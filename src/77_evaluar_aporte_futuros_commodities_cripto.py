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

MIN_N_CANDIDATO = 700
MIN_COBERTURA_CANDIDATO = 65.0
MAX_CAMBIOS = 5

UMBRAL_REDUNDANCIA_ADICION = 0.97
UMBRAL_SUSTITUCION = 0.85
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
    df = leer_csv(processed / "ca0001_modelo50_division_temporal.csv")
    df["fecha_fin"] = pd.to_datetime(df["fecha_fin"], errors="coerce")

    train = df[
        df["segmento"].astype(str).eq("entrenamiento_descubrimiento")
    ]
    valid = df[df["segmento"].astype(str).eq("validacion")]

    if train.empty or valid.empty:
        raise RuntimeError(
            "No se encontró la división temporal del módulo 50."
        )

    return (
        pd.Timestamp(train["fecha_fin"].iloc[0]).normalize(),
        pd.Timestamp(valid["fecha_fin"].iloc[0]).normalize(),
    )


def cargar_fuentes(processed: Path) -> dict[str, pd.DataFrame]:
    archivos = {
        "base": "ca0001_modelo56_base_alineada.csv",
        "factores69": "ca0001_modelo69_factores_ampliados.csv",
        "canasta70": "ca0001_modelo70_canasta_seleccionada.csv",
        "acciones71": "ca0001_modelo71_acciones_seleccionadas.csv",
        "dm71": "ca0001_modelo71_diebold_mariano.csv",
        "factores72": "ca0001_modelo72_factores_bvl.csv",
        "seleccion73": "ca0001_modelo73_factores_bvl_seleccionados.csv",
        "dm73": "ca0001_modelo73_diebold_mariano.csv",
        "factores74": "ca0001_modelo74_factores_indices.csv",
        "canasta75": "ca0001_modelo75_canasta_con_indices.csv",
        "dm75": "ca0001_modelo75_diebold_mariano.csv",
        "factores76": "ca0001_modelo76_factores_futuros_cripto.csv",
        "catalogo76": "ca0001_modelo76_catalogo_futuros_cripto.csv",
        "screening76": "ca0001_modelo76_screening_train.csv",
    }

    fuentes: dict[str, pd.DataFrame] = {}

    opcionales = {"acciones71", "seleccion73"}

    for clave, nombre in archivos.items():
        ruta = processed / nombre

        if not ruta.exists():
            if clave in opcionales:
                fuentes[clave] = pd.DataFrame()
                continue
            raise FileNotFoundError(f"Falta el archivo: {ruta}")

        fuentes[clave] = leer_csv(ruta)

    base = fuentes["base"]
    base["fecha_cuota"] = pd.to_datetime(
        base["fecha_cuota"], errors="coerce"
    ).dt.normalize()
    base["cuota_sbs"] = pd.to_numeric(
        base["cuota_sbs"], errors="coerce"
    )
    base["retorno_cuota"] = pd.to_numeric(
        base["retorno_cuota"], errors="coerce"
    )

    for clave in [
        "factores69",
        "factores72",
        "factores74",
        "factores76",
    ]:
        df = fuentes[clave]
        df["fecha_cuota"] = pd.to_datetime(
            df["fecha_cuota"], errors="coerce"
        ).dt.normalize()

        for columna in df.columns:
            if columna != "fecha_cuota":
                df[columna] = pd.to_numeric(
                    df[columna], errors="coerce"
                )

    for clave, columna in [
        ("canasta70", "lag"),
        ("acciones71", "lag"),
        ("seleccion73", "lag"),
        ("canasta75", "lag"),
    ]:
        df = fuentes[clave]

        if not df.empty and columna in df.columns:
            df[columna] = pd.to_numeric(
                df[columna], errors="coerce"
            ).astype("Int64")

    screen = fuentes["screening76"]

    for columna in [
        "mejor_lag_train",
        "n_train",
        "cobertura_train_pct",
        "spearman_train",
        "pearson_train",
        "mutual_information_train",
        "abs_spearman_train",
    ]:
        screen[columna] = pd.to_numeric(
            screen[columna], errors="coerce"
        )

    return fuentes


def construir_campeon_pre76(
    fuentes: dict[str, pd.DataFrame],
    afp: str,
) -> list[dict[str, Any]]:
    fila_dm75 = fuentes["dm75"][
        fuentes["dm75"]["afp"].astype(str).eq(afp)
    ]

    usar_modelo75 = (
        not fila_dm75.empty
        and a_booleano(
            fila_dm75["supera_campeon_con_evidencia"].iloc[0]
        )
    )

    if usar_modelo75:
        specs = (
            fuentes["canasta75"][
                fuentes["canasta75"]["afp"].astype(str).eq(afp)
            ]
            .sort_values("orden")
            [["factor", "lag"]]
            .dropna()
            .to_dict(orient="records")
        )
    else:
        specs = (
            fuentes["canasta70"][
                fuentes["canasta70"]["afp"].astype(str).eq(afp)
            ]
            .sort_values("orden")
            [["factor", "lag"]]
            .dropna()
            .to_dict(orient="records")
        )

        fila_dm71 = fuentes["dm71"][
            fuentes["dm71"]["afp"].astype(str).eq(afp)
        ]
        usar_acciones = (
            not fila_dm71.empty
            and a_booleano(
                fila_dm71[
                    "supera_modelo70_con_evidencia"
                ].iloc[0]
            )
        )

        if usar_acciones and not fuentes["acciones71"].empty:
            specs.extend(
                fuentes["acciones71"][
                    fuentes["acciones71"]["afp"].astype(str).eq(afp)
                ]
                .sort_values("orden_accion")
                [["factor", "lag"]]
                .dropna()
                .to_dict(orient="records")
            )

        fila_dm73 = fuentes["dm73"][
            fuentes["dm73"]["afp"].astype(str).eq(afp)
        ]
        usar_bvl = (
            not fila_dm73.empty
            and a_booleano(
                fila_dm73[
                    "supera_campeon_con_evidencia"
                ].iloc[0]
            )
        )

        if usar_bvl and not fuentes["seleccion73"].empty:
            specs.extend(
                fuentes["seleccion73"][
                    fuentes["seleccion73"]["afp"].astype(str).eq(afp)
                ]
                .sort_values("orden_bvl")
                [["factor", "lag"]]
                .dropna()
                .to_dict(orient="records")
            )

    resultado = []
    vistos = set()

    for spec in specs:
        clave = (str(spec["factor"]), int(spec["lag"]))

        if clave in vistos:
            continue

        vistos.add(clave)
        resultado.append(
            {
                "factor": clave[0],
                "lag": clave[1],
                "origen": "CAMPEON_PRE76",
            }
        )

    if not resultado:
        raise RuntimeError(
            f"No se pudo construir el campeón previo de {afp}."
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
    ).merge(
        fuentes["factores76"],
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

    x[columnas] = (
        x[columnas]
        .replace([np.inf, -np.inf], np.nan)
        .fillna(0.0)
    )

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

    objetivos = p.index[
        p["fecha_cuota"].ge(fecha_inicio)
        & p["fecha_cuota"].le(fecha_fin)
    ].tolist()

    for i in objetivos:
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
        modelo = ajustar_modelo(
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


def construir_pool(
    fuentes: dict[str, pd.DataFrame],
    afp: str,
    campeon: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    screen = fuentes["screening76"]
    catalogo = fuentes["catalogo76"]

    s = screen[
        screen["afp"].astype(str).eq(afp)
        & screen["n_train"].ge(MIN_N_CANDIDATO)
        & screen["cobertura_train_pct"].ge(
            MIN_COBERTURA_CANDIDATO
        )
    ].copy()

    s = s.merge(
        catalogo,
        on="factor",
        how="left",
        suffixes=("", "_catalogo"),
    )

    # Conserva una sola versión por instrumento: USD o PEN,
    # la que mostró mayor relación absoluta en entrenamiento.
    s = (
        s.sort_values(
            [
                "ticker",
                "abs_spearman_train",
                "mutual_information_train",
            ],
            ascending=[True, False, False],
        )
        .drop_duplicates("ticker", keep="first")
        .sort_values(
            [
                "categoria",
                "abs_spearman_train",
            ],
            ascending=[True, False],
        )
    )

    existentes = {
        (str(x["factor"]), int(x["lag"]))
        for x in campeon
    }

    pool = []

    for _, fila in s.iterrows():
        spec = {
            "factor": str(fila["factor"]),
            "lag": int(fila["mejor_lag_train"]),
            "ticker": str(fila["ticker"]),
            "nombre": str(fila["nombre"]),
            "categoria": str(fila["categoria"]),
            "moneda_modelo": str(fila["moneda_modelo"]),
            "spearman_train": float(fila["spearman_train"]),
            "pearson_train": float(fila["pearson_train"]),
        }

        if (spec["factor"], spec["lag"]) in existentes:
            continue

        pool.append(spec)

    return pool


def correlacion_train(
    panel: pd.DataFrame,
    a: dict[str, Any],
    b: dict[str, Any],
    fin_train: pd.Timestamp,
) -> float:
    pf, columnas = materializar(panel, [a, b])
    train = pf[pf["fecha_cuota"].le(fin_train)]
    corr = train[columnas].corr().iloc[0, 1]

    return abs(float(corr)) if pd.notna(corr) else 0.0


def max_correlacion(
    panel: pd.DataFrame,
    candidato: dict[str, Any],
    specs: list[dict[str, Any]],
    fin_train: pd.Timestamp,
) -> tuple[float, int | None]:
    if not specs:
        return 0.0, None

    valores = [
        correlacion_train(
            panel,
            candidato,
            spec,
            fin_train,
        )
        for spec in specs
    ]

    idx = int(np.argmax(valores))
    return float(valores[idx]), idx


def mejor_operacion_candidato(
    panel: pd.DataFrame,
    specs_actuales: list[dict[str, Any]],
    candidato: dict[str, Any],
    fin_train: pd.Timestamp,
    fin_valid: pd.Timestamp,
) -> dict[str, Any] | None:
    operaciones = []

    max_corr, idx_mas_parecido = max_correlacion(
        panel,
        candidato,
        specs_actuales,
        fin_train,
    )

    if max_corr < UMBRAL_REDUNDANCIA_ADICION:
        propuesta = specs_actuales + [
            {
                **candidato,
                "origen": "MOD76_ADICION",
            }
        ]
        cfg, _ = evaluar_validacion(
            panel,
            propuesta,
            fin_train,
            fin_valid,
        )

        operaciones.append(
            {
                "tipo_operacion": "AGREGAR",
                "factor_sale": "",
                "propuesta": propuesta,
                "cfg": cfg,
                "correlacion_relevante": max_corr,
            }
        )

    if (
        idx_mas_parecido is not None
        and max_corr >= UMBRAL_SUSTITUCION
    ):
        propuesta = [
            dict(x)
            for x in specs_actuales
        ]
        factor_sale = propuesta[
            idx_mas_parecido
        ]["factor"]
        propuesta[idx_mas_parecido] = {
            **candidato,
            "origen": "MOD76_SUSTITUCION",
        }

        cfg, _ = evaluar_validacion(
            panel,
            propuesta,
            fin_train,
            fin_valid,
        )

        operaciones.append(
            {
                "tipo_operacion": "SUSTITUIR",
                "factor_sale": factor_sale,
                "propuesta": propuesta,
                "cfg": cfg,
                "correlacion_relevante": max_corr,
            }
        )

    if not operaciones:
        return None

    return min(
        operaciones,
        key=lambda x: (
            x["cfg"]["mape_cuota_pct"],
            x["cfg"]["p90_error_abs_pct"],
        ),
    )


def ranking_individual(
    panel: pd.DataFrame,
    campeon: list[dict[str, Any]],
    pool: list[dict[str, Any]],
    fin_train: pd.Timestamp,
    fin_valid: pd.Timestamp,
    afp: str,
) -> pd.DataFrame:
    cfg_base, _ = evaluar_validacion(
        panel,
        campeon,
        fin_train,
        fin_valid,
    )

    filas = []

    for candidato in pool:
        operacion = mejor_operacion_candidato(
            panel,
            campeon,
            candidato,
            fin_train,
            fin_valid,
        )

        if operacion is None:
            continue

        cfg = operacion["cfg"]
        mejora = (
            cfg_base["mape_cuota_pct"]
            - cfg["mape_cuota_pct"]
        )

        aceptado = (
            mejora >= MEJORA_MINIMA_MAPE_PUNTOS
            and cfg["p90_error_abs_pct"]
            <= cfg_base["p90_error_abs_pct"]
            + TOLERANCIA_P90_PUNTOS
        )

        filas.append(
            {
                "afp": afp,
                "ticker": candidato["ticker"],
                "nombre": candidato["nombre"],
                "categoria": candidato["categoria"],
                "factor": candidato["factor"],
                "lag": candidato["lag"],
                "moneda_modelo": candidato["moneda_modelo"],
                "operacion_preferida": operacion["tipo_operacion"],
                "factor_sale": operacion["factor_sale"],
                "correlacion_relevante": operacion[
                    "correlacion_relevante"
                ],
                "mape_base_pct": cfg_base["mape_cuota_pct"],
                "mape_candidato_pct": cfg["mape_cuota_pct"],
                "mejora_mape_puntos": mejora,
                "p90_base_pct": cfg_base["p90_error_abs_pct"],
                "p90_candidato_pct": cfg["p90_error_abs_pct"],
                "familia": cfg["familia"],
                "alpha": cfg["alpha"],
                "half_life": cfg["half_life"],
                "aceptado_validacion": aceptado,
            }
        )

    if not filas:
        return pd.DataFrame()

    return pd.DataFrame(filas).sort_values(
        [
            "mape_candidato_pct",
            "p90_candidato_pct",
        ]
    ).reset_index(drop=True)


def seleccion_forward(
    panel: pd.DataFrame,
    campeon: list[dict[str, Any]],
    pool: list[dict[str, Any]],
    fin_train: pd.Timestamp,
    fin_valid: pd.Timestamp,
    afp: str,
) -> tuple[
    list[dict[str, Any]],
    dict[str, Any],
    pd.DataFrame,
]:
    actuales = [dict(x) for x in campeon]
    cfg_actual, _ = evaluar_validacion(
        panel,
        actuales,
        fin_train,
        fin_valid,
    )
    disponibles = [dict(x) for x in pool]

    trazas = [
        {
            "afp": afp,
            "paso": 0,
            "accion": "CAMPEON_PRE76",
            "ticker": "",
            "nombre": "",
            "categoria": "",
            "factor_entra": "",
            "factor_sale": "",
            "mape_antes_pct": np.nan,
            "mape_despues_pct": cfg_actual["mape_cuota_pct"],
            "mejora_mape_puntos": np.nan,
            "p90_despues_pct": cfg_actual["p90_error_abs_pct"],
            "aceptado": True,
        }
    ]

    for paso in range(1, MAX_CAMBIOS + 1):
        evaluaciones = []

        for candidato in disponibles:
            operacion = mejor_operacion_candidato(
                panel,
                actuales,
                candidato,
                fin_train,
                fin_valid,
            )

            if operacion is None:
                continue

            evaluaciones.append(
                {
                    "candidato": candidato,
                    **operacion,
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
            mejora >= MEJORA_MINIMA_MAPE_PUNTOS
            and cfg_nueva["p90_error_abs_pct"]
            <= cfg_actual["p90_error_abs_pct"]
            + TOLERANCIA_P90_PUNTOS
        )

        candidato = mejor["candidato"]

        trazas.append(
            {
                "afp": afp,
                "paso": paso,
                "accion": mejor["tipo_operacion"],
                "ticker": candidato["ticker"],
                "nombre": candidato["nombre"],
                "categoria": candidato["categoria"],
                "factor_entra": candidato["factor"],
                "factor_sale": mejor["factor_sale"],
                "mape_antes_pct": cfg_actual["mape_cuota_pct"],
                "mape_despues_pct": cfg_nueva["mape_cuota_pct"],
                "mejora_mape_puntos": mejora,
                "p90_despues_pct": cfg_nueva["p90_error_abs_pct"],
                "aceptado": aceptar,
            }
        )

        if not aceptar:
            break

        actuales = mejor["propuesta"]
        cfg_actual = cfg_nueva

        disponibles = [
            x
            for x in disponibles
            if x["ticker"] != candidato["ticker"]
        ]

    return actuales, cfg_actual, pd.DataFrame(trazas)


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


def coeficientes(
    modelo: ModeloRidge,
    specs: list[dict[str, Any]],
    afp: str,
    tipo_modelo: str,
) -> pd.DataFrame:
    filas = []

    for spec, coef in zip(specs, modelo.ridge.coef_):
        filas.append(
            {
                "afp": afp,
                "tipo_modelo": tipo_modelo,
                "factor": spec["factor"],
                "lag": spec["lag"],
                "origen": spec.get("origen", ""),
                "coeficiente_estandarizado": float(coef),
                "abs_coeficiente": abs(float(coef)),
            }
        )

    return pd.DataFrame(filas).sort_values(
        "abs_coeficiente",
        ascending=False,
    )


def main() -> None:
    raiz = Path(__file__).resolve().parents[1]
    processed = raiz / "data" / "processed"
    graficos = processed / "graficos_modelo77"
    graficos.mkdir(parents=True, exist_ok=True)

    fin_train, fin_valid = cargar_division(processed)
    fuentes = cargar_fuentes(processed)

    ranking_todos = []
    trazas_todas = []
    seleccion_final = []
    metricas_validacion = []
    metricas_prueba = []
    simulaciones = []
    dm_filas = []
    coeficientes_todos = []

    for afp in AFPS:
        print(
            f"\nEvaluando futuros, commodities y cripto para {afp}..."
        )

        panel = preparar_panel(fuentes, afp)
        campeon = construir_campeon_pre76(fuentes, afp)
        pool = construir_pool(fuentes, afp, campeon)

        ranking = ranking_individual(
            panel,
            campeon,
            pool,
            fin_train,
            fin_valid,
            afp,
        )
        ranking_todos.append(ranking)

        final_specs, cfg_final, traza = seleccion_forward(
            panel,
            campeon,
            pool,
            fin_train,
            fin_valid,
            afp,
        )
        trazas_todas.append(traza)

        cfg_base, _ = evaluar_validacion(
            panel,
            campeon,
            fin_train,
            fin_valid,
        )

        metricas_validacion.extend(
            [
                {
                    "afp": afp,
                    "tipo_modelo": "CAMPEON_PRE76",
                    "n_factores": len(campeon),
                    "n_factores_mod76": 0,
                    **cfg_base,
                },
                {
                    "afp": afp,
                    "tipo_modelo": "CAMPEON_CON_MOD76",
                    "n_factores": len(final_specs),
                    "n_factores_mod76": sum(
                        str(x.get("origen", "")).startswith("MOD76_")
                        for x in final_specs
                    ),
                    **cfg_final,
                },
            ]
        )

        met_base, sim_base, modelo_base = evaluar_prueba(
            panel,
            campeon,
            cfg_base,
            fin_valid,
        )
        met_final, sim_final, modelo_final = evaluar_prueba(
            panel,
            final_specs,
            cfg_final,
            fin_valid,
        )

        metricas_prueba.extend(
            [
                {
                    "afp": afp,
                    "tipo_modelo": "CAMPEON_PRE76",
                    "n_factores": len(campeon),
                    "n_factores_mod76": 0,
                    "familia": cfg_base["familia"],
                    "alpha": cfg_base["alpha"],
                    "half_life": cfg_base["half_life"],
                    **met_base,
                },
                {
                    "afp": afp,
                    "tipo_modelo": "CAMPEON_CON_MOD76",
                    "n_factores": len(final_specs),
                    "n_factores_mod76": sum(
                        str(x.get("origen", "")).startswith("MOD76_")
                        for x in final_specs
                    ),
                    "familia": cfg_final["familia"],
                    "alpha": cfg_final["alpha"],
                    "half_life": cfg_final["half_life"],
                    **met_final,
                },
            ]
        )

        sim_base["afp"] = afp
        sim_base["tipo_modelo"] = "CAMPEON_PRE76"
        sim_final["afp"] = afp
        sim_final["tipo_modelo"] = "CAMPEON_CON_MOD76"
        simulaciones.extend([sim_base, sim_final])

        unido = sim_final[
            ["fecha_hoy_simulada", "error_abs_pct"]
        ].rename(
            columns={"error_abs_pct": "perdida_mod76"}
        ).merge(
            sim_base[
                ["fecha_hoy_simulada", "error_abs_pct"]
            ].rename(
                columns={"error_abs_pct": "perdida_base"}
            ),
            on="fecha_hoy_simulada",
            how="inner",
        )

        dm = diebold_mariano(
            unido["perdida_mod76"].to_numpy(float),
            unido["perdida_base"].to_numpy(float),
            max_lag=5,
        )

        dm_filas.append(
            {
                "afp": afp,
                "modelo": "CAMPEON_CON_MOD76",
                "referencia": "CAMPEON_PRE76",
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
                    modelo_base,
                    campeon,
                    afp,
                    "CAMPEON_PRE76",
                ),
                coeficientes(
                    modelo_final,
                    final_specs,
                    afp,
                    "CAMPEON_CON_MOD76",
                ),
            ]
        )

        for orden, spec in enumerate(final_specs, start=1):
            meta = fuentes["catalogo76"][
                fuentes["catalogo76"]["factor"]
                .astype(str)
                .eq(str(spec["factor"]))
            ]

            seleccion_final.append(
                {
                    "afp": afp,
                    "orden": orden,
                    "factor": spec["factor"],
                    "lag": int(spec["lag"]),
                    "origen": spec.get("origen", "CAMPEON_PRE76"),
                    "es_factor_mod76": str(
                        spec.get("origen", "")
                    ).startswith("MOD76_"),
                    "ticker": (
                        str(meta["ticker"].iloc[0])
                        if not meta.empty
                        else ""
                    ),
                    "nombre": (
                        str(meta["nombre"].iloc[0])
                        if not meta.empty
                        else ""
                    ),
                    "categoria": (
                        str(meta["categoria"].iloc[0])
                        if not meta.empty
                        else ""
                    ),
                    "moneda_modelo": (
                        str(meta["moneda_modelo"].iloc[0])
                        if not meta.empty
                        else ""
                    ),
                }
            )

        plt.figure(figsize=(12, 5))
        plt.plot(
            sim_final["fecha_hoy_simulada"],
            sim_final["cuota_real_hoy"],
            label="Cuota SBS",
        )
        plt.plot(
            sim_base["fecha_hoy_simulada"],
            sim_base["cuota_estimada_hoy"],
            label="Campeón previo",
        )
        plt.plot(
            sim_final["fecha_hoy_simulada"],
            sim_final["cuota_estimada_hoy"],
            label="Campeón + módulo 76",
        )
        plt.ylabel("Valor cuota")
        plt.title(
            f"Futuros, commodities y cripto — {afp}"
        )
        plt.legend()
        plt.tight_layout()
        plt.savefig(
            graficos / f"01_mod76_{afp.lower()}.png",
            dpi=160,
            bbox_inches="tight",
        )
        plt.close()

    ranking_validos = [
        x for x in ranking_todos
        if isinstance(x, pd.DataFrame) and not x.empty
    ]
    ranking_df = (
        pd.concat(ranking_validos, ignore_index=True)
        if ranking_validos
        else pd.DataFrame()
    )

    trazas_df = pd.concat(
        trazas_todas,
        ignore_index=True,
    )
    seleccion_df = pd.DataFrame(seleccion_final)
    validacion_df = pd.DataFrame(metricas_validacion)
    prueba_df = pd.DataFrame(metricas_prueba)
    simulaciones_df = pd.concat(
        simulaciones,
        ignore_index=True,
    )
    dm_df = pd.DataFrame(dm_filas)
    coeficientes_df = pd.concat(
        coeficientes_todos,
        ignore_index=True,
    )

    if not ranking_df.empty:
        categorias_df = (
            ranking_df.sort_values(
                [
                    "afp",
                    "categoria",
                    "mape_candidato_pct",
                ]
            )
            .groupby(
                ["afp", "categoria"],
                as_index=False,
            )
            .first()
        )
    else:
        categorias_df = pd.DataFrame()

    rutas = {
        "ranking": (
            processed
            / "ca0001_modelo77_ranking_individual_validacion.csv"
        ),
        "categorias": (
            processed
            / "ca0001_modelo77_mejor_por_categoria.csv"
        ),
        "seleccion": (
            processed
            / "ca0001_modelo77_canasta_final.csv"
        ),
        "trazabilidad": (
            processed
            / "ca0001_modelo77_trazabilidad_forward.csv"
        ),
        "validacion": (
            processed
            / "ca0001_modelo77_metricas_validacion.csv"
        ),
        "prueba": (
            processed
            / "ca0001_modelo77_metricas_prueba.csv"
        ),
        "simulaciones": (
            processed
            / "ca0001_modelo77_simulacion_publicacion_5d.csv"
        ),
        "dm": (
            processed
            / "ca0001_modelo77_diebold_mariano.csv"
        ),
        "coeficientes": (
            processed
            / "ca0001_modelo77_coeficientes.csv"
        ),
        "resumen": (
            processed
            / "ca0001_modelo77_resumen.json"
        ),
    }

    ranking_df.to_csv(
        rutas["ranking"],
        index=False,
        encoding="utf-8-sig",
    )
    categorias_df.to_csv(
        rutas["categorias"],
        index=False,
        encoding="utf-8-sig",
    )
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
    coeficientes_df.to_csv(
        rutas["coeficientes"],
        index=False,
        encoding="utf-8-sig",
    )

    resumen = {
        "version": "modelo77_aporte_incremental_futuros_commodities_cripto",
        "criterio_campeon": (
            "Se usa el modelo 75 solo donde superó al campeón con "
            "evidencia Diebold-Mariano; en los demás casos se conserva "
            "el último campeón estadísticamente respaldado."
        ),
        "canasta_final": seleccion_df.to_dict(orient="records"),
        "metricas_prueba": prueba_df.to_dict(orient="records"),
        "diebold_mariano": dm_df.to_dict(orient="records"),
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
        "\nMÓDULO 77 — APORTE INCREMENTAL DE FUTUROS, "
        "COMMODITIES Y CRIPTO"
    )
    print("=" * 170)

    print("\nMEJOR CANDIDATO POR CATEGORÍA — VALIDACIÓN")
    print("-" * 170)
    if categorias_df.empty:
        print("No se generaron candidatos válidos.")
    else:
        print(
            categorias_df[
                [
                    "afp",
                    "categoria",
                    "ticker",
                    "nombre",
                    "moneda_modelo",
                    "operacion_preferida",
                    "factor_sale",
                    "mape_base_pct",
                    "mape_candidato_pct",
                    "mejora_mape_puntos",
                    "p90_candidato_pct",
                    "aceptado_validacion",
                ]
            ].to_string(index=False)
        )

    print("\nTRAZABILIDAD FORWARD")
    print("-" * 170)
    print(trazas_df.to_string(index=False))

    print("\nCANASTA RESULTANTE")
    print("-" * 170)
    print(seleccion_df.to_string(index=False))

    print("\nMÉTRICAS DE VALIDACIÓN")
    print("-" * 170)
    print(
        validacion_df[
            [
                "afp",
                "tipo_modelo",
                "n_factores",
                "n_factores_mod76",
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
    print("-" * 170)
    print(
        prueba_df[
            [
                "afp",
                "tipo_modelo",
                "n_factores",
                "n_factores_mod76",
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

    print("\nDIEBOLD-MARIANO")
    print("-" * 170)
    print(dm_df.to_string(index=False))

    print("\nARCHIVOS CREADOS")
    print("-" * 170)
    for ruta in rutas.values():
        print(f" - {ruta.resolve()}")
    print(f" - {graficos.resolve()}")

    print(
        "\nLECTURA:\n"
        "- El ranking por categoría impide que los futuros bursátiles "
        "oculten automáticamente a oro, petróleo, bonos o cripto.\n"
        "- Un futuro puede sustituir a un ETF/índice muy parecido o "
        "agregarse cuando aporta información diferente.\n"
        "- La selección usa validación; la prueba y Diebold-Mariano "
        "determinan si la mejora merece adoptarse.\n"
        "- Cripto se interpreta como proxy de apetito por riesgo, no "
        "como tenencia confirmada de una AFP."
    )


if __name__ == "__main__":
    main()
