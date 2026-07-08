from __future__ import annotations

import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

warnings.filterwarnings("ignore")

AFPS = ["Habitat", "Integra", "Prima", "Profuturo"]
RETRASO_PUBLICACION_DIAS = 5
MIN_EXPANDING = 60
VENTANA_MEDIA = 20

BASELINES = [
    "RETORNO_CERO",
    "PERSISTENCIA_1D",
    "MEDIA_EXPANSIVA",
    "MEDIA_MOVIL_20",
]


def leer_csv_flexible(ruta: Path) -> pd.DataFrame:
    intentos = [
        {"sep": None, "engine": "python", "encoding": "utf-8-sig"},
        {"sep": None, "engine": "python", "encoding": "latin-1"},
        {"sep": ",", "encoding": "utf-8-sig"},
        {"sep": ";", "encoding": "utf-8-sig"},
        {"sep": ";", "encoding": "latin-1"},
    ]
    ultimo_error = None
    for args in intentos:
        try:
            return pd.read_csv(ruta, **args)
        except Exception as exc:
            ultimo_error = exc
    raise RuntimeError(f"No se pudo leer {ruta}: {ultimo_error}")


def cargar_division(processed: Path) -> tuple[pd.Timestamp, pd.Timestamp]:
    ruta = processed / "ca0001_modelo50_division_temporal.csv"
    df = leer_csv_flexible(ruta)
    df["fecha_fin"] = pd.to_datetime(df["fecha_fin"], errors="coerce")

    train = df[df["segmento"].astype(str).eq("entrenamiento_descubrimiento")]
    valid = df[df["segmento"].astype(str).eq("validacion")]

    if train.empty or valid.empty:
        raise ValueError("No se encontraron entrenamiento y validación.")

    return pd.Timestamp(train["fecha_fin"].iloc[0]), pd.Timestamp(valid["fecha_fin"].iloc[0])


def cargar_base(processed: Path) -> pd.DataFrame:
    ruta = processed / "ca0001_modelo56_base_alineada.csv"
    df = leer_csv_flexible(ruta)
    df["fecha_cuota"] = pd.to_datetime(df["fecha_cuota"], errors="coerce")
    df["cuota_sbs"] = pd.to_numeric(df["cuota_sbs"], errors="coerce")
    df["retorno_cuota"] = pd.to_numeric(df["retorno_cuota"], errors="coerce")

    return (
        df.dropna(subset=["fecha_cuota", "afp", "cuota_sbs"])
        .sort_values(["afp", "fecha_cuota"])
        .reset_index(drop=True)
    )


def segmento(fecha: pd.Timestamp, fin_train: pd.Timestamp, fin_valid: pd.Timestamp) -> str:
    if fecha <= fin_train:
        return "entrenamiento"
    if fecha <= fin_valid:
        return "validacion"
    return "prueba"


def predicciones_diarias_un_paso(
    base: pd.DataFrame,
    fin_train: pd.Timestamp,
    fin_valid: pd.Timestamp,
) -> pd.DataFrame:
    salidas = []

    for afp, grupo in base.groupby("afp", sort=False):
        g = grupo[["fecha_cuota", "cuota_sbs", "retorno_cuota"]].copy()
        g = g.sort_values("fecha_cuota").reset_index(drop=True)
        r = g["retorno_cuota"]

        pred_map = {
            "RETORNO_CERO": pd.Series(0.0, index=g.index),
            "PERSISTENCIA_1D": r.shift(1),
            "MEDIA_EXPANSIVA": r.shift(1).expanding(min_periods=MIN_EXPANDING).mean(),
            "MEDIA_MOVIL_20": r.shift(1).rolling(
                VENTANA_MEDIA, min_periods=VENTANA_MEDIA
            ).mean(),
        }

        for nombre, pred in pred_map.items():
            b = g.copy()
            b["afp"] = afp
            b["baseline"] = nombre
            b["retorno_estimado"] = pred
            b["segmento"] = b["fecha_cuota"].apply(
                lambda f: segmento(pd.Timestamp(f), fin_train, fin_valid)
            )
            salidas.append(b)

    return pd.concat(salidas, ignore_index=True)


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
            "cobertura_direccional_pct": 0.0,
        }

    mae = float(mean_absolute_error(y, p))
    rmse = float(mean_squared_error(y, p) ** 0.5)
    r2 = float(r2_score(y, p)) if len(y) >= 2 else np.nan
    sesgo = float(np.mean(p - y))

    correlacion = (
        float(np.corrcoef(y, p)[0, 1])
        if np.std(y) > 0 and np.std(p) > 0
        else np.nan
    )

    mascara_dir = np.abs(p) > 1e-15
    cobertura = float(mascara_dir.mean() * 100.0)
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
        "cobertura_direccional_pct": cobertura,
    }


def evaluar_diarias(pred: pd.DataFrame) -> pd.DataFrame:
    filas = []
    for (afp, baseline, seg), g in pred.groupby(
        ["afp", "baseline", "segmento"], sort=False
    ):
        filas.append(
            {
                "afp": afp,
                "baseline": baseline,
                "segmento": seg,
                **metricas_diarias(
                    g["retorno_cuota"].to_numpy(float),
                    g["retorno_estimado"].to_numpy(float),
                ),
            }
        )
    return pd.DataFrame(filas)


def siguiente_prediccion_recursiva(
    baseline: str,
    historial_visible_y_predicho: list[float],
) -> float:
    if baseline == "RETORNO_CERO":
        return 0.0

    if baseline == "PERSISTENCIA_1D":
        return float(historial_visible_y_predicho[-1])

    if baseline == "MEDIA_EXPANSIVA":
        return float(np.mean(historial_visible_y_predicho))

    if baseline == "MEDIA_MOVIL_20":
        ventana = historial_visible_y_predicho[-VENTANA_MEDIA:]
        return float(np.mean(ventana))

    raise ValueError(f"Baseline no reconocido: {baseline}")


def simular_publicacion_5d_estricta(
    base_afp: pd.DataFrame,
    baseline: str,
    fin_train: pd.Timestamp,
    fin_valid: pd.Timestamp,
) -> pd.DataFrame:
    cuotas = (
        base_afp[["fecha_cuota", "cuota_sbs", "retorno_cuota"]]
        .drop_duplicates("fecha_cuota", keep="last")
        .sort_values("fecha_cuota")
        .reset_index(drop=True)
    )

    resultados = []

    for _, objetivo in cuotas.iterrows():
        fecha_obj = pd.Timestamp(objetivo["fecha_cuota"])
        corte = fecha_obj - pd.Timedelta(days=RETRASO_PUBLICACION_DIAS)

        visibles = cuotas[cuotas["fecha_cuota"].le(corte)].copy()
        if visibles.empty:
            continue

        ancla = visibles.iloc[-1]
        fecha_ancla = pd.Timestamp(ancla["fecha_cuota"])

        ocultas = cuotas[
            cuotas["fecha_cuota"].gt(fecha_ancla)
            & cuotas["fecha_cuota"].le(fecha_obj)
        ].copy()

        if ocultas.empty:
            continue

        historia = visibles["retorno_cuota"].dropna().astype(float).tolist()

        if baseline == "MEDIA_EXPANSIVA" and len(historia) < MIN_EXPANDING:
            continue
        if baseline == "MEDIA_MOVIL_20" and len(historia) < VENTANA_MEDIA:
            continue
        if baseline == "PERSISTENCIA_1D" and len(historia) < 1:
            continue

        pred_ocultas = []
        historia_recursiva = historia.copy()

        for _ in range(len(ocultas)):
            pred = siguiente_prediccion_recursiva(
                baseline,
                historia_recursiva,
            )
            pred_ocultas.append(pred)
            historia_recursiva.append(pred)

        cuota_ancla = float(ancla["cuota_sbs"])
        cuota_real = float(objetivo["cuota_sbs"])
        ret_est_acum = float(np.prod(1.0 + np.asarray(pred_ocultas)) - 1.0)
        ret_real_acum = float(cuota_real / cuota_ancla - 1.0)
        cuota_est = float(cuota_ancla * (1.0 + ret_est_acum))
        error_pct = float(cuota_est / cuota_real - 1.0)

        resultados.append(
            {
                "afp": str(base_afp["afp"].iloc[0]),
                "baseline": baseline,
                "fecha_hoy_simulada": fecha_obj,
                "segmento": segmento(fecha_obj, fin_train, fin_valid),
                "fecha_ultima_cuota_visible": fecha_ancla,
                "cuotas_ocultas_estimadas": int(len(ocultas)),
                "cuota_ultima_visible": cuota_ancla,
                "cuota_estimada_hoy": cuota_est,
                "cuota_real_hoy": cuota_real,
                "error_pct": error_pct,
                "error_abs_pct": abs(error_pct),
                "retorno_estimado_acumulado": ret_est_acum,
                "retorno_real_acumulado": ret_real_acum,
            }
        )

    return pd.DataFrame(resultados)


def metricas_5d(g: pd.DataFrame) -> dict[str, float]:
    if g.empty:
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

    pred = g["retorno_estimado_acumulado"].to_numpy(float)
    real = g["retorno_real_acumulado"].to_numpy(float)

    mascara_dir = np.abs(pred) > 1e-15
    cobertura = float(mascara_dir.mean() * 100.0)
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
        "n_publicacion": int(len(g)),
        "mape_cuota_5d_pct": float(g["error_abs_pct"].mean() * 100.0),
        "mediana_error_abs_5d_pct": float(g["error_abs_pct"].median() * 100.0),
        "p90_error_abs_5d_pct": float(g["error_abs_pct"].quantile(0.90) * 100.0),
        "error_maximo_abs_5d_pct": float(g["error_abs_pct"].max() * 100.0),
        "sesgo_5d_pct": float(g["error_pct"].mean() * 100.0),
        "correlacion_retorno_acumulado": correlacion,
        "direccion_acumulada_pct": direccion,
        "cobertura_direccional_acumulada_pct": cobertura,
    }


def evaluar_publicacion(
    base: pd.DataFrame,
    fin_train: pd.Timestamp,
    fin_valid: pd.Timestamp,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    sims = []
    mets = []

    for afp in AFPS:
        base_afp = base[base["afp"].eq(afp)].copy()

        for baseline in BASELINES:
            sim = simular_publicacion_5d_estricta(
                base_afp,
                baseline,
                fin_train,
                fin_valid,
            )
            sims.append(sim)

            for seg in ["entrenamiento", "validacion", "prueba"]:
                mets.append(
                    {
                        "afp": afp,
                        "baseline": baseline,
                        "segmento": seg,
                        **metricas_5d(sim[sim["segmento"].eq(seg)]),
                    }
                )

    return pd.concat(sims, ignore_index=True), pd.DataFrame(mets)


def agregar_referencias(
    diarias: pd.DataFrame,
    cuota: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    ref_mae = (
        diarias[diarias["baseline"].eq("RETORNO_CERO")]
        [["afp", "segmento", "mae"]]
        .rename(columns={"mae": "mae_retorno_cero"})
    )
    diarias = diarias.merge(ref_mae, on=["afp", "segmento"], how="left")
    diarias["mejora_mae_vs_cero_pct"] = (
        (diarias["mae_retorno_cero"] - diarias["mae"])
        / diarias["mae_retorno_cero"]
        * 100.0
    )
    diarias["ranking_mae"] = diarias.groupby(
        ["afp", "segmento"]
    )["mae"].rank(method="min", ascending=True)

    ref_mape = (
        cuota[cuota["baseline"].eq("RETORNO_CERO")]
        [["afp", "segmento", "mape_cuota_5d_pct"]]
        .rename(columns={"mape_cuota_5d_pct": "mape_cero_pct"})
    )
    cuota = cuota.merge(ref_mape, on=["afp", "segmento"], how="left")
    cuota["mejora_mape_vs_cero_pct"] = (
        (cuota["mape_cero_pct"] - cuota["mape_cuota_5d_pct"])
        / cuota["mape_cero_pct"]
        * 100.0
    )
    cuota["ranking_mape"] = cuota.groupby(
        ["afp", "segmento"]
    )["mape_cuota_5d_pct"].rank(method="min", ascending=True)

    return diarias, cuota


def guardar_figura(ruta: Path) -> None:
    plt.tight_layout()
    plt.savefig(ruta, dpi=160, bbox_inches="tight")
    plt.close()


def graficos(diarias: pd.DataFrame, cuota: pd.DataFrame, carpeta: Path) -> None:
    carpeta.mkdir(parents=True, exist_ok=True)

    for afp in AFPS:
        for seg in ["entrenamiento", "validacion", "prueba"]:
            d = diarias[
                diarias["afp"].eq(afp)
                & diarias["segmento"].eq(seg)
            ].sort_values("mae")

            x = np.arange(len(d))
            ancho = 0.36
            plt.figure(figsize=(10, 5))
            plt.bar(x - ancho / 2, d["mae"], width=ancho, label="MAE")
            plt.bar(x + ancho / 2, d["rmse"], width=ancho, label="RMSE")
            plt.xticks(x, d["baseline"], rotation=25, ha="right")
            plt.ylabel("Error del retorno")
            plt.title(f"Baselines diarios — {seg} — {afp}")
            plt.legend()
            guardar_figura(
                carpeta / f"01_mae_rmse_{seg}_{afp.lower()}.png"
            )

            q = cuota[
                cuota["afp"].eq(afp)
                & cuota["segmento"].eq(seg)
            ].sort_values("mape_cuota_5d_pct")

            x = np.arange(len(q))
            plt.figure(figsize=(10, 5))
            plt.bar(x - ancho / 2, q["mape_cuota_5d_pct"], width=ancho, label="MAPE")
            plt.bar(x + ancho / 2, q["p90_error_abs_5d_pct"], width=ancho, label="P90")
            plt.xticks(x, q["baseline"], rotation=25, ha="right")
            plt.ylabel("Porcentaje")
            plt.title(f"Publicación SBS estricta — {seg} — {afp}")
            plt.legend()
            guardar_figura(
                carpeta / f"02_mape_p90_{seg}_{afp.lower()}.png"
            )


def imprimir_segmento(
    titulo: str,
    df: pd.DataFrame,
    seg: str,
    columnas: list[str],
    ranking: str,
) -> None:
    print(f"\n{titulo} — {seg.upper()}")
    print("-" * 140)
    print(
        df[df["segmento"].eq(seg)]
        [columnas]
        .sort_values(["afp", ranking])
        .to_string(index=False)
    )


def main() -> None:
    raiz = Path(__file__).resolve().parents[1]
    processed = raiz / "data" / "processed"
    carpeta_graficos = processed / "graficos_modelo63_corregido"

    fin_train, fin_valid = cargar_division(processed)
    base = cargar_base(processed)

    pred_diarias = predicciones_diarias_un_paso(
        base, fin_train, fin_valid
    )
    met_diarias = evaluar_diarias(pred_diarias)

    sim_5d, met_5d = evaluar_publicacion(
        base, fin_train, fin_valid
    )

    met_diarias, met_5d = agregar_referencias(
        met_diarias, met_5d
    )

    graficos(met_diarias, met_5d, carpeta_graficos)

    rutas = {
        "pred_diarias": processed / "ca0001_modelo63_corregido_predicciones_diarias.csv",
        "met_diarias": processed / "ca0001_modelo63_corregido_metricas_diarias.csv",
        "sim_5d": processed / "ca0001_modelo63_corregido_simulacion_publicacion_5d.csv",
        "met_5d": processed / "ca0001_modelo63_corregido_metricas_publicacion_5d.csv",
        "resumen_json": processed / "ca0001_modelo63_corregido_resumen.json",
    }

    pred_diarias.to_csv(
        rutas["pred_diarias"], index=False, encoding="utf-8-sig", date_format="%Y-%m-%d"
    )
    met_diarias.to_csv(
        rutas["met_diarias"], index=False, encoding="utf-8-sig"
    )
    sim_5d.to_csv(
        rutas["sim_5d"], index=False, encoding="utf-8-sig", date_format="%Y-%m-%d"
    )
    met_5d.to_csv(
        rutas["met_5d"], index=False, encoding="utf-8-sig"
    )

    resumen = {
        "version": "modelo63_corregido_sin_fuga_de_informacion",
        "correccion_clave": (
            "En la simulación de retraso SBS, cada pronóstico usa solamente "
            "retornos visibles hasta la fecha de corte. Los días ocultos se "
            "generan recursivamente y nunca usan retornos oficiales ocultos."
        ),
        "fin_entrenamiento_60pct": str(fin_train.date()),
        "fin_validacion_20pct": str(fin_valid.date()),
    }
    rutas["resumen_json"].write_text(
        json.dumps(resumen, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    cols_diarias = [
        "afp", "baseline", "n", "mae", "rmse", "r2", "sesgo",
        "correlacion", "direccion_diaria_pct",
        "mejora_mae_vs_cero_pct", "ranking_mae",
    ]
    cols_5d = [
        "afp", "baseline", "n_publicacion",
        "mape_cuota_5d_pct", "mediana_error_abs_5d_pct",
        "p90_error_abs_5d_pct", "error_maximo_abs_5d_pct",
        "sesgo_5d_pct", "direccion_acumulada_pct",
        "mejora_mape_vs_cero_pct", "ranking_mape",
    ]

    print("\nMÓDULO 63 CORREGIDO — MÉTRICAS ANTES DEL ENTRENAMIENTO")
    print("=" * 140)
    print(
        "Corrección aplicada: la simulación de publicación SBS no utiliza "
        "ningún retorno oficial oculto."
    )
    print(
        f"60 % entrenamiento hasta {fin_train.date()} | "
        f"20 % validación hasta {fin_valid.date()} | resto prueba"
    )

    for seg in ["entrenamiento", "validacion", "prueba"]:
        imprimir_segmento(
            "MÉTRICAS DIARIAS DE UN PASO",
            met_diarias,
            seg,
            cols_diarias,
            "ranking_mae",
        )

    for seg in ["entrenamiento", "validacion", "prueba"]:
        imprimir_segmento(
            "MÉTRICAS DE CUOTA CON RETRASO SBS DE CINCO DÍAS",
            met_5d,
            seg,
            cols_5d,
            "ranking_mape",
        )

    print("\nARCHIVOS CREADOS")
    print("-" * 140)
    for ruta in rutas.values():
        print(f" - {ruta.resolve()}")
    print(f" - {carpeta_graficos.resolve()}")

    print(
        "\nIMPORTANTE:\n"
        "- Las métricas diarias de un paso son benchmarks descriptivos.\n"
        "- Las métricas de publicación de cinco días son las operativas.\n"
        "- Un baseline solo es útil si supera al retorno cero sin usar "
        "información que en la fecha simulada aún no estaba publicada."
    )


if __name__ == "__main__":
    main()
