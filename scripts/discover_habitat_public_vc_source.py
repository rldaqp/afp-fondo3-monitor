"""Descubre la fuente pública usada por el visor de valor cuota de AFP Hábitat."""

from __future__ import annotations

import json
import re
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

PAGE = "https://www.afphabitat.com.pe/rentabilidad/"
WP_PAGE = "https://www.afphabitat.com.pe/wp-json/wp/v2/pages/222"
HEADERS = {"User-Agent": "Mozilla/5.0 AFP-Habitat-Fondo3-Monitor"}
KEYS = (
    "valor", "cuota", "rentab", "fondo", "chart", "graf", "ajax",
    "api", "json", "service", "histor", "iframe",
)


def interesting(text: object) -> bool:
    low = str(text).lower()
    return any(key in low for key in KEYS)


def absolute(base: str, value: object) -> str:
    return urljoin(base, str(value).strip())


def print_contexts(label: str, raw: str) -> None:
    print(f"{label}_CONTEXTS_START")
    needles = (
        "valorcuota", "valor-cuota", "valor cuota", "iframe",
        "serviciosweb", "api/services", "admin-ajax", "wp-json",
    )
    emitted: set[str] = set()
    for needle in needles:
        for match in re.finditer(re.escape(needle), raw, re.I):
            chunk = raw[max(0, match.start() - 900): min(len(raw), match.end() + 1700)]
            compact = " ".join(chunk.split())
            if compact in emitted:
                continue
            emitted.add(compact)
            print(f"NEEDLE={needle}")
            print(compact[:3000])
    print(f"{label}_CONTEXTS_END")


def collect_embeds(base: str, soup: BeautifulSoup) -> set[str]:
    urls: set[str] = set()
    print("EMBEDS_START")
    for tag in ("iframe", "embed", "object"):
        for node in soup.find_all(tag):
            print(f"{tag.upper()}_ATTRS={json.dumps(dict(node.attrs), ensure_ascii=False)}")
            for attr in ("src", "data-src", "data-lazy-src", "data-url", "data-iframe", "data"):
                value = node.get(attr)
                if value:
                    url = absolute(base, value)
                    urls.add(url)
                    print(f"{tag.upper()}_{attr.upper()}={url}")
    print("EMBEDS_END")
    return urls


def print_related_nodes(soup: BeautifulSoup) -> None:
    print("RELATED_NODES_START")
    seen: set[str] = set()
    for node in soup.find_all(True):
        attrs = " ".join(
            [str(node.get("id", "")), " ".join(node.get("class", [])), str(node.attrs)]
        )
        text = " ".join(node.get_text(" ", strip=True).split())
        combined = f"{attrs} {text}"
        if not interesting(combined):
            continue
        rendered = str(node)
        compact = " ".join(rendered.split())
        if compact in seen:
            continue
        seen.add(compact)
        print(compact[:2500])
    print("RELATED_NODES_END")


def inspect_scripts(base: str, soup: BeautifulSoup, label: str) -> None:
    scripts = [absolute(base, node.get("src")) for node in soup.find_all("script") if node.get("src")]
    host = urlparse(base).netloc
    print(f"{label}_SCRIPTS_START")
    for script_url in scripts:
        if urlparse(script_url).netloc != host:
            continue
        try:
            js = requests.get(script_url, headers=HEADERS, timeout=45)
            js.raise_for_status()
        except Exception as exc:
            print(f"JS_ERROR={script_url} · {type(exc).__name__}: {exc}")
            continue
        matches = [line.strip() for line in js.text.splitlines() if interesting(line)]
        if not matches:
            continue
        print(f"JS_SOURCE={script_url}")
        for line in matches[:160]:
            print(line[:1800])
    print(f"{label}_SCRIPTS_END")


def inspect_document(url: str, label: str, recurse: bool = False) -> set[str]:
    response = requests.get(url, headers=HEADERS, timeout=60)
    response.raise_for_status()
    print(f"{label}_STATUS={response.status_code}")
    print(f"{label}_FINAL_URL={response.url}")
    print(f"{label}_CONTENT_TYPE={response.headers.get('content-type')}")
    print(f"{label}_LENGTH={len(response.content)}")

    soup = BeautifulSoup(response.text, "lxml")
    embeds = collect_embeds(response.url, soup)
    print_related_nodes(soup)
    print_contexts(label, response.text)
    inspect_scripts(response.url, soup, label)

    print(f"{label}_FORMS_START")
    for form in soup.find_all("form"):
        print(json.dumps(dict(form.attrs), ensure_ascii=False))
        print(" ".join(str(form).split())[:2500])
    print(f"{label}_FORMS_END")

    if recurse:
        for index, embed_url in enumerate(sorted(embeds), start=1):
            try:
                inspect_document(embed_url, f"IFRAME_{index}", recurse=False)
            except Exception as exc:
                print(f"IFRAME_ERROR={embed_url} · {type(exc).__name__}: {exc}")
    return embeds


def inspect_wp_page() -> set[str]:
    response = requests.get(WP_PAGE, headers=HEADERS, timeout=60)
    response.raise_for_status()
    payload = response.json()
    rendered = str(payload.get("content", {}).get("rendered", ""))
    print(f"WP_STATUS={response.status_code}")
    print(f"WP_RENDERED_LENGTH={len(rendered)}")
    print_contexts("WP_RENDERED", rendered)
    soup = BeautifulSoup(rendered, "lxml")
    embeds = collect_embeds(PAGE, soup)
    print_related_nodes(soup)
    return embeds


def main() -> None:
    page_embeds = inspect_document(PAGE, "PAGE", recurse=True)
    wp_embeds = inspect_wp_page()
    all_embeds = sorted(page_embeds | wp_embeds)
    print("ALL_EMBED_URLS_START")
    for url in all_embeds:
        print(url)
    print("ALL_EMBED_URLS_END")

    # Revisa también cualquier URL explícita de servicios encontrada en el HTML.
    page = requests.get(PAGE, headers=HEADERS, timeout=60)
    page.raise_for_status()
    candidates = set(re.findall(r"https?://[^\s\"'<>]+", page.text, re.I))
    print("SERVICE_CANDIDATES_START")
    for url in sorted(candidates):
        if interesting(url):
            print(url.replace("\\/", "/"))
    print("SERVICE_CANDIDATES_END")


if __name__ == "__main__":
    main()
