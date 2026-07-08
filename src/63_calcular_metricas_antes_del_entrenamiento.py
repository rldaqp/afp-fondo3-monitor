from __future__ import annotations

import json
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score


warnings.filterwarnings("ignore")

AFPS = ["Habitat", "Integra", "Prima", "Profuturo"]
RETRASO_PUBLICACION_DIAS = 5
MIN_EXPANDING = 60
VENTANA_MEDIA = 20

BASELINES = {
    "RETORNO_CERO": "Pronostica retorno diario igual a cero.",
    "PERSISTENCIA_1D": "Usa como pronóstico el retorno observado del día anterior.",
    "MEDIA_EXPANSIVA": (
        f"Usa el promedio histórico disponible hasta el día anterior, "
        f"con un mínimo de {MIN_EXPANDING} observaciones."
    ),
    "MEDIA_MOVIL_20": (
        f"Usa el promedio de los últimos {VENTANA_MEDIA} retornos disponibles, "
        "sin utilizar el retorno del día objetivo."
    ),
}


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
        raise FileNotFoundError(
            "No existe ca0001_modelo50_division_temporal.csv."
        )

    df = leer_csv_flexible(ruta)
    df["fecha_inicio"] = pd.to_datetime(df["fecha_inicio"], errors="coerce")
    df["fecha_fin"] = pd.to_datetime(df["fecha_fin"], errors="coerce")

    train = df[df["segmento"].astype(str).eq("entrenamiento_descubrimiento")]
    valid = df[df["segmento"].astype(str).eq("validacion")]

    if train.empty or valid.empty:
        raise ValueError(
            "No se encontraron los segmentos entrenamiento y validación."
        )

    return (
        pd.Timestamp(train["fecha_fin"].iloc[0]),
        pd.Timestamp(valid["fecha_fin"].iloc[0]),
    )


def cargar_base(processed: Path) -> pd.DataFrame:
    ruta = processed / "ca0001_modelo56_base_alineada.csv"

    if not ruta.exists():
        raise FileNotFoundError(
            "No existe ca0001_modelo56_base_alineada.csv. "
            "Ejecute primero el módulo 56."
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


def generar_predicciones_baseline(
    base: pd.DataFrame,
    fin_train: pd.Timestamp,
    fin_valid: pd.Timestamp,
) -> pd.DataFrame:
    resultados = []

    for afp, grupo in base.groupby("afp", sort=False):
        g = grupo[
            ["fecha_cuota", "cuota_sbs", "retorno_cuota"]
        ].copy()
        g = g.sort_values("fecha_cuota").reset_index(drop=True)

        retorno = g["retorno_cuota"]

        predicciones = {
            "RETORNO_CERO": pd.Series(0.0, index=g.index),
            "PERSISTENCIA_1D": retorno.shift(1),
            "MEDIA_EXPANSIVA": (
                retorno.shift(1)
                .expanding(min_periods=MIN_EXPANDING)
                .mean()
            ),
            "MEDIA_MOVIL_20": (
                retorno.shift(1)
                .rolling(VENTANA_MEDIA, min_periods=VENTANA_MEDIA)
                .mean()
            ),
        }

        for baseline, pred in predicciones.items():
            bloque = g.copy()
            bloque["afp"] = afp
            bloque["baseline"] = baseline
            bloque["retorno_estimado"] = pred
            bloque["segmento"] = bloque["fecha_cuota"].apply(
                lambda fecha: asignar_segmento(
                    pd.Timestamp(fecha),
                    fin_train,
                    fin_valid,
                )
            )
            resultados.append(bloque)

    return pd.concat(resultados, ignore_index=True)


def metricas_diarias(
    y_real: np.ndarray,
    y_pred: np.ndarray,
) -> dict[str, float]:
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
            "correlacion_real_estimado": np.nan,
            "direccion_diaria_pct": np.nan,
            "cobertura_direccional_pct": 0.0,
        }

    mae = float(mean_absolute_error(y, p))
    rmse = float(mean_squared_error(y, p) ** 0.5)
    r2 = float(r2_score(y, p)) if len(y) >= 2 else np.nan
    sesgo = float(np.mean(p - y))

    if np.std(p) > 0 and np.std(y) > 0:
        correlacion = float(np.corrcoef(y, p)[0, 1])
    else:
        correlacion = np.nan

    mascara_dir = np.abs(p) > 1e-15
    cobertura_dir = float(mascara_dir.mean() * 100.0)

    if mascara_dir.any():
        direccion = float(
            (
                np.sign(y[mascara_dir])
                == np.sign(p[mascara_dir])
            ).mean()
            * 100.0
        )
    else:
        direccion = np.nan

    return {
        "n": int(len(y)),
        "mae": mae,
        "rmse": rmse,
        "r2": r2,
        "sesgo": sesgo,
        "correlacion_real_estimado": correlacion,
        "direccion_diaria_pct": direccion,
        "cobertura_direccional_pct": cobertura_dir,
    }


def evaluar_metricas_diarias(
    predicciones: pd.DataFrame,
) -> pd.DataFrame:
    filas = []

    for (afp, baseline, segmento), grupo in predicciones.groupby(
        ["afp", "baseline", "segmento"],
        sort=False,
    ):
        metricas = metricas_diarias(
            grupo["retorno_cuota"].to_numpy(dtype=float),
            grupo["retorno_estimado"].to_numpy(dtype=float),
        )
        filas.append(
            {
                "afp": afp,
                "baseline": baseline,
                "segmento": segmento,
                **metricas,
            }
        )

    return pd.DataFrame(filas)


def simular_publicacion_5d(
    base_afp: pd.DataFrame,
    pred_afp_baseline: pd.DataFrame,
    fin_train: pd.Timestamp,
    fin_valid: pd.Timestamp,
) -> pd.DataFrame:
    cuotas = (
        base_afp[
            ["fecha_cuota", "cuota_sbs"]
        ]
        .dropna()
        .drop_duplicates("fecha_cuota", keep="last")
        .sort_values("fecha_cuota")
        .reset_index(drop=True)
    )

    pred = (
        pred_afp_baseline[
            ["fecha_cuota", "retorno_estimado"]
        ]
        .drop_duplicates("fecha_cuota", keep="last")
        .sort_values("fecha_cuota")
    )

    pred_map = pred.set_index("fecha_cuota")[
        "retorno_estimado"
    ].to_dict()

    resultados = []

    for _, objetivo in cuotas.iterrows():
        fecha_objetivo = pd.Timestamp(objetivo["fecha_cuota"])
        fecha_corte_visible = (
            fecha_objetivo
            - pd.Timedelta(days=RETRASO_PUBLICACION_DIAS)
        )

        candidatas = cuotas[
            cuotas["fecha_cuota"].le(fecha_corte_visible)
        ]

        if candidatas.empty:
            continue

        ancla = candidatas.iloc[-1]
        fecha_ancla = pd.Timestamp(ancla["fecha_cuota"])

        fechas_ocultas = cuotas[
            cuotas["fecha_cuota"].gt(fecha_ancla)
            & cuotas["fecha_cuota"].le(fecha_objetivo)
        ]["fecha_cuota"].tolist()

        if not fechas_ocultas:
            continue

        retornos_estimados = []
        predicciones_completas = True

        for fecha in fechas_ocultas:
            valor = pred_map.get(fecha, np.nan)
            if not np.isfinite(valor):
                predicciones_completas = False
                break
            retornos_estimados.append(float(valor))

        if not predicciones_completas:
            continue

        cuota_ancla = float(ancla["cuota_sbs"])
        cuota_real = float(objetivo["cuota_sbs"])
        retorno_estimado_acumulado = float(
            np.prod(1.0 + np.asarray(retornos_estimados)) - 1.0
        )
        cuota_estimada = cuota_ancla * (
            1.0 + retorno_estimado_acumulado
        )
        retorno_real_acumulado = cuota_real / cuota_ancla - 1.0
        error_pct = cuota_estimada / cuota_real - 1.0

        resultados.append(
            {
                "fecha_hoy_simulada": fecha_objetivo,
                "segmento": asignar_segmento(
                    fecha_objetivo,
                    fin_train,
                    fin_valid,
                ),
                "fecha_ultima_cuota_visible": fecha_ancla,
                "cuota_ultima_visible": cuota_ancla,
                "cuotas_ocultas_estimadas": len(fechas_ocultas),
                "cuota_estimada_hoy": cuota_estimada,
                "cuota_real_hoy": cuota_real,
                "error_pct": error_pct,
                "error_abs_pct": abs(error_pct),
                "retorno_estimado_acumulado": (
                    retorno_estimado_acumulado
                ),
                "retorno_real_acumulado": retorno_real_acumulado,
            }
        )

    return pd.DataFrame(resultados)


def metricas_publicacion(
    simulacion: pd.DataFrame,
) -> dict[str, float]:
    if simulacion.empty:
        return {
            "n_publicacion": 0,
            "mape_cuota_5d_pct": np.nan,
            "mediana_error_abs_5d_pct": np.nan,
            "p90_error_abs_5d_pct": np.nan,
            "error_maximo_abs_5d_pct": np.nan,
            "sesgo_5d_pct": np.nan,
            "correlacion_retorno_acumulado": np.nan,
            "direccion_acumulada_pct": np.nan,
            "cobertura_direccional_acumulada_pct": 0.0,
        }

    pred = simulacion["retorno_estimado_acumulado"].to_numpy()
    real = simulacion["retorno_real_acumulado"].to_numpy()

    mascara_dir = np.abs(pred) > 1e-15
    cobertura_dir = float(mascara_dir.mean() * 100.0)

    if mascara_dir.any():
        direccion = float(
            (
                np.sign(pred[mascara_dir])
                == np.sign(real[mascara_dir])
            ).mean()
            * 100.0
        )
    else:
        direccion = np.nan

    if np.std(pred) > 0 and np.std(real) > 0:
        correlacion = float(np.corrcoef(real, pred)[0, 1])
    else:
        correlacion = np.nan

    return {
        "n_publicacion": int(len(simulacion)),
        "mape_cuota_5d_pct": float(
            simulacion["error_abs_pct"].mean() * 100.0
        ),
        "mediana_error_abs_5d_pct": float(
            simulacion["error_abs_pct"].median() * 100.0
        ),
        "p90_error_abs_5d_pct": float(
            simulacion["error_abs_pct"].quantile(0.90) * 100.0
        ),
        "error_maximo_abs_5d_pct": float(
            simulacion["error_abs_pct"].max() * 100.0
        ),
        "sesgo_5d_pct": float(
            simulacion["error_pct"].mean() * 100.0
        ),
        "correlacion_retorno_acumulado": correlacion,
        "direccion_acumulada_pct": direccion,
        "cobertura_direccional_acumulada_pct": cobertura_dir,
    }


def evaluar_publicacion_5d(
    base: pd.DataFrame,
    predicciones: pd.DataFrame,
    fin_train: pd.Timestamp,
    fin_valid: pd.Timestamp,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    simulaciones = []
    metricas = []

    for afp in AFPS:
        base_afp = base[base["afp"].eq(afp)].copy()

        for baseline in BASELINES:
            pred = predicciones[
                predicciones["afp"].eq(afp)
                & predicciones["baseline"].eq(baseline)
            ].copy()

            simulacion = simular_publicacion_5d(
                base_afp,
                pred,
                fin_train,
                fin_valid,
            )

            if not simulacion.empty:
                simulacion["afp"] = afp
                simulacion["baseline"] = baseline
                simulaciones.append(simulacion)

            for segmento in [
                "entrenamiento",
                "validacion",
                "prueba",
            ]:
                bloque = simulacion[
                    simulacion["segmento"].eq(segmento)
                ] if not simulacion.empty else pd.DataFrame()

                metricas.append(
                    {
                        "afp": afp,
                        "baseline": baseline,
                        "segmento": segmento,
                        **metricas_publicacion(bloque),
                    }
                )

    simulaciones_df = (
        pd.concat(simulaciones, ignore_index=True)
        if simulaciones
        else pd.DataFrame()
    )

    return simulaciones_df, pd.DataFrame(metricas)


def agregar_comparaciones_con_cero(
    metricas_diarias_df: pd.DataFrame,
    metricas_5d_df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    diarias = metricas_diarias_df.copy()
    publicacion = metricas_5d_df.copy()

    referencia_mae = (
        diarias[diarias["baseline"].eq("RETORNO_CERO")]
        [["afp", "segmento", "mae"]]
        .rename(columns={"mae": "mae_retorno_cero"})
    )

    diarias = diarias.merge(
        referencia_mae,
        on=["afp", "segmento"],
        how="left",
    )
    diarias["mejora_mae_vs_cero_pct"] = (
        (
            diarias["mae_retorno_cero"]
            - diarias["mae"]
        )
        / diarias["mae_retorno_cero"]
        * 100.0
    )
    diarias["ranking_mae"] = diarias.groupby(
        ["afp", "segmento"]
    )["mae"].rank(method="min", ascending=True)

    referencia_mape = (
        publicacion[
            publicacion["baseline"].eq("RETORNO_CERO")
        ]
        [["afp", "segmento", "mape_cuota_5d_pct"]]
        .rename(
            columns={
                "mape_cuota_5d_pct": (
                    "mape_cuota_5d_retorno_cero_pct"
                )
            }
        )
    )

    publicacion = publicacion.merge(
        referencia_mape,
        on=["afp", "segmento"],
        how="left",
    )
    publicacion["mejora_mape_vs_cero_pct"] = (
        (
            publicacion[
                "mape_cuota_5d_retorno_cero_pct"
            ]
            - publicacion["mape_cuota_5d_pct"]
        )
        / publicacion[
            "mape_cuota_5d_retorno_cero_pct"
        ]
        * 100.0
    )
    publicacion["ranking_mape"] = publicacion.groupby(
        ["afp", "segmento"]
    )["mape_cuota_5d_pct"].rank(
        method="min",
        ascending=True,
    )

    return diarias, publicacion


def guardar_figura(ruta: Path) -> None:
    plt.tight_layout()
    plt.savefig(ruta, dpi=160, bbox_inches="tight")
    plt.close()


def graficar_resultados(
    metricas_diarias_df: pd.DataFrame,
    metricas_5d_df: pd.DataFrame,
    graficos: Path,
) -> None:
    graficos.mkdir(parents=True, exist_ok=True)

    for afp in AFPS:
        diario = metricas_diarias_df[
            metricas_diarias_df["afp"].eq(afp)
            & metricas_diarias_df["segmento"].eq("prueba")
        ].sort_values("mae")

        if not diario.empty:
            x = np.arange(len(diario))
            ancho = 0.36

            plt.figure(figsize=(10, 5))
            plt.bar(
                x - ancho / 2,
                diario["mae"],
                width=ancho,
                label="MAE",
            )
            plt.bar(
                x + ancho / 2,
                diario["rmse"],
                width=ancho,
                label="RMSE",
            )
            plt.xticks(
                x,
                diario["baseline"],
                rotation=25,
                ha="right",
            )
            plt.ylabel("Error del retorno diario")
            plt.title(
                f"Baselines antes del entrenamiento — "
                f"MAE y RMSE en prueba — {afp}"
            )
            plt.legend()
            guardar_figura(
                graficos
                / f"01_mae_rmse_prueba_{afp.lower()}.png"
            )

        cuota = metricas_5d_df[
            metricas_5d_df["afp"].eq(afp)
            & metricas_5d_df["segmento"].eq("prueba")
        ].sort_values("mape_cuota_5d_pct")

        if not cuota.empty:
            x = np.arange(len(cuota))
            ancho = 0.36

            plt.figure(figsize=(10, 5))
            plt.bar(
                x - ancho / 2,
                cuota["mape_cuota_5d_pct"],
                width=ancho,
                label="MAPE cuota",
            )
            plt.bar(
                x + ancho / 2,
                cuota["p90_error_abs_5d_pct"],
                width=ancho,
                label="P90 error",
            )
            plt.xticks(
                x,
                cuota["baseline"],
                rotation=25,
                ha="right",
            )
            plt.ylabel("Porcentaje")
            plt.title(
                f"Baselines antes del entrenamiento — "
                f"MAPE y P90 con retraso SBS — {afp}"
            )
            plt.legend()
            guardar_figura(
                graficos
                / f"02_mape_p90_prueba_{afp.lower()}.png"
            )

        evolucion = metricas_5d_df[
            metricas_5d_df["afp"].eq(afp)
        ].copy()

        if not evolucion.empty:
            orden_segmentos = {
                "entrenamiento": 0,
                "validacion": 1,
                "prueba": 2,
            }
            evolucion["orden_segmento"] = evolucion[
                "segmento"
            ].map(orden_segmentos)

            plt.figure(figsize=(10, 5))
            for baseline, grupo in evolucion.groupby(
                "baseline"
            ):
                grupo = grupo.sort_values("orden_segmento")
                plt.plot(
                    grupo["segmento"],
                    grupo["mape_cuota_5d_pct"],
                    marker="o",
                    label=baseline,
                )

            plt.ylabel("MAPE del valor cuota (%)")
            plt.title(
                f"Estabilidad de los baselines por segmento — {afp}"
            )
            plt.legend()
            guardar_figura(
                graficos
                / f"03_mape_segmentos_{afp.lower()}.png"
            )


def main() -> None:
    raiz = Path(__file__).resolve().parents[1]
    processed = raiz / "data" / "processed"
    graficos = processed / "graficos_modelo63"

    fin_train, fin_valid = cargar_division(processed)
    base = cargar_base(processed)

    predicciones = generar_predicciones_baseline(
        base,
        fin_train,
        fin_valid,
    )

    metricas_diarias_df = evaluar_metricas_diarias(
        predicciones
    )

    simulaciones_df, metricas_5d_df = evaluar_publicacion_5d(
        base,
        predicciones,
        fin_train,
        fin_valid,
    )

    metricas_diarias_df, metricas_5d_df = (
        agregar_comparaciones_con_cero(
            metricas_diarias_df,
            metricas_5d_df,
        )
    )

    resumen_prueba = metricas_diarias_df[
        metricas_diarias_df["segmento"].eq("prueba")
    ].merge(
        metricas_5d_df[
            metricas_5d_df["segmento"].eq("prueba")
        ],
        on=["afp", "baseline", "segmento"],
        how="outer",
        suffixes=("_diario", "_5d"),
    )

    graficar_resultados(
        metricas_diarias_df,
        metricas_5d_df,
        graficos,
    )

    rutas = {
        "predicciones": (
            processed
            / "ca0001_modelo63_predicciones_baselines.csv"
        ),
        "metricas_diarias": (
            processed
            / "ca0001_modelo63_metricas_diarias_baselines.csv"
        ),
        "simulacion_5d": (
            processed
            / "ca0001_modelo63_simulacion_publicacion_5d_baselines.csv"
        ),
        "metricas_5d": (
            processed
            / "ca0001_modelo63_metricas_publicacion_5d_baselines.csv"
        ),
        "resumen_prueba": (
            processed
            / "ca0001_modelo63_resumen_prueba_baselines.csv"
        ),
        "resumen_json": (
            processed
            / "ca0001_modelo63_resumen.json"
        ),
    }

    predicciones.to_csv(
        rutas["predicciones"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    metricas_diarias_df.to_csv(
        rutas["metricas_diarias"],
        index=False,
        encoding="utf-8-sig",
    )
    simulaciones_df.to_csv(
        rutas["simulacion_5d"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    metricas_5d_df.to_csv(
        rutas["metricas_5d"],
        index=False,
        encoding="utf-8-sig",
    )
    resumen_prueba.to_csv(
        rutas["resumen_prueba"],
        index=False,
        encoding="utf-8-sig",
    )

    resumen = {
        "version": "modelo63_metricas_antes_del_entrenamiento",
        "principio": (
            "No existe MAE de un modelo inexistente. "
            "Estas métricas corresponden a predictores ingenuos "
            "que se calculan antes de entrenar modelos complejos "
            "y establecen el piso mínimo que deben superar."
        ),
        "baselines": BASELINES,
        "fecha_fin_train": str(fin_train.date()),
        "fecha_fin_validacion": str(fin_valid.date()),
        "resumen_prueba": resumen_prueba.to_dict(
            orient="records"
        ),
        "graficos_generados": len(
            list(graficos.glob("*.png"))
        ),
    }

    rutas["resumen_json"].write_text(
        json.dumps(
            resumen,
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )

    print(
        "\nMÓDULO 63 — MÉTRICAS ANTES DEL ENTRENAMIENTO"
    )
    print("=" * 120)
    print(
        "Se evaluaron predictores ingenuos sin entrenar "
        "modelos estadísticos o de machine learning."
    )

    print("\nMÉTRICAS DIARIAS — SEGMENTO DE PRUEBA")
    print("-" * 120)
    columnas_diarias = [
        "afp",
        "baseline",
        "n",
        "mae",
        "rmse",
        "r2",
        "sesgo",
        "direccion_diaria_pct",
        "cobertura_direccional_pct",
        "mejora_mae_vs_cero_pct",
        "ranking_mae",
    ]
    print(
        metricas_diarias_df[
            metricas_diarias_df["segmento"].eq("prueba")
        ][columnas_diarias]
        .sort_values(["afp", "ranking_mae"])
        .to_string(index=False)
    )

    print(
        "\nMÉTRICAS DEL VALOR CUOTA CON RETRASO "
        "DE CINCO DÍAS — PRUEBA"
    )
    print("-" * 120)
    columnas_5d = [
        "afp",
        "baseline",
        "n_publicacion",
        "mape_cuota_5d_pct",
        "mediana_error_abs_5d_pct",
        "p90_error_abs_5d_pct",
        "error_maximo_abs_5d_pct",
        "sesgo_5d_pct",
        "direccion_acumulada_pct",
        "cobertura_direccional_acumulada_pct",
        "mejora_mape_vs_cero_pct",
        "ranking_mape",
    ]
    print(
        metricas_5d_df[
            metricas_5d_df["segmento"].eq("prueba")
        ][columnas_5d]
        .sort_values(["afp", "ranking_mape"])
        .to_string(index=False)
    )

    print("\nARCHIVOS CREADOS")
    print("-" * 120)
    for ruta in rutas.values():
        print(f" - {ruta.resolve()}")
    print(f" - {graficos.resolve()}")

    print(
        "\nLECTURA CORRECTA:\n"
        "- Estas son las métricas que sí pueden calcularse "
        "antes de entrenar modelos complejos.\n"
        "- RETORNO_CERO equivale a mantener la última cuota "
        "visible en la simulación de publicación.\n"
        "- Los futuros modelos deberán reducir MAE, RMSE, "
        "MAPE y P90 respecto de estos baselines.\n"
        "- La dirección del predictor cero se deja como no "
        "aplicable porque no pronostica subida ni caída.\n"
        "- Los mismos indicadores se volverán a calcular "
        "después del entrenamiento para comparar de forma justa."
    )


if __name__ == "__main__":
    main()
