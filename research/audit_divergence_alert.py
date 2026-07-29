from __future__ import annotations

import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import HuberRegressor
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "rolling90"
OUT = ROOT / "research_outputs" / "divergence_alert"
WINDOW = 90
THRESHOLD = 0.001
EPSILON = 1.1
ALPHA = 0.0001
CANCEL_EXTREME = 0.70
INTENSITY_Q = 0.80
USD_Q = 0.80
FEATURES = ["ret_SPY", "ret_NEM", "ret_FCX", "ret_EPU", "ret_MCHI", "ret_EEM", "ret_USD_PEN"]
TARGET_DATES = ["2026-04-09", "2026-06-01", "2026-06-18"]
ERROR_DATES = ["2026-03-24", "2026-03-27", "2026-04-06", "2026-04-07", "2026-04-09", "2026-06-01", "2026-06-08", "2026-06-16", "2026-06-17", "2026-06-18", "2026-06-22", "2026-06-26", "2026-07-02", "2026-07-20"]


def classify(x: float) -> str:
    if x > THRESHOLD:
        return "SUBE"
    if x < -THRESHOLD:
        return "BAJA"
    return "NEUTRO"


def prepare_data() -> pd.DataFrame:
    sbs = pd.read_csv(DATA / "sbs_profuturo_f3.csv")
    markets = pd.read_csv(DATA / "markets.csv")
    sbs["fecha"] = pd.to_datetime(sbs["fecha"], errors="coerce")
    sbs["valor_cuota"] = pd.to_numeric(sbs["valor_cuota"], errors="coerce")
    sbs = sbs.dropna(subset=["fecha", "valor_cuota"]).sort_values("fecha").drop_duplicates("fecha", keep="last")
    sbs["ret_profuturo"] = sbs["valor_cuota"].pct_change(fill_method=None)
    markets["fecha"] = pd.to_datetime(markets["fecha"], errors="coerce")
    for col in FEATURES:
        markets[col] = pd.to_numeric(markets[col], errors="coerce")
    data = sbs[["fecha", "valor_cuota", "ret_profuturo"]].merge(markets[["fecha", *FEATURES]], on="fecha", how="inner")
    return data.dropna(subset=["ret_profuturo", *FEATURES]).sort_values("fecha").reset_index(drop=True)


def fit_huber(train: pd.DataFrame) -> tuple[StandardScaler, HuberRegressor, dict[str, float]]:
    scaler = StandardScaler()
    xs = scaler.fit_transform(train[FEATURES].to_numpy(float))
    model = HuberRegressor(epsilon=EPSILON, alpha=ALPHA, fit_intercept=True, max_iter=3000, tol=1e-8)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", ConvergenceWarning)
        model.fit(xs, train["ret_profuturo"].to_numpy(float) * 100.0)
    scale = np.where(np.asarray(scaler.scale_, dtype=float) == 0, 1.0, np.asarray(scaler.scale_, dtype=float))
    coef = np.asarray(model.coef_, dtype=float) / scale / 100.0
    intercept = (float(model.intercept_) - float(np.sum(np.asarray(model.coef_) * np.asarray(scaler.mean_) / scale))) / 100.0
    return scaler, model, {"intercept": intercept, **{f: float(v) for f, v in zip(FEATURES, coef)}}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    data = prepare_data()
    rows = []
    for i in range(WINDOW, len(data)):
        train = data.iloc[i - WINDOW:i]
        row = data.iloc[i]
        scaler, model, beta = fit_huber(train)
        pred = float(model.predict(scaler.transform(row[FEATURES].to_numpy(float).reshape(1, -1)))[0] / 100.0)
        contrib = {f: float(beta[f] * float(row[f])) for f in FEATURES}
        positive = float(sum(v for v in contrib.values() if v > 0))
        negative = float(sum(-v for v in contrib.values() if v < 0))
        intensity = positive + negative
        cancellation = 0.0 if intensity <= 0 else 1.0 - abs(positive - negative) / intensity
        usd_contrib = contrib["ret_USD_PEN"]
        non_usd_net = float(sum(v for f, v in contrib.items() if f != "ret_USD_PEN"))
        ordered = sorted(contrib.items(), key=lambda kv: abs(kv[1]), reverse=True)
        rows.append({
            "fecha": row["fecha"],
            "ret_profuturo": float(row["ret_profuturo"]),
            "real_class": classify(float(row["ret_profuturo"])),
            "pred_huber": pred,
            "pred_class": classify(pred),
            "hit": classify(float(row["ret_profuturo"])) == classify(pred),
            "intercept": float(beta["intercept"]),
            "positive_contrib": positive,
            "negative_contrib_abs": negative,
            "net_factor_contrib": positive - negative,
            "intensity": intensity,
            "cancellation": cancellation,
            "usd_return": float(row["ret_USD_PEN"]),
            "usd_beta": float(beta["ret_USD_PEN"]),
            "usd_contrib": usd_contrib,
            "non_usd_net": non_usd_net,
            "usd_opposes_others": bool(usd_contrib * non_usd_net < 0),
            "usd_abs_rank": 1 + [k for k, _ in ordered].index("ret_USD_PEN"),
            **{f"contrib_{f}": v for f, v in contrib.items()},
            **{f"value_{f}": float(row[f]) for f in FEATURES},
        })
    out = pd.DataFrame(rows).sort_values("fecha").reset_index(drop=True)
    out["intensity_p80_prev90"] = out["intensity"].shift(1).rolling(WINDOW, min_periods=WINDOW).quantile(INTENSITY_Q)
    out["usd_abs_p80_prev90"] = out["usd_contrib"].abs().shift(1).rolling(WINDOW, min_periods=WINDOW).quantile(USD_Q)
    out["divergence_extreme_alert"] = out["intensity_p80_prev90"].notna() & out["cancellation"].gt(CANCEL_EXTREME) & out["intensity"].gt(out["intensity_p80_prev90"]) & out["positive_contrib"].gt(0) & out["negative_contrib_abs"].gt(0)
    out["usd_extreme_alert"] = out["usd_abs_p80_prev90"].notna() & out["usd_contrib"].abs().gt(out["usd_abs_p80_prev90"])
    out["either_alert"] = out["divergence_extreme_alert"] | out["usd_extreme_alert"]
    target = out[out["fecha"].dt.strftime("%Y-%m-%d").isin(TARGET_DATES)].copy()
    errors = out[out["fecha"].dt.strftime("%Y-%m-%d").isin(ERROR_DATES)].copy()
    latest90 = out.tail(WINDOW).copy()
    summary = {
        "method": {
            "rolling_window": WINDOW,
            "huber_epsilon": EPSILON,
            "huber_alpha": ALPHA,
            "classification_threshold": THRESHOLD,
            "divergence_rule": "cancellation>0.70 and intensity>rolling prior-90 p80",
            "usd_rule": "abs USD contribution>rolling prior-90 p80",
            "intercept_excluded_from_divergence": True,
            "no_lookahead": True,
        },
        "target_dates": target.assign(fecha=target["fecha"].dt.strftime("%Y-%m-%d")).to_dict("records"),
        "error_dates_summary": {
            "n": int(len(errors)),
            "divergence_alert_n": int(errors["divergence_extreme_alert"].sum()),
            "usd_alert_n": int(errors["usd_extreme_alert"].sum()),
            "either_alert_n": int(errors["either_alert"].sum()),
            "divergence_dates": errors.loc[errors["divergence_extreme_alert"], "fecha"].dt.strftime("%Y-%m-%d").tolist(),
            "usd_dates": errors.loc[errors["usd_extreme_alert"], "fecha"].dt.strftime("%Y-%m-%d").tolist(),
            "either_dates": errors.loc[errors["either_alert"], "fecha"].dt.strftime("%Y-%m-%d").tolist(),
        },
        "latest90_alert_frequency": {
            "divergence_n": int(latest90["divergence_extreme_alert"].sum()),
            "usd_n": int(latest90["usd_extreme_alert"].sum()),
            "either_n": int(latest90["either_alert"].sum()),
        },
    }
    out.to_csv(OUT / "daily_alert_audit.csv", index=False)
    target.to_csv(OUT / "target_dates.csv", index=False)
    errors.to_csv(OUT / "error_dates.csv", index=False)
    (OUT / "results.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
