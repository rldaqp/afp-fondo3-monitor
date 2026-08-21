from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "rolling90"
OUT = ROOT / "analysis" / "profuturo_static_windows_validation.json"
PRED_OUT = ROOT / "analysis" / "profuturo_static_windows_predictions.csv"

FEATURES = ["ret_SPY", "ret_EEM", "ret_EPU", "ret_MCHI", "ret_USD_PEN", "ret_QQQ"]
TRAIN_SPECS = {"90": 90, "180": 180, "270": 270, "FULL": None}
TEST_SIZES = [90, 60]
THRESHOLD = 0.001


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
        end=(end + pd.Timedelta(days=3)).strftime("%Y-%m-%d"),
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


def fit_static(train: pd.DataFrame) -> dict:
    x = train[FEATURES].to_numpy(float)
    y = train["ret_target"].to_numpy(float)
    d = np.c_[np.ones(len(x)), x]
    beta = np.linalg.lstsq(d, y, rcond=None)[0]
    fitted = d @ beta
    resid = y - fitted
    sse = float(np.sum(resid ** 2))
    sst = float(np.sum((y - y.mean()) ** 2))
    train_r2 = 1.0 - sse / sst if sst > 0 else None

    mu_x = x.mean(axis=0)
    sd_x = x.std(axis=0, ddof=0)
    sd_y = y.std(ddof=0)
    std_beta = beta[1:] * sd_x / sd_y if sd_y > 0 else np.full(len(FEATURES), np.nan)

    # Diagnóstico clásico de coeficientes OLS (sin usarlo como criterio principal de selección).
    dof = len(y) - d.shape[1]
    xtx_inv = np.linalg.pinv(d.T @ d)
    sigma2 = sse / dof if dof > 0 else np.nan
    se = np.sqrt(np.diag(xtx_inv) * sigma2)
    tvals = beta / se
    try:
        from scipy.stats import t as student_t
        pvals = 2.0 * student_t.sf(np.abs(tvals), df=dof)
    except Exception:
        pvals = np.full_like(beta, np.nan)

    names = ["intercept", *FEATURES]
    coef = {}
    for i, name in enumerate(names):
        coef[name] = {
            "estimate": float(beta[i]),
            "std_error": float(se[i]) if np.isfinite(se[i]) else None,
            "t": float(tvals[i]) if np.isfinite(tvals[i]) else None,
            "p_value": float(pvals[i]) if np.isfinite(pvals[i]) else None,
        }
    standardized = {FEATURES[i]: float(std_beta[i]) for i in range(len(FEATURES))}
    condition_number = float(np.linalg.cond(np.c_[np.ones(len(x)), (x - mu_x) / np.where(sd_x < 1e-12, 1.0, sd_x)]))
    return {
        "beta": beta,
        "coefficients": coef,
        "standardized_beta": standardized,
        "train_r2": train_r2,
        "condition_number_standardized_design": condition_number,
        "vif": vif_table(train),
    }


def predict(model: dict, test: pd.DataFrame) -> np.ndarray:
    x = test[FEATURES].to_numpy(float)
    return np.c_[np.ones(len(x)), x] @ model["beta"]


def metrics(test: pd.DataFrame, pred_ret: np.ndarray) -> dict:
    actual_ret = test["ret_target"].to_numpy(float)
    prev_vc = test["prev_vc"].to_numpy(float)
    actual_vc = test["valor_cuota"].to_numpy(float)
    pred_vc = prev_vc * (1.0 + pred_ret)
    naive_vc = prev_vc

    err_r = pred_ret - actual_ret
    err_v = pred_vc - actual_vc
    mae_v = float(np.mean(np.abs(err_v)))
    rmse_v = float(np.sqrt(np.mean(err_v ** 2)))
    naive_rmse_v = float(np.sqrt(np.mean((naive_vc - actual_vc) ** 2)))
    ybar = actual_ret.mean()
    denom = float(np.sum((actual_ret - ybar) ** 2))
    oos_r2 = None if denom <= 1e-20 else float(1.0 - np.sum(err_r ** 2) / denom)
    corr = None
    if np.std(pred_ret) > 0 and np.std(actual_ret) > 0:
        corr = float(np.corrcoef(pred_ret, actual_ret)[0, 1])
    pred_class = np.array([classify(float(v)) for v in pred_ret])
    actual_class = np.array([classify(float(v)) for v in actual_ret])
    rel_v = np.abs(err_v) / actual_vc

    return {
        "n": int(len(test)),
        "start": test.iloc[0]["fecha"].strftime("%Y-%m-%d"),
        "end": test.iloc[-1]["fecha"].strftime("%Y-%m-%d"),
        "return_mae": float(np.mean(np.abs(err_r))),
        "return_rmse": float(np.sqrt(np.mean(err_r ** 2))),
        "return_bias": float(np.mean(err_r)),
        "oos_r2_return": oos_r2,
        "pred_actual_return_corr": corr,
        "direction_accuracy": float(np.mean(pred_class == actual_class)),
        "vc_mae": mae_v,
        "vc_rmse": rmse_v,
        "vc_mape_pct": float(np.mean(rel_v) * 100.0),
        "vc_bias": float(np.mean(err_v)),
        "within_0_5pct": float(np.mean(rel_v <= 0.005)),
        "within_1pct": float(np.mean(rel_v <= 0.01)),
        "naive_vc_rmse": naive_rmse_v,
        "theil_u_vs_no_change": None if naive_rmse_v <= 0 else float(rmse_v / naive_rmse_v),
    }


def run_split(frame: pd.DataFrame, test_size: int) -> tuple[dict, list[dict]]:
    if len(frame) <= test_size + 270:
        raise RuntimeError(f"Muestra insuficiente: {len(frame)} para test {test_size} + train 270")
    train_pool = frame.iloc[:-test_size].copy()
    test = frame.iloc[-test_size:].copy()
    models = {}
    pred_rows = []

    for label, ntrain in TRAIN_SPECS.items():
        train = train_pool.copy() if ntrain is None else train_pool.tail(ntrain).copy()
        fit = fit_static(train)
        pred_ret = predict(fit, test)
        m = metrics(test, pred_ret)
        models[label] = {
            "train_n": int(len(train)),
            "train_start": train.iloc[0]["fecha"].strftime("%Y-%m-%d"),
            "train_end": train.iloc[-1]["fecha"].strftime("%Y-%m-%d"),
            "metrics": m,
            "train_r2": fit["train_r2"],
            "condition_number_standardized_design": fit["condition_number_standardized_design"],
            "vif": fit["vif"],
            "coefficients": fit["coefficients"],
            "standardized_beta": fit["standardized_beta"],
        }
        pred_vc = test["prev_vc"].to_numpy(float) * (1.0 + pred_ret)
        for i, (_, row) in enumerate(test.iterrows()):
            pred_rows.append({
                "test_size": test_size,
                "model": label,
                "fecha": row["fecha"].strftime("%Y-%m-%d"),
                "actual_return": float(row["ret_target"]),
                "pred_return": float(pred_ret[i]),
                "actual_vc": float(row["valor_cuota"]),
                "prev_vc": float(row["prev_vc"]),
                "pred_vc": float(pred_vc[i]),
            })

    def score_tuple(item):
        name, data = item
        mm = data["metrics"]
        return (mm["vc_rmse"], mm["vc_mae"], mm["theil_u_vs_no_change"])

    ranking = [name for name, _ in sorted(models.items(), key=score_tuple)]
    return {
        "test_size": test_size,
        "test_start": test.iloc[0]["fecha"].strftime("%Y-%m-%d"),
        "test_end": test.iloc[-1]["fecha"].strftime("%Y-%m-%d"),
        "train_pool_n": int(len(train_pool)),
        "models": models,
        "ranking_by_vc_rmse_then_mae": ranking,
        "best_vc_rmse": min(models, key=lambda k: models[k]["metrics"]["vc_rmse"]),
        "best_vc_mae": min(models, key=lambda k: models[k]["metrics"]["vc_mae"]),
        "best_direction": max(models, key=lambda k: models[k]["metrics"]["direction_accuracy"]),
        "best_theil_u": min(models, key=lambda k: models[k]["metrics"]["theil_u_vs_no_change"]),
    }, pred_rows


def main() -> None:
    markets = read_csv(DATA / "markets.csv")
    sbs = read_csv(DATA / "sbs_profuturo_f3.csv")
    sbs["valor_cuota"] = pd.to_numeric(sbs["valor_cuota"], errors="coerce")
    sbs = sbs.dropna(subset=["valor_cuota"]).copy()
    sbs["prev_vc"] = sbs["valor_cuota"].shift(1)
    sbs["ret_target"] = sbs["valor_cuota"].pct_change(fill_method=None)

    qqq = load_qqq(markets["fecha"].min(), markets["fecha"].max())
    m = markets.merge(qqq, on="fecha", how="left")
    frame = sbs[["fecha", "valor_cuota", "prev_vc", "ret_target"]].merge(m[["fecha", *[f for f in FEATURES if f != "ret_QQQ"], "ret_QQQ"]], on="fecha", how="inner")
    frame = frame.loc[frame["fecha"] >= pd.Timestamp("2025-01-01")]
    frame = frame.dropna(subset=["valor_cuota", "prev_vc", "ret_target", *FEATURES]).sort_values("fecha").drop_duplicates("fecha", keep="last").reset_index(drop=True)

    splits = {}
    all_preds = []
    for test_size in TEST_SIZES:
        result, preds = run_split(frame, test_size)
        splits[str(test_size)] = result
        all_preds.extend(preds)

    payload = {
        "generated_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "fund": "PROFUTURO Fondo 3",
        "purpose": "Validación estática sin rolling; investigación solamente, no modifica el modelo oficial.",
        "features": FEATURES,
        "excluded": ["ret_NEM", "ret_FCX"],
        "qqq_representation": "retorno QQQ directo; en OLS es predictivamente equivalente a residualizarlo contra los demás factores presentes.",
        "common_complete_rows": int(len(frame)),
        "first_complete_date": frame.iloc[0]["fecha"].strftime("%Y-%m-%d"),
        "last_complete_date": frame.iloc[-1]["fecha"].strftime("%Y-%m-%d"),
        "primary_validation": "90",
        "method": "Cada modelo se ajusta una sola vez y sus coeficientes quedan fijos durante todo el bloque de validación. 90/180/270 indican número de observaciones de entrenamiento inmediatamente anteriores al test; FULL usa todas las observaciones disponibles antes del test. Las cuatro variantes predicen exactamente las mismas fechas fuera de muestra. El VC diario estimado usa el VC SBS real de la observación previa para medir precisión one-step-ahead. Theil U compara RMSE de VC contra la regla ingenua VC_t = VC_{t-1}.",
        "splits": splits,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    pd.DataFrame(all_preds).to_csv(PRED_OUT, index=False)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
