from __future__ import annotations

import argparse
import re
import time
from io import BytesIO
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urljoin

import numpy as np
import pandas as pd
import requests
from bs4 import BeautifulSoup

PAGINA_SBS = (
    "https://www.sbs.gob.pe/app/stats_net/stats/"
    "EstadisticaSistemaFinancieroResultados.aspx?c=FP-1359"
)

AFPS = ["Habitat", "Integra", "Prima", "Profuturo"]

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


def obtener_enlaces_mensuales(
    sesion: requests.Session,
    anio_desde: int = 2015,
    anio_hasta: int | None = None,
) -> list[dict]:
    """
    Lee la página oficial de la SBS y obtiene los enlaces mensuales FP-1359.
    """
    if anio_hasta is None:
        anio_hasta = datetime.now().year

    respuesta = sesion.get(PAGINA_SBS, timeout=60)
    respuesta.raise_for_status()

    soup = BeautifulSoup(respuesta.text, "lxml")
    registros: list[dict] = []

    for enlace in soup.find_all("a", href=True):
        href = unquote(enlace["href"])
        url = urljoin(PAGINA_SBS, href)
        url_min = url.lower()

        if "fp-1359" not in url_min:
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

    # Eliminar enlaces duplicados.
    unicos = {r["url"]: r for r in registros}
    resultado = sorted(
        unicos.values(),
        key=lambda x: (x["anio"], x["mes"], x["archivo"]),
    )

    if not resultado:
        raise RuntimeError(
            "No se encontraron archivos mensuales FP-1359. "
            "La estructura de la página de la SBS puede haber cambiado."
        )

    return resultado


def descargar_excel(
    sesion: requests.Session,
    registro: dict,
    carpeta: Path,
    reemplazar: bool = False,
) -> Path:
    carpeta.mkdir(parents=True, exist_ok=True)
    destino = carpeta / registro["archivo"]

    if destino.exists() and destino.stat().st_size > 1_000 and not reemplazar:
        return destino

    respuesta = sesion.get(
        registro["url"],
        timeout=90,
        allow_redirects=True,
        headers={"Referer": PAGINA_SBS},
    )
    respuesta.raise_for_status()

    if len(respuesta.content) < 1_000:
        raise RuntimeError(
            f"El archivo {registro['archivo']} es demasiado pequeño "
            "y podría ser una página de error."
        )

    destino.write_bytes(respuesta.content)
    return destino


def preparar_excel(archivo: Path) -> tuple[BytesIO, str]:
    """
    Detecta el formato real por la firma binaria del archivo, no por la
    extensión. Algunos archivos de la SBS terminan en .XLS, pero en realidad
    contienen un libro XLSX.
    """
    contenido = archivo.read_bytes()

    # XLSX es un archivo ZIP y comienza normalmente con PK.
    if contenido.startswith(b"PK"):
        return BytesIO(contenido), "openpyxl"

    # XLS clásico usa el contenedor OLE Compound File.
    if contenido.startswith(bytes.fromhex("D0CF11E0A1B11AE1")):
        return BytesIO(contenido), "xlrd"

    raise ValueError(
        f"{archivo.name} no parece ser un Excel XLS ni XLSX válido. "
        "Puede haberse descargado una página HTML de error."
    )


def buscar_hoja_fondo3(archivo: Path) -> str:
    fuente, motor = preparar_excel(archivo)
    libro = pd.ExcelFile(fuente, engine=motor)

    # Primera opción: nombre exacto o equivalente.
    for hoja in libro.sheet_names:
        normalizada = re.sub(r"[^a-z0-9]", "", hoja.lower())
        if "fondo3" in normalizada and (
            "vcdiario" in normalizada or "valorcuota" in normalizada
        ):
            return hoja

    # Segunda opción: cualquier hoja que contenga Fondo 3.
    for hoja in libro.sheet_names:
        normalizada = re.sub(r"[^a-z0-9]", "", hoja.lower())
        if "fondo3" in normalizada:
            return hoja

    raise ValueError(
        f"No se encontró una hoja del Fondo 3 en {archivo.name}. "
        f"Hojas disponibles: {libro.sheet_names}"
    )


def normalizar_texto(valor: object) -> str:
    if pd.isna(valor):
        return ""
    return re.sub(r"\s+", " ", str(valor)).strip()


def localizar_fila_encabezado(tabla: pd.DataFrame) -> int:
    """
    Busca una fila con 'Día' y, al menos, dos nombres de AFP.
    """
    for indice, fila in tabla.iterrows():
        valores = [normalizar_texto(x).lower() for x in fila.tolist()]
        contiene_dia = any(x in {"día", "dia", "fecha"} for x in valores)
        afps_en_fila = sum(
            any(afp.lower() in celda for celda in valores)
            for afp in AFPS
        )

        if contiene_dia and afps_en_fila >= 2:
            return int(indice)

    raise ValueError("No se pudo localizar la fila de encabezados.")


def identificar_columnas(encabezados: list[str]) -> dict[str, int]:
    columnas: dict[str, int] = {}

    for indice, encabezado in enumerate(encabezados):
        texto = normalizar_texto(encabezado).lower()

        if texto in {"día", "dia", "fecha"}:
            columnas["fecha"] = indice

        for afp in AFPS:
            if afp.lower() in texto:
                columnas[afp] = indice

    if "fecha" not in columnas:
        raise ValueError("No se encontró la columna de fecha.")

    afps_detectadas = [afp for afp in AFPS if afp in columnas]
    if len(afps_detectadas) < 2:
        raise ValueError(
            "Se detectaron muy pocas AFP en el encabezado: "
            f"{afps_detectadas}"
        )

    return columnas


def leer_fondo3(
    archivo: Path,
    anio_archivo: int,
    mes_archivo: int,
) -> pd.DataFrame:
    """
    Lee la hoja Fondo 3 y la transforma al formato largo:
    fecha | afp | fondo | valor_cuota | archivo_origen
    """
    hoja = buscar_hoja_fondo3(archivo)
    fuente, motor = preparar_excel(archivo)

    tabla = pd.read_excel(
        fuente,
        sheet_name=hoja,
        header=None,
        engine=motor,
    )

    fila_encabezado = localizar_fila_encabezado(tabla)
    encabezados = [
        normalizar_texto(x)
        for x in tabla.iloc[fila_encabezado].tolist()
    ]
    columnas = identificar_columnas(encabezados)

    datos = tabla.iloc[fila_encabezado + 1 :].copy()

    fechas = pd.to_datetime(
        datos.iloc[:, columnas["fecha"]],
        errors="coerce",
        dayfirst=True,
    )

    filas: list[dict] = []

    for afp in AFPS:
        if afp not in columnas:
            continue

        valores = pd.to_numeric(
            datos.iloc[:, columnas[afp]],
            errors="coerce",
        )

        temporal = pd.DataFrame(
            {
                "fecha": fechas,
                "afp": afp,
                "fondo": 3,
                "valor_cuota": valores,
            }
        )

        temporal = temporal.dropna(subset=["fecha", "valor_cuota"])
        temporal = temporal[temporal["valor_cuota"] > 0]

        for registro in temporal.itertuples(index=False):
            filas.append(
                {
                    "fecha": registro.fecha,
                    "afp": registro.afp,
                    "fondo": 3,
                    "valor_cuota": float(registro.valor_cuota),
                    "anio_archivo": anio_archivo,
                    "mes_archivo": mes_archivo,
                    "archivo_origen": archivo.name,
                    "hoja_origen": hoja,
                    "fuente_url": PAGINA_SBS,
                }
            )

    if not filas:
        raise ValueError(
            f"No se obtuvieron datos del Fondo 3 en {archivo.name}."
        )

    resultado = pd.DataFrame(filas)

    # Control: conservar fechas razonablemente cercanas al periodo del archivo.
    # Se deja un margen porque algunos archivos pueden contener días limítrofes.
    resultado = resultado[
        resultado["fecha"].dt.year.between(anio_archivo - 1, anio_archivo + 1)
    ]

    return resultado


def calcular_indicadores(base: pd.DataFrame) -> pd.DataFrame:
    base = base.sort_values(["afp", "fecha"]).copy()

    base["rendimiento_simple"] = (
        base.groupby("afp")["valor_cuota"].pct_change()
    )
    base["rendimiento_log"] = (
        base.groupby("afp")["valor_cuota"]
        .transform(lambda x: np.log(x / x.shift(1)))
    )

    base["variacion_porcentual"] = base["rendimiento_simple"] * 100
    base["dia_semana"] = base["fecha"].dt.day_name()

    return base


def crear_control_calidad(
    base: pd.DataFrame,
    errores: list[dict],
) -> pd.DataFrame:
    filas: list[dict] = []

    for afp, grupo in base.groupby("afp"):
        grupo = grupo.sort_values("fecha")
        duplicados = int(
            grupo.duplicated(subset=["fecha"], keep=False).sum()
        )
        max_variacion = float(
            grupo["variacion_porcentual"].abs().max()
        )

        filas.append(
            {
                "afp": afp,
                "fecha_inicial": grupo["fecha"].min(),
                "fecha_final": grupo["fecha"].max(),
                "observaciones": len(grupo),
                "fechas_unicas": grupo["fecha"].nunique(),
                "duplicados_fecha": duplicados,
                "valores_nulos": int(grupo["valor_cuota"].isna().sum()),
                "variacion_diaria_max_abs_pct": max_variacion,
                "dias_con_variacion_mayor_5pct": int(
                    (grupo["variacion_porcentual"].abs() > 5).sum()
                ),
            }
        )

    control = pd.DataFrame(filas)
    control["archivos_con_error"] = len(errores)
    return control


def guardar_resultados(
    base: pd.DataFrame,
    errores: list[dict],
    carpeta_processed: Path,
) -> None:
    carpeta_processed.mkdir(parents=True, exist_ok=True)

    # Mantener una observación por AFP-fecha. Si hay duplicados, conservar
    # la procedente del archivo mensual más reciente.
    base = base.sort_values(
        ["fecha", "afp", "anio_archivo", "mes_archivo"]
    )
    base = base.drop_duplicates(
        subset=["fecha", "afp"],
        keep="last",
    )
    base = calcular_indicadores(base)

    archivo_largo = carpeta_processed / "sbs_fondo3_historico_largo.csv"
    archivo_ancho = carpeta_processed / "sbs_fondo3_historico_ancho.csv"
    archivo_control = carpeta_processed / "sbs_fondo3_control_calidad.csv"
    archivo_errores = carpeta_processed / "sbs_fondo3_errores.csv"

    base.to_csv(
        archivo_largo,
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )

    ancho = base.pivot(
        index="fecha",
        columns="afp",
        values="valor_cuota",
    ).reset_index()

    ancho.to_csv(
        archivo_ancho,
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )

    control = crear_control_calidad(base, errores)
    control.to_csv(
        archivo_control,
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )

    pd.DataFrame(errores).to_csv(
        archivo_errores,
        index=False,
        encoding="utf-8-sig",
    )

    print("\nArchivos creados:")
    print(f" - {archivo_largo.resolve()}")
    print(f" - {archivo_ancho.resolve()}")
    print(f" - {archivo_control.resolve()}")
    print(f" - {archivo_errores.resolve()}")

    print("\nResumen:")
    print(f"Observaciones consolidadas: {len(base):,}")
    print(
        "Rango:",
        base["fecha"].min().date(),
        "a",
        base["fecha"].max().date(),
    )
    print(f"AFP: {', '.join(sorted(base['afp'].unique()))}")
    print(f"Archivos con error: {len(errores)}")

    print("\nÚltimas observaciones:")
    ultimas = (
        base.sort_values("fecha")
        .groupby("afp", as_index=False)
        .tail(1)[["fecha", "afp", "valor_cuota", "variacion_porcentual"]]
    )
    print(ultimas.to_string(index=False))


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Descarga y consolida los valores cuota históricos "
            "del Fondo 3 de las AFP desde la SBS."
        )
    )
    parser.add_argument(
        "--desde",
        type=int,
        default=2015,
        help="Primer año que se descargará. Predeterminado: 2015.",
    )
    parser.add_argument(
        "--hasta",
        type=int,
        default=datetime.now().year,
        help="Último año que se descargará.",
    )
    parser.add_argument(
        "--reemplazar",
        action="store_true",
        help="Vuelve a descargar archivos que ya existen.",
    )
    parser.add_argument(
        "--pausa",
        type=float,
        default=0.3,
        help="Segundos de pausa entre descargas. Predeterminado: 0.3.",
    )
    args = parser.parse_args()

    if args.desde > args.hasta:
        raise ValueError("--desde no puede ser mayor que --hasta.")

    raiz = Path(__file__).resolve().parents[1]
    carpeta_raw = raiz / "data" / "raw" / "sbs" / "historico"
    carpeta_processed = raiz / "data" / "processed"

    sesion = crear_sesion()

    print(
        f"Buscando archivos oficiales entre {args.desde} "
        f"y {args.hasta}..."
    )
    enlaces = obtener_enlaces_mensuales(
        sesion,
        anio_desde=args.desde,
        anio_hasta=args.hasta,
    )

    print(f"Archivos mensuales encontrados: {len(enlaces)}")

    bases: list[pd.DataFrame] = []
    errores: list[dict] = []

    for numero, registro in enumerate(enlaces, start=1):
        etiqueta = (
            f"{registro['anio']}-{registro['mes']:02d} "
            f"({numero}/{len(enlaces)})"
        )
        print(f"\nProcesando {etiqueta}: {registro['archivo']}")

        try:
            archivo = descargar_excel(
                sesion,
                registro,
                carpeta_raw,
                reemplazar=args.reemplazar,
            )
            datos = leer_fondo3(
                archivo,
                anio_archivo=registro["anio"],
                mes_archivo=registro["mes"],
            )
            bases.append(datos)
            print(f"  Correcto: {len(datos)} observaciones.")
        except Exception as error:
            print(f"  ERROR: {error}")
            errores.append(
                {
                    "anio": registro["anio"],
                    "mes": registro["mes"],
                    "archivo": registro["archivo"],
                    "url": registro["url"],
                    "error": str(error),
                }
            )

        time.sleep(max(args.pausa, 0))

    if not bases:
        raise RuntimeError(
            "No se pudo procesar ningún archivo histórico."
        )

    base_completa = pd.concat(bases, ignore_index=True)
    guardar_resultados(
        base_completa,
        errores,
        carpeta_processed,
    )


if __name__ == "__main__":
    main()
