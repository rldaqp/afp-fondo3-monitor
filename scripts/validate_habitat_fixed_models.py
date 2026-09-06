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
MODEL_VERSION = "habitat-rolling90-levels-returns-v4"


def finite(value) -> bool:
    try:
        return value is not None and math.isfinite(float(value))
    except Exception:
        return False


def patch_ui() -> None:
    html = INDEX.read_text(encoding="utf-8")

    # El gráfico de pesos usa categorías; no debe heredar el eje fecha.
    old_weight = "{...baseLayout,barmode:'group',yaxis:{...baseLayout.yaxis,ticksuffix:'%',title:'Aporte absoluto'}},config);"
    new_weight = "{...baseLayout,barmode:'group',xaxis:{type:'category',gridcolor:'#213147',zeroline:false},yaxis:{...baseLayout.yaxis,ticksuffix:'%',title:'Aporte absoluto'}},config);"
    if old_weight in html:
        html = html.replace(old_weight, new_weight, 1)
    assert new_weight in html, "No se pudo fijar el eje categórico del gráfico de pesos"

    # Identidad productiva: únicamente Niveles 90 + Retornos 90.
    old_headers = [
        "Misma lógica matemática que Profuturo · Niveles = OLS absoluto · Retornos = variación aplicada al VC previo · calibración propia con la serie SBS de Hábitat",
        "Misma arquitectura metodológica del visor Profuturo · Niveles y Retornos expresados sobre una base comparable · calibración propia con la serie SBS de Hábitat",
    ]
    final_header = "Dos modelos productivos actualizados · Niveles 90 = OLS absoluto · Retornos 90 = variación aplicada al VC previo · calibración móvil con las 90 observaciones SBS más recientes"
    for text in old_headers:
        html = html.replace(text, final_header)

    html = html.replace(
        "<div><b>Validación fuera de muestra</b> <span class=\"small\">· desde 18/08/2026 · Niveles = OLS absoluto directo, igual que Profuturo; la normalización queda solo como diagnóstico.</span></div>",
        "<div><b>Backtest móvil de 7 ruedas</b> <span class=\"small\">· las 7 últimas fechas SBS quedan fuera del ajuste; ambos modelos se entrenan con las 90 observaciones inmediatamente anteriores.</span></div>",
    )

    html = html.replace("<h2>Modelo de niveles</h2>", "<h2>Modelo de niveles · 90 ruedas</h2>")
    html = html.replace("<h2>Modelo de retornos</h2>", "<h2>Modelo de retornos · 90 ruedas</h2>")
    html = html.replace('<span class="statuspill" id="levelStatus">FIJO</span>', '<span class="statuspill" id="levelStatus">90 RUEDAS</span>')
    html = html.replace('<span class="statuspill" id="returnStatus">FIJO</span>', '<span class="statuspill" id="returnStatus">90 RUEDAS</span>')

    html = html.replace(
        "Estima directamente el valor cuota a partir del nivel actual de los cinco factores, igual que Profuturo.",
        "Estima directamente el valor cuota con los cinco factores usando las 90 observaciones SBS más recientes.",
    )
    html = html.replace(
        "Estima el retorno diario de los cinco factores y lo aplica sobre el VC de la rueda anterior.",
        "Estima el retorno diario con 90 observaciones y lo aplica sobre el VC de la rueda anterior.",
    )

    # Se elimina del visor la tarjeta de normalización: solo quedan dos modelos.
    normalized_card = '    <div class="mini"><span>Niveles normalizado · diagnóstico</span><b id="mLevelRaw">—</b></div>\n'
    html = html.replace(normalized_card, "")
    html = html.replace(
        ".modelmeta{display:grid;grid-template-columns:repeat(5,1fr);gap:6px}",
        ".modelmeta{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:6px}",
    )

    # Evita intentar escribir sobre una tarjeta eliminada.
    assignments = [
        "$('mLevelRaw').textContent=vc(l?.vc_niveles_normalizado ?? LIVE?.models?.niveles?.vc_normalized_intraday);",
        "$('mLevelRaw').textContent=vc(l?.vc_niveles_raw ?? LIVE?.models?.niveles?.vc_raw_intraday);",
    ]
    for assignment in assignments:
        html = html.replace(assignment, "")

    # Textos metodológicos antiguos que todavía mencionaban una tercera referencia.
    html = html.replace(
        "Niveles estima directamente el VC con los niveles actuales de los cinco factores, igual que Profuturo. Retornos estima la variación diaria de esos factores y la aplica sobre el VC previo. La serie normalizada de Niveles se conserva únicamente como diagnóstico para estudiar la brecha, no como reemplazo del modelo principal.",
        "Hábitat mantiene únicamente dos modelos productivos, ambos con ventana móvil de 90 observaciones. Niveles 90 estima directamente el VC absoluto y Retornos 90 estima la variación diaria para aplicarla sobre el VC previo.",
    )
    html = html.replace(
        "Niveles = OLS absoluto directo, igual que Profuturo; la normalización queda solo como diagnóstico.",
        "Niveles 90 y Retornos 90 se recalibran con la información SBS más reciente.",
    )

    INDEX.write_text(html, encoding="utf-8")


def main() -> None:
    if not BASE.exists():
        raise SystemExit(f"Falta {BASE}")
    base = json.loads(BASE.read_text(encoding="utf-8"))
    assert base.get("fund") == "HÁBITAT Fondo 3"
    assert base.get("model_version") == MODEL_VERSION
    assert base.get("window") == 90
    assert base.get("factors") == FACTORS
    assert int(base.get("training", {}).get("n_levels", 0)) == 90
    assert int(base.get("training", {}).get("n_returns", 0)) == 90
    assert base.get("training", {}).get("end") == base.get("latest", {}).get("latest_sbs_date")
    assert finite(base["latest"]["latest_sbs_vc"])
    assert "dos modelos productivos" in base.get("comparison_rule", "").lower()

    backtest = base.get("backtest7", {})
    assert int(backtest.get("n", 0)) == 7
    assert int(backtest.get("window", 0)) == 90
    assert backtest.get("training_end") < backtest.get("holdout_start")

    rows = base.get("rows", [])
    dates = [str(r.get("fecha", ""))[:10] for r in rows]
    assert len(rows) == len(set(dates)), "Fechas duplicadas en base Hábitat"
    assert dates == sorted(dates), "Fechas no ordenadas en base Hábitat"
    useful = [r for r in rows if finite(r.get("vc_niveles")) and finite(r.get("vc_retornos"))]
    assert useful, "No existen observaciones comparables de Niveles 90 y Retornos 90"
    for row in useful[-10:]:
        assert finite(row.get("vc_niveles_raw")), "Falta alias OLS de auditoría"
        assert abs(float(row["vc_niveles_raw"]) - float(row["vc_niveles"])) < 1e-12
        assert finite(row.get("ret_niveles_implicito")), "Falta retorno implícito de Niveles"

    assert list(base.get("models", {})) == ["niveles", "retornos"]
    for key in ("niveles", "retornos"):
        model = base["models"][key]
        coeff = model["coefficients"]
        assert set(coeff) == {"intercept", *FACTORS}
        assert all(finite(v) for v in coeff.values())
        assert int(model.get("window", 0)) == 90
        assert int(model.get("n", 0)) == 90
        assert finite(model["r2"])
        assert finite(model["adj_r2"])
        assert finite(model["stderr"])
        assert model.get("operational_rule")

    validation = base.get("metrics", {}).get("validation", {})
    for key in ("niveles", "retornos"):
        assert int(validation.get(key, {}).get("n", 0)) == 7
        assert finite(validation.get(key, {}).get("mae_pct"))
        assert finite(validation.get(key, {}).get("rmse_pct"))
        assert finite(validation.get(key, {}).get("bias_pct"))
        assert finite(validation.get(key, {}).get("r2_vc_oos"))

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
        assert abs(float(levels["vc_intraday"]) - float(levels["vc_raw_intraday"])) < 1e-12
        assert finite(levels["vc_raw_previous"])
        assert finite(levels["return_intraday"])
        assert finite(returns["vc_intraday"])
        assert finite(returns["return_intraday"])
        assert finite(returns["base_vc"])

    patch_ui()

    # Se conserva el runtime de operaciones independiente de Hábitat.
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
    assert "Dos modelos productivos actualizados" in html
    assert "Modelo de niveles · 90 ruedas" in html
    assert "Modelo de retornos · 90 ruedas" in html
    assert 'id="mLevelRaw"' not in html
    assert "Niveles normalizado · diagnóstico" not in html

    print(
        "Hábitat rolling90 validado:",
        base["training"],
        base["latest"],
        base["metrics"]["validation"],
    )


if __name__ == "__main__":
    main()
