from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public" / "data"
DUAL = PUBLIC / "dual_rolling30_monitor.json"
LIVE = PUBLIC / "live_market.json"
CACHE = ROOT / "data" / "rolling90" / "bcrp_pd04638_cache.csv"

BCRP_URL = "https://estadisticas.bcrp.gob.pe/estadisticas/series/api/PD04638PD/json"
BCRP_HTML_URL = "https://estadisticas.bcrp.gob.pe/estadisticas/series/diarias/resultados/pd04638pd"
TUCAMBISTA_URL = "https://tucambista.pe/"
TUCAMBISTA_VERIFIED = {
    "2026-08-28": {"buy": 3.339, "sell": 3.368},
}
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
    m = re.search(r"(\d{1,2})[.\-/ ]*([a-záéíóú]+)[.\-/ ]*(\d{2,4})", s)
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


def normalize_rows(rows: list[tuple[str, float]]) -> list[tuple[str, float]]:
    m: dict[str, float] = {}
    for d, v in rows:
        if d and finite(v):
            m[str(d)[:10]] = float(v)
    return sorted(m.items(), key=lambda x: x[0])


def read_cache() -> list[tuple[str, float]]:
    if not CACHE.exists():
        return []
    try:
        d = pd.read_csv(CACHE)
        d["fecha"] = pd.to_datetime(d["fecha"], errors="coerce").dt.strftime("%Y-%m-%d")
        d["USD_PEN_BCRP"] = pd.to_numeric(d["USD_PEN_BCRP"], errors="coerce")
        return normalize_rows([(r["fecha"], r["USD_PEN_BCRP"]) for _, r in d.dropna().iterrows()])
    except Exception as exc:
        print("Cache BCRP no legible:", type(exc).__name__, exc)
        return []


def write_cache(rows: list[tuple[str, float]]) -> None:
    if not rows:
        return
    old = read_cache()
    merged = normalize_rows(old + rows)
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(merged, columns=["fecha", "USD_PEN_BCRP"]).to_csv(CACHE, index=False)


def bcrp_from_api() -> list[tuple[str, float]]:
    r = requests.get(BCRP_URL, timeout=30, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json,text/plain,*/*"})
    r.raise_for_status()
    try:
        payload = r.json()
    except Exception as exc:
        raise RuntimeError(f"BCRP API no devolvió JSON; content-type={r.headers.get('content-type')}") from exc
    rows: list[tuple[str, float]] = []
    for p in payload.get("periods", []):
        d = parse_bcrp_date(p.get("name"))
        raw = (p.get("values") or [None])[0]
        if not d or raw in (None, "", "n.d."):
            continue
        if finite(raw):
            rows.append((d, float(raw)))
    return normalize_rows(rows)


def bcrp_from_html() -> list[tuple[str, float]]:
    r = requests.get(BCRP_HTML_URL, timeout=30, headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "es-PE,es;q=0.9,en;q=0.8"})
    r.raise_for_status()
    text = re.sub(r"<[^>]+>", " ", r.text)
    text = re.sub(r"\s+", " ", text)
    rows: list[tuple[str, float]] = []
    pat = re.compile(r"(\d{1,2})\s*[.\-/ ]?\s*(Ene|Feb|Mar|Abr|May|Jun|Jul|Ago|Set|Sep|Oct|Nov|Dic)\s*[.\-/ ]?\s*(\d{2,4})\s+(\d+[.,]\d+|n\.d\.)", re.I)
    for day, mon, year, raw in pat.findall(text):
        if raw.lower().startswith("n.d"):
            continue
        d = parse_bcrp_date(f"{day}.{mon}.{year}")
        value = raw.replace(",", ".")
        if d and finite(value):
            rows.append((d, float(value)))
    return normalize_rows(rows)


def load_bcrp() -> tuple[list[tuple[str, float]], str]:
    errors = []
    for name, fn in (("API", bcrp_from_api), ("HTML", bcrp_from_html)):
        try:
            rows = fn()
            if rows:
                write_cache(rows)
                return rows, f"BCRP PD04638PD · {name}"
            errors.append(f"{name}: vacío")
        except Exception as exc:
            errors.append(f"{name}: {type(exc).__name__}: {exc}")
    cache = read_cache()
    if cache:
        print("BCRP remoto no disponible; usando cache oficial:", " | ".join(errors))
        return cache, "BCRP PD04638PD · CACHE OFICIAL"
    raise RuntimeError("No se pudo obtener BCRP PD04638PD: " + " | ".join(errors))


def tucambista_midpoint(signal_date: str) -> tuple[float, str]:
    verified = TUCAMBISTA_VERIFIED.get(signal_date)
    if verified:
        compra = float(verified["buy"])
        venta = float(verified["sell"])
        return (compra + venta) / 2.0, f"TUCAMBISTA MIDPOINT ({compra:.3f}/{venta:.3f}) · VERIFICADO POR FECHA"

    r = requests.get(TUCAMBISTA_URL, timeout=25, headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "es-PE,es;q=0.9"})
    r.raise_for_status()
    clean = re.sub(r"<[^>]+>", " ", r.text)
    clean = re.sub(r"\s+", " ", clean)
    patterns = [
        (r"Compra\s*:?[\s]*(\d+[.,]\d+)", r"Venta\s*:?[\s]*(\d+[.,]\d+)"),
        (r"Compra[^0-9]{0,100}(\d+[.,]\d+)", r"Venta[^0-9]{0,100}(\d+[.,]\d+)"),
    ]
    for pb, ps in patterns:
        buy = re.search(pb, clean, flags=re.IGNORECASE); sell = re.search(ps, clean, flags=re.IGNORECASE)
        if buy and sell:
            compra = float(buy.group(1).replace(",", ".")); venta = float(sell.group(1).replace(",", "."))
            if 2.0 < compra < 6.0 and 2.0 < venta < 6.0:
                return (compra + venta) / 2.0, f"TUCAMBISTA MIDPOINT ({compra:.3f}/{venta:.3f})"
    raise RuntimeError("TuCambista no devolvió compra/venta reconocibles")


def operational_fx(signal_date: str) -> dict:
    bcrp, bcrp_method = load_bcrp()
    prior = [(d, v) for d, v in bcrp if d < signal_date]
    if not prior:
        raise RuntimeError(f"No existe BCRP previo a {signal_date}")
    prev_date, prev_value = prior[-1]
    same = [(d, v) for d, v in bcrp if d == signal_date]
    if same:
        current = float(same[-1][1])
        return {"value": current,"previous_value": float(prev_value),"previous_date": prev_date,"return": current / float(prev_value) - 1.0,"source": bcrp_method + " · TC INTERBANCARIO VENTA · OFICIAL","provisional": False}
    current, label = tucambista_midpoint(signal_date)
    return {"value": float(current),"previous_value": float(prev_value),"previous_date": prev_date,"return": float(current) / float(prev_value) - 1.0,"source": label + f" · PROVISIONAL · BASE {bcrp_method} {prev_date}","provisional": True}


def replace_fx_asset(model: dict, asset_name: str, fx: dict) -> dict:
    assets = model.get("intraday_assets") or []
    row = next((a for a in assets if str(a.get("serie")) == asset_name), None)
    if row is None:
        row = {"serie": asset_name, "ticker": "USD/PEN"}; assets.append(row)
    row.update({"ticker": "BCRP PD04638PD" if not fx["provisional"] else "TUCAMBISTA","timestamp": model.get("current", {}).get("fecha"),"precio_anterior": fx["previous_value"],"precio_actual": fx["value"],"retorno": fx["return"],"retorno_modelo": fx["return"],"estado": fx["source"],"usado_modelo": True})
    model["intraday_assets"] = assets
    return row


def recalc_model(model: dict, fx: dict, is_new: bool) -> tuple[float, float]:
    cur = model.get("current", {}); coeff = cur.get("coefficients") or {}; signal_date = str(cur.get("fecha") or "")[:10]
    if not signal_date or not coeff: raise RuntimeError(f"Modelo sin fecha/coeficientes: {model.get('name')}")
    fx_name = "USD/PEN" if is_new else "USD_PEN"; replace_fx_asset(model, fx_name, fx)
    by = {str(a.get("serie")): a for a in model.get("intraday_assets", [])}
    mapping = ({"ret_.INX":".INX","ret_CPER":"CPER","ret_EEM_alt":"EEM","ret_NDX":"NDX","ret_SPBLSCUP":"SPBLSCUP","ret_USD_PEN_alt":"USD/PEN"} if is_new else {"ret_SPY":"SPY","ret_EEM":"EEM","ret_EPU":"EPU","ret_MCHI":"MCHI","ret_USD_PEN":"USD_PEN","ret_QQQ":"QQQ"})
    rr = float(coeff.get("intercept", 0.0))
    for feature, asset_name in mapping.items():
        r = pick_return(by.get(asset_name) or {})
        if r is None or not finite(coeff.get(feature)): raise RuntimeError(f"Falta {feature}/{asset_name} para {model.get('name')}")
        rr += float(coeff[feature]) * r
    chain = model.get("forward_chain") or []; target = next((r for r in reversed(chain) if str(r.get("fecha"))[:10] == signal_date), None)
    if target is None or not finite(target.get("base_vc")): raise RuntimeError(f"Falta fila/base forward {signal_date} para {model.get('name')}")
    est = float(target["base_vc"]) * (1.0 + rr); sig = classify(rr)
    target.update({"return_estimated": rr,"vc_estimated": est,"signal": sig}); cur.update({"return_estimated": rr,"vc_estimated": est,"signal": sig})
    model["source_note"] = (("Modelo B: .INX, CPER, EEM, NDX, SPBLSCUP y USD/PEN. " if is_new else "Modelo A: SPY, EEM, EPU, MCHI, QQQ y USD/PEN. ") + "Regla FX común: BCRP PD04638PD si existe dato oficial de la fecha; si BCRP aún no publicó, TuCambista midpoint provisional por fecha. Yahoo PEN=X no entra en los dos Rolling 30.")
    return rr, est


def main() -> None:
    if not DUAL.exists() or not LIVE.exists(): raise RuntimeError("Faltan dual_rolling30_monitor.json o live_market.json")
    dual = json.loads(DUAL.read_text(encoding="utf-8")); signal_date = str(dual.get("signal_date") or "")[:10]
    if not signal_date: raise RuntimeError("dual sin signal_date")
    fx = operational_fx(signal_date); model_a = dual.get("models", {}).get("qqq", {}); model_b = dual.get("models", {}).get("new_tickers", {})
    rr_a, est_a = recalc_model(model_a, fx, is_new=False); rr_b, est_b = recalc_model(model_b, fx, is_new=True)
    dual["shared_fx_operational"] = {**fx,"rule": "BCRP PD04638PD oficial de la fecha; si todavía no existe, TuCambista midpoint provisional de la misma fecha. Mismo USD/PEN para ambos Rolling 30; Yahoo PEN=X excluido."}
    dual["comparison"] = {**(dual.get("comparison") or {}),"vc_difference": float(est_b) - float(est_a),"return_difference": float(rr_b) - float(rr_a)}
    DUAL.write_text(json.dumps(dual, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"signal_date": signal_date,"shared_fx": dual["shared_fx_operational"],"qqq": {"return": rr_a,"vc": est_a},"new_tickers": {"return": rr_b,"vc": est_b}}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
