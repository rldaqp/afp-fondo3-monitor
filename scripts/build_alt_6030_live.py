from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "rolling90"
ANALYSIS = ROOT / "data" / "analysis"
PUBLIC = ROOT / "public" / "data"
LIVE_PATH = PUBLIC / "live_market.json"
ALT_CLOSES = ANALYSIS / "googlefinance_alt_aligned_closes_20260402_20260820.csv"
SBS_PATH = DATA / "sbs_profuturo_f3.csv"
MARKETS_PATH = DATA / "markets.csv"
CHALLENGER_STATE_PATH = DATA / "reduced_6030_state.json"
OUT_PATH = PUBLIC / "alt_6030_experimental.json"
LEDGER_PATH = DATA / "alt_6030_shadow.csv"

ANCHOR_DATE = pd.Timestamp("2026-08-18")
CYCLE_START = pd.Timestamp("2026-08-19")
TRAIN_WINDOW = 60
FREEZE_HORIZON = 30
THRESHOLD = 0.001
LIMA = ZoneInfo("America/Lima")
CLOSE_COLS = [".INX", "CPER", "EEM", "NDX", "SPBLSCUP", "USD_PEN"]
FEATURES = ["ret_.INX", "ret_CPER", "ret_EEM_alt", "ret_NDX", "ret_SPBLSCUP", "ret_USD_PEN_alt"]
DISPLAY_FEATURES = [".INX", "CPER", "EEM", "NDX", "SPBLSCUP", "USD/PEN"]
CALENDAR_FEATURES = ["ret_SPY", "ret_EEM", "ret_EPU", "ret_MCHI", "ret_USD_PEN"]
TEST_DATES = pd.to_datetime([
    "2026-07-22", "2026-07-23", "2026-07-24", "2026-07-27", "2026-07-28",
    "2026-07-29", "2026-07-30", "2026-07-31", "2026-08-03", "2026-08-04",
    "2026-08-05", "2026-08-06", "2026-08-07", "2026-08-10", "2026-08-11",
    "2026-08-12", "2026-08-13", "2026-08-14", "2026-08-17", "2026-08-18",
])


def classify(value: float) -> str:
    if value > THRESHOLD:
        return "SUBE"
    if value < -THRESHOLD:
        return "BAJA"
    return "NEUTRO"


def safe_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception:
        return {}


def build_alt_returns() -> pd.DataFrame:
    alt = pd.read_csv(ALT_CLOSES)
    alt["fecha"] = pd.to_datetime(alt["fecha"], errors="coerce")
    for col in CLOSE_COLS:
        alt[col] = pd.to_numeric(alt[col], errors="coerce")
    alt = alt.dropna(subset=["fecha", *CLOSE_COLS]).sort_values("fecha").drop_duplicates("fecha", keep="last")
    for col in CLOSE_COLS:
        alt[f"ret_{col}"] = alt[col].pct_change(fill_method=None)
    alt = alt.rename(columns={"ret_EEM": "ret_EEM_alt", "ret_USD_PEN": "ret_USD_PEN_alt"})
    return alt


def load_inputs() -> tuple[dict, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    live = safe_json(LIVE_PATH)
    if not live:
        raise RuntimeError("Falta live_market.json")

    alt = build_alt_returns()

    sbs = pd.read_csv(SBS_PATH)
    sbs["fecha"] = pd.to_datetime(sbs["fecha"], errors="coerce")
    sbs["valor_cuota"] = pd.to_numeric(sbs["valor_cuota"], errors="coerce")
    sbs = sbs.dropna(subset=["fecha", "valor_cuota"]).sort_values("fecha").drop_duplicates("fecha", keep="last")
    sbs["ret_target"] = sbs["valor_cuota"].pct_change(fill_method=None)

    markets = pd.read_csv(MARKETS_PATH)
    markets["fecha"] = pd.to_datetime(markets["fecha"], errors="coerce")
    for col in CALENDAR_FEATURES:
        markets[col] = pd.to_numeric(markets[col], errors="coerce")
    market_calendar = markets[["fecha", *CALENDAR_FEATURES]].dropna(subset=["fecha", *CALENDAR_FEATURES])
    market_calendar = market_calendar.sort_values("fecha").drop_duplicates("fecha", keep="last")

    calendar = sbs[["fecha", "valor_cuota", "ret_target"]].merge(market_calendar, on="fecha", how="inner")
    calendar = calendar.dropna(subset=["ret_target", "valor_cuota", *CALENDAR_FEATURES]).sort_values("fecha").drop_duplicates("fecha", keep="last").reset_index(drop=True)

    aligned = calendar[["fecha", "valor_cuota", "ret_target"]].merge(alt[["fecha", *FEATURES]], on="fecha", how="left")
    return live, alt, calendar, aligned


def fit(train: pd.DataFrame) -> tuple[np.ndarray, dict[str, float]]:
    x = train[FEATURES].to_numpy(float)
    y = train["ret_target"].to_numpy(float)
    beta = np.linalg.lstsq(np.c_[np.ones(len(x)), x], y, rcond=None)[0]
    names = ["intercept", *FEATURES]
    return beta, {name: float(value) for name, value in zip(names, beta)}


def predict(beta: np.ndarray, values: dict[str, float]) -> float:
    return float(beta[0] + sum(float(beta[i + 1]) * float(values[f]) for i, f in enumerate(FEATURES)))


def row_values(row: pd.Series) -> dict[str, float]:
    values = {}
    for feature in FEATURES:
        value = pd.to_numeric(pd.Series([row.get(feature)]), errors="coerce").iloc[0]
        if pd.isna(value):
            raise RuntimeError(f"Falta {feature} en fecha histórica")
        values[feature] = float(value)
    return values


def live_values(live: dict) -> tuple[dict[str, float], dict[str, str], dict[str, str]]:
    rows = {str(x.get("serie", "")): x for x in live.get("experimental_assets", [])}
    mapping = {
        "ret_.INX": ".INX",
        "ret_CPER": "CPER",
        "ret_EEM_alt": "EEM",
        "ret_NDX": "NDX",
        "ret_SPBLSCUP": "SPBLSCUP",
        "ret_USD_PEN_alt": "USD/PEN",
    }
    values, sources, stamps = {}, {}, {}
    for feature, serie in mapping.items():
        row = rows.get(serie, {})
        raw = row.get("retorno")
        value = pd.to_numeric(pd.Series([raw]), errors="coerce").iloc[0]
        if pd.isna(value) and serie == "SPBLSCUP":
            value = 0.0
            sources[feature] = "SIN NUEVO CIERRE · RETORNO 0"
        elif pd.isna(value):
            raise RuntimeError(f"Falta retorno intradía para {serie}")
        else:
            sources[feature] = str(row.get("estado", ""))
        values[feature] = float(value)
        stamps[feature] = str(row.get("timestamp", ""))
    return values, sources, stamps


def load_ledger() -> pd.DataFrame:
    if not LEDGER_PATH.exists() or LEDGER_PATH.stat().st_size == 0:
        return pd.DataFrame()
    df = pd.read_csv(LEDGER_PATH)
    df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce")
    return df.dropna(subset=["fecha"]).sort_values("fecha").drop_duplicates("fecha", keep="last").reset_index(drop=True)


def exact_train(calendar: pd.DataFrame, aligned: pd.DataFrame, before_or_on: pd.Timestamp, strict_before: bool = False) -> pd.DataFrame:
    base = calendar.loc[calendar["fecha"] < before_or_on] if strict_before else calendar.loc[calendar["fecha"] <= before_or_on]
    target_dates = base.tail(TRAIN_WINDOW)[["fecha"]].copy()
    if len(target_dates) != TRAIN_WINDOW:
        raise RuntimeError(f"Calendario challenger incompleto: {len(target_dates)}")
    train = target_dates.merge(aligned, on="fecha", how="left")
    missing = train.loc[train[FEATURES].isna().any(axis=1), "fecha"].dt.date.astype(str).tolist()
    if missing:
        raise RuntimeError(f"Faltan nuevos tickers en fechas del challenger: {missing}")
    return train.sort_values("fecha").reset_index(drop=True)


def historical_backtest(calendar: pd.DataFrame, aligned: pd.DataFrame) -> dict:
    test = aligned.loc[aligned["fecha"].isin(TEST_DATES)].copy().sort_values("fecha").reset_index(drop=True)
    missing_test = [d.date().isoformat() for d in TEST_DATES if d not in set(test.dropna(subset=FEATURES)["fecha"])]
    if missing_test:
        return {"n": 0, "rows": [], "error": f"Fechas faltantes del test: {missing_test}"}
    test = test.dropna(subset=FEATURES)
    train = exact_train(calendar, aligned, TEST_DATES[0], strict_before=True)
    beta, _ = fit(train)
    vc_value = float(train.iloc[-1]["valor_cuota"])
    rows, errors = [], []
    for _, row in test.iterrows():
        ret = predict(beta, row_values(row))
        vc_value *= 1.0 + ret
        actual = float(row["valor_cuota"])
        err = abs(vc_value - actual)
        errors.append(err)
        rows.append({
            "fecha": pd.Timestamp(row["fecha"]).date().isoformat(),
            "source": "BACKTEST CIEGO 60/30 · MISMO CALENDARIO CHALLENGER",
            "vc": vc_value,
            "return": ret,
            "signal": classify(ret),
            "actual_vc": actual,
            "abs_error": err,
        })
    arr = np.asarray(errors, dtype=float)
    return {
        "n": len(rows),
        "train_start": pd.Timestamp(train.iloc[0]["fecha"]).date().isoformat(),
        "train_end": pd.Timestamp(train.iloc[-1]["fecha"]).date().isoformat(),
        "anchor_date": pd.Timestamp(train.iloc[-1]["fecha"]).date().isoformat(),
        "anchor_vc": float(train.iloc[-1]["valor_cuota"]),
        "mae_vc": float(arr.mean()),
        "rmse_vc": float(np.sqrt(np.mean(arr ** 2))),
        "rows": rows,
    }


def main() -> None:
    live, alt, calendar, aligned = load_inputs()
    signal_date = pd.Timestamp(str(live.get("signal_date"))).normalize()

    train = exact_train(calendar, aligned, ANCHOR_DATE, strict_before=False)
    if pd.Timestamp(train.iloc[-1]["fecha"]).normalize() != ANCHOR_DATE:
        raise RuntimeError("La ventana 60/30 no termina en el ancla 18/08")

    state = safe_json(CHALLENGER_STATE_PATH)
    challenger_span_match = None
    if state:
        challenger_span_match = (
            str(train.iloc[0]["fecha"].date()) == str(state.get("train_start"))
            and str(train.iloc[-1]["fecha"].date()) == str(state.get("train_end"))
            and int(state.get("train_n", TRAIN_WINDOW)) == TRAIN_WINDOW
        )
        if not challenger_span_match:
            raise RuntimeError(
                f"Ventana experimental no coincide con challenger: "
                f"{train.iloc[0]['fecha'].date()}–{train.iloc[-1]['fecha'].date()} vs "
                f"{state.get('train_start')}–{state.get('train_end')}"
            )

    beta, coeff = fit(train)
    anchor_vc = float(train.iloc[-1]["valor_cuota"])

    alt_by_date = {pd.Timestamp(r["fecha"]).normalize(): r for _, r in alt.iterrows()}
    ledger = load_ledger()
    existing = {} if ledger.empty else {pd.Timestamp(r["fecha"]).normalize(): dict(r) for _, r in ledger.iterrows()}
    generated = datetime.now(LIMA).isoformat()
    vc_value = anchor_vc
    rows: list[dict] = [{
        "fecha": ANCHOR_DATE.date().isoformat(),
        "base_vc": anchor_vc,
        "return": None,
        "signal": "ANCLA",
        "vc": anchor_vc,
        "actual_vc": anchor_vc,
        "abs_error": 0.0,
        "source": "ANCLA SBS DEL CICLO",
        "factor_returns": {},
        "factor_sources": {},
        "factor_timestamps": {},
        "updated_at_lima": generated,
    }]
    current_row: dict | None = None

    sbs_map = {pd.Timestamp(r["fecha"]).normalize(): float(r["valor_cuota"]) for _, r in calendar.iterrows()}

    for d in pd.bdate_range(CYCLE_START, signal_date):
        d = pd.Timestamp(d).normalize()
        old = existing.get(d)
        if old is not None and d < signal_date and pd.notna(old.get("vc")) and pd.notna(old.get("return")):
            vc_value = float(old["vc"])
            rows.append(old)
            continue

        if d == signal_date:
            values, sources, stamps = live_values(live)
            source = "INTRADÍA EXPERIMENTAL" if bool(live.get("market_open")) else "CIERRE/ÚLTIMO CORTE EXPERIMENTAL"
        else:
            hist = alt_by_date.get(d)
            if hist is None:
                values = {f: 0.0 for f in FEATURES}
                sources = {f: "SIN SESIÓN · RETORNO 0" for f in FEATURES}
                stamps = {f: d.date().isoformat() for f in FEATURES}
                source = "SIN SESIÓN · RETORNO 0"
            else:
                values = row_values(hist)
                sources = {f: "CIERRE HISTÓRICO GUARDADO" for f in FEATURES}
                stamps = {f: d.date().isoformat() for f in FEATURES}
                source = "CIERRE HISTÓRICO GUARDADO"

        ret = predict(beta, values)
        base_vc = vc_value
        vc_value = base_vc * (1.0 + ret)
        actual_vc = sbs_map.get(d)
        row = {
            "fecha": d.date().isoformat(),
            "base_vc": base_vc,
            "return": ret,
            "signal": classify(ret),
            "vc": vc_value,
            "actual_vc": actual_vc,
            "abs_error": None if actual_vc is None else abs(vc_value - actual_vc),
            "source": source,
            "factor_returns": values,
            "factor_sources": sources,
            "factor_timestamps": stamps,
            "updated_at_lima": generated,
        }
        rows.append(row)
        if d == signal_date:
            current_row = row

    if current_row is None:
        if signal_date == ANCHOR_DATE:
            current_row = rows[0]
        else:
            same = [r for r in rows if str(r.get("fecha")) == signal_date.date().isoformat()]
            current_row = same[-1] if same else None
    if current_row is None:
        raise RuntimeError("No se pudo calcular el 60/30 de nuevos tickers")

    ledger_rows = [r for r in rows if r.get("source") != "ANCLA SBS DEL CICLO"]
    new_ledger = pd.DataFrame(ledger_rows)
    if not ledger.empty:
        before = ledger.loc[ledger["fecha"] < CYCLE_START].copy()
        new_ledger = pd.concat([before, new_ledger], ignore_index=True, sort=False)
    new_ledger = new_ledger.sort_values("fecha").drop_duplicates("fecha", keep="last")
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    new_ledger.to_csv(LEDGER_PATH, index=False)

    backtest = historical_backtest(calendar, aligned)
    output = {
        "generated_at_lima": generated,
        "signal_date": signal_date.date().isoformat(),
        "mode": live.get("mode"),
        "market_open": bool(live.get("market_open")),
        "market_snapshot_generated_at_lima": live.get("generated_at_lima"),
        "role": "EXPERIMENTAL; no reemplaza OLS oficial ni challenger 60/30 vigente.",
        "model": {
            "name": "OLS 60/30 · nuevos tickers",
            "features_display": DISPLAY_FEATURES,
            "features": FEATURES,
            "return_estimated": None if current_row.get("return") is None else float(current_row["return"]),
            "signal": str(current_row["signal"]),
            "vc_estimated": float(current_row["vc"]),
            "blind_chain": True,
            "reanchored_with_latest_sbs": False,
        },
        "cycle": {
            "cycle_start": CYCLE_START.date().isoformat(),
            "cycle_day": int(max(0, len([r for r in rows if str(r.get("fecha", "")) >= CYCLE_START.date().isoformat()]))),
            "anchor_date": ANCHOR_DATE.date().isoformat(),
            "anchor_vc": anchor_vc,
            "train_start": pd.Timestamp(train.iloc[0]["fecha"]).date().isoformat(),
            "train_end": pd.Timestamp(train.iloc[-1]["fecha"]).date().isoformat(),
            "train_n": TRAIN_WINDOW,
            "freeze_horizon": FREEZE_HORIZON,
            "same_calendar_as_challenger": challenger_span_match,
            "calendar_rule": "Mismas 60 fechas base del challenger, definidas por SBS + factores de mercado completos; los seis nuevos tickers se ajustan sobre esas fechas.",
            "coefficients": coeff,
        },
        "backtest_exact20": backtest,
        "operational_history": rows,
        "history_min_date": backtest.get("rows", [{}])[0].get("fecha") if backtest.get("rows") else ANCHOR_DATE.date().isoformat(),
        "history_max_date": signal_date.date().isoformat(),
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "signal_date": output["signal_date"],
        "signal": output["model"]["signal"],
        "vc": output["model"]["vc_estimated"],
        "return": output["model"]["return_estimated"],
        "train_start": output["cycle"]["train_start"],
        "train_end": output["cycle"]["train_end"],
        "same_calendar_as_challenger": output["cycle"]["same_calendar_as_challenger"],
        "backtest_n": output["backtest_exact20"].get("n"),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
