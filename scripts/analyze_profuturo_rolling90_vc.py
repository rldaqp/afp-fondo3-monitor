from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "rolling90"
OUT = ROOT / "analysis" / "profuturo_rolling90_vc_validation.json"
PRED_OUT = ROOT / "analysis" / "profuturo_rolling90_vc_predictions.csv"

WINDOW = 90
THRESHOLD = 0.001
BLIND_CUTOFF = pd.Timestamp("2026-08-06")
TARGET_END = pd.Timestamp("2026-08-20")
KNOWN_SBS_19 = 70.327

OFFICIAL_FEATURES = [
    "ret_SPY", "ret_EEM", "ret_EPU", "ret_MCHI",
    "ret_NEM", "ret_FCX", "ret_USD_PEN",
]
ALT_FEATURES = [
    "ret_SPY", "ret_EEM", "ret_EPU", "ret_MCHI",
    "ret_USD_PEN", "ret_QQQ",
]


def classify(x: float) -> str:
    if x > THRESHOLD:
        return "SUBE"
    if x < -THRESHOLD:
        return "BAJA"
    return "NEUTRO"


def read_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce")
    return df.dropna(subset=["fecha"]).sort_values("fecha").drop_duplicates("fecha", keep="last").reset_index(drop=True)


def extract_close(raw: pd.DataFrame, ticker: str) -> pd.Series:
    if raw.empty:
        return pd.Series(dtype=float)
    if isinstance(raw.columns, pd.MultiIndex):
        for key in [("Close", ticker), (ticker, "Close")]:
            if key in raw.columns:
                return pd.to_numeric(raw[key], errors="coerce").dropna()
        if "Close" in raw.columns.get_level_values(0):
            block = raw.xs("Close", axis=1, level=0)
            if ticker in block.columns:
                return pd.to_numeric(block[ticker], errors="coerce").dropna()
    if "Close" in raw.columns:
        return pd.to_numeric(raw["Close"], errors="coerce").dropna()
    raise RuntimeError("Yahoo no devolvió Close utilizable para QQQ")


def load_qqq(start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    raw = yf.download(
        "QQQ",
        start=(start - pd.Timedelta(days=10)).strftime("%Y-%m-%d"),
        end=(end + pd.Timedelta(days=2)).strftime("%Y-%m-%d"),
        auto_adjust=False,
        actions=False,
        progress=False,
        threads=False,
    )
    close = extract_close(raw, "QQQ")
    if close.empty:
        raise RuntimeError("No se pudo descargar QQQ")
    idx = pd.to_datetime(close.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    q = pd.DataFrame({"fecha": idx.normalize(), "QQQ": close.to_numpy(float)})
    q = q.sort_values("fecha").drop_duplicates("fecha", keep="last")
    q["ret_QQQ"] = q["QQQ"].pct_change(fill_method=None)
    return q[["fecha", "QQQ", "ret_QQQ"]]


def fit_ols(train: pd.DataFrame, features: list[str]) -> np.ndarray:
    x = train[features].to_numpy(float)
    y = train["ret_target"].to_numpy(float)
    return np.linalg.lstsq(np.c_[np.ones(len(x)), x], y, rcond=None)[0]


def predict(beta: np.ndarray, row: pd.Series, features: list[str]) -> float:
    return float(np.r_[1.0, row[features].to_numpy(float)] @ beta)


def coefficient_dict(beta: np.ndarray, features: list[str]) -> dict[str, float]:
    out = {"intercept": float(beta[0])}
    out.update({features[i]: float(beta[i + 1]) for i in range(len(features))})
    return out


def prepare_train(
    sbs: pd.DataFrame,
    marketq: pd.DataFrame,
    features: list[str],
    cutoff: pd.Timestamp,
) -> pd.DataFrame:
    frame = sbs[["fecha", "valor_cuota", "ret_target"]].merge(
        marketq[["fecha", *features]], on="fecha", how="inner"
    )
    frame = frame.loc[frame["fecha"] <= cutoff]
    frame = frame.dropna(subset=["valor_cuota", "ret_target", *features])
    frame = frame.sort_values("fecha").drop_duplicates("fecha", keep="last")
    if len(frame) < WINDOW:
        raise RuntimeError(f"Muestra insuficiente para {features}: {len(frame)}")
    return frame.tail(WINDOW).reset_index(drop=True)


def fill_pending_fx(marketq: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, object]]:
    pending_path = DATA / "pending_predictions.csv"
    info: dict[str, object] = {"used": False}
    if not pending_path.exists():
        return marketq, info
    pending = read_csv(pending_path)
    if "ret_USD_PEN" not in pending.columns:
        return marketq, info
    pending["ret_USD_PEN"] = pd.to_numeric(pending["ret_USD_PEN"], errors="coerce")
    out = marketq.copy()
    for _, p in pending.loc[(pending["fecha"] > BLIND_CUTOFF) & (pending["fecha"] <= TARGET_END)].iterrows():
        if pd.isna(p["ret_USD_PEN"]):
            continue
        mask = out["fecha"].eq(p["fecha"])
        if mask.any() and out.loc[mask, "ret_USD_PEN"].isna().all():
            out.loc[mask, "ret_USD_PEN"] = float(p["ret_USD_PEN"])
            info = {
                "used": True,
                "date": pd.Timestamp(p["fecha"]).strftime("%Y-%m-%d"),
                "ret_USD_PEN": float(p["ret_USD_PEN"]),
                "source": str(p.get("usd_pen_fuente", "pending_predictions.csv")),
                "provisional": bool(p.get("usd_pen_provisional", True)),
            }
    return out, info


def blind_path(
    name: str,
    beta: np.ndarray,
    features: list[str],
    marketq: pd.DataFrame,
    anchor_vc: float,
    actual_map: dict[pd.Timestamp, float],
) -> pd.DataFrame:
    needed = sorted(set(OFFICIAL_FEATURES + ALT_FEATURES))
    future = marketq.loc[(marketq["fecha"] > BLIND_CUTOFF) & (marketq["fecha"] <= TARGET_END)].copy()
    # En este tramo 7-20 agosto no hay feriados bursátiles de EE.UU.; exigimos solo las variables del modelo.
    future = future.dropna(subset=features).sort_values("fecha").drop_duplicates("fecha", keep="last")
    vc = float(anchor_vc)
    rows: list[dict[str, object]] = []
    for _, row in future.iterrows():
        pred_ret = predict(beta, row, features)
        base = vc
        vc = float(vc * (1.0 + pred_ret))
        fecha = pd.Timestamp(row["fecha"])
        actual_vc = actual_map.get(fecha)
        rows.append({
            "fecha": fecha,
            "model": name,
            "base_blind_vc": base,
            "pred_return": pred_ret,
            "pred_signal": classify(pred_ret),
            "pred_vc_blind": vc,
            "actual_vc": actual_vc,
            "error_signed": None if actual_vc is None else float(vc - actual_vc),
            "error_abs": None if actual_vc is None else float(abs(vc - actual_vc)),
        })
    return pd.DataFrame(rows)


def path_metrics(path: pd.DataFrame) -> dict[str, object]:
    v = path.dropna(subset=["actual_vc"]).copy()
    err = v["pred_vc_blind"].to_numpy(float) - v["actual_vc"].to_numpy(float)
    rel = np.abs(err) / v["actual_vc"].to_numpy(float)
    return {
        "n": int(len(v)),
        "start": v.iloc[0]["fecha"].strftime("%Y-%m-%d"),
        "end": v.iloc[-1]["fecha"].strftime("%Y-%m-%d"),
        "vc_mae": float(np.mean(np.abs(err))),
        "vc_rmse": float(np.sqrt(np.mean(err ** 2))),
        "vc_mape_pct": float(np.mean(rel) * 100.0),
        "vc_bias": float(np.mean(err)),
        "within_0_5pct": float(np.mean(rel <= 0.005)),
        "within_1pct": float(np.mean(rel <= 0.01)),
        "final_actual_vc": float(v.iloc[-1]["actual_vc"]),
        "final_pred_vc": float(v.iloc[-1]["pred_vc_blind"]),
        "final_error": float(v.iloc[-1]["pred_vc_blind"] - v.iloc[-1]["actual_vc"]),
    }


def main() -> None:
    markets = read_csv(DATA / "markets.csv")
    sbs = read_csv(DATA / "sbs_profuturo_f3.csv")
    sbs["valor_cuota"] = pd.to_numeric(sbs["valor_cuota"], errors="coerce")
    sbs = sbs.dropna(subset=["valor_cuota"]).copy()
    sbs["ret_target"] = sbs["valor_cuota"].pct_change(fill_method=None)

    qqq = load_qqq(markets["fecha"].min(), TARGET_END)
    marketq = markets.merge(qqq, on="fecha", how="left")
    marketq, fx_info = fill_pending_fx(marketq)

    anchor_row = sbs.loc[sbs["fecha"].eq(BLIND_CUTOFF)]
    if anchor_row.empty:
        raise RuntimeError("No existe VC SBS del 2026-08-06 para anclar la prueba ciega")
    anchor_vc = float(anchor_row.iloc[-1]["valor_cuota"])

    train_official = prepare_train(sbs, marketq, OFFICIAL_FEATURES, BLIND_CUTOFF)
    train_alt = prepare_train(sbs, marketq, ALT_FEATURES, BLIND_CUTOFF)
    beta_official = fit_ols(train_official, OFFICIAL_FEATURES)
    beta_alt = fit_ols(train_alt, ALT_FEATURES)

    actual_map = {
        pd.Timestamp(r["fecha"]): float(r["valor_cuota"])
        for _, r in sbs.loc[(sbs["fecha"] > BLIND_CUTOFF) & (sbs["fecha"] <= TARGET_END)].iterrows()
    }
    # El 19 se usa exclusivamente para evaluar después de pronosticar; nunca entra al entrenamiento.
    actual_map[pd.Timestamp("2026-08-19")] = KNOWN_SBS_19

    official = blind_path(
        "ACTUAL_GITHUB_7F", beta_official, OFFICIAL_FEATURES, marketq, anchor_vc, actual_map
    )
    alt = blind_path(
        "SIN_NEM_FCX_MAS_QQQ", beta_alt, ALT_FEATURES, marketq, anchor_vc, actual_map
    )

    common_dates = sorted(set(official["fecha"]).intersection(set(alt["fecha"])))
    official = official.loc[official["fecha"].isin(common_dates)].reset_index(drop=True)
    alt = alt.loc[alt["fecha"].isin(common_dates)].reset_index(drop=True)

    comp = official[["fecha", "actual_vc", "pred_vc_blind", "pred_return", "error_abs", "error_signed"]].rename(columns={
        "pred_vc_blind": "vc_actual_model_blind",
        "pred_return": "ret_actual_model",
        "error_abs": "abs_err_actual_model",
        "error_signed": "err_actual_model",
    }).merge(
        alt[["fecha", "pred_vc_blind", "pred_return", "error_abs", "error_signed"]].rename(columns={
            "pred_vc_blind": "vc_alt_blind",
            "pred_return": "ret_alt",
            "error_abs": "abs_err_alt",
            "error_signed": "err_alt",
        }), on="fecha", how="inner"
    )
    comp["alt_minus_actual_model"] = comp["vc_alt_blind"] - comp["vc_actual_model_blind"]
    comp["winner"] = np.where(
        comp["actual_vc"].isna(),
        "SIN SBS",
        np.where(comp["abs_err_alt"] < comp["abs_err_actual_model"], "SIN NEM/FCX + QQQ", "ACTUAL GITHUB"),
    )

    payload = {
        "generated_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "fund": "PROFUTURO Fondo 3",
        "purpose": "Prueba ciega estricta: después del VC SBS del 06/08 no se usa ningún VC SBS para reanclar el nivel ni para recalibrar los coeficientes. Solo entran retornos observados de indicadores.",
        "blind_cutoff": BLIND_CUTOFF.strftime("%Y-%m-%d"),
        "anchor_vc_sbs": anchor_vc,
        "target_end": TARGET_END.strftime("%Y-%m-%d"),
        "important_method_note": "Una vez que se prohíbe usar nuevos VC SBS, un rolling90 genuino ya no puede recalibrarse porque falta la variable objetivo. Por eso esta es la prueba sin fuga de información correcta: ambos modelos se estiman una sola vez con las últimas 90 observaciones conocidas al 06/08, se congelan y desde el 07/08 se encadena el VC usando únicamente los indicadores. El VC SBS posterior se revela solo al final para medir error.",
        "models": {
            "ACTUAL_GITHUB_7F": {
                "features": OFFICIAL_FEATURES,
                "train_n": int(len(train_official)),
                "train_start": train_official.iloc[0]["fecha"].strftime("%Y-%m-%d"),
                "train_end": train_official.iloc[-1]["fecha"].strftime("%Y-%m-%d"),
                "coefficients": coefficient_dict(beta_official, OFFICIAL_FEATURES),
                "metrics_blind": path_metrics(official),
            },
            "SIN_NEM_FCX_MAS_QQQ": {
                "features": ALT_FEATURES,
                "train_n": int(len(train_alt)),
                "train_start": train_alt.iloc[0]["fecha"].strftime("%Y-%m-%d"),
                "train_end": train_alt.iloc[-1]["fecha"].strftime("%Y-%m-%d"),
                "coefficients": coefficient_dict(beta_alt, ALT_FEATURES),
                "metrics_blind": path_metrics(alt),
            },
        },
        "fx_pending_fill": fx_info,
        "sbs_19_used_only_for_evaluation": KNOWN_SBS_19,
        "comparison": [
            {
                "fecha": r["fecha"].strftime("%Y-%m-%d"),
                "actual_vc": None if pd.isna(r["actual_vc"]) else float(r["actual_vc"]),
                "vc_actual_model_blind": float(r["vc_actual_model_blind"]),
                "vc_alt_blind": float(r["vc_alt_blind"]),
                "abs_err_actual_model": None if pd.isna(r["abs_err_actual_model"]) else float(r["abs_err_actual_model"]),
                "abs_err_alt": None if pd.isna(r["abs_err_alt"]) else float(r["abs_err_alt"]),
                "alt_minus_actual_model": float(r["alt_minus_actual_model"]),
                "winner": str(r["winner"]),
            }
            for _, r in comp.iterrows()
        ],
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    out_csv = comp.copy()
    out_csv["fecha"] = pd.to_datetime(out_csv["fecha"]).dt.strftime("%Y-%m-%d")
    out_csv.to_csv(PRED_OUT, index=False)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
