from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(path: str):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def series_official(rows):
    out = {}
    for r in rows:
        d = str(r.get("fecha") or "")[:10]
        try:
            v = float(r.get("vc"))
        except (TypeError, ValueError):
            continue
        official = r.get("es_oficial") is True or "SBS" in str(r.get("fuente") or "").upper()
        if d and v > 0 and official:
            out[d] = v
    return out


def dual_actual(db):
    out = {}
    for key in ("qqq", "new_tickers"):
        m = db.get("models", {}).get(key, {})
        for name in ("history_one_step", "history_operational", "forward_chain"):
            for r in m.get(name, []) or []:
                d = str(r.get("fecha") or "")[:10]
                try:
                    v = float(r.get("actual_vc"))
                except (TypeError, ValueError):
                    continue
                if d and v > 0:
                    out[d] = v
        c = m.get("current") or {}
        d = str(c.get("fecha") or "")[:10]
        try:
            v = float(c.get("actual_vc"))
        except (TypeError, ValueError):
            v = 0.0
        if d and v > 0:
            out[d] = v
    latest = db.get("latest_sbs") or {}
    d = str(latest.get("fecha") or "")[:10]
    try:
        v = float(latest.get("vc"))
    except (TypeError, ValueError):
        v = 0.0
    if d and v > 0:
        out[d] = v
    return out


def hybrid(series, dual):
    out = series_official(series)
    out.update(dual_actual(dual))
    return out


def calc(capital, entry, exit_):
    ret = exit_ / entry - 1.0
    gain = capital * ret
    return ret, gain, capital + gain


def main():
    prof_series = load("public/data/series.json")
    hab_series = load("public/habitat/data/series.json")
    prof_dual = load("public/data/dual_rolling30_monitor.json")
    hab_dual = load("public/habitat/data/dual_rolling30_monitor.json")

    p = hybrid(prof_series, prof_dual)
    h = hybrid(hab_series, hab_dual)

    assert p["2026-08-18"] == 69.6328126, p["2026-08-18"]
    assert abs(p["2026-08-20"] - 71.0427094) < 1e-9, p["2026-08-20"]
    assert h["2026-08-18"] == 33.0720663, h["2026-08-18"]
    assert abs(h["2026-08-20"] - 33.2617644) < 1e-9, h["2026-08-20"]

    cap = 30000.0
    pr, pg, pf = calc(cap, p["2026-08-18"], p["2026-08-20"])
    hr, hg, hf = calc(cap, h["2026-08-18"], h["2026-08-20"])

    assert round(pg, 2) == 607.43, pg
    assert round(pr * 100, 2) == 2.02, pr
    assert round(hg, 2) == 172.08, hg
    assert round(hr * 100, 2) == 0.57, hr
    assert pf > hf

    print("CASO VALIDADO 18/08/2026 -> 20/08/2026, capital S/30,000")
    print(f"Profuturo: ganancia S/{pg:.2f}, rentabilidad {pr*100:.2f}%, final S/{pf:.2f}")
    print(f"Habitat: ganancia S/{hg:.2f}, rentabilidad {hr*100:.2f}%, final S/{hf:.2f}")
    print(f"Ventaja Profuturo: S/{pf-hf:.2f}")


if __name__ == "__main__":
    main()
