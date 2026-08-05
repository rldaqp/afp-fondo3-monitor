from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "rolling90"
PUBLIC_DATA = ROOT / "public" / "data"
PUBLIC_DATA.mkdir(parents=True, exist_ok=True)

sbs_path = DATA / "sbs_profuturo_f3.csv"
hist_path = DATA / "historical_predictions.csv"
calendar_path = DATA / "historical_calendar_predictions.csv"
pending_path = DATA / "pending_predictions.csv"

sbs = pd.read_csv(sbs_path) if sbs_path.exists() else pd.DataFrame()
hist = pd.read_csv(hist_path) if hist_path.exists() else pd.DataFrame()
calendar = pd.read_csv(calendar_path) if calendar_path.exists() else pd.DataFrame()
pending = pd.read_csv(pending_path) if pending_path.exists() else pd.DataFrame()

records: list[dict[str, object]] = []
historical_by_date: dict[str, dict[str, object]] = {}


def add_historical_predictions(frame: pd.DataFrame, source: str) -> None:
    """Incorpora estimaciones normales y luego rellenos de calendario."""
    if frame.empty:
        return
    work = frame.copy()
    work["fecha"] = pd.to_datetime(work["fecha"], errors="coerce")
    work["ret_estimado"] = pd.to_numeric(work.get("ret_estimado"), errors="coerce")
    for _, row in work.dropna(subset=["fecha"]).iterrows():
        key = row["fecha"].strftime("%Y-%m-%d")
        historical_by_date[key] = {
            "senal": None if pd.isna(row.get("senal")) else str(row.get("senal")),
            "ret_estimado": (
                None if pd.isna(row.get("ret_estimado")) else float(row.get("ret_estimado"))
            ),
            "estado_modelo": source,
        }


# Predicciones con factores completos.
add_historical_predictions(hist, "OLS FACTORES COMPLETOS")
# Fechas oficiales omitidas por cierres o rezagos de alguna fuente.
# El relleno solo completa la visualización/operación; no altera el entrenamiento.
add_historical_predictions(calendar, "OLS CALENDARIO COMPLETO")

# Fuente primaria de la simulación: todos los valores cuota oficiales disponibles.
if not sbs.empty:
    sbs["fecha"] = pd.to_datetime(sbs["fecha"], errors="coerce")
    sbs["valor_cuota"] = pd.to_numeric(sbs["valor_cuota"], errors="coerce")
    for _, row in sbs.dropna(subset=["fecha", "valor_cuota"]).iterrows():
        key = row["fecha"].strftime("%Y-%m-%d")
        model = historical_by_date.get(key, {})
        records.append(
            {
                "fecha": key,
                "vc": float(row["valor_cuota"]),
                "fuente": "SBS OFICIAL",
                "es_oficial": True,
                "senal": model.get("senal"),
                "ret_estimado": model.get("ret_estimado"),
                "estado_modelo": model.get("estado_modelo"),
            }
        )
# Respaldo para repositorios antiguos que todavía no tengan el CSV SBS consolidado.
elif not hist.empty:
    hist["fecha"] = pd.to_datetime(hist["fecha"], errors="coerce")
    hist["valor_cuota"] = pd.to_numeric(hist.get("valor_cuota"), errors="coerce")
    for _, row in hist.dropna(subset=["fecha", "valor_cuota"]).iterrows():
        key = row["fecha"].strftime("%Y-%m-%d")
        model = historical_by_date.get(key, {})
        records.append(
            {
                "fecha": key,
                "vc": float(row["valor_cuota"]),
                "fuente": "SBS OFICIAL",
                "es_oficial": True,
                "senal": model.get("senal"),
                "ret_estimado": model.get("ret_estimado"),
                "estado_modelo": model.get("estado_modelo"),
            }
        )

# Después del último VC oficial se agregan las estimaciones encadenadas pendientes.
if not pending.empty:
    pending["fecha"] = pd.to_datetime(pending["fecha"], errors="coerce")
    pending["valor_cuota_estimado"] = pd.to_numeric(
        pending["valor_cuota_estimado"], errors="coerce"
    )
    pending["ret_estimado"] = pd.to_numeric(
        pending.get("ret_estimado"), errors="coerce"
    )
    for _, row in pending.dropna(
        subset=["fecha", "valor_cuota_estimado"]
    ).iterrows():
        records.append(
            {
                "fecha": row["fecha"].strftime("%Y-%m-%d"),
                "vc": float(row["valor_cuota_estimado"]),
                "fuente": "MODELO OLS",
                "es_oficial": False,
                "senal": None if pd.isna(row.get("senal")) else str(row.get("senal")),
                "ret_estimado": (
                    None
                    if pd.isna(row.get("ret_estimado"))
                    else float(row.get("ret_estimado"))
                ),
                "estado_modelo": str(row.get("estado_fuentes", "PENDIENTE")),
            }
        )

# Una publicación oficial siempre prevalece sobre una estimación del mismo día.
by_date: dict[str, dict[str, object]] = {}
for row in sorted(records, key=lambda value: str(value["fecha"])):
    key = str(row["fecha"])
    previous = by_date.get(key)
    if (
        previous is None
        or bool(row.get("es_oficial"))
        or not bool(previous.get("es_oficial"))
    ):
        by_date[key] = row
records = [by_date[key] for key in sorted(by_date)]

if not records:
    raise RuntimeError("No se pudo construir la línea temporal de operación.")

# Control de integridad: ninguna fecha SBS puede desaparecer de la simulación.
if not sbs.empty:
    expected = {
        row["fecha"].strftime("%Y-%m-%d"): float(row["valor_cuota"])
        for _, row in sbs.dropna(subset=["fecha", "valor_cuota"]).iterrows()
    }
    published = {
        str(row["fecha"]): float(row["vc"])
        for row in records
        if bool(row.get("es_oficial"))
    }
    missing = sorted(set(expected) - set(published))
    mismatched = sorted(
        key
        for key in expected.keys() & published.keys()
        if abs(expected[key] - published[key]) > 1e-10
    )
    if missing or mismatched:
        raise RuntimeError(
            "Línea temporal inconsistente con SBS · "
            f"faltantes={missing[:10]} · valores distintos={mismatched[:10]}"
        )

# Desde que empieza el OLS, cada fecha oficial debe tener señal y retorno estimado.
model_dates = sorted(historical_by_date)
if model_dates:
    first_model_date = model_dates[0]
    missing_model = [
        row["fecha"]
        for row in records
        if bool(row.get("es_oficial"))
        and str(row["fecha"]) >= first_model_date
        and row.get("ret_estimado") is None
    ]
    if missing_model:
        raise RuntimeError(
            "Fechas SBS sin estimación OLS: " + ", ".join(missing_model[:20])
        )

(PUBLIC_DATA / "operation_series.json").write_text(
    json.dumps(records, ensure_ascii=False, indent=2),
    encoding="utf-8",
)

print(
    "operation_series.json creado con todos los VC SBS y calendario OLS completo · "
    f"{len(records)} filas · {records[0]['fecha']} -> {records[-1]['fecha']}"
)
