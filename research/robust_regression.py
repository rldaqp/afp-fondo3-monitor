from __future__ import annotations

import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import HuberRegressor, Ridge
from sklearn.preprocessing import StandardScaler

WINDOW = 90
THRESHOLD = 0.001
FACTORS = [
    "ret_SPY",
    "ret_NEM",
    "ret_FCX",
    "ret_EPU",
    "ret_MCHI",
    "ret_EEM",
    "ret_USD_PEN",
]
RIDGE_ALPHAS = [0.0, 0.001, 0.003, 0.01, 0.03, 0.1, 0.3, 1.0, 3.0, 10.0, 30.0, 100.0]
HUBER_EPSILONS = [1.1, 1.2, 1.35, 1.5, 1.75, 2.0]
HUBER_ALPHAS = [0.0, 1e-6, 1e-5, 1e-4, 1e-3, 1e-2]

ROOT = Path(__file__).resolve().parents[1]
MARKETS = ROOT / "data" / "rolling90" / "markets.csv"
SBS = ROOT / "data" / "rolling90" / "sbs_profuturo_f3.csv"
OUT = ROOT / "research_outputs_robust"


def classify(values: pd.Series | np.ndarray) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    return np.where(arr > THRESHOLD, "SUBE", np.where(arr < -THRESHOLD, "BAJA", "NEUTRO"))


def prepare_data() -> pd.DataFrame:
    markets = pd.read_csv(MARKETS, parse_dates=["fecha"]).sort_values("fecha")
    sbs = pd.read_csv(SBS, parse_dates=["fecha"]).sort_values("fecha")
    sbs["ret_profuturo"] = sbs["valor_cuota"].pct_change(fill_method=None)
    data = sbs[["fecha", "valor_cuota", "ret_profuturo"]].merge(markets[["fecha", *FACTORS]], on="fecha", how="inner")
    return data.dropna(subset=["ret_profuturo", *FACTORS]).sort_values("fecha").reset_index(drop=True)


def fit_predict_ols(x_train: np.ndarray, y_train: np.ndarray, x_test: np.ndarray) -> float:
    design = np.column_stack([np.ones(len(x_train)), x_train])
    beta, *_ = np.linalg.lstsq(design, y_train, rcond=None)
    return float(np.r_[1.0, x_test] @ beta)


def fit_predict_ridge(x_train: np.ndarray, y_train: np.ndarray, x_test: np.ndarray, alpha: float) -> float:
    scaler = StandardScaler()
    x_train_s = scaler.fit_transform(x_train)
    x_test_s = scaler.transform(x_test.reshape(1, -1))
    model = Ridge(alpha=alpha, fit_intercept=True)
    model.fit(x_train_s, y_train * 100.0)
    return float(model.predict(x_test_s)[0] / 100.0)


def fit_predict_huber(
    x_train: np.ndarray,
    y_train: np.ndarray,
    x_test: np.ndarray,
    epsilon: float,
    alpha: float,
) -> float:
    scaler = StandardScaler()
    x_train_s = scaler.fit_transform(x_train)
    x_test_s = scaler.transform(x_test.reshape(1, -1))
    model = HuberRegressor(
        epsilon=epsilon,
        alpha=alpha,
        fit_intercept=True,
        max_iter=3000,
        tol=1e-8,
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", ConvergenceWarning)
        model.fit(x_train_s, y_train * 100.0)
    return float(model.predict(x_test_s)[0] / 100.0)


def rolling_predictions(data: pd.DataFrame, model_name: str, params: dict | None = None) -> pd.DataFrame:
    params = params or {}
    rows: list[dict] = []
    for i in range(WINDOW, len(data)):
        train = data.iloc[i - WINDOW : i]
        row = data.iloc[i]
        x_train = train[FACTORS].to_numpy(float)
        y_train = train["ret_profuturo"].to_numpy(float)
        x_test = row[FACTORS].to_numpy(float)
        if model_name == "OLS":
            pred = fit_predict_ols(x_train, y_train, x_test)
        elif model_name == "RIDGE":
            pred = fit_predict_ridge(x_train, y_train, x_test, float(params["alpha"]))
        elif model_name == "HUBER":
            pred = fit_predict_huber(
                x_train,
                y_train,
                x_test,
                float(params["epsilon"]),
                float(params["alpha"]),
            )
        else:
            raise ValueError(f"Modelo desconocido: {model_name}")
        rows.append(
            {
                "fecha": row["fecha"],
                "ret_real": float(row["ret_profuturo"]),
                "ret_estimado": pred,
                "senal_real": classify([row["ret_profuturo"]])[0],
                "senal_estimada": classify([pred])[0],
            }
        )
    return pd.DataFrame(rows)


def metrics(pred: pd.DataFrame) -> dict:
    if pred.empty:
        return {}
    y = pred["ret_real"].to_numpy(float)
    p = pred["ret_estimado"].to_numpy(float)
    actual = pred["senal_real"].to_numpy(str)
    estimated = pred["senal_estimada"].to_numpy(str)
    exact = actual == estimated
    direction = np.sign(y) == np.sign(p)
    active = np.abs(p) > THRESHOLD
    residual = y - p
    sst = float(np.sum((y - y.mean()) ** 2))
    out = {
        "n": int(len(pred)),
        "correct": int(exact.sum()),
        "classification_accuracy": float(exact.mean()),
        "direction_correct": int(direction.sum()),
        "direction_accuracy": float(direction.mean()),
        "active_n": int(active.sum()),
        "active_correct": int((exact & active).sum()),
        "active_accuracy": float(exact[active].mean()) if active.any() else None,
        "mae_return_pp": float(np.mean(np.abs(residual)) * 100.0),
        "rmse_return_pp": float(np.sqrt(np.mean(residual**2)) * 100.0),
        "r2": float(1.0 - np.sum(residual**2) / sst) if sst > 0 else None,
        "opposite_direction_errors": int((((estimated == "SUBE") & (actual == "BAJA")) | ((estimated == "BAJA") & (actual == "SUBE"))).sum()),
    }
    for signal in ["SUBE", "BAJA", "NEUTRO"]:
        mask = estimated == signal
        out[f"{signal.lower()}_n"] = int(mask.sum())
        out[f"{signal.lower()}_correct"] = int((exact & mask).sum())
        out[f"{signal.lower()}_accuracy"] = float(exact[mask].mean()) if mask.any() else None
    return out


def selection_key(row: dict) -> tuple:
    return (
        float(row["classification_accuracy"]),
        -float(row["mae_return_pp"]),
        -float(row["rmse_return_pp"]),
    )


def main() -> None:
    data = prepare_data()
    ols = rolling_predictions(data, "OLS")
    n = len(ols)
    cut60 = int(np.floor(n * 0.60))
    cut80 = int(np.floor(n * 0.80))
    validation_slice = slice(cut60, cut80)
    test_slice = slice(cut80, n)

    ridge_grid: list[dict] = []
    ridge_predictions: dict[float, pd.DataFrame] = {}
    for alpha in RIDGE_ALPHAS:
        pred = rolling_predictions(data, "RIDGE", {"alpha": alpha})
        ridge_predictions[alpha] = pred
        row = {"model": "RIDGE", "alpha": alpha, "epsilon": None, **metrics(pred.iloc[validation_slice].reset_index(drop=True))}
        ridge_grid.append(row)
    best_ridge_row = max(ridge_grid, key=selection_key)
    best_ridge_alpha = float(best_ridge_row["alpha"])
    ridge = ridge_predictions[best_ridge_alpha]

    huber_grid: list[dict] = []
    huber_predictions: dict[tuple[float, float], pd.DataFrame] = {}
    for epsilon in HUBER_EPSILONS:
        for alpha in HUBER_ALPHAS:
            pred = rolling_predictions(data, "HUBER", {"epsilon": epsilon, "alpha": alpha})
            huber_predictions[(epsilon, alpha)] = pred
            row = {"model": "HUBER", "alpha": alpha, "epsilon": epsilon, **metrics(pred.iloc[validation_slice].reset_index(drop=True))}
            huber_grid.append(row)
    best_huber_row = max(huber_grid, key=selection_key)
    best_huber_key = (float(best_huber_row["epsilon"]), float(best_huber_row["alpha"]))
    huber = huber_predictions[best_huber_key]

    models = {"OLS": ols, "RIDGE": ridge, "HUBER": huber}
    scopes = {
        "validation20": validation_slice,
        "test20": test_slice,
        "last90": slice(max(0, n - 90), n),
        "all_walk_forward": slice(0, n),
    }
    summary_rows: list[dict] = []
    summary: dict[str, dict] = {}
    for scope_name, scope_slice in scopes.items():
        summary[scope_name] = {}
        for name, pred in models.items():
            vals = metrics(pred.iloc[scope_slice].reset_index(drop=True))
            summary[scope_name][name] = vals
            summary_rows.append({"scope": scope_name, "model": name, **vals})

    audit = ols.tail(90).copy().rename(columns={"ret_estimado": "ret_estimado_OLS", "senal_estimada": "senal_OLS"})
    for name, pred in [("RIDGE", ridge), ("HUBER", huber)]:
        temp = pred.tail(90)[["fecha", "ret_estimado", "senal_estimada"]].rename(
            columns={"ret_estimado": f"ret_estimado_{name}", "senal_estimada": f"senal_{name}"}
        )
        audit = audit.merge(temp, on="fecha", how="inner")
    audit["acierto_OLS"] = audit["senal_OLS"] == audit["senal_real"]
    audit["acierto_RIDGE"] = audit["senal_RIDGE"] == audit["senal_real"]
    audit["acierto_HUBER"] = audit["senal_HUBER"] == audit["senal_real"]

    error_audit: dict[str, dict] = {}
    for name in ["RIDGE", "HUBER"]:
        corrected = (~audit["acierto_OLS"]) & audit[f"acierto_{name}"]
        new_errors = audit["acierto_OLS"] & (~audit[f"acierto_{name}"])
        error_audit[name] = {
            "baseline_errors": int((~audit["acierto_OLS"]).sum()),
            "corrected_baseline_errors": int(corrected.sum()),
            "baseline_errors_remaining": int(((~audit["acierto_OLS"]) & (~audit[f"acierto_{name}"])).sum()),
            "new_errors_created": int(new_errors.sum()),
            "net_change_correct": int(audit[f"acierto_{name}"].sum() - audit["acierto_OLS"].sum()),
            "corrected_dates": [str(x.date()) for x in audit.loc[corrected, "fecha"]],
            "new_error_dates": [str(x.date()) for x in audit.loc[new_errors, "fecha"]],
        }

    results = {
        "methodology": {
            "window": WINDOW,
            "threshold": THRESHOLD,
            "factors": FACTORS,
            "n_walk_forward_predictions": n,
            "split": {
                "train_like_60": [str(ols.iloc[0]["fecha"].date()), str(ols.iloc[cut60 - 1]["fecha"].date())],
                "validation20": [str(ols.iloc[cut60]["fecha"].date()), str(ols.iloc[cut80 - 1]["fecha"].date())],
                "test20": [str(ols.iloc[cut80]["fecha"].date()), str(ols.iloc[-1]["fecha"].date())],
            },
            "selection_rule": "maximizar accuracy de 3 clases en validacion; desempatar por menor MAE y RMSE",
            "ridge_grid": RIDGE_ALPHAS,
            "huber_epsilon_grid": HUBER_EPSILONS,
            "huber_alpha_grid": HUBER_ALPHAS,
        },
        "selected_parameters": {
            "RIDGE": {"alpha": best_ridge_alpha, "validation_metrics": best_ridge_row},
            "HUBER": {"epsilon": best_huber_key[0], "alpha": best_huber_key[1], "validation_metrics": best_huber_row},
        },
        "summary": summary,
        "error_audit_last90": error_audit,
    }

    OUT.mkdir(exist_ok=True)
    (OUT / "robust_results.json").write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    pd.DataFrame(summary_rows).to_csv(OUT / "robust_summary.csv", index=False)
    pd.DataFrame(ridge_grid + huber_grid).to_csv(OUT / "robust_validation_grid.csv", index=False)
    audit.to_csv(OUT / "robust_error_audit.csv", index=False)
    print(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    main()
