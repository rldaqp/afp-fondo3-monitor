from __future__ import annotations

import json
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "rolling90"
OUT = ROOT / "analysis" / "epu_fcx_nem_ablation_profuturo.json"
WINDOW = 90
HORIZONS = [30, 60, 90, 180]
THRESHOLD = 0.001

FIXED = ["ret_SPY", "ret_EEM", "ret_MCHI", "ret_USD_PEN"]
TRIO = ["ret_EPU", "ret_FCX", "ret_NEM"]
FULL = FIXED + TRIO


def classify(value: float) -> str:
    if value > THRESHOLD:
        return "SUBE"
    if value < -THRESHOLD:
        return "BAJA"
    return "NEUTRO"


def read_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce")
    return df.dropna(subset=["fecha"]).sort_values("fecha").reset_index(drop=True)


def model_map() -> dict[str, list[str]]:
    models: dict[str, list[str]] = {"ACTUAL": FULL}
    # Todas las combinaciones posibles de EPU/FCX/NEM manteniendo fijos
    # SPY, EEM, MCHI y USD/PEN. Esto permite ver tanto ablation individual
    # como si una pareja o un solo factor basta.
    for r in range(2, -1, -1):
        for keep in combinations(TRIO, r):
            if r == 2:
                removed = [x for x in TRIO if x not in keep]
                name = "SIN_" + removed[0].replace("ret_", "")
            elif r == 1:
                name = "SOLO_" + keep[0].replace("ret_", "") + "_DEL_TRIO"
            else:
                name = "SIN_EPU_FCX_NEM"
            models[name] = FIXED + list(keep)
    return models


def fit_predict(train: pd.DataFrame, row: pd.Series, features: list[str]) -> float:
    x = train[features].to_numpy(float)
    y = train["ret_target"].to_numpy(float)
    beta = np.linalg.lstsq(np.c_[np.ones(len(x)), x], y, rcond=None)[0]
    return float(np.r_[1.0, row[features].to_numpy(float)] @ beta)


def build_predictions(frame: pd.DataFrame, features: list[str]) -> pd.DataFrame:
    rows: list[dict] = []
    for i in range(WINDOW, len(frame)):
        train = frame.iloc[i - WINDOW:i]
        current = frame.iloc[i]
        pred = fit_predict(train, current, features)
        actual = float(current["ret_target"])
        rows.append({
            "fecha": current["fecha"],
            "pred": pred,
            "actual": actual,
            "pred_class": classify(pred),
            "actual_class": classify(actual),
            "abs_error": abs(pred - actual),
        })
    return pd.DataFrame(rows)


def metrics(pred: pd.DataFrame) -> dict:
    err = pred["pred"].to_numpy(float) - pred["actual"].to_numpy(float)
    return {
        "n": int(len(pred)),
        "start": pred.iloc[0]["fecha"].strftime("%Y-%m-%d"),
        "end": pred.iloc[-1]["fecha"].strftime("%Y-%m-%d"),
        "mae": float(np.mean(np.abs(err))),
        "rmse": float(np.sqrt(np.mean(err ** 2))),
        "direction_accuracy": float((pred["pred_class"] == pred["actual_class"]).mean()),
    }


def vif_table(df: pd.DataFrame, features: list[str]) -> dict:
    x = df[features].to_numpy(float)
    out: dict[str, float | None] = {}
    if len(features) == 1:
        return {"by_feature": {features[0]: 1.0}, "max_vif": 1.0, "max_vif_feature": features[0]}
    for j, feature in enumerate(features):
        y = x[:, j]
        others = np.delete(x, j, axis=1)
        design = np.c_[np.ones(len(others)), others]
        beta = np.linalg.lstsq(design, y, rcond=None)[0]
        fitted = design @ beta
        ss_res = float(np.sum((y - fitted) ** 2))
        ss_tot = float(np.sum((y - np.mean(y)) ** 2))
        if ss_tot <= 1e-20:
            vif = None
        else:
            r2 = 1.0 - ss_res / ss_tot
            vif = float(1.0 / max(1e-12, 1.0 - r2))
        out[feature] = vif
    finite = {k: v for k, v in out.items() if v is not None and np.isfinite(v)}
    return {
        "by_feature": out,
        "max_vif": max(finite.values()) if finite else None,
        "max_vif_feature": max(finite, key=finite.get) if finite else None,
    }


def pairwise_corr(df: pd.DataFrame) -> dict:
    corr = df[TRIO].corr()
    return {
        "EPU_FCX": float(corr.loc["ret_EPU", "ret_FCX"]),
        "EPU_NEM": float(corr.loc["ret_EPU", "ret_NEM"]),
        "FCX_NEM": float(corr.loc["ret_FCX", "ret_NEM"]),
    }


def main() -> None:
    models = model_map()
    markets = read_csv(DATA / "markets.csv")
    sbs = read_csv(DATA / "sbs_profuturo_f3.csv")
    sbs["valor_cuota"] = pd.to_numeric(sbs["valor_cuota"], errors="coerce")
    sbs = sbs.dropna(subset=["valor_cuota"]).drop_duplicates("fecha", keep="last")
    sbs["ret_target"] = sbs["valor_cuota"].pct_change(fill_method=None)

    # Mismas fechas completas para todos los modelos: la comparación no se
    # beneficia de tener más filas cuando se elimina una variable.
    frame = sbs[["fecha", "ret_target"]].merge(markets[["fecha", *FULL]], on="fecha", how="inner")
    frame = frame.loc[frame["fecha"] >= pd.Timestamp("2025-01-01")]
    frame = frame.dropna(subset=["ret_target", *FULL]).sort_values("fecha").drop_duplicates("fecha", keep="last").reset_index(drop=True)
    if len(frame) <= WINDOW + max(HORIZONS):
        raise RuntimeError(f"Solo hay {len(frame)} filas completas; insuficiente para train 90 + evaluación 180")

    predictions = {name: build_predictions(frame, features) for name, features in models.items()}
    dates = predictions["ACTUAL"]["fecha"]
    for name, pred in predictions.items():
        if not pred["fecha"].equals(dates):
            raise RuntimeError(f"Fechas desalineadas en {name}")

    windows: dict[str, dict] = {}
    for h in [*HORIZONS, "ALL"]:
        slices = {name: (pred if h == "ALL" else pred.tail(int(h))) for name, pred in predictions.items()}
        mm = {name: metrics(p.reset_index(drop=True)) for name, p in slices.items()}
        base = mm["ACTUAL"]
        compare = {}
        for name, m in mm.items():
            compare[name] = {
                **m,
                "mae_change_vs_actual_pct": float((m["mae"] / base["mae"] - 1.0) * 100.0),
                "direction_delta_pp_vs_actual": float((m["direction_accuracy"] - base["direction_accuracy"]) * 100.0),
            }
        windows[str(h)] = {
            "models": compare,
            "best_mae": min(mm, key=lambda n: mm[n]["mae"]),
            "best_direction": max(mm, key=lambda n: mm[n]["direction_accuracy"]),
        }

    recent90 = frame.tail(WINDOW).reset_index(drop=True)
    vifs = {name: vif_table(recent90, features) for name, features in models.items()}

    # Valor incremental individual: cuánto cambia el error al sacar cada factor
    # del modelo completo en cada horizonte. Positivo = quitarlo empeora MAE,
    # por tanto ese factor aportaba.
    incremental: dict[str, dict] = {}
    for factor, model_without in [("EPU", "SIN_EPU"), ("FCX", "SIN_FCX"), ("NEM", "SIN_NEM")]:
        incremental[factor] = {}
        for h in [*HORIZONS, "ALL"]:
            full_m = windows[str(h)]["models"]["ACTUAL"]
            wo_m = windows[str(h)]["models"][model_without]
            incremental[factor][str(h)] = {
                "mae_penalty_when_removed_pct": float((wo_m["mae"] / full_m["mae"] - 1.0) * 100.0),
                "direction_change_when_removed_pp": float((wo_m["direction_accuracy"] - full_m["direction_accuracy"]) * 100.0),
            }

    payload = {
        "generated_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "fund": "PROFUTURO",
        "purpose": "Diagnóstico de ablation EPU/FCX/NEM; no modifica visor ni modelo oficial.",
        "method": "OLS rolling 90 sobre las mismas fechas completas. Se prueban todas las combinaciones de EPU, FCX y NEM manteniendo SPY, EEM, MCHI y USD/PEN.",
        "common_complete_rows": int(len(frame)),
        "prediction_rows": int(len(dates)),
        "first_prediction": dates.iloc[0].strftime("%Y-%m-%d"),
        "last_prediction": dates.iloc[-1].strftime("%Y-%m-%d"),
        "models": models,
        "recent90_pairwise_correlations": pairwise_corr(recent90),
        "recent90_vif": vifs,
        "windows": windows,
        "incremental_value": incremental,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
