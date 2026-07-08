from __future__ import annotations

import json
import math
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import joblib
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from scipy import stats
from sklearn.base import clone
from sklearn.compose import TransformedTargetRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import (
    ElasticNet,
    HuberRegressor,
    LinearRegression,
    QuantileRegressor,
    Ridge,
)
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from statsmodels.stats.diagnostic import acorr_ljungbox, het_arch
from statsmodels.graphics.tsaplots import plot_acf


warnings.filterwarnings("ignore")

AFPS = ["Habitat", "Integra", "Prima", "Profuturo"]
RETRASO_PUBLICACION_DIAS = 5
LAGS_ARDL_FACTORES = [0, 1, 2, 3]
LAGS_ARDL_OBJETIVO = [1, 2, 3]
RANDOM_STATE = 42


@dataclass
class ModeloEspecificacion:
    nombre: str
    tipo_features: str  # "estatico" o "ardl"
    rejilla: list[dict[str, Any]]
    constructor: Callable[[dict[str, Any]], Any]


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


def cargar_division(processed: Path) -> tuple[pd.Timestamp, pd.Timestamp]:
    ruta = processed / "ca0001_modelo50_division_temporal.csv"
    if not ruta.exists():
        raise FileNotFoundError("No existe ca0001_modelo50_division_temporal.csv.")

    df = leer_csv_flexible(ruta)
    df["fecha_fin"] = pd.to_datetime(df["fecha_fin"], errors="coerce")

    train = df[df["segmento"].astype(str).eq("entrenamiento_descubrimiento")]
    valid = df[df["segmento"].astype(str).eq("validacion")]

    if train.empty or valid.empty:
        raise ValueError("No se encontraron los segmentos de entrenamiento y validación.")

    return (
        pd.Timestamp(train["fecha_fin"].iloc[0]),
        pd.Timestamp(valid["fecha_fin"].iloc[0]),
    )


def cargar_canasta(processed: Path) -> pd.DataFrame:
    ruta = processed / "ca0001_modelo51_canasta_depurada.csv"
    if not ruta.exists():
        raise FileNotFoundError("No existe ca0001_modelo51_canasta_depurada.csv.")

    df = leer_csv_flexible(ruta)
    if not {"afp", "factor"}.issubset(df.columns):
        raise ValueError("La canasta debe contener las columnas afp y factor.")

    if "orden" not in df.columns:
        df["orden"] = df.groupby("afp").cumcount() + 1

    return (
        df.dropna(subset=["afp", "factor"])
        .sort_values(["afp", "orden"])
        .drop_duplicates(["afp", "factor"])
        .reset_index(drop=True)
    )


def cargar_base(processed: Path) -> pd.DataFrame:
    ruta = processed / "ca0001_modelo56_base_alineada.csv"
    if not ruta.exists():
        raise FileNotFoundError(
            "No existe ca0001_modelo56_base_alineada.csv. Ejecute primero el módulo 56."
        )

    df = leer_csv_flexible(ruta)
    df["fecha_cuota"] = pd.to_datetime(df["fecha_cuota"], errors="coerce")
    df["cuota_sbs"] = pd.to_numeric(df["cuota_sbs"], errors="coerce")
    df["retorno_cuota"] = pd.to_numeric(df["retorno_cuota"], errors="coerce")

    return (
        df.dropna(subset=["fecha_cuota", "afp", "cuota_sbs"])
        .sort_values(["afp", "fecha_cuota"])
        .reset_index(drop=True)
    )


def asignar_segmento(
    fecha: pd.Timestamp,
    fin_train: pd.Timestamp,
    fin_valid: pd.Timestamp,
) -> str:
    if fecha <= fin_train:
        return "entrenamiento"
    if fecha <= fin_valid:
        return "validacion"
    return "prueba"


def construir_pipeline_estimador(estimador: Any) -> Pipeline:
    return Pipeline(
        steps=[
            ("imputador", SimpleImputer(strategy="constant", fill_value=0.0)),
            ("escalador", StandardScaler()),
            ("modelo", estimador),
        ]
    )


def constructor_ols(_: dict[str, Any]) -> Pipeline:
    return construir_pipeline_estimador(LinearRegression())


def constructor_ridge(params: dict[str, Any]) -> Pipeline:
    return construir_pipeline_estimador(Ridge(alpha=float(params["alpha"])))


def constructor_elastic(params: dict[str, Any]) -> Pipeline:
    return construir_pipeline_estimador(
        ElasticNet(
            alpha=float(params["alpha"]),
            l1_ratio=float(params["l1_ratio"]),
            max_iter=20000,
            random_state=RANDOM_STATE,
        )
    )


def constructor_huber(params: dict[str, Any]) -> Pipeline:
    return construir_pipeline_estimador(
        HuberRegressor(
            epsilon=float(params["epsilon"]),
            alpha=float(params["alpha"]),
            max_iter=2000,
        )
    )


def constructor_lad(params: dict[str, Any]) -> Pipeline:
    return construir_pipeline_estimador(
        QuantileRegressor(
            quantile=0.5,
            alpha=float(params["alpha"]),
            solver="highs",
        )
    )


def especificaciones_modelos() -> list[ModeloEspecificacion]:
    return [
        ModeloEspecificacion(
            nombre="OLS",
            tipo_features="estatico",
            rejilla=[{}],
            constructor=constructor_ols,
        ),
        ModeloEspecificacion(
            nombre="RIDGE",
            tipo_features="estatico",
            rejilla=[{"alpha": a} for a in [0.001, 0.01, 0.1, 1.0, 10.0, 100.0]],
            constructor=constructor_ridge,
        ),
        ModeloEspecificacion(
            nombre="ELASTIC_NET",
            tipo_features="estatico",
            rejilla=[
                {"alpha": a, "l1_ratio": l1}
                for a in [0.00001, 0.0001, 0.001, 0.01]
                for l1 in [0.1, 0.5, 0.9]
            ],
            constructor=constructor_elastic,
        ),
        ModeloEspecificacion(
            nombre="HUBER",
            tipo_features="estatico",
            rejilla=[
                {"epsilon": e, "alpha": a}
                for e in [1.1, 1.35, 1.5, 1.75, 2.0]
                for a in [0.000001, 0.0001, 0.01, 0.1]
            ],
            constructor=constructor_huber,
        ),
        ModeloEspecificacion(
            nombre="LAD_Q50",
            tipo_features="estatico",
            rejilla=[
                {"alpha": a}
                for a in [0.0, 0.000001, 0.00001, 0.0001, 0.001, 0.01]
            ],
            constructor=constructor_lad,
        ),
        ModeloEspecificacion(
            nombre="ARDL_OLS",
            tipo_features="ardl",
            rejilla=[{}],
            constructor=constructor_ols,
        ),
        ModeloEspecificacion(
            nombre="ARDL_RIDGE",
            tipo_features="ardl",
            rejilla=[{"alpha": a} for a in [0.001, 0.01, 0.1, 1.0, 10.0, 100.0]],
            constructor=constructor_ridge,
        ),
    ]


def preparar_base_afp(
    base: pd.DataFrame,
    canasta: pd.DataFrame,
    afp: str,
) -> tuple[pd.DataFrame, list[str], list[str]]:
    factores = (
        canasta[canasta["afp"].eq(afp)]
        .sort_values("orden")["factor"]
        .astype(str)
        .tolist()
    )

    columnas_factores = [f"{f}__retorno_alineado" for f in factores]
    faltantes = [c for c in columnas_factores if c not in base.columns]
    if faltantes:
        raise ValueError(f"Faltan columnas para {afp}: {faltantes}")

    g = base[base["afp"].eq(afp)][
        ["fecha_cuota", "cuota_sbs", "retorno_cuota"] + columnas_factores
    ].copy()
    g = g.sort_values("fecha_cuota").reset_index(drop=True)

    for columna in columnas_factores:
        g[columna] = pd.to_numeric(g[columna], errors="coerce").fillna(0.0)

    columnas_estaticas = columnas_factores.copy()

    columnas_ardl: list[str] = []
    for columna in columnas_factores:
        for lag in LAGS_ARDL_FACTORES:
            nueva = f"{columna}__lag{lag}"
            g[nueva] = g[columna].shift(lag)
            columnas_ardl.append(nueva)

    for lag in LAGS_ARDL_OBJETIVO:
        nueva = f"retorno_cuota__lag{lag}"
        g[nueva] = g["retorno_cuota"].shift(lag)
        columnas_ardl.append(nueva)

    return g, columnas_estaticas, columnas_ardl


def metricas_diarias(y_real: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    mascara = np.isfinite(y_real) & np.isfinite(y_pred)
    y = np.asarray(y_real)[mascara]
    p = np.asarray(y_pred)[mascara]

    if len(y) == 0:
        return {
            "n": 0,
            "mae": np.nan,
            "rmse": np.nan,
            "r2": np.nan,
            "sesgo": np.nan,
            "correlacion": np.nan,
            "direccion_diaria_pct": np.nan,
        }

    mae = float(mean_absolute_error(y, p))
    rmse = float(mean_squared_error(y, p) ** 0.5)
    r2 = float(r2_score(y, p)) if len(y) > 1 else np.nan
    sesgo = float(np.mean(p - y))
    correlacion = (
        float(np.corrcoef(y, p)[0, 1])
        if np.std(y) > 0 and np.std(p) > 0
        else np.nan
    )

    mascara_dir = np.abs(p) > 1e-15
    direccion = (
        float((np.sign(y[mascara_dir]) == np.sign(p[mascara_dir])).mean() * 100.0)
        if mascara_dir.any()
        else np.nan
    )

    return {
        "n": int(len(y)),
        "mae": mae,
        "rmse": rmse,
        "r2": r2,
        "sesgo": sesgo,
        "correlacion": correlacion,
        "direccion_diaria_pct": direccion,
    }


def metricas_publicacion(sim: pd.DataFrame) -> dict[str, float]:
    if sim.empty:
        return {
            "n_publicacion": 0,
            "mape_cuota_5d_pct": np.nan,
            "mediana_error_abs_5d_pct": np.nan,
            "p90_error_abs_5d_pct": np.nan,
            "error_maximo_abs_5d_pct": np.nan,
            "sesgo_5d_pct": np.nan,
            "correlacion_retorno_acumulado": np.nan,
            "direccion_acumulada_pct": np.nan,
        }

    pred = sim["retorno_estimado_acumulado"].to_numpy(float)
    real = sim["retorno_real_acumulado"].to_numpy(float)
    mascara_dir = np.abs(pred) > 1e-15

    direccion = (
        float((np.sign(pred[mascara_dir]) == np.sign(real[mascara_dir])).mean() * 100.0)
        if mascara_dir.any()
        else np.nan
    )

    correlacion = (
        float(np.corrcoef(real, pred)[0, 1])
        if np.std(real) > 0 and np.std(pred) > 0
        else np.nan
    )

    return {
        "n_publicacion": int(len(sim)),
        "mape_cuota_5d_pct": float(sim["error_abs_pct"].mean() * 100.0),
        "mediana_error_abs_5d_pct": float(sim["error_abs_pct"].median() * 100.0),
        "p90_error_abs_5d_pct": float(sim["error_abs_pct"].quantile(0.90) * 100.0),
        "error_maximo_abs_5d_pct": float(sim["error_abs_pct"].max() * 100.0),
        "sesgo_5d_pct": float(sim["error_pct"].mean() * 100.0),
        "correlacion_retorno_acumulado": correlacion,
        "direccion_acumulada_pct": direccion,
    }


def obtener_columnas(tipo_features: str, columnas_estaticas: list[str], columnas_ardl: list[str]) -> list[str]:
    return columnas_estaticas if tipo_features == "estatico" else columnas_ardl


def ajustar_modelo(
    especificacion: ModeloEspecificacion,
    params: dict[str, Any],
    datos: pd.DataFrame,
    columnas: list[str],
) -> Any:
    muestra = datos.dropna(subset=["retorno_cuota"]).copy()
    if especificacion.tipo_features == "ardl":
        muestra = muestra.dropna(subset=columnas)

    X = muestra[columnas]
    y = muestra["retorno_cuota"]
    modelo = especificacion.constructor(params)
    modelo.fit(X, y)
    return modelo


def predecir_un_paso(
    modelo: Any,
    datos: pd.DataFrame,
    columnas: list[str],
    tipo_features: str,
) -> pd.DataFrame:
    muestra = datos.dropna(subset=["retorno_cuota"]).copy()
    if tipo_features == "ardl":
        muestra = muestra.dropna(subset=columnas)

    muestra["retorno_estimado"] = modelo.predict(muestra[columnas])

    return muestra[
        ["fecha_cuota", "cuota_sbs", "retorno_cuota", "retorno_estimado"]
    ].copy()


def construir_fila_ardl_recursiva(
    g: pd.DataFrame,
    indice: int,
    columnas_ardl: list[str],
    historia_retorno: list[float],
) -> pd.DataFrame:
    fila: dict[str, float] = {}

    for columna in columnas_ardl:
        if columna.startswith("retorno_cuota__lag"):
            lag = int(columna.rsplit("lag", 1)[1])
            fila[columna] = historia_retorno[-lag] if len(historia_retorno) >= lag else 0.0
        else:
            valor = g.loc[indice, columna]
            fila[columna] = 0.0 if pd.isna(valor) else float(valor)

    return pd.DataFrame([fila], columns=columnas_ardl)


def simular_publicacion_5d(
    g: pd.DataFrame,
    modelo: Any,
    tipo_features: str,
    columnas: list[str],
    fecha_inicio: pd.Timestamp,
    fecha_fin: pd.Timestamp,
) -> pd.DataFrame:
    resultados = []

    indices_objetivo = g.index[
        g["fecha_cuota"].ge(fecha_inicio)
        & g["fecha_cuota"].le(fecha_fin)
    ].tolist()

    for i in indices_objetivo:
        fecha_obj = pd.Timestamp(g.loc[i, "fecha_cuota"])
        fecha_corte = fecha_obj - pd.Timedelta(days=RETRASO_PUBLICACION_DIAS)

        candidatos = g.index[g["fecha_cuota"].le(fecha_corte)].tolist()
        if not candidatos:
            continue

        a = candidatos[-1]
        if a >= i:
            continue

        historia = g.loc[:a, "retorno_cuota"].dropna().astype(float).tolist()
        predicciones_ocultas: list[float] = []

        for j in range(a + 1, i + 1):
            if tipo_features == "estatico":
                X = pd.DataFrame([g.loc[j, columnas].to_dict()], columns=columnas)
            else:
                X = construir_fila_ardl_recursiva(
                    g=g,
                    indice=j,
                    columnas_ardl=columnas,
                    historia_retorno=historia,
                )

            pred = float(modelo.predict(X)[0])
            predicciones_ocultas.append(pred)
            historia.append(pred)

        cuota_ancla = float(g.loc[a, "cuota_sbs"])
        cuota_real = float(g.loc[i, "cuota_sbs"])
        retorno_estimado_acumulado = float(
            np.prod(1.0 + np.asarray(predicciones_ocultas)) - 1.0
        )
        retorno_real_acumulado = float(cuota_real / cuota_ancla - 1.0)
        cuota_estimada = float(cuota_ancla * (1.0 + retorno_estimado_acumulado))
        error_pct = float(cuota_estimada / cuota_real - 1.0)

        resultados.append(
            {
                "fecha_hoy_simulada": fecha_obj,
                "fecha_ultima_cuota_visible": pd.Timestamp(g.loc[a, "fecha_cuota"]),
                "cuotas_ocultas_estimadas": int(i - a),
                "cuota_ultima_visible": cuota_ancla,
                "cuota_estimada_hoy": cuota_estimada,
                "cuota_real_hoy": cuota_real,
                "error_pct": error_pct,
                "error_abs_pct": abs(error_pct),
                "retorno_estimado_acumulado": retorno_estimado_acumulado,
                "retorno_real_acumulado": retorno_real_acumulado,
            }
        )

    return pd.DataFrame(resultados)


def seleccionar_hiperparametros(
    especificacion: ModeloEspecificacion,
    g: pd.DataFrame,
    columnas: list[str],
    fin_train: pd.Timestamp,
    fin_valid: pd.Timestamp,
) -> tuple[dict[str, Any], pd.DataFrame]:
    train = g[g["fecha_cuota"].le(fin_train)].copy()
    valid = g[
        g["fecha_cuota"].gt(fin_train)
        & g["fecha_cuota"].le(fin_valid)
    ].copy()

    filas = []

    for params in especificacion.rejilla:
        try:
            modelo = ajustar_modelo(especificacion, params, train, columnas)
            pred_valid = predecir_un_paso(
                modelo,
                valid,
                columnas,
                especificacion.tipo_features,
            )
            met_diaria = metricas_diarias(
                pred_valid["retorno_cuota"].to_numpy(float),
                pred_valid["retorno_estimado"].to_numpy(float),
            )

            sim_valid = simular_publicacion_5d(
                g=g,
                modelo=modelo,
                tipo_features=especificacion.tipo_features,
                columnas=columnas,
                fecha_inicio=pd.Timestamp(valid["fecha_cuota"].min()),
                fecha_fin=fin_valid,
            )
            met_5d = metricas_publicacion(sim_valid)

            filas.append(
                {
                    "modelo": especificacion.nombre,
                    "parametros": json.dumps(params, sort_keys=True),
                    "val_mae": met_diaria["mae"],
                    "val_rmse": met_diaria["rmse"],
                    "val_r2": met_diaria["r2"],
                    "val_direccion_pct": met_diaria["direccion_diaria_pct"],
                    "val_mape_5d_pct": met_5d["mape_cuota_5d_pct"],
                    "val_p90_5d_pct": met_5d["p90_error_abs_5d_pct"],
                    "estado": "CORRECTO",
                }
            )
        except Exception as exc:
            filas.append(
                {
                    "modelo": especificacion.nombre,
                    "parametros": json.dumps(params, sort_keys=True),
                    "val_mae": np.nan,
                    "val_rmse": np.nan,
                    "val_r2": np.nan,
                    "val_direccion_pct": np.nan,
                    "val_mape_5d_pct": np.nan,
                    "val_p90_5d_pct": np.nan,
                    "estado": f"ERROR: {exc}",
                }
            )

    resultados = pd.DataFrame(filas)
    validos = resultados[
        resultados["estado"].eq("CORRECTO")
        & resultados["val_mape_5d_pct"].notna()
    ].copy()

    if validos.empty:
        raise RuntimeError(
            f"No se pudo ajustar ningún candidato válido para {especificacion.nombre}."
        )

    validos = validos.sort_values(
        ["val_mape_5d_pct", "val_mae", "val_p90_5d_pct"],
        ascending=[True, True, True],
    )
    mejor = json.loads(validos.iloc[0]["parametros"])
    resultados["seleccionado"] = resultados["parametros"].eq(
        json.dumps(mejor, sort_keys=True)
    )

    return mejor, resultados


def diagnosticos_residuales(residuos: pd.Series) -> dict[str, float]:
    r = residuos.dropna()
    salida = {
        "n_residuos": int(len(r)),
        "ljungbox_p_lag5": np.nan,
        "ljungbox_p_lag10": np.nan,
        "ljungbox_p_lag20": np.nan,
        "arch_lm_p_lag10": np.nan,
        "asimetria_residual": np.nan,
        "curtosis_exceso_residual": np.nan,
    }

    if len(r) >= 40:
        lb = acorr_ljungbox(r, lags=[5, 10, 20], return_df=True)
        salida["ljungbox_p_lag5"] = float(lb.loc[5, "lb_pvalue"])
        salida["ljungbox_p_lag10"] = float(lb.loc[10, "lb_pvalue"])
        salida["ljungbox_p_lag20"] = float(lb.loc[20, "lb_pvalue"])

    if len(r) >= 50:
        try:
            salida["arch_lm_p_lag10"] = float(het_arch(r, nlags=10)[1])
        except Exception:
            pass

    if len(r) >= 5:
        salida["asimetria_residual"] = float(stats.skew(r, bias=False))
        salida["curtosis_exceso_residual"] = float(
            stats.kurtosis(r, fisher=True, bias=False)
        )

    return salida


def diebold_mariano(
    perdida_modelo: np.ndarray,
    perdida_referencia: np.ndarray,
    max_lag: int,
) -> dict[str, float]:
    mascara = np.isfinite(perdida_modelo) & np.isfinite(perdida_referencia)
    d = np.asarray(perdida_modelo)[mascara] - np.asarray(perdida_referencia)[mascara]
    n = len(d)

    if n < 30:
        return {
            "n_dm": n,
            "dm_estadistico": np.nan,
            "dm_pvalor": np.nan,
            "diferencia_media_perdida": np.nan,
        }

    media = float(np.mean(d))
    centrado = d - media
    gamma0 = float(np.dot(centrado, centrado) / n)
    var_hac = gamma0

    for lag in range(1, min(max_lag, n - 1) + 1):
        gamma = float(np.dot(centrado[lag:], centrado[:-lag]) / n)
        peso = 1.0 - lag / (max_lag + 1.0)
        var_hac += 2.0 * peso * gamma

    var_media = var_hac / n
    if var_media <= 0:
        estadistico = np.nan
        pvalor = np.nan
    else:
        estadistico = media / math.sqrt(var_media)
        pvalor = float(2.0 * (1.0 - stats.norm.cdf(abs(estadistico))))

    return {
        "n_dm": int(n),
        "dm_estadistico": float(estadistico) if np.isfinite(estadistico) else np.nan,
        "dm_pvalor": pvalor,
        "diferencia_media_perdida": media,
    }


def guardar_figura(ruta: Path) -> None:
    plt.tight_layout()
    plt.savefig(ruta, dpi=160, bbox_inches="tight")
    plt.close()


def crear_graficos(
    metricas_diarias_df: pd.DataFrame,
    metricas_5d_df: pd.DataFrame,
    predicciones_df: pd.DataFrame,
    simulaciones_df: pd.DataFrame,
    ranking_df: pd.DataFrame,
    graficos: Path,
) -> None:
    graficos.mkdir(parents=True, exist_ok=True)

    for afp in AFPS:
        prueba_d = metricas_diarias_df[
            metricas_diarias_df["afp"].eq(afp)
            & metricas_diarias_df["segmento"].eq("prueba")
        ].sort_values("mae")

        if not prueba_d.empty:
            x = np.arange(len(prueba_d))
            ancho = 0.36
            plt.figure(figsize=(11, 5))
            plt.bar(x - ancho / 2, prueba_d["mae"], width=ancho, label="MAE")
            plt.bar(x + ancho / 2, prueba_d["rmse"], width=ancho, label="RMSE")
            plt.xticks(x, prueba_d["modelo"], rotation=30, ha="right")
            plt.ylabel("Error del retorno")
            plt.title(f"Comparación diaria en prueba — {afp}")
            plt.legend()
            guardar_figura(graficos / f"01_mae_rmse_test_{afp.lower()}.png")

        prueba_5d = metricas_5d_df[
            metricas_5d_df["afp"].eq(afp)
            & metricas_5d_df["segmento"].eq("prueba")
        ].sort_values("mape_cuota_5d_pct")

        if not prueba_5d.empty:
            x = np.arange(len(prueba_5d))
            ancho = 0.36
            plt.figure(figsize=(11, 5))
            plt.bar(
                x - ancho / 2,
                prueba_5d["mape_cuota_5d_pct"],
                width=ancho,
                label="MAPE",
            )
            plt.bar(
                x + ancho / 2,
                prueba_5d["p90_error_abs_5d_pct"],
                width=ancho,
                label="P90",
            )
            plt.xticks(x, prueba_5d["modelo"], rotation=30, ha="right")
            plt.ylabel("Porcentaje")
            plt.title(f"Cuota no publicada: MAPE y P90 en prueba — {afp}")
            plt.legend()
            guardar_figura(graficos / f"02_mape_p90_test_{afp.lower()}.png")

        ranking_afp = ranking_df[ranking_df["afp"].eq(afp)]
        if not ranking_afp.empty:
            ganador = ranking_afp.sort_values(
                ["ranking_validacion_mape", "mape_prueba_pct"]
            ).iloc[0]["modelo"]

            pred = predicciones_df[
                predicciones_df["afp"].eq(afp)
                & predicciones_df["modelo"].eq(ganador)
                & predicciones_df["segmento"].eq("prueba")
            ].sort_values("fecha_cuota")

            if not pred.empty:
                plt.figure(figsize=(12, 5))
                plt.plot(
                    pred["fecha_cuota"],
                    pred["retorno_cuota"] * 100.0,
                    label="Retorno SBS",
                )
                plt.plot(
                    pred["fecha_cuota"],
                    pred["retorno_estimado"] * 100.0,
                    label=f"Estimado {ganador}",
                )
                plt.axhline(0, linewidth=1)
                plt.ylabel("Retorno diario (%)")
                plt.title(f"Retorno real vs estimado — {afp} — {ganador}")
                plt.legend()
                guardar_figura(
                    graficos / f"03_retorno_real_estimado_{afp.lower()}.png"
                )

                residuos = pred["retorno_cuota"] - pred["retorno_estimado"]
                plt.figure(figsize=(9, 5))
                plt.hist(residuos.dropna(), bins=50)
                plt.axvline(residuos.mean(), linestyle="--", label="Media")
                plt.xlabel("Residuo")
                plt.ylabel("Frecuencia")
                plt.title(f"Distribución de residuos — {afp} — {ganador}")
                plt.legend()
                guardar_figura(
                    graficos / f"04_residuos_histograma_{afp.lower()}.png"
                )

                if residuos.dropna().shape[0] >= 50:
                    plt.figure(figsize=(9, 5))
                    plot_acf(residuos.dropna(), lags=30, zero=False, ax=plt.gca())
                    plt.title(f"ACF de residuos — {afp} — {ganador}")
                    guardar_figura(
                        graficos / f"05_residuos_acf_{afp.lower()}.png"
                    )

            sim = simulaciones_df[
                simulaciones_df["afp"].eq(afp)
                & simulaciones_df["modelo"].eq(ganador)
                & simulaciones_df["segmento"].eq("prueba")
            ].sort_values("fecha_hoy_simulada")

            if not sim.empty:
                plt.figure(figsize=(12, 5))
                plt.plot(
                    sim["fecha_hoy_simulada"],
                    sim["cuota_real_hoy"],
                    label="Cuota SBS real",
                )
                plt.plot(
                    sim["fecha_hoy_simulada"],
                    sim["cuota_estimada_hoy"],
                    label=f"Cuota estimada {ganador}",
                )
                plt.ylabel("Valor cuota")
                plt.title(f"Cuota SBS vs estimada con retraso de cinco días — {afp}")
                plt.legend()
                guardar_figura(
                    graficos / f"06_cuota_real_estimada_{afp.lower()}.png"
                )

    pivote = metricas_5d_df[
        metricas_5d_df["segmento"].eq("prueba")
    ].pivot(index="modelo", columns="afp", values="mape_cuota_5d_pct")

    if not pivote.empty:
        pivote = pivote.reindex(columns=AFPS)
        plt.figure(figsize=(9, max(5, len(pivote) * 0.6)))
        imagen = plt.imshow(pivote.to_numpy(), aspect="auto")
        plt.colorbar(imagen, label="MAPE cuota (%)")
        plt.xticks(range(len(pivote.columns)), pivote.columns)
        plt.yticks(range(len(pivote.index)), pivote.index)
        plt.title("Mapa de calor del MAPE operativo en prueba")
        for i in range(len(pivote.index)):
            for j in range(len(pivote.columns)):
                valor = pivote.iloc[i, j]
                if pd.notna(valor):
                    plt.text(j, i, f"{valor:.3f}", ha="center", va="center")
        guardar_figura(graficos / "07_heatmap_mape_test.png")


def main() -> None:
    raiz = Path(__file__).resolve().parents[1]
    processed = raiz / "data" / "processed"
    graficos = processed / "graficos_modelo64"
    modelos_dir = processed / "modelos_modelo64"
    graficos.mkdir(parents=True, exist_ok=True)
    modelos_dir.mkdir(parents=True, exist_ok=True)

    fin_train, fin_valid = cargar_division(processed)
    canasta = cargar_canasta(processed)
    base = cargar_base(processed)
    especificaciones = especificaciones_modelos()

    metricas_diarias_todas = []
    metricas_5d_todas = []
    predicciones_todas = []
    simulaciones_todas = []
    seleccion_todas = []
    diagnosticos_todos = []
    modelos_guardados: dict[tuple[str, str], Any] = {}

    for afp in AFPS:
        print(f"\nProcesando {afp}...")
        g, columnas_estaticas, columnas_ardl = preparar_base_afp(base, canasta, afp)

        fecha_inicio_valid = pd.Timestamp(
            g.loc[g["fecha_cuota"].gt(fin_train), "fecha_cuota"].min()
        )
        fecha_inicio_test = pd.Timestamp(
            g.loc[g["fecha_cuota"].gt(fin_valid), "fecha_cuota"].min()
        )
        fecha_fin_total = pd.Timestamp(g["fecha_cuota"].max())

        for especificacion in especificaciones:
            columnas = obtener_columnas(
                especificacion.tipo_features,
                columnas_estaticas,
                columnas_ardl,
            )

            mejor_params, tabla_grid = seleccionar_hiperparametros(
                especificacion=especificacion,
                g=g,
                columnas=columnas,
                fin_train=fin_train,
                fin_valid=fin_valid,
            )
            tabla_grid["afp"] = afp
            seleccion_todas.append(tabla_grid)

            train = g[g["fecha_cuota"].le(fin_train)].copy()
            train_valid = g[g["fecha_cuota"].le(fin_valid)].copy()
            valid = g[
                g["fecha_cuota"].gt(fin_train)
                & g["fecha_cuota"].le(fin_valid)
            ].copy()
            test = g[g["fecha_cuota"].gt(fin_valid)].copy()

            modelo_train = ajustar_modelo(
                especificacion, mejor_params, train, columnas
            )
            modelo_final = ajustar_modelo(
                especificacion, mejor_params, train_valid, columnas
            )
            modelos_guardados[(afp, especificacion.nombre)] = modelo_final
            joblib.dump(
                {
                    "modelo": modelo_final,
                    "afp": afp,
                    "nombre_modelo": especificacion.nombre,
                    "tipo_features": especificacion.tipo_features,
                    "columnas": columnas,
                    "parametros": mejor_params,
                    "fecha_fin_entrenamiento_final": str(fin_valid.date()),
                },
                modelos_dir / f"{afp.lower()}_{especificacion.nombre.lower()}.joblib",
            )

            bloques = [
                ("entrenamiento", train, modelo_train),
                ("validacion", valid, modelo_train),
                ("prueba", test, modelo_final),
            ]

            for nombre_segmento, datos_segmento, modelo_segmento in bloques:
                pred = predecir_un_paso(
                    modelo_segmento,
                    datos_segmento,
                    columnas,
                    especificacion.tipo_features,
                )
                pred["afp"] = afp
                pred["modelo"] = especificacion.nombre
                pred["segmento"] = nombre_segmento
                predicciones_todas.append(pred)

                met = metricas_diarias(
                    pred["retorno_cuota"].to_numpy(float),
                    pred["retorno_estimado"].to_numpy(float),
                )
                metricas_diarias_todas.append(
                    {
                        "afp": afp,
                        "modelo": especificacion.nombre,
                        "segmento": nombre_segmento,
                        "tipo_features": especificacion.tipo_features,
                        "parametros": json.dumps(mejor_params, sort_keys=True),
                        **met,
                    }
                )

                residuos = pred["retorno_cuota"] - pred["retorno_estimado"]
                diagnosticos_todos.append(
                    {
                        "afp": afp,
                        "modelo": especificacion.nombre,
                        "segmento": nombre_segmento,
                        **diagnosticos_residuales(residuos),
                    }
                )

            simulaciones_segmentos = [
                (
                    "entrenamiento",
                    modelo_train,
                    pd.Timestamp(g["fecha_cuota"].min()),
                    fin_train,
                ),
                (
                    "validacion",
                    modelo_train,
                    fecha_inicio_valid,
                    fin_valid,
                ),
                (
                    "prueba",
                    modelo_final,
                    fecha_inicio_test,
                    fecha_fin_total,
                ),
            ]

            for nombre_segmento, modelo_segmento, inicio, fin in simulaciones_segmentos:
                sim = simular_publicacion_5d(
                    g=g,
                    modelo=modelo_segmento,
                    tipo_features=especificacion.tipo_features,
                    columnas=columnas,
                    fecha_inicio=inicio,
                    fecha_fin=fin,
                )
                sim["afp"] = afp
                sim["modelo"] = especificacion.nombre
                sim["segmento"] = nombre_segmento
                simulaciones_todas.append(sim)

                met5 = metricas_publicacion(sim)
                metricas_5d_todas.append(
                    {
                        "afp": afp,
                        "modelo": especificacion.nombre,
                        "segmento": nombre_segmento,
                        "tipo_features": especificacion.tipo_features,
                        "parametros": json.dumps(mejor_params, sort_keys=True),
                        **met5,
                    }
                )

    metricas_diarias_df = pd.DataFrame(metricas_diarias_todas)
    metricas_5d_df = pd.DataFrame(metricas_5d_todas)
    predicciones_df = pd.concat(predicciones_todas, ignore_index=True)
    simulaciones_df = pd.concat(simulaciones_todas, ignore_index=True)
    seleccion_df = pd.concat(seleccion_todas, ignore_index=True)
    diagnosticos_df = pd.DataFrame(diagnosticos_todos)

    # Añadir baselines oficiales del módulo 63 corregido
    ruta_base_diaria = processed / "ca0001_modelo63_corregido_metricas_diarias.csv"
    ruta_base_5d = processed / "ca0001_modelo63_corregido_metricas_publicacion_5d.csv"

    if ruta_base_diaria.exists():
        bd = leer_csv_flexible(ruta_base_diaria)
        bd = bd[bd["baseline"].isin(["RETORNO_CERO", "MEDIA_EXPANSIVA"])].copy()
        bd = bd.rename(columns={"baseline": "modelo"})
        bd["tipo_features"] = "baseline"
        bd["parametros"] = "{}"
        columnas_comunes = [c for c in metricas_diarias_df.columns if c in bd.columns]
        metricas_diarias_df = pd.concat(
            [metricas_diarias_df, bd[columnas_comunes]],
            ignore_index=True,
            sort=False,
        )

    if ruta_base_5d.exists():
        b5 = leer_csv_flexible(ruta_base_5d)
        b5 = b5[b5["baseline"].isin(["RETORNO_CERO", "MEDIA_EXPANSIVA"])].copy()
        b5 = b5.rename(columns={"baseline": "modelo"})
        b5["tipo_features"] = "baseline"
        b5["parametros"] = "{}"
        columnas_comunes = [c for c in metricas_5d_df.columns if c in b5.columns]
        metricas_5d_df = pd.concat(
            [metricas_5d_df, b5[columnas_comunes]],
            ignore_index=True,
            sort=False,
        )

    # Ranking: validación determina preferencia; prueba sirve para auditoría
    ranking_filas = []
    for afp in AFPS:
        val = metricas_5d_df[
            metricas_5d_df["afp"].eq(afp)
            & metricas_5d_df["segmento"].eq("validacion")
        ][["modelo", "mape_cuota_5d_pct", "p90_error_abs_5d_pct"]].copy()
        val["ranking_validacion_mape"] = val["mape_cuota_5d_pct"].rank(
            method="min", ascending=True
        )

        test = metricas_5d_df[
            metricas_5d_df["afp"].eq(afp)
            & metricas_5d_df["segmento"].eq("prueba")
        ][
            [
                "modelo",
                "mape_cuota_5d_pct",
                "p90_error_abs_5d_pct",
                "direccion_acumulada_pct",
                "sesgo_5d_pct",
            ]
        ].copy()
        test = test.rename(
            columns={
                "mape_cuota_5d_pct": "mape_prueba_pct",
                "p90_error_abs_5d_pct": "p90_prueba_pct",
                "direccion_acumulada_pct": "direccion_acumulada_prueba_pct",
                "sesgo_5d_pct": "sesgo_prueba_pct",
            }
        )
        combinado = val.merge(test, on="modelo", how="outer")
        combinado["afp"] = afp
        combinado["ranking_prueba_mape"] = combinado["mape_prueba_pct"].rank(
            method="min", ascending=True
        )
        ranking_filas.append(combinado)

    ranking_df = pd.concat(ranking_filas, ignore_index=True)

    # Diebold-Mariano en prueba: pérdida absoluta diaria y operativa
    dm_filas = []
    referencias = ["RIDGE", "MEDIA_EXPANSIVA"]

    for afp in AFPS:
        for referencia in referencias:
            ref_d = predicciones_df[
                predicciones_df["afp"].eq(afp)
                & predicciones_df["modelo"].eq(referencia)
                & predicciones_df["segmento"].eq("prueba")
            ][["fecha_cuota", "retorno_cuota", "retorno_estimado"]].copy()

            if not ref_d.empty:
                ref_d["perdida_ref"] = (
                    ref_d["retorno_cuota"] - ref_d["retorno_estimado"]
                ).abs()

                for modelo in predicciones_df[
                    predicciones_df["afp"].eq(afp)
                    & predicciones_df["segmento"].eq("prueba")
                ]["modelo"].unique():
                    cand = predicciones_df[
                        predicciones_df["afp"].eq(afp)
                        & predicciones_df["modelo"].eq(modelo)
                        & predicciones_df["segmento"].eq("prueba")
                    ][["fecha_cuota", "retorno_cuota", "retorno_estimado"]].copy()
                    cand["perdida_modelo"] = (
                        cand["retorno_cuota"] - cand["retorno_estimado"]
                    ).abs()
                    unido = cand.merge(
                        ref_d[["fecha_cuota", "perdida_ref"]],
                        on="fecha_cuota",
                        how="inner",
                    )
                    dm_filas.append(
                        {
                            "afp": afp,
                            "modelo": modelo,
                            "referencia": referencia,
                            "metrica": "error_absoluto_diario",
                            **diebold_mariano(
                                unido["perdida_modelo"].to_numpy(float),
                                unido["perdida_ref"].to_numpy(float),
                                max_lag=1,
                            ),
                        }
                    )

            ref_5 = simulaciones_df[
                simulaciones_df["afp"].eq(afp)
                & simulaciones_df["modelo"].eq(referencia)
                & simulaciones_df["segmento"].eq("prueba")
            ][["fecha_hoy_simulada", "error_abs_pct"]].rename(
                columns={"error_abs_pct": "perdida_ref"}
            )

            if not ref_5.empty:
                for modelo in simulaciones_df[
                    simulaciones_df["afp"].eq(afp)
                    & simulaciones_df["segmento"].eq("prueba")
                ]["modelo"].unique():
                    cand5 = simulaciones_df[
                        simulaciones_df["afp"].eq(afp)
                        & simulaciones_df["modelo"].eq(modelo)
                        & simulaciones_df["segmento"].eq("prueba")
                    ][["fecha_hoy_simulada", "error_abs_pct"]].rename(
                        columns={"error_abs_pct": "perdida_modelo"}
                    )
                    unido5 = cand5.merge(ref_5, on="fecha_hoy_simulada", how="inner")
                    dm_filas.append(
                        {
                            "afp": afp,
                            "modelo": modelo,
                            "referencia": referencia,
                            "metrica": "error_absoluto_cuota_5d",
                            **diebold_mariano(
                                unido5["perdida_modelo"].to_numpy(float),
                                unido5["perdida_ref"].to_numpy(float),
                                max_lag=5,
                            ),
                        }
                    )

    dm_df = pd.DataFrame(dm_filas)

    crear_graficos(
        metricas_diarias_df=metricas_diarias_df,
        metricas_5d_df=metricas_5d_df,
        predicciones_df=predicciones_df,
        simulaciones_df=simulaciones_df,
        ranking_df=ranking_df,
        graficos=graficos,
    )

    rutas = {
        "metricas_diarias": processed / "ca0001_modelo64_metricas_diarias.csv",
        "metricas_5d": processed / "ca0001_modelo64_metricas_publicacion_5d.csv",
        "predicciones": processed / "ca0001_modelo64_predicciones_diarias.csv",
        "simulaciones": processed / "ca0001_modelo64_simulacion_publicacion_5d.csv",
        "seleccion": processed / "ca0001_modelo64_seleccion_hiperparametros.csv",
        "diagnosticos": processed / "ca0001_modelo64_diagnosticos_residuales.csv",
        "ranking": processed / "ca0001_modelo64_ranking_modelos.csv",
        "dm": processed / "ca0001_modelo64_diebold_mariano.csv",
        "resumen": processed / "ca0001_modelo64_resumen.json",
    }

    metricas_diarias_df.to_csv(rutas["metricas_diarias"], index=False, encoding="utf-8-sig")
    metricas_5d_df.to_csv(rutas["metricas_5d"], index=False, encoding="utf-8-sig")
    predicciones_df.to_csv(
        rutas["predicciones"], index=False, encoding="utf-8-sig", date_format="%Y-%m-%d"
    )
    simulaciones_df.to_csv(
        rutas["simulaciones"], index=False, encoding="utf-8-sig", date_format="%Y-%m-%d"
    )
    seleccion_df.to_csv(rutas["seleccion"], index=False, encoding="utf-8-sig")
    diagnosticos_df.to_csv(rutas["diagnosticos"], index=False, encoding="utf-8-sig")
    ranking_df.to_csv(rutas["ranking"], index=False, encoding="utf-8-sig")
    dm_df.to_csv(rutas["dm"], index=False, encoding="utf-8-sig")

    resumen = {
        "version": "modelo64_competencia_lineal_robusta_ardl",
        "fecha_fin_entrenamiento_60pct": str(fin_train.date()),
        "fecha_fin_validacion_20pct": str(fin_valid.date()),
        "modelos": [e.nombre for e in especificaciones],
        "criterio_hiperparametros": (
            "Menor MAPE de cuota en validación; desempate por MAE diario y P90."
        ),
        "ranking": ranking_df.to_dict(orient="records"),
        "graficos_generados": len(list(graficos.glob("*.png"))),
    }
    rutas["resumen"].write_text(
        json.dumps(resumen, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    print("\nMÓDULO 64 — COMPETENCIA DE MODELOS LINEALES, ROBUSTOS Y ARDL")
    print("=" * 150)
    print(
        f"Entrenamiento: hasta {fin_train.date()} | "
        f"Validación: hasta {fin_valid.date()} | "
        "Prueba: periodo posterior"
    )
    print(
        "Selección de hiperparámetros: menor MAPE operativo en validación; "
        "desempate por MAE diario y P90."
    )

    print("\nHIPERPARÁMETROS SELECCIONADOS")
    print("-" * 150)
    seleccion_impresa = (
        seleccion_df[seleccion_df["seleccionado"].eq(True)]
        [["afp", "modelo", "parametros", "val_mae", "val_mape_5d_pct", "val_p90_5d_pct"]]
        .sort_values(["afp", "modelo"])
    )
    print(seleccion_impresa.to_string(index=False))

    print("\nMÉTRICAS DIARIAS — PRUEBA")
    print("-" * 150)
    columnas_diarias = [
        "afp",
        "modelo",
        "n",
        "mae",
        "rmse",
        "r2",
        "sesgo",
        "correlacion",
        "direccion_diaria_pct",
    ]
    print(
        metricas_diarias_df[metricas_diarias_df["segmento"].eq("prueba")]
        [columnas_diarias]
        .sort_values(["afp", "mae"])
        .to_string(index=False)
    )

    print("\nMÉTRICAS DE CUOTA CON RETRASO SBS DE CINCO DÍAS — PRUEBA")
    print("-" * 150)
    columnas_5d = [
        "afp",
        "modelo",
        "n_publicacion",
        "mape_cuota_5d_pct",
        "mediana_error_abs_5d_pct",
        "p90_error_abs_5d_pct",
        "error_maximo_abs_5d_pct",
        "sesgo_5d_pct",
        "correlacion_retorno_acumulado",
        "direccion_acumulada_pct",
    ]
    print(
        metricas_5d_df[metricas_5d_df["segmento"].eq("prueba")]
        [columnas_5d]
        .sort_values(["afp", "mape_cuota_5d_pct"])
        .to_string(index=False)
    )

    print("\nRANKING: VALIDACIÓN VS PRUEBA")
    print("-" * 150)
    print(
        ranking_df[
            [
                "afp",
                "modelo",
                "mape_cuota_5d_pct",
                "ranking_validacion_mape",
                "mape_prueba_pct",
                "ranking_prueba_mape",
                "p90_prueba_pct",
                "direccion_acumulada_prueba_pct",
            ]
        ]
        .sort_values(["afp", "ranking_validacion_mape"])
        .to_string(index=False)
    )

    print("\nARCHIVOS CREADOS")
    print("-" * 150)
    for ruta in rutas.values():
        print(f" - {ruta.resolve()}")
    print(f" - {graficos.resolve()}")
    print(f" - {modelos_dir.resolve()}")

    print(
        "\nLECTURA CORRECTA:\n"
        "- El modelo preferido se selecciona con validación, no mirando la prueba.\n"
        "- La prueba se usa para auditar generalización.\n"
        "- Los ARDL usan retornos anteriores y factores rezagados; durante la "
        "ventana SBS oculta, los retornos del fondo se generan recursivamente.\n"
        "- El siguiente módulo incorporará ARIMAX, Kalman/ventanas adaptativas "
        "y bandas de volatilidad."
    )


if __name__ == "__main__":
    main()
