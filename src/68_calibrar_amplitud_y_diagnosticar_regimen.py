from __future__ import annotations

import json
import math
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from scipy import stats
from sklearn.linear_model import HuberRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score


warnings.filterwarnings("ignore")

AFPS = ["Habitat", "Integra", "Prima", "Profuturo"]
RETRASO_PUBLICACION_DIAS = 5
MIN_HISTORIAL = 60

VENTANAS_ESCALA = [60, 120, 250, None]
VENTANAS_AFIN = [120, 250, None]
VENTANAS_HUBER = [120, 250]
VIDAS_MEDIAS_MAGNITUD = [60, 120, 250]


def leer_csv(ruta: Path) -> pd.DataFrame:
    intentos = [
        {"encoding": "utf-8-sig"},
        {"encoding": "latin-1"},
    ]
    ultimo_error: Exception | None = None
    for argumentos in intentos:
        try:
            return pd.read_csv(ruta, **argumentos)
        except Exception as exc:
            ultimo_error = exc
    raise RuntimeError(f"No se pudo leer {ruta}: {ultimo_error}")


def normalizar(df: pd.DataFrame) -> pd.DataFrame:
    x = df.copy()

    for columna in ["afp", "modelo", "tarea", "segmento"]:
        x[columna] = x[columna].astype(str).str.strip()

    for columna in ["fecha_hoy_simulada", "fecha_ultima_cuota_visible"]:
        x[columna] = pd.to_datetime(
            x[columna], errors="coerce"
        ).dt.normalize()

    numericas = [
        "cuota_ultima_visible",
        "cuota_real_hoy",
        "retorno_acumulado_real",
        "retorno_acumulado_estimado",
    ]
    for columna in numericas:
        x[columna] = pd.to_numeric(x[columna], errors="coerce")

    return (
        x.dropna(
            subset=[
                "afp",
                "modelo",
                "segmento",
                "fecha_hoy_simulada",
                "cuota_ultima_visible",
                "cuota_real_hoy",
                "retorno_acumulado_real",
                "retorno_acumulado_estimado",
            ]
        )
        .sort_values(["afp", "fecha_hoy_simulada"])
        .reset_index(drop=True)
    )


def extraer_ew(df: pd.DataFrame, afp: str) -> pd.DataFrame:
    bloque = df[
        df["afp"].eq(afp)
        & df["modelo"].str.startswith("EW_RIDGE")
        & df["segmento"].isin(["validacion", "prueba"])
    ].copy()

    if bloque.empty:
        raise RuntimeError(f"No se encontró EW Ridge para {afp}.")

    modelo = bloque["modelo"].iloc[0]
    bloque = bloque[bloque["modelo"].eq(modelo)].copy()
    bloque["pred_original"] = bloque["retorno_acumulado_estimado"]

    return bloque[
        [
            "afp",
            "modelo",
            "segmento",
            "fecha_hoy_simulada",
            "fecha_ultima_cuota_visible",
            "cuota_ultima_visible",
            "cuota_real_hoy",
            "retorno_acumulado_real",
            "pred_original",
        ]
    ].sort_values("fecha_hoy_simulada").reset_index(drop=True)


def candidatos() -> list[dict[str, Any]]:
    lista: list[dict[str, Any]] = [
        {
            "metodo": "IDENTIDAD",
            "ventana": None,
            "vida_media": None,
            "nombre": "IDENTIDAD_EW",
        }
    ]

    for ventana in VENTANAS_ESCALA:
        etiqueta = "TODOS" if ventana is None else str(ventana)
        lista.append(
            {
                "metodo": "ESCALA",
                "ventana": ventana,
                "vida_media": None,
                "nombre": f"ESCALA_W{etiqueta}",
            }
        )

    for ventana in VENTANAS_AFIN:
        etiqueta = "TODOS" if ventana is None else str(ventana)
        lista.append(
            {
                "metodo": "AFIN",
                "ventana": ventana,
                "vida_media": None,
                "nombre": f"AFIN_W{etiqueta}",
            }
        )

    for ventana in VENTANAS_HUBER:
        lista.append(
            {
                "metodo": "HUBER",
                "ventana": ventana,
                "vida_media": None,
                "nombre": f"HUBER_W{ventana}",
            }
        )

    for vida_media in VIDAS_MEDIAS_MAGNITUD:
        lista.append(
            {
                "metodo": "MAGNITUD_EWMA",
                "ventana": None,
                "vida_media": vida_media,
                "nombre": f"MAGNITUD_EWMA_HL{vida_media}",
            }
        )

    return lista


def pesos_exponenciales(n: int, vida_media: int) -> np.ndarray:
    edades = np.arange(n - 1, -1, -1, dtype=float)
    return np.power(0.5, edades / float(vida_media))


def ajustar_calibrador(
    historia: pd.DataFrame,
    especificacion: dict[str, Any],
) -> tuple[float, float, float]:
    metodo = especificacion["metodo"]
    ventana = especificacion["ventana"]
    vida_media = especificacion["vida_media"]

    if metodo == "IDENTIDAD":
        return 0.0, 1.0, 1.0

    h = historia.copy()
    if ventana is not None:
        h = h.tail(int(ventana))

    if len(h) < MIN_HISTORIAL:
        return 0.0, 1.0, 1.0

    x = h["pred_original"].to_numpy(float)
    y = h["retorno_acumulado_real"].to_numpy(float)

    if metodo == "ESCALA":
        denominador = float(np.dot(x, x))
        beta = float(np.dot(x, y) / denominador) if denominador > 1e-12 else 1.0
        beta = float(np.clip(beta, 0.35, 2.50))
        return 0.0, beta, beta

    if metodo == "AFIN":
        X = np.column_stack([np.ones(len(x)), x])
        coeficientes = np.linalg.lstsq(X, y, rcond=None)[0]
        intercepto = float(np.clip(coeficientes[0], -0.005, 0.005))
        pendiente = float(np.clip(coeficientes[1], 0.35, 2.50))
        return intercepto, pendiente, pendiente

    if metodo == "HUBER":
        modelo = HuberRegressor(
            epsilon=1.35,
            alpha=0.0001,
            max_iter=500,
        )
        modelo.fit(x.reshape(-1, 1), y)
        intercepto = float(np.clip(modelo.intercept_, -0.005, 0.005))
        pendiente = float(np.clip(modelo.coef_[0], 0.35, 2.50))
        return intercepto, pendiente, pendiente

    if metodo == "MAGNITUD_EWMA":
        pesos = pesos_exponenciales(len(h), int(vida_media))
        numerador = float(np.sum(pesos * np.abs(y)))
        denominador = float(np.sum(pesos * np.abs(x)))
        beta = numerador / denominador if denominador > 1e-12 else 1.0
        beta = float(np.clip(beta, 0.35, 2.50))
        return 0.0, beta, beta

    raise ValueError(f"Método desconocido: {metodo}")


def predecir_walk_forward(
    datos_objetivo: pd.DataFrame,
    historia_inicial: pd.DataFrame,
    especificacion: dict[str, Any],
) -> pd.DataFrame:
    historial = historia_inicial.copy().sort_values("fecha_hoy_simulada")
    resultados = []

    for _, fila in datos_objetivo.sort_values("fecha_hoy_simulada").iterrows():
        fecha_objetivo = pd.Timestamp(fila["fecha_hoy_simulada"])
        fecha_visible = fecha_objetivo - pd.Timedelta(
            days=RETRASO_PUBLICACION_DIAS
        )

        historia_visible = historial[
            historial["fecha_hoy_simulada"].le(fecha_visible)
        ].copy()

        intercepto, pendiente, escala = ajustar_calibrador(
            historia_visible,
            especificacion,
        )

        pred_original = float(fila["pred_original"])
        pred_calibrada = float(intercepto + pendiente * pred_original)

        resultados.append(
            {
                **fila.to_dict(),
                "metodo_calibracion": especificacion["metodo"],
                "nombre_calibracion": especificacion["nombre"],
                "ventana_calibracion": especificacion["ventana"],
                "vida_media_calibracion": especificacion["vida_media"],
                "n_historial_calibracion": int(len(historia_visible)),
                "intercepto_calibracion": intercepto,
                "pendiente_calibracion": pendiente,
                "escala_magnitud": escala,
                "pred_calibrada": pred_calibrada,
            }
        )

        historial = pd.concat(
            [historial, pd.DataFrame([fila.to_dict()])],
            ignore_index=True,
        ).drop_duplicates(
            subset=["fecha_hoy_simulada"],
            keep="last",
        )

    return pd.DataFrame(resultados)


def metricas(df: pd.DataFrame, columna_pred: str) -> dict[str, float]:
    y = df["retorno_acumulado_real"].to_numpy(float)
    p = df[columna_pred].to_numpy(float)
    ancla = df["cuota_ultima_visible"].to_numpy(float)
    cuota_real = df["cuota_real_hoy"].to_numpy(float)

    mascara = np.isfinite(y) & np.isfinite(p) & np.isfinite(ancla) & np.isfinite(
        cuota_real
    )
    y, p = y[mascara], p[mascara]
    ancla, cuota_real = ancla[mascara], cuota_real[mascara]

    cuota_estimada = ancla * (1.0 + p)
    error_pct = cuota_estimada / cuota_real - 1.0
    error_abs = np.abs(error_pct)
    residuo = y - p

    mascara_direccion = np.abs(p) > 1e-15
    direccion = (
        float(
            (
                np.sign(y[mascara_direccion])
                == np.sign(p[mascara_direccion])
            ).mean()
            * 100.0
        )
        if mascara_direccion.any()
        else np.nan
    )

    correlacion = (
        float(np.corrcoef(y, p)[0, 1])
        if np.std(y) > 0 and np.std(p) > 0
        else np.nan
    )

    razon_volatilidad = (
        float(np.std(p, ddof=1) / np.std(y, ddof=1))
        if np.std(y, ddof=1) > 0
        else np.nan
    )

    return {
        "n": int(len(y)),
        "mae_retorno": float(mean_absolute_error(y, p)),
        "rmse_retorno": float(mean_squared_error(y, p) ** 0.5),
        "r2_retorno": float(r2_score(y, p)),
        "sesgo_retorno": float(np.mean(p - y)),
        "desviacion_residual": float(np.std(residuo, ddof=1)),
        "varianza_residual": float(np.var(residuo, ddof=1)),
        "correlacion_retorno": correlacion,
        "direccion_pct": direccion,
        "volatilidad_real": float(np.std(y, ddof=1)),
        "volatilidad_estimada": float(np.std(p, ddof=1)),
        "razon_volatilidad_estimada_real": razon_volatilidad,
        "mape_cuota_pct": float(np.mean(error_abs) * 100.0),
        "mediana_error_abs_pct": float(np.median(error_abs) * 100.0),
        "p90_error_abs_pct": float(np.quantile(error_abs, 0.90) * 100.0),
        "error_maximo_abs_pct": float(np.max(error_abs) * 100.0),
        "sesgo_cuota_pct": float(np.mean(error_pct) * 100.0),
    }


def diebold_mariano(
    perdida_modelo: np.ndarray,
    perdida_referencia: np.ndarray,
    max_lag: int = 5,
) -> dict[str, float]:
    modelo = np.asarray(perdida_modelo, dtype=float)
    referencia = np.asarray(perdida_referencia, dtype=float)
    mascara = np.isfinite(modelo) & np.isfinite(referencia)
    diferencia = modelo[mascara] - referencia[mascara]
    n = len(diferencia)

    if n < 30:
        return {
            "n_dm": int(n),
            "diferencia_media_perdida": np.nan,
            "dm_estadistico": np.nan,
            "dm_pvalor": np.nan,
        }

    media = float(np.mean(diferencia))
    centrada = diferencia - media
    gamma0 = float(np.dot(centrada, centrada) / n)
    var_hac = gamma0

    for lag in range(1, min(max_lag, n - 1) + 1):
        gamma = float(np.dot(centrada[lag:], centrada[:-lag]) / n)
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


def ajuste_holm(pvalores: pd.Series) -> pd.Series:
    p = pvalores.astype(float)
    validos = p.dropna().sort_values()
    cantidad = len(validos)
    salida = pd.Series(np.nan, index=p.index, dtype=float)

    maximo_previo = 0.0
    for posicion, (indice, valor) in enumerate(validos.items(), start=1):
        ajustado = min(1.0, (cantidad - posicion + 1) * valor)
        ajustado = max(maximo_previo, ajustado)
        salida.loc[indice] = ajustado
        maximo_previo = ajustado

    return salida


def agregar_error(df: pd.DataFrame, columna_pred: str) -> pd.DataFrame:
    x = df.copy()
    x["cuota_estimada"] = (
        x["cuota_ultima_visible"] * (1.0 + x[columna_pred])
    )
    x["error_pct"] = x["cuota_estimada"] / x["cuota_real_hoy"] - 1.0
    x["error_abs_pct"] = x["error_pct"].abs()
    return x


def dividir_cuartiles(df: pd.DataFrame) -> pd.DataFrame:
    x = df.sort_values("fecha_hoy_simulada").copy()
    x["subperiodo"] = pd.qcut(
        np.arange(len(x)),
        q=4,
        labels=["Q1", "Q2", "Q3", "Q4"],
    )
    return x


def pruebas_cambio_regimen(df: pd.DataFrame, columna_pred: str) -> dict[str, float]:
    x = dividir_cuartiles(agregar_error(df, columna_pred))
    anterior = x[x["subperiodo"].isin(["Q1", "Q2", "Q3"])]
    reciente = x[x["subperiodo"].eq("Q4")]

    if anterior.empty or reciente.empty:
        return {
            "welch_p_error_firmado": np.nan,
            "levene_p_error_absoluto": np.nan,
            "ks_p_error_absoluto": np.nan,
        }

    welch = stats.ttest_ind(
        anterior["error_pct"],
        reciente["error_pct"],
        equal_var=False,
        nan_policy="omit",
    )
    levene = stats.levene(
        anterior["error_abs_pct"],
        reciente["error_abs_pct"],
        center="median",
    )
    ks = stats.ks_2samp(
        anterior["error_abs_pct"],
        reciente["error_abs_pct"],
    )

    return {
        "welch_p_error_firmado": float(welch.pvalue),
        "levene_p_error_absoluto": float(levene.pvalue),
        "ks_p_error_absoluto": float(ks.pvalue),
    }


def guardar_figura(ruta: Path) -> None:
    plt.tight_layout()
    plt.savefig(ruta, dpi=160, bbox_inches="tight")
    plt.close()


def main() -> None:
    raiz = Path(__file__).resolve().parents[1]
    processed = raiz / "data" / "processed"
    graficos = processed / "graficos_modelo68"
    graficos.mkdir(parents=True, exist_ok=True)

    ruta = processed / "ca0001_modelo66_simulaciones_cuota.csv"
    if not ruta.exists():
        raise FileNotFoundError(f"No existe {ruta}")

    simulaciones = normalizar(leer_csv(ruta))
    especificaciones = candidatos()

    seleccion_filas = []
    metricas_validacion_filas = []
    metricas_prueba_filas = []
    predicciones_prueba = []
    subperiodos_filas = []
    dm_filas = []
    regimen_filas = []

    for afp in AFPS:
        print(f"\nCalibrando amplitud para {afp}...")
        ew = extraer_ew(simulaciones, afp)

        validacion = ew[ew["segmento"].eq("validacion")].copy()
        prueba = ew[ew["segmento"].eq("prueba")].copy()

        if len(validacion) < 200 or len(prueba) < 200:
            raise RuntimeError(
                f"Muestras insuficientes para {afp}: "
                f"validación={len(validacion)}, prueba={len(prueba)}"
            )

        fecha_evaluacion_validacion = validacion[
            "fecha_hoy_simulada"
        ].iloc[min(250, len(validacion) - 1)]

        resultados_validacion = []

        for especificacion in especificaciones:
            pred_val = predecir_walk_forward(
                validacion,
                pd.DataFrame(columns=validacion.columns),
                especificacion,
            )
            evaluable = pred_val[
                pred_val["fecha_hoy_simulada"].ge(
                    fecha_evaluacion_validacion
                )
                & pred_val["n_historial_calibracion"].ge(MIN_HISTORIAL)
            ].copy()

            met = metricas(evaluable, "pred_calibrada")
            fila = {
                "afp": afp,
                **especificacion,
                **met,
            }
            resultados_validacion.append(fila)
            metricas_validacion_filas.append(fila)

        tabla_validacion = pd.DataFrame(resultados_validacion).sort_values(
            [
                "mape_cuota_pct",
                "p90_error_abs_pct",
                "mae_retorno",
                "error_maximo_abs_pct",
            ]
        )
        ganador = tabla_validacion.iloc[0].to_dict()

        seleccion_filas.append(
            {
                "afp": afp,
                "nombre_calibracion": ganador["nombre"],
                "metodo": ganador["metodo"],
                "ventana": ganador["ventana"],
                "vida_media": ganador["vida_media"],
                "mape_validacion_pct": ganador["mape_cuota_pct"],
                "p90_validacion_pct": ganador["p90_error_abs_pct"],
                "r2_validacion": ganador["r2_retorno"],
                "razon_volatilidad_validacion": (
                    ganador["razon_volatilidad_estimada_real"]
                ),
            }
        )

        especificacion_ganadora = next(
            e
            for e in especificaciones
            if e["nombre"] == ganador["nombre"]
        )

        pred_test = predecir_walk_forward(
            prueba,
            validacion,
            especificacion_ganadora,
        )
        pred_test["afp"] = afp
        predicciones_prueba.append(pred_test)

        met_test = metricas(pred_test, "pred_calibrada")
        metricas_prueba_filas.append(
            {
                "afp": afp,
                "modelo_base": ew["modelo"].iloc[0],
                "nombre_calibracion": ganador["nombre"],
                "metodo": ganador["metodo"],
                "ventana": ganador["ventana"],
                "vida_media": ganador["vida_media"],
                **met_test,
            }
        )

        # Subperiodos
        dividido = dividir_cuartiles(pred_test)
        for subperiodo, bloque in dividido.groupby(
            "subperiodo", observed=False
        ):
            met_sub = metricas(bloque, "pred_calibrada")
            subperiodos_filas.append(
                {
                    "afp": afp,
                    "subperiodo": str(subperiodo),
                    "fecha_inicio": bloque[
                        "fecha_hoy_simulada"
                    ].min(),
                    "fecha_fin": bloque[
                        "fecha_hoy_simulada"
                    ].max(),
                    **met_sub,
                }
            )

        # DM contra EW sin calibrar
        base = agregar_error(pred_test, "pred_original")
        calibrado = agregar_error(pred_test, "pred_calibrada")
        dm = diebold_mariano(
            calibrado["error_abs_pct"].to_numpy(float),
            base["error_abs_pct"].to_numpy(float),
            max_lag=5,
        )
        dm_filas.append(
            {
                "afp": afp,
                "modelo": ganador["nombre"],
                "referencia": "EW_RIDGE_SIN_CALIBRAR",
                **dm,
            }
        )

        regimen_filas.append(
            {
                "afp": afp,
                "modelo": ganador["nombre"],
                **pruebas_cambio_regimen(
                    pred_test,
                    "pred_calibrada",
                ),
            }
        )

        # Gráfico cuota
        cuota_base = (
            pred_test["cuota_ultima_visible"]
            * (1.0 + pred_test["pred_original"])
        )
        cuota_calibrada = (
            pred_test["cuota_ultima_visible"]
            * (1.0 + pred_test["pred_calibrada"])
        )

        plt.figure(figsize=(12, 5))
        plt.plot(
            pred_test["fecha_hoy_simulada"],
            pred_test["cuota_real_hoy"],
            label="Cuota SBS",
        )
        plt.plot(
            pred_test["fecha_hoy_simulada"],
            cuota_base,
            label="EW Ridge original",
        )
        plt.plot(
            pred_test["fecha_hoy_simulada"],
            cuota_calibrada,
            label="EW Ridge calibrado",
        )
        plt.ylabel("Valor cuota")
        plt.title(f"Calibración de amplitud — {afp}")
        plt.legend()
        guardar_figura(
            graficos / f"01_cuota_calibrada_{afp.lower()}.png"
        )

        # Pendiente/escala
        plt.figure(figsize=(12, 5))
        plt.plot(
            pred_test["fecha_hoy_simulada"],
            pred_test["pendiente_calibracion"],
        )
        plt.axhline(1.0, linestyle="--")
        plt.ylabel("Factor de escala")
        plt.title(f"Escala dinámica del retorno estimado — {afp}")
        guardar_figura(
            graficos / f"02_escala_dinamica_{afp.lower()}.png"
        )

        # MAPE móvil
        errores = pd.DataFrame(
            {
                "fecha": pred_test["fecha_hoy_simulada"],
                "base": base["error_abs_pct"] * 100.0,
                "calibrado": calibrado["error_abs_pct"] * 100.0,
            }
        ).sort_values("fecha")
        errores["mape60_base"] = errores["base"].rolling(60).mean()
        errores["mape60_calibrado"] = (
            errores["calibrado"].rolling(60).mean()
        )

        plt.figure(figsize=(12, 5))
        plt.plot(
            errores["fecha"],
            errores["mape60_base"],
            label="EW Ridge original",
        )
        plt.plot(
            errores["fecha"],
            errores["mape60_calibrado"],
            label="Calibrado",
        )
        plt.ylabel("MAPE móvil 60 observaciones (%)")
        plt.title(f"Error móvil antes y después de calibrar — {afp}")
        plt.legend()
        guardar_figura(
            graficos / f"03_mape_movil_{afp.lower()}.png"
        )

    seleccion_df = pd.DataFrame(seleccion_filas)
    validacion_df = pd.DataFrame(metricas_validacion_filas)
    prueba_df = pd.DataFrame(metricas_prueba_filas)
    predicciones_df = pd.concat(
        predicciones_prueba,
        ignore_index=True,
    )
    subperiodos_df = pd.DataFrame(subperiodos_filas)
    dm_df = pd.DataFrame(dm_filas)
    regimen_df = pd.DataFrame(regimen_filas)

    dm_df["pvalor_holm"] = ajuste_holm(dm_df["dm_pvalor"])
    dm_df["supera_base_con_evidencia"] = (
        dm_df["diferencia_media_perdida"].lt(0)
        & dm_df["pvalor_holm"].lt(0.05)
    )

    rutas = {
        "seleccion": (
            processed
            / "ca0001_modelo68_calibracion_seleccionada.csv"
        ),
        "validacion": (
            processed
            / "ca0001_modelo68_metricas_validacion.csv"
        ),
        "prueba": (
            processed
            / "ca0001_modelo68_metricas_prueba.csv"
        ),
        "predicciones": (
            processed
            / "ca0001_modelo68_predicciones_prueba.csv"
        ),
        "subperiodos": (
            processed
            / "ca0001_modelo68_estabilidad_subperiodos.csv"
        ),
        "dm": (
            processed
            / "ca0001_modelo68_diebold_mariano.csv"
        ),
        "regimen": (
            processed
            / "ca0001_modelo68_pruebas_cambio_regimen.csv"
        ),
        "resumen": (
            processed
            / "ca0001_modelo68_resumen.json"
        ),
    }

    seleccion_df.to_csv(
        rutas["seleccion"],
        index=False,
        encoding="utf-8-sig",
    )
    validacion_df.to_csv(
        rutas["validacion"],
        index=False,
        encoding="utf-8-sig",
    )
    prueba_df.to_csv(
        rutas["prueba"],
        index=False,
        encoding="utf-8-sig",
    )
    predicciones_df.to_csv(
        rutas["predicciones"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    subperiodos_df.to_csv(
        rutas["subperiodos"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    dm_df.to_csv(
        rutas["dm"],
        index=False,
        encoding="utf-8-sig",
    )
    regimen_df.to_csv(
        rutas["regimen"],
        index=False,
        encoding="utf-8-sig",
    )

    resumen = {
        "version": "modelo68_calibracion_amplitud_y_regimen",
        "metodologia": (
            "La calibración se selecciona dentro de validación. "
            "En prueba se actualiza únicamente con resultados cuya fecha "
            "ya habría sido publicada al considerar cinco días de retraso."
        ),
        "seleccion": seleccion_df.to_dict(orient="records"),
        "metricas_prueba": prueba_df.to_dict(orient="records"),
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

    print("\nMÓDULO 68 — CALIBRACIÓN DE AMPLITUD Y CAMBIO DE RÉGIMEN")
    print("=" * 150)
    print(
        "Se comprueba si el problema reciente es de magnitud: "
        "el modelo acierta la dirección, pero subestima o sobrestima "
        "la amplitud del movimiento."
    )

    print("\nCALIBRACIÓN SELECCIONADA CON VALIDACIÓN")
    print("-" * 150)
    print(seleccion_df.to_string(index=False))

    print("\nMÉTRICAS EN PRUEBA")
    print("-" * 150)
    print(
        prueba_df[
            [
                "afp",
                "nombre_calibracion",
                "n",
                "mae_retorno",
                "rmse_retorno",
                "r2_retorno",
                "correlacion_retorno",
                "direccion_pct",
                "razon_volatilidad_estimada_real",
                "mape_cuota_pct",
                "mediana_error_abs_pct",
                "p90_error_abs_pct",
                "error_maximo_abs_pct",
                "sesgo_cuota_pct",
            ]
        ].to_string(index=False)
    )

    print("\nDIEBOLD-MARIANO CONTRA EW RIDGE SIN CALIBRAR")
    print("-" * 150)
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
                "supera_base_con_evidencia",
            ]
        ].to_string(index=False)
    )

    print("\nESTABILIDAD POR SUBPERIODOS")
    print("-" * 150)
    print(
        subperiodos_df[
            [
                "afp",
                "subperiodo",
                "fecha_inicio",
                "fecha_fin",
                "mape_cuota_pct",
                "p90_error_abs_pct",
                "r2_retorno",
                "direccion_pct",
                "razon_volatilidad_estimada_real",
            ]
        ].to_string(index=False)
    )

    print("\nPRUEBAS DE CAMBIO DE RÉGIMEN: Q1-Q3 VS Q4")
    print("-" * 150)
    print(regimen_df.to_string(index=False))

    print("\nARCHIVOS CREADOS")
    print("-" * 150)
    for ruta in rutas.values():
        print(f" - {ruta.resolve()}")
    print(f" - {graficos.resolve()}")

    print(
        "\nLECTURA:\n"
        "- razón de volatilidad < 1: el modelo reacciona con poca amplitud.\n"
        "- razón de volatilidad > 1: el modelo exagera la amplitud.\n"
        "- p-valores de régimen < 0.05 indican que Q4 cambió "
        "significativamente respecto de Q1-Q3.\n"
        "- La calibración solo se adopta si mejora prueba y no genera "
        "inestabilidad.\n"
        "- Después de este diagnóstico corresponde ampliar el universo de "
        "factores, porque más complejidad con la misma canasta ya no basta."
    )


if __name__ == "__main__":
    main()
