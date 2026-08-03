"""Recupera snapshots públicos de Variables SPP para completar julio de 2026."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "rolling90" / "sbs_wayback_july_probe.json"
TARGET = "https://www.sbs.gob.pe/app/spp/variablesSPP_net/PagSS/variables_spp.aspx"
CDX = (
    "https://web.archive.org/cdx/search/cdx?"
    f"url={quote(TARGET, safe='')}&from=20260701&to=20260731&output=json&"
    "filter=statuscode:200&fl=timestamp,original,statuscode,digest&collapse=digest"
)
HEADERS = {"User-Agent": "Mozilla/5.0 AFP-Fondo3-Monitor"}
DATE_RE = re.compile(r"Información\s+al\s+(\d{2}/\d{2}/\d{4})", re.I)


def norm(value: str) -> str:
    return " ".join(value.replace("\xa0", " ").split())


def parse_num(value: str) -> float | None:
    try:
        return float(value.replace(",", "").strip())
    except Exception:
        return None


def extract_habitat(html: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "lxml")
    rows: list[dict[str, Any]] = []
    for tr in soup.find_all("tr"):
        cells = tr.find_all(["th", "td"], recursive=False)
        texts = [norm(cell.get_text(" ", strip=True)) for cell in cells]
        if not texts or texts[0].upper() != "HABITAT" or len(texts) < 10:
            continue
        date = None
        for previous in tr.find_all_previous(string=True, limit=600):
            match = DATE_RE.search(norm(str(previous)))
            if match:
                date = match.group(1)
                break
        if not date:
            continue
        quotas = parse_num(texts[7])
        fund_value = parse_num(texts[8])
        vc = parse_num(texts[9])
        if quotas and fund_value and vc:
            rows.append(
                {
                    "fecha": date,
                    "cuotas_fondo": quotas,
                    "valor_fondo": fund_value,
                    "valor_cuota": vc,
                }
            )
    by_date = {row["fecha"]: row for row in rows}
    return [by_date[key] for key in sorted(by_date)]


def main() -> None:
    session = requests.Session()
    session.headers.update(HEADERS)
    result: dict[str, Any] = {"cdx_url": CDX, "captures": [], "records": []}

    cdx_response = session.get(CDX, timeout=90)
    result["cdx_status"] = cdx_response.status_code
    result["cdx_sample"] = cdx_response.text[:10000]
    cdx_response.raise_for_status()
    payload = cdx_response.json()
    captures = payload[1:] if isinstance(payload, list) and payload else []

    all_rows: dict[str, dict[str, Any]] = {}
    for capture in captures:
        timestamp = str(capture[0])
        original = str(capture[1])
        replay = f"https://web.archive.org/web/{timestamp}id_/{original}"
        item: dict[str, Any] = {"timestamp": timestamp, "original": original, "replay": replay}
        try:
            response = session.get(replay, timeout=90)
            item["status"] = response.status_code
            item["content_type"] = response.headers.get("content-type")
            item["content_length"] = len(response.content)
            rows = extract_habitat(response.text) if response.ok else []
            item["dates"] = [row["fecha"] for row in rows]
            item["records"] = rows
            for row in rows:
                all_rows[row["fecha"]] = {**row, "snapshot": timestamp, "replay": replay}
        except Exception as exc:
            item["error"] = f"{type(exc).__name__}: {exc}"
        result["captures"].append(item)

    result["records"] = [all_rows[key] for key in sorted(all_rows)]
    result["july_early"] = [
        row for row in result["records"]
        if row["fecha"] in {
            "01/07/2026", "02/07/2026", "03/07/2026", "06/07/2026",
            "07/07/2026", "08/07/2026", "09/07/2026", "10/07/2026",
            "13/07/2026", "14/07/2026", "15/07/2026", "16/07/2026",
            "17/07/2026", "20/07/2026",
        }
    ]
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Capturas CDX: {len(captures)}")
    print(f"Registros únicos: {len(result['records'])}")
    print(f"Fechas julio faltantes recuperadas: {len(result['july_early'])}")
    for row in result["july_early"]:
        print(f"{row['fecha']} · VC {row['valor_cuota']:.7f}")


if __name__ == "__main__":
    main()
