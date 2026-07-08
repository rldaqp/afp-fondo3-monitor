from __future__ import annotations

import re
from datetime import datetime
from io import StringIO
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup

SBS_URL = "https://www.sbs.gob.pe/app/spp/variablesSPP_net/PagSS/variables_spp.aspx"
AFPS = ("HABITAT", "INTEGRA", "PROFUTURO", "PRIMA")

# Captura números con decimales, por ejemplo:
# 181,030,714.08 | 6,071,238,455.09 | 33.5370629
NUMBER_RE = re.compile(r"\d{1,3}(?:,\d{3})*\.\d+|\d+\.\d+")


def descargar_html(url: str = SBS_URL, timeout: int = 30) -> str:
    """Descarga la página de variables diarias de la SBS."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/149 Safari/537.36"
        )
    }

    response = requests.get(url, headers=headers, timeout=timeout)
    response.raise_for_status()
    response.encoding = response.apparent_encoding
    return response.text


def _a_float(valor: str) -> float:
    return float(valor.replace(",", ""))


def extraer_fondo3_reciente(html: str) -> pd.DataFrame:
    """
    Extrae los valores cuota del Fondo 3 de las cuatro AFP para las fechas
    recientes mostradas en la página de la SBS.

    La página repite, por cada fecha:
    Fondo 1: cuotas, fondo, valor cuota
    Fondo 2: cuotas, fondo, valor cuota
    Fondo 3: cuotas, fondo, valor cuota
    Fondo 0: cuotas, fondo, valor cuota

    Por ello, dentro de cada AFP el valor cuota del Fondo 3 es el noveno
    valor numérico de la secuencia (posición 8 contando desde cero).
    """
    soup = BeautifulSoup(html, "lxml")
    texto = soup.get_text(" ", strip=True)
    texto = re.sub(r"\s+", " ", texto)

    fechas = list(
        re.finditer(
            r"Información\s+al\s+(\d{2}/\d{2}/\d{4})",
            texto,
            flags=re.IGNORECASE,
        )
    )

    if not fechas:
        raise ValueError(
            "No se encontraron bloques 'Información al dd/mm/aaaa'. "
            "La SBS pudo haber cambiado el formato de la página."
        )

    fecha_descarga = datetime.now().astimezone()
    filas: list[dict] = []

    for i, coincidencia_fecha in enumerate(fechas):
        fecha_texto = coincidencia_fecha.group(1)
        inicio = coincidencia_fecha.end()
        fin = fechas[i + 1].start() if i + 1 < len(fechas) else len(texto)
        bloque = texto[inicio:fin]

        posiciones: list[tuple[int, str]] = []
        for afp in AFPS:
            encontrado = re.search(rf"\b{re.escape(afp)}\b", bloque)
            if encontrado:
                posiciones.append((encontrado.start(), afp))

        posiciones.sort()

        for j, (posicion, afp) in enumerate(posiciones):
            inicio_afp = posicion + len(afp)
            fin_afp = (
                posiciones[j + 1][0]
                if j + 1 < len(posiciones)
                else len(bloque)
            )
            bloque_afp = bloque[inicio_afp:fin_afp]
            numeros = NUMBER_RE.findall(bloque_afp)

            if len(numeros) < 9:
                print(
                    f"Advertencia: {afp} {fecha_texto} tiene "
                    f"{len(numeros)} números; se esperaban al menos 9."
                )
                continue

            valor_cuota_fondo3 = _a_float(numeros[8])

            filas.append(
                {
                    "fecha_valor": pd.to_datetime(
                        fecha_texto, format="%d/%m/%Y"
                    ),
                    "afp": afp.title(),
                    "fondo": 3,
                    "valor_cuota": valor_cuota_fondo3,
                    "fecha_descarga": fecha_descarga.isoformat(),
                    "fuente_url": SBS_URL,
                    "estado": "oficial",
                }
            )

    if not filas:
        raise ValueError(
            "No se pudo extraer ningún valor cuota del Fondo 3."
        )

    resultado = pd.DataFrame(filas)
    resultado = resultado.sort_values(["fecha_valor", "afp"])
    resultado = resultado.reset_index(drop=True)
    return resultado


def guardar_resultados(
    df: pd.DataFrame,
    carpeta_raiz: str | Path = ".",
) -> tuple[Path, Path]:
    """
    Guarda:
    1. Una captura individual con fecha y hora.
    2. Un archivo maestro acumulativo de versiones ('vintages').
    """
    raiz = Path(carpeta_raiz)
    raw_dir = raiz / "data" / "raw" / "sbs"
    processed_dir = raiz / "data" / "processed"
    raw_dir.mkdir(parents=True, exist_ok=True)
    processed_dir.mkdir(parents=True, exist_ok=True)

    sello = datetime.now().strftime("%Y%m%d_%H%M%S")
    captura = raw_dir / f"sbs_fondo3_{sello}.csv"
    maestro = processed_dir / "sbs_fondo3_vintages.csv"

    df.to_csv(captura, index=False, encoding="utf-8-sig")

    if maestro.exists():
        anterior = pd.read_csv(
            maestro,
            parse_dates=["fecha_valor"],
        )
        combinado = pd.concat([anterior, df], ignore_index=True)
    else:
        combinado = df.copy()

    # Evita duplicar una misma observación dentro de la misma descarga.
    combinado = combinado.drop_duplicates(
        subset=["fecha_valor", "afp", "fecha_descarga"],
        keep="last",
    )
    combinado = combinado.sort_values(
        ["fecha_descarga", "fecha_valor", "afp"]
    )
    combinado.to_csv(maestro, index=False, encoding="utf-8-sig")

    return captura, maestro


def ejecutar(carpeta_raiz: str | Path = ".") -> pd.DataFrame:
    html = descargar_html()
    datos = extraer_fondo3_reciente(html)
    captura, maestro = guardar_resultados(datos, carpeta_raiz)

    print("\nExtracción completada.")
    print(f"Observaciones: {len(datos)}")
    print(
        "Rango de fechas:",
        datos["fecha_valor"].min().date(),
        "a",
        datos["fecha_valor"].max().date(),
    )
    print(f"Captura: {captura.resolve()}")
    print(f"Maestro: {maestro.resolve()}")
    print("\nÚltimos valores:")
    print(
        datos.sort_values("fecha_valor")
        .groupby("afp", as_index=False)
        .tail(1)[["fecha_valor", "afp", "valor_cuota"]]
        .to_string(index=False)
    )
    return datos


if __name__ == "__main__":
    ejecutar(Path(__file__).resolve().parents[1])
