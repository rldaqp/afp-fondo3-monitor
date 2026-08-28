from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DUAL = ROOT / "public" / "data" / "dual_rolling30_monitor.json"
AUDIT = ROOT / "analysis" / "recheck_20260824_exact.json"
DATE = "2026-08-24"


def _replace_operational(model: dict, row: dict) -> None:
    hist = [r for r in model.get("history_operational", []) if str(r.get("fecha"))[:10] != DATE]
    hist.append(row)
    hist.sort(key=lambda r: str(r.get("fecha", ""))[:10])
    model["history_operational"] = hist


def main() -> None:
    if not DUAL.exists() or not AUDIT.exists():
        raise RuntimeError("Falta dual_rolling30_monitor.json o recheck_20260824_exact.json")

    d = json.loads(DUAL.read_text(encoding="utf-8"))
    a = json.loads(AUDIT.read_text(encoding="utf-8"))
    actual_21 = float(a["sbs_actual_21"])
    actual_24 = float(a["sbs_actual_24"])
    actual_ret = actual_24 / actual_21 - 1.0
    anchor_date = str(a["anchor"]["fecha"])
    anchor_vc = float(a["anchor"]["vc"])

    mapping = {
        "qqq": "qqq",
        "new_tickers": "new_tickers",
    }

    corrections = {}
    for model_key, audit_key in mapping.items():
        model = d["models"][model_key]
        audit_model = a[audit_key]
        chain = next(r for r in audit_model["chain"] if str(r["fecha"])[:10] == DATE)
        ret = float(chain["return_estimated"])
        est = float(chain["vc_estimated"])
        row = {
            "fecha": DATE,
            "base_vc": float(chain["base_vc"]),
            "vc_estimated": est,
            "return_estimated": ret,
            "signal": "SUBE" if ret > 0.001 else ("BAJA" if ret < -0.001 else "NEUTRO"),
            "actual_vc": actual_24,
            "actual_return_daily": actual_ret,
            "actual_return": actual_ret,
            "anchor_date": anchor_date,
            "anchor_vc": anchor_vc,
            "error_vc": est - actual_24,
            "error_pct": (est / actual_24 - 1.0) * 100.0,
            "source": "RECALCULO EXACTO POST-INCIDENTE 24/08 · CIERRES DIARIOS VALIDOS · BCRP PD04638PD",
            "quality_status": "CORREGIDO_EXACTO",
            "quality_note": "Se sustituye en el visor la fila operacional contaminada del 24/08. El recálculo usa ancla SBS 20/08, encadena 21 y 24 sin conocer sus VC, y usa cierres correctos de factores y BCRP oficial.",
            "include_in_score": True,
            "correction_basis": "analysis/recheck_20260824_exact.json",
        }
        _replace_operational(model, row)
        corrections[model_key] = {
            "vc_estimated": est,
            "return_estimated": ret,
            "error_pct_vs_sbs_24": float(audit_model["error_pct_vs_sbs_24"]),
        }

    d["historical_corrections"] = d.get("historical_corrections", {})
    d["historical_corrections"][DATE] = {
        "status": "CORREGIDO",
        "reason": "Incidente documentado en datos operacionales del 24/08, especialmente CPER y SPBLSCUP del Modelo B y continuidad de la cadena 21→24.",
        "basis": "analysis/recheck_20260824_exact.json",
        "anchor": a["anchor"],
        "sbs_actual_21": actual_21,
        "sbs_actual_24": actual_24,
        "models": corrections,
    }

    DUAL.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(d["historical_corrections"][DATE], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
