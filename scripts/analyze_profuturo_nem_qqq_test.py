from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "rolling90"
OUT = ROOT / "analysis" / "nem_qqq_profuturo_test.json"
PAIR_OUT = ROOT / "analysis" / "nem_qqq_profuturo_predictions.csv"
TRAIN_WINDOW = 90
THRESHOLD = 0.001
BASE = ["ret_SPY", "ret_EEM", "ret_EPU", "ret_MCHI", "ret_NEM", "ret_FCX", "ret_USD_PEN"]
NO_NEM = [f for f in BASE if f != "ret_NEM"]


def read_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce")
    return df.dropna(subset=["fecha"]).sort_values("fecha").reset_index(drop=True)


def classify(x: float) -> str:
    if x > THRESHOLD:
        return "SUBE"
    if x < -THRESHOLD:
        return "BAJA"
    return "NEUTRO"


def extract_close(raw: pd.DataFrame, ticker: str) -> pd.Series:
    if isinstance(raw.columns, pd.MultiIndex):
        for key in [("Close", ticker), (ticker, "Close")]:
            if key in raw.columns:
                return pd.to_numeric(raw[key], errors="coerce")
        cols = [c for c in raw.columns if "Close" in c]
        if cols:
            return pd.to_numeric(raw[cols[0]], errors="coerce")
    if "Close" in raw.columns:
        return pd.to_numeric(raw["Close"], errors="coerce")
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
    close = extract_close(raw, "QQQ").dropna()
    if close.empty:
        raise RuntimeError("No se pudo descargar QQQ")
    idx = pd.to_datetime(close.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    out = pd.DataFrame({"fecha": idx.normalize(), "QQQ": close.to_numpy(float)})
    out = out.sort_values("fecha").drop_duplicates("fecha", keep="last")
    out["ret_QQQ"] = out["QQQ"].pct_change(fill_method=None)
    return out[["fecha", "QQQ", "ret_QQQ"]]


def ols_beta(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    return np.linalg.lstsq(np.c_[np.ones(len(x)), x], y, rcond=None)[0]


def predict_ols(train: pd.DataFrame, row: pd.Series, features: list[str]) -> tuple[float, np.ndarray]:
    x = train[features].to_numpy(float)
    y = train["ret_target"].to_numpy(float)
    beta = ols_beta(x, y)
    pred = float(np.r_[1.0, row[features].to_numpy(float)] @ beta)
    return pred, beta


def predict_with_qqq_residual(train: pd.DataFrame, row: pd.Series, features: list[str]) -> tuple[float, float, float]:
    x = train[features].to_numpy(float)
    q = train["ret_QQQ"].to_numpy(float)
    q_beta = ols_beta(x, q)
    q_hat_train = np.c_[np.ones(len(x)), x] @ q_beta
    q_resid_train = q - q_hat_train
    current_x = row[features].to_numpy(float)
    q_hat_now = float(np.r_[1.0, current_x] @ q_beta)
    q_resid_now = float(row["ret_QQQ"] - q_hat_now)

    design = np.c_[x, q_resid_train]
    y = train["ret_target"].to_numpy(float)
    beta = ols_beta(design, y)
    pred = float(np.r_[1.0, current_x, q_resid_now] @ beta)
    return pred, q_resid_now, float(beta[-1])


def metrics(df: pd.DataFrame, col: str) -> dict:
    p = df[col].to_numpy(float)
    y = df["actual"].to_numpy(float)
    err = p - y
    pred_class = np.array([classify(v) for v in p])
    actual_class = np.array([classify(v) for v in y])
    return {
        "n": int(len(df)),
        "mae": float(np.mean(np.abs(err))),
        "rmse": float(np.sqrt(np.mean(err ** 2))),
        "direction_accuracy": float(np.mean(pred_class == actual_class)),
    }


def compare_slice(df: pd.DataFrame) -> dict:
    cols = ["actual_ols", "sin_nem", "actual_qqq_inc", "sin_nem_qqq_inc"]
    out = {c: metrics(df, c) for c in cols}
    base_mae = out["actual_ols"]["mae"]
    base_acc = out["actual_ols"]["direction_accuracy"]
    for c in cols:
        out[c]["mae_change_vs_actual_pct"] = float((out[c]["mae"] / base_mae - 1.0) * 100.0)
        out[c]["direction_delta_pp_vs_actual"] = float((out[c]["direction_accuracy"] - base_acc) * 100.0)
    return {
        "models": out,
        "best_mae": min(out, key=lambda k: out[k]["mae"]),
        "best_direction": max(out, key=lambda k: out[k]["direction_accuracy"]),
    }


def rolling_summary(pred: pd.DataFrame, horizon: int, challenger: str) -> dict:
    rows = []
    for end in range(horizon, len(pred) + 1):
        s = pred.iloc[end-horizon:end]
        a = metrics(s, "actual_ols")
        c = metrics(s, challenger)
        rows.append({
            "end": s.iloc[-1]["fecha"],
            "mae_improvement_pct": (1.0 - c["mae"] / a["mae"]) * 100.0,
            "direction_delta_pp": (c["direction_accuracy"] - a["direction_accuracy"]) * 100.0,
        })
    rdf = pd.DataFrame(rows)
    latest = rdf.iloc[-1]
    # Current consecutive streak of positive MAE improvement.
    mask = rdf["mae_improvement_pct"] > 0
    streak = 0
    for v in mask.iloc[::-1]:
        if not v:
            break
        streak += 1
    start = None
    if streak:
        start = rdf.iloc[len(rdf)-streak]["end"].strftime("%Y-%m-%d")
    return {
        "n_windows": int(len(rdf)),
        "share_windows_lower_mae": float((rdf["mae_improvement_pct"] > 0).mean()),
        "share_windows_better_direction": float((rdf["direction_delta_pp"] > 0).mean()),
        "median_mae_improvement_pct": float(rdf["mae_improvement_pct"].median()),
        "latest_mae_improvement_pct": float(latest["mae_improvement_pct"]),
        "latest_direction_delta_pp": float(latest["direction_delta_pp"]),
        "current_positive_mae_streak_windows": int(streak),
        "current_positive_mae_streak_start_end_date": start,
        "min_mae_improvement_pct": float(rdf["mae_improvement_pct"].min()),
        "max_mae_improvement_pct": float(rdf["mae_improvement_pct"].max()),
    }


def regime_compare(pred: pd.DataFrame, mask: pd.Series) -> dict:
    s = pred.loc[mask].copy()
    if len(s) < 5:
        return {"n": int(len(s))}
    a = metrics(s, "actual_ols")
    n = metrics(s, "sin_nem")
    q = metrics(s, "sin_nem_qqq_inc")
    return {
        "n": int(len(s)),
        "sin_nem_mae_improvement_pct": float((1 - n["mae"] / a["mae"]) * 100),
        "sin_nem_direction_delta_pp": float((n["direction_accuracy"] - a["direction_accuracy"]) * 100),
        "sin_nem_qqq_mae_improvement_pct": float((1 - q["mae"] / a["mae"]) * 100),
        "sin_nem_qqq_direction_delta_pp": float((q["direction_accuracy"] - a["direction_accuracy"]) * 100),
    }


def main() -> None:
    markets = read_csv(DATA / "markets.csv")
    sbs = read_csv(DATA / "sbs_profuturo_f3.csv")
    sbs["valor_cuota"] = pd.to_numeric(sbs["valor_cuota"], errors="coerce")
    sbs = sbs.dropna(subset=["valor_cuota"]).drop_duplicates("fecha", keep="last")
    sbs["ret_target"] = sbs["valor_cuota"].pct_change(fill_method=None)
    qqq = download_qqq(markets["fecha"].min(), markets["fecha"].max())
    markets = markets.merge(qqq, on="fecha", how="left")

    frame = sbs[["fecha", "ret_target"]].merge(markets, on="fecha", how="inner")
    frame = frame.loc[frame["fecha"] >= pd.Timestamp("2025-01-01")]
    frame = frame.dropna(subset=["ret_target", "ret_QQQ", *BASE]).sort_values("fecha").drop_duplicates("fecha", keep="last").reset_index(drop=True)
    if len(frame) <= TRAIN_WINDOW + 180:
        raise RuntimeError(f"Filas insuficientes: {len(frame)}")

    rows = []
    for i in range(TRAIN_WINDOW, len(frame)):
        train = frame.iloc[i-TRAIN_WINDOW:i]
        row = frame.iloc[i]
        p_actual, b_actual = predict_ols(train, row, BASE)
        p_no_nem, _ = predict_ols(train, row, NO_NEM)
        p_actual_q, qres_actual, qcoef_actual = predict_with_qqq_residual(train, row, BASE)
        p_no_nem_q, qres_no_nem, qcoef_no_nem = predict_with_qqq_residual(train, row, NO_NEM)
        nem_coef = float(b_actual[1 + BASE.index("ret_NEM")])
        rows.append({
            "fecha": row["fecha"],
            "actual": float(row["ret_target"]),
            "ret_NEM": float(row["ret_NEM"]),
            "actual_ols": p_actual,
            "sin_nem": p_no_nem,
            "actual_qqq_inc": p_actual_q,
            "sin_nem_qqq_inc": p_no_nem_q,
            "nem_coef": nem_coef,
            "qqq_resid_actual": qres_actual,
            "qqq_resid_sin_nem": qres_no_nem,
            "qqq_coef_actual": qcoef_actual,
            "qqq_coef_sin_nem": qcoef_no_nem,
        })
    pred = pd.DataFrame(rows)

    windows = {}
    for h in [30, 60, 90, 180, "ALL"]:
        s = pred if h == "ALL" else pred.tail(int(h))
        windows[str(h)] = compare_slice(s.reset_index(drop=True))

    rolling = {}
    for challenger in ["sin_nem", "actual_qqq_inc", "sin_nem_qqq_inc"]:
        rolling[challenger] = {str(h): rolling_summary(pred, h, challenger) for h in [30, 60, 90, 180]}

    abs_nem = pred["ret_NEM"].abs()
    q75 = float(abs_nem.quantile(0.75))
    regimes = {
        "NEM_UP": regime_compare(pred, pred["ret_NEM"] > 0),
        "NEM_DOWN": regime_compare(pred, pred["ret_NEM"] < 0),
        "NEM_BIG_MOVE_TOP25": regime_compare(pred, abs_nem >= q75),
        "NEM_NORMAL_BOTTOM75": regime_compare(pred, abs_nem < q75),
    }

    pred["quarter"] = pred["fecha"].dt.to_period("Q").astype(str)
    periods = {}
    for period, s in pred.groupby("quarter"):
        if len(s) >= 10:
            periods[period] = compare_slice(s.reset_index(drop=True))

    nem_coef = pred["nem_coef"]
    coefficient_stability = {
        "mean": float(nem_coef.mean()),
        "median": float(nem_coef.median()),
        "positive_share": float((nem_coef > 0).mean()),
        "negative_share": float((nem_coef < 0).mean()),
        "sign_changes": int((np.sign(nem_coef).diff().fillna(0) != 0).sum()),
        "recent30_median": float(nem_coef.tail(30).median()),
        "recent90_median": float(nem_coef.tail(90).median()),
        "min": float(nem_coef.min()),
        "max": float(nem_coef.max()),
    }

    payload = {
        "generated_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "fund": "PROFUTURO",
        "purpose": "Prueba de NEM, QQQ incremental y combinación SIN NEM + QQQ; diagnóstico solamente.",
        "method": "OLS rolling 90. QQQ residualizado dentro de cada ventana contra los factores presentes en cada modelo, sin información futura.",
        "common_complete_rows": int(len(frame)),
        "prediction_rows": int(len(pred)),
        "first_prediction": pred.iloc[0]["fecha"].strftime("%Y-%m-%d"),
        "last_prediction": pred.iloc[-1]["fecha"].strftime("%Y-%m-%d"),
        "models": {
            "actual_ols": BASE,
            "sin_nem": NO_NEM,
            "actual_qqq_inc": BASE + ["QQQ residual contra BASE"],
            "sin_nem_qqq_inc": NO_NEM + ["QQQ residual contra SIN_NEM"],
        },
        "windows": windows,
        "rolling_consistency": rolling,
        "nem_regimes": regimes,
        "nem_abs_return_q75": q75,
        "quarterly": periods,
        "nem_coefficient_stability": coefficient_stability,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    pred.drop(columns=["quarter"]).to_csv(PAIR_OUT, index=False)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
