from __future__ import annotations

import json
import re
import sys
from datetime import datetime, time as clock_time
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import patch_dual_rolling30_fx_operational as fxmod

LIVE = ROOT / "public" / "data" / "live_market.json"
LATEST = ROOT / "public" / "data" / "latest.json"
PENDING = ROOT / "data" / "rolling90" / "pending_predictions.csv"
NY = ZoneInfo("America/New_York")
LIMA = ZoneInfo("America/Lima")


def finite(v):
    try:
        return v is not None and np.isfinite(float(v))
    except Exception:
        return False


def close_series(raw, ticker):
    if raw.empty:
        return pd.Series(dtype=float)
    if isinstance(raw.columns, pd.MultiIndex):
        for key in [("Close", ticker), (ticker, "Close")]:
            if key in raw.columns:
                return pd.to_numeric(raw[key], errors="coerce").dropna()
        if "Close" in raw.columns.get_level_values(0):
            b = raw.xs("Close", axis=1, level=0)
            if ticker in b.columns:
                return pd.to_numeric(b[ticker], errors="coerce").dropna()
    if "Close" in raw.columns:
        return pd.to_numeric(raw["Close"], errors="coerce").dropna()
    return pd.Series(dtype=float)


def pair(ticker, target):
    raw = yf.download(ticker, period="12d", interval="1d", auto_adjust=False,
                      actions=False, progress=False, threads=False)
    s = close_series(raw, ticker)
    if s.empty:
        raise RuntimeError(f"Yahoo sin {ticker}")
    idx = pd.to_datetime(s.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    d = pd.DataFrame({"fecha": idx.normalize(), "close": s.to_numpy(float)})
    same = d[d.fecha.eq(target)]
    prev = d[d.fecha.lt(target)].tail(1)
    if same.empty or prev.empty:
        raise RuntimeError(f"Cierre {target.date()} no disponible para {ticker}")
    return float(prev.iloc[-1].close), float(same.iloc[-1].close)


def spblscup_google(target):
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait

    opts = webdriver.ChromeOptions()
    for arg in ("--headless=new", "--no-sandbox", "--disable-dev-shm-usage",
                "--disable-gpu", "--window-size=1920,1080", "--lang=en-US"):
        opts.add_argument(arg)
    driver = webdriver.Chrome(options=opts)
    try:
        driver.get("https://www.google.com/finance/quote/SPBLSCUP:INDEXSP?hl=en&gl=us")
        WebDriverWait(driver, 25).until(lambda d: d.find_element(By.TAG_NAME, "body"))
        body = re.sub(r"\s+", " ", driver.find_element(By.TAG_NAME, "body").text)

        price = None
        for el in driver.find_elements(By.CSS_SELECTOR, "[data-last-price]"):
            try:
                v = float(str(el.get_attribute("data-last-price")).replace(",", ""))
            except Exception:
                continue
            if 100 < v < 1000:
                price = v
                break
        if price is None:
            m = re.search(r"S&P(?:/BVL)?\s+Peru\s+Select\s+20%\s+Capped\s+Index\s*\(USD\)\s+([\d,]+(?:\.\d+)?)", body, re.I)
            if m:
                price = float(m.group(1).replace(",", ""))
        if price is None:
            raise RuntimeError("SPBLSCUP sin precio principal")

        pm = re.search(r"Prev(?:ious)?\.?\s*close\s+\$?([\d,]+(?:\.\d+)?)", body, re.I)
        if not pm:
            raise RuntimeError("SPBLSCUP sin previous close")
        previous = float(pm.group(1).replace(",", ""))

        stamp = None
        for el in driver.find_elements(By.CSS_SELECTOR, "[data-last-normal-market-timestamp]"):
            raw = el.get_attribute("data-last-normal-market-timestamp")
            if not raw:
                continue
            try:
                sec = int(raw)
                if sec > 10_000_000_000:
                    sec //= 1000
                dt = datetime.fromtimestamp(sec, tz=NY)
                if dt.date() == target.date():
                    stamp = dt
                    break
            except Exception:
                pass
        if stamp is None:
            raise RuntimeError("SPBLSCUP no confirma la fecha de sesión")
        return previous, float(price), float(price / previous - 1.0), stamp.isoformat()
    finally:
        driver.quit()


def classify(v):
    return "SUBE" if v > 0.001 else ("BAJA" if v < -0.001 else "NEUTRO")


def main():
    now_ny = datetime.now(NY)
    target = pd.Timestamp(now_ny.date()).normalize()
    if target.weekday() >= 5 or now_ny.time() < clock_time(16, 5):
        print("No corresponde forzar cierre de sesión actual")
        return

    latest = json.loads(LATEST.read_text(encoding="utf-8"))
    old = json.loads(LIVE.read_text(encoding="utf-8")) if LIVE.exists() else {}
    coeff = latest.get("coefficients") or {}
    core_names = [k[4:] for k in coeff if str(k).startswith("ret_") and k != "ret_USD_PEN"]
    if not core_names:
        raise RuntimeError("latest.json sin factores")

    features = {}
    assets = []
    for name in core_names:
        prev, cur = pair(name, target)
        ret = cur / prev - 1.0
        features[f"ret_{name}"] = ret
        assets.append({"serie": name, "ticker": name, "timestamp": target.date().isoformat(),
                       "precio_anterior": prev, "precio_actual": cur, "retorno": ret,
                       "retorno_modelo": ret, "estado": "YAHOO · CIERRE SESIÓN ACTUAL · USADO POR MODELO",
                       "usado_modelo": True})

    fx = fxmod.operational_fx(target.date().isoformat())
    fxrow = {"serie": "USD_PEN", "ticker": "BCRP PD04638PD" if not fx["provisional"] else "TUCAMBISTA",
             "timestamp": target.date().isoformat(), "precio_anterior": float(fx["previous_value"]),
             "precio_actual": float(fx["value"]), "retorno": float(fx["return"]),
             "retorno_modelo": float(fx["return"]), "estado": str(fx["source"]) + " · USADO POR MODELO",
             "usado_modelo": True}
    assets.append(fxrow)
    features["ret_USD_PEN"] = float(fx["return"])

    experimental = []
    for name, ticker in {".INX": "^GSPC", "CPER": "CPER", "EEM": "EEM", "NDX": "^NDX"}.items():
        prev, cur = pair(ticker, target)
        ret = cur / prev - 1.0
        experimental.append({"serie": name, "ticker": ticker, "timestamp": target.date().isoformat(),
                             "precio_anterior": prev, "precio_actual": cur, "retorno": ret,
                             "retorno_modelo": ret, "estado": f"YAHOO {ticker} · CIERRE VALIDADO",
                             "usado_modelo": True, "validado_modelo": True})

    prev, cur, ret, stamp = spblscup_google(target)
    experimental.append({"serie": "SPBLSCUP", "ticker": "SPBLSCUP:INDEXSP",
                         "timestamp": target.date().isoformat(), "precio_anterior": prev,
                         "precio_actual": cur, "retorno": ret, "retorno_modelo": ret,
                         "estado": "GOOGLE FINANCE · SESIÓN ACTUAL VALIDADA", "usado_modelo": True,
                         "validado_modelo": True, "google_stamp": stamp})
    experimental.append({"serie": "USD/PEN", "ticker": fxrow["ticker"],
                         "timestamp": target.date().isoformat(), "precio_anterior": fxrow["precio_anterior"],
                         "precio_actual": fxrow["precio_actual"], "retorno": fxrow["retorno"],
                         "retorno_modelo": fxrow["retorno_modelo"], "estado": fxrow["estado"],
                         "usado_modelo": True, "validado_modelo": True})

    pred = float(coeff.get("intercept", 0.0))
    for f, v in features.items():
        if f in coeff:
            pred += float(coeff[f]) * float(v)

    pending = pd.read_csv(PENDING) if PENDING.exists() else pd.DataFrame()
    vc_base = float(latest["latest_sbs_vc"])
    if not pending.empty and "fecha" in pending.columns:
        pending["fecha"] = pd.to_datetime(pending["fecha"], errors="coerce").dt.normalize()
        prior = pending[pending.fecha.lt(target)].sort_values("fecha")
        if not prior.empty and finite(prior.iloc[-1].get("valor_cuota_estimado")):
            vc_base = float(prior.iloc[-1]["valor_cuota_estimado"])

    payload = {"generated_at_lima": datetime.now(LIMA).isoformat(), "mode": "CIERRE DIARIO",
               "market_open": False, "signal_date": target.date().isoformat(), "vc_base": vc_base,
               "vc_estimated": vc_base * (1 + pred), "return_estimated": pred, "signal": classify(pred),
               "assets": assets, "action": "CIERRE", "engine": "LIVE INDEPENDIENTE · SESIÓN ACTUAL VALIDADA",
               "fx_source": "BCRP" if not fx["provisional"] else "TUCAMBISTA PROVISIONAL",
               "fx_provisional": bool(fx["provisional"]),
               "fx_rule": "BCRP PD04638PD oficial; si aún no existe la fecha, TuCambista provisional.",
               "experimental_assets": experimental,
               "experimental_watchlist": [".INX", "CPER", "EEM", "NDX", "SPBLSCUP", "USD/PEN"],
               "new_ticker_validation": {"signal_date": target.date().isoformat(), "status": "OK", "problems": [],
                                         "rule": "Todos los factores pertenecen a la misma sesión."},
               "session_refresh": {"previous_signal_date": str(old.get("signal_date") or "")[:10],
                                   "corrected_to": target.date().isoformat()}}
    LIVE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"signal_date": payload["signal_date"],
                      "assets": {r["serie"]: [r["precio_actual"], r["retorno"]] for r in assets},
                      "experimental": {r["serie"]: [r["precio_actual"], r["retorno"]] for r in experimental}},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
