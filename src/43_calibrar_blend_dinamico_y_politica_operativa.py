from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score


MODELO_BASE = "M0_base_mercado"
MODELO_HIBRIDO = "M2_hibrido"

MIN_CALIBRACION = 252
REFIT_CADA = 21
BOOTSTRAP_REPS = 500
BOOTSTRAP_BLOQUE = 21
LAG_HAC = 21
SEMILLA = 20260704


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


def prueba_hac(
    diferencial: np.ndarray,
    lag: int = LAG_HAC,
) -> dict[str, float | str]:
    """
    Prueba unilateral de media positiva:

        d_t = pérdida_referencia - pérdida_candidato

    Un promedio positivo favorece al candidato.
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
            "hac_media": np.nan,
            "hac_estadistico": np.nan,
            "hac_p_unilateral": np.nan,
            "hac_metodo": "muestra_insuficiente",
        }

    escala = float(np.std(d, ddof=1))

    if (
        not np.isfinite(escala)
        or escala <= np.finfo(float).tiny
    ):
        return {
            "hac_n": n,
            "hac_media": float(np.mean(d)),
            "hac_estadistico": np.nan,
            "hac_p_unilateral": np.nan,
            "hac_metodo": "diferencial_constante",
        }

    z = d / escala
    media = float(z.mean())
    centrado = z - media
    lag_efectivo = min(lag, n - 1)

    largo_plazo = float(
        np.dot(centrado, centrado) / n
    )

    for k in range(1, lag_efectivo + 1):
        autocov = float(
            np.dot(
                centrado[k:],
                centrado[:-k],
            )
            / n
        )
        peso = 1.0 - k / (
            lag_efectivo + 1.0
        )
        largo_plazo += 2.0 * peso * autocov

    var_media = largo_plazo / n
    metodo = "newey_west_bartlett"

    if (
        not np.isfinite(var_media)
        or var_media <= 0.0
    ):
        var_media = float(
            np.var(z, ddof=1) / n
        )
        metodo = "iid_respaldo"

    if (
        not np.isfinite(var_media)
        or var_media <= 0.0
    ):
        estadistico = np.nan
        p = np.nan
    else:
        estadistico = media / math.sqrt(var_media)
        p = 1.0 - normal_cdf(estadistico)

    return {
        "hac_n": n,
        "hac_media": float(np.mean(d)),
        "hac_estadistico": estadistico,
        "hac_p_unilateral": p,
        "hac_metodo": metodo,
    }


def bootstrap_mejora(
    y: np.ndarray,
    pred_referencia: np.ndarray,
    pred_candidato: np.ndarray,
    reps: int = BOOTSTRAP_REPS,
) -> dict[str, float]:
    y = np.asarray(y, dtype=float)
    referencia = np.asarray(
        pred_referencia,
        dtype=float,
    )
    candidato = np.asarray(
        pred_candidato,
        dtype=float,
    )

    mascara = (
        np.isfinite(y)
        & np.isfinite(referencia)
        & np.isfinite(candidato)
    )
    y = y[mascara]
    referencia = referencia[mascara]
    candidato = candidato[mascara]

    n = len(y)

    if n < 100:
        return {
            "bootstrap_n": n,
            "mejora_mse_pct": np.nan,
            "ic95_inferior_pct": np.nan,
            "ic95_superior_pct": np.nan,
            "prob_mejora": np.nan,
        }

    e0 = (y - referencia) ** 2
    e1 = (y - candidato) ** 2

    mse0 = float(e0.mean())
    mse1 = float(e1.mean())
    mejora = (
        (mse0 - mse1) / mse0 * 100.0
        if mse0 > 0
        else np.nan
    )

    rng = np.random.default_rng(SEMILLA)
    resultados = []

    for _ in range(reps):
        indices: list[int] = []

        while len(indices) < n:
            inicio = int(
                rng.integers(
                    0,
                    max(
                        n - BOOTSTRAP_BLOQUE + 1,
                        1,
                    ),
                )
            )
            indices.extend(
                range(
                    inicio,
                    min(
                        inicio + BOOTSTRAP_BLOQUE,
                        n,
                    ),
                )
            )

        idx = np.asarray(
            indices[:n],
            dtype=int,
        )
        b0 = float(e0[idx].mean())
        b1 = float(e1[idx].mean())

        if b0 > 0:
            resultados.append(
                (b0 - b1) / b0 * 100.0
            )

    arr = np.asarray(resultados)

    return {
        "bootstrap_n": n,
        "mejora_mse_pct": mejora,
        "ic95_inferior_pct": float(
            np.quantile(arr, 0.025)
        ),
        "ic95_superior_pct": float(
            np.quantile(arr, 0.975)
        ),
        "prob_mejora": float(
            (arr > 0).mean()
        ),
    }


def preparar_predicciones(
    df: pd.DataFrame,
    escenario: str,
    variante: str,
) -> pd.DataFrame:
    base = df[
        df["escenario"].eq(escenario)
        & df["variante_confianza"].eq(
            variante
        )
        & df["modelo"].isin(
            [MODELO_BASE, MODELO_HIBRIDO]
        )
    ].copy()

    base["fecha"] = pd.to_datetime(
        base["fecha"],
        errors="coerce",
    )

    for columna in [
        "y_real",
        "y_pred",
        "n_train",
    ]:
        base[columna] = pd.to_numeric(
            base[columna],
            errors="coerce",
        )

    base = base.dropna(
        subset=[
            "fecha",
            "afp",
            "modelo",
            "y_real",
            "y_pred",
        ]
    )

    real = (
        base[
            base["modelo"].eq(MODELO_BASE)
        ][
            [
                "fecha",
                "afp",
                "y_real",
                "y_pred",
                "n_train",
            ]
        ]
        .rename(
            columns={
                "y_pred": "pred_base",
                "n_train": "n_train_base",
            }
        )
    )

    hibrido = (
        base[
            base["modelo"].eq(
                MODELO_HIBRIDO
            )
        ][
            [
                "fecha",
                "afp",
                "y_pred",
                "n_train",
            ]
        ]
        .rename(
            columns={
                "y_pred": "pred_hibrido",
                "n_train": "n_train_hibrido",
            }
        )
    )

    combinado = real.merge(
        hibrido,
        on=["fecha", "afp"],
        how="inner",
        validate="one_to_one",
    )

    return combinado.sort_values(
        ["afp", "fecha"]
    ).reset_index(drop=True)


def lambda_optimo(
    y: np.ndarray,
    pred_base: np.ndarray,
    pred_hibrido: np.ndarray,
) -> tuple[float, float]:
    """
    Minimiza:

        y_hat = base + lambda * (híbrido - base)

    con lambda restringido al intervalo [0, 1].
    """
    y = np.asarray(y, dtype=float)
    base = np.asarray(pred_base, dtype=float)
    hibrido = np.asarray(
        pred_hibrido,
        dtype=float,
    )

    delta = hibrido - base
    residual_base = y - base

    denominador = float(
        np.dot(delta, delta)
    )
    numerador = float(
        np.dot(delta, residual_base)
    )

    if denominador <= np.finfo(float).tiny:
        bruto = 0.0
    else:
        bruto = numerador / denominador

    restringido = float(
        np.clip(bruto, 0.0, 1.0)
    )

    return bruto, restringido


def construir_blend_dinamico(
    datos: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    predicciones = []
    trayectorias = []

    for afp, grupo in datos.groupby(
        "afp",
        sort=True,
    ):
        grupo = grupo.sort_values(
            "fecha"
        ).reset_index(drop=True)

        if len(grupo) <= MIN_CALIBRACION + 60:
            continue

        for inicio in range(
            MIN_CALIBRACION,
            len(grupo),
            REFIT_CADA,
        ):
            fin = min(
                inicio + REFIT_CADA,
                len(grupo),
            )

            historial = grupo.iloc[:inicio]
            prueba = grupo.iloc[inicio:fin]

            bruto, lam = lambda_optimo(
                historial["y_real"].to_numpy(),
                historial[
                    "pred_base"
                ].to_numpy(),
                historial[
                    "pred_hibrido"
                ].to_numpy(),
            )

            bloque = prueba.copy()
            bloque["lambda_bruto"] = bruto
            bloque["lambda_operativo"] = lam
            bloque["pred_blend"] = (
                bloque["pred_base"]
                + lam
                * (
                    bloque["pred_hibrido"]
                    - bloque["pred_base"]
                )
            )
            bloque["n_calibracion_lambda"] = (
                len(historial)
            )
            predicciones.append(bloque)

            trayectorias.append(
                {
                    "afp": afp,
                    "fecha_inicio_aplicacion": (
                        prueba["fecha"].min()
                    ),
                    "fecha_fin_aplicacion": (
                        prueba["fecha"].max()
                    ),
                    "n_calibracion_lambda": (
                        len(historial)
                    ),
                    "lambda_bruto": bruto,
                    "lambda_operativo": lam,
                    "lambda_en_limite_cero": (
                        lam == 0.0
                    ),
                    "lambda_en_limite_uno": (
                        lam == 1.0
                    ),
                }
            )

    if not predicciones:
        raise RuntimeError(
            "No se pudo construir el blend dinámico."
        )

    return (
        pd.concat(
            predicciones,
            ignore_index=True,
        ),
        pd.DataFrame(trayectorias),
    )


def metricas_prediccion(
    y: np.ndarray,
    pred: np.ndarray,
) -> dict[str, float]:
    y = np.asarray(y, dtype=float)
    pred = np.asarray(pred, dtype=float)

    return {
        "rmse": float(
            mean_squared_error(
                y,
                pred,
            ) ** 0.5
        ),
        "mae": float(
            mean_absolute_error(
                y,
                pred,
            )
        ),
        "r2": float(
            r2_score(
                y,
                pred,
            )
        ),
        "direccion_pct": float(
            (
                np.sign(y)
                == np.sign(pred)
            ).mean()
            * 100.0
        ),
    }


def resumir_blend(
    predicciones: pd.DataFrame,
    trayectoria: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    resumen = []
    pruebas = []

    for afp, grupo in predicciones.groupby(
        "afp",
        sort=True,
    ):
        y = grupo["y_real"].to_numpy()
        base = grupo["pred_base"].to_numpy()
        hibrido = grupo[
            "pred_hibrido"
        ].to_numpy()
        blend = grupo["pred_blend"].to_numpy()

        met_base = metricas_prediccion(
            y,
            base,
        )
        met_hibrido = metricas_prediccion(
            y,
            hibrido,
        )
        met_blend = metricas_prediccion(
            y,
            blend,
        )

        mse_base = met_base["rmse"] ** 2
        mse_hibrido = met_hibrido[
            "rmse"
        ] ** 2
        mse_blend = met_blend["rmse"] ** 2

        trayectoria_afp = trayectoria[
            trayectoria["afp"].eq(afp)
        ]

        resumen.append(
            {
                "afp": afp,
                "observaciones_oos_blend": len(
                    grupo
                ),
                "primera_fecha_blend": (
                    grupo["fecha"].min()
                ),
                "ultima_fecha_blend": (
                    grupo["fecha"].max()
                ),
                "rmse_base": met_base["rmse"],
                "rmse_hibrido": (
                    met_hibrido["rmse"]
                ),
                "rmse_blend": met_blend["rmse"],
                "mae_base": met_base["mae"],
                "mae_hibrido": met_hibrido[
                    "mae"
                ],
                "mae_blend": met_blend["mae"],
                "r2_base": met_base["r2"],
                "r2_hibrido": met_hibrido["r2"],
                "r2_blend": met_blend["r2"],
                "direccion_base_pct": (
                    met_base["direccion_pct"]
                ),
                "direccion_hibrido_pct": (
                    met_hibrido[
                        "direccion_pct"
                    ]
                ),
                "direccion_blend_pct": (
                    met_blend["direccion_pct"]
                ),
                "mejora_blend_vs_base_mse_pct": (
                    (mse_base - mse_blend)
                    / mse_base
                    * 100.0
                ),
                "mejora_blend_vs_hibrido_mse_pct": (
                    (mse_hibrido - mse_blend)
                    / mse_hibrido
                    * 100.0
                ),
                "lambda_mediana": float(
                    trayectoria_afp[
                        "lambda_operativo"
                    ].median()
                ),
                "lambda_media": float(
                    trayectoria_afp[
                        "lambda_operativo"
                    ].mean()
                ),
                "lambda_p10": float(
                    trayectoria_afp[
                        "lambda_operativo"
                    ].quantile(0.10)
                ),
                "lambda_p90": float(
                    trayectoria_afp[
                        "lambda_operativo"
                    ].quantile(0.90)
                ),
                "lambda_ultimo": float(
                    trayectoria_afp.sort_values(
                        "fecha_fin_aplicacion"
                    )[
                        "lambda_operativo"
                    ].iloc[-1]
                ),
                "proporcion_lambda_cero": float(
                    trayectoria_afp[
                        "lambda_en_limite_cero"
                    ].mean()
                ),
                "proporcion_lambda_uno": float(
                    trayectoria_afp[
                        "lambda_en_limite_uno"
                    ].mean()
                ),
            }
        )

        comparaciones = [
            (
                "blend_vs_base",
                base,
                blend,
            ),
            (
                "blend_vs_hibrido",
                hibrido,
                blend,
            ),
        ]

        for nombre, referencia, candidato in comparaciones:
            boot = bootstrap_mejora(
                y,
                referencia,
                candidato,
            )
            hac = prueba_hac(
                (y - referencia) ** 2
                - (y - candidato) ** 2
            )

            fila = {
                "afp": afp,
                "comparacion": nombre,
            }
            fila.update(boot)
            fila.update(hac)
            pruebas.append(fila)

    return (
        pd.DataFrame(resumen),
        pd.DataFrame(pruebas),
    )


def leer_fecha_maxima_mercado(
    ruta: Path,
) -> pd.Timestamp:
    df = pd.read_csv(ruta)

    candidatas = [
        columna
        for columna in df.columns
        if str(columna).strip().lower()
        in {
            "fecha",
            "date",
            "trading_date",
        }
    ]

    if not candidatas:
        candidatas = [df.columns[0]]

    fechas = pd.to_datetime(
        df[candidatas[0]],
        errors="coerce",
    )

    return fechas.max()


def construir_politica_operativa(
    processed: Path,
    escenario: str,
    variante: str,
    trayectoria: pd.DataFrame,
) -> pd.DataFrame:
    ventanas = leer_csv(
        processed
        / "ca0001_proxy_ventanas_publicacion_45d.csv",
        [
            "fecha_cartera",
            "fecha_disponible",
            "fecha_fin_validez",
        ],
    )

    ventanas = ventanas[
        ventanas["escenario"].eq(
            escenario
        )
        & ventanas[
            "variante_confianza"
        ].eq(variante)
    ].copy()

    fecha_mercado = leer_fecha_maxima_mercado(
        processed
        / "mercados_factores_modelo.csv"
    )

    ultimas_lambda = (
        trayectoria.sort_values(
            "fecha_fin_aplicacion"
        )
        .groupby(
            "afp",
            as_index=False,
        )
        .tail(1)[
            [
                "afp",
                "lambda_operativo",
                "fecha_fin_aplicacion",
            ]
        ]
        .rename(
            columns={
                "lambda_operativo": (
                    "lambda_validado_ultimo"
                ),
                "fecha_fin_aplicacion": (
                    "fecha_ultimo_lambda"
                ),
            }
        )
    )

    ultimas_ventanas = (
        ventanas.sort_values(
            "fecha_cartera"
        )
        .groupby(
            "afp",
            as_index=False,
        )
        .tail(1)[
            [
                "afp",
                "periodo",
                "fecha_cartera",
                "fecha_disponible",
                "fecha_fin_validez",
                "estado_cobertura",
            ]
        ]
    )

    politica = ultimas_ventanas.merge(
        ultimas_lambda,
        on="afp",
        how="left",
        validate="one_to_one",
    )

    politica["fecha_mercado_referencia"] = (
        fecha_mercado
    )
    politica["composicion_vigente"] = (
        politica["fecha_mercado_referencia"]
        <= politica["fecha_fin_validez"]
    )
    politica["dias_desde_vencimiento"] = (
        politica["fecha_mercado_referencia"]
        - politica["fecha_fin_validez"]
    ).dt.days.clip(lower=0)

    politica["lambda_operativo_actual"] = np.where(
        politica["composicion_vigente"],
        politica["lambda_validado_ultimo"],
        0.0,
    )
    politica["modo_operativo"] = np.where(
        politica["composicion_vigente"],
        "modelo_hibrido_con_blend",
        "fallback_modelo_base",
    )
    politica["razon"] = np.where(
        politica["composicion_vigente"],
        "composición dentro de su ventana pública",
        "composición vencida; no arrastrar pesos antiguos",
    )

    return politica.sort_values("afp")


def construir_control(
    predicciones: pd.DataFrame,
    trayectoria: pd.DataFrame,
    politica: pd.DataFrame,
) -> pd.DataFrame:
    controles = [
        {
            "control": "lambda_en_rango_0_1",
            "estado": (
                "correcto"
                if trayectoria[
                    "lambda_operativo"
                ].between(0.0, 1.0).all()
                else "revisar"
            ),
            "detalle": (
                f"min={trayectoria['lambda_operativo'].min():.6f}; "
                f"max={trayectoria['lambda_operativo'].max():.6f}"
            ),
        },
        {
            "control": "predicciones_sin_duplicados",
            "estado": (
                "correcto"
                if not predicciones.duplicated(
                    ["fecha", "afp"]
                ).any()
                else "revisar"
            ),
            "detalle": (
                f"filas={len(predicciones)}"
            ),
        },
        {
            "control": "politica_por_cuatro_afp",
            "estado": (
                "correcto"
                if politica["afp"].nunique() == 4
                else "revisar"
            ),
            "detalle": (
                f"afp={politica['afp'].nunique()}"
            ),
        },
        {
            "control": "sin_composicion_vencida_en_operacion",
            "estado": (
                "correcto"
                if (
                    politica.loc[
                        ~politica[
                            "composicion_vigente"
                        ],
                        "lambda_operativo_actual",
                    ]
                    == 0.0
                ).all()
                else "revisar"
            ),
            "detalle": (
                f"fallbacks={(~politica['composicion_vigente']).sum()}"
            ),
        },
    ]

    return pd.DataFrame(controles)


def main() -> None:
    raiz = Path(__file__).resolve().parents[1]
    processed = raiz / "data" / "processed"

    seleccion = leer_csv(
        processed
        / "ca0001_modelo42_seleccion_uniforme.csv"
    )

    if seleccion.empty:
        raise RuntimeError(
            "La selección uniforme del módulo 42 está vacía."
        )

    escenario = str(
        seleccion.iloc[0]["escenario"]
    )
    variante = str(
        seleccion.iloc[0][
            "variante_confianza"
        ]
    )

    predicciones_41 = leer_csv(
        processed
        / "ca0001_modelo41_predicciones_oos.csv",
        ["fecha"],
    )

    datos = preparar_predicciones(
        predicciones_41,
        escenario,
        variante,
    )

    pred_blend, trayectoria = (
        construir_blend_dinamico(datos)
    )
    resumen, pruebas = resumir_blend(
        pred_blend,
        trayectoria,
    )
    politica = construir_politica_operativa(
        processed,
        escenario,
        variante,
        trayectoria,
    )
    control = construir_control(
        pred_blend,
        trayectoria,
        politica,
    )

    seleccion_salida = seleccion.copy()
    seleccion_salida[
        "modelo_operativo_con_composicion"
    ] = "blend_dinamico_M0_M2"
    seleccion_salida[
        "regla_sin_composicion_vigente"
    ] = "lambda=0; fallback_modelo_base"

    rutas = {
        "predicciones": (
            processed
            / "ca0001_modelo43_predicciones_blend_dinamico.csv"
        ),
        "trayectoria": (
            processed
            / "ca0001_modelo43_trayectoria_lambda.csv"
        ),
        "resumen": (
            processed
            / "ca0001_modelo43_resumen_blend.csv"
        ),
        "pruebas": (
            processed
            / "ca0001_modelo43_pruebas_blend.csv"
        ),
        "politica": (
            processed
            / "ca0001_modelo43_politica_operativa.csv"
        ),
        "control": (
            processed
            / "ca0001_modelo43_control.csv"
        ),
        "seleccion": (
            processed
            / "ca0001_modelo43_configuracion_final.csv"
        ),
    }

    pred_blend.to_csv(
        rutas["predicciones"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    trayectoria.to_csv(
        rutas["trayectoria"],
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
    pruebas.to_csv(
        rutas["pruebas"],
        index=False,
        encoding="utf-8-sig",
    )
    politica.to_csv(
        rutas["politica"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    control.to_csv(
        rutas["control"],
        index=False,
        encoding="utf-8-sig",
    )
    seleccion_salida.to_csv(
        rutas["seleccion"],
        index=False,
        encoding="utf-8-sig",
    )

    print(
        "\nCALIBRACIÓN DEL BLEND DINÁMICO TERMINADA"
    )
    print("=" * 120)

    print("\nCONFIGURACIÓN HEREDADA DEL MÓDULO 42")
    print("-" * 120)
    print(
        f"Escenario: {escenario}\n"
        f"Variante: {variante}\n"
        "Modelos combinados: M0_base_mercado y M2_hibrido"
    )

    print("\nRESULTADOS DEL BLEND DINÁMICO")
    print("-" * 120)
    print(
        resumen.to_string(index=False)
    )

    print("\nPRUEBAS DEL BLEND")
    print("-" * 120)
    print(
        pruebas.to_string(index=False)
    )

    print("\nTRAYECTORIA DE LAMBDA")
    print("-" * 120)
    print(
        trayectoria.groupby(
            "afp",
            as_index=False,
        )
        .agg(
            bloques=("lambda_operativo", "size"),
            lambda_mediana=(
                "lambda_operativo",
                "median",
            ),
            lambda_media=(
                "lambda_operativo",
                "mean",
            ),
            lambda_min=(
                "lambda_operativo",
                "min",
            ),
            lambda_max=(
                "lambda_operativo",
                "max",
            ),
            proporcion_cero=(
                "lambda_en_limite_cero",
                "mean",
            ),
            proporcion_uno=(
                "lambda_en_limite_uno",
                "mean",
            ),
        )
        .to_string(index=False)
    )

    print("\nPOLÍTICA OPERATIVA")
    print("-" * 120)
    print(
        politica[
            [
                "afp",
                "periodo",
                "fecha_fin_validez",
                "fecha_mercado_referencia",
                "composicion_vigente",
                "dias_desde_vencimiento",
                "lambda_validado_ultimo",
                "lambda_operativo_actual",
                "modo_operativo",
                "razon",
            ]
        ].to_string(index=False)
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
        "\nCriterio metodológico:\n"
        "- Lambda se estima únicamente con predicciones OOS anteriores y "
        "se aplica a los siguientes 21 días; no usa información futura.\n"
        "- Lambda=0 equivale al modelo base y lambda=1 al híbrido completo.\n"
        "- El blend permite que la evidencia histórica determine cuánto "
        "peso dar a la composición por AFP, sin fijar porcentajes arbitrarios.\n"
        "- Cuando la composición pública vence, el sistema fuerza lambda=0 "
        "y vuelve al modelo base.\n"
        "- La política evita utilizar en julio una composición cuya ventana "
        "pública terminó meses antes."
    )


if __name__ == "__main__":
    main()
