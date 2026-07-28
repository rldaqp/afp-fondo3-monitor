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
PUBLIC = ROOT / "public" / "data"
THRESHOLD = 0.001
WINDOW = 90
FEATURES = ["ret_SPY", "ret_NEM", "ret_FCX", "ret_EPU", "ret_MCHI", "ret_EEM", "ret_USD_PEN"]
LABELS = {
    "ret_SPY": "SPY",
    "ret_NEM": "NEM",
    "ret_FCX": "FCX",
    "ret_EPU": "EPU",
    "ret_MCHI": "MCHI",
    "ret_EEM": "EEM",
    "ret_USD_PEN": "USD/PEN",
}
HUBER_EPSILON = 1.1
HUBER_ALPHA = 0.0001


def _classify(x: float) -> str:
    if x > THRESHOLD:
        return "SUBE"
    if x < -THRESHOLD:
        return "BAJA"
    return "NEUTRO"


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(path)


def _pct(v: float) -> float:
    return float(v) * 100.0


def _signal_metrics(frame: pd.DataFrame, pred_col: str) -> dict[str, object]:
    if frame.empty:
        return {
            "window_n": 0,
            "correct": 0,
            "classification_accuracy": None,
            "mae_return_pp": None,
            "sube_accuracy": None,
            "sube_n": 0,
            "baja_accuracy": None,
            "baja_n": 0,
            "neutro_accuracy": None,
            "neutro_n": 0,
        }
    work = frame.dropna(subset=["ret_profuturo", pred_col]).copy()
    work["real_class"] = work["ret_profuturo"].map(_classify)
    work["pred_class"] = work[pred_col].map(_classify)
    work["hit"] = work["real_class"].eq(work["pred_class"])
    out: dict[str, object] = {
        "window_n": int(len(work)),
        "correct": int(work["hit"].sum()),
        "classification_accuracy": float(work["hit"].mean()),
        "mae_return_pp": _pct(float((work[pred_col] - work["ret_profuturo"]).abs().mean())),
    }
    for signal in ["SUBE", "BAJA", "NEUTRO"]:
        subset = work.loc[work["pred_class"] == signal]
        out[f"{signal.lower()}_n"] = int(len(subset))
        out[f"{signal.lower()}_accuracy"] = None if subset.empty else float(subset["hit"].mean())
    return out


def _prepare_huber_data(sbs_raw: pd.DataFrame, markets: pd.DataFrame) -> pd.DataFrame:
    if sbs_raw.empty or markets.empty:
        return pd.DataFrame()
    sbs = sbs_raw.copy()
    mkt = markets.copy()
    sbs["fecha"] = pd.to_datetime(sbs["fecha"], errors="coerce")
    sbs["valor_cuota"] = pd.to_numeric(sbs["valor_cuota"], errors="coerce")
    sbs = sbs.dropna(subset=["fecha", "valor_cuota"]).sort_values("fecha").drop_duplicates("fecha", keep="last")
    sbs["ret_profuturo"] = sbs["valor_cuota"].pct_change(fill_method=None)
    mkt["fecha"] = pd.to_datetime(mkt["fecha"], errors="coerce")
    for feature in FEATURES:
        if feature not in mkt.columns:
            return pd.DataFrame()
        mkt[feature] = pd.to_numeric(mkt[feature], errors="coerce")
    data = sbs[["fecha", "valor_cuota", "ret_profuturo"]].merge(
        mkt[["fecha", *FEATURES]], on="fecha", how="inner"
    )
    return data.dropna(subset=["ret_profuturo", *FEATURES]).sort_values("fecha").reset_index(drop=True)


def _fit_huber(x_train: np.ndarray, y_train: np.ndarray) -> tuple[StandardScaler, HuberRegressor]:
    scaler = StandardScaler()
    x_scaled = scaler.fit_transform(x_train)
    model = HuberRegressor(
        epsilon=HUBER_EPSILON,
        alpha=HUBER_ALPHA,
        fit_intercept=True,
        max_iter=3000,
        tol=1e-8,
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", ConvergenceWarning)
        model.fit(x_scaled, y_train * 100.0)
    return scaler, model


def _huber_coefficients(scaler: StandardScaler, model: HuberRegressor) -> dict[str, float]:
    scale = np.where(np.asarray(scaler.scale_, dtype=float) == 0, 1.0, np.asarray(scaler.scale_, dtype=float))
    coef = np.asarray(model.coef_, dtype=float) / scale / 100.0
    intercept = (
        float(model.intercept_)
        - float(np.sum(np.asarray(model.coef_) * np.asarray(scaler.mean_) / scale))
    ) / 100.0
    return {"intercept": intercept, **{feature: float(value) for feature, value in zip(FEATURES, coef)}}


def _predict_from_coefficients(row: pd.Series, coefficients: dict[str, float]) -> float:
    result = float(coefficients.get("intercept", 0.0))
    for feature in FEATURES:
        result += float(coefficients.get(feature, 0.0)) * float(row[feature])
    return float(result)


def _rolling_huber(data: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    if len(data) <= WINDOW:
        return pd.DataFrame()
    for i in range(WINDOW, len(data)):
        train = data.iloc[i - WINDOW : i]
        row = data.iloc[i]
        scaler, model = _fit_huber(
            train[FEATURES].to_numpy(float),
            train["ret_profuturo"].to_numpy(float),
        )
        pred = float(
            model.predict(scaler.transform(row[FEATURES].to_numpy(float).reshape(1, -1)))[0] / 100.0
        )
        rows.append(
            {
                "fecha": row["fecha"],
                "ret_profuturo": float(row["ret_profuturo"]),
                "ret_estimado_huber": pred,
                "senal_real": _classify(float(row["ret_profuturo"])),
                "senal_huber": _classify(pred),
                "acierto_huber": _classify(float(row["ret_profuturo"])) == _classify(pred),
            }
        )
    return pd.DataFrame(rows)


def _build_huber_challenger(
    latest: dict[str, object],
    hist: pd.DataFrame,
    pending: pd.DataFrame,
    sbs_raw: pd.DataFrame,
    markets: pd.DataFrame,
) -> dict[str, object]:
    data = _prepare_huber_data(sbs_raw, markets)
    if len(data) < WINDOW + 1:
        raise RuntimeError(f"Muestra Huber insuficiente: {len(data)}")

    history = _rolling_huber(data)
    history["fecha"] = pd.to_datetime(history["fecha"], errors="coerce")
    history = history.dropna(subset=["fecha"]).sort_values("fecha").drop_duplicates("fecha", keep="last")
    history.to_csv(DATA / "huber_challenger_predictions.csv", index=False)

    recent_huber = history.tail(WINDOW).copy()
    huber_perf = _signal_metrics(
        recent_huber.rename(columns={"ret_estimado_huber": "ret_estimado"}),
        "ret_estimado",
    )

    paired = hist[["fecha", "ret_profuturo", "ret_estimado"]].merge(
        history[["fecha", "ret_estimado_huber"]], on="fecha", how="inner"
    ).tail(WINDOW)
    paired["real_class"] = paired["ret_profuturo"].map(_classify)
    paired["ols_class"] = paired["ret_estimado"].map(_classify)
    paired["huber_class"] = paired["ret_estimado_huber"].map(_classify)
    paired["ols_hit"] = paired["real_class"].eq(paired["ols_class"])
    paired["huber_hit"] = paired["real_class"].eq(paired["huber_class"])
    corrected = (~paired["ols_hit"]) & paired["huber_hit"]
    new_errors = paired["ols_hit"] & (~paired["huber_hit"])

    train = data.tail(WINDOW).copy()
    scaler, model = _fit_huber(
        train[FEATURES].to_numpy(float),
        train["ret_profuturo"].to_numpy(float),
    )
    coefficients = _huber_coefficients(scaler, model)

    pending_series: list[dict[str, object]] = []
    base_vc = float(latest["latest_sbs_vc"])
    last_sbs_date = pd.Timestamp(str(latest["latest_sbs_date"]))
    if not pending.empty:
        work = pending.copy()
        work["fecha"] = pd.to_datetime(work["fecha"], errors="coerce")
        for feature in FEATURES:
            work[feature] = pd.to_numeric(work.get(feature), errors="coerce")
        work = work.loc[work["fecha"].gt(last_sbs_date)].dropna(
            subset=["fecha", *FEATURES]
        ).sort_values("fecha")
        for _, row in work.iterrows():
            ret = _predict_from_coefficients(row, coefficients)
            base_vc = base_vc * (1.0 + ret)
            pending_series.append(
                {
                    "fecha": row["fecha"].date().isoformat(),
                    "ret_estimado": ret,
                    "senal": _classify(ret),
                    "vc_estimado": base_vc,
                }
            )
    pd.DataFrame(pending_series).to_csv(DATA / "huber_challenger_pending.csv", index=False)

    current = pending_series[-1] if pending_series else None
    ols_accuracy = float(paired["ols_hit"].mean()) if len(paired) else None
    huber_accuracy = float(paired["huber_hit"].mean()) if len(paired) else None
    ols_mae_pp = (
        _pct(float((paired["ret_estimado"] - paired["ret_profuturo"]).abs().mean()))
        if len(paired)
        else None
    )
    huber_mae_pp = (
        _pct(float((paired["ret_estimado_huber"] - paired["ret_profuturo"]).abs().mean()))
        if len(paired)
        else None
    )

    return {
        "status": "CHALLENGER ACTIVO",
        "role": "Modelo paralelo; no reemplaza la señal oficial OLS.",
        "parameters": {
            "window": WINDOW,
            "epsilon": HUBER_EPSILON,
            "alpha": HUBER_ALPHA,
            "selection": "Parámetros elegidos con validación temporal 60/20/20; prueba final independiente favorable.",
        },
        "training": {
            "n": int(len(train)),
            "start": train["fecha"].iloc[0].date().isoformat(),
            "end": train["fecha"].iloc[-1].date().isoformat(),
        },
        "coefficients": coefficients,
        "current": None
        if current is None
        else {
            **current,
            "agrees_with_ols": str(current["senal"]) == str(latest.get("signal")),
            "ols_signal": latest.get("signal"),
            "ols_return_estimated": latest.get("latest_return_estimated"),
        },
        "performance": huber_perf,
        "comparison_vs_ols": {
            "paired_n": int(len(paired)),
            "ols_correct": int(paired["ols_hit"].sum()),
            "huber_correct": int(paired["huber_hit"].sum()),
            "net_correct": int(paired["huber_hit"].sum() - paired["ols_hit"].sum()),
            "ols_accuracy": ols_accuracy,
            "huber_accuracy": huber_accuracy,
            "accuracy_delta_pp": None
            if ols_accuracy is None
            else (huber_accuracy - ols_accuracy) * 100.0,
            "ols_mae_return_pp": ols_mae_pp,
            "huber_mae_return_pp": huber_mae_pp,
            "mae_delta_pp": None if ols_mae_pp is None else huber_mae_pp - ols_mae_pp,
            "corrected_errors": int(corrected.sum()),
            "new_errors": int(new_errors.sum()),
            "corrected_dates": [x.date().isoformat() for x in paired.loc[corrected, "fecha"]],
            "new_error_dates": [x.date().isoformat() for x in paired.loc[new_errors, "fecha"]],
        },
        "pending_series": pending_series,
    }


def main() -> None:
    latest_path = PUBLIC / "latest.json"
    if not latest_path.exists():
        raise RuntimeError("Falta public/data/latest.json")
    latest = json.loads(latest_path.read_text(encoding="utf-8"))

    hist = _read_csv(DATA / "historical_predictions.csv")
    pending = _read_csv(DATA / "pending_predictions.csv")
    sbs_raw = _read_csv(DATA / "sbs_profuturo_f3.csv")
    markets = _read_csv(DATA / "markets.csv")

    if hist.empty:
        raise RuntimeError("Falta histórico OLS para construir métricas")

    for col in ["ret_profuturo", "ret_estimado", "valor_cuota", "valor_cuota_estimado"]:
        hist[col] = pd.to_numeric(hist[col], errors="coerce")
    hist["fecha"] = pd.to_datetime(hist["fecha"], errors="coerce")
    hist = hist.dropna(
        subset=["fecha", "ret_profuturo", "ret_estimado", "valor_cuota", "valor_cuota_estimado"]
    )
    hist = hist.sort_values("fecha").drop_duplicates("fecha", keep="last")
    recent = hist.tail(WINDOW).copy()
    recent["real_class"] = recent["ret_profuturo"].map(_classify)
    recent["pred_class"] = recent["ret_estimado"].map(_classify)
    recent["hit"] = recent["real_class"].eq(recent["pred_class"])

    accuracy = float(recent["hit"].mean()) if len(recent) else np.nan
    mae = float((recent["ret_estimado"] - recent["ret_profuturo"]).abs().mean())
    zero_mae = float(recent["ret_profuturo"].abs().mean())

    prev = recent["ret_profuturo"].shift(1)
    prev_class = prev.map(lambda x: _classify(float(x)) if pd.notna(x) else None)
    valid_prev = prev_class.notna()
    prev_acc = (
        float((prev_class[valid_prev] == recent.loc[valid_prev, "real_class"]).mean())
        if valid_prev.any()
        else np.nan
    )

    by_signal: dict[str, dict[str, object]] = {}
    for signal in ["SUBE", "BAJA", "NEUTRO"]:
        subset = recent.loc[recent["pred_class"] == signal]
        by_signal[signal] = {
            "n": int(len(subset)),
            "accuracy": None if subset.empty else float(subset["hit"].mean()),
        }

    current_signal = str(latest.get("signal", "NEUTRO"))
    current_stats = by_signal.get(current_signal, {"n": 0, "accuracy": None})
    current_accuracy = current_stats.get("accuracy")
    n_current = int(current_stats.get("n", 0) or 0)
    if current_accuracy is None or n_current < 5:
        confidence_label = "MUESTRA BAJA"
    elif float(current_accuracy) >= 0.70:
        confidence_label = "ALTA"
    elif float(current_accuracy) >= 0.55:
        confidence_label = "MEDIA"
    else:
        confidence_label = "BAJA"

    rel_error = (
        (recent["valor_cuota_estimado"] / recent["valor_cuota"] - 1.0)
        .abs()
        .replace([np.inf, -np.inf], np.nan)
        .dropna()
    )
    q80 = float(rel_error.quantile(0.80)) if not rel_error.empty else 0.0
    q90 = float(rel_error.quantile(0.90)) if not rel_error.empty else 0.0

    contributions: list[dict[str, object]] = []
    beta = latest.get("coefficients", {}) or {}
    if not pending.empty:
        pending["fecha"] = pd.to_datetime(pending["fecha"], errors="coerce")
        row = pending.sort_values("fecha").iloc[-1]
        contributions.append(
            {
                "feature": "intercept",
                "label": "Base",
                "value": 1.0,
                "coefficient": float(beta.get("intercept", 0.0)),
                "contribution_pp": _pct(float(beta.get("intercept", 0.0))),
            }
        )
        for feature in FEATURES:
            value = pd.to_numeric(pd.Series([row.get(feature)]), errors="coerce").iloc[0]
            coef = float(beta.get(feature, 0.0))
            if pd.notna(value):
                contributions.append(
                    {
                        "feature": feature,
                        "label": LABELS[feature],
                        "value": float(value),
                        "coefficient": coef,
                        "contribution_pp": _pct(coef * float(value)),
                    }
                )
    contributions.sort(key=lambda x: abs(float(x["contribution_pp"])), reverse=True)

    quality_critical: list[str] = []
    quality_warnings: list[str] = []

    if int(latest.get("training_n", 0)) != WINDOW:
        quality_critical.append(f"Ventana OLS {latest.get('training_n')} / {WINDOW}")
    if "ret_EEM" not in beta:
        quality_critical.append("El modelo publicado no contiene el factor EEM")

    if sbs_raw.empty:
        quality_critical.append("Serie SBS vacía")
        sbs = pd.DataFrame()
    else:
        sbs_raw["fecha"] = pd.to_datetime(sbs_raw["fecha"], errors="coerce")
        sbs_raw["valor_cuota"] = pd.to_numeric(sbs_raw["valor_cuota"], errors="coerce")
        dup = int(sbs_raw["fecha"].duplicated(keep=False).sum())
        if dup:
            quality_critical.append(f"{dup} fechas SBS duplicadas")
        if (sbs_raw["valor_cuota"] <= 0).fillna(True).any():
            quality_critical.append("Valor cuota SBS inválido")
        sbs = (
            sbs_raw.dropna(subset=["fecha", "valor_cuota"])
            .sort_values("fecha")
            .drop_duplicates("fecha", keep="last")
        )

    if not markets.empty and not sbs.empty:
        markets["fecha"] = pd.to_datetime(markets["fecha"], errors="coerce")
        equity_cols = ["SPY", "NEM", "FCX", "EPU", "MCHI", "EEM"]
        available = [c for c in equity_cols if c in markets.columns]
        if len(available) != len(equity_cols):
            quality_critical.append("Falta EEM o algún ETF del modelo en markets.csv")
        else:
            last_sbs = pd.Timestamp(latest["latest_sbs_date"])
            start = last_sbs - pd.Timedelta(days=45)
            candidate = markets.loc[
                markets["fecha"].between(start, last_sbs)
                & markets[available].notna().all(axis=1),
                "fecha",
            ].dropna()
            candidate = {
                pd.Timestamp(x).normalize()
                for x in candidate
                if pd.Timestamp(x).weekday() < 5
            }
            sbs_dates = {pd.Timestamp(x).normalize() for x in sbs["fecha"]}
            possible = sorted(candidate - sbs_dates)
            if possible:
                quality_warnings.append(
                    "Posibles fechas SBS a revisar: "
                    + ", ".join(x.strftime("%d/%m") for x in possible[-6:])
                )

    fx_source = str(latest.get("latest_fx_source", "BCRP"))
    fx_provisional = bool(latest.get("latest_fx_provisional", False))
    if fx_provisional:
        quality_warnings.append(f"FX provisional: {fx_source}")

    if not pending.empty:
        last_pending = pending.iloc[-1]
        missing_features = [
            f
            for f in FEATURES
            if pd.isna(
                pd.to_numeric(pd.Series([last_pending.get(f)]), errors="coerce").iloc[0]
            )
        ]
        if missing_features:
            quality_critical.append("Faltan variables: " + ", ".join(missing_features))

    challenger_huber: dict[str, object]
    try:
        challenger_huber = _build_huber_challenger(latest, hist, pending, sbs_raw, markets)
    except Exception as exc:
        challenger_huber = {
            "status": "NO DISPONIBLE",
            "role": "El challenger no reemplaza la señal oficial OLS.",
            "error": str(exc),
        }
        quality_warnings.append(f"Huber challenger no disponible: {exc}")

    if quality_critical:
        quality_status = "REVISAR"
    elif quality_warnings:
        quality_status = "PROVISIONAL"
    else:
        quality_status = "OK"

    improvement = None
    if zero_mae > 0:
        improvement = float((zero_mae - mae) / zero_mae)

    payload = {
        "generated_for": latest.get("latest_estimate_date"),
        "current_signal": current_signal,
        "confidence": {
            "label": confidence_label,
            "historical_accuracy": current_accuracy,
            "n": n_current,
            "description": "Acierto histórico de la misma clase de señal en las últimas 90 observaciones OLS; no es una probabilidad garantizada.",
        },
        "performance": {
            "window_n": int(len(recent)),
            "classification_accuracy": accuracy,
            "mae_return_pp": _pct(mae),
            "sube_accuracy": by_signal["SUBE"]["accuracy"],
            "sube_n": by_signal["SUBE"]["n"],
            "baja_accuracy": by_signal["BAJA"]["accuracy"],
            "baja_n": by_signal["BAJA"]["n"],
            "neutro_accuracy": by_signal["NEUTRO"]["accuracy"],
            "neutro_n": by_signal["NEUTRO"]["n"],
        },
        "challenger_huber": challenger_huber,
        "uncertainty": {
            "relative_q80": q80,
            "relative_q90": q90,
            "label": "Banda empírica 80%",
            "description": "Se deriva de los errores relativos históricos del VC estimado. Para días encadenados pendientes se amplía con la raíz del horizonte.",
        },
        "benchmarks": {
            "zero_change_mae_pp": _pct(zero_mae),
            "ols_mae_pp": _pct(mae),
            "ols_mae_improvement_vs_zero": improvement,
            "previous_direction_accuracy": prev_acc,
        },
        "contributions": contributions,
        "quality": {
            "status": quality_status,
            "critical": quality_critical,
            "warnings": quality_warnings,
            "training_n": int(latest.get("training_n", 0)),
            "latest_sbs_date": latest.get("latest_sbs_date"),
            "fx_source": fx_source,
            "fx_provisional": fx_provisional,
        },
    }

    PUBLIC.mkdir(parents=True, exist_ok=True)
    (PUBLIC / "model_insights.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if quality_critical:
        raise AssertionError(" | ".join(quality_critical))

    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
