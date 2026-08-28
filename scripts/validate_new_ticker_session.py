from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
LIVE = ROOT / "public" / "data" / "live_market.json"
ALT_LIVE = ROOT / "data" / "analysis" / "googlefinance_alt_rolling30_live_returns.csv"
ALT_BASE = ROOT / "data" / "analysis" / "googlefinance_alt_6030_returns_20260303_20260820.csv"
MARKETS = ROOT / "data" / "rolling90" / "markets.csv"
WANTED = [".INX", "CPER", "EEM", "NDX", "SPBLSCUP"]
BCRP_URL = "https://estadisticas.bcrp.gob.pe/estadisticas/series/api/PD04638PD/json"
MESES = {
    "ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
    "jul": 7, "ago": 8, "set": 9, "sep": 9, "oct": 10, "nov": 11, "dic": 12,
}


def finite(v) -> bool:
    try:
        return v is not None and np.isfinite(float(v))
    except Exception:
        return False


def parse_bcrp_date(text: str) -> pd.Timestamp:
    s = str(text).lower().strip()
    m = re.search(r"(\d{1,2})[.\-/ ]+([a-záéíóú]+)[.\-/ ]+(\d{2,4})", s)
    if not m:
        return pd.NaT
    mon = m.group(2)[:3]
    for a, b in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u")):
        mon = mon.replace(a, b)
    month = MESES.get(mon)
    if not month:
        return pd.NaT
    year = int(m.group(3))
    if year < 100:
        year += 2000
    return pd.Timestamp(year, month, int(m.group(1))).normalize()


def load_bcrp_history() -> pd.DataFrame:
    """Obtiene el TC interbancario venta oficial y su retorno entre observaciones válidas."""
    r = requests.get(BCRP_URL, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    rows = []
    for p in r.json().get("periods", []):
        fecha = parse_bcrp_date(p.get("name"))
        raw = (p.get("values") or [None])[0]
        value = pd.to_numeric(pd.Series([raw]), errors="coerce").iloc[0]
        if pd.notna(fecha) and pd.notna(value):
            rows.append({"fecha": fecha, "USD_PEN_BCRP": float(value)})
    if not rows:
        raise RuntimeError("BCRP PD04638PD no devolvió observaciones válidas")
    fx = pd.DataFrame(rows).sort_values("fecha").drop_duplicates("fecha", keep="last")
    fx["ret_BCRP"] = fx["USD_PEN_BCRP"].pct_change(fill_method=None)
    return fx


def normalize_historical_fx() -> dict:
    """Corrige el FX histórico usado por ambos Rolling 30 con BCRP PD04638PD.

    No se hardcodea el 24/08. Se reemplaza cada fecha para la que BCRP tiene dato
    oficial. Así el 24/08 y la ventana de entrenamiento quedan coherentes con la
    misma fuente oficial que usa el chequeo exacto.
    """
    fx = load_bcrp_history()
    ret_map = fx.set_index("fecha")["ret_BCRP"]
    val_map = fx.set_index("fecha")["USD_PEN_BCRP"]
    report = {"source": "BCRP PD04638PD · TC INTERBANCARIO VENTA · OFICIAL"}

    markets = pd.read_csv(MARKETS)
    md = pd.to_datetime(markets["fecha"], errors="coerce").dt.normalize()
    official_ret = md.map(ret_map)
    official_val = md.map(val_map)
    mask = official_ret.notna()
    before_24 = None
    after_24 = None
    focus = md.eq(pd.Timestamp("2026-08-24"))
    if focus.any() and "ret_USD_PEN" in markets.columns:
        before_24 = pd.to_numeric(markets.loc[focus, "ret_USD_PEN"], errors="coerce").iloc[-1]
    markets.loc[mask, "ret_USD_PEN"] = official_ret.loc[mask].astype(float)
    if "USD_PEN" in markets.columns:
        markets.loc[official_val.notna(), "USD_PEN"] = official_val.loc[official_val.notna()].astype(float)
    if focus.any():
        after_24 = pd.to_numeric(markets.loc[focus, "ret_USD_PEN"], errors="coerce").iloc[-1]
    markets.to_csv(MARKETS, index=False)
    report["markets_rows_overridden"] = int(mask.sum())

    if ALT_BASE.exists():
        base = pd.read_csv(ALT_BASE)
        bd = pd.to_datetime(base["fecha"], errors="coerce").dt.normalize()
        bret = bd.map(ret_map)
        bmask = bret.notna()
        if "ret_USD_PEN" in base.columns:
            base.loc[bmask, "ret_USD_PEN"] = bret.loc[bmask].astype(float)
            base.to_csv(ALT_BASE, index=False)
        report["new_tickers_base_rows_overridden"] = int(bmask.sum())
    else:
        report["new_tickers_base_rows_overridden"] = 0

    fx24 = fx.loc[fx["fecha"].eq(pd.Timestamp("2026-08-24"))]
    report["focus_2026_08_24"] = {
        "stored_return_before": None if before_24 is None or not finite(before_24) else float(before_24),
        "official_return_after": None if after_24 is None or not finite(after_24) else float(after_24),
        "official_value": None if fx24.empty else float(fx24.iloc[-1]["USD_PEN_BCRP"]),
        "corrected": bool(
            before_24 is not None
            and after_24 is not None
            and finite(before_24)
            and finite(after_24)
            and abs(float(before_24) - float(after_24)) > 1e-12
        ),
    }
    return report


def main() -> None:
    live = json.loads(LIVE.read_text(encoding="utf-8"))
    signal_date = str(live.get("signal_date", ""))[:10]
    assets = {str(x.get("serie")): x for x in live.get("experimental_assets", [])}
    core = {str(x.get("serie")): x for x in live.get("assets", [])}

    problems: list[str] = []
    for name in WANTED:
        row = assets.get(name)
        if row is None:
            problems.append(f"{name}: ausente")
            continue
        if row.get("validado_modelo") is False:
            problems.append(f"{name}: marcado no validado")
            continue
        ret = row.get("retorno_modelo") if row.get("retorno_modelo") is not None else row.get("retorno")
        if not finite(ret):
            problems.append(f"{name}: retorno no finito")

    # Control cruzado específico para el índice Perú. EPU no reemplaza a
    # SPBLSCUP: solo sirve como alarma de integridad. Una discrepancia >5 puntos
    # porcentuales en una sola sesión obliga a dejar Modelo B pendiente antes que
    # alimentar un número posiblemente extraído de otra tarjeta de Google.
    sp = assets.get("SPBLSCUP")
    epu = core.get("EPU")
    if sp and epu:
        sp_ret = sp.get("retorno_modelo") if sp.get("retorno_modelo") is not None else sp.get("retorno")
        epu_ret = epu.get("retorno_modelo") if epu.get("retorno_modelo") is not None else epu.get("retorno")
        if finite(sp_ret) and finite(epu_ret) and abs(float(sp_ret) - float(epu_ret)) > 0.05:
            sp["validado_modelo"] = False
            sp["usado_modelo"] = False
            sp["retorno_modelo"] = None
            sp["retorno"] = None
            sp["estado"] = (
                f"CIERRE BLOQUEADO · SPBLSCUP difiere {abs(float(sp_ret)-float(epu_ret))*100:.2f} pp de EPU; "
                "requiere fuente exacta corroborada"
            )
            problems.append("SPBLSCUP: divergencia >5 pp frente a EPU")

    # Si hay cualquier problema, borra del incremental la fila de HOY para que
    # el constructor no reutilice un cierre ya persistido pero luego invalidado.
    if problems and ALT_LIVE.exists() and signal_date:
        df = pd.read_csv(ALT_LIVE)
        if "fecha" in df.columns:
            dates = pd.to_datetime(df["fecha"], errors="coerce").dt.strftime("%Y-%m-%d")
            before = len(df)
            df = df.loc[dates.ne(signal_date)].copy()
            if len(df) != before:
                df.to_csv(ALT_LIVE, index=False)
                print(f"Fila incremental {signal_date} retirada por validación: {problems}")

    # La normalización BCRP se ejecuta antes de construir ambos Rolling 30.
    # Si BCRP no responde, se bloquea el rebuild en lugar de entrenar con FX
    # histórico inconsistente.
    fx_report = normalize_historical_fx()

    live["new_ticker_validation"] = {
        "signal_date": signal_date,
        "status": "OK" if not problems else "PENDIENTE/BLOQUEADO",
        "problems": problems,
        "rule": "No se usa un cierre dudoso para Modelo B; se conserva la última sesión completa.",
    }
    live["historical_fx_validation"] = fx_report
    LIVE.write_text(json.dumps(live, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "new_ticker_validation": live["new_ticker_validation"],
        "historical_fx_validation": fx_report,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
