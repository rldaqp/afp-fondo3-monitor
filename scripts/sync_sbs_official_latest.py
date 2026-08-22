from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "data" / "rolling90" / "sbs_profuturo_f3.csv"
STATUS_PATH = ROOT / "public" / "data" / "sbs_sync_status.json"
SERIES_PATH = ROOT / "public" / "data" / "series.json"
SIGNALS_PATH = ROOT / "public" / "data" / "signals.json"
SBS_URL = "https://www.sbs.gob.pe/app/spp/variablesSPP_net/PagSS/variables_spp.aspx"
LIMA = ZoneInfo("America/Lima")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151 Safari/537.36"
}

# El 20/08 fue facilitado por el usuario solo para comparar el modelo. No puede
# considerarse SBS oficial hasta que aparezca en la fuente SBS consultada por el
# propio monitor. En cuanto la SBS lo publique, esta misma sincronización lo
# reincorpora automáticamente con el valor obtenido de la web oficial.
COMPARISON_ONLY_DATES = {pd.Timestamp("2026-08-20")}


def norm(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(text.lower().split())


def parse_num(value: object) -> float | None:
    x = pd.to_numeric(str(value).replace("\xa0", "").replace(" ", "").replace(",", ""), errors="coerce")
    return None if pd.isna(x) else float(x)


def parse_sbs_html(html: str) -> pd.DataFrame:
    soup = BeautifulSoup(html, "lxml")
    rows: list[dict[str, object]] = []

    for table in soup.find_all("table"):
        text = " ".join(table.stripped_strings)
        dates = list(dict.fromkeys(re.findall(r"\d{2}/\d{2}/\d{4}", text)))
        if len(dates) != 1:
            continue
        fecha = pd.to_datetime(dates[0], format="%d/%m/%Y", errors="coerce")
        if pd.isna(fecha):
            continue
        for tr in table.find_all("tr"):
            cells = tr.find_all(["th", "td"], recursive=False)
            values = [" ".join(c.get_text(" ", strip=True).split()) for c in cells]
            if values and norm(values[0]) == "profuturo" and len(values) >= 10:
                vc = parse_num(values[9])
                if vc is not None:
                    rows.append({"fecha": fecha, "valor_cuota": vc})
                break

    if not rows:
        text = soup.get_text("\n", strip=True)
        marks = list(re.finditer(r"Informaci[oó]n\s+al\s+(\d{2}/\d{2}/\d{4})", text, flags=re.I))
        for i, mark in enumerate(marks):
            fecha = pd.to_datetime(mark.group(1), format="%d/%m/%Y", errors="coerce")
            end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
            block = text[mark.end():end]
            p = re.search(r"PROFUTURO\s+([^\n]+)", block, flags=re.I)
            if not p or pd.isna(fecha):
                continue
            nums = re.findall(r"-?\d[\d,]*(?:\.\d+)?", p.group(1))
            if len(nums) >= 9:
                vc = parse_num(nums[8])
                if vc is not None:
                    rows.append({"fecha": fecha, "valor_cuota": vc})

    if not rows:
        raise RuntimeError("La página SBS abrió, pero no se pudo extraer PROFUTURO Fondo 3")

    out = pd.DataFrame(rows)
    out["fecha"] = pd.to_datetime(out["fecha"], errors="coerce")
    out["valor_cuota"] = pd.to_numeric(out["valor_cuota"], errors="coerce")
    out = out.dropna().sort_values("fecha").drop_duplicates("fecha", keep="last")
    if out.empty or not out["valor_cuota"].between(20, 150).all():
        raise RuntimeError("Valores SBS fuera de rango de control")
    return out


def fetch_requests() -> str:
    r = requests.get(SBS_URL, headers=HEADERS, timeout=45)
    r.raise_for_status()
    text = r.text
    low = text.lower()
    if "incapsula" in low or "request unsuccessful" in low or "profuturo" not in low:
        raise RuntimeError("SBS bloqueó la consulta HTTP directa")
    return text


def fetch_selenium() -> str:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait

    options = webdriver.ChromeOptions()
    for arg in (
        "--headless=new",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-gpu",
        "--window-size=1920,1080",
        "--lang=es-PE",
    ):
        options.add_argument(arg)

    driver = webdriver.Chrome(options=options)
    try:
        driver.get(SBS_URL)
        WebDriverWait(driver, 35).until(
            lambda d: "PROFUTURO" in d.find_element(By.TAG_NAME, "body").text
            and "Información al" in d.find_element(By.TAG_NAME, "body").text
        )
        return driver.page_source
    finally:
        driver.quit()


def load_saved() -> pd.DataFrame:
    if not CSV_PATH.exists():
        return pd.DataFrame(columns=["fecha", "valor_cuota"])
    df = pd.read_csv(CSV_PATH)
    df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce")
    df["valor_cuota"] = pd.to_numeric(df["valor_cuota"], errors="coerce")
    return df.dropna().sort_values("fecha").drop_duplicates("fecha", keep="last")


def save_csv(df: pd.DataFrame) -> None:
    out = df.copy().sort_values("fecha").drop_duplicates("fecha", keep="last")
    out["fecha"] = pd.to_datetime(out["fecha"]).dt.strftime("%Y-%m-%d")
    out.to_csv(CSV_PATH, index=False, encoding="utf-8")


def sync_public_series(sbs: pd.DataFrame) -> None:
    """Mantiene el gráfico VC real vs estimado alineado al CSV SBS vigente."""
    if SERIES_PATH.exists():
        series = json.loads(SERIES_PATH.read_text(encoding="utf-8"))
    else:
        series = []

    if SIGNALS_PATH.exists():
        signals = json.loads(SIGNALS_PATH.read_text(encoding="utf-8"))
    else:
        signals = []

    signal_by_date = {
        str(row.get("fecha", ""))[:10]: row
        for row in signals
        if isinstance(row, dict) and row.get("fecha")
    }
    by_date: dict[str, dict[str, object]] = {}
    for row in series:
        if isinstance(row, dict) and row.get("fecha"):
            by_date[str(row["fecha"])[:10]] = dict(row)

    official_dates = {
        pd.Timestamp(row["fecha"]).strftime("%Y-%m-%d")
        for _, row in sbs.dropna(subset=["fecha", "valor_cuota"]).iterrows()
    }

    # Si una fecha quedó antes como SBS por una comparación manual, se retira
    # mientras no exista en el CSV oficial confirmado por esta sincronización.
    for date_value in COMPARISON_ONLY_DATES:
        key = date_value.strftime("%Y-%m-%d")
        if key not in official_dates and key in by_date and by_date[key].get("fuente") == "SBS OFICIAL":
            del by_date[key]

    for _, row in sbs.dropna(subset=["fecha", "valor_cuota"]).iterrows():
        fecha = pd.Timestamp(row["fecha"]).strftime("%Y-%m-%d")
        value = float(row["valor_cuota"])
        old = by_date.get(fecha, {})
        sig = signal_by_date.get(fecha, {})
        by_date[fecha] = {
            "fecha": fecha,
            "vc": value,
            "fuente": "SBS OFICIAL",
            "senal": old.get("senal") if old.get("senal") is not None else sig.get("senal"),
            "ret_estimado": old.get("ret_estimado") if old.get("ret_estimado") is not None else sig.get("ret_estimado"),
        }

    out = [by_date[key] for key in sorted(by_date)]
    SERIES_PATH.parent.mkdir(parents=True, exist_ok=True)
    SERIES_PATH.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    latest = sbs.sort_values("fecha").iloc[-1]
    latest_date = pd.Timestamp(latest["fecha"]).strftime("%Y-%m-%d")
    latest_vc = float(latest["valor_cuota"])
    published = by_date.get(latest_date)
    if not published or published.get("fuente") != "SBS OFICIAL" or abs(float(published.get("vc")) - latest_vc) > 1e-10:
        raise RuntimeError("series.json no quedó sincronizado con el último SBS")
    print(f"Gráfico SBS sincronizado hasta {latest_date} · VC {latest_vc:.7f}")


def main() -> None:
    method = "REQUESTS"
    try:
        html = fetch_requests()
    except Exception as first:
        print(f"SBS requests no disponible: {type(first).__name__}: {first}")
        method = "SELENIUM"
        html = fetch_selenium()

    remote = parse_sbs_html(html)
    saved = load_saved()
    remote_dates = set(pd.to_datetime(remote["fecha"]))

    for date_value in COMPARISON_ONLY_DATES:
        if date_value not in remote_dates:
            saved = saved.loc[saved["fecha"] != date_value].copy()

    latest_remote = remote.iloc[-1]
    remote_date = pd.Timestamp(latest_remote["fecha"])
    remote_vc = float(latest_remote["valor_cuota"])
    saved_date = pd.Timestamp(saved["fecha"].max()) if not saved.empty else pd.NaT

    merged = pd.concat([saved, remote], ignore_index=True)
    merged["fecha"] = pd.to_datetime(merged["fecha"], errors="coerce")
    merged["valor_cuota"] = pd.to_numeric(merged["valor_cuota"], errors="coerce")
    merged = merged.dropna().sort_values("fecha").drop_duplicates("fecha", keep="last")
    save_csv(merged)

    # Importante: el gráfico principal usa public/data/series.json, no lee el CSV
    # SBS directamente. Por eso se actualiza en la misma ejecución.
    sync_public_series(merged)

    status = {
        "checked_at_lima": datetime.now(LIMA).isoformat(),
        "source": "SBS OFICIAL · Información Diaria de las Principales Variables del SPP",
        "method": method,
        "latest_remote_date": remote_date.strftime("%Y-%m-%d"),
        "latest_remote_vc_profuturo_f3": remote_vc,
        "previous_saved_date": None if pd.isna(saved_date) else saved_date.strftime("%Y-%m-%d"),
        "updated": bool(pd.isna(saved_date) or remote_date > saved_date),
        "comparison_only_dates": [d.strftime("%Y-%m-%d") for d in sorted(COMPARISON_ONLY_DATES)],
        "url": SBS_URL,
    }
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(status, ensure_ascii=False))


if __name__ == "__main__":
    main()
