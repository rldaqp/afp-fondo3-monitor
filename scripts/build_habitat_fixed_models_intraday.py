from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from fixed_market_quotes import google_html_quote, positive, session_context, yahoo_chart_quote

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "public" / "habitat" / "data" / "fixed_models_2026.json"
OUT = ROOT / "public" / "habitat" / "data" / "fixed_models_intraday.json"
LIMA = ZoneInfo("America/Lima")
NY = ZoneInfo("America/New_York")
FACTORS = ["SPY", "EEM", "MCHI", "QQQ", "SPBLSCUP"]
LIQUID = FACTORS[:-1]
GOOGLE_EXCHANGES = {
    "SPY": "NYSEARCA",
    "EEM": "NYSEARCA",
    "MCHI": "NASDAQ",
    "QQQ": "NASDAQ",
    "SPBLSCUP": "INDEXSP",
}
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept-Language": "en-US,en;q=0.9"}


def short_error(exc) -> str:
    message = re.sub(r"\s+", " ", str(exc)).strip()[:240]
    return f"{type(exc).__name__}: {message}"


def previous_close_map(rows: list[dict], target_date: str) -> dict:
    eligible = sorted(
        (r for r in rows if str(r.get("fecha", ""))[:10] < target_date),
        key=lambda r: r["fecha"],
    )
    if not eligible:
        raise RuntimeError("Hábitat: no existe una sesión anterior en la base fija")
    prior = eligible[-1]
    result = {}
    for name in FACTORS:
        if positive(prior.get(name)):
            result[name] = {"price": float(prior[name]), "date": prior["fecha"]}
    missing = [x for x in FACTORS if x not in result]
    if missing:
        raise RuntimeError(f"Hábitat: cierre previo incompleto: {', '.join(missing)}")
    return result


def quote_record(ticker, price, stamp, confirmed, baseline, now, provider):
    ctx = session_context(now)
    previous = float(baseline["price"])
    if not 0.5 * previous < float(price) < 1.5 * previous:
        raise ValueError(f"{ticker}: precio fuera de rango frente al cierre previo")
    same_date = stamp.date().isoformat() == ctx["date"]
    fresh = same_date and (
        bool(confirmed)
        if not ctx["market_open"]
        else 0 <= (now - stamp).total_seconds() <= 12 * 60
    )
    return {
        "price_previous": previous,
        "price_current": float(price),
        "return": float(price) / previous - 1.0,
        "timestamp": stamp.date().isoformat(),
        "quote_timestamp": stamp.isoformat(),
        "fresh": bool(fresh),
        "close_confirmed": bool(confirmed),
        "previous_close_date": baseline["date"],
        "previous_close_basis": "CIERRE BASE FIJA",
        "source": f"{provider} {ticker} · {'CIERRE REGULAR CONFIRMADO' if confirmed else 'SNAPSHOT NO CONSOLIDADO'}",
    }


def yahoo_snapshot(ticker, now, baseline):
    response = requests.get(
        f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}",
        params={"interval": "5m", "range": "5d", "includePrePost": "false"},
        headers=HEADERS,
        timeout=20,
    )
    response.raise_for_status()
    price, stamp, confirmed = yahoo_chart_quote(response.json(), ticker, now)
    return quote_record(ticker, price, stamp, confirmed, baseline, now, "YAHOO")


def google_snapshot(ticker, now, baseline):
    exchange = GOOGLE_EXCHANGES[ticker]
    response = requests.get(
        f"https://www.google.com/finance/quote/{ticker}:{exchange}?hl=en&gl=us",
        headers=HEADERS,
        timeout=20,
    )
    response.raise_for_status()
    price, stamp, confirmed = google_html_quote(response.text, ticker, exchange, now)
    return quote_record(ticker, price, stamp, confirmed, baseline, now, "GOOGLE FINANCE")


def main() -> None:
    if not BASE.exists():
        raise RuntimeError(f"Falta la base fija de Hábitat: {BASE}")
    base = json.loads(BASE.read_text(encoding="utf-8"))
    previous_snapshot = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    previous_by_ticker = {r.get("ticker"): r for r in previous_snapshot.get("tickers", [])}

    now = datetime.now(NY)
    ctx = session_context(now)
    target = ctx["date"]
    rows = sorted(base.get("rows", []), key=lambda r: r.get("fecha", ""))
    baselines = previous_close_map(rows, target)

    fmap = {}
    problems = []
    for ticker in FACTORS:
        failures = []
        providers = [yahoo_snapshot, google_snapshot] if ticker in LIQUID else [google_snapshot]
        for provider in providers:
            try:
                quote = provider(ticker, now, baselines[ticker])
                if ticker not in fmap or quote["fresh"]:
                    fmap[ticker] = quote
                if quote["fresh"]:
                    break
            except Exception as exc:
                failures.append(f"{ticker} {provider.__name__}: {short_error(exc)}")

        if ticker not in fmap or not fmap[ticker]["fresh"]:
            old = previous_by_ticker.get(ticker, {})
            if (
                not ctx["market_open"]
                and old.get("close_confirmed") is True
                and str(old.get("timestamp", ""))[:10] == target
                and positive(old.get("price_current"))
            ):
                fmap[ticker] = {
                    **old,
                    "source": "CACHE DE CIERRE VERIFICADO · MISMA FECHA",
                }
            elif ticker not in fmap:
                prior = baselines[ticker]
                fmap[ticker] = {
                    "price_previous": prior["price"],
                    "price_current": prior["price"],
                    "return": 0.0,
                    "timestamp": prior["date"],
                    "quote_timestamp": None,
                    "fresh": False,
                    "close_confirmed": False,
                    "previous_close_date": prior["date"],
                    "previous_close_basis": "CIERRE BASE FIJA",
                    "source": "CIERRE PREVIO · FALLBACK NO ACTUAL",
                }
            problems.extend(failures)
            problems.append(
                f"{ticker}: falta dato propio de {target}; no se reutiliza como si fuera actual el dato de {fmap[ticker]['timestamp']}"
            )

    prior_rows = [r for r in rows if str(r.get("fecha", ""))[:10] < target]
    prior = prior_rows[-1]
    if positive(prior.get("vc_sbs")):
        return_base = float(prior["vc_sbs"])
        base_rule = "VC SBS real de la sesión anterior"
    elif positive(prior.get("vc_retornos")):
        return_base = float(prior["vc_retornos"])
        base_rule = "VC estimado por retornos de la sesión anterior"
    else:
        raise RuntimeError("Hábitat: no existe VC base consecutivo para el modelo de retornos")

    level_coeff = base["models"]["niveles"]["coefficients"]
    return_coeff = base["models"]["retornos"]["coefficients"]
    level_contrib = {x: float(level_coeff[x]) * float(fmap[x]["price_current"]) for x in FACTORS}
    return_contrib = {x: float(return_coeff[x]) * float(fmap[x]["return"]) for x in FACTORS}
    vc_levels = float(level_coeff["intercept"]) + sum(level_contrib.values())
    ret_est = float(return_coeff["intercept"]) + sum(return_contrib.values())
    vc_returns = return_base * (1.0 + ret_est)
    level_den = sum(abs(v) for v in level_contrib.values())
    return_den = sum(abs(v) for v in return_contrib.values())

    tickers = []
    for ticker in FACTORS:
        q = fmap[ticker]
        tickers.append({
            "ticker": ticker,
            **q,
            "level_coefficient": float(level_coeff[ticker]),
            "return_coefficient": float(return_coeff[ticker]),
            "level_contribution": float(level_contrib[ticker]),
            "return_contribution": float(return_contrib[ticker]),
            "level_weight_abs_pct": abs(level_contrib[ticker]) / level_den * 100.0 if level_den else None,
            "return_weight_abs_pct": abs(return_contrib[ticker]) / return_den * 100.0 if return_den else None,
        })

    fresh = sum(1 for row in tickers if row["fresh"])
    consolidated = (
        not ctx["market_open"]
        and fresh == len(FACTORS)
        and all(row["close_confirmed"] for row in tickers)
        and all(str(row["timestamp"])[:10] == target for row in tickers)
    )

    payload = {
        "fund": "HÁBITAT Fondo 3",
        "generated_at_lima": now.astimezone(LIMA).isoformat(),
        "generated_at_ny": now.isoformat(),
        "signal_date": target,
        "market_open": ctx["market_open"],
        "session_open_ny": ctx["open"].isoformat(),
        "session_close_ny": ctx["close"].isoformat(),
        "next_session_open_ny": ctx["next_open"].isoformat(),
        "next_session_close_ny": ctx["next_close"].isoformat(),
        "mode": ("INTRADÍA" if fresh == 5 else "INTRADÍA PARCIAL") if ctx["market_open"] else "CIERRE / ÚLTIMO SNAPSHOT",
        "close_consolidated": consolidated,
        "fresh_factors": fresh,
        "total_factors": len(FACTORS),
        "problems": problems,
        "latest_sbs_date": base["latest"]["latest_sbs_date"],
        "latest_sbs_vc": base["latest"]["latest_sbs_vc"],
        "previous_close_rule": "Cierre regular validado de la sesión anterior; un dato antiguo nunca se reasigna a la fecha corriente.",
        "models": {
            "niveles": {
                "vc_intraday": vc_levels,
                "equation": base["models"]["niveles"]["equation"],
            },
            "retornos": {
                "return_intraday": ret_est,
                "vc_intraday": vc_returns,
                "base_vc": return_base,
                "base_date": prior["fecha"],
                "base_rule": base_rule,
                "equation": base["models"]["retornos"]["equation"],
            },
        },
        "tickers": tickers,
        "weight_note": "Peso relativo del aporte absoluto al cálculo; no representa tenencia de cartera.",
    }

    if len({row["ticker"] for row in tickers}) != len(FACTORS):
        raise RuntimeError("Hábitat: snapshot con factores duplicados")
    for row in tickers:
        if row["fresh"] and str(row["timestamp"])[:10] != target:
            raise RuntimeError(f"Hábitat: {row['ticker']} marcado fresh con fecha ajena")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "signal_date": target,
        "mode": payload["mode"],
        "fresh_factors": fresh,
        "close_consolidated": consolidated,
        "vc_niveles": vc_levels,
        "vc_retornos": vc_returns,
        "problems": problems,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
