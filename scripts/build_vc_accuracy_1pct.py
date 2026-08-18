from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SIGNALS = ROOT / "public" / "data" / "signals.json"
OUT_DATA = ROOT / "data" / "rolling90" / "vc_accuracy_1pct.json"
OUT_PUBLIC = ROOT / "public" / "data" / "vc_accuracy_1pct.json"


def main() -> None:
    rows = json.loads(SIGNALS.read_text(encoding="utf-8"))
    hist = [
        r for r in rows
        if r.get("tipo") == "HISTORICO"
        and r.get("ret_estimado") is not None
        and r.get("vc_estimado") is not None
        and r.get("vc_real") is not None
    ]

    strong = [r for r in hist if abs(float(r["ret_estimado"])) >= 0.01]
    if not strong:
        raise RuntimeError("No hay casos históricos con movimiento estimado >= 1%")

    errors = [
        abs(float(r["vc_estimado"]) / float(r["vc_real"]) - 1.0)
        for r in strong
        if float(r["vc_real"]) > 0
    ]
    within = sum(err <= 0.01 for err in errors)
    result = {
        "definition": "Acierto del VC para movimientos estimados de magnitud >=1%: VC estimado dentro de ±1% del VC oficial SBS.",
        "threshold_signal_abs": 0.01,
        "threshold_vc_error_abs": 0.01,
        "n": len(errors),
        "hits": within,
        "accuracy": within / len(errors),
        "mean_abs_error_pct": sum(errors) / len(errors) * 100,
    }

    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    OUT_DATA.write_text(text, encoding="utf-8")
    OUT_PUBLIC.write_text(text, encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
