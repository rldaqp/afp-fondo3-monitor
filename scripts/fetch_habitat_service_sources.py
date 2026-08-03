"""Descarga el source map público y extrae los archivos fuente del servicio Hábitat."""

from __future__ import annotations

import json
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "rolling90" / "habitat_service_sources.txt"
MAP_URL = "https://www.afphabitat.com.pe/privado/admin/investments/home/static/js/main.eb72ebba.js.map"
HEADERS = {
    "User-Agent": "Mozilla/5.0 AFP-Habitat-Fondo3-Monitor",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.afphabitat.com.pe/privado/admin/investments/home/",
}

NAME_KEYS = (
    "general-service",
    "profitability",
    "sectionprofitability",
    "app.js",
    "app.jsx",
)
CONTENT_KEYS = (
    "fee_values",
    "fee_inputs",
    "val_12",
    "getHash",
    "feeInputResponse",
    "fetchData",
)


def main() -> None:
    response = requests.get(MAP_URL, headers=HEADERS, timeout=120)
    response.raise_for_status()
    payload = response.json()
    sources = payload.get("sources", [])
    contents = payload.get("sourcesContent", [])
    if not sources or not contents:
        raise RuntimeError("El source map no contiene sources/sourcesContent.")

    selected: list[tuple[str, str]] = []
    for index, name in enumerate(sources):
        content = contents[index] if index < len(contents) else None
        if not content:
            continue
        low_name = str(name).lower()
        low_content = str(content).lower()
        if any(key in low_name for key in NAME_KEYS) or any(
            key.lower() in low_content for key in CONTENT_KEYS
        ):
            selected.append((str(name), str(content)))

    if not selected:
        raise RuntimeError("No se encontraron archivos fuente del servicio Hábitat.")

    lines = [
        f"MAP_URL={MAP_URL}",
        f"SOURCE_COUNT={len(sources)}",
        f"SELECTED_COUNT={len(selected)}",
    ]
    for name, content in selected:
        lines.extend(
            [
                "",
                f"===== SOURCE={name} =====",
                content,
                f"===== END_SOURCE={name} =====",
            ]
        )

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Fuentes extraídas: {len(selected)} · {OUTPUT.stat().st_size} bytes")
    for name, _ in selected:
        print(name)


if __name__ == "__main__":
    main()
