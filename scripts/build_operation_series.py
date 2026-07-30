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
pending_path = DATA / "pending_predictions.csv"

sbs = pd.read_csv(sbs_path) if sbs_path.exists() else pd.DataFrame()
hist = pd.read_csv(hist_path) if hist_path.exists() else pd.DataFrame()
pending = pd.read_csv(pending_path) if pending_path.exists() else pd.DataFrame()

records: list[dict[str, object]] = []
historical_by_date: dict[str, dict[str, object]] = {}

# Las predicciones históricas solo existen cuando todos los factores del modelo
# están completos. Se usan para enriquecer la fila, nunca para decidir qué fechas
# oficiales SBS forman parte de la línea temporal de una operación.
if not hist.empty:
    hist["fecha"] = pd.to_datetime(hist["fecha"], errors="coerce")
    hist["ret_estimado"] = pd.to_numeric(hist.get("ret_estimado"), errors="coerce")
    for _, row in hist.dropna(subset=["fecha"]).iterrows():
        key = row["fecha"].strftime("%Y-%m-%d")
        historical_by_date[key] = {
            "senal": None if pd.isna(row.get("senal")) else str(row.get("senal")),
            "ret_estimado": (
                None if pd.isna(row.get("ret_estimado")) else float(row.get("ret_estimado"))
            ),
        }

# Fuente primaria de la simulación: todos los valores cuota oficiales disponibles,
# incluso cuando una fecha no pudo entrar al entrenamiento por faltar algún mercado.
if not sbs.empty:
    sbs["fecha"] = pd.to_datetime(sbs["fecha"], errors="coerce")
    sbs["valor_cuota"] = pd.to_numeric(sbs["valor_cuota"], errors="coerce")
    for _, row in sbs.dropna(subset=["fecha", "valor_cuota"]).iterrows():
        key = row["fecha"].strftime("%Y-%m-%d")
        model = historical_by_date.get(key, {})
        records.append({
            "fecha": key,
            "vc": float(row["valor_cuota"]),
            "fuente": "SBS OFICIAL",
            "es_oficial": True,
            "senal": model.get("senal"),
            "ret_estimado": model.get("ret_estimado"),
        })
# Respaldo para repositorios antiguos que todavía no tengan el CSV consolidado SBS.
elif not hist.empty:
    hist["valor_cuota"] = pd.to_numeric(hist.get("valor_cuota"), errors="coerce")
    for _, row in hist.dropna(subset=["fecha", "valor_cuota"]).iterrows():
        key = row["fecha"].strftime("%Y-%m-%d")
        records.append({
            "fecha": key,
            "vc": float(row["valor_cuota"]),
            "fuente": "SBS OFICIAL",
            "es_oficial": True,
            "senal": historical_by_date.get(key, {}).get("senal"),
            "ret_estimado": historical_by_date.get(key, {}).get("ret_estimado"),
        })

# Después del último VC oficial se agregan las estimaciones encadenadas pendientes.
if not pending.empty:
    pending["fecha"] = pd.to_datetime(pending["fecha"], errors="coerce")
    pending["valor_cuota_estimado"] = pd.to_numeric(
        pending["valor_cuota_estimado"], errors="coerce"
    )
    pending["ret_estimado"] = pd.to_numeric(pending.get("ret_estimado"), errors="coerce")
    for _, row in pending.dropna(subset=["fecha", "valor_cuota_estimado"]).iterrows():
        records.append({
            "fecha": row["fecha"].strftime("%Y-%m-%d"),
            "vc": float(row["valor_cuota_estimado"]),
            "fuente": "MODELO OLS",
            "es_oficial": False,
            "senal": None if pd.isna(row.get("senal")) else str(row.get("senal")),
            "ret_estimado": (
                None if pd.isna(row.get("ret_estimado")) else float(row.get("ret_estimado"))
            ),
        })

# Una publicación oficial siempre prevalece sobre una estimación del mismo día.
by_date: dict[str, dict[str, object]] = {}
for row in sorted(records, key=lambda x: str(x["fecha"])):
    key = str(row["fecha"])
    previous = by_date.get(key)
    if previous is None or bool(row.get("es_oficial")) or not bool(previous.get("es_oficial")):
        by_date[key] = row
records = [by_date[key] for key in sorted(by_date)]

if not records:
    raise RuntimeError("No se pudo construir la línea temporal de operación.")

# Control de integridad: ninguna fecha SBS puede desaparecer de la simulación y
# su valor debe coincidir exactamente con el archivo consolidado.
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
        key for key in expected.keys() & published.keys()
        if abs(expected[key] - published[key]) > 1e-10
    )
    if missing or mismatched:
        raise RuntimeError(
            "Línea temporal inconsistente con SBS · "
            f"faltantes={missing[:10]} · valores distintos={mismatched[:10]}"
        )

(PUBLIC_DATA / "operation_series.json").write_text(
    json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
)

print(
    "operation_series.json creado con todos los VC SBS · "
    f"{len(records)} filas · {records[0]['fecha']} -> {records[-1]['fecha']}"
)
