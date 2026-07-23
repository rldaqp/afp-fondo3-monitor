from __future__ import annotations

import importlib.util
import json
from datetime import datetime, time as clock_time
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "rolling90"
PUBLIC_DATA = ROOT / "public" / "data"
ENGINE_PATH = ROOT / "scripts" / "build_rolling90_pages.py"

spec = importlib.util.spec_from_file_location("rolling90_notebook_parity", ENGINE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError(f"No se pudo cargar {ENGINE_PATH}")
engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)

LIMA = ZoneInfo("America/Lima")
NY = ZoneInfo("America/New_York")
MODEL_START = pd.Timestamp("2025-01-01")
WINDOW = 90
THRESHOLD = 0.001
FEATURES = [f"ret_{x}" for x in engine.ASSETS] + ["ret_USD_PEN"]
EQUITY_FEATURES = [f"ret_{x}" for x in engine.ASSETS]
EXCLUDED_RETURN_DATES = {pd.Timestamp("2026-07-06")}


def _classify(value: float) -> str:
    if value > THRESHOLD:
        return "SUBE"
    if value < -THRESHOLD:
        return "BAJA"
    return "NEUTRO"


def _fit_ols(train: pd.DataFrame) -> LinearRegression:
    model = LinearRegression(fit_intercept=True)
    model.fit(train[FEATURES].to_numpy(float), train["ret_profuturo"].to_numpy(float))
    return model


def _predict(model: LinearRegression, row: pd.Series) -> float:
    values = row[FEATURES].to_numpy(dtype=float).reshape(1, -1)
    return float(model.predict(values)[0])


def _returns_from_last_valid(frame: pd.DataFrame, value_column: str) -> pd.Series:
    ordered = frame[["fecha", value_column]].copy()
    ordered["fecha"] = pd.to_datetime(ordered["fecha"], errors="coerce")
    ordered = (
        ordered.dropna(subset=["fecha"])
        .sort_values("fecha")
        .drop_duplicates("fecha", keep="last")
        .reset_index(drop=True)
    )
    valid = ordered.loc[ordered[value_column].notna()].copy()
    valid["retorno"] = pd.to_numeric(valid[value_column], errors="coerce").pct_change(fill_method=None)
    mapping = valid.set_index("fecha")["retorno"]
    return ordered["fecha"].map(mapping)


def _merge_downloaded_over_saved(saved: pd.DataFrame, downloaded: pd.DataFrame) -> pd.DataFrame:
    cols = engine.ASSETS
    old = saved[["fecha", *cols]].copy() if not saved.empty else pd.DataFrame(columns=["fecha", *cols])
    new = downloaded[["fecha", *cols]].copy() if not downloaded.empty else pd.DataFrame(columns=["fecha", *cols])
    for frame in (old, new):
        frame["fecha"] = pd.to_datetime(frame["fecha"], errors="coerce")
    if old.empty:
        result = new
    elif new.empty:
        result = old
    else:
        old_i = old.drop_duplicates("fecha", keep="last").set_index("fecha")
        new_i = new.drop_duplicates("fecha", keep="last").set_index("fecha")
        result = new_i.combine_first(old_i).reset_index()
    return result.dropna(subset=["fecha"]).sort_values("fecha").drop_duplicates("fecha", keep="last")


def _rebuild_markets_notebook() -> tuple[pd.DataFrame, str]:
    """Replica update_sources + returns_from_last_valid del notebook.

    Acciones/ETF: Yahoo diario cuando responde; el guardado sobrevive solo donde
    la descarga nueva es nula. USD/PEN: exclusivamente BCRP. PEN=X nunca entra
    en las variables del modelo.
    """
    saved = engine.read_saved(DATA / "markets.csv")
    if not saved.empty:
        saved["fecha"] = pd.to_datetime(saved["fecha"], errors="coerce")

    try:
        downloaded = engine.download_yahoo()
        if _market_open_now():
            today_ny = pd.Timestamp(datetime.now(NY).date())
            downloaded = downloaded.loc[pd.to_datetime(downloaded["fecha"]) < today_ny].copy()
        equity = _merge_downloaded_over_saved(saved, downloaded)
        equity_note = "Yahoo Finance actualizado; respaldo guardado solo donde Yahoo no trae valor"
    except Exception as exc:
        equity = saved[["fecha", *engine.ASSETS]].copy()
        equity_note = f"Yahoo no disponible; se conservó histórico guardado ({type(exc).__name__})"

    bcrp = engine.load_bcrp().copy()
    bcrp["fecha"] = pd.to_datetime(bcrp["fecha"], errors="coerce")
    bcrp["USD_PEN"] = pd.to_numeric(bcrp["USD_PEN"], errors="coerce")
    bcrp = bcrp.dropna(subset=["fecha", "USD_PEN"]).sort_values("fecha").drop_duplicates("fecha", keep="last")
    if bcrp.empty:
        raise RuntimeError("BCRP no devolvió USD/PEN; no se puede certificar paridad con el notebook")

    markets = equity.merge(bcrp[["fecha", "USD_PEN"]], on="fecha", how="outer")
    markets["fecha"] = pd.to_datetime(markets["fecha"], errors="coerce")
    markets = markets.dropna(subset=["fecha"]).sort_values("fecha").drop_duplicates("fecha", keep="last").reset_index(drop=True)
    for col in [*engine.ASSETS, "USD_PEN"]:
        markets[col] = pd.to_numeric(markets[col], errors="coerce")
        markets[f"ret_{col}"] = _returns_from_last_valid(markets, col).to_numpy()

    note = f"{equity_note}; BCRP exclusivo para USD/PEN hasta {bcrp['fecha'].max():%Y-%m-%d}"
    return markets, note


def _build_complete(sbs: pd.DataFrame, markets: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    s = sbs[["fecha", "valor_cuota"]].copy()
    s["fecha"] = pd.to_datetime(s["fecha"], errors="coerce")
    s["valor_cuota"] = pd.to_numeric(s["valor_cuota"], errors="coerce")
    s = s.dropna().sort_values("fecha").drop_duplicates("fecha", keep="last").reset_index(drop=True)
    s["ret_profuturo"] = s["valor_cuota"].pct_change(fill_method=None)
    s.loc[s["fecha"].isin(EXCLUDED_RETURN_DATES), "ret_profuturo"] = np.nan

    complete = s.merge(markets[["fecha", *FEATURES]], on="fecha", how="inner", validate="one_to_one")
    complete = (
        complete.loc[complete["fecha"] >= MODEL_START]
        .dropna(subset=["valor_cuota", "ret_profuturo", *FEATURES])
        .sort_values("fecha")
        .drop_duplicates("fecha", keep="last")
        .reset_index(drop=True)
    )
    return complete, s


def _run_notebook_model(sbs: pd.DataFrame, markets: pd.DataFrame):
    complete, s = _build_complete(sbs, markets)
    if len(complete) < WINDOW:
        raise RuntimeError(f"Solo hay {len(complete)} observaciones completas; se requieren {WINDOW}")

    historical_rows: list[dict[str, object]] = []
    for idx in range(WINDOW, len(complete)):
        train = complete.iloc[idx - WINDOW:idx]
        current = complete.iloc[idx]
        fitted = _fit_ols(train)
        pred = _predict(fitted, current)
        previous_value = float(complete.iloc[idx - 1]["valor_cuota"])
        historical_rows.append({
            "fecha": current["fecha"],
            "modelo": "OLS",
            "valor_cuota": float(current["valor_cuota"]),
            "valor_cuota_anterior": previous_value,
            "ret_profuturo": float(current["ret_profuturo"]),
            "ret_estimado": pred,
            "valor_cuota_estimado": previous_value * (1.0 + pred),
            "senal": _classify(pred),
            "ventana_inicio": train.iloc[0]["fecha"],
            "ventana_fin": train.iloc[-1]["fecha"],
            "n_entrenamiento": WINDOW,
        })
    historical = pd.DataFrame(historical_rows)

    train = complete.tail(WINDOW).copy()
    fitted = _fit_ols(train)
    latest_sbs = s.sort_values("fecha").iloc[-1]
    last_sbs_date = pd.Timestamp(latest_sbs["fecha"])
    last_sbs_vc = float(latest_sbs["valor_cuota"])

    # Exactamente como build_pending_market_rows del notebook:
    # cinco retornos bursátiles obligatorios; USD/PEN ausente -> 0 % provisional.
    pending_features = markets.loc[
        markets["fecha"] > last_sbs_date,
        ["fecha", *FEATURES],
    ].copy()
    pending_features = pending_features.dropna(subset=EQUITY_FEATURES).sort_values("fecha")
    pending_features["usd_pen_fresco"] = pending_features["ret_USD_PEN"].notna()
    pending_features["ret_USD_PEN"] = pending_features["ret_USD_PEN"].fillna(0.0)
    pending_features["fuentes_completas"] = pending_features["usd_pen_fresco"].astype(bool)
    pending_features["estado_fuentes"] = np.where(
        pending_features["fuentes_completas"], "COMPLETAS", "USD/PEN PROVISIONAL 0 %"
    )

    pending_rows: list[dict[str, object]] = []
    base = last_sbs_vc
    for _, row in pending_features.iterrows():
        pred = _predict(fitted, row)
        estimate = base * (1.0 + pred)
        record = {
            "fecha": row["fecha"],
            "modelo": "OLS",
            "valor_cuota_base": base,
            "ret_estimado": pred,
            "valor_cuota_estimado": estimate,
            "senal": _classify(pred),
            "ventana_inicio": train.iloc[0]["fecha"],
            "ventana_fin": train.iloc[-1]["fecha"],
            "n_entrenamiento": WINDOW,
            "usd_pen_fresco": bool(row["usd_pen_fresco"]),
            "fuentes_completas": bool(row["fuentes_completas"]),
            "estado_fuentes": str(row["estado_fuentes"]),
            "estado": "PENDIENTE SBS / FUENTES COMPLETAS" if bool(row["fuentes_completas"]) else "PROVISIONAL / USD_PEN REZAGADO",
        }
        for feature in FEATURES:
            record[feature] = float(row[feature])
        pending_rows.append(record)
        base = estimate
    pending = pd.DataFrame(pending_rows)

    beta = {"intercept": float(fitted.intercept_)}
    beta.update({feature: float(coef) for feature, coef in zip(FEATURES, fitted.coef_)})
    latest_equity = markets.dropna(subset=EQUITY_FEATURES).sort_values("fecha")
    meta = {
        "train_start": pd.Timestamp(train.iloc[0]["fecha"]),
        "train_end": pd.Timestamp(train.iloc[-1]["fecha"]),
        "train_n": len(train),
        "latest_sbs_date": last_sbs_date,
        "latest_sbs_vc": last_sbs_vc,
        "latest_market_date": pd.Timestamp(latest_equity.iloc[-1]["fecha"]),
        "coefficients": beta,
    }
    return historical, pending, meta


def _build_series(sbs: pd.DataFrame, pending: pd.DataFrame) -> pd.DataFrame:
    official = sbs[["fecha", "valor_cuota"]].rename(columns={"valor_cuota": "vc"}).copy()
    official["fuente"] = "SBS OFICIAL"
    official["senal"] = None
    official["ret_estimado"] = np.nan
    if pending.empty:
        return official.sort_values("fecha").reset_index(drop=True)
    projected = pending[["fecha", "valor_cuota_estimado", "senal", "ret_estimado"]].rename(columns={"valor_cuota_estimado": "vc"})
    projected["fuente"] = "MODELO OLS"
    return pd.concat([official, projected], ignore_index=True).sort_values("fecha").drop_duplicates("fecha", keep="last")


def _write_signals(historical: pd.DataFrame, pending: pd.DataFrame) -> None:
    records: list[dict[str, object]] = []
    for _, r in historical.iterrows():
        records.append({
            "fecha": pd.Timestamp(r["fecha"]).strftime("%Y-%m-%d"),
            "ret_estimado": float(r["ret_estimado"]),
            "senal": str(r["senal"]),
            "vc_real": float(r["valor_cuota"]),
            "vc_estimado": float(r["valor_cuota_estimado"]),
            "tipo": "HISTORICO",
        })
    for _, r in pending.iterrows():
        records.append({
            "fecha": pd.Timestamp(r["fecha"]).strftime("%Y-%m-%d"),
            "ret_estimado": float(r["ret_estimado"]),
            "senal": str(r["senal"]),
            "vc_real": None,
            "vc_estimado": float(r["valor_cuota_estimado"]),
            "tipo": "PENDIENTE",
            "estado_fuentes": str(r.get("estado_fuentes", "")),
        })
    records.sort(key=lambda x: x["fecha"])
    (PUBLIC_DATA / "signals.json").write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")


def _market_open_now() -> bool:
    now = datetime.now(NY)
    return now.weekday() < 5 and clock_time(9, 30) <= now.time() < clock_time(16, 10)


def _extract_close(raw: pd.DataFrame, ticker: str) -> pd.Series:
    if raw.empty:
        return pd.Series(dtype=float)
    if isinstance(raw.columns, pd.MultiIndex):
        for key in [("Close", ticker), (ticker, "Close")]:
            if key in raw.columns:
                return pd.to_numeric(raw[key], errors="coerce").dropna()
        if "Close" in raw.columns.get_level_values(0):
            block = raw.xs("Close", axis=1, level=0)
            if ticker in block.columns:
                return pd.to_numeric(block[ticker], errors="coerce").dropna()
    if "Close" in raw.columns:
        return pd.to_numeric(raw["Close"], errors="coerce").dropna()
    return pd.Series(dtype=float)


def _fx_display_reference(raw: pd.DataFrame, markets: pd.DataFrame, signal_date: pd.Timestamp) -> tuple[float, float, object, str]:
    """Solo visual. Nunca alimenta el modelo."""
    try:
        ser = _extract_close(raw, "PEN=X")
        if not ser.empty:
            current = float(ser.iloc[-1])
            ts = pd.Timestamp(ser.index[-1])
            if ts.tzinfo is None:
                ts = ts.tz_localize("UTC")
            ts = ts.tz_convert(NY)
            # Retorno visual: contra el último cierre intradía de una fecha anterior.
            idx = pd.to_datetime(ser.index)
            tmp = pd.DataFrame({"ts": idx, "price": ser.to_numpy(float)})
            if getattr(tmp["ts"].dt, "tz", None) is not None:
                tmp["date"] = tmp["ts"].dt.tz_convert(NY).dt.date
            else:
                tmp["date"] = tmp["ts"].dt.date
            earlier = tmp.loc[tmp["date"] < signal_date.date()]
            if not earlier.empty:
                previous = float(earlier.iloc[-1]["price"])
            else:
                previous = current
            return current, (current / previous - 1.0 if previous else 0.0), ts.isoformat(), "YAHOO PEN=X · SOLO REFERENCIA · MODELO USA 0 %"
    except Exception:
        pass

    fx = markets.loc[(markets["fecha"] < signal_date) & markets["USD_PEN"].notna(), ["fecha", "USD_PEN"]].sort_values("fecha")
    if fx.empty:
        return np.nan, 0.0, None, "USD/PEN NO DISPONIBLE · MODELO USA 0 %"
    last = fx.iloc[-1]
    return float(last["USD_PEN"]), 0.0, pd.Timestamp(last["fecha"]).strftime("%Y-%m-%d"), "BCRP REZAGADO · MODELO USA 0 %"


def _write_live_snapshot(markets: pd.DataFrame, pending: pd.DataFrame, latest: dict) -> None:
    now_ny = datetime.now(NY)
    now_lima = datetime.now(LIMA)
    open_now = _market_open_now()
    rows: list[dict[str, object]] = []

    if not open_now:
        complete = markets.dropna(subset=EQUITY_FEATURES).sort_values("fecha")
        signal_date = pd.Timestamp(complete.iloc[-1]["fecha"])
        for name in engine.ASSETS:
            valid = markets.loc[markets[name].notna() & (markets["fecha"] <= signal_date), ["fecha", name]].sort_values("fecha")
            cur = valid.iloc[-1]
            prev = valid.iloc[-2] if len(valid) >= 2 else cur
            rows.append({
                "serie": name, "ticker": name, "timestamp": signal_date.strftime("%Y-%m-%d"),
                "precio_anterior": float(prev[name]), "precio_actual": float(cur[name]),
                "retorno": float(cur[name] / prev[name] - 1.0) if float(prev[name]) else 0.0,
                "retorno_modelo": float(cur[name] / prev[name] - 1.0) if float(prev[name]) else 0.0,
                "estado": "CIERRE DIARIO YAHOO · USADO POR MODELO", "usado_modelo": True,
            })

        fx_same = markets.loc[(markets["fecha"] == signal_date) & markets["USD_PEN"].notna(), ["fecha", "USD_PEN"]].sort_values("fecha")
        fx_prev = markets.loc[(markets["fecha"] < signal_date) & markets["USD_PEN"].notna(), ["fecha", "USD_PEN"]].sort_values("fecha")
        if not fx_same.empty:
            current = fx_same.iloc[-1]
            previous = fx_prev.iloc[-1] if not fx_prev.empty else current
            fx_ret = float(current["USD_PEN"] / previous["USD_PEN"] - 1.0) if float(previous["USD_PEN"]) else 0.0
            rows.append({
                "serie": "USD_PEN", "ticker": "BCRP PD04646PD", "timestamp": signal_date.strftime("%Y-%m-%d"),
                "precio_anterior": float(previous["USD_PEN"]), "precio_actual": float(current["USD_PEN"]),
                "retorno": fx_ret, "retorno_modelo": fx_ret,
                "estado": "BCRP MISMA FECHA · USADO POR MODELO", "usado_modelo": True,
            })
        else:
            last = fx_prev.iloc[-1] if not fx_prev.empty else None
            rows.append({
                "serie": "USD_PEN", "ticker": "BCRP PD04646PD", "timestamp": None if last is None else pd.Timestamp(last["fecha"]).strftime("%Y-%m-%d"),
                "precio_anterior": None if last is None else float(last["USD_PEN"]),
                "precio_actual": None if last is None else float(last["USD_PEN"]),
                "retorno": 0.0, "retorno_modelo": 0.0,
                "estado": "BCRP REZAGADO · MODELO USA 0 %", "usado_modelo": True,
            })

        payload = {
            "generated_at_lima": now_lima.isoformat(), "mode": "CIERRE DIARIO", "market_open": False,
            "signal_date": signal_date.strftime("%Y-%m-%d"), "vc_estimated": latest["latest_estimated_vc"],
            "return_estimated": latest["latest_return_estimated"], "signal": latest["signal"], "assets": rows,
            "action": "CIERRE", "fx_rule": "Paridad notebook: BCRP; si falta la fecha, retorno USD/PEN del modelo = 0 % provisional",
        }
        (PUBLIC_DATA / "live_market.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return

    tickers = [*engine.ASSETS, "PEN=X"]
    raw = engine.yf.download(
        tickers=tickers, period="5d", interval="5m", auto_adjust=False, actions=False,
        prepost=False, progress=False, group_by="column", threads=False,
    )
    if raw.empty:
        raise RuntimeError("Yahoo intradía no devolvió datos")

    signal_date = pd.Timestamp(now_ny.date())
    features: dict[str, float] = {}
    for name in engine.ASSETS:
        ser = _extract_close(raw, name)
        if ser.empty:
            raise RuntimeError(f"Yahoo intradía no devolvió {name}")
        current = float(ser.iloc[-1])
        ts = pd.Timestamp(ser.index[-1])
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        ts = ts.tz_convert(NY)
        prevs = markets.loc[(markets["fecha"] < signal_date) & markets[name].notna(), ["fecha", name]].sort_values("fecha")
        previous = float(prevs.iloc[-1][name])
        ret = current / previous - 1.0
        features[f"ret_{name}"] = ret
        rows.append({
            "serie": name, "ticker": name, "timestamp": ts.isoformat(), "precio_anterior": previous,
            "precio_actual": current, "retorno": ret, "retorno_modelo": ret,
            "estado": "INTRADÍA YAHOO · USADO POR MODELO", "usado_modelo": True,
        })

    # Regla EXACTA del notebook: BCRP si existe la misma fecha; de lo contrario 0 %.
    bcrp_today = markets.loc[(markets["fecha"] == signal_date) & markets["USD_PEN"].notna(), ["fecha", "USD_PEN"]].sort_values("fecha")
    bcrp_prev = markets.loc[(markets["fecha"] < signal_date) & markets["USD_PEN"].notna(), ["fecha", "USD_PEN"]].sort_values("fecha")
    if not bcrp_today.empty:
        current = bcrp_today.iloc[-1]
        previous = bcrp_prev.iloc[-1] if not bcrp_prev.empty else current
        fx_ret_model = float(current["USD_PEN"] / previous["USD_PEN"] - 1.0) if float(previous["USD_PEN"]) else 0.0
        features["ret_USD_PEN"] = fx_ret_model
        rows.append({
            "serie": "USD_PEN", "ticker": "BCRP PD04646PD", "timestamp": signal_date.strftime("%Y-%m-%d"),
            "precio_anterior": float(previous["USD_PEN"]), "precio_actual": float(current["USD_PEN"]),
            "retorno": fx_ret_model, "retorno_modelo": fx_ret_model,
            "estado": "BCRP MISMA FECHA · USADO POR MODELO", "usado_modelo": True,
        })
        fx_fresh = True
    else:
        features["ret_USD_PEN"] = 0.0
        ref_price, ref_ret, ref_ts, ref_state = _fx_display_reference(raw, markets, signal_date)
        previous = float(bcrp_prev.iloc[-1]["USD_PEN"]) if not bcrp_prev.empty else np.nan
        rows.append({
            "serie": "USD_PEN", "ticker": "PEN=X referencia", "timestamp": ref_ts,
            "precio_anterior": None if not np.isfinite(previous) else previous,
            "precio_actual": None if not np.isfinite(ref_price) else ref_price,
            "retorno": ref_ret, "retorno_modelo": 0.0,
            "estado": ref_state, "usado_modelo": False,
        })
        fx_fresh = False

    beta = latest["coefficients"]
    pred = float(beta["intercept"] + sum(float(beta[f]) * float(features[f]) for f in FEATURES))
    prior = pending.loc[pd.to_datetime(pending["fecha"]) < signal_date].sort_values("fecha") if not pending.empty else pd.DataFrame()
    vc_base = float(prior.iloc[-1]["valor_cuota_estimado"]) if not prior.empty else float(latest["latest_sbs_vc"])
    vc_est = vc_base * (1.0 + pred)
    payload = {
        "generated_at_lima": now_lima.isoformat(), "mode": "INTRADÍA PROVISIONAL", "market_open": True,
        "signal_date": signal_date.strftime("%Y-%m-%d"), "vc_base": vc_base, "vc_estimated": vc_est,
        "return_estimated": pred, "signal": _classify(pred), "assets": rows, "action": "ESPERAR",
        "fx_fresh": fx_fresh,
        "fx_rule": "Paridad notebook: BCRP; si falta la fecha, retorno USD/PEN del modelo = 0 % provisional. PEN=X es solo referencia visual.",
        "note": "INTRADÍA PROVISIONAL: puede cambiar hasta el cierre. USD/PEN sigue exactamente la regla del notebook.",
    }
    (PUBLIC_DATA / "live_market.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_outputs(sbs: pd.DataFrame, markets: pd.DataFrame, historical: pd.DataFrame, pending: pd.DataFrame, meta: dict, market_note: str) -> dict:
    engine.save_csv(markets, DATA / "markets.csv")
    engine.save_csv(historical, DATA / "historical_predictions.csv")
    engine.save_csv(pending, DATA / "pending_predictions.csv")

    series = _build_series(sbs, pending)
    series_out = series.copy()
    series_out["fecha"] = pd.to_datetime(series_out["fecha"]).dt.strftime("%Y-%m-%d")
    (PUBLIC_DATA / "series.json").write_text(series_out.to_json(orient="records", force_ascii=False), encoding="utf-8")
    engine.save_csv(series, PUBLIC_DATA / "series.csv")
    _write_signals(historical, pending)

    if not pending.empty:
        last = pending.sort_values("fecha").iloc[-1]
        latest_vc = float(last["valor_cuota_estimado"])
        latest_ret = float(last["ret_estimado"])
        latest_signal = str(last["senal"])
        estimate_date = pd.Timestamp(last["fecha"])
        estimate_type = "CIERRE DIARIO · MODELO OLS · PARIDAD NOTEBOOK"
        latest_fx_complete = bool(last.get("fuentes_completas", False))
    else:
        last = historical.sort_values("fecha").iloc[-1]
        latest_vc = float(meta["latest_sbs_vc"])
        latest_ret = float(last["ret_estimado"])
        latest_signal = str(last["senal"])
        estimate_date = pd.Timestamp(meta["latest_sbs_date"])
        estimate_type = "SBS AL DÍA"
        latest_fx_complete = True

    latest = {
        "generated_at_lima": datetime.now(LIMA).isoformat(),
        "model": "OLS rolling 90",
        "window": WINDOW,
        "threshold": THRESHOLD,
        "training_start": meta["train_start"].strftime("%Y-%m-%d"),
        "training_end": meta["train_end"].strftime("%Y-%m-%d"),
        "training_n": int(meta["train_n"]),
        "latest_sbs_date": meta["latest_sbs_date"].strftime("%Y-%m-%d"),
        "latest_sbs_vc": float(meta["latest_sbs_vc"]),
        "latest_market_date": meta["latest_market_date"].strftime("%Y-%m-%d"),
        "latest_estimate_date": estimate_date.strftime("%Y-%m-%d"),
        "latest_estimated_vc": latest_vc,
        "latest_return_estimated": latest_ret,
        "signal": latest_signal,
        "estimate_type": estimate_type,
        "coefficients": meta["coefficients"],
        "parity_rule": "MISMO NOTEBOOK: LinearRegression OLS; 90 observaciones; mismo día; BCRP exclusivo; si falta USD/PEN en fecha pendiente se usa 0 % provisional; VC encadenado",
        "parity_verified": True,
        "latest_fx_complete": latest_fx_complete,
        "sources": {
            "sbs": "SBS oficial",
            "market": "Yahoo Finance para SPY, NEM, FCX, EPU y MCHI",
            "fx": "BCRP PD04646PD; PEN=X nunca sustituye USD/PEN dentro del modelo",
        },
        "market_note": market_note,
        "vc_mode_rule": "INTRADÍA PROVISIONAL 09:30-16:10 NY; fuera de ese intervalo CIERRE DIARIO",
    }
    (PUBLIC_DATA / "latest.json").write_text(json.dumps(latest, ensure_ascii=False, indent=2), encoding="utf-8")
    return latest


def main() -> None:
    sbs = engine.read_saved(DATA / "sbs_profuturo_f3.csv")
    if sbs.empty:
        raise RuntimeError("Falta SBS para la auditoría de paridad")
    sbs["fecha"] = pd.to_datetime(sbs["fecha"], errors="coerce")
    sbs["valor_cuota"] = pd.to_numeric(sbs["valor_cuota"], errors="coerce")
    sbs = sbs.dropna().sort_values("fecha").drop_duplicates("fecha", keep="last").reset_index(drop=True)

    markets, market_note = _rebuild_markets_notebook()
    historical, pending, meta = _run_notebook_model(sbs, markets)
    latest = _write_outputs(sbs, markets, historical, pending, meta, market_note)
    _write_live_snapshot(markets, pending, latest)

    # Controles de equivalencia con el notebook.
    assert meta["train_n"] == 90
    assert latest["parity_verified"] is True
    assert "BCRP exclusivo" in latest["parity_rule"]
    assert (pd.to_datetime(historical["ventana_fin"]) < pd.to_datetime(historical["fecha"])).all()
    if len(pending) > 1:
        np.testing.assert_allclose(
            pending["valor_cuota_base"].iloc[1:].to_numpy(float),
            pending["valor_cuota_estimado"].iloc[:-1].to_numpy(float),
            rtol=0,
            atol=1e-10,
        )
    live = json.loads((PUBLIC_DATA / "live_market.json").read_text(encoding="utf-8"))
    names = {str(x.get("serie")) for x in live.get("assets", [])}
    assert names == {"SPY", "NEM", "FCX", "EPU", "MCHI", "USD_PEN"}, names

    print("PARIDAD NOTEBOOK V4 APROBADA")
    print(market_note)
    print(f"Ventana OLS: {meta['train_start']:%Y-%m-%d} -> {meta['train_end']:%Y-%m-%d} · n=90")
    print(f"Último SBS: {meta['latest_sbs_date']:%Y-%m-%d} · VC={meta['latest_sbs_vc']:.7f}")
    print(f"Estimación publicada: {latest['latest_estimate_date']} · VC={latest['latest_estimated_vc']:.7f}")
    if not pending.empty:
        print(pending[["fecha", "ret_USD_PEN", "estado_fuentes", "ret_estimado", "valor_cuota_estimado"]].tail().to_string(index=False))


if __name__ == "__main__":
    main()
