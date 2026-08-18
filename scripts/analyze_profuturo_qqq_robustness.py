from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "rolling90"
OUT_JSON = ROOT / "analysis" / "qqq_robustness_profuturo.json"
OUT_CSV = ROOT / "analysis" / "qqq_robustness_paired_predictions.csv"
TRAIN_WINDOW = 90
HORIZONS = [30, 60, 90, 180]
THRESHOLD = 0.001
BOOT_REPS = 5000
BOOT_BLOCK = 5
RNG_SEED = 20260818

BASE_FEATURES = ["ret_SPY", "ret_EEM", "ret_EPU", "ret_MCHI", "ret_NEM", "ret_FCX", "ret_USD_PEN"]
ALL_FEATURES = [*BASE_FEATURES, "ret_QQQ"]


def classify(v: float) -> str:
    if v > THRESHOLD:
        return "SUBE"
    if v < -THRESHOLD:
        return "BAJA"
    return "NEUTRO"


def read_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce")
    return df.dropna(subset=["fecha"]).sort_values("fecha").reset_index(drop=True)


def extract_close(raw: pd.DataFrame, ticker: str) -> pd.Series:
    if raw.empty:
        return pd.Series(dtype=float)
    if isinstance(raw.columns, pd.MultiIndex):
        for key in [("Close", ticker), (ticker, "Close")]:
            if key in raw.columns:
                return pd.to_numeric(raw[key], errors="coerce")
        cols = [c for c in raw.columns if "Close" in c]
        if cols:
            return pd.to_numeric(raw[cols[0]], errors="coerce")
    if "Close" in raw.columns:
        return pd.to_numeric(raw["Close"], errors="coerce")
    raise RuntimeError("Yahoo no devolvio Close utilizable para QQQ")


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
    q = pd.DataFrame({"fecha": idx.normalize(), "QQQ": close.to_numpy(float)})
    q = q.sort_values("fecha").drop_duplicates("fecha", keep="last")
    q["ret_QQQ"] = q["QQQ"].pct_change(fill_method=None)
    return q[["fecha", "ret_QQQ"]]


def standardize(train_x: np.ndarray, current_x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    mu = train_x.mean(axis=0)
    sd = train_x.std(axis=0, ddof=0)
    sd = np.where(sd < 1e-12, 1.0, sd)
    return (train_x - mu) / sd, (current_x - mu) / sd


def ols_fit_predict(train_x: np.ndarray, y: np.ndarray, current_x: np.ndarray) -> tuple[float, np.ndarray]:
    xz, cz = standardize(train_x, current_x)
    beta = np.linalg.lstsq(np.c_[np.ones(len(xz)), xz], y, rcond=None)[0]
    pred = float(np.r_[1.0, cz] @ beta)
    return pred, beta


def residualize_against_current(train: pd.DataFrame, current: pd.Series) -> tuple[np.ndarray, np.ndarray, float]:
    x = train[BASE_FEATURES].to_numpy(float)
    q = train["ret_QQQ"].to_numpy(float)
    beta = np.linalg.lstsq(np.c_[np.ones(len(x)), x], q, rcond=None)[0]
    q_fit = np.c_[np.ones(len(x)), x] @ beta
    resid_train = q - q_fit
    current_base = current[BASE_FEATURES].to_numpy(float)
    resid_current = float(current["ret_QQQ"] - np.r_[1.0, current_base] @ beta)
    train_x = np.column_stack([x, resid_train])
    current_x = np.r_[current_base, resid_current]
    return train_x, current_x, float(np.std(resid_train, ddof=0))


def build_paired_predictions(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for i in range(TRAIN_WINDOW, len(frame)):
        train = frame.iloc[i - TRAIN_WINDOW:i]
        current = frame.iloc[i]
        y = train["ret_target"].to_numpy(float)
        actual = float(current["ret_target"])

        bx = train[BASE_FEATURES].to_numpy(float)
        bc = current[BASE_FEATURES].to_numpy(float)
        base_pred, _ = ols_fit_predict(bx, y, bc)

        rx, rc, resid_sd = residualize_against_current(train, current)
        chall_pred, chall_beta = ols_fit_predict(rx, y, rc)
        qqq_resid_coef_std = float(chall_beta[-1])

        rows.append({
            "fecha": current["fecha"],
            "actual": actual,
            "base_pred": base_pred,
            "challenger_pred": chall_pred,
            "base_class": classify(base_pred),
            "challenger_class": classify(chall_pred),
            "actual_class": classify(actual),
            "qqq_resid_coef_std": qqq_resid_coef_std,
            "qqq_resid_train_sd": resid_sd,
        })
    df = pd.DataFrame(rows)
    df["base_abs_err"] = (df["base_pred"] - df["actual"]).abs()
    df["challenger_abs_err"] = (df["challenger_pred"] - df["actual"]).abs()
    df["mae_improvement"] = df["base_abs_err"] - df["challenger_abs_err"]
    df["base_dir_correct"] = (df["base_class"] == df["actual_class"]).astype(int)
    df["challenger_dir_correct"] = (df["challenger_class"] == df["actual_class"]).astype(int)
    df["direction_improvement"] = df["challenger_dir_correct"] - df["base_dir_correct"]
    df["prev_actual"] = df["actual"].shift(1)
    df["sign_flip"] = (df["actual"] * df["prev_actual"] < 0).fillna(False)
    return df


def paired_metrics(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"n": 0}
    base_mae = float(df["base_abs_err"].mean())
    chall_mae = float(df["challenger_abs_err"].mean())
    base_acc = float(df["base_dir_correct"].mean())
    chall_acc = float(df["challenger_dir_correct"].mean())
    wins = int((df["mae_improvement"] > 1e-15).sum())
    losses = int((df["mae_improvement"] < -1e-15).sum())
    ties = int(len(df) - wins - losses)
    return {
        "n": int(len(df)),
        "base_mae": base_mae,
        "challenger_mae": chall_mae,
        "mae_improvement_pct": float((1.0 - chall_mae / base_mae) * 100.0),
        "mean_abs_error_improvement": float(df["mae_improvement"].mean()),
        "median_abs_error_improvement": float(df["mae_improvement"].median()),
        "challenger_win_days": wins,
        "base_win_days": losses,
        "ties": ties,
        "challenger_win_rate_ex_ties": float(wins / max(1, wins + losses)),
        "base_direction_accuracy": base_acc,
        "challenger_direction_accuracy": chall_acc,
        "direction_delta_pp": float((chall_acc - base_acc) * 100.0),
        "direction_gain_days": int((df["direction_improvement"] > 0).sum()),
        "direction_loss_days": int((df["direction_improvement"] < 0).sum()),
    }


def moving_block_bootstrap_ci(values: np.ndarray, reps: int = BOOT_REPS, block: int = BOOT_BLOCK) -> dict:
    values = np.asarray(values, dtype=float)
    n = len(values)
    if n < 2:
        return {"mean": float(values.mean()) if n else None, "ci95": [None, None], "prob_positive": None}
    rng = np.random.default_rng(RNG_SEED + n)
    means = np.empty(reps, dtype=float)
    blocks_needed = int(np.ceil(n / block))
    max_start = max(1, n - block + 1)
    for r in range(reps):
        starts = rng.integers(0, max_start, size=blocks_needed)
        sample = np.concatenate([values[s:s + block] for s in starts])[:n]
        means[r] = sample.mean()
    lo, hi = np.quantile(means, [0.025, 0.975])
    return {
        "mean": float(values.mean()),
        "ci95": [float(lo), float(hi)],
        "prob_positive": float((means > 0).mean()),
        "block_length": block,
        "reps": reps,
    }


def bootstrap_summary(df: pd.DataFrame) -> dict:
    return {
        "mae_improvement": moving_block_bootstrap_ci(df["mae_improvement"].to_numpy(float)),
        "direction_improvement": moving_block_bootstrap_ci(df["direction_improvement"].to_numpy(float)),
    }


def rolling_window_consistency(df: pd.DataFrame, window: int) -> dict:
    if len(df) < window:
        return {"window": window, "n_windows": 0}
    mae_wins = 0
    dir_wins = 0
    dir_nonworse = 0
    improvements = []
    dir_deltas = []
    for end in range(window, len(df) + 1):
        part = df.iloc[end - window:end]
        m = paired_metrics(part)
        improvements.append(m["mae_improvement_pct"])
        dir_deltas.append(m["direction_delta_pp"])
        if m["challenger_mae"] < m["base_mae"]:
            mae_wins += 1
        if m["challenger_direction_accuracy"] > m["base_direction_accuracy"]:
            dir_wins += 1
        if m["challenger_direction_accuracy"] >= m["base_direction_accuracy"]:
            dir_nonworse += 1
    return {
        "window": window,
        "n_windows": len(improvements),
        "mae_win_share": float(mae_wins / len(improvements)),
        "direction_win_share": float(dir_wins / len(improvements)),
        "direction_nonworse_share": float(dir_nonworse / len(improvements)),
        "median_mae_improvement_pct": float(np.median(improvements)),
        "min_mae_improvement_pct": float(np.min(improvements)),
        "max_mae_improvement_pct": float(np.max(improvements)),
        "median_direction_delta_pp": float(np.median(dir_deltas)),
    }


def leave_out_tests(df: pd.DataFrame) -> dict:
    out = {}
    for criterion, col in {
        "largest_abs_target_days": "actual",
        "largest_abs_paired_difference_days": "mae_improvement",
    }.items():
        out[criterion] = {}
        order = df[col].abs().sort_values(ascending=False).index
        for k in [1, 3, 5, 10]:
            keep = df.drop(index=order[:k])
            out[criterion][str(k)] = paired_metrics(keep)
    return out


def contribution_concentration(df: pd.DataFrame) -> dict:
    positive = df.loc[df["mae_improvement"] > 0, "mae_improvement"].sort_values(ascending=False)
    total_positive = float(positive.sum())
    net = float(df["mae_improvement"].sum())
    out = {"net_total_abs_error_improvement": net, "positive_improvement_total": total_positive}
    for k in [1, 3, 5, 10]:
        top = float(positive.head(k).sum())
        out[f"top_{k}_positive_share"] = float(top / total_positive) if total_positive > 0 else None
        out[f"top_{k}_positive_vs_net"] = float(top / net) if abs(net) > 1e-15 else None
    return out


def regime_metrics(df: pd.DataFrame) -> dict:
    abs_q75 = float(df["actual"].abs().quantile(0.75))
    masks = {
        "up": df["actual"] > THRESHOLD,
        "down": df["actual"] < -THRESHOLD,
        "neutral": df["actual"].abs() <= THRESHOLD,
        "strong_up_1pct": df["actual"] >= 0.01,
        "strong_down_1pct": df["actual"] <= -0.01,
        "high_movement_top_quartile": df["actual"].abs() >= abs_q75,
        "lower_movement_bottom_75pct": df["actual"].abs() < abs_q75,
        "sign_flip_day": df["sign_flip"],
        "non_sign_flip_day": ~df["sign_flip"],
    }
    return {name: paired_metrics(df.loc[mask].copy()) for name, mask in masks.items()}


def calendar_periods(df: pd.DataFrame) -> dict:
    tmp = df.copy()
    tmp["quarter"] = tmp["fecha"].dt.to_period("Q").astype(str)
    tmp["half"] = tmp["fecha"].dt.year.astype(str) + "-H" + np.where(tmp["fecha"].dt.month <= 6, "1", "2")
    quarters = {k: paired_metrics(g.copy()) for k, g in tmp.groupby("quarter") if len(g) >= 10}
    halves = {k: paired_metrics(g.copy()) for k, g in tmp.groupby("half") if len(g) >= 10}
    return {"quarters": quarters, "halves": halves}


def coefficient_stability(df: pd.DataFrame) -> dict:
    c = df["qqq_resid_coef_std"].to_numpy(float)
    signs = np.sign(c)
    sign_changes = int(np.sum(signs[1:] * signs[:-1] < 0))
    return {
        "n": int(len(c)),
        "median": float(np.median(c)),
        "mean": float(np.mean(c)),
        "q10": float(np.quantile(c, 0.10)),
        "q90": float(np.quantile(c, 0.90)),
        "min": float(np.min(c)),
        "max": float(np.max(c)),
        "positive_share": float(np.mean(c > 0)),
        "negative_share": float(np.mean(c < 0)),
        "sign_changes": sign_changes,
        "recent30_median": float(np.median(c[-30:])),
        "recent90_median": float(np.median(c[-90:])),
    }


def top_days(df: pd.DataFrame, n: int = 10) -> dict:
    cols = ["fecha", "actual", "base_pred", "challenger_pred", "base_abs_err", "challenger_abs_err", "mae_improvement", "base_dir_correct", "challenger_dir_correct"]
    best = df.nlargest(n, "mae_improvement")[cols].copy()
    worst = df.nsmallest(n, "mae_improvement")[cols].copy()
    for d in (best, worst):
        d["fecha"] = d["fecha"].dt.strftime("%Y-%m-%d")
    return {"largest_challenger_gains": best.to_dict("records"), "largest_challenger_losses": worst.to_dict("records")}


def main() -> None:
    markets = read_csv(DATA / "markets.csv")
    sbs = read_csv(DATA / "sbs_profuturo_f3.csv")
    sbs["valor_cuota"] = pd.to_numeric(sbs["valor_cuota"], errors="coerce")
    sbs = sbs.dropna(subset=["valor_cuota"]).drop_duplicates("fecha", keep="last")
    sbs["ret_target"] = sbs["valor_cuota"].pct_change(fill_method=None)

    qqq = download_qqq(markets["fecha"].min(), max(markets["fecha"].max(), pd.Timestamp.now().normalize()))
    markets = markets.merge(qqq, on="fecha", how="left")
    frame = sbs[["fecha", "ret_target"]].merge(markets, on="fecha", how="inner")
    frame = frame.loc[frame["fecha"] >= pd.Timestamp("2025-01-01")]
    frame = frame.dropna(subset=["ret_target", *ALL_FEATURES]).sort_values("fecha").drop_duplicates("fecha", keep="last").reset_index(drop=True)
    if len(frame) <= TRAIN_WINDOW + max(HORIZONS):
        raise RuntimeError(f"Muestra insuficiente: {len(frame)} filas completas")

    paired = build_paired_predictions(frame)
    paired.to_csv(OUT_CSV, index=False)

    horizon_metrics = {}
    bootstrap = {}
    for h in [*HORIZONS, "ALL"]:
        part = paired if h == "ALL" else paired.tail(int(h)).reset_index(drop=True)
        horizon_metrics[str(h)] = paired_metrics(part)
        bootstrap[str(h)] = bootstrap_summary(part)

    payload = {
        "generated_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "fund": "PROFUTURO",
        "purpose": "Revision de robustez del QQQ residualizado contra todos los factores actuales. Diagnostico solamente; no modifica visor ni modelo oficial.",
        "method": "OLS rolling 90. En cada ventana, QQQ residual = QQQ menos la parte explicada por SPY, EEM, EPU, MCHI, NEM, FCX y USD/PEN usando solo el train de esa ventana. Evaluacion paired out-of-sample.",
        "common_complete_rows": int(len(frame)),
        "prediction_rows": int(len(paired)),
        "first_prediction": paired.iloc[0]["fecha"].strftime("%Y-%m-%d"),
        "last_prediction": paired.iloc[-1]["fecha"].strftime("%Y-%m-%d"),
        "horizon_metrics": horizon_metrics,
        "moving_block_bootstrap": bootstrap,
        "rolling_window_consistency": {str(h): rolling_window_consistency(paired, h) for h in HORIZONS},
        "leave_out_sensitivity": leave_out_tests(paired),
        "improvement_concentration": contribution_concentration(paired),
        "regimes": regime_metrics(paired),
        "calendar_periods": calendar_periods(paired),
        "qqq_residual_coefficient_stability": coefficient_stability(paired),
        "top_days": top_days(paired, 10),
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
