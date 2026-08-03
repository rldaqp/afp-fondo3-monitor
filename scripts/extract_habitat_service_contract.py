"""Extrae del source map el contrato exacto del servicio público de AFP Hábitat."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "rolling90" / "habitat_bundle_debug.txt"
OUTPUT = ROOT / "data" / "rolling90" / "habitat_service_contract.txt"

SOURCE_MARKER = re.compile(r"^SOURCE=(.+)$", re.MULTILINE)
TERMS = [
    "/fee_values",
    "/fee_inputs",
    "/val_12",
    "getHash",
    "sendGet",
    "axios.get",
    "axios.post",
    "fetchData",
    "feeInputResponse",
    "fund_id",
    "period_id",
    "apiUrl",
    "urlBaseAzure",
    "GeneralService",
]


def compact(value: str) -> str:
    return " ".join(value.replace("\\/", "/").split())


def source_blocks(raw: str) -> list[tuple[str, str]]:
    markers = list(SOURCE_MARKER.finditer(raw))
    blocks: list[tuple[str, str]] = []
    for index, marker in enumerate(markers):
        start = marker.start()
        end = markers[index + 1].start() if index + 1 < len(markers) else len(raw)
        blocks.append((marker.group(1).strip(), raw[start:end]))
    return blocks


def main() -> None:
    if not SOURCE.exists() or SOURCE.stat().st_size == 0:
        raise RuntimeError(f"No existe diagnóstico: {SOURCE}")
    raw = SOURCE.read_text(encoding="utf-8", errors="replace")

    lines: list[str] = [
        f"SOURCE_BYTES={SOURCE.stat().st_size}",
        "",
        "BLOQUES_DE_CODIGO_RELEVANTES",
    ]

    selected = 0
    for name, block in source_blocks(raw):
        low_name = name.lower()
        low_block = block.lower()
        is_relevant_name = any(
            key in low_name
            for key in (
                "general-service",
                "profitability",
                "app.js",
                "app.jsx",
                "funds",
                "investment",
                "service",
            )
        )
        contains_endpoint = any(term.lower() in low_block for term in TERMS)
        if not (is_relevant_name or contains_endpoint):
            continue
        lines.append(f"\n===== SOURCE={name} =====")
        lines.append(block[:120000])
        selected += 1
        if selected >= 30:
            break

    lines.extend(["", "CONTEXTOS_GLOBALES"])
    seen: set[str] = set()
    for term in TERMS:
        hits = 0
        for match in re.finditer(re.escape(term), raw, re.I):
            context = compact(raw[max(0, match.start() - 1800): min(len(raw), match.end() + 4200)])
            if context in seen:
                continue
            seen.add(context)
            lines.append(f"\n===== TERM={term} =====")
            lines.append(context[:8000])
            hits += 1
            if hits >= 12:
                break

    OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(
        f"Contrato extraído: {OUTPUT} · {OUTPUT.stat().st_size} bytes · "
        f"{selected} bloques · {len(seen)} contextos"
    )


if __name__ == "__main__":
    main()
