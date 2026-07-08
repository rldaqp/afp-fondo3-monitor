from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


AFPS = ["Habitat", "Integra", "Prima", "Profuturo"]

CATEGORIAS_TOTAL_EXTERIOR = [
    "fondos_mutuos_exterior",
    "alternativos_exterior",
    "etf_exterior_via_mercado_local",
    "acciones_exterior_directas",
    "fondos_inversion_exterior",
    "depositos_exterior",
    "renta_fija_financiera_exterior",
    "renta_fija_no_financiera_exterior",
    "renta_fija_organismos_internacionales",
    "renta_fija_soberana_exterior",
    "renta_fija_exterior_otros",
]

ESTADOS_HOJA = {
    "isin",
    "fondo_sin_isin_pareja_exacta",
}

UMBRAL_ESTRICTO_PCT = 2.0
UMBRAL_OPERATIVO_PCT = 5.0
UMBRAL_AMPLIADO_PCT = 15.0


def leer_csv(ruta: Path, fecha: str | None = None) -> pd.DataFrame:
    if not ruta.exists():
        raise FileNotFoundError(f"No existe: {ruta}")

    return pd.read_csv(
        ruta,
        parse_dates=[fecha] if fecha else [],
    )


def limpiar_texto(serie: pd.Series) -> pd.Series:
    return (
        serie.fillna("")
        .astype(str)
        .str.strip()
        .replace("nan", "")
    )


def preparar_hoja10(df: pd.DataFrame) -> pd.DataFrame:
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
    salida["valor"] = pd.to_numeric(
        salida["valor"],
        errors="coerce",
    ).fillna(0.0)
    salida["fila_excel_aprox"] = pd.to_numeric(
        salida["fila_excel_aprox"],
        errors="coerce",
    ).astype("Int64")

    for columna in [
        "afp",
        "estado_refinado",
        "entidad_administradora",
        "isin",
        "instrumento_sin_isin",
        "moneda",
    ]:
        if columna not in salida.columns:
            salida[columna] = ""
        salida[columna] = limpiar_texto(salida[columna])

    salida["identificador_final"] = np.where(
        salida["isin"].str.len() > 0,
        salida["isin"],
        np.where(
            salida["instrumento_sin_isin"].str.len() > 0,
            salida["instrumento_sin_isin"],
            salida["entidad_administradora"],
        ),
    )

    salida["tipo_identificador"] = np.where(
        salida["isin"].str.len() > 0,
        "isin",
        "fondo_sin_isin",
    )

    salida["valor_redondeado"] = salida["valor"].round(6)

    return salida


def seleccionar_hojas_canonicas(
    df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    hojas = df[
        df["estado_refinado"].isin(ESTADOS_HOJA)
    ].copy()

    entidades_control = df[
        ~df["estado_refinado"].isin(ESTADOS_HOJA)
    ].copy()

    clave_dedup = [
        "periodo",
        "afp",
        "identificador_final",
        "valor_redondeado",
    ]

    hojas = (
        hojas.sort_values(
            clave_dedup + ["fila_excel_aprox"]
        )
        .drop_duplicates(
            subset=clave_dedup,
            keep="first",
        )
        .copy()
    )

    return hojas, entidades_control


def preparar_fp1356(
    fp: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    salida = fp.copy()

    salida["fecha_cartera"] = pd.to_datetime(
        salida["fecha_cartera"],
        errors="coerce",
    )
    salida["periodo"] = (
        salida["fecha_cartera"]
        .dt.to_period("M")
        .astype(str)
    )
    salida["monto_miles_soles"] = pd.to_numeric(
        salida["monto_miles_soles"],
        errors="coerce",
    )
    salida["participacion_pct"] = pd.to_numeric(
        salida["participacion_pct"],
        errors="coerce",
    )

    total_fondo = (
        salida.groupby(
            ["periodo", "afp"],
            as_index=False,
        )
        .agg(
            total_fondo_miles_soles=(
                "monto_miles_soles",
                "sum",
            ),
        )
    )

    total_exterior = (
        salida[
            salida["categoria_economica"].isin(
                CATEGORIAS_TOTAL_EXTERIOR
            )
        ]
        .groupby(
            ["periodo", "afp"],
            as_index=False,
        )
        .agg(
            total_exterior_miles_soles=(
                "monto_miles_soles",
                "sum",
            ),
            total_exterior_pct_fp1356=(
                "participacion_pct",
                "sum",
            ),
        )
    )

    return total_fondo, total_exterior


def construir_control_periodos(
    hojas: pd.DataFrame,
    total_fondo: pd.DataFrame,
    total_exterior: pd.DataFrame,
) -> pd.DataFrame:
    resumen = (
        hojas.groupby(
            ["periodo", "afp"],
            as_index=False,
        )
        .agg(
            fecha_ca=("fecha_cartera", "max"),
            monto_hojas_miles_soles=("valor", "sum"),
            registros_hojas=("valor", "size"),
            identificadores_unicos=(
                "identificador_final",
                "nunique",
            ),
            registros_isin=(
                "tipo_identificador",
                lambda s: int((s == "isin").sum()),
            ),
            registros_fondo_sin_isin=(
                "tipo_identificador",
                lambda s: int(
                    (s == "fondo_sin_isin").sum()
                ),
            ),
        )
        .merge(
            total_fondo,
            on=["periodo", "afp"],
            how="inner",
            validate="one_to_one",
        )
        .merge(
            total_exterior,
            on=["periodo", "afp"],
            how="inner",
            validate="one_to_one",
        )
    )

    resumen["ratio_cobertura_exterior"] = np.where(
        resumen["total_exterior_miles_soles"].abs() > 0,
        resumen["monto_hojas_miles_soles"]
        / resumen["total_exterior_miles_soles"],
        np.nan,
    )
    resumen["error_cobertura_pct"] = (
        resumen["ratio_cobertura_exterior"] - 1.0
    ).abs() * 100.0

    resumen["factor_reescala"] = np.where(
        resumen["monto_hojas_miles_soles"].abs() > 0,
        resumen["total_exterior_miles_soles"]
        / resumen["monto_hojas_miles_soles"],
        np.nan,
    )

    resumen["estado_cobertura"] = np.select(
        [
            resumen["error_cobertura_pct"]
            <= UMBRAL_ESTRICTO_PCT,
            resumen["error_cobertura_pct"]
            <= UMBRAL_OPERATIVO_PCT,
            resumen["error_cobertura_pct"]
            <= UMBRAL_AMPLIADO_PCT,
        ],
        [
            "estricto",
            "operativo",
            "ampliado",
        ],
        default="excluir",
    )

    resumen["elegible_modelo_principal"] = (
        resumen["estado_cobertura"].isin(
            ["estricto", "operativo"]
        )
    )
    resumen["elegible_analisis_ampliado"] = (
        resumen["estado_cobertura"].isin(
            ["estricto", "operativo", "ampliado"]
        )
    )

    resumen["cobertura_exterior_pct"] = (
        resumen["ratio_cobertura_exterior"] * 100.0
    )
    resumen["exterior_sobre_fondo_pct"] = np.where(
        resumen["total_fondo_miles_soles"].abs() > 0,
        resumen["total_exterior_miles_soles"]
        / resumen["total_fondo_miles_soles"]
        * 100.0,
        np.nan,
    )

    return resumen


def construir_base_final(
    hojas: pd.DataFrame,
    control: pd.DataFrame,
) -> pd.DataFrame:
    columnas_control = [
        "periodo",
        "afp",
        "monto_hojas_miles_soles",
        "total_exterior_miles_soles",
        "total_fondo_miles_soles",
        "ratio_cobertura_exterior",
        "error_cobertura_pct",
        "factor_reescala",
        "estado_cobertura",
        "elegible_modelo_principal",
        "elegible_analisis_ampliado",
    ]

    base = hojas.merge(
        control[columnas_control],
        on=["periodo", "afp"],
        how="inner",
        validate="many_to_one",
    )

    base["peso_dentro_hojas"] = np.where(
        base["monto_hojas_miles_soles"].abs() > 0,
        base["valor"]
        / base["monto_hojas_miles_soles"],
        np.nan,
    )

    base["valor_reconciliado_miles_soles"] = (
        base["valor"] * base["factor_reescala"]
    )

    base["peso_exterior_reconciliado"] = np.where(
        base["total_exterior_miles_soles"].abs() > 0,
        base["valor_reconciliado_miles_soles"]
        / base["total_exterior_miles_soles"],
        np.nan,
    )

    base["peso_total_fondo_reconciliado"] = np.where(
        base["total_fondo_miles_soles"].abs() > 0,
        base["valor_reconciliado_miles_soles"]
        / base["total_fondo_miles_soles"],
        np.nan,
    )

    base["peso_exterior_reconciliado_pct"] = (
        base["peso_exterior_reconciliado"] * 100.0
    )
    base["peso_total_fondo_reconciliado_pct"] = (
        base["peso_total_fondo_reconciliado"] * 100.0
    )

    base["usar_modelo_principal"] = (
        base["elegible_modelo_principal"]
    )
    base["usar_analisis_ampliado"] = (
        base["elegible_analisis_ampliado"]
    )

    return base


def resumen_cobertura(
    control: pd.DataFrame,
) -> pd.DataFrame:
    general = (
        control.groupby(
            ["afp", "estado_cobertura"],
            as_index=False,
        )
        .agg(
            observaciones=("periodo", "size"),
            periodos_unicos=("periodo", "nunique"),
            ratio_mediano=(
                "ratio_cobertura_exterior",
                "median",
            ),
            error_mediano_pct=(
                "error_cobertura_pct",
                "median",
            ),
            error_p90_pct=(
                "error_cobertura_pct",
                lambda s: float(
                    pd.Series(s).dropna().quantile(0.90)
                ),
            ),
        )
    )

    totales = (
        control.groupby("afp", as_index=False)
        .agg(
            observaciones_totales=("periodo", "size"),
        )
    )

    general = general.merge(
        totales,
        on="afp",
        how="left",
        validate="many_to_one",
    )
    general["participacion_estado_pct"] = (
        general["observaciones"]
        / general["observaciones_totales"]
        * 100.0
    )

    return general.sort_values(
        ["afp", "estado_cobertura"]
    )


def resumen_general(
    control: pd.DataFrame,
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "observaciones_periodo_afp": len(control),
                "periodos_unicos": control["periodo"].nunique(),
                "afp": control["afp"].nunique(),
                "ratio_mediano": (
                    control["ratio_cobertura_exterior"].median()
                ),
                "error_mediano_pct": (
                    control["error_cobertura_pct"].median()
                ),
                "error_p90_pct": (
                    control["error_cobertura_pct"].quantile(0.90)
                ),
                "elegibles_modelo_principal": int(
                    control[
                        "elegible_modelo_principal"
                    ].sum()
                ),
                "elegibles_modelo_principal_pct": float(
                    control[
                        "elegible_modelo_principal"
                    ].mean()
                    * 100.0
                ),
                "elegibles_analisis_ampliado": int(
                    control[
                        "elegible_analisis_ampliado"
                    ].sum()
                ),
                "elegibles_analisis_ampliado_pct": float(
                    control[
                        "elegible_analisis_ampliado"
                    ].mean()
                    * 100.0
                ),
                "excluidos": int(
                    (
                        control["estado_cobertura"]
                        == "excluir"
                    ).sum()
                ),
            }
        ]
    )


def top_ultimo_mes(
    base: pd.DataFrame,
) -> pd.DataFrame:
    ultima_fecha = base["fecha_cartera"].max()

    top = base[
        base["fecha_cartera"] == ultima_fecha
    ].copy()

    top = top.sort_values(
        [
            "afp",
            "peso_exterior_reconciliado_pct",
        ],
        ascending=[True, False],
    )
    top["ranking_afp"] = (
        top.groupby("afp")
        .cumcount()
        .add(1)
    )

    return top[
        top["ranking_afp"] <= 20
    ].copy()


def catalogo_identificadores(
    base: pd.DataFrame,
) -> pd.DataFrame:
    return (
        base.groupby(
            [
                "afp",
                "identificador_final",
                "tipo_identificador",
                "isin",
                "entidad_administradora",
                "moneda",
            ],
            dropna=False,
            as_index=False,
        )
        .agg(
            primera_fecha=("fecha_cartera", "min"),
            ultima_fecha=("fecha_cartera", "max"),
            meses_presentes=("periodo", "nunique"),
            valor_mediano_reconciliado=(
                "valor_reconciliado_miles_soles",
                "median",
            ),
            peso_mediano_total_fondo_pct=(
                "peso_total_fondo_reconciliado_pct",
                "median",
            ),
            peso_maximo_total_fondo_pct=(
                "peso_total_fondo_reconciliado_pct",
                "max",
            ),
        )
        .sort_values(
            [
                "afp",
                "peso_maximo_total_fondo_pct",
            ],
            ascending=[True, False],
        )
    )


def main() -> None:
    raiz = Path(__file__).resolve().parents[1]
    processed = raiz / "data" / "processed"

    hoja10 = preparar_hoja10(
        leer_csv(
            processed
            / "ca0001_fondo3_historico_hoja10_refinada.csv",
            "fecha_cartera",
        )
    )
    fp = leer_csv(
        processed
        / "fp1356_cartera_economica_mensual_v2.csv",
        "fecha_cartera",
    )

    hojas, entidades_control = seleccionar_hojas_canonicas(
        hoja10
    )
    total_fondo, total_exterior = preparar_fp1356(fp)

    control = construir_control_periodos(
        hojas,
        total_fondo,
        total_exterior,
    )
    base_final = construir_base_final(
        hojas,
        control,
    )

    resumen_estados = resumen_cobertura(control)
    resumen = resumen_general(control)
    top = top_ultimo_mes(base_final)
    catalogo = catalogo_identificadores(base_final)

    base_principal = base_final[
        base_final["usar_modelo_principal"]
    ].copy()
    base_ampliada = base_final[
        base_final["usar_analisis_ampliado"]
    ].copy()

    rutas = {
        "base_final": (
            processed
            / "ca0001_fondo3_hoja10_base_canonica_reconciliada.csv"
        ),
        "base_principal": (
            processed
            / "ca0001_fondo3_hoja10_base_modelo_principal.csv"
        ),
        "base_ampliada": (
            processed
            / "ca0001_fondo3_hoja10_base_analisis_ampliado.csv"
        ),
        "control": (
            processed
            / "ca0001_fondo3_hoja10_control_cobertura.csv"
        ),
        "resumen_estados": (
            processed
            / "ca0001_fondo3_hoja10_resumen_estados_cobertura.csv"
        ),
        "resumen": (
            processed
            / "ca0001_fondo3_hoja10_resumen_final.csv"
        ),
        "entidades_control": (
            processed
            / "ca0001_fondo3_hoja10_entidades_control_no_sumables.csv"
        ),
        "top": (
            processed
            / "ca0001_fondo3_hoja10_top_ultimo_mes_reconciliado.csv"
        ),
        "catalogo": (
            processed
            / "ca0001_fondo3_hoja10_catalogo_identificadores.csv"
        ),
    }

    base_final.to_csv(
        rutas["base_final"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    base_principal.to_csv(
        rutas["base_principal"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    base_ampliada.to_csv(
        rutas["base_ampliada"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    control.to_csv(
        rutas["control"],
        index=False,
        encoding="utf-8-sig",
    )
    resumen_estados.to_csv(
        rutas["resumen_estados"],
        index=False,
        encoding="utf-8-sig",
    )
    resumen.to_csv(
        rutas["resumen"],
        index=False,
        encoding="utf-8-sig",
    )
    entidades_control.to_csv(
        rutas["entidades_control"],
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
    catalogo.to_csv(
        rutas["catalogo"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )

    print("\nCONSTRUCCIÓN DE BASE CANÓNICA DE HOJA 10 TERMINADA")
    print("=" * 118)

    print("\nRESUMEN GENERAL")
    print("-" * 118)
    print(resumen.to_string(index=False))

    print("\nESTADOS DE COBERTURA POR AFP")
    print("-" * 118)
    print(resumen_estados.to_string(index=False))

    print("\nCONTROL GENERAL DE COBERTURA")
    print("-" * 118)
    print(
        control[
            [
                "periodo",
                "afp",
                "monto_hojas_miles_soles",
                "total_exterior_miles_soles",
                "ratio_cobertura_exterior",
                "error_cobertura_pct",
                "factor_reescala",
                "estado_cobertura",
                "elegible_modelo_principal",
                "elegible_analisis_ampliado",
            ]
        ]
        .sort_values(
            ["periodo", "afp"]
        )
        .tail(24)
        .to_string(index=False)
    )

    print("\nTOP RECONCILIADO DEL ÚLTIMO MES")
    print("-" * 118)

    for afp in AFPS:
        tabla = top[top["afp"] == afp].head(12)

        if tabla.empty:
            continue

        print(f"\n{afp}")
        print(
            tabla[
                [
                    "ranking_afp",
                    "identificador_final",
                    "tipo_identificador",
                    "entidad_administradora",
                    "moneda",
                    "peso_exterior_reconciliado_pct",
                    "peso_total_fondo_reconciliado_pct",
                    "estado_cobertura",
                ]
            ].to_string(index=False)
        )

    print("\nArchivos creados:")
    for ruta in rutas.values():
        print(f" - {ruta.resolve()}")

    print(
        "\nCriterio metodológico final:\n"
        "- La capa sumable queda formada únicamente por ISIN y fondos "
        "específicos sin ISIN.\n"
        "- Las entidades pendientes se conservan como control y metadato, "
        "pero no se agregan como posiciones adicionales.\n"
        "- Se utiliza total_exterior como referencia fija para todas las "
        "AFP; no se selecciona un objetivo diferente por AFP para evitar "
        "sobreajuste.\n"
        "- Los valores reescalados solo distribuyen el total exterior entre "
        "los identificadores observados; no crean información nueva.\n"
        "- El modelo principal utiliza periodos con error de cobertura de "
        "hasta 5 %. El análisis ampliado admite hasta 15 % y debe incluir "
        "pruebas de sensibilidad.\n"
        "- La base permite estudiar exposiciones compatibles con los "
        "identificadores reportados, pero todavía no prueba causalidad sobre "
        "el rendimiento diario de la cuota."
    )


if __name__ == "__main__":
    main()
