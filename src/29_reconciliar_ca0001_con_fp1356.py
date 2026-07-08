from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


AFPS = ["Habitat", "Integra", "Prima", "Profuturo"]

UMBRAL_HOJA3_CORRECTO = 0.50
UMBRAL_HOJA3_TOLERABLE = 1.00

UMBRAL_HOJA10_CORRECTO = 1.00
UMBRAL_HOJA10_TOLERABLE = 2.00

UMBRAL_DIF_PORCENTAJE_INTERNO_PP = 1.00


CANDIDATOS_HOJA10 = {
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


def agregar_periodo(
    df: pd.DataFrame,
    columna_fecha: str,
) -> pd.DataFrame:
    salida = df.copy()
    salida["periodo"] = (
        pd.to_datetime(salida[columna_fecha])
        .dt.to_period("M")
        .astype(str)
    )
    return salida


def normalizar_porcentaje(
    serie: pd.Series,
) -> pd.Series:
    valores = pd.to_numeric(serie, errors="coerce")

    return pd.Series(
        np.where(
            valores.abs() <= 2.0,
            valores * 100.0,
            valores,
        ),
        index=serie.index,
    )


def clasificar_estado(
    error_rel_pct: pd.Series,
    correcto: float,
    tolerable: float,
) -> pd.Series:
    return pd.Series(
        np.select(
            [
                error_rel_pct <= correcto,
                error_rel_pct <= tolerable,
            ],
            [
                "correcto",
                "tolerable",
            ],
            default="revisar",
        ),
        index=error_rel_pct.index,
    )


def resumir_ca(
    df: pd.DataFrame,
    fuente: str,
) -> pd.DataFrame:
    df = agregar_periodo(df, "fecha_cartera")
    df["valor"] = pd.to_numeric(
        df["valor"],
        errors="coerce",
    )

    if "participacion_reportada_pct" in df.columns:
        df["participacion_reportada_pct"] = pd.to_numeric(
            df["participacion_reportada_pct"],
            errors="coerce",
        )
    elif "participacion_reportada" in df.columns:
        df["participacion_reportada_pct"] = normalizar_porcentaje(
            df["participacion_reportada"]
        )
    else:
        df["participacion_reportada_pct"] = np.nan

    if "estado_refinado" not in df.columns:
        df["estado_refinado"] = ""

    if fuente == "hoja3":
        estado_pendiente = "pendiente_sin_categoria"
    else:
        estado_pendiente = "entidad_sin_isin_pendiente"

    resumen = (
        df.groupby(
            ["periodo", "afp"],
            as_index=False,
        )
        .agg(
            fecha_ca=("fecha_cartera", "max"),
            monto_ca_miles_soles=("valor", "sum"),
            participacion_reportada_suma_pct=(
                "participacion_reportada_pct",
                "sum",
            ),
            registros=("valor", "size"),
            registros_pendientes=(
                "estado_refinado",
                lambda s: int((s == estado_pendiente).sum()),
            ),
            registros_identificados=(
                "estado_refinado",
                lambda s: int((s != estado_pendiente).sum()),
            ),
        )
    )

    resumen["fuente"] = fuente
    resumen["pendientes_pct_registros"] = np.where(
        resumen["registros"] > 0,
        resumen["registros_pendientes"]
        / resumen["registros"]
        * 100.0,
        np.nan,
    )

    return resumen


def construir_referencias_fp(
    fp: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    fp = agregar_periodo(fp, "fecha_cartera")
    fp["monto_miles_soles"] = pd.to_numeric(
        fp["monto_miles_soles"],
        errors="coerce",
    )
    fp["participacion_pct"] = pd.to_numeric(
        fp["participacion_pct"],
        errors="coerce",
    )

    total = (
        fp.groupby(
            ["periodo", "afp"],
            as_index=False,
        )
        .agg(
            fecha_fp=("fecha_cartera", "max"),
            total_fp_miles_soles=("monto_miles_soles", "sum"),
            suma_fp_pct=("participacion_pct", "sum"),
        )
    )

    filas = []

    for nombre_objetivo, categorias in CANDIDATOS_HOJA10.items():
        bloque = fp[
            fp["categoria_economica"].isin(categorias)
        ]

        agrupado = (
            bloque.groupby(
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
        agrupado["objetivo_hoja10"] = nombre_objetivo
        agrupado["categorias_objetivo"] = " | ".join(categorias)
        filas.append(agrupado)

    objetivos = pd.concat(
        filas,
        ignore_index=True,
    )

    return total, objetivos


def reconciliar_hoja3(
    ca3: pd.DataFrame,
    fp_total: pd.DataFrame,
) -> pd.DataFrame:
    control = ca3.merge(
        fp_total,
        on=["periodo", "afp"],
        how="inner",
        validate="one_to_one",
    )

    control["diferencia_miles_soles"] = (
        control["monto_ca_miles_soles"]
        - control["total_fp_miles_soles"]
    )
    control["error_relativo_pct"] = np.where(
        control["total_fp_miles_soles"].abs() > 0,
        control["diferencia_miles_soles"].abs()
        / control["total_fp_miles_soles"].abs()
        * 100.0,
        np.nan,
    )

    control["participacion_calculada_sobre_fp_pct"] = np.where(
        control["total_fp_miles_soles"].abs() > 0,
        control["monto_ca_miles_soles"]
        / control["total_fp_miles_soles"]
        * 100.0,
        np.nan,
    )

    control["diferencia_porcentaje_interno_pp"] = (
        control["participacion_reportada_suma_pct"]
        - control["participacion_calculada_sobre_fp_pct"]
    ).abs()

    control["estado_monto"] = clasificar_estado(
        control["error_relativo_pct"],
        UMBRAL_HOJA3_CORRECTO,
        UMBRAL_HOJA3_TOLERABLE,
    )

    control["estado_porcentaje_interno"] = np.where(
        control["diferencia_porcentaje_interno_pp"]
        <= UMBRAL_DIF_PORCENTAJE_INTERNO_PP,
        "correcto",
        "revisar",
    )

    control["elegible_emisores"] = (
        control["estado_monto"].isin(
            ["correcto", "tolerable"]
        )
        & (
            control["estado_porcentaje_interno"]
            == "correcto"
        )
    )

    return control


def evaluar_candidatos_hoja10(
    ca10: pd.DataFrame,
    fp_total: pd.DataFrame,
    objetivos: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    base = ca10.merge(
        fp_total,
        on=["periodo", "afp"],
        how="inner",
        validate="one_to_one",
    )

    comparacion = base.merge(
        objetivos,
        on=["periodo", "afp"],
        how="inner",
        validate="one_to_many",
    )

    comparacion["diferencia_miles_soles"] = (
        comparacion["monto_ca_miles_soles"]
        - comparacion["objetivo_monto_miles_soles"]
    )
    comparacion["error_relativo_pct"] = np.where(
        comparacion[
            "objetivo_monto_miles_soles"
        ].abs()
        > 0,
        comparacion["diferencia_miles_soles"].abs()
        / comparacion[
            "objetivo_monto_miles_soles"
        ].abs()
        * 100.0,
        np.nan,
    )

    comparacion["participacion_calculada_sobre_fp_pct"] = np.where(
        comparacion["total_fp_miles_soles"].abs() > 0,
        comparacion["monto_ca_miles_soles"]
        / comparacion["total_fp_miles_soles"]
        * 100.0,
        np.nan,
    )
    comparacion["diferencia_porcentaje_interno_pp"] = (
        comparacion["participacion_reportada_suma_pct"]
        - comparacion[
            "participacion_calculada_sobre_fp_pct"
        ]
    ).abs()

    ranking = (
        comparacion.groupby(
            "objetivo_hoja10",
            as_index=False,
        )
        .agg(
            observaciones=("error_relativo_pct", "count"),
            error_mediano_pct=(
                "error_relativo_pct",
                "median",
            ),
            error_medio_pct=(
                "error_relativo_pct",
                "mean",
            ),
            error_p90_pct=(
                "error_relativo_pct",
                lambda s: float(
                    pd.Series(s).dropna().quantile(0.90)
                ),
            ),
            dentro_1pct=(
                "error_relativo_pct",
                lambda s: float(
                    (pd.Series(s).dropna() <= 1.0).mean()
                    * 100.0
                ),
            ),
            dentro_2pct=(
                "error_relativo_pct",
                lambda s: float(
                    (pd.Series(s).dropna() <= 2.0).mean()
                    * 100.0
                ),
            ),
            dentro_5pct=(
                "error_relativo_pct",
                lambda s: float(
                    (pd.Series(s).dropna() <= 5.0).mean()
                    * 100.0
                ),
            ),
        )
        .sort_values(
            [
                "error_mediano_pct",
                "error_p90_pct",
                "error_medio_pct",
            ],
            ascending=True,
        )
        .reset_index(drop=True)
    )
    ranking["ranking"] = (
        ranking.index + 1
    )

    return comparacion, ranking


def seleccionar_objetivo_hoja10(
    comparacion: pd.DataFrame,
    ranking: pd.DataFrame,
) -> tuple[str, pd.DataFrame]:
    if ranking.empty:
        raise ValueError(
            "No fue posible comparar objetivos para la hoja 10."
        )

    objetivo = str(
        ranking.iloc[0]["objetivo_hoja10"]
    )

    control = comparacion[
        comparacion["objetivo_hoja10"] == objetivo
    ].copy()

    control["estado_monto"] = clasificar_estado(
        control["error_relativo_pct"],
        UMBRAL_HOJA10_CORRECTO,
        UMBRAL_HOJA10_TOLERABLE,
    )
    control["estado_porcentaje_interno"] = np.where(
        control["diferencia_porcentaje_interno_pp"]
        <= UMBRAL_DIF_PORCENTAJE_INTERNO_PP,
        "correcto",
        "revisar",
    )

    control["elegible_isin"] = (
        control["estado_monto"].isin(
            ["correcto", "tolerable"]
        )
        & (
            control["estado_porcentaje_interno"]
            == "correcto"
        )
    )

    return objetivo, control


def mejores_objetivos_por_afp(
    comparacion: pd.DataFrame,
) -> pd.DataFrame:
    resumen = (
        comparacion.groupby(
            ["afp", "objetivo_hoja10"],
            as_index=False,
        )
        .agg(
            observaciones=("error_relativo_pct", "count"),
            error_mediano_pct=(
                "error_relativo_pct",
                "median",
            ),
            error_p90_pct=(
                "error_relativo_pct",
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


def detectar_cambios_estructura(
    ca3_detalle: pd.DataFrame,
    ca10_detalle: pd.DataFrame,
) -> pd.DataFrame:
    partes = []

    for fuente, df in [
        ("hoja3", ca3_detalle),
        ("hoja10", ca10_detalle),
    ]:
        bloque = agregar_periodo(
            df,
            "fecha_cartera",
        )

        if fuente == "hoja3":
            identificador = "identificador_especifico"
        else:
            identificador = "isin"

        if identificador not in bloque.columns:
            bloque[identificador] = ""

        resumen = (
            bloque.groupby(
                ["periodo", "afp"],
                as_index=False,
            )
            .agg(
                registros=("valor", "size"),
                identificadores_unicos=(
                    identificador,
                    lambda s: int(
                        pd.Series(s)
                        .fillna("")
                        .astype(str)
                        .replace("", np.nan)
                        .nunique()
                    ),
                ),
            )
        )

        resumen = resumen.sort_values(
            ["afp", "periodo"]
        )
        resumen["cambio_registros_pct"] = (
            resumen.groupby("afp")["registros"]
            .pct_change()
            .mul(100.0)
        )
        resumen["cambio_identificadores_pct"] = (
            resumen.groupby("afp")[
                "identificadores_unicos"
            ]
            .pct_change()
            .mul(100.0)
        )

        resumen["alerta_cambio_estructura"] = np.where(
            (
                resumen["cambio_registros_pct"].abs()
                >= 40.0
            )
            | (
                resumen[
                    "cambio_identificadores_pct"
                ].abs()
                >= 40.0
            ),
            "revisar",
            "normal",
        )
        resumen["fuente"] = fuente
        partes.append(resumen)

    return pd.concat(
        partes,
        ignore_index=True,
    )


def resumen_final(
    control3: pd.DataFrame,
    control10: pd.DataFrame,
    objetivo10: str,
) -> pd.DataFrame:
    filas = []

    for fuente, control, elegible in [
        ("hoja3_emisores", control3, "elegible_emisores"),
        ("hoja10_isin", control10, "elegible_isin"),
    ]:
        filas.append(
            {
                "fuente": fuente,
                "objetivo_reconciliacion": (
                    "total_cartera_fp1356"
                    if fuente == "hoja3_emisores"
                    else objetivo10
                ),
                "observaciones": len(control),
                "periodos_unicos": control["periodo"].nunique(),
                "afp": control["afp"].nunique(),
                "error_mediano_pct": (
                    control["error_relativo_pct"].median()
                ),
                "error_p90_pct": (
                    control["error_relativo_pct"].quantile(0.90)
                ),
                "correctos": int(
                    (control["estado_monto"] == "correcto").sum()
                ),
                "tolerables": int(
                    (control["estado_monto"] == "tolerable").sum()
                ),
                "revisar": int(
                    (control["estado_monto"] == "revisar").sum()
                ),
                "elegibles": int(control[elegible].sum()),
                "elegibles_pct": (
                    float(control[elegible].mean() * 100.0)
                    if len(control)
                    else np.nan
                ),
            }
        )

    return pd.DataFrame(filas)


def construir_elegibilidad(
    control3: pd.DataFrame,
    control10: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    c3 = control3[
        [
            "periodo",
            "afp",
            "elegible_emisores",
            "estado_monto",
            "error_relativo_pct",
        ]
    ].rename(
        columns={
            "estado_monto": "estado_hoja3",
            "error_relativo_pct": "error_hoja3_pct",
        }
    )

    c10 = control10[
        [
            "periodo",
            "afp",
            "elegible_isin",
            "estado_monto",
            "error_relativo_pct",
        ]
    ].rename(
        columns={
            "estado_monto": "estado_hoja10",
            "error_relativo_pct": "error_hoja10_pct",
        }
    )

    combinado = c3.merge(
        c10,
        on=["periodo", "afp"],
        how="outer",
        validate="one_to_one",
    )

    combinado["elegible_ambas"] = (
        combinado["elegible_emisores"].fillna(False)
        & combinado["elegible_isin"].fillna(False)
    )

    elegibles = combinado[
        combinado["elegible_ambas"]
    ].copy()
    excluidos = combinado[
        ~combinado["elegible_ambas"]
    ].copy()

    return elegibles, excluidos


def main() -> None:
    raiz = Path(__file__).resolve().parents[1]
    processed = raiz / "data" / "processed"

    ruta_ca3 = (
        processed
        / "ca0001_fondo3_historico_hoja3_refinada.csv"
    )
    ruta_ca10 = (
        processed
        / "ca0001_fondo3_historico_hoja10_refinada.csv"
    )
    ruta_fp = (
        processed
        / "fp1356_cartera_economica_mensual_v2.csv"
    )

    ca3_detalle = leer_csv(
        ruta_ca3,
        ["fecha_cartera"],
    )
    ca10_detalle = leer_csv(
        ruta_ca10,
        ["fecha_cartera"],
    )
    fp = leer_csv(
        ruta_fp,
        ["fecha_cartera"],
    )

    ca3 = resumir_ca(ca3_detalle, "hoja3")
    ca10 = resumir_ca(ca10_detalle, "hoja10")
    fp_total, objetivos = construir_referencias_fp(fp)

    control3 = reconciliar_hoja3(
        ca3,
        fp_total,
    )

    comparacion10, ranking10 = (
        evaluar_candidatos_hoja10(
            ca10,
            fp_total,
            objetivos,
        )
    )

    objetivo10, control10 = (
        seleccionar_objetivo_hoja10(
            comparacion10,
            ranking10,
        )
    )

    ranking_afp = mejores_objetivos_por_afp(
        comparacion10
    )
    cambios = detectar_cambios_estructura(
        ca3_detalle,
        ca10_detalle,
    )
    resumen = resumen_final(
        control3,
        control10,
        objetivo10,
    )
    elegibles, excluidos = construir_elegibilidad(
        control3,
        control10,
    )

    rutas = {
        "control3": (
            processed
            / "ca0001_fp1356_reconciliacion_hoja3.csv"
        ),
        "comparacion10": (
            processed
            / "ca0001_fp1356_candidatos_hoja10.csv"
        ),
        "ranking10": (
            processed
            / "ca0001_fp1356_ranking_objetivos_hoja10.csv"
        ),
        "ranking_afp": (
            processed
            / "ca0001_fp1356_ranking_objetivos_hoja10_por_afp.csv"
        ),
        "control10": (
            processed
            / "ca0001_fp1356_reconciliacion_hoja10.csv"
        ),
        "cambios": (
            processed
            / "ca0001_cambios_estructura_historica.csv"
        ),
        "resumen": (
            processed
            / "ca0001_fp1356_resumen_reconciliacion.csv"
        ),
        "elegibles": (
            processed
            / "ca0001_fp1356_periodos_elegibles.csv"
        ),
        "excluidos": (
            processed
            / "ca0001_fp1356_periodos_excluidos.csv"
        ),
    }

    control3.to_csv(
        rutas["control3"],
        index=False,
        encoding="utf-8-sig",
    )
    comparacion10.to_csv(
        rutas["comparacion10"],
        index=False,
        encoding="utf-8-sig",
    )
    ranking10.to_csv(
        rutas["ranking10"],
        index=False,
        encoding="utf-8-sig",
    )
    ranking_afp.to_csv(
        rutas["ranking_afp"],
        index=False,
        encoding="utf-8-sig",
    )
    control10.to_csv(
        rutas["control10"],
        index=False,
        encoding="utf-8-sig",
    )
    cambios.to_csv(
        rutas["cambios"],
        index=False,
        encoding="utf-8-sig",
    )
    resumen.to_csv(
        rutas["resumen"],
        index=False,
        encoding="utf-8-sig",
    )
    elegibles.to_csv(
        rutas["elegibles"],
        index=False,
        encoding="utf-8-sig",
    )
    excluidos.to_csv(
        rutas["excluidos"],
        index=False,
        encoding="utf-8-sig",
    )

    print("\nRECONCILIACIÓN CA-0001 CONTRA FP-1356 TERMINADA")
    print("=" * 112)
    print(f"Observaciones hoja 3: {len(control3)}")
    print(f"Observaciones hoja 10: {len(control10)}")
    print(f"Objetivo seleccionado para hoja 10: {objetivo10}")
    print(f"Periodos-AFP elegibles en ambas fuentes: {len(elegibles)}")
    print(f"Periodos-AFP excluidos: {len(excluidos)}")

    print("\nRESUMEN DE RECONCILIACIÓN")
    print("-" * 112)
    print(resumen.to_string(index=False))

    print("\nRANKING DE OBJETIVOS POSIBLES PARA HOJA 10")
    print("-" * 112)
    print(
        ranking10[
            [
                "ranking",
                "objetivo_hoja10",
                "observaciones",
                "error_mediano_pct",
                "error_p90_pct",
                "dentro_1pct",
                "dentro_2pct",
                "dentro_5pct",
            ]
        ].to_string(index=False)
    )

    print("\nMEJOR OBJETIVO DE HOJA 10 POR AFP")
    print("-" * 112)
    print(
        ranking_afp[
            ranking_afp["ranking_afp"] == 1
        ][
            [
                "afp",
                "objetivo_hoja10",
                "observaciones",
                "error_mediano_pct",
                "error_p90_pct",
            ]
        ].to_string(index=False)
    )

    print("\nESTADOS DE HOJA 3")
    print("-" * 112)
    print(
        control3["estado_monto"]
        .value_counts(dropna=False)
        .rename_axis("estado")
        .reset_index(name="observaciones")
        .to_string(index=False)
    )

    print("\nESTADOS DE HOJA 10")
    print("-" * 112)
    print(
        control10["estado_monto"]
        .value_counts(dropna=False)
        .rename_axis("estado")
        .reset_index(name="observaciones")
        .to_string(index=False)
    )

    alertas = cambios[
        cambios["alerta_cambio_estructura"] == "revisar"
    ]

    print("\nALERTAS DE CAMBIO DE ESTRUCTURA")
    print("-" * 112)

    if alertas.empty:
        print("No se detectaron cambios abruptos superiores al 40 %.")
    else:
        print(
            alertas[
                [
                    "fuente",
                    "periodo",
                    "afp",
                    "registros",
                    "identificadores_unicos",
                    "cambio_registros_pct",
                    "cambio_identificadores_pct",
                ]
            ].head(40).to_string(index=False)
        )

    print("\nArchivos creados:")
    for ruta in rutas.values():
        print(f" - {ruta.resolve()}")

    print(
        "\nInterpretación:\n"
        "- La hoja 3 se contrasta contra el total completo del Fondo 3.\n"
        "- La hoja 10 no se fuerza contra un subtotal supuesto: se comparan "
        "varios alcances económicos de FP-1356 y se selecciona el que mejor "
        "reconcilia de forma histórica.\n"
        "- La selección del objetivo de hoja 10 es una inferencia empírica; "
        "debe ser estable entre AFP y meses para considerarla válida.\n"
        "- Los periodos elegibles son los únicos que podrán alimentar las "
        "exposiciones históricas por emisor e ISIN.\n"
        "- Una reconciliación correcta no demuestra todavía la exposición "
        "sectorial de cada fondo; esa clasificación se realizará después "
        "con los identificadores ya validados."
    )


if __name__ == "__main__":
    main()
