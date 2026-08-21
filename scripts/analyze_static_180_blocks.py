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

FEATURES_CURRENT = [
    "ret_SPY", "ret_EEM", "ret_EPU", "ret_MCHI",
    "ret_NEM", "ret_FCX", "ret_USD_PEN",
]
FEATURES_FULL = [
    "ret_SPY", "ret_EEM", "ret_EPU", "ret_MCHI",
    "ret_NEM", "ret_FCX", "ret_USD_PEN", "ret_QQQ",
]
FEATURES_REDUCED = [
    "ret_SPY", "ret_EEM", "ret_EPU", "ret_MCHI",
    "ret_USD_PEN", "ret_QQQ",
]
MODELS = {
    "actual_github_7f": FEATURES_CURRENT,
    "con_nem_fcx_qqq_8f": FEATURES_FULL,
    "sin_nem_fcx_qqq_6f": FEATURES_REDUCED,
}
ALL_FEATURES = sorted(set(FEATURES_FULL))


def read_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce")
    return df.dropna(subset=["fecha"]).sort_values("fecha").drop_duplicates("fecha", keep="last").reset_index(drop=True)


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
    adj_r2 = None if r2 is None or n <= k else float(1.0 - (1.0 - r2) * (n - 1) / (n - k))
    return {
        "beta": beta,
        "r2": r2,
        "adj_r2": adj_r2,
        "rmse_train": float(np.sqrt(np.mean(resid ** 2))),
        "condition_number": float(np.linalg.cond(X)),
        "coefficients": {name: float(v) for name, v in zip(["intercept", *features], beta)},
    }


def calc_vif(train: pd.DataFrame, features: list[str]) -> dict:
    out = {}
    for target in features:
        others = [c for c in features if c != target]
        y = train[target].to_numpy(float)
        X = np.c_[np.ones(len(train)), train[others].to_numpy(float)]
        b = np.linalg.lstsq(X, y, rcond=None)[0]
        resid = y - X @ b
        sse = float(np.sum(resid ** 2))
        sst = float(np.sum((y - y.mean()) ** 2))
        if sst <= 1e-20:
            out[target] = None
        else:
            r2 = 1.0 - sse / sst
            out[target] = None if 1.0 - r2 <= 1e-12 else float(1.0 / (1.0 - r2))
    return out


def predict(beta: np.ndarray, row: pd.Series, features: list[str]) -> float:
    return float(np.r_[1.0, row[features].to_numpy(float)] @ beta)


def signal(x: float) -> int:
    return 1 if x > THRESHOLD else (-1 if x < -THRESHOLD else 0)


def metrics(df: pd.DataFrame) -> dict:
    err = df["pred_vc"].to_numpy(float) - df["actual_vc"].to_numpy(float)
    actual_vc = df["actual_vc"].to_numpy(float)
    pr = df["pred_return"].to_numpy(float)
    ar = df["actual_return"].to_numpy(float)
    den = float(np.sum((ar - ar.mean()) ** 2))
    r2 = None if den <= 1e-20 else float(1.0 - np.sum((pr - ar) ** 2) / den)
    corr = None if np.std(pr) == 0 or np.std(ar) == 0 else float(np.corrcoef(pr, ar)[0, 1])
    return {
        "n": int(len(df)),
        "vc_mae": float(np.mean(np.abs(err))),
        "vc_rmse": float(np.sqrt(np.mean(err ** 2))),
        "vc_mape_pct": float(np.mean(np.abs(err) / actual_vc) * 100.0),
        "vc_bias": float(np.mean(err)),
        "within_0_5pct": float(np.mean(np.abs(err) / actual_vc <= 0.005)),
        "within_1pct": float(np.mean(np.abs(err) / actual_vc <= 0.01)),
        "return_mae": float(np.mean(np.abs(pr - ar))),
        "return_rmse": float(np.sqrt(np.mean((pr - ar) ** 2))),
        "direction_accuracy": float(np.mean(np.array([signal(x) for x in pr]) == np.array([signal(x) for x in ar]))),
        "oos_r2_return": r2,
        "pred_actual_return_corr": corr,
    }


def run_continuous_180(real: pd.DataFrame, eval_start: int, train_window: int, horizon: int, model: str, features: list[str]) -> tuple[dict, list[dict]]:
    vc_est = float(real.iloc[eval_start - 1]["valor_cuota"])
    rows = []
    fits = []
    for block_start in range(eval_start, len(real), horizon):
        block_end = min(block_start + horizon, len(real))
        train = real.iloc[block_start - train_window:block_start].copy()
        fit = ols_fit(train, features)
        fits.append({
            "block_start": real.iloc[block_start]["fecha"].strftime("%Y-%m-%d"),
            "train_start": train.iloc[0]["fecha"].strftime("%Y-%m-%d"),
            "train_end": train.iloc[-1]["fecha"].strftime("%Y-%m-%d"),
            "r2": fit["r2"],
            "adj_r2": fit["adj_r2"],
            "rmse_train": fit["rmse_train"],
            "condition_number": fit["condition_number"],
            "max_vif": max(v for v in calc_vif(train, features).values() if v is not None),
        })
        for i in range(block_start, block_end):
            r = real.iloc[i]
            pr = predict(fit["beta"], r, features)
            vc_est *= 1.0 + pr
            rows.append({
                "test_type": "continuous_180",
                "model": model,
                "train_window": train_window,
                "freeze_horizon": horizon,
                "block_start": real.iloc[block_start]["fecha"],
                "fecha": r["fecha"],
                "pred_return": pr,
                "actual_return": float(r["ret_target"]),
                "pred_vc": vc_est,
                "actual_vc": float(r["valor_cuota"]),
            })
    df = pd.DataFrame(rows)
    out = metrics(df)
    end = df.iloc[-1]
    out.update({
        "endpoint_pred_vc": float(end["pred_vc"]),
        "endpoint_actual_vc": float(end["actual_vc"]),
        "endpoint_abs_error": float(abs(end["pred_vc"] - end["actual_vc"])),
        "mean_train_r2": float(np.mean([x["r2"] for x in fits if x["r2"] is not None])),
        "mean_train_adj_r2": float(np.mean([x["adj_r2"] for x in fits if x["adj_r2"] is not None])),
        "mean_condition_number": float(np.mean([x["condition_number"] for x in fits])),
        "max_condition_number": float(np.max([x["condition_number"] for x in fits])),
        "mean_max_vif": float(np.mean([x["max_vif"] for x in fits])),
        "n_calibrations": len(fits),
    })
    return out, rows


def run_independent_blocks(real: pd.DataFrame, train_window: int, horizon: int, model: str, features: list[str]) -> tuple[dict, list[dict], list[dict]]:
    # Bloques no superpuestos. Cada bloque usa un unico VC real al inicio como ancla.
    # Dentro del bloque no se reancla ni se recalibra; solo se usan los indicadores.
    start0 = max(TRAIN_WINDOWS)
    rows = []
    blocks = []
    for block_start in range(start0, len(real) - horizon + 1, horizon):
        block_end = block_start + horizon
        train = real.iloc[block_start - train_window:block_start].copy()
        fit = ols_fit(train, features)
        vifs = calc_vif(train, features)
        vc_est = float(real.iloc[block_start - 1]["valor_cuota"])
        block_rows = []
        for i in range(block_start, block_end):
            r = real.iloc[i]
            pr = predict(fit["beta"], r, features)
            vc_est *= 1.0 + pr
            rr = {
                "test_type": "independent_nonoverlap",
                "model": model,
                "train_window": train_window,
                "freeze_horizon": horizon,
                "block_start": real.iloc[block_start]["fecha"],
                "fecha": r["fecha"],
                "pred_return": pr,
                "actual_return": float(r["ret_target"]),
                "pred_vc": vc_est,
                "actual_vc": float(r["valor_cuota"]),
            }
            rows.append(rr)
            block_rows.append(rr)
        bdf = pd.DataFrame(block_rows)
        bm = metrics(bdf)
        endpoint = bdf.iloc[-1]
        blocks.append({
            "block_start": real.iloc[block_start]["fecha"].strftime("%Y-%m-%d"),
            "block_end": real.iloc[block_end - 1]["fecha"].strftime("%Y-%m-%d"),
            "train_start": train.iloc[0]["fecha"].strftime("%Y-%m-%d"),
            "train_end": train.iloc[-1]["fecha"].strftime("%Y-%m-%d"),
            "vc_mae": bm["vc_mae"],
            "vc_rmse": bm["vc_rmse"],
            "endpoint_abs_error": float(abs(endpoint["pred_vc"] - endpoint["actual_vc"])),
            "endpoint_error": float(endpoint["pred_vc"] - endpoint["actual_vc"]),
            "direction_accuracy": bm["direction_accuracy"],
            "return_mae": bm["return_mae"],
            "train_r2": fit["r2"],
            "train_adj_r2": fit["adj_r2"],
            "condition_number": fit["condition_number"],
            "max_vif": max(v for v in vifs.values() if v is not None),
        })
    df = pd.DataFrame(rows)
    out = metrics(df)
    out.update({
        "n_blocks": int(len(blocks)),
        "mean_endpoint_abs_error": float(np.mean([b["endpoint_abs_error"] for b in blocks])),
        "median_endpoint_abs_error": float(np.median([b["endpoint_abs_error"] for b in blocks])),
        "mean_train_r2": float(np.mean([b["train_r2"] for b in blocks if b["train_r2"] is not None])),
        "mean_train_adj_r2": float(np.mean([b["train_adj_r2"] for b in blocks if b["train_adj_r2"] is not None])),
        "mean_condition_number": float(np.mean([b["condition_number"] for b in blocks])),
        "mean_max_vif": float(np.mean([b["max_vif"] for b in blocks])),
    })
    return out, rows, blocks


def main() -> None:
    markets = read_csv(DATA / "markets.csv")
    sbs = read_csv(DATA / "sbs_profuturo_f3.csv")
    sbs["valor_cuota"] = pd.to_numeric(sbs["valor_cuota"], errors="coerce")
    sbs = sbs.dropna(subset=["valor_cuota"]).copy()
    sbs["ret_target"] = sbs["valor_cuota"].pct_change(fill_method=None)
    qqq = load_qqq(markets["fecha"].min(), markets["fecha"].max())
    mq = markets.merge(qqq, on="fecha", how="left")
    real = sbs[["fecha", "valor_cuota", "ret_target"]].merge(mq[["fecha", *ALL_FEATURES]], on="fecha", how="inner")
    real = real.dropna(subset=["valor_cuota", "ret_target", *ALL_FEATURES]).sort_values("fecha").drop_duplicates("fecha", keep="last").reset_index(drop=True)
    if len(real) < EVAL_LENGTH + max(TRAIN_WINDOWS) + 1:
        raise RuntimeError(f"Muestra insuficiente: {len(real)}")

    eval_start = len(real) - EVAL_LENGTH
    continuous = {}
    independent = {}
    detail_rows = []
    ranking_rows = []

    for tw in TRAIN_WINDOWS:
        continuous[str(tw)] = {}
        independent[str(tw)] = {}
        for h in HORIZONS:
            continuous[str(tw)][str(h)] = {}
            independent[str(tw)][str(h)] = {}
            for model, features in MODELS.items():
                cs, cr = run_continuous_180(real, eval_start, tw, h, model, features)
                continuous[str(tw)][str(h)][model] = cs
                detail_rows.extend(cr)
                hs, hr, hb = run_independent_blocks(real, tw, h, model, features)
                hs["blocks"] = hb
                independent[str(tw)][str(h)][model] = hs
                detail_rows.extend(hr)
                ranking_rows.append({
                    "training_window": tw,
                    "freeze_horizon": h,
                    "model": model,
                    "vc_mae": hs["vc_mae"],
                    "vc_rmse": hs["vc_rmse"],
                    "vc_mape_pct": hs["vc_mape_pct"],
                    "mean_endpoint_abs_error": hs["mean_endpoint_abs_error"],
                    "direction_accuracy": hs["direction_accuracy"],
                    "return_mae": hs["return_mae"],
                    "oos_r2_return": hs["oos_r2_return"],
                    "n_blocks": hs["n_blocks"],
                })

    # Comparacion directa contra produccion dentro de cada configuracion.
    comparisons = {}
    for tw in TRAIN_WINDOWS:
        comparisons[str(tw)] = {}
        for h in HORIZONS:
            cur = independent[str(tw)][str(h)]["actual_github_7f"]
            comparisons[str(tw)][str(h)] = {}
            for model in ["con_nem_fcx_qqq_8f", "sin_nem_fcx_qqq_6f"]:
                m = independent[str(tw)][str(h)][model]
                cur_blocks = independent[str(tw)][str(h)]["actual_github_7f"]["blocks"]
                m_blocks = m["blocks"]
                wins = sum(1 for a, b in zip(m_blocks, cur_blocks) if a["vc_mae"] < b["vc_mae"])
                endpoint_wins = sum(1 for a, b in zip(m_blocks, cur_blocks) if a["endpoint_abs_error"] < b["endpoint_abs_error"])
                comparisons[str(tw)][str(h)][model] = {
                    "vc_mae_improvement_vs_current_pct": float((cur["vc_mae"] - m["vc_mae"]) / cur["vc_mae"] * 100.0),
                    "vc_rmse_improvement_vs_current_pct": float((cur["vc_rmse"] - m["vc_rmse"]) / cur["vc_rmse"] * 100.0),
                    "endpoint_mae_improvement_vs_current_pct": float((cur["mean_endpoint_abs_error"] - m["mean_endpoint_abs_error"]) / cur["mean_endpoint_abs_error"] * 100.0),
                    "block_path_win_pct": float(wins / max(1, len(m_blocks)) * 100.0),
                    "block_endpoint_win_pct": float(endpoint_wins / max(1, len(m_blocks)) * 100.0),
                }

    ranking = pd.DataFrame(ranking_rows).sort_values(["vc_mae", "vc_rmse", "mean_endpoint_abs_error"]).reset_index(drop=True)
    ranking["rank"] = np.arange(1, len(ranking) + 1)

    payload = {
        "generated_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "fund": "PROFUTURO Fondo 3",
        "common_complete_rows": int(len(real)),
        "first_real_date": real.iloc[0]["fecha"].strftime("%Y-%m-%d"),
        "last_real_date": real.iloc[-1]["fecha"].strftime("%Y-%m-%d"),
        "models": MODELS,
        "design": {
            "training_windows": TRAIN_WINDOWS,
            "freeze_horizons": HORIZONS,
            "continuous_last180": "Un solo VC real al inicio de los ultimos 180 dias; no se reancla dentro de los 180 dias. Se recalibra solo al finalizar cada bloque de 30/60/90 observaciones.",
            "historical_independent_nonoverlap": "Bloques historicos no superpuestos. Cada bloque toma solo el VC real inmediatamente anterior como ancla, congela coeficientes durante 30/60/90 observaciones y no usa ningun VC SBS del interior para corregirse. Se compara al final con SBS.",
        },
        "continuous_last180": continuous,
        "historical_independent_nonoverlap": independent,
        "comparison_vs_current_github": comparisons,
        "ranking_historical_independent_by_vc_mae": ranking.to_dict(orient="records"),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    detail = pd.DataFrame(detail_rows)
    for c in ["block_start", "fecha"]:
        detail[c] = pd.to_datetime(detail[c]).dt.strftime("%Y-%m-%d")
    detail.to_csv(DETAIL, index=False)
    print(json.dumps({
        "comparison_vs_current_github": comparisons,
        "top_ranking": payload["ranking_historical_independent_by_vc_mae"][:12],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
