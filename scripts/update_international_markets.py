"""Public exchange indices and US ETF pre-market quotes for mercados.html."""
import argparse
import csv
import json
import math
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import exchange_calendars as xc

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "public/data/indices_internacionales.json"
CATALOG = ROOT / "data/processed/ca0001_modelo74_catalogo_indices.csv"
NY = ZoneInfo("America/New_York")
GROUPS = {
    "china": [("000001.SS", "XSHG"), ("000300.SS", "XSHG"), ("399001.SZ", "XSHG"), ("^HSI", "XHKG")],
    "asia": [("^N225", "XTKS"), ("^KS11", "XKRX"), ("^TWII", "XTAI"), ("^BSESN", "XBOM"), ("^AXJO", "XASX")],
    "europa": [("^GDAXI", "XETR"), ("^FTSE", "XLON"), ("^FCHI", "XPAR"), ("^IBEX", "XMAD")],
    "america": [("^GSPC", "XNYS"), ("^NDX", "XNYS"), ("^DJI", "XNYS"), ("^BVSP", "BVMF"), ("^MXX", "XMEX")],
}
ETFS = ["SPY", "QQQ", "EEM", "EPU", "MCHI", "CPER"]


def request_json(url):
    request = Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    with urlopen(request, timeout=12) as response:
        return json.load(response)


def number(value):
    try:
        result = float(value)
    except (ValueError, TypeError):
        return None
    return result if math.isfinite(result) else None


def yahoo_chart(symbol, period="1d", extended=False):
    params = "?range=" + period + "&interval=5m&includePrePost=" + str(extended).lower()
    for host in ("query1", "query2"):
        try:
            result = request_json("https://" + host + ".finance.yahoo.com/v8/finance/chart/" + quote(symbol, safe="") + params)["chart"]["result"][0]
            if result["meta"]["symbol"].upper() != symbol.upper():
                raise ValueError("Símbolo inesperado")
            return result
        except Exception as exc:
            if host == "query2":
                raise RuntimeError(f"Yahoo Finance: {exc}") from exc


def bars(chart):
    quotes = (chart.get("indicators", {}).get("quote") or [{}])[0]
    return [(t, round(float(p), 5)) for t, p in zip(chart.get("timestamp") or [], quotes.get("close") or [])
            if isinstance(t, int) and number(p) is not None and float(p) > 0]


def index_quote(symbol, now):
    chart = yahoo_chart(symbol)
    meta = chart["meta"]
    stamp = int(meta["regularMarketTime"])
    price = number(meta["regularMarketPrice"])
    if not price or price <= 0 or not 0 < stamp <= now + 90:
        raise ValueError("Cotización o fecha inválida")
    tz = ZoneInfo(meta["exchangeTimezoneName"])
    local_day = datetime.fromtimestamp(stamp, tz).date()
    points = [[t, p] for t, p in bars(chart) if t <= stamp and datetime.fromtimestamp(t, tz).date() == local_day]
    change = number(meta.get("regularMarketChangePercent"))
    if change is None:
        prior = number(meta.get("previousClose") or meta.get("chartPreviousClose"))
        change = (price / prior - 1) * 100 if prior and prior > 0 else None
    return {"at": stamp, "price": price, "change": change, "session": local_day.isoformat(), "points": points}


def schedules(now):
    first = now.date() - timedelta(days=18)
    last = now.date() + timedelta(days=18)
    result = {}
    for mic in sorted({mic for group in GROUPS.values() for _, mic in group}):
        try:
            calendar = xc.get_calendar(mic)
            rows = calendar.schedule.loc[first.isoformat():last.isoformat()]
        except Exception as exc:
            print(f"Calendario {mic}: {exc}", file=sys.stderr)
            result[mic] = {"tz": "UTC", "until": "1970-01-01", "sessions": []}
            continue
        result[mic] = {
            "tz": str(calendar.tz),
            "until": min(last.isoformat(), calendar.last_session.date().isoformat()),
            "sessions": [[int(d.timestamp()) if d == d else None for d in row]
                         for row in rows[["open", "break_start", "break_end", "close"]].itertuples(index=False, name=None)],
        }
    return result


def pre_window(target, previous):
    local_day = datetime.fromtimestamp(target[0], NY).date()
    start = int(datetime.combine(local_day, time(4), NY).timestamp())
    return local_day.isoformat(), start, target[0], previous


def nasdaq_pre(symbol, day, start, end, now):
    url = f"https://api.nasdaq.com/api/quote/{symbol}/info?assetclass=etf"
    data = request_json(url)["data"]
    if not data or str(data.get("marketStatus", "")).lower() != "pre-market":
        return None
    primary = data.get("primaryData") or {}
    match = re.fullmatch(r"([A-Za-z]{3} \d{1,2}, \d{4} \d{1,2}:\d{2}(?::\d{2})? [AP]M) ET", str(primary.get("lastTradeTimestamp", "")))
    if not match:
        return None
    fmt = "%b %d, %Y %I:%M:%S %p" if match[1].count(":") == 2 else "%b %d, %Y %I:%M %p"
    dt = datetime.strptime(match[1], fmt).replace(tzinfo=NY)
    stamp = int(dt.timestamp())
    if dt.date().isoformat() != day or not start <= stamp < end or stamp > now:
        return None
    price = number(str(primary.get("lastSalePrice", "")).replace("$", "").replace(",", ""))
    if not price or price <= 0:
        return None
    change = number(str(primary.get("percentageChange", "")).strip().rstrip("%"))
    return {"at": stamp, "price": price, "change": change, "source": "Nasdaq"}


def pre_quote(symbol, window, now, cached):
    day, start, end, previous = window
    if now < start:
        return None
    if start <= now < end:
        try:
            latest = nasdaq_pre(symbol, day, start, end, now)
            if latest:
                return latest
        except Exception as exc:
            print(f"{symbol} Nasdaq: {exc}", file=sys.stderr)
    if now >= end and cached and cached.get("complete"):
        return cached
    chart = yahoo_chart(symbol, "5d", True)
    prices = bars(chart)
    eligible = [(t, p) for t, p in prices if start <= t < end and t <= now]
    if not eligible:
        return cached
    stamp, price = max(eligible)
    meta = chart["meta"]
    prev_open, _, _, prev_close = previous
    regular_stamp = meta.get("regularMarketTime") or 0
    base = None
    if prev_open <= regular_stamp <= prev_close + 15 * 60:
        base = number(meta.get("regularMarketPrice"))
    if base is None:
        # An official daily close is preferable to the previous 15:55 candle.
        base = yahoo_daily_close(symbol, datetime.fromtimestamp(prev_open, NY).date())
    change = (price / base - 1) * 100 if base and base > 0 else None
    return {"at": stamp, "price": price, "change": change, "source": "Yahoo Finance · 5 min"}


def yahoo_daily_close(symbol, target):
    try:
        url = "https://query1.finance.yahoo.com/v8/finance/chart/" + quote(symbol, safe="") + "?range=1mo&interval=1d"
        chart = request_json(url)["chart"]["result"][0]
        return next((p for t, p in reversed(bars(chart)) if datetime.fromtimestamp(t, NY).date() == target), None)
    except Exception:
        return None


def keep_latest(old, new):
    if old and (not new or old["at"] > new["at"]):
        return old
    return new


def build(force=False):
    previous = json.loads(OUTPUT.read_text()) if OUTPUT.exists() else {}
    now = datetime.now(timezone.utc)
    stamp = int(now.timestamp())
    if not force and stamp - previous.get("checked_at", 0) < 7 * 60:
        return
    calendars = schedules(now)
    us = calendars["XNYS"]["sessions"]
    ny_day = now.astimezone(NY).date()
    target = max(i for i, s in enumerate(us) if datetime.fromtimestamp(s[0], NY).date() <= ny_day)
    window = pre_window(us[target], us[target - 1])
    pre_day, start, end, _ = window
    active = start <= stamp <= end or any(s[0] <= stamp <= s[3] + 75 * 60 for c in calendars.values() for s in c["sessions"])
    if not force and previous and not active and stamp - previous["checked_at"] < 12 * 3600:
        return
    with CATALOG.open(encoding="utf-8-sig") as stream:
        catalog = {r["ticker_elegido"]: r for r in csv.DictReader(stream) if r["transformacion"] == "retorno_indice_moneda_local"}
    old_indices = {r["symbol"]: r for r in previous.get("indices", [])}
    old_pre = previous.get("premarket", {}) if previous.get("premarket_day") == pre_day else {}

    def read_index(item):
        symbol, mic, group = item
        prior = old_indices.get(symbol, {}).get("quote")
        try:
            current = index_quote(symbol, stamp)
            value = keep_latest(prior, current)
            ok = True
        except Exception as exc:
            print(f"{symbol}: {exc}", file=sys.stderr)
            value, ok = prior, False
        return {"symbol": symbol, "name": catalog[symbol]["indice"], "market": catalog[symbol]["pais_region"],
                "calendar": mic, "group": group, "quote": value, "ok": ok}

    def read_pre(symbol):
        old = old_pre.get(symbol, {})
        cached = old.get("quote")
        try:
            value = keep_latest(cached, pre_quote(symbol, window, stamp, cached))
            if value and stamp >= end + 30 * 60:
                value["complete"] = True
            return symbol, {"quote": value, "ok": True}
        except Exception as exc:
            print(f"{symbol} premercado: {exc}", file=sys.stderr)
            return symbol, {"quote": cached, "ok": False}

    universe = [(sym, mic, group) for group, items in GROUPS.items() for sym, mic in items]
    with ThreadPoolExecutor(max_workers=5) as pool:
        indices = list(pool.map(read_index, universe))
        pre = dict(pool.map(read_pre, ETFS))
    if not any(r["ok"] for r in indices) and not any(r["ok"] and r["quote"] for r in pre.values()):
        raise RuntimeError("Ningún proveedor respondió con una cotización")
    payload = {"checked_at": stamp, "calendars": calendars, "indices": indices, "premarket_day": pre_day, "premarket": pre}
    tmp = OUTPUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n", encoding="utf-8")
    tmp.replace(OUTPUT)
    print(f"Índices consultados: {sum(r['ok'] for r in indices)}/{len(indices)}. Premercado: {pre_day}.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    build(parser.parse_args().force)
