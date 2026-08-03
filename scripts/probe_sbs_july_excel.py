"""Identifica el patrón real de archivos SBS de julio y prueba el Excel 2026."""

from __future__ import annotations

import io
import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

import pandas as pd
import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "rolling90" / "sbs_july_excel_probe.json"
INDEX = (
    "https://www.sbs.gob.pe/app/stats_net/stats/"
    "EstadisticaSistemaFinancieroResultados.aspx?c=FP-1359"
)
HEADERS = {"User-Agent": "Mozilla/5.0 AFP-Fondo3-Monitor"}


def inspect_excel(content: bytes) -> dict[str, object]:
    out: dict[str, object] = {}
    try:
        book = pd.ExcelFile(io.BytesIO(content), engine="xlrd")
        out["sheet_names"] = book.sheet_names
        if "VC-Diario-Fondo3" in book.sheet_names:
            raw = pd.read_excel(
                io.BytesIO(content),
                sheet_name="VC-Diario-Fondo3",
                header=None,
                engine="xlrd",
            )
            values = raw.astype(str)
            date_candidates: list[str] = []
            for cell in values.to_numpy().ravel():
                if re.search(r"2026", str(cell)):
                    date_candidates.append(str(cell))
            out["date_samples"] = date_candidates[:40]
            out["rows"] = len(raw)
            out["columns"] = len(raw.columns)
    except Exception as exc:
        out["parse_error"] = f"{type(exc).__name__}: {exc}"
    return out


def candidate_from_old(url: str) -> str | None:
    parsed = urlparse(url)
    path = parsed.path
    year_match = re.search(r"/(20\d{2})/", path)
    if not year_match:
        return None
    old_year = year_match.group(1)
    path = path.replace(f"/{old_year}/", "/2026/", 1)
    path = re.sub(old_year + r"(?=\.[Xx][Ll][Ss]$)", "2026", path)
    return parsed._replace(path=path, query="", fragment="").geturl()


def main() -> None:
    session = requests.Session()
    session.headers.update(HEADERS)
    result: dict[str, object] = {"index": INDEX, "historical_july_links": [], "attempts": []}

    response = session.get(INDEX, timeout=60)
    response.raise_for_status()
    soup = BeautifulSoup(response.content, "lxml")
    links: list[str] = []
    all_fp_links: list[str] = []
    for anchor in soup.find_all("a", href=True):
        url = urljoin(INDEX, anchor["href"])
        if "FP-1359" not in url.upper() or not url.lower().endswith(".xls"):
            continue
        all_fp_links.append(url)
        if "/julio/" in url.lower() or re.search(r"-(?:jl|ju|jul|07)20\d{2}\.xls$", url, re.I):
            links.append(url)

    result["historical_july_links"] = sorted(set(links))
    result["all_link_samples"] = sorted(set(all_fp_links))[-80:]

    candidates: set[str] = {
        "https://intranet2.sbs.gob.pe/estadistica/financiera/2026/Julio/FP-1359-jl2026.XLS",
        "https://intranet2.sbs.gob.pe/estadistica/financiera/2026/Julio/FP-1359-ju2026.XLS",
        "https://intranet2.sbs.gob.pe/estadistica/financiera/2026/Julio/FP-1359-jul2026.XLS",
        "https://intranet2.sbs.gob.pe/estadistica/financiera/2026/Julio/FP-1359-072026.XLS",
    }
    for link in links:
        candidate = candidate_from_old(link)
        if candidate:
            candidates.add(candidate)

    for url in sorted(candidates):
        item: dict[str, object] = {"url": url}
        try:
            file_response = session.get(url, timeout=60, allow_redirects=True)
            item.update(
                {
                    "status": file_response.status_code,
                    "final_url": file_response.url,
                    "content_type": file_response.headers.get("content-type"),
                    "content_length": len(file_response.content),
                    "first_bytes_hex": file_response.content[:16].hex(),
                }
            )
            if file_response.ok and len(file_response.content) > 1000:
                item.update(inspect_excel(file_response.content))
        except Exception as exc:
            item["error"] = f"{type(exc).__name__}: {exc}"
        result["attempts"].append(item)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Enlaces julio históricos: {len(links)}")
    for link in sorted(set(links)):
        print(link)
    print("Intentos 2026:")
    for item in result["attempts"]:
        print(
            f"{item['url']} · status={item.get('status')} · "
            f"bytes={item.get('content_length')} · sheets={item.get('sheet_names')}"
        )


if __name__ == "__main__":
    main()
