from __future__ import annotations

import html
import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public" / "data"
DATA = ROOT / "data" / "rolling90"
LIVE_PATH = PUBLIC / "live_market.json"
LATEST_PATH = PUBLIC / "latest.json"
MARKETS_PATH = DATA / "markets.csv"
SBS_PATH = DATA / "sbs_profuturo_f3.csv"
LIMA = ZoneInfo("America/Lima")

MONTHS_ES = {1:"enero",2:"febrero",3:"marzo",4:"abril",5:"mayo",6:"junio",7:"julio",8:"agosto",9:"septiembre",10:"octubre",11:"noviembre",12:"diciembre"}
TUCAMBISTA_VERIFIED = {"2026-08-28": {"buy": 3.339, "sell": 3.368}}
YAHOO_FINAL = {".INX":"^GSPC", "CPER":"CPER", "EEM":"EEM", "NDX":"^NDX"}


def _extract_close(raw: pd.DataFrame, ticker: str) -> pd.Series:
    if raw.empty:
        return pd.Series(dtype=float)
    if isinstance(raw.columns, pd.MultiIndex):
        for key in [("Close", ticker), (ticker, "Close")]:
            if key in raw.columns:
                return pd.to_numeric(raw[key], errors="coerce").dropna()
        if "Close" in raw.columns.get_level_values(0):
            block = raw.xs("Close", axis=1, level=0)
            if ticker in block.columns:
                return pd.to_numeric(block[ticker], errors="coerce").dropna()
    if "Close" in raw.columns:
        return pd.to_numeric(raw["Close"], errors="coerce").dropna()
    return pd.Series(dtype=float)


def _tucambista_url(day: pd.Timestamp) -> str:
    return f"https://tucambista.pe/tipo-de-cambio-{day.day}-de-{MONTHS_ES[day.month]}"


def _parse_tucambista(text: str) -> tuple[float, float]:
    plain = html.unescape(text)
    plain = re.sub(r"<script\b[^>]*>.*?</script>|<style\b[^>]*>.*?</style>", " ", plain, flags=re.I|re.S)
    plain = re.sub(r"<[^>]+>", " ", plain)
    plain = re.sub(r"\s+", " ", plain)
    def pick(label: str) -> float | None:
        for pattern in [rf"{label}\s*(?:S/?\.?\s*)?[:\-]?\s*([23]\.[0-9]{{3,4}})", rf"{label}.{{0,100}}?([23]\.[0-9]{{3,4}})"]:
            m = re.search(pattern, plain, flags=re.I)
            if m:
                value = float(m.group(1))
                if 2 < value < 6:
                    return value
        return None
    buy, sell = pick("Compra"), pick("Venta")
    if buy is None or sell is None:
        raise RuntimeError("No se pudieron leer Compra/Venta de TuCambista")
    return float(buy), float(sell)


def tucambista_quote(day: pd.Timestamp) -> dict:
    key = day.strftime("%Y-%m-%d")
    url = _tucambista_url(day)
    try:
        r = requests.get(url, timeout=15, headers={"User-Agent":"Mozilla/5.0 Chrome/131 Safari/537.36", "Accept-Language":"es-PE,es;q=0.9"})
        r.raise_for_status()
        buy, sell = _parse_tucambista(r.text)
        source = "TUCAMBISTA WEB"
    except Exception as exc:
        verified = TUCAMBISTA_VERIFIED.get(key)
        if not verified:
            raise RuntimeError(f"TuCambista no disponible para {key}: {exc}") from exc
        buy, sell = float(verified["buy"]), float(verified["sell"])
        source = "TUCAMBISTA VERIFICADO"
    return {"buy":buy, "sell":sell, "midpoint":(buy+sell)/2.0, "source":source, "url":url}


def yahoo_daily_close(ticker: str, day: pd.Timestamp) -> tuple[float,float,float]:
    raw = yf.download(ticker, start=(day-pd.Timedelta(days=8)).strftime("%Y-%m-%d"), end=(day+pd.Timedelta(days=3)).strftime("%Y-%m-%d"), interval="1d", auto_adjust=False, actions=False, progress=False, threads=False)
    close = _extract_close(raw, ticker)
    if close.empty:
        raise RuntimeError(f"Yahoo no devolvio {ticker}")
    idx = pd.to_datetime(close.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    frame = pd.DataFrame({"fecha":idx.normalize(), "close":close.to_numpy(float)}).sort_values("fecha").drop_duplicates("fecha", keep="last")
    same, prior = frame.loc[frame.fecha.eq(day)], frame.loc[frame.fecha.lt(day)]
    if same.empty or prior.empty:
        raise RuntimeError(f"Sin cierre exacto {day.date()} para {ticker}")
    current, previous = float(same.iloc[-1].close), float(prior.iloc[-1].close)
    return previous, current, current/previous-1.0


def fx_asset(live: dict) -> dict:
    for asset in live.get("assets", []):
        if asset.get("serie") == "USD_PEN":
            return asset
    raise RuntimeError("No existe USD_PEN")


def apply_tucambista(live: dict, signal_date: pd.Timestamp) -> None:
    fx = fx_asset(live)
    if "BCRP MISMA FECHA" in str(fx.get("estado", "")) and str(fx.get("timestamp", ""))[:10] == signal_date.strftime("%Y-%m-%d"):
        live["fx_source"], live["fx_provisional"] = "BCRP", False
        return
    quote = tucambista_quote(signal_date)
    previous = float(fx.get("precio_actual") or fx.get("precio_anterior"))
    current = float(quote["midpoint"])
    ret = current/previous - 1.0
    fx.update({"ticker":"TUCAMBISTA","timestamp":signal_date.strftime("%Y-%m-%d"),"precio_anterior":previous,"precio_actual":current,"retorno":ret,"retorno_modelo":ret,"estado":"TUCAMBISTA MIDPOINT · MISMO DIA · USADO POR MODELO","usado_modelo":True})
    live.update({"fx_source":"TUCAMBISTA MIDPOINT","fx_provisional":True,"fx_buy":quote["buy"],"fx_sell":quote["sell"],"fx_midpoint":quote["midpoint"],"fx_url":quote["url"],"fx_rule":"BCRP para la fecha cuando existe; si BCRP aun no publica, TuCambista midpoint (Compra+Venta)/2 del mismo dia. Yahoo no se usa para USD/PEN."})


def predict(beta: dict, values: dict[str,float]) -> float:
    required = [k for k in beta if k.startswith("ret_")]
    missing = [k for k in required if k not in values or not np.isfinite(values[k])]
    if missing:
        raise RuntimeError(f"Faltan factores OLS: {missing}")
    return float(beta.get("intercept",0.0) + sum(float(beta[k])*float(values[k]) for k in required))


def recalc_chain(live: dict, latest: dict, signal_date: pd.Timestamp) -> None:
    beta = latest.get("coefficients") or {}
    markets = pd.read_csv(MARKETS_PATH)
    sbs = pd.read_csv(SBS_PATH)
    markets["fecha"] = pd.to_datetime(markets["fecha"], errors="coerce").dt.normalize()
    sbs["fecha"] = pd.to_datetime(sbs["fecha"], errors="coerce").dt.normalize()
    sbs["valor_cuota"] = pd.to_numeric(sbs["valor_cuota"], errors="coerce")
    anchors = sbs.dropna(subset=["fecha","valor_cuota"]).loc[lambda x:x.fecha.lt(signal_date)].sort_values("fecha")
    if anchors.empty:
        raise RuntimeError("No existe VC SBS real anterior a la fecha de señal")
    anchor = anchors.iloc[-1]
    anchor_date, vc = pd.Timestamp(anchor.fecha), float(anchor.valor_cuota)
    chain = []
    required = [k for k in beta if k.startswith("ret_")]
    live_values = {}
    for asset in live.get("assets", []):
        key = f"ret_{asset.get('serie','')}"
        if key in required:
            raw = asset.get("retorno_modelo") if asset.get("retorno_modelo") is not None else asset.get("retorno")
            live_values[key] = float(raw)
    candidates = markets.loc[(markets.fecha.gt(anchor_date)) & (markets.fecha.le(signal_date))].sort_values("fecha")
    for _, row in candidates.iterrows():
        day = pd.Timestamp(row.fecha)
        if day.eq(signal_date):
            values = live_values
        else:
            values = {k: float(row[k]) for k in required if k in row and pd.notna(row[k])}
        if any(k not in values for k in required):
            continue
        p = predict(beta, values)
        vc *= 1.0 + p
        chain.append({"fecha":day.strftime("%Y-%m-%d"),"ret_estimado":p,"vc_estimado":vc})
    if not chain or chain[-1]["fecha"] != signal_date.strftime("%Y-%m-%d"):
        raise RuntimeError(f"No se pudo reconstruir cadena hasta {signal_date.date()}")
    final = chain[-1]
    threshold = float(latest.get("threshold",0.001))
    live.update({"vc_base":float(anchor.valor_cuota),"vc_anchor_date":anchor_date.strftime("%Y-%m-%d"),"return_estimated":final["ret_estimado"],"vc_estimated":final["vc_estimado"],"signal":"SUBE" if final["ret_estimado"]>threshold else ("BAJA" if final["ret_estimado"] < -threshold else "NEUTRO"),"model_snapshot_source":"CIERRE RECALCULADO · ULTIMO SBS REAL + FACTORES DEFINITIVOS + TUCAMBISTA","model_snapshot_date":signal_date.strftime("%Y-%m-%d"),"vc_chain_after_sbs":chain})
    live.pop("warning", None)


def finalize_experimental(live: dict, signal_date: pd.Timestamp) -> None:
    if bool(live.get("market_open")):
        return
    old = {str(x.get("serie")):dict(x) for x in live.get("experimental_assets",[]) if x.get("serie")}
    rows, problems = [], []
    for symbol,ticker in YAHOO_FINAL.items():
        try:
            previous,current,ret = yahoo_daily_close(ticker, signal_date)
            rows.append({"serie":symbol,"ticker":ticker,"timestamp":signal_date.strftime("%Y-%m-%d"),"precio_anterior":previous,"precio_actual":current,"retorno":ret,"retorno_modelo":None,"estado":"CIERRE DIARIO DEFINITIVO YAHOO · VALIDADO POST-CIERRE","usado_modelo":False,"validado_modelo":True,"error_validacion":None})
        except Exception as exc:
            prior = old.get(symbol,{"serie":symbol,"ticker":ticker})
            prior.update({"validado_modelo":False,"estado":"CIERRE DIARIO NO DISPONIBLE","error_validacion":str(exc)})
            rows.append(prior); problems.append(symbol)
    sp = old.get("SPBLSCUP")
    if sp and str(sp.get("timestamp",""))[:10] == signal_date.strftime("%Y-%m-%d") and sp.get("precio_actual") is not None:
        sp.update({"validado_modelo":True,"error_validacion":None}); rows.append(sp)
    else:
        if sp: rows.append(sp)
        problems.append("SPBLSCUP")
    fx = fx_asset(live)
    rows.append({"serie":"USD/PEN","ticker":fx.get("ticker"),"timestamp":fx.get("timestamp"),"precio_anterior":fx.get("precio_anterior"),"precio_actual":fx.get("precio_actual"),"retorno":fx.get("retorno"),"retorno_modelo":None,"estado":f"{fx.get('estado','')} · NUEVO 60/30 EXPERIMENTAL","usado_modelo":False,"validado_modelo":True,"error_validacion":None})
    live["experimental_assets"] = rows
    live["new_ticker_validation"] = {"signal_date":signal_date.strftime("%Y-%m-%d"),"status":"COMPLETO/VALIDADO" if not problems else "INCOMPLETO","problems":problems,"rule":"Fuera del horario de mercado se exige cierre diario exacto de la fecha; no se conservan capturas 15:55 como cierre."}


def main() -> None:
    live = json.loads(LIVE_PATH.read_text(encoding="utf-8"))
    latest = json.loads(LATEST_PATH.read_text(encoding="utf-8"))
    signal_date = pd.Timestamp(str(live.get("signal_date",""))[:10]).normalize()
    apply_tucambista(live, signal_date)
    recalc_chain(live, latest, signal_date)
    finalize_experimental(live, signal_date)
    live["finalized_at_lima"] = datetime.now(LIMA).isoformat()
    live["finalizer_version"] = "tucambista-final-close-v2"
    LIVE_PATH.write_text(json.dumps(live,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"signal_date":live.get("signal_date"),"fx_source":live.get("fx_source"),"fx_midpoint":live.get("fx_midpoint"),"vc_anchor_date":live.get("vc_anchor_date"),"vc_estimated":live.get("vc_estimated"),"return_estimated":live.get("return_estimated"),"signal":live.get("signal"),"new_ticker_validation":live.get("new_ticker_validation")},ensure_ascii=False,indent=2))

if __name__ == "__main__":
    main()
