from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SBS_PATH = ROOT / "data" / "rolling90" / "sbs_profuturo_f3.csv"
SERIES_PATH = ROOT / "public" / "data" / "series.json"
SIGNALS_PATH = ROOT / "public" / "data" / "signals.json"

if not SBS_PATH.exists():
    raise RuntimeError("Falta data/rolling90/sbs_profuturo_f3.csv")

sbs = pd.read_csv(SBS_PATH)
sbs["fecha"] = pd.to_datetime(sbs["fecha"], errors="coerce")
sbs["valor_cuota"] = pd.to_numeric(sbs["valor_cuota"], errors="coerce")
sbs = sbs.dropna(subset=["fecha", "valor_cuota"]).sort_values("fecha").drop_duplicates("fecha", keep="last")

if SERIES_PATH.exists():
    series = json.loads(SERIES_PATH.read_text(encoding="utf-8"))
else:
    series = []

if SIGNALS_PATH.exists():
    signals = json.loads(SIGNALS_PATH.read_text(encoding="utf-8"))
else:
    signals = []

signal_by_date = {
    str(r.get("fecha", ""))[:10]: r
    for r in signals
    if isinstance(r, dict) and r.get("fecha")
}

by_date: dict[str, dict[str, object]] = {}
for row in series:
    if not isinstance(row, dict) or not row.get("fecha"):
        continue
    by_date[str(row["fecha"])[:10]] = dict(row)

for _, row in sbs.iterrows():
    fecha = pd.Timestamp(row["fecha"]).strftime("%Y-%m-%d")
    vc = float(row["valor_cuota"])
    old = by_date.get(fecha, {})
    sig = signal_by_date.get(fecha, {})
    by_date[fecha] = {
        "fecha": fecha,
        "vc": vc,
        "fuente": "SBS OFICIAL",
        "senal": old.get("senal", sig.get("senal")),
        "ret_estimado": old.get("ret_estimado", sig.get("ret_estimado")),
    }

out = [by_date[k] for k in sorted(by_date)]
SERIES_PATH.parent.mkdir(parents=True, exist_ok=True)
SERIES_PATH.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

latest = sbs.iloc[-1]
latest_date = pd.Timestamp(latest["fecha"]).strftime("%Y-%m-%d")
latest_vc = float(latest["valor_cuota"])
published = next((r for r in reversed(out) if r.get("fuente") == "SBS OFICIAL"), None)
if published is None or published.get("fecha") != latest_date or abs(float(published.get("vc")) - latest_vc) > 1e-10:
    raise RuntimeError("series.json no quedó sincronizado con el último SBS")

print(f"series.json sincronizado con SBS hasta {latest_date} · VC {latest_vc:.7f}")
