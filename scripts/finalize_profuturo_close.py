from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "rolling90"
PUBLIC = ROOT / "public" / "data"
LIVE_PATH = PUBLIC / "live_market.json"
LATEST_PATH = PUBLIC / "latest.json"
MARKETS_PATH = DATA / "markets.csv"
SBS_PATH = DATA / "sbs_profuturo_f3.csv"
LIMA = ZoneInfo("America/Lima")

# Cotizaciones históricas de TuCambista verificadas contra la página fechada.
# Para una fecha ya cerrada tienen prioridad sobre una relectura dinámica del sitio.
TUCAMBISTA_VERIFIED = {
    "2026-08-28": {"buy": 3.339, "sell": 3.368},
}

YAHOO_FINAL = {
    ".INX": "^GSPC",
    "CPER": "CPER",
    "EEM": "EEM",
    "NDX": "^NDX",
}


def extract_close(raw: pd.DataFrame, ticker: str) -> pd.Series:
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


def yahoo_close(ticker: str, day: pd.Timestamp) -> tuple[float, float, float]:
    raw = yf.download(
        ticker,
        start=(day - pd.Timedelta(days=8)).strftime("%Y-%m-%d"),
        end=(day + pd.Timedelta(days=3)).strftime("%Y-%m-%d"),
        interval="1d",
        auto_adjust=False,
        actions=False,
        progress=False,
        threads=False,
    )
    close = extract_close(raw, ticker)
    if close.empty:
        raise RuntimeError(f"Sin datos Yahoo para {ticker}")
    idx = pd.to_datetime(close.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    frame = pd.DataFrame({"fecha": idx.normalize(), "close": close.to_numpy(float)})
    frame = frame.sort_values("fecha").drop_duplicates("fecha", keep="last")
    current = frame.loc[frame.fecha == day]
    previous = frame.loc[frame.fecha < day]
    if current.empty or previous.empty:
        raise RuntimeError(f"No existe cierre exacto {day.date()} para {ticker}")
    cur = float(current.iloc[-1].close)
    prev = float(previous.iloc[-1].close)
    return prev, cur, cur / prev - 1.0


def fx_asset(live: dict) -> dict:
    for row in live.get("assets", []):
        if row.get("serie") == "USD_PEN":
            return row
    raise RuntimeError("Falta USD_PEN en live_market.json")


def tucambista_quote(day: pd.Timestamp) -> dict:
    key = day.strftime("%Y-%m-%d")
    verified = TUCAMBISTA_VERIFIED.get(key)
    if verified:
        buy = float(verified["buy"])
        sell = float(verified["sell"])
        return {
            "buy": buy,
            "sell": sell,
            "midpoint": (buy + sell) / 2.0,
            "source": "TUCAMBISTA VERIFICADO POR FECHA",
            "url": f"https://tucambista.pe/tipo-de-cambio-{day.day}-de-agosto",
        }
    # Para fechas futuras/no congeladas se consulta la página del día y se exige
    # que el JSON embebido o texto visible contenga Compra y Venta inequívocas.
    url = "https://tucambista.pe/"
    r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    import re
    text = re.sub(r"<[^>]+>", " ", r.text)
    buy_m = re.search(r"Compra\s*:?\s*([23]\.[0-9]{3,4})", text, re.I)
    sell_m = re.search(r"Venta\s*:?\s*([23]\.[0-9]{3,4})", text, re.I)
    if not buy_m or not sell_m:
        raise RuntimeError("TuCambista no devolvió Compra/Venta inequívocas")
    buy, sell = float(buy_m.group(1)), float(sell_m.group(1))
    return {"buy": buy, "sell": sell, "midpoint": (buy + sell) / 2.0, "source": "TUCAMBISTA WEB", "url": url}


def apply_fx(live: dict, day: pd.Timestamp) -> None:
    fx = fx_asset(live)
    if "BCRP MISMA FECHA" in str(fx.get("estado", "")) and str(fx.get("timestamp", ""))[:10] == day.strftime("%Y-%m-%d"):
        live["fx_source"] = "BCRP"
        live["fx_provisional"] = False
        return
    quote = tucambista_quote(day)
    # El previo debe ser la observación previa real, no un midpoint ya sobrescrito.
    previous = float(fx.get("precio_anterior") or fx.get("precio_actual"))
    current = float(quote["midpoint"])
    ret = current / previous - 1.0
    fx.update({
        "ticker": "TUCAMBISTA",
        "timestamp": day.strftime("%Y-%m-%d"),
        "precio_anterior": previous,
        "precio_actual": current,
        "retorno": ret,
        "retorno_modelo": ret,
        "estado": "TUCAMBISTA MIDPOINT · MISMO DIA · USADO POR MODELO",
        "usado_modelo": True,
    })
    live.update({
        "fx_source": "TUCAMBISTA MIDPOINT",
        "fx_provisional": True,
        "fx_buy": quote["buy"],
        "fx_sell": quote["sell"],
        "fx_midpoint": quote["midpoint"],
        "fx_quote_source": quote["source"],
        "fx_url": quote["url"],
        "fx_rule": "BCRP si existe para la fecha; si no, TuCambista midpoint del mismo día. Yahoo no se usa para USD/PEN.",
    })


def model_return(beta: dict, values: dict[str, float]) -> float:
    factors = [k for k in beta if k.startswith("ret_")]
    missing = [k for k in factors if k not in values or not np.isfinite(values[k])]
    if missing:
        raise RuntimeError(f"Faltan factores OLS: {missing}")
    return float(beta.get("intercept", 0.0) + sum(float(beta[k]) * values[k] for k in factors))


def recalc_from_last_sbs(live: dict, latest: dict, signal_date: pd.Timestamp) -> None:
    beta = latest.get("coefficients") or {}
    markets = pd.read_csv(MARKETS_PATH)
    sbs = pd.read_csv(SBS_PATH)
    markets["fecha"] = pd.to_datetime(markets["fecha"], errors="coerce").dt.normalize()
    sbs["fecha"] = pd.to_datetime(sbs["fecha"], errors="coerce").dt.normalize()
    sbs["valor_cuota"] = pd.to_numeric(sbs["valor_cuota"], errors="coerce")

    anchors = sbs.dropna(subset=["fecha", "valor_cuota"])
    anchors = anchors.loc[anchors.fecha < signal_date].sort_values("fecha")
    if anchors.empty:
        raise RuntimeError("No existe VC SBS real anterior a la señal")
    anchor = anchors.iloc[-1]
    anchor_date = pd.Timestamp(anchor.fecha)
    vc = float(anchor.valor_cuota)

    factors = [k for k in beta if k.startswith("ret_")]
    live_values: dict[str, float] = {}
    for row in live.get("assets", []):
        key = f"ret_{row.get('serie', '')}"
        if key in factors:
            raw = row.get("retorno_modelo") if row.get("retorno_modelo") is not None else row.get("retorno")
            live_values[key] = float(raw)

    chain = []
    days = markets.loc[(markets.fecha > anchor_date) & (markets.fecha <= signal_date)].sort_values("fecha")
    for _, row in days.iterrows():
        day = pd.Timestamp(row.fecha)
        if day == signal_date:
            values = live_values
        else:
            values = {k: float(row[k]) for k in factors if k in row.index and pd.notna(row[k])}
        if any(k not in values for k in factors):
            continue
        pred = model_return(beta, values)
        vc *= 1.0 + pred
        chain.append({"fecha": day.strftime("%Y-%m-%d"), "ret_estimado": pred, "vc_estimado": vc})

    if not chain or chain[-1]["fecha"] != signal_date.strftime("%Y-%m-%d"):
        raise RuntimeError("La cadena estimada no llegó a la fecha de señal")
    final = chain[-1]
    threshold = float(latest.get("threshold", 0.001))
    live.update({
        "vc_base": float(anchor.valor_cuota),
        "vc_anchor_date": anchor_date.strftime("%Y-%m-%d"),
        "return_estimated": final["ret_estimado"],
        "vc_estimated": final["vc_estimado"],
        "signal": "SUBE" if final["ret_estimado"] > threshold else ("BAJA" if final["ret_estimado"] < -threshold else "NEUTRO"),
        "model_snapshot_source": "CIERRE RECALCULADO · ULTIMO SBS REAL + FACTORES DEFINITIVOS + TUCAMBISTA",
        "model_snapshot_date": signal_date.strftime("%Y-%m-%d"),
        "vc_chain_after_sbs": chain,
    })
    live.pop("warning", None)


def finalize_experimental(live: dict, signal_date: pd.Timestamp) -> None:
    if bool(live.get("market_open")):
        return
    old = {str(x.get("serie")): dict(x) for x in live.get("experimental_assets", []) if x.get("serie")}
    rows, problems = [], []
    for symbol, ticker in YAHOO_FINAL.items():
        try:
            prev, cur, ret = yahoo_close(ticker, signal_date)
            rows.append({
                "serie": symbol, "ticker": ticker, "timestamp": signal_date.strftime("%Y-%m-%d"),
                "precio_anterior": prev, "precio_actual": cur, "retorno": ret, "retorno_modelo": None,
                "estado": "CIERRE DIARIO DEFINITIVO YAHOO · VALIDADO POST-CIERRE",
                "usado_modelo": False, "validado_modelo": True, "error_validacion": None,
            })
        except Exception as exc:
            prior = old.get(symbol, {"serie": symbol, "ticker": ticker})
            prior.update({"validado_modelo": False, "estado": "CIERRE DIARIO NO DISPONIBLE", "error_validacion": str(exc)})
            rows.append(prior)
            problems.append(symbol)

    sp = old.get("SPBLSCUP")
    if sp and str(sp.get("timestamp", ""))[:10] == signal_date.strftime("%Y-%m-%d") and sp.get("precio_actual") is not None:
        sp.update({"validado_modelo": True, "error_validacion": None})
        rows.append(sp)
    else:
        if sp:
            rows.append(sp)
        problems.append("SPBLSCUP")

    fx = fx_asset(live)
    rows.append({
        "serie": "USD/PEN", "ticker": fx.get("ticker"), "timestamp": fx.get("timestamp"),
        "precio_anterior": fx.get("precio_anterior"), "precio_actual": fx.get("precio_actual"),
        "retorno": fx.get("retorno"), "retorno_modelo": None,
        "estado": f"{fx.get('estado', '')} · NUEVO 60/30 EXPERIMENTAL",
        "usado_modelo": False, "validado_modelo": True, "error_validacion": None,
    })
    live["experimental_assets"] = rows
    live["new_ticker_validation"] = {
        "signal_date": signal_date.strftime("%Y-%m-%d"),
        "status": "COMPLETO/VALIDADO" if not problems else "INCOMPLETO",
        "problems": problems,
        "rule": "Post-cierre se exige cierre diario exacto; una captura 15:55 nunca se acepta como cierre.",
    }


def main() -> None:
    live = json.loads(LIVE_PATH.read_text(encoding="utf-8"))
    latest = json.loads(LATEST_PATH.read_text(encoding="utf-8"))
    signal_date = pd.Timestamp(str(live.get("signal_date", ""))[:10]).normalize()
    apply_fx(live, signal_date)
    recalc_from_last_sbs(live, latest, signal_date)
    finalize_experimental(live, signal_date)
    live["finalized_at_lima"] = datetime.now(LIMA).isoformat()
    live["finalizer_version"] = "tucambista-final-close-v4"
    LIVE_PATH.write_text(json.dumps(live, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "signal_date": live.get("signal_date"),
        "fx_source": live.get("fx_source"),
        "fx_midpoint": live.get("fx_midpoint"),
        "vc_anchor_date": live.get("vc_anchor_date"),
        "vc_estimated": live.get("vc_estimated"),
        "return_estimated": live.get("return_estimated"),
        "signal": live.get("signal"),
        "new_ticker_validation": live.get("new_ticker_validation"),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
