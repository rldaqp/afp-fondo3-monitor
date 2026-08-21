from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "rolling90"
OUT = ROOT / "analysis" / "profuturo_static_180_blocks.json"
DETAIL = ROOT / "analysis" / "profuturo_static_180_blocks.csv"

EVAL_LENGTH = 180
TRAIN_WINDOWS = [30, 60, 90]
HORIZONS = [30, 60, 90]
THRESHOLD = 0.001

FEATURES_FULL = [
    "ret_SPY", "ret_EEM", "ret_EPU", "ret_MCHI",
    "ret_NEM", "ret_FCX", "ret_USD_PEN", "ret_QQQ",
]
FEATURES_REDUCED = [
    "ret_SPY", "ret_EEM", "ret_EPU", "ret_MCHI",
    "ret_USD_PEN", "ret_QQQ",
]
MODELS = {
    "con_nem_fcx_qqq": FEATURES_FULL,
    "sin_nem_fcx_qqq": FEATURES_REDUCED,
}
ALL_FEATURES = sorted(set(FEATURES_FULL))


def read_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce")
    return (
        df.dropna(subset=["fecha"])
        .sort_values("fecha")
        .drop_duplicates("fecha", keep="last")
        .reset_index(drop=True)
    )


def extract_close(raw: pd.DataFrame, ticker: str) -> pd.Series:
    if raw.empty:
        raise RuntimeError(f"Yahoo no devolvio datos para {ticker}")
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
    raise RuntimeError(f"Yahoo no devolvio Close utilizable para {ticker}")


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
    return q[["fecha", "ret_QQQ"]]


def ols_fit(train: pd.DataFrame, features: list[str]) -> dict:
    x = train[features].to_numpy(float)
    y = train["ret_target"].to_numpy(float)
    X = np.c_[np.ones(len(x)), x]
    beta = np.linalg.lstsq(X, y, rcond=None)[0]
    fitted = X @ beta
    resid = y - fitted
    n, k = X.shape
    sse = float(np.sum(resid ** 2))
    sst = float(np.sum((y - y.mean()) ** 2))
    r2 = None if sst <= 1e-20 else float(1.0 - sse / sst)
    adj_r2 = None
    if r2 is not None and n > k:
        adj_r2 = float(1.0 - (1.0 - r2) * (n - 1) / (n - k))
    sigma2 = sse / max(1, n - k)
    cov = sigma2 * np.linalg.pinv(X.T @ X)
    se = np.sqrt(np.maximum(np.diag(cov), 0.0))
    tstat = np.divide(beta, se, out=np.full_like(beta, np.nan), where=se > 0)
    names = ["intercept", *features]
    return {
        "beta": beta,
        "coefficients": {n_: float(v) for n_, v in zip(names, beta)},
        "std_errors": {n_: float(v) for n_, v in zip(names, se)},
        "tstats": {n_: (None if not np.isfinite(v) else float(v)) for n_, v in zip(names, tstat)},
        "n": int(n),
        "k_parameters": int(k),
        "r2": r2,
        "adj_r2": adj_r2,
        "rmse_train": float(np.sqrt(np.mean(resid ** 2))),
        "condition_number": float(np.linalg.cond(X)),
    }


def calc_vif(train: pd.DataFrame, features: list[str]) -> dict:
    out = {}
    for j, target in enumerate(features):
        others = [c for c in features if c != target]
        y = train[target].to_numpy(float)
        X = np.c_[np.ones(len(train)), train[others].to_numpy(float)]
        b = np.linalg.lstsq(X, y, rcond=None)[0]
        resid = y - X @ b
        sse = float(np.sum(resid ** 2))
        sst = float(np.sum((y - y.mean()) ** 2))
        if sst <= 1e-20:
            out[target] = None
            continue
        r2 = 1.0 - sse / sst
        out[target] = None if (1.0 - r2) <= 1e-12 else float(1.0 / (1.0 - r2))
    return out


def predict(beta: np.ndarray, row: pd.Series, features: list[str]) -> float:
    return float(np.r_[1.0, row[features].to_numpy(float)] @ beta)


def signal(x: float) -> int:
    if x > THRESHOLD:
        return 1
    if x < -THRESHOLD:
        return -1
    return 0


def summarize_path(df: pd.DataFrame, base_vc: float) -> dict:
    actual_vc = df["actual_vc"].to_numpy(float)
    pred_vc = df["pred_vc"].to_numpy(float)
    actual_ret = df["actual_return"].to_numpy(float)
    pred_ret = df["pred_return"].to_numpy(float)
    err = pred_vc - actual_vc
    abs_rel = np.abs(err) / actual_vc
    rmse = float(np.sqrt(np.mean(err ** 2)))
    naive = np.full(len(df), float(base_vc))
    naive_rmse = float(np.sqrt(np.mean((naive - actual_vc) ** 2)))
    den = float(np.sum((actual_ret - actual_ret.mean()) ** 2))
    oos_r2 = None if den <= 1e-20 else float(1.0 - np.sum((pred_ret - actual_ret) ** 2) / den)
    corr = None
    if np.std(pred_ret) > 0 and np.std(actual_ret) > 0:
        corr = float(np.corrcoef(pred_ret, actual_ret)[0, 1])
    end = df.iloc[-1]
    return {
        "n": int(len(df)),
        "start": df.iloc[0]["fecha"].strftime("%Y-%m-%d"),
        "end": end["fecha"].strftime("%Y-%m-%d"),
        "base_vc": float(base_vc),
        "endpoint_pred_vc": float(end["pred_vc"]),
        "endpoint_actual_vc": float(end["actual_vc"]),
        "endpoint_error": float(end["pred_vc"] - end["actual_vc"]),
        "endpoint_abs_error": float(abs(end["pred_vc"] - end["actual_vc"])),
        "endpoint_abs_pct_error": float(abs(end["pred_vc"] - end["actual_vc"]) / end["actual_vc"] * 100.0),
        "vc_mae": float(np.mean(np.abs(err))),
        "vc_rmse": rmse,
        "vc_mape_pct": float(np.mean(abs_rel) * 100.0),
        "vc_bias": float(np.mean(err)),
        "within_0_5pct": float(np.mean(abs_rel <= 0.005)),
        "within_1pct": float(np.mean(abs_rel <= 0.01)),
        "return_mae": float(np.mean(np.abs(pred_ret - actual_ret))),
        "return_rmse": float(np.sqrt(np.mean((pred_ret - actual_ret) ** 2))),
        "direction_accuracy": float(np.mean([signal(x) for x in pred_ret] == np.array([signal(x) for x in actual_ret]))),
        "oos_r2_return": oos_r2,
        "pred_actual_return_corr": corr,
        "naive_constant_vc_rmse": naive_rmse,
        "theil_u_vs_constant_base": None if naive_rmse <= 1e-20 else float(rmse / naive_rmse),
    }


def summarize_estimators(calibs: list[dict], features: list[str]) -> dict:
    if not calibs:
        return {}
    coeff_names = ["intercept", *features]
    coeff_summary = {}
    for name in coeff_names:
        vals = np.array([c["fit"]["coefficients"][name] for c in calibs], dtype=float)
        coeff_summary[name] = {
            "mean": float(vals.mean()),
            "std": float(vals.std(ddof=0)),
            "min": float(vals.min()),
            "max": float(vals.max()),
        }
    all_vifs = {f: [c["vif"].get(f) for c in calibs if c["vif"].get(f) is not None] for f in features}
    vif_summary = {
        f: {
            "mean": float(np.mean(v)) if v else None,
            "max": float(np.max(v)) if v else None,
        }
        for f, v in all_vifs.items()
    }
    return {
        "n_calibrations": int(len(calibs)),
        "mean_train_r2": float(np.mean([c["fit"]["r2"] for c in calibs if c["fit"]["r2"] is not None])),
        "mean_train_adj_r2": float(np.mean([c["fit"]["adj_r2"] for c in calibs if c["fit"]["adj_r2"] is not None])),
        "mean_train_rmse": float(np.mean([c["fit"]["rmse_train"] for c in calibs])),
        "condition_number_mean": float(np.mean([c["fit"]["condition_number"] for c in calibs])),
        "condition_number_max": float(np.max([c["fit"]["condition_number"] for c in calibs])),
        "coefficients": coeff_summary,
        "vif": vif_summary,
        "calibrations": calibs,
    }


def run_combo(real: pd.DataFrame, eval_start: int, train_window: int, horizon: int, model_name: str, features: list[str]) -> tuple[dict, list[dict]]:
    # Cadena estricta: se ancla una sola vez justo antes de los 180 dias de evaluacion.
    # El VC estimado NUNCA se reancla con el VC real durante los 180 dias.
    # Los coeficientes se recalibran solo al terminar cada bloque de H dias,
    # usando exclusivamente informacion que ya era historica en ese punto.
    base_row = real.iloc[eval_start - 1]
    vc_est = float(base_row["valor_cuota"])
    base_vc = vc_est
    rows = []
    calibs = []

    for block_start in range(eval_start, len(real), horizon):
        block_end = min(block_start + horizon, len(real))
        if block_start - train_window < 0:
            raise RuntimeError("No hay historia suficiente para la ventana solicitada")
        train = real.iloc[block_start - train_window:block_start].copy()
        fit = ols_fit(train, features)
        vif = calc_vif(train, features)
        calibs.append({
            "block_start": real.iloc[block_start]["fecha"].strftime("%Y-%m-%d"),
            "block_end": real.iloc[block_end - 1]["fecha"].strftime("%Y-%m-%d"),
            "train_start": train.iloc[0]["fecha"].strftime("%Y-%m-%d"),
            "train_end": train.iloc[-1]["fecha"].strftime("%Y-%m-%d"),
            "fit": {k: v for k, v in fit.items() if k != "beta"},
            "vif": vif,
        })
        beta = fit["beta"]
        block_no = len(calibs)
        for i in range(block_start, block_end):
            r = real.iloc[i]
            pr = predict(beta, r, features)
            vc_est *= 1.0 + pr
            rows.append({
                "model": model_name,
                "train_window": train_window,
                "reestimate_every": horizon,
                "block": block_no,
                "fecha": r["fecha"],
                "pred_return": pr,
                "actual_return": float(r["ret_target"]),
                "pred_vc": vc_est,
                "actual_vc": float(r["valor_cuota"]),
                "error_vc": vc_est - float(r["valor_cuota"]),
            })

    path = pd.DataFrame(rows)
    summary = summarize_path(path, base_vc)
    summary["training_window"] = train_window
    summary["reestimate_every"] = horizon
    summary["model"] = model_name
    summary["estimator_summary"] = summarize_estimators(calibs, features)
    return summary, rows


def main() -> None:
    markets = read_csv(DATA / "markets.csv")
    sbs = read_csv(DATA / "sbs_profuturo_f3.csv")
    sbs["valor_cuota"] = pd.to_numeric(sbs["valor_cuota"], errors="coerce")
    sbs = sbs.dropna(subset=["valor_cuota"]).copy()
    sbs["ret_target"] = sbs["valor_cuota"].pct_change(fill_method=None)

    qqq = load_qqq(markets["fecha"].min(), markets["fecha"].max())
    mq = markets.merge(qqq, on="fecha", how="left")
    real = sbs[["fecha", "valor_cuota", "ret_target"]].merge(
        mq[["fecha", *ALL_FEATURES]], on="fecha", how="inner"
    )
    real = (
        real.dropna(subset=["valor_cuota", "ret_target", *ALL_FEATURES])
        .sort_values("fecha")
        .drop_duplicates("fecha", keep="last")
        .reset_index(drop=True)
    )
    if len(real) < EVAL_LENGTH + max(TRAIN_WINDOWS) + 1:
        raise RuntimeError(f"Muestra insuficiente: {len(real)}")

    eval_start = len(real) - EVAL_LENGTH
    base = real.iloc[eval_start - 1]
    eval_first = real.iloc[eval_start]
    eval_last = real.iloc[-1]

    results = {}
    detail_rows = []
    ranking_rows = []

    for train_window in TRAIN_WINDOWS:
        results[str(train_window)] = {}
        for horizon in HORIZONS:
            results[str(train_window)][str(horizon)] = {}
            for model_name, features in MODELS.items():
                summary, rows = run_combo(real, eval_start, train_window, horizon, model_name, features)
                results[str(train_window)][str(horizon)][model_name] = summary
                detail_rows.extend(rows)
                ranking_rows.append({
                    "training_window": train_window,
                    "reestimate_every": horizon,
                    "model": model_name,
                    "vc_mae": summary["vc_mae"],
                    "vc_rmse": summary["vc_rmse"],
                    "vc_mape_pct": summary["vc_mape_pct"],
                    "endpoint_abs_error": summary["endpoint_abs_error"],
                    "endpoint_abs_pct_error": summary["endpoint_abs_pct_error"],
                    "direction_accuracy": summary["direction_accuracy"],
                    "return_mae": summary["return_mae"],
                    "oos_r2_return": summary["oos_r2_return"],
                    "theil_u_vs_constant_base": summary["theil_u_vs_constant_base"],
                })

    ranking = pd.DataFrame(ranking_rows).sort_values(["vc_mae", "vc_rmse", "endpoint_abs_error"]).reset_index(drop=True)
    for i, r in ranking.iterrows():
        ranking.loc[i, "rank_vc_mae"] = i + 1

    payload = {
        "generated_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "fund": "PROFUTURO Fondo 3",
        "design": {
            "evaluation_length_complete_market_observations": EVAL_LENGTH,
            "evaluation_start": eval_first["fecha"].strftime("%Y-%m-%d"),
            "evaluation_end": eval_last["fecha"].strftime("%Y-%m-%d"),
            "single_initial_anchor_date": base["fecha"].strftime("%Y-%m-%d"),
            "single_initial_anchor_vc": float(base["valor_cuota"]),
            "training_windows": TRAIN_WINDOWS,
            "coefficient_freeze_horizons": HORIZONS,
            "no_reanchor": True,
            "note": "Se usa un solo VC real para anclar al inicio de los 180 dias. Durante los 180 dias el VC estimado nunca se corrige con el VC real. Los coeficientes solo se recalibran al terminar cada bloque de 30, 60 o 90 observaciones y cada recalibracion usa exclusivamente datos ya historicos. Los VC reales del bloque activo solo se revelan para medir error.",
        },
        "models": {
            "con_nem_fcx_qqq": FEATURES_FULL,
            "sin_nem_fcx_qqq": FEATURES_REDUCED,
        },
        "common_complete_rows": int(len(real)),
        "results": results,
        "ranking_by_vc_mae": ranking.to_dict(orient="records"),
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    detail = pd.DataFrame(detail_rows)
    detail["fecha"] = pd.to_datetime(detail["fecha"]).dt.strftime("%Y-%m-%d")
    detail.to_csv(DETAIL, index=False)
    print(json.dumps({
        "design": payload["design"],
        "ranking_by_vc_mae": payload["ranking_by_vc_mae"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
