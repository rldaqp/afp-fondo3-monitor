from __future__ import annotations

import json
import math
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from scipy import stats
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.preprocessing import StandardScaler


warnings.filterwarnings("ignore")

AFPS = ["Habitat", "Integra", "Prima", "Profuturo"]

BASELINE = {
    "Habitat": [
        {"factor": "ret_IDX_VIX", "lag": 0},
        {"factor": "ret_USD_COPX", "lag": 0},
    ],
    "Integra": [
        {"factor": "ret_USD_COPX", "lag": 0},
        {"factor": "ret_USD_EPU", "lag": 0},
    ],
    "Prima": [
        {"factor": "ret_USD_COPX", "lag": 0},
        {"factor": "ret_USD_EPU", "lag": 0},
        {"factor": "ret_IDX_VIX", "lag": 0},
        {"factor": "ret_USD_XLB", "lag": 0},
    ],
    "Profuturo": [
        {"factor": "ret_USD_COPX", "lag": 0},
        {"factor": "ret_USD_EPU", "lag": 0},
    ],
}

ALPHAS_RIDGE = [0.001, 0.01, 0.1, 1.0, 10.0, 100.0]
ALPHAS_EW = [0.001, 0.1, 10.0]
VIDAS_MEDIAS = [60, 120, 250, 500]

MAX_CANDIDATOS = 35
MAX_ADICIONES = 8
UMBRAL_REDUNDANCIA = 0.97
MEJORA_MINIMA_MAPE_PUNTOS = 0.003
TOLERANCIA_P90_PUNTOS = 0.05
RETRASO_PUBLICACION_DIAS = 5
MIN_FILAS = 500


@dataclass
class ModeloLineal:
    scaler: StandardScaler
    ridge: Ridge
    familia: str
    alpha: float
    half_life: int | None
    columnas: list[str]

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        z = self.scaler.transform(X[self.columnas])
        return self.ridge.predict(z)


def leer_csv(ruta: Path) -> pd.DataFrame:
    intentos = [
        {"encoding": "utf-8-sig"},
        {"encoding": "latin-1"},
    ]
    ultimo = None
    for args in intentos:
        try:
            return pd.read_csv(ruta, **args)
        except Exception as exc:
            ultimo = exc
    raise RuntimeError(f"No se pudo leer {ruta}: {ultimo}")


def cargar_division(processed: Path) -> tuple[pd.Timestamp, pd.Timestamp]:
    ruta = processed / "ca0001_modelo50_division_temporal.csv"
    df = leer_csv(ruta)
    df["fecha_fin"] = pd.to_datetime(df["fecha_fin"], errors="coerce")

    train = df[df["segmento"].astype(str).eq("entrenamiento_descubrimiento")]
    valid = df[df["segmento"].astype(str).eq("validacion")]

    if train.empty or valid.empty:
        raise ValueError("No se encontró la división temporal del módulo 50.")

    return (
        pd.Timestamp(train["fecha_fin"].iloc[0]).normalize(),
        pd.Timestamp(valid["fecha_fin"].iloc[0]).normalize(),
    )


def cargar_datos(processed: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    base = leer_csv(processed / "ca0001_modelo56_base_alineada.csv")
    factores = leer_csv(processed / "ca0001_modelo69_factores_ampliados.csv")
    screening = leer_csv(processed / "ca0001_modelo69_screening_train.csv")

    base["fecha_cuota"] = pd.to_datetime(
        base["fecha_cuota"], errors="coerce"
    ).dt.normalize()
    factores["fecha_cuota"] = pd.to_datetime(
        factores["fecha_cuota"], errors="coerce"
    ).dt.normalize()

    base["retorno_cuota"] = pd.to_numeric(
        base["retorno_cuota"], errors="coerce"
    )
    base["cuota_sbs"] = pd.to_numeric(base["cuota_sbs"], errors="coerce")

    for columna in factores.columns:
        if columna != "fecha_cuota":
            factores[columna] = pd.to_numeric(
                factores[columna], errors="coerce"
            )

    return base, factores, screening


def cargar_catalogo(processed: Path) -> pd.DataFrame:
    ruta = processed / "ca0001_modelo69_catalogo_factores.csv"
    if not ruta.exists():
        return pd.DataFrame(
            columns=[
                "factor",
                "ticker",
                "nombre",
                "categoria",
                "transformacion",
                "moneda_modelo",
            ]
        )
    return leer_csv(ruta)


def preparar_panel_afp(
    base: pd.DataFrame,
    factores: pd.DataFrame,
    afp: str,
) -> pd.DataFrame:
    g = (
        base[base["afp"].astype(str).eq(afp)]
        [["fecha_cuota", "cuota_sbs", "retorno_cuota"]]
        .dropna(subset=["fecha_cuota", "cuota_sbs"])
        .drop_duplicates("fecha_cuota", keep="last")
        .sort_values("fecha_cuota")
    )

    panel = g.merge(
        factores,
        on="fecha_cuota",
        how="left",
        validate="one_to_one",
    ).sort_values("fecha_cuota").reset_index(drop=True)

    return panel


def nombre_feature(factor: str, lag: int) -> str:
    return f"{factor}__lag{lag}"


def materializar_features(
    panel: pd.DataFrame,
    especificaciones: list[dict[str, Any]],
) -> tuple[pd.DataFrame, list[str]]:
    x = panel.copy()
    columnas = []

    for spec in especificaciones:
        factor = str(spec["factor"])
        lag = int(spec["lag"])
        columna = nombre_feature(factor, lag)

        if factor not in x.columns:
            raise KeyError(f"No existe el factor {factor}")

        x[columna] = pd.to_numeric(
            x[factor], errors="coerce"
        ).shift(lag)
        columnas.append(columna)

    x[columnas] = x[columnas].replace(
        [np.inf, -np.inf], np.nan
    ).fillna(0.0)

    return x, columnas


def pesos_exponenciales(n: int, half_life: int) -> np.ndarray:
    edades = np.arange(n - 1, -1, -1, dtype=float)
    return np.power(0.5, edades / float(half_life))


def ajustar_modelo(
    X: pd.DataFrame,
    y: pd.Series,
    columnas: list[str],
    familia: str,
    alpha: float,
    half_life: int | None,
) -> ModeloLineal:
    mascara = y.notna()
    Xf = X.loc[mascara, columnas].copy()
    yf = y.loc[mascara].astype(float)

    if len(yf) < MIN_FILAS:
        raise ValueError(f"Muestra insuficiente: {len(yf)}")

    scaler = StandardScaler()
    z = scaler.fit_transform(Xf)

    ridge = Ridge(alpha=float(alpha))

    if familia == "EW_RIDGE":
        if half_life is None:
            raise ValueError("EW_RIDGE requiere half_life.")
        pesos = pesos_exponenciales(len(yf), int(half_life))
        ridge.fit(z, yf, sample_weight=pesos)
    else:
        ridge.fit(z, yf)

    return ModeloLineal(
        scaler=scaler,
        ridge=ridge,
        familia=familia,
        alpha=float(alpha),
        half_life=half_life,
        columnas=columnas,
    )


def predecir_panel(
    panel_features: pd.DataFrame,
    modelo: ModeloLineal,
) -> pd.DataFrame:
    salida = panel_features[
        ["fecha_cuota", "cuota_sbs", "retorno_cuota"]
    ].copy()
    salida["retorno_estimado"] = modelo.predict(panel_features)
    return salida


def simular_publicacion(
    predicciones: pd.DataFrame,
    fecha_inicio: pd.Timestamp,
    fecha_fin: pd.Timestamp,
) -> pd.DataFrame:
    p = predicciones.sort_values("fecha_cuota").reset_index(drop=True)
    filas = []

    objetivos = p[
        p["fecha_cuota"].ge(fecha_inicio)
        & p["fecha_cuota"].le(fecha_fin)
    ]

    for i, fila in objetivos.iterrows():
        fecha_obj = pd.Timestamp(fila["fecha_cuota"])
        corte_visible = fecha_obj - pd.Timedelta(
            days=RETRASO_PUBLICACION_DIAS
        )

        candidatos = p.index[
            p["fecha_cuota"].le(corte_visible)
        ].tolist()

        if not candidatos:
            continue

        ancla = candidatos[-1]
        if ancla >= i:
            continue

        ventana = p.loc[ancla + 1 : i, "retorno_estimado"].astype(float)
        retorno_estimado = float(np.prod(1.0 + ventana.to_numpy()) - 1.0)

        cuota_ancla = float(p.loc[ancla, "cuota_sbs"])
        cuota_real = float(p.loc[i, "cuota_sbs"])
        cuota_estimada = float(cuota_ancla * (1.0 + retorno_estimado))
        retorno_real = float(cuota_real / cuota_ancla - 1.0)
        error_pct = float(cuota_estimada / cuota_real - 1.0)

        filas.append(
            {
                "fecha_hoy_simulada": fecha_obj,
                "fecha_ultima_cuota_visible": pd.Timestamp(
                    p.loc[ancla, "fecha_cuota"]
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


def metricas_diarias(df: pd.DataFrame) -> dict[str, float]:
    x = df.dropna(subset=["retorno_cuota", "retorno_estimado"])
    if x.empty:
        return {
            "n_diario": 0,
            "mae_diario": np.nan,
            "rmse_diario": np.nan,
            "r2_diario": np.nan,
            "correlacion_diaria": np.nan,
            "direccion_diaria_pct": np.nan,
        }

    y = x["retorno_cuota"].to_numpy(float)
    p = x["retorno_estimado"].to_numpy(float)

    correlacion = (
        float(np.corrcoef(y, p)[0, 1])
        if np.std(y) > 0 and np.std(p) > 0
        else np.nan
    )

    mascara = np.abs(p) > 1e-15
    direccion = (
        float((np.sign(y[mascara]) == np.sign(p[mascara])).mean() * 100.0)
        if mascara.any()
        else np.nan
    )

    return {
        "n_diario": int(len(x)),
        "mae_diario": float(mean_absolute_error(y, p)),
        "rmse_diario": float(mean_squared_error(y, p) ** 0.5),
        "r2_diario": float(r2_score(y, p)),
        "correlacion_diaria": correlacion,
        "direccion_diaria_pct": direccion,
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

    correlacion = (
        float(np.corrcoef(real, pred)[0, 1])
        if np.std(real) > 0 and np.std(pred) > 0
        else np.nan
    )

    mascara = np.abs(pred) > 1e-15
    direccion = (
        float(
            (
                np.sign(real[mascara])
                == np.sign(pred[mascara])
            ).mean()
            * 100.0
        )
        if mascara.any()
        else np.nan
    )

    return {
        "n_publicacion": int(len(sim)),
        "mape_cuota_pct": float(sim["error_abs_pct"].mean() * 100.0),
        "mediana_error_abs_pct": float(
            sim["error_abs_pct"].median() * 100.0
        ),
        "p90_error_abs_pct": float(
            sim["error_abs_pct"].quantile(0.90) * 100.0
        ),
        "error_maximo_abs_pct": float(
            sim["error_abs_pct"].max() * 100.0
        ),
        "sesgo_cuota_pct": float(sim["error_pct"].mean() * 100.0),
        "correlacion_retorno_acumulado": correlacion,
        "direccion_acumulada_pct": direccion,
    }


def evaluar_configuracion(
    panel: pd.DataFrame,
    specs: list[dict[str, Any]],
    fin_train: pd.Timestamp,
    fin_valid: pd.Timestamp,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    pf, columnas = materializar_features(panel, specs)
    train = pf[pf["fecha_cuota"].le(fin_train)]
    valid = pf[
        pf["fecha_cuota"].gt(fin_train)
        & pf["fecha_cuota"].le(fin_valid)
    ]

    configuraciones = []

    for alpha in ALPHAS_RIDGE:
        configuraciones.append(
            {
                "familia": "RIDGE",
                "alpha": alpha,
                "half_life": None,
            }
        )

    for half_life in VIDAS_MEDIAS:
        for alpha in ALPHAS_EW:
            configuraciones.append(
                {
                    "familia": "EW_RIDGE",
                    "alpha": alpha,
                    "half_life": half_life,
                }
            )

    filas = []
    simulaciones: dict[int, pd.DataFrame] = {}

    for config_id, cfg in enumerate(configuraciones):
        modelo = ajustar_modelo(
            train,
            train["retorno_cuota"],
            columnas,
            cfg["familia"],
            cfg["alpha"],
            cfg["half_life"],
        )

        pred_todo = predecir_panel(pf, modelo)
        sim = simular_publicacion(
            pred_todo,
            pd.Timestamp(valid["fecha_cuota"].min()),
            fin_valid,
        )

        diaria = metricas_diarias(
            pred_todo[
                pred_todo["fecha_cuota"].gt(fin_train)
                & pred_todo["fecha_cuota"].le(fin_valid)
            ]
        )
        cuota = metricas_cuota(sim)

        fila = {
            "_config_id": int(config_id),
            **cfg,
            **diaria,
            **cuota,
        }
        filas.append(fila)
        simulaciones[int(config_id)] = sim

    tabla = pd.DataFrame(filas).sort_values(
        [
            "mape_cuota_pct",
            "p90_error_abs_pct",
            "mae_diario",
        ]
    ).reset_index(drop=True)

    ganador_serie = tabla.iloc[0].copy()
    config_id_ganador = int(ganador_serie["_config_id"])

    ganador = ganador_serie.drop(labels=["_config_id"]).to_dict()
    tabla_publica = tabla.drop(columns=["_config_id"])

    return ganador, tabla_publica, simulaciones[config_id_ganador]

def correlacion_con_seleccionados(
    panel: pd.DataFrame,
    candidato: dict[str, Any],
    seleccionados: list[dict[str, Any]],
    fin_train: pd.Timestamp,
) -> float:
    if not seleccionados:
        return 0.0

    specs = seleccionados + [candidato]
    pf, columnas = materializar_features(panel, specs)
    train = pf[pf["fecha_cuota"].le(fin_train)]

    col_cand = columnas[-1]
    max_corr = 0.0

    for col in columnas[:-1]:
        corr = train[[col, col_cand]].corr().iloc[0, 1]
        if pd.notna(corr):
            max_corr = max(max_corr, abs(float(corr)))

    return max_corr


def construir_pool(
    screening: pd.DataFrame,
    afp: str,
    baseline: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    base_keys = {
        (str(x["factor"]), int(x["lag"]))
        for x in baseline
    }

    s = screening[
        screening["afp"].astype(str).eq(afp)
    ].copy()

    for col in [
        "abs_spearman_train",
        "cobertura_train_pct",
        "n_train",
        "mejor_lag_train",
    ]:
        s[col] = pd.to_numeric(s[col], errors="coerce")

    s = s[
        s["cobertura_train_pct"].ge(95.0)
        & s["n_train"].ge(1000)
    ].sort_values(
        ["abs_spearman_train", "mutual_information_train"],
        ascending=False,
    )

    pool = []
    for _, fila in s.iterrows():
        spec = {
            "factor": str(fila["factor"]),
            "lag": int(fila["mejor_lag_train"]),
            "spearman_train": float(fila["spearman_train"]),
            "pearson_train": float(fila["pearson_train"]),
            "mutual_information_train": float(
                fila["mutual_information_train"]
            ),
        }
        key = (spec["factor"], spec["lag"])
        if key not in base_keys:
            pool.append(spec)

        if len(pool) >= MAX_CANDIDATOS:
            break

    return pool


def forward_selection(
    panel: pd.DataFrame,
    baseline: list[dict[str, Any]],
    pool: list[dict[str, Any]],
    fin_train: pd.Timestamp,
    fin_valid: pd.Timestamp,
    afp: str,
) -> tuple[list[dict[str, Any]], dict[str, Any], pd.DataFrame]:
    seleccionados = [dict(x) for x in baseline]
    mejor_actual, _, _ = evaluar_configuracion(
        panel, seleccionados, fin_train, fin_valid
    )

    trazas = [
        {
            "afp": afp,
            "paso": 0,
            "accion": "BASELINE",
            "factor": "",
            "lag": np.nan,
            "max_corr_con_seleccionados": np.nan,
            "mape_antes_pct": np.nan,
            "mape_despues_pct": mejor_actual["mape_cuota_pct"],
            "mejora_mape_puntos": np.nan,
            "p90_despues_pct": mejor_actual["p90_error_abs_pct"],
            "familia": mejor_actual["familia"],
            "alpha": mejor_actual["alpha"],
            "half_life": mejor_actual["half_life"],
            "aceptado": True,
        }
    ]

    disponibles = [dict(x) for x in pool]

    for paso in range(1, MAX_ADICIONES + 1):
        evaluados = []

        for cand in disponibles:
            corr = correlacion_con_seleccionados(
                panel,
                cand,
                seleccionados,
                fin_train,
            )

            if corr >= UMBRAL_REDUNDANCIA:
                evaluados.append(
                    {
                        "candidato": cand,
                        "max_corr": corr,
                        "rechazado_redundancia": True,
                    }
                )
                continue

            specs_prueba = seleccionados + [cand]
            ganador, _, _ = evaluar_configuracion(
                panel,
                specs_prueba,
                fin_train,
                fin_valid,
            )
            evaluados.append(
                {
                    "candidato": cand,
                    "max_corr": corr,
                    "rechazado_redundancia": False,
                    "ganador": ganador,
                }
            )

        validos = [
            e for e in evaluados
            if not e["rechazado_redundancia"]
        ]

        if not validos:
            break

        mejor_eval = min(
            validos,
            key=lambda e: (
                e["ganador"]["mape_cuota_pct"],
                e["ganador"]["p90_error_abs_pct"],
            ),
        )

        cand = mejor_eval["candidato"]
        nuevo = mejor_eval["ganador"]
        mejora = (
            mejor_actual["mape_cuota_pct"]
            - nuevo["mape_cuota_pct"]
        )

        acepta = (
            mejora >= MEJORA_MINIMA_MAPE_PUNTOS
            and nuevo["p90_error_abs_pct"]
            <= mejor_actual["p90_error_abs_pct"]
            + TOLERANCIA_P90_PUNTOS
        )

        trazas.append(
            {
                "afp": afp,
                "paso": paso,
                "accion": "AGREGAR",
                "factor": cand["factor"],
                "lag": cand["lag"],
                "max_corr_con_seleccionados": mejor_eval["max_corr"],
                "mape_antes_pct": mejor_actual["mape_cuota_pct"],
                "mape_despues_pct": nuevo["mape_cuota_pct"],
                "mejora_mape_puntos": mejora,
                "p90_despues_pct": nuevo["p90_error_abs_pct"],
                "familia": nuevo["familia"],
                "alpha": nuevo["alpha"],
                "half_life": nuevo["half_life"],
                "aceptado": acepta,
            }
        )

        if not acepta:
            break

        seleccionados.append(cand)
        mejor_actual = nuevo
        disponibles = [
            x for x in disponibles
            if not (
                x["factor"] == cand["factor"]
                and int(x["lag"]) == int(cand["lag"])
            )
        ]

    return seleccionados, mejor_actual, pd.DataFrame(trazas)


def backward_pruning(
    panel: pd.DataFrame,
    specs: list[dict[str, Any]],
    baseline: list[dict[str, Any]],
    fin_train: pd.Timestamp,
    fin_valid: pd.Timestamp,
    afp: str,
) -> tuple[list[dict[str, Any]], dict[str, Any], pd.DataFrame]:
    actuales = [dict(x) for x in specs]
    actual, _, _ = evaluar_configuracion(
        panel, actuales, fin_train, fin_valid
    )
    filas = []

    cambio = True
    paso = 0

    while cambio and len(actuales) > 1:
        cambio = False
        paso += 1
        opciones = []

        for idx, spec in enumerate(actuales):
            prueba = actuales[:idx] + actuales[idx + 1 :]
            ganador, _, _ = evaluar_configuracion(
                panel,
                prueba,
                fin_train,
                fin_valid,
            )
            opciones.append((idx, spec, ganador))

        idx, spec, ganador = min(
            opciones,
            key=lambda z: (
                z[2]["mape_cuota_pct"],
                z[2]["p90_error_abs_pct"],
            ),
        )

        mejora = actual["mape_cuota_pct"] - ganador["mape_cuota_pct"]
        equivalente_mas_simple = (
            ganador["mape_cuota_pct"]
            <= actual["mape_cuota_pct"] + 0.001
            and ganador["p90_error_abs_pct"]
            <= actual["p90_error_abs_pct"] + 0.02
        )

        eliminar = mejora > 0 or equivalente_mas_simple

        filas.append(
            {
                "afp": afp,
                "paso_backward": paso,
                "factor_evaluado": spec["factor"],
                "lag": spec["lag"],
                "mape_antes_pct": actual["mape_cuota_pct"],
                "mape_sin_factor_pct": ganador["mape_cuota_pct"],
                "diferencia_mape_puntos": mejora,
                "p90_sin_factor_pct": ganador["p90_error_abs_pct"],
                "eliminado": eliminar,
            }
        )

        if eliminar:
            actuales.pop(idx)
            actual = ganador
            cambio = True

    return actuales, actual, pd.DataFrame(filas)


def evaluar_en_prueba(
    panel: pd.DataFrame,
    specs: list[dict[str, Any]],
    configuracion: dict[str, Any],
    fin_valid: pd.Timestamp,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame, ModeloLineal]:
    pf, columnas = materializar_features(panel, specs)
    train_valid = pf[pf["fecha_cuota"].le(fin_valid)]
    test = pf[pf["fecha_cuota"].gt(fin_valid)]

    modelo = ajustar_modelo(
        train_valid,
        train_valid["retorno_cuota"],
        columnas,
        str(configuracion["familia"]),
        float(configuracion["alpha"]),
        (
            int(configuracion["half_life"])
            if pd.notna(configuracion["half_life"])
            else None
        ),
    )

    pred_todo = predecir_panel(pf, modelo)
    pred_test = pred_todo[pred_todo["fecha_cuota"].gt(fin_valid)]
    sim = simular_publicacion(
        pred_todo,
        pd.Timestamp(test["fecha_cuota"].min()),
        pd.Timestamp(test["fecha_cuota"].max()),
    )

    met = {
        **metricas_diarias(pred_test),
        **metricas_cuota(sim),
    }

    return met, pred_test, sim, modelo


def diebold_mariano(
    perdida_modelo: np.ndarray,
    perdida_ref: np.ndarray,
    max_lag: int = 5,
) -> dict[str, float]:
    m = np.asarray(perdida_modelo, dtype=float)
    r = np.asarray(perdida_ref, dtype=float)
    mascara = np.isfinite(m) & np.isfinite(r)
    d = m[mascara] - r[mascara]
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


def coeficientes_modelo(
    modelo: ModeloLineal,
    specs: list[dict[str, Any]],
    afp: str,
    tipo: str,
) -> pd.DataFrame:
    filas = []
    for spec, columna, coef in zip(
        specs,
        modelo.columnas,
        modelo.ridge.coef_,
    ):
        filas.append(
            {
                "afp": afp,
                "tipo_modelo": tipo,
                "factor": spec["factor"],
                "lag": spec["lag"],
                "columna": columna,
                "coeficiente_estandarizado": float(coef),
                "abs_coeficiente": abs(float(coef)),
            }
        )
    return pd.DataFrame(filas).sort_values(
        "abs_coeficiente", ascending=False
    )


def guardar_figura(ruta: Path) -> None:
    plt.tight_layout()
    plt.savefig(ruta, dpi=160, bbox_inches="tight")
    plt.close()


def main() -> None:
    raiz = Path(__file__).resolve().parents[1]
    processed = raiz / "data" / "processed"
    graficos = processed / "graficos_modelo70"
    graficos.mkdir(parents=True, exist_ok=True)

    fin_train, fin_valid = cargar_division(processed)
    base, factores, screening = cargar_datos(processed)
    catalogo = cargar_catalogo(processed)

    canastas = []
    trazas_forward = []
    trazas_backward = []
    metricas_validacion = []
    metricas_prueba = []
    simulaciones = []
    dm_filas = []
    coeficientes = []

    for afp in AFPS:
        print(f"\nSeleccionando canasta ampliada para {afp}...")

        panel = preparar_panel_afp(base, factores, afp)
        baseline = [dict(x) for x in BASELINE[afp]]

        for spec in baseline:
            if spec["factor"] not in panel.columns:
                raise KeyError(
                    f"Falta el factor base {spec['factor']} para {afp}"
                )

        pool = construir_pool(screening, afp, baseline)

        seleccion_forward, cfg_forward, traza_f = forward_selection(
            panel,
            baseline,
            pool,
            fin_train,
            fin_valid,
            afp,
        )
        trazas_forward.append(traza_f)

        seleccion_final, cfg_final, traza_b = backward_pruning(
            panel,
            seleccion_forward,
            baseline,
            fin_train,
            fin_valid,
            afp,
        )
        trazas_backward.append(traza_b)

        # Recalcular métricas de validación definitivas.
        cfg_base, _, sim_val_base = evaluar_configuracion(
            panel,
            baseline,
            fin_train,
            fin_valid,
        )
        cfg_expandida, _, sim_val_expandida = evaluar_configuracion(
            panel,
            seleccion_final,
            fin_train,
            fin_valid,
        )

        metricas_validacion.extend(
            [
                {
                    "afp": afp,
                    "tipo_modelo": "BASELINE",
                    "n_factores": len(baseline),
                    **cfg_base,
                },
                {
                    "afp": afp,
                    "tipo_modelo": "EXPANDIDO",
                    "n_factores": len(seleccion_final),
                    **cfg_expandida,
                },
            ]
        )

        met_base, _, sim_test_base, modelo_base = evaluar_en_prueba(
            panel,
            baseline,
            cfg_base,
            fin_valid,
        )
        met_exp, _, sim_test_exp, modelo_exp = evaluar_en_prueba(
            panel,
            seleccion_final,
            cfg_expandida,
            fin_valid,
        )

        metricas_prueba.extend(
            [
                {
                    "afp": afp,
                    "tipo_modelo": "BASELINE",
                    "n_factores": len(baseline),
                    "familia": cfg_base["familia"],
                    "alpha": cfg_base["alpha"],
                    "half_life": cfg_base["half_life"],
                    **met_base,
                },
                {
                    "afp": afp,
                    "tipo_modelo": "EXPANDIDO",
                    "n_factores": len(seleccion_final),
                    "familia": cfg_expandida["familia"],
                    "alpha": cfg_expandida["alpha"],
                    "half_life": cfg_expandida["half_life"],
                    **met_exp,
                },
            ]
        )

        sim_test_base["afp"] = afp
        sim_test_base["tipo_modelo"] = "BASELINE"
        sim_test_exp["afp"] = afp
        sim_test_exp["tipo_modelo"] = "EXPANDIDO"
        simulaciones.extend([sim_test_base, sim_test_exp])

        unido = sim_test_exp[
            ["fecha_hoy_simulada", "error_abs_pct"]
        ].rename(
            columns={"error_abs_pct": "perdida_expandido"}
        ).merge(
            sim_test_base[
                ["fecha_hoy_simulada", "error_abs_pct"]
            ].rename(
                columns={"error_abs_pct": "perdida_baseline"}
            ),
            on="fecha_hoy_simulada",
            how="inner",
        )

        dm = diebold_mariano(
            unido["perdida_expandido"].to_numpy(float),
            unido["perdida_baseline"].to_numpy(float),
            max_lag=5,
        )
        dm_filas.append(
            {
                "afp": afp,
                "modelo": "EXPANDIDO",
                "referencia": "BASELINE",
                **dm,
                "supera_baseline_con_evidencia": (
                    pd.notna(dm["diferencia_media_perdida"])
                    and pd.notna(dm["dm_pvalor"])
                    and dm["diferencia_media_perdida"] < 0
                    and dm["dm_pvalor"] < 0.05
                ),
            }
        )

        coeficientes.extend(
            [
                coeficientes_modelo(
                    modelo_base,
                    baseline,
                    afp,
                    "BASELINE",
                ),
                coeficientes_modelo(
                    modelo_exp,
                    seleccion_final,
                    afp,
                    "EXPANDIDO",
                ),
            ]
        )

        for orden, spec in enumerate(seleccion_final, start=1):
            fila_screen = screening[
                screening["afp"].astype(str).eq(afp)
                & screening["factor"].astype(str).eq(spec["factor"])
                & pd.to_numeric(
                    screening["mejor_lag_train"],
                    errors="coerce",
                ).eq(int(spec["lag"]))
            ]

            canastas.append(
                {
                    "afp": afp,
                    "orden": orden,
                    "factor": spec["factor"],
                    "lag": int(spec["lag"]),
                    "es_factor_baseline": any(
                        x["factor"] == spec["factor"]
                        and int(x["lag"]) == int(spec["lag"])
                        for x in baseline
                    ),
                    "spearman_train": (
                        float(fila_screen["spearman_train"].iloc[0])
                        if not fila_screen.empty
                        else np.nan
                    ),
                    "pearson_train": (
                        float(fila_screen["pearson_train"].iloc[0])
                        if not fila_screen.empty
                        else np.nan
                    ),
                    "mutual_information_train": (
                        float(
                            fila_screen[
                                "mutual_information_train"
                            ].iloc[0]
                        )
                        if not fila_screen.empty
                        else np.nan
                    ),
                    "familia_modelo_final": cfg_expandida["familia"],
                    "alpha_final": cfg_expandida["alpha"],
                    "half_life_final": cfg_expandida["half_life"],
                }
            )

        # Gráfico cuota
        plt.figure(figsize=(12, 5))
        plt.plot(
            sim_test_exp["fecha_hoy_simulada"],
            sim_test_exp["cuota_real_hoy"],
            label="Cuota SBS",
        )
        plt.plot(
            sim_test_base["fecha_hoy_simulada"],
            sim_test_base["cuota_estimada_hoy"],
            label="Baseline",
        )
        plt.plot(
            sim_test_exp["fecha_hoy_simulada"],
            sim_test_exp["cuota_estimada_hoy"],
            label="Expandido",
        )
        plt.ylabel("Valor cuota")
        plt.title(f"Canasta base vs ampliada — {afp}")
        plt.legend()
        guardar_figura(
            graficos / f"01_cuota_{afp.lower()}.png"
        )

    canasta_df = pd.DataFrame(canastas)

    if not catalogo.empty:
        canasta_df = canasta_df.merge(
            catalogo[
                [
                    "factor",
                    "ticker",
                    "nombre",
                    "categoria",
                    "transformacion",
                    "moneda_modelo",
                ]
            ].drop_duplicates("factor"),
            on="factor",
            how="left",
        )

    forward_df = pd.concat(
        trazas_forward,
        ignore_index=True,
    )
    backward_df = pd.concat(
        [x for x in trazas_backward if not x.empty],
        ignore_index=True,
    ) if any(not x.empty for x in trazas_backward) else pd.DataFrame()

    val_df = pd.DataFrame(metricas_validacion)
    test_df = pd.DataFrame(metricas_prueba)
    sim_df = pd.concat(simulaciones, ignore_index=True)
    dm_df = pd.DataFrame(dm_filas)
    coef_df = pd.concat(coeficientes, ignore_index=True)

    rutas = {
        "canasta": processed / "ca0001_modelo70_canasta_seleccionada.csv",
        "forward": processed / "ca0001_modelo70_trazabilidad_forward.csv",
        "backward": processed / "ca0001_modelo70_trazabilidad_backward.csv",
        "validacion": processed / "ca0001_modelo70_metricas_validacion.csv",
        "prueba": processed / "ca0001_modelo70_metricas_prueba.csv",
        "simulaciones": processed / "ca0001_modelo70_simulacion_publicacion_5d.csv",
        "dm": processed / "ca0001_modelo70_diebold_mariano.csv",
        "coeficientes": processed / "ca0001_modelo70_coeficientes.csv",
        "resumen": processed / "ca0001_modelo70_resumen.json",
    }

    canasta_df.to_csv(
        rutas["canasta"], index=False, encoding="utf-8-sig"
    )
    forward_df.to_csv(
        rutas["forward"], index=False, encoding="utf-8-sig"
    )
    backward_df.to_csv(
        rutas["backward"], index=False, encoding="utf-8-sig"
    )
    val_df.to_csv(
        rutas["validacion"], index=False, encoding="utf-8-sig"
    )
    test_df.to_csv(
        rutas["prueba"], index=False, encoding="utf-8-sig"
    )
    sim_df.to_csv(
        rutas["simulaciones"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    dm_df.to_csv(
        rutas["dm"], index=False, encoding="utf-8-sig"
    )
    coef_df.to_csv(
        rutas["coeficientes"], index=False, encoding="utf-8-sig"
    )

    resumen = {
        "version": "modelo70_seleccion_incremental_factores",
        "fin_entrenamiento": str(fin_train.date()),
        "fin_validacion": str(fin_valid.date()),
        "criterio": (
            "Forward selection con validación operativa de 5 días, "
            "control de redundancia y poda backward."
        ),
        "canasta_seleccionada": canasta_df.to_dict(orient="records"),
        "metricas_prueba": test_df.to_dict(orient="records"),
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

    print("\nMÓDULO 70 — SELECCIÓN INCREMENTAL DE LA CANASTA AMPLIADA")
    print("=" * 165)
    print(
        "La selección usa entrenamiento y validación. "
        "La prueba solo audita el resultado."
    )

    print("\nCANASTA FINAL POR AFP")
    print("-" * 165)
    columnas_canasta = [
        "afp",
        "orden",
        "factor",
        "ticker",
        "nombre",
        "categoria",
        "lag",
        "es_factor_baseline",
        "spearman_train",
        "familia_modelo_final",
        "alpha_final",
        "half_life_final",
    ]
    columnas_canasta = [
        c for c in columnas_canasta if c in canasta_df.columns
    ]
    print(canasta_df[columnas_canasta].to_string(index=False))

    print("\nMÉTRICAS DE VALIDACIÓN")
    print("-" * 165)
    print(
        val_df[
            [
                "afp",
                "tipo_modelo",
                "n_factores",
                "familia",
                "alpha",
                "half_life",
                "mape_cuota_pct",
                "p90_error_abs_pct",
                "r2_diario",
                "direccion_diaria_pct",
            ]
        ].to_string(index=False)
    )

    print("\nMÉTRICAS DE PRUEBA")
    print("-" * 165)
    print(
        test_df[
            [
                "afp",
                "tipo_modelo",
                "n_factores",
                "familia",
                "alpha",
                "half_life",
                "mae_diario",
                "rmse_diario",
                "r2_diario",
                "direccion_diaria_pct",
                "mape_cuota_pct",
                "mediana_error_abs_pct",
                "p90_error_abs_pct",
                "error_maximo_abs_pct",
                "sesgo_cuota_pct",
                "direccion_acumulada_pct",
            ]
        ].to_string(index=False)
    )

    print("\nDIEBOLD-MARIANO: EXPANDIDO VS BASELINE")
    print("-" * 165)
    print(dm_df.to_string(index=False))

    print("\nTRAZABILIDAD FORWARD")
    print("-" * 165)
    print(
        forward_df[
            [
                "afp",
                "paso",
                "accion",
                "factor",
                "lag",
                "max_corr_con_seleccionados",
                "mape_antes_pct",
                "mape_despues_pct",
                "mejora_mape_puntos",
                "p90_despues_pct",
                "aceptado",
            ]
        ].to_string(index=False)
    )

    print("\nARCHIVOS CREADOS")
    print("-" * 165)
    for ruta in rutas.values():
        print(f" - {ruta.resolve()}")
    print(f" - {graficos.resolve()}")

    print(
        "\nLECTURA:\n"
        "- El factor debe mejorar el MAPE en validación y no deteriorar "
        "materialmente el P90.\n"
        "- La poda backward busca la canasta mínima; puede retirar factores "
        "antiguos si ya no aportan valor incremental.\n"
        "- La prueba revela si la mejora se mantiene fuera del periodo usado "
        "para seleccionar.\n"
        "- El siguiente módulo abrirá únicamente los ETF/índices ganadores "
        "para estudiar sus acciones y componentes."
    )


if __name__ == "__main__":
    main()
