from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

import build_reduced_6030_challenger as m

ROOT = Path(__file__).resolve().parents[1]
ALT_CLOSES = ROOT / "data" / "analysis" / "googlefinance_alt_aligned_closes_20260402_20260820.csv"
OUT_JSON = ROOT / "public" / "data" / "compare_6030_exact20.json"
OUT_CSV = ROOT / "data" / "analysis" / "compare_6030_exact20.csv"

ALT_CLOSE_COLS = [".INX", "CPER", "EEM", "NDX", "SPBLSCUP", "USD_PEN"]
ALT_FEATURES = ["ret_.INX", "ret_CPER", "ret_EEM_alt", "ret_NDX", "ret_SPBLSCUP", "ret_USD_PEN_alt"]
TEST_DATES = pd.to_datetime([
    "2026-07-22", "2026-07-23", "2026-07-24", "2026-07-27", "2026-07-28",
    "2026-07-29", "2026-07-30", "2026-07-31", "2026-08-03", "2026-08-04",
    "2026-08-05", "2026-08-06", "2026-08-07", "2026-08-10", "2026-08-11",
    "2026-08-12", "2026-08-13", "2026-08-14", "2026-08-17", "2026-08-18",
])
PROJ_DATES = pd.to_datetime(["2026-08-19", "2026-08-20"])


def fit(train: pd.DataFrame, features: list[str]) -> tuple[np.ndarray, dict[str, float]]:
    x = train[features].to_numpy(float)
    y = train["ret_target"].to_numpy(float)
    beta = np.linalg.lstsq(np.c_[np.ones(len(x)), x], y, rcond=None)[0]
    names = ["intercept", *features]
    return beta, {name: float(value) for name, value in zip(names, beta)}


def pred(beta: np.ndarray, row: pd.Series, features: list[str]) -> float:
    return float(np.r_[1.0, row[features].to_numpy(float)] @ beta)


def build_alt() -> pd.DataFrame:
    alt = pd.read_csv(ALT_CLOSES)
    alt["fecha"] = pd.to_datetime(alt["fecha"], errors="coerce")
    for c in ALT_CLOSE_COLS:
        alt[c] = pd.to_numeric(alt[c], errors="coerce")
    alt = alt.dropna(subset=["fecha", *ALT_CLOSE_COLS]).sort_values("fecha").drop_duplicates("fecha", keep="last")
    for c in ALT_CLOSE_COLS:
        alt[f"ret_{c}"] = alt[c].pct_change(fill_method=None)
    alt = alt.rename(columns={"ret_EEM": "ret_EEM_alt", "ret_USD_PEN": "ret_USD_PEN_alt"})
    return alt[["fecha", *ALT_FEATURES]].copy()


def main() -> None:
    markets = m.read_csv(m.DATA / "markets.csv")
    sbs_raw = m.read_csv(m.DATA / "sbs_profuturo_f3.csv")
    if markets.empty or sbs_raw.empty:
        raise RuntimeError("Faltan markets.csv o SBS")

    markets["fecha"] = pd.to_datetime(markets["fecha"], errors="coerce")
    qqq = m.download_qqq(pd.Timestamp("2026-04-01"), pd.Timestamp("2026-08-20"))
    common, sbs, mq = m.prepare_frames(markets, sbs_raw, qqq)
    alt = build_alt()

    # Misma base de observaciones del challenger actual; luego se añaden los nuevos tickers.
    both = common.merge(alt, on="fecha", how="inner")
    both = both.dropna(subset=[*m.REDUCED_FEATURES, *ALT_FEATURES, "ret_target", "valor_cuota"]).sort_values("fecha").drop_duplicates("fecha", keep="last").reset_index(drop=True)

    test = both.loc[both["fecha"].isin(TEST_DATES)].copy().sort_values("fecha").reset_index(drop=True)
    if list(test["fecha"]) != list(TEST_DATES):
        missing = [d.date().isoformat() for d in TEST_DATES if d not in set(test["fecha"])]
        raise RuntimeError(f"Faltan fechas exactas del test: {missing}")

    test_start = TEST_DATES[0]
    train = both.loc[both["fecha"] < test_start].tail(60).copy().reset_index(drop=True)
    if len(train) != 60:
        raise RuntimeError(f"Entrenamiento histórico incompleto: {len(train)}")
    anchor = train.iloc[-1]
    if pd.Timestamp(anchor["fecha"]) != pd.Timestamp("2026-07-21"):
        raise RuntimeError(f"Ancla histórica inesperada: {anchor['fecha']}")

    cur_beta, cur_coeff = fit(train, m.REDUCED_FEATURES)
    alt_beta, alt_coeff = fit(train, ALT_FEATURES)
    cur_vc = float(anchor["valor_cuota"])
    alt_vc = float(anchor["valor_cuota"])
    rows: list[dict] = []
    for _, r in test.iterrows():
        cur_ret = pred(cur_beta, r, m.REDUCED_FEATURES)
        alt_ret = pred(alt_beta, r, ALT_FEATURES)
        cur_vc *= 1.0 + cur_ret
        alt_vc *= 1.0 + alt_ret
        actual = float(r["valor_cuota"])
        err_cur = abs(cur_vc - actual)
        err_alt = abs(alt_vc - actual)
        rows.append({
            "fecha": pd.Timestamp(r["fecha"]).date().isoformat(),
            "vc_challenger_6030": cur_vc,
            "ret_challenger_6030": cur_ret,
            "vc_nuevos_tickers_6030": alt_vc,
            "ret_nuevos_tickers_6030": alt_ret,
            "vc_sbs_real": actual,
            "error_abs_challenger": err_cur,
            "error_abs_nuevos_tickers": err_alt,
            "mejor": "NUEVOS TICKERS" if err_alt < err_cur else ("CHALLENGER" if err_cur < err_alt else "EMPATE"),
        })

    hist = pd.DataFrame(rows)

    # Proyección 19-20/08: recalibración de ambos modelos con 60 observaciones hasta el ancla SBS 18/08.
    anchor_date = pd.Timestamp("2026-08-18")
    proj_train = both.loc[both["fecha"] <= anchor_date].tail(60).copy().reset_index(drop=True)
    if len(proj_train) != 60 or pd.Timestamp(proj_train.iloc[-1]["fecha"]) != anchor_date:
        raise RuntimeError("Entrenamiento de proyección 18/08 incompleto")
    proj_cur_beta, proj_cur_coeff = fit(proj_train, m.REDUCED_FEATURES)
    proj_alt_beta, proj_alt_coeff = fit(proj_train, ALT_FEATURES)

    sbs_anchor = sbs.loc[sbs["fecha"].eq(anchor_date), "valor_cuota"]
    if sbs_anchor.empty:
        raise RuntimeError("No existe VC SBS del 18/08")
    anchor_vc = float(sbs_anchor.iloc[-1])

    current_pred_frame = mq.merge(alt, on="fecha", how="inner")
    current_pred_frame = current_pred_frame.loc[current_pred_frame["fecha"].isin(PROJ_DATES)].copy().sort_values("fecha")
    current_pred_frame = current_pred_frame.dropna(subset=[*m.REDUCED_FEATURES, *ALT_FEATURES])
    if list(current_pred_frame["fecha"]) != list(PROJ_DATES):
        missing = [d.date().isoformat() for d in PROJ_DATES if d not in set(current_pred_frame["fecha"])]
        raise RuntimeError(f"Faltan fechas de proyección: {missing}")

    ledger = m.ledger_read()
    cur_proj_vc = anchor_vc
    alt_proj_vc = anchor_vc
    projections: list[dict] = []
    for _, r in current_pred_frame.iterrows():
        d = pd.Timestamp(r["fecha"])
        cur_ret = pred(proj_cur_beta, r, m.REDUCED_FEATURES)
        alt_ret = pred(proj_alt_beta, r, ALT_FEATURES)
        cur_proj_vc *= 1.0 + cur_ret
        alt_proj_vc *= 1.0 + alt_ret
        ledger_row = ledger.loc[ledger["fecha"].eq(d)] if not ledger.empty else pd.DataFrame()
        ledger_vc = None if ledger_row.empty else float(pd.to_numeric(ledger_row.iloc[-1]["challenger_vc"], errors="coerce"))
        projections.append({
            "fecha": d.date().isoformat(),
            "vc_challenger_6030_recalculado": cur_proj_vc,
            "ret_challenger_6030_recalculado": cur_ret,
            "vc_challenger_6030_ledger": ledger_vc,
            "diferencia_vs_ledger": None if ledger_vc is None else cur_proj_vc - ledger_vc,
            "vc_nuevos_tickers_6030": alt_proj_vc,
            "ret_nuevos_tickers_6030": alt_ret,
            "vc_sbs_real": None,
        })

    mae_cur = float(hist["error_abs_challenger"].mean())
    mae_alt = float(hist["error_abs_nuevos_tickers"].mean())
    rmse_cur = float(np.sqrt(np.mean(np.square(hist["vc_challenger_6030"] - hist["vc_sbs_real"]))))
    rmse_alt = float(np.sqrt(np.mean(np.square(hist["vc_nuevos_tickers_6030"] - hist["vc_sbs_real"]))))

    payload = {
        "method": "Comparación corregida: exactamente los últimos 20 VC SBS consecutivos (22/07-18/08). Ambos backtests usan las mismas 60 observaciones anteriores, coeficientes congelados y cadena ciega. SPBLSCUP se mantiene sin variación en días sin cierre peruano mediante último cierre disponible. Proyección 19-20 usa ancla SBS 18/08 y 60 observaciones hasta esa fecha.",
        "historical": {
            "train_start": pd.Timestamp(train.iloc[0]["fecha"]).date().isoformat(),
            "train_end": pd.Timestamp(train.iloc[-1]["fecha"]).date().isoformat(),
            "anchor_date": pd.Timestamp(anchor["fecha"]).date().isoformat(),
            "anchor_vc": float(anchor["valor_cuota"]),
            "test_start": TEST_DATES[0].date().isoformat(),
            "test_end": TEST_DATES[-1].date().isoformat(),
            "test_n": len(rows),
            "current_coefficients": cur_coeff,
            "alternative_coefficients": alt_coeff,
            "rows": rows,
            "metrics": {
                "mae_challenger": mae_cur,
                "mae_nuevos_tickers": mae_alt,
                "rmse_challenger": rmse_cur,
                "rmse_nuevos_tickers": rmse_alt,
                "challenger_better_days": int((hist["mejor"] == "CHALLENGER").sum()),
                "new_tickers_better_days": int((hist["mejor"] == "NUEVOS TICKERS").sum()),
            },
        },
        "projection": {
            "train_start": pd.Timestamp(proj_train.iloc[0]["fecha"]).date().isoformat(),
            "train_end": pd.Timestamp(proj_train.iloc[-1]["fecha"]).date().isoformat(),
            "anchor_date": anchor_date.date().isoformat(),
            "anchor_vc": anchor_vc,
            "current_coefficients": proj_cur_coeff,
            "alternative_coefficients": proj_alt_coeff,
            "rows": projections,
        },
        "alternative_features_display": [".INX", "CPER", "EEM", "NDX", "SPBLSCUP", "USD/PEN"],
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    pd.concat([hist, pd.DataFrame(projections)], ignore_index=True, sort=False).to_csv(OUT_CSV, index=False, encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
