from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

import build_reduced_6030_challenger as m

OUT_PATH = m.PUBLIC / "reduced_6030_history.json"


def build_backtest_history(common: pd.DataFrame) -> list[dict]:
    rows: list[dict] = []
    start0 = 90
    block_id = 0
    for block_start in range(start0, len(common) - m.FREEZE_HORIZON + 1, m.FREEZE_HORIZON):
        block_id += 1
        block_end = block_start + m.FREEZE_HORIZON
        train = common.iloc[block_start - m.TRAIN_WINDOW:block_start]
        red_beta, _ = m.fit_ols(train, m.REDUCED_FEATURES)
        off_beta, _ = m.fit_ols(train, m.OFFICIAL_FEATURES)
        anchor = common.iloc[block_start - 1]
        red_vc = float(anchor["valor_cuota"])
        off_vc = red_vc
        for i in range(block_start, block_end):
            r = common.iloc[i]
            red_ret = float(np.r_[1.0, r[m.REDUCED_FEATURES].to_numpy(float)] @ red_beta)
            off_ret = float(np.r_[1.0, r[m.OFFICIAL_FEATURES].to_numpy(float)] @ off_beta)
            red_vc *= 1.0 + red_ret
            off_vc *= 1.0 + off_ret
            actual_vc = float(r["valor_cuota"])
            rows.append({
                "fecha": pd.Timestamp(r["fecha"]).date().isoformat(),
                "source": "BACKTEST CIEGO 60/30",
                "block": block_id,
                "anchor_date": pd.Timestamp(anchor["fecha"]).date().isoformat(),
                "anchor_vc": float(anchor["valor_cuota"]),
                "train_start": pd.Timestamp(train.iloc[0]["fecha"]).date().isoformat(),
                "train_end": pd.Timestamp(train.iloc[-1]["fecha"]).date().isoformat(),
                "challenger_vc": red_vc,
                "challenger_return": red_ret,
                "official_vc": off_vc,
                "official_return": off_ret,
                "actual_vc": actual_vc,
                "challenger_abs_error": abs(red_vc - actual_vc),
                "official_abs_error": abs(off_vc - actual_vc),
            })
    return rows


def build_operational_history(state: dict, ledger: pd.DataFrame, sbs: pd.DataFrame) -> list[dict]:
    rows: list[dict] = []
    if state:
        anchor_date = str(state.get("anchor_date", ""))[:10]
        anchor_vc = state.get("anchor_vc")
        if anchor_date and anchor_vc is not None:
            rows.append({
                "fecha": anchor_date,
                "source": "ANCLA SBS DEL CICLO",
                "challenger_vc": float(anchor_vc),
                "challenger_return": None,
                "official_vc": None,
                "official_return": None,
                "actual_vc": float(anchor_vc),
                "challenger_abs_error": 0.0,
                "official_abs_error": None,
                "cycle_start": state.get("cycle_start"),
                "train_start": state.get("train_start"),
                "train_end": state.get("train_end"),
            })
    if ledger.empty:
        return rows
    actual_map = {}
    if not sbs.empty:
        actual_map = {
            pd.Timestamp(r["fecha"]).date().isoformat(): float(r["valor_cuota"])
            for _, r in sbs.dropna(subset=["fecha", "valor_cuota"]).iterrows()
        }
    for _, r in ledger.sort_values("fecha").iterrows():
        fecha = pd.Timestamp(r["fecha"]).date().isoformat()
        cv = pd.to_numeric(pd.Series([r.get("challenger_vc")]), errors="coerce").iloc[0]
        cr = pd.to_numeric(pd.Series([r.get("challenger_return")]), errors="coerce").iloc[0]
        ov = pd.to_numeric(pd.Series([r.get("official_vc")]), errors="coerce").iloc[0]
        orr = pd.to_numeric(pd.Series([r.get("official_return")]), errors="coerce").iloc[0]
        av = actual_map.get(fecha)
        rows.append({
            "fecha": fecha,
            "source": "SOMBRA OPERATIVA 60/30",
            "cycle_start": str(r.get("cycle_start", ""))[:10],
            "train_start": str(r.get("train_start", ""))[:10],
            "train_end": str(r.get("train_end", ""))[:10],
            "challenger_vc": None if pd.isna(cv) else float(cv),
            "challenger_return": None if pd.isna(cr) else float(cr),
            "official_vc": None if pd.isna(ov) else float(ov),
            "official_return": None if pd.isna(orr) else float(orr),
            "actual_vc": av,
            "challenger_abs_error": None if av is None or pd.isna(cv) else abs(float(cv) - av),
            "official_abs_error": None if av is None or pd.isna(ov) else abs(float(ov) - av),
        })
    return rows


def main() -> None:
    latest = m.safe_json(m.LATEST_PATH)
    live = m.safe_json(m.LIVE_PATH)
    markets = m.read_csv(m.DATA / "markets.csv")
    sbs_raw = m.read_csv(m.DATA / "sbs_profuturo_f3.csv")
    if not latest or not live or markets.empty or sbs_raw.empty:
        raise RuntimeError("Faltan archivos base para historial 60/30")

    markets["fecha"] = pd.to_datetime(markets["fecha"], errors="coerce")
    signal_date = pd.Timestamp(str(live.get("signal_date") or latest.get("latest_estimate_date"))).normalize()
    start = min(markets["fecha"].dropna().min(), pd.Timestamp("2024-12-01"))
    qqq = m.download_qqq(start, max(signal_date, pd.Timestamp.now().normalize()))
    common, sbs, _ = m.prepare_frames(markets, sbs_raw, qqq)
    state = m.safe_json(m.STATE_PATH)
    ledger = m.ledger_read()

    backtest = build_backtest_history(common)
    operational = build_operational_history(state, ledger, sbs)
    dates = sorted({r["fecha"] for r in backtest + operational})
    output = {
        "model": "OLS 60/30 sin NEM ni FCX + QQQ",
        "rule": "Backtest: coeficientes estimados con 60 observaciones y congelados 30; SBS solo evalua dentro de cada bloque. Operativo: cadena ciega desde el ancla del ciclo.",
        "first_date": dates[0] if dates else None,
        "last_date": dates[-1] if dates else None,
        "backtest_history": backtest,
        "operational_history": operational,
    }
    m.PUBLIC.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    assert backtest
    assert operational
    print(json.dumps({"backtest_rows": len(backtest), "operational_rows": len(operational), "first": output["first_date"], "last": output["last_date"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
