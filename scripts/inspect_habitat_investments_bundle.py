"""Extrae endpoints y contratos del bundle público de inversiones de AFP Hábitat."""

from __future__ import annotations

import json
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

APP = "https://www.afphabitat.com.pe/privado/admin/investments/home"
HEADERS = {"User-Agent": "Mozilla/5.0 AFP-Habitat-Fondo3-Monitor"}
TERMS = (
    "cuota", "valor", "fund", "fondo", "investment", "rentab", "histor",
    "api", "service", "axios", "fetch", "graphql", "date", "fecha",
)


def relevant(text: object) -> bool:
    low = str(text).lower()
    return any(term in low for term in TERMS)


def strings_from_js(text: str) -> list[str]:
    values: set[str] = set()
    patterns = (
        r'"((?:\\.|[^"\\]){2,500})"',
        r"'((?:\\.|[^'\\]){2,500})'",
        r"`((?:\\.|[^`\\]){2,500})`",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.DOTALL):
            value = match.group(1)
            if relevant(value):
                values.add(value)
    return sorted(values)


def print_contexts(label: str, text: str, max_hits: int = 300) -> None:
    print(f"{label}_CONTEXTS_START")
    hits = 0
    for term in TERMS:
        for match in re.finditer(re.escape(term), text, re.I):
            chunk = text[max(0, match.start() - 500): min(len(text), match.end() + 1000)]
            print(f"TERM={term}")
            print(" ".join(chunk.split())[:1800])
            hits += 1
            if hits >= max_hits:
                print("CONTEXT_LIMIT_REACHED")
                print(f"{label}_CONTEXTS_END")
                return
    print(f"{label}_CONTEXTS_END")


def main() -> None:
    session = requests.Session()
    session.headers.update(HEADERS)

    page = session.get(APP, timeout=60)
    page.raise_for_status()
    soup = BeautifulSoup(page.text, "lxml")
    scripts = [urljoin(page.url, node.get("src")) for node in soup.find_all("script") if node.get("src")]
    main_scripts = [url for url in scripts if "/static/js/main." in url and url.endswith(".js")]
    print(f"APP_STATUS={page.status_code}")
    print(f"APP_URL={page.url}")
    print("SCRIPT_URLS_START")
    for url in scripts:
        print(url)
    print("SCRIPT_URLS_END")
    if not main_scripts:
        raise RuntimeError("No se encontró el bundle principal de inversiones.")

    bundle_url = main_scripts[-1]
    bundle = session.get(bundle_url, timeout=90)
    bundle.raise_for_status()
    print(f"BUNDLE_URL={bundle_url}")
    print(f"BUNDLE_LENGTH={len(bundle.content)}")

    print("BUNDLE_RELEVANT_STRINGS_START")
    for value in strings_from_js(bundle.text):
        print(value[:1000])
    print("BUNDLE_RELEVANT_STRINGS_END")
    print_contexts("BUNDLE", bundle.text, max_hits=180)

    map_urls = [bundle_url + ".map"]
    source_map_match = re.search(r"sourceMappingURL=([^\s*]+)", bundle.text)
    if source_map_match:
        map_urls.insert(0, urljoin(bundle_url, source_map_match.group(1).strip()))

    source_map = None
    source_map_url = None
    for candidate in dict.fromkeys(map_urls):
        try:
            response = session.get(candidate, timeout=120)
            if response.ok and response.content:
                source_map = response.json()
                source_map_url = candidate
                break
        except Exception as exc:
            print(f"MAP_ERROR={candidate} · {type(exc).__name__}: {exc}")

    if source_map is None:
        print("SOURCE_MAP_NOT_AVAILABLE")
        return

    print(f"SOURCE_MAP_URL={source_map_url}")
    sources = source_map.get("sources", [])
    contents = source_map.get("sourcesContent", [])
    print(f"SOURCE_COUNT={len(sources)}")

    print("SOURCE_NAMES_START")
    for name in sources:
        if relevant(name):
            print(name)
    print("SOURCE_NAMES_END")

    print("SOURCE_MATCHES_START")
    for index, name in enumerate(sources):
        content = contents[index] if index < len(contents) else None
        if not content or not (relevant(name) or relevant(content)):
            continue
        print(f"SOURCE={name}")
        print("RELEVANT_STRINGS")
        for value in strings_from_js(content)[:250]:
            print(value[:1000])
        print_contexts(f"SOURCE_{index}", content, max_hits=120)
    print("SOURCE_MATCHES_END")


if __name__ == "__main__":
    main()
