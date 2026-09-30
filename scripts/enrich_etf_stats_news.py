from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "public" / "data" / "etf_market_snapshot.json"
SYMBOLS = ["SPY", "QQQ", "EEM", "EPU", "MCHI", "CPER"]
NEWS_REFRESH_MINUTES = 30
NEWS_QUERIES = {
    "SPY": "S&P 500 Federal Reserve inflation US economy stocks",
    "QQQ": "Nasdaq technology semiconductors Nvidia Apple Microsoft stocks",
    "EEM": "emerging markets dollar China Taiwan Korea stocks",
    "EPU": "Peru economy mining copper Credicorp Southern Copper stocks",
    "MCHI": "China economy stocks Alibaba Tencent technology",
    "CPER": "copper price China demand inventories mining",
}


def _safe_float(value: Any) -> float | None:
    try:
        x = float(value)
        return x if math.isfinite(x) else None
    except Exception:
        return None


def _extract_frame(raw: pd.DataFrame, symbol: str) -> pd.DataFrame:
    if raw is None or raw.empty:
        return pd.DataFrame()
    if isinstance(raw.columns, pd.MultiIndex):
        if symbol not in raw.columns.get_level_values(0):
            return pd.DataFrame()
        frame = raw[symbol].copy()
    else:
        if len(SYMBOLS) != 1:
            return pd.DataFrame()
        frame = raw.copy()
    if frame.index.tz is not None:
        frame.index = frame.index.tz_convert("America/New_York")
    else:
        frame.index = pd.to_datetime(frame.index, errors="coerce")
    frame = frame[~frame.index.isna()].sort_index()
    return frame.dropna(subset=["Close"])


def _intraday_returns(frame: pd.DataFrame, days: int) -> pd.Series:
    if frame.empty:
        return pd.Series(dtype=float)
    dates = pd.Index(frame.index.date)
    unique_dates = list(dict.fromkeys(dates))[-days:]
    subset = frame.loc[dates.isin(unique_dates)].copy()
    grouped = subset.groupby(subset.index.date, group_keys=False)["Close"].pct_change()
    return pd.to_numeric(grouped, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()


def _stats(r: pd.Series) -> dict[str, Any]:
    x = pd.to_numeric(r, errors="coerce").dropna().astype(float)
    n = int(len(x))
    if n < 3:
        return {
            "n": n,
            "mean": None,
            "std": None,
            "skew": None,
            "excess_kurtosis": None,
            "jb": None,
            "p_value": None,
            "normality": "muestra insuficiente",
        }
    mean = _safe_float(x.mean())
    std = _safe_float(x.std(ddof=1))
    skew = _safe_float(x.skew())
    kurt = _safe_float(x.kurt())
    jb = None
    p = None
    if n >= 8 and skew is not None and kurt is not None:
        jb = n / 6.0 * (skew**2 + (kurt**2) / 4.0)
        # Bajo H0 y muestra razonable, JB ~ chi-cuadrado con 2 gl; SF = exp(-x/2).
        p = math.exp(-jb / 2.0)
    if p is None:
        label = "muestra insuficiente"
    elif p >= 0.05:
        label = "compatible con normalidad"
    else:
        label = "no compatible con normalidad"
    return {
        "n": n,
        "mean": mean,
        "std": std,
        "skew": skew,
        "excess_kurtosis": kurt,
        "jb": _safe_float(jb),
        "p_value": _safe_float(p),
        "normality": label,
    }


def _prob_hist(values: np.ndarray, edges: np.ndarray) -> np.ndarray:
    if values.size == 0:
        return np.zeros(len(edges) - 1, dtype=float)
    counts, _ = np.histogram(values, bins=edges)
    total = counts.sum()
    return counts.astype(float) / total if total > 0 else np.zeros_like(counts, dtype=float)


def _distribution_payload(frame: pd.DataFrame) -> dict[str, Any]:
    r1 = _intraday_returns(frame, 1)
    r5 = _intraday_returns(frame, 5)
    r20 = _intraday_returns(frame, 20)
    base = r20 if len(r20) >= 30 else (r5 if len(r5) >= 10 else r1)
    if len(base) < 3:
        return {"windows": {}, "histogram": {}, "shift": {"label": "sin datos suficientes"}}

    vals = base.to_numpy(dtype=float)
    lo = float(np.nanpercentile(vals, 0.5))
    hi = float(np.nanpercentile(vals, 99.5))
    if not math.isfinite(lo) or not math.isfinite(hi) or hi <= lo:
        mu = float(np.nanmean(vals))
        sd = float(np.nanstd(vals)) or 0.0001
        lo, hi = mu - 4 * sd, mu + 4 * sd
    edges = np.linspace(lo, hi, 31)
    centers = (edges[:-1] + edges[1:]) / 2

    windows = {"today": r1, "5d": r5, "20d": r20}
    stats = {k: _stats(v) for k, v in windows.items()}
    probs = {k: _prob_hist(v.to_numpy(dtype=float), edges) for k, v in windows.items()}

    p5 = probs["5d"]
    p20 = probs["20d"]
    hellinger = _safe_float(np.sqrt(np.sum((np.sqrt(p5) - np.sqrt(p20)) ** 2)) / np.sqrt(2))
    std5 = stats["5d"].get("std")
    std20 = stats["20d"].get("std")
    vol_ratio = _safe_float(std5 / std20) if std5 not in (None, 0) and std20 not in (None, 0) else None

    if hellinger is None or stats["5d"].get("n", 0) < 30 or stats["20d"].get("n", 0) < 100:
        shift_label = "sin datos suficientes"
    elif hellinger < 0.12 and (vol_ratio is None or 0.80 <= vol_ratio <= 1.25):
        shift_label = "distribución relativamente estable"
    elif hellinger < 0.25 and (vol_ratio is None or 0.65 <= vol_ratio <= 1.50):
        shift_label = "distribución cambiando"
    else:
        shift_label = "cambio fuerte de distribución"

    return {
        "windows": stats,
        "histogram": {
            "centers": [float(x) for x in centers],
            "today": [float(x) for x in probs["today"]],
            "5d": [float(x) for x in probs["5d"]],
            "20d": [float(x) for x in probs["20d"]],
        },
        "shift": {
            "hellinger_5d_vs_20d": hellinger,
            "volatility_ratio_5d_vs_20d": vol_ratio,
            "label": shift_label,
        },
        "method": (
            "Rendimientos intradía de 5 minutos, excluyendo saltos entre sesiones. "
            "Normalidad: prueba Jarque-Bera (umbral p=0,05). El cambio 5D vs 20D usa distancia de Hellinger y relación de volatilidad; "
            "la etiqueta de cambio es una heurística descriptiva, no una predicción."
        ),
    }


def _parse_news_item(item: dict[str, Any]) -> dict[str, Any] | None:
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
    return {
        "title": str(title).strip(),
        "source": str(source).strip(),
        "url": str(url).strip() if url else None,
        "published_at": published,
        "summary": str(summary).strip()[:500],
    }


def _fetch_news(symbol: str) -> list[dict[str, Any]]:
    query = NEWS_QUERIES[symbol]
    search = yf.Search(query, news_count=10)
    raw = getattr(search, "news", None) or []
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        parsed = _parse_news_item(item)
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


def _news_due(payload: dict[str, Any], now: datetime) -> bool:
    raw = payload.get("news_refreshed_at")
    if not raw:
        return True
    try:
        previous = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if previous.tzinfo is None:
            previous = previous.replace(tzinfo=timezone.utc)
        return now - previous >= timedelta(minutes=NEWS_REFRESH_MINUTES)
    except Exception:
        return True


def main() -> None:
    if not SNAPSHOT.exists():
        raise SystemExit(f"No existe {SNAPSHOT}")
    payload = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    by_symbol = {x.get("symbol"): x for x in payload.get("tickers", []) if isinstance(x, dict)}

    raw = yf.download(
        SYMBOLS,
        period="1mo",
        interval="5m",
        auto_adjust=False,
        actions=False,
        progress=False,
        threads=True,
        group_by="ticker",
    )
    for symbol in SYMBOLS:
        item = by_symbol.get(symbol)
        if not item:
            continue
        frame = _extract_frame(raw, symbol)
        try:
            item["distribution"] = _distribution_payload(frame)
        except Exception as exc:
            item["distribution"] = {"error": str(exc), "windows": {}, "histogram": {}, "shift": {"label": "sin datos"}}

    now = datetime.now(timezone.utc)
    news_errors: dict[str, str] = {}
    if _news_due(payload, now):
        for symbol in SYMBOLS:
            item = by_symbol.get(symbol)
            if not item:
                continue
            previous_news = item.get("news", [])
            try:
                news = _fetch_news(symbol)
                item["news"] = news if news else previous_news
            except Exception as exc:
                news_errors[symbol] = str(exc)
                item["news"] = previous_news
        payload["news_refreshed_at"] = now.isoformat()
    payload["news_refresh_minutes"] = NEWS_REFRESH_MINUTES
    payload["news_errors"] = news_errors
    payload["distribution_refreshed_at"] = now.isoformat()
    payload["distribution_method"] = (
        "Se analizan rendimientos intradía de 5 minutos en ventanas de hoy, 5 y 20 sesiones. "
        "Jarque-Bera evalúa compatibilidad con una distribución normal; el cambio 5D vs 20D es descriptivo y no predice el precio."
    )

    SNAPSHOT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print("Distribución estadística actualizada para:", ", ".join(SYMBOLS))
    print("Noticias refrescadas:", "sí" if payload.get("news_refreshed_at") == now.isoformat() else "no")
    if news_errors:
        print("Advertencias noticias:", news_errors)


if __name__ == "__main__":
    main()
