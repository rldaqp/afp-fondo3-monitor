from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "public" / "data" / "fixed_models_2026.json"
OUT = ROOT / "public" / "data" / "model_health.json"

TRAIN_START = pd.Timestamp("2026-07-07")
VALIDATION_START = pd.Timestamp("2026-08-18")
FACTORS = ["SPY", "EEM", "MCHI", "QQQ", "SPBLSCUP"]
WINDOW = 30
SIGNAL_THRESHOLD = 0.01


def finite(v):
    try:
        return v is not None and np.isfinite(float(v))
    except Exception:
        return False


def ols_fit(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    X = np.column_stack([np.ones(len(x)), x])
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    return beta


def predict(beta: np.ndarray, x: np.ndarray) -> float:
    return float(beta[0] + np.dot(beta[1:], x))


def metrics(errors, dirs_actual=None, dirs_pred=None):
    e = np.asarray([x for x in errors if finite(x)], dtype=float)
    out = {
        "n": int(e.size),
        "mae_pct": float(np.mean(np.abs(e))) if e.size else None,
        "rmse_pct": float(np.sqrt(np.mean(e ** 2))) if e.size else None,
        "bias_pct": float(np.mean(e)) if e.size else None,
    }
    if dirs_actual is not None and dirs_pred is not None:
        pairs = [
            (float(a), float(p))
            for a, p in zip(dirs_actual, dirs_pred)
            if finite(a) and finite(p)
        ]
        out["direction_n"] = len(pairs)
        out["direction_accuracy"] = (
            float(np.mean([np.sign(a) == np.sign(p) for a, p in pairs]))
            if pairs else None
        )
    return out


def tail_metrics(eval_rows, n):
    d = eval_rows[-n:] if len(eval_rows) > n else eval_rows
    return metrics(
        [r["base_error_pct"] for r in d],
        [r.get("actual_return") for r in d],
        [r.get("base_pred_return") for r in d],
    )


def challenger_metrics(eval_rows):
    return metrics(
        [r["challenger_error_pct"] for r in eval_rows],
        [r.get("actual_return") for r in eval_rows],
        [r.get("challenger_pred_return") for r in eval_rows],
    )


def improvement(base, challenger, key):
    b, c = base.get(key), challenger.get(key)
    if not finite(b) or not finite(c) or float(b) == 0:
        return None
    return float(1.0 - float(c) / float(b))


def health_status(eval_rows, base_full, chall_full):
    n = len(eval_rows)
    mae_gain = improvement(base_full, chall_full, "mae_pct")
    rmse_gain = improvement(base_full, chall_full, "rmse_pct")
    wins = [
        abs(r["challenger_error_pct"]) < abs(r["base_error_pct"])
        for r in eval_rows
        if finite(r.get("challenger_error_pct")) and finite(r.get("base_error_pct"))
    ]
    win_share = float(np.mean(wins)) if wins else None
    recent5 = wins[-5:]
    recent5_wins = int(sum(recent5)) if recent5 else 0
    recent10 = tail_metrics(eval_rows, 10)

    if n < 10:
        return {
            "code": "INSUFFICIENT",
            "label": "MANTENER · MUESTRA AÚN CORTA",
            "reason": f"Solo hay {n} observaciones fuera de muestra. Se requieren al menos 10 para una primera alerta y 15 para considerar recalibración.",
            "mae_improvement": mae_gain,
            "rmse_improvement": rmse_gain,
            "challenger_win_share": win_share,
            "challenger_recent5_wins": recent5_wins,
        }

    base_dir = base_full.get("direction_accuracy")
    chall_dir = chall_full.get("direction_accuracy")
    material = (
        finite(mae_gain) and mae_gain >= 0.15
        and finite(rmse_gain) and rmse_gain >= 0.10
        and finite(win_share) and win_share >= 0.60
        and (
            not finite(base_dir) or not finite(chall_dir)
            or float(chall_dir) >= float(base_dir) - 0.05
        )
    )
    persistent = len(recent5) >= 5 and recent5_wins >= 4
    recent_degradation = False
    if finite(recent10.get("mae_pct")) and finite(base_full.get("mae_pct")) and float(base_full["mae_pct"]) > 0:
        recent_degradation |= float(recent10["mae_pct"]) > 1.25 * float(base_full["mae_pct"])
    if finite(recent10.get("bias_pct")):
        recent_degradation |= abs(float(recent10["bias_pct"])) > 0.30
    if recent10.get("direction_n", 0) >= 8 and finite(recent10.get("direction_accuracy")):
        recent_degradation |= float(recent10["direction_accuracy"]) < 0.55

    if n >= 30 and material and persistent:
        code, label = "CHANGE", "CAMBIO RECOMENDADO"
        reason = "El Rolling-30 supera materialmente al modelo base y la ventaja es persistente. Revisar coeficientes antes de promoverlo a modelo oficial."
    elif n >= 15 and material and persistent:
        code, label = "RECALIBRATE", "RECALIBRAR · MANTENER EN SOMBRA"
        reason = "El challenger muestra una mejora material, pero aún conviene acumular evidencia antes de sustituir el modelo base."
    elif recent_degradation or (finite(mae_gain) and mae_gain >= 0.10):
        code, label = "WATCH", "VIGILAR"
        reason = "Hay señales de deterioro reciente o el challenger empieza a mejorar al modelo base. Todavía no se cumple el umbral de cambio."
    else:
        code, label = "MAINTAIN", "MANTENER"
        reason = "No existe evidencia suficiente de que recalibrar mejore de forma consistente al modelo base."

    return {
        "code": code,
        "label": label,
        "reason": reason,
        "mae_improvement": mae_gain,
        "rmse_improvement": rmse_gain,
        "challenger_win_share": win_share,
        "challenger_recent5_wins": recent5_wins,
    }


def beta_dict(beta):
    return {"intercept": float(beta[0]), **{f: float(beta[i + 1]) for i, f in enumerate(FACTORS)}}


def effect_drift(base_coeff, chall_beta, x_window):
    s = np.nanstd(x_window, axis=0, ddof=1)
    base = np.asarray([float(base_coeff[f]) for f in FACTORS]) * s
    chall = np.asarray(chall_beta[1:], dtype=float) * s
    den = float(np.sum(np.abs(base)))
    return float(np.sum(np.abs(chall - base)) / den) if den > 0 else None


def rolling_level(df, base_coeff):
    eval_rows = []
    last_beta = None
    last_window = None
    previous_challenger_pred = None
    for idx, row in df.iterrows():
        d = row["fecha"]
        if d < VALIDATION_START or not finite(row["vc_sbs"]):
            continue
        hist = df.loc[
            (df["fecha"] < d)
            & (df["fecha"] >= TRAIN_START)
            & df["vc_sbs"].notna()
            & df[FACTORS].notna().all(axis=1)
        ].tail(WINDOW)
        if len(hist) < WINDOW or not row[FACTORS].notna().all():
            continue
        xh = hist[FACTORS].to_numpy(float)
        yh = hist["vc_sbs"].to_numpy(float)
        beta = ols_fit(xh, yh)
        pred = predict(beta, row[FACTORS].to_numpy(float))
        actual = float(row["vc_sbs"])
        base_pred = float(row["vc_niveles"])
        base_err = (base_pred / actual - 1.0) * 100.0
        chall_err = (pred / actual - 1.0) * 100.0
        prev_idx = idx - 1
        actual_ret = None
        base_ret = None
        if prev_idx >= 0 and finite(df.iloc[prev_idx]["vc_sbs"]):
            prev_actual = float(df.iloc[prev_idx]["vc_sbs"])
            actual_ret = actual / prev_actual - 1.0
        if prev_idx >= 0 and finite(df.iloc[prev_idx]["vc_niveles"]):
            base_ret = base_pred / float(df.iloc[prev_idx]["vc_niveles"]) - 1.0
        chall_ret = pred / previous_challenger_pred - 1.0 if finite(previous_challenger_pred) else None
        eval_rows.append({
            "date": d.date().isoformat(),
            "base_error_pct": base_err,
            "challenger_error_pct": chall_err,
            "actual_return": actual_ret,
            "base_pred_return": base_ret,
            "challenger_pred_return": chall_ret,
            "challenger_prediction": pred,
        })
        previous_challenger_pred = pred
        last_beta = beta
        last_window = xh

    base_full = metrics(
        [r["base_error_pct"] for r in eval_rows],
        [r["actual_return"] for r in eval_rows],
        [r["base_pred_return"] for r in eval_rows],
    )
    chall_full = challenger_metrics(eval_rows)
    status = health_status(eval_rows, base_full, chall_full)
    return {
        "evaluation": eval_rows,
        "base": {
            "full": base_full,
            "recent_5": tail_metrics(eval_rows, 5),
            "recent_10": tail_metrics(eval_rows, 10),
            "recent_20": tail_metrics(eval_rows, 20),
        },
        "challenger": {
            "window": WINDOW,
            "full": chall_full,
            "coefficients": beta_dict(last_beta) if last_beta is not None else None,
            "effect_drift": effect_drift(base_coeff, last_beta, last_window) if last_beta is not None else None,
        },
        "status": status,
    }


def rolling_returns(df, base_coeff):
    dfx = df.copy()
    dfx["actual_return"] = dfx["vc_sbs"].pct_change(fill_method=None)
    for f in FACTORS:
        dfx[f"ret_{f}"] = dfx[f].pct_change(fill_method=None)
    ret_cols = [f"ret_{f}" for f in FACTORS]

    eval_rows = []
    last_beta = None
    last_window = None
    for idx, row in dfx.iterrows():
        d = row["fecha"]
        if d < VALIDATION_START or not finite(row["vc_sbs"]):
            continue
        hist = dfx.loc[
            (dfx["fecha"] < d)
            & (dfx["fecha"] >= TRAIN_START)
            & dfx["actual_return"].notna()
            & dfx[ret_cols].notna().all(axis=1)
        ].tail(WINDOW)
        if len(hist) < WINDOW or not row[ret_cols].notna().all():
            continue
        xh = hist[ret_cols].to_numpy(float)
        yh = hist["actual_return"].to_numpy(float)
        beta = ols_fit(xh, yh)
        rhat = predict(beta, row[ret_cols].to_numpy(float))
        prev = dfx.iloc[idx - 1] if idx > 0 else None
        if prev is None or not finite(prev["vc_sbs"]):
            continue
        prev_actual = float(prev["vc_sbs"])
        pred_vc = prev_actual * (1.0 + rhat)
        actual = float(row["vc_sbs"])
        base_pred = float(row["vc_retornos"])
        base_err = (base_pred / actual - 1.0) * 100.0
        chall_err = (pred_vc / actual - 1.0) * 100.0
        actual_ret = actual / prev_actual - 1.0
        base_ret = float(row["ret_vc_estimado"])
        eval_rows.append({
            "date": d.date().isoformat(),
            "base_error_pct": base_err,
            "challenger_error_pct": chall_err,
            "actual_return": actual_ret,
            "base_pred_return": base_ret,
            "challenger_pred_return": rhat,
            "challenger_prediction": pred_vc,
        })
        last_beta = beta
        last_window = xh

    base_full = metrics(
        [r["base_error_pct"] for r in eval_rows],
        [r["actual_return"] for r in eval_rows],
        [r["base_pred_return"] for r in eval_rows],
    )
    chall_full = challenger_metrics(eval_rows)
    status = health_status(eval_rows, base_full, chall_full)
    return {
        "evaluation": eval_rows,
        "base": {
            "full": base_full,
            "recent_5": tail_metrics(eval_rows, 5),
            "recent_10": tail_metrics(eval_rows, 10),
            "recent_20": tail_metrics(eval_rows, 20),
        },
        "challenger": {
            "window": WINDOW,
            "full": chall_full,
            "coefficients": beta_dict(last_beta) if last_beta is not None else None,
            "effect_drift": effect_drift(base_coeff, last_beta, last_window) if last_beta is not None else None,
        },
        "status": status,
    }


def signal_stats(df):
    d = df.copy()
    d["level_return"] = d["vc_niveles"].pct_change(fill_method=None)
    d["actual_return"] = d["vc_sbs"].pct_change(fill_method=None)
    d = d.loc[(d["fecha"] >= VALIDATION_START) & d["vc_sbs"].notna()].copy()
    sig = d.loc[d["level_return"] >= SIGNAL_THRESHOLD]
    rows = []
    for idx, r in sig.iterrows():
        rec = {
            "date": r["fecha"].date().isoformat(),
            "model_return": float(r["level_return"]),
            "actual_same_day_return": float(r["actual_return"]) if finite(r["actual_return"]) else None,
        }
        for h in (1, 3, 5):
            pos = df.index.get_loc(idx)
            if isinstance(pos, slice) or pos + h >= len(df):
                rec[f"forward_{h}d"] = None
                continue
            start = float(r["vc_sbs"]) if finite(r["vc_sbs"]) else None
            end = df.iloc[pos + h]["vc_sbs"]
            rec[f"forward_{h}d"] = float(end / start - 1.0) if finite(start) and finite(end) else None
        rows.append(rec)

    same = [x["actual_same_day_return"] for x in rows if finite(x["actual_same_day_return"])]
    out = {
        "threshold": SIGNAL_THRESHOLD,
        "n_signals": len(rows),
        "same_day_positive_rate": float(np.mean(np.asarray(same) > 0)) if same else None,
        "same_day_avg_return": float(np.mean(same)) if same else None,
        "signals": rows,
    }
    for h in (1, 3, 5):
        vals = [x[f"forward_{h}d"] for x in rows if finite(x[f"forward_{h}d"])]
        out[f"forward_{h}d_n"] = len(vals)
        out[f"forward_{h}d_positive_rate"] = float(np.mean(np.asarray(vals) > 0)) if vals else None
        out[f"forward_{h}d_avg_return"] = float(np.mean(vals)) if vals else None
    return out


def main():
    data = json.loads(SOURCE.read_text(encoding="utf-8"))
    df = pd.DataFrame(data["rows"])
    df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce")
    numeric = FACTORS + ["vc_sbs", "vc_niveles", "ret_vc_estimado", "vc_retornos"]
    for c in numeric:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["fecha"]).sort_values("fecha").reset_index(drop=True)

    levels = rolling_level(df, data["models"]["niveles"]["coefficients"])
    returns = rolling_returns(df, data["models"]["retornos"]["coefficients"])
    payload = {
        "generated_from": data.get("generated_at_lima"),
        "validation_start": VALIDATION_START.date().isoformat(),
        "policy": {
            "champion": "Coeficientes fijos calibrados 07/07/2026–17/08/2026.",
            "challenger": "Rolling-30 OLS recalibrado en sombra usando únicamente observaciones anteriores a cada predicción.",
            "minimum_watch_n": 10,
            "minimum_recalibrate_n": 15,
            "minimum_change_n": 30,
            "change_rules": [
                "Mejora MAE challenger >= 15%",
                "Mejora RMSE challenger >= 10%",
                "Challenger gana >= 60% de las fechas comparables",
                "Gana al menos 4 de las últimas 5 fechas",
                "Precisión direccional challenger no empeora más de 5 pp",
                "Con >=30 observaciones fuera de muestra, se marca CAMBIO RECOMENDADO; nunca se sustituye automáticamente.",
            ],
        },
        "models": {"niveles": levels, "retornos": returns},
        "signal_plus_1pct": signal_stats(df),
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "levels_status": levels["status"],
        "returns_status": returns["status"],
        "signal": payload["signal_plus_1pct"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
