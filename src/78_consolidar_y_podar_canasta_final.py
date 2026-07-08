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

# Poda final: se permite una pérdida muy pequeña de validación
# a cambio de reducir el número de factores.
TOLERANCIA_MAPE_PODA_PUNTOS = 0.0015
TOLERANCIA_P90_PODA_PUNTOS = 0.03
MAX_CAIDA_DIRECCION_PUNTOS = 0.75


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


def leer_csv(ruta: Path, obligatorio: bool = True) -> pd.DataFrame:
    if not ruta.exists():
        if obligatorio:
            raise FileNotFoundError(f"Falta el archivo: {ruta}")
        return pd.DataFrame()

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
        "true", "1", "si", "sí", "yes"
    }


def cargar_division(processed: Path) -> tuple[pd.Timestamp, pd.Timestamp]:
    df = leer_csv(processed / "ca0001_modelo50_division_temporal.csv")
    df["fecha_fin"] = pd.to_datetime(df["fecha_fin"], errors="coerce")

    train = df[
        df["segmento"].astype(str).eq("entrenamiento_descubrimiento")
    ]
    valid = df[df["segmento"].astype(str).eq("validacion")]

    if train.empty or valid.empty:
        raise RuntimeError("No se encontró la división temporal del módulo 50.")

    return (
        pd.Timestamp(train["fecha_fin"].iloc[0]).normalize(),
        pd.Timestamp(valid["fecha_fin"].iloc[0]).normalize(),
    )


def cargar_fuentes(processed: Path) -> dict[str, pd.DataFrame]:
    archivos = {
        "base": ("ca0001_modelo56_base_alineada.csv", True),
        "factores69": ("ca0001_modelo69_factores_ampliados.csv", True),
        "catalogo69": ("ca0001_modelo69_catalogo_factores.csv", False),
        "canasta70": ("ca0001_modelo70_canasta_seleccionada.csv", True),
        "acciones71": ("ca0001_modelo71_acciones_seleccionadas.csv", False),
        "dm71": ("ca0001_modelo71_diebold_mariano.csv", True),
        "factores72": ("ca0001_modelo72_factores_bvl.csv", True),
        "catalogo72": ("ca0001_modelo72_catalogo_factores_bvl.csv", False),
        "seleccion73": ("ca0001_modelo73_factores_bvl_seleccionados.csv", False),
        "dm73": ("ca0001_modelo73_diebold_mariano.csv", True),
        "factores74": ("ca0001_modelo74_factores_indices.csv", True),
        "catalogo74": ("ca0001_modelo74_catalogo_indices.csv", False),
        "canasta75": ("ca0001_modelo75_canasta_con_indices.csv", True),
        "dm75": ("ca0001_modelo75_diebold_mariano.csv", True),
        "factores76": ("ca0001_modelo76_factores_futuros_cripto.csv", True),
        "catalogo76": ("ca0001_modelo76_catalogo_futuros_cripto.csv", False),
        "canasta77": ("ca0001_modelo77_canasta_final.csv", True),
        "dm77": ("ca0001_modelo77_diebold_mariano.csv", True),
    }

    fuentes: dict[str, pd.DataFrame] = {}

    for clave, (nombre, obligatorio) in archivos.items():
        fuentes[clave] = leer_csv(
            processed / nombre,
            obligatorio=obligatorio,
        )

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

    for clave in ["factores69", "factores72", "factores74", "factores76"]:
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
        ("canasta77", "lag"),
    ]:
        df = fuentes[clave]
        if not df.empty and columna in df.columns:
            df[columna] = pd.to_numeric(
                df[columna], errors="coerce"
            ).astype("Int64")

    return fuentes


def dm_favorable(
    df: pd.DataFrame,
    afp: str,
    columna_bool: str,
) -> bool:
    fila = df[df["afp"].astype(str).eq(afp)]
    if fila.empty or columna_bool not in fila.columns:
        return False
    return a_booleano(fila[columna_bool].iloc[0])


def construir_campeon_evidencia(
    fuentes: dict[str, pd.DataFrame],
    afp: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    historial = ["M70"]

    specs = (
        fuentes["canasta70"][
            fuentes["canasta70"]["afp"].astype(str).eq(afp)
        ]
        .sort_values("orden")
        [["factor", "lag"]]
        .dropna()
        .to_dict(orient="records")
    )

    if dm_favorable(
        fuentes["dm71"],
        afp,
        "supera_modelo70_con_evidencia",
    ) and not fuentes["acciones71"].empty:
        specs.extend(
            fuentes["acciones71"][
                fuentes["acciones71"]["afp"].astype(str).eq(afp)
            ]
            .sort_values("orden_accion")
            [["factor", "lag"]]
            .dropna()
            .to_dict(orient="records")
        )
        historial.append("M71")

    if dm_favorable(
        fuentes["dm73"],
        afp,
        "supera_campeon_con_evidencia",
    ) and not fuentes["seleccion73"].empty:
        specs.extend(
            fuentes["seleccion73"][
                fuentes["seleccion73"]["afp"].astype(str).eq(afp)
            ]
            .sort_values("orden_bvl")
            [["factor", "lag"]]
            .dropna()
            .to_dict(orient="records")
        )
        historial.append("M73")

    if dm_favorable(
        fuentes["dm75"],
        afp,
        "supera_campeon_con_evidencia",
    ):
        specs = (
            fuentes["canasta75"][
                fuentes["canasta75"]["afp"].astype(str).eq(afp)
            ]
            .sort_values("orden")
            [["factor", "lag"]]
            .dropna()
            .to_dict(orient="records")
        )
        historial.append("M75")

    if dm_favorable(
        fuentes["dm77"],
        afp,
        "supera_campeon_con_evidencia",
    ):
        specs = (
            fuentes["canasta77"][
                fuentes["canasta77"]["afp"].astype(str).eq(afp)
            ]
            .sort_values("orden")
            [["factor", "lag"]]
            .dropna()
            .to_dict(orient="records")
        )
        historial.append("M77")

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
            }
        )

    if not resultado:
        raise RuntimeError(f"No se pudo construir el campeón de {afp}.")

    return resultado, historial


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
    columnas = []

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
    filas = []

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
            "direccion_diaria_pct": np.nan,
        }

    real = x["retorno_cuota"].to_numpy(float)
    estimado = x["retorno_estimado"].to_numpy(float)
    mascara = np.abs(estimado) > 1e-15

    return {
        "n_diario": int(len(x)),
        "mae_diario": float(
            mean_absolute_error(real, estimado)
        ),
        "rmse_diario": float(
            mean_squared_error(real, estimado) ** 0.5
        ),
        "r2_diario": float(r2_score(real, estimado)),
        "direccion_diaria_pct": (
            float(
                (
                    np.sign(real[mascara])
                    == np.sign(estimado[mascara])
                ).mean()
                * 100.0
            )
            if mascara.any()
            else np.nan
        ),
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
            "direccion_acumulada_pct": np.nan,
        }

    real = sim["retorno_acumulado_real"].to_numpy(float)
    estimado = sim["retorno_acumulado_estimado"].to_numpy(float)
    mascara = np.abs(estimado) > 1e-15

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
        "direccion_acumulada_pct": (
            float(
                (
                    np.sign(real[mascara])
                    == np.sign(estimado[mascara])
                ).mean()
                * 100.0
            )
            if mascara.any()
            else np.nan
        ),
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
) -> tuple[dict[str, Any], pd.DataFrame, ModeloRidge]:
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


def podar_backward(
    panel: pd.DataFrame,
    specs_iniciales: list[dict[str, Any]],
    fin_train: pd.Timestamp,
    fin_valid: pd.Timestamp,
    afp: str,
) -> tuple[list[dict[str, Any]], dict[str, Any], pd.DataFrame]:
    actuales = [dict(x) for x in specs_iniciales]
    cfg_actual, _ = evaluar_validacion(
        panel, actuales, fin_train, fin_valid
    )

    trazas = [
        {
            "afp": afp,
            "paso": 0,
            "accion": "CANASTA_EVIDENCIA",
            "factor_retirado": "",
            "n_factores_antes": len(actuales),
            "n_factores_despues": len(actuales),
            "mape_antes_pct": np.nan,
            "mape_despues_pct": cfg_actual["mape_cuota_pct"],
            "cambio_mape_puntos": np.nan,
            "p90_despues_pct": cfg_actual["p90_error_abs_pct"],
            "direccion_despues_pct": cfg_actual["direccion_diaria_pct"],
            "aceptado": True,
        }
    ]

    paso = 1

    while len(actuales) > 1:
        candidatos = []

        for idx, spec in enumerate(actuales):
            propuesta = [
                dict(x)
                for j, x in enumerate(actuales)
                if j != idx
            ]

            cfg_nueva, _ = evaluar_validacion(
                panel,
                propuesta,
                fin_train,
                fin_valid,
            )

            cambio_mape = (
                cfg_nueva["mape_cuota_pct"]
                - cfg_actual["mape_cuota_pct"]
            )
            cambio_direccion = (
                cfg_actual["direccion_diaria_pct"]
                - cfg_nueva["direccion_diaria_pct"]
            )

            aceptable = (
                cambio_mape <= TOLERANCIA_MAPE_PODA_PUNTOS
                and cfg_nueva["p90_error_abs_pct"]
                <= cfg_actual["p90_error_abs_pct"]
                + TOLERANCIA_P90_PODA_PUNTOS
                and cambio_direccion
                <= MAX_CAIDA_DIRECCION_PUNTOS
            )

            candidatos.append(
                {
                    "idx": idx,
                    "factor": spec["factor"],
                    "propuesta": propuesta,
                    "cfg": cfg_nueva,
                    "cambio_mape": cambio_mape,
                    "aceptable": aceptable,
                }
            )

        aceptables = [
            x for x in candidatos
            if x["aceptable"]
        ]

        if not aceptables:
            break

        mejor = min(
            aceptables,
            key=lambda x: (
                x["cfg"]["mape_cuota_pct"],
                x["cfg"]["p90_error_abs_pct"],
            ),
        )

        trazas.append(
            {
                "afp": afp,
                "paso": paso,
                "accion": "RETIRAR",
                "factor_retirado": mejor["factor"],
                "n_factores_antes": len(actuales),
                "n_factores_despues": len(mejor["propuesta"]),
                "mape_antes_pct": cfg_actual["mape_cuota_pct"],
                "mape_despues_pct": mejor["cfg"]["mape_cuota_pct"],
                "cambio_mape_puntos": mejor["cambio_mape"],
                "p90_despues_pct": mejor["cfg"]["p90_error_abs_pct"],
                "direccion_despues_pct": mejor["cfg"]["direccion_diaria_pct"],
                "aceptado": True,
            }
        )

        actuales = mejor["propuesta"]
        cfg_actual = mejor["cfg"]
        paso += 1

    if paso == 1:
        trazas.append(
            {
                "afp": afp,
                "paso": 1,
                "accion": "SIN_RETIROS",
                "factor_retirado": "",
                "n_factores_antes": len(actuales),
                "n_factores_despues": len(actuales),
                "mape_antes_pct": cfg_actual["mape_cuota_pct"],
                "mape_despues_pct": cfg_actual["mape_cuota_pct"],
                "cambio_mape_puntos": 0.0,
                "p90_despues_pct": cfg_actual["p90_error_abs_pct"],
                "direccion_despues_pct": cfg_actual["direccion_diaria_pct"],
                "aceptado": False,
            }
        )

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


def construir_metadatos(
    fuentes: dict[str, pd.DataFrame],
) -> dict[str, dict[str, Any]]:
    meta: dict[str, dict[str, Any]] = {}

    def registrar(
        df: pd.DataFrame,
        nombre_col: str | None,
        ticker_col: str | None,
        categoria_col: str | None,
        moneda_col: str | None,
        origen: str,
    ) -> None:
        if df.empty or "factor" not in df.columns:
            return

        for _, fila in df.iterrows():
            factor = str(fila["factor"])

            meta[factor] = {
                "nombre": (
                    str(fila[nombre_col])
                    if nombre_col and nombre_col in df.columns
                    and pd.notna(fila[nombre_col])
                    else ""
                ),
                "ticker": (
                    str(fila[ticker_col])
                    if ticker_col and ticker_col in df.columns
                    and pd.notna(fila[ticker_col])
                    else ""
                ),
                "categoria": (
                    str(fila[categoria_col])
                    if categoria_col and categoria_col in df.columns
                    and pd.notna(fila[categoria_col])
                    else ""
                ),
                "moneda_modelo": (
                    str(fila[moneda_col])
                    if moneda_col and moneda_col in df.columns
                    and pd.notna(fila[moneda_col])
                    else ""
                ),
                "fuente_catalogo": origen,
            }

    registrar(
        fuentes["catalogo69"],
        "nombre",
        "ticker",
        "categoria",
        "moneda_modelo",
        "M69",
    )
    registrar(
        fuentes["catalogo72"],
        "instrumento",
        "ticker_elegido",
        "tipo",
        "moneda_modelo",
        "M72",
    )
    registrar(
        fuentes["catalogo74"],
        "indice",
        "ticker_elegido",
        "pais_region",
        "moneda_modelo",
        "M74",
    )
    registrar(
        fuentes["catalogo76"],
        "nombre",
        "ticker",
        "categoria",
        "moneda_modelo",
        "M76",
    )

    return meta


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
    graficos = processed / "graficos_modelo78"
    graficos.mkdir(parents=True, exist_ok=True)

    fin_train, fin_valid = cargar_division(processed)
    fuentes = cargar_fuentes(processed)
    metadatos = construir_metadatos(fuentes)

    canasta_evidencia_todos = []
    canasta_podada_todos = []
    trazas_todas = []
    validacion_todas = []
    prueba_todas = []
    simulaciones = []
    dm_filas = []
    coeficientes_todos = []
    historial_filas = []

    for afp in AFPS:
        print(f"\nConsolidando y podando la canasta de {afp}...")

        panel = preparar_panel(fuentes, afp)
        canasta_evidencia, historial = construir_campeon_evidencia(
            fuentes,
            afp,
        )

        podada, cfg_podada, traza = podar_backward(
            panel,
            canasta_evidencia,
            fin_train,
            fin_valid,
            afp,
        )
        trazas_todas.append(traza)

        cfg_evidencia, _ = evaluar_validacion(
            panel,
            canasta_evidencia,
            fin_train,
            fin_valid,
        )

        validacion_todas.extend(
            [
                {
                    "afp": afp,
                    "tipo_modelo": "CANASTA_EVIDENCIA",
                    "n_factores": len(canasta_evidencia),
                    **cfg_evidencia,
                },
                {
                    "afp": afp,
                    "tipo_modelo": "CANASTA_PODADA",
                    "n_factores": len(podada),
                    **cfg_podada,
                },
            ]
        )

        met_evidencia, sim_evidencia, modelo_evidencia = evaluar_prueba(
            panel,
            canasta_evidencia,
            cfg_evidencia,
            fin_valid,
        )
        met_podada, sim_podada, modelo_podada = evaluar_prueba(
            panel,
            podada,
            cfg_podada,
            fin_valid,
        )

        prueba_todas.extend(
            [
                {
                    "afp": afp,
                    "tipo_modelo": "CANASTA_EVIDENCIA",
                    "n_factores": len(canasta_evidencia),
                    "familia": cfg_evidencia["familia"],
                    "alpha": cfg_evidencia["alpha"],
                    "half_life": cfg_evidencia["half_life"],
                    **met_evidencia,
                },
                {
                    "afp": afp,
                    "tipo_modelo": "CANASTA_PODADA",
                    "n_factores": len(podada),
                    "familia": cfg_podada["familia"],
                    "alpha": cfg_podada["alpha"],
                    "half_life": cfg_podada["half_life"],
                    **met_podada,
                },
            ]
        )

        sim_evidencia["afp"] = afp
        sim_evidencia["tipo_modelo"] = "CANASTA_EVIDENCIA"
        sim_podada["afp"] = afp
        sim_podada["tipo_modelo"] = "CANASTA_PODADA"
        simulaciones.extend([sim_evidencia, sim_podada])

        unido = sim_podada[
            ["fecha_hoy_simulada", "error_abs_pct"]
        ].rename(
            columns={"error_abs_pct": "perdida_podada"}
        ).merge(
            sim_evidencia[
                ["fecha_hoy_simulada", "error_abs_pct"]
            ].rename(
                columns={"error_abs_pct": "perdida_evidencia"}
            ),
            on="fecha_hoy_simulada",
            how="inner",
        )

        dm = diebold_mariano(
            unido["perdida_podada"].to_numpy(float),
            unido["perdida_evidencia"].to_numpy(float),
            max_lag=5,
        )

        dm_filas.append(
            {
                "afp": afp,
                "modelo": "CANASTA_PODADA",
                "referencia": "CANASTA_EVIDENCIA",
                **dm,
                "poda_no_empeora_con_evidencia": (
                    pd.notna(dm["diferencia_media_perdida"])
                    and pd.notna(dm["dm_pvalor"])
                    and not (
                        dm["diferencia_media_perdida"] > 0
                        and dm["dm_pvalor"] < 0.05
                    )
                ),
            }
        )

        coeficientes_todos.extend(
            [
                coeficientes(
                    modelo_evidencia,
                    canasta_evidencia,
                    afp,
                    "CANASTA_EVIDENCIA",
                ),
                coeficientes(
                    modelo_podada,
                    podada,
                    afp,
                    "CANASTA_PODADA",
                ),
            ]
        )

        for orden, spec in enumerate(canasta_evidencia, start=1):
            canasta_evidencia_todos.append(
                {
                    "afp": afp,
                    "orden": orden,
                    "factor": spec["factor"],
                    "lag": int(spec["lag"]),
                }
            )

        for orden, spec in enumerate(podada, start=1):
            meta = metadatos.get(spec["factor"], {})
            canasta_podada_todos.append(
                {
                    "afp": afp,
                    "orden": orden,
                    "factor": spec["factor"],
                    "lag": int(spec["lag"]),
                    "ticker": meta.get("ticker", ""),
                    "nombre": meta.get("nombre", ""),
                    "categoria": meta.get("categoria", ""),
                    "moneda_modelo": meta.get("moneda_modelo", ""),
                    "fuente_catalogo": meta.get("fuente_catalogo", ""),
                }
            )

        historial_filas.append(
            {
                "afp": afp,
                "modulos_aceptados": " > ".join(historial),
                "n_factores_evidencia": len(canasta_evidencia),
                "n_factores_podada": len(podada),
            }
        )

        plt.figure(figsize=(12, 5))
        plt.plot(
            sim_podada["fecha_hoy_simulada"],
            sim_podada["cuota_real_hoy"],
            label="Cuota SBS",
        )
        plt.plot(
            sim_evidencia["fecha_hoy_simulada"],
            sim_evidencia["cuota_estimada_hoy"],
            label="Canasta con evidencia",
        )
        plt.plot(
            sim_podada["fecha_hoy_simulada"],
            sim_podada["cuota_estimada_hoy"],
            label="Canasta podada",
        )
        plt.ylabel("Valor cuota")
        plt.title(f"Consolidación y poda final — {afp}")
        plt.legend()
        plt.tight_layout()
        plt.savefig(
            graficos / f"01_poda_{afp.lower()}.png",
            dpi=160,
            bbox_inches="tight",
        )
        plt.close()

    evidencia_df = pd.DataFrame(canasta_evidencia_todos)
    podada_df = pd.DataFrame(canasta_podada_todos)
    trazas_df = pd.concat(trazas_todas, ignore_index=True)
    validacion_df = pd.DataFrame(validacion_todas)
    prueba_df = pd.DataFrame(prueba_todas)
    simulaciones_df = pd.concat(simulaciones, ignore_index=True)
    dm_df = pd.DataFrame(dm_filas)
    coeficientes_df = pd.concat(
        coeficientes_todos,
        ignore_index=True,
    )
    historial_df = pd.DataFrame(historial_filas)

    rutas = {
        "canasta_evidencia": (
            processed
            / "ca0001_modelo78_canasta_con_evidencia.csv"
        ),
        "canasta_podada": (
            processed
            / "ca0001_modelo78_canasta_final_podada.csv"
        ),
        "trazabilidad": (
            processed
            / "ca0001_modelo78_trazabilidad_poda.csv"
        ),
        "validacion": (
            processed
            / "ca0001_modelo78_metricas_validacion.csv"
        ),
        "prueba": (
            processed
            / "ca0001_modelo78_metricas_prueba.csv"
        ),
        "simulacion": (
            processed
            / "ca0001_modelo78_simulacion_publicacion_5d.csv"
        ),
        "dm": (
            processed
            / "ca0001_modelo78_diebold_mariano_poda.csv"
        ),
        "coeficientes": (
            processed
            / "ca0001_modelo78_coeficientes.csv"
        ),
        "historial": (
            processed
            / "ca0001_modelo78_historial_modelos_aceptados.csv"
        ),
        "resumen": (
            processed
            / "ca0001_modelo78_resumen.json"
        ),
    }

    evidencia_df.to_csv(
        rutas["canasta_evidencia"],
        index=False,
        encoding="utf-8-sig",
    )
    podada_df.to_csv(
        rutas["canasta_podada"],
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
        rutas["simulacion"],
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
    historial_df.to_csv(
        rutas["historial"],
        index=False,
        encoding="utf-8-sig",
    )

    resumen = {
        "version": "modelo78_consolidacion_y_poda_final",
        "criterio": (
            "Solo se heredan cambios de módulos con mejora favorable "
            "en Diebold-Mariano. Después se realiza poda backward usando "
            "exclusivamente validación. La prueba se usa solo como auditoría."
        ),
        "advertencia": (
            "El periodo de prueba ya fue consultado en varios módulos. "
            "La confirmación definitiva debe hacerse con cuotas SBS futuras."
        ),
        "canasta_final_podada": podada_df.to_dict(orient="records"),
        "metricas_prueba": prueba_df.to_dict(orient="records"),
        "diebold_mariano_poda": dm_df.to_dict(orient="records"),
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

    print("\nMÓDULO 78 — CONSOLIDACIÓN Y PODA FINAL")
    print("=" * 170)

    print("\nHISTORIAL DE MÓDULOS ACEPTADOS")
    print("-" * 170)
    print(historial_df.to_string(index=False))

    print("\nCANASTA FINAL PODADA")
    print("-" * 170)
    print(podada_df.to_string(index=False))

    print("\nTRAZABILIDAD DE LA PODA")
    print("-" * 170)
    print(trazas_df.to_string(index=False))

    print("\nMÉTRICAS DE VALIDACIÓN")
    print("-" * 170)
    print(
        validacion_df[
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
    print("-" * 170)
    print(
        prueba_df[
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

    print("\nDIEBOLD-MARIANO: PODADA VS CANASTA CON EVIDENCIA")
    print("-" * 170)
    print(dm_df.to_string(index=False))

    print("\nARCHIVOS CREADOS")
    print("-" * 170)
    for ruta in rutas.values():
        print(f" - {ruta.resolve()}")
    print(f" - {graficos.resolve()}")

    print(
        "\nLECTURA:\n"
        "- M77 no se incorpora si futuros/cripto no superaron al campeón.\n"
        "- La poda elimina factores que ya no aportan información suficiente.\n"
        "- La canasta podada es la candidata para congelar y monitorear.\n"
        "- Después de este módulo no conviene seguir buscando variables "
        "sobre el mismo test: corresponde validación prospectiva con cuotas futuras."
    )


if __name__ == "__main__":
    main()
