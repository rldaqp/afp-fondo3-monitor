from __future__ import annotations

import json
import math
import re
import unicodedata
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_squared_error, r2_score
from sklearn.preprocessing import StandardScaler


AFPS = ["Habitat", "Integra", "Prima", "Profuturo"]
ALPHAS = [0.01, 0.1, 1.0, 10.0, 100.0]

MAX_FACTORES = 5
UMBRAL_DUPLICADO_EXACTO = 0.9999
UMBRAL_REDUNDANCIA = 0.92
MEJORA_MINIMA_VALID_PCT = 0.25

DESCRIPCIONES = {
    "ret_COPX": "ETF de mineras de cobre",
    "ret_EPU": "ETF de acciones peruanas",
    "ret_EEM": "ETF de mercados emergentes",
    "ret_MCHI": "ETF de acciones chinas",
    "ret_XLB": "ETF del sector materiales de Estados Unidos",
    "ret_VGK": "ETF de acciones europeas",
    "ret_ACWI": "ETF de acciones mundiales",
    "ret_IDX_VIX": "Índice de volatilidad VIX",
    "vix_retorno": "Índice de volatilidad VIX",
    "ret_QQQ": "ETF Nasdaq 100 / tecnología",
    "ret_SPY": "ETF S&P 500",
    "ret_SMH": "ETF de semiconductores",
    "ret_SOXX": "ETF de semiconductores",
    "ret_HYG": "ETF de bonos corporativos de alto rendimiento",
    "ret_LQD": "ETF de bonos corporativos grado de inversión",
    "ret_GDX": "ETF de mineras de oro",
    "ret_EWJ": "ETF de acciones japonesas",
}

PREFERENCIA_NOMBRE = {
    "ret_IDX_VIX": 0,
    "vix_retorno": 1,
}


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

    raise RuntimeError(f"No se pudo leer {ruta}: {ultimo_error}")


def detectar_columna(
    columnas: Iterable[object],
    alias: set[str],
) -> str | None:
    alias_limpios = {limpiar_nombre(valor) for valor in alias}

    for columna in columnas:
        if limpiar_nombre(columna) in alias_limpios:
            return str(columna)

    for columna in columnas:
        limpio = limpiar_nombre(columna)
        for candidato in sorted(alias_limpios, key=len, reverse=True):
            if candidato and (
                limpio.startswith(candidato)
                or limpio.endswith(candidato)
            ):
                return str(columna)

    return None


def normalizar_afp(valor: object) -> str | None:
    limpio = limpiar_nombre(valor)

    for afp in AFPS:
        if limpiar_nombre(afp) in limpio:
            return afp

    return None


def cargar_objetivo_sbs(processed: Path) -> pd.DataFrame:
    ruta = processed / "sbs_fondo3_base_maestra.csv"

    if not ruta.exists():
        raise FileNotFoundError(f"No existe la base SBS: {ruta}")

    df = leer_csv_flexible(ruta)

    fecha_col = detectar_columna(
        df.columns,
        {"fecha", "date", "fecha_cuota", "fecha_valor_cuota"},
    )
    afp_col = detectar_columna(
        df.columns,
        {"afp", "administradora", "nombre_afp"},
    )
    valor_col = detectar_columna(
        df.columns,
        {"valor_cuota", "valor_de_la_cuota", "cuota", "valor"},
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
        raise ValueError("No se identificaron fecha y AFP en la base SBS.")

    base = pd.DataFrame(
        {
            "fecha": pd.to_datetime(df[fecha_col], errors="coerce"),
            "afp": df[afp_col].map(normalizar_afp),
        }
    )

    if valor_col is not None:
        base["valor_cuota"] = pd.to_numeric(
            df[valor_col],
            errors="coerce",
        )
        base = base.sort_values(["afp", "fecha"])
        base["retorno_afp"] = (
            base.groupby("afp")["valor_cuota"]
            .pct_change(fill_method=None)
        )

    elif retorno_col is not None:
        valores = pd.to_numeric(
            df[retorno_col],
            errors="coerce",
        )
        limpio = limpiar_nombre(retorno_col)

        if any(
            token in limpio
            for token in ["PCT", "PORCENTAJE", "PERCENT"]
        ):
            valores = valores / 100.0

        base["retorno_afp"] = valores

    else:
        raise ValueError(
            "No se encontró valor cuota ni retorno en la base SBS."
        )

    return (
        base.dropna(subset=["fecha", "afp", "retorno_afp"])
        .sort_values(["fecha", "afp"])
        .drop_duplicates(subset=["fecha", "afp"], keep="last")
        .reset_index(drop=True)
    )


def inferir_transformacion_factor(
    serie: pd.Series,
    nombre: str,
) -> str:
    valores = pd.to_numeric(serie, errors="coerce").dropna()

    if len(valores) < 30:
        return "insuficiente"

    limpio = limpiar_nombre(nombre)
    fraccion_negativa = float((valores < 0).mean())
    fraccion_positiva = float((valores > 0).mean())
    p99_abs = float(valores.abs().quantile(0.99))

    if (
        fraccion_negativa > 0.05
        and fraccion_positiva > 0.05
        and p99_abs <= 0.50
    ):
        return "ya_es_variacion"

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


def cargar_factores_mercado(processed: Path) -> pd.DataFrame:
    ruta = processed / "mercados_factores_modelo.csv"

    if not ruta.exists():
        raise FileNotFoundError(
            f"No existe el archivo de mercados: {ruta}"
        )

    df = leer_csv_flexible(ruta)
    fecha_col = detectar_columna(
        df.columns,
        {"fecha", "date", "trading_date"},
    )

    if fecha_col is None:
        fecha_col = str(df.columns[0])

    salida = pd.DataFrame(
        {"fecha": pd.to_datetime(df[fecha_col], errors="coerce")}
    )

    for columna in df.columns:
        if str(columna) == fecha_col:
            continue

        serie = pd.to_numeric(df[columna], errors="coerce")

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
            transformada = serie.pct_change(fill_method=None)
        else:
            continue

        salida[str(columna)] = transformada

    return (
        salida.dropna(subset=["fecha"])
        .sort_values("fecha")
        .drop_duplicates(subset=["fecha"], keep="last")
        .reset_index(drop=True)
    )


def cargar_division(processed: Path) -> tuple[pd.Timestamp, pd.Timestamp]:
    ruta = processed / "ca0001_modelo50_division_temporal.csv"

    if not ruta.exists():
        raise FileNotFoundError(
            "Primero debe ejecutarse el módulo 50."
        )

    division = leer_csv_flexible(ruta)
    division["fecha_fin"] = pd.to_datetime(
        division["fecha_fin"],
        errors="coerce",
    )

    fin_train = division.loc[
        division["segmento"].eq("entrenamiento_descubrimiento"),
        "fecha_fin",
    ].iloc[0]
    fin_valid = division.loc[
        division["segmento"].eq("validacion"),
        "fecha_fin",
    ].iloc[0]

    return pd.Timestamp(fin_train), pd.Timestamp(fin_valid)


def cargar_candidatos(processed: Path) -> pd.DataFrame:
    ruta = processed / "ca0001_modelo50_relaciones_seleccionadas.csv"

    if not ruta.exists():
        raise FileNotFoundError(
            "No existe la selección del módulo 50."
        )

    df = leer_csv_flexible(ruta)

    for columna in [
        "corr_s_train",
        "corr_s_valid",
        "corr_s_test",
        "score_pretest",
    ]:
        if columna in df.columns:
            df[columna] = pd.to_numeric(df[columna], errors="coerce")

    if "estable_train_valid" in df.columns:
        df["estable_train_valid"] = (
            df["estable_train_valid"]
            .astype(str)
            .str.lower()
            .isin(["true", "1", "si", "sí"])
        )

    return df


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
    candidatos_afp: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, str]]:
    mercado = factores.sort_values("fecha").copy()
    rezagados = pd.DataFrame({"fecha": mercado["fecha"]})
    mapeo: dict[str, str] = {}

    for _, fila in candidatos_afp.iterrows():
        factor = str(fila["factor"])
        lag = int(fila["mejor_lag_train"])

        if factor not in mercado.columns:
            continue

        feature = f"{factor}__lag{lag}"
        rezagados[feature] = mercado[factor].shift(lag)
        mapeo[feature] = factor

    base = (
        objetivo_afp[["fecha", "retorno_afp"]]
        .merge(
            rezagados,
            on="fecha",
            how="inner",
            validate="one_to_one",
        )
        .sort_values("fecha")
        .reset_index(drop=True)
    )

    return base, mapeo


def evaluar_ridge(
    train: pd.DataFrame,
    valid: pd.DataFrame,
    columnas: list[str],
) -> tuple[float, float]:
    scaler = StandardScaler()
    x_train = scaler.fit_transform(train[columnas])
    x_valid = scaler.transform(valid[columnas])
    y_train = train["retorno_afp"].to_numpy()
    y_valid = valid["retorno_afp"].to_numpy()

    resultados = []

    for alpha in ALPHAS:
        modelo = Ridge(alpha=alpha)
        modelo.fit(x_train, y_train)
        pred = modelo.predict(x_valid)
        rmse = float(
            mean_squared_error(y_valid, pred) ** 0.5
        )
        resultados.append((rmse, alpha))

    return min(resultados, key=lambda par: par[0])


def elegir_representante_duplicado(
    grupo: list[str],
    candidatos_afp: pd.DataFrame,
    mapeo: dict[str, str],
) -> str:
    registros = []

    for feature in grupo:
        factor = mapeo[feature]
        fila = candidatos_afp[
            candidatos_afp["factor"].eq(factor)
        ].iloc[0]

        score = float(fila["score_pretest"])
        preferencia = PREFERENCIA_NOMBRE.get(factor, 100)
        registros.append(
            (
                -score,
                preferencia,
                len(factor),
                factor,
                feature,
            )
        )

    return sorted(registros)[0][-1]


def detectar_duplicados(
    train_valid: pd.DataFrame,
    features: list[str],
    candidatos_afp: pd.DataFrame,
    mapeo: dict[str, str],
) -> tuple[list[str], list[dict[str, object]]]:
    if len(features) <= 1:
        return features, []

    corr = train_valid[features].corr().abs()
    pendientes = set(features)
    conservar = []
    auditoria = []

    while pendientes:
        actual = sorted(pendientes)[0]
        grupo = [
            otro
            for otro in pendientes
            if (
                pd.notna(corr.loc[actual, otro])
                and corr.loc[actual, otro] >= UMBRAL_DUPLICADO_EXACTO
            )
        ]

        elegido = elegir_representante_duplicado(
            grupo,
            candidatos_afp,
            mapeo,
        )
        conservar.append(elegido)

        for feature in grupo:
            if feature != elegido:
                auditoria.append(
                    {
                        "factor_conservado": mapeo[elegido],
                        "factor_descartado": mapeo[feature],
                        "motivo": "duplicado_exacto",
                        "correlacion_entre_factores": float(
                            corr.loc[elegido, feature]
                        ),
                    }
                )

        pendientes.difference_update(grupo)

    return conservar, auditoria


def seleccionar_canasta_afp(
    afp: str,
    objetivo: pd.DataFrame,
    factores: pd.DataFrame,
    candidatos: pd.DataFrame,
    fin_train: pd.Timestamp,
    fin_valid: pd.Timestamp,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    candidatos_afp = candidatos[
        candidatos["afp"].eq(afp)
        & candidatos["estable_train_valid"].eq(True)
    ].copy()

    candidatos_afp = candidatos_afp.sort_values(
        ["score_pretest", "factor"],
        ascending=[False, True],
    )

    objetivo_afp = objetivo[objetivo["afp"].eq(afp)].copy()
    base, mapeo = construir_base_afp(
        objetivo_afp,
        factores,
        candidatos_afp,
    )
    base["segmento"] = base["fecha"].map(
        lambda fecha: segmento_fecha(
            fecha,
            fin_train,
            fin_valid,
        )
    )

    features = list(mapeo.keys())
    base_modelo = base[
        ["fecha", "retorno_afp", "segmento"] + features
    ].copy()

    train = base_modelo[
        base_modelo["segmento"].eq("train")
    ]
    valid = base_modelo[
        base_modelo["segmento"].eq("valid")
    ]
    train_valid = base_modelo[
        base_modelo["segmento"].isin(["train", "valid"])
    ]

    features_sin_dup, auditoria_dup = detectar_duplicados(
        train_valid,
        features,
        candidatos_afp,
        mapeo,
    )

    seleccionadas: list[str] = []
    auditoria_seleccion: list[dict[str, object]] = []
    mejor_rmse_actual: float | None = None

    ordenadas = sorted(
        features_sin_dup,
        key=lambda feature: (
            -float(
                candidatos_afp.loc[
                    candidatos_afp["factor"].eq(mapeo[feature]),
                    "score_pretest",
                ].iloc[0]
            ),
            mapeo[feature],
        ),
    )

    for feature in ordenadas:
        factor = mapeo[feature]

        if len(seleccionadas) >= MAX_FACTORES:
            auditoria_seleccion.append(
                {
                    "afp": afp,
                    "factor": factor,
                    "estado": "descartado",
                    "motivo": "limite_maximo_canasta",
                    "correlacion_max_con_canasta": np.nan,
                    "mejora_valid_pct": np.nan,
                }
            )
            continue

        corr_max = 0.0

        if seleccionadas:
            correlaciones = (
                train_valid[seleccionadas + [feature]]
                .corr()[feature]
                .drop(labels=[feature])
                .abs()
            )
            corr_max = float(correlaciones.max())

            if corr_max >= UMBRAL_REDUNDANCIA:
                auditoria_seleccion.append(
                    {
                        "afp": afp,
                        "factor": factor,
                        "estado": "descartado",
                        "motivo": "redundante_con_canasta",
                        "correlacion_max_con_canasta": corr_max,
                        "mejora_valid_pct": np.nan,
                    }
                )
                continue

        columnas_prueba = seleccionadas + [feature]
        bloque_train = train[
            ["retorno_afp"] + columnas_prueba
        ].dropna()
        bloque_valid = valid[
            ["retorno_afp"] + columnas_prueba
        ].dropna()

        if len(bloque_train) < 250 or len(bloque_valid) < 100:
            auditoria_seleccion.append(
                {
                    "afp": afp,
                    "factor": factor,
                    "estado": "descartado",
                    "motivo": "muestra_insuficiente",
                    "correlacion_max_con_canasta": corr_max,
                    "mejora_valid_pct": np.nan,
                }
            )
            continue

        rmse_nuevo, alpha_nuevo = evaluar_ridge(
            bloque_train,
            bloque_valid,
            columnas_prueba,
        )

        if mejor_rmse_actual is None:
            mejora_pct = np.nan
            aceptar = True
        else:
            mejora_pct = (
                (mejor_rmse_actual - rmse_nuevo)
                / mejor_rmse_actual
                * 100.0
            )
            aceptar = mejora_pct >= MEJORA_MINIMA_VALID_PCT

        if aceptar:
            seleccionadas.append(feature)
            mejor_rmse_actual = rmse_nuevo
            auditoria_seleccion.append(
                {
                    "afp": afp,
                    "factor": factor,
                    "estado": "seleccionado",
                    "motivo": "aporta_informacion",
                    "correlacion_max_con_canasta": corr_max,
                    "mejora_valid_pct": mejora_pct,
                    "alpha_valid": alpha_nuevo,
                    "rmse_valid_acumulado": rmse_nuevo,
                }
            )
        else:
            auditoria_seleccion.append(
                {
                    "afp": afp,
                    "factor": factor,
                    "estado": "descartado",
                    "motivo": "sin_mejora_validacion",
                    "correlacion_max_con_canasta": corr_max,
                    "mejora_valid_pct": mejora_pct,
                    "alpha_valid": alpha_nuevo,
                    "rmse_valid_acumulado": rmse_nuevo,
                }
            )

    auditoria_total = pd.DataFrame(
        [
            {
                "afp": afp,
                "factor": fila["factor_descartado"],
                "estado": "descartado",
                "motivo": fila["motivo"],
                "correlacion_max_con_canasta": fila[
                    "correlacion_entre_factores"
                ],
                "factor_equivalente_conservado": fila[
                    "factor_conservado"
                ],
            }
            for fila in auditoria_dup
        ]
        + auditoria_seleccion
    )

    if not seleccionadas:
        return pd.DataFrame(), auditoria_total, pd.DataFrame()

    columnas_finales = seleccionadas
    train_valid_final = base_modelo[
        base_modelo["segmento"].isin(["train", "valid"])
    ][["fecha", "retorno_afp"] + columnas_finales].dropna()
    test_final = base_modelo[
        base_modelo["segmento"].eq("test")
    ][["fecha", "retorno_afp"] + columnas_finales].dropna()

    rmse_valid_final, alpha_final = evaluar_ridge(
        train_valid_final[
            train_valid_final["fecha"].le(fin_train)
        ],
        train_valid_final[
            train_valid_final["fecha"].gt(fin_train)
        ],
        columnas_finales,
    )

    scaler = StandardScaler()
    x_train_valid = scaler.fit_transform(
        train_valid_final[columnas_finales]
    )
    x_test = scaler.transform(test_final[columnas_finales])
    y_train_valid = train_valid_final["retorno_afp"].to_numpy()
    y_test = test_final["retorno_afp"].to_numpy()

    modelo = Ridge(alpha=alpha_final)
    modelo.fit(x_train_valid, y_train_valid)
    pred_test = modelo.predict(x_test)

    rmse_test = float(
        mean_squared_error(y_test, pred_test) ** 0.5
    )
    rmse_cero = float(
        mean_squared_error(
            y_test,
            np.zeros_like(y_test),
        ) ** 0.5
    )
    r2 = float(r2_score(y_test, pred_test))
    direccion = float(
        (
            np.sign(y_test)
            == np.sign(pred_test)
        ).mean()
        * 100.0
    )

    filas_canasta = []

    for orden, feature in enumerate(seleccionadas, start=1):
        factor = mapeo[feature]
        fila_corr = candidatos_afp[
            candidatos_afp["factor"].eq(factor)
        ].iloc[0]

        filas_canasta.append(
            {
                "afp": afp,
                "orden": orden,
                "factor": factor,
                "descripcion": DESCRIPCIONES.get(
                    factor,
                    "Factor de mercado",
                ),
                "lag_dias": int(
                    fila_corr["mejor_lag_train"]
                ),
                "direccion_relacion": fila_corr[
                    "direccion_relacion"
                ],
                "corr_train": float(
                    fila_corr["corr_s_train"]
                ),
                "corr_valid": float(
                    fila_corr["corr_s_valid"]
                ),
                "corr_test": float(
                    fila_corr["corr_s_test"]
                ),
                "score_pretest": float(
                    fila_corr["score_pretest"]
                ),
                "confirmada_en_test": fila_corr[
                    "confirmada_en_test"
                ],
            }
        )

    metricas = pd.DataFrame(
        [
            {
                "afp": afp,
                "n_factores_canasta": len(seleccionadas),
                "factores_canasta": " | ".join(
                    mapeo[feature]
                    for feature in seleccionadas
                ),
                "alpha_final": alpha_final,
                "rmse_valid_final": rmse_valid_final,
                "n_test": len(test_final),
                "rmse_test": rmse_test,
                "rmse_baseline_cero": rmse_cero,
                "mejora_rmse_vs_cero_pct": (
                    (rmse_cero - rmse_test)
                    / rmse_cero
                    * 100.0
                ),
                "r2_test": r2,
                "direccion_correcta_test_pct": direccion,
            }
        ]
    )

    predicciones = pd.DataFrame(
        {
            "fecha": test_final["fecha"],
            "afp": afp,
            "retorno_real": y_test,
            "retorno_estimado": pred_test,
        }
    )

    return (
        pd.DataFrame(filas_canasta),
        auditoria_total,
        pd.concat(
            [
                metricas.assign(tipo_registro="metrica"),
                predicciones.assign(tipo_registro="prediccion"),
            ],
            ignore_index=True,
            sort=False,
        ),
    )


def construir_canasta_comun(canastas: pd.DataFrame) -> pd.DataFrame:
    if canastas.empty:
        return pd.DataFrame()

    resumen = (
        canastas.groupby(
            ["factor", "descripcion"],
            as_index=False,
        )
        .agg(
            afp_en_que_aparece=("afp", "nunique"),
            lista_afp=(
                "afp",
                lambda serie: " | ".join(
                    sorted(set(serie))
                ),
            ),
            correlacion_test_media=(
                "corr_test",
                "mean",
            ),
            score_pretest_medio=(
                "score_pretest",
                "mean",
            ),
            lag_mas_frecuente=(
                "lag_dias",
                lambda serie: int(
                    serie.mode().iloc[0]
                ),
            ),
        )
        .sort_values(
            [
                "afp_en_que_aparece",
                "score_pretest_medio",
            ],
            ascending=[False, False],
        )
        .reset_index(drop=True)
    )

    resumen["clasificacion"] = np.where(
        resumen["afp_en_que_aparece"] >= 3,
        "nucleo_comun",
        "especifico_de_algunas_afp",
    )

    resumen["prioridad"] = np.arange(
        1,
        len(resumen) + 1,
    )

    return resumen


def crear_reporte_markdown(
    canastas: pd.DataFrame,
    comun: pd.DataFrame,
    metricas: pd.DataFrame,
    auditoria: pd.DataFrame,
    ruta: Path,
) -> None:
    lineas = [
        "# Canasta depurada para seguimiento del Fondo 3",
        "",
        "## Criterio",
        "",
        (
            "Se eliminaron duplicados exactos y factores con "
            "información muy redundante. La canasta se seleccionó "
            "con entrenamiento y validación; la prueba final se usó "
            "solo para evaluar."
        ),
        "",
        "## Núcleo común",
        "",
    ]

    if comun.empty:
        lineas.append("No se identificó una canasta común.")
    else:
        nucleo = comun[
            comun["clasificacion"].eq("nucleo_comun")
        ]

        if nucleo.empty:
            lineas.append(
                "Ningún factor apareció en al menos tres AFP."
            )
        else:
            for _, fila in nucleo.iterrows():
                lineas.append(
                    f"- **{fila['factor']}** — "
                    f"{fila['descripcion']}; aparece en "
                    f"{int(fila['afp_en_que_aparece'])} AFP; "
                    f"rezago más frecuente: "
                    f"{int(fila['lag_mas_frecuente'])} días."
                )

    for afp in AFPS:
        lineas.extend(["", f"## {afp}", ""])
        bloque = canastas[canastas["afp"].eq(afp)]

        if bloque.empty:
            lineas.append(
                "No se obtuvo una canasta depurada."
            )
            continue

        for _, fila in bloque.sort_values("orden").iterrows():
            lineas.append(
                f"{int(fila['orden'])}. **{fila['factor']}** — "
                f"{fila['descripcion']}; relación "
                f"{fila['direccion_relacion']}; lag "
                f"{int(fila['lag_dias'])}; correlación de prueba "
                f"{fila['corr_test']:.3f}."
            )

        met = metricas[metricas["afp"].eq(afp)]

        if not met.empty:
            fila = met.iloc[0]
            lineas.extend(
                [
                    "",
                    (
                        f"Prueba final: R²={fila['r2_test']:.3f}; "
                        f"dirección correcta="
                        f"{fila['direccion_correcta_test_pct']:.1f} %; "
                        f"mejora RMSE frente a cero="
                        f"{fila['mejora_rmse_vs_cero_pct']:.1f} %."
                    ),
                ]
            )

    lineas.extend(
        [
            "",
            "## Advertencia interpretativa",
            "",
            (
                "Los ETF e índices seleccionados son termómetros "
                "públicos de la exposición económica observada. "
                "No prueban que la AFP mantenga exactamente esos "
                "instrumentos en cartera."
            ),
        ]
    )

    ruta.write_text(
        "\n".join(lineas),
        encoding="utf-8",
    )


def main() -> None:
    raiz = Path(__file__).resolve().parents[1]
    processed = raiz / "data" / "processed"

    objetivo = cargar_objetivo_sbs(processed)
    factores = cargar_factores_mercado(processed)
    candidatos = cargar_candidatos(processed)
    fin_train, fin_valid = cargar_division(processed)

    todas_canastas = []
    todas_auditorias = []
    todas_metricas = []
    todas_predicciones = []

    for afp in AFPS:
        canasta, auditoria, combinado = seleccionar_canasta_afp(
            afp,
            objetivo,
            factores,
            candidatos,
            fin_train,
            fin_valid,
        )

        if not canasta.empty:
            todas_canastas.append(canasta)

        if not auditoria.empty:
            todas_auditorias.append(auditoria)

        if not combinado.empty:
            met = combinado[
                combinado["tipo_registro"].eq("metrica")
            ].drop(columns=["tipo_registro"])
            pred = combinado[
                combinado["tipo_registro"].eq("prediccion")
            ].drop(columns=["tipo_registro"])

            todas_metricas.append(met)
            todas_predicciones.append(pred)

    canastas = (
        pd.concat(todas_canastas, ignore_index=True)
        if todas_canastas
        else pd.DataFrame()
    )
    auditoria = (
        pd.concat(todas_auditorias, ignore_index=True)
        if todas_auditorias
        else pd.DataFrame()
    )
    metricas = (
        pd.concat(todas_metricas, ignore_index=True)
        if todas_metricas
        else pd.DataFrame()
    )
    predicciones = (
        pd.concat(todas_predicciones, ignore_index=True)
        if todas_predicciones
        else pd.DataFrame()
    )
    comun = construir_canasta_comun(canastas)

    rutas = {
        "canasta": processed / "ca0001_modelo51_canasta_depurada.csv",
        "comun": processed / "ca0001_modelo51_canasta_comun.csv",
        "auditoria": processed / "ca0001_modelo51_auditoria_descartes.csv",
        "metricas": processed / "ca0001_modelo51_metricas_prueba.csv",
        "predicciones": processed / "ca0001_modelo51_predicciones_prueba.csv",
        "reporte": processed / "ca0001_modelo51_reporte.md",
        "json": processed / "ca0001_modelo51_resumen.json",
    }

    canastas.to_csv(
        rutas["canasta"],
        index=False,
        encoding="utf-8-sig",
    )
    comun.to_csv(
        rutas["comun"],
        index=False,
        encoding="utf-8-sig",
    )
    auditoria.to_csv(
        rutas["auditoria"],
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
    crear_reporte_markdown(
        canastas,
        comun,
        metricas,
        auditoria,
        rutas["reporte"],
    )

    resumen = {
        "version": "modelo51_canasta_depurada",
        "criterios": {
            "max_factores_por_afp": MAX_FACTORES,
            "umbral_duplicado_exacto": UMBRAL_DUPLICADO_EXACTO,
            "umbral_redundancia": UMBRAL_REDUNDANCIA,
            "mejora_minima_validacion_pct": MEJORA_MINIMA_VALID_PCT,
        },
        "canasta_por_afp": canastas.to_dict(orient="records"),
        "canasta_comun": comun.to_dict(orient="records"),
        "metricas": metricas.to_dict(orient="records"),
    }

    rutas["json"].write_text(
        json.dumps(
            resumen,
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )

    print("\nCANASTA DEPURADA DE SEGUIMIENTO TERMINADA")
    print("=" * 120)

    print("\nCANASTA POR AFP")
    print("-" * 120)
    if canastas.empty:
        print("No se obtuvo una canasta.")
    else:
        columnas = [
            "afp",
            "orden",
            "factor",
            "descripcion",
            "lag_dias",
            "direccion_relacion",
            "corr_train",
            "corr_valid",
            "corr_test",
        ]
        print(canastas[columnas].to_string(index=False))

    print("\nNÚCLEO COMÚN")
    print("-" * 120)
    if comun.empty:
        print("No se obtuvo canasta común.")
    else:
        columnas = [
            "prioridad",
            "factor",
            "descripcion",
            "afp_en_que_aparece",
            "lista_afp",
            "lag_mas_frecuente",
            "correlacion_test_media",
            "clasificacion",
        ]
        print(comun[columnas].to_string(index=False))

    print("\nDESEMPEÑO DE LA CANASTA DEPURADA")
    print("-" * 120)
    print(metricas.to_string(index=False))

    print("\nDESCARTES IMPORTANTES")
    print("-" * 120)
    if auditoria.empty:
        print("No hubo descartes.")
    else:
        mostrar = auditoria[
            [
                columna
                for columna in [
                    "afp",
                    "factor",
                    "estado",
                    "motivo",
                    "factor_equivalente_conservado",
                    "correlacion_max_con_canasta",
                    "mejora_valid_pct",
                ]
                if columna in auditoria.columns
            ]
        ]
        print(mostrar.to_string(index=False))

    print("\nArchivos creados:")
    for ruta in rutas.values():
        print(f" - {ruta.resolve()}")

    print(
        "\nLectura correcta:\n"
        "- 'seleccionado' significa que el factor aportó información "
        "adicional en validación.\n"
        "- 'duplicado_exacto' significa que representaba la misma serie.\n"
        "- 'redundante_con_canasta' significa que repetía casi el mismo "
        "movimiento de otro factor.\n"
        "- La lista final será la base para construir el índice de "
        "seguimiento y la gráfica cuota SBS versus cuota estimada."
    )


if __name__ == "__main__":
    main()
