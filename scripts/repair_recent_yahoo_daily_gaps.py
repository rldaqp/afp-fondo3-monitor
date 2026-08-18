from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
MARKETS_PATH = ROOT / "data" / "rolling90" / "markets.csv"
ASSETS = ["SPY", "NEM", "FCX", "EPU", "MCHI", "EEM"]
CORE = ["SPY", "NEM", "FCX", "EPU", "MCHI"]
NY = "America/New_York"


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


def _recent_intraday_daily_closes(ticker: str) -> dict[pd.Timestamp, float]:
    """Obtiene cierres recientes desde barras Yahoo de 5 minutos.

    Es un respaldo de la descarga diaria. Sirve cuando Yahoo devuelve una fila
    diaria incompleta para un ticker aislado, como ocurrió con EEM el 17/08/2026.
    """
    raw = yf.download(
        tickers=ticker,
        period="10d",
        interval="5m",
        auto_adjust=False,
        actions=False,
        prepost=False,
        progress=False,
        threads=False,
    )
    ser = _extract_close(raw, ticker)
    if ser.empty:
        return {}

    idx = pd.to_datetime(ser.index)
    if getattr(idx, "tz", None) is None:
        idx = idx.tz_localize("UTC").tz_convert(NY)
    else:
        idx = idx.tz_convert(NY)

    frame = pd.DataFrame({"ts": idx, "close": ser.to_numpy(float)})
    frame = frame.dropna(subset=["close"]).sort_values("ts")
    frame["fecha"] = frame["ts"].dt.tz_localize(None).dt.normalize()

    # Última barra regular de cada sesión. prepost=False evita after-hours.
    daily = frame.groupby("fecha", as_index=False).tail(1)
    return {
        pd.Timestamp(row.fecha).normalize(): float(row.close)
        for row in daily.itertuples()
        if np.isfinite(row.close)
    }


def _recompute_returns(markets: pd.DataFrame) -> pd.DataFrame:
    out = markets.copy().sort_values("fecha").reset_index(drop=True)
    for variable in [*ASSETS, "USD_PEN"]:
        if variable not in out.columns:
            continue
        valid = out[["fecha", variable]].dropna().copy()
        valid[f"ret_{variable}"] = pd.to_numeric(
            valid[variable], errors="coerce"
        ).pct_change(fill_method=None)
        mapping = valid.set_index("fecha")[f"ret_{variable}"]
        out[f"ret_{variable}"] = out["fecha"].map(mapping)
    return out


def main() -> None:
    if not MARKETS_PATH.exists():
        raise RuntimeError(f"No existe {MARKETS_PATH}")

    markets = pd.read_csv(MARKETS_PATH)
    markets["fecha"] = pd.to_datetime(markets["fecha"], errors="coerce")
    markets = (
        markets.dropna(subset=["fecha"])
        .sort_values("fecha")
        .drop_duplicates("fecha", keep="last")
        .reset_index(drop=True)
    )

    for asset in ASSETS:
        if asset not in markets.columns:
            markets[asset] = np.nan
        markets[asset] = pd.to_numeric(markets[asset], errors="coerce")

    # Solo reparamos sesiones bursátiles reales: los cinco activos base deben
    # existir. No se rellenan fines de semana ni feriados.
    candidate_mask = markets[CORE].notna().all(axis=1)
    repaired: list[tuple[str, str, float]] = []

    for ticker in ASSETS:
        missing_mask = candidate_mask & markets[ticker].isna()
        missing_dates = set(markets.loc[missing_mask, "fecha"].dt.normalize())
        if not missing_dates:
            continue

        closes = _recent_intraday_daily_closes(ticker)
        for date_value in sorted(missing_dates):
            close = closes.get(pd.Timestamp(date_value).normalize())
            if close is None or not np.isfinite(close):
                continue
            idx = markets.index[markets["fecha"].dt.normalize().eq(date_value)]
            if len(idx) != 1:
                continue
            markets.at[idx[0], ticker] = float(close)
            repaired.append((ticker, pd.Timestamp(date_value).strftime("%Y-%m-%d"), float(close)))

    markets = _recompute_returns(markets)

    # Control específico: ninguna sesión reciente con los cinco activos base
    # puede quedar sin EEM. Si aún falta, el OLS no debe publicarse como completo.
    recent_core = markets.loc[candidate_mask].sort_values("fecha").tail(5)
    missing_eem = recent_core.loc[recent_core["EEM"].isna(), "fecha"]
    if not missing_eem.empty:
        dates = ", ".join(pd.Timestamp(x).strftime("%Y-%m-%d") for x in missing_eem)
        raise RuntimeError(f"Yahoo sigue sin cierre EEM para sesiones recientes: {dates}")

    out = markets.copy()
    out["fecha"] = pd.to_datetime(out["fecha"]).dt.strftime("%Y-%m-%d")
    out.to_csv(MARKETS_PATH, index=False, encoding="utf-8")

    if repaired:
        for ticker, date_text, close in repaired:
            print(f"REPARADO {ticker} {date_text}: {close:.8f}")
    else:
        print("No había huecos recientes que reparar.")

    latest_complete = pd.to_datetime(recent_core["fecha"]).max()
    print(f"Última sesión bursátil completa tras reparación: {latest_complete:%Y-%m-%d}")


if __name__ == "__main__":
    main()
