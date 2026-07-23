from __future__ import annotations

import importlib.util
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "rolling90"
PUBLIC_DATA = ROOT / "public" / "data"
ENGINE_PATH = ROOT / "scripts" / "build_rolling90_pages.py"

spec = importlib.util.spec_from_file_location("rolling90_final_engine", ENGINE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError(f"No se pudo cargar {ENGINE_PATH}")
engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)

LIMA = ZoneInfo("America/Lima")


def _clean_fx_history(markets: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    """BCRP gobierna el histórico; valores guardados solo sobreviven después del último BCRP."""
    out = markets.copy()
    out["fecha"] = pd.to_datetime(out["fecha"], errors="coerce")
    try:
        bcrp = engine.load_bcrp().copy()
        bcrp["fecha"] = pd.to_datetime(bcrp["fecha"], errors="coerce")
        bcrp["USD_PEN"] = pd.to_numeric(bcrp["USD_PEN"], errors="coerce")
        bcrp = bcrp.dropna().sort_values("fecha").drop_duplicates("fecha", keep="last")
    except Exception as exc:
        return out, f"BCRP no disponible en auditoría final: {type(exc).__name__}: {exc}"

    if bcrp.empty:
        return out, "BCRP vacío en auditoría final; se conservó el respaldo existente"

    last_bcrp = pd.Timestamp(bcrp["fecha"].max())
    bcrp_map = bcrp.set_index("fecha")["USD_PEN"]

    # Eliminar cualquier relleno histórico procedente de Yahoo/Stooq antes o en
    # la última fecha oficial BCRP. Solo fechas realmente publicadas por BCRP
    # reciben USD/PEN dentro de ese tramo.
    hist_mask = out["fecha"].le(last_bcrp)
    out.loc[hist_mask, "USD_PEN"] = out.loc[hist_mask, "fecha"].map(bcrp_map)

    # Recalcular retorno FX únicamente sobre observaciones válidas, exactamente
    # igual que el motor base hace con cada variable.
    valid = out[["fecha", "USD_PEN"]].dropna().sort_values("fecha").drop_duplicates("fecha", keep="last")
    valid["ret_USD_PEN"] = valid["USD_PEN"].pct_change(fill_method=None)
    out = out.drop(columns=["ret_USD_PEN"], errors="ignore").merge(
        valid[["fecha", "ret_USD_PEN"]], on="fecha", how="left"
    )
    return out.sort_values("fecha").drop_duplicates("fecha", keep="last").reset_index(drop=True), (
        f"BCRP histórico validado hasta {last_bcrp:%Y-%m-%d}; respaldo permitido solo después"
    )


def _write_outputs(sbs: pd.DataFrame, markets: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    historical, pending, meta = engine.run_model(sbs, markets)
    series = engine.build_series(sbs, pending)

    engine.save_csv(historical, DATA / "historical_predictions.csv")
    engine.save_csv(pending, DATA / "pending_predictions.csv")
    engine.save_csv(markets, DATA / "markets.csv")

    series_out = series.copy()
    series_out["fecha"] = pd.to_datetime(series_out["fecha"]).dt.strftime("%Y-%m-%d")
    (PUBLIC_DATA / "series.json").write_text(
        series_out.to_json(orient="records", force_ascii=False), encoding="utf-8"
    )
    engine.save_csv(series, PUBLIC_DATA / "series.csv")

    if not pending.empty:
        row = pending.sort_values("fecha").iloc[-1]
        latest_vc = float(row["valor_cuota_estimado"])
        latest_return = float(row["ret_estimado"])
        latest_signal = str(row["senal"])
        estimate_date = pd.Timestamp(row["fecha"])
        estimate_type = "CIERRE DIARIO · MODELO OLS"
    else:
        row = historical.sort_values("fecha").iloc[-1]
        latest_vc = float(meta["latest_sbs_vc"])
        latest_return = float(row["ret_estimado"])
        latest_signal = str(row["senal"])
        estimate_date = pd.Timestamp(meta["latest_sbs_date"])
        estimate_type = "SBS AL DÍA"

    previous = {}
    latest_path = PUBLIC_DATA / "latest.json"
    if latest_path.exists():
        try:
            previous = json.loads(latest_path.read_text(encoding="utf-8"))
        except Exception:
            previous = {}

    latest = {
        "generated_at_lima": datetime.now(LIMA).isoformat(),
        "model": "OLS rolling 90",
        "window": engine.WINDOW,
        "threshold": engine.THRESHOLD,
        "training_start": pd.Timestamp(meta["train_start"]).strftime("%Y-%m-%d"),
        "training_end": pd.Timestamp(meta["train_end"]).strftime("%Y-%m-%d"),
        "training_n": int(meta["train_n"]),
        "latest_sbs_date": pd.Timestamp(meta["latest_sbs_date"]).strftime("%Y-%m-%d"),
        "latest_sbs_vc": float(meta["latest_sbs_vc"]),
        "latest_market_date": pd.Timestamp(meta["latest_market_date"]).strftime("%Y-%m-%d"),
        "latest_estimate_date": estimate_date.strftime("%Y-%m-%d"),
        "latest_estimated_vc": latest_vc,
        "latest_return_estimated": latest_return,
        "signal": latest_signal,
        "estimate_type": estimate_type,
        "sources": previous.get("sources", {}),
        "warnings": previous.get("warnings", []),
        "coefficients": {
            "intercept": float(meta["beta"][0]),
            **{k: float(v) for k, v in zip(engine.FEATURES, meta["beta"][1:])},
        },
        "parity_rule": "Sin anticipación; 90 observaciones completas; BCRP histórico; sin imputación FX=0; VC pendiente encadenado",
        "vc_mode_rule": "INTRADÍA PROVISIONAL 09:30-16:10 NY; fuera de ese intervalo CIERRE DIARIO",
    }
    latest.setdefault("sources", {})["fx"] = "BCRP histórico; Yahoo PEN=X solo cola posterior a la última fecha BCRP"
    latest["sources"]["market"] = "Yahoo Finance; respaldo de cola reciente si Yahoo no responde"
    latest_path.write_text(json.dumps(latest, ensure_ascii=False, indent=2), encoding="utf-8")
    return historical, pending, meta


def _write_signals(historical: pd.DataFrame, pending: pd.DataFrame, sbs: pd.DataFrame) -> None:
    records: list[dict[str, object]] = []
    ss = sbs.copy().sort_values("fecha").drop_duplicates("fecha", keep="last")
    ss["valor_cuota"] = pd.to_numeric(ss["valor_cuota"], errors="coerce")
    ss["vc_previo"] = ss["valor_cuota"].shift(1)
    h = historical.merge(ss[["fecha", "vc_previo"]], on="fecha", how="left")
    h["vc_estimado"] = h["vc_previo"] * (1.0 + pd.to_numeric(h["ret_estimado"], errors="coerce"))
    for _, r in h.dropna(subset=["fecha", "ret_estimado"]).iterrows():
        records.append({
            "fecha": pd.Timestamp(r["fecha"]).strftime("%Y-%m-%d"),
            "ret_estimado": float(r["ret_estimado"]),
            "senal": str(r["senal"]),
            "vc_real": float(r["valor_cuota"]),
            "vc_estimado": None if pd.isna(r["vc_estimado"]) else float(r["vc_estimado"]),
            "tipo": "HISTORICO",
        })
    if not pending.empty:
        for _, r in pending.dropna(subset=["fecha", "ret_estimado"]).iterrows():
            records.append({
                "fecha": pd.Timestamp(r["fecha"]).strftime("%Y-%m-%d"),
                "ret_estimado": float(r["ret_estimado"]),
                "senal": str(r["senal"]),
                "vc_real": None,
                "vc_estimado": float(r["valor_cuota_estimado"]),
                "tipo": "PENDIENTE",
            })
    records.sort(key=lambda x: str(x["fecha"]))
    (PUBLIC_DATA / "signals.json").write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")


def _reprice_live(meta: dict, pending: pd.DataFrame) -> None:
    path = PUBLIC_DATA / "live_market.json"
    if not path.exists():
        return
    try:
        live = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return
    latest = json.loads((PUBLIC_DATA / "latest.json").read_text(encoding="utf-8"))

    if not live.get("market_open") or not str(live.get("mode", "")).startswith("INTRADÍA"):
        live["vc_estimated"] = latest["latest_estimated_vc"]
        live["return_estimated"] = latest["latest_return_estimated"]
        live["signal"] = latest["signal"]
        live["action"] = "CIERRE"
        path.write_text(json.dumps(live, ensure_ascii=False, indent=2), encoding="utf-8")
        return

    returns = {str(a.get("serie")): a.get("retorno") for a in live.get("assets", [])}
    features = {
        "ret_SPY": returns.get("SPY"),
        "ret_NEM": returns.get("NEM"),
        "ret_FCX": returns.get("FCX"),
        "ret_EPU": returns.get("EPU"),
        "ret_MCHI": returns.get("MCHI"),
        "ret_USD_PEN": returns.get("USD_PEN"),
    }
    if not all(v is not None and np.isfinite(float(v)) for v in features.values()):
        live["action"] = "ESPERAR"
        live["note"] = "Fuente intradía incompleta: no se trata la señal como definitiva."
        path.write_text(json.dumps(live, ensure_ascii=False, indent=2), encoding="utf-8")
        return

    beta = latest["coefficients"]
    pred = float(beta["intercept"] + sum(float(beta[k]) * float(features[k]) for k in engine.FEATURES))
    signal_date = pd.Timestamp(live["signal_date"])
    prior = pending.loc[pd.to_datetime(pending["fecha"]) < signal_date].sort_values("fecha") if not pending.empty else pd.DataFrame()
    vc_base = float(prior.iloc[-1]["valor_cuota_estimado"]) if not prior.empty else float(latest["latest_sbs_vc"])
    vc_est = vc_base * (1.0 + pred)
    live["vc_base"] = vc_base
    live["vc_estimated"] = vc_est
    live["return_estimated"] = pred
    live["signal"] = engine.classify(pred)
    live["action"] = "ESPERAR"  # intradía siempre es provisional
    live["note"] = "INTRADÍA PROVISIONAL: puede cambiar hasta 16:10 Nueva York. Señal orientativa; acción ESPERAR hasta cierre."
    path.write_text(json.dumps(live, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    sbs = engine.read_saved(DATA / "sbs_profuturo_f3.csv")
    markets = engine.read_saved(DATA / "markets.csv")
    if sbs.empty or markets.empty:
        raise RuntimeError("Faltan SBS o mercados para la auditoría final")
    sbs["fecha"] = pd.to_datetime(sbs["fecha"], errors="coerce")
    markets["fecha"] = pd.to_datetime(markets["fecha"], errors="coerce")

    markets, fx_note = _clean_fx_history(markets)
    historical, pending, meta = _write_outputs(sbs, markets)
    _write_signals(historical, pending, sbs)
    _reprice_live(meta, pending)

    # Controles equivalentes a los del notebook final.
    assert int(meta["train_n"]) == 90
    if not historical.empty:
        assert (pd.to_datetime(historical["ventana_fin"]) < pd.to_datetime(historical["fecha"])).all()
    if len(pending) > 1:
        ordered = pending.sort_values("fecha").reset_index(drop=True)
        np.testing.assert_allclose(
            ordered["valor_cuota_base"].iloc[1:].to_numpy(float),
            ordered["valor_cuota_estimado"].iloc[:-1].to_numpy(float),
            rtol=0,
            atol=1e-10,
        )
    print("AUDITORÍA FINAL APROBADA")
    print(fx_note)
    print(f"Ventana: {meta['train_start']:%Y-%m-%d} -> {meta['train_end']:%Y-%m-%d} · n=90")


if __name__ == "__main__":
    main()
