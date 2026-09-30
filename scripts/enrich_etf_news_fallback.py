from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

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


def _translate_es(text: str) -> str | None:
    text = str(text or "").strip()
    if not text:
        return ""
    try:
        params = urlencode({
            "client": "gtx",
            "sl": "auto",
            "tl": "es",
            "dt": "t",
            "q": text[:3500],
        })
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
        if summary:
            row["summary_es"] = (parts[1].strip() if len(parts) > 1 else "")[:700]
        else:
            row["summary_es"] = ""
    return row


def _parse(item: dict[str, Any], related_to: str | None = None) -> dict[str, Any] | None:
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
    if related_to:
        source = f"{source} · {related_to} (componente)"
    return {
        "title": str(title).strip(),
        "source": str(source).strip(),
        "url": str(url).strip() if url else None,
        "published_at": published,
        "summary": str(summary).strip()[:500],
        "related_to": related_to,
    }


def _dedupe(raw: list[tuple[dict[str, Any], str | None]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item, related_to in raw:
        parsed = _parse(item, related_to=related_to)
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


def _collect(symbol: str) -> list[dict[str, Any]]:
    raw: list[tuple[dict[str, Any], str | None]] = []
    try:
        raw.extend((x, None) for x in (yf.Ticker(symbol).get_news(count=8, tab="news") or []))
    except Exception:
        pass
    try:
        raw.extend((x, None) for x in (getattr(yf.Search(symbol, news_count=8, raise_errors=False), "news", None) or []))
    except Exception:
        pass
    try:
        raw.extend((x, None) for x in (getattr(yf.Search(QUERIES[symbol], news_count=8, raise_errors=False), "news", None) or []))
    except Exception:
        pass
    return _dedupe(raw)


def _collect_components(item: dict[str, Any]) -> list[dict[str, Any]]:
    raw: list[tuple[dict[str, Any], str | None]] = []
    holdings = item.get("holdings", []) if isinstance(item, dict) else []
    for holding in holdings[:5]:
        hs = str(holding.get("symbol") or "").strip() if isinstance(holding, dict) else ""
        if not hs or hs.lower() in {"nan", "none"}:
            continue
        try:
            news = yf.Ticker(hs).get_news(count=4, tab="news") or []
            raw.extend((x, hs) for x in news)
        except Exception:
            continue
        if len(raw) >= 12:
            break
    return _dedupe(raw)


def _load(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return fallback
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else fallback
    except Exception:
        return fallback


def _recent_symbol_attempt(cache: dict[str, Any], symbol: str, now: datetime) -> bool:
    attempts = cache.get("attempted_by_symbol") if isinstance(cache.get("attempted_by_symbol"), dict) else {}
    raw = attempts.get(symbol)
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
    by_symbol = {x.get("symbol"): x for x in payload.get("tickers", []) if isinstance(x, dict)}
    now = datetime.now(timezone.utc)

    counts: dict[str, int] = {}
    attempted: list[str] = []
    for symbol in SYMBOLS:
        existing = cache["by_symbol"].get(symbol, []) or []
        if not existing and not _recent_symbol_attempt(cache, symbol, now):
            attempted.append(symbol)
            rows = _collect(symbol)
            if not rows:
                rows = _collect_components(by_symbol.get(symbol, {}))
            cache["attempted_by_symbol"][symbol] = now.isoformat()
            if rows:
                cache["by_symbol"][symbol] = rows
                existing = rows

        # La traducción se guarda en caché: solo se consulta cuando falta.
        translated_rows = []
        for row in existing:
            translated_rows.append(_ensure_spanish(row))
        if translated_rows:
            cache["by_symbol"][symbol] = translated_rows
        counts[symbol] = len(translated_rows)

    total = sum(len(cache["by_symbol"].get(s, []) or []) for s in SYMBOLS)
    if attempted and total > 0:
        cache["refreshed_at"] = now.isoformat()
    cache["fallback_attempted_at"] = now.isoformat() if attempted else cache.get("fallback_attempted_at")
    cache["refresh_minutes"] = REFRESH_MINUTES
    NEWS_CACHE.parent.mkdir(parents=True, exist_ok=True)
    NEWS_CACHE.write_text(json.dumps(cache, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    for s in SYMBOLS:
        if s in by_symbol:
            by_symbol[s]["news"] = cache["by_symbol"].get(s, []) or []
    payload["news_refreshed_at"] = cache.get("refreshed_at")
    payload["news_refresh_minutes"] = REFRESH_MINUTES
    payload["news_fallback_counts"] = {s: len(cache["by_symbol"].get(s, []) or []) for s in SYMBOLS}
    payload["news_language"] = "es"
    SNAPSHOT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print("Noticias fallback por ETF:", payload["news_fallback_counts"], "intentados:", attempted, "total:", total)


if __name__ == "__main__":
    main()
