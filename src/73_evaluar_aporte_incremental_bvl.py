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

ALPHAS_RIDGE = [0.001, 0.01, 0.1, 1.0, 10.0, 100.0]
ALPHAS_EW = [0.001, 0.1, 10.0]
VIDAS_MEDIAS = [60, 120, 250, 500]

MAX_CANDIDATOS_BVL = 18
MAX_ADICIONES_BVL = 5
UMBRAL_REDUNDANCIA = 0.95
MEJORA_MINIMA_MAPE_PUNTOS = 0.002
TOLERANCIA_P90_PUNTOS = 0.05
RETRASO_PUBLICACION_DIAS = 5
MIN_FILAS = 500

# Ya fueron probados en el módulo 71 con las mismas acciones/ADR.
# No se vuelven a presentar como “nuevas” señales BVL.
INSTRUMENTOS_YA_PROBADOS_MOD71 = {
    "Credicorp",
    "Southern Copper",
    "Buenaventura",
}


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

    for args in intentos:
        try:
            return pd.read_csv(ruta, **args)
        except Exception as exc:
            ultimo_error = exc

    raise RuntimeError(f"No se pudo leer {ruta}: {ultimo_error}")


def a_booleano(valor: Any) -> bool:
    if isinstance(valor, (bool, np.bool_)):
        return bool(valor)

    texto = str(valor).strip().lower()
    return texto in {"true", "1", "si", "sí", "yes"}


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
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
]:
    base = leer_csv(processed / "ca0001_modelo56_base_alineada.csv")
    factores69 = leer_csv(processed / "ca0001_modelo69_factores_ampliados.csv")
    canasta70 = leer_csv(processed / "ca0001_modelo70_canasta_seleccionada.csv")
    acciones71 = leer_csv(processed / "ca0001_modelo71_acciones_seleccionadas.csv")
    dm71 = leer_csv(processed / "ca0001_modelo71_diebold_mariano.csv")
    factores72 = leer_csv(processed / "ca0001_modelo72_factores_bvl.csv")

    base["fecha_cuota"] = pd.to_datetime(
        base["fecha_cuota"], errors="coerce"
    ).dt.normalize()
    base["cuota_sbs"] = pd.to_numeric(base["cuota_sbs"], errors="coerce")
    base["retorno_cuota"] = pd.to_numeric(
        base["retorno_cuota"], errors="coerce"
    )

    for df in [factores69, factores72]:
        df["fecha_cuota"] = pd.to_datetime(
            df["fecha_cuota"], errors="coerce"
        ).dt.normalize()

        for columna in df.columns:
            if columna != "fecha_cuota":
                df[columna] = pd.to_numeric(
                    df[columna], errors="coerce"
                )

    canasta70["lag"] = pd.to_numeric(
        canasta70["lag"], errors="coerce"
    ).astype("Int64")

    if not acciones71.empty:
        acciones71["lag"] = pd.to_numeric(
            acciones71["lag"], errors="coerce"
        ).astype("Int64")

    return base, factores69, canasta70, acciones71, dm71, factores72


def cargar_catalogo_y_screening(
    processed: Path,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    catalogo72 = leer_csv(
        processed / "ca0001_modelo72_catalogo_factores_bvl.csv"
    )
    screening72 = leer_csv(
        processed / "ca0001_modelo72_screening_train_bvl.csv"
    )

    screening72["mejor_lag_train"] = pd.to_numeric(
        screening72["mejor_lag_train"], errors="coerce"
    )
    screening72["n_train"] = pd.to_numeric(
        screening72["n_train"], errors="coerce"
    )
    screening72["cobertura_train_pct"] = pd.to_numeric(
        screening72["cobertura_train_pct"], errors="coerce"
    )
    screening72["abs_spearman_train"] = pd.to_numeric(
        screening72["abs_spearman_train"], errors="coerce"
    )
    screening72["elegible_operativo"] = screening72[
        "elegible_operativo"
    ].map(a_booleano)

    return catalogo72, screening72


def construir_campeon_actual(
    canasta70: pd.DataFrame,
    acciones71: pd.DataFrame,
    dm71: pd.DataFrame,
    afp: str,
) -> list[dict[str, Any]]:
    specs = (
        canasta70[canasta70["afp"].astype(str).eq(afp)]
        .sort_values("orden")
        [["factor", "lag"]]
        .dropna()
        .to_dict(orient="records")
    )

    fila_dm = dm71[dm71["afp"].astype(str).eq(afp)]
    usar_acciones = (
        not fila_dm.empty
        and a_booleano(
            fila_dm["supera_modelo70_con_evidencia"].iloc[0]
        )
    )

    if usar_acciones and not acciones71.empty:
        nuevas = (
            acciones71[
                acciones71["afp"].astype(str).eq(afp)
            ]
            .sort_values("orden_accion")
            [["factor", "lag"]]
            .dropna()
            .to_dict(orient="records")
        )
        specs.extend(nuevas)

    unicos = []
    vistos = set()

    for spec in specs:
        clave = (str(spec["factor"]), int(spec["lag"]))
        if clave in vistos:
            continue
        vistos.add(clave)
        unicos.append(
            {
                "factor": clave[0],
                "lag": clave[1],
            }
        )

    if not unicos:
        raise RuntimeError(
            f"No se pudo construir el campeón actual para {afp}."
        )

    return unicos


def preparar_panel(
    base: pd.DataFrame,
    factores69: pd.DataFrame,
    factores72: pd.DataFrame,
    afp: str,
) -> pd.DataFrame:
    cuota = (
        base[base["afp"].astype(str).eq(afp)]
        [["fecha_cuota", "cuota_sbs", "retorno_cuota"]]
        .dropna(subset=["fecha_cuota", "cuota_sbs"])
        .drop_duplicates("fecha_cuota", keep="last")
        .sort_values("fecha_cuota")
    )

    factores = factores69.merge(
        factores72,
        on="fecha_cuota",
        how="outer",
        validate="one_to_one",
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

    # En los factores BVL, NaN significa “sin nueva señal negociada”.
    # Operativamente se convierte a contribución cero, sin fingir que fue
    # un retorno observado de 0% en la auditoría de origen.
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
                len(yf),
                int(half_life),
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
            ancla + 1 : i,
            "retorno_estimado",
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


def evaluar_validacion(
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


def construir_pool_bvl(
    screening72: pd.DataFrame,
    afp: str,
    campeon_specs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    existentes = {
        (str(x["factor"]), int(x["lag"]))
        for x in campeon_specs
    }

    s = screening72[
        screening72["afp"].astype(str).eq(afp)
        & screening72["elegible_operativo"].eq(True)
        & ~screening72["instrumento"].astype(str).isin(
            INSTRUMENTOS_YA_PROBADOS_MOD71
        )
    ].copy()

    s = s.sort_values(
        [
            "abs_spearman_train",
            "mutual_information_train",
        ],
        ascending=False,
    )

    pool = []

    for _, fila in s.iterrows():
        spec = {
            "factor": str(fila["factor"]),
            "lag": int(fila["mejor_lag_train"]),
            "instrumento": str(fila["instrumento"]),
            "ticker_elegido": str(fila["ticker_elegido"]),
            "tipo": str(fila["tipo"]),
            "sector": str(fila["sector"]),
            "moneda_modelo": str(fila["moneda_modelo"]),
            "spearman_train": float(fila["spearman_train"]),
            "pearson_train": float(fila["pearson_train"]),
        }

        clave = (spec["factor"], spec["lag"])

        if clave in existentes:
            continue

        pool.append(spec)

        if len(pool) >= MAX_CANDIDATOS_BVL:
            break

    return pool


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


def seleccionar_bvl(
    panel: pd.DataFrame,
    campeon_specs: list[dict[str, Any]],
    pool: list[dict[str, Any]],
    fin_train: pd.Timestamp,
    fin_valid: pd.Timestamp,
    afp: str,
) -> tuple[
    list[dict[str, Any]],
    dict[str, Any],
    pd.DataFrame,
]:
    seleccionados = [dict(x) for x in campeon_specs]
    cfg_actual, _ = evaluar_validacion(
        panel,
        seleccionados,
        fin_train,
        fin_valid,
    )

    disponibles = [dict(x) for x in pool]

    trazas = [
        {
            "afp": afp,
            "paso": 0,
            "accion": "CAMPEON_ACTUAL",
            "factor": "",
            "instrumento": "",
            "lag": np.nan,
            "max_corr_con_canasta": np.nan,
            "mape_antes_pct": np.nan,
            "mape_despues_pct": cfg_actual["mape_cuota_pct"],
            "mejora_mape_puntos": np.nan,
            "p90_despues_pct": cfg_actual["p90_error_abs_pct"],
            "aceptado": True,
        }
    ]

    for paso in range(1, MAX_ADICIONES_BVL + 1):
        evaluados = []

        for candidato in disponibles:
            corr = max_correlacion(
                panel,
                candidato,
                seleccionados,
                fin_train,
            )

            if corr >= UMBRAL_REDUNDANCIA:
                continue

            cfg_nueva, _ = evaluar_validacion(
                panel,
                seleccionados + [candidato],
                fin_train,
                fin_valid,
            )

            evaluados.append(
                {
                    "candidato": candidato,
                    "max_corr": corr,
                    "cfg": cfg_nueva,
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

        candidato = mejor["candidato"]
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
                "accion": "AGREGAR_BVL",
                "factor": candidato["factor"],
                "instrumento": candidato["instrumento"],
                "lag": candidato["lag"],
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

        seleccionados.append(candidato)
        cfg_actual = cfg_nueva

        disponibles = [
            x
            for x in disponibles
            if not (
                x["factor"] == candidato["factor"]
                and int(x["lag"]) == int(candidato["lag"])
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
            np.dot(
                centrado[lag:],
                centrado[:-lag],
            )
            / n
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
        2.0
        * (
            1.0
            - stats.norm.cdf(abs(estadistico))
        )
    )

    return {
        "n_dm": int(n),
        "diferencia_media_perdida": media,
        "dm_estadistico": float(estadistico),
        "dm_pvalor": pvalor,
    }


def estabilidad_cuartiles(
    sim: pd.DataFrame,
    afp: str,
    tipo_modelo: str,
) -> pd.DataFrame:
    x = sim.sort_values("fecha_hoy_simulada").copy()

    if len(x) < 20:
        return pd.DataFrame()

    x["subperiodo"] = pd.qcut(
        np.arange(len(x)),
        4,
        labels=["Q1", "Q2", "Q3", "Q4"],
    )

    filas = []

    for subperiodo, bloque in x.groupby(
        "subperiodo",
        observed=False,
    ):
        met = metricas_cuota(bloque)
        filas.append(
            {
                "afp": afp,
                "tipo_modelo": tipo_modelo,
                "subperiodo": str(subperiodo),
                "fecha_inicio": bloque[
                    "fecha_hoy_simulada"
                ].min(),
                "fecha_fin": bloque[
                    "fecha_hoy_simulada"
                ].max(),
                **met,
            }
        )

    return pd.DataFrame(filas)


def coeficientes(
    modelo: ModeloRidge,
    specs: list[dict[str, Any]],
    afp: str,
    tipo_modelo: str,
) -> pd.DataFrame:
    filas = []

    for spec, coef in zip(
        specs,
        modelo.ridge.coef_,
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
    graficos = processed / "graficos_modelo73"
    graficos.mkdir(parents=True, exist_ok=True)

    fin_train, fin_valid = cargar_division(processed)

    (
        base,
        factores69,
        canasta70,
        acciones71,
        dm71,
        factores72,
    ) = cargar_fuentes(processed)

    catalogo72, screening72 = cargar_catalogo_y_screening(processed)

    factores_bvl_seleccionados = []
    trazas = []
    metricas_validacion = []
    metricas_prueba = []
    simulaciones = []
    dm_filas = []
    estabilidad = []
    coeficientes_todos = []

    for afp in AFPS:
        print(f"\nProbando aporte incremental BVL para {afp}...")

        panel = preparar_panel(
            base,
            factores69,
            factores72,
            afp,
        )

        campeon_specs = construir_campeon_actual(
            canasta70,
            acciones71,
            dm71,
            afp,
        )

        pool = construir_pool_bvl(
            screening72,
            afp,
            campeon_specs,
        )

        specs_bvl, cfg_bvl, traza = seleccionar_bvl(
            panel,
            campeon_specs,
            pool,
            fin_train,
            fin_valid,
            afp,
        )
        trazas.append(traza)

        agregados = specs_bvl[len(campeon_specs):]

        cfg_campeon, _ = evaluar_validacion(
            panel,
            campeon_specs,
            fin_train,
            fin_valid,
        )
        cfg_final, _ = evaluar_validacion(
            panel,
            specs_bvl,
            fin_train,
            fin_valid,
        )

        metricas_validacion.extend(
            [
                {
                    "afp": afp,
                    "tipo_modelo": "CAMPEON_PRE_BVL",
                    "n_factores": len(campeon_specs),
                    "n_factores_bvl": 0,
                    **cfg_campeon,
                },
                {
                    "afp": afp,
                    "tipo_modelo": "CAMPEON_MAS_BVL",
                    "n_factores": len(specs_bvl),
                    "n_factores_bvl": len(agregados),
                    **cfg_final,
                },
            ]
        )

        met_campeon, sim_campeon, modelo_campeon = evaluar_prueba(
            panel,
            campeon_specs,
            cfg_campeon,
            fin_valid,
        )
        met_bvl, sim_bvl, modelo_bvl = evaluar_prueba(
            panel,
            specs_bvl,
            cfg_final,
            fin_valid,
        )

        metricas_prueba.extend(
            [
                {
                    "afp": afp,
                    "tipo_modelo": "CAMPEON_PRE_BVL",
                    "n_factores": len(campeon_specs),
                    "n_factores_bvl": 0,
                    "familia": cfg_campeon["familia"],
                    "alpha": cfg_campeon["alpha"],
                    "half_life": cfg_campeon["half_life"],
                    **met_campeon,
                },
                {
                    "afp": afp,
                    "tipo_modelo": "CAMPEON_MAS_BVL",
                    "n_factores": len(specs_bvl),
                    "n_factores_bvl": len(agregados),
                    "familia": cfg_final["familia"],
                    "alpha": cfg_final["alpha"],
                    "half_life": cfg_final["half_life"],
                    **met_bvl,
                },
            ]
        )

        sim_campeon["afp"] = afp
        sim_campeon["tipo_modelo"] = "CAMPEON_PRE_BVL"
        sim_bvl["afp"] = afp
        sim_bvl["tipo_modelo"] = "CAMPEON_MAS_BVL"
        simulaciones.extend([sim_campeon, sim_bvl])

        estabilidad.extend(
            [
                estabilidad_cuartiles(
                    sim_campeon,
                    afp,
                    "CAMPEON_PRE_BVL",
                ),
                estabilidad_cuartiles(
                    sim_bvl,
                    afp,
                    "CAMPEON_MAS_BVL",
                ),
            ]
        )

        unido = sim_bvl[
            ["fecha_hoy_simulada", "error_abs_pct"]
        ].rename(
            columns={
                "error_abs_pct": "perdida_bvl"
            }
        ).merge(
            sim_campeon[
                ["fecha_hoy_simulada", "error_abs_pct"]
            ].rename(
                columns={
                    "error_abs_pct": "perdida_campeon"
                }
            ),
            on="fecha_hoy_simulada",
            how="inner",
        )

        dm = diebold_mariano(
            unido["perdida_bvl"].to_numpy(float),
            unido["perdida_campeon"].to_numpy(float),
            max_lag=5,
        )

        dm_filas.append(
            {
                "afp": afp,
                "modelo": "CAMPEON_MAS_BVL",
                "referencia": "CAMPEON_PRE_BVL",
                **dm,
                "supera_campeon_con_evidencia": (
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
                    modelo_campeon,
                    campeon_specs,
                    afp,
                    "CAMPEON_PRE_BVL",
                ),
                coeficientes(
                    modelo_bvl,
                    specs_bvl,
                    afp,
                    "CAMPEON_MAS_BVL",
                ),
            ]
        )

        for orden, spec in enumerate(
            agregados,
            start=1,
        ):
            meta = catalogo72[
                catalogo72["factor"].astype(str).eq(
                    str(spec["factor"])
                )
            ]

            factores_bvl_seleccionados.append(
                {
                    "afp": afp,
                    "orden_bvl": orden,
                    "factor": spec["factor"],
                    "lag": int(spec["lag"]),
                    "instrumento": (
                        meta["instrumento"].iloc[0]
                        if not meta.empty
                        else spec.get("instrumento", "")
                    ),
                    "ticker_elegido": (
                        meta["ticker_elegido"].iloc[0]
                        if not meta.empty
                        else spec.get("ticker_elegido", "")
                    ),
                    "tipo": (
                        meta["tipo"].iloc[0]
                        if not meta.empty
                        else spec.get("tipo", "")
                    ),
                    "sector": (
                        meta["sector"].iloc[0]
                        if not meta.empty
                        else spec.get("sector", "")
                    ),
                    "moneda_modelo": (
                        meta["moneda_modelo"].iloc[0]
                        if not meta.empty
                        else spec.get("moneda_modelo", "")
                    ),
                }
            )

        plt.figure(figsize=(12, 5))
        plt.plot(
            sim_bvl["fecha_hoy_simulada"],
            sim_bvl["cuota_real_hoy"],
            label="Cuota SBS",
        )
        plt.plot(
            sim_campeon["fecha_hoy_simulada"],
            sim_campeon["cuota_estimada_hoy"],
            label="Campeón previo",
        )
        plt.plot(
            sim_bvl["fecha_hoy_simulada"],
            sim_bvl["cuota_estimada_hoy"],
            label="Campeón + BVL",
        )
        plt.ylabel("Valor cuota")
        plt.title(f"Aporte incremental BVL — {afp}")
        plt.legend()
        guardar_figura(
            graficos / f"01_cuota_bvl_{afp.lower()}.png"
        )

    seleccion_df = pd.DataFrame(
        factores_bvl_seleccionados
    )
    trazas_df = pd.concat(
        trazas,
        ignore_index=True,
    )
    validacion_df = pd.DataFrame(
        metricas_validacion
    )
    prueba_df = pd.DataFrame(
        metricas_prueba
    )
    simulaciones_df = pd.concat(
        simulaciones,
        ignore_index=True,
    )
    dm_df = pd.DataFrame(dm_filas)

    estabilidad_validos = [
        x for x in estabilidad
        if isinstance(x, pd.DataFrame) and not x.empty
    ]
    estabilidad_df = (
        pd.concat(
            estabilidad_validos,
            ignore_index=True,
        )
        if estabilidad_validos
        else pd.DataFrame()
    )

    coeficientes_df = pd.concat(
        coeficientes_todos,
        ignore_index=True,
    )

    rutas = {
        "seleccion": (
            processed
            / "ca0001_modelo73_factores_bvl_seleccionados.csv"
        ),
        "trazabilidad": (
            processed
            / "ca0001_modelo73_trazabilidad_seleccion.csv"
        ),
        "validacion": (
            processed
            / "ca0001_modelo73_metricas_validacion.csv"
        ),
        "prueba": (
            processed
            / "ca0001_modelo73_metricas_prueba.csv"
        ),
        "simulaciones": (
            processed
            / "ca0001_modelo73_simulacion_publicacion_5d.csv"
        ),
        "dm": (
            processed
            / "ca0001_modelo73_diebold_mariano.csv"
        ),
        "estabilidad": (
            processed
            / "ca0001_modelo73_estabilidad_subperiodos.csv"
        ),
        "coeficientes": (
            processed
            / "ca0001_modelo73_coeficientes.csv"
        ),
        "resumen": (
            processed
            / "ca0001_modelo73_resumen.json"
        ),
    }

    seleccion_df.to_csv(
        rutas["seleccion"],
        index=False,
        encoding="utf-8-sig",
    )
    trazas_df.to_csv(
        rutas["trazabilidad"],
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
    simulaciones_df.to_csv(
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
    estabilidad_df.to_csv(
        rutas["estabilidad"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    coeficientes_df.to_csv(
        rutas["coeficientes"],
        index=False,
        encoding="utf-8-sig",
    )

    resumen = {
        "version": "modelo73_aporte_incremental_bvl",
        "criterio_campeon_previo": (
            "Modelo 70 para AFP sin mejora significativa de acciones; "
            "Modelo 70 más acciones del módulo 71 cuando DM fue significativo."
        ),
        "factores_bvl_seleccionados": seleccion_df.to_dict(
            orient="records"
        ),
        "metricas_prueba": prueba_df.to_dict(
            orient="records"
        ),
        "nota": (
            "Los índices BVL no estuvieron disponibles vía Yahoo Finance. "
            "Este módulo evalúa acciones locales descargables. "
            "La incorporación definitiva exige mejora en prueba y DM."
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

    print("\nMÓDULO 73 — APORTE INCREMENTAL DE ACCIONES BVL")
    print("=" * 165)
    print(
        "Se parte del campeón actual de cada AFP y se agregan "
        "solo factores BVL elegibles."
    )

    print("\nFACTORES BVL SELECCIONADOS EN VALIDACIÓN")
    print("-" * 165)

    if seleccion_df.empty:
        print(
            "Ningún factor BVL superó el umbral de aporte incremental."
        )
    else:
        print(seleccion_df.to_string(index=False))

    print("\nMÉTRICAS DE VALIDACIÓN")
    print("-" * 165)
    print(
        validacion_df[
            [
                "afp",
                "tipo_modelo",
                "n_factores",
                "n_factores_bvl",
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
        prueba_df[
            [
                "afp",
                "tipo_modelo",
                "n_factores",
                "n_factores_bvl",
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

    print("\nDIEBOLD-MARIANO: BVL VS CAMPEÓN PREVIO")
    print("-" * 165)
    print(dm_df.to_string(index=False))

    print("\nTRAZABILIDAD")
    print("-" * 165)
    print(trazas_df.to_string(index=False))

    print("\nARCHIVOS CREADOS")
    print("-" * 165)
    for ruta in rutas.values():
        print(f" - {ruta.resolve()}")
    print(f" - {graficos.resolve()}")

    print(
        "\nLECTURA:\n"
        "- El campeón previo ya incorpora la mejor evidencia de los "
        "módulos 70 y 71.\n"
        "- Las acciones BVL compiten por aporte adicional, no por "
        "correlación aislada.\n"
        "- Los ADR ya probados en el módulo 71 no se cuentan nuevamente "
        "como señales BVL nuevas.\n"
        "- Si ninguna acción local mejora de forma estable, eso también "
        "es un resultado útil: los ETF/ADR líquidos serían mejores "
        "instrumentos de seguimiento diario."
    )


if __name__ == "__main__":
    main()
