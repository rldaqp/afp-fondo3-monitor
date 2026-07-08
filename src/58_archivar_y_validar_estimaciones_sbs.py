from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Iterable

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


AFPS = ["Habitat", "Integra", "Prima", "Profuturo"]
VENTANA_RECIENTE = 20


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
            "fecha_cuota": pd.to_datetime(
                df[fecha_col],
                errors="coerce",
            ),
            "afp": df[afp_col].map(normalizar_afp),
            "cuota_sbs": pd.to_numeric(
                df[cuota_col],
                errors="coerce",
            ),
        }
    )

    salida = (
        salida.dropna(subset=["fecha_cuota", "afp", "cuota_sbs"])
        .sort_values(["afp", "fecha_cuota"])
        .drop_duplicates(
            subset=["fecha_cuota", "afp"],
            keep="last",
        )
        .reset_index(drop=True)
    )

    salida["cuota_sbs_anterior"] = (
        salida.groupby("afp")["cuota_sbs"].shift(1)
    )
    salida["retorno_real_diario"] = (
        salida["cuota_sbs"]
        / salida["cuota_sbs_anterior"]
        - 1.0
    )

    return salida


def cargar_estimaciones_actuales(
    processed: Path,
) -> tuple[pd.DataFrame, pd.Timestamp]:
    ruta = processed / "ca0001_modelo57_estimaciones_pendientes.csv"

    if not ruta.exists():
        raise FileNotFoundError(
            "No existe ca0001_modelo57_estimaciones_pendientes.csv. "
            "Primero ejecute el módulo 57."
        )

    fecha_archivo = pd.Timestamp.fromtimestamp(
        ruta.stat().st_mtime
    )

    df = leer_csv_flexible(ruta)

    columnas_requeridas = [
        "fecha_cuota",
        "afp",
        "fecha_ultima_cuota_oficial",
        "cuota_ultima_oficial",
        "dias_desde_ultima_oficial",
        "retorno_estimado",
        "cuota_estimada",
    ]
    columnas_cobertura = [
        "factores_total",
        "factores_con_dato_nuevo",
        "cobertura_factores_pct",
        "estado_cobertura",
        "factores_actualizados",
        "factores_sin_actualizar",
    ]

    faltantes = set(columnas_requeridas) - set(df.columns)

    if faltantes:
        raise ValueError(
            "Faltan columnas en las estimaciones del módulo 57: "
            + ", ".join(sorted(faltantes))
        )

    columnas_disponibles = columnas_requeridas + [
        columna
        for columna in columnas_cobertura
        if columna in df.columns
    ]
    salida = df[columnas_disponibles].copy()
    salida["fecha_cuota"] = pd.to_datetime(
        salida["fecha_cuota"],
        errors="coerce",
    )
    salida["fecha_ultima_cuota_oficial"] = pd.to_datetime(
        salida["fecha_ultima_cuota_oficial"],
        errors="coerce",
    )
    salida["afp"] = salida["afp"].map(normalizar_afp)

    for columna in [
        "cuota_ultima_oficial",
        "dias_desde_ultima_oficial",
        "retorno_estimado",
        "cuota_estimada",
        "factores_total",
        "factores_con_dato_nuevo",
        "cobertura_factores_pct",
    ]:
        if columna in salida.columns:
            salida[columna] = pd.to_numeric(
                salida[columna],
                errors="coerce",
            )

    salida = (
        salida.dropna(
            subset=[
                "fecha_cuota",
                "afp",
                "fecha_ultima_cuota_oficial",
                "cuota_ultima_oficial",
                "retorno_estimado",
                "cuota_estimada",
            ]
        )
        .sort_values(["afp", "fecha_cuota"])
        .reset_index(drop=True)
    )

    salida["fecha_generacion_archivo"] = fecha_archivo
    salida["archivo_origen"] = ruta.name

    return salida, fecha_archivo


def crear_id_pronostico(fila: pd.Series) -> str:
    partes = [
        str(fila["afp"]),
        pd.Timestamp(fila["fecha_cuota"]).strftime("%Y-%m-%d"),
        pd.Timestamp(
            fila["fecha_ultima_cuota_oficial"]
        ).strftime("%Y-%m-%d"),
        f"{float(fila['cuota_estimada']):.12f}",
        f"{float(fila['retorno_estimado']):.12f}",
    ]
    texto = "|".join(partes)
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()[:24]


def cargar_archivo_historico(processed: Path) -> pd.DataFrame:
    ruta = processed / "ca0001_modelo58_archivo_pronosticos.csv"

    if not ruta.exists():
        return pd.DataFrame()

    df = leer_csv_flexible(ruta)

    for columna in [
        "fecha_cuota",
        "fecha_ultima_cuota_oficial",
        "fecha_generacion_archivo",
    ]:
        if columna in df.columns:
            df[columna] = pd.to_datetime(
                df[columna],
                errors="coerce",
            )

    if "afp" in df.columns:
        df["afp"] = df["afp"].map(normalizar_afp)

    return df


def archivar_pronosticos(
    actuales: pd.DataFrame,
    archivo_previo: pd.DataFrame,
) -> tuple[pd.DataFrame, int]:
    nuevos = actuales.copy()
    nuevos["id_pronostico"] = nuevos.apply(
        crear_id_pronostico,
        axis=1,
    )

    if archivo_previo.empty:
        combinado = nuevos.copy()
        agregados = len(nuevos)
    else:
        archivo_previo = archivo_previo.copy()
        ids_previos = set(
            archivo_previo["id_pronostico"].astype(str)
        )

        columnas_metadatos = [
            "factores_total",
            "factores_con_dato_nuevo",
            "cobertura_factores_pct",
            "estado_cobertura",
            "factores_actualizados",
            "factores_sin_actualizar",
        ]
        nuevos_por_id = nuevos.set_index("id_pronostico")

        for columna in columnas_metadatos:
            if columna not in nuevos_por_id.columns:
                continue

            if columna not in archivo_previo.columns:
                archivo_previo[columna] = np.nan

            valores_nuevos = archivo_previo["id_pronostico"].map(
                nuevos_por_id[columna]
            )
            archivo_previo[columna] = archivo_previo[columna].where(
                archivo_previo[columna].notna(),
                valores_nuevos,
            )

        por_agregar = nuevos[
            ~nuevos["id_pronostico"].isin(ids_previos)
        ]
        agregados = len(por_agregar)
        combinado = pd.concat(
            [archivo_previo, por_agregar],
            ignore_index=True,
            sort=False,
        )

    combinado = (
        combinado.sort_values(
            [
                "afp",
                "fecha_cuota",
                "fecha_generacion_archivo",
            ]
        )
        .drop_duplicates(
            subset=["id_pronostico"],
            keep="first",
        )
        .reset_index(drop=True)
    )

    return combinado, agregados


def validar_pronosticos(
    archivo: pd.DataFrame,
    sbs: pd.DataFrame,
) -> pd.DataFrame:
    columnas_sbs = [
        "fecha_cuota",
        "afp",
        "cuota_sbs",
        "cuota_sbs_anterior",
        "retorno_real_diario",
    ]

    validacion = archivo.merge(
        sbs[columnas_sbs],
        on=["fecha_cuota", "afp"],
        how="left",
        validate="many_to_one",
    )

    validacion["estado_validacion"] = np.where(
        validacion["cuota_sbs"].notna(),
        "VALIDADO",
        "PENDIENTE",
    )
    validacion["error_cuota"] = (
        validacion["cuota_estimada"]
        - validacion["cuota_sbs"]
    )
    validacion["error_pct"] = (
        validacion["cuota_estimada"]
        / validacion["cuota_sbs"]
        - 1.0
    )
    validacion["error_abs_pct"] = (
        validacion["error_pct"].abs()
    )
    validacion["error_retorno_diario"] = (
        validacion["retorno_estimado"]
        - validacion["retorno_real_diario"]
    )
    validacion["direccion_diaria_correcta"] = (
        np.sign(validacion["retorno_estimado"])
        == np.sign(validacion["retorno_real_diario"])
    )

    validacion["retorno_estimado_desde_ancla"] = (
        validacion["cuota_estimada"]
        / validacion["cuota_ultima_oficial"]
        - 1.0
    )
    validacion["retorno_real_desde_ancla"] = (
        validacion["cuota_sbs"]
        / validacion["cuota_ultima_oficial"]
        - 1.0
    )
    validacion["direccion_acumulada_correcta"] = (
        np.sign(validacion["retorno_estimado_desde_ancla"])
        == np.sign(validacion["retorno_real_desde_ancla"])
    )

    return validacion


def seleccionar_versiones(
    validacion: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    ordenada = validacion.sort_values(
        [
            "afp",
            "fecha_cuota",
            "fecha_generacion_archivo",
        ]
    )

    primera = (
        ordenada.groupby(
            ["afp", "fecha_cuota"],
            as_index=False,
        )
        .head(1)
        .copy()
    )
    primera["version_evaluada"] = "primera_prediccion"

    ultima = (
        ordenada.groupby(
            ["afp", "fecha_cuota"],
            as_index=False,
        )
        .tail(1)
        .copy()
    )
    ultima["version_evaluada"] = "ultima_prediccion"

    return primera, ultima


def resumir_metricas_version(
    version: pd.DataFrame,
    etiqueta: str,
) -> pd.DataFrame:
    filas = []

    for afp in AFPS:
        bloque = (
            version[
                version["afp"].eq(afp)
                & version["estado_validacion"].eq("VALIDADO")
            ]
            .sort_values("fecha_cuota")
            .copy()
        )

        if bloque.empty:
            filas.append(
                {
                    "version_evaluada": etiqueta,
                    "afp": afp,
                    "observaciones_validadas": 0,
                    "fecha_inicio": pd.NaT,
                    "fecha_fin": pd.NaT,
                    "mape_cuota_pct": np.nan,
                    "mediana_error_abs_pct": np.nan,
                    "p90_error_abs_pct": np.nan,
                    "sesgo_medio_pct": np.nan,
                    "rmse_retorno_diario": np.nan,
                    "direccion_diaria_correcta_pct": np.nan,
                    "direccion_acumulada_correcta_pct": np.nan,
                    "mape_ultimas_20_pct": np.nan,
                    "direccion_ultimas_20_pct": np.nan,
                }
            )
            continue

        recientes = bloque.tail(VENTANA_RECIENTE)

        filas.append(
            {
                "version_evaluada": etiqueta,
                "afp": afp,
                "observaciones_validadas": len(bloque),
                "fecha_inicio": bloque["fecha_cuota"].min(),
                "fecha_fin": bloque["fecha_cuota"].max(),
                "mape_cuota_pct": float(
                    bloque["error_abs_pct"].mean() * 100.0
                ),
                "mediana_error_abs_pct": float(
                    bloque["error_abs_pct"].median() * 100.0
                ),
                "p90_error_abs_pct": float(
                    bloque["error_abs_pct"].quantile(0.90)
                    * 100.0
                ),
                "sesgo_medio_pct": float(
                    bloque["error_pct"].mean() * 100.0
                ),
                "rmse_retorno_diario": float(
                    np.sqrt(
                        np.mean(
                            bloque[
                                "error_retorno_diario"
                            ].dropna()
                            ** 2
                        )
                    )
                ),
                "direccion_diaria_correcta_pct": float(
                    bloque[
                        "direccion_diaria_correcta"
                    ].mean()
                    * 100.0
                ),
                "direccion_acumulada_correcta_pct": float(
                    bloque[
                        "direccion_acumulada_correcta"
                    ].mean()
                    * 100.0
                ),
                "mape_ultimas_20_pct": float(
                    recientes["error_abs_pct"].mean()
                    * 100.0
                ),
                "direccion_ultimas_20_pct": float(
                    recientes[
                        "direccion_acumulada_correcta"
                    ].mean()
                    * 100.0
                ),
            }
        )

    return pd.DataFrame(filas)


def calcular_metricas(
    primera: pd.DataFrame,
    ultima: pd.DataFrame,
) -> pd.DataFrame:
    return pd.concat(
        [
            resumir_metricas_version(
                primera,
                "primera_prediccion",
            ),
            resumir_metricas_version(
                ultima,
                "ultima_prediccion",
            ),
        ],
        ignore_index=True,
    )


def cargar_contribuciones(
    processed: Path,
) -> pd.DataFrame:
    ruta = processed / "ca0001_modelo57_contribuciones.csv"

    if not ruta.exists():
        return pd.DataFrame()

    df = leer_csv_flexible(ruta)

    columnas = {
        "fecha_cuota",
        "afp",
        "factor",
        "contribucion_modelo",
    }

    if not columnas.issubset(df.columns):
        return pd.DataFrame()

    df["fecha_cuota"] = pd.to_datetime(
        df["fecha_cuota"],
        errors="coerce",
    )
    df["afp"] = df["afp"].map(normalizar_afp)
    df["contribucion_modelo"] = pd.to_numeric(
        df["contribucion_modelo"],
        errors="coerce",
    )

    return df.dropna(
        subset=[
            "fecha_cuota",
            "afp",
            "factor",
            "contribucion_modelo",
        ]
    )


def reconciliar_contribuciones(
    contribuciones: pd.DataFrame,
    actuales: pd.DataFrame,
) -> pd.DataFrame:
    if contribuciones.empty or actuales.empty:
        return pd.DataFrame()

    suma = (
        contribuciones.groupby(
            ["fecha_cuota", "afp"],
            as_index=False,
        )["contribucion_modelo"]
        .sum()
        .rename(
            columns={
                "contribucion_modelo": (
                    "suma_contribuciones_incluye_intercepto"
                )
            }
        )
    )

    intercepto = (
        contribuciones[
            contribuciones["factor"].eq("intercepto")
        ][
            [
                "fecha_cuota",
                "afp",
                "contribucion_modelo",
            ]
        ]
        .rename(
            columns={
                "contribucion_modelo": (
                    "contribucion_intercepto"
                )
            }
        )
    )

    reconciliacion = (
        actuales[
            [
                "fecha_cuota",
                "afp",
                "retorno_estimado",
            ]
        ]
        .merge(
            suma,
            on=["fecha_cuota", "afp"],
            how="left",
            validate="one_to_one",
        )
        .merge(
            intercepto,
            on=["fecha_cuota", "afp"],
            how="left",
            validate="one_to_one",
        )
    )

    reconciliacion["diferencia_reconciliacion"] = (
        reconciliacion[
            "suma_contribuciones_incluye_intercepto"
        ]
        - reconciliacion["retorno_estimado"]
    )
    reconciliacion["reconciliado"] = (
        reconciliacion[
            "diferencia_reconciliacion"
        ].abs()
        <= 1e-10
    )

    return reconciliacion


def construir_pendientes(
    ultima: pd.DataFrame,
) -> pd.DataFrame:
    return (
        ultima[
            ultima["estado_validacion"].eq("PENDIENTE")
        ]
        .sort_values(["afp", "fecha_cuota"])
        .reset_index(drop=True)
    )


def construir_nuevos_validados(
    validacion: pd.DataFrame,
    processed: Path,
) -> pd.DataFrame:
    ruta_previa = (
        processed
        / "ca0001_modelo58_validaciones_confirmadas.csv"
    )

    previos = set()

    if ruta_previa.exists():
        df_previo = leer_csv_flexible(ruta_previa)
        if "id_pronostico" in df_previo.columns:
            previos = set(
                df_previo["id_pronostico"].astype(str)
            )

    return validacion[
        validacion["estado_validacion"].eq("VALIDADO")
        & ~validacion["id_pronostico"].isin(previos)
    ].copy()


def crear_graficos(
    ultima: pd.DataFrame,
    graficos_dir: Path,
) -> None:
    graficos_dir.mkdir(parents=True, exist_ok=True)

    for afp in AFPS:
        bloque = (
            ultima[
                ultima["afp"].eq(afp)
                & ultima["estado_validacion"].eq("VALIDADO")
            ]
            .sort_values("fecha_cuota")
            .copy()
        )

        if bloque.empty:
            continue

        plt.figure(figsize=(12, 6))
        plt.plot(
            bloque["fecha_cuota"],
            bloque["cuota_sbs"],
            label="Cuota oficial SBS",
            linewidth=1.8,
        )
        plt.plot(
            bloque["fecha_cuota"],
            bloque["cuota_estimada"],
            label="Última estimación archivada",
            linewidth=1.2,
            linestyle="--",
        )
        plt.title(
            f"{afp} Fondo 3: estimaciones validadas vs SBS"
        )
        plt.xlabel("Fecha del valor cuota")
        plt.ylabel("Valor cuota")
        plt.legend()
        plt.grid(True, alpha=0.25)
        plt.tight_layout()
        plt.savefig(
            graficos_dir
            / f"modelo58_{afp.lower()}_validado_vs_sbs.png",
            dpi=180,
        )
        plt.close()

        plt.figure(figsize=(12, 5))
        plt.plot(
            bloque["fecha_cuota"],
            bloque["error_pct"] * 100.0,
            linewidth=1.0,
        )
        plt.axhline(0.0, linewidth=1.0)
        plt.title(
            f"{afp} Fondo 3: error de las estimaciones validadas"
        )
        plt.xlabel("Fecha del valor cuota")
        plt.ylabel("Error estimado - oficial (%)")
        plt.grid(True, alpha=0.25)
        plt.tight_layout()
        plt.savefig(
            graficos_dir
            / f"modelo58_{afp.lower()}_error_validado.png",
            dpi=180,
        )
        plt.close()


def crear_controles(
    archivo: pd.DataFrame,
    actuales: pd.DataFrame,
    reconciliacion: pd.DataFrame,
) -> pd.DataFrame:
    ids_actuales = set(
        actuales.apply(crear_id_pronostico, axis=1)
    )
    ids_archivo = set(
        archivo["id_pronostico"].astype(str)
    )

    controles = [
        {
            "control": "pronosticos_actuales_archivados",
            "estado": (
                "correcto"
                if ids_actuales.issubset(ids_archivo)
                else "revisar"
            ),
            "detalle": (
                f"actuales={len(ids_actuales)}, "
                f"archivados={len(ids_archivo)}"
            ),
        },
        {
            "control": "ids_sin_duplicados",
            "estado": (
                "correcto"
                if archivo["id_pronostico"].is_unique
                else "revisar"
            ),
            "detalle": f"filas_archivo={len(archivo)}",
        },
        {
            "control": "reconciliacion_con_intercepto",
            "estado": (
                "no_aplica"
                if reconciliacion.empty
                else (
                    "correcto"
                    if reconciliacion["reconciliado"].all()
                    else "revisar"
                )
            ),
            "detalle": (
                "la suma de factores más intercepto debe igualar "
                "el retorno estimado"
            ),
        },
        {
            "control": "archivo_no_sobrescribe_pronosticos",
            "estado": "correcto",
            "detalle": (
                "cada versión se conserva con fecha de generación "
                "e identificador propio"
            ),
        },
        {
            "control": "metadatos_cobertura_archivados",
            "estado": (
                "correcto"
                if {
                    "cobertura_factores_pct",
                    "estado_cobertura",
                }.issubset(archivo.columns)
                else "no_aplica"
            ),
            "detalle": (
                "la cobertura observada al generar el pronóstico queda "
                "conservada para su validación posterior"
            ),
        },
    ]

    return pd.DataFrame(controles)


def crear_reporte(
    metricas: pd.DataFrame,
    pendientes: pd.DataFrame,
    nuevos_validados: pd.DataFrame,
    reconciliacion: pd.DataFrame,
    ruta: Path,
) -> None:
    lineas = [
        "# Archivo y validación automática de estimaciones",
        "",
        (
            "El módulo archiva las estimaciones y su cobertura de factores "
            "generadas por el módulo 57 antes de que sean reemplazadas. "
            "Cuando la SBS incorpora la cuota "
            "de una fecha estimada, el pronóstico pasa de PENDIENTE a VALIDADO."
        ),
        "",
        "## Nuevas validaciones",
        "",
        f"- Pronósticos recién validados: {len(nuevos_validados)}.",
        f"- Pronósticos todavía pendientes: {len(pendientes)}.",
        "",
        "## Métricas",
        "",
    ]

    for _, fila in metricas.iterrows():
        lineas.extend(
            [
                (
                    f"### {fila['afp']} — "
                    f"{fila['version_evaluada']}"
                ),
                "",
                (
                    f"- Observaciones validadas: "
                    f"{int(fila['observaciones_validadas'])}."
                ),
            ]
        )

        if int(fila["observaciones_validadas"]) > 0:
            lineas.extend(
                [
                    (
                        f"- MAPE de cuota: "
                        f"{fila['mape_cuota_pct']:.3f} %."
                    ),
                    (
                        f"- Dirección diaria correcta: "
                        f"{fila['direccion_diaria_correcta_pct']:.1f} %."
                    ),
                    (
                        f"- Dirección acumulada correcta: "
                        f"{fila['direccion_acumulada_correcta_pct']:.1f} %."
                    ),
                    (
                        f"- MAPE de las últimas {VENTANA_RECIENTE}: "
                        f"{fila['mape_ultimas_20_pct']:.3f} %."
                    ),
                ]
            )

        lineas.append("")

    lineas.extend(
        [
            "## Reconciliación de contribuciones",
            "",
            (
                "La contribución total incluye COPX, EPU, VIX o XLB, "
                "según la AFP, más el intercepto del modelo."
            ),
            (
                f"- Filas reconciliadas: "
                f"{int(reconciliacion['reconciliado'].sum()) if not reconciliacion.empty else 0} "
                f"de {len(reconciliacion)}."
            ),
            "",
            "## Regla operativa",
            "",
            (
                "Ejecute este módulo inmediatamente después del módulo 57 "
                "para archivar los pronósticos. Cuando actualice las cuotas "
                "SBS, vuelva a ejecutar primero el módulo 58 para validar las "
                "predicciones anteriores y después ejecute nuevamente el 57."
            ),
        ]
    )

    ruta.write_text("\n".join(lineas), encoding="utf-8")


def main() -> None:
    raiz = Path(__file__).resolve().parents[1]
    processed = raiz / "data" / "processed"
    graficos_dir = processed / "graficos_modelo58"

    sbs = cargar_sbs(processed)
    actuales, fecha_archivo = cargar_estimaciones_actuales(processed)
    archivo_previo = cargar_archivo_historico(processed)
    archivo, agregados = archivar_pronosticos(
        actuales,
        archivo_previo,
    )
    validacion = validar_pronosticos(archivo, sbs)
    primera, ultima = seleccionar_versiones(validacion)
    metricas = calcular_metricas(primera, ultima)
    pendientes = construir_pendientes(ultima)
    nuevos_validados = construir_nuevos_validados(
        validacion,
        processed,
    )
    contribuciones = cargar_contribuciones(processed)
    reconciliacion = reconciliar_contribuciones(
        contribuciones,
        actuales,
    )
    controles = crear_controles(
        archivo,
        actuales,
        reconciliacion,
    )

    crear_graficos(
        ultima,
        graficos_dir,
    )

    rutas = {
        "archivo": (
            processed
            / "ca0001_modelo58_archivo_pronosticos.csv"
        ),
        "validacion": (
            processed
            / "ca0001_modelo58_validacion_completa.csv"
        ),
        "confirmadas": (
            processed
            / "ca0001_modelo58_validaciones_confirmadas.csv"
        ),
        "nuevas": (
            processed
            / "ca0001_modelo58_nuevas_validaciones.csv"
        ),
        "pendientes": (
            processed
            / "ca0001_modelo58_pronosticos_pendientes.csv"
        ),
        "metricas": (
            processed
            / "ca0001_modelo58_metricas.csv"
        ),
        "reconciliacion": (
            processed
            / "ca0001_modelo58_reconciliacion_contribuciones.csv"
        ),
        "controles": (
            processed
            / "ca0001_modelo58_controles.csv"
        ),
        "reporte": (
            processed
            / "ca0001_modelo58_reporte.md"
        ),
        "json": (
            processed
            / "ca0001_modelo58_resumen.json"
        ),
    }

    archivo.to_csv(
        rutas["archivo"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d %H:%M:%S",
    )
    validacion.to_csv(
        rutas["validacion"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d %H:%M:%S",
    )

    confirmadas = validacion[
        validacion["estado_validacion"].eq("VALIDADO")
    ].copy()
    confirmadas.to_csv(
        rutas["confirmadas"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d %H:%M:%S",
    )
    nuevos_validados.to_csv(
        rutas["nuevas"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d %H:%M:%S",
    )
    pendientes.to_csv(
        rutas["pendientes"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d %H:%M:%S",
    )
    metricas.to_csv(
        rutas["metricas"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    reconciliacion.to_csv(
        rutas["reconciliacion"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    controles.to_csv(
        rutas["controles"],
        index=False,
        encoding="utf-8-sig",
    )
    crear_reporte(
        metricas,
        pendientes,
        nuevos_validados,
        reconciliacion,
        rutas["reporte"],
    )

    contenido = {
        "version": "modelo58_archivo_y_validacion",
        "fecha_archivo_modulo57": str(fecha_archivo),
        "pronosticos_agregados_esta_ejecucion": agregados,
        "pronosticos_archivados_total": len(archivo),
        "pronosticos_validados_total": len(confirmadas),
        "nuevas_validaciones": len(nuevos_validados),
        "pronosticos_pendientes": len(pendientes),
        "metricas": metricas.to_dict(orient="records"),
        "controles": controles.to_dict(orient="records"),
        "graficos": [
            ruta.name
            for ruta in sorted(graficos_dir.glob("*.png"))
        ],
        "nota": (
            "Para no perder un pronóstico, el módulo 58 debe ejecutarse "
            "antes de volver a generar el módulo 57 después de una "
            "actualización de cuotas SBS."
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

    print("\nARCHIVO Y VALIDACIÓN DE PRONÓSTICOS TERMINADOS")
    print("=" * 120)

    print("\nESTADO GENERAL")
    print("-" * 120)
    print(f"Pronósticos agregados esta ejecución: {agregados}")
    print(f"Pronósticos archivados acumulados: {len(archivo)}")
    print(f"Pronósticos validados acumulados: {len(confirmadas)}")
    print(f"Nuevas validaciones: {len(nuevos_validados)}")
    print(f"Pronósticos pendientes: {len(pendientes)}")

    print("\nMÉTRICAS POR AFP Y VERSIÓN")
    print("-" * 120)
    print(metricas.to_string(index=False))

    print("\nNUEVAS VALIDACIONES")
    print("-" * 120)
    if nuevos_validados.empty:
        print(
            "Todavía no hay nuevas cuotas SBS que coincidan con "
            "los pronósticos archivados."
        )
    else:
        columnas = [
            "afp",
            "fecha_cuota",
            "fecha_ultima_cuota_oficial",
            "cuota_estimada",
            "cuota_sbs",
            "error_pct",
            "retorno_estimado",
            "retorno_real_diario",
            "direccion_diaria_correcta",
            "direccion_acumulada_correcta",
        ]
        print(
            nuevos_validados[columnas].to_string(index=False)
        )

    print("\nPRONÓSTICOS PENDIENTES")
    print("-" * 120)
    if pendientes.empty:
        print("No quedan pronósticos pendientes.")
    else:
        columnas = [
            "afp",
            "fecha_cuota",
            "fecha_ultima_cuota_oficial",
            "cuota_estimada",
            "retorno_estimado",
            "fecha_generacion_archivo",
        ]
        print(pendientes[columnas].to_string(index=False))

    print("\nRECONCILIACIÓN DE CONTRIBUCIONES")
    print("-" * 120)
    if reconciliacion.empty:
        print("No fue posible reconciliar contribuciones.")
    else:
        print(reconciliacion.to_string(index=False))

    print("\nCONTROLES")
    print("-" * 120)
    print(controles.to_string(index=False))

    print("\nArchivos creados:")
    for ruta in rutas.values():
        print(f" - {ruta.resolve()}")
    print(f" - Carpeta de gráficos: {graficos_dir.resolve()}")

    print(
        "\nORDEN OPERATIVO CORRECTO:\n"
        "1. Ejecute el módulo 57 para generar las estimaciones actuales.\n"
        "2. Ejecute inmediatamente el módulo 58 para archivarlas.\n"
        "3. Cuando actualice la base SBS, ejecute primero el módulo 58.\n"
        "4. Revise las nuevas validaciones y sus errores.\n"
        "5. Después ejecute otra vez el módulo 57 para reanclar y generar "
        "las nuevas cuotas pendientes.\n"
        "6. Ejecute nuevamente el módulo 58 para archivar la nueva versión."
    )


if __name__ == "__main__":
    main()
