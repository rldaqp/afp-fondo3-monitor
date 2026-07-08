from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


AFPS = ["Habitat", "Integra", "Prima", "Profuturo"]

MIN_MUESTRA_ORIENTATIVA = 20
MIN_MUESTRA_ESTABLE = 60


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

    ultimo_error: Exception | None = None

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
        limpio = limpiar_nombre(columna)

        if limpio in alias_limpios:
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


def normalizar_escala(
    serie: pd.Series,
    nombre_columna: str,
) -> tuple[pd.Series, str]:
    valores = pd.to_numeric(
        serie,
        errors="coerce",
    )
    validos = valores.dropna()
    limpio = limpiar_nombre(nombre_columna)

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


def cargar_predicciones(
    processed: Path,
) -> pd.DataFrame:
    ruta = (
        processed
        / "nowcast_historico_estimaciones.csv"
    )

    if not ruta.exists():
        raise FileNotFoundError(
            f"No existe el histórico de nowcasts: {ruta}"
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
    modelo_col = detectar_columna(
        df.columns,
        {
            "modelo",
            "model",
            "estimador",
        },
    )

    faltantes = [
        nombre
        for nombre, columna in {
            "fecha": fecha_col,
            "afp": afp_col,
            "prediccion": pred_col,
        }.items()
        if columna is None
    ]

    if faltantes:
        raise ValueError(
            "No se identificaron las columnas "
            f"{faltantes} en {ruta.name}. "
            f"Columnas: {list(df.columns)}"
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
            "estimador": (
                df[modelo_col]
                .fillna("")
                .astype(str)
                .str.strip()
                if modelo_col is not None
                else ""
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

    salida = (
        salida.sort_values(
            [
                "fecha_prediccion",
                "afp",
            ]
        )
        .drop_duplicates(
            subset=[
                "fecha_prediccion",
                "afp",
            ],
            keep="last",
        )
        .reset_index(drop=True)
    )

    salida["prediccion_retorno_pct"] = (
        salida["prediccion_retorno"]
        * 100.0
    )

    return salida


def cargar_retorno_real(
    processed: Path,
) -> tuple[pd.DataFrame, dict[str, object]]:
    ruta = (
        processed
        / "sbs_fondo3_base_maestra.csv"
    )

    if not ruta.exists():
        raise FileNotFoundError(
            f"No existe la base maestra SBS: {ruta}"
        )

    df = leer_csv_flexible(ruta)

    fecha_col = detectar_columna(
        df.columns,
        {
            "fecha",
            "date",
            "fecha_cuota",
            "fecha_valor_cuota",
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
    retorno_col = detectar_columna(
        df.columns,
        {
            "retorno_diario",
            "retorno",
            "return",
            "rentabilidad_diaria",
            "rendimiento_diario",
            "variacion_diaria",
        },
    )
    valor_col = detectar_columna(
        df.columns,
        {
            "valor_cuota",
            "valor_de_la_cuota",
            "cuota",
            "valor",
        },
    )

    if fecha_col is None or afp_col is None:
        raise ValueError(
            "La base maestra no contiene columnas "
            "reconocibles de fecha y AFP."
        )

    base = pd.DataFrame(
        {
            "fecha_real": pd.to_datetime(
                df[fecha_col],
                errors="coerce",
            ),
            "afp": df[afp_col].map(
                normalizar_afp
            ),
        }
    )

    metodo = ""

    if valor_col is not None:
        base["valor_cuota"] = pd.to_numeric(
            df[valor_col],
            errors="coerce",
        )
        base = base.sort_values(
            [
                "afp",
                "fecha_real",
            ]
        )
        base["retorno_real"] = (
            base.groupby("afp")[
                "valor_cuota"
            ]
            .pct_change(fill_method=None)
        )
        metodo = "calculado_desde_valor_cuota"

    elif retorno_col is not None:
        retorno, escala = normalizar_escala(
            df[retorno_col],
            retorno_col,
        )
        base["retorno_real"] = retorno
        metodo = (
            "columna_retorno_"
            + escala
        )

    else:
        raise ValueError(
            "La base maestra no contiene valor de "
            "cuota ni retorno diario reconocible."
        )

    salida = (
        base.dropna(
            subset=[
                "fecha_real",
                "afp",
                "retorno_real",
            ]
        )
        .sort_values(
            [
                "fecha_real",
                "afp",
            ]
        )
        .drop_duplicates(
            subset=[
                "fecha_real",
                "afp",
            ],
            keep="last",
        )
        .reset_index(drop=True)
    )

    control = {
        "ruta_base_real": str(
            ruta.resolve()
        ),
        "metodo_retorno_real": metodo,
        "fecha_minima_real": (
            salida["fecha_real"].min()
        ),
        "fecha_maxima_real": (
            salida["fecha_real"].max()
        ),
        "filas_retorno_real": int(
            len(salida)
        ),
        "afp_retorno_real": int(
            salida["afp"].nunique()
        ),
    }

    return salida, control


def construir_detalle(
    predicciones: pd.DataFrame,
    reales: pd.DataFrame,
) -> pd.DataFrame:
    detalle = predicciones.merge(
        reales,
        left_on=[
            "fecha_prediccion",
            "afp",
        ],
        right_on=[
            "fecha_real",
            "afp",
        ],
        how="left",
        validate="one_to_one",
    )

    detalle["estado_validacion"] = np.where(
        detalle["retorno_real"].notna(),
        "VALIDADO",
        "PENDIENTE_PUBLICACION",
    )

    detalle["retorno_real_pct"] = (
        detalle["retorno_real"]
        * 100.0
    )

    detalle["error"] = (
        detalle["prediccion_retorno"]
        - detalle["retorno_real"]
    )
    detalle["error_pct"] = (
        detalle["error"]
        * 100.0
    )
    detalle["error_absoluto"] = (
        detalle["error"].abs()
    )
    detalle["error_absoluto_pct"] = (
        detalle["error_absoluto"]
        * 100.0
    )
    detalle["error_cuadrado"] = (
        detalle["error"] ** 2
    )

    detalle["direccion_predicha"] = np.select(
        [
            detalle["prediccion_retorno"] > 0,
            detalle["prediccion_retorno"] < 0,
        ],
        [
            "positiva",
            "negativa",
        ],
        default="neutra",
    )

    detalle["direccion_real"] = np.select(
        [
            detalle["retorno_real"] > 0,
            detalle["retorno_real"] < 0,
        ],
        [
            "positiva",
            "negativa",
        ],
        default=np.where(
            detalle["retorno_real"].isna(),
            "pendiente",
            "neutra",
        ),
    )

    detalle["direccion_correcta"] = np.where(
        detalle["retorno_real"].notna(),
        (
            np.sign(
                detalle["prediccion_retorno"]
            )
            == np.sign(
                detalle["retorno_real"]
            )
        ),
        np.nan,
    )

    detalle["sobreestima"] = np.where(
        detalle["retorno_real"].notna(),
        detalle["error"] > 0,
        np.nan,
    )

    columnas = [
        "fecha_prediccion",
        "afp",
        "estimador",
        "prediccion_retorno",
        "prediccion_retorno_pct",
        "fecha_real",
        "retorno_real",
        "retorno_real_pct",
        "error",
        "error_pct",
        "error_absoluto",
        "error_absoluto_pct",
        "error_cuadrado",
        "direccion_predicha",
        "direccion_real",
        "direccion_correcta",
        "sobreestima",
        "estado_validacion",
    ]

    return detalle[columnas].sort_values(
        [
            "fecha_prediccion",
            "afp",
        ]
    ).reset_index(drop=True)


def nivel_muestra(n: int) -> str:
    if n < MIN_MUESTRA_ORIENTATIVA:
        return "insuficiente"
    if n < MIN_MUESTRA_ESTABLE:
        return "orientativa"
    return "estable"


def calcular_metricas(
    grupo: pd.DataFrame,
) -> dict[str, object]:
    validos = grupo[
        grupo["estado_validacion"].eq(
            "VALIDADO"
        )
    ].dropna(
        subset=[
            "retorno_real",
            "prediccion_retorno",
        ]
    )

    n = len(validos)

    if n == 0:
        return {
            "observaciones_validadas": 0,
            "nivel_muestra": "sin_datos",
            "rmse": np.nan,
            "mae": np.nan,
            "sesgo_medio": np.nan,
            "rmse_pct": np.nan,
            "mae_pct": np.nan,
            "sesgo_medio_pct": np.nan,
            "direccion_correcta_pct": np.nan,
            "correlacion": np.nan,
            "prediccion_media_pct": np.nan,
            "retorno_real_medio_pct": np.nan,
        }

    error = (
        validos["prediccion_retorno"]
        - validos["retorno_real"]
    )

    rmse = float(
        np.sqrt(
            np.mean(error ** 2)
        )
    )
    mae = float(
        np.mean(
            np.abs(error)
        )
    )
    sesgo = float(
        np.mean(error)
    )

    correlacion = (
        float(
            validos[
                [
                    "prediccion_retorno",
                    "retorno_real",
                ]
            ]
            .corr()
            .iloc[0, 1]
        )
        if n >= 3
        else np.nan
    )

    return {
        "observaciones_validadas": n,
        "nivel_muestra": nivel_muestra(n),
        "rmse": rmse,
        "mae": mae,
        "sesgo_medio": sesgo,
        "rmse_pct": rmse * 100.0,
        "mae_pct": mae * 100.0,
        "sesgo_medio_pct": sesgo * 100.0,
        "direccion_correcta_pct": float(
            validos[
                "direccion_correcta"
            ]
            .astype(float)
            .mean()
            * 100.0
        ),
        "correlacion": correlacion,
        "prediccion_media_pct": float(
            validos[
                "prediccion_retorno_pct"
            ].mean()
        ),
        "retorno_real_medio_pct": float(
            validos[
                "retorno_real_pct"
            ].mean()
        ),
    }


def construir_metricas_por_afp(
    detalle: pd.DataFrame,
) -> pd.DataFrame:
    filas = []

    for afp in AFPS:
        grupo = detalle[
            detalle["afp"].eq(afp)
        ]
        metricas = calcular_metricas(
            grupo
        )

        filas.append(
            {
                "afp": afp,
                **metricas,
                "observaciones_pendientes": int(
                    grupo[
                        "estado_validacion"
                    ].eq(
                        "PENDIENTE_PUBLICACION"
                    ).sum()
                ),
                "primera_fecha_prediccion": (
                    grupo[
                        "fecha_prediccion"
                    ].min()
                ),
                "ultima_fecha_prediccion": (
                    grupo[
                        "fecha_prediccion"
                    ].max()
                ),
            }
        )

    return pd.DataFrame(filas)



def construir_resumen_global(
    detalle: pd.DataFrame,
    control_real: dict[str, object],
) -> pd.DataFrame:
    metricas = calcular_metricas(
        detalle
    )

    fechas_validadas = (
        detalle.loc[
            detalle[
                "estado_validacion"
            ].eq("VALIDADO"),
            "fecha_prediccion",
        ]
        .dropna()
        .nunique()
    )
    fechas_pendientes = (
        detalle.loc[
            detalle[
                "estado_validacion"
            ].eq(
                "PENDIENTE_PUBLICACION"
            ),
            "fecha_prediccion",
        ]
        .dropna()
        .nunique()
    )

    fecha_maxima_real = pd.to_datetime(
        control_real.get(
            "fecha_maxima_real"
        ),
        errors="coerce",
    )

    fechas_pendientes_ordenadas = (
        detalle.loc[
            detalle[
                "estado_validacion"
            ].eq(
                "PENDIENTE_PUBLICACION"
            ),
            "fecha_prediccion",
        ]
        .dropna()
        .sort_values()
        .unique()
    )

    primera_fecha_pendiente = (
        pd.Timestamp(
            fechas_pendientes_ordenadas[0]
        )
        if len(
            fechas_pendientes_ordenadas
        )
        else pd.NaT
    )

    ultima_fecha_pendiente = (
        pd.Timestamp(
            fechas_pendientes_ordenadas[-1]
        )
        if len(
            fechas_pendientes_ordenadas
        )
        else pd.NaT
    )

    dias_brecha = np.nan

    if (
        pd.notna(fecha_maxima_real)
        and pd.notna(
            primera_fecha_pendiente
        )
    ):
        dias_brecha = int(
            (
                primera_fecha_pendiente.normalize()
                - fecha_maxima_real.normalize()
            ).days
        )

    return pd.DataFrame(
        [
            {
                **metricas,
                "fechas_validadas": int(
                    fechas_validadas
                ),
                "fechas_pendientes": int(
                    fechas_pendientes
                ),
                "filas_pendientes": int(
                    detalle[
                        "estado_validacion"
                    ].eq(
                        "PENDIENTE_PUBLICACION"
                    ).sum()
                ),
                "fecha_maxima_prediccion": (
                    detalle[
                        "fecha_prediccion"
                    ].max()
                ),
                "fecha_maxima_real_disponible": (
                    fecha_maxima_real
                ),
                "primera_fecha_pendiente": (
                    primera_fecha_pendiente
                ),
                "ultima_fecha_pendiente": (
                    ultima_fecha_pendiente
                ),
                "dias_brecha_hasta_primera_pendiente": (
                    dias_brecha
                ),
                "estado_ciclo": (
                    "PENDIENTE_DE_DATOS_OFICIALES"
                    if metricas[
                        "observaciones_validadas"
                    ]
                    == 0
                    else (
                        "VALIDACION_PARCIAL"
                        if fechas_pendientes > 0
                        else "VALIDACION_COMPLETA"
                    )
                ),
            }
        ]
    )


def construir_pendientes(
    detalle: pd.DataFrame,
) -> pd.DataFrame:
    return detalle[
        detalle["estado_validacion"].eq(
            "PENDIENTE_PUBLICACION"
        )
    ][
        [
            "fecha_prediccion",
            "afp",
            "estimador",
            "prediccion_retorno",
            "prediccion_retorno_pct",
            "estado_validacion",
        ]
    ].copy()


def construir_control(
    predicciones: pd.DataFrame,
    reales: pd.DataFrame,
    detalle: pd.DataFrame,
    control_real: dict[str, object],
) -> pd.DataFrame:
    controles = [
        {
            "control": "predicciones_sin_duplicados",
            "estado": (
                "correcto"
                if not predicciones.duplicated(
                    [
                        "fecha_prediccion",
                        "afp",
                    ]
                ).any()
                else "revisar"
            ),
            "detalle": (
                f"filas={len(predicciones)}"
            ),
        },
        {
            "control": "cuatro_afp_en_predicciones",
            "estado": (
                "correcto"
                if set(
                    predicciones["afp"]
                )
                == set(AFPS)
                else "revisar"
            ),
            "detalle": (
                ", ".join(
                    sorted(
                        predicciones[
                            "afp"
                        ].dropna().unique()
                    )
                )
            ),
        },
        {
            "control": "base_real_sin_duplicados",
            "estado": (
                "correcto"
                if not reales.duplicated(
                    [
                        "fecha_real",
                        "afp",
                    ]
                ).any()
                else "revisar"
            ),
            "detalle": (
                f"filas={len(reales)}"
            ),
        },
        {
            "control": "afp_en_base_real",
            "estado": (
                "correcto"
                if set(
                    reales["afp"]
                )
                == set(AFPS)
                else "revisar"
            ),
            "detalle": (
                f"afp={reales['afp'].nunique()}"
            ),
        },
        {
            "control": "alineacion_sin_lookahead",
            "estado": "correcto",
            "detalle": (
                "cada predicción se compara solo con "
                "el retorno oficial de su misma fecha y AFP"
            ),
        },
        {
            "control": "estado_publicacion",
            "estado": (
                "pendiente"
                if detalle[
                    "estado_validacion"
                ].eq(
                    "PENDIENTE_PUBLICACION"
                ).any()
                else "correcto"
            ),
            "detalle": (
                f"pendientes="
                f"{int(detalle['estado_validacion'].eq('PENDIENTE_PUBLICACION').sum())}; "
                f"fecha_maxima_real="
                f"{control_real['fecha_maxima_real']}"
            ),
        },
    ]

    return pd.DataFrame(controles)


def exportar_json(
    resumen: pd.DataFrame,
    metricas_afp: pd.DataFrame,
    pendientes: pd.DataFrame,
    control: pd.DataFrame,
    ruta: Path,
) -> None:
    def limpiar_registro(
        registro: dict[str, object],
    ) -> dict[str, object]:
        limpio: dict[str, object] = {}

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

        return limpio

    contenido = {
        "version": (
            "modelo49_validacion_expost"
        ),
        "resumen_global": [
            limpiar_registro(registro)
            for registro in resumen.to_dict(
                orient="records"
            )
        ],
        "metricas_por_afp": [
            limpiar_registro(registro)
            for registro in metricas_afp.to_dict(
                orient="records"
            )
        ],
        "pendientes": [
            limpiar_registro(registro)
            for registro in pendientes.to_dict(
                orient="records"
            )
        ],
        "control": control.to_dict(
            orient="records"
        ),
        "nota": (
            "Las métricas solo se calculan con retornos "
            "oficiales ya publicados. Una muestra menor "
            "a 20 observaciones es insuficiente para "
            "conclusiones de desempeño."
        ),
    }

    ruta.write_text(
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

    predicciones = cargar_predicciones(
        processed
    )
    reales, control_real = (
        cargar_retorno_real(
            processed
        )
    )
    detalle = construir_detalle(
        predicciones,
        reales,
    )
    metricas_afp = (
        construir_metricas_por_afp(
            detalle
        )
    )
    resumen = construir_resumen_global(
        detalle,
        control_real,
    )
    pendientes = construir_pendientes(
        detalle
    )
    control = construir_control(
        predicciones,
        reales,
        detalle,
        control_real,
    )

    rutas = {
        "detalle": (
            processed
            / "ca0001_modelo49_validacion_expost_detalle.csv"
        ),
        "metricas_afp": (
            processed
            / "ca0001_modelo49_metricas_por_afp.csv"
        ),
        "resumen": (
            processed
            / "ca0001_modelo49_resumen_global.csv"
        ),
        "pendientes": (
            processed
            / "ca0001_modelo49_pendientes_publicacion.csv"
        ),
        "control": (
            processed
            / "ca0001_modelo49_control.csv"
        ),
        "json": (
            processed
            / "ca0001_modelo49_validacion_expost.json"
        ),
    }

    detalle.to_csv(
        rutas["detalle"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    metricas_afp.to_csv(
        rutas["metricas_afp"],
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
    pendientes.to_csv(
        rutas["pendientes"],
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
        resumen,
        metricas_afp,
        pendientes,
        control,
        rutas["json"],
    )

    print(
        "\nVALIDACIÓN EX POST DEL NOWCAST CORREGIDA TERMINADA"
    )
    print("=" * 120)

    print("\nRESUMEN GLOBAL")
    print("-" * 120)
    print(
        resumen.to_string(index=False)
    )

    print("\nMÉTRICAS POR AFP")
    print("-" * 120)
    print(
        metricas_afp.to_string(
            index=False
        )
    )

    print("\nPREDICCIONES PENDIENTES DE DATO OFICIAL")
    print("-" * 120)

    if pendientes.empty:
        print(
            "No existen predicciones pendientes."
        )
    else:
        print(
            pendientes.to_string(
                index=False
            )
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
        "\nCriterio de lectura:\n"
        "- PENDIENTE_PUBLICACION no es un error: significa "
        "que la SBS todavía no figura en la base maestra para "
        "esa fecha.\n"
        "- Las métricas se recalculan automáticamente cuando "
        "sbs_fondo3_base_maestra.csv incorpore nuevas cuotas.\n"
        "- Menos de 20 observaciones validadas se considera una "
        "muestra insuficiente; entre 20 y 59, orientativa; desde "
        "60, más estable.\n"
        "- La validación compara cada nowcast únicamente con el "
        "retorno oficial de la misma AFP y fecha."
    )


if __name__ == "__main__":
    main()
