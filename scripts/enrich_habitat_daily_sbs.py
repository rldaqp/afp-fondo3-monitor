from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "rolling90"
HISTORY_PATH = DATA / "sbs_habitat_f3.csv"
DAILY_PATH = DATA / "sbs_habitat_f3_daily.csv"
SBS_DAILY = "https://www.sbs.gob.pe/app/spp/variablesSPP_net/PagSS/variables_spp.aspx"
HEADERS = {"User-Agent": "Mozilla/5.0 AFP-Habitat-Fondo3-GitHubActions"}
DATE_RE = re.compile(r"\b(\d{2}/\d{2}/\d{4})\b")


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
        raise RuntimeError("La tabla diaria de la SBS no devolvió registros de Hábitat Fondo 3.")

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


def main() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    online = download_daily()
    saved_daily = read_csv(DAILY_PATH)
    daily = pd.concat([saved_daily, online], ignore_index=True, sort=False)
    daily = daily.sort_values("fecha").drop_duplicates("fecha", keep="last").reset_index(drop=True)
    save_csv(daily, DAILY_PATH)

    history = read_csv(HISTORY_PATH)
    daily_vc = daily[["fecha", "valor_cuota"]].copy()
    merged = pd.concat([history[["fecha", "valor_cuota"]], daily_vc], ignore_index=True, sort=False)
    merged["valor_cuota"] = pd.to_numeric(merged["valor_cuota"], errors="coerce")
    merged = (
        merged.dropna()
        .sort_values("fecha")
        .drop_duplicates("fecha", keep="last")
        .reset_index(drop=True)
    )
    save_csv(merged, HISTORY_PATH)

    latest = daily.iloc[-1]
    print(
        "SBS diaria Hábitat Fondo 3: "
        f"{latest['fecha']:%Y-%m-%d} · VC {latest['valor_cuota']:.7f} · "
        f"cuotas {latest['cuotas_fondo']:.2f} · fondo S/ {latest['valor_fondo']:.2f}"
    )


if __name__ == "__main__":
    main()
