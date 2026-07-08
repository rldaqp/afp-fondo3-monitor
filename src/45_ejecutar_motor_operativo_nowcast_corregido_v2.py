from __future__ import annotations

import json
import os
import re
import unicodedata
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


AFPS = ["Habitat", "Integra", "Prima", "Profuturo"]

MODELO_BASE = "M0_base_mercado"
MODELO_HIBRIDO = "M2_hibrido"

MAX_DIAS_DESACTUALIZACION = 7


def limpiar_nombre(valor: object) -> str:
    texto = str(valor).strip().upper()
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(
        caracter
        for caracter in texto
        if not unicodedata.combining(caracter)
    )
    return re.sub(r"[^A-Z0-9]+", "", texto)


def leer_csv_flexible(
    ruta: Path,
    nrows: int | None = None,
) -> pd.DataFrame:
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

    ultimo_error: Exception | None = None

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
    Convierte valores booleanos representados como True/False, 1/0,
    sí/no o yes/no. Los vacíos se interpretan como False.
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

def detectar_columna(
    columnas: Iterable[object],
    alias: set[str],
) -> str | None:
    alias_limpios = {
        limpiar_nombre(valor)
        for valor in alias
    }

    for columna in columnas:
        if limpiar_nombre(columna) in alias_limpios:
            return str(columna)

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
                return str(columna)

    return None


def normalizar_afp(valor: object) -> str | None:
    limpio = limpiar_nombre(valor)

    for afp in AFPS:
        if limpiar_nombre(afp) in limpio:
            return afp

    return None


def normalizar_modelo(
    valor: object,
    nombre_archivo: str = "",
) -> str:
    texto = (
        limpiar_nombre(valor)
        + limpiar_nombre(nombre_archivo)
    )

    if any(
        token in texto
        for token in [
            "M2HIBRIDO",
            "HIBRIDO",
            "HYBRID",
            "COMPOSICION",
        ]
    ):
        return MODELO_HIBRIDO

    if any(
        token in texto
        for token in [
            "M0BASEMERCADO",
            "BASEMERCADO",
            "MODELOBASE",
            "BASE",
        ]
    ):
        return MODELO_BASE

    return "modelo_no_identificado"



def columna_fecha(
    columnas: Iterable[object],
) -> str | None:
    """
    Fecha genérica de respaldo. Para el nowcast se usa primero
    detectar_fechas_nowcast(), que prioriza la fecha objetivo.
    """
    return detectar_columna(
        columnas,
        {
            "fecha_prediccion",
            "fecha_objetivo",
            "fecha_nowcast",
            "fecha_estimada",
            "fecha_proyectada",
            "fecha_mercado",
            "fecha",
            "date",
            "fecha_referencia",
            "fecha_modelo",
            "trading_date",
            "fecha_ultima_oficial",
        },
    )


def columna_prediccion(
    columnas: Iterable[object],
) -> str | None:
    """
    Detecta únicamente columnas que representen un retorno pronosticado.

    No acepta palabras genéricas como 'nowcast' porque podrían aparecer
    en columnas de horizonte, por ejemplo dias_nowcast.
    """
    alias_exactos = {
        "PREDICCION",
        "PREDICTION",
        "FORECAST",
        "YPRED",
        "RETORNOPREDICHO",
        "RETORNOESTIMADO",
        "RETORNOESTIMADODIA",
        "RETORNOESTIMADOPCT",
        "RETORNOPRONOSTICADO",
        "PREDICCIONRETORNO",
        "PREDICCIONRETORNODIA",
        "PREDICCIONRETORNOPCT",
        "RENTABILIDADESTIMADA",
        "RENTABILIDADPREDICHA",
        "NOWCASTRETORNO",
        "RETORNONOWCAST",
        "ESTIMACIONRETORNO",
    }

    prohibidos = {
        "DIA",
        "DIAS",
        "HORIZONTE",
        "LAG",
        "REZAGO",
        "ATRASO",
        "VENTANA",
        "CONTEO",
        "NUMERO",
        "FECHA",
        "OFICIAL",
        "ESTADO",
        "MODELO",
    }

    # Primero, coincidencia exacta.
    for columna in columnas:
        limpio = limpiar_nombre(columna)
        if limpio in alias_exactos:
            return str(columna)

    candidatos: list[tuple[int, str]] = []

    for columna in columnas:
        limpio = limpiar_nombre(columna)

        if any(token in limpio for token in prohibidos):
            continue

        tiene_retorno = any(
            token in limpio
            for token in [
                "RETORNO",
                "RENTABILIDAD",
                "RETURN",
            ]
        )
        tiene_prediccion = any(
            token in limpio
            for token in [
                "PRED",
                "ESTIM",
                "FORECAST",
                "PRONOST",
                "NOWCAST",
            ]
        )

        if tiene_retorno and tiene_prediccion:
            puntaje = (
                10 * ("RETORNO" in limpio)
                + 8 * ("ESTIMADO" in limpio)
                + 8 * ("PREDICHO" in limpio)
                + 6 * ("PREDICCION" in limpio)
                + 4 * ("DIA" in limpio)
                + 2 * ("PCT" in limpio)
            )
            candidatos.append(
                (puntaje, str(columna))
            )

    if not candidatos:
        return None

    candidatos.sort(reverse=True)
    return candidatos[0][1]


def columna_horizonte(
    columnas: Iterable[object],
) -> str | None:
    return detectar_columna(
        columnas,
        {
            "dia_nowcast",
            "dias_nowcast",
            "horizonte",
            "horizonte_dias",
            "dias_horizonte",
            "paso",
            "step",
            "lead",
            "lead_days",
        },
    )


def detectar_fechas_nowcast(
    df: pd.DataFrame,
) -> tuple[pd.Series, pd.Series, str, str | None, str | None]:
    """
    Devuelve:
      fecha_objetivo, fecha_ancla, método, columna_objetivo, columna_horizonte

    Prioriza una fecha futura/objetivo. Si solo existe fecha_ultima_oficial
    y un horizonte 1,2,3, deriva la fecha objetivo sumando días.
    """
    columnas = list(df.columns)

    objetivo = detectar_columna(
        columnas,
        {
            "fecha_prediccion",
            "fecha_objetivo",
            "fecha_nowcast",
            "fecha_estimada",
            "fecha_proyectada",
            "fecha_forecast",
            "fecha_pronostico",
            "fecha_mercado_objetivo",
        },
    )

    ancla = detectar_columna(
        columnas,
        {
            "fecha_ultima_oficial",
            "fecha_oficial",
            "fecha_base",
            "fecha_referencia",
            "fecha_corte",
        },
    )

    horizonte = columna_horizonte(columnas)

    if objetivo is not None:
        fecha_objetivo = pd.to_datetime(
            df[objetivo],
            errors="coerce",
        )
        fecha_ancla = (
            pd.to_datetime(
                df[ancla],
                errors="coerce",
            )
            if ancla is not None
            else fecha_objetivo
        )
        return (
            fecha_objetivo,
            fecha_ancla,
            "fecha_objetivo_explicita",
            objetivo,
            horizonte,
        )

    if ancla is not None and horizonte is not None:
        fecha_ancla = pd.to_datetime(
            df[ancla],
            errors="coerce",
        )
        dias = pd.to_numeric(
            df[horizonte],
            errors="coerce",
        )
        fecha_objetivo = (
            fecha_ancla
            + pd.to_timedelta(
                dias,
                unit="D",
            )
        )
        return (
            fecha_objetivo,
            fecha_ancla,
            "fecha_ancla_mas_horizonte",
            None,
            horizonte,
        )

    generica = detectar_columna(
        columnas,
        {
            "fecha",
            "date",
            "trading_date",
            "fecha_mercado",
            "fecha_modelo",
            "fecha_referencia",
            "fecha_ultima_oficial",
        },
    )

    if generica is None:
        vacia = pd.Series(
            pd.NaT,
            index=df.index,
            dtype="datetime64[ns]",
        )
        return (
            vacia,
            vacia,
            "sin_fecha",
            None,
            horizonte,
        )

    fecha = pd.to_datetime(
        df[generica],
        errors="coerce",
    )
    return (
        fecha,
        fecha,
        "fecha_generica",
        generica,
        horizonte,
    )


def normalizar_escala_prediccion(
    serie: pd.Series,
    nombre_columna: str,
) -> tuple[pd.Series, str]:
    valores = pd.to_numeric(
        serie,
        errors="coerce",
    )
    limpio = limpiar_nombre(nombre_columna)
    validos = valores.dropna()

    if validos.empty:
        return valores, "sin_datos"

    p99 = float(
        validos.abs().quantile(0.99)
    )
    mediana = float(
        validos.abs().median()
    )

    columna_pct = any(
        token in limpio
        for token in [
            "PCT",
            "PORCENTAJE",
            "PERCENT",
        ]
    )

    if columna_pct:
        return valores / 100.0, "porcentaje_a_decimal"

    # Respaldo para series claramente guardadas como porcentaje.
    if (
        p99 > 0.20
        and p99 <= 20.0
        and mediana > 0.01
    ):
        return valores / 100.0, "escala_porcentual_inferida"

    return valores, "decimal"


def columna_modelo(
    columnas: Iterable[object],
) -> str | None:
    return detectar_columna(
        columnas,
        {
            "modelo",
            "model",
            "tipo_modelo",
            "nombre_modelo",
        },
    )


def columna_afp(
    columnas: Iterable[object],
) -> str | None:
    return detectar_columna(
        columnas,
        {
            "afp",
            "administradora",
            "nombre_afp",
        },
    )


def leer_fecha_maxima_mercado(
    processed: Path,
) -> pd.Timestamp:
    ruta = (
        processed
        / "mercados_factores_modelo.csv"
    )

    if not ruta.exists():
        return pd.NaT

    df = leer_csv_flexible(ruta)
    fecha = columna_fecha(df.columns)

    if fecha is None:
        fecha = str(df.columns[0])

    fechas = pd.to_datetime(
        df[fecha],
        errors="coerce",
    )

    return fechas.max()



def evaluar_candidato(
    ruta: Path,
    fecha_mercado: pd.Timestamp,
    configuracion: pd.DataFrame,
) -> dict[str, object] | None:
    try:
        df = leer_csv_flexible(ruta)
    except Exception:
        return None

    columnas = list(df.columns)
    pred = columna_prediccion(columnas)
    afp_col = columna_afp(columnas)
    modelo_col = columna_modelo(columnas)

    columnas_afp = [
        str(columna)
        for columna in columnas
        if normalizar_afp(columna) is not None
    ]

    nombre = ruta.name.lower()

    exclusiones = [
        "modelo41_predicciones_oos",
        "modelo42_perdidas",
        "modelo43_predicciones",
        "modelo45_",
        "resumen_modelos",
        "estabilidad_anual",
        "rolling_252",
        "bootstrap",
        "ranking",
        "control",
        "base_maestra",
        "historico_ancho",
        "auditoria",
        "atribucion",
        "ultima_fecha",
    ]

    if any(
        exclusion in nombre
        for exclusion in exclusiones
    ):
        return None

    formato_largo = (
        pred is not None
        and afp_col is not None
    )
    formato_ancho = (
        pred is None
        and len(columnas_afp) >= 3
        and any(
            token in nombre
            for token in [
                "nowcast",
                "predic",
                "forecast",
                "estimacion",
            ]
        )
    )

    if not (
        formato_largo
        or formato_ancho
    ):
        return None

    (
        fecha_objetivo,
        fecha_ancla,
        metodo_fecha,
        columna_fecha_objetivo,
        horizonte_col,
    ) = detectar_fechas_nowcast(df)

    if formato_largo:
        pred_normalizada, escala = (
            normalizar_escala_prediccion(
                df[pred],
                pred,
            )
        )
        afp_norm = df[afp_col].map(
            normalizar_afp
        )

        if modelo_col is not None:
            modelos = df[modelo_col].map(
                lambda valor: normalizar_modelo(
                    valor,
                    ruta.name,
                )
            )
        else:
            modelo_archivo = normalizar_modelo(
                "",
                ruta.name,
            )
            modelos = pd.Series(
                modelo_archivo,
                index=df.index,
            )

        muestra = pd.DataFrame(
            {
                "fecha": fecha_objetivo,
                "afp": afp_norm,
                "prediccion": pred_normalizada,
                "modelo": modelos,
            }
        ).dropna(
            subset=[
                "fecha",
                "afp",
                "prediccion",
            ]
        )

    else:
        # Solo se admite ancho cuando el propio nombre indica que es
        # un archivo de predicción.
        columnas_afp_map = {
            normalizar_afp(columna): str(columna)
            for columna in columnas_afp
            if normalizar_afp(columna)
        }

        largo = (
            df[
                list(
                    dict.fromkeys(
                        [
                            columna
                            for columna in [
                                columna_fecha_objetivo,
                                horizonte_col,
                            ]
                            if columna is not None
                        ]
                        + list(
                            columnas_afp_map.values()
                        )
                    )
                )
            ]
            .copy()
        )

        largo["__fecha_objetivo__"] = fecha_objetivo
        largo = largo.melt(
            id_vars=["__fecha_objetivo__"],
            value_vars=list(
                columnas_afp_map.values()
            ),
            var_name="columna_afp",
            value_name="prediccion_original",
        )

        inverso = {
            columna: afp_nombre
            for afp_nombre, columna
            in columnas_afp_map.items()
        }

        pred_normalizada, escala = (
            normalizar_escala_prediccion(
                largo["prediccion_original"],
                "prediccion",
            )
        )

        modelo_archivo = normalizar_modelo(
            "",
            ruta.name,
        )

        muestra = pd.DataFrame(
            {
                "fecha": largo[
                    "__fecha_objetivo__"
                ],
                "afp": largo[
                    "columna_afp"
                ].map(inverso),
                "prediccion": pred_normalizada,
                "modelo": modelo_archivo,
            }
        ).dropna(
            subset=[
                "fecha",
                "afp",
                "prediccion",
            ]
        )
        pred = "columnas_afp_anchas"

    if muestra.empty:
        return None

    fecha_maxima = muestra["fecha"].max()
    latest = muestra[
        muestra["fecha"].eq(
            fecha_maxima
        )
    ].copy()

    afp_latest = int(
        latest["afp"].nunique()
    )
    modelos_latest = sorted(
        latest["modelo"].dropna().unique()
    )

    requeridos = {
        str(fila["afp"]): str(
            fila["modelo_operativo_actual"]
        )
        for _, fila in configuracion.iterrows()
    }

    cumple_modelo = 0

    for afp_nombre, requerido in requeridos.items():
        existe = (
            (
                latest["afp"].eq(
                    afp_nombre
                )
            )
            & (
                latest["modelo"].eq(
                    requerido
                )
            )
        ).any()
        cumple_modelo += int(existe)

    p99_abs = float(
        latest["prediccion"]
        .abs()
        .quantile(0.99)
    )
    mediana_abs = float(
        latest["prediccion"]
        .abs()
        .median()
    )

    plausible = bool(
        np.isfinite(p99_abs)
        and p99_abs <= 0.20
        and mediana_abs <= 0.10
    )

    preferencia = (
        25 * ("nowcast" in nombre)
        + 20 * ("operativo" in nombre)
        + 12 * ("predic" in nombre)
        + 10 * ("forecast" in nombre)
        + 10 * ("fondo3" in nombre)
        + 8 * ("modelo_base" in nombre)
        - 18 * ("historico" in nombre)
        - 18 * ("validacion" in nombre)
        - 10 * ("detalle" in nombre)
    )

    if metodo_fecha == "fecha_objetivo_explicita":
        preferencia += 20
    elif metodo_fecha == "fecha_ancla_mas_horizonte":
        preferencia += 18

    dias_diferencia = np.nan

    if (
        pd.notna(fecha_mercado)
        and pd.notna(fecha_maxima)
    ):
        dias_diferencia = int(
            (
                fecha_mercado.normalize()
                - fecha_maxima.normalize()
            ).days
        )

        if abs(dias_diferencia) <= 1:
            preferencia += 45
        elif abs(dias_diferencia) <= 3:
            preferencia += 30
        elif abs(dias_diferencia) <= 7:
            preferencia += 10
        elif dias_diferencia > 30:
            preferencia -= 30

    preferencia += 8 * afp_latest
    preferencia += 20 * cumple_modelo
    preferencia += 20 if plausible else -100

    if "modelo_no_identificado" in modelos_latest:
        preferencia -= 40

    return {
        "ruta": str(ruta.resolve()),
        "archivo": ruta.name,
        "formato": (
            "largo"
            if formato_largo
            else "ancho"
        ),
        "columna_fecha_objetivo": columna_fecha_objetivo,
        "metodo_fecha": metodo_fecha,
        "columna_horizonte": horizonte_col,
        "columna_prediccion": pred,
        "columna_afp": afp_col,
        "columna_modelo": modelo_col,
        "escala_prediccion": escala,
        "fecha_maxima": fecha_maxima,
        "fecha_mercado": fecha_mercado,
        "dias_vs_mercado": dias_diferencia,
        "observaciones": int(len(muestra)),
        "afp_latest": afp_latest,
        "modelos_latest": " | ".join(
            modelos_latest
        ),
        "modelos_requeridos_cumplidos": (
            cumple_modelo
        ),
        "p99_abs_prediccion": p99_abs,
        "mediana_abs_prediccion": mediana_abs,
        "prediccion_plausible": plausible,
        "puntaje": preferencia,
    }


def descubrir_nowcast(
    processed: Path,
    fecha_mercado: pd.Timestamp,
    configuracion: pd.DataFrame,
) -> tuple[Path | None, pd.DataFrame]:
    ruta_forzada = os.environ.get(
        "AFP_NOWCAST_CSV",
        "",
    ).strip()

    if ruta_forzada:
        ruta = Path(ruta_forzada)

        if not ruta.exists():
            raise FileNotFoundError(
                "AFP_NOWCAST_CSV apunta a una "
                f"ruta inexistente: {ruta}"
            )

        candidato = evaluar_candidato(
            ruta,
            fecha_mercado,
            configuracion,
        )

        if candidato is None:
            raise ValueError(
                "El archivo indicado en AFP_NOWCAST_CSV "
                "no contiene una columna estricta de retorno "
                "pronosticado o no supera la validación estructural."
            )

        auditoria = pd.DataFrame(
            [candidato]
        )

        if not bool(
            auditoria.iloc[0][
                "prediccion_plausible"
            ]
        ):
            raise ValueError(
                "El archivo forzado contiene valores de "
                "predicción implausibles."
            )

        return ruta, auditoria

    candidatos = []

    for ruta in processed.rglob("*.csv"):
        candidato = evaluar_candidato(
            ruta,
            fecha_mercado,
            configuracion,
        )

        if candidato is not None:
            candidatos.append(candidato)

    if not candidatos:
        return None, pd.DataFrame()

    auditoria = (
        pd.DataFrame(candidatos)
        .sort_values(
            [
                "prediccion_plausible",
                "modelos_requeridos_cumplidos",
                "puntaje",
                "fecha_maxima",
                "afp_latest",
            ],
            ascending=[
                False,
                False,
                False,
                False,
                False,
            ],
        )
        .reset_index(drop=True)
    )

    elegibles = auditoria[
        auditoria[
            "prediccion_plausible"
        ].eq(True)
        & auditoria[
            "afp_latest"
        ].ge(4)
        & auditoria[
            "modelos_requeridos_cumplidos"
        ].ge(4)
    ]

    if elegibles.empty:
        return None, auditoria

    return (
        Path(elegibles.iloc[0]["ruta"]),
        auditoria,
    )



def preparar_nowcast(
    ruta: Path,
) -> pd.DataFrame:
    df = leer_csv_flexible(ruta)
    pred = columna_prediccion(df.columns)
    afp_col = columna_afp(df.columns)
    modelo_col = columna_modelo(df.columns)

    (
        fecha_objetivo,
        fecha_ancla,
        metodo_fecha,
        columna_fecha_objetivo,
        horizonte_col,
    ) = detectar_fechas_nowcast(df)

    if pred is not None and afp_col is not None:
        pred_normalizada, escala = (
            normalizar_escala_prediccion(
                df[pred],
                pred,
            )
        )

        if modelo_col is not None:
            modelos = df[modelo_col].map(
                lambda valor: normalizar_modelo(
                    valor,
                    ruta.name,
                )
            )
        else:
            modelos = pd.Series(
                normalizar_modelo(
                    "",
                    ruta.name,
                ),
                index=df.index,
            )

        salida = pd.DataFrame(
            {
                "fecha_prediccion": (
                    fecha_objetivo
                ),
                "fecha_ancla": fecha_ancla,
                "afp": df[afp_col].map(
                    normalizar_afp
                ),
                "prediccion_original": pd.to_numeric(
                    df[pred],
                    errors="coerce",
                ),
                "prediccion": pred_normalizada,
                "modelo_fuente": modelos,
                "metodo_fecha": metodo_fecha,
                "escala_prediccion": escala,
                "columna_prediccion": pred,
                "columna_horizonte": horizonte_col,
            }
        )

    else:
        columnas_afp = {
            normalizar_afp(columna): str(columna)
            for columna in df.columns
            if normalizar_afp(columna)
        }

        if len(columnas_afp) < 3:
            raise ValueError(
                f"{ruta.name} no tiene formato largo "
                "ni columnas anchas de AFP."
            )

        base = df.copy()
        base["__fecha_objetivo__"] = (
            fecha_objetivo
        )
        base["__fecha_ancla__"] = fecha_ancla

        largo = base.melt(
            id_vars=[
                "__fecha_objetivo__",
                "__fecha_ancla__",
            ],
            value_vars=list(
                columnas_afp.values()
            ),
            var_name="columna_afp",
            value_name="prediccion_original",
        )

        inverso = {
            columna: afp_nombre
            for afp_nombre, columna
            in columnas_afp.items()
        }

        pred_normalizada, escala = (
            normalizar_escala_prediccion(
                largo[
                    "prediccion_original"
                ],
                "prediccion",
            )
        )

        salida = pd.DataFrame(
            {
                "fecha_prediccion": largo[
                    "__fecha_objetivo__"
                ],
                "fecha_ancla": largo[
                    "__fecha_ancla__"
                ],
                "afp": largo[
                    "columna_afp"
                ].map(inverso),
                "prediccion_original": (
                    pd.to_numeric(
                        largo[
                            "prediccion_original"
                        ],
                        errors="coerce",
                    )
                ),
                "prediccion": (
                    pred_normalizada
                ),
                "modelo_fuente": (
                    normalizar_modelo(
                        "",
                        ruta.name,
                    )
                ),
                "metodo_fecha": metodo_fecha,
                "escala_prediccion": escala,
                "columna_prediccion": (
                    "columnas_afp_anchas"
                ),
                "columna_horizonte": horizonte_col,
            }
        )

    salida = (
        salida.dropna(
            subset=[
                "fecha_prediccion",
                "afp",
                "prediccion",
            ]
        )
        .sort_values(
            [
                "afp",
                "fecha_prediccion",
            ]
        )
        .drop_duplicates(
            subset=[
                "fecha_prediccion",
                "afp",
                "modelo_fuente",
            ],
            keep="last",
        )
    )

    if salida.empty:
        raise ValueError(
            f"{ruta.name} no produjo predicciones válidas."
        )

    p99 = float(
        salida["prediccion"]
        .abs()
        .quantile(0.99)
    )

    if p99 > 0.20:
        raise ValueError(
            f"{ruta.name} contiene predicciones implausibles "
            f"después de normalizar la escala: p99={p99:.6f}."
        )

    return salida


def cargar_umbral_error(
    processed: Path,
) -> pd.DataFrame:
    ruta = (
        processed
        / "ca0001_modelo41_resultados_oos.csv"
    )

    if not ruta.exists():
        return pd.DataFrame(
            {
                "afp": AFPS,
                "rmse_referencia": np.nan,
            }
        )

    resultados = leer_csv_flexible(ruta)

    filtro = resultados[
        resultados["escenario"].eq(
            "ampliado_15pct"
        )
        & resultados[
            "variante_confianza"
        ].eq("alta")
        & resultados["modelo"].eq(
            MODELO_BASE
        )
    ].copy()

    filtro["rmse"] = pd.to_numeric(
        filtro["rmse"],
        errors="coerce",
    )

    return filtro[
        ["afp", "rmse"]
    ].rename(
        columns={
            "rmse": "rmse_referencia",
        }
    )


def seleccionar_prediccion(
    nowcast: pd.DataFrame,
    configuracion: pd.DataFrame,
    fecha_mercado: pd.Timestamp,
    processed: Path,
) -> pd.DataFrame:
    filas = []

    rmse = cargar_umbral_error(
        processed
    ).set_index("afp")[
        "rmse_referencia"
    ].to_dict()

    for _, config in configuracion.iterrows():
        afp = str(config["afp"])
        modelo_requerido = str(
            config["modelo_operativo_actual"]
        )
        lambda_actual = float(
            config["lambda_operativo_actual"]
        )

        datos_afp = nowcast[
            nowcast["afp"].eq(afp)
        ].copy()

        if datos_afp.empty:
            filas.append(
                {
                    "afp": afp,
                    "estado_prediccion": (
                        "sin_prediccion"
                    ),
                    "modelo_operativo": (
                        modelo_requerido
                    ),
                    "lambda_operativo": (
                        lambda_actual
                    ),
                }
            )
            continue

        fecha_latest = datos_afp[
            "fecha_prediccion"
        ].max()

        latest = datos_afp[
            datos_afp[
                "fecha_prediccion"
            ].eq(fecha_latest)
        ].copy()

        base = latest[
            latest["modelo_fuente"].eq(
                MODELO_BASE
            )
        ]
        hibrido = latest[
            latest["modelo_fuente"].eq(
                MODELO_HIBRIDO
            )
        ]
        prediccion = np.nan
        fuente = ""
        observacion = ""

        if modelo_requerido == MODELO_BASE:
            if not base.empty:
                prediccion = float(
                    base.iloc[-1]["prediccion"]
                )
                fuente = MODELO_BASE
            else:
                observacion = (
                    "no existe predicción M0 para "
                    "la fecha más reciente"
                )

        elif modelo_requerido == MODELO_HIBRIDO:
            if not hibrido.empty:
                prediccion = float(
                    hibrido.iloc[-1][
                        "prediccion"
                    ]
                )
                fuente = MODELO_HIBRIDO
            else:
                observacion = (
                    "no existe predicción híbrida "
                    "para la fecha más reciente"
                )
        else:
            observacion = (
                f"modelo operativo no reconocido: "
                f"{modelo_requerido}"
            )

        dias_atraso = np.nan

        if (
            pd.notna(fecha_mercado)
            and pd.notna(fecha_latest)
        ):
            dias_atraso = int(
                (
                    fecha_mercado.normalize()
                    - fecha_latest.normalize()
                ).days
            )

        rmse_ref = rmse.get(
            afp,
            np.nan,
        )
        intensidad = np.nan
        direccion = ""
        magnitud = ""

        if pd.notna(prediccion):
            direccion = (
                "positiva"
                if prediccion > 0
                else (
                    "negativa"
                    if prediccion < 0
                    else "neutra"
                )
            )

            if (
                pd.notna(rmse_ref)
                and rmse_ref > 0
            ):
                intensidad = abs(
                    prediccion
                ) / rmse_ref

                if intensidad < 0.50:
                    magnitud = (
                        "débil_frente_al_error_oos"
                    )
                elif intensidad < 1.00:
                    magnitud = (
                        "moderada_frente_al_error_oos"
                    )
                else:
                    magnitud = (
                        "alta_frente_al_error_oos"
                    )
            else:
                magnitud = (
                    "sin_rmse_de_referencia"
                )

        prediccion_plausible = bool(
            pd.notna(prediccion)
            and abs(prediccion) <= 0.20
        )

        estado = (
            "correcto"
            if prediccion_plausible
            else "revisar"
        )

        if (
            pd.notna(prediccion)
            and not prediccion_plausible
        ):
            observacion = (
                observacion
                + ("; " if observacion else "")
                + "predicción fuera del rango plausible ±20 % diario"
            )

        if (
            pd.notna(dias_atraso)
            and dias_atraso
            > MAX_DIAS_DESACTUALIZACION
        ):
            estado = "desactualizada"
            observacion = (
                observacion
                + (
                    "; " if observacion else ""
                )
                + (
                    f"la predicción está {dias_atraso} "
                    "días detrás del mercado"
                )
            )

        filas.append(
            {
                "afp": afp,
                "fecha_prediccion": fecha_latest,
                "fecha_mercado_referencia": (
                    fecha_mercado
                ),
                "dias_atraso": dias_atraso,
                "modelo_operativo": (
                    modelo_requerido
                ),
                "modelo_fuente": fuente,
                "lambda_operativo": (
                    lambda_actual
                ),
                "prediccion_retorno": (
                    prediccion
                ),
                "prediccion_retorno_pct": (
                    prediccion * 100.0
                    if pd.notna(prediccion)
                    else np.nan
                ),
                "rmse_oos_referencia": (
                    rmse_ref
                ),
                "ratio_prediccion_rmse": (
                    intensidad
                ),
                "direccion_analitica": (
                    direccion
                ),
                "magnitud_analitica": (
                    magnitud
                ),
                "prediccion_plausible": prediccion_plausible,
                "estado_prediccion": estado,
                "observacion": observacion,
            }
        )

    return pd.DataFrame(filas)


def construir_control(
    configuracion: pd.DataFrame,
    auditoria: pd.DataFrame,
    salida: pd.DataFrame,
    ruta_nowcast: Path | None,
) -> pd.DataFrame:
    controles = []

    controles.append(
        {
            "control": (
                "configuracion_cuatro_afp"
            ),
            "estado": (
                "correcto"
                if set(
                    configuracion["afp"]
                )
                == set(AFPS)
                else "revisar"
            ),
            "detalle": (
                f"afp={configuracion['afp'].nunique()}"
            ),
        }
    )

    controles.append(
        {
            "control": (
                "archivo_nowcast_detectado"
            ),
            "estado": (
                "correcto"
                if ruta_nowcast is not None
                else "revisar"
            ),
            "detalle": (
                str(ruta_nowcast)
                if ruta_nowcast is not None
                else (
                    "defina AFP_NOWCAST_CSV con la "
                    "ruta del archivo de predicciones"
                )
            ),
        }
    )

    controles.append(
        {
            "control": (
                "prediccion_por_cuatro_afp"
            ),
            "estado": (
                "correcto"
                if (
                    not salida.empty
                    and salida[
                        "prediccion_retorno"
                    ].notna().sum()
                    == 4
                )
                else "revisar"
            ),
            "detalle": (
                f"predicciones_validas="
                f"{int(salida['prediccion_retorno'].notna().sum())}"
                if not salida.empty
                else "predicciones_validas=0"
            ),
        }
    )


    controles.append(
        {
            "control": (
                "predicciones_plausibles"
            ),
            "estado": (
                "correcto"
                if (
                    not salida.empty
                    and salida[
                        "prediccion_plausible"
                    ].fillna(False).all()
                )
                else "revisar"
            ),
            "detalle": (
                f"max_abs="
                f"{salida['prediccion_retorno'].abs().max():.6f}"
                if (
                    not salida.empty
                    and salida[
                        "prediccion_retorno"
                    ].notna().any()
                )
                else "sin_predicciones"
            ),
        }
    )

    controles.append(
        {
            "control": (
                "modelo_fuente_explicito"
            ),
            "estado": (
                "correcto"
                if (
                    not salida.empty
                    and not salida[
                        "modelo_fuente"
                    ].eq(
                        "modelo_no_identificado"
                    ).any()
                    and salida[
                        "modelo_fuente"
                    ].ne("").all()
                )
                else "revisar"
            ),
            "detalle": (
                "no se aceptan predicciones con modelo no identificado"
            ),
        }
    )

    controles.append(
        {
            "control": (
                "politica_modelo_respetada"
            ),
            "estado": (
                "correcto"
                if (
                    salida.empty
                    or not (
                        salida[
                            "modelo_operativo"
                        ].eq(MODELO_BASE)
                        & salida[
                            "modelo_fuente"
                        ].eq(MODELO_HIBRIDO)
                    ).any()
                )
                else "revisar"
            ),
            "detalle": (
                "M0 no debe sustituirse por M2 "
                "cuando la composición está vencida"
            ),
        }
    )

    controles.append(
        {
            "control": (
                "candidato_principal_auditado"
            ),
            "estado": (
                "correcto"
                if (
                    ruta_nowcast is None
                    or (
                        not auditoria.empty
                        and str(
                            ruta_nowcast.resolve()
                        )
                        == str(
                            auditoria.iloc[0][
                                "ruta"
                            ]
                        )
                    )
                )
                else "revisar"
            ),
            "detalle": (
                f"candidatos={len(auditoria)}"
            ),
        }
    )

    return pd.DataFrame(controles)


def exportar_json(
    salida: pd.DataFrame,
    control: pd.DataFrame,
    ruta_nowcast: Path | None,
    ruta_salida: Path,
) -> None:
    registros = []

    for registro in salida.to_dict(
        orient="records"
    ):
        limpio = {}

        for clave, valor in registro.items():
            if isinstance(
                valor,
                (pd.Timestamp, np.datetime64),
            ):
                limpio[clave] = (
                    pd.Timestamp(valor).strftime(
                        "%Y-%m-%d"
                    )
                    if pd.notna(valor)
                    else None
                )
            elif pd.isna(valor):
                limpio[clave] = None
            elif isinstance(
                valor,
                np.generic,
            ):
                limpio[clave] = valor.item()
            else:
                limpio[clave] = valor

        registros.append(limpio)

    contenido = {
        "version": (
            "modelo45_motor_operativo_v2"
        ),
        "archivo_predicciones": (
            str(ruta_nowcast.resolve())
            if ruta_nowcast is not None
            else None
        ),
        "nota": (
            "Las etiquetas de dirección y magnitud "
            "son diagnósticos analíticos; no constituyen "
            "una recomendación de operación."
        ),
        "predicciones": registros,
        "control": control.to_dict(
            orient="records"
        ),
    }

    ruta_salida.write_text(
        json.dumps(
            contenido,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def main() -> None:
    raiz = Path(__file__).resolve().parents[1]
    processed = raiz / "data" / "processed"

    ruta_config = (
        processed
        / "ca0001_modelo44_configuracion_produccion.csv"
    )

    if not ruta_config.exists():
        raise FileNotFoundError(
            "Primero ejecute el módulo 44. "
            f"No existe: {ruta_config}"
        )

    configuracion = leer_csv_flexible(
        ruta_config
    )

    configuracion[
        "composicion_vigente"
    ] = convertir_booleano(
        configuracion[
            "composicion_vigente"
        ]
    )

    fecha_mercado = leer_fecha_maxima_mercado(
        processed
    )

    ruta_nowcast, auditoria = descubrir_nowcast(
        processed,
        fecha_mercado,
        configuracion,
    )

    if ruta_nowcast is None:
        nowcast = pd.DataFrame(
            columns=[
                "fecha_prediccion",
                "afp",
                "prediccion",
                "modelo_fuente",
            ]
        )
    else:
        nowcast = preparar_nowcast(
            ruta_nowcast
        )

    salida = seleccionar_prediccion(
        nowcast,
        configuracion,
        fecha_mercado,
        processed,
    )

    control = construir_control(
        configuracion,
        auditoria,
        salida,
        ruta_nowcast,
    )

    rutas = {
        "operativo_csv": (
            processed
            / "ca0001_modelo45_nowcast_operativo.csv"
        ),
        "operativo_json": (
            processed
            / "ca0001_modelo45_nowcast_operativo.json"
        ),
        "auditoria": (
            processed
            / "ca0001_modelo45_candidatos_prediccion.csv"
        ),
        "control": (
            processed
            / "ca0001_modelo45_control.csv"
        ),
    }

    salida.to_csv(
        rutas["operativo_csv"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    auditoria.to_csv(
        rutas["auditoria"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    control.to_csv(
        rutas["control"],
        index=False,
        encoding="utf-8-sig",
    )
    exportar_json(
        salida,
        control,
        ruta_nowcast,
        rutas["operativo_json"],
    )

    print(
        "\nMOTOR OPERATIVO DE NOWCAST V2 TERMINADO"
    )
    print("=" * 120)

    print("\nARCHIVO DE PREDICCIONES SELECCIONADO")
    print("-" * 120)

    if ruta_nowcast is None:
        print(
            "No se detectó un archivo actual de "
            "predicciones."
        )
        print(
            "\nDefina manualmente la ruta en "
            "PowerShell y vuelva a ejecutar:"
        )
        print(
            '$env:AFP_NOWCAST_CSV="C:\\ruta\\archivo.csv"'
        )
    else:
        print(ruta_nowcast.resolve())

    print("\nTOP DE CANDIDATOS")
    print("-" * 120)

    if auditoria.empty:
        print(
            "No se encontraron candidatos."
        )
    else:
        print(
            auditoria.head(15).to_string(
                index=False
            )
        )

    print("\nNOWCAST OPERATIVO")
    print("-" * 120)
    print(
        salida.to_string(
            index=False
        )
    )

    print("\nCONTROL")
    print("-" * 120)
    print(
        control.to_string(
            index=False
        )
    )

    print("\nArchivos creados:")
    for ruta in rutas.values():
        print(f" - {ruta.resolve()}")

    print(
        "\nCriterio operativo:\n"
        "- El módulo 44 determina el modelo permitido por AFP.\n"
        "- Con composición vencida solo se acepta M0_base_mercado.\n"
        "- El archivo de predicciones se detecta con validación estricta de columna, escala, fecha objetivo y modelo; también puede "
        "fijarse mediante AFP_NOWCAST_CSV.\n"
        "- La magnitud se expresa como razón entre la predicción y el RMSE "
        "OOS del modelo base.\n"
        "- Las salidas son diagnósticos analíticos y no constituyen una "
        "recomendación de compra, venta, cambio de fondo u operación."
    )


if __name__ == "__main__":
    main()
