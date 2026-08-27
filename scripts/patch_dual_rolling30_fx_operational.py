from __future__ import annotations

import json
import re
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public" / "data"
DUAL = PUBLIC / "dual_rolling30_monitor.json"
LIVE = PUBLIC / "live_market.json"

BCRP_URL = "https://estadisticas.bcrp.gob.pe/estadisticas/series/api/PD04638PD/json"
TUCAMBISTA_URL = "https://tucambista.pe/"
MESES = {
    "ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
    "jul": 7, "ago": 8, "set": 9, "sep": 9, "oct": 10, "nov": 11, "dic": 12,
}


def finite(v) -> bool:
    try:
        x = float(v)
        return float("-inf") < x < float("inf")
    except Exception:
        return False


def classify(v: float) -> str:
    return "SUBE" if v > 0.001 else ("BAJA" if v < -0.001 else "NEUTRO")


def pick_return(row: dict):
    v = row.get("retorno_modelo")
    if v is None:
        v = row.get("retorno")
    return float(v) if finite(v) else None


def parse_bcrp_date(text: str) -> str | None:
    s = str(text).lower().strip()
    m = re.search(r"(\d{1,2})[.\-/ ]+([a-záéíóú]+)[.\-/ ]+(\d{2,4})", s)
    if not m:
        return None
    mon = m.group(2)[:3]
    for a, b in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u")):
        mon = mon.replace(a, b)
    month = MESES.get(mon)
    if not month:
        return None
    year = int(m.group(3))
    if year < 100:
        year += 2000
    return f"{year:04d}-{month:02d}-{int(m.group(1)):02d}"


def load_bcrp() -> list[tuple[str, float]]:
    r = requests.get(BCRP_URL, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    rows: list[tuple[str, float]] = []
    for p in r.json().get("periods", []):
        d = parse_bcrp_date(p.get("name"))
        raw = (p.get("values") or [None])[0]
        if not d or raw in (None, "", "n.d."):
            continue
        try:
            rows.append((d, float(raw)))
        except Exception:
            continue
    rows.sort(key=lambda x: x[0])
    if not rows:
        raise RuntimeError("BCRP PD04638PD no devolvió datos utilizables")
    return rows


def tucambista_midpoint() -> tuple[float, str]:
    r = requests.get(TUCAMBISTA_URL, timeout=25, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    clean = re.sub(r"<[^>]+>", " ", r.text)
    clean = re.sub(r"\s+", " ", clean)

    patterns = [
        (r"Compra\s*:?[\s]*(\d+\.\d+)", r"Venta\s*:?[\s]*(\d+\.\d+)"),
        (r"Compra[^0-9]{0,80}(\d+\.\d+)", r"Venta[^0-9]{0,80}(\d+\.\d+)"),
    ]
    for pb, ps in patterns:
        buy = re.search(pb, clean, flags=re.IGNORECASE)
        sell = re.search(ps, clean, flags=re.IGNORECASE)
        if buy and sell:
            compra, venta = float(buy.group(1)), float(sell.group(1))
            if 2.0 < compra < 6.0 and 2.0 < venta < 6.0:
                return (compra + venta) / 2.0, f"TUCAMBISTA MIDPOINT ({compra:.3f}/{venta:.3f})"
    raise RuntimeError("TuCambista no devolvió compra/venta reconocibles")


def operational_fx(signal_date: str) -> dict:
    """Regla única: BCRP PD04638PD si ya publicó la fecha; si no, TuCambista provisional."""
    bcrp = load_bcrp()
    prior = [(d, v) for d, v in bcrp if d < signal_date]
    if not prior:
        raise RuntimeError(f"No existe BCRP previo a {signal_date}")
    prev_date, prev_value = prior[-1]
    same = [(d, v) for d, v in bcrp if d == signal_date]

    if same:
        current = float(same[-1][1])
        return {
            "value": current,
            "previous_value": float(prev_value),
            "previous_date": prev_date,
            "return": current / float(prev_value) - 1.0,
            "source": "BCRP PD04638PD · TC INTERBANCARIO VENTA · OFICIAL",
            "provisional": False,
        }

    current, label = tucambista_midpoint()
    return {
        "value": float(current),
        "previous_value": float(prev_value),
        "previous_date": prev_date,
        "return": float(current) / float(prev_value) - 1.0,
        "source": label + " · PROVISIONAL",
        "provisional": True,
    }


def replace_fx_asset(model: dict, asset_name: str, fx: dict) -> dict:
    assets = model.get("intraday_assets") or []
    row = next((a for a in assets if str(a.get("serie")) == asset_name), None)
    if row is None:
        row = {"serie": asset_name, "ticker": "USD/PEN"}
        assets.append(row)
    row.update({
        "ticker": "BCRP PD04638PD" if not fx["provisional"] else "TUCAMBISTA",
        "timestamp": model.get("current", {}).get("fecha"),
        "precio_anterior": fx["previous_value"],
        "precio_actual": fx["value"],
        "retorno": fx["return"],
        "retorno_modelo": fx["return"],
        "estado": fx["source"],
        "usado_modelo": True,
    })
    model["intraday_assets"] = assets
    return row


def recalc_model(model: dict, fx: dict, is_new: bool) -> tuple[float, float]:
    cur = model.get("current", {})
    coeff = cur.get("coefficients") or {}
    signal_date = str(cur.get("fecha") or "")[:10]
    if not signal_date or not coeff:
        raise RuntimeError(f"Modelo sin fecha/coeficientes: {model.get('name')}")

    fx_name = "USD/PEN" if is_new else "USD_PEN"
    replace_fx_asset(model, fx_name, fx)
    by = {str(a.get("serie")): a for a in model.get("intraday_assets", [])}
    mapping = (
        {
            "ret_.INX": ".INX",
            "ret_CPER": "CPER",
            "ret_EEM_alt": "EEM",
            "ret_NDX": "NDX",
            "ret_SPBLSCUP": "SPBLSCUP",
            "ret_USD_PEN_alt": "USD/PEN",
        }
        if is_new
        else {
            "ret_SPY": "SPY",
            "ret_EEM": "EEM",
            "ret_EPU": "EPU",
            "ret_MCHI": "MCHI",
            "ret_USD_PEN": "USD_PEN",
            "ret_QQQ": "QQQ",
        }
    )

    rr = float(coeff.get("intercept", 0.0))
    for feature, asset_name in mapping.items():
        row = by.get(asset_name)
        r = pick_return(row or {})
        if r is None or not finite(coeff.get(feature)):
            raise RuntimeError(f"Falta {feature}/{asset_name} para {model.get('name')}")
        rr += float(coeff[feature]) * r

    chain = model.get("forward_chain") or []
    target = next((r for r in reversed(chain) if str(r.get("fecha"))[:10] == signal_date), None)
    if target is None:
        raise RuntimeError(f"No existe fila forward {signal_date} para {model.get('name')}")
    if not finite(target.get("base_vc")):
        raise RuntimeError(f"Falta base_vc para {model.get('name')}")

    est = float(target["base_vc"]) * (1.0 + rr)
    sig = classify(rr)
    target.update({"return_estimated": rr, "vc_estimated": est, "signal": sig})
    cur.update({"return_estimated": rr, "vc_estimated": est, "signal": sig})
    model["source_note"] = (
        ("Modelo B: .INX, CPER, EEM, NDX, SPBLSCUP y USD/PEN. " if is_new else
         "Modelo A: SPY, EEM, EPU, MCHI, QQQ y USD/PEN. ")
        + "Regla FX operativa común: BCRP PD04638PD si existe dato oficial de la fecha; "
          "si BCRP aún no publicó, TuCambista midpoint provisional. Yahoo PEN=X no entra en los dos Rolling 30."
    )
    return rr, est


def main() -> None:
    if not DUAL.exists() or not LIVE.exists():
        raise RuntimeError("Faltan dual_rolling30_monitor.json o live_market.json")

    dual = json.loads(DUAL.read_text(encoding="utf-8"))
    signal_date = str(dual.get("signal_date") or "")[:10]
    if not signal_date:
        raise RuntimeError("dual sin signal_date")

    fx = operational_fx(signal_date)
    model_a = dual.get("models", {}).get("qqq", {})
    model_b = dual.get("models", {}).get("new_tickers", {})
    rr_a, est_a = recalc_model(model_a, fx, is_new=False)
    rr_b, est_b = recalc_model(model_b, fx, is_new=True)

    dual["shared_fx_operational"] = {
        **fx,
        "rule": "BCRP PD04638PD oficial de la fecha; si todavía no existe, TuCambista midpoint provisional. Mismo USD/PEN para ambos Rolling 30; Yahoo PEN=X excluido.",
    }
    dual["comparison"] = {
        **(dual.get("comparison") or {}),
        "vc_difference": float(est_b) - float(est_a),
        "return_difference": float(rr_b) - float(rr_a),
    }
    DUAL.write_text(json.dumps(dual, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "signal_date": signal_date,
        "shared_fx": dual["shared_fx_operational"],
        "qqq": {"return": rr_a, "vc": est_a},
        "new_tickers": {"return": rr_b, "vc": est_b},
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
