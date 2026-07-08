from __future__ import annotations

import warnings
import re
import os
import unicodedata
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


warnings.filterwarnings("ignore", category=RuntimeWarning)

AFPS = ["Habitat", "Integra", "Prima", "Profuturo"]

FACTORES_PUBLICOS = [
    "ACWI", "SPY", "QQQ", "EEM", "ILF", "EPU", "VGK", "EWJ",
    "MCHI", "XLK", "XLF", "XLE", "XLB", "XLI", "XLV", "XLY",
    "XLP", "GLD", "CPER", "COPX", "TLT", "LQD", "HYG",
]

FACTORES_EXTRA_BASE = ["VIX", "DXY", "USDPEN"]

CONTROLES_EXPOSICION = [
    "peso_publico_modelado",
    "PRIVATE_ALTERNATIVES",
    "RESIDUAL_NO_MAPEADO",
    "PESO_EXCLUIDO_POR_CONFIANZA",
    "error_cobertura_pct",
    "factor_reescala",
]

LAGS_POR_AFP = {
    "Habitat": [0, 1, 2],
    "Integra": [0],
    "Prima": [0],
    "Profuturo": [0, 1],
}

MODELOS = [
    "M0_base_mercado",
    "M1_proxy_directo",
    "M2_hibrido",
    "P1_proxy_afp_ajena",
    "P2_proxy_pesos_permutados",
]

MIN_ENTRENAMIENTO = 504
REFIT_CADA = 21
ALPHA_RIDGE = 10.0
BOOTSTRAP_REPS = 400
BOOTSTRAP_BLOQUE = 21
SEMILLA = 20260704



def limpiar_nombre(texto: object) -> str:
    valor = str(texto).strip().upper()
    valor = unicodedata.normalize("NFKD", valor)
    valor = "".join(
        caracter
        for caracter in valor
        if not unicodedata.combining(caracter)
    )
    return re.sub(r"[^A-Z0-9]+", "", valor)


def leer_csv_flexible(
    ruta: Path,
    nrows: int | None = None,
) -> pd.DataFrame:
    """
    Lee CSV con coma, punto y coma o tabulación, y prueba UTF-8/Latin-1.
    """
    intentos = [
        {
            "sep": None,
            "engine": "python",
            "encoding": "utf-8-sig",
        },
        {
            "sep": None,
            "engine": "python",
            "encoding": "latin-1",
        },
        {
            "sep": ",",
            "encoding": "utf-8-sig",
        },
        {
            "sep": ";",
            "encoding": "utf-8-sig",
        },
        {
            "sep": ";",
            "encoding": "latin-1",
        },
    ]

    ultimo_error = None

    for argumentos in intentos:
        try:
            return pd.read_csv(
                ruta,
                nrows=nrows,
                **argumentos,
            )
        except Exception as error:
            ultimo_error = error

    raise RuntimeError(
        f"No se pudo leer {ruta}: {ultimo_error}"
    )




def convertir_booleano(serie: pd.Series) -> pd.Series:
    """
    Convierte columnas con True/False, 1/0, sí/no o yes/no
    a booleanos puros. Los valores vacíos se interpretan como False.
    """
    if pd.api.types.is_bool_dtype(serie):
        return serie.fillna(False).astype(bool)

    return (
        serie.fillna(False)
        .astype(str)
        .str.strip()
        .str.lower()
        .isin(
            {
                "true",
                "1",
                "si",
                "sí",
                "yes",
                "y",
                "verdadero",
            }
        )
        .astype(bool)
    )


def parsear_fechas_robusto(
    serie: pd.Series,
    nombre_origen: str = "fecha",
) -> tuple[pd.Series, dict[str, object]]:
    """
    Prueba formatos frecuentes de fecha y elige el que conserva más
    observaciones, evita fechas futuras y mantiene una serie diaria plausible.

    Es especialmente importante para no interpretar 05/12/2026 como
    12/05/2026, ni perder todos los días mayores que 12.
    """
    original = serie.copy()
    texto = (
        original.fillna("")
        .astype(str)
        .str.strip()
    )

    candidatos: list[tuple[str, pd.Series]] = []

    formatos = [
        ("iso_guion", "%Y-%m-%d"),
        ("iso_barra", "%Y/%m/%d"),
        ("dia_mes_anio_barra", "%d/%m/%Y"),
        ("mes_dia_anio_barra", "%m/%d/%Y"),
        ("dia_mes_anio_guion", "%d-%m-%Y"),
        ("mes_dia_anio_guion", "%m-%d-%Y"),
        ("anio_mes_dia_compacto", "%Y%m%d"),
    ]

    for nombre, formato in formatos:
        fechas = pd.to_datetime(
            texto,
            format=formato,
            errors="coerce",
        )
        candidatos.append((nombre, fechas))

    # Candidatos flexibles como último recurso.
    candidatos.extend(
        [
            (
                "flexible_dayfirst_false",
                pd.to_datetime(
                    texto,
                    errors="coerce",
                    dayfirst=False,
                ),
            ),
            (
                "flexible_dayfirst_true",
                pd.to_datetime(
                    texto,
                    errors="coerce",
                    dayfirst=True,
                ),
            ),
        ]
    )

    hoy = pd.Timestamp.today().normalize()
    limite_futuro = hoy + pd.Timedelta(days=7)
    limite_pasado = pd.Timestamp("2000-01-01")

    evaluaciones = []

    for nombre, fechas in candidatos:
        validas = fechas.notna()
        n_validas = int(validas.sum())

        if n_validas == 0:
            evaluaciones.append(
                {
                    "metodo": nombre,
                    "fechas": fechas,
                    "validas": 0,
                    "unicas": 0,
                    "futuras": 10**9,
                    "anteriores_2000": 10**9,
                    "duplicadas": 10**9,
                    "puntaje": -10**12,
                }
            )
            continue

        valores = fechas[validas]
        unicas = int(valores.nunique())
        futuras = int((valores > limite_futuro).sum())
        anteriores = int((valores < limite_pasado).sum())
        duplicadas = n_validas - unicas

        # Prioridad:
        # 1) conservar filas válidas;
        # 2) conservar fechas únicas;
        # 3) penalizar fechas futuras o absurdamente antiguas;
        # 4) penalizar duplicación creada por una interpretación incorrecta.
        puntaje = (
            n_validas * 1_000_000
            + unicas * 1_000
            - futuras * 10_000_000
            - anteriores * 10_000_000
            - duplicadas
        )

        evaluaciones.append(
            {
                "metodo": nombre,
                "fechas": fechas,
                "validas": n_validas,
                "unicas": unicas,
                "futuras": futuras,
                "anteriores_2000": anteriores,
                "duplicadas": duplicadas,
                "puntaje": puntaje,
            }
        )

    mejor = max(
        evaluaciones,
        key=lambda x: x["puntaje"],
    )

    fechas_finales = mejor["fechas"]

    control = {
        "origen": nombre_origen,
        "metodo_fecha": mejor["metodo"],
        "filas_originales": int(len(original)),
        "fechas_validas": int(mejor["validas"]),
        "fechas_unicas": int(mejor["unicas"]),
        "fechas_futuras": int(mejor["futuras"]),
        "fecha_minima": (
            fechas_finales.min()
            if fechas_finales.notna().any()
            else pd.NaT
        ),
        "fecha_maxima": (
            fechas_finales.max()
            if fechas_finales.notna().any()
            else pd.NaT
        ),
    }

    return fechas_finales, control


def validar_base_cuotas(
    salida: pd.DataFrame,
    control_fecha: dict[str, object],
) -> pd.DataFrame:
    """
    Detiene la evaluación cuando la base de cuotas perdió fechas,
    contiene fechas futuras o genera retornos incompatibles con una cuota AFP.
    """
    conteo = (
        salida.groupby("afp", as_index=False)
        .agg(
            observaciones=("fecha", "size"),
            fechas_unicas=("fecha", "nunique"),
            primera_fecha=("fecha", "min"),
            ultima_fecha=("fecha", "max"),
            retorno_abs_mediano=(
                "retorno_cuota",
                lambda s: float(
                    pd.to_numeric(s, errors="coerce")
                    .abs()
                    .median()
                ),
            ),
            retorno_abs_p99=(
                "retorno_cuota",
                lambda s: float(
                    pd.to_numeric(s, errors="coerce")
                    .abs()
                    .quantile(0.99)
                ),
            ),
            retorno_abs_max=(
                "retorno_cuota",
                lambda s: float(
                    pd.to_numeric(s, errors="coerce")
                    .abs()
                    .max()
                ),
            ),
        )
    )

    problemas = []

    if set(conteo["afp"]) != set(AFPS):
        problemas.append(
            "no están presentes las cuatro AFP"
        )

    # Esta investigación ya tiene una base maestra diaria 2015-2026.
    # Menos de 2 500 fechas por AFP significa que la lectura perdió una
    # porción importante de la serie.
    if not conteo.empty and conteo["fechas_unicas"].min() < 2500:
        problemas.append(
            "alguna AFP conserva menos de 2 500 fechas; "
            "la base maestra esperada tiene aproximadamente 2 966"
        )

    hoy = pd.Timestamp.today().normalize()
    if (
        not conteo.empty
        and conteo["ultima_fecha"].max()
        > hoy + pd.Timedelta(days=7)
    ):
        problemas.append(
            "la fecha máxima está en el futuro"
        )

    # Los retornos diarios del Fondo 3 normalmente son de pocos puntos
    # porcentuales. Un p99 superior a 10 % indica fechas desordenadas,
    # valores mal leídos o escala porcentual incorrecta.
    if (
        not conteo.empty
        and conteo["retorno_abs_p99"].max() > 0.10
    ):
        problemas.append(
            "el percentil 99 del retorno absoluto supera 10 %"
        )

    if problemas:
        detalle = "\n".join(
            f"- {problema}"
            for problema in problemas
        )

        raise ValueError(
            "La base de cuotas fue detectada, pero no supera los "
            "controles de integridad:\n"
            f"{detalle}\n\n"
            "Control del parser de fechas:\n"
            f"{control_fecha}\n\n"
            "Resumen por AFP:\n"
            f"{conteo.to_string(index=False)}"
        )

    return conteo

def columna_fecha(columnas: Iterable[str]) -> str | None:
    alias = {
        "FECHA",
        "DATE",
        "FECHACUOTA",
        "FECHACARTERA",
        "FECHAVALORCUOTA",
        "FECHAVALOR",
        "FECHADEVALOR",
        "FECHAINFORMACION",
        "FECHADEINFORMACION",
        "FECHAREGISTRO",
        "FECHADECORTE",
        "FECHACIERRE",
        "DIA",
        "TRADINGDATE",
    }

    for columna in columnas:
        limpio = limpiar_nombre(columna)

        if limpio in alias:
            return columna

    for columna in columnas:
        limpio = limpiar_nombre(columna)

        if limpio.startswith("FECHA") and any(
            palabra in limpio
            for palabra in [
                "CUOTA",
                "VALOR",
                "INFO",
                "REGISTRO",
                "CORTE",
                "CIERRE",
            ]
        ):
            return columna

    return None


def canon_factor(columna: object) -> str | None:
    """
    Reconoce factores aunque la columna incluya prefijos, sufijos o
    etiquetas de precio, por ejemplo:
    - ACWI_return
    - ret_SPY
    - QQQ_Adj Close
    - ('XLK', 'Close')
    - mercado_EEM_pct_change
    """
    original = str(columna).upper()
    limpio = limpiar_nombre(columna)

    alias = {
        "ACWI": "ACWI",
        "SPY": "SPY",
        "QQQ": "QQQ",
        "EEM": "EEM",
        "ILF": "ILF",
        "EPU": "EPU",
        "VGK": "VGK",
        "EWJ": "EWJ",
        "MCHI": "MCHI",
        "XLK": "XLK",
        "XLF": "XLF",
        "XLE": "XLE",
        "XLB": "XLB",
        "XLI": "XLI",
        "XLV": "XLV",
        "XLY": "XLY",
        "XLP": "XLP",
        "GLD": "GLD",
        "CPER": "CPER",
        "COPX": "COPX",
        "TLT": "TLT",
        "LQD": "LQD",
        "HYG": "HYG",
        "VIX": "VIX",
        "VIXCLS": "VIX",
        "DXY": "DXY",
        "DX": "DXY",
        "DOLLARINDEX": "DXY",
        "USDPEN": "USDPEN",
        "PENUSD": "USDPEN",
        "USDPERU": "USDPEN",
    }

    # Coincidencia exacta después de limpiar.
    if limpio in alias:
        return alias[limpio]

    # Separar la etiqueta original por delimitadores habituales y buscar
    # el ticker como token completo.
    tokens = {
        limpiar_nombre(token)
        for token in re.split(
            r"[^A-Z0-9]+",
            original,
        )
        if limpiar_nombre(token)
    }

    for candidato, canonico in alias.items():
        if candidato in tokens:
            return canonico

    # Detectar ticker incrustado entre palabras conocidas de precio/retorno.
    palabras_ruido = [
        "RETORNO", "RETURN", "RET", "PCTCHANGE", "CHANGE",
        "ADJCLOSE", "CLOSE", "PRICE", "PRECIO", "NIVEL",
        "OPEN", "HIGH", "LOW", "VOLUME", "MERCADO", "FACTOR",
    ]

    reducido = limpio
    for ruido in palabras_ruido:
        reducido = reducido.replace(ruido, "")

    if reducido in alias:
        return alias[reducido]

    # Último recurso: buscar el ticker como prefijo o sufijo, priorizando
    # identificadores más largos para evitar confundir DX con DXY.
    for candidato in sorted(alias, key=len, reverse=True):
        if (
            reducido.startswith(candidato)
            or reducido.endswith(candidato)
        ):
            return alias[candidato]

    return None



def leer_cabecera(ruta: Path) -> list[str]:
    try:
        return list(
            leer_csv_flexible(
                ruta,
                nrows=0,
            ).columns
        )
    except Exception:
        return []


def descubrir_archivo_mercado(
    processed: Path,
) -> tuple[Path, list[str], str]:
    """
    Busca el archivo de factores en formato ancho o largo.

    Formato ancho:
        fecha, ACWI, SPY, QQQ, ...

    Formato largo:
        fecha, ticker/factor/symbol, retorno/close/price
    """
    candidatos = []

    rutas = list(processed.rglob("*.csv"))

    for ruta in rutas:
        columnas = leer_cabecera(ruta)
        if not columnas:
            continue

        fecha = columna_fecha(columnas)
        nombres = {
            limpiar_nombre(columna): columna
            for columna in columnas
        }

        factores = {
            canon_factor(columna)
            for columna in columnas
            if canon_factor(columna) is not None
        }
        factores.discard(None)

        coincidencias_anchas = len(
            factores.intersection(
                set(
                    FACTORES_PUBLICOS
                    + FACTORES_EXTRA_BASE
                )
            )
        )

        # Detección de formato largo.
        factor_col = detectar_columna(
            columnas,
            {
                "FACTOR", "TICKER", "SYMBOL", "SIMBOLO",
                "ACTIVO", "INSTRUMENTO", "SERIE",
            },
        )
        valor_col = detectar_columna(
            columnas,
            {
                "RETORNO", "RETURN", "RETORNODIARIO",
                "RENDIMIENTO", "RENTABILIDADDIARIA",
                "ADJCLOSE", "CLOSE", "PRICE", "PRECIO",
                "VALOR", "NIVEL",
            },
        )
        es_largo = (
            fecha is not None
            and factor_col is not None
            and valor_col is not None
        )

        if coincidencias_anchas < 4 and not es_largo:
            continue

        nombre = ruta.name.lower()
        preferencia = (
            8 * ("factor" in nombre)
            + 6 * ("mercado" in nombre)
            + 4 * (
                "return" in nombre
                or "retorno" in nombre
            )
            + 2 * ("precio" in nombre or "price" in nombre)
            - 5 * ("proxy" in nombre)
            - 5 * ("modelo" in nombre)
            - 4 * ("resultado" in nombre)
        )

        formato = "largo" if es_largo and coincidencias_anchas < 4 else "ancho"

        puntuacion = (
            coincidencias_anchas
            + (20 if es_largo else 0)
        )

        candidatos.append(
            (
                puntuacion,
                preferencia,
                ruta,
                sorted(factores),
                formato,
            )
        )

    if not candidatos:
        # Crear un diagnóstico para que el error sea accionable.
        diagnostico = []
        for ruta in rutas[:200]:
            columnas = leer_cabecera(ruta)
            if columnas:
                diagnostico.append(
                    f"{ruta.name}: {', '.join(map(str, columnas[:12]))}"
                )

        muestra = "\n".join(diagnostico[:25])

        raise FileNotFoundError(
            "No se encontró automáticamente el archivo de mercado. "
            "Se revisaron archivos CSV recursivamente dentro de "
            f"{processed}. Encabezados observados:\n{muestra}"
        )

    candidatos.sort(
        key=lambda x: (x[0], x[1]),
        reverse=True,
    )

    _, _, ruta, factores, formato = candidatos[0]
    return ruta, factores, formato



def descubrir_archivo_cuotas(processed: Path) -> Path:
    """
    Detecta el maestro diario de cuotas en formato largo o ancho.

    También puede fijarse explícitamente con la variable:
        AFP_CUOTAS_CSV=C:\\ruta\\archivo.csv
    """
    ruta_forzada = os.environ.get("AFP_CUOTAS_CSV", "").strip()

    if ruta_forzada:
        ruta = Path(ruta_forzada)

        if not ruta.exists():
            raise FileNotFoundError(
                "AFP_CUOTAS_CSV apunta a una ruta inexistente: "
                f"{ruta}"
            )

        return ruta

    candidatos = []
    diagnostico = []

    for ruta in processed.rglob("*.csv"):
        columnas = leer_cabecera(ruta)

        if not columnas:
            continue

        diagnostico.append(
            f"{ruta.name}: {', '.join(map(str, columnas[:15]))}"
        )

        fecha = columna_fecha(columnas)

        if fecha is None:
            continue

        nombres = {
            limpiar_nombre(columna): columna
            for columna in columnas
        }

        columna_afp = detectar_columna(
            columnas,
            {
                "AFP",
                "ADMINISTRADORA",
                "NOMBREAFP",
                "AFPADMINISTRADORA",
                "EMPRESA",
            },
        )

        retorno_col = detectar_columna(
            columnas,
            {
                "RETORNODIARIO",
                "RETORNO",
                "RETURN",
                "RENTABILIDDIARIA",
                "RENTABILIDADDIARIA",
                "RENDIMIENTO",
                "RENDIMIENTODIARIO",
                "VARIACIONDIARIA",
                "VARIACIONPORCENTUAL",
                "PCTCHANGE",
            },
        )

        valor_col = detectar_columna(
            columnas,
            {
                "VALORCUOTA",
                "VALORDELACUOTA",
                "CUOTA",
                "VALORCUOTAFONDO3",
                "VALORFONDO3",
                "VALOR",
            },
        )

        columnas_afp = []
        for columna in columnas:
            limpio = limpiar_nombre(columna)

            if any(
                limpiar_nombre(afp) in limpio
                for afp in AFPS
            ):
                columnas_afp.append(columna)

        valido_largo = (
            columna_afp is not None
            and (
                retorno_col is not None
                or valor_col is not None
            )
        )
        valido_ancho = len(columnas_afp) >= 3

        if not (valido_largo or valido_ancho):
            continue

        nombre = ruta.name.lower()

        penalizacion = (
            12 * ("ca0001" in nombre)
            + 10 * ("fp1356" in nombre)
            + 8 * ("cartera" in nombre)
            + 8 * ("taxonomia" in nombre)
            + 8 * ("proxy" in nombre)
            + 8 * ("modelo" in nombre)
            + 6 * ("resultado" in nombre)
            + 6 * ("predic" in nombre)
            + 5 * ("hoja" in nombre)
        )

        preferencia = (
            15 * ("cuota" in nombre)
            + 8 * ("master" in nombre)
            + 5 * ("fondo3" in nombre or "fondo_3" in nombre)
            + 3 * ("sbs" in nombre)
            + 2 * ("diario" in nombre)
            - penalizacion
        )

        puntuacion_estructura = (
            30 * int(valido_largo)
            + 5 * len(columnas_afp)
            + 4 * int(valor_col is not None)
            + 2 * int(retorno_col is not None)
        )

        # Validación ligera del contenido para evitar confundir una cartera
        # con el maestro de una cuota por AFP y fecha.
        calidad = 0.0

        try:
            muestra = leer_csv_flexible(
                ruta,
                nrows=30000,
            )

            if columna_afp is not None:
                muestra_fecha, _ = parsear_fechas_robusto(
                    muestra[fecha],
                    nombre_origen=f"{ruta.name}:{fecha}",
                )
                muestra_afp = muestra[
                    columna_afp
                ].map(normalizar_afp)

                validos = pd.DataFrame(
                    {
                        "fecha": muestra_fecha,
                        "afp": muestra_afp,
                    }
                ).dropna()

                validos = validos[
                    validos["afp"].isin(AFPS)
                ]

                if not validos.empty:
                    ratio = (
                        len(validos)
                        / validos[
                            ["fecha", "afp"]
                        ].drop_duplicates().shape[0]
                    )

                    if ratio <= 1.05:
                        calidad += 30
                    elif ratio <= 1.25:
                        calidad += 15
                    elif ratio > 3:
                        calidad -= 25

                    fechas_con_afp = (
                        validos.groupby("fecha")["afp"]
                        .nunique()
                    )
                    if (
                        not fechas_con_afp.empty
                        and fechas_con_afp.median() >= 3
                    ):
                        calidad += 15

        except Exception:
            pass

        candidatos.append(
            (
                puntuacion_estructura
                + preferencia
                + calidad,
                preferencia,
                ruta,
                "largo" if valido_largo else "ancho",
                columnas,
            )
        )

    if not candidatos:
        muestra = "\n".join(
            diagnostico[:40]
        )

        raise FileNotFoundError(
            "No se encontró automáticamente el CSV diario de cuotas. "
            "Se admiten nombres como Fecha de información, "
            "Administradora y Valor Cuota, además de archivos separados "
            "por punto y coma. Encabezados observados:\n"
            f"{muestra}\n\n"
            "También puede fijar la ruta en PowerShell con:\n"
            '$env:AFP_CUOTAS_CSV="C:\\ruta\\archivo.csv"'
        )

    candidatos.sort(
        key=lambda x: (x[0], x[1]),
        reverse=True,
    )

    return candidatos[0][2]



def detectar_columna(
    columnas: Iterable[str],
    alias: set[str],
) -> str | None:
    alias_limpios = {
        limpiar_nombre(valor)
        for valor in alias
    }

    for columna in columnas:
        if limpiar_nombre(columna) in alias_limpios:
            return columna

    # Coincidencia flexible, dando prioridad a nombres más largos.
    for columna in columnas:
        limpio = limpiar_nombre(columna)

        for candidato in sorted(
            alias_limpios,
            key=len,
            reverse=True,
        ):
            if (
                candidato
                and (
                    limpio.startswith(candidato)
                    or limpio.endswith(candidato)
                )
            ):
                return columna

    return None


def normalizar_afp(valor: object) -> str | None:
    texto = limpiar_nombre(valor)

    for afp in AFPS:
        if limpiar_nombre(afp) in texto:
            return afp

    return None



def preparar_cuotas(ruta: Path) -> pd.DataFrame:
    df = leer_csv_flexible(ruta)
    fecha = columna_fecha(df.columns)

    if fecha is None:
        raise ValueError(
            f"No se identificó la fecha en {ruta.name}. "
            f"Columnas: {list(df.columns)}"
        )

    df[fecha], control_fecha = parsear_fechas_robusto(
        df[fecha],
        nombre_origen=f"{ruta.name}:{fecha}",
    )

    columna_afp = detectar_columna(
        df.columns,
        {
            "AFP",
            "ADMINISTRADORA",
            "NOMBREAFP",
            "AFPADMINISTRADORA",
            "EMPRESA",
        },
    )

    retorno_col = detectar_columna(
        df.columns,
        {
            "RETORNODIARIO",
            "RETORNO",
            "RETURN",
            "RENTABILIDDIARIA",
            "RENTABILIDADDIARIA",
            "RENDIMIENTO",
            "RENDIMIENTODIARIO",
            "VARIACIONDIARIA",
            "VARIACIONPORCENTUAL",
            "PCTCHANGE",
        },
    )

    valor_col = detectar_columna(
        df.columns,
        {
            "VALORCUOTA",
            "VALORDELACUOTA",
            "CUOTA",
            "VALORCUOTAFONDO3",
            "VALORFONDO3",
            "VALOR",
        },
    )

    fondo_col = detectar_columna(
        df.columns,
        {
            "FONDO",
            "TIPOFONDO",
            "NUMEROFONDO",
            "FONDOTIPO",
        },
    )

    if fondo_col is not None:
        fondo_texto = (
            df[fondo_col]
            .fillna("")
            .astype(str)
            .map(limpiar_nombre)
        )
        mascara_f3 = fondo_texto.isin(
            {
                "3",
                "FONDO3",
                "TIPO3",
                "F3",
            }
        ) | fondo_texto.str.contains(
            r"(?:^|FONDO|TIPO)3$",
            regex=True,
        )

        if mascara_f3.any():
            df = df[mascara_f3].copy()

    if columna_afp is not None:
        salida = df.copy()
        salida["afp"] = salida[
            columna_afp
        ].map(normalizar_afp)

        # Se prefiere el valor de cuota cuando está disponible, porque
        # evita problemas de escala en retornos ya expresados en porcentaje.
        if valor_col is not None:
            salida["valor_cuota"] = pd.to_numeric(
                salida[valor_col],
                errors="coerce",
            )
            salida = salida.sort_values(
                ["afp", fecha]
            )
            salida["retorno_cuota"] = (
                salida.groupby("afp")["valor_cuota"]
                .pct_change(fill_method=None)
            )
        elif retorno_col is not None:
            salida["retorno_cuota"] = pd.to_numeric(
                salida[retorno_col],
                errors="coerce",
            )

            # Corregir retornos guardados como porcentaje (por ejemplo 1.25
            # en lugar de 0.0125), sin afectar series ya decimales.
            p99 = salida["retorno_cuota"].abs().quantile(0.99)
            mediana = salida["retorno_cuota"].abs().median()

            if (
                pd.notna(p99)
                and pd.notna(mediana)
                and p99 > 0.50
                and mediana > 0.01
            ):
                salida["retorno_cuota"] = (
                    salida["retorno_cuota"] / 100.0
                )
        else:
            raise ValueError(
                "El archivo de cuotas no contiene una columna "
                "reconocible de retorno ni valor de cuota."
            )

        salida = salida.rename(
            columns={fecha: "fecha"}
        )
        salida = salida[
            salida["afp"].isin(AFPS)
        ][
            ["fecha", "afp", "retorno_cuota"]
        ]

    else:
        columnas_afp = {}

        for afp in AFPS:
            candidatas = [
                columna
                for columna in df.columns
                if limpiar_nombre(afp)
                in limpiar_nombre(columna)
            ]

            if candidatas:
                candidatas.sort(
                    key=lambda columna: (
                        "CUOTA"
                        not in limpiar_nombre(columna),
                        "VALOR"
                        not in limpiar_nombre(columna),
                        len(limpiar_nombre(columna)),
                    )
                )
                columnas_afp[afp] = candidatas[0]

        if len(columnas_afp) < 3:
            raise ValueError(
                "El archivo no tiene formato largo ni al menos tres "
                "columnas identificables por nombre de AFP. "
                f"Columnas: {list(df.columns)}"
            )

        salida = (
            df[
                [fecha]
                + list(columnas_afp.values())
            ]
            .rename(columns={fecha: "fecha"})
            .melt(
                id_vars="fecha",
                var_name="columna_afp",
                value_name="valor_o_retorno",
            )
        )
        inverso = {
            columna: afp
            for afp, columna
            in columnas_afp.items()
        }
        salida["afp"] = salida[
            "columna_afp"
        ].map(inverso)
        salida["valor_o_retorno"] = pd.to_numeric(
            salida["valor_o_retorno"],
            errors="coerce",
        )

        q95 = (
            salida["valor_o_retorno"]
            .abs()
            .quantile(0.95)
        )

        if pd.notna(q95) and q95 <= 0.30:
            salida["retorno_cuota"] = (
                salida["valor_o_retorno"]
            )
        else:
            salida = salida.sort_values(
                ["afp", "fecha"]
            )
            salida["retorno_cuota"] = (
                salida.groupby("afp")[
                    "valor_o_retorno"
                ]
                .pct_change(fill_method=None)
            )

        salida = salida[
            ["fecha", "afp", "retorno_cuota"]
        ]

    salida = (
        salida.dropna(
            subset=[
                "fecha",
                "afp",
                "retorno_cuota",
            ]
        )
        .sort_values(
            ["afp", "fecha"]
        )
        .drop_duplicates(
            subset=["fecha", "afp"],
            keep="last",
        )
    )

    if salida.empty:
        raise ValueError(
            f"El archivo {ruta.name} fue leído, pero no produjo "
            "retornos válidos para Habitat, Integra, Prima o Profuturo."
        )

    conteo_afp = salida.groupby("afp")[
        "fecha"
    ].nunique()

    if len(conteo_afp) < 4:
        raise ValueError(
            "El archivo detectado no contiene las cuatro AFP. "
            f"Conteo: {conteo_afp.to_dict()}"
        )

    control_integridad = validar_base_cuotas(
        salida,
        control_fecha,
    )

    salida.attrs["control_fecha"] = control_fecha
    salida.attrs["control_integridad"] = control_integridad

    return salida


def serie_es_retorno(
    serie: pd.Series,
    nombre_original: str,
) -> bool:
    nombre = limpiar_nombre(nombre_original)

    if any(
        palabra in nombre
        for palabra in [
            "RET", "RETURN", "RENDIMIENTO",
            "RENTABILIDAD", "PCTCHANGE",
        ]
    ):
        return True

    valores = pd.to_numeric(
        serie,
        errors="coerce",
    ).dropna()

    if len(valores) < 20:
        return True

    mediana = valores.abs().median()
    p99 = valores.abs().quantile(0.99)

    return bool(
        pd.notna(mediana)
        and pd.notna(p99)
        and mediana <= 0.08
        and p99 <= 0.50
    )



def preparar_mercado(
    ruta: Path,
    formato: str = "ancho",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    original = leer_csv_flexible(ruta)
    fecha = columna_fecha(original.columns)

    if fecha is None:
        raise ValueError(
            f"No se identificó la fecha en {ruta.name}."
        )

    original[fecha], control_fecha_mercado = parsear_fechas_robusto(
        original[fecha],
        nombre_origen=f"{ruta.name}:{fecha}",
    )

    factores_deseados = (
        FACTORES_PUBLICOS + FACTORES_EXTRA_BASE
    )
    control = []

    if formato == "largo":
        factor_col = detectar_columna(
            original.columns,
            {
                "FACTOR", "TICKER", "SYMBOL", "SIMBOLO",
                "ACTIVO", "INSTRUMENTO", "SERIE",
            },
        )
        valor_col = detectar_columna(
            original.columns,
            {
                "RETORNO", "RETURN", "RETORNODIARIO",
                "RENDIMIENTO", "RENTABILIDADDIARIA",
                "ADJCLOSE", "CLOSE", "PRICE", "PRECIO",
                "VALOR", "NIVEL",
            },
        )

        if factor_col is None or valor_col is None:
            raise ValueError(
                f"El archivo {ruta.name} parecía largo, pero no "
                "se identificaron factor y valor."
            )

        largo = original[
            [fecha, factor_col, valor_col]
        ].copy()
        largo["factor_canonico"] = largo[
            factor_col
        ].map(canon_factor)
        largo["valor_numerico"] = pd.to_numeric(
            largo[valor_col],
            errors="coerce",
        )
        largo = largo[
            largo["factor_canonico"].isin(
                factores_deseados
            )
        ].dropna(
            subset=[fecha, "factor_canonico", "valor_numerico"]
        )

        ancho_original = (
            largo.pivot_table(
                index=fecha,
                columns="factor_canonico",
                values="valor_numerico",
                aggfunc="last",
            )
            .sort_index()
        )

        mercado = pd.DataFrame(
            index=ancho_original.index
        )

        for factor in ancho_original.columns:
            serie = ancho_original[factor]
            es_retorno = serie_es_retorno(
                serie,
                valor_col,
            )

            if es_retorno:
                retorno = serie
                modo = "retorno_existente_largo"
            else:
                retorno = serie.pct_change(
                    fill_method=None
                )
                modo = "nivel_largo_convertido_pct_change"

            mercado[factor] = retorno
            control.append(
                {
                    "factor": factor,
                    "columna_original": (
                        f"{factor_col}/{valor_col}"
                    ),
                    "modo": modo,
                    "observaciones": int(
                        retorno.notna().sum()
                    ),
                }
            )

    else:
        mapa = {}

        for columna in original.columns:
            factor = canon_factor(columna)
            if factor and factor not in mapa:
                mapa[factor] = columna

        factores_presentes = [
            factor
            for factor in factores_deseados
            if factor in mapa
        ]

        if len(
            set(factores_presentes)
            .intersection(FACTORES_PUBLICOS)
        ) < 8:
            raise ValueError(
                "El archivo ancho detectado tiene menos de ocho "
                "factores públicos reconocidos. Columnas: "
                + ", ".join(map(str, original.columns[:30]))
            )

        mercado = pd.DataFrame(
            {"fecha": original[fecha]}
        )

        for factor in factores_presentes:
            columna = mapa[factor]
            serie = pd.to_numeric(
                original[columna],
                errors="coerce",
            )

            es_retorno = serie_es_retorno(
                serie,
                columna,
            )

            if es_retorno:
                retorno = serie
                modo = "retorno_existente"
            else:
                retorno = serie.pct_change(
                    fill_method=None
                )
                modo = "nivel_convertido_pct_change"

            mercado[factor] = retorno
            control.append(
                {
                    "factor": factor,
                    "columna_original": columna,
                    "modo": modo,
                    "observaciones": int(
                        retorno.notna().sum()
                    ),
                }
            )

        mercado = (
            mercado.dropna(subset=["fecha"])
            .sort_values("fecha")
            .drop_duplicates("fecha", keep="last")
            .set_index("fecha")
        )

    if mercado.index.name != "fecha":
        mercado.index.name = "fecha"

    proporcion = mercado.notna().mean(axis=1)
    mercado = mercado[
        proporcion >= 0.40
    ].copy()

    # No interpolamos retornos. Los faltantes se dejan en cero para
    # representar ausencia de señal ese día.
    mercado = mercado.fillna(0.0)

    return mercado, pd.DataFrame(control)


def preparar_ventanas(
    ruta: Path,
) -> pd.DataFrame:
    ventanas = pd.read_csv(
        ruta,
        parse_dates=[
            "fecha_cartera",
            "fecha_disponible",
            "fecha_fin_validez",
        ],
    )

    for columna in (
        FACTORES_PUBLICOS
        + [
            "PRIVATE_ALTERNATIVES",
            "RESIDUAL_NO_MAPEADO",
            "PESO_EXCLUIDO_POR_CONFIANZA",
            "peso_publico_modelado",
            "error_cobertura_pct",
            "factor_reescala",
        ]
    ):
        if columna not in ventanas.columns:
            ventanas[columna] = 0.0

        ventanas[columna] = pd.to_numeric(
            ventanas[columna],
            errors="coerce",
        ).fillna(0.0)

    if "ventana_utilizable" in ventanas.columns:
        ventanas["ventana_utilizable"] = convertir_booleano(
            ventanas["ventana_utilizable"]
        )
        ventanas = ventanas[
            ventanas["ventana_utilizable"]
        ].copy()

    return ventanas


def expandir_ventanas_diarias(
    ventanas: pd.DataFrame,
    fechas_mercado: pd.DatetimeIndex,
) -> pd.DataFrame:
    columnas = (
        [
            "escenario",
            "variante_confianza",
            "afp",
            "periodo",
            "fecha_cartera",
            "fecha_disponible",
            "fecha_fin_validez",
            "estado_cobertura",
        ]
        + FACTORES_PUBLICOS
        + CONTROLES_EXPOSICION
    )

    partes = []

    for _, fila in ventanas.iterrows():
        fechas = fechas_mercado[
            (fechas_mercado >= fila["fecha_disponible"])
            & (fechas_mercado <= fila["fecha_fin_validez"])
        ]

        if len(fechas) == 0:
            continue

        bloque = pd.DataFrame(
            {
                "fecha": fechas,
                "escenario": fila["escenario"],
                "variante_confianza": fila[
                    "variante_confianza"
                ],
                "afp": fila["afp"],
                "periodo": fila["periodo"],
                "fecha_cartera": fila["fecha_cartera"],
                "fecha_disponible": fila["fecha_disponible"],
                "fecha_fin_validez": fila["fecha_fin_validez"],
                "estado_cobertura": fila[
                    "estado_cobertura"
                ],
            }
        )

        for columna in FACTORES_PUBLICOS + CONTROLES_EXPOSICION:
            bloque[columna] = fila[columna]

        partes.append(bloque)

    if not partes:
        raise ValueError(
            "No se pudo expandir ninguna ventana a fechas de mercado."
        )

    diaria = pd.concat(
        partes,
        ignore_index=True,
    )

    diaria = (
        diaria.sort_values(
            [
                "escenario",
                "variante_confianza",
                "afp",
                "fecha",
                "fecha_cartera",
            ]
        )
        .drop_duplicates(
            subset=[
                "escenario",
                "variante_confianza",
                "afp",
                "fecha",
            ],
            keep="last",
        )
    )

    return diaria


def añadir_afp_ajena(
    diaria: pd.DataFrame,
) -> pd.DataFrame:
    claves = [
        "escenario",
        "variante_confianza",
        "fecha",
    ]

    sumas = (
        diaria.groupby(
            claves,
            as_index=False,
        )[FACTORES_PUBLICOS]
        .sum()
    )
    conteos = (
        diaria.groupby(
            claves,
            as_index=False,
        )["afp"]
        .nunique()
        .rename(columns={"afp": "numero_afp"})
    )

    total = sumas.merge(
        conteos,
        on=claves,
        how="left",
        validate="one_to_one",
    )

    salida = diaria.merge(
        total,
        on=claves,
        how="left",
        validate="many_to_one",
        suffixes=("", "_suma_afp"),
    )

    for factor in FACTORES_PUBLICOS:
        denominador = (
            salida["numero_afp"] - 1
        ).replace(0, np.nan)

        salida[f"{factor}_ajena"] = (
            salida[f"{factor}_suma_afp"]
            - salida[factor]
        ) / denominador

        salida.drop(
            columns=[f"{factor}_suma_afp"],
            inplace=True,
        )

    return salida


def añadir_señales(
    diaria: pd.DataFrame,
    mercado: pd.DataFrame,
) -> tuple[pd.DataFrame, list[str]]:
    factores_disponibles = [
        factor
        for factor in FACTORES_PUBLICOS
        if factor in mercado.columns
    ]

    factores_faltantes = [
        factor
        for factor in FACTORES_PUBLICOS
        if factor not in mercado.columns
    ]

    mercado_reset = mercado.reset_index()
    salida = diaria.merge(
        mercado_reset,
        on="fecha",
        how="left",
        validate="many_to_one",
        suffixes=("_peso", "_ret"),
    )

    rng = np.random.default_rng(SEMILLA)
    permutados = factores_disponibles.copy()
    rng.shuffle(permutados)
    mapa_permutado = dict(
        zip(
            factores_disponibles,
            permutados,
        )
    )

    señal = np.zeros(len(salida))
    señal_ajena = np.zeros(len(salida))
    señal_permutada = np.zeros(len(salida))

    peso_sin_serie = np.zeros(len(salida))

    for factor in factores_disponibles:
        peso = pd.to_numeric(
            salida[f"{factor}_peso"],
            errors="coerce",
        ).fillna(0.0)
        peso_ajeno = pd.to_numeric(
            salida[f"{factor}_ajena"],
            errors="coerce",
        ).fillna(0.0)
        retorno = pd.to_numeric(
            salida[f"{factor}_ret"],
            errors="coerce",
        ).fillna(0.0)

        retorno_perm = pd.to_numeric(
            salida[f"{mapa_permutado[factor]}_ret"],
            errors="coerce",
        ).fillna(0.0)

        señal += peso.to_numpy() * retorno.to_numpy()
        señal_ajena += (
            peso_ajeno.to_numpy()
            * retorno.to_numpy()
        )
        señal_permutada += (
            peso.to_numpy()
            * retorno_perm.to_numpy()
        )

    for factor in factores_faltantes:
        if f"{factor}_peso" in salida.columns:
            peso_sin_serie += pd.to_numeric(
                salida[f"{factor}_peso"],
                errors="coerce",
            ).fillna(0.0).to_numpy()

    salida["proxy_signal"] = señal
    salida["proxy_signal_ajena"] = señal_ajena
    salida["proxy_signal_permutada"] = señal_permutada
    salida["peso_factor_sin_serie"] = peso_sin_serie

    columnas_retorno = (
        factores_disponibles
        + [
            factor
            for factor in FACTORES_EXTRA_BASE
            if factor in mercado.columns
        ]
    )

    return salida, columnas_retorno


def crear_lags_mercado(
    mercado: pd.DataFrame,
    factores: list[str],
    lags: list[int],
) -> pd.DataFrame:
    salida = pd.DataFrame(index=mercado.index)

    for factor in factores:
        for lag in lags:
            salida[f"{factor}_lag{lag}"] = (
                mercado[factor].shift(lag)
            )

    return salida


def crear_lags_señales(
    df: pd.DataFrame,
    columnas: list[str],
    lags: list[int],
) -> pd.DataFrame:
    salida = df.copy().sort_values("fecha")

    for columna in columnas:
        for lag in lags:
            salida[f"{columna}_lag{lag}"] = (
                salida[columna].shift(lag)
            )

    return salida


def clip_entrenamiento(
    X_train: pd.DataFrame,
    X_test: pd.DataFrame,
    y_train: pd.Series,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series]:
    q_low = X_train.quantile(0.005)
    q_high = X_train.quantile(0.995)

    X_train_clip = X_train.clip(
        lower=q_low,
        upper=q_high,
        axis=1,
    )
    X_test_clip = X_test.clip(
        lower=q_low,
        upper=q_high,
        axis=1,
    )

    y_low = y_train.quantile(0.005)
    y_high = y_train.quantile(0.995)
    y_train_clip = y_train.clip(
        lower=y_low,
        upper=y_high,
    )

    return (
        X_train_clip,
        X_test_clip,
        y_train_clip,
    )


def prediccion_walk_forward(
    datos: pd.DataFrame,
    features: list[str],
) -> pd.DataFrame:
    datos = (
        datos[
            ["fecha", "retorno_cuota"] + features
        ]
        .dropna()
        .sort_values("fecha")
        .reset_index(drop=True)
    )

    if len(datos) <= MIN_ENTRENAMIENTO + 60:
        return pd.DataFrame()

    predicciones = []

    for inicio in range(
        MIN_ENTRENAMIENTO,
        len(datos),
        REFIT_CADA,
    ):
        fin = min(
            inicio + REFIT_CADA,
            len(datos),
        )

        train = datos.iloc[:inicio]
        test = datos.iloc[inicio:fin]

        X_train = train[features]
        X_test = test[features]
        y_train = train["retorno_cuota"]

        X_train, X_test, y_train = (
            clip_entrenamiento(
                X_train,
                X_test,
                y_train,
            )
        )

        modelo = Pipeline(
            [
                ("scaler", StandardScaler()),
                (
                    "ridge",
                    Ridge(
                        alpha=ALPHA_RIDGE,
                        fit_intercept=True,
                    ),
                ),
            ]
        )
        modelo.fit(X_train, y_train)
        pred = modelo.predict(X_test)

        bloque = pd.DataFrame(
            {
                "fecha": test["fecha"].to_numpy(),
                "y_real": test[
                    "retorno_cuota"
                ].to_numpy(),
                "y_pred": pred,
                "n_train": len(train),
            }
        )
        predicciones.append(bloque)

    if not predicciones:
        return pd.DataFrame()

    return pd.concat(
        predicciones,
        ignore_index=True,
    )


def metricas(
    pred: pd.DataFrame,
) -> dict[str, float]:
    y = pred["y_real"].to_numpy()
    yhat = pred["y_pred"].to_numpy()

    return {
        "observaciones_oos": len(pred),
        "rmse": float(
            mean_squared_error(
                y,
                yhat,
            ) ** 0.5
        ),
        "mse": float(
            mean_squared_error(y, yhat)
        ),
        "mae": float(
            mean_absolute_error(y, yhat)
        ),
        "r2": float(
            r2_score(y, yhat)
        ),
        "direccion_pct": float(
            (np.sign(y) == np.sign(yhat)).mean()
            * 100.0
        ),
    }


def bootstrap_mejora(
    base: pd.DataFrame,
    candidato: pd.DataFrame,
    reps: int = BOOTSTRAP_REPS,
) -> dict[str, float]:
    combinado = base[
        ["fecha", "y_real", "y_pred"]
    ].merge(
        candidato[
            ["fecha", "y_pred"]
        ],
        on="fecha",
        how="inner",
        suffixes=("_base", "_candidato"),
        validate="one_to_one",
    )

    if len(combinado) < 100:
        return {
            "bootstrap_n": len(combinado),
            "mejora_mse_pct": np.nan,
            "ic95_inferior_pct": np.nan,
            "ic95_superior_pct": np.nan,
            "prob_mejora": np.nan,
        }

    y = combinado["y_real"].to_numpy()
    e0 = (
        y - combinado["y_pred_base"].to_numpy()
    ) ** 2
    e1 = (
        y - combinado["y_pred_candidato"].to_numpy()
    ) ** 2

    mejora_observada = (
        (e0.mean() - e1.mean())
        / e0.mean()
        * 100.0
    )

    rng = np.random.default_rng(SEMILLA)
    n = len(combinado)
    resultados = []

    for _ in range(reps):
        indices = []

        while len(indices) < n:
            inicio = int(
                rng.integers(
                    0,
                    max(n - BOOTSTRAP_BLOQUE + 1, 1),
                )
            )
            indices.extend(
                range(
                    inicio,
                    min(
                        inicio + BOOTSTRAP_BLOQUE,
                        n,
                    ),
                )
            )

        idx = np.asarray(
            indices[:n],
            dtype=int,
        )

        mse0 = e0[idx].mean()
        mse1 = e1[idx].mean()

        if mse0 > 0:
            resultados.append(
                (mse0 - mse1) / mse0 * 100.0
            )

    arr = np.asarray(resultados)

    return {
        "bootstrap_n": n,
        "mejora_mse_pct": float(
            mejora_observada
        ),
        "ic95_inferior_pct": float(
            np.quantile(arr, 0.025)
        ),
        "ic95_superior_pct": float(
            np.quantile(arr, 0.975)
        ),
        "prob_mejora": float(
            (arr > 0).mean()
        ),
    }


def evaluar_grupo(
    grupo: pd.DataFrame,
    mercado: pd.DataFrame,
    cuotas_afp: pd.DataFrame,
    factores_base: list[str],
    afp: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    lags = LAGS_POR_AFP[afp]

    grupo = grupo.sort_values("fecha").copy()
    grupo = crear_lags_señales(
        grupo,
        [
            "proxy_signal",
            "proxy_signal_ajena",
            "proxy_signal_permutada",
        ],
        lags,
    )

    mercado_lag = crear_lags_mercado(
        mercado,
        factores_base,
        lags,
    ).reset_index()

    datos = grupo.merge(
        mercado_lag,
        on="fecha",
        how="left",
        validate="many_to_one",
    ).merge(
        cuotas_afp,
        on="fecha",
        how="inner",
        validate="many_to_one",
    )

    base_features = [
        f"{factor}_lag{lag}"
        for factor in factores_base
        for lag in lags
    ]
    proxy_features = [
        f"proxy_signal_lag{lag}"
        for lag in lags
    ]
    wrong_features = [
        f"proxy_signal_ajena_lag{lag}"
        for lag in lags
    ]
    shuffle_features = [
        f"proxy_signal_permutada_lag{lag}"
        for lag in lags
    ]

    controles = [
        columna
        for columna in (
            CONTROLES_EXPOSICION
            + ["peso_factor_sin_serie"]
        )
        if columna in datos.columns
    ]

    feature_sets = {
        "M0_base_mercado": base_features,
        "M1_proxy_directo": (
            proxy_features + controles
        ),
        "M2_hibrido": (
            base_features
            + proxy_features
            + controles
        ),
        "P1_proxy_afp_ajena": (
            base_features
            + wrong_features
            + controles
        ),
        "P2_proxy_pesos_permutados": (
            base_features
            + shuffle_features
            + controles
        ),
    }

    todas = sorted(
        {
            feature
            for features in feature_sets.values()
            for feature in features
        }
    )

    datos_comunes = datos.dropna(
        subset=[
            "retorno_cuota",
            *todas,
        ]
    ).copy()

    if len(datos_comunes) <= MIN_ENTRENAMIENTO + 60:
        return pd.DataFrame(), pd.DataFrame()

    resultados = []
    predicciones = []

    for modelo, features in feature_sets.items():
        pred = prediccion_walk_forward(
            datos_comunes,
            features,
        )

        if pred.empty:
            continue

        met = metricas(pred)
        met["modelo"] = modelo
        resultados.append(met)

        pred["modelo"] = modelo
        predicciones.append(pred)

    return (
        pd.DataFrame(resultados),
        pd.concat(
            predicciones,
            ignore_index=True,
        )
        if predicciones
        else pd.DataFrame(),
    )


def main() -> None:
    raiz = Path(__file__).resolve().parents[1]
    processed = raiz / "data" / "processed"

    ruta_ventanas = (
        processed
        / "ca0001_proxy_ventanas_publicacion_45d.csv"
    )

    if not ruta_ventanas.exists():
        raise FileNotFoundError(
            f"No existe: {ruta_ventanas}"
        )

    ruta_mercado, factores_detectados, formato_mercado = (
        descubrir_archivo_mercado(processed)
    )
    ruta_cuotas = descubrir_archivo_cuotas(
        processed
    )

    mercado, control_mercado = preparar_mercado(
        ruta_mercado,
        formato_mercado,
    )
    cuotas = preparar_cuotas(
        ruta_cuotas
    )
    control_fecha_cuotas = cuotas.attrs.get(
        "control_fecha",
        {},
    )
    control_integridad_cuotas = cuotas.attrs.get(
        "control_integridad",
        pd.DataFrame(),
    )

    ventanas = preparar_ventanas(
        ruta_ventanas
    )

    diaria = expandir_ventanas_diarias(
        ventanas,
        mercado.index,
    )
    diaria = añadir_afp_ajena(diaria)
    diaria, factores_base = añadir_señales(
        diaria,
        mercado,
    )

    resultados_todos = []
    predicciones_todas = []
    coberturas = []

    grupos = diaria.groupby(
        [
            "escenario",
            "variante_confianza",
            "afp",
        ],
        sort=True,
    )

    total_grupos = grupos.ngroups
    numero = 0

    for claves, grupo in grupos:
        numero += 1
        escenario, variante, afp = claves

        print(
            f"Evaluando {numero:02d}/{total_grupos:02d}: "
            f"{escenario} | {variante} | {afp}"
        )

        cuotas_afp = cuotas[
            cuotas["afp"].eq(afp)
        ][
            ["fecha", "retorno_cuota"]
        ].copy()

        resultados, predicciones = evaluar_grupo(
            grupo,
            mercado,
            cuotas_afp,
            factores_base,
            afp,
        )

        coberturas.append(
            {
                "escenario": escenario,
                "variante_confianza": variante,
                "afp": afp,
                "fechas_exposicion": grupo["fecha"].nunique(),
                "primera_fecha_exposicion": grupo["fecha"].min(),
                "ultima_fecha_exposicion": grupo["fecha"].max(),
                "observaciones_cuota": cuotas_afp["fecha"].nunique(),
                "factores_base": len(factores_base),
            }
        )

        if resultados.empty:
            continue

        resultados["escenario"] = escenario
        resultados["variante_confianza"] = variante
        resultados["afp"] = afp
        resultados_todos.append(resultados)

        predicciones["escenario"] = escenario
        predicciones["variante_confianza"] = variante
        predicciones["afp"] = afp
        predicciones_todas.append(predicciones)

    if not resultados_todos:
        raise RuntimeError(
            "No se generaron resultados OOS. Revise los archivos "
            "detectados y la cobertura temporal."
        )

    resultados = pd.concat(
        resultados_todos,
        ignore_index=True,
    )
    predicciones = pd.concat(
        predicciones_todas,
        ignore_index=True,
    )
    cobertura = pd.DataFrame(coberturas)

    bootstrap_filas = []

    for claves, grupo in predicciones.groupby(
        [
            "escenario",
            "variante_confianza",
            "afp",
        ],
        sort=True,
    ):
        escenario, variante, afp = claves

        base = grupo[
            grupo["modelo"].eq(
                "M0_base_mercado"
            )
        ]

        if base.empty:
            continue

        for modelo in [
            "M1_proxy_directo",
            "M2_hibrido",
            "P1_proxy_afp_ajena",
            "P2_proxy_pesos_permutados",
        ]:
            candidato = grupo[
                grupo["modelo"].eq(modelo)
            ]

            if candidato.empty:
                continue

            boot = bootstrap_mejora(
                base,
                candidato,
            )
            boot.update(
                {
                    "escenario": escenario,
                    "variante_confianza": variante,
                    "afp": afp,
                    "modelo": modelo,
                    "comparado_con": "M0_base_mercado",
                }
            )
            bootstrap_filas.append(boot)

        principal = grupo[
            grupo["modelo"].eq(
                "M2_hibrido"
            )
        ]

        if not principal.empty:
            for modelo in [
                "P1_proxy_afp_ajena",
                "P2_proxy_pesos_permutados",
            ]:
                placebo = grupo[
                    grupo["modelo"].eq(modelo)
                ]

                if placebo.empty:
                    continue

                boot = bootstrap_mejora(
                    placebo,
                    principal,
                )
                boot.update(
                    {
                        "escenario": escenario,
                        "variante_confianza": variante,
                        "afp": afp,
                        "modelo": "M2_hibrido",
                        "comparado_con": modelo,
                    }
                )
                bootstrap_filas.append(boot)

    bootstrap = pd.DataFrame(
        bootstrap_filas
    )

    resultados = resultados.merge(
        bootstrap[
            bootstrap["comparado_con"].eq(
                "M0_base_mercado"
            )
        ][
            [
                "escenario",
                "variante_confianza",
                "afp",
                "modelo",
                "mejora_mse_pct",
                "ic95_inferior_pct",
                "ic95_superior_pct",
                "prob_mejora",
            ]
        ],
        on=[
            "escenario",
            "variante_confianza",
            "afp",
            "modelo",
        ],
        how="left",
        validate="one_to_one",
    )

    ranking = (
        resultados[
            resultados["modelo"].isin(
                [
                    "M1_proxy_directo",
                    "M2_hibrido",
                ]
            )
        ]
        .sort_values(
            [
                "afp",
                "escenario",
                "mejora_mse_pct",
                "rmse",
            ],
            ascending=[True, True, False, True],
        )
        .copy()
    )
    ranking["ranking_afp_escenario"] = (
        ranking.groupby(
            ["afp", "escenario"]
        )
        .cumcount()
        .add(1)
    )

    archivos_detectados = pd.DataFrame(
        [
            {
                "tipo": "mercado",
                "ruta": str(ruta_mercado.resolve()),
                "detalle": (
                    f"formato={formato_mercado}; "
                    + " | ".join(
                        sorted(factores_detectados)
                    )
                ),
            },
            {
                "tipo": "cuotas",
                "ruta": str(ruta_cuotas.resolve()),
                "detalle": (
                    f"{cuotas['fecha'].min().date()} a "
                    f"{cuotas['fecha'].max().date()}"
                ),
            },
            {
                "tipo": "ventanas",
                "ruta": str(ruta_ventanas.resolve()),
                "detalle": f"{len(ventanas)} ventanas",
            },
        ]
    )

    control_fecha_df = pd.DataFrame(
        [control_fecha_cuotas]
    )

    if not isinstance(
        control_integridad_cuotas,
        pd.DataFrame,
    ):
        control_integridad_cuotas = pd.DataFrame()

    rutas = {
        "resultados": (
            processed
            / "ca0001_modelo41_resultados_oos.csv"
        ),
        "predicciones": (
            processed
            / "ca0001_modelo41_predicciones_oos.csv"
        ),
        "bootstrap": (
            processed
            / "ca0001_modelo41_bootstrap_placebos.csv"
        ),
        "ranking": (
            processed
            / "ca0001_modelo41_ranking_variantes.csv"
        ),
        "cobertura": (
            processed
            / "ca0001_modelo41_cobertura_temporal.csv"
        ),
        "archivos": (
            processed
            / "ca0001_modelo41_archivos_detectados.csv"
        ),
        "control_mercado": (
            processed
            / "ca0001_modelo41_control_factores_mercado.csv"
        ),
        "control_fecha_cuotas": (
            processed
            / "ca0001_modelo41_control_fecha_cuotas.csv"
        ),
        "control_integridad_cuotas": (
            processed
            / "ca0001_modelo41_control_integridad_cuotas.csv"
        ),
    }

    resultados.to_csv(
        rutas["resultados"],
        index=False,
        encoding="utf-8-sig",
    )
    predicciones.to_csv(
        rutas["predicciones"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    bootstrap.to_csv(
        rutas["bootstrap"],
        index=False,
        encoding="utf-8-sig",
    )
    ranking.to_csv(
        rutas["ranking"],
        index=False,
        encoding="utf-8-sig",
    )
    cobertura.to_csv(
        rutas["cobertura"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    archivos_detectados.to_csv(
        rutas["archivos"],
        index=False,
        encoding="utf-8-sig",
    )
    control_mercado.to_csv(
        rutas["control_mercado"],
        index=False,
        encoding="utf-8-sig",
    )
    control_fecha_df.to_csv(
        rutas["control_fecha_cuotas"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    control_integridad_cuotas.to_csv(
        rutas["control_integridad_cuotas"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )

    print("\nEVALUACIÓN OOS DE PROXIES TERMINADA")
    print("=" * 120)

    print("\nARCHIVOS DETECTADOS")
    print("-" * 120)
    print(archivos_detectados.to_string(index=False))

    print("\nCONTROL DE FECHAS Y CUOTAS")
    print("-" * 120)
    print(control_fecha_df.to_string(index=False))
    print()
    print(control_integridad_cuotas.to_string(index=False))

    print("\nRESULTADOS OOS: MODELO BASE, PROXY E HÍBRIDO")
    print("-" * 120)
    print(
        resultados[
            resultados["modelo"].isin(
                [
                    "M0_base_mercado",
                    "M1_proxy_directo",
                    "M2_hibrido",
                ]
            )
        ][
            [
                "escenario",
                "variante_confianza",
                "afp",
                "modelo",
                "observaciones_oos",
                "rmse",
                "mae",
                "r2",
                "direccion_pct",
                "mejora_mse_pct",
                "ic95_inferior_pct",
                "ic95_superior_pct",
                "prob_mejora",
            ]
        ]
        .sort_values(
            [
                "afp",
                "escenario",
                "variante_confianza",
                "modelo",
            ]
        )
        .to_string(index=False)
    )

    print("\nCOMPARACIÓN CON PLACEBOS")
    print("-" * 120)
    print(
        bootstrap[
            bootstrap["comparado_con"].isin(
                [
                    "P1_proxy_afp_ajena",
                    "P2_proxy_pesos_permutados",
                ]
            )
        ][
            [
                "escenario",
                "variante_confianza",
                "afp",
                "modelo",
                "comparado_con",
                "bootstrap_n",
                "mejora_mse_pct",
                "ic95_inferior_pct",
                "ic95_superior_pct",
                "prob_mejora",
            ]
        ]
        .sort_values(
            [
                "afp",
                "escenario",
                "variante_confianza",
                "comparado_con",
            ]
        )
        .to_string(index=False)
    )

    print("\nRANKING DE VARIANTES")
    print("-" * 120)
    print(
        ranking[
            ranking["ranking_afp_escenario"]
            <= 4
        ][
            [
                "afp",
                "escenario",
                "ranking_afp_escenario",
                "variante_confianza",
                "modelo",
                "observaciones_oos",
                "rmse",
                "r2",
                "mejora_mse_pct",
                "prob_mejora",
            ]
        ].to_string(index=False)
    )

    print("\nCOBERTURA TEMPORAL")
    print("-" * 120)
    print(
        cobertura.to_string(index=False)
    )

    print("\nArchivos creados:")
    for ruta in rutas.values():
        print(f" - {ruta.resolve()}")

    print(
        "\nCriterio de lectura:\n"
        "- M0 es el modelo de mercado sin información de composición.\n"
        "- M1 usa únicamente el retorno proxy ponderado y controles de "
        "cobertura.\n"
        "- M2 combina los factores de mercado con el retorno proxy "
        "ponderado.\n"
        "- P1 reemplaza la composición de la AFP por el promedio de las "
        "otras AFP disponibles en la misma fecha.\n"
        "- P2 conserva los pesos, pero permuta las etiquetas de los "
        "factores, destruyendo la correspondencia económica.\n"
        "- Una mejora convincente exige M2 superior a M0, intervalo "
        "bootstrap favorable y ventaja frente a los placebos.\n"
        "- La evaluación es temporal, con entrenamiento expansivo, "
        "reestimación cada 21 observaciones y sin utilizar composiciones "
        "antes de su ventana pública."
    )


if __name__ == "__main__":
    main()
