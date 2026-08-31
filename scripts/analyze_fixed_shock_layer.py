from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
FIXED = ROOT / "public" / "data" / "fixed_models_2026.csv"
META = ROOT / "public" / "data" / "fixed_models_2026.json"
MARKETS = ROOT / "data" / "rolling90" / "markets.csv"
OUT = ROOT / "analysis" / "fixed_shock_layer_test.json"
OUT_DAILY = ROOT / "analysis" / "fixed_shock_layer_daily.csv"

TRAIN_START = pd.Timestamp("2026-07-07")
TRAIN_END = pd.Timestamp("2026-08-17")
VALIDATION_START = pd.Timestamp("2026-08-18")
ROLLING_Z = 30
THRESHOLDS = [1.0, 1.5, 2.0]
FEATURE_SETS = {
    "US": ["z_US"],
    "PE": ["z_PE"],
    "CH": ["z_CH"],
    "ALL3": ["z_US", "z_PE", "z_CH"],
}
MODELS = {
    "niveles": "base_ret_niveles",
    "retornos": "base_ret_retornos",
}


def finite(v) -> bool:
    try:
        return v is not None and np.isfinite(float(v))
    except Exception:
        return False


def load_frame() -> tuple[pd.DataFrame, dict]:
    df = pd.read_csv(FIXED)
    df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce").dt.normalize()
    df = df.dropna(subset=["fecha"]).sort_values("fecha").drop_duplicates("fecha", keep="last").reset_index(drop=True)

    numeric = ["SPY", "EEM", "MCHI", "QQQ", "SPBLSCUP", "vc_sbs", "vc_niveles", "ret_vc_estimado", "vc_retornos"]
    for c in numeric:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    markets = pd.read_csv(MARKETS)
    markets["fecha"] = pd.to_datetime(markets["fecha"], errors="coerce").dt.normalize()
    markets["ret_EPU"] = pd.to_numeric(markets["ret_EPU"], errors="coerce")
    markets = markets.dropna(subset=["fecha"]).sort_values("fecha").drop_duplicates("fecha", keep="last")
    df = df.merge(markets[["fecha", "ret_EPU"]], on="fecha", how="left")

    factors = ["SPY", "EEM", "MCHI", "QQQ", "SPBLSCUP"]
    for c in factors:
        df[f"ret_{c}"] = df[c].pct_change(fill_method=None)

    # Target y ancla exactamente sobre el backbone diario del modelo fijo.
    df["prev_vc"] = df["vc_sbs"].shift(1)
    df["target_ret"] = df["vc_sbs"] / df["prev_vc"] - 1.0
    df["base_ret_retornos"] = df["ret_vc_estimado"]
    df["base_ret_niveles"] = df["vc_niveles"] / df["prev_vc"] - 1.0

    # Tres desacoples propuestos.
    df["D_US"] = df["ret_QQQ"] - df["ret_SPY"]
    df["D_PE"] = df["ret_EPU"] - df["ret_SPBLSCUP"]
    df["D_CH"] = df["ret_MCHI"] - df["ret_EEM"]

    for name in ["US", "PE", "CH"]:
        d = df[f"D_{name}"]
        mu = d.shift(1).rolling(ROLLING_Z, min_periods=ROLLING_Z).mean()
        sd = d.shift(1).rolling(ROLLING_Z, min_periods=ROLLING_Z).std(ddof=1)
        df[f"z_{name}"] = (d - mu) / sd.replace(0.0, np.nan)

    meta = json.loads(META.read_text(encoding="utf-8"))
    return df, meta


def shock_matrix(d: pd.DataFrame, cols: list[str], threshold: float) -> np.ndarray:
    arr = d[cols].to_numpy(float)
    return np.where(np.abs(arr) >= threshold, arr, 0.0)


def fit_gamma(X: np.ndarray, y: np.ndarray) -> np.ndarray:
    if X.size == 0 or X.shape[1] == 0:
        return np.zeros(0, dtype=float)
    return np.linalg.lstsq(X, y, rcond=None)[0]


def metric_block(d: pd.DataFrame, pred_ret: np.ndarray | pd.Series) -> dict:
    rr = np.asarray(pred_ret, dtype=float)
    yvc = d["vc_sbs"].to_numpy(float)
    pvc0 = d["prev_vc"].to_numpy(float)
    target_ret = d["target_ret"].to_numpy(float)
    pred_vc = pvc0 * (1.0 + rr)
    err_pct = (pred_vc / yvc - 1.0) * 100.0
    valid = np.isfinite(err_pct) & np.isfinite(rr) & np.isfinite(target_ret)
    if not valid.any():
        return {"n": 0, "mae_pct": None, "rmse_pct": None, "direction_accuracy": None, "bias_pct": None}
    e = err_pct[valid]
    rrv = rr[valid]
    trv = target_ret[valid]
    return {
        "n": int(valid.sum()),
        "mae_pct": float(np.mean(np.abs(e))),
        "rmse_pct": float(np.sqrt(np.mean(e ** 2))),
        "direction_accuracy": float(np.mean(np.sign(rrv) == np.sign(trv))),
        "bias_pct": float(np.mean(e)),
    }


def loo_predictions(train: pd.DataFrame, base_col: str, cols: list[str], threshold: float) -> tuple[np.ndarray, list[dict]]:
    X = shock_matrix(train, cols, threshold)
    residual = train["target_ret"].to_numpy(float) - train[base_col].to_numpy(float)
    base = train[base_col].to_numpy(float)
    out = np.full(len(train), np.nan, dtype=float)
    betas = []
    for i in range(len(train)):
        mask = np.ones(len(train), dtype=bool)
        mask[i] = False
        beta = fit_gamma(X[mask], residual[mask])
        out[i] = base[i] + float(X[i] @ beta)
        betas.append({cols[j]: float(beta[j]) for j in range(len(cols))})
    return out, betas


def improvement(base: dict, corrected: dict) -> dict:
    ans = {}
    for key in ["mae_pct", "rmse_pct"]:
        b = base.get(key)
        c = corrected.get(key)
        if finite(b) and finite(c) and float(b) != 0:
            ans[f"{key}_reduction_pct"] = float((float(b) - float(c)) / float(b) * 100.0)
        else:
            ans[f"{key}_reduction_pct"] = None
    return ans


def active_counts(X: np.ndarray, cols: list[str]) -> dict:
    return {
        "any": int(np.any(X != 0.0, axis=1).sum()),
        **{cols[j]: int((X[:, j] != 0.0).sum()) for j in range(len(cols))},
    }


def main() -> None:
    df, meta = load_frame()
    required = ["vc_sbs", "prev_vc", "target_ret", "base_ret_niveles", "base_ret_retornos", "z_US", "z_PE", "z_CH"]
    usable = df.dropna(subset=required).copy().reset_index(drop=True)
    train = usable[(usable["fecha"] >= TRAIN_START) & (usable["fecha"] <= TRAIN_END)].copy().reset_index(drop=True)
    oos = usable[usable["fecha"] >= VALIDATION_START].copy().reset_index(drop=True)

    if len(train) < 20:
        raise RuntimeError(f"Entrenamiento insuficiente para shocks: {len(train)}")
    if len(oos) == 0:
        raise RuntimeError("No hay observaciones OOS con SBS y z-scores completos")

    payload = {
        "purpose": "Diagnóstico de una segunda capa de shocks sobre los modelos fijos vigentes; no modifica coeficientes base ni el visor.",
        "model_version": meta.get("model_version"),
        "base_equations": meta.get("models"),
        "training_period": {"start": TRAIN_START.date().isoformat(), "end": TRAIN_END.date().isoformat(), "n": int(len(train))},
        "oos_period": {"start": oos.iloc[0]["fecha"].date().isoformat(), "end": oos.iloc[-1]["fecha"].date().isoformat(), "n": int(len(oos))},
        "shock_definition": {
            "US": "R_QQQ - R_SPY",
            "PE": "R_EPU - R_SPBLSCUP",
            "CH": "R_MCHI - R_EEM",
            "zscore": "(D_t - media de las 30 sesiones anteriores) / desviación estándar de las 30 sesiones anteriores; shift(1), sin fuga futura",
            "feature": "x = z si |z| >= umbral; x = 0 en otro caso",
            "correction": "R_corregido = R_base + sum(gamma_k * x_k); sin intercepto en la capa de shock",
        },
        "selection_rule": "Elegir por menor MAE leave-one-out dentro del periodo de entrenamiento; OOS desde 18/08 no participa en la selección.",
        "thresholds_tested": THRESHOLDS,
        "feature_sets_tested": FEATURE_SETS,
        "models": {},
    }

    daily_selected = []

    for model_name, base_col in MODELS.items():
        base_train = metric_block(train, train[base_col].to_numpy(float))
        base_oos = metric_block(oos, oos[base_col].to_numpy(float))
        candidates = []

        for threshold in THRESHOLDS:
            for set_name, cols in FEATURE_SETS.items():
                loo_pred, _ = loo_predictions(train, base_col, cols, threshold)
                loo_metrics = metric_block(train, loo_pred)

                Xtr = shock_matrix(train, cols, threshold)
                resid = train["target_ret"].to_numpy(float) - train[base_col].to_numpy(float)
                gamma = fit_gamma(Xtr, resid)
                Xoos = shock_matrix(oos, cols, threshold)
                corr_oos = Xoos @ gamma
                pred_oos = oos[base_col].to_numpy(float) + corr_oos
                oos_metrics = metric_block(oos, pred_oos)

                shock_mask = np.any(Xoos != 0.0, axis=1)
                if shock_mask.any():
                    oos_shock = oos.loc[shock_mask].copy().reset_index(drop=True)
                    base_shock = metric_block(oos_shock, oos.loc[shock_mask, base_col].to_numpy(float))
                    corr_shock = metric_block(oos_shock, pred_oos[shock_mask])
                else:
                    base_shock = {"n": 0, "mae_pct": None, "rmse_pct": None, "direction_accuracy": None, "bias_pct": None}
                    corr_shock = dict(base_shock)

                candidates.append({
                    "feature_set": set_name,
                    "features": cols,
                    "threshold": threshold,
                    "train_active": active_counts(Xtr, cols),
                    "oos_active": active_counts(Xoos, cols),
                    "gamma": {cols[j]: float(gamma[j]) for j in range(len(cols))},
                    "gamma_pp_per_z": {cols[j]: float(gamma[j] * 100.0) for j in range(len(cols))},
                    "train_loo": loo_metrics,
                    "train_loo_improvement_vs_base": improvement(base_train, loo_metrics),
                    "oos": oos_metrics,
                    "oos_improvement_vs_base": improvement(base_oos, oos_metrics),
                    "oos_shock_days": {
                        "base": base_shock,
                        "corrected": corr_shock,
                        "improvement": improvement(base_shock, corr_shock),
                    },
                })

        ranked = sorted(
            candidates,
            key=lambda r: (
                float("inf") if not finite(r["train_loo"].get("mae_pct")) else float(r["train_loo"]["mae_pct"]),
                float("inf") if not finite(r["train_loo"].get("rmse_pct")) else float(r["train_loo"]["rmse_pct"]),
            ),
        )
        selected = ranked[0]
        cols = selected["features"]
        threshold = float(selected["threshold"])
        Xtr = shock_matrix(train, cols, threshold)
        resid = train["target_ret"].to_numpy(float) - train[base_col].to_numpy(float)
        gamma = fit_gamma(Xtr, resid)
        Xoos = shock_matrix(oos, cols, threshold)
        correction = Xoos @ gamma
        pred = oos[base_col].to_numpy(float) + correction

        payload["models"][model_name] = {
            "base_train": base_train,
            "base_oos": base_oos,
            "selected_by_train_loo": selected,
            "ranking_by_train_loo": ranked,
        }

        for i, r in oos.iterrows():
            pred_vc_base = float(r["prev_vc"] * (1.0 + r[base_col]))
            pred_vc_corr = float(r["prev_vc"] * (1.0 + pred[i]))
            rec = {
                "model": model_name,
                "fecha": r["fecha"].date().isoformat(),
                "actual_vc": float(r["vc_sbs"]),
                "prev_vc": float(r["prev_vc"]),
                "target_ret": float(r["target_ret"]),
                "base_ret": float(r[base_col]),
                "correction_ret": float(correction[i]),
                "corrected_ret": float(pred[i]),
                "base_vc": pred_vc_base,
                "corrected_vc": pred_vc_corr,
                "z_US": float(r["z_US"]),
                "z_PE": float(r["z_PE"]),
                "z_CH": float(r["z_CH"]),
                "selected_feature_set": selected["feature_set"],
                "selected_threshold": threshold,
                "shock_active": bool(np.any(Xoos[i] != 0.0)),
            }
            daily_selected.append(rec)

    # Chequeo contra métricas publicadas del modelo vigente.
    published = meta.get("metrics", {}).get("validation_from_2026_08_18", {})
    checks = {}
    for model_name in MODELS:
        calc = payload["models"][model_name]["base_oos"]
        pub = published.get(model_name, {})
        checks[model_name] = {
            "calculated_n": calc.get("n"),
            "published_n": pub.get("n"),
            "calculated_mae_pct": calc.get("mae_pct"),
            "published_mae_pct": pub.get("mae_pct"),
            "mae_abs_diff": None if not (finite(calc.get("mae_pct")) and finite(pub.get("mae_pct"))) else abs(float(calc["mae_pct"]) - float(pub["mae_pct"])),
        }
    payload["base_metric_reproduction_check"] = checks

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    pd.DataFrame(daily_selected).to_csv(OUT_DAILY, index=False)

    summary = {
        m: {
            "base_oos": payload["models"][m]["base_oos"],
            "selected": payload["models"][m]["selected_by_train_loo"],
        }
        for m in MODELS
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
