from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "rolling90"
PUBLIC = ROOT / "public" / "data"
THRESHOLD = 0.001
WINDOW = 90
FEATURES = ["ret_SPY", "ret_NEM", "ret_FCX", "ret_EPU", "ret_MCHI", "ret_USD_PEN"]
LABELS = {
    "ret_SPY": "SPY",
    "ret_NEM": "NEM",
    "ret_FCX": "FCX",
    "ret_EPU": "EPU",
    "ret_MCHI": "MCHI",
    "ret_USD_PEN": "USD/PEN",
}


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
    hist = hist.dropna(subset=["fecha", "ret_profuturo", "ret_estimado", "valor_cuota", "valor_cuota_estimado"])
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
    prev_acc = float((prev_class[valid_prev] == recent.loc[valid_prev, "real_class"]).mean()) if valid_prev.any() else np.nan

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

    rel_error = (recent["valor_cuota_estimado"] / recent["valor_cuota"] - 1.0).abs().replace([np.inf, -np.inf], np.nan).dropna()
    q80 = float(rel_error.quantile(0.80)) if not rel_error.empty else 0.0
    q90 = float(rel_error.quantile(0.90)) if not rel_error.empty else 0.0

    contributions: list[dict[str, object]] = []
    beta = latest.get("coefficients", {}) or {}
    if not pending.empty:
        pending["fecha"] = pd.to_datetime(pending["fecha"], errors="coerce")
        row = pending.sort_values("fecha").iloc[-1]
        contributions.append({
            "feature": "intercept",
            "label": "Base",
            "value": 1.0,
            "coefficient": float(beta.get("intercept", 0.0)),
            "contribution_pp": _pct(float(beta.get("intercept", 0.0))),
        })
        for feature in FEATURES:
            value = pd.to_numeric(pd.Series([row.get(feature)]), errors="coerce").iloc[0]
            coef = float(beta.get(feature, 0.0))
            if pd.notna(value):
                contributions.append({
                    "feature": feature,
                    "label": LABELS[feature],
                    "value": float(value),
                    "coefficient": coef,
                    "contribution_pp": _pct(coef * float(value)),
                })
    contributions.sort(key=lambda x: abs(float(x["contribution_pp"])), reverse=True)

    # Calidad de datos: controles críticos + avisos. Los posibles huecos SBS solo se
    # marcan para revisión porque un feriado peruano puede ser legítimo.
    quality_critical: list[str] = []
    quality_warnings: list[str] = []

    if int(latest.get("training_n", 0)) != WINDOW:
        quality_critical.append(f"Ventana OLS {latest.get('training_n')} / {WINDOW}")

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
        sbs = sbs_raw.dropna(subset=["fecha", "valor_cuota"]).sort_values("fecha").drop_duplicates("fecha", keep="last")

    if not markets.empty and not sbs.empty:
        markets["fecha"] = pd.to_datetime(markets["fecha"], errors="coerce")
        equity_cols = ["SPY", "NEM", "FCX", "EPU", "MCHI"]
        available = [c for c in equity_cols if c in markets.columns]
        if len(available) == len(equity_cols):
            last_sbs = pd.Timestamp(latest["latest_sbs_date"])
            start = last_sbs - pd.Timedelta(days=45)
            candidate = markets.loc[
                markets["fecha"].between(start, last_sbs)
                & markets[available].notna().all(axis=1),
                "fecha",
            ].dropna()
            candidate = {pd.Timestamp(x).normalize() for x in candidate if pd.Timestamp(x).weekday() < 5}
            sbs_dates = {pd.Timestamp(x).normalize() for x in sbs["fecha"]}
            possible = sorted(candidate - sbs_dates)
            if possible:
                quality_warnings.append(
                    "Posibles fechas SBS a revisar: " + ", ".join(x.strftime("%d/%m") for x in possible[-6:])
                )

    fx_source = str(latest.get("latest_fx_source", "BCRP"))
    fx_provisional = bool(latest.get("latest_fx_provisional", False))
    if fx_provisional:
        quality_warnings.append(f"FX provisional: {fx_source}")

    if not pending.empty:
        last_pending = pending.iloc[-1]
        missing_features = [f for f in FEATURES if pd.isna(pd.to_numeric(pd.Series([last_pending.get(f)]), errors="coerce").iloc[0])]
        if missing_features:
            quality_critical.append("Faltan variables: " + ", ".join(missing_features))

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
    (PUBLIC / "model_insights.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # Controles críticos: si fallan, no debe publicarse el visor.
    if quality_critical:
        raise AssertionError(" | ".join(quality_critical))

    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
