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

RETRASO_PUBLICACION_DIAS = 5
MIN_FILAS = 500

MAX_CANDIDATOS_INDICES = 30
MAX_SUSTITUCIONES = 4
MAX_ADICIONES = 5

UMBRAL_CORRELACION_SUSTITUCION = 0.85
UMBRAL_REDUNDANCIA_ADICION = 0.97
MEJORA_MINIMA_MAPE_PUNTOS = 0.002
TOLERANCIA_P90_PUNTOS = 0.05


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
    ultimo_error: Exception | None = None

    for encoding in ["utf-8-sig", "latin-1"]:
        try:
            return pd.read_csv(ruta, encoding=encoding)
        except Exception as exc:
            ultimo_error = exc

    raise RuntimeError(f"No se pudo leer {ruta}: {ultimo_error}")


def a_booleano(valor: Any) -> bool:
    if isinstance(valor, (bool, np.bool_)):
        return bool(valor)

    return str(valor).strip().lower() in {
        "true",
        "1",
        "si",
        "sí",
        "yes",
    }


def cargar_division(processed: Path) -> tuple[pd.Timestamp, pd.Timestamp]:
    df = leer_csv(
        processed / "ca0001_modelo50_division_temporal.csv"
    )
    df["fecha_fin"] = pd.to_datetime(
        df["fecha_fin"], errors="coerce"
    )

    train = df[
        df["segmento"].astype(str).eq(
            "entrenamiento_descubrimiento"
        )
    ]
    valid = df[
        df["segmento"].astype(str).eq("validacion")
    ]

    if train.empty or valid.empty:
        raise RuntimeError(
            "No se encontró la división temporal del módulo 50."
        )

    return (
        pd.Timestamp(train["fecha_fin"].iloc[0]).normalize(),
        pd.Timestamp(valid["fecha_fin"].iloc[0]).normalize(),
    )


def cargar_fuentes(
    processed: Path,
) -> dict[str, pd.DataFrame]:
    nombres = {
        "base": "ca0001_modelo56_base_alineada.csv",
        "factores69": "ca0001_modelo69_factores_ampliados.csv",
        "canasta70": "ca0001_modelo70_canasta_seleccionada.csv",
        "acciones71": "ca0001_modelo71_acciones_seleccionadas.csv",
        "dm71": "ca0001_modelo71_diebold_mariano.csv",
        "factores72": "ca0001_modelo72_factores_bvl.csv",
        "seleccion73": "ca0001_modelo73_factores_bvl_seleccionados.csv",
        "dm73": "ca0001_modelo73_diebold_mariano.csv",
        "factores74": "ca0001_modelo74_factores_indices.csv",
        "catalogo74": "ca0001_modelo74_catalogo_indices.csv",
        "screening74": "ca0001_modelo74_screening_train_indices.csv",
    }

    fuentes: dict[str, pd.DataFrame] = {}

    for clave, nombre in nombres.items():
        ruta = processed / nombre

        if not ruta.exists():
            if clave in {"acciones71", "seleccion73"}:
                fuentes[clave] = pd.DataFrame()
                continue
            raise FileNotFoundError(f"Falta el archivo: {ruta}")

        fuentes[clave] = leer_csv(ruta)

    fuentes["base"]["fecha_cuota"] = pd.to_datetime(
        fuentes["base"]["fecha_cuota"],
        errors="coerce",
    ).dt.normalize()

    fuentes["base"]["cuota_sbs"] = pd.to_numeric(
        fuentes["base"]["cuota_sbs"],
        errors="coerce",
    )
    fuentes["base"]["retorno_cuota"] = pd.to_numeric(
        fuentes["base"]["retorno_cuota"],
        errors="coerce",
    )

    for clave in ["factores69", "factores72", "factores74"]:
        df = fuentes[clave]
        df["fecha_cuota"] = pd.to_datetime(
            df["fecha_cuota"],
            errors="coerce",
        ).dt.normalize()

        for columna in df.columns:
            if columna != "fecha_cuota":
                df[columna] = pd.to_numeric(
                    df[columna],
                    errors="coerce",
                )

    for clave, columna_lag in [
        ("canasta70", "lag"),
        ("acciones71", "lag"),
        ("seleccion73", "lag"),
    ]:
        df = fuentes[clave]

        if not df.empty and columna_lag in df.columns:
            df[columna_lag] = pd.to_numeric(
                df[columna_lag],
                errors="coerce",
            ).astype("Int64")

    screening = fuentes["screening74"]

    for columna in [
        "mejor_lag_train",
        "n_train",
        "cobertura_train_pct",
        "spearman_train",
        "pearson_train",
        "mutual_information_train",
        "abs_spearman_train",
    ]:
        screening[columna] = pd.to_numeric(
            screening[columna],
            errors="coerce",
        )

    return fuentes


def construir_campeon_actual(
    fuentes: dict[str, pd.DataFrame],
    afp: str,
) -> list[dict[str, Any]]:
    canasta70 = fuentes["canasta70"]
    acciones71 = fuentes["acciones71"]
    dm71 = fuentes["dm71"]
    seleccion73 = fuentes["seleccion73"]
    dm73 = fuentes["dm73"]

    specs = (
        canasta70[
            canasta70["afp"].astype(str).eq(afp)
        ]
        .sort_values("orden")
        [["factor", "lag"]]
        .dropna()
        .to_dict(orient="records")
    )

    fila_dm71 = dm71[
        dm71["afp"].astype(str).eq(afp)
    ]

    usar_acciones71 = (
        not fila_dm71.empty
        and a_booleano(
            fila_dm71[
                "supera_modelo70_con_evidencia"
            ].iloc[0]
        )
    )

    if usar_acciones71 and not acciones71.empty:
        specs.extend(
            acciones71[
                acciones71["afp"].astype(str).eq(afp)
            ]
            .sort_values("orden_accion")
            [["factor", "lag"]]
            .dropna()
            .to_dict(orient="records")
        )

    fila_dm73 = dm73[
        dm73["afp"].astype(str).eq(afp)
    ]

    usar_bvl73 = (
        not fila_dm73.empty
        and a_booleano(
            fila_dm73[
                "supera_campeon_con_evidencia"
            ].iloc[0]
        )
    )

    if usar_bvl73 and not seleccion73.empty:
        specs.extend(
            seleccion73[
                seleccion73["afp"].astype(str).eq(afp)
            ]
            .sort_values("orden_bvl")
            [["factor", "lag"]]
            .dropna()
            .to_dict(orient="records")
        )

    resultado = []
    vistos = set()

    for spec in specs:
        clave = (
            str(spec["factor"]),
            int(spec["lag"]),
        )

        if clave in vistos:
            continue

        vistos.add(clave)
        resultado.append(
            {
                "factor": clave[0],
                "lag": clave[1],
                "origen": "CAMPEON_PRE_INDICES",
            }
        )

    if not resultado:
        raise RuntimeError(
            f"No se pudo construir el campeón de {afp}."
        )

    return resultado


def preparar_panel(
    fuentes: dict[str, pd.DataFrame],
    afp: str,
) -> pd.DataFrame:
    cuota = (
        fuentes["base"][
            fuentes["base"]["afp"].astype(str).eq(afp)
        ]
        [["fecha_cuota", "cuota_sbs", "retorno_cuota"]]
        .dropna(subset=["fecha_cuota", "cuota_sbs"])
        .drop_duplicates("fecha_cuota", keep="last")
        .sort_values("fecha_cuota")
    )

    factores = fuentes["factores69"].merge(
        fuentes["factores72"],
        on="fecha_cuota",
        how="outer",
        validate="one_to_one",
    ).merge(
        fuentes["factores74"],
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
    columnas = []

    for spec in specs:
        factor = str(spec["factor"])
        lag = int(spec["lag"])
        columna = nombre_feature(factor, lag)

        if factor not in x.columns:
            raise KeyError(f"No existe el factor {factor}")

        x[columna] = pd.to_numeric(
            x[factor],
            errors="coerce",
        ).shift(lag)

        columnas.append(columna)

    x[columnas] = (
        x[columnas]
        .replace([np.inf, -np.inf], np.nan)
        .fillna(0.0)
    )

    return x, columnas


def pesos_exponenciales(
    n: int,
    half_life: int,
) -> np.ndarray:
    edades = np.arange(
        n - 1,
        -1,
        -1,
        dtype=float,
    )
    return np.power(
        0.5,
        edades / float(half_life),
    )


def ajustar_modelo(
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
        raise ValueError(
            f"Muestra insuficiente: {len(yf)}"
        )

    scaler = StandardScaler()
    z = scaler.fit_transform(Xf)

    ridge = Ridge(alpha=float(alpha))

    if familia == "EW_RIDGE":
        if half_life is None:
            raise ValueError(
                "EW_RIDGE requiere half_life."
            )

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

    salida["retorno_estimado"] = modelo.predict(
        panel_features
    )

    return salida


def simular_publicacion(
    predicciones: pd.DataFrame,
    fecha_inicio: pd.Timestamp,
    fecha_fin: pd.Timestamp,
) -> pd.DataFrame:
    p = predicciones.sort_values(
        "fecha_cuota"
    ).reset_index(drop=True)

    filas = []

    objetivos = p.index[
        p["fecha_cuota"].ge(fecha_inicio)
        & p["fecha_cuota"].le(fecha_fin)
    ].tolist()

    for i in objetivos:
        fecha_objetivo = pd.Timestamp(
            p.loc[i, "fecha_cuota"]
        )
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
            np.prod(1.0 + retornos.to_numpy())
            - 1.0
        )

        cuota_ancla = float(
            p.loc[ancla, "cuota_sbs"]
        )
        cuota_real = float(
            p.loc[i, "cuota_sbs"]
        )
        cuota_estimada = float(
            cuota_ancla
            * (1.0 + retorno_estimado)
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


def metricas_diarias(
    pred: pd.DataFrame,
) -> dict[str, float]:
    x = pred.dropna(
        subset=[
            "retorno_cuota",
            "retorno_estimado",
        ]
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
    estimado = x[
        "retorno_estimado"
    ].to_numpy(float)

    correlacion = (
        float(
            np.corrcoef(real, estimado)[0, 1]
        )
        if np.std(real) > 0
        and np.std(estimado) > 0
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
            mean_squared_error(real, estimado)
            ** 0.5
        ),
        "r2_diario": float(
            r2_score(real, estimado)
        ),
        "correlacion_diaria": correlacion,
        "direccion_diaria_pct": direccion,
    }


def metricas_cuota(
    sim: pd.DataFrame,
) -> dict[str, float]:
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

    real = sim[
        "retorno_acumulado_real"
    ].to_numpy(float)
    estimado = sim[
        "retorno_acumulado_estimado"
    ].to_numpy(float)

    correlacion = (
        float(
            np.corrcoef(real, estimado)[0, 1]
        )
        if np.std(real) > 0
        and np.std(estimado) > 0
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
            sim["error_abs_pct"].mean()
            * 100.0
        ),
        "mediana_error_abs_pct": float(
            sim["error_abs_pct"].median()
            * 100.0
        ),
        "p90_error_abs_pct": float(
            sim["error_abs_pct"].quantile(0.90)
            * 100.0
        ),
        "error_maximo_abs_pct": float(
            sim["error_abs_pct"].max()
            * 100.0
        ),
        "sesgo_cuota_pct": float(
            sim["error_pct"].mean()
            * 100.0
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
    pf, columnas = materializar(
        panel,
        specs,
    )

    train = pf[
        pf["fecha_cuota"].le(fin_train)
    ]
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

    for cfg in configuraciones:
        modelo = ajustar_modelo(
            train,
            train["retorno_cuota"],
            columnas,
            cfg["familia"],
            cfg["alpha"],
            cfg["half_life"],
        )

        pred = predecir_panel(
            pf,
            modelo,
        )

        pred_valid = pred[
            pred["fecha_cuota"].gt(fin_train)
            & pred["fecha_cuota"].le(fin_valid)
        ]

        sim = simular_publicacion(
            pred,
            pd.Timestamp(
                valid["fecha_cuota"].min()
            ),
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

    return (
        tabla.iloc[0].to_dict(),
        tabla,
    )


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
    pf, columnas = materializar(
        panel,
        specs,
    )

    train_valid = pf[
        pf["fecha_cuota"].le(fin_valid)
    ]
    test = pf[
        pf["fecha_cuota"].gt(fin_valid)
    ]

    modelo = ajustar_modelo(
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

    pred = predecir_panel(
        pf,
        modelo,
    )
    pred_test = pred[
        pred["fecha_cuota"].gt(fin_valid)
    ]

    sim = simular_publicacion(
        pred,
        pd.Timestamp(
            test["fecha_cuota"].min()
        ),
        pd.Timestamp(
            test["fecha_cuota"].max()
        ),
    )

    return (
        {
            **metricas_diarias(pred_test),
            **metricas_cuota(sim),
        },
        sim,
        modelo,
    )


def construir_pool_indices(
    fuentes: dict[str, pd.DataFrame],
    afp: str,
) -> list[dict[str, Any]]:
    screening = fuentes["screening74"]
    catalogo = fuentes["catalogo74"]

    s = screening[
        screening["afp"].astype(str).eq(afp)
        & screening["n_train"].ge(1000)
        & screening["cobertura_train_pct"].ge(90.0)
    ].copy()

    s = s.sort_values(
        [
            "abs_spearman_train",
            "mutual_information_train",
        ],
        ascending=False,
    ).head(MAX_CANDIDATOS_INDICES)

    pool = []

    for _, fila in s.iterrows():
        meta = catalogo[
            catalogo["factor"].astype(str).eq(
                str(fila["factor"])
            )
        ]

        pool.append(
            {
                "factor": str(fila["factor"]),
                "lag": int(
                    fila["mejor_lag_train"]
                ),
                "indice": (
                    str(meta["indice"].iloc[0])
                    if not meta.empty
                    else ""
                ),
                "pais_region": (
                    str(
                        meta["pais_region"].iloc[0]
                    )
                    if not meta.empty
                    else ""
                ),
                "ticker_elegido": (
                    str(
                        meta["ticker_elegido"].iloc[0]
                    )
                    if not meta.empty
                    else ""
                ),
                "moneda_modelo": (
                    str(
                        meta["moneda_modelo"].iloc[0]
                    )
                    if not meta.empty
                    else ""
                ),
                "spearman_train": float(
                    fila["spearman_train"]
                ),
                "pearson_train": float(
                    fila["pearson_train"]
                ),
            }
        )

    return pool


def correlacion_train(
    panel: pd.DataFrame,
    spec_a: dict[str, Any],
    spec_b: dict[str, Any],
    fin_train: pd.Timestamp,
) -> float:
    pf, columnas = materializar(
        panel,
        [spec_a, spec_b],
    )

    train = pf[
        pf["fecha_cuota"].le(fin_train)
    ]

    corr = train[
        columnas
    ].corr().iloc[0, 1]

    return (
        abs(float(corr))
        if pd.notna(corr)
        else 0.0
    )


def max_correlacion_con_canasta(
    panel: pd.DataFrame,
    candidato: dict[str, Any],
    specs: list[dict[str, Any]],
    fin_train: pd.Timestamp,
) -> float:
    if not specs:
        return 0.0

    return max(
        correlacion_train(
            panel,
            candidato,
            existente,
            fin_train,
        )
        for existente in specs
    )


def seleccionar_sustituciones(
    panel: pd.DataFrame,
    specs_iniciales: list[dict[str, Any]],
    pool: list[dict[str, Any]],
    fin_train: pd.Timestamp,
    fin_valid: pd.Timestamp,
    afp: str,
) -> tuple[
    list[dict[str, Any]],
    dict[str, Any],
    pd.DataFrame,
]:
    actuales = [
        dict(x)
        for x in specs_iniciales
    ]

    cfg_actual, _ = evaluar_validacion(
        panel,
        actuales,
        fin_train,
        fin_valid,
    )

    trazas = []

    for paso in range(
        1,
        MAX_SUSTITUCIONES + 1,
    ):
        evaluaciones = []

        for idx, existente in enumerate(
            actuales
        ):
            # Solo tiene sentido sustituir factores que no sean ya
            # índices nativos del módulo 74.
            if str(existente["factor"]).startswith(
                "ret_IDX_LOCAL_"
            ) or str(existente["factor"]).startswith(
                "ret_IDX_PEN_"
            ):
                continue

            for candidato in pool:
                if any(
                    candidato["factor"]
                    == x["factor"]
                    and int(candidato["lag"])
                    == int(x["lag"])
                    for x in actuales
                ):
                    continue

                corr = correlacion_train(
                    panel,
                    existente,
                    candidato,
                    fin_train,
                )

                if corr < UMBRAL_CORRELACION_SUSTITUCION:
                    continue

                propuesta = [
                    dict(x)
                    for x in actuales
                ]
                propuesta[idx] = {
                    **candidato,
                    "origen": "INDICE_NATIVO_SUSTITUCION",
                }

                cfg_nueva, _ = evaluar_validacion(
                    panel,
                    propuesta,
                    fin_train,
                    fin_valid,
                )

                evaluaciones.append(
                    {
                        "idx": idx,
                        "existente": existente,
                        "candidato": candidato,
                        "corr": corr,
                        "propuesta": propuesta,
                        "cfg": cfg_nueva,
                    }
                )

        if not evaluaciones:
            break

        mejor = min(
            evaluaciones,
            key=lambda x: (
                x["cfg"]["mape_cuota_pct"],
                x["cfg"]["p90_error_abs_pct"],
            ),
        )

        cfg_nueva = mejor["cfg"]
        mejora = (
            cfg_actual["mape_cuota_pct"]
            - cfg_nueva["mape_cuota_pct"]
        )

        aceptar = (
            mejora
            >= MEJORA_MINIMA_MAPE_PUNTOS
            and cfg_nueva[
                "p90_error_abs_pct"
            ]
            <= cfg_actual[
                "p90_error_abs_pct"
            ]
            + TOLERANCIA_P90_PUNTOS
        )

        trazas.append(
            {
                "afp": afp,
                "paso": paso,
                "accion": "SUSTITUIR",
                "factor_sale": mejor[
                    "existente"
                ]["factor"],
                "factor_entra": mejor[
                    "candidato"
                ]["factor"],
                "indice_entra": mejor[
                    "candidato"
                ].get("indice", ""),
                "correlacion_train": mejor["corr"],
                "mape_antes_pct": cfg_actual[
                    "mape_cuota_pct"
                ],
                "mape_despues_pct": cfg_nueva[
                    "mape_cuota_pct"
                ],
                "mejora_mape_puntos": mejora,
                "p90_despues_pct": cfg_nueva[
                    "p90_error_abs_pct"
                ],
                "aceptado": aceptar,
            }
        )

        if not aceptar:
            break

        actuales = mejor["propuesta"]
        cfg_actual = cfg_nueva

    return (
        actuales,
        cfg_actual,
        pd.DataFrame(trazas),
    )


def seleccionar_adiciones(
    panel: pd.DataFrame,
    specs_iniciales: list[dict[str, Any]],
    pool: list[dict[str, Any]],
    fin_train: pd.Timestamp,
    fin_valid: pd.Timestamp,
    afp: str,
) -> tuple[
    list[dict[str, Any]],
    dict[str, Any],
    pd.DataFrame,
]:
    actuales = [
        dict(x)
        for x in specs_iniciales
    ]

    cfg_actual, _ = evaluar_validacion(
        panel,
        actuales,
        fin_train,
        fin_valid,
    )

    disponibles = [
        dict(x)
        for x in pool
        if not any(
            x["factor"] == s["factor"]
            and int(x["lag"]) == int(
                s["lag"]
            )
            for s in actuales
        )
    ]

    trazas = []

    for paso in range(
        1,
        MAX_ADICIONES + 1,
    ):
        evaluaciones = []

        for candidato in disponibles:
            corr = max_correlacion_con_canasta(
                panel,
                candidato,
                actuales,
                fin_train,
            )

            if (
                corr
                >= UMBRAL_REDUNDANCIA_ADICION
            ):
                continue

            propuesta = actuales + [
                {
                    **candidato,
                    "origen": "INDICE_NATIVO_ADICION",
                }
            ]

            cfg_nueva, _ = evaluar_validacion(
                panel,
                propuesta,
                fin_train,
                fin_valid,
            )

            evaluaciones.append(
                {
                    "candidato": candidato,
                    "corr": corr,
                    "propuesta": propuesta,
                    "cfg": cfg_nueva,
                }
            )

        if not evaluaciones:
            break

        mejor = min(
            evaluaciones,
            key=lambda x: (
                x["cfg"]["mape_cuota_pct"],
                x["cfg"]["p90_error_abs_pct"],
            ),
        )

        cfg_nueva = mejor["cfg"]
        mejora = (
            cfg_actual["mape_cuota_pct"]
            - cfg_nueva["mape_cuota_pct"]
        )

        aceptar = (
            mejora
            >= MEJORA_MINIMA_MAPE_PUNTOS
            and cfg_nueva[
                "p90_error_abs_pct"
            ]
            <= cfg_actual[
                "p90_error_abs_pct"
            ]
            + TOLERANCIA_P90_PUNTOS
        )

        trazas.append(
            {
                "afp": afp,
                "paso": paso,
                "accion": "AGREGAR",
                "factor_entra": mejor[
                    "candidato"
                ]["factor"],
                "indice_entra": mejor[
                    "candidato"
                ].get("indice", ""),
                "max_corr_con_canasta": mejor[
                    "corr"
                ],
                "mape_antes_pct": cfg_actual[
                    "mape_cuota_pct"
                ],
                "mape_despues_pct": cfg_nueva[
                    "mape_cuota_pct"
                ],
                "mejora_mape_puntos": mejora,
                "p90_despues_pct": cfg_nueva[
                    "p90_error_abs_pct"
                ],
                "aceptado": aceptar,
            }
        )

        if not aceptar:
            break

        actuales = mejor["propuesta"]
        cfg_actual = cfg_nueva

        usados = {
            (
                x["factor"],
                int(x["lag"]),
            )
            for x in actuales
        }

        disponibles = [
            x
            for x in disponibles
            if (
                x["factor"],
                int(x["lag"]),
            )
            not in usados
        ]

    return (
        actuales,
        cfg_actual,
        pd.DataFrame(trazas),
    )


def diebold_mariano(
    perdida_modelo: np.ndarray,
    perdida_referencia: np.ndarray,
    max_lag: int = 5,
) -> dict[str, float]:
    modelo = np.asarray(
        perdida_modelo,
        dtype=float,
    )
    referencia = np.asarray(
        perdida_referencia,
        dtype=float,
    )

    mascara = (
        np.isfinite(modelo)
        & np.isfinite(referencia)
    )

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
    gamma0 = float(
        np.dot(centrado, centrado)
        / n
    )
    var_hac = gamma0

    for lag in range(
        1,
        min(max_lag, n - 1) + 1,
    ):
        gamma = float(
            np.dot(
                centrado[lag:],
                centrado[:-lag],
            )
            / n
        )
        peso = (
            1.0
            - lag / (max_lag + 1.0)
        )
        var_hac += (
            2.0
            * peso
            * gamma
        )

    var_media = var_hac / n

    if var_media <= 0:
        return {
            "n_dm": int(n),
            "diferencia_media_perdida": media,
            "dm_estadistico": np.nan,
            "dm_pvalor": np.nan,
        }

    estadistico = (
        media / math.sqrt(var_media)
    )
    pvalor = float(
        2.0
        * (
            1.0
            - stats.norm.cdf(
                abs(estadistico)
            )
        )
    )

    return {
        "n_dm": int(n),
        "diferencia_media_perdida": media,
        "dm_estadistico": float(
            estadistico
        ),
        "dm_pvalor": pvalor,
    }


def estabilidad_cuartiles(
    sim: pd.DataFrame,
    afp: str,
    tipo_modelo: str,
) -> pd.DataFrame:
    x = sim.sort_values(
        "fecha_hoy_simulada"
    ).copy()

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
        filas.append(
            {
                "afp": afp,
                "tipo_modelo": tipo_modelo,
                "subperiodo": str(
                    subperiodo
                ),
                "fecha_inicio": bloque[
                    "fecha_hoy_simulada"
                ].min(),
                "fecha_fin": bloque[
                    "fecha_hoy_simulada"
                ].max(),
                **metricas_cuota(bloque),
            }
        )

    return pd.DataFrame(filas)


def coeficientes_modelo(
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
                "origen": spec.get(
                    "origen",
                    "",
                ),
                "coeficiente_estandarizado": float(
                    coef
                ),
                "abs_coeficiente": abs(
                    float(coef)
                ),
            }
        )

    return pd.DataFrame(filas).sort_values(
        "abs_coeficiente",
        ascending=False,
    )


def guardar_figura(
    ruta: Path,
) -> None:
    plt.tight_layout()
    plt.savefig(
        ruta,
        dpi=160,
        bbox_inches="tight",
    )
    plt.close()


def main() -> None:
    raiz = Path(__file__).resolve().parents[1]
    processed = raiz / "data" / "processed"
    graficos = processed / "graficos_modelo75"
    graficos.mkdir(
        parents=True,
        exist_ok=True,
    )

    fin_train, fin_valid = cargar_division(
        processed
    )
    fuentes = cargar_fuentes(
        processed
    )

    seleccion_final = []
    trazas_sustitucion = []
    trazas_adicion = []
    metricas_validacion = []
    metricas_prueba = []
    simulaciones = []
    dm_filas = []
    estabilidad_todos = []
    coeficientes_todos = []

    for afp in AFPS:
        print(
            f"\nComparando ETF e índices nativos para {afp}..."
        )

        panel = preparar_panel(
            fuentes,
            afp,
        )

        campeon = construir_campeon_actual(
            fuentes,
            afp,
        )

        pool = construir_pool_indices(
            fuentes,
            afp,
        )

        (
            tras_sustitucion,
            cfg_sustitucion,
            traza_s,
        ) = seleccionar_sustituciones(
            panel,
            campeon,
            pool,
            fin_train,
            fin_valid,
            afp,
        )

        (
            final_specs,
            cfg_final,
            traza_a,
        ) = seleccionar_adiciones(
            panel,
            tras_sustitucion,
            pool,
            fin_train,
            fin_valid,
            afp,
        )

        trazas_sustitucion.append(
            traza_s
        )
        trazas_adicion.append(
            traza_a
        )

        cfg_campeon, _ = evaluar_validacion(
            panel,
            campeon,
            fin_train,
            fin_valid,
        )

        metricas_validacion.extend(
            [
                {
                    "afp": afp,
                    "tipo_modelo": "CAMPEON_PRE_INDICES",
                    "n_factores": len(campeon),
                    "n_indices_nativos": 0,
                    **cfg_campeon,
                },
                {
                    "afp": afp,
                    "tipo_modelo": "CAMPEON_CON_INDICES",
                    "n_factores": len(final_specs),
                    "n_indices_nativos": sum(
                        str(x["factor"]).startswith(
                            "ret_IDX_LOCAL_"
                        )
                        or str(x["factor"]).startswith(
                            "ret_IDX_PEN_"
                        )
                        for x in final_specs
                    ),
                    **cfg_final,
                },
            ]
        )

        (
            met_campeon,
            sim_campeon,
            modelo_campeon,
        ) = evaluar_prueba(
            panel,
            campeon,
            cfg_campeon,
            fin_valid,
        )

        (
            met_final,
            sim_final,
            modelo_final,
        ) = evaluar_prueba(
            panel,
            final_specs,
            cfg_final,
            fin_valid,
        )

        metricas_prueba.extend(
            [
                {
                    "afp": afp,
                    "tipo_modelo": "CAMPEON_PRE_INDICES",
                    "n_factores": len(campeon),
                    "n_indices_nativos": 0,
                    "familia": cfg_campeon[
                        "familia"
                    ],
                    "alpha": cfg_campeon[
                        "alpha"
                    ],
                    "half_life": cfg_campeon[
                        "half_life"
                    ],
                    **met_campeon,
                },
                {
                    "afp": afp,
                    "tipo_modelo": "CAMPEON_CON_INDICES",
                    "n_factores": len(final_specs),
                    "n_indices_nativos": sum(
                        str(x["factor"]).startswith(
                            "ret_IDX_LOCAL_"
                        )
                        or str(x["factor"]).startswith(
                            "ret_IDX_PEN_"
                        )
                        for x in final_specs
                    ),
                    "familia": cfg_final[
                        "familia"
                    ],
                    "alpha": cfg_final[
                        "alpha"
                    ],
                    "half_life": cfg_final[
                        "half_life"
                    ],
                    **met_final,
                },
            ]
        )

        sim_campeon["afp"] = afp
        sim_campeon[
            "tipo_modelo"
        ] = "CAMPEON_PRE_INDICES"

        sim_final["afp"] = afp
        sim_final[
            "tipo_modelo"
        ] = "CAMPEON_CON_INDICES"

        simulaciones.extend(
            [sim_campeon, sim_final]
        )

        estabilidad_todos.extend(
            [
                estabilidad_cuartiles(
                    sim_campeon,
                    afp,
                    "CAMPEON_PRE_INDICES",
                ),
                estabilidad_cuartiles(
                    sim_final,
                    afp,
                    "CAMPEON_CON_INDICES",
                ),
            ]
        )

        unido = sim_final[
            [
                "fecha_hoy_simulada",
                "error_abs_pct",
            ]
        ].rename(
            columns={
                "error_abs_pct": "perdida_indices"
            }
        ).merge(
            sim_campeon[
                [
                    "fecha_hoy_simulada",
                    "error_abs_pct",
                ]
            ].rename(
                columns={
                    "error_abs_pct": "perdida_campeon"
                }
            ),
            on="fecha_hoy_simulada",
            how="inner",
        )

        dm = diebold_mariano(
            unido[
                "perdida_indices"
            ].to_numpy(float),
            unido[
                "perdida_campeon"
            ].to_numpy(float),
            max_lag=5,
        )

        dm_filas.append(
            {
                "afp": afp,
                "modelo": "CAMPEON_CON_INDICES",
                "referencia": "CAMPEON_PRE_INDICES",
                **dm,
                "supera_campeon_con_evidencia": (
                    pd.notna(
                        dm[
                            "diferencia_media_perdida"
                        ]
                    )
                    and pd.notna(
                        dm["dm_pvalor"]
                    )
                    and dm[
                        "diferencia_media_perdida"
                    ]
                    < 0
                    and dm["dm_pvalor"] < 0.05
                ),
            }
        )

        coeficientes_todos.extend(
            [
                coeficientes_modelo(
                    modelo_campeon,
                    campeon,
                    afp,
                    "CAMPEON_PRE_INDICES",
                ),
                coeficientes_modelo(
                    modelo_final,
                    final_specs,
                    afp,
                    "CAMPEON_CON_INDICES",
                ),
            ]
        )

        for orden, spec in enumerate(
            final_specs,
            start=1,
        ):
            meta = fuentes[
                "catalogo74"
            ][
                fuentes["catalogo74"][
                    "factor"
                ].astype(str).eq(
                    str(spec["factor"])
                )
            ]

            seleccion_final.append(
                {
                    "afp": afp,
                    "orden": orden,
                    "factor": spec["factor"],
                    "lag": int(spec["lag"]),
                    "origen": spec.get(
                        "origen",
                        "CAMPEON_PRE_INDICES",
                    ),
                    "es_indice_nativo": (
                        str(spec["factor"]).startswith(
                            "ret_IDX_LOCAL_"
                        )
                        or str(spec["factor"]).startswith(
                            "ret_IDX_PEN_"
                        )
                    ),
                    "indice": (
                        str(
                            meta["indice"].iloc[0]
                        )
                        if not meta.empty
                        else ""
                    ),
                    "pais_region": (
                        str(
                            meta[
                                "pais_region"
                            ].iloc[0]
                        )
                        if not meta.empty
                        else ""
                    ),
                    "ticker_elegido": (
                        str(
                            meta[
                                "ticker_elegido"
                            ].iloc[0]
                        )
                        if not meta.empty
                        else ""
                    ),
                    "moneda_modelo": (
                        str(
                            meta[
                                "moneda_modelo"
                            ].iloc[0]
                        )
                        if not meta.empty
                        else ""
                    ),
                }
            )

        plt.figure(figsize=(12, 5))
        plt.plot(
            sim_final[
                "fecha_hoy_simulada"
            ],
            sim_final["cuota_real_hoy"],
            label="Cuota SBS",
        )
        plt.plot(
            sim_campeon[
                "fecha_hoy_simulada"
            ],
            sim_campeon[
                "cuota_estimada_hoy"
            ],
            label="Campeón previo",
        )
        plt.plot(
            sim_final[
                "fecha_hoy_simulada"
            ],
            sim_final[
                "cuota_estimada_hoy"
            ],
            label="Campeón con índices",
        )
        plt.ylabel("Valor cuota")
        plt.title(
            f"ETF frente a índices nativos — {afp}"
        )
        plt.legend()
        guardar_figura(
            graficos
            / f"01_indices_vs_etf_{afp.lower()}.png"
        )

    seleccion_df = pd.DataFrame(
        seleccion_final
    )

    trazas_s_df = (
        pd.concat(
            [
                x
                for x in trazas_sustitucion
                if not x.empty
            ],
            ignore_index=True,
        )
        if any(
            not x.empty
            for x in trazas_sustitucion
        )
        else pd.DataFrame()
    )

    trazas_a_df = (
        pd.concat(
            [
                x
                for x in trazas_adicion
                if not x.empty
            ],
            ignore_index=True,
        )
        if any(
            not x.empty
            for x in trazas_adicion
        )
        else pd.DataFrame()
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
    dm_df = pd.DataFrame(
        dm_filas
    )

    estabilidad_validos = [
        x
        for x in estabilidad_todos
        if isinstance(x, pd.DataFrame)
        and not x.empty
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
            / "ca0001_modelo75_canasta_con_indices.csv"
        ),
        "sustituciones": (
            processed
            / "ca0001_modelo75_trazabilidad_sustituciones.csv"
        ),
        "adiciones": (
            processed
            / "ca0001_modelo75_trazabilidad_adiciones.csv"
        ),
        "validacion": (
            processed
            / "ca0001_modelo75_metricas_validacion.csv"
        ),
        "prueba": (
            processed
            / "ca0001_modelo75_metricas_prueba.csv"
        ),
        "simulaciones": (
            processed
            / "ca0001_modelo75_simulacion_publicacion_5d.csv"
        ),
        "dm": (
            processed
            / "ca0001_modelo75_diebold_mariano.csv"
        ),
        "estabilidad": (
            processed
            / "ca0001_modelo75_estabilidad_subperiodos.csv"
        ),
        "coeficientes": (
            processed
            / "ca0001_modelo75_coeficientes.csv"
        ),
        "resumen": (
            processed
            / "ca0001_modelo75_resumen.json"
        ),
    }

    seleccion_df.to_csv(
        rutas["seleccion"],
        index=False,
        encoding="utf-8-sig",
    )
    trazas_s_df.to_csv(
        rutas["sustituciones"],
        index=False,
        encoding="utf-8-sig",
    )
    trazas_a_df.to_csv(
        rutas["adiciones"],
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
        "version": "modelo75_indices_nativos_vs_etf",
        "criterio": (
            "Primero se prueban sustituciones de factores existentes "
            "por índices nativos altamente correlacionados. Luego se "
            "prueban adiciones no redundantes. La elección usa solo "
            "entrenamiento y validación; prueba queda para auditoría."
        ),
        "canasta_final": seleccion_df.to_dict(
            orient="records"
        ),
        "metricas_prueba": prueba_df.to_dict(
            orient="records"
        ),
        "diebold_mariano": dm_df.to_dict(
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

    print(
        "\nMÓDULO 75 — ÍNDICES NATIVOS VS ETF"
    )
    print("=" * 170)
    print(
        "Se prueban dos rutas: sustituir ETF/proxies por índices "
        "nativos y agregar índices no redundantes."
    )

    print("\nCANASTA FINAL SELECCIONADA")
    print("-" * 170)
    print(
        seleccion_df.to_string(
            index=False
        )
    )

    print("\nTRAZABILIDAD DE SUSTITUCIONES")
    print("-" * 170)
    if trazas_s_df.empty:
        print(
            "No hubo sustituciones aceptadas."
        )
    else:
        print(
            trazas_s_df.to_string(
                index=False
            )
        )

    print("\nTRAZABILIDAD DE ADICIONES")
    print("-" * 170)
    if trazas_a_df.empty:
        print(
            "No hubo adiciones aceptadas."
        )
    else:
        print(
            trazas_a_df.to_string(
                index=False
            )
        )

    print("\nMÉTRICAS DE VALIDACIÓN")
    print("-" * 170)
    print(
        validacion_df[
            [
                "afp",
                "tipo_modelo",
                "n_factores",
                "n_indices_nativos",
                "familia",
                "alpha",
                "half_life",
                "mape_cuota_pct",
                "p90_error_abs_pct",
                "r2_diario",
                "direccion_diaria_pct",
            ]
        ].to_string(
            index=False
        )
    )

    print("\nMÉTRICAS DE PRUEBA")
    print("-" * 170)
    print(
        prueba_df[
            [
                "afp",
                "tipo_modelo",
                "n_factores",
                "n_indices_nativos",
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
        ].to_string(
            index=False
        )
    )

    print(
        "\nDIEBOLD-MARIANO: ÍNDICES VS CAMPEÓN"
    )
    print("-" * 170)
    print(
        dm_df.to_string(
            index=False
        )
    )

    print("\nARCHIVOS CREADOS")
    print("-" * 170)
    for ruta in rutas.values():
        print(f" - {ruta.resolve()}")
    print(f" - {graficos.resolve()}")

    print(
        "\nLECTURA:\n"
        "- Una sustitución aceptada significa que el índice nativo "
        "representó mejor la señal que el ETF/proxy reemplazado.\n"
        "- Una adición aceptada significa que el índice aportó "
        "información nueva además de la canasta existente.\n"
        "- La adopción definitiva exige que la mejora también aparezca "
        "en prueba y preferiblemente en Diebold-Mariano.\n"
        "- Los índices no son activos comprables por sí mismos; para "
        "operación diaria se seguirá su ticker o un ETF equivalente."
    )


if __name__ == "__main__":
    main()
