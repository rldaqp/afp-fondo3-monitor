from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


AFPS = ["Habitat", "Integra", "Prima", "Profuturo"]

UMBRAL_ALERTA_TURNOVER = 0.35
UMBRAL_ALERTA_TOP5 = 0.60
UMBRAL_ALERTA_HHI = 0.15
UMBRAL_ALERTA_REESCALA_BAJO = 0.90
UMBRAL_ALERTA_REESCALA_ALTO = 1.10
TOLERANCIA_PESOS = 1e-6


def leer_csv(ruta: Path, fechas: list[str] | None = None) -> pd.DataFrame:
    if not ruta.exists():
        raise FileNotFoundError(f"No existe: {ruta}")

    return pd.read_csv(
        ruta,
        parse_dates=fechas or [],
    )


def convertir_booleano(serie: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(serie):
        return serie.fillna(False)

    return (
        serie.fillna(False)
        .astype(str)
        .str.strip()
        .str.lower()
        .isin({"true", "1", "si", "sí", "yes"})
    )


def preparar_base(df: pd.DataFrame) -> pd.DataFrame:
    salida = df.copy()

    salida["fecha_cartera"] = pd.to_datetime(
        salida["fecha_cartera"],
        errors="coerce",
    )
    salida["periodo"] = (
        salida["fecha_cartera"]
        .dt.to_period("M")
        .astype(str)
    )

    numericas = [
        "valor",
        "valor_reconciliado_miles_soles",
        "peso_exterior_reconciliado",
        "peso_total_fondo_reconciliado",
        "peso_exterior_reconciliado_pct",
        "peso_total_fondo_reconciliado_pct",
        "factor_reescala",
        "error_cobertura_pct",
        "total_exterior_miles_soles",
        "total_fondo_miles_soles",
    ]

    for columna in numericas:
        if columna in salida.columns:
            salida[columna] = pd.to_numeric(
                salida[columna],
                errors="coerce",
            )

    for columna in [
        "afp",
        "identificador_final",
        "tipo_identificador",
        "entidad_administradora",
        "moneda",
        "estado_cobertura",
        "isin",
    ]:
        if columna not in salida.columns:
            salida[columna] = ""
        salida[columna] = (
            salida[columna]
            .fillna("")
            .astype(str)
            .str.strip()
        )

    salida["usar_modelo_principal"] = convertir_booleano(
        salida["usar_modelo_principal"]
    )
    salida["usar_analisis_ampliado"] = convertir_booleano(
        salida["usar_analisis_ampliado"]
    )

    salida["moneda_normalizada"] = (
        salida["moneda"]
        .replace("", "SIN_DATO")
        .str.upper()
    )

    salida["gestora_normalizada"] = (
        salida["entidad_administradora"]
        .replace("", "SIN_GESTORA")
        .str.upper()
    )

    salida["es_isin"] = salida["tipo_identificador"].eq("isin")
    salida["es_fondo_sin_isin"] = salida[
        "tipo_identificador"
    ].eq("fondo_sin_isin")

    return salida


def construir_escenarios(base: pd.DataFrame) -> dict[str, pd.DataFrame]:
    return {
        "principal_5pct": base[
            base["usar_modelo_principal"]
        ].copy(),
        "ampliado_15pct": base[
            base["usar_analisis_ampliado"]
        ].copy(),
    }


def hhi(serie: pd.Series) -> float:
    valores = pd.to_numeric(serie, errors="coerce").fillna(0.0)
    return float(np.square(valores).sum())


def sumar_top(serie: pd.Series, n: int) -> float:
    valores = (
        pd.to_numeric(serie, errors="coerce")
        .fillna(0.0)
        .sort_values(ascending=False)
    )
    return float(valores.head(n).sum())


def construir_features(
    escenarios: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    filas = []

    for escenario, df in escenarios.items():
        for (periodo, afp), grupo in df.groupby(
            ["periodo", "afp"],
            sort=True,
        ):
            grupo = grupo.copy()

            pesos = grupo["peso_exterior_reconciliado"].fillna(0.0)
            pesos_fondo = grupo[
                "peso_total_fondo_reconciliado"
            ].fillna(0.0)

            por_gestora = (
                grupo.groupby("gestora_normalizada")[
                    "peso_exterior_reconciliado"
                ]
                .sum()
            )
            por_moneda = (
                grupo.groupby("moneda_normalizada")[
                    "peso_exterior_reconciliado"
                ]
                .sum()
            )

            filas.append(
                {
                    "escenario": escenario,
                    "periodo": periodo,
                    "fecha_cartera": grupo[
                        "fecha_cartera"
                    ].max(),
                    "afp": afp,
                    "estado_cobertura": grupo[
                        "estado_cobertura"
                    ].iloc[0],
                    "factor_reescala": grupo[
                        "factor_reescala"
                    ].iloc[0],
                    "error_cobertura_pct": grupo[
                        "error_cobertura_pct"
                    ].iloc[0],
                    "total_exterior_miles_soles": grupo[
                        "total_exterior_miles_soles"
                    ].iloc[0],
                    "total_fondo_miles_soles": grupo[
                        "total_fondo_miles_soles"
                    ].iloc[0],
                    "numero_identificadores": grupo[
                        "identificador_final"
                    ].nunique(),
                    "numero_isin": grupo.loc[
                        grupo["es_isin"],
                        "identificador_final",
                    ].nunique(),
                    "numero_fondos_sin_isin": grupo.loc[
                        grupo["es_fondo_sin_isin"],
                        "identificador_final",
                    ].nunique(),
                    "peso_isin_exterior": float(
                        grupo.loc[
                            grupo["es_isin"],
                            "peso_exterior_reconciliado",
                        ].sum()
                    ),
                    "peso_fondos_sin_isin_exterior": float(
                        grupo.loc[
                            grupo["es_fondo_sin_isin"],
                            "peso_exterior_reconciliado",
                        ].sum()
                    ),
                    "peso_usd_exterior": float(
                        por_moneda.get("USD", 0.0)
                    ),
                    "peso_eur_exterior": float(
                        por_moneda.get("EUR", 0.0)
                    ),
                    "peso_jpy_exterior": float(
                        por_moneda.get("JPY", 0.0)
                    ),
                    "peso_sin_moneda_exterior": float(
                        por_moneda.get("SIN_DATO", 0.0)
                    ),
                    "peso_otras_monedas_exterior": float(
                        por_moneda.drop(
                            labels=[
                                "USD",
                                "EUR",
                                "JPY",
                                "SIN_DATO",
                            ],
                            errors="ignore",
                        ).sum()
                    ),
                    "top1_exterior": sumar_top(pesos, 1),
                    "top5_exterior": sumar_top(pesos, 5),
                    "top10_exterior": sumar_top(pesos, 10),
                    "hhi_identificadores": hhi(pesos),
                    "hhi_gestoras": hhi(por_gestora),
                    "suma_pesos_exterior": float(pesos.sum()),
                    "suma_pesos_total_fondo": float(
                        pesos_fondo.sum()
                    ),
                    "exterior_sobre_total_fondo": float(
                        grupo["total_exterior_miles_soles"].iloc[0]
                        / grupo["total_fondo_miles_soles"].iloc[0]
                    )
                    if abs(
                        grupo["total_fondo_miles_soles"].iloc[0]
                    )
                    > 0
                    else np.nan,
                }
            )

    return pd.DataFrame(filas)


def construir_control_pesos(features: pd.DataFrame) -> pd.DataFrame:
    control = features.copy()

    control["error_suma_exterior"] = (
        control["suma_pesos_exterior"] - 1.0
    ).abs()
    control["error_suma_total_fondo"] = (
        control["suma_pesos_total_fondo"]
        - control["exterior_sobre_total_fondo"]
    ).abs()

    control["estado_suma_exterior"] = np.where(
        control["error_suma_exterior"] <= TOLERANCIA_PESOS,
        "correcto",
        "revisar",
    )
    control["estado_suma_total_fondo"] = np.where(
        control["error_suma_total_fondo"] <= TOLERANCIA_PESOS,
        "correcto",
        "revisar",
    )

    return control


def meses_entre(periodo_anterior: str, periodo_actual: str) -> int:
    anterior = pd.Period(periodo_anterior, freq="M")
    actual = pd.Period(periodo_actual, freq="M")
    return int(actual.ordinal - anterior.ordinal)


def construir_turnover(
    escenarios: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    filas = []

    for escenario, df in escenarios.items():
        for afp, grupo_afp in df.groupby("afp"):
            periodos = sorted(grupo_afp["periodo"].unique())

            for anterior, actual in zip(periodos[:-1], periodos[1:]):
                anterior_df = (
                    grupo_afp[
                        grupo_afp["periodo"] == anterior
                    ][
                        [
                            "identificador_final",
                            "peso_exterior_reconciliado",
                        ]
                    ]
                    .groupby(
                        "identificador_final",
                        as_index=False,
                    )
                    .sum()
                    .rename(
                        columns={
                            "peso_exterior_reconciliado": (
                                "peso_anterior"
                            )
                        }
                    )
                )

                actual_df = (
                    grupo_afp[
                        grupo_afp["periodo"] == actual
                    ][
                        [
                            "identificador_final",
                            "peso_exterior_reconciliado",
                        ]
                    ]
                    .groupby(
                        "identificador_final",
                        as_index=False,
                    )
                    .sum()
                    .rename(
                        columns={
                            "peso_exterior_reconciliado": (
                                "peso_actual"
                            )
                        }
                    )
                )

                comparacion = anterior_df.merge(
                    actual_df,
                    on="identificador_final",
                    how="outer",
                ).fillna(0.0)

                turnover = float(
                    0.5
                    * (
                        comparacion["peso_actual"]
                        - comparacion["peso_anterior"]
                    )
                    .abs()
                    .sum()
                )
                solapamiento = float(
                    np.minimum(
                        comparacion["peso_actual"],
                        comparacion["peso_anterior"],
                    ).sum()
                )

                filas.append(
                    {
                        "escenario": escenario,
                        "afp": afp,
                        "periodo_anterior": anterior,
                        "periodo_actual": actual,
                        "salto_meses": meses_entre(
                            anterior,
                            actual,
                        ),
                        "turnover_mensual": turnover,
                        "solapamiento_pesos": solapamiento,
                        "identificadores_nuevos": int(
                            (
                                (comparacion["peso_anterior"] == 0)
                                & (comparacion["peso_actual"] > 0)
                            ).sum()
                        ),
                        "identificadores_salientes": int(
                            (
                                (comparacion["peso_anterior"] > 0)
                                & (comparacion["peso_actual"] == 0)
                            ).sum()
                        ),
                        "comparacion_consecutiva": (
                            meses_entre(anterior, actual) == 1
                        ),
                    }
                )

    return pd.DataFrame(filas)


def construir_secuencias(
    escenarios: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    filas = []

    for escenario, df in escenarios.items():
        for afp, grupo in df.groupby("afp"):
            periodos = sorted(
                pd.PeriodIndex(
                    grupo["periodo"].unique(),
                    freq="M",
                )
            )

            if not periodos:
                continue

            inicio = periodos[0]
            anterior = periodos[0]

            for actual in periodos[1:]:
                if actual.ordinal - anterior.ordinal == 1:
                    anterior = actual
                    continue

                filas.append(
                    {
                        "escenario": escenario,
                        "afp": afp,
                        "inicio": str(inicio),
                        "fin": str(anterior),
                        "meses_consecutivos": (
                            anterior.ordinal - inicio.ordinal + 1
                        ),
                    }
                )
                inicio = actual
                anterior = actual

            filas.append(
                {
                    "escenario": escenario,
                    "afp": afp,
                    "inicio": str(inicio),
                    "fin": str(anterior),
                    "meses_consecutivos": (
                        anterior.ordinal - inicio.ordinal + 1
                    ),
                }
            )

    return pd.DataFrame(filas).sort_values(
        [
            "escenario",
            "afp",
            "meses_consecutivos",
        ],
        ascending=[True, True, False],
    )


def construir_persistencia(
    escenarios: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    filas = []

    for escenario, df in escenarios.items():
        meses_totales = (
            df.groupby("afp")["periodo"]
            .nunique()
            .to_dict()
        )

        resumen = (
            df.groupby(
                [
                    "afp",
                    "identificador_final",
                    "tipo_identificador",
                    "isin",
                    "entidad_administradora",
                    "moneda_normalizada",
                ],
                dropna=False,
                as_index=False,
            )
            .agg(
                primera_fecha=("fecha_cartera", "min"),
                ultima_fecha=("fecha_cartera", "max"),
                meses_presentes=("periodo", "nunique"),
                peso_mediano_exterior=(
                    "peso_exterior_reconciliado",
                    "median",
                ),
                peso_promedio_exterior=(
                    "peso_exterior_reconciliado",
                    "mean",
                ),
                peso_maximo_exterior=(
                    "peso_exterior_reconciliado",
                    "max",
                ),
                peso_mediano_total_fondo=(
                    "peso_total_fondo_reconciliado",
                    "median",
                ),
            )
        )

        resumen["escenario"] = escenario
        resumen["meses_elegibles_afp"] = resumen["afp"].map(
            meses_totales
        )
        resumen["persistencia_pct"] = np.where(
            resumen["meses_elegibles_afp"] > 0,
            resumen["meses_presentes"]
            / resumen["meses_elegibles_afp"]
            * 100.0,
            np.nan,
        )

        filas.append(resumen)

    return pd.concat(
        filas,
        ignore_index=True,
        sort=False,
    )


def construir_alertas(
    features: pd.DataFrame,
    turnover: pd.DataFrame,
) -> pd.DataFrame:
    alertas = []

    for _, fila in features.iterrows():
        motivos = []

        if fila["top5_exterior"] >= UMBRAL_ALERTA_TOP5:
            motivos.append("top5_alto")
        if fila["hhi_identificadores"] >= UMBRAL_ALERTA_HHI:
            motivos.append("hhi_identificadores_alto")
        if (
            fila["factor_reescala"]
            < UMBRAL_ALERTA_REESCALA_BAJO
            or fila["factor_reescala"]
            > UMBRAL_ALERTA_REESCALA_ALTO
        ):
            motivos.append("reescala_material")

        if motivos:
            alertas.append(
                {
                    "tipo_alerta": "estructura_mensual",
                    "escenario": fila["escenario"],
                    "afp": fila["afp"],
                    "periodo": fila["periodo"],
                    "motivos": " | ".join(motivos),
                    "valor_principal": fila["top5_exterior"],
                    "valor_secundario": fila[
                        "hhi_identificadores"
                    ],
                }
            )

    if not turnover.empty:
        consecutivo = turnover[
            turnover["comparacion_consecutiva"]
        ]

        for _, fila in consecutivo.iterrows():
            if (
                fila["turnover_mensual"]
                >= UMBRAL_ALERTA_TURNOVER
            ):
                alertas.append(
                    {
                        "tipo_alerta": "turnover",
                        "escenario": fila["escenario"],
                        "afp": fila["afp"],
                        "periodo": fila["periodo_actual"],
                        "motivos": "turnover_mensual_alto",
                        "valor_principal": fila[
                            "turnover_mensual"
                        ],
                        "valor_secundario": fila[
                            "solapamiento_pesos"
                        ],
                    }
                )

    return pd.DataFrame(alertas)


def resumen_cobertura(
    features: pd.DataFrame,
) -> pd.DataFrame:
    return (
        features.groupby(
            ["escenario", "afp"],
            as_index=False,
        )
        .agg(
            periodos=("periodo", "nunique"),
            primera_fecha=("fecha_cartera", "min"),
            ultima_fecha=("fecha_cartera", "max"),
            error_cobertura_mediano_pct=(
                "error_cobertura_pct",
                "median",
            ),
            factor_reescala_mediano=(
                "factor_reescala",
                "median",
            ),
            numero_identificadores_mediano=(
                "numero_identificadores",
                "median",
            ),
            top5_mediano=("top5_exterior", "median"),
            hhi_mediano=("hhi_identificadores", "median"),
        )
    )


def resumen_turnover(turnover: pd.DataFrame) -> pd.DataFrame:
    if turnover.empty:
        return pd.DataFrame()

    consecutivo = turnover[
        turnover["comparacion_consecutiva"]
    ]

    return (
        consecutivo.groupby(
            ["escenario", "afp"],
            as_index=False,
        )
        .agg(
            comparaciones_consecutivas=(
                "periodo_actual",
                "size",
            ),
            turnover_mediano=(
                "turnover_mensual",
                "median",
            ),
            turnover_p90=(
                "turnover_mensual",
                lambda s: float(
                    pd.Series(s).dropna().quantile(0.90)
                ),
            ),
            solapamiento_mediano=(
                "solapamiento_pesos",
                "median",
            ),
            nuevos_mediano=(
                "identificadores_nuevos",
                "median",
            ),
            salientes_mediano=(
                "identificadores_salientes",
                "median",
            ),
        )
    )


def main() -> None:
    raiz = Path(__file__).resolve().parents[1]
    processed = raiz / "data" / "processed"

    base = preparar_base(
        leer_csv(
            processed
            / "ca0001_fondo3_hoja10_base_canonica_reconciliada.csv",
            ["fecha_cartera"],
        )
    )

    escenarios = construir_escenarios(base)

    features = construir_features(escenarios)
    control_pesos = construir_control_pesos(features)
    turnover = construir_turnover(escenarios)
    secuencias = construir_secuencias(escenarios)
    persistencia = construir_persistencia(escenarios)
    alertas = construir_alertas(features, turnover)
    cobertura = resumen_cobertura(features)
    turnover_resumen = resumen_turnover(turnover)

    rutas = {
        "features": (
            processed
            / "ca0001_fondo3_features_mensuales_identificadores.csv"
        ),
        "control_pesos": (
            processed
            / "ca0001_fondo3_control_suma_pesos.csv"
        ),
        "turnover": (
            processed
            / "ca0001_fondo3_turnover_identificadores.csv"
        ),
        "secuencias": (
            processed
            / "ca0001_fondo3_secuencias_elegibles.csv"
        ),
        "persistencia": (
            processed
            / "ca0001_fondo3_persistencia_identificadores.csv"
        ),
        "alertas": (
            processed
            / "ca0001_fondo3_alertas_estabilidad_identificadores.csv"
        ),
        "cobertura": (
            processed
            / "ca0001_fondo3_resumen_cobertura_features.csv"
        ),
        "turnover_resumen": (
            processed
            / "ca0001_fondo3_resumen_turnover.csv"
        ),
    }

    features.to_csv(
        rutas["features"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    control_pesos.to_csv(
        rutas["control_pesos"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    turnover.to_csv(
        rutas["turnover"],
        index=False,
        encoding="utf-8-sig",
    )
    secuencias.to_csv(
        rutas["secuencias"],
        index=False,
        encoding="utf-8-sig",
    )
    persistencia.to_csv(
        rutas["persistencia"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    alertas.to_csv(
        rutas["alertas"],
        index=False,
        encoding="utf-8-sig",
    )
    cobertura.to_csv(
        rutas["cobertura"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    turnover_resumen.to_csv(
        rutas["turnover_resumen"],
        index=False,
        encoding="utf-8-sig",
    )

    print("\nAUDITORÍA DE ESTABILIDAD DE IDENTIFICADORES TERMINADA")
    print("=" * 118)

    print("\nRESUMEN DE COBERTURA Y CONCENTRACIÓN")
    print("-" * 118)
    print(cobertura.to_string(index=False))

    print("\nCONTROL DE SUMA DE PESOS")
    print("-" * 118)
    print(
        control_pesos.groupby(
            [
                "escenario",
                "estado_suma_exterior",
                "estado_suma_total_fondo",
            ],
            as_index=False,
        )
        .size()
        .rename(columns={"size": "observaciones"})
        .to_string(index=False)
    )

    print("\nRESUMEN DE TURNOVER")
    print("-" * 118)
    if turnover_resumen.empty:
        print("No se generaron comparaciones consecutivas.")
    else:
        print(turnover_resumen.to_string(index=False))

    print("\nSECUENCIAS ELEGIBLES MÁS LARGAS")
    print("-" * 118)
    print(
        secuencias.groupby(
            ["escenario", "afp"],
            as_index=False,
        )
        .head(3)
        .to_string(index=False)
    )

    print("\nÚLTIMO MES DISPONIBLE POR AFP Y ESCENARIO")
    print("-" * 118)
    ultimos = (
        features.sort_values("fecha_cartera")
        .groupby(["escenario", "afp"], as_index=False)
        .tail(1)
    )
    print(
        ultimos[
            [
                "escenario",
                "periodo",
                "afp",
                "estado_cobertura",
                "numero_identificadores",
                "peso_isin_exterior",
                "peso_fondos_sin_isin_exterior",
                "peso_usd_exterior",
                "top5_exterior",
                "hhi_identificadores",
                "factor_reescala",
            ]
        ].to_string(index=False)
    )

    print("\nALERTAS")
    print("-" * 118)
    if alertas.empty:
        print("No se generaron alertas con los umbrales definidos.")
    else:
        print(
            alertas.groupby(
                ["escenario", "tipo_alerta", "motivos"],
                as_index=False,
            )
            .size()
            .rename(columns={"size": "observaciones"})
            .sort_values(
                ["escenario", "observaciones"],
                ascending=[True, False],
            )
            .to_string(index=False)
        )

    print("\nArchivos creados:")
    for ruta in rutas.values():
        print(f" - {ruta.resolve()}")

    print(
        "\nCriterio de lectura:\n"
        "- La suma de pesos exteriores debe ser 1 en todos los periodos "
        "reconciliados.\n"
        "- El turnover se calcula como la mitad de la suma de cambios "
        "absolutos de los pesos; solo las comparaciones mensuales "
        "consecutivas deben interpretarse como rotación mensual.\n"
        "- Las secuencias continuas son más adecuadas para modelos "
        "temporales que observaciones aisladas separadas por meses "
        "excluidos.\n"
        "- Una concentración o rotación alta no implica error por sí sola; "
        "sirve para detectar cambios que deben contrastarse con el archivo "
        "original.\n"
        "- El siguiente enriquecimiento por país, sector e índice debe "
        "aplicarse primero al modelo principal y luego repetirse sobre la "
        "base ampliada como prueba de sensibilidad."
    )


if __name__ == "__main__":
    main()
