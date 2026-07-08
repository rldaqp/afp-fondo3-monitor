from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


TOP_N = 20


def convertir_bool(serie: pd.Series) -> pd.Series:
    if serie.dtype == bool:
        return serie

    return (
        serie.astype(str)
        .str.strip()
        .str.lower()
        .isin({"true", "1", "si", "sí", "yes"})
    )


def preparar_base(ruta: Path) -> pd.DataFrame:
    if not ruta.exists():
        raise FileNotFoundError(f"No existe el archivo: {ruta}")

    df = pd.read_csv(ruta, parse_dates=["fecha_cartera"])

    columnas_requeridas = {
        "fecha_cartera",
        "afp",
        "nivel_profundidad",
        "nivel_1",
        "nivel_2",
        "nivel_3",
        "descripcion",
        "ruta_jerarquica",
        "participacion_pct",
        "monto_miles_soles",
        "es_hoja",
    }

    faltantes = columnas_requeridas - set(df.columns)
    if faltantes:
        raise ValueError(
            f"Faltan columnas en la base de cartera: {sorted(faltantes)}"
        )

    df["participacion_pct"] = pd.to_numeric(
        df["participacion_pct"],
        errors="coerce",
    )
    df["monto_miles_soles"] = pd.to_numeric(
        df["monto_miles_soles"],
        errors="coerce",
    )
    df["nivel_profundidad"] = pd.to_numeric(
        df["nivel_profundidad"],
        errors="coerce",
    )
    df["es_hoja"] = convertir_bool(df["es_hoja"])

    for columna in [
        "nivel_1",
        "nivel_2",
        "nivel_3",
        "descripcion",
        "ruta_jerarquica",
    ]:
        df[columna] = df[columna].fillna("").astype(str).str.strip()

    return df.sort_values(
        ["fecha_cartera", "afp", "fila_excel_aprox"]
    ).reset_index(drop=True)


def control_sumas_nivel1(base: pd.DataFrame) -> pd.DataFrame:
    nivel1 = base[
        (base["nivel_profundidad"] == 1)
        & (~base["descripcion"].str.contains(
            "total",
            case=False,
            na=False,
        ))
    ].copy()

    control = (
        nivel1.groupby(["fecha_cartera", "afp"], as_index=False)
        .agg(
            suma_participacion_pct=("participacion_pct", "sum"),
            categorias_nivel1=("descripcion", "nunique"),
        )
    )

    control["desvio_vs_100"] = (
        control["suma_participacion_pct"] - 100.0
    )
    control["estado"] = np.where(
        control["suma_participacion_pct"].between(99.0, 101.0),
        "correcto",
        "revisar",
    )

    return control


def hojas_validas(base: pd.DataFrame) -> pd.DataFrame:
    hojas = base[
        base["es_hoja"]
        & base["participacion_pct"].notna()
        & (~base["descripcion"].str.contains(
            "total",
            case=False,
            na=False,
        ))
    ].copy()

    # Se excluyen notas y filas sin una descripción útil.
    hojas = hojas[
        hojas["descripcion"].str.len() > 2
    ].copy()

    return hojas


def top_ultimo_mes(hojas: pd.DataFrame) -> pd.DataFrame:
    ultima_fecha = hojas["fecha_cartera"].max()

    ultimo = hojas[
        hojas["fecha_cartera"] == ultima_fecha
    ].copy()

    ultimo["participacion_abs"] = (
        ultimo["participacion_pct"].abs()
    )

    ultimo = ultimo.sort_values(
        ["afp", "participacion_abs"],
        ascending=[True, False],
    )

    ultimo["ranking_afp"] = (
        ultimo.groupby("afp")
        .cumcount()
        .add(1)
    )

    return ultimo[
        ultimo["ranking_afp"] <= TOP_N
    ].copy()


def resumen_nivel2_ultimo_mes(base: pd.DataFrame) -> pd.DataFrame:
    ultima_fecha = base["fecha_cartera"].max()

    nivel2 = base[
        (base["fecha_cartera"] == ultima_fecha)
        & (base["nivel_profundidad"] == 2)
        & base["participacion_pct"].notna()
        & (~base["descripcion"].str.contains(
            "total",
            case=False,
            na=False,
        ))
    ].copy()

    return nivel2.sort_values(
        ["afp", "participacion_pct"],
        ascending=[True, False],
    )


def catalogo_frecuencia(hojas: pd.DataFrame) -> pd.DataFrame:
    catalogo = (
        hojas.groupby(
            [
                "nivel_1",
                "nivel_2",
                "nivel_3",
                "descripcion",
                "ruta_jerarquica",
            ],
            dropna=False,
        )
        .agg(
            primera_fecha=("fecha_cartera", "min"),
            ultima_fecha=("fecha_cartera", "max"),
            meses_presentes=("fecha_cartera", "nunique"),
            afp_presentes=("afp", "nunique"),
            participacion_mediana_pct=(
                "participacion_pct",
                "median",
            ),
            participacion_max_abs_pct=(
                "participacion_pct",
                lambda s: float(pd.Series(s).abs().max()),
            ),
            observaciones=("participacion_pct", "size"),
        )
        .reset_index()
    )

    catalogo = catalogo.sort_values(
        [
            "participacion_max_abs_pct",
            "meses_presentes",
        ],
        ascending=[False, False],
    )

    catalogo["id_instrumento"] = np.arange(
        1,
        len(catalogo) + 1,
    )

    columnas = [
        "id_instrumento",
        "nivel_1",
        "nivel_2",
        "nivel_3",
        "descripcion",
        "ruta_jerarquica",
        "primera_fecha",
        "ultima_fecha",
        "meses_presentes",
        "afp_presentes",
        "participacion_mediana_pct",
        "participacion_max_abs_pct",
        "observaciones",
    ]

    return catalogo[columnas]


def descripciones_para_mapeo(
    catalogo: pd.DataFrame,
) -> pd.DataFrame:
    salida = catalogo.copy()

    salida["categoria_economica_propuesta"] = ""
    salida["factor_mercado_propuesto"] = ""
    salida["requiere_revision_manual"] = "SI"
    salida["comentario_revision"] = ""

    return salida


def main() -> None:
    raiz = Path(__file__).resolve().parents[1]
    processed = raiz / "data" / "processed"

    ruta_base = (
        processed / "fp1356_fondo3_cartera_largo.csv"
    )

    base = preparar_base(ruta_base)
    control = control_sumas_nivel1(base)
    hojas = hojas_validas(base)
    top = top_ultimo_mes(hojas)
    nivel2 = resumen_nivel2_ultimo_mes(base)
    catalogo = catalogo_frecuencia(hojas)
    mapeo = descripciones_para_mapeo(catalogo)

    rutas = {
        "control": (
            processed / "fp1356_control_sumas_mensuales.csv"
        ),
        "nivel2": (
            processed / "fp1356_resumen_nivel2_ultimo_mes.csv"
        ),
        "top": (
            processed / "fp1356_top_instrumentos_ultimo_mes.csv"
        ),
        "catalogo": (
            processed / "fp1356_catalogo_instrumentos_frecuencia.csv"
        ),
        "mapeo": (
            processed / "fp1356_descripciones_para_mapeo.csv"
        ),
    }

    control.to_csv(
        rutas["control"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    nivel2.to_csv(
        rutas["nivel2"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    top.to_csv(
        rutas["top"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    catalogo.to_csv(
        rutas["catalogo"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    mapeo.to_csv(
        rutas["mapeo"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )

    ultima_fecha = base["fecha_cartera"].max()

    print("\nAUDITORÍA DETALLADA FP-1356 TERMINADA")
    print("=" * 108)
    print(f"Última fecha de cartera: {ultima_fecha.date()}")
    print(f"Registros hoja analizados: {len(hojas):,}")
    print(f"Instrumentos/rutas únicas: {len(catalogo):,}")
    print(
        "AFP-mes con suma de nivel 1 correcta:",
        int((control["estado"] == "correcto").sum()),
        "de",
        len(control),
    )
    print(
        "AFP-mes para revisar:",
        int((control["estado"] == "revisar").sum()),
    )

    print("\nCATEGORÍAS DE NIVEL 2 DEL ÚLTIMO MES")
    print("-" * 108)
    print(
        nivel2[
            [
                "fecha_cartera",
                "afp",
                "nivel_1",
                "descripcion",
                "participacion_pct",
            ]
        ].to_string(index=False)
    )

    print("\nTOP INSTRUMENTOS/DETALLES DEL ÚLTIMO MES")
    print("-" * 108)

    for afp in sorted(top["afp"].unique()):
        tabla = top[top["afp"] == afp].copy()

        print(f"\n{afp}")
        print(
            tabla[
                [
                    "ranking_afp",
                    "nivel_1",
                    "nivel_2",
                    "descripcion",
                    "participacion_pct",
                ]
            ].to_string(index=False)
        )

    print("\nArchivos creados:")
    for ruta in rutas.values():
        print(f" - {ruta.resolve()}")

    print(
        "\nSiguiente paso:\n"
        "Usaremos fp1356_descripciones_para_mapeo.csv para asignar "
        "cada instrumento a una categoría económica y a un factor de "
        "mercado. No se construirán pesos dinámicos hasta revisar que "
        "las filas terminales no estén duplicando subtotales."
    )


if __name__ == "__main__":
    main()
