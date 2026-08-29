from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROF_HTML = ROOT / "public" / "index.html"
PROF_RUNTIME = ROOT / "public" / "data" / "dual_trade_runtime_v1.js"
HAB = ROOT / "public" / "habitat"
HAB_DATA = HAB / "data"
HAB_HTML = HAB / "index.html"
HAB_RUNTIME = HAB_DATA / "dual_trade_runtime_v1.js"

HABITAT_APPS_SCRIPT = "https://script.google.com/macros/s/AKfycbxoYHkCu0cZPx_KsMlI0Jd5PEATgxBjZTR8oK8qs1cUjRHJbiK0t-bxkH5ACprgp81S7g/exec"


def build_html() -> str:
    html = PROF_HTML.read_text(encoding="utf-8")
    # La UI se clona deliberadamente del visor Profuturo para garantizar la
    # misma arquitectura visual A/B. Los datos son relativos a /habitat/data.
    html = html.replace("Profuturo Fondo 3", "Hábitat Fondo 3")
    html = html.replace("PROFUTURO Fondo 3", "HÁBITAT Fondo 3")
    html = html.replace("Profuturo", "Hábitat")
    html = html.replace("PROFUTURO", "HABITAT")
    # Solo cambia el texto visible; se conserva la clave/IDs blind3 porque el
    # frontend dual ya los usa y el JSON Hábitat los rellena con 30 pares.
    html = html.replace("Validación blind3:", "Validación homogénea últimos 30 pares:")
    html = html.replace("validación blind3", "validación homogénea de 30 pares")
    html = html.replace("Validación blind3", "Validación homogénea de 30 pares")
    if "data/dual_rolling30_monitor.json" not in html:
        raise RuntimeError("La plantilla Profuturo ya no contiene el monitor dual esperado")
    if "Modelo A · Rolling 30 + QQQ" not in html or "Modelo B · Rolling 30 + nuevos tickers" not in html:
        raise RuntimeError("La plantilla Profuturo no contiene los dos modelos A/B")
    return html


def build_runtime() -> str:
    js = PROF_RUNTIME.read_text(encoding="utf-8")
    js = js.replace("PROFUTURO", "HABITAT")
    js = js.replace("Profuturo", "Hábitat")
    js = js.replace("profuturo", "habitat")
    js = re.sub(r"const LEGACY_KEYS=\[[^;]*\];", "const LEGACY_KEYS=[];", js, count=1)
    js = re.sub(r"const DEFAULT_URL='[^']*';", f"const DEFAULT_URL='{HABITAT_APPS_SCRIPT}';", js, count=1)
    if "const FUND='HABITAT';" not in js:
        raise RuntimeError("No se pudo enrutar el runtime de operaciones a HABITAT")
    if "habitat_fondo3_trade_history_v3" not in js:
        raise RuntimeError("No se creó la llave local separada de Hábitat")
    if HABITAT_APPS_SCRIPT not in js:
        raise RuntimeError("No quedó configurado el Apps Script de Hábitat")
    return js


def main() -> None:
    HAB_DATA.mkdir(parents=True, exist_ok=True)
    html = build_html()
    runtime = build_runtime()
    HAB_HTML.write_text(html, encoding="utf-8")
    HAB_RUNTIME.write_text(runtime, encoding="utf-8")

    final = HAB_HTML.read_text(encoding="utf-8")
    assert "Hábitat Fondo 3" in final
    assert "Modelo A · Rolling 30 + QQQ" in final
    assert "Modelo B · Rolling 30 + nuevos tickers" in final
    assert "SPY · EEM · EPU · MCHI · USD/PEN · QQQ" in final
    assert ".INX · CPER · EEM · NDX · SPBLSCUP · USD/PEN" in final
    assert "data/dual_rolling30_monitor.json" in final
    assert "dSbs" in final
    assert "Pesos de los factores" in final or "FACTOR_WEIGHT" in final
    print("Hábitat convertido a la misma UI dual Rolling30 A/B de Profuturo.")


if __name__ == "__main__":
    main()
