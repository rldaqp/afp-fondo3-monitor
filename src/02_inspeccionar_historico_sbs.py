from __future__ import annotations

import argparse
import re
from pathlib import Path
from urllib.parse import urljoin, unquote

import pandas as pd
import requests
from bs4 import BeautifulSoup

PAGINA_SBS = (
    "https://www.sbs.gob.pe/app/stats_net/stats/"
    "EstadisticaSistemaFinancieroResultados.aspx?c=FP-1359"
)

MESES = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "setiembre": 9,
    "septiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}


def obtener_enlaces_excel() -> list[dict]:
    """Obtiene desde la página oficial los archivos mensuales FP-1359."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/149 Safari/537.36"
        )
    }

    respuesta = requests.get(PAGINA_SBS, headers=headers, timeout=40)
    respuesta.raise_for_status()

    soup = BeautifulSoup(respuesta.text, "lxml")
    resultados: list[dict] = []

    for enlace in soup.find_all("a", href=True):
        href = enlace["href"]
        href_decodificado = unquote(href)

        if "FP-1359" not in href_decodificado.upper():
            continue
        if not href_decodificado.lower().endswith((".xls", ".xlsx")):
            continue

        url = urljoin(PAGINA_SBS, href)
        texto = enlace.get_text(" ", strip=True)

        coincidencia_anio = re.search(r"/(20\d{2})/", url)
        anio = int(coincidencia_anio.group(1)) if coincidencia_anio else None

        mes_nombre = None
        mes_numero = None
        for nombre, numero in MESES.items():
            if f"/{nombre}/" in url.lower():
                mes_nombre = nombre.capitalize()
                mes_numero = numero
                break

        resultados.append(
            {
                "anio": anio,
                "mes": mes_numero,
                "mes_nombre": mes_nombre or texto,
                "url": url,
                "archivo": Path(url.split("?")[0]).name,
            }
        )

    # Quitar duplicados y ordenar.
    unicos = {(r["url"]): r for r in resultados}
    ordenados = sorted(
        unicos.values(),
        key=lambda r: (
            r["anio"] or 0,
            r["mes"] or 0,
            r["archivo"],
        ),
    )

    if not ordenados:
        raise RuntimeError(
            "No se encontraron archivos FP-1359 en la página oficial. "
            "La SBS pudo haber cambiado la estructura del portal."
        )

    return ordenados


def seleccionar_archivo(
    enlaces: list[dict],
    anio: int | None,
    mes: int | None,
) -> dict:
    """Selecciona un archivo específico o, por defecto, el más reciente."""
    candidatos = enlaces

    if anio is not None:
        candidatos = [x for x in candidatos if x["anio"] == anio]

    if mes is not None:
        candidatos = [x for x in candidatos if x["mes"] == mes]

    if not candidatos:
        raise ValueError(
            f"No se encontró un archivo para año={anio}, mes={mes}."
        )

    return candidatos[-1]


def descargar_archivo(
    registro: dict,
    carpeta_salida: Path,
) -> Path:
    """Descarga el Excel seleccionado."""
    carpeta_salida.mkdir(parents=True, exist_ok=True)
    destino = carpeta_salida / registro["archivo"]

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/149 Safari/537.36"
        ),
        "Referer": PAGINA_SBS,
    }

    respuesta = requests.get(
        registro["url"],
        headers=headers,
        timeout=60,
        allow_redirects=True,
    )
    respuesta.raise_for_status()

    if len(respuesta.content) < 1_000:
        raise RuntimeError(
            "El archivo descargado es demasiado pequeño. "
            "Puede ser una página de error en lugar del Excel."
        )

    destino.write_bytes(respuesta.content)
    return destino


def inspeccionar_excel(archivo: Path, carpeta_salida: Path) -> None:
    """
    Muestra la estructura del libro y guarda una vista previa de cada hoja.
    Este paso permite diseñar el parser histórico sin adivinar columnas.
    """
    carpeta_salida.mkdir(parents=True, exist_ok=True)

    motor = "xlrd" if archivo.suffix.lower() == ".xls" else "openpyxl"
    libro = pd.ExcelFile(archivo, engine=motor)

    print("\nHojas encontradas:")
    for hoja in libro.sheet_names:
        print(f" - {hoja}")

    for numero, hoja in enumerate(libro.sheet_names, start=1):
        tabla = pd.read_excel(
            archivo,
            sheet_name=hoja,
            header=None,
            engine=motor,
        )

        nombre_seguro = re.sub(r"[^A-Za-z0-9_-]+", "_", hoja).strip("_")
        vista = carpeta_salida / (
            f"{archivo.stem}_hoja_{numero:02d}_{nombre_seguro}_vista.csv"
        )

        tabla.head(40).to_csv(
            vista,
            index=False,
            header=False,
            encoding="utf-8-sig",
        )

        print("\n" + "=" * 78)
        print(f"HOJA: {hoja}")
        print(f"Dimensiones: {tabla.shape[0]} filas x {tabla.shape[1]} columnas")
        print(f"Vista previa guardada en: {vista.resolve()}")
        print("-" * 78)

        with pd.option_context(
            "display.max_rows", 25,
            "display.max_columns", 20,
            "display.width", 220,
            "display.max_colwidth", 45,
        ):
            print(tabla.head(25).to_string(index=True, header=False))


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Descarga e inspecciona un archivo mensual oficial de "
            "Valor Cuota por AFP y Tipo de Fondo (FP-1359)."
        )
    )
    parser.add_argument(
        "--anio",
        type=int,
        default=None,
        help="Año a descargar. Si se omite, usa el archivo más reciente.",
    )
    parser.add_argument(
        "--mes",
        type=int,
        choices=range(1, 13),
        default=None,
        help="Mes numérico, por ejemplo 5 para mayo.",
    )
    args = parser.parse_args()

    raiz = Path(__file__).resolve().parents[1]
    carpeta_excel = raiz / "data" / "raw" / "sbs" / "historico"
    carpeta_vistas = raiz / "data" / "processed" / "vistas_historico"

    print("Buscando archivos mensuales oficiales de la SBS...")
    enlaces = obtener_enlaces_excel()

    print(f"Archivos encontrados: {len(enlaces)}")
    print(
        "Rango detectado:",
        f"{enlaces[0]['mes_nombre']} {enlaces[0]['anio']}",
        "a",
        f"{enlaces[-1]['mes_nombre']} {enlaces[-1]['anio']}",
    )

    elegido = seleccionar_archivo(enlaces, args.anio, args.mes)

    print("\nArchivo seleccionado:")
    print(
        f"  Periodo: {elegido['mes_nombre']} {elegido['anio']}\n"
        f"  Archivo: {elegido['archivo']}"
    )

    archivo = descargar_archivo(elegido, carpeta_excel)

    print("\nDescarga completada:")
    print(f"  {archivo.resolve()}")
    print(f"  Tamaño: {archivo.stat().st_size:,} bytes")

    inspeccionar_excel(archivo, carpeta_vistas)

    print("\nInspección terminada correctamente.")
    print(
        "Comparte la parte de PowerShell que empieza en 'HOJA:' "
        "para construir el parser histórico exacto."
    )


if __name__ == "__main__":
    main()
