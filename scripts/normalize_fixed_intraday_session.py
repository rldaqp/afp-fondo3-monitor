from __future__ import annotations

import json
from datetime import datetime, time as clock_time
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "public" / "data" / "fixed_models_2026.json"
SNAP = ROOT / "public" / "data" / "fixed_models_intraday.json"
NY = ZoneInfo("America/New_York")
LIMA = ZoneInfo("America/Lima")
FACTORS = ["SPY", "EEM", "MCHI", "QQQ", "SPBLSCUP"]


def finite(v) -> bool:
    try:
        return v is not None and np.isfinite(float(v))
    except Exception:
        return False


def main() -> None:
    if not BASE.exists() or not SNAP.exists():
        return

    base = json.loads(BASE.read_text(encoding="utf-8"))
    snap = json.loads(SNAP.read_text(encoding="utf-8"))
    rows = base.get("rows") or []
    complete = [r for r in rows if all(finite(r.get(f)) for f in FACTORS)]
    if not complete:
        return

    last = complete[-1]
    last_date = str(last.get("fecha") or "")[:10]
    snap_date = str(snap.get("signal_date") or "")[:10]
    now_ny = datetime.now(NY)

    # Después de medianoche NY, fast_info puede seguir devolviendo el cierre de
    # la rueda anterior pero el builder antiguo lo etiquetaba con la fecha nueva.
    # Antes de 09:30 NY (o durante fin de semana) no existe una nueva rueda regular.
    # Si el snapshot pretende ir un día por delante de la última fila fija validada,
    # se normaliza al último cierre real en vez de publicar una sesión fantasma.
    pre_open_or_weekend = now_ny.weekday() >= 5 or now_ny.time() < clock_time(9, 30)
    if not (pre_open_or_weekend and snap_date > last_date):
        return

    previous = None
    for r in reversed(complete[:-1]):
        if str(r.get("fecha") or "")[:10] < last_date:
            previous = r
            break
    if previous is None:
        return

    lc = base["models"]["niveles"]["coefficients"]
    rc = base["models"]["retornos"]["coefficients"]

    level_contrib = {}
    return_contrib = {}
    ret_est = float(rc["intercept"])
    vc_levels = float(lc["intercept"])
    factor_returns = {}
    for f in FACTORS:
        cur = float(last[f])
        prev = float(previous[f])
        ret = cur / prev - 1.0
        factor_returns[f] = ret
        level_contrib[f] = float(lc[f]) * cur
        return_contrib[f] = float(rc[f]) * ret
        vc_levels += level_contrib[f]
        ret_est += return_contrib[f]

    # Usa exactamente la misma política de anclaje que la serie fija.
    if finite(previous.get("vc_sbs")):
        ret_base = float(previous["vc_sbs"])
        ret_base_kind = "VC SBS real de la sesión anterior"
    elif finite(previous.get("vc_retornos")):
        ret_base = float(previous["vc_retornos"])
        ret_base_kind = "VC estimado por retornos de la sesión anterior"
    else:
        ret_base = float(base["latest"]["latest_sbs_vc"])
        ret_base_kind = "Último VC SBS disponible"

    vc_returns = (
        float(last["vc_retornos"])
        if finite(last.get("vc_retornos"))
        else ret_base * (1.0 + ret_est)
    )
    if finite(last.get("vc_niveles")):
        vc_levels = float(last["vc_niveles"])
    if finite(last.get("ret_vc_estimado")):
        ret_est = float(last["ret_vc_estimado"])

    den_l = sum(abs(v) for v in level_contrib.values())
    den_r = sum(abs(v) for v in return_contrib.values())
    prev_date = str(previous.get("fecha") or "")[:10]
    tickers = []
    for f in FACTORS:
        tickers.append({
            "ticker": f,
            "timestamp": last_date,
            "fresh": True,
            "price_previous": float(previous[f]),
            "price_current": float(last[f]),
            "return": factor_returns[f],
            "previous_close_date": prev_date,
            "previous_close_basis": "CIERRE BASE FIJA",
            "provider_previous_close": None,
            "level_coefficient": float(lc[f]),
            "return_coefficient": float(rc[f]),
            "level_contribution": level_contrib[f],
            "return_contribution": return_contrib[f],
            "level_weight_abs_pct": abs(level_contrib[f]) / den_l * 100.0 if den_l else 0.0,
            "return_weight_abs_pct": abs(return_contrib[f]) / den_r * 100.0 if den_r else 0.0,
            "source": "CIERRE FIJO VALIDADO · SIN NUEVA SESIÓN PREAPERTURA",
        })

    normalized = {
        "generated_at_lima": datetime.now(LIMA).isoformat(),
        "generated_at_ny": now_ny.isoformat(),
        "signal_date": last_date,
        "mode": "CIERRE / ÚLTIMO SNAPSHOT",
        "market_open": False,
        "fresh_factors": len(FACTORS),
        "total_factors": len(FACTORS),
        "problems": [],
        "previous_close_rule": "Cierre regular validado más reciente de la base fija, anterior a la sesión objetivo; proveedor solo como fallback.",
        "models": {
            "niveles": {
                "vc_intraday": vc_levels,
                "equation": base["models"]["niveles"]["equation"],
            },
            "retornos": {
                "return_intraday": ret_est,
                "vc_intraday": vc_returns,
                "base_vc": ret_base,
                "base_rule": ret_base_kind + " · cierre fijo normalizado",
                "equation": base["models"]["retornos"]["equation"],
            },
        },
        "tickers": tickers,
        "weight_note": "Peso relativo = participación del valor absoluto del aporte actual de cada factor; no representa tenencia de cartera.",
        "source_live": "Preapertura/fin de semana: se conserva el último cierre regular validado; no se crea una sesión nueva con cotizaciones rezagadas.",
    }
    SNAP.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Snapshot normalizado a último cierre real:", last_date)


if __name__ == "__main__":
    main()
