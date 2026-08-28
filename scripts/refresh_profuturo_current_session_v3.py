from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
V2 = ROOT / "scripts" / "refresh_profuturo_current_session_v2.py"

spec = importlib.util.spec_from_file_location("profuturo_refresh_v2", V2)
if spec is None or spec.loader is None:
    raise RuntimeError(f"No se pudo cargar {V2}")
m = importlib.util.module_from_spec(spec)
sys.modules["profuturo_refresh_v2"] = m
spec.loader.exec_module(m)
original_spb = m.spblscup_google


def stamp_matches_text(value, target: pd.Timestamp) -> bool:
    s = str(value or "")
    if not s:
        return False
    try:
        ts = pd.Timestamp(s)
        if ts.tzinfo is not None:
            ts = ts.tz_convert(m.NY).tz_localize(None)
        if ts.date() == target.date():
            return True
    except Exception:
        pass
    # Google puede mostrar, por ejemplo: "Aug 28, 5:30:20 PM UTC-4" sin año.
    mon = target.strftime("%b")
    return re.search(rf"\b{re.escape(mon)}\s+{target.day}\b", s, re.I) is not None


def spb_with_validated_fallback(target: pd.Timestamp):
    try:
        return original_spb(target)
    except Exception as first_error:
        live = json.loads(m.LIVE.read_text(encoding="utf-8")) if m.LIVE.exists() else {}
        for row in live.get("experimental_assets", []):
            if str(row.get("serie")) != "SPBLSCUP":
                continue
            if not stamp_matches_text(row.get("google_stamp"), target):
                continue
            if not (m.finite(row.get("precio_actual")) and m.finite(row.get("retorno"))):
                continue
            cur = float(row["precio_actual"])
            ret = float(row["retorno"])
            prev = row.get("precio_anterior")
            if not m.finite(prev):
                prev = cur / (1.0 + ret) if abs(1.0 + ret) > 1e-12 else None
            if not m.finite(prev):
                continue
            print("SPBLSCUP: se reutiliza el quote Google/Selenium de la misma sesión", row.get("google_stamp"))
            return float(prev), cur, ret, str(row.get("google_stamp"))
        raise RuntimeError(f"SPBLSCUP actual no validado; error inicial: {first_error}")


m.spblscup_google = spb_with_validated_fallback

if __name__ == "__main__":
    m.main()
