from __future__ import annotations

import html
import json
import math
import re
from pathlib import Path
from urllib.request import Request, urlopen

import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "public" / "data" / "etf_market_snapshot.json"
USCF_URL = "https://www.uscfinvestments.com/cper"
MONTH_CODES = {
    "Jan": "F", "Feb": "G", "Mar": "H", "Apr": "J", "May": "K", "Jun": "M",
    "Jul": "N", "Aug": "Q", "Sep": "U", "Oct": "V", "Nov": "X", "Dec": "Z",
}


def _safe_float(value):
    try:
        x = float(value)
        return x if math.isfinite(x) else None
    except Exception:
        return None


def _fetch_official_components() -> list[dict]:
    req = Request(
        USCF_URL,
        headers={"User-Agent": "Mozilla/5.0 (compatible; Fondo3Monitor/1.0)"},
    )
    with urlopen(req, timeout=20) as response:
        raw = response.read().decode("utf-8", errors="ignore")

    text = html.unescape(re.sub(r"<[^>]+>", " ", raw))
    text = re.sub(r"\s+", " ", text)
    matches = re.findall(r"COPPER FUTURE\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)(\d{2})", text, flags=re.I)

    unique: list[tuple[str, str]] = []
    for month, year in matches:
        key = (month.title(), year)
        if key not in unique:
            unique.append(key)

    # La metodología vigente de SummerHaven selecciona uno o tres contratos.
    # Si son tres, las posiciones del benchmark son equitativas; si es uno, 100%.
    if len(unique) not in {1, 3}:
        raise RuntimeError(f"USCF devolvió {len(unique)} componentes; se esperaba 1 o 3")

    weight = 1.0 / len(unique)
    rows = []
    for month, year in unique:
        code = MONTH_CODES[month]
        yahoo_symbol = f"HG{code}{year}.CMX"
        rows.append(
            {
                "symbol": yahoo_symbol,
                "name": f"Copper Future {month}{year}",
                "weight": weight,
                "change": None,
                "holding_type": "benchmark_future",
                "source": "USCF / SummerHaven Copper Index",
            }
        )
    return rows


def _daily_change(symbol: str):
    try:
        hist = yf.Ticker(symbol).history(
            period="5d",
            interval="1d",
            auto_adjust=False,
            actions=False,
        )
        if hist is None or hist.empty or "Close" not in hist.columns:
            return None
        close = pd.to_numeric(hist["Close"], errors="coerce").dropna()
        if len(close) < 2 or float(close.iloc[-2]) == 0:
            return None
        return _safe_float(float(close.iloc[-1]) / float(close.iloc[-2]) - 1)
    except Exception:
        return None


def main() -> None:
    payload = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    tickers = payload.get("tickers", [])
    cper = next((x for x in tickers if isinstance(x, dict) and x.get("symbol") == "CPER"), None)
    if cper is None:
        raise RuntimeError("No se encontró CPER en el snapshot")

    # Yahoo no expone top_holdings de CPER. Para este ETF de futuros usamos
    # los Benchmark Component Futures Contracts publicados por el emisor USCF.
    components = _fetch_official_components()
    for component in components:
        component["change"] = _daily_change(component["symbol"])

    cper["holdings"] = components
    cper["holdings_source"] = "USCF / SummerHaven Copper Index"
    cper["holdings_note"] = (
        "CPER no es una cartera de acciones: se muestran los contratos de futuros de cobre "
        "que componen actualmente su benchmark. El peso corresponde a la asignación del índice; "
        "no incluye el colateral en efectivo o instrumentos del Tesoro."
    )

    holdings_errors = payload.get("holdings_errors", {})
    if isinstance(holdings_errors, dict):
        holdings_errors.pop("CPER", None)

    payload["holdings_method"] = (
        "Mapa de calor de las principales posiciones reportadas por Yahoo Finance para SPY, QQQ, EEM, EPU y MCHI. "
        "Para CPER se usan los Benchmark Component Futures Contracts publicados por USCF y la metodología vigente "
        "del SummerHaven Copper Index. El tamaño representa el peso y el color la variación diaria cuando hay cotización compatible."
    )
    SNAPSHOT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print("CPER enriquecido:", ", ".join(x["symbol"] for x in components))


if __name__ == "__main__":
    main()
