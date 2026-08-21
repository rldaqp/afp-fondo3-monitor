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
FEATURES_FULL8 = ["ret_SPY", "ret_EEM", "ret_EPU", "ret_MCHI", "ret_NEM", "ret_FCX", "ret_USD_PEN", "ret_QQQ"]
BASE_RESID = ["ret_SPY", "ret_EEM", "ret_EPU", "ret_MCHI", "ret_USD_PEN"]
FEATURES_RESID_MODEL = BASE_RESID + ["resid_QQQ", "resid_FCX", "resid_NEM"]
ALL_FEATURES = sorted(set(FEATURES_FULL8))
BLIND_HORIZONS = [5, 10, 20]
MANUAL_VALIDATION = {pd.Timestamp("2026-08-19"): 70.327}
MODEL_NAMES = ["current", "alt", "resid", "combo"]


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


def fit_ols(train: pd.DataFrame, features: list[str], target: str = "ret_target") -> np.ndarray:
    x = train[features].to_numpy(float)
    y = train[target].to_numpy(float)
    return np.linalg.lstsq(np.c_[np.ones(len(x)), x], y, rcond=None)[0]


def predict(beta: np.ndarray, row: pd.Series, features: list[str]) -> float:
    return float(np.r_[1.0, row[features].to_numpy(float)] @ beta)


def residualize_fit(train: pd.DataFrame, target: str, regressors: list[str]) -> np.ndarray:
    return fit_ols(train, regressors, target=target)


def residual_value(beta: np.ndarray, row: pd.Series, target: str, regressors: list[str]) -> float:
    expected = float(np.r_[1.0, row[regressors].to_numpy(float)] @ beta)
    return float(row[target] - expected)


def fit_residual_mining_model(train: pd.DataFrame) -> dict:
    # QQQ se ortogonaliza contra los cinco factores base; FCX y NEM contra EPU.
    # Con OLS puro y los factores base presentes, esto es una reparametrización del modelo 8F.
    # Se conserva para comprobar empíricamente si la residualización por sí sola cambia la predicción.
    bq = residualize_fit(train, "ret_QQQ", BASE_RESID)
    bf = residualize_fit(train, "ret_FCX", ["ret_EPU"])
    bn = residualize_fit(train, "ret_NEM", ["ret_EPU"])
    aug = train.copy()
    aug["resid_QQQ"] = [residual_value(bq, r, "ret_QQQ", BASE_RESID) for _, r in train.iterrows()]
    aug["resid_FCX"] = [residual_value(bf, r, "ret_FCX", ["ret_EPU"]) for _, r in train.iterrows()]
    aug["resid_NEM"] = [residual_value(bn, r, "ret_NEM", ["ret_EPU"]) for _, r in train.iterrows()]
    beta = fit_ols(aug, FEATURES_RESID_MODEL)
    return {"beta": beta, "bq": bq, "bf": bf, "bn": bn}


def predict_residual_mining(model: dict, row: pd.Series) -> float:
    r = row.copy()
    r["resid_QQQ"] = residual_value(model["bq"], row, "ret_QQQ", BASE_RESID)
    r["resid_FCX"] = residual_value(model["bf"], row, "ret_FCX", ["ret_EPU"])
    r["resid_NEM"] = residual_value(model["bn"], row, "ret_NEM", ["ret_EPU"])
    return predict(model["beta"], r, FEATURES_RESID_MODEL)


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


def summarize_origins(o: pd.DataFrame) -> dict:
    out = {
        "n_origins": int(len(o)),
        "first_origin": o.iloc[0]["origin_date"].strftime("%Y-%m-%d") if len(o) else None,
        "last_origin": o.iloc[-1]["origin_date"].strftime("%Y-%m-%d") if len(o) else None,
        "models": {},
    }
    if o.empty:
        return out
    for m in MODEL_NAMES:
        out["models"][m] = {
            "endpoint_mae": float(o[f"endpoint_abs_{m}"].mean()),
            "endpoint_median_abs": float(o[f"endpoint_abs_{m}"].median()),
            "endpoint_bias": float(o[f"endpoint_bias_{m}"].mean()),
            "path_mae": float(o[f"path_mae_{m}"].mean()),
        }
    cur_ep = out["models"]["current"]["endpoint_mae"]
    cur_path = out["models"]["current"]["path_mae"]
    out["vs_current"] = {}
    for m in ["alt", "resid", "combo"]:
        ep = out["models"][m]["endpoint_mae"]
        pa = out["models"][m]["path_mae"]
        out["vs_current"][m] = {
            "endpoint_win_pct": float((o[f"endpoint_abs_{m}"] < o["endpoint_abs_current"]).mean() * 100.0),
            "path_win_pct": float((o[f"path_mae_{m}"] < o["path_mae_current"]).mean() * 100.0),
            "endpoint_mae_improvement_pct": float((cur_ep - ep) / cur_ep * 100.0),
            "path_mae_improvement_pct": float((cur_path - pa) / cur_path * 100.0),
        }
    return out


def blind_chain_backtest(frame: pd.DataFrame) -> tuple[dict, pd.DataFrame]:
    rows: list[dict] = []
    summaries_all: dict[str, dict] = {}
    summaries_recent90: dict[str, dict] = {}
    residual_equivalence_diffs: list[float] = []

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
            b_full8 = fit_ols(train, FEATURES_FULL8)
            m_resid = fit_residual_mining_model(train)

            vc0 = float(frame.iloc[origin_i]["valor_cuota"])
            cur_vc = vc0
            alt_vc = vc0
            resid_vc = vc0
            path_abs = {m: [] for m in MODEL_NAMES}

            for step, (_, r) in enumerate(future.iterrows(), start=1):
                pr_cur = predict(b_cur, r, FEATURES_CURRENT)
                pr_alt = predict(b_alt, r, FEATURES_ALT)
                pr_resid = predict_residual_mining(m_resid, r)
                pr_full8 = predict(b_full8, r, FEATURES_FULL8)
                residual_equivalence_diffs.append(abs(pr_resid - pr_full8))

                cur_vc *= 1.0 + pr_cur
                alt_vc *= 1.0 + pr_alt
                resid_vc *= 1.0 + pr_resid
                combo_vc = 0.5 * cur_vc + 0.5 * alt_vc

                actual = float(r["valor_cuota"])
                values = {"current": cur_vc, "alt": alt_vc, "resid": resid_vc, "combo": combo_vc}
                row_out = {
                    "horizon": horizon,
                    "origin_date": frame.iloc[origin_i]["fecha"],
                    "origin_vc": vc0,
                    "step": step,
                    "fecha": r["fecha"],
                    "actual_vc": actual,
                    "current_pred_return": pr_cur,
                    "alt_pred_return": pr_alt,
                    "resid_pred_return": pr_resid,
                    "full8_pred_return_check": pr_full8,
                }
                for m, val in values.items():
                    err = val - actual
                    path_abs[m].append(abs(err))
                    row_out[f"{m}_pred_vc"] = val
                    row_out[f"{m}_error"] = err
                    row_out[f"{m}_abs_error"] = abs(err)
                rows.append(row_out)

            endpoint_actual = float(future.iloc[-1]["valor_cuota"])
            endpoint_values = {
                "current": cur_vc,
                "alt": alt_vc,
                "resid": resid_vc,
                "combo": 0.5 * cur_vc + 0.5 * alt_vc,
            }
            origin_row = {
                "origin_date": frame.iloc[origin_i]["fecha"],
                "end_date": future.iloc[-1]["fecha"],
            }
            for m, val in endpoint_values.items():
                origin_row[f"endpoint_abs_{m}"] = abs(val - endpoint_actual)
                origin_row[f"endpoint_bias_{m}"] = val - endpoint_actual
                origin_row[f"path_mae_{m}"] = float(np.mean(path_abs[m]))
            origins.append(origin_row)

        o = pd.DataFrame(origins)
        summaries_all[str(horizon)] = summarize_origins(o)
        summaries_recent90[str(horizon)] = summarize_origins(o.tail(min(90, len(o))).reset_index(drop=True))

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
                    "resid_pred_vc": float(x.resid_pred_vc),
                    "combo_pred_vc": float(x.combo_pred_vc),
                    "current_abs_error": float(x.current_abs_error),
                    "alt_abs_error": float(x.alt_abs_error),
                    "resid_abs_error": float(x.resid_abs_error),
                    "combo_abs_error": float(x.combo_abs_error),
                }
                for x in rp.itertuples(index=False)
            ],
        }

    return {
        "summary_all_origins": summaries_all,
        "summary_recent_90_origins": summaries_recent90,
        "recent_paths": recent_paths,
        "residual_model_equivalence_check": {
            "max_abs_daily_return_difference_vs_raw_full8": float(max(residual_equivalence_diffs)) if residual_equivalence_diffs else None,
            "note": "Con OLS puro, residualizar QQQ/FCX/NEM contra factores que siguen dentro del modelo es una reparametrización; por eso debe ser predictivamente equivalente al OLS raw de 8 factores. Si se quiere reducir realmente la amplificación minera hace falta shrinkage/capping o excluir/reponderar factores, no solo residualizar.",
        },
    }, all_rows


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

    # One-step del modelo alternativo para conservar la comparación previa.
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
    m_resid = fit_residual_mining_model(train_current)
    current_market = marketq.loc[(marketq["fecha"] > last_sbs_date) & (marketq["fecha"] <= TARGET_END)].copy()
    current_market = current_market.dropna(subset=ALL_FEATURES).sort_values("fecha")

    cur_vc = float(last_sbs["valor_cuota"])
    alt_vc = float(last_sbs["valor_cuota"])
    resid_vc = float(last_sbs["valor_cuota"])
    live_chain = []
    for _, row in current_market.iterrows():
        pr_cur = predict(b_cur, row, FEATURES_CURRENT)
        pr_alt = predict(b_alt, row, FEATURES_ALT)
        pr_resid = predict_residual_mining(m_resid, row)
        cur_vc *= 1.0 + pr_cur
        alt_vc *= 1.0 + pr_alt
        resid_vc *= 1.0 + pr_resid
        combo_vc = 0.5 * cur_vc + 0.5 * alt_vc
        actual_manual = MANUAL_VALIDATION.get(pd.Timestamp(row["fecha"]))
        live_chain.append({
            "fecha": row["fecha"].strftime("%Y-%m-%d"),
            "actual_vc_manual_validation": actual_manual,
            "current_pred_return": pr_cur,
            "current_pred_vc": cur_vc,
            "alt_pred_return": pr_alt,
            "alt_pred_vc": alt_vc,
            "resid_pred_return": pr_resid,
            "resid_pred_vc": resid_vc,
            "combo_pred_vc": combo_vc,
            "current_abs_error_if_known": None if actual_manual is None else abs(cur_vc - actual_manual),
            "alt_abs_error_if_known": None if actual_manual is None else abs(alt_vc - actual_manual),
            "resid_abs_error_if_known": None if actual_manual is None else abs(resid_vc - actual_manual),
            "combo_abs_error_if_known": None if actual_manual is None else abs(combo_vc - actual_manual),
        })

    payload = {
        "generated_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "fund": "PROFUTURO Fondo 3",
        "purpose": "Backtest ciego rolling90: después de cada corte se congelan coeficientes y no se usa ningún VC SBS futuro para reanclar o recalibrar; solo se observan retornos de indicadores.",
        "window": WINDOW,
        "models": {
            "current": {"features": FEATURES_CURRENT, "description": "Modelo actual GitHub 7 factores"},
            "alt": {"features": FEATURES_ALT, "description": "Sin NEM/FCX + QQQ"},
            "resid": {"features": FEATURES_RESID_MODEL, "description": "Minería y QQQ residualizados; OLS puro"},
            "combo": {"description": "Promedio 50/50 de los niveles VC ciegos de current y alt"},
        },
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
        "method_note": "Cada origen usa exactamente 90 observaciones reales previas. Se ajustan los modelos una sola vez, luego se congelan y se encadena el VC durante 5, 10 o 20 observaciones futuras usando solo retornos de mercado. Los VC SBS futuros se revelan únicamente al final para medir error. summary_recent_90_origins restringe la comparación a los 90 orígenes más recientes de cada horizonte.",
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
