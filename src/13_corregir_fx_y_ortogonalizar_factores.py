from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LinearRegression, Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import GridSearchCV, TimeSeriesSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


FECHA_CORTE_TEST = pd.Timestamp("2025-01-01")
ALPHAS = [0.01, 0.1, 1.0, 10.0, 100.0, 1000.0]
N_SPLITS = 5

TICKERS_NECESARIOS = [
    "ACWI",
    "XLK",
    "EEM",
    "EPU",
    "COPX",
    "TLT",
    "HYG",
    "LQD",
    "^VIX",
    "PEN=X",
]


def preparar_tabla_mercado(ruta: Path) -> pd.DataFrame:
    if not ruta.exists():
        raise FileNotFoundError(f"No existe: {ruta}")

    df = pd.read_csv(ruta, parse_dates=["fecha"])
    df = df.sort_values("fecha").drop_duplicates("fecha").copy()

    faltantes = [c for c in TICKERS_NECESARIOS if c not in df.columns]
    if faltantes:
        raise ValueError(
            f"Faltan columnas de mercado en {ruta.name}: {faltantes}"
        )

    for columna in TICKERS_NECESARIOS:
        df[columna] = pd.to_numeric(df[columna], errors="coerce")

    return df


def preparar_afp(ruta: Path) -> pd.DataFrame:
    if not ruta.exists():
        raise FileNotFoundError(f"No existe: {ruta}")

    df = pd.read_csv(ruta, parse_dates=["fecha"])
    df["rendimiento_simple"] = pd.to_numeric(
        df["rendimiento_simple"],
        errors="coerce",
    )
    return df.sort_values(["afp", "fecha"]).copy()


def diseno_a_usd_mas_fx(raw: pd.DataFrame) -> pd.DataFrame:
    """
    Modelo A:
    Activos internacionales en su moneda de cotización (USD)
    + USD/PEN como factor independiente.
    """
    salida = pd.DataFrame({"fecha": raw["fecha"]})
    salida["mercado_global_usd"] = raw["ACWI"]
    salida["tecnologia_usd"] = raw["XLK"]
    salida["emergentes_usd"] = raw["EEM"]
    salida["peru_usd"] = raw["EPU"]
    salida["mineras_cobre_usd"] = raw["COPX"]
    salida["bonos_tesoro_usd"] = raw["TLT"]
    salida["spread_credito_usd"] = raw["HYG"] - raw["LQD"]
    salida["vix"] = raw["^VIX"]
    salida["fx_usdpen"] = raw["PEN=X"]
    return salida


def diseno_b_pen_sin_fx(pen: pd.DataFrame) -> pd.DataFrame:
    """
    Modelo B:
    Activos ya convertidos a PEN, sin volver a agregar USD/PEN.
    """
    salida = pd.DataFrame({"fecha": pen["fecha"]})
    salida["mercado_global_pen"] = pen["ACWI"]
    salida["tecnologia_pen"] = pen["XLK"]
    salida["emergentes_pen"] = pen["EEM"]
    salida["peru_pen"] = pen["EPU"]
    salida["mineras_cobre_pen"] = pen["COPX"]
    salida["bonos_tesoro_pen"] = pen["TLT"]
    salida["spread_credito_pen"] = pen["HYG"] - pen["LQD"]
    salida["vix"] = pen["^VIX"]
    return salida


def ajustar_residualizador(
    datos: pd.DataFrame,
    objetivo: str,
    predictores: list[str],
) -> Pipeline:
    mascara = datos[objetivo].notna()

    modelo = Pipeline(
        steps=[
            ("imputar", SimpleImputer(strategy="median")),
            ("regresion", LinearRegression()),
        ]
    )

    modelo.fit(
        datos.loc[mascara, predictores],
        datos.loc[mascara, objetivo],
    )
    return modelo


def transformar_residual(
    datos: pd.DataFrame,
    objetivo: str,
    predictores: list[str],
    modelo: Pipeline,
) -> pd.Series:
    prediccion = modelo.predict(datos[predictores])
    residual = datos[objetivo] - prediccion
    residual[datos[objetivo].isna()] = np.nan
    return residual


def ajustar_ortogonalizadores(
    entrenamiento_raw: pd.DataFrame,
) -> dict[str, tuple[Pipeline, str, list[str]]]:
    """
    Jerarquía:
    mercado global -> tecnología/emergentes -> Perú -> cobre.
    Así cada bloque adicional representa movimiento no explicado
    por los bloques más generales anteriores.
    """
    especificaciones = {
        "tecnologia_extra": ("XLK", ["ACWI"]),
        "emergentes_extra": ("EEM", ["ACWI"]),
        "peru_extra": ("EPU", ["ACWI", "EEM"]),
        "cobre_extra": ("COPX", ["ACWI", "EEM", "EPU"]),
    }

    modelos = {}

    for nombre, (objetivo, predictores) in especificaciones.items():
        modelo = ajustar_residualizador(
            entrenamiento_raw,
            objetivo,
            predictores,
        )
        modelos[nombre] = (modelo, objetivo, predictores)

    return modelos


def diseno_c_bloques_ortogonales(
    raw: pd.DataFrame,
    ortogonalizadores: dict[str, tuple[Pipeline, str, list[str]]],
) -> pd.DataFrame:
    salida = pd.DataFrame({"fecha": raw["fecha"]})
    salida["mercado_global"] = raw["ACWI"]

    for nombre, (modelo, objetivo, predictores) in ortogonalizadores.items():
        salida[nombre] = transformar_residual(
            raw,
            objetivo,
            predictores,
            modelo,
        )

    salida["bonos_tesoro"] = raw["TLT"]
    salida["spread_credito"] = raw["HYG"] - raw["LQD"]
    salida["vix"] = raw["^VIX"]
    salida["fx_usdpen"] = raw["PEN=X"]
    return salida


def crear_ridge() -> Pipeline:
    return Pipeline(
        steps=[
            ("imputar", SimpleImputer(strategy="median")),
            ("escalar", StandardScaler()),
            ("ridge", Ridge()),
        ]
    )


def seleccionar_alpha(
    X: pd.DataFrame,
    y: pd.Series,
) -> float:
    busqueda = GridSearchCV(
        estimator=crear_ridge(),
        param_grid={"ridge__alpha": ALPHAS},
        scoring="neg_root_mean_squared_error",
        cv=TimeSeriesSplit(n_splits=N_SPLITS),
        n_jobs=-1,
        refit=True,
    )
    busqueda.fit(X, y)
    return float(busqueda.best_params_["ridge__alpha"])


def metricas(
    y_real: pd.Series,
    y_pred: np.ndarray,
) -> dict:
    real = np.asarray(y_real, dtype=float)
    pred = np.asarray(y_pred, dtype=float)

    mae = mean_absolute_error(real, pred)
    rmse = float(np.sqrt(mean_squared_error(real, pred)))
    r2 = r2_score(real, pred)

    correlacion = (
        float(np.corrcoef(real, pred)[0, 1])
        if np.std(real) > 0 and np.std(pred) > 0
        else np.nan
    )

    acierto = float(
        (np.sign(real) == np.sign(pred)).mean() * 100
    )

    return {
        "observaciones": len(real),
        "mae": mae,
        "rmse": rmse,
        "r2": r2,
        "correlacion": correlacion,
        "acierto_direccion_pct": acierto,
    }


def coeficientes_originales(
    modelo: Pipeline,
    columnas: list[str],
) -> tuple[pd.DataFrame, float]:
    scaler = modelo.named_steps["escalar"]
    ridge = modelo.named_steps["ridge"]

    coef_std = np.asarray(ridge.coef_, dtype=float)
    coef_original = coef_std / scaler.scale_

    intercepto = float(
        ridge.intercept_
        - np.sum(coef_std * scaler.mean_ / scaler.scale_)
    )

    tabla = pd.DataFrame(
        {
            "factor": columnas,
            "coef_estandarizado": coef_std,
            "coef_original": coef_original,
        }
    )
    tabla["coef_abs_estandarizado"] = tabla[
        "coef_estandarizado"
    ].abs()

    return tabla, intercepto


def evaluar_diseno(
    nombre_afp: str,
    nombre_modelo: str,
    afp_train: pd.DataFrame,
    afp_test: pd.DataFrame,
    diseno_train: pd.DataFrame,
    diseno_test: pd.DataFrame,
) -> tuple[dict, Pipeline, list[str]]:
    columnas = [c for c in diseno_train.columns if c != "fecha"]

    train = afp_train[["fecha", "rendimiento_simple"]].merge(
        diseno_train,
        on="fecha",
        how="inner",
        validate="one_to_one",
    ).dropna(subset=["rendimiento_simple"])

    test = afp_test[["fecha", "rendimiento_simple"]].merge(
        diseno_test,
        on="fecha",
        how="inner",
        validate="one_to_one",
    ).dropna(subset=["rendimiento_simple"])

    X_train = train[columnas]
    y_train = train["rendimiento_simple"]
    X_test = test[columnas]
    y_test = test["rendimiento_simple"]

    alpha = seleccionar_alpha(X_train, y_train)
    modelo = crear_ridge()
    modelo.set_params(ridge__alpha=alpha)
    modelo.fit(X_train, y_train)

    pred = modelo.predict(X_test)
    met = metricas(y_test, pred)

    resultado = {
        "afp": nombre_afp,
        "metodo": nombre_modelo,
        "alpha_ridge": alpha,
        "fecha_test_inicio": test["fecha"].min(),
        "fecha_test_fin": test["fecha"].max(),
        **met,
    }

    return resultado, modelo, columnas


def ajustar_y_atribuir_ultima_fecha(
    nombre_afp: str,
    nombre_modelo: str,
    afp_completa: pd.DataFrame,
    diseno_completo: pd.DataFrame,
    alpha: float,
) -> tuple[pd.DataFrame, dict]:
    columnas = [c for c in diseno_completo.columns if c != "fecha"]

    combinado = afp_completa[
        ["fecha", "rendimiento_simple"]
    ].merge(
        diseno_completo,
        on="fecha",
        how="inner",
        validate="one_to_one",
    ).dropna(subset=["rendimiento_simple"])

    X = combinado[columnas]
    y = combinado["rendimiento_simple"]

    modelo = crear_ridge()
    modelo.set_params(ridge__alpha=alpha)
    modelo.fit(X, y)

    ultima = combinado.iloc[-1]
    X_ultima = combinado[columnas].iloc[[-1]]

    pred = float(modelo.predict(X_ultima)[0])
    real = float(ultima["rendimiento_simple"])
    residual = real - pred

    coef, intercepto = coeficientes_originales(
        modelo,
        columnas,
    )

    valores = X_ultima.iloc[0].to_dict()
    coef["valor_factor"] = coef["factor"].map(valores)
    coef["contribucion_retorno"] = (
        coef["coef_original"] * coef["valor_factor"]
    )
    coef["contribucion_puntos_pct"] = (
        coef["contribucion_retorno"] * 100
    )

    coef["afp"] = nombre_afp
    coef["metodo"] = nombre_modelo
    coef["fecha"] = ultima["fecha"]
    coef["retorno_real_pct"] = real * 100
    coef["retorno_estimado_pct"] = pred * 100
    coef["residual_pct"] = residual * 100
    coef["intercepto_pct"] = intercepto * 100

    coef = coef.sort_values(
        "contribucion_retorno",
        key=lambda s: s.abs(),
        ascending=False,
    ).reset_index(drop=True)
    coef["ranking_contribucion"] = np.arange(1, len(coef) + 1)

    resumen = {
        "afp": nombre_afp,
        "metodo": nombre_modelo,
        "fecha": ultima["fecha"],
        "retorno_real_pct": real * 100,
        "retorno_estimado_pct": pred * 100,
        "residual_pct": residual * 100,
        "parte_explicada_pct_sobre_movimiento": (
            pred / real * 100 if real != 0 else np.nan
        ),
        "alpha_ridge": alpha,
    }

    return coef, resumen


def main() -> None:
    raiz = Path(__file__).resolve().parents[1]
    processed = raiz / "data" / "processed"

    ruta_afp = processed / "sbs_fondo3_base_maestra.csv"
    ruta_raw = processed / "mercados_retornos_locales.csv"
    ruta_pen = processed / "mercados_retornos_en_pen.csv"

    afp = preparar_afp(ruta_afp)
    raw = preparar_tabla_mercado(ruta_raw)
    pen = preparar_tabla_mercado(ruta_pen)

    diseno_a = diseno_a_usd_mas_fx(raw)
    diseno_b = diseno_b_pen_sin_fx(pen)

    resultados_metricas = []
    atribuciones = []
    resumen_ultima = []
    bloques_guardar = []

    for nombre_afp, grupo_afp in afp.groupby("afp"):
        grupo_afp = grupo_afp.sort_values("fecha").copy()

        afp_train = grupo_afp[
            grupo_afp["fecha"] < FECHA_CORTE_TEST
        ].copy()
        afp_test = grupo_afp[
            grupo_afp["fecha"] >= FECHA_CORTE_TEST
        ].copy()

        raw_train = raw[raw["fecha"] < FECHA_CORTE_TEST].copy()
        raw_test = raw[raw["fecha"] >= FECHA_CORTE_TEST].copy()

        ortogonalizadores_train = ajustar_ortogonalizadores(
            raw_train
        )
        diseno_c_train = diseno_c_bloques_ortogonales(
            raw_train,
            ortogonalizadores_train,
        )
        diseno_c_test = diseno_c_bloques_ortogonales(
            raw_test,
            ortogonalizadores_train,
        )

        diseños = {
            "A_USD_mas_FX": (
                diseno_a[diseno_a["fecha"] < FECHA_CORTE_TEST],
                diseno_a[diseno_a["fecha"] >= FECHA_CORTE_TEST],
            ),
            "B_PEN_sin_FX": (
                diseno_b[diseno_b["fecha"] < FECHA_CORTE_TEST],
                diseno_b[diseno_b["fecha"] >= FECHA_CORTE_TEST],
            ),
            "C_Bloques_ortogonales": (
                diseno_c_train,
                diseno_c_test,
            ),
        }

        alphas_por_metodo = {}

        print("\n" + "=" * 100)
        print(f"AFP: {nombre_afp}")
        print("-" * 100)

        for nombre_metodo, (
            diseño_train,
            diseño_test,
        ) in diseños.items():
            resultado, _, _ = evaluar_diseno(
                nombre_afp,
                nombre_metodo,
                afp_train,
                afp_test,
                diseño_train,
                diseño_test,
            )

            resultados_metricas.append(resultado)
            alphas_por_metodo[nombre_metodo] = resultado[
                "alpha_ridge"
            ]

            print(
                f"{nombre_metodo}: "
                f"RMSE={resultado['rmse']:.6f} | "
                f"R²={resultado['r2']:.4f} | "
                f"Corr={resultado['correlacion']:.4f} | "
                f"Dirección={resultado['acierto_direccion_pct']:.2f}%"
            )

        # Para la atribución final, los ortogonalizadores se reajustan
        # usando todos los datos disponibles hasta la última fecha.
        ortogonalizadores_full = ajustar_ortogonalizadores(raw)
        diseno_c_full = diseno_c_bloques_ortogonales(
            raw,
            ortogonalizadores_full,
        )

        diseños_full = {
            "A_USD_mas_FX": diseno_a,
            "B_PEN_sin_FX": diseno_b,
            "C_Bloques_ortogonales": diseno_c_full,
        }

        for nombre_metodo, diseño_full in diseños_full.items():
            detalle, resumen = ajustar_y_atribuir_ultima_fecha(
                nombre_afp,
                nombre_metodo,
                grupo_afp,
                diseño_full,
                alphas_por_metodo[nombre_metodo],
            )
            atribuciones.append(detalle)
            resumen_ultima.append(resumen)

        bloques_afp = diseno_c_full.copy()
        bloques_afp["afp_referencia"] = nombre_afp
        bloques_guardar.append(bloques_afp)

    metricas_df = pd.DataFrame(resultados_metricas)
    atribuciones_df = pd.concat(
        atribuciones,
        ignore_index=True,
    )
    resumen_df = pd.DataFrame(resumen_ultima)
    bloques_df = pd.concat(
        bloques_guardar,
        ignore_index=True,
    ).drop_duplicates(subset=["fecha"])

    metricas_df["ranking_rmse"] = (
        metricas_df.groupby("afp")["rmse"]
        .rank(method="first", ascending=True)
        .astype(int)
    )

    ruta_metricas = (
        processed / "fondo3_comparacion_metodos_fx.csv"
    )
    ruta_atribucion = (
        processed / "fondo3_atribucion_corregida_ultima_fecha.csv"
    )
    ruta_resumen = (
        processed / "fondo3_resumen_corregido_ultima_fecha.csv"
    )
    ruta_bloques = (
        processed / "mercados_factores_bloques_ortogonales.csv"
    )

    metricas_df.to_csv(
        ruta_metricas,
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    atribuciones_df.to_csv(
        ruta_atribucion,
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    resumen_df.to_csv(
        ruta_resumen,
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    bloques_df.to_csv(
        ruta_bloques,
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )

    print("\n" + "=" * 100)
    print("COMPARACIÓN FUERA DE MUESTRA")
    print("=" * 100)
    print(
        metricas_df.sort_values(
            ["afp", "ranking_rmse"]
        )[
            [
                "afp",
                "metodo",
                "rmse",
                "mae",
                "r2",
                "correlacion",
                "acierto_direccion_pct",
                "ranking_rmse",
            ]
        ].to_string(index=False)
    )

    print("\n" + "=" * 100)
    print("ATRIBUCIÓN CORREGIDA — BLOQUES ORTOGONALES")
    print("=" * 100)

    tabla_c = atribuciones_df[
        atribuciones_df["metodo"] == "C_Bloques_ortogonales"
    ].copy()

    for nombre_afp in sorted(tabla_c["afp"].unique()):
        tabla = tabla_c[
            tabla_c["afp"] == nombre_afp
        ].head(10)

        print(f"\n{nombre_afp}")
        print("-" * 100)
        print(
            tabla[
                [
                    "fecha",
                    "factor",
                    "contribucion_puntos_pct",
                    "retorno_real_pct",
                    "retorno_estimado_pct",
                    "residual_pct",
                ]
            ].to_string(index=False)
        )

    print("\nArchivos creados:")
    for ruta in [
        ruta_metricas,
        ruta_atribucion,
        ruta_resumen,
        ruta_bloques,
    ]:
        print(f" - {ruta.resolve()}")

    print(
        "\nCómo interpretar:\n"
        "- A_USD_mas_FX: activos en USD y tipo de cambio separado.\n"
        "- B_PEN_sin_FX: activos convertidos a soles, sin duplicar USD/PEN.\n"
        "- C_Bloques_ortogonales: separa mercado global, tecnología, "
        "emergentes, Perú y cobre para reducir solapamientos.\n"
        "- Si A y B tienen resultados similares, la relación cambiaria es "
        "más confiable.\n"
        "- Si C conserva buen desempeño con menor solapamiento, sus "
        "contribuciones son más interpretables.\n"
        "- Los bloques siguen siendo exposiciones estadísticas, no "
        "porcentajes exactos de cartera."
    )


if __name__ == "__main__":
    main()
