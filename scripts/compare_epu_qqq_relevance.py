from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "rolling90"
OUT = DATA / "epu_qqq_relevance.json"
WINDOW = 90
THRESHOLD = 0.001

# Prueba marginal sobre la arquitectura actual: SPY y los demás factores se mantienen.
BASE_FEATURES = [
    "ret_SPY",
    "ret_NEM",
    "ret_FCX",
    "ret_MCHI",
    "ret_EEM",
    "ret_USD_PEN",
]
VARIANTS = {
    "BASE_SIN_EPU_QQQ": BASE_FEATURES,
    "EPU": [*BASE_FEATURES, "ret_EPU"],
    "QQQ": [*BASE_FEATURES, "ret_QQQ"],
    "EPU_QQQ": [*BASE_FEATURES, "ret_EPU", "ret_QQQ"],
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
    raise RuntimeError("Yahoo no devolvió Close utilizable para QQQ.")


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
        raise RuntimeError("No hay suficientes observaciones para rolling 90.")
    err = p - y
    return {
        "n_predictions": int(len(y)),
        "mae": float(np.mean(np.abs(err))),
        "rmse": float(np.sqrt(np.mean(err ** 2))),
        "direction_accuracy": float(np.mean([classify(a) == classify(b) for a, b in zip(p, y)])),
        "pred_actual_corr": float(np.corrcoef(p, y)[0, 1]) if len(y) > 2 and np.std(p) > 0 and np.std(y) > 0 else None,
    }


def standardized_beta_recent(frame: pd.DataFrame) -> dict:
    train = frame.tail(WINDOW).copy()
    features = VARIANTS["EPU_QQQ"]
    x = train[features].to_numpy(float)
    y = train["ret_target"].to_numpy(float)
    xs = x.std(axis=0, ddof=0)
    ys = y.std(ddof=0)
    xz = (x - x.mean(axis=0)) / np.where(xs == 0, 1.0, xs)
    yz = (y - y.mean()) / (ys if ys else 1.0)
    beta = np.linalg.lstsq(np.c_[np.ones(len(xz)), xz], yz, rcond=None)[0][1:]
    mapping = {name: float(value) for name, value in zip(features, beta)}
    return {
        "epu": mapping["ret_EPU"],
        "qqq": mapping["ret_QQQ"],
        "abs_epu": abs(mapping["ret_EPU"]),
        "abs_qqq": abs(mapping["ret_QQQ"]),
    }


def analyze_fund(name: str, sbs_path: Path, markets: pd.DataFrame) -> dict:
    sbs = read_csv(sbs_path)
    sbs["valor_cuota"] = pd.to_numeric(sbs["valor_cuota"], errors="coerce")
    sbs = sbs.dropna(subset=["valor_cuota"]).drop_duplicates("fecha", keep="last")
    sbs["ret_target"] = sbs["valor_cuota"].pct_change(fill_method=None)

    required = ["ret_target", *BASE_FEATURES, "ret_EPU", "ret_QQQ"]
    frame = sbs[["fecha", "ret_target"]].merge(markets, on="fecha", how="inner")
    frame = frame.loc[frame["fecha"] >= pd.Timestamp("2025-01-01")]
    frame = frame.dropna(subset=required).sort_values("fecha").drop_duplicates("fecha", keep="last").reset_index(drop=True)
    if len(frame) <= WINDOW + 10:
        raise RuntimeError(f"{name}: solo {len(frame)} filas completas.")

    metrics = {key: rolling_metrics(frame, features) for key, features in VARIANTS.items()}
    base_mae = metrics["BASE_SIN_EPU_QQQ"]["mae"]
    for key in ("EPU", "QQQ", "EPU_QQQ"):
        metrics[key]["mae_improvement_vs_base"] = 1.0 - metrics[key]["mae"] / base_mae if base_mae > 0 else None

    recent = frame.tail(WINDOW)
    winner = min(("EPU", "QQQ", "EPU_QQQ"), key=lambda key: metrics[key]["mae"])
    return {
        "fund": name,
        "common_complete_rows": int(len(frame)),
        "first_date": frame.iloc[0]["fecha"].strftime("%Y-%m-%d"),
        "last_date": frame.iloc[-1]["fecha"].strftime("%Y-%m-%d"),
        "target_corr_full": {
            "EPU": float(frame["ret_target"].corr(frame["ret_EPU"])),
            "QQQ": float(frame["ret_target"].corr(frame["ret_QQQ"])),
        },
        "target_corr_recent_90": {
            "EPU": float(recent["ret_target"].corr(recent["ret_EPU"])),
            "QQQ": float(recent["ret_target"].corr(recent["ret_QQQ"])),
        },
        "epu_qqq_return_corr": float(frame["ret_EPU"].corr(frame["ret_QQQ"])),
        "standardized_beta_both_recent_90": standardized_beta_recent(frame),
        "rolling_90": metrics,
        "winner_by_mae": winner,
        "qqq_mae_advantage_vs_epu": (
            (metrics["EPU"]["mae"] - metrics["QQQ"]["mae"]) / metrics["EPU"]["mae"]
            if metrics["EPU"]["mae"] > 0 else None
        ),
    }


def recommendation(results: dict[str, dict]) -> dict:
    qqq_better = all(r["rolling_90"]["QQQ"]["mae"] < r["rolling_90"]["EPU"]["mae"] for r in results.values())
    epu_better = all(r["rolling_90"]["EPU"]["mae"] < r["rolling_90"]["QQQ"]["mae"] for r in results.values())
    both_best = all(r["winner_by_mae"] == "EPU_QQQ" for r in results.values())
    if both_best:
        return {"action": "KEEP_EPU_AND_ADD_QQQ", "summary": "EPU y QQQ juntos producen el menor MAE en ambos fondos; aportan información complementaria."}
    if qqq_better:
        return {"action": "QQQ_MORE_RELEVANT_THAN_EPU", "summary": "QQQ reduce más el MAE que EPU en ambos fondos al mantener constantes los demás factores del modelo."}
    if epu_better:
        return {"action": "EPU_MORE_RELEVANT_THAN_QQQ", "summary": "EPU reduce más el MAE que QQQ en ambos fondos al mantener constantes los demás factores."}
    return {"action": "MIXED", "summary": "La relevancia EPU vs QQQ difiere entre Profuturo y Hábitat; no conviene sustituir uno por otro con esta evidencia."}


def main() -> None:
    markets = read_csv(DATA / "markets.csv")
    qqq = download_qqq(markets["fecha"].min(), max(markets["fecha"].max(), pd.Timestamp.now().normalize()))
    markets = markets.merge(qqq, on="fecha", how="left")
    results = {
        "PROFUTURO": analyze_fund("PROFUTURO", DATA / "sbs_profuturo_f3.csv", markets),
        "HABITAT": analyze_fund("HABITAT", DATA / "sbs_habitat_f3.csv", markets),
    }
    payload = {
        "generated_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "nasdaq_proxy": "QQQ (Nasdaq-100 ETF, Yahoo Finance Close, auto_adjust=False)",
        "method": "Prueba marginal sobre el modelo actual OLS rolling 90: se mantienen SPY, NEM, FCX, MCHI, EEM y USD/PEN. Se compara añadir EPU, añadir QQQ o añadir ambos, usando las mismas fechas y el mismo objetivo SBS.",
        "results": results,
        "recommendation": recommendation(results),
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
