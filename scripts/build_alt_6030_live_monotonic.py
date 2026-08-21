from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

import build_alt_6030_live as base

MODEL_VERSION = "CONSTRAINED_RIDGE_V2"
POSITIVE_FEATURES = {"ret_.INX", "ret_NDX", "ret_SPBLSCUP"}
RIDGE_LAMBDAS = (0.01, 0.03, 0.1, 0.3, 1.0, 3.0, 10.0)
FIT_LOG: list[dict] = []


def solve_constrained_ridge(x: np.ndarray, y: np.ndarray, ridge_lambda: float) -> np.ndarray:
    """Ridge sobre factores estandarizados con restricciones de signo.

    .INX, NDX y SPBLSCUP nunca pueden tener beta negativa. Los demás factores
    quedan libres. El intercepto no se penaliza.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    mu = x.mean(axis=0)
    scale = x.std(axis=0, ddof=0)
    scale = np.where(scale < 1e-12, 1.0, scale)
    z = (x - mu) / scale
    y_mean = float(y.mean())
    yc = y - y_mean

    b = np.zeros(z.shape[1], dtype=float)
    positive_idx = {i for i, feature in enumerate(base.FEATURES) if feature in POSITIVE_FEATURES}
    denom = np.sum(z * z, axis=0) + float(ridge_lambda)

    for _ in range(20000):
        fitted = z @ b
        max_change = 0.0
        for j in range(z.shape[1]):
            residual_j = yc - fitted + z[:, j] * b[j]
            new_b = float(np.dot(z[:, j], residual_j) / denom[j]) if denom[j] > 0 else 0.0
            if j in positive_idx:
                new_b = max(0.0, new_b)
            delta = new_b - b[j]
            if delta:
                fitted += z[:, j] * delta
                b[j] = new_b
                max_change = max(max_change, abs(delta))
        if max_change < 1e-12:
            break

    raw_beta = b / scale
    intercept = y_mean - float(np.dot(mu, raw_beta))
    beta = np.r_[intercept, raw_beta]
    for j, feature in enumerate(base.FEATURES):
        if feature in POSITIVE_FEATURES and beta[j + 1] < -1e-12:
            raise RuntimeError(f"Restricción monotónica incumplida en {feature}: {beta[j + 1]}")
    return beta


def choose_lambda(train: pd.DataFrame) -> tuple[float, dict[str, float]]:
    """Validación walk-forward interna; no usa observaciones posteriores a la ventana."""
    x = train[base.FEATURES].to_numpy(float)
    y = train["ret_target"].to_numpy(float)
    splits = (35, 40, 45, 50, 55)
    scores: dict[str, float] = {}
    for lam in RIDGE_LAMBDAS:
        errors: list[float] = []
        for end in splits:
            if end >= len(train):
                continue
            valid_end = min(end + 5, len(train))
            beta = solve_constrained_ridge(x[:end], y[:end], lam)
            pred = beta[0] + x[end:valid_end] @ beta[1:]
            errors.extend(np.square(pred - y[end:valid_end]).tolist())
        scores[str(lam)] = float(np.mean(errors)) if errors else float("inf")
    best = min(RIDGE_LAMBDAS, key=lambda lam: (scores[str(lam)], lam))
    return float(best), scores


def monotonic_fit(train: pd.DataFrame) -> tuple[np.ndarray, dict[str, float]]:
    lam, scores = choose_lambda(train)
    x = train[base.FEATURES].to_numpy(float)
    y = train["ret_target"].to_numpy(float)
    beta = solve_constrained_ridge(x, y, lam)
    names = ["intercept", *base.FEATURES]
    coeff = {name: float(value) for name, value in zip(names, beta)}
    FIT_LOG.append({
        "model_version": MODEL_VERSION,
        "estimator": "RIDGE CON RESTRICCIONES DE SIGNO",
        "ridge_lambda": lam,
        "positive_constraints": sorted(POSITIVE_FEATURES),
        "cv_mse_by_lambda": scores,
        "train_start": str(pd.Timestamp(train.iloc[0]["fecha"]).date()),
        "train_end": str(pd.Timestamp(train.iloc[-1]["fecha"]).date()),
        "train_n": int(len(train)),
    })
    return beta, coeff


def main() -> None:
    # Parchea el estimador en el motor existente para conservar exactamente la
    # misma lógica 60/30, tickers, ancla, cadena ciega e histórico.
    base.fit = monotonic_fit

    # No mezclar el ledger de la OLS sin restricción con la versión corregida.
    base.LEDGER_PATH = base.DATA / "alt_6030_shadow_monotonic_v2.csv"
    base.main()

    payload = json.loads(base.OUT_PATH.read_text(encoding="utf-8"))
    current_fit = FIT_LOG[0] if FIT_LOG else {}
    coeff = payload.get("cycle", {}).get("coefficients", {})
    for feature in POSITIVE_FEATURES:
        value = float(coeff.get(feature, 0.0))
        if value < -1e-12:
            raise RuntimeError(f"El modelo publicado conserva beta negativa en {feature}: {value}")

    payload["model"]["name"] = "RIDGE 60/30 · nuevos tickers · monotónico"
    payload["model"]["model_version"] = MODEL_VERSION
    payload["model"]["estimator"] = current_fit.get("estimator")
    payload["model"]["ridge_lambda"] = current_fit.get("ridge_lambda")
    payload["model"]["positive_constraints"] = current_fit.get("positive_constraints")
    payload["model"]["rule"] = (
        "Se mantienen .INX, CPER, EEM, NDX, SPBLSCUP y USD/PEN. Ridge reduce la "
        "inestabilidad por colinealidad .INX/NDX y se exige beta >= 0 para .INX, NDX "
        "y SPBLSCUP. La cadena 60/30 sigue sin reanclaje SBS dentro del bloque."
    )
    payload["cycle"]["fit"] = current_fit
    payload["cycle"]["model_version"] = MODEL_VERSION
    payload["cycle"]["monotonic_positive_features"] = sorted(POSITIVE_FEATURES)

    # Marca cada fila operativa para distinguirla de la primera OLS experimental.
    for row in payload.get("operational_history", []):
        row["model_version"] = MODEL_VERSION
    for row in payload.get("backtest_exact20", {}).get("rows", []):
        row["model_version"] = MODEL_VERSION

    base.OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "model_version": MODEL_VERSION,
        "signal_date": payload.get("signal_date"),
        "vc": payload.get("model", {}).get("vc_estimated"),
        "return": payload.get("model", {}).get("return_estimated"),
        "ridge_lambda": payload.get("model", {}).get("ridge_lambda"),
        "coefficients": coeff,
        "backtest_mae": payload.get("backtest_exact20", {}).get("mae_vc"),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
