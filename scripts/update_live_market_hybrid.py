from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
BASE_PATH = ROOT / "scripts" / "update_live_market_only.py"
ALT_CLOSES_PATH = ROOT / "data" / "analysis" / "googlefinance_alt_aligned_closes_20260402_20260820.csv"

spec = importlib.util.spec_from_file_location("fondo3_live_base", BASE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError(f"No se pudo cargar {BASE_PATH}")
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)

# Símbolos exactamente como se ven en Google Finance y como se usaron en la
# comparación del nuevo 60/30. Se mantienen separados de payload['assets'] para
# no alterar los factores que alimentan al OLS principal.
EXPERIMENTAL_QUOTES = [
    (".INX", "INDEXSP", "^GSPC"),
    ("CPER", "NYSEARCA", "CPER"),
    ("EEM", "NYSEARCA", "EEM"),
    ("NDX", "INDEXNASDAQ", "^NDX"),
    ("SPBLSCUP", "INDEXSP", None),
]


def _configure_assets_from_model(latest: dict) -> None:
    """El intradía usa exactamente los factores publicados por el OLS vigente."""
    if "ret_EEM" in (latest.get("coefficients", {}) or {}) and "EEM" not in base.ASSETS:
        base.ASSETS.append("EEM")
    base.FEATURES = [f"ret_{x}" for x in base.ASSETS] + ["ret_USD_PEN"]


def _fx_row(payload: dict) -> dict | None:
    for row in payload.get("assets", []):
        if row.get("serie") == "USD_PEN":
            return row
    return None


def _apply_hybrid_fx(payload: dict, latest: dict, pending: pd.DataFrame) -> dict:
    row = _fx_row(payload)
    if row is None:
        payload["fx_source"] = "SIN DATO"
        payload["fx_provisional"] = True
        return payload

    if "BCRP MISMA FECHA" in str(row.get("estado", "")):
        payload["fx_source"] = "BCRP"
        payload["fx_provisional"] = False
        payload["fx_rule"] = "BCRP si existe; Yahoo PEN=X solo como respaldo provisional cuando BCRP aún no publicó la fecha."
        return payload

    signal_date = pd.Timestamp(payload.get("signal_date")).normalize()

    if payload.get("market_open"):
        fx_ret = pd.to_numeric(pd.Series([row.get("retorno")]), errors="coerce").iloc[0]
        if np.isfinite(fx_ret):
            beta_fx = float(latest["coefficients"]["ret_USD_PEN"])
            old_pred = float(payload["return_estimated"])
            new_pred = old_pred + beta_fx * float(fx_ret)
            vc_base = float(payload.get("vc_base", latest["latest_sbs_vc"]))
            payload["return_estimated"] = new_pred
            payload["vc_estimated"] = vc_base * (1.0 + new_pred)
            payload["signal"] = base._classify(new_pred)

            current = row.get("precio_actual")
            if current is not None and np.isfinite(float(current)) and abs(1.0 + float(fx_ret)) > 1e-12:
                row["precio_anterior"] = float(current) / (1.0 + float(fx_ret))
            row["ticker"] = "PEN=X"
            row["retorno_modelo"] = float(fx_ret)
            row["estado"] = "YAHOO PEN=X · PROVISIONAL · USADO POR MODELO"
            row["usado_modelo"] = True
            payload["fx_source"] = "YAHOO PEN=X PROVISIONAL"
            payload["fx_provisional"] = True
        else:
            row["retorno_modelo"] = 0.0
            row["estado"] = "USD/PEN SIN DATO · MODELO USA 0 %"
            row["usado_modelo"] = True
            payload["fx_source"] = "SIN DATO · 0 %"
            payload["fx_provisional"] = True
    else:
        p = pending.copy()
        if not p.empty:
            p["fecha"] = pd.to_datetime(p["fecha"], errors="coerce")
            same = p.loc[p["fecha"].dt.normalize().eq(signal_date)].sort_values("fecha")
        else:
            same = pd.DataFrame()

        if not same.empty:
            r = same.iloc[-1]
            source = str(r.get("usd_pen_fuente", ""))
            if source.startswith("YAHOO"):
                fx_ret = float(r.get("ret_USD_PEN", 0.0))
                row["ticker"] = "PEN=X"
                row["precio_anterior"] = None
                row["precio_actual"] = None
                row["retorno"] = fx_ret
                row["retorno_modelo"] = fx_ret
                row["estado"] = "YAHOO PEN=X · PROVISIONAL · USADO POR MODELO"
                row["usado_modelo"] = True
                payload["fx_source"] = "YAHOO PEN=X PROVISIONAL"
                payload["fx_provisional"] = True
            elif source == "BCRP":
                payload["fx_source"] = "BCRP"
                payload["fx_provisional"] = False
            else:
                row["retorno_modelo"] = 0.0
                row["estado"] = "USD/PEN SIN DATO · MODELO USA 0 %"
                row["usado_modelo"] = True
                payload["fx_source"] = "SIN DATO · 0 %"
                payload["fx_provisional"] = True
        else:
            payload["fx_source"] = str(latest.get("latest_fx_source", "SIN DATO"))
            payload["fx_provisional"] = bool(latest.get("latest_fx_provisional", True))

    payload["fx_rule"] = (
        "Histórico/entrenamiento: BCRP. Predicción: BCRP si existe; "
        "si está rezagado, Yahoo PEN=X provisional; 0 % solo si ambas fuentes faltan."
    )
    return payload


def _google_finance_quote(symbol: str, exchange: str) -> dict:
    """Lee el precio y variación que Google Finance expone en atributos del quote."""
    url = f"https://www.google.com/finance/quote/{symbol}:{exchange}?hl=en"
    response = requests.get(
        url,
        timeout=12,
        headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    response.raise_for_status()
    text = response.text
    price_match = re.search(r'data-last-price="([+-]?[0-9.,]+)"', text)
    pct_match = re.search(r'data-price-change-percent="([+-]?[0-9.,]+)"', text)
    ts_match = re.search(r'data-last-normal-market-timestamp="([0-9]+)"', text)
    if not price_match:
        raise RuntimeError(f"Google Finance no devolvió precio para {symbol}")
    price = float(price_match.group(1).replace(",", ""))
    ret = None
    if pct_match:
        ret = float(pct_match.group(1).replace(",", "")) / 100.0
    timestamp = None
    if ts_match:
        stamp = int(ts_match.group(1))
        if stamp > 10_000_000_000:
            stamp //= 1000
        timestamp = datetime.fromtimestamp(stamp, tz=base.NY).isoformat()
    return {"price": price, "return": ret, "timestamp": timestamp, "source": "GOOGLE FINANCE"}


def _yahoo_equivalent_quote(symbol: str, yahoo_ticker: str) -> dict:
    """Respaldo intradía para .INX/NDX y ETFs cuando Google Finance no responde."""
    raw = base.yf.download(
        yahoo_ticker,
        period="5d",
        interval="5m",
        auto_adjust=False,
        actions=False,
        prepost=False,
        progress=False,
        threads=False,
    )
    ser = base._extract_close(raw, yahoo_ticker)
    if ser.empty:
        raise RuntimeError(f"Yahoo no devolvió {yahoo_ticker}")
    current = float(ser.iloc[-1])
    ts = pd.Timestamp(ser.index[-1])
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    ts_ny = ts.tz_convert(base.NY)

    daily_raw = base.yf.download(
        yahoo_ticker,
        period="10d",
        interval="1d",
        auto_adjust=False,
        actions=False,
        progress=False,
        threads=False,
    )
    daily = base._extract_close(daily_raw, yahoo_ticker)
    previous = None
    if not daily.empty:
        idx = pd.to_datetime(daily.index)
        for dt, value in zip(idx, daily.to_numpy(float)):
            d = pd.Timestamp(dt)
            if d.tzinfo is not None:
                d = d.tz_convert(base.NY).tz_localize(None)
            if d.date() < ts_ny.date():
                previous = float(value)
    ret = current / previous - 1.0 if previous not in (None, 0.0) else None
    return {
        "price": current,
        "return": ret,
        "timestamp": ts_ny.isoformat(),
        "source": f"YAHOO {yahoo_ticker} · RESPALDO EQUIVALENTE",
    }


def _stored_google_quote(symbol: str) -> dict | None:
    """Último cierre exacto guardado de Google Finance como respaldo final."""
    if not ALT_CLOSES_PATH.exists():
        return None
    try:
        frame = pd.read_csv(ALT_CLOSES_PATH)
    except Exception:
        return None
    if symbol not in frame.columns or "fecha" not in frame.columns:
        return None
    frame["fecha"] = pd.to_datetime(frame["fecha"], errors="coerce")
    frame[symbol] = pd.to_numeric(frame[symbol], errors="coerce")
    valid = frame.dropna(subset=["fecha", symbol]).sort_values("fecha")
    if valid.empty:
        return None
    row = valid.iloc[-1]
    return {
        "price": float(row[symbol]),
        "return": None,
        "timestamp": pd.Timestamp(row["fecha"]).strftime("%Y-%m-%d"),
        "source": "ÚLTIMO CIERRE GOOGLE FINANCE GUARDADO",
    }


def _previous_experimental_by_symbol(previous: dict) -> dict[str, dict]:
    return {
        str(row.get("serie")): row
        for row in previous.get("experimental_assets", [])
        if row.get("serie")
    }


def _attach_experimental_quotes(payload: dict, previous: dict) -> dict:
    """Añade los seis tickers nuevos sin tocar los activos ni el VC del OLS vigente."""
    old = _previous_experimental_by_symbol(previous)
    rows: list[dict] = []
    for symbol, exchange, yahoo_ticker in EXPERIMENTAL_QUOTES:
        quote = None
        error = None
        try:
            quote = _google_finance_quote(symbol, exchange)
        except Exception as exc:
            error = f"Google: {type(exc).__name__}"
        if quote is None and yahoo_ticker:
            try:
                quote = _yahoo_equivalent_quote(symbol, yahoo_ticker)
            except Exception as exc:
                error = f"{error or ''}; Yahoo: {type(exc).__name__}".strip("; ")
        if quote is None:
            quote = _stored_google_quote(symbol)
        if quote is None and symbol in old:
            prior = dict(old[symbol])
            prior["estado"] = "SEGUIMIENTO 60/30 EXPERIMENTAL · ÚLTIMO DATO CONSERVADO"
            prior["usado_modelo"] = False
            rows.append(prior)
            continue
        if quote is None:
            rows.append({
                "serie": symbol,
                "ticker": f"{symbol}:{exchange}",
                "timestamp": None,
                "precio_anterior": None,
                "precio_actual": None,
                "retorno": None,
                "retorno_modelo": None,
                "estado": f"SEGUIMIENTO 60/30 EXPERIMENTAL · SIN DATO{(' · ' + error) if error else ''}",
                "usado_modelo": False,
            })
            continue
        rows.append({
            "serie": symbol,
            "ticker": f"{symbol}:{exchange}",
            "timestamp": quote.get("timestamp"),
            "precio_anterior": None,
            "precio_actual": quote.get("price"),
            "retorno": quote.get("return"),
            "retorno_modelo": None,
            "estado": f"{quote.get('source')} · NUEVO 60/30 EXPERIMENTAL",
            "usado_modelo": False,
        })

    # USD/PEN se replica de la fuente vigente para que no aparezcan dos tipos de
    # cambio contradictorios en la misma pantalla. Solo cambia la etiqueta visual.
    fx = _fx_row(payload)
    if fx is not None:
        rows.append({
            "serie": "USD/PEN",
            "ticker": "USD/PEN",
            "timestamp": fx.get("timestamp"),
            "precio_anterior": fx.get("precio_anterior"),
            "precio_actual": fx.get("precio_actual"),
            "retorno": fx.get("retorno"),
            "retorno_modelo": None,
            "estado": f"{fx.get('estado', '')} · NUEVO 60/30 EXPERIMENTAL",
            "usado_modelo": False,
        })
    elif "USD/PEN" in old:
        rows.append(dict(old["USD/PEN"]))
    else:
        rows.append({
            "serie": "USD/PEN", "ticker": "USD/PEN", "timestamp": None,
            "precio_anterior": None, "precio_actual": None, "retorno": None,
            "retorno_modelo": None,
            "estado": "NUEVO 60/30 EXPERIMENTAL · SIN DATO", "usado_modelo": False,
        })

    payload["experimental_assets"] = rows
    payload["experimental_watchlist"] = [".INX", "CPER", "EEM", "NDX", "SPBLSCUP", "USD/PEN"]
    payload["experimental_note"] = (
        "Seguimiento del nuevo 60/30. No modifica el OLS principal ni el challenger 60/30 vigente."
    )
    return payload


def _preserve_today_intraday(payload: dict) -> dict:
    """No borrar el snapshot de hoy con el cierre diario anterior al terminar NY."""
    if str(payload.get("mode", "")).startswith("INTRAD"):
        return payload
    today_lima = datetime.now(base.LIMA).date().isoformat()
    if str(payload.get("signal_date", "")) >= today_lima:
        return payload
    if not base.LIVE_PATH.exists():
        return payload
    try:
        previous = json.loads(base.LIVE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return payload
    if not str(previous.get("mode", "")).startswith("INTRAD"):
        return payload
    if str(previous.get("signal_date", "")) != today_lima:
        return payload
    if not np.isfinite(float(previous.get("vc_estimated", np.nan))):
        return payload

    preserved = dict(previous)
    preserved["market_open"] = False
    preserved["mode"] = "INTRADIA PROVISIONAL - ULTIMO CORTE"
    preserved["action"] = "ULTIMO_CORTE"
    preserved["checked_at_lima"] = datetime.now(base.LIMA).isoformat()
    preserved["note"] = (
        "Se conserva el ultimo snapshot intradia de hoy porque el cierre diario "
        "de hoy aun no esta disponible."
    )
    return preserved


def _update_habitat_live() -> None:
    script = ROOT / "scripts" / "update_habitat_live_market.py"
    if not script.exists():
        return
    subprocess.run([sys.executable, str(script)], cwd=ROOT, check=True)
    # Compatibilidad con ejecuciones antiguas del workflow, que solo hacían git add
    # explícito del archivo de Profuturo.
    subprocess.run(
        ["git", "add", "public/habitat/data/live_market.json"],
        cwd=ROOT,
        check=True,
    )


def main() -> None:
    if not base.LATEST_PATH.exists():
        raise RuntimeError("Falta public/data/latest.json")
    latest = json.loads(base.LATEST_PATH.read_text(encoding="utf-8"))
    _configure_assets_from_model(latest)
    markets = base._read_csv(base.MARKETS_PATH)
    pending = base._read_csv(base.PENDING_PATH)
    if markets.empty:
        raise RuntimeError("Falta data/rolling90/markets.csv")

    previous_live: dict = {}
    if base.LIVE_PATH.exists():
        try:
            previous_live = json.loads(base.LIVE_PATH.read_text(encoding="utf-8"))
        except Exception:
            previous_live = {}

    try:
        payload = base._build_live(latest, markets, pending)
        payload = _apply_hybrid_fx(payload, latest, pending)
    except Exception as exc:
        open_now = base._market_open_now()
        payload = {
            "generated_at_lima": datetime.now(base.LIMA).isoformat(),
            "mode": "MERCADO ABIERTO · INTRADÍA NO DISPONIBLE" if open_now else "CIERRE DIARIO · ACTUALIZACIÓN NO DISPONIBLE",
            "market_open": open_now,
            "signal_date": datetime.now(base.NY).date().isoformat() if open_now else latest.get("latest_market_date"),
            "vc_estimated": float(latest["latest_estimated_vc"]),
            "return_estimated": float(latest["latest_return_estimated"]),
            "signal": str(latest["signal"]),
            "assets": previous_live.get("assets", []),
            "action": "ESPERAR" if open_now else "CIERRE",
            "engine": "LIVE INDEPENDIENTE",
            "warning": f"{type(exc).__name__}: {exc}",
            "fx_source": latest.get("latest_fx_source", "SIN DATO"),
            "fx_provisional": latest.get("latest_fx_provisional", True),
            "fx_rule": "BCRP si existe; Yahoo PEN=X provisional si BCRP está rezagado; 0 % solo si ambas fuentes faltan.",
        }

    payload = _preserve_today_intraday(payload)
    payload = _attach_experimental_quotes(payload, previous_live)
    base.LIVE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _update_habitat_live()
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
