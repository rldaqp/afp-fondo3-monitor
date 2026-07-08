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
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import ExtraTreesRegressor, GradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.inspection import permutation_importance
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import PolynomialFeatures, StandardScaler
from sklearn.svm import SVR


warnings.filterwarnings("ignore")

AFPS = ["Habitat", "Integra", "Prima", "Profuturo"]
RETRASO_PUBLICACION_DIAS = 5
RANDOM_STATE = 42


@dataclass
class Especificacion:
    tarea: str
    familia: str
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
        raise ValueError("No se encontraron entrenamiento y validación.")

    return (
        pd.Timestamp(train["fecha_fin"].iloc[0]),
        pd.Timestamp(valid["fecha_fin"].iloc[0]),
    )


def cargar_canasta(processed: Path) -> pd.DataFrame:
    ruta = processed / "ca0001_modelo51_canasta_depurada.csv"
    if not ruta.exists():
        raise FileNotFoundError("No existe ca0001_modelo51_canasta_depurada.csv.")

    df = leer_csv_flexible(ruta)
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
        raise FileNotFoundError("No existe ca0001_modelo56_base_alineada.csv.")

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


def preparar_afp(
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
    columnas_base = [f"{factor}__retorno_alineado" for factor in factores]

    faltantes = [c for c in columnas_base if c not in base.columns]
    if faltantes:
        raise ValueError(f"Faltan columnas para {afp}: {faltantes}")

    g = base[base["afp"].eq(afp)][
        ["fecha_cuota", "cuota_sbs", "retorno_cuota"] + columnas_base
    ].copy()
    g = g.sort_values("fecha_cuota").reset_index(drop=True)

    for columna in columnas_base:
        g[columna] = pd.to_numeric(g[columna], errors="coerce").fillna(0.0)

    columnas_diarias: list[str] = []
    for columna in columnas_base:
        nombre = columna.replace("__retorno_alineado", "")

        for lag in range(4):
            nueva = f"{nombre}__lag{lag}"
            g[nueva] = g[columna].shift(lag)
            columnas_diarias.append(nueva)

        g[f"{nombre}__media5"] = g[columna].rolling(5, min_periods=1).mean()
        g[f"{nombre}__vol5"] = g[columna].rolling(5, min_periods=2).std().fillna(0.0)
        g[f"{nombre}__acum5"] = (
            (1.0 + g[columna]).rolling(5, min_periods=1).apply(np.prod, raw=True) - 1.0
        )

        columnas_diarias.extend(
            [
                f"{nombre}__media5",
                f"{nombre}__vol5",
                f"{nombre}__acum5",
            ]
        )

    g[columnas_diarias] = g[columnas_diarias].replace(
        [np.inf, -np.inf], np.nan
    ).fillna(0.0)

    return g, factores, columnas_diarias


def construir_base_directa(
    g: pd.DataFrame,
    factores: list[str],
    columnas_base: list[str],
    fin_train: pd.Timestamp,
    fin_valid: pd.Timestamp,
) -> tuple[pd.DataFrame, list[str]]:
    filas = []

    for i in range(len(g)):
        fecha_obj = pd.Timestamp(g.loc[i, "fecha_cuota"])
        fecha_corte = fecha_obj - pd.Timedelta(days=RETRASO_PUBLICACION_DIAS)

        candidatos = g.index[g["fecha_cuota"].le(fecha_corte)].tolist()
        if not candidatos:
            continue

        a = candidatos[-1]
        if a >= i:
            continue

        ventana = g.loc[a + 1 : i, columnas_base].copy()
        if ventana.empty:
            continue

        caracteristicas: dict[str, float] = {
            "n_cuotas_ocultas": float(i - a),
            "dias_calendario_ocultos": float(
                (fecha_obj - pd.Timestamp(g.loc[a, "fecha_cuota"])).days
            ),
        }

        for factor, columna in zip(factores, columnas_base):
            valores = ventana[columna].astype(float).to_numpy()
            caracteristicas[f"{factor}__oculto_acumulado"] = float(
                np.prod(1.0 + valores) - 1.0
            )
            caracteristicas[f"{factor}__oculto_suma"] = float(np.sum(valores))
            caracteristicas[f"{factor}__oculto_media"] = float(np.mean(valores))
            caracteristicas[f"{factor}__oculto_vol"] = float(
                np.std(valores, ddof=1) if len(valores) > 1 else 0.0
            )
            caracteristicas[f"{factor}__oculto_min"] = float(np.min(valores))
            caracteristicas[f"{factor}__oculto_max"] = float(np.max(valores))
            caracteristicas[f"{factor}__oculto_ultimo"] = float(valores[-1])

        historia_visible = g.loc[:a, "retorno_cuota"].dropna().astype(float)
        cuota_visible = g.loc[:a, "cuota_sbs"].dropna().astype(float)

        caracteristicas["fondo_visible_ultimo_retorno"] = float(
            historia_visible.iloc[-1] if len(historia_visible) else 0.0
        )
        caracteristicas["fondo_visible_media5"] = float(
            historia_visible.tail(5).mean() if len(historia_visible) else 0.0
        )
        caracteristicas["fondo_visible_vol5"] = float(
            historia_visible.tail(5).std(ddof=1)
            if len(historia_visible.tail(5)) > 1
            else 0.0
        )
        caracteristicas["fondo_visible_media20"] = float(
            historia_visible.tail(20).mean() if len(historia_visible) else 0.0
        )
        caracteristicas["fondo_visible_vol20"] = float(
            historia_visible.tail(20).std(ddof=1)
            if len(historia_visible.tail(20)) > 1
            else 0.0
        )
        caracteristicas["fondo_visible_tendencia20"] = float(
            cuota_visible.iloc[-1] / cuota_visible.iloc[-20] - 1.0
            if len(cuota_visible) >= 20
            else 0.0
        )

        cuota_ancla = float(g.loc[a, "cuota_sbs"])
        cuota_real = float(g.loc[i, "cuota_sbs"])
        retorno_real = float(cuota_real / cuota_ancla - 1.0)

        fila = {
            "fecha_hoy_simulada": fecha_obj,
            "fecha_ultima_cuota_visible": pd.Timestamp(g.loc[a, "fecha_cuota"]),
            "cuota_ultima_visible": cuota_ancla,
            "cuota_real_hoy": cuota_real,
            "retorno_acumulado_real": retorno_real,
            "segmento": asignar_segmento(fecha_obj, fin_train, fin_valid),
            **caracteristicas,
        }
        filas.append(fila)

    df = pd.DataFrame(filas)
    columnas_features = [
        c
        for c in df.columns
        if c
        not in {
            "fecha_hoy_simulada",
            "fecha_ultima_cuota_visible",
            "cuota_ultima_visible",
            "cuota_real_hoy",
            "retorno_acumulado_real",
            "segmento",
        }
    ]

    df[columnas_features] = df[columnas_features].replace(
        [np.inf, -np.inf], np.nan
    ).fillna(0.0)

    return df, columnas_features


def pipeline_escalado(modelo: Any) -> Pipeline:
    return Pipeline(
        [
            ("imputador", SimpleImputer(strategy="constant", fill_value=0.0)),
            ("escalador", StandardScaler()),
            ("modelo", modelo),
        ]
    )


def constructor_ridge(params: dict[str, Any]) -> Pipeline:
    return pipeline_escalado(Ridge(alpha=float(params["alpha"])))


def constructor_poly_ridge(params: dict[str, Any]) -> Pipeline:
    return Pipeline(
        [
            ("imputador", SimpleImputer(strategy="constant", fill_value=0.0)),
            (
                "polinomios",
                PolynomialFeatures(
                    degree=2,
                    include_bias=False,
                    interaction_only=bool(params["interaction_only"]),
                ),
            ),
            ("escalador", StandardScaler()),
            ("modelo", Ridge(alpha=float(params["alpha"]))),
        ]
    )


def constructor_svr(params: dict[str, Any]) -> Pipeline:
    return pipeline_escalado(
        SVR(
            kernel="rbf",
            C=float(params["C"]),
            epsilon=float(params["epsilon"]),
            gamma=params["gamma"],
        )
    )


def constructor_gb(params: dict[str, Any]) -> Pipeline:
    return Pipeline(
        [
            ("imputador", SimpleImputer(strategy="constant", fill_value=0.0)),
            (
                "modelo",
                GradientBoostingRegressor(
                    n_estimators=int(params["n_estimators"]),
                    learning_rate=float(params["learning_rate"]),
                    max_depth=int(params["max_depth"]),
                    min_samples_leaf=int(params["min_samples_leaf"]),
                    loss="huber",
                    random_state=RANDOM_STATE,
                ),
            ),
        ]
    )


def constructor_extra(params: dict[str, Any]) -> Pipeline:
    max_depth = params["max_depth"]
    if max_depth is not None:
        max_depth = int(max_depth)

    return Pipeline(
        [
            ("imputador", SimpleImputer(strategy="constant", fill_value=0.0)),
            (
                "modelo",
                ExtraTreesRegressor(
                    n_estimators=250,
                    max_depth=max_depth,
                    min_samples_leaf=int(params["min_samples_leaf"]),
                    max_features=params["max_features"],
                    n_jobs=-1,
                    random_state=RANDOM_STATE,
                ),
            ),
        ]
    )


def especificaciones(tarea: str) -> list[Especificacion]:
    prefijo = "DIARIO" if tarea == "diario" else "DIRECTO"

    return [
        Especificacion(
            tarea=tarea,
            familia=f"{prefijo}_RIDGE",
            rejilla=[
                {"alpha": a}
                for a in [0.001, 0.01, 0.1, 1.0, 10.0, 100.0]
            ],
            constructor=constructor_ridge,
        ),
        Especificacion(
            tarea=tarea,
            familia=f"{prefijo}_POLY_RIDGE",
            rejilla=[
                {"alpha": a, "interaction_only": inter}
                for a in [0.01, 0.1, 1.0, 10.0]
                for inter in [True, False]
            ],
            constructor=constructor_poly_ridge,
        ),
        Especificacion(
            tarea=tarea,
            familia=f"{prefijo}_SVR_RBF",
            rejilla=[
                {"C": c, "epsilon": eps, "gamma": gamma}
                for c in [0.5, 2.0, 10.0]
                for eps in [0.0005, 0.001]
                for gamma in ["scale", 0.1]
            ],
            constructor=constructor_svr,
        ),
        Especificacion(
            tarea=tarea,
            familia=f"{prefijo}_GRADIENT_BOOSTING",
            rejilla=[
                {
                    "n_estimators": n,
                    "learning_rate": lr,
                    "max_depth": depth,
                    "min_samples_leaf": leaf,
                }
                for n in [100, 250]
                for lr in [0.03, 0.05]
                for depth in [1, 2]
                for leaf in [10, 30]
            ],
            constructor=constructor_gb,
        ),
        Especificacion(
            tarea=tarea,
            familia=f"{prefijo}_EXTRA_TREES",
            rejilla=[
                {
                    "max_depth": depth,
                    "min_samples_leaf": leaf,
                    "max_features": mf,
                }
                for depth in [5, None]
                for leaf in [5, 20]
                for mf in [0.7, 1.0]
            ],
            constructor=constructor_extra,
        ),
    ]


def metricas_regresion(y: np.ndarray, p: np.ndarray) -> dict[str, float]:
    y = np.asarray(y, dtype=float)
    p = np.asarray(p, dtype=float)
    mascara = np.isfinite(y) & np.isfinite(p)
    y = y[mascara]
    p = p[mascara]

    if len(y) == 0:
        return {
            "n": 0,
            "mae": np.nan,
            "rmse": np.nan,
            "r2": np.nan,
            "sesgo": np.nan,
            "desviacion_residual": np.nan,
            "varianza_residual": np.nan,
            "correlacion": np.nan,
            "direccion_pct": np.nan,
        }

    residuo = y - p
    mascara_dir = np.abs(p) > 1e-15

    return {
        "n": int(len(y)),
        "mae": float(mean_absolute_error(y, p)),
        "rmse": float(mean_squared_error(y, p) ** 0.5),
        "r2": float(r2_score(y, p)) if len(y) > 1 else np.nan,
        "sesgo": float(np.mean(p - y)),
        "desviacion_residual": float(
            np.std(residuo, ddof=1) if len(residuo) > 1 else np.nan
        ),
        "varianza_residual": float(
            np.var(residuo, ddof=1) if len(residuo) > 1 else np.nan
        ),
        "correlacion": float(
            np.corrcoef(y, p)[0, 1]
            if np.std(y) > 0 and np.std(p) > 0
            else np.nan
        ),
        "direccion_pct": float(
            (
                np.sign(y[mascara_dir])
                == np.sign(p[mascara_dir])
            ).mean()
            * 100.0
            if mascara_dir.any()
            else np.nan
        ),
    }


def metricas_cuota(sim: pd.DataFrame) -> dict[str, float]:
    if sim.empty:
        return {
            "n_publicacion": 0,
            "mape_cuota_pct": np.nan,
            "mediana_error_abs_pct": np.nan,
            "p90_error_abs_pct": np.nan,
            "error_maximo_abs_pct": np.nan,
            "sesgo_cuota_pct": np.nan,
            "correlacion_retorno_acumulado": np.nan,
            "direccion_acumulada_pct": np.nan,
        }

    real = sim["retorno_acumulado_real"].to_numpy(float)
    pred = sim["retorno_acumulado_estimado"].to_numpy(float)
    mascara_dir = np.abs(pred) > 1e-15

    return {
        "n_publicacion": int(len(sim)),
        "mape_cuota_pct": float(sim["error_abs_pct"].mean() * 100.0),
        "mediana_error_abs_pct": float(sim["error_abs_pct"].median() * 100.0),
        "p90_error_abs_pct": float(
            sim["error_abs_pct"].quantile(0.90) * 100.0
        ),
        "error_maximo_abs_pct": float(sim["error_abs_pct"].max() * 100.0),
        "sesgo_cuota_pct": float(sim["error_pct"].mean() * 100.0),
        "correlacion_retorno_acumulado": float(
            np.corrcoef(real, pred)[0, 1]
            if np.std(real) > 0 and np.std(pred) > 0
            else np.nan
        ),
        "direccion_acumulada_pct": float(
            (
                np.sign(real[mascara_dir])
                == np.sign(pred[mascara_dir])
            ).mean()
            * 100.0
            if mascara_dir.any()
            else np.nan
        ),
    }


def simular_diario(
    g: pd.DataFrame,
    modelo: Any,
    columnas: list[str],
    fecha_inicio: pd.Timestamp,
    fecha_fin: pd.Timestamp,
) -> pd.DataFrame:
    filas = []

    indices = g.index[
        g["fecha_cuota"].ge(fecha_inicio)
        & g["fecha_cuota"].le(fecha_fin)
    ].tolist()

    for i in indices:
        fecha_obj = pd.Timestamp(g.loc[i, "fecha_cuota"])
        corte = fecha_obj - pd.Timedelta(days=RETRASO_PUBLICACION_DIAS)
        candidatos = g.index[g["fecha_cuota"].le(corte)].tolist()

        if not candidatos:
            continue

        a = candidatos[-1]
        if a >= i:
            continue

        X = g.loc[a + 1 : i, columnas]
        pred_diaria = np.asarray(modelo.predict(X), dtype=float)
        retorno_estimado = float(np.prod(1.0 + pred_diaria) - 1.0)

        cuota_ancla = float(g.loc[a, "cuota_sbs"])
        cuota_real = float(g.loc[i, "cuota_sbs"])
        cuota_estimada = float(cuota_ancla * (1.0 + retorno_estimado))
        retorno_real = float(cuota_real / cuota_ancla - 1.0)
        error_pct = float(cuota_estimada / cuota_real - 1.0)

        filas.append(
            {
                "fecha_hoy_simulada": fecha_obj,
                "fecha_ultima_cuota_visible": pd.Timestamp(
                    g.loc[a, "fecha_cuota"]
                ),
                "cuota_ultima_visible": cuota_ancla,
                "cuota_real_hoy": cuota_real,
                "cuota_estimada_hoy": cuota_estimada,
                "retorno_acumulado_real": retorno_real,
                "retorno_acumulado_estimado": retorno_estimado,
                "error_pct": error_pct,
                "error_abs_pct": abs(error_pct),
            }
        )

    return pd.DataFrame(filas)


def predecir_directo(
    df: pd.DataFrame,
    modelo: Any,
    columnas: list[str],
) -> pd.DataFrame:
    salida = df[
        [
            "fecha_hoy_simulada",
            "fecha_ultima_cuota_visible",
            "cuota_ultima_visible",
            "cuota_real_hoy",
            "retorno_acumulado_real",
            "segmento",
        ]
    ].copy()

    salida["retorno_acumulado_estimado"] = modelo.predict(df[columnas])
    salida["cuota_estimada_hoy"] = (
        salida["cuota_ultima_visible"]
        * (1.0 + salida["retorno_acumulado_estimado"])
    )
    salida["error_pct"] = (
        salida["cuota_estimada_hoy"] / salida["cuota_real_hoy"] - 1.0
    )
    salida["error_abs_pct"] = salida["error_pct"].abs()

    return salida


def seleccionar_familia_diaria(
    especificacion: Especificacion,
    g: pd.DataFrame,
    columnas: list[str],
    fin_train: pd.Timestamp,
    fin_valid: pd.Timestamp,
) -> tuple[dict[str, Any], pd.DataFrame]:
    train = g[g["fecha_cuota"].le(fin_train)].dropna(
        subset=["retorno_cuota"]
    )
    valid = g[
        g["fecha_cuota"].gt(fin_train)
        & g["fecha_cuota"].le(fin_valid)
    ].dropna(subset=["retorno_cuota"])

    filas = []

    for params in especificacion.rejilla:
        try:
            modelo = especificacion.constructor(params)
            modelo.fit(train[columnas], train["retorno_cuota"])

            pred_valid = modelo.predict(valid[columnas])
            met_diaria = metricas_regresion(
                valid["retorno_cuota"].to_numpy(float),
                pred_valid,
            )

            sim_valid = simular_diario(
                g,
                modelo,
                columnas,
                pd.Timestamp(valid["fecha_cuota"].min()),
                fin_valid,
            )
            met_cuota = metricas_cuota(sim_valid)

            filas.append(
                {
                    "familia": especificacion.familia,
                    "parametros": json.dumps(params, sort_keys=True),
                    "val_mae": met_diaria["mae"],
                    "val_r2": met_diaria["r2"],
                    "val_mape_cuota_pct": met_cuota["mape_cuota_pct"],
                    "val_p90_pct": met_cuota["p90_error_abs_pct"],
                    "estado": "CORRECTO",
                }
            )
        except Exception as exc:
            filas.append(
                {
                    "familia": especificacion.familia,
                    "parametros": json.dumps(params, sort_keys=True),
                    "val_mae": np.nan,
                    "val_r2": np.nan,
                    "val_mape_cuota_pct": np.nan,
                    "val_p90_pct": np.nan,
                    "estado": f"ERROR: {exc}",
                }
            )

    tabla = pd.DataFrame(filas)
    validos = tabla[
        tabla["estado"].eq("CORRECTO")
        & tabla["val_mape_cuota_pct"].notna()
    ].sort_values(
        ["val_mape_cuota_pct", "val_mae", "val_p90_pct"]
    )

    if validos.empty:
        raise RuntimeError(f"Sin candidatos válidos: {especificacion.familia}")

    mejor = json.loads(validos.iloc[0]["parametros"])
    tabla["seleccionado"] = tabla["parametros"].eq(
        json.dumps(mejor, sort_keys=True)
    )

    return mejor, tabla


def seleccionar_familia_directa(
    especificacion: Especificacion,
    df: pd.DataFrame,
    columnas: list[str],
) -> tuple[dict[str, Any], pd.DataFrame]:
    train = df[df["segmento"].eq("entrenamiento")]
    valid = df[df["segmento"].eq("validacion")]

    filas = []

    for params in especificacion.rejilla:
        try:
            modelo = especificacion.constructor(params)
            modelo.fit(
                train[columnas],
                train["retorno_acumulado_real"],
            )

            sim_valid = predecir_directo(valid, modelo, columnas)
            met_ret = metricas_regresion(
                sim_valid["retorno_acumulado_real"].to_numpy(float),
                sim_valid["retorno_acumulado_estimado"].to_numpy(float),
            )
            met_cuota = metricas_cuota(sim_valid)

            filas.append(
                {
                    "familia": especificacion.familia,
                    "parametros": json.dumps(params, sort_keys=True),
                    "val_mae": met_ret["mae"],
                    "val_r2": met_ret["r2"],
                    "val_mape_cuota_pct": met_cuota["mape_cuota_pct"],
                    "val_p90_pct": met_cuota["p90_error_abs_pct"],
                    "estado": "CORRECTO",
                }
            )
        except Exception as exc:
            filas.append(
                {
                    "familia": especificacion.familia,
                    "parametros": json.dumps(params, sort_keys=True),
                    "val_mae": np.nan,
                    "val_r2": np.nan,
                    "val_mape_cuota_pct": np.nan,
                    "val_p90_pct": np.nan,
                    "estado": f"ERROR: {exc}",
                }
            )

    tabla = pd.DataFrame(filas)
    validos = tabla[
        tabla["estado"].eq("CORRECTO")
        & tabla["val_mape_cuota_pct"].notna()
    ].sort_values(
        ["val_mape_cuota_pct", "val_mae", "val_p90_pct"]
    )

    if validos.empty:
        raise RuntimeError(f"Sin candidatos válidos: {especificacion.familia}")

    mejor = json.loads(validos.iloc[0]["parametros"])
    tabla["seleccionado"] = tabla["parametros"].eq(
        json.dumps(mejor, sort_keys=True)
    )

    return mejor, tabla


def diebold_mariano(
    perdida_modelo: np.ndarray,
    perdida_ref: np.ndarray,
    max_lag: int = 5,
) -> dict[str, float]:
    modelo = np.asarray(perdida_modelo, dtype=float)
    ref = np.asarray(perdida_ref, dtype=float)

    mascara = np.isfinite(modelo) & np.isfinite(ref)
    d = modelo[mascara] - ref[mascara]
    n = len(d)

    if n < 30:
        return {
            "n_dm": int(n),
            "diferencia_media_perdida": np.nan,
            "dm_estadistico": np.nan,
            "dm_pvalor": np.nan,
        }

    media = float(np.mean(d))
    c = d - media
    gamma0 = float(np.dot(c, c) / n)
    var_hac = gamma0

    for lag in range(1, min(max_lag, n - 1) + 1):
        gamma = float(np.dot(c[lag:], c[:-lag]) / n)
        peso = 1.0 - lag / (max_lag + 1.0)
        var_hac += 2.0 * peso * gamma

    var_media = var_hac / n

    if var_media <= 0:
        return {
            "n_dm": int(n),
            "diferencia_media_perdida": media,
            "dm_estadistico": np.nan,
            "dm_pvalor": np.nan,
        }

    estadistico = media / math.sqrt(var_media)
    pvalor = float(
        2.0 * (1.0 - stats.norm.cdf(abs(estadistico)))
    )

    return {
        "n_dm": int(n),
        "diferencia_media_perdida": media,
        "dm_estadistico": float(estadistico),
        "dm_pvalor": pvalor,
    }


def ajustar_holm(pvalores: pd.Series) -> pd.Series:
    p = pvalores.astype(float)
    validos = p.dropna().sort_values()
    m = len(validos)
    corregidos = pd.Series(np.nan, index=p.index, dtype=float)

    max_previo = 0.0
    for posicion, (indice, valor) in enumerate(validos.items(), start=1):
        ajustado = min(1.0, (m - posicion + 1) * valor)
        ajustado = max(max_previo, ajustado)
        corregidos.loc[indice] = ajustado
        max_previo = ajustado

    return corregidos


def importancia_permutacion(
    modelo: Any,
    X: pd.DataFrame,
    y: pd.Series,
    afp: str,
    nombre_modelo: str,
    tarea: str,
) -> pd.DataFrame:
    if len(X) < 30:
        return pd.DataFrame()

    resultado = permutation_importance(
        modelo,
        X,
        y,
        scoring="neg_mean_absolute_error",
        n_repeats=5,
        random_state=RANDOM_STATE,
        n_jobs=-1,
    )

    return (
        pd.DataFrame(
            {
                "afp": afp,
                "modelo": nombre_modelo,
                "tarea": tarea,
                "variable": X.columns,
                "importancia_media": resultado.importances_mean,
                "importancia_desv": resultado.importances_std,
            }
        )
        .sort_values("importancia_media", ascending=False)
        .reset_index(drop=True)
    )


def guardar_figura(ruta: Path) -> None:
    plt.tight_layout()
    plt.savefig(ruta, dpi=160, bbox_inches="tight")
    plt.close()


def generar_graficos(
    ranking_test: pd.DataFrame,
    simulaciones: pd.DataFrame,
    importancia: pd.DataFrame,
    graficos: Path,
) -> None:
    graficos.mkdir(parents=True, exist_ok=True)

    for afp in AFPS:
        tabla = ranking_test[ranking_test["afp"].eq(afp)].sort_values(
            "mape_cuota_pct"
        )

        if not tabla.empty:
            x = np.arange(len(tabla))
            ancho = 0.36

            plt.figure(figsize=(12, 5))
            plt.bar(
                x - ancho / 2,
                tabla["mape_cuota_pct"],
                width=ancho,
                label="MAPE",
            )
            plt.bar(
                x + ancho / 2,
                tabla["p90_error_abs_pct"],
                width=ancho,
                label="P90",
            )
            plt.xticks(x, tabla["modelo"], rotation=35, ha="right")
            plt.ylabel("Porcentaje")
            plt.title(f"Modelos no lineales y directos — {afp}")
            plt.legend()
            guardar_figura(graficos / f"01_mape_p90_{afp.lower()}.png")

        seleccionado = tabla[tabla["seleccionado_validacion"].eq(True)]
        if not seleccionado.empty:
            nombre = seleccionado.iloc[0]["modelo"]
            sim = simulaciones[
                simulaciones["afp"].eq(afp)
                & simulaciones["modelo"].eq(nombre)
                & simulaciones["segmento"].eq("prueba")
            ].sort_values("fecha_hoy_simulada")

            if not sim.empty:
                plt.figure(figsize=(12, 5))
                plt.plot(
                    sim["fecha_hoy_simulada"],
                    sim["cuota_real_hoy"],
                    label="Cuota SBS",
                )
                plt.plot(
                    sim["fecha_hoy_simulada"],
                    sim["cuota_estimada_hoy"],
                    label=nombre,
                )
                plt.ylabel("Valor cuota")
                plt.title(
                    f"Ganador por validación: cuota real vs estimada — {afp}"
                )
                plt.legend()
                guardar_figura(
                    graficos / f"02_cuota_ganador_{afp.lower()}.png"
                )

                plt.figure(figsize=(6, 6))
                plt.scatter(
                    sim["retorno_acumulado_real"] * 100.0,
                    sim["retorno_acumulado_estimado"] * 100.0,
                    s=14,
                    alpha=0.6,
                )
                minimo = min(
                    sim["retorno_acumulado_real"].min(),
                    sim["retorno_acumulado_estimado"].min(),
                ) * 100.0
                maximo = max(
                    sim["retorno_acumulado_real"].max(),
                    sim["retorno_acumulado_estimado"].max(),
                ) * 100.0
                plt.plot([minimo, maximo], [minimo, maximo], linestyle="--")
                plt.xlabel("Retorno acumulado real (%)")
                plt.ylabel("Retorno acumulado estimado (%)")
                plt.title(f"Retorno acumulado real vs estimado — {afp}")
                guardar_figura(
                    graficos / f"03_scatter_ganador_{afp.lower()}.png"
                )

        imp = importancia[importancia["afp"].eq(afp)].head(15)
        if not imp.empty:
            imp = imp.sort_values("importancia_media")
            plt.figure(figsize=(10, 6))
            plt.barh(imp["variable"], imp["importancia_media"])
            plt.xlabel("Incremento del MAE al permutar la variable")
            plt.title(f"Variables más importantes — {afp}")
            guardar_figura(
                graficos / f"04_importancia_{afp.lower()}.png"
            )


def main() -> None:
    raiz = Path(__file__).resolve().parents[1]
    processed = raiz / "data" / "processed"
    graficos = processed / "graficos_modelo66"
    modelos_dir = processed / "modelos_modelo66"
    graficos.mkdir(parents=True, exist_ok=True)
    modelos_dir.mkdir(parents=True, exist_ok=True)

    fin_train, fin_valid = cargar_division(processed)
    canasta = cargar_canasta(processed)
    base = cargar_base(processed)

    seleccion_todas = []
    metricas_todas = []
    simulaciones_todas = []
    importancia_todas = []
    campeones_validacion = []

    for afp in AFPS:
        print(f"\nProcesando modelos no lineales para {afp}...")

        g, factores, columnas_diarias = preparar_afp(
            base,
            canasta,
            afp,
        )
        columnas_base = [
            f"{factor}__retorno_alineado"
            for factor in factores
        ]

        directa, columnas_directas = construir_base_directa(
            g,
            factores,
            columnas_base,
            fin_train,
            fin_valid,
        )

        resultados_afp = []

        # Modelos diarios que luego se acumulan
        for especificacion in especificaciones("diario"):
            mejor, tabla = seleccionar_familia_diaria(
                especificacion,
                g,
                columnas_diarias,
                fin_train,
                fin_valid,
            )
            tabla["afp"] = afp
            tabla["tarea"] = "diario_recursivo"
            seleccion_todas.append(tabla)

            train = g[
                g["fecha_cuota"].le(fin_train)
            ].dropna(subset=["retorno_cuota"])
            train_valid = g[
                g["fecha_cuota"].le(fin_valid)
            ].dropna(subset=["retorno_cuota"])

            modelo_train = especificacion.constructor(mejor)
            modelo_train.fit(
                train[columnas_diarias],
                train["retorno_cuota"],
            )

            modelo_final = especificacion.constructor(mejor)
            modelo_final.fit(
                train_valid[columnas_diarias],
                train_valid["retorno_cuota"],
            )

            nombre = especificacion.familia
            joblib.dump(
                {
                    "afp": afp,
                    "tarea": "diario_recursivo",
                    "modelo": modelo_final,
                    "columnas": columnas_diarias,
                    "parametros": mejor,
                },
                modelos_dir / f"{afp.lower()}_{nombre.lower()}.joblib",
            )

            segmentos = [
                (
                    "entrenamiento",
                    modelo_train,
                    pd.Timestamp(g["fecha_cuota"].min()),
                    fin_train,
                ),
                (
                    "validacion",
                    modelo_train,
                    pd.Timestamp(
                        g.loc[
                            g["fecha_cuota"].gt(fin_train),
                            "fecha_cuota",
                        ].min()
                    ),
                    fin_valid,
                ),
                (
                    "prueba",
                    modelo_final,
                    pd.Timestamp(
                        g.loc[
                            g["fecha_cuota"].gt(fin_valid),
                            "fecha_cuota",
                        ].min()
                    ),
                    pd.Timestamp(g["fecha_cuota"].max()),
                ),
            ]

            for seg, modelo_seg, inicio, fin in segmentos:
                sim = simular_diario(
                    g,
                    modelo_seg,
                    columnas_diarias,
                    inicio,
                    fin,
                )
                sim["afp"] = afp
                sim["modelo"] = nombre
                sim["tarea"] = "diario_recursivo"
                sim["segmento"] = seg
                simulaciones_todas.append(sim)

                met_ret = metricas_regresion(
                    sim["retorno_acumulado_real"].to_numpy(float),
                    sim["retorno_acumulado_estimado"].to_numpy(float),
                )
                met_cuota = metricas_cuota(sim)

                fila = {
                    "afp": afp,
                    "modelo": nombre,
                    "tarea": "diario_recursivo",
                    "segmento": seg,
                    "parametros": json.dumps(mejor, sort_keys=True),
                    **{
                        f"retorno_acumulado_{k}": v
                        for k, v in met_ret.items()
                    },
                    **met_cuota,
                }
                metricas_todas.append(fila)

                if seg == "validacion":
                    resultados_afp.append(fila)

            test_rows = g[g["fecha_cuota"].gt(fin_valid)].dropna(
                subset=["retorno_cuota"]
            )
            importancia_todas.append(
                importancia_permutacion(
                    modelo_final,
                    test_rows[columnas_diarias],
                    test_rows["retorno_cuota"],
                    afp,
                    nombre,
                    "diario_recursivo",
                )
            )

        # Modelos directos del retorno oculto acumulado
        for especificacion in especificaciones("directo"):
            mejor, tabla = seleccionar_familia_directa(
                especificacion,
                directa,
                columnas_directas,
            )
            tabla["afp"] = afp
            tabla["tarea"] = "directo_acumulado"
            seleccion_todas.append(tabla)

            train = directa[
                directa["segmento"].eq("entrenamiento")
            ]
            train_valid = directa[
                directa["segmento"].isin(
                    ["entrenamiento", "validacion"]
                )
            ]

            modelo_train = especificacion.constructor(mejor)
            modelo_train.fit(
                train[columnas_directas],
                train["retorno_acumulado_real"],
            )

            modelo_final = especificacion.constructor(mejor)
            modelo_final.fit(
                train_valid[columnas_directas],
                train_valid["retorno_acumulado_real"],
            )

            nombre = especificacion.familia
            joblib.dump(
                {
                    "afp": afp,
                    "tarea": "directo_acumulado",
                    "modelo": modelo_final,
                    "columnas": columnas_directas,
                    "parametros": mejor,
                },
                modelos_dir / f"{afp.lower()}_{nombre.lower()}.joblib",
            )

            for seg, modelo_seg in [
                ("entrenamiento", modelo_train),
                ("validacion", modelo_train),
                ("prueba", modelo_final),
            ]:
                bloque = directa[directa["segmento"].eq(seg)]
                sim = predecir_directo(
                    bloque,
                    modelo_seg,
                    columnas_directas,
                )
                sim["afp"] = afp
                sim["modelo"] = nombre
                sim["tarea"] = "directo_acumulado"
                sim["segmento"] = seg
                simulaciones_todas.append(sim)

                met_ret = metricas_regresion(
                    sim["retorno_acumulado_real"].to_numpy(float),
                    sim["retorno_acumulado_estimado"].to_numpy(float),
                )
                met_cuota = metricas_cuota(sim)

                fila = {
                    "afp": afp,
                    "modelo": nombre,
                    "tarea": "directo_acumulado",
                    "segmento": seg,
                    "parametros": json.dumps(mejor, sort_keys=True),
                    **{
                        f"retorno_acumulado_{k}": v
                        for k, v in met_ret.items()
                    },
                    **met_cuota,
                }
                metricas_todas.append(fila)

                if seg == "validacion":
                    resultados_afp.append(fila)

            test_directo = directa[directa["segmento"].eq("prueba")]
            importancia_todas.append(
                importancia_permutacion(
                    modelo_final,
                    test_directo[columnas_directas],
                    test_directo["retorno_acumulado_real"],
                    afp,
                    nombre,
                    "directo_acumulado",
                )
            )

        # Campeón por validación entre los modelos nuevos
        tabla_validacion = pd.DataFrame(resultados_afp)
        ganador = tabla_validacion.sort_values(
            [
                "mape_cuota_pct",
                "retorno_acumulado_mae",
                "p90_error_abs_pct",
            ]
        ).iloc[0]

        campeones_validacion.append(
            {
                "afp": afp,
                "modelo": ganador["modelo"],
                "tarea": ganador["tarea"],
                "mape_validacion_pct": ganador["mape_cuota_pct"],
                "r2_validacion": ganador["retorno_acumulado_r2"],
            }
        )

    seleccion_df = pd.concat(seleccion_todas, ignore_index=True)
    metricas_df = pd.DataFrame(metricas_todas)
    simulaciones_df = pd.concat(simulaciones_todas, ignore_index=True)
    importancia_df = pd.concat(
        [x for x in importancia_todas if not x.empty],
        ignore_index=True,
    )
    campeones_df = pd.DataFrame(campeones_validacion)

    # Incorporar Ridge y EW Ridge como referencias
    ruta_m65 = processed / "ca0001_modelo65_metricas_publicacion_5d.csv"
    ruta_s65 = processed / "ca0001_modelo65_simulacion_publicacion_5d.csv"

    referencias_metricas = []
    referencias_sim = []

    if ruta_m65.exists() and ruta_s65.exists():
        m65 = leer_csv_flexible(ruta_m65)
        s65 = leer_csv_flexible(ruta_s65)

        for afp in AFPS:
            modelos_ref = (
                m65[
                    m65["afp"].eq(afp)
                    & m65["segmento"].isin(
                        ["validacion", "prueba"]
                    )
                    & m65["familia"].isin(
                        ["REFERENCIA", "EW_RIDGE"]
                    )
                ]["modelo"]
                .dropna()
                .unique()
                .tolist()
            )

            for modelo in modelos_ref:
                for seg in ["validacion", "prueba"]:
                    fila = m65[
                        m65["afp"].eq(afp)
                        & m65["modelo"].eq(modelo)
                        & m65["segmento"].eq(seg)
                    ]
                    if fila.empty:
                        continue

                    r = fila.iloc[0]
                    referencias_metricas.append(
                        {
                            "afp": afp,
                            "modelo": modelo,
                            "tarea": "referencia",
                            "segmento": seg,
                            "parametros": "{}",
                            "retorno_acumulado_n": r.get(
                                "n_publicacion",
                                np.nan,
                            ),
                            "retorno_acumulado_mae": np.nan,
                            "retorno_acumulado_rmse": np.nan,
                            "retorno_acumulado_r2": np.nan,
                            "retorno_acumulado_sesgo": np.nan,
                            "retorno_acumulado_desviacion_residual": np.nan,
                            "retorno_acumulado_varianza_residual": np.nan,
                            "retorno_acumulado_correlacion": r.get(
                                "correlacion_retorno_acumulado",
                                np.nan,
                            ),
                            "retorno_acumulado_direccion_pct": r.get(
                                "direccion_acumulada_pct",
                                np.nan,
                            ),
                            "n_publicacion": r.get(
                                "n_publicacion",
                                np.nan,
                            ),
                            "mape_cuota_pct": r.get(
                                "mape_cuota_5d_pct",
                                np.nan,
                            ),
                            "mediana_error_abs_pct": r.get(
                                "mediana_error_abs_5d_pct",
                                np.nan,
                            ),
                            "p90_error_abs_pct": r.get(
                                "p90_error_abs_5d_pct",
                                np.nan,
                            ),
                            "error_maximo_abs_pct": r.get(
                                "error_maximo_abs_5d_pct",
                                np.nan,
                            ),
                            "sesgo_cuota_pct": r.get(
                                "sesgo_5d_pct",
                                np.nan,
                            ),
                            "correlacion_retorno_acumulado": r.get(
                                "correlacion_retorno_acumulado",
                                np.nan,
                            ),
                            "direccion_acumulada_pct": r.get(
                                "direccion_acumulada_pct",
                                np.nan,
                            ),
                        }
                    )

                sim_ref = s65[
                    s65["afp"].eq(afp)
                    & s65["modelo"].eq(modelo)
                    & s65["segmento"].isin(
                        ["validacion", "prueba"]
                    )
                ].copy()

                if not sim_ref.empty:
                    sim_ref = sim_ref.rename(
                        columns={
                            "retorno_real_acumulado": (
                                "retorno_acumulado_real"
                            ),
                            "retorno_estimado_acumulado": (
                                "retorno_acumulado_estimado"
                            ),
                        }
                    )
                    sim_ref["tarea"] = "referencia"
                    referencias_sim.append(sim_ref)

    if referencias_metricas:
        metricas_df = pd.concat(
            [metricas_df, pd.DataFrame(referencias_metricas)],
            ignore_index=True,
            sort=False,
        )

    if referencias_sim:
        simulaciones_df = pd.concat(
            [simulaciones_df] + referencias_sim,
            ignore_index=True,
            sort=False,
        )

    # Selección global por validación, incluyendo referencias
    ranking_validacion = metricas_df[
        metricas_df["segmento"].eq("validacion")
    ].copy()
    ranking_validacion["ranking_validacion"] = ranking_validacion.groupby(
        "afp"
    )["mape_cuota_pct"].rank(method="min", ascending=True)

    seleccion_global = (
        ranking_validacion.sort_values(
            [
                "afp",
                "mape_cuota_pct",
                "p90_error_abs_pct",
            ]
        )
        .groupby("afp", as_index=False)
        .first()
        [["afp", "modelo", "tarea", "mape_cuota_pct"]]
        .rename(
            columns={
                "mape_cuota_pct": "mape_validacion_ganador_pct"
            }
        )
    )

    ranking_test = metricas_df[
        metricas_df["segmento"].eq("prueba")
    ].copy()
    ranking_test = ranking_test.merge(
        seleccion_global[["afp", "modelo"]].assign(
            seleccionado_validacion=True
        ),
        on=["afp", "modelo"],
        how="left",
    )
    ranking_test["seleccionado_validacion"] = (
        ranking_test["seleccionado_validacion"].fillna(False)
    )
    ranking_test["ranking_mape_prueba"] = ranking_test.groupby(
        "afp"
    )["mape_cuota_pct"].rank(method="min", ascending=True)

    # DM contra EW Ridge seleccionado en cada AFP
    dm_filas = []

    for afp in AFPS:
        referencia = simulaciones_df[
            simulaciones_df["afp"].eq(afp)
            & simulaciones_df["tarea"].eq("referencia")
            & simulaciones_df["modelo"].astype(str).str.startswith(
                "EW_RIDGE"
            )
            & simulaciones_df["segmento"].eq("prueba")
        ][["fecha_hoy_simulada", "error_abs_pct"]].copy()

        referencia["fecha_hoy_simulada"] = pd.to_datetime(
            referencia["fecha_hoy_simulada"],
            errors="coerce",
        ).dt.normalize()
        referencia = referencia.dropna().drop_duplicates(
            "fecha_hoy_simulada"
        ).rename(
            columns={
                "error_abs_pct": "perdida_referencia"
            }
        )

        candidatos = simulaciones_df[
            simulaciones_df["afp"].eq(afp)
            & simulaciones_df["segmento"].eq("prueba")
            & ~simulaciones_df["tarea"].eq("referencia")
        ]["modelo"].dropna().unique()

        for modelo in candidatos:
            cand = simulaciones_df[
                simulaciones_df["afp"].eq(afp)
                & simulaciones_df["modelo"].eq(modelo)
                & simulaciones_df["segmento"].eq("prueba")
            ][["fecha_hoy_simulada", "error_abs_pct"]].copy()

            cand["fecha_hoy_simulada"] = pd.to_datetime(
                cand["fecha_hoy_simulada"],
                errors="coerce",
            ).dt.normalize()
            cand = cand.dropna().drop_duplicates(
                "fecha_hoy_simulada"
            ).rename(
                columns={
                    "error_abs_pct": "perdida_modelo"
                }
            )

            unido = cand.merge(
                referencia,
                on="fecha_hoy_simulada",
                how="inner",
            )

            resultado = diebold_mariano(
                unido["perdida_modelo"].to_numpy(float),
                unido["perdida_referencia"].to_numpy(float),
                max_lag=5,
            )

            dm_filas.append(
                {
                    "afp": afp,
                    "modelo": modelo,
                    "referencia": "EW_RIDGE",
                    **resultado,
                }
            )

    dm_df = pd.DataFrame(dm_filas)
    dm_df["pvalor_holm"] = ajustar_holm(dm_df["dm_pvalor"])
    dm_df["supera_ew_con_evidencia"] = (
        dm_df["diferencia_media_perdida"].lt(0)
        & dm_df["pvalor_holm"].lt(0.05)
    )

    # Conservar importancia solo del ganador global por validación
    importancia_ganadores = []
    for _, fila in seleccion_global.iterrows():
        imp = importancia_df[
            importancia_df["afp"].eq(fila["afp"])
            & importancia_df["modelo"].eq(fila["modelo"])
        ].copy()
        if not imp.empty:
            importancia_ganadores.append(imp)

    importancia_final = (
        pd.concat(importancia_ganadores, ignore_index=True)
        if importancia_ganadores
        else pd.DataFrame()
    )

    generar_graficos(
        ranking_test,
        simulaciones_df,
        importancia_final,
        graficos,
    )

    rutas = {
        "seleccion": (
            processed
            / "ca0001_modelo66_seleccion_hiperparametros.csv"
        ),
        "metricas": (
            processed
            / "ca0001_modelo66_metricas_comparables.csv"
        ),
        "simulaciones": (
            processed
            / "ca0001_modelo66_simulaciones_cuota.csv"
        ),
        "ranking_validacion": (
            processed
            / "ca0001_modelo66_ranking_validacion.csv"
        ),
        "ranking_prueba": (
            processed
            / "ca0001_modelo66_ranking_prueba.csv"
        ),
        "seleccion_global": (
            processed
            / "ca0001_modelo66_ganadores_validacion.csv"
        ),
        "dm": (
            processed
            / "ca0001_modelo66_diebold_mariano_vs_ew.csv"
        ),
        "importancia": (
            processed
            / "ca0001_modelo66_importancia_variables.csv"
        ),
        "resumen": (
            processed
            / "ca0001_modelo66_resumen.json"
        ),
    }

    seleccion_df.to_csv(
        rutas["seleccion"],
        index=False,
        encoding="utf-8-sig",
    )
    metricas_df.to_csv(
        rutas["metricas"],
        index=False,
        encoding="utf-8-sig",
    )
    simulaciones_df.to_csv(
        rutas["simulaciones"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    ranking_validacion.to_csv(
        rutas["ranking_validacion"],
        index=False,
        encoding="utf-8-sig",
    )
    ranking_test.to_csv(
        rutas["ranking_prueba"],
        index=False,
        encoding="utf-8-sig",
    )
    seleccion_global.to_csv(
        rutas["seleccion_global"],
        index=False,
        encoding="utf-8-sig",
    )
    dm_df.to_csv(
        rutas["dm"],
        index=False,
        encoding="utf-8-sig",
    )
    importancia_final.to_csv(
        rutas["importancia"],
        index=False,
        encoding="utf-8-sig",
    )

    resumen = {
        "version": "modelo66_no_lineales_y_objetivo_directo",
        "fin_entrenamiento": str(fin_train.date()),
        "fin_validacion": str(fin_valid.date()),
        "criterio_seleccion": (
            "Menor MAPE de cuota en validación; desempate por MAE "
            "del retorno acumulado y P90."
        ),
        "ganadores_validacion": seleccion_global.to_dict(
            orient="records"
        ),
        "graficos_generados": len(list(graficos.glob("*.png"))),
    }

    rutas["resumen"].write_text(
        json.dumps(
            resumen,
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )

    print(
        "\nMÓDULO 66 — MODELOS NO LINEALES Y OBJETIVO DIRECTO"
    )
    print("=" * 155)
    print(
        "Se comparan modelos diarios acumulados y modelos que estiman "
        "directamente el retorno oculto entre la última cuota visible y hoy."
    )

    print("\nGANADORES DE HIPERPARÁMETROS POR FAMILIA")
    print("-" * 155)
    print(
        seleccion_df[seleccion_df["seleccionado"].eq(True)]
        [
            [
                "afp",
                "tarea",
                "familia",
                "parametros",
                "val_mae",
                "val_r2",
                "val_mape_cuota_pct",
                "val_p90_pct",
            ]
        ]
        .sort_values(["afp", "tarea", "familia"])
        .to_string(index=False)
    )

    print("\nGANADOR GLOBAL SEGÚN VALIDACIÓN")
    print("-" * 155)
    print(seleccion_global.to_string(index=False))

    print("\nRANKING OPERATIVO EN PRUEBA")
    print("-" * 155)
    print(
        ranking_test[
            [
                "afp",
                "modelo",
                "tarea",
                "mape_cuota_pct",
                "mediana_error_abs_pct",
                "p90_error_abs_pct",
                "error_maximo_abs_pct",
                "sesgo_cuota_pct",
                "correlacion_retorno_acumulado",
                "direccion_acumulada_pct",
                "retorno_acumulado_mae",
                "retorno_acumulado_rmse",
                "retorno_acumulado_r2",
                "ranking_mape_prueba",
                "seleccionado_validacion",
            ]
        ]
        .sort_values(["afp", "ranking_mape_prueba"])
        .to_string(index=False)
    )

    print("\nDIEBOLD-MARIANO CONTRA EW RIDGE")
    print("-" * 155)
    print(
        dm_df[
            [
                "afp",
                "modelo",
                "n_dm",
                "diferencia_media_perdida",
                "dm_estadistico",
                "dm_pvalor",
                "pvalor_holm",
                "supera_ew_con_evidencia",
            ]
        ]
        .sort_values(["afp", "pvalor_holm"])
        .to_string(index=False)
    )

    print("\nVARIABLES MÁS IMPORTANTES DE LOS GANADORES")
    print("-" * 155)
    if importancia_final.empty:
        print("No se generó importancia por permutación.")
    else:
        print(
            importancia_final.groupby("afp", group_keys=False)
            .head(10)
            [
                [
                    "afp",
                    "modelo",
                    "tarea",
                    "variable",
                    "importancia_media",
                    "importancia_desv",
                ]
            ]
            .to_string(index=False)
        )

    print("\nARCHIVOS CREADOS")
    print("-" * 155)
    for ruta in rutas.values():
        print(f" - {ruta.resolve()}")
    print(f" - {graficos.resolve()}")
    print(f" - {modelos_dir.resolve()}")

    print(
        "\nLECTURA CORRECTA:\n"
        "- La validación elige el modelo; la prueba solo audita.\n"
        "- Los modelos DIRECTO estiman de una sola vez el retorno oculto "
        "acumulado y no necesitan encadenar retornos diarios.\n"
        "- Los modelos DIARIO predicen cada retorno y luego los acumulan.\n"
        "- El ganador debe mejorar MAPE y P90 sin deteriorar de forma "
        "grave la dirección ni producir sobreajuste.\n"
        "- La prueba Diebold-Mariano usa corrección de Holm por "
        "comparaciones múltiples."
    )


if __name__ == "__main__":
    main()
