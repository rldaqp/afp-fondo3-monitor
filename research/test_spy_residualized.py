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
OUT = ROOT / "research_outputs" / "spy_residualized"
WINDOW = 90
THRESHOLD = 0.001
EPSILON = 1.1
ALPHA = 0.0001
SPY = "ret_SPY"
OTHER_FEATURES = ["ret_NEM", "ret_FCX", "ret_EPU", "ret_MCHI", "ret_EEM", "ret_USD_PEN"]
FULL_FEATURES = [SPY, *OTHER_FEATURES]
RESIDUAL_FEATURES = ["ret_SPY_residual", *OTHER_FEATURES]


def classify(value: float) -> str:
    if value > THRESHOLD:
        return "SUBE"
    if value < -THRESHOLD:
        return "BAJA"
    return "NEUTRO"


def prepare_data() -> pd.DataFrame:
    sbs = pd.read_csv(DATA / "sbs_profuturo_f3.csv")
    markets = pd.read_csv(DATA / "markets.csv")
    sbs["fecha"] = pd.to_datetime(sbs["fecha"], errors="coerce")
    sbs["valor_cuota"] = pd.to_numeric(sbs["valor_cuota"], errors="coerce")
    sbs = (
        sbs.dropna(subset=["fecha", "valor_cuota"])
        .sort_values("fecha")
        .drop_duplicates("fecha", keep="last")
    )
    sbs["ret_profuturo"] = sbs["valor_cuota"].pct_change(fill_method=None)
    markets["fecha"] = pd.to_datetime(markets["fecha"], errors="coerce")
    for feature in FULL_FEATURES:
        markets[feature] = pd.to_numeric(markets[feature], errors="coerce")
    data = sbs[["fecha", "valor_cuota", "ret_profuturo"]].merge(
        markets[["fecha", *FULL_FEATURES]], on="fecha", how="inner"
    )
    return (
        data.dropna(subset=["ret_profuturo", *FULL_FEATURES])
        .sort_values("fecha")
        .reset_index(drop=True)
    )


def fit_huber(x: np.ndarray, y: np.ndarray) -> tuple[StandardScaler, HuberRegressor]:
    scaler = StandardScaler()
    x_scaled = scaler.fit_transform(x)
    model = HuberRegressor(
        epsilon=EPSILON,
        alpha=ALPHA,
        fit_intercept=True,
        max_iter=3000,
        tol=1e-8,
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", ConvergenceWarning)
        model.fit(x_scaled, y * 100.0)
    return scaler, model


def coefficients_original_scale(
    scaler: StandardScaler,
    model: HuberRegressor,
    features: list[str],
) -> dict[str, float]:
    scale = np.where(
        np.asarray(scaler.scale_, dtype=float) == 0,
        1.0,
        np.asarray(scaler.scale_, dtype=float),
    )
    coef = np.asarray(model.coef_, dtype=float) / scale / 100.0
    intercept = (
        float(model.intercept_)
        - float(np.sum(np.asarray(model.coef_) * np.asarray(scaler.mean_) / scale))
    ) / 100.0
    return {"intercept": intercept, **{f: float(v) for f, v in zip(features, coef)}}


def fit_residualized(
    train: pd.DataFrame,
) -> tuple[LinearRegression, StandardScaler, HuberRegressor, pd.DataFrame]:
    first_stage = LinearRegression().fit(
        train[OTHER_FEATURES].to_numpy(float),
        train[SPY].to_numpy(float),
    )
    spy_fitted = first_stage.predict(train[OTHER_FEATURES].to_numpy(float))
    transformed = train[OTHER_FEATURES].copy()
    transformed.insert(0, "ret_SPY_residual", train[SPY].to_numpy(float) - spy_fitted)
    scaler, model = fit_huber(
        transformed[RESIDUAL_FEATURES].to_numpy(float),
        train["ret_profuturo"].to_numpy(float),
    )
    return first_stage, scaler, model, transformed


def transform_residual_row(row: pd.Series, first_stage: LinearRegression) -> np.ndarray:
    other = row[OTHER_FEATURES].to_numpy(float).reshape(1, -1)
    residual = float(row[SPY]) - float(first_stage.predict(other)[0])
    return np.array([residual, *other.ravel()], dtype=float)


def effective_raw_coefficients(
    residual_beta: dict[str, float],
    first_stage: LinearRegression,
) -> dict[str, float]:
    gamma = float(residual_beta["ret_SPY_residual"])
    result = {
        "intercept": float(residual_beta["intercept"] - gamma * float(first_stage.intercept_)),
        SPY: gamma,
    }
    for feature, first_coef in zip(OTHER_FEATURES, np.asarray(first_stage.coef_, dtype=float)):
        result[feature] = float(residual_beta[feature] - gamma * float(first_coef))
    return result


def predict_full(
    train: pd.DataFrame,
    row: pd.Series,
) -> tuple[float, dict[str, float]]:
    scaler, model = fit_huber(
        train[FULL_FEATURES].to_numpy(float),
        train["ret_profuturo"].to_numpy(float),
    )
    pred = float(
        model.predict(scaler.transform(row[FULL_FEATURES].to_numpy(float).reshape(1, -1)))[0]
        / 100.0
    )
    return pred, coefficients_original_scale(scaler, model, FULL_FEATURES)


def predict_residualized(
    train: pd.DataFrame,
    row: pd.Series,
) -> tuple[float, dict[str, float], dict[str, float], dict[str, object]]:
    first_stage, scaler, model, transformed = fit_residualized(train)
    x_row = transform_residual_row(row, first_stage)
    pred = float(model.predict(scaler.transform(x_row.reshape(1, -1)))[0] / 100.0)
    residual_beta = coefficients_original_scale(scaler, model, RESIDUAL_FEATURES)
    raw_beta = effective_raw_coefficients(residual_beta, first_stage)
    fitted = first_stage.predict(train[OTHER_FEATURES].to_numpy(float))
    residuals = train[SPY].to_numpy(float) - fitted
    diagnostic = {
        "first_stage_r2": float(first_stage.score(train[OTHER_FEATURES].to_numpy(float), train[SPY].to_numpy(float))),
        "spy_std": float(np.std(train[SPY].to_numpy(float), ddof=1)),
        "residual_std": float(np.std(residuals, ddof=1)),
        "residual_to_spy_std_ratio": float(np.std(residuals, ddof=1) / np.std(train[SPY].to_numpy(float), ddof=1)),
        "first_stage_intercept": float(first_stage.intercept_),
        "first_stage_coefficients": {
            feature: float(value)
            for feature, value in zip(OTHER_FEATURES, np.asarray(first_stage.coef_, dtype=float))
        },
        "residual_correlations": {
            feature: float(np.corrcoef(transformed["ret_SPY_residual"], transformed[feature])[0, 1])
            for feature in OTHER_FEATURES
        },
    }
    return pred, residual_beta, raw_beta, diagnostic


def rolling_predictions(data: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: list[dict[str, object]] = []
    coefficients: list[dict[str, object]] = []
    for i in range(WINDOW, len(data)):
        train = data.iloc[i - WINDOW : i]
        row = data.iloc[i]
        pred_full, beta_full = predict_full(train, row)
        pred_resid, beta_resid, beta_effective, diagnostic = predict_residualized(train, row)
        actual = float(row["ret_profuturo"])
        rows.append(
            {
                "row_index": i,
                "fecha": row["fecha"],
                "ret_profuturo": actual,
                "real_class": classify(actual),
                "pred_full7": pred_full,
                "class_full7": classify(pred_full),
                "pred_spy_residual": pred_resid,
                "class_spy_residual": classify(pred_resid),
                "first_stage_r2": diagnostic["first_stage_r2"],
                "spy_residual_std_ratio": diagnostic["residual_to_spy_std_ratio"],
            }
        )
        coefficients.append(
            {
                "row_index": i,
                "fecha_objetivo": row["fecha"],
                "ventana_inicio": train.iloc[0]["fecha"],
                "ventana_fin": train.iloc[-1]["fecha"],
                "full_ret_SPY": beta_full[SPY],
                "residual_basis_SPY": beta_resid["ret_SPY_residual"],
                "effective_raw_SPY": beta_effective[SPY],
                "first_stage_r2": diagnostic["first_stage_r2"],
                "residual_std_ratio": diagnostic["residual_to_spy_std_ratio"],
            }
        )
    return pd.DataFrame(rows), pd.DataFrame(coefficients)


def metrics(frame: pd.DataFrame, pred_col: str) -> dict[str, object]:
    work = frame.dropna(subset=["ret_profuturo", pred_col]).copy()
    work["real_class"] = work["ret_profuturo"].map(classify)
    work["pred_class"] = work[pred_col].map(classify)
    work["hit"] = work["real_class"].eq(work["pred_class"])
    work["direction_hit"] = np.sign(work["ret_profuturo"]).eq(np.sign(work[pred_col]))
    error = work[pred_col] - work["ret_profuturo"]
    hard_reversal = (
        (work["real_class"].eq("SUBE") & work["pred_class"].eq("BAJA"))
        | (work["real_class"].eq("BAJA") & work["pred_class"].eq("SUBE"))
    )
    result: dict[str, object] = {
        "n": int(len(work)),
        "correct": int(work["hit"].sum()),
        "accuracy": float(work["hit"].mean()) if len(work) else None,
        "direction_correct": int(work["direction_hit"].sum()),
        "direction_accuracy": float(work["direction_hit"].mean()) if len(work) else None,
        "mae_pp": float(error.abs().mean() * 100.0) if len(work) else None,
        "rmse_pp": float(np.sqrt(np.mean(error * error)) * 100.0) if len(work) else None,
        "r2": float(r2_score(work["ret_profuturo"], work[pred_col])) if len(work) > 1 else None,
        "hard_reversals": int(hard_reversal.sum()),
    }
    for signal in ["SUBE", "BAJA", "NEUTRO"]:
        subset = work[work["pred_class"].eq(signal)]
        result[f"{signal.lower()}_n"] = int(len(subset))
        result[f"{signal.lower()}_accuracy"] = None if subset.empty else float(subset["hit"].mean())
    return result


def split_name(index: int, n: int) -> str:
    train_end = int(np.floor(n * 0.60))
    validation_end = int(np.floor(n * 0.80))
    if index < train_end:
        return "train"
    if index < validation_end:
        return "validation"
    return "test"


def current_predictions(data: pd.DataFrame) -> dict[str, object]:
    latest = json.loads((ROOT / "public" / "data" / "latest.json").read_text(encoding="utf-8"))
    pending = pd.read_csv(DATA / "pending_predictions.csv")
    pending["fecha"] = pd.to_datetime(pending["fecha"], errors="coerce")
    for feature in FULL_FEATURES:
        pending[feature] = pd.to_numeric(pending.get(feature), errors="coerce")

    train = data.tail(WINDOW).copy()
    full_scaler, full_model = fit_huber(
        train[FULL_FEATURES].to_numpy(float),
        train["ret_profuturo"].to_numpy(float),
    )
    full_beta = coefficients_original_scale(full_scaler, full_model, FULL_FEATURES)

    first_stage, residual_scaler, residual_model, transformed = fit_residualized(train)
    residual_beta = coefficients_original_scale(residual_scaler, residual_model, RESIDUAL_FEATURES)
    effective_beta = effective_raw_coefficients(residual_beta, first_stage)
    fitted_spy = first_stage.predict(train[OTHER_FEATURES].to_numpy(float))
    spy_residuals = train[SPY].to_numpy(float) - fitted_spy

    last_sbs = pd.Timestamp(str(latest["latest_sbs_date"]))
    work = (
        pending[pending["fecha"].gt(last_sbs)]
        .dropna(subset=["fecha", *FULL_FEATURES])
        .sort_values("fecha")
    )
    full_vc = float(latest["latest_sbs_vc"])
    residual_vc = float(latest["latest_sbs_vc"])
    full_chain: list[dict[str, object]] = []
    residual_chain: list[dict[str, object]] = []
    for _, row in work.iterrows():
        full_pred = float(
            full_model.predict(
                full_scaler.transform(row[FULL_FEATURES].to_numpy(float).reshape(1, -1))
            )[0]
            / 100.0
        )
        residual_x = transform_residual_row(row, first_stage)
        residual_pred = float(
            residual_model.predict(residual_scaler.transform(residual_x.reshape(1, -1)))[0]
            / 100.0
        )
        full_vc *= 1.0 + full_pred
        residual_vc *= 1.0 + residual_pred
        full_chain.append(
            {
                "fecha": row["fecha"].date().isoformat(),
                "ret_estimado": full_pred,
                "senal": classify(full_pred),
                "vc_estimado": full_vc,
            }
        )
        residual_chain.append(
            {
                "fecha": row["fecha"].date().isoformat(),
                "ret_estimado": residual_pred,
                "senal": classify(residual_pred),
                "vc_estimado": residual_vc,
                "spy_residual": float(residual_x[0]),
            }
        )

    residual_frame = transformed.copy()
    return {
        "training": {
            "n": int(len(train)),
            "start": train.iloc[0]["fecha"].date().isoformat(),
            "end": train.iloc[-1]["fecha"].date().isoformat(),
        },
        "full7": {
            "coefficients": full_beta,
            "latest": full_chain[-1] if full_chain else None,
            "pending_series": full_chain,
        },
        "spy_residualized": {
            "coefficients_residual_basis": residual_beta,
            "coefficients_effective_raw_basis": effective_beta,
            "latest": residual_chain[-1] if residual_chain else None,
            "pending_series": residual_chain,
            "first_stage": {
                "r2": float(first_stage.score(train[OTHER_FEATURES].to_numpy(float), train[SPY].to_numpy(float))),
                "intercept": float(first_stage.intercept_),
                "coefficients": {
                    feature: float(value)
                    for feature, value in zip(OTHER_FEATURES, np.asarray(first_stage.coef_, dtype=float))
                },
                "spy_std": float(np.std(train[SPY].to_numpy(float), ddof=1)),
                "residual_std": float(np.std(spy_residuals, ddof=1)),
                "residual_std_ratio": float(np.std(spy_residuals, ddof=1) / np.std(train[SPY].to_numpy(float), ddof=1)),
                "residual_correlations": {
                    feature: float(np.corrcoef(residual_frame["ret_SPY_residual"], residual_frame[feature])[0, 1])
                    for feature in OTHER_FEATURES
                },
            },
        },
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    data = prepare_data()
    if len(data) <= WINDOW:
        raise RuntimeError(f"Muestra insuficiente: {len(data)}")

    paired, coefficient_history = rolling_predictions(data)
    paired["split"] = paired["row_index"].map(lambda i: split_name(int(i), len(data)))
    paired["hit_full7"] = paired["real_class"].eq(paired["class_full7"])
    paired["hit_spy_residual"] = paired["real_class"].eq(paired["class_spy_residual"])

    latest90 = paired.tail(WINDOW).copy()
    corrected = (~latest90["hit_full7"]) & latest90["hit_spy_residual"]
    new_errors = latest90["hit_full7"] & (~latest90["hit_spy_residual"])

    split_metrics: dict[str, dict[str, object]] = {}
    for split in ["train", "validation", "test"]:
        subset = paired[paired["split"].eq(split)]
        split_metrics[split] = {
            "full7": metrics(subset, "pred_full7"),
            "spy_residualized": metrics(subset, "pred_spy_residual"),
        }

    train_end = int(np.floor(len(data) * 0.60))
    validation_end = int(np.floor(len(data) * 0.80))
    result = {
        "method": {
            "window": WINDOW,
            "threshold": THRESHOLD,
            "huber_epsilon": EPSILON,
            "huber_alpha": ALPHA,
            "target": "same-date Profuturo Fondo 3 return",
            "full_features": FULL_FEATURES,
            "residual_features": RESIDUAL_FEATURES,
            "first_stage": "Within each rolling training window, OLS regresses SPY on NEM, FCX, EPU, MCHI, EEM and USD/PEN. Huber receives the SPY residual plus those six factors.",
            "leakage_control": "Both the SPY first stage and Huber are fitted only on the previous 90 complete observations for every target date.",
            "note": "Residualization is a reparameterization of the same seven-factor information set; improvement must be demonstrated out of sample.",
        },
        "sample": {
            "n": int(len(data)),
            "start": data.iloc[0]["fecha"].date().isoformat(),
            "end": data.iloc[-1]["fecha"].date().isoformat(),
            "rolling_predictions_n": int(len(paired)),
            "raw_60_20_20": {
                "train_n": train_end,
                "train_start": data.iloc[0]["fecha"].date().isoformat(),
                "train_end": data.iloc[train_end - 1]["fecha"].date().isoformat(),
                "validation_n": validation_end - train_end,
                "validation_start": data.iloc[train_end]["fecha"].date().isoformat(),
                "validation_end": data.iloc[validation_end - 1]["fecha"].date().isoformat(),
                "test_n": len(data) - validation_end,
                "test_start": data.iloc[validation_end]["fecha"].date().isoformat(),
                "test_end": data.iloc[-1]["fecha"].date().isoformat(),
            },
        },
        "latest90": {
            "date_start": latest90.iloc[0]["fecha"].date().isoformat(),
            "date_end": latest90.iloc[-1]["fecha"].date().isoformat(),
            "full7": metrics(latest90, "pred_full7"),
            "spy_residualized": metrics(latest90, "pred_spy_residual"),
            "corrected_errors": int(corrected.sum()),
            "new_errors": int(new_errors.sum()),
            "net_correct": int(corrected.sum() - new_errors.sum()),
            "corrected_dates": latest90.loc[corrected, "fecha"].dt.date.astype(str).tolist(),
            "new_error_dates": latest90.loc[new_errors, "fecha"].dt.date.astype(str).tolist(),
            "signal_changes": int((latest90["class_full7"] != latest90["class_spy_residual"]).sum()),
        },
        "chronological_60_20_20": split_metrics,
        "coefficient_stability": {
            "full_spy": {
                "n": int(len(coefficient_history)),
                "negative_n": int((coefficient_history["full_ret_SPY"] < 0).sum()),
                "negative_share": float((coefficient_history["full_ret_SPY"] < 0).mean()),
                "median": float(coefficient_history["full_ret_SPY"].median()),
                "latest": float(coefficient_history.iloc[-1]["full_ret_SPY"]),
            },
            "residual_spy": {
                "n": int(len(coefficient_history)),
                "negative_n": int((coefficient_history["residual_basis_SPY"] < 0).sum()),
                "negative_share": float((coefficient_history["residual_basis_SPY"] < 0).mean()),
                "median": float(coefficient_history["residual_basis_SPY"].median()),
                "latest": float(coefficient_history.iloc[-1]["residual_basis_SPY"]),
            },
            "first_stage_r2": {
                "median": float(coefficient_history["first_stage_r2"].median()),
                "latest": float(coefficient_history.iloc[-1]["first_stage_r2"]),
            },
            "residual_std_ratio": {
                "median": float(coefficient_history["residual_std_ratio"].median()),
                "latest": float(coefficient_history.iloc[-1]["residual_std_ratio"]),
            },
        },
        "current": current_predictions(data),
    }

    paired.to_csv(OUT / "paired_predictions.csv", index=False)
    coefficient_history.to_csv(OUT / "coefficient_history.csv", index=False)
    (OUT / "results.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
