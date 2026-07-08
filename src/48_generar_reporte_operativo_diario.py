from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


AFPS = ["Habitat", "Integra", "Prima", "Profuturo"]

UMBRAL_DEBIL = 0.50
UMBRAL_MODERADO = 1.00
UMBRAL_DISPERSION_BAJA_PP = 0.05


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
        if limpiar_nombre(columna) in alias_limpios:
            return str(columna)

    return None


def normalizar_afp(valor: object) -> str | None:
    limpio = limpiar_nombre(valor)

    for afp in AFPS:
        if limpiar_nombre(afp) in limpio:
            return afp

    return None


def convertir_booleano(serie: pd.Series) -> pd.Series:
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
                "verdadero",
            }
        )
    )


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


def cargar_nowcast_validado(
    processed: Path,
) -> pd.DataFrame:
    ruta = (
        processed
        / "ca0001_modelo47_nowcast_actual_validado.csv"
    )

    if not ruta.exists():
        raise FileNotFoundError(
            "No existe la salida validada del módulo 47."
        )

    df = leer_csv_flexible(ruta)

    for columna in [
        "fecha_prediccion",
        "fecha_mercado_referencia",
        "fecha_fin_validez",
    ]:
        if columna in df.columns:
            df[columna] = pd.to_datetime(
                df[columna],
                errors="coerce",
            )

    for columna in [
        "prediccion_retorno",
        "prediccion_retorno_pct",
        "rmse_oos_base",
        "ratio_prediccion_rmse",
        "lambda_operativo_actual",
    ]:
        if columna in df.columns:
            df[columna] = pd.to_numeric(
                df[columna],
                errors="coerce",
            )

    if "composicion_vigente" in df.columns:
        df["composicion_vigente"] = (
            convertir_booleano(
                df["composicion_vigente"]
            )
        )

    df["afp"] = df["afp"].map(
        normalizar_afp
    )

    return df


def cargar_control(
    processed: Path,
) -> pd.DataFrame:
    ruta = (
        processed
        / "ca0001_modelo47_control.csv"
    )

    if not ruta.exists():
        raise FileNotFoundError(
            "No existe el control del módulo 47."
        )

    return leer_csv_flexible(ruta)


def cargar_estado_composicion(
    processed: Path,
) -> pd.DataFrame:
    ruta = (
        processed
        / "ca0001_modelo44_estado_operativo.csv"
    )

    if not ruta.exists():
        return pd.DataFrame()

    df = leer_csv_flexible(ruta)

    for columna in [
        "fecha_fin_validez",
        "fecha_mercado_referencia",
    ]:
        if columna in df.columns:
            df[columna] = pd.to_datetime(
                df[columna],
                errors="coerce",
            )

    if "composicion_vigente" in df.columns:
        df["composicion_vigente"] = (
            convertir_booleano(
                df["composicion_vigente"]
            )
        )

    df["afp"] = df["afp"].map(
        normalizar_afp
    )

    return df


def cargar_tendencia_historica(
    processed: Path,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    ruta = (
        processed
        / "nowcast_historico_estimaciones.csv"
    )

    if not ruta.exists():
        return pd.DataFrame(), pd.DataFrame()

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

    if any(
        columna is None
        for columna in [
            fecha_col,
            afp_col,
            pred_col,
        ]
    ):
        return pd.DataFrame(), pd.DataFrame()

    prediccion, escala = normalizar_escala(
        df[pred_col],
        pred_col,
    )

    detalle = pd.DataFrame(
        {
            "fecha_prediccion": pd.to_datetime(
                df[fecha_col],
                errors="coerce",
            ),
            "afp": df[afp_col].map(
                normalizar_afp
            ),
            "estimador": (
                df[modelo_col].astype(str)
                if modelo_col is not None
                else ""
            ),
            "prediccion_retorno": prediccion,
            "escala": escala,
        }
    ).dropna(
        subset=[
            "fecha_prediccion",
            "afp",
            "prediccion_retorno",
        ]
    )

    detalle = (
        detalle.sort_values(
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

    detalle["prediccion_retorno_pct"] = (
        detalle["prediccion_retorno"]
        * 100.0
    )
    detalle["direccion"] = np.select(
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

    resumen = (
        detalle.groupby(
            "fecha_prediccion",
            as_index=False,
        )
        .agg(
            afp_disponibles=(
                "afp",
                "nunique",
            ),
            retorno_medio_pct=(
                "prediccion_retorno_pct",
                "mean",
            ),
            retorno_mediano_pct=(
                "prediccion_retorno_pct",
                "median",
            ),
            retorno_minimo_pct=(
                "prediccion_retorno_pct",
                "min",
            ),
            retorno_maximo_pct=(
                "prediccion_retorno_pct",
                "max",
            ),
            afp_positivas=(
                "prediccion_retorno",
                lambda serie: int(
                    (serie > 0).sum()
                ),
            ),
            afp_negativas=(
                "prediccion_retorno",
                lambda serie: int(
                    (serie < 0).sum()
                ),
            ),
        )
    )

    resumen[
        "dispersion_entre_afp_pp"
    ] = (
        resumen["retorno_maximo_pct"]
        - resumen["retorno_minimo_pct"]
    )

    return detalle, resumen


def clasificar_estado_global(
    nowcast: pd.DataFrame,
    control: pd.DataFrame,
) -> dict[str, object]:
    controles_correctos = bool(
        control["estado"]
        .astype(str)
        .str.lower()
        .eq("correcto")
        .all()
    )

    afp_validadas = int(
        nowcast[
            "estado_validacion"
        ].eq("validado").sum()
    )

    ratio_mediano = float(
        nowcast[
            "ratio_prediccion_rmse"
        ].median()
    )
    dispersion = float(
        nowcast[
            "prediccion_retorno_pct"
        ].max()
        - nowcast[
            "prediccion_retorno_pct"
        ].min()
    )
    signos = set(
        nowcast[
            "direccion_analitica"
        ].dropna()
    )

    if not controles_correctos or afp_validadas != 4:
        estado = "NO_VALIDADO"
        intensidad = "no_clasificada"
    elif ratio_mediano < UMBRAL_DEBIL:
        estado = "VALIDADO_DEBIL"
        intensidad = "debil"
    elif ratio_mediano < UMBRAL_MODERADO:
        estado = "VALIDADO_MODERADO"
        intensidad = "moderada"
    else:
        estado = "VALIDADO_ALTO"
        intensidad = "alta"

    consenso = (
        signos.pop()
        if len(signos) == 1
        else "mixto"
    )

    diferenciacion = (
        "baja"
        if dispersion
        <= UMBRAL_DISPERSION_BAJA_PP
        else "relevante"
    )

    accionabilidad = (
        "no_concluyente_por_si_sola"
        if estado
        in {
            "VALIDADO_DEBIL",
            "VALIDADO_MODERADO",
        }
        else (
            "revisar_antes_de_uso"
            if estado == "NO_VALIDADO"
            else "requiere_confirmacion_adicional"
        )
    )

    return {
        "estado_global": estado,
        "intensidad_global": intensidad,
        "consenso_direccion": consenso,
        "diferenciacion_entre_afp": diferenciacion,
        "accionabilidad_estadistica": accionabilidad,
        "afp_validadas": afp_validadas,
        "controles_correctos": controles_correctos,
        "ratio_rmse_mediano": ratio_mediano,
        "dispersion_entre_afp_pp": dispersion,
    }


def construir_alertas(
    nowcast: pd.DataFrame,
    control: pd.DataFrame,
    estado: dict[str, object],
    composicion: pd.DataFrame,
) -> pd.DataFrame:
    alertas: list[dict[str, object]] = []

    for _, fila in control.iterrows():
        if str(fila["estado"]).lower() != "correcto":
            alertas.append(
                {
                    "nivel": "critico",
                    "codigo": (
                        f"CONTROL_{fila['control']}"
                    ),
                    "mensaje": fila.get(
                        "detalle",
                        "",
                    ),
                }
            )

    if (
        estado["estado_global"]
        == "VALIDADO_DEBIL"
    ):
        alertas.append(
            {
                "nivel": "informativo",
                "codigo": "SENAL_DEBIL",
                "mensaje": (
                    "La predicción mediana equivale a "
                    f"{estado['ratio_rmse_mediano']:.3f} "
                    "veces el RMSE OOS."
                ),
            }
        )

    if (
        estado[
            "diferenciacion_entre_afp"
        ]
        == "baja"
    ):
        alertas.append(
            {
                "nivel": "informativo",
                "codigo": "BAJA_DIFERENCIACION_AFP",
                "mensaje": (
                    "La dispersión entre AFP es "
                    f"{estado['dispersion_entre_afp_pp']:.4f} "
                    "puntos porcentuales."
                ),
            }
        )

    if not composicion.empty:
        vencidas = int(
            (
                ~composicion[
                    "composicion_vigente"
                ]
            ).sum()
        )

        if vencidas:
            alertas.append(
                {
                    "nivel": "operativo",
                    "codigo": "COMPOSICION_VENCIDA",
                    "mensaje": (
                        f"{vencidas} AFP operan con "
                        "fallback M0_base_mercado."
                    ),
                }
            )

    if not alertas:
        alertas.append(
            {
                "nivel": "sin_alertas",
                "codigo": "OK",
                "mensaje": (
                    "No se identificaron alertas."
                ),
            }
        )

    return pd.DataFrame(alertas)


def construir_resumen_ejecutivo(
    nowcast: pd.DataFrame,
    estado: dict[str, object],
    tendencia_resumen: pd.DataFrame,
) -> pd.DataFrame:
    fecha = nowcast[
        "fecha_prediccion"
    ].max()

    dias_historicos = int(
        tendencia_resumen[
            "fecha_prediccion"
        ].nunique()
    ) if not tendencia_resumen.empty else 0

    return pd.DataFrame(
        [
            {
                "fecha_prediccion": fecha,
                "estado_global": (
                    estado["estado_global"]
                ),
                "intensidad_global": (
                    estado["intensidad_global"]
                ),
                "consenso_direccion": (
                    estado[
                        "consenso_direccion"
                    ]
                ),
                "diferenciacion_entre_afp": (
                    estado[
                        "diferenciacion_entre_afp"
                    ]
                ),
                "accionabilidad_estadistica": (
                    estado[
                        "accionabilidad_estadistica"
                    ]
                ),
                "afp_validadas": (
                    estado["afp_validadas"]
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
                "dispersion_entre_afp_pp": (
                    estado[
                        "dispersion_entre_afp_pp"
                    ]
                ),
                "ratio_rmse_mediano": (
                    estado[
                        "ratio_rmse_mediano"
                    ]
                ),
                "dias_tendencia_disponibles": (
                    dias_historicos
                ),
                "modelo_operativo": (
                    "M0_base_mercado"
                ),
                "composicion_utilizada": False,
                "lectura": (
                    "Sesgo positivo débil y homogéneo; "
                    "sin diferenciación estadística suficiente "
                    "entre AFP y sin señal fuerte por sí sola."
                ),
            }
        ]
    )


def construir_markdown(
    nowcast: pd.DataFrame,
    resumen: pd.DataFrame,
    tendencia: pd.DataFrame,
    alertas: pd.DataFrame,
) -> str:
    fila = resumen.iloc[0]
    fecha = pd.Timestamp(
        fila["fecha_prediccion"]
    ).strftime("%Y-%m-%d")

    lineas = [
        f"# Reporte operativo AFP Fondo 3 — {fecha}",
        "",
        "## Estado general",
        "",
        f"- Estado: **{fila['estado_global']}**",
        f"- Dirección común: **{fila['consenso_direccion']}**",
        f"- Intensidad: **{fila['intensidad_global']}**",
        (
            "- Diferenciación entre AFP: "
            f"**{fila['diferenciacion_entre_afp']}**"
        ),
        (
            "- Modelo operativo: "
            f"**{fila['modelo_operativo']}**"
        ),
        "- Composición CA-0001 utilizada: **No**",
        "",
        "## Nowcast por AFP",
        "",
        "| AFP | Estimador | Retorno estimado | Ratio / RMSE | Lectura |",
        "|---|---|---:|---:|---|",
    ]

    for _, registro in nowcast.iterrows():
        lineas.append(
            "| "
            f"{registro['afp']} | "
            f"{registro['estimador_raw']} | "
            f"{registro['prediccion_retorno_pct']:.4f}% | "
            f"{registro['ratio_prediccion_rmse']:.3f} | "
            f"{registro['magnitud_analitica']} |"
        )

    lineas.extend(
        [
            "",
            "## Lectura ejecutiva",
            "",
            str(fila["lectura"]),
            "",
        ]
    )

    if not tendencia.empty:
        lineas.extend(
            [
                "## Tendencia disponible",
                "",
                "| Fecha | Retorno medio | AFP positivas | AFP negativas | Dispersión |",
                "|---|---:|---:|---:|---:|",
            ]
        )

        for _, registro in tendencia.iterrows():
            fecha_t = pd.Timestamp(
                registro[
                    "fecha_prediccion"
                ]
            ).strftime("%Y-%m-%d")

            lineas.append(
                "| "
                f"{fecha_t} | "
                f"{registro['retorno_medio_pct']:.4f}% | "
                f"{int(registro['afp_positivas'])} | "
                f"{int(registro['afp_negativas'])} | "
                f"{registro['dispersion_entre_afp_pp']:.4f} pp |"
            )

        lineas.append("")

    lineas.extend(
        [
            "## Alertas",
            "",
        ]
    )

    for _, alerta in alertas.iterrows():
        lineas.append(
            f"- **{alerta['codigo']}**: "
            f"{alerta['mensaje']}"
        )

    lineas.extend(
        [
            "",
            "## Nota metodológica",
            "",
            (
                "Este reporte es un diagnóstico estadístico. "
                "No constituye una recomendación de compra, venta, "
                "cambio de fondo o decisión financiera."
            ),
            "",
        ]
    )

    return "\n".join(lineas)


def exportar_json(
    nowcast: pd.DataFrame,
    resumen: pd.DataFrame,
    tendencia: pd.DataFrame,
    alertas: pd.DataFrame,
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
            "modelo48_reporte_operativo_diario"
        ),
        "resumen": [
            limpiar_registro(registro)
            for registro in resumen.to_dict(
                orient="records"
            )
        ],
        "nowcast": [
            limpiar_registro(registro)
            for registro in nowcast.to_dict(
                orient="records"
            )
        ],
        "tendencia": [
            limpiar_registro(registro)
            for registro in tendencia.to_dict(
                orient="records"
            )
        ],
        "alertas": alertas.to_dict(
            orient="records"
        ),
        "nota": (
            "Diagnóstico estadístico; no constituye "
            "recomendación financiera."
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

    nowcast = cargar_nowcast_validado(
        processed
    )
    control = cargar_control(
        processed
    )
    composicion = cargar_estado_composicion(
        processed
    )
    (
        tendencia_detalle,
        tendencia_resumen,
    ) = cargar_tendencia_historica(
        processed
    )

    estado = clasificar_estado_global(
        nowcast,
        control,
    )
    alertas = construir_alertas(
        nowcast,
        control,
        estado,
        composicion,
    )
    resumen = construir_resumen_ejecutivo(
        nowcast,
        estado,
        tendencia_resumen,
    )
    markdown = construir_markdown(
        nowcast,
        resumen,
        tendencia_resumen,
        alertas,
    )

    rutas = {
        "resumen": (
            processed
            / "ca0001_modelo48_resumen_ejecutivo.csv"
        ),
        "alertas": (
            processed
            / "ca0001_modelo48_alertas.csv"
        ),
        "tendencia_detalle": (
            processed
            / "ca0001_modelo48_tendencia_detalle.csv"
        ),
        "tendencia_resumen": (
            processed
            / "ca0001_modelo48_tendencia_resumen.csv"
        ),
        "reporte_md": (
            processed
            / "ca0001_modelo48_reporte_operativo_diario.md"
        ),
        "reporte_json": (
            processed
            / "ca0001_modelo48_reporte_operativo_diario.json"
        ),
    }

    resumen.to_csv(
        rutas["resumen"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    alertas.to_csv(
        rutas["alertas"],
        index=False,
        encoding="utf-8-sig",
    )
    tendencia_detalle.to_csv(
        rutas["tendencia_detalle"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    tendencia_resumen.to_csv(
        rutas["tendencia_resumen"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    rutas["reporte_md"].write_text(
        markdown,
        encoding="utf-8",
    )
    exportar_json(
        nowcast,
        resumen,
        tendencia_resumen,
        alertas,
        rutas["reporte_json"],
    )

    print(
        "\nREPORTE OPERATIVO DIARIO GENERADO"
    )
    print("=" * 120)

    print("\nRESUMEN EJECUTIVO")
    print("-" * 120)
    print(
        resumen.to_string(index=False)
    )

    print("\nNOWCAST POR AFP")
    print("-" * 120)
    print(
        nowcast[
            [
                "afp",
                "estimador_raw",
                "prediccion_retorno_pct",
                "ratio_prediccion_rmse",
                "direccion_analitica",
                "magnitud_analitica",
                "estado_validacion",
            ]
        ].to_string(index=False)
    )

    print("\nTENDENCIA DISPONIBLE")
    print("-" * 120)

    if tendencia_resumen.empty:
        print(
            "No existe una serie histórica compatible."
        )
    else:
        print(
            tendencia_resumen.to_string(
                index=False
            )
        )

    print("\nALERTAS")
    print("-" * 120)
    print(
        alertas.to_string(index=False)
    )

    print("\nArchivos creados:")
    for ruta in rutas.values():
        print(f" - {ruta.resolve()}")

    print(
        "\nCriterio de lectura:\n"
        "- VALIDADO_DEBIL significa que los controles son correctos, "
        "pero la señal mediana es inferior a 0.5 veces el RMSE OOS.\n"
        "- Baja diferenciación significa que las AFP presentan estimaciones "
        "muy cercanas entre sí.\n"
        "- La composición CA-0001 permanece fuera del nowcast mientras "
        "sus ventanas públicas estén vencidas.\n"
        "- El reporte es diagnóstico y no constituye una recomendación "
        "financiera ni una instrucción de cambio de fondo."
    )


if __name__ == "__main__":
    main()
