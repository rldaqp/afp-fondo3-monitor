from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "rolling90"
OUT = ROOT / "analysis" / "custom_no_nem_fcx_20260819.json"

WINDOW = 90
TARGET_DATE = pd.Timestamp("2026-08-19")
THRESHOLD = 0.001
EXCLUDED_RETURN_DATES = {pd.Timestamp("2026-07-06")}
BASE_FEATURES = ["ret_SPY", "ret_EEM", "ret_EPU", "ret_MCHI", "ret_USD_PEN"]


def classify(value: float) -> str:
    if value > THRESHOLD:
        return "SUBE"
    if value < -THRESHOLD:
        return "BAJA"
    return "NEUTRO"


def read_csv(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    frame["fecha"] = pd.to_datetime(frame["fecha"], errors="coerce")
    return frame.dropna(subset=["fecha"]).sort_values("fecha").drop_duplicates("fecha", keep="last").reset_index(drop=True)


def extract_close(raw: pd.DataFrame, ticker: str) -> pd.Series:
    if raw.empty:
        return pd.Series(dtype=float)
    if isinstance(raw.columns, pd.MultiIndex):
        for key in [("Close", ticker), (ticker, "Close")]:
            if key in raw.columns:
                return pd.to_numeric(raw[key], errors="coerce").dropna()
        if "Close" in raw.columns.get_level_values(0):
            block = raw.xs("Close", axis=1, level=0)
            if ticker in block.columns:
                return pd.to_numeric(block[ticker], errors="coerce").dropna()
    if "Close" in raw.columns:
        return pd.to_numeric(raw["Close"], errors="coerce").dropna()
    return pd.Series(dtype=float)


def load_qqq() -> pd.DataFrame:
    raw = yf.download(
        "QQQ",
        start="2024-12-30",
        end="2026-08-21",
        auto_adjust=False,
        actions=False,
        progress=False,
        threads=False,
    )
    close = extract_close(raw, "QQQ")
    if close.empty:
        raise RuntimeError("Yahoo Finance no devolvió QQQ")
    idx = pd.to_datetime(close.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    qqq = pd.DataFrame({"fecha": idx.normalize(), "QQQ": close.to_numpy(float)})
    qqq = qqq.sort_values("fecha").drop_duplicates("fecha", keep="last")
    qqq["ret_QQQ"] = qqq["QQQ"].pct_change(fill_method=None)
    return qqq


def fit_ols(train: pd.DataFrame, features: list[str], target: str = "ret_target") -> np.ndarray:
    x = train[features].to_numpy(float)
    y = train[target].to_numpy(float)
    return np.linalg.lstsq(np.c_[np.ones(len(x)), x], y, rcond=None)[0]


def predict(beta: np.ndarray, row: pd.Series, features: list[str]) -> float:
    return float(np.r_[1.0, row[features].to_numpy(float)] @ beta)


def main() -> None:
    markets = read_csv(DATA / "markets.csv")
    sbs = read_csv(DATA / "sbs_profuturo_f3.csv")
    qqq = load_qqq()

    sbs["valor_cuota"] = pd.to_numeric(sbs["valor_cuota"], errors="coerce")
    sbs = sbs.dropna(subset=["valor_cuota"]).copy()
    sbs["ret_target"] = sbs["valor_cuota"].pct_change(fill_method=None)
    for date_value in EXCLUDED_RETURN_DATES:
        sbs.loc[sbs["fecha"].eq(date_value), "ret_target"] = np.nan

    all_data = (
        sbs[["fecha", "valor_cuota", "ret_target"]]
        .merge(markets[["fecha", *BASE_FEATURES]], on="fecha", how="inner")
        .merge(qqq[["fecha", "ret_QQQ"]], on="fecha", how="inner")
        .loc[lambda x: x["fecha"] < TARGET_DATE]
        .dropna(subset=["ret_target", *BASE_FEATURES, "ret_QQQ"])
        .sort_values("fecha")
        .drop_duplicates("fecha", keep="last")
        .reset_index(drop=True)
    )
    if len(all_data) < WINDOW:
        raise RuntimeError(f"Solo hay {len(all_data)} filas completas; se requieren {WINDOW}")
    train = all_data.tail(WINDOW).copy()

    current = (
        markets.loc[markets["fecha"].eq(TARGET_DATE), ["fecha", *BASE_FEATURES]]
        .merge(qqq.loc[qqq["fecha"].eq(TARGET_DATE), ["fecha", "ret_QQQ"]], on="fecha", how="inner")
    )
    if current.empty or current[[*BASE_FEATURES, "ret_QQQ"]].isna().any(axis=None):
        raise RuntimeError("Faltan factores completos del 2026-08-19")
    current_row = current.iloc[0]

    base_sbs = sbs.loc[sbs["fecha"] < TARGET_DATE].dropna(subset=["valor_cuota"]).sort_values("fecha").iloc[-1]
    base_vc = float(base_sbs["valor_cuota"])
    base_date = pd.Timestamp(base_sbs["fecha"])

    # Variante 1: sin NEM, sin FCX y sin QQQ.
    beta_base = fit_ols(train, BASE_FEATURES)
    ret_no_qqq = predict(beta_base, current_row, BASE_FEATURES)
    vc_no_qqq = base_vc * (1.0 + ret_no_qqq)

    # Variante 2: sin NEM/FCX + QQQ incremental. La residualización se estima
    # solamente en las 90 filas de entrenamiento para evitar leakage.
    x = train[BASE_FEATURES].to_numpy(float)
    q = train["ret_QQQ"].to_numpy(float)
    q_beta = np.linalg.lstsq(np.c_[np.ones(len(x)), x], q, rcond=None)[0]
    train["ret_QQQ_resid"] = q - np.c_[np.ones(len(x)), x] @ q_beta
    qqq_expected = float(np.r_[1.0, current_row[BASE_FEATURES].to_numpy(float)] @ q_beta)
    qqq_resid_current = float(current_row["ret_QQQ"] - qqq_expected)

    qqq_features = BASE_FEATURES + ["ret_QQQ_resid"]
    beta_qqq = fit_ols(train, qqq_features)
    current_qqq = current_row.copy()
    current_qqq["ret_QQQ_resid"] = qqq_resid_current
    ret_with_qqq = predict(beta_qqq, current_qqq, qqq_features)
    vc_with_qqq = base_vc * (1.0 + ret_with_qqq)

    payload = {
        "fund": "PROFUTURO Fondo 3",
        "target_date": TARGET_DATE.strftime("%Y-%m-%d"),
        "base_vc_date": base_date.strftime("%Y-%m-%d"),
        "base_vc": base_vc,
        "training": {
            "n": WINDOW,
            "start": train.iloc[0]["fecha"].strftime("%Y-%m-%d"),
            "end": train.iloc[-1]["fecha"].strftime("%Y-%m-%d"),
            "features_common": BASE_FEATURES,
            "excluded": ["ret_NEM", "ret_FCX"],
        },
        "market_returns_target_date": {feature: float(current_row[feature]) for feature in BASE_FEATURES},
        "qqq": {
            "return": float(current_row["ret_QQQ"]),
            "expected_from_base_factors": qqq_expected,
            "residual_incremental": qqq_resid_current,
        },
        "without_qqq": {
            "return_estimated": ret_no_qqq,
            "signal": classify(ret_no_qqq),
            "vc_estimated": vc_no_qqq,
        },
        "with_qqq_incremental": {
            "return_estimated": ret_with_qqq,
            "signal": classify(ret_with_qqq),
            "vc_estimated": vc_with_qqq,
        },
        "difference_with_minus_without": {
            "return_pp": (ret_with_qqq - ret_no_qqq) * 100.0,
            "vc": vc_with_qqq - vc_no_qqq,
        },
        "method": "OLS rolling 90. Ambas variantes excluyen NEM y FCX. La variante QQQ usa QQQ residualizado dentro de la misma ventana de 90 contra SPY, EEM, EPU, MCHI y USD/PEN.",
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
