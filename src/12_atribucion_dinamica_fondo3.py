from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.model_selection import GridSearchCV, TimeSeriesSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


VENTANA = 252
MIN_OBSERVACIONES = 200
TOP_N = 12
ALPHAS = [0.1, 1.0, 10.0, 100.0, 1000.0]


def crear_pipeline(alpha: float) -> Pipeline:
    return Pipeline(
        steps=[
            ("imputar", SimpleImputer(strategy="median")),
            ("escalar", StandardScaler()),
            ("ridge", Ridge(alpha=alpha)),
        ]
    )


def elegir_alpha(
    X: pd.DataFrame,
    y: pd.Series,
) -> float:
    pipeline = Pipeline(
        steps=[
            ("imputar", SimpleImputer(strategy="median")),
            ("escalar", StandardScaler()),
            ("ridge", Ridge()),
        ]
    )

    busqueda = GridSearchCV(
        estimator=pipeline,
        param_grid={"ridge__alpha": ALPHAS},
        scoring="neg_root_mean_squared_error",
        cv=TimeSeriesSplit(n_splits=5),
        n_jobs=-1,
        refit=True,
    )
    busqueda.fit(X, y)
    return float(busqueda.best_params_["ridge__alpha"])


def coeficientes_originales(
    pipeline: Pipeline,
    columnas: list[str],
) -> tuple[pd.DataFrame, float]:
    """
    Devuelve coeficientes en escala original y estandarizada.
    """
    imputer = pipeline.named_steps["imputar"]
    scaler = pipeline.named_steps["escalar"]
    ridge = pipeline.named_steps["ridge"]

    coef_std = np.asarray(ridge.coef_, dtype=float)
    coef_original = coef_std / scaler.scale_

    intercept_original = float(
        ridge.intercept_
        - np.sum(coef_std * scaler.mean_ / scaler.scale_)
    )

    tabla = pd.DataFrame(
        {
            "factor": columnas,
            "coef_estandarizado": coef_std,
            "coef_original": coef_original,
        }
    )
    tabla["coef_abs_estandarizado"] = tabla[
        "coef_estandarizado"
    ].abs()

    return tabla, intercept_original


def preparar_datos(
    ruta_afp: Path,
    ruta_factores: Path,
) -> tuple[pd.DataFrame, list[str]]:
    afp = pd.read_csv(ruta_afp, parse_dates=["fecha"])
    factores = pd.read_csv(ruta_factores, parse_dates=["fecha"])

    columnas_factores = [
        c for c in factores.columns if c.startswith("ret_")
    ]

    for columna in columnas_factores:
        factores[columna] = pd.to_numeric(
            factores[columna],
            errors="coerce",
        )

    afp["rendimiento_simple"] = pd.to_numeric(
        afp["rendimiento_simple"],
        errors="coerce",
    )

    base = afp.merge(
        factores[["fecha"] + columnas_factores],
        on="fecha",
        how="inner",
        validate="many_to_one",
    )

    base = base.sort_values(["afp", "fecha"]).reset_index(drop=True)
    return base, columnas_factores


def fin_de_mes_indices(grupo: pd.DataFrame) -> list[int]:
    """
    Devuelve posiciones de la última observación disponible de cada mes.
    """
    temporal = grupo[["fecha"]].copy()
    temporal["periodo"] = temporal["fecha"].dt.to_period("M")

    indices = (
        temporal.groupby("periodo", sort=True)
        .tail(1)
        .index
        .tolist()
    )
    return indices


def calcular_atribucion_rolling(
    grupo: pd.DataFrame,
    columnas_factores: list[str],
    alpha: float,
    nombre_afp: str,
) -> pd.DataFrame:
    grupo = grupo.sort_values("fecha").reset_index(drop=True)
    indices_cierre = fin_de_mes_indices(grupo)
    filas = []

    for indice_fin in indices_cierre:
        inicio = max(0, indice_fin - VENTANA + 1)
        ventana = grupo.iloc[inicio : indice_fin + 1].copy()
        ventana = ventana.dropna(subset=["rendimiento_simple"])

        if len(ventana) < MIN_OBSERVACIONES:
            continue

        X = ventana[columnas_factores]
        y = ventana["rendimiento_simple"]

        modelo = crear_pipeline(alpha)
        modelo.fit(X, y)

        coeficientes, intercepto = coeficientes_originales(
            modelo,
            columnas_factores,
        )

        pred = modelo.predict(X)
        residuo = y.to_numpy() - pred
        r2 = modelo.score(X, y)
        rmse = float(np.sqrt(np.mean(residuo**2)))

        coeficientes = coeficientes.sort_values(
            "coef_abs_estandarizado",
            ascending=False,
        ).reset_index(drop=True)
        coeficientes["ranking_ventana"] = (
            np.arange(1, len(coeficientes) + 1)
        )

        for registro in coeficientes.itertuples(index=False):
            filas.append(
                {
                    "afp": nombre_afp,
                    "fecha_fin_ventana": ventana["fecha"].max(),
                    "fecha_inicio_ventana": ventana["fecha"].min(),
                    "observaciones": len(ventana),
                    "alpha_ridge": alpha,
                    "r2_in_sample": r2,
                    "rmse_in_sample": rmse,
                    "intercepto_original": intercepto,
                    "factor": registro.factor,
                    "coef_estandarizado": registro.coef_estandarizado,
                    "coef_original": registro.coef_original,
                    "coef_abs_estandarizado": (
                        registro.coef_abs_estandarizado
                    ),
                    "ranking_ventana": registro.ranking_ventana,
                    "top5_ventana": registro.ranking_ventana <= 5,
                }
            )

    return pd.DataFrame(filas)


def resumir_estabilidad(
    rolling: pd.DataFrame,
) -> pd.DataFrame:
    resumen = (
        rolling.groupby(["afp", "factor"])
        .agg(
            ventanas=("fecha_fin_ventana", "nunique"),
            coef_mediana=("coef_estandarizado", "median"),
            coef_promedio=("coef_estandarizado", "mean"),
            coef_abs_mediana=(
                "coef_abs_estandarizado",
                "median",
            ),
            top5_frecuencia_pct=(
                "top5_ventana",
                lambda s: float(pd.Series(s).mean() * 100),
            ),
            signo_positivo_pct=(
                "coef_estandarizado",
                lambda s: float((pd.Series(s) > 0).mean() * 100),
            ),
            ultimo_coef=(
                "coef_estandarizado",
                "last",
            ),
            ultimo_ranking=(
                "ranking_ventana",
                "last",
            ),
        )
        .reset_index()
    )

    resumen["consistencia_signo_pct"] = (
        resumen["signo_positivo_pct"]
        .sub(50)
        .abs()
        .mul(2)
    )

    resumen["puntaje_estabilidad"] = (
        0.60 * resumen["top5_frecuencia_pct"]
        + 0.40 * resumen["consistencia_signo_pct"]
    )

    resumen = resumen.sort_values(
        ["afp", "puntaje_estabilidad", "coef_abs_mediana"],
        ascending=[True, False, False],
    )
    resumen["ranking_estabilidad"] = (
        resumen.groupby("afp")
        .cumcount()
        .add(1)
    )

    return resumen


def atribucion_ultima_fecha(
    grupo: pd.DataFrame,
    columnas_factores: list[str],
    alpha: float,
    nombre_afp: str,
) -> pd.DataFrame:
    grupo = grupo.sort_values("fecha").reset_index(drop=True)
    grupo = grupo.dropna(subset=["rendimiento_simple"])

    ventana = grupo.tail(VENTANA).copy()

    if len(ventana) < MIN_OBSERVACIONES:
        return pd.DataFrame()

    X = ventana[columnas_factores]
    y = ventana["rendimiento_simple"]

    modelo = crear_pipeline(alpha)
    modelo.fit(X, y)

    coeficientes, intercepto = coeficientes_originales(
        modelo,
        columnas_factores,
    )

    ultima = ventana.iloc[-1]
    X_ultima = ventana[columnas_factores].iloc[[-1]]

    prediccion = float(modelo.predict(X_ultima)[0])
    real = float(ultima["rendimiento_simple"])
    residual = real - prediccion

    valores = X_ultima.iloc[0]

    coeficientes["retorno_factor"] = coeficientes[
        "factor"
    ].map(valores.to_dict())

    coeficientes["contribucion_retorno"] = (
        coeficientes["coef_original"]
        * coeficientes["retorno_factor"]
    )
    coeficientes["contribucion_puntos_pct"] = (
        coeficientes["contribucion_retorno"] * 100
    )

    coeficientes["afp"] = nombre_afp
    coeficientes["fecha"] = ultima["fecha"]
    coeficientes["retorno_real_pct"] = real * 100
    coeficientes["retorno_estimado_pct"] = prediccion * 100
    coeficientes["residual_pct"] = residual * 100
    coeficientes["intercepto_pct"] = intercepto * 100

    coeficientes = coeficientes.sort_values(
        "contribucion_retorno",
        key=lambda s: s.abs(),
        ascending=False,
    ).reset_index(drop=True)
    coeficientes["ranking_contribucion"] = (
        np.arange(1, len(coeficientes) + 1)
    )

    return coeficientes


def agregar_catalogo(
    tabla: pd.DataFrame,
    ruta_catalogo: Path,
) -> pd.DataFrame:
    if not ruta_catalogo.exists() or tabla.empty:
        return tabla

    catalogo = pd.read_csv(ruta_catalogo)

    columnas = [
        c
        for c in [
            "columna_modelo",
            "ticker",
            "nombre",
            "grupo",
            "moneda",
        ]
        if c in catalogo.columns
    ]

    catalogo = catalogo[columnas].drop_duplicates(
        subset=["columna_modelo"]
    )

    return tabla.merge(
        catalogo,
        left_on="factor",
        right_on="columna_modelo",
        how="left",
    )


def main() -> None:
    raiz = Path(__file__).resolve().parents[1]
    processed = raiz / "data" / "processed"

    ruta_afp = processed / "sbs_fondo3_base_maestra.csv"
    ruta_factores = processed / "mercados_factores_modelo.csv"
    ruta_catalogo = processed / "mercados_catalogo_factores.csv"

    base, columnas_factores = preparar_datos(
        ruta_afp,
        ruta_factores,
    )

    rolling_total = []
    ultima_total = []
    parametros = []

    for nombre_afp, grupo in base.groupby("afp"):
        grupo = grupo.sort_values("fecha").copy()

        entrenamiento_alpha = grupo[
            grupo["fecha"] < pd.Timestamp("2025-01-01")
        ].dropna(subset=["rendimiento_simple"])

        alpha = elegir_alpha(
            entrenamiento_alpha[columnas_factores],
            entrenamiento_alpha["rendimiento_simple"],
        )

        parametros.append(
            {
                "afp": nombre_afp,
                "alpha_ridge_atribucion": alpha,
                "ventana_sesiones": VENTANA,
            }
        )

        print(
            f"\n{nombre_afp}: alpha={alpha} | "
            "calculando atribución mensual dinámica..."
        )

        rolling = calcular_atribucion_rolling(
            grupo,
            columnas_factores,
            alpha,
            nombre_afp,
        )
        rolling_total.append(rolling)

        ultima = atribucion_ultima_fecha(
            grupo,
            columnas_factores,
            alpha,
            nombre_afp,
        )
        ultima_total.append(ultima)

    rolling_df = pd.concat(
        rolling_total,
        ignore_index=True,
    )
    ultima_df = pd.concat(
        ultima_total,
        ignore_index=True,
    )

    estabilidad = resumir_estabilidad(rolling_df)

    rolling_df = agregar_catalogo(
        rolling_df,
        ruta_catalogo,
    )
    estabilidad = agregar_catalogo(
        estabilidad,
        ruta_catalogo,
    )
    ultima_df = agregar_catalogo(
        ultima_df,
        ruta_catalogo,
    )

    parametros_df = pd.DataFrame(parametros)

    ruta_rolling = (
        processed / "fondo3_atribucion_dinamica_mensual.csv"
    )
    ruta_estabilidad = (
        processed / "fondo3_estabilidad_factores.csv"
    )
    ruta_ultima = (
        processed / "fondo3_atribucion_ultima_fecha.csv"
    )
    ruta_parametros = (
        processed / "fondo3_atribucion_parametros.csv"
    )

    rolling_df.to_csv(
        ruta_rolling,
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    estabilidad.to_csv(
        ruta_estabilidad,
        index=False,
        encoding="utf-8-sig",
    )
    ultima_df.to_csv(
        ruta_ultima,
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    parametros_df.to_csv(
        ruta_parametros,
        index=False,
        encoding="utf-8-sig",
    )

    print("\n" + "=" * 100)
    print("FACTORES MÁS ESTABLES POR AFP")
    print("=" * 100)

    for nombre_afp in sorted(estabilidad["afp"].unique()):
        tabla = estabilidad[
            (estabilidad["afp"] == nombre_afp)
            & (estabilidad["ranking_estabilidad"] <= TOP_N)
        ].copy()

        columnas = [
            "ranking_estabilidad",
            "factor",
            "nombre",
            "grupo",
            "coef_mediana",
            "top5_frecuencia_pct",
            "consistencia_signo_pct",
            "ultimo_coef",
        ]
        columnas = [c for c in columnas if c in tabla.columns]

        print(f"\n{nombre_afp}")
        print("-" * 100)
        print(tabla[columnas].to_string(index=False))

    print("\n" + "=" * 100)
    print("ATRIBUCIÓN DE LA ÚLTIMA FECHA OFICIAL")
    print("=" * 100)

    for nombre_afp in sorted(ultima_df["afp"].unique()):
        tabla = ultima_df[
            ultima_df["afp"] == nombre_afp
        ].head(10)

        print(f"\n{nombre_afp}")
        print("-" * 100)
        print(
            tabla[
                [
                    "fecha",
                    "factor",
                    "nombre",
                    "contribucion_puntos_pct",
                    "retorno_real_pct",
                    "retorno_estimado_pct",
                    "residual_pct",
                ]
            ].to_string(index=False)
        )

    print("\nArchivos creados:")
    for ruta in [
        ruta_rolling,
        ruta_estabilidad,
        ruta_ultima,
        ruta_parametros,
    ]:
        print(f" - {ruta.resolve()}")

    print(
        "\nInterpretación importante:\n"
        "- Este módulo estima qué factores explican conjuntamente la "
        "variación del Fondo 3 y cómo cambia esa relación en el tiempo.\n"
        "- Los coeficientes Ridge no son porcentajes exactos de cartera.\n"
        "- Un factor estable y con signo consistente es un buen candidato "
        "para el siguiente nivel de análisis por sectores, ETF y acciones.\n"
        "- La atribución diaria separa la parte explicada por los factores "
        "y el residual no explicado."
    )


if __name__ == "__main__":
    main()
