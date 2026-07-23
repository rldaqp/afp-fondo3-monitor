"""Punto de entrada seguro de Streamlit Community Cloud.

Corrige tres problemas operativos:
1. Ejecuta la aplicación completa en cada rerun.
2. Evita el conflicto entre la clave del formulario y session_state.
3. Sustituye la descarga masiva de yfinance por consultas individuales con
   reintentos, para que un YFRateLimitError de EPU no detenga toda la app.
"""

from __future__ import annotations

from pathlib import Path
import runpy
import time as time_module
from urllib.parse import quote

import pandas as pd
import requests
import streamlit as st
import yfinance as yf

HERE = Path(__file__).resolve().parent
APP_FILE = HERE / "streamlit_unified.py"

st.set_page_config(
    page_title="Profuturo Fondo 3",
    page_icon="📈",
    layout="wide",
)

# ------------------------------------------------------------------
# 1. Clave distinta para el formulario y para el resultado calculado.
# ------------------------------------------------------------------
_original_form = st.form


def _form_without_state_conflict(key, *args, **kwargs):
    safe_key = "operation_form" if key == "operation" else key
    return _original_form(safe_key, *args, **kwargs)


st.form = _form_without_state_conflict

# ------------------------------------------------------------------
# 2. Descarga robusta de Yahoo Finance.
# ------------------------------------------------------------------
# El endpoint chart no requiere la cookie/crumb usada por algunas rutas de
# yfinance y permite descargar cada instrumento por separado. Se prueban
# query1 y query2 con pausas crecientes.
_YAHOO_HOSTS = (
    "https://query1.finance.yahoo.com",
    "https://query2.finance.yahoo.com",
)
_YAHOO_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 "
        "Chrome/126.0 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
}


def _ticker_list(tickers):
    if isinstance(tickers, str):
        return [item for item in tickers.replace(",", " ").split() if item]
    return list(tickers)


def _chart_series(ticker, *, start=None, period=None, interval="1d"):
    params = {
        "interval": interval,
        "events": "div,splits",
        "includeAdjustedClose": "true",
    }

    if start is not None:
        start_ts = pd.Timestamp(start, tz="UTC")
        end_ts = pd.Timestamp.now(tz="UTC") + pd.Timedelta(days=2)
        params["period1"] = int(start_ts.timestamp())
        params["period2"] = int(end_ts.timestamp())
    else:
        params["range"] = period or "5d"

    errors = []
    for wait_seconds in (0, 2, 5):
        if wait_seconds:
            time_module.sleep(wait_seconds)

        for host in _YAHOO_HOSTS:
            try:
                url = f"{host}/v8/finance/chart/{quote(str(ticker))}"
                response = requests.get(
                    url,
                    params=params,
                    headers=_YAHOO_HEADERS,
                    timeout=30,
                )
                response.raise_for_status()
                payload = response.json()
                result = payload.get("chart", {}).get("result") or []
                if not result:
                    raise RuntimeError("Yahoo no devolvió una serie")

                item = result[0]
                timestamps = item.get("timestamp") or []
                quote_data = (
                    item.get("indicators", {})
                    .get("quote", [{}])[0]
                )
                closes = quote_data.get("close") or []
                if not timestamps or not closes:
                    raise RuntimeError("Serie sin precios de cierre")

                size = min(len(timestamps), len(closes))
                index = pd.to_datetime(
                    timestamps[:size], unit="s", utc=True
                )
                series = pd.Series(
                    closes[:size], index=index, name=str(ticker), dtype="float64"
                ).dropna()

                if series.empty:
                    raise RuntimeError("Serie de cierre vacía")
                return series
            except Exception as error:
                errors.append(f"{host}: {type(error).__name__}: {error}")

    raise RuntimeError(
        f"No se pudo descargar {ticker} después de varios intentos. "
        + " | ".join(errors[-4:])
    )


def _safe_yahoo_download(
    tickers,
    start=None,
    end=None,
    period=None,
    interval="1d",
    **kwargs,
):
    del end, kwargs
    names = _ticker_list(tickers)
    series_by_ticker = {}
    failures = []

    for ticker in names:
        try:
            series_by_ticker[ticker] = _chart_series(
                ticker,
                start=start,
                period=period,
                interval=interval,
            )
        except Exception as error:
            failures.append(f"{ticker}: {error}")

    if failures:
        raise RuntimeError(
            "Falló la descarga de índices: " + " || ".join(failures)
        )

    frame = pd.concat(series_by_ticker, axis=1).sort_index()
    frame.columns = pd.MultiIndex.from_tuples(
        [("Close", ticker) for ticker in frame.columns]
    )
    return frame


# El núcleo OLS importa el mismo módulo yfinance, por lo que usará esta
# función en sus descargas diarias e intradía.
yf.download = _safe_yahoo_download

# ------------------------------------------------------------------
# 3. Ejecutar la app y mostrar cualquier error en pantalla.
# ------------------------------------------------------------------
loading = st.empty()
loading.info("Cargando SBS e índices; ejecutando modelo OLS rolling 90…")

try:
    runpy.run_path(str(APP_FILE), run_name="__main__")
    loading.empty()
except Exception as error:
    loading.empty()
    st.error("La aplicación unificada no pudo iniciar.")
    st.exception(error)
    st.stop()
