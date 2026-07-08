from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


ESCENARIOS = {
    "principal_5pct": "usar_modelo_principal",
    "ampliado_15pct": "usar_analisis_ampliado",
}

VARIANTES = {
    "alta": {"alta"},
    "alta_media": {"alta", "media"},
    "todos_mapeados": {"alta", "media", "baja"},
}

FACTORES_PUBLICOS = [
    "ACWI", "SPY", "QQQ", "EEM", "ILF", "EPU", "VGK", "EWJ",
    "MCHI", "XLK", "XLF", "XLE", "XLB", "XLI", "XLV", "XLY",
    "XLP", "GLD", "CPER", "COPX", "TLT", "LQD", "HYG",
]

COLUMNAS_CONTROL = [
    "PRIVATE_ALTERNATIVES",
    "RESIDUAL_NO_MAPEADO",
    "PESO_EXCLUIDO_POR_CONFIANZA",
]

DIAS_REZAGO_PUBLICACION = 45
DIAS_MAXIMOS_ANTIGUEDAD = 75
TOLERANCIA = 1e-8


def leer_csv(
    ruta: Path,
    fechas: list[str] | None = None,
) -> pd.DataFrame:
    if not ruta.exists():
        raise FileNotFoundError(f"No existe: {ruta}")

    return pd.read_csv(
        ruta,
        parse_dates=fechas or [],
    )


def limpiar_texto(serie: pd.Series) -> pd.Series:
    return (
        serie.fillna("")
        .astype(str)
        .str.strip()
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

    for columna in [
        "afp",
        "factor_proxy_mercado",
        "confianza_factor_proxy",
        "estado_cobertura",
        "identificador_agregacion",
    ]:
        if columna not in salida.columns:
            salida[columna] = ""
        salida[columna] = limpiar_texto(
            salida[columna]
        )

    for columna in [
        "peso_exterior_reconciliado",
        "peso_total_fondo_reconciliado",
        "error_cobertura_pct",
        "factor_reescala",
    ]:
        salida[columna] = pd.to_numeric(
            salida[columna],
            errors="coerce",
        )

    for columna in [
        "usar_modelo_principal",
        "usar_analisis_ampliado",
    ]:
        salida[columna] = convertir_booleano(
            salida[columna]
        )

    return salida


def expandir_escenarios(base: pd.DataFrame) -> pd.DataFrame:
    partes = []

    for escenario, columna in ESCENARIOS.items():
        bloque = base[
            base[columna]
        ].copy()
        bloque["escenario"] = escenario
        partes.append(bloque)

    if not partes:
        return pd.DataFrame()

    return pd.concat(
        partes,
        ignore_index=True,
        sort=False,
    )


def asignar_factor_variante(
    fila: pd.Series,
    confianzas_incluidas: set[str],
) -> str:
    factor = fila["factor_proxy_mercado"]
    confianza = fila["confianza_factor_proxy"]

    if factor == "PRIVATE_ALTERNATIVES":
        return "PRIVATE_ALTERNATIVES"

    if factor == "RESIDUAL_NO_MAPEADO":
        return "RESIDUAL_NO_MAPEADO"

    if factor not in FACTORES_PUBLICOS:
        return "RESIDUAL_NO_MAPEADO"

    if confianza in confianzas_incluidas:
        return factor

    return "PESO_EXCLUIDO_POR_CONFIANZA"


def construir_largo(
    escenarios: pd.DataFrame,
) -> pd.DataFrame:
    partes = []

    for variante, confianzas in VARIANTES.items():
        bloque = escenarios.copy()
        bloque["variante_confianza"] = variante
        bloque["factor_modelo"] = bloque.apply(
            lambda fila: asignar_factor_variante(
                fila,
                confianzas,
            ),
            axis=1,
        )
        partes.append(bloque)

    expandido = pd.concat(
        partes,
        ignore_index=True,
        sort=False,
    )

    largo = (
        expandido.groupby(
            [
                "escenario",
                "variante_confianza",
                "periodo",
                "fecha_cartera",
                "afp",
                "factor_modelo",
            ],
            as_index=False,
        )
        .agg(
            peso_exterior=(
                "peso_exterior_reconciliado",
                "sum",
            ),
            peso_total_fondo=(
                "peso_total_fondo_reconciliado",
                "sum",
            ),
            identificadores=(
                "identificador_agregacion",
                "nunique",
            ),
            error_cobertura_pct=(
                "error_cobertura_pct",
                "first",
            ),
            factor_reescala=(
                "factor_reescala",
                "first",
            ),
            estado_cobertura=(
                "estado_cobertura",
                "first",
            ),
        )
    )

    largo["peso_exterior_pct"] = (
        largo["peso_exterior"] * 100.0
    )
    largo["peso_total_fondo_pct"] = (
        largo["peso_total_fondo"] * 100.0
    )

    return largo


def construir_ancho(largo: pd.DataFrame) -> pd.DataFrame:
    claves = [
        "escenario",
        "variante_confianza",
        "periodo",
        "fecha_cartera",
        "afp",
    ]

    ancho = (
        largo.pivot_table(
            index=claves,
            columns="factor_modelo",
            values="peso_total_fondo",
            aggfunc="sum",
            fill_value=0.0,
        )
        .reset_index()
    )
    ancho.columns.name = None

    for columna in FACTORES_PUBLICOS + COLUMNAS_CONTROL:
        if columna not in ancho.columns:
            ancho[columna] = 0.0

    metadatos = (
        largo.groupby(
            claves,
            as_index=False,
        )
        .agg(
            error_cobertura_pct=(
                "error_cobertura_pct",
                "first",
            ),
            factor_reescala=(
                "factor_reescala",
                "first",
            ),
            estado_cobertura=(
                "estado_cobertura",
                "first",
            ),
            peso_exterior_total=(
                "peso_exterior",
                "sum",
            ),
            peso_total_fondo_total=(
                "peso_total_fondo",
                "sum",
            ),
        )
    )

    ancho = ancho.merge(
        metadatos,
        on=claves,
        how="left",
        validate="one_to_one",
    )

    ancho["peso_publico_modelado"] = ancho[
        FACTORES_PUBLICOS
    ].sum(axis=1)
    ancho["peso_no_publico_o_no_mapeado"] = (
        ancho["PRIVATE_ALTERNATIVES"]
        + ancho["RESIDUAL_NO_MAPEADO"]
    )
    ancho["peso_excluido_confianza"] = ancho[
        "PESO_EXCLUIDO_POR_CONFIANZA"
    ]
    ancho["peso_total_reconstruido"] = (
        ancho["peso_publico_modelado"]
        + ancho["peso_no_publico_o_no_mapeado"]
        + ancho["peso_excluido_confianza"]
    )
    ancho["diferencia_control"] = (
        ancho["peso_total_reconstruido"]
        - ancho["peso_total_fondo_total"]
    )
    ancho["estado_control"] = np.where(
        ancho["diferencia_control"].abs()
        <= TOLERANCIA,
        "correcto",
        "revisar",
    )

    return ancho[
        claves
        + [
            "estado_cobertura",
            "error_cobertura_pct",
            "factor_reescala",
            "peso_exterior_total",
            "peso_total_fondo_total",
            "peso_publico_modelado",
            "peso_no_publico_o_no_mapeado",
            "peso_excluido_confianza",
        ]
        + FACTORES_PUBLICOS
        + COLUMNAS_CONTROL
        + [
            "peso_total_reconstruido",
            "diferencia_control",
            "estado_control",
        ]
    ]


def construir_ventanas(ancho: pd.DataFrame) -> pd.DataFrame:
    filas = []

    grupos = ancho.groupby(
        [
            "escenario",
            "variante_confianza",
            "afp",
        ],
        sort=True,
    )

    for _, grupo in grupos:
        grupo = grupo.sort_values(
            "fecha_cartera"
        ).copy()

        grupo["fecha_disponible"] = (
            grupo["fecha_cartera"]
            + pd.to_timedelta(
                DIAS_REZAGO_PUBLICACION,
                unit="D",
            )
        )
        grupo["siguiente_fecha_disponible"] = (
            grupo["fecha_disponible"].shift(-1)
        )
        grupo["fecha_fin_por_antiguedad"] = (
            grupo["fecha_cartera"]
            + pd.to_timedelta(
                DIAS_MAXIMOS_ANTIGUEDAD,
                unit="D",
            )
        )

        fin_siguiente = (
            grupo["siguiente_fecha_disponible"]
            - pd.Timedelta(days=1)
        )

        grupo["fecha_fin_validez"] = grupo[
            "fecha_fin_por_antiguedad"
        ]

        mascara = (
            fin_siguiente.notna()
            & (
                fin_siguiente
                < grupo["fecha_fin_validez"]
            )
        )
        grupo.loc[
            mascara,
            "fecha_fin_validez",
        ] = fin_siguiente[mascara]

        grupo["dias_ventana"] = (
            grupo["fecha_fin_validez"]
            - grupo["fecha_disponible"]
        ).dt.days + 1

        grupo["ventana_utilizable"] = (
            grupo["dias_ventana"] > 0
        )

        filas.append(grupo)

    return pd.concat(
        filas,
        ignore_index=True,
        sort=False,
    )


def construir_resumen(ancho: pd.DataFrame) -> pd.DataFrame:
    resumen = (
        ancho.groupby(
            [
                "escenario",
                "variante_confianza",
                "afp",
            ],
            as_index=False,
        )
        .agg(
            observaciones=("periodo", "size"),
            periodos=("periodo", "nunique"),
            primera_fecha=(
                "fecha_cartera",
                "min",
            ),
            ultima_fecha=(
                "fecha_cartera",
                "max",
            ),
            peso_publico_mediano=(
                "peso_publico_modelado",
                "median",
            ),
            peso_publico_p10=(
                "peso_publico_modelado",
                lambda s: float(
                    pd.Series(s)
                    .dropna()
                    .quantile(0.10)
                ),
            ),
            peso_publico_p90=(
                "peso_publico_modelado",
                lambda s: float(
                    pd.Series(s)
                    .dropna()
                    .quantile(0.90)
                ),
            ),
            peso_privado_mediano=(
                "PRIVATE_ALTERNATIVES",
                "median",
            ),
            peso_residual_mediano=(
                "RESIDUAL_NO_MAPEADO",
                "median",
            ),
            peso_excluido_mediano=(
                "PESO_EXCLUIDO_POR_CONFIANZA",
                "median",
            ),
            error_cobertura_mediano_pct=(
                "error_cobertura_pct",
                "median",
            ),
        )
    )

    for columna in [
        "peso_publico_mediano",
        "peso_publico_p10",
        "peso_publico_p90",
        "peso_privado_mediano",
        "peso_residual_mediano",
        "peso_excluido_mediano",
    ]:
        resumen[f"{columna}_pct"] = (
            resumen[columna] * 100.0
        )

    return resumen


def construir_turnover_factores(
    ancho: pd.DataFrame,
) -> pd.DataFrame:
    filas = []

    columnas = (
        FACTORES_PUBLICOS
        + COLUMNAS_CONTROL
    )

    for claves, grupo in ancho.groupby(
        [
            "escenario",
            "variante_confianza",
            "afp",
        ],
        sort=True,
    ):
        grupo = grupo.sort_values(
            "fecha_cartera"
        ).copy()

        for i in range(1, len(grupo)):
            anterior = grupo.iloc[i - 1]
            actual = grupo.iloc[i]

            salto_meses = (
                pd.Period(
                    actual["periodo"],
                    freq="M",
                ).ordinal
                - pd.Period(
                    anterior["periodo"],
                    freq="M",
                ).ordinal
            )

            turnover = 0.5 * float(
                np.abs(
                    actual[columnas].to_numpy(dtype=float)
                    - anterior[columnas].to_numpy(dtype=float)
                ).sum()
            )

            filas.append(
                {
                    "escenario": claves[0],
                    "variante_confianza": claves[1],
                    "afp": claves[2],
                    "periodo_anterior": anterior["periodo"],
                    "periodo_actual": actual["periodo"],
                    "salto_meses": salto_meses,
                    "comparacion_consecutiva": (
                        salto_meses == 1
                    ),
                    "turnover_factores": turnover,
                }
            )

    return pd.DataFrame(filas)


def main() -> None:
    raiz = Path(__file__).resolve().parents[1]
    processed = raiz / "data" / "processed"

    base = preparar_base(
        leer_csv(
            processed
            / "ca0001_base_identificadores_taxonomia_refinada.csv",
            ["fecha_cartera"],
        )
    )

    escenarios = expandir_escenarios(base)
    largo = construir_largo(escenarios)
    ancho = construir_ancho(largo)
    ventanas = construir_ventanas(ancho)
    resumen = construir_resumen(ancho)
    turnover = construir_turnover_factores(ancho)

    control = (
        ancho.groupby(
            "estado_control",
            as_index=False,
        )
        .size()
        .rename(
            columns={"size": "observaciones"}
        )
    )

    resumen_ventanas = (
        ventanas.groupby(
            [
                "escenario",
                "variante_confianza",
                "afp",
            ],
            as_index=False,
        )
        .agg(
            ventanas_totales=(
                "periodo",
                "size",
            ),
            ventanas_utilizables=(
                "ventana_utilizable",
                "sum",
            ),
            dias_utilizables=(
                "dias_ventana",
                lambda s: int(
                    pd.Series(s)
                    .clip(lower=0)
                    .sum()
                ),
            ),
            primera_disponibilidad=(
                "fecha_disponible",
                "min",
            ),
            ultima_fecha_fin=(
                "fecha_fin_validez",
                "max",
            ),
        )
    )

    rutas = {
        "largo": (
            processed
            / "ca0001_proxy_exposiciones_mensuales_largo.csv"
        ),
        "ancho": (
            processed
            / "ca0001_proxy_exposiciones_mensuales_ancho.csv"
        ),
        "ventanas": (
            processed
            / "ca0001_proxy_ventanas_publicacion_45d.csv"
        ),
        "resumen": (
            processed
            / "ca0001_proxy_resumen_cobertura_variantes.csv"
        ),
        "turnover": (
            processed
            / "ca0001_proxy_turnover_factores.csv"
        ),
        "control": (
            processed
            / "ca0001_proxy_control_pesos.csv"
        ),
        "resumen_ventanas": (
            processed
            / "ca0001_proxy_resumen_ventanas.csv"
        ),
    }

    largo.to_csv(
        rutas["largo"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    ancho.to_csv(
        rutas["ancho"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    ventanas.to_csv(
        rutas["ventanas"],
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
    turnover.to_csv(
        rutas["turnover"],
        index=False,
        encoding="utf-8-sig",
    )
    control.to_csv(
        rutas["control"],
        index=False,
        encoding="utf-8-sig",
    )
    resumen_ventanas.to_csv(
        rutas["resumen_ventanas"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )

    print(
        "\nPREPARACIÓN DE EXPOSICIONES PUBLICABLES TERMINADA"
    )
    print("=" * 120)

    print("\nRESUMEN DE COBERTURA POR VARIANTE")
    print("-" * 120)
    print(
        resumen[
            [
                "escenario",
                "variante_confianza",
                "afp",
                "periodos",
                "primera_fecha",
                "ultima_fecha",
                "peso_publico_mediano_pct",
                "peso_publico_p10_pct",
                "peso_publico_p90_pct",
                "peso_privado_mediano_pct",
                "peso_residual_mediano_pct",
                "peso_excluido_mediano_pct",
                "error_cobertura_mediano_pct",
            ]
        ].to_string(index=False)
    )

    print("\nVENTANAS UTILIZABLES CON REZAGO DE 45 DÍAS")
    print("-" * 120)
    print(
        resumen_ventanas.to_string(index=False)
    )

    print("\nCONTROL DE PESOS")
    print("-" * 120)
    print(control.to_string(index=False))

    print("\nTURNOVER DE FACTORES")
    print("-" * 120)

    if turnover.empty:
        print("No se generaron comparaciones.")
    else:
        print(
            turnover[
                turnover[
                    "comparacion_consecutiva"
                ]
            ]
            .groupby(
                [
                    "escenario",
                    "variante_confianza",
                    "afp",
                ],
                as_index=False,
            )
            .agg(
                comparaciones=(
                    "periodo_actual",
                    "size",
                ),
                turnover_mediano=(
                    "turnover_factores",
                    "median",
                ),
                turnover_p90=(
                    "turnover_factores",
                    lambda s: float(
                        pd.Series(s)
                        .dropna()
                        .quantile(0.90)
                    ),
                ),
            )
            .to_string(index=False)
        )

    print("\nÚLTIMAS EXPOSICIONES DISPONIBLES")
    print("-" * 120)

    ultimas = (
        ventanas.sort_values(
            "fecha_cartera"
        )
        .groupby(
            [
                "escenario",
                "variante_confianza",
                "afp",
            ],
            as_index=False,
        )
        .tail(1)
    )

    print(
        ultimas[
            [
                "escenario",
                "variante_confianza",
                "afp",
                "periodo",
                "fecha_disponible",
                "fecha_fin_validez",
                "ventana_utilizable",
                "peso_publico_modelado",
                "PRIVATE_ALTERNATIVES",
                "RESIDUAL_NO_MAPEADO",
                "PESO_EXCLUIDO_POR_CONFIANZA",
            ]
        ].to_string(index=False)
    )

    print("\nArchivos creados:")
    for ruta in rutas.values():
        print(f" - {ruta.resolve()}")

    print(
        "\nCriterio metodológico:\n"
        "- Se preparan tres variantes: solo proxies de confianza alta, "
        "alta+media y todos los proxies mapeados.\n"
        "- Los pesos corresponden al Fondo 3 completo, no solo a la "
        "cartera exterior.\n"
        "- PRIVATE_ALTERNATIVES y RESIDUAL_NO_MAPEADO permanecen como "
        "controles separados; no se fuerzan a un índice público.\n"
        "- Cada cartera mensual se considera observable 45 días después "
        "de su fecha y deja de utilizarse cuando supera 75 días de "
        "antigüedad.\n"
        "- Esta convención evita usar información futura y también evita "
        "arrastrar durante muchos meses una cartera antigua.\n"
        "- El módulo siguiente debe comparar las tres variantes mediante "
        "evaluación temporal fuera de muestra y placebos."
    )


if __name__ == "__main__":
    main()
