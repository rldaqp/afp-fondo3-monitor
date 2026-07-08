from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd


AFPS = ["Habitat", "Integra", "Prima", "Profuturo"]


def normalizar(valor: object) -> str:
    if pd.isna(valor):
        return ""

    texto = str(valor).strip().lower()
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(
        caracter
        for caracter in texto
        if not unicodedata.combining(caracter)
    )
    texto = re.sub(r"\s+", " ", texto)
    return texto


def convertir_bool(serie: pd.Series) -> pd.Series:
    if serie.dtype == bool:
        return serie

    return (
        serie.astype(str)
        .str.strip()
        .str.lower()
        .isin({"true", "1", "si", "sí", "yes"})
    )


def es_total_o_control(fila: pd.Series) -> bool:
    nivel_1 = normalizar(fila.get("nivel_1", ""))
    descripcion = normalizar(fila.get("descripcion", ""))
    ruta = normalizar(fila.get("ruta_jerarquica", ""))

    if nivel_1 == "total":
        return True

    if descripcion in {
        "fondo de pensiones",
        "encaje legal",
    }:
        return True

    if ruta.startswith("total >"):
        return True

    return False


def contiene_alguno(texto: str, terminos: list[str]) -> bool:
    return any(termino in texto for termino in terminos)


def clasificar_categoria(fila: pd.Series) -> tuple[str, str, str]:
    """
    Retorna:
      categoria_economica,
      factor_representativo_inicial,
      calidad_proxy_inicial.

    La clasificación se basa en el instrumento publicado por la SBS.
    No identifica todavía el emisor o fondo subyacente.
    """
    descripcion = normalizar(fila.get("descripcion", ""))
    nivel_1 = normalizar(fila.get("nivel_1", ""))
    nivel_2 = normalizar(fila.get("nivel_2", ""))
    ruta = normalizar(fila.get("ruta_jerarquica", ""))

    exterior = "inversiones en el exterior" in nivel_1
    local = "inversiones locales" in nivel_1

    if "operaciones en transito" in descripcion or "operaciones en transito" in ruta:
        return (
            "operaciones_en_transito",
            "sin_factor_directo",
            "no_aplicable",
        )

    if contiene_alguno(
        descripcion,
        [
            "fondos mutuos alternativos del extranjero",
            "fondo mutuo alternativo extranjero",
        ],
    ):
        return (
            "alternativos_exterior",
            "proxy_alternativos_pendiente",
            "baja",
        )

    if (
        "fondos mutuos del extranjero" in descripcion
        and "etf" in descripcion
    ):
        return (
            "etf_exterior_via_mercado_local",
            "ACWI_EEM_QQQ_por_identificar",
            "media",
        )

    if "fondos mutuos del extranjero" in descripcion:
        return (
            "fondos_mutuos_exterior",
            "ACWI",
            "media",
        )

    if "fondo de inversion alternativo" in descripcion:
        return (
            "alternativos_local",
            "proxy_alternativos_pendiente",
            "baja",
        )

    if "fondo de inversion tradicional" in descripcion:
        return (
            "fondos_inversion_local_tradicional",
            "proxy_fondos_locales_pendiente",
            "baja",
        )

    if "titulos con derecho de participacion" in descripcion:
        return (
            "titulizaciones_participacion_local",
            "proxy_activos_alternativos_locales_pendiente",
            "baja",
        )

    if "bonos de titulizacion" in descripcion:
        return (
            "titulizaciones_deuda_local",
            "proxy_credito_local_pendiente",
            "baja",
        )

    if "acciones y valores representativos sobre acciones" in descripcion:
        if exterior:
            return (
                "acciones_exterior_directas",
                "ACWI",
                "media",
            )

        if local and "sistema financiero" in nivel_2:
            return (
                "acciones_locales_financieras",
                "EPU_financieras_por_identificar",
                "media",
            )

        if local:
            return (
                "acciones_locales_no_financieras",
                "EPU",
                "media",
            )

    if contiene_alguno(
        descripcion,
        [
            "bonos del gobierno central",
            "certificados y depositos a plazo del bcrp",
            "letras del tesoro",
            "bonos brady",
        ],
    ):
        return (
            "renta_fija_soberana_local",
            "tasas_soberanas_peru_pendiente",
            "baja",
        )

    if (
        exterior
        and "gobierno" in nivel_2
        and contiene_alguno(
            descripcion,
            [
                "titulos de deuda",
                "bonos",
                "letras",
            ],
        )
    ):
        return (
            "renta_fija_soberana_exterior",
            "TLT",
            "media",
        )

    if "certificados y depositos a plazo" in descripcion:
        if exterior:
            return (
                "depositos_exterior",
                "tasas_cortas_usd_fx",
                "baja",
            )

        return (
            "depositos_locales",
            "tasas_cortas_pen_pendiente",
            "baja",
        )

    if "organismos internacionales" in descripcion:
        return (
            "renta_fija_organismos_internacionales",
            "LQD_TLT",
            "baja",
        )

    if "sistema financiero" in nivel_2 and contiene_alguno(
        descripcion,
        [
            "bonos",
            "papeles comerciales",
            "titulos de deuda",
        ],
    ):
        if exterior:
            return (
                "renta_fija_financiera_exterior",
                "LQD_HYG",
                "media",
            )

        return (
            "renta_fija_financiera_local",
            "credito_financiero_peru_pendiente",
            "baja",
        )

    if "empresas no financieras" in nivel_2 and contiene_alguno(
        descripcion,
        [
            "bonos",
            "papeles comerciales",
            "nuevos proyectos",
            "titulos de deuda",
        ],
    ):
        if exterior:
            return (
                "renta_fija_no_financiera_exterior",
                "LQD_HYG",
                "media",
            )

        return (
            "renta_fija_no_financiera_local",
            "credito_corporativo_peru_pendiente",
            "baja",
        )

    if exterior and contiene_alguno(
        descripcion,
        [
            "bonos",
            "titulos de deuda",
            "papeles comerciales",
        ],
    ):
        return (
            "renta_fija_exterior_otros",
            "LQD_HYG_TLT",
            "baja",
        )

    if local and contiene_alguno(
        descripcion,
        [
            "bonos",
            "titulos de deuda",
            "papeles comerciales",
        ],
    ):
        return (
            "renta_fija_local_otros",
            "proxy_renta_fija_local_pendiente",
            "baja",
        )

    return (
        "otros_no_mapeados",
        "sin_proxy",
        "no_disponible",
    )


def preparar_base(ruta: Path) -> pd.DataFrame:
    if not ruta.exists():
        raise FileNotFoundError(f"No existe: {ruta}")

    base = pd.read_csv(
        ruta,
        parse_dates=["fecha_cartera"],
    )

    requeridas = {
        "fecha_cartera",
        "afp",
        "nivel_1",
        "nivel_2",
        "nivel_3",
        "descripcion",
        "ruta_jerarquica",
        "participacion_pct",
        "monto_miles_soles",
        "es_hoja",
    }

    faltantes = requeridas - set(base.columns)
    if faltantes:
        raise ValueError(
            f"Faltan columnas: {sorted(faltantes)}"
        )

    base["participacion_pct"] = pd.to_numeric(
        base["participacion_pct"],
        errors="coerce",
    )
    base["monto_miles_soles"] = pd.to_numeric(
        base["monto_miles_soles"],
        errors="coerce",
    )
    base["es_hoja"] = convertir_bool(base["es_hoja"])

    for columna in [
        "nivel_1",
        "nivel_2",
        "nivel_3",
        "descripcion",
        "ruta_jerarquica",
    ]:
        base[columna] = (
            base[columna]
            .fillna("")
            .astype(str)
            .str.strip()
        )

    return base


def seleccionar_componentes(base: pd.DataFrame) -> pd.DataFrame:
    componentes = base[
        base["es_hoja"]
        & base["participacion_pct"].notna()
    ].copy()

    mascara_control = componentes.apply(
        es_total_o_control,
        axis=1,
    )
    componentes = componentes[~mascara_control].copy()

    componentes = componentes[
        ~componentes["descripcion"].str.contains(
            r"^total$",
            case=False,
            regex=True,
            na=False,
        )
    ].copy()

    clasificaciones = componentes.apply(
        clasificar_categoria,
        axis=1,
        result_type="expand",
    )
    clasificaciones.columns = [
        "categoria_economica",
        "factor_representativo_inicial",
        "calidad_proxy_inicial",
    ]

    componentes = pd.concat(
        [
            componentes.reset_index(drop=True),
            clasificaciones.reset_index(drop=True),
        ],
        axis=1,
    )

    return componentes


def agregar_mensual(
    componentes: pd.DataFrame,
) -> pd.DataFrame:
    mensual = (
        componentes.groupby(
            [
                "fecha_cartera",
                "afp",
                "categoria_economica",
                "factor_representativo_inicial",
                "calidad_proxy_inicial",
            ],
            as_index=False,
            dropna=False,
        )
        .agg(
            monto_miles_soles=("monto_miles_soles", "sum"),
            participacion_pct=("participacion_pct", "sum"),
            instrumentos=("descripcion", "nunique"),
        )
    )

    mensual = mensual.sort_values(
        [
            "fecha_cartera",
            "afp",
            "participacion_pct",
        ],
        ascending=[True, True, False],
    )

    return mensual


def crear_control(
    componentes: pd.DataFrame,
) -> pd.DataFrame:
    componentes = componentes.copy()
    componentes["es_no_mapeado"] = (
        componentes["categoria_economica"]
        == "otros_no_mapeados"
    )

    control = (
        componentes.groupby(
            ["fecha_cartera", "afp"],
            as_index=False,
        )
        .agg(
            suma_componentes_pct=("participacion_pct", "sum"),
            participacion_no_mapeada_pct=(
                "participacion_pct",
                lambda s: float(
                    s[
                        componentes.loc[s.index, "es_no_mapeado"]
                    ].sum()
                ),
            ),
            numero_componentes=("descripcion", "size"),
            categorias_economicas=(
                "categoria_economica",
                "nunique",
            ),
        )
    )

    control["desvio_vs_100_pct"] = (
        control["suma_componentes_pct"] - 100.0
    )

    control["estado_suma"] = np.where(
        control["suma_componentes_pct"].between(99.0, 101.0),
        "correcto",
        "revisar",
    )

    control["estado_mapeo"] = np.where(
        control["participacion_no_mapeada_pct"].abs() <= 1.0,
        "correcto",
        "revisar",
    )

    control["estado_general"] = np.where(
        (control["estado_suma"] == "correcto")
        & (control["estado_mapeo"] == "correcto"),
        "correcto",
        "revisar",
    )

    return control


def crear_catalogo(componentes: pd.DataFrame) -> pd.DataFrame:
    catalogo = (
        componentes.groupby(
            [
                "nivel_1",
                "nivel_2",
                "nivel_3",
                "descripcion",
                "ruta_jerarquica",
                "categoria_economica",
                "factor_representativo_inicial",
                "calidad_proxy_inicial",
            ],
            as_index=False,
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
        )
    )

    catalogo = catalogo.sort_values(
        [
            "categoria_economica",
            "participacion_max_abs_pct",
        ],
        ascending=[True, False],
    )

    return catalogo


def main() -> None:
    raiz = Path(__file__).resolve().parents[1]
    processed = raiz / "data" / "processed"

    ruta_base = (
        processed / "fp1356_fondo3_cartera_largo.csv"
    )

    base = preparar_base(ruta_base)
    componentes = seleccionar_componentes(base)
    mensual = agregar_mensual(componentes)
    control = crear_control(componentes)
    catalogo = crear_catalogo(componentes)

    no_mapeados = componentes[
        componentes["categoria_economica"]
        == "otros_no_mapeados"
    ].copy()

    rutas = {
        "detalle": (
            processed / "fp1356_cartera_economica_detalle.csv"
        ),
        "mensual": (
            processed / "fp1356_cartera_economica_mensual.csv"
        ),
        "control": (
            processed / "fp1356_cartera_economica_control.csv"
        ),
        "catalogo": (
            processed / "fp1356_catalogo_mapeo_aplicado.csv"
        ),
        "no_mapeados": (
            processed / "fp1356_cartera_no_mapeada.csv"
        ),
    }

    componentes.to_csv(
        rutas["detalle"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    mensual.to_csv(
        rutas["mensual"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    control.to_csv(
        rutas["control"],
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
    no_mapeados.to_csv(
        rutas["no_mapeados"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )

    ultima_fecha = mensual["fecha_cartera"].max()
    ultimo = mensual[
        mensual["fecha_cartera"] == ultima_fecha
    ].copy()

    print("\nMAPEO ECONÓMICO FP-1356 TERMINADO")
    print("=" * 108)
    print(f"Última fecha: {ultima_fecha.date()}")
    print(f"Componentes terminales válidos: {len(componentes):,}")
    print(
        "Categorías económicas:",
        componentes["categoria_economica"].nunique(),
    )
    print(
        "AFP-mes con control correcto:",
        int((control["estado_general"] == "correcto").sum()),
        "de",
        len(control),
    )
    print(
        "AFP-mes para revisar:",
        int((control["estado_general"] == "revisar").sum()),
    )
    print(
        "Participación no mapeada máxima:",
        f"{control['participacion_no_mapeada_pct'].abs().max():.6f} %",
    )

    print("\nCOMPOSICIÓN ECONÓMICA DEL ÚLTIMO MES")
    print("-" * 108)

    for afp in AFPS:
        tabla = ultimo[
            ultimo["afp"] == afp
        ].sort_values(
            "participacion_pct",
            ascending=False,
        )

        print(f"\n{afp}")
        print(
            tabla[
                [
                    "categoria_economica",
                    "participacion_pct",
                    "factor_representativo_inicial",
                    "calidad_proxy_inicial",
                ]
            ].to_string(index=False)
        )

    if not no_mapeados.empty:
        print("\nDESCRIPCIONES NO MAPEADAS")
        print("-" * 108)
        resumen_no_mapeado = (
            no_mapeados.groupby(
                [
                    "nivel_1",
                    "nivel_2",
                    "descripcion",
                ],
                as_index=False,
            )
            .agg(
                participacion_max_abs_pct=(
                    "participacion_pct",
                    lambda s: float(pd.Series(s).abs().max()),
                ),
                meses=("fecha_cartera", "nunique"),
            )
            .sort_values(
                "participacion_max_abs_pct",
                ascending=False,
            )
        )

        print(
            resumen_no_mapeado.head(30).to_string(index=False)
        )

    print("\nArchivos creados:")
    for ruta in rutas.values():
        print(f" - {ruta.resolve()}")

    print(
        "\nInterpretación:\n"
        "- Se excluyeron Fondo de Pensiones y Encaje Legal porque son "
        "filas de control/total y no instrumentos subyacentes.\n"
        "- Las categorías mensuales deben sumar aproximadamente 100 % "
        "por AFP, incluyendo operaciones en tránsito.\n"
        "- Los factores propuestos son proxies iniciales; no son todavía "
        "una atribución definitiva.\n"
        "- La categoría fondos_mutuos_exterior sigue siendo demasiado "
        "amplia. Para conocer sectores o emisores específicos será "
        "necesario incorporar la composición específica CA-0001.\n"
        "- El siguiente modelo probará si los pesos mensuales reales "
        "mejoran el desempeño fuera de muestra frente al modelo sin pesos."
    )


if __name__ == "__main__":
    main()
