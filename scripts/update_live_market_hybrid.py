from __future__ import annotations

import importlib.util
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
BASE_PATH = ROOT / "scripts" / "update_live_market_only.py"

spec = importlib.util.spec_from_file_location("fondo3_live_base", BASE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError(f"No se pudo cargar {BASE_PATH}")
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)


def _configure_assets_from_model(latest: dict) -> None:
    """El intradía usa exactamente los factores publicados por el OLS vigente.

    Durante la migración, un latest.json antiguo de 6 factores sigue funcionando.
    En cuanto latest.json publica ret_EEM, EEM entra automáticamente en la misma
    descarga Yahoo intradía que los demás ETF.
    """
    if "ret_EEM" in (latest.get("coefficients", {}) or {}) and "EEM" not in base.ASSETS:
        base.ASSETS.append("EEM")
    base.FEATURES = [f"ret_{x}" for x in base.ASSETS] + ["ret_USD_PEN"]


def _fx_row(payload: dict) -> dict | None:
    for row in payload.get("assets", []):
        if row.get("serie") == "USD_PEN":
            return row
    return None


def _apply_hybrid_fx(payload: dict, latest: dict, pending: pd.DataFrame) -> dict:
    row = _fx_row(payload)
    if row is None:
        payload["fx_source"] = "SIN DATO"
        payload["fx_provisional"] = True
        return payload

    # BCRP de la misma fecha siempre tiene prioridad y conserva la metodología histórica.
    if "BCRP MISMA FECHA" in str(row.get("estado", "")):
        payload["fx_source"] = "BCRP"
        payload["fx_provisional"] = False
        payload["fx_rule"] = "BCRP si existe; Yahoo PEN=X solo como respaldo provisional cuando BCRP aún no publicó la fecha."
        return payload

    signal_date = pd.Timestamp(payload.get("signal_date")).normalize()

    if payload.get("market_open"):
        # El motor base ya descargó PEN=X intradía como referencia visual. Reutilizamos
        # exactamente ese retorno, pero ahora sí entra provisionalmente al OLS.
        fx_ret = pd.to_numeric(pd.Series([row.get("retorno")]), errors="coerce").iloc[0]
        if np.isfinite(fx_ret):
            beta_fx = float(latest["coefficients"]["ret_USD_PEN"])
            old_pred = float(payload["return_estimated"])
            new_pred = old_pred + beta_fx * float(fx_ret)
            vc_base = float(payload.get("vc_base", latest["latest_sbs_vc"]))
            payload["return_estimated"] = new_pred
            payload["vc_estimated"] = vc_base * (1.0 + new_pred)
            payload["signal"] = base._classify(new_pred)

            current = row.get("precio_actual")
            if current is not None and np.isfinite(float(current)) and abs(1.0 + float(fx_ret)) > 1e-12:
                row["precio_anterior"] = float(current) / (1.0 + float(fx_ret))
            row["ticker"] = "PEN=X"
            row["retorno_modelo"] = float(fx_ret)
            row["estado"] = "YAHOO PEN=X · PROVISIONAL · USADO POR MODELO"
            row["usado_modelo"] = True
            payload["fx_source"] = "YAHOO PEN=X PROVISIONAL"
            payload["fx_provisional"] = True
        else:
            row["retorno_modelo"] = 0.0
            row["estado"] = "USD/PEN SIN DATO · MODELO USA 0 %"
            row["usado_modelo"] = True
            payload["fx_source"] = "SIN DATO · 0 %"
            payload["fx_provisional"] = True
    else:
        # Fuera de mercado, latest.json ya contiene el cálculo diario híbrido. Ajustamos
        # la tarjeta USD/PEN para que el celular muestre la fuente realmente utilizada.
        p = pending.copy()
        if not p.empty:
            p["fecha"] = pd.to_datetime(p["fecha"], errors="coerce")
            same = p.loc[p["fecha"].dt.normalize().eq(signal_date)].sort_values("fecha")
        else:
            same = pd.DataFrame()

        if not same.empty:
            r = same.iloc[-1]
            source = str(r.get("usd_pen_fuente", ""))
            if source.startswith("YAHOO"):
                fx_ret = float(r.get("ret_USD_PEN", 0.0))
                row["ticker"] = "PEN=X"
                row["precio_anterior"] = None
                row["precio_actual"] = None
                row["retorno"] = fx_ret
                row["retorno_modelo"] = fx_ret
                row["estado"] = "YAHOO PEN=X · PROVISIONAL · USADO POR MODELO"
                row["usado_modelo"] = True
                payload["fx_source"] = "YAHOO PEN=X PROVISIONAL"
                payload["fx_provisional"] = True
            elif source == "BCRP":
                payload["fx_source"] = "BCRP"
                payload["fx_provisional"] = False
            else:
                row["retorno_modelo"] = 0.0
                row["estado"] = "USD/PEN SIN DATO · MODELO USA 0 %"
                row["usado_modelo"] = True
                payload["fx_source"] = "SIN DATO · 0 %"
                payload["fx_provisional"] = True
        else:
            payload["fx_source"] = str(latest.get("latest_fx_source", "SIN DATO"))
            payload["fx_provisional"] = bool(latest.get("latest_fx_provisional", True))

    payload["fx_rule"] = (
        "Histórico/entrenamiento: BCRP. Predicción: BCRP si existe; "
        "si está rezagado, Yahoo PEN=X provisional; 0 % solo si ambas fuentes faltan."
    )
    return payload


def main() -> None:
    if not base.LATEST_PATH.exists():
        raise RuntimeError("Falta public/data/latest.json")
    latest = json.loads(base.LATEST_PATH.read_text(encoding="utf-8"))
    _configure_assets_from_model(latest)
    markets = base._read_csv(base.MARKETS_PATH)
    pending = base._read_csv(base.PENDING_PATH)
    if markets.empty:
        raise RuntimeError("Falta data/rolling90/markets.csv")

    try:
        payload = base._build_live(latest, markets, pending)
        payload = _apply_hybrid_fx(payload, latest, pending)
    except Exception as exc:
        previous: dict = {}
        if base.LIVE_PATH.exists():
            try:
                previous = json.loads(base.LIVE_PATH.read_text(encoding="utf-8"))
            except Exception:
                previous = {}
        open_now = base._market_open_now()
        payload = {
            "generated_at_lima": datetime.now(base.LIMA).isoformat(),
            "mode": "MERCADO ABIERTO · INTRADÍA NO DISPONIBLE" if open_now else "CIERRE DIARIO · ACTUALIZACIÓN NO DISPONIBLE",
            "market_open": open_now,
            "signal_date": datetime.now(base.NY).date().isoformat() if open_now else latest.get("latest_market_date"),
            "vc_estimated": float(latest["latest_estimated_vc"]),
            "return_estimated": float(latest["latest_return_estimated"]),
            "signal": str(latest["signal"]),
            "assets": previous.get("assets", []),
            "action": "ESPERAR" if open_now else "CIERRE",
            "engine": "LIVE INDEPENDIENTE",
            "warning": f"{type(exc).__name__}: {exc}",
            "fx_source": latest.get("latest_fx_source", "SIN DATO"),
            "fx_provisional": latest.get("latest_fx_provisional", True),
            "fx_rule": "BCRP si existe; Yahoo PEN=X provisional si BCRP está rezagado; 0 % solo si ambas fuentes faltan.",
        }

    base.LIVE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

# SYNC_TRIGGER_EEM_20260727: fuerza una ejecución posterior a la publicación del OLS de 7 factores.
