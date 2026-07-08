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
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score


warnings.filterwarnings("ignore")

AFPS = ["Habitat", "Integra", "Prima", "Profuturo"]
PESOS_PARES = np.round(np.arange(0.0, 1.0001, 0.05), 2)
PESOS_TRIPLES = np.round(np.arange(0.0, 1.0001, 0.10), 2)


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


def normalizar_simulaciones(df: pd.DataFrame) -> pd.DataFrame:
    x = df.copy()

    for col in ["afp", "modelo", "tarea", "segmento"]:
        x[col] = x[col].astype(str).str.strip()

    for col in ["fecha_hoy_simulada", "fecha_ultima_cuota_visible"]:
        x[col] = pd.to_datetime(x[col], errors="coerce").dt.normalize()

    numericas = [
        "cuota_ultima_visible",
        "cuota_real_hoy",
        "cuota_estimada_hoy",
        "retorno_acumulado_real",
        "retorno_acumulado_estimado",
        "error_pct",
        "error_abs_pct",
    ]
    for col in numericas:
        x[col] = pd.to_numeric(x[col], errors="coerce")

    return x.dropna(
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


def metricas(y_real: np.ndarray, y_pred: np.ndarray, cuota_ancla: np.ndarray,
             cuota_real: np.ndarray) -> dict[str, float]:
    y = np.asarray(y_real, dtype=float)
    p = np.asarray(y_pred, dtype=float)
    a = np.asarray(cuota_ancla, dtype=float)
    q = np.asarray(cuota_real, dtype=float)

    mascara = np.isfinite(y) & np.isfinite(p) & np.isfinite(a) & np.isfinite(q)
    y, p, a, q = y[mascara], p[mascara], a[mascara], q[mascara]

    if len(y) == 0:
        return {
            "n": 0,
            "mae_retorno": np.nan,
            "rmse_retorno": np.nan,
            "r2_retorno": np.nan,
            "correlacion_retorno": np.nan,
            "direccion_pct": np.nan,
            "mape_cuota_pct": np.nan,
            "mediana_error_abs_pct": np.nan,
            "p90_error_abs_pct": np.nan,
            "error_maximo_abs_pct": np.nan,
            "sesgo_cuota_pct": np.nan,
        }

    cuota_est = a * (1.0 + p)
    error_pct = cuota_est / q - 1.0
    error_abs = np.abs(error_pct)
    mascara_dir = np.abs(p) > 1e-15

    correlacion = (
        float(np.corrcoef(y, p)[0, 1])
        if np.std(y) > 0 and np.std(p) > 0
        else np.nan
    )

    direccion = (
        float((np.sign(y[mascara_dir]) == np.sign(p[mascara_dir])).mean() * 100.0)
        if mascara_dir.any()
        else np.nan
    )

    return {
        "n": int(len(y)),
        "mae_retorno": float(mean_absolute_error(y, p)),
        "rmse_retorno": float(mean_squared_error(y, p) ** 0.5),
        "r2_retorno": float(r2_score(y, p)) if len(y) > 1 else np.nan,
        "correlacion_retorno": correlacion,
        "direccion_pct": direccion,
        "mape_cuota_pct": float(error_abs.mean() * 100.0),
        "mediana_error_abs_pct": float(np.median(error_abs) * 100.0),
        "p90_error_abs_pct": float(np.quantile(error_abs, 0.90) * 100.0),
        "error_maximo_abs_pct": float(error_abs.max() * 100.0),
        "sesgo_cuota_pct": float(error_pct.mean() * 100.0),
    }


def construir_panel(df: pd.DataFrame, afp: str, segmento: str,
                    modelos: list[str]) -> pd.DataFrame:
    base_cols = [
        "fecha_hoy_simulada",
        "fecha_ultima_cuota_visible",
        "cuota_ultima_visible",
        "cuota_real_hoy",
        "retorno_acumulado_real",
    ]

    panel = None

    for modelo in modelos:
        bloque = (
            df[
                df["afp"].eq(afp)
                & df["segmento"].eq(segmento)
                & df["modelo"].eq(modelo)
            ][base_cols + ["retorno_acumulado_estimado"]]
            .drop_duplicates("fecha_hoy_simulada", keep="last")
            .rename(
                columns={
                    "retorno_acumulado_estimado": f"pred__{modelo}"
                }
            )
        )

        if panel is None:
            panel = bloque
        else:
            panel = panel.merge(
                bloque[
                    ["fecha_hoy_simulada", f"pred__{modelo}"]
                ],
                on="fecha_hoy_simulada",
                how="inner",
                validate="one_to_one",
            )

    return panel if panel is not None else pd.DataFrame()


def evaluar_prediccion(panel: pd.DataFrame, pred: np.ndarray) -> dict[str, float]:
    return metricas(
        panel["retorno_acumulado_real"].to_numpy(float),
        pred,
        panel["cuota_ultima_visible"].to_numpy(float),
        panel["cuota_real_hoy"].to_numpy(float),
    )


def candidatos_pares(modelo_ew: str, otros: list[str]) -> list[dict[str, Any]]:
    candidatos = []

    for modelo in otros:
        for peso_ew in PESOS_PARES:
            candidatos.append(
                {
                    "tipo_ensemble": "PAR",
                    "modelos": [modelo_ew, modelo],
                    "pesos": [float(peso_ew), float(1.0 - peso_ew)],
                    "nombre": (
                        f"BLEND_{modelo_ew}_{modelo}"
                        f"_W{peso_ew:.2f}_{1.0-peso_ew:.2f}"
                    ),
                }
            )

    return candidatos


def candidatos_triples(modelo_ew: str, modelo_et: str,
                       modelo_ridge: str) -> list[dict[str, Any]]:
    candidatos = []

    for w_ew in PESOS_TRIPLES:
        for w_et in PESOS_TRIPLES:
            w_ridge = round(1.0 - w_ew - w_et, 10)
            if w_ridge < -1e-9:
                continue
            if w_ridge < 0:
                w_ridge = 0.0

            candidatos.append(
                {
                    "tipo_ensemble": "TRIPLE",
                    "modelos": [modelo_ew, modelo_et, modelo_ridge],
                    "pesos": [float(w_ew), float(w_et), float(w_ridge)],
                    "nombre": (
                        f"BLEND3_W{w_ew:.2f}_{w_et:.2f}_{w_ridge:.2f}"
                    ),
                }
            )

    return candidatos


def combinar(panel: pd.DataFrame, modelos: list[str],
             pesos: list[float]) -> np.ndarray:
    pred = np.zeros(len(panel), dtype=float)

    for modelo, peso in zip(modelos, pesos):
        pred += peso * panel[f"pred__{modelo}"].to_numpy(float)

    return pred


def diebold_mariano(perdida_modelo: np.ndarray,
                    perdida_referencia: np.ndarray,
                    max_lag: int = 5) -> dict[str, float]:
    modelo = np.asarray(perdida_modelo, dtype=float)
    ref = np.asarray(perdida_referencia, dtype=float)
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
    centrado = d - media
    gamma0 = float(np.dot(centrado, centrado) / n)
    var_hac = gamma0

    for lag in range(1, min(max_lag, n - 1) + 1):
        gamma = float(np.dot(centrado[lag:], centrado[:-lag]) / n)
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
    pvalor = float(2.0 * (1.0 - stats.norm.cdf(abs(estadistico))))

    return {
        "n_dm": int(n),
        "diferencia_media_perdida": media,
        "dm_estadistico": float(estadistico),
        "dm_pvalor": pvalor,
    }


def holm(pvalores: pd.Series) -> pd.Series:
    p = pvalores.astype(float)
    validos = p.dropna().sort_values()
    m = len(validos)
    salida = pd.Series(np.nan, index=p.index, dtype=float)

    max_previo = 0.0
    for posicion, (indice, valor) in enumerate(validos.items(), start=1):
        ajustado = min(1.0, (m - posicion + 1) * valor)
        ajustado = max(max_previo, ajustado)
        salida.loc[indice] = ajustado
        max_previo = ajustado

    return salida


def error_abs_cuota(panel: pd.DataFrame, pred: np.ndarray) -> np.ndarray:
    cuota_est = panel["cuota_ultima_visible"].to_numpy(float) * (1.0 + pred)
    return np.abs(
        cuota_est / panel["cuota_real_hoy"].to_numpy(float) - 1.0
    )


def metricas_subperiodos(panel: pd.DataFrame, pred: np.ndarray,
                        afp: str, nombre: str) -> pd.DataFrame:
    x = panel.copy().sort_values("fecha_hoy_simulada").reset_index(drop=True)
    x["pred"] = pred
    x["cuartil"] = pd.qcut(
        np.arange(len(x)),
        q=4,
        labels=["Q1", "Q2", "Q3", "Q4"],
    )

    filas = []
    for cuartil, bloque in x.groupby("cuartil", observed=False):
        met = evaluar_prediccion(bloque, bloque["pred"].to_numpy(float))
        filas.append(
            {
                "afp": afp,
                "modelo": nombre,
                "subperiodo": str(cuartil),
                "fecha_inicio": bloque["fecha_hoy_simulada"].min(),
                "fecha_fin": bloque["fecha_hoy_simulada"].max(),
                **met,
            }
        )

    return pd.DataFrame(filas)


def guardar_figura(ruta: Path) -> None:
    plt.tight_layout()
    plt.savefig(ruta, dpi=160, bbox_inches="tight")
    plt.close()


def main() -> None:
    raiz = Path(__file__).resolve().parents[1]
    processed = raiz / "data" / "processed"
    graficos = processed / "graficos_modelo67"
    graficos.mkdir(parents=True, exist_ok=True)

    ruta = processed / "ca0001_modelo66_simulaciones_cuota.csv"
    if not ruta.exists():
        raise FileNotFoundError(f"No existe {ruta}")

    simulaciones = normalizar_simulaciones(leer_csv(ruta))

    resultados_validacion = []
    resultados_prueba = []
    predicciones_finales = []
    subperiodos_todos = []
    pesos_seleccionados = []
    dm_filas = []

    for afp in AFPS:
        modelos_afp = simulaciones[
            simulaciones["afp"].eq(afp)
            & simulaciones["segmento"].isin(["validacion", "prueba"])
        ]["modelo"].dropna().unique().tolist()

        modelos_ew = [m for m in modelos_afp if m.startswith("EW_RIDGE")]
        if not modelos_ew:
            raise RuntimeError(f"No se encontró EW Ridge para {afp}")
        modelo_ew = modelos_ew[0]

        preferidos = [
            "DIRECTO_EXTRA_TREES",
            "DIRECTO_RIDGE",
            "DIRECTO_GRADIENT_BOOSTING",
            "DIARIO_EXTRA_TREES",
            "DIARIO_GRADIENT_BOOSTING",
            "DIARIO_RIDGE",
        ]
        otros = [m for m in preferidos if m in modelos_afp]

        candidatos = candidatos_pares(modelo_ew, otros)

        if (
            "DIRECTO_EXTRA_TREES" in otros
            and "DIRECTO_RIDGE" in otros
        ):
            candidatos.extend(
                candidatos_triples(
                    modelo_ew,
                    "DIRECTO_EXTRA_TREES",
                    "DIRECTO_RIDGE",
                )
            )

        todos_modelos_panel = sorted(
            set(
                [modelo_ew]
                + [m for c in candidatos for m in c["modelos"]]
            )
        )

        panel_val = construir_panel(
            simulaciones, afp, "validacion", todos_modelos_panel
        )
        panel_test = construir_panel(
            simulaciones, afp, "prueba", todos_modelos_panel
        )

        if len(panel_val) < 100 or len(panel_test) < 100:
            raise RuntimeError(
                f"Panel insuficiente para {afp}: "
                f"validación={len(panel_val)}, prueba={len(panel_test)}"
            )

        for candidato in candidatos:
            pred_val = combinar(
                panel_val,
                candidato["modelos"],
                candidato["pesos"],
            )
            met = evaluar_prediccion(panel_val, pred_val)
            resultados_validacion.append(
                {
                    "afp": afp,
                    **candidato,
                    **met,
                }
            )

        tabla_val_afp = pd.DataFrame(
            [r for r in resultados_validacion if r["afp"] == afp]
        ).sort_values(
            [
                "mape_cuota_pct",
                "p90_error_abs_pct",
                "mae_retorno",
                "error_maximo_abs_pct",
            ]
        )

        ganador = tabla_val_afp.iloc[0].to_dict()
        pesos_seleccionados.append(
            {
                "afp": afp,
                "nombre": ganador["nombre"],
                "tipo_ensemble": ganador["tipo_ensemble"],
                "modelos": json.dumps(ganador["modelos"]),
                "pesos": json.dumps(ganador["pesos"]),
                "mape_validacion_pct": ganador["mape_cuota_pct"],
                "p90_validacion_pct": ganador["p90_error_abs_pct"],
            }
        )

        pred_test = combinar(
            panel_test,
            ganador["modelos"],
            ganador["pesos"],
        )
        met_test = evaluar_prediccion(panel_test, pred_test)

        resultados_prueba.append(
            {
                "afp": afp,
                "modelo": ganador["nombre"],
                "tipo_ensemble": ganador["tipo_ensemble"],
                "modelos": json.dumps(ganador["modelos"]),
                "pesos": json.dumps(ganador["pesos"]),
                **met_test,
            }
        )

        cuota_est = (
            panel_test["cuota_ultima_visible"].to_numpy(float)
            * (1.0 + pred_test)
        )
        error_pct = (
            cuota_est
            / panel_test["cuota_real_hoy"].to_numpy(float)
            - 1.0
        )

        detalle = panel_test.copy()
        detalle["afp"] = afp
        detalle["modelo_ensemble"] = ganador["nombre"]
        detalle["retorno_acumulado_estimado_ensemble"] = pred_test
        detalle["cuota_estimada_ensemble"] = cuota_est
        detalle["error_pct_ensemble"] = error_pct
        detalle["error_abs_pct_ensemble"] = np.abs(error_pct)
        predicciones_finales.append(detalle)

        subperiodos_todos.append(
            metricas_subperiodos(
                panel_test,
                pred_test,
                afp,
                ganador["nombre"],
            )
        )

        pred_ew = panel_test[f"pred__{modelo_ew}"].to_numpy(float)
        perdida_ens = error_abs_cuota(panel_test, pred_test)
        perdida_ew = error_abs_cuota(panel_test, pred_ew)

        dm_filas.append(
            {
                "afp": afp,
                "modelo": ganador["nombre"],
                "referencia": modelo_ew,
                **diebold_mariano(
                    perdida_ens,
                    perdida_ew,
                    max_lag=5,
                ),
            }
        )

        # Gráfico de cuota
        plt.figure(figsize=(12, 5))
        plt.plot(
            panel_test["fecha_hoy_simulada"],
            panel_test["cuota_real_hoy"],
            label="Cuota SBS",
        )
        plt.plot(
            panel_test["fecha_hoy_simulada"],
            cuota_est,
            label="Ensemble",
        )
        cuota_ew = (
            panel_test["cuota_ultima_visible"].to_numpy(float)
            * (1.0 + pred_ew)
        )
        plt.plot(
            panel_test["fecha_hoy_simulada"],
            cuota_ew,
            label="EW Ridge",
            alpha=0.75,
        )
        plt.ylabel("Valor cuota")
        plt.title(f"Ensemble vs EW Ridge — {afp}")
        plt.legend()
        guardar_figura(
            graficos / f"01_cuota_ensemble_{afp.lower()}.png"
        )

        # MAPE móvil 60 observaciones
        errores = pd.DataFrame(
            {
                "fecha": panel_test["fecha_hoy_simulada"].to_numpy(),
                "ensemble": perdida_ens * 100.0,
                "ew": perdida_ew * 100.0,
            }
        ).sort_values("fecha")
        errores["mape60_ensemble"] = (
            errores["ensemble"].rolling(60).mean()
        )
        errores["mape60_ew"] = errores["ew"].rolling(60).mean()

        plt.figure(figsize=(12, 5))
        plt.plot(
            errores["fecha"],
            errores["mape60_ensemble"],
            label="Ensemble",
        )
        plt.plot(
            errores["fecha"],
            errores["mape60_ew"],
            label="EW Ridge",
        )
        plt.ylabel("MAPE móvil de 60 observaciones (%)")
        plt.title(f"Estabilidad temporal del error — {afp}")
        plt.legend()
        guardar_figura(
            graficos / f"02_mape_movil_{afp.lower()}.png"
        )

    val_df = pd.DataFrame(resultados_validacion)
    prueba_df = pd.DataFrame(resultados_prueba)
    detalle_df = pd.concat(predicciones_finales, ignore_index=True)
    subperiodos_df = pd.concat(subperiodos_todos, ignore_index=True)
    pesos_df = pd.DataFrame(pesos_seleccionados)
    dm_df = pd.DataFrame(dm_filas)
    dm_df["pvalor_holm"] = holm(dm_df["dm_pvalor"])
    dm_df["supera_ew_con_evidencia"] = (
        dm_df["diferencia_media_perdida"].lt(0)
        & dm_df["pvalor_holm"].lt(0.05)
    )

    rutas = {
        "validacion": processed / "ca0001_modelo67_grid_ensembles_validacion.csv",
        "pesos": processed / "ca0001_modelo67_pesos_seleccionados.csv",
        "prueba": processed / "ca0001_modelo67_metricas_prueba.csv",
        "detalle": processed / "ca0001_modelo67_predicciones_prueba.csv",
        "subperiodos": processed / "ca0001_modelo67_estabilidad_subperiodos.csv",
        "dm": processed / "ca0001_modelo67_diebold_mariano_vs_ew.csv",
        "resumen": processed / "ca0001_modelo67_resumen.json",
    }

    val_df.to_csv(rutas["validacion"], index=False, encoding="utf-8-sig")
    pesos_df.to_csv(rutas["pesos"], index=False, encoding="utf-8-sig")
    prueba_df.to_csv(rutas["prueba"], index=False, encoding="utf-8-sig")
    detalle_df.to_csv(
        rutas["detalle"],
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
    dm_df.to_csv(rutas["dm"], index=False, encoding="utf-8-sig")

    resumen = {
        "version": "modelo67_ensembles_y_estabilidad",
        "metodologia": (
            "Los pesos se seleccionan únicamente con validación. "
            "La prueba audita MAPE, P90, R² acumulado, dirección y estabilidad "
            "por cuatro subperiodos."
        ),
        "pesos_seleccionados": pesos_df.to_dict(orient="records"),
        "metricas_prueba": prueba_df.to_dict(orient="records"),
        "graficos_generados": len(list(graficos.glob("*.png"))),
    }
    rutas["resumen"].write_text(
        json.dumps(resumen, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    print("\nMÓDULO 67 — ENSEMBLES Y ESTABILIDAD TEMPORAL")
    print("=" * 150)
    print(
        "Se combinan EW Ridge y los principales modelos directos/diarios. "
        "Los pesos se eligen solo con validación."
    )

    print("\nPESOS SELECCIONADOS")
    print("-" * 150)
    print(pesos_df.to_string(index=False))

    print("\nMÉTRICAS EN PRUEBA")
    print("-" * 150)
    print(
        prueba_df[
            [
                "afp",
                "modelo",
                "n",
                "mae_retorno",
                "rmse_retorno",
                "r2_retorno",
                "correlacion_retorno",
                "direccion_pct",
                "mape_cuota_pct",
                "mediana_error_abs_pct",
                "p90_error_abs_pct",
                "error_maximo_abs_pct",
                "sesgo_cuota_pct",
            ]
        ].to_string(index=False)
    )

    print("\nDIEBOLD-MARIANO CONTRA EW RIDGE")
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
                "supera_ew_con_evidencia",
            ]
        ].to_string(index=False)
    )

    print("\nESTABILIDAD POR CUARTILES DEL PERIODO DE PRUEBA")
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
            ]
        ].to_string(index=False)
    )

    print("\nARCHIVOS CREADOS")
    print("-" * 150)
    for ruta in rutas.values():
        print(f" - {ruta.resolve()}")
    print(f" - {graficos.resolve()}")

    print(
        "\nLECTURA:\n"
        "- Un peso EW igual a 1 significa que la validación rechazó combinar.\n"
        "- Un peso intermedio indica que el modelo directo aporta información "
        "complementaria.\n"
        "- La mejora debe mantenerse en prueba y, de preferencia, en varios "
        "subperiodos.\n"
        "- supera_ew_con_evidencia=True exige menor error y p-valor Holm < 0.05."
    )


if __name__ == "__main__":
    main()
