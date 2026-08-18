"""Actualiza exclusivamente AFP Hábitat Fondo 3 con VC oficiales y OLS rolling 90.

La serie SBS debe ser continua. Si una fecha oficial presente en el calendario del
Fondo 3 no puede recuperarse, el proceso se detiene: nunca se sustituye por una
estimación ni se publica como "SBS pendiente".
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urljoin

import pandas as pd
import requests
from bs4 import BeautifulSoup

import build_habitat_exact_parity as habitat_ols
import enrich_habitat_daily_sbs as source
from habitat_complete_official_calendar import (
    install as install_official_calendar,
    validate_official_estimate_calendar,
)
from postprocess_habitat_chart_clarity import main as clarify_habitat_chart
from postprocess_habitat_sbs_indicators import ensure_latest_consistency
from postprocess_trade_cloud_fund_routing import patch as route_trade_cloud

ROOT = Path(__file__).resolve().parents[1]
OFFICIAL_CORRECTIONS = (
    ROOT / "data" / "rolling90" / "sbs_habitat_f3_official_corrections.csv"
)


def install_official_corrections() -> None:
    """Incorpora VC oficiales SBS recuperados del historial del propio proyecto.

    El archivo contiene publicaciones de la página diaria Variables SPP que ya
    habían sido descargadas por las ejecuciones históricas del monitor. No son
    valores estimados y solo se aplican a la serie de Hábitat.
    """
    if not OFFICIAL_CORRECTIONS.exists() or OFFICIAL_CORRECTIONS.stat().st_size == 0:
        raise RuntimeError("No existe el respaldo oficial SBS de Hábitat para julio.")

    corrections = pd.read_csv(OFFICIAL_CORRECTIONS)
    corrections["fecha"] = pd.to_datetime(corrections["fecha"], errors="coerce")
    corrections["valor_cuota"] = pd.to_numeric(
        corrections["valor_cuota"], errors="coerce"
    )
    corrections = (
        corrections.dropna(subset=["fecha", "valor_cuota"])
        .loc[lambda frame: frame["valor_cuota"].gt(0), ["fecha", "valor_cuota"]]
        .sort_values("fecha")
        .drop_duplicates("fecha", keep="last")
    )
    if len(corrections) != 14:
        raise RuntimeError(
            f"El respaldo oficial de julio tiene {len(corrections)} fechas; se esperan 14."
        )

    saved = source.read_csv(source.HISTORY_PATH)
    frames = [frame for frame in (saved, corrections) if not frame.empty]
    merged = pd.concat(frames, ignore_index=True, sort=False)
    merged["valor_cuota"] = pd.to_numeric(merged["valor_cuota"], errors="coerce")
    merged = (
        merged.dropna(subset=["fecha", "valor_cuota"])
        .sort_values("fecha")
        .drop_duplicates("fecha", keep="last")
        .reset_index(drop=True)
    )
    source.save_csv(merged, source.HISTORY_PATH)
    print(
        "VC oficiales SBS de Hábitat restaurados: "
        + ", ".join(corrections["fecha"].dt.strftime("%Y-%m-%d"))
    )


def recent_monthly_urls() -> list[str]:
    """Busca los seis archivos mensuales SBS más recientes, incluso si aún no están enlazados."""
    today = pd.Timestamp.now(tz="America/Lima").tz_localize(None).normalize()
    urls: set[str] = set()

    for offset in range(0, 6):
        date = today - pd.DateOffset(months=offset)
        urls.add(source.month_url(int(date.year), int(date.month)))

    try:
        response = requests.get(source.SBS_INDEX, headers=source.HEADERS, timeout=45)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "lxml")
        current_year = str(int(today.year))
        for anchor in soup.find_all("a", href=True):
            url = urljoin(source.SBS_INDEX, anchor["href"])
            if (
                "FP-1359" in url.upper()
                and url.lower().endswith(".xls")
                and f"/{current_year}/" in url
            ):
                urls.add(url)
    except Exception as exc:
        print(
            "Índice SBS no disponible; se usarán rutas mensuales predecibles: "
            f"{type(exc).__name__}: {exc}"
        )
    return sorted(urls)


def validate_latest_market_consistency() -> None:
    """Evita publicar Hábitat con una fecha de mercado atrasada.

    Compara el último mercado publicado por Hábitat con la última fila completa
    de los seis ETF de Yahoo ya persistidos en la base compartida. Si existe una
    sesión posterior completa, el workflow falla en vez de dejar silenciosamente
    una fecha antigua en el visor.
    """
    markets_path = ROOT / "data" / "rolling90" / "markets.csv"
    latest_path = ROOT / "public" / "habitat" / "data" / "latest.json"

    markets = pd.read_csv(markets_path)
    markets["fecha"] = pd.to_datetime(markets["fecha"], errors="coerce")
    equity = ["SPY", "NEM", "FCX", "EPU", "MCHI", "EEM"]
    complete = markets.dropna(subset=["fecha", *equity]).sort_values("fecha")
    if complete.empty:
        raise RuntimeError("No hay sesiones completas de mercado para validar Hábitat.")

    expected = pd.Timestamp(complete.iloc[-1]["fecha"]).normalize()
    latest = json.loads(latest_path.read_text(encoding="utf-8"))
    published = pd.Timestamp(latest["latest_market_date"]).normalize()
    if published != expected:
        raise RuntimeError(
            "Hábitat publicó una fecha de mercado atrasada: "
            f"visor={published:%Y-%m-%d}, mercado={expected:%Y-%m-%d}"
        )

    print(f"Hábitat validado con último mercado completo: {expected:%Y-%m-%d}")


def main() -> None:
    install_official_corrections()

    # Se conserva la validación estricta original de enrich_habitat_daily_sbs:
    # Hábitat debe contener todas las fechas oficiales del calendario Fondo 3.
    source.discover_monthly_urls = recent_monthly_urls
    source.main()

    # Regla exclusiva de Hábitat: todo VC oficial debe tener VC estimado OLS,
    # incluso cuando algún mercado esté cerrado o no publique por feriado.
    install_official_calendar()
    habitat_ols.main()
    clarify_habitat_chart()
    ensure_latest_consistency()
    route_trade_cloud("habitat")
    validate_official_estimate_calendar()
    validate_latest_market_consistency()


if __name__ == "__main__":
    main()
