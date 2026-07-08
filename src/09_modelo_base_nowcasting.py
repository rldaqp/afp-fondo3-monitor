from __future__ import annotations

from pathlib import Path
import warnings

import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.impute import SimpleImputer
from sklearn.linear_model import ElasticNet, HuberRegressor, LinearRegression, Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import GridSearchCV, TimeSeriesSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


FECHA_CORTE_TEST = pd.Timestamp("2025-01-01")
N_SPLITS = 5
RANDOM_STATE = 42


def metricas(y_real: pd.Series, y_pred: np.ndarray) -> dict:
    y_real_np = np.asarray(y_real, dtype=float)
    y_pred_np = np.asarray(y_pred, dtype=float)

    mascara = np.isfinite(y_real_np) & np.isfinite(y_pred_np)
    y_real_np = y_real_np[mascara]
    y_pred_np = y_pred_np[mascara]

    if len(y_real_np) == 0:
        return {
            "observaciones": 0,
            "mae": np.nan,
            "rmse": np.nan,
            "r2": np.nan,
            "correlacion": np.nan,
            "acierto_direccion_pct": np.nan,
        }

    mae = mean_absolute_error(y_real_np, y_pred_np)
    rmse = np.sqrt(mean_squared_error(y_real_np, y_pred_np))
    r2 = r2_score(y_real_np, y_pred_np)

    if np.std(y_real_np) > 0 and np.std(y_pred_np) > 0:
        correlacion = float(np.corrcoef(y_real_np, y_pred_np)[0, 1])
    else:
        correlacion = np.nan

    acierto = float(
        (np.sign(y_real_np) == np.sign(y_pred_np)).mean() * 100
    )

    return {
        "observaciones": len(y_real_np),
        "mae": mae,
        "rmse": rmse,
        "r2": r2,
        "correlacion": correlacion,
        "acierto_direccion_pct": acierto,
    }


def leer_datos(
    ruta_afp: Path,
    ruta_factores: Path,
) -> tuple[pd.DataFrame, list[str]]:
    afp = pd.read_csv(ruta_afp, parse_dates=["fecha"])
    factores = pd.read_csv(ruta_factores, parse_dates=["fecha"])

    columnas_factores = [
        c for c in factores.columns if c.startswith("ret_")
    ]

    if "ret_ACWI" not in columnas_factores:
        raise ValueError(
            "No se encontró ret_ACWI en la base de factores."
        )

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


def crear_modelos(tscv: TimeSeriesSplit) -> dict:
    modelos = {}

    modelos["ACWI_lineal"] = Pipeline(
        steps=[
            ("imputar", SimpleImputer(strategy="median")),
            ("modelo", LinearRegression()),
        ]
    )

    ridge_pipe = Pipeline(
        steps=[
            ("imputar", SimpleImputer(strategy="median")),
            ("escalar", StandardScaler()),
            ("ridge", Ridge()),
        ]
    )
    modelos["Ridge"] = GridSearchCV(
        estimator=ridge_pipe,
        param_grid={
            "ridge__alpha": [
                0.01,
                0.1,
                1.0,
                10.0,
                100.0,
                1000.0,
            ]
        },
        scoring="neg_root_mean_squared_error",
        cv=tscv,
        n_jobs=-1,
        refit=True,
    )

    elastic_pipe = Pipeline(
        steps=[
            ("imputar", SimpleImputer(strategy="median")),
            ("escalar", StandardScaler()),
            (
                "elasticnet",
                ElasticNet(
                    max_iter=100_000,
                    random_state=RANDOM_STATE,
                ),
            ),
        ]
    )
    modelos["ElasticNet"] = GridSearchCV(
        estimator=elastic_pipe,
        param_grid={
            "elasticnet__alpha": [
                0.00001,
                0.00003,
                0.0001,
                0.0003,
                0.001,
                0.003,
                0.01,
            ],
            "elasticnet__l1_ratio": [
                0.05,
                0.25,
                0.50,
                0.75,
                0.95,
            ],
        },
        scoring="neg_root_mean_squared_error",
        cv=tscv,
        n_jobs=-1,
        refit=True,
    )

    modelos["Huber_robusto"] = Pipeline(
        steps=[
            ("imputar", SimpleImputer(strategy="median")),
            ("escalar", StandardScaler()),
            (
                "huber",
                HuberRegressor(
                    epsilon=1.35,
                    alpha=0.0001,
                    max_iter=5_000,
                ),
            ),
        ]
    )

    return modelos


def extraer_coeficientes(
    modelo_nombre: str,
    modelo_ajustado,
    columnas: list[str],
    afp: str,
) -> pd.DataFrame:
    estimador = modelo_ajustado

    if hasattr(modelo_ajustado, "best_estimator_"):
        estimador = modelo_ajustado.best_estimator_

    ultimo_paso = estimador.steps[-1][1] if hasattr(
        estimador, "steps"
    ) else estimador

    if not hasattr(ultimo_paso, "coef_"):
        return pd.DataFrame()

    coeficientes = np.ravel(ultimo_paso.coef_)

    if len(coeficientes) != len(columnas):
        return pd.DataFrame()

    tabla = pd.DataFrame(
        {
            "afp": afp,
            "modelo": modelo_nombre,
            "factor": columnas,
            "coeficiente_estandarizado": coeficientes,
        }
    )
    tabla["coeficiente_abs"] = tabla[
        "coeficiente_estandarizado"
    ].abs()
    tabla = tabla.sort_values(
        "coeficiente_abs",
        ascending=False,
    )
    tabla["ranking"] = np.arange(1, len(tabla) + 1)
    return tabla


def main() -> None:
    warnings.filterwarnings(
        "ignore",
        message="Objective did not converge",
    )

    raiz = Path(__file__).resolve().parents[1]
    processed = raiz / "data" / "processed"
    modelos_dir = raiz / "models"
    modelos_dir.mkdir(parents=True, exist_ok=True)

    ruta_afp = processed / "sbs_fondo3_base_maestra.csv"
    ruta_factores = processed / "mercados_factores_modelo.csv"

    print("Leyendo datos...")
    base, columnas_factores = leer_datos(
        ruta_afp,
        ruta_factores,
    )

    print(
        f"Observaciones combinadas: {len(base):,} | "
        f"Factores: {len(columnas_factores)}"
    )

    resultados = []
    predicciones = []
    coeficientes = []

    for nombre_afp, grupo in base.groupby("afp"):
        grupo = grupo.sort_values("fecha").copy()
        grupo = grupo.dropna(subset=["rendimiento_simple"])

        pretest = grupo["fecha"] < FECHA_CORTE_TEST
        test = grupo["fecha"] >= FECHA_CORTE_TEST

        entrenamiento = grupo.loc[pretest].copy()
        prueba = grupo.loc[test].copy()

        if len(entrenamiento) < 500 or len(prueba) < 50:
            print(
                f"\n{nombre_afp}: datos insuficientes. "
                f"Entrenamiento={len(entrenamiento)}, "
                f"prueba={len(prueba)}"
            )
            continue

        X_train = entrenamiento[columnas_factores]
        y_train = entrenamiento["rendimiento_simple"]
        X_test = prueba[columnas_factores]
        y_test = prueba["rendimiento_simple"]

        tscv = TimeSeriesSplit(n_splits=N_SPLITS)
        modelos = crear_modelos(tscv)

        print("\n" + "=" * 94)
        print(f"AFP: {nombre_afp}")
        print(
            f"Entrenamiento: {entrenamiento['fecha'].min().date()} "
            f"a {entrenamiento['fecha'].max().date()} "
            f"({len(entrenamiento):,} observaciones)"
        )
        print(
            f"Prueba: {prueba['fecha'].min().date()} "
            f"a {prueba['fecha'].max().date()} "
            f"({len(prueba):,} observaciones)"
        )
        print("-" * 94)

        # Benchmark: pronosticar rendimiento cero.
        pred_cero = np.zeros(len(y_test))
        met_cero = metricas(y_test, pred_cero)
        resultados.append(
            {
                "afp": nombre_afp,
                "modelo": "Benchmark_cero",
                "periodo_prueba_inicio": prueba["fecha"].min(),
                "periodo_prueba_fin": prueba["fecha"].max(),
                **met_cero,
                "mejores_parametros": "",
            }
        )

        for nombre_modelo, modelo in modelos.items():
            if nombre_modelo == "ACWI_lineal":
                columnas_modelo = ["ret_ACWI"]
            else:
                columnas_modelo = columnas_factores

            Xtr = entrenamiento[columnas_modelo]
            Xte = prueba[columnas_modelo]

            print(f"Ajustando {nombre_modelo}...")

            modelo_ajustado = clone(modelo)
            modelo_ajustado.fit(Xtr, y_train)
            pred = modelo_ajustado.predict(Xte)

            met = metricas(y_test, pred)

            mejores_parametros = ""
            if hasattr(modelo_ajustado, "best_params_"):
                mejores_parametros = str(
                    modelo_ajustado.best_params_
                )

            resultados.append(
                {
                    "afp": nombre_afp,
                    "modelo": nombre_modelo,
                    "periodo_prueba_inicio": prueba["fecha"].min(),
                    "periodo_prueba_fin": prueba["fecha"].max(),
                    **met,
                    "mejores_parametros": mejores_parametros,
                }
            )

            predicciones.append(
                pd.DataFrame(
                    {
                        "fecha": prueba["fecha"].values,
                        "afp": nombre_afp,
                        "modelo": nombre_modelo,
                        "retorno_real": y_test.values,
                        "retorno_estimado": pred,
                    }
                )
            )

            tabla_coef = extraer_coeficientes(
                nombre_modelo,
                modelo_ajustado,
                columnas_modelo,
                nombre_afp,
            )
            if not tabla_coef.empty:
                coeficientes.append(tabla_coef)

            print(
                f"  RMSE={met['rmse']:.6f} | "
                f"MAE={met['mae']:.6f} | "
                f"R²={met['r2']:.4f} | "
                f"Corr={met['correlacion']:.4f} | "
                f"Dirección={met['acierto_direccion_pct']:.2f}%"
            )

    resultados_df = pd.DataFrame(resultados)

    if resultados_df.empty:
        raise RuntimeError(
            "No se pudo ajustar ningún modelo."
        )

    resultados_df["ranking_rmse"] = (
        resultados_df.groupby("afp")["rmse"]
        .rank(method="first", ascending=True)
        .astype(int)
    )

    predicciones_df = (
        pd.concat(predicciones, ignore_index=True)
        if predicciones
        else pd.DataFrame()
    )

    coeficientes_df = (
        pd.concat(coeficientes, ignore_index=True)
        if coeficientes
        else pd.DataFrame()
    )

    salida_metricas = (
        processed / "modelo_base_nowcast_metricas.csv"
    )
    salida_pred = (
        processed / "modelo_base_nowcast_predicciones.csv"
    )
    salida_coef = (
        processed / "modelo_base_nowcast_coeficientes.csv"
    )

    resultados_df.to_csv(
        salida_metricas,
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    predicciones_df.to_csv(
        salida_pred,
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    coeficientes_df.to_csv(
        salida_coef,
        index=False,
        encoding="utf-8-sig",
    )

    print("\n" + "=" * 94)
    print("RESUMEN DE MODELOS EN EL PERIODO DE PRUEBA")
    print("-" * 94)

    columnas_resumen = [
        "afp",
        "modelo",
        "rmse",
        "mae",
        "r2",
        "correlacion",
        "acierto_direccion_pct",
        "ranking_rmse",
    ]

    print(
        resultados_df.sort_values(
            ["afp", "ranking_rmse"]
        )[columnas_resumen].to_string(index=False)
    )

    print("\nArchivos creados:")
    print(f" - {salida_metricas.resolve()}")
    print(f" - {salida_pred.resolve()}")
    print(f" - {salida_coef.resolve()}")

    print(
        "\nInterpretación:\n"
        "- Este es un modelo de NOWCAST contemporáneo: usa los movimientos "
        "del mercado de la misma fecha para estimar el rendimiento AFP de "
        "esa fecha cuando la SBS todavía no lo ha publicado.\n"
        "- No es todavía un modelo para anticipar el mercado de mañana.\n"
        "- El periodo 2025-2026 se mantuvo fuera del entrenamiento para "
        "evaluar el desempeño con datos no vistos.\n"
        "- Un R² positivo y un RMSE menor que el benchmark son señales útiles, "
        "pero no garantizan rentabilidad de inversión."
    )


if __name__ == "__main__":
    main()
