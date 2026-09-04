"""Publish SBS, history and the confirmed close as one consistent generation."""
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fixed_model_contract import FACTORS, recalculate, validate_snapshot

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


def main(sbs_only=False, root=ROOT):
    base_path, snap_path = (root / "public/data" / n for n in ("fixed_models_2026.json", "fixed_models_intraday.json"))
    base = json.loads(base_path.read_text(encoding="utf-8"))
    official = read_official(root)
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
