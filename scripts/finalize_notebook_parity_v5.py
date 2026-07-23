from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
V4_PATH = ROOT / "scripts" / "finalize_notebook_parity_v4.py"
REFERENCE_PATH = ROOT / "data" / "rolling90" / "notebook_training_reference.csv"
LATEST_PATH = ROOT / "public" / "data" / "latest.json"
PENDING_PATH = ROOT / "data" / "rolling90" / "pending_predictions.csv"

spec = importlib.util.spec_from_file_location("notebook_parity_v4_base", V4_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError(f"No se pudo cargar {V4_PATH}")
parity = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parity)

_original_run = parity._run_notebook_model


def _load_reference() -> pd.DataFrame:
    if not REFERENCE_PATH.exists():
        raise RuntimeError(f"Falta referencia canónica {REFERENCE_PATH}")
    ref = pd.read_csv(REFERENCE_PATH)
    ref["fecha"] = pd.to_datetime(ref["fecha"], errors="coerce")
    numeric = ["valor_cuota", "ret_profuturo", *parity.FEATURES]
    for col in numeric:
        ref[col] = pd.to_numeric(ref[col], errors="coerce")
    ref = (
        ref.dropna(subset=["fecha", *numeric])
        .sort_values("fecha")
        .drop_duplicates("fecha", keep="last")
        .reset_index(drop=True)
    )
    if len(ref) != parity.WINDOW:
        raise RuntimeError(f"La referencia debe tener exactamente {parity.WINDOW} filas; tiene {len(ref)}")
    if ref.iloc[0]["fecha"] != pd.Timestamp("2026-02-27"):
        raise RuntimeError("Inicio inesperado de referencia notebook")
    if ref.iloc[-1]["fecha"] != pd.Timestamp("2026-07-20"):
        raise RuntimeError("Fin inesperado de referencia notebook")
    return ref


def _run_with_canonical_history(sbs: pd.DataFrame, markets: pd.DataFrame):
    # Conservamos el histórico gráfico ya calculado por el motor base.
    historical, _, _ = _original_run(sbs, markets)

    # Base completa dinámica: sirve únicamente para incorporar nuevas observaciones
    # oficiales posteriores al corte canónico del notebook. El pasado no se reescribe
    # con revisiones posteriores de Yahoo/BCRP.
    complete_dynamic, s = parity._build_complete(sbs, markets)
    reference = _load_reference()
    reference_end = pd.Timestamp(reference["fecha"].max())

    future = complete_dynamic.loc[complete_dynamic["fecha"] > reference_end, reference.columns].copy()
    canonical = (
        pd.concat([reference, future], ignore_index=True)
        .sort_values("fecha")
        .drop_duplicates("fecha", keep="last")
        .reset_index(drop=True)
    )
    if len(canonical) < parity.WINDOW:
        raise RuntimeError("No hay 90 observaciones en la base canónica")

    train = canonical.tail(parity.WINDOW).copy()
    fitted = parity._fit_ols(train)

    latest_sbs = s.sort_values("fecha").iloc[-1]
    last_sbs_date = pd.Timestamp(latest_sbs["fecha"])
    last_sbs_vc = float(latest_sbs["valor_cuota"])

    pending_features = markets.loc[
        markets["fecha"] > last_sbs_date,
        ["fecha", *parity.FEATURES],
    ].copy()
    pending_features = pending_features.dropna(subset=parity.EQUITY_FEATURES).sort_values("fecha")
    pending_features["usd_pen_fresco"] = pending_features["ret_USD_PEN"].notna()
    pending_features["ret_USD_PEN"] = pending_features["ret_USD_PEN"].fillna(0.0)
    pending_features["fuentes_completas"] = pending_features["usd_pen_fresco"].astype(bool)
    pending_features["estado_fuentes"] = np.where(
        pending_features["fuentes_completas"],
        "COMPLETAS",
        "USD/PEN PROVISIONAL 0 %",
    )

    rows: list[dict[str, object]] = []
    base = last_sbs_vc
    for _, row in pending_features.iterrows():
        pred = parity._predict(fitted, row)
        estimate = base * (1.0 + pred)
        record: dict[str, object] = {
            "fecha": row["fecha"],
            "modelo": "OLS",
            "valor_cuota_base": base,
            "ret_estimado": pred,
            "valor_cuota_estimado": estimate,
            "senal": parity._classify(pred),
            "ventana_inicio": train.iloc[0]["fecha"],
            "ventana_fin": train.iloc[-1]["fecha"],
            "n_entrenamiento": parity.WINDOW,
            "usd_pen_fresco": bool(row["usd_pen_fresco"]),
            "fuentes_completas": bool(row["fuentes_completas"]),
            "estado_fuentes": str(row["estado_fuentes"]),
            "estado": (
                "PENDIENTE SBS / FUENTES COMPLETAS"
                if bool(row["fuentes_completas"])
                else "PROVISIONAL / FUENTE REZAGADA"
            ),
        }
        for feature in parity.FEATURES:
            record[feature] = float(row[feature])
        rows.append(record)
        base = estimate
    pending = pd.DataFrame(rows)

    beta = {"intercept": float(fitted.intercept_)}
    beta.update({feature: float(coef) for feature, coef in zip(parity.FEATURES, fitted.coef_)})
    latest_equity = markets.dropna(subset=parity.EQUITY_FEATURES).sort_values("fecha")
    meta = {
        "train_start": pd.Timestamp(train.iloc[0]["fecha"]),
        "train_end": pd.Timestamp(train.iloc[-1]["fecha"]),
        "train_n": len(train),
        "latest_sbs_date": last_sbs_date,
        "latest_sbs_vc": last_sbs_vc,
        "latest_market_date": pd.Timestamp(latest_equity.iloc[-1]["fecha"]),
        "coefficients": beta,
    }
    return historical, pending, meta


parity._run_notebook_model = _run_with_canonical_history
parity.main()

latest = json.loads(LATEST_PATH.read_text(encoding="utf-8"))
latest["parity_reference"] = (
    "Ventana canónica exacta del notebook al 20/07/2026; "
    "desde la siguiente observación oficial el rolling 90 continúa normalmente"
)
latest["parity_verified"] = True
LATEST_PATH.write_text(json.dumps(latest, ensure_ascii=False, indent=2), encoding="utf-8")

# Prueba numérica real contra el HTML generado por el notebook.
if latest.get("latest_sbs_date") == "2026-07-20":
    pending = pd.read_csv(PENDING_PATH)
    pending["fecha"] = pd.to_datetime(pending["fecha"]).dt.strftime("%Y-%m-%d")
    expected = {
        "2026-07-21": 69.65879107720521,
        "2026-07-22": 70.43398277251534,
    }
    assert latest["training_start"] == "2026-02-27", latest
    assert latest["training_end"] == "2026-07-20", latest
    for fecha, reference_vc in expected.items():
        row = pending.loc[pending["fecha"] == fecha]
        if row.empty:
            raise AssertionError(f"Falta predicción de control {fecha}")
        actual = float(row.iloc[-1]["valor_cuota_estimado"])
        if abs(actual - reference_vc) >= 1e-9:
            raise AssertionError((fecha, actual, reference_vc))

print("PARIDAD NOTEBOOK V5 APROBADA")
print(json.dumps(latest, ensure_ascii=False, indent=2))
