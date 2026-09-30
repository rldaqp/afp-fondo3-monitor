from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "public" / "data" / "etf_market_snapshot.json"

TICKERS: dict[str, dict[str, str]] = {
    "SPY": {"name": "S&P 500", "factor": "EE. UU."},
    "QQQ": {"name": "Nasdaq 100", "factor": "Tecnología"},
    "EEM": {"name": "Mercados emergentes", "factor": "Emergentes"},
    "EPU": {"name": "Perú", "factor": "Perú"},
    "MCHI": {"name": "China", "factor": "China"},
    "CPER": {"name": "Cobre", "factor": "Cobre"},
}


def _safe_float(value: Any) -> float | None:
    try:
        x = float(value)
        return x if math.isfinite(x) else None
    except Exception:
        return None


def _rsi(series: pd.Series, period: int = 14) -> float | None:
    s = pd.to_numeric(series, errors="coerce").dropna()
    if len(s) < period + 2:
        return None
    delta = s.diff()
    gain = delta.clip(lower=0)
    loss = (-delta.clip(upper=0))
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return _safe_float(rsi.iloc[-1])


def _normalize_index(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if out.index.tz is not None:
        out.index = out.index.tz_convert("America/New_York")
    else:
        out.index = pd.to_datetime(out.index, errors="coerce")
    out = out[~out.index.isna()].sort_index()
    return out


def _volume_profile(day: pd.DataFrame, bins: int = 36) -> dict[str, Any]:
    if day.empty:
        return {"prices": [], "volumes": [], "poc": None, "vah": None, "val": None}

    low = _safe_float(day["Low"].min())
    high = _safe_float(day["High"].max())
    if low is None or high is None or high <= low:
        return {"prices": [], "volumes": [], "poc": None, "vah": None, "val": None}

    edges = np.linspace(low, high, bins + 1)
    centers = (edges[:-1] + edges[1:]) / 2
    volumes = np.zeros(bins, dtype=float)

    typical = (day["High"] + day["Low"] + day["Close"]) / 3
    vols = pd.to_numeric(day["Volume"], errors="coerce").fillna(0)
    idx = np.searchsorted(edges, typical.to_numpy(dtype=float), side="right") - 1
    idx = np.clip(idx, 0, bins - 1)
    for i, v in zip(idx, vols.to_numpy(dtype=float)):
        if math.isfinite(v) and v > 0:
            volumes[int(i)] += float(v)

    if float(volumes.sum()) <= 0:
        return {
            "prices": [round(float(x), 4) for x in centers],
            "volumes": [0.0 for _ in centers],
            "poc": None,
            "vah": None,
            "val": None,
        }

    poc_idx = int(np.argmax(volumes))
    target = float(volumes.sum()) * 0.70
    order = np.argsort(volumes)[::-1]
    selected: list[int] = []
    acc = 0.0
    for i in order:
        selected.append(int(i))
        acc += float(volumes[int(i)])
        if acc >= target:
            break

    val_idx = min(selected)
    vah_idx = max(selected)
    return {
        "prices": [round(float(x), 4) for x in centers],
        "volumes": [float(x) for x in volumes],
        "poc": round(float(centers[poc_idx]), 4),
        "vah": round(float(centers[vah_idx]), 4),
        "val": round(float(centers[val_idx]), 4),
    }


def _relative_volume(all_bars: pd.DataFrame, latest_day: pd.DataFrame) -> float | None:
    if latest_day.empty:
        return None
    dates = pd.Index(all_bars.index.date)
    unique_dates = list(dict.fromkeys(dates))
    if len(unique_dates) < 2:
        return None

    n_bars = len(latest_day)
    today_volume = pd.to_numeric(latest_day["Volume"], errors="coerce").fillna(0).sum()
    comps: list[float] = []
    for d in unique_dates[:-1][-4:]:
        z = all_bars.loc[dates == d].iloc[:n_bars]
        if not z.empty:
            v = pd.to_numeric(z["Volume"], errors="coerce").fillna(0).sum()
            if v > 0:
                comps.append(float(v))
    if not comps:
        return None
    baseline = float(np.median(comps))
    return _safe_float(today_volume / baseline) if baseline > 0 else None


def _trend(close: float | None, ema9: float | None, ema21: float | None) -> str:
    if close is None or ema9 is None or ema21 is None:
        return "sin señal"
    if close > ema9 > ema21:
        return "alcista"
    if close < ema9 < ema21:
        return "bajista"
    return "mixta"


def _series_payload(day: pd.DataFrame, limit: int = 90) -> dict[str, list[Any]]:
    z = day.tail(limit).copy()
    ema9 = z["Close"].ewm(span=9, adjust=False).mean()
    ema21 = z["Close"].ewm(span=21, adjust=False).mean()
    return {
        "time": [ts.isoformat() for ts in z.index],
        "open": [float(x) for x in z["Open"]],
        "high": [float(x) for x in z["High"]],
        "low": [float(x) for x in z["Low"]],
        "close": [float(x) for x in z["Close"]],
        "volume": [float(x) for x in z["Volume"].fillna(0)],
        "ema9": [float(x) for x in ema9],
        "ema21": [float(x) for x in ema21],
    }


def fetch_ticker(symbol: str) -> dict[str, Any]:
    hist = yf.Ticker(symbol).history(
        period="5d",
        interval="5m",
        auto_adjust=False,
        prepost=False,
        actions=False,
    )
    if hist is None or hist.empty:
        raise RuntimeError(f"Sin datos intradía para {symbol}")

    hist = _normalize_index(hist)
    required = ["Open", "High", "Low", "Close", "Volume"]
    missing = [c for c in required if c not in hist.columns]
    if missing:
        raise RuntimeError(f"Faltan columnas {missing} en {symbol}")
    hist = hist.dropna(subset=["Open", "High", "Low", "Close"])
    if hist.empty:
        raise RuntimeError(f"Serie intradía vacía para {symbol}")

    dates = pd.Index(hist.index.date)
    latest_date = dates[-1]
    day = hist.loc[dates == latest_date].copy()
    previous = hist.loc[dates < latest_date]

    current = _safe_float(day["Close"].iloc[-1])
    prev_close = _safe_float(previous["Close"].iloc[-1]) if not previous.empty else None
    change = None
    if current is not None and prev_close not in (None, 0):
        change = current / float(prev_close) - 1

    full_close = hist["Close"]
    ema9 = _safe_float(full_close.ewm(span=9, adjust=False).mean().iloc[-1])
    ema21 = _safe_float(full_close.ewm(span=21, adjust=False).mean().iloc[-1])
    rsi = _rsi(full_close)
    rel_vol = _relative_volume(hist, day)
    profile = _volume_profile(day)

    return {
        "symbol": symbol,
        "price": current,
        "prev_close": prev_close,
        "change": change,
        "rsi14": rsi,
        "ema9": ema9,
        "ema21": ema21,
        "trend": _trend(current, ema9, ema21),
        "relative_volume": rel_vol,
        "session_date": str(latest_date),
        "last_bar": day.index[-1].isoformat(),
        "profile": profile,
        "bars": _series_payload(day),
    }


def _load_previous() -> dict[str, Any]:
    if not OUT.exists():
        return {}
    try:
        return json.loads(OUT.read_text(encoding="utf-8"))
    except Exception:
        return {}


def main() -> None:
    previous = _load_previous()
    previous_map = {x.get("symbol"): x for x in previous.get("tickers", []) if isinstance(x, dict)}
    rows: list[dict[str, Any]] = []
    errors: dict[str, str] = {}

    for symbol, meta in TICKERS.items():
        try:
            item = fetch_ticker(symbol)
        except Exception as exc:
            errors[symbol] = str(exc)
            item = previous_map.get(symbol, {"symbol": symbol, "error": str(exc)})
            item = dict(item)
            item["stale"] = True
        item.update(meta)
        rows.append(item)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "Yahoo Finance vía yfinance. Datos gratuitos; pueden presentar retrasos o interrupciones.",
        "profile_method": (
            "Perfil aproximado: el volumen de cada vela de 5 minutos se asigna al precio típico "
            "(máximo+mínimo+cierre)/3. No es Level II ni volumen exacto ejecutado por precio."
        ),
        "tickers": rows,
        "errors": errors,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Snapshot ETF escrito en {OUT}")
    if errors:
        print("Advertencias:", errors)


if __name__ == "__main__":
    main()
