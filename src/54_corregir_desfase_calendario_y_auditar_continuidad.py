from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


AFPS = ["Habitat", "Integra", "Prima", "Profuturo"]
DESFASES_CALENDARIO = [4, 5]
COBERTURA_ESTRICTA = 1.00
COBERTURA_MINIMA_ORIENTATIVA = 0.75


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


def cargar_sbs(processed: Path) -> pd.DataFrame:
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
    cuota_col = detectar_columna(
        df.columns,
        {"valor_cuota", "valor_de_la_cuota", "cuota", "valor"},
    )

    if fecha_col is None or afp_col is None or cuota_col is None:
        raise ValueError(
            "La base SBS debe contener fecha, AFP y valor cuota."
        )

    salida = pd.DataFrame(
        {
            "fecha": pd.to_datetime(df[fecha_col], errors="coerce"),
            "afp": df[afp_col].map(normalizar_afp),
            "cuota_sbs": pd.to_numeric(df[cuota_col], errors="coerce"),
        }
    )

    return (
        salida.dropna(subset=["fecha", "afp", "cuota_sbs"])
        .sort_values(["afp", "fecha"])
        .drop_duplicates(subset=["fecha", "afp"], keep="last")
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
        .sort_values(["afp", "fecha"])
        .drop_duplicates(subset=["fecha", "afp"], keep="last")
        .reset_index(drop=True)
    )


def auditar_continuidad(
    predicciones: pd.DataFrame,
) -> pd.DataFrame:
    bloques = []

    for afp, bloque in predicciones.groupby("afp", sort=False):
        temporal = bloque.sort_values("fecha").copy()
        temporal["fecha_anterior_prediccion"] = temporal["fecha"].shift(1)
        temporal["dias_calendario_desde_anterior"] = (
            temporal["fecha"]
            - temporal["fecha_anterior_prediccion"]
        ).dt.days
        temporal["brecha_mayor_4_dias"] = (
            temporal["dias_calendario_desde_anterior"] > 4
        )
        temporal["brecha_mayor_10_dias"] = (
            temporal["dias_calendario_desde_anterior"] > 10
        )
        bloques.append(temporal)

    return pd.concat(bloques, ignore_index=True)


def construir_simulacion_calendario(
    sbs: pd.DataFrame,
    predicciones: pd.DataFrame,
) -> pd.DataFrame:
    filas = []

    for afp in AFPS:
        cuotas_afp = (
            sbs[sbs["afp"].eq(afp)]
            .sort_values("fecha")
            .reset_index(drop=True)
        )
        pred_afp = (
            predicciones[predicciones["afp"].eq(afp)]
            .sort_values("fecha")
            .reset_index(drop=True)
        )

        if cuotas_afp.empty or pred_afp.empty:
            continue

        fechas_pred = set(pred_afp["fecha"])

        for _, objetivo in pred_afp.iterrows():
            fecha_objetivo = pd.Timestamp(objetivo["fecha"])
            cuota_objetivo_fila = cuotas_afp[
                cuotas_afp["fecha"].eq(fecha_objetivo)
            ]

            if cuota_objetivo_fila.empty:
                continue

            cuota_objetivo = float(
                cuota_objetivo_fila["cuota_sbs"].iloc[0]
            )

            for desfase in DESFASES_CALENDARIO:
                fecha_corte = fecha_objetivo - pd.Timedelta(days=desfase)

                candidatas_ancla = cuotas_afp[
                    cuotas_afp["fecha"].le(fecha_corte)
                ]

                if candidatas_ancla.empty:
                    continue

                ancla = candidatas_ancla.iloc[-1]
                fecha_ancla = pd.Timestamp(ancla["fecha"])
                cuota_ancla = float(ancla["cuota_sbs"])

                fechas_sbs_esperadas = cuotas_afp[
                    cuotas_afp["fecha"].gt(fecha_ancla)
                    & cuotas_afp["fecha"].le(fecha_objetivo)
                ]["fecha"].tolist()

                fechas_pred_disponibles = [
                    fecha
                    for fecha in fechas_sbs_esperadas
                    if fecha in fechas_pred
                ]

                n_esperadas = len(fechas_sbs_esperadas)
                n_disponibles = len(fechas_pred_disponibles)

                if n_esperadas == 0 or n_disponibles == 0:
                    continue

                cobertura = n_disponibles / n_esperadas

                ventana_pred = pred_afp[
                    pred_afp["fecha"].isin(fechas_pred_disponibles)
                ].sort_values("fecha")

                retorno_estimado_acumulado = float(
                    (1.0 + ventana_pred["retorno_estimado"]).prod() - 1.0
                )
                cuota_estimada = cuota_ancla * (
                    1.0 + retorno_estimado_acumulado
                )
                retorno_real_acumulado = (
                    cuota_objetivo / cuota_ancla - 1.0
                )
                error_pct = cuota_estimada / cuota_objetivo - 1.0

                filas.append(
                    {
                        "afp": afp,
                        "fecha_objetivo": fecha_objetivo,
                        "desfase_calendario_dias": desfase,
                        "fecha_corte_publicacion_simulada": fecha_corte,
                        "fecha_ancla_sbs": fecha_ancla,
                        "dias_calendario_entre_ancla_y_objetivo": (
                            fecha_objetivo - fecha_ancla
                        ).days,
                        "cuota_ancla_sbs": cuota_ancla,
                        "cuota_sbs_objetivo": cuota_objetivo,
                        "fechas_sbs_esperadas": n_esperadas,
                        "predicciones_disponibles": n_disponibles,
                        "cobertura_predicciones_pct": cobertura * 100.0,
                        "retorno_estimado_acumulado": (
                            retorno_estimado_acumulado
                        ),
                        "retorno_real_acumulado": retorno_real_acumulado,
                        "cuota_estimada": cuota_estimada,
                        "error_pct": error_pct,
                        "error_abs_pct": abs(error_pct),
                        "direccion_correcta": (
                            np.sign(retorno_estimado_acumulado)
                            == np.sign(retorno_real_acumulado)
                        ),
                        "ventana_estricta": cobertura >= COBERTURA_ESTRICTA,
                        "ventana_orientativa": (
                            cobertura >= COBERTURA_MINIMA_ORIENTATIVA
                        ),
                    }
                )

    return pd.DataFrame(filas)


def resumir_metricas(
    simulacion: pd.DataFrame,
    columna_filtro: str,
    etiqueta: str,
) -> pd.DataFrame:
    base = simulacion[simulacion[columna_filtro].eq(True)].copy()

    filas = []

    for (afp, desfase), bloque in base.groupby(
        ["afp", "desfase_calendario_dias"],
        sort=True,
    ):
        if bloque.empty:
            continue

        filas.append(
            {
                "tipo_evaluacion": etiqueta,
                "afp": afp,
                "desfase_calendario_dias": int(desfase),
                "observaciones": len(bloque),
                "fecha_inicio": bloque["fecha_objetivo"].min(),
                "fecha_fin": bloque["fecha_objetivo"].max(),
                "cobertura_media_pct": float(
                    bloque["cobertura_predicciones_pct"].mean()
                ),
                "mape_cuota_pct": float(
                    bloque["error_abs_pct"].mean() * 100.0
                ),
                "p90_error_abs_pct": float(
                    bloque["error_abs_pct"].quantile(0.90) * 100.0
                ),
                "sesgo_medio_pct": float(
                    bloque["error_pct"].mean() * 100.0
                ),
                "correlacion_retorno_acumulado": float(
                    bloque["retorno_real_acumulado"].corr(
                        bloque["retorno_estimado_acumulado"]
                    )
                ),
                "direccion_correcta_pct": float(
                    bloque["direccion_correcta"].mean() * 100.0
                ),
            }
        )

    return pd.DataFrame(filas)


def main() -> None:
    raiz = Path(__file__).resolve().parents[1]
    processed = raiz / "data" / "processed"

    sbs = cargar_sbs(processed)
    predicciones = cargar_predicciones(processed)
    auditoria = auditar_continuidad(predicciones)
    simulacion = construir_simulacion_calendario(sbs, predicciones)

    metricas_estrictas = resumir_metricas(
        simulacion,
        "ventana_estricta",
        "cobertura_100_pct",
    )
    metricas_orientativas = resumir_metricas(
        simulacion,
        "ventana_orientativa",
        "cobertura_minima_75_pct",
    )
    metricas = pd.concat(
        [metricas_estrictas, metricas_orientativas],
        ignore_index=True,
    )

    resumen_brechas = (
        auditoria.groupby("afp", as_index=False)
        .agg(
            observaciones_prediccion=("fecha", "count"),
            fecha_inicio=("fecha", "min"),
            fecha_fin=("fecha", "max"),
            brechas_mayores_4_dias=(
                "brecha_mayor_4_dias",
                "sum",
            ),
            brechas_mayores_10_dias=(
                "brecha_mayor_10_dias",
                "sum",
            ),
            maxima_brecha_calendario=(
                "dias_calendario_desde_anterior",
                "max",
            ),
        )
    )

    rutas = {
        "auditoria": (
            processed
            / "ca0001_modelo54_auditoria_continuidad.csv"
        ),
        "brechas": (
            processed
            / "ca0001_modelo54_resumen_brechas.csv"
        ),
        "simulacion": (
            processed
            / "ca0001_modelo54_simulacion_calendario.csv"
        ),
        "metricas": (
            processed
            / "ca0001_modelo54_metricas_calendario.csv"
        ),
        "json": (
            processed
            / "ca0001_modelo54_resumen.json"
        ),
    }

    auditoria.to_csv(
        rutas["auditoria"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    resumen_brechas.to_csv(
        rutas["brechas"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    simulacion.to_csv(
        rutas["simulacion"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    metricas.to_csv(
        rutas["metricas"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )

    contenido = {
        "version": "modelo54_desfase_calendario_y_auditoria",
        "desfases_calendario": DESFASES_CALENDARIO,
        "resumen_brechas": resumen_brechas.to_dict(orient="records"),
        "metricas": metricas.to_dict(orient="records"),
        "nota": (
            "El desfase se calcula en días calendario. Para cada fecha "
            "objetivo se usa la última cuota SBS cuya fecha sea menor o "
            "igual al día objetivo menos 4 o 5 días."
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

    print("\nAUDITORÍA DEL DESFASE CALENDARIO TERMINADA")
    print("=" * 120)

    print("\nRESUMEN DE CONTINUIDAD DE LAS PREDICCIONES")
    print("-" * 120)
    print(resumen_brechas.to_string(index=False))

    print("\nMÉTRICAS CON DESFASE REAL DE 4 Y 5 DÍAS CALENDARIO")
    print("-" * 120)
    if metricas.empty:
        print("No hubo ventanas suficientes para evaluar.")
    else:
        print(metricas.to_string(index=False))

    print("\nÚLTIMA VENTANA POR AFP Y DESFASE")
    print("-" * 120)
    ultimas = (
        simulacion.sort_values(
            ["afp", "desfase_calendario_dias", "fecha_objetivo"]
        )
        .groupby(
            ["afp", "desfase_calendario_dias"],
            as_index=False,
        )
        .tail(1)
    )
    columnas = [
        "afp",
        "desfase_calendario_dias",
        "fecha_objetivo",
        "fecha_corte_publicacion_simulada",
        "fecha_ancla_sbs",
        "dias_calendario_entre_ancla_y_objetivo",
        "fechas_sbs_esperadas",
        "predicciones_disponibles",
        "cobertura_predicciones_pct",
        "cuota_ancla_sbs",
        "cuota_estimada",
        "cuota_sbs_objetivo",
        "error_pct",
        "direccion_correcta",
    ]
    print(ultimas[columnas].to_string(index=False))

    print("\nArchivos creados:")
    for ruta in rutas.values():
        print(f" - {ruta.resolve()}")

    print(
        "\nLectura correcta:\n"
        "- El módulo 53 usó 4 o 5 observaciones, no 4 o 5 días calendario.\n"
        "- Este módulo usa exactamente 4 o 5 días calendario para localizar "
        "la última cuota que habría estado disponible.\n"
        "- También mide si faltan predicciones dentro de cada ventana.\n"
        "- Las métricas de cobertura 100 % son las más confiables.\n"
        "- Las métricas con cobertura mínima de 75 % son solo orientativas."
    )


if __name__ == "__main__":
    main()
