from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "rolling90"
PUBLIC = ROOT / "public" / "data"
OUT = PUBLIC / "rolling30_no_nem_fcx_qqq.json"

TRAIN_WINDOW = 30
THRESHOLD = 0.001
FEATURES = [
    "ret_SPY",
    "ret_EEM",
    "ret_EPU",
    "ret_MCHI",
    "ret_USD_PEN",
    "ret_QQQ",
]


def classify(v: float) -> str:
    if v > THRESHOLD:
        return "SUBE"
    if v < -THRESHOLD:
        return "BAJA"
    return "NEUTRO"


def read_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce").dt.normalize()
    return df.dropna(subset=["fecha"]).sort_values("fecha").drop_duplicates("fecha", keep="last").reset_index(drop=True)


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
    raise RuntimeError("Yahoo no devolvió Close utilizable para QQQ")


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
        raise RuntimeError("No se pudo obtener QQQ")
    idx = pd.to_datetime(close.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    q = pd.DataFrame({"fecha": idx.normalize(), "QQQ": close.to_numpy(float)})
    q = q.sort_values("fecha").drop_duplicates("fecha", keep="last")
    q["ret_QQQ"] = q["QQQ"].pct_change(fill_method=None)
    return q.reset_index(drop=True)


def fit(train: pd.DataFrame) -> tuple[np.ndarray, dict[str, float]]:
    x = train[FEATURES].to_numpy(float)
    y = train["ret_target"].to_numpy(float)
    beta = np.linalg.lstsq(np.c_[np.ones(len(x)), x], y, rcond=None)[0]
    return beta, {k: float(v) for k, v in zip(["intercept", *FEATURES], beta)}


def predict(beta: np.ndarray, values: dict[str, float]) -> float:
    return float(beta[0] + sum(float(beta[i + 1]) * float(values[f]) for i, f in enumerate(FEATURES)))


def train_metrics(train: pd.DataFrame, beta: np.ndarray) -> dict:
    x = train[FEATURES].to_numpy(float)
    y = train["ret_target"].to_numpy(float)
    fitted = np.c_[np.ones(len(x)), x] @ beta
    err = fitted - y
    ss_res = float(np.sum(err ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else None
    n, p = len(y), len(FEATURES)
    r2_adj = None if r2 is None or n <= p + 1 else 1.0 - (1.0 - r2) * (n - 1) / (n - p - 1)
    return {
        "n": n,
        "r2": r2,
        "r2_adj": r2_adj,
        "mae_return": float(np.mean(np.abs(err))),
        "rmse_return": float(np.sqrt(np.mean(err ** 2))),
    }


def main() -> None:
    markets = read_csv(DATA / "markets.csv")
    sbs = read_csv(DATA / "sbs_profuturo_f3.csv")
    sbs["valor_cuota"] = pd.to_numeric(sbs["valor_cuota"], errors="coerce")
    sbs = sbs.dropna(subset=["valor_cuota"]).copy()
    sbs["ret_target"] = sbs["valor_cuota"].pct_change(fill_method=None)

    live = json.loads((PUBLIC / "live_market.json").read_text(encoding="utf-8"))
    signal_date = pd.Timestamp(str(live["signal_date"])).normalize()
    qqq = download_qqq(markets["fecha"].min(), signal_date)

    mq = markets.merge(qqq[["fecha", "ret_QQQ"]], on="fecha", how="left")
    frame = sbs[["fecha", "valor_cuota", "ret_target"]].merge(
        mq[["fecha", "ret_SPY", "ret_EEM", "ret_EPU", "ret_MCHI", "ret_USD_PEN", "ret_QQQ"]],
        on="fecha",
        how="inner",
    )
    frame = frame.dropna(subset=["ret_target", "valor_cuota", *FEATURES]).sort_values("fecha").drop_duplicates("fecha", keep="last").reset_index(drop=True)

    latest_train = frame.loc[frame["fecha"] < signal_date].tail(TRAIN_WINDOW).copy().reset_index(drop=True)
    if len(latest_train) != TRAIN_WINDOW:
        raise RuntimeError(f"Entrenamiento rolling30 incompleto: {len(latest_train)}")
    beta_latest, coeff_latest = fit(latest_train)

    live_assets = {str(x.get("serie")): x for x in live.get("assets", [])}
    live_values: dict[str, float] = {}
    for feature, serie in {
        "ret_SPY": "SPY",
        "ret_EEM": "EEM",
        "ret_EPU": "EPU",
        "ret_MCHI": "MCHI",
        "ret_USD_PEN": "USD_PEN",
    }.items():
        row = live_assets.get(serie, {})
        raw = row.get("retorno_modelo")
        if raw is None:
            raw = row.get("retorno")
        val = pd.to_numeric(pd.Series([raw]), errors="coerce").iloc[0]
        if pd.isna(val):
            raise RuntimeError(f"Falta {feature} en live_market")
        live_values[feature] = float(val)

    qsame = qqq.loc[qqq["fecha"].eq(signal_date)]
    if qsame.empty:
        raise RuntimeError(f"QQQ no tiene cierre para {signal_date.date()}")
    qprev = qqq.loc[qqq["fecha"] < signal_date].tail(1)
    if qprev.empty:
        raise RuntimeError("QQQ sin cierre previo")
    qret = float(qsame.iloc[-1]["QQQ"] / qprev.iloc[-1]["QQQ"] - 1.0)
    live_values["ret_QQQ"] = qret

    # Predicciones 19/20/21 siguiendo el comportamiento de un rolling real:
    # cada fecha recalibra con las últimas 30 observaciones SBS disponibles antes de esa fecha.
    dates = [pd.Timestamp("2026-08-19"), pd.Timestamp("2026-08-20"), signal_date]
    rows = []
    prev_est: float | None = None
    for d in dates:
        train = frame.loc[frame["fecha"] < d].tail(TRAIN_WINDOW).copy().reset_index(drop=True)
        if len(train) != TRAIN_WINDOW:
            raise RuntimeError(f"Train insuficiente para {d.date()}: {len(train)}")
        beta, coeff = fit(train)

        if d == signal_date:
            values = dict(live_values)
            factor_source = "live_market + QQQ Yahoo cierre"
        else:
            same = mq.loc[mq["fecha"].eq(d)]
            if same.empty:
                raise RuntimeError(f"Falta mercado para {d.date()}")
            r = same.iloc[-1]
            values = {f: float(r[f]) for f in FEATURES}
            factor_source = "markets.csv + QQQ Yahoo"

        ret = predict(beta, values)
        prior_sbs = sbs.loc[sbs["fecha"] < d].sort_values("fecha").tail(1)
        if prior_sbs.empty:
            raise RuntimeError(f"Falta SBS previo para {d.date()}")
        prior_date = pd.Timestamp(prior_sbs.iloc[-1]["fecha"]).normalize()
        prior_vc = float(prior_sbs.iloc[-1]["valor_cuota"])

        # Si el SBS del día inmediatamente anterior no existe, encadenamos el
        # estimado rolling30 del día previo. Para 21/08, hoy ocurre con 20/08.
        use_estimated_base = prev_est is not None and prior_date < d - pd.Timedelta(days=1) and d == signal_date
        base_vc = float(prev_est) if use_estimated_base else prior_vc
        base_date = "estimado previo" if use_estimated_base else prior_date.date().isoformat()
        vc = base_vc * (1.0 + ret)
        prev_est = vc
        actual = sbs.loc[sbs["fecha"].eq(d), "valor_cuota"]
        actual_vc = None if actual.empty else float(actual.iloc[-1])
        rows.append({
            "fecha": d.date().isoformat(),
            "train_start": train.iloc[0]["fecha"].date().isoformat(),
            "train_end": train.iloc[-1]["fecha"].date().isoformat(),
            "train_n": len(train),
            "base_date": base_date,
            "base_vc": base_vc,
            "return_estimated": ret,
            "signal": classify(ret),
            "vc_estimated": vc,
            "actual_vc_sbs": actual_vc,
            "error_pct": None if actual_vc is None else (vc / actual_vc - 1.0) * 100.0,
            "factor_source": factor_source,
            "coefficients": coeff,
        })

    official = json.loads((PUBLIC / "live_market.json").read_text(encoding="utf-8"))
    reduced = json.loads((PUBLIC / "reduced_6030_challenger.json").read_text(encoding="utf-8"))
    current = rows[-1]
    payload = {
        "generated_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "fund": "PROFUTURO Fondo 3",
        "model": "OLS rolling 30 · sin NEM ni FCX · mantiene QQQ",
        "rolling": True,
        "train_window": TRAIN_WINDOW,
        "freeze_horizon": None,
        "features": FEATURES,
        "target": "retorno diario del VC SBS",
        "latest_training": {
            "start": latest_train.iloc[0]["fecha"].date().isoformat(),
            "end": latest_train.iloc[-1]["fecha"].date().isoformat(),
            "n": len(latest_train),
            "coefficients": coeff_latest,
            "metrics_in_sample": train_metrics(latest_train, beta_latest),
        },
        "current": current,
        "recent": rows,
        "comparison_current": {
            "rolling90_official": {
                "return_estimated": float(official["return_estimated"]),
                "vc_estimated": float(official["vc_estimated"]),
            },
            "challenger_60_30_no_nem_fcx_qqq": {
                "return_estimated": float(reduced["challenger"]["return_estimated"]),
                "vc_estimated": float(reduced["challenger"]["vc_estimated"]),
            },
            "rolling30_no_nem_fcx_qqq": {
                "return_estimated": float(current["return_estimated"]),
                "vc_estimated": float(current["vc_estimated"]),
            },
        },
        "note": "Experimental. Rolling 30 significa recalibrar OLS con las últimas 30 observaciones válidas; no congela beta por 30 sesiones. NEM y FCX están excluidos; QQQ se mantiene.",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
