from __future__ import annotations

import html
import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public" / "data"
DATA = ROOT / "data" / "rolling90"
LIVE_PATH = PUBLIC / "live_market.json"
LATEST_PATH = PUBLIC / "latest.json"
PENDING_PATH = DATA / "pending_predictions.csv"
LIMA = ZoneInfo("America/Lima")

MONTHS_ES = {
    1: "enero", 2: "febrero", 3: "marzo", 4: "abril",
    5: "mayo", 6: "junio", 7: "julio", 8: "agosto",
    9: "septiembre", 10: "octubre", 11: "noviembre", 12: "diciembre",
}

# Respaldo de fechas ya verificadas externamente. Sirve si el sitio bloquea
# temporalmente al runner. No se usa Yahoo para USD/PEN.
TUCAMBISTA_VERIFIED = {
    "2026-08-28": {"buy": 3.339, "sell": 3.368},
}

YAHOO_FINAL = {
    ".INX": "^GSPC",
    "CPER": "CPER",
    "EEM": "EEM",
    "NDX": "^NDX",
}


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


def _tucambista_url(day: pd.Timestamp) -> str:
    return f"https://tucambista.pe/tipo-de-cambio-{day.day}-de-{MONTHS_ES[day.month]}"


def _parse_tucambista(text: str) -> tuple[float, float]:
    plain = html.unescape(text)
    plain = re.sub(r"<script\b[^>]*>.*?</script>", " ", plain, flags=re.I | re.S)
    plain = re.sub(r"<style\b[^>]*>.*?</style>", " ", plain, flags=re.I | re.S)
    plain = re.sub(r"<[^>]+>", " ", plain)
    plain = re.sub(r"\s+", " ", plain)

    def pick(label: str) -> float | None:
        patterns = [
            rf"{label}\s*(?:S/?\.?\s*)?[:\-]?\s*([23]\.[0-9]{{3,4}})",
            rf"{label}.{{0,100}}?([23]\.[0-9]{{3,4}})",
        ]
        for pattern in patterns:
            m = re.search(pattern, plain, flags=re.I)
            if m:
                value = float(m.group(1))
                if 2.0 < value < 6.0:
                    return value
        return None

    buy = pick("Compra")
    sell = pick("Venta")
    if buy is None or sell is None:
        raise RuntimeError("No se pudieron leer Compra/Venta de TuCambista")
    if buy > sell + 0.10:
        raise RuntimeError(f"TuCambista inconsistente: compra={buy}, venta={sell}")
    return buy, sell


def tucambista_quote(day: pd.Timestamp) -> dict:
    key = day.strftime("%Y-%m-%d")
    url = _tucambista_url(day)
    try:
        r = requests.get(
            url,
            timeout=15,
            headers={
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131 Safari/537.36",
                "Accept-Language": "es-PE,es;q=0.9,en;q=0.7",
            },
        )
        r.raise_for_status()
        buy, sell = _parse_tucambista(r.text)
        source = "TUCAMBISTA WEB"
    except Exception as exc:
        verified = TUCAMBISTA_VERIFIED.get(key)
        if not verified:
            raise RuntimeError(f"TuCambista no disponible para {key}: {type(exc).__name__}: {exc}") from exc
        buy = float(verified["buy"])
        sell = float(verified["sell"])
        source = "TUCAMBISTA VERIFICADO"
    return {
        "buy": float(buy),
        "sell": float(sell),
        "midpoint": (float(buy) + float(sell)) / 2.0,
        "source": source,
        "url": url,
    }


def yahoo_daily_close(ticker: str, day: pd.Timestamp) -> tuple[float, float, float]:
    start = (day - pd.Timedelta(days=8)).strftime("%Y-%m-%d")
    end = (day + pd.Timedelta(days=3)).strftime("%Y-%m-%d")
    raw = yf.download(
        ticker,
        start=start,
        end=end,
        interval="1d",
        auto_adjust=False,
        actions=False,
        progress=False,
        threads=False,
    )
    close = _extract_close(raw, ticker)
    if close.empty:
        raise RuntimeError(f"Yahoo no devolvio cierre diario de {ticker}")
    idx = pd.to_datetime(close.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    frame = pd.DataFrame({"fecha": idx.normalize(), "close": close.to_numpy(float)})
    frame = frame.sort_values("fecha").drop_duplicates("fecha", keep="last")
    same = frame.loc[frame["fecha"].eq(day)]
    prior = frame.loc[frame["fecha"].lt(day)]
    if same.empty or prior.empty:
        raise RuntimeError(f"No existe cierre exacto {day.date()} o cierre previo para {ticker}")
    current = float(same.iloc[-1]["close"])
    previous = float(prior.iloc[-1]["close"])
    ret = current / previous - 1.0 if previous else 0.0
    return previous, current, ret


def _fx_asset(live: dict) -> dict | None:
    for asset in live.get("assets", []):
        if asset.get("serie") == "USD_PEN":
            return asset
    return None


def apply_tucambista(live: dict, signal_date: pd.Timestamp) -> None:
    fx = _fx_asset(live)
    if fx is None:
        raise RuntimeError("No existe fila USD_PEN en live_market.json")

    # Si BCRP ya publico exactamente la fecha de la señal, se conserva como
    # fuente oficial. TuCambista reemplaza exclusivamente el antiguo fallback Yahoo/0%.
    if "BCRP MISMA FECHA" in str(fx.get("estado", "")) and str(fx.get("timestamp", ""))[:10] == signal_date.strftime("%Y-%m-%d"):
        live["fx_source"] = "BCRP"
        live["fx_provisional"] = False
        live["fx_rule"] = "BCRP para la fecha cuando existe; si BCRP aun no publica, TuCambista midpoint del mismo dia. Yahoo no se usa para USD/PEN."
        return

    quote = tucambista_quote(signal_date)
    current = float(quote["midpoint"])
    previous_candidates = [fx.get("precio_actual"), fx.get("precio_anterior")]
    previous = None
    for raw in previous_candidates:
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if np.isfinite(value) and value > 0:
            previous = value
            break
    if previous is None:
        raise RuntimeError("No existe USD/PEN previo valido para calcular retorno TuCambista")

    ret = current / previous - 1.0
    fx.update({
        "ticker": "TUCAMBISTA",
        "timestamp": signal_date.strftime("%Y-%m-%d"),
        "precio_anterior": previous,
        "precio_actual": current,
        "retorno": ret,
        "retorno_modelo": ret,
        "estado": "TUCAMBISTA MIDPOINT · MISMO DIA · USADO POR MODELO",
        "usado_modelo": True,
    })
    live["fx_source"] = "TUCAMBISTA MIDPOINT"
    live["fx_provisional"] = True
    live["fx_buy"] = quote["buy"]
    live["fx_sell"] = quote["sell"]
    live["fx_midpoint"] = quote["midpoint"]
    live["fx_url"] = quote["url"]
    live["fx_rule"] = "BCRP para la fecha cuando existe; si BCRP aun no publica, TuCambista midpoint (Compra+Venta)/2 del mismo dia. Yahoo no se usa para USD/PEN."


def recalc_ols(live: dict, latest: dict, pending: pd.DataFrame, signal_date: pd.Timestamp) -> None:
    beta = latest.get("coefficients") or {}
    if not beta:
        raise RuntimeError("latest.json no contiene coeficientes OLS")

    features: dict[str, float] = {}
    for asset in live.get("assets", []):
        serie = str(asset.get("serie", ""))
        feature = f"ret_{serie}"
        if feature not in beta:
            continue
        raw = asset.get("retorno_modelo")
        if raw is None:
            raw = asset.get("retorno")
        value = pd.to_numeric(pd.Series([raw]), errors="coerce").iloc[0]
        if pd.notna(value):
            features[feature] = float(value)

    required = [k for k in beta if k.startswith("ret_")]
    missing = [k for k in required if k not in features]
    if missing:
        raise RuntimeError(f"Faltan factores para recalcular OLS: {missing}")

    pred = float(beta.get("intercept", 0.0))
    pred += sum(float(beta[k]) * features[k] for k in required)

    vc_base = None
    if not pending.empty:
        p = pending.copy()
        p["fecha"] = pd.to_datetime(p["fecha"], errors="coerce").dt.normalize()
        prior = p.loc[p["fecha"].lt(signal_date)].sort_values("fecha")
        if not prior.empty:
            raw = pd.to_numeric(pd.Series([prior.iloc[-1].get("valor_cuota_estimado")]), errors="coerce").iloc[0]
            if pd.notna(raw):
                vc_base = float(raw)
    if vc_base is None:
        vc_base = float(latest["latest_sbs_vc"])

    threshold = float(latest.get("threshold", 0.001))
    live["vc_base"] = vc_base
    live["return_estimated"] = pred
    live["vc_estimated"] = vc_base * (1.0 + pred)
    live["signal"] = "SUBE" if pred > threshold else ("BAJA" if pred < -threshold else "NEUTRO")
    live["model_snapshot_source"] = "CIERRE RECALCULADO · FACTORES DEFINITIVOS + TUCAMBISTA"
    live["model_snapshot_date"] = signal_date.strftime("%Y-%m-%d")
    live.pop("warning", None)


def finalize_experimental(live: dict, signal_date: pd.Timestamp) -> None:
    if bool(live.get("market_open")):
        return
    old = {str(x.get("serie")): dict(x) for x in live.get("experimental_assets", []) if x.get("serie")}
    rows: list[dict] = []
    problems: list[str] = []

    for symbol in [".INX", "CPER", "EEM", "NDX"]:
        ticker = YAHOO_FINAL[symbol]
        try:
            previous, current, ret = yahoo_daily_close(ticker, signal_date)
            rows.append({
                "serie": symbol,
                "ticker": ticker,
                "timestamp": signal_date.strftime("%Y-%m-%d"),
                "precio_anterior": previous,
                "precio_actual": current,
                "retorno": ret,
                "retorno_modelo": None,
                "estado": "CIERRE DIARIO DEFINITIVO YAHOO · VALIDADO POST-CIERRE",
                "usado_modelo": False,
                "validado_modelo": True,
                "error_validacion": None,
            })
        except Exception as exc:
            prior = old.get(symbol, {"serie": symbol, "ticker": ticker})
            prior["validado_modelo"] = False
            prior["estado"] = f"CIERRE DIARIO NO DISPONIBLE · {type(exc).__name__}"
            prior["error_validacion"] = str(exc)
            rows.append(prior)
            problems.append(symbol)

    sp = old.get("SPBLSCUP")
    if sp and str(sp.get("timestamp", ""))[:10] == signal_date.strftime("%Y-%m-%d") and sp.get("precio_actual") is not None:
        sp["validado_modelo"] = True
        sp["error_validacion"] = None
        rows.append(sp)
    elif sp:
        rows.append(sp)
        problems.append("SPBLSCUP")
    else:
        problems.append("SPBLSCUP")

    fx = _fx_asset(live)
    if fx is not None:
        rows.append({
            "serie": "USD/PEN",
            "ticker": fx.get("ticker", "TUCAMBISTA"),
            "timestamp": fx.get("timestamp"),
            "precio_anterior": fx.get("precio_anterior"),
            "precio_actual": fx.get("precio_actual"),
            "retorno": fx.get("retorno"),
            "retorno_modelo": None,
            "estado": f"{fx.get('estado', '')} · NUEVO 60/30 EXPERIMENTAL",
            "usado_modelo": False,
            "validado_modelo": True,
            "error_validacion": None,
        })

    live["experimental_assets"] = rows
    live["new_ticker_validation"] = {
        "signal_date": signal_date.strftime("%Y-%m-%d"),
        "status": "COMPLETO/VALIDADO" if not problems else "INCOMPLETO",
        "problems": problems,
        "rule": "Fuera del horario de mercado se exige cierre diario exacto de la fecha; no se conservan capturas 15:55 como cierre.",
    }


def main() -> None:
    live = json.loads(LIVE_PATH.read_text(encoding="utf-8"))
    latest = json.loads(LATEST_PATH.read_text(encoding="utf-8"))
    pending = pd.read_csv(PENDING_PATH) if PENDING_PATH.exists() and PENDING_PATH.stat().st_size else pd.DataFrame()
    signal_date = pd.Timestamp(str(live.get("signal_date", ""))[:10]).normalize()

    apply_tucambista(live, signal_date)
    recalc_ols(live, latest, pending, signal_date)
    finalize_experimental(live, signal_date)
    live["finalized_at_lima"] = datetime.now(LIMA).isoformat()
    live["finalizer_version"] = "tucambista-final-close-v1"

    LIVE_PATH.write_text(json.dumps(live, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "signal_date": live.get("signal_date"),
        "fx_source": live.get("fx_source"),
        "fx_midpoint": live.get("fx_midpoint"),
        "vc_estimated": live.get("vc_estimated"),
        "return_estimated": live.get("return_estimated"),
        "signal": live.get("signal"),
        "new_ticker_validation": live.get("new_ticker_validation"),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
