from __future__ import annotations

import json
import math
from pathlib import Path
from statistics import mean, median

ROOT = Path(__file__).resolve().parents[1]
SIGNALS = ROOT / "public" / "data" / "signals.json"
OUT = ROOT / "data" / "rolling90" / "vc_accuracy_1pct.json"


def finite(x):
    try:
        return math.isfinite(float(x))
    except Exception:
        return False


def summarize(rows):
    errors = [abs(float(r["vc_estimado"]) / float(r["vc_real"]) - 1.0) for r in rows]
    signed = [float(r["vc_estimado"]) / float(r["vc_real"]) - 1.0 for r in rows]
    return {
        "n": len(rows),
        "within_0_50pct": sum(e <= 0.005 for e in errors) / len(rows) if rows else None,
        "within_0_75pct": sum(e <= 0.0075 for e in errors) / len(rows) if rows else None,
        "within_1_00pct": sum(e <= 0.01 for e in errors) / len(rows) if rows else None,
        "within_1_50pct": sum(e <= 0.015 for e in errors) / len(rows) if rows else None,
        "mean_abs_error_pct": mean(errors) * 100 if rows else None,
        "median_abs_error_pct": median(errors) * 100 if rows else None,
        "mean_signed_error_pct": mean(signed) * 100 if rows else None,
        "max_abs_error_pct": max(errors) * 100 if rows else None,
    }


def main():
    data = json.loads(SIGNALS.read_text(encoding="utf-8"))
    hist = [
        r for r in data
        if r.get("tipo") == "HISTORICO"
        and finite(r.get("ret_estimado"))
        and finite(r.get("vc_estimado"))
        and finite(r.get("vc_real"))
        and float(r.get("vc_real")) > 0
    ]
    pos = [r for r in hist if float(r["ret_estimado"]) >= 0.01]
    neg = [r for r in hist if float(r["ret_estimado"]) <= -0.01]
    abs1 = [r for r in hist if abs(float(r["ret_estimado"])) >= 0.01]

    payload = {
        "definition": "Precisión del VC = porcentaje de casos cuyo VC estimado terminó dentro de ±1.00% del VC oficial SBS.",
        "historical_rows": len(hist),
        "positive_signal_ge_1pct": summarize(pos),
        "negative_signal_le_minus_1pct": summarize(neg),
        "absolute_signal_ge_1pct": summarize(abs1),
        "positive_dates": [r["fecha"] for r in pos],
        "negative_dates": [r["fecha"] for r in neg],
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
