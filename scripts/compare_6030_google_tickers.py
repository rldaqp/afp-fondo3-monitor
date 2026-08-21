from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

import build_reduced_6030_challenger as m

ROOT = Path(__file__).resolve().parents[1]
ALT_PATH = ROOT / "data" / "analysis" / "googlefinance_alt_6030_returns_20260303_20260820.csv"
OUT_JSON = ROOT / "data" / "analysis" / "compare_6030_google_tickers_20260818.json"
OUT_CSV = ROOT / "data" / "analysis" / "compare_6030_google_tickers_20260818.csv"

CURRENT_FEATURES = m.REDUCED_FEATURES
ALT_FEATURES = [
    "ret_.INX",
    "ret_CPER",
    "ret_EEM_alt",
    "ret_NDX",
    "ret_SPBLSCUP",
    "ret_USD_PEN_alt",
]


def fit(train: pd.DataFrame, features: list[str]) -> tuple[np.ndarray, dict[str, float]]:
    X = train[features].to_numpy(float)
    y = train["ret_target"].to_numpy(float)
    beta = np.linalg.lstsq(np.c_[np.ones(len(X)), X], y, rcond=None)[0]
    names = ["intercept", *features]
    return beta, {name: float(value) for name, value in zip(names, beta)}


def predict(beta: np.ndarray, row: pd.Series, features: list[str]) -> float:
    return float(np.r_[1.0, row[features].to_numpy(float)] @ beta)


def main() -> None:
    markets = m.read_csv(m.DATA / "markets.csv")
    sbs = m.read_csv(m.DATA / "sbs_profuturo_f3.csv")
    alt = pd.read_csv(ALT_PATH)
    if markets.empty or sbs.empty or alt.empty:
        raise RuntimeError("Faltan datos para la comparación 60/30")

    markets["fecha"] = pd.to_datetime(markets["fecha"], errors="coerce")
    sbs["fecha"] = pd.to_datetime(sbs["fecha"], errors="coerce")
    alt["fecha"] = pd.to_datetime(alt["fecha"], errors="coerce")

    # QQQ se obtiene exactamente con la misma rutina del challenger actual.
    start = min(markets["fecha"].dropna().min(), pd.Timestamp("2026-02-01"))
    qqq = m.download_qqq(start, pd.Timestamp("2026-08-19"))

    # Factores del challenger actual: SPY, EEM, EPU, MCHI, USD/PEN y QQQ.
    mq = markets.merge(qqq[["fecha", "ret_QQQ"]], on="fecha", how="left")
    current = mq[["fecha", *CURRENT_FEATURES]].copy()
    for col in CURRENT_FEATURES:
        current[col] = pd.to_numeric(current[col], errors="coerce")

    # Factores de la alternativa solicitada, conservando los símbolos de Google Finance.
    alt = alt.rename(columns={
        "ret_EEM": "ret_EEM_alt",
        "ret_USD_PEN": "ret_USD_PEN_alt",
    })
    for col in ALT_FEATURES:
        alt[col] = pd.to_numeric(alt[col], errors="coerce")
    alt = alt[["fecha", *ALT_FEATURES]]

    factors = current.merge(alt, on="fecha", how="inner")
    factors = factors.dropna(subset=[*CURRENT_FEATURES, *ALT_FEATURES]).sort_values("fecha").drop_duplicates("fecha", keep="last")

    sbs["valor_cuota"] = pd.to_numeric(sbs["valor_cuota"], errors="coerce")
    sbs = sbs.dropna(subset=["fecha", "valor_cuota"]).sort_values("fecha").drop_duplicates("fecha", keep="last")
    sbs["ret_target"] = sbs["valor_cuota"].pct_change(fill_method=None)

    # Para que la comparación sea limpia, ambos modelos usan exactamente las mismas fechas.
    common = sbs[["fecha", "valor_cuota", "ret_target"]].merge(factors, on="fecha", how="inner")
    common = common.dropna(subset=["ret_target", *CURRENT_FEATURES, *ALT_FEATURES]).sort_values("fecha").reset_index(drop=True)

    latest_sbs_date = pd.Timestamp(sbs["fecha"].max()).normalize()
    eligible = common.loc[common["fecha"] <= latest_sbs_date].copy()
    if len(eligible) < 80:
        raise RuntimeError(f"Muestra común insuficiente: {len(eligible)}")

    # Últimos 20 días con VC oficial SBS. Se consideran 20 sesiones de un bloque
    # 60/30: 60 observaciones previas de entrenamiento, coeficientes congelados y
    # cadena ciega sin reanclaje SBS durante la prueba.
    test = eligible.tail(20).copy().reset_index(drop=True)
    test_start = pd.Timestamp(test.iloc[0]["fecha"])
    train = eligible.loc[eligible["fecha"] < test_start].tail(60).copy().reset_index(drop=True)
    if len(train) != 60:
        raise RuntimeError(f"Entrenamiento incompleto: {len(train)}")

    cur_beta, cur_coeff = fit(train, CURRENT_FEATURES)
    alt_beta, alt_coeff = fit(train, ALT_FEATURES)

    anchor = train.iloc[-1]
    cur_vc = float(anchor["valor_cuota"])
    alt_vc = float(anchor["valor_cuota"])
    rows: list[dict] = []

    for _, row in test.iterrows():
        cur_ret = predict(cur_beta, row, CURRENT_FEATURES)
        alt_ret = predict(alt_beta, row, ALT_FEATURES)
        cur_vc *= 1.0 + cur_ret
        alt_vc *= 1.0 + alt_ret
        actual = float(row["valor_cuota"])
        rows.append({
            "fecha": pd.Timestamp(row["fecha"]).date().isoformat(),
            "vc_6030_actual": cur_vc,
            "ret_6030_actual": cur_ret,
            "vc_6030_tickers_google": alt_vc,
            "ret_6030_tickers_google": alt_ret,
            "vc_sbs_real": actual,
            "error_abs_actual": abs(cur_vc - actual),
            "error_abs_tickers_google": abs(alt_vc - actual),
            "mejor": "TICKERS GOOGLE" if abs(alt_vc - actual) < abs(cur_vc - actual) else ("ACTUAL" if abs(cur_vc - actual) < abs(alt_vc - actual) else "EMPATE"),
        })

    result = pd.DataFrame(rows)
    mae_current = float(result["error_abs_actual"].mean())
    mae_alt = float(result["error_abs_tickers_google"].mean())
    rmse_current = float(np.sqrt(np.mean(np.square(result["vc_6030_actual"] - result["vc_sbs_real"]))))
    rmse_alt = float(np.sqrt(np.mean(np.square(result["vc_6030_tickers_google"] - result["vc_sbs_real"]))))

    payload = {
        "method": "Comparación ciega homogénea 60/30: mismas 60 fechas de entrenamiento y 20 fechas de prueba dentro del horizonte congelado de 30; sin reanclaje SBS durante la prueba.",
        "train_start": pd.Timestamp(train.iloc[0]["fecha"]).date().isoformat(),
        "train_end": pd.Timestamp(train.iloc[-1]["fecha"]).date().isoformat(),
        "train_n": int(len(train)),
        "anchor_date": pd.Timestamp(anchor["fecha"]).date().isoformat(),
        "anchor_vc": float(anchor["valor_cuota"]),
        "test_start": pd.Timestamp(test.iloc[0]["fecha"]).date().isoformat(),
        "test_end": pd.Timestamp(test.iloc[-1]["fecha"]).date().isoformat(),
        "test_n": int(len(test)),
        "current_features": CURRENT_FEATURES,
        "alternative_features_display": [".INX", "CPER", "EEM", "NDX", "SPBLSCUP", "USD/PEN"],
        "alternative_source": "Google Finance exact symbols supplied by user; historical daily closes converted to daily returns.",
        "current_coefficients": cur_coeff,
        "alternative_coefficients": alt_coeff,
        "metrics": {
            "mae_vc_current": mae_current,
            "mae_vc_alternative": mae_alt,
            "rmse_vc_current": rmse_current,
            "rmse_vc_alternative": rmse_alt,
            "alternative_better_days": int((result["mejor"] == "TICKERS GOOGLE").sum()),
            "current_better_days": int((result["mejor"] == "ACTUAL").sum()),
        },
        "rows": rows,
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    result.to_csv(OUT_CSV, index=False, encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
