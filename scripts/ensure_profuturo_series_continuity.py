from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "fixed_models" / "yahoo_levels_2026.csv"
OUT_JSON = ROOT / "public" / "data" / "fixed_models_2026.json"
OUT_CSV = ROOT / "public" / "data" / "fixed_models_2026.csv"

YAHOO_FACTORS = ["SPY", "EEM", "MCHI", "QQQ"]
FACTORS = YAHOO_FACTORS + ["SPBLSCUP"]


def finite(v) -> bool:
    try:
        return v is not None and np.isfinite(float(v))
    except Exception:
        return False


def load_cache() -> pd.DataFrame:
    if CACHE.exists():
        c = pd.read_csv(CACHE)
    else:
        c = pd.DataFrame(columns=["fecha", *YAHOO_FACTORS, "source"])
    for col in ["fecha", *YAHOO_FACTORS, "source"]:
        if col not in c.columns:
            c[col] = np.nan
    c["fecha"] = pd.to_datetime(c["fecha"], errors="coerce").dt.normalize()
    for col in YAHOO_FACTORS:
        c[col] = pd.to_numeric(c[col], errors="coerce")
    return c.dropna(subset=["fecha"]).sort_values("fecha").drop_duplicates("fecha", keep="first")


def persist_cache(cache: pd.DataFrame) -> None:
    c = cache[["fecha", *YAHOO_FACTORS, "source"]].copy()
    c = c.sort_values("fecha").drop_duplicates("fecha", keep="first")
    c["fecha"] = pd.to_datetime(c["fecha"]).dt.strftime("%Y-%m-%d")
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    c.to_csv(CACHE, index=False)


def main() -> None:
    payload = json.loads(OUT_JSON.read_text(encoding="utf-8"))
    rows = pd.DataFrame(payload.get("rows", []))
    if rows.empty:
        raise RuntimeError("fixed_models_2026.json no contiene filas")

    rows["fecha"] = pd.to_datetime(rows["fecha"], errors="coerce").dt.normalize()
    rows = rows.dropna(subset=["fecha"]).sort_values("fecha").reset_index(drop=True)
    for col in FACTORS + ["vc_sbs"]:
        rows[col] = pd.to_numeric(rows.get(col), errors="coerce")

    cache = load_cache()
    cache_by_date = cache.set_index("fecha") if not cache.empty else pd.DataFrame()
    restored = []

    # Primero restaura huecos históricos desde la caché persistente. Esto evita
    # que una descarga temporalmente incompleta de Yahoo vuelva a romper la serie.
    for idx, row in rows.iterrows():
        d = pd.Timestamp(row["fecha"])
        if cache.empty or d not in cache_by_date.index:
            continue
        used = False
        for col in YAHOO_FACTORS:
            if not finite(rows.at[idx, col]) and finite(cache_by_date.at[d, col]):
                rows.at[idx, col] = float(cache_by_date.at[d, col])
                used = True
        if used:
            restored.append(d.strftime("%Y-%m-%d"))
            src = str(rows.at[idx, "source"] or "")
            rows.at[idx, "source"] = (src + " · CACHE HISTORICA YAHOO").strip(" ·")

    # Después incorpora a la caché todas las ruedas completas nuevas, sin
    # reemplazar fechas ya validadas previamente.
    known = set(pd.to_datetime(cache["fecha"]).tolist()) if not cache.empty else set()
    additions = []
    for _, row in rows.iterrows():
        d = pd.Timestamp(row["fecha"])
        if d in known or not all(finite(row[c]) for c in YAHOO_FACTORS):
            continue
        additions.append({
            "fecha": d,
            **{c: float(row[c]) for c in YAHOO_FACTORS},
            "source": "YAHOO CACHE PERSISTENTE",
        })
        known.add(d)
    if additions:
        cache = pd.concat([cache, pd.DataFrame(additions)], ignore_index=True)
    persist_cache(cache)

    level_coeff = payload["models"]["niveles"]["coefficients"]
    return_coeff = payload["models"]["retornos"]["coefficients"]

    # Recalcula ambos modelos desde los mismos factores ya restaurados.
    for col in FACTORS:
        rows[col] = pd.to_numeric(rows[col], errors="coerce")
        rows[f"ret_{col}"] = rows[col].pct_change(fill_method=None)

    rows["vc_niveles"] = float(level_coeff["intercept"])
    valid_levels = pd.Series(True, index=rows.index)
    for col in FACTORS:
        valid_levels &= rows[col].notna()
        rows["vc_niveles"] += float(level_coeff[col]) * rows[col]
    rows.loc[~valid_levels, "vc_niveles"] = np.nan

    rows["ret_vc_estimado"] = float(return_coeff["intercept"])
    valid_returns = pd.Series(True, index=rows.index)
    for col in FACTORS:
        valid_returns &= rows[f"ret_{col}"].notna()
        rows["ret_vc_estimado"] += float(return_coeff[col]) * rows[f"ret_{col}"]
    rows.loc[~valid_returns, "ret_vc_estimado"] = np.nan

    estimates = []
    prev_est = np.nan
    for i, row in rows.iterrows():
        if i == 0 or not finite(row["ret_vc_estimado"]):
            estimates.append(np.nan)
            continue
        prev_actual = rows.iloc[i - 1]["vc_sbs"]
        if finite(prev_actual):
            base = float(prev_actual)
        elif finite(prev_est):
            base = float(prev_est)
        else:
            base = np.nan
        value = base * (1.0 + float(row["ret_vc_estimado"])) if finite(base) else np.nan
        estimates.append(value)
        if finite(value):
            prev_est = value
    rows["vc_retornos"] = estimates

    rows["error_niveles_pct"] = np.where(
        rows["vc_sbs"].notna() & rows["vc_niveles"].notna(),
        (rows["vc_niveles"] / rows["vc_sbs"] - 1.0) * 100.0,
        np.nan,
    )
    rows["error_retornos_pct"] = np.where(
        rows["vc_sbs"].notna() & rows["vc_retornos"].notna(),
        (rows["vc_retornos"] / rows["vc_sbs"] - 1.0) * 100.0,
        np.nan,
    )

    # Fechas críticas que ya fueron auditadas. Si alguna vuelve a quedar vacía,
    # el flujo debe fallar antes de publicar un gráfico cortado.
    critical = ["2026-08-27", "2026-08-28", "2026-08-31"]
    for ds in critical:
        d = pd.Timestamp(ds)
        r = rows.loc[rows["fecha"].eq(d)]
        if r.empty:
            raise RuntimeError(f"Falta la rueda crítica {ds}")
        rr = r.iloc[0]
        missing = [c for c in FACTORS + ["vc_niveles", "ret_vc_estimado", "vc_retornos"] if not finite(rr[c])]
        if missing:
            raise RuntimeError(f"Rueda {ds} incompleta: {missing}")

    last_complete = rows.loc[rows[FACTORS].notna().all(axis=1)].tail(1)
    if last_complete.empty:
        raise RuntimeError("No hay última rueda completa")
    last = last_complete.iloc[0]
    payload["latest"]["market_date"] = pd.Timestamp(last["fecha"]).strftime("%Y-%m-%d")
    payload["latest"]["vc_niveles"] = float(last["vc_niveles"]) if finite(last["vc_niveles"]) else None
    payload["latest"]["ret_vc_estimado"] = float(last["ret_vc_estimado"]) if finite(last["ret_vc_estimado"]) else None
    payload["latest"]["vc_retornos"] = float(last["vc_retornos"]) if finite(last["vc_retornos"]) else None

    output_cols = [
        "fecha", "fase", "SPY", "EEM", "MCHI", "QQQ", "SPBLSCUP", "source",
        "vc_sbs", "vc_niveles", "ret_vc_estimado", "vc_retornos",
        "error_niveles_pct", "error_retornos_pct",
    ]
    out = rows[output_cols].copy()
    out["fecha"] = out["fecha"].dt.strftime("%Y-%m-%d")
    out.to_csv(OUT_CSV, index=False)

    def clean(v):
        if v is None:
            return None
        if isinstance(v, (float, np.floating)):
            return None if not np.isfinite(v) else float(v)
        if isinstance(v, (int, np.integer)):
            return int(v)
        if pd.isna(v):
            return None
        return v

    payload["rows"] = [{k: clean(v) for k, v in r.items()} for r in out.to_dict(orient="records")]
    payload.setdefault("sources", {})["YAHOO_CACHE"] = "data/fixed_models/yahoo_levels_2026.csv · respaldo persistente contra huecos de descarga"
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    check = rows.loc[rows["fecha"].isin(pd.to_datetime(critical)), ["fecha", "vc_niveles", "ret_vc_estimado", "vc_retornos"]]
    print("Continuidad Profuturo validada")
    print(check.to_string(index=False))
    if restored:
        print("Fechas restauradas desde cache:", ", ".join(sorted(set(restored))))


if __name__ == "__main__":
    main()
