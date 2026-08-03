from __future__ import annotations

import io
import re
import unicodedata
from pathlib import Path
from urllib.parse import urljoin

import pandas as pd
import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "rolling90"
HISTORY_PATH = DATA / "sbs_habitat_f3.csv"
DAILY_PATH = DATA / "sbs_habitat_f3_daily.csv"
PROFUTURO_PATH = DATA / "sbs_profuturo_f3.csv"

SBS_INDEX = (
    "https://www.sbs.gob.pe/app/stats_net/stats/"
    "EstadisticaSistemaFinancieroResultados.aspx?c=FP-1359"
)
SBS_DAILY = "https://www.sbs.gob.pe/app/spp/variablesSPP_net/PagSS/variables_spp.aspx"
HEADERS = {"User-Agent": "Mozilla/5.0 AFP-Habitat-Fondo3-GitHubActions"}
DATE_RE = re.compile(r"\b(\d{2}/\d{2}/\d{4})\b")

MONTHS = {
    1: ("Enero", "en"),
    2: ("Febrero", "fe"),
    3: ("Marzo", "ma"),
    4: ("Abril", "ab"),
    5: ("Mayo", "my"),
    6: ("Junio", "jn"),
    7: ("Julio", "jl"),
    8: ("Agosto", "ag"),
    9: ("Setiembre", "se"),
    10: ("Octubre", "oc"),
    11: ("Noviembre", "no"),
    12: ("Diciembre", "di"),
}


def norm(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return " ".join(text.lower().split())


def parse_num(value: object) -> float | None:
    number = pd.to_numeric(
        str(value).replace("\xa0", "").replace(" ", "").replace(",", ""),
        errors="coerce",
    )
    return None if pd.isna(number) else float(number)


def nearest_date(row) -> pd.Timestamp | None:
    for previous in row.find_all_previous(string=True, limit=500):
        text = " ".join(str(previous).split())
        if "informacion al" not in norm(text):
            continue
        match = DATE_RE.search(text)
        if match:
            return pd.to_datetime(match.group(1), format="%d/%m/%Y")
    return None


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    frame = pd.read_csv(path)
    frame["fecha"] = pd.to_datetime(frame["fecha"], errors="coerce")
    return frame.dropna(subset=["fecha"])


def save_csv(frame: pd.DataFrame, path: Path) -> None:
    output = frame.copy()
    output["fecha"] = pd.to_datetime(output["fecha"]).dt.strftime("%Y-%m-%d")
    output.to_csv(path, index=False, encoding="utf-8")


def download_daily() -> pd.DataFrame:
    response = requests.get(SBS_DAILY, headers=HEADERS, timeout=60)
    response.raise_for_status()
    soup = BeautifulSoup(response.content, "lxml")
    rows: list[dict[str, object]] = []

    for row in soup.find_all("tr"):
        cells = row.find_all(["th", "td"], recursive=False)
        texts = [" ".join(cell.get_text(" ", strip=True).split()) for cell in cells]
        if not texts or norm(texts[0]) != "habitat" or len(texts) < 10:
            continue

        date = nearest_date(row)
        quotas = parse_num(texts[7])
        fund_value = parse_num(texts[8])
        unit_value = parse_num(texts[9])
        if date is None or quotas is None or fund_value is None or unit_value is None:
            continue

        rows.append(
            {
                "fecha": date,
                "cuotas_fondo": quotas,
                "valor_fondo": fund_value,
                "valor_cuota": unit_value,
            }
        )

    frame = pd.DataFrame(rows)
    if frame.empty:
        raise RuntimeError(
            "La tabla diaria de la SBS no devolvió registros de Hábitat Fondo 3."
        )

    frame["fecha"] = pd.to_datetime(frame["fecha"], errors="coerce")
    for column in ("cuotas_fondo", "valor_fondo", "valor_cuota"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = (
        frame.dropna()
        .sort_values("fecha")
        .drop_duplicates("fecha", keep="last")
        .reset_index(drop=True)
    )
    if frame.empty or not frame["valor_cuota"].gt(0).all():
        raise RuntimeError("Los registros diarios de la SBS son inválidos.")
    return frame


def month_url(year: int, month: int) -> str:
    folder, code = MONTHS[month]
    return (
        "https://intranet2.sbs.gob.pe/estadistica/financiera/"
        f"{year}/{folder}/FP-1359-{code}{year}.XLS"
    )


def discover_monthly_urls() -> list[str]:
    urls: set[str] = set()
    try:
        response = requests.get(SBS_INDEX, headers=HEADERS, timeout=60)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "lxml")
        for anchor in soup.find_all("a", href=True):
            url = urljoin(SBS_INDEX, anchor["href"])
            if "FP-1359" in url.upper() and url.lower().endswith(".xls"):
                urls.add(url)
    except Exception as exc:
        print(f"Índice SBS no disponible: {type(exc).__name__}: {exc}")

    today = pd.Timestamp.now(tz="America/Lima").tz_localize(None).normalize()
    # El enlace del mes corriente suele aparecer con rezago en el índice.
    # Por eso se prueba también la ruta oficial predecible del mes actual
    # y de los dos meses anteriores.
    for offset in range(0, 3):
        date = today - pd.DateOffset(months=offset)
        urls.add(month_url(int(date.year), int(date.month)))
    return sorted(urls)


def parse_habitat_monthly(content: bytes, source: str) -> pd.DataFrame:
    raw = pd.read_excel(
        io.BytesIO(content),
        sheet_name="VC-Diario-Fondo3",
        header=None,
        engine="xlrd",
    )
    header_row = next(
        row
        for row in range(min(30, len(raw)))
        if "dia" in [norm(value) for value in raw.iloc[row]]
        and "habitat" in [norm(value) for value in raw.iloc[row]]
    )
    header = [norm(value) for value in raw.iloc[header_row]]
    block = raw.iloc[
        header_row + 1 :,
        [header.index("dia"), header.index("habitat")],
    ].copy()
    block.columns = ["fecha", "valor_cuota"]
    block["fecha"] = pd.to_datetime(block["fecha"], errors="coerce")
    block["valor_cuota"] = pd.to_numeric(block["valor_cuota"], errors="coerce")
    block = block.dropna().sort_values("fecha").drop_duplicates("fecha", keep="last")
    if block.empty:
        raise RuntimeError(f"El Excel no contiene Hábitat Fondo 3: {source}")
    return block


def download_monthly_history() -> tuple[pd.DataFrame, list[str]]:
    session = requests.Session()
    session.headers.update(HEADERS)
    frames: list[pd.DataFrame] = []
    warnings: list[str] = []
    for url in discover_monthly_urls():
        try:
            response = session.get(url, timeout=75)
            if response.status_code == 404:
                continue
            response.raise_for_status()
            if len(response.content) < 5000:
                continue
            frames.append(parse_habitat_monthly(response.content, url))
            print(f"SBS mensual Hábitat descargada: {url}")
        except Exception as exc:
            warnings.append(f"{url}: {type(exc).__name__}")
    if not frames:
        return pd.DataFrame(columns=["fecha", "valor_cuota"]), warnings
    history = pd.concat(frames, ignore_index=True)
    history = history.sort_values("fecha").drop_duplicates("fecha", keep="last")
    return history.reset_index(drop=True), warnings


def validate_continuity(history: pd.DataFrame) -> None:
    profuturo = read_csv(PROFUTURO_PATH)
    if profuturo.empty or history.empty:
        return
    latest = pd.Timestamp(history["fecha"].max())
    start = max(pd.Timestamp("2026-07-01"), latest - pd.Timedelta(days=45))
    expected = set(
        profuturo.loc[
            profuturo["fecha"].between(start, latest, inclusive="both"),
            "fecha",
        ].dt.normalize()
    )
    present = set(
        history.loc[
            history["fecha"].between(start, latest, inclusive="both"),
            "fecha",
        ].dt.normalize()
    )
    missing = sorted(expected - present)
    if missing:
        dates = ", ".join(date.strftime("%Y-%m-%d") for date in missing[:20])
        raise RuntimeError(
            "El histórico SBS de Hábitat continúa incompleto. "
            f"Faltan fechas oficiales presentes en el calendario del Fondo 3: {dates}"
        )


def main() -> None:
    DATA.mkdir(parents=True, exist_ok=True)

    online_daily = download_daily()
    saved_daily = read_csv(DAILY_PATH)
    daily = pd.concat([saved_daily, online_daily], ignore_index=True, sort=False)
    daily = (
        daily.sort_values("fecha")
        .drop_duplicates("fecha", keep="last")
        .reset_index(drop=True)
    )
    save_csv(daily, DAILY_PATH)

    saved_history = read_csv(HISTORY_PATH)
    monthly, warnings = download_monthly_history()
    daily_vc = daily[["fecha", "valor_cuota"]].copy()
    frames = [
        frame[["fecha", "valor_cuota"]]
        for frame in (saved_history, monthly, daily_vc)
        if not frame.empty
    ]
    if not frames:
        raise RuntimeError("No existe ninguna serie SBS de Hábitat Fondo 3.")
    history = pd.concat(frames, ignore_index=True, sort=False)
    history["valor_cuota"] = pd.to_numeric(history["valor_cuota"], errors="coerce")
    history = (
        history.dropna()
        .sort_values("fecha")
        .drop_duplicates("fecha", keep="last")
        .reset_index(drop=True)
    )
    validate_continuity(history)
    save_csv(history, HISTORY_PATH)

    latest = daily.iloc[-1]
    print(
        "SBS Hábitat Fondo 3 consolidada: "
        f"{history['fecha'].min():%Y-%m-%d} -> {history['fecha'].max():%Y-%m-%d} · "
        f"{len(history)} registros · último VC {latest['valor_cuota']:.7f}"
    )
    if warnings:
        print("Avisos de archivos mensuales: " + " | ".join(warnings[-5:]))


if __name__ == "__main__":
    main()
