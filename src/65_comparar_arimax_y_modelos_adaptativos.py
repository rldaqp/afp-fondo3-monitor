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

from statsmodels.stats.diagnostic import acorr_ljungbox, het_arch
from statsmodels.tsa.statespace.sarimax import SARIMAX


warnings.filterwarnings("ignore")

AFPS = ["Habitat", "Integra", "Prima", "Profuturo"]
RETRASO_PUBLICACION_DIAS = 5

ARIMAX_ORDERS = [(0, 0, 0), (1, 0, 0), (2, 0, 0), (1, 0, 1)]
ROLLING_WINDOWS = [120, 250, 500, 1000]
EW_HALF_LIVES = [60, 120, 250, 500]
RIDGE_ALPHAS = [0.001, 0.1, 10.0]


@dataclass
class Candidato:
    familia: str
    nombre: str
    parametros: dict[str, Any]


def leer_csv_flexible(ruta: Path) -> pd.DataFrame:
    intentos = [
        {"sep": None, "engine": "python", "encoding": "utf-8-sig"},
        {"sep": None, "engine": "python", "encoding": "latin-1"},
        {"sep": ",", "encoding": "utf-8-sig"},
        {"sep": ";", "encoding": "utf-8-sig"},
        {"sep": ";", "encoding": "latin-1"},
    ]
    ultimo_error: Exception | None = None
    for args in intentos:
        try:
            return pd.read_csv(ruta, **args)
        except Exception as exc:
            ultimo_error = exc
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


def preparar_afp(
    base: pd.DataFrame,
    canasta: pd.DataFrame,
    afp: str,
) -> tuple[pd.DataFrame, list[str]]:
    factores = (
        canasta[canasta["afp"].eq(afp)]
        .sort_values("orden")["factor"]
        .astype(str)
        .tolist()
    )
    columnas = [f"{f}__retorno_alineado" for f in factores]

    faltantes = [c for c in columnas if c not in base.columns]
    if faltantes:
        raise ValueError(f"Faltan columnas para {afp}: {faltantes}")

    g = base[base["afp"].eq(afp)][
        ["fecha_cuota", "cuota_sbs", "retorno_cuota"] + columnas
    ].copy()
    g = g.sort_values("fecha_cuota").reset_index(drop=True)

    for c in columnas:
        g[c] = pd.to_numeric(g[c], errors="coerce").fillna(0.0)

    return g, columnas


def segmento(
    fecha: pd.Timestamp,
    fin_train: pd.Timestamp,
    fin_valid: pd.Timestamp,
) -> str:
    if fecha <= fin_train:
        return "entrenamiento"
    if fecha <= fin_valid:
        return "validacion"
    return "prueba"


def metricas_diarias(y: np.ndarray, p: np.ndarray) -> dict[str, float]:
    mascara = np.isfinite(y) & np.isfinite(p)
    y = np.asarray(y)[mascara]
    p = np.asarray(p)[mascara]

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
            "direccion_diaria_pct": np.nan,
        }

    residuo = y - p
    desviacion = float(np.std(residuo, ddof=1)) if len(residuo) > 1 else np.nan
    varianza = float(np.var(residuo, ddof=1)) if len(residuo) > 1 else np.nan

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
        "mae": float(mean_absolute_error(y, p)),
        "rmse": float(mean_squared_error(y, p) ** 0.5),
        "r2": float(r2_score(y, p)) if len(y) > 1 else np.nan,
        "sesgo": float(np.mean(p - y)),
        "desviacion_residual": desviacion,
        "varianza_residual": varianza,
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
    mascara = np.abs(pred) > 1e-15

    direccion = (
        float((np.sign(pred[mascara]) == np.sign(real[mascara])).mean() * 100.0)
        if mascara.any()
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


def diagnosticos_residuales(residuos: pd.Series) -> dict[str, float]:
    r = residuos.dropna()
    salida = {
        "n_residuos": int(len(r)),
        "ljungbox_p_lag10": np.nan,
        "arch_lm_p_lag10": np.nan,
        "asimetria_residual": np.nan,
        "curtosis_exceso_residual": np.nan,
    }

    if len(r) >= 40:
        lb = acorr_ljungbox(r, lags=[10], return_df=True)
        salida["ljungbox_p_lag10"] = float(lb.loc[10, "lb_pvalue"])

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


def ajustar_ridge(
    historia: pd.DataFrame,
    columnas: list[str],
    alpha: float,
    pesos: np.ndarray | None = None,
) -> tuple[StandardScaler, Ridge]:
    datos = historia.dropna(subset=["retorno_cuota"]).copy()
    X = datos[columnas].to_numpy(float)
    y = datos["retorno_cuota"].to_numpy(float)

    scaler = StandardScaler()
    Xs = scaler.fit_transform(X)

    modelo = Ridge(alpha=alpha)
    modelo.fit(Xs, y, sample_weight=pesos)
    return scaler, modelo


def predecir_ridge(
    scaler: StandardScaler,
    modelo: Ridge,
    X: pd.DataFrame,
) -> np.ndarray:
    return modelo.predict(scaler.transform(X.to_numpy(float)))


def pesos_half_life(n: int, half_life: int) -> np.ndarray:
    edades = np.arange(n - 1, -1, -1, dtype=float)
    return np.power(0.5, edades / float(half_life))


def walk_forward_ridge(
    g: pd.DataFrame,
    columnas: list[str],
    indices_objetivo: list[int],
    ventana: int | None,
    half_life: int | None,
    alpha: float,
) -> pd.DataFrame:
    filas = []

    for i in indices_objetivo:
        historia = g.loc[: i - 1].dropna(subset=["retorno_cuota"]).copy()
        if ventana is not None:
            historia = historia.tail(ventana)

        if len(historia) < 60:
            continue

        pesos = (
            pesos_half_life(len(historia), half_life)
            if half_life is not None
            else None
        )
        scaler, modelo = ajustar_ridge(historia, columnas, alpha, pesos)
        pred = float(predecir_ridge(scaler, modelo, g.loc[[i], columnas])[0])

        filas.append(
            {
                "fecha_cuota": g.loc[i, "fecha_cuota"],
                "cuota_sbs": g.loc[i, "cuota_sbs"],
                "retorno_cuota": g.loc[i, "retorno_cuota"],
                "retorno_estimado": pred,
            }
        )

    return pd.DataFrame(filas)


def simular_publicacion_ridge(
    g: pd.DataFrame,
    columnas: list[str],
    indices_objetivo: list[int],
    ventana: int | None,
    half_life: int | None,
    alpha: float,
) -> pd.DataFrame:
    filas = []

    for i in indices_objetivo:
        fecha_obj = pd.Timestamp(g.loc[i, "fecha_cuota"])
        corte = fecha_obj - pd.Timedelta(days=RETRASO_PUBLICACION_DIAS)
        candidatos = g.index[g["fecha_cuota"].le(corte)].tolist()

        if not candidatos:
            continue

        a = candidatos[-1]
        if a >= i:
            continue

        historia = g.loc[:a].dropna(subset=["retorno_cuota"]).copy()
        if ventana is not None:
            historia = historia.tail(ventana)

        if len(historia) < 60:
            continue

        pesos = (
            pesos_half_life(len(historia), half_life)
            if half_life is not None
            else None
        )
        scaler, modelo = ajustar_ridge(historia, columnas, alpha, pesos)
        pred = predecir_ridge(scaler, modelo, g.loc[a + 1 : i, columnas])
        retorno_estimado = float(np.prod(1.0 + pred) - 1.0)

        cuota_ancla = float(g.loc[a, "cuota_sbs"])
        cuota_real = float(g.loc[i, "cuota_sbs"])
        cuota_estimada = float(cuota_ancla * (1.0 + retorno_estimado))
        retorno_real = float(cuota_real / cuota_ancla - 1.0)
        error_pct = float(cuota_estimada / cuota_real - 1.0)

        filas.append(
            {
                "fecha_hoy_simulada": fecha_obj,
                "fecha_ultima_cuota_visible": g.loc[a, "fecha_cuota"],
                "cuotas_ocultas_estimadas": int(i - a),
                "cuota_ultima_visible": cuota_ancla,
                "cuota_estimada_hoy": cuota_estimada,
                "cuota_real_hoy": cuota_real,
                "error_pct": error_pct,
                "error_abs_pct": abs(error_pct),
                "retorno_estimado_acumulado": retorno_estimado,
                "retorno_real_acumulado": retorno_real,
            }
        )

    return pd.DataFrame(filas)


def ajustar_arimax(
    g_hist: pd.DataFrame,
    columnas: list[str],
    order: tuple[int, int, int],
):
    datos = g_hist.dropna(subset=["retorno_cuota"]).copy()

    modelo = SARIMAX(
        endog=datos["retorno_cuota"].to_numpy(float),
        exog=datos[columnas].to_numpy(float),
        order=order,
        trend="c",
        enforce_stationarity=False,
        enforce_invertibility=False,
    )
    return modelo.fit(disp=False, maxiter=250)


def walk_forward_arimax(
    g: pd.DataFrame,
    columnas: list[str],
    indices_objetivo: list[int],
    order: tuple[int, int, int],
) -> pd.DataFrame:
    if not indices_objetivo:
        return pd.DataFrame()

    primero = indices_objetivo[0]
    historial = g.loc[: primero - 1].copy()
    resultado = ajustar_arimax(historial, columnas, order)
    ultimo_estado = primero - 1
    filas = []

    for i in indices_objetivo:
        if i - 1 > ultimo_estado:
            nuevas = g.loc[ultimo_estado + 1 : i - 1]
            resultado = resultado.append(
                nuevas["retorno_cuota"].to_numpy(float),
                exog=nuevas[columnas].to_numpy(float),
                refit=False,
            )
            ultimo_estado = i - 1

        pred = resultado.get_forecast(
            steps=1,
            exog=g.loc[[i], columnas].to_numpy(float),
        ).predicted_mean
        valor = float(np.asarray(pred)[0])

        filas.append(
            {
                "fecha_cuota": g.loc[i, "fecha_cuota"],
                "cuota_sbs": g.loc[i, "cuota_sbs"],
                "retorno_cuota": g.loc[i, "retorno_cuota"],
                "retorno_estimado": valor,
            }
        )

    return pd.DataFrame(filas)


def simular_publicacion_arimax(
    g: pd.DataFrame,
    columnas: list[str],
    indices_objetivo: list[int],
    order: tuple[int, int, int],
) -> pd.DataFrame:
    if not indices_objetivo:
        return pd.DataFrame()

    primer_obj = indices_objetivo[0]
    fecha_primer_obj = pd.Timestamp(g.loc[primer_obj, "fecha_cuota"])
    primer_corte = fecha_primer_obj - pd.Timedelta(days=RETRASO_PUBLICACION_DIAS)
    anclas_iniciales = g.index[g["fecha_cuota"].le(primer_corte)].tolist()

    if not anclas_iniciales:
        return pd.DataFrame()

    primer_ancla = anclas_iniciales[-1]
    resultado = ajustar_arimax(g.loc[:primer_ancla], columnas, order)
    ultimo_estado = primer_ancla
    filas = []

    for i in indices_objetivo:
        fecha_obj = pd.Timestamp(g.loc[i, "fecha_cuota"])
        corte = fecha_obj - pd.Timedelta(days=RETRASO_PUBLICACION_DIAS)
        candidatos = g.index[g["fecha_cuota"].le(corte)].tolist()

        if not candidatos:
            continue

        a = candidatos[-1]
        if a >= i:
            continue

        if a > ultimo_estado:
            nuevas = g.loc[ultimo_estado + 1 : a]
            resultado = resultado.append(
                nuevas["retorno_cuota"].to_numpy(float),
                exog=nuevas[columnas].to_numpy(float),
                refit=False,
            )
            ultimo_estado = a

        exog_futuro = g.loc[a + 1 : i, columnas].to_numpy(float)
        pred = resultado.get_forecast(
            steps=len(exog_futuro),
            exog=exog_futuro,
        ).predicted_mean
        pred = np.asarray(pred, dtype=float)

        retorno_estimado = float(np.prod(1.0 + pred) - 1.0)
        cuota_ancla = float(g.loc[a, "cuota_sbs"])
        cuota_real = float(g.loc[i, "cuota_sbs"])
        cuota_estimada = float(cuota_ancla * (1.0 + retorno_estimado))
        retorno_real = float(cuota_real / cuota_ancla - 1.0)
        error_pct = float(cuota_estimada / cuota_real - 1.0)

        filas.append(
            {
                "fecha_hoy_simulada": fecha_obj,
                "fecha_ultima_cuota_visible": g.loc[a, "fecha_cuota"],
                "cuotas_ocultas_estimadas": int(i - a),
                "cuota_ultima_visible": cuota_ancla,
                "cuota_estimada_hoy": cuota_estimada,
                "cuota_real_hoy": cuota_real,
                "error_pct": error_pct,
                "error_abs_pct": abs(error_pct),
                "retorno_estimado_acumulado": retorno_estimado,
                "retorno_real_acumulado": retorno_real,
            }
        )

    return pd.DataFrame(filas)


def lista_candidatos() -> list[Candidato]:
    candidatos: list[Candidato] = []

    for order in ARIMAX_ORDERS:
        candidatos.append(
            Candidato(
                familia="ARIMAX",
                nombre=f"ARIMAX_{order[0]}{order[1]}{order[2]}",
                parametros={"order": list(order)},
            )
        )

    for ventana in ROLLING_WINDOWS:
        for alpha in RIDGE_ALPHAS:
            candidatos.append(
                Candidato(
                    familia="ROLLING_RIDGE",
                    nombre=f"ROLLING_RIDGE_W{ventana}_A{alpha:g}",
                    parametros={"ventana": ventana, "alpha": alpha},
                )
            )

    for half_life in EW_HALF_LIVES:
        for alpha in RIDGE_ALPHAS:
            candidatos.append(
                Candidato(
                    familia="EW_RIDGE",
                    nombre=f"EW_RIDGE_HL{half_life}_A{alpha:g}",
                    parametros={"half_life": half_life, "alpha": alpha},
                )
            )

    return candidatos


def evaluar_candidato(
    candidato: Candidato,
    g: pd.DataFrame,
    columnas: list[str],
    indices: list[int],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if candidato.familia == "ARIMAX":
        order = tuple(candidato.parametros["order"])
        diario = walk_forward_arimax(g, columnas, indices, order)
        operativo = simular_publicacion_arimax(g, columnas, indices, order)
        return diario, operativo

    if candidato.familia == "ROLLING_RIDGE":
        ventana = int(candidato.parametros["ventana"])
        alpha = float(candidato.parametros["alpha"])
        diario = walk_forward_ridge(
            g, columnas, indices, ventana=ventana, half_life=None, alpha=alpha
        )
        operativo = simular_publicacion_ridge(
            g, columnas, indices, ventana=ventana, half_life=None, alpha=alpha
        )
        return diario, operativo

    if candidato.familia == "EW_RIDGE":
        half_life = int(candidato.parametros["half_life"])
        alpha = float(candidato.parametros["alpha"])
        diario = walk_forward_ridge(
            g, columnas, indices, ventana=None, half_life=half_life, alpha=alpha
        )
        operativo = simular_publicacion_ridge(
            g, columnas, indices, ventana=None, half_life=half_life, alpha=alpha
        )
        return diario, operativo

    raise ValueError(f"Familia desconocida: {candidato.familia}")


def diebold_mariano(
    perdida_modelo: np.ndarray,
    perdida_ref: np.ndarray,
    max_lag: int,
) -> dict[str, float]:
    mascara = np.isfinite(perdida_modelo) & np.isfinite(perdida_ref)
    d = np.asarray(perdida_modelo)[mascara] - np.asarray(perdida_ref)[mascara]
    n = len(d)

    if n < 30:
        return {
            "n_dm": n,
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
            "n_dm": n,
            "diferencia_media_perdida": media,
            "dm_estadistico": np.nan,
            "dm_pvalor": np.nan,
        }

    estadistico = media / math.sqrt(var_media)
    pvalor = float(2.0 * (1.0 - stats.norm.cdf(abs(estadistico))))

    return {
        "n_dm": n,
        "diferencia_media_perdida": media,
        "dm_estadistico": float(estadistico),
        "dm_pvalor": pvalor,
    }


def guardar_figura(ruta: Path) -> None:
    plt.tight_layout()
    plt.savefig(ruta, dpi=160, bbox_inches="tight")
    plt.close()


def graficar(
    metricas_diarias: pd.DataFrame,
    metricas_5d: pd.DataFrame,
    predicciones: pd.DataFrame,
    simulaciones: pd.DataFrame,
    seleccion: pd.DataFrame,
    graficos: Path,
) -> None:
    graficos.mkdir(parents=True, exist_ok=True)

    for afp in AFPS:
        test_d = metricas_diarias[
            metricas_diarias["afp"].eq(afp)
            & metricas_diarias["segmento"].eq("prueba")
        ].sort_values("mae")

        if not test_d.empty:
            plt.figure(figsize=(11, 5))
            plt.bar(test_d["modelo"], test_d["r2"] * 100.0)
            plt.xticks(rotation=30, ha="right")
            plt.ylabel("R² fuera de muestra (%)")
            plt.title(f"R² de modelos dinámicos y adaptativos — {afp}")
            guardar_figura(graficos / f"01_r2_test_{afp.lower()}.png")

        test_5 = metricas_5d[
            metricas_5d["afp"].eq(afp)
            & metricas_5d["segmento"].eq("prueba")
        ].sort_values("mape_cuota_5d_pct")

        if not test_5.empty:
            x = np.arange(len(test_5))
            ancho = 0.36
            plt.figure(figsize=(11, 5))
            plt.bar(
                x - ancho / 2,
                test_5["mape_cuota_5d_pct"],
                width=ancho,
                label="MAPE",
            )
            plt.bar(
                x + ancho / 2,
                test_5["p90_error_abs_5d_pct"],
                width=ancho,
                label="P90",
            )
            plt.xticks(x, test_5["modelo"], rotation=30, ha="right")
            plt.ylabel("Porcentaje")
            plt.title(f"MAPE y P90 operativos — {afp}")
            plt.legend()
            guardar_figura(graficos / f"02_mape_p90_test_{afp.lower()}.png")

        sel = seleccion[
            seleccion["afp"].eq(afp)
            & seleccion["seleccionado_familia"].eq(True)
        ]
        for _, fila in sel.iterrows():
            nombre = fila["modelo"]

            pred = predicciones[
                predicciones["afp"].eq(afp)
                & predicciones["modelo"].eq(nombre)
                & predicciones["segmento"].eq("prueba")
            ].sort_values("fecha_cuota")

            if not pred.empty:
                plt.figure(figsize=(12, 5))
                plt.plot(pred["fecha_cuota"], pred["retorno_cuota"] * 100.0, label="SBS")
                plt.plot(
                    pred["fecha_cuota"],
                    pred["retorno_estimado"] * 100.0,
                    label=nombre,
                )
                plt.axhline(0, linewidth=1)
                plt.ylabel("Retorno diario (%)")
                plt.title(f"Retorno real vs estimado — {afp} — {nombre}")
                plt.legend()
                guardar_figura(
                    graficos / f"03_retorno_{afp.lower()}_{nombre.lower()}.png"
                )

            sim = simulaciones[
                simulaciones["afp"].eq(afp)
                & simulaciones["modelo"].eq(nombre)
                & simulaciones["segmento"].eq("prueba")
            ].sort_values("fecha_hoy_simulada")

            if not sim.empty:
                plt.figure(figsize=(12, 5))
                plt.plot(sim["fecha_hoy_simulada"], sim["cuota_real_hoy"], label="Cuota SBS")
                plt.plot(
                    sim["fecha_hoy_simulada"],
                    sim["cuota_estimada_hoy"],
                    label=nombre,
                )
                plt.ylabel("Valor cuota")
                plt.title(f"Cuota SBS vs estimada — {afp} — {nombre}")
                plt.legend()
                guardar_figura(
                    graficos / f"04_cuota_{afp.lower()}_{nombre.lower()}.png"
                )


def main() -> None:
    raiz = Path(__file__).resolve().parents[1]
    processed = raiz / "data" / "processed"
    graficos = processed / "graficos_modelo65"

    fin_train, fin_valid = cargar_division(processed)
    canasta = cargar_canasta(processed)
    base = cargar_base(processed)
    candidatos = lista_candidatos()

    seleccion_filas = []
    metricas_diarias_filas = []
    metricas_5d_filas = []
    predicciones_todas = []
    simulaciones_todas = []
    diagnosticos_filas = []

    for afp in AFPS:
        print(f"\nSeleccionando modelos dinámicos para {afp}...")
        g, columnas = preparar_afp(base, canasta, afp)

        idx_valid = g.index[
            g["fecha_cuota"].gt(fin_train)
            & g["fecha_cuota"].le(fin_valid)
        ].tolist()
        idx_test = g.index[g["fecha_cuota"].gt(fin_valid)].tolist()

        evaluacion_validacion = []

        for candidato in candidatos:
            try:
                diario_v, oper_v = evaluar_candidato(candidato, g, columnas, idx_valid)
                md = metricas_diarias(
                    diario_v["retorno_cuota"].to_numpy(float),
                    diario_v["retorno_estimado"].to_numpy(float),
                )
                mo = metricas_publicacion(oper_v)

                evaluacion_validacion.append(
                    {
                        "afp": afp,
                        "familia": candidato.familia,
                        "modelo": candidato.nombre,
                        "parametros": json.dumps(candidato.parametros, sort_keys=True),
                        "val_mae": md["mae"],
                        "val_rmse": md["rmse"],
                        "val_r2": md["r2"],
                        "val_mape_5d_pct": mo["mape_cuota_5d_pct"],
                        "val_p90_5d_pct": mo["p90_error_abs_5d_pct"],
                        "estado": "CORRECTO",
                    }
                )
            except Exception as exc:
                evaluacion_validacion.append(
                    {
                        "afp": afp,
                        "familia": candidato.familia,
                        "modelo": candidato.nombre,
                        "parametros": json.dumps(candidato.parametros, sort_keys=True),
                        "val_mae": np.nan,
                        "val_rmse": np.nan,
                        "val_r2": np.nan,
                        "val_mape_5d_pct": np.nan,
                        "val_p90_5d_pct": np.nan,
                        "estado": f"ERROR: {exc}",
                    }
                )

        tabla_val = pd.DataFrame(evaluacion_validacion)
        tabla_val["seleccionado_familia"] = False

        ganadores_familia: list[str] = []
        for familia, grupo in tabla_val[
            tabla_val["estado"].eq("CORRECTO")
        ].groupby("familia"):
            grupo = grupo.dropna(subset=["val_mape_5d_pct"]).sort_values(
                ["val_mape_5d_pct", "val_mae", "val_p90_5d_pct"]
            )
            if not grupo.empty:
                ganador = grupo.iloc[0]["modelo"]
                ganadores_familia.append(ganador)
                tabla_val.loc[tabla_val["modelo"].eq(ganador), "seleccionado_familia"] = True

        seleccion_filas.append(tabla_val)

        mapa_candidatos = {c.nombre: c for c in candidatos}

        for nombre in ganadores_familia:
            candidato = mapa_candidatos[nombre]

            for nombre_segmento, indices in [
                ("validacion", idx_valid),
                ("prueba", idx_test),
            ]:
                diario, operativo = evaluar_candidato(candidato, g, columnas, indices)

                diario["afp"] = afp
                diario["modelo"] = nombre
                diario["familia"] = candidato.familia
                diario["segmento"] = nombre_segmento
                predicciones_todas.append(diario)

                operativo["afp"] = afp
                operativo["modelo"] = nombre
                operativo["familia"] = candidato.familia
                operativo["segmento"] = nombre_segmento
                simulaciones_todas.append(operativo)

                md = metricas_diarias(
                    diario["retorno_cuota"].to_numpy(float),
                    diario["retorno_estimado"].to_numpy(float),
                )
                metricas_diarias_filas.append(
                    {
                        "afp": afp,
                        "modelo": nombre,
                        "familia": candidato.familia,
                        "segmento": nombre_segmento,
                        "parametros": json.dumps(candidato.parametros, sort_keys=True),
                        **md,
                    }
                )

                mo = metricas_publicacion(operativo)
                metricas_5d_filas.append(
                    {
                        "afp": afp,
                        "modelo": nombre,
                        "familia": candidato.familia,
                        "segmento": nombre_segmento,
                        "parametros": json.dumps(candidato.parametros, sort_keys=True),
                        **mo,
                    }
                )

                residuos = diario["retorno_cuota"] - diario["retorno_estimado"]
                diagnosticos_filas.append(
                    {
                        "afp": afp,
                        "modelo": nombre,
                        "familia": candidato.familia,
                        "segmento": nombre_segmento,
                        **diagnosticos_residuales(residuos),
                    }
                )

    seleccion_df = pd.concat(seleccion_filas, ignore_index=True)
    metricas_diarias_df = pd.DataFrame(metricas_diarias_filas)
    metricas_5d_df = pd.DataFrame(metricas_5d_filas)
    predicciones_df = pd.concat(predicciones_todas, ignore_index=True)
    simulaciones_df = pd.concat(simulaciones_todas, ignore_index=True)
    diagnosticos_df = pd.DataFrame(diagnosticos_filas)

    # Añadir Ridge del módulo 64 como campeón de referencia
    ruta_md64 = processed / "ca0001_modelo64_metricas_diarias.csv"
    ruta_m564 = processed / "ca0001_modelo64_metricas_publicacion_5d.csv"
    ruta_p64 = processed / "ca0001_modelo64_predicciones_diarias.csv"
    ruta_s64 = processed / "ca0001_modelo64_simulacion_publicacion_5d.csv"

    if all(r.exists() for r in [ruta_md64, ruta_m564, ruta_p64, ruta_s64]):
        md64 = leer_csv_flexible(ruta_md64)
        m564 = leer_csv_flexible(ruta_m564)
        p64 = leer_csv_flexible(ruta_p64)
        s64 = leer_csv_flexible(ruta_s64)

        md64 = md64[
            md64["modelo"].eq("RIDGE")
            & md64["segmento"].isin(["validacion", "prueba"])
        ].copy()
        m564 = m564[
            m564["modelo"].eq("RIDGE")
            & m564["segmento"].isin(["validacion", "prueba"])
        ].copy()
        p64 = p64[
            p64["modelo"].eq("RIDGE")
            & p64["segmento"].isin(["validacion", "prueba"])
        ].copy()
        s64 = s64[
            s64["modelo"].eq("RIDGE")
            & s64["segmento"].isin(["validacion", "prueba"])
        ].copy()

        md64["familia"] = "REFERENCIA"
        m564["familia"] = "REFERENCIA"
        p64["familia"] = "REFERENCIA"
        s64["familia"] = "REFERENCIA"

        columnas_md = [c for c in metricas_diarias_df.columns if c in md64.columns]
        columnas_m5 = [c for c in metricas_5d_df.columns if c in m564.columns]
        columnas_p = [c for c in predicciones_df.columns if c in p64.columns]
        columnas_s = [c for c in simulaciones_df.columns if c in s64.columns]

        metricas_diarias_df = pd.concat(
            [metricas_diarias_df, md64[columnas_md]], ignore_index=True, sort=False
        )
        metricas_5d_df = pd.concat(
            [metricas_5d_df, m564[columnas_m5]], ignore_index=True, sort=False
        )
        predicciones_df = pd.concat(
            [predicciones_df, p64[columnas_p]], ignore_index=True, sort=False
        )
        simulaciones_df = pd.concat(
            [simulaciones_df, s64[columnas_s]], ignore_index=True, sort=False
        )

    # Ranking de prueba y comparación DM frente a Ridge
    ranking = (
        metricas_5d_df[metricas_5d_df["segmento"].eq("prueba")]
        .copy()
        .sort_values(["afp", "mape_cuota_5d_pct", "p90_error_abs_5d_pct"])
    )
    ranking["ranking_mape_prueba"] = ranking.groupby("afp")[
        "mape_cuota_5d_pct"
    ].rank(method="min", ascending=True)

    dm_filas = []
    for afp in AFPS:
        ref = simulaciones_df[
            simulaciones_df["afp"].eq(afp)
            & simulaciones_df["modelo"].eq("RIDGE")
            & simulaciones_df["segmento"].eq("prueba")
        ][["fecha_hoy_simulada", "error_abs_pct"]].rename(
            columns={"error_abs_pct": "perdida_ref"}
        )

        if ref.empty:
            continue

        for modelo in simulaciones_df[
            simulaciones_df["afp"].eq(afp)
            & simulaciones_df["segmento"].eq("prueba")
        ]["modelo"].unique():
            cand = simulaciones_df[
                simulaciones_df["afp"].eq(afp)
                & simulaciones_df["modelo"].eq(modelo)
                & simulaciones_df["segmento"].eq("prueba")
            ][["fecha_hoy_simulada", "error_abs_pct"]].rename(
                columns={"error_abs_pct": "perdida_modelo"}
            )
            unido = cand.merge(ref, on="fecha_hoy_simulada", how="inner")
            dm_filas.append(
                {
                    "afp": afp,
                    "modelo": modelo,
                    "referencia": "RIDGE",
                    **diebold_mariano(
                        unido["perdida_modelo"].to_numpy(float),
                        unido["perdida_ref"].to_numpy(float),
                        max_lag=5,
                    ),
                }
            )

    dm_df = pd.DataFrame(dm_filas)

    graficar(
        metricas_diarias_df,
        metricas_5d_df,
        predicciones_df,
        simulaciones_df,
        seleccion_df,
        graficos,
    )

    rutas = {
        "seleccion": processed / "ca0001_modelo65_seleccion_dinamicos.csv",
        "metricas_diarias": processed / "ca0001_modelo65_metricas_diarias.csv",
        "metricas_5d": processed / "ca0001_modelo65_metricas_publicacion_5d.csv",
        "predicciones": processed / "ca0001_modelo65_predicciones_diarias.csv",
        "simulaciones": processed / "ca0001_modelo65_simulacion_publicacion_5d.csv",
        "diagnosticos": processed / "ca0001_modelo65_diagnosticos_residuales.csv",
        "ranking": processed / "ca0001_modelo65_ranking_prueba.csv",
        "dm": processed / "ca0001_modelo65_diebold_mariano.csv",
        "resumen": processed / "ca0001_modelo65_resumen.json",
    }

    seleccion_df.to_csv(rutas["seleccion"], index=False, encoding="utf-8-sig")
    metricas_diarias_df.to_csv(rutas["metricas_diarias"], index=False, encoding="utf-8-sig")
    metricas_5d_df.to_csv(rutas["metricas_5d"], index=False, encoding="utf-8-sig")
    predicciones_df.to_csv(
        rutas["predicciones"], index=False, encoding="utf-8-sig", date_format="%Y-%m-%d"
    )
    simulaciones_df.to_csv(
        rutas["simulaciones"], index=False, encoding="utf-8-sig", date_format="%Y-%m-%d"
    )
    diagnosticos_df.to_csv(rutas["diagnosticos"], index=False, encoding="utf-8-sig")
    ranking.to_csv(rutas["ranking"], index=False, encoding="utf-8-sig")
    dm_df.to_csv(rutas["dm"], index=False, encoding="utf-8-sig")

    resumen = {
        "version": "modelo65_arimax_y_modelos_adaptativos",
        "fin_entrenamiento": str(fin_train.date()),
        "fin_validacion": str(fin_valid.date()),
        "familias": ["ARIMAX", "ROLLING_RIDGE", "EW_RIDGE"],
        "criterio_seleccion": (
            "Por familia y AFP: menor MAPE operativo en validación; "
            "desempate por MAE diario y P90."
        ),
        "ranking_prueba": ranking.to_dict(orient="records"),
        "graficos_generados": len(list(graficos.glob("*.png"))),
    }
    rutas["resumen"].write_text(
        json.dumps(resumen, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    print("\nMÓDULO 65 — ARIMAX Y MODELOS ADAPTATIVOS")
    print("=" * 150)
    print(
        "Se comparan ARIMAX, Ridge por ventana móvil y Ridge con ponderación "
        "exponencial. La selección se hace con validación."
    )

    print("\nGANADORES POR FAMILIA EN VALIDACIÓN")
    print("-" * 150)
    print(
        seleccion_df[seleccion_df["seleccionado_familia"].eq(True)]
        [
            [
                "afp",
                "familia",
                "modelo",
                "parametros",
                "val_mae",
                "val_r2",
                "val_mape_5d_pct",
                "val_p90_5d_pct",
            ]
        ]
        .sort_values(["afp", "familia"])
        .to_string(index=False)
    )

    print("\nMÉTRICAS DIARIAS — PRUEBA")
    print("-" * 150)
    print(
        metricas_diarias_df[metricas_diarias_df["segmento"].eq("prueba")]
        [
            [
                "afp",
                "modelo",
                "familia",
                "n",
                "mae",
                "rmse",
                "r2",
                "desviacion_residual",
                "varianza_residual",
                "correlacion",
                "direccion_diaria_pct",
            ]
        ]
        .sort_values(["afp", "mae"])
        .to_string(index=False)
    )

    print("\nMÉTRICAS OPERATIVAS DE CUOTA — PRUEBA")
    print("-" * 150)
    print(
        ranking[
            [
                "afp",
                "modelo",
                "familia",
                "mape_cuota_5d_pct",
                "mediana_error_abs_5d_pct",
                "p90_error_abs_5d_pct",
                "error_maximo_abs_5d_pct",
                "sesgo_5d_pct",
                "correlacion_retorno_acumulado",
                "direccion_acumulada_pct",
                "ranking_mape_prueba",
            ]
        ].to_string(index=False)
    )

    print("\nDIEBOLD-MARIANO VS RIDGE — ERROR DE CUOTA")
    print("-" * 150)
    print(
        dm_df[
            [
                "afp",
                "modelo",
                "diferencia_media_perdida",
                "dm_estadistico",
                "dm_pvalor",
            ]
        ]
        .sort_values(["afp", "dm_pvalor"])
        .to_string(index=False)
    )

    print("\nARCHIVOS CREADOS")
    print("-" * 150)
    for ruta in rutas.values():
        print(f" - {ruta.resolve()}")
    print(f" - {graficos.resolve()}")

    print(
        "\nLECTURA CORRECTA:\n"
        "- Un R² mayor es favorable, pero el objetivo principal sigue siendo "
        "reducir MAPE y P90 de la cuota no publicada.\n"
        "- Rolling Ridge pregunta si conviene usar solo la historia reciente.\n"
        "- EW Ridge da más peso a lo reciente sin desechar totalmente el pasado.\n"
        "- ARIMAX incorpora memoria estadística y factores externos.\n"
        "- El siguiente bloque comparará modelos no lineales y el objetivo "
        "directo del retorno acumulado oculto."
    )


if __name__ == "__main__":
    main()
