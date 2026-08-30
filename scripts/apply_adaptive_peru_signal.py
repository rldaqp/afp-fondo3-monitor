from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

import build_dual_rolling30_monitor as base

ROOT = Path(__file__).resolve().parents[1]
DUAL = ROOT / "public" / "data" / "dual_rolling30_monitor.json"
DATA = ROOT / "data" / "rolling90"
TRAIN = 30

CONTROL = ["ret_SPY", "ret_EEM", "ret_MCHI", "ret_USD_PEN", "ret_QQQ"]
EPU_FEATURES = CONTROL + ["ret_EPU"]
BVL_FEATURES = CONTROL + ["ret_SPBLSCUP"]


def _metrics(rows: list[dict]) -> dict:
    valid = [r for r in rows if base.finite(r.get("actual_vc")) and base.finite(r.get("vc_estimated"))]
    if not valid:
        return {"n": 0}
    y = np.array([float(r["actual_vc"]) for r in valid], dtype=float)
    p = np.array([float(r["vc_estimated"]) for r in valid], dtype=float)
    e = p - y
    corr = float(np.corrcoef(p, y)[0, 1]) if len(valid) > 1 else None
    sst = float(np.sum((y - y.mean()) ** 2))
    r2 = float(1.0 - np.sum(e ** 2) / sst) if sst > 0 else None
    return {
        "n": len(valid),
        "start": str(valid[0]["fecha"])[:10],
        "end": str(valid[-1]["fecha"])[:10],
        "pearson_r": corr,
        "corr2": None if corr is None else corr * corr,
        "predictive_r2": r2,
        "mae_vc": float(np.mean(np.abs(e))),
        "rmse_vc": float(np.sqrt(np.mean(e ** 2))),
        "mape_pct": float(np.mean(np.abs(e / y)) * 100.0),
        "bias_vc": float(np.mean(e)),
    }


def _spbl_series(nf: pd.DataFrame) -> pd.DataFrame:
    x = nf[["fecha", "ret_SPBLSCUP"]].copy()
    x["ret_SPBLSCUP"] = pd.to_numeric(x["ret_SPBLSCUP"], errors="coerce")
    x = x.dropna(subset=["ret_SPBLSCUP"]).sort_values("fecha").drop_duplicates("fecha", keep="last")

    # Cierres auditados tras el incidente del 24/08. Se fuerzan para impedir
    # que una captura histórica contaminada vuelva a entrar al selector.
    corrected = pd.DataFrame({
        "fecha": pd.to_datetime(["2026-08-21", "2026-08-24", "2026-08-25", "2026-08-26", "2026-08-27"]),
        "ret_SPBLSCUP": [
            460.43 / 446.70 - 1.0,
            459.23 / 460.43 - 1.0,
            0.010735361365764362,
            -0.004114960358497122,
            -0.0019686316928069214,
        ],
    })
    x = pd.concat([x, corrected], ignore_index=True)
    return x.sort_values("fecha").drop_duplicates("fecha", keep="last").reset_index(drop=True)


def _build_frames(signal_date: pd.Timestamp):
    sbs = base.sbs_frame()
    markets = base.read_csv(DATA / "markets.csv")
    qdaily = base.load_qqq_daily(markets["fecha"].min(), signal_date)
    qf = markets.merge(qdaily[["fecha", "ret_QQQ"]], on="fecha", how="left")
    qf = qf[["fecha", "ret_SPY", "ret_EEM", "ret_EPU", "ret_MCHI", "ret_USD_PEN", "ret_QQQ"]].copy()
    for c in EPU_FEATURES:
        qf[c] = pd.to_numeric(qf[c], errors="coerce")
    qf = qf.dropna(subset=EPU_FEATURES).sort_values("fecha").drop_duplicates("fecha", keep="last").reset_index(drop=True)

    nf = base.load_new_factors()
    spbl = _spbl_series(nf)
    bvl_f = qf[["fecha", *CONTROL]].merge(spbl, on="fecha", how="inner")
    bvl_f = bvl_f.dropna(subset=BVL_FEATURES).sort_values("fecha").drop_duplicates("fecha", keep="last").reset_index(drop=True)

    epu_common = base.build_common(sbs, qf, EPU_FEATURES)
    bvl_common = base.build_common(sbs, bvl_f, BVL_FEATURES)
    return sbs, qf, nf, spbl, epu_common, bvl_common


def _prediction_for_date(common: pd.DataFrame, features: list[str], date: pd.Timestamp):
    pos = common.index[common["fecha"].eq(date)]
    if len(pos) == 0:
        return None
    i = int(pos[-1])
    if i < TRAIN:
        return None
    train = common.iloc[i - TRAIN:i].copy()
    if len(train) != TRAIN:
        return None
    beta, coeff = base.fit(train, features)
    target = common.iloc[i]
    rr = base.predict(beta, target, features)
    return rr, coeff, train, target


def _adaptive_history(epu_common: pd.DataFrame, bvl_common: pd.DataFrame, limit: int = 140) -> list[dict]:
    bvl_by_date = {pd.Timestamp(r["fecha"]).normalize(): r for _, r in bvl_common.iterrows()}
    rows = []
    for i in range(TRAIN, len(epu_common)):
        target = epu_common.iloc[i]
        date = pd.Timestamp(target["fecha"]).normalize()
        train_e = epu_common.iloc[i - TRAIN:i].copy()
        beta_e, coeff_e = base.fit(train_e, EPU_FEATURES)
        ret_e = base.predict(beta_e, target, EPU_FEATURES)

        bpred = _prediction_for_date(bvl_common, BVL_FEATURES, date)
        ret_b = None
        coeff_b = None
        spbl_ret = None
        if date in bvl_by_date:
            spbl_ret = float(bvl_by_date[date]["ret_SPBLSCUP"])
        if bpred is not None:
            ret_b, coeff_b, _, _ = bpred

        epu_ret = float(target["ret_EPU"])
        divergence = bool(spbl_ret is not None and epu_ret != 0 and spbl_ret != 0 and np.sign(epu_ret) != np.sign(spbl_ret))
        use_bvl = bool(divergence and ret_b is not None)
        rr = float(ret_b if use_bvl else ret_e)
        used = "SPBLSCUP" if use_bvl else "EPU"

        base_vc = float(target["prev_vc"])
        actual = float(target["valor_cuota"])
        est = base_vc * (1.0 + rr)
        row = {
            "fecha": date.date().isoformat(),
            "base_date": pd.Timestamp(target["prev_date"]).date().isoformat(),
            "base_vc": base_vc,
            "vc_estimated": est,
            "actual_vc": actual,
            "return_estimated": rr,
            "actual_return": actual / base_vc - 1.0,
            "actual_return_daily": actual / base_vc - 1.0,
            "signal": base.classify(rr),
            "error_pct": (est / actual - 1.0) * 100.0,
            "train_start": pd.Timestamp(train_e.iloc[0]["fecha"]).date().isoformat(),
            "train_end": pd.Timestamp(train_e.iloc[-1]["fecha"]).date().isoformat(),
            "peru_signal_used": used,
            "peru_divergence": divergence,
            "ret_EPU": epu_ret,
            "ret_SPBLSCUP": spbl_ret,
            "return_estimated_epu": float(ret_e),
            "return_estimated_bvl": None if ret_b is None else float(ret_b),
            "vc_estimated_epu": base_vc * (1.0 + float(ret_e)),
            "vc_estimated_bvl": None if ret_b is None else base_vc * (1.0 + float(ret_b)),
            "adaptive_rule": "SPBLSCUP si EPU y SPBLSCUP tienen signos opuestos; EPU en otro caso",
        }
        rows.append(row)
    return rows[-limit:]


def _live_epu_row(live: dict, qqq_now: dict) -> dict[str, float]:
    by = {str(x.get("serie")): x for x in live.get("assets", [])}
    vals = {}
    for f, n in {"ret_SPY": "SPY", "ret_EEM": "EEM", "ret_EPU": "EPU", "ret_MCHI": "MCHI", "ret_USD_PEN": "USD_PEN"}.items():
        r = by.get(n, {})
        raw = r.get("retorno_modelo") if r.get("retorno_modelo") is not None else r.get("retorno")
        if not base.finite(raw):
            raise RuntimeError(f"Falta {n} para selector adaptativo")
        vals[f] = float(raw)
    vals["ret_QQQ"] = float(qqq_now["retorno"])
    return vals


def _adaptive_forward(
    model: dict,
    live: dict,
    signal_date: pd.Timestamp,
    sbs: pd.DataFrame,
    qf: pd.DataFrame,
    nf: pd.DataFrame,
    spbl: pd.DataFrame,
    epu_common: pd.DataFrame,
    bvl_common: pd.DataFrame,
):
    latest = sbs.iloc[-1]
    anchor_date = pd.Timestamp(latest["fecha"]).normalize()
    anchor_vc = float(latest["valor_cuota"])

    train_e = epu_common.loc[epu_common["fecha"] <= anchor_date].tail(TRAIN).copy()
    train_b = bvl_common.loc[bvl_common["fecha"] <= anchor_date].tail(TRAIN).copy()
    if len(train_e) != TRAIN:
        raise RuntimeError("Train EPU incompleto para selector adaptativo")
    beta_e, coeff_e = base.fit(train_e, EPU_FEATURES)
    beta_b = coeff_b = None
    if len(train_b) == TRAIN:
        beta_b, coeff_b = base.fit(train_b, BVL_FEATURES)

    qdaily = base.load_qqq_daily(qf["fecha"].min(), signal_date)
    qqq_now = base.qqq_snapshot(signal_date, qdaily, bool(live.get("market_open")))
    e_live = _live_epu_row(live, qqq_now)
    qf_live = base.extend_with_live(qf, signal_date, e_live, EPU_FEATURES)

    n_live, n_assets = base.new_intraday_values(live, signal_date, nf)
    sp_live = pd.concat([
        spbl,
        pd.DataFrame([{"fecha": signal_date, "ret_SPBLSCUP": float(n_live["ret_SPBLSCUP"])}]),
    ], ignore_index=True).sort_values("fecha").drop_duplicates("fecha", keep="last")
    sp_map = {pd.Timestamp(r["fecha"]).normalize(): float(r["ret_SPBLSCUP"]) for _, r in sp_live.iterrows() if base.finite(r.get("ret_SPBLSCUP"))}

    hidden = qf_live.loc[(qf_live["fecha"] > anchor_date) & (qf_live["fecha"] <= signal_date)].sort_values("fecha").drop_duplicates("fecha", keep="last")
    hidden_map = {pd.Timestamp(r["fecha"]).normalize(): r for _, r in hidden.iterrows()}
    old_forward = {pd.Timestamp(str(r.get("fecha"))).normalize(): r for r in model.get("forward_chain", []) if r.get("fecha")}
    dates = sorted(set(hidden_map) | {d for d in old_forward if anchor_date < d <= signal_date})

    vc = anchor_vc
    rows = []
    selected_coeff = coeff_e
    selected_used = "EPU"
    for date in dates:
        if date not in hidden_map:
            old = dict(old_forward[date])
            base_vc = vc
            old_vc = float(old["vc_estimated"])
            rr = old_vc / base_vc - 1.0
            vc = old_vc
            old.update({
                "base_vc": base_vc,
                "return_estimated": rr,
                "peru_signal_used": "FALLBACK_OPERACIONAL",
                "peru_divergence": None,
                "adaptive_rule": "fallback por falta de factores de la sesión",
            })
            rows.append(old)
            continue

        r = hidden_map[date]
        ret_e = base.predict(beta_e, r, EPU_FEATURES)
        epu_ret = float(r["ret_EPU"])
        sp_ret = sp_map.get(date)
        ret_b = None
        if beta_b is not None and sp_ret is not None:
            b_row = {f: float(r[f]) for f in CONTROL}
            b_row["ret_SPBLSCUP"] = float(sp_ret)
            ret_b = base.predict(beta_b, b_row, BVL_FEATURES)
        divergence = bool(sp_ret is not None and epu_ret != 0 and sp_ret != 0 and np.sign(epu_ret) != np.sign(sp_ret))
        use_bvl = bool(divergence and ret_b is not None)
        rr = float(ret_b if use_bvl else ret_e)
        used = "SPBLSCUP" if use_bvl else "EPU"
        base_vc = vc
        vc = base_vc * (1.0 + rr)
        rows.append({
            "fecha": date.date().isoformat(),
            "base_vc": base_vc,
            "vc_estimated": vc,
            "return_estimated": rr,
            "signal": base.classify(rr),
            "actual_vc": None,
            "chain_source": "MODELO A ADAPTATIVO EPU/BVL",
            "peru_signal_used": used,
            "peru_divergence": divergence,
            "ret_EPU": epu_ret,
            "ret_SPBLSCUP": sp_ret,
            "return_estimated_epu": float(ret_e),
            "return_estimated_bvl": None if ret_b is None else float(ret_b),
            "vc_estimated_epu": base_vc * (1.0 + float(ret_e)),
            "vc_estimated_bvl": None if ret_b is None else base_vc * (1.0 + float(ret_b)),
            "adaptive_rule": "SPBLSCUP si EPU y SPBLSCUP tienen signos opuestos; EPU en otro caso",
        })
        selected_coeff = coeff_b if use_bvl and coeff_b is not None else coeff_e
        selected_used = used

    if not rows:
        hist = model.get("history_one_step", [])
        if hist:
            rows = [{**hist[-1], "chain_source": "HISTÓRICO ADAPTATIVO ONE-STEP"}]
        else:
            rows = [{"fecha": signal_date.date().isoformat(), "base_vc": anchor_vc, "vc_estimated": anchor_vc, "return_estimated": 0.0, "signal": "NEUTRO", "actual_vc": anchor_vc, "chain_source": "ANCLA SBS"}]

    meta = {
        "anchor_date": anchor_date.date().isoformat(),
        "anchor_vc": anchor_vc,
        "train_start": pd.Timestamp(train_e.iloc[0]["fecha"]).date().isoformat(),
        "train_end": pd.Timestamp(train_e.iloc[-1]["fecha"]).date().isoformat(),
        "train_n": len(train_e),
        "coefficients": selected_coeff,
        "coefficients_epu": coeff_e,
        "coefficients_bvl": coeff_b,
        "peru_signal_used": selected_used,
        "blind_chain_sessions": len(rows),
        "adaptive_selector": True,
    }
    return rows, meta, qqq_now, n_assets


def _adaptive_operational(old_rows: list[dict], history: list[dict]) -> list[dict]:
    h = {str(r["fecha"])[:10]: r for r in history}
    out = []
    for old in old_rows:
        d = str(old.get("fecha", ""))[:10]
        if d in h:
            row = dict(h[d])
            row.update({
                "source": "RECONSTRUCCIÓN ADAPTATIVA EPU/BVL · ONE-STEP SIN LOOKAHEAD",
                "quality_status": "RECONSTRUIDO_ADAPTATIVO_EPU_BVL",
                "quality_note": "Fila reconstruida con regla conocida al cierre: si EPU y SPBLSCUP discrepan de signo se usa el modelo BVL; en otro caso se usa EPU.",
                "include_in_score": True,
            })
            out.append(row)
        else:
            out.append(old)
    return sorted(out, key=lambda r: str(r.get("fecha", ""))[:10])


def main() -> None:
    if not DUAL.exists():
        raise RuntimeError("No existe dual_rolling30_monitor.json")
    d = json.loads(DUAL.read_text(encoding="utf-8"))
    signal_date = pd.Timestamp(str(d["signal_date"])).normalize()
    live = json.loads(base.LIVE.read_text(encoding="utf-8"))

    sbs, qf, nf, spbl, epu_common, bvl_common = _build_frames(signal_date)
    hist = _adaptive_history(epu_common, bvl_common)
    if not hist:
        raise RuntimeError("No se pudo reconstruir histórico adaptativo")

    model = d["models"]["qqq"]
    old_operational = list(model.get("history_operational", []))
    model["history_one_step"] = hist
    model["history_operational"] = _adaptive_operational(old_operational, hist)

    forward, meta, qqq_now, n_assets = _adaptive_forward(model, live, signal_date, sbs, qf, nf, spbl, epu_common, bvl_common)
    model["forward_chain"] = forward
    model["current"] = {**forward[-1], **meta}
    model["name"] = "Rolling 30 · QQQ · Perú adaptativo EPU/BVL"
    model["short"] = "QQQ + Perú adaptativo"
    model["features_display"] = ["SPY", "EEM", "MCHI", "USD/PEN", "QQQ", "EPU/SPBLSCUP"]
    model["features"] = [*CONTROL, "ret_PERU_ADAPTATIVO"]
    model["history_metrics"] = _metrics(hist)
    model["adaptive_validation"] = {
        "rule": "Usar SPBLSCUP solo cuando EPU y SPBLSCUP tienen signos opuestos; EPU en el resto. Ambos modelos controlan SPY, EEM, MCHI, USD/PEN y QQQ.",
        "no_lookahead": True,
        "last30": _metrics(hist[-30:]),
        "last60": _metrics(hist[-60:]),
        "last90": _metrics(hist[-90:]),
        "spbl_history_start": None if bvl_common.empty else pd.Timestamp(bvl_common.iloc[0]["fecha"]).date().isoformat(),
        "selector_version": "EPU_SPBLSCUP_SIGN_DIVERGENCE_V1",
    }

    # Ticker bar: siempre seis factores. La señal Perú visible es exactamente la
    # elegida para la sesión actual.
    q_assets = base.qqq_intraday_assets(live, qqq_now)
    current_used = str(model["current"].get("peru_signal_used") or "EPU")
    if current_used == "SPBLSCUP":
        sp_asset = next((dict(x) for x in n_assets if str(x.get("serie")) == "SPBLSCUP"), None)
        q_assets = [x for x in q_assets if str(x.get("serie")) != "EPU"]
        if sp_asset is not None:
            sp_asset["usado_modelo"] = True
            q_assets.insert(2, sp_asset)
    model["intraday_assets"] = q_assets
    model["source_note"] = "SPY/EEM/MCHI/QQQ: Yahoo Finance; Perú adaptativo: EPU normalmente y SPBLSCUP cuando ambos discrepan de signo; USD/PEN normalizado con BCRP PD04638PD en la reconstrucción."

    d["rule"] = (
        "Modelo A: OLS Rolling 30 con controles SPY, EEM, MCHI, USD/PEN y QQQ. "
        "La señal Perú es adaptativa: usa EPU normalmente y cambia a SPBLSCUP únicamente cuando EPU y SPBLSCUP tienen signos opuestos en la sesión. "
        "La reconstrucción histórica aplica la misma regla sin mirar el VC futuro. Modelo B se mantiene sin cambios."
    )
    d["adaptive_peru"] = {
        "enabled": True,
        "model": "qqq",
        "version": "EPU_SPBLSCUP_SIGN_DIVERGENCE_V1",
        "decision_known_at_close": True,
        "fallback": "EPU si SPBLSCUP no está disponible o no hay divergencia de signo",
        "reconstructed_history_rows": len(hist),
        "current_signal": model["current"].get("peru_signal_used"),
        "current_divergence": model["current"].get("peru_divergence"),
    }

    # La comparación blind3 preexistente pertenece al modelo QQQ anterior y se
    # conserva solo como auditoría; no se presenta como validación del selector.
    if isinstance(d.get("blind3"), dict):
        d["blind3"]["adaptive_model_note"] = "Blind3 histórico corresponde al QQQ previo; el selector adaptativo se valida en adaptive_validation y en analysis/epu_spbl_disagreement_analysis.json."

    DUAL.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    row24 = next((r for r in hist if str(r.get("fecha"))[:10] == "2026-08-24"), None)
    print(json.dumps({
        "signal_date": str(d["signal_date"]),
        "adaptive_current": model["current"],
        "last30": model["adaptive_validation"]["last30"],
        "row_2026_08_24": row24,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
