from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
BASE_PATH = ROOT / "scripts" / "finalize_notebook_parity_v5.py"

spec = importlib.util.spec_from_file_location("fondo3_v5_hybrid_base", BASE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError(f"No se pudo cargar {BASE_PATH}")
v5 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v5)

# Modelo operativo de 7 factores. EEM se incorpora al mismo universo Yahoo que
# SPY/NEM/FCX/EPU/MCHI y usa exactamente el mismo Close diario.
if "EEM" not in v5.parity.engine.ASSETS:
    v5.parity.engine.ASSETS.append("EEM")
v5.parity.FEATURES = [f"ret_{x}" for x in v5.parity.engine.ASSETS] + ["ret_USD_PEN"]
v5.parity.EQUITY_FEATURES = [f"ret_{x}" for x in v5.parity.engine.ASSETS]
v5.parity.engine.FEATURES = list(v5.parity.FEATURES)

_original_run = v5._run_with_canonical_history
_original_write_outputs = v5.parity._write_outputs
_original_download_yahoo = v5.parity.engine.download_yahoo
_original_rebuild_markets = v5.parity._rebuild_markets_notebook


def _prepare_saved_markets_for_eem() -> None:
    """Permite la primera migración 6 -> 7 factores sin inventar datos de EEM.

    El archivo guardado histórico aún puede no tener la columna EEM. Se crea
    vacía únicamente para que la rutina de combinación pueda ejecutarse; los
    valores de EEM deben venir de la descarga Yahoo Finance del mismo proceso.
    Si Yahoo no devuelve EEM, la validación de observaciones completas fallará
    en vez de sustituirlo por otra fuente.
    """
    path = v5.parity.DATA / "markets.csv"
    saved = v5.parity.engine.read_saved(path)
    if saved.empty or "EEM" in saved.columns:
        return
    saved["EEM"] = np.nan
    v5.parity.engine.save_csv(saved, path)
    print("Migración EEM: columna creada; valores serán descargados desde Yahoo Finance.")


def _download_yahoo_repaired() -> pd.DataFrame:
    """Repara huecos recientes de la descarga múltiple con consultas individuales.

    Yahoo puede devolver la fila de una sesión para SPY/NEM/FCX/EPU/MCHI y dejar
    un ticker aislado (por ejemplo EEM) vacío. Ese hueco hacía que el modelo
    considerara 14/08 como último mercado aunque el 17/08 ya hubiera cerrado.
    Se conserva Yahoo como única fuente de los ETF y solo se reintenta cada ticker
    individualmente para la cola reciente.
    """
    try:
        market = _original_download_yahoo().copy()
    except Exception as exc:
        print(f"Yahoo múltiple incompleto: {type(exc).__name__}: {exc}")
        market = pd.DataFrame(columns=["fecha", *v5.parity.engine.ASSETS])

    if "fecha" not in market.columns:
        market["fecha"] = pd.NaT
    market["fecha"] = pd.to_datetime(market["fecha"], errors="coerce")
    for ticker in v5.parity.engine.ASSETS:
        if ticker not in market.columns:
            market[ticker] = np.nan
        market[ticker] = pd.to_numeric(market[ticker], errors="coerce")

    now_lima = pd.Timestamp.now(tz="America/Lima")
    start = (now_lima - pd.Timedelta(days=35)).strftime("%Y-%m-%d")
    end = (now_lima + pd.Timedelta(days=2)).strftime("%Y-%m-%d")

    for ticker in v5.parity.engine.ASSETS:
        try:
            raw = yf.download(
                tickers=ticker,
                start=start,
                end=end,
                interval="1d",
                auto_adjust=False,
                actions=False,
                progress=False,
                threads=False,
            )
            ser = v5.parity._extract_close(raw, ticker)
            if ser.empty:
                print(f"Reintento Yahoo {ticker}: sin datos")
                continue
            idx = pd.to_datetime(ser.index)
            if getattr(idx, "tz", None) is not None:
                idx = idx.tz_convert("America/New_York").tz_localize(None)
            repair = pd.DataFrame(
                {
                    "fecha": idx.normalize(),
                    f"{ticker}__repair": ser.to_numpy(float),
                }
            )
            repair = (
                repair.dropna(subset=["fecha", f"{ticker}__repair"])
                .sort_values("fecha")
                .drop_duplicates("fecha", keep="last")
            )
            market = market.merge(repair, on="fecha", how="outer")
            repaired_col = f"{ticker}__repair"
            market[ticker] = pd.to_numeric(
                market[repaired_col], errors="coerce"
            ).combine_first(pd.to_numeric(market[ticker], errors="coerce"))
            market = market.drop(columns=[repaired_col])
        except Exception as exc:
            print(f"Reintento Yahoo {ticker} falló: {type(exc).__name__}: {exc}")

    return (
        market.dropna(subset=["fecha"])
        .sort_values("fecha")
        .drop_duplicates("fecha", keep="last")
        .reset_index(drop=True)
    )


def _rebuild_markets_persisted() -> tuple[pd.DataFrame, str]:
    """Reconstruye mercados con el reintento Yahoo y persiste la cola reparada."""
    markets, note = _original_rebuild_markets()
    v5.parity.engine.save_csv(markets, v5.parity.DATA / "markets.csv")
    return markets, note + "; reintento individual Yahoo habilitado para huecos recientes"


def _penx_daily_returns() -> dict[pd.Timestamp, float]:
    """Retornos diarios PEN=X de Yahoo, solo para respaldo provisional."""
    try:
        raw = yf.download(
            tickers="PEN=X",
            period="1y",
            interval="1d",
            auto_adjust=False,
            actions=False,
            progress=False,
            threads=False,
        )
        ser = v5.parity._extract_close(raw, "PEN=X")
        if ser.empty:
            return {}
        idx = pd.to_datetime(ser.index)
        if getattr(idx, "tz", None) is not None:
            idx = idx.tz_convert("America/New_York").tz_localize(None)
        frame = pd.DataFrame({"fecha": idx.normalize(), "precio": ser.to_numpy(float)})
        frame = frame.dropna().sort_values("fecha").drop_duplicates("fecha", keep="last")
        frame["retorno"] = frame["precio"].pct_change(fill_method=None)
        return {
            pd.Timestamp(r.fecha): float(r.retorno)
            for r in frame.itertuples()
            if np.isfinite(r.retorno)
        }
    except Exception as exc:
        print(f"Yahoo PEN=X provisional no disponible: {type(exc).__name__}: {exc}")
        return {}


def _run_hybrid(sbs: pd.DataFrame, markets: pd.DataFrame):
    historical, pending, meta = _original_run(sbs, markets)
    if pending.empty:
        return historical, pending, meta

    yahoo_returns = _penx_daily_returns()
    out = pending.copy().sort_values("fecha").reset_index(drop=True)
    out["ret_USD_PEN_bcrp"] = np.where(out["usd_pen_fresco"], out["ret_USD_PEN"], np.nan)
    out["ret_USD_PEN_yahoo"] = np.nan
    out["usd_pen_fuente"] = np.where(out["usd_pen_fresco"], "BCRP", "SIN DATO")
    out["usd_pen_provisional"] = False

    for i, row in out.iterrows():
        if bool(row["usd_pen_fresco"]):
            continue
        fecha = pd.Timestamp(row["fecha"]).normalize()
        yahoo_ret = yahoo_returns.get(fecha)
        if yahoo_ret is not None and np.isfinite(yahoo_ret):
            out.at[i, "ret_USD_PEN_yahoo"] = float(yahoo_ret)
            out.at[i, "ret_USD_PEN"] = float(yahoo_ret)
            out.at[i, "usd_pen_fuente"] = "YAHOO PEN=X PROVISIONAL"
            out.at[i, "usd_pen_provisional"] = True
            out.at[i, "estado_fuentes"] = "USD/PEN YAHOO PEN=X · PROVISIONAL"
            out.at[i, "estado"] = "PROVISIONAL / FX YAHOO PEN=X"
        else:
            out.at[i, "ret_USD_PEN"] = 0.0
            out.at[i, "estado_fuentes"] = "USD/PEN SIN DATO · 0 % PROVISIONAL"
            out.at[i, "estado"] = "PROVISIONAL / FX SIN DATO"

    # El entrenamiento y sus coeficientes no cambian por la regla híbrida de FX:
    # usa BCRP histórico. EEM sí forma parte estructural del OLS de 7 factores.
    beta = meta["coefficients"]
    base = float(meta["latest_sbs_vc"])
    for i, row in out.iterrows():
        pred = float(beta["intercept"])
        for feature in v5.parity.FEATURES:
            pred += float(beta[feature]) * float(row[feature])
        estimate = base * (1.0 + pred)
        out.at[i, "valor_cuota_base"] = base
        out.at[i, "ret_estimado"] = pred
        out.at[i, "valor_cuota_estimado"] = estimate
        out.at[i, "senal"] = v5.parity._classify(pred)
        base = estimate

    return historical, out, meta


def _write_outputs_hybrid(sbs, markets, historical, pending, meta, market_note):
    latest = _original_write_outputs(sbs, markets, historical, pending, meta, market_note)
    latest["parity_rule"] = (
        "BCRP exclusivo para histórico/entrenamiento; en predicción pendiente se usa BCRP si existe; "
        "si BCRP está rezagado se usa Yahoo PEN=X provisional; 0 % solo si ambas fuentes faltan; VC encadenado"
    )
    latest.setdefault("sources", {})["fx"] = (
        "BCRP PD04646PD para histórico y entrenamiento; Yahoo PEN=X solo como respaldo provisional "
        "de predicciones cuando BCRP aún no publicó la fecha"
    )
    latest["sources"]["EEM"] = "Yahoo Finance · Close · auto_adjust=False · misma descarga que los demás ETF"
    latest["model_factors"] = [*v5.parity.engine.ASSETS, "USD_PEN"]
    if not pending.empty:
        last = pending.sort_values("fecha").iloc[-1]
        latest["latest_fx_source"] = str(last.get("usd_pen_fuente", "BCRP"))
        latest["latest_fx_provisional"] = bool(last.get("usd_pen_provisional", False))
    else:
        latest["latest_fx_source"] = "BCRP"
        latest["latest_fx_provisional"] = False
    return latest


v5.parity.engine.download_yahoo = _download_yahoo_repaired
v5.parity._rebuild_markets_notebook = _rebuild_markets_persisted
v5._run_with_canonical_history = _run_hybrid
v5.parity._write_outputs = _write_outputs_hybrid


if __name__ == "__main__":
    _prepare_saved_markets_for_eem()
    v5.main()
    # v5 conserva por compatibilidad el nombre del motor live anterior; actualizamos
    # únicamente la etiqueta de auditoría después de que finaliza su validación interna.
    latest = json.loads(v5.LATEST_PATH.read_text(encoding="utf-8"))
    latest["live_engine"] = "INDEPENDIENTE: update_live_market_hybrid.py"

    # Control anti-regresión: si los cinco activos base ya tienen una sesión,
    # EEM también debe tenerla. Nunca volver a publicar silenciosamente un viernes
    # como último mercado por un hueco aislado de EEM en el lunes siguiente.
    markets_check = v5.parity.engine.read_saved(v5.parity.DATA / "markets.csv")
    markets_check["fecha"] = pd.to_datetime(markets_check["fecha"], errors="coerce")
    core = ["SPY", "NEM", "FCX", "EPU", "MCHI"]
    recent_core = (
        markets_check.dropna(subset=core)
        .sort_values("fecha")
        .tail(5)
    )
    if recent_core.empty:
        raise RuntimeError("No hay sesiones recientes de los cinco activos base para validar EEM")
    missing_eem = recent_core.loc[recent_core["EEM"].isna(), "fecha"]
    if not missing_eem.empty:
        dates = ", ".join(pd.Timestamp(x).strftime("%Y-%m-%d") for x in missing_eem)
        raise RuntimeError(f"EEM sigue faltando en sesiones ya cerradas: {dates}")

    expected_market_date = pd.Timestamp(recent_core.iloc[-1]["fecha"]).normalize()
    published_market_date = pd.Timestamp(latest["latest_market_date"]).normalize()
    if published_market_date != expected_market_date:
        raise RuntimeError(
            "Último mercado inconsistente: "
            f"latest.json={published_market_date:%Y-%m-%d}, "
            f"mercados={expected_market_date:%Y-%m-%d}"
        )

    if expected_market_date > pd.Timestamp(latest["latest_sbs_date"]).normalize():
        pending_check = v5.parity.engine.read_saved(v5.PENDING_PATH)
        pending_check["fecha"] = pd.to_datetime(pending_check["fecha"], errors="coerce")
        if expected_market_date not in set(pending_check["fecha"].dropna().dt.normalize()):
            raise RuntimeError(
                f"La sesión {expected_market_date:%Y-%m-%d} existe pero no fue estimada por el OLS"
            )

    v5.LATEST_PATH.write_text(json.dumps(latest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Último mercado validado: {expected_market_date:%Y-%m-%d}")

# FORCE_RECALC_2026_08_18: cambio inocuo para disparar el workflow pesado de Profuturo inmediatamente.
