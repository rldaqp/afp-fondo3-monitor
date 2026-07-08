from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


REZAGOS = (0, 1, 2, 3)
MIN_OBSERVACIONES = 250
TOP_N = 15
UMBRAL_WINSOR = 0.01  # recorta 1 % inferior y superior para análisis robusto


def winsorizar(serie: pd.Series, proporcion: float = UMBRAL_WINSOR) -> pd.Series:
    """
    Recorta extremos sin eliminar observaciones.
    Se usa solo para comparar la sensibilidad de las correlaciones a valores atípicos.
    """
    limpia = serie.dropna()

    if limpia.empty:
        return serie

    inferior = limpia.quantile(proporcion)
    superior = limpia.quantile(1 - proporcion)
    return serie.clip(lower=inferior, upper=superior)


def correlacion_segura(
    x: pd.Series,
    y: pd.Series,
    minimo: int = MIN_OBSERVACIONES,
) -> tuple[float, int]:
    pares = pd.concat([x, y], axis=1).dropna()
    n = len(pares)

    if n < minimo:
        return np.nan, n

    correlacion = pares.iloc[:, 0].corr(pares.iloc[:, 1])
    return float(correlacion), n


def leer_afp(ruta: Path) -> pd.DataFrame:
    if not ruta.exists():
        raise FileNotFoundError(f"No existe la base maestra AFP: {ruta}")

    df = pd.read_csv(ruta, parse_dates=["fecha"])

    columnas = {"fecha", "afp", "rendimiento_simple", "variacion_porcentual"}
    faltantes = columnas - set(df.columns)

    if faltantes:
        raise ValueError(
            f"A la base AFP le faltan columnas: {sorted(faltantes)}"
        )

    df = df.sort_values(["afp", "fecha"]).copy()
    df["ret_afp"] = pd.to_numeric(
        df["rendimiento_simple"],
        errors="coerce",
    )
    df["ret_afp_w"] = (
        df.groupby("afp")["ret_afp"]
        .transform(winsorizar)
    )

    return df


def leer_factores(ruta: Path) -> tuple[pd.DataFrame, list[str]]:
    if not ruta.exists():
        raise FileNotFoundError(f"No existe la base de mercados: {ruta}")

    df = pd.read_csv(ruta, parse_dates=["fecha"])
    df = df.sort_values("fecha").drop_duplicates("fecha").copy()

    factores = [
        columna
        for columna in df.columns
        if columna.startswith("ret_")
    ]

    if not factores:
        raise ValueError(
            "No se encontraron columnas de factores que empiecen con 'ret_'."
        )

    for columna in factores:
        df[columna] = pd.to_numeric(df[columna], errors="coerce")

    # Crear rezagos sobre el calendario propio de cada mercado.
    for factor in factores:
        for rezago in REZAGOS:
            nueva = f"{factor}_lag{rezago}"
            df[nueva] = df[factor].shift(rezago)

    columnas_salida = ["fecha"] + [
        f"{factor}_lag{rezago}"
        for factor in factores
        for rezago in REZAGOS
    ]

    return df[columnas_salida], factores


def calcular_correlaciones(
    afp: pd.DataFrame,
    factores_rezagados: pd.DataFrame,
    factores: list[str],
) -> pd.DataFrame:
    combinado = afp.merge(
        factores_rezagados,
        on="fecha",
        how="left",
        validate="many_to_one",
    )

    resultados: list[dict] = []

    for nombre_afp, grupo in combinado.groupby("afp"):
        grupo = grupo.sort_values("fecha").copy()

        for factor in factores:
            for rezago in REZAGOS:
                columna = f"{factor}_lag{rezago}"

                corr_raw, n_raw = correlacion_segura(
                    grupo["ret_afp"],
                    grupo[columna],
                )

                factor_w = winsorizar(grupo[columna])
                corr_w, n_w = correlacion_segura(
                    grupo["ret_afp_w"],
                    factor_w,
                )

                resultados.append(
                    {
                        "afp": nombre_afp,
                        "factor": factor,
                        "rezago_dias_mercado": rezago,
                        "correlacion_raw": corr_raw,
                        "correlacion_winsorizada": corr_w,
                        "observaciones": min(n_raw, n_w),
                        "correlacion_abs_raw": (
                            abs(corr_raw) if pd.notna(corr_raw) else np.nan
                        ),
                        "correlacion_abs_winsorizada": (
                            abs(corr_w) if pd.notna(corr_w) else np.nan
                        ),
                    }
                )

    resultado = pd.DataFrame(resultados)

    resultado["cambio_por_extremos"] = (
        resultado["correlacion_winsorizada"]
        - resultado["correlacion_raw"]
    )

    return resultado


def seleccionar_mejor_rezago(correlaciones: pd.DataFrame) -> pd.DataFrame:
    """
    Para cada AFP y factor, conserva el rezago con mayor correlación absoluta
    winsorizada.
    """
    validas = correlaciones.dropna(
        subset=["correlacion_winsorizada"]
    ).copy()

    if validas.empty:
        return validas

    indices = (
        validas.groupby(["afp", "factor"])[
            "correlacion_abs_winsorizada"
        ]
        .idxmax()
    )

    mejor = validas.loc[indices].copy()
    mejor = mejor.sort_values(
        ["afp", "correlacion_abs_winsorizada"],
        ascending=[True, False],
    )

    mejor["ranking_afp"] = (
        mejor.groupby("afp")[
            "correlacion_abs_winsorizada"
        ]
        .rank(method="first", ascending=False)
        .astype(int)
    )

    return mejor


def crear_top_factores(mejor_rezago: pd.DataFrame) -> pd.DataFrame:
    return mejor_rezago[
        mejor_rezago["ranking_afp"] <= TOP_N
    ].copy()


def crear_cobertura_union(
    afp: pd.DataFrame,
    factores: pd.DataFrame,
) -> pd.DataFrame:
    fechas_afp = set(afp["fecha"].dropna())
    fechas_mercado = set(factores["fecha"].dropna())

    filas = [
        {
            "indicador": "fechas_afp",
            "valor": len(fechas_afp),
        },
        {
            "indicador": "fechas_mercados",
            "valor": len(fechas_mercado),
        },
        {
            "indicador": "fechas_comunes",
            "valor": len(fechas_afp & fechas_mercado),
        },
        {
            "indicador": "fechas_solo_afp",
            "valor": len(fechas_afp - fechas_mercado),
        },
        {
            "indicador": "fechas_solo_mercados",
            "valor": len(fechas_mercado - fechas_afp),
        },
    ]

    return pd.DataFrame(filas)


def main() -> None:
    raiz = Path(__file__).resolve().parents[1]
    processed = raiz / "data" / "processed"

    ruta_afp = processed / "sbs_fondo3_base_maestra.csv"
    ruta_factores = processed / "mercados_factores_modelo.csv"

    print("Leyendo base maestra del Fondo 3...")
    afp = leer_afp(ruta_afp)

    print("Leyendo factores de mercado...")
    factores_rezagados, factores = leer_factores(ruta_factores)

    print(
        f"Factores detectados: {len(factores)} | "
        f"Rezagos evaluados: {REZAGOS}"
    )

    cobertura = crear_cobertura_union(afp, factores_rezagados)

    print("Calculando correlaciones por AFP, factor y rezago...")
    correlaciones = calcular_correlaciones(
        afp,
        factores_rezagados,
        factores,
    )

    mejor_rezago = seleccionar_mejor_rezago(correlaciones)
    top_factores = crear_top_factores(mejor_rezago)

    ruta_correlaciones = (
        processed / "fondo3_correlaciones_factores_rezagos.csv"
    )
    ruta_mejor = (
        processed / "fondo3_mejor_rezago_por_factor.csv"
    )
    ruta_top = (
        processed / "fondo3_top_factores_por_afp.csv"
    )
    ruta_cobertura = (
        processed / "fondo3_cobertura_fechas_mercados.csv"
    )

    correlaciones.to_csv(
        ruta_correlaciones,
        index=False,
        encoding="utf-8-sig",
    )
    mejor_rezago.to_csv(
        ruta_mejor,
        index=False,
        encoding="utf-8-sig",
    )
    top_factores.to_csv(
        ruta_top,
        index=False,
        encoding="utf-8-sig",
    )
    cobertura.to_csv(
        ruta_cobertura,
        index=False,
        encoding="utf-8-sig",
    )

    print("\nAnálisis terminado correctamente.")
    print("\nCobertura de fechas:")
    print(cobertura.to_string(index=False))

    for nombre_afp in sorted(top_factores["afp"].unique()):
        tabla = top_factores[
            top_factores["afp"] == nombre_afp
        ][
            [
                "ranking_afp",
                "factor",
                "rezago_dias_mercado",
                "correlacion_raw",
                "correlacion_winsorizada",
                "observaciones",
            ]
        ].copy()

        print("\n" + "=" * 94)
        print(f"TOP FACTORES — {nombre_afp}")
        print("-" * 94)
        print(tabla.to_string(index=False))

    print("\nArchivos creados:")
    for ruta in [
        ruta_correlaciones,
        ruta_mejor,
        ruta_top,
        ruta_cobertura,
    ]:
        print(f" - {ruta.resolve()}")

    print(
        "\nNota metodológica:\n"
        "- rezago 0: movimiento del mercado en la misma fecha del valor cuota.\n"
        "- rezago 1: movimiento del mercado en su sesión anterior.\n"
        "- rezago 2 y 3: sesiones anteriores adicionales.\n"
        "- la correlación winsorizada reduce el efecto de valores extremos, "
        "pero no elimina observaciones.\n"
        "- una correlación alta no demuestra que la AFP posea directamente "
        "ese activo; identifica exposición estadística compatible."
    )


if __name__ == "__main__":
    main()
