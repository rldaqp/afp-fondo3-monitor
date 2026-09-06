from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from build_fixed_levels_returns_monitor import load_spblscup_levels, yahoo_history

ROOT = Path(__file__).resolve().parents[1]
SBS = ROOT / "data" / "rolling90" / "sbs_habitat_f3.csv"
OUT_JSON = ROOT / "public" / "habitat" / "data" / "fixed_models_2026.json"
OUT_CSV = ROOT / "public" / "habitat" / "data" / "fixed_models_2026.csv"
LIMA = ZoneInfo("America/Lima")

HISTORY_START = pd.Timestamp("2026-01-05")
WINDOW = 90
BACKTEST_DAYS = 7
FACTORS = ["SPY", "EEM", "MCHI", "QQQ", "SPBLSCUP"]
RET_FACTORS = [f"ret_{x}" for x in FACTORS]


def finite(value) -> bool:
    try:
        return value is not None and np.isfinite(float(value))
    except Exception:
        return False


def ols_fit(frame: pd.DataFrame, y_col: str, x_cols: list[str]) -> dict:
    d = frame[[y_col, *x_cols]].dropna().copy()
    if len(d) <= len(x_cols) + 1:
        raise RuntimeError(
            f"Muestra insuficiente para {y_col}: {len(d)} observaciones para {len(x_cols)} factores"
        )
    y = d[y_col].to_numpy(float)
    x = d[x_cols].to_numpy(float)
    design = np.column_stack([np.ones(len(d)), x])
    beta, _, _, _ = np.linalg.lstsq(design, y, rcond=None)
    fitted = design @ beta
    resid = y - fitted
    sse = float(np.sum(resid ** 2))
    sst = float(np.sum((y - np.mean(y)) ** 2))
    r2 = 1.0 - sse / sst if sst else 1.0
    n, p = len(d), len(x_cols)
    adj = 1.0 - (1.0 - r2) * (n - 1) / max(n - p - 1, 1)
    stderr = float(np.sqrt(sse / max(n - p - 1, 1)))
    coeff = {"intercept": float(beta[0])}
    coeff.update({name: float(beta[i + 1]) for i, name in enumerate(x_cols)})
    return {
        "coefficients": coeff,
        "n": int(n),
        "r2": float(r2),
        "adj_r2": float(adj),
        "stderr": stderr,
        "fitted": fitted,
    }


def equation(coeff: dict, prefix: str = "VC") -> str:
    bits = [f"{coeff['intercept']:.12f}"]
    for name in FACTORS:
        value = float(coeff[name])
        sign = "+" if value >= 0 else "−"
        bits.append(f" {sign} {abs(value):.12f}×{prefix}_{name}")
    return "".join(bits)


def model_level(coeff: dict, frame: pd.DataFrame) -> np.ndarray:
    x = frame[FACTORS].to_numpy(float)
    beta = np.array([float(coeff[x]) for x in FACTORS], dtype=float)
    return float(coeff["intercept"]) + x @ beta


def model_return(coeff: dict, frame: pd.DataFrame) -> np.ndarray:
    x = frame[RET_FACTORS].to_numpy(float)
    beta = np.array([float(coeff[x.replace("ret_", "")]) for x in RET_FACTORS], dtype=float)
    return float(coeff["intercept"]) + x @ beta


def error_metrics(actual, predicted) -> dict:
    a = np.asarray(actual, float)
    p = np.asarray(predicted, float)
    ok = np.isfinite(a) & np.isfinite(p) & (a != 0)
    if not ok.any():
        return {"n": 0, "mae_pct": None, "rmse_pct": None, "bias_pct": None, "max_abs_pct": None, "r2_vc_oos": None}
    a = a[ok]
    p = p[ok]
    e = (p / a - 1.0) * 100.0
    sse = float(np.sum((a - p) ** 2))
    sst = float(np.sum((a - np.mean(a)) ** 2))
    return {
        "n": int(len(a)),
        "mae_pct": float(np.mean(np.abs(e))),
        "rmse_pct": float(np.sqrt(np.mean(e ** 2))),
        "bias_pct": float(np.mean(e)),
        "max_abs_pct": float(np.max(np.abs(e))),
        "r2_vc_oos": float(1.0 - sse / sst) if sst else None,
    }


def chained_vc(df: pd.DataFrame, return_col: str) -> list[float]:
    values = []
    previous_estimate = np.nan
    for i, row in df.iterrows():
        if i == 0 or not finite(row[return_col]):
            values.append(np.nan)
            continue
        previous_actual = df.iloc[i - 1]["vc_sbs"]
        if finite(previous_actual):
            base = float(previous_actual)
        elif finite(previous_estimate):
            base = float(previous_estimate)
        else:
            base = np.nan
        value = base * (1.0 + float(row[return_col])) if finite(base) else np.nan
        values.append(value)
        if finite(value):
            previous_estimate = value
    return values


def one_step_return_vc(frame: pd.DataFrame, predicted_returns: np.ndarray, full_real: pd.DataFrame) -> np.ndarray:
    prior_map = full_real[["fecha", "vc_sbs"]].copy()
    prior_map["prev_sbs_vc"] = prior_map["vc_sbs"].shift(1)
    prev = frame["fecha"].map(prior_map.set_index("fecha")["prev_sbs_vc"]).to_numpy(float)
    return prev * (1.0 + np.asarray(predicted_returns, float))


def clean(value):
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat()
    if isinstance(value, (np.floating, float)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, (np.integer, int)):
        return int(value)
    if pd.isna(value):
        return None
    return value


def main() -> None:
    if not SBS.exists():
        raise RuntimeError(f"Falta la serie SBS de Hábitat: {SBS}")

    yahoo = yahoo_history()
    spb = load_spblscup_levels()[["fecha", "SPBLSCUP"]].copy()
    market = spb.merge(yahoo, on="fecha", how="inner")
    market = market.sort_values("fecha").drop_duplicates("fecha", keep="last")
    market = market.loc[market["fecha"] >= HISTORY_START].copy()

    sbs = pd.read_csv(SBS)
    sbs["fecha"] = pd.to_datetime(sbs["fecha"], errors="coerce").dt.normalize()
    sbs["valor_cuota"] = pd.to_numeric(sbs["valor_cuota"], errors="coerce")
    sbs = sbs.dropna(subset=["fecha", "valor_cuota"])
    sbs = sbs.sort_values("fecha").drop_duplicates("fecha", keep="last")

    df = market.merge(
        sbs[["fecha", "valor_cuota"]].rename(columns={"valor_cuota": "vc_sbs"}),
        on="fecha",
        how="left",
    ).sort_values("fecha").reset_index(drop=True)

    if df["fecha"].duplicated().any():
        raise RuntimeError("Hábitat: se detectaron fechas duplicadas antes del ajuste")

    for name in FACTORS:
        df[name] = pd.to_numeric(df[name], errors="coerce")
        df[f"ret_{name}"] = df[name].pct_change(fill_method=None)
    df["ret_vc_sbs"] = df["vc_sbs"].pct_change(fill_method=None)

    usable = df.dropna(subset=["vc_sbs", "ret_vc_sbs", *FACTORS, *RET_FACTORS]).copy().reset_index(drop=True)
    if len(usable) < WINDOW + BACKTEST_DAYS:
        raise RuntimeError(f"Hábitat: se requieren al menos {WINDOW + BACKTEST_DAYS} observaciones completas")

    # PRODUCCIÓN: ambos modelos usan las 90 observaciones SBS más recientes.
    train = usable.tail(WINDOW).copy().reset_index(drop=True)
    train_start = pd.Timestamp(train["fecha"].min())
    train_end = pd.Timestamp(train["fecha"].max())

    level_fit = ols_fit(train, "vc_sbs", FACTORS)
    return_fit_raw = ols_fit(train, "ret_vc_sbs", RET_FACTORS)

    level_coeff = level_fit["coefficients"]
    return_coeff = {"intercept": return_fit_raw["coefficients"]["intercept"]}
    for name in FACTORS:
        return_coeff[name] = return_fit_raw["coefficients"][f"ret_{name}"]

    # NIVELES 90: OLS absoluto directo.
    df["vc_niveles"] = np.nan
    valid_level = df[FACTORS].notna().all(axis=1)
    df.loc[valid_level, "vc_niveles"] = model_level(level_coeff, df.loc[valid_level])
    df["vc_niveles_raw"] = df["vc_niveles"]  # alias de compatibilidad/auditoría
    previous_level = df["vc_niveles"].shift(1)
    df["ret_niveles_implicito"] = np.where(
        df["vc_niveles"].notna() & previous_level.notna() & previous_level.ne(0),
        df["vc_niveles"] / previous_level - 1.0,
        np.nan,
    )

    # RETORNOS 90: retorno diario aplicado al VC SBS previo; si SBS aún no existe,
    # continúa desde la estimación consecutiva anterior.
    df["ret_vc_estimado"] = np.nan
    valid_return = df[RET_FACTORS].notna().all(axis=1)
    df.loc[valid_return, "ret_vc_estimado"] = model_return(return_coeff, df.loc[valid_return])
    df["vc_retornos"] = chained_vc(df, "ret_vc_estimado")

    df["error_niveles_pct"] = np.where(
        df["vc_sbs"].notna() & df["vc_niveles"].notna(),
        (df["vc_niveles"] / df["vc_sbs"] - 1.0) * 100.0,
        np.nan,
    )
    df["error_retornos_pct"] = np.where(
        df["vc_sbs"].notna() & df["vc_retornos"].notna(),
        (df["vc_retornos"] / df["vc_sbs"] - 1.0) * 100.0,
        np.nan,
    )

    def phase(date: pd.Timestamp, has_actual: bool) -> str:
        if date < train_start:
            return "RETROSPECTIVO"
        if date <= train_end and has_actual:
            return "ENTRENAMIENTO 90"
        return "PROYECCIÓN" if not has_actual else "SBS POSTERIOR"

    df["fase"] = [phase(d, finite(v)) for d, v in zip(df["fecha"], df["vc_sbs"])]

    # Diagnóstico móvil de 7 días: deja las 7 últimas fechas SBS completamente
    # fuera del ajuste y entrena ambos modelos con las 90 observaciones anteriores.
    holdout = usable.tail(BACKTEST_DAYS).copy().reset_index(drop=True)
    holdout_start = pd.Timestamp(holdout["fecha"].min())
    bt_pool = usable.loc[usable["fecha"] < holdout_start].copy()
    bt_train = bt_pool.tail(WINDOW).copy().reset_index(drop=True)
    if len(bt_train) != WINDOW:
        raise RuntimeError("Hábitat: no hay 90 observaciones previas para el backtest de 7 días")

    bt_level_fit = ols_fit(bt_train, "vc_sbs", FACTORS)
    bt_return_fit_raw = ols_fit(bt_train, "ret_vc_sbs", RET_FACTORS)
    bt_return_coeff = {"intercept": bt_return_fit_raw["coefficients"]["intercept"]}
    for name in FACTORS:
        bt_return_coeff[name] = bt_return_fit_raw["coefficients"][f"ret_{name}"]

    bt_level_pred = model_level(bt_level_fit["coefficients"], holdout)
    bt_ret_pred = model_return(bt_return_coeff, holdout)
    bt_ret_vc = one_step_return_vc(holdout, bt_ret_pred, usable)
    validation_metrics = {
        "niveles": error_metrics(holdout["vc_sbs"], bt_level_pred),
        "retornos": error_metrics(holdout["vc_sbs"], bt_ret_vc),
    }

    train_level_pred = model_level(level_coeff, train)
    train_ret_pred = model_return(return_coeff, train)
    train_ret_vc = one_step_return_vc(train, train_ret_pred, usable)
    training_metrics = {
        "niveles": error_metrics(train["vc_sbs"], train_level_pred),
        "retornos": error_metrics(train["vc_sbs"], train_ret_vc),
    }

    latest_sbs = sbs.iloc[-1]

    level_model = {
        **{k: v for k, v in level_fit.items() if k != "fitted"},
        "coefficients": level_coeff,
        "window": WINDOW,
        "equation": equation(level_coeff, "VC"),
        "target": "nivel absoluto del valor cuota Hábitat Fondo 3",
        "operational_rule": "Niveles 90: OLS absoluto directo estimado con las 90 observaciones SBS más recientes disponibles.",
    }
    return_model = {
        **{k: v for k, v in return_fit_raw.items() if k != "fitted"},
        "coefficients": return_coeff,
        "window": WINDOW,
        "equation": equation(return_coeff, "r"),
        "target": "retorno diario del valor cuota Hábitat Fondo 3",
        "operational_rule": "Retornos 90: estima el retorno con las 90 observaciones SBS más recientes y lo aplica al VC SBS de la rueda anterior; si aún no existe SBS, continúa desde la estimación consecutiva anterior.",
    }

    rows = [{k: clean(v) for k, v in record.items()} for record in df.to_dict(orient="records")]

    payload = {
        "fund": "HÁBITAT Fondo 3",
        "generated_at_lima": datetime.now(LIMA).isoformat(),
        "model_version": "habitat-rolling90-levels-returns-v4",
        "history_start": HISTORY_START.date().isoformat(),
        "window": WINDOW,
        "training": {
            "start": train_start.date().isoformat(),
            "end": train_end.date().isoformat(),
            "n_levels": int(level_fit["n"]),
            "n_returns": int(return_fit_raw["n"]),
            "rule": "90 observaciones completas más recientes hasta el último VC SBS disponible",
        },
        "validation_start": holdout_start.date().isoformat(),
        "backtest7": {
            "holdout_start": holdout_start.date().isoformat(),
            "holdout_end": pd.Timestamp(holdout["fecha"].max()).date().isoformat(),
            "n": BACKTEST_DAYS,
            "training_start": pd.Timestamp(bt_train["fecha"].min()).date().isoformat(),
            "training_end": pd.Timestamp(bt_train["fecha"].max()).date().isoformat(),
            "window": WINDOW,
            "rule": "Las 7 últimas fechas SBS quedan fuera; ambos modelos se ajustan con las 90 observaciones inmediatamente anteriores.",
        },
        "factors": FACTORS,
        "latest": {
            "latest_sbs_date": pd.Timestamp(latest_sbs["fecha"]).date().isoformat(),
            "latest_sbs_vc": float(latest_sbs["valor_cuota"]),
            "latest_market_date": pd.Timestamp(df.iloc[-1]["fecha"]).date().isoformat(),
        },
        "models": {
            "niveles": level_model,
            "retornos": return_model,
        },
        "metrics": {
            "training": training_metrics,
            "validation": validation_metrics,
        },
        "comparison_rule": "Hábitat mantiene únicamente dos modelos productivos, ambos con ventana móvil de 90 observaciones: Niveles 90 estima el VC absoluto; Retornos 90 estima la variación diaria y la aplica sobre el VC previo.",
        "anti_stale_rules": [
            "Una fecha aparece una sola vez; cualquier duplicado se resuelve antes del cálculo.",
            "Los cinco factores deben pertenecer a la misma rueda de mercado para estimar Niveles.",
            "No se copia un precio o cierre antiguo a una fecha nueva.",
            "Retornos usa el VC SBS de la rueda anterior cuando existe; si no existe aún, encadena únicamente desde su estimación consecutiva anterior.",
        ],
        "rows": rows,
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    export = df.copy()
    export["fecha"] = export["fecha"].dt.strftime("%Y-%m-%d")
    export.to_csv(OUT_CSV, index=False)

    print(json.dumps({
        "fund": payload["fund"],
        "model_version": payload["model_version"],
        "training": payload["training"],
        "backtest7": payload["backtest7"],
        "latest": payload["latest"],
        "r2": {
            "niveles90": level_model["r2"],
            "retornos90": return_model["r2"],
        },
        "validation7": validation_metrics,
        "latest_models": {
            "niveles90": clean(df.iloc[-1]["vc_niveles"]),
            "retornos90": clean(df.iloc[-1]["vc_retornos"]),
            "ret_niveles_implicito": clean(df.iloc[-1]["ret_niveles_implicito"]),
            "ret_retornos": clean(df.iloc[-1]["ret_vc_estimado"]),
        },
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
