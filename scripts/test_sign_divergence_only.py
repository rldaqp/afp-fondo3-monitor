from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT / "public" / "data" / "fixed_models_2026.json"
MARKETS_PATH = ROOT / "data" / "rolling90" / "markets.csv"
OUT_JSON = ROOT / "analysis" / "sign_divergence_only_test.json"
OUT_CSV = ROOT / "analysis" / "sign_divergence_days.csv"

DISCOVERY_END = pd.Timestamp("2026-07-06")
TRAIN_START = pd.Timestamp("2026-07-07")
TRAIN_END = pd.Timestamp("2026-08-17")
OOS_START = pd.Timestamp("2026-08-18")


def metrics(q: pd.DataFrame, pred_ret_col: str) -> dict:
    q = q.dropna(subset=["target_ret", pred_ret_col]).copy()
    if q.empty:
        return {"n": 0}
    e = (q[pred_ret_col] - q["target_ret"]) * 100.0
    return {
        "n": int(len(q)),
        "mae_pp": float(np.mean(np.abs(e))),
        "rmse_pp": float(np.sqrt(np.mean(e**2))),
        "bias_pp": float(np.mean(e)),
        "direction_accuracy": float(np.mean(np.sign(q[pred_ret_col]) == np.sign(q["target_ret"]))),
    }


def improve(base: dict, corr: dict) -> dict:
    def red(k):
        b, c = base.get(k), corr.get(k)
        if b in (None, 0) or c is None:
            return None
        return float((b-c)/b*100.0)
    return {"mae_reduction_pct": red("mae_pp"), "rmse_reduction_pct": red("rmse_pp")}


def read_markets() -> pd.DataFrame:
    d = pd.read_csv(MARKETS_PATH)
    d["fecha"] = pd.to_datetime(d["fecha"], errors="coerce").dt.normalize()
    for c in ["ret_EPU"]:
        d[c] = pd.to_numeric(d[c], errors="coerce")
    return d[["fecha", "ret_EPU"]].dropna(subset=["fecha"]).drop_duplicates("fecha", keep="last")


def sign_pattern(a: pd.Series, b: pd.Series, name_a: str, name_b: str) -> pd.Series:
    out = pd.Series(pd.NA, index=a.index, dtype="object")
    m1 = (a > 0) & (b < 0)
    m2 = (a < 0) & (b > 0)
    out[m1] = f"{name_a}_UP_{name_b}_DOWN"
    out[m2] = f"{name_a}_DOWN_{name_b}_UP"
    return out


def fit_alphas(train: pd.DataFrame, residual_col: str, pattern_cols: list[str]) -> dict:
    alphas = {}
    counts = {}
    for col in pattern_cols:
        vals = train[col].dropna().unique().tolist()
        for p in vals:
            q = train[train[col] == p][residual_col].dropna()
            key = f"{col}:{p}"
            counts[key] = int(len(q))
            alphas[key] = None if q.empty else float(q.mean())
    return {"alphas": alphas, "counts": counts}


def apply_alphas(d: pd.DataFrame, fit: dict, pattern_cols: list[str]) -> pd.Series:
    corr = pd.Series(0.0, index=d.index, dtype=float)
    for col in pattern_cols:
        for p in d[col].dropna().unique().tolist():
            key = f"{col}:{p}"
            alpha = fit["alphas"].get(key)
            if alpha is not None:
                corr.loc[d[col] == p] += alpha
    return corr


def summarize_patterns(d: pd.DataFrame, residual_col: str, period_name: str) -> dict:
    out = {"period": period_name, "US": {}, "PE": {}}
    for pair, col in [("US", "pattern_US"), ("PE", "pattern_PE")]:
        for p, g in d[d[col].notna()].groupby(col):
            resid = g[residual_col].dropna()
            out[pair][str(p)] = {
                "n": int(len(g)),
                "dates": [x.date().isoformat() for x in g["fecha"]],
                "mean_residual_pp": None if resid.empty else float(resid.mean()*100.0),
                "median_residual_pp": None if resid.empty else float(resid.median()*100.0),
                "base_mae_pp": None if resid.empty else float(np.mean(np.abs(resid))*100.0),
            }
    return out


def main():
    payload = json.loads(MODEL_PATH.read_text(encoding="utf-8"))
    rows = pd.DataFrame(payload["rows"])
    rows["fecha"] = pd.to_datetime(rows["fecha"], errors="coerce").dt.normalize()
    nums = ["vc_sbs", "vc_niveles", "ret_vc_estimado", "SPY", "QQQ", "SPBLSCUP"]
    for c in nums:
        rows[c] = pd.to_numeric(rows[c], errors="coerce")
    rows = rows.sort_values("fecha").drop_duplicates("fecha", keep="last").reset_index(drop=True)

    # Factor returns on the exact model series.
    rows["ret_SPY"] = rows["SPY"].pct_change(fill_method=None)
    rows["ret_QQQ"] = rows["QQQ"].pct_change(fill_method=None)
    rows["ret_SPBLSCUP"] = rows["SPBLSCUP"].pct_change(fill_method=None)

    # Actual SBS return belongs to current date; previous real SBS only.
    rows["prev_vc_sbs"] = rows["vc_sbs"].ffill().shift(1)
    rows["target_ret"] = rows["vc_sbs"] / rows["prev_vc_sbs"] - 1.0
    rows["base_ret_niveles"] = rows["vc_niveles"] / rows["prev_vc_sbs"] - 1.0
    rows["base_ret_retornos"] = rows["ret_vc_estimado"]

    rows = rows.merge(read_markets(), on="fecha", how="left")
    rows["pattern_US"] = sign_pattern(rows["ret_QQQ"], rows["ret_SPY"], "QQQ", "SPY")
    rows["pattern_PE"] = sign_pattern(rows["ret_EPU"], rows["ret_SPBLSCUP"], "EPU", "SPBLSCUP")
    rows["div_US"] = rows["pattern_US"].notna()
    rows["div_PE"] = rows["pattern_PE"].notna()
    rows["div_any"] = rows["div_US"] | rows["div_PE"]

    discovery = rows[(rows["fecha"] <= DISCOVERY_END) & rows["target_ret"].notna()].copy()
    train = rows[(rows["fecha"] >= TRAIN_START) & (rows["fecha"] <= TRAIN_END) & rows["target_ret"].notna()].copy()
    oos = rows[(rows["fecha"] >= OOS_START) & rows["target_ret"].notna()].copy()

    result = {
        "purpose": "Probar correcciones exclusivamente en dias donde los pares tienen signos opuestos; cero correccion en dias normales.",
        "model_version": payload.get("model_version"),
        "definitions": {
            "US": "QQQ y SPY con signos opuestos",
            "PE": "EPU y SPBLSCUP con signos opuestos",
            "correction": "alpha promedio del residual del modelo para cada direccion de divergencia; se suma solo si esa divergencia ocurre",
        },
        "periods": {
            "discovery_pre_0707": {"start": None if discovery.empty else discovery.fecha.min().date().isoformat(), "end": None if discovery.empty else discovery.fecha.max().date().isoformat(), "n": int(len(discovery))},
            "training_current": {"start": "2026-07-07", "end": "2026-08-17", "n": int(len(train))},
            "oos": {"start": "2026-08-18", "end": None if oos.empty else oos.fecha.max().date().isoformat(), "n": int(len(oos))},
        },
        "models": {},
    }

    for model, base_col in [("niveles", "base_ret_niveles"), ("retornos", "base_ret_retornos")]:
        rows[f"resid_{model}"] = rows["target_ret"] - rows[base_col]
        discovery[f"resid_{model}"] = discovery["target_ret"] - discovery[base_col]
        train[f"resid_{model}"] = train["target_ret"] - train[base_col]
        oos[f"resid_{model}"] = oos["target_ret"] - oos[base_col]

        prefit = fit_alphas(discovery, f"resid_{model}", ["pattern_US", "pattern_PE"])
        currfit = fit_alphas(train, f"resid_{model}", ["pattern_US", "pattern_PE"])

        tests = {}
        for fit_name, fit, eval_name, eval_df in [
            ("pre_july_fit", prefit, "training_0707_0817", train),
            ("pre_july_fit", prefit, "oos_0818_plus", oos),
            ("current_fit_0707_0817", currfit, "oos_0818_plus", oos),
        ]:
            q = eval_df.copy()
            q["correction"] = apply_alphas(q, fit, ["pattern_US", "pattern_PE"])
            q["corrected_ret"] = q[base_col] + q["correction"]
            b_all = metrics(q, base_col)
            c_all = metrics(q, "corrected_ret")
            qa = q[q["div_any"]].copy()
            b_div = metrics(qa, base_col)
            c_div = metrics(qa, "corrected_ret")
            key = f"{fit_name}__to__{eval_name}"
            tests[key] = {
                "fit": fit,
                "all_days": {"base": b_all, "corrected": c_all, "improvement": improve(b_all, c_all)},
                "divergence_days_only": {"base": b_div, "corrected": c_div, "improvement": improve(b_div, c_div), "n_divergence": int(len(qa))},
            }

        result["models"][model] = {
            "pattern_stats": {
                "pre_july": summarize_patterns(discovery, f"resid_{model}", "pre_july"),
                "training": summarize_patterns(train, f"resid_{model}", "training"),
                "oos": summarize_patterns(oos, f"resid_{model}", "oos"),
            },
            "tests": tests,
        }

    # Export every historical divergence day for inspection.
    exp = rows[rows["div_any"]].copy()
    keep = [
        "fecha", "vc_sbs", "target_ret", "ret_SPY", "ret_QQQ", "pattern_US",
        "ret_EPU", "ret_SPBLSCUP", "pattern_PE", "base_ret_niveles", "base_ret_retornos",
    ]
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    exp[keep].to_csv(OUT_CSV, index=False)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
