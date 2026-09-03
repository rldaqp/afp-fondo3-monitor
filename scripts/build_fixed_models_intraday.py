from __future__ import annotations

import json
import re
from datetime import datetime, time as clock_time
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "public" / "data" / "fixed_models_2026.json"
LIVE = ROOT / "public" / "data" / "live_market.json"
OUT = ROOT / "public" / "data" / "fixed_models_intraday.json"
LIMA = ZoneInfo("America/Lima")
NY = ZoneInfo("America/New_York")

FACTORS = ["SPY", "EEM", "MCHI", "QQQ", "SPBLSCUP"]
LIQUID = ["SPY", "EEM", "MCHI", "QQQ"]
GOOGLE_EXCHANGES = {
    "SPY": "NYSEARCA",
    "EEM": "NYSEARCA",
    "MCHI": "NASDAQ",
    "QQQ": "NASDAQ",
    "SPBLSCUP": "INDEXSP",
}


def finite(v):
    try:
        return v is not None and np.isfinite(float(v))
    except Exception:
        return False


def market_is_open(now_ny: datetime) -> bool:
    return now_ny.weekday() < 5 and clock_time(9, 30) <= now_ny.time() < clock_time(16, 5)


def short_error(exc: Exception) -> str:
    """Keep provider diagnostics useful without publishing driver stack traces."""
    message = re.sub(r"\s+", " ", str(exc)).strip()
    return f"{type(exc).__name__}: {message[:240]}"


def validated_previous_close_map(rows, target_date: str):
    """Latest validated regular-session close in the fixed history before target_date.

    This is the single return baseline used by the visor. It prevents tiny differences
    between vendor-specific `previous_close` fields from flipping the sign of a ticker.
    """
    eligible = [r for r in rows if str(r.get("fecha") or "")[:10] < target_date]
    out = {}
    for ticker in FACTORS:
        for row in reversed(eligible):
            if finite(row.get(ticker)) and float(row[ticker]) > 0:
                out[ticker] = {
                    "price": float(row[ticker]),
                    "date": str(row.get("fecha") or "")[:10],
                }
                break
    return out


def liquid_snapshot(ticker: str, now_ny: datetime, baseline=None):
    """Current/last Yahoo quote against the monitor's validated previous close."""
    baseline_price = float(baseline["price"]) if baseline and finite(baseline.get("price")) else None
    baseline_date = str(baseline.get("date") or "")[:10] if baseline else None

    provider_prev = None
    # fast_info no expone la hora del último negocio y puede devolver T-1. Se
    # exige una serie 5m porque su índice permite probar a qué sesión pertenece
    # la cotización tanto durante la rueda como al cierre.

    raw = yf.download(
        ticker,
        period="5d",
        interval="5m",
        auto_adjust=False,
        actions=False,
        progress=False,
        threads=False,
        prepost=False,
    )
    if raw.empty:
        raise RuntimeError(f"Yahoo no devolvió {ticker} intradía")
    if isinstance(raw.columns, pd.MultiIndex):
        if ("Close", ticker) in raw.columns:
            s = pd.to_numeric(raw[("Close", ticker)], errors="coerce").dropna()
        elif "Close" in raw.columns.get_level_values(0):
            s = pd.to_numeric(raw.xs("Close", axis=1, level=0).iloc[:, 0], errors="coerce").dropna()
        else:
            raise RuntimeError(f"{ticker} sin columna Close")
    else:
        s = pd.to_numeric(raw["Close"], errors="coerce").dropna()
    if s.empty:
        raise RuntimeError(f"{ticker} intradía vacío")
    cur = float(s.iloc[-1])
    quote_stamp = pd.Timestamp(s.index[-1])
    if quote_stamp.tzinfo is None:
        quote_stamp = quote_stamp.tz_localize(NY)
    else:
        quote_stamp = quote_stamp.tz_convert(NY)
    quote_date = quote_stamp.date().isoformat()
    fresh = quote_date == now_ny.date().isoformat()

    if finite(baseline_price) and baseline_price > 0:
        prev = baseline_price
        basis = "CIERRE BASE FIJA"
    else:
        daily = yf.download(
            ticker,
            period="10d",
            interval="1d",
            auto_adjust=False,
            actions=False,
            progress=False,
            threads=False,
        )
        if daily.empty:
            raise RuntimeError(f"{ticker} diario vacío")
        if isinstance(daily.columns, pd.MultiIndex):
            if ("Close", ticker) in daily.columns:
                d = pd.to_numeric(daily[("Close", ticker)], errors="coerce").dropna()
            else:
                d = pd.to_numeric(daily.xs("Close", axis=1, level=0).iloc[:, 0], errors="coerce").dropna()
        else:
            d = pd.to_numeric(daily["Close"], errors="coerce").dropna()
        dates = pd.to_datetime(d.index)
        if getattr(dates, "tz", None) is not None:
            dates = dates.tz_localize(None)
        if len(d) >= 2 and dates[-1].date() == now_ny.date():
            prev = float(d.iloc[-2])
        else:
            prev = float(d.iloc[-1])
        provider_prev = prev
        basis = "PREV. YAHOO 1D"

    return {
        "precio_anterior": float(prev),
        "precio_actual": cur,
        "retorno": cur / float(prev) - 1.0,
        "source": f"YAHOO {ticker} · 5M {'ACTUAL' if fresh else 'ÚLTIMO DISPONIBLE'} + {basis}",
        "timestamp": quote_date,
        "fresh": fresh,
        "previous_close_date": baseline_date,
        "previous_close_basis": basis,
        "provider_previous_close": provider_prev,
    }


def google_finance_snapshot(ticker: str, now_ny: datetime, baseline=None):
    """Timestamped HTTP fallback for all fixed-model factors."""
    exchange = GOOGLE_EXCHANGES[ticker]
    url = f"https://www.google.com/finance/quote/{ticker}:{exchange}?hl=en&gl=us"
    response = requests.get(
        url,
        timeout=12,
        headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    response.raise_for_status()
    text = response.text
    price_match = re.search(r'data-last-price="([+-]?[0-9.,]+)"', text)
    stamp_match = re.search(r'data-last-normal-market-timestamp="([0-9]+)"', text)
    if not price_match:
        raise RuntimeError(f"Google Finance no devolvió precio para {ticker}")

    price = float(price_match.group(1).replace(",", ""))
    baseline_price = float(baseline["price"]) if baseline and finite(baseline.get("price")) else None
    baseline_date = str(baseline.get("date") or "")[:10] if baseline else None
    if not finite(baseline_price) or baseline_price <= 0:
        raise RuntimeError(f"{ticker} sin cierre fijo previo")
    # Evita aceptar por error el precio de otro instrumento embebido en la página.
    if not (0.5 * baseline_price < price < 1.5 * baseline_price):
        raise RuntimeError(f"{ticker} fuera de rango frente al cierre fijo")

    stamp = None
    if stamp_match:
        sec = int(stamp_match.group(1))
        if sec > 10_000_000_000:
            sec //= 1000
        stamp = datetime.fromtimestamp(sec, tz=NY)
    quote_date = stamp.date().isoformat() if stamp else (baseline_date or "")
    fresh = stamp is not None and stamp.date() == now_ny.date()
    return {
        "precio_anterior": baseline_price,
        "precio_actual": price,
        "retorno": price / baseline_price - 1.0,
        "source": (
            f"GOOGLE FINANCE {ticker} · {'QUOTE ACTUAL' if fresh else 'ÚLTIMO QUOTE'}"
            " + CIERRE BASE FIJA"
        ),
        "timestamp": quote_date,
        "fresh": fresh,
        "previous_close_date": baseline_date,
        "previous_close_basis": "CIERRE BASE FIJA",
        "provider_previous_close": None,
    }


def spblscup_google(now_ny: datetime, baseline=None):
    """Read Google Finance current quote; use fixed-history close as return baseline."""
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait

    baseline_price = float(baseline["price"]) if baseline and finite(baseline.get("price")) else None
    baseline_date = str(baseline.get("date") or "")[:10] if baseline else None

    opts = webdriver.ChromeOptions()
    for arg in (
        "--headless=new",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-gpu",
        "--window-size=1920,1080",
        "--lang=en-US",
    ):
        opts.add_argument(arg)
    driver = webdriver.Chrome(options=opts)
    try:
        driver.get("https://www.google.com/finance/quote/SPBLSCUP:INDEXSP?hl=en&gl=us")
        WebDriverWait(driver, 25).until(lambda d: d.find_element(By.TAG_NAME, "body"))
        body = re.sub(r"\s+", " ", driver.find_element(By.TAG_NAME, "body").text)

        price = None
        stamp = None
        for el in driver.find_elements(By.CSS_SELECTOR, "[data-last-price]"):
            try:
                value = float(str(el.get_attribute("data-last-price")).replace(",", ""))
            except Exception:
                continue
            if 100 < value < 1000:
                price = value
                raw_stamp = el.get_attribute("data-last-normal-market-timestamp")
                if raw_stamp:
                    try:
                        sec = int(raw_stamp)
                        if sec > 10_000_000_000:
                            sec //= 1000
                        stamp = datetime.fromtimestamp(sec, tz=NY)
                    except Exception:
                        pass
                break

        if price is None:
            m = re.search(
                r"S&P(?:/BVL)?\s+Peru\s+Select\s+20%\s+Capped\s+Index\s*\(USD\)\s+([\d,]+(?:\.\d+)?)",
                body,
                re.I,
            )
            if m:
                price = float(m.group(1).replace(",", ""))
        if price is None:
            raise RuntimeError("SPBLSCUP sin precio principal")

        provider_previous = None
        pm = re.search(r"Prev(?:ious)?\.?\s*close\s+\$?([\d,]+(?:\.\d+)?)", body, re.I)
        if pm:
            provider_previous = float(pm.group(1).replace(",", ""))

        previous = baseline_price if finite(baseline_price) and baseline_price > 0 else provider_previous
        if not finite(previous) or previous <= 0:
            raise RuntimeError("SPBLSCUP sin cierre previo válido")
        basis = "CIERRE BASE FIJA" if baseline_price is not None else "PREV. GOOGLE"

        if stamp is None:
            for el in driver.find_elements(By.CSS_SELECTOR, "[data-last-normal-market-timestamp]"):
                raw = el.get_attribute("data-last-normal-market-timestamp")
                if not raw:
                    continue
                try:
                    sec = int(raw)
                    if sec > 10_000_000_000:
                        sec //= 1000
                    stamp = datetime.fromtimestamp(sec, tz=NY)
                    break
                except Exception:
                    pass

        # Sin timestamp verificable no se presenta SPBLSCUP como cotización de
        # la rueda actual. Se conserva como respaldo visible, marcado no fresco.
        stamp_date = stamp.date().isoformat() if stamp else (baseline_date or now_ny.date().isoformat())
        fresh = stamp is not None and stamp.date() == now_ny.date()
        return {
            "precio_anterior": float(previous),
            "precio_actual": float(price),
            "retorno": float(price / float(previous) - 1.0),
            "source": ("GOOGLE FINANCE SPBLSCUP · QUOTE ACTUAL" if fresh else "GOOGLE FINANCE SPBLSCUP · ÚLTIMO QUOTE") + f" + {basis}",
            "timestamp": stamp_date,
            "fresh": fresh,
            "previous_close_date": baseline_date,
            "previous_close_basis": basis,
            "provider_previous_close": provider_previous,
        }
    finally:
        driver.quit()


def old_live_factor_map(live):
    rows = list(live.get("assets", [])) + list(live.get("experimental_assets", []))
    out = {}
    for row in rows:
        name = str(row.get("serie") or "")
        if name not in set(FACTORS):
            continue
        if not (finite(row.get("precio_actual")) and finite(row.get("precio_anterior"))):
            continue
        cur = float(row["precio_actual"])
        prev = float(row["precio_anterior"])
        ret = float(row.get("retorno")) if finite(row.get("retorno")) else cur / prev - 1.0
        out[name] = {
            "precio_anterior": prev,
            "precio_actual": cur,
            "retorno": ret,
            "source": str(row.get("estado") or row.get("ticker") or "LIVE") + " · FALLBACK",
            "timestamp": str(row.get("timestamp") or live.get("signal_date") or "")[:10],
            "fresh": False,
            "previous_close_date": None,
            "previous_close_basis": "FALLBACK LIVE",
            "provider_previous_close": prev,
        }
    return out


def main():
    if not BASE.exists():
        raise RuntimeError(f"Falta {BASE}")
    base = json.loads(BASE.read_text(encoding="utf-8"))
    old_live = json.loads(LIVE.read_text(encoding="utf-8")) if LIVE.exists() else {}
    old_map = old_live_factor_map(old_live)
    now_ny = datetime.now(NY)
    now_lima = datetime.now(LIMA)
    open_now = market_is_open(now_ny)

    rows = base.get("rows") or []
    if not rows:
        raise RuntimeError("fixed_models_2026.json sin filas")
    target_date = now_ny.date().isoformat()
    baseline_map = validated_previous_close_map(rows, target_date)

    fmap = {}
    problems = []
    for ticker in LIQUID:
        try:
            fmap[ticker] = liquid_snapshot(ticker, now_ny, baseline_map.get(ticker))
        except Exception as exc:
            problems.append(f"{ticker} Yahoo: {short_error(exc)}")
            try:
                fmap[ticker] = google_finance_snapshot(ticker, now_ny, baseline_map.get(ticker))
            except Exception as google_exc:
                problems.append(f"{ticker} Google: {short_error(google_exc)}")
                if ticker in old_map:
                    fmap[ticker] = old_map[ticker]

    try:
        fmap["SPBLSCUP"] = google_finance_snapshot(
            "SPBLSCUP", now_ny, baseline_map.get("SPBLSCUP")
        )
    except Exception as exc:
        problems.append(f"SPBLSCUP Google HTTP: {short_error(exc)}")
        try:
            fmap["SPBLSCUP"] = spblscup_google(now_ny, baseline_map.get("SPBLSCUP"))
        except Exception as browser_exc:
            problems.append(f"SPBLSCUP Google navegador: {short_error(browser_exc)}")
            if "SPBLSCUP" in old_map:
                fmap["SPBLSCUP"] = old_map["SPBLSCUP"]

    last = rows[-1]
    prev_row = rows[-2] if len(rows) >= 2 else {}
    for f in FACTORS:
        if f in fmap:
            continue
        if finite(last.get(f)):
            base_item = baseline_map.get(f)
            p = float(base_item["price"]) if base_item and finite(base_item.get("price")) else (float(prev_row.get(f)) if finite(prev_row.get(f)) else float(last[f]))
            c = float(last[f])
            fmap[f] = {
                "precio_anterior": p,
                "precio_actual": c,
                "retorno": (c / p - 1.0) if p else 0.0,
                "source": "ÚLTIMO CIERRE FIJO · FALLBACK",
                "timestamp": str(last.get("fecha") or "")[:10],
                "fresh": False,
                "previous_close_date": str(base_item.get("date") or "")[:10] if base_item else None,
                "previous_close_basis": "CIERRE BASE FIJA",
                "provider_previous_close": None,
            }

    missing = [f for f in FACTORS if f not in fmap]
    if missing:
        raise RuntimeError("Faltan factores: " + ", ".join(missing))

    # Una fuente puede responder correctamente pero seguir entregando la rueda
    # anterior. No se descarta el snapshot completo: se publica como parcial y
    # se deja la incidencia explícita para que el visor nunca confunda T-1 con T.
    if open_now:
        for f in FACTORS:
            quote_date = str(fmap[f].get("timestamp") or "")[:10]
            if not (bool(fmap[f].get("fresh")) and quote_date == target_date):
                problems.append(
                    f"{f}: sin cotización verificable de {target_date}; "
                    f"último dato {quote_date or 'sin fecha'}"
                )

    lc = base["models"]["niveles"]["coefficients"]
    rc = base["models"]["retornos"]["coefficients"]
    vc_levels = float(lc["intercept"])
    ret_est = float(rc["intercept"])
    level_contrib = {}
    return_contrib = {}
    for f in FACTORS:
        price = float(fmap[f]["precio_actual"])
        ret = float(fmap[f]["retorno"])
        level_contrib[f] = float(lc[f]) * price
        return_contrib[f] = float(rc[f]) * ret
        vc_levels += level_contrib[f]
        ret_est += return_contrib[f]

    fresh_dates = [str(fmap[f].get("timestamp") or "")[:10] for f in FACTORS if fmap[f].get("fresh")]
    if open_now:
        signal_date = target_date
    elif fresh_dates:
        signal_date = max(fresh_dates)
    else:
        signal_date = str(last.get("fecha") or old_live.get("signal_date") or "")[:10]

    earlier = [r for r in rows if str(r.get("fecha") or "")[:10] < signal_date]
    prior = earlier[-1] if earlier else last
    if finite(prior.get("vc_sbs")):
        ret_base = float(prior["vc_sbs"])
        ret_base_kind = "VC SBS real de la sesión anterior"
    elif finite(prior.get("vc_retornos")):
        ret_base = float(prior["vc_retornos"])
        ret_base_kind = "VC estimado por retornos de la sesión anterior"
    else:
        ret_base = float(base["latest"]["latest_sbs_vc"])
        ret_base_kind = "Último VC SBS disponible"
    vc_returns = ret_base * (1.0 + ret_est)

    den_l = sum(abs(v) for v in level_contrib.values())
    den_r = sum(abs(v) for v in return_contrib.values())
    tickers = []
    for f in FACTORS:
        x = fmap[f]
        tickers.append(
            {
                "ticker": f,
                "timestamp": x["timestamp"],
                "fresh": bool(x.get("fresh")),
                "price_previous": x["precio_anterior"],
                "price_current": x["precio_actual"],
                "return": x["retorno"],
                "previous_close_date": x.get("previous_close_date"),
                "previous_close_basis": x.get("previous_close_basis"),
                "provider_previous_close": x.get("provider_previous_close"),
                "level_coefficient": float(lc[f]),
                "return_coefficient": float(rc[f]),
                "level_contribution": level_contrib[f],
                "return_contribution": return_contrib[f],
                "level_weight_abs_pct": (abs(level_contrib[f]) / den_l * 100.0) if den_l else None,
                "return_weight_abs_pct": (abs(return_contrib[f]) / den_r * 100.0) if den_r else None,
                "source": x["source"],
            }
        )

    fresh_count = sum(bool(x.get("fresh")) and str(x.get("timestamp") or "")[:10] == signal_date for x in fmap.values())
    if open_now and fresh_count == len(FACTORS):
        mode = "INTRADÍA"
    elif open_now:
        mode = "INTRADÍA PARCIAL"
    else:
        mode = "CIERRE / ÚLTIMO SNAPSHOT"

    payload = {
        "generated_at_lima": now_lima.isoformat(),
        "generated_at_ny": now_ny.isoformat(),
        "signal_date": signal_date,
        "mode": mode,
        "market_open": open_now,
        "fresh_factors": fresh_count,
        "total_factors": len(FACTORS),
        "problems": problems,
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
                "base_rule": ret_base_kind,
                "equation": base["models"]["retornos"]["equation"],
            },
        },
        "tickers": tickers,
        "weight_note": "Peso relativo = participación del valor absoluto del aporte actual de cada factor; no representa tenencia de cartera.",
        "source_live": "Precio actual: Yahoo Finance 5m con Google Finance como respaldo; toda cotización exige fecha verificable. Retorno: contra cierre regular validado de la base fija.",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "signal_date": signal_date,
                "mode": mode,
                "market_open": open_now,
                "fresh_factors": fresh_count,
                "total_factors": len(FACTORS),
                "previous_close_rule": payload["previous_close_rule"],
                "problems": problems,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
