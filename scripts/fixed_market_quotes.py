"""Dated regular-session quotes; never infer a quote date from a fallback price."""
from __future__ import annotations

import math
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
from bs4 import BeautifulSoup

NY = ZoneInfo("America/New_York")


def session_context(now):
    now = now.astimezone(NY)
    cal = xcals.get_calendar("XNYS")
    session = cal.date_to_session(now.date().isoformat(), direction="previous")
    if now < cal.session_open(session):
        session = cal.previous_session(session)
    opening = cal.session_open(session).to_pydatetime().astimezone(NY)
    closing = cal.session_close(session).to_pydatetime().astimezone(NY)
    following = cal.next_session(session)
    return {"date": session.date().isoformat(), "open": opening, "close": closing,
            "next_open": cal.session_open(following).to_pydatetime().astimezone(NY),
            "next_close": cal.session_close(following).to_pydatetime().astimezone(NY),
            "market_open": opening <= now < closing}


def positive(value):
    return value is not None and math.isfinite(float(value)) and float(value) > 0


def yahoo_chart_quote(payload, ticker, now):
    """Keep Yahoo's 16:00 closing print, which yfinance's 5m cleanup can remove."""
    result = (payload.get("chart", {}).get("result") or [None])[0]
    if not result or result.get("meta", {}).get("symbol") != ticker:
        raise ValueError(f"Yahoo: instrumento inesperado para {ticker}")
    ctx = session_context(now)
    meta = result["meta"]
    quotes = (result.get("indicators", {}).get("quote") or [{}])[0].get("close", [])
    bars = []
    for ts, value in zip(result.get("timestamp", []), quotes):
        stamp = datetime.fromtimestamp(ts, tz=NY)
        if positive(value) and ctx["open"] <= stamp <= min(now, ctx["close"]):
            bars.append((stamp, float(value)))
    regular_time = meta.get("regularMarketTime")
    if regular_time and positive(meta.get("regularMarketPrice")):
        stamp = datetime.fromtimestamp(regular_time, tz=NY)
        # regularMarketPrice is not the post-market quote. Require its own time.
        if ctx["close"] <= stamp <= min(now, ctx["close"] + timedelta(minutes=10)):
            return float(meta["regularMarketPrice"]), stamp, True
    if not bars:
        raise ValueError(f"Yahoo: {ticker} sin cotización de {ctx['date']}")
    stamp, price = max(bars)
    return price, stamp, now >= ctx["close"] and stamp == ctx["close"]


def visible_google_stamp(text, now):
    match = re.search(
        r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2}),?\s+"
        r"(?:(\d{4}),?\s+)?(\d{1,2}):(\d{2})(?::(\d{2}))?\s*(AM|PM)\s+"
        r"GMT\s*([+−-]\d{1,2})(?::(\d{2}))?", text, re.I,
    )
    if not match:
        return None
    month, day, year, hour, minute, second, ampm, offset, offminute = match.groups()
    months = "jan feb mar apr may jun jul aug sep oct nov dec".split()
    hours = int(offset.replace("−", "-"))
    tz = timezone(timedelta(minutes=hours * 60 + (1 if hours >= 0 else -1) * int(offminute or 0)))
    hour = int(hour) % 12 + (12 if ampm.upper() == "PM" else 0)
    years = [int(year)] if year else [now.year - 1, now.year, now.year + 1]
    candidates = [datetime(y, months.index(month.lower()) + 1, int(day), hour,
                           int(minute), int(second or 0), tzinfo=tz).astimezone(NY) for y in years]
    stamp = min(candidates, key=lambda d: abs((now - d).total_seconds()))
    return stamp if stamp <= now + timedelta(minutes=1) else None


def google_html_quote(html, ticker, exchange, now):
    soup = BeautifulSoup(html, "lxml")
    # Canonical URL identifies the page; sidebar instruments must never be used.
    canonical = soup.find("meta", attrs={"property": "og:url"})
    if canonical and f"/quote/{ticker}:{exchange}" not in canonical.get("content", ""):
        raise ValueError("Google Finance devolvió otro instrumento")
    main = soup.select_one('main') or soup.select_one('[role="main"]') or soup
    price_node = main.select_one('.YMlKec.fxKbKc')
    if price_node:
        price_text = price_node.get_text(" ", strip=True)
        price = float(re.sub(r"[^\d.+-]", "", price_text))
        owner = price_node.find_parent(attrs={"data-last-price": True})
        if owner and owner.get("data-exchange") not in (None, exchange):
            raise ValueError("Google: precio principal de otra bolsa")
        raw_stamp = owner.get("data-last-normal-market-timestamp") if owner else None
        stamp = None
        if raw_stamp:
            sec = int(raw_stamp)
            stamp = datetime.fromtimestamp(sec / 1000 if sec > 10_000_000_000 else sec, tz=NY)
        # Scope visible date to the quote header, ending before chart/sidebar.
        text = main.get_text(" ", strip=True)
        start = text.find(price_text)
        header = text[start:start + 700] if start >= 0 else ""
        visible = visible_google_stamp(header, now)
        if visible is not None:
            stamp = visible
    else:
        # Google also serves a text-first layout without the legacy data attrs.
        text = re.sub(r"\s+", " ", main.get_text(" ", strip=True))
        if ticker == "SPBLSCUP":
            label = r"S&P(?:/BVL)?\s+Peru\s+Select\s+20%\s+Capped\s+Index\s*\(USD\)"
        else:
            title = soup.title.get_text(" ", strip=True) if soup.title else ""
            marker = f" ({ticker})"
            if marker not in title or f"{ticker}:{exchange}" not in text:
                raise ValueError(f"Google: {ticker} sin identidad principal verificable")
            label = re.escape(title.split(marker)[0])
        # The FIRST price next to the instrument name is the regular quote;
        # the second may be after-hours and must not replace it.
        match = re.search(label + r"\s+\$?([\d,]+(?:\.\d+)?)", text, re.I)
        if not match:
            raise ValueError(f"Google: {ticker} sin precio principal")
        price = float(match.group(1).replace(",", ""))
        stamp = visible_google_stamp(text[match.end():match.end() + 700], now)
    if not positive(price) or stamp is None or stamp > now + timedelta(minutes=1):
        raise ValueError(f"Google: {ticker} sin precio y hora propios verificables")
    ctx = session_context(now)
    confirmed = stamp.date().isoformat() == ctx["date"] and now >= ctx["close"] and stamp >= ctx["close"]
    return price, stamp, confirmed
