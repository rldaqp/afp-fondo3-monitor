from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

import build_reduced_6030_challenger as current
import recheck_6030_exact20 as exact

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "rolling90"
PUBLIC = ROOT / "public" / "data"
LIVE_PATH = PUBLIC / "live_market.json"
OUT_PATH = PUBLIC / "alt_6030_experimental.json"
LEDGER_PATH = DATA / "alt_6030_shadow.csv"

ANCHOR_DATE = pd.Timestamp("2026-08-18")
CYCLE_START = pd.Timestamp("2026-08-19")
TRAIN_WINDOW = 60
FREEZE_HORIZON = 30
THRESHOLD = 0.001
LIMA = ZoneInfo("America/Lima")
FEATURES = exact.ALT_FEATURES
DISPLAY_FEATURES = [".INX", "CPER", "EEM", "NDX", "SPBLSCUP", "USD/PEN"]


def classify(value: float) -> str:
    if value > THRESHOLD:
        return "SUBE"
    if value < -THRESHOLD:
        return "BAJA"
    return "NEUTRO"


def _safe_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception:
        return {}


def _fit(train: pd.DataFrame) -> tuple[np.ndarray, dict[str, float]]:
    x = train[FEATURES].to_numpy(float)
    y = train["ret_target"].to_numpy(float)
    beta = np.linalg.lstsq(np.c_[np.ones(len(x)), x], y, rcond=None)[0]
    names = ["intercept", *FEATURES]
    return beta, {name: float(value) for name, value in zip(names, beta)}


def _predict(beta: np.ndarray, values: dict[str, float]) -> float:
    return float(beta[0] + sum(float(beta[i + 1]) * float(values[f]) for i, f in enumerate(FEATURES)))


def _row_values(row: pd.Series) -> dict[str, float]:
    out: dict[str, float] = {}
    for f in FEATURES:
        value = pd.to_numeric(pd.Series([row.get(f)]), errors="coerce").iloc[0]
        if pd.isna(value):
            raise RuntimeError(f"Falta {f} en fecha histórica")
        out[f] = float(value)
    return out


def _live_values(live: dict) -> tuple[dict[str, float], dict[str, str]]:
    rows = {str(x.get("serie", "")): x for x in live.get("experimental_assets", [])}
    mapping = {
        "ret_.INX": ".INX",
        "ret_CPER": "CPER",
        "ret_EEM_alt": "EEM",
        "ret_NDX": "NDX",
        "ret_SPBLSCUP": "SPBLSCUP",
        "ret_USD_PEN_alt": "USD/PEN",
    }
    values: dict[str, float] = {}
    sources: dict[str, str] = {}
    for feature, serie in mapping.items():
        row = rows.get(serie, {})
        raw = row.get("retorno")
        value = pd.to_numeric(pd.Series([raw]), errors="coerce").iloc[0]
        # SPBLSCUP puede no negociar una sesión peruana aunque NY sí esté abierto.
        # En ese caso se mantiene el último cierre: retorno 0, igual que en el backtest.
        if pd.isna(value) and serie == "SPBLSCUP":
            value = 0.0
            sources[feature] = "SIN NUEVO CIERRE · RETORNO 0"
        elif pd.isna(value):
            raise RuntimeError(f"Falta retorno intradía para {serie}")
        else:
            sources[feature] = str(row.get("estado", ""))
        values[feature] = float(value)
    return values, sources


def _load_ledger() -> pd.DataFrame:
    if not LEDGER_PATH.exists() or LEDGER_PATH.stat().st_size == 0:
        return pd.DataFrame()
    df = pd.read_csv(LEDGER_PATH)
    df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce")
    return df.dropna(subset=["fecha"]).sort_values("fecha").drop_duplicates("fecha", keep="last").reset_index(drop=True)


def _historical_backtest(both: pd.DataFrame) -> dict:
    test = both.loc[both["fecha"].isin(exact.TEST_DATES)].copy().sort_values("fecha").reset_index(drop=True)
    train = both.loc[both["fecha"] < exact.TEST_DATES[0]].tail(TRAIN_WINDOW).copy().reset_index(drop=True)
    if len(test) != len(exact.TEST_DATES) or len(train) != TRAIN_WINDOW:
        return {"n": 0, "rows": []}
    beta, _ = _fit(train)
    vc = float(train.iloc[-1]["valor_cuota"])
    rows: list[dict] = []
    errors: list[float] = []
    for _, row in test.iterrows():
        ret = _predict(beta, _row_values(row))
        vc *= 1.0 + ret
        actual = float(row["valor_cuota"])
        err = abs(vc - actual)
        errors.append(err)
        rows.append({
            "fecha": pd.Timestamp(row["fecha"]).date().isoformat(),
            "vc": vc,
            "return": ret,
            "actual_vc": actual,
            "abs_error": err,
        })
    arr = np.asarray(errors, dtype=float)
    return {
        "n": len(rows),
        "mae_vc": float(arr.mean()),
        "rmse_vc": float(np.sqrt(np.mean(arr ** 2))),
        "rows": rows,
    }


def main() -> None:
    live = _safe_json(LIVE_PATH)
    markets = current.read_csv(DATA / "markets.csv")
    sbs_raw = current.read_csv(DATA / "sbs_profuturo_f3.csv")
    if not live or markets.empty or sbs_raw.empty:
        raise RuntimeError("Faltan datos base para 60/30 nuevos tickers")

    signal_date = pd.Timestamp(str(live.get("signal_date"))).normalize()
    markets["fecha"] = pd.to_datetime(markets["fecha"], errors="coerce")

    # La misma muestra común que se usó al comparar el challenger vigente y los
    # nuevos tickers. Así los coeficientes de 19-20/08 reproducen la prueba previa.
    qqq = current.download_qqq(pd.Timestamp("2026-04-01"), max(signal_date, pd.Timestamp("2026-08-20")))
    common, sbs, _ = current.prepare_frames(markets, sbs_raw, qqq)
    alt = exact.build_alt()
    both = common.merge(alt, on="fecha", how="inner")
    both = both.dropna(subset=[*current.REDUCED_FEATURES, *FEATURES, "ret_target", "valor_cuota"]).sort_values("fecha").drop_duplicates("fecha", keep="last").reset_index(drop=True)

    train = both.loc[both["fecha"] <= ANCHOR_DATE].tail(TRAIN_WINDOW).copy().reset_index(drop=True)
    if len(train) != TRAIN_WINDOW or pd.Timestamp(train.iloc[-1]["fecha"]).normalize() != ANCHOR_DATE:
        raise RuntimeError("Entrenamiento 60/30 nuevos tickers incompleto al 18/08")
    beta, coeff = _fit(train)

    anchor_rows = sbs.loc[sbs["fecha"].eq(ANCHOR_DATE), "valor_cuota"]
    if anchor_rows.empty:
        raise RuntimeError("No existe ancla SBS 18/08")
    anchor_vc = float(anchor_rows.iloc[-1])

    ledger = _load_ledger()
    existing = {} if ledger.empty else {pd.Timestamp(r["fecha"]).normalize(): dict(r) for _, r in ledger.iterrows()}
    vc = anchor_vc
    rows: list[dict] = []
    generated = datetime.now(LIMA).isoformat()

    # Recorremos desde el inicio del ciclo hasta el corte actual. 19 y 20 salen de
    # cierres Google Finance guardados; días anteriores al actual que ya pasaron se
    # conservan desde el ledger, evitando reescribir la sombra operativa.
    calendar = pd.bdate_range(CYCLE_START, signal_date)
    alt_by_date = {pd.Timestamp(r["fecha"]).normalize(): r for _, r in alt.iterrows()}
    current_row: dict | None = None
    for d in calendar:
        d = pd.Timestamp(d).normalize()
        old = existing.get(d)
        if old is not None and d < signal_date and pd.notna(old.get("vc")) and pd.notna(old.get("return")):
            vc = float(old["vc"])
            rows.append(old)
            continue

        if d == signal_date:
            values, sources = _live_values(live)
            source = "INTRADÍA EXPERIMENTAL" if bool(live.get("market_open")) else "CIERRE/ÚLTIMO CORTE EXPERIMENTAL"
        else:
            hist = alt_by_date.get(d)
            if hist is None:
                # Feriado o sesión sin cierre conjunto: no inventamos movimiento.
                values = {f: 0.0 for f in FEATURES}
                sources = {f: "SIN SESIÓN · 0" for f in FEATURES}
                source = "SIN SESIÓN · RETORNO 0"
            else:
                values = _row_values(hist)
                sources = {f: "GOOGLE FINANCE CIERRE" for f in FEATURES}
                source = "GOOGLE FINANCE CIERRE"

        ret = _predict(beta, values)
        base_vc = vc
        vc = base_vc * (1.0 + ret)
        actual = sbs.loc[sbs["fecha"].eq(d), "valor_cuota"]
        actual_vc = None if actual.empty else float(actual.iloc[-1])
        row = {
            "fecha": d.date().isoformat(),
            "base_vc": base_vc,
            "return": ret,
            "signal": classify(ret),
            "vc": vc,
            "actual_vc": actual_vc,
            "abs_error": None if actual_vc is None else abs(vc - actual_vc),
            "source": source,
            "factor_returns": values,
            "factor_sources": sources,
            "updated_at_lima": generated,
        }
        rows.append(row)
        if d == signal_date:
            current_row = row

    if current_row is None:
        same = [r for r in rows if str(r.get("fecha")) == signal_date.date().isoformat()]
        current_row = same[-1] if same else None
    if current_row is None:
        raise RuntimeError("No se pudo calcular el 60/30 de nuevos tickers")

    new_ledger = pd.DataFrame(rows)
    if not ledger.empty:
        before = ledger.loc[ledger["fecha"] < CYCLE_START].copy()
        new_ledger = pd.concat([before, new_ledger], ignore_index=True, sort=False)
    new_ledger = new_ledger.sort_values("fecha").drop_duplicates("fecha", keep="last")
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    new_ledger.to_csv(LEDGER_PATH, index=False)

    backtest = _historical_backtest(both)
    cycle_day = int(len([r for r in rows if str(r.get("fecha", "")) >= CYCLE_START.date().isoformat()]))
    output = {
        "generated_at_lima": generated,
        "signal_date": signal_date.date().isoformat(),
        "mode": live.get("mode"),
        "market_open": bool(live.get("market_open")),
        "role": "EXPERIMENTAL; no reemplaza OLS oficial ni challenger 60/30 vigente.",
        "model": {
            "name": "OLS 60/30 · nuevos tickers",
            "features_display": DISPLAY_FEATURES,
            "features": FEATURES,
            "return_estimated": float(current_row["return"]),
            "signal": str(current_row["signal"]),
            "vc_estimated": float(current_row["vc"]),
            "blind_chain": True,
            "reanchored_with_latest_sbs": False,
        },
        "cycle": {
            "cycle_start": CYCLE_START.date().isoformat(),
            "cycle_day": cycle_day,
            "anchor_date": ANCHOR_DATE.date().isoformat(),
            "anchor_vc": anchor_vc,
            "train_start": pd.Timestamp(train.iloc[0]["fecha"]).date().isoformat(),
            "train_end": pd.Timestamp(train.iloc[-1]["fecha"]).date().isoformat(),
            "train_n": TRAIN_WINDOW,
            "freeze_horizon": FREEZE_HORIZON,
            "coefficients": coeff,
        },
        "backtest_exact20": backtest,
        "operational_history": rows,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
