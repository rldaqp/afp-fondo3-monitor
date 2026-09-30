from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

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
    "EPU": "Peru economy mining copper Credicorp Southern Copper Buenaventura",
    "MCHI": "China economy stocks Alibaba Tencent technology",
    "CPER": "copper price China demand inventories mining",
}
MACRO_QUERIES = {
    "Brent / petróleo": "Brent crude oil OPEC Middle East oil price",
    "Tasas / bonos": "US Treasury yields Federal Reserve interest rates inflation",
    "Dólar": "US dollar DXY emerging markets currencies",
    "China": "China economy stimulus demand commodities",
    "Cobre": "copper price inventories China demand mining",
}
MACRO_SOURCES = {
    "Brent / petróleo": ["BZ=F", "CL=F"],
    "Tasas / bonos": ["^TNX", "TLT"],
    "Dólar": ["DX-Y.NYB", "UUP"],
    "China": ["MCHI", "FXI"],
    "Cobre": ["HG=F", "CPER"],
}
MACRO_QUOTES = [
    {"label": "Brent", "symbol": "BZ=F", "topic": "Brent / petróleo", "unit": "USD/barril", "decimals": 2},
    {"label": "Treasury 10 años", "symbol": "^TNX", "topic": "Tasas / bonos", "unit": "%", "decimals": 3},
    {"label": "Dólar DXY", "symbol": "DX-Y.NYB", "topic": "Dólar", "unit": "puntos", "decimals": 2},
    {"label": "China (MCHI)", "symbol": "MCHI", "topic": "China", "unit": "USD", "decimals": 2},
    {"label": "Cobre", "symbol": "HG=F", "topic": "Cobre", "unit": "USD/libra", "decimals": 4},
]


def _translate_es(text: str) -> str | None:
    text = str(text or "").strip()
    if not text:
        return ""
    try:
        params = urlencode({"client": "gtx", "sl": "auto", "tl": "es", "dt": "t", "q": text[:3500]})
        req = Request(
            f"https://translate.googleapis.com/translate_a/single?{params}",
            headers={"User-Agent": "Mozilla/5.0"},
        )
        with urlopen(req, timeout=8) as response:
            data = json.loads(response.read().decode("utf-8"))
        translated = "".join(
            str(segment[0])
            for segment in (data[0] if isinstance(data, list) and data else [])
            if isinstance(segment, list) and segment and segment[0]
        ).strip()
        return translated or None
    except Exception:
        return None


def _ensure_spanish(row: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(row, dict):
        return row
    title = str(row.get("title") or "").strip()
    summary = str(row.get("summary") or "").strip()
    if row.get("title_es") and (not summary or row.get("summary_es") is not None):
        return row
    combined = title if not summary else f"{title}\n\n{summary}"
    translated = _translate_es(combined)
    if translated:
        parts = translated.split("\n", 1)
        row["title_es"] = parts[0].strip() or title
        row["summary_es"] = (parts[1].strip() if summary and len(parts) > 1 else "")[:700]
    return row


def _parse(item: dict[str, Any], related_to: str | None = None, macro_topic: str | None = None) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    content = item.get("content") if isinstance(item.get("content"), dict) else item
    title = content.get("title") or item.get("title")
    if not title:
        return None
    provider = content.get("provider") if isinstance(content.get("provider"), dict) else {}
    source = provider.get("displayName") or item.get("publisher") or content.get("publisher") or "Fuente financiera"
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
    if related_to:
        source = f"{source} · {related_to} (componente)"
    return {
        "title": str(title).strip(),
        "source": str(source).strip(),
        "url": str(url).strip() if url else None,
        "published_at": published,
        "summary": str(summary).strip()[:500],
        "related_to": related_to,
        "macro_topic": macro_topic,
    }


def _dedupe(raw: list[tuple[dict[str, Any], str | None, str | None]], limit: int = 5) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item, related_to, macro_topic in raw:
        parsed = _parse(item, related_to=related_to, macro_topic=macro_topic)
        if not parsed:
            continue
        key = (parsed.get("url") or parsed["title"]).lower()
        if key in seen:
            continue
        seen.add(key)
        rows.append(parsed)
        if len(rows) >= limit:
            break
    return rows


def _google_news_rss(query: str, *, macro_topic: str | None = None, limit: int = 4, days: int = 1) -> list[dict[str, Any]]:
    """Google News RSS fallback. We keep only headline/source/time; no article-body scraping."""
    try:
        q = f"{query} when:{max(1, int(days))}d"
        params = urlencode({"q": q, "hl": "en-US", "gl": "US", "ceid": "US:en"})
        req = Request(
            f"https://news.google.com/rss/search?{params}",
            headers={"User-Agent": "Mozilla/5.0"},
        )
        with urlopen(req, timeout=10) as response:
            root = ET.fromstring(response.read())
        rows: list[dict[str, Any]] = []
        for node in root.findall("./channel/item")[:limit]:
            title = (node.findtext("title") or "").strip()
            link = (node.findtext("link") or "").strip()
            pub = (node.findtext("pubDate") or "").strip()
            source_node = node.find("source")
            source = ((source_node.text if source_node is not None else "") or "Google News").strip()
            if not title:
                continue
            published_at = pub
            if pub:
                try:
                    published_at = parsedate_to_datetime(pub).astimezone(timezone.utc).isoformat()
                except Exception:
                    pass
            rows.append({
                "title": title,
                "publisher": source,
                "link": link or None,
                "pubDate": published_at,
                "summary": "",
                "macro_topic": macro_topic,
            })
        return rows
    except Exception:
        return []


def _collect(symbol: str) -> list[dict[str, Any]]:
    raw: list[tuple[dict[str, Any], str | None, str | None]] = []
    try:
        raw.extend((x, None, None) for x in (yf.Ticker(symbol).get_news(count=8, tab="news") or []))
    except Exception:
        pass
    try:
        raw.extend((x, None, None) for x in (getattr(yf.Search(symbol, news_count=8, raise_errors=False), "news", None) or []))
    except Exception:
        pass
    try:
        raw.extend((x, None, None) for x in (getattr(yf.Search(QUERIES[symbol], news_count=8, raise_errors=False), "news", None) or []))
    except Exception:
        pass
    rows = _dedupe(raw, limit=5)
    if not rows and symbol == "EPU":
        rss = _google_news_rss(QUERIES[symbol], limit=5, days=2)
        rows = _dedupe([(x, None, None) for x in rss], limit=5)
    return rows


def _collect_components(item: dict[str, Any]) -> list[dict[str, Any]]:
    raw: list[tuple[dict[str, Any], str | None, str | None]] = []
    holdings = item.get("holdings", []) if isinstance(item, dict) else []
    for holding in holdings[:5]:
        hs = str(holding.get("symbol") or "").strip() if isinstance(holding, dict) else ""
        if not hs or hs.lower() in {"nan", "none"}:
            continue
        try:
            news = yf.Ticker(hs).get_news(count=4, tab="news") or []
            raw.extend((x, hs, None) for x in news)
        except Exception:
            continue
        if len(raw) >= 12:
            break
    return _dedupe(raw, limit=5)


def _collect_macro() -> list[dict[str, Any]]:
    raw: list[tuple[dict[str, Any], str | None, str | None]] = []
    for topic, tickers in MACRO_SOURCES.items():
        topic_rows: list[tuple[dict[str, Any], str | None, str | None]] = []
        for ticker in tickers:
            try:
                news = yf.Ticker(ticker).get_news(count=5, tab="news") or []
                topic_rows.extend((x, None, topic) for x in news[:2])
            except Exception:
                continue
        if not topic_rows:
            rss = _google_news_rss(MACRO_QUERIES[topic], macro_topic=topic, limit=3, days=1)
            topic_rows.extend((x, None, topic) for x in rss)
        raw.extend(topic_rows[:2])
    return _dedupe(raw, limit=10)


def _macro_market_snapshot(previous: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Cotizaciones macro gratuitas. Se conserva el último dato si una fuente falla temporalmente."""
    old = {str(x.get("label")): x for x in (previous or []) if isinstance(x, dict)}
    rows: list[dict[str, Any]] = []
    for cfg in MACRO_QUOTES:
        try:
            hist = yf.Ticker(cfg["symbol"]).history(
                period="5d",
                interval="1d",
                auto_adjust=False,
                actions=False,
            )
            if hist is None or hist.empty or "Close" not in hist.columns:
                raise RuntimeError("sin cotización")
            hist = hist.dropna(subset=["Close"])
            if hist.empty:
                raise RuntimeError("serie vacía")
            last = hist.iloc[-1]
            price = float(last["Close"])
            prev = float(hist.iloc[-2]["Close"]) if len(hist) >= 2 else None
            change = (price / prev - 1) if prev not in (None, 0) else None
            delta = (price - prev) if prev is not None else None
            idx = hist.index[-1]
            asof = idx.isoformat() if hasattr(idx, "isoformat") else str(idx)
            rows.append({
                **cfg,
                "price": price,
                "prev_close": prev,
                "change": change,
                "delta": delta,
                "open": float(last["Open"]) if "Open" in hist.columns and last.get("Open") == last.get("Open") else None,
                "high": float(last["High"]) if "High" in hist.columns and last.get("High") == last.get("High") else None,
                "low": float(last["Low"]) if "Low" in hist.columns and last.get("Low") == last.get("Low") else None,
                "asof": asof,
                "stale": False,
            })
        except Exception:
            prior = old.get(cfg["label"])
            if prior:
                kept = dict(prior)
                kept["stale"] = True
                rows.append(kept)
    return rows


def _load(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return fallback
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else fallback
    except Exception:
        return fallback


def _recent(raw: Any, now: datetime) -> bool:
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
    cache.setdefault("attempted_by_symbol", {})
    cache.setdefault("macro_news", [])
    cache.setdefault("macro_market", [])
    by_symbol = {x.get("symbol"): x for x in payload.get("tickers", []) if isinstance(x, dict)}
    now = datetime.now(timezone.utc)

    attempted: list[str] = []
    for symbol in SYMBOLS:
        existing = cache["by_symbol"].get(symbol, []) or []
        last_attempt = cache["attempted_by_symbol"].get(symbol)
        if not _recent(last_attempt, now):
            attempted.append(symbol)
            rows = _collect(symbol)
            if not rows:
                rows = _collect_components(by_symbol.get(symbol, {}))
            if not rows and symbol == "EPU":
                rss = _google_news_rss(QUERIES[symbol], limit=5, days=2)
                rows = _dedupe([(x, None, None) for x in rss], limit=5)
            cache["attempted_by_symbol"][symbol] = now.isoformat()
            if rows:
                existing = rows
                cache["by_symbol"][symbol] = rows
        translated_rows = [_ensure_spanish(row) for row in existing]
        if translated_rows:
            cache["by_symbol"][symbol] = translated_rows

    macro_attempted = False
    if not cache.get("macro_news") or not _recent(cache.get("macro_attempted_at"), now):
        macro_attempted = True
        macro_rows = _collect_macro()
        cache["macro_attempted_at"] = now.isoformat()
        if macro_rows:
            cache["macro_news"] = macro_rows
    cache["macro_news"] = [_ensure_spanish(row) for row in (cache.get("macro_news") or [])]

    macro_market = _macro_market_snapshot(cache.get("macro_market") or [])
    if macro_market:
        cache["macro_market"] = macro_market

    total = sum(len(cache["by_symbol"].get(s, []) or []) for s in SYMBOLS)
    if (attempted or macro_attempted) and (total > 0 or cache.get("macro_news")):
        cache["refreshed_at"] = now.isoformat()
    cache["fallback_attempted_at"] = now.isoformat() if attempted else cache.get("fallback_attempted_at")
    cache["refresh_minutes"] = REFRESH_MINUTES
    NEWS_CACHE.parent.mkdir(parents=True, exist_ok=True)
    NEWS_CACHE.write_text(json.dumps(cache, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    for s in SYMBOLS:
        if s in by_symbol:
            by_symbol[s]["news"] = cache["by_symbol"].get(s, []) or []
    payload["macro_news"] = cache.get("macro_news", []) or []
    payload["macro_market"] = cache.get("macro_market", []) or []
    payload["news_refreshed_at"] = cache.get("refreshed_at")
    payload["news_refresh_minutes"] = REFRESH_MINUTES
    payload["news_fallback_counts"] = {s: len(cache["by_symbol"].get(s, []) or []) for s in SYMBOLS}
    payload["news_language"] = "es"
    SNAPSHOT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(
        "Noticias por ETF:", payload["news_fallback_counts"],
        "macro:", len(payload["macro_news"]),
        "cotizaciones macro:", len(payload["macro_market"]),
        "refrescados:", attempted,
    )


if __name__ == "__main__":
    main()
