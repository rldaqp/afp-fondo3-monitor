from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

DATA_PATH = Path("public/habitat/data/fixed_models_2026.csv")
OUT_JSON = Path("analysis/habitat_window_stability.json")
OUT_CSV = Path("analysis/habitat_window_stability.csv")
PUBLIC_JSON = Path("public/habitat/data/window_stability_diagnostic.json")

FACTORS = ["SPY", "EEM", "MCHI", "QQQ", "SPBLSCUP"]
WINDOWS = [30, 50, 60, 90]
ORIGINAL_START = pd.Timestamp("2026-07-07")
ORIGINAL_END = pd.Timestamp("2026-08-17")
VALIDATION_START = pd.Timestamp("2026-08-18")

FACTOR_SETS = {
    "full_5": FACTORS,
    "no_mchi": [f for f in FACTORS if f != "MCHI"],
    "no_spblscup": [f for f in FACTORS if f != "SPBLSCUP"],
    "no_mchi_spblscup": [f for f in FACTORS if f not in {"MCHI", "SPBLSCUP"}],
}


def clean_float(x):
    if x is None:
        return None
    x = float(x)
    if not np.isfinite(x):
        return None
    return x


def metrics(actual: np.ndarray, pred: np.ndarray) -> dict:
    actual = np.asarray(actual, dtype=float)
    pred = np.asarray(pred, dtype=float)
    mask = np.isfinite(actual) & np.isfinite(pred) & (actual != 0)
    if mask.sum() == 0:
        return {"n": 0, "mae_pct": None, "rmse_pct": None, "bias_pct": None, "max_abs_pct": None}
    err_pct = (pred[mask] / actual[mask] - 1.0) * 100.0
    return {
        "n": int(mask.sum()),
        "mae_pct": clean_float(np.mean(np.abs(err_pct))),
        "rmse_pct": clean_float(np.sqrt(np.mean(err_pct ** 2))),
        "bias_pct": clean_float(np.mean(err_pct)),
        "max_abs_pct": clean_float(np.max(np.abs(err_pct))),
    }


def fit_ols(frame: pd.DataFrame, factors: list[str]) -> dict:
    X = frame[factors].to_numpy(dtype=float)
    y = frame["vc_sbs"].to_numpy(dtype=float)
    X1 = np.column_stack([np.ones(len(X)), X])
    beta, *_ = np.linalg.lstsq(X1, y, rcond=None)
    fitted = X1 @ beta
    resid = y - fitted
    ss_res = float(np.sum(resid ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else np.nan

    # Condition number on standardized factor matrix (not raw scales).
    std = X.std(axis=0, ddof=1)
    std[std == 0] = 1.0
    Z = (X - X.mean(axis=0)) / std
    condition_number = float(np.linalg.cond(Z)) if len(X) > len(factors) else np.nan

    # VIF from inverse factor correlation matrix.
    corr = np.corrcoef(Z, rowvar=False)
    inv_corr = np.linalg.pinv(corr)
    vif = {f: clean_float(inv_corr[i, i]) for i, f in enumerate(factors)}

    return {
        "intercept": float(beta[0]),
        "beta": {f: float(beta[i + 1]) for i, f in enumerate(factors)},
        "fitted": fitted,
        "r2": clean_float(r2),
        "condition_number": clean_float(condition_number),
        "vif": vif,
    }


def predict(model: dict, rows: pd.DataFrame, factors: list[str]) -> np.ndarray:
    if rows.empty:
        return np.array([], dtype=float)
    X = rows[factors].to_numpy(dtype=float)
    beta = np.array([model["beta"][f] for f in factors], dtype=float)
    return model["intercept"] + X @ beta


def rows_payload(frame: pd.DataFrame, pred_cols: list[str]) -> list[dict]:
    out = []
    for _, r in frame.iterrows():
        item = {
            "fecha": r["fecha"].strftime("%Y-%m-%d"),
            "vc_sbs": clean_float(r.get("vc_sbs")),
        }
        for c in pred_cols:
            v = r.get(c)
            item[c] = clean_float(v)
            if item["vc_sbs"] is not None and item[c] is not None:
                item[c + "_error_pct"] = clean_float((item[c] / item["vc_sbs"] - 1.0) * 100.0)
        out.append(item)
    return out


def main():
    df = pd.read_csv(DATA_PATH)
    df["fecha"] = pd.to_datetime(df["fecha"])
    df = df.sort_values("fecha").drop_duplicates("fecha", keep="last").reset_index(drop=True)

    for c in FACTORS + ["vc_sbs", "vc_niveles", "vc_retornos"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    valid = df.dropna(subset=FACTORS + ["vc_sbs"]).copy().reset_index(drop=True)
    latest_sbs_date = valid["fecha"].max()
    latest_sbs_vc = float(valid.loc[valid["fecha"].idxmax(), "vc_sbs"])

    pre_dates = valid.loc[valid["fecha"] < ORIGINAL_START, "fecha"]
    pre20_dates = list(pre_dates.tail(20))
    pre20_start = min(pre20_dates) if pre20_dates else None
    pre20_end = max(pre20_dates) if pre20_dates else None

    result: dict = {
        "fund": "HÁBITAT Fondo 3",
        "method": "OLS de niveles con intercepto; prueba anclada al 17/08 y walk-forward estricto usando solo observaciones previas al día estimado.",
        "factors_are_proxies_not_holdings": True,
        "factors": FACTORS,
        "windows": WINDOWS,
        "original_training": {"start": "2026-07-07", "end": "2026-08-17", "n": 30},
        "validation": {"start": "2026-08-18", "end": latest_sbs_date.strftime("%Y-%m-%d")},
        "pre20": {
            "start": pre20_start.strftime("%Y-%m-%d") if pre20_start is not None else None,
            "end": pre20_end.strftime("%Y-%m-%d") if pre20_end is not None else None,
            "n": len(pre20_dates),
        },
        "latest_sbs": {"date": latest_sbs_date.strftime("%Y-%m-%d"), "vc": latest_sbs_vc},
        "anchored_at_2026_08_17": {},
        "walk_forward": {},
        "factor_ablation_anchored_validation": {},
    }

    # A. Models frozen at the original cut-off (17 Aug) with 30/50/60/90 observations.
    anchor_pool = valid[valid["fecha"] <= ORIGINAL_END].copy()
    validation_rows = valid[valid["fecha"] >= VALIDATION_START].copy()
    original_period = valid[(valid["fecha"] >= ORIGINAL_START) & (valid["fecha"] <= ORIGINAL_END)].copy()
    projection_rows = df[(df["fecha"] > latest_sbs_date) & df[FACTORS].notna().all(axis=1)].copy()

    comparison = original_period[["fecha", "vc_sbs"]].copy()
    validation_comparison = validation_rows[["fecha", "vc_sbs"]].copy()

    for w in WINDOWS:
        train = anchor_pool.tail(w).copy()
        if len(train) < w:
            continue
        model = fit_ols(train, FACTORS)
        pred_train = predict(model, train, FACTORS)
        pred_original = predict(model, original_period, FACTORS)
        pred_validation = predict(model, validation_rows, FACTORS)
        pred_projection = predict(model, projection_rows, FACTORS)

        comparison[f"anchored_{w}"] = pred_original
        validation_comparison[f"anchored_{w}"] = pred_validation

        last_train_row = original_period[original_period["fecha"] == ORIGINAL_END]
        last_train_pred = clean_float(predict(model, last_train_row, FACTORS)[0]) if len(last_train_row) else None
        last_train_real = clean_float(last_train_row["vc_sbs"].iloc[0]) if len(last_train_row) else None

        proj = []
        for i, (_, r) in enumerate(projection_rows.iterrows()):
            proj.append({
                "fecha": r["fecha"].strftime("%Y-%m-%d"),
                "vc_est": clean_float(pred_projection[i]),
            })

        result["anchored_at_2026_08_17"][str(w)] = {
            "train_start": train["fecha"].min().strftime("%Y-%m-%d"),
            "train_end": train["fecha"].max().strftime("%Y-%m-%d"),
            "n": int(len(train)),
            "r2_train": model["r2"],
            "condition_number_standardized": model["condition_number"],
            "vif": model["vif"],
            "coefficients": {"intercept": model["intercept"], **model["beta"]},
            "metrics_train_window": metrics(train["vc_sbs"].to_numpy(), pred_train),
            "metrics_original_07jul_17aug": metrics(original_period["vc_sbs"].to_numpy(), pred_original),
            "metrics_validation_18aug_latest": metrics(validation_rows["vc_sbs"].to_numpy(), pred_validation),
            "last_original_training_date": {
                "date": "2026-08-17",
                "vc_sbs": last_train_real,
                "vc_est": last_train_pred,
                "error_pct": clean_float((last_train_pred / last_train_real - 1.0) * 100.0) if last_train_real and last_train_pred else None,
            },
            "projection_after_latest_sbs": proj,
        }

    # Include the published fixed 30 model in the in-sample VC-vs-estimate table.
    if "vc_niveles" in df.columns:
        published = df[(df["fecha"] >= ORIGINAL_START) & (df["fecha"] <= ORIGINAL_END)][["fecha", "vc_sbs", "vc_niveles"]].copy()
        result["published_fixed_30_training_fit"] = {
            "metrics": metrics(published["vc_sbs"].to_numpy(), published["vc_niveles"].to_numpy()),
            "rows": rows_payload(published, ["vc_niveles"]),
        }

    result["anchored_vc_vs_real_through_17aug"] = rows_payload(comparison, [c for c in comparison.columns if c.startswith("anchored_")])
    result["anchored_validation_vc_vs_real"] = rows_payload(validation_comparison, [c for c in validation_comparison.columns if c.startswith("anchored_")])

    # B. Strict one-step walk-forward. Each target is estimated with the immediately preceding W real SBS observations only.
    wf_records = []
    start_eval = pre20_start if pre20_start is not None else ORIGINAL_START
    target_rows = valid[(valid["fecha"] >= start_eval) & (valid["fecha"] <= latest_sbs_date)].copy()

    for _, target in target_rows.iterrows():
        record = {"fecha": target["fecha"], "vc_sbs": float(target["vc_sbs"])}
        prior = valid[valid["fecha"] < target["fecha"]]
        for w in WINDOWS:
            train = prior.tail(w)
            col = f"wf_{w}"
            if len(train) == w:
                model = fit_ols(train, FACTORS)
                one = pd.DataFrame([target])
                record[col] = float(predict(model, one, FACTORS)[0])
            else:
                record[col] = np.nan
        wf_records.append(record)

    wf = pd.DataFrame(wf_records)
    wf_pred_cols = [f"wf_{w}" for w in WINDOWS]
    for w in WINDOWS:
        c = f"wf_{w}"
        segments = {
            "pre20_before_07jul": wf[wf["fecha"].isin(pre20_dates)],
            "original_period_07jul_17aug": wf[(wf["fecha"] >= ORIGINAL_START) & (wf["fecha"] <= ORIGINAL_END)],
            "validation_18aug_latest": wf[wf["fecha"] >= VALIDATION_START],
            "combined_07jul_latest": wf[wf["fecha"] >= ORIGINAL_START],
        }
        result["walk_forward"][str(w)] = {
            name: metrics(seg["vc_sbs"].to_numpy(), seg[c].to_numpy()) for name, seg in segments.items()
        }

    result["walk_forward_rows"] = rows_payload(wf, wf_pred_cols)

    # C. Factor ablation, frozen at 17 Aug, to test whether MCHI/SPBLSCUP are stable proxies.
    for set_name, factors in FACTOR_SETS.items():
        result["factor_ablation_anchored_validation"][set_name] = {}
        for w in WINDOWS:
            train = anchor_pool.dropna(subset=factors + ["vc_sbs"]).tail(w)
            if len(train) < w:
                continue
            model = fit_ols(train, factors)
            pred_val = predict(model, validation_rows, factors)
            pred_last = predict(model, original_period[original_period["fecha"] == ORIGINAL_END], factors)
            result["factor_ablation_anchored_validation"][set_name][str(w)] = {
                "metrics_validation_18aug_latest": metrics(validation_rows["vc_sbs"].to_numpy(), pred_val),
                "last_training_date_est": clean_float(pred_last[0]) if len(pred_last) else None,
                "coefficients": {"intercept": model["intercept"], **model["beta"]},
            }

    # Ranking: prioritize truly unseen validation error for models frozen on 17 Aug.
    ranking = []
    for w, block in result["anchored_at_2026_08_17"].items():
        m = block["metrics_validation_18aug_latest"]
        ranking.append({
            "window": int(w),
            "mae_pct": m["mae_pct"],
            "rmse_pct": m["rmse_pct"],
            "bias_pct": m["bias_pct"],
        })
    ranking.sort(key=lambda x: (float("inf") if x["mae_pct"] is None else x["mae_pct"]))
    result["ranking_anchored_validation_by_mae"] = ranking

    # Flat CSV useful for inspection: real vs anchored and walk-forward over the original+validation period.
    flat = valid[(valid["fecha"] >= ORIGINAL_START) & (valid["fecha"] <= latest_sbs_date)][["fecha", "vc_sbs"]].copy()
    for w in WINDOWS:
        if f"anchored_{w}" in validation_comparison.columns:
            anchor_model_block = result["anchored_at_2026_08_17"][str(w)]
            train = anchor_pool.tail(w)
            model = fit_ols(train, FACTORS)
            flat[f"anchored_{w}"] = predict(model, flat, FACTORS)
        wf_map = wf.set_index("fecha")[f"wf_{w}"] if f"wf_{w}" in wf.columns else pd.Series(dtype=float)
        flat[f"wf_{w}"] = flat["fecha"].map(wf_map)
    if "vc_niveles" in df.columns:
        fixed_map = df.set_index("fecha")["vc_niveles"]
        flat["published_fixed_30"] = flat["fecha"].map(fixed_map)

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    PUBLIC_JSON.parent.mkdir(parents=True, exist_ok=True)
    flat.to_csv(OUT_CSV, index=False)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    OUT_JSON.write_text(text, encoding="utf-8")
    PUBLIC_JSON.write_text(text, encoding="utf-8")

    print(json.dumps({
        "latest_sbs": result["latest_sbs"],
        "ranking": result["ranking_anchored_validation_by_mae"],
        "walk_forward": result["walk_forward"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
