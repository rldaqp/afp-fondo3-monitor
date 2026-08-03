"""Ejecuta Hábitat con fuentes oficiales y estimación explícita de huecos SBS."""

from __future__ import annotations

from urllib.parse import urljoin

import pandas as pd
import requests
from bs4 import BeautifulSoup

import enrich_habitat_daily_sbs as source
from build_habitat_gap_aware import main as build_gap_aware
from postprocess_habitat_sbs_indicators import ensure_latest_consistency


def recent_monthly_urls() -> list[str]:
    """Usa archivos SBS recientes y prueba la ruta mensual aún no enlazada."""
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
            "Índice SBS no disponible; se usarán rutas predecibles: "
            f"{type(exc).__name__}: {exc}"
        )
    return sorted(urls)


def continuity_is_modelled(history: pd.DataFrame) -> None:
    """Informa los huecos SBS; el generador gap-aware debe cubrirlos después."""
    profuturo = source.read_csv(source.PROFUTURO_PATH)
    if profuturo.empty or history.empty:
        return
    latest = pd.Timestamp(history["fecha"].max())
    start = max(pd.Timestamp("2026-07-01"), latest - pd.Timedelta(days=45))
    expected = set(
        profuturo.loc[
            profuturo["fecha"].between(start, latest, inclusive="both"), "fecha"
        ].dt.normalize()
    )
    present = set(
        history.loc[
            history["fecha"].between(start, latest, inclusive="both"), "fecha"
        ].dt.normalize()
    )
    missing = sorted(expected - present)
    if missing:
        print(
            "SBS mensual pendiente; el modelo cubrirá como ESTIMADO, no oficial: "
            + ", ".join(date.strftime("%Y-%m-%d") for date in missing)
        )


def main() -> None:
    source.discover_monthly_urls = recent_monthly_urls
    source.validate_continuity = continuity_is_modelled
    source.main()

    # Único motor operativo: paridad metodológica Profuturo + huecos identificados.
    build_gap_aware()
    ensure_latest_consistency()


if __name__ == "__main__":
    main()
