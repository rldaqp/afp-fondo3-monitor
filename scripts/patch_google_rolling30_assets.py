from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
LIVE_PATH = ROOT / "public" / "data" / "live_market.json"
OUT_RETURNS = ROOT / "data" / "analysis" / "googlefinance_alt_rolling30_live_returns.csv"

# Los cuatro primeros tienen un equivalente exacto/operable en Yahoo que se usa
# SOLO como control/fallback del cierre. SPBLSCUP no tiene equivalente Yahoo fiable.
SPECS = {
    ".INX": {"quote": ".INX:INDEXSP", "lo": 1000.0, "hi": 20000.0, "yahoo": "^GSPC"},
    "CPER": {"quote": "CPER:NYSEARCA", "lo": 5.0, "hi": 100.0, "yahoo": "CPER"},
    "EEM": {"quote": "EEM:NYSEARCA", "lo": 10.0, "hi": 150.0, "yahoo": "EEM"},
    "NDX": {"quote": "NDX:INDEXNASDAQ", "lo": 5000.0, "hi": 50000.0, "yahoo": "^NDX"},
    "SPBLSCUP": {"quote": "SPBLSCUP:INDEXSP", "lo": 100.0, "hi": 1000.0, "yahoo": None},
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


def extract_close(raw: pd.DataFrame, ticker: str) -> pd.Series:
    if raw.empty:
        return pd.Series(dtype=float)
    if isinstance(raw.columns, pd.MultiIndex):
        for key in [("Close", ticker), (ticker, "Close")]:
            if key in raw.columns:
                return pd.to_numeric(raw[key], errors="coerce").dropna()
        if "Close" in raw.columns.get_level_values(0):
            b = raw.xs("Close", axis=1, level=0)
            if ticker in b.columns:
                return pd.to_numeric(b[ticker], errors="coerce").dropna()
    if "Close" in raw.columns:
        return pd.to_numeric(raw["Close"], errors="coerce").dropna()
    return pd.Series(dtype=float)


def yahoo_close(ticker: str, signal_date: str) -> dict | None:
    """Cierre Yahoo de la sesión, usado para validar .INX/CPER/EEM/NDX."""
    target = pd.Timestamp(signal_date).normalize()
    raw = yf.download(
        ticker,
        start=(target - pd.Timedelta(days=10)).strftime("%Y-%m-%d"),
        end=(target + pd.Timedelta(days=2)).strftime("%Y-%m-%d"),
        auto_adjust=False,
        actions=False,
        progress=False,
        threads=False,
    )
    close = extract_close(raw, ticker)
    if close.empty:
        return None
    idx = pd.to_datetime(close.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    d = pd.DataFrame({"fecha": idx.normalize(), "close": close.to_numpy(float)})
    same = d.loc[d["fecha"].eq(target)]
    prev = d.loc[d["fecha"] < target].tail(1)
    if same.empty or prev.empty:
        return None
    current = float(same.iloc[-1]["close"])
    previous = float(prev.iloc[-1]["close"])
    return {
        "price": current,
        "previous": previous,
        "return": current / previous - 1.0,
        "source": f"YAHOO {ticker} · CIERRE VALIDACIÓN",
    }


def google_main_price(driver, name: str, body: str, lo: float, hi: float) -> float:
    """Extrae el precio principal; nunca usa 'primer número que caiga en rango'."""
    # SPBLSCUP: esta expresión por nombre del instrumento fue la que ya había
    # funcionado correctamente con 446.70/460.43. Evita confundir 52-week high,
    # rangos u otros números de la página con el nivel del índice.
    if name == "SPBLSCUP":
        m = re.search(
            r"S&P(?:/BVL)?\s+Peru\s+Select\s+20%\s+Capped\s+Index\s*\(USD\)\s+([\d,]+(?:\.\d+)?)",
            body,
            flags=re.I,
        )
        if m:
            v = float(m.group(1).replace(",", ""))
            if lo < v < hi:
                return v

    # Google Finance expone el quote principal mediante data-last-price. Se
    # consulta el atributo real del DOM, no el texto de tarjetas auxiliares.
    candidates = []
    for el in driver.find_elements("css selector", "[data-last-price]"):
        raw = el.get_attribute("data-last-price")
        try:
            v = float(str(raw).replace(",", ""))
        except Exception:
            continue
        if lo < v < hi:
            candidates.append(v)
    if candidates:
        return float(candidates[0])

    # Último recurso: el bloque visual de precio principal, pero únicamente si
    # hay un candidato inequívoco. No se escanean números arbitrarios del body.
    visual = []
    for el in driver.find_elements("css selector", "div.YMlKec.fxKbKc"):
        try:
            v = num(el.text)
        except Exception:
            continue
        if lo < v < hi:
            visual.append(v)
    visual = list(dict.fromkeys(visual))
    if len(visual) == 1:
        return float(visual[0])
    raise RuntimeError(f"Precio principal ambiguo/no identificado: {visual[:5]}")


def scrape_all(signal_date: str) -> dict[str, dict]:
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
        for name, spec in SPECS.items():
            quote, lo, hi = spec["quote"], float(spec["lo"]), float(spec["hi"])
            yahoo_ticker = spec.get("yahoo")
            url = f"https://www.google.com/finance/quote/{quote}?hl=en&gl=us"
            ycheck = None
            if yahoo_ticker:
                try:
                    ycheck = yahoo_close(str(yahoo_ticker), signal_date)
                except Exception as exc:
                    print(name, "Yahoo validación no disponible:", type(exc).__name__, exc)
            try:
                driver.get(url)
                WebDriverWait(driver, 25).until(lambda d: len(d.find_elements(By.TAG_NAME, "body")) == 1)
                WebDriverWait(driver, 25).until(lambda d: "close" in d.find_element(By.TAG_NAME, "body").text.lower())
                body = driver.find_element(By.TAG_NAME, "body").text

                price = google_main_price(driver, name, body, lo, hi)
                collapsed = re.sub(r"\s+", " ", body)
                pm = re.search(r"Prev(?:ious)?\.?\s*close\s+\$?([\d,]+(?:\.\d+)?)", collapsed, re.I)
                previous = float(pm.group(1).replace(",", "")) if pm else None
                if previous is None or not (lo < previous < hi):
                    raise RuntimeError("No se identificó Prev close")
                ret = price / previous - 1.0

                # Para instrumentos con equivalente Yahoo exacto, Google debe
                # concordar con el cierre. Si no, se usa el cierre Yahoo validado.
                validation = "GOOGLE EXACTO"
                if ycheck is not None:
                    price_gap = abs(price / float(ycheck["price"]) - 1.0)
                    ret_gap = abs(ret - float(ycheck["return"]))
                    if price_gap > 0.003 or ret_gap > 0.003:
                        price = float(ycheck["price"])
                        previous = float(ycheck["previous"])
                        ret = float(ycheck["return"])
                        validation = f"YAHOO {yahoo_ticker} · CORRIGE GOOGLE INCONSISTENTE"
                    else:
                        validation = f"GOOGLE EXACTO · VALIDADO YAHOO {yahoo_ticker}"

                # Un >12% diario en cualquiera de estos índices/ETF se bloquea.
                # No sustituimos por 0%; el modelo debe quedar pendiente si no hay
                # una fuente corroborada.
                if abs(ret) > 0.12:
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
                    "validation": validation,
                    "valid_for_model": True,
                    "url": url,
                }
            except Exception as exc:
                # Si Google falla para un instrumento con equivalente exacto,
                # Yahoo sigue siendo una validación aceptable del mismo cierre.
                if ycheck is not None:
                    out[name] = {
                        "quote": quote,
                        "price": float(ycheck["price"]),
                        "previous": float(ycheck["previous"]),
                        "return": float(ycheck["return"]),
                        "stamp": signal_date,
                        "validation": f"YAHOO {yahoo_ticker} · FALLBACK POR ERROR GOOGLE",
                        "valid_for_model": True,
                        "google_error": f"{type(exc).__name__}: {exc}",
                        "url": url,
                    }
                else:
                    out[name] = {
                        "quote": quote,
                        "error": f"{type(exc).__name__}: {exc}",
                        "validation": "NO VALIDADO · NO USAR EN MODELO",
                        "valid_for_model": False,
                        "url": url,
                    }
    finally:
        driver.quit()
    return out


def persist_closed_returns(live: dict, scraped: dict[str, dict]) -> None:
    if bool(live.get("market_open")):
        return
    if not all(bool(scraped.get(k, {}).get("valid_for_model")) and finite(scraped.get(k, {}).get("return")) for k in SPECS):
        print("No se persiste cierre: faltan uno o más retornos validados")
        return

    row = {
        "fecha": str(live.get("signal_date", ""))[:10],
        "ret_.INX": scraped[".INX"]["return"],
        "ret_CPER": scraped["CPER"]["return"],
        "ret_EEM": scraped["EEM"]["return"],
        "ret_NDX": scraped["NDX"]["return"],
        "ret_SPBLSCUP": scraped["SPBLSCUP"]["return"],
        "source": "CIERRE VALIDADO · GOOGLE FINANCE/YAHOO EQUIVALENTE",
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
    print("Cierre rolling30 nuevos tickers persistido y validado:", row["fecha"])


def main() -> None:
    if not LIVE_PATH.exists():
        raise RuntimeError("Falta public/data/live_market.json")
    live = json.loads(LIVE_PATH.read_text(encoding="utf-8"))
    signal_date = str(live.get("signal_date", ""))[:10]
    if not signal_date:
        raise RuntimeError("live_market sin signal_date")
    scraped = scrape_all(signal_date)

    rows = live.setdefault("experimental_assets", [])
    by = {str(x.get("serie")): x for x in rows}
    for name, result in scraped.items():
        row = by.get(name)
        if row is None:
            row = {"serie": name, "ticker": result["quote"]}
            rows.append(row)

        if not bool(result.get("valid_for_model")) or not finite(result.get("return")):
            row.update({
                "ticker": result["quote"],
                "retorno_modelo": None,
                "usado_modelo": False,
                "validado_modelo": False,
                "estado": result.get("validation") or "NO VALIDADO · NO USAR EN MODELO",
                "error_validacion": result.get("error"),
            })
            print(name, result.get("error"))
            continue

        row.update(
            {
                "ticker": result["quote"],
                "timestamp": str(live.get("signal_date") or result.get("stamp")),
                "precio_anterior": result["previous"],
                "precio_actual": result["price"],
                "retorno": result["return"],
                "retorno_modelo": result["return"],
                "estado": result.get("validation") or "CIERRE VALIDADO",
                "usado_modelo": True,
                "validado_modelo": True,
                "google_stamp": result.get("stamp"),
                "error_validacion": result.get("google_error"),
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
