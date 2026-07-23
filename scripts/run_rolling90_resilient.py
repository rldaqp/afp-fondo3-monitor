from __future__ import annotations

import importlib.util
import io
import re
import time
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "scripts" / "build_rolling90_pages.py"

spec = importlib.util.spec_from_file_location("rolling90_engine", ENGINE)
if spec is None or spec.loader is None:
    raise RuntimeError(f"No se pudo cargar {ENGINE}")
engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)

_original_download_yahoo = engine.download_yahoo
_original_download_sbs = engine.download_sbs


def _get_text(url: str, attempts: int = 3) -> str:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            response = requests.get(url, headers=engine.HEADERS, timeout=45)
            response.raise_for_status()
            text = response.text.strip()
            if text:
                return text
        except Exception as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(1.0 + attempt)
    raise RuntimeError(
        f"No respondió {url}: {type(last_error).__name__}: {last_error}"
    )


def _parse_sbs_daily_blocks() -> pd.DataFrame:
    """Asocia cada 'Información al ...' con la tabla inmediata siguiente."""
    response = requests.get(engine.SBS_DAILY, headers=engine.HEADERS, timeout=45)
    response.raise_for_status()
    soup = BeautifulSoup(response.content, "lxml")
    rows: list[dict[str, object]] = []

    for node in soup.find_all(string=True):
        text = " ".join(str(node).split())
        if "informacion al" not in engine.norm(text):
            continue
        match = re.search(r"(\d{2}/\d{2}/\d{4})", text)
        if not match:
            continue

        fecha = pd.to_datetime(match.group(1), format="%d/%m/%Y")
        parent = getattr(node, "parent", None)
        table = parent.find_next("table") if parent is not None else None
        if table is None:
            continue

        valor = None
        for tr in table.find_all("tr"):
            cells = tr.find_all(["th", "td"], recursive=False)
            if not cells:
                continue
            texts = [" ".join(cell.get_text(" ", strip=True).split()) for cell in cells]
            if texts and engine.norm(texts[0]) == "profuturo" and len(texts) >= 10:
                valor = engine.parse_num(texts[9])
                break

        if valor is not None:
            rows.append({"fecha": fecha, "valor_cuota": float(valor)})

    if not rows:
        raise RuntimeError("No se pudieron extraer bloques diarios SBS de Profuturo Fondo 3")

    daily = pd.DataFrame(rows)
    daily["fecha"] = pd.to_datetime(daily["fecha"], errors="coerce")
    daily["valor_cuota"] = pd.to_numeric(daily["valor_cuota"], errors="coerce")
    return (
        daily.dropna()
        .sort_values("fecha")
        .drop_duplicates("fecha", keep="last")
        .reset_index(drop=True)
    )


def download_sbs_resilient() -> tuple[pd.DataFrame, list[str]]:
    base, warnings = _original_download_sbs()
    try:
        daily = _parse_sbs_daily_blocks()
        combined = pd.concat([base, daily], ignore_index=True)
        combined["fecha"] = pd.to_datetime(combined["fecha"], errors="coerce")
        combined["valor_cuota"] = pd.to_numeric(combined["valor_cuota"], errors="coerce")
        combined = (
            combined.dropna()
            .sort_values("fecha")
            .drop_duplicates("fecha", keep="last")
            .reset_index(drop=True)
        )
        print(
            "SBS diaria incorporada hasta "
            f"{combined['fecha'].max():%Y-%m-%d}"
        )
        return combined, warnings
    except Exception as exc:
        warnings.append(f"SBS diaria por bloques: {type(exc).__name__}: {exc}")
        return base, warnings


def _download_stooq_ticker(ticker: str) -> pd.DataFrame:
    symbols = {
        "SPY": "spy.us",
        "NEM": "nem.us",
        "FCX": "fcx.us",
        "EPU": "epu.us",
        "MCHI": "mchi.us",
    }
    symbol = symbols[ticker]
    start = engine.START.strftime("%Y%m%d")
    end = pd.Timestamp.now(tz="America/Lima").strftime("%Y%m%d")
    url = f"https://stooq.com/q/d/l/?s={symbol}&d1={start}&d2={end}&i=d"
    text = _get_text(url)
    frame = pd.read_csv(io.StringIO(text))
    if frame.empty or "Date" not in frame.columns or "Close" not in frame.columns:
        raise RuntimeError(f"Stooq devolvió datos inválidos para {ticker}")
    out = frame[["Date", "Close"]].copy()
    out.columns = ["fecha", ticker]
    out["fecha"] = pd.to_datetime(out["fecha"], errors="coerce")
    out[ticker] = pd.to_numeric(out[ticker], errors="coerce")
    return (
        out.dropna()
        .sort_values("fecha")
        .drop_duplicates("fecha", keep="last")
        .reset_index(drop=True)
    )


def _download_stooq() -> pd.DataFrame:
    frames = [_download_stooq_ticker(ticker) for ticker in engine.ASSETS]
    market = frames[0]
    for frame in frames[1:]:
        market = market.merge(frame, on="fecha", how="outer")
    return market.sort_values("fecha").drop_duplicates("fecha", keep="last")


def download_market_resilient() -> pd.DataFrame:
    try:
        market = _original_download_yahoo()
        print("Mercado descargado desde Yahoo Finance")
        return market
    except Exception as yahoo_error:
        print(
            "Yahoo Finance no respondió; se usa Stooq como respaldo: "
            f"{type(yahoo_error).__name__}: {yahoo_error}"
        )
        market = _download_stooq()
        print("Mercado descargado desde Stooq")
        return market


engine.download_sbs = download_sbs_resilient
engine.download_yahoo = download_market_resilient
engine.main()
