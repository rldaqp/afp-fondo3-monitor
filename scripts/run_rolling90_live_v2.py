from __future__ import annotations

import importlib.util
import io
import json
import re
import time
from datetime import datetime, time as clock_time
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "scripts" / "build_rolling90_pages.py"
DATA = ROOT / "data" / "rolling90"
PUBLIC_DATA = ROOT / "public" / "data"
PUBLIC_DATA.mkdir(parents=True, exist_ok=True)

spec = importlib.util.spec_from_file_location("rolling90_engine_v2", ENGINE)
if spec is None or spec.loader is None:
    raise RuntimeError(f"No se pudo cargar {ENGINE}")
engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)

_original_download_yahoo = engine.download_yahoo
_original_download_sbs = engine.download_sbs
_original_load_bcrp = engine.load_bcrp
_original_run_model = engine.run_model

NY = ZoneInfo("America/New_York")
LIMA = ZoneInfo("America/Lima")
EQUITY_FEATURES = [f"ret_{x}" for x in engine.ASSETS]


def _get_text(url: str, attempts: int = 3) -> str:
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            response = requests.get(url, headers=engine.HEADERS, timeout=45)
            response.raise_for_status()
            if response.text.strip():
                return response.text
        except Exception as exc:
            last = exc
            if attempt + 1 < attempts:
                time.sleep(1 + attempt)
    raise RuntimeError(f"No respondió {url}: {type(last).__name__}: {last}")


def _parse_sbs_daily_blocks() -> pd.DataFrame:
    response = requests.get(engine.SBS_DAILY, headers=engine.HEADERS, timeout=45)
    response.raise_for_status()
    soup = BeautifulSoup(response.content, "lxml")
    rows: list[dict[str, object]] = []
    for table in soup.find_all("table"):
        text = " ".join(table.stripped_strings)
        dates = list(dict.fromkeys(re.findall(r"\d{2}/\d{2}/\d{4}", text)))
        if len(dates) != 1:
            continue
        fecha = pd.to_datetime(dates[0], format="%d/%m/%Y")
        for tr in table.find_all("tr"):
            if tr.find_parent("table") is not table:
                continue
            cells = tr.find_all(["th", "td"], recursive=False)
            values = [" ".join(c.get_text(" ", strip=True).split()) for c in cells]
            if values and engine.norm(values[0]) == "profuturo" and len(values) >= 10:
                vc = engine.parse_num(values[9])
                if vc is not None:
                    rows.append({"fecha": fecha, "valor_cuota": float(vc)})
                break
    if not rows:
        raise RuntimeError("No se pudo extraer la tabla diaria SBS")
    out = pd.DataFrame(rows)
    out["fecha"] = pd.to_datetime(out["fecha"], errors="coerce")
    out["valor_cuota"] = pd.to_numeric(out["valor_cuota"], errors="coerce")
    return out.dropna().sort_values("fecha").drop_duplicates("fecha", keep="last")


def download_sbs_resilient() -> tuple[pd.DataFrame, list[str]]:
    base, warnings = _original_download_sbs()
    try:
        daily = _parse_sbs_daily_blocks()
        base = pd.concat([base, daily], ignore_index=True)
        base["fecha"] = pd.to_datetime(base["fecha"], errors="coerce")
        base["valor_cuota"] = pd.to_numeric(base["valor_cuota"], errors="coerce")
        base = base.dropna().sort_values("fecha").drop_duplicates("fecha", keep="last")
    except Exception as exc:
        warnings.append(f"SBS diaria: {type(exc).__name__}: {exc}")
    return base.reset_index(drop=True), warnings


def _market_open_now() -> bool:
    now = datetime.now(NY)
    return now.weekday() < 5 and clock_time(9, 30) <= now.time() < clock_time(16, 10)


def _download_stooq_ticker(ticker: str) -> pd.DataFrame:
    symbols = {"SPY": "spy.us", "NEM": "nem.us", "FCX": "fcx.us", "EPU": "epu.us", "MCHI": "mchi.us"}
    start = engine.START.strftime("%Y%m%d")
    end = pd.Timestamp.now(tz="America/Lima").strftime("%Y%m%d")
    text = _get_text(f"https://stooq.com/q/d/l/?s={symbols[ticker]}&d1={start}&d2={end}&i=d")
    raw = pd.read_csv(io.StringIO(text))
    out = raw[["Date", "Close"]].copy()
    out.columns = ["fecha", ticker]
    out["fecha"] = pd.to_datetime(out["fecha"], errors="coerce")
    out[ticker] = pd.to_numeric(out[ticker], errors="coerce")
    return out.dropna().sort_values("fecha").drop_duplicates("fecha", keep="last")


def _download_stooq() -> pd.DataFrame:
    frames = [_download_stooq_ticker(t) for t in engine.ASSETS]
    out = frames[0]
    for frame in frames[1:]:
        out = out.merge(frame, on="fecha", how="outer")
    return out.sort_values("fecha").drop_duplicates("fecha", keep="last")


def download_market_resilient() -> pd.DataFrame:
    """Yahoo es principal. Stooq solo agrega fechas posteriores al último Yahoo guardado."""
    try:
        out = _original_download_yahoo()
        # El cierre diario de hoy no es definitivo mientras NY siga abierto.
        if _market_open_now():
            today_ny = pd.Timestamp(datetime.now(NY).date())
            out = out.loc[pd.to_datetime(out["fecha"]) < today_ny].copy()
        print("Mercado diario: Yahoo Finance")
        return out
    except Exception as exc:
        print(f"Yahoo diario falló: {type(exc).__name__}: {exc}")
        stooq = _download_stooq()
        saved = engine.read_saved(DATA / "markets.csv")
        if not saved.empty:
            saved["fecha"] = pd.to_datetime(saved["fecha"], errors="coerce")
            yahoo_tail = saved.loc[saved[engine.ASSETS].notna().any(axis=1), "fecha"].max()
            if pd.notna(yahoo_tail):
                stooq = stooq.loc[stooq["fecha"] > pd.Timestamp(yahoo_tail)].copy()
        if _market_open_now():
            today_ny = pd.Timestamp(datetime.now(NY).date())
            stooq = stooq.loc[stooq["fecha"] < today_ny].copy()
        print("Stooq usado solo para cola posterior al histórico guardado")
        return stooq if not stooq.empty else pd.DataFrame(columns=["fecha", *engine.ASSETS])


def _download_yahoo_pen_daily() -> pd.DataFrame:
    end = (pd.Timestamp.now(tz="America/Lima") + pd.Timedelta(days=2)).strftime("%Y-%m-%d")
    raw = engine.yf.download("PEN=X", start=engine.START.strftime("%Y-%m-%d"), end=end,
                             auto_adjust=False, actions=False, progress=False, threads=False)
    if raw.empty:
        raise RuntimeError("Yahoo no devolvió PEN=X")
    if isinstance(raw.columns, pd.MultiIndex):
        if ("Close", "PEN=X") in raw.columns:
            close = raw[("Close", "PEN=X")]
        elif "Close" in raw.columns.get_level_values(0):
            close = raw.xs("Close", axis=1, level=0).iloc[:, 0]
        else:
            raise RuntimeError("Sin Close para PEN=X")
    else:
        close = raw["Close"]
    idx = pd.to_datetime(raw.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    out = pd.DataFrame({"fecha": idx, "USD_PEN_YAHOO": np.asarray(pd.to_numeric(close, errors="coerce"), float)})
    return out.dropna().sort_values("fecha").drop_duplicates("fecha", keep="last")


def load_fx_resilient() -> pd.DataFrame:
    """BCRP forma el histórico. Yahoo PEN=X solo cubre la cola posterior al último BCRP."""
    try:
        bcrp = _original_load_bcrp().copy()
    except Exception as exc:
        print(f"BCRP falló: {type(exc).__name__}: {exc}")
        bcrp = pd.DataFrame(columns=["fecha", "USD_PEN"])
    try:
        yahoo = _download_yahoo_pen_daily()
    except Exception as exc:
        print(f"Yahoo PEN=X falló: {type(exc).__name__}: {exc}")
        yahoo = pd.DataFrame(columns=["fecha", "USD_PEN_YAHOO"])

    if bcrp.empty:
        if yahoo.empty:
            raise RuntimeError("No hay USD/PEN de BCRP ni Yahoo")
        return yahoo.rename(columns={"USD_PEN_YAHOO": "USD_PEN"})[["fecha", "USD_PEN"]]

    bcrp["fecha"] = pd.to_datetime(bcrp["fecha"], errors="coerce")
    last_bcrp = bcrp["fecha"].max()
    tail = yahoo.loc[yahoo["fecha"] > last_bcrp, ["fecha", "USD_PEN_YAHOO"]].copy() if not yahoo.empty else pd.DataFrame()
    if not tail.empty:
        tail = tail.rename(columns={"USD_PEN_YAHOO": "USD_PEN"})
        out = pd.concat([bcrp[["fecha", "USD_PEN"]], tail[["fecha", "USD_PEN"]]], ignore_index=True)
    else:
        out = bcrp[["fecha", "USD_PEN"]].copy()
    print(f"USD/PEN: histórico BCRP hasta {last_bcrp:%Y-%m-%d}; Yahoo solo cola posterior")
    return out.dropna().sort_values("fecha").drop_duplicates("fecha", keep="last")


def run_model_compatible(sbs: pd.DataFrame, market: pd.DataFrame):
    """Mantiene entrenamiento completo; solo la cola pendiente puede usar FX 0% si todo respaldo falló."""
    m = market.copy()
    last_sbs = pd.Timestamp(sbs.sort_values("fecha").iloc[-1]["fecha"])
    pending_mask = m["fecha"].gt(last_sbs) & m[EQUITY_FEATURES].notna().all(axis=1) & m["ret_USD_PEN"].isna()
    m.loc[pending_mask, "ret_USD_PEN"] = 0.0
    return _original_run_model(sbs, m)


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


def _write_signals() -> None:
    hist = engine.read_saved(DATA / "historical_predictions.csv")
    pending = engine.read_saved(DATA / "pending_predictions.csv")
    sbs = engine.read_saved(DATA / "sbs_profuturo_f3.csv")
    records: list[dict[str, object]] = []
    if not hist.empty and not sbs.empty:
        sbs = sbs.sort_values("fecha").drop_duplicates("fecha", keep="last")
        sbs["vc_previo"] = pd.to_numeric(sbs["valor_cuota"], errors="coerce").shift(1)
        h = hist.merge(sbs[["fecha", "vc_previo"]], on="fecha", how="left")
        h["vc_estimado"] = h["vc_previo"] * (1 + pd.to_numeric(h["ret_estimado"], errors="coerce"))
        for _, r in h.dropna(subset=["fecha", "ret_estimado"]).iterrows():
            records.append({"fecha": pd.Timestamp(r.fecha).strftime("%Y-%m-%d"), "ret_estimado": float(r.ret_estimado),
                            "senal": str(r.senal), "vc_real": float(r.valor_cuota),
                            "vc_estimado": None if pd.isna(r.vc_estimado) else float(r.vc_estimado), "tipo": "HISTORICO"})
    if not pending.empty:
        for _, r in pending.dropna(subset=["fecha", "ret_estimado"]).iterrows():
            records.append({"fecha": pd.Timestamp(r.fecha).strftime("%Y-%m-%d"), "ret_estimado": float(r.ret_estimado),
                            "senal": str(r.senal), "vc_real": None, "vc_estimado": float(r.valor_cuota_estimado), "tipo": "PENDIENTE"})
    records.sort(key=lambda x: x["fecha"])
    (PUBLIC_DATA / "signals.json").write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")


def _live_snapshot() -> None:
    latest = json.loads((PUBLIC_DATA / "latest.json").read_text(encoding="utf-8"))
    markets = engine.read_saved(DATA / "markets.csv")
    pending = engine.read_saved(DATA / "pending_predictions.csv")
    now_ny = datetime.now(NY)
    now_lima = datetime.now(LIMA)
    open_now = _market_open_now()
    rows: list[dict[str, object]] = []

    if not open_now:
        complete = markets.dropna(subset=engine.ASSETS).sort_values("fecha")
        signal_date = pd.Timestamp(complete.iloc[-1]["fecha"])
        for name in engine.ASSETS:
            valid = markets.loc[markets[name].notna() & (markets["fecha"] <= signal_date), ["fecha", name]].sort_values("fecha")
            cur, prev = valid.iloc[-1], valid.iloc[-2]
            rows.append({"serie": name, "ticker": name, "timestamp": signal_date.strftime("%Y-%m-%d"),
                         "precio_anterior": float(prev[name]), "precio_actual": float(cur[name]),
                         "retorno": float(cur[name] / prev[name] - 1), "estado": "CIERRE DIARIO"})
        payload = {"generated_at_lima": now_lima.isoformat(), "mode": "CIERRE DIARIO", "market_open": False,
                   "signal_date": signal_date.strftime("%Y-%m-%d"), "vc_estimated": latest["latest_estimated_vc"],
                   "return_estimated": latest["latest_return_estimated"], "signal": latest["signal"], "assets": rows}
        (PUBLIC_DATA / "live_market.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return

    tickers = [*engine.ASSETS, "PEN=X"]
    raw = engine.yf.download(tickers=tickers, period="5d", interval="5m", auto_adjust=False, actions=False,
                             prepost=False, progress=False, group_by="column", threads=False)
    if raw.empty:
        raise RuntimeError("Yahoo intradía no devolvió datos")

    signal_date = pd.Timestamp(now_ny.date())
    features: dict[str, float] = {}
    for name in engine.ASSETS:
        ser = _extract_close(raw, name)
        current = float(ser.iloc[-1])
        ts = pd.Timestamp(ser.index[-1])
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        ts = ts.tz_convert(NY)
        prevs = markets.loc[(markets["fecha"] < signal_date) & markets[name].notna(), ["fecha", name]].sort_values("fecha")
        prev = float(prevs.iloc[-1][name])
        ret = current / prev - 1
        features[f"ret_{name}"] = ret
        rows.append({"serie": name, "ticker": name, "timestamp": ts.isoformat(), "precio_anterior": prev,
                     "precio_actual": current, "retorno": ret, "estado": "INTRADÍA YAHOO"})

    # USD/PEN: BCRP manda si ya publicó hoy; Yahoo PEN=X solo si aún no existe esa fecha.
    try:
        bcrp = _original_load_bcrp()
    except Exception:
        bcrp = pd.DataFrame(columns=["fecha", "USD_PEN"])
    bcrp_today = bcrp.loc[pd.to_datetime(bcrp["fecha"]).eq(signal_date)] if not bcrp.empty else pd.DataFrame()
    if not bcrp_today.empty:
        cur_fx = float(bcrp_today.iloc[-1]["USD_PEN"])
        prev_fx = float(bcrp.loc[pd.to_datetime(bcrp["fecha"]) < signal_date].sort_values("fecha").iloc[-1]["USD_PEN"])
        fx_state = "BCRP MISMA FECHA"
        fx_ts = signal_date.strftime("%Y-%m-%d")
    else:
        fx_ser = _extract_close(raw, "PEN=X")
        cur_fx = float(fx_ser.iloc[-1])
        fx_ts_value = pd.Timestamp(fx_ser.index[-1])
        if fx_ts_value.tzinfo is None:
            fx_ts_value = fx_ts_value.tz_localize("UTC")
        fx_ts = fx_ts_value.tz_convert(NY).isoformat()
        if not bcrp.empty:
            prev_fx = float(bcrp.loc[pd.to_datetime(bcrp["fecha"]) < signal_date].sort_values("fecha").iloc[-1]["USD_PEN"])
        else:
            prev_fx = float(markets.loc[(markets["fecha"] < signal_date) & markets["USD_PEN"].notna()].sort_values("fecha").iloc[-1]["USD_PEN"])
        fx_state = "YAHOO PEN=X · RESPALDO INTRADÍA"
    fx_ret = cur_fx / prev_fx - 1
    features["ret_USD_PEN"] = fx_ret
    rows.append({"serie": "USD_PEN", "ticker": "PEN=X", "timestamp": fx_ts, "precio_anterior": prev_fx,
                 "precio_actual": cur_fx, "retorno": fx_ret, "estado": fx_state})

    beta = latest["coefficients"]
    pred = float(beta["intercept"] + sum(float(beta[f]) * features[f] for f in engine.FEATURES))
    if not pending.empty:
        p = pending.loc[pd.to_datetime(pending["fecha"]) < signal_date].sort_values("fecha")
    else:
        p = pd.DataFrame()
    vc_base = float(p.iloc[-1]["valor_cuota_estimado"]) if not p.empty else float(latest["latest_sbs_vc"])
    vc_est = vc_base * (1 + pred)
    signal = engine.classify(pred)
    payload = {"generated_at_lima": now_lima.isoformat(), "mode": "INTRADÍA PROVISIONAL", "market_open": True,
               "signal_date": signal_date.strftime("%Y-%m-%d"), "vc_base": vc_base, "vc_estimated": vc_est,
               "return_estimated": pred, "signal": signal, "assets": rows,
               "note": "Provisional hasta 16:10 Nueva York y hasta completar fuentes."}
    (PUBLIC_DATA / "live_market.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


engine.download_sbs = download_sbs_resilient
engine.download_yahoo = download_market_resilient
engine.load_bcrp = load_fx_resilient
engine.run_model = run_model_compatible
engine.main()
_write_signals()
try:
    _live_snapshot()
except Exception as exc:
    latest = json.loads((PUBLIC_DATA / "latest.json").read_text(encoding="utf-8"))
    fallback = {"generated_at_lima": datetime.now(LIMA).isoformat(), "mode": "CIERRE DIARIO · INTRADÍA NO DISPONIBLE",
                "market_open": _market_open_now(), "signal_date": latest["latest_estimate_date"],
                "vc_estimated": latest["latest_estimated_vc"], "return_estimated": latest["latest_return_estimated"],
                "signal": latest["signal"], "assets": [], "warning": f"{type(exc).__name__}: {exc}"}
    (PUBLIC_DATA / "live_market.json").write_text(json.dumps(fallback, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Advertencia intradía: {type(exc).__name__}: {exc}")

# Auditoría explícita de fuente/método para el visor.
latest_path = PUBLIC_DATA / "latest.json"
latest = json.loads(latest_path.read_text(encoding="utf-8"))
latest.setdefault("sources", {})["fx"] = "BCRP histórico; Yahoo PEN=X solo cola posterior al último BCRP"
latest["sources"]["market"] = "Yahoo Finance; Stooq solo cola nueva si Yahoo falla"
latest["vc_mode_rule"] = "INTRADÍA PROVISIONAL 09:30-16:10 NY; fuera de ese intervalo CIERRE DIARIO"
latest_path.write_text(json.dumps(latest, ensure_ascii=False, indent=2), encoding="utf-8")
print("Rolling 90 v2: histórico preservado, cola resiliente e intradía separado.")