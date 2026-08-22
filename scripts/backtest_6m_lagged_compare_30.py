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

TRAIN_WINDOW = 30
PRIMARY_LAG = 3
LAGS = [3, 4, 5]
ROLL_FEATURES = ["ret_SPY", "ret_EEM", "ret_EPU", "ret_MCHI", "ret_USD_PEN", "ret_QQQ"]
SIMPLE_FACTOR = "EPU"
THRESHOLD = 0.001


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
    raw = yf.download(
        "QQQ",
        start=(start - pd.Timedelta(days=20)).strftime("%Y-%m-%d"),
        end=(end + pd.Timedelta(days=5)).strftime("%Y-%m-%d"),
        auto_adjust=False,
        actions=False,
        progress=False,
        threads=False,
    )
    close = extract_close(raw, "QQQ")
    if close.empty:
        raise RuntimeError("No se pudo descargar QQQ")
    idx = pd.to_datetime(close.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    q = pd.DataFrame({"fecha": idx.normalize(), "QQQ": close.to_numpy(float)})
    q = q.sort_values("fecha").drop_duplicates("fecha", keep="last")
    q["ret_QQQ"] = q["QQQ"].pct_change(fill_method=None)
    return q.reset_index(drop=True)


def fit_ols(train: pd.DataFrame, features: list[str], target: str) -> np.ndarray:
    x = train[features].to_numpy(float)
    y = train[target].to_numpy(float)
    return np.linalg.lstsq(np.c_[np.ones(len(x)), x], y, rcond=None)[0]


def pred_ols(beta: np.ndarray, row: pd.Series, features: list[str]) -> float:
    return float(np.r_[1.0, row[features].to_numpy(float)] @ beta)


def classify(v: float) -> str:
    return "SUBE" if v > THRESHOLD else ("BAJA" if v < -THRESHOLD else "NEUTRO")


def metrics(d: pd.DataFrame, pred_col: str) -> dict:
    x = d.dropna(subset=[pred_col, "actual_vc"]).copy()
    if x.empty:
        return {"n": 0}
    err = x[pred_col] - x["actual_vc"]
    ape = err.abs() / x["actual_vc"] * 100.0
    actual_change = x["actual_vc"] / x["visible_base_vc"] - 1.0
    pred_change = x[pred_col] / x["visible_base_vc"] - 1.0
    return {
        "n": int(len(x)),
        "start": x["target_date"].min().date().isoformat(),
        "end": x["target_date"].max().date().isoformat(),
        "mae_vc": float(err.abs().mean()),
        "rmse_vc": float(np.sqrt(np.mean(err.to_numpy(float) ** 2))),
        "mape_pct": float(ape.mean()),
        "median_abs_pct": float(ape.median()),
        "p90_abs_pct": float(ape.quantile(0.90)),
        "bias_vc": float(err.mean()),
        "within_025_pct": float((ape <= 0.25).mean() * 100.0),
        "within_050_pct": float((ape <= 0.50).mean() * 100.0),
        "within_100_pct": float((ape <= 1.00).mean() * 100.0),
        "direction_accuracy_pct": float((np.sign(pred_change) == np.sign(actual_change)).mean() * 100.0),
        "mean_actual_move_pct": float(actual_change.abs().mean() * 100.0),
    }


def monthly_metrics(d: pd.DataFrame, pred_col: str) -> list[dict]:
    out = []
    x = d.dropna(subset=[pred_col, "actual_vc"]).copy()
    x["month"] = x["target_date"].dt.to_period("M").astype(str)
    for month, g in x.groupby("month"):
        m = metrics(g, pred_col)
        m["month"] = month
        out.append(m)
    return out


def build_simple_pairs(markets: pd.DataFrame, sbs: pd.DataFrame, qqq: pd.DataFrame) -> pd.DataFrame:
    levels = markets[["fecha", "SPY", "NEM", "FCX", "EPU", "MCHI", "EEM", "USD_PEN"]].copy()
    levels = levels.merge(qqq[["fecha", "QQQ"]], on="fecha", how="left")
    levels = levels.sort_values("fecha").dropna(subset=[SIMPLE_FACTOR]).reset_index(drop=True)
    right = sbs[["fecha", "valor_cuota"]].rename(columns={"fecha": "target_date", "valor_cuota": "target_vc"}).sort_values("target_date")
    pairs = pd.merge_asof(
        levels.rename(columns={"fecha": "market_date"}).sort_values("market_date"),
        right,
        left_on="market_date",
        right_on="target_date",
        direction="forward",
        allow_exact_matches=False,
    )
    return pairs.dropna(subset=["target_date", "target_vc", SIMPLE_FACTOR]).sort_values("target_date").drop_duplicates("target_date", keep="last").reset_index(drop=True)


def backtest_for_lag(markets: pd.DataFrame, sbs: pd.DataFrame, qqq: pd.DataFrame, lag: int) -> pd.DataFrame:
    s = sbs.copy()
    s["valor_cuota"] = pd.to_numeric(s["valor_cuota"], errors="coerce")
    s = s.dropna(subset=["valor_cuota"]).sort_values("fecha").drop_duplicates("fecha", keep="last").reset_index(drop=True)
    s["ret_target"] = s["valor_cuota"].pct_change(fill_method=None)

    mq = markets.merge(qqq[["fecha", "QQQ", "ret_QQQ"]], on="fecha", how="left")
    for c in ROLL_FEATURES[:-1]:
        mq[c] = pd.to_numeric(mq[c], errors="coerce")
    factor_rows = mq[["fecha", *ROLL_FEATURES]].dropna(subset=ROLL_FEATURES).sort_values("fecha").drop_duplicates("fecha", keep="last").reset_index(drop=True)
    common = s[["fecha", "valor_cuota", "ret_target"]].merge(factor_rows, on="fecha", how="inner")
    common = common.dropna(subset=["ret_target", *ROLL_FEATURES]).sort_values("fecha").drop_duplicates("fecha", keep="last").reset_index(drop=True)

    simple_pairs = build_simple_pairs(markets, s, qqq)
    latest = s["fecha"].max()
    start = (latest - pd.DateOffset(months=6)).normalize()

    rows = []
    # Se mide sobre sesiones completas comunes. Para cada objetivo se ocultan
    # exactamente 'lag' sesiones de VC; el VC de corte sí es visible.
    for i in range(lag, len(common)):
        target = pd.Timestamp(common.iloc[i]["fecha"]).normalize()
        if target < start or target > latest:
            continue
        cutoff = pd.Timestamp(common.iloc[i - lag]["fecha"]).normalize()
        base_vc = float(common.iloc[i - lag]["valor_cuota"])
        actual = float(common.iloc[i]["valor_cuota"])

        train_roll = common.loc[common["fecha"] <= cutoff].tail(TRAIN_WINDOW).copy()
        if len(train_roll) != TRAIN_WINDOW:
            continue
        beta_roll = fit_ols(train_roll, ROLL_FEATURES, "ret_target")
        hidden = factor_rows.loc[(factor_rows["fecha"] > cutoff) & (factor_rows["fecha"] <= target)].copy()
        if len(hidden) != lag or pd.Timestamp(hidden.iloc[-1]["fecha"]) != target:
            continue
        vc_roll = base_vc
        hidden_returns = []
        for _, hr in hidden.iterrows():
            rr = pred_ols(beta_roll, hr, ROLL_FEATURES)
            hidden_returns.append(rr)
            vc_roll *= 1.0 + rr

        # Regresión simple original: nivel VC objetivo contra EPU del cierre
        # inmediatamente anterior; entrenamiento solo con pares cuyo VC ya era visible.
        train_simple = simple_pairs.loc[simple_pairs["target_date"] <= cutoff].tail(TRAIN_WINDOW).copy()
        vc_simple = np.nan
        simple_market_date = pd.NaT
        simple_beta0 = np.nan
        simple_beta1 = np.nan
        if len(train_simple) == TRAIN_WINDOW:
            xs = train_simple[SIMPLE_FACTOR].to_numpy(float)
            ys = train_simple["target_vc"].to_numpy(float)
            b1, b0 = np.polyfit(xs, ys, 1)
            prior_level = markets.loc[(markets["fecha"] < target) & markets[SIMPLE_FACTOR].notna(), ["fecha", SIMPLE_FACTOR]].tail(1)
            if not prior_level.empty:
                simple_market_date = pd.Timestamp(prior_level.iloc[0]["fecha"])
                vc_simple = float(b0 + b1 * float(prior_level.iloc[0][SIMPLE_FACTOR]))
                simple_beta0 = float(b0)
                simple_beta1 = float(b1)

        rows.append({
            "lag_sessions": lag,
            "target_date": target,
            "visible_cutoff": cutoff,
            "visible_base_vc": base_vc,
            "actual_vc": actual,
            "rolling30_vc": float(vc_roll),
            "rolling30_return_from_base": float(vc_roll / base_vc - 1.0),
            "rolling30_hidden_returns": json.dumps(hidden_returns),
            "rolling30_train_start": train_roll.iloc[0]["fecha"],
            "rolling30_train_end": train_roll.iloc[-1]["fecha"],
            "rolling30_beta": json.dumps({k: float(v) for k, v in zip(["intercept", *ROLL_FEATURES], beta_roll)}),
            "simple30_epu_vc": None if pd.isna(vc_simple) else float(vc_simple),
            "simple30_market_date": simple_market_date,
            "simple30_train_start": train_simple.iloc[0]["target_date"] if len(train_simple) == TRAIN_WINDOW else pd.NaT,
            "simple30_train_end": train_simple.iloc[-1]["target_date"] if len(train_simple) == TRAIN_WINDOW else pd.NaT,
            "simple30_intercept": None if pd.isna(simple_beta0) else simple_beta0,
            "simple30_slope_epu": None if pd.isna(simple_beta1) else simple_beta1,
            "naive_last_visible_vc": base_vc,
        })

    out = pd.DataFrame(rows)
    for pred in ["rolling30_vc", "simple30_epu_vc", "naive_last_visible_vc"]:
        out[f"{pred}_error_pct"] = (out[pred] / out["actual_vc"] - 1.0) * 100.0
        out[f"{pred}_abs_error_pct"] = out[f"{pred}_error_pct"].abs()
    return out


def summarize(all_results: pd.DataFrame) -> dict:
    payload = {
        "generated_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "fund": "PROFUTURO Fondo 3",
        "period_rule": "últimos 6 meses respecto del último VC SBS real disponible",
        "primary_lag_sessions": PRIMARY_LAG,
        "lag_rule": "En cada fecha objetivo se ocultan las últimas N sesiones completas de VC. El modelo solo puede entrenar y anclarse en el VC del corte visible. Los VC ocultos se usan únicamente después para evaluar; nunca para recalibrar esa predicción.",
        "models": {
            "simple30_epu": "Regresión lineal simple de nivel: VC objetivo = intercepto + pendiente × cierre EPU anterior. Últimos 30 pares conocidos mercado t -> siguiente VC SBS. EPU es el factor simple que resultó mejor en el archivo de referencia de 30 días.",
            "rolling30_no_nem_fcx_qqq": "OLS multivariable sobre retorno VC; 30 últimas observaciones conocidas; variables SPY, EEM, EPU, MCHI, USD/PEN y QQQ; NEM/FCX excluidos. Para el horizonte ciego, beta se fija en el corte visible y se encadenan solo retornos de mercado de las sesiones ocultas.",
            "naive": "Último VC SBS visible, sin cambio; benchmark de no-modelo.",
        },
        "results_by_lag": {},
    }
    for lag in LAGS:
        d = all_results.loc[all_results["lag_sessions"] == lag].copy()
        payload["results_by_lag"][str(lag)] = {
            "date_start": d["target_date"].min().date().isoformat() if not d.empty else None,
            "date_end": d["target_date"].max().date().isoformat() if not d.empty else None,
            "rolling30": metrics(d, "rolling30_vc"),
            "simple30_epu": metrics(d, "simple30_epu_vc"),
            "naive": metrics(d, "naive_last_visible_vc"),
            "monthly_rolling30": monthly_metrics(d, "rolling30_vc"),
            "monthly_simple30_epu": monthly_metrics(d, "simple30_epu_vc"),
        }
    primary = all_results.loc[all_results["lag_sessions"] == PRIMARY_LAG].copy()
    if not primary.empty:
        p = primary.dropna(subset=["rolling30_vc", "simple30_epu_vc", "actual_vc"]).copy()
        p["winner"] = np.where(
            (p["rolling30_vc"] - p["actual_vc"]).abs() < (p["simple30_epu_vc"] - p["actual_vc"]).abs(),
            "rolling30",
            np.where(
                (p["rolling30_vc"] - p["actual_vc"]).abs() > (p["simple30_epu_vc"] - p["actual_vc"]).abs(),
                "simple30_epu",
                "tie",
            ),
        )
        payload["primary_pairwise"] = {
            "n": int(len(p)),
            "rolling30_wins": int((p["winner"] == "rolling30").sum()),
            "simple30_epu_wins": int((p["winner"] == "simple30_epu").sum()),
            "ties": int((p["winner"] == "tie").sum()),
            "rolling30_mean_abs_error_advantage_pct_points": float(p["simple30_epu_vc_abs_error_pct"].mean() - p["rolling30_vc_abs_error_pct"].mean()),
        }
        worst_roll = p.nlargest(10, "rolling30_vc_abs_error_pct")[["target_date", "visible_cutoff", "actual_vc", "rolling30_vc", "rolling30_vc_error_pct"]]
        worst_simple = p.nlargest(10, "simple30_epu_vc_abs_error_pct")[["target_date", "visible_cutoff", "actual_vc", "simple30_epu_vc", "simple30_epu_vc_error_pct"]]
        payload["worst_10_primary"] = {
            "rolling30": worst_roll.assign(target_date=worst_roll["target_date"].dt.strftime("%Y-%m-%d"), visible_cutoff=worst_roll["visible_cutoff"].dt.strftime("%Y-%m-%d")).to_dict(orient="records"),
            "simple30_epu": worst_simple.assign(target_date=worst_simple["target_date"].dt.strftime("%Y-%m-%d"), visible_cutoff=worst_simple["visible_cutoff"].dt.strftime("%Y-%m-%d")).to_dict(orient="records"),
        }
    return payload


def main() -> None:
    markets = read_csv(DATA / "markets.csv")
    sbs = read_csv(DATA / "sbs_profuturo_f3.csv")
    qqq = load_qqq(markets["fecha"].min(), max(markets["fecha"].max(), sbs["fecha"].max()))
    all_results = pd.concat([backtest_for_lag(markets, sbs, qqq, lag) for lag in LAGS], ignore_index=True)
    payload = summarize(all_results)

    ANALYSIS.mkdir(parents=True, exist_ok=True)
    PUBLIC.mkdir(parents=True, exist_ok=True)
    out_csv = ANALYSIS / "backtest_6m_lagged_compare_30.csv"
    out_json = ANALYSIS / "backtest_6m_lagged_compare_30.json"
    pub_json = PUBLIC / "backtest_6m_lagged_compare_30.json"

    save = all_results.copy()
    for c in ["target_date", "visible_cutoff", "rolling30_train_start", "rolling30_train_end", "simple30_market_date", "simple30_train_start", "simple30_train_end"]:
        if c in save.columns:
            save[c] = pd.to_datetime(save[c], errors="coerce").dt.strftime("%Y-%m-%d")
    save.to_csv(out_csv, index=False)
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    out_json.write_text(text, encoding="utf-8")
    pub_json.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
