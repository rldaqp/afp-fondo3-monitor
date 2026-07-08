from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import GridSearchCV, TimeSeriesSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


FECHA_CORTE_TEST = pd.Timestamp("2025-01-01")
ALPHAS = [0.01, 0.1, 1.0, 10.0, 100.0, 1000.0]
N_SPLITS = 5
BOOTSTRAP_REPETICIONES = 2000
BOOTSTRAP_BLOQUE = 20
SEMILLA = 20260704

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

COLUMNAS_PESO = [
    *CATEGORIAS_PESOS.keys(),
    "peso_rv_total",
    "peso_exterior_total",
    "peso_mapeado_total",
]


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
        raise ValueError(f"Faltan factores de mercado: {faltantes}")

    for factor in FACTORES_MERCADO:
        df[factor] = pd.to_numeric(df[factor], errors="coerce")

    return df[["fecha", *FACTORES_MERCADO]]


def leer_pesos_mensuales(ruta: Path) -> pd.DataFrame:
    if not ruta.exists():
        raise FileNotFoundError(f"No existe: {ruta}")

    df = pd.read_csv(ruta, parse_dates=["fecha_cartera"])

    requeridas = {
        "fecha_cartera",
        "afp",
        "categoria_economica",
        "participacion_pct",
    }
    faltantes = requeridas - set(df.columns)
    if faltantes:
        raise ValueError(f"Faltan columnas de pesos: {sorted(faltantes)}")

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
        presentes = [c for c in categorias if c in pivote.columns]
        pivote[nombre_peso] = (
            pivote[presentes].sum(axis=1) / 100.0
            if presentes
            else 0.0
        )

    pivote["peso_rv_total"] = (
        pivote["peso_rv_exterior"] + pivote["peso_rv_local"]
    )
    pivote["peso_exterior_total"] = (
        pivote["peso_rv_exterior"] + pivote["peso_rf_exterior"]
    )
    pivote["peso_mapeado_total"] = pivote[
        list(CATEGORIAS_PESOS.keys())
    ].sum(axis=1)

    return pivote[
        ["fecha_cartera", "afp", *COLUMNAS_PESO]
    ].sort_values(["afp", "fecha_cartera"])


def leer_rezagos(ruta: Path, afps: list[str]) -> dict[str, str]:
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


def escenario_dinamico(
    pesos: pd.DataFrame,
    nombre: str,
    dias_publicacion: int,
    meses_adicionales: int = 0,
    rotar_afp: bool = False,
) -> pd.DataFrame:
    salida = pesos.copy()

    if rotar_afp:
        orden = ["Habitat", "Integra", "Prima", "Profuturo"]
        mapa_fuente_a_destino = {
            "Habitat": "Integra",
            "Integra": "Prima",
            "Prima": "Profuturo",
            "Profuturo": "Habitat",
        }
        salida["afp_fuente"] = salida["afp"]
        salida["afp"] = salida["afp"].map(mapa_fuente_a_destino)

        if salida["afp"].isna().any():
            faltantes = sorted(
                salida.loc[salida["afp"].isna(), "afp_fuente"].unique()
            )
            raise ValueError(
                f"No se pudo rotar estas AFP: {faltantes}"
            )

    salida["fecha_efectiva"] = (
        salida["fecha_cartera"]
        + pd.DateOffset(months=meses_adicionales)
        + pd.to_timedelta(dias_publicacion, unit="D")
    )
    salida["escenario"] = nombre

    return salida[
        [
            "fecha_cartera",
            "fecha_efectiva",
            "afp",
            *COLUMNAS_PESO,
            "escenario",
        ]
    ].sort_values(["afp", "fecha_efectiva"])


def escenario_constante_train(
    pesos: pd.DataFrame,
    afp: pd.DataFrame,
) -> pd.DataFrame:
    promedio = (
        pesos[pesos["fecha_cartera"] < FECHA_CORTE_TEST]
        .groupby("afp", as_index=False)[COLUMNAS_PESO]
        .mean()
    )

    fechas = afp[["fecha", "afp"]].drop_duplicates().copy()
    salida = fechas.merge(
        promedio,
        on="afp",
        how="left",
        validate="many_to_one",
    )
    salida["fecha_cartera"] = pd.NaT
    salida["fecha_efectiva"] = salida["fecha"]
    salida["escenario"] = "pesos_constantes_train"

    return salida[
        [
            "fecha_cartera",
            "fecha_efectiva",
            "afp",
            *COLUMNAS_PESO,
            "escenario",
        ]
    ].sort_values(["afp", "fecha_efectiva"])


def asignar_pesos_asof(
    afp: pd.DataFrame,
    pesos_escenario: pd.DataFrame,
) -> pd.DataFrame:
    salidas = []

    for nombre_afp, grupo_afp in afp.groupby("afp"):
        grupo_afp = grupo_afp.sort_values("fecha").copy()
        grupo_pesos = pesos_escenario[
            pesos_escenario["afp"] == nombre_afp
        ].sort_values("fecha_efectiva").copy()

        if grupo_pesos.empty:
            raise ValueError(
                f"No existen pesos para {nombre_afp} en "
                f"{pesos_escenario['escenario'].iloc[0]}"
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

    return pd.concat(salidas, ignore_index=True).sort_values(
        ["afp", "fecha"]
    )


def asignar_pesos_constantes(
    afp: pd.DataFrame,
    pesos_constantes: pd.DataFrame,
) -> pd.DataFrame:
    columnas = ["afp", *COLUMNAS_PESO]
    promedio = (
        pesos_constantes[columnas]
        .drop_duplicates(subset=["afp"])
    )

    salida = afp.merge(
        promedio,
        on="afp",
        how="left",
        validate="many_to_one",
    )
    salida["fecha_cartera"] = pd.NaT
    salida["fecha_efectiva"] = salida["fecha"]
    salida["escenario"] = "pesos_constantes_train"
    return salida


def construir_base_sin_pesos(datos: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "fecha": datos["fecha"],
            "afp": datos["afp"],
            "rendimiento_simple": datos["rendimiento_simple"],
            "global": datos["ACWI"],
            "tecnologia": datos["XLK"],
            "emergentes": datos["EEM"],
            "peru": datos["EPU"],
            "cobre": datos["COPX"],
            "tesoro_usa": datos["TLT"],
            "credito_ig": datos["LQD"],
            "credito_hy": datos["HYG"],
            "vix": datos["^VIX"],
            "fx_usdpen": datos["PEN=X"],
        }
    )


def construir_factores_ponderados(datos: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "fecha": datos["fecha"],
            "afp": datos["afp"],
            "rendimiento_simple": datos["rendimiento_simple"],
            "global_x_rv_ext": (
                datos["ACWI"] * datos["peso_rv_exterior"]
            ),
            "tecnologia_x_rv_ext": (
                datos["XLK"] * datos["peso_rv_exterior"]
            ),
            "emergentes_x_rv_ext": (
                datos["EEM"] * datos["peso_rv_exterior"]
            ),
            "peru_x_rv_local": (
                datos["EPU"] * datos["peso_rv_local"]
            ),
            "cobre_x_rv_total": (
                datos["COPX"] * datos["peso_rv_total"]
            ),
            "tesoro_x_rf_ext": (
                datos["TLT"] * datos["peso_rf_exterior"]
            ),
            "credito_ig_x_rf_ext": (
                datos["LQD"] * datos["peso_rf_exterior"]
            ),
            "credito_hy_x_rf_ext": (
                datos["HYG"] * datos["peso_rf_exterior"]
            ),
            "vix_x_rv_total": (
                datos["^VIX"] * datos["peso_rv_total"]
            ),
            "fx_x_exterior": (
                datos["PEN=X"] * datos["peso_exterior_total"]
            ),
        }
    )


def construir_hibrido(
    base: pd.DataFrame,
    ponderado: pd.DataFrame,
) -> pd.DataFrame:
    return base.merge(
        ponderado.drop(columns=["rendimiento_simple"]),
        on=["fecha", "afp"],
        how="inner",
        validate="one_to_one",
    )


def agregar_rezagos(
    tabla: pd.DataFrame,
    rezagos: list[int],
) -> pd.DataFrame:
    ids = {"fecha", "afp", "rendimiento_simple"}
    factores = [c for c in tabla.columns if c not in ids]

    salida = tabla[
        ["fecha", "afp", "rendimiento_simple"]
    ].copy()

    for factor in factores:
        for rezago in rezagos:
            salida[f"{factor}_lag{rezago}"] = (
                tabla.groupby("afp")[factor].shift(rezago)
            )

    return salida


def crear_modelo(alpha: float | None = None) -> Pipeline:
    modelo = Pipeline(
        steps=[
            ("imputar", SimpleImputer(strategy="median")),
            ("escalar", StandardScaler()),
            ("ridge", Ridge()),
        ]
    )
    if alpha is not None:
        modelo.set_params(ridge__alpha=alpha)
    return modelo


def elegir_alpha(X: pd.DataFrame, y: pd.Series) -> float:
    busqueda = GridSearchCV(
        estimator=crear_modelo(),
        param_grid={"ridge__alpha": ALPHAS},
        scoring="neg_root_mean_squared_error",
        cv=TimeSeriesSplit(n_splits=N_SPLITS),
        n_jobs=-1,
        refit=True,
    )
    busqueda.fit(X, y)
    return float(busqueda.best_params_["ridge__alpha"])


def metricas(y: np.ndarray, p: np.ndarray) -> dict:
    y = np.asarray(y, dtype=float)
    p = np.asarray(p, dtype=float)

    return {
        "observaciones": len(y),
        "rmse": float(np.sqrt(mean_squared_error(y, p))),
        "mae": float(mean_absolute_error(y, p)),
        "r2": float(r2_score(y, p)),
        "correlacion": (
            float(np.corrcoef(y, p)[0, 1])
            if np.std(y) > 0 and np.std(p) > 0
            else np.nan
        ),
        "acierto_direccion_pct": float(
            (np.sign(y) == np.sign(p)).mean() * 100
        ),
    }


def ajustar_evaluar(
    tabla: pd.DataFrame,
    nombre_afp: str,
    escenario: str,
    esquema: str,
) -> tuple[dict, pd.DataFrame]:
    columnas = [
        c for c in tabla.columns
        if c not in {"fecha", "afp", "rendimiento_simple"}
    ]

    train = tabla[
        tabla["fecha"] < FECHA_CORTE_TEST
    ].copy()
    test = tabla[
        tabla["fecha"] >= FECHA_CORTE_TEST
    ].copy()

    if len(train) < 500 or len(test) < 50:
        raise ValueError(
            f"Datos insuficientes {nombre_afp} {escenario}: "
            f"train={len(train)}, test={len(test)}"
        )

    alpha = elegir_alpha(
        train[columnas],
        train["rendimiento_simple"],
    )
    modelo = crear_modelo(alpha)
    modelo.fit(
        train[columnas],
        train["rendimiento_simple"],
    )

    pred = modelo.predict(test[columnas])
    met = metricas(
        test["rendimiento_simple"].to_numpy(),
        pred,
    )

    resultado = {
        "afp": nombre_afp,
        "escenario": escenario,
        "esquema_rezago": esquema,
        "alpha_ridge": alpha,
        "fecha_test_inicio": test["fecha"].min(),
        "fecha_test_fin": test["fecha"].max(),
        "numero_variables": len(columnas),
        **met,
    }

    predicciones = test[
        ["fecha", "afp", "rendimiento_simple"]
    ].copy()
    predicciones["escenario"] = escenario
    predicciones["estimado"] = pred
    predicciones["error"] = (
        predicciones["rendimiento_simple"]
        - predicciones["estimado"]
    )
    predicciones["error_cuadrado"] = predicciones["error"] ** 2

    return resultado, predicciones


def bootstrap_bloques(
    mejora: np.ndarray,
) -> tuple[float, float, float, str]:
    valores = np.asarray(mejora, dtype=float)
    valores = valores[np.isfinite(valores)]

    n = len(valores)
    if n < BOOTSTRAP_BLOQUE * 2:
        return np.nan, np.nan, np.nan, "muestra_insuficiente"

    rng = np.random.default_rng(SEMILLA)
    inicios = np.arange(0, n - BOOTSTRAP_BLOQUE + 1)
    bloques = int(np.ceil(n / BOOTSTRAP_BLOQUE))
    medias = np.empty(BOOTSTRAP_REPETICIONES)

    for i in range(BOOTSTRAP_REPETICIONES):
        indices = []
        for _ in range(bloques):
            inicio = int(rng.choice(inicios))
            indices.extend(
                range(inicio, inicio + BOOTSTRAP_BLOQUE)
            )
        muestra = valores[np.asarray(indices[:n])]
        medias[i] = float(np.mean(muestra))

    media = float(np.mean(valores))
    inferior, superior = np.quantile(medias, [0.025, 0.975])

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


def comparar_parejas(
    predicciones: pd.DataFrame,
    pares: list[tuple[str, str, str]],
) -> pd.DataFrame:
    filas = []

    for nombre_comparacion, mejor, referencia in pares:
        for afp in sorted(predicciones["afp"].unique()):
            a = predicciones[
                (predicciones["afp"] == afp)
                & (predicciones["escenario"] == mejor)
            ][["fecha", "error_cuadrado"]].rename(
                columns={"error_cuadrado": "perdida_mejor"}
            )

            b = predicciones[
                (predicciones["afp"] == afp)
                & (predicciones["escenario"] == referencia)
            ][["fecha", "error_cuadrado"]].rename(
                columns={"error_cuadrado": "perdida_referencia"}
            )

            unido = a.merge(
                b,
                on="fecha",
                how="inner",
                validate="one_to_one",
            )

            if unido.empty:
                continue

            mejora = (
                unido["perdida_referencia"]
                - unido["perdida_mejor"]
            ).to_numpy()

            media, inferior, superior, evidencia = bootstrap_bloques(
                mejora
            )

            mse_ref = float(unido["perdida_referencia"].mean())
            mse_mejor = float(unido["perdida_mejor"].mean())

            filas.append(
                {
                    "comparacion": nombre_comparacion,
                    "afp": afp,
                    "escenario_evaluado": mejor,
                    "escenario_referencia": referencia,
                    "observaciones": len(unido),
                    "mse_referencia": mse_ref,
                    "mse_evaluado": mse_mejor,
                    "mejora_mse_pct": (
                        (mse_ref - mse_mejor) / mse_ref * 100
                        if mse_ref > 0
                        else np.nan
                    ),
                    "diferencia_media_perdida": media,
                    "ic95_inferior": inferior,
                    "ic95_superior": superior,
                    "evidencia_bootstrap": evidencia,
                }
            )

    return pd.DataFrame(filas)


def metricas_anuales(predicciones: pd.DataFrame) -> pd.DataFrame:
    tabla = predicciones.copy()
    tabla["anio"] = tabla["fecha"].dt.year

    filas = []
    for (afp, escenario, anio), grupo in tabla.groupby(
        ["afp", "escenario", "anio"]
    ):
        filas.append(
            {
                "afp": afp,
                "escenario": escenario,
                "anio": anio,
                **metricas(
                    grupo["rendimiento_simple"].to_numpy(),
                    grupo["estimado"].to_numpy(),
                ),
            }
        )

    return pd.DataFrame(filas)


def main() -> None:
    raiz = Path(__file__).resolve().parents[1]
    processed = raiz / "data" / "processed"

    afp = leer_afp(
        processed / "sbs_fondo3_base_maestra.csv"
    )
    mercados = leer_mercados(
        processed / "mercados_retornos_locales.csv"
    )
    pesos = leer_pesos_mensuales(
        processed / "fp1356_cartera_economica_mensual_v2.csv"
    )
    rezagos = leer_rezagos(
        processed / "fondo3_mejor_rezago_por_afp.csv",
        sorted(afp["afp"].unique()),
    )

    escenarios_pesos = {
        "M1_oraculo_1d": escenario_dinamico(
            pesos,
            "M1_oraculo_1d",
            dias_publicacion=1,
        ),
        "M1_publico_30d": escenario_dinamico(
            pesos,
            "M1_publico_30d",
            dias_publicacion=30,
        ),
        "M1_publico_45d": escenario_dinamico(
            pesos,
            "M1_publico_45d",
            dias_publicacion=45,
        ),
        "M1_publico_60d": escenario_dinamico(
            pesos,
            "M1_publico_60d",
            dias_publicacion=60,
        ),
        "M1_pesos_12m_atras": escenario_dinamico(
            pesos,
            "M1_pesos_12m_atras",
            dias_publicacion=45,
            meses_adicionales=12,
        ),
        "M1_afp_equivocada_45d": escenario_dinamico(
            pesos,
            "M1_afp_equivocada_45d",
            dias_publicacion=45,
            rotar_afp=True,
        ),
    }

    pesos_constantes = escenario_constante_train(pesos, afp)

    datos_base = afp.merge(
        mercados,
        on="fecha",
        how="inner",
        validate="many_to_one",
    )

    tablas_modelo: dict[str, pd.DataFrame] = {
        "M0_sin_pesos": construir_base_sin_pesos(datos_base)
    }

    for nombre, tabla_pesos in escenarios_pesos.items():
        asignados = asignar_pesos_asof(afp, tabla_pesos)
        datos = asignados.merge(
            mercados,
            on="fecha",
            how="inner",
            validate="many_to_one",
        )
        datos = datos.dropna(subset=["fecha_cartera"]).copy()
        tablas_modelo[nombre] = construir_factores_ponderados(datos)

    asignados_constantes = asignar_pesos_constantes(
        afp,
        pesos_constantes,
    )
    datos_constantes = asignados_constantes.merge(
        mercados,
        on="fecha",
        how="inner",
        validate="many_to_one",
    )
    tablas_modelo["M1_pesos_constantes_train"] = (
        construir_factores_ponderados(datos_constantes)
    )

    # Híbrido realista con 45 días de disponibilidad.
    base_45 = construir_base_sin_pesos(
        asignar_pesos_asof(
            afp,
            escenarios_pesos["M1_publico_45d"],
        ).merge(
            mercados,
            on="fecha",
            how="inner",
            validate="many_to_one",
        ).dropna(subset=["fecha_cartera"])
    )
    ponderado_45 = tablas_modelo["M1_publico_45d"]
    tablas_modelo["M2_hibrido_publico_45d"] = construir_hibrido(
        base_45,
        ponderado_45,
    )

    resultados = []
    predicciones = []

    for nombre_afp in sorted(afp["afp"].unique()):
        esquema = rezagos.get(nombre_afp, "lag0")
        lista_rezagos = ESQUEMAS_REZAGO[esquema]

        print("\n" + "=" * 116)
        print(
            f"AFP: {nombre_afp} | "
            f"Rezago: {esquema}"
        )
        print("-" * 116)

        for nombre_escenario, tabla in tablas_modelo.items():
            tabla_afp = tabla[
                tabla["afp"] == nombre_afp
            ].sort_values("fecha").copy()

            tabla_rezagada = agregar_rezagos(
                tabla_afp,
                lista_rezagos,
            )

            resultado, pred = ajustar_evaluar(
                tabla_rezagada,
                nombre_afp,
                nombre_escenario,
                esquema,
            )

            resultados.append(resultado)
            predicciones.append(pred)

            print(
                f"{nombre_escenario}: "
                f"RMSE={resultado['rmse']:.6f} | "
                f"R²={resultado['r2']:.4f} | "
                f"Corr={resultado['correlacion']:.4f} | "
                f"Dirección={resultado['acierto_direccion_pct']:.2f}%"
            )

    metricas_df = pd.DataFrame(resultados)
    predicciones_df = pd.concat(predicciones, ignore_index=True)

    metricas_df["ranking_rmse"] = (
        metricas_df.groupby("afp")["rmse"]
        .rank(method="first", ascending=True)
        .astype(int)
    )

    pares = [
        (
            "publico_30d_vs_sin_pesos",
            "M1_publico_30d",
            "M0_sin_pesos",
        ),
        (
            "publico_45d_vs_sin_pesos",
            "M1_publico_45d",
            "M0_sin_pesos",
        ),
        (
            "publico_60d_vs_sin_pesos",
            "M1_publico_60d",
            "M0_sin_pesos",
        ),
        (
            "hibrido_45d_vs_sin_pesos",
            "M2_hibrido_publico_45d",
            "M0_sin_pesos",
        ),
        (
            "publico_45d_vs_constante",
            "M1_publico_45d",
            "M1_pesos_constantes_train",
        ),
        (
            "publico_45d_vs_12m_atras",
            "M1_publico_45d",
            "M1_pesos_12m_atras",
        ),
        (
            "publico_45d_vs_afp_equivocada",
            "M1_publico_45d",
            "M1_afp_equivocada_45d",
        ),
        (
            "oraculo_1d_vs_publico_45d",
            "M1_oraculo_1d",
            "M1_publico_45d",
        ),
    ]

    bootstrap_df = comparar_parejas(
        predicciones_df,
        pares,
    )
    anual_df = metricas_anuales(predicciones_df)

    rutas = {
        "metricas": (
            processed / "fondo3_robustez_pesos_escenarios_metricas.csv"
        ),
        "bootstrap": (
            processed / "fondo3_robustez_pesos_bootstrap.csv"
        ),
        "anual": (
            processed / "fondo3_robustez_pesos_anual.csv"
        ),
        "predicciones": (
            processed / "fondo3_robustez_pesos_predicciones.csv"
        ),
    }

    metricas_df.to_csv(
        rutas["metricas"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    bootstrap_df.to_csv(
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

    print("\n" + "=" * 116)
    print("RANKING DE ESCENARIOS FUERA DE MUESTRA")
    print("=" * 116)
    print(
        metricas_df.sort_values(
            ["afp", "ranking_rmse"]
        )[
            [
                "afp",
                "escenario",
                "rmse",
                "mae",
                "r2",
                "correlacion",
                "acierto_direccion_pct",
                "ranking_rmse",
            ]
        ].to_string(index=False)
    )

    print("\n" + "=" * 116)
    print("PRUEBAS DE ROBUSTEZ Y PLACEBOS")
    print("=" * 116)
    print(
        bootstrap_df[
            [
                "comparacion",
                "afp",
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
        "\nCriterio estricto:\n"
        "- La composición tiene valor predictivo operativo si los escenarios "
        "de 30, 45 o 60 días superan robustamente a M0.\n"
        "- La variación mensual de pesos aporta información si 45 días supera "
        "robustamente a pesos constantes y a pesos de 12 meses atrás.\n"
        "- La información específica por AFP aporta valor si los pesos correctos "
        "superan robustamente a los pesos de otra AFP.\n"
        "- Si solo gana el escenario oráculo de 1 día, la mejora anterior tenía "
        "sesgo de disponibilidad y no es utilizable en tiempo real.\n"
        "- Aun superando estas pruebas, la identificación de sectores y acciones "
        "dentro de fondos mutuos requerirá la base CA-0001."
    )


if __name__ == "__main__":
    main()
