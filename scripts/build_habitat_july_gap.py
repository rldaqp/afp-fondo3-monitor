"""Limita la cobertura provisional de huecos al tramo pendiente de julio de 2026."""

from __future__ import annotations

import pandas as pd

import build_habitat_gap_aware as gap

GAP_START = pd.Timestamp("2026-07-01")
_original_missing_runs = gap.missing_runs


def july_missing_runs(
    calendar: list[pd.Timestamp],
    official_dates: set[pd.Timestamp],
) -> list[dict[str, object]]:
    """Ignora ausencias antiguas y cubre solo el hueco actual de publicación SBS."""
    runs = _original_missing_runs(calendar, official_dates)
    selected: list[dict[str, object]] = []
    for run in runs:
        missing = [pd.Timestamp(value).normalize() for value in run.get("missing", [])]
        if not missing or min(missing) < GAP_START:
            continue
        selected.append(run)
    return selected


def july_validate(
    calendar: list[pd.Timestamp],
    sbs: pd.DataFrame,
    signals: list[dict[str, object]],
    series: list[dict[str, object]],
    latest: dict,
    train: pd.DataFrame,
) -> list[str]:
    if len(train) != gap.base.WINDOW:
        raise AssertionError("La ventana vigente no tiene 90 observaciones.")

    official = {
        pd.Timestamp(value).normalize()
        for value in pd.to_datetime(sbs["fecha"], errors="coerce").dropna()
    }
    end = max(official)
    pending_dates = [
        pd.Timestamp(date).normalize()
        for date in calendar
        if GAP_START <= pd.Timestamp(date).normalize() <= end
        and pd.Timestamp(date).normalize() not in official
    ]

    signal_by_date = {str(row["fecha"]): row for row in signals}
    series_by_date = {str(row["fecha"]): row for row in series}
    for date in pending_dates:
        key = date.strftime("%Y-%m-%d")
        signal = signal_by_date.get(key)
        operation = series_by_date.get(key)
        if not signal or signal.get("tipo") != "SBS_PENDIENTE":
            raise AssertionError(f"Falta estimación identificada para {key}.")
        if signal.get("vc_real") is not None or float(signal["vc_estimado"]) <= 0:
            raise AssertionError(f"Estimación SBS pendiente inválida: {key}.")
        if not operation or operation.get("fuente") != "MODELO OLS · SBS PENDIENTE":
            raise AssertionError(f"La línea temporal omite el gap {key}.")

    if pending_dates:
        boundary_candidates = sorted(date for date in official if date > pending_dates[-1])
        if boundary_candidates:
            boundary_key = boundary_candidates[0].strftime("%Y-%m-%d")
            boundary = signal_by_date.get(boundary_key)
            if not boundary or boundary.get("tipo") != "HISTORICO_GAP":
                raise AssertionError(
                    f"El primer VC oficial posterior al hueco no compara real vs estimado: {boundary_key}."
                )
            if boundary.get("vc_real") is None or boundary.get("vc_estimado") is None:
                raise AssertionError(f"Comparación incompleta en {boundary_key}.")

    if latest.get("methodology_parity_verified") is not True:
        raise AssertionError("No se certificó la paridad metodológica.")
    return [date.strftime("%Y-%m-%d") for date in pending_dates]


def main() -> None:
    gap.missing_runs = july_missing_runs
    gap.validate = july_validate
    gap.main()


if __name__ == "__main__":
    main()
