"""Alinea el visor Hábitat con la estructura visual y de datos de Profuturo."""

import json
from pathlib import Path

from build_habitat_profuturo_parity import main

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_DATA = ROOT / "public" / "habitat" / "data"


def ensure_latest_consistency() -> None:
    signals_path = PUBLIC_DATA / "signals.json"
    latest_path = PUBLIC_DATA / "latest.json"
    live_path = PUBLIC_DATA / "live_market.json"
    signals = json.loads(signals_path.read_text(encoding="utf-8"))
    latest = json.loads(latest_path.read_text(encoding="utf-8"))
    live = json.loads(live_path.read_text(encoding="utf-8"))
    if not signals:
        raise RuntimeError("Hábitat no generó señales históricas ni pendientes.")
    current = signals[-1]
    latest["latest_estimate_date"] = current["fecha"]
    latest["latest_estimated_vc"] = float(current["vc_estimado"])
    latest["latest_return_estimated"] = float(current["ret_estimado"])
    latest["signal"] = current["senal"]
    live["signal_date"] = current["fecha"]
    live["vc_estimated"] = float(current["vc_estimado"])
    live["return_estimated"] = float(current["ret_estimado"])
    live["signal"] = current["senal"]
    latest_path.write_text(json.dumps(latest, ensure_ascii=False, indent=2), encoding="utf-8")
    live_path.write_text(json.dumps(live, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
    ensure_latest_consistency()
