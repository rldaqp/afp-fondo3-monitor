from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd


AFPS = ["Habitat", "Integra", "Prima", "Profuturo"]
TOLERANCIA_RELATIVA = 1e-7
TOLERANCIA_ABSOLUTA = 1e-4

TERMINOS_INSTRUMENTO = [
    "accion",
    "acciones",
    "bono",
    "bonos",
    "fondo",
    "fondos",
    "deposito",
    "depositos",
    "certificado",
    "certificados",
    "titulo",
    "titulos",
    "papel comercial",
    "papeles comerciales",
    "cuenta corriente",
    "cuentas corrientes",
    "etf",
    "instrumento",
    "instrumentos",
    "cuota",
    "cuotas",
    "letra",
    "letras",
    "valor representativo",
    "valores representativos",
    "forward",
    "futuro",
    "opcion",
    "swap",
]

NOMBRES_CONTROL = {
    "total",
    "total general",
    "sistema",
    "nacional",
    "extranjero",
    "i. nacional",
    "ii. extranjero",
    "i. inversiones locales",
    "ii. inversiones en el exterior",
}


def normalizar(valor: object) -> str:
    if pd.isna(valor):
        return ""
    return re.sub(r"\s+", " ", str(valor)).strip()


def clave(valor: object) -> str:
    texto = normalizar(valor).lower()
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(
        caracter
        for caracter in texto
        if not unicodedata.combining(caracter)
    )
    return re.sub(r"\s+", " ", texto).strip()


def valor_igual(a: object, b: object) -> bool:
    a_num = pd.to_numeric(pd.Series([a]), errors="coerce").iloc[0]
    b_num = pd.to_numeric(pd.Series([b]), errors="coerce").iloc[0]

    if pd.isna(a_num) or pd.isna(b_num):
        return False

    return bool(
        np.isclose(
            float(a_num),
            float(b_num),
            rtol=TOLERANCIA_RELATIVA,
            atol=TOLERANCIA_ABSOLUTA,
        )
    )


def parece_instrumento_o_categoria(nombre: str) -> bool:
    texto = clave(nombre)

    if not texto or texto in NOMBRES_CONTROL:
        return False

    if any(termino in texto for termino in TERMINOS_INSTRUMENTO):
        return True

    # Las categorías de la SBS suelen estar completamente en mayúsculas.
    original = normalizar(nombre)
    letras = [c for c in original if c.isalpha()]

    return bool(
        letras
        and original.upper() == original
        and len(original) >= 8
    )


def parece_entidad_o_fondo(nombre: str) -> bool:
    texto = clave(nombre)

    if not texto or texto in NOMBRES_CONTROL:
        return False

    indicadores = [
        "l.p.",
        "lp",
        "fund",
        "fondo",
        "partners",
        "capital",
        "asset",
        "management",
        "advisors",
        "investors",
        "company",
        "corporation",
        "inc.",
        "limited",
        "ltd",
        "plc",
        "sicav",
        "trust",
        "feeder",
        "partnership",
    ]

    return any(indicador in texto for indicador in indicadores)


def preparar_hoja3(ruta: Path) -> pd.DataFrame:
    if not ruta.exists():
        raise FileNotFoundError(f"No existe: {ruta}")

    df = pd.read_csv(ruta, parse_dates=["fecha_cartera"])
    df["valor"] = pd.to_numeric(df["valor"], errors="coerce")
    df["fila_excel_aprox"] = pd.to_numeric(
        df["fila_excel_aprox"],
        errors="coerce",
    )

    for columna in [
        "identificador_especifico",
        "categoria_instrumento",
        "estado_pareja",
        "moneda",
    ]:
        if columna not in df.columns:
            df[columna] = ""
        df[columna] = df[columna].fillna("").astype(str).str.strip()

    return df.sort_values(
        ["fecha_cartera", "archivo", "afp", "fila_excel_aprox"]
    ).reset_index(drop=True)


def refinar_hoja3(
    df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    salidas = []
    controles = []

    claves_grupo = [
        "fecha_cartera",
        "archivo",
        "afp",
    ]

    for claves, grupo in df.groupby(claves_grupo, sort=True):
        grupo = grupo.sort_values("fila_excel_aprox").reset_index(drop=True)
        usados: set[int] = set()

        for i in range(len(grupo)):
            if i in usados:
                continue

            fila = grupo.iloc[i].copy()
            identificador = fila["identificador_especifico"]
            categoria = fila["categoria_instrumento"]
            estado = fila["estado_pareja"]

            if (
                estado == "pareja_exacta"
                and categoria
            ):
                fila["estado_refinado"] = "pareja_exacta_original"
                fila["fila_categoria_origen"] = np.nan
                salidas.append(fila.to_dict())
                continue

            emparejada = False

            if i + 1 < len(grupo):
                siguiente = grupo.iloc[i + 1]

                adyacente = (
                    int(siguiente["fila_excel_aprox"])
                    == int(fila["fila_excel_aprox"]) + 1
                )
                mismo_valor = valor_igual(
                    fila["valor"],
                    siguiente["valor"],
                )
                segundo_es_categoria = parece_instrumento_o_categoria(
                    siguiente["identificador_especifico"]
                )

                if (
                    adyacente
                    and mismo_valor
                    and segundo_es_categoria
                ):
                    fila["categoria_instrumento"] = (
                        siguiente["identificador_especifico"]
                    )
                    fila["estado_refinado"] = (
                        "pareja_exacta_heuristica"
                    )
                    fila["fila_categoria_origen"] = (
                        siguiente["fila_excel_aprox"]
                    )
                    salidas.append(fila.to_dict())
                    usados.add(i + 1)
                    emparejada = True

                    controles.append(
                        {
                            "fuente": "hoja_3",
                            "fecha_cartera": claves[0],
                            "archivo": claves[1],
                            "afp": claves[2],
                            "fila_principal": fila["fila_excel_aprox"],
                            "fila_secundaria": (
                                siguiente["fila_excel_aprox"]
                            ),
                            "identificador": identificador,
                            "categoria_asignada": (
                                siguiente[
                                    "identificador_especifico"
                                ]
                            ),
                            "valor": fila["valor"],
                            "accion": "fusion_adyacente_exacta",
                        }
                    )

            if emparejada:
                continue

            fila["estado_refinado"] = (
                "pendiente_sin_categoria"
                if not categoria
                else "categoria_existente_no_exacta"
            )
            fila["fila_categoria_origen"] = np.nan
            salidas.append(fila.to_dict())

    refinado = pd.DataFrame(salidas)
    control = pd.DataFrame(controles)

    return refinado, control


def preparar_hoja10(ruta: Path) -> pd.DataFrame:
    if not ruta.exists():
        raise FileNotFoundError(f"No existe: {ruta}")

    df = pd.read_csv(ruta, parse_dates=["fecha_cartera"])
    df["valor"] = pd.to_numeric(df["valor"], errors="coerce")
    df["fila_excel_aprox"] = pd.to_numeric(
        df["fila_excel_aprox"],
        errors="coerce",
    )

    for columna in [
        "entidad_administradora",
        "isin",
        "moneda",
        "estado_identificacion",
        "seccion",
    ]:
        if columna not in df.columns:
            df[columna] = ""
        df[columna] = df[columna].fillna("").astype(str).str.strip()

    return df.sort_values(
        ["fecha_cartera", "archivo", "afp", "fila_excel_aprox"]
    ).reset_index(drop=True)


def refinar_hoja10(
    df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    salidas = []
    controles = []

    claves_grupo = [
        "fecha_cartera",
        "archivo",
        "afp",
    ]

    for claves, grupo in df.groupby(claves_grupo, sort=True):
        grupo = grupo.sort_values("fila_excel_aprox").reset_index(drop=True)
        usados: set[int] = set()

        for i in range(len(grupo)):
            if i in usados:
                continue

            fila = grupo.iloc[i].copy()

            if fila["isin"]:
                fila["instrumento_sin_isin"] = ""
                fila["estado_refinado"] = "isin"
                salidas.append(fila.to_dict())
                continue

            emparejada = False

            if i + 1 < len(grupo):
                siguiente = grupo.iloc[i + 1]

                adyacente = (
                    int(siguiente["fila_excel_aprox"])
                    == int(fila["fila_excel_aprox"]) + 1
                )
                mismo_valor = valor_igual(
                    fila["valor"],
                    siguiente["valor"],
                )
                ambas_sin_isin = (
                    not fila["isin"]
                    and not siguiente["isin"]
                )

                nombre_primero = fila["entidad_administradora"]
                nombre_segundo = (
                    siguiente["entidad_administradora"]
                )

                segundo_parece_fondo = parece_entidad_o_fondo(
                    nombre_segundo
                )

                if (
                    adyacente
                    and mismo_valor
                    and ambas_sin_isin
                    and segundo_parece_fondo
                    and nombre_primero != nombre_segundo
                ):
                    fila["instrumento_sin_isin"] = nombre_segundo
                    fila["moneda"] = (
                        siguiente["moneda"]
                        or fila["moneda"]
                    )
                    fila["estado_refinado"] = (
                        "fondo_sin_isin_pareja_exacta"
                    )
                    fila["fila_instrumento_origen"] = (
                        siguiente["fila_excel_aprox"]
                    )
                    salidas.append(fila.to_dict())
                    usados.add(i + 1)
                    emparejada = True

                    controles.append(
                        {
                            "fuente": "hoja_10",
                            "fecha_cartera": claves[0],
                            "archivo": claves[1],
                            "afp": claves[2],
                            "fila_administradora": (
                                fila["fila_excel_aprox"]
                            ),
                            "fila_instrumento": (
                                siguiente["fila_excel_aprox"]
                            ),
                            "administradora": nombre_primero,
                            "instrumento_sin_isin": nombre_segundo,
                            "valor": fila["valor"],
                            "accion": (
                                "fusion_administradora_fondo_sin_isin"
                            ),
                        }
                    )

            if emparejada:
                continue

            fila["instrumento_sin_isin"] = ""
            fila["estado_refinado"] = (
                "entidad_sin_isin_pendiente"
            )
            fila["fila_instrumento_origen"] = np.nan
            salidas.append(fila.to_dict())

    refinado = pd.DataFrame(salidas)
    control = pd.DataFrame(controles)

    return refinado, control


def agregar_participacion(
    df: pd.DataFrame,
    nombre_grupo: str,
) -> pd.DataFrame:
    if df.empty:
        return df

    salida = df.copy()

    totales = (
        salida.groupby(
            ["fecha_cartera", "archivo", "afp"],
            as_index=False,
        )["valor"]
        .sum()
        .rename(columns={"valor": "total_refinado"})
    )

    salida = salida.merge(
        totales,
        on=["fecha_cartera", "archivo", "afp"],
        how="left",
        validate="many_to_one",
    )

    salida[f"participacion_{nombre_grupo}_pct"] = np.where(
        salida["total_refinado"].abs() > TOLERANCIA_ABSOLUTA,
        salida["valor"] / salida["total_refinado"] * 100.0,
        np.nan,
    )

    return salida


def pendientes_hoja3(df: pd.DataFrame) -> pd.DataFrame:
    pendientes = df[
        df["estado_refinado"] == "pendiente_sin_categoria"
    ].copy()

    if pendientes.empty:
        return pendientes

    pendientes["motivo"] = "sin_categoria_identificada"
    pendientes["fuente"] = "hoja_3"
    return pendientes


def pendientes_hoja10(df: pd.DataFrame) -> pd.DataFrame:
    pendientes = df[
        df["estado_refinado"] == "entidad_sin_isin_pendiente"
    ].copy()

    if pendientes.empty:
        return pendientes

    pendientes["motivo"] = "sin_isin_y_sin_pareja_de_fondo"
    pendientes["fuente"] = "hoja_10"
    return pendientes


def top_refinado(
    hoja3: pd.DataFrame,
    hoja10: pd.DataFrame,
) -> pd.DataFrame:
    partes = []

    if not hoja3.empty:
        h3 = hoja3.copy()
        h3["fuente_detalle"] = "hoja_3"
        h3["identificador_final"] = h3[
            "identificador_especifico"
        ]
        h3["categoria_final"] = h3[
            "categoria_instrumento"
        ]
        partes.append(h3)

    if not hoja10.empty:
        h10 = hoja10.copy()
        h10["fuente_detalle"] = "hoja_10"
        h10["identificador_final"] = np.where(
            h10["isin"].astype(str).str.len() > 0,
            h10["isin"],
            np.where(
                h10["instrumento_sin_isin"].astype(str).str.len() > 0,
                h10["instrumento_sin_isin"],
                h10["entidad_administradora"],
            ),
        )
        h10["categoria_final"] = h10[
            "entidad_administradora"
        ]
        partes.append(h10)

    if not partes:
        return pd.DataFrame()

    top = pd.concat(partes, ignore_index=True, sort=False)
    top["valor_abs"] = top["valor"].abs()

    top = top.sort_values(
        ["fuente_detalle", "afp", "valor_abs"],
        ascending=[True, True, False],
    )
    top["ranking"] = (
        top.groupby(["fuente_detalle", "afp"])
        .cumcount()
        .add(1)
    )

    return top[top["ranking"] <= 20].copy()


def main() -> None:
    raiz = Path(__file__).resolve().parents[1]
    processed = raiz / "data" / "processed"

    ruta_h3 = (
        processed
        / "ca0001_fondo3_hoja3_emisores_canonicos.csv"
    )
    ruta_h10 = (
        processed
        / "ca0001_fondo3_hoja10_isin_canonicos.csv"
    )

    hoja3 = preparar_hoja3(ruta_h3)
    hoja10 = preparar_hoja10(ruta_h10)

    hoja3_ref, control3 = refinar_hoja3(hoja3)
    hoja10_ref, control10 = refinar_hoja10(hoja10)

    hoja3_ref = agregar_participacion(
        hoja3_ref,
        "hoja3_refinada",
    )
    hoja10_ref = agregar_participacion(
        hoja10_ref,
        "hoja10_refinada",
    )

    pendientes3 = pendientes_hoja3(hoja3_ref)
    pendientes10 = pendientes_hoja10(hoja10_ref)

    pendientes = pd.concat(
        [pendientes3, pendientes10],
        ignore_index=True,
        sort=False,
    )

    controles_fusion = pd.concat(
        [control3, control10],
        ignore_index=True,
        sort=False,
    )

    resumen = pd.DataFrame(
        [
            {
                "fuente": "hoja_3",
                "registros_entrada": len(hoja3),
                "registros_salida": len(hoja3_ref),
                "fusiones_nuevas": len(control3),
                "parejas_exactas_originales": int(
                    (
                        hoja3_ref["estado_refinado"]
                        == "pareja_exacta_original"
                    ).sum()
                ),
                "parejas_exactas_heuristicas": int(
                    (
                        hoja3_ref["estado_refinado"]
                        == "pareja_exacta_heuristica"
                    ).sum()
                ),
                "pendientes": int(
                    (
                        hoja3_ref["estado_refinado"]
                        == "pendiente_sin_categoria"
                    ).sum()
                ),
            },
            {
                "fuente": "hoja_10",
                "registros_entrada": len(hoja10),
                "registros_salida": len(hoja10_ref),
                "fusiones_nuevas": len(control10),
                "parejas_exactas_originales": int(
                    (
                        hoja10_ref["estado_refinado"]
                        == "isin"
                    ).sum()
                ),
                "parejas_exactas_heuristicas": int(
                    (
                        hoja10_ref["estado_refinado"]
                        == "fondo_sin_isin_pareja_exacta"
                    ).sum()
                ),
                "pendientes": int(
                    (
                        hoja10_ref["estado_refinado"]
                        == "entidad_sin_isin_pendiente"
                    ).sum()
                ),
            },
        ]
    )

    top = top_refinado(
        hoja3_ref,
        hoja10_ref,
    )

    rutas = {
        "hoja3": (
            processed
            / "ca0001_fondo3_hoja3_refinada.csv"
        ),
        "hoja10": (
            processed
            / "ca0001_fondo3_hoja10_refinada.csv"
        ),
        "fusiones": (
            processed
            / "ca0001_fondo3_refinamiento_fusiones.csv"
        ),
        "pendientes": (
            processed
            / "ca0001_fondo3_refinamiento_pendientes.csv"
        ),
        "resumen": (
            processed
            / "ca0001_fondo3_refinamiento_resumen.csv"
        ),
        "top": (
            processed
            / "ca0001_fondo3_top_refinado.csv"
        ),
    }

    hoja3_ref.to_csv(
        rutas["hoja3"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    hoja10_ref.to_csv(
        rutas["hoja10"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    controles_fusion.to_csv(
        rutas["fusiones"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    pendientes.to_csv(
        rutas["pendientes"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    resumen.to_csv(
        rutas["resumen"],
        index=False,
        encoding="utf-8-sig",
    )
    top.to_csv(
        rutas["top"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )

    print("\nREFINAMIENTO FINAL DEL PILOTO CA-0001")
    print("=" * 108)
    print(resumen.to_string(index=False))

    print("\nESTADOS FINALES — HOJA 3")
    print("-" * 108)
    print(
        hoja3_ref["estado_refinado"]
        .value_counts(dropna=False)
        .rename_axis("estado")
        .reset_index(name="registros")
        .to_string(index=False)
    )

    print("\nESTADOS FINALES — HOJA 10")
    print("-" * 108)
    print(
        hoja10_ref["estado_refinado"]
        .value_counts(dropna=False)
        .rename_axis("estado")
        .reset_index(name="registros")
        .to_string(index=False)
    )

    if not pendientes.empty:
        print("\nPRINCIPALES PENDIENTES")
        print("-" * 108)

        columnas = [
            columna
            for columna in [
                "fuente",
                "afp",
                "fila_excel_aprox",
                "identificador_especifico",
                "entidad_administradora",
                "valor",
                "motivo",
            ]
            if columna in pendientes.columns
        ]

        print(
            pendientes.sort_values(
                "valor",
                ascending=False,
            )[columnas].head(30).to_string(index=False)
        )

    print("\nTOP REFINADO DE EXPOSICIONES")
    print("-" * 108)

    for fuente in sorted(top["fuente_detalle"].unique()):
        for afp in AFPS:
            tabla = top[
                (top["fuente_detalle"] == fuente)
                & (top["afp"] == afp)
            ].head(10)

            if tabla.empty:
                continue

            print(f"\n{fuente} — {afp}")
            print(
                tabla[
                    [
                        "ranking",
                        "identificador_final",
                        "categoria_final",
                        "valor",
                        "estado_refinado",
                    ]
                ].to_string(index=False)
            )

    print("\nArchivos creados:")
    for ruta in rutas.values():
        print(f" - {ruta.resolve()}")

    print(
        "\nCriterio para pasar al histórico:\n"
        "- La hoja 3 debe quedar con pocos pendientes materiales y sin "
        "pares adyacentes repetidos dentro del top de exposición.\n"
        "- La hoja 10 debe fusionar los pares administradora–fondo sin ISIN "
        "y conservar por separado los ISIN verdaderos.\n"
        "- Los pendientes no se eliminan: se mantienen con bandera para "
        "revisión y no deben sumarse automáticamente con otra fila igual.\n"
        "- Si el resultado es estable, el siguiente módulo aplicará estas "
        "reglas a los 133 meses y generará controles por archivo, hoja y AFP."
    )


if __name__ == "__main__":
    main()
