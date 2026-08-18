from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from sklearn.linear_model import Ridge

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "rolling90"
OUT = ROOT / "analysis" / "qqq_ridge_residualized_profuturo.json"
TRAIN_WINDOW = 90
HORIZONS = [30, 60, 90, 180]
THRESHOLD = 0.001
RIDGE_ALPHAS = [0.01, 0.1, 1.0, 10.0]

BASE_FEATURES = ["ret_SPY", "ret_EEM", "ret_EPU", "ret_MCHI", "ret_NEM", "ret_FCX", "ret_USD_PEN"]
B_FEATURES = ["ret_SPY", "ret_QQQ", "ret_EEM", "ret_EPU", "ret_MCHI", "ret_NEM", "ret_FCX", "ret_USD_PEN"]
OTHER_FEATURES = ["ret_EEM", "ret_EPU", "ret_MCHI", "ret_NEM", "ret_FCX", "ret_USD_PEN"]


def classify(v: float) -> str:
    if v > THRESHOLD:
        return "SUBE"
    if v < -THRESHOLD:
        return "BAJA"
    return "NEUTRO"


def read_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce")
    return df.dropna(subset=["fecha"]).sort_values("fecha").reset_index(drop=True)


def extract_close(raw: pd.DataFrame, ticker: str) -> pd.Series:
    if raw.empty:
        return pd.Series(dtype=float)
    if isinstance(raw.columns, pd.MultiIndex):
        for key in [("Close", ticker), (ticker, "Close")]:
            if key in raw.columns:
                return pd.to_numeric(raw[key], errors="coerce")
        cols = [c for c in raw.columns if "Close" in c]
        if cols:
            return pd.to_numeric(raw[cols[0]], errors="coerce")
    if "Close" in raw.columns:
        return pd.to_numeric(raw["Close"], errors="coerce")
    raise RuntimeError("Yahoo no devolvió Close utilizable para QQQ")


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
        raise RuntimeError("No se pudo descargar QQQ")
    idx = pd.to_datetime(close.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    q = pd.DataFrame({"fecha": idx.normalize(), "QQQ": close.to_numpy(float)})
    q = q.sort_values("fecha").drop_duplicates("fecha", keep="last")
    q["ret_QQQ"] = q["QQQ"].pct_change(fill_method=None)
    return q[["fecha", "ret_QQQ"]]


def standardize(train_x: np.ndarray, current_x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    mu = train_x.mean(axis=0)
    sd = train_x.std(axis=0, ddof=0)
    sd = np.where(sd < 1e-12, 1.0, sd)
    return (train_x - mu) / sd, (current_x - mu) / sd


def ols_predict(train_x: np.ndarray, y: np.ndarray, current_x: np.ndarray) -> tuple[float, float]:
    xz, cz = standardize(train_x, current_x)
    beta = np.linalg.lstsq(np.c_[np.ones(len(xz)), xz], y, rcond=None)[0]
    pred = float(np.r_[1.0, cz] @ beta)
    return pred, float(np.linalg.norm(beta[1:]))


def ridge_predict(train_x: np.ndarray, y: np.ndarray, current_x: np.ndarray, alpha: float) -> tuple[float, float]:
    xz, cz = standardize(train_x, current_x)
    model = Ridge(alpha=alpha, fit_intercept=True)
    model.fit(xz, y)
    pred = float(model.predict(cz.reshape(1, -1))[0])
    return pred, float(np.linalg.norm(model.coef_))


def residualize_qqq_on_spy(train: pd.DataFrame, current: pd.Series) -> tuple[np.ndarray, np.ndarray]:
    spy = train["ret_SPY"].to_numpy(float)
    qqq = train["ret_QQQ"].to_numpy(float)
    beta = np.linalg.lstsq(np.c_[np.ones(len(spy)), spy], qqq, rcond=None)[0]
    resid_train = qqq - (beta[0] + beta[1] * spy)
    resid_current = float(current["ret_QQQ"] - (beta[0] + beta[1] * float(current["ret_SPY"])))
    train_x = np.column_stack([
        train["ret_SPY"].to_numpy(float),
        resid_train,
        *[train[f].to_numpy(float) for f in OTHER_FEATURES],
    ])
    current_x = np.array([
        float(current["ret_SPY"]),
        resid_current,
        *[float(current[f]) for f in OTHER_FEATURES],
    ], dtype=float)
    return train_x, current_x


def residualize_qqq_on_all_current(train: pd.DataFrame, current: pd.Series) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    x_base = train[BASE_FEATURES].to_numpy(float)
    qqq = train["ret_QQQ"].to_numpy(float)
    design = np.c_[np.ones(len(x_base)), x_base]
    beta = np.linalg.lstsq(design, qqq, rcond=None)[0]
    resid_train = qqq - design @ beta

    current_base = current[BASE_FEATURES].to_numpy(float)
    resid_current = float(current["ret_QQQ"] - np.r_[1.0, current_base] @ beta)

    train_x = np.column_stack([x_base, resid_train])
    current_x = np.r_[current_base, resid_current].astype(float)
    return train_x, current_x, beta


def build_predictions(frame: pd.DataFrame) -> dict[str, pd.DataFrame]:
    rows: dict[str, list[dict]] = {
        "ACTUAL_OLS": [],
        "B_SPY_MAS_QQQ_OLS": [],
        "QQQ_RESIDUAL_SPY_OLS": [],
        "QQQ_RESIDUAL_TODOS_OLS": [],
        **{f"RIDGE_{a:g}": [] for a in RIDGE_ALPHAS},
    }

    for i in range(TRAIN_WINDOW, len(frame)):
        train = frame.iloc[i - TRAIN_WINDOW:i]
        current = frame.iloc[i]
        y = train["ret_target"].to_numpy(float)
        actual = float(current["ret_target"])

        bx = train[BASE_FEATURES].to_numpy(float)
        bc = current[BASE_FEATURES].to_numpy(float)
        pred, norm = ols_predict(bx, y, bc)
        rows["ACTUAL_OLS"].append({"fecha": current["fecha"], "pred": pred, "actual": actual, "coef_norm": norm})

        qx = train[B_FEATURES].to_numpy(float)
        qc = current[B_FEATURES].to_numpy(float)
        pred, norm = ols_predict(qx, y, qc)
        rows["B_SPY_MAS_QQQ_OLS"].append({"fecha": current["fecha"], "pred": pred, "actual": actual, "coef_norm": norm})

        rx, rc = residualize_qqq_on_spy(train, current)
        pred, norm = ols_predict(rx, y, rc)
        rows["QQQ_RESIDUAL_SPY_OLS"].append({"fecha": current["fecha"], "pred": pred, "actual": actual, "coef_norm": norm})

        fx, fc, _ = residualize_qqq_on_all_current(train, current)
        pred, norm = ols_predict(fx, y, fc)
        rows["QQQ_RESIDUAL_TODOS_OLS"].append({"fecha": current["fecha"], "pred": pred, "actual": actual, "coef_norm": norm})

        for a in RIDGE_ALPHAS:
            pred, norm = ridge_predict(qx, y, qc, a)
            rows[f"RIDGE_{a:g}"].append({"fecha": current["fecha"], "pred": pred, "actual": actual, "coef_norm": norm})

    out = {k: pd.DataFrame(v) for k, v in rows.items()}
    for df in out.values():
        df["pred_class"] = df["pred"].map(classify)
        df["actual_class"] = df["actual"].map(classify)
    return out


def metrics(df: pd.DataFrame) -> dict:
    err = df["pred"].to_numpy(float) - df["actual"].to_numpy(float)
    return {
        "n": int(len(df)),
        "mae": float(np.mean(np.abs(err))),
        "rmse": float(np.sqrt(np.mean(err ** 2))),
        "direction_accuracy": float((df["pred_class"] == df["actual_class"]).mean()),
        "median_coef_norm": float(df["coef_norm"].median()),
        "max_coef_norm": float(df["coef_norm"].max()),
    }


def vif_table(x: np.ndarray, names: list[str]) -> dict:
    out = {}
    for j, name in enumerate(names):
        y = x[:, j]
        others = np.delete(x, j, axis=1)
        design = np.c_[np.ones(len(others)), others]
        fit = np.linalg.lstsq(design, y, rcond=None)[0]
        pred = design @ fit
        ss_res = float(np.sum((y - pred) ** 2))
        ss_tot = float(np.sum((y - y.mean()) ** 2))
        r2 = 1.0 - ss_res / ss_tot if ss_tot > 1e-20 else 1.0
        out[name] = float(1.0 / max(1e-12, 1.0 - r2))
    return {"by_feature": out, "max_vif": max(out.values()), "max_vif_feature": max(out, key=out.get)}


def recent_vifs(frame: pd.DataFrame) -> dict:
    recent = frame.tail(90).copy()
    actual = vif_table(recent[BASE_FEATURES].to_numpy(float), BASE_FEATURES)
    b = vif_table(recent[B_FEATURES].to_numpy(float), B_FEATURES)

    spy = recent["ret_SPY"].to_numpy(float)
    qqq = recent["ret_QQQ"].to_numpy(float)
    beta_spy = np.linalg.lstsq(np.c_[np.ones(len(spy)), spy], qqq, rcond=None)[0]
    resid_spy = qqq - (beta_spy[0] + beta_spy[1] * spy)
    rx = np.column_stack([spy, resid_spy, *[recent[f].to_numpy(float) for f in OTHER_FEATURES]])
    names_spy = ["ret_SPY", "ret_QQQ_resid_spy", *OTHER_FEATURES]
    r_spy = vif_table(rx, names_spy)

    x_base = recent[BASE_FEATURES].to_numpy(float)
    design_all = np.c_[np.ones(len(x_base)), x_base]
    beta_all = np.linalg.lstsq(design_all, qqq, rcond=None)[0]
    resid_all = qqq - design_all @ beta_all
    fx = np.column_stack([x_base, resid_all])
    names_all = [*BASE_FEATURES, "ret_QQQ_resid_todos"]
    r_all = vif_table(fx, names_all)

    corr_resid_all = {
        feature: float(np.corrcoef(recent[feature].to_numpy(float), resid_all)[0, 1])
        for feature in BASE_FEATURES
    }

    return {
        "ACTUAL": actual,
        "B_SPY_MAS_QQQ": b,
        "QQQ_RESIDUAL_SPY": r_spy,
        "QQQ_RESIDUAL_TODOS": r_all,
        "qqq_on_spy_beta_recent90": float(beta_spy[1]),
        "qqq_on_all_current_beta_recent90": {
            "intercept": float(beta_all[0]),
            **{feature: float(beta_all[i + 1]) for i, feature in enumerate(BASE_FEATURES)},
        },
        "corr_qqq_residual_todos_vs_current_recent90": corr_resid_all,
        "qqq_residual_todos_std_recent90": float(np.std(resid_all, ddof=0)),
    }


def max_prediction_diff(a: pd.DataFrame, b: pd.DataFrame) -> float:
    return float(np.max(np.abs(a["pred"].to_numpy(float) - b["pred"].to_numpy(float))))


def main() -> None:
    markets = read_csv(DATA / "markets.csv")
    sbs = read_csv(DATA / "sbs_profuturo_f3.csv")
    sbs["valor_cuota"] = pd.to_numeric(sbs["valor_cuota"], errors="coerce")
    sbs = sbs.dropna(subset=["valor_cuota"]).drop_duplicates("fecha", keep="last")
    sbs["ret_target"] = sbs["valor_cuota"].pct_change(fill_method=None)

    qqq = download_qqq(markets["fecha"].min(), max(markets["fecha"].max(), pd.Timestamp.now().normalize()))
    markets = markets.merge(qqq, on="fecha", how="left")

    frame = sbs[["fecha", "ret_target"]].merge(markets, on="fecha", how="inner")
    frame = frame.loc[frame["fecha"] >= pd.Timestamp("2025-01-01")]
    frame = frame.dropna(subset=["ret_target", *B_FEATURES]).sort_values("fecha").drop_duplicates("fecha", keep="last").reset_index(drop=True)
    if len(frame) <= TRAIN_WINDOW + max(HORIZONS):
        raise RuntimeError("Muestra insuficiente")

    preds = build_predictions(frame)
    windows = {}
    for h in [*HORIZONS, "ALL"]:
        label = str(h)
        metric_map = {}
        for name, df in preds.items():
            part = df if h == "ALL" else df.tail(int(h))
            metric_map[name] = metrics(part.reset_index(drop=True))
        base = metric_map["ACTUAL_OLS"]
        for m in metric_map.values():
            m["mae_change_vs_actual_pct"] = float((m["mae"] / base["mae"] - 1.0) * 100.0)
            m["direction_delta_pp_vs_actual"] = float((m["direction_accuracy"] - base["direction_accuracy"]) * 100.0)
        windows[label] = {
            "models": metric_map,
            "best_mae": min(metric_map, key=lambda n: metric_map[n]["mae"]),
            "best_direction": max(metric_map, key=lambda n: metric_map[n]["direction_accuracy"]),
        }

    equivalence = {
        "spy_plus_qqq_vs_residual_spy": max_prediction_diff(preds["B_SPY_MAS_QQQ_OLS"], preds["QQQ_RESIDUAL_SPY_OLS"]),
        "spy_plus_qqq_vs_residual_todos": max_prediction_diff(preds["B_SPY_MAS_QQQ_OLS"], preds["QQQ_RESIDUAL_TODOS_OLS"]),
    }

    payload = {
        "generated_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "fund": "PROFUTURO",
        "purpose": "Diagnóstico solamente. No modifica visor ni modelo oficial.",
        "method": "Rolling 90. QQQ residual se calcula dentro de cada ventana para evitar leakage. QQQ_RESIDUAL_TODOS quita de QQQ lo explicado por SPY, EEM, EPU, MCHI, NEM, FCX y USD/PEN.",
        "common_complete_rows": int(len(frame)),
        "prediction_rows": int(len(next(iter(preds.values())))),
        "first_prediction": next(iter(preds.values())).iloc[0]["fecha"].strftime("%Y-%m-%d"),
        "last_prediction": next(iter(preds.values())).iloc[-1]["fecha"].strftime("%Y-%m-%d"),
        "ridge_alphas": RIDGE_ALPHAS,
        "windows": windows,
        "recent90_vif": recent_vifs(frame),
        "residualization_equivalence_max_abs_prediction_diff": equivalence,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
