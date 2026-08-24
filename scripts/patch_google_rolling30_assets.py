from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
LIVE_PATH = ROOT / "public" / "data" / "live_market.json"
OUT_RETURNS = ROOT / "data" / "analysis" / "googlefinance_alt_rolling30_live_returns.csv"

SPECS = {
    ".INX": (".INX:INDEXSP", 1000.0, 20000.0),
    "CPER": ("CPER:NYSEARCA", 5.0, 100.0),
    "EEM": ("EEM:NYSEARCA", 10.0, 150.0),
    "NDX": ("NDX:INDEXNASDAQ", 5000.0, 50000.0),
    "SPBLSCUP": ("SPBLSCUP:INDEXSP", 100.0, 1000.0),
}


def finite(v) -> bool:
    try:
        return v is not None and np.isfinite(float(v))
    except Exception:
        return False


def num(text: str) -> float:
    s = str(text).replace("−", "-").replace("$", "").replace(",", "").strip()
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    if not m:
        raise ValueError(text)
    return float(m.group(0))


def numeric_candidates(text: str) -> list[float]:
    """Convierte solo tokens numéricos válidos; Google a veces devuelve ',' como token."""
    out: list[float] = []
    for token in re.findall(r"(?:\$\s*)?[\d,]+(?:\.\d+)?", text):
        try:
            out.append(num(token))
        except (TypeError, ValueError):
            continue
    return out


def scrape_all() -> dict[str, dict]:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait

    opts = webdriver.ChromeOptions()
    for arg in (
        "--headless=new",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-gpu",
        "--window-size=1920,1080",
        "--lang=en-US",
    ):
        opts.add_argument(arg)

    driver = webdriver.Chrome(options=opts)
    out: dict[str, dict] = {}
    try:
        for name, (quote, lo, hi) in SPECS.items():
            url = f"https://www.google.com/finance/quote/{quote}?hl=en&gl=us"
            try:
                driver.get(url)
                WebDriverWait(driver, 25).until(lambda d: len(d.find_elements(By.TAG_NAME, "body")) == 1)
                WebDriverWait(driver, 25).until(lambda d: "close" in d.find_element(By.TAG_NAME, "body").text.lower())
                body = driver.find_element(By.TAG_NAME, "body").text

                price = None
                for el in driver.find_elements(By.CSS_SELECTOR, "div.YMlKec.fxKbKc"):
                    try:
                        candidate = num(el.text)
                    except Exception:
                        continue
                    if lo < candidate < hi:
                        price = candidate
                        break
                if price is None:
                    # Respaldo robusto: ignora tokens vacíos/comas y conserva solo números válidos.
                    candidates = numeric_candidates(body[:1600])
                    price = next((x for x in candidates if lo < x < hi), None)
                if price is None:
                    raise RuntimeError("No se identificó precio principal")

                collapsed = re.sub(r"\s+", " ", body)
                pm = re.search(r"Prev(?:ious)?\.?\s*close\s+\$?([\d,]+(?:\.\d+)?)", collapsed, re.I)
                previous = float(pm.group(1).replace(",", "")) if pm else None
                if previous is None or not (lo < previous < hi):
                    raise RuntimeError("No se identificó Prev close")
                ret = price / previous - 1.0
                if abs(ret) > 0.20:
                    raise RuntimeError(f"Movimiento fuera de control: {ret:.3%}")

                sm = re.search(
                    r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},\s+[^\n]+UTC[+-]\d+",
                    body,
                    re.I,
                )
                out[name] = {
                    "quote": quote,
                    "price": float(price),
                    "previous": float(previous),
                    "return": float(ret),
                    "stamp": sm.group(0) if sm else "GOOGLE FINANCE · SESIÓN ACTUAL",
                    "url": url,
                }
            except Exception as exc:
                out[name] = {"quote": quote, "error": f"{type(exc).__name__}: {exc}", "url": url}
    finally:
        driver.quit()
    return out


def persist_closed_returns(live: dict, scraped: dict[str, dict]) -> None:
    if bool(live.get("market_open")):
        return
    if not all(finite(scraped.get(k, {}).get("return")) for k in SPECS):
        print("No se persiste cierre: faltan uno o más retornos exactos Google Finance")
        return

    row = {
        "fecha": str(live.get("signal_date", ""))[:10],
        "ret_.INX": scraped[".INX"]["return"],
        "ret_CPER": scraped["CPER"]["return"],
        "ret_EEM": scraped["EEM"]["return"],
        "ret_NDX": scraped["NDX"]["return"],
        "ret_SPBLSCUP": scraped["SPBLSCUP"]["return"],
        "source": "GOOGLE FINANCE · SELENIUM · CIERRE",
    }
    if not row["fecha"]:
        return
    OUT_RETURNS.parent.mkdir(parents=True, exist_ok=True)
    if OUT_RETURNS.exists():
        df = pd.read_csv(OUT_RETURNS)
    else:
        df = pd.DataFrame(columns=list(row))
    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce").dt.strftime("%Y-%m-%d")
    df = df.dropna(subset=["fecha"]).sort_values("fecha").drop_duplicates("fecha", keep="last")
    df.to_csv(OUT_RETURNS, index=False)
    print("Cierre Google rolling30 persistido:", row["fecha"])


def main() -> None:
    if not LIVE_PATH.exists():
        raise RuntimeError("Falta public/data/live_market.json")
    live = json.loads(LIVE_PATH.read_text(encoding="utf-8"))
    scraped = scrape_all()

    rows = live.setdefault("experimental_assets", [])
    by = {str(x.get("serie")): x for x in rows}
    for name, result in scraped.items():
        if not finite(result.get("return")):
            print(name, result.get("error"))
            continue
        row = by.get(name)
        if row is None:
            row = {"serie": name, "ticker": result["quote"]}
            rows.append(row)
        row.update(
            {
                "ticker": result["quote"],
                "timestamp": str(live.get("signal_date") or result.get("stamp")),
                "precio_anterior": result["previous"],
                "precio_actual": result["price"],
                "retorno": result["return"],
                "retorno_modelo": result["return"],
                "estado": "GOOGLE FINANCE · SELENIUM · ROLLING30 NUEVOS TICKERS",
                "usado_modelo": True,
                "google_stamp": result.get("stamp"),
            }
        )

    live["experimental_google_rolling30_checked"] = True
    live["experimental_google_rolling30_results"] = {
        k: {kk: vv for kk, vv in v.items() if kk != "url"} for k, v in scraped.items()
    }
    LIVE_PATH.write_text(json.dumps(live, ensure_ascii=False, indent=2), encoding="utf-8")
    persist_closed_returns(live, scraped)
    print(json.dumps(live["experimental_google_rolling30_results"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
