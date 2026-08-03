"""Inspecciona y prueba la navegación histórica de Variables SPP de la SBS."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "rolling90" / "sbs_variables_history_probe.json"
URLS = [
    "https://www.sbs.gob.pe/app/spp/variablesSPP_net/PagSS/variables_spp.aspx",
    "https://www.sbs.gob.pe/app/spp/variablesSPP/variables_spp.asp",
]
TARGETS = ["10/07/2026", "2026-07-10", "20260710"]
PARAM_NAMES = [
    "fecha", "Fecha", "FECHA", "date", "Date", "fec", "Fec", "f",
    "dia", "txtFecha", "ctl00$ContentPlaceHolder1$txtFecha",
]
HEADERS = {
    "User-Agent": "Mozilla/5.0 AFP-Fondo3-Monitor",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
DATE_RE = re.compile(r"Información\s+al\s+(\d{2}/\d{2}/\d{4})", re.I)
URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.I)


def summarize_response(response: requests.Response) -> dict[str, Any]:
    text = response.text
    dates = list(dict.fromkeys(DATE_RE.findall(text)))
    return {
        "status": response.status_code,
        "final_url": response.url,
        "content_type": response.headers.get("content-type"),
        "content_length": len(response.content),
        "dates": dates,
        "contains_10_july": "10/07/2026" in text,
        "contains_1_july": "01/07/2026" in text,
        "sample": text[:5000],
    }


def inspect_document(response: requests.Response) -> dict[str, Any]:
    soup = BeautifulSoup(response.text, "lxml")
    forms = []
    for form in soup.find_all("form"):
        controls = []
        for node in form.find_all(["input", "select", "button", "textarea"]):
            item = {
                "tag": node.name,
                "type": node.get("type"),
                "name": node.get("name"),
                "id": node.get("id"),
                "value": node.get("value"),
                "text": " ".join(node.get_text(" ", strip=True).split())[:300],
                "attrs": {str(k): str(v) for k, v in node.attrs.items()},
            }
            if node.name == "select":
                item["options"] = [
                    {
                        "value": option.get("value"),
                        "text": " ".join(option.get_text(" ", strip=True).split()),
                        "selected": option.has_attr("selected"),
                    }
                    for option in node.find_all("option")
                ][:100]
            controls.append(item)
        forms.append(
            {
                "action": urljoin(response.url, form.get("action") or response.url),
                "method": (form.get("method") or "get").lower(),
                "attrs": {str(k): str(v) for k, v in form.attrs.items()},
                "controls": controls,
            }
        )

    scripts = []
    for node in soup.find_all("script"):
        if node.get("src"):
            scripts.append({"src": urljoin(response.url, node.get("src"))})
        else:
            text = node.get_text("\n", strip=False)
            if any(term in text.lower() for term in ("fecha", "histor", "ajax", "variable", "postback")):
                scripts.append({"inline": text[:20000]})

    links = []
    for node in soup.find_all("a", href=True):
        href = urljoin(response.url, node.get("href"))
        text = " ".join(node.get_text(" ", strip=True).split())
        if any(term in f"{href} {text}".lower() for term in ("fecha", "histor", "variable", "spp", "xls", "excel")):
            links.append({"href": href, "text": text})

    comments_and_contexts = []
    raw = response.text
    for term in ("10/07/2026", "fecha", "históric", "histor", "__doPostBack", "variables_spp"):
        for match in re.finditer(re.escape(term), raw, re.I):
            context = " ".join(raw[max(0, match.start() - 800):match.end() + 1600].split())
            if context not in comments_and_contexts:
                comments_and_contexts.append(context[:3000])
            if len(comments_and_contexts) >= 120:
                break

    return {
        "forms": forms,
        "scripts": scripts,
        "links": links,
        "absolute_urls": sorted(set(URL_RE.findall(raw)))[:300],
        "contexts": comments_and_contexts,
    }


def hidden_payload(form: dict[str, Any]) -> dict[str, str]:
    payload: dict[str, str] = {}
    for control in form.get("controls", []):
        if control.get("tag") != "input" or not control.get("name"):
            continue
        kind = str(control.get("type") or "text").lower()
        if kind == "hidden":
            payload[str(control["name"])] = str(control.get("value") or "")
    return payload


def main() -> None:
    session = requests.Session()
    session.headers.update(HEADERS)
    result: dict[str, Any] = {"pages": [], "query_attempts": [], "post_attempts": []}

    for url in URLS:
        try:
            response = session.get(url, timeout=60)
            page = {"url": url, **summarize_response(response)}
            page["document"] = inspect_document(response)
            result["pages"].append(page)

            # Prueba parámetros GET frecuentes usados por visores históricos.
            for name in PARAM_NAMES:
                for target in TARGETS:
                    try:
                        query_response = session.get(url, params={name: target}, timeout=45)
                        summary = summarize_response(query_response)
                        result["query_attempts"].append(
                            {"url": url, "parameter": name, "value": target, **summary}
                        )
                    except Exception as exc:
                        result["query_attempts"].append(
                            {"url": url, "parameter": name, "value": target, "error": f"{type(exc).__name__}: {exc}"}
                        )

            # Reproduce formularios ASP/ASP.NET conservando campos ocultos.
            for form in page["document"].get("forms", []):
                action = form.get("action") or url
                base = hidden_payload(form)
                named_controls = [
                    control for control in form.get("controls", [])
                    if control.get("name") and str(control.get("type") or "").lower() != "hidden"
                ]
                likely_names = [
                    str(control["name"]) for control in named_controls
                    if any(term in str(control.get("name", "")).lower() for term in ("fecha", "date", "fec", "dia"))
                ]
                submit_controls = [
                    control for control in named_controls
                    if str(control.get("type") or "").lower() in {"submit", "button", "image"}
                ]
                for field_name in likely_names[:20]:
                    for target in TARGETS:
                        payload = dict(base)
                        payload[field_name] = target
                        if submit_controls:
                            submit = submit_controls[0]
                            if submit.get("name"):
                                payload[str(submit["name"])] = str(submit.get("value") or submit.get("text") or "Consultar")
                        try:
                            post_response = session.post(action, data=payload, timeout=60)
                            result["post_attempts"].append(
                                {
                                    "page_url": url,
                                    "action": action,
                                    "field": field_name,
                                    "value": target,
                                    "payload_keys": list(payload.keys()),
                                    **summarize_response(post_response),
                                }
                            )
                        except Exception as exc:
                            result["post_attempts"].append(
                                {
                                    "page_url": url,
                                    "action": action,
                                    "field": field_name,
                                    "value": target,
                                    "error": f"{type(exc).__name__}: {exc}",
                                }
                            )
        except Exception as exc:
            result["pages"].append({"url": url, "error": f"{type(exc).__name__}: {exc}"})

    successful = [
        item for item in [*result["query_attempts"], *result["post_attempts"]]
        if item.get("contains_10_july") or item.get("contains_1_july")
    ]
    result["successful_attempts"] = successful
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Páginas: {len(result['pages'])}")
    print(f"GET probados: {len(result['query_attempts'])}")
    print(f"POST probados: {len(result['post_attempts'])}")
    print(f"Intentos con julio temprano: {len(successful)}")


if __name__ == "__main__":
    main()
