from __future__ import annotations

import json
import warnings
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.decomposition import PCA
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import HuberRegressor
from sklearn.metrics import r2_score
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "rolling90"
OUT = ROOT / "research_outputs" / "global_pca_factor"
WINDOW = 90
THRESHOLD = 0.001
EPSILON = 1.1
ALPHA = 0.0001

FULL_FEATURES = [
    "ret_SPY",
    "ret_NEM",
    "ret_FCX",
    "ret_EPU",
    "ret_MCHI",
    "ret_EEM",
    "ret_USD_PEN",
]
GLOBAL4 = ["ret_SPY", "ret_EPU", "ret_MCHI", "ret_EEM"]
ALL_ETFS = ["ret_SPY", "ret_NEM", "ret_FCX", "ret_EPU", "ret_MCHI", "ret_EEM"]


@dataclass(frozen=True)
class Spec:
    code: str
    pca_features: tuple[str, ...] = ()
    n_components: int = 0
    retained_features: tuple[str, ...] = ()


SPECS = [
    Spec(code="full7", retained_features=tuple(FULL_FEATURES)),
    Spec(
        code="global4_pc1",
        pca_features=tuple(GLOBAL4),
        n_components=1,
        retained_features=("ret_NEM", "ret_FCX", "ret_USD_PEN"),
    ),
    Spec(
        code="global4_pc2",
        pca_features=tuple(GLOBAL4),
        n_components=2,
        retained_features=("ret_NEM", "ret_FCX", "ret_USD_PEN"),
    ),
    Spec(
        code="all6_pc1",
        pca_features=tuple(ALL_ETFS),
        n_components=1,
        retained_features=("ret_USD_PEN",),
    ),
]


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
    sbs = (
        sbs.dropna(subset=["fecha", "valor_cuota"])
        .sort_values("fecha")
        .drop_duplicates("fecha", keep="last")
    )
    sbs["ret_profuturo"] = sbs["valor_cuota"].pct_change(fill_method=None)
    markets["fecha"] = pd.to_datetime(markets["fecha"], errors="coerce")
    for col in FULL_FEATURES:
        markets[col] = pd.to_numeric(markets[col], errors="coerce")
    data = sbs[["fecha", "valor_cuota", "ret_profuturo"]].merge(
        markets[["fecha", *FULL_FEATURES]], on="fecha", how="inner"
    )
    return (
        data.dropna(subset=["ret_profuturo", *FULL_FEATURES])
        .sort_values("fecha")
        .reset_index(drop=True)
    )


def build_design(
    train: pd.DataFrame,
    row: pd.Series,
    spec: Spec,
) -> tuple[np.ndarray, np.ndarray, dict[str, object]]:
    if spec.n_components == 0:
        x_train = train[list(spec.retained_features)].to_numpy(float)
        x_row = row[list(spec.retained_features)].to_numpy(float).reshape(1, -1)
        return x_train, x_row, {
            "design_features": list(spec.retained_features),
            "explained_variance_ratio": [],
            "pca_loadings": {},
        }

    pca_cols = list(spec.pca_features)
    pca_scaler = StandardScaler()
    z_train = pca_scaler.fit_transform(train[pca_cols].to_numpy(float))
    z_row = pca_scaler.transform(row[pca_cols].to_numpy(float).reshape(1, -1))
    pca = PCA(n_components=spec.n_components, svd_solver="full")
    pc_train = pca.fit_transform(z_train)
    pc_row = pca.transform(z_row)

    retained = list(spec.retained_features)
    if retained:
        x_train = np.column_stack([pc_train, train[retained].to_numpy(float)])
        x_row = np.column_stack([pc_row, row[retained].to_numpy(float).reshape(1, -1)])
    else:
        x_train = pc_train
        x_row = pc_row

    pc_names = [f"PC{i + 1}" for i in range(spec.n_components)]
    loadings = {
        pc_names[i]: {feature: float(pca.components_[i, j]) for j, feature in enumerate(pca_cols)}
        for i in range(spec.n_components)
    }
    return x_train, x_row, {
        "design_features": [*pc_names, *retained],
        "explained_variance_ratio": [float(v) for v in pca.explained_variance_ratio_],
        "pca_loadings": loadings,
    }


def fit_huber(x_train: np.ndarray, y_train: np.ndarray) -> tuple[StandardScaler, HuberRegressor]:
    scaler = StandardScaler()
    xs = scaler.fit_transform(x_train)
    model = HuberRegressor(
        epsilon=EPSILON,
        alpha=ALPHA,
        fit_intercept=True,
        max_iter=3000,
        tol=1e-8,
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", ConvergenceWarning)
        model.fit(xs, y_train * 100.0)
    return scaler, model


def one_prediction(train: pd.DataFrame, row: pd.Series, spec: Spec) -> tuple[float, dict[str, object]]:
    x_train, x_row, diag = build_design(train, row, spec)
    scaler, model = fit_huber(x_train, train["ret_profuturo"].to_numpy(float))
    pred = float(model.predict(scaler.transform(x_row))[0] / 100.0)
    diag["huber_coefficients_standardized"] = {
        feature: float(value)
        for feature, value in zip(diag["design_features"], np.asarray(model.coef_, dtype=float))
    }
    return pred, diag


def rolling_predictions(data: pd.DataFrame, spec: Spec) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: list[dict[str, object]] = []
    diagnostics: list[dict[str, object]] = []
    for i in range(WINDOW, len(data)):
        train = data.iloc[i - WINDOW : i]
        row = data.iloc[i]
        pred, diag = one_prediction(train, row, spec)
        rows.append(
            {
                "row_index": i,
                "fecha": row["fecha"],
                "ret_profuturo": float(row["ret_profuturo"]),
                f"pred_{spec.code}": pred,
                f"class_{spec.code}": classify(pred),
                "real_class": classify(float(row["ret_profuturo"])),
            }
        )
        diagnostics.append(
            {
                "row_index": i,
                "fecha_objetivo": row["fecha"],
                "ventana_inicio": train.iloc[0]["fecha"],
                "ventana_fin": train.iloc[-1]["fecha"],
                "modelo": spec.code,
                "explained_variance_pc1": (
                    diag["explained_variance_ratio"][0]
                    if diag["explained_variance_ratio"]
                    else np.nan
                ),
                "explained_variance_total": (
                    float(sum(diag["explained_variance_ratio"]))
                    if diag["explained_variance_ratio"]
                    else np.nan
                ),
                "pca_loadings_json": json.dumps(diag["pca_loadings"], ensure_ascii=False),
                "huber_coefficients_json": json.dumps(
                    diag["huber_coefficients_standardized"], ensure_ascii=False
                ),
            }
        )
    return pd.DataFrame(rows), pd.DataFrame(diagnostics)


def metrics(frame: pd.DataFrame, pred_col: str) -> dict[str, object]:
    w = frame.dropna(subset=["ret_profuturo", pred_col]).copy()
    w["real_class"] = w["ret_profuturo"].map(classify)
    w["pred_class"] = w[pred_col].map(classify)
    w["hit"] = w["real_class"].eq(w["pred_class"])
    err = w[pred_col] - w["ret_profuturo"]
    active = w[w["pred_class"].ne("NEUTRO") & w["real_class"].ne("NEUTRO")]
    result: dict[str, object] = {
        "n": int(len(w)),
        "correct": int(w["hit"].sum()),
        "accuracy": float(w["hit"].mean()) if len(w) else None,
        "mae_pp": float(err.abs().mean() * 100.0) if len(w) else None,
        "rmse_pp": float(np.sqrt(np.mean(err * err)) * 100.0) if len(w) else None,
        "r2": float(r2_score(w["ret_profuturo"], w[pred_col])) if len(w) > 1 else None,
        "raw_direction_accuracy": float(
            (np.sign(w[pred_col]) == np.sign(w["ret_profuturo"])).mean()
        ) if len(w) else None,
        "active_direction_accuracy": float(
            (np.sign(active[pred_col]) == np.sign(active["ret_profuturo"])).mean()
        ) if len(active) else None,
        "active_n": int(len(active)),
        "hard_reversals": int(
            (
                ((w["pred_class"] == "SUBE") & (w["real_class"] == "BAJA"))
                | ((w["pred_class"] == "BAJA") & (w["real_class"] == "SUBE"))
            ).sum()
        ),
    }
    for signal in ["SUBE", "BAJA", "NEUTRO"]:
        sub = w[w["pred_class"].eq(signal)]
        result[f"{signal.lower()}_n"] = int(len(sub))
        result[f"{signal.lower()}_accuracy"] = None if sub.empty else float(sub["hit"].mean())
    return result


def split_name(idx: int, n: int) -> str:
    train_end = int(np.floor(n * 0.60))
    validation_end = int(np.floor(n * 0.80))
    if idx < train_end:
        return "train"
    if idx < validation_end:
        return "validation"
    return "test"


def current_prediction(data: pd.DataFrame, spec: Spec) -> dict[str, object]:
    latest = json.loads((ROOT / "public" / "data" / "latest.json").read_text(encoding="utf-8"))
    pending = pd.read_csv(DATA / "pending_predictions.csv")
    pending["fecha"] = pd.to_datetime(pending["fecha"], errors="coerce")
    for f in FULL_FEATURES:
        pending[f] = pd.to_numeric(pending.get(f), errors="coerce")

    train = data.tail(WINDOW).copy()
    base_vc = float(latest["latest_sbs_vc"])
    last_sbs = pd.Timestamp(latest["latest_sbs_date"])
    chain: list[dict[str, object]] = []
    last_diag: dict[str, object] = {}
    work = pending[pending["fecha"].gt(last_sbs)].dropna(subset=["fecha", *FULL_FEATURES]).sort_values("fecha")
    for _, row in work.iterrows():
        pred, diag = one_prediction(train, row, spec)
        base_vc *= 1.0 + pred
        chain.append(
            {
                "fecha": row["fecha"].date().isoformat(),
                "ret_estimado": pred,
                "senal": classify(pred),
                "vc_estimado": base_vc,
            }
        )
        last_diag = diag
    return {
        "training_start": train.iloc[0]["fecha"].date().isoformat(),
        "training_end": train.iloc[-1]["fecha"].date().isoformat(),
        "training_n": int(len(train)),
        "latest": chain[-1] if chain else None,
        "pending_series": chain,
        "design_features": last_diag.get("design_features", []),
        "explained_variance_ratio": last_diag.get("explained_variance_ratio", []),
        "pca_loadings": last_diag.get("pca_loadings", {}),
        "huber_coefficients_standardized": last_diag.get("huber_coefficients_standardized", {}),
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    data = prepare_data()
    if len(data) <= WINDOW:
        raise RuntimeError(f"Muestra insuficiente: {len(data)}")

    predictions: dict[str, pd.DataFrame] = {}
    diag_frames: list[pd.DataFrame] = []
    paired: pd.DataFrame | None = None
    for spec in SPECS:
        pred, diag = rolling_predictions(data, spec)
        predictions[spec.code] = pred
        diag_frames.append(diag)
        cols = ["row_index", "fecha", f"pred_{spec.code}", f"class_{spec.code}"]
        if paired is None:
            paired = pred.copy()
        else:
            paired = paired.merge(pred[cols], on=["row_index", "fecha"], how="inner")

    assert paired is not None
    paired["split"] = paired["row_index"].map(lambda i: split_name(int(i), len(data)))
    paired["hit_full7"] = paired["real_class"].eq(paired["class_full7"])
    latest90 = paired.tail(WINDOW).copy()

    split_metrics: dict[str, dict[str, dict[str, object]]] = {}
    for split in ["train", "validation", "test"]:
        sub = paired[paired["split"].eq(split)]
        split_metrics[split] = {
            spec.code: metrics(sub, f"pred_{spec.code}") for spec in SPECS
        }

    candidate_codes = [spec.code for spec in SPECS if spec.code != "full7"]
    validation_ranking = sorted(
        candidate_codes,
        key=lambda code: (
            -float(split_metrics["validation"][code]["accuracy"]),
            float(split_metrics["validation"][code]["mae_pp"]),
            float(split_metrics["validation"][code]["rmse_pp"]),
        ),
    )
    selected = validation_ranking[0]

    comparisons: dict[str, dict[str, object]] = {}
    for code in candidate_codes:
        candidate_hit = latest90["real_class"].eq(latest90[f"class_{code}"])
        baseline_hit = latest90["hit_full7"]
        corrected = (~baseline_hit) & candidate_hit
        new_errors = baseline_hit & (~candidate_hit)
        comparisons[code] = {
            "corrected_errors": int(corrected.sum()),
            "new_errors": int(new_errors.sum()),
            "net_correct": int(corrected.sum() - new_errors.sum()),
            "corrected_dates": latest90.loc[corrected, "fecha"].dt.date.astype(str).tolist(),
            "new_error_dates": latest90.loc[new_errors, "fecha"].dt.date.astype(str).tolist(),
            "signal_changes": int((latest90["class_full7"] != latest90[f"class_{code}"]).sum()),
            "max_abs_prediction_difference_pp": float(
                (latest90[f"pred_{code}"] - latest90["pred_full7"]).abs().max() * 100.0
            ),
        }

    diagnostics = pd.concat(diag_frames, ignore_index=True)
    pca_summary: dict[str, dict[str, object]] = {}
    for spec in SPECS:
        if spec.n_components == 0:
            continue
        d = diagnostics[diagnostics["modelo"].eq(spec.code)].copy()
        pca_summary[spec.code] = {
            "pc1_explained_variance_median": float(d["explained_variance_pc1"].median()),
            "pc1_explained_variance_latest": float(d.iloc[-1]["explained_variance_pc1"]),
            "total_explained_variance_median": float(d["explained_variance_total"].median()),
            "total_explained_variance_latest": float(d.iloc[-1]["explained_variance_total"]),
            "latest_loadings": json.loads(d.iloc[-1]["pca_loadings_json"]),
        }

    result = {
        "method": {
            "window": WINDOW,
            "threshold": THRESHOLD,
            "huber_epsilon": EPSILON,
            "huber_alpha": ALPHA,
            "baseline": "Huber rolling90 con siete factores",
            "candidates": {
                "global4_pc1": "PC1 de SPY/EPU/MCHI/EEM + NEM + FCX + USD/PEN",
                "global4_pc2": "PC1 y PC2 de SPY/EPU/MCHI/EEM + NEM + FCX + USD/PEN",
                "all6_pc1": "PC1 de los seis ETF + USD/PEN",
            },
            "pca_leakage_control": "Scaler y PCA se ajustan exclusivamente dentro de cada ventana previa de 90 observaciones",
            "model_leakage_control": "Cada retorno objetivo se predice usando solo las 90 observaciones anteriores",
            "selection_rule": "Mayor exactitud en validación; desempate por menor MAE y luego RMSE",
        },
        "sample": {
            "n": int(len(data)),
            "start": data.iloc[0]["fecha"].date().isoformat(),
            "end": data.iloc[-1]["fecha"].date().isoformat(),
            "rolling_predictions_n": int(len(paired)),
        },
        "latest90": {
            spec.code: metrics(latest90, f"pred_{spec.code}") for spec in SPECS
        },
        "comparisons_vs_full7_latest90": comparisons,
        "chronological_60_20_20": split_metrics,
        "validation_ranking": validation_ranking,
        "selected_on_validation": selected,
        "selected_test_metrics": split_metrics["test"][selected],
        "baseline_test_metrics": split_metrics["test"]["full7"],
        "pca_diagnostics": pca_summary,
        "current": {spec.code: current_prediction(data, spec) for spec in SPECS},
    }

    paired.to_csv(OUT / "paired_predictions.csv", index=False)
    diagnostics.to_csv(OUT / "pca_diagnostics.csv", index=False)
    (OUT / "results.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
