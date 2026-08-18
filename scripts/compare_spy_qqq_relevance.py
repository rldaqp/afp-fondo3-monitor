from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "rolling90"
OUT = DATA / "spy_qqq_relevance.json"
WINDOW = 90
THRESHOLD = 0.001

OTHER_FEATURES = [
    "ret_NEM",
    "ret_FCX",
    "ret_EPU",
    "ret_MCHI",
    "ret_EEM",
    "ret_USD_PEN",
]
VARIANTS = {
    "NEITHER": OTHER_FEATURES,
    "SPY": ["ret_SPY", *OTHER_FEATURES],
    "QQQ": ["ret_QQQ", *OTHER_FEATURES],
    "BOTH": ["ret_SPY", "ret_QQQ", *OTHER_FEATURES],
}


def classify(value: float) -> str:
    if value > THRESHOLD:
        return "SUBE"
    if value < -THRESHOLD:
        return "BAJA"
    return "NEUTRO"


def read_csv(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    frame["fecha"] = pd.to_datetime(frame["fecha"], errors="coerce")
    return frame.dropna(subset=["fecha"]).sort_values("fecha").reset_index(drop=True)


def extract_close(raw: pd.DataFrame, ticker: str) -> pd.Series:
    if raw.empty:
        return pd.Series(dtype=float)
    if isinstance(raw.columns, pd.MultiIndex):
        for key in [("Close", ticker), (ticker, "Close")]:
            if key in raw.columns:
                return pd.to_numeric(raw[key], errors="coerce")
        close_cols = [col for col in raw.columns if "Close" in col]
        if close_cols:
            return pd.to_numeric(raw[close_cols[0]], errors="coerce")
    if "Close" in raw.columns:
        return pd.to_numeric(raw["Close"], errors="coerce")
    raise RuntimeError("Yahoo no devolvió una columna Close utilizable para QQQ.")


def download_qqq(start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    raw = yf.download(
        "QQQ",
        start=(start - pd.Timedelta(days=10)).strftime("%Y-%m-%d"),
        end=(end + pd.Timedelta(days=3)).strftime("%Y-%m-%d"),
        auto_adjust=False,
        actions=False,
        progress=False,
        threads=False,
    )
    close = extract_close(raw, "QQQ").dropna()
    if close.empty:
        raise RuntimeError("No se pudo descargar QQQ desde Yahoo Finance.")
    idx = pd.to_datetime(close.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    frame = pd.DataFrame({"fecha": idx.normalize(), "QQQ": close.to_numpy(float)})
    frame = frame.sort_values("fecha").drop_duplicates("fecha", keep="last")
    frame["ret_QQQ"] = frame["QQQ"].pct_change(fill_method=None)
    return frame[["fecha", "QQQ", "ret_QQQ"]]


def fit_predict(train: pd.DataFrame, row: pd.Series, features: list[str]) -> float:
    x = train[features].to_numpy(float)
    y = train["ret_target"].to_numpy(float)
    beta = np.linalg.lstsq(np.c_[np.ones(len(x)), x], y, rcond=None)[0]
    return float(np.r_[1.0, row[features].to_numpy(float)] @ beta)


def rolling_metrics(frame: pd.DataFrame, features: list[str]) -> dict:
    predictions: list[float] = []
    actuals: list[float] = []
    for i in range(WINDOW, len(frame)):
        train = frame.iloc[i - WINDOW : i]
        current = frame.iloc[i]
        predictions.append(fit_predict(train, current, features))
        actuals.append(float(current["ret_target"]))
    p = np.asarray(predictions, dtype=float)
    y = np.asarray(actuals, dtype=float)
    if len(y) == 0:
        raise RuntimeError("No hay suficientes observaciones para evaluación rolling 90.")
    err = p - y
    accuracy = float(np.mean([classify(a) == classify(b) for a, b in zip(p, y)]))
    corr = float(np.corrcoef(p, y)[0, 1]) if len(y) > 2 and np.std(p) > 0 and np.std(y) > 0 else None
    return {
        "n_predictions": int(len(y)),
        "mae": float(np.mean(np.abs(err))),
        "rmse": float(np.sqrt(np.mean(err ** 2))),
        "direction_accuracy": accuracy,
        "pred_actual_corr": corr,
    }


def standardized_current_beta(frame: pd.DataFrame) -> dict:
    train = frame.tail(WINDOW).copy()
    features = VARIANTS["BOTH"]
    x = train[features].to_numpy(float)
    y = train["ret_target"].to_numpy(float)
    x_mean = x.mean(axis=0)
    x_std = x.std(axis=0, ddof=0)
    y_std = y.std(ddof=0)
    safe = np.where(x_std == 0, 1.0, x_std)
    xz = (x - x_mean) / safe
    yz = (y - y.mean()) / (y_std if y_std else 1.0)
    beta = np.linalg.lstsq(np.c_[np.ones(len(xz)), xz], yz, rcond=None)[0][1:]
    mapping = {name: float(value) for name, value in zip(features, beta)}
    return {
        "spy": mapping["ret_SPY"],
        "qqq": mapping["ret_QQQ"],
        "abs_spy": abs(mapping["ret_SPY"]),
        "abs_qqq": abs(mapping["ret_QQQ"]),
    }


def analyze_fund(name: str, sbs_path: Path, markets: pd.DataFrame) -> dict:
    sbs = read_csv(sbs_path)
    sbs["valor_cuota"] = pd.to_numeric(sbs["valor_cuota"], errors="coerce")
    sbs = sbs.dropna(subset=["valor_cuota"]).drop_duplicates("fecha", keep="last")
    sbs["ret_target"] = sbs["valor_cuota"].pct_change(fill_method=None)

    required = ["ret_target", "ret_SPY", "ret_QQQ", *OTHER_FEATURES]
    frame = sbs[["fecha", "ret_target"]].merge(markets, on="fecha", how="inner")
    frame = frame.loc[frame["fecha"] >= pd.Timestamp("2025-01-01")]
    frame = frame.dropna(subset=required).sort_values("fecha").drop_duplicates("fecha", keep="last").reset_index(drop=True)
    if len(frame) <= WINDOW + 10:
        raise RuntimeError(f"{name}: solo {len(frame)} filas comunes completas; insuficiente para el contraste.")

    metrics = {key: rolling_metrics(frame, features) for key, features in VARIANTS.items()}
    base_mae = metrics["NEITHER"]["mae"]
    for key in ("SPY", "QQQ", "BOTH"):
        metrics[key]["mae_improvement_vs_neither"] = (
            1.0 - metrics[key]["mae"] / base_mae if base_mae > 0 else None
        )

    spy_qqq_corr = float(frame["ret_SPY"].corr(frame["ret_QQQ"]))
    target_spy_corr = float(frame["ret_target"].corr(frame["ret_SPY"]))
    target_qqq_corr = float(frame["ret_target"].corr(frame["ret_QQQ"]))
    recent = frame.tail(WINDOW)
    recent_target_spy_corr = float(recent["ret_target"].corr(recent["ret_SPY"]))
    recent_target_qqq_corr = float(recent["ret_target"].corr(recent["ret_QQQ"]))

    candidates = ["SPY", "QQQ", "BOTH"]
    winner = min(candidates, key=lambda key: metrics[key]["mae"])
    spy_mae = metrics["SPY"]["mae"]
    qqq_mae = metrics["QQQ"]["mae"]
    relative_qqq_vs_spy = (spy_mae - qqq_mae) / spy_mae if spy_mae > 0 else 0.0

    return {
        "fund": name,
        "common_complete_rows": int(len(frame)),
        "first_date": frame.iloc[0]["fecha"].strftime("%Y-%m-%d"),
        "last_date": frame.iloc[-1]["fecha"].strftime("%Y-%m-%d"),
        "spy_qqq_return_corr": spy_qqq_corr,
        "target_corr_full": {"SPY": target_spy_corr, "QQQ": target_qqq_corr},
        "target_corr_recent_90": {"SPY": recent_target_spy_corr, "QQQ": recent_target_qqq_corr},
        "standardized_beta_both_recent_90": standardized_current_beta(frame),
        "rolling_90": metrics,
        "winner_by_mae": winner,
        "qqq_mae_advantage_vs_spy": relative_qqq_vs_spy,
    }


def recommendation(results: dict[str, dict]) -> dict:
    prof = results["PROFUTURO"]
    hab = results["HABITAT"]
    winners = {prof["winner_by_mae"], hab["winner_by_mae"]}
    qqq_better_both = (
        prof["rolling_90"]["QQQ"]["mae"] < prof["rolling_90"]["SPY"]["mae"]
        and hab["rolling_90"]["QQQ"]["mae"] < hab["rolling_90"]["SPY"]["mae"]
    )
    spy_better_both = (
        prof["rolling_90"]["SPY"]["mae"] < prof["rolling_90"]["QQQ"]["mae"]
        and hab["rolling_90"]["SPY"]["mae"] < hab["rolling_90"]["QQQ"]["mae"]
    )
    if qqq_better_both:
        action = "REPLACE_SPY_WITH_QQQ"
        summary = "QQQ aporta menor MAE rolling 90 que SPY en ambos fondos; conviene usar Nasdaq-100 como factor principal de mercado USA."
    elif spy_better_both:
        action = "KEEP_SPY"
        summary = "SPY mantiene menor MAE rolling 90 que QQQ en ambos fondos; Nasdaq debe quedar como challenger, no reemplazar a SPY."
    elif winners == {"BOTH"}:
        action = "KEEP_BOTH_WITH_COLLINEARITY_WARNING"
        summary = "La combinación SPY+QQQ es la mejor en ambos fondos, pero deben vigilarse coeficientes por alta colinealidad."
    else:
        action = "KEEP_CHALLENGER"
        summary = "La evidencia difiere entre Profuturo y Hábitat; no conviene reemplazar SPY todavía. Mantener QQQ como challenger y seguir acumulando observaciones."
    return {"action": action, "summary": summary}


def main() -> None:
    markets = read_csv(DATA / "markets.csv")
    start = markets["fecha"].min()
    end = max(markets["fecha"].max(), pd.Timestamp.now().normalize())
    qqq = download_qqq(start, end)
    markets = markets.merge(qqq, on="fecha", how="left")

    results = {
        "PROFUTURO": analyze_fund("PROFUTURO", DATA / "sbs_profuturo_f3.csv", markets),
        "HABITAT": analyze_fund("HABITAT", DATA / "sbs_habitat_f3.csv", markets),
    }
    payload = {
        "generated_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "nasdaq_proxy": "QQQ (Nasdaq-100 ETF, Yahoo Finance Close, auto_adjust=False)",
        "method": (
            "Comparación justa con las mismas fechas completas: OLS rolling 90. Se evalúan cuatro variantes: "
            "sin SPY/QQQ, SPY, QQQ y ambos. Criterio principal: MAE fuera de muestra; también se reportan "
            "acierto direccional, correlaciones y beta estandarizado reciente."
        ),
        "results": results,
        "recommendation": recommendation(results),
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
