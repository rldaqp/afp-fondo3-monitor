from __future__ import annotations

import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import HuberRegressor, LinearRegression
from sklearn.metrics import r2_score
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "rolling90"
OUT = ROOT / "research_outputs" / "spy_sign"
WINDOW = 90
THRESHOLD = 0.001
EPSILON = 1.1
ALPHA = 0.0001
FULL_FEATURES = ["ret_SPY", "ret_NEM", "ret_FCX", "ret_EPU", "ret_MCHI", "ret_EEM", "ret_USD_PEN"]
NO_SPY_FEATURES = [x for x in FULL_FEATURES if x != "ret_SPY"]


def classify(x: float) -> str:
    if x > THRESHOLD:
        return "SUBE"
    if x < -THRESHOLD:
        return "BAJA"
    return "NEUTRO"


def prepare_data() -> pd.DataFrame:
    sbs = pd.read_csv(DATA / "sbs_profuturo_f3.csv")
    markets = pd.read_csv(DATA / "markets.csv")
    sbs["fecha"] = pd.to_datetime(sbs["fecha"], errors="coerce")
    sbs["valor_cuota"] = pd.to_numeric(sbs["valor_cuota"], errors="coerce")
    sbs = sbs.dropna(subset=["fecha", "valor_cuota"]).sort_values("fecha").drop_duplicates("fecha", keep="last")
    sbs["ret_profuturo"] = sbs["valor_cuota"].pct_change(fill_method=None)
    markets["fecha"] = pd.to_datetime(markets["fecha"], errors="coerce")
    for col in FULL_FEATURES:
        markets[col] = pd.to_numeric(markets[col], errors="coerce")
    data = sbs[["fecha", "valor_cuota", "ret_profuturo"]].merge(
        markets[["fecha", *FULL_FEATURES]], on="fecha", how="inner"
    )
    return data.dropna(subset=["ret_profuturo", *FULL_FEATURES]).sort_values("fecha").reset_index(drop=True)


def fit_huber(x: np.ndarray, y: np.ndarray) -> tuple[StandardScaler, HuberRegressor]:
    scaler = StandardScaler()
    xs = scaler.fit_transform(x)
    model = HuberRegressor(
        epsilon=EPSILON,
        alpha=ALPHA,
        fit_intercept=True,
        max_iter=3000,
        tol=1e-8,
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", ConvergenceWarning)
        model.fit(xs, y * 100.0)
    return scaler, model


def raw_coefficients(scaler: StandardScaler, model: HuberRegressor, features: list[str]) -> dict[str, float]:
    scale = np.where(np.asarray(scaler.scale_, dtype=float) == 0, 1.0, np.asarray(scaler.scale_, dtype=float))
    coef = np.asarray(model.coef_, dtype=float) / scale / 100.0
    intercept = (
        float(model.intercept_)
        - float(np.sum(np.asarray(model.coef_) * np.asarray(scaler.mean_) / scale))
    ) / 100.0
    return {"intercept": intercept, **{f: float(v) for f, v in zip(features, coef)}}


def rolling_predictions(data: pd.DataFrame, features: list[str], label: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: list[dict[str, object]] = []
    coefs: list[dict[str, object]] = []
    for i in range(WINDOW, len(data)):
        train = data.iloc[i - WINDOW:i]
        row = data.iloc[i]
        scaler, model = fit_huber(train[features].to_numpy(float), train["ret_profuturo"].to_numpy(float))
        pred = float(model.predict(scaler.transform(row[features].to_numpy(float).reshape(1, -1)))[0] / 100.0)
        beta = raw_coefficients(scaler, model, features)
        rows.append({
            "row_index": i,
            "fecha": row["fecha"],
            "ret_profuturo": float(row["ret_profuturo"]),
            f"pred_{label}": pred,
            f"class_{label}": classify(pred),
            "real_class": classify(float(row["ret_profuturo"])),
        })
        coefs.append({
            "row_index": i,
            "fecha_objetivo": row["fecha"],
            "ventana_inicio": train.iloc[0]["fecha"],
            "ventana_fin": train.iloc[-1]["fecha"],
            "modelo": label,
            **beta,
        })
    return pd.DataFrame(rows), pd.DataFrame(coefs)


def metrics(frame: pd.DataFrame, pred_col: str) -> dict[str, object]:
    w = frame.dropna(subset=["ret_profuturo", pred_col]).copy()
    w["real_class"] = w["ret_profuturo"].map(classify)
    w["pred_class"] = w[pred_col].map(classify)
    w["hit"] = w["real_class"].eq(w["pred_class"])
    err = w[pred_col] - w["ret_profuturo"]
    result: dict[str, object] = {
        "n": int(len(w)),
        "correct": int(w["hit"].sum()),
        "accuracy": float(w["hit"].mean()) if len(w) else None,
        "mae_pp": float(err.abs().mean() * 100.0) if len(w) else None,
        "rmse_pp": float(np.sqrt(np.mean(err * err)) * 100.0) if len(w) else None,
        "r2": float(r2_score(w["ret_profuturo"], w[pred_col])) if len(w) > 1 else None,
    }
    for signal in ["SUBE", "BAJA", "NEUTRO"]:
        sub = w[w["pred_class"].eq(signal)]
        result[f"{signal.lower()}_n"] = int(len(sub))
        result[f"{signal.lower()}_accuracy"] = None if sub.empty else float(sub["hit"].mean())
    return result


def vif_table(frame: pd.DataFrame, features: list[str]) -> list[dict[str, float | str]]:
    x = StandardScaler().fit_transform(frame[features].to_numpy(float))
    rows: list[dict[str, float | str]] = []
    for j, feature in enumerate(features):
        y = x[:, j]
        others = np.delete(x, j, axis=1)
        r2 = float(LinearRegression().fit(others, y).score(others, y))
        vif = float(np.inf if r2 >= 1.0 else 1.0 / (1.0 - r2))
        rows.append({"feature": feature, "vif": vif, "r2_against_others": r2})
    return rows


def split_name(idx: int, n: int) -> str:
    train_end = int(np.floor(n * 0.60))
    validation_end = int(np.floor(n * 0.80))
    if idx < train_end:
        return "train"
    if idx < validation_end:
        return "validation"
    return "test"


def current_prediction(data: pd.DataFrame, features: list[str]) -> dict[str, object]:
    latest = json.loads((ROOT / "public" / "data" / "latest.json").read_text(encoding="utf-8"))
    pending = pd.read_csv(DATA / "pending_predictions.csv")
    pending["fecha"] = pd.to_datetime(pending["fecha"], errors="coerce")
    for f in FULL_FEATURES:
        pending[f] = pd.to_numeric(pending.get(f), errors="coerce")
    train = data.tail(WINDOW)
    scaler, model = fit_huber(train[features].to_numpy(float), train["ret_profuturo"].to_numpy(float))
    beta = raw_coefficients(scaler, model, features)
    base_vc = float(latest["latest_sbs_vc"])
    last_sbs = pd.Timestamp(latest["latest_sbs_date"])
    chain: list[dict[str, object]] = []
    work = pending[pending["fecha"].gt(last_sbs)].dropna(subset=["fecha", *features]).sort_values("fecha")
    for _, row in work.iterrows():
        pred = float(model.predict(scaler.transform(row[features].to_numpy(float).reshape(1, -1)))[0] / 100.0)
        base_vc *= 1.0 + pred
        chain.append({"fecha": row["fecha"].date().isoformat(), "ret_estimado": pred, "senal": classify(pred), "vc_estimado": base_vc})
    return {
        "training_start": train.iloc[0]["fecha"].date().isoformat(),
        "training_end": train.iloc[-1]["fecha"].date().isoformat(),
        "training_n": int(len(train)),
        "coefficients": beta,
        "latest": chain[-1] if chain else None,
        "pending_series": chain,
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    data = prepare_data()
    if len(data) <= WINDOW:
        raise RuntimeError(f"Muestra insuficiente: {len(data)}")

    full_pred, full_coef = rolling_predictions(data, FULL_FEATURES, "full7")
    no_spy_pred, no_spy_coef = rolling_predictions(data, NO_SPY_FEATURES, "no_spy")
    paired = full_pred.merge(
        no_spy_pred[["row_index", "fecha", "pred_no_spy", "class_no_spy"]],
        on=["row_index", "fecha"], how="inner"
    )
    paired["split"] = paired["row_index"].map(lambda i: split_name(int(i), len(data)))
    paired["hit_full7"] = paired["real_class"].eq(paired["class_full7"])
    paired["hit_no_spy"] = paired["real_class"].eq(paired["class_no_spy"])

    latest90 = paired.tail(WINDOW).copy()
    corrected = (~latest90["hit_full7"]) & latest90["hit_no_spy"]
    new_errors = latest90["hit_full7"] & (~latest90["hit_no_spy"])

    spy_series = pd.to_numeric(full_coef["ret_SPY"], errors="coerce").dropna()
    latest90_coef = full_coef.tail(WINDOW).copy()
    latest90_spy = pd.to_numeric(latest90_coef["ret_SPY"], errors="coerce").dropna()

    corr_full = data[FULL_FEATURES].corr()["ret_SPY"].drop("ret_SPY").to_dict()
    corr_latest90 = data.tail(WINDOW)[FULL_FEATURES].corr()["ret_SPY"].drop("ret_SPY").to_dict()
    x_latest = StandardScaler().fit_transform(data.tail(WINDOW)[FULL_FEATURES].to_numpy(float))
    condition_number = float(np.linalg.cond(x_latest))

    split_metrics: dict[str, dict[str, object]] = {}
    for split in ["train", "validation", "test"]:
        sub = paired[paired["split"].eq(split)]
        split_metrics[split] = {
            "full7": metrics(sub, "pred_full7"),
            "no_spy": metrics(sub, "pred_no_spy"),
        }

    result = {
        "method": {
            "window": WINDOW,
            "threshold": THRESHOLD,
            "huber_epsilon": EPSILON,
            "huber_alpha": ALPHA,
            "features_full7": FULL_FEATURES,
            "features_no_spy": NO_SPY_FEATURES,
            "scaling": "StandardScaler fitted separately inside every rolling training window",
            "target": "same-date Profuturo Fondo 3 return",
            "leakage_control": "Each target is predicted using only the previous 90 complete observations",
        },
        "sample": {
            "n": int(len(data)),
            "start": data.iloc[0]["fecha"].date().isoformat(),
            "end": data.iloc[-1]["fecha"].date().isoformat(),
            "rolling_predictions_n": int(len(paired)),
        },
        "spy_diagnostics": {
            "correlation_full_sample": {k: float(v) for k, v in corr_full.items()},
            "correlation_latest90": {k: float(v) for k, v in corr_latest90.items()},
            "vif_latest90": vif_table(data.tail(WINDOW), FULL_FEATURES),
            "condition_number_standardized_latest90": condition_number,
            "rolling_coefficient_all": {
                "n": int(len(spy_series)),
                "negative_n": int((spy_series < 0).sum()),
                "positive_n": int((spy_series > 0).sum()),
                "negative_share": float((spy_series < 0).mean()),
                "median": float(spy_series.median()),
                "min": float(spy_series.min()),
                "max": float(spy_series.max()),
            },
            "rolling_coefficient_latest90": {
                "n": int(len(latest90_spy)),
                "negative_n": int((latest90_spy < 0).sum()),
                "positive_n": int((latest90_spy > 0).sum()),
                "negative_share": float((latest90_spy < 0).mean()),
                "median": float(latest90_spy.median()),
                "min": float(latest90_spy.min()),
                "max": float(latest90_spy.max()),
                "latest": float(latest90_spy.iloc[-1]),
            },
        },
        "latest90": {
            "full7": metrics(latest90, "pred_full7"),
            "no_spy": metrics(latest90, "pred_no_spy"),
            "corrected_errors": int(corrected.sum()),
            "new_errors": int(new_errors.sum()),
            "corrected_dates": latest90.loc[corrected, "fecha"].dt.date.astype(str).tolist(),
            "new_error_dates": latest90.loc[new_errors, "fecha"].dt.date.astype(str).tolist(),
            "signal_changes": int((latest90["class_full7"] != latest90["class_no_spy"]).sum()),
        },
        "chronological_60_20_20": split_metrics,
        "current": {
            "full7": current_prediction(data, FULL_FEATURES),
            "no_spy": current_prediction(data, NO_SPY_FEATURES),
        },
    }

    paired.to_csv(OUT / "paired_predictions.csv", index=False)
    pd.concat([full_coef, no_spy_coef], ignore_index=True).to_csv(OUT / "rolling_coefficients.csv", index=False)
    (OUT / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
