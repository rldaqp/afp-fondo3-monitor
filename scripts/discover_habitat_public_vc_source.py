"""Descubre la fuente pública de datos usada por el visor de rentabilidad de AFP Hábitat."""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

PAGE = "https://www.afphabitat.com.pe/rentabilidad/"
HEADERS = {"User-Agent": "Mozilla/5.0 AFP-Habitat-Fondo3-Monitor"}
KEYS = ("valor", "cuota", "rentab", "fondo", "chart", "graf", "ajax", "api", "json")


def interesting(text: str) -> bool:
    low = text.lower()
    return any(key in low for key in KEYS)


def main() -> None:
    response = requests.get(PAGE, headers=HEADERS, timeout=60)
    response.raise_for_status()
    print(f"PAGE_STATUS={response.status_code}")
    print(f"PAGE_FINAL_URL={response.url}")
    soup = BeautifulSoup(response.text, "lxml")

    urls: set[str] = set()
    for tag, attr in (("script", "src"), ("a", "href"), ("form", "action"), ("link", "href")):
        for node in soup.find_all(tag):
            value = node.get(attr)
            if value:
                url = urljoin(response.url, value)
                if interesting(url):
                    urls.add(url)

    print("INTERESTING_URLS_START")
    for url in sorted(urls):
        print(url)
    print("INTERESTING_URLS_END")

    inline = "\n".join(script.get_text("\n", strip=False) for script in soup.find_all("script") if not script.get("src"))
    for pattern in (
        r"https?://[^\s\"']+",
        r"[\"']([^\"']*(?:valor|cuota|rentab|fondo|ajax|api|json)[^\"']*)[\"']",
    ):
        print(f"INLINE_PATTERN={pattern}")
        seen: set[str] = set()
        for match in re.finditer(pattern, inline, re.I):
            value = match.group(1) if match.lastindex else match.group(0)
            if value not in seen:
                seen.add(value)
                print(value[:500])

    # Inspecciona JavaScript del mismo sitio y registra líneas relacionadas con datos.
    scripts = [urljoin(response.url, node.get("src")) for node in soup.find_all("script") if node.get("src")]
    host = urlparse(response.url).netloc
    for script_url in scripts:
        if urlparse(script_url).netloc != host:
            continue
        try:
            js = requests.get(script_url, headers=HEADERS, timeout=45)
            js.raise_for_status()
        except Exception as exc:
            print(f"JS_ERROR {script_url} {type(exc).__name__}: {exc}")
            continue
        matches = [line.strip() for line in js.text.splitlines() if interesting(line)]
        if matches:
            print(f"JS_SOURCE={script_url}")
            for line in matches[:80]:
                print(line[:1000])


if __name__ == "__main__":
    main()
