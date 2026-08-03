"""Prueba de lectura de los endpoints públicos usados por el visor de AFP Hábitat."""

from __future__ import annotations

import json
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "rolling90" / "habitat_api_probe.json"

BASES = [
    "https://www.afphabitat.com.pe/privado/admin/investments/home/api",
    "https://www.afphabitat.com.pe/privado/investments/home/api",
    "https://serviciosweb.afphabitat.com.pe/privado/admin/investments/home/api",
    "https://serviciosweb.afphabitat.com.pe/privado/investments/home/api",
]
ENDPOINTS = ["", "fee_values", "fee_inputs", "val_12"]
EXTRA_URLS = [
    "https://www.afphabitat.com.pe/privado/hash",
    "https://serviciosweb.afphabitat.com.pe/privado/hash",
]
HEADERS = {
    "User-Agent": "Mozilla/5.0 AFP-Habitat-Fondo3-Monitor",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.afphabitat.com.pe/privado/admin/investments/home/",
    "Origin": "https://www.afphabitat.com.pe",
}


def inspect(url: str) -> dict[str, object]:
    row: dict[str, object] = {"url": url, "method": "GET"}
    try:
        response = requests.get(url, headers=HEADERS, timeout=45, allow_redirects=True)
        body = response.text
        row.update(
            {
                "status": response.status_code,
                "final_url": response.url,
                "content_type": response.headers.get("content-type"),
                "content_length": len(response.content),
                "allow": response.headers.get("allow"),
                "server": response.headers.get("server"),
                "sample": body[:12000],
            }
        )
        try:
            payload = response.json()
            row["json_type"] = type(payload).__name__
            if isinstance(payload, dict):
                row["json_keys"] = list(payload.keys())[:100]
            elif isinstance(payload, list):
                row["json_length"] = len(payload)
                row["json_first"] = payload[:3]
        except Exception:
            row["json_type"] = None
    except Exception as exc:
        row["error"] = f"{type(exc).__name__}: {exc}"
    return row


def main() -> None:
    urls: list[str] = []
    for base in BASES:
        for endpoint in ENDPOINTS:
            urls.append(base if not endpoint else f"{base}/{endpoint}")
    urls.extend(EXTRA_URLS)

    results = [inspect(url) for url in dict.fromkeys(urls)]
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    for row in results:
        print(
            f"{row['url']} · status={row.get('status')} · "
            f"type={row.get('content_type')} · bytes={row.get('content_length')} · "
            f"error={row.get('error')}"
        )


if __name__ == "__main__":
    main()
