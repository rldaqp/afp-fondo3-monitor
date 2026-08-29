from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

import build_dual_rolling30_monitor as base

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "rolling90"
PUBLIC = ROOT / "public" / "habitat" / "data"
OUT = PUBLIC / "dual_rolling30_monitor.json"
PROF_DUAL = ROOT / "public" / "data" / "dual_rolling30_monitor.json"

TRAIN = 30
QQQ_FEATURES = list(base.QQQ_FEATURES)
NEW_FEATURES = list(base.NEW_FEATURES)


def habitat_sbs_frame() -> pd.DataFrame:
    s = base.read_csv(DATA / "sbs_habitat_f3.csv")
    s["valor_cuota"] = pd.to_numeric(s["valor_cuota"], errors="coerce")
    s = s.dropna(subset=["valor_cuota"]).copy()
    s["prev_vc"] = s["valor_cuota"].shift(1)
    s["prev_date"] = s["fecha"].shift(1)
    s["ret_target"] = s["valor_cuota"].pct_change(fill_method=None)
    return s


def asset_returns(model: dict, features: list[str], mapping: dict[str, str]) -> tuple[dict[str, float], list[dict]]:
    assets = [dict(x) for x in model.get("intraday_assets", [])]
    by = {str(x.get("serie")): x for x in assets}
    vals: dict[str, float] = {}
    for feature in features:
        name = mapping[feature]
        row = by.get(name)
        if row is None and name == "USD/PEN":
            row = by.get("USD_PEN")
        if row is None:
            raise RuntimeError(f"No existe {name} en el snapshot de mercado compartido")
        raw = row.get("retorno_modelo") if row.get("retorno_modelo") is not None else row.get("retorno")
        if not base.finite(raw):
            raise RuntimeError(f"Retorno no disponible para {name}")
        vals[feature] = float(raw)
    return vals, assets


def fair_last30(rows_a: list[dict], rows_b: list[dict]) -> dict:
    a = {str(r["fecha"]): r for r in rows_a}
    b = {str(r["fecha"]): r for r in rows_b}
    dates = sorted(set(a) & set(b))[-30:]

    def metrics(source: dict[str, dict]) -> dict:
        if not dates:
            return {"n": 0}
        est = np.array([float(source[d]["vc_estimated"]) for d in dates])
        act = np.array([float(source[d]["actual_vc"]) for d in dates])
        err = est - act
        corr = float(np.corrcoef(est, act)[0, 1]) if len(dates) >= 2 else None
        return {
            "n": len(dates),
            "date_start": dates[0],
            "date_end": dates[-1],
            "mape_pct": float(np.mean(np.abs(err / act)) * 100.0),
            "mae_vc": float(np.mean(np.abs(err))),
            "rmse_vc": float(np.sqrt(np.mean(err ** 2))),
            "corr_vc": corr,
            "r2_corr": None if corr is None else corr * corr,
        }

    ma = metrics(a)
    mb = metrics(b)
    return {
        "rule": "Comparación homogénea de los últimos 30 pares disponibles en las mismas fechas. Cada predicción es one-step y usa únicamente las 30 observaciones anteriores; sin lookahead.",
        "common_period": {"start": dates[0] if dates else None, "end": dates[-1] if dates else None},
        "qqq_common": ma,
        "new_tickers_common": mb,
        "pairwise": {"n": len(dates)},
    }


def main() -> None:
    if not PROF_DUAL.exists():
        raise RuntimeError("Falta el monitor dual de Profuturo que provee el snapshot común de mercado")
    prof = json.loads(PROF_DUAL.read_text(encoding="utf-8"))
    signal_date = pd.Timestamp(str(prof["signal_date"])).normalize()
    market_mode = prof.get("market_mode")
    market_open = bool(prof.get("market_open"))

    sbs = habitat_sbs_frame()
    latest_sbs = sbs.iloc[-1]
    if not base.finite(latest_sbs["valor_cuota"]):
        raise RuntimeError("El último VC SBS de Hábitat no es numérico")

    # El shadow es independiente por AFP. Las funciones/método son exactamente
    # los mismos del monitor Profuturo; solo cambia el target SBS de Hábitat.
    base.SHADOW = DATA / "habitat_dual_rolling30_shadow.csv"

    markets = base.read_csv(DATA / "markets.csv")
    qdaily = base.load_qqq_daily(markets["fecha"].min(), signal_date)
    qf = markets.merge(qdaily[["fecha", "ret_QQQ"]], on="fecha", how="left")[["fecha", *QQQ_FEATURES]].copy()
    for c in QQQ_FEATURES:
        qf[c] = pd.to_numeric(qf[c], errors="coerce")
    qf = qf.dropna(subset=QQQ_FEATURES).sort_values("fecha").drop_duplicates("fecha", keep="last").reset_index(drop=True)

    qmap = {
        "ret_SPY": "SPY",
        "ret_EEM": "EEM",
        "ret_EPU": "EPU",
        "ret_MCHI": "MCHI",
        "ret_USD_PEN": "USD/PEN",
        "ret_QQQ": "QQQ",
    }
    qlive, qassets = asset_returns(prof["models"]["qqq"], QQQ_FEATURES, qmap)
    qf_live = base.extend_with_live(qf, signal_date, qlive, QQQ_FEATURES)
    qcommon = base.build_common(sbs, qf, QQQ_FEATURES)

    nf = base.load_new_factors()
    nmap = {
        "ret_.INX": ".INX",
        "ret_CPER": "CPER",
        "ret_EEM_alt": "EEM",
        "ret_NDX": "NDX",
        "ret_SPBLSCUP": "SPBLSCUP",
        "ret_USD_PEN_alt": "USD/PEN",
    }
    nlive, nassets = asset_returns(prof["models"]["new_tickers"], NEW_FEATURES, nmap)
    nf_live = base.extend_with_live(nf, signal_date, nlive, NEW_FEATURES)
    ncommon = base.build_common(sbs, nf, NEW_FEATURES)

    if len(qcommon) < TRAIN or len(ncommon) < TRAIN:
        raise RuntimeError(f"Muestra insuficiente Hábitat: A={len(qcommon)} B={len(ncommon)}")

    qhist = base.one_step_history(qcommon, QQQ_FEATURES)
    nhist = base.one_step_history(ncommon, NEW_FEATURES)
    qforward, qmeta = base.forward_chain(qcommon, qf_live, QQQ_FEATURES, sbs, signal_date, "habitat_qqq")
    nforward, nmeta = base.forward_chain(ncommon, nf_live, NEW_FEATURES, sbs, signal_date, "habitat_new_tickers")

    qcur = {**qforward[-1], **qmeta}
    ncur = {**nforward[-1], **nmeta}
    validation = fair_last30(qhist, nhist)
    qa = validation["qqq_common"]
    nb = validation["new_tickers_common"]
    winner = "—"
    if base.finite(qa.get("mape_pct")) and base.finite(nb.get("mape_pct")):
        winner = "NUEVOS TICKERS" if float(nb["mape_pct"]) < float(qa["mape_pct"]) else "QQQ"

    payload = {
        "generated_at_lima": pd.Timestamp.now(tz=base.LIMA).isoformat(),
        "fund": "HÁBITAT Fondo 3",
        "signal_date": signal_date.date().isoformat(),
        "market_mode": market_mode,
        "market_open": market_open,
        "latest_sbs": {
            "fecha": pd.Timestamp(latest_sbs["fecha"]).date().isoformat(),
            "vc": float(latest_sbs["valor_cuota"]),
        },
        "rule": "Dos modelos OLS Rolling 30 con exactamente las mismas canastas y reglas de Profuturo, recalibrados exclusivamente contra los VC SBS de Hábitat Fondo 3. Si SBS está atrasada, se encadenan los días faltantes; al publicarse un VC real, ambos modelos vuelven a anclarse automáticamente a Hábitat.",
        "models": {
            "qqq": {
                "key": "qqq",
                "name": "Rolling 30 · QQQ",
                "short": "QQQ",
                "features_display": ["SPY", "EEM", "EPU", "MCHI", "USD/PEN", "QQQ"],
                "features": QQQ_FEATURES,
                "current": qcur,
                "forward_chain": qforward,
                "history_one_step": qhist,
                "history_metrics": base.history_metrics(qhist),
                "intraday_assets": qassets,
                "source_note": "Mismos factores y snapshot de mercado de Profuturo; coeficientes entrenados solo con Hábitat Fondo 3.",
            },
            "new_tickers": {
                "key": "new_tickers",
                "name": "Rolling 30 · nuevos tickers",
                "short": "Nuevos tickers",
                "features_display": [".INX", "CPER", "EEM", "NDX", "SPBLSCUP", "USD/PEN"],
                "features": NEW_FEATURES,
                "current": ncur,
                "forward_chain": nforward,
                "history_one_step": nhist,
                "history_metrics": base.history_metrics(nhist),
                "intraday_assets": nassets,
                "source_note": "Mismos factores y snapshot de mercado de Profuturo; coeficientes entrenados solo con Hábitat Fondo 3.",
            },
        },
        # Se conserva la clave por compatibilidad con el frontend dual, pero su
        # contenido ahora es una comparación homogénea Hábitat de 30 pares.
        "blind3": validation,
        "comparison": {
            "winner_blind3_mape": winner,
            "vc_difference": float(ncur["vc_estimated"]) - float(qcur["vc_estimated"]),
            "return_difference": float(ncur["return_estimated"]) - float(qcur["return_estimated"]),
        },
    }

    assert payload["models"]["qqq"]["current"]["train_n"] == 30
    assert payload["models"]["new_tickers"]["current"]["train_n"] == 30
    assert len(payload["models"]["qqq"]["features"]) == 6
    assert len(payload["models"]["new_tickers"]["features"]) == 6
    assert base.finite(payload["latest_sbs"]["vc"])

    PUBLIC.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "fund": payload["fund"],
        "latest_sbs": payload["latest_sbs"],
        "signal_date": payload["signal_date"],
        "model_a": qcur,
        "model_b": ncur,
        "validation30": validation,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
