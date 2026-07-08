from __future__ import annotations

import re
import unicodedata
from io import BytesIO
from pathlib import Path

import numpy as np
import pandas as pd


CODIGO_AFP = {
    "HA": "Habitat",
    "IN": "Integra",
    # En CA-0001, PR corresponde a Profuturo y RI a Prima.
    "PR": "Profuturo",
    "RI": "Prima",
}

AFPS = ["Habitat", "Integra", "Prima", "Profuturo"]

HOJAS_PRIORITARIAS = [
    "1",
    "1-A",
    "2",
    "3",
    "6",
    "7",
    "9",
    "10",
    "11",
    "13",
]

CODIGOS_MES = {
    "en": 1,
    "fe": 2,
    "ma": 3,
    "ab": 4,
    "my": 5,
    "jn": 6,
    "jl": 7,
    "ag": 8,
    "se": 9,
    "oc": 10,
    "no": 11,
    "di": 12,
}

ETIQUETAS_GENERICAS = [
    "fondos mutuos del extranjero",
    "fondo mutuo alternativo extranjero",
    "fondo mutuo alternativo del extranjero",
    "fondos mutuos o de inversion",
    "fondos mutuos o de inversión",
    "acciones en el extranjero",
    "acciones y valores representativos",
    "bonos de empresa privada extranjera",
    "bono sistema financiero extranjero",
    "titulos de deuda",
    "títulos de deuda",
    "cuentas corrientes del exterior",
    "depositos overnight",
    "depósitos overnight",
    "monedas",
    "indice",
    "índice",
    "bonos",
    "materia prima",
    "forwards",
    "swaps",
    "futuros",
    "opciones",
]


def normalizar(valor: object) -> str:
    if pd.isna(valor):
        return ""
    return re.sub(r"\s+", " ", str(valor)).strip()


def normalizar_clave(valor: object) -> str:
    texto = normalizar(valor).lower()
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(
        caracter
        for caracter in texto
        if not unicodedata.combining(caracter)
    )
    return re.sub(r"\s+", " ", texto).strip()


def numerico(valor: object) -> float:
    if pd.isna(valor):
        return np.nan

    if isinstance(valor, (int, float, np.integer, np.floating)):
        return float(valor)

    texto = normalizar(valor).replace(",", "").replace("%", "")
    if not texto:
        return np.nan

    try:
        return float(texto)
    except ValueError:
        return np.nan


def periodo_desde_nombre(nombre: str) -> tuple[int, int]:
    """
    Corrige el error del módulo anterior, que mostraba 0-00 porque
    convertía el nombre a minúsculas pero buscaba un patrón en mayúsculas.
    """
    coincidencia = re.search(
        r"ca-0001-([a-z]{2})(20\d{2})",
        nombre,
        flags=re.IGNORECASE,
    )

    if not coincidencia:
        return (0, 0)

    codigo = coincidencia.group(1).lower()
    anio = int(coincidencia.group(2))
    mes = CODIGOS_MES.get(codigo, 0)

    return anio, mes


def preparar_excel(archivo: Path) -> tuple[BytesIO, str]:
    contenido = archivo.read_bytes()

    if contenido.startswith(b"PK"):
        return BytesIO(contenido), "openpyxl"

    if contenido.startswith(bytes.fromhex("D0CF11E0A1B11AE1")):
        return BytesIO(contenido), "xlrd"

    inicio = contenido[:500].lower()
    if b"<html" in inicio or b"<!doctype html" in inicio:
        raise ValueError(
            f"{archivo.name} contiene HTML y no un libro Excel."
        )

    raise ValueError(
        f"{archivo.name} no es un XLS/XLSX reconocido."
    )


def leer_libro(archivo: Path) -> list[str]:
    fuente, motor = preparar_excel(archivo)
    return pd.ExcelFile(fuente, engine=motor).sheet_names


def leer_hoja(archivo: Path, hoja: str) -> pd.DataFrame:
    fuente, motor = preparar_excel(archivo)

    tabla = pd.read_excel(
        fuente,
        sheet_name=hoja,
        header=None,
        engine=motor,
    )

    tabla = tabla.dropna(how="all").dropna(axis=1, how="all")
    return tabla.reset_index(drop=True)


def detectar_fecha(tabla: pd.DataFrame, anio: int, mes: int) -> pd.Timestamp:
    limite_filas = min(12, len(tabla))
    limite_columnas = min(10, len(tabla.columns))

    patrones = [
        r"\b(\d{1,2})[-/](\d{1,2})[-/](20\d{2})\b",
        r"\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b",
    ]

    for i in range(limite_filas):
        for j in range(limite_columnas):
            valor = tabla.iat[i, j]

            if isinstance(valor, pd.Timestamp):
                return valor.normalize()

            texto = normalizar(valor)
            for patron in patrones:
                coincidencia = re.search(patron, texto)
                if not coincidencia:
                    continue

                fecha = pd.to_datetime(
                    coincidencia.group(0),
                    dayfirst=True,
                    errors="coerce",
                )
                if pd.notna(fecha):
                    return pd.Timestamp(fecha).normalize()

    if anio > 0 and mes > 0:
        return (
            pd.Timestamp(year=anio, month=mes, day=1)
            + pd.offsets.MonthEnd(0)
        )

    return pd.NaT


def afp_desde_etiqueta(etiqueta: str) -> tuple[str | None, bool]:
    clave = normalizar_clave(etiqueta).upper()

    codigo = re.fullmatch(r"(HA|IN|PR|RI)(00|01|02|03)", clave)
    if codigo:
        prefijo, fondo = codigo.groups()
        return CODIGO_AFP[prefijo], fondo == "03"

    explicitas = {
        "HABITAT F3": "Habitat",
        "INTEGRA F3": "Integra",
        "PRIMA F3": "Prima",
        "PROFUTURO F3": "Profuturo",
    }

    for texto, afp in explicitas.items():
        if texto in clave:
            return afp, True

    return None, False


def detectar_columnas_fondo3(
    tabla: pd.DataFrame,
) -> tuple[int, int, dict[str, dict]]:
    """
    Detecta una fila con HA03, IN03, PR03 y RI03 o con los nombres
    explícitos Habitat F3, Integra F3, Prima F3 y Profuturo F3.

    Retorna:
      fila de códigos,
      fila inicial de datos,
      columnas por AFP.
    """
    limite_filas = min(12, len(tabla))
    mejor = None

    for i in range(limite_filas):
        detectadas = {}

        for j, valor in enumerate(tabla.iloc[i].tolist()):
            afp, es_fondo3 = afp_desde_etiqueta(normalizar(valor))
            if afp and es_fondo3:
                detectadas[afp] = j

        puntaje = len(detectadas)

        if mejor is None or puntaje > mejor[0]:
            mejor = (puntaje, i, detectadas)

    if mejor is None or mejor[0] < 3:
        raise ValueError(
            "No se encontraron al menos tres columnas identificables "
            "del Fondo 3."
        )

    _, fila_codigos, columnas_codigo = mejor

    fila_subencabezado = None
    for i in range(
        fila_codigos + 1,
        min(fila_codigos + 4, len(tabla)),
    ):
        texto = " | ".join(
            normalizar_clave(x)
            for x in tabla.iloc[i].tolist()
        )
        if "monto" in texto and ("%" in texto or "porcentaje" in texto):
            fila_subencabezado = i
            break

    columnas = {}

    for afp, columna in columnas_codigo.items():
        columna_pct = None
        modo = "valor_unico"

        if fila_subencabezado is not None:
            etiqueta = normalizar_clave(
                tabla.iat[fila_subencabezado, columna]
            )
            etiqueta_siguiente = (
                normalizar_clave(
                    tabla.iat[fila_subencabezado, columna + 1]
                )
                if columna + 1 < len(tabla.columns)
                else ""
            )

            if "monto" in etiqueta:
                modo = "monto_pct"
                columna_pct = columna + 1
            elif (
                columna > 0
                and "monto"
                in normalizar_clave(
                    tabla.iat[fila_subencabezado, columna - 1]
                )
            ):
                columna = columna - 1
                modo = "monto_pct"
                columna_pct = columna + 1
            elif "monto" in etiqueta_siguiente:
                columna = columna + 1
                modo = "monto_pct"
                columna_pct = columna + 1

        columnas[afp] = {
            "columna_valor": columna,
            "columna_pct": columna_pct,
            "modo": modo,
        }

    fila_inicio = (
        fila_subencabezado + 1
        if fila_subencabezado is not None
        else fila_codigos + 1
    )

    return fila_codigos, fila_inicio, columnas


def tipo_identificacion(descriptor: str) -> str:
    texto = normalizar(descriptor)
    clave = normalizar_clave(texto)

    if re.fullmatch(r"[A-Z]{2}[A-Z0-9]{10}", texto.upper()):
        return "codigo_isin"

    if "etf" in clave:
        return "etf_o_fondo_identificado"

    if contiene_generica(clave):
        return "categoria_generica"

    if re.match(r"^(i{1,3}|iv|v)\.", clave):
        return "subtotal_geografico"

    if re.match(r"^\d+\.", clave):
        return "subtotal_clase"

    if clave in {"total", "sistema", "total general"}:
        return "total_control"

    return "entidad_fondo_o_instrumento"


def contiene_generica(clave: str) -> bool:
    return any(etiqueta in clave for etiqueta in ETIQUETAS_GENERICAS)


def es_control_o_subtotal(descriptor: str) -> bool:
    tipo = tipo_identificacion(descriptor)
    return tipo in {
        "categoria_generica",
        "subtotal_geografico",
        "subtotal_clase",
        "total_control",
    }


def extraer_hoja(
    archivo: Path,
    hoja: str,
    anio: int,
    mes: int,
) -> tuple[pd.DataFrame, dict]:
    tabla = leer_hoja(archivo, hoja)
    fecha = detectar_fecha(tabla, anio, mes)

    fila_codigos, fila_inicio, columnas = detectar_columnas_fondo3(tabla)
    primera_columna_valor = min(
        detalle["columna_valor"]
        for detalle in columnas.values()
    )

    filas = []

    for i in range(fila_inicio, len(tabla)):
        metadatos = [
            normalizar(tabla.iat[i, j])
            for j in range(primera_columna_valor)
        ]
        metadatos_no_vacios = [
            valor for valor in metadatos if valor
        ]
        descriptor = " | ".join(metadatos_no_vacios)

        if not descriptor:
            descriptor = normalizar(tabla.iat[i, 0])

        registro = {
            "fecha_cartera": fecha,
            "anio": anio,
            "mes": mes,
            "archivo": archivo.name,
            "hoja": hoja,
            "fila_excel_aprox": i + 1,
            "descriptor": descriptor,
            "tipo_identificacion": tipo_identificacion(descriptor),
            "es_control_o_subtotal": es_control_o_subtotal(descriptor),
        }

        for numero, valor in enumerate(metadatos, start=1):
            registro[f"meta_{numero}"] = valor

        algun_valor = False

        for afp in AFPS:
            detalle = columnas.get(afp)

            if not detalle:
                registro[f"valor_{afp}"] = np.nan
                registro[f"pct_{afp}"] = np.nan
                continue

            valor = numerico(
                tabla.iat[i, detalle["columna_valor"]]
            )
            pct = (
                numerico(tabla.iat[i, detalle["columna_pct"]])
                if detalle["columna_pct"] is not None
                else np.nan
            )

            registro[f"valor_{afp}"] = valor
            registro[f"pct_{afp}"] = pct

            if pd.notna(valor) and abs(valor) > 0:
                algun_valor = True

        if algun_valor:
            filas.append(registro)

    wide = pd.DataFrame(filas)

    if wide.empty:
        raise ValueError(
            "Se detectaron columnas, pero no se extrajeron filas "
            "con valores distintos de cero."
        )

    columnas_vector = [f"valor_{afp}" for afp in AFPS]
    vector = (
        wide[columnas_vector]
        .fillna(0.0)
        .round(8)
        .astype(str)
        .agg("|".join, axis=1)
    )
    wide["vector_fondo3"] = vector

    misma_anterior = (
        wide["vector_fondo3"]
        == wide["vector_fondo3"].shift(1)
    )
    misma_siguiente = (
        wide["vector_fondo3"]
        == wide["vector_fondo3"].shift(-1)
    )
    wide["duplicado_vector_adyacente"] = (
        misma_anterior | misma_siguiente
    )

    control = {
        "archivo": archivo.name,
        "fecha_cartera": fecha,
        "hoja": hoja,
        "filas_excel": len(tabla),
        "columnas_excel": len(tabla.columns),
        "fila_codigos": fila_codigos + 1,
        "fila_inicio_datos": fila_inicio + 1,
        "afp_detectadas": " | ".join(sorted(columnas)),
        "numero_afp_detectadas": len(columnas),
        "filas_extraidas": len(wide),
        "filas_detalle_no_control": int(
            (~wide["es_control_o_subtotal"]).sum()
        ),
        "duplicados_adyacentes": int(
            wide["duplicado_vector_adyacente"].sum()
        ),
    }

    return wide, control


def convertir_largo(wide: pd.DataFrame) -> pd.DataFrame:
    filas = []

    columnas_meta = [
        columna
        for columna in wide.columns
        if not columna.startswith("valor_")
        and not columna.startswith("pct_")
    ]

    for fila in wide.itertuples(index=False):
        diccionario = fila._asdict()

        for afp in AFPS:
            valor = diccionario.get(f"valor_{afp}")
            pct = diccionario.get(f"pct_{afp}")

            if pd.isna(valor) or abs(float(valor)) == 0:
                continue

            registro = {
                columna: diccionario[columna]
                for columna in columnas_meta
            }
            registro.update(
                {
                    "afp": afp,
                    "fondo": 3,
                    "valor": float(valor),
                    "participacion_reportada": (
                        float(pct) if pd.notna(pct) else np.nan
                    ),
                }
            )
            filas.append(registro)

    return pd.DataFrame(filas)


def seleccionar_candidatos_detalle(
    largo: pd.DataFrame,
) -> pd.DataFrame:
    candidatos = largo[
        ~largo["es_control_o_subtotal"]
    ].copy()

    # Conserva todas las filas, pero prioriza las identificaciones
    # específicas cuando existen duplicados adyacentes.
    prioridad = {
        "codigo_isin": 5,
        "etf_o_fondo_identificado": 4,
        "entidad_fondo_o_instrumento": 3,
        "categoria_generica": 1,
        "subtotal_geografico": 0,
        "subtotal_clase": 0,
        "total_control": 0,
    }

    candidatos["prioridad_identificacion"] = (
        candidatos["tipo_identificacion"]
        .map(prioridad)
        .fillna(2)
    )

    return candidatos.sort_values(
        [
            "hoja",
            "afp",
            "valor",
            "prioridad_identificacion",
        ],
        ascending=[True, True, False, False],
    )


def crear_top(candidatos: pd.DataFrame) -> pd.DataFrame:
    top = candidatos.copy()
    top["valor_abs"] = top["valor"].abs()

    top = top.sort_values(
        ["hoja", "afp", "valor_abs"],
        ascending=[True, True, False],
    )

    top["ranking_hoja_afp"] = (
        top.groupby(["hoja", "afp"])
        .cumcount()
        .add(1)
    )

    return top[top["ranking_hoja_afp"] <= 20].copy()


def main() -> None:
    raiz = Path(__file__).resolve().parents[1]
    raw = raiz / "data" / "raw" / "sbs" / "ca0001_composicion"
    processed = raiz / "data" / "processed"
    processed.mkdir(parents=True, exist_ok=True)

    archivos = [
        archivo
        for archivo in raw.iterdir()
        if archivo.is_file()
        and archivo.suffix.lower() in {".xls", ".xlsx"}
        and "ca-0001" in archivo.name.lower()
    ]

    archivos_validos = [
        (periodo_desde_nombre(archivo.name), archivo)
        for archivo in archivos
        if periodo_desde_nombre(archivo.name) != (0, 0)
    ]

    if not archivos_validos:
        raise FileNotFoundError(
            "No se encontraron archivos CA-0001 con periodo reconocible."
        )

    (anio, mes), archivo = max(
        archivos_validos,
        key=lambda elemento: elemento[0],
    )

    hojas_disponibles = leer_libro(archivo)
    hojas = [
        hoja
        for hoja in HOJAS_PRIORITARIAS
        if hoja in hojas_disponibles
    ]

    print("\nPILOTO DE EXTRACCIÓN CA-0001 — FONDO 3")
    print("=" * 108)
    print(f"Archivo realmente más reciente descargado: {archivo.name}")
    print(f"Periodo reconocido: {anio}-{mes:02d}")
    print(f"Hojas disponibles: {', '.join(hojas_disponibles)}")
    print(f"Hojas prioritarias a probar: {', '.join(hojas)}")

    bases_wide = []
    controles = []
    errores = []

    for hoja in hojas:
        print(f"\nProcesando hoja {hoja}...")

        try:
            wide, control = extraer_hoja(
                archivo,
                hoja,
                anio,
                mes,
            )
            bases_wide.append(wide)
            controles.append(control)

            print(
                f"  Correcto: {len(wide)} filas | "
                f"AFP detectadas={control['numero_afp_detectadas']} | "
                f"detalle={control['filas_detalle_no_control']} | "
                f"duplicados adyacentes="
                f"{control['duplicados_adyacentes']}"
            )

        except Exception as error:
            errores.append(
                {
                    "archivo": archivo.name,
                    "hoja": hoja,
                    "error": str(error),
                }
            )
            print(f"  No procesada: {error}")

    if not bases_wide:
        raise RuntimeError(
            "No fue posible extraer ninguna hoja del Fondo 3."
        )

    wide_total = pd.concat(
        bases_wide,
        ignore_index=True,
        sort=False,
    )
    largo = convertir_largo(wide_total)
    candidatos = seleccionar_candidatos_detalle(largo)
    top = crear_top(candidatos)
    control_df = pd.DataFrame(controles)
    errores_df = pd.DataFrame(errores)

    rutas = {
        "wide": (
            processed / "ca0001_piloto_fondo3_ancho.csv"
        ),
        "largo": (
            processed / "ca0001_piloto_fondo3_largo.csv"
        ),
        "candidatos": (
            processed / "ca0001_piloto_fondo3_candidatos_detalle.csv"
        ),
        "top": (
            processed / "ca0001_piloto_fondo3_top_detalle.csv"
        ),
        "control": (
            processed / "ca0001_piloto_fondo3_control_hojas.csv"
        ),
        "errores": (
            processed / "ca0001_piloto_fondo3_errores.csv"
        ),
    }

    wide_total.to_csv(
        rutas["wide"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    largo.to_csv(
        rutas["largo"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    candidatos.to_csv(
        rutas["candidatos"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    top.to_csv(
        rutas["top"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    control_df.to_csv(
        rutas["control"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    errores_df.to_csv(
        rutas["errores"],
        index=False,
        encoding="utf-8-sig",
    )

    print("\n" + "=" * 108)
    print("CONTROL DEL PILOTO POR HOJA")
    print("=" * 108)
    print(control_df.to_string(index=False))

    print("\n" + "=" * 108)
    print("TOP DE CANDIDATOS ESPECÍFICOS POR HOJA Y AFP")
    print("=" * 108)

    hojas_top = sorted(top["hoja"].astype(str).unique())

    for hoja in hojas_top:
        for afp in AFPS:
            tabla = top[
                (top["hoja"].astype(str) == hoja)
                & (top["afp"] == afp)
            ].head(10)

            if tabla.empty:
                continue

            print(f"\nHoja {hoja} — {afp}")
            print("-" * 108)
            print(
                tabla[
                    [
                        "ranking_hoja_afp",
                        "fila_excel_aprox",
                        "descriptor",
                        "tipo_identificacion",
                        "valor",
                        "participacion_reportada",
                        "duplicado_vector_adyacente",
                    ]
                ].to_string(index=False)
            )

    print("\nArchivos creados:")
    for ruta in rutas.values():
        print(f" - {ruta.resolve()}")

    print(
        "\nLectura metodológica:\n"
        "- Las hojas 1 y 1-A son agregadas por tipo de instrumento; "
        "no identifican por sí solas el activo final.\n"
        "- La hoja 3 contiene nombres de emisores, administradoras y fondos, "
        "pero también filas genéricas duplicadas; por eso quedan marcadas.\n"
        "- Las hojas 9 y 10 pueden aportar nombres de fondos, ETF, códigos "
        "e instrumentos, aunque sus valores pueden ser unidades y no montos.\n"
        "- Las hojas 11 y 13 corresponden a derivados; sirven para analizar "
        "cobertura cambiaria y no deben sumarse como cartera física.\n"
        "- Este piloto no suma hojas entre sí. Primero valida qué representa "
        "cada una y evita doble conteo antes de consolidar los 133 meses."
    )


if __name__ == "__main__":
    main()
