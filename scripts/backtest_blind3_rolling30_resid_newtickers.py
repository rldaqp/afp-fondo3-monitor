from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "rolling90"
ANALYSIS = ROOT / "analysis"
PUBLIC = ROOT / "public" / "data"
ALT_PATH = ROOT / "data" / "analysis" / "googlefinance_alt_6030_returns_20260303_20260820.csv"

TRAIN = 30
LAGS = [3, 4, 5]
PRIMARY_LAG = 3
BASE = ["ret_SPY", "ret_EEM", "ret_EPU", "ret_MCHI", "ret_USD_PEN"]
RAW = [*BASE, "ret_QQQ"]
RESID = [*BASE, "ret_QQQ_resid"]
ALT = ["ret_.INX", "ret_CPER", "ret_EEM_alt", "ret_NDX", "ret_SPBLSCUP", "ret_USD_PEN_alt"]


def read_csv(path: Path) -> pd.DataFrame:
    d = pd.read_csv(path)
    d["fecha"] = pd.to_datetime(d["fecha"], errors="coerce").dt.normalize()
    return d.dropna(subset=["fecha"]).sort_values("fecha").drop_duplicates("fecha", keep="last").reset_index(drop=True)


def extract_close(raw: pd.DataFrame, ticker: str) -> pd.Series:
    if raw.empty:
        return pd.Series(dtype=float)
    if isinstance(raw.columns, pd.MultiIndex):
        for key in [("Close", ticker), (ticker, "Close")]:
            if key in raw.columns:
                return pd.to_numeric(raw[key], errors="coerce").dropna()
        if "Close" in raw.columns.get_level_values(0):
            b = raw.xs("Close", axis=1, level=0)
            if ticker in b.columns:
                return pd.to_numeric(b[ticker], errors="coerce").dropna()
    if "Close" in raw.columns:
        return pd.to_numeric(raw["Close"], errors="coerce").dropna()
    return pd.Series(dtype=float)


def load_qqq(start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    raw = yf.download("QQQ", start=(start-pd.Timedelta(days=20)).strftime("%Y-%m-%d"), end=(end+pd.Timedelta(days=5)).strftime("%Y-%m-%d"), auto_adjust=False, actions=False, progress=False, threads=False)
    s = extract_close(raw, "QQQ")
    if s.empty:
        raise RuntimeError("No se pudo descargar QQQ")
    idx = pd.to_datetime(s.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    q = pd.DataFrame({"fecha": idx.normalize(), "QQQ": s.to_numpy(float)})
    q = q.sort_values("fecha").drop_duplicates("fecha", keep="last")
    q["ret_QQQ"] = q["QQQ"].pct_change(fill_method=None)
    return q.reset_index(drop=True)


def fit(train: pd.DataFrame, features: list[str], target: str = "ret_target") -> np.ndarray:
    X = train[features].to_numpy(float)
    y = train[target].to_numpy(float)
    return np.linalg.lstsq(np.c_[np.ones(len(X)), X], y, rcond=None)[0]


def pred(beta: np.ndarray, row: pd.Series, features: list[str]) -> float:
    return float(np.r_[1.0, row[features].to_numpy(float)] @ beta)


def residualize_qqq(train: pd.DataFrame) -> tuple[pd.DataFrame, np.ndarray]:
    qbeta = fit(train, BASE, target="ret_QQQ")
    out = train.copy()
    out["ret_QQQ_resid"] = out["ret_QQQ"].to_numpy(float) - (np.c_[np.ones(len(out)), out[BASE].to_numpy(float)] @ qbeta)
    return out, qbeta


def metrics(d: pd.DataFrame, col: str) -> dict:
    x = d.dropna(subset=[col, "actual_vc"]).copy()
    if x.empty:
        return {"n": 0}
    err = x[col] - x["actual_vc"]
    ape = err.abs() / x["actual_vc"] * 100.0
    actual_move = x["actual_vc"] / x["visible_base_vc"] - 1.0
    pred_move = x[col] / x["visible_base_vc"] - 1.0
    return {
        "n": int(len(x)),
        "start": x["target_date"].min().date().isoformat(),
        "end": x["target_date"].max().date().isoformat(),
        "mae_vc": float(err.abs().mean()),
        "rmse_vc": float(np.sqrt(np.mean(err.to_numpy(float) ** 2))),
        "mape_pct": float(ape.mean()),
        "median_abs_pct": float(ape.median()),
        "p90_abs_pct": float(ape.quantile(.90)),
        "bias_vc": float(err.mean()),
        "within_025_pct": float((ape <= .25).mean() * 100),
        "within_050_pct": float((ape <= .50).mean() * 100),
        "within_100_pct": float((ape <= 1.0).mean() * 100),
        "direction_accuracy_pct": float((np.sign(actual_move) == np.sign(pred_move)).mean() * 100),
    }


def monthly(d: pd.DataFrame, col: str) -> list[dict]:
    x = d.dropna(subset=[col, "actual_vc"]).copy()
    x["month"] = x["target_date"].dt.to_period("M").astype(str)
    out = []
    for m, g in x.groupby("month"):
        z = metrics(g, col); z["month"] = m; out.append(z)
    return out


def build_frames():
    markets = read_csv(DATA / "markets.csv")
    sbs = read_csv(DATA / "sbs_profuturo_f3.csv")
    sbs["valor_cuota"] = pd.to_numeric(sbs["valor_cuota"], errors="coerce")
    sbs = sbs.dropna(subset=["valor_cuota"]).copy()
    sbs["ret_target"] = sbs["valor_cuota"].pct_change(fill_method=None)
    qqq = load_qqq(markets["fecha"].min(), sbs["fecha"].max())

    mq = markets.merge(qqq[["fecha", "ret_QQQ"]], on="fecha", how="left")
    base_factors = mq[["fecha", *RAW]].copy()
    for c in RAW:
        base_factors[c] = pd.to_numeric(base_factors[c], errors="coerce")
    base_factors = base_factors.dropna(subset=RAW).sort_values("fecha").drop_duplicates("fecha", keep="last")
    base_common = sbs[["fecha", "valor_cuota", "ret_target"]].merge(base_factors, on="fecha", how="inner")
    base_common = base_common.dropna(subset=["ret_target", *RAW]).sort_values("fecha").reset_index(drop=True)

    alt = read_csv(ALT_PATH).rename(columns={"ret_EEM":"ret_EEM_alt", "ret_USD_PEN":"ret_USD_PEN_alt"})
    for c in ALT:
        alt[c] = pd.to_numeric(alt[c], errors="coerce")
    alt = alt[["fecha", *ALT]].dropna(subset=ALT)
    all_factors = base_factors.merge(alt, on="fecha", how="inner").dropna(subset=[*RAW, *ALT]).sort_values("fecha").reset_index(drop=True)
    all_common = sbs[["fecha", "valor_cuota", "ret_target"]].merge(all_factors, on="fecha", how="inner")
    all_common = all_common.dropna(subset=["ret_target", *RAW, *ALT]).sort_values("fecha").reset_index(drop=True)
    return sbs, base_factors, base_common, all_factors, all_common


def backtest(panel: pd.DataFrame, factors: pd.DataFrame, lag: int, include_alt: bool) -> pd.DataFrame:
    latest = panel["fecha"].max()
    sixm_start = (latest - pd.DateOffset(months=6)).normalize()
    rows = []
    for i in range(lag, len(panel)):
        target = pd.Timestamp(panel.iloc[i]["fecha"]).normalize()
        if target < sixm_start:
            continue
        cutoff = pd.Timestamp(panel.iloc[i-lag]["fecha"]).normalize()
        base_vc = float(panel.iloc[i-lag]["valor_cuota"])
        actual = float(panel.iloc[i]["valor_cuota"])
        train = panel.loc[panel["fecha"] <= cutoff].tail(TRAIN).copy()
        if len(train) != TRAIN:
            continue
        hidden = factors.loc[(factors["fecha"] > cutoff) & (factors["fecha"] <= target)].copy()
        if len(hidden) != lag or pd.Timestamp(hidden.iloc[-1]["fecha"]) != target:
            continue

        raw_beta = fit(train, RAW)
        vc_raw = base_vc
        for _, r in hidden.iterrows():
            vc_raw *= 1.0 + pred(raw_beta, r, RAW)

        train_resid, qbeta = residualize_qqq(train)
        resid_beta = fit(train_resid, RESID)
        vc_resid = base_vc
        resid_rets = []
        q_resids = []
        for _, r0 in hidden.iterrows():
            r = r0.copy()
            qexp = float(np.r_[1.0, r[BASE].to_numpy(float)] @ qbeta)
            r["ret_QQQ_resid"] = float(r["ret_QQQ"] - qexp)
            rr = pred(resid_beta, r, RESID)
            vc_resid *= 1.0 + rr
            resid_rets.append(rr); q_resids.append(float(r["ret_QQQ_resid"]))

        vc_alt = np.nan
        if include_alt:
            alt_beta = fit(train, ALT)
            vc_alt = base_vc
            for _, r in hidden.iterrows():
                vc_alt *= 1.0 + pred(alt_beta, r, ALT)

        rows.append({
            "lag_sessions": lag,
            "target_date": target,
            "visible_cutoff": cutoff,
            "visible_base_vc": base_vc,
            "actual_vc": actual,
            "raw_qqq_vc": float(vc_raw),
            "resid_qqq_vc": float(vc_resid),
            "new_tickers_vc": None if pd.isna(vc_alt) else float(vc_alt),
            "resid_qqq_hidden_returns": json.dumps(resid_rets),
            "qqq_hidden_residuals": json.dumps(q_resids),
            "train_start": train.iloc[0]["fecha"],
            "train_end": train.iloc[-1]["fecha"],
        })
    d = pd.DataFrame(rows)
    for c in ["raw_qqq_vc", "resid_qqq_vc", "new_tickers_vc"]:
        if c in d.columns:
            d[c+"_error_pct"] = (d[c] / d["actual_vc"] - 1.0) * 100.0
            d[c+"_abs_error_pct"] = d[c+"_error_pct"].abs()
    return d


def pairwise(d: pd.DataFrame, cols: list[str]) -> dict:
    x = d.dropna(subset=[*cols, "actual_vc"]).copy()
    wins = {c:0 for c in cols}
    ties = 0
    for _, r in x.iterrows():
        errs = {c:abs(float(r[c])-float(r["actual_vc"])) for c in cols}
        m = min(errs.values())
        ww = [c for c,v in errs.items() if abs(v-m) < 1e-12]
        if len(ww)==1: wins[ww[0]] += 1
        else: ties += 1
    return {"n":int(len(x)), "wins":wins, "ties":ties}


def main():
    sbs, base_factors, base_common, all_factors, all_common = build_frames()
    full = pd.concat([backtest(base_common, base_factors, lag, False) for lag in LAGS], ignore_index=True)
    common = pd.concat([backtest(all_common, all_factors, lag, True) for lag in LAGS], ignore_index=True)

    payload = {
        "generated_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "fund":"PROFUTURO Fondo 3",
        "train_window":TRAIN,
        "primary_lag":PRIMARY_LAG,
        "blind_rule":"Para cada objetivo se ocultan exactamente N VC SBS. El modelo solo ve y usa el VC del corte visible; beta y la regresión auxiliar de QQQ se estiman únicamente con datos hasta ese corte. Durante los N días ocultos se encadenan predicciones usando mercado conocido, sin reanclar ni recalibrar con los VC ocultos. Los VC reales se revelan solo para medir el error.",
        "models":{
            "raw_qqq":"Rolling 30: SPY, EEM, EPU, MCHI, USD/PEN y QQQ bruto; sin NEM/FCX.",
            "resid_qqq":"Rolling 30: SPY, EEM, EPU, MCHI, USD/PEN + QQQ residualizado contra esos cinco factores dentro de la misma ventana de 30. La regresión de residualización también queda congelada durante el bloque ciego.",
            "new_tickers":"Rolling 30: .INX, CPER, EEM, NDX, SPBLSCUP y USD/PEN, usando los retornos exactos guardados de Google Finance.",
        },
        "data_note":"El histórico exacto de nuevos tickers disponible en el repositorio empieza 2026-03-03. Por eso su comparación justa requiere primero 30 observaciones de entrenamiento y tiene un tramo efectivo menor que seis meses. El QQQ residual sí se evalúa en todo el tramo de seis meses disponible.",
        "full_six_month_residual":{},
        "common_exact_comparison":{},
    }
    for lag in LAGS:
        f = full.loc[full["lag_sessions"]==lag].copy()
        c = common.loc[common["lag_sessions"]==lag].copy()
        payload["full_six_month_residual"][str(lag)] = {
            "raw_qqq":metrics(f,"raw_qqq_vc"),
            "resid_qqq":metrics(f,"resid_qqq_vc"),
            "pairwise":pairwise(f,["raw_qqq_vc","resid_qqq_vc"]),
            "monthly_resid_qqq":monthly(f,"resid_qqq_vc"),
        }
        payload["common_exact_comparison"][str(lag)] = {
            "date_start": None if c.empty else c["target_date"].min().date().isoformat(),
            "date_end": None if c.empty else c["target_date"].max().date().isoformat(),
            "raw_qqq":metrics(c,"raw_qqq_vc"),
            "resid_qqq":metrics(c,"resid_qqq_vc"),
            "new_tickers":metrics(c,"new_tickers_vc"),
            "pairwise":pairwise(c,["raw_qqq_vc","resid_qqq_vc","new_tickers_vc"]),
            "monthly_resid_qqq":monthly(c,"resid_qqq_vc"),
            "monthly_new_tickers":monthly(c,"new_tickers_vc"),
        }

    p = common.loc[common["lag_sessions"]==PRIMARY_LAG].dropna(subset=["resid_qqq_vc","new_tickers_vc"]).copy()
    payload["latest_primary_rows"] = p.tail(12)[["target_date","visible_cutoff","visible_base_vc","actual_vc","raw_qqq_vc","resid_qqq_vc","new_tickers_vc","raw_qqq_vc_error_pct","resid_qqq_vc_error_pct","new_tickers_vc_error_pct"]].assign(target_date=lambda x:x.target_date.dt.strftime("%Y-%m-%d"), visible_cutoff=lambda x:x.visible_cutoff.dt.strftime("%Y-%m-%d")).to_dict(orient="records")
    payload["worst_primary"] = {
        "resid_qqq": p.nlargest(8,"resid_qqq_vc_abs_error_pct")[["target_date","visible_cutoff","actual_vc","resid_qqq_vc","resid_qqq_vc_error_pct"]].assign(target_date=lambda x:x.target_date.dt.strftime("%Y-%m-%d"), visible_cutoff=lambda x:x.visible_cutoff.dt.strftime("%Y-%m-%d")).to_dict(orient="records"),
        "new_tickers": p.nlargest(8,"new_tickers_vc_abs_error_pct")[["target_date","visible_cutoff","actual_vc","new_tickers_vc","new_tickers_vc_error_pct"]].assign(target_date=lambda x:x.target_date.dt.strftime("%Y-%m-%d"), visible_cutoff=lambda x:x.visible_cutoff.dt.strftime("%Y-%m-%d")).to_dict(orient="records"),
    }

    ANALYSIS.mkdir(parents=True, exist_ok=True); PUBLIC.mkdir(parents=True, exist_ok=True)
    for name, df in [("full",full),("common",common)]:
        z=df.copy()
        for col in ["target_date","visible_cutoff","train_start","train_end"]:
            if col in z.columns: z[col]=pd.to_datetime(z[col],errors="coerce").dt.strftime("%Y-%m-%d")
        z.to_csv(ANALYSIS/f"backtest_blind3_rolling30_{name}.csv",index=False)
    text=json.dumps(payload,ensure_ascii=False,indent=2)
    (ANALYSIS/"backtest_blind3_rolling30_resid_newtickers.json").write_text(text,encoding="utf-8")
    (PUBLIC/"backtest_blind3_rolling30_resid_newtickers.json").write_text(text,encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
