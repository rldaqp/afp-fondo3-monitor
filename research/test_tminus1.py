from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

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

ROOT = Path(__file__).resolve().parents[1]
MARKETS = ROOT / "data" / "rolling90" / "markets.csv"
SBS = ROOT / "data" / "rolling90" / "sbs_profuturo_f3.csv"
OUT = ROOT / "research_outputs"


def classify(values: pd.Series | np.ndarray) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    return np.where(arr > THRESHOLD, "SUBE", np.where(arr < -THRESHOLD, "BAJA", "NEUTRO"))


def ols_predict(x_train: np.ndarray, y_train: np.ndarray, x_test: np.ndarray) -> float:
    design = np.column_stack([np.ones(len(x_train)), x_train])
    beta, *_ = np.linalg.lstsq(design, y_train, rcond=None)
    return float(np.r_[1.0, x_test] @ beta)


def rolling_predictions(df: pd.DataFrame, features: list[str]) -> pd.DataFrame:
    use = df.dropna(subset=["ret_profuturo", *features]).copy().reset_index(drop=True)
    rows: list[dict] = []
    for i in range(WINDOW, len(use)):
        train = use.iloc[i - WINDOW : i]
        row = use.iloc[i]
        pred = ols_predict(
            train[features].to_numpy(float),
            train["ret_profuturo"].to_numpy(float),
            row[features].to_numpy(float),
        )
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
    actual_class = pred["senal_real"].to_numpy(str)
    predicted_class = pred["senal_estimada"].to_numpy(str)
    exact = predicted_class == actual_class
    direction = np.sign(p) == np.sign(y)
    active = np.abs(p) > THRESHOLD
    residual = y - p
    sst = float(np.sum((y - y.mean()) ** 2))
    r2 = float(1.0 - np.sum(residual**2) / sst) if sst > 0 else np.nan
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
        "r2": r2,
    }
    for signal in ["SUBE", "BAJA", "NEUTRO"]:
        mask = predicted_class == signal
        out[f"{signal.lower()}_n"] = int(mask.sum())
        out[f"{signal.lower()}_correct"] = int((exact & mask).sum())
        out[f"{signal.lower()}_accuracy"] = float(exact[mask].mean()) if mask.any() else None
    return out


def segment_metrics(pred: pd.DataFrame, start: int, end: int) -> dict:
    return metrics(pred.iloc[start:end].reset_index(drop=True))


def main() -> None:
    markets = pd.read_csv(MARKETS, parse_dates=["fecha"]).sort_values("fecha")
    sbs = pd.read_csv(SBS, parse_dates=["fecha"]).sort_values("fecha")
    sbs["ret_profuturo"] = sbs["valor_cuota"].pct_change(fill_method=None)

    # t-1 es la sesión de mercado inmediatamente anterior disponible.
    for factor in FACTORS:
        markets[f"{factor}_lag1"] = markets[factor].shift(1)

    data = sbs[["fecha", "valor_cuota", "ret_profuturo"]].merge(markets, on="fecha", how="inner")
    feature_sets = {
        "t": FACTORS,
        "t_minus_1": [f"{f}_lag1" for f in FACTORS],
        "t_plus_t_minus_1": FACTORS + [f"{f}_lag1" for f in FACTORS],
    }

    predictions = {name: rolling_predictions(data, feats) for name, feats in feature_sets.items()}

    # Ventana comparable: fechas presentes en los tres modelos.
    common_dates = set(predictions["t"]["fecha"])
    for name in ["t_minus_1", "t_plus_t_minus_1"]:
        common_dates &= set(predictions[name]["fecha"])
    common_dates = sorted(common_dates)
    comparable = {
        name: frame[frame["fecha"].isin(common_dates)].sort_values("fecha").reset_index(drop=True)
        for name, frame in predictions.items()
    }

    last90 = {name: metrics(frame.tail(90).reset_index(drop=True)) for name, frame in comparable.items()}

    # Corte cronológico 60/20/20 sobre predicciones walk-forward comparables.
    n = len(common_dates)
    cut60 = int(np.floor(n * 0.60))
    cut80 = int(np.floor(n * 0.80))
    split = {
        "n_common_predictions": n,
        "train_like_60": [str(common_dates[0].date()), str(common_dates[cut60 - 1].date())] if cut60 else None,
        "validation_20": [str(common_dates[cut60].date()), str(common_dates[cut80 - 1].date())],
        "test_20": [str(common_dates[cut80].date()), str(common_dates[-1].date())],
        "validation": {name: segment_metrics(frame, cut60, cut80) for name, frame in comparable.items()},
        "test": {name: segment_metrics(frame, cut80, n) for name, frame in comparable.items()},
    }

    # Auditoría de los 14 errores del modelo t en las últimas 90 fechas comparables.
    base90 = comparable["t"].tail(90).reset_index(drop=True)
    combo90 = comparable["t_plus_t_minus_1"].tail(90).reset_index(drop=True)
    audit = base90.merge(
        combo90[["fecha", "ret_estimado", "senal_estimada"]],
        on="fecha",
        suffixes=("_t", "_combo"),
    )
    audit["acierto_t"] = audit["senal_estimada_t"] == audit["senal_real"]
    audit["acierto_combo"] = audit["senal_estimada_combo"] == audit["senal_real"]
    errors_t = audit[~audit["acierto_t"]].copy()
    errors_t["estado_combo"] = np.select(
        [errors_t["acierto_combo"], ~errors_t["acierto_combo"]],
        ["CORREGIDO", "SIGUE_ERROR"],
        default="",
    )
    new_errors = audit[audit["acierto_t"] & ~audit["acierto_combo"]].copy()

    results = {
        "methodology": {
            "window": WINDOW,
            "threshold": THRESHOLD,
            "factors": FACTORS,
            "t_minus_1_definition": "sesion de mercado inmediatamente anterior disponible",
            "models": {k: v for k, v in feature_sets.items()},
        },
        "last90_common": last90,
        "split_60_20_20_on_walk_forward_predictions": split,
        "error_audit": {
            "baseline_errors": int((~audit["acierto_t"]).sum()),
            "baseline_correct": int(audit["acierto_t"].sum()),
            "corrected_by_combo": int((~audit["acierto_t"] & audit["acierto_combo"]).sum()),
            "baseline_errors_remaining": int((~audit["acierto_t"] & ~audit["acierto_combo"]).sum()),
            "new_errors_created_by_combo": int((audit["acierto_t"] & ~audit["acierto_combo"]).sum()),
            "net_change_correct": int(audit["acierto_combo"].sum() - audit["acierto_t"].sum()),
        },
    }

    OUT.mkdir(exist_ok=True)
    (OUT / "tminus1_results.json").write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")

    errors_cols = [
        "fecha",
        "ret_real",
        "senal_real",
        "ret_estimado_t",
        "senal_estimada_t",
        "ret_estimado_combo",
        "senal_estimada_combo",
        "estado_combo",
    ]
    errors_t[errors_cols].to_csv(OUT / "tminus1_baseline_errors.csv", index=False)
    new_cols = [
        "fecha",
        "ret_real",
        "senal_real",
        "ret_estimado_t",
        "senal_estimada_t",
        "ret_estimado_combo",
        "senal_estimada_combo",
    ]
    new_errors[new_cols].to_csv(OUT / "tminus1_new_errors.csv", index=False)

    summary_rows = []
    for scope, scope_metrics in [("last90", last90), ("validation20", split["validation"]), ("test20", split["test"])]:
        for name, vals in scope_metrics.items():
            summary_rows.append({"scope": scope, "model": name, **vals})
    pd.DataFrame(summary_rows).to_csv(OUT / "tminus1_summary.csv", index=False)

    print(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    main()
