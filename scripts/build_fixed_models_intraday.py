from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "public" / "data" / "fixed_models_2026.json"
LIVE = ROOT / "public" / "data" / "live_market.json"
OUT = ROOT / "public" / "data" / "fixed_models_intraday.json"
LIMA = ZoneInfo("America/Lima")

FACTORS = ["SPY", "EEM", "MCHI", "QQQ", "SPBLSCUP"]


def finite(v):
    try:
        return v is not None and np.isfinite(float(v))
    except Exception:
        return False


def qqq_snapshot():
    # fast_info is the lightest path. Fall back to a short intraday series.
    try:
        t = yf.Ticker("QQQ")
        info = t.fast_info
        cur = float(info["last_price"])
        prev = float(info["previous_close"])
        if finite(cur) and finite(prev) and prev > 0:
            return prev, cur, cur / prev - 1.0, "YAHOO QQQ · FAST_INFO"
    except Exception as exc:
        print("QQQ fast_info fallback:", type(exc).__name__, exc)

    raw = yf.download("QQQ", period="5d", interval="5m", auto_adjust=False,
                      actions=False, progress=False, threads=False)
    if raw.empty:
        raise RuntimeError("Yahoo no devolvió QQQ intradía")
    if isinstance(raw.columns, pd.MultiIndex):
        if ("Close", "QQQ") in raw.columns:
            s = pd.to_numeric(raw[("Close", "QQQ")], errors="coerce").dropna()
        elif "Close" in raw.columns.get_level_values(0):
            s = pd.to_numeric(raw.xs("Close", axis=1, level=0).iloc[:, 0], errors="coerce").dropna()
        else:
            raise RuntimeError("QQQ sin columna Close")
    else:
        s = pd.to_numeric(raw["Close"], errors="coerce").dropna()
    if s.empty:
        raise RuntimeError("QQQ intradía vacío")
    cur = float(s.iloc[-1])

    daily = yf.download("QQQ", period="10d", interval="1d", auto_adjust=False,
                        actions=False, progress=False, threads=False)
    if isinstance(daily.columns, pd.MultiIndex):
        if ("Close", "QQQ") in daily.columns:
            d = pd.to_numeric(daily[("Close", "QQQ")], errors="coerce").dropna()
        else:
            d = pd.to_numeric(daily.xs("Close", axis=1, level=0).iloc[:, 0], errors="coerce").dropna()
    else:
        d = pd.to_numeric(daily["Close"], errors="coerce").dropna()
    if d.empty:
        raise RuntimeError("QQQ diario vacío")
    # If today's daily candle is already present, previous close is penultimate.
    today = pd.Timestamp.now(tz=LIMA).date()
    dates = pd.to_datetime(d.index)
    if getattr(dates, "tz", None) is not None:
        dates = dates.tz_localize(None)
    if dates[-1].date() == today and len(d) >= 2:
        prev = float(d.iloc[-2])
    else:
        prev = float(d.iloc[-1])
    return prev, cur, cur / prev - 1.0, "YAHOO QQQ · 5M"


def live_factor_map(live):
    rows = list(live.get("assets", [])) + list(live.get("experimental_assets", []))
    out = {}
    for row in rows:
        name = str(row.get("serie") or "")
        if name not in {"SPY", "EEM", "MCHI", "SPBLSCUP"}:
            continue
        if not (finite(row.get("precio_actual")) and finite(row.get("precio_anterior"))):
            continue
        # Prefer the experimental validated SPBLSCUP quote when there are duplicates.
        score = 2 if name == "SPBLSCUP" and bool(row.get("validado_modelo", True)) else 1
        old = out.get(name)
        if old is None or score >= old["_score"]:
            cur = float(row["precio_actual"])
            prev = float(row["precio_anterior"])
            ret = float(row.get("retorno")) if finite(row.get("retorno")) else cur / prev - 1.0
            out[name] = {
                "_score": score,
                "precio_anterior": prev,
                "precio_actual": cur,
                "retorno": ret,
                "source": str(row.get("estado") or row.get("ticker") or "LIVE"),
                "timestamp": str(row.get("timestamp") or live.get("signal_date") or "")[:10],
            }
    return out


def main():
    if not BASE.exists():
        raise RuntimeError(f"Falta {BASE}")
    base = json.loads(BASE.read_text(encoding="utf-8"))
    live = json.loads(LIVE.read_text(encoding="utf-8")) if LIVE.exists() else {}

    fmap = live_factor_map(live)
    qprev, qcur, qret, qsrc = qqq_snapshot()
    fmap["QQQ"] = {
        "_score": 3, "precio_anterior": qprev, "precio_actual": qcur,
        "retorno": qret, "source": qsrc,
        "timestamp": str(live.get("signal_date") or datetime.now(LIMA).date())[:10],
    }

    # Fall back to the latest daily close only when a live factor is unavailable.
    rows = base.get("rows") or []
    if not rows:
        raise RuntimeError("fixed_models_2026.json sin filas")
    last = rows[-1]
    prev = rows[-2] if len(rows) >= 2 else {}
    for f in FACTORS:
        if f in fmap:
            continue
        if finite(last.get(f)):
            p = float(prev.get(f)) if finite(prev.get(f)) else float(last[f])
            c = float(last[f])
            fmap[f] = {
                "_score": 0, "precio_anterior": p, "precio_actual": c,
                "retorno": (c / p - 1.0) if p else 0.0,
                "source": "ÚLTIMO CIERRE DISPONIBLE · FALLBACK",
                "timestamp": str(last.get("fecha") or ""),
            }

    missing = [f for f in FACTORS if f not in fmap]
    if missing:
        raise RuntimeError("Faltan factores: " + ", ".join(missing))

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

    signal_date = str(live.get("signal_date") or last.get("fecha") or "")[:10]
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
        tickers.append({
            "ticker": f,
            "timestamp": x["timestamp"],
            "price_previous": x["precio_anterior"],
            "price_current": x["precio_actual"],
            "return": x["retorno"],
            "level_coefficient": float(lc[f]),
            "return_coefficient": float(rc[f]),
            "level_contribution": level_contrib[f],
            "return_contribution": return_contrib[f],
            "level_weight_abs_pct": (abs(level_contrib[f]) / den_l * 100.0) if den_l else None,
            "return_weight_abs_pct": (abs(return_contrib[f]) / den_r * 100.0) if den_r else None,
            "source": x["source"],
        })

    payload = {
        "generated_at_lima": datetime.now(LIMA).isoformat(),
        "signal_date": signal_date,
        "mode": str(live.get("mode") or "SNAPSHOT"),
        "market_open": bool(live.get("market_open")),
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
        "source_live": "public/data/live_market.json + Yahoo Finance QQQ",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "signal_date": signal_date,
        "mode": payload["mode"],
        "levels": vc_levels,
        "returns_vc": vc_returns,
        "returns": ret_est,
        "tickers": {x["ticker"]: x["price_current"] for x in tickers},
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
