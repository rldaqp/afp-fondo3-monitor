from __future__ import annotations

import json
import math
import re
import unicodedata
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_squared_error, r2_score
from sklearn.preprocessing import StandardScaler


AFPS = ["Habitat", "Integra", "Prima", "Profuturo"]

LAGS_MERCADO = [0, 1, 2, 3]
TRAIN_FRAC = 0.60
VALID_FRAC = 0.20
MAX_FACTORES_POR_AFP = 8
MAX_FACTORES_POR_FAMILIA = 2
ALPHAS = [0.01, 0.1, 1.0, 10.0, 100.0]

MIN_OBS_CORR = 120
UMBRAL_TRAIN = 0.15
UMBRAL_VALID = 0.10
UMBRAL_TEST_CONFIRMACION = 0.10


def limpiar_nombre(valor: object) -> str:
    texto = str(valor).strip().upper()
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(
        caracter
        for caracter in texto
        if not unicodedata.combining(caracter)
    )
    return re.sub(r"[^A-Z0-9]+", "", texto)


def leer_csv_flexible(ruta: Path) -> pd.DataFrame:
    intentos = [
        {"sep": None, "engine": "python", "encoding": "utf-8-sig"},
        {"sep": None, "engine": "python", "encoding": "latin-1"},
        {"sep": ",", "encoding": "utf-8-sig"},
        {"sep": ";", "encoding": "utf-8-sig"},
        {"sep": ";", "encoding": "latin-1"},
    ]

    ultimo_error: Exception | None = None

    for argumentos in intentos:
        try:
            return pd.read_csv(ruta, **argumentos)
        except Exception as error:
            ultimo_error = error

    raise RuntimeError(
        f"No se pudo leer {ruta}: {ultimo_error}"
    )


def detectar_columna(
    columnas: Iterable[object],
    alias: set[str],
) -> str | None:
    alias_limpios = {
        limpiar_nombre(valor)
        for valor in alias
    }

    for columna in columnas:
        if limpiar_nombre(columna) in alias_limpios:
            return str(columna)

    for columna in columnas:
        limpio = limpiar_nombre(columna)

        for candidato in sorted(
            alias_limpios,
            key=len,
            reverse=True,
        ):
            if (
                candidato
                and (
                    limpio.startswith(candidato)
                    or limpio.endswith(candidato)
                )
            ):
                return str(columna)

    return None


def normalizar_afp(valor: object) -> str | None:
    limpio = limpiar_nombre(valor)

    for afp in AFPS:
        if limpiar_nombre(afp) in limpio:
            return afp

    return None


def cargar_objetivo_sbs(
    processed: Path,
) -> pd.DataFrame:
    ruta = (
        processed
        / "sbs_fondo3_base_maestra.csv"
    )

    if not ruta.exists():
        raise FileNotFoundError(
            f"No existe la base SBS: {ruta}"
        )

    df = leer_csv_flexible(ruta)

    fecha_col = detectar_columna(
        df.columns,
        {
            "fecha",
            "date",
            "fecha_cuota",
            "fecha_valor_cuota",
        },
    )
    afp_col = detectar_columna(
        df.columns,
        {
            "afp",
            "administradora",
            "nombre_afp",
        },
    )
    valor_col = detectar_columna(
        df.columns,
        {
            "valor_cuota",
            "valor_de_la_cuota",
            "cuota",
            "valor",
        },
    )
    retorno_col = detectar_columna(
        df.columns,
        {
            "retorno_diario",
            "retorno",
            "return",
            "rentabilidad_diaria",
            "variacion_diaria",
        },
    )

    if fecha_col is None or afp_col is None:
        raise ValueError(
            "No se identificaron fecha y AFP "
            "en la base SBS."
        )

    base = pd.DataFrame(
        {
            "fecha": pd.to_datetime(
                df[fecha_col],
                errors="coerce",
            ),
            "afp": df[afp_col].map(
                normalizar_afp
            ),
        }
    )

    if valor_col is not None:
        base["valor_cuota"] = pd.to_numeric(
            df[valor_col],
            errors="coerce",
        )
        base = base.sort_values(
            ["afp", "fecha"]
        )
        base["retorno_afp"] = (
            base.groupby("afp")[
                "valor_cuota"
            ]
            .pct_change(fill_method=None)
        )
        metodo = "pct_change_valor_cuota"

    elif retorno_col is not None:
        valores = pd.to_numeric(
            df[retorno_col],
            errors="coerce",
        )
        limpio = limpiar_nombre(retorno_col)

        if any(
            token in limpio
            for token in [
                "PCT",
                "PORCENTAJE",
                "PERCENT",
            ]
        ):
            valores = valores / 100.0

        base["retorno_afp"] = valores
        metodo = "columna_retorno"

    else:
        raise ValueError(
            "No se encontró valor cuota ni retorno "
            "en la base SBS."
        )

    salida = (
        base.dropna(
            subset=[
                "fecha",
                "afp",
                "retorno_afp",
            ]
        )
        .sort_values(
            ["fecha", "afp"]
        )
        .drop_duplicates(
            subset=["fecha", "afp"],
            keep="last",
        )
        .reset_index(drop=True)
    )

    salida.attrs["metodo_objetivo"] = metodo
    return salida


def inferir_transformacion_factor(
    serie: pd.Series,
    nombre: str,
) -> str:
    valores = pd.to_numeric(
        serie,
        errors="coerce",
    ).dropna()

    if len(valores) < 30:
        return "insuficiente"

    limpio = limpiar_nombre(nombre)
    fraccion_negativa = float(
        (valores < 0).mean()
    )
    fraccion_positiva = float(
        (valores > 0).mean()
    )
    p99_abs = float(
        valores.abs().quantile(0.99)
    )

    # Ya parece una serie de retornos o variaciones.
    if (
        fraccion_negativa > 0.05
        and fraccion_positiva > 0.05
        and p99_abs <= 0.50
    ):
        return "ya_es_variacion"

    # Tasas y rendimientos se modelan mejor en diferencias.
    if any(
        token in limpio
        for token in [
            "YIELD",
            "RATE",
            "TASA",
            "TREASURY",
            "TNX",
            "IRX",
            "FVX",
            "TYX",
        ]
    ):
        return "diferencia"

    return "retorno_porcentual"


def cargar_factores_mercado(
    processed: Path,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    ruta = (
        processed
        / "mercados_factores_modelo.csv"
    )

    if not ruta.exists():
        raise FileNotFoundError(
            f"No existe el archivo de mercados: {ruta}"
        )

    df = leer_csv_flexible(ruta)

    fecha_col = detectar_columna(
        df.columns,
        {
            "fecha",
            "date",
            "trading_date",
        },
    )

    if fecha_col is None:
        fecha_col = str(df.columns[0])

    fechas = pd.to_datetime(
        df[fecha_col],
        errors="coerce",
    )

    salida = pd.DataFrame(
        {"fecha": fechas}
    )
    auditoria = []

    for columna in df.columns:
        if str(columna) == fecha_col:
            continue

        serie = pd.to_numeric(
            df[columna],
            errors="coerce",
        )

        if serie.notna().sum() < 120:
            continue

        metodo = inferir_transformacion_factor(
            serie,
            str(columna),
        )

        if metodo == "ya_es_variacion":
            transformada = serie

        elif metodo == "diferencia":
            transformada = serie.diff()

        elif metodo == "retorno_porcentual":
            transformada = serie.pct_change(
                fill_method=None
            )

        else:
            continue

        nombre_factor = str(columna)
        salida[nombre_factor] = transformada

        auditoria.append(
            {
                "factor": nombre_factor,
                "metodo_transformacion": metodo,
                "observaciones_originales": int(
                    serie.notna().sum()
                ),
                "observaciones_transformadas": int(
                    transformada.notna().sum()
                ),
                "p99_abs_transformado": float(
                    transformada.dropna()
                    .abs()
                    .quantile(0.99)
                ),
            }
        )

    salida = (
        salida.dropna(subset=["fecha"])
        .sort_values("fecha")
        .drop_duplicates(
            subset=["fecha"],
            keep="last",
        )
        .reset_index(drop=True)
    )

    return salida, pd.DataFrame(auditoria)


def familia_factor(nombre: str) -> str:
    limpio = limpiar_nombre(nombre)

    reglas = [
        (
            "tecnologia_semiconductores",
            [
                "QQQ",
                "SOXX",
                "SMH",
                "NASDAQ",
                "TECH",
                "SEMICON",
            ],
        ),
        (
            "acciones_globales_usa",
            [
                "ACWI",
                "SPY",
                "VOO",
                "IVV",
                "VT",
                "WORLD",
                "MSCI",
            ],
        ),
        (
            "acciones_regionales",
            [
                "EEM",
                "VGK",
                "EZU",
                "EWJ",
                "EUROPE",
                "JAPAN",
                "EMERGING",
            ],
        ),
        (
            "bonos_credito",
            [
                "LQD",
                "HYG",
                "BOND",
                "TREASURY",
                "TLT",
                "IEF",
                "SHY",
            ],
        ),
        (
            "tipo_cambio",
            [
                "USD",
                "PEN",
                "FX",
                "DXY",
                "EUR",
                "JPY",
            ],
        ),
        (
            "materias_primas",
            [
                "GOLD",
                "GDX",
                "COPPER",
                "OIL",
                "WTI",
                "COMMOD",
                "XLB",
                "REMX",
            ],
        ),
        (
            "volatilidad",
            [
                "VIX",
                "VOL",
            ],
        ),
    ]

    for familia, tokens in reglas:
        if any(token in limpio for token in tokens):
            return familia

    return "otros"


def dividir_fechas(
    objetivo: pd.DataFrame,
    factores: pd.DataFrame,
) -> tuple[
    pd.Timestamp,
    pd.Timestamp,
    pd.DataFrame,
]:
    fechas_objetivo = set(
        objetivo["fecha"].dropna().unique()
    )
    fechas_factores = set(
        factores["fecha"].dropna().unique()
    )

    comunes = sorted(
        fechas_objetivo
        & fechas_factores
    )

    if len(comunes) < 800:
        raise RuntimeError(
            "Hay muy pocas fechas comunes entre "
            "SBS y mercados."
        )

    n = len(comunes)
    fin_train_idx = max(
        int(math.floor(n * TRAIN_FRAC)) - 1,
        0,
    )
    fin_valid_idx = max(
        int(
            math.floor(
                n
                * (
                    TRAIN_FRAC
                    + VALID_FRAC
                )
            )
        )
        - 1,
        fin_train_idx + 1,
    )

    fin_train = pd.Timestamp(
        comunes[fin_train_idx]
    )
    fin_valid = pd.Timestamp(
        comunes[fin_valid_idx]
    )

    tabla = pd.DataFrame(
        [
            {
                "segmento": "entrenamiento_descubrimiento",
                "fecha_inicio": pd.Timestamp(
                    comunes[0]
                ),
                "fecha_fin": fin_train,
                "observaciones_fecha": (
                    fin_train_idx + 1
                ),
                "uso": (
                    "seleccionar rezagos y medir "
                    "correlaciones iniciales"
                ),
            },
            {
                "segmento": "validacion",
                "fecha_inicio": pd.Timestamp(
                    comunes[fin_train_idx + 1]
                ),
                "fecha_fin": fin_valid,
                "observaciones_fecha": (
                    fin_valid_idx
                    - fin_train_idx
                ),
                "uso": (
                    "confirmar estabilidad y elegir "
                    "regularizacion"
                ),
            },
            {
                "segmento": "prueba_intocable",
                "fecha_inicio": pd.Timestamp(
                    comunes[fin_valid_idx + 1]
                ),
                "fecha_fin": pd.Timestamp(
                    comunes[-1]
                ),
                "observaciones_fecha": (
                    n
                    - fin_valid_idx
                    - 1
                ),
                "uso": (
                    "medir desempeño final sin "
                    "seleccionar variables"
                ),
            },
        ]
    )

    return fin_train, fin_valid, tabla


def segmento_fecha(
    fecha: pd.Timestamp,
    fin_train: pd.Timestamp,
    fin_valid: pd.Timestamp,
) -> str:
    if fecha <= fin_train:
        return "train"

    if fecha <= fin_valid:
        return "valid"

    return "test"


def construir_base_afp(
    objetivo_afp: pd.DataFrame,
    factores: pd.DataFrame,
    lags: list[int],
) -> pd.DataFrame:
    mercado = factores.sort_values(
        "fecha"
    ).copy()

    columnas_factores = [
        columna
        for columna in mercado.columns
        if columna != "fecha"
    ]

    rezagados = pd.DataFrame(
        {"fecha": mercado["fecha"]}
    )

    for factor in columnas_factores:
        for lag in lags:
            rezagados[
                f"{factor}__lag{lag}"
            ] = mercado[factor].shift(lag)

    return (
        objetivo_afp[
            ["fecha", "retorno_afp"]
        ]
        .merge(
            rezagados,
            on="fecha",
            how="inner",
            validate="one_to_one",
        )
        .sort_values("fecha")
        .reset_index(drop=True)
    )


def correlacion_segura(
    x: pd.Series,
    y: pd.Series,
    metodo: str,
) -> tuple[float, int]:
    pares = pd.DataFrame(
        {
            "x": pd.to_numeric(
                x,
                errors="coerce",
            ),
            "y": pd.to_numeric(
                y,
                errors="coerce",
            ),
        }
    ).dropna()

    n = len(pares)

    if n < MIN_OBS_CORR:
        return np.nan, n

    if (
        pares["x"].std(ddof=1) == 0
        or pares["y"].std(ddof=1) == 0
    ):
        return np.nan, n

    if metodo == "pearson":
        valor = pares["x"].corr(
            pares["y"],
            method="pearson",
        )
    else:
        valor = spearmanr(
            pares["x"],
            pares["y"],
        ).statistic

    return float(valor), n


def calcular_correlaciones(
    objetivo: pd.DataFrame,
    factores: pd.DataFrame,
    fin_train: pd.Timestamp,
    fin_valid: pd.Timestamp,
) -> pd.DataFrame:
    filas = []

    for afp in AFPS:
        objetivo_afp = objetivo[
            objetivo["afp"].eq(afp)
        ].copy()

        base = construir_base_afp(
            objetivo_afp,
            factores,
            LAGS_MERCADO,
        )
        base["segmento"] = base[
            "fecha"
        ].map(
            lambda fecha: segmento_fecha(
                fecha,
                fin_train,
                fin_valid,
            )
        )

        factores_originales = [
            columna
            for columna in factores.columns
            if columna != "fecha"
        ]

        for factor in factores_originales:
            resultados_lag = []

            for lag in LAGS_MERCADO:
                columna = f"{factor}__lag{lag}"
                train = base[
                    base["segmento"].eq(
                        "train"
                    )
                ]

                corr_s, n_train = (
                    correlacion_segura(
                        train[columna],
                        train["retorno_afp"],
                        "spearman",
                    )
                )
                corr_p, _ = correlacion_segura(
                    train[columna],
                    train["retorno_afp"],
                    "pearson",
                )

                resultados_lag.append(
                    {
                        "lag": lag,
                        "corr_s_train": corr_s,
                        "corr_p_train": corr_p,
                        "n_train": n_train,
                    }
                )

            resultados_validos = [
                registro
                for registro in resultados_lag
                if pd.notna(
                    registro["corr_s_train"]
                )
            ]

            if not resultados_validos:
                continue

            mejor = max(
                resultados_validos,
                key=lambda registro: abs(
                    registro["corr_s_train"]
                ),
            )
            lag = int(mejor["lag"])
            columna = f"{factor}__lag{lag}"

            valores = {
                "afp": afp,
                "factor": factor,
                "familia": familia_factor(
                    factor
                ),
                "mejor_lag_train": lag,
                **mejor,
            }

            for segmento in [
                "valid",
                "test",
            ]:
                bloque = base[
                    base["segmento"].eq(
                        segmento
                    )
                ]
                corr_s, n_seg = (
                    correlacion_segura(
                        bloque[columna],
                        bloque["retorno_afp"],
                        "spearman",
                    )
                )
                corr_p, _ = correlacion_segura(
                    bloque[columna],
                    bloque["retorno_afp"],
                    "pearson",
                )

                valores[
                    f"corr_s_{segmento}"
                ] = corr_s
                valores[
                    f"corr_p_{segmento}"
                ] = corr_p
                valores[
                    f"n_{segmento}"
                ] = n_seg

            signo_train = np.sign(
                valores["corr_s_train"]
            )
            signo_valid = np.sign(
                valores["corr_s_valid"]
            ) if pd.notna(
                valores["corr_s_valid"]
            ) else 0
            signo_test = np.sign(
                valores["corr_s_test"]
            ) if pd.notna(
                valores["corr_s_test"]
            ) else 0

            valores[
                "estable_train_valid"
            ] = bool(
                abs(
                    valores[
                        "corr_s_train"
                    ]
                )
                >= UMBRAL_TRAIN
                and abs(
                    valores[
                        "corr_s_valid"
                    ]
                )
                >= UMBRAL_VALID
                and signo_train
                == signo_valid
            )

            valores[
                "confirmada_en_test"
            ] = bool(
                valores[
                    "estable_train_valid"
                ]
                and abs(
                    valores["corr_s_test"]
                )
                >= UMBRAL_TEST_CONFIRMACION
                and signo_train
                == signo_test
            )

            valores[
                "score_pretest"
            ] = (
                min(
                    abs(
                        valores[
                            "corr_s_train"
                        ]
                    ),
                    abs(
                        valores[
                            "corr_s_valid"
                        ]
                    ),
                )
                if pd.notna(
                    valores[
                        "corr_s_valid"
                    ]
                )
                else 0.0
            )

            minimo_confirmado = min(
                abs(
                    valores[
                        "corr_s_train"
                    ]
                ),
                abs(
                    valores[
                        "corr_s_valid"
                    ]
                )
                if pd.notna(
                    valores[
                        "corr_s_valid"
                    ]
                )
                else 0.0,
                abs(
                    valores[
                        "corr_s_test"
                    ]
                )
                if pd.notna(
                    valores[
                        "corr_s_test"
                    ]
                )
                else 0.0,
            )

            if (
                valores[
                    "confirmada_en_test"
                ]
                and minimo_confirmado
                >= 0.40
            ):
                nivel = "alta_y_estable"

            elif (
                valores[
                    "confirmada_en_test"
                ]
                and minimo_confirmado
                >= 0.25
            ):
                nivel = "moderada_y_estable"

            elif valores[
                "confirmada_en_test"
            ]:
                nivel = "debil_pero_estable"

            elif valores[
                "estable_train_valid"
            ]:
                nivel = (
                    "no_confirmada_en_test"
                )

            else:
                nivel = (
                    "sin_relacion_estable"
                )

            valores[
                "nivel_relacion"
            ] = nivel
            valores[
                "direccion_relacion"
            ] = (
                "positiva"
                if signo_train > 0
                else "negativa"
            )

            filas.append(valores)

    resultado = pd.DataFrame(filas)

    if resultado.empty:
        raise RuntimeError(
            "No se pudieron calcular correlaciones."
        )

    resultado["ranking_pretest"] = (
        resultado.groupby("afp")[
            "score_pretest"
        ]
        .rank(
            method="first",
            ascending=False,
        )
        .astype(int)
    )

    return resultado.sort_values(
        [
            "afp",
            "ranking_pretest",
        ]
    ).reset_index(drop=True)


def seleccionar_factores(
    correlaciones: pd.DataFrame,
) -> pd.DataFrame:
    seleccionados = []

    for afp in AFPS:
        candidatos = (
            correlaciones[
                correlaciones["afp"].eq(afp)
                & correlaciones[
                    "estable_train_valid"
                ].eq(True)
            ]
            .sort_values(
                "score_pretest",
                ascending=False,
            )
        )

        conteo_familia: dict[str, int] = {}

        for _, fila in candidatos.iterrows():
            familia = str(
                fila["familia"]
            )
            actual = conteo_familia.get(
                familia,
                0,
            )

            if actual >= MAX_FACTORES_POR_FAMILIA:
                continue

            seleccionados.append(
                fila.to_dict()
            )
            conteo_familia[
                familia
            ] = actual + 1

            if (
                sum(
                    1
                    for registro
                    in seleccionados
                    if registro["afp"] == afp
                )
                >= MAX_FACTORES_POR_AFP
            ):
                break

    salida = pd.DataFrame(
        seleccionados
    )

    if salida.empty:
        return salida

    salida["orden_modelo"] = (
        salida.groupby("afp")
        .cumcount()
        + 1
    )

    return salida


def ajustar_y_evaluar_modelo(
    objetivo: pd.DataFrame,
    factores: pd.DataFrame,
    seleccion: pd.DataFrame,
    fin_train: pd.Timestamp,
    fin_valid: pd.Timestamp,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    metricas = []
    predicciones = []

    for afp in AFPS:
        seleccion_afp = seleccion[
            seleccion["afp"].eq(afp)
        ]

        if seleccion_afp.empty:
            metricas.append(
                {
                    "afp": afp,
                    "estado_modelo": (
                        "sin_factores_estables"
                    ),
                }
            )
            continue

        objetivo_afp = objetivo[
            objetivo["afp"].eq(afp)
        ].copy()
        base = construir_base_afp(
            objetivo_afp,
            factores,
            LAGS_MERCADO,
        )
        base["segmento"] = base[
            "fecha"
        ].map(
            lambda fecha: segmento_fecha(
                fecha,
                fin_train,
                fin_valid,
            )
        )

        columnas = [
            f"{fila['factor']}__lag{int(fila['mejor_lag_train'])}"
            for _, fila in seleccion_afp.iterrows()
        ]

        base_modelo = base[
            [
                "fecha",
                "retorno_afp",
                "segmento",
            ]
            + columnas
        ].dropna()

        train = base_modelo[
            base_modelo["segmento"].eq(
                "train"
            )
        ]
        valid = base_modelo[
            base_modelo["segmento"].eq(
                "valid"
            )
        ]
        test = base_modelo[
            base_modelo["segmento"].eq(
                "test"
            )
        ]

        if (
            len(train) < 250
            or len(valid) < 100
            or len(test) < 100
        ):
            metricas.append(
                {
                    "afp": afp,
                    "estado_modelo": (
                        "muestra_insuficiente"
                    ),
                    "n_train": len(train),
                    "n_valid": len(valid),
                    "n_test": len(test),
                }
            )
            continue

        scaler_train = StandardScaler()
        x_train = scaler_train.fit_transform(
            train[columnas]
        )
        x_valid = scaler_train.transform(
            valid[columnas]
        )
        y_train = train[
            "retorno_afp"
        ].to_numpy()
        y_valid = valid[
            "retorno_afp"
        ].to_numpy()

        evaluacion_alpha = []

        for alpha in ALPHAS:
            modelo = Ridge(alpha=alpha)
            modelo.fit(
                x_train,
                y_train,
            )
            pred_valid = modelo.predict(
                x_valid
            )
            rmse_valid = float(
                mean_squared_error(
                    y_valid,
                    pred_valid,
                ) ** 0.5
            )
            evaluacion_alpha.append(
                (
                    rmse_valid,
                    alpha,
                )
            )

        _, mejor_alpha = min(
            evaluacion_alpha,
            key=lambda par: par[0],
        )

        train_valid = base_modelo[
            base_modelo[
                "segmento"
            ].isin(
                [
                    "train",
                    "valid",
                ]
            )
        ]

        scaler_final = StandardScaler()
        x_train_valid = (
            scaler_final.fit_transform(
                train_valid[columnas]
            )
        )
        x_test = scaler_final.transform(
            test[columnas]
        )
        y_train_valid = train_valid[
            "retorno_afp"
        ].to_numpy()
        y_test = test[
            "retorno_afp"
        ].to_numpy()

        modelo_final = Ridge(
            alpha=mejor_alpha
        )
        modelo_final.fit(
            x_train_valid,
            y_train_valid,
        )
        pred_test = modelo_final.predict(
            x_test
        )

        rmse_test = float(
            mean_squared_error(
                y_test,
                pred_test,
            ) ** 0.5
        )
        rmse_cero = float(
            mean_squared_error(
                y_test,
                np.zeros_like(y_test),
            ) ** 0.5
        )
        r2_test = float(
            r2_score(
                y_test,
                pred_test,
            )
        )
        direccion = float(
            (
                np.sign(y_test)
                == np.sign(pred_test)
            ).mean()
            * 100.0
        )

        metricas.append(
            {
                "afp": afp,
                "estado_modelo": "evaluado",
                "factores_usados": len(
                    columnas
                ),
                "lista_factores": " | ".join(
                    columnas
                ),
                "alpha_seleccionado": (
                    mejor_alpha
                ),
                "n_train": len(train),
                "n_valid": len(valid),
                "n_test": len(test),
                "rmse_test": rmse_test,
                "rmse_baseline_cero": (
                    rmse_cero
                ),
                "mejora_rmse_vs_cero_pct": (
                    (
                        rmse_cero
                        - rmse_test
                    )
                    / rmse_cero
                    * 100.0
                ),
                "r2_test": r2_test,
                "direccion_correcta_test_pct": (
                    direccion
                ),
            }
        )

        predicciones.append(
            pd.DataFrame(
                {
                    "fecha": test["fecha"],
                    "afp": afp,
                    "retorno_real": y_test,
                    "retorno_predicho": (
                        pred_test
                    ),
                    "segmento": (
                        "prueba_intocable"
                    ),
                }
            )
        )

    return (
        pd.DataFrame(metricas),
        (
            pd.concat(
                predicciones,
                ignore_index=True,
            )
            if predicciones
            else pd.DataFrame()
        ),
    )


def construir_control(
    objetivo: pd.DataFrame,
    factores: pd.DataFrame,
    correlaciones: pd.DataFrame,
    seleccion: pd.DataFrame,
    metricas: pd.DataFrame,
) -> pd.DataFrame:
    controles = [
        {
            "control": "cuatro_afp_objetivo",
            "estado": (
                "correcto"
                if set(
                    objetivo["afp"]
                )
                == set(AFPS)
                else "revisar"
            ),
            "detalle": (
                f"afp={objetivo['afp'].nunique()}"
            ),
        },
        {
            "control": "factores_disponibles",
            "estado": (
                "correcto"
                if factores.shape[1] > 5
                else "revisar"
            ),
            "detalle": (
                f"factores={factores.shape[1] - 1}"
            ),
        },
        {
            "control": "seleccion_sin_test",
            "estado": "correcto",
            "detalle": (
                "rezagos y factores se eligen solo con "
                "train y validación"
            ),
        },
        {
            "control": "prueba_no_usada_para_seleccion",
            "estado": "correcto",
            "detalle": (
                "test se usa únicamente para confirmar "
                "y medir desempeño final"
            ),
        },
        {
            "control": "correlaciones_generadas",
            "estado": (
                "correcto"
                if not correlaciones.empty
                else "revisar"
            ),
            "detalle": (
                f"filas={len(correlaciones)}"
            ),
        },
        {
            "control": "factores_estables_seleccionados",
            "estado": (
                "correcto"
                if not seleccion.empty
                else "revisar"
            ),
            "detalle": (
                f"filas={len(seleccion)}"
            ),
        },
        {
            "control": "modelos_test_evaluados",
            "estado": (
                "correcto"
                if (
                    not metricas.empty
                    and metricas[
                        "estado_modelo"
                    ].eq("evaluado").sum()
                    == 4
                )
                else "revisar"
            ),
            "detalle": (
                f"evaluados="
                f"{int(metricas['estado_modelo'].eq('evaluado').sum())}"
                if not metricas.empty
                else "evaluados=0"
            ),
        },
    ]

    return pd.DataFrame(controles)


def exportar_json(
    division: pd.DataFrame,
    seleccion: pd.DataFrame,
    metricas: pd.DataFrame,
    control: pd.DataFrame,
    ruta: Path,
) -> None:
    def limpiar_registro(
        registro: dict[str, object],
    ) -> dict[str, object]:
        limpio: dict[str, object] = {}

        for clave, valor in registro.items():
            if isinstance(
                valor,
                (pd.Timestamp, np.datetime64),
            ):
                limpio[clave] = (
                    pd.Timestamp(valor).strftime(
                        "%Y-%m-%d"
                    )
                    if pd.notna(valor)
                    else None
                )
            elif pd.isna(valor):
                limpio[clave] = None
            elif isinstance(
                valor,
                np.generic,
            ):
                limpio[clave] = valor.item()
            else:
                limpio[clave] = valor

        return limpio

    contenido = {
        "version": (
            "modelo50_mapa_relaciones_y_prueba"
        ),
        "division_temporal": [
            limpiar_registro(registro)
            for registro in division.to_dict(
                orient="records"
            )
        ],
        "relaciones_seleccionadas": [
            limpiar_registro(registro)
            for registro in seleccion.to_dict(
                orient="records"
            )
        ],
        "metricas_prueba": [
            limpiar_registro(registro)
            for registro in metricas.to_dict(
                orient="records"
            )
        ],
        "control": control.to_dict(
            orient="records"
        ),
        "nota": (
            "La correlación se calcula sobre variaciones "
            "diarias, no sobre niveles de precios. El conjunto "
            "de prueba no participa en la selección de factores."
        ),
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

    objetivo = cargar_objetivo_sbs(
        processed
    )
    factores, auditoria_factores = (
        cargar_factores_mercado(
            processed
        )
    )
    (
        fin_train,
        fin_valid,
        division,
    ) = dividir_fechas(
        objetivo,
        factores,
    )
    correlaciones = calcular_correlaciones(
        objetivo,
        factores,
        fin_train,
        fin_valid,
    )
    seleccion = seleccionar_factores(
        correlaciones
    )
    metricas, predicciones = (
        ajustar_y_evaluar_modelo(
            objetivo,
            factores,
            seleccion,
            fin_train,
            fin_valid,
        )
    )
    control = construir_control(
        objetivo,
        factores,
        correlaciones,
        seleccion,
        metricas,
    )

    rutas = {
        "division": (
            processed
            / "ca0001_modelo50_division_temporal.csv"
        ),
        "auditoria_factores": (
            processed
            / "ca0001_modelo50_transformacion_factores.csv"
        ),
        "correlaciones": (
            processed
            / "ca0001_modelo50_correlaciones_rezagadas.csv"
        ),
        "seleccion": (
            processed
            / "ca0001_modelo50_relaciones_seleccionadas.csv"
        ),
        "metricas": (
            processed
            / "ca0001_modelo50_metricas_prueba.csv"
        ),
        "predicciones": (
            processed
            / "ca0001_modelo50_predicciones_prueba.csv"
        ),
        "control": (
            processed
            / "ca0001_modelo50_control.csv"
        ),
        "json": (
            processed
            / "ca0001_modelo50_resumen.json"
        ),
    }

    division.to_csv(
        rutas["division"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    auditoria_factores.to_csv(
        rutas["auditoria_factores"],
        index=False,
        encoding="utf-8-sig",
    )
    correlaciones.to_csv(
        rutas["correlaciones"],
        index=False,
        encoding="utf-8-sig",
    )
    seleccion.to_csv(
        rutas["seleccion"],
        index=False,
        encoding="utf-8-sig",
    )
    metricas.to_csv(
        rutas["metricas"],
        index=False,
        encoding="utf-8-sig",
    )
    predicciones.to_csv(
        rutas["predicciones"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    control.to_csv(
        rutas["control"],
        index=False,
        encoding="utf-8-sig",
    )
    exportar_json(
        division,
        seleccion,
        metricas,
        control,
        rutas["json"],
    )

    print(
        "\nMAPA DE RELACIONES Y PRUEBA TEMPORAL TERMINADOS"
    )
    print("=" * 120)

    print("\nDIVISIÓN TEMPORAL")
    print("-" * 120)
    print(
        division.to_string(index=False)
    )

    print("\nRELACIONES SELECCIONADAS POR AFP")
    print("-" * 120)

    if seleccion.empty:
        print(
            "No se encontraron relaciones estables "
            "con los umbrales actuales."
        )
    else:
        columnas_mostrar = [
            "afp",
            "orden_modelo",
            "factor",
            "familia",
            "mejor_lag_train",
            "corr_s_train",
            "corr_s_valid",
            "corr_s_test",
            "estable_train_valid",
            "confirmada_en_test",
            "nivel_relacion",
            "direccion_relacion",
        ]

        print(
            seleccion[
                columnas_mostrar
            ].to_string(index=False)
        )

    print("\nDESEMPEÑO EN PRUEBA INTACTA")
    print("-" * 120)
    print(
        metricas.to_string(index=False)
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
        "- El primer 60 % del histórico descubre correlaciones y rezagos.\n"
        "- El siguiente 20 % confirma estabilidad y elige la regularización.\n"
        "- El último 20 % queda intacto hasta la evaluación final.\n"
        "- La selección nunca usa la correlación del test.\n"
        "- Se correlacionan variaciones diarias, no niveles de precios.\n"
        "- Un factor solo se considera útil para seguimiento si mantiene "
        "signo y magnitud razonable fuera del periodo donde fue descubierto."
    )


if __name__ == "__main__":
    main()
