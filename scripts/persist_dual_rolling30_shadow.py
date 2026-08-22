from __future__ import annotations

import json
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public" / "data"
DATA = ROOT / "data" / "rolling90"
DUAL_PATH = PUBLIC / "dual_rolling30_monitor.json"
SBS_PATH = DATA / "sbs_profuturo_f3.csv"
SHADOW_PATH = DATA / "dual_rolling30_shadow.csv"
LIMA = ZoneInfo("America/Lima")

COLS = [
    "model_key", "model_name", "fecha", "first_generated_at_lima", "last_updated_at_lima",
    "frozen", "anchor_date", "anchor_vc", "base_vc", "vc_estimated", "return_estimated",
    "signal", "actual_vc", "actual_return_daily", "error_vc", "error_pct",
    "direction_hit", "source",
]


def finite(v) -> bool:
    try:
        return v is not None and np.isfinite(float(v))
    except Exception:
        return False


def load_shadow() -> pd.DataFrame:
    if not SHADOW_PATH.exists():
        return pd.DataFrame(columns=COLS)
    d = pd.read_csv(SHADOW_PATH)
    for c in COLS:
        if c not in d.columns:
            d[c] = None
    d["fecha"] = pd.to_datetime(d["fecha"], errors="coerce").dt.strftime("%Y-%m-%d")
    d["frozen"] = d["frozen"].astype(str).str.lower().isin({"true", "1", "yes"})
    return d[COLS].dropna(subset=["model_key", "fecha"]).copy()


def sbs_maps() -> tuple[dict[str, float], dict[str, float]]:
    s = pd.read_csv(SBS_PATH)
    s["fecha"] = pd.to_datetime(s["fecha"], errors="coerce")
    s["valor_cuota"] = pd.to_numeric(s["valor_cuota"], errors="coerce")
    s = s.dropna(subset=["fecha", "valor_cuota"]).sort_values("fecha").drop_duplicates("fecha", keep="last")
    s["actual_return_daily"] = s["valor_cuota"].pct_change(fill_method=None)
    vc = {d.date().isoformat(): float(v) for d, v in zip(s["fecha"], s["valor_cuota"])}
    ret = {d.date().isoformat(): float(v) for d, v in zip(s["fecha"], s["actual_return_daily"]) if finite(v)}
    return vc, ret


def upsert_prediction(d: pd.DataFrame, model_key: str, model_name: str, row: dict, signal_date: str, market_open: bool, meta: dict, now: str) -> pd.DataFrame:
    fecha = str(row.get("fecha", ""))[:10]
    if not fecha or not finite(row.get("vc_estimated")) or not finite(row.get("return_estimated")):
        return d
    mask = d["model_key"].eq(model_key) & d["fecha"].eq(fecha)
    existing = d.loc[mask]
    should_freeze = fecha < signal_date or (fecha == signal_date and not market_open)

    # Una prediccion congelada es inmutable: nunca se reescribe cuando SBS revela el VC.
    if not existing.empty and bool(existing.iloc[-1]["frozen"]):
        return d

    payload = {
        "model_key": model_key,
        "model_name": model_name,
        "fecha": fecha,
        "first_generated_at_lima": now if existing.empty else existing.iloc[-1]["first_generated_at_lima"],
        "last_updated_at_lima": now,
        "frozen": bool(should_freeze),
        "anchor_date": str(meta.get("anchor_date") or "")[:10],
        "anchor_vc": float(meta.get("anchor_vc")) if finite(meta.get("anchor_vc")) else None,
        "base_vc": float(row.get("base_vc")) if finite(row.get("base_vc")) else None,
        "vc_estimated": float(row["vc_estimated"]),
        "return_estimated": float(row["return_estimated"]),
        "signal": str(row.get("signal") or ""),
        "actual_vc": None,
        "actual_return_daily": None,
        "error_vc": None,
        "error_pct": None,
        "direction_hit": None,
        "source": "OPERACIONAL ROLLING30 · CIERRE" if should_freeze else "OPERACIONAL ROLLING30 · INTRADIA PROVISIONAL",
    }
    if not existing.empty:
        d = d.loc[~mask].copy()
    return pd.concat([d, pd.DataFrame([payload])], ignore_index=True)


def reconcile(d: pd.DataFrame, vc_map: dict[str, float], ret_map: dict[str, float]) -> pd.DataFrame:
    for idx, r in d.iterrows():
        fecha = str(r["fecha"])
        actual = vc_map.get(fecha)
        if actual is None or not finite(r.get("vc_estimated")):
            continue
        est = float(r["vc_estimated"])
        d.at[idx, "actual_vc"] = actual
        d.at[idx, "error_vc"] = est - actual
        d.at[idx, "error_pct"] = (est / actual - 1.0) * 100.0
        actual_ret = ret_map.get(fecha)
        if actual_ret is not None:
            d.at[idx, "actual_return_daily"] = actual_ret
            er = float(r["return_estimated"]) if finite(r.get("return_estimated")) else 0.0
            d.at[idx, "direction_hit"] = bool(np.sign(er) == np.sign(actual_ret))
    return d


def metrics(rows: list[dict]) -> dict:
    x = [r for r in rows if finite(r.get("actual_vc")) and finite(r.get("vc_estimated"))]
    if not x:
        return {"n": 0, "mae_vc": None, "rmse_vc": None, "mape_pct": None, "direction_accuracy_pct": None}
    est = np.array([float(r["vc_estimated"]) for r in x])
    actual = np.array([float(r["actual_vc"]) for r in x])
    err = est - actual
    dh = [r.get("direction_hit") for r in x if isinstance(r.get("direction_hit"), (bool, np.bool_))]
    return {
        "n": len(x),
        "start": min(r["fecha"] for r in x),
        "end": max(r["fecha"] for r in x),
        "mae_vc": float(np.mean(np.abs(err))),
        "rmse_vc": float(np.sqrt(np.mean(err ** 2))),
        "mape_pct": float(np.mean(np.abs(err / actual)) * 100.0),
        "direction_accuracy_pct": float(np.mean(dh) * 100.0) if dh else None,
    }


def main() -> None:
    dual = json.loads(DUAL_PATH.read_text(encoding="utf-8"))
    d = load_shadow()
    now = pd.Timestamp.now(tz=LIMA).isoformat()
    signal_date = str(dual.get("signal_date", ""))[:10]
    market_open = bool(dual.get("market_open"))

    for key, model in dual.get("models", {}).items():
        meta = model.get("current", {})
        for row in model.get("forward_chain", []) or []:
            d = upsert_prediction(d, key, model.get("name", key), row, signal_date, market_open, meta, now)

    vc_map, ret_map = sbs_maps()
    d = reconcile(d, vc_map, ret_map)
    d = d.sort_values(["fecha", "model_key"]).drop_duplicates(["model_key", "fecha"], keep="last").reset_index(drop=True)

    SHADOW_PATH.parent.mkdir(parents=True, exist_ok=True)
    d.to_csv(SHADOW_PATH, index=False)

    for key, model in dual.get("models", {}).items():
        g = d.loc[d["model_key"].eq(key)].copy().sort_values("fecha")
        rows = []
        for _, r in g.iterrows():
            def val(name):
                v = r.get(name)
                if pd.isna(v):
                    return None
                if name == "frozen" or name == "direction_hit":
                    return bool(v)
                if name in {"actual_vc", "actual_return_daily", "error_vc", "error_pct", "anchor_vc", "base_vc", "vc_estimated", "return_estimated"}:
                    return float(v) if finite(v) else None
                return v
            rows.append({k: val(k) for k in COLS})
        model["history_operational"] = rows
        model["operational_metrics"] = metrics(rows)

    dual["operational_history_rule"] = (
        "Cada prediccion diaria se congela al cierre y queda inmutable. Cuando SBS publica el VC real, "
        "solo se completa actual_vc/error; el VC estimado historico no se recalcula ni se reancla retroactivamente."
    )
    DUAL_PATH.write_text(json.dumps(dual, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "shadow_rows": int(len(d)),
        "qqq": dual.get("models", {}).get("qqq", {}).get("operational_metrics"),
        "new_tickers": dual.get("models", {}).get("new_tickers", {}).get("operational_metrics"),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
