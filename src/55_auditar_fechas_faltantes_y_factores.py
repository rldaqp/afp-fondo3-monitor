from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


AFPS = ["Habitat", "Integra", "Prima", "Profuturo"]

DIAS_SEMANA = {
    0: "lunes",
    1: "martes",
    2: "miercoles",
    3: "jueves",
    4: "viernes",
    5: "sabado",
    6: "domingo",
}


def limpiar_nombre(valor: object) -> str:
    texto = str(valor).strip().upper()
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(
        caracter
        for caracter in texto
        if not unicodedata.combining(caracter)
    )
    return re.sub(r"[^A-Z0-9]+", "", texto)


def leer_csv_flexible(ruta: Path) -> pd.DataFrame:
    intentos = [
        {"sep": None, "engine": "python", "encoding": "utf-8-sig"},
        {"sep": None, "engine": "python", "encoding": "latin-1"},
        {"sep": ",", "encoding": "utf-8-sig"},
        {"sep": ";", "encoding": "utf-8-sig"},
        {"sep": ";", "encoding": "latin-1"},
    ]

    ultimo_error: Exception | None = None

    for argumentos in intentos:
        try:
            return pd.read_csv(ruta, **argumentos)
        except Exception as error:
            ultimo_error = error

    raise RuntimeError(f"No se pudo leer {ruta}: {ultimo_error}")


def detectar_columna(
    columnas: Iterable[object],
    alias: set[str],
) -> str | None:
    alias_limpios = {limpiar_nombre(valor) for valor in alias}

    for columna in columnas:
        if limpiar_nombre(columna) in alias_limpios:
            return str(columna)

    for columna in columnas:
        limpio = limpiar_nombre(columna)

        for candidato in sorted(alias_limpios, key=len, reverse=True):
            if candidato and (
                limpio.startswith(candidato)
                or limpio.endswith(candidato)
            ):
                return str(columna)

    return None


def normalizar_afp(valor: object) -> str | None:
    limpio = limpiar_nombre(valor)

    for afp in AFPS:
        if limpiar_nombre(afp) in limpio:
            return afp

    return None


def cargar_inicio_test(processed: Path) -> pd.Timestamp:
    ruta = processed / "ca0001_modelo50_division_temporal.csv"

    if not ruta.exists():
        raise FileNotFoundError(
            "No existe ca0001_modelo50_division_temporal.csv."
        )

    df = leer_csv_flexible(ruta)
    fila = df[
        df["segmento"].astype(str).eq("prueba_intocable")
    ]

    if fila.empty:
        raise ValueError(
            "No se encontró el segmento prueba_intocable."
        )

    return pd.to_datetime(
        fila["fecha_inicio"].iloc[0],
        errors="raise",
    )


def cargar_sbs(
    processed: Path,
    inicio_test: pd.Timestamp,
) -> pd.DataFrame:
    ruta = processed / "sbs_fondo3_base_maestra.csv"

    if not ruta.exists():
        raise FileNotFoundError(f"No existe la base SBS: {ruta}")

    df = leer_csv_flexible(ruta)

    fecha_col = detectar_columna(
        df.columns,
        {"fecha", "date", "fecha_cuota", "fecha_valor_cuota"},
    )
    afp_col = detectar_columna(
        df.columns,
        {"afp", "administradora", "nombre_afp"},
    )

    if fecha_col is None or afp_col is None:
        raise ValueError(
            "No se identificaron fecha y AFP en la base SBS."
        )

    salida = pd.DataFrame(
        {
            "fecha": pd.to_datetime(df[fecha_col], errors="coerce"),
            "afp": df[afp_col].map(normalizar_afp),
        }
    )

    return (
        salida.dropna(subset=["fecha", "afp"])
        .loc[lambda x: x["fecha"].ge(inicio_test)]
        .drop_duplicates(subset=["fecha", "afp"])
        .sort_values(["afp", "fecha"])
        .reset_index(drop=True)
    )


def cargar_predicciones(processed: Path) -> pd.DataFrame:
    ruta = processed / "ca0001_modelo51_predicciones_prueba.csv"

    if not ruta.exists():
        raise FileNotFoundError(
            "No existe ca0001_modelo51_predicciones_prueba.csv."
        )

    df = leer_csv_flexible(ruta)

    fecha_col = detectar_columna(df.columns, {"fecha", "date"})
    afp_col = detectar_columna(df.columns, {"afp", "administradora"})
    pred_col = detectar_columna(
        df.columns,
        {
            "retorno_estimado",
            "retorno_predicho",
            "prediccion",
            "y_pred",
        },
    )

    if fecha_col is None or afp_col is None or pred_col is None:
        raise ValueError(
            "No se identificaron fecha, AFP y retorno estimado."
        )

    salida = pd.DataFrame(
        {
            "fecha": pd.to_datetime(df[fecha_col], errors="coerce"),
            "afp": df[afp_col].map(normalizar_afp),
            "retorno_estimado": pd.to_numeric(
                df[pred_col],
                errors="coerce",
            ),
        }
    )

    return (
        salida.dropna(subset=["fecha", "afp", "retorno_estimado"])
        .drop_duplicates(subset=["fecha", "afp"], keep="last")
        .sort_values(["afp", "fecha"])
        .reset_index(drop=True)
    )


def cargar_canasta(processed: Path) -> pd.DataFrame:
    ruta = processed / "ca0001_modelo51_canasta_depurada.csv"

    if not ruta.exists():
        raise FileNotFoundError(
            "No existe ca0001_modelo51_canasta_depurada.csv."
        )

    df = leer_csv_flexible(ruta)

    if not {"afp", "factor"}.issubset(df.columns):
        raise ValueError(
            "La canasta depurada no contiene afp y factor."
        )

    df["afp"] = df["afp"].map(normalizar_afp)
    df["factor"] = df["factor"].astype(str)

    return (
        df.dropna(subset=["afp", "factor"])
        .drop_duplicates(subset=["afp", "factor"])
        .reset_index(drop=True)
    )


def inferir_transformacion_factor(
    serie: pd.Series,
    nombre: str,
) -> str:
    valores = pd.to_numeric(serie, errors="coerce").dropna()

    if len(valores) < 30:
        return "insuficiente"

    limpio = limpiar_nombre(nombre)
    fraccion_negativa = float((valores < 0).mean())
    fraccion_positiva = float((valores > 0).mean())
    p99_abs = float(valores.abs().quantile(0.99))

    if (
        fraccion_negativa > 0.05
        and fraccion_positiva > 0.05
        and p99_abs <= 0.50
    ):
        return "ya_es_variacion"

    if any(
        token in limpio
        for token in [
            "YIELD",
            "RATE",
            "TASA",
            "TREASURY",
            "TNX",
            "IRX",
            "FVX",
            "TYX",
        ]
    ):
        return "diferencia"

    return "retorno_porcentual"


def cargar_factores_transformados(
    processed: Path,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    ruta = processed / "mercados_factores_modelo.csv"

    if not ruta.exists():
        raise FileNotFoundError(
            f"No existe el archivo de mercados: {ruta}"
        )

    df = leer_csv_flexible(ruta)

    fecha_col = detectar_columna(
        df.columns,
        {"fecha", "date", "trading_date"},
    )

    if fecha_col is None:
        fecha_col = str(df.columns[0])

    salida = pd.DataFrame(
        {
            "fecha": pd.to_datetime(
                df[fecha_col],
                errors="coerce",
            )
        }
    )
    transformaciones = []

    for columna in df.columns:
        if str(columna) == fecha_col:
            continue

        serie = pd.to_numeric(df[columna], errors="coerce")

        if serie.notna().sum() < 30:
            continue

        metodo = inferir_transformacion_factor(
            serie,
            str(columna),
        )

        if metodo == "ya_es_variacion":
            transformada = serie
        elif metodo == "diferencia":
            transformada = serie.diff()
        elif metodo == "retorno_porcentual":
            transformada = serie.pct_change(fill_method=None)
        else:
            continue

        salida[str(columna)] = transformada
        transformaciones.append(
            {
                "factor": str(columna),
                "metodo": metodo,
                "observaciones_no_nulas": int(
                    transformada.notna().sum()
                ),
            }
        )

    salida = (
        salida.dropna(subset=["fecha"])
        .sort_values("fecha")
        .drop_duplicates(subset=["fecha"], keep="last")
        .reset_index(drop=True)
    )

    return salida, pd.DataFrame(transformaciones)


def auditar_fechas(
    sbs: pd.DataFrame,
    predicciones: pd.DataFrame,
    canasta: pd.DataFrame,
    factores: pd.DataFrame,
) -> pd.DataFrame:
    pred_keys = set(
        zip(predicciones["fecha"], predicciones["afp"])
    )
    fechas_mercado = set(factores["fecha"])

    factor_index = factores.set_index("fecha")
    filas = []

    for _, fila_sbs in sbs.iterrows():
        fecha = pd.Timestamp(fila_sbs["fecha"])
        afp = str(fila_sbs["afp"])
        tiene_prediccion = (fecha, afp) in pred_keys

        seleccionados = (
            canasta.loc[
                canasta["afp"].eq(afp),
                "factor",
            ]
            .astype(str)
            .tolist()
        )

        fecha_en_mercado = fecha in fechas_mercado
        disponibles = []
        faltantes = []

        if fecha_en_mercado:
            registro = factor_index.loc[fecha]

            if isinstance(registro, pd.DataFrame):
                registro = registro.iloc[-1]

            for factor in seleccionados:
                if (
                    factor in registro.index
                    and pd.notna(registro[factor])
                ):
                    disponibles.append(factor)
                else:
                    faltantes.append(factor)
        else:
            faltantes = seleccionados.copy()

        total = len(seleccionados)
        n_disponibles = len(disponibles)
        cobertura = (
            n_disponibles / total
            if total > 0
            else np.nan
        )

        if tiene_prediccion:
            causa = "prediccion_disponible"
        elif not fecha_en_mercado:
            causa = "fecha_ausente_en_archivo_mercados"
        elif n_disponibles == 0:
            causa = "ningun_factor_seleccionado_disponible"
        elif n_disponibles < total:
            causa = "faltan_factores_seleccionados"
        else:
            causa = "factores_disponibles_pero_sin_prediccion"

        filas.append(
            {
                "fecha": fecha,
                "dia_semana": DIAS_SEMANA[fecha.weekday()],
                "afp": afp,
                "tiene_prediccion": tiene_prediccion,
                "fecha_en_archivo_mercados": fecha_en_mercado,
                "factores_seleccionados": total,
                "factores_disponibles": n_disponibles,
                "cobertura_factores_pct": (
                    cobertura * 100.0
                    if pd.notna(cobertura)
                    else np.nan
                ),
                "lista_factores_disponibles": " | ".join(disponibles),
                "lista_factores_faltantes": " | ".join(faltantes),
                "causa_preliminar": causa,
            }
        )

    return pd.DataFrame(filas)


def construir_brechas(
    predicciones: pd.DataFrame,
) -> pd.DataFrame:
    filas = []

    for afp, bloque in predicciones.groupby("afp", sort=False):
        temporal = bloque.sort_values("fecha").copy()
        temporal["fecha_anterior"] = temporal["fecha"].shift(1)
        temporal["dias_brecha"] = (
            temporal["fecha"] - temporal["fecha_anterior"]
        ).dt.days

        brechas = temporal[
            temporal["dias_brecha"].gt(4)
        ]

        for _, fila in brechas.iterrows():
            filas.append(
                {
                    "afp": afp,
                    "fecha_anterior": fila["fecha_anterior"],
                    "fecha_siguiente": fila["fecha"],
                    "dias_brecha": int(fila["dias_brecha"]),
                }
            )

    return pd.DataFrame(filas)


def resumir_por_afp(auditoria: pd.DataFrame) -> pd.DataFrame:
    resumen = (
        auditoria.groupby("afp", as_index=False)
        .agg(
            fechas_sbs_esperadas=("fecha", "count"),
            predicciones_disponibles=("tiene_prediccion", "sum"),
            fechas_sin_prediccion=(
                "tiene_prediccion",
                lambda serie: int((~serie).sum()),
            ),
            cobertura_predicciones_pct=(
                "tiene_prediccion",
                lambda serie: float(serie.mean() * 100.0),
            ),
            fechas_ausentes_en_mercados=(
                "causa_preliminar",
                lambda serie: int(
                    (serie == "fecha_ausente_en_archivo_mercados").sum()
                ),
            ),
            fechas_con_factores_incompletos=(
                "causa_preliminar",
                lambda serie: int(
                    (serie == "faltan_factores_seleccionados").sum()
                ),
            ),
            fechas_con_factores_completos_sin_prediccion=(
                "causa_preliminar",
                lambda serie: int(
                    (
                        serie
                        == "factores_disponibles_pero_sin_prediccion"
                    ).sum()
                ),
            ),
        )
    )

    return resumen


def fechas_faltantes_comunes(
    auditoria: pd.DataFrame,
) -> pd.DataFrame:
    faltantes = auditoria[
        ~auditoria["tiene_prediccion"]
    ].copy()

    if faltantes.empty:
        return pd.DataFrame()

    resumen = (
        faltantes.groupby("fecha", as_index=False)
        .agg(
            dia_semana=("dia_semana", "first"),
            afp_sin_prediccion=("afp", "nunique"),
            lista_afp=(
                "afp",
                lambda serie: " | ".join(sorted(set(serie))),
            ),
            causas=(
                "causa_preliminar",
                lambda serie: " | ".join(sorted(set(serie))),
            ),
            factores_faltantes=(
                "lista_factores_faltantes",
                lambda serie: " || ".join(
                    sorted(
                        {
                            valor
                            for valor in serie
                            if str(valor).strip()
                        }
                    )
                ),
            ),
        )
        .sort_values(["afp_sin_prediccion", "fecha"], ascending=[False, True])
        .reset_index(drop=True)
    )

    resumen["faltante_en_las_4_afp"] = (
        resumen["afp_sin_prediccion"] == 4
    )

    return resumen


def main() -> None:
    raiz = Path(__file__).resolve().parents[1]
    processed = raiz / "data" / "processed"

    inicio_test = cargar_inicio_test(processed)
    sbs = cargar_sbs(processed, inicio_test)
    predicciones = cargar_predicciones(processed)
    canasta = cargar_canasta(processed)
    factores, transformaciones = cargar_factores_transformados(processed)

    auditoria = auditar_fechas(
        sbs,
        predicciones,
        canasta,
        factores,
    )
    resumen = resumir_por_afp(auditoria)
    comunes = fechas_faltantes_comunes(auditoria)
    brechas = construir_brechas(predicciones)

    rutas = {
        "auditoria": (
            processed
            / "ca0001_modelo55_auditoria_fechas_prediccion.csv"
        ),
        "resumen": (
            processed
            / "ca0001_modelo55_resumen_cobertura.csv"
        ),
        "comunes": (
            processed
            / "ca0001_modelo55_fechas_faltantes_comunes.csv"
        ),
        "brechas": (
            processed
            / "ca0001_modelo55_brechas_prediccion.csv"
        ),
        "transformaciones": (
            processed
            / "ca0001_modelo55_transformaciones_factores.csv"
        ),
        "json": (
            processed
            / "ca0001_modelo55_resumen.json"
        ),
    }

    auditoria.to_csv(
        rutas["auditoria"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    resumen.to_csv(
        rutas["resumen"],
        index=False,
        encoding="utf-8-sig",
    )
    comunes.to_csv(
        rutas["comunes"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    brechas.to_csv(
        rutas["brechas"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    transformaciones.to_csv(
        rutas["transformaciones"],
        index=False,
        encoding="utf-8-sig",
    )

    contenido = {
        "version": "modelo55_auditoria_fechas_faltantes",
        "inicio_prueba": str(inicio_test.date()),
        "resumen_cobertura": resumen.to_dict(orient="records"),
        "fechas_faltantes_comunes": comunes.to_dict(orient="records"),
        "brechas": brechas.to_dict(orient="records"),
        "nota": (
            "Este módulo no rellena datos. Solo identifica si la ausencia "
            "de predicción se origina en fechas ausentes del archivo de "
            "mercados, factores seleccionados faltantes o una falla del "
            "pipeline pese a tener factores completos."
        ),
    }

    rutas["json"].write_text(
        json.dumps(
            contenido,
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )

    print("\nAUDITORÍA DE FECHAS FALTANTES TERMINADA")
    print("=" * 120)

    print("\nRESUMEN DE COBERTURA POR AFP")
    print("-" * 120)
    print(resumen.to_string(index=False))

    print("\nCAUSAS DE FECHAS SIN PREDICCIÓN")
    print("-" * 120)
    causas = (
        auditoria[~auditoria["tiene_prediccion"]]
        .groupby(["afp", "causa_preliminar"])
        .size()
        .reset_index(name="fechas")
    )
    print(causas.to_string(index=False))

    print("\nÚLTIMAS 30 FECHAS FALTANTES COMUNES")
    print("-" * 120)
    if comunes.empty:
        print("No hay fechas faltantes.")
    else:
        print(comunes.tail(30).to_string(index=False))

    print("\nBRECHAS MAYORES A 4 DÍAS")
    print("-" * 120)
    if brechas.empty:
        print("No hay brechas mayores a 4 días.")
    else:
        print(brechas.to_string(index=False))

    print("\nArchivos creados:")
    for ruta in rutas.values():
        print(f" - {ruta.resolve()}")

    print(
        "\nLectura correcta:\n"
        "- Si predominan fechas ausentes en mercados, debemos completar "
        "el calendario de factores o definir un modelo de respaldo para "
        "días sin sesión.\n"
        "- Si faltan factores seleccionados, debemos identificar cuál "
        "ticker está incompleto y reconstruirlo.\n"
        "- Si los factores están completos pero no existe predicción, "
        "hay una falla de ensamblaje del modelo.\n"
        "- No se debe rellenar con cero ni interpolar hasta conocer la causa."
    )


if __name__ == "__main__":
    main()
