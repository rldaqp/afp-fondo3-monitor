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

# Fechas que en PD04640PD aparecen como n.d. y deben conservar el último
# SBS Venta oficial disponible para no dejar huecos en el modelo.
EXPECTED_GAPS = {
    "2026-07-23": 3.404,
    "2026-07-27": 3.411,
    "2026-07-28": 3.411,
    "2026-07-29": 3.411,
    "2026-08-06": 3.394,
}

# Controles adicionales de la propia serie SBS Venta.
EXPECTED_OFFICIAL = {
    "2026-07-24": 3.411,
    "2026-07-30": 3.399,
    "2026-08-07": 3.391,
    "2026-08-10": 3.387,
    "2026-08-17": 3.370,
}


def main() -> None:
    if not MARKETS.exists():
        raise RuntimeError("No existe markets.csv")

    rows, method = fxmod.load_bcrp()
    if not rows:
        raise RuntimeError("BCRP PD04640PD SBS Venta no devolvió datos")

    b = pd.DataFrame(rows, columns=["fecha", "USD_PEN_BCRP"])
    b["fecha"] = pd.to_datetime(b["fecha"], errors="coerce").dt.normalize()
    b["USD_PEN_BCRP"] = pd.to_numeric(b["USD_PEN_BCRP"], errors="coerce")
    b = b.dropna().sort_values("fecha").drop_duplicates("fecha", keep="last")
    latest_official = b["fecha"].max()

    d = pd.read_csv(MARKETS)
    d["fecha"] = pd.to_datetime(d["fecha"], errors="coerce").dt.normalize()
    d["USD_PEN"] = pd.to_numeric(d["USD_PEN"], errors="coerce")
    d["ret_USD_PEN"] = pd.to_numeric(d["ret_USD_PEN"], errors="coerce")
    d = d.sort_values("fecha").reset_index(drop=True)
    before = d[["fecha", "USD_PEN", "ret_USD_PEN"]].copy()

    merged = d.merge(b, on="fecha", how="left").sort_values("fecha").reset_index(drop=True)

    # Dentro del histórico ya publicado por BCRP, un hueco significa que la
    # serie oficial publicó n.d. (o que no hay observación ese día). Se usa el
    # último SBS Venta oficial. No se extiende este arrastre a fechas posteriores
    # a la última publicación oficial.
    merged["USD_PEN_BCRP_FILL"] = merged["USD_PEN_BCRP"].ffill()
    hist_mask = merged["fecha"].le(latest_official) & merged["USD_PEN_BCRP_FILL"].notna()
    merged.loc[hist_mask, "USD_PEN"] = merged.loc[hist_mask, "USD_PEN_BCRP_FILL"]

    ret_calc = merged["USD_PEN"].pct_change(fill_method=None)
    merged.loc[hist_mask & ret_calc.notna(), "ret_USD_PEN"] = ret_calc.loc[hist_mask & ret_calc.notna()]

    merged = merged.drop(columns=["USD_PEN_BCRP", "USD_PEN_BCRP_FILL"])

    expected = {**EXPECTED_GAPS, **EXPECTED_OFFICIAL}
    for date, value in expected.items():
        mask = merged["fecha"].eq(pd.Timestamp(date))
        if not mask.any():
            continue
        got = merged.loc[mask, "USD_PEN"].iloc[-1]
        assert pd.notna(got) and abs(float(got) - value) < 1e-12, (date, got, value)

    check_dates = pd.to_datetime(list(expected.keys()))
    check = merged[merged["fecha"].isin(check_dates)][["fecha", "USD_PEN", "ret_USD_PEN"]].copy()

    changed = []
    joined = before.merge(
        merged[["fecha", "USD_PEN", "ret_USD_PEN"]],
        on="fecha",
        suffixes=("_before", "_after"),
    )
    for _, r in joined.iterrows():
        value_changed = not (
            (pd.isna(r["USD_PEN_before"]) and pd.isna(r["USD_PEN_after"]))
            or (pd.notna(r["USD_PEN_before"]) and pd.notna(r["USD_PEN_after"]) and float(r["USD_PEN_before"]) == float(r["USD_PEN_after"]))
        )
        return_changed = not (
            (pd.isna(r["ret_USD_PEN_before"]) and pd.isna(r["ret_USD_PEN_after"]))
            or (pd.notna(r["ret_USD_PEN_before"]) and pd.notna(r["ret_USD_PEN_after"]) and float(r["ret_USD_PEN_before"]) == float(r["ret_USD_PEN_after"]))
        )
        if value_changed or return_changed:
            changed.append({
                "fecha": str(r["fecha"].date()),
                "before_value": None if pd.isna(r["USD_PEN_before"]) else float(r["USD_PEN_before"]),
                "after_value": None if pd.isna(r["USD_PEN_after"]) else float(r["USD_PEN_after"]),
                "before_return": None if pd.isna(r["ret_USD_PEN_before"]) else float(r["ret_USD_PEN_before"]),
                "after_return": None if pd.isna(r["ret_USD_PEN_after"]) else float(r["ret_USD_PEN_after"]),
            })

    out = merged.copy()
    out["fecha"] = out["fecha"].dt.strftime("%Y-%m-%d")
    out.to_csv(MARKETS, index=False)

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps({
        "source": method,
        "series": "BCRP PD04640PD",
        "series_name": "TC Sistema bancario SBS (S/ por US$) - Venta",
        "latest_official_date": str(latest_official.date()),
        "missing_policy": "Dentro del histórico oficial, n.d. se completa con el último SBS Venta oficial disponible (forward-fill). No se arrastra más allá de la última fecha publicada por BCRP.",
        "checked_reference_dates": check.assign(fecha=check["fecha"].dt.strftime("%Y-%m-%d")).to_dict(orient="records"),
        "changed_rows": changed,
    }, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    print(f"Fuente: {method}")
    print(f"Última fecha oficial: {latest_official.date()}")
    print(check.to_string(index=False))


if __name__ == "__main__":
    main()
