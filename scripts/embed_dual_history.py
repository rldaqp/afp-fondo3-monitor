from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "analysis" / "backtest_blind3_rolling30_common.csv"
TARGET = ROOT / "public" / "data" / "dual_rolling30_monitor.json"
THRESHOLD = 0.001


def finite(v):
    try:
        return v is not None and float(v) == float(v)
    except Exception:
        return False


def signal(ret: float) -> str:
    if ret > THRESHOLD:
        return "SUBE"
    if ret < -THRESHOLD:
        return "BAJA"
    return "NEUTRO"


def make_row(r: dict, estimate_field: str) -> dict:
    fecha = str(r["target_date"])[:10]
    base_date = str(r["visible_cutoff"])[:10]
    base = float(r["visible_base_vc"])
    actual = float(r["actual_vc"])
    est = float(r[estimate_field])
    ret_est = est / base - 1.0
    ret_real = actual / base - 1.0
    return {
        "fecha": fecha,
        "base_date": base_date,
        "base_vc": base,
        "vc_estimated": est,
        "actual_vc": actual,
        "return_estimated": ret_est,
        "actual_return": ret_real,
        "signal": signal(ret_est),
        "error_pct": (est / actual - 1.0) * 100.0,
        "validation": "BACKTEST CIEGO 3 VC",
        "horizon_sessions": 3,
    }


def main() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"No existe {SOURCE}")
    if not TARGET.exists():
        raise SystemExit(f"No existe {TARGET}")

    qqq = []
    new = []
    with SOURCE.open("r", encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            try:
                if int(float(r.get("lag_sessions") or 0)) != 3:
                    continue
                required = ["target_date", "visible_cutoff", "visible_base_vc", "actual_vc", "raw_qqq_vc", "new_tickers_vc"]
                if not all(r.get(k) not in (None, "") for k in required):
                    continue
                qqq.append(make_row(r, "raw_qqq_vc"))
                new.append(make_row(r, "new_tickers_vc"))
            except Exception:
                continue

    qqq.sort(key=lambda x: x["fecha"])
    new.sort(key=lambda x: x["fecha"])

    if len(qqq) < 70 or len(new) < 70 or len(qqq) != len(new):
        raise SystemExit(f"Histórico insuficiente: qqq={len(qqq)} nuevos={len(new)}")

    payload = json.loads(TARGET.read_text(encoding="utf-8"))
    payload["models"]["qqq"]["history_one_step"] = qqq
    payload["models"]["new_tickers"]["history_one_step"] = new
    payload["models"]["qqq"]["history_metrics"]["n"] = len(qqq)
    payload["models"]["new_tickers"]["history_metrics"]["n"] = len(new)
    payload["history_chart_meta"] = {
        "source": "analysis/backtest_blind3_rolling30_common.csv",
        "validation": "BACKTEST CIEGO 3 VC",
        "n_common": len(qqq),
        "start": qqq[0]["fecha"],
        "end": qqq[-1]["fecha"],
        "note": "Histórico común de ambos modelos. Cada estimación histórica se calculó ocultando exactamente 3 VC SBS; el seguimiento operativo posterior se conserva por separado y no se ajusta retroactivamente.",
    }
    TARGET.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload["history_chart_meta"], ensure_ascii=False))


if __name__ == "__main__":
    main()
