from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


AFPS = ["Habitat", "Integra", "Prima", "Profuturo"]

MAX_FILAS_HIJAS = 90
MAX_ITERACIONES = 8
TOLERANCIA_RELATIVA = 1e-6
TOLERANCIA_ABSOLUTA = 1e-3

MONEDAS = {
    "USD",
    "EUR",
    "GBP",
    "JPY",
    "PEN",
    "CHF",
    "CAD",
    "AUD",
    "CNY",
    "HKD",
    "BRL",
    "MXN",
    "CLP",
    "COP",
}

CANDIDATOS_FP1356 = {
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


def leer_csv(ruta: Path, fechas: list[str] | None = None) -> pd.DataFrame:
    if not ruta.exists():
        raise FileNotFoundError(f"No existe: {ruta}")

    return pd.read_csv(
        ruta,
        parse_dates=fechas or [],
    )


def primera_no_vacia(serie: pd.Series) -> str:
    for valor in serie:
        if pd.isna(valor):
            continue
        texto = str(valor).strip()
        if texto and texto.lower() != "nan":
            return texto
    return ""


def preparar_historico(df: pd.DataFrame) -> pd.DataFrame:
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
        "entidad_administradora",
        "isin",
        "instrumento_sin_isin",
        "estado_refinado",
        "moneda",
    ]:
        if columna not in salida.columns:
            salida[columna] = ""
        salida[columna] = (
            salida[columna]
            .fillna("")
            .astype(str)
            .str.strip()
        )

    if "participacion_reportada_pct" in salida.columns:
        salida["participacion_reportada_pct"] = pd.to_numeric(
            salida["participacion_reportada_pct"],
            errors="coerce",
        )
    elif "participacion_reportada" in salida.columns:
        valores = pd.to_numeric(
            salida["participacion_reportada"],
            errors="coerce",
        )
        salida["participacion_reportada_pct"] = np.where(
            valores.abs() <= 2.0,
            valores * 100.0,
            valores,
        )
    else:
        salida["participacion_reportada_pct"] = np.nan

    return salida


def construir_tabla_filas(df: pd.DataFrame) -> pd.DataFrame:
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

    metadatos = (
        df.groupby(claves, as_index=False)
        .agg(
            entidad_administradora=(
                "entidad_administradora",
                primera_no_vacia,
            ),
            isin=("isin", primera_no_vacia),
            instrumento_sin_isin=(
                "instrumento_sin_isin",
                primera_no_vacia,
            ),
            moneda=("moneda", primera_no_vacia),
            estado_refinado=(
                "estado_refinado",
                primera_no_vacia,
            ),
        )
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

    tabla["nombre_final"] = np.where(
        tabla["isin"].astype(str).str.len() > 0,
        tabla["isin"],
        np.where(
            tabla["instrumento_sin_isin"]
            .astype(str)
            .str.len()
            > 0,
            tabla["instrumento_sin_isin"],
            tabla["entidad_administradora"],
        ),
    )

    tabla["monto_vector_total"] = (
        tabla[AFPS].abs().sum(axis=1)
    )
    tabla["es_isin"] = (
        tabla["isin"].astype(str).str.len() > 0
    )
    tabla["es_moneda_suelta"] = (
        tabla["nombre_final"]
        .astype(str)
        .str.upper()
        .isin(MONEDAS)
    )
    tabla["activo_jerarquia"] = True
    tabla["es_subtotal_jerarquico"] = False
    tabla["id_relacion_padre"] = ""
    tabla["iteracion_eliminacion"] = np.nan

    return tabla.sort_values(
        ["periodo", "archivo", "fila_excel_aprox"]
    ).reset_index(drop=True)


def vector_fila(fila: pd.Series) -> np.ndarray:
    return np.array(
        [float(fila.get(afp, 0.0)) for afp in AFPS],
        dtype=float,
    )


def error_vector(
    padre: np.ndarray,
    suma_hijos: np.ndarray,
) -> float:
    denominador = max(
        float(np.abs(padre).sum()),
        TOLERANCIA_ABSOLUTA,
    )
    return float(
        np.abs(padre - suma_hijos).sum()
        / denominador
    )


def excede_vector(
    padre: np.ndarray,
    acumulado: np.ndarray,
) -> bool:
    limites = (
        padre
        + np.abs(padre) * 1e-5
        + TOLERANCIA_ABSOLUTA
    )
    return bool(np.any(acumulado > limites))


def candidato_padre(fila: pd.Series) -> bool:
    if not bool(fila["activo_jerarquia"]):
        return False

    if bool(fila["es_isin"]):
        return False

    if bool(fila["es_moneda_suelta"]):
        return False

    if float(fila["monto_vector_total"]) <= TOLERANCIA_ABSOLUTA:
        return False

    return True


def hijo_mas_especifico(fila: pd.Series) -> bool:
    return bool(
        fila["es_isin"]
        or str(fila["instrumento_sin_isin"]).strip()
    )


def detectar_subtotales_grupo(
    grupo: pd.DataFrame,
    contador_inicial: int,
) -> tuple[pd.DataFrame, list[dict], int]:
    grupo = grupo.copy().reset_index(drop=True)
    relaciones: list[dict] = []
    contador = contador_inicial

    for iteracion in range(1, MAX_ITERACIONES + 1):
        cambios = 0

        for i in range(len(grupo) - 2, -1, -1):
            padre_fila = grupo.iloc[i]

            if not candidato_padre(padre_fila):
                continue

            padre = vector_fila(padre_fila)
            acumulado = np.zeros(len(AFPS), dtype=float)
            indices_hijos: list[int] = []

            limite = min(
                len(grupo),
                i + 1 + MAX_FILAS_HIJAS,
            )

            for j in range(i + 1, limite):
                if not bool(grupo.at[j, "activo_jerarquia"]):
                    continue

                hijo = vector_fila(grupo.iloc[j])

                if np.abs(hijo).sum() <= TOLERANCIA_ABSOLUTA:
                    continue

                acumulado = acumulado + hijo
                indices_hijos.append(j)

                error = error_vector(padre, acumulado)

                coincidencia_multiple = (
                    len(indices_hijos) >= 2
                    and error <= TOLERANCIA_RELATIVA
                )
                coincidencia_simple = (
                    len(indices_hijos) == 1
                    and error <= TOLERANCIA_RELATIVA
                    and hijo_mas_especifico(grupo.iloc[j])
                    and (
                        int(grupo.at[j, "fila_excel_aprox"])
                        - int(padre_fila["fila_excel_aprox"])
                        <= 3
                    )
                )

                if coincidencia_multiple or coincidencia_simple:
                    contador += 1
                    relacion = f"H10J_{contador:07d}"

                    grupo.at[i, "activo_jerarquia"] = False
                    grupo.at[i, "es_subtotal_jerarquico"] = True
                    grupo.at[i, "id_relacion_padre"] = relacion
                    grupo.at[i, "iteracion_eliminacion"] = iteracion

                    nombres_hijos = [
                        str(grupo.at[k, "nombre_final"])
                        for k in indices_hijos
                    ]
                    filas_hijos = [
                        str(int(grupo.at[k, "fila_excel_aprox"]))
                        for k in indices_hijos
                    ]

                    relaciones.append(
                        {
                            "id_relacion_padre": relacion,
                            "periodo": padre_fila["periodo"],
                            "archivo": padre_fila["archivo"],
                            "iteracion": iteracion,
                            "fila_padre": int(
                                padre_fila["fila_excel_aprox"]
                            ),
                            "nombre_padre": padre_fila["nombre_final"],
                            "estado_padre": padre_fila[
                                "estado_refinado"
                            ],
                            "numero_hijos_activos": len(indices_hijos),
                            "filas_hijas": " | ".join(filas_hijos),
                            "nombres_hijos": " | ".join(nombres_hijos),
                            "error_relativo_vector": error,
                            "monto_vector_padre": float(
                                np.abs(padre).sum()
                            ),
                            "monto_vector_hijos": float(
                                np.abs(acumulado).sum()
                            ),
                        }
                    )

                    cambios += 1
                    break

                if excede_vector(padre, acumulado):
                    break

        if cambios == 0:
            break

    return grupo, relaciones, contador


def detectar_jerarquia(tabla: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    partes = []
    relaciones_total: list[dict] = []
    contador = 0

    for _, grupo in tabla.groupby(
        ["periodo", "archivo"],
        sort=True,
    ):
        depurado, relaciones, contador = detectar_subtotales_grupo(
            grupo,
            contador,
        )
        partes.append(depurado)
        relaciones_total.extend(relaciones)

    tabla_salida = pd.concat(
        partes,
        ignore_index=True,
        sort=False,
    )

    return tabla_salida, pd.DataFrame(relaciones_total)


def aplicar_hojas_finales(
    detalle: pd.DataFrame,
    tabla_filas: pd.DataFrame,
) -> pd.DataFrame:
    mascara = tabla_filas[
        [
            "periodo",
            "archivo",
            "fila_excel_aprox",
            "activo_jerarquia",
            "es_subtotal_jerarquico",
            "id_relacion_padre",
            "iteracion_eliminacion",
        ]
    ]

    salida = detalle.merge(
        mascara,
        on=["periodo", "archivo", "fila_excel_aprox"],
        how="left",
        validate="many_to_one",
    )

    salida["activo_jerarquia"] = (
        salida["activo_jerarquia"]
        .fillna(True)
        .astype(bool)
    )

    return salida[
        salida["activo_jerarquia"]
    ].copy()


def preparar_fp1356(fp: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
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

    for objetivo, categorias in CANDIDATOS_FP1356.items():
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


def resumen_ca(df: pd.DataFrame) -> pd.DataFrame:
    return (
        df.groupby(
            ["periodo", "afp"],
            as_index=False,
        )
        .agg(
            monto_ca_miles_soles=("valor", "sum"),
            registros=("valor", "size"),
            suma_pct_reportada=(
                "participacion_reportada_pct",
                "sum",
            ),
        )
    )


def reconciliar(
    original: pd.DataFrame,
    hojas: pd.DataFrame,
    total_fp: pd.DataFrame,
    objetivos: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    comparaciones = []

    for escenario, detalle in [
        ("original", original),
        ("solo_hojas_jerarquia", hojas),
    ]:
        base = (
            resumen_ca(detalle)
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

        base["escenario"] = escenario
        base["ratio_ca_objetivo"] = np.where(
            base["objetivo_monto_miles_soles"].abs() > 0,
            base["monto_ca_miles_soles"]
            / base["objetivo_monto_miles_soles"],
            np.nan,
        )
        base["error_abs_pct"] = (
            base["ratio_ca_objetivo"] - 1.0
        ).abs() * 100.0
        base["pct_ca_sobre_fondo"] = np.where(
            base["total_fp_miles_soles"].abs() > 0,
            base["monto_ca_miles_soles"]
            / base["total_fp_miles_soles"]
            * 100.0,
            np.nan,
        )
        base["diferencia_pct_interno_pp"] = (
            base["suma_pct_reportada"]
            - base["pct_ca_sobre_fondo"]
        ).abs()

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
            diferencia_interna_mediana_pp=(
                "diferencia_pct_interno_pp",
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


def control_por_periodo(tabla_filas: pd.DataFrame) -> pd.DataFrame:
    return (
        tabla_filas.groupby(
            ["periodo", "archivo"],
            as_index=False,
        )
        .agg(
            filas_iniciales=("fila_excel_aprox", "size"),
            subtotales_jerarquicos=(
                "es_subtotal_jerarquico",
                "sum",
            ),
            hojas_finales=("activo_jerarquia", "sum"),
            iteracion_maxima=(
                "iteracion_eliminacion",
                "max",
            ),
        )
    )


def main() -> None:
    raiz = Path(__file__).resolve().parents[1]
    processed = raiz / "data" / "processed"

    ruta_h10 = (
        processed
        / "ca0001_fondo3_historico_hoja10_refinada.csv"
    )
    ruta_fp = (
        processed
        / "fp1356_cartera_economica_mensual_v2.csv"
    )

    h10 = preparar_historico(
        leer_csv(ruta_h10, ["fecha_cartera"])
    )
    fp = leer_csv(ruta_fp, ["fecha_cartera"])

    tabla_filas = construir_tabla_filas(h10)
    tabla_auditada, relaciones = detectar_jerarquia(
        tabla_filas
    )
    hojas = aplicar_hojas_finales(
        h10,
        tabla_auditada,
    )

    total_fp, objetivos = preparar_fp1356(fp)
    comparacion, ranking = reconciliar(
        h10,
        hojas,
        total_fp,
        objetivos,
    )
    control_periodo = control_por_periodo(
        tabla_auditada
    )

    resumen_general = pd.DataFrame(
        [
            {
                "filas_unicas_iniciales": len(tabla_filas),
                "subtotales_jerarquicos_detectados": int(
                    tabla_auditada[
                        "es_subtotal_jerarquico"
                    ].sum()
                ),
                "filas_hoja_final": int(
                    tabla_auditada["activo_jerarquia"].sum()
                ),
                "reduccion_pct": (
                    (
                        len(tabla_filas)
                        - tabla_auditada[
                            "activo_jerarquia"
                        ].sum()
                    )
                    / len(tabla_filas)
                    * 100.0
                ),
                "relaciones_padre_hijos": len(relaciones),
                "periodos": tabla_auditada["periodo"].nunique(),
            }
        ]
    )

    rutas = {
        "filas": (
            processed
            / "ca0001_hoja10_auditoria_jerarquia_filas.csv"
        ),
        "relaciones": (
            processed
            / "ca0001_hoja10_auditoria_relaciones_padre_hijos.csv"
        ),
        "hojas": (
            processed
            / "ca0001_hoja10_hojas_jerarquia_auditoria.csv"
        ),
        "comparacion": (
            processed
            / "ca0001_hoja10_reconciliacion_jerarquia.csv"
        ),
        "ranking": (
            processed
            / "ca0001_hoja10_ranking_jerarquia.csv"
        ),
        "control_periodo": (
            processed
            / "ca0001_hoja10_control_jerarquia_por_periodo.csv"
        ),
        "resumen": (
            processed
            / "ca0001_hoja10_resumen_jerarquia.csv"
        ),
    }

    tabla_auditada.to_csv(
        rutas["filas"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    relaciones.to_csv(
        rutas["relaciones"],
        index=False,
        encoding="utf-8-sig",
    )
    hojas.to_csv(
        rutas["hojas"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    comparacion.to_csv(
        rutas["comparacion"],
        index=False,
        encoding="utf-8-sig",
    )
    ranking.to_csv(
        rutas["ranking"],
        index=False,
        encoding="utf-8-sig",
    )
    control_periodo.to_csv(
        rutas["control_periodo"],
        index=False,
        encoding="utf-8-sig",
    )
    resumen_general.to_csv(
        rutas["resumen"],
        index=False,
        encoding="utf-8-sig",
    )

    print("\nAUDITORÍA JERÁRQUICA DE LA HOJA 10")
    print("=" * 118)

    print("\nRESUMEN DE DEPURACIÓN JERÁRQUICA")
    print("-" * 118)
    print(resumen_general.to_string(index=False))

    print("\nRANKING DE RECONCILIACIÓN ANTES Y DESPUÉS")
    print("-" * 118)
    print(
        ranking[
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

    print("\nRELACIONES PADRE–HIJOS DE MAYOR MONTO")
    print("-" * 118)

    if relaciones.empty:
        print("No se detectaron relaciones jerárquicas.")
    else:
        print(
            relaciones.sort_values(
                "monto_vector_padre",
                ascending=False,
            )[
                [
                    "periodo",
                    "archivo",
                    "iteracion",
                    "fila_padre",
                    "nombre_padre",
                    "numero_hijos_activos",
                    "filas_hijas",
                    "error_relativo_vector",
                    "monto_vector_padre",
                ]
            ]
            .head(40)
            .to_string(index=False)
        )

    print("\nCONTROL DE PERIODOS CON MÁS SUBTOTALES")
    print("-" * 118)
    print(
        control_periodo.sort_values(
            "subtotales_jerarquicos",
            ascending=False,
        )
        .head(30)
        .to_string(index=False)
    )

    print("\nArchivos creados:")
    for ruta in rutas.values():
        print(f" - {ruta.resolve()}")

    print(
        "\nCriterio de lectura:\n"
        "- El programa identifica una fila padre cuando su vector de las "
        "cuatro AFP coincide con la suma de las filas hijas posteriores.\n"
        "- La regla se aplica de abajo hacia arriba y en varias iteraciones, "
        "por lo que puede detectar fondo, vehículo y administradora como "
        "niveles sucesivos de una misma inversión.\n"
        "- Las filas padre se marcan como subtotales; no se borran de la "
        "auditoría, pero se excluyen de la base provisional de hojas.\n"
        "- El resultado es favorable si el ratio frente a total_exterior "
        "pasa de aproximadamente 2,0 a aproximadamente 1,0 y el error "
        "mediano cae de forma sustancial.\n"
        "- Esta salida todavía es de auditoría. No reemplaza la base "
        "histórica hasta validar la reconciliación."
    )


if __name__ == "__main__":
    main()
