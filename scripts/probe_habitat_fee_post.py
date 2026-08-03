"""Prueba el endpoint vigente de valor cuota de AFP Hábitat."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "rolling90" / "habitat_fee_post_probe.json"
BASE = "https://www.afphabitat.com.pe"
SERVICE_BASE = "https://serviciosweb.afphabitat.com.pe"
APP = f"{BASE}/privado/admin/investments/home/"
FEE_URLS = [
    f"{BASE}/privado/investments/home/api/fee_values",
    f"{BASE}/privado/admin/investments/home/api/fee_values",
    f"{SERVICE_BASE}/privado/investments/home/api/fee_values",
    f"{SERVICE_BASE}/privado/admin/investments/home/api/fee_values",
]
HASH_URLS = [
    f"{BASE}/privado/hash",
    f"{BASE}/privado/investments/home/api/hash",
    f"{BASE}/privado/investments/home/hash",
    f"{SERVICE_BASE}/privado/hash",
    f"{SERVICE_BASE}/privado/investments/home/api/hash",
]
DATES = [
    "2026-07",
    "07-2026",
    "07/2026",
    "2026/07",
    "072026",
    "202607",
    "2026-07-31",
    "31-07-2026",
    "Julio 2026",
]
STATIC_HASH = "8c19b71855cd167e12b55115c961f5be"
COMMON_HEADERS = {
    "User-Agent": "Mozilla/5.0 AFP-Habitat-Fondo3-Monitor",
    "Accept": "application/json, text/plain, */*",
    "Referer": APP,
    "Origin": BASE,
    "X-Requested-With": "XMLHttpRequest",
}
HEX_RE = re.compile(r"\b[a-f0-9]{24,128}\b", re.I)


def sample_response(response: requests.Response) -> dict[str, Any]:
    row: dict[str, Any] = {
        "status": response.status_code,
        "final_url": response.url,
        "content_type": response.headers.get("content-type"),
        "content_length": len(response.content),
        "allow": response.headers.get("allow"),
        "cookies": response.cookies.get_dict(),
        "sample": response.text[:20000],
    }
    try:
        payload = response.json()
        row["json_type"] = type(payload).__name__
        row["json_payload"] = payload
        if isinstance(payload, dict):
            row["json_keys"] = list(payload.keys())[:100]
        elif isinstance(payload, list):
            row["json_length"] = len(payload)
    except Exception:
        row["json_type"] = None
    return row


def collect_strings(value: Any) -> list[str]:
    strings: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in {"hash", "csrf", "csrf_habitat", "token", "csrf_token"}:
                strings.append(str(item))
            strings.extend(collect_strings(item))
    elif isinstance(value, list):
        for item in value:
            strings.extend(collect_strings(item))
    elif isinstance(value, str):
        strings.extend(HEX_RE.findall(value))
    return strings


def is_success(item: dict[str, Any]) -> bool:
    if item.get("status") != 200 or item.get("json_type") not in {"dict", "list"}:
        return False
    payload = item.get("json_payload")
    body_low = json.dumps(payload, ensure_ascii=False).lower()
    if any(text in body_low for text in ("route", "not found", "csrf inválido", "csrf invalido")):
        return False
    return int(item.get("content_length") or 0) > 20


def main() -> None:
    session = requests.Session()
    session.headers.update(COMMON_HEADERS)
    result: dict[str, Any] = {"app": {}, "hash_attempts": [], "post_attempts": []}
    hashes: list[str] = []

    app_response = session.get(APP, timeout=60)
    result["app"] = sample_response(app_response)
    result["session_cookies_after_app"] = session.cookies.get_dict()

    soup = BeautifulSoup(app_response.text, "lxml")
    for node in soup.find_all(["input", "meta"]):
        attrs = {str(key).lower(): str(value) for key, value in node.attrs.items()}
        combined = " ".join([*attrs.keys(), *attrs.values()]).lower()
        if "csrf" in combined or "token" in combined or "hash" in combined:
            for attr in ("value", "content"):
                value = node.get(attr)
                if value:
                    hashes.append(str(value))
    hashes.extend(HEX_RE.findall(app_response.text))

    for url in HASH_URLS:
        try:
            response = session.get(url, timeout=45, allow_redirects=True)
            item = {"url": url, **sample_response(response)}
            result["hash_attempts"].append(item)
            try:
                hashes.extend(collect_strings(response.json()))
            except Exception:
                hashes.extend(HEX_RE.findall(response.text))
        except Exception as exc:
            result["hash_attempts"].append({"url": url, "error": f"{type(exc).__name__}: {exc}"})

    hashes.extend([STATIC_HASH, ""])
    cleaned_hashes: list[str] = []
    for value in hashes:
        value = str(value).strip()
        if value not in cleaned_hashes and len(value) <= 256:
            cleaned_hashes.append(value)
    result["candidate_hashes"] = cleaned_hashes

    stop = False
    for fee_url in FEE_URLS:
        for hash_value in cleaned_hashes[:12]:
            for date_value in DATES:
                for encoding in ("multipart", "urlencoded"):
                    try:
                        values = {"csrf_habitat": hash_value, "fecha": date_value}
                        if encoding == "multipart":
                            response = session.post(
                                fee_url,
                                files={key: (None, value) for key, value in values.items()},
                                headers=COMMON_HEADERS,
                                timeout=60,
                                allow_redirects=True,
                            )
                        else:
                            response = session.post(
                                fee_url,
                                data=values,
                                headers={**COMMON_HEADERS, "Content-Type": "application/x-www-form-urlencoded"},
                                timeout=60,
                                allow_redirects=True,
                            )
                        item = {
                            "url": fee_url,
                            "hash": hash_value,
                            "fecha": date_value,
                            "encoding": encoding,
                            **sample_response(response),
                        }
                        result["post_attempts"].append(item)
                        if is_success(item):
                            result["successful_attempt"] = item
                            stop = True
                            break
                    except Exception as exc:
                        result["post_attempts"].append(
                            {
                                "url": fee_url,
                                "hash": hash_value,
                                "fecha": date_value,
                                "encoding": encoding,
                                "error": f"{type(exc).__name__}: {exc}",
                            }
                        )
                if stop:
                    break
            if stop:
                break
        if stop:
            break

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Hashes candidatos: {len(cleaned_hashes)}")
    print(f"POST probados: {len(result['post_attempts'])}")
    print(f"Éxito: {bool(result.get('successful_attempt'))}")
    if result.get("successful_attempt"):
        item = result["successful_attempt"]
        print(f"URL={item['url']} · fecha={item['fecha']} · encoding={item['encoding']}")


if __name__ == "__main__":
    main()
