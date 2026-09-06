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

    # El gráfico de pesos usa categorías; no debe heredar el eje fecha.
    old_weight = "{...baseLayout,barmode:'group',yaxis:{...baseLayout.yaxis,ticksuffix:'%',title:'Aporte absoluto'}},config);"
    new_weight = "{...baseLayout,barmode:'group',xaxis:{type:'category',gridcolor:'#213147',zeroline:false},yaxis:{...baseLayout.yaxis,ticksuffix:'%',title:'Aporte absoluto'}},config);"
    if old_weight in html:
        html = html.replace(old_weight, new_weight, 1)
    assert new_weight in html, "No se pudo fijar el eje categórico del gráfico de pesos"

    # El visor debe dejar claro que el modelo principal de Niveles es el OLS
    # absoluto directo, igual que Profuturo. La serie rebasada queda únicamente
    # como diagnóstico y no reemplaza al modelo.
    headers = [
        "Misma arquitectura metodológica del visor Profuturo · Niveles y Retornos expresados sobre una base comparable · calibración propia con la serie SBS de Hábitat",
        "Mismos cinco factores y ecuaciones base del visor Profuturo · Hábitat añade una normalización comparativa de Niveles · calibración propia con la serie SBS de Hábitat",
    ]
    final_header = "Misma lógica matemática que Profuturo · Niveles = OLS absoluto · Retornos = variación aplicada al VC previo · calibración propia con la serie SBS de Hábitat"
    for text in headers:
        html = html.replace(text, final_header)

    html = html.replace("Modelo de niveles · operativo", "Modelo de niveles")
    html = html.replace("Niveles normalizado · comparación", "Modelo de niveles")
    html = html.replace(
        "La ecuación estima un nivel OLS bruto; para seguimiento operativo se usa su variación entre dos ruedas y se aplica sobre el VC anterior.",
        "Estima directamente el valor cuota a partir del nivel actual de los cinco factores, igual que Profuturo.",
    )
    html = html.replace("<span>VC operativo</span>", "<span>VC estimado</span>")
    html = html.replace("Nivel OLS bruto", "Niveles normalizado · diagnóstico")
    html = html.replace("Nivel OLS original · diagnóstico", "Niveles normalizado · diagnóstico")
    html = html.replace("Error estándar bruto", "Error estándar")
    html = html.replace("Ecuación · niveles bruto", "Ecuación de Niveles")
    html = html.replace("Ecuación original de Niveles", "Ecuación de Niveles")
    html = html.replace(
        "Niveles mostrado = versión anclada comparable; el nivel OLS absoluto queda solo como diagnóstico.",
        "Niveles = OLS absoluto directo, igual que Profuturo; la normalización queda solo como diagnóstico.",
    )
    html = html.replace("Niveles anclado · MAE", "Niveles · MAE")
    html = html.replace("Niveles anclado · RMSE", "Niveles · RMSE")
    html = html.replace("Niveles anclado", "Niveles")
    html = html.replace(
        "Una observación por fecha; ambos modelos operativos parten del VC de la rueda anterior.",
        "Una observación por fecha; Niveles es absoluto y Retornos aplica la variación estimada sobre el VC previo.",
    )
    html = html.replace(
        "· ambos se calculan sobre el VC de la rueda anterior.",
        "· compara Niveles absoluto contra Retornos aplicado al VC previo.",
    )

    # Mostrar en la tercera mini-tarjeta la normalización diagnóstica, no repetir
    # el mismo OLS absoluto que ya es el valor principal.
    html = html.replace(
        "$('mLevelRaw').textContent=vc(l?.vc_niveles_raw ?? LIVE?.models?.niveles?.vc_raw_intraday);",
        "$('mLevelRaw').textContent=vc(l?.vc_niveles_normalizado ?? LIVE?.models?.niveles?.vc_normalized_intraday);",
    )

    # Incorporar el diagnóstico normalizado en el punto live cuando todavía no
    # existe una fila histórica para esa misma fecha.
    old_live_fragment = "vc_niveles_raw:finite(LIVE.models.niveles.vc_raw_intraday)?Number(LIVE.models.niveles.vc_raw_intraday):null,ret_niveles_implicito:finite(LIVE.models.niveles.return_intraday)?Number(LIVE.models.niveles.return_intraday):null,"
    new_live_fragment = "vc_niveles_raw:finite(LIVE.models.niveles.vc_raw_intraday)?Number(LIVE.models.niveles.vc_raw_intraday):null,vc_niveles_normalizado:finite(LIVE.models.niveles.vc_normalized_intraday)?Number(LIVE.models.niveles.vc_normalized_intraday):null,ret_niveles_implicito:finite(LIVE.models.niveles.return_intraday)?Number(LIVE.models.niveles.return_intraday):null,"
    if old_live_fragment in html:
        html = html.replace(old_live_fragment, new_live_fragment, 1)

    old_method = "Niveles conserva la regresión absoluta para obtener la variación implícita entre dos ruedas, pero el VC operativo se vuelve a anclar al VC de la rueda anterior. Retornos estima directamente la variación diaria y también se aplica sobre el VC anterior. Por eso la comparación de ambos VC queda en la misma base."
    new_method = "Niveles estima directamente el VC con los niveles actuales de los cinco factores, igual que Profuturo. Retornos estima la variación diaria de esos factores y la aplica sobre el VC previo. La serie normalizada de Niveles se conserva únicamente como diagnóstico para estudiar la brecha, no como reemplazo del modelo principal."
    html = html.replace(old_method, new_method)

    INDEX.write_text(html, encoding="utf-8")


def main() -> None:
    if not BASE.exists():
        raise SystemExit(f"Falta {BASE}")
    base = json.loads(BASE.read_text(encoding="utf-8"))
    assert base.get("fund") == "HÁBITAT Fondo 3"
    assert base.get("model_version") == "habitat-fixed-levels-returns-v3-profuturo-parity"
    assert base.get("factors") == FACTORS
    assert base.get("training", {}).get("start") == "2026-07-07"
    assert base.get("training", {}).get("end") == "2026-08-17"
    assert base.get("validation_start") == "2026-08-18"
    assert int(base["training"]["n_levels"]) > 20
    assert int(base["training"]["n_returns"]) > 20
    assert finite(base["latest"]["latest_sbs_vc"])
    assert "Misma lógica que Profuturo" in base.get("comparison_rule", "")

    rows = base.get("rows", [])
    dates = [str(r.get("fecha", ""))[:10] for r in rows]
    assert len(rows) == len(set(dates)), "Fechas duplicadas en base Hábitat"
    assert dates == sorted(dates), "Fechas no ordenadas en base Hábitat"
    useful = [r for r in rows if finite(r.get("vc_niveles")) and finite(r.get("vc_retornos"))]
    assert useful, "No existen observaciones comparables de Niveles y Retornos"
    for row in useful[-10:]:
        assert finite(row.get("vc_niveles_raw")), "Falta alias OLS de auditoría"
        assert abs(float(row["vc_niveles_raw"]) - float(row["vc_niveles"])) < 1e-12
        assert finite(row.get("ret_niveles_implicito")), "Falta retorno implícito de Niveles"
        assert finite(row.get("vc_niveles_normalizado")), "Falta diagnóstico normalizado de Niveles"

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
    assert finite(validation.get("niveles_normalizado", {}).get("mae_pct"))

    if LIVE.exists():
        live = json.loads(LIVE.read_text(encoding="utf-8"))
        assert live.get("fund") == "HÁBITAT Fondo 3"
        assert "Misma lógica que Profuturo" in live.get("comparison_rule", "")
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
        if levels.get("vc_normalized_intraday") is not None:
            assert finite(levels["vc_normalized_intraday"])
        assert finite(returns["vc_intraday"])
        assert finite(returns["return_intraday"])
        assert finite(returns["base_vc"])

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
    assert "Misma lógica matemática que Profuturo" in html
    assert "Niveles normalizado · diagnóstico" in html
    assert "Niveles anclado" not in html

    print(
        "Hábitat con paridad matemática Profuturo validado:",
        base["latest"],
        base["metrics"]["validation"],
    )


if __name__ == "__main__":
    main()
