from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_dual_rolling30_monitor as m


def current_new_assets(live: dict) -> list[dict]:
    wanted = [".INX", "CPER", "EEM", "NDX", "SPBLSCUP", "USD/PEN"]
    by = {str(x.get("serie")): dict(x) for x in live.get("experimental_assets", [])}
    rows = []
    for name in wanted:
        row = by.get(name, {"serie": name})
        raw = row.get("retorno_modelo") if row.get("retorno_modelo") is not None else row.get("retorno")
        if not m.finite(raw):
            row["usado_modelo"] = False
            row["estado"] = str(row.get("estado") or "DATO PENDIENTE") + " · NO SE INVENTA 0%"
        rows.append(row)
    return rows


def build_fallback(reason: Exception) -> None:
    live = json.loads(m.LIVE.read_text(encoding="utf-8"))
    signal_date = pd.Timestamp(str(live.get("signal_date"))).normalize()
    sbs = m.sbs_frame()
    latest_sbs = sbs.iloc[-1]
    markets = m.read_csv(m.DATA / "markets.csv")

    # Modelo A: se actualiza normalmente aunque falle una fuente exclusiva del Modelo B.
    qdaily = m.load_qqq_daily(markets["fecha"].min(), signal_date)
    qqq_now = m.qqq_snapshot(signal_date, qdaily, bool(live.get("market_open")))
    qf = markets.merge(qdaily[["fecha", "ret_QQQ"]], on="fecha", how="left")[["fecha", *m.QQQ_FEATURES]].copy()
    for c in m.QQQ_FEATURES:
        qf[c] = pd.to_numeric(qf[c], errors="coerce")
    qf = qf.dropna(subset=m.QQQ_FEATURES).sort_values("fecha").drop_duplicates("fecha", keep="last").reset_index(drop=True)

    lby = {str(x.get("serie")): x for x in live.get("assets", [])}
    qlive = {}
    for f, name in {
        "ret_SPY": "SPY",
        "ret_EEM": "EEM",
        "ret_EPU": "EPU",
        "ret_MCHI": "MCHI",
        "ret_USD_PEN": "USD_PEN",
    }.items():
        row = lby.get(name, {})
        raw = row.get("retorno_modelo") if row.get("retorno_modelo") is not None else row.get("retorno")
        if not m.finite(raw):
            raise RuntimeError(f"Fallback: falta {name} para Rolling30 QQQ")
        qlive[f] = float(raw)
    qlive["ret_QQQ"] = float(qqq_now["retorno"])
    qf_live = m.extend_with_live(qf, signal_date, qlive, m.QQQ_FEATURES)
    qcommon = m.build_common(sbs, qf, m.QQQ_FEATURES)
    qhist = m.one_step_history(qcommon, m.QQQ_FEATURES)
    qforward, qmeta = m.forward_chain(qcommon, qf_live, m.QQQ_FEATURES, sbs, signal_date)
    qcur = {**qforward[-1], **qmeta}
    qcur["data_status"] = "ACTUALIZADO"

    # Modelo B: usa únicamente sesiones completas de los seis factores.
    # Si SPBLSCUP aún no está disponible hoy, NO se sustituye por 0 ni por otro índice.
    nf = m.load_new_factors()
    ncommon = m.build_common(sbs, nf, m.NEW_FEATURES)
    nhist = m.one_step_history(ncommon, m.NEW_FEATURES)
    nforward, nmeta = m.forward_chain(ncommon, nf, m.NEW_FEATURES, sbs, signal_date)
    if nforward:
        ncur = {**nforward[-1], **nmeta}
    else:
        # Solo debería ocurrir cuando el ancla SBS coincide con la última sesión completa.
        last_hist = nhist[-1] if nhist else None
        if last_hist is None:
            raise RuntimeError("Fallback: Modelo B no tiene una observación completa utilizable")
        ncur = {
            **last_hist,
            **nmeta,
            "fecha": last_hist["fecha"],
            "vc_estimated": float(last_hist["vc_estimated"]),
            "return_estimated": float(last_hist["return_estimated"]),
            "signal": str(last_hist["signal"]),
        }
    ncur["data_status"] = "ÚLTIMA SESIÓN COMPLETA · INTRADÍA ACTUAL PENDIENTE"
    ncur["pending_reason"] = str(reason)
    ncur["current_market_date"] = signal_date.date().isoformat()

    blind = m.load_blind3()
    qm = blind.get("qqq_common", {})
    nm = blind.get("new_tickers_common", {})
    winner = "—"
    if m.finite(qm.get("mape_pct")) and m.finite(nm.get("mape_pct")):
        winner = "NUEVOS TICKERS" if float(nm["mape_pct"]) < float(qm["mape_pct"]) else "QQQ"

    nassets = current_new_assets(live)
    payload = {
        "generated_at_lima": pd.Timestamp.now(tz=m.LIMA).isoformat(),
        "fund": "PROFUTURO Fondo 3",
        "signal_date": signal_date.date().isoformat(),
        "market_mode": live.get("mode"),
        "market_open": bool(live.get("market_open")),
        "latest_sbs": {
            "fecha": pd.Timestamp(latest_sbs["fecha"]).date().isoformat(),
            "vc": float(latest_sbs["valor_cuota"]),
        },
        "rule": "Solo quedan dos modelos visibles. Ambos son OLS rolling 30. Si SBS está atrasada se encadenan los días faltantes sin usar VC ocultos. Si un factor intradía exclusivo del Modelo B no está disponible, se conserva su última sesión completa y se marca pendiente; nunca se inventa un retorno 0%.",
        "degraded_mode": True,
        "degraded_reason": str(reason),
        "models": {
            "qqq": {
                "key": "qqq",
                "name": "Rolling 30 · QQQ",
                "short": "QQQ",
                "features_display": ["SPY", "EEM", "EPU", "MCHI", "USD/PEN", "QQQ"],
                "features": m.QQQ_FEATURES,
                "current": qcur,
                "forward_chain": qforward,
                "history_one_step": qhist,
                "history_metrics": m.history_metrics(qhist),
                "intraday_assets": m.qqq_intraday_assets(live, qqq_now),
                "history_operational": [],
                "operational_metrics": {"n": 0, "status": "Se completa con el ledger inmutable al cierre"},
                "source_note": "Modelo A actualizado normalmente. SPY/EEM/EPU/MCHI/QQQ: Yahoo; USD/PEN: fuente operativa del monitor.",
            },
            "new_tickers": {
                "key": "new_tickers",
                "name": "Rolling 30 · nuevos tickers",
                "short": "Nuevos tickers",
                "features_display": [".INX", "CPER", "EEM", "NDX", "SPBLSCUP", "USD/PEN"],
                "features": m.NEW_FEATURES,
                "current": ncur,
                "forward_chain": nforward,
                "history_one_step": nhist,
                "history_metrics": m.history_metrics(nhist),
                "intraday_assets": nassets,
                "history_operational": [],
                "operational_metrics": {"n": 0, "status": "Sesión actual pendiente de los seis factores completos"},
                "source_note": "No se fabrica SPBLSCUP ni se usa 0%. Mientras falte el factor actual, se muestra la última predicción construida con una sesión completa.",
            },
        },
        "blind3": blind,
        "comparison": {
            "winner_blind3_mape": winner,
            "vc_difference": float(ncur["vc_estimated"]) - float(qcur["vc_estimated"]),
            "return_difference": float(ncur["return_estimated"]) - float(qcur["return_estimated"]),
            "same_market_date": str(ncur.get("fecha"))[:10] == signal_date.date().isoformat(),
        },
    }
    m.OUT.parent.mkdir(parents=True, exist_ok=True)
    m.OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "fallback": True,
        "reason": str(reason),
        "signal_date": payload["signal_date"],
        "qqq_date": qcur.get("fecha"),
        "qqq_vc": qcur.get("vc_estimated"),
        "new_date": ncur.get("fecha"),
        "new_vc": ncur.get("vc_estimated"),
    }, ensure_ascii=False, indent=2))


def main() -> None:
    try:
        m.main()
    except Exception as exc:
        print(f"Constructor dual normal no disponible: {type(exc).__name__}: {exc}")
        build_fallback(exc)


if __name__ == "__main__":
    main()
