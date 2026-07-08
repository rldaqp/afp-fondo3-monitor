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
    "EstadisticaSistemaFinancieroResultados.aspx?c=CA-0001"
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
    "fondo de pensiones tipo 3",
    "fondo 3",
    "habitat",
    "integra",
    "prima",
    "profuturo",
    "emisor",
    "instrumento",
    "isin",
    "nemonico",
    "nemónico",
    "pais",
    "país",
    "moneda",
    "valor",
    "monto",
    "participacion",
    "participación",
    "fondo mutuo",
    "etf",
    "administradora",
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

        if "ca-0001" not in url_min:
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
            "No se encontraron archivos CA-0001 en la página oficial."
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
        timeout=180,
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

    inicio = contenido[:500].lower()
    if b"<html" in inicio or b"<!doctype html" in inicio:
        raise RuntimeError(
            f"{registro['archivo']} devolvió HTML y no un Excel."
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


def normalizar(valor: object) -> str:
    if pd.isna(valor):
        return ""
    return re.sub(r"\s+", " ", str(valor)).strip()


def buscar_coincidencias(
    tabla: pd.DataFrame,
    registro: dict,
    archivo: Path,
    hoja: str,
) -> list[dict]:
    coincidencias: list[dict] = []

    limite_filas = min(160, len(tabla))
    limite_columnas = min(50, len(tabla.columns))

    for i in range(limite_filas):
        for j in range(limite_columnas):
            valor = normalizar(tabla.iat[i, j])
            valor_min = valor.lower()

            claves = [
                palabra
                for palabra in PALABRAS_CLAVE
                if palabra in valor_min
            ]

            if claves:
                coincidencias.append(
                    {
                        "anio": registro["anio"],
                        "mes": registro["mes"],
                        "archivo": archivo.name,
                        "hoja": hoja,
                        "fila_excel_aprox": i + 1,
                        "columna_excel_aprox": j + 1,
                        "valor": valor,
                        "palabras_detectadas": " | ".join(claves),
                    }
                )

    return coincidencias


def exportar_muestra(
    tabla: pd.DataFrame,
    registro: dict,
    archivo: Path,
    hoja: str,
) -> pd.DataFrame:
    muestra = tabla.iloc[:160, :50].copy()
    muestra.columns = [
        f"C{numero}"
        for numero in range(1, len(muestra.columns) + 1)
    ]

    muestra.insert(
        0,
        "fila_excel_aprox",
        range(1, len(muestra) + 1),
    )
    muestra.insert(0, "hoja", hoja)
    muestra.insert(0, "archivo", archivo.name)
    muestra.insert(0, "mes", registro["mes"])
    muestra.insert(0, "anio", registro["anio"])

    return muestra


def inspeccionar_archivo(
    archivo: Path,
    registro: dict,
) -> tuple[list[dict], list[dict], list[pd.DataFrame]]:
    fuente, motor, formato_real = preparar_excel(archivo)
    libro = pd.ExcelFile(fuente, engine=motor)

    hojas: list[dict] = []
    coincidencias_total: list[dict] = []
    muestras: list[pd.DataFrame] = []

    for hoja in libro.sheet_names:
        fuente_hoja, motor_hoja, _ = preparar_excel(archivo)

        tabla = pd.read_excel(
            fuente_hoja,
            sheet_name=hoja,
            header=None,
            engine=motor_hoja,
            nrows=200,
        )

        tabla = tabla.dropna(how="all").dropna(axis=1, how="all")
        tabla = tabla.reset_index(drop=True)

        texto = " ".join(
            normalizar(valor).lower()
            for valor in tabla.to_numpy().ravel()
        )

        palabras = [
            palabra
            for palabra in PALABRAS_CLAVE
            if palabra in texto
        ]

        puntaje = sum(
            3
            if palabra in {
                "fondo tipo 3",
                "fondo de pensiones tipo 3",
                "fondo 3",
                "habitat",
                "integra",
                "prima",
                "profuturo",
            }
            else 1
            for palabra in palabras
        )

        hojas.append(
            {
                "anio": registro["anio"],
                "mes": registro["mes"],
                "archivo": archivo.name,
                "formato_real": formato_real,
                "hoja": hoja,
                "filas_leidas": int(tabla.shape[0]),
                "columnas_leidas": int(tabla.shape[1]),
                "puntaje_relevancia": puntaje,
                "palabras_detectadas": " | ".join(palabras),
            }
        )

        coincidencias_total.extend(
            buscar_coincidencias(
                tabla,
                registro,
                archivo,
                hoja,
            )
        )

        if puntaje > 0:
            muestras.append(
                exportar_muestra(
                    tabla,
                    registro,
                    archivo,
                    hoja,
                )
            )

    return hojas, coincidencias_total, muestras


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Descarga e inspecciona la composición específica CA-0001 "
            "de las carteras administradas por las AFP."
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
        "--exitos",
        type=int,
        default=3,
        help=(
            "Cantidad de archivos más recientes que deben descargarse "
            "correctamente. Si un enlace falla, continúa hacia atrás."
        ),
    )
    parser.add_argument(
        "--reemplazar",
        action="store_true",
    )
    args = parser.parse_args()

    raiz = Path(__file__).resolve().parents[1]
    raw = raiz / "data" / "raw" / "sbs" / "ca0001_composicion"
    processed = raiz / "data" / "processed"
    processed.mkdir(parents=True, exist_ok=True)

    sesion = crear_sesion()

    print("Leyendo la página oficial CA-0001 de la SBS...")
    enlaces = obtener_enlaces(
        sesion,
        args.anio_desde,
        args.anio_hasta,
    )
    print(f"Enlaces CA-0001 encontrados: {len(enlaces)}")

    ruta_inventario = (
        processed / "ca0001_inventario_enlaces.csv"
    )
    pd.DataFrame(enlaces).to_csv(
        ruta_inventario,
        index=False,
        encoding="utf-8-sig",
    )

    inspeccionados: list[dict] = []
    hojas_total: list[dict] = []
    coincidencias_total: list[dict] = []
    errores: list[dict] = []
    muestras_total: list[pd.DataFrame] = []

    exitos = 0

    for registro in reversed(enlaces):
        if exitos >= args.exitos:
            break

        print(
            f"\nProbando {registro['anio']}-{registro['mes']:02d} "
            f"{registro['archivo']}"
        )

        try:
            archivo = descargar(
                sesion,
                registro,
                raw,
                args.reemplazar,
            )

            fuente, motor, formato_real = preparar_excel(archivo)
            libro = pd.ExcelFile(fuente, engine=motor)

            hojas, coincidencias, muestras = inspeccionar_archivo(
                archivo,
                registro,
            )

            inspeccionados.append(
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

            hojas_total.extend(hojas)
            coincidencias_total.extend(coincidencias)
            muestras_total.extend(muestras)

            exitos += 1

            print(
                f"  Correcto: {formato_real} | "
                f"{len(libro.sheet_names)} hojas"
            )

            top_hojas = sorted(
                hojas,
                key=lambda x: x["puntaje_relevancia"],
                reverse=True,
            )[:10]

            for fila in top_hojas:
                print(
                    f"   - {fila['hoja']}: "
                    f"{fila['filas_leidas']}x"
                    f"{fila['columnas_leidas']} | "
                    f"puntaje={fila['puntaje_relevancia']}"
                )

        except Exception as error:
            mensaje = str(error)
            errores.append(
                {
                    **registro,
                    "error": mensaje,
                }
            )
            print(f"  ERROR: {mensaje}")

    if exitos == 0:
        raise RuntimeError(
            "No se logró descargar ningún archivo CA-0001."
        )

    hojas_df = pd.DataFrame(hojas_total)
    coincidencias_df = pd.DataFrame(coincidencias_total)
    errores_df = pd.DataFrame(errores)
    inspeccionados_df = pd.DataFrame(inspeccionados)

    if muestras_total:
        muestras_df = pd.concat(
            muestras_total,
            ignore_index=True,
            sort=False,
        )
    else:
        muestras_df = pd.DataFrame()

    rutas = {
        "inventario": ruta_inventario,
        "archivos": (
            processed / "ca0001_archivos_inspeccionados.csv"
        ),
        "hojas": (
            processed / "ca0001_inventario_hojas.csv"
        ),
        "coincidencias": (
            processed / "ca0001_coincidencias_estructura.csv"
        ),
        "muestras": (
            processed / "ca0001_muestras_hojas_relevantes.csv"
        ),
        "errores": (
            processed / "ca0001_errores_inspeccion.csv"
        ),
    }

    inspeccionados_df.to_csv(
        rutas["archivos"],
        index=False,
        encoding="utf-8-sig",
    )
    hojas_df.to_csv(
        rutas["hojas"],
        index=False,
        encoding="utf-8-sig",
    )
    coincidencias_df.to_csv(
        rutas["coincidencias"],
        index=False,
        encoding="utf-8-sig",
    )
    muestras_df.to_csv(
        rutas["muestras"],
        index=False,
        encoding="utf-8-sig",
    )
    errores_df.to_csv(
        rutas["errores"],
        index=False,
        encoding="utf-8-sig",
    )

    print("\nINSPECCIÓN CA-0001 TERMINADA")
    print("=" * 100)
    print(f"Enlaces encontrados: {len(enlaces)}")
    print(f"Archivos correctos inspeccionados: {exitos}")
    print(f"Enlaces fallidos durante la búsqueda: {len(errores)}")
    print(f"Hojas inspeccionadas: {len(hojas_df)}")
    print(f"Coincidencias de estructura: {len(coincidencias_df)}")

    if not hojas_df.empty:
        print("\nHOJAS CON MAYOR PUNTAJE DE RELEVANCIA")
        print("-" * 100)
        columnas = [
            "anio",
            "mes",
            "archivo",
            "hoja",
            "filas_leidas",
            "columnas_leidas",
            "puntaje_relevancia",
            "palabras_detectadas",
        ]
        print(
            hojas_df.sort_values(
                "puntaje_relevancia",
                ascending=False,
            )[columnas].head(25).to_string(index=False)
        )

    print("\nArchivos creados:")
    for ruta in rutas.values():
        print(f" - {ruta.resolve()}")

    print(
        "\nSiguiente paso:\n"
        "Comparte el bloque HOJAS CON MAYOR PUNTAJE DE RELEVANCIA. "
        "Con esa estructura se construirá el consolidador de CA-0001 "
        "sin asumir columnas, hojas ni formatos históricos."
    )


if __name__ == "__main__":
    main()
