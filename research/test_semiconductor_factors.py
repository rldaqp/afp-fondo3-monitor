from __future__ import annotations

import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import HuberRegressor
from sklearn.metrics import r2_score
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "rolling90"
OUT = ROOT / "research_outputs" / "semiconductor_factors"
WINDOW = 90
THRESHOLD = 0.001
EPSILON = 1.1
ALPHA = 0.0001

BASE_FEATURES = [
    "ret_SPY",
    "ret_NEM",
    "ret_FCX",
    "ret_EPU",
    "ret_MCHI",
    "ret_EEM",
    "ret_USD_PEN",
]

VARIANTS: dict[str, list[str]] = {
    "full7": BASE_FEATURES,
    "plus_soxx": [*BASE_FEATURES, "ret_SOXX"],
    "plus_smh": [*BASE_FEATURES, "ret_SMH"],
    "replace_spy_soxx": [f for f in BASE_FEATURES if f != "ret_SPY"] + ["ret_SOXX"],
    "replace_spy_smh": [f for f in BASE_FEATURES if f != "ret_SPY"] + ["ret_SMH"],
}

TARGET_DATES = ["2026-04-09", "2026-06-01", "2026-06-18"]


def classify(value: float) -> str:
    if value > THRESHOLD:
        return "SUBE"
    if value < -THRESHOLD:
        return "BAJA"
    return "NEUTRO"


def download_close(ticker: str, start: str, end: str) -> pd.Series:
    raw = yf.download(
        ticker,
        start=start,
        end=end,
        auto_adjust=False,
        progress=False,
        threads=False,
    )
    if raw.empty:
        raise RuntimeError(f"Yahoo no devolvió datos para {ticker}")
    close = raw["Close"]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    close = pd.to_numeric(close, errors="coerce")
    close.index = pd.to_datetime(close.index, errors="coerce").tz_localize(None)
    close.name = ticker
    return close.dropna().sort_index()


def prepare_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    sbs = pd.read_csv(DATA / "sbs_profuturo_f3.csv")
    markets = pd.read_csv(DATA / "markets.csv")

    sbs["fecha"] = pd.to_datetime(sbs["fecha"], errors="coerce")
    sbs["valor_cuota"] = pd.to_numeric(sbs["valor_cuota"], errors="coerce")
    sbs = (
        sbs.dropna(subset=["fecha", "valor_cuota"])
        .sort_values("fecha")
        .drop_duplicates("fecha", keep="last")
    )
    sbs["ret_profuturo"] = sbs["valor_cuota"].pct_change(fill_method=None)

    markets["fecha"] = pd.to_datetime(markets["fecha"], errors="coerce")
    for feature in BASE_FEATURES:
        markets[feature] = pd.to_numeric(markets.get(feature), errors="coerce")

    start = (markets["fecha"].min() - pd.Timedelta(days=15)).date().isoformat()
    end = (pd.Timestamp.utcnow().tz_localize(None) + pd.Timedelta(days=2)).date().isoformat()
    semis = pd.concat(
        [download_close("SOXX", start, end), download_close("SMH", start, end)],
        axis=1,
    ).reset_index().rename(columns={"Date": "fecha", "index": "fecha"})
    semis["fecha"] = pd.to_datetime(semis["fecha"], errors="coerce")
    for ticker in ["SOXX", "SMH"]:
        semis[f"ret_{ticker}"] = semis[ticker].pct_change(fill_method=None)

    merged_market = markets.merge(
        semis[["fecha", "SOXX", "SMH", "ret_SOXX", "ret_SMH"]],
        on="fecha",
        how="left",
    )
    all_features = sorted({f for features in VARIANTS.values() for f in features})
    data = sbs[["fecha", "valor_cuota", "ret_profuturo"]].merge(
        merged_market[["fecha", *all_features]],
        on="fecha",
        how="inner",
    )
    data = (
        data.dropna(subset=["ret_profuturo", *all_features])
        .sort_values("fecha")
        .reset_index(drop=True)
    )
    return data, merged_market


def fit_huber(x: np.ndarray, y: np.ndarray) -> tuple[StandardScaler, HuberRegressor]:
    scaler = StandardScaler()
    x_scaled = scaler.fit_transform(x)
    model = HuberRegressor(
        epsilon=EPSILON,
        alpha=ALPHA,
        fit_intercept=True,
        max_iter=3000,
        tol=1e-8,
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", ConvergenceWarning)
        model.fit(x_scaled, y * 100.0)
    return scaler, model


def rolling_predictions(data: pd.DataFrame, features: list[str], label: str) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for i in range(WINDOW, len(data)):
        train = data.iloc[i - WINDOW : i]
        row = data.iloc[i]
        scaler, model = fit_huber(
            train[features].to_numpy(float),
            train["ret_profuturo"].to_numpy(float),
        )
        pred = float(
            model.predict(
                scaler.transform(row[features].to_numpy(float).reshape(1, -1))
            )[0]
            / 100.0
        )
        rows.append(
            {
                "row_index": i,
                "fecha": row["fecha"],
                "ret_profuturo": float(row["ret_profuturo"]),
                f"pred_{label}": pred,
                f"class_{label}": classify(pred),
                "real_class": classify(float(row["ret_profuturo"])),
            }
        )
    return pd.DataFrame(rows)


def metrics(frame: pd.DataFrame, pred_col: str) -> dict[str, object]:
    work = frame.dropna(subset=["ret_profuturo", pred_col]).copy()
    work["pred_class"] = work[pred_col].map(classify)
    work["real_class"] = work["ret_profuturo"].map(classify)
    work["hit"] = work["pred_class"].eq(work["real_class"])
    error = work[pred_col] - work["ret_profuturo"]
    result: dict[str, object] = {
        "n": int(len(work)),
        "correct": int(work["hit"].sum()),
        "accuracy": float(work["hit"].mean()) if len(work) else None,
        "mae_pp": float(error.abs().mean() * 100.0) if len(work) else None,
        "rmse_pp": float(np.sqrt(np.mean(error * error)) * 100.0) if len(work) else None,
        "r2": float(r2_score(work["ret_profuturo"], work[pred_col])) if len(work) > 1 else None,
        "hard_reversals": int(
            (
                work["pred_class"].isin(["SUBE", "BAJA"])
                & work["real_class"].isin(["SUBE", "BAJA"])
                & work["pred_class"].ne(work["real_class"])
            ).sum()
        ),
    }
    for signal in ["SUBE", "BAJA", "NEUTRO"]:
        subset = work.loc[work["pred_class"].eq(signal)]
        result[f"{signal.lower()}_n"] = int(len(subset))
        result[f"{signal.lower()}_accuracy"] = (
            None if subset.empty else float(subset["hit"].mean())
        )
    return result


def split_name(row_index: int, n: int) -> str:
    train_end = int(np.floor(n * 0.60))
    validation_end = int(np.floor(n * 0.80))
    if row_index < train_end:
        return "train"
    if row_index < validation_end:
        return "validation"
    return "test"


def current_chain(
    data: pd.DataFrame,
    merged_market: pd.DataFrame,
    features: list[str],
) -> dict[str, object]:
    train = data.tail(WINDOW).copy()
    scaler, model = fit_huber(
        train[features].to_numpy(float),
        train["ret_profuturo"].to_numpy(float),
    )
    last_sbs_date = pd.Timestamp(data.iloc[-1]["fecha"])
    base_vc = float(data.iloc[-1]["valor_cuota"])
    pending = merged_market.loc[merged_market["fecha"].gt(last_sbs_date)].copy()
    pending = pending.dropna(subset=["fecha", *features]).sort_values("fecha")
    chain: list[dict[str, object]] = []
    for _, row in pending.iterrows():
        pred = float(
            model.predict(
                scaler.transform(row[features].to_numpy(float).reshape(1, -1))
            )[0]
            / 100.0
        )
        base_vc *= 1.0 + pred
        chain.append(
            {
                "fecha": row["fecha"].date().isoformat(),
                "ret_estimado": pred,
                "senal": classify(pred),
                "vc_estimado": base_vc,
            }
        )
    return {
        "training_start": train.iloc[0]["fecha"].date().isoformat(),
        "training_end": train.iloc[-1]["fecha"].date().isoformat(),
        "training_n": int(len(train)),
        "latest": chain[-1] if chain else None,
        "pending_series": chain,
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    data, merged_market = prepare_data()
    if len(data) <= WINDOW:
        raise RuntimeError(f"Muestra insuficiente: {len(data)}")

    predictions: dict[str, pd.DataFrame] = {}
    paired: pd.DataFrame | None = None
    for label, features in VARIANTS.items():
        pred = rolling_predictions(data, features, label)
        predictions[label] = pred
        cols = ["row_index", "fecha", f"pred_{label}", f"class_{label}"]
        if paired is None:
            paired = pred.copy()
        else:
            paired = paired.merge(pred[cols], on=["row_index", "fecha"], how="inner")

    assert paired is not None
    paired["split"] = paired["row_index"].map(lambda i: split_name(int(i), len(data)))
    for label in VARIANTS:
        paired[f"hit_{label}"] = paired["real_class"].eq(paired[f"class_{label}"])

    split_metrics: dict[str, dict[str, object]] = {}
    for split in ["train", "validation", "test"]:
        subset = paired.loc[paired["split"].eq(split)]
        split_metrics[split] = {
            label: metrics(subset, f"pred_{label}") for label in VARIANTS
        }

    validation = split_metrics["validation"]
    candidates = [label for label in VARIANTS if label != "full7"]
    selected = sorted(
        candidates,
        key=lambda label: (
            -float(validation[label]["accuracy"]),
            float(validation[label]["mae_pp"]),
            float(validation[label]["rmse_pp"]),
        ),
    )[0]

    latest90 = paired.tail(WINDOW).copy()
    base_hit = latest90["hit_full7"]
    candidate_hit = latest90[f"hit_{selected}"]
    corrected = (~base_hit) & candidate_hit
    new_errors = base_hit & (~candidate_hit)

    target_rows = paired.loc[
        paired["fecha"].dt.strftime("%Y-%m-%d").isin(TARGET_DATES)
    ].copy()
    target_cols = ["fecha", "ret_profuturo", "real_class"]
    for label in VARIANTS:
        target_cols.extend([f"pred_{label}", f"class_{label}", f"hit_{label}"])
    target_rows = target_rows[target_cols]

    current = {
        label: current_chain(data, merged_market, features)
        for label, features in VARIANTS.items()
    }

    result = {
        "method": {
            "window": WINDOW,
            "threshold": THRESHOLD,
            "huber_epsilon": EPSILON,
            "huber_alpha": ALPHA,
            "variants": VARIANTS,
            "semiconductor_prices": "Yahoo Finance Close, auto_adjust=False",
            "selection_rule": "Highest validation classification accuracy; ties by lower validation MAE and RMSE",
            "leakage_control": "Every target uses only the preceding 90 complete observations; test is not used for selection",
        },
        "sample": {
            "n": int(len(data)),
            "start": data.iloc[0]["fecha"].date().isoformat(),
            "end": data.iloc[-1]["fecha"].date().isoformat(),
            "rolling_predictions_n": int(len(paired)),
        },
        "selected_candidate": selected,
        "chronological_60_20_20": split_metrics,
        "latest90": {
            "metrics": {
                label: metrics(latest90, f"pred_{label}") for label in VARIANTS
            },
            "selected_vs_full7": {
                "corrected_errors": int(corrected.sum()),
                "new_errors": int(new_errors.sum()),
                "corrected_dates": latest90.loc[corrected, "fecha"].dt.date.astype(str).tolist(),
                "new_error_dates": latest90.loc[new_errors, "fecha"].dt.date.astype(str).tolist(),
                "signal_changes": int(
                    latest90[f"class_{selected}"].ne(latest90["class_full7"]).sum()
                ),
            },
        },
        "target_dates": json.loads(target_rows.to_json(orient="records", date_format="iso")),
        "current": current,
    }

    paired.to_csv(OUT / "paired_predictions.csv", index=False)
    target_rows.to_csv(OUT / "target_dates.csv", index=False)
    merged_market[["fecha", "SOXX", "SMH", "ret_SOXX", "ret_SMH"]].dropna(
        subset=["fecha"]
    ).to_csv(OUT / "semiconductor_data.csv", index=False)
    (OUT / "results.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
