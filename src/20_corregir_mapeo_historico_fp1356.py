from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd


AFPS = ["Habitat", "Integra", "Prima", "Profuturo"]


def normalizar(valor: object) -> str:
    if pd.isna(valor):
        return ""

    texto = str(valor).strip().lower()
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(
        caracter
        for caracter in texto
        if not unicodedata.combining(caracter)
    )
    return re.sub(r"\s+", " ", texto)


def convertir_bool(serie: pd.Series) -> pd.Series:
    if serie.dtype == bool:
        return serie

    return (
        serie.astype(str)
        .str.strip()
        .str.lower()
        .isin({"true", "1", "si", "sí", "yes"})
    )


def contiene_alguno(texto: str, terminos: list[str]) -> bool:
    return any(termino in texto for termino in terminos)


def es_total_o_control(fila: pd.Series) -> bool:
    nivel_1 = normalizar(fila.get("nivel_1", ""))
    descripcion = normalizar(fila.get("descripcion", ""))
    ruta = normalizar(fila.get("ruta_jerarquica", ""))

    return (
        nivel_1 == "total"
        or ruta.startswith("total >")
        or descripcion in {"fondo de pensiones", "encaje legal"}
    )


def contexto_fila(fila: pd.Series) -> str:
    partes = [
        normalizar(fila.get("nivel_1", "")),
        normalizar(fila.get("nivel_2", "")),
        normalizar(fila.get("nivel_3", "")),
        normalizar(fila.get("ruta_jerarquica", "")),
    ]
    return " | ".join(parte for parte in partes if parte)


def resultado(
    categoria: str,
    factor: str,
    calidad: str,
    regla: str,
) -> tuple[str, str, str, str]:
    return categoria, factor, calidad, regla


def clasificar_categoria(
    fila: pd.Series,
) -> tuple[str, str, str, str]:
    """
    Clasificador compatible con nomenclaturas SBS actuales e históricas.

    Retorna:
      categoria_economica,
      factor_representativo_inicial,
      calidad_proxy_inicial,
      regla_mapeo.
    """
    descripcion = normalizar(fila.get("descripcion", ""))
    contexto = contexto_fila(fila)

    local = "inversiones locales" in contexto
    exterior = "inversiones en el exterior" in contexto
    sistema_financiero = "sistema financiero" in contexto
    no_financiera = "empresas no financieras" in contexto
    administradora_fondos = "administradoras de fondos" in contexto
    titulizadora = "sociedades titulizadoras" in contexto
    gobierno = "gobierno" in contexto

    if contiene_alguno(
        descripcion,
        ["operaciones en transito"],
    ):
        return resultado(
            "operaciones_en_transito",
            "sin_factor_directo",
            "no_aplicable",
            "operaciones_transito",
        )

    # Fondos mutuos y fondos de inversión: etiquetas actuales e históricas.
    if contiene_alguno(
        descripcion,
        [
            "fondos mutuos alternativos del extranjero",
            "fondo mutuo alternativo extranjero",
            "fondo de inversiones alternativos",
        ],
    ):
        return resultado(
            "alternativos_exterior" if exterior else "alternativos_local",
            "proxy_alternativos_pendiente",
            "baja",
            "fondos_alternativos",
        )

    if (
        contiene_alguno(
            descripcion,
            [
                "fondos mutuos del extranjero",
                "cuotas de fondos mutuos",
                "fondos mutuos",
            ],
        )
        and "etf" in descripcion
    ):
        return resultado(
            "etf_exterior_via_mercado_local",
            "ACWI_EEM_QQQ_por_identificar",
            "media",
            "fondos_etf",
        )

    if contiene_alguno(
        descripcion,
        [
            "fondos mutuos del extranjero",
            "cuotas de fondos mutuos",
            "fondos mutuos",
        ],
    ):
        if exterior:
            return resultado(
                "fondos_mutuos_exterior",
                "ACWI",
                "media",
                "fondos_mutuos_exterior_actual_historico",
            )

        if local:
            return resultado(
                "fondos_mutuos_locales",
                "proxy_fondos_locales_pendiente",
                "baja",
                "fondos_mutuos_locales_historico",
            )

    if "fondo mutuo local" in descripcion:
        return resultado(
            "fondos_mutuos_locales",
            "proxy_fondos_locales_pendiente",
            "baja",
            "fondo_mutuo_local",
        )

    if contiene_alguno(
        descripcion,
        [
            "fondo de inversion alternativo",
            "fondo de inversiones alternativos",
        ],
    ):
        return resultado(
            "alternativos_exterior" if exterior else "alternativos_local",
            "proxy_alternativos_pendiente",
            "baja",
            "fondos_inversion_alternativos",
        )

    if contiene_alguno(
        descripcion,
        [
            "fondo de inversion tradicional",
            "cuotas de fondos de inversion",
            "fondos de inversion",
            "bonos de fondos de inversion",
        ],
    ):
        if exterior:
            return resultado(
                "fondos_inversion_exterior",
                "proxy_fondos_exterior_pendiente",
                "baja",
                "fondos_inversion_exterior_actual_historico",
            )

        return resultado(
            "fondos_inversion_local_tradicional",
            "proxy_fondos_locales_pendiente",
            "baja",
            "fondos_inversion_local_actual_historico",
        )

    # Participaciones y titulizaciones.
    if contiene_alguno(
        descripcion,
        [
            "titulos con derecho de participacion",
        ],
    ):
        return resultado(
            "titulizaciones_participacion_local",
            "proxy_activos_alternativos_locales_pendiente",
            "baja",
            "titulizacion_participacion",
        )

    if contiene_alguno(
        descripcion,
        [
            "bonos de titulizacion",
            "papel comercial tit",
        ],
    ):
        return resultado(
            "titulizaciones_deuda_local",
            "proxy_credito_local_pendiente",
            "baja",
            "titulizacion_deuda",
        )

    # Renta variable actual e histórica.
    if contiene_alguno(
        descripcion,
        [
            "acciones y valores representativos sobre acciones",
            "certificados prov. acc.",
            "certificados provisionales de acciones",
            "certificados de suscripcion preferente",
            "acciones de capital por privatizacion",
            "acciones preferentes",
        ],
    ):
        if exterior:
            return resultado(
                "acciones_exterior_directas",
                "ACWI",
                "media",
                "acciones_exterior_actual_historico",
            )

        if sistema_financiero:
            return resultado(
                "acciones_locales_financieras",
                "EPU_financieras_por_identificar",
                "media",
                "acciones_locales_financieras_actual_historico",
            )

        return resultado(
            "acciones_locales_no_financieras",
            "EPU",
            "media",
            "acciones_locales_actual_historico",
        )

    # Deuda soberana local y exterior.
    if contiene_alguno(
        descripcion,
        [
            "bonos del gobierno central",
            "certificados y depositos a plazo del bcrp",
            "letras del tesoro",
            "bonos brady",
        ],
    ):
        return resultado(
            "renta_fija_soberana_local",
            "tasas_soberanas_peru_pendiente",
            "baja",
            "renta_fija_soberana_local",
        )

    if (
        exterior
        and gobierno
        and contiene_alguno(
            descripcion,
            ["titulos de deuda", "bonos", "letras"],
        )
    ):
        return resultado(
            "renta_fija_soberana_exterior",
            "TLT",
            "media",
            "renta_fija_soberana_exterior",
        )

    # Depósitos.
    if contiene_alguno(
        descripcion,
        ["certificados y depositos a plazo"],
    ):
        if exterior:
            return resultado(
                "depositos_exterior",
                "tasas_cortas_usd_fx",
                "baja",
                "depositos_exterior",
            )

        return resultado(
            "depositos_locales",
            "tasas_cortas_pen_pendiente",
            "baja",
            "depositos_locales",
        )

    if "organismos internacionales" in descripcion:
        return resultado(
            "renta_fija_organismos_internacionales",
            "LQD_TLT",
            "baja",
            "organismos_internacionales",
        )

    # Deuda del sistema financiero: etiquetas actuales e históricas.
    if contiene_alguno(
        descripcion,
        [
            "bonos del sistema financiero",
            "bonos subordinados",
            "bonos hipotecarios",
            "bonos de arrendamiento financiero",
            "otros bonos sector financiero",
            "papeles comerciales",
        ],
    ) and (sistema_financiero or "sistema financiero" in descripcion):
        if exterior:
            return resultado(
                "renta_fija_financiera_exterior",
                "LQD_HYG",
                "media",
                "renta_fija_financiera_exterior_actual_historico",
            )

        return resultado(
            "renta_fija_financiera_local",
            "credito_financiero_peru_pendiente",
            "baja",
            "renta_fija_financiera_local_actual_historico",
        )

    # Deuda no financiera: etiquetas actuales e históricas.
    if contiene_alguno(
        descripcion,
        [
            "bonos de empresas no financieras",
            "bonos corporativos",
            "bonos para nuevos proyectos",
            "titulos de deuda emitidos por entidades no financieras",
            "papeles comerciales",
        ],
    ) and (no_financiera or "no financieras" in descripcion or "corporativos" in descripcion):
        if exterior or "del exterior" in descripcion:
            return resultado(
                "renta_fija_no_financiera_exterior",
                "LQD_HYG",
                "media",
                "renta_fija_no_financiera_exterior_actual_historico",
            )

        return resultado(
            "renta_fija_no_financiera_local",
            "credito_corporativo_peru_pendiente",
            "baja",
            "renta_fija_no_financiera_local_actual_historico",
        )

    # Títulos de deuda genéricos usando el contexto disponible.
    if contiene_alguno(
        descripcion,
        [
            "titulos de deuda",
            "bonos",
            "papel comercial",
        ],
    ):
        if titulizadora:
            return resultado(
                "titulizaciones_deuda_local",
                "proxy_credito_local_pendiente",
                "baja",
                "deuda_generica_titulizadora",
            )

        if exterior and sistema_financiero:
            return resultado(
                "renta_fija_financiera_exterior",
                "LQD_HYG",
                "media",
                "deuda_generica_financiera_exterior",
            )

        if local and sistema_financiero:
            return resultado(
                "renta_fija_financiera_local",
                "credito_financiero_peru_pendiente",
                "baja",
                "deuda_generica_financiera_local",
            )

        if exterior and no_financiera:
            return resultado(
                "renta_fija_no_financiera_exterior",
                "LQD_HYG",
                "media",
                "deuda_generica_no_financiera_exterior",
            )

        if local and no_financiera:
            return resultado(
                "renta_fija_no_financiera_local",
                "credito_corporativo_peru_pendiente",
                "baja",
                "deuda_generica_no_financiera_local",
            )

        if exterior:
            return resultado(
                "renta_fija_exterior_otros",
                "LQD_HYG_TLT",
                "baja",
                "deuda_generica_exterior",
            )

        if local:
            return resultado(
                "renta_fija_local_otros",
                "proxy_renta_fija_local_pendiente",
                "baja",
                "deuda_generica_local",
            )

    if contiene_alguno(
        descripcion,
        [
            "otros instrumentos autorizados",
        ],
    ):
        return resultado(
            "otros_instrumentos_autorizados",
            "sin_proxy",
            "no_disponible",
            "otros_instrumentos_autorizados",
        )

    return resultado(
        "otros_no_mapeados",
        "sin_proxy",
        "no_disponible",
        "sin_regla",
    )


def preparar_base(ruta: Path) -> pd.DataFrame:
    if not ruta.exists():
        raise FileNotFoundError(f"No existe: {ruta}")

    base = pd.read_csv(
        ruta,
        parse_dates=["fecha_cartera"],
    )

    requeridas = {
        "fecha_cartera",
        "afp",
        "nivel_1",
        "nivel_2",
        "nivel_3",
        "descripcion",
        "ruta_jerarquica",
        "participacion_pct",
        "monto_miles_soles",
        "es_hoja",
    }

    faltantes = requeridas - set(base.columns)
    if faltantes:
        raise ValueError(
            f"Faltan columnas: {sorted(faltantes)}"
        )

    base["participacion_pct"] = pd.to_numeric(
        base["participacion_pct"],
        errors="coerce",
    )
    base["monto_miles_soles"] = pd.to_numeric(
        base["monto_miles_soles"],
        errors="coerce",
    )
    base["es_hoja"] = convertir_bool(base["es_hoja"])

    for columna in [
        "nivel_1",
        "nivel_2",
        "nivel_3",
        "descripcion",
        "ruta_jerarquica",
    ]:
        base[columna] = (
            base[columna]
            .fillna("")
            .astype(str)
            .str.strip()
        )

    return base


def seleccionar_componentes(base: pd.DataFrame) -> pd.DataFrame:
    componentes = base[
        base["es_hoja"]
        & base["participacion_pct"].notna()
    ].copy()

    mascara_control = componentes.apply(
        es_total_o_control,
        axis=1,
    )
    componentes = componentes[~mascara_control].copy()

    clasificaciones = componentes.apply(
        clasificar_categoria,
        axis=1,
        result_type="expand",
    )
    clasificaciones.columns = [
        "categoria_economica",
        "factor_representativo_inicial",
        "calidad_proxy_inicial",
        "regla_mapeo",
    ]

    return pd.concat(
        [
            componentes.reset_index(drop=True),
            clasificaciones.reset_index(drop=True),
        ],
        axis=1,
    )


def agregar_mensual(
    componentes: pd.DataFrame,
) -> pd.DataFrame:
    mensual = (
        componentes.groupby(
            [
                "fecha_cartera",
                "afp",
                "categoria_economica",
                "factor_representativo_inicial",
                "calidad_proxy_inicial",
            ],
            as_index=False,
            dropna=False,
        )
        .agg(
            monto_miles_soles=("monto_miles_soles", "sum"),
            participacion_pct=("participacion_pct", "sum"),
            instrumentos=("descripcion", "nunique"),
        )
    )

    return mensual.sort_values(
        ["fecha_cartera", "afp", "participacion_pct"],
        ascending=[True, True, False],
    )


def crear_control(
    componentes: pd.DataFrame,
) -> pd.DataFrame:
    temporal = componentes.copy()
    temporal["es_no_mapeado"] = (
        temporal["categoria_economica"] == "otros_no_mapeados"
    )

    filas = []

    for (fecha, afp), grupo in temporal.groupby(
        ["fecha_cartera", "afp"],
        sort=True,
    ):
        no_mapeado = grupo.loc[
            grupo["es_no_mapeado"],
            "participacion_pct",
        ]

        suma = float(grupo["participacion_pct"].sum())
        no_mapeado_neto = float(no_mapeado.sum())
        no_mapeado_abs = float(no_mapeado.abs().sum())

        filas.append(
            {
                "fecha_cartera": fecha,
                "afp": afp,
                "suma_componentes_pct": suma,
                "desvio_vs_100_pct": suma - 100.0,
                "participacion_no_mapeada_pct": no_mapeado_neto,
                "participacion_no_mapeada_abs_pct": no_mapeado_abs,
                "numero_componentes": len(grupo),
                "categorias_economicas": grupo[
                    "categoria_economica"
                ].nunique(),
                "estado_suma": (
                    "correcto"
                    if 99.0 <= suma <= 101.0
                    else "revisar"
                ),
                "estado_mapeo": (
                    "correcto"
                    if no_mapeado_abs <= 1.0
                    else "revisar"
                ),
            }
        )

    control = pd.DataFrame(filas)
    control["estado_general"] = np.where(
        (control["estado_suma"] == "correcto")
        & (control["estado_mapeo"] == "correcto"),
        "correcto",
        "revisar",
    )

    return control


def crear_catalogo(
    componentes: pd.DataFrame,
) -> pd.DataFrame:
    return (
        componentes.groupby(
            [
                "nivel_1",
                "nivel_2",
                "nivel_3",
                "descripcion",
                "ruta_jerarquica",
                "categoria_economica",
                "factor_representativo_inicial",
                "calidad_proxy_inicial",
                "regla_mapeo",
            ],
            as_index=False,
            dropna=False,
        )
        .agg(
            primera_fecha=("fecha_cartera", "min"),
            ultima_fecha=("fecha_cartera", "max"),
            meses_presentes=("fecha_cartera", "nunique"),
            afp_presentes=("afp", "nunique"),
            participacion_mediana_pct=(
                "participacion_pct",
                "median",
            ),
            participacion_max_abs_pct=(
                "participacion_pct",
                lambda s: float(pd.Series(s).abs().max()),
            ),
        )
        .sort_values(
            [
                "categoria_economica",
                "participacion_max_abs_pct",
            ],
            ascending=[True, False],
        )
    )


def comparar_con_v1(
    processed: Path,
    control_v2: pd.DataFrame,
) -> pd.DataFrame:
    ruta_v1 = (
        processed / "fp1356_cartera_economica_control.csv"
    )

    if not ruta_v1.exists():
        return pd.DataFrame()

    v1 = pd.read_csv(
        ruta_v1,
        parse_dates=["fecha_cartera"],
    )

    columnas_v1 = [
        "fecha_cartera",
        "afp",
        "participacion_no_mapeada_pct",
        "estado_general",
    ]
    columnas_v1 = [
        columna for columna in columnas_v1 if columna in v1.columns
    ]

    comparacion = v1[columnas_v1].merge(
        control_v2[
            [
                "fecha_cartera",
                "afp",
                "participacion_no_mapeada_abs_pct",
                "estado_general",
            ]
        ],
        on=["fecha_cartera", "afp"],
        how="outer",
        suffixes=("_v1", "_v2"),
    )

    return comparacion


def main() -> None:
    raiz = Path(__file__).resolve().parents[1]
    processed = raiz / "data" / "processed"

    ruta_base = (
        processed / "fp1356_fondo3_cartera_largo.csv"
    )

    base = preparar_base(ruta_base)
    componentes = seleccionar_componentes(base)
    mensual = agregar_mensual(componentes)
    control = crear_control(componentes)
    catalogo = crear_catalogo(componentes)

    no_mapeados = componentes[
        componentes["categoria_economica"]
        == "otros_no_mapeados"
    ].copy()

    comparacion = comparar_con_v1(
        processed,
        control,
    )

    rutas = {
        "detalle": (
            processed / "fp1356_cartera_economica_detalle_v2.csv"
        ),
        "mensual": (
            processed / "fp1356_cartera_economica_mensual_v2.csv"
        ),
        "control": (
            processed / "fp1356_cartera_economica_control_v2.csv"
        ),
        "catalogo": (
            processed / "fp1356_catalogo_mapeo_aplicado_v2.csv"
        ),
        "no_mapeados": (
            processed / "fp1356_cartera_no_mapeada_v2.csv"
        ),
        "comparacion": (
            processed / "fp1356_comparacion_mapeo_v1_v2.csv"
        ),
    }

    componentes.to_csv(
        rutas["detalle"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    mensual.to_csv(
        rutas["mensual"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    control.to_csv(
        rutas["control"],
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
    no_mapeados.to_csv(
        rutas["no_mapeados"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    comparacion.to_csv(
        rutas["comparacion"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )

    ultima_fecha = mensual["fecha_cartera"].max()

    print("\nMAPEO ECONÓMICO HISTÓRICO V2 TERMINADO")
    print("=" * 108)
    print(f"Última fecha: {ultima_fecha.date()}")
    print(f"AFP-mes esperados: {base['fecha_cartera'].nunique() * len(AFPS)}")
    print(f"AFP-mes procesados: {len(control)}")
    print(
        "AFP-mes con control correcto:",
        int((control["estado_general"] == "correcto").sum()),
        "de",
        len(control),
    )
    print(
        "AFP-mes para revisar:",
        int((control["estado_general"] == "revisar").sum()),
    )
    print(
        "Participación no mapeada máxima absoluta:",
        f"{control['participacion_no_mapeada_abs_pct'].max():.6f} %",
    )
    print(
        "Mediana no mapeada absoluta:",
        f"{control['participacion_no_mapeada_abs_pct'].median():.6f} %",
    )

    ultimo = mensual[
        mensual["fecha_cartera"] == ultima_fecha
    ].copy()

    print("\nCOMPOSICIÓN ECONÓMICA V2 DEL ÚLTIMO MES")
    print("-" * 108)

    for afp in AFPS:
        tabla = ultimo[
            ultimo["afp"] == afp
        ].sort_values(
            "participacion_pct",
            ascending=False,
        )

        print(f"\n{afp}")
        print(
            tabla[
                [
                    "categoria_economica",
                    "participacion_pct",
                    "factor_representativo_inicial",
                    "calidad_proxy_inicial",
                ]
            ].to_string(index=False)
        )

    if not no_mapeados.empty:
        print("\nPRINCIPALES DESCRIPCIONES TODAVÍA NO MAPEADAS")
        print("-" * 108)

        resumen = (
            no_mapeados.groupby(
                [
                    "nivel_1",
                    "nivel_2",
                    "descripcion",
                ],
                as_index=False,
            )
            .agg(
                participacion_max_abs_pct=(
                    "participacion_pct",
                    lambda s: float(
                        pd.Series(s).abs().max()
                    ),
                ),
                meses=("fecha_cartera", "nunique"),
            )
            .sort_values(
                "participacion_max_abs_pct",
                ascending=False,
            )
        )

        print(resumen.head(30).to_string(index=False))

    print("\nArchivos creados:")
    for ruta in rutas.values():
        print(f" - {ruta.resolve()}")

    print(
        "\nCriterio para continuar:\n"
        "- Si la participación no mapeada máxima queda por debajo de 1 %, "
        "podemos construir el primer modelo con pesos mensuales.\n"
        "- Si quedan meses por encima de 1 %, deben revisarse las "
        "descripciones todavía no mapeadas antes de modelar.\n"
        "- Este módulo corrige nomenclaturas históricas; no identifica aún "
        "los activos subyacentes de los fondos mutuos extranjeros."
    )


if __name__ == "__main__":
    main()
