from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd


MODELO_BASE = "M0_base_mercado"
MODELO_HIBRIDO = "M2_hibrido"
MODELO_PROXY = "M1_proxy_directo"

VENTANA_ROLLING = 252
MIN_ROLLING = 126
LAG_HAC = 21
TOLERANCIA = 1e-12
TOLERANCIA_HAC = np.finfo(float).tiny

ORDEN_VARIANTE = {
    "alta": 0,
    "alta_media": 1,
    "todos_mapeados": 2,
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


def normal_cdf(valor: float) -> float:
    return 0.5 * (
        1.0
        + math.erf(
            valor / math.sqrt(2.0)
        )
    )



def prueba_hac_perdida(
    diferencial: np.ndarray,
    lag: int = LAG_HAC,
) -> dict[str, float | str]:
    """
    Prueba unilateral de media positiva del diferencial de pérdida:

        d_t = error_base^2 - error_hibrido^2

    Un valor positivo favorece al modelo híbrido.

    La serie se reescala antes de calcular Newey-West. El estadístico no
    cambia con este reescalamiento, pero se evita confundir varianzas muy
    pequeñas —normales cuando se trabaja con errores cuadrados diarios—
    con una varianza exactamente igual a cero.
    """
    d = np.asarray(
        diferencial,
        dtype=float,
    )
    d = d[np.isfinite(d)]

    n = len(d)

    if n < 30:
        return {
            "hac_n": n,
            "hac_media_diferencial": np.nan,
            "hac_error_estandar": np.nan,
            "hac_estadistico": np.nan,
            "hac_p_unilateral": np.nan,
            "hac_metodo": "muestra_insuficiente",
        }

    media_original = float(d.mean())

    escala = float(
        np.nanstd(
            d,
            ddof=1,
        )
    )

    if (
        not np.isfinite(escala)
        or escala <= TOLERANCIA_HAC
    ):
        escala = float(
            np.nanmax(
                np.abs(d)
            )
        )

    if (
        not np.isfinite(escala)
        or escala <= TOLERANCIA_HAC
    ):
        return {
            "hac_n": n,
            "hac_media_diferencial": media_original,
            "hac_error_estandar": 0.0,
            "hac_estadistico": np.nan,
            "hac_p_unilateral": np.nan,
            "hac_metodo": "diferencial_constante",
        }

    z = d / escala
    media_z = float(z.mean())
    centrado = z - media_z

    lag_efectivo = min(
        lag,
        n - 1,
    )

    # Estimador Newey-West con kernel de Bartlett.
    largo_plazo = float(
        np.dot(
            centrado,
            centrado,
        )
        / n
    )

    for k in range(
        1,
        lag_efectivo + 1,
    ):
        autocov = float(
            np.dot(
                centrado[k:],
                centrado[:-k],
            )
            / n
        )
        peso = (
            1.0
            - k
            / (
                lag_efectivo + 1.0
            )
        )
        largo_plazo += (
            2.0
            * peso
            * autocov
        )

    var_media_z = (
        largo_plazo / n
    )
    metodo = "newey_west_bartlett"

    # El kernel de Bartlett debería producir una varianza no negativa.
    # Ante una anomalía numérica, se usa la varianza iid como respaldo,
    # en lugar de fabricar una varianza diminuta.
    if (
        not np.isfinite(var_media_z)
        or var_media_z <= 0.0
    ):
        var_media_z = float(
            np.var(
                z,
                ddof=1,
            )
            / n
        )
        metodo = "iid_respaldo_por_anomalia_numerica"

    if (
        not np.isfinite(var_media_z)
        or var_media_z <= 0.0
    ):
        estadistico = np.nan
        p_unilateral = np.nan
        error_estandar_original = np.nan
    else:
        error_estandar_z = math.sqrt(
            var_media_z
        )
        estadistico = (
            media_z
            / error_estandar_z
        )
        p_unilateral = (
            1.0
            - normal_cdf(
                estadistico
            )
        )
        error_estandar_original = (
            error_estandar_z
            * escala
        )

    return {
        "hac_n": n,
        "hac_media_diferencial": media_original,
        "hac_error_estandar": error_estandar_original,
        "hac_estadistico": estadistico,
        "hac_p_unilateral": p_unilateral,
        "hac_metodo": metodo,
    }


def preparar_predicciones(
    predicciones: pd.DataFrame,
) -> pd.DataFrame:
    salida = predicciones.copy()

    salida["fecha"] = pd.to_datetime(
        salida["fecha"],
        errors="coerce",
    )

    for columna in [
        "y_real",
        "y_pred",
        "n_train",
    ]:
        salida[columna] = pd.to_numeric(
            salida[columna],
            errors="coerce",
        )

    salida = salida.dropna(
        subset=[
            "fecha",
            "y_real",
            "y_pred",
            "modelo",
            "escenario",
            "variante_confianza",
            "afp",
        ]
    )

    return salida


def emparejar_modelos(
    grupo: pd.DataFrame,
    modelo_a: str,
    modelo_b: str,
) -> pd.DataFrame:
    a = (
        grupo[
            grupo["modelo"].eq(modelo_a)
        ][
            [
                "fecha",
                "y_real",
                "y_pred",
            ]
        ]
        .rename(
            columns={
                "y_pred": "pred_a",
            }
        )
    )

    b = (
        grupo[
            grupo["modelo"].eq(modelo_b)
        ][
            [
                "fecha",
                "y_real",
                "y_pred",
            ]
        ]
        .rename(
            columns={
                "y_pred": "pred_b",
            }
        )
    )

    combinado = a.merge(
        b[
            [
                "fecha",
                "pred_b",
            ]
        ],
        on="fecha",
        how="inner",
        validate="one_to_one",
    )

    combinado = combinado.sort_values(
        "fecha"
    ).reset_index(drop=True)

    return combinado


def metricas_comparacion(
    combinado: pd.DataFrame,
) -> dict[str, float]:
    if combinado.empty:
        return {
            "observaciones": 0,
            "mse_base": np.nan,
            "mse_hibrido": np.nan,
            "rmse_base": np.nan,
            "rmse_hibrido": np.nan,
            "mae_base": np.nan,
            "mae_hibrido": np.nan,
            "mejora_mse_pct": np.nan,
            "mejora_mae_pct": np.nan,
            "direccion_base_pct": np.nan,
            "direccion_hibrido_pct": np.nan,
            "cambio_direccion_pp": np.nan,
        }

    y = combinado["y_real"].to_numpy(
        dtype=float
    )
    base = combinado["pred_a"].to_numpy(
        dtype=float
    )
    hibrido = combinado["pred_b"].to_numpy(
        dtype=float
    )

    error_base = y - base
    error_hibrido = y - hibrido

    mse_base = float(
        np.mean(error_base**2)
    )
    mse_hibrido = float(
        np.mean(error_hibrido**2)
    )
    mae_base = float(
        np.mean(np.abs(error_base))
    )
    mae_hibrido = float(
        np.mean(np.abs(error_hibrido))
    )

    mejora_mse = (
        (mse_base - mse_hibrido)
        / mse_base
        * 100.0
        if mse_base > 0
        else np.nan
    )
    mejora_mae = (
        (mae_base - mae_hibrido)
        / mae_base
        * 100.0
        if mae_base > 0
        else np.nan
    )

    direccion_base = float(
        (
            np.sign(y)
            == np.sign(base)
        ).mean()
        * 100.0
    )
    direccion_hibrido = float(
        (
            np.sign(y)
            == np.sign(hibrido)
        ).mean()
        * 100.0
    )

    return {
        "observaciones": len(combinado),
        "mse_base": mse_base,
        "mse_hibrido": mse_hibrido,
        "rmse_base": math.sqrt(mse_base),
        "rmse_hibrido": math.sqrt(mse_hibrido),
        "mae_base": mae_base,
        "mae_hibrido": mae_hibrido,
        "mejora_mse_pct": mejora_mse,
        "mejora_mae_pct": mejora_mae,
        "direccion_base_pct": direccion_base,
        "direccion_hibrido_pct": direccion_hibrido,
        "cambio_direccion_pp": (
            direccion_hibrido
            - direccion_base
        ),
    }


def metricas_recortadas(
    combinado: pd.DataFrame,
) -> dict[str, float]:
    if len(combinado) < 100:
        return {
            "observaciones_recortadas": np.nan,
            "mejora_mse_recortada_pct": np.nan,
        }

    y = combinado["y_real"].to_numpy(
        dtype=float
    )
    base = combinado["pred_a"].to_numpy(
        dtype=float
    )
    hibrido = combinado["pred_b"].to_numpy(
        dtype=float
    )

    e0 = (y - base) ** 2
    e1 = (y - hibrido) ** 2

    umbral = float(
        np.quantile(
            np.maximum(e0, e1),
            0.99,
        )
    )
    mascara = (
        np.maximum(e0, e1)
        <= umbral
    )

    if mascara.sum() < 50:
        return {
            "observaciones_recortadas": int(
                mascara.sum()
            ),
            "mejora_mse_recortada_pct": np.nan,
        }

    mse0 = float(
        e0[mascara].mean()
    )
    mse1 = float(
        e1[mascara].mean()
    )

    return {
        "observaciones_recortadas": int(
            mascara.sum()
        ),
        "mejora_mse_recortada_pct": (
            (mse0 - mse1)
            / mse0
            * 100.0
            if mse0 > 0
            else np.nan
        ),
    }


def construir_resumen_general(
    predicciones: pd.DataFrame,
    resultados: pd.DataFrame,
    bootstrap: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    filas = []
    pares_guardados = []

    claves = [
        "escenario",
        "variante_confianza",
        "afp",
    ]

    for valores, grupo in predicciones.groupby(
        claves,
        sort=True,
    ):
        combinado = emparejar_modelos(
            grupo,
            MODELO_BASE,
            MODELO_HIBRIDO,
        )

        if combinado.empty:
            continue

        met = metricas_comparacion(
            combinado
        )
        met.update(
            metricas_recortadas(
                combinado
            )
        )

        y = combinado[
            "y_real"
        ].to_numpy(dtype=float)
        e0 = (
            y
            - combinado["pred_a"].to_numpy(
                dtype=float
            )
        ) ** 2
        e1 = (
            y
            - combinado["pred_b"].to_numpy(
                dtype=float
            )
        ) ** 2

        met.update(
            prueba_hac_perdida(
                e0 - e1
            )
        )

        fila = dict(
            zip(claves, valores)
        )
        fila.update(met)
        filas.append(fila)

        combinado = combinado.copy()

        for columna, valor in zip(
            claves,
            valores,
        ):
            combinado[columna] = valor

        combinado["perdida_base"] = e0
        combinado["perdida_hibrido"] = e1
        combinado["ventaja_hibrido"] = (
            e0 - e1
        )
        pares_guardados.append(combinado)

    resumen = pd.DataFrame(filas)
    pares = pd.concat(
        pares_guardados,
        ignore_index=True,
    )

    boot_base = bootstrap[
        bootstrap["comparado_con"].eq(
            MODELO_BASE
        )
        & bootstrap["modelo"].eq(
            MODELO_HIBRIDO
        )
    ][
        claves
        + [
            "mejora_mse_pct",
            "ic95_inferior_pct",
            "ic95_superior_pct",
            "prob_mejora",
        ]
    ].rename(
        columns={
            "mejora_mse_pct": (
                "bootstrap_mejora_vs_base_pct"
            ),
            "ic95_inferior_pct": (
                "bootstrap_ic95_inferior_vs_base_pct"
            ),
            "ic95_superior_pct": (
                "bootstrap_ic95_superior_vs_base_pct"
            ),
            "prob_mejora": (
                "bootstrap_prob_mejora_vs_base"
            ),
        }
    )

    resumen = resumen.merge(
        boot_base,
        on=claves,
        how="left",
        validate="one_to_one",
    )

    resultado_base = resultados[
        resultados["modelo"].eq(
            MODELO_BASE
        )
    ][
        claves
        + [
            "r2",
            "direccion_pct",
        ]
    ].rename(
        columns={
            "r2": "r2_base_reportado",
            "direccion_pct": (
                "direccion_base_reportada_pct"
            ),
        }
    )

    resultado_hibrido = resultados[
        resultados["modelo"].eq(
            MODELO_HIBRIDO
        )
    ][
        claves
        + [
            "r2",
            "direccion_pct",
        ]
    ].rename(
        columns={
            "r2": "r2_hibrido_reportado",
            "direccion_pct": (
                "direccion_hibrida_reportada_pct"
            ),
        }
    )

    resumen = resumen.merge(
        resultado_base,
        on=claves,
        how="left",
        validate="one_to_one",
    ).merge(
        resultado_hibrido,
        on=claves,
        how="left",
        validate="one_to_one",
    )

    return resumen, pares


def construir_estabilidad_anual(
    pares: pd.DataFrame,
) -> pd.DataFrame:
    salida = pares.copy()
    salida["anio"] = (
        salida["fecha"].dt.year
    )

    filas = []

    for claves, grupo in salida.groupby(
        [
            "escenario",
            "variante_confianza",
            "afp",
            "anio",
        ],
        sort=True,
    ):
        met = metricas_comparacion(
            grupo.rename(
                columns={
                    "pred_a": "pred_a",
                    "pred_b": "pred_b",
                }
            )
        )
        fila = {
            "escenario": claves[0],
            "variante_confianza": claves[1],
            "afp": claves[2],
            "anio": claves[3],
        }
        fila.update(met)
        filas.append(fila)

    return pd.DataFrame(filas)


def construir_rolling(
    pares: pd.DataFrame,
) -> pd.DataFrame:
    filas = []

    for claves, grupo in pares.groupby(
        [
            "escenario",
            "variante_confianza",
            "afp",
        ],
        sort=True,
    ):
        grupo = grupo.sort_values(
            "fecha"
        ).reset_index(drop=True)

        if len(grupo) < MIN_ROLLING:
            continue

        e0 = grupo[
            "perdida_base"
        ].rolling(
            VENTANA_ROLLING,
            min_periods=MIN_ROLLING,
        ).mean()
        e1 = grupo[
            "perdida_hibrido"
        ].rolling(
            VENTANA_ROLLING,
            min_periods=MIN_ROLLING,
        ).mean()

        mejora = (
            (e0 - e1)
            / e0
            * 100.0
        )

        bloque = pd.DataFrame(
            {
                "escenario": claves[0],
                "variante_confianza": claves[1],
                "afp": claves[2],
                "fecha": grupo["fecha"],
                "observaciones_ventana": (
                    np.minimum(
                        np.arange(
                            1,
                            len(grupo) + 1,
                        ),
                        VENTANA_ROLLING,
                    )
                ),
                "mse_base_rolling": e0,
                "mse_hibrido_rolling": e1,
                "mejora_mse_rolling_pct": mejora,
            }
        )

        filas.append(
            bloque.dropna(
                subset=[
                    "mejora_mse_rolling_pct"
                ]
            )
        )

    if not filas:
        return pd.DataFrame()

    return pd.concat(
        filas,
        ignore_index=True,
    )


def resumir_estabilidad(
    resumen: pd.DataFrame,
    anual: pd.DataFrame,
    rolling: pd.DataFrame,
) -> pd.DataFrame:
    claves = [
        "escenario",
        "variante_confianza",
        "afp",
    ]

    anual_resumen = (
        anual.groupby(
            claves,
            as_index=False,
        )
        .agg(
            anios_evaluados=(
                "anio",
                "nunique",
            ),
            anios_mejora_positiva=(
                "mejora_mse_pct",
                lambda s: int(
                    (
                        pd.to_numeric(
                            s,
                            errors="coerce",
                        )
                        > 0
                    ).sum()
                ),
            ),
            mejora_anual_mediana_pct=(
                "mejora_mse_pct",
                "median",
            ),
            peor_anio_mejora_pct=(
                "mejora_mse_pct",
                "min",
            ),
            mejor_anio_mejora_pct=(
                "mejora_mse_pct",
                "max",
            ),
        )
    )
    anual_resumen[
        "proporcion_anios_positivos"
    ] = (
        anual_resumen[
            "anios_mejora_positiva"
        ]
        / anual_resumen[
            "anios_evaluados"
        ]
    )

    if rolling.empty:
        rolling_resumen = pd.DataFrame(
            columns=claves
            + [
                "ventanas_rolling",
                "proporcion_rolling_positiva",
                "mejora_rolling_mediana_pct",
                "mejora_rolling_p10_pct",
                "mejora_rolling_p90_pct",
            ]
        )
    else:
        rolling_resumen = (
            rolling.groupby(
                claves,
                as_index=False,
            )
            .agg(
                ventanas_rolling=(
                    "fecha",
                    "size",
                ),
                proporcion_rolling_positiva=(
                    "mejora_mse_rolling_pct",
                    lambda s: float(
                        (
                            pd.to_numeric(
                                s,
                                errors="coerce",
                            )
                            > 0
                        ).mean()
                    ),
                ),
                mejora_rolling_mediana_pct=(
                    "mejora_mse_rolling_pct",
                    "median",
                ),
                mejora_rolling_p10_pct=(
                    "mejora_mse_rolling_pct",
                    lambda s: float(
                        pd.to_numeric(
                            s,
                            errors="coerce",
                        ).quantile(0.10)
                    ),
                ),
                mejora_rolling_p90_pct=(
                    "mejora_mse_rolling_pct",
                    lambda s: float(
                        pd.to_numeric(
                            s,
                            errors="coerce",
                        ).quantile(0.90)
                    ),
                ),
            )
        )

    return resumen.merge(
        anual_resumen,
        on=claves,
        how="left",
        validate="one_to_one",
    ).merge(
        rolling_resumen,
        on=claves,
        how="left",
        validate="one_to_one",
    )


def preparar_placebos(
    bootstrap: pd.DataFrame,
) -> pd.DataFrame:
    claves = [
        "escenario",
        "variante_confianza",
        "afp",
    ]

    placebos = bootstrap[
        bootstrap["modelo"].eq(
            MODELO_HIBRIDO
        )
        & bootstrap[
            "comparado_con"
        ].isin(
            [
                "P1_proxy_afp_ajena",
                "P2_proxy_pesos_permutados",
            ]
        )
    ].copy()

    columnas = [
        "mejora_mse_pct",
        "ic95_inferior_pct",
        "ic95_superior_pct",
        "prob_mejora",
    ]

    piezas = []

    for placebo in [
        "P1_proxy_afp_ajena",
        "P2_proxy_pesos_permutados",
    ]:
        bloque = placebos[
            placebos["comparado_con"].eq(
                placebo
            )
        ][
            claves + columnas
        ].copy()

        sufijo = (
            "vs_afp_ajena"
            if placebo
            == "P1_proxy_afp_ajena"
            else "vs_pesos_permutados"
        )

        bloque = bloque.rename(
            columns={
                columna: f"{columna}_{sufijo}"
                for columna in columnas
            }
        )
        piezas.append(bloque)

    salida = piezas[0]

    for pieza in piezas[1:]:
        salida = salida.merge(
            pieza,
            on=claves,
            how="outer",
            validate="one_to_one",
        )

    return salida


def clasificar_evidencia(
    fila: pd.Series,
) -> pd.Series:
    mejora = fila[
        "bootstrap_mejora_vs_base_pct"
    ]
    inferior = fila[
        "bootstrap_ic95_inferior_vs_base_pct"
    ]
    prob = fila[
        "bootstrap_prob_mejora_vs_base"
    ]

    placebo_perm = fila.get(
        "mejora_mse_pct_vs_pesos_permutados",
        np.nan,
    )
    placebo_perm_inf = fila.get(
        "ic95_inferior_pct_vs_pesos_permutados",
        np.nan,
    )
    placebo_afp = fila.get(
        "mejora_mse_pct_vs_afp_ajena",
        np.nan,
    )
    placebo_afp_inf = fila.get(
        "ic95_inferior_pct_vs_afp_ajena",
        np.nan,
    )

    anios = fila.get(
        "proporcion_anios_positivos",
        np.nan,
    )
    rolling = fila.get(
        "proporcion_rolling_positiva",
        np.nan,
    )
    recortada = fila.get(
        "mejora_mse_recortada_pct",
        np.nan,
    )

    if (
        pd.notna(mejora)
        and mejora > 0
        and pd.notna(inferior)
        and inferior > 0
        and pd.notna(prob)
        and prob >= 0.95
        and pd.notna(placebo_perm_inf)
        and placebo_perm_inf > 0
    ):
        utilidad = "fuerte"
    elif (
        pd.notna(mejora)
        and mejora > 0
        and pd.notna(prob)
        and prob >= 0.90
        and pd.notna(placebo_perm)
        and placebo_perm > 0
    ):
        utilidad = "moderada"
    elif pd.notna(mejora) and mejora > 0:
        utilidad = "débil"
    else:
        utilidad = "no_favorable"

    if (
        pd.notna(placebo_afp_inf)
        and placebo_afp_inf > 0
    ):
        especificidad = "fuerte"
    elif (
        pd.notna(placebo_afp)
        and placebo_afp > 0
        and fila.get(
            "prob_mejora_vs_afp_ajena",
            0.0,
        )
        >= 0.80
    ):
        especificidad = "moderada"
    else:
        especificidad = "no_demostrada"

    criterios_estabilidad = [
        pd.notna(anios)
        and anios >= 0.60,
        pd.notna(rolling)
        and rolling >= 0.60,
        pd.notna(recortada)
        and recortada > 0,
    ]
    cantidad_estable = sum(
        bool(x)
        for x in criterios_estabilidad
    )

    if cantidad_estable == 3:
        estabilidad = "alta"
    elif cantidad_estable >= 2:
        estabilidad = "media"
    else:
        estabilidad = "baja"

    fila["evidencia_utilidad_composicion"] = (
        utilidad
    )
    fila["evidencia_especificidad_afp"] = (
        especificidad
    )
    fila["estabilidad_temporal"] = (
        estabilidad
    )

    if (
        utilidad == "fuerte"
        and estabilidad in {
            "alta",
            "media",
        }
    ):
        conclusion = "incorporar_como_feature"
    elif (
        utilidad in {
            "fuerte",
            "moderada",
        }
        and estabilidad != "baja"
    ):
        conclusion = (
            "incorporar_con_peso_reducido"
        )
    elif utilidad == "débil":
        conclusion = "solo_sensibilidad"
    else:
        conclusion = "no_incorporar"

    fila["decision_preliminar"] = conclusion

    return fila


def construir_ranking_uniforme(
    resumen: pd.DataFrame,
) -> pd.DataFrame:
    filas = []

    for claves, grupo in resumen.groupby(
        [
            "escenario",
            "variante_confianza",
        ],
        sort=True,
    ):
        afp_presentes = int(
            grupo["afp"].nunique()
        )
        mejoras = pd.to_numeric(
            grupo[
                "bootstrap_mejora_vs_base_pct"
            ],
            errors="coerce",
        )
        inferiores = pd.to_numeric(
            grupo[
                "bootstrap_ic95_inferior_vs_base_pct"
            ],
            errors="coerce",
        )
        perm_inf = pd.to_numeric(
            grupo.get(
                "ic95_inferior_pct_vs_pesos_permutados",
                pd.Series(
                    np.nan,
                    index=grupo.index,
                ),
            ),
            errors="coerce",
        )

        filas.append(
            {
                "escenario": claves[0],
                "variante_confianza": claves[1],
                "afp_presentes": afp_presentes,
                "afp_mejora_positiva": int(
                    (mejoras > 0).sum()
                ),
                "afp_ic_base_positivo": int(
                    (inferiores > 0).sum()
                ),
                "afp_ic_placebo_permutado_positivo": int(
                    (perm_inf > 0).sum()
                ),
                "mejora_media_pct": float(
                    mejoras.mean()
                ),
                "mejora_mediana_pct": float(
                    mejoras.median()
                ),
                "mejora_minima_pct": float(
                    mejoras.min()
                ),
                "mejora_maxima_pct": float(
                    mejoras.max()
                ),
                "rolling_positivo_mediano": float(
                    pd.to_numeric(
                        grupo[
                            "proporcion_rolling_positiva"
                        ],
                        errors="coerce",
                    ).median()
                ),
                "anios_positivos_mediano": float(
                    pd.to_numeric(
                        grupo[
                            "proporcion_anios_positivos"
                        ],
                        errors="coerce",
                    ).median()
                ),
                "orden_variante": ORDEN_VARIANTE.get(
                    claves[1],
                    99,
                ),
            }
        )

    ranking = pd.DataFrame(filas)

    ranking = ranking.sort_values(
        [
            "afp_mejora_positiva",
            "afp_ic_base_positivo",
            "afp_ic_placebo_permutado_positivo",
            "mejora_minima_pct",
            "mejora_media_pct",
            "orden_variante",
        ],
        ascending=[
            False,
            False,
            False,
            False,
            False,
            True,
        ],
    ).reset_index(drop=True)

    ranking["ranking_uniforme"] = (
        np.arange(
            1,
            len(ranking) + 1,
        )
    )

    return ranking


def main() -> None:
    raiz = Path(__file__).resolve().parents[1]
    processed = raiz / "data" / "processed"

    resultados = leer_csv(
        processed
        / "ca0001_modelo41_resultados_oos.csv"
    )
    predicciones = preparar_predicciones(
        leer_csv(
            processed
            / "ca0001_modelo41_predicciones_oos.csv",
            ["fecha"],
        )
    )
    bootstrap = leer_csv(
        processed
        / "ca0001_modelo41_bootstrap_placebos.csv"
    )

    resumen, pares = (
        construir_resumen_general(
            predicciones,
            resultados,
            bootstrap,
        )
    )
    anual = construir_estabilidad_anual(
        pares
    )
    rolling = construir_rolling(
        pares
    )
    resumen = resumir_estabilidad(
        resumen,
        anual,
        rolling,
    )

    placebos = preparar_placebos(
        bootstrap
    )
    resumen = resumen.merge(
        placebos,
        on=[
            "escenario",
            "variante_confianza",
            "afp",
        ],
        how="left",
        validate="one_to_one",
    )

    resumen = resumen.apply(
        clasificar_evidencia,
        axis=1,
    )

    ranking = construir_ranking_uniforme(
        resumen
    )
    seleccion = ranking.head(1).copy()

    if not seleccion.empty:
        escenario_sel = seleccion.iloc[0][
            "escenario"
        ]
        variante_sel = seleccion.iloc[0][
            "variante_confianza"
        ]

        seleccion_afp = resumen[
            resumen["escenario"].eq(
                escenario_sel
            )
            & resumen[
                "variante_confianza"
            ].eq(
                variante_sel
            )
        ].copy()
    else:
        seleccion_afp = pd.DataFrame()

    rutas = {
        "resumen": (
            processed
            / "ca0001_modelo42_resumen_robustez.csv"
        ),
        "anual": (
            processed
            / "ca0001_modelo42_estabilidad_anual.csv"
        ),
        "rolling": (
            processed
            / "ca0001_modelo42_rolling_252.csv"
        ),
        "pares": (
            processed
            / "ca0001_modelo42_perdidas_emparejadas.csv"
        ),
        "ranking": (
            processed
            / "ca0001_modelo42_ranking_uniforme.csv"
        ),
        "seleccion": (
            processed
            / "ca0001_modelo42_seleccion_uniforme.csv"
        ),
        "seleccion_afp": (
            processed
            / "ca0001_modelo42_seleccion_uniforme_por_afp.csv"
        ),
    }

    resumen.to_csv(
        rutas["resumen"],
        index=False,
        encoding="utf-8-sig",
    )
    anual.to_csv(
        rutas["anual"],
        index=False,
        encoding="utf-8-sig",
    )
    rolling.to_csv(
        rutas["rolling"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    pares.to_csv(
        rutas["pares"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    ranking.to_csv(
        rutas["ranking"],
        index=False,
        encoding="utf-8-sig",
    )
    seleccion.to_csv(
        rutas["seleccion"],
        index=False,
        encoding="utf-8-sig",
    )
    seleccion_afp.to_csv(
        rutas["seleccion_afp"],
        index=False,
        encoding="utf-8-sig",
    )

    print(
        "\nROBUSTEZ TEMPORAL Y SELECCIÓN UNIFORME TERMINADAS"
    )
    print("=" * 120)

    print("\nRANKING DE CONFIGURACIONES UNIFORMES")
    print("-" * 120)
    print(
        ranking[
            [
                "ranking_uniforme",
                "escenario",
                "variante_confianza",
                "afp_presentes",
                "afp_mejora_positiva",
                "afp_ic_base_positivo",
                "afp_ic_placebo_permutado_positivo",
                "mejora_media_pct",
                "mejora_minima_pct",
                "rolling_positivo_mediano",
                "anios_positivos_mediano",
            ]
        ].to_string(index=False)
    )

    print("\nCONFIGURACIÓN UNIFORME SELECCIONADA")
    print("-" * 120)

    if seleccion.empty:
        print(
            "No se pudo seleccionar una configuración."
        )
    else:
        print(
            seleccion.to_string(
                index=False
            )
        )

    print("\nEVIDENCIA POR AFP EN LA CONFIGURACIÓN SELECCIONADA")
    print("-" * 120)

    if seleccion_afp.empty:
        print(
            "No hay resultados por AFP."
        )
    else:
        columnas = [
            "afp",
            "observaciones",
            "rmse_base",
            "rmse_hibrido",
            "bootstrap_mejora_vs_base_pct",
            "bootstrap_ic95_inferior_vs_base_pct",
            "bootstrap_ic95_superior_vs_base_pct",
            "bootstrap_prob_mejora_vs_base",
            "mejora_mse_pct_vs_afp_ajena",
            "ic95_inferior_pct_vs_afp_ajena",
            "mejora_mse_pct_vs_pesos_permutados",
            "ic95_inferior_pct_vs_pesos_permutados",
            "proporcion_anios_positivos",
            "proporcion_rolling_positiva",
            "mejora_mse_recortada_pct",
            "cambio_direccion_pp",
            "hac_p_unilateral",
            "evidencia_utilidad_composicion",
            "evidencia_especificidad_afp",
            "estabilidad_temporal",
            "decision_preliminar",
        ]
        print(
            seleccion_afp[
                columnas
            ].sort_values(
                "afp"
            ).to_string(
                index=False
            )
        )

    print("\nMEJORES CONFIGURACIONES POR AFP")
    print("-" * 120)

    mejores_afp = (
        resumen.sort_values(
            [
                "afp",
                "bootstrap_mejora_vs_base_pct",
                "bootstrap_ic95_inferior_vs_base_pct",
            ],
            ascending=[
                True,
                False,
                False,
            ],
        )
        .groupby(
            "afp",
            as_index=False,
        )
        .head(3)
    )

    print(
        mejores_afp[
            [
                "afp",
                "escenario",
                "variante_confianza",
                "bootstrap_mejora_vs_base_pct",
                "bootstrap_ic95_inferior_vs_base_pct",
                "prob_mejora_vs_pesos_permutados",
                "proporcion_anios_positivos",
                "proporcion_rolling_positiva",
                "decision_preliminar",
            ]
        ].to_string(
            index=False
        )
    )

    print("\nArchivos creados:")
    for ruta in rutas.values():
        print(f" - {ruta.resolve()}")

    print(
        "\nCriterio metodológico:\n"
        "- La selección uniforme evita escoger una combinación distinta "
        "para cada AFP solo porque funcionó mejor en la muestra observada.\n"
        "- La mejora frente a M0 demuestra utilidad incremental sobre los "
        "factores de mercado; la ventaja frente al placebo permutado "
        "demuestra que la correspondencia económica de los pesos aporta "
        "información.\n"
        "- La comparación con la composición promedio de otras AFP mide "
        "especificidad por administradora. Si no se supera ese placebo, la "
        "evidencia es compatible con una señal estratégica común al sistema, "
        "no con una identificación precisa de la cartera de cada AFP.\n"
        "- La estabilidad anual, rolling y sin el 1 % de errores extremos "
        "reduce el riesgo de aceptar una mejora concentrada en pocos episodios.\n"
        "- La composición debe usarse como complemento del modelo de mercado, "
        "nunca como proxy directo independiente ni como prueba causal."
    )


if __name__ == "__main__":
    main()
