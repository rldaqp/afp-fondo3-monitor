from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import requests


AFPS = ["Habitat", "Integra", "Prima", "Profuturo"]

TIMEOUT_DESCARGA = 180
REINTENTOS = 3


def cargar_modulo(nombre: str, ruta: Path):
    if not ruta.exists():
        raise FileNotFoundError(
            f"No existe {ruta}. Guarda primero los módulos 26 y 27 "
            "dentro de la carpeta src."
        )

    spec = importlib.util.spec_from_file_location(nombre, ruta)
    if spec is None or spec.loader is None:
        raise ImportError(f"No se pudo cargar el módulo: {ruta}")

    modulo = importlib.util.module_from_spec(spec)
    sys.modules[nombre] = modulo
    spec.loader.exec_module(modulo)
    return modulo


def crear_sesion() -> requests.Session:
    sesion = requests.Session()
    sesion.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/149 Safari/537.36"
            )
        }
    )
    return sesion


def descargar_archivo(
    sesion: requests.Session,
    url: str,
    destino: Path,
    pagina_referencia: str,
) -> tuple[Path, str]:
    destino.parent.mkdir(parents=True, exist_ok=True)

    if destino.exists() and destino.stat().st_size > 1_000:
        return destino, "reutilizado"

    ultimo_error = None

    for intento in range(1, REINTENTOS + 1):
        try:
            respuesta = sesion.get(
                url,
                timeout=TIMEOUT_DESCARGA,
                allow_redirects=True,
                headers={"Referer": pagina_referencia},
            )
            respuesta.raise_for_status()

            contenido = respuesta.content

            if len(contenido) < 1_000:
                raise RuntimeError(
                    f"Archivo demasiado pequeño: {len(contenido)} bytes."
                )

            inicio = contenido[:500].lower()
            if b"<html" in inicio or b"<!doctype html" in inicio:
                raise RuntimeError(
                    "La respuesta contiene HTML y no un archivo Excel."
                )

            destino.write_bytes(contenido)
            return destino, f"descargado_intento_{intento}"

        except Exception as error:
            ultimo_error = error

    raise RuntimeError(
        f"No se pudo descargar después de {REINTENTOS} intentos: "
        f"{ultimo_error}"
    )


def preparar_inventario(ruta: Path) -> pd.DataFrame:
    if not ruta.exists():
        raise FileNotFoundError(
            "No existe ca0001_inventario_enlaces.csv. "
            "Ejecuta primero el módulo 23."
        )

    inventario = pd.read_csv(ruta)

    requeridas = {"anio", "mes", "url", "archivo"}
    faltantes = requeridas - set(inventario.columns)

    if faltantes:
        raise ValueError(
            f"Faltan columnas en el inventario: {sorted(faltantes)}"
        )

    inventario["anio"] = pd.to_numeric(
        inventario["anio"],
        errors="coerce",
    ).astype("Int64")
    inventario["mes"] = pd.to_numeric(
        inventario["mes"],
        errors="coerce",
    ).astype("Int64")

    inventario = inventario.dropna(
        subset=["anio", "mes", "url", "archivo"]
    ).copy()

    inventario["anio"] = inventario["anio"].astype(int)
    inventario["mes"] = inventario["mes"].astype(int)

    inventario = (
        inventario.sort_values(["anio", "mes", "archivo"])
        .drop_duplicates(subset=["url"], keep="last")
        .reset_index(drop=True)
    )

    return inventario


def normalizar_participacion(
    serie: pd.Series,
) -> pd.Series:
    valores = pd.to_numeric(serie, errors="coerce")

    return np.where(
        valores.abs() <= 2.0,
        valores * 100.0,
        valores,
    )


def procesar_hoja3(
    archivo: Path,
    anio: int,
    mes: int,
    m26,
    m27,
) -> tuple[pd.DataFrame, dict, pd.DataFrame]:
    base, control_base = m26.crear_filas_base(
        archivo,
        "3",
        anio,
        mes,
    )
    canonico, incidencias = m26.depurar_hoja3(base)

    largo = m26.a_largo(
        canonico,
        [
            "identificador_especifico",
            "categoria_instrumento",
            "estado_pareja",
            "moneda",
        ],
        "miles_soles",
    )

    refinado, fusiones = m27.refinar_hoja3(largo)
    refinado = m27.agregar_participacion(
        refinado,
        "hoja3_refinada",
    )

    if "participacion_reportada" in refinado.columns:
        refinado["participacion_reportada_pct"] = (
            normalizar_participacion(
                refinado["participacion_reportada"]
            )
        )

    control = {
        **control_base,
        "filas_canonicas": len(canonico),
        "registros_largos": len(largo),
        "registros_refinados": len(refinado),
        "parejas_exactas_originales": int(
            (
                refinado["estado_refinado"]
                == "pareja_exacta_original"
            ).sum()
        ),
        "parejas_exactas_heuristicas": int(
            (
                refinado["estado_refinado"]
                == "pareja_exacta_heuristica"
            ).sum()
        ),
        "pendientes": int(
            (
                refinado["estado_refinado"]
                == "pendiente_sin_categoria"
            ).sum()
        ),
        "fusiones_nuevas": len(fusiones),
        "incidencias_iniciales": len(incidencias),
        "estado_proceso": "correcto",
        "error": "",
    }

    return refinado, control, fusiones


def procesar_hoja10(
    archivo: Path,
    anio: int,
    mes: int,
    m26,
    m27,
) -> tuple[pd.DataFrame, dict, pd.DataFrame, pd.DataFrame]:
    base, control_base = m26.crear_filas_base(
        archivo,
        "10",
        anio,
        mes,
    )
    canonico, grupos = m26.depurar_hoja10(base)

    largo = m26.a_largo(
        canonico,
        [
            "grupo",
            "entidad_administradora",
            "isin",
            "moneda",
            "seccion",
            "estado_identificacion",
        ],
        "miles_soles",
    )

    refinado, fusiones = m27.refinar_hoja10(largo)
    refinado = m27.agregar_participacion(
        refinado,
        "hoja10_refinada",
    )

    if "participacion_reportada" in refinado.columns:
        refinado["participacion_reportada_pct"] = (
            normalizar_participacion(
                refinado["participacion_reportada"]
            )
        )

    control = {
        **control_base,
        "filas_canonicas": len(canonico),
        "registros_largos": len(largo),
        "registros_refinados": len(refinado),
        "grupos_reconciliados": int(
            (grupos["estado"] == "reconciliado").sum()
        )
        if not grupos.empty
        else 0,
        "grupos_sin_isin": int(
            (grupos["estado"] == "sin_isin").sum()
        )
        if not grupos.empty
        else 0,
        "grupos_revisar": int(
            (grupos["estado"] == "revisar").sum()
        )
        if not grupos.empty
        else 0,
        "registros_isin": int(
            (refinado["estado_refinado"] == "isin").sum()
        ),
        "fondos_sin_isin_pareja": int(
            (
                refinado["estado_refinado"]
                == "fondo_sin_isin_pareja_exacta"
            ).sum()
        ),
        "pendientes": int(
            (
                refinado["estado_refinado"]
                == "entidad_sin_isin_pendiente"
            ).sum()
        ),
        "fusiones_nuevas": len(fusiones),
        "estado_proceso": "correcto",
        "error": "",
    }

    return refinado, control, grupos, fusiones


def procesar_hoja9(
    archivo: Path,
    anio: int,
    mes: int,
    m26,
) -> tuple[pd.DataFrame, dict]:
    base, control_base = m26.crear_filas_base(
        archivo,
        "9",
        anio,
        mes,
    )
    canonico = m26.depurar_hoja9(base)

    largo = m26.a_largo(
        canonico,
        [
            "administrador",
            "fondo_local",
        ],
        "unidades",
    )

    control = {
        **control_base,
        "filas_canonicas": len(canonico),
        "registros_largos": len(largo),
        "estado_proceso": "correcto",
        "error": "",
    }

    return largo, control


def crear_catalogo_hoja3(
    df: pd.DataFrame,
) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()

    return (
        df.groupby(
            [
                "afp",
                "identificador_especifico",
                "categoria_instrumento",
                "estado_refinado",
            ],
            dropna=False,
            as_index=False,
        )
        .agg(
            primera_fecha=("fecha_cartera", "min"),
            ultima_fecha=("fecha_cartera", "max"),
            meses_presentes=("fecha_cartera", "nunique"),
            valor_mediano_miles_soles=("valor", "median"),
            valor_maximo_miles_soles=("valor", "max"),
            observaciones=("valor", "size"),
        )
        .sort_values(
            [
                "afp",
                "valor_maximo_miles_soles",
            ],
            ascending=[True, False],
        )
    )


def crear_catalogo_hoja10(
    df: pd.DataFrame,
) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()

    salida = df.copy()
    salida["identificador_final"] = np.where(
        salida["isin"].fillna("").astype(str).str.len() > 0,
        salida["isin"],
        np.where(
            salida["instrumento_sin_isin"]
            .fillna("")
            .astype(str)
            .str.len()
            > 0,
            salida["instrumento_sin_isin"],
            salida["entidad_administradora"],
        ),
    )

    return (
        salida.groupby(
            [
                "afp",
                "identificador_final",
                "isin",
                "entidad_administradora",
                "moneda",
                "estado_refinado",
            ],
            dropna=False,
            as_index=False,
        )
        .agg(
            primera_fecha=("fecha_cartera", "min"),
            ultima_fecha=("fecha_cartera", "max"),
            meses_presentes=("fecha_cartera", "nunique"),
            valor_mediano_miles_soles=("valor", "median"),
            valor_maximo_miles_soles=("valor", "max"),
            observaciones=("valor", "size"),
        )
        .sort_values(
            [
                "afp",
                "valor_maximo_miles_soles",
            ],
            ascending=[True, False],
        )
    )


def crear_top_ultimo_mes(
    hoja3: pd.DataFrame,
    hoja10: pd.DataFrame,
) -> pd.DataFrame:
    partes = []

    if not hoja3.empty:
        ultima3 = hoja3["fecha_cartera"].max()
        h3 = hoja3[
            hoja3["fecha_cartera"] == ultima3
        ].copy()
        h3["fuente_detalle"] = "hoja_3"
        h3["identificador_final"] = h3[
            "identificador_especifico"
        ]
        h3["categoria_final"] = h3[
            "categoria_instrumento"
        ]
        partes.append(h3)

    if not hoja10.empty:
        ultima10 = hoja10["fecha_cartera"].max()
        h10 = hoja10[
            hoja10["fecha_cartera"] == ultima10
        ].copy()
        h10["fuente_detalle"] = "hoja_10"
        h10["identificador_final"] = np.where(
            h10["isin"].fillna("").astype(str).str.len() > 0,
            h10["isin"],
            np.where(
                h10["instrumento_sin_isin"]
                .fillna("")
                .astype(str)
                .str.len()
                > 0,
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

    top = pd.concat(
        partes,
        ignore_index=True,
        sort=False,
    )
    top["valor_abs"] = top["valor"].abs()

    top = top.sort_values(
        [
            "fuente_detalle",
            "afp",
            "valor_abs",
        ],
        ascending=[True, True, False],
    )
    top["ranking"] = (
        top.groupby(
            ["fuente_detalle", "afp"]
        )
        .cumcount()
        .add(1)
    )

    return top[top["ranking"] <= 20].copy()


def main() -> None:
    raiz = Path(__file__).resolve().parents[1]
    src = raiz / "src"
    raw = raiz / "data" / "raw" / "sbs" / "ca0001_composicion"
    processed = raiz / "data" / "processed"
    processed.mkdir(parents=True, exist_ok=True)

    m26 = cargar_modulo(
        "modulo26_ca0001",
        src / "26_depuracion_canonica_ca0001.py",
    )
    m27 = cargar_modulo(
        "modulo27_ca0001",
        src / "27_refinar_duplicaciones_ca0001.py",
    )

    inventario = preparar_inventario(
        processed / "ca0001_inventario_enlaces.csv"
    )

    sesion = crear_sesion()
    pagina_referencia = (
        "https://www.sbs.gob.pe/app/stats_net/stats/"
        "EstadisticaSistemaFinancieroResultados.aspx?c=CA-0001"
    )

    bases_hoja3 = []
    bases_hoja10 = []
    bases_hoja9 = []

    controles_archivos = []
    controles_hojas = []
    errores = []
    grupos_hoja10 = []
    fusiones_total = []

    print("\nCONSOLIDACIÓN HISTÓRICA CA-0001 — FONDO 3")
    print("=" * 112)
    print(f"Archivos del inventario: {len(inventario)}")

    for numero, fila in enumerate(
        inventario.itertuples(index=False),
        start=1,
    ):
        destino = raw / str(fila.archivo)

        print(
            f"\n[{numero:03d}/{len(inventario):03d}] "
            f"{fila.anio}-{fila.mes:02d} {fila.archivo}"
        )

        control_archivo = {
            "anio": fila.anio,
            "mes": fila.mes,
            "archivo": fila.archivo,
            "url": fila.url,
            "estado_descarga": "",
            "hojas_disponibles": "",
            "hoja3_estado": "no_procesada",
            "hoja9_estado": "no_procesada",
            "hoja10_estado": "no_procesada",
            "estado_general": "revisar",
            "error_general": "",
        }

        try:
            archivo, estado_descarga = descargar_archivo(
                sesion,
                str(fila.url),
                destino,
                pagina_referencia,
            )
            control_archivo["estado_descarga"] = estado_descarga

            fuente, motor = m26.preparar_excel(archivo)
            libro = pd.ExcelFile(fuente, engine=motor)
            hojas = [str(x) for x in libro.sheet_names]
            control_archivo["hojas_disponibles"] = " | ".join(hojas)

            for hoja in ["3", "9", "10"]:
                if hoja not in hojas:
                    controles_hojas.append(
                        {
                            "anio": fila.anio,
                            "mes": fila.mes,
                            "archivo": fila.archivo,
                            "hoja": hoja,
                            "estado_proceso": "hoja_ausente",
                            "error": "",
                        }
                    )
                    control_archivo[f"hoja{hoja}_estado"] = (
                        "hoja_ausente"
                    )
                    continue

                try:
                    if hoja == "3":
                        base, control, fusiones = procesar_hoja3(
                            archivo,
                            fila.anio,
                            fila.mes,
                            m26,
                            m27,
                        )
                        bases_hoja3.append(base)
                        fusiones["hoja"] = "3"
                        fusiones_total.append(fusiones)

                    elif hoja == "10":
                        (
                            base,
                            control,
                            grupos,
                            fusiones,
                        ) = procesar_hoja10(
                            archivo,
                            fila.anio,
                            fila.mes,
                            m26,
                            m27,
                        )
                        bases_hoja10.append(base)
                        grupos["archivo"] = fila.archivo
                        grupos["fecha_cartera"] = (
                            base["fecha_cartera"].iloc[0]
                            if not base.empty
                            else pd.NaT
                        )
                        grupos_hoja10.append(grupos)
                        fusiones["hoja"] = "10"
                        fusiones_total.append(fusiones)

                    else:
                        base, control = procesar_hoja9(
                            archivo,
                            fila.anio,
                            fila.mes,
                            m26,
                        )
                        bases_hoja9.append(base)

                    controles_hojas.append(
                        {
                            "anio": fila.anio,
                            "mes": fila.mes,
                            **control,
                        }
                    )
                    control_archivo[f"hoja{hoja}_estado"] = (
                        "correcto"
                    )

                    print(
                        f"  Hoja {hoja}: correcto | "
                        f"registros={len(base):,}"
                    )

                except Exception as error_hoja:
                    mensaje = str(error_hoja)
                    controles_hojas.append(
                        {
                            "anio": fila.anio,
                            "mes": fila.mes,
                            "archivo": fila.archivo,
                            "hoja": hoja,
                            "estado_proceso": "error",
                            "error": mensaje,
                        }
                    )
                    errores.append(
                        {
                            "anio": fila.anio,
                            "mes": fila.mes,
                            "archivo": fila.archivo,
                            "hoja": hoja,
                            "etapa": "procesamiento_hoja",
                            "error": mensaje,
                        }
                    )
                    control_archivo[f"hoja{hoja}_estado"] = "error"
                    print(f"  Hoja {hoja}: ERROR — {mensaje}")

            estados = [
                control_archivo["hoja3_estado"],
                control_archivo["hoja9_estado"],
                control_archivo["hoja10_estado"],
            ]

            control_archivo["estado_general"] = (
                "correcto"
                if "correcto" in estados and "error" not in estados
                else "revisar"
            )

        except Exception as error_archivo:
            mensaje = str(error_archivo)
            control_archivo["estado_general"] = "error"
            control_archivo["error_general"] = mensaje

            errores.append(
                {
                    "anio": fila.anio,
                    "mes": fila.mes,
                    "archivo": fila.archivo,
                    "hoja": "",
                    "etapa": "descarga_o_apertura",
                    "error": mensaje,
                }
            )
            print(f"  ERROR GENERAL — {mensaje}")

        controles_archivos.append(control_archivo)

    hoja3_df = (
        pd.concat(
            bases_hoja3,
            ignore_index=True,
            sort=False,
        )
        if bases_hoja3
        else pd.DataFrame()
    )
    hoja10_df = (
        pd.concat(
            bases_hoja10,
            ignore_index=True,
            sort=False,
        )
        if bases_hoja10
        else pd.DataFrame()
    )
    hoja9_df = (
        pd.concat(
            bases_hoja9,
            ignore_index=True,
            sort=False,
        )
        if bases_hoja9
        else pd.DataFrame()
    )
    grupos10_df = (
        pd.concat(
            grupos_hoja10,
            ignore_index=True,
            sort=False,
        )
        if grupos_hoja10
        else pd.DataFrame()
    )
    fusiones_df = (
        pd.concat(
            fusiones_total,
            ignore_index=True,
            sort=False,
        )
        if fusiones_total
        else pd.DataFrame()
    )

    control_archivos_df = pd.DataFrame(controles_archivos)
    control_hojas_df = pd.DataFrame(controles_hojas)
    errores_df = pd.DataFrame(errores)

    catalogo3 = crear_catalogo_hoja3(hoja3_df)
    catalogo10 = crear_catalogo_hoja10(hoja10_df)
    top_ultimo = crear_top_ultimo_mes(
        hoja3_df,
        hoja10_df,
    )

    rutas = {
        "hoja3": (
            processed
            / "ca0001_fondo3_historico_hoja3_refinada.csv"
        ),
        "hoja10": (
            processed
            / "ca0001_fondo3_historico_hoja10_refinada.csv"
        ),
        "hoja9": (
            processed
            / "ca0001_fondo3_historico_hoja9_unidades.csv"
        ),
        "control_archivos": (
            processed
            / "ca0001_fondo3_historico_control_archivos.csv"
        ),
        "control_hojas": (
            processed
            / "ca0001_fondo3_historico_control_hojas.csv"
        ),
        "errores": (
            processed
            / "ca0001_fondo3_historico_errores.csv"
        ),
        "grupos10": (
            processed
            / "ca0001_fondo3_historico_control_grupos_hoja10.csv"
        ),
        "fusiones": (
            processed
            / "ca0001_fondo3_historico_fusiones.csv"
        ),
        "catalogo3": (
            processed
            / "ca0001_fondo3_historico_catalogo_emisores.csv"
        ),
        "catalogo10": (
            processed
            / "ca0001_fondo3_historico_catalogo_isin.csv"
        ),
        "top": (
            processed
            / "ca0001_fondo3_historico_top_ultimo_mes.csv"
        ),
    }

    hoja3_df.to_csv(
        rutas["hoja3"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    hoja10_df.to_csv(
        rutas["hoja10"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    hoja9_df.to_csv(
        rutas["hoja9"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    control_archivos_df.to_csv(
        rutas["control_archivos"],
        index=False,
        encoding="utf-8-sig",
    )
    control_hojas_df.to_csv(
        rutas["control_hojas"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    errores_df.to_csv(
        rutas["errores"],
        index=False,
        encoding="utf-8-sig",
    )
    grupos10_df.to_csv(
        rutas["grupos10"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    fusiones_df.to_csv(
        rutas["fusiones"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    catalogo3.to_csv(
        rutas["catalogo3"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    catalogo10.to_csv(
        rutas["catalogo10"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    top_ultimo.to_csv(
        rutas["top"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )

    archivos_correctos = int(
        (control_archivos_df["estado_general"] == "correcto").sum()
    )
    archivos_revisar = int(
        (control_archivos_df["estado_general"] == "revisar").sum()
    )
    archivos_error = int(
        (control_archivos_df["estado_general"] == "error").sum()
    )

    print("\n" + "=" * 112)
    print("CONSOLIDACIÓN HISTÓRICA CA-0001 TERMINADA")
    print("=" * 112)
    print(f"Archivos inventariados: {len(inventario)}")
    print(f"Archivos correctos: {archivos_correctos}")
    print(f"Archivos para revisar: {archivos_revisar}")
    print(f"Archivos con error general: {archivos_error}")
    print(f"Errores de archivo/hoja registrados: {len(errores_df)}")
    print(f"Registros históricos hoja 3: {len(hoja3_df):,}")
    print(f"Registros históricos hoja 10: {len(hoja10_df):,}")
    print(f"Registros históricos hoja 9: {len(hoja9_df):,}")

    if not hoja3_df.empty:
        print(
            "Rango hoja 3:",
            hoja3_df["fecha_cartera"].min().date(),
            "a",
            hoja3_df["fecha_cartera"].max().date(),
        )
        print(
            "Meses únicos hoja 3:",
            hoja3_df["fecha_cartera"].nunique(),
        )

    if not hoja10_df.empty:
        print(
            "Rango hoja 10:",
            hoja10_df["fecha_cartera"].min().date(),
            "a",
            hoja10_df["fecha_cartera"].max().date(),
        )
        print(
            "Meses únicos hoja 10:",
            hoja10_df["fecha_cartera"].nunique(),
        )

    print("\nESTADO DE LAS HOJAS")
    print("-" * 112)
    if not control_hojas_df.empty:
        print(
            control_hojas_df.groupby(
                ["hoja", "estado_proceso"],
                dropna=False,
            )
            .size()
            .reset_index(name="archivos")
            .to_string(index=False)
        )

    print("\nTOP DEL ÚLTIMO MES")
    print("-" * 112)

    if top_ultimo.empty:
        print("No se generó top del último mes.")
    else:
        for fuente in sorted(
            top_ultimo["fuente_detalle"].unique()
        ):
            for afp in AFPS:
                tabla = top_ultimo[
                    (
                        top_ultimo["fuente_detalle"]
                        == fuente
                    )
                    & (top_ultimo["afp"] == afp)
                ].head(8)

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
        "\nCriterio para el siguiente paso:\n"
        "- No se suman hoja 3, hoja 9 y hoja 10; cada una representa una "
        "vista distinta de la misma cartera.\n"
        "- Primero se revisarán los errores y los cambios históricos de "
        "estructura.\n"
        "- Después se reconciliarán los totales monetarios de hoja 3 y "
        "hoja 10 contra FP-1356 por AFP y mes.\n"
        "- Solo los meses reconciliados se utilizarán para construir "
        "exposiciones por ISIN, gestora, sector, país y moneda.\n"
        "- Los registros pendientes permanecen identificados y no se "
        "eliminan ni se duplican automáticamente."
    )


if __name__ == "__main__":
    main()
