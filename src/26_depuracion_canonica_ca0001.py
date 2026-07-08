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
    "PR": "Profuturo",
    "RI": "Prima",
}

AFPS = ["Habitat", "Integra", "Prima", "Profuturo"]

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

PATRON_CODIGO_CARTERA = re.compile(
    r"^(HA|IN|PR|RI)(00|01|02|03)$",
    flags=re.IGNORECASE,
)

PATRON_ISIN = re.compile(
    r"^[A-Z]{2}[A-Z0-9]{10}$",
    flags=re.IGNORECASE,
)

SUBTOTALES_EXACTOS = {
    "nacional",
    "extranjero",
    "i. nacional",
    "ii. extranjero",
    "i. inversiones locales",
    "ii. inversiones en el exterior",
    "total",
    "total general",
    "sistema",
}

PATRONES_CATEGORIA = [
    "acciones del capital social",
    "acciones del trabajo",
    "acciones preferentes",
    "acciones en el extranjero",
    "valor rep.derecho sobre acc.",
    "valor representativo",
    "fondos mutuos del extranjero",
    "fondos mutuos alternativos del extranjero",
    "fondo mutuo alternativo extranjero",
    "fondo mutuo alternativo del extranjero",
    "fondo de inversion tradicional",
    "fondo de inversion alternativo",
    "bonos de empresas privadas",
    "bonos de empresa privada extranjera",
    "bono sistema financiero extranjero",
    "bonos subordinados",
    "bonos hipotecarios",
    "bonos de arrendamiento financiero",
    "bonos del gobierno",
    "tit. deuda emitidos",
    "titulos de deuda",
    "títulos de deuda",
    "depositos a plazo",
    "depósitos a plazo",
    "cuentas corrientes",
    "cuentas corrientes del exterior",
    "depositos overnight",
    "depósitos overnight",
    "papeles comerciales",
    "titulos con derecho",
    "títulos con derecho",
    "certificados de deposito",
    "certificados de depósito",
    "instrumentos de corto plazo",
    "instrumentos de largo plazo",
]

TOLERANCIA_RELATIVA = 1e-7
TOLERANCIA_ABSOLUTA = 1e-4


def normalizar(valor: object) -> str:
    if pd.isna(valor):
        return ""
    return re.sub(r"\s+", " ", str(valor)).strip()


def clave(valor: object) -> str:
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
    coincidencia = re.search(
        r"ca-0001-([a-z]{2})(20\d{2})",
        nombre,
        flags=re.IGNORECASE,
    )

    if not coincidencia:
        return 0, 0

    mes = CODIGOS_MES.get(coincidencia.group(1).lower(), 0)
    anio = int(coincidencia.group(2))
    return anio, mes


def preparar_excel(archivo: Path) -> tuple[BytesIO, str]:
    contenido = archivo.read_bytes()

    if contenido.startswith(b"PK"):
        return BytesIO(contenido), "openpyxl"

    if contenido.startswith(bytes.fromhex("D0CF11E0A1B11AE1")):
        return BytesIO(contenido), "xlrd"

    raise ValueError(
        f"{archivo.name} no es un libro XLS/XLSX reconocido."
    )


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


def detectar_fecha(
    tabla: pd.DataFrame,
    anio: int,
    mes: int,
) -> pd.Timestamp:
    for i in range(min(10, len(tabla))):
        for j in range(min(8, len(tabla.columns))):
            valor = tabla.iat[i, j]

            if isinstance(valor, pd.Timestamp):
                return valor.normalize()

            texto = normalizar(valor)
            coincidencia = re.search(
                r"\b\d{1,2}[-/]\d{1,2}[-/]20\d{2}\b",
                texto,
            )

            if coincidencia:
                fecha = pd.to_datetime(
                    coincidencia.group(0),
                    dayfirst=True,
                    errors="coerce",
                )
                if pd.notna(fecha):
                    return pd.Timestamp(fecha).normalize()

    return (
        pd.Timestamp(year=anio, month=mes, day=1)
        + pd.offsets.MonthEnd(0)
    )


def detectar_columnas(
    tabla: pd.DataFrame,
) -> tuple[int, int, int, dict[str, dict]]:
    """
    Detecta todos los códigos HAxx/INxx/PRxx/RIxx.

    La frontera de metadatos se fija antes de la primera columna de
    cualquier fondo, no antes de la primera columna de Fondo 3.
    Así se evita contaminar el nombre con montos de F0/F1/F2.
    """
    mejor = None

    for i in range(min(12, len(tabla))):
        codigos = []

        for j, valor in enumerate(tabla.iloc[i].tolist()):
            texto = normalizar(valor).upper()
            coincidencia = PATRON_CODIGO_CARTERA.fullmatch(texto)

            if coincidencia:
                codigos.append(
                    {
                        "columna": j,
                        "prefijo": coincidencia.group(1).upper(),
                        "fondo": coincidencia.group(2),
                        "codigo": texto,
                    }
                )

        if mejor is None or len(codigos) > len(mejor[1]):
            mejor = (i, codigos)

    if mejor is None or len(mejor[1]) < 4:
        raise ValueError(
            "No se detectó una fila suficiente de códigos de cartera."
        )

    fila_codigos, codigos = mejor
    frontera_metadatos = min(item["columna"] for item in codigos)

    fila_sub = None

    for i in range(
        fila_codigos + 1,
        min(fila_codigos + 4, len(tabla)),
    ):
        texto = " | ".join(
            clave(x) for x in tabla.iloc[i].tolist()
        )

        if "monto" in texto and "%" in texto:
            fila_sub = i
            break

    columnas_f3: dict[str, dict] = {}

    for item in codigos:
        if item["fondo"] != "03":
            continue

        afp = CODIGO_AFP[item["prefijo"]]
        columna_valor = item["columna"]
        columna_pct = None
        unidad = "unidades"

        if fila_sub is not None:
            etiqueta = clave(tabla.iat[fila_sub, columna_valor])
            siguiente = (
                clave(tabla.iat[fila_sub, columna_valor + 1])
                if columna_valor + 1 < len(tabla.columns)
                else ""
            )

            if "monto" in etiqueta:
                columna_pct = columna_valor + 1
                unidad = "miles_soles"
            elif "monto" in siguiente:
                columna_valor += 1
                columna_pct = columna_valor + 1
                unidad = "miles_soles"

        columnas_f3[afp] = {
            "codigo": item["codigo"],
            "columna_valor": columna_valor,
            "columna_pct": columna_pct,
            "unidad": unidad,
        }

    if len(columnas_f3) < 3:
        raise ValueError(
            "Se detectaron menos de tres AFP con Fondo 3."
        )

    fila_inicio = (
        fila_sub + 1
        if fila_sub is not None
        else fila_codigos + 1
    )

    return (
        fila_codigos,
        fila_inicio,
        frontera_metadatos,
        columnas_f3,
    )


def crear_filas_base(
    archivo: Path,
    hoja: str,
    anio: int,
    mes: int,
) -> tuple[pd.DataFrame, dict]:
    tabla = leer_hoja(archivo, hoja)
    fecha = detectar_fecha(tabla, anio, mes)

    (
        fila_codigos,
        fila_inicio,
        frontera_metadatos,
        columnas_f3,
    ) = detectar_columnas(tabla)

    filas = []

    for i in range(fila_inicio, len(tabla)):
        metadatos = [
            normalizar(tabla.iat[i, j])
            for j in range(frontera_metadatos)
        ]
        no_vacios = [valor for valor in metadatos if valor]

        if not no_vacios:
            continue

        nombre = no_vacios[0]
        moneda = ""

        for valor in no_vacios[1:]:
            if re.fullmatch(
                r"[A-Z]{3}",
                valor.upper(),
            ):
                moneda = valor.upper()
                break

        registro = {
            "fecha_cartera": fecha,
            "archivo": archivo.name,
            "hoja": hoja,
            "fila_excel_aprox": i + 1,
            "nombre": nombre,
            "nombre_clave": clave(nombre),
            "moneda": moneda,
            "metadatos": " | ".join(no_vacios),
        }

        tiene_valor = False

        for afp in AFPS:
            detalle = columnas_f3.get(afp)

            if detalle is None:
                registro[f"valor_{afp}"] = 0.0
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

            valor = 0.0 if pd.isna(valor) else float(valor)

            registro[f"valor_{afp}"] = valor
            registro[f"pct_{afp}"] = pct

            if abs(valor) > 0:
                tiene_valor = True

        if tiene_valor or nombre:
            filas.append(registro)

    base = pd.DataFrame(filas)

    control = {
        "archivo": archivo.name,
        "hoja": hoja,
        "fecha_cartera": fecha,
        "fila_codigos": fila_codigos + 1,
        "fila_inicio_datos": fila_inicio + 1,
        "frontera_metadatos_columna": frontera_metadatos + 1,
        "afp_fondo3_detectadas": " | ".join(sorted(columnas_f3)),
        "numero_afp_detectadas": len(columnas_f3),
        "unidad": "miles_soles"
        if any(
            detalle["unidad"] == "miles_soles"
            for detalle in columnas_f3.values()
        )
        else "unidades",
        "filas_base": len(base),
    }

    return base, control


def vector_fila(fila: pd.Series) -> np.ndarray:
    return np.array(
        [
            float(fila.get(f"valor_{afp}", 0.0))
            for afp in AFPS
        ],
        dtype=float,
    )


def vectores_iguales(
    fila_a: pd.Series,
    fila_b: pd.Series,
) -> bool:
    return bool(
        np.allclose(
            vector_fila(fila_a),
            vector_fila(fila_b),
            rtol=TOLERANCIA_RELATIVA,
            atol=TOLERANCIA_ABSOLUTA,
        )
    )


def es_isin(texto: str) -> bool:
    return bool(PATRON_ISIN.fullmatch(normalizar(texto).upper()))


def es_subtotal(texto: str) -> bool:
    texto_clave = clave(texto)

    if texto_clave in SUBTOTALES_EXACTOS:
        return True

    if re.match(r"^(i{1,4}|iv|v)\.", texto_clave):
        return True

    if re.match(r"^\d+\.\s", texto_clave):
        return True

    return False


def es_categoria_generica(texto: str) -> bool:
    texto_clave = clave(texto)

    return any(
        patron in texto_clave
        for patron in PATRONES_CATEGORIA
    )


def a_largo(
    base: pd.DataFrame,
    columnas_adicionales: list[str],
    tipo_valor: str,
) -> pd.DataFrame:
    filas = []

    for _, fila in base.iterrows():
        for afp in AFPS:
            valor = float(fila.get(f"valor_{afp}", 0.0))

            if abs(valor) <= TOLERANCIA_ABSOLUTA:
                continue

            registro = {
                "fecha_cartera": fila["fecha_cartera"],
                "archivo": fila["archivo"],
                "hoja": fila["hoja"],
                "fila_excel_aprox": fila["fila_excel_aprox"],
                "afp": afp,
                "fondo": 3,
                "valor": valor,
                "tipo_valor": tipo_valor,
                "participacion_reportada": fila.get(
                    f"pct_{afp}",
                    np.nan,
                ),
            }

            for columna in columnas_adicionales:
                registro[columna] = fila.get(columna, "")

            filas.append(registro)

    return pd.DataFrame(filas)


def depurar_hoja3(
    base: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Hoja 3:
    - fila específica: emisor, administradora o fondo;
    - fila siguiente: categoría genérica con el mismo vector.

    Se conserva una sola vez la fila específica y se adjunta la categoría.
    """
    registros = []
    controles = []
    usados = set()

    for i in range(len(base)):
        if i in usados:
            continue

        fila = base.iloc[i]
        nombre = fila["nombre"]

        if es_subtotal(nombre):
            continue

        if es_categoria_generica(nombre):
            controles.append(
                {
                    "fila_excel_aprox": fila["fila_excel_aprox"],
                    "tipo_control": "categoria_sin_especifico_previo",
                    "nombre": nombre,
                }
            )
            continue

        categoria = ""
        estado_pareja = "sin_categoria_adyacente"

        if i + 1 < len(base):
            siguiente = base.iloc[i + 1]

            if (
                es_categoria_generica(siguiente["nombre"])
                and vectores_iguales(fila, siguiente)
            ):
                categoria = siguiente["nombre"]
                estado_pareja = "pareja_exacta"
                usados.add(i + 1)

        registro = fila.to_dict()
        registro["categoria_instrumento"] = categoria
        registro["estado_pareja"] = estado_pareja
        registro["identificador_especifico"] = nombre
        registros.append(registro)

    canonico = pd.DataFrame(registros)
    control = pd.DataFrame(controles)

    return canonico, control


def depurar_hoja10(
    base: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Hoja 10:
    - una fila de administradora/emisor;
    - una o varias filas ISIN debajo.

    Cuando existen ISIN, se conservan los ISIN y la fila superior solo
    se usa como administrador/emisor. Si no hay ISIN, se conserva la
    entidad como exposición todavía no identificada.
    """
    grupos = []
    actual = None
    seccion = ""

    for _, fila in base.iterrows():
        nombre = fila["nombre"]
        nombre_clave = fila["nombre_clave"]

        if nombre_clave in {
            "nacional",
            "extranjero",
            "i. nacional",
            "ii. extranjero",
        }:
            seccion = nombre
            actual = None
            continue

        if es_subtotal(nombre) or es_categoria_generica(nombre):
            continue

        if es_isin(nombre):
            if actual is None:
                actual = {
                    "entidad": "",
                    "fila_entidad": np.nan,
                    "vector_entidad": np.zeros(len(AFPS)),
                    "hijos": [],
                    "seccion": seccion,
                }

            actual["hijos"].append(fila.to_dict())
            continue

        if actual is not None:
            grupos.append(actual)

        actual = {
            "entidad": nombre,
            "fila_entidad": fila["fila_excel_aprox"],
            "vector_entidad": vector_fila(fila),
            "fila_entidad_dict": fila.to_dict(),
            "hijos": [],
            "seccion": seccion,
        }

    if actual is not None:
        grupos.append(actual)

    canonicos = []
    controles = []

    for numero, grupo in enumerate(grupos, start=1):
        hijos = grupo["hijos"]
        entidad = grupo["entidad"]

        if hijos:
            suma_hijos = np.sum(
                [vector_fila(pd.Series(hijo)) for hijo in hijos],
                axis=0,
            )
            vector_entidad = grupo["vector_entidad"]

            diferencia = vector_entidad - suma_hijos
            max_abs = float(np.max(np.abs(diferencia)))

            denominador = max(
                float(np.max(np.abs(vector_entidad))),
                TOLERANCIA_ABSOLUTA,
            )
            max_rel = max_abs / denominador

            estado = (
                "reconciliado"
                if max_rel <= 1e-5
                else "revisar"
            )

            controles.append(
                {
                    "grupo": numero,
                    "entidad": entidad,
                    "fila_entidad": grupo["fila_entidad"],
                    "numero_isin": len(hijos),
                    "max_diferencia_abs": max_abs,
                    "max_diferencia_rel": max_rel,
                    "estado": estado,
                }
            )

            for hijo in hijos:
                registro = dict(hijo)
                registro["grupo"] = numero
                registro["entidad_administradora"] = entidad
                registro["isin"] = hijo["nombre"].upper()
                registro["seccion"] = grupo["seccion"]
                registro["estado_identificacion"] = "isin"
                canonicos.append(registro)

        else:
            fila_entidad = grupo.get("fila_entidad_dict")

            if fila_entidad is None:
                continue

            if np.max(np.abs(grupo["vector_entidad"])) <= TOLERANCIA_ABSOLUTA:
                continue

            registro = dict(fila_entidad)
            registro["grupo"] = numero
            registro["entidad_administradora"] = entidad
            registro["isin"] = ""
            registro["seccion"] = grupo["seccion"]
            registro["estado_identificacion"] = "entidad_sin_isin"
            canonicos.append(registro)

            controles.append(
                {
                    "grupo": numero,
                    "entidad": entidad,
                    "fila_entidad": grupo["fila_entidad"],
                    "numero_isin": 0,
                    "max_diferencia_abs": np.nan,
                    "max_diferencia_rel": np.nan,
                    "estado": "sin_isin",
                }
            )

    return pd.DataFrame(canonicos), pd.DataFrame(controles)


def depurar_hoja9(
    base: pd.DataFrame,
) -> pd.DataFrame:
    administrador = ""
    registros = []

    for _, fila in base.iterrows():
        nombre = fila["nombre"]

        if es_subtotal(nombre):
            continue

        tiene_valores = (
            np.max(np.abs(vector_fila(fila)))
            > TOLERANCIA_ABSOLUTA
        )

        if not tiene_valores:
            administrador = nombre
            continue

        registro = fila.to_dict()
        registro["administrador"] = administrador
        registro["fondo_local"] = nombre
        registros.append(registro)

    return pd.DataFrame(registros)


def agregar_participacion_calculada(
    largo: pd.DataFrame,
) -> pd.DataFrame:
    if largo.empty:
        return largo

    salida = largo.copy()
    totales = (
        salida.groupby(
            ["fecha_cartera", "hoja", "afp"],
            as_index=False,
        )["valor"]
        .sum()
        .rename(columns={"valor": "total_canonico"})
    )

    salida = salida.merge(
        totales,
        on=["fecha_cartera", "hoja", "afp"],
        how="left",
        validate="many_to_one",
    )

    salida["participacion_calculada_pct"] = np.where(
        salida["total_canonico"].abs() > TOLERANCIA_ABSOLUTA,
        salida["valor"] / salida["total_canonico"] * 100.0,
        np.nan,
    )

    return salida


def crear_top(
    largo: pd.DataFrame,
    nombre: str,
) -> pd.DataFrame:
    if largo.empty:
        return pd.DataFrame()

    salida = largo.copy()
    salida["fuente_detalle"] = nombre
    salida["valor_abs"] = salida["valor"].abs()

    salida = salida.sort_values(
        ["afp", "valor_abs"],
        ascending=[True, False],
    )

    salida["ranking"] = (
        salida.groupby("afp")
        .cumcount()
        .add(1)
    )

    return salida[salida["ranking"] <= 20].copy()


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
        and periodo_desde_nombre(archivo.name) != (0, 0)
    ]

    if not archivos:
        raise FileNotFoundError(
            "No se encontraron archivos CA-0001 descargados."
        )

    archivo = max(
        archivos,
        key=lambda x: periodo_desde_nombre(x.name),
    )
    anio, mes = periodo_desde_nombre(archivo.name)

    print("\nDEPURACIÓN CANÓNICA CA-0001 — FONDO 3")
    print("=" * 112)
    print(f"Archivo: {archivo.name}")
    print(f"Periodo: {anio}-{mes:02d}")

    controles_hojas = []

    base3, control3 = crear_filas_base(
        archivo,
        "3",
        anio,
        mes,
    )
    controles_hojas.append(control3)

    base10, control10 = crear_filas_base(
        archivo,
        "10",
        anio,
        mes,
    )
    controles_hojas.append(control10)

    base9, control9 = crear_filas_base(
        archivo,
        "9",
        anio,
        mes,
    )
    controles_hojas.append(control9)

    canonico3, incidencias3 = depurar_hoja3(base3)
    canonico10, grupos10 = depurar_hoja10(base10)
    canonico9 = depurar_hoja9(base9)

    largo3 = a_largo(
        canonico3,
        [
            "identificador_especifico",
            "categoria_instrumento",
            "estado_pareja",
            "moneda",
        ],
        "miles_soles",
    )

    largo10 = a_largo(
        canonico10,
        [
            "grupo",
            "entidad_administradora",
            "isin",
            "moneda",
            "seccion",
            "estado_identificacion",
        ],
        "miles_soles",
    )

    largo9 = a_largo(
        canonico9,
        [
            "administrador",
            "fondo_local",
        ],
        "unidades",
    )

    largo3 = agregar_participacion_calculada(largo3)
    largo10 = agregar_participacion_calculada(largo10)

    top3 = crear_top(largo3, "hoja3_emisor_o_fondo")
    top10 = crear_top(largo10, "hoja10_isin")
    top = pd.concat(
        [top3, top10],
        ignore_index=True,
        sort=False,
    )

    control_hojas_df = pd.DataFrame(controles_hojas)

    resumen = pd.DataFrame(
        [
            {
                "fuente": "hoja_3",
                "filas_base": len(base3),
                "registros_canonicos": len(canonico3),
                "registros_largos": len(largo3),
                "parejas_exactas": int(
                    (canonico3["estado_pareja"] == "pareja_exacta").sum()
                ),
                "pendientes": int(
                    (canonico3["estado_pareja"] != "pareja_exacta").sum()
                ),
            },
            {
                "fuente": "hoja_10",
                "filas_base": len(base10),
                "registros_canonicos": len(canonico10),
                "registros_largos": len(largo10),
                "parejas_exactas": int(
                    (grupos10["estado"] == "reconciliado").sum()
                )
                if not grupos10.empty
                else 0,
                "pendientes": int(
                    (grupos10["estado"] != "reconciliado").sum()
                )
                if not grupos10.empty
                else 0,
            },
            {
                "fuente": "hoja_9",
                "filas_base": len(base9),
                "registros_canonicos": len(canonico9),
                "registros_largos": len(largo9),
                "parejas_exactas": np.nan,
                "pendientes": np.nan,
            },
        ]
    )

    rutas = {
        "hoja3": (
            processed
            / "ca0001_fondo3_hoja3_emisores_canonicos.csv"
        ),
        "hoja10": (
            processed
            / "ca0001_fondo3_hoja10_isin_canonicos.csv"
        ),
        "hoja9": (
            processed
            / "ca0001_fondo3_hoja9_fondos_locales_unidades.csv"
        ),
        "grupos10": (
            processed
            / "ca0001_fondo3_hoja10_control_grupos.csv"
        ),
        "incidencias3": (
            processed
            / "ca0001_fondo3_hoja3_incidencias.csv"
        ),
        "control_hojas": (
            processed
            / "ca0001_fondo3_control_columnas_hojas.csv"
        ),
        "resumen": (
            processed
            / "ca0001_fondo3_resumen_depuracion.csv"
        ),
        "top": (
            processed
            / "ca0001_fondo3_top_exposiciones_identificadas.csv"
        ),
    }

    largo3.to_csv(
        rutas["hoja3"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    largo10.to_csv(
        rutas["hoja10"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    largo9.to_csv(
        rutas["hoja9"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    grupos10.to_csv(
        rutas["grupos10"],
        index=False,
        encoding="utf-8-sig",
    )
    incidencias3.to_csv(
        rutas["incidencias3"],
        index=False,
        encoding="utf-8-sig",
    )
    control_hojas_df.to_csv(
        rutas["control_hojas"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    resumen.to_csv(
        rutas["resumen"],
        index=False,
        encoding="utf-8-sig",
    )
    top.to_csv(
        rutas["top"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )

    print("\nRESUMEN DE DEPURACIÓN")
    print("-" * 112)
    print(resumen.to_string(index=False))

    if not grupos10.empty:
        print("\nCONTROL DE GRUPOS ADMINISTRADORA–ISIN (HOJA 10)")
        print("-" * 112)
        print(
            grupos10["estado"]
            .value_counts(dropna=False)
            .rename_axis("estado")
            .reset_index(name="grupos")
            .to_string(index=False)
        )

    print("\nTOP DE ISIN IDENTIFICADOS POR AFP")
    print("-" * 112)

    for afp in AFPS:
        tabla = top10[top10["afp"] == afp].head(12)

        if tabla.empty:
            continue

        print(f"\n{afp}")
        print(
            tabla[
                [
                    "ranking",
                    "entidad_administradora",
                    "isin",
                    "moneda",
                    "valor",
                    "participacion_calculada_pct",
                    "estado_identificacion",
                ]
            ].to_string(index=False)
        )

    print("\nTOP DE EMISORES/FONDOS IDENTIFICADOS EN HOJA 3")
    print("-" * 112)

    for afp in AFPS:
        tabla = top3[top3["afp"] == afp].head(12)

        if tabla.empty:
            continue

        print(f"\n{afp}")
        print(
            tabla[
                [
                    "ranking",
                    "identificador_especifico",
                    "categoria_instrumento",
                    "valor",
                    "participacion_calculada_pct",
                    "estado_pareja",
                ]
            ].to_string(index=False)
        )

    print("\nArchivos creados:")
    for ruta in rutas.values():
        print(f" - {ruta.resolve()}")

    print(
        "\nCriterio para continuar:\n"
        "- No se suman las hojas 3, 9 y 10: son vistas distintas de la "
        "misma cartera.\n"
        "- La hoja 3 se usa para emisor/fondo y clase de instrumento.\n"
        "- La hoja 10 se usa para ISIN, moneda y administradora.\n"
        "- La hoja 9 se conserva en unidades para fondos locales.\n"
        "- Solo se consolidarán los 133 meses si la mayoría de los grupos "
        "de la hoja 10 quedan reconciliados y la hoja 3 reduce de forma "
        "sustancial las duplicaciones.\n"
        "- Los derivados de las hojas 11 y 13 quedan en una base separada "
        "y no se mezclan con las posiciones físicas."
    )


if __name__ == "__main__":
    main()
