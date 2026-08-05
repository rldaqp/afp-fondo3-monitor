from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "rolling90"
PUBLIC_DATA = ROOT / "public" / "data"

SBS_PATH = DATA / "sbs_profuturo_f3.csv"
MARKETS_PATH = DATA / "markets.csv"
REFERENCE_PATH = DATA / "notebook_training_reference.csv"
BACKFILL_PATH = DATA / "historical_calendar_predictions.csv"
SIGNALS_PATH = PUBLIC_DATA / "signals.json"

ASSETS = ["SPY", "NEM", "FCX", "EPU", "MCHI", "EEM"]
FEATURES = [f"ret_{asset}" for asset in ASSETS] + ["ret_USD_PEN"]
WINDOW = 90
THRESHOLD = 0.001
MODEL_START = pd.Timestamp("2025-01-01")
REFERENCE_END = pd.Timestamp("2026-07-20")


def classify(value: float) -> str:
    if value > THRESHOLD:
        return "SUBE"
    if value < -THRESHOLD:
        return "BAJA"
    return "NEUTRO"


def fit_ols(train: pd.DataFrame) -> np.ndarray:
    x = train[FEATURES].to_numpy(dtype=float)
    y = train["ret_profuturo"].to_numpy(dtype=float)
    return np.linalg.lstsq(np.c_[np.ones(len(x)), x], y, rcond=None)[0]


def predict(beta: np.ndarray, features: dict[str, float]) -> float:
    values = np.array([features[name] for name in FEATURES], dtype=float)
    return float(np.r_[1.0, values] @ beta)


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        raise RuntimeError(f"Falta archivo requerido: {path}")
    return pd.read_csv(path)


def normalize_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    sbs = read_csv(SBS_PATH)
    markets = read_csv(MARKETS_PATH)
    reference = read_csv(REFERENCE_PATH)

    sbs["fecha"] = pd.to_datetime(sbs["fecha"], errors="coerce")
    sbs["valor_cuota"] = pd.to_numeric(sbs["valor_cuota"], errors="coerce")
    sbs = (
        sbs.dropna(subset=["fecha", "valor_cuota"])
        .sort_values("fecha")
        .drop_duplicates("fecha", keep="last")
        .reset_index(drop=True)
    )
    sbs["ret_profuturo"] = sbs["valor_cuota"].pct_change(fill_method=None)

    markets["fecha"] = pd.to_datetime(markets["fecha"], errors="coerce")
    markets = (
        markets.dropna(subset=["fecha"])
        .sort_values("fecha")
        .drop_duplicates("fecha", keep="last")
        .reset_index(drop=True)
    )
    for feature in FEATURES:
        if feature not in markets.columns:
            markets[feature] = np.nan
        markets[feature] = pd.to_numeric(markets[feature], errors="coerce")

    reference["fecha"] = pd.to_datetime(reference["fecha"], errors="coerce")
    for column in ["valor_cuota", "ret_profuturo", *FEATURES]:
        if column not in reference.columns:
            raise RuntimeError(f"La referencia canónica no contiene {column}")
        reference[column] = pd.to_numeric(reference[column], errors="coerce")
    reference = (
        reference.dropna(subset=["fecha", "valor_cuota", "ret_profuturo", *FEATURES])
        .sort_values("fecha")
        .drop_duplicates("fecha", keep="last")
        .reset_index(drop=True)
    )
    if len(reference) != WINDOW or reference["fecha"].max() != REFERENCE_END:
        raise RuntimeError(
            "Referencia canónica inválida: "
            f"filas={len(reference)} fin={reference['fecha'].max()}"
        )
    return sbs, markets, reference


def complete_training_rows(sbs: pd.DataFrame, markets: pd.DataFrame) -> pd.DataFrame:
    complete = sbs.merge(
        markets[["fecha", *FEATURES]],
        on="fecha",
        how="inner",
        validate="one_to_one",
    )
    return (
        complete.loc[complete["fecha"] >= MODEL_START]
        .dropna(subset=["valor_cuota", "ret_profuturo", *FEATURES])
        .sort_values("fecha")
        .drop_duplicates("fecha", keep="last")
        .reset_index(drop=True)
    )


def training_for_date(
    date_value: pd.Timestamp,
    complete: pd.DataFrame,
    reference: pd.DataFrame,
) -> pd.DataFrame:
    columns = ["fecha", "valor_cuota", "ret_profuturo", *FEATURES]
    if date_value <= REFERENCE_END:
        train = complete.loc[complete["fecha"] < date_value, columns].tail(WINDOW)
    else:
        future = complete.loc[
            (complete["fecha"] > REFERENCE_END)
            & (complete["fecha"] < date_value),
            columns,
        ]
        canonical = (
            pd.concat([reference[columns], future], ignore_index=True)
            .sort_values("fecha")
            .drop_duplicates("fecha", keep="last")
        )
        train = canonical.tail(WINDOW)
    if len(train) != WINDOW:
        raise RuntimeError(
            f"No hay {WINDOW} observaciones previas para {date_value:%Y-%m-%d}; "
            f"solo {len(train)}"
        )
    return train.reset_index(drop=True)


def feature_values_for_date(
    date_value: pd.Timestamp,
    markets: pd.DataFrame,
) -> tuple[dict[str, float], list[str]]:
    exact = markets.loc[markets["fecha"].eq(date_value)]
    row = exact.iloc[-1] if not exact.empty else pd.Series(dtype=object)
    values: dict[str, float] = {}
    imputed: list[str] = []
    for feature in FEATURES:
        value = pd.to_numeric(row.get(feature), errors="coerce")
        if pd.isna(value):
            values[feature] = 0.0
            imputed.append(feature)
        else:
            values[feature] = float(value)
    return values, imputed


def existing_historical_signals() -> list[dict[str, object]]:
    if not SIGNALS_PATH.exists():
        raise RuntimeError(f"Falta {SIGNALS_PATH}")
    payload = json.loads(SIGNALS_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise RuntimeError("signals.json no contiene una lista")
    return payload


def main() -> None:
    sbs, markets, reference = normalize_inputs()
    complete = complete_training_rows(sbs, markets)
    signals = existing_historical_signals()

    existing_dates = {
        pd.Timestamp(row["fecha"])
        for row in signals
        if row.get("tipo") == "HISTORICO"
        and row.get("ret_estimado") is not None
        and row.get("vc_estimado") is not None
    }
    if not existing_dates:
        raise RuntimeError("No existen señales históricas para definir el inicio del modelo")
    first_signal_date = min(existing_dates)

    eligible_dates = [
        pd.Timestamp(value)
        for value in sbs.loc[sbs["fecha"] >= first_signal_date, "fecha"]
    ]
    missing_dates = sorted(set(eligible_dates) - existing_dates)

    backfills: list[dict[str, object]] = []
    public_rows: list[dict[str, object]] = []
    for date_value in missing_dates:
        current = sbs.loc[sbs["fecha"].eq(date_value)]
        previous = sbs.loc[sbs["fecha"] < date_value].tail(1)
        if current.empty or previous.empty:
            raise RuntimeError(f"No se pudo obtener base SBS para {date_value:%Y-%m-%d}")

        train = training_for_date(date_value, complete, reference)
        feature_values, imputed = feature_values_for_date(date_value, markets)
        beta = fit_ols(train)
        estimated_return = predict(beta, feature_values)

        official_vc = float(current.iloc[-1]["valor_cuota"])
        previous_vc = float(previous.iloc[-1]["valor_cuota"])
        estimated_vc = previous_vc * (1.0 + estimated_return)
        official_return = official_vc / previous_vc - 1.0
        signal = classify(estimated_return)
        imputed_text = "|".join(imputed)

        backfills.append(
            {
                "fecha": date_value.strftime("%Y-%m-%d"),
                "modelo": "OLS CALENDARIO COMPLETO",
                "valor_cuota": official_vc,
                "valor_cuota_anterior": previous_vc,
                "ret_profuturo": official_return,
                "ret_estimado": estimated_return,
                "valor_cuota_estimado": estimated_vc,
                "senal": signal,
                "ventana_inicio": train.iloc[0]["fecha"].strftime("%Y-%m-%d"),
                "ventana_fin": train.iloc[-1]["fecha"].strftime("%Y-%m-%d"),
                "n_entrenamiento": WINDOW,
                "fuentes_imputadas_0": imputed_text,
                "metodo_calendario": (
                    "Factores sin publicación en la fecha se consideran 0%; "
                    "no ingresan como observación nueva al entrenamiento"
                ),
            }
        )
        public_rows.append(
            {
                "fecha": date_value.strftime("%Y-%m-%d"),
                "ret_estimado": estimated_return,
                "senal": signal,
                "vc_real": official_vc,
                "vc_estimado": estimated_vc,
                "tipo": "HISTORICO",
                "estado_fuentes": (
                    "CALENDARIO COMPLETO"
                    if not imputed
                    else "CALENDARIO COMPLETO · 0%: " + ", ".join(imputed)
                ),
                "calendario_completado": True,
            }
        )

    columns = [
        "fecha",
        "modelo",
        "valor_cuota",
        "valor_cuota_anterior",
        "ret_profuturo",
        "ret_estimado",
        "valor_cuota_estimado",
        "senal",
        "ventana_inicio",
        "ventana_fin",
        "n_entrenamiento",
        "fuentes_imputadas_0",
        "metodo_calendario",
    ]
    pd.DataFrame(backfills, columns=columns).to_csv(
        BACKFILL_PATH,
        index=False,
        encoding="utf-8",
    )

    by_key: dict[tuple[str, str], dict[str, object]] = {}
    for row in signals:
        by_key[(str(row.get("fecha")), str(row.get("tipo")))] = row
    for row in public_rows:
        by_key[(str(row["fecha"]), "HISTORICO")] = row

    merged = sorted(
        by_key.values(),
        key=lambda row: (str(row.get("fecha")), str(row.get("tipo"))),
    )
    SIGNALS_PATH.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    final_historical = {
        pd.Timestamp(row["fecha"])
        for row in merged
        if row.get("tipo") == "HISTORICO"
        and row.get("ret_estimado") is not None
        and row.get("vc_estimado") is not None
    }
    still_missing = sorted(set(eligible_dates) - final_historical)
    if still_missing:
        raise RuntimeError(
            "Persisten fechas oficiales sin OLS: "
            + ", ".join(value.strftime("%Y-%m-%d") for value in still_missing)
        )

    formatted = ", ".join(value.strftime("%Y-%m-%d") for value in missing_dates)
    print(
        "Calendario OLS Profuturo completo · "
        f"{len(missing_dates)} fechas restauradas"
        + (f": {formatted}" if formatted else "")
    )


if __name__ == "__main__":
    main()
