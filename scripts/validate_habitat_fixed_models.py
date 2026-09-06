from __future__ import annotations

import json
import math
from pathlib import Path

from install_habitat_fixed_trade_runtime import main as install_trade_runtime

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "public" / "habitat" / "data" / "fixed_models_2026.json"
LIVE = ROOT / "public" / "habitat" / "data" / "fixed_models_intraday.json"
TRADE = ROOT / "public" / "habitat" / "data" / "fixed_trade_runtime_v1.js"
INDEX = ROOT / "public" / "habitat" / "index.html"
FACTORS = ["SPY", "EEM", "MCHI", "QQQ", "SPBLSCUP"]


def finite(value) -> bool:
    try:
        return value is not None and math.isfinite(float(value))
    except Exception:
        return False


def patch_ui() -> None:
    html = INDEX.read_text(encoding="utf-8")

    # El gráfico de pesos usa tickers (categorías), no fechas. El layout base
    # heredaba xaxis.type='date' de los gráficos temporales y Plotly no podía
    # ubicar SPY/EEM/MCHI/QQQ/SPBLSCUP como barras visibles.
    old_weight = "{...baseLayout,barmode:'group',yaxis:{...baseLayout.yaxis,ticksuffix:'%',title:'Aporte absoluto'}},config);"
    new_weight = "{...baseLayout,barmode:'group',xaxis:{type:'category',gridcolor:'#213147',zeroline:false},yaxis:{...baseLayout.yaxis,ticksuffix:'%',title:'Aporte absoluto'}},config);"
    if old_weight in html:
        html = html.replace(old_weight, new_weight, 1)
    assert new_weight in html, "No se pudo fijar el eje categórico del gráfico de pesos"

    # Transparencia metodológica: el rebase/anclaje de Niveles fue añadido en
    # Hábitat para comparar señales; Profuturo muestra directamente su OLS de
    # niveles. No debe presentarse como si ambos tratamientos fueran idénticos.
    html = html.replace(
        "Misma arquitectura metodológica del visor Profuturo · Niveles y Retornos expresados sobre una base comparable · calibración propia con la serie SBS de Hábitat",
        "Mismos cinco factores y ecuaciones base del visor Profuturo · Hábitat añade una normalización comparativa de Niveles · calibración propia con la serie SBS de Hábitat",
    )
    html = html.replace("Modelo de niveles · operativo", "Niveles normalizado · comparación")
    html = html.replace("Nivel OLS bruto", "Nivel OLS original · diagnóstico")
    html = html.replace("Ecuación · niveles bruto", "Ecuación original de Niveles")

    INDEX.write_text(html, encoding="utf-8")


def main() -> None:
    if not BASE.exists():
        raise SystemExit(f"Falta {BASE}")
    base = json.loads(BASE.read_text(encoding="utf-8"))
    assert base.get("fund") == "HÁBITAT Fondo 3"
    assert base.get("model_version") == "habitat-fixed-levels-returns-v2-anchored"
    assert base.get("factors") == FACTORS
    assert base.get("training", {}).get("start") == "2026-07-07"
    assert base.get("training", {}).get("end") == "2026-08-17"
    assert base.get("validation_start") == "2026-08-18"
    assert int(base["training"]["n_levels"]) > 20
    assert int(base["training"]["n_returns"]) > 20
    assert finite(base["latest"]["latest_sbs_vc"])
    assert "Ambos VC operativos parten" in base.get("comparison_rule", "")

    rows = base.get("rows", [])
    dates = [str(r.get("fecha", ""))[:10] for r in rows]
    assert len(rows) == len(set(dates)), "Fechas duplicadas en base Hábitat"
    assert dates == sorted(dates), "Fechas no ordenadas en base Hábitat"
    useful = [r for r in rows if finite(r.get("vc_niveles")) and finite(r.get("vc_retornos"))]
    assert useful, "No existen observaciones comparables de Niveles y Retornos"
    for row in useful[-10:]:
        assert finite(row.get("vc_niveles_raw")), "Falta nivel OLS original de auditoría"
        assert finite(row.get("ret_niveles_implicito")), "Falta retorno implícito de Niveles"

    for key in ("niveles", "retornos"):
        model = base["models"][key]
        coeff = model["coefficients"]
        assert set(coeff) == {"intercept", *FACTORS}
        assert all(finite(v) for v in coeff.values())
        assert finite(model["r2"])
        assert finite(model["adj_r2"])
        assert finite(model["stderr"])
        assert model.get("operational_rule")

    validation = base.get("metrics", {}).get("validation", {})
    assert finite(validation.get("niveles", {}).get("mae_pct"))
    assert finite(validation.get("retornos", {}).get("mae_pct"))
    assert finite(validation.get("niveles_raw", {}).get("mae_pct"))

    if LIVE.exists():
        live = json.loads(LIVE.read_text(encoding="utf-8"))
        assert live.get("fund") == "HÁBITAT Fondo 3"
        signal_date = str(live.get("signal_date", ""))[:10]
        assert len(signal_date) == 10
        tickers = live.get("tickers", [])
        assert [r.get("ticker") for r in tickers] == FACTORS
        assert len({r.get("ticker") for r in tickers}) == 5
        for row in tickers:
            assert finite(row.get("price_previous"))
            assert finite(row.get("price_current"))
            assert finite(row.get("return"))
            if row.get("fresh") is True:
                assert str(row.get("timestamp", ""))[:10] == signal_date, (
                    f"{row.get('ticker')} fresh con fecha distinta a signal_date"
                )
        levels = live["models"]["niveles"]
        returns = live["models"]["retornos"]
        assert finite(levels["vc_intraday"])
        assert finite(levels["vc_raw_intraday"])
        assert finite(levels["vc_raw_previous"])
        assert finite(levels["return_intraday"])
        assert finite(levels["base_vc"])
        assert finite(returns["vc_intraday"])
        assert finite(returns["return_intraday"])
        assert finite(returns["base_vc"])
        if levels.get("base_rule") == "VC SBS real de la sesión anterior":
            assert abs(float(levels["base_vc"]) - float(returns["base_vc"])) < 1e-12

    patch_ui()

    # Copia la misma lógica de operaciones del visor Profuturo y la aísla con
    # identidad, localStorage y endpoint de Drive propios de Hábitat.
    install_trade_runtime()
    assert TRADE.exists() and TRADE.stat().st_size > 1000
    runtime = TRADE.read_text(encoding="utf-8")
    html = INDEX.read_text(encoding="utf-8")
    assert "const FUND='HABITAT';" in runtime
    assert "habitat_fondo3_trade_history_v3" in runtime
    assert "Profuturo" not in runtime and "PROFUTURO" not in runtime
    assert "data/fixed_trade_runtime_v1.js" in html
    assert "mode:'markers'" in html
    assert "Niveles implícito" in html
    assert "Modelo retornos" in html
    assert "Retorno real SBS" in html
    assert "Aguja vertical" in html
    assert "xaxis:{type:'category'" in html
    assert "Niveles normalizado · comparación" in html
    assert "Nivel OLS original · diagnóstico" in html

    print(
        "Hábitat niveles/retornos anclados validado:",
        base["latest"],
        base["metrics"]["validation"],
    )


if __name__ == "__main__":
    main()
