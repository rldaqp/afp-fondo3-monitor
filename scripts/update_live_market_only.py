from __future__ import annotations

import importlib.util
import json
from datetime import datetime, time as clock_time
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "rolling90"
PUBLIC_DATA = ROOT / "public" / "data"
ENGINE_PATH = ROOT / "scripts" / "build_rolling90_pages.py"
LATEST_PATH = PUBLIC_DATA / "latest.json"
LIVE_PATH = PUBLIC_DATA / "live_market.json"
PENDING_PATH = DATA / "pending_predictions.csv"
MARKETS_PATH = DATA / "markets.csv"

spec = importlib.util.spec_from_file_location("rolling90_live_engine", ENGINE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError(f"No se pudo cargar {ENGINE_PATH}")
engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)

ASSETS = list(engine.ASSETS)
FEATURES = list(engine.FEATURES)
THRESHOLD = float(engine.THRESHOLD)
NY = ZoneInfo("America/New_York")
LIMA = ZoneInfo("America/Lima")


def _market_open_now() -> bool:
    now = datetime.now(NY)
    return now.weekday() < 5 and clock_time(9, 30) <= now.time() < clock_time(16, 10)


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    frame = pd.read_csv(path)
    if "fecha" in frame.columns:
        frame["fecha"] = pd.to_datetime(frame["fecha"], errors="coerce")
    return frame


def _extract_close(raw: pd.DataFrame, ticker: str) -> pd.Series:
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


def _classify(value: float) -> str:
    if value > THRESHOLD:
        return "SUBE"
    if value < -THRESHOLD:
        return "BAJA"
    return "NEUTRO"


def _last_daily_rows(markets: pd.DataFrame, signal_date: pd.Timestamp) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    complete = markets.dropna(subset=ASSETS).sort_values("fecha")
    if complete.empty:
        raise RuntimeError("No existe cierre diario guardado")
    last_date = pd.Timestamp(complete.iloc[-1]["fecha"])
    for name in ASSETS:
        valid = markets.loc[markets[name].notna() & (markets["fecha"] <= last_date), ["fecha", name]].sort_values("fecha")
        cur = valid.iloc[-1]
        prev = valid.iloc[-2] if len(valid) >= 2 else cur
        ret = float(cur[name] / prev[name] - 1.0) if float(prev[name]) else 0.0
        rows.append({
            "serie": name,
            "ticker": name,
            "timestamp": last_date.strftime("%Y-%m-%d"),
            "precio_anterior": float(prev[name]),
            "precio_actual": float(cur[name]),
            "retorno": ret,
            "retorno_modelo": ret,
            "estado": "CIERRE DIARIO YAHOO · USADO POR MODELO",
            "usado_modelo": True,
        })

    fx_same = markets.loc[(markets["fecha"] == last_date) & markets["USD_PEN"].notna(), ["fecha", "USD_PEN"]].sort_values("fecha")
    fx_prev = markets.loc[(markets["fecha"] < last_date) & markets["USD_PEN"].notna(), ["fecha", "USD_PEN"]].sort_values("fecha")
    if not fx_same.empty:
        cur = fx_same.iloc[-1]
        prev = fx_prev.iloc[-1] if not fx_prev.empty else cur
        ret = float(cur["USD_PEN"] / prev["USD_PEN"] - 1.0) if float(prev["USD_PEN"]) else 0.0
        rows.append({
            "serie": "USD_PEN", "ticker": "BCRP PD04646PD", "timestamp": last_date.strftime("%Y-%m-%d"),
            "precio_anterior": float(prev["USD_PEN"]), "precio_actual": float(cur["USD_PEN"]),
            "retorno": ret, "retorno_modelo": ret,
            "estado": "BCRP MISMA FECHA · USADO POR MODELO", "usado_modelo": True,
        })
    else:
        last_fx = fx_prev.iloc[-1] if not fx_prev.empty else None
        rows.append({
            "serie": "USD_PEN", "ticker": "BCRP PD04646PD",
            "timestamp": None if last_fx is None else pd.Timestamp(last_fx["fecha"]).strftime("%Y-%m-%d"),
            "precio_anterior": None if last_fx is None else float(last_fx["USD_PEN"]),
            "precio_actual": None if last_fx is None else float(last_fx["USD_PEN"]),
            "retorno": 0.0, "retorno_modelo": 0.0,
            "estado": "BCRP REZAGADO · MODELO USA 0 %", "usado_modelo": True,
        })
    return rows


def _fx_visual_reference(raw: pd.DataFrame, signal_date: pd.Timestamp) -> tuple[float | None, float, str | None]:
    ser = _extract_close(raw, "PEN=X")
    if ser.empty:
        return None, 0.0, None
    current = float(ser.iloc[-1])
    ts = pd.Timestamp(ser.index[-1])
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    ts_ny = ts.tz_convert(NY)

    idx = pd.to_datetime(ser.index)
    tmp = pd.DataFrame({"ts": idx, "price": ser.to_numpy(float)})
    if getattr(tmp["ts"].dt, "tz", None) is not None:
        tmp["date"] = tmp["ts"].dt.tz_convert(NY).dt.date
    else:
        tmp["date"] = tmp["ts"].dt.date
    earlier = tmp.loc[tmp["date"] < signal_date.date()]
    previous = float(earlier.iloc[-1]["price"]) if not earlier.empty else current
    ret = current / previous - 1.0 if previous else 0.0
    return current, ret, ts_ny.isoformat()


def _build_live(latest: dict, markets: pd.DataFrame, pending: pd.DataFrame) -> dict:
    now_lima = datetime.now(LIMA)
    now_ny = datetime.now(NY)
    open_now = _market_open_now()

    if not open_now:
        complete = markets.dropna(subset=ASSETS).sort_values("fecha")
        signal_date = pd.Timestamp(complete.iloc[-1]["fecha"])
        return {
            "generated_at_lima": now_lima.isoformat(),
            "mode": "CIERRE DIARIO",
            "market_open": False,
            "signal_date": signal_date.strftime("%Y-%m-%d"),
            "vc_estimated": float(latest["latest_estimated_vc"]),
            "return_estimated": float(latest["latest_return_estimated"]),
            "signal": str(latest["signal"]),
            "assets": _last_daily_rows(markets, signal_date),
            "action": "CIERRE",
            "engine": "LIVE INDEPENDIENTE",
            "fx_rule": "Modelo: BCRP; si falta la fecha, USD/PEN = 0 % provisional. PEN=X es solo referencia visual.",
        }

    tickers = [*ASSETS, "PEN=X"]
    raw = yf.download(
        tickers=tickers,
        period="5d",
        interval="5m",
        auto_adjust=False,
        actions=False,
        prepost=False,
        progress=False,
        group_by="column",
        threads=False,
    )
    if raw.empty:
        raise RuntimeError("Yahoo intradía no devolvió datos")

    signal_date = pd.Timestamp(now_ny.date())
    features: dict[str, float] = {}
    rows: list[dict[str, object]] = []

    for name in ASSETS:
        ser = _extract_close(raw, name)
        if ser.empty:
            raise RuntimeError(f"Yahoo intradía no devolvió {name}")
        current = float(ser.iloc[-1])
        ts = pd.Timestamp(ser.index[-1])
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        ts = ts.tz_convert(NY)
        prevs = markets.loc[(markets["fecha"] < signal_date) & markets[name].notna(), ["fecha", name]].sort_values("fecha")
        if prevs.empty:
            raise RuntimeError(f"No existe cierre previo para {name}")
        previous = float(prevs.iloc[-1][name])
        ret = current / previous - 1.0
        features[f"ret_{name}"] = ret
        rows.append({
            "serie": name, "ticker": name, "timestamp": ts.isoformat(),
            "precio_anterior": previous, "precio_actual": current,
            "retorno": ret, "retorno_modelo": ret,
            "estado": "INTRADÍA YAHOO · USADO POR MODELO", "usado_modelo": True,
        })

    # USD/PEN del MODELO: BCRP de la misma fecha si ya existe; de lo contrario 0 %.
    # PEN=X se muestra solo como referencia visual y jamás sustituye al BCRP en OLS.
    bcrp = pd.DataFrame()
    try:
        bcrp = engine.load_bcrp()
        bcrp["fecha"] = pd.to_datetime(bcrp["fecha"], errors="coerce")
    except Exception:
        bcrp = pd.DataFrame(columns=["fecha", "USD_PEN"])

    if bcrp.empty:
        bcrp = markets.loc[markets["USD_PEN"].notna(), ["fecha", "USD_PEN"]].copy()

    same = bcrp.loc[(bcrp["fecha"] == signal_date) & bcrp["USD_PEN"].notna()].sort_values("fecha")
    previous_fx_rows = bcrp.loc[(bcrp["fecha"] < signal_date) & bcrp["USD_PEN"].notna()].sort_values("fecha")

    if not same.empty:
        cur_fx = float(same.iloc[-1]["USD_PEN"])
        prev_fx = float(previous_fx_rows.iloc[-1]["USD_PEN"]) if not previous_fx_rows.empty else cur_fx
        fx_ret = cur_fx / prev_fx - 1.0 if prev_fx else 0.0
        features["ret_USD_PEN"] = fx_ret
        rows.append({
            "serie": "USD_PEN", "ticker": "BCRP PD04646PD", "timestamp": signal_date.strftime("%Y-%m-%d"),
            "precio_anterior": prev_fx, "precio_actual": cur_fx,
            "retorno": fx_ret, "retorno_modelo": fx_ret,
            "estado": "BCRP MISMA FECHA · USADO POR MODELO", "usado_modelo": True,
        })
        fx_fresh = True
    else:
        features["ret_USD_PEN"] = 0.0
        ref_price, ref_ret, ref_ts = _fx_visual_reference(raw, signal_date)
        prev_fx = float(previous_fx_rows.iloc[-1]["USD_PEN"]) if not previous_fx_rows.empty else None
        rows.append({
            "serie": "USD_PEN", "ticker": "PEN=X referencia", "timestamp": ref_ts,
            "precio_anterior": prev_fx, "precio_actual": ref_price,
            "retorno": ref_ret, "retorno_modelo": 0.0,
            "estado": "YAHOO PEN=X · SOLO REFERENCIA · MODELO USA 0 %", "usado_modelo": False,
        })
        fx_fresh = False

    beta = latest["coefficients"]
    pred = float(beta["intercept"] + sum(float(beta[f]) * float(features[f]) for f in FEATURES))

    prior = pending.loc[pending["fecha"] < signal_date].sort_values("fecha") if not pending.empty else pd.DataFrame()
    vc_base = float(prior.iloc[-1]["valor_cuota_estimado"]) if not prior.empty else float(latest["latest_sbs_vc"])
    vc_est = vc_base * (1.0 + pred)

    return {
        "generated_at_lima": now_lima.isoformat(),
        "mode": "INTRADÍA PROVISIONAL",
        "market_open": True,
        "signal_date": signal_date.strftime("%Y-%m-%d"),
        "vc_base": vc_base,
        "vc_estimated": vc_est,
        "return_estimated": pred,
        "signal": _classify(pred),
        "assets": rows,
        "action": "ESPERAR",
        "engine": "LIVE INDEPENDIENTE",
        "fx_fresh": fx_fresh,
        "fx_rule": "Paridad notebook: BCRP; si falta la fecha, retorno USD/PEN del modelo = 0 % provisional. PEN=X es solo referencia visual.",
        "note": "Snapshot intradía independiente del modelo pesado; puede cambiar hasta el cierre.",
    }


def main() -> None:
    if not LATEST_PATH.exists():
        raise RuntimeError("Falta public/data/latest.json")
    latest = json.loads(LATEST_PATH.read_text(encoding="utf-8"))
    markets = _read_csv(MARKETS_PATH)
    pending = _read_csv(PENDING_PATH)
    if markets.empty:
        raise RuntimeError("Falta data/rolling90/markets.csv")

    try:
        payload = _build_live(latest, markets, pending)
    except Exception as exc:
        previous: dict = {}
        if LIVE_PATH.exists():
            try:
                previous = json.loads(LIVE_PATH.read_text(encoding="utf-8"))
            except Exception:
                previous = {}
        payload = {
            "generated_at_lima": datetime.now(LIMA).isoformat(),
            "mode": "MERCADO ABIERTO · INTRADÍA NO DISPONIBLE" if _market_open_now() else "CIERRE DIARIO · ACTUALIZACIÓN NO DISPONIBLE",
            "market_open": _market_open_now(),
            "signal_date": datetime.now(NY).date().isoformat() if _market_open_now() else latest.get("latest_market_date"),
            "vc_estimated": float(latest["latest_estimated_vc"]),
            "return_estimated": float(latest["latest_return_estimated"]),
            "signal": str(latest["signal"]),
            "assets": previous.get("assets", []),
            "action": "ESPERAR" if _market_open_now() else "CIERRE",
            "engine": "LIVE INDEPENDIENTE",
            "warning": f"{type(exc).__name__}: {exc}",
            "fx_rule": "BCRP para el modelo; PEN=X solo referencia visual.",
        }

    LIVE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
