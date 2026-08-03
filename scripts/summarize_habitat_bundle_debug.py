"""Reduce el diagnóstico grande del bundle Hábitat a endpoints y contratos útiles."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "rolling90" / "habitat_bundle_debug.txt"
OUTPUT = ROOT / "data" / "rolling90" / "habitat_endpoint_summary.txt"

TERMS = [
    "serviciosweb",
    "baseURL",
    "axios",
    "fetch(",
    "valorCuota",
    "valorcuota",
    "valor-cuota",
    "unitValue",
    "unit_value",
    "historical",
    "history",
    "rentabilidad",
    "fondo",
    "fund",
    "/api/",
    "api/services",
    "investment",
]

URL_RE = re.compile(r"https?://[^\s\"'<>\\]+", re.I)
PATH_RE = re.compile(
    r"[\"'`]([^\"'`]{0,240}(?:api|service|cuota|valor|fund|fondo|histor|rentab|investment)[^\"'`]{0,240})[\"'`]",
    re.I,
)


def compact(value: str) -> str:
    return " ".join(value.replace("\\/", "/").split())


def main() -> None:
    if not SOURCE.exists() or SOURCE.stat().st_size == 0:
        raise RuntimeError(f"No existe diagnóstico con contenido: {SOURCE}")

    raw = SOURCE.read_text(encoding="utf-8", errors="replace")
    lines: list[str] = [
        f"SOURCE_BYTES={SOURCE.stat().st_size}",
        f"SOURCE_CHARS={len(raw)}",
        "",
        "URLS_RELEVANTES",
    ]

    urls = sorted({compact(match.group(0)) for match in URL_RE.finditer(raw)})
    relevant_urls = [
        url for url in urls
        if any(term.lower().replace("(", "") in url.lower() for term in TERMS)
    ]
    lines.extend(relevant_urls or ["SIN_URLS_RELEVANTES"])

    lines.extend(["", "CADENAS_RELEVANTES"])
    strings: set[str] = set()
    for match in PATH_RE.finditer(raw):
        value = compact(match.group(1))
        if 2 <= len(value) <= 600:
            strings.add(value)
    for value in sorted(strings)[:1000]:
        lines.append(value)
    if not strings:
        lines.append("SIN_CADENAS_RELEVANTES")

    lines.extend(["", "CONTEXTOS"])
    seen: set[str] = set()
    count = 0
    for term in TERMS:
        for match in re.finditer(re.escape(term), raw, re.I):
            start = max(0, match.start() - 900)
            end = min(len(raw), match.end() + 1800)
            context = compact(raw[start:end])
            if context in seen:
                continue
            seen.add(context)
            lines.append(f"\n=== TERM={term} ===")
            lines.append(context[:4000])
            count += 1
            if count >= 300:
                break
        if count >= 300:
            break
    if not seen:
        lines.append("SIN_CONTEXTOS")

    OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Resumen escrito: {OUTPUT} · {OUTPUT.stat().st_size} bytes · {count} contextos")


if __name__ == "__main__":
    main()
