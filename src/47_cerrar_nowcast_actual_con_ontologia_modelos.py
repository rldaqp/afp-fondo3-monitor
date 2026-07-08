from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


AFPS = ["Habitat", "Integra", "Prima", "Profuturo"]

FAMILIA_BASE = "M0_base_mercado"
FAMILIA_HIBRIDA = "M2_hibrido"

MAPEO_ESTIMADORES = {
    "ACWILINEAL": FAMILIA_BASE,
    "RIDGE": FAMILIA_BASE,
    "ELASTICNET": FAMILIA_BASE,
    "HUBERROBUSTO": FAMILIA_BASE,
    "M0BASEMERCADO": FAMILIA_BASE,
    "M2HIBRIDO": FAMILIA_HIBRIDA,
    "HIBRIDO": FAMILIA_HIBRIDA,
    "HYBRID": FAMILIA_HIBRIDA,
}

MAX_RETORNO_DIARIO_PLAUSIBLE = 0.20


def limpiar_nombre(valor: object) -> str:
    texto = str(valor).strip().upper()
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(
        caracter
        for caracter in texto
        if not unicodedata.combining(caracter)
    )
    return re.sub(r"[^A-Z0-9]+", "", texto)


def leer_csv_flexible(ruta: Path) -> pd.DataFrame:
    intentos = [
        {"sep": None, "engine": "python", "encoding": "utf-8-sig"},
        {"sep": None, "engine": "python", "encoding": "latin-1"},
        {"sep": ",", "encoding": "utf-8-sig"},
        {"sep": ";", "encoding": "utf-8-sig"},
        {"sep": ";", "encoding": "latin-1"},
    ]

    ultimo_error = None

    for argumentos in intentos:
        try:
            return pd.read_csv(ruta, **argumentos)
        except Exception as error:
            ultimo_error = error

    raise RuntimeError(
        f"No se pudo leer {ruta}: {ultimo_error}"
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

    return None


def normalizar_afp(valor: object) -> str | None:
    limpio = limpiar_nombre(valor)

    for afp in AFPS:
        if limpiar_nombre(afp) in limpio:
            return afp

    return None


def clasificar_estimador(valor: object) -> str:
    limpio = limpiar_nombre(valor)

    if limpio in MAPEO_ESTIMADORES:
        return MAPEO_ESTIMADORES[limpio]

    for patron, familia in MAPEO_ESTIMADORES.items():
        if patron and patron in limpio:
            return familia

    return "familia_no_identificada"


def fecha_maxima_mercado(processed: Path) -> pd.Timestamp:
    ruta = processed / "mercados_factores_modelo.csv"

    if not ruta.exists():
        return pd.NaT

    df = leer_csv_flexible(ruta)
    fecha_col = detectar_columna(
        df.columns,
        {
            "fecha",
            "date",
            "trading_date",
        },
    )

    if fecha_col is None:
        fecha_col = str(df.columns[0])

    return pd.to_datetime(
        df[fecha_col],
        errors="coerce",
    ).max()


def normalizar_escala(
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

    if any(
        token in limpio
        for token in [
            "PCT",
            "PORCENTAJE",
            "PERCENT",
        ]
    ):
        return valores / 100.0, "porcentaje_a_decimal"

    if (
        p99 > 0.20
        and p99 <= 20.0
        and mediana > 0.01
    ):
        return (
            valores / 100.0,
            "escala_porcentual_inferida",
        )

    return valores, "decimal"


def cargar_nowcast_actual(
    processed: Path,
) -> tuple[pd.DataFrame, str]:
    ruta = (
        processed
        / "nowcast_operativo_fondo3.csv"
    )

    if not ruta.exists():
        raise FileNotFoundError(
            f"No existe el archivo operativo: {ruta}"
        )

    df = leer_csv_flexible(ruta)

    fecha_col = detectar_columna(
        df.columns,
        {
            "fecha_estimada",
            "fecha_prediccion",
            "fecha_objetivo",
            "fecha_nowcast",
            "fecha",
        },
    )
    afp_col = detectar_columna(
        df.columns,
        {
            "afp",
            "administradora",
            "nombre_afp",
        },
    )
    modelo_col = detectar_columna(
        df.columns,
        {
            "modelo",
            "model",
            "modelo_operativo",
            "estimador",
        },
    )
    pred_col = detectar_columna(
        df.columns,
        {
            "retorno_estimado_dia",
            "retorno_estimado",
            "retorno_predicho",
            "prediccion",
            "y_pred",
            "forecast",
        },
    )

    faltantes = [
        nombre
        for nombre, valor in {
            "fecha": fecha_col,
            "afp": afp_col,
            "modelo": modelo_col,
            "prediccion": pred_col,
        }.items()
        if valor is None
    ]

    if faltantes:
        raise ValueError(
            "Faltan columnas necesarias en "
            f"{ruta.name}: {faltantes}. "
            f"Columnas disponibles: {list(df.columns)}"
        )

    prediccion, escala = normalizar_escala(
        df[pred_col],
        pred_col,
    )

    salida = pd.DataFrame(
        {
            "fecha_prediccion": pd.to_datetime(
                df[fecha_col],
                errors="coerce",
            ),
            "afp": df[afp_col].map(
                normalizar_afp
            ),
            "estimador_raw": (
                df[modelo_col]
                .fillna("")
                .astype(str)
                .str.strip()
            ),
            "familia_modelo": (
                df[modelo_col]
                .map(clasificar_estimador)
            ),
            "prediccion_original": pd.to_numeric(
                df[pred_col],
                errors="coerce",
            ),
            "prediccion_retorno": prediccion,
            "escala_prediccion": escala,
        }
    ).dropna(
        subset=[
            "fecha_prediccion",
            "afp",
            "prediccion_retorno",
        ]
    )

    fecha_latest = salida[
        "fecha_prediccion"
    ].max()

    latest = salida[
        salida[
            "fecha_prediccion"
        ].eq(fecha_latest)
    ].copy()

    latest = (
        latest.sort_values(
            [
                "afp",
                "estimador_raw",
            ]
        )
        .drop_duplicates(
            subset=["afp"],
            keep="last",
        )
        .reset_index(drop=True)
    )

    return latest, str(ruta.resolve())


def cargar_configuracion(
    processed: Path,
) -> pd.DataFrame:
    ruta = (
        processed
        / "ca0001_modelo44_configuracion_produccion.csv"
    )

    if not ruta.exists():
        raise FileNotFoundError(
            "No existe la configuración del módulo 44."
        )

    df = leer_csv_flexible(ruta)

    df["afp"] = df["afp"].map(
        normalizar_afp
    )

    return df


def cargar_rmse_base(
    processed: Path,
) -> pd.DataFrame:
    ruta = (
        processed
        / "ca0001_modelo41_resultados_oos.csv"
    )

    if not ruta.exists():
        raise FileNotFoundError(
            "No existe el resultado OOS del módulo 41."
        )

    df = leer_csv_flexible(ruta)

    filtro = df[
        df["escenario"].eq(
            "ampliado_15pct"
        )
        & df[
            "variante_confianza"
        ].eq("alta")
        & df["modelo"].eq(
            FAMILIA_BASE
        )
    ][
        ["afp", "rmse"]
    ].copy()

    filtro["afp"] = filtro["afp"].map(
        normalizar_afp
    )
    filtro["rmse"] = pd.to_numeric(
        filtro["rmse"],
        errors="coerce",
    )

    return filtro.rename(
        columns={
            "rmse": "rmse_oos_base",
        }
    )


def construir_nowcast_validado(
    nowcast: pd.DataFrame,
    configuracion: pd.DataFrame,
    rmse: pd.DataFrame,
    fecha_mercado: pd.Timestamp,
) -> pd.DataFrame:
    salida = (
        nowcast.merge(
            configuracion[
                [
                    "afp",
                    "modelo_operativo_actual",
                    "lambda_operativo_actual",
                    "composicion_vigente",
                    "periodo_ultima_composicion",
                    "fecha_fin_validez",
                ]
            ],
            on="afp",
            how="left",
            validate="one_to_one",
        )
        .merge(
            rmse,
            on="afp",
            how="left",
            validate="one_to_one",
        )
    )

    salida["fecha_mercado_referencia"] = (
        fecha_mercado
    )
    salida["dias_atraso"] = (
        salida[
            "fecha_mercado_referencia"
        ]
        - salida["fecha_prediccion"]
    ).dt.days

    salida[
        "familia_compatible_con_politica"
    ] = (
        salida["familia_modelo"]
        == salida["modelo_operativo_actual"]
    )

    salida["prediccion_plausible"] = (
        salida["prediccion_retorno"]
        .abs()
        .le(
            MAX_RETORNO_DIARIO_PLAUSIBLE
        )
    )

    salida["prediccion_retorno_pct"] = (
        salida["prediccion_retorno"]
        * 100.0
    )

    salida["ratio_prediccion_rmse"] = (
        salida["prediccion_retorno"]
        .abs()
        / salida["rmse_oos_base"]
    )

    salida["direccion_analitica"] = np.select(
        [
            salida["prediccion_retorno"] > 0,
            salida["prediccion_retorno"] < 0,
        ],
        [
            "positiva",
            "negativa",
        ],
        default="neutra",
    )

    salida["magnitud_analitica"] = pd.cut(
        salida["ratio_prediccion_rmse"],
        bins=[
            -np.inf,
            0.50,
            1.00,
            np.inf,
        ],
        labels=[
            "debil_frente_al_error_oos",
            "moderada_frente_al_error_oos",
            "alta_frente_al_error_oos",
        ],
        right=False,
    ).astype(str)

    salida["estado_validacion"] = np.where(
        salida[
            "familia_compatible_con_politica"
        ]
        & salida["prediccion_plausible"]
        & salida["dias_atraso"].eq(0)
        & salida["rmse_oos_base"].notna(),
        "validado",
        "revisar",
    )

    salida["observacion"] = ""

    salida.loc[
        ~salida[
            "familia_compatible_con_politica"
        ],
        "observacion",
    ] += (
        "familia del estimador incompatible "
        "con la política operativa; "
    )

    salida.loc[
        ~salida["prediccion_plausible"],
        "observacion",
    ] += "predicción fuera del rango plausible; "

    salida.loc[
        salida["dias_atraso"].ne(0),
        "observacion",
    ] += "fecha objetivo distinta de la fecha de mercado; "

    salida.loc[
        salida["rmse_oos_base"].isna(),
        "observacion",
    ] += "sin RMSE OOS de referencia; "

    salida["observacion"] = (
        salida["observacion"]
        .str.rstrip("; ")
    )

    salida["afp"] = pd.Categorical(
        salida["afp"],
        categories=AFPS,
        ordered=True,
    )

    columnas = [
        "afp",
        "fecha_prediccion",
        "fecha_mercado_referencia",
        "dias_atraso",
        "estimador_raw",
        "familia_modelo",
        "modelo_operativo_actual",
        "lambda_operativo_actual",
        "composicion_vigente",
        "periodo_ultima_composicion",
        "fecha_fin_validez",
        "prediccion_retorno",
        "prediccion_retorno_pct",
        "rmse_oos_base",
        "ratio_prediccion_rmse",
        "direccion_analitica",
        "magnitud_analitica",
        "familia_compatible_con_politica",
        "prediccion_plausible",
        "estado_validacion",
        "observacion",
    ]

    return (
        salida[columnas]
        .sort_values("afp")
        .reset_index(drop=True)
    )


def construir_resumen_sistema(
    nowcast: pd.DataFrame,
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "fecha_prediccion": (
                    nowcast[
                        "fecha_prediccion"
                    ].max()
                ),
                "afp_validas": int(
                    nowcast[
                        "estado_validacion"
                    ].eq("validado").sum()
                ),
                "retorno_medio_pct": float(
                    nowcast[
                        "prediccion_retorno_pct"
                    ].mean()
                ),
                "retorno_mediano_pct": float(
                    nowcast[
                        "prediccion_retorno_pct"
                    ].median()
                ),
                "retorno_minimo_pct": float(
                    nowcast[
                        "prediccion_retorno_pct"
                    ].min()
                ),
                "retorno_maximo_pct": float(
                    nowcast[
                        "prediccion_retorno_pct"
                    ].max()
                ),
                "dispersion_entre_afp_pp": float(
                    nowcast[
                        "prediccion_retorno_pct"
                    ].max()
                    - nowcast[
                        "prediccion_retorno_pct"
                    ].min()
                ),
                "ratio_rmse_mediano": float(
                    nowcast[
                        "ratio_prediccion_rmse"
                    ].median()
                ),
                "direccion_comun": (
                    nowcast[
                        "direccion_analitica"
                    ].mode().iloc[0]
                    if not nowcast.empty
                    else ""
                ),
                "lectura_sistema": (
                    "sesgo positivo débil y bastante homogéneo"
                    if (
                        nowcast[
                            "prediccion_retorno"
                        ].gt(0).all()
                        and nowcast[
                            "ratio_prediccion_rmse"
                        ].median()
                        < 0.50
                    )
                    else (
                        "señal no uniforme o de mayor intensidad"
                    )
                ),
            }
        ]
    )


def construir_mapeo_estimadores() -> pd.DataFrame:
    filas = []

    for estimador, familia in [
        ("ACWI_lineal", FAMILIA_BASE),
        ("Ridge", FAMILIA_BASE),
        ("ElasticNet", FAMILIA_BASE),
        ("Huber_robusto", FAMILIA_BASE),
        ("M2_hibrido", FAMILIA_HIBRIDA),
    ]:
        filas.append(
            {
                "estimador_o_etiqueta": estimador,
                "familia_modelo": familia,
                "criterio": (
                    "estimador del modelo base de mercado"
                    if familia == FAMILIA_BASE
                    else (
                        "modelo que incorpora composición CA-0001"
                    )
                ),
            }
        )

    return pd.DataFrame(filas)


def construir_control(
    nowcast: pd.DataFrame,
    fecha_mercado: pd.Timestamp,
) -> pd.DataFrame:
    controles = [
        {
            "control": "cuatro_afp_presentes",
            "estado": (
                "correcto"
                if set(
                    nowcast["afp"].astype(str)
                )
                == set(AFPS)
                else "revisar"
            ),
            "detalle": (
                ", ".join(
                    nowcast["afp"]
                    .astype(str)
                    .tolist()
                )
            ),
        },
        {
            "control": "fecha_objetivo_actual",
            "estado": (
                "correcto"
                if (
                    nowcast[
                        "fecha_prediccion"
                    ].eq(
                        fecha_mercado
                    ).all()
                )
                else "revisar"
            ),
            "detalle": (
                f"fecha_mercado={fecha_mercado.date()}"
                if pd.notna(fecha_mercado)
                else "fecha_mercado=NaT"
            ),
        },
        {
            "control": "familia_modelo_compatible",
            "estado": (
                "correcto"
                if nowcast[
                    "familia_compatible_con_politica"
                ].all()
                else "revisar"
            ),
            "detalle": (
                "los estimadores actuales pertenecen a M0_base_mercado"
            ),
        },
        {
            "control": "predicciones_plausibles",
            "estado": (
                "correcto"
                if nowcast[
                    "prediccion_plausible"
                ].all()
                else "revisar"
            ),
            "detalle": (
                f"max_abs={nowcast['prediccion_retorno'].abs().max():.6f}"
            ),
        },
        {
            "control": "cuatro_predicciones_validadas",
            "estado": (
                "correcto"
                if nowcast[
                    "estado_validacion"
                ].eq("validado").sum()
                == 4
                else "revisar"
            ),
            "detalle": (
                f"validadas={int(nowcast['estado_validacion'].eq('validado').sum())}"
            ),
        },
        {
            "control": "composicion_vencida_no_utilizada",
            "estado": (
                "correcto"
                if (
                    nowcast[
                        "composicion_vigente"
                    ].eq(False).all()
                    and nowcast[
                        "familia_modelo"
                    ].eq(
                        FAMILIA_BASE
                    ).all()
                )
                else "revisar"
            ),
            "detalle": (
                "se usa únicamente el modelo base de mercado"
            ),
        },
    ]

    return pd.DataFrame(controles)


def exportar_json(
    nowcast: pd.DataFrame,
    resumen: pd.DataFrame,
    control: pd.DataFrame,
    ruta_fuente: str,
    ruta_salida: Path,
) -> None:
    def limpiar_registro(
        registro: dict[str, object],
    ) -> dict[str, object]:
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
            elif isinstance(
                valor,
                pd.Categorical,
            ):
                limpio[clave] = str(valor)
            elif pd.isna(valor):
                limpio[clave] = None
            elif isinstance(
                valor,
                np.generic,
            ):
                limpio[clave] = valor.item()
            else:
                limpio[clave] = valor

        return limpio

    contenido = {
        "version": "modelo47_nowcast_actual_validado",
        "archivo_fuente": ruta_fuente,
        "regla_semantica": (
            "ACWI_lineal, Ridge, ElasticNet y Huber_robusto "
            "son estimadores pertenecientes a M0_base_mercado; "
            "no son modelos híbridos de composición."
        ),
        "nowcast": [
            limpiar_registro(registro)
            for registro in nowcast.to_dict(
                orient="records"
            )
        ],
        "resumen_sistema": [
            limpiar_registro(registro)
            for registro in resumen.to_dict(
                orient="records"
            )
        ],
        "control": control.to_dict(
            orient="records"
        ),
        "nota": (
            "La dirección y magnitud son diagnósticos estadísticos. "
            "No constituyen recomendación de cambio de fondo, compra, "
            "venta u operación."
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

    fecha_mercado = fecha_maxima_mercado(
        processed
    )
    nowcast_raw, ruta_fuente = (
        cargar_nowcast_actual(
            processed
        )
    )
    configuracion = cargar_configuracion(
        processed
    )
    rmse = cargar_rmse_base(
        processed
    )

    nowcast = construir_nowcast_validado(
        nowcast_raw,
        configuracion,
        rmse,
        fecha_mercado,
    )
    resumen = construir_resumen_sistema(
        nowcast
    )
    mapeo = construir_mapeo_estimadores()
    control = construir_control(
        nowcast,
        fecha_mercado,
    )

    rutas = {
        "nowcast_csv": (
            processed
            / "ca0001_modelo47_nowcast_actual_validado.csv"
        ),
        "nowcast_json": (
            processed
            / "ca0001_modelo47_nowcast_actual_validado.json"
        ),
        "resumen": (
            processed
            / "ca0001_modelo47_resumen_sistema.csv"
        ),
        "mapeo": (
            processed
            / "ca0001_modelo47_mapeo_estimadores.csv"
        ),
        "control": (
            processed
            / "ca0001_modelo47_control.csv"
        ),
    }

    nowcast.to_csv(
        rutas["nowcast_csv"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    resumen.to_csv(
        rutas["resumen"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    mapeo.to_csv(
        rutas["mapeo"],
        index=False,
        encoding="utf-8-sig",
    )
    control.to_csv(
        rutas["control"],
        index=False,
        encoding="utf-8-sig",
    )
    exportar_json(
        nowcast,
        resumen,
        control,
        ruta_fuente,
        rutas["nowcast_json"],
    )

    print(
        "\nNOWCAST ACTUAL VALIDADO Y CERRADO"
    )
    print("=" * 120)

    print("\nMAPEO SEMÁNTICO DE ESTIMADORES")
    print("-" * 120)
    print(
        mapeo.to_string(index=False)
    )

    print("\nNOWCAST VALIDADO POR AFP")
    print("-" * 120)
    print(
        nowcast[
            [
                "afp",
                "fecha_prediccion",
                "estimador_raw",
                "familia_modelo",
                "modelo_operativo_actual",
                "prediccion_retorno_pct",
                "rmse_oos_base",
                "ratio_prediccion_rmse",
                "direccion_analitica",
                "magnitud_analitica",
                "estado_validacion",
            ]
        ].to_string(index=False)
    )

    print("\nRESUMEN DEL SISTEMA")
    print("-" * 120)
    print(
        resumen.to_string(index=False)
    )

    print("\nCONTROL")
    print("-" * 120)
    print(
        control.to_string(index=False)
    )

    print("\nArchivos creados:")
    for ruta in rutas.values():
        print(f" - {ruta.resolve()}")

    print(
        "\nCriterio final:\n"
        "- Huber_robusto, ElasticNet, Ridge y ACWI_lineal son "
        "estimadores internos del modelo base de mercado.\n"
        "- La etiqueta del estimador no reemplaza la familia M0/M2.\n"
        "- Como la composición está vencida, solo M0_base_mercado es "
        "operativamente admisible.\n"
        "- Un retorno estimado inferior a la mitad del RMSE OOS se "
        "clasifica como señal débil frente al error del modelo.\n"
        "- El resultado es un diagnóstico estadístico, no una "
        "recomendación de operación o cambio de fondo."
    )


if __name__ == "__main__":
    main()
