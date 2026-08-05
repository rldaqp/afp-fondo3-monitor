"""Actualiza exclusivamente AFP Hábitat Fondo 3 con VC oficiales y OLS rolling 90.

La serie SBS debe ser continua. Si una fecha oficial presente en el calendario del
Fondo 3 no puede recuperarse, el proceso se detiene: nunca se sustituye por una
estimación ni se publica como "SBS pendiente".
"""

from __future__ import annotations

from urllib.parse import urljoin

import pandas as pd
import requests
from bs4 import BeautifulSoup

import enrich_habitat_daily_sbs as source
from build_habitat_exact_parity import main as build_habitat_ols
from postprocess_habitat_chart_clarity import main as clarify_habitat_chart
from postprocess_habitat_sbs_indicators import ensure_latest_consistency


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


def main() -> None:
    # Se conserva la validación estricta original de enrich_habitat_daily_sbs:
    # Hábitat debe contener todas las fechas oficiales del calendario Fondo 3.
    source.discover_monthly_urls = recent_monthly_urls
    source.main()

    # OLS único, ventana móvil de 90 observaciones y coeficientes propios de Hábitat.
    build_habitat_ols()
    clarify_habitat_chart()
    ensure_latest_consistency()


if __name__ == "__main__":
    main()
