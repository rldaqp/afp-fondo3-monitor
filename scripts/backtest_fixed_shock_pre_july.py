from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT / "public" / "data" / "fixed_models_2026.json"
MARKETS_PATH = ROOT / "data" / "rolling90" / "markets.csv"
SBS_PATH = ROOT / "data" / "rolling90" / "sbs_profuturo_f3.csv"
OUT_JSON = ROOT / "analysis" / "fixed_shock_pre_july_backtest.json"
OUT_CSV = ROOT / "analysis" / "fixed_shock_pre_july_daily.csv"

CUTOFF = pd.Timestamp("2026-07-07")
ROLL = 30

# Congelados exactamente desde la prueba 07/07-17/08; NO se reestiman con el pasado.
PARAMS = {
    "niveles": {"threshold": 1.0, "gamma": 0.0013583926885644075},
    "retornos": {"threshold": 1.5, "gamma": 0.0017154416565956182},
}


def read_csv(path: Path) -> pd.DataFrame:
    d = pd.read_csv(path)
    d["fecha"] = pd.to_datetime(d["fecha"], errors="coerce").dt.normalize()
    return d.dropna(subset=["fecha"]).sort_values("fecha").drop_duplicates("fecha", keep="last").reset_index(drop=True)


def safe_metrics(d: pd.DataFrame, pred_col: str) -> dict:
    q = d.dropna(subset=["vc_sbs", pred_col, "target_ret"]).copy()
    if q.empty:
        return {"n": 0}
    err = (q[pred_col].to_numpy(float) / q["vc_sbs"].to_numpy(float) - 1.0) * 100.0
    pred_ret_col = "base_ret" if pred_col == "base_vc" else "corrected_ret"
    pred_ret = q[pred_ret_col].to_numpy(float)
    actual_ret = q["target_ret"].to_numpy(float)
    hits = np.sign(pred_ret) == np.sign(actual_ret)
    return {
        "n": int(len(q)),
        "start": q["fecha"].iloc[0].date().isoformat(),
        "end": q["fecha"].iloc[-1].date().isoformat(),
        "mae_pct": float(np.mean(np.abs(err))),
        "rmse_pct": float(np.sqrt(np.mean(err ** 2))),
        "bias_pct": float(np.mean(err)),
        "direction_accuracy": float(np.mean(hits)),
    }


def improvement(base: dict, corr: dict) -> dict:
    def red(k: str):
        b, c = base.get(k), corr.get(k)
        if b in (None, 0) or c is None:
            return None
        return float((b - c) / b * 100.0)
    return {
        "mae_pct_reduction_pct": red("mae_pct"),
        "rmse_pct_reduction_pct": red("rmse_pct"),
    }


def prior_sbs_map(sbs: pd.DataFrame) -> dict[pd.Timestamp, tuple[pd.Timestamp, float]]:
    last_date = None
    last_vc = None
    out = {}
    for _, r in sbs.iterrows():
        d = pd.Timestamp(r["fecha"]).normalize()
        if last_date is not None:
            out[d] = (last_date, last_vc)
        last_date = d
        last_vc = float(r["valor_cuota"])
    return out


def refit_gamma_pre(d: pd.DataFrame, threshold: float) -> dict:
    q = d[(d["fecha"] < CUTOFF) & d["z_PE"].notna()].copy()
    q["x"] = np.where(q["z_PE"].abs() >= threshold, q["z_PE"], 0.0)
    active = q[q["x"] != 0].copy()
    if active.empty:
        return {"n_active": 0, "gamma": None, "gamma_pp_per_z": None}
    x = active["x"].to_numpy(float)
    y = (active["target_ret"] - active["base_ret"]).to_numpy(float)
    denom = float(x @ x)
    gamma = float((x @ y) / denom) if denom > 0 else None
    return {
        "n_active": int(len(active)),
        "gamma": gamma,
        "gamma_pp_per_z": None if gamma is None else gamma * 100.0,
    }


def main():
    payload = json.loads(MODEL_PATH.read_text(encoding="utf-8"))
    rows = pd.DataFrame(payload["rows"])
    rows["fecha"] = pd.to_datetime(rows["fecha"], errors="coerce").dt.normalize()
    numeric = ["vc_sbs", "vc_niveles", "vc_retornos", "ret_vc_estimado", "SPBLSCUP"]
    for c in numeric:
        rows[c] = pd.to_numeric(rows[c], errors="coerce")
    rows = rows.dropna(subset=["fecha"]).sort_values("fecha").drop_duplicates("fecha", keep="last").reset_index(drop=True)

    markets = read_csv(MARKETS_PATH)
    markets["ret_EPU"] = pd.to_numeric(markets["ret_EPU"], errors="coerce")

    # Retorno SPBLSCUP tal como está representado en la serie usada por el modelo fijo.
    sp = rows[["fecha", "SPBLSCUP"]].dropna().copy()
    sp["ret_SPBLSCUP"] = sp["SPBLSCUP"].pct_change(fill_method=None)

    factors = markets[["fecha", "ret_EPU"]].merge(sp[["fecha", "ret_SPBLSCUP"]], on="fecha", how="inner")
    factors["D_PE"] = factors["ret_EPU"] - factors["ret_SPBLSCUP"]
    factors["mu_PE_prev30"] = factors["D_PE"].rolling(ROLL, min_periods=ROLL).mean().shift(1)
    factors["sd_PE_prev30"] = factors["D_PE"].rolling(ROLL, min_periods=ROLL).std(ddof=1).shift(1)
    factors["z_PE"] = (factors["D_PE"] - factors["mu_PE_prev30"]) / factors["sd_PE_prev30"]

    sbs = read_csv(SBS_PATH)
    sbs["valor_cuota"] = pd.to_numeric(sbs["valor_cuota"], errors="coerce")
    sbs = sbs.dropna(subset=["valor_cuota"]).copy()
    prev_map = prior_sbs_map(sbs)

    frame = rows.merge(factors[["fecha", "ret_EPU", "ret_SPBLSCUP", "D_PE", "z_PE"]], on="fecha", how="left")
    prev_dates, prev_vcs = [], []
    for d in frame["fecha"]:
        p = prev_map.get(pd.Timestamp(d).normalize())
        prev_dates.append(None if p is None else p[0])
        prev_vcs.append(np.nan if p is None else p[1])
    frame["prev_sbs_date"] = prev_dates
    frame["prev_vc"] = prev_vcs
    frame["target_ret"] = frame["vc_sbs"] / frame["prev_vc"] - 1.0

    all_daily = []
    result_models = {}
    for model in ["niveles", "retornos"]:
        d = frame.copy()
        if model == "niveles":
            d["base_vc"] = d["vc_niveles"]
            d["base_ret"] = d["base_vc"] / d["prev_vc"] - 1.0
            d["published_historical_vc"] = d["vc_niveles"]
        else:
            # La prueba debe aislar SOLO el shock. Para ello reconstruimos el VC base
            # desde el mismo VC SBS t-1 que usa el VC corregido. El campo histórico
            # vc_retornos fue generado con reglas de anclaje antiguas y no es adecuado
            # para esta comparación retrospectiva.
            d["base_ret"] = d["ret_vc_estimado"]
            d["base_vc"] = d["prev_vc"] * (1.0 + d["base_ret"])
            d["published_historical_vc"] = d["vc_retornos"]

        threshold = PARAMS[model]["threshold"]
        gamma = PARAMS[model]["gamma"]
        d["shock_active"] = d["z_PE"].abs() >= threshold
        d["correction_ret"] = np.where(d["shock_active"], gamma * d["z_PE"], 0.0)
        d["corrected_ret"] = d["base_ret"] + d["correction_ret"]
        d["corrected_vc"] = d["prev_vc"] * (1.0 + d["corrected_ret"])
        d["model"] = model

        pre = d[(d["fecha"] < CUTOFF) & d["z_PE"].notna() & d["vc_sbs"].notna() & d["base_vc"].notna()].copy()
        active = pre[pre["shock_active"]].copy()
        inactive = pre[~pre["shock_active"]].copy()

        base_all = safe_metrics(pre, "base_vc")
        corr_all = safe_metrics(pre, "corrected_vc")
        base_active = safe_metrics(active, "base_vc")
        corr_active = safe_metrics(active, "corrected_vc")

        monthly = {}
        for period, g in pre.groupby(pre["fecha"].dt.to_period("M")):
            b = safe_metrics(g, "base_vc")
            c = safe_metrics(g, "corrected_vc")
            monthly[str(period)] = {
                "active_days": int(g["shock_active"].sum()),
                "base": b,
                "corrected": c,
                "improvement": improvement(b, c),
            }

        if not active.empty:
            eb = np.abs(active["base_vc"].to_numpy(float) / active["vc_sbs"].to_numpy(float) - 1.0)
            ec = np.abs(active["corrected_vc"].to_numpy(float) / active["vc_sbs"].to_numpy(float) - 1.0)
            win_days = int(np.sum(ec < eb))
            tie_days = int(np.sum(np.isclose(ec, eb, atol=1e-12)))
            loss_days = int(len(active) - win_days - tie_days)
        else:
            win_days = tie_days = loss_days = 0

        result_models[model] = {
            "frozen_parameters": {
                "threshold_abs_z": threshold,
                "gamma": gamma,
                "gamma_pp_per_z": gamma * 100.0,
                "source": "seleccionados con 07/07-17/08; no reestimados con datos pre-07/07",
            },
            "pre_july_period": {
                "start": None if pre.empty else pre["fecha"].iloc[0].date().isoformat(),
                "end": None if pre.empty else pre["fecha"].iloc[-1].date().isoformat(),
                "n": int(len(pre)),
                "active_days": int(len(active)),
                "inactive_days": int(len(inactive)),
            },
            "all_days": {
                "base": base_all,
                "corrected": corr_all,
                "improvement": improvement(base_all, corr_all),
            },
            "shock_days_only": {
                "base": base_active,
                "corrected": corr_active,
                "improvement": improvement(base_active, corr_active),
                "win_days": win_days,
                "loss_days": loss_days,
                "tie_days": tie_days,
                "win_rate_pct": None if len(active) == 0 else float(win_days / len(active) * 100.0),
            },
            "monthly": monthly,
            "refit_on_pre_july_for_sign_check_only": refit_gamma_pre(d, threshold),
        }

        cols = [
            "model", "fecha", "prev_sbs_date", "prev_vc", "vc_sbs", "target_ret",
            "base_ret", "base_vc", "published_historical_vc", "ret_EPU", "ret_SPBLSCUP", "D_PE", "z_PE",
            "shock_active", "correction_ret", "corrected_ret", "corrected_vc",
        ]
        all_daily.append(pre[cols])

    out = {
        "purpose": "Prueba retrospectiva de robustez antes del 07/07/2026 aplicando sin cambios los gamma y umbrales seleccionados posteriormente. No es OOS puro porque la ecuacion base fue calibrada con 07/07-17/08.",
        "base_model_version": payload.get("model_version"),
        "cutoff": "2026-07-07",
        "anchoring_rule": "Base y corregido se reconstruyen desde el mismo VC SBS inmediatamente anterior; si shock=0, ambos son identicos.",
        "zscore_definition": "z_PE=(R_EPU-R_SPBLSCUP - media previa 30)/desv.est previa 30; solo informacion anterior al dia evaluado",
        "models": result_models,
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    pd.concat(all_daily, ignore_index=True).to_csv(OUT_CSV, index=False)
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
