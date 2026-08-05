"""Valida que Hábitat use VC SBS oficiales y un único estimador OLS."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "rolling90"
PUBLIC = ROOT / "public" / "habitat"
PUBLIC_DATA = PUBLIC / "data"


def read_csv(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    frame["fecha"] = pd.to_datetime(frame["fecha"], errors="coerce")
    return frame.dropna(subset=["fecha"]).sort_values("fecha").drop_duplicates("fecha")


def read_json(name: str):
    return json.loads((PUBLIC_DATA / name).read_text(encoding="utf-8"))


def main() -> None:
    required = [
        DATA / "sbs_habitat_f3.csv",
        DATA / "sbs_habitat_f3_daily.csv",
        PUBLIC / "index.html",
        PUBLIC_DATA / "latest.json",
        PUBLIC_DATA / "series.json",
        PUBLIC_DATA / "signals.json",
        PUBLIC_DATA / "operation_series.json",
        PUBLIC_DATA / "model_insights.json",
        PUBLIC_DATA / "live_market.json",
    ]
    for path in required:
        if not path.exists() or path.stat().st_size == 0:
            raise AssertionError(f"Falta archivo de Hábitat: {path.relative_to(ROOT)}")

    history = read_csv(DATA / "sbs_habitat_f3.csv")
    profuturo_calendar = read_csv(DATA / "sbs_profuturo_f3.csv")
    daily = read_csv(DATA / "sbs_habitat_f3_daily.csv")
    latest = read_json("latest.json")
    series = read_json("series.json")
    signals = read_json("signals.json")
    operation = read_json("operation_series.json")
    insights = read_json("model_insights.json")
    html = (PUBLIC / "index.html").read_text(encoding="utf-8")

    if len(history) < 90 or not history["fecha"].is_unique:
        raise AssertionError("El histórico oficial de Hábitat es insuficiente o tiene duplicados.")
    if not pd.to_numeric(history["valor_cuota"], errors="coerce").gt(0).all():
        raise AssertionError("El histórico de Hábitat contiene VC inválidos.")

    start = pd.Timestamp("2026-07-01")
    end = pd.Timestamp("2026-07-29")
    expected = set(
        profuturo_calendar.loc[
            profuturo_calendar["fecha"].between(start, end), "fecha"
        ].dt.normalize()
    )
    official = set(
        history.loc[history["fecha"].between(start, end), "fecha"].dt.normalize()
    )
    missing = sorted(expected - official)
    if missing:
        raise AssertionError(
            "Faltan VC oficiales de Hábitat: "
            + ", ".join(date.strftime("%Y-%m-%d") for date in missing)
        )

    series_by_date = {
        pd.Timestamp(row["fecha"]).normalize(): row
        for row in series
    }
    for date in expected:
        row = series_by_date.get(date)
        if not row:
            raise AssertionError(f"La serie no contiene {date:%Y-%m-%d}.")
        if row.get("fuente") != "SBS OFICIAL" or row.get("es_oficial") is not True:
            raise AssertionError(f"{date:%Y-%m-%d} no está marcado como SBS oficial: {row}")
        if float(row["vc"]) <= 0:
            raise AssertionError(f"VC oficial inválido en {date:%Y-%m-%d}.")

    if any(row.get("tipo") == "SBS_PENDIENTE" for row in signals):
        raise AssertionError("Persisten señales SBS_PENDIENTE.")
    if any("SBS PENDIENTE" in str(row.get("fuente", "")).upper() for row in series):
        raise AssertionError("Persisten VC provisionales dentro del histórico oficial.")
    if latest.get("official_gap_dates"):
        raise AssertionError("latest.json todavía declara fechas oficiales faltantes.")
    if int(latest.get("estimated_gap_count", 0)) != 0:
        raise AssertionError("latest.json todavía declara VC de julio estimados.")

    if latest.get("afp") != "Hábitat" or int(latest.get("fund", 0)) != 3:
        raise AssertionError("La cabecera no corresponde a Hábitat Fondo 3.")
    if latest.get("model") != "OLS rolling 90":
        raise AssertionError("Hábitat no está usando OLS rolling 90.")
    if int(latest.get("window", 0)) != 90 or int(latest.get("training_n", 0)) != 90:
        raise AssertionError("La ventana OLS de Hábitat no tiene 90 observaciones.")
    if abs(float(latest.get("threshold", 0)) - 0.001) > 1e-12:
        raise AssertionError("El umbral de señal no es 0.1 %.")
    if latest.get("parity_verified") is not True or latest.get("methodology_parity_verified") is not True:
        raise AssertionError("No se verificó la metodología OLS de Hábitat.")
    if latest.get("model_factors") != ["SPY", "NEM", "FCX", "EPU", "MCHI", "EEM", "USD_PEN"]:
        raise AssertionError("Los siete factores del OLS no coinciden.")
    if latest.get("latest_sbs_date") != daily.iloc[-1]["fecha"].strftime("%Y-%m-%d"):
        raise AssertionError("El último VC SBS no coincide con la fuente diaria.")
    if float(latest.get("latest_sbs_vc", 0)) <= 0 or float(latest.get("latest_estimated_vc", 0)) <= 0:
        raise AssertionError("La cabecera contiene VC inválidos.")
    if latest.get("signal") not in {"SUBE", "NEUTRO", "BAJA"}:
        raise AssertionError("La señal OLS es inválida.")

    historical = [row for row in signals if row.get("tipo") == "HISTORICO"]
    if not historical:
        raise AssertionError("No hay predicciones históricas OLS.")
    if not all(row.get("vc_real") is not None and row.get("vc_estimado") is not None for row in historical):
        raise AssertionError("Hay comparaciones históricas incompletas.")
    if not all(row.get("senal") in {"SUBE", "NEUTRO", "BAJA"} for row in signals):
        raise AssertionError("Hay señales fuera de las categorías permitidas.")
    if len(series) < len(history) or len(operation) != len(series):
        raise AssertionError("Las series operativas no coinciden.")
    if int(insights["quality"]["training_n"]) != 90 or insights["quality"]["status"] != "OK":
        raise AssertionError("La calidad del OLS de Hábitat no está en estado OK.")
    if insights["challenger_huber"]["status"] != "NO APLICA EN HÁBITAT":
        raise AssertionError("Se activó un modelo distinto de OLS.")

    required_html = [
        "Hábitat Fondo 3",
        "VC real vs VC estimado",
        "Indicadores oficiales SBS del Fondo 3",
        "HABITAT_CHART_OFFICIAL_VS_OLS_V6",
        "VC SBS real (oficial)",
        "VC estimado OLS",
    ]
    for marker in required_html:
        if marker not in html:
            raise AssertionError(f"El visor no contiene: {marker}")
    forbidden_html = ["VC provisional · SBS pendiente", "Tramo SBS pendiente"]
    for marker in forbidden_html:
        if marker in html:
            raise AssertionError(f"El visor conserva texto provisional: {marker}")

    print(f"VC oficiales Hábitat: {len(history)}")
    print(f"Fechas oficiales de julio verificadas: {len(expected)}")
    print(f"Predicciones OLS disponibles: {len(signals)}")
    print(json.dumps(latest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
