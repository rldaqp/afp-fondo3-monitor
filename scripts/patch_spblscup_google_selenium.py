from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
LIVE_PATH = ROOT / "public" / "data" / "live_market.json"


def finite(value) -> bool:
    try:
        return value is not None and np.isfinite(float(value))
    except Exception:
        return False


def extract_google_finance() -> tuple[float, float | None, str]:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait

    url = "https://www.google.com/finance/quote/SPBLSCUP:INDEXSP?hl=en&gl=us"
    options = webdriver.ChromeOptions()
    for arg in (
        "--headless=new",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-gpu",
        "--window-size=1920,1080",
        "--lang=en-US",
    ):
        options.add_argument(arg)

    driver = webdriver.Chrome(options=options)
    try:
        driver.get(url)
        WebDriverWait(driver, 30).until(
            lambda d: "S&P Peru Select 20% Capped Index" in d.find_element(By.TAG_NAME, "body").text
        )
        text = driver.find_element(By.TAG_NAME, "body").text
    finally:
        driver.quit()

    price_match = re.search(
        r"S&P Peru Select 20% Capped Index\s*\(USD\)\s+([\d,]+\.\d+)",
        text,
        flags=re.IGNORECASE,
    )
    if not price_match:
        raise RuntimeError("Google Finance abrió, pero no se identificó el nivel SPBLSCUP")
    price = float(price_match.group(1).replace(",", ""))

    prev_match = re.search(r"Prev\.\s*close\s+([\d,]+\.\d+)", text, flags=re.IGNORECASE)
    previous = float(prev_match.group(1).replace(",", "")) if prev_match else None

    stamp_match = re.search(
        r"(Aug|Sep|Oct|Nov|Dec|Jan|Feb|Mar|Apr|May|Jun|Jul)\s+\d{1,2},\s+[^\n]+UTC[+-]\d+",
        text,
        flags=re.IGNORECASE,
    )
    stamp = stamp_match.group(0) if stamp_match else "GOOGLE FINANCE · SESIÓN ACTUAL"

    if not (300 < price < 700):
        raise RuntimeError(f"Nivel SPBLSCUP fuera de rango de control: {price}")
    if previous and abs(price / previous - 1.0) > 0.10:
        raise RuntimeError(f"Movimiento SPBLSCUP >10%: {price} vs {previous}")
    return price, previous, stamp


def main() -> None:
    if not LIVE_PATH.exists():
        raise RuntimeError("Falta public/data/live_market.json")
    live = json.loads(LIVE_PATH.read_text(encoding="utf-8"))

    try:
        price, previous, stamp = extract_google_finance()
    except Exception as exc:
        print(f"SPBLSCUP Selenium no disponible: {type(exc).__name__}: {exc}")
        return

    rows = live.setdefault("experimental_assets", [])
    row = next((x for x in rows if x.get("serie") == "SPBLSCUP"), None)
    if row is None:
        row = {"serie": "SPBLSCUP", "ticker": "SPBLSCUP:INDEXSP"}
        rows.append(row)

    if previous is None:
        old_price = row.get("precio_actual")
        if finite(old_price) and float(old_price) != price:
            previous = float(old_price)

    ret = price / previous - 1.0 if previous not in (None, 0.0) else None
    row.update(
        {
            "ticker": "SPBLSCUP:INDEXSP",
            "timestamp": str(live.get("signal_date") or stamp),
            "precio_anterior": previous,
            "precio_actual": price,
            "retorno": ret,
            "retorno_modelo": ret,
            "estado": "GOOGLE FINANCE · SELENIUM · NUEVO 60/30 EXPERIMENTAL",
            "usado_modelo": True,
        }
    )
    live["experimental_spblscup_source"] = "GOOGLE FINANCE · SELENIUM"
    live["experimental_spblscup_stamp"] = stamp
    LIVE_PATH.write_text(json.dumps(live, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "signal_date": live.get("signal_date"),
                "SPBLSCUP": price,
                "previous": previous,
                "return": ret,
                "stamp": stamp,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
