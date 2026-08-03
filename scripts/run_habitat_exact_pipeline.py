"""Ejecuta la cadena oficial y exacta de Hábitat sin recorrer archivos SBS innecesarios."""

from __future__ import annotations

from urllib.parse import urljoin

import pandas as pd
import requests
from bs4 import BeautifulSoup

import enrich_habitat_daily_sbs as source
from postprocess_habitat_sbs_indicators import ensure_latest_consistency
from build_habitat_exact_parity import main as build_exact


def recent_monthly_urls() -> list[str]:
    """Usa solo el año vigente y las rutas mensuales recientes.

    El histórico ya está guardado en el repositorio. Para completar la cola diaria
    solo se requieren el mes actual, julio y los meses inmediatamente anteriores.
    Esto evita que GitHub Actions intente descargar todos los XLS desde 2015.
    """
    today = pd.Timestamp.now(tz="America/Lima").tz_localize(None).normalize()
    urls: set[str] = set()

    # Rutas oficiales predecibles: mes actual y cinco meses anteriores.
    for offset in range(0, 6):
        date = today - pd.DateOffset(months=offset)
        urls.add(source.month_url(int(date.year), int(date.month)))

    # Enlaces publicados del año vigente; se ignoran años antiguos.
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
        print(f"Índice SBS no disponible; se usarán rutas predecibles: {type(exc).__name__}: {exc}")

    return sorted(urls)


def main() -> None:
    # Sustituye únicamente el descubrimiento de archivos; conserva toda la
    # extracción, consolidación y validación oficial del módulo base.
    source.discover_monthly_urls = recent_monthly_urls
    source.main()

    # Único motor de Hábitat: misma metodología de Profuturo, coeficientes propios.
    build_exact()
    ensure_latest_consistency()


if __name__ == "__main__":
    main()
