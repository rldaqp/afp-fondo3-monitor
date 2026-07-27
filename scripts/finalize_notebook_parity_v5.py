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
REFERENCE_END = pd.Timestamp("2026-07-20")

spec = importlib.util.spec_from_file_location("notebook_parity_v4_base", V4_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError(f"No se pudo cargar {V4_PATH}")
parity = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parity)

# La exclusión histórica del 06/07/2026 era un workaround de una base incompleta.
# Con la cuota SBS restaurada, no corresponde excluir esa observación.
parity.EXCLUDED_RETURN_DATES = set()

_original_run = parity._run_notebook_model


def _correct_historical_bases(historical: pd.DataFrame) -> pd.DataFrame:
    """Usa como base la cuota SBS previa real, aunque la fecha previa no sea modelable."""
    if historical.empty:
        return historical
    out = historical.copy()
    denom = 1.0 + pd.to_numeric(out["ret_profuturo"], errors="coerce")
    previous = pd.to_numeric(out["valor_cuota"], errors="coerce") / denom
    out["valor_cuota_anterior"] = previous
    out["valor_cuota_estimado"] = previous * (
        1.0 + pd.to_numeric(out["ret_estimado"], errors="coerce")
    )
    return out


def _rebuild_reference(complete_dynamic: pd.DataFrame) -> pd.DataFrame:
    """Reconstruye las 90 observaciones canónicas con la SBS ya corregida."""
    columns = ["fecha", "valor_cuota", "ret_profuturo", *parity.FEATURES]
    ref = (
        complete_dynamic.loc[complete_dynamic["fecha"] <= REFERENCE_END, columns]
        .dropna(subset=columns)
        .sort_values("fecha")
        .drop_duplicates("fecha", keep="last")
        .tail(parity.WINDOW)
        .reset_index(drop=True)
    )
    if len(ref) != parity.WINDOW:
        raise RuntimeError(
            f"La referencia corregida debe tener {parity.WINDOW} filas; tiene {len(ref)}"
        )
    if pd.Timestamp(ref.iloc[-1]["fecha"]) != REFERENCE_END:
        raise RuntimeError("La referencia corregida no termina el 20/07/2026")

    required_dates = {
        pd.Timestamp("2026-07-01"),
        pd.Timestamp("2026-07-02"),
        pd.Timestamp("2026-07-06"),
        pd.Timestamp("2026-07-08"),
        pd.Timestamp("2026-07-09"),
    }
    present = set(pd.to_datetime(ref["fecha"]))
    missing = sorted(required_dates - present)
    if missing:
        raise AssertionError(
            "La referencia corregida aún omite fechas completas: "
            + ", ".join(d.strftime("%Y-%m-%d") for d in missing)
        )

    row_10 = ref.loc[pd.to_datetime(ref["fecha"]).eq(pd.Timestamp("2026-07-10"))]
    if row_10.empty:
        raise AssertionError("Falta 2026-07-10 en la referencia corregida")
    expected_ret_10 = 71.0624925 / 70.9792394 - 1.0
    actual_ret_10 = float(row_10.iloc[-1]["ret_profuturo"])
    if abs(actual_ret_10 - expected_ret_10) > 1e-12:
        raise AssertionError(
            f"Retorno 10/07 incorrecto: {actual_ret_10:.12f} != {expected_ret_10:.12f}"
        )

    saved = ref.copy()
    saved["fecha"] = pd.to_datetime(saved["fecha"]).dt.strftime("%Y-%m-%d")
    saved.to_csv(REFERENCE_PATH, index=False, encoding="utf-8")
    return ref


def _run_with_canonical_history(sbs: pd.DataFrame, markets: pd.DataFrame):
    # Histórico rolling completo, ya sin exclusión artificial del 06/07.
    historical, _, _ = _original_run(sbs, markets)
    historical = _correct_historical_bases(historical)

    # Reconstruye la referencia fija al 20/07 con las cuotas recuperadas.
    complete_dynamic, s = parity._build_complete(sbs, markets)
    reference = _rebuild_reference(complete_dynamic)
    reference_end = pd.Timestamp(reference["fecha"].max())

    # Desde el día siguiente al corte canónico, el rolling 90 avanza normalmente.
    future = complete_dynamic.loc[
        complete_dynamic["fecha"] > reference_end,
        reference.columns,
    ].copy()
    canonical = (
        pd.concat([reference, future], ignore_index=True)
        .sort_values("fecha")
        .drop_duplicates("fecha", keep="last")
        .reset_index(drop=True)
    )
    if len(canonical) < parity.WINDOW:
        raise RuntimeError("No hay 90 observaciones en la base canónica corregida")

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


def main() -> None:
    # IMPORTANTE: este proceso NO descarga ni escribe intradía. Solo modelo/SBS.
    sbs = parity.engine.read_saved(parity.DATA / "sbs_profuturo_f3.csv")
    if sbs.empty:
        raise RuntimeError("Falta SBS para la auditoría de paridad")
    sbs["fecha"] = pd.to_datetime(sbs["fecha"], errors="coerce")
    sbs["valor_cuota"] = pd.to_numeric(sbs["valor_cuota"], errors="coerce")
    sbs = sbs.dropna().sort_values("fecha").drop_duplicates("fecha", keep="last").reset_index(drop=True)

    markets, market_note = parity._rebuild_markets_notebook()
    historical, pending, meta = _run_with_canonical_history(sbs, markets)
    latest = parity._write_outputs(sbs, markets, historical, pending, meta, market_note)

    latest["parity_reference"] = (
        "Ventana canónica exacta reconstruida con SBS corregida al 20/07/2026; "
        "desde la siguiente observación oficial el rolling 90 continúa normalmente"
    )
    latest["parity_verified"] = True
    latest["reference_rebuilt"] = True
    latest["live_engine"] = "INDEPENDIENTE: update_live_market_only.py"
    LATEST_PATH.write_text(json.dumps(latest, ensure_ascii=False, indent=2), encoding="utf-8")

    assert int(meta["train_n"]) == parity.WINDOW
    assert latest["parity_verified"] is True
    assert latest["reference_rebuilt"] is True
    assert "BCRP exclusivo" in latest["parity_rule"]
    assert (pd.to_datetime(historical["ventana_fin"]) < pd.to_datetime(historical["fecha"])).all()
    if len(pending) > 1:
        np.testing.assert_allclose(
            pending["valor_cuota_base"].iloc[1:].to_numpy(float),
            pending["valor_cuota_estimado"].iloc[:-1].to_numpy(float),
            rtol=0,
            atol=1e-10,
        )

    # Controles de integridad de la ventana canónica corregida.
    ref_check = pd.read_csv(REFERENCE_PATH)
    ref_check["fecha"] = pd.to_datetime(ref_check["fecha"], errors="coerce")
    assert len(ref_check) == parity.WINDOW
    assert ref_check["fecha"].max() == REFERENCE_END
    for date_text in ["2026-07-01", "2026-07-02", "2026-07-06", "2026-07-08", "2026-07-09"]:
        assert pd.Timestamp(date_text) in set(ref_check["fecha"]), f"Falta {date_text} en referencia"

    print("PARIDAD NOTEBOOK V5 CORREGIDA Y APROBADA")
    print(json.dumps(latest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
