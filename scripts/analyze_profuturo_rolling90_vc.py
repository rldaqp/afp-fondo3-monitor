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
BLIND_OUT = ROOT / "analysis" / "profuturo_blind_chain_validation.csv"

WINDOW = 90
THRESHOLD = 0.001
TARGET_END = pd.Timestamp("2026-08-20")
FEATURES_CURRENT = ["ret_SPY", "ret_EEM", "ret_EPU", "ret_MCHI", "ret_NEM", "ret_FCX", "ret_USD_PEN"]
FEATURES_ALT = ["ret_SPY", "ret_EEM", "ret_EPU", "ret_MCHI", "ret_USD_PEN", "ret_QQQ"]
ALL_FEATURES = sorted(set(FEATURES_CURRENT + FEATURES_ALT))
BLIND_HORIZONS = [5, 10, 20]
MANUAL_VALIDATION = {pd.Timestamp("2026-08-19"): 70.327}


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


def fit_ols(train: pd.DataFrame, features: list[str]) -> np.ndarray:
    x = train[features].to_numpy(float)
    y = train["ret_target"].to_numpy(float)
    return np.linalg.lstsq(np.c_[np.ones(len(x)), x], y, rcond=None)[0]


def predict(beta: np.ndarray, row: pd.Series, features: list[str]) -> float:
    return float(np.r_[1.0, row[features].to_numpy(float)] @ beta)


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


def blind_chain_backtest(frame: pd.DataFrame) -> tuple[dict, pd.DataFrame]:
    rows: list[dict] = []
    summaries: dict[str, dict] = {}

    for horizon in BLIND_HORIZONS:
        origins = []
        for origin_i in range(WINDOW - 1, len(frame) - horizon):
            train = frame.iloc[origin_i - WINDOW + 1: origin_i + 1].copy()
            future = frame.iloc[origin_i + 1: origin_i + 1 + horizon].copy()
            if len(train) != WINDOW or len(future) != horizon:
                continue
            if train[["ret_target", *ALL_FEATURES]].isna().any().any() or future[ALL_FEATURES].isna().any().any():
                continue

            b_cur = fit_ols(train, FEATURES_CURRENT)
            b_alt = fit_ols(train, FEATURES_ALT)
            vc0 = float(frame.iloc[origin_i]["valor_cuota"])
            cur_vc = vc0
            alt_vc = vc0
            path_abs_cur = []
            path_abs_alt = []

            for step, (_, r) in enumerate(future.iterrows(), start=1):
                pr_cur = predict(b_cur, r, FEATURES_CURRENT)
                pr_alt = predict(b_alt, r, FEATURES_ALT)
                cur_vc *= (1.0 + pr_cur)
                alt_vc *= (1.0 + pr_alt)
                actual = float(r["valor_cuota"])
                err_cur = cur_vc - actual
                err_alt = alt_vc - actual
                path_abs_cur.append(abs(err_cur))
                path_abs_alt.append(abs(err_alt))
                rows.append({
                    "horizon": horizon,
                    "origin_date": frame.iloc[origin_i]["fecha"],
                    "origin_vc": vc0,
                    "step": step,
                    "fecha": r["fecha"],
                    "actual_vc": actual,
                    "current_pred_vc": cur_vc,
                    "alt_pred_vc": alt_vc,
                    "current_error": err_cur,
                    "alt_error": err_alt,
                    "current_abs_error": abs(err_cur),
                    "alt_abs_error": abs(err_alt),
                    "current_pred_return": pr_cur,
                    "alt_pred_return": pr_alt,
                })

            endpoint_actual = float(future.iloc[-1]["valor_cuota"])
            origins.append({
                "origin_date": frame.iloc[origin_i]["fecha"],
                "end_date": future.iloc[-1]["fecha"],
                "endpoint_abs_current": abs(cur_vc - endpoint_actual),
                "endpoint_abs_alt": abs(alt_vc - endpoint_actual),
                "endpoint_bias_current": cur_vc - endpoint_actual,
                "endpoint_bias_alt": alt_vc - endpoint_actual,
                "path_mae_current": float(np.mean(path_abs_cur)),
                "path_mae_alt": float(np.mean(path_abs_alt)),
            })

        o = pd.DataFrame(origins)
        summaries[str(horizon)] = {
            "n_origins": int(len(o)),
            "first_origin": o.iloc[0]["origin_date"].strftime("%Y-%m-%d") if len(o) else None,
            "last_origin": o.iloc[-1]["origin_date"].strftime("%Y-%m-%d") if len(o) else None,
            "endpoint_mae_current": float(o["endpoint_abs_current"].mean()),
            "endpoint_mae_alt": float(o["endpoint_abs_alt"].mean()),
            "endpoint_median_abs_current": float(o["endpoint_abs_current"].median()),
            "endpoint_median_abs_alt": float(o["endpoint_abs_alt"].median()),
            "endpoint_bias_current": float(o["endpoint_bias_current"].mean()),
            "endpoint_bias_alt": float(o["endpoint_bias_alt"].mean()),
            "path_mae_current": float(o["path_mae_current"].mean()),
            "path_mae_alt": float(o["path_mae_alt"].mean()),
            "alt_beats_current_endpoint_pct": float((o["endpoint_abs_alt"] < o["endpoint_abs_current"]).mean() * 100.0),
            "alt_beats_current_path_pct": float((o["path_mae_alt"] < o["path_mae_current"]).mean() * 100.0),
            "endpoint_mae_improvement_alt_pct": float((o["endpoint_abs_current"].mean() - o["endpoint_abs_alt"].mean()) / o["endpoint_abs_current"].mean() * 100.0),
            "path_mae_improvement_alt_pct": float((o["path_mae_current"].mean() - o["path_mae_alt"].mean()) / o["path_mae_current"].mean() * 100.0),
        }

    all_rows = pd.DataFrame(rows)

    recent_paths = {}
    for horizon in [10, 20]:
        sub = all_rows.loc[all_rows["horizon"] == horizon].copy()
        if sub.empty:
            continue
        latest_origin = sub["origin_date"].max()
        rp = sub.loc[sub["origin_date"] == latest_origin].sort_values("step")
        recent_paths[str(horizon)] = {
            "origin_date": latest_origin.strftime("%Y-%m-%d"),
            "origin_vc": float(rp.iloc[0]["origin_vc"]),
            "end_date": rp.iloc[-1]["fecha"].strftime("%Y-%m-%d"),
            "rows": [
                {
                    "step": int(x.step),
                    "fecha": x.fecha.strftime("%Y-%m-%d"),
                    "actual_vc": float(x.actual_vc),
                    "current_pred_vc": float(x.current_pred_vc),
                    "alt_pred_vc": float(x.alt_pred_vc),
                    "current_abs_error": float(x.current_abs_error),
                    "alt_abs_error": float(x.alt_abs_error),
                }
                for x in rp.itertuples(index=False)
            ],
        }
    return {"summary": summaries, "recent_paths": recent_paths}, all_rows


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
        marketq[["fecha", *ALL_FEATURES]], on="fecha", how="inner"
    )
    real = real.loc[real["fecha"] >= pd.Timestamp("2025-01-01")]
    real = real.dropna(subset=["valor_cuota", "prev_vc", "ret_target", *ALL_FEATURES]).sort_values("fecha").drop_duplicates("fecha", keep="last").reset_index(drop=True)
    if len(real) <= WINDOW:
        raise RuntimeError("Muestra insuficiente")

    # One-step del modelo alternativo, para conservar la comparación anterior.
    rows = []
    for i in range(WINDOW, len(real)):
        train = real.iloc[i-WINDOW:i].copy()
        current = real.iloc[i]
        beta = fit_ols(train, FEATURES_ALT)
        pred_ret = predict(beta, current, FEATURES_ALT)
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

    blind, blind_rows = blind_chain_backtest(real)

    last_sbs = sbs.dropna(subset=["valor_cuota"]).sort_values("fecha").iloc[-1]
    last_sbs_date = pd.Timestamp(last_sbs["fecha"])
    train_current = real.tail(WINDOW).copy()
    b_cur = fit_ols(train_current, FEATURES_CURRENT)
    b_alt = fit_ols(train_current, FEATURES_ALT)
    current_market = marketq.loc[(marketq["fecha"] > last_sbs_date) & (marketq["fecha"] <= TARGET_END)].copy()
    current_market = current_market.dropna(subset=ALL_FEATURES).sort_values("fecha")
    cur_vc = float(last_sbs["valor_cuota"])
    alt_vc = float(last_sbs["valor_cuota"])
    live_chain = []
    for _, row in current_market.iterrows():
        pr_cur = predict(b_cur, row, FEATURES_CURRENT)
        pr_alt = predict(b_alt, row, FEATURES_ALT)
        cur_vc *= 1.0 + pr_cur
        alt_vc *= 1.0 + pr_alt
        actual_manual = MANUAL_VALIDATION.get(pd.Timestamp(row["fecha"]))
        live_chain.append({
            "fecha": row["fecha"].strftime("%Y-%m-%d"),
            "actual_vc_manual_validation": actual_manual,
            "current_pred_return": pr_cur,
            "current_pred_vc": cur_vc,
            "current_abs_error_if_known": None if actual_manual is None else abs(cur_vc - actual_manual),
            "alt_pred_return": pr_alt,
            "alt_pred_vc": alt_vc,
            "alt_abs_error_if_known": None if actual_manual is None else abs(alt_vc - actual_manual),
        })

    payload = {
        "generated_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "fund": "PROFUTURO Fondo 3",
        "purpose": "Validación ciega: después del corte no se usa ningún VC SBS para reanclar nivel ni recalibrar coeficientes; solo retornos observados de los indicadores.",
        "window": WINDOW,
        "current_model_features": FEATURES_CURRENT,
        "alternative_model_features": FEATURES_ALT,
        "alternative_excluded": ["ret_NEM", "ret_FCX"],
        "common_real_rows": int(len(real)),
        "first_real_date": real.iloc[0]["fecha"].strftime("%Y-%m-%d"),
        "last_real_date": real.iloc[-1]["fecha"].strftime("%Y-%m-%d"),
        "one_step_alt_metrics": metrics,
        "blind_chain": blind,
        "live_blind_chain_after_last_sbs": {
            "last_sbs_date": last_sbs_date.strftime("%Y-%m-%d"),
            "last_sbs_vc": float(last_sbs["valor_cuota"]),
            "manual_validation_note": "70.327 del 19/08 fue informado por el usuario y se usa solo para medir error; no entra al entrenamiento ni reancla la cadena.",
            "rows": live_chain,
        },
        "method_note": "Para cada origen histórico se ajustan ambos OLS una sola vez con las 90 observaciones reales anteriores, se congelan coeficientes y se encadena el VC durante 5, 10 o 20 observaciones futuras usando solo precios/retornos de indicadores. Los VC SBS futuros se consultan únicamente después para medir error.",
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    p = preds.copy()
    for c in ["fecha", "train_start", "train_end"]:
        p[c] = pd.to_datetime(p[c]).dt.strftime("%Y-%m-%d")
    p.to_csv(PRED_OUT, index=False)
    if not blind_rows.empty:
        b = blind_rows.copy()
        for c in ["origin_date", "fecha"]:
            b[c] = pd.to_datetime(b[c]).dt.strftime("%Y-%m-%d")
        b.to_csv(BLIND_OUT, index=False)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
