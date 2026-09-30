from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "public" / "data" / "etf_market_snapshot.json"
NEWS_CACHE = ROOT / "public" / "data" / "etf_news_cache.json"
SYMBOLS = ["SPY", "QQQ", "EEM", "EPU", "MCHI", "CPER"]
REFRESH_MINUTES = 30
QUERIES = {
    "SPY": "S&P 500 Federal Reserve inflation US economy stocks",
    "QQQ": "Nasdaq technology semiconductors Nvidia Apple Microsoft stocks",
    "EEM": "emerging markets dollar China Taiwan Korea stocks",
    "EPU": "Peru economy mining copper Credicorp Southern Copper stocks",
    "MCHI": "China economy stocks Alibaba Tencent technology",
    "CPER": "copper price China demand inventories mining",
}


def _parse(item: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    content = item.get("content") if isinstance(item.get("content"), dict) else item
    title = content.get("title") or item.get("title")
    if not title:
        return None
    provider = content.get("provider") if isinstance(content.get("provider"), dict) else {}
    source = provider.get("displayName") or item.get("publisher") or content.get("publisher") or "Yahoo Finance"
    url = None
    for key in ("canonicalUrl", "clickThroughUrl"):
        obj = content.get(key)
        if isinstance(obj, dict) and obj.get("url"):
            url = obj.get("url")
            break
    url = url or item.get("link") or content.get("link")
    published = content.get("pubDate") or item.get("pubDate")
    if not published and item.get("providerPublishTime"):
        try:
            published = datetime.fromtimestamp(float(item["providerPublishTime"]), tz=timezone.utc).isoformat()
        except Exception:
            published = None
    summary = content.get("summary") or item.get("summary") or ""
    return {
        "title": str(title).strip(),
        "source": str(source).strip(),
        "url": str(url).strip() if url else None,
        "published_at": published,
        "summary": str(summary).strip()[:500],
    }


def _collect(symbol: str) -> list[dict[str, Any]]:
    raw: list[dict[str, Any]] = []
    try:
        raw.extend(yf.Ticker(symbol).get_news(count=8, tab="news") or [])
    except Exception:
        pass
    try:
        raw.extend(getattr(yf.Search(symbol, news_count=8, raise_errors=False), "news", None) or [])
    except Exception:
        pass
    try:
        raw.extend(getattr(yf.Search(QUERIES[symbol], news_count=8, raise_errors=False), "news", None) or [])
    except Exception:
        pass

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        parsed = _parse(item)
        if not parsed:
            continue
        key = (parsed.get("url") or parsed["title"]).lower()
        if key in seen:
            continue
        seen.add(key)
        rows.append(parsed)
        if len(rows) >= 5:
            break
    return rows


def _load(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return fallback
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else fallback
    except Exception:
        return fallback


def _recent_attempt(cache: dict[str, Any], now: datetime) -> bool:
    raw = cache.get("fallback_attempted_at")
    if not raw:
        return False
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return now - dt < timedelta(minutes=REFRESH_MINUTES)
    except Exception:
        return False


def main() -> None:
    if not SNAPSHOT.exists():
        raise SystemExit(f"No existe {SNAPSHOT}")
    payload = _load(SNAPSHOT, {})
    cache = _load(NEWS_CACHE, {"by_symbol": {}})
    cache.setdefault("by_symbol", {})
    by_symbol = {x.get("symbol"): x for x in payload.get("tickers", []) if isinstance(x, dict)}
    now = datetime.now(timezone.utc)

    existing_total = sum(len(cache["by_symbol"].get(s, []) or []) for s in SYMBOLS)
    if existing_total > 0 or _recent_attempt(cache, now):
        for s in SYMBOLS:
            if s in by_symbol:
                by_symbol[s]["news"] = cache["by_symbol"].get(s, []) or []
        payload["news_refreshed_at"] = cache.get("refreshed_at")
        payload["news_refresh_minutes"] = REFRESH_MINUTES
        SNAPSHOT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        print(f"Noticias fallback: sin consulta nueva; caché={existing_total} artículos")
        return

    counts: dict[str, int] = {}
    for symbol in SYMBOLS:
        rows = _collect(symbol)
        counts[symbol] = len(rows)
        if rows:
            cache["by_symbol"][symbol] = rows

    cache["fallback_attempted_at"] = now.isoformat()
    total = sum(len(cache["by_symbol"].get(s, []) or []) for s in SYMBOLS)
    if total > 0:
        cache["refreshed_at"] = now.isoformat()
    cache["refresh_minutes"] = REFRESH_MINUTES
    NEWS_CACHE.parent.mkdir(parents=True, exist_ok=True)
    NEWS_CACHE.write_text(json.dumps(cache, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    for s in SYMBOLS:
        if s in by_symbol:
            by_symbol[s]["news"] = cache["by_symbol"].get(s, []) or []
    payload["news_refreshed_at"] = cache.get("refreshed_at")
    payload["news_refresh_minutes"] = REFRESH_MINUTES
    payload["news_fallback_counts"] = counts
    SNAPSHOT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print("Noticias fallback por ETF:", counts, "total:", total)


if __name__ == "__main__":
    main()
