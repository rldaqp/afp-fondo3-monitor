from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "rolling90"
PUBLIC = ROOT / "public" / "data"
LATEST_PATH = PUBLIC / "latest.json"
LIVE_PATH = PUBLIC / "live_market.json"
OUT_PATH = PUBLIC / "reduced_6030_challenger.json"
STATE_PATH = DATA / "reduced_6030_state.json"
LEDGER_PATH = DATA / "reduced_6030_shadow.csv"

TRAIN_WINDOW = 60
FREEZE_HORIZON = 30
THRESHOLD = 0.001
INITIAL_CYCLE_START = pd.Timestamp("2026-08-19")
INITIAL_ANCHOR_DATE = pd.Timestamp("2026-08-18")
LIMA = ZoneInfo("America/Lima")

REDUCED_FEATURES = [
    "ret_SPY",
    "ret_EEM",
    "ret_EPU",
    "ret_MCHI",
    "ret_USD_PEN",
    "ret_QQQ",
]
OFFICIAL_FEATURES = [
    "ret_SPY",
    "ret_EEM",
    "ret_EPU",
    "ret_MCHI",
    "ret_NEM",
    "ret_FCX",
    "ret_USD_PEN",
]
COMMON_FEATURES = sorted(set(REDUCED_FEATURES + OFFICIAL_FEATURES))


def classify(value: float) -> str:
    if value > THRESHOLD:
        return "SUBE"
    if value < -THRESHOLD:
        return "BAJA"
    return "NEUTRO"


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    frame = pd.read_csv(path)
    if "fecha" in frame.columns:
        frame["fecha"] = pd.to_datetime(frame["fecha"], errors="coerce")
    return frame


def safe_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception:
        return {}


def extract_close(raw: pd.DataFrame, ticker: str) -> pd.Series:
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


def download_qqq(start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    raw = yf.download(
        "QQQ",
        start=(start - pd.Timedelta(days=10)).strftime("%Y-%m-%d"),
        end=(end + pd.Timedelta(days=3)).strftime("%Y-%m-%d"),
        auto_adjust=False,
        actions=False,
        progress=False,
        threads=False,
    )
    close = extract_close(raw, "QQQ")
    if close.empty:
        raise RuntimeError("Yahoo no devolvio cierres de QQQ")
    idx = pd.to_datetime(close.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    out = pd.DataFrame({"fecha": idx.normalize(), "QQQ": close.to_numpy(float)})
    out = out.sort_values("fecha").drop_duplicates("fecha", keep="last")
    out["ret_QQQ"] = out["QQQ"].pct_change(fill_method=None)
    return out


def qqq_current_return(qqq: pd.DataFrame, signal_date: pd.Timestamp, market_open: bool) -> tuple[float, str]:
    q = qqq.sort_values("fecha")
    previous_rows = q.loc[q["fecha"] < signal_date]
    if previous_rows.empty:
        raise RuntimeError("No existe cierre previo de QQQ")
    previous = float(previous_rows.iloc[-1]["QQQ"])
    same = q.loc[q["fecha"] == signal_date]
    if not market_open and not same.empty:
        current = float(same.iloc[-1]["QQQ"])
        return current / previous - 1.0, "CIERRE DIARIO YAHOO"

    raw = yf.download(
        "QQQ",
        period="5d",
        interval="5m",
        auto_adjust=False,
        actions=False,
        prepost=False,
        progress=False,
        threads=False,
    )
    close = extract_close(raw, "QQQ")
    if not close.empty:
        current = float(close.iloc[-1])
        return current / previous - 1.0, "INTRADIA YAHOO" if market_open else "ULTIMO CORTE YAHOO"
    if not same.empty:
        current = float(same.iloc[-1]["QQQ"])
        return current / previous - 1.0, "CIERRE DIARIO YAHOO"
    raise RuntimeError("No se pudo obtener QQQ actual")


def fit_ols(train: pd.DataFrame, features: list[str]) -> tuple[np.ndarray, dict[str, float]]:
    x = train[features].to_numpy(float)
    y = train["ret_target"].to_numpy(float)
    beta = np.linalg.lstsq(np.c_[np.ones(len(x)), x], y, rcond=None)[0]
    names = ["intercept", *features]
    return beta, {name: float(value) for name, value in zip(names, beta)}


def predict_from_coeff(coeff: dict[str, float], values: dict[str, float], features: list[str]) -> float:
    return float(coeff["intercept"] + sum(float(coeff[f]) * float(values[f]) for f in features))


def prepare_frames(markets: pd.DataFrame, sbs_raw: pd.DataFrame, qqq: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    markets = markets.copy()
    sbs = sbs_raw.copy()
    markets["fecha"] = pd.to_datetime(markets["fecha"], errors="coerce")
    for f in sorted(set(OFFICIAL_FEATURES + [x for x in REDUCED_FEATURES if x != "ret_QQQ"])):
        if f not in markets.columns:
            raise RuntimeError(f"Falta {f} en markets.csv")
        markets[f] = pd.to_numeric(markets[f], errors="coerce")

    sbs["fecha"] = pd.to_datetime(sbs["fecha"], errors="coerce")
    sbs["valor_cuota"] = pd.to_numeric(sbs["valor_cuota"], errors="coerce")
    sbs = sbs.dropna(subset=["fecha", "valor_cuota"]).sort_values("fecha").drop_duplicates("fecha", keep="last")
    sbs["ret_target"] = sbs["valor_cuota"].pct_change(fill_method=None)

    mq = markets.merge(qqq[["fecha", "ret_QQQ"]], on="fecha", how="left")
    common = sbs[["fecha", "valor_cuota", "ret_target"]].merge(
        mq[["fecha", *COMMON_FEATURES]], on="fecha", how="inner"
    )
    common = common.loc[common["fecha"] >= pd.Timestamp("2025-01-01")]
    common = common.dropna(subset=["ret_target", "valor_cuota", *COMMON_FEATURES]).sort_values("fecha").drop_duplicates("fecha", keep="last").reset_index(drop=True)
    if len(common) < 100:
        raise RuntimeError(f"Muestra comun insuficiente: {len(common)}")
    return common, sbs, mq


def initial_state(common: pd.DataFrame, sbs: pd.DataFrame) -> dict:
    anchor_rows = sbs.loc[sbs["fecha"] <= INITIAL_ANCHOR_DATE]
    if anchor_rows.empty:
        raise RuntimeError("No existe VC SBS para anclar el ciclo 60/30")
    anchor = anchor_rows.iloc[-1]
    anchor_date = pd.Timestamp(anchor["fecha"]).normalize()
    train = common.loc[common["fecha"] <= anchor_date].tail(TRAIN_WINDOW).copy()
    if len(train) != TRAIN_WINDOW:
        raise RuntimeError(f"Entrenamiento inicial 60/30 incompleto: {len(train)}")
    _, coeff = fit_ols(train, REDUCED_FEATURES)
    state = {
        "version": 1,
        "model": "OLS 60/30 sin NEM ni FCX + QQQ",
        "cycle_start": INITIAL_CYCLE_START.date().isoformat(),
        "anchor_date": anchor_date.date().isoformat(),
        "anchor_vc": float(anchor["valor_cuota"]),
        "train_start": train.iloc[0]["fecha"].date().isoformat(),
        "train_end": train.iloc[-1]["fecha"].date().isoformat(),
        "train_n": TRAIN_WINDOW,
        "freeze_horizon": FREEZE_HORIZON,
        "features": REDUCED_FEATURES,
        "coefficients": coeff,
        "created_at_lima": datetime.now(LIMA).isoformat(),
    }
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return state


def ledger_read() -> pd.DataFrame:
    ledger = read_csv(LEDGER_PATH)
    if ledger.empty:
        return pd.DataFrame()
    ledger["fecha"] = pd.to_datetime(ledger["fecha"], errors="coerce")
    return ledger.dropna(subset=["fecha"]).sort_values("fecha").drop_duplicates("fecha", keep="last").reset_index(drop=True)


def maybe_roll_state(state: dict, ledger: pd.DataFrame, common: pd.DataFrame, sbs: pd.DataFrame, signal_date: pd.Timestamp) -> dict:
    if ledger.empty:
        return state
    cycle_start = pd.Timestamp(state["cycle_start"])
    cycle_rows = ledger.loc[ledger["fecha"] >= cycle_start].sort_values("fecha")
    if len(cycle_rows) < FREEZE_HORIZON:
        return state
    day30 = pd.Timestamp(cycle_rows.iloc[FREEZE_HORIZON - 1]["fecha"]).normalize()
    if signal_date <= day30:
        return state

    # Solo recalibra cuando SBS ya publico el VC del cierre del bloque. Hasta
    # entonces se mantiene el mismo modelo: nunca se usa un VC futuro para
    # corregir retrospectivamente la cadena.
    anchors = sbs.loc[(sbs["fecha"] >= day30) & (sbs["fecha"] < signal_date)].sort_values("fecha")
    if anchors.empty:
        return state
    anchor = anchors.iloc[-1]
    anchor_date = pd.Timestamp(anchor["fecha"]).normalize()
    train = common.loc[common["fecha"] <= anchor_date].tail(TRAIN_WINDOW).copy()
    if len(train) != TRAIN_WINDOW:
        return state
    _, coeff = fit_ols(train, REDUCED_FEATURES)
    new_state = {
        "version": int(state.get("version", 1)) + 1,
        "model": "OLS 60/30 sin NEM ni FCX + QQQ",
        "cycle_start": signal_date.date().isoformat(),
        "anchor_date": anchor_date.date().isoformat(),
        "anchor_vc": float(anchor["valor_cuota"]),
        "train_start": train.iloc[0]["fecha"].date().isoformat(),
        "train_end": train.iloc[-1]["fecha"].date().isoformat(),
        "train_n": TRAIN_WINDOW,
        "freeze_horizon": FREEZE_HORIZON,
        "features": REDUCED_FEATURES,
        "coefficients": coeff,
        "created_at_lima": datetime.now(LIMA).isoformat(),
        "previous_cycle_day30": day30.date().isoformat(),
    }
    STATE_PATH.write_text(json.dumps(new_state, ensure_ascii=False, indent=2), encoding="utf-8")
    return new_state


def values_for_date(date_value: pd.Timestamp, mq: pd.DataFrame, qqq: pd.DataFrame) -> dict[str, float] | None:
    same = mq.loc[mq["fecha"].eq(date_value)]
    if same.empty:
        return None
    row = same.iloc[-1]
    values: dict[str, float] = {}
    for f in REDUCED_FEATURES:
        value = pd.to_numeric(pd.Series([row.get(f)]), errors="coerce").iloc[0]
        if pd.isna(value):
            return None
        values[f] = float(value)
    return values


def live_values(live: dict, mq: pd.DataFrame, qqq: pd.DataFrame, signal_date: pd.Timestamp) -> tuple[dict[str, float], str]:
    mapping: dict[str, float] = {}
    for asset in live.get("assets", []):
        serie = str(asset.get("serie", ""))
        key = f"ret_{serie}"
        if key not in REDUCED_FEATURES:
            continue
        raw = asset.get("retorno_modelo")
        if raw is None:
            raw = asset.get("retorno")
        value = pd.to_numeric(pd.Series([raw]), errors="coerce").iloc[0]
        if pd.notna(value):
            mapping[key] = float(value)

    for f in [x for x in REDUCED_FEATURES if x != "ret_QQQ"]:
        if f not in mapping:
            same = mq.loc[mq["fecha"].eq(signal_date)]
            if same.empty:
                raise RuntimeError(f"Falta {f} para {signal_date.date()}")
            value = pd.to_numeric(pd.Series([same.iloc[-1].get(f)]), errors="coerce").iloc[0]
            if pd.isna(value):
                raise RuntimeError(f"Falta {f} para {signal_date.date()}")
            mapping[f] = float(value)

    qret, qsource = qqq_current_return(qqq, signal_date, bool(live.get("market_open")))
    mapping["ret_QQQ"] = qret
    return mapping, qsource


def official_for_date(date_value: pd.Timestamp, live: dict, pending: pd.DataFrame) -> tuple[float | None, float | None, str | None]:
    if str(live.get("signal_date", ""))[:10] == date_value.date().isoformat():
        try:
            return float(live["return_estimated"]), float(live["vc_estimated"]), str(live.get("signal"))
        except Exception:
            pass
    if not pending.empty:
        p = pending.copy()
        p["fecha"] = pd.to_datetime(p["fecha"], errors="coerce")
        same = p.loc[p["fecha"].eq(date_value)]
        if not same.empty:
            row = same.iloc[-1]
            rr = pd.to_numeric(pd.Series([row.get("ret_estimado")]), errors="coerce").iloc[0]
            vv = pd.to_numeric(pd.Series([row.get("valor_cuota_estimado")]), errors="coerce").iloc[0]
            return (None if pd.isna(rr) else float(rr), None if pd.isna(vv) else float(vv), str(row.get("senal", "")) or None)
    return None, None, None


def build_chain(state: dict, ledger: pd.DataFrame, mq: pd.DataFrame, qqq: pd.DataFrame, live: dict, pending: pd.DataFrame, signal_date: pd.Timestamp) -> tuple[pd.DataFrame, dict]:
    coeff = {k: float(v) for k, v in state["coefficients"].items()}
    cycle_start = pd.Timestamp(state["cycle_start"])
    vc = float(state["anchor_vc"])
    generated = datetime.now(LIMA).isoformat()
    prior = ledger.loc[ledger["fecha"] >= cycle_start].sort_values("fecha") if not ledger.empty else pd.DataFrame()
    rows: list[dict] = []

    # Fechas completas anteriores al corte actual. Si ya existen en el ledger,
    # se conserva la prediccion que realmente se genero: no se reescribe el pasado.
    dates = list(
        mq.loc[(mq["fecha"] >= cycle_start) & (mq["fecha"] < signal_date), "fecha"]
        .dropna().drop_duplicates().sort_values()
    )
    if signal_date >= cycle_start:
        dates.append(signal_date)

    existing = {} if prior.empty else {pd.Timestamp(r["fecha"]): r for _, r in prior.iterrows()}
    last_current: dict | None = None
    for d in dates:
        d = pd.Timestamp(d).normalize()
        old = existing.get(d)
        if old is not None and d < signal_date and pd.notna(old.get("challenger_vc")) and pd.notna(old.get("challenger_return")):
            vc = float(old["challenger_vc"])
            rows.append(dict(old))
            continue

        if d == signal_date:
            values, qsource = live_values(live, mq, qqq, signal_date)
        else:
            values = values_for_date(d, mq, qqq)
            qsource = "CIERRE DIARIO YAHOO"
            if values is None:
                continue
        pred = predict_from_coeff(coeff, values, REDUCED_FEATURES)
        base_vc = vc
        vc = base_vc * (1.0 + pred)
        off_ret, off_vc, off_signal = official_for_date(d, live, pending)
        row = {
            "fecha": d,
            "cycle_start": state["cycle_start"],
            "train_start": state["train_start"],
            "train_end": state["train_end"],
            "base_vc": base_vc,
            "challenger_return": pred,
            "challenger_signal": classify(pred),
            "challenger_vc": vc,
            "official_return": off_ret,
            "official_signal": off_signal,
            "official_vc": off_vc,
            "qqq_return": values["ret_QQQ"],
            "qqq_source": qsource,
            "actual_vc": np.nan,
            "challenger_abs_vc_error": np.nan,
            "official_abs_vc_error": np.nan,
            "status": "PENDIENTE SBS",
            "updated_at_lima": generated,
        }
        rows.append(row)
        last_current = row

    if last_current is None:
        same = [r for r in rows if pd.Timestamp(r["fecha"]).normalize() == signal_date]
        if same:
            last_current = same[-1]
    if last_current is None:
        raise RuntimeError("No se pudo construir el VC challenger del corte actual")

    out = pd.DataFrame(rows)
    if not ledger.empty:
        before = ledger.loc[ledger["fecha"] < cycle_start]
        out = pd.concat([before, out], ignore_index=True)
    out = out.sort_values("fecha").drop_duplicates("fecha", keep="last").reset_index(drop=True)
    return out, last_current


def evaluate_ledger(ledger: pd.DataFrame, sbs: pd.DataFrame) -> pd.DataFrame:
    if ledger.empty:
        return ledger
    actual = sbs.set_index("fecha")["valor_cuota"].to_dict()
    for idx, row in ledger.iterrows():
        d = pd.Timestamp(row["fecha"]).normalize()
        av = actual.get(d)
        if av is None or pd.isna(av):
            continue
        av = float(av)
        ledger.at[idx, "actual_vc"] = av
        cv = pd.to_numeric(pd.Series([row.get("challenger_vc")]), errors="coerce").iloc[0]
        ov = pd.to_numeric(pd.Series([row.get("official_vc")]), errors="coerce").iloc[0]
        if pd.notna(cv):
            ledger.at[idx, "challenger_abs_vc_error"] = abs(float(cv) - av)
        if pd.notna(ov):
            ledger.at[idx, "official_abs_vc_error"] = abs(float(ov) - av)
        ledger.at[idx, "status"] = "EVALUADO"
    return ledger


def blind_backtest(common: pd.DataFrame) -> dict:
    start0 = 90  # mismo burn-in usado en la comparacion historica de candidatos
    rows: list[dict] = []
    endpoints: list[dict] = []
    for block_start in range(start0, len(common) - FREEZE_HORIZON + 1, FREEZE_HORIZON):
        block_end = block_start + FREEZE_HORIZON
        train = common.iloc[block_start - TRAIN_WINDOW:block_start]
        red_beta, _ = fit_ols(train, REDUCED_FEATURES)
        off_beta, _ = fit_ols(train, OFFICIAL_FEATURES)
        red_vc = float(common.iloc[block_start - 1]["valor_cuota"])
        off_vc = red_vc
        block_red = []
        block_off = []
        for i in range(block_start, block_end):
            r = common.iloc[i]
            red_ret = float(np.r_[1.0, r[REDUCED_FEATURES].to_numpy(float)] @ red_beta)
            off_ret = float(np.r_[1.0, r[OFFICIAL_FEATURES].to_numpy(float)] @ off_beta)
            red_vc *= 1.0 + red_ret
            off_vc *= 1.0 + off_ret
            actual_vc = float(r["valor_cuota"])
            rows.append({"actual_vc": actual_vc, "reduced_vc": red_vc, "official_vc": off_vc})
            block_red.append(abs(red_vc - actual_vc))
            block_off.append(abs(off_vc - actual_vc))
        endpoints.append({
            "reduced": abs(red_vc - float(common.iloc[block_end - 1]["valor_cuota"])),
            "official": abs(off_vc - float(common.iloc[block_end - 1]["valor_cuota"])),
            "reduced_mae": float(np.mean(block_red)),
            "official_mae": float(np.mean(block_off)),
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return {"n_blocks": 0}
    red_err = df["reduced_vc"] - df["actual_vc"]
    off_err = df["official_vc"] - df["actual_vc"]
    red_mae = float(red_err.abs().mean())
    off_mae = float(off_err.abs().mean())
    return {
        "design": "Bloques no superpuestos: entrenar 60 observaciones, congelar 30, un solo VC SBS como ancla al inicio; dentro del bloque SBS solo evalua y nunca corrige.",
        "n_blocks": int(len(endpoints)),
        "n_predictions": int(len(df)),
        "official_current_7f": {
            "vc_mae": off_mae,
            "vc_rmse": float(np.sqrt(np.mean(off_err.to_numpy(float) ** 2))),
            "mean_endpoint_abs_error": float(np.mean([x["official"] for x in endpoints])),
        },
        "challenger_6030": {
            "vc_mae": red_mae,
            "vc_rmse": float(np.sqrt(np.mean(red_err.to_numpy(float) ** 2))),
            "mean_endpoint_abs_error": float(np.mean([x["reduced"] for x in endpoints])),
        },
        "mae_improvement_pct": None if off_mae <= 0 else float((off_mae - red_mae) / off_mae * 100.0),
        "challenger_better_blocks": int(sum(x["reduced_mae"] < x["official_mae"] for x in endpoints)),
        "official_better_blocks": int(sum(x["official_mae"] < x["reduced_mae"] for x in endpoints)),
    }


def forward_summary(ledger: pd.DataFrame) -> dict:
    if ledger.empty:
        return {"evaluated": 0, "pending": 0}
    evaluated = ledger.loc[ledger["status"].astype(str).eq("EVALUADO")].copy()
    out = {"evaluated": int(len(evaluated)), "pending": int(len(ledger) - len(evaluated))}
    if not evaluated.empty:
        ce = pd.to_numeric(evaluated["challenger_abs_vc_error"], errors="coerce").dropna()
        oe = pd.to_numeric(evaluated["official_abs_vc_error"], errors="coerce").dropna()
        out["challenger_vc_mae"] = None if ce.empty else float(ce.mean())
        out["official_vc_mae"] = None if oe.empty else float(oe.mean())
    return out


def main() -> None:
    latest = safe_json(LATEST_PATH)
    live = safe_json(LIVE_PATH)
    markets = read_csv(DATA / "markets.csv")
    sbs_raw = read_csv(DATA / "sbs_profuturo_f3.csv")
    pending = read_csv(DATA / "pending_predictions.csv")
    if not latest or not live or markets.empty or sbs_raw.empty:
        raise RuntimeError("Faltan archivos base para challenger 60/30")

    markets["fecha"] = pd.to_datetime(markets["fecha"], errors="coerce")
    signal_date = pd.Timestamp(str(live.get("signal_date") or latest.get("latest_estimate_date"))).normalize()
    start = min(markets["fecha"].dropna().min(), pd.Timestamp("2024-12-01"))
    qqq = download_qqq(start, max(signal_date, pd.Timestamp.now().normalize()))
    common, sbs, mq = prepare_frames(markets, sbs_raw, qqq)

    state = safe_json(STATE_PATH)
    if not state:
        state = initial_state(common, sbs)
    ledger = ledger_read()
    state = maybe_roll_state(state, ledger, common, sbs, signal_date)
    ledger, current = build_chain(state, ledger, mq, qqq, live, pending, signal_date)
    ledger = evaluate_ledger(ledger, sbs)
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    ledger.to_csv(LEDGER_PATH, index=False)

    official_ret = float(live.get("return_estimated"))
    official_vc = float(live.get("vc_estimated"))
    challenger_ret = float(current["challenger_return"])
    challenger_vc = float(current["challenger_vc"])
    cycle_rows = ledger.loc[ledger["fecha"] >= pd.Timestamp(state["cycle_start"])]
    cycle_day = int(len(cycle_rows))

    output = {
        "generated_at_lima": datetime.now(LIMA).isoformat(),
        "signal_date": signal_date.date().isoformat(),
        "mode": live.get("mode"),
        "market_open": bool(live.get("market_open")),
        "role": "UNICO CHALLENGER EN SOMBRA; no reemplaza el OLS rolling 90 oficial.",
        "official": {
            "model": "OLS rolling 90 oficial · SPY EEM EPU MCHI NEM FCX USD/PEN",
            "return_estimated": official_ret,
            "signal": str(live.get("signal")),
            "vc_estimated": official_vc,
        },
        "challenger": {
            "model": "OLS 60/30 · sin NEM ni FCX + QQQ",
            "return_estimated": challenger_ret,
            "signal": classify(challenger_ret),
            "vc_estimated": challenger_vc,
            "blind_chain": True,
            "reanchored_with_latest_sbs": False,
        },
        "comparison": {
            "same_signal": classify(challenger_ret) == str(live.get("signal")),
            "vc_difference": challenger_vc - official_vc,
            "return_difference_pp": (challenger_ret - official_ret) * 100.0,
        },
        "cycle": {
            "train_window": TRAIN_WINDOW,
            "freeze_horizon": FREEZE_HORIZON,
            "cycle_start": state["cycle_start"],
            "cycle_day": cycle_day,
            "anchor_date": state["anchor_date"],
            "anchor_vc": float(state["anchor_vc"]),
            "train_start": state["train_start"],
            "train_end": state["train_end"],
            "train_n": int(state["train_n"]),
            "features": REDUCED_FEATURES,
            "rule": "Coeficientes congelados 30 sesiones. El VC se encadena desde el ancla del ciclo y no se corrige con SBS dentro del bloque.",
        },
        "qqq": {
            "return": float(current["qqq_return"]),
            "source": str(current["qqq_source"]),
        },
        "blind_backtest": blind_backtest(common),
        "forward_sbs": forward_summary(ledger),
        "ledger": "data/rolling90/reduced_6030_shadow.csv",
    }

    PUBLIC.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    assert output["challenger"]["signal"] in {"SUBE", "NEUTRO", "BAJA"}
    assert float(output["challenger"]["vc_estimated"]) > 0
    assert int(output["cycle"]["train_n"]) == TRAIN_WINDOW
    assert int(output["cycle"]["freeze_horizon"]) == FREEZE_HORIZON
    assert "ret_NEM" not in output["cycle"]["features"]
    assert "ret_FCX" not in output["cycle"]["features"]
    assert "ret_QQQ" in output["cycle"]["features"]
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
