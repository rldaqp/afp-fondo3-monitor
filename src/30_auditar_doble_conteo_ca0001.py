from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


AFPS = ["Habitat", "Integra", "Prima", "Profuturo"]
VENTANA_FILAS = 3
REDONDEO_VECTOR = 6

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


def leer_csv(ruta: Path, fecha: str | None = None) -> pd.DataFrame:
    if not ruta.exists():
        raise FileNotFoundError(f"No existe: {ruta}")

    return pd.read_csv(
        ruta,
        parse_dates=[fecha] if fecha else [],
    )


def asegurar_columnas(df: pd.DataFrame, columnas: list[str]) -> pd.DataFrame:
    salida = df.copy()

    for columna in columnas:
        if columna not in salida.columns:
            salida[columna] = ""
        salida[columna] = salida[columna].fillna("").astype(str)

    return salida


def normalizar_porcentaje(serie: pd.Series) -> pd.Series:
    valores = pd.to_numeric(serie, errors="coerce")

    return pd.Series(
        np.where(
            valores.abs() <= 2.0,
            valores * 100.0,
            valores,
        ),
        index=serie.index,
    )


def preparar_detalle(df: pd.DataFrame, fuente: str) -> pd.DataFrame:
    salida = df.copy()
    salida["valor"] = pd.to_numeric(
        salida["valor"],
        errors="coerce",
    ).fillna(0.0)
    salida["fila_excel_aprox"] = pd.to_numeric(
        salida["fila_excel_aprox"],
        errors="coerce",
    ).astype("Int64")
    salida["periodo"] = (
        salida["fecha_cartera"]
        .dt.to_period("M")
        .astype(str)
    )

    if "participacion_reportada_pct" in salida.columns:
        salida["participacion_reportada_pct"] = pd.to_numeric(
            salida["participacion_reportada_pct"],
            errors="coerce",
        )
    elif "participacion_reportada" in salida.columns:
        salida["participacion_reportada_pct"] = normalizar_porcentaje(
            salida["participacion_reportada"]
        )
    else:
        salida["participacion_reportada_pct"] = np.nan

    if fuente == "hoja3":
        salida = asegurar_columnas(
            salida,
            [
                "identificador_especifico",
                "categoria_instrumento",
                "estado_refinado",
            ],
        )
    else:
        salida = asegurar_columnas(
            salida,
            [
                "entidad_administradora",
                "isin",
                "instrumento_sin_isin",
                "estado_refinado",
                "moneda",
            ],
        )

    return salida


def tabla_por_fila(df: pd.DataFrame, fuente: str) -> pd.DataFrame:
    claves = [
        "periodo",
        "fecha_cartera",
        "archivo",
        "fila_excel_aprox",
    ]

    valores = (
        df.pivot_table(
            index=claves,
            columns="afp",
            values="valor",
            aggfunc="sum",
            fill_value=0.0,
        )
        .reset_index()
    )
    valores.columns.name = None

    porcentajes = (
        df.pivot_table(
            index=claves,
            columns="afp",
            values="participacion_reportada_pct",
            aggfunc="first",
        )
        .reset_index()
    )
    porcentajes.columns = [
        columna
        if columna in claves
        else f"pct_{columna}"
        for columna in porcentajes.columns
    ]

    if fuente == "hoja3":
        meta_cols = [
            "identificador_especifico",
            "categoria_instrumento",
            "estado_refinado",
        ]
    else:
        meta_cols = [
            "entidad_administradora",
            "isin",
            "instrumento_sin_isin",
            "estado_refinado",
            "moneda",
        ]

    metadatos = (
        df.groupby(claves, as_index=False)[meta_cols]
        .first()
    )

    tabla = (
        valores.merge(
            porcentajes,
            on=claves,
            how="left",
            validate="one_to_one",
        )
        .merge(
            metadatos,
            on=claves,
            how="left",
            validate="one_to_one",
        )
    )

    for afp in AFPS:
        if afp not in tabla.columns:
            tabla[afp] = 0.0
        if f"pct_{afp}" not in tabla.columns:
            tabla[f"pct_{afp}"] = np.nan

    tabla["fingerprint_vector"] = (
        tabla[AFPS]
        .round(REDONDEO_VECTOR)
        .astype(str)
        .agg("|".join, axis=1)
    )
    tabla["monto_vector_total"] = tabla[AFPS].abs().sum(axis=1)
    tabla["fuente"] = fuente

    return tabla


def prioridad_fila(fila: pd.Series, fuente: str) -> float:
    estado = str(fila.get("estado_refinado", ""))

    if fuente == "hoja10":
        isin = str(fila.get("isin", "")).strip()
        instrumento = str(
            fila.get("instrumento_sin_isin", "")
        ).strip()
        entidad = str(
            fila.get("entidad_administradora", "")
        ).strip()

        prioridad = 0.0

        if isin:
            prioridad += 100.0
        if instrumento:
            prioridad += 80.0
        if "pareja_exacta" in estado:
            prioridad += 40.0
        if "pendiente" in estado:
            prioridad += 10.0
        prioridad += min(len(instrumento or isin or entidad), 80) / 100.0
        return prioridad

    categoria = str(
        fila.get("categoria_instrumento", "")
    ).strip()
    identificador = str(
        fila.get("identificador_especifico", "")
    ).strip()

    prioridad = 0.0

    if categoria:
        prioridad += 100.0
    if "pareja_exacta_original" in estado:
        prioridad += 50.0
    elif "pareja_exacta_heuristica" in estado:
        prioridad += 45.0
    elif "pendiente" in estado:
        prioridad += 10.0

    prioridad += min(len(identificador), 80) / 100.0
    return prioridad


def formar_clusters(tabla: pd.DataFrame, fuente: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    tabla = tabla.copy()
    tabla["conservar_auditoria"] = True
    tabla["id_cluster"] = ""
    tabla["prioridad"] = tabla.apply(
        lambda fila: prioridad_fila(fila, fuente),
        axis=1,
    )

    registros_clusters = []
    contador = 0

    grupos = tabla.groupby(
        ["periodo", "archivo", "fingerprint_vector"],
        sort=False,
    )

    for (periodo, archivo, fingerprint), grupo in grupos:
        if len(grupo) <= 1:
            continue

        grupo = grupo.sort_values("fila_excel_aprox")
        indices = grupo.index.tolist()
        cluster_actual = [indices[0]]

        for indice_anterior, indice_actual in zip(indices[:-1], indices[1:]):
            fila_anterior = int(
                tabla.at[indice_anterior, "fila_excel_aprox"]
            )
            fila_actual = int(
                tabla.at[indice_actual, "fila_excel_aprox"]
            )

            if fila_actual - fila_anterior <= VENTANA_FILAS:
                cluster_actual.append(indice_actual)
            else:
                if len(cluster_actual) > 1:
                    contador += 1
                    registrar_cluster(
                        tabla,
                        cluster_actual,
                        fuente,
                        periodo,
                        archivo,
                        fingerprint,
                        contador,
                        registros_clusters,
                    )
                cluster_actual = [indice_actual]

        if len(cluster_actual) > 1:
            contador += 1
            registrar_cluster(
                tabla,
                cluster_actual,
                fuente,
                periodo,
                archivo,
                fingerprint,
                contador,
                registros_clusters,
            )

    clusters = pd.DataFrame(registros_clusters)
    return tabla, clusters


def registrar_cluster(
    tabla: pd.DataFrame,
    indices: list[int],
    fuente: str,
    periodo: str,
    archivo: str,
    fingerprint: str,
    contador: int,
    registros_clusters: list[dict],
) -> None:
    bloque = tabla.loc[indices].copy()
    ganador = bloque.sort_values(
        ["prioridad", "fila_excel_aprox"],
        ascending=[False, True],
    ).index[0]

    id_cluster = f"{fuente}_{contador:06d}"

    for indice in indices:
        tabla.at[indice, "id_cluster"] = id_cluster
        tabla.at[indice, "conservar_auditoria"] = indice == ganador

    registros_clusters.append(
        {
            "id_cluster": id_cluster,
            "fuente": fuente,
            "periodo": periodo,
            "archivo": archivo,
            "fingerprint_vector": fingerprint,
            "numero_filas": len(indices),
            "filas_excel": " | ".join(
                str(int(x))
                for x in bloque["fila_excel_aprox"].tolist()
            ),
            "fila_conservada": int(
                tabla.at[ganador, "fila_excel_aprox"]
            ),
            "monto_vector_total": float(
                bloque.iloc[0]["monto_vector_total"]
            ),
            "prioridades": " | ".join(
                f"{x:.2f}"
                for x in bloque["prioridad"].tolist()
            ),
        }
    )


def aplicar_conservacion(
    detalle: pd.DataFrame,
    tabla_filas: pd.DataFrame,
) -> pd.DataFrame:
    claves = [
        "periodo",
        "archivo",
        "fila_excel_aprox",
    ]

    mascara = tabla_filas[
        claves + ["conservar_auditoria"]
    ]

    salida = detalle.merge(
        mascara,
        on=claves,
        how="left",
        validate="many_to_one",
    )

    salida["conservar_auditoria"] = (
        salida["conservar_auditoria"]
        .fillna(True)
        .astype(bool)
    )

    return salida[
        salida["conservar_auditoria"]
    ].copy()


def construir_fp(fp: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    salida = fp.copy()
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

    for objetivo, categorias in CANDIDATOS_HOJA10.items():
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
                objetivo_pct=("participacion_pct", "sum"),
            )
        )
        bloque["objetivo"] = objetivo
        objetivos.append(bloque)

    return total, pd.concat(objetivos, ignore_index=True)


def resumir_fuente(df: pd.DataFrame) -> pd.DataFrame:
    return (
        df.groupby(
            ["periodo", "afp"],
            as_index=False,
        )
        .agg(
            monto_ca_miles_soles=("valor", "sum"),
            suma_pct_reportada=(
                "participacion_reportada_pct",
                "sum",
            ),
            registros=("valor", "size"),
        )
    )


def reconciliar_hoja3(
    antes: pd.DataFrame,
    despues: pd.DataFrame,
    fp_total: pd.DataFrame,
) -> pd.DataFrame:
    filas = []

    for escenario, tabla in [
        ("antes", antes),
        ("despues_auditoria", despues),
    ]:
        resumen = resumir_fuente(tabla).merge(
            fp_total,
            on=["periodo", "afp"],
            how="inner",
            validate="one_to_one",
        )
        resumen["escenario"] = escenario
        resumen["ratio_ca_fp"] = np.where(
            resumen["total_fp_miles_soles"].abs() > 0,
            resumen["monto_ca_miles_soles"]
            / resumen["total_fp_miles_soles"],
            np.nan,
        )
        resumen["error_abs_pct"] = (
            resumen["ratio_ca_fp"] - 1.0
        ).abs() * 100.0
        resumen["pct_calculado_sobre_fp"] = (
            resumen["ratio_ca_fp"] * 100.0
        )
        resumen["dif_pct_interno_pp"] = (
            resumen["suma_pct_reportada"]
            - resumen["pct_calculado_sobre_fp"]
        ).abs()
        filas.append(resumen)

    return pd.concat(filas, ignore_index=True)


def reconciliar_hoja10(
    antes: pd.DataFrame,
    despues: pd.DataFrame,
    fp_total: pd.DataFrame,
    objetivos: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    filas = []

    for escenario, tabla in [
        ("antes", antes),
        ("despues_auditoria", despues),
    ]:
        resumen = resumir_fuente(tabla).merge(
            fp_total,
            on=["periodo", "afp"],
            how="inner",
            validate="one_to_one",
        )
        resumen = resumen.merge(
            objetivos,
            on=["periodo", "afp"],
            how="inner",
            validate="one_to_many",
        )
        resumen["escenario"] = escenario
        resumen["ratio_ca_objetivo"] = np.where(
            resumen["objetivo_monto_miles_soles"].abs() > 0,
            resumen["monto_ca_miles_soles"]
            / resumen["objetivo_monto_miles_soles"],
            np.nan,
        )
        resumen["error_abs_pct"] = (
            resumen["ratio_ca_objetivo"] - 1.0
        ).abs() * 100.0
        resumen["pct_calculado_sobre_total_fp"] = np.where(
            resumen["total_fp_miles_soles"].abs() > 0,
            resumen["monto_ca_miles_soles"]
            / resumen["total_fp_miles_soles"]
            * 100.0,
            np.nan,
        )
        resumen["dif_pct_interno_pp"] = (
            resumen["suma_pct_reportada"]
            - resumen["pct_calculado_sobre_total_fp"]
        ).abs()
        filas.append(resumen)

    detalle = pd.concat(filas, ignore_index=True)

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
            diferencia_interna_mediana_pp=(
                "dif_pct_interno_pp",
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


def resumen_duplicados(
    tabla_filas: pd.DataFrame,
    clusters: pd.DataFrame,
    fuente: str,
) -> pd.DataFrame:
    total_filas = len(tabla_filas)
    descartadas = int(
        (~tabla_filas["conservar_auditoria"]).sum()
    )

    return pd.DataFrame(
        [
            {
                "fuente": fuente,
                "filas_unicas_antes": total_filas,
                "clusters_detectados": len(clusters),
                "filas_descartadas_auditoria": descartadas,
                "filas_unicas_despues": total_filas - descartadas,
                "reduccion_pct": (
                    descartadas / total_filas * 100.0
                    if total_filas
                    else np.nan
                ),
            }
        ]
    )


def main() -> None:
    raiz = Path(__file__).resolve().parents[1]
    processed = raiz / "data" / "processed"

    h3 = preparar_detalle(
        leer_csv(
            processed
            / "ca0001_fondo3_historico_hoja3_refinada.csv",
            "fecha_cartera",
        ),
        "hoja3",
    )
    h10 = preparar_detalle(
        leer_csv(
            processed
            / "ca0001_fondo3_historico_hoja10_refinada.csv",
            "fecha_cartera",
        ),
        "hoja10",
    )
    fp = leer_csv(
        processed
        / "fp1356_cartera_economica_mensual_v2.csv",
        "fecha_cartera",
    )

    filas3 = tabla_por_fila(h3, "hoja3")
    filas10 = tabla_por_fila(h10, "hoja10")

    filas3_auditadas, clusters3 = formar_clusters(
        filas3,
        "hoja3",
    )
    filas10_auditadas, clusters10 = formar_clusters(
        filas10,
        "hoja10",
    )

    h3_dedup = aplicar_conservacion(
        h3,
        filas3_auditadas,
    )
    h10_dedup = aplicar_conservacion(
        h10,
        filas10_auditadas,
    )

    fp_total, objetivos = construir_fp(fp)

    rec3 = reconciliar_hoja3(
        h3,
        h3_dedup,
        fp_total,
    )
    rec10, ranking10 = reconciliar_hoja10(
        h10,
        h10_dedup,
        fp_total,
        objetivos,
    )

    clusters = pd.concat(
        [clusters3, clusters10],
        ignore_index=True,
        sort=False,
    )
    resumen_dup = pd.concat(
        [
            resumen_duplicados(
                filas3_auditadas,
                clusters3,
                "hoja3",
            ),
            resumen_duplicados(
                filas10_auditadas,
                clusters10,
                "hoja10",
            ),
        ],
        ignore_index=True,
    )

    resumen_rec3 = (
        rec3.groupby("escenario", as_index=False)
        .agg(
            observaciones=("error_abs_pct", "count"),
            ratio_mediano=("ratio_ca_fp", "median"),
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
            diferencia_interna_mediana_pp=(
                "dif_pct_interno_pp",
                "median",
            ),
        )
    )

    rutas = {
        "clusters": (
            processed
            / "ca0001_auditoria_clusters_vectores_duplicados.csv"
        ),
        "filas3": (
            processed
            / "ca0001_auditoria_filas_hoja3.csv"
        ),
        "filas10": (
            processed
            / "ca0001_auditoria_filas_hoja10.csv"
        ),
        "h3_dedup": (
            processed
            / "ca0001_hoja3_deduplicada_auditoria.csv"
        ),
        "h10_dedup": (
            processed
            / "ca0001_hoja10_deduplicada_auditoria.csv"
        ),
        "rec3": (
            processed
            / "ca0001_auditoria_reconciliacion_hoja3.csv"
        ),
        "rec10": (
            processed
            / "ca0001_auditoria_reconciliacion_hoja10.csv"
        ),
        "ranking10": (
            processed
            / "ca0001_auditoria_ranking_hoja10.csv"
        ),
        "resumen_dup": (
            processed
            / "ca0001_auditoria_resumen_duplicados.csv"
        ),
        "resumen_rec3": (
            processed
            / "ca0001_auditoria_resumen_reconciliacion_hoja3.csv"
        ),
    }

    clusters.to_csv(
        rutas["clusters"],
        index=False,
        encoding="utf-8-sig",
    )
    filas3_auditadas.to_csv(
        rutas["filas3"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    filas10_auditadas.to_csv(
        rutas["filas10"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    h3_dedup.to_csv(
        rutas["h3_dedup"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    h10_dedup.to_csv(
        rutas["h10_dedup"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    rec3.to_csv(
        rutas["rec3"],
        index=False,
        encoding="utf-8-sig",
    )
    rec10.to_csv(
        rutas["rec10"],
        index=False,
        encoding="utf-8-sig",
    )
    ranking10.to_csv(
        rutas["ranking10"],
        index=False,
        encoding="utf-8-sig",
    )
    resumen_dup.to_csv(
        rutas["resumen_dup"],
        index=False,
        encoding="utf-8-sig",
    )
    resumen_rec3.to_csv(
        rutas["resumen_rec3"],
        index=False,
        encoding="utf-8-sig",
    )

    print("\nAUDITORÍA DE POSIBLE DOBLE CONTEO CA-0001")
    print("=" * 116)

    print("\nRESUMEN DE VECTORES DUPLICADOS")
    print("-" * 116)
    print(resumen_dup.to_string(index=False))

    print("\nHOJA 3 — RECONCILIACIÓN ANTES Y DESPUÉS")
    print("-" * 116)
    print(resumen_rec3.to_string(index=False))

    print("\nHOJA 10 — RANKING ANTES Y DESPUÉS")
    print("-" * 116)
    print(
        ranking10[
            [
                "escenario",
                "ranking_escenario",
                "objetivo",
                "observaciones",
                "ratio_mediano",
                "ratio_p10",
                "ratio_p90",
                "error_mediano_pct",
                "error_p90_pct",
                "dentro_1pct",
                "dentro_2pct",
                "diferencia_interna_mediana_pp",
            ]
        ].to_string(index=False)
    )

    print("\nPRINCIPALES CLUSTERS SOSPECHOSOS")
    print("-" * 116)

    if clusters.empty:
        print("No se detectaron vectores duplicados próximos.")
    else:
        print(
            clusters.sort_values(
                "monto_vector_total",
                ascending=False,
            ).head(40).to_string(index=False)
        )

    print("\nArchivos creados:")
    for ruta in rutas.values():
        print(f" - {ruta.resolve()}")

    print(
        "\nCriterio de lectura:\n"
        "- Un ratio mediano cercano a 2,0 en hoja 10 confirma doble conteo "
        "aproximado; un ratio cercano a 1,0 después de la auditoría indica "
        "que los pares repetidos explicaban el problema.\n"
        "- Las bases deduplicadas son solo resultados de auditoría y no "
        "reemplazan todavía los históricos originales.\n"
        "- Si la reconciliación mejora de forma material, se convertirán "
        "estas reglas en una depuración histórica definitiva.\n"
        "- Si el ratio sigue cerca de 2,0, el problema está en una jerarquía "
        "más profunda o en la interpretación del alcance de la hoja 10."
    )


if __name__ == "__main__":
    main()
