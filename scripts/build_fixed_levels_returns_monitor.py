from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "data" / "fixed_models" / "spblscup_levels_2026.csv"
SBS = ROOT / "data" / "rolling90" / "sbs_profuturo_f3.csv"
LIVE = ROOT / "public" / "data" / "live_market.json"
FIXED_INTRADAY = ROOT / "public" / "data" / "fixed_models_intraday.json"
LIVE_RET = ROOT / "data" / "analysis" / "googlefinance_alt_rolling30_live_returns.csv"
OUT_JSON = ROOT / "public" / "data" / "fixed_models_2026.json"
OUT_CSV = ROOT / "public" / "data" / "fixed_models_2026.csv"

LIMA = ZoneInfo("America/Lima")
TRAIN_START = pd.Timestamp("2026-07-07")
TRAIN_END = pd.Timestamp("2026-08-17")
VALIDATION_START = pd.Timestamp("2026-08-18")
HISTORY_START = pd.Timestamp("2026-01-05")

# Cierres SPBLSCUP auditados para las ruedas donde se detectó un desplazamiento
# de fecha provocado por un snapshot experimental antiguo. Se mantienen como
# anclas históricas y no pueden ser reemplazados por un dato con otra fecha.
AUDITED_SPBLSCUP = {
    "2026-08-28": 454.70,
    "2026-08-31": 450.67,
    "2026-09-01": 446.70,
    "2026-09-02": 455.17,
}

# Modelo recalibrado sobre la misma muestra original de 30 ruedas, corrigiendo
# únicamente los VC SBS que estaban mal transcritos en el Excel de calibración:
# 2026-08-14 = 70.8740985 y 2026-08-17 = 71.5395979.
# Los factores de la calibración conservan la precisión/redondeo del Excel
# original para mantener reproducibilidad con la hoja RLD del usuario.
LEVEL_COEFF = {
    "intercept": 16.079002570838444,
    "SPY": -0.022645639344358,
    "EEM": 0.782531468403534,
    "MCHI": -0.331228398975249,
    "QQQ": 0.017346437590436,
    "SPBLSCUP": 0.057402010773155,
}
RETURN_COEFF = {
    "intercept": 0.000712278486375,
    "SPY": -0.512994712486852,
    "EEM": 0.631737612710381,
    "MCHI": -0.296644846397524,
    "QQQ": 0.481312806588779,
    "SPBLSCUP": 0.264337624798652,
}
TRAIN_R2_LEVEL = 0.9839967207688474
TRAIN_R2_RETURN = 0.9518032304214648
TRAIN_ADJ_R2_LEVEL = 0.9806627042623572
TRAIN_ADJ_R2_RETURN = 0.94176223675927
TRAIN_STDERR_LEVEL = 0.190351025609838
TRAIN_STDERR_RETURN = 0.003847219671018321
TRAIN_SBS_CORRECTIONS = {
    "2026-08-14": 70.8740985,
    "2026-08-17": 71.5395979,
}
YAHOO = {"SPY": "SPY", "EEM": "EEM", "MCHI": "MCHI", "QQQ": "QQQ"}


def finite(v) -> bool:
    try:
        return v is not None and np.isfinite(float(v))
    except Exception:
        return False


def extract_close(raw: pd.DataFrame, ticker: str) -> pd.Series:
    if raw.empty:
        return pd.Series(dtype=float)
    if isinstance(raw.columns, pd.MultiIndex):
        for key in [("Close", ticker), (ticker, "Close")]:
            if key in raw.columns:
                return pd.to_numeric(raw[key], errors="coerce").dropna()
        if "Close" in raw.columns.get_level_values(0):
            b = raw.xs("Close", axis=1, level=0)
            if ticker in b.columns:
                return pd.to_numeric(b[ticker], errors="coerce").dropna()
    if "Close" in raw.columns:
        return pd.to_numeric(raw["Close"], errors="coerce").dropna()
    return pd.Series(dtype=float)


def yahoo_history() -> pd.DataFrame:
    start = (HISTORY_START - pd.Timedelta(days=10)).strftime("%Y-%m-%d")
    end = (pd.Timestamp.now().normalize() + pd.Timedelta(days=3)).strftime("%Y-%m-%d")
    frames = []
    for name, ticker in YAHOO.items():
        raw = yf.download(
            ticker, start=start, end=end, auto_adjust=False,
            actions=False, progress=False, threads=False
        )
        close = extract_close(raw, ticker)
        if close.empty:
            raise RuntimeError(f"Yahoo sin historia para {ticker}")
        idx = pd.to_datetime(close.index)
        if getattr(idx, "tz", None) is not None:
            idx = idx.tz_localize(None)
        frames.append(pd.DataFrame({"fecha": idx.normalize(), name: close.to_numpy(float)}))
    out = frames[0]
    for d in frames[1:]:
        out = out.merge(d, on="fecha", how="inner")
    return out.sort_values("fecha").drop_duplicates("fecha", keep="last")


def session_date(raw) -> pd.Timestamp | None:
    text = str(raw or "")[:10]
    d = pd.to_datetime(text, errors="coerce")
    if pd.isna(d):
        return None
    return pd.Timestamp(d).normalize()


def upsert_spblscup(spb: pd.DataFrame, d: pd.Timestamp, value: float, source: str) -> pd.DataFrame:
    mask = spb["fecha"].eq(d)
    if mask.any():
        spb.loc[mask, "SPBLSCUP"] = float(value)
        spb.loc[mask, "source"] = source
        return spb
    return pd.concat([spb, pd.DataFrame([{
        "fecha": d,
        "SPBLSCUP": float(value),
        "source": source,
    }])], ignore_index=True)


def apply_audited_spblscup(spb: pd.DataFrame) -> pd.DataFrame:
    for ds, value in AUDITED_SPBLSCUP.items():
        spb = upsert_spblscup(
            spb,
            pd.Timestamp(ds),
            value,
            "CIERRE SPBLSCUP AUDITADO · FECHA BLOQUEADA",
        )
    return spb


def load_spblscup_levels() -> pd.DataFrame:
    if not SEED.exists():
        raise RuntimeError(f"Falta {SEED}")
    spb = pd.read_csv(SEED)
    spb["fecha"] = pd.to_datetime(spb["fecha"], errors="coerce").dt.normalize()
    spb["SPBLSCUP"] = pd.to_numeric(spb["SPBLSCUP"], errors="coerce")
    spb = spb.dropna(subset=["fecha", "SPBLSCUP"]).sort_values("fecha")
    if "source" not in spb.columns:
        spb["source"] = "SEMILLA"

    # Restaura primero las ruedas históricas auditadas. Esto corrige cualquier
    # valor ya persistido con una fecha equivocada en una ejecución anterior.
    spb = apply_audited_spblscup(spb)

    # Completa cierres nuevos persistidos por el flujo Google Finance existente.
    if LIVE_RET.exists():
        lr = pd.read_csv(LIVE_RET)
        if "fecha" in lr.columns and "ret_SPBLSCUP" in lr.columns:
            lr["fecha"] = pd.to_datetime(lr["fecha"], errors="coerce").dt.normalize()
            lr["ret_SPBLSCUP"] = pd.to_numeric(lr["ret_SPBLSCUP"], errors="coerce")
            lr = lr.dropna(subset=["fecha", "ret_SPBLSCUP"]).sort_values("fecha")
            known = {pd.Timestamp(r.fecha): float(r.SPBLSCUP) for r in spb.itertuples()}
            source = {pd.Timestamp(r.fecha): str(r.source) for r in spb.itertuples()}
            for r in lr.itertuples():
                d = pd.Timestamp(r.fecha)
                if d in known:
                    continue
                prev_dates = [x for x in known if x < d]
                if not prev_dates:
                    continue
                prev = max(prev_dates)
                known[d] = known[prev] * (1.0 + float(r.ret_SPBLSCUP))
                source[d] = "RECONSTRUIDO · CIERRE VALIDADO GOOGLE/YAHOO"
            spb = pd.DataFrame({
                "fecha": sorted(known),
                "SPBLSCUP": [known[d] for d in sorted(known)],
                "source": [source[d] for d in sorted(known)],
            })

    # live_market contiene también activos experimentales. Solo se acepta un
    # SPBLSCUP si SU PROPIA fecha coincide con signal_date. Antes se ignoraba
    # esta comprobación y un cierre antiguo (20/08 = 446.70) se copiaba en la
    # fecha corriente, causando la repetición observada en 31/08, 01/09 y 02/09.
    if LIVE.exists():
        try:
            live = json.loads(LIVE.read_text(encoding="utf-8"))
            d = session_date(live.get("signal_date"))
            if d is not None and not bool(live.get("market_open")):
                for row in live.get("experimental_assets", []):
                    if str(row.get("serie")) != "SPBLSCUP":
                        continue
                    asset_date = session_date(row.get("timestamp"))
                    if asset_date != d:
                        print(
                            "SPBLSCUP live_market ignorado por fecha desfasada:",
                            asset_date.date().isoformat() if asset_date is not None else None,
                            "!=",
                            d.date().isoformat(),
                        )
                        continue
                    if finite(row.get("precio_actual")) and bool(row.get("validado_modelo", True)):
                        spb = upsert_spblscup(
                            spb,
                            d,
                            float(row["precio_actual"]),
                            "GOOGLE FINANCE · CIERRE SESIÓN VALIDADO · FECHA COINCIDENTE",
                        )
                        break
        except Exception as exc:
            print("Aviso: live_market no aportó SPBLSCUP:", type(exc).__name__, exc)

    # El snapshot específico de los modelos fijos es una fuente más segura para
    # el cierre reciente porque conserva la fecha del propio ticker. Se acepta
    # únicamente si el mercado ya está cerrado y ticker.timestamp = signal_date.
    if FIXED_INTRADAY.exists():
        try:
            snap = json.loads(FIXED_INTRADAY.read_text(encoding="utf-8"))
            d = session_date(snap.get("signal_date"))
            if d is not None and not bool(snap.get("market_open")):
                for row in snap.get("tickers", []):
                    if str(row.get("ticker")) != "SPBLSCUP":
                        continue
                    asset_date = session_date(row.get("timestamp"))
                    if asset_date != d:
                        continue
                    if finite(row.get("price_current")) and bool(row.get("fresh", False)):
                        spb = upsert_spblscup(
                            spb,
                            d,
                            float(row["price_current"]),
                            "GOOGLE FINANCE · SNAPSHOT FIJO DE CIERRE · FECHA COINCIDENTE",
                        )
                        break
        except Exception as exc:
            print("Aviso: fixed_models_intraday no aportó SPBLSCUP:", type(exc).__name__, exc)

    # Las ruedas auditadas prevalecen sobre cualquier fuente automática.
    spb = apply_audited_spblscup(spb)
    spb = spb.sort_values("fecha").drop_duplicates("fecha", keep="last")
    SEED.parent.mkdir(parents=True, exist_ok=True)
    persist = spb.copy()
    persist["fecha"] = persist["fecha"].dt.strftime("%Y-%m-%d")
    persist.to_csv(SEED, index=False)
    return spb


def phase(d: pd.Timestamp, has_actual: bool) -> str:
    if d < TRAIN_START:
        return "RETROSPECTIVO"
    if d <= TRAIN_END:
        return "ENTRENAMIENTO"
    return "VALIDACIÓN" if has_actual else "PROYECCIÓN"


def metric_block(df: pd.DataFrame, mask: pd.Series) -> dict:
    d = df.loc[mask].copy()
    out = {}
    for key, col in [("niveles", "error_niveles_pct"), ("retornos", "error_retornos_pct")]:
        e = pd.to_numeric(d[col], errors="coerce").dropna().to_numpy(float)
        out[key] = {
            "n": int(e.size),
            "mae_pct": float(np.mean(np.abs(e))) if e.size else None,
            "rmse_pct": float(np.sqrt(np.mean(e ** 2))) if e.size else None,
        }
    return out


def main() -> None:
    yahoo = yahoo_history()
    spb = load_spblscup_levels()
    df = spb.merge(yahoo, on="fecha", how="left")
    df = df.loc[df["fecha"] >= HISTORY_START].sort_values("fecha").reset_index(drop=True)

    sbs = pd.read_csv(SBS)
    sbs["fecha"] = pd.to_datetime(sbs["fecha"], errors="coerce").dt.normalize()
    sbs["valor_cuota"] = pd.to_numeric(sbs["valor_cuota"], errors="coerce")
    sbs = sbs.dropna(subset=["fecha", "valor_cuota"]).sort_values("fecha")
    df = df.merge(
        sbs[["fecha", "valor_cuota"]].rename(columns={"valor_cuota": "vc_sbs"}),
        on="fecha", how="left"
    )

    factors = ["SPY", "EEM", "MCHI", "QQQ", "SPBLSCUP"]
    for c in factors:
        df[c] = pd.to_numeric(df[c], errors="coerce")
        df[f"ret_{c}"] = df[c].pct_change(fill_method=None)

    df["vc_niveles"] = LEVEL_COEFF["intercept"]
    valid_levels = pd.Series(True, index=df.index)
    for c in factors:
        valid_levels &= df[c].notna()
        df["vc_niveles"] += LEVEL_COEFF[c] * df[c]
    df.loc[~valid_levels, "vc_niveles"] = np.nan

    df["ret_vc_estimado"] = RETURN_COEFF["intercept"]
    valid_returns = pd.Series(True, index=df.index)
    for c in factors:
        valid_returns &= df[f"ret_{c}"].notna()
        df["ret_vc_estimado"] += RETURN_COEFF[c] * df[f"ret_{c}"]
    df.loc[~valid_returns, "ret_vc_estimado"] = np.nan

    s_est = []
    prev_est = np.nan
    for i, row in df.iterrows():
        if i == 0 or not finite(row["ret_vc_estimado"]):
            s_est.append(np.nan)
            continue
        prev_actual = df.iloc[i - 1]["vc_sbs"]
        if finite(prev_actual):
            base = float(prev_actual)
        elif finite(prev_est):
            base = float(prev_est)
        else:
            base = np.nan
        value = base * (1.0 + float(row["ret_vc_estimado"])) if finite(base) else np.nan
        s_est.append(value)
        prev_est = value
    df["vc_retornos"] = s_est

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

    validation = metric_block(
        df, (df["fecha"] >= VALIDATION_START) & df["vc_sbs"].notna()
    )
    retrospective = metric_block(
        df, (df["fecha"] < TRAIN_START) & df["vc_sbs"].notna()
    )

    latest_actual = df.loc[df["vc_sbs"].notna()].tail(1)
    latest_row = df.loc[df[factors].notna().all(axis=1)].tail(1)
    if latest_row.empty:
        raise RuntimeError("No existe una última fila completa de mercado")
    last = latest_row.iloc[0]

    columns = [
        "fecha", "fase", "SPY", "EEM", "MCHI", "QQQ", "SPBLSCUP", "source",
        "vc_sbs", "vc_niveles", "ret_vc_estimado", "vc_retornos",
        "error_niveles_pct", "error_retornos_pct",
    ]
    out = df[columns].copy()
    out["fecha"] = out["fecha"].dt.strftime("%Y-%m-%d")
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT_CSV, index=False)

    def clean(v):
        if isinstance(v, (np.floating, float)):
            return None if not np.isfinite(v) else float(v)
        if isinstance(v, np.integer):
            return int(v)
        if pd.isna(v):
            return None
        return v

    rows = [{k: clean(v) for k, v in r.items()} for r in out.to_dict(orient="records")]
    payload = {
        "generated_at_lima": datetime.now(LIMA).isoformat(),
        "model_version": "v2-sbs-corrected-20260831",
        "history_start": HISTORY_START.date().isoformat(),
        "training": {
            "start": TRAIN_START.date().isoformat(),
            "end": TRAIN_END.date().isoformat(),
            "n": 30,
            "levels_r2": TRAIN_R2_LEVEL,
            "levels_adjusted_r2": TRAIN_ADJ_R2_LEVEL,
            "levels_standard_error": TRAIN_STDERR_LEVEL,
            "returns_r2": TRAIN_R2_RETURN,
            "returns_adjusted_r2": TRAIN_ADJ_R2_RETURN,
            "returns_standard_error": TRAIN_STDERR_RETURN,
            "sbs_corrections": TRAIN_SBS_CORRECTIONS,
        },
        "methodology": {
            "calibration_note": "Misma muestra y mismos factores del Excel RLD original; se corrigieron los VC SBS de 14/08/2026 y 17/08/2026 antes de recalibrar ambos modelos.",
            "before_training": "RETROSPECTIVO: aplica coeficientes calibrados en julio-agosto a fechas anteriores; no es validación fuera de muestra.",
            "after_training": "VALIDACIÓN/PROYECCIÓN: coeficientes v2 congelados desde 18/08/2026 para evaluación comparable.",
            "returns_base": "Usa VC SBS real del día anterior cuando existe; si no, encadena desde el VC estimado anterior.",
        },
        "models": {
            "niveles": {
                "coefficients": LEVEL_COEFF,
                "equation": "VC = 16.07900257 - 0.02264564·SPY + 0.78253147·EEM - 0.33122840·MCHI + 0.01734644·QQQ + 0.05740201·SPBLSCUP",
            },
            "retornos": {
                "coefficients": RETURN_COEFF,
                "equation": "RVC = 0.0007122785 - 0.51299471·RSPY + 0.63173761·REEM - 0.29664485·RMCHI + 0.48131281·RQQQ + 0.26433762·RSPBLSCUP",
            },
        },
        "metrics": {
            "validation_from_2026_08_18": validation,
            "retrospective_before_2026_07_07": retrospective,
        },
        "latest": {
            "market_date": pd.Timestamp(last["fecha"]).date().isoformat(),
            "vc_niveles": clean(last["vc_niveles"]),
            "ret_vc_estimado": clean(last["ret_vc_estimado"]),
            "vc_retornos": clean(last["vc_retornos"]),
            "latest_sbs_date": None if latest_actual.empty else pd.Timestamp(latest_actual.iloc[0]["fecha"]).date().isoformat(),
            "latest_sbs_vc": None if latest_actual.empty else clean(latest_actual.iloc[0]["vc_sbs"]),
        },
        "sources": {
            "SPY_EEM_MCHI_QQQ": "Yahoo Finance · cierre diario no ajustado",
            "SPBLSCUP": "Semilla auditada + Google Finance (SPBLSCUP:INDEXSP) con control estricto de fecha",
            "VC_SBS": "data/rolling90/sbs_profuturo_f3.csv · serie oficial usada por el monitor",
        },
        "rows": rows,
    }
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"rows": len(rows), "last": payload["latest"], "validation": validation}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
