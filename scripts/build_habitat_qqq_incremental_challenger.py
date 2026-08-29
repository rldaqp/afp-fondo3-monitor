from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

import build_qqq_incremental_challenger as core

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "rolling90"
PUBLIC = ROOT / "public" / "habitat" / "data"
LATEST_PATH = PUBLIC / "latest.json"
LIVE_PATH = PUBLIC / "live_market.json"
OUT_PATH = PUBLIC / "qqq_incremental_challenger.json"
SHADOW_PATH = DATA / "habitat_qqq_incremental_shadow.csv"
LIMA = ZoneInfo("America/Lima")
WINDOW = 90
BASE_FEATURES = list(core.BASE_FEATURES)


def safe_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception:
        return {}


def live_base_features(live: dict) -> np.ndarray:
    mapping: dict[str, float] = {}
    for row in live.get("assets", []):
        serie = str(row.get("serie", ""))
        key = f"ret_{serie}"
        if key not in BASE_FEATURES:
            continue
        value = pd.to_numeric(pd.Series([row.get("retorno_modelo")]), errors="coerce").iloc[0]
        if pd.notna(value):
            mapping[key] = float(value)
    missing = [f for f in BASE_FEATURES if f not in mapping]
    if missing:
        raise RuntimeError("Hábitat no tiene todos los factores actuales: " + ", ".join(missing))
    return np.array([mapping[f] for f in BASE_FEATURES], dtype=float)


def update_shadow(current: dict, sbs: pd.DataFrame, latest_sbs_date: str) -> tuple[pd.DataFrame, dict]:
    if SHADOW_PATH.exists() and SHADOW_PATH.stat().st_size:
        shadow = pd.read_csv(SHADOW_PATH)
    else:
        shadow = pd.DataFrame()

    signal_date = str(current["signal_date"])
    if signal_date > str(latest_sbs_date)[:10]:
        row = {
            "fecha": signal_date,
            "created_at_lima": current["generated_at_lima"],
            "updated_at_lima": current["generated_at_lima"],
            "vc_base": current["vc_base"],
            "official_return": current["official"]["return_estimated"],
            "official_signal": current["official"]["signal"],
            "official_vc": current["official"]["vc_estimated"],
            "challenger_return": current["challenger"]["return_estimated"],
            "challenger_signal": current["challenger"]["signal"],
            "challenger_vc": current["challenger"]["vc_estimated"],
            "qqq_return": current["qqq"]["return"],
            "qqq_residual": current["qqq"]["residual"],
            "actual_return": np.nan,
            "actual_signal": "",
            "actual_vc": np.nan,
            "official_abs_error": np.nan,
            "challenger_abs_error": np.nan,
            "official_hit": "",
            "challenger_hit": "",
            "status": "PENDIENTE",
        }
        if not shadow.empty and "fecha" in shadow.columns and signal_date in set(shadow["fecha"].astype(str)):
            idx = shadow.index[shadow["fecha"].astype(str).eq(signal_date)][-1]
            created = shadow.at[idx, "created_at_lima"] if "created_at_lima" in shadow.columns else row["created_at_lima"]
            for key, value in row.items():
                shadow.at[idx, key] = value
            shadow.at[idx, "created_at_lima"] = created
        else:
            shadow = pd.concat([shadow, pd.DataFrame([row])], ignore_index=True)

    if not shadow.empty:
        if "fecha" in shadow.columns:
            shadow["fecha"] = shadow["fecha"].astype(str).str[:10]
        s = sbs.copy()
        s["fecha"] = pd.to_datetime(s["fecha"], errors="coerce")
        shadow = core.evaluate_shadow(shadow, s)
        shadow = shadow.sort_values("fecha").drop_duplicates("fecha", keep="last").reset_index(drop=True)
        SHADOW_PATH.parent.mkdir(parents=True, exist_ok=True)
        shadow.to_csv(SHADOW_PATH, index=False)
    return shadow, core.forward_metrics(shadow)


def main() -> None:
    latest = safe_json(LATEST_PATH)
    live = safe_json(LIVE_PATH)
    if not latest or not live:
        raise RuntimeError("Falta latest.json o live_market.json de Hábitat")

    markets = core.read_csv(DATA / "markets.csv")
    sbs_raw = core.read_csv(DATA / "sbs_habitat_f3.csv")
    if markets.empty or sbs_raw.empty:
        raise RuntimeError("Falta markets.csv o sbs_habitat_f3.csv")

    markets["fecha"] = pd.to_datetime(markets["fecha"], errors="coerce")
    start = min(markets["fecha"].dropna().min(), pd.Timestamp("2024-12-01"))
    signal_date = pd.Timestamp(str(live.get("signal_date") or latest.get("latest_estimate_date"))).normalize()
    qqq = core.download_qqq_daily(start, max(signal_date, pd.Timestamp.now().normalize()))
    frame, sbs = core.prepare_data(markets, sbs_raw, qqq)

    train = frame.tail(WINDOW).copy()
    beta_resid, challenger_model = core.fit_challenger(train)
    base_current = live_base_features(live)
    qqq_ret, qqq_prev, qqq_current, qqq_source = core.current_qqq_return(
        qqq, signal_date, bool(live.get("market_open"))
    )
    qqq_resid = float(qqq_ret - np.r_[1.0, base_current] @ beta_resid)
    challenger_input = np.r_[base_current, qqq_resid]
    challenger_ret = core.standardize_predict(challenger_model, challenger_input)

    # Convertir el modelo estandarizado a coeficientes efectivos en escala original.
    # y = a_z + sum(b_z * (x-mu)/sd) = a_raw + sum(beta_raw*x)
    challenger_mu = np.asarray(challenger_model["mu"], dtype=float)
    challenger_sd = np.asarray(challenger_model["sd"], dtype=float)
    challenger_coef_z = np.asarray(challenger_model["coef"], dtype=float)
    challenger_beta_raw = challenger_coef_z / challenger_sd
    challenger_intercept_raw = float(challenger_model["intercept"] - challenger_mu @ challenger_beta_raw)
    challenger_features = [*BASE_FEATURES, "ret_QQQ_residual"]
    challenger_coefficients_raw = {
        "intercept": challenger_intercept_raw,
        **{f: float(challenger_beta_raw[i]) for i, f in enumerate(challenger_features)},
    }
    challenger_contributions = [
        {
            "feature": f,
            "value": float(challenger_input[i]),
            "coefficient": float(challenger_beta_raw[i]),
            "contribution_pp": float(challenger_beta_raw[i] * challenger_input[i] * 100.0),
        }
        for i, f in enumerate(challenger_features)
    ]

    official_ret = float(live["return_estimated"])
    official_vc = float(live["vc_estimated"])
    vc_base_raw = pd.to_numeric(pd.Series([live.get("vc_base")]), errors="coerce").iloc[0]
    if pd.notna(vc_base_raw) and float(vc_base_raw) > 0:
        vc_base = float(vc_base_raw)
    elif abs(1.0 + official_ret) > 1e-12:
        vc_base = official_vc / (1.0 + official_ret)
    else:
        vc_base = float(latest["latest_sbs_vc"])
    challenger_vc = vc_base * (1.0 + challenger_ret)

    current: dict[str, object] = {
        "generated_at_lima": datetime.now(LIMA).isoformat(),
        "signal_date": signal_date.date().isoformat(),
        "mode": live.get("mode"),
        "market_open": bool(live.get("market_open")),
        "fund": "HABITAT FONDO 3",
        "role": "CHALLENGER EN SOMBRA; no reemplaza el OLS oficial de Hábitat.",
        "vc_base": vc_base,
        "official": {
            "model": "OLS rolling 90 oficial Hábitat",
            "return_estimated": official_ret,
            "signal": str(live.get("signal")),
            "vc_estimated": official_vc,
        },
        "challenger": {
            "model": "OLS rolling 90 Hábitat + QQQ incremental residualizado",
            "return_estimated": challenger_ret,
            "signal": core.classify(challenger_ret),
            "vc_estimated": challenger_vc,
            "features": challenger_features,
            "coefficients_raw": challenger_coefficients_raw,
            "contributions": challenger_contributions,
            "coefficient_note": "Coeficientes efectivos en escala original, derivados exactamente del modelo estandarizado vigente.",
        },
        "qqq": {
            "return": qqq_ret,
            "residual": qqq_resid,
            "previous_close": qqq_prev,
            "current_price": qqq_current,
            "source": qqq_source,
            "residualized_against": BASE_FEATURES,
        },
        "comparison": {
            "same_signal": core.classify(challenger_ret) == str(live.get("signal")),
            "vc_difference": challenger_vc - official_vc,
            "return_difference_pp": (challenger_ret - official_ret) * 100.0,
        },
        "training": {
            "window": WINDOW,
            "n": int(len(train)),
            "start": train.iloc[0]["fecha"].date().isoformat(),
            "end": train.iloc[-1]["fecha"].date().isoformat(),
            "qqq_residualizer": {
                "intercept": float(beta_resid[0]),
                **{f: float(beta_resid[i + 1]) for i, f in enumerate(BASE_FEATURES)},
            },
        },
        "performance_backtest": core.build_backtest(frame),
    }

    shadow, shadow_metrics = update_shadow(current, sbs, str(latest.get("latest_sbs_date", "")))
    current["shadow_forward"] = shadow_metrics
    current["shadow_forward"]["ledger"] = "data/rolling90/habitat_qqq_incremental_shadow.csv"
    current["shadow_forward"]["rule"] = "Solo cuenta como prueba futura cuando la SBS publique el VC real de Hábitat para la fecha guardada."

    PUBLIC.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")

    assert current["official"]["signal"] in {"SUBE", "NEUTRO", "BAJA"}
    assert current["challenger"]["signal"] in {"SUBE", "NEUTRO", "BAJA"}
    assert abs(float(current["official"]["vc_estimated"]) - official_vc) < 1e-12
    assert abs(float(current["vc_base"]) * (1.0 + official_ret) - official_vc) < 1e-8
    assert int(current["training"]["n"]) == WINDOW
    print(json.dumps(current, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
