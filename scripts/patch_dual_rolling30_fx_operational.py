from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public" / "data"
DUAL = PUBLIC / "dual_rolling30_monitor.json"
ALT = PUBLIC / "alt_6030_experimental.json"


def finite(v) -> bool:
    try:
        return v is not None and float("-inf") < float(v) < float("inf")
    except Exception:
        return False


def classify(v: float) -> str:
    return "SUBE" if v > 0.001 else ("BAJA" if v < -0.001 else "NEUTRO")


def main() -> None:
    if not DUAL.exists() or not ALT.exists():
        raise RuntimeError("Faltan dual_rolling30_monitor.json o alt_6030_experimental.json")
    dual = json.loads(DUAL.read_text(encoding="utf-8"))
    alt = json.loads(ALT.read_text(encoding="utf-8"))
    fx = alt.get("fx_operational") or {}
    fx_ret = fx.get("return")
    if not finite(fx_ret):
        print("FX operativo alternativo no disponible; se conserva el valor del builder dual.")
        return

    model = dual.get("models", {}).get("new_tickers", {})
    cur = model.get("current", {})
    coeff = cur.get("coefficients") or {}
    signal_date = str(dual.get("signal_date") or "")[:10]
    if not signal_date or not coeff:
        raise RuntimeError("Modelo nuevos tickers no tiene fecha/coeficientes")

    assets = model.get("intraday_assets") or []
    by = {str(a.get("serie")): a for a in assets}
    fx_asset = by.get("USD/PEN")
    if fx_asset is None:
        fx_asset = {"serie": "USD/PEN", "ticker": "USD/PEN"}
        assets.append(fx_asset)
    fx_asset.update({
        "retorno": float(fx_ret),
        "retorno_modelo": float(fx_ret),
        "estado": str(fx.get("source") or "FX OPERATIVO PROVISIONAL"),
        "usado_modelo": True,
        "timestamp": signal_date,
    })
    if finite(fx.get("value")):
        fx_asset["precio_actual"] = float(fx["value"])

    feature_to_asset = {
        "ret_.INX": ".INX",
        "ret_CPER": "CPER",
        "ret_EEM_alt": "EEM",
        "ret_NDX": "NDX",
        "ret_SPBLSCUP": "SPBLSCUP",
        "ret_USD_PEN_alt": "USD/PEN",
    }
    rr = float(coeff.get("intercept", 0.0))
    for feature, name in feature_to_asset.items():
        a = by.get(name) if name != "USD/PEN" else fx_asset
        if a is None:
            raise RuntimeError(f"Falta activo {name} para recalcular FX operativo")
        r = a.get("retorno_modelo") if a.get("retorno_modelo") is not None else a.get("retorno")
        if not finite(r) or not finite(coeff.get(feature)):
            raise RuntimeError(f"Falta retorno/coeficiente {feature}")
        rr += float(coeff[feature]) * float(r)

    chain = model.get("forward_chain") or []
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
    model["intraday_assets"] = assets
    model["source_note"] = (
        "Modelo B: rolling 30 con .INX, CPER, EEM, NDX, SPBLSCUP y USD/PEN. "
        "Para el día operativo, USD/PEN usa la misma regla FX del modelo alternativo: BCRP si está disponible; "
        "si no, fuente provisional explícita. La predicción se congela al cierre y no se modifica al aparecer SBS."
    )
    dual.setdefault("fx_operational_new_tickers", {}).update({
        "return": float(fx_ret),
        "value": float(fx["value"]) if finite(fx.get("value")) else None,
        "source": fx.get("source"),
        "provisional": bool(fx.get("provisional")),
    })
    DUAL.write_text(json.dumps(dual, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"signal_date": signal_date, "fx": dual["fx_operational_new_tickers"], "return_estimated": rr, "vc_estimated": est, "signal": sig}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
