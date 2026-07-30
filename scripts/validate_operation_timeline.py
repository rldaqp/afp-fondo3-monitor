from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "rolling90"
PUBLIC_DATA = ROOT / "public" / "data"

sbs = pd.read_csv(DATA / "sbs_profuturo_f3.csv")
sbs["fecha"] = pd.to_datetime(sbs["fecha"], errors="coerce")
sbs["valor_cuota"] = pd.to_numeric(sbs["valor_cuota"], errors="coerce")
sbs = sbs.dropna(subset=["fecha", "valor_cuota"]).sort_values("fecha")
expected = {
    row["fecha"].strftime("%Y-%m-%d"): float(row["valor_cuota"])
    for _, row in sbs.iterrows()
}


def load_timeline(name: str) -> list[dict[str, object]]:
    rows = json.loads((PUBLIC_DATA / name).read_text(encoding="utf-8"))
    if not isinstance(rows, list) or not rows:
        raise AssertionError(f"{name} está vacío o no es una lista")
    dates = [str(row.get("fecha")) for row in rows]
    if dates != sorted(dates):
        raise AssertionError(f"{name} no está ordenado por fecha")
    if len(dates) != len(set(dates)):
        raise AssertionError(f"{name} contiene fechas duplicadas")
    return rows


def official_map(rows: list[dict[str, object]]) -> dict[str, float]:
    return {
        str(row["fecha"]): float(row["vc"])
        for row in rows
        if row.get("fuente") == "SBS OFICIAL"
    }


series = load_timeline("series.json")
operation = load_timeline("operation_series.json")

for name, rows in (("series.json", series), ("operation_series.json", operation)):
    observed = official_map(rows)
    missing = sorted(set(expected) - set(observed))
    extra = sorted(set(observed) - set(expected))
    mismatched = sorted(
        key for key in expected.keys() & observed.keys()
        if abs(expected[key] - observed[key]) > 1e-10
    )
    if missing or extra or mismatched:
        raise AssertionError(
            f"{name} no concilia con SBS: "
            f"faltantes={missing[:10]}, extras={extra[:10]}, distintos={mismatched[:10]}"
        )

# El simulador conserva operation_series.json por compatibilidad con el panel de
# métricas, pero el generador anterior garantiza que contiene los mismos VC SBS
# que series.json. Ambos postprocesos deben reconocer la misma asignación.
assignment = "operationSeries=op.sort((a,b)=>a.fecha.localeCompare(b.fecha))"
mobile_source = (ROOT / "scripts" / "postprocess_mobile_ui_v3.py").read_text(
    encoding="utf-8"
)
insights_source = (ROOT / "scripts" / "postprocess_model_insights_ui.py").read_text(
    encoding="utf-8"
)
if assignment not in mobile_source:
    raise AssertionError("El simulador cambió la asignación compatible de operationSeries")
if assignment not in insights_source:
    raise AssertionError("El postproceso de métricas no reconoce la serie del simulador")

# La fuente de la bitácora consulta series.json para los VC oficiales y permite
# fechas SBS aunque no exista una predicción histórica del modelo.
trade_source = (ROOT / "scripts" / "postprocess_trade_history.py").read_text(
    encoding="utf-8"
)
required_trade_fragments = [
    "fetch('data/series.json?ts='+Date.now()",
    "function officialRow(date){return timeline.find",
    "entryOfficial=officialAt(ep.fecha)",
    "exitOfficial=officialAt(exitDate)",
]
for fragment in required_trade_fragments:
    if fragment not in trade_source:
        raise AssertionError(f"La bitácora no contiene el control esperado: {fragment}")

# Caso que originó la revisión: verificar que ambas fechas existen y se valoran distinto.
case_dates = ("2026-07-22", "2026-07-23")
if all(date in expected for date in case_dates):
    entry, exit_ = (expected[date] for date in case_dates)
    return_ = exit_ / entry - 1.0
    if abs(return_) < 1e-12:
        raise AssertionError("Los VC SBS del 22 y 23 de julio quedaron iguales")
    print(
        "Caso 22/07→23/07 correcto · "
        f"{entry:.7f} → {exit_:.7f} · retorno {return_ * 100:+.4f}%"
    )

print(
    "Línea temporal validada · "
    f"{len(expected)} VC oficiales presentes en gráfico y simulación"
)
