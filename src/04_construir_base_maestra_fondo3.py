from __future__ import annotations

from pathlib import Path
import numpy as np
import pandas as pd


AFPS_ESPERADAS = {"Habitat", "Integra", "Prima", "Profuturo"}


def leer_historico(ruta: Path) -> pd.DataFrame:
    if not ruta.exists():
        raise FileNotFoundError(f"No existe el archivo histórico: {ruta}")

    df = pd.read_csv(ruta, parse_dates=["fecha"])

    columnas_minimas = {"fecha", "afp", "fondo", "valor_cuota"}
    faltantes = columnas_minimas - set(df.columns)
    if faltantes:
        raise ValueError(
            f"Al histórico le faltan columnas obligatorias: {sorted(faltantes)}"
        )

    salida = df[["fecha", "afp", "fondo", "valor_cuota"]].copy()
    salida["fuente_tipo"] = "mensual_sbs"
    salida["fecha_disponible"] = pd.NaT
    salida["archivo_fuente"] = df.get("archivo_origen", pd.Series(index=df.index, dtype="object"))
    salida["prioridad_fuente"] = 2
    return salida


def leer_vintages(ruta: Path) -> pd.DataFrame:
    if not ruta.exists():
        raise FileNotFoundError(f"No existe el archivo de capturas diarias: {ruta}")

    df = pd.read_csv(ruta)

    if "fecha_valor" not in df.columns:
        raise ValueError("El archivo de vintages no contiene la columna 'fecha_valor'.")

    df["fecha_valor"] = pd.to_datetime(df["fecha_valor"], errors="coerce")
    df["fecha_descarga"] = pd.to_datetime(
        df.get("fecha_descarga"),
        errors="coerce",
        utc=True,
    )

    columnas_minimas = {"fecha_valor", "afp", "fondo", "valor_cuota"}
    faltantes = columnas_minimas - set(df.columns)
    if faltantes:
        raise ValueError(
            f"A los vintages les faltan columnas obligatorias: {sorted(faltantes)}"
        )

    # Para cada AFP-fecha, conservar la captura más reciente.
    df = df.sort_values("fecha_descarga")
    df = df.drop_duplicates(subset=["fecha_valor", "afp"], keep="last")

    salida = pd.DataFrame(
        {
            "fecha": df["fecha_valor"],
            "afp": df["afp"],
            "fondo": df["fondo"],
            "valor_cuota": pd.to_numeric(df["valor_cuota"], errors="coerce"),
            "fuente_tipo": "captura_diaria_sbs",
            "fecha_disponible": df["fecha_descarga"],
            "archivo_fuente": "sbs_fondo3_vintages.csv",
            "prioridad_fuente": 1,
        }
    )
    return salida


def encontrar_diferencias_fuentes(
    historico: pd.DataFrame,
    vintages: pd.DataFrame,
) -> pd.DataFrame:
    comparacion = historico.merge(
        vintages,
        on=["fecha", "afp", "fondo"],
        how="inner",
        suffixes=("_mensual", "_diaria"),
    )

    if comparacion.empty:
        return comparacion

    comparacion["diferencia_absoluta"] = (
        comparacion["valor_cuota_mensual"]
        - comparacion["valor_cuota_diaria"]
    )
    comparacion["diferencia_pct"] = (
        comparacion["diferencia_absoluta"]
        / comparacion["valor_cuota_mensual"]
        * 100
    )

    return comparacion[
        [
            "fecha",
            "afp",
            "fondo",
            "valor_cuota_mensual",
            "valor_cuota_diaria",
            "diferencia_absoluta",
            "diferencia_pct",
        ]
    ].sort_values(["fecha", "afp"])


def construir_base_maestra(
    historico: pd.DataFrame,
    vintages: pd.DataFrame,
) -> pd.DataFrame:
    combinado = pd.concat([historico, vintages], ignore_index=True)

    combinado["fecha"] = pd.to_datetime(combinado["fecha"], errors="coerce")
    combinado["valor_cuota"] = pd.to_numeric(
        combinado["valor_cuota"],
        errors="coerce",
    )

    combinado = combinado.dropna(
        subset=["fecha", "afp", "fondo", "valor_cuota"]
    )
    combinado = combinado[combinado["valor_cuota"] > 0]

    # Si existe dato mensual y captura diaria para una misma AFP-fecha,
    # se conserva el mensual como versión definitiva.
    combinado = combinado.sort_values(
        ["fecha", "afp", "prioridad_fuente"]
    )
    combinado = combinado.drop_duplicates(
        subset=["fecha", "afp", "fondo"],
        keep="last",
    )

    combinado = combinado.sort_values(["afp", "fecha"]).reset_index(drop=True)

    combinado["rendimiento_simple"] = (
        combinado.groupby("afp")["valor_cuota"].pct_change()
    )
    combinado["rendimiento_log"] = (
        combinado.groupby("afp")["valor_cuota"]
        .transform(lambda serie: np.log(serie / serie.shift(1)))
    )
    combinado["variacion_porcentual"] = (
        combinado["rendimiento_simple"] * 100
    )
    combinado["anio"] = combinado["fecha"].dt.year
    combinado["mes"] = combinado["fecha"].dt.month
    combinado["dia_semana_num"] = combinado["fecha"].dt.dayofweek
    combinado["dia_semana"] = combinado["fecha"].dt.day_name()

    return combinado


def crear_auditoria(base: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    resumen_afp = (
        base.groupby("afp")
        .agg(
            fecha_inicial=("fecha", "min"),
            fecha_final=("fecha", "max"),
            observaciones=("fecha", "size"),
            fechas_unicas=("fecha", "nunique"),
            valores_nulos=("valor_cuota", lambda s: int(s.isna().sum())),
            variacion_max_abs_pct=(
                "variacion_porcentual",
                lambda s: float(s.abs().max()),
            ),
            dias_variacion_mayor_5pct=(
                "variacion_porcentual",
                lambda s: int((s.abs() > 5).sum()),
            ),
        )
        .reset_index()
    )

    cobertura_fecha = (
        base.groupby("fecha")
        .agg(
            numero_afp=("afp", "nunique"),
            afp_presentes=("afp", lambda s: ", ".join(sorted(set(s)))),
        )
        .reset_index()
    )

    cobertura_fecha["completo_4_afp"] = cobertura_fecha["numero_afp"] == 4
    fechas_incompletas = cobertura_fecha[
        ~cobertura_fecha["completo_4_afp"]
    ].copy()

    anomalos = base[
        base["variacion_porcentual"].abs() > 5
    ][
        [
            "fecha",
            "afp",
            "valor_cuota",
            "variacion_porcentual",
            "fuente_tipo",
        ]
    ].copy()

    anomalos = anomalos.sort_values(
        "variacion_porcentual",
        key=lambda s: s.abs(),
        ascending=False,
    )

    return resumen_afp, fechas_incompletas, anomalos


def main() -> None:
    raiz = Path(__file__).resolve().parents[1]
    processed = raiz / "data" / "processed"

    ruta_historico = processed / "sbs_fondo3_historico_largo.csv"
    ruta_vintages = processed / "sbs_fondo3_vintages.csv"

    print("Leyendo histórico mensual...")
    historico = leer_historico(ruta_historico)

    print("Leyendo capturas diarias...")
    vintages = leer_vintages(ruta_vintages)

    print("Comparando fuentes en fechas superpuestas...")
    diferencias = encontrar_diferencias_fuentes(historico, vintages)

    print("Construyendo base maestra...")
    base = construir_base_maestra(historico, vintages)

    resumen_afp, fechas_incompletas, anomalos = crear_auditoria(base)

    salida_larga = processed / "sbs_fondo3_base_maestra.csv"
    salida_ancha = processed / "sbs_fondo3_base_maestra_ancha.csv"
    salida_resumen = processed / "sbs_fondo3_auditoria_resumen.csv"
    salida_incompletas = processed / "sbs_fondo3_fechas_incompletas.csv"
    salida_anomalos = processed / "sbs_fondo3_variaciones_anomalas.csv"
    salida_diferencias = processed / "sbs_fondo3_diferencias_fuentes.csv"

    base.to_csv(
        salida_larga,
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )

    base.pivot(
        index="fecha",
        columns="afp",
        values="valor_cuota",
    ).reset_index().to_csv(
        salida_ancha,
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )

    resumen_afp.to_csv(
        salida_resumen,
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    fechas_incompletas.to_csv(
        salida_incompletas,
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    anomalos.to_csv(
        salida_anomalos,
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    diferencias.to_csv(
        salida_diferencias,
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )

    print("\nBase maestra creada correctamente.")
    print(f"Observaciones: {len(base):,}")
    print(
        "Rango:",
        base["fecha"].min().date(),
        "a",
        base["fecha"].max().date(),
    )
    print(f"Fechas únicas: {base['fecha'].nunique():,}")
    print(
        "Fechas incompletas:",
        len(fechas_incompletas),
    )
    print(
        "Variaciones superiores a 5 % para revisar:",
        len(anomalos),
    )
    print(
        "Registros comparables entre fuente mensual y diaria:",
        len(diferencias),
    )

    if not diferencias.empty:
        max_dif = diferencias["diferencia_pct"].abs().max()
        print(
            "Máxima diferencia entre fuentes:",
            f"{max_dif:.8f} %",
        )

    print("\nÚltimos valores consolidados:")
    ultimos = (
        base.sort_values("fecha")
        .groupby("afp", as_index=False)
        .tail(1)[
            [
                "fecha",
                "afp",
                "valor_cuota",
                "fuente_tipo",
                "variacion_porcentual",
            ]
        ]
    )
    print(ultimos.to_string(index=False))

    print("\nArchivos generados:")
    for ruta in [
        salida_larga,
        salida_ancha,
        salida_resumen,
        salida_incompletas,
        salida_anomalos,
        salida_diferencias,
    ]:
        print(f" - {ruta.resolve()}")


if __name__ == "__main__":
    main()
