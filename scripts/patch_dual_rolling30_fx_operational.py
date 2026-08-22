from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public" / "data"
DUAL = PUBLIC / "dual_rolling30_monitor.json"
LIVE = PUBLIC / "live_market.json"
ALT = PUBLIC / "alt_6030_experimental.json"


def finite(v) -> bool:
    try:
        return v is not None and float("-inf") < float(v) < float("inf")
    except Exception:
        return False


def classify(v: float) -> str:
    return "SUBE" if v > 0.001 else ("BAJA" if v < -0.001 else "NEUTRO")


def pick_return(row: dict):
    v = row.get("retorno_modelo")
    if v is None:
        v = row.get("retorno")
    return float(v) if finite(v) else None


def find_shared_fx(live: dict) -> dict:
    # Regla común para ambos Rolling 30: usar exactamente el mismo USD/PEN
    # operativo que ya emplea el Modelo A en live_market. Históricamente ambos
    # modelos siguen entrenando con la serie diaria guardada/BCRP correspondiente.
    for row in live.get("assets", []):
        if str(row.get("serie")) == "USD_PEN":
            return dict(row)
    for row in live.get("experimental_assets", []):
        if str(row.get("serie")) in {"USD/PEN", "USD_PEN"}:
            return dict(row)
    raise RuntimeError("No existe USD/PEN operativo común en live_market.json")


def main() -> None:
    if not DUAL.exists() or not LIVE.exists():
        raise RuntimeError("Faltan dual_rolling30_monitor.json o live_market.json")

    dual = json.loads(DUAL.read_text(encoding="utf-8"))
    live = json.loads(LIVE.read_text(encoding="utf-8"))
    alt = json.loads(ALT.read_text(encoding="utf-8")) if ALT.exists() else {}

    shared = find_shared_fx(live)
    fx_ret = pick_return(shared)
    if fx_ret is None:
        raise RuntimeError("USD/PEN operativo común no tiene retorno utilizable")

    model_a = dual.get("models", {}).get("qqq", {})
    model_b = dual.get("models", {}).get("new_tickers", {})
    cur = model_b.get("current", {})
    coeff = cur.get("coefficients") or {}
    signal_date = str(dual.get("signal_date") or "")[:10]
    if not signal_date or not coeff:
        raise RuntimeError("Modelo B no tiene fecha/coeficientes")

    # Confirmar que el Modelo A ya está usando la misma cotización/retorno.
    a_fx = next((a for a in model_a.get("intraday_assets", []) if str(a.get("serie")) == "USD_PEN"), None)
    if a_fx is None:
        raise RuntimeError("Modelo A no contiene USD_PEN")
    a_ret = pick_return(a_fx)
    if a_ret is None or abs(a_ret - fx_ret) > 1e-12:
        raise RuntimeError(f"USD/PEN común no coincide con Modelo A: {a_ret} vs {fx_ret}")

    assets = model_b.get("intraday_assets") or []
    by = {str(a.get("serie")): a for a in assets}
    fx_asset = by.get("USD/PEN")
    if fx_asset is None:
        fx_asset = {"serie": "USD/PEN", "ticker": "USD/PEN"}
        assets.append(fx_asset)

    fx_asset.update({
        "ticker": shared.get("ticker") or "PEN=X",
        "timestamp": shared.get("timestamp") or signal_date,
        "precio_anterior": shared.get("precio_anterior"),
        "precio_actual": shared.get("precio_actual"),
        "retorno": fx_ret,
        "retorno_modelo": fx_ret,
        "estado": "MISMA FUENTE QUE MODELO A · " + str(shared.get("estado") or live.get("fx_source") or "USD/PEN OPERATIVO"),
        "usado_modelo": True,
    })

    feature_to_asset = {
        "ret_.INX": ".INX",
        "ret_CPER": "CPER",
        "ret_EEM_alt": "EEM",
        "ret_NDX": "NDX",
        "ret_SPBLSCUP": "SPBLSCUP",
        "ret_USD_PEN_alt": "USD/PEN",
    }
    by = {str(a.get("serie")): a for a in assets}
    rr = float(coeff.get("intercept", 0.0))
    for feature, name in feature_to_asset.items():
        a = by.get(name)
        if a is None:
            raise RuntimeError(f"Falta activo {name} para recalcular Modelo B")
        r = pick_return(a)
        if r is None or not finite(coeff.get(feature)):
            raise RuntimeError(f"Falta retorno/coeficiente {feature}")
        rr += float(coeff[feature]) * r

    chain = model_b.get("forward_chain") or []
    target = next((r for r in reversed(chain) if str(r.get("fecha"))[:10] == signal_date), None)
    if target is None:
        raise RuntimeError(f"No existe fila forward para {signal_date}")
    base = target.get("base_vc")
    if not finite(base):
        raise RuntimeError("Falta base_vc del día actual")

    est = float(base) * (1.0 + rr)
    sig = classify(rr)
    target.update({"return_estimated": rr, "vc_estimated": est, "signal": sig})
    cur.update({"return_estimated": rr, "vc_estimated": est, "signal": sig})
    model_b["intraday_assets"] = assets
    model_b["source_note"] = (
        "Modelo B: rolling 30 con .INX, CPER, EEM, NDX, SPBLSCUP y USD/PEN. "
        "Para la comparación operativa, USD/PEN usa exactamente la misma fuente del Modelo A. "
        "Si BCRP está rezagado, ambos usan la misma fuente provisional del monitor; el histórico conserva su serie diaria de entrenamiento."
    )

    # Metadato honesto de la fuente realmente usada por los dos Rolling 30.
    dual["shared_fx_operational"] = {
        "return": fx_ret,
        "value": float(shared["precio_actual"]) if finite(shared.get("precio_actual")) else None,
        "previous_value": float(shared["precio_anterior"]) if finite(shared.get("precio_anterior")) else None,
        "source": shared.get("estado") or live.get("fx_source"),
        "timestamp": shared.get("timestamp"),
        "provisional": bool(live.get("fx_provisional")),
        "rule": "Mismo USD/PEN operativo para ambos Rolling 30; no se mezclan Yahoo y Tucambista dentro de la comparación dual.",
    }

    # Campo legado conservado solo para no romper el workflow histórico 60/30.
    # Los valores usados por el Modelo B están documentados arriba en shared_fx_operational.
    legacy_fx = alt.get("fx_operational") or {}
    dual["fx_operational_new_tickers"] = {
        "return": fx_ret,
        "value": float(shared["precio_actual"]) if finite(shared.get("precio_actual")) else None,
        "source": legacy_fx.get("source"),
        "source_used_model": shared.get("estado") or live.get("fx_source"),
        "legacy_validation_source_only": True,
        "provisional": bool(live.get("fx_provisional")),
    }

    DUAL.write_text(json.dumps(dual, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "signal_date": signal_date,
        "shared_fx": dual["shared_fx_operational"],
        "return_estimated_b": rr,
        "vc_estimated_b": est,
        "signal_b": sig,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
