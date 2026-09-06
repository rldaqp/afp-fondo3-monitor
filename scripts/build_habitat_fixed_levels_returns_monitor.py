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
TRAIN_START = pd.Timestamp("2026-07-07")
TRAIN_END = pd.Timestamp("2026-08-17")
VALIDATION_START = pd.Timestamp("2026-08-18")
FACTORS = ["SPY", "EEM", "MCHI", "QQQ", "SPBLSCUP"]


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
    }


def equation(coeff: dict, prefix: str = "VC") -> str:
    bits = [f"{coeff['intercept']:.12f}"]
    for name in FACTORS:
        value = float(coeff[name])
        sign = "+" if value >= 0 else "−"
        bits.append(f" {sign} {abs(value):.12f}×{prefix}_{name if prefix == 'r' else name}")
    return "".join(bits)


def phase(date: pd.Timestamp, has_actual: bool) -> str:
    if date < TRAIN_START:
        return "RETROSPECTIVO"
    if date <= TRAIN_END:
        return "ENTRENAMIENTO"
    return "VALIDACIÓN" if has_actual else "PROYECCIÓN"


def metrics(frame: pd.DataFrame, mask: pd.Series, error_col: str) -> dict:
    e = pd.to_numeric(frame.loc[mask, error_col], errors="coerce").dropna().to_numpy(float)
    return {
        "n": int(e.size),
        "mae_pct": float(np.mean(np.abs(e))) if e.size else None,
        "rmse_pct": float(np.sqrt(np.mean(e ** 2))) if e.size else None,
        "bias_pct": float(np.mean(e)) if e.size else None,
    }


def metric_block(frame: pd.DataFrame, mask: pd.Series) -> dict:
    return {
        "niveles": metrics(frame, mask, "error_niveles_pct"),
        "retornos": metrics(frame, mask, "error_retornos_pct"),
        "niveles_raw": metrics(frame, mask, "error_niveles_raw_pct"),
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

    train_mask = df["fecha"].between(TRAIN_START, TRAIN_END)
    level_fit = ols_fit(df.loc[train_mask], "vc_sbs", FACTORS)
    return_fit = ols_fit(df.loc[train_mask], "ret_vc_sbs", [f"ret_{x}" for x in FACTORS])

    level_coeff = level_fit["coefficients"]
    return_coeff_raw = return_fit["coefficients"]
    return_coeff = {"intercept": return_coeff_raw["intercept"]}
    for name in FACTORS:
        return_coeff[name] = return_coeff_raw[f"ret_{name}"]

    # 1) Nivel absoluto bruto del OLS. Se conserva para auditoría y diagnóstico.
    df["vc_niveles_raw"] = float(level_coeff["intercept"])
    level_valid = pd.Series(True, index=df.index)
    for name in FACTORS:
        level_valid &= df[name].notna()
        df["vc_niveles_raw"] += float(level_coeff[name]) * df[name]
    df.loc[~level_valid, "vc_niveles_raw"] = np.nan

    # 2) Variación implícita del modelo de niveles entre dos ruedas consecutivas.
    # Esta es la magnitud comparable con el modelo de retornos.
    previous_raw = df["vc_niveles_raw"].shift(1)
    df["ret_niveles_implicito"] = np.where(
        df["vc_niveles_raw"].notna() & previous_raw.notna() & previous_raw.ne(0),
        df["vc_niveles_raw"] / previous_raw - 1.0,
        np.nan,
    )

    # 3) VC operativo de niveles: usa la misma regla de base que Retornos.
    # Si existe SBS del día anterior, ambos modelos arrancan exactamente del mismo VC.
    # Si SBS aún no fue publicado, cada modelo mantiene su cadena consecutiva propia.
    df["vc_niveles"] = chained_vc(df, "ret_niveles_implicito")

    # Modelo de retornos explícitos de los cinco factores.
    df["ret_vc_estimado"] = float(return_coeff["intercept"])
    return_valid = pd.Series(True, index=df.index)
    for name in FACTORS:
        return_valid &= df[f"ret_{name}"].notna()
        df["ret_vc_estimado"] += float(return_coeff[name]) * df[f"ret_{name}"]
    df.loc[~return_valid, "ret_vc_estimado"] = np.nan
    df["vc_retornos"] = chained_vc(df, "ret_vc_estimado")

    df["error_niveles_raw_pct"] = np.where(
        df["vc_sbs"].notna() & df["vc_niveles_raw"].notna(),
        (df["vc_niveles_raw"] / df["vc_sbs"] - 1.0) * 100.0,
        np.nan,
    )
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
    df["fase"] = [phase(d, finite(v)) for d, v in zip(df["fecha"], df["vc_sbs"])]

    latest_sbs = sbs.iloc[-1]
    validation_mask = (df["fecha"] >= VALIDATION_START) & df["vc_sbs"].notna()
    training_metrics = metric_block(df, train_mask & df["vc_sbs"].notna())
    validation_metrics = metric_block(df, validation_mask)

    level_model = {
        **level_fit,
        "coefficients": level_coeff,
        "equation": equation(level_coeff, "VC"),
        "target": "nivel absoluto bruto del valor cuota Hábitat Fondo 3",
        "operational_rule": "El VC mostrado se ancla al VC de la rueda anterior usando la variación implícita entre dos niveles OLS consecutivos.",
    }
    return_model = {
        **return_fit,
        "coefficients": return_coeff,
        "equation": equation(return_coeff, "r"),
        "target": "retorno diario del valor cuota Hábitat Fondo 3",
        "operational_rule": "El retorno estimado se aplica al VC de la rueda anterior.",
    }

    rows = []
    for record in df.to_dict(orient="records"):
        rows.append({k: clean(v) for k, v in record.items()})

    payload = {
        "fund": "HÁBITAT Fondo 3",
        "generated_at_lima": datetime.now(LIMA).isoformat(),
        "model_version": "habitat-fixed-levels-returns-v2-anchored",
        "history_start": HISTORY_START.date().isoformat(),
        "training": {
            "start": TRAIN_START.date().isoformat(),
            "end": TRAIN_END.date().isoformat(),
            "n_levels": level_fit["n"],
            "n_returns": return_fit["n"],
        },
        "validation_start": VALIDATION_START.date().isoformat(),
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
        "comparison_rule": "Ambos VC operativos parten del VC de la rueda anterior; Niveles usa la variación implícita del OLS en niveles y Retornos usa la regresión explícita de retornos.",
        "anti_stale_rules": [
            "Una fecha aparece una sola vez; cualquier duplicado se resuelve antes del cálculo.",
            "Los cinco factores deben pertenecer a la misma rueda de mercado para estimar el nivel.",
            "No se copia un precio o cierre antiguo a una fecha nueva.",
            "Niveles y Retornos usan el VC SBS de la rueda anterior cuando existe; si aún no existe SBS, cada modelo encadena solo desde su estimación consecutiva anterior.",
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
        "training": payload["training"],
        "latest": payload["latest"],
        "validation": payload["metrics"]["validation"],
        "latest_operational": {
            "niveles": clean(df.iloc[-1]["vc_niveles"]),
            "niveles_raw": clean(df.iloc[-1]["vc_niveles_raw"]),
            "retornos": clean(df.iloc[-1]["vc_retornos"]),
            "ret_niveles": clean(df.iloc[-1]["ret_niveles_implicito"]),
            "ret_retornos": clean(df.iloc[-1]["ret_vc_estimado"]),
        },
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
