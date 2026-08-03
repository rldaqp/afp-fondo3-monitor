"""Construye Hábitat con paridad Profuturo y cubre huecos SBS con estimaciones OLS.

Los huecos nunca se presentan como datos oficiales. Se estiman con el mismo
LinearRegression, ventana 90 y factores de Profuturo, pero con coeficientes
entrenados exclusivamente sobre retornos diarios válidos de Hábitat.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

import build_habitat_exact_parity as base

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "rolling90"
PUBLIC = ROOT / "public" / "habitat"
PUBLIC_DATA = PUBLIC / "data"
PROFUTURO_PATH = DATA / "sbs_profuturo_f3.csv"


def official_calendar(sbs: pd.DataFrame) -> list[pd.Timestamp]:
    profuturo = base.read_csv(PROFUTURO_PATH)
    profuturo = (
        profuturo.dropna(subset=["fecha"])
        .sort_values("fecha")
        .drop_duplicates("fecha", keep="last")
    )
    start = pd.Timestamp(sbs["fecha"].min()).normalize()
    end = pd.Timestamp(sbs["fecha"].max()).normalize()
    dates = [
        pd.Timestamp(value).normalize()
        for value in profuturo.loc[
            profuturo["fecha"].between(start, end, inclusive="both"), "fecha"
        ]
    ]
    if not dates:
        raise RuntimeError("No existe calendario oficial de referencia del Fondo 3.")
    return sorted(dict.fromkeys(dates))


def build_complete_gap_aware(
    sbs: pd.DataFrame,
    markets: pd.DataFrame,
) -> tuple[pd.DataFrame, list[pd.Timestamp]]:
    """Solo admite retornos diarios entre dos fechas oficiales consecutivas.

    Así, el cambio 30/06 -> 21/07 jamás se interpreta como retorno de un día.
    """
    calendar = official_calendar(sbs)
    previous_by_date = {
        calendar[index]: calendar[index - 1]
        for index in range(1, len(calendar))
    }
    official_values = {
        pd.Timestamp(row.fecha).normalize(): float(row.valor_cuota)
        for row in sbs.itertuples()
    }

    target = sbs.copy()
    target["fecha"] = pd.to_datetime(target["fecha"]).dt.normalize()
    target["fecha_previa_calendario"] = target["fecha"].map(previous_by_date)
    target["valor_cuota_previo"] = target["fecha_previa_calendario"].map(
        official_values
    )
    target["ret_habitat"] = (
        pd.to_numeric(target["valor_cuota"], errors="coerce")
        / pd.to_numeric(target["valor_cuota_previo"], errors="coerce")
        - 1.0
    )
    target["ret_profuturo"] = target["ret_habitat"]

    complete = target.merge(
        markets[["fecha", *base.FEATURES]],
        on="fecha",
        how="inner",
        validate="one_to_one",
    )
    complete = (
        complete.loc[complete["fecha"] >= pd.Timestamp("2025-01-01")]
        .dropna(
            subset=[
                "valor_cuota",
                "valor_cuota_previo",
                "ret_habitat",
                "ret_profuturo",
                *base.FEATURES,
            ]
        )
        .sort_values("fecha")
        .drop_duplicates("fecha", keep="last")
        .reset_index(drop=True)
    )
    if len(complete) < base.WINDOW:
        raise RuntimeError(
            f"Hábitat solo tiene {len(complete)} retornos diarios válidos; "
            f"se requieren {base.WINDOW}."
        )
    return complete, calendar


def missing_runs(
    calendar: list[pd.Timestamp],
    official_dates: set[pd.Timestamp],
) -> list[dict[str, object]]:
    runs: list[dict[str, object]] = []
    index = 0
    while index < len(calendar):
        if calendar[index] in official_dates:
            index += 1
            continue
        start_index = index
        while index < len(calendar) and calendar[index] not in official_dates:
            index += 1
        missing = calendar[start_index:index]
        previous = calendar[start_index - 1] if start_index > 0 else None
        boundary = calendar[index] if index < len(calendar) else None
        if previous is not None and previous in official_dates:
            runs.append(
                {
                    "missing": missing,
                    "previous": previous,
                    "boundary": boundary if boundary in official_dates else None,
                }
            )
    return runs


def build_gap_predictions(
    sbs: pd.DataFrame,
    complete: pd.DataFrame,
    markets: pd.DataFrame,
    calendar: list[pd.Timestamp],
) -> pd.DataFrame:
    official_values = {
        pd.Timestamp(row.fecha).normalize(): float(row.valor_cuota)
        for row in sbs.itertuples()
    }
    market_by_date = markets.set_index(pd.to_datetime(markets["fecha"]).dt.normalize())
    rows: list[dict[str, object]] = []

    for run in missing_runs(calendar, set(official_values)):
        missing = list(run["missing"])
        previous = pd.Timestamp(run["previous"])
        boundary = run["boundary"]
        if not missing:
            continue

        train = complete.loc[complete["fecha"] < missing[0]].tail(base.WINDOW)
        if len(train) != base.WINDOW:
            raise RuntimeError(
                f"No hay 90 observaciones previas para estimar el hueco {missing[0]:%Y-%m-%d}."
            )
        fitted = base.fit_model(train)
        estimated_base = float(official_values[previous])
        prediction_dates = [*missing]
        if boundary is not None:
            prediction_dates.append(pd.Timestamp(boundary))

        for date in prediction_dates:
            if date not in market_by_date.index:
                raise RuntimeError(
                    f"No existe mercado para estimar la fecha SBS pendiente {date:%Y-%m-%d}."
                )
            market_row = market_by_date.loc[date]
            if isinstance(market_row, pd.DataFrame):
                market_row = market_row.iloc[-1]
            if any(pd.isna(market_row.get(feature)) for feature in base.FEATURES):
                raise RuntimeError(
                    f"Fuentes históricas incompletas para {date:%Y-%m-%d}; "
                    "no se aplicará un respaldo provisional dentro del histórico."
                )

            estimate_return = base.predict(fitted, market_row)
            estimated_vc = estimated_base * (1.0 + estimate_return)
            real_vc = official_values.get(date)
            rows.append(
                {
                    "fecha": date,
                    "modelo": "OLS",
                    "valor_cuota": np.nan if real_vc is None else real_vc,
                    "valor_cuota_anterior": estimated_base,
                    "ret_real": np.nan,
                    "ret_estimado": estimate_return,
                    "valor_cuota_estimado": estimated_vc,
                    "senal": base.classify(estimate_return),
                    "ventana_inicio": train.iloc[0]["fecha"],
                    "ventana_fin": train.iloc[-1]["fecha"],
                    "n_entrenamiento": base.WINDOW,
                    "tipo_gap": (
                        "SBS_PENDIENTE" if real_vc is None else "CIERRE_DE_GAP"
                    ),
                    "base_estimada": True,
                }
            )
            estimated_base = estimated_vc

    return pd.DataFrame(rows)


def build_signals(
    historical: pd.DataFrame,
    gaps: pd.DataFrame,
    pending: pd.DataFrame,
) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for row in historical.itertuples():
        records.append(
            {
                "fecha": pd.Timestamp(row.fecha).strftime("%Y-%m-%d"),
                "ret_estimado": float(row.ret_estimado),
                "senal": str(row.senal),
                "vc_real": float(row.valor_cuota),
                "vc_estimado": float(row.valor_cuota_estimado),
                "tipo": "HISTORICO",
                "fuente": "SBS OFICIAL + MODELO OLS",
            }
        )
    if not gaps.empty:
        for row in gaps.itertuples():
            is_pending = str(row.tipo_gap) == "SBS_PENDIENTE"
            records.append(
                {
                    "fecha": pd.Timestamp(row.fecha).strftime("%Y-%m-%d"),
                    "ret_estimado": float(row.ret_estimado),
                    "senal": str(row.senal),
                    "vc_real": None if is_pending else float(row.valor_cuota),
                    "vc_estimado": float(row.valor_cuota_estimado),
                    "tipo": "SBS_PENDIENTE" if is_pending else "HISTORICO_GAP",
                    "fuente": (
                        "MODELO OLS · SBS PENDIENTE"
                        if is_pending
                        else "SBS OFICIAL + ESTIMACIÓN ENCADENADA DEL GAP"
                    ),
                }
            )
    if not pending.empty:
        for row in pending.itertuples():
            records.append(
                {
                    "fecha": pd.Timestamp(row.fecha).strftime("%Y-%m-%d"),
                    "ret_estimado": float(row.ret_estimado),
                    "senal": str(row.senal),
                    "vc_real": None,
                    "vc_estimado": float(row.valor_cuota_estimado),
                    "tipo": "PENDIENTE",
                    "fuente": "MODELO OLS · POSTERIOR AL ÚLTIMO VC SBS",
                }
            )
    by_date: dict[str, dict[str, object]] = {}
    priority = {"HISTORICO": 4, "HISTORICO_GAP": 3, "SBS_PENDIENTE": 2, "PENDIENTE": 1}
    for record in records:
        key = str(record["fecha"])
        previous = by_date.get(key)
        if previous is None or priority[str(record["tipo"])] > priority[str(previous["tipo"])]:
            by_date[key] = record
    return [by_date[key] for key in sorted(by_date)]


def build_series(
    sbs: pd.DataFrame,
    gaps: pd.DataFrame,
    pending: pd.DataFrame,
    signals: list[dict[str, object]],
) -> list[dict[str, object]]:
    signal_by_date = {str(row["fecha"]): row for row in signals}
    records: list[dict[str, object]] = []
    for row in sbs.itertuples():
        date = pd.Timestamp(row.fecha).strftime("%Y-%m-%d")
        signal = signal_by_date.get(date, {})
        records.append(
            {
                "fecha": date,
                "vc": float(row.valor_cuota),
                "fuente": "SBS OFICIAL",
                "es_oficial": True,
                "senal": signal.get("senal"),
                "ret_estimado": signal.get("ret_estimado"),
            }
        )
    if not gaps.empty:
        for row in gaps.loc[gaps["tipo_gap"] == "SBS_PENDIENTE"].itertuples():
            records.append(
                {
                    "fecha": pd.Timestamp(row.fecha).strftime("%Y-%m-%d"),
                    "vc": float(row.valor_cuota_estimado),
                    "fuente": "MODELO OLS · SBS PENDIENTE",
                    "es_oficial": False,
                    "senal": str(row.senal),
                    "ret_estimado": float(row.ret_estimado),
                }
            )
    if not pending.empty:
        for row in pending.itertuples():
            records.append(
                {
                    "fecha": pd.Timestamp(row.fecha).strftime("%Y-%m-%d"),
                    "vc": float(row.valor_cuota_estimado),
                    "fuente": "MODELO OLS",
                    "es_oficial": False,
                    "senal": str(row.senal),
                    "ret_estimado": float(row.ret_estimado),
                }
            )
    by_date: dict[str, dict[str, object]] = {}
    for record in sorted(records, key=lambda item: str(item["fecha"])):
        key = str(record["fecha"])
        previous = by_date.get(key)
        if previous is None or bool(record["es_oficial"]):
            by_date[key] = record
    return [by_date[key] for key in sorted(by_date)]


def patch_html(gap_dates: list[str]) -> None:
    path = PUBLIC / "index.html"
    html = path.read_text(encoding="utf-8")
    start = "<!-- HABITAT_GAP_NOTICE START -->"
    end = "<!-- HABITAT_GAP_NOTICE END -->"
    if start in html and end in html:
        before, rest = html.split(start, 1)
        _, after = rest.split(end, 1)
        html = before + after

    dates_text = ", ".join(date.split("-")[2] + "/07" for date in gap_dates)
    notice = f"""
{start}
<div class="monitor-help" id="habitatGapNotice">
  <b>Tramo SBS pendiente:</b> la SBS aún no publicó el Excel mensual de julio.
  Los días {dates_text} se muestran con VC estimado OLS encadenado y no se usan
  como retornos reales para entrenar el modelo. Se reemplazarán automáticamente
  cuando la SBS publique los valores oficiales.
</div>
{end}
"""
    anchor = '<section class="panel" id="modelInsightsPanel">'
    html = html.replace(anchor, notice + "\n" + anchor, 1)

    old = (
        "{x:est.map(x=>x.fecha),y:est.map(x=>x.vc_estimado),mode:'lines+markers',"
        "name:'VC estimado OLS',customdata:est.map(x=>x.senal),hovertemplate:"
        "'<b>%{x}</b><br>VC estimado: %{y:.7f}<br>Señal: %{customdata}<extra></extra>'}"
    )
    new = (
        "{x:est.map(x=>x.fecha),y:est.map(x=>x.vc_estimado),mode:'lines+markers',"
        "name:'VC estimado OLS',marker:{color:est.map(x=>x.tipo==='SBS_PENDIENTE'"
        "?'#fbbf24':signalColor(x.senal)),size:est.map(x=>x.tipo==='SBS_PENDIENTE'?10:7)},"
        "customdata:est.map(x=>[x.senal,x.tipo]),hovertemplate:"
        "'<b>%{x}</b><br>VC estimado: %{y:.7f}<br>Señal: %{customdata[0]}"
        "<br>Estado: %{customdata[1]}<extra></extra>'}"
    )
    html = html.replace(old, new)
    path.write_text(html, encoding="utf-8")


def validate(
    calendar: list[pd.Timestamp],
    sbs: pd.DataFrame,
    signals: list[dict[str, object]],
    series: list[dict[str, object]],
    latest: dict,
    train: pd.DataFrame,
) -> list[str]:
    if len(train) != base.WINDOW:
        raise AssertionError("La ventana vigente no tiene 90 observaciones.")
    official = {pd.Timestamp(value).normalize() for value in sbs["fecha"]}
    gaps = [date for date in calendar if date not in official]
    signal_by_date = {str(row["fecha"]): row for row in signals}
    series_by_date = {str(row["fecha"]): row for row in series}
    for date in gaps:
        key = date.strftime("%Y-%m-%d")
        signal = signal_by_date.get(key)
        operation = series_by_date.get(key)
        if not signal or signal.get("tipo") != "SBS_PENDIENTE":
            raise AssertionError(f"Falta estimación identificada para {key}.")
        if signal.get("vc_real") is not None or float(signal["vc_estimado"]) <= 0:
            raise AssertionError(f"Estimación SBS pendiente inválida: {key}.")
        if not operation or operation.get("fuente") != "MODELO OLS · SBS PENDIENTE":
            raise AssertionError(f"La línea temporal omite el gap {key}.")
    if latest.get("methodology_parity_verified") is not True:
        raise AssertionError("No se certificó la paridad metodológica.")
    return [date.strftime("%Y-%m-%d") for date in gaps]


def main() -> None:
    sbs, markets, market_note = base.prepare_inputs()
    complete, calendar = build_complete_gap_aware(sbs, markets)
    historical = base.historical_predictions(complete)
    gaps = build_gap_predictions(sbs, complete, markets, calendar)
    pending, fitted, train = base.pending_predictions(sbs, complete, markets)
    signals = build_signals(historical, gaps, pending)
    series = build_series(sbs, gaps, pending, signals)
    latest, insights = base.model_outputs(
        sbs,
        markets,
        historical,
        pending,
        fitted,
        train,
        market_note,
    )

    gap_dates = validate(calendar, sbs, signals, series, latest, train)
    latest["official_gap_dates"] = gap_dates
    latest["estimated_gap_count"] = len(gap_dates)
    latest["sbs_gap_status"] = "SBS JULIO PENDIENTE · CUBIERTO POR MODELO OLS"
    latest["gap_policy"] = (
        "Las fechas sin VC SBS se estiman en cadena desde el último VC oficial. "
        "No se usan como variable objetivo ni como retornos reales de entrenamiento."
    )
    latest["warnings"] = [
        *latest.get("warnings", []),
        f"La SBS aún no publicó {len(gap_dates)} VC diarios de julio; el visor los identifica como estimados.",
    ]
    insights["quality"]["status"] = "PROVISIONAL"
    insights["quality"]["warnings"] = [
        *insights["quality"].get("warnings", []),
        f"{len(gap_dates)} fechas internas están estimadas por publicación SBS pendiente.",
    ]

    base.write_json("signals.json", signals)
    base.write_json("series.json", series)
    base.write_json("operation_series.json", series)
    base.write_json("latest.json", latest)
    base.write_json("model_insights.json", insights)
    base.write_json("live_market.json", base.live_market(latest, markets))
    base.ui.build_html()
    patch_html(gap_dates)

    print(
        "Hábitat gap-aware aprobado · misma metodología Profuturo · "
        f"{len(gap_dates)} fechas SBS pendientes estimadas · "
        f"ventana {latest['training_start']} -> {latest['training_end']}."
    )


if __name__ == "__main__":
    main()
