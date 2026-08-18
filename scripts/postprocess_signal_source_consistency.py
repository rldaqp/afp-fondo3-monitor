from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML_PATH = ROOT / "public" / "index.html"


def main() -> None:
    html = HTML_PATH.read_text(encoding="utf-8")

    # Un cierre guardado en live_market no debe reemplazar al latest.json cuando
    # ambos corresponden a la misma fecha. latest.json es la salida canónica del
    # OLS de cierre; live_market solo prevalece si es intradía vigente o si trae
    # una fecha posterior todavía no incorporada por el cierre canónico.
    old = "if(mode.startsWith('CIERRE')){const latest=String((latestData&&latestData.latest_estimate_date)||'').slice(0,10);return !latest||d>=latest}"
    new = "if(mode.startsWith('CIERRE')){const latest=String((latestData&&latestData.latest_estimate_date)||'').slice(0,10);return !latest||d>latest}"
    if old in html:
        html = html.replace(old, new, 1)
    elif new not in html:
        raise RuntimeError("No se encontró la regla de prioridad CIERRE/live para corregir")

    # Aclara que el +1% no es el retorno diario: mide la distancia acumulada
    # entre el último VC oficial SBS y el VC estimado más reciente disponible.
    html = html.replace(
        "Capa táctica sobre el VC estimado; no cambia la señal oficial SUBE / BAJA / NEUTRO.",
        "Margen acumulado desde el último VC oficial SBS hasta el VC estimado más reciente; no es el retorno diario y no cambia la señal oficial SUBE / BAJA / NEUTRO.",
        1,
    )
    html = html.replace(
        "<b>Regla:</b> +1.00% o más = ENTRAR · entre −1.00% y +1.00% = ESPERAR · −1.00% o menos = SALIR / NO ENTRAR. Es una regla del visor basada en el modelo, no una garantía de rentabilidad.",
        "<b>Regla:</b> el margen se calcula contra el último VC SBS publicado y puede abarcar varios días pendientes. +1.00% o más = ENTRAR · entre −1.00% y +1.00% = ESPERAR · −1.00% o menos = SALIR / NO ENTRAR. Es una regla del visor basada en el modelo, no una garantía de rentabilidad.",
        1,
    )

    HTML_PATH.write_text(html, encoding="utf-8")
    print("Profuturo: cierre canónico y señal táctica alineados; se aclara retorno diario vs margen acumulado.")


if __name__ == "__main__":
    main()
