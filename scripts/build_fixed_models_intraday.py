from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from fixed_market_quotes import google_html_quote, positive, session_context, yahoo_chart_quote
from fixed_model_contract import history_revision, validate_snapshot

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "public" / "data" / "fixed_models_2026.json"
OUT = ROOT / "public" / "data" / "fixed_models_intraday.json"
LIMA = ZoneInfo("America/Lima")
NY = ZoneInfo("America/New_York")
FACTORS = ["SPY", "EEM", "MCHI", "QQQ", "SPBLSCUP"]
LIQUID = FACTORS[:-1]
GOOGLE_EXCHANGES = {"SPY": "NYSEARCA", "EEM": "NYSEARCA", "MCHI": "NASDAQ", "QQQ": "NASDAQ", "SPBLSCUP": "INDEXSP"}
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept-Language": "en-US,en;q=0.9"}


def short_error(exc):
    message = re.sub(r'\s+', ' ', str(exc)).strip()[:240]
    return f"{type(exc).__name__}: {message}"


def validated_previous_close_map(rows, target_date):
    eligible = sorted((r for r in rows if r["fecha"] < target_date), key=lambda r: r["fecha"])
    if not eligible:
        raise ValueError("No existe la sesión anterior en la base fija")
    prior = eligible[-1]
    return {f: {"price": float(prior[f]), "date": prior["fecha"]} for f in FACTORS if positive(prior.get(f))}


def quote_record(ticker, price, stamp, confirmed, baseline, now, provider):
    ctx = session_context(now)
    if not baseline or not positive(baseline.get("price")):
        raise ValueError(f"{ticker}: sin cierre previo validado")
    previous = float(baseline["price"])
    if not 0.5 * previous < price < 1.5 * previous:
        raise ValueError(f"{ticker}: precio fuera de rango frente al cierre previo")
    same_date = stamp.date().isoformat() == ctx["date"]
    current = same_date and (confirmed if not ctx["market_open"] else 0 <= (now-stamp).total_seconds() <= 12*60)
    return {
        "precio_anterior": previous, "precio_actual": price, "retorno": price / previous - 1,
        "timestamp": stamp.date().isoformat(), "quote_timestamp": stamp.isoformat(),
        "fresh": current, "close_confirmed": confirmed,
        "previous_close_date": baseline["date"], "previous_close_basis": "CIERRE BASE FIJA",
        "provider_previous_close": None,
        "source": f"{provider} {ticker} · {'CIERRE REGULAR CONFIRMADO' if confirmed else 'SNAPSHOT NO CONSOLIDADO'} + CIERRE BASE FIJA",
    }


def liquid_snapshot(ticker, now_ny, baseline=None):
    response = requests.get(
        f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}",
        params={"interval": "5m", "range": "5d", "includePrePost": "false"},
        headers=HEADERS, timeout=20,
    )
    response.raise_for_status()
    price, stamp, confirmed = yahoo_chart_quote(response.json(), ticker, now_ny)
    return quote_record(ticker, price, stamp, confirmed, baseline, now_ny, "YAHOO")


def google_finance_snapshot(ticker, now_ny, baseline=None):
    exchange = GOOGLE_EXCHANGES[ticker]
    response = requests.get(
        f"https://www.google.com/finance/quote/{ticker}:{exchange}?hl=en&gl=us",
        headers=HEADERS, timeout=20,
    )
    response.raise_for_status()
    price, stamp, confirmed = google_html_quote(response.text, ticker, exchange, now_ny)
    return quote_record(ticker, price, stamp, confirmed, baseline, now_ny, "GOOGLE FINANCE")


def build_snapshot(base, now, previous_snapshot=None):
    ctx = session_context(now)
    target = ctx["date"]
    rows = sorted(base["rows"], key=lambda r: r["fecha"])
    baseline = validated_previous_close_map(rows, target)
    fmap, problems = {}, []
    previous_map = {t["ticker"]: t for t in (previous_snapshot or {}).get("tickers", [])}
    for ticker in FACTORS:
        failures = []
        providers = [liquid_snapshot, google_finance_snapshot] if ticker in LIQUID else [google_finance_snapshot]
        for provider in providers:
            try:
                quote = provider(ticker, now, baseline.get(ticker))
                if ticker not in fmap or quote["fresh"]:
                    fmap[ticker] = quote
                if quote["fresh"]:
                    break
            except Exception as exc:
                failures.append(f"{ticker} {getattr(provider, '__name__', 'fuente')}: {short_error(exc)}")
        if ticker not in fmap or not fmap[ticker]["fresh"]:
            old = previous_map.get(ticker, {})
            # Retain a verifiably closed snapshot across temporary provider outages.
            if old.get("close_confirmed") and old.get("timestamp") == target and not ctx["market_open"]:
                stamp = datetime.fromisoformat(old["quote_timestamp"])
                fmap[ticker] = quote_record(ticker, float(old["price_current"]), stamp, True,
                                           baseline[ticker], now, "CACHE CIERRE VERIFICADO")
            elif ticker not in fmap:
                prior = baseline[ticker]
                fmap[ticker] = {
                    "precio_anterior": prior["price"], "precio_actual": prior["price"], "retorno": 0.0,
                    "timestamp": prior["date"], "quote_timestamp": None, "fresh": False, "close_confirmed": False,
                    "previous_close_date": prior["date"], "previous_close_basis": "CIERRE BASE FIJA",
                    "provider_previous_close": None, "source": "CIERRE PREVIO · FALLBACK NO ACTUAL",
                }
        if not fmap[ticker]["fresh"]:
            problems.extend(failures)
            problems.append(f"{ticker}: falta {'cotización actual' if ctx['market_open'] else 'cierre confirmado'} de {target}; dato {fmap[ticker]['timestamp']}")

    prior = [r for r in rows if r["fecha"] < target][-1]
    if positive(prior.get("vc_sbs")):
        ret_base, rule = float(prior["vc_sbs"]), "VC SBS real de la sesión anterior"
    elif positive(prior.get("vc_retornos")):
        ret_base, rule = float(prior["vc_retornos"]), "VC estimado por retornos de la sesión anterior"
    else:
        raise ValueError("No existe VC base de la sesión anterior; no se permite saltar fechas")
    lc, rc = (base["models"][k]["coefficients"] for k in ("niveles", "retornos"))
    level_contrib = {f: float(lc[f])*fmap[f]["precio_actual"] for f in FACTORS}
    return_contrib = {f: float(rc[f])*fmap[f]["retorno"] for f in FACTORS}
    vc_levels = float(lc["intercept"]) + sum(level_contrib.values())
    ret_est = float(rc["intercept"]) + sum(return_contrib.values())
    den_l, den_r = sum(map(abs, level_contrib.values())), sum(map(abs, return_contrib.values()))
    tickers = []
    for f in FACTORS:
        q = fmap[f]
        tickers.append({
            "ticker": f, "timestamp": q["timestamp"], "quote_timestamp": q["quote_timestamp"],
            "fresh": q["fresh"], "close_confirmed": q["close_confirmed"],
            "price_previous": q["precio_anterior"], "price_current": q["precio_actual"], "return": q["retorno"],
            "previous_close_date": q["previous_close_date"], "previous_close_basis": q["previous_close_basis"],
            "provider_previous_close": q["provider_previous_close"],
            "level_coefficient": float(lc[f]), "return_coefficient": float(rc[f]),
            "level_contribution": level_contrib[f], "return_contribution": return_contrib[f],
            "level_weight_abs_pct": abs(level_contrib[f])/den_l*100 if den_l else None,
            "return_weight_abs_pct": abs(return_contrib[f])/den_r*100 if den_r else None,
            "source": q["source"],
        })
    fresh = sum(t["fresh"] for t in tickers)
    payload = {
        "generated_at_lima": now.astimezone(LIMA).isoformat(), "generated_at_ny": now.isoformat(),
        "signal_date": target, "market_open": ctx["market_open"], "session_open_ny": ctx["open"].isoformat(),
        "session_close_ny": ctx["close"].isoformat(),
        "next_session_open_ny": ctx["next_open"].isoformat(), "next_session_close_ny": ctx["next_close"].isoformat(),
        "mode": ("INTRADÍA" if fresh == 5 else "INTRADÍA PARCIAL") if ctx["market_open"] else "CIERRE / ÚLTIMO SNAPSHOT",
        "close_consolidated": not ctx["market_open"] and fresh == 5 and all(t["close_confirmed"] for t in tickers),
        "fresh_factors": fresh, "total_factors": 5, "problems": problems,
        "base_revision": history_revision(base),
        "latest_sbs_date": base["latest"]["latest_sbs_date"], "latest_sbs_vc": base["latest"]["latest_sbs_vc"],
        "previous_close_rule": "Cierre regular validado de la sesión anterior; sin reutilizar otra fecha.",
        "models": {
            "niveles": {"vc_intraday": vc_levels, "equation": base["models"]["niveles"]["equation"]},
            "retornos": {"return_intraday": ret_est, "vc_intraday": ret_base*(1+ret_est), "base_vc": ret_base,
                         "base_date": prior["fecha"], "base_rule": rule, "equation": base["models"]["retornos"]["equation"]},
        },
        "tickers": tickers,
        "weight_note": "Peso relativo del aporte absoluto; no representa tenencia de cartera.",
        "source_live": "Cierre regular Yahoo con hora propia; Google Finance con precio y fecha del instrumento principal.",
    }
    validate_snapshot(base, payload)
    return payload


def main():
    base = json.loads(BASE.read_text(encoding="utf-8"))
    previous = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else None
    payload = build_snapshot(base, datetime.now(NY), previous)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: payload[k] for k in ("signal_date", "mode", "fresh_factors", "close_consolidated", "problems")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
