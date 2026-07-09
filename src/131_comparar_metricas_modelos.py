from __future__ import annotations

from pathlib import Path

import pandas as pd


def leer_csv(ruta: Path) -> pd.DataFrame:
    if not ruta.exists():
        raise FileNotFoundError(f"No existe: {ruta}")
    return pd.read_csv(ruta)


def formato_pct(valor: float, decimales: int = 2) -> str:
    if pd.isna(valor):
        return ""
    return f"{valor:.{decimales}f}%"


def formato_num(valor: float, decimales: int = 4) -> str:
    if pd.isna(valor):
        return ""
    return f"{valor:.{decimales}f}"


def tabla_markdown(df: pd.DataFrame) -> str:
    if df.empty:
        return "_Sin datos._"

    columnas = [str(c) for c in df.columns]
    filas = []
    filas.append("| " + " | ".join(columnas) + " |")
    filas.append("| " + " | ".join(["---"] * len(columnas)) + " |")
    for _, fila in df.iterrows():
        valores = []
        for valor in fila.tolist():
            if pd.isna(valor):
                valores.append("")
            else:
                texto = str(valor).replace("|", "/")
                valores.append(texto)
        filas.append("| " + " | ".join(valores) + " |")
    return "\n".join(filas)


def preparar_modelo_actual(processed: Path) -> pd.DataFrame:
    df = leer_csv(processed / "ca0001_modelo78_metricas_prueba.csv")
    actual = df[df["tipo_modelo"].eq("CANASTA_PODADA")].copy()
    actual["modelo"] = "Actual monitor: EW-Ridge canasta podada"
    actual["mae_retorno"] = actual["mae_diario"]
    actual["rmse_retorno"] = actual["rmse_diario"]
    actual["r2"] = actual["r2_diario"]
    actual["direccion_pct"] = actual["direccion_acumulada_pct"]
    actual["mape_cuota_pct"] = actual["mape_cuota_pct"]
    actual["observaciones"] = actual["n_publicacion"]
    actual["periodo"] = "prueba historica publicacion SBS"
    return actual[
        [
            "afp",
            "modelo",
            "periodo",
            "observaciones",
            "n_factores",
            "mae_retorno",
            "rmse_retorno",
            "r2",
            "mape_cuota_pct",
            "direccion_pct",
            "mediana_error_abs_pct",
            "p90_error_abs_pct",
            "error_maximo_abs_pct",
        ]
    ]


def preparar_pesos_reales(processed: Path) -> pd.DataFrame:
    df = leer_csv(processed / "fondo3_modelos_pesos_reales_metricas.csv")
    df = df.copy()
    df["modelo_largo"] = df["modelo"] + " / " + df["esquema_rezago"]
    df["mape_cuota_pct"] = pd.NA
    df["mediana_error_abs_pct"] = pd.NA
    df["p90_error_abs_pct"] = pd.NA
    df["error_maximo_abs_pct"] = pd.NA
    df["periodo"] = df["fecha_test_inicio"] + " a " + df["fecha_test_fin"]
    return df[
        [
            "afp",
            "modelo_largo",
            "periodo",
            "observaciones",
            "numero_variables",
            "mae",
            "rmse",
            "r2",
            "mape_cuota_pct",
            "acierto_direccion_pct",
            "correlacion",
            "ranking_rmse",
            "mediana_error_abs_pct",
            "p90_error_abs_pct",
            "error_maximo_abs_pct",
        ]
    ].rename(
        columns={
            "modelo_largo": "modelo",
            "numero_variables": "n_factores",
            "mae": "mae_retorno",
            "rmse": "rmse_retorno",
            "acierto_direccion_pct": "direccion_pct",
        }
    )


def mejores_pesos_reales(pesos: pd.DataFrame) -> pd.DataFrame:
    x = pesos.sort_values(["afp", "rmse_retorno"]).copy()
    return x.groupby("afp", as_index=False).head(1)


def formatear_resumen(df: pd.DataFrame) -> pd.DataFrame:
    salida = df.copy()
    for col in ["mae_retorno", "rmse_retorno", "r2", "correlacion"]:
        if col in salida.columns:
            salida[col] = pd.to_numeric(salida[col], errors="coerce").map(
                lambda v: formato_num(v, 4)
            )
    for col in [
        "mape_cuota_pct",
        "direccion_pct",
        "mediana_error_abs_pct",
        "p90_error_abs_pct",
        "error_maximo_abs_pct",
    ]:
        if col in salida.columns:
            salida[col] = pd.to_numeric(salida[col], errors="coerce").map(
                lambda v: formato_pct(v, 2)
            )
    return salida


def main() -> None:
    raiz = Path(__file__).resolve().parents[1]
    processed = raiz / "data" / "processed"
    docs = raiz / "docs"

    actual = preparar_modelo_actual(processed)
    pesos = preparar_pesos_reales(processed)
    mejores = mejores_pesos_reales(pesos)

    comparativa = pd.concat(
        [
            actual.assign(familia_comparacion="modelo_actual_monitor"),
            mejores.assign(familia_comparacion="mejor_modelo_pesos_reales"),
        ],
        ignore_index=True,
    )

    comparativa_csv = processed / "comparativa_metricas_modelos_resumen.csv"
    detalle_csv = processed / "comparativa_metricas_modelos_detalle_pesos_reales.csv"
    comparativa.to_csv(comparativa_csv, index=False, encoding="utf-8-sig")
    pesos.to_csv(detalle_csv, index=False, encoding="utf-8-sig")

    actual_md = formatear_resumen(
        actual[
            [
                "afp",
                "modelo",
                "observaciones",
                "n_factores",
                "mae_retorno",
                "rmse_retorno",
                "r2",
                "mape_cuota_pct",
                "direccion_pct",
                "p90_error_abs_pct",
            ]
        ]
    )
    mejores_md = formatear_resumen(
        mejores[
            [
                "afp",
                "modelo",
                "observaciones",
                "n_factores",
                "mae_retorno",
                "rmse_retorno",
                "r2",
                "correlacion",
                "direccion_pct",
            ]
        ]
    )
    detalle_md = formatear_resumen(
        pesos[
            [
                "afp",
                "modelo",
                "observaciones",
                "n_factores",
                "mae_retorno",
                "rmse_retorno",
                "r2",
                "correlacion",
                "direccion_pct",
                "ranking_rmse",
            ]
        ]
    )

    reporte = f"""# Comparativa de metricas de modelos Fondo 3

## Como leer las metricas

- **MAE retorno**: error promedio. Menor es mejor.
- **RMSE retorno**: error castigando mas los errores grandes. Menor es mejor.
- **R2**: cuanto explica el modelo. Mayor es mejor.
- **Correlacion**: si el retorno estimado se mueve parecido al real. Mayor es mejor.
- **MAPE cuota**: error porcentual sobre valor cuota. Menor es mejor.
- **Direccion**: porcentaje de veces que acierta sube/baja. Mayor es mejor.
- **P90 error**: en 90% de los casos el error queda por debajo de ese valor. Menor es mejor.

## Modelo actual del monitor

Este es el modelo que hoy alimenta el monitor: **EW-Ridge con canasta podada**.

{tabla_markdown(actual_md)}

## Mejores modelos con pesos reales

Estos modelos prueban si usar pesos reales de cartera mejora frente a modelos sin pesos. Se elige el mejor por menor RMSE dentro de cada AFP.

{tabla_markdown(mejores_md)}

## Detalle de modelos con pesos reales

- **M0_sin_pesos**: usa factores de mercado sin pesos de cartera.
- **M1_pesos_reales**: usa factores modulados por pesos reales de cartera.
- **M2_hibrido**: combina factores sin pesos y factores con pesos reales.

{tabla_markdown(detalle_md)}

## Criterio de eleccion propuesto

Para elegir modelo no basta una sola metrica. Propongo este orden:

1. Que tenga menor **RMSE** y **MAE**.
2. Que mantenga buena **direccion**.
3. Que tenga buena **correlacion**.
4. Que supere al modelo simple de ultima cuota SBS.
5. Que sea explicable: si dos modelos empatan, preferir el mas simple.

## Lectura actual

El modelo actual del monitor tiene una direccion alta, cerca de 80% a 84%, y MAPE de cuota alrededor de 0.64% a 0.78%.

Los modelos con pesos reales muestran que incorporar cartera ayuda en varias AFP:

- Habitat: gana el hibrido M2.
- Integra: gana M1 con pesos reales.
- Prima: gana M1 con pesos reales por RMSE, aunque M2 tiene mayor correlacion.
- Profuturo: gana el hibrido M2.

Importante: estas tablas no son todavia una competencia perfecta entre el monitor actual y la futura cartera replicante intradia, porque vienen de pruebas historicas distintas. La siguiente fase debe poner todos los modelos en el mismo periodo y con la misma regla de evaluacion.
"""

    salida = docs / "09_comparativa_metricas_modelos.md"
    salida.write_text(reporte, encoding="utf-8")

    print(f"Reporte creado: {salida}")
    print(f"CSV resumen: {comparativa_csv}")
    print(f"CSV detalle: {detalle_csv}")


if __name__ == "__main__":
    main()
