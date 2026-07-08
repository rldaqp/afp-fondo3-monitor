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

CATEGORIAS_ACCIONES = {
    "ACCIONES_PERU",
    "ACCIONES_MINERAS",
}

LAGS_ACCIONES = [0, 1, 2, 3]
ALPHAS_RIDGE = [0.001, 0.01, 0.1, 1.0, 10.0, 100.0]
ALPHAS_EW = [0.001, 0.1, 10.0]
VIDAS_MEDIAS = [60, 120, 250, 500]

MAX_ACCIONES_AGREGADAS = 4
MAX_CANDIDATOS_SCREEN = 28
UMBRAL_REDUNDANCIA = 0.95
MEJORA_MINIMA_MAPE_PUNTOS = 0.002
TOLERANCIA_P90_PUNTOS = 0.05
RETRASO_PUBLICACION_DIAS = 5
MIN_FILAS = 500


@dataclass
class ModeloRidge:
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
    ultimo_error: Exception | None = None

    for argumentos in intentos:
        try:
            return pd.read_csv(ruta, **argumentos)
        except Exception as exc:
            ultimo_error = exc

    raise RuntimeError(f"No se pudo leer {ruta}: {ultimo_error}")


def cargar_division(processed: Path) -> tuple[pd.Timestamp, pd.Timestamp]:
    df = leer_csv(processed / "ca0001_modelo50_division_temporal.csv")
    df["fecha_fin"] = pd.to_datetime(df["fecha_fin"], errors="coerce")

    train = df[
        df["segmento"].astype(str).eq("entrenamiento_descubrimiento")
    ]
    valid = df[df["segmento"].astype(str).eq("validacion")]

    if train.empty or valid.empty:
        raise ValueError("No se encontró la división temporal del módulo 50.")

    return (
        pd.Timestamp(train["fecha_fin"].iloc[0]).normalize(),
        pd.Timestamp(valid["fecha_fin"].iloc[0]).normalize(),
    )


def cargar_fuentes(
    processed: Path,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    base = leer_csv(processed / "ca0001_modelo56_base_alineada.csv")
    factores = leer_csv(processed / "ca0001_modelo69_factores_ampliados.csv")
    catalogo = leer_csv(processed / "ca0001_modelo69_catalogo_factores.csv")
    canasta = leer_csv(processed / "ca0001_modelo70_canasta_seleccionada.csv")

    base["fecha_cuota"] = pd.to_datetime(
        base["fecha_cuota"], errors="coerce"
    ).dt.normalize()
    factores["fecha_cuota"] = pd.to_datetime(
        factores["fecha_cuota"], errors="coerce"
    ).dt.normalize()

    base["cuota_sbs"] = pd.to_numeric(base["cuota_sbs"], errors="coerce")
    base["retorno_cuota"] = pd.to_numeric(
        base["retorno_cuota"], errors="coerce"
    )

    for columna in factores.columns:
        if columna != "fecha_cuota":
            factores[columna] = pd.to_numeric(
                factores[columna], errors="coerce"
            )

    canasta["lag"] = pd.to_numeric(
        canasta["lag"], errors="coerce"
    ).astype("Int64")

    return base, factores, catalogo, canasta


def preparar_panel(
    base: pd.DataFrame,
    factores: pd.DataFrame,
    afp: str,
) -> pd.DataFrame:
    cuota = (
        base[base["afp"].astype(str).eq(afp)]
        [["fecha_cuota", "cuota_sbs", "retorno_cuota"]]
        .dropna(subset=["fecha_cuota", "cuota_sbs"])
        .drop_duplicates("fecha_cuota", keep="last")
        .sort_values("fecha_cuota")
    )

    return (
        cuota.merge(
            factores,
            on="fecha_cuota",
            how="left",
            validate="one_to_one",
        )
        .sort_values("fecha_cuota")
        .reset_index(drop=True)
    )


def nombre_feature(factor: str, lag: int) -> str:
    return f"{factor}__lag{lag}"


def materializar(
    panel: pd.DataFrame,
    specs: list[dict[str, Any]],
) -> tuple[pd.DataFrame, list[str]]:
    x = panel.copy()
    columnas: list[str] = []

    for spec in specs:
        factor = str(spec["factor"])
        lag = int(spec["lag"])
        columna = nombre_feature(factor, lag)

        if factor not in x.columns:
            raise KeyError(f"No existe el factor {factor}")

        x[columna] = pd.to_numeric(
            x[factor], errors="coerce"
        ).shift(lag)
        columnas.append(columna)

    x[columnas] = (
        x[columnas]
        .replace([np.inf, -np.inf], np.nan)
        .fillna(0.0)
    )

    return x, columnas


def pesos_exponenciales(n: int, half_life: int) -> np.ndarray:
    edades = np.arange(n - 1, -1, -1, dtype=float)
    return np.power(0.5, edades / float(half_life))


def ajustar(
    X: pd.DataFrame,
    y: pd.Series,
    columnas: list[str],
    familia: str,
    alpha: float,
    half_life: int | None,
) -> ModeloRidge:
    mascara = y.notna()
    Xf = X.loc[mascara, columnas]
    yf = y.loc[mascara].astype(float)

    if len(yf) < MIN_FILAS:
        raise ValueError(f"Muestra insuficiente: {len(yf)}")

    scaler = StandardScaler()
    z = scaler.fit_transform(Xf)

    ridge = Ridge(alpha=float(alpha))

    if familia == "EW_RIDGE":
        if half_life is None:
            raise ValueError("EW_RIDGE requiere half_life.")
        ridge.fit(
            z,
            yf,
            sample_weight=pesos_exponenciales(
                len(yf), int(half_life)
            ),
        )
    else:
        ridge.fit(z, yf)

    return ModeloRidge(
        scaler=scaler,
        ridge=ridge,
        familia=familia,
        alpha=float(alpha),
        half_life=half_life,
        columnas=columnas,
    )


def predecir_panel(
    panel_features: pd.DataFrame,
    modelo: ModeloRidge,
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
    filas: list[dict[str, Any]] = []

    indices_objetivo = p.index[
        p["fecha_cuota"].ge(fecha_inicio)
        & p["fecha_cuota"].le(fecha_fin)
    ].tolist()

    for i in indices_objetivo:
        fecha_objetivo = pd.Timestamp(p.loc[i, "fecha_cuota"])
        corte_visible = fecha_objetivo - pd.Timedelta(
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

        retornos = p.loc[
            ancla + 1 : i, "retorno_estimado"
        ].astype(float)

        retorno_estimado = float(
            np.prod(1.0 + retornos.to_numpy()) - 1.0
        )
        cuota_ancla = float(p.loc[ancla, "cuota_sbs"])
        cuota_real = float(p.loc[i, "cuota_sbs"])
        cuota_estimada = float(
            cuota_ancla * (1.0 + retorno_estimado)
        )
        retorno_real = float(
            cuota_real / cuota_ancla - 1.0
        )
        error_pct = float(
            cuota_estimada / cuota_real - 1.0
        )

        filas.append(
            {
                "fecha_hoy_simulada": fecha_objetivo,
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


def metricas_diarias(pred: pd.DataFrame) -> dict[str, float]:
    x = pred.dropna(
        subset=["retorno_cuota", "retorno_estimado"]
    )

    if x.empty:
        return {
            "n_diario": 0,
            "mae_diario": np.nan,
            "rmse_diario": np.nan,
            "r2_diario": np.nan,
            "correlacion_diaria": np.nan,
            "direccion_diaria_pct": np.nan,
        }

    real = x["retorno_cuota"].to_numpy(float)
    estimado = x["retorno_estimado"].to_numpy(float)

    correlacion = (
        float(np.corrcoef(real, estimado)[0, 1])
        if np.std(real) > 0 and np.std(estimado) > 0
        else np.nan
    )

    mascara = np.abs(estimado) > 1e-15
    direccion = (
        float(
            (
                np.sign(real[mascara])
                == np.sign(estimado[mascara])
            ).mean()
            * 100.0
        )
        if mascara.any()
        else np.nan
    )

    return {
        "n_diario": int(len(x)),
        "mae_diario": float(
            mean_absolute_error(real, estimado)
        ),
        "rmse_diario": float(
            mean_squared_error(real, estimado) ** 0.5
        ),
        "r2_diario": float(r2_score(real, estimado)),
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
    estimado = sim["retorno_acumulado_estimado"].to_numpy(float)

    correlacion = (
        float(np.corrcoef(real, estimado)[0, 1])
        if np.std(real) > 0 and np.std(estimado) > 0
        else np.nan
    )

    mascara = np.abs(estimado) > 1e-15
    direccion = (
        float(
            (
                np.sign(real[mascara])
                == np.sign(estimado[mascara])
            ).mean()
            * 100.0
        )
        if mascara.any()
        else np.nan
    )

    return {
        "n_publicacion": int(len(sim)),
        "mape_cuota_pct": float(
            sim["error_abs_pct"].mean() * 100.0
        ),
        "mediana_error_abs_pct": float(
            sim["error_abs_pct"].median() * 100.0
        ),
        "p90_error_abs_pct": float(
            sim["error_abs_pct"].quantile(0.90) * 100.0
        ),
        "error_maximo_abs_pct": float(
            sim["error_abs_pct"].max() * 100.0
        ),
        "sesgo_cuota_pct": float(
            sim["error_pct"].mean() * 100.0
        ),
        "correlacion_retorno_acumulado": correlacion,
        "direccion_acumulada_pct": direccion,
    }


def evaluar(
    panel: pd.DataFrame,
    specs: list[dict[str, Any]],
    fin_train: pd.Timestamp,
    fin_valid: pd.Timestamp,
) -> tuple[dict[str, Any], pd.DataFrame]:
    pf, columnas = materializar(panel, specs)
    train = pf[pf["fecha_cuota"].le(fin_train)]
    valid = pf[
        pf["fecha_cuota"].gt(fin_train)
        & pf["fecha_cuota"].le(fin_valid)
    ]

    configuraciones: list[dict[str, Any]] = []

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

    for cfg in configuraciones:
        modelo = ajustar(
            train,
            train["retorno_cuota"],
            columnas,
            cfg["familia"],
            cfg["alpha"],
            cfg["half_life"],
        )

        pred = predecir_panel(pf, modelo)
        pred_valid = pred[
            pred["fecha_cuota"].gt(fin_train)
            & pred["fecha_cuota"].le(fin_valid)
        ]
        sim = simular_publicacion(
            pred,
            pd.Timestamp(valid["fecha_cuota"].min()),
            fin_valid,
        )

        filas.append(
            {
                **cfg,
                **metricas_diarias(pred_valid),
                **metricas_cuota(sim),
            }
        )

    tabla = pd.DataFrame(filas).sort_values(
        [
            "mape_cuota_pct",
            "p90_error_abs_pct",
            "mae_diario",
        ]
    ).reset_index(drop=True)

    return tabla.iloc[0].to_dict(), tabla


def evaluar_prueba(
    panel: pd.DataFrame,
    specs: list[dict[str, Any]],
    cfg: dict[str, Any],
    fin_valid: pd.Timestamp,
) -> tuple[
    dict[str, Any],
    pd.DataFrame,
    ModeloRidge,
]:
    pf, columnas = materializar(panel, specs)
    train_valid = pf[pf["fecha_cuota"].le(fin_valid)]
    test = pf[pf["fecha_cuota"].gt(fin_valid)]

    modelo = ajustar(
        train_valid,
        train_valid["retorno_cuota"],
        columnas,
        str(cfg["familia"]),
        float(cfg["alpha"]),
        (
            int(cfg["half_life"])
            if pd.notna(cfg["half_life"])
            else None
        ),
    )

    pred = predecir_panel(pf, modelo)
    pred_test = pred[pred["fecha_cuota"].gt(fin_valid)]
    sim = simular_publicacion(
        pred,
        pd.Timestamp(test["fecha_cuota"].min()),
        pd.Timestamp(test["fecha_cuota"].max()),
    )

    return {
        **metricas_diarias(pred_test),
        **metricas_cuota(sim),
    }, sim, modelo


def calcular_screen_train(
    panel: pd.DataFrame,
    candidatos: list[dict[str, Any]],
    fin_train: pd.Timestamp,
) -> pd.DataFrame:
    filas = []
    train = panel[panel["fecha_cuota"].le(fin_train)].copy()

    for spec in candidatos:
        factor = spec["factor"]
        lag = int(spec["lag"])
        x = pd.to_numeric(
            train[factor], errors="coerce"
        ).shift(lag)
        par = pd.concat(
            [train["retorno_cuota"], x],
            axis=1,
        ).dropna()

        if len(par) < 1000:
            continue

        spearman = float(
            par.iloc[:, 0].corr(
                par.iloc[:, 1], method="spearman"
            )
        )
        pearson = float(
            par.iloc[:, 0].corr(
                par.iloc[:, 1], method="pearson"
            )
        )

        filas.append(
            {
                **spec,
                "n_train": int(len(par)),
                "spearman_train": spearman,
                "pearson_train": pearson,
                "abs_spearman_train": abs(spearman),
            }
        )

    return (
        pd.DataFrame(filas)
        .sort_values(
            ["abs_spearman_train", "factor"],
            ascending=[False, True],
        )
        .reset_index(drop=True)
    )


def max_correlacion(
    panel: pd.DataFrame,
    candidato: dict[str, Any],
    seleccionados: list[dict[str, Any]],
    fin_train: pd.Timestamp,
) -> float:
    specs = seleccionados + [candidato]
    pf, columnas = materializar(panel, specs)
    train = pf[pf["fecha_cuota"].le(fin_train)]
    col_candidato = columnas[-1]

    maximo = 0.0
    for columna in columnas[:-1]:
        corr = train[[columna, col_candidato]].corr().iloc[0, 1]
        if pd.notna(corr):
            maximo = max(maximo, abs(float(corr)))

    return maximo


def seleccionar_acciones(
    panel: pd.DataFrame,
    base_specs: list[dict[str, Any]],
    candidatos: list[dict[str, Any]],
    fin_train: pd.Timestamp,
    fin_valid: pd.Timestamp,
    afp: str,
) -> tuple[
    list[dict[str, Any]],
    dict[str, Any],
    pd.DataFrame,
]:
    seleccionados = [dict(x) for x in base_specs]
    cfg_actual, _ = evaluar(
        panel, seleccionados, fin_train, fin_valid
    )
    disponibles = [dict(x) for x in candidatos]

    trazas = [
        {
            "afp": afp,
            "paso": 0,
            "accion": "BASE_MODELO70",
            "factor": "",
            "lag": np.nan,
            "max_corr_con_canasta": np.nan,
            "mape_antes_pct": np.nan,
            "mape_despues_pct": cfg_actual["mape_cuota_pct"],
            "mejora_mape_puntos": np.nan,
            "p90_despues_pct": cfg_actual["p90_error_abs_pct"],
            "aceptado": True,
        }
    ]

    for paso in range(1, MAX_ACCIONES_AGREGADAS + 1):
        evaluados = []

        for cand in disponibles:
            corr = max_correlacion(
                panel,
                cand,
                seleccionados,
                fin_train,
            )

            if corr >= UMBRAL_REDUNDANCIA:
                continue

            cfg, _ = evaluar(
                panel,
                seleccionados + [cand],
                fin_train,
                fin_valid,
            )
            evaluados.append(
                {
                    "candidato": cand,
                    "max_corr": corr,
                    "cfg": cfg,
                }
            )

        if not evaluados:
            break

        mejor = min(
            evaluados,
            key=lambda x: (
                x["cfg"]["mape_cuota_pct"],
                x["cfg"]["p90_error_abs_pct"],
            ),
        )

        cand = mejor["candidato"]
        cfg_nueva = mejor["cfg"]
        mejora = (
            cfg_actual["mape_cuota_pct"]
            - cfg_nueva["mape_cuota_pct"]
        )

        aceptar = (
            mejora >= MEJORA_MINIMA_MAPE_PUNTOS
            and cfg_nueva["p90_error_abs_pct"]
            <= cfg_actual["p90_error_abs_pct"]
            + TOLERANCIA_P90_PUNTOS
        )

        trazas.append(
            {
                "afp": afp,
                "paso": paso,
                "accion": "AGREGAR_ACCION",
                "factor": cand["factor"],
                "lag": cand["lag"],
                "max_corr_con_canasta": mejor["max_corr"],
                "mape_antes_pct": cfg_actual["mape_cuota_pct"],
                "mape_despues_pct": cfg_nueva["mape_cuota_pct"],
                "mejora_mape_puntos": mejora,
                "p90_despues_pct": cfg_nueva["p90_error_abs_pct"],
                "aceptado": aceptar,
            }
        )

        if not aceptar:
            break

        seleccionados.append(cand)
        cfg_actual = cfg_nueva
        disponibles = [
            x for x in disponibles
            if not (
                x["factor"] == cand["factor"]
                and int(x["lag"]) == int(cand["lag"])
            )
        ]

    return seleccionados, cfg_actual, pd.DataFrame(trazas)


def diebold_mariano(
    perdida_modelo: np.ndarray,
    perdida_referencia: np.ndarray,
    max_lag: int = 5,
) -> dict[str, float]:
    modelo = np.asarray(perdida_modelo, dtype=float)
    referencia = np.asarray(perdida_referencia, dtype=float)
    mascara = np.isfinite(modelo) & np.isfinite(referencia)
    d = modelo[mascara] - referencia[mascara]
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
        gamma = float(
            np.dot(centrado[lag:], centrado[:-lag]) / n
        )
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
        2.0 * (
            1.0 - stats.norm.cdf(abs(estadistico))
        )
    )

    return {
        "n_dm": int(n),
        "diferencia_media_perdida": media,
        "dm_estadistico": float(estadistico),
        "dm_pvalor": pvalor,
    }


def coeficientes(
    modelo: ModeloRidge,
    specs: list[dict[str, Any]],
    afp: str,
    tipo_modelo: str,
) -> pd.DataFrame:
    filas = []

    for spec, coef in zip(
        specs, modelo.ridge.coef_
    ):
        filas.append(
            {
                "afp": afp,
                "tipo_modelo": tipo_modelo,
                "factor": spec["factor"],
                "lag": spec["lag"],
                "coeficiente_estandarizado": float(coef),
                "abs_coeficiente": abs(float(coef)),
            }
        )

    return pd.DataFrame(filas).sort_values(
        "abs_coeficiente",
        ascending=False,
    )


def guardar_figura(ruta: Path) -> None:
    plt.tight_layout()
    plt.savefig(ruta, dpi=160, bbox_inches="tight")
    plt.close()


def main() -> None:
    raiz = Path(__file__).resolve().parents[1]
    processed = raiz / "data" / "processed"
    graficos = processed / "graficos_modelo71"
    graficos.mkdir(parents=True, exist_ok=True)

    fin_train, fin_valid = cargar_division(processed)
    base, factores, catalogo, canasta = cargar_fuentes(processed)

    catalogo_acciones = catalogo[
        catalogo["categoria"].astype(str).isin(
            CATEGORIAS_ACCIONES
        )
    ].copy()

    factores_acciones = (
        catalogo_acciones["factor"]
        .dropna()
        .astype(str)
        .unique()
        .tolist()
    )

    if not factores_acciones:
        raise RuntimeError(
            "No se encontraron acciones en el catálogo del módulo 69."
        )

    resumen_acciones = []
    screening_todos = []
    trazas_todas = []
    metricas_validacion = []
    metricas_prueba = []
    simulaciones = []
    dm_filas = []
    coeficientes_todos = []

    for afp in AFPS:
        print(f"\nEvaluando acciones individuales para {afp}...")

        panel = preparar_panel(base, factores, afp)

        base_specs = (
            canasta[canasta["afp"].astype(str).eq(afp)]
            .sort_values("orden")
            [["factor", "lag"]]
            .dropna()
            .to_dict(orient="records")
        )

        if not base_specs:
            raise RuntimeError(
                f"No se encontró la canasta del módulo 70 para {afp}."
            )

        candidatos_brutos = [
            {
                "factor": factor,
                "lag": lag,
            }
            for factor in factores_acciones
            for lag in LAGS_ACCIONES
            if factor in panel.columns
        ]

        screen = calcular_screen_train(
            panel,
            candidatos_brutos,
            fin_train,
        )
        screen["afp"] = afp
        screening_todos.append(screen)

        candidatos = (
            screen.head(MAX_CANDIDATOS_SCREEN)
            [["factor", "lag", "spearman_train", "pearson_train"]]
            .to_dict(orient="records")
        )

        specs_finales, cfg_final, traza = seleccionar_acciones(
            panel,
            base_specs,
            candidatos,
            fin_train,
            fin_valid,
            afp,
        )
        trazas_todas.append(traza)

        acciones_agregadas = specs_finales[len(base_specs):]

        cfg_base, _ = evaluar(
            panel,
            base_specs,
            fin_train,
            fin_valid,
        )
        cfg_acciones, _ = evaluar(
            panel,
            specs_finales,
            fin_train,
            fin_valid,
        )

        metricas_validacion.extend(
            [
                {
                    "afp": afp,
                    "tipo_modelo": "MODELO70",
                    "n_factores": len(base_specs),
                    **cfg_base,
                },
                {
                    "afp": afp,
                    "tipo_modelo": "MODELO70_MAS_ACCIONES",
                    "n_factores": len(specs_finales),
                    "n_acciones_agregadas": len(acciones_agregadas),
                    **cfg_acciones,
                },
            ]
        )

        met_base, sim_base, modelo_base = evaluar_prueba(
            panel,
            base_specs,
            cfg_base,
            fin_valid,
        )
        met_acc, sim_acc, modelo_acc = evaluar_prueba(
            panel,
            specs_finales,
            cfg_acciones,
            fin_valid,
        )

        metricas_prueba.extend(
            [
                {
                    "afp": afp,
                    "tipo_modelo": "MODELO70",
                    "n_factores": len(base_specs),
                    "n_acciones_agregadas": 0,
                    "familia": cfg_base["familia"],
                    "alpha": cfg_base["alpha"],
                    "half_life": cfg_base["half_life"],
                    **met_base,
                },
                {
                    "afp": afp,
                    "tipo_modelo": "MODELO70_MAS_ACCIONES",
                    "n_factores": len(specs_finales),
                    "n_acciones_agregadas": len(acciones_agregadas),
                    "familia": cfg_acciones["familia"],
                    "alpha": cfg_acciones["alpha"],
                    "half_life": cfg_acciones["half_life"],
                    **met_acc,
                },
            ]
        )

        sim_base["afp"] = afp
        sim_base["tipo_modelo"] = "MODELO70"
        sim_acc["afp"] = afp
        sim_acc["tipo_modelo"] = "MODELO70_MAS_ACCIONES"
        simulaciones.extend([sim_base, sim_acc])

        unido = sim_acc[
            ["fecha_hoy_simulada", "error_abs_pct"]
        ].rename(
            columns={
                "error_abs_pct": "perdida_acciones"
            }
        ).merge(
            sim_base[
                ["fecha_hoy_simulada", "error_abs_pct"]
            ].rename(
                columns={
                    "error_abs_pct": "perdida_modelo70"
                }
            ),
            on="fecha_hoy_simulada",
            how="inner",
        )

        dm = diebold_mariano(
            unido["perdida_acciones"].to_numpy(float),
            unido["perdida_modelo70"].to_numpy(float),
            max_lag=5,
        )

        dm_filas.append(
            {
                "afp": afp,
                "modelo": "MODELO70_MAS_ACCIONES",
                "referencia": "MODELO70",
                **dm,
                "supera_modelo70_con_evidencia": (
                    pd.notna(dm["diferencia_media_perdida"])
                    and pd.notna(dm["dm_pvalor"])
                    and dm["diferencia_media_perdida"] < 0
                    and dm["dm_pvalor"] < 0.05
                ),
            }
        )

        coeficientes_todos.extend(
            [
                coeficientes(
                    modelo_base,
                    base_specs,
                    afp,
                    "MODELO70",
                ),
                coeficientes(
                    modelo_acc,
                    specs_finales,
                    afp,
                    "MODELO70_MAS_ACCIONES",
                ),
            ]
        )

        for orden, spec in enumerate(
            acciones_agregadas,
            start=1,
        ):
            meta = catalogo_acciones[
                catalogo_acciones["factor"].astype(str).eq(
                    str(spec["factor"])
                )
            ]

            resumen_acciones.append(
                {
                    "afp": afp,
                    "orden_accion": orden,
                    "factor": spec["factor"],
                    "lag": int(spec["lag"]),
                    "ticker": (
                        meta["ticker"].iloc[0]
                        if not meta.empty
                        else ""
                    ),
                    "nombre": (
                        meta["nombre"].iloc[0]
                        if not meta.empty
                        else ""
                    ),
                    "categoria": (
                        meta["categoria"].iloc[0]
                        if not meta.empty
                        else ""
                    ),
                    "transformacion": (
                        meta["transformacion"].iloc[0]
                        if not meta.empty
                        else ""
                    ),
                    "moneda_modelo": (
                        meta["moneda_modelo"].iloc[0]
                        if not meta.empty
                        else ""
                    ),
                }
            )

        plt.figure(figsize=(12, 5))
        plt.plot(
            sim_acc["fecha_hoy_simulada"],
            sim_acc["cuota_real_hoy"],
            label="Cuota SBS",
        )
        plt.plot(
            sim_base["fecha_hoy_simulada"],
            sim_base["cuota_estimada_hoy"],
            label="Modelo 70",
        )
        plt.plot(
            sim_acc["fecha_hoy_simulada"],
            sim_acc["cuota_estimada_hoy"],
            label="Modelo 70 + acciones",
        )
        plt.ylabel("Valor cuota")
        plt.title(f"Acciones individuales: aporte incremental — {afp}")
        plt.legend()
        guardar_figura(
            graficos / f"01_acciones_{afp.lower()}.png"
        )

    acciones_df = pd.DataFrame(resumen_acciones)
    screening_df = pd.concat(
        screening_todos,
        ignore_index=True,
    )
    trazas_df = pd.concat(
        trazas_todas,
        ignore_index=True,
    )
    val_df = pd.DataFrame(metricas_validacion)
    test_df = pd.DataFrame(metricas_prueba)
    sim_df = pd.concat(simulaciones, ignore_index=True)
    dm_df = pd.DataFrame(dm_filas)
    coef_df = pd.concat(
        coeficientes_todos,
        ignore_index=True,
    )

    rutas = {
        "acciones": (
            processed
            / "ca0001_modelo71_acciones_seleccionadas.csv"
        ),
        "screening": (
            processed
            / "ca0001_modelo71_screening_acciones_train.csv"
        ),
        "trazabilidad": (
            processed
            / "ca0001_modelo71_trazabilidad_seleccion.csv"
        ),
        "validacion": (
            processed
            / "ca0001_modelo71_metricas_validacion.csv"
        ),
        "prueba": (
            processed
            / "ca0001_modelo71_metricas_prueba.csv"
        ),
        "simulaciones": (
            processed
            / "ca0001_modelo71_simulacion_publicacion_5d.csv"
        ),
        "dm": (
            processed
            / "ca0001_modelo71_diebold_mariano.csv"
        ),
        "coeficientes": (
            processed
            / "ca0001_modelo71_coeficientes.csv"
        ),
        "resumen": (
            processed
            / "ca0001_modelo71_resumen.json"
        ),
    }

    acciones_df.to_csv(
        rutas["acciones"],
        index=False,
        encoding="utf-8-sig",
    )
    screening_df.to_csv(
        rutas["screening"],
        index=False,
        encoding="utf-8-sig",
    )
    trazas_df.to_csv(
        rutas["trazabilidad"],
        index=False,
        encoding="utf-8-sig",
    )
    val_df.to_csv(
        rutas["validacion"],
        index=False,
        encoding="utf-8-sig",
    )
    test_df.to_csv(
        rutas["prueba"],
        index=False,
        encoding="utf-8-sig",
    )
    sim_df.to_csv(
        rutas["simulaciones"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    dm_df.to_csv(
        rutas["dm"],
        index=False,
        encoding="utf-8-sig",
    )
    coef_df.to_csv(
        rutas["coeficientes"],
        index=False,
        encoding="utf-8-sig",
    )

    resumen = {
        "version": "modelo71_acciones_individuales",
        "objetivo": (
            "Determinar qué acciones líquidas agregan información "
            "incremental sobre la canasta de ETF/índices del módulo 70."
        ),
        "acciones_seleccionadas": acciones_df.to_dict(
            orient="records"
        ),
        "metricas_prueba": test_df.to_dict(
            orient="records"
        ),
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

    print("\nMÓDULO 71 — ACCIONES INDIVIDUALES Y APORTE INCREMENTAL")
    print("=" * 160)
    print(
        "La canasta del módulo 70 se mantiene fija. "
        "Las acciones solo se agregan si mejoran la validación."
    )

    print("\nACCIONES SELECCIONADAS")
    print("-" * 160)
    if acciones_df.empty:
        print(
            "Ninguna acción superó el aporte de los ETF/índices "
            "con los criterios establecidos."
        )
    else:
        print(acciones_df.to_string(index=False))

    print("\nTOP 15 ACCIONES POR AFP — SCREENING DE ENTRENAMIENTO")
    print("-" * 160)
    print(
        screening_df.groupby(
            "afp", group_keys=False
        ).head(15)[
            [
                "afp",
                "factor",
                "lag",
                "n_train",
                "spearman_train",
                "pearson_train",
            ]
        ].to_string(index=False)
    )

    print("\nMÉTRICAS DE VALIDACIÓN")
    print("-" * 160)
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
    print("-" * 160)
    print(
        test_df[
            [
                "afp",
                "tipo_modelo",
                "n_factores",
                "n_acciones_agregadas",
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

    print("\nDIEBOLD-MARIANO: ACCIONES VS MODELO 70")
    print("-" * 160)
    print(dm_df.to_string(index=False))

    print("\nTRAZABILIDAD DE LA SELECCIÓN")
    print("-" * 160)
    print(trazas_df.to_string(index=False))

    print("\nARCHIVOS CREADOS")
    print("-" * 160)
    for ruta in rutas.values():
        print(f" - {ruta.resolve()}")
    print(f" - {graficos.resolve()}")

    print(
        "\nLECTURA:\n"
        "- Una acción puede ser un proxy estadístico sin ser una "
        "tenencia confirmada de la AFP.\n"
        "- Se prueban versiones USD y PEN y rezagos de 0 a 3 días.\n"
        "- La acción debe aportar información adicional después de "
        "controlar por los ETF e índices del módulo 70.\n"
        "- El paso posterior cruzará las acciones seleccionadas con "
        "CA-0001/OpenFIGI y con los componentes de los ETF ganadores."
    )


if __name__ == "__main__":
    main()
