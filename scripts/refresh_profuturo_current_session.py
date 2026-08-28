from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, time as clock_time
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public" / "data"
LIVE_PATH = PUBLIC / "live_market.json"
LATEST_PATH = PUBLIC / "latest.json"
PENDING_PATH = ROOT / "data" / "rolling90" / "pending_predictions.csv"
LIMA = ZoneInfo("America/Lima")
NY = ZoneInfo("America/New_York")


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"No se pudo cargar {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


base = load_module("profuturo_live_base_refresh", ROOT / "scripts" / "update_live_market_only.py")
hybrid = load_module("profuturo_live_hybrid_refresh", ROOT / "scripts" / "update_live_market_hybrid.py")
fxmod = load_module("profuturo_fx_refresh", ROOT / "scripts" / "patch_dual_rolling30_fx_operational.py")


def finite(v) -> bool:
    try:
        return v is not None and np.isfinite(float(v))
    except Exception:
        return False


def extract_close(raw: pd.DataFrame, ticker: str) -> pd.Series:
    if raw.empty:
        return pd.Series(dtype=float)
    if isinstance(raw.columns, pd.MultiIndex):
        for key in [("Close", ticker), (ticker, "Close")]:
            if key in raw.columns:
                return pd.to_numeric(raw[key], errors="coerce").dropna()
        if "Close" in raw.columns.get_level_values(0):
            block = raw.xs("Close", axis=1, level=0)
            if ticker in block.columns:
                return pd.to_numeric(block[ticker], errors="coerce").dropna()
    if "Close" in raw.columns:
        return pd.to_numeric(raw["Close"], errors="coerce").dropna()
    return pd.Series(dtype=float)


def daily_pair(ticker: str, target: pd.Timestamp) -> tuple[float, float]:
    raw = yf.download(
        ticker,
        period="12d",
        interval="1d",
        auto_adjust=False,
        actions=False,
        progress=False,
        threads=False,
    )
    s = extract_close(raw, ticker)
    if s.empty:
        raise RuntimeError(f"Yahoo diario sin datos para {ticker}")
    idx = pd.to_datetime(s.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    d = pd.DataFrame({"fecha": idx.normalize(), "close": s.to_numpy(float)})
    same = d.loc[d["fecha"].eq(target)]
    prev = d.loc[d["fecha"] < target].tail(1)
    if same.empty or prev.empty:
        raise RuntimeError(f"Yahoo aún no tiene cierre {target.date()} para {ticker}")
    return float(prev.iloc[-1]["close"]), float(same.iloc[-1]["close"])


def classify(value: float) -> str:
    threshold = 0.001
    return "SUBE" if value > threshold else ("BAJA" if value < -threshold else "NEUTRO")


def current_fx(target_iso: str) -> dict:
    fx = fxmod.operational_fx(target_iso)
    return {
        "serie": "USD_PEN",
        "ticker": "BCRP PD04638PD" if not fx["provisional"] else "TUCAMBISTA",
        "timestamp": target_iso,
        "precio_anterior": float(fx["previous_value"]),
        "precio_actual": float(fx["value"]),
        "retorno": float(fx["return"]),
        "retorno_modelo": float(fx["return"]),
        "estado": str(fx["source"]) + " · USADO POR MODELO",
        "usado_modelo": True,
        "fx_provisional": bool(fx["provisional"]),
    }


def current_core_rows(latest: dict, target: pd.Timestamp) -> tuple[list[dict], dict[str, float]]:
    coeff = latest.get("coefficients") or {}
    feature_names = [k for k in coeff if str(k).startswith("ret_") and k != "ret_USD_PEN"]
    series = [k[4:] for k in feature_names]
    if not series:
        raise RuntimeError("latest.json no contiene factores del OLS")

    rows: list[dict] = []
    features: dict[str, float] = {}
    for name in series:
        prev, cur = daily_pair(name, target)
        ret = cur / prev - 1.0
        features[f"ret_{name}"] = ret
        rows.append({
            "serie": name,
            "ticker": name,
            "timestamp": target.date().isoformat(),
            "precio_anterior": prev,
            "precio_actual": cur,
            "retorno": ret,
            "retorno_modelo": ret,
            "estado": "YAHOO · CIERRE SESIÓN ACTUAL · USADO POR MODELO",
            "usado_modelo": True,
        })

    fxrow = current_fx(target.date().isoformat())
    features["ret_USD_PEN"] = float(fxrow["retorno_modelo"])
    rows.append(fxrow)
    return rows, features


def current_experimental_rows(target: pd.Timestamp, fxrow: dict) -> list[dict]:
    mapping = {
        ".INX": "^GSPC",
        "CPER": "CPER",
        "EEM": "EEM",
        "NDX": "^NDX",
    }
    rows: list[dict] = []
    for name, ticker in mapping.items():
        prev, cur = daily_pair(ticker, target)
        ret = cur / prev - 1.0
        rows.append({
            "serie": name,
            "ticker": ticker,
            "timestamp": target.date().isoformat(),
            "precio_anterior": prev,
            "precio_actual": cur,
            "retorno": ret,
            "retorno_modelo": ret,
            "estado": f"YAHOO {ticker} · CIERRE VALIDADO",
            "usado_modelo": True,
            "validado_modelo": True,
        })

    # SPBLSCUP no tiene equivalente Yahoo fiable. Se toma el quote exacto de
    # Google Finance y se exige que su timestamp corresponda a la sesión actual.
    quote = hybrid._google_finance_quote("SPBLSCUP", "INDEXSP")
    stamp = pd.Timestamp(quote.get("timestamp")) if quote.get("timestamp") else pd.NaT
    if pd.isna(stamp):
        raise RuntimeError("SPBLSCUP sin timestamp de sesión")
    if stamp.tzinfo is not None:
        stamp = stamp.tz_convert(NY).tz_localize(None)
    if stamp.date() != target.date():
        raise RuntimeError(f"SPBLSCUP pertenece a {stamp.date()}, no a {target.date()}")
    cur = float(quote["price"])
    ret = quote.get("return")
    if not finite(ret):
        raise RuntimeError("SPBLSCUP sin variación diaria")
    ret = float(ret)
    prev = cur / (1.0 + ret) if abs(1.0 + ret) > 1e-12 else None
    rows.append({
        "serie": "SPBLSCUP",
        "ticker": "SPBLSCUP:INDEXSP",
        "timestamp": target.date().isoformat(),
        "precio_anterior": prev,
        "precio_actual": cur,
        "retorno": ret,
        "retorno_modelo": ret,
        "estado": "GOOGLE FINANCE · SESIÓN ACTUAL VALIDADA",
        "usado_modelo": True,
        "validado_modelo": True,
        "google_stamp": quote.get("timestamp"),
    })

    rows.append({
        "serie": "USD/PEN",
        "ticker": fxrow["ticker"],
        "timestamp": target.date().isoformat(),
        "precio_anterior": fxrow["precio_anterior"],
        "precio_actual": fxrow["precio_actual"],
        "retorno": fxrow["retorno"],
        "retorno_modelo": fxrow["retorno_modelo"],
        "estado": fxrow["estado"],
        "usado_modelo": True,
        "validado_modelo": True,
    })
    return rows


def estimated_base(latest: dict, pending: pd.DataFrame, target: pd.Timestamp) -> float:
    if not pending.empty and "fecha" in pending.columns:
        p = pending.copy()
        p["fecha"] = pd.to_datetime(p["fecha"], errors="coerce").dt.normalize()
        prior = p.loc[p["fecha"] < target].sort_values("fecha")
        if not prior.empty and finite(prior.iloc[-1].get("valor_cuota_estimado")):
            return float(prior.iloc[-1]["valor_cuota_estimado"])
    return float(latest["latest_sbs_vc"])


def main() -> None:
    now_ny = datetime.now(NY)
    target = pd.Timestamp(now_ny.date()).normalize()
    if target.weekday() >= 5:
        print("Fin de semana: no se fuerza una sesión nueva.")
        return
    # Solo corregimos el cierre después de que Nueva York haya terminado. Durante
    # mercado abierto manda el snapshot intradía de 5 minutos.
    if now_ny.time() < clock_time(16, 5):
        print("Mercado NY aún abierto o en ventana de cierre; no se fuerza diario.")
        return

    latest = json.loads(LATEST_PATH.read_text(encoding="utf-8"))
    current = json.loads(LIVE_PATH.read_text(encoding="utf-8")) if LIVE_PATH.exists() else {}
    current_date = str(current.get("signal_date") or "")[:10]
    target_iso = target.date().isoformat()

    rows, features = current_core_rows(latest, target)
    coeff = latest.get("coefficients") or {}
    pred = float(coeff.get("intercept", 0.0))
    for feature, value in features.items():
        if feature in coeff:
            pred += float(coeff[feature]) * float(value)

    pending = pd.read_csv(PENDING_PATH) if PENDING_PATH.exists() else pd.DataFrame()
    vc_base = estimated_base(latest, pending, target)
    vc_est = vc_base * (1.0 + pred)
    fxrow = next(r for r in rows if r["serie"] == "USD_PEN")
    experimental = current_experimental_rows(target, fxrow)

    payload = {
        "generated_at_lima": datetime.now(LIMA).isoformat(),
        "mode": "CIERRE DIARIO",
        "market_open": False,
        "signal_date": target_iso,
        "vc_base": vc_base,
        "vc_estimated": vc_est,
        "return_estimated": pred,
        "signal": classify(pred),
        "assets": rows,
        "action": "CIERRE",
        "engine": "LIVE INDEPENDIENTE · CIERRE ACTUAL REFRESCADO",
        "fx_source": "BCRP" if not fxrow.get("fx_provisional") else "TUCAMBISTA PROVISIONAL",
        "fx_provisional": bool(fxrow.get("fx_provisional")),
        "fx_rule": "Rolling 30: BCRP PD04638PD oficial; si aún no existe la fecha, TuCambista midpoint provisional.",
        "experimental_assets": experimental,
        "experimental_watchlist": [".INX", "CPER", "EEM", "NDX", "SPBLSCUP", "USD/PEN"],
        "experimental_note": "Factores de la sesión actual verificados al cierre; SPBLSCUP exige timestamp Google de la misma fecha.",
        "new_ticker_validation": {
            "signal_date": target_iso,
            "status": "OK",
            "problems": [],
            "rule": "Todos los factores del Modelo B deben corresponder a la misma sesión.",
        },
        "session_refresh": {
            "previous_signal_date": current_date,
            "corrected_to": target_iso,
            "reason": "El snapshot de cierre no puede retroceder a la última fila almacenada en markets.csv.",
        },
    }
    LIVE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "previous_signal_date": current_date,
        "signal_date": target_iso,
        "assets": {r["serie"]: {"price": r["precio_actual"], "return": r["retorno"]} for r in rows},
        "experimental": {r["serie"]: {"price": r["precio_actual"], "return": r["retorno"]} for r in experimental},
        "vc_estimated": vc_est,
        "return_estimated": pred,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
