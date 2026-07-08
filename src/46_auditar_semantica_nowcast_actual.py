from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


AFPS = ["Habitat", "Integra", "Prima", "Profuturo"]

ARCHIVOS_PRIORITARIOS = [
    "nowcast_operativo_fondo3.csv",
    "nowcast_historico_estimaciones.csv",
    "nowcast_validacion_detalle.csv",
    "modelo_base_nowcast_predicciones.csv",
]


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


def clasificar_modelo(valor: object) -> str:
    limpio = limpiar_nombre(valor)

    if not limpio:
        return "vacio"

    if any(
        patron in limpio
        for patron in [
            "M0BASEMERCADO",
            "M0",
            "BASEMERCADO",
            "MODELOBASE",
        ]
    ):
        return "M0_base_mercado"

    if any(
        patron in limpio
        for patron in [
            "M2HIBRIDO",
            "M2",
            "HIBRIDO",
            "HYBRID",
        ]
    ):
        return "M2_hibrido"

    return "no_identificado"


def fecha_mercado(processed: Path) -> pd.Timestamp:
    ruta = processed / "mercados_factores_modelo.csv"

    if not ruta.exists():
        return pd.NaT

    df = leer_csv_flexible(ruta)
    columna = detectar_columna(
        df.columns,
        {
            "fecha",
            "date",
            "trading_date",
        },
    )

    if columna is None:
        columna = str(df.columns[0])

    return pd.to_datetime(
        df[columna],
        errors="coerce",
    ).max()


def auditar_archivo(
    ruta: Path,
    fecha_referencia: pd.Timestamp,
) -> tuple[dict[str, object], pd.DataFrame]:
    df = leer_csv_flexible(ruta)

    fecha_objetivo_col = detectar_columna(
        df.columns,
        {
            "fecha_estimada",
            "fecha_prediccion",
            "fecha_objetivo",
            "fecha_nowcast",
            "fecha_proyectada",
            "fecha",
        },
    )
    fecha_ancla_col = detectar_columna(
        df.columns,
        {
            "fecha_ultima_oficial",
            "fecha_oficial",
            "fecha_base",
            "fecha_referencia",
        },
    )
    horizonte_col = detectar_columna(
        df.columns,
        {
            "dia_nowcast",
            "dias_nowcast",
            "horizonte",
            "horizonte_dias",
            "paso",
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
            "tipo_modelo",
        },
    )
    prediccion_col = detectar_columna(
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

    if fecha_objetivo_col is not None:
        fecha_objetivo = pd.to_datetime(
            df[fecha_objetivo_col],
            errors="coerce",
        )
        metodo_fecha = "fecha_objetivo_explicita"
    elif (
        fecha_ancla_col is not None
        and horizonte_col is not None
    ):
        fecha_ancla = pd.to_datetime(
            df[fecha_ancla_col],
            errors="coerce",
        )
        horizonte = pd.to_numeric(
            df[horizonte_col],
            errors="coerce",
        )
        fecha_objetivo = (
            fecha_ancla
            + pd.to_timedelta(
                horizonte,
                unit="D",
            )
        )
        metodo_fecha = "fecha_ancla_mas_horizonte"
    elif fecha_ancla_col is not None:
        fecha_objetivo = pd.to_datetime(
            df[fecha_ancla_col],
            errors="coerce",
        )
        metodo_fecha = "solo_fecha_ancla"
    else:
        fecha_objetivo = pd.Series(
            pd.NaT,
            index=df.index,
            dtype="datetime64[ns]",
        )
        metodo_fecha = "sin_fecha"

    afp = (
        df[afp_col].map(normalizar_afp)
        if afp_col is not None
        else pd.Series(
            None,
            index=df.index,
            dtype=object,
        )
    )

    modelo_raw = (
        df[modelo_col].astype(str)
        if modelo_col is not None
        else pd.Series(
            "",
            index=df.index,
            dtype=object,
        )
    )
    modelo_clasificado = modelo_raw.map(
        clasificar_modelo
    )

    prediccion = (
        pd.to_numeric(
            df[prediccion_col],
            errors="coerce",
        )
        if prediccion_col is not None
        else pd.Series(
            np.nan,
            index=df.index,
            dtype=float,
        )
    )

    detalle = pd.DataFrame(
        {
            "archivo": ruta.name,
            "fila_origen": np.arange(
                1,
                len(df) + 1,
            ),
            "fecha_objetivo": fecha_objetivo,
            "afp": afp,
            "modelo_raw": modelo_raw,
            "modelo_clasificado": modelo_clasificado,
            "prediccion_raw": prediccion,
        }
    )

    fecha_maxima = detalle[
        "fecha_objetivo"
    ].max()

    if pd.notna(fecha_maxima):
        latest = detalle[
            detalle["fecha_objetivo"].eq(
                fecha_maxima
            )
        ].copy()
    else:
        latest = detalle.copy()

    etiquetas_modelo = (
        modelo_raw.replace(
            {"": np.nan, "nan": np.nan}
        )
        .dropna()
        .value_counts()
        .to_dict()
    )

    dias_vs_mercado = np.nan

    if (
        pd.notna(fecha_referencia)
        and pd.notna(fecha_maxima)
    ):
        dias_vs_mercado = int(
            (
                fecha_referencia.normalize()
                - fecha_maxima.normalize()
            ).days
        )

    if (
        len(df) > 100
        or (
            pd.notna(dias_vs_mercado)
            and dias_vs_mercado > 0
        )
    ):
        naturaleza = "historico_o_backtest"
    elif (
        pd.notna(dias_vs_mercado)
        and dias_vs_mercado == 0
        and len(df) <= 50
    ):
        naturaleza = "nowcast_actual_candidato"
    else:
        naturaleza = "indeterminado"

    resumen = {
        "archivo": ruta.name,
        "ruta": str(ruta.resolve()),
        "filas": int(len(df)),
        "columnas": " | ".join(
            map(str, df.columns)
        ),
        "columna_fecha_objetivo": fecha_objetivo_col,
        "columna_fecha_ancla": fecha_ancla_col,
        "columna_horizonte": horizonte_col,
        "metodo_fecha": metodo_fecha,
        "columna_afp": afp_col,
        "columna_modelo": modelo_col,
        "columna_prediccion": prediccion_col,
        "fecha_minima_objetivo": detalle[
            "fecha_objetivo"
        ].min(),
        "fecha_maxima_objetivo": fecha_maxima,
        "fecha_mercado_referencia": fecha_referencia,
        "dias_vs_mercado": dias_vs_mercado,
        "afp_latest": int(
            latest["afp"].nunique()
        ),
        "predicciones_latest": int(
            latest["prediccion_raw"]
            .notna()
            .sum()
        ),
        "modelos_m0_latest": int(
            latest[
                "modelo_clasificado"
            ].eq(
                "M0_base_mercado"
            ).sum()
        ),
        "modelos_m2_latest": int(
            latest[
                "modelo_clasificado"
            ].eq(
                "M2_hibrido"
            ).sum()
        ),
        "modelos_no_identificados_latest": int(
            latest[
                "modelo_clasificado"
            ].eq(
                "no_identificado"
            ).sum()
        ),
        "etiquetas_modelo_raw": json.dumps(
            etiquetas_modelo,
            ensure_ascii=False,
        ),
        "naturaleza_archivo": naturaleza,
        "apto_operativo_actual": bool(
            naturaleza
            == "nowcast_actual_candidato"
            and latest["afp"].nunique() == 4
            and latest[
                "modelo_clasificado"
            ].eq(
                "M0_base_mercado"
            ).sum()
            >= 4
            and latest[
                "prediccion_raw"
            ].notna().sum()
            >= 4
        ),
    }

    return resumen, latest


def main() -> None:
    raiz = Path(__file__).resolve().parents[1]
    processed = raiz / "data" / "processed"

    fecha_referencia = fecha_mercado(
        processed
    )

    resumenes = []
    detalles = []

    for nombre in ARCHIVOS_PRIORITARIOS:
        ruta = processed / nombre

        if not ruta.exists():
            resumenes.append(
                {
                    "archivo": nombre,
                    "ruta": str(ruta.resolve()),
                    "naturaleza_archivo": "no_existe",
                    "apto_operativo_actual": False,
                }
            )
            continue

        resumen, detalle = auditar_archivo(
            ruta,
            fecha_referencia,
        )
        resumenes.append(resumen)
        detalles.append(detalle)

    resumen_df = pd.DataFrame(
        resumenes
    )

    detalle_df = (
        pd.concat(
            detalles,
            ignore_index=True,
        )
        if detalles
        else pd.DataFrame()
    )

    rutas = {
        "resumen": (
            processed
            / "ca0001_modelo46_auditoria_semantica_archivos.csv"
        ),
        "detalle": (
            processed
            / "ca0001_modelo46_filas_ultima_fecha.csv"
        ),
    }

    resumen_df.to_csv(
        rutas["resumen"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    detalle_df.to_csv(
        rutas["detalle"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )

    print(
        "\nAUDITORÍA SEMÁNTICA DEL NOWCAST TERMINADA"
    )
    print("=" * 120)

    print("\nRESUMEN DE ARCHIVOS")
    print("-" * 120)

    columnas_resumen = [
        "archivo",
        "filas",
        "metodo_fecha",
        "fecha_maxima_objetivo",
        "fecha_mercado_referencia",
        "dias_vs_mercado",
        "afp_latest",
        "predicciones_latest",
        "modelos_m0_latest",
        "modelos_m2_latest",
        "modelos_no_identificados_latest",
        "etiquetas_modelo_raw",
        "naturaleza_archivo",
        "apto_operativo_actual",
    ]

    existentes = [
        columna
        for columna in columnas_resumen
        if columna in resumen_df.columns
    ]

    print(
        resumen_df[
            existentes
        ].to_string(index=False)
    )

    print("\nFILAS DE LA ÚLTIMA FECHA")
    print("-" * 120)

    if detalle_df.empty:
        print("No hay filas para mostrar.")
    else:
        print(
            detalle_df[
                [
                    "archivo",
                    "fila_origen",
                    "fecha_objetivo",
                    "afp",
                    "modelo_raw",
                    "modelo_clasificado",
                    "prediccion_raw",
                ]
            ]
            .sort_values(
                [
                    "archivo",
                    "fecha_objetivo",
                    "afp",
                ]
            )
            .to_string(index=False)
        )

    print("\nArchivos creados:")
    for ruta in rutas.values():
        print(f" - {ruta.resolve()}")

    print(
        "\nCriterio:\n"
        "- modelo_base_nowcast_predicciones.csv se considera histórico "
        "si termina antes de la fecha de mercado o contiene muchas filas.\n"
        "- Un nowcast actual debe tener fecha objetivo igual a la fecha "
        "de mercado, cuatro AFP, retornos numéricos y un modelo M0 "
        "identificable, porque la composición está vencida.\n"
        "- No se infiere que una etiqueta desconocida sea M0; primero "
        "debe auditarse su significado."
    )


if __name__ == "__main__":
    main()
