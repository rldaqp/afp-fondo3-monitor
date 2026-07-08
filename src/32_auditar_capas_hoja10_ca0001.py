from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


OBJETIVOS_FP1356 = {
    "total_exterior": [
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
    ],
    "rv_y_fondos_exterior": [
        "fondos_mutuos_exterior",
        "alternativos_exterior",
        "etf_exterior_via_mercado_local",
        "acciones_exterior_directas",
        "fondos_inversion_exterior",
    ],
    "fondos_exterior_amplio": [
        "fondos_mutuos_exterior",
        "alternativos_exterior",
        "etf_exterior_via_mercado_local",
        "fondos_inversion_exterior",
    ],
    "administradoras_fondos_exterior": [
        "fondos_mutuos_exterior",
        "alternativos_exterior",
        "fondos_inversion_exterior",
    ],
    "fondos_mutuos_mas_etf": [
        "fondos_mutuos_exterior",
        "etf_exterior_via_mercado_local",
    ],
    "fondos_mutuos_exterior": [
        "fondos_mutuos_exterior",
    ],
}


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

    salida["tipo_capa"] = np.select(
        [
            salida["estado_refinado"].eq("isin"),
            salida["estado_refinado"].eq(
                "fondo_sin_isin_pareja_exacta"
            ),
            salida["estado_refinado"].eq(
                "entidad_sin_isin_pendiente"
            ),
        ],
        [
            "isin",
            "fondo_sin_isin",
            "entidad_pendiente",
        ],
        default="otro",
    )

    salida["valor_redondeado"] = salida["valor"].round(6)

    return salida


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

    total = (
        salida.groupby(
            ["periodo", "afp"],
            as_index=False,
        )
        .agg(
            total_fp_miles_soles=("monto_miles_soles", "sum"),
        )
    )

    objetivos = []

    for objetivo, categorias in OBJETIVOS_FP1356.items():
        bloque = (
            salida[
                salida["categoria_economica"].isin(categorias)
            ]
            .groupby(
                ["periodo", "afp"],
                as_index=False,
            )
            .agg(
                objetivo_monto_miles_soles=(
                    "monto_miles_soles",
                    "sum",
                ),
                objetivo_participacion_pct=(
                    "participacion_pct",
                    "sum",
                ),
            )
        )
        bloque["objetivo"] = objetivo
        objetivos.append(bloque)

    return total, pd.concat(objetivos, ignore_index=True)


def crear_escenarios(
    hoja10: pd.DataFrame,
) -> dict[str, pd.DataFrame]:
    hojas_identificadas = hoja10[
        hoja10["tipo_capa"].isin(
            ["isin", "fondo_sin_isin"]
        )
    ].copy()

    solo_isin = hoja10[
        hoja10["tipo_capa"].eq("isin")
    ].copy()

    solo_fondos_sin_isin = hoja10[
        hoja10["tipo_capa"].eq("fondo_sin_isin")
    ].copy()

    solo_entidades = hoja10[
        hoja10["tipo_capa"].eq("entidad_pendiente")
    ].copy()

    clave_dedup = [
        "periodo",
        "afp",
        "identificador_final",
        "valor_redondeado",
    ]

    hojas_identificadas_dedup = (
        hojas_identificadas.sort_values(
            [
                "periodo",
                "afp",
                "identificador_final",
                "valor_redondeado",
                "fila_excel_aprox",
            ]
        )
        .drop_duplicates(
            subset=clave_dedup,
            keep="first",
        )
        .copy()
    )

    solo_isin_dedup = (
        solo_isin.sort_values(
            [
                "periodo",
                "afp",
                "identificador_final",
                "valor_redondeado",
                "fila_excel_aprox",
            ]
        )
        .drop_duplicates(
            subset=clave_dedup,
            keep="first",
        )
        .copy()
    )

    entidades_dedup = (
        solo_entidades.sort_values(
            [
                "periodo",
                "afp",
                "identificador_final",
                "valor_redondeado",
                "fila_excel_aprox",
            ]
        )
        .drop_duplicates(
            subset=clave_dedup,
            keep="first",
        )
        .copy()
    )

    return {
        "todas_las_filas": hoja10,
        "solo_hojas_identificadas": hojas_identificadas,
        "hojas_identificadas_dedup_id_valor": (
            hojas_identificadas_dedup
        ),
        "solo_isin": solo_isin,
        "solo_isin_dedup_id_valor": solo_isin_dedup,
        "solo_fondos_sin_isin": solo_fondos_sin_isin,
        "solo_entidades_pendientes": solo_entidades,
        "entidades_pendientes_dedup_id_valor": entidades_dedup,
    }


def resumir_escenario(
    nombre: str,
    df: pd.DataFrame,
) -> pd.DataFrame:
    resumen = (
        df.groupby(
            ["periodo", "afp"],
            as_index=False,
        )
        .agg(
            monto_ca_miles_soles=("valor", "sum"),
            registros=("valor", "size"),
            identificadores_unicos=(
                "identificador_final",
                "nunique",
            ),
        )
    )
    resumen["escenario"] = nombre
    return resumen


def comparar_escenarios(
    escenarios: dict[str, pd.DataFrame],
    total_fp: pd.DataFrame,
    objetivos: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    comparaciones = []

    for nombre, df in escenarios.items():
        base = (
            resumir_escenario(nombre, df)
            .merge(
                total_fp,
                on=["periodo", "afp"],
                how="inner",
                validate="one_to_one",
            )
            .merge(
                objetivos,
                on=["periodo", "afp"],
                how="inner",
                validate="one_to_many",
            )
        )

        base["ratio_ca_objetivo"] = np.where(
            base["objetivo_monto_miles_soles"].abs() > 0,
            base["monto_ca_miles_soles"]
            / base["objetivo_monto_miles_soles"],
            np.nan,
        )
        base["error_abs_pct"] = (
            base["ratio_ca_objetivo"] - 1.0
        ).abs() * 100.0
        base["ratio_ca_total_fondo"] = np.where(
            base["total_fp_miles_soles"].abs() > 0,
            base["monto_ca_miles_soles"]
            / base["total_fp_miles_soles"],
            np.nan,
        )

        comparaciones.append(base)

    detalle = pd.concat(
        comparaciones,
        ignore_index=True,
    )

    ranking = (
        detalle.groupby(
            ["escenario", "objetivo"],
            as_index=False,
        )
        .agg(
            observaciones=("error_abs_pct", "count"),
            ratio_mediano=("ratio_ca_objetivo", "median"),
            ratio_p10=(
                "ratio_ca_objetivo",
                lambda s: float(
                    pd.Series(s).dropna().quantile(0.10)
                ),
            ),
            ratio_p90=(
                "ratio_ca_objetivo",
                lambda s: float(
                    pd.Series(s).dropna().quantile(0.90)
                ),
            ),
            error_mediano_pct=("error_abs_pct", "median"),
            error_p90_pct=(
                "error_abs_pct",
                lambda s: float(
                    pd.Series(s).dropna().quantile(0.90)
                ),
            ),
            dentro_1pct=(
                "error_abs_pct",
                lambda s: float(
                    (pd.Series(s).dropna() <= 1.0).mean()
                    * 100.0
                ),
            ),
            dentro_2pct=(
                "error_abs_pct",
                lambda s: float(
                    (pd.Series(s).dropna() <= 2.0).mean()
                    * 100.0
                ),
            ),
            registros_medianos=("registros", "median"),
            identificadores_medianos=(
                "identificadores_unicos",
                "median",
            ),
        )
        .sort_values(
            [
                "escenario",
                "error_mediano_pct",
                "error_p90_pct",
            ]
        )
    )

    ranking["ranking_escenario"] = (
        ranking.groupby("escenario")
        .cumcount()
        .add(1)
    )

    return detalle, ranking


def contribucion_por_capa(
    hoja10: pd.DataFrame,
    total_fp: pd.DataFrame,
    objetivos: pd.DataFrame,
) -> pd.DataFrame:
    total_exterior = objetivos[
        objetivos["objetivo"].eq("total_exterior")
    ][
        [
            "periodo",
            "afp",
            "objetivo_monto_miles_soles",
        ]
    ].rename(
        columns={
            "objetivo_monto_miles_soles": (
                "total_exterior_miles_soles"
            )
        }
    )

    capas = (
        hoja10.groupby(
            ["periodo", "afp", "tipo_capa"],
            as_index=False,
        )
        .agg(
            monto_capa_miles_soles=("valor", "sum"),
            registros=("valor", "size"),
            identificadores_unicos=(
                "identificador_final",
                "nunique",
            ),
        )
        .merge(
            total_fp,
            on=["periodo", "afp"],
            how="inner",
            validate="many_to_one",
        )
        .merge(
            total_exterior,
            on=["periodo", "afp"],
            how="inner",
            validate="many_to_one",
        )
    )

    capas["ratio_capa_total_exterior"] = np.where(
        capas["total_exterior_miles_soles"].abs() > 0,
        capas["monto_capa_miles_soles"]
        / capas["total_exterior_miles_soles"],
        np.nan,
    )
    capas["ratio_capa_total_fondo"] = np.where(
        capas["total_fp_miles_soles"].abs() > 0,
        capas["monto_capa_miles_soles"]
        / capas["total_fp_miles_soles"],
        np.nan,
    )

    return (
        capas.groupby("tipo_capa", as_index=False)
        .agg(
            observaciones=("ratio_capa_total_exterior", "count"),
            ratio_mediano_total_exterior=(
                "ratio_capa_total_exterior",
                "median",
            ),
            ratio_p10_total_exterior=(
                "ratio_capa_total_exterior",
                lambda s: float(
                    pd.Series(s).dropna().quantile(0.10)
                ),
            ),
            ratio_p90_total_exterior=(
                "ratio_capa_total_exterior",
                lambda s: float(
                    pd.Series(s).dropna().quantile(0.90)
                ),
            ),
            ratio_mediano_total_fondo=(
                "ratio_capa_total_fondo",
                "median",
            ),
            registros_medianos=("registros", "median"),
            identificadores_medianos=(
                "identificadores_unicos",
                "median",
            ),
        )
        .sort_values(
            "ratio_mediano_total_exterior",
            ascending=False,
        )
    )


def auditar_duplicados_identificador(
    hoja10: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    claves = [
        "periodo",
        "afp",
        "identificador_final",
        "valor_redondeado",
    ]

    grupos = (
        hoja10.groupby(
            claves,
            dropna=False,
            as_index=False,
        )
        .agg(
            ocurrencias=("valor", "size"),
            monto_una_ocurrencia=("valor", "first"),
            filas_excel=(
                "fila_excel_aprox",
                lambda s: " | ".join(
                    str(int(x))
                    for x in pd.Series(s).dropna().tolist()
                ),
            ),
            estados=(
                "estado_refinado",
                lambda s: " | ".join(
                    sorted(set(limpiar_texto(pd.Series(s))))
                ),
            ),
        )
    )

    duplicados = grupos[
        grupos["ocurrencias"] > 1
    ].copy()
    duplicados["monto_duplicado_excedente"] = (
        duplicados["monto_una_ocurrencia"]
        * (duplicados["ocurrencias"] - 1)
    )

    resumen = pd.DataFrame(
        [
            {
                "grupos_identificador_valor": len(grupos),
                "grupos_duplicados_exactos": len(duplicados),
                "ocurrencias_totales_duplicadas": int(
                    duplicados["ocurrencias"].sum()
                ),
                "filas_excedentes_por_duplicado": int(
                    (duplicados["ocurrencias"] - 1).sum()
                ),
                "monto_excedente_total_miles_soles": float(
                    duplicados[
                        "monto_duplicado_excedente"
                    ].sum()
                ),
            }
        ]
    )

    return duplicados, resumen


def mejores_por_afp(
    detalle: pd.DataFrame,
) -> pd.DataFrame:
    resumen = (
        detalle.groupby(
            ["afp", "escenario", "objetivo"],
            as_index=False,
        )
        .agg(
            observaciones=("error_abs_pct", "count"),
            ratio_mediano=("ratio_ca_objetivo", "median"),
            error_mediano_pct=("error_abs_pct", "median"),
            error_p90_pct=(
                "error_abs_pct",
                lambda s: float(
                    pd.Series(s).dropna().quantile(0.90)
                ),
            ),
        )
        .sort_values(
            [
                "afp",
                "error_mediano_pct",
                "error_p90_pct",
            ]
        )
    )

    resumen["ranking_afp"] = (
        resumen.groupby("afp")
        .cumcount()
        .add(1)
    )

    return resumen


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

    total_fp, objetivos = preparar_fp1356(fp)
    escenarios = crear_escenarios(hoja10)

    detalle, ranking = comparar_escenarios(
        escenarios,
        total_fp,
        objetivos,
    )
    capas = contribucion_por_capa(
        hoja10,
        total_fp,
        objetivos,
    )
    duplicados, resumen_duplicados = (
        auditar_duplicados_identificador(hoja10)
    )
    ranking_afp = mejores_por_afp(detalle)

    mejor_total_exterior = (
        ranking[
            ranking["objetivo"].eq("total_exterior")
        ]
        .sort_values(
            ["error_mediano_pct", "error_p90_pct"]
        )
        .reset_index(drop=True)
    )

    rutas = {
        "detalle": (
            processed
            / "ca0001_hoja10_auditoria_capas_detalle.csv"
        ),
        "ranking": (
            processed
            / "ca0001_hoja10_auditoria_capas_ranking.csv"
        ),
        "capas": (
            processed
            / "ca0001_hoja10_contribucion_por_capa.csv"
        ),
        "duplicados": (
            processed
            / "ca0001_hoja10_duplicados_identificador_valor.csv"
        ),
        "resumen_duplicados": (
            processed
            / "ca0001_hoja10_resumen_duplicados_identificador.csv"
        ),
        "ranking_afp": (
            processed
            / "ca0001_hoja10_auditoria_capas_ranking_por_afp.csv"
        ),
        "mejor_total_exterior": (
            processed
            / "ca0001_hoja10_mejor_escenario_total_exterior.csv"
        ),
    }

    detalle.to_csv(
        rutas["detalle"],
        index=False,
        encoding="utf-8-sig",
    )
    ranking.to_csv(
        rutas["ranking"],
        index=False,
        encoding="utf-8-sig",
    )
    capas.to_csv(
        rutas["capas"],
        index=False,
        encoding="utf-8-sig",
    )
    duplicados.to_csv(
        rutas["duplicados"],
        index=False,
        encoding="utf-8-sig",
    )
    resumen_duplicados.to_csv(
        rutas["resumen_duplicados"],
        index=False,
        encoding="utf-8-sig",
    )
    ranking_afp.to_csv(
        rutas["ranking_afp"],
        index=False,
        encoding="utf-8-sig",
    )
    mejor_total_exterior.to_csv(
        rutas["mejor_total_exterior"],
        index=False,
        encoding="utf-8-sig",
    )

    print("\nAUDITORÍA DE CAPAS PARA LA HOJA 10")
    print("=" * 118)

    print("\nCONTRIBUCIÓN POR TIPO DE CAPA")
    print("-" * 118)
    print(capas.to_string(index=False))

    print("\nRANKING DE ESCENARIOS CONTRA TOTAL_EXTERIOR")
    print("-" * 118)
    print(
        mejor_total_exterior[
            [
                "escenario",
                "observaciones",
                "ratio_mediano",
                "ratio_p10",
                "ratio_p90",
                "error_mediano_pct",
                "error_p90_pct",
                "dentro_1pct",
                "dentro_2pct",
                "registros_medianos",
                "identificadores_medianos",
            ]
        ].to_string(index=False)
    )

    print("\nMEJOR ESCENARIO Y OBJETIVO POR AFP")
    print("-" * 118)
    print(
        ranking_afp[
            ranking_afp["ranking_afp"] == 1
        ][
            [
                "afp",
                "escenario",
                "objetivo",
                "observaciones",
                "ratio_mediano",
                "error_mediano_pct",
                "error_p90_pct",
            ]
        ].to_string(index=False)
    )

    print("\nDUPLICADOS EXACTOS POR IDENTIFICADOR Y VALOR")
    print("-" * 118)
    print(resumen_duplicados.to_string(index=False))

    if duplicados.empty:
        print("No se detectaron duplicados exactos.")
    else:
        print(
            duplicados.sort_values(
                "monto_duplicado_excedente",
                ascending=False,
            )
            .head(40)
            .to_string(index=False)
        )

    print("\nArchivos creados:")
    for ruta in rutas.values():
        print(f" - {ruta.resolve()}")

    print(
        "\nCriterio de lectura:\n"
        "- Si solo_hojas_identificadas o su versión deduplicada presenta "
        "un ratio cercano a 1 frente a total_exterior, la segunda capa está "
        "formada principalmente por entidades o administradoras pendientes.\n"
        "- Si solo_isin queda cerca de 1, los ISIN representan casi todo el "
        "alcance monetario de la hoja 10.\n"
        "- Si las entidades pendientes también quedan cerca de 1, se habrá "
        "confirmado que la hoja contiene dos representaciones paralelas de "
        "la misma cartera.\n"
        "- La deduplicación por identificador y valor solo se considera "
        "válida cuando mejora la reconciliación sin eliminar posiciones "
        "materiales no repetidas.\n"
        "- Este módulo es de auditoría: no sustituye aún la base histórica."
    )


if __name__ == "__main__":
    main()
