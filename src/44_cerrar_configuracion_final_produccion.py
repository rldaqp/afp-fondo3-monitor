from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


AFPS = ["Habitat", "Integra", "Prima", "Profuturo"]

MODELO_BASE = "M0_base_mercado"
MODELO_HIBRIDO = "M2_hibrido"
MODELO_BLEND = "blend_dinamico_M0_M2"

TOLERANCIA = 1e-12


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


def valor_numerico(
    fila: pd.Series,
    columna: str,
    default: float = np.nan,
) -> float:
    valor = pd.to_numeric(
        pd.Series([fila.get(columna)]),
        errors="coerce",
    ).iloc[0]

    if pd.isna(valor):
        return default

    return float(valor)


def decidir_modelo_con_composicion(
    fila: pd.Series,
) -> tuple[str, float, str]:
    """
    Decide entre híbrido completo y blend.

    El blend solo se selecciona cuando:
    1. mejora el MSE frente al híbrido;
    2. su intervalo bootstrap inferior frente al híbrido es positivo;
    3. la probabilidad de mejora es al menos 95 %.

    En cualquier otro caso se mantiene el híbrido completo, que fue la
    configuración validada por el módulo 42.
    """
    mejora_blend = valor_numerico(
        fila,
        "mejora_blend_vs_hibrido_mse_pct",
    )
    ic_inferior = valor_numerico(
        fila,
        "ic95_inferior_blend_vs_hibrido_pct",
    )
    prob = valor_numerico(
        fila,
        "prob_mejora_blend_vs_hibrido",
    )
    lambda_ultimo = valor_numerico(
        fila,
        "lambda_ultimo",
        1.0,
    )

    blend_superior = (
        pd.notna(mejora_blend)
        and mejora_blend > 0.0
        and pd.notna(ic_inferior)
        and ic_inferior > 0.0
        and pd.notna(prob)
        and prob >= 0.95
    )

    if blend_superior:
        return (
            MODELO_BLEND,
            float(np.clip(lambda_ultimo, 0.0, 1.0)),
            (
                "el blend supera al híbrido con evidencia bootstrap "
                "concluyente"
            ),
        )

    return (
        MODELO_HIBRIDO,
        1.0,
        (
            "el blend no supera al híbrido completo; se conserva M2 "
            "cuando la composición está vigente"
        ),
    )


def preparar_pruebas_blend(
    pruebas: pd.DataFrame,
) -> pd.DataFrame:
    claves = ["afp"]

    columnas = [
        "mejora_mse_pct",
        "ic95_inferior_pct",
        "ic95_superior_pct",
        "prob_mejora",
        "hac_p_unilateral",
    ]

    partes = []

    for comparacion, sufijo in [
        ("blend_vs_base", "blend_vs_base"),
        ("blend_vs_hibrido", "blend_vs_hibrido"),
    ]:
        bloque = pruebas[
            pruebas["comparacion"].eq(comparacion)
        ][
            claves + columnas
        ].copy()

        bloque = bloque.rename(
            columns={
                columna: f"{columna}_{sufijo}"
                for columna in columnas
            }
        )
        partes.append(bloque)

    salida = partes[0]

    for parte in partes[1:]:
        salida = salida.merge(
            parte,
            on=claves,
            how="outer",
            validate="one_to_one",
        )

    return salida


def construir_configuracion(
    seleccion_uniforme: pd.DataFrame,
    evidencia_afp: pd.DataFrame,
    resumen_blend: pd.DataFrame,
    pruebas_blend: pd.DataFrame,
    politica: pd.DataFrame,
) -> pd.DataFrame:
    if seleccion_uniforme.empty:
        raise RuntimeError(
            "La selección uniforme del módulo 42 está vacía."
        )

    escenario = str(
        seleccion_uniforme.iloc[0]["escenario"]
    )
    variante = str(
        seleccion_uniforme.iloc[0]["variante_confianza"]
    )

    pruebas_anchas = preparar_pruebas_blend(
        pruebas_blend
    )

    base = evidencia_afp.merge(
        resumen_blend,
        on="afp",
        how="outer",
        validate="one_to_one",
        suffixes=("_m42", "_m43"),
    ).merge(
        pruebas_anchas,
        on="afp",
        how="left",
        validate="one_to_one",
    ).merge(
        politica,
        on="afp",
        how="left",
        validate="one_to_one",
        suffixes=("", "_politica"),
    )

    filas = []

    for _, fila in base.iterrows():
        (
            modelo_vigente,
            lambda_vigente,
            razon_modelo_vigente,
        ) = decidir_modelo_con_composicion(
            pd.Series(
                {
                    **fila.to_dict(),
                    "ic95_inferior_blend_vs_hibrido_pct": fila.get(
                        "ic95_inferior_pct_blend_vs_hibrido"
                    ),
                    "prob_mejora_blend_vs_hibrido": fila.get(
                        "prob_mejora_blend_vs_hibrido"
                    ),
                }
            )
        )

        composicion_vigente = bool(
            fila.get("composicion_vigente", False)
        )

        if composicion_vigente:
            modelo_actual = modelo_vigente
            lambda_actual = lambda_vigente
            modo_actual = "composicion_activa"
            razon_actual = razon_modelo_vigente
        else:
            modelo_actual = MODELO_BASE
            lambda_actual = 0.0
            modo_actual = "fallback_sin_composicion_vigente"
            razon_actual = (
                "la composición pública está vencida; se utiliza "
                "exclusivamente el modelo base"
            )

        filas.append(
            {
                "afp": fila["afp"],
                "escenario_composicion": escenario,
                "variante_confianza": variante,
                "modelo_sin_composicion": MODELO_BASE,
                "modelo_con_composicion_vigente": modelo_vigente,
                "lambda_con_composicion_vigente": lambda_vigente,
                "razon_modelo_con_composicion": razon_modelo_vigente,
                "composicion_vigente": composicion_vigente,
                "periodo_ultima_composicion": fila.get("periodo"),
                "fecha_fin_validez": fila.get("fecha_fin_validez"),
                "fecha_mercado_referencia": fila.get(
                    "fecha_mercado_referencia"
                ),
                "dias_desde_vencimiento": valor_numerico(
                    fila,
                    "dias_desde_vencimiento",
                    0.0,
                ),
                "modelo_operativo_actual": modelo_actual,
                "lambda_operativo_actual": lambda_actual,
                "modo_operativo_actual": modo_actual,
                "razon_operativa_actual": razon_actual,
                "decision_preliminar_m42": fila.get(
                    "decision_preliminar"
                ),
                "evidencia_utilidad_composicion": fila.get(
                    "evidencia_utilidad_composicion"
                ),
                "evidencia_especificidad_afp": fila.get(
                    "evidencia_especificidad_afp"
                ),
                "estabilidad_temporal": fila.get(
                    "estabilidad_temporal"
                ),
                "mejora_hibrido_vs_base_pct": valor_numerico(
                    fila,
                    "bootstrap_mejora_vs_base_pct",
                ),
                "ic95_inferior_hibrido_vs_base_pct": valor_numerico(
                    fila,
                    "bootstrap_ic95_inferior_vs_base_pct",
                ),
                "hac_p_hibrido_vs_base": valor_numerico(
                    fila,
                    "hac_p_unilateral_m42",
                    valor_numerico(
                        fila,
                        "hac_p_unilateral",
                    ),
                ),
                "mejora_blend_vs_base_pct": valor_numerico(
                    fila,
                    "mejora_mse_pct_blend_vs_base",
                ),
                "ic95_inferior_blend_vs_base_pct": valor_numerico(
                    fila,
                    "ic95_inferior_pct_blend_vs_base",
                ),
                "mejora_blend_vs_hibrido_pct": valor_numerico(
                    fila,
                    "mejora_mse_pct_blend_vs_hibrido",
                ),
                "ic95_inferior_blend_vs_hibrido_pct": valor_numerico(
                    fila,
                    "ic95_inferior_pct_blend_vs_hibrido",
                ),
                "prob_mejora_blend_vs_hibrido": valor_numerico(
                    fila,
                    "prob_mejora_blend_vs_hibrido",
                ),
                "lambda_mediana_diagnostica": valor_numerico(
                    fila,
                    "lambda_mediana",
                ),
                "lambda_ultimo_diagnostico": valor_numerico(
                    fila,
                    "lambda_ultimo",
                ),
            }
        )

    salida = pd.DataFrame(filas)

    salida["afp"] = pd.Categorical(
        salida["afp"],
        categories=AFPS,
        ordered=True,
    )

    return salida.sort_values("afp").reset_index(drop=True)


def construir_control(
    configuracion: pd.DataFrame,
) -> pd.DataFrame:
    controles = []

    controles.append(
        {
            "control": "cuatro_afp_presentes",
            "estado": (
                "correcto"
                if set(
                    configuracion["afp"].astype(str)
                )
                == set(AFPS)
                else "revisar"
            ),
            "detalle": (
                ", ".join(
                    configuracion["afp"]
                    .astype(str)
                    .tolist()
                )
            ),
        }
    )

    controles.append(
        {
            "control": "lambda_actual_en_rango",
            "estado": (
                "correcto"
                if configuracion[
                    "lambda_operativo_actual"
                ].between(0.0, 1.0).all()
                else "revisar"
            ),
            "detalle": (
                f"min={configuracion['lambda_operativo_actual'].min():.6f}; "
                f"max={configuracion['lambda_operativo_actual'].max():.6f}"
            ),
        }
    )

    mascara_vencida = ~configuracion[
        "composicion_vigente"
    ]

    controles.append(
        {
            "control": "composicion_vencida_no_utilizada",
            "estado": (
                "correcto"
                if (
                    configuracion.loc[
                        mascara_vencida,
                        "modelo_operativo_actual",
                    ].eq(MODELO_BASE).all()
                    and configuracion.loc[
                        mascara_vencida,
                        "lambda_operativo_actual",
                    ].abs().le(TOLERANCIA).all()
                )
                else "revisar"
            ),
            "detalle": (
                f"casos_vencidos={int(mascara_vencida.sum())}"
            ),
        }
    )

    controles.append(
        {
            "control": "blend_no_desplaza_hibrido_sin_evidencia",
            "estado": (
                "correcto"
                if not (
                    configuracion[
                        "modelo_con_composicion_vigente"
                    ].eq(MODELO_BLEND)
                    & (
                        configuracion[
                            "ic95_inferior_blend_vs_hibrido_pct"
                        ].fillna(-np.inf)
                        <= 0.0
                    )
                ).any()
                else "revisar"
            ),
            "detalle": (
                "el blend solo puede seleccionarse con IC inferior positivo"
            ),
        }
    )

    return pd.DataFrame(controles)


def exportar_json(
    configuracion: pd.DataFrame,
    ruta: Path,
) -> None:
    registros = []

    for registro in configuracion.to_dict(
        orient="records"
    ):
        limpio = {}

        for clave, valor in registro.items():
            if isinstance(
                valor,
                (pd.Timestamp, np.datetime64),
            ):
                limpio[clave] = (
                    pd.Timestamp(valor).strftime("%Y-%m-%d")
                    if pd.notna(valor)
                    else None
                )
            elif pd.isna(valor):
                limpio[clave] = None
            elif isinstance(valor, np.generic):
                limpio[clave] = valor.item()
            else:
                limpio[clave] = valor

        registros.append(limpio)

    contenido = {
        "version": "modelo44_configuracion_produccion",
        "regla_general": {
            "sin_composicion_vigente": MODELO_BASE,
            "con_composicion_vigente": (
                "usar la decisión por AFP; actualmente M2_hibrido "
                "salvo evidencia concluyente a favor del blend"
            ),
            "prohibicion": (
                "no arrastrar una composición más allá de su "
                "fecha_fin_validez"
            ),
        },
        "afp": registros,
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

    seleccion_uniforme = leer_csv(
        processed
        / "ca0001_modelo42_seleccion_uniforme.csv"
    )
    evidencia_afp = leer_csv(
        processed
        / "ca0001_modelo42_seleccion_uniforme_por_afp.csv"
    )
    resumen_blend = leer_csv(
        processed
        / "ca0001_modelo43_resumen_blend.csv",
        [
            "primera_fecha_blend",
            "ultima_fecha_blend",
        ],
    )
    pruebas_blend = leer_csv(
        processed
        / "ca0001_modelo43_pruebas_blend.csv"
    )
    politica = leer_csv(
        processed
        / "ca0001_modelo43_politica_operativa.csv",
        [
            "fecha_cartera",
            "fecha_disponible",
            "fecha_fin_validez",
            "fecha_ultimo_lambda",
            "fecha_mercado_referencia",
        ],
    )

    politica["composicion_vigente"] = convertir_booleano(
        politica["composicion_vigente"]
    )

    configuracion = construir_configuracion(
        seleccion_uniforme,
        evidencia_afp,
        resumen_blend,
        pruebas_blend,
        politica,
    )
    control = construir_control(
        configuracion
    )

    estado = configuracion[
        [
            "afp",
            "periodo_ultima_composicion",
            "fecha_fin_validez",
            "fecha_mercado_referencia",
            "composicion_vigente",
            "dias_desde_vencimiento",
            "modelo_operativo_actual",
            "lambda_operativo_actual",
            "modo_operativo_actual",
            "razon_operativa_actual",
        ]
    ].copy()

    rutas = {
        "configuracion_csv": (
            processed
            / "ca0001_modelo44_configuracion_produccion.csv"
        ),
        "configuracion_json": (
            processed
            / "ca0001_modelo44_configuracion_produccion.json"
        ),
        "estado": (
            processed
            / "ca0001_modelo44_estado_operativo.csv"
        ),
        "control": (
            processed
            / "ca0001_modelo44_control.csv"
        ),
    }

    configuracion.to_csv(
        rutas["configuracion_csv"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    exportar_json(
        configuracion,
        rutas["configuracion_json"],
    )
    estado.to_csv(
        rutas["estado"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    control.to_csv(
        rutas["control"],
        index=False,
        encoding="utf-8-sig",
    )

    print(
        "\nCONFIGURACIÓN FINAL DE PRODUCCIÓN CERRADA"
    )
    print("=" * 120)

    print(
        "\nDECISIÓN CUANDO EXISTA COMPOSICIÓN VIGENTE"
    )
    print("-" * 120)
    print(
        configuracion[
            [
                "afp",
                "modelo_con_composicion_vigente",
                "lambda_con_composicion_vigente",
                "mejora_hibrido_vs_base_pct",
                "mejora_blend_vs_hibrido_pct",
                "ic95_inferior_blend_vs_hibrido_pct",
                "razon_modelo_con_composicion",
            ]
        ].to_string(index=False)
    )

    print("\nESTADO OPERATIVO ACTUAL")
    print("-" * 120)
    print(
        estado.to_string(index=False)
    )

    print("\nCONTROL")
    print("-" * 120)
    print(
        control.to_string(index=False)
    )

    print("\nArchivos creados:")
    for ruta in rutas.values():
        print(f" - {ruta.resolve()}")

    print(
        "\nCriterio final:\n"
        "- El blend dinámico mejoró al modelo base, pero no superó al "
        "híbrido completo en ninguna AFP.\n"
        "- Por ello, con composición vigente se conserva M2_hibrido "
        "con lambda=1, salvo que una futura reevaluación demuestre que "
        "el blend es superior con intervalo bootstrap completamente positivo.\n"
        "- Sin composición vigente se utiliza M0_base_mercado y lambda=0.\n"
        "- En la fecha de referencia actual, las cuatro AFP permanecen "
        "en fallback porque sus composiciones están vencidas."
    )


if __name__ == "__main__":
    main()
