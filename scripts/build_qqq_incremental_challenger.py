from __future__ import annotations

import argparse
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
OUT_PATH = PUBLIC / "qqq_incremental_challenger.json"
SHADOW_PATH = DATA / "qqq_incremental_shadow.csv"

WINDOW = 90
THRESHOLD = 0.001
LIMA = ZoneInfo("America/Lima")
NY = ZoneInfo("America/New_York")

BASE_FEATURES = [
    "ret_SPY",
    "ret_NEM",
    "ret_FCX",
    "ret_EPU",
    "ret_MCHI",
    "ret_EEM",
    "ret_USD_PEN",
]
CHALLENGER_FEATURES = [*BASE_FEATURES, "ret_QQQ_residual"]
HORIZONS = [30, 60, 90, 180]


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


def download_qqq_daily(start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
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
        raise RuntimeError("Yahoo no devolvió cierres diarios de QQQ")
    idx = pd.to_datetime(close.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    out = pd.DataFrame({"fecha": idx.normalize(), "QQQ": close.to_numpy(float)})
    out = out.sort_values("fecha").drop_duplicates("fecha", keep="last")
    out["ret_QQQ"] = out["QQQ"].pct_change(fill_method=None)
    return out


def current_qqq_return(qqq_daily: pd.DataFrame, signal_date: pd.Timestamp, market_open: bool) -> tuple[float, float, float, str]:
    q = qqq_daily.sort_values("fecha")
    prior = q.loc[q["fecha"] < signal_date]
    if prior.empty:
        raise RuntimeError("No existe cierre previo de QQQ")
    previous = float(prior.iloc[-1]["QQQ"])

    same = q.loc[q["fecha"] == signal_date]
    if not market_open and not same.empty:
        current = float(same.iloc[-1]["QQQ"])
        return current / previous - 1.0, previous, current, "CIERRE DIARIO YAHOO"

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
    intraday = extract_close(raw, "QQQ")
    if not intraday.empty:
        current = float(intraday.iloc[-1])
        return current / previous - 1.0, previous, current, "INTRADÍA YAHOO" if market_open else "ÚLTIMO CORTE YAHOO"

    if not same.empty:
        current = float(same.iloc[-1]["QQQ"])
        return current / previous - 1.0, previous, current, "CIERRE DIARIO YAHOO"
    raise RuntimeError("No se pudo obtener precio actual de QQQ")


def prepare_data(markets: pd.DataFrame, sbs_raw: pd.DataFrame, qqq: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    markets = markets.copy()
    sbs = sbs_raw.copy()
    markets["fecha"] = pd.to_datetime(markets["fecha"], errors="coerce")
    for f in BASE_FEATURES:
        if f not in markets.columns:
            raise RuntimeError(f"Falta {f} en markets.csv")
        markets[f] = pd.to_numeric(markets[f], errors="coerce")

    sbs["fecha"] = pd.to_datetime(sbs["fecha"], errors="coerce")
    sbs["valor_cuota"] = pd.to_numeric(sbs["valor_cuota"], errors="coerce")
    sbs = sbs.dropna(subset=["fecha", "valor_cuota"]).sort_values("fecha").drop_duplicates("fecha", keep="last")
    sbs["ret_target"] = sbs["valor_cuota"].pct_change(fill_method=None)

    m = markets.merge(qqq[["fecha", "QQQ", "ret_QQQ"]], on="fecha", how="left")
    frame = sbs[["fecha", "valor_cuota", "ret_target"]].merge(m, on="fecha", how="inner")
    frame = frame.loc[frame["fecha"] >= pd.Timestamp("2025-01-01")]
    frame = frame.dropna(subset=["ret_target", "ret_QQQ", *BASE_FEATURES]).sort_values("fecha").drop_duplicates("fecha", keep="last").reset_index(drop=True)
    if len(frame) <= WINDOW:
        raise RuntimeError(f"Muestra insuficiente para QQQ incremental: {len(frame)}")
    return frame, sbs


def residualizer(train: pd.DataFrame) -> np.ndarray:
    x = train[BASE_FEATURES].to_numpy(float)
    q = train["ret_QQQ"].to_numpy(float)
    return np.linalg.lstsq(np.c_[np.ones(len(x)), x], q, rcond=None)[0]


def residual_values(train: pd.DataFrame, beta: np.ndarray) -> np.ndarray:
    x = train[BASE_FEATURES].to_numpy(float)
    return train["ret_QQQ"].to_numpy(float) - np.c_[np.ones(len(x)), x] @ beta


def standardize_fit(x: np.ndarray, y: np.ndarray) -> dict[str, np.ndarray | float]:
    mu = x.mean(axis=0)
    sd = x.std(axis=0, ddof=0)
    sd = np.where(sd < 1e-12, 1.0, sd)
    xz = (x - mu) / sd
    beta = np.linalg.lstsq(np.c_[np.ones(len(xz)), xz], y, rcond=None)[0]
    return {"mu": mu, "sd": sd, "intercept": float(beta[0]), "coef": beta[1:]}


def standardize_predict(model: dict[str, np.ndarray | float], x: np.ndarray) -> float:
    mu = np.asarray(model["mu"], dtype=float)
    sd = np.asarray(model["sd"], dtype=float)
    coef = np.asarray(model["coef"], dtype=float)
    xz = (np.asarray(x, dtype=float) - mu) / sd
    return float(float(model["intercept"]) + xz @ coef)


def fit_challenger(train: pd.DataFrame) -> tuple[np.ndarray, dict[str, np.ndarray | float]]:
    beta_resid = residualizer(train)
    resid = residual_values(train, beta_resid)
    x = np.column_stack([train[BASE_FEATURES].to_numpy(float), resid])
    model = standardize_fit(x, train["ret_target"].to_numpy(float))
    return beta_resid, model


def challenger_predict(train: pd.DataFrame, current: pd.Series) -> tuple[float, float]:
    beta_resid, model = fit_challenger(train)
    base = current[BASE_FEATURES].to_numpy(float)
    qqq_resid = float(current["ret_QQQ"] - np.r_[1.0, base] @ beta_resid)
    pred = standardize_predict(model, np.r_[base, qqq_resid])
    return pred, qqq_resid


def rolling_predictions(frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for i in range(WINDOW, len(frame)):
        train = frame.iloc[i - WINDOW:i]
        current = frame.iloc[i]
        challenger, residual = challenger_predict(train, current)

        # OLS base reconstruido sobre exactamente la misma muestra común con QQQ.
        x_base = train[BASE_FEATURES].to_numpy(float)
        base_model = standardize_fit(x_base, train["ret_target"].to_numpy(float))
        official = standardize_predict(base_model, current[BASE_FEATURES].to_numpy(float))
        actual = float(current["ret_target"])
        rows.append({
            "fecha": current["fecha"],
            "actual": actual,
            "official": official,
            "challenger": challenger,
            "qqq_residual": residual,
            "actual_signal": classify(actual),
            "official_signal": classify(official),
            "challenger_signal": classify(challenger),
        })
    return pd.DataFrame(rows)


def metrics(pred: pd.DataFrame) -> dict[str, object]:
    if pred.empty:
        return {"n": 0}
    ae_off = (pred["official"] - pred["actual"]).abs()
    ae_ch = (pred["challenger"] - pred["actual"]).abs()
    off_hit = pred["official_signal"].eq(pred["actual_signal"])
    ch_hit = pred["challenger_signal"].eq(pred["actual_signal"])
    off_mae = float(ae_off.mean())
    ch_mae = float(ae_ch.mean())
    return {
        "n": int(len(pred)),
        "official_mae": off_mae,
        "challenger_mae": ch_mae,
        "mae_improvement_pct": None if off_mae <= 0 else float((off_mae - ch_mae) / off_mae * 100.0),
        "official_direction_accuracy": float(off_hit.mean()),
        "challenger_direction_accuracy": float(ch_hit.mean()),
        "direction_delta_pp": float((ch_hit.mean() - off_hit.mean()) * 100.0),
        "challenger_win_days": int((ae_ch < ae_off).sum()),
        "official_win_days": int((ae_off < ae_ch).sum()),
        "ties": int(np.isclose(ae_off.to_numpy(float), ae_ch.to_numpy(float), atol=1e-15).sum()),
    }


def vif_table(x: np.ndarray, names: list[str]) -> dict[str, object]:
    values: dict[str, float] = {}
    for j, name in enumerate(names):
        y = x[:, j]
        others = np.delete(x, j, axis=1)
        design = np.c_[np.ones(len(others)), others]
        fit = np.linalg.lstsq(design, y, rcond=None)[0]
        pred = design @ fit
        ss_res = float(np.sum((y - pred) ** 2))
        ss_tot = float(np.sum((y - y.mean()) ** 2))
        r2 = 1.0 - ss_res / ss_tot if ss_tot > 1e-20 else 1.0
        values[name] = float(1.0 / max(1e-12, 1.0 - r2))
    return {
        "by_feature": values,
        "max_vif": float(max(values.values())),
        "max_vif_feature": max(values, key=values.get),
    }


def build_backtest(frame: pd.DataFrame) -> dict[str, object]:
    pred = rolling_predictions(frame)
    windows: dict[str, object] = {}
    for h in HORIZONS:
        windows[str(h)] = metrics(pred.tail(h))
    windows["ALL"] = metrics(pred)

    recent = frame.tail(WINDOW)
    beta = residualizer(recent)
    resid = residual_values(recent, beta)
    x = np.column_stack([recent[BASE_FEATURES].to_numpy(float), resid])
    vif = vif_table(x, CHALLENGER_FEATURES)
    return {
        "method": "OLS rolling 90. QQQ se residualiza dentro de cada ventana contra los 7 factores del OLS oficial; no usa información futura.",
        "prediction_rows": int(len(pred)),
        "first_prediction": None if pred.empty else pred.iloc[0]["fecha"].date().isoformat(),
        "last_prediction": None if pred.empty else pred.iloc[-1]["fecha"].date().isoformat(),
        "windows": windows,
        "recent90_vif": vif,
    }


def live_base_features(live: dict, pending: pd.DataFrame, signal_date: pd.Timestamp) -> np.ndarray:
    mapping: dict[str, float] = {}
    for row in live.get("assets", []):
        serie = str(row.get("serie", ""))
        key = f"ret_{serie}"
        if key in BASE_FEATURES:
            value = pd.to_numeric(pd.Series([row.get("retorno_modelo")]), errors="coerce").iloc[0]
            if pd.notna(value):
                mapping[key] = float(value)
    if all(f in mapping for f in BASE_FEATURES):
        return np.array([mapping[f] for f in BASE_FEATURES], dtype=float)

    if not pending.empty:
        p = pending.copy()
        p["fecha"] = pd.to_datetime(p["fecha"], errors="coerce")
        same = p.loc[p["fecha"].dt.normalize().eq(signal_date)].sort_values("fecha")
        if not same.empty:
            row = same.iloc[-1]
            vals = [pd.to_numeric(pd.Series([row.get(f)]), errors="coerce").iloc[0] for f in BASE_FEATURES]
            if all(pd.notna(v) for v in vals):
                return np.array(vals, dtype=float)
    missing = [f for f in BASE_FEATURES if f not in mapping]
    raise RuntimeError("No se pudieron obtener factores actuales: " + ", ".join(missing))


def evaluate_shadow(shadow: pd.DataFrame, sbs: pd.DataFrame) -> pd.DataFrame:
    if shadow.empty:
        return shadow
    s = sbs.copy().sort_values("fecha").drop_duplicates("fecha", keep="last")
    s["actual_return"] = s["valor_cuota"].pct_change(fill_method=None)
    lookup = s.set_index(s["fecha"].dt.strftime("%Y-%m-%d"))[["valor_cuota", "actual_return"]].to_dict("index")
    for idx, row in shadow.iterrows():
        key = str(row.get("fecha", ""))[:10]
        actual = lookup.get(key)
        if not actual or pd.isna(actual.get("actual_return")):
            continue
        ar = float(actual["actual_return"])
        avc = float(actual["valor_cuota"])
        shadow.at[idx, "actual_return"] = ar
        shadow.at[idx, "actual_signal"] = classify(ar)
        shadow.at[idx, "actual_vc"] = avc
        for prefix in ("official", "challenger"):
            pred = pd.to_numeric(pd.Series([row.get(f"{prefix}_return")]), errors="coerce").iloc[0]
            sig = str(row.get(f"{prefix}_signal", ""))
            if pd.notna(pred):
                shadow.at[idx, f"{prefix}_abs_error"] = abs(float(pred) - ar)
                shadow.at[idx, f"{prefix}_hit"] = bool(sig == classify(ar))
        shadow.at[idx, "status"] = "EVALUADO"
    return shadow


def forward_metrics(shadow: pd.DataFrame) -> dict[str, object]:
    if shadow.empty:
        return {"n": 0, "pending": 0}
    evaluated = shadow.loc[shadow.get("status", pd.Series(index=shadow.index, dtype=str)).astype(str).eq("EVALUADO")].copy()
    out: dict[str, object] = {
        "n": int(len(evaluated)),
        "pending": int(len(shadow) - len(evaluated)),
        "start_date": None if shadow.empty else str(shadow.iloc[0].get("fecha"))[:10],
    }
    if evaluated.empty:
        return out
    for prefix in ("official", "challenger"):
        ae = pd.to_numeric(evaluated[f"{prefix}_abs_error"], errors="coerce").dropna()
        hits = evaluated[f"{prefix}_hit"].astype(str).str.lower().map({"true": True, "false": False}).dropna()
        out[f"{prefix}_mae"] = None if ae.empty else float(ae.mean())
        out[f"{prefix}_direction_accuracy"] = None if hits.empty else float(hits.mean())
    if out.get("official_mae") is not None and out.get("challenger_mae") is not None and float(out["official_mae"]) > 0:
        out["mae_improvement_pct"] = float((float(out["official_mae"]) - float(out["challenger_mae"])) / float(out["official_mae"]) * 100.0)
    if out.get("official_direction_accuracy") is not None and out.get("challenger_direction_accuracy") is not None:
        out["direction_delta_pp"] = float((float(out["challenger_direction_accuracy"]) - float(out["official_direction_accuracy"])) * 100.0)
    return out


def update_shadow(current: dict[str, object], sbs: pd.DataFrame, latest_sbs_date: str) -> tuple[pd.DataFrame, dict[str, object]]:
    shadow = read_csv(SHADOW_PATH)
    if shadow.empty:
        shadow = pd.DataFrame()
    if "fecha" in shadow.columns:
        shadow["fecha"] = shadow["fecha"].dt.strftime("%Y-%m-%d")

    signal_date = str(current["signal_date"])
    if signal_date > str(latest_sbs_date)[:10]:
        row = {
            "fecha": signal_date,
            "created_at_lima": current["generated_at_lima"],
            "updated_at_lima": current["generated_at_lima"],
            "vc_base": current["vc_base"],
            "official_return": current["official"]["return_estimated"],
            "official_signal": current["official"]["signal"],
            "official_vc": current["official"]["vc_estimated"],
            "challenger_return": current["challenger"]["return_estimated"],
            "challenger_signal": current["challenger"]["signal"],
            "challenger_vc": current["challenger"]["vc_estimated"],
            "qqq_return": current["qqq"]["return"],
            "qqq_residual": current["qqq"]["residual"],
            "actual_return": np.nan,
            "actual_signal": "",
            "actual_vc": np.nan,
            "official_abs_error": np.nan,
            "challenger_abs_error": np.nan,
            "official_hit": "",
            "challenger_hit": "",
            "status": "PENDIENTE",
        }
        if not shadow.empty and signal_date in set(shadow["fecha"].astype(str)):
            idx = shadow.index[shadow["fecha"].astype(str).eq(signal_date)][-1]
            created = shadow.at[idx, "created_at_lima"] if "created_at_lima" in shadow.columns else row["created_at_lima"]
            for key, value in row.items():
                shadow.at[idx, key] = value
            shadow.at[idx, "created_at_lima"] = created
        else:
            shadow = pd.concat([shadow, pd.DataFrame([row])], ignore_index=True)

    if not shadow.empty:
        shadow = evaluate_shadow(shadow, sbs)
        shadow = shadow.sort_values("fecha").drop_duplicates("fecha", keep="last").reset_index(drop=True)
        SHADOW_PATH.parent.mkdir(parents=True, exist_ok=True)
        shadow.to_csv(SHADOW_PATH, index=False)
    return shadow, forward_metrics(shadow)


def safe_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception:
        return {}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live-only", action="store_true", help="Conserva el backtest existente si ya fue calculado")
    args = parser.parse_args()

    latest = safe_json(LATEST_PATH)
    live = safe_json(LIVE_PATH)
    if not latest or not live:
        raise RuntimeError("Falta latest.json o live_market.json")

    markets = read_csv(DATA / "markets.csv")
    sbs_raw = read_csv(DATA / "sbs_profuturo_f3.csv")
    pending = read_csv(DATA / "pending_predictions.csv")
    if markets.empty or sbs_raw.empty:
        raise RuntimeError("Falta markets.csv o sbs_profuturo_f3.csv")

    markets["fecha"] = pd.to_datetime(markets["fecha"], errors="coerce")
    start = min(markets["fecha"].dropna().min(), pd.Timestamp("2024-12-01"))
    signal_date = pd.Timestamp(str(live.get("signal_date") or latest.get("latest_estimate_date"))).normalize()
    qqq = download_qqq_daily(start, max(signal_date, pd.Timestamp.now().normalize()))
    frame, sbs = prepare_data(markets, sbs_raw, qqq)

    train = frame.tail(WINDOW).copy()
    beta_resid, challenger_model = fit_challenger(train)
    base_current = live_base_features(live, pending, signal_date)
    qqq_ret, qqq_prev, qqq_current, qqq_source = current_qqq_return(qqq, signal_date, bool(live.get("market_open")))
    qqq_resid = float(qqq_ret - np.r_[1.0, base_current] @ beta_resid)
    challenger_ret = standardize_predict(challenger_model, np.r_[base_current, qqq_resid])

    official_ret = float(live.get("return_estimated"))
    official_vc = float(live.get("vc_estimated"))
    vc_base_raw = pd.to_numeric(pd.Series([live.get("vc_base")]), errors="coerce").iloc[0]
    if pd.notna(vc_base_raw) and float(vc_base_raw) > 0:
        vc_base = float(vc_base_raw)
    elif abs(1.0 + official_ret) > 1e-12:
        vc_base = official_vc / (1.0 + official_ret)
    else:
        vc_base = float(latest["latest_sbs_vc"])
    challenger_vc = vc_base * (1.0 + challenger_ret)

    generated = datetime.now(LIMA).isoformat()
    current: dict[str, object] = {
        "generated_at_lima": generated,
        "signal_date": signal_date.date().isoformat(),
        "mode": live.get("mode"),
        "market_open": bool(live.get("market_open")),
        "role": "CHALLENGER EN SOMBRA; no reemplaza el OLS oficial.",
        "vc_base": vc_base,
        "official": {
            "model": "OLS rolling 90 oficial",
            "return_estimated": official_ret,
            "signal": str(live.get("signal")),
            "vc_estimated": official_vc,
        },
        "challenger": {
            "model": "OLS rolling 90 + QQQ incremental residualizado",
            "return_estimated": challenger_ret,
            "signal": classify(challenger_ret),
            "vc_estimated": challenger_vc,
        },
        "qqq": {
            "return": qqq_ret,
            "residual": qqq_resid,
            "previous_close": qqq_prev,
            "current_price": qqq_current,
            "source": qqq_source,
            "residualized_against": BASE_FEATURES,
        },
        "comparison": {
            "same_signal": classify(challenger_ret) == str(live.get("signal")),
            "vc_difference": challenger_vc - official_vc,
            "return_difference_pp": (challenger_ret - official_ret) * 100.0,
        },
        "training": {
            "window": WINDOW,
            "n": int(len(train)),
            "start": train.iloc[0]["fecha"].date().isoformat(),
            "end": train.iloc[-1]["fecha"].date().isoformat(),
            "qqq_residualizer": {
                "intercept": float(beta_resid[0]),
                **{f: float(beta_resid[i + 1]) for i, f in enumerate(BASE_FEATURES)},
            },
        },
    }

    old = safe_json(OUT_PATH)
    if args.live_only and old.get("performance_backtest"):
        current["performance_backtest"] = old["performance_backtest"]
    else:
        current["performance_backtest"] = build_backtest(frame)

    shadow, shadow_metrics = update_shadow(current, sbs, str(latest.get("latest_sbs_date", "")))
    current["shadow_forward"] = shadow_metrics
    current["shadow_forward"]["ledger"] = "data/rolling90/qqq_incremental_shadow.csv"
    current["shadow_forward"]["rule"] = "Solo cuenta como prueba futura cuando la SBS publique el VC real de la fecha guardada."

    PUBLIC.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")

    assert current["challenger"]["signal"] in {"SUBE", "NEUTRO", "BAJA"}
    assert float(current["challenger"]["vc_estimated"]) > 0
    assert float(current["official"]["vc_estimated"]) > 0
    assert int(current["training"]["n"]) == WINDOW
    print(json.dumps(current, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
