from __future__ import annotations

import argparse
import re
from datetime import datetime
from io import BytesIO
from pathlib import Path
from urllib.parse import unquote, urljoin

import pandas as pd
import requests
from bs4 import BeautifulSoup


PAGINA_SBS = (
    "https://www.sbs.gob.pe/app/stats_net/stats/"
    "EstadisticaSistemaFinancieroResultados.aspx?c=FP-1356"
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

PALABRAS_CLAVE = [
    "fondo tipo 3",
    "fondo 3",
    "habitat",
    "integra",
    "prima",
    "profuturo",
    "instrumento",
    "cartera",
    "monto",
    "participacion",
    "participación",
]


def crear_sesion() -> requests.Session:
    sesion = requests.Session()
    sesion.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/149 Safari/537.36"
            )
        }
    )
    return sesion


def obtener_enlaces(
    sesion: requests.Session,
    anio_desde: int,
    anio_hasta: int,
) -> list[dict]:
    respuesta = sesion.get(PAGINA_SBS, timeout=60)
    respuesta.raise_for_status()

    soup = BeautifulSoup(respuesta.text, "lxml")
    registros: list[dict] = []

    for enlace in soup.find_all("a", href=True):
        href = unquote(enlace["href"])
        url = urljoin(PAGINA_SBS, href)
        url_min = url.lower()

        if "fp-1356" not in url_min:
            continue
        if not url_min.endswith((".xls", ".xlsx")):
            continue

        coincidencia_anio = re.search(r"/(20\d{2})/", url)
        if not coincidencia_anio:
            continue

        anio = int(coincidencia_anio.group(1))
        if not (anio_desde <= anio <= anio_hasta):
            continue

        mes = None
        mes_nombre = None

        for nombre, numero in MESES.items():
            if f"/{nombre}/" in url_min:
                mes = numero
                mes_nombre = nombre.capitalize()
                break

        if mes is None:
            texto = enlace.get_text(" ", strip=True).lower()
            for nombre, numero in MESES.items():
                if nombre in texto:
                    mes = numero
                    mes_nombre = nombre.capitalize()
                    break

        if mes is None:
            continue

        registros.append(
            {
                "anio": anio,
                "mes": mes,
                "mes_nombre": mes_nombre,
                "url": url,
                "archivo": Path(url.split("?")[0]).name,
            }
        )

    unicos = {registro["url"]: registro for registro in registros}
    resultado = sorted(
        unicos.values(),
        key=lambda x: (x["anio"], x["mes"], x["archivo"]),
    )

    if not resultado:
        raise RuntimeError(
            "No se encontraron archivos FP-1356 en la página de la SBS."
        )

    return resultado


def descargar(
    sesion: requests.Session,
    registro: dict,
    carpeta: Path,
    reemplazar: bool,
) -> Path:
    carpeta.mkdir(parents=True, exist_ok=True)
    destino = carpeta / registro["archivo"]

    if (
        destino.exists()
        and destino.stat().st_size > 1_000
        and not reemplazar
    ):
        return destino

    respuesta = sesion.get(
        registro["url"],
        timeout=120,
        allow_redirects=True,
        headers={"Referer": PAGINA_SBS},
    )
    respuesta.raise_for_status()

    contenido = respuesta.content

    if len(contenido) < 1_000:
        raise RuntimeError(
            f"{registro['archivo']} es demasiado pequeño "
            "y podría ser una página de error."
        )

    destino.write_bytes(contenido)
    return destino


def preparar_excel(archivo: Path) -> tuple[BytesIO, str, str]:
    contenido = archivo.read_bytes()

    if contenido.startswith(b"PK"):
        return BytesIO(contenido), "openpyxl", "xlsx_real"

    firma_xls = bytes.fromhex("D0CF11E0A1B11AE1")
    if contenido.startswith(firma_xls):
        return BytesIO(contenido), "xlrd", "xls_real"

    inicio = contenido[:500].lower()
    if b"<html" in inicio or b"<!doctype html" in inicio:
        raise ValueError(
            "El archivo descargado contiene HTML y no un libro Excel."
        )

    raise ValueError(
        "La firma binaria no corresponde a un XLS ni XLSX reconocido."
    )


def normalizar_texto(valor: object) -> str:
    if pd.isna(valor):
        return ""
    return re.sub(r"\s+", " ", str(valor)).strip()


def inspeccionar_archivo(
    archivo: Path,
    registro: dict,
) -> tuple[list[dict], list[dict]]:
    fuente, motor, formato_real = preparar_excel(archivo)
    libro = pd.ExcelFile(fuente, engine=motor)

    hojas: list[dict] = []
    coincidencias: list[dict] = []

    for hoja in libro.sheet_names:
        fuente_hoja, motor_hoja, _ = preparar_excel(archivo)

        tabla = pd.read_excel(
            fuente_hoja,
            sheet_name=hoja,
            header=None,
            engine=motor_hoja,
            nrows=80,
        )

        filas = int(tabla.shape[0])
        columnas = int(tabla.shape[1])

        texto_completo = " ".join(
            normalizar_texto(valor).lower()
            for valor in tabla.to_numpy().ravel()
        )

        palabras_detectadas = [
            palabra
            for palabra in PALABRAS_CLAVE
            if palabra in texto_completo
        ]

        hojas.append(
            {
                "anio": registro["anio"],
                "mes": registro["mes"],
                "archivo": archivo.name,
                "formato_real": formato_real,
                "hoja": hoja,
                "filas_leidas": filas,
                "columnas_leidas": columnas,
                "palabras_detectadas": " | ".join(
                    palabras_detectadas
                ),
                "posible_hoja_fondo3": any(
                    palabra in palabras_detectadas
                    for palabra in [
                        "fondo tipo 3",
                        "fondo 3",
                        "habitat",
                        "integra",
                        "prima",
                        "profuturo",
                    ]
                ),
            }
        )

        limite_filas = min(60, filas)
        limite_columnas = min(30, columnas)

        for i in range(limite_filas):
            for j in range(limite_columnas):
                valor = normalizar_texto(tabla.iat[i, j])
                valor_min = valor.lower()

                claves_celda = [
                    palabra
                    for palabra in PALABRAS_CLAVE
                    if palabra in valor_min
                ]

                if claves_celda:
                    coincidencias.append(
                        {
                            "anio": registro["anio"],
                            "mes": registro["mes"],
                            "archivo": archivo.name,
                            "hoja": hoja,
                            "fila_excel_aprox": i + 1,
                            "columna_excel_aprox": j + 1,
                            "valor": valor,
                            "palabras_detectadas": " | ".join(
                                claves_celda
                            ),
                        }
                    )

    return hojas, coincidencias


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Descarga e inspecciona archivos SBS FP-1356 para "
            "identificar la estructura de cartera del Fondo 3."
        )
    )
    parser.add_argument(
        "--anio-desde",
        type=int,
        default=2015,
    )
    parser.add_argument(
        "--anio-hasta",
        type=int,
        default=datetime.now().year,
    )
    parser.add_argument(
        "--ultimos",
        type=int,
        default=3,
        help=(
            "Cantidad de archivos más recientes a descargar e inspeccionar. "
            "Use 0 para procesar todos."
        ),
    )
    parser.add_argument(
        "--reemplazar",
        action="store_true",
    )
    args = parser.parse_args()

    raiz = Path(__file__).resolve().parents[1]
    carpeta_raw = (
        raiz / "data" / "raw" / "sbs" / "fp1356_cartera"
    )
    carpeta_processed = raiz / "data" / "processed"
    carpeta_processed.mkdir(parents=True, exist_ok=True)

    sesion = crear_sesion()

    print("Leyendo la página oficial de la SBS...")
    enlaces = obtener_enlaces(
        sesion,
        args.anio_desde,
        args.anio_hasta,
    )

    print(f"Archivos FP-1356 encontrados: {len(enlaces)}")

    inventario_enlaces = pd.DataFrame(enlaces)
    ruta_enlaces = (
        carpeta_processed / "fp1356_inventario_enlaces.csv"
    )
    inventario_enlaces.to_csv(
        ruta_enlaces,
        index=False,
        encoding="utf-8-sig",
    )

    seleccion = enlaces
    if args.ultimos > 0:
        seleccion = enlaces[-args.ultimos :]

    print(
        f"Archivos seleccionados para inspección: {len(seleccion)}"
    )

    inventario_archivos: list[dict] = []
    inventario_hojas: list[dict] = []
    coincidencias_total: list[dict] = []
    errores: list[dict] = []

    for numero, registro in enumerate(seleccion, start=1):
        print(
            f"\n[{numero}/{len(seleccion)}] "
            f"{registro['anio']}-{registro['mes']:02d} "
            f"{registro['archivo']}"
        )

        try:
            archivo = descargar(
                sesion,
                registro,
                carpeta_raw,
                args.reemplazar,
            )

            fuente, motor, formato_real = preparar_excel(archivo)
            libro = pd.ExcelFile(fuente, engine=motor)

            inventario_archivos.append(
                {
                    **registro,
                    "ruta_local": str(archivo.resolve()),
                    "tamano_bytes": archivo.stat().st_size,
                    "formato_real": formato_real,
                    "numero_hojas": len(libro.sheet_names),
                    "hojas": " | ".join(libro.sheet_names),
                    "estado": "correcto",
                    "error": "",
                }
            )

            hojas, coincidencias = inspeccionar_archivo(
                archivo,
                registro,
            )

            inventario_hojas.extend(hojas)
            coincidencias_total.extend(coincidencias)

            print(
                f"  Correcto: {formato_real} | "
                f"{len(libro.sheet_names)} hojas"
            )
            for hoja in hojas:
                marca = (
                    "POSIBLE FONDO 3"
                    if hoja["posible_hoja_fondo3"]
                    else ""
                )
                print(
                    f"   - {hoja['hoja']}: "
                    f"{hoja['filas_leidas']}x"
                    f"{hoja['columnas_leidas']} "
                    f"{marca}"
                )

        except Exception as error:
            mensaje = str(error)
            errores.append(
                {
                    **registro,
                    "error": mensaje,
                }
            )
            inventario_archivos.append(
                {
                    **registro,
                    "ruta_local": "",
                    "tamano_bytes": 0,
                    "formato_real": "",
                    "numero_hojas": 0,
                    "hojas": "",
                    "estado": "error",
                    "error": mensaje,
                }
            )
            print(f"  ERROR: {mensaje}")

    rutas = {
        "enlaces": ruta_enlaces,
        "archivos": (
            carpeta_processed
            / "fp1356_inventario_archivos_inspeccionados.csv"
        ),
        "hojas": (
            carpeta_processed
            / "fp1356_inventario_hojas.csv"
        ),
        "coincidencias": (
            carpeta_processed
            / "fp1356_coincidencias_estructura.csv"
        ),
        "errores": (
            carpeta_processed
            / "fp1356_errores_inspeccion.csv"
        ),
    }

    pd.DataFrame(inventario_archivos).to_csv(
        rutas["archivos"],
        index=False,
        encoding="utf-8-sig",
    )
    pd.DataFrame(inventario_hojas).to_csv(
        rutas["hojas"],
        index=False,
        encoding="utf-8-sig",
    )
    pd.DataFrame(coincidencias_total).to_csv(
        rutas["coincidencias"],
        index=False,
        encoding="utf-8-sig",
    )
    pd.DataFrame(errores).to_csv(
        rutas["errores"],
        index=False,
        encoding="utf-8-sig",
    )

    print("\nINSPECCIÓN TERMINADA")
    print("=" * 90)
    print(f"Archivos encontrados en la web: {len(enlaces)}")
    print(f"Archivos inspeccionados: {len(seleccion)}")
    print(
        "Archivos correctos:",
        sum(
            1
            for fila in inventario_archivos
            if fila["estado"] == "correcto"
        ),
    )
    print(f"Archivos con error: {len(errores)}")
    print(
        "Coincidencias de estructura encontradas:",
        len(coincidencias_total),
    )

    print("\nArchivos creados:")
    for ruta in rutas.values():
        print(f" - {ruta.resolve()}")

    print(
        "\nSiguiente paso:\n"
        "Comparte el bloque mostrado en PowerShell y, si se solicita, "
        "el archivo fp1356_coincidencias_estructura.csv. "
        "Con esa evidencia se construirá el parser definitivo sin "
        "suponer la estructura del Excel."
    )


if __name__ == "__main__":
    main()
