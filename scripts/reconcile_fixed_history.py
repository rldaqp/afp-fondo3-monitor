"""Publish SBS, history and the confirmed close as one consistent generation."""
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fixed_model_contract import FACTORS, recalculate, validate_snapshot
from build_fixed_levels_returns_monitor import (
    LEVEL_COEFF, RETURN_COEFF, TRAIN_R2_LEVEL, TRAIN_R2_RETURN,
    TRAIN_ADJ_R2_LEVEL, TRAIN_ADJ_R2_RETURN,
    TRAIN_STDERR_LEVEL, TRAIN_STDERR_RETURN,
)

ROOT = Path(__file__).resolve().parents[1]


def read_official(root=ROOT):
    with (root / "data/rolling90/sbs_profuturo_f3.csv").open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == len({r["fecha"] for r in rows}), "SBS con fechas duplicadas"
    return {r["fecha"]: float(r["valor_cuota"]) for r in rows}


def write_rows(path, rows):
    fields = list(rows[0])
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def cache_close(root, snap):
    prices = {t["ticker"]: t["price_current"] for t in snap["tickers"]}
    for name, factors in (("yahoo_levels_2026.csv", FACTORS[:-1]), ("spblscup_levels_2026.csv", ["SPBLSCUP"])):
        path = root / "data/fixed_models" / name
        with path.open(encoding="utf-8") as f:
            rows = {r["fecha"]: r for r in csv.DictReader(f)}
        rows[snap["signal_date"]] = {"fecha": snap["signal_date"], **{f: prices[f] for f in factors},
                                    "source": "CIERRE REGULAR VERIFICADO · TIMESTAMP PROPIO"}
        write_rows(path, [rows[k] for k in sorted(rows)])


def synchronize_calibration(base):
    """Persist the approved 30-SBS-session OLS coefficients before each snapshot."""
    base["model_version"] = "v3-30vc-through-20260930"
    base["training"].update({
        "start": "2026-08-19", "end": "2026-09-30", "n": 30,
        "levels_r2": TRAIN_R2_LEVEL, "returns_r2": TRAIN_R2_RETURN,
        "levels_adjusted_r2": TRAIN_ADJ_R2_LEVEL,
        "returns_adjusted_r2": TRAIN_ADJ_R2_RETURN,
        "levels_standard_error": TRAIN_STDERR_LEVEL,
        "returns_standard_error": TRAIN_STDERR_RETURN,
    })
    base["models"]["niveles"] = {
        "coefficients": LEVEL_COEFF,
        "equation": "VC = 13.88935016 - 0.03515844·SPY + 0.74157875·EEM - 0.10681725·MCHI + 0.03592193·QQQ + 0.03329520·SPBLSCUP",
    }
    base["models"]["retornos"] = {
        "coefficients": RETURN_COEFF,
        "equation": "RVC = 0.0001081555 - 0.63026640·RSPY + 0.55404242·REEM - 0.01280332·RMCHI + 0.53713071·RQQQ + 0.27871670·RSPBLSCUP",
    }
    base["methodology"].update({
        "calibration_note": "OLS de las últimas 30 sesiones con VC SBS antes del 01/10/2026 (19/08–30/09).",
        "before_training": "RETROSPECTIVO: fechas anteriores al 19/08/2026; no son validación fuera de muestra.",
        "after_training": "VALIDACIÓN/PROYECCIÓN: coeficientes congelados desde el 01/10/2026.",
    })


def main(sbs_only=False, root=ROOT):
    base_path, snap_path = (root / "public/data" / n for n in ("fixed_models_2026.json", "fixed_models_intraday.json"))
    base = json.loads(base_path.read_text(encoding="utf-8"))
    official = read_official(root)
    synchronize_calibration(base)
    recalculate(base, official)
    if not sbs_only:
        snap = json.loads(snap_path.read_text(encoding="utf-8"))
        validate_snapshot(base, snap)
        if snap["close_consolidated"]:
            target = snap["signal_date"]
            row = next((r for r in base["rows"] if r["fecha"] == target), None)
            if row is None:
                row = {k: None for k in base["rows"][-1]}
                row["fecha"] = target
                base["rows"].append(row)
                base["rows"].sort(key=lambda r: r["fecha"])
            row.update({t["ticker"]: t["price_current"] for t in snap["tickers"]})
            row["source"] = "CIERRE REGULAR VERIFICADO · 5/5 CON FECHA PROPIA"
            cache_close(root, snap)
            recalculate(base, official)
        snap["base_revision"] = base["data_revision"]
        validate_snapshot(base, snap)
        snap_path.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")
    base["generated_at_lima"] = datetime.now(ZoneInfo("America/Lima")).isoformat()
    base_path.write_text(json.dumps(base, ensure_ascii=False, indent=2), encoding="utf-8")
    write_rows(root / "public/data/fixed_models_2026.csv", base["rows"])
    print("SBS/serie reconciliados:", base["latest"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sbs-only", action="store_true")
    main(parser.parse_args().sbs_only)
