from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LinearRegression, Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import GridSearchCV, TimeSeriesSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


FECHA_CORTE_TEST = pd.Timestamp("2025-01-01")
ALPHAS = [0.01, 0.1, 1.0, 10.0, 100.0, 1000.0]
N_SPLITS = 5

ESQUEMAS_REZAGO = {
    "lag0": [0],
    "lag1": [1],
    "lag2": [2],
    "lag0_1": [0, 1],
    "lag0_1_2": [0, 1, 2],
}

TICKERS = [
    "ACWI",
    "XLK",
    "EEM",
    "EPU",
    "COPX",
    "TLT",
    "HYG",
    "LQD",
    "^VIX",
    "PEN=X",
]


def leer_mercados(ruta: Path) -> pd.DataFrame:
    if not ruta.exists():
        raise FileNotFoundError(f"No existe: {ruta}")

    df = pd.read_csv(ruta, parse_dates=["fecha"])
    df = df.sort_values("fecha").drop_duplicates("fecha").copy()

    faltantes = [c for c in TICKERS if c not in df.columns]
    if faltantes:
        raise ValueError(
            f"Faltan columnas de mercado: {faltantes}"
        )

    for columna in TICKERS:
        df[columna] = pd.to_numeric(
            df[columna],
            errors="coerce",
        )

    return df


def leer_afp(ruta: Path) -> pd.DataFrame:
    if not ruta.exists():
        raise FileNotFoundError(f"No existe: {ruta}")

    df = pd.read_csv(ruta, parse_dates=["fecha"])
    df["rendimiento_simple"] = pd.to_numeric(
        df["rendimiento_simple"],
        errors="coerce",
    )
    return df.sort_values(["afp", "fecha"]).copy()


def ajustar_residualizador(
    datos: pd.DataFrame,
    objetivo: str,
    predictores: list[str],
) -> Pipeline:
    mascara = datos[objetivo].notna()

    modelo = Pipeline(
        steps=[
            ("imputar", SimpleImputer(strategy="median")),
            ("regresion", LinearRegression()),
        ]
    )

    modelo.fit(
        datos.loc[mascara, predictores],
        datos.loc[mascara, objetivo],
    )
    return modelo


def ajustar_ortogonalizadores(
    entrenamiento: pd.DataFrame,
) -> dict[str, tuple[Pipeline, str, list[str]]]:
    especificaciones = {
        "tecnologia_extra": ("XLK", ["ACWI"]),
        "emergentes_extra": ("EEM", ["ACWI"]),
        "peru_extra": ("EPU", ["ACWI", "EEM"]),
        "cobre_extra": ("COPX", ["ACWI", "EEM", "EPU"]),
    }

    modelos = {}

    for nombre, (objetivo, predictores) in especificaciones.items():
        modelos[nombre] = (
            ajustar_residualizador(
                entrenamiento,
                objetivo,
                predictores,
            ),
            objetivo,
            predictores,
        )

    return modelos


def transformar_residual(
    datos: pd.DataFrame,
    modelo: Pipeline,
    objetivo: str,
    predictores: list[str],
) -> pd.Series:
    pred = modelo.predict(datos[predictores])
    residual = datos[objetivo] - pred
    residual[datos[objetivo].isna()] = np.nan
    return residual


def construir_bloques(
    datos: pd.DataFrame,
    ortogonalizadores: dict[str, tuple[Pipeline, str, list[str]]],
) -> pd.DataFrame:
    salida = pd.DataFrame({"fecha": datos["fecha"]})

    salida["mercado_global"] = datos["ACWI"]

    for nombre, (
        modelo,
        objetivo,
        predictores,
    ) in ortogonalizadores.items():
        salida[nombre] = transformar_residual(
            datos,
            modelo,
            objetivo,
            predictores,
        )

    salida["bonos_tesoro"] = datos["TLT"]
    salida["spread_credito"] = datos["HYG"] - datos["LQD"]
    salida["vix"] = datos["^VIX"]
    salida["fx_usdpen"] = datos["PEN=X"]

    return salida


def agregar_rezagos(
    bloques: pd.DataFrame,
    rezagos: list[int],
) -> pd.DataFrame:
    base = bloques.sort_values("fecha").reset_index(drop=True)
    salida = pd.DataFrame({"fecha": base["fecha"]})

    columnas = [c for c in base.columns if c != "fecha"]

    for columna in columnas:
        for rezago in rezagos:
            salida[f"{columna}_lag{rezago}"] = (
                base[columna].shift(rezago)
            )

    return salida


def crear_ridge(alpha: float | None = None) -> Pipeline:
    modelo = Pipeline(
        steps=[
            ("imputar", SimpleImputer(strategy="median")),
            ("escalar", StandardScaler()),
            ("ridge", Ridge()),
        ]
    )

    if alpha is not None:
        modelo.set_params(ridge__alpha=alpha)

    return modelo


def elegir_alpha(
    X: pd.DataFrame,
    y: pd.Series,
) -> float:
    busqueda = GridSearchCV(
        estimator=crear_ridge(),
        param_grid={"ridge__alpha": ALPHAS},
        scoring="neg_root_mean_squared_error",
        cv=TimeSeriesSplit(n_splits=N_SPLITS),
        n_jobs=-1,
        refit=True,
    )
    busqueda.fit(X, y)
    return float(busqueda.best_params_["ridge__alpha"])


def metricas(
    real: pd.Series,
    estimado: np.ndarray,
) -> dict:
    y = np.asarray(real, dtype=float)
    p = np.asarray(estimado, dtype=float)

    rmse = float(np.sqrt(mean_squared_error(y, p)))
    mae = float(mean_absolute_error(y, p))
    r2 = float(r2_score(y, p))

    correlacion = (
        float(np.corrcoef(y, p)[0, 1])
        if np.std(y) > 0 and np.std(p) > 0
        else np.nan
    )

    direccion = float(
        (np.sign(y) == np.sign(p)).mean() * 100
    )

    return {
        "observaciones": len(y),
        "rmse": rmse,
        "mae": mae,
        "r2": r2,
        "correlacion": correlacion,
        "acierto_direccion_pct": direccion,
    }


def evaluar_esquema(
    nombre_afp: str,
    esquema: str,
    afp_grupo: pd.DataFrame,
    factores: pd.DataFrame,
) -> tuple[dict, float]:
    combinado = afp_grupo[
        ["fecha", "rendimiento_simple"]
    ].merge(
        factores,
        on="fecha",
        how="inner",
        validate="one_to_one",
    ).dropna(subset=["rendimiento_simple"])

    columnas = [
        c for c in combinado.columns
        if c not in ["fecha", "rendimiento_simple"]
    ]

    train = combinado[
        combinado["fecha"] < FECHA_CORTE_TEST
    ].copy()
    test = combinado[
        combinado["fecha"] >= FECHA_CORTE_TEST
    ].copy()

    X_train = train[columnas]
    y_train = train["rendimiento_simple"]
    X_test = test[columnas]
    y_test = test["rendimiento_simple"]

    alpha = elegir_alpha(X_train, y_train)
    modelo = crear_ridge(alpha)
    modelo.fit(X_train, y_train)

    pred = modelo.predict(X_test)
    met = metricas(y_test, pred)

    resultado = {
        "afp": nombre_afp,
        "esquema_rezago": esquema,
        "rezagos": ",".join(
            str(x) for x in ESQUEMAS_REZAGO[esquema]
        ),
        "numero_variables": len(columnas),
        "alpha_ridge": alpha,
        "fecha_prueba_inicio": test["fecha"].min(),
        "fecha_prueba_fin": test["fecha"].max(),
        **met,
    }

    return resultado, alpha


def coeficientes_originales(
    modelo: Pipeline,
    columnas: list[str],
) -> tuple[pd.DataFrame, float]:
    scaler = modelo.named_steps["escalar"]
    ridge = modelo.named_steps["ridge"]

    coef_std = np.asarray(ridge.coef_, dtype=float)
    coef_original = coef_std / scaler.scale_

    intercepto = float(
        ridge.intercept_
        - np.sum(coef_std * scaler.mean_ / scaler.scale_)
    )

    tabla = pd.DataFrame(
        {
            "variable": columnas,
            "coef_estandarizado": coef_std,
            "coef_original": coef_original,
        }
    )

    return tabla, intercepto


def nombre_factor_base(variable: str) -> str:
    if "_lag" in variable:
        return variable.rsplit("_lag", 1)[0]
    return variable


def atribuir_ultima_fecha(
    nombre_afp: str,
    afp_grupo: pd.DataFrame,
    factores: pd.DataFrame,
    esquema: str,
    alpha: float,
) -> tuple[pd.DataFrame, dict]:
    combinado = afp_grupo[
        ["fecha", "rendimiento_simple"]
    ].merge(
        factores,
        on="fecha",
        how="inner",
        validate="one_to_one",
    ).dropna(subset=["rendimiento_simple"])

    columnas = [
        c for c in combinado.columns
        if c not in ["fecha", "rendimiento_simple"]
    ]

    modelo = crear_ridge(alpha)
    modelo.fit(
        combinado[columnas],
        combinado["rendimiento_simple"],
    )

    ultima = combinado.iloc[-1]
    X_ultima = combinado[columnas].iloc[[-1]]

    estimado = float(modelo.predict(X_ultima)[0])
    real = float(ultima["rendimiento_simple"])
    residual = real - estimado

    coef, intercepto = coeficientes_originales(
        modelo,
        columnas,
    )

    valores = X_ultima.iloc[0].to_dict()
    coef["valor_variable"] = coef["variable"].map(valores)
    coef["contribucion_retorno"] = (
        coef["coef_original"] * coef["valor_variable"]
    )
    coef["factor_base"] = coef["variable"].map(
        nombre_factor_base
    )

    agregado = (
        coef.groupby("factor_base", as_index=False)
        .agg(
            contribucion_retorno=(
                "contribucion_retorno",
                "sum",
            ),
            numero_rezagos=("variable", "count"),
        )
    )

    agregado["contribucion_puntos_pct"] = (
        agregado["contribucion_retorno"] * 100
    )
    agregado["afp"] = nombre_afp
    agregado["esquema_rezago"] = esquema
    agregado["fecha"] = ultima["fecha"]
    agregado["retorno_real_pct"] = real * 100
    agregado["retorno_estimado_pct"] = estimado * 100
    agregado["intercepto_pct"] = intercepto * 100
    agregado["residual_pct"] = residual * 100

    agregado = agregado.sort_values(
        "contribucion_retorno",
        key=lambda s: s.abs(),
        ascending=False,
    ).reset_index(drop=True)
    agregado["ranking_contribucion"] = (
        np.arange(1, len(agregado) + 1)
    )

    filas_extra = pd.DataFrame(
        [
            {
                "factor_base": "intercepto",
                "contribucion_retorno": intercepto,
                "numero_rezagos": 0,
                "contribucion_puntos_pct": intercepto * 100,
                "afp": nombre_afp,
                "esquema_rezago": esquema,
                "fecha": ultima["fecha"],
                "retorno_real_pct": real * 100,
                "retorno_estimado_pct": estimado * 100,
                "intercepto_pct": intercepto * 100,
                "residual_pct": residual * 100,
                "ranking_contribucion": len(agregado) + 1,
            },
            {
                "factor_base": "residual_no_explicado",
                "contribucion_retorno": residual,
                "numero_rezagos": 0,
                "contribucion_puntos_pct": residual * 100,
                "afp": nombre_afp,
                "esquema_rezago": esquema,
                "fecha": ultima["fecha"],
                "retorno_real_pct": real * 100,
                "retorno_estimado_pct": estimado * 100,
                "intercepto_pct": intercepto * 100,
                "residual_pct": residual * 100,
                "ranking_contribucion": len(agregado) + 2,
            },
        ]
    )

    detalle = pd.concat(
        [agregado, filas_extra],
        ignore_index=True,
        sort=False,
    )

    resumen = {
        "afp": nombre_afp,
        "esquema_rezago": esquema,
        "fecha": ultima["fecha"],
        "retorno_real_pct": real * 100,
        "retorno_estimado_pct": estimado * 100,
        "intercepto_pct": intercepto * 100,
        "residual_pct": residual * 100,
        "parte_explicada_pct_sobre_movimiento": (
            estimado / real * 100 if real != 0 else np.nan
        ),
        "alpha_ridge": alpha,
    }

    return detalle, resumen


def main() -> None:
    raiz = Path(__file__).resolve().parents[1]
    processed = raiz / "data" / "processed"

    ruta_afp = processed / "sbs_fondo3_base_maestra.csv"
    ruta_mercados = processed / "mercados_retornos_locales.csv"

    afp = leer_afp(ruta_afp)
    mercados = leer_mercados(ruta_mercados)

    mercados_train = mercados[
        mercados["fecha"] < FECHA_CORTE_TEST
    ].copy()

    # Evaluación sin fuga: los bloques del test se calculan con
    # relaciones estimadas únicamente en el periodo de entrenamiento.
    ortogonalizadores_train = ajustar_ortogonalizadores(
        mercados_train
    )
    bloques_evaluacion = construir_bloques(
        mercados,
        ortogonalizadores_train,
    )

    diseños_evaluacion = {
        nombre: agregar_rezagos(
            bloques_evaluacion,
            rezagos,
        )
        for nombre, rezagos in ESQUEMAS_REZAGO.items()
    }

    resultados = []
    mejores = []

    for nombre_afp, grupo in afp.groupby("afp"):
        print("\n" + "=" * 100)
        print(f"AFP: {nombre_afp}")
        print("-" * 100)

        resultados_afp = []

        for esquema, diseño in diseños_evaluacion.items():
            resultado, alpha = evaluar_esquema(
                nombre_afp,
                esquema,
                grupo,
                diseño,
            )
            resultados.append(resultado)
            resultados_afp.append(resultado)

            print(
                f"{esquema}: "
                f"RMSE={resultado['rmse']:.6f} | "
                f"R²={resultado['r2']:.4f} | "
                f"Corr={resultado['correlacion']:.4f} | "
                f"Dirección={resultado['acierto_direccion_pct']:.2f}%"
            )

        tabla_afp = pd.DataFrame(resultados_afp)
        mejor = tabla_afp.sort_values(
            ["rmse", "mae"],
            ascending=True,
        ).iloc[0]

        mejores.append(
            {
                "afp": nombre_afp,
                "mejor_esquema": mejor["esquema_rezago"],
                "alpha_ridge": mejor["alpha_ridge"],
                "rmse": mejor["rmse"],
                "mae": mejor["mae"],
                "r2": mejor["r2"],
                "correlacion": mejor["correlacion"],
                "acierto_direccion_pct": mejor[
                    "acierto_direccion_pct"
                ],
            }
        )

    resultados_df = pd.DataFrame(resultados)
    resultados_df["ranking_rmse"] = (
        resultados_df.groupby("afp")["rmse"]
        .rank(method="first", ascending=True)
        .astype(int)
    )

    mejores_df = pd.DataFrame(mejores)

    # Atribución final: se reajustan los bloques con toda la historia.
    ortogonalizadores_full = ajustar_ortogonalizadores(
        mercados
    )
    bloques_full = construir_bloques(
        mercados,
        ortogonalizadores_full,
    )

    detalles = []
    resumenes = []

    for fila in mejores_df.itertuples(index=False):
        nombre_afp = fila.afp
        esquema = fila.mejor_esquema
        alpha = fila.alpha_ridge

        diseño_full = agregar_rezagos(
            bloques_full,
            ESQUEMAS_REZAGO[esquema],
        )

        grupo = afp[afp["afp"] == nombre_afp].copy()

        detalle, resumen = atribuir_ultima_fecha(
            nombre_afp,
            grupo,
            diseño_full,
            esquema,
            alpha,
        )

        detalles.append(detalle)
        resumenes.append(resumen)

    detalle_df = pd.concat(
        detalles,
        ignore_index=True,
    )
    resumen_df = pd.DataFrame(resumenes)

    ruta_resultados = (
        processed / "fondo3_comparacion_rezagos.csv"
    )
    ruta_mejores = (
        processed / "fondo3_mejor_rezago_por_afp.csv"
    )
    ruta_detalle = (
        processed / "fondo3_atribucion_con_rezagos.csv"
    )
    ruta_resumen = (
        processed / "fondo3_atribucion_con_rezagos_resumen.csv"
    )

    resultados_df.to_csv(
        ruta_resultados,
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    mejores_df.to_csv(
        ruta_mejores,
        index=False,
        encoding="utf-8-sig",
    )
    detalle_df.to_csv(
        ruta_detalle,
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    resumen_df.to_csv(
        ruta_resumen,
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )

    print("\n" + "=" * 100)
    print("MEJOR ESQUEMA DE DESFASE POR AFP")
    print("=" * 100)
    print(mejores_df.to_string(index=False))

    print("\n" + "=" * 100)
    print("ATRIBUCIÓN DE LA ÚLTIMA FECHA CON DESFASE OPTIMIZADO")
    print("=" * 100)

    for nombre_afp in sorted(detalle_df["afp"].unique()):
        tabla = detalle_df[
            detalle_df["afp"] == nombre_afp
        ].copy()

        print(f"\n{nombre_afp}")
        print("-" * 100)
        print(
            tabla[
                [
                    "factor_base",
                    "contribucion_puntos_pct",
                    "esquema_rezago",
                    "retorno_real_pct",
                    "retorno_estimado_pct",
                    "residual_pct",
                ]
            ].to_string(index=False)
        )

    print("\nArchivos creados:")
    for ruta in [
        ruta_resultados,
        ruta_mejores,
        ruta_detalle,
        ruta_resumen,
    ]:
        print(f" - {ruta.resolve()}")

    print(
        "\nInterpretación:\n"
        "- lag0 usa el mercado de la misma fecha.\n"
        "- lag1 y lag2 prueban si la AFP incorpora precios con uno o dos "
        "cierres de retraso.\n"
        "- lag0_1 y lag0_1_2 permiten que la valorización distribuya el "
        "efecto entre varios cierres.\n"
        "- El esquema ganador se elige exclusivamente por desempeño "
        "fuera de muestra desde 2025.\n"
        "- La atribución incluye explícitamente intercepto y residual, "
        "por lo que la suma queda reconciliada con el retorno real."
    )


if __name__ == "__main__":
    main()
