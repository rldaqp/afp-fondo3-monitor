from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "rolling90"
PUBLIC_DATA = ROOT / "public" / "data"
PUBLIC_DATA.mkdir(parents=True, exist_ok=True)

hist_path = DATA / "historical_predictions.csv"
pending_path = DATA / "pending_predictions.csv"

hist = pd.read_csv(hist_path) if hist_path.exists() else pd.DataFrame()
pending = pd.read_csv(pending_path) if pending_path.exists() else pd.DataFrame()

records: list[dict[str, object]] = []

# Replica build_monitor_timeline() del notebook:
# - histórico del modelo => VC oficial SBS de esa misma fila;
# - pendientes posteriores a SBS => VC estimado encadenado.
if not hist.empty:
    hist["fecha"] = pd.to_datetime(hist["fecha"], errors="coerce")
    hist["valor_cuota"] = pd.to_numeric(hist["valor_cuota"], errors="coerce")
    hist["ret_estimado"] = pd.to_numeric(hist.get("ret_estimado"), errors="coerce")
    for _, row in hist.dropna(subset=["fecha", "valor_cuota"]).iterrows():
        records.append({
            "fecha": row["fecha"].strftime("%Y-%m-%d"),
            "vc": float(row["valor_cuota"]),
            "fuente": "SBS OFICIAL",
            "es_oficial": True,
            "senal": None if pd.isna(row.get("senal")) else str(row.get("senal")),
            "ret_estimado": None if pd.isna(row.get("ret_estimado")) else float(row.get("ret_estimado")),
        })

if not pending.empty:
    pending["fecha"] = pd.to_datetime(pending["fecha"], errors="coerce")
    pending["valor_cuota_estimado"] = pd.to_numeric(pending["valor_cuota_estimado"], errors="coerce")
    pending["ret_estimado"] = pd.to_numeric(pending.get("ret_estimado"), errors="coerce")
    for _, row in pending.dropna(subset=["fecha", "valor_cuota_estimado"]).iterrows():
        records.append({
            "fecha": row["fecha"].strftime("%Y-%m-%d"),
            "vc": float(row["valor_cuota_estimado"]),
            "fuente": "MODELO OLS",
            "es_oficial": False,
            "senal": None if pd.isna(row.get("senal")) else str(row.get("senal")),
            "ret_estimado": None if pd.isna(row.get("ret_estimado")) else float(row.get("ret_estimado")),
        })

# Igual que el notebook: ordenar y conservar la última fila por fecha.
by_date: dict[str, dict[str, object]] = {}
for row in sorted(records, key=lambda x: str(x["fecha"])):
    by_date[str(row["fecha"])] = row
records = [by_date[k] for k in sorted(by_date)]

if not records:
    raise RuntimeError("No se pudo construir la línea temporal de operación del notebook.")

(PUBLIC_DATA / "operation_series.json").write_text(
    json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
)

print(
    "operation_series.json creado · "
    f"{len(records)} filas · {records[0]['fecha']} -> {records[-1]['fecha']}"
)
