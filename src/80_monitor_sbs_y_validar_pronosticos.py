from __future__ import annotations

import argparse
import html
import re
import shutil
import subprocess
import sys
from datetime import datetime
from io import StringIO
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt


URL_SBS = (
    "https://www.sbs.gob.pe/app/spp/"
    "variablesSPP_net/PagSS/variables_spp.aspx"
)

AFPS = ["Habitat", "Integra", "Prima", "Profuturo"]

NOMBRES_AFP = {
    "HABITAT": "Habitat",
    "INTEGRA": "Integra",
    "PRIMA": "Prima",
    "PROFUTURO": "Profuturo",
}


def leer_csv(
    ruta: Path,
    obligatorio: bool = False,
) -> pd.DataFrame:
    if not ruta.exists():
        if obligatorio:
            raise FileNotFoundError(f"Falta el archivo: {ruta}")
        return pd.DataFrame()

    ultimo_error: Exception | None = None

    for encoding in ["utf-8-sig", "latin-1", "utf-8"]:
        try:
            return pd.read_csv(ruta, encoding=encoding)
        except Exception as exc:
            ultimo_error = exc

    raise RuntimeError(f"No se pudo leer {ruta}: {ultimo_error}")


def escribir_csv(
    df: pd.DataFrame,
    ruta: Path,
) -> None:
    df.to_csv(
        ruta,
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )


def numero(valor: Any) -> float:
    if pd.isna(valor):
        return np.nan

    texto = str(valor).strip()
    texto = texto.replace("\xa0", "")
    texto = texto.replace(" ", "")
    texto = texto.replace(",", "")

    match = re.search(r"-?\d+(?:\.\d+)?", texto)

    if not match:
        return np.nan

    try:
        return float(match.group(0))
    except ValueError:
        return np.nan


def normalizar_afp(valor: Any) -> str | None:
    texto = (
        str(valor)
        .strip()
        .upper()
        .replace("AFP", "")
        .strip()
    )

    for clave, nombre in NOMBRES_AFP.items():
        if clave in texto:
            return nombre

    return None


def aplanar_columnas(
    df: pd.DataFrame,
) -> pd.DataFrame:
    salida = df.copy()

    if isinstance(salida.columns, pd.MultiIndex):
        salida.columns = [
            " | ".join(
                str(x).strip()
                for x in tupla
                if str(x).strip()
                and not str(x).startswith("Unnamed")
            )
            for tupla in salida.columns
        ]
    else:
        salida.columns = [
            str(x).strip()
            for x in salida.columns
        ]

    return salida


def extraer_tabla_fecha(
    tabla_html: str,
    fecha: pd.Timestamp,
) -> list[dict[str, Any]]:
    try:
        tablas = pd.read_html(StringIO(tabla_html))
    except ValueError:
        return []

    if not tablas:
        return []

    df = aplanar_columnas(tablas[0])

    columna_afp = None

    for columna in df.columns:
        valores = df[columna].map(normalizar_afp)
        if valores.notna().sum() >= 3:
            columna_afp = columna
            break

    if columna_afp is None:
        for columna in df.columns:
            if "AFP" in columna.upper():
                columna_afp = columna
                break

    if columna_afp is None:
        return []

    # Primera opción: localizar columna explícita de Fondo 3 / Valor Cuota.
    columna_valor_f3 = None

    for columna in df.columns:
        etiqueta = (
            str(columna)
            .upper()
            .replace("Ó", "O")
            .replace("Í", "I")
        )

        if (
            "FONDO 3" in etiqueta
            and "VALOR CUOTA" in etiqueta
        ):
            columna_valor_f3 = columna
            break

    filas = []

    for _, fila in df.iterrows():
        afp = normalizar_afp(fila.get(columna_afp))

        if afp is None:
            continue

        valor_cuota = np.nan

        if columna_valor_f3 is not None:
            valor_cuota = numero(
                fila.get(columna_valor_f3)
            )

        # Respaldo posicional:
        # tras AFP vienen 12 campos:
        # F1(3), F2(3), F3(3), F0(3).
        # El valor cuota de F3 es el noveno número.
        if pd.isna(valor_cuota):
            valores = []

            for columna in df.columns:
                if columna == columna_afp:
                    continue

                valor = numero(fila.get(columna))

                if pd.notna(valor):
                    valores.append(valor)

            if len(valores) >= 9:
                valor_cuota = valores[8]

        if pd.notna(valor_cuota):
            filas.append(
                {
                    "fecha_cuota": fecha.normalize(),
                    "afp": afp,
                    "tipo_fondo": 3,
                    "cuota_sbs": float(valor_cuota),
                    "fuente": URL_SBS,
                }
            )

    return filas


def descargar_sbs() -> tuple[pd.DataFrame, str]:
    try:
        import requests
    except ImportError as exc:
        raise RuntimeError(
            "Falta requests. Ejecuta: pip install requests"
        ) from exc

    try:
        from bs4 import BeautifulSoup
    except ImportError as exc:
        raise RuntimeError(
            "Falta beautifulsoup4. Ejecuta: "
            "pip install beautifulsoup4 lxml"
        ) from exc

    respuesta = requests.get(
        URL_SBS,
        headers={
            "User-Agent": (
                "Mozilla/5.0 AFP-Fondo3-"
                "Monitor-Academico/1.0"
            )
        },
        timeout=60,
    )
    respuesta.raise_for_status()

    texto = respuesta.text
    soup = BeautifulSoup(texto, "html.parser")

    patron_fecha = re.compile(
        r"Informaci[oó]n\s+al\s+"
        r"(\d{2}/\d{2}/\d{4})",
        flags=re.IGNORECASE,
    )

    resultados = []
    tablas_usadas = set()

    for nodo in soup.find_all(
        string=patron_fecha
    ):
        coincidencia = patron_fecha.search(
            str(nodo)
        )

        if not coincidencia:
            continue

        fecha = pd.to_datetime(
            coincidencia.group(1),
            format="%d/%m/%Y",
            errors="coerce",
        )

        if pd.isna(fecha):
            continue

        # La fecha está dentro del mismo bloque de tabla que sus valores.
        # Usar find_next("table") desplazaba cada fecha hacia la tabla
        # del día anterior. Buscamos el ancestro de tabla más pequeño
        # que contenga las cuatro AFP y el Fondo 3.
        tabla = None

        for ancestro in nodo.parents:
            if getattr(ancestro, "name", None) != "table":
                continue

            contenido = ancestro.get_text(
                " ",
                strip=True,
            ).upper()

            if (
                "HABITAT" in contenido
                and "INTEGRA" in contenido
                and "PRIMA" in contenido
                and "PROFUTURO" in contenido
                and "FONDO 3" in contenido
            ):
                tabla = ancestro
                break

        if tabla is None:
            continue

        identidad = id(tabla)

        if identidad in tablas_usadas:
            continue

        tablas_usadas.add(identidad)

        resultados.extend(
            extraer_tabla_fecha(
                str(tabla),
                pd.Timestamp(fecha),
            )
        )

    # Respaldo: algunas versiones de la página pueden no enlazar
    # claramente cada texto de fecha con su tabla.
    if not resultados:
        fechas = [
            pd.to_datetime(x, format="%d/%m/%Y")
            for x in patron_fecha.findall(
                soup.get_text(" ", strip=True)
            )
        ]

        tablas_candidatas = []

        for tabla in soup.find_all("table"):
            contenido = tabla.get_text(
                " ",
                strip=True,
            ).upper()

            if (
                "HABITAT" in contenido
                and "INTEGRA" in contenido
                and "PRIMA" in contenido
                and "PROFUTURO" in contenido
            ):
                tablas_candidatas.append(tabla)

        for fecha, tabla in zip(
            fechas,
            tablas_candidatas,
        ):
            resultados.extend(
                extraer_tabla_fecha(
                    str(tabla),
                    pd.Timestamp(fecha),
                )
            )

    df = pd.DataFrame(resultados)

    if df.empty:
        raise RuntimeError(
            "La página SBS respondió, pero no se pudieron "
            "extraer los valores del Fondo 3."
        )

    df["fecha_cuota"] = pd.to_datetime(
        df["fecha_cuota"],
        errors="coerce",
    ).dt.normalize()

    df["cuota_sbs"] = pd.to_numeric(
        df["cuota_sbs"],
        errors="coerce",
    )

    df = (
        df.dropna(
            subset=[
                "fecha_cuota",
                "afp",
                "cuota_sbs",
            ]
        )
        .drop_duplicates(
            subset=[
                "fecha_cuota",
                "afp",
            ],
            keep="last",
        )
        .sort_values(
            [
                "fecha_cuota",
                "afp",
            ]
        )
        .reset_index(drop=True)
    )

    return df, texto


def actualizar_archivo_oficial(
    nuevos: pd.DataFrame,
    ruta: Path,
) -> pd.DataFrame:
    anterior = leer_csv(ruta)

    if not anterior.empty:
        anterior["fecha_cuota"] = pd.to_datetime(
            anterior["fecha_cuota"],
            errors="coerce",
        ).dt.normalize()

    combinado = pd.concat(
        [
            anterior,
            nuevos,
        ],
        ignore_index=True,
    )

    combinado = (
        combinado.drop_duplicates(
            subset=[
                "fecha_cuota",
                "afp",
            ],
            keep="last",
        )
        .sort_values(
            [
                "fecha_cuota",
                "afp",
            ]
        )
        .reset_index(drop=True)
    )

    escribir_csv(combinado, ruta)

    return combinado


def actualizar_base_modelo(
    base_ruta: Path,
    oficiales: pd.DataFrame,
    processed: Path,
) -> tuple[pd.DataFrame, int]:
    base = leer_csv(
        base_ruta,
        obligatorio=True,
    )

    base["fecha_cuota"] = pd.to_datetime(
        base["fecha_cuota"],
        errors="coerce",
    ).dt.normalize()

    base["afp"] = base["afp"].astype(str)

    existentes = set(
        zip(
            base["afp"],
            base["fecha_cuota"],
        )
    )

    nuevos_reales = oficiales[
        [
            (
                str(afp),
                pd.Timestamp(fecha),
            )
            not in existentes
            for afp, fecha in zip(
                oficiales["afp"],
                oficiales["fecha_cuota"],
            )
        ]
    ].copy()

    # Protección: el monitor no sobrescribe silenciosamente cuotas
    # históricas ya existentes. Si detecta una diferencia, la reporta
    # y conserva la base. Solo agrega fechas nuevas.
    indice_cuota = {
        (
            str(fila["afp"]),
            pd.Timestamp(fila["fecha_cuota"]),
        ): float(fila["cuota_sbs"])
        for _, fila in oficiales.iterrows()
    }

    cambios = 0
    discrepancias = []

    for _, fila in base.iterrows():
        clave = (
            str(fila["afp"]),
            pd.Timestamp(fila["fecha_cuota"]),
        )

        if clave not in indice_cuota:
            continue

        nuevo_valor = indice_cuota[clave]
        anterior = pd.to_numeric(
            pd.Series([fila.get("cuota_sbs")]),
            errors="coerce",
        ).iloc[0]

        if (
            pd.notna(anterior)
            and not np.isclose(
                float(anterior),
                nuevo_valor,
                rtol=0,
                atol=1e-8,
            )
        ):
            discrepancias.append(
                {
                    "afp": clave[0],
                    "fecha_cuota": clave[1],
                    "cuota_base": float(anterior),
                    "cuota_web_sbs": nuevo_valor,
                    "diferencia": nuevo_valor - float(anterior),
                }
            )

    if discrepancias:
        ruta_discrepancias = (
            processed
            / "ca0001_modelo80_discrepancias_historicas.csv"
        )
        escribir_csv(
            pd.DataFrame(discrepancias),
            ruta_discrepancias,
        )
        print(
            "\nADVERTENCIA: se detectaron diferencias con fechas "
            "ya existentes. No se sobrescribieron automáticamente."
        )
        print(
            f"Revisa: {ruta_discrepancias.resolve()}"
        )

    if not nuevos_reales.empty:
        columnas = list(base.columns)
        filas_nuevas = []

        for _, fila in nuevos_reales.iterrows():
            nueva = {
                columna: np.nan
                for columna in columnas
            }

            nueva["afp"] = fila["afp"]
            nueva["fecha_cuota"] = fila["fecha_cuota"]
            nueva["cuota_sbs"] = fila["cuota_sbs"]
            filas_nuevas.append(nueva)

        base = pd.concat(
            [
                base,
                pd.DataFrame(filas_nuevas),
            ],
            ignore_index=True,
        )

        cambios += len(filas_nuevas)

    if cambios > 0:
        marca = datetime.now().strftime(
            "%Y%m%d_%H%M%S"
        )

        respaldo = (
            processed
            / f"ca0001_modelo56_base_alineada_BACKUP_{marca}.csv"
        )

        shutil.copy2(
            base_ruta,
            respaldo,
        )

        base = base.sort_values(
            [
                "afp",
                "fecha_cuota",
            ]
        ).reset_index(drop=True)

        base["cuota_sbs"] = pd.to_numeric(
            base["cuota_sbs"],
            errors="coerce",
        )

        base["retorno_cuota"] = (
            base.groupby(
                "afp",
                sort=False,
            )["cuota_sbs"]
            .pct_change(
                fill_method=None
            )
        )

        escribir_csv(
            base,
            base_ruta,
        )

    return base, cambios


def evaluar_pronosticos(
    oficiales: pd.DataFrame,
    pronosticos_ruta: Path,
    evaluacion_ruta: Path,
) -> pd.DataFrame:
    pronosticos = leer_csv(
        pronosticos_ruta
    )

    anterior = leer_csv(
        evaluacion_ruta
    )

    if pronosticos.empty:
        return anterior

    pronosticos["fecha_objetivo"] = pd.to_datetime(
        pronosticos["fecha_objetivo"],
        errors="coerce",
    ).dt.normalize()

    pronosticos[
        "fecha_ultima_cuota_oficial"
    ] = pd.to_datetime(
        pronosticos[
            "fecha_ultima_cuota_oficial"
        ],
        errors="coerce",
    ).dt.normalize()

    oficiales_eval = oficiales.rename(
        columns={
            "cuota_sbs": "cuota_real_sbs"
        }
    )[
        [
            "fecha_cuota",
            "afp",
            "cuota_real_sbs",
        ]
    ]

    unido = pronosticos.merge(
        oficiales_eval,
        left_on=[
            "fecha_objetivo",
            "afp",
        ],
        right_on=[
            "fecha_cuota",
            "afp",
        ],
        how="inner",
    )

    if unido.empty:
        return anterior

    unido["desviacion_cuota"] = (
        unido["cuota_estimada"]
        - unido["cuota_real_sbs"]
    )

    unido["error_pct"] = (
        unido["cuota_estimada"]
        / unido["cuota_real_sbs"]
        - 1.0
    )

    unido["error_abs_pct"] = unido[
        "error_pct"
    ].abs()

    unido["retorno_real_desde_ancla"] = (
        unido["cuota_real_sbs"]
        / unido["cuota_ultima_oficial"]
        - 1.0
    )

    unido["direccion_real"] = np.where(
        unido[
            "retorno_real_desde_ancla"
        ].gt(0),
        "SUBE",
        np.where(
            unido[
                "retorno_real_desde_ancla"
            ].lt(0),
            "BAJA",
            "SIN_CAMBIO",
        ),
    )

    unido["acierto_direccion"] = (
        unido["direccion_estimada"]
        == unido["direccion_real"]
    )

    unido["fecha_evaluacion"] = (
        pd.Timestamp.now().normalize()
    )

    columnas = [
        "run_id",
        "afp",
        "fecha_objetivo",
        "fecha_ultima_cuota_oficial",
        "cuota_ultima_oficial",
        "cuota_estimada",
        "cuota_real_sbs",
        "desviacion_cuota",
        "error_pct",
        "error_abs_pct",
        "retorno_acumulado_estimado",
        "retorno_real_desde_ancla",
        "direccion_estimada",
        "direccion_real",
        "acierto_direccion",
        "cobertura_factores_pct",
        "nivel_cobertura_datos",
        "fecha_evaluacion",
    ]

    columnas = [
        c
        for c in columnas
        if c in unido.columns
    ]

    nuevos = unido[columnas].copy()

    if not anterior.empty:
        anterior["fecha_objetivo"] = pd.to_datetime(
            anterior["fecha_objetivo"],
            errors="coerce",
        ).dt.normalize()

    combinado = pd.concat(
        [
            anterior,
            nuevos,
        ],
        ignore_index=True,
    )

    combinado = (
        combinado.drop_duplicates(
            subset=[
                "afp",
                "fecha_objetivo",
            ],
            keep="first",
        )
        .sort_values(
            [
                "fecha_objetivo",
                "afp",
            ]
        )
        .reset_index(drop=True)
    )

    escribir_csv(
        combinado,
        evaluacion_ruta,
    )

    return combinado


def calcular_metricas(
    evaluacion: pd.DataFrame,
) -> pd.DataFrame:
    if evaluacion.empty:
        return pd.DataFrame(
            columns=[
                "afp",
                "n_pronosticos_evaluados",
                "mape_prospectivo_pct",
                "sesgo_pct",
                "p90_error_abs_pct",
                "error_maximo_abs_pct",
                "acierto_direccion_pct",
                "pearson_retorno",
            ]
        )

    filas = []

    for afp in AFPS:
        x = evaluacion[
            evaluacion["afp"]
            .astype(str)
            .eq(afp)
        ].copy()

        if x.empty:
            filas.append(
                {
                    "afp": afp,
                    "n_pronosticos_evaluados": 0,
                    "mape_prospectivo_pct": np.nan,
                    "sesgo_pct": np.nan,
                    "p90_error_abs_pct": np.nan,
                    "error_maximo_abs_pct": np.nan,
                    "acierto_direccion_pct": np.nan,
                    "pearson_retorno": np.nan,
                }
            )
            continue

        pearson = np.nan

        if (
            len(x) >= 3
            and x[
                "retorno_acumulado_estimado"
            ].std() > 0
            and x[
                "retorno_real_desde_ancla"
            ].std() > 0
        ):
            pearson = x[
                "retorno_acumulado_estimado"
            ].corr(
                x[
                    "retorno_real_desde_ancla"
                ]
            )

        filas.append(
            {
                "afp": afp,
                "n_pronosticos_evaluados": int(
                    len(x)
                ),
                "mape_prospectivo_pct": float(
                    x["error_abs_pct"].mean()
                    * 100.0
                ),
                "sesgo_pct": float(
                    x["error_pct"].mean()
                    * 100.0
                ),
                "p90_error_abs_pct": float(
                    x["error_abs_pct"]
                    .quantile(0.90)
                    * 100.0
                ),
                "error_maximo_abs_pct": float(
                    x["error_abs_pct"].max()
                    * 100.0
                ),
                "acierto_direccion_pct": float(
                    x["acierto_direccion"]
                    .astype(float)
                    .mean()
                    * 100.0
                ),
                "pearson_retorno": (
                    float(pearson)
                    if pd.notna(pearson)
                    else np.nan
                ),
            }
        )

    return pd.DataFrame(filas)


def crear_graficos(
    evaluacion: pd.DataFrame,
    carpeta: Path,
) -> None:
    carpeta.mkdir(
        parents=True,
        exist_ok=True,
    )

    if evaluacion.empty:
        return

    for afp in AFPS:
        x = evaluacion[
            evaluacion["afp"]
            .astype(str)
            .eq(afp)
        ].copy()

        if x.empty:
            continue

        x["fecha_objetivo"] = pd.to_datetime(
            x["fecha_objetivo"],
            errors="coerce",
        )

        x = x.sort_values(
            "fecha_objetivo"
        )

        plt.figure(figsize=(12, 5))
        plt.plot(
            x["fecha_objetivo"],
            x["cuota_real_sbs"],
            marker="o",
            label="Cuota real SBS",
        )
        plt.plot(
            x["fecha_objetivo"],
            x["cuota_estimada"],
            marker="o",
            label="Primer pronóstico congelado",
        )
        plt.title(
            f"Validación prospectiva — {afp}"
        )
        plt.xlabel("Fecha objetivo")
        plt.ylabel("Valor cuota")
        plt.legend()
        plt.grid(
            True,
            alpha=0.3,
        )
        plt.tight_layout()
        plt.savefig(
            carpeta
            / f"01_real_vs_pronostico_{afp.lower()}.png",
            dpi=170,
            bbox_inches="tight",
        )
        plt.close()



def preparar_pronosticos_pendientes(
    pronosticos_ruta: Path,
    oficiales: pd.DataFrame,
) -> pd.DataFrame:
    pronosticos = leer_csv(pronosticos_ruta)

    if pronosticos.empty:
        return pd.DataFrame()

    pronosticos["fecha_objetivo"] = pd.to_datetime(
        pronosticos["fecha_objetivo"],
        errors="coerce",
    ).dt.normalize()

    oficiales_claves = oficiales[
        [
            "fecha_cuota",
            "afp",
        ]
    ].drop_duplicates().copy()

    pendientes = pronosticos.merge(
        oficiales_claves,
        left_on=[
            "fecha_objetivo",
            "afp",
        ],
        right_on=[
            "fecha_cuota",
            "afp",
        ],
        how="left",
        indicator=True,
    )

    pendientes = pendientes[
        pendientes["_merge"].eq("left_only")
    ].copy()

    if pendientes.empty:
        return pendientes

    pendientes["estado_pronostico"] = (
        "ESPERANDO PUBLICACIÓN SBS"
    )

    # Convierte el retorno acumulado a porcentaje para mostrarlo.
    if "retorno_acumulado_estimado" in pendientes.columns:
        pendientes[
            "retorno_acumulado_estimado_pct"
        ] = (
            pd.to_numeric(
                pendientes[
                    "retorno_acumulado_estimado"
                ],
                errors="coerce",
            )
            * 100.0
        )

    columnas = [
        "afp",
        "fecha_objetivo",
        "fecha_ultima_cuota_oficial",
        "cuota_ultima_oficial",
        "cuota_estimada",
        "retorno_acumulado_estimado_pct",
        "direccion_estimada",
        "cobertura_factores_pct",
        "nivel_cobertura_datos",
        "estado_pronostico",
        "run_id",
    ]

    columnas = [
        c
        for c in columnas
        if c in pendientes.columns
    ]

    return (
        pendientes[columnas]
        .sort_values(
            [
                "fecha_objetivo",
                "afp",
            ],
            ascending=[
                False,
                True,
            ],
        )
        .reset_index(drop=True)
    )

def crear_dashboard(
    pendientes: pd.DataFrame,
    evaluacion: pd.DataFrame,
    metricas: pd.DataFrame,
    oficiales: pd.DataFrame,
    ruta: Path,
    carpeta_graficos: Path,
) -> None:
    ultima_sbs = (
        oficiales["fecha_cuota"].max()
        if not oficiales.empty
        else pd.NaT
    )

    def tabla_html(
        df: pd.DataFrame,
        mensaje_vacio: str,
    ) -> str:
        if df.empty:
            return f"<p>{html.escape(mensaje_vacio)}</p>"

        return df.to_html(
            index=False,
            border=0,
            classes="tabla",
            float_format=lambda x: f"{x:.6f}",
        )

    pendientes_mostrar = pendientes.copy()
    metricas_mostrar = metricas.copy()
    evaluacion_mostrar = evaluacion.copy()

    if not pendientes_mostrar.empty:
        renombrar_pendientes = {
            "afp": "AFP",
            "fecha_objetivo": "Fecha pronosticada",
            "fecha_ultima_cuota_oficial": "Ancla SBS",
            "cuota_ultima_oficial": "Última cuota oficial",
            "cuota_estimada": "Cuota estimada",
            "retorno_acumulado_estimado_pct": "Variación estimada (%)",
            "direccion_estimada": "Dirección",
            "cobertura_factores_pct": "Cobertura (%)",
            "nivel_cobertura_datos": "Nivel datos",
            "estado_pronostico": "Estado",
        }

        columnas_pendientes = [
            "afp",
            "fecha_objetivo",
            "fecha_ultima_cuota_oficial",
            "cuota_ultima_oficial",
            "cuota_estimada",
            "retorno_acumulado_estimado_pct",
            "direccion_estimada",
            "cobertura_factores_pct",
            "nivel_cobertura_datos",
            "estado_pronostico",
        ]

        pendientes_mostrar = (
            pendientes_mostrar[
                [
                    c
                    for c in columnas_pendientes
                    if c in pendientes_mostrar.columns
                ]
            ]
            .rename(
                columns=renombrar_pendientes
            )
        )

    if not evaluacion_mostrar.empty:
        evaluacion_mostrar[
            "error_pct"
        ] = evaluacion_mostrar[
            "error_pct"
        ] * 100.0

        evaluacion_mostrar[
            "error_abs_pct"
        ] = evaluacion_mostrar[
            "error_abs_pct"
        ] * 100.0

        columnas_eval = [
            "afp",
            "fecha_objetivo",
            "cuota_estimada",
            "cuota_real_sbs",
            "desviacion_cuota",
            "error_pct",
            "error_abs_pct",
            "direccion_estimada",
            "direccion_real",
            "acierto_direccion",
        ]

        renombrar_eval = {
            "afp": "AFP",
            "fecha_objetivo": "Fecha",
            "cuota_estimada": "Cuota estimada",
            "cuota_real_sbs": "Cuota real SBS",
            "desviacion_cuota": "Desviación cuota",
            "error_pct": "Error (%)",
            "error_abs_pct": "Error absoluto (%)",
            "direccion_estimada": "Dirección estimada",
            "direccion_real": "Dirección real",
            "acierto_direccion": "¿Acertó dirección?",
        }

        evaluacion_mostrar = (
            evaluacion_mostrar[
                [
                    c
                    for c in columnas_eval
                    if c
                    in evaluacion_mostrar.columns
                ]
            ]
            .rename(
                columns=renombrar_eval
            )
            .sort_values(
                [
                    "Fecha",
                    "AFP",
                ],
                ascending=[
                    False,
                    True,
                ],
            )
        )

    imagenes = []

    for afp in AFPS:
        nombre = (
            f"01_real_vs_pronostico_"
            f"{afp.lower()}.png"
        )

        ruta_imagen = carpeta_graficos / nombre

        if ruta_imagen.exists():
            imagenes.append(
                f"""
                <section class="grafico">
                  <h3>{html.escape(afp)}</h3>
                  <img src="graficos_modelo80/{nombre}"
                       alt="Real vs pronóstico {html.escape(afp)}">
                </section>
                """
            )

    contenido = f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta http-equiv="refresh" content="300">
<title>Monitor AFP Fondo 3</title>
<style>
body {{
  font-family: Arial, sans-serif;
  margin: 24px;
  background: #f5f6f8;
  color: #1f2937;
}}
h1, h2, h3 {{ color: #17365d; }}
.tarjeta {{
  background: white;
  padding: 18px;
  margin-bottom: 18px;
  border-radius: 10px;
  box-shadow: 0 2px 8px rgba(0,0,0,.08);
}}
.tabla {{
  border-collapse: collapse;
  width: 100%;
  background: white;
}}
.tabla th, .tabla td {{
  padding: 8px;
  border-bottom: 1px solid #ddd;
  text-align: right;
}}
.tabla th:first-child, .tabla td:first-child {{
  text-align: left;
}}
.grafico img {{
  max-width: 100%;
  background: white;
  border-radius: 8px;
}}
.aviso {{
  background: #fff7d6;
  border-left: 5px solid #d8a500;
  padding: 12px;
}}
.pendiente {{
  border-left: 6px solid #2563eb;
}}
</style>
</head>
<body>
<h1>Monitor prospectivo AFP Fondo 3</h1>

<div class="tarjeta">
  <strong>Última fecha detectada en SBS:</strong>
  {html.escape(str(ultima_sbs.date()) if pd.notna(ultima_sbs) else "Sin datos")}
  <br>
  <strong>Última actualización local:</strong>
  {html.escape(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))}
</div>

<div class="aviso">
La estimación es un resultado estadístico anticipado.
El valor oficial es el publicado por la SBS.
</div>

<div class="tarjeta pendiente">
<h2>Pronósticos vigentes pendientes de publicación SBS</h2>
<p>
Estos son los resultados que el modelo ya dejó congelados.
Cuando la SBS publique la misma fecha, pasarán automáticamente
a la tabla de comparación.
</p>
{tabla_html(
    pendientes_mostrar,
    "No existen pronósticos pendientes en este momento."
)}
</div>

<div class="tarjeta">
<h2>Pronóstico congelado frente a cuota real SBS</h2>
{tabla_html(
    evaluacion_mostrar,
    "Todavía no existen pronósticos cuya fecha ya haya sido publicada por la SBS."
)}
</div>

<div class="tarjeta">
<h2>Métricas prospectivas acumuladas</h2>
{tabla_html(
    metricas_mostrar,
    "Las métricas aparecerán después de comparar al menos un pronóstico con su cuota oficial."
)}
</div>

<div class="tarjeta">
<h2>Gráficos de validación prospectiva</h2>
{''.join(imagenes) if imagenes else '<p>Los gráficos aparecerán cuando exista al menos una cuota publicada que coincida con un pronóstico.</p>'}
</div>
</body>
</html>
"""

    ruta.write_text(
        contenido,
        encoding="utf-8",
    )


def ejecutar_modelo79(
    raiz: Path,
) -> int:
    ruta = (
        raiz
        / "src"
        / "79_congelar_modelo_y_estimar_prospectivamente.py"
    )

    if not ruta.exists():
        print(
            "No se encontró el módulo 79; "
            "no se generó un nuevo pronóstico."
        )
        return 1

    proceso = subprocess.run(
        [
            sys.executable,
            str(ruta),
        ],
        cwd=str(raiz),
        check=False,
    )

    return int(
        proceso.returncode
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Comprueba la publicación SBS, actualiza la base, "
            "evalúa pronósticos congelados y genera dashboard."
        )
    )

    parser.add_argument(
        "--pronosticar",
        action="store_true",
        help=(
            "Después de actualizar SBS, ejecuta el módulo 79 "
            "para generar nuevos pronósticos."
        ),
    )

    args = parser.parse_args()

    raiz = Path(
        __file__
    ).resolve().parents[1]

    processed = (
        raiz
        / "data"
        / "processed"
    )

    processed.mkdir(
        parents=True,
        exist_ok=True,
    )

    rutas = {
        "oficial": (
            processed
            / "ca0001_modelo80_sbs_oficial_detectado.csv"
        ),
        "base": (
            processed
            / "ca0001_modelo56_base_alineada.csv"
        ),
        "pronosticos": (
            processed
            / "ca0001_modelo79_primer_pronostico_congelado.csv"
        ),
        "evaluacion": (
            processed
            / "ca0001_modelo80_evaluacion_prospectiva.csv"
        ),
        "metricas": (
            processed
            / "ca0001_modelo80_metricas_prospectivas.csv"
        ),
        "dashboard": (
            processed
            / "ca0001_modelo80_dashboard.html"
        ),
        "html_sbs": (
            processed
            / "ca0001_modelo80_ultima_respuesta_sbs.html"
        ),
    }

    graficos = (
        processed
        / "graficos_modelo80"
    )

    print(
        "\nMÓDULO 80 — MONITOR SBS Y VALIDACIÓN PROSPECTIVA"
    )
    print("=" * 160)

    oficiales_web, html_sbs = descargar_sbs()

    rutas["html_sbs"].write_text(
        html_sbs,
        encoding="utf-8",
    )

    oficiales = actualizar_archivo_oficial(
        oficiales_web,
        rutas["oficial"],
    )

    _, cambios = actualizar_base_modelo(
        rutas["base"],
        oficiales_web,
        processed,
    )

    # Cuando se solicita pronosticar, primero se actualizan las
    # estimaciones. Así el tablero que se crea en esta misma ejecución
    # ya muestra los pronósticos nuevos.
    pendientes = preparar_pronosticos_pendientes(
        rutas["pronosticos"],
        oficiales,
    )

    evaluacion = evaluar_pronosticos(
        oficiales,
        rutas["pronosticos"],
        rutas["evaluacion"],
    )

    metricas = calcular_metricas(
        evaluacion
    )

    escribir_csv(
        metricas,
        rutas["metricas"],
    )

    crear_graficos(
        evaluacion,
        graficos,
    )

    crear_dashboard(
        pendientes,
        evaluacion,
        metricas,
        oficiales,
        rutas["dashboard"],
        graficos,
    )

    ultima_fecha = oficiales_web[
        "fecha_cuota"
    ].max()

    print(
        f"Última fecha SBS detectada: "
        f"{ultima_fecha.date()}"
    )
    print(
        f"Registros nuevos o corregidos en la base: "
        f"{cambios}"
    )

    print(
        "\nÚLTIMOS VALORES SBS FONDO 3"
    )
    print("-" * 160)

    print(
        oficiales_web[
            oficiales_web["fecha_cuota"]
            .eq(ultima_fecha)
        ][
            [
                "fecha_cuota",
                "afp",
                "cuota_sbs",
            ]
        ].to_string(
            index=False
        )
    )

    print(
        "\nMÉTRICAS PROSPECTIVAS"
    )
    print("-" * 160)

    print(
        metricas.to_string(
            index=False
        )
    )

    if args.pronosticar:
        print(
            "\nEjecutando módulo 79 para generar "
            "nuevos pronósticos..."
        )

        codigo = ejecutar_modelo79(
            raiz
        )

        print(
            f"Módulo 79 terminó con código: {codigo}"
        )

    print(
        "\nARCHIVOS PRINCIPALES"
    )
    print("-" * 160)

    for clave in [
        "oficial",
        "evaluacion",
        "metricas",
        "dashboard",
    ]:
        print(
            f" - {rutas[clave].resolve()}"
        )

    print(
        "\nPara abrir el tablero en PowerShell:\n"
        'Start-Process ".\\data\\processed\\'
        'ca0001_modelo80_dashboard.html"'
    )


if __name__ == "__main__":
    main()
