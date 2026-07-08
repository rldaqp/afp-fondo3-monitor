from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import ElasticNet, HuberRegressor, Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


def leer_mejor_modelo(metricas: pd.DataFrame, afp: str) -> pd.Series:
    tabla = metricas[
        (metricas["afp"] == afp)
        & (~metricas["modelo"].isin(["Benchmark_cero", "ACWI_lineal"]))
    ].copy()

    if tabla.empty:
        raise ValueError(f"No hay modelos válidos para {afp}.")

    if "ranking_rmse" in tabla.columns:
        tabla = tabla.sort_values(["ranking_rmse", "rmse"])
    else:
        tabla = tabla.sort_values("rmse")

    return tabla.iloc[0]


def construir_modelo(nombre: str, parametros_texto: str | float | None):
    parametros = {}

    if isinstance(parametros_texto, str) and parametros_texto.strip():
        try:
            parametros = ast.literal_eval(parametros_texto)
        except Exception:
            parametros = {}

    if nombre == "ElasticNet":
        alpha = parametros.get("elasticnet__alpha", 0.0001)
        l1_ratio = parametros.get("elasticnet__l1_ratio", 0.5)

        return Pipeline(
            steps=[
                ("imputar", SimpleImputer(strategy="median")),
                ("escalar", StandardScaler()),
                (
                    "elasticnet",
                    ElasticNet(
                        alpha=alpha,
                        l1_ratio=l1_ratio,
                        max_iter=100_000,
                        random_state=42,
                    ),
                ),
            ]
        )

    if nombre == "Ridge":
        alpha = parametros.get("ridge__alpha", 1.0)

        return Pipeline(
            steps=[
                ("imputar", SimpleImputer(strategy="median")),
                ("escalar", StandardScaler()),
                ("ridge", Ridge(alpha=alpha)),
            ]
        )

    if nombre == "Huber_robusto":
        return Pipeline(
            steps=[
                ("imputar", SimpleImputer(strategy="median")),
                ("escalar", StandardScaler()),
                (
                    "huber",
                    HuberRegressor(
                        epsilon=1.35,
                        alpha=0.0001,
                        max_iter=5_000,
                    ),
                ),
            ]
        )

    raise ValueError(f"Modelo no soportado: {nombre}")


def sigma_residual_fuera_muestra(
    predicciones: pd.DataFrame,
    afp: str,
    modelo: str,
) -> float:
    tabla = predicciones[
        (predicciones["afp"] == afp)
        & (predicciones["modelo"] == modelo)
    ].copy()

    if tabla.empty:
        return np.nan

    residuo = (
        pd.to_numeric(tabla["retorno_real"], errors="coerce")
        - pd.to_numeric(tabla["retorno_estimado"], errors="coerce")
    ).dropna()

    if len(residuo) < 30:
        return np.nan

    return float(residuo.std(ddof=1))


def main() -> None:
    raiz = Path(__file__).resolve().parents[1]
    processed = raiz / "data" / "processed"

    ruta_afp = processed / "sbs_fondo3_base_maestra.csv"
    ruta_factores = processed / "mercados_factores_modelo.csv"
    ruta_metricas = processed / "modelo_base_nowcast_metricas.csv"
    ruta_predicciones = processed / "modelo_base_nowcast_predicciones.csv"

    for ruta in [
        ruta_afp,
        ruta_factores,
        ruta_metricas,
        ruta_predicciones,
    ]:
        if not ruta.exists():
            raise FileNotFoundError(f"No existe el archivo requerido: {ruta}")

    afp = pd.read_csv(ruta_afp, parse_dates=["fecha"])
    factores = pd.read_csv(ruta_factores, parse_dates=["fecha"])
    metricas = pd.read_csv(ruta_metricas)
    predicciones_oos = pd.read_csv(
        ruta_predicciones,
        parse_dates=["fecha"],
    )

    columnas_factores = [
        c for c in factores.columns if c.startswith("ret_")
    ]

    if not columnas_factores:
        raise ValueError("No se encontraron columnas de factores ret_*.")

    factores = factores.sort_values("fecha").drop_duplicates("fecha").copy()

    resultados = []
    resumen_modelos = []

    for nombre_afp, grupo_afp in afp.groupby("afp"):
        grupo_afp = grupo_afp.sort_values("fecha").copy()

        ultimo = grupo_afp.iloc[-1]
        fecha_ultima_oficial = pd.Timestamp(ultimo["fecha"])
        valor_ultima_oficial = float(ultimo["valor_cuota"])

        mejor = leer_mejor_modelo(metricas, nombre_afp)
        nombre_modelo = str(mejor["modelo"])
        parametros = mejor.get("mejores_parametros", "")

        modelo = construir_modelo(nombre_modelo, parametros)

        entrenamiento = grupo_afp.merge(
            factores[["fecha"] + columnas_factores],
            on="fecha",
            how="inner",
            validate="one_to_one",
        )
        entrenamiento = entrenamiento.dropna(
            subset=["rendimiento_simple"]
        ).copy()

        X_train = entrenamiento[columnas_factores]
        y_train = pd.to_numeric(
            entrenamiento["rendimiento_simple"],
            errors="coerce",
        )

        mascara = y_train.notna()
        X_train = X_train.loc[mascara]
        y_train = y_train.loc[mascara]

        modelo.fit(X_train, y_train)

        pendientes = factores[
            factores["fecha"] > fecha_ultima_oficial
        ].copy()

        if pendientes.empty:
            print(
                f"{nombre_afp}: no hay fechas de mercado posteriores "
                f"al último valor oficial {fecha_ultima_oficial.date()}."
            )
            continue

        pendientes = pendientes.sort_values("fecha")
        pred = modelo.predict(pendientes[columnas_factores])

        sigma = sigma_residual_fuera_muestra(
            predicciones_oos,
            nombre_afp,
            nombre_modelo,
        )

        valor_estimado = valor_ultima_oficial
        retorno_acumulado = 1.0

        for numero_dia, (indice, fila) in enumerate(
            pendientes.iterrows(),
            start=1,
        ):
            retorno_estimado = float(pred[numero_dia - 1])
            valor_estimado *= (1.0 + retorno_estimado)
            retorno_acumulado *= (1.0 + retorno_estimado)

            # Intervalo aproximado acumulado con error fuera de muestra.
            if np.isfinite(sigma):
                sigma_acumulada = sigma * np.sqrt(numero_dia)
                retorno_acum = retorno_acumulado - 1.0

                retorno_bajo_80 = retorno_acum - 1.2816 * sigma_acumulada
                retorno_alto_80 = retorno_acum + 1.2816 * sigma_acumulada
                retorno_bajo_95 = retorno_acum - 1.96 * sigma_acumulada
                retorno_alto_95 = retorno_acum + 1.96 * sigma_acumulada

                valor_bajo_80 = valor_ultima_oficial * (
                    1.0 + retorno_bajo_80
                )
                valor_alto_80 = valor_ultima_oficial * (
                    1.0 + retorno_alto_80
                )
                valor_bajo_95 = valor_ultima_oficial * (
                    1.0 + retorno_bajo_95
                )
                valor_alto_95 = valor_ultima_oficial * (
                    1.0 + retorno_alto_95
                )
            else:
                valor_bajo_80 = np.nan
                valor_alto_80 = np.nan
                valor_bajo_95 = np.nan
                valor_alto_95 = np.nan

            resultados.append(
                {
                    "afp": nombre_afp,
                    "modelo": nombre_modelo,
                    "fecha_ultima_oficial": fecha_ultima_oficial,
                    "valor_ultima_oficial": valor_ultima_oficial,
                    "fecha_estimada": fila["fecha"],
                    "dias_estimados_acumulados": numero_dia,
                    "retorno_estimado_dia": retorno_estimado,
                    "retorno_estimado_dia_pct": retorno_estimado * 100,
                    "retorno_estimado_acumulado_pct": (
                        retorno_acumulado - 1.0
                    ) * 100,
                    "valor_cuota_estimado": valor_estimado,
                    "valor_estimado_bajo_80": valor_bajo_80,
                    "valor_estimado_alto_80": valor_alto_80,
                    "valor_estimado_bajo_95": valor_bajo_95,
                    "valor_estimado_alto_95": valor_alto_95,
                    "sigma_residual_oos": sigma,
                }
            )

        resumen_modelos.append(
            {
                "afp": nombre_afp,
                "modelo_operativo": nombre_modelo,
                "rmse_prueba": mejor["rmse"],
                "mae_prueba": mejor["mae"],
                "r2_prueba": mejor["r2"],
                "correlacion_prueba": mejor["correlacion"],
                "acierto_direccion_pct": mejor[
                    "acierto_direccion_pct"
                ],
                "fecha_ultima_oficial": fecha_ultima_oficial,
                "valor_ultima_oficial": valor_ultima_oficial,
                "fecha_ultimo_mercado": pendientes["fecha"].max(),
                "dias_nowcast": len(pendientes),
            }
        )

    if not resultados:
        raise RuntimeError(
            "No se generaron estimaciones. "
            "Puede que no existan fechas de mercado posteriores a la SBS."
        )

    nowcast = pd.DataFrame(resultados).sort_values(
        ["afp", "fecha_estimada"]
    )
    resumen = pd.DataFrame(resumen_modelos).sort_values("afp")

    ruta_nowcast = processed / "nowcast_operativo_fondo3.csv"
    ruta_resumen = processed / "nowcast_operativo_resumen_modelos.csv"

    nowcast.to_csv(
        ruta_nowcast,
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    resumen.to_csv(
        ruta_resumen,
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )

    print("\nNOWCAST OPERATIVO GENERADO")
    print("=" * 108)

    ultimos = (
        nowcast.sort_values("fecha_estimada")
        .groupby("afp", as_index=False)
        .tail(1)
    )

    columnas_salida = [
        "afp",
        "modelo",
        "fecha_ultima_oficial",
        "valor_ultima_oficial",
        "fecha_estimada",
        "dias_estimados_acumulados",
        "retorno_estimado_acumulado_pct",
        "valor_cuota_estimado",
        "valor_estimado_bajo_80",
        "valor_estimado_alto_80",
    ]

    print(ultimos[columnas_salida].to_string(index=False))

    print("\nModelos operativos seleccionados:")
    print(
        resumen[
            [
                "afp",
                "modelo_operativo",
                "rmse_prueba",
                "mae_prueba",
                "r2_prueba",
                "correlacion_prueba",
                "acierto_direccion_pct",
                "dias_nowcast",
            ]
        ].to_string(index=False)
    )

    print("\nArchivos creados:")
    print(f" - {ruta_nowcast.resolve()}")
    print(f" - {ruta_resumen.resolve()}")

    print(
        "\nAdvertencias:\n"
        "- Esto estima el valor cuota de fechas de mercado ya transcurridas "
        "pero todavía no publicadas por la SBS.\n"
        "- No predice el cierre del mercado de mañana.\n"
        "- Los intervalos son aproximados y se basan en el error histórico "
        "fuera de muestra; no garantizan que el valor real quede dentro.\n"
        "- No debe utilizarse todavía para invertir dinero real."
    )


if __name__ == "__main__":
    main()
