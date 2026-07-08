from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.metrics import (
    mean_absolute_error,
    mean_squared_error,
    r2_score,
)
from sklearn.model_selection import GridSearchCV, TimeSeriesSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


FECHA_CORTE_TEST = pd.Timestamp("2025-01-01")
ALPHAS = [0.01, 0.1, 1.0, 10.0, 100.0, 1000.0]
N_SPLITS = 5
BOOTSTRAP_REPETICIONES = 2000
BOOTSTRAP_BLOQUE = 20
SEMILLA = 12345

ESQUEMAS_REZAGO = {
    "lag0": [0],
    "lag1": [1],
    "lag2": [2],
    "lag0_1": [0, 1],
    "lag0_1_2": [0, 1, 2],
}

FACTORES_MERCADO = [
    "ACWI",
    "XLK",
    "EEM",
    "EPU",
    "COPX",
    "TLT",
    "LQD",
    "HYG",
    "^VIX",
    "PEN=X",
]

CATEGORIAS_PESOS = {
    "peso_rv_exterior": [
        "fondos_mutuos_exterior",
        "acciones_exterior_directas",
        "etf_exterior_via_mercado_local",
        "fondos_inversion_exterior",
    ],
    "peso_rv_local": [
        "acciones_locales_no_financieras",
        "acciones_locales_financieras",
    ],
    "peso_rf_exterior": [
        "renta_fija_soberana_exterior",
        "renta_fija_financiera_exterior",
        "renta_fija_no_financiera_exterior",
        "renta_fija_organismos_internacionales",
        "renta_fija_exterior_otros",
    ],
    "peso_rf_local": [
        "renta_fija_soberana_local",
        "renta_fija_financiera_local",
        "renta_fija_no_financiera_local",
        "renta_fija_local_otros",
        "titulizaciones_deuda_local",
    ],
    "peso_alternativos": [
        "alternativos_exterior",
        "alternativos_local",
        "titulizaciones_participacion_local",
        "fondos_inversion_local_tradicional",
        "fondos_mutuos_locales",
        "otros_instrumentos_autorizados",
    ],
    "peso_liquidez_transito": [
        "depositos_locales",
        "depositos_exterior",
        "operaciones_en_transito",
    ],
}


def leer_afp(ruta: Path) -> pd.DataFrame:
    if not ruta.exists():
        raise FileNotFoundError(f"No existe: {ruta}")

    df = pd.read_csv(ruta, parse_dates=["fecha"])
    df["rendimiento_simple"] = pd.to_numeric(
        df["rendimiento_simple"],
        errors="coerce",
    )

    return (
        df.sort_values(["afp", "fecha"])
        .dropna(subset=["rendimiento_simple"])
        .reset_index(drop=True)
    )


def leer_mercados(ruta: Path) -> pd.DataFrame:
    if not ruta.exists():
        raise FileNotFoundError(f"No existe: {ruta}")

    df = pd.read_csv(ruta, parse_dates=["fecha"])
    df = df.sort_values("fecha").drop_duplicates("fecha").copy()

    faltantes = [
        factor for factor in FACTORES_MERCADO
        if factor not in df.columns
    ]
    if faltantes:
        raise ValueError(
            f"Faltan factores de mercado: {faltantes}"
        )

    for factor in FACTORES_MERCADO:
        df[factor] = pd.to_numeric(
            df[factor],
            errors="coerce",
        )

    return df[["fecha", *FACTORES_MERCADO]]


def leer_pesos_mensuales(ruta: Path) -> pd.DataFrame:
    if not ruta.exists():
        raise FileNotFoundError(f"No existe: {ruta}")

    df = pd.read_csv(
        ruta,
        parse_dates=["fecha_cartera"],
    )

    requeridas = {
        "fecha_cartera",
        "afp",
        "categoria_economica",
        "participacion_pct",
    }
    faltantes = requeridas - set(df.columns)
    if faltantes:
        raise ValueError(
            f"Faltan columnas de pesos: {sorted(faltantes)}"
        )

    df["participacion_pct"] = pd.to_numeric(
        df["participacion_pct"],
        errors="coerce",
    ).fillna(0.0)

    pivote = (
        df.pivot_table(
            index=["fecha_cartera", "afp"],
            columns="categoria_economica",
            values="participacion_pct",
            aggfunc="sum",
            fill_value=0.0,
        )
        .reset_index()
    )
    pivote.columns.name = None

    for nombre_peso, categorias in CATEGORIAS_PESOS.items():
        columnas_presentes = [
            categoria for categoria in categorias
            if categoria in pivote.columns
        ]

        if columnas_presentes:
            pivote[nombre_peso] = (
                pivote[columnas_presentes].sum(axis=1) / 100.0
            )
        else:
            pivote[nombre_peso] = 0.0

    pivote["peso_rv_total"] = (
        pivote["peso_rv_exterior"]
        + pivote["peso_rv_local"]
    )
    pivote["peso_exterior_total"] = (
        pivote["peso_rv_exterior"]
        + pivote["peso_rf_exterior"]
    )
    pivote["peso_mapeado_total"] = (
        pivote[
            list(CATEGORIAS_PESOS.keys())
        ].sum(axis=1)
    )

    # La fotografía de fin de mes se aplica desde el día siguiente.
    pivote["fecha_efectiva"] = (
        pivote["fecha_cartera"] + pd.Timedelta(days=1)
    )

    columnas_salida = [
        "fecha_cartera",
        "fecha_efectiva",
        "afp",
        *CATEGORIAS_PESOS.keys(),
        "peso_rv_total",
        "peso_exterior_total",
        "peso_mapeado_total",
    ]

    return pivote[columnas_salida].sort_values(
        ["afp", "fecha_efectiva"]
    )


def leer_mejores_rezagos(
    ruta: Path,
    afps: list[str],
) -> dict[str, str]:
    resultado = {afp: "lag0" for afp in afps}

    if not ruta.exists():
        return resultado

    tabla = pd.read_csv(ruta)

    if not {"afp", "mejor_esquema"}.issubset(tabla.columns):
        return resultado

    for fila in tabla.itertuples(index=False):
        if (
            fila.afp in resultado
            and fila.mejor_esquema in ESQUEMAS_REZAGO
        ):
            resultado[fila.afp] = fila.mejor_esquema

    return resultado


def asignar_pesos_diarios(
    afp: pd.DataFrame,
    pesos: pd.DataFrame,
) -> pd.DataFrame:
    salidas = []

    for nombre_afp, grupo_afp in afp.groupby("afp"):
        grupo_afp = grupo_afp.sort_values("fecha").copy()
        grupo_pesos = pesos[
            pesos["afp"] == nombre_afp
        ].sort_values("fecha_efectiva").copy()

        if grupo_pesos.empty:
            raise ValueError(
                f"No existen pesos mensuales para {nombre_afp}."
            )

        combinado = pd.merge_asof(
            grupo_afp,
            grupo_pesos.drop(columns=["afp"]),
            left_on="fecha",
            right_on="fecha_efectiva",
            direction="backward",
            allow_exact_matches=True,
        )
        combinado["afp"] = nombre_afp
        salidas.append(combinado)

    return pd.concat(
        salidas,
        ignore_index=True,
    ).sort_values(["afp", "fecha"])


def construir_factores_base(
    datos: pd.DataFrame,
) -> pd.DataFrame:
    salida = pd.DataFrame(
        {
            "fecha": datos["fecha"],
            "afp": datos["afp"],
            "rendimiento_simple": datos["rendimiento_simple"],
        }
    )

    salida["global"] = datos["ACWI"]
    salida["tecnologia"] = datos["XLK"]
    salida["emergentes"] = datos["EEM"]
    salida["peru"] = datos["EPU"]
    salida["cobre"] = datos["COPX"]
    salida["tesoro_usa"] = datos["TLT"]
    salida["credito_ig"] = datos["LQD"]
    salida["credito_hy"] = datos["HYG"]
    salida["vix"] = datos["^VIX"]
    salida["fx_usdpen"] = datos["PEN=X"]

    return salida


def construir_factores_ponderados(
    datos: pd.DataFrame,
) -> pd.DataFrame:
    salida = pd.DataFrame(
        {
            "fecha": datos["fecha"],
            "afp": datos["afp"],
            "rendimiento_simple": datos["rendimiento_simple"],
        }
    )

    salida["global_x_rv_ext"] = (
        datos["ACWI"] * datos["peso_rv_exterior"]
    )
    salida["tecnologia_x_rv_ext"] = (
        datos["XLK"] * datos["peso_rv_exterior"]
    )
    salida["emergentes_x_rv_ext"] = (
        datos["EEM"] * datos["peso_rv_exterior"]
    )
    salida["peru_x_rv_local"] = (
        datos["EPU"] * datos["peso_rv_local"]
    )
    salida["cobre_x_rv_total"] = (
        datos["COPX"] * datos["peso_rv_total"]
    )
    salida["tesoro_x_rf_ext"] = (
        datos["TLT"] * datos["peso_rf_exterior"]
    )
    salida["credito_ig_x_rf_ext"] = (
        datos["LQD"] * datos["peso_rf_exterior"]
    )
    salida["credito_hy_x_rf_ext"] = (
        datos["HYG"] * datos["peso_rf_exterior"]
    )
    salida["vix_x_rv_total"] = (
        datos["^VIX"] * datos["peso_rv_total"]
    )
    salida["fx_x_exterior"] = (
        datos["PEN=X"] * datos["peso_exterior_total"]
    )

    return salida


def combinar_hibrido(
    base: pd.DataFrame,
    ponderado: pd.DataFrame,
) -> pd.DataFrame:
    identificadores = [
        "fecha",
        "afp",
        "rendimiento_simple",
    ]

    return base.merge(
        ponderado.drop(columns=["rendimiento_simple"]),
        on=["fecha", "afp"],
        how="inner",
        validate="one_to_one",
        suffixes=("", "_ponderado"),
    )[[
        *identificadores,
        *[
            columna for columna in base.columns
            if columna not in identificadores
        ],
        *[
            columna for columna in ponderado.columns
            if columna not in identificadores
        ],
    ]]


def agregar_rezagos(
    df: pd.DataFrame,
    rezagos: list[int],
) -> pd.DataFrame:
    identificadores = {
        "fecha",
        "afp",
        "rendimiento_simple",
    }
    factores = [
        columna for columna in df.columns
        if columna not in identificadores
    ]

    salida = df[
        ["fecha", "afp", "rendimiento_simple"]
    ].copy()

    for factor in factores:
        for rezago in rezagos:
            salida[f"{factor}_lag{rezago}"] = (
                df.groupby("afp")[factor].shift(rezago)
            )

    return salida


def crear_modelo(alpha: float | None = None) -> Pipeline:
    pipeline = Pipeline(
        steps=[
            ("imputar", SimpleImputer(strategy="median")),
            ("escalar", StandardScaler()),
            ("ridge", Ridge()),
        ]
    )

    if alpha is not None:
        pipeline.set_params(ridge__alpha=alpha)

    return pipeline


def elegir_alpha(
    X: pd.DataFrame,
    y: pd.Series,
) -> float:
    busqueda = GridSearchCV(
        estimator=crear_modelo(),
        param_grid={"ridge__alpha": ALPHAS},
        scoring="neg_root_mean_squared_error",
        cv=TimeSeriesSplit(n_splits=N_SPLITS),
        n_jobs=-1,
        refit=True,
    )
    busqueda.fit(X, y)

    return float(
        busqueda.best_params_["ridge__alpha"]
    )


def calcular_metricas(
    real: np.ndarray,
    estimado: np.ndarray,
) -> dict:
    real = np.asarray(real, dtype=float)
    estimado = np.asarray(estimado, dtype=float)

    rmse = float(
        np.sqrt(mean_squared_error(real, estimado))
    )
    mae = float(mean_absolute_error(real, estimado))
    r2 = float(r2_score(real, estimado))

    correlacion = (
        float(np.corrcoef(real, estimado)[0, 1])
        if np.std(real) > 0 and np.std(estimado) > 0
        else np.nan
    )
    direccion = float(
        (np.sign(real) == np.sign(estimado)).mean() * 100
    )

    return {
        "observaciones": len(real),
        "rmse": rmse,
        "mae": mae,
        "r2": r2,
        "correlacion": correlacion,
        "acierto_direccion_pct": direccion,
    }


def ajustar_evaluar(
    tabla: pd.DataFrame,
    nombre_afp: str,
    nombre_modelo: str,
    esquema: str,
) -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    columnas = [
        columna for columna in tabla.columns
        if columna not in {
            "fecha",
            "afp",
            "rendimiento_simple",
        }
    ]

    tabla = tabla.dropna(
        subset=["rendimiento_simple"]
    ).copy()

    train = tabla[
        tabla["fecha"] < FECHA_CORTE_TEST
    ].copy()
    test = tabla[
        tabla["fecha"] >= FECHA_CORTE_TEST
    ].copy()

    if len(train) < 500 or len(test) < 50:
        raise ValueError(
            f"Datos insuficientes para {nombre_afp} - {nombre_modelo}: "
            f"train={len(train)}, test={len(test)}"
        )

    X_train = train[columnas]
    y_train = train["rendimiento_simple"]
    X_test = test[columnas]
    y_test = test["rendimiento_simple"]

    alpha = elegir_alpha(X_train, y_train)
    modelo = crear_modelo(alpha)
    modelo.fit(X_train, y_train)

    pred = modelo.predict(X_test)
    metricas = calcular_metricas(
        y_test.to_numpy(),
        pred,
    )

    resultado = {
        "afp": nombre_afp,
        "modelo": nombre_modelo,
        "esquema_rezago": esquema,
        "alpha_ridge": alpha,
        "fecha_test_inicio": test["fecha"].min(),
        "fecha_test_fin": test["fecha"].max(),
        "numero_variables": len(columnas),
        **metricas,
    }

    predicciones = test[
        ["fecha", "afp", "rendimiento_simple"]
    ].copy()
    predicciones["modelo"] = nombre_modelo
    predicciones["esquema_rezago"] = esquema
    predicciones["estimado"] = pred
    predicciones["error"] = (
        predicciones["rendimiento_simple"]
        - predicciones["estimado"]
    )
    predicciones["error_cuadrado"] = (
        predicciones["error"] ** 2
    )
    predicciones["error_absoluto"] = (
        predicciones["error"].abs()
    )

    scaler = modelo.named_steps["escalar"]
    ridge = modelo.named_steps["ridge"]

    coeficientes = pd.DataFrame(
        {
            "afp": nombre_afp,
            "modelo": nombre_modelo,
            "esquema_rezago": esquema,
            "variable": columnas,
            "coef_estandarizado": ridge.coef_,
            "coef_original": ridge.coef_ / scaler.scale_,
        }
    )
    coeficientes["coef_abs_estandarizado"] = (
        coeficientes["coef_estandarizado"].abs()
    )
    coeficientes = coeficientes.sort_values(
        "coef_abs_estandarizado",
        ascending=False,
    )

    return resultado, predicciones, coeficientes


def bootstrap_bloques(
    mejora_diaria: np.ndarray,
    repeticiones: int = BOOTSTRAP_REPETICIONES,
    bloque: int = BOOTSTRAP_BLOQUE,
) -> tuple[float, float, float, str]:
    """
    mejora_diaria = pérdida baseline - pérdida modelo.
    Positivo significa que el modelo alternativo mejora.
    """
    valores = np.asarray(mejora_diaria, dtype=float)
    valores = valores[np.isfinite(valores)]

    n = len(valores)
    if n < bloque * 2:
        return np.nan, np.nan, np.nan, "muestra_insuficiente"

    rng = np.random.default_rng(SEMILLA)
    inicios_posibles = np.arange(0, n - bloque + 1)
    medias = np.empty(repeticiones)

    bloques_necesarios = int(np.ceil(n / bloque))

    for i in range(repeticiones):
        indices = []

        for _ in range(bloques_necesarios):
            inicio = int(rng.choice(inicios_posibles))
            indices.extend(
                range(inicio, inicio + bloque)
            )

        muestra = valores[np.array(indices[:n])]
        medias[i] = float(np.mean(muestra))

    media = float(np.mean(valores))
    inferior, superior = np.quantile(
        medias,
        [0.025, 0.975],
    )

    if inferior > 0:
        evidencia = "mejora_robusta"
    elif superior < 0:
        evidencia = "empeora_robustamente"
    else:
        evidencia = "no_concluyente"

    return (
        media,
        float(inferior),
        float(superior),
        evidencia,
    )


def comparar_con_baseline(
    predicciones: pd.DataFrame,
) -> pd.DataFrame:
    baseline = predicciones[
        predicciones["modelo"] == "M0_sin_pesos"
    ][
        [
            "fecha",
            "afp",
            "error_cuadrado",
        ]
    ].rename(
        columns={
            "error_cuadrado": "error_cuadrado_baseline"
        }
    )

    filas = []

    for (afp, modelo), grupo in predicciones[
        predicciones["modelo"] != "M0_sin_pesos"
    ].groupby(["afp", "modelo"]):
        unido = grupo.merge(
            baseline[baseline["afp"] == afp],
            on=["fecha", "afp"],
            how="inner",
            validate="one_to_one",
        )

        mejora = (
            unido["error_cuadrado_baseline"]
            - unido["error_cuadrado"]
        ).to_numpy()

        media, inferior, superior, evidencia = (
            bootstrap_bloques(mejora)
        )

        mse_baseline = float(
            unido["error_cuadrado_baseline"].mean()
        )
        mse_modelo = float(
            unido["error_cuadrado"].mean()
        )

        mejora_pct = (
            (mse_baseline - mse_modelo)
            / mse_baseline
            * 100
            if mse_baseline > 0
            else np.nan
        )

        filas.append(
            {
                "afp": afp,
                "modelo": modelo,
                "observaciones_comparadas": len(unido),
                "mse_baseline": mse_baseline,
                "mse_modelo": mse_modelo,
                "mejora_mse_pct": mejora_pct,
                "diferencia_media_perdida": media,
                "ic95_inferior": inferior,
                "ic95_superior": superior,
                "evidencia_bootstrap": evidencia,
                "bloque_sesiones": BOOTSTRAP_BLOQUE,
                "repeticiones": BOOTSTRAP_REPETICIONES,
            }
        )

    return pd.DataFrame(filas)


def metricas_por_anio(
    predicciones: pd.DataFrame,
) -> pd.DataFrame:
    tabla = predicciones.copy()
    tabla["anio"] = tabla["fecha"].dt.year

    filas = []

    for (
        afp,
        modelo,
        anio,
    ), grupo in tabla.groupby(
        ["afp", "modelo", "anio"]
    ):
        met = calcular_metricas(
            grupo["rendimiento_simple"].to_numpy(),
            grupo["estimado"].to_numpy(),
        )
        filas.append(
            {
                "afp": afp,
                "modelo": modelo,
                "anio": anio,
                **met,
            }
        )

    return pd.DataFrame(filas)


def main() -> None:
    raiz = Path(__file__).resolve().parents[1]
    processed = raiz / "data" / "processed"

    ruta_afp = (
        processed / "sbs_fondo3_base_maestra.csv"
    )
    ruta_mercados = (
        processed / "mercados_retornos_locales.csv"
    )
    ruta_pesos = (
        processed / "fp1356_cartera_economica_mensual_v2.csv"
    )
    ruta_rezagos = (
        processed / "fondo3_mejor_rezago_por_afp.csv"
    )

    afp = leer_afp(ruta_afp)
    mercados = leer_mercados(ruta_mercados)
    pesos = leer_pesos_mensuales(ruta_pesos)

    afps = sorted(afp["afp"].unique())
    mejores_rezagos = leer_mejores_rezagos(
        ruta_rezagos,
        afps,
    )

    afp_pesos = asignar_pesos_diarios(
        afp,
        pesos,
    )

    datos = afp_pesos.merge(
        mercados,
        on="fecha",
        how="inner",
        validate="many_to_one",
    )

    # Se eliminan únicamente fechas anteriores a la primera cartera
    # disponible para cada AFP.
    datos = datos.dropna(
        subset=["fecha_cartera"]
    ).copy()

    base = construir_factores_base(datos)
    ponderado = construir_factores_ponderados(datos)
    hibrido = combinar_hibrido(base, ponderado)

    modelos_fuente = {
        "M0_sin_pesos": base,
        "M1_pesos_reales": ponderado,
        "M2_hibrido": hibrido,
    }

    metricas_total = []
    predicciones_total = []
    coeficientes_total = []

    for nombre_afp in afps:
        esquema = mejores_rezagos.get(
            nombre_afp,
            "lag0",
        )
        rezagos = ESQUEMAS_REZAGO[esquema]

        print("\n" + "=" * 112)
        print(
            f"AFP: {nombre_afp} | "
            f"Esquema de rezago: {esquema}"
        )
        print("-" * 112)

        for nombre_modelo, fuente in modelos_fuente.items():
            tabla_afp = fuente[
                fuente["afp"] == nombre_afp
            ].sort_values("fecha").copy()

            tabla_rezagada = agregar_rezagos(
                tabla_afp,
                rezagos,
            )

            resultado, pred, coef = ajustar_evaluar(
                tabla_rezagada,
                nombre_afp,
                nombre_modelo,
                esquema,
            )

            metricas_total.append(resultado)
            predicciones_total.append(pred)
            coeficientes_total.append(coef)

            print(
                f"{nombre_modelo}: "
                f"RMSE={resultado['rmse']:.6f} | "
                f"R²={resultado['r2']:.4f} | "
                f"Corr={resultado['correlacion']:.4f} | "
                f"Dirección={resultado['acierto_direccion_pct']:.2f}%"
            )

    metricas_df = pd.DataFrame(metricas_total)
    predicciones_df = pd.concat(
        predicciones_total,
        ignore_index=True,
    )
    coeficientes_df = pd.concat(
        coeficientes_total,
        ignore_index=True,
    )

    metricas_df["ranking_rmse"] = (
        metricas_df.groupby("afp")["rmse"]
        .rank(method="first", ascending=True)
        .astype(int)
    )

    comparacion_df = comparar_con_baseline(
        predicciones_df,
    )
    anual_df = metricas_por_anio(
        predicciones_df,
    )

    cobertura_pesos = (
        datos.groupby("afp", as_index=False)
        .agg(
            fecha_inicio_pesos=("fecha", "min"),
            fecha_fin_pesos=("fecha", "max"),
            observaciones=("fecha", "size"),
            peso_mapeado_mediano=(
                "peso_mapeado_total",
                "median",
            ),
            peso_mapeado_minimo=(
                "peso_mapeado_total",
                "min",
            ),
            peso_mapeado_maximo=(
                "peso_mapeado_total",
                "max",
            ),
        )
    )

    rutas = {
        "metricas": (
            processed / "fondo3_modelos_pesos_reales_metricas.csv"
        ),
        "bootstrap": (
            processed / "fondo3_modelos_pesos_reales_bootstrap.csv"
        ),
        "anual": (
            processed / "fondo3_modelos_pesos_reales_anual.csv"
        ),
        "predicciones": (
            processed / "fondo3_modelos_pesos_reales_predicciones.csv"
        ),
        "coeficientes": (
            processed / "fondo3_modelos_pesos_reales_coeficientes.csv"
        ),
        "pesos_diarios": (
            processed / "fondo3_pesos_diarios_aplicados.csv"
        ),
        "cobertura": (
            processed / "fondo3_pesos_cobertura.csv"
        ),
    }

    metricas_df.to_csv(
        rutas["metricas"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    comparacion_df.to_csv(
        rutas["bootstrap"],
        index=False,
        encoding="utf-8-sig",
    )
    anual_df.to_csv(
        rutas["anual"],
        index=False,
        encoding="utf-8-sig",
    )
    predicciones_df.to_csv(
        rutas["predicciones"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    coeficientes_df.to_csv(
        rutas["coeficientes"],
        index=False,
        encoding="utf-8-sig",
    )

    columnas_pesos = [
        "fecha",
        "afp",
        "fecha_cartera",
        *CATEGORIAS_PESOS.keys(),
        "peso_rv_total",
        "peso_exterior_total",
        "peso_mapeado_total",
    ]
    datos[columnas_pesos].to_csv(
        rutas["pesos_diarios"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    cobertura_pesos.to_csv(
        rutas["cobertura"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )

    print("\n" + "=" * 112)
    print("COMPARACIÓN FINAL FUERA DE MUESTRA")
    print("=" * 112)
    print(
        metricas_df.sort_values(
            ["afp", "ranking_rmse"]
        )[
            [
                "afp",
                "modelo",
                "esquema_rezago",
                "rmse",
                "mae",
                "r2",
                "correlacion",
                "acierto_direccion_pct",
                "ranking_rmse",
            ]
        ].to_string(index=False)
    )

    print("\n" + "=" * 112)
    print("PRUEBA BOOTSTRAP FRENTE AL MODELO SIN PESOS")
    print("=" * 112)
    print(
        comparacion_df[
            [
                "afp",
                "modelo",
                "mejora_mse_pct",
                "ic95_inferior",
                "ic95_superior",
                "evidencia_bootstrap",
            ]
        ].to_string(index=False)
    )

    print("\nArchivos creados:")
    for ruta in rutas.values():
        print(f" - {ruta.resolve()}")

    print(
        "\nCriterio de decisión:\n"
        "- Los pesos aportan evidencia real solo si M1 o M2 reducen el "
        "RMSE frente a M0 y el bootstrap resulta mejora_robusta.\n"
        "- Una mejora pequeña o no concluyente no valida definitivamente "
        "la composición como explicación diaria.\n"
        "- M1 prueba la cartera ponderada; M2 permite además que queden "
        "efectos generales no captados por la clasificación.\n"
        "- Las fotografías de cartera se aplican desde el día siguiente "
        "al cierre mensual. Esto evita usar una composición futura, pero "
        "no reproduce el retraso real de publicación de la SBS.\n"
        "- Aunque M1 o M2 mejoren, FP-1356 no revela los activos internos "
        "de los fondos mutuos extranjeros. La validación sectorial final "
        "requerirá CA-0001."
    )


if __name__ == "__main__":
    main()
