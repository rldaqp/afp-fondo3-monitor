from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "rolling90"
ANALYSIS = ROOT / "data" / "analysis"
PUBLIC = ROOT / "public" / "data"
LIVE_PATH = PUBLIC / "live_market.json"
ALT_CLOSES = ANALYSIS / "googlefinance_alt_aligned_closes_20260402_20260820.csv"
SBS_PATH = DATA / "sbs_profuturo_f3.csv"
OUT_PATH = PUBLIC / "alt_6030_experimental.json"
LEDGER_PATH = DATA / "alt_6030_shadow.csv"

ANCHOR_DATE = pd.Timestamp("2026-08-18")
CYCLE_START = pd.Timestamp("2026-08-19")
TRAIN_WINDOW = 60
FREEZE_HORIZON = 30
THRESHOLD = 0.001
LIMA = ZoneInfo("America/Lima")
FEATURES = ["ret_.INX", "ret_CPER", "ret_EEM_alt", "ret_NDX", "ret_SPBLSCUP", "ret_USD_PEN_alt"]
DISPLAY_FEATURES = [".INX", "CPER", "EEM", "NDX", "SPBLSCUP", "USD/PEN"]
MARKET_COLS = [".INX", "CPER", "EEM", "NDX", "SPBLSCUP"]
BCRP_URL = "https://estadisticas.bcrp.gob.pe/estadisticas/series/api/PD04638PD/json"
TUCAMBISTA_URL = "https://tucambista.pe/"

# Dato oficial verificado en la página SBS. Se mantiene como override temporal
# mientras Incapsula impida que el robot local/Actions lea esa fecha.
SBS_OVERRIDES = {
    pd.Timestamp("2026-08-19"): 70.3276160,
}

MESES = {
    "ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
    "jul": 7, "ago": 8, "set": 9, "sep": 9, "oct": 10, "nov": 11, "dic": 12,
}


def classify(value: float) -> str:
    if value > THRESHOLD:
        return "SUBE"
    if value < -THRESHOLD:
        return "BAJA"
    return "NEUTRO"


def parse_bcrp_date(text: str) -> pd.Timestamp:
    s = str(text).lower().strip()
    m = re.search(r"(\d{1,2})[.\-/ ]+([a-záéíóú]+)[.\-/ ]+(\d{2,4})", s)
    if not m:
        return pd.NaT
    day = int(m.group(1))
    mon = m.group(2)[:3]
    for a, b in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u")):
        mon = mon.replace(a, b)
    year = int(m.group(3))
    if year < 100:
        year += 2000
    month = MESES.get(mon)
    return pd.Timestamp(year, month, day) if month else pd.NaT


def load_bcrp() -> pd.DataFrame:
    r = requests.get(BCRP_URL, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    rows = []
    for period in r.json().get("periods", []):
        date = parse_bcrp_date(period.get("name"))
        value = pd.to_numeric(pd.Series([(period.get("values") or [None])[0]]), errors="coerce").iloc[0]
        if pd.notna(date) and pd.notna(value):
            rows.append({"fecha_bcrp": pd.Timestamp(date).normalize(), "USD_PEN_BCRP": float(value)})
    if not rows:
        raise RuntimeError("BCRP PD04638PD no devolvió observaciones")
    return (
        pd.DataFrame(rows)
        .sort_values("fecha_bcrp")
        .drop_duplicates("fecha_bcrp", keep="last")
        .reset_index(drop=True)
    )


def load_sbs() -> pd.DataFrame:
    sbs = pd.read_csv(SBS_PATH)
    sbs["fecha"] = pd.to_datetime(sbs["fecha"], errors="coerce").dt.normalize()
    sbs["valor_cuota"] = pd.to_numeric(sbs["valor_cuota"], errors="coerce")
    sbs = sbs.dropna(subset=["fecha", "valor_cuota"])[["fecha", "valor_cuota"]]
    extra = pd.DataFrame([{"fecha": d, "valor_cuota": v} for d, v in SBS_OVERRIDES.items()])
    sbs = pd.concat([sbs, extra], ignore_index=True)
    sbs = sbs.sort_values("fecha").drop_duplicates("fecha", keep="last").reset_index(drop=True)
    sbs["ret_target"] = sbs["valor_cuota"].pct_change(fill_method=None)
    return sbs


def load_market(bcrp: pd.DataFrame) -> pd.DataFrame:
    alt = pd.read_csv(ALT_CLOSES)
    alt["fecha"] = pd.to_datetime(alt["fecha"], errors="coerce").dt.normalize()
    for col in MARKET_COLS:
        alt[col] = pd.to_numeric(alt[col], errors="coerce")
    alt = alt.dropna(subset=["fecha", *MARKET_COLS]).sort_values("fecha").drop_duplicates("fecha", keep="last")
    alt = pd.merge_asof(
        alt.sort_values("fecha"),
        bcrp.sort_values("fecha_bcrp"),
        left_on="fecha",
        right_on="fecha_bcrp",
        direction="backward",
    )
    alt["USD_PEN"] = alt["USD_PEN_BCRP"]
    for col in [*MARKET_COLS, "USD_PEN"]:
        alt[f"ret_{col}"] = alt[col].pct_change(fill_method=None)
    return alt.rename(columns={"ret_EEM": "ret_EEM_alt", "ret_USD_PEN": "ret_USD_PEN_alt"}).reset_index(drop=True)


def fit(frame: pd.DataFrame) -> tuple[np.ndarray, dict[str, float]]:
    x = frame[FEATURES].to_numpy(float)
    y = frame["ret_target"].to_numpy(float)
    beta = np.linalg.lstsq(np.c_[np.ones(len(x)), x], y, rcond=None)[0]
    return beta, {k: float(v) for k, v in zip(["intercept", *FEATURES], beta)}


def predict(beta: np.ndarray, values: dict[str, float]) -> float:
    return float(beta[0] + sum(float(beta[i + 1]) * float(values[f]) for i, f in enumerate(FEATURES)))


def row_values(row: pd.Series) -> dict[str, float]:
    out = {}
    for f in FEATURES:
        v = pd.to_numeric(pd.Series([row.get(f)]), errors="coerce").iloc[0]
        if pd.isna(v):
            raise RuntimeError(f"Falta {f} en fecha histórica")
        out[f] = float(v)
    return out


def tucambista_midpoint() -> tuple[float, str]:
    r = requests.get(TUCAMBISTA_URL, timeout=25, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    text = re.sub(r"\s+", " ", r.text)
    buy = re.search(r"Compra\s*:?[\s<>&;/a-zA-Z=\"'_-]*?(\d+\.\d+)", text, flags=re.IGNORECASE)
    sell = re.search(r"Venta\s*:?[\s<>&;/a-zA-Z=\"'_-]*?(\d+\.\d+)", text, flags=re.IGNORECASE)
    if not buy or not sell:
        # El texto visible suele ser más fácil de encontrar sin etiquetas HTML.
        clean = re.sub(r"<[^>]+>", " ", r.text)
        clean = re.sub(r"\s+", " ", clean)
        buy = re.search(r"Compra\s*:?[\s]*(\d+\.\d+)", clean, flags=re.IGNORECASE)
        sell = re.search(r"Venta\s*:?[\s]*(\d+\.\d+)", clean, flags=re.IGNORECASE)
    if not buy or not sell:
        raise RuntimeError("TuCambista no devolvió compra/venta")
    compra, venta = float(buy.group(1)), float(sell.group(1))
    return (compra + venta) / 2.0, f"TUCAMBISTA PROVISIONAL ({compra:.3f}/{venta:.3f})"


def fx_for_signal(signal_date: pd.Timestamp, market_open: bool, bcrp: pd.DataFrame, market: pd.DataFrame, live: dict) -> tuple[float, float, str, bool]:
    same = bcrp.loc[bcrp["fecha_bcrp"].eq(signal_date)]
    if (not market_open) and not same.empty:
        current = float(same.iloc[-1]["USD_PEN_BCRP"])
        source = "BCRP OFICIAL · CIERRE"
        provisional = False
    else:
        try:
            current, source = tucambista_midpoint()
            provisional = True
        except Exception:
            row = next((x for x in live.get("experimental_assets", []) if x.get("serie") == "USD/PEN"), {})
            raw = pd.to_numeric(pd.Series([row.get("precio_actual")]), errors="coerce").iloc[0]
            if pd.isna(raw):
                raise
            current = float(raw)
            source = "FALLBACK LIVE USD/PEN · PROVISIONAL"
            provisional = True

    prev_rows = market.loc[market["fecha"] < signal_date].sort_values("fecha")
    if prev_rows.empty:
        raise RuntimeError("No existe USD/PEN previo para el retorno operativo")
    previous = float(prev_rows.iloc[-1]["USD_PEN"])
    return current, current / previous - 1.0, source, provisional


def live_values(live: dict, market: pd.DataFrame, bcrp: pd.DataFrame, signal_date: pd.Timestamp) -> tuple[dict[str, float], dict[str, str], dict[str, str], dict]:
    assets = {str(x.get("serie", "")): x for x in live.get("experimental_assets", [])}
    mapping = {
        "ret_.INX": ".INX",
        "ret_CPER": "CPER",
        "ret_EEM_alt": "EEM",
        "ret_NDX": "NDX",
        "ret_SPBLSCUP": "SPBLSCUP",
    }
    values, sources, stamps = {}, {}, {}
    for feature, serie in mapping.items():
        row = assets.get(serie, {})
        raw = pd.to_numeric(pd.Series([row.get("retorno")]), errors="coerce").iloc[0]
        if pd.isna(raw):
            raise RuntimeError(f"Falta retorno operativo para {serie}; no se usa 0% artificial")
        values[feature] = float(raw)
        sources[feature] = str(row.get("estado", ""))
        stamps[feature] = str(row.get("timestamp", ""))

    fx_value, fx_ret, fx_source, fx_provisional = fx_for_signal(
        signal_date, bool(live.get("market_open")), bcrp, market, live
    )
    values["ret_USD_PEN_alt"] = fx_ret
    sources["ret_USD_PEN_alt"] = fx_source
    stamps["ret_USD_PEN_alt"] = signal_date.date().isoformat()
    fx_meta = {"value": fx_value, "return": fx_ret, "source": fx_source, "provisional": fx_provisional}
    return values, sources, stamps, fx_meta


def reanchored_backtest(both: pd.DataFrame, n: int = 20) -> dict:
    test = both.loc[both["fecha"] <= ANCHOR_DATE].tail(n).copy().reset_index(drop=True)
    if test.empty:
        return {"n": 0, "rows": []}
    train = both.loc[both["fecha"] < test.iloc[0]["fecha"]].tail(TRAIN_WINDOW).copy().reset_index(drop=True)
    if len(train) != TRAIN_WINDOW:
        return {"n": 0, "rows": [], "error": "Entrenamiento histórico insuficiente"}
    beta, _ = fit(train)
    rows, errors = [], []
    for _, row in test.iterrows():
        d = pd.Timestamp(row["fecha"])
        prev = both.loc[both["fecha"] < d].sort_values("fecha")
        if prev.empty:
            continue
        base_row = prev.iloc[-1]
        base_vc = float(base_row["valor_cuota"])
        ret = predict(beta, row_values(row))
        est = base_vc * (1.0 + ret)
        actual = float(row["valor_cuota"])
        err = est - actual
        errors.append(err)
        rows.append({
            "fecha": d.date().isoformat(),
            "source": "BACKTEST REANCLADO",
            "base_date": pd.Timestamp(base_row["fecha"]).date().isoformat(),
            "base_vc": base_vc,
            "vc": est,
            "return": ret,
            "signal": classify(ret),
            "actual_vc": actual,
            "error_vc": err,
            "abs_error": abs(err),
            "error_pct": err / actual * 100.0,
        })
    arr = np.asarray(errors, dtype=float)
    return {
        "n": len(rows),
        "design": "Un paso desde el último VC SBS real anterior; beta congelado en el bloque de validación.",
        "mae_vc": float(np.mean(np.abs(arr))) if len(arr) else None,
        "rmse_vc": float(np.sqrt(np.mean(arr ** 2))) if len(arr) else None,
        "mape_pct": float(np.mean(np.abs(arr / np.asarray([r["actual_vc"] for r in rows], dtype=float))) * 100.0) if len(arr) else None,
        "rows": rows,
    }


def main() -> None:
    live = json.loads(LIVE_PATH.read_text(encoding="utf-8"))
    signal_date = pd.Timestamp(str(live.get("signal_date"))).normalize()
    bcrp = load_bcrp()
    market = load_market(bcrp)
    sbs = load_sbs()

    both = sbs[["fecha", "valor_cuota", "ret_target"]].merge(
        market[["fecha", *FEATURES]], on="fecha", how="inner"
    )
    both = both.dropna(subset=["ret_target", "valor_cuota", *FEATURES]).sort_values("fecha").drop_duplicates("fecha", keep="last").reset_index(drop=True)

    train = both.loc[both["fecha"] <= ANCHOR_DATE].tail(TRAIN_WINDOW).copy().reset_index(drop=True)
    if len(train) != TRAIN_WINDOW or pd.Timestamp(train.iloc[-1]["fecha"]).normalize() != ANCHOR_DATE:
        raise RuntimeError("Entrenamiento OLS 60/30 incompleto al 18/08")
    beta, coeff = fit(train)

    latest_sbs_rows = sbs.loc[sbs["fecha"] < signal_date].sort_values("fecha")
    if latest_sbs_rows.empty:
        raise RuntimeError("No existe SBS real anterior para reanclar")
    latest_sbs = latest_sbs_rows.iloc[-1]
    latest_sbs_date = pd.Timestamp(latest_sbs["fecha"]).normalize()
    latest_sbs_vc = float(latest_sbs["valor_cuota"])

    market_by_date = {pd.Timestamp(r["fecha"]).normalize(): r for _, r in market.iterrows()}
    generated = datetime.now(LIMA).isoformat()
    rows = []

    # Conserva el estimado del 19 para poder compararlo con el SBS real, aunque el
    # reanclaje operativo vigente ya parta desde ese SBS oficial.
    start = CYCLE_START
    vc_state = None
    fx_meta_current = None
    for d in pd.bdate_range(start, signal_date):
        d = pd.Timestamp(d).normalize()
        actual_same = sbs.loc[sbs["fecha"].eq(d), "valor_cuota"]
        prev_actual = sbs.loc[sbs["fecha"] < d].sort_values("fecha")
        if prev_actual.empty:
            continue

        if d <= latest_sbs_date:
            base_row = prev_actual.iloc[-1]
            base_vc = float(base_row["valor_cuota"])
            base_date = pd.Timestamp(base_row["fecha"]).normalize()
        else:
            if vc_state is None:
                base_vc = latest_sbs_vc
                base_date = latest_sbs_date
            else:
                base_vc = float(vc_state)
                base_date = pd.Timestamp(rows[-1]["fecha"]).normalize()

        if d == signal_date and d > market["fecha"].max():
            values, sources, stamps, fx_meta = live_values(live, market, bcrp, signal_date)
            fx_meta_current = fx_meta
            source = "INTRADÍA REANCLADA" if bool(live.get("market_open")) else "CIERRE REANCLADO"
        else:
            hist = market_by_date.get(d)
            if hist is None:
                raise RuntimeError(f"Falta mercado histórico para {d.date()}")
            values = row_values(hist)
            sources = {f: "CIERRE HISTÓRICO · BCRP FX" for f in FEATURES}
            stamps = {f: d.date().isoformat() for f in FEATURES}
            source = "CIERRE HISTÓRICO REANCLADO"

        ret = predict(beta, values)
        est = base_vc * (1.0 + ret)
        actual = float(actual_same.iloc[-1]) if not actual_same.empty else None
        rows.append({
            "fecha": d.date().isoformat(),
            "base_date": base_date.date().isoformat(),
            "base_vc": base_vc,
            "return": ret,
            "signal": classify(ret),
            "vc": est,
            "actual_vc": actual,
            "abs_error": None if actual is None else abs(est - actual),
            "error_pct": None if actual is None else (est - actual) / actual * 100.0,
            "source": source,
            "factor_returns": values,
            "factor_sources": sources,
            "factor_timestamps": stamps,
            "updated_at_lima": generated,
        })
        vc_state = actual if actual is not None else est

    current = next((r for r in reversed(rows) if r["fecha"] == signal_date.date().isoformat()), None)
    if current is None:
        raise RuntimeError("No se calculó la fecha objetivo del nuevo 60/30")

    ledger = pd.DataFrame(rows)
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    ledger.to_csv(LEDGER_PATH, index=False)

    backtest = reanchored_backtest(both, 20)
    output = {
        "generated_at_lima": generated,
        "signal_date": signal_date.date().isoformat(),
        "mode": live.get("mode"),
        "market_open": bool(live.get("market_open")),
        "market_snapshot_generated_at_lima": live.get("generated_at_lima"),
        "role": "EXPERIMENTAL · REANCLADO; no reemplaza OLS oficial ni challenger vigente.",
        "model": {
            "name": "OLS 60/30 · nuevos tickers · reanclado SBS",
            "features_display": DISPLAY_FEATURES,
            "features": FEATURES,
            "return_estimated": float(current["return"]),
            "signal": current["signal"],
            "vc_estimated": float(current["vc"]),
            "blind_chain": False,
            "reanchored_with_latest_sbs": True,
            "sbs_anchor_date": latest_sbs_date.date().isoformat(),
            "sbs_anchor_vc": latest_sbs_vc,
        },
        "cycle": {
            "cycle_start": CYCLE_START.date().isoformat(),
            "cycle_day": len([r for r in rows if r["fecha"] >= CYCLE_START.date().isoformat()]),
            "anchor_date": ANCHOR_DATE.date().isoformat(),
            "anchor_vc": float(train.iloc[-1]["valor_cuota"]),
            "train_start": pd.Timestamp(train.iloc[0]["fecha"]).date().isoformat(),
            "train_end": pd.Timestamp(train.iloc[-1]["fecha"]).date().isoformat(),
            "train_n": TRAIN_WINDOW,
            "freeze_horizon": FREEZE_HORIZON,
            "coefficients": coeff,
            "fx_training_source": "BCRP PD04638PD · TC Interbancario Venta",
        },
        "fx_operational": fx_meta_current,
        "backtest_exact20": backtest,
        "operational_history": rows,
        "history_min_date": backtest.get("rows", [{}])[0].get("fecha") if backtest.get("rows") else CYCLE_START.date().isoformat(),
        "history_max_date": signal_date.date().isoformat(),
        "rules": {
            "beta": "60 observaciones válidas hasta 18/08; congelado 30 sesiones.",
            "vc": "Reanclar con el último VC SBS real disponible; encadenar solo los días aún no publicados por SBS.",
            "fx": "Histórico BCRP PD04638PD. Intradía TuCambista. Al cierre BCRP de la misma fecha si existe; si no, TuCambista provisional.",
            "spblscup": "No se permite retorno 0 artificial; requiere cotización de la sesión.",
        },
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "signal_date": output["signal_date"],
        "vc": output["model"]["vc_estimated"],
        "return": output["model"]["return_estimated"],
        "sbs_anchor_date": output["model"]["sbs_anchor_date"],
        "fx": output.get("fx_operational"),
        "coefficients": output["cycle"]["coefficients"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
