"""Ejecuta Hábitat con fuentes oficiales y estimación explícita del hueco de julio.

La presentación final separa VC SBS real, VC provisional de fechas pendientes y
VC estimado OLS, manteniendo continuidad visual sin confundir las fuentes.
"""

from __future__ import annotations

from urllib.parse import urljoin

import pandas as pd
import requests
from bs4 import BeautifulSoup
from pandas.tseries.holiday import (
    AbstractHolidayCalendar,
    GoodFriday,
    Holiday,
    USLaborDay,
    USMartinLutherKingJr,
    USMemorialDay,
    USPresidentsDay,
    USThanksgivingDay,
    nearest_workday,
)

import build_habitat_gap_aware as gap
import enrich_habitat_daily_sbs as source
from build_habitat_july_gap import main as build_july_gap
from postprocess_habitat_chart_clarity import main as clarify_habitat_chart
from postprocess_habitat_sbs_indicators import ensure_latest_consistency


class USMarketHolidayCalendar(AbstractHolidayCalendar):
    """Cierres regulares de NYSE relevantes para los factores Yahoo del OLS."""

    rules = [
        Holiday("New Year's Day", month=1, day=1, observance=nearest_workday),
        USMartinLutherKingJr,
        USPresidentsDay,
        GoodFriday,
        USMemorialDay,
        Holiday(
            "Juneteenth",
            month=6,
            day=19,
            start_date=pd.Timestamp("2022-06-19"),
            observance=nearest_workday,
        ),
        Holiday("Independence Day", month=7, day=4, observance=nearest_workday),
        USLaborDay,
        USThanksgivingDay,
        Holiday("Christmas Day", month=12, day=25, observance=nearest_workday),
    ]


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
    """Informa el hueco reciente; el motor de julio lo cubre como estimado."""
    profuturo = source.read_csv(source.PROFUTURO_PATH)
    if profuturo.empty or history.empty:
        return
    latest = pd.Timestamp(history["fecha"].max())
    start = pd.Timestamp("2026-07-01")
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


def install_market_holiday_rule() -> None:
    """Usa retorno 0 para ETF únicamente cuando NYSE estuvo oficialmente cerrado.

    Una fila con todos los factores bursátiles vacíos no se acepta de forma general.
    Solo se normaliza cuando la fecha pertenece al calendario de cierres de NYSE y
    el retorno USD/PEN del BCRP sí está disponible. Así, una falla ordinaria de
    descarga continúa deteniendo la publicación.
    """

    original = gap.build_gap_predictions

    def holiday_safe_predictions(
        sbs: pd.DataFrame,
        complete: pd.DataFrame,
        markets: pd.DataFrame,
        calendar: list[pd.Timestamp],
    ) -> pd.DataFrame:
        adjusted = markets.copy()
        adjusted["fecha"] = pd.to_datetime(adjusted["fecha"], errors="coerce").dt.normalize()
        valid_dates = adjusted["fecha"].dropna()
        if valid_dates.empty:
            return original(sbs, complete, adjusted, calendar)

        holidays = set(
            USMarketHolidayCalendar()
            .holidays(start=valid_dates.min(), end=valid_dates.max())
            .normalize()
        )
        equity_features = list(gap.base.EQUITY_FEATURES)
        normalized: list[pd.Timestamp] = []

        for date in sorted(holidays):
            date_mask = adjusted["fecha"].eq(date)
            if not bool(date_mask.any()):
                continue
            equity_missing = adjusted.loc[date_mask, equity_features].isna().all(axis=1)
            fx_available = adjusted.loc[date_mask, "ret_USD_PEN"].notna()
            safe_indexes = equity_missing.index[equity_missing & fx_available]
            if safe_indexes.empty:
                continue
            adjusted.loc[safe_indexes, equity_features] = 0.0
            normalized.append(pd.Timestamp(date).normalize())

        if normalized:
            print(
                "Cierre bursátil EE. UU. reconocido; retornos ETF = 0 % y "
                "USD/PEN BCRP conservado: "
                + ", ".join(date.strftime("%Y-%m-%d") for date in normalized)
            )
        return original(sbs, complete, adjusted, calendar)

    gap.build_gap_predictions = holiday_safe_predictions


def main() -> None:
    source.discover_monthly_urls = recent_monthly_urls
    source.validate_continuity = continuity_is_modelled
    source.main()

    install_market_holiday_rule()

    # Mismo método que Profuturo; solo cubre el hueco actual desde julio de 2026.
    build_july_gap()
    clarify_habitat_chart()
    ensure_latest_consistency()


if __name__ == "__main__":
    main()
