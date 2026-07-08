from __future__ import annotations

import hashlib
import re
from pathlib import Path

import numpy as np
import pandas as pd


TOLERANCIA_VALOR = 1e-6
TOLERANCIA_PESOS = 1e-8

CONFIANZAS_AUTO = {"alta", "media_alta"}


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


def limpiar_texto(valor: object) -> str:
    if pd.isna(valor):
        return ""
    return re.sub(r"\s+", " ", str(valor)).strip()


def normalizar_codigo(valor: object) -> str:
    return limpiar_texto(valor).upper().replace(" ", "")


def normalizar_nombre(valor: object) -> str:
    texto = limpiar_texto(valor).upper()
    texto = re.sub(r"[^A-Z0-9]+", " ", texto)
    return re.sub(r"\s+", " ", texto).strip()


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


def conjuntos_desde_campo(valor: object) -> set[str]:
    texto = limpiar_texto(valor)

    if not texto:
        return set()

    partes = re.split(r"\s*\|\s*", texto)

    return {
        normalizar_nombre(x)
        for x in partes
        if normalizar_nombre(x)
    }


def interseccion_campos(
    valor_a: object,
    valor_b: object,
) -> bool:
    conjunto_a = conjuntos_desde_campo(valor_a)
    conjunto_b = conjuntos_desde_campo(valor_b)

    return bool(conjunto_a & conjunto_b)


def crear_id_privado(nombre: str) -> str:
    normalizado = normalizar_nombre(nombre)
    digest = hashlib.sha1(
        normalizado.encode("utf-8")
    ).hexdigest()[:16].upper()
    return f"PRIVATE::{digest}"


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
        "isin",
        "identificador_final",
        "tipo_identificador",
        "afp",
        "entidad_administradora",
        "moneda",
        "estado_cobertura",
    ]:
        if columna not in salida.columns:
            salida[columna] = ""
        salida[columna] = salida[columna].map(limpiar_texto)

    salida["isin_original"] = salida["isin"].map(
        normalizar_codigo
    )

    for columna in [
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
    ]:
        if columna not in salida.columns:
            salida[columna] = np.nan
        salida[columna] = pd.to_numeric(
            salida[columna],
            errors="coerce",
        )

    salida["usar_modelo_principal"] = convertir_booleano(
        salida["usar_modelo_principal"]
    )
    salida["usar_analisis_ampliado"] = convertir_booleano(
        salida["usar_analisis_ampliado"]
    )

    return salida


def preparar_universo(df: pd.DataFrame) -> pd.DataFrame:
    salida = df.copy()

    salida["isin_normalizado"] = salida[
        "isin_normalizado"
    ].map(normalizar_codigo)

    for columna in [
        "gestora_reportada",
        "moneda_reportada",
        "lista_afp",
        "clasificacion_identificador",
    ]:
        if columna not in salida.columns:
            salida[columna] = ""
        salida[columna] = salida[columna].map(limpiar_texto)

    for columna in [
        "peso_max_total_fondo_pct",
        "meses_presentes",
    ]:
        if columna not in salida.columns:
            salida[columna] = np.nan
        salida[columna] = pd.to_numeric(
            salida[columna],
            errors="coerce",
        )

    return salida


def preparar_canonicos(df: pd.DataFrame) -> pd.DataFrame:
    salida = df.copy()

    salida["isin"] = salida["isin"].map(
        normalizar_codigo
    )

    for columna in [
        "canonical_security_id",
        "ticker",
        "name",
        "securityType",
        "securityType2",
        "marketSector",
        "exchCode",
        "figi",
        "compositeFIGI",
        "shareClassFIGI",
        "clase_ambiguedad",
        "razon_ambiguedad",
    ]:
        if columna not in salida.columns:
            salida[columna] = ""
        salida[columna] = salida[columna].map(limpiar_texto)

    if "mapeo_aceptable_automatico" not in salida.columns:
        salida["mapeo_aceptable_automatico"] = False
    salida["mapeo_aceptable_automatico"] = convertir_booleano(
        salida["mapeo_aceptable_automatico"]
    )

    return salida


def preparar_correcciones(df: pd.DataFrame) -> pd.DataFrame:
    salida = df.copy()

    if salida.empty:
        return salida

    salida["identificador_original"] = salida[
        "identificador_original"
    ].map(normalizar_codigo)
    salida["isin_corregido_propuesto"] = salida[
        "isin_corregido_propuesto"
    ].map(normalizar_codigo)

    for columna in [
        "confianza_correccion",
        "gestora_reportada",
        "lista_afp",
        "ticker_corregido",
        "nombre_corregido",
        "figi_corregido",
    ]:
        if columna not in salida.columns:
            salida[columna] = ""
        salida[columna] = salida[columna].map(limpiar_texto)

    for columna in [
        "correccion_resuelta_openfigi",
        "corregido_ya_existe_en_universo",
    ]:
        if columna not in salida.columns:
            salida[columna] = False
        salida[columna] = convertir_booleano(
            salida[columna]
        )

    for columna in [
        "peso_max_total_fondo_pct",
        "meses_presentes",
    ]:
        if columna not in salida.columns:
            salida[columna] = np.nan
        salida[columna] = pd.to_numeric(
            salida[columna],
            errors="coerce",
        )

    return salida


def evaluar_correcciones_medias(
    correcciones: pd.DataFrame,
    universo: pd.DataFrame,
    base: pd.DataFrame,
) -> pd.DataFrame:
    if correcciones.empty:
        return correcciones

    salida = correcciones.copy()

    universo_idx = universo.set_index(
        "isin_normalizado",
        drop=False,
    )

    filas = []

    for _, fila in salida.iterrows():
        original = fila["identificador_original"]
        corregido = fila["isin_corregido_propuesto"]
        confianza = fila["confianza_correccion"]

        orig_u = (
            universo_idx.loc[original]
            if original in universo_idx.index
            else None
        )
        corr_u = (
            universo_idx.loc[corregido]
            if corregido in universo_idx.index
            else None
        )

        match_gestora = False
        match_moneda = False
        match_afp = False

        if orig_u is not None and corr_u is not None:
            match_gestora = interseccion_campos(
                orig_u["gestora_reportada"],
                corr_u["gestora_reportada"],
            )
            match_moneda = interseccion_campos(
                orig_u["moneda_reportada"],
                corr_u["moneda_reportada"],
            )
            match_afp = interseccion_campos(
                orig_u["lista_afp"],
                corr_u["lista_afp"],
            )

        b_original = base[
            base["isin_original"].eq(original)
        ][
            [
                "periodo",
                "afp",
                "valor_reconciliado_miles_soles",
            ]
        ].copy()

        b_corregido = base[
            base["isin_original"].eq(corregido)
        ][
            [
                "periodo",
                "afp",
                "valor_reconciliado_miles_soles",
            ]
        ].copy()

        coincidencias = b_original.merge(
            b_corregido,
            on=["periodo", "afp"],
            how="inner",
            suffixes=("_original", "_corregido"),
        )

        meses_colision = len(coincidencias)

        if coincidencias.empty:
            colisiones_compatibles = True
        else:
            diferencia = (
                coincidencias[
                    "valor_reconciliado_miles_soles_original"
                ]
                - coincidencias[
                    "valor_reconciliado_miles_soles_corregido"
                ]
            ).abs()

            escala = coincidencias[
                [
                    "valor_reconciliado_miles_soles_original",
                    "valor_reconciliado_miles_soles_corregido",
                ]
            ].abs().max(axis=1).clip(lower=1.0)

            colisiones_compatibles = bool(
                (diferencia / escala <= 1e-6).all()
            )

        señales_metadata = sum(
            [match_gestora, match_moneda, match_afp]
        )

        aprobada = False
        razon = ""

        if confianza in CONFIANZAS_AUTO:
            aprobada = bool(
                fila["correccion_resuelta_openfigi"]
            )
            razon = (
                "checksum_y_openfigi_confirmados"
                if aprobada
                else "confianza_alta_sin_confirmacion_openfigi"
            )

        elif confianza == "media":
            aprobada = bool(
                fila["corregido_ya_existe_en_universo"]
                and señales_metadata >= 2
                and colisiones_compatibles
            )
            razon = (
                "codigo_existente_y_metadata_compatible"
                if aprobada
                else "evidencia_interna_insuficiente"
            )

        elif confianza == "baja":
            aprobada = False
            razon = "texto_no_isin_o_correccion_no_confirmada"

        else:
            aprobada = False
            razon = "confianza_no_clasificada"

        filas.append(
            {
                **fila.to_dict(),
                "match_gestora": match_gestora,
                "match_moneda": match_moneda,
                "match_afp": match_afp,
                "senales_metadata": señales_metadata,
                "meses_colision_original_corregido": (
                    meses_colision
                ),
                "colisiones_compatibles": (
                    colisiones_compatibles
                ),
                "correccion_aprobada": aprobada,
                "razon_decision": razon,
            }
        )

    return pd.DataFrame(filas)


def construir_mapa_correcciones(
    decisiones: pd.DataFrame,
) -> dict[str, str]:
    if decisiones.empty:
        return {}

    aprobadas = decisiones[
        decisiones["correccion_aprobada"]
    ]

    return dict(
        zip(
            aprobadas["identificador_original"],
            aprobadas["isin_corregido_propuesto"],
        )
    )


def construir_maestro(
    universo: pd.DataFrame,
    canonicos: pd.DataFrame,
    decisiones: pd.DataFrame,
) -> pd.DataFrame:
    mapa = construir_mapa_correcciones(decisiones)

    maestro = universo.copy()
    maestro["identificador_original"] = maestro[
        "isin_normalizado"
    ]
    maestro["identificador_canonico"] = maestro[
        "identificador_original"
    ].map(
        lambda x: mapa.get(x, x)
    )
    maestro["fue_corregido_checksum"] = (
        maestro["identificador_original"]
        != maestro["identificador_canonico"]
    )

    decision_cols = [
        "identificador_original",
        "isin_corregido_propuesto",
        "confianza_correccion",
        "correccion_aprobada",
        "razon_decision",
        "ticker_corregido",
        "nombre_corregido",
        "figi_corregido",
    ]

    if decisiones.empty:
        decisiones_join = pd.DataFrame(
            columns=decision_cols
        )
    else:
        decisiones_join = decisiones[
            decision_cols
        ].copy()

    maestro = maestro.merge(
        decisiones_join,
        on="identificador_original",
        how="left",
        validate="one_to_one",
    )

    canon_cols = [
        "isin",
        "canonical_security_id",
        "ticker",
        "name",
        "securityType",
        "securityType2",
        "marketSector",
        "exchCode",
        "figi",
        "compositeFIGI",
        "shareClassFIGI",
        "clase_ambiguedad",
        "razon_ambiguedad",
        "mapeo_aceptable_automatico",
    ]

    maestro = maestro.merge(
        canonicos[canon_cols],
        left_on="identificador_canonico",
        right_on="isin",
        how="left",
        validate="many_to_one",
    )

    mascara_fallback = (
        maestro["fue_corregido_checksum"]
        & maestro["canonical_security_id"]
        .fillna("")
        .eq("")
        & maestro["figi_corregido"]
        .fillna("")
        .ne("")
    )

    maestro.loc[
        mascara_fallback,
        "canonical_security_id",
    ] = maestro.loc[
        mascara_fallback,
        "figi_corregido",
    ]
    maestro.loc[
        mascara_fallback,
        "ticker",
    ] = maestro.loc[
        mascara_fallback,
        "ticker_corregido",
    ]
    maestro.loc[
        mascara_fallback,
        "name",
    ] = maestro.loc[
        mascara_fallback,
        "nombre_corregido",
    ]
    maestro.loc[
        mascara_fallback,
        "mapeo_aceptable_automatico",
    ] = True
    maestro.loc[
        mascara_fallback,
        "clase_ambiguedad",
    ] = "corregido_checksum_openfigi"
    maestro.loc[
        mascara_fallback,
        "razon_ambiguedad",
    ] = "checksum_corregido_y_figi_confirmado"

    # Normalizar explícitamente las condiciones a booleanos puros.
    # Después de los merges, pandas puede dejar estas columnas con dtype
    # object por la presencia de valores nulos. np.select exige arreglos
    # booleanos y no acepta Series object aunque contengan True/False.
    maestro["fue_corregido_checksum"] = convertir_booleano(
        maestro["fue_corregido_checksum"]
    )
    maestro["mapeo_aceptable_automatico"] = convertir_booleano(
        maestro["mapeo_aceptable_automatico"]
    )

    condicion_corregido = (
        maestro["fue_corregido_checksum"]
        & maestro["mapeo_aceptable_automatico"]
    ).to_numpy(dtype=bool)

    condicion_openfigi = (
        maestro["mapeo_aceptable_automatico"]
    ).to_numpy(dtype=bool)

    condicion_no_estandar = (
        maestro["clasificacion_identificador"]
        .eq("identificador_no_estandar")
        .fillna(False)
        .to_numpy(dtype=bool)
    )

    condicion_checksum_pendiente = (
        maestro["clasificacion_identificador"]
        .eq("formato_isin_checksum_invalido")
        .fillna(False)
        .to_numpy(dtype=bool)
    )

    maestro["estado_identidad_final"] = np.select(
        [
            condicion_corregido,
            condicion_openfigi,
            condicion_no_estandar,
            condicion_checksum_pendiente,
        ],
        [
            "checksum_corregido_validado",
            "openfigi_validado",
            "identificador_privado_o_no_estandar",
            "checksum_invalido_pendiente",
        ],
        default="isin_no_resuelto",
    )

    maestro["usar_en_enriquecimiento_automatico"] = (
        maestro["estado_identidad_final"].isin(
            [
                "openfigi_validado",
                "checksum_corregido_validado",
            ]
        )
    )

    return maestro.drop(
        columns=["isin"],
        errors="ignore",
    )


def aplicar_maestro_a_base(
    base: pd.DataFrame,
    maestro: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    mapa = maestro[
        [
            "identificador_original",
            "identificador_canonico",
            "canonical_security_id",
            "ticker",
            "name",
            "securityType",
            "securityType2",
            "marketSector",
            "exchCode",
            "estado_identidad_final",
            "usar_en_enriquecimiento_automatico",
            "fue_corregido_checksum",
        ]
    ].copy()

    salida = base.merge(
        mapa,
        left_on="isin_original",
        right_on="identificador_original",
        how="left",
        validate="many_to_one",
    )

    es_privado = salida["tipo_identificador"].eq(
        "fondo_sin_isin"
    )

    salida.loc[
        es_privado,
        "identificador_canonico",
    ] = salida.loc[
        es_privado,
        "identificador_final",
    ]
    salida.loc[
        es_privado,
        "canonical_security_id",
    ] = salida.loc[
        es_privado,
        "identificador_final",
    ].map(crear_id_privado)
    salida.loc[
        es_privado,
        "name",
    ] = salida.loc[
        es_privado,
        "identificador_final",
    ]
    salida.loc[
        es_privado,
        "estado_identidad_final",
    ] = "fondo_privado_sin_isin"
    salida.loc[
        es_privado,
        "usar_en_enriquecimiento_automatico",
    ] = False
    salida.loc[
        es_privado,
        "fue_corregido_checksum",
    ] = False

    salida["identificador_agregacion"] = np.where(
        salida["canonical_security_id"]
        .fillna("")
        .astype(str)
        .ne(""),
        salida["canonical_security_id"],
        salida["identificador_canonico"],
    )

    claves_colision = [
        "periodo",
        "afp",
        "identificador_agregacion",
    ]

    colisiones = (
        salida.groupby(
            claves_colision,
            dropna=False,
            as_index=False,
        )
        .agg(
            filas_origen=("identificador_final", "size"),
            identificadores_originales=(
                "isin_original",
                lambda s: " | ".join(
                    sorted(
                        {
                            limpiar_texto(x)
                            for x in s
                            if limpiar_texto(x)
                        }
                    )
                ),
            ),
            valores_origen=(
                "valor_reconciliado_miles_soles",
                lambda s: " | ".join(
                    f"{float(x):.6f}"
                    for x in s
                    if pd.notna(x)
                ),
            ),
        )
    )

    colisiones = colisiones[
        colisiones["filas_origen"] > 1
    ].copy()

    columnas_constantes = [
        "fecha_cartera",
        "archivo",
        "estado_cobertura",
        "factor_reescala",
        "error_cobertura_pct",
        "total_exterior_miles_soles",
        "total_fondo_miles_soles",
        "usar_modelo_principal",
        "usar_analisis_ampliado",
        "identificador_canonico",
        "canonical_security_id",
        "ticker",
        "name",
        "securityType",
        "securityType2",
        "marketSector",
        "exchCode",
        "estado_identidad_final",
        "usar_en_enriquecimiento_automatico",
        "tipo_identificador",
        "entidad_administradora",
        "moneda",
    ]

    agg = {
        columna: "first"
        for columna in columnas_constantes
        if columna in salida.columns
    }

    for columna in [
        "valor",
        "valor_reconciliado_miles_soles",
        "peso_exterior_reconciliado",
        "peso_total_fondo_reconciliado",
        "peso_exterior_reconciliado_pct",
        "peso_total_fondo_reconciliado_pct",
    ]:
        if columna in salida.columns:
            agg[columna] = "sum"

    agg["identificador_final"] = (
        lambda s: " | ".join(
            sorted(
                {
                    limpiar_texto(x)
                    for x in s
                    if limpiar_texto(x)
                }
            )
        )
    )
    agg["isin_original"] = (
        lambda s: " | ".join(
            sorted(
                {
                    limpiar_texto(x)
                    for x in s
                    if limpiar_texto(x)
                }
            )
        )
    )
    agg["fue_corregido_checksum"] = "max"

    agregada = (
        salida.groupby(
            claves_colision,
            dropna=False,
            as_index=False,
        )
        .agg(agg)
    )

    return agregada, colisiones


def controlar_pesos(
    base_original: pd.DataFrame,
    base_final: pd.DataFrame,
) -> pd.DataFrame:
    original = (
        base_original.groupby(
            ["periodo", "afp"],
            as_index=False,
        )
        .agg(
            peso_exterior_original=(
                "peso_exterior_reconciliado",
                "sum",
            ),
            peso_fondo_original=(
                "peso_total_fondo_reconciliado",
                "sum",
            ),
        )
    )

    final = (
        base_final.groupby(
            ["periodo", "afp"],
            as_index=False,
        )
        .agg(
            peso_exterior_final=(
                "peso_exterior_reconciliado",
                "sum",
            ),
            peso_fondo_final=(
                "peso_total_fondo_reconciliado",
                "sum",
            ),
        )
    )

    control = original.merge(
        final,
        on=["periodo", "afp"],
        how="outer",
        validate="one_to_one",
    )

    control["diferencia_peso_exterior"] = (
        control["peso_exterior_final"]
        - control["peso_exterior_original"]
    )
    control["diferencia_peso_fondo"] = (
        control["peso_fondo_final"]
        - control["peso_fondo_original"]
    )

    control["estado_control"] = np.where(
        control["diferencia_peso_exterior"].abs()
        <= TOLERANCIA_PESOS,
        "correcto",
        "revisar",
    )

    return control


def resumen_final(
    maestro: pd.DataFrame,
    decisiones: pd.DataFrame,
    base_final: pd.DataFrame,
    colisiones: pd.DataFrame,
    control_pesos: pd.DataFrame,
) -> pd.DataFrame:
    filas = []

    for estado, grupo in maestro.groupby(
        "estado_identidad_final",
        dropna=False,
    ):
        filas.append(
            {
                "seccion": "identidades",
                "categoria": estado,
                "cantidad": grupo[
                    "identificador_original"
                ].nunique(),
                "detalle": (
                    f"peso máximo: "
                    f"{grupo['peso_max_total_fondo_pct'].max():.6f}%"
                ),
            }
        )

    if not decisiones.empty:
        for aprobado, grupo in decisiones.groupby(
            "correccion_aprobada"
        ):
            filas.append(
                {
                    "seccion": "correcciones",
                    "categoria": (
                        "aprobadas"
                        if aprobado
                        else "pendientes"
                    ),
                    "cantidad": len(grupo),
                    "detalle": "decisiones de checksum",
                }
            )

    filas.extend(
        [
            {
                "seccion": "base_final",
                "categoria": "registros",
                "cantidad": len(base_final),
                "detalle": "AFP-mes-identificador canónico",
            },
            {
                "seccion": "base_final",
                "categoria": "colisiones_agregadas",
                "cantidad": len(colisiones),
                "detalle": (
                    "grupos con más de una fila de origen"
                ),
            },
            {
                "seccion": "control",
                "categoria": "periodos_pesos_correctos",
                "cantidad": int(
                    control_pesos[
                        "estado_control"
                    ].eq("correcto").sum()
                ),
                "detalle": (
                    f"de {len(control_pesos)} combinaciones AFP-mes"
                ),
            },
        ]
    )

    return pd.DataFrame(filas)


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
    universo = preparar_universo(
        leer_csv(
            processed
            / "ca0001_isin_universo_priorizado.csv",
            ["primera_fecha", "ultima_fecha"],
        )
    )
    canonicos = preparar_canonicos(
        leer_csv(
            processed
            / "ca0001_isin_openfigi_mapeo_canonico.csv"
        )
    )
    correcciones = preparar_correcciones(
        leer_csv(
            processed
            / "ca0001_isin_correcciones_checksum_propuestas.csv"
        )
    )

    decisiones = evaluar_correcciones_medias(
        correcciones,
        universo,
        base,
    )

    maestro = construir_maestro(
        universo,
        canonicos,
        decisiones,
    )

    base_final, colisiones = aplicar_maestro_a_base(
        base,
        maestro,
    )

    control_pesos = controlar_pesos(
        base,
        base_final,
    )

    pendientes = maestro[
        ~maestro["usar_en_enriquecimiento_automatico"]
    ].copy()

    resumen = resumen_final(
        maestro,
        decisiones,
        base_final,
        colisiones,
        control_pesos,
    )

    rutas = {
        "decisiones": (
            processed
            / "ca0001_identificadores_decisiones_checksum.csv"
        ),
        "aprobadas": (
            processed
            / "ca0001_identificadores_correcciones_aprobadas.csv"
        ),
        "pendientes_correccion": (
            processed
            / "ca0001_identificadores_correcciones_pendientes.csv"
        ),
        "maestro": (
            processed
            / "ca0001_maestro_identificadores_canonico_final.csv"
        ),
        "base_final": (
            processed
            / "ca0001_base_identificadores_canonica_final.csv"
        ),
        "colisiones": (
            processed
            / "ca0001_base_identificadores_colisiones.csv"
        ),
        "pendientes": (
            processed
            / "ca0001_identificadores_pendientes_finales.csv"
        ),
        "control_pesos": (
            processed
            / "ca0001_base_identificadores_control_pesos.csv"
        ),
        "resumen": (
            processed
            / "ca0001_identificadores_resumen_final.csv"
        ),
    }

    decisiones.to_csv(
        rutas["decisiones"],
        index=False,
        encoding="utf-8-sig",
    )
    decisiones[
        decisiones["correccion_aprobada"]
    ].to_csv(
        rutas["aprobadas"],
        index=False,
        encoding="utf-8-sig",
    )
    decisiones[
        ~decisiones["correccion_aprobada"]
    ].to_csv(
        rutas["pendientes_correccion"],
        index=False,
        encoding="utf-8-sig",
    )
    maestro.to_csv(
        rutas["maestro"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    base_final.to_csv(
        rutas["base_final"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    colisiones.to_csv(
        rutas["colisiones"],
        index=False,
        encoding="utf-8-sig",
    )
    pendientes.to_csv(
        rutas["pendientes"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    control_pesos.to_csv(
        rutas["control_pesos"],
        index=False,
        encoding="utf-8-sig",
    )
    resumen.to_csv(
        rutas["resumen"],
        index=False,
        encoding="utf-8-sig",
    )

    print("\nCONSOLIDACIÓN FINAL DE IDENTIFICADORES TERMINADA")
    print("=" * 118)

    print("\nDECISIONES DE CORRECCIÓN DE CHECKSUM")
    print("-" * 118)

    if decisiones.empty:
        print("No existían correcciones propuestas.")
    else:
        print(
            decisiones.groupby(
                [
                    "confianza_correccion",
                    "correccion_aprobada",
                    "razon_decision",
                ],
                as_index=False,
            )
            .size()
            .rename(columns={"size": "identificadores"})
            .to_string(index=False)
        )

    print("\nRESUMEN DE IDENTIDADES FINALES")
    print("-" * 118)
    print(
        maestro.groupby(
            "estado_identidad_final",
            as_index=False,
        )
        .agg(
            identificadores=(
                "identificador_original",
                "nunique",
            ),
            peso_maximo_pct=(
                "peso_max_total_fondo_pct",
                "max",
            ),
            meses_mediana=("meses_presentes", "median"),
        )
        .sort_values(
            "identificadores",
            ascending=False,
        )
        .to_string(index=False)
    )

    print("\nCONTROL DE PESOS DESPUÉS DE CONSOLIDAR")
    print("-" * 118)
    print(
        control_pesos["estado_control"]
        .value_counts(dropna=False)
        .rename_axis("estado")
        .reset_index(name="observaciones")
        .to_string(index=False)
    )

    print("\nCOLISIONES GENERADAS POR LA CANONIZACIÓN")
    print("-" * 118)
    print(f"Grupos con más de una fila de origen: {len(colisiones)}")

    if not colisiones.empty:
        print(
            colisiones.sort_values(
                "filas_origen",
                ascending=False,
            )
            .head(30)
            .to_string(index=False)
        )

    print("\nTOP FINAL DE IDENTIFICADORES CANÓNICOS")
    print("-" * 118)
    print(
        base_final.sort_values(
            "peso_total_fondo_reconciliado_pct",
            ascending=False,
        )[
            [
                "periodo",
                "afp",
                "identificador_agregacion",
                "identificador_canonico",
                "ticker",
                "name",
                "estado_identidad_final",
                "peso_total_fondo_reconciliado_pct",
                "estado_cobertura",
            ]
        ]
        .head(40)
        .to_string(index=False)
    )

    print("\nPENDIENTES DE IDENTIDAD DE MAYOR PESO")
    print("-" * 118)

    if pendientes.empty:
        print("No quedaron identificadores pendientes.")
    else:
        print(
            pendientes.sort_values(
                "peso_max_total_fondo_pct",
                ascending=False,
            )[
                [
                    "identificador_original",
                    "identificador_canonico",
                    "estado_identidad_final",
                    "gestora_reportada",
                    "moneda_reportada",
                    "peso_max_total_fondo_pct",
                    "meses_presentes",
                    "lista_afp",
                ]
            ]
            .head(40)
            .to_string(index=False)
        )

    print("\nArchivos creados:")
    for ruta in rutas.values():
        print(f" - {ruta.resolve()}")

    print(
        "\nCriterio metodológico final:\n"
        "- Las correcciones de confianza alta y media-alta se aplican solo "
        "cuando OpenFIGI confirma el ISIN corregido.\n"
        "- Las correcciones de confianza media se aplican únicamente si el "
        "código corregido ya existe en la serie, la metadata coincide y no "
        "aparecen colisiones incompatibles.\n"
        "- Los nombres de empresas que accidentalmente tienen 12 caracteres "
        "no se convierten en ISIN.\n"
        "- La consolidación agrega exposiciones que terminan en la misma "
        "identidad canónica, conservando el control de sus filas de origen.\n"
        "- Los pesos deben permanecer exactamente iguales antes y después "
        "de la canonización.\n"
        "- Solo los estados openfigi_validado y "
        "checksum_corregido_validado pasan automáticamente al posterior "
        "enriquecimiento de país, sector e índice."
    )


if __name__ == "__main__":
    main()
