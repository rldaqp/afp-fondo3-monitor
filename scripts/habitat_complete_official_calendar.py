"""Garantiza una estimación OLS para cada fecha con VC oficial de Hábitat.

La corrección es exclusiva de Hábitat. Las fechas oficiales se conservan aunque
algún mercado esté cerrado o una fuente diaria no publique por feriado.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

import build_habitat_exact_parity as habitat

ROOT = Path(__file__).resolve().parents[1]
SBS_PATH = ROOT / "data" / "rolling90" / "sbs_habitat_f3.csv"
SIGNALS_PATH = ROOT / "public" / "habitat" / "data" / "signals.json"


def build_complete_official_calendar(
    sbs: pd.DataFrame,
    markets: pd.DataFrame,
) -> pd.DataFrame:
    """Construye el OLS sobre el calendario SBS, sin perder feriados oficiales."""
    target = sbs.copy()
    target["ret_habitat"] = target["valor_cuota"].pct_change(fill_method=None)
    target["ret_profuturo"] = target["ret_habitat"]

    complete = target.merge(
        markets[["fecha", *habitat.FEATURES]],
        on="fecha",
        how="left",
        validate="one_to_one",
    )
    complete = complete.loc[
        complete["fecha"] >= pd.Timestamp("2025-01-01")
    ].copy()

    for feature in habitat.FEATURES:
        complete[feature] = pd.to_numeric(complete[feature], errors="coerce")

    # En feriados peruanos BCRP puede no publicar USD/PEN aunque la SBS sí tenga VC.
    # Primero se usa PEN=X; 0 % queda como último respaldo si tampoco existe Yahoo.
    yahoo_fx = habitat.profuturo._penx_daily_returns()
    missing_fx = complete["ret_USD_PEN"].isna()
    if missing_fx.any():
        fallback = complete.loc[missing_fx, "fecha"].map(
            lambda value: yahoo_fx.get(pd.Timestamp(value).normalize())
        )
        complete.loc[missing_fx, "ret_USD_PEN"] = pd.to_numeric(
            fallback, errors="coerce"
        ).to_numpy()

    fallback_log: list[str] = []
    for feature in habitat.FEATURES:
        missing = complete[feature].isna()
        if missing.any():
            dates = complete.loc[missing, "fecha"].dt.strftime("%Y-%m-%d").tolist()
            fallback_log.append(f"{feature}: {', '.join(dates[-15:])}")
            # Retorno 0 % representa cierre/no publicación del mercado en esa fecha.
            complete.loc[missing, feature] = 0.0

    complete = (
        complete.dropna(
            subset=["valor_cuota", "ret_habitat", "ret_profuturo"]
        )
        .sort_values("fecha")
        .drop_duplicates("fecha", keep="last")
        .reset_index(drop=True)
    )

    if complete[habitat.FEATURES].isna().any().any():
        raise RuntimeError("Persisten factores faltantes en fechas oficiales de Hábitat.")
    if not np.isfinite(complete[habitat.FEATURES].to_numpy(float)).all():
        raise RuntimeError("Existen factores no finitos en el calendario oficial de Hábitat.")
    if len(complete) < habitat.WINDOW:
        raise RuntimeError(
            f"Hábitat solo tiene {len(complete)} observaciones utilizables; "
            f"se requieren {habitat.WINDOW}."
        )

    if fallback_log:
        print("Factores sustituidos para conservar fechas SBS oficiales:")
        for item in fallback_log:
            print(" - " + item)
    return complete


def install() -> None:
    """Instala la regla solo en el módulo de construcción de Hábitat."""
    habitat.build_complete = build_complete_official_calendar


def validate_official_estimate_calendar() -> float:
    """Comprueba que todo VC SBS modelable tenga su VC estimado OLS."""
    sbs = pd.read_csv(SBS_PATH)
    sbs["fecha"] = pd.to_datetime(sbs["fecha"], errors="coerce")
    sbs["valor_cuota"] = pd.to_numeric(sbs["valor_cuota"], errors="coerce")
    sbs = (
        sbs.dropna(subset=["fecha", "valor_cuota"])
        .sort_values("fecha")
        .drop_duplicates("fecha", keep="last")
    )

    signals = json.loads(SIGNALS_PATH.read_text(encoding="utf-8"))
    historical = {
        pd.Timestamp(row["fecha"]).normalize(): row
        for row in signals
        if row.get("tipo") == "HISTORICO"
        and row.get("vc_real") is not None
        and row.get("vc_estimado") is not None
    }
    if not historical:
        raise AssertionError("No existen predicciones históricas OLS de Hábitat.")

    first_model_date = min(historical)
    expected = sbs.loc[sbs["fecha"] >= first_model_date, ["fecha", "valor_cuota"]]
    missing = [
        pd.Timestamp(row.fecha).normalize()
        for row in expected.itertuples()
        if pd.Timestamp(row.fecha).normalize() not in historical
    ]
    if missing:
        raise AssertionError(
            "Hay VC SBS sin VC estimado OLS: "
            + ", ".join(date.strftime("%Y-%m-%d") for date in missing)
        )

    for row in expected.itertuples():
        date = pd.Timestamp(row.fecha).normalize()
        signal = historical[date]
        if abs(float(signal["vc_real"]) - float(row.valor_cuota)) > 1e-9:
            raise AssertionError(f"El VC real no coincide con SBS en {date:%Y-%m-%d}.")
        if not np.isfinite(float(signal["vc_estimado"])):
            raise AssertionError(f"El VC estimado no es válido en {date:%Y-%m-%d}.")

    holiday = pd.Timestamp("2026-07-28")
    if holiday not in historical:
        raise AssertionError("El 28/07/2026 tiene VC SBS pero no VC estimado OLS.")
    if abs(float(historical[holiday]["vc_real"]) - 31.6169856) > 1e-9:
        raise AssertionError("El VC SBS del 28/07/2026 no coincide con 31.6169856.")

    estimate = float(historical[holiday]["vc_estimado"])
    print(
        "Calendario SBS–OLS completo: "
        f"{len(expected)} fechas verificadas; 28/07/2026 estimado={estimate:.7f}"
    )
    return estimate
