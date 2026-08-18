from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "rolling90"
OUT = ROOT / "analysis" / "factor_tournament_profuturo.json"
TRAIN_WINDOW = 90
HORIZONS = [30, 60, 90, 180]
THRESHOLD = 0.001

MODELS = {
    "ACTUAL": ["ret_SPY", "ret_EEM", "ret_EPU", "ret_MCHI", "ret_NEM", "ret_FCX", "ret_USD_PEN"],
    "A_QQQ_REEMPLAZA_SPY": ["ret_QQQ", "ret_EEM", "ret_EPU", "ret_MCHI", "ret_NEM", "ret_FCX", "ret_USD_PEN"],
    "B_SPY_MAS_QQQ": ["ret_SPY", "ret_QQQ", "ret_EEM", "ret_EPU", "ret_MCHI", "ret_NEM", "ret_FCX", "ret_USD_PEN"],
    "C_QQQ_REEMPLAZA_EEM": ["ret_SPY", "ret_QQQ", "ret_EPU", "ret_MCHI", "ret_NEM", "ret_FCX", "ret_USD_PEN"],
}


def classify(value: float) -> str:
    if value > THRESHOLD:
        return "SUBE"
    if value < -THRESHOLD:
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
        close_cols = [c for c in raw.columns if "Close" in c]
        if close_cols:
            return pd.to_numeric(raw[close_cols[0]], errors="coerce")
    if "Close" in raw.columns:
        return pd.to_numeric(raw["Close"], errors="coerce")
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
    close = extract_close(raw, "QQQ").dropna()
    if close.empty:
        raise RuntimeError("No se pudo descargar QQQ desde Yahoo Finance")
    idx = pd.to_datetime(close.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    qqq = pd.DataFrame({"fecha": idx.normalize(), "QQQ": close.to_numpy(float)})
    qqq = qqq.sort_values("fecha").drop_duplicates("fecha", keep="last")
    qqq["ret_QQQ"] = qqq["QQQ"].pct_change(fill_method=None)
    return qqq[["fecha", "QQQ", "ret_QQQ"]]


def fit_predict(train: pd.DataFrame, row: pd.Series, features: list[str]) -> tuple[float, np.ndarray]:
    x = train[features].to_numpy(float)
    y = train["ret_target"].to_numpy(float)
    beta = np.linalg.lstsq(np.c_[np.ones(len(x)), x], y, rcond=None)[0]
    pred = float(np.r_[1.0, row[features].to_numpy(float)] @ beta)
    return pred, beta


def build_predictions(frame: pd.DataFrame, features: list[str]) -> pd.DataFrame:
    rows = []
    for i in range(TRAIN_WINDOW, len(frame)):
        train = frame.iloc[i - TRAIN_WINDOW:i]
        current = frame.iloc[i]
        pred, beta = fit_predict(train, current, features)
        actual = float(current["ret_target"])
        rows.append({
            "fecha": current["fecha"],
            "pred": pred,
            "actual": actual,
            "pred_class": classify(pred),
            "actual_class": classify(actual),
            "coef_norm": float(np.linalg.norm(beta[1:])),
        })
    return pd.DataFrame(rows)


def metrics(pred: pd.DataFrame) -> dict:
    p = pred["pred"].to_numpy(float)
    y = pred["actual"].to_numpy(float)
    err = p - y
    corr = None
    if len(y) > 2 and np.std(p) > 0 and np.std(y) > 0:
        corr = float(np.corrcoef(p, y)[0, 1])
    return {
        "n": int(len(pred)),
        "start": pred.iloc[0]["fecha"].strftime("%Y-%m-%d"),
        "end": pred.iloc[-1]["fecha"].strftime("%Y-%m-%d"),
        "mae": float(np.mean(np.abs(err))),
        "rmse": float(np.sqrt(np.mean(err ** 2))),
        "direction_accuracy": float((pred["pred_class"] == pred["actual_class"]).mean()),
        "pred_actual_corr": corr,
        "median_coef_norm": float(pred["coef_norm"].median()),
        "max_coef_norm": float(pred["coef_norm"].max()),
    }


def vif_table(df: pd.DataFrame, features: list[str]) -> dict:
    x = df[features].to_numpy(float)
    out = {}
    for j, feature in enumerate(features):
        y = x[:, j]
        others = np.delete(x, j, axis=1)
        design = np.c_[np.ones(len(others)), others]
        beta = np.linalg.lstsq(design, y, rcond=None)[0]
        fitted = design @ beta
        ss_res = float(np.sum((y - fitted) ** 2))
        ss_tot = float(np.sum((y - np.mean(y)) ** 2))
        if ss_tot <= 1e-20:
            vif = None
        else:
            r2 = 1.0 - ss_res / ss_tot
            vif = float(1.0 / max(1e-12, 1.0 - r2))
        out[feature] = vif
    finite = {k: v for k, v in out.items() if v is not None and np.isfinite(v)}
    return {
        "by_feature": out,
        "max_vif": max(finite.values()) if finite else None,
        "max_vif_feature": max(finite, key=finite.get) if finite else None,
    }


def main() -> None:
    markets = read_csv(DATA / "markets.csv")
    sbs = read_csv(DATA / "sbs_profuturo_f3.csv")
    sbs["valor_cuota"] = pd.to_numeric(sbs["valor_cuota"], errors="coerce")
    sbs = sbs.dropna(subset=["valor_cuota"]).drop_duplicates("fecha", keep="last")
    sbs["ret_target"] = sbs["valor_cuota"].pct_change(fill_method=None)

    qqq = download_qqq(markets["fecha"].min(), max(markets["fecha"].max(), pd.Timestamp.now().normalize()))
    markets = markets.merge(qqq, on="fecha", how="left")

    all_features = sorted({f for fs in MODELS.values() for f in fs})
    frame = sbs[["fecha", "ret_target"]].merge(markets, on="fecha", how="inner")
    frame = frame.loc[frame["fecha"] >= pd.Timestamp("2025-01-01")]
    frame = frame.dropna(subset=["ret_target", *all_features]).sort_values("fecha").drop_duplicates("fecha", keep="last").reset_index(drop=True)
    if len(frame) <= TRAIN_WINDOW + max(HORIZONS):
        raise RuntimeError(f"Solo hay {len(frame)} filas completas; insuficiente para evaluación 180 + train 90")

    predictions = {name: build_predictions(frame, features) for name, features in MODELS.items()}
    base_dates = predictions["ACTUAL"]["fecha"]
    for name, pred in predictions.items():
        if not pred["fecha"].equals(base_dates):
            raise RuntimeError(f"Fechas desalineadas en {name}")

    windows = {}
    for h in [*HORIZONS, "ALL"]:
        label = str(h)
        slices = {name: (pred if h == "ALL" else pred.tail(int(h))) for name, pred in predictions.items()}
        metric_map = {name: metrics(p.reset_index(drop=True)) for name, p in slices.items()}
        best_mae = min(metric_map, key=lambda n: metric_map[n]["mae"])
        best_direction = max(metric_map, key=lambda n: metric_map[n]["direction_accuracy"])
        base = metric_map["ACTUAL"]
        deltas = {}
        for name, m in metric_map.items():
            deltas[name] = {
                "mae_change_vs_actual_pct": float((m["mae"] / base["mae"] - 1.0) * 100.0),
                "direction_delta_pp_vs_actual": float((m["direction_accuracy"] - base["direction_accuracy"]) * 100.0),
            }
        windows[label] = {
            "models": metric_map,
            "best_mae": best_mae,
            "best_direction": best_direction,
            "vs_actual": deltas,
        }

    recent90 = frame.tail(90).reset_index(drop=True)
    vifs = {name: vif_table(recent90, features) for name, features in MODELS.items()}

    mae_wins = {name: 0 for name in MODELS}
    dir_wins = {name: 0 for name in MODELS}
    for h in map(str, HORIZONS):
        mae_wins[windows[h]["best_mae"]] += 1
        dir_wins[windows[h]["best_direction"]] += 1

    payload = {
        "generated_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "fund": "PROFUTURO",
        "purpose": "Diagnóstico solamente; no modifica el visor ni el modelo oficial.",
        "method": "OLS rolling 90, mismas fechas completas para los cuatro modelos, target VC SBS oficial y QQQ Yahoo Finance. Ventanas 30/60/90/180 son evaluación fuera de muestra reciente.",
        "common_complete_rows": int(len(frame)),
        "prediction_rows": int(len(base_dates)),
        "first_prediction": base_dates.iloc[0].strftime("%Y-%m-%d"),
        "last_prediction": base_dates.iloc[-1].strftime("%Y-%m-%d"),
        "models": MODELS,
        "windows": windows,
        "recent90_vif": vifs,
        "wins_recent_windows": {
            "mae": mae_wins,
            "direction": dir_wins,
        },
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
