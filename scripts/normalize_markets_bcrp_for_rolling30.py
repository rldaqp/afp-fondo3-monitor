from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import patch_dual_rolling30_fx_operational as fxmod

MARKETS = ROOT / "data" / "rolling90" / "markets.csv"
REPORT = ROOT / "data" / "analysis" / "rolling30_bcrp_normalization.json"


def main() -> None:
    if not MARKETS.exists():
        raise RuntimeError("No existe markets.csv")

    rows, method = fxmod.load_bcrp()
    if not rows:
        raise RuntimeError("BCRP PD04638PD no devolvió datos")

    b = pd.DataFrame(rows, columns=["fecha", "USD_PEN_BCRP"])
    b["fecha"] = pd.to_datetime(b["fecha"], errors="coerce").dt.normalize()
    b["USD_PEN_BCRP"] = pd.to_numeric(b["USD_PEN_BCRP"], errors="coerce")
    b = b.dropna().sort_values("fecha").drop_duplicates("fecha", keep="last")
    b["ret_BCRP"] = b["USD_PEN_BCRP"].pct_change(fill_method=None)

    d = pd.read_csv(MARKETS)
    d["fecha"] = pd.to_datetime(d["fecha"], errors="coerce").dt.normalize()
    d["USD_PEN"] = pd.to_numeric(d["USD_PEN"], errors="coerce")
    d["ret_USD_PEN"] = pd.to_numeric(d["ret_USD_PEN"], errors="coerce")
    before = d[["fecha", "USD_PEN", "ret_USD_PEN"]].copy()

    merged = d.merge(b, on="fecha", how="left")
    mask = merged["USD_PEN_BCRP"].notna()
    merged.loc[mask, "USD_PEN"] = merged.loc[mask, "USD_PEN_BCRP"]
    rmask = merged["ret_BCRP"].notna()
    merged.loc[rmask, "ret_USD_PEN"] = merged.loc[rmask, "ret_BCRP"]
    merged = merged.drop(columns=["USD_PEN_BCRP", "ret_BCRP"])
    merged["fecha"] = merged["fecha"].dt.strftime("%Y-%m-%d")
    merged.to_csv(MARKETS, index=False)

    check_dates = pd.to_datetime(["2026-08-24", "2026-08-25", "2026-08-26", "2026-08-27"])
    check = merged[pd.to_datetime(merged["fecha"]).isin(check_dates)][["fecha", "USD_PEN", "ret_USD_PEN"]]
    expected = {
        "2026-08-24": (3.34714285714286, -4.267850283590224e-05),
        "2026-08-25": (3.34457142857143, -0.0007682458386687463),
        "2026-08-26": (3.34528571428571, 0.0002135656928055063),
        "2026-08-27": (3.34514285714286, -4.2704018446082515e-05),
    }
    for _, r in check.iterrows():
        date = str(r["fecha"])[:10]
        if date in expected:
            value, ret = expected[date]
            assert abs(float(r["USD_PEN"]) - value) < 1e-10, (date, r.to_dict())
            assert abs(float(r["ret_USD_PEN"]) - ret) < 1e-12, (date, r.to_dict())

    changed = []
    aft = merged.copy()
    aft["fecha"] = pd.to_datetime(aft["fecha"], errors="coerce").dt.normalize()
    joined = before.merge(aft[["fecha", "USD_PEN", "ret_USD_PEN"]], on="fecha", suffixes=("_before", "_after"))
    for _, r in joined.iterrows():
        if (pd.notna(r["USD_PEN_after"]) and r["USD_PEN_before"] != r["USD_PEN_after"]) or (
            pd.notna(r["ret_USD_PEN_after"]) and r["ret_USD_PEN_before"] != r["ret_USD_PEN_after"]
        ):
            if str(r["fecha"].date()) >= "2026-08-20":
                changed.append({
                    "fecha": str(r["fecha"].date()),
                    "before_value": None if pd.isna(r["USD_PEN_before"]) else float(r["USD_PEN_before"]),
                    "after_value": None if pd.isna(r["USD_PEN_after"]) else float(r["USD_PEN_after"]),
                    "before_return": None if pd.isna(r["ret_USD_PEN_before"]) else float(r["ret_USD_PEN_before"]),
                    "after_return": None if pd.isna(r["ret_USD_PEN_after"]) else float(r["ret_USD_PEN_after"]),
                })

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps({
        "source": method,
        "series": "BCRP PD04638PD",
        "purpose": "Normalización temporal para los dos Rolling 30; evita usar la serie USD/PEN redondeada del markets.csv en el modelo A.",
        "checked_2026_08_24_27": check.to_dict(orient="records"),
        "changed_recent": changed,
    }, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(check.to_string(index=False))


if __name__ == "__main__":
    main()
