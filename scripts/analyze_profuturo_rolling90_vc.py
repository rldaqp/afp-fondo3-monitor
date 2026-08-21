from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "rolling90"
OUT = ROOT / "analysis" / "profuturo_rolling90_vc_validation.json"
PRED_OUT = ROOT / "analysis" / "profuturo_rolling90_vc_predictions.csv"

WINDOW = 90
THRESHOLD = 0.001
TARGET_END = pd.Timestamp("2026-08-20")
FEATURES = ["ret_SPY", "ret_EEM", "ret_EPU", "ret_MCHI", "ret_USD_PEN", "ret_QQQ"]


def classify(x: float) -> str:
    if x > THRESHOLD:
        return "SUBE"
    if x < -THRESHOLD:
        return "BAJA"
    return "NEUTRO"


def read_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce")
    return df.dropna(subset=["fecha"]).sort_values("fecha").drop_duplicates("fecha", keep="last").reset_index(drop=True)


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
    raise RuntimeError("Yahoo no devolvió Close utilizable para QQQ")


def load_qqq(start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    raw = yf.download(
        "QQQ",
        start=(start - pd.Timedelta(days=10)).strftime("%Y-%m-%d"),
        end=(end + pd.Timedelta(days=2)).strftime("%Y-%m-%d"),
        auto_adjust=False,
        actions=False,
        progress=False,
        threads=False,
    )
    close = extract_close(raw, "QQQ")
    idx = pd.to_datetime(close.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    q = pd.DataFrame({"fecha": idx.normalize(), "QQQ": close.to_numpy(float)})
    q = q.sort_values("fecha").drop_duplicates("fecha", keep="last")
    q["ret_QQQ"] = q["QQQ"].pct_change(fill_method=None)
    return q[["fecha", "QQQ", "ret_QQQ"]]


def fit_ols(train: pd.DataFrame) -> np.ndarray:
    x = train[FEATURES].to_numpy(float)
    y = train["ret_target"].to_numpy(float)
    return np.linalg.lstsq(np.c_[np.ones(len(x)), x], y, rcond=None)[0]


def predict(beta: np.ndarray, row: pd.Series) -> float:
    return float(np.r_[1.0, row[FEATURES].to_numpy(float)] @ beta)


def vif_table(train: pd.DataFrame) -> dict:
    x = train[FEATURES].to_numpy(float)
    out = {}
    for j, name in enumerate(FEATURES):
        y = x[:, j]
        others = np.delete(x, j, axis=1)
        d = np.c_[np.ones(len(others)), others]
        b = np.linalg.lstsq(d, y, rcond=None)[0]
        fitted = d @ b
        ss_res = float(np.sum((y - fitted) ** 2))
        ss_tot = float(np.sum((y - y.mean()) ** 2))
        r2 = 1.0 - ss_res / ss_tot if ss_tot > 1e-20 else 1.0
        out[name] = float(1.0 / max(1e-12, 1.0 - r2))
    return {"by_feature": out, "max_vif": max(out.values()), "max_vif_feature": max(out, key=out.get)}


def metric_block(pred: pd.DataFrame) -> dict:
    actual_ret = pred["actual_return"].to_numpy(float)
    pred_ret = pred["pred_return"].to_numpy(float)
    actual_vc = pred["actual_vc"].to_numpy(float)
    est_vc = pred["pred_vc"].to_numpy(float)
    prev_vc = pred["prev_vc"].to_numpy(float)
    err_vc = est_vc - actual_vc
    rel = np.abs(err_vc) / actual_vc
    naive_rmse = float(np.sqrt(np.mean((prev_vc - actual_vc) ** 2)))
    rmse = float(np.sqrt(np.mean(err_vc ** 2)))
    den = float(np.sum((actual_ret - actual_ret.mean()) ** 2))
    r2 = None if den <= 1e-20 else float(1.0 - np.sum((pred_ret - actual_ret) ** 2) / den)
    corr = None if np.std(pred_ret) == 0 or np.std(actual_ret) == 0 else float(np.corrcoef(pred_ret, actual_ret)[0, 1])
    return {
        "n": int(len(pred)),
        "start": pred.iloc[0]["fecha"].strftime("%Y-%m-%d"),
        "end": pred.iloc[-1]["fecha"].strftime("%Y-%m-%d"),
        "vc_mae": float(np.mean(np.abs(err_vc))),
        "vc_rmse": rmse,
        "vc_mape_pct": float(np.mean(rel) * 100.0),
        "vc_bias": float(np.mean(err_vc)),
        "within_0_5pct": float(np.mean(rel <= 0.005)),
        "within_1pct": float(np.mean(rel <= 0.01)),
        "direction_accuracy": float(np.mean(pred["pred_signal"].to_numpy() == pred["actual_signal"].to_numpy())),
        "return_mae": float(np.mean(np.abs(pred_ret - actual_ret))),
        "return_rmse": float(np.sqrt(np.mean((pred_ret - actual_ret) ** 2))),
        "oos_r2_return": r2,
        "pred_actual_return_corr": corr,
        "naive_vc_rmse": naive_rmse,
        "theil_u_vs_no_change": None if naive_rmse <= 0 else float(rmse / naive_rmse),
    }


def main() -> None:
    markets = read_csv(DATA / "markets.csv")
    sbs = read_csv(DATA / "sbs_profuturo_f3.csv")
    sbs["valor_cuota"] = pd.to_numeric(sbs["valor_cuota"], errors="coerce")
    sbs = sbs.dropna(subset=["valor_cuota"]).copy()
    sbs["prev_vc"] = sbs["valor_cuota"].shift(1)
    sbs["ret_target"] = sbs["valor_cuota"].pct_change(fill_method=None)

    qqq = load_qqq(markets["fecha"].min(), TARGET_END)
    marketq = markets.merge(qqq[["fecha", "QQQ", "ret_QQQ"]], on="fecha", how="left")

    real = sbs[["fecha", "valor_cuota", "prev_vc", "ret_target"]].merge(
        marketq[["fecha", "ret_SPY", "ret_EEM", "ret_EPU", "ret_MCHI", "ret_USD_PEN", "ret_QQQ"]],
        on="fecha", how="inner"
    )
    real = real.loc[real["fecha"] >= pd.Timestamp("2025-01-01")]
    real = real.dropna(subset=["valor_cuota", "prev_vc", "ret_target", *FEATURES]).sort_values("fecha").drop_duplicates("fecha", keep="last").reset_index(drop=True)
    if len(real) <= WINDOW:
        raise RuntimeError("Muestra insuficiente")

    rows = []
    for i in range(WINDOW, len(real)):
        train = real.iloc[i-WINDOW:i].copy()
        current = real.iloc[i]
        beta = fit_ols(train)
        pred_ret = predict(beta, current)
        pred_vc = float(current["prev_vc"] * (1.0 + pred_ret))
        actual_ret = float(current["ret_target"])
        rows.append({
            "fecha": current["fecha"],
            "prev_vc": float(current["prev_vc"]),
            "actual_vc": float(current["valor_cuota"]),
            "pred_vc": pred_vc,
            "actual_return": actual_ret,
            "pred_return": pred_ret,
            "actual_signal": classify(actual_ret),
            "pred_signal": classify(pred_ret),
            "train_start": train.iloc[0]["fecha"],
            "train_end": train.iloc[-1]["fecha"],
        })
    preds = pd.DataFrame(rows)

    metrics = {
        "recent_60": metric_block(preds.tail(60).reset_index(drop=True)),
        "recent_90": metric_block(preds.tail(90).reset_index(drop=True)),
        "all_oos": metric_block(preds.reset_index(drop=True)),
    }

    last_sbs = sbs.dropna(subset=["valor_cuota"]).sort_values("fecha").iloc[-1]
    last_sbs_date = pd.Timestamp(last_sbs["fecha"])
    chained_vc = float(last_sbs["valor_cuota"])
    projection_rows = []

    # Con SBS aún sin publicar, no inventamos targets para 19/20: el entrenamiento permanece
    # en las últimas 90 observaciones reales disponibles y el VC se encadena desde el último SBS.
    train_current = real.tail(WINDOW).copy()
    beta_current = fit_ols(train_current)
    current_market = marketq.loc[(marketq["fecha"] > last_sbs_date) & (marketq["fecha"] <= TARGET_END)].copy()
    current_market = current_market.dropna(subset=FEATURES).sort_values("fecha")
    for _, row in current_market.iterrows():
        pred_ret = predict(beta_current, row)
        base = chained_vc
        chained_vc = float(base * (1.0 + pred_ret))
        projection_rows.append({
            "fecha": row["fecha"].strftime("%Y-%m-%d"),
            "base_vc": base,
            "base_type": "SBS real" if len(projection_rows) == 0 else "VC estimado previo",
            "pred_return": pred_ret,
            "signal": classify(pred_ret),
            "pred_vc": chained_vc,
            "qqq_close": float(row["QQQ"]) if pd.notna(row.get("QQQ")) else None,
            "qqq_return": float(row["ret_QQQ"]),
            "fx_return": float(row["ret_USD_PEN"]),
        })

    coef = {"intercept": float(beta_current[0])}
    coef.update({FEATURES[i]: float(beta_current[i+1]) for i in range(len(FEATURES))})

    payload = {
        "generated_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "fund": "PROFUTURO Fondo 3",
        "purpose": "Rolling 90 real-vs-estimado y proyección hasta cierre 2026-08-20; investigación, no cambia producción.",
        "features": FEATURES,
        "excluded": ["ret_NEM", "ret_FCX"],
        "qqq_representation": "retorno QQQ directo; predictivamente equivalente a QQQ residualizado en OLS con los mismos otros factores.",
        "common_real_rows": int(len(real)),
        "oos_prediction_rows": int(len(preds)),
        "first_oos": preds.iloc[0]["fecha"].strftime("%Y-%m-%d"),
        "last_oos": preds.iloc[-1]["fecha"].strftime("%Y-%m-%d"),
        "metrics": metrics,
        "current_training": {
            "n": WINDOW,
            "start": train_current.iloc[0]["fecha"].strftime("%Y-%m-%d"),
            "end": train_current.iloc[-1]["fecha"].strftime("%Y-%m-%d"),
            "coefficients": coef,
            "vif": vif_table(train_current),
        },
        "last_sbs": {"fecha": last_sbs_date.strftime("%Y-%m-%d"), "valor_cuota": float(last_sbs["valor_cuota"])},
        "projection_to_close": projection_rows,
        "projection_note": "19/20 se proyectan con coeficientes rolling90 estimados sobre las últimas 90 observaciones SBS reales. Al no existir todavía VC SBS posterior al 18, el entrenamiento no incorpora retornos estimados como si fueran reales; solo se encadena el nivel del VC para obtener el 20.",
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    p = preds.copy()
    for c in ["fecha", "train_start", "train_end"]:
        p[c] = pd.to_datetime(p[c]).dt.strftime("%Y-%m-%d")
    p.to_csv(PRED_OUT, index=False)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
