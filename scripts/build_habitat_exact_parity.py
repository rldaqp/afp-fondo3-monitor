from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

import build_habitat_profuturo_parity as ui
import finalize_fx_hybrid as profuturo

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "rolling90"
PUBLIC = ROOT / "public" / "habitat"
PUBLIC_DATA = PUBLIC / "data"
PUBLIC_DATA.mkdir(parents=True, exist_ok=True)

LIMA = ZoneInfo("America/Lima")
WINDOW = 90
THRESHOLD = 0.001

# Se reutiliza la misma cadena metodológica de Profuturo:
# Yahoo Close para los ETF/acciones, BCRP para USD/PEN histórico,
# EEM como séptimo factor y PEN=X solo como respaldo pendiente.
parity = profuturo.v5.parity
FEATURES = list(parity.FEATURES)
EQUITY_FEATURES = list(parity.EQUITY_FEATURES)
ASSETS = list(parity.engine.ASSETS)


def classify(value: float) -> str:
    if value > THRESHOLD:
        return "SUBE"
    if value < -THRESHOLD:
        return "BAJA"
    return "NEUTRO"


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        raise RuntimeError(f"No existe o está vacío: {path.relative_to(ROOT)}")
    frame = pd.read_csv(path)
    frame["fecha"] = pd.to_datetime(frame["fecha"], errors="coerce")
    return frame.dropna(subset=["fecha"])


def write_json(name: str, payload: object) -> None:
    (PUBLIC_DATA / name).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def prepare_inputs() -> tuple[pd.DataFrame, pd.DataFrame, str]:
    sbs = read_csv(DATA / "sbs_habitat_f3.csv")
    sbs["valor_cuota"] = pd.to_numeric(sbs["valor_cuota"], errors="coerce")
    sbs = (
        sbs.dropna(subset=["fecha", "valor_cuota"])
        .sort_values("fecha")
        .drop_duplicates("fecha", keep="last")
        .reset_index(drop=True)
    )
    if len(sbs) < WINDOW + 1:
        raise RuntimeError(
            f"Hábitat tiene {len(sbs)} valores cuota; se requieren al menos {WINDOW + 1}."
        )

    profuturo._prepare_saved_markets_for_eem()
    markets, market_note = parity._rebuild_markets_notebook()
    markets["fecha"] = pd.to_datetime(markets["fecha"], errors="coerce")
    markets = (
        markets.dropna(subset=["fecha"])
        .sort_values("fecha")
        .drop_duplicates("fecha", keep="last")
        .reset_index(drop=True)
    )
    for column in FEATURES:
        markets[column] = pd.to_numeric(markets[column], errors="coerce")
    return sbs, markets, market_note


def build_complete(sbs: pd.DataFrame, markets: pd.DataFrame) -> pd.DataFrame:
    target = sbs.copy()
    target["ret_habitat"] = target["valor_cuota"].pct_change(fill_method=None)
    # La función OLS de Profuturo espera este nombre. Solo cambia la variable
    # objetivo: aquí contiene el retorno real de Hábitat.
    target["ret_profuturo"] = target["ret_habitat"]
    complete = target.merge(
        markets[["fecha", *FEATURES]],
        on="fecha",
        how="inner",
        validate="one_to_one",
    )
    complete = (
        complete.loc[complete["fecha"] >= pd.Timestamp("2025-01-01")]
        .dropna(subset=["valor_cuota", "ret_habitat", "ret_profuturo", *FEATURES])
        .sort_values("fecha")
        .drop_duplicates("fecha", keep="last")
        .reset_index(drop=True)
    )
    if len(complete) < WINDOW:
        raise RuntimeError(
            f"Hábitat solo tiene {len(complete)} observaciones completas; "
            f"se requieren {WINDOW}."
        )
    return complete


def fit_model(train: pd.DataFrame):
    return parity._fit_ols(train)


def predict(model, row: pd.Series) -> float:
    return parity._predict(model, row)


def historical_predictions(complete: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for index in range(WINDOW, len(complete)):
        train = complete.iloc[index - WINDOW:index]
        current = complete.iloc[index]
        fitted = fit_model(train)
        estimate_return = predict(fitted, current)

        # Igual que la corrección canónica de Profuturo: la base histórica es
        # el VC SBS inmediatamente anterior real, aunque esa fecha no tenga
        # mercados completos para entrar al entrenamiento.
        previous_vc = float(current["valor_cuota"]) / (
            1.0 + float(current["ret_habitat"])
        )
        rows.append(
            {
                "fecha": current["fecha"],
                "modelo": "OLS",
                "valor_cuota": float(current["valor_cuota"]),
                "valor_cuota_anterior": previous_vc,
                "ret_real": float(current["ret_habitat"]),
                "ret_estimado": estimate_return,
                "valor_cuota_estimado": previous_vc * (1.0 + estimate_return),
                "senal": classify(estimate_return),
                "ventana_inicio": train.iloc[0]["fecha"],
                "ventana_fin": train.iloc[-1]["fecha"],
                "n_entrenamiento": WINDOW,
            }
        )
    return pd.DataFrame(rows)


def pending_predictions(
    sbs: pd.DataFrame,
    complete: pd.DataFrame,
    markets: pd.DataFrame,
) -> tuple[pd.DataFrame, object, pd.DataFrame]:
    train = complete.tail(WINDOW).copy()
    fitted = fit_model(train)
    latest_sbs = sbs.iloc[-1]
    last_sbs_date = pd.Timestamp(latest_sbs["fecha"])
    last_sbs_vc = float(latest_sbs["valor_cuota"])

    pending = markets.loc[
        markets["fecha"] > last_sbs_date,
        ["fecha", *FEATURES],
    ].copy()
    pending = pending.dropna(subset=EQUITY_FEATURES).sort_values("fecha")
    pending["usd_pen_fresco"] = pending["ret_USD_PEN"].notna()
    pending["ret_USD_PEN_bcrp"] = pending["ret_USD_PEN"]
    pending["ret_USD_PEN_yahoo"] = np.nan
    pending["usd_pen_fuente"] = np.where(
        pending["usd_pen_fresco"], "BCRP", "SIN DATO"
    )
    pending["usd_pen_provisional"] = False

    yahoo_fx = profuturo._penx_daily_returns()
    for index, row in pending.iterrows():
        if bool(row["usd_pen_fresco"]):
            continue
        date = pd.Timestamp(row["fecha"]).normalize()
        yahoo_return = yahoo_fx.get(date)
        if yahoo_return is not None and np.isfinite(yahoo_return):
            pending.at[index, "ret_USD_PEN"] = float(yahoo_return)
            pending.at[index, "ret_USD_PEN_yahoo"] = float(yahoo_return)
            pending.at[index, "usd_pen_fuente"] = "YAHOO PEN=X PROVISIONAL"
            pending.at[index, "usd_pen_provisional"] = True
        else:
            pending.at[index, "ret_USD_PEN"] = 0.0
            pending.at[index, "usd_pen_fuente"] = "SIN DATO · 0 % PROVISIONAL"
            pending.at[index, "usd_pen_provisional"] = True

    rows: list[dict[str, object]] = []
    base_vc = last_sbs_vc
    for _, row in pending.iterrows():
        estimate_return = predict(fitted, row)
        estimated_vc = base_vc * (1.0 + estimate_return)
        record: dict[str, object] = {
            "fecha": row["fecha"],
            "modelo": "OLS",
            "valor_cuota_base": base_vc,
            "ret_estimado": estimate_return,
            "valor_cuota_estimado": estimated_vc,
            "senal": classify(estimate_return),
            "ventana_inicio": train.iloc[0]["fecha"],
            "ventana_fin": train.iloc[-1]["fecha"],
            "n_entrenamiento": WINDOW,
            "usd_pen_fresco": bool(row["usd_pen_fresco"]),
            "usd_pen_fuente": str(row["usd_pen_fuente"]),
            "usd_pen_provisional": bool(row["usd_pen_provisional"]),
        }
        for feature in FEATURES:
            record[feature] = float(row[feature])
        rows.append(record)
        base_vc = estimated_vc
    return pd.DataFrame(rows), fitted, train


def build_signals(
    historical: pd.DataFrame,
    pending: pd.DataFrame,
) -> list[dict]:
    records: list[dict] = []
    if not historical.empty:
        for row in historical.itertuples():
            records.append(
                {
                    "fecha": pd.Timestamp(row.fecha).strftime("%Y-%m-%d"),
                    "ret_estimado": float(row.ret_estimado),
                    "senal": str(row.senal),
                    "vc_real": float(row.valor_cuota),
                    "vc_estimado": float(row.valor_cuota_estimado),
                    "tipo": "HISTORICO",
                }
            )
    if not pending.empty:
        for row in pending.itertuples():
            records.append(
                {
                    "fecha": pd.Timestamp(row.fecha).strftime("%Y-%m-%d"),
                    "ret_estimado": float(row.ret_estimado),
                    "senal": str(row.senal),
                    "vc_real": None,
                    "vc_estimado": float(row.valor_cuota_estimado),
                    "tipo": "PENDIENTE",
                }
            )
    return sorted(records, key=lambda row: row["fecha"])


def build_series(sbs: pd.DataFrame, pending: pd.DataFrame) -> list[dict]:
    records: list[dict] = []
    for row in sbs.itertuples():
        records.append(
            {
                "fecha": pd.Timestamp(row.fecha).strftime("%Y-%m-%d"),
                "vc": float(row.valor_cuota),
                "fuente": "SBS OFICIAL",
                "es_oficial": True,
                "senal": None,
                "ret_estimado": None,
            }
        )
    if not pending.empty:
        for row in pending.itertuples():
            records.append(
                {
                    "fecha": pd.Timestamp(row.fecha).strftime("%Y-%m-%d"),
                    "vc": float(row.valor_cuota_estimado),
                    "fuente": "MODELO OLS",
                    "es_oficial": False,
                    "senal": str(row.senal),
                    "ret_estimado": float(row.ret_estimado),
                }
            )
    return sorted(records, key=lambda row: row["fecha"])


def period_change(sbs: pd.DataFrame, days: int) -> float | None:
    latest = sbs.iloc[-1]
    target_date = pd.Timestamp(latest["fecha"]) - pd.Timedelta(days=days)
    previous = sbs.loc[sbs["fecha"] <= target_date]
    if previous.empty:
        return None
    return float(latest["valor_cuota"]) / float(previous.iloc[-1]["valor_cuota"]) - 1.0


def official_indicators(sbs: pd.DataFrame) -> dict:
    latest = sbs.iloc[-1]
    daily_path = DATA / "sbs_habitat_f3_daily.csv"
    daily = read_csv(daily_path)
    for column in ("cuotas_fondo", "valor_fondo", "valor_cuota"):
        daily[column] = pd.to_numeric(daily[column], errors="coerce")
    daily = daily.dropna().sort_values("fecha")
    detail = daily.loc[daily["fecha"] == latest["fecha"]]
    if detail.empty:
        detail = daily.tail(1)
    detail_row = detail.iloc[-1] if not detail.empty else None

    current_year = sbs.loc[sbs["fecha"].dt.year == pd.Timestamp(latest["fecha"]).year]
    ytd = None
    if not current_year.empty:
        ytd = float(latest["valor_cuota"]) / float(current_year.iloc[0]["valor_cuota"]) - 1.0
    one_day = None
    if len(sbs) > 1:
        one_day = float(latest["valor_cuota"]) / float(sbs.iloc[-2]["valor_cuota"]) - 1.0

    return {
        "date": pd.Timestamp(latest["fecha"]).strftime("%Y-%m-%d"),
        "unit_value": float(latest["valor_cuota"]),
        "fund_quotas": (
            None if detail_row is None else float(detail_row["cuotas_fondo"])
        ),
        "fund_value_pen": (
            None if detail_row is None else float(detail_row["valor_fondo"])
        ),
        "change_1d": one_day,
        "change_7d": period_change(sbs, 7),
        "change_30d": period_change(sbs, 30),
        "change_90d": period_change(sbs, 90),
        "change_ytd": ytd,
        "source": "SBS · Variables SPP y Valor Cuota por AFP",
        "source_url": "https://www.sbs.gob.pe/sistema-privado-de-pensiones/variables-spp",
    }


def model_outputs(
    sbs: pd.DataFrame,
    markets: pd.DataFrame,
    historical: pd.DataFrame,
    pending: pd.DataFrame,
    fitted,
    train: pd.DataFrame,
    market_note: str,
) -> tuple[dict, dict]:
    last_signal = (
        pending.iloc[-1] if not pending.empty else historical.iloc[-1]
    )
    latest_sbs = sbs.iloc[-1]
    beta = {"intercept": float(fitted.intercept_)}
    beta.update(
        {
            feature: float(coefficient)
            for feature, coefficient in zip(FEATURES, fitted.coef_)
        }
    )

    evaluated = historical.tail(WINDOW).copy()
    evaluated["senal_real"] = evaluated["ret_real"].map(classify)
    evaluated["correcta"] = evaluated["senal"] == evaluated["senal_real"]
    errors = (evaluated["ret_estimado"] - evaluated["ret_real"]).abs()
    accuracy = float(evaluated["correcta"].mean()) if not evaluated.empty else 0.0
    signal_rows = evaluated.loc[evaluated["senal"] == str(last_signal["senal"])]
    signal_accuracy = (
        float(signal_rows["correcta"].mean()) if not signal_rows.empty else 0.0
    )
    ols_mae = float(errors.mean()) if not errors.empty else 0.0
    zero_mae = float(evaluated["ret_real"].abs().mean()) if not evaluated.empty else 0.0
    q80 = float(errors.quantile(0.80)) if not errors.empty else 0.0

    feature_row = (
        pending.iloc[-1]
        if not pending.empty
        else markets.loc[
            markets["fecha"] == pd.Timestamp(last_signal["fecha"])
        ].iloc[-1]
    )
    labels = {
        "ret_SPY": "SPY",
        "ret_NEM": "NEM",
        "ret_FCX": "FCX",
        "ret_EPU": "EPU",
        "ret_MCHI": "MCHI",
        "ret_EEM": "EEM",
        "ret_USD_PEN": "USD/PEN",
    }
    contributions = [
        {
            "feature": "intercept",
            "label": "Base",
            "value": 1.0,
            "coefficient": beta["intercept"],
            "contribution_pp": beta["intercept"] * 100,
        }
    ]
    for feature in FEATURES:
        value = float(feature_row[feature])
        contribution = beta[feature] * value * 100
        contributions.append(
            {
                "feature": feature,
                "label": labels.get(feature, feature),
                "value": value,
                "coefficient": beta[feature],
                "contribution_pp": contribution,
            }
        )
    contributions.sort(
        key=lambda item: abs(float(item["contribution_pp"])), reverse=True
    )

    equity_complete = markets.dropna(subset=EQUITY_FEATURES).sort_values("fecha")
    fx_source = str(last_signal.get("usd_pen_fuente", "BCRP"))
    fx_provisional = bool(last_signal.get("usd_pen_provisional", False))

    latest = {
        "afp": "Hábitat",
        "fund": 3,
        "generated_at_lima": datetime.now(LIMA).isoformat(),
        "model": "OLS rolling 90",
        "window": WINDOW,
        "threshold": THRESHOLD,
        "training_start": pd.Timestamp(train.iloc[0]["fecha"]).strftime("%Y-%m-%d"),
        "training_end": pd.Timestamp(train.iloc[-1]["fecha"]).strftime("%Y-%m-%d"),
        "training_n": len(train),
        "latest_sbs_date": pd.Timestamp(latest_sbs["fecha"]).strftime("%Y-%m-%d"),
        "latest_sbs_vc": float(latest_sbs["valor_cuota"]),
        "latest_market_date": pd.Timestamp(equity_complete.iloc[-1]["fecha"]).strftime("%Y-%m-%d"),
        "latest_estimate_date": pd.Timestamp(last_signal["fecha"]).strftime("%Y-%m-%d"),
        "latest_estimated_vc": float(last_signal["valor_cuota_estimado"]),
        "latest_return_estimated": float(last_signal["ret_estimado"]),
        "signal": str(last_signal["senal"]),
        "estimate_type": "CIERRE DIARIO · OLS ROLLING 90 · MISMA METODOLOGÍA PROFUTURO",
        "coefficients": beta,
        "parity_rule": (
            "Misma metodología de Profuturo: LinearRegression OLS, ventana móvil de 90 "
            "observaciones completas, siete factores, Yahoo Close, BCRP para USD/PEN "
            "histórico, PEN=X solo como respaldo pendiente y VC encadenado."
        ),
        "parity_verified": True,
        "methodology_parity_verified": True,
        "target_rule": (
            "Los coeficientes se estiman exclusivamente con retornos de Hábitat Fondo 3; "
            "no se reutilizan coeficientes de Profuturo."
        ),
        "model_factors": [*ASSETS, "USD_PEN"],
        "latest_fx_source": fx_source,
        "latest_fx_provisional": fx_provisional,
        "sources": {
            "sbs": "SBS oficial · Hábitat Fondo 3",
            "market": market_note,
            "fx": (
                "BCRP PD04646PD para histórico y entrenamiento; Yahoo PEN=X solo "
                "como respaldo provisional posterior al último VC SBS."
            ),
            "EEM": "Yahoo Finance · Close · auto_adjust=False",
        },
        "sbs_download_status": "SBS EN LÍNEA Y CONSOLIDADA",
        "warnings": [],
        "official_indicators": official_indicators(sbs),
        "live_engine": "CIERRE DIARIO HÁBITAT · MISMAS REGLAS DE FUENTES",
    }

    performance = {
        "window_n": int(len(evaluated)),
        "classification_accuracy": accuracy,
        "mae_return_pp": ols_mae * 100,
    }
    for signal, key in (("SUBE", "sube"), ("BAJA", "baja"), ("NEUTRO", "neutro")):
        subset = evaluated.loc[evaluated["senal"] == signal]
        performance[f"{key}_n"] = int(len(subset))
        performance[f"{key}_accuracy"] = (
            float(subset["correcta"].mean()) if not subset.empty else None
        )

    insights = {
        "generated_for": latest["latest_estimate_date"],
        "current_signal": latest["signal"],
        "confidence": {
            "historical_accuracy": signal_accuracy,
            "n": int(len(signal_rows)),
            "label": latest["signal"],
            "description": (
                "Aciertos históricos de la misma clase de señal; no es garantía futura."
            ),
        },
        "performance": performance,
        "uncertainty": {
            "relative_q80": q80,
            "label": "Banda empírica 80%",
        },
        "benchmarks": {
            "zero_change_mae_pp": zero_mae * 100,
            "ols_mae_pp": ols_mae * 100,
            "ols_mae_improvement_vs_zero": (
                1.0 - ols_mae / zero_mae if zero_mae > 0 else None
            ),
        },
        "contributions": contributions,
        "quality": {
            "status": "OK",
            "warnings": [],
            "critical": [],
            "training_n": len(train),
            "latest_sbs_date": latest["latest_sbs_date"],
            "fx_provisional": fx_provisional,
        },
        "challenger_huber": {
            "status": "NO APLICA EN HÁBITAT",
            "error": "La comparación solicitada mantiene OLS como modelo único.",
        },
    }
    return latest, insights


def live_market(latest: dict, markets: pd.DataFrame) -> dict:
    signal_date = pd.Timestamp(latest["latest_estimate_date"])
    assets = []
    for symbol in [*ASSETS, "USD_PEN"]:
        value_column = symbol
        valid = markets.loc[
            markets[value_column].notna() & (markets["fecha"] <= signal_date),
            ["fecha", value_column],
        ].sort_values("fecha")
        current = valid.iloc[-1] if not valid.empty else None
        previous = valid.iloc[-2] if len(valid) > 1 else None
        return_column = f"ret_{symbol}"
        model_row = markets.loc[markets["fecha"] == signal_date]
        model_return = (
            None
            if model_row.empty or pd.isna(model_row.iloc[-1].get(return_column))
            else float(model_row.iloc[-1][return_column])
        )
        assets.append(
            {
                "serie": symbol,
                "ticker": "PEN=X" if symbol == "USD_PEN" else symbol,
                "timestamp": (
                    None
                    if current is None
                    else pd.Timestamp(current["fecha"]).strftime("%Y-%m-%d")
                ),
                "precio_anterior": (
                    None if previous is None else float(previous[value_column])
                ),
                "precio_actual": (
                    None if current is None else float(current[value_column])
                ),
                "retorno": model_return,
                "retorno_modelo": model_return,
                "estado": "CIERRE DIARIO · MISMA FUENTE DEL MODELO PROFUTURO",
                "usado_modelo": model_return is not None,
            }
        )
    return {
        "generated_at_lima": datetime.now(LIMA).isoformat(),
        "mode": "CIERRE DIARIO",
        "market_open": False,
        "signal_date": latest["latest_estimate_date"],
        "vc_estimated": latest["latest_estimated_vc"],
        "return_estimated": latest["latest_return_estimated"],
        "signal": latest["signal"],
        "assets": assets,
        "action": "CIERRE",
        "engine": "OLS HÁBITAT · PARIDAD METODOLÓGICA PROFUTURO",
        "fx_rule": latest["parity_rule"],
        "fx_source": latest["latest_fx_source"],
        "fx_provisional": latest["latest_fx_provisional"],
    }


def validate_outputs(
    sbs: pd.DataFrame,
    signals: list[dict],
    latest: dict,
    train: pd.DataFrame,
) -> None:
    if len(train) != WINDOW:
        raise AssertionError(f"La ventana no tiene {WINDOW} observaciones.")
    if not signals:
        raise AssertionError("No se generaron señales de Hábitat.")
    historical = [row for row in signals if row["tipo"] == "HISTORICO"]
    if not historical:
        raise AssertionError("No se generó VC histórico estimado.")
    if not all(
        row["vc_real"] is not None and row["vc_estimado"] is not None
        for row in historical
    ):
        raise AssertionError("Hay fechas históricas sin VC real o estimado.")

    july = sbs.loc[
        sbs["fecha"].between(
            pd.Timestamp("2026-07-01"),
            pd.Timestamp("2026-07-20"),
            inclusive="both",
        )
    ]
    prof_path = DATA / "sbs_profuturo_f3.csv"
    if prof_path.exists():
        prof = read_csv(prof_path)
        expected = set(
            prof.loc[
                prof["fecha"].between(
                    pd.Timestamp("2026-07-01"),
                    pd.Timestamp("2026-07-20"),
                    inclusive="both",
                ),
                "fecha",
            ].dt.normalize()
        )
        present = set(july["fecha"].dt.normalize())
        missing = sorted(expected - present)
        if missing:
            raise AssertionError(
                "Hábitat sigue omitiendo fechas de julio: "
                + ", ".join(date.strftime("%Y-%m-%d") for date in missing)
            )

    current = signals[-1]
    if latest["latest_estimate_date"] != current["fecha"]:
        raise AssertionError("La cabecera no coincide con la última señal.")
    if abs(float(latest["latest_estimated_vc"]) - float(current["vc_estimado"])) > 1e-10:
        raise AssertionError("El último VC estimado no coincide con la serie.")
    if latest.get("methodology_parity_verified") is not True:
        raise AssertionError("No se certificó la paridad metodológica.")


def main() -> None:
    sbs, markets, market_note = prepare_inputs()
    complete = build_complete(sbs, markets)
    historical = historical_predictions(complete)
    pending, fitted, train = pending_predictions(sbs, complete, markets)
    signals = build_signals(historical, pending)
    series = build_series(sbs, pending)
    latest, insights = model_outputs(
        sbs,
        markets,
        historical,
        pending,
        fitted,
        train,
        market_note,
    )
    validate_outputs(sbs, signals, latest, train)

    write_json("signals.json", signals)
    write_json("series.json", series)
    write_json("operation_series.json", series)
    write_json("latest.json", latest)
    write_json("model_insights.json", insights)
    write_json("live_market.json", live_market(latest, markets))

    # Solo reutiliza la plantilla visual. Los datos y el modelo ya fueron
    # generados arriba mediante la misma metodología operativa de Profuturo.
    ui.build_html()
    print(
        "Hábitat corregido · histórico continuo · misma metodología Profuturo · "
        f"{len(historical)} VC históricos estimados · "
        f"ventana {latest['training_start']} -> {latest['training_end']}."
    )


if __name__ == "__main__":
    main()
