from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "rolling90"
OUT = DATA / "profuturo_spy_qqq_windows.json"
TRAIN_WINDOW = 90
THRESHOLD = 0.001
HORIZONS = [30, 60, 90, 180]

COMMON_FEATURES = [
    "ret_NEM",
    "ret_FCX",
    "ret_EPU",
    "ret_MCHI",
    "ret_EEM",
    "ret_USD_PEN",
]
VARIANTS = {
    "SPY": ["ret_SPY", *COMMON_FEATURES],
    "QQQ": ["ret_QQQ", *COMMON_FEATURES],
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
    qqq = pd.DataFrame({"fecha": idx.normalize(), "QQQ": close.to_numpy(float)})
    qqq = qqq.sort_values("fecha").drop_duplicates("fecha", keep="last")
    qqq["ret_QQQ"] = qqq["QQQ"].pct_change(fill_method=None)
    return qqq[["fecha", "QQQ", "ret_QQQ"]]


def fit_predict(train: pd.DataFrame, row: pd.Series, features: list[str]) -> float:
    x = train[features].to_numpy(float)
    y = train["ret_target"].to_numpy(float)
    beta = np.linalg.lstsq(np.c_[np.ones(len(x)), x], y, rcond=None)[0]
    return float(np.r_[1.0, row[features].to_numpy(float)] @ beta)


def build_predictions(frame: pd.DataFrame, features: list[str]) -> pd.DataFrame:
    rows: list[dict] = []
    for i in range(TRAIN_WINDOW, len(frame)):
        train = frame.iloc[i - TRAIN_WINDOW : i]
        current = frame.iloc[i]
        pred = fit_predict(train, current, features)
        actual = float(current["ret_target"])
        rows.append(
            {
                "fecha": current["fecha"],
                "pred": pred,
                "actual": actual,
                "pred_class": classify(pred),
                "actual_class": classify(actual),
            }
        )
    return pd.DataFrame(rows)


def metrics(pred: pd.DataFrame) -> dict:
    p = pred["pred"].to_numpy(float)
    y = pred["actual"].to_numpy(float)
    err = p - y
    corr = float(np.corrcoef(p, y)[0, 1]) if len(y) > 2 and np.std(p) > 0 and np.std(y) > 0 else None
    return {
        "n": int(len(pred)),
        "start": pred.iloc[0]["fecha"].strftime("%Y-%m-%d"),
        "end": pred.iloc[-1]["fecha"].strftime("%Y-%m-%d"),
        "mae": float(np.mean(np.abs(err))),
        "rmse": float(np.sqrt(np.mean(err ** 2))),
        "direction_accuracy": float((pred["pred_class"] == pred["actual_class"]).mean()),
        "pred_actual_corr": corr,
    }


def compare_window(spy: pd.DataFrame, qqq: pd.DataFrame, horizon: int) -> dict:
    s = spy.tail(horizon).reset_index(drop=True)
    q = qqq.tail(horizon).reset_index(drop=True)
    if not s["fecha"].equals(q["fecha"]):
        raise RuntimeError(f"Las fechas SPY/QQQ no coinciden en ventana {horizon}.")
    sm = metrics(s)
    qm = metrics(q)
    mae_winner = "QQQ" if qm["mae"] < sm["mae"] else "SPY"
    accuracy_winner = "QQQ" if qm["direction_accuracy"] > sm["direction_accuracy"] else ("SPY" if sm["direction_accuracy"] > qm["direction_accuracy"] else "EMPATE")
    return {
        "SPY": sm,
        "QQQ": qm,
        "winner_mae": mae_winner,
        "winner_direction": accuracy_winner,
        "qqq_mae_change_vs_spy": float(qm["mae"] / sm["mae"] - 1.0),
        "qqq_accuracy_delta_pp": float((qm["direction_accuracy"] - sm["direction_accuracy"]) * 100.0),
    }


def main() -> None:
    markets = read_csv(DATA / "markets.csv")
    sbs = read_csv(DATA / "sbs_profuturo_f3.csv")
    sbs["valor_cuota"] = pd.to_numeric(sbs["valor_cuota"], errors="coerce")
    sbs = sbs.dropna(subset=["valor_cuota"]).drop_duplicates("fecha", keep="last")
    sbs["ret_target"] = sbs["valor_cuota"].pct_change(fill_method=None)

    qqq = download_qqq(markets["fecha"].min(), max(markets["fecha"].max(), pd.Timestamp.now().normalize()))
    markets = markets.merge(qqq, on="fecha", how="left")

    required = ["ret_target", "ret_SPY", "ret_QQQ", *COMMON_FEATURES]
    frame = sbs[["fecha", "ret_target"]].merge(markets, on="fecha", how="inner")
    frame = frame.loc[frame["fecha"] >= pd.Timestamp("2025-01-01")]
    frame = frame.dropna(subset=required).sort_values("fecha").drop_duplicates("fecha", keep="last").reset_index(drop=True)
    if len(frame) <= TRAIN_WINDOW + max(HORIZONS):
        raise RuntimeError(f"Solo hay {len(frame)} filas completas; insuficiente para ventana 180 con training 90.")

    predictions = {
        name: build_predictions(frame, features)
        for name, features in VARIANTS.items()
    }
    if not predictions["SPY"]["fecha"].equals(predictions["QQQ"]["fecha"]):
        raise RuntimeError("Las predicciones SPY y QQQ no tienen las mismas fechas.")

    windows = {
        str(h): compare_window(predictions["SPY"], predictions["QQQ"], h)
        for h in HORIZONS
    }
    all_n = len(predictions["SPY"])
    windows["ALL"] = compare_window(predictions["SPY"], predictions["QQQ"], all_n)

    qqq_mae_wins = sum(windows[str(h)]["winner_mae"] == "QQQ" for h in HORIZONS)
    qqq_direction_wins = sum(windows[str(h)]["winner_direction"] == "QQQ" for h in HORIZONS)
    payload = {
        "generated_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "fund": "PROFUTURO",
        "model_rule": "Mismo OLS rolling 90 del visor; EPU, EEM, NEM, FCX, MCHI y USD/PEN constantes. Único cambio: SPY versus QQQ. Las ventanas 30/60/90/180 son periodos recientes de evaluación fuera de muestra; el entrenamiento sigue siendo siempre 90.",
        "common_complete_rows": int(len(frame)),
        "prediction_rows": int(all_n),
        "first_prediction": predictions["SPY"].iloc[0]["fecha"].strftime("%Y-%m-%d"),
        "last_prediction": predictions["SPY"].iloc[-1]["fecha"].strftime("%Y-%m-%d"),
        "windows": windows,
        "stability": {
            "qqq_mae_wins_out_of_4": qqq_mae_wins,
            "qqq_direction_wins_out_of_4": qqq_direction_wins,
            "recommendation": (
                "REPLACE_SPY_WITH_QQQ" if qqq_mae_wins >= 3 and qqq_direction_wins >= 2
                else "KEEP_QQQ_AS_CHALLENGER"
            ),
        },
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
