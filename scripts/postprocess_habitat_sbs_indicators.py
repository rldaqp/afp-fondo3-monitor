"""Genera Hábitat con histórico completo y paridad metodológica de Profuturo.

La regeneración conserva una línea OLS continua en todo el periodo, incluso en
fechas cuyo VC oficial SBS todavía está pendiente de publicación.
"""

import json
from pathlib import Path

from build_habitat_exact_parity import main

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public" / "habitat"
PUBLIC_DATA = PUBLIC / "data"


def ensure_latest_consistency() -> None:
    signals_path = PUBLIC_DATA / "signals.json"
    latest_path = PUBLIC_DATA / "latest.json"
    live_path = PUBLIC_DATA / "live_market.json"
    index_path = PUBLIC / "index.html"
    signals = json.loads(signals_path.read_text(encoding="utf-8"))
    latest = json.loads(latest_path.read_text(encoding="utf-8"))
    live = json.loads(live_path.read_text(encoding="utf-8"))
    if not signals:
        raise RuntimeError("Hábitat no generó señales históricas ni pendientes.")

    current = signals[-1]
    latest["latest_estimate_date"] = current["fecha"]
    latest["latest_estimated_vc"] = float(current["vc_estimado"])
    latest["latest_return_estimated"] = float(current["ret_estimado"])
    latest["signal"] = current["senal"]
    live["signal_date"] = current["fecha"]
    live["vc_estimated"] = float(current["vc_estimado"])
    live["return_estimated"] = float(current["ret_estimado"])
    live["signal"] = current["senal"]
    latest_path.write_text(
        json.dumps(latest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    live_path.write_text(
        json.dumps(live, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    html = index_path.read_text(encoding="utf-8")
    phrase = "modelo de Hábitat se entrena por separado"
    if phrase not in html:
        note = (
            '<div class="note" style="margin:12px 0">'
            'El modelo de Hábitat se entrena por separado y no reutiliza coeficientes '
            'de Profuturo. Usa la misma metodología de Profuturo: OLS, siete factores, '
            'ventana móvil de 90 observaciones y las mismas reglas de fuentes.'
            '</div>'
        )
        html = html.replace("</main>", note + "</main>", 1)
        index_path.write_text(html, encoding="utf-8")


if __name__ == "__main__":
    main()
    ensure_latest_consistency()
