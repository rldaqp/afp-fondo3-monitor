from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import time
import unicodedata
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


SBS_URL = (
    "https://www.sbs.gob.pe/app/spp/"
    "variablesSPP_net/PagSS/variables_spp.aspx"
)

TICKERS = {
    "ret_COPX": "COPX",
    "ret_EPU": "EPU",
    "ret_XLB": "XLB",
    "ret_IDX_VIX": "^VIX",
}

AFP_NORMALIZADA = {
    "HABITAT": "Habitat",
    "INTEGRA": "Integra",
    "PRIMA": "Prima",
    "PROFUTURO": "Profuturo",
}

AFP_ORDEN = ["Habitat", "Integra", "Prima", "Profuturo"]


class ExtractorTextoHTML(HTMLParser):
    """Convierte el HTML de la SBS en líneas de texto sin depender de bs4."""

    ETIQUETAS_BLOQUE = {
        "br",
        "p",
        "div",
        "tr",
        "td",
        "th",
        "table",
        "li",
        "h1",
        "h2",
        "h3",
        "h4",
        "span",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.partes: list[str] = []
        self.ignorar = 0

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        tag = tag.lower()

        if tag in {"script", "style", "noscript"}:
            self.ignorar += 1
            return

        if self.ignorar == 0 and tag in self.ETIQUETAS_BLOQUE:
            self.partes.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()

        if tag in {"script", "style", "noscript"}:
            self.ignorar = max(0, self.ignorar - 1)
            return

        if self.ignorar == 0 and tag in self.ETIQUETAS_BLOQUE:
            self.partes.append("\n")

    def handle_data(self, data: str) -> None:
        if self.ignorar == 0 and data:
            self.partes.append(data)

    def obtener_lineas(self) -> list[str]:
        texto = "".join(self.partes)
        lineas = []

        for fragmento in re.split(r"[\r\n]+", texto):
            limpio = re.sub(r"\s+", " ", fragmento).strip()
            if limpio:
                lineas.append(limpio)

        return lineas


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

    for clave, nombre in AFP_NORMALIZADA.items():
        if clave in limpio:
            return nombre

    return None


def numero_ingles(texto: str) -> float | None:
    limpio = (
        str(texto)
        .strip()
        .replace("\xa0", "")
        .replace(" ", "")
        .replace(",", "")
    )

    if not re.fullmatch(r"-?\d+(?:\.\d+)?", limpio):
        return None

    try:
        return float(limpio)
    except ValueError:
        return None


def importar_requests():
    try:
        import requests  # type: ignore
    except ImportError as error:
        raise RuntimeError(
            "Falta requests. Instale con: python -m pip install requests"
        ) from error

    return requests


def descargar_html_sbs(
    ruta_snapshot: Path,
    reintentos: int = 3,
) -> str:
    requests = importar_requests()
    ultimo_error: Exception | None = None

    for intento in range(1, reintentos + 1):
        try:
            respuesta = requests.get(
                SBS_URL,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 Chrome/149 Safari/537.36"
                    )
                },
                timeout=40,
            )
            respuesta.raise_for_status()
            respuesta.encoding = (
                respuesta.apparent_encoding
                or respuesta.encoding
                or "utf-8"
            )
            html = respuesta.text

            if "Información" not in html and "Informaci" not in html:
                raise RuntimeError(
                    "La respuesta SBS no contiene el texto esperado."
                )

            ruta_snapshot.write_text(
                html,
                encoding="utf-8",
                errors="replace",
            )
            return html

        except Exception as error:
            ultimo_error = error
            if intento < reintentos:
                time.sleep(2 * intento)

    raise RuntimeError(
        f"No se pudo descargar la página SBS: {ultimo_error}"
    )


def extraer_fondo3_sbs(html: str) -> pd.DataFrame:
    parser = ExtractorTextoHTML()
    parser.feed(html)
    lineas = parser.obtener_lineas()

    patron_fecha = re.compile(
        r"Informaci[oó]n\s+al\s+(\d{2}/\d{2}/\d{4})",
        flags=re.IGNORECASE,
    )

    indices_fecha: list[tuple[int, pd.Timestamp]] = []

    for indice, linea in enumerate(lineas):
        coincidencia = patron_fecha.search(linea)
        if coincidencia:
            fecha = pd.to_datetime(
                coincidencia.group(1),
                format="%d/%m/%Y",
                errors="coerce",
            )
            if pd.notna(fecha):
                indices_fecha.append((indice, pd.Timestamp(fecha)))

    if not indices_fecha:
        raise RuntimeError(
            "No se identificaron bloques 'Información al dd/mm/aaaa' "
            "en la página SBS."
        )

    registros: list[dict[str, object]] = []

    for posicion, (inicio, fecha) in enumerate(indices_fecha):
        fin = (
            indices_fecha[posicion + 1][0]
            if posicion + 1 < len(indices_fecha)
            else len(lineas)
        )
        bloque = lineas[inicio + 1 : fin]

        posiciones_afp: list[tuple[int, str]] = []

        for indice, linea in enumerate(bloque):
            normalizado = limpiar_nombre(linea)

            if normalizado in AFP_NORMALIZADA:
                posiciones_afp.append(
                    (
                        indice,
                        AFP_NORMALIZADA[normalizado],
                    )
                )

        for posicion_afp, (inicio_afp, afp) in enumerate(
            posiciones_afp
        ):
            fin_afp = (
                posiciones_afp[posicion_afp + 1][0]
                if posicion_afp + 1 < len(posiciones_afp)
                else len(bloque)
            )

            numeros: list[float] = []

            for linea in bloque[inicio_afp + 1 : fin_afp]:
                valor = numero_ingles(linea)
                if valor is not None:
                    numeros.append(valor)

            # Orden oficial observado:
            # Fondo 1: Cuotas, Fondo, Valor cuota
            # Fondo 2: Cuotas, Fondo, Valor cuota
            # Fondo 3: Cuotas, Fondo, Valor cuota
            # Fondo 0: Cuotas, Fondo, Valor cuota
            if len(numeros) < 9:
                continue

            registros.append(
                {
                    "fecha": fecha,
                    "afp": afp,
                    "valor_cuota": float(numeros[8]),
                    "fuente": "SBS_variables_SPP",
                }
            )

    resultado = pd.DataFrame(registros)

    if resultado.empty:
        raise RuntimeError(
            "La página SBS fue descargada, pero no se extrajeron "
            "valores cuota de Fondo 3."
        )

    resultado = (
        resultado.drop_duplicates(
            subset=["fecha", "afp"],
            keep="first",
        )
        .sort_values(["fecha", "afp"])
        .reset_index(drop=True)
    )

    control = (
        resultado.groupby("fecha")["afp"]
        .nunique()
        .reset_index(name="numero_afp")
    )

    fechas_incompletas = control[
        control["numero_afp"].ne(4)
    ]

    if not fechas_incompletas.empty:
        fechas = ", ".join(
            fecha.strftime("%Y-%m-%d")
            for fecha in fechas_incompletas["fecha"]
        )
        raise RuntimeError(
            "La extracción SBS produjo fechas incompletas: "
            f"{fechas}"
        )

    return resultado


def respaldar_archivo(
    ruta: Path,
    directorio_backup: Path,
) -> Path | None:
    if not ruta.exists():
        return None

    directorio_backup.mkdir(parents=True, exist_ok=True)
    destino = directorio_backup / ruta.name
    shutil.copy2(ruta, destino)
    return destino


def actualizar_base_sbs(
    processed: Path,
    datos_web: pd.DataFrame,
    directorio_backup: Path,
    solo_auditar: bool,
) -> tuple[pd.DataFrame, dict[str, object]]:
    ruta = processed / "sbs_fondo3_base_maestra.csv"

    if not ruta.exists():
        raise FileNotFoundError(f"No existe la base SBS: {ruta}")

    existente = leer_csv_flexible(ruta)

    fecha_col = detectar_columna(
        existente.columns,
        {"fecha", "date", "fecha_cuota", "fecha_valor_cuota"},
    )
    afp_col = detectar_columna(
        existente.columns,
        {"afp", "administradora", "nombre_afp"},
    )
    cuota_col = detectar_columna(
        existente.columns,
        {"valor_cuota", "valor_de_la_cuota", "cuota", "valor"},
    )

    if fecha_col is None or afp_col is None or cuota_col is None:
        raise ValueError(
            "No se identificaron fecha, AFP y valor cuota "
            "en sbs_fondo3_base_maestra.csv."
        )

    base = existente.copy()
    base[fecha_col] = pd.to_datetime(
        base[fecha_col],
        errors="coerce",
    )
    base["_afp_normalizada"] = base[afp_col].map(normalizar_afp)
    base[cuota_col] = pd.to_numeric(
        base[cuota_col],
        errors="coerce",
    )

    antes_filas = len(base)
    antes_fecha = base[fecha_col].max()

    nuevas = pd.DataFrame(
        {
            fecha_col: datos_web["fecha"],
            afp_col: datos_web["afp"],
            cuota_col: datos_web["valor_cuota"],
            "_afp_normalizada": datos_web["afp"],
        }
    )

    for columna in base.columns:
        if columna not in nuevas.columns:
            nuevas[columna] = np.nan

    nuevas = nuevas[base.columns]

    combinado = pd.concat(
        [base, nuevas],
        ignore_index=True,
        sort=False,
    )

    combinado["_prioridad_web"] = (
        combinado.index >= len(base)
    ).astype(int)

    combinado = (
        combinado.sort_values(
            [
                fecha_col,
                "_afp_normalizada",
                "_prioridad_web",
            ]
        )
        .drop_duplicates(
            subset=[fecha_col, "_afp_normalizada"],
            keep="last",
        )
        .drop(columns=["_prioridad_web"])
        .sort_values([fecha_col, "_afp_normalizada"])
        .reset_index(drop=True)
    )

    despues_filas = len(combinado)
    despues_fecha = combinado[fecha_col].max()

    claves_antes = set(
        zip(
            base[fecha_col],
            base["_afp_normalizada"],
        )
    )
    claves_web = set(
        zip(
            datos_web["fecha"],
            datos_web["afp"],
        )
    )
    nuevas_claves = claves_web - claves_antes

    combinado_salida = combinado.drop(
        columns=["_afp_normalizada"]
    )

    if not solo_auditar:
        respaldar_archivo(ruta, directorio_backup)
        combinado_salida.to_csv(
            ruta,
            index=False,
            encoding="utf-8-sig",
            date_format="%Y-%m-%d",
        )

    detalle = {
        "archivo": ruta.name,
        "fecha_maxima_antes": (
            str(pd.Timestamp(antes_fecha).date())
            if pd.notna(antes_fecha)
            else None
        ),
        "fecha_maxima_web": str(
            pd.Timestamp(datos_web["fecha"].max()).date()
        ),
        "fecha_maxima_despues": (
            str(pd.Timestamp(despues_fecha).date())
            if pd.notna(despues_fecha)
            else None
        ),
        "filas_antes": antes_filas,
        "filas_despues": despues_filas,
        "nuevas_claves_fecha_afp": len(nuevas_claves),
        "modo": "AUDITORIA" if solo_auditar else "ACTUALIZADO",
    }

    return combinado_salida, detalle


def importar_yfinance():
    try:
        import yfinance as yf  # type: ignore
    except ImportError as error:
        raise RuntimeError(
            "Falta yfinance. Instale con: "
            "python -m pip install --upgrade yfinance"
        ) from error

    return yf


def extraer_cierre_yfinance(
    descarga: pd.DataFrame,
    ticker: str,
) -> pd.Series:
    if descarga.empty:
        return pd.Series(dtype=float)

    if isinstance(descarga.columns, pd.MultiIndex):
        candidatos = [
            (ticker, "Close"),
            ("Close", ticker),
        ]

        for candidato in candidatos:
            if candidato in descarga.columns:
                serie = descarga[candidato]
                return pd.to_numeric(
                    serie,
                    errors="coerce",
                ).dropna()

        # Compatibilidad con variaciones de nombres.
        for columna in descarga.columns:
            partes = [str(valor) for valor in columna]
            if ticker in partes and "Close" in partes:
                return pd.to_numeric(
                    descarga[columna],
                    errors="coerce",
                ).dropna()

    if "Close" in descarga.columns:
        return pd.to_numeric(
            descarga["Close"],
            errors="coerce",
        ).dropna()

    raise RuntimeError(
        f"No se identificó el cierre ajustado para {ticker}."
    )


def detectar_semantica_serie(
    serie: pd.Series,
    nombre: str,
) -> str:
    valores = pd.to_numeric(
        serie,
        errors="coerce",
    ).dropna()

    if len(valores) < 30:
        return (
            "retorno"
            if limpiar_nombre(nombre).startswith("RET")
            else "nivel"
        )

    fraccion_negativa = float((valores < 0).mean())
    fraccion_positiva = float((valores > 0).mean())
    p99_abs = float(valores.abs().quantile(0.99))

    if (
        fraccion_negativa > 0.05
        and fraccion_positiva > 0.05
        and p99_abs <= 0.50
    ):
        return "retorno"

    return "nivel"


def descargar_mercados(
    fecha_inicio: pd.Timestamp,
    fecha_fin_exclusiva: pd.Timestamp,
    ruta_snapshot: Path,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    yf = importar_yfinance()
    tickers = list(TICKERS.values())

    descarga = yf.download(
        tickers=tickers,
        start=fecha_inicio.strftime("%Y-%m-%d"),
        end=fecha_fin_exclusiva.strftime("%Y-%m-%d"),
        interval="1d",
        auto_adjust=True,
        repair=True,
        actions=False,
        progress=False,
        threads=True,
        group_by="ticker",
        multi_level_index=True,
        timeout=30,
    )

    if descarga is None or descarga.empty:
        raise RuntimeError(
            "yfinance no devolvió observaciones para los tickers."
        )

    descarga.to_csv(
        ruta_snapshot,
        encoding="utf-8-sig",
    )

    niveles = pd.DataFrame()
    controles = []

    for columna_destino, ticker in TICKERS.items():
        serie = extraer_cierre_yfinance(descarga, ticker)
        serie.index = pd.to_datetime(
            serie.index,
            errors="coerce",
        ).tz_localize(None)
        serie = serie[
            ~serie.index.isna()
        ].sort_index()

        niveles[columna_destino] = serie

        controles.append(
            {
                "factor": columna_destino,
                "ticker": ticker,
                "observaciones_descargadas": int(serie.notna().sum()),
                "fecha_minima_descargada": (
                    serie.index.min()
                    if not serie.empty
                    else pd.NaT
                ),
                "fecha_maxima_descargada": (
                    serie.index.max()
                    if not serie.empty
                    else pd.NaT
                ),
                "ultimo_nivel": (
                    float(serie.iloc[-1])
                    if not serie.empty
                    else np.nan
                ),
            }
        )

    niveles.index.name = "fecha"
    niveles = niveles.sort_index()

    return niveles, pd.DataFrame(controles)


def actualizar_base_mercados(
    processed: Path,
    directorio_backup: Path,
    directorio_snapshot: Path,
    solo_auditar: bool,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, object]]:
    ruta = processed / "mercados_factores_modelo.csv"

    if not ruta.exists():
        raise FileNotFoundError(
            f"No existe la base de mercados: {ruta}"
        )

    existente = leer_csv_flexible(ruta)
    fecha_col = detectar_columna(
        existente.columns,
        {"fecha", "date", "trading_date"},
    )

    if fecha_col is None:
        fecha_col = str(existente.columns[0])

    existente[fecha_col] = pd.to_datetime(
        existente[fecha_col],
        errors="coerce",
    )
    existente = (
        existente.dropna(subset=[fecha_col])
        .sort_values(fecha_col)
        .drop_duplicates(subset=[fecha_col], keep="last")
        .reset_index(drop=True)
    )

    fecha_max_antes = pd.Timestamp(
        existente[fecha_col].max()
    )

    # Descarga una ventana anterior para calcular correctamente
    # el primer retorno nuevo.
    fecha_inicio = fecha_max_antes - pd.Timedelta(days=15)
    fecha_fin_exclusiva = pd.Timestamp(
        date.today() + timedelta(days=2)
    )

    niveles, controles = descargar_mercados(
        fecha_inicio,
        fecha_fin_exclusiva,
        directorio_snapshot / "yfinance_descarga.csv",
    )

    actualizacion = pd.DataFrame(
        {fecha_col: niveles.index}
    )

    semanticas: dict[str, str] = {}

    for columna_destino in TICKERS:
        if columna_destino in existente.columns:
            semantica = detectar_semantica_serie(
                existente[columna_destino],
                columna_destino,
            )
        else:
            semantica = "retorno"

        semanticas[columna_destino] = semantica

        if semantica == "retorno":
            actualizacion[columna_destino] = (
                niveles[columna_destino]
                .pct_change(fill_method=None)
                .to_numpy()
            )
        else:
            actualizacion[columna_destino] = (
                niveles[columna_destino].to_numpy()
            )

    if "vix_retorno" in existente.columns:
        actualizacion["vix_retorno"] = (
            niveles["ret_IDX_VIX"]
            .pct_change(fill_method=None)
            .to_numpy()
        )
        semanticas["vix_retorno"] = "retorno"

    columnas_actualizables = [
        columna
        for columna in actualizacion.columns
        if columna != fecha_col
    ]

    combinado = existente.merge(
        actualizacion,
        on=fecha_col,
        how="outer",
        suffixes=("", "__nuevo"),
        validate="one_to_one",
    )

    for columna in columnas_actualizables:
        nueva_col = f"{columna}__nuevo"

        if columna not in combinado.columns and nueva_col in combinado.columns:
            combinado[columna] = combinado[nueva_col]
            combinado = combinado.drop(columns=[nueva_col])
            continue

        if nueva_col in combinado.columns:
            # Conserva el histórico ya validado y solo rellena huecos
            # o incorpora fechas nuevas.
            combinado[columna] = combinado[columna].combine_first(
                combinado[nueva_col]
            )
            combinado = combinado.drop(columns=[nueva_col])

    combinado = (
        combinado.sort_values(fecha_col)
        .drop_duplicates(subset=[fecha_col], keep="last")
        .reset_index(drop=True)
    )

    fecha_max_despues = pd.Timestamp(
        combinado[fecha_col].max()
    )

    nuevas_fechas = set(combinado[fecha_col]) - set(
        existente[fecha_col]
    )

    controles["semantica_archivo_destino"] = controles[
        "factor"
    ].map(semanticas)

    for factor in TICKERS:
        controles.loc[
            controles["factor"].eq(factor),
            "ultimo_valor_archivo",
        ] = (
            pd.to_numeric(
                combinado[factor],
                errors="coerce",
            ).dropna().iloc[-1]
            if factor in combinado.columns
            and pd.to_numeric(
                combinado[factor],
                errors="coerce",
            ).notna().any()
            else np.nan
        )

    if not solo_auditar:
        respaldar_archivo(ruta, directorio_backup)
        combinado.to_csv(
            ruta,
            index=False,
            encoding="utf-8-sig",
            date_format="%Y-%m-%d",
        )

    detalle = {
        "archivo": ruta.name,
        "fecha_maxima_antes": str(fecha_max_antes.date()),
        "fecha_maxima_descargada": (
            str(pd.Timestamp(niveles.index.max()).date())
            if not niveles.empty
            else None
        ),
        "fecha_maxima_despues": str(
            fecha_max_despues.date()
        ),
        "nuevas_fechas": len(nuevas_fechas),
        "semanticas": semanticas,
        "modo": "AUDITORIA" if solo_auditar else "ACTUALIZADO",
    }

    return combinado, controles, detalle


def validar_resultados(
    base_sbs: pd.DataFrame,
    base_mercados: pd.DataFrame,
) -> pd.DataFrame:
    fecha_sbs_col = detectar_columna(
        base_sbs.columns,
        {"fecha", "date", "fecha_cuota", "fecha_valor_cuota"},
    )
    afp_col = detectar_columna(
        base_sbs.columns,
        {"afp", "administradora", "nombre_afp"},
    )
    cuota_col = detectar_columna(
        base_sbs.columns,
        {"valor_cuota", "valor_de_la_cuota", "cuota", "valor"},
    )
    fecha_mercado_col = detectar_columna(
        base_mercados.columns,
        {"fecha", "date", "trading_date"},
    )

    controles = []

    if (
        fecha_sbs_col is not None
        and afp_col is not None
        and cuota_col is not None
    ):
        temporal = base_sbs.copy()
        temporal[fecha_sbs_col] = pd.to_datetime(
            temporal[fecha_sbs_col],
            errors="coerce",
        )
        temporal["_afp"] = temporal[afp_col].map(normalizar_afp)
        temporal[cuota_col] = pd.to_numeric(
            temporal[cuota_col],
            errors="coerce",
        )

        ultima_fecha = temporal[fecha_sbs_col].max()
        ultima = temporal[
            temporal[fecha_sbs_col].eq(ultima_fecha)
        ]

        controles.extend(
            [
                {
                    "control": "sbs_ultima_fecha_tiene_4_afp",
                    "estado": (
                        "correcto"
                        if ultima["_afp"].nunique() == 4
                        else "revisar"
                    ),
                    "detalle": (
                        f"fecha={ultima_fecha.date()}, "
                        f"afp={ultima['_afp'].nunique()}"
                    ),
                },
                {
                    "control": "sbs_cuotas_positivas",
                    "estado": (
                        "correcto"
                        if (
                            temporal[cuota_col].dropna() > 0
                        ).all()
                        else "revisar"
                    ),
                    "detalle": (
                        f"cuotas_no_positivas="
                        f"{int((temporal[cuota_col] <= 0).sum())}"
                    ),
                },
            ]
        )

    if fecha_mercado_col is not None:
        temporal = base_mercados.copy()
        temporal[fecha_mercado_col] = pd.to_datetime(
            temporal[fecha_mercado_col],
            errors="coerce",
        )

        controles.append(
            {
                "control": "mercados_fecha_maxima",
                "estado": "correcto",
                "detalle": str(
                    temporal[fecha_mercado_col].max().date()
                ),
            }
        )

        for factor in TICKERS:
            controles.append(
                {
                    "control": f"mercado_{factor}_disponible",
                    "estado": (
                        "correcto"
                        if factor in temporal.columns
                        and pd.to_numeric(
                            temporal[factor],
                            errors="coerce",
                        ).notna().any()
                        else "revisar"
                    ),
                    "detalle": (
                        f"observaciones="
                        f"{int(pd.to_numeric(temporal.get(factor), errors='coerce').notna().sum())}"
                        if factor in temporal.columns
                        else "columna_ausente"
                    ),
                }
            )

    return pd.DataFrame(controles)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Actualiza las cuotas SBS Fondo 3 y los factores de mercado "
            "utilizados por el modelo operativo."
        )
    )
    parser.add_argument(
        "--solo-auditar",
        action="store_true",
        help=(
            "Descarga y compara, pero no modifica los CSV principales."
        ),
    )
    args = parser.parse_args()

    raiz = Path(__file__).resolve().parents[1]
    processed = raiz / "data" / "processed"

    sello = datetime.now().strftime("%Y%m%d_%H%M%S")
    directorio_ejecucion = (
        processed / "actualizaciones_modelo61" / sello
    )
    directorio_backup = directorio_ejecucion / "backup"
    directorio_snapshot = directorio_ejecucion / "fuentes"

    directorio_backup.mkdir(parents=True, exist_ok=True)
    directorio_snapshot.mkdir(parents=True, exist_ok=True)

    print("\nACTUALIZADOR DE FUENTES SBS Y MERCADOS")
    print("=" * 120)
    print(
        "Modo:",
        "SOLO AUDITORÍA" if args.solo_auditar else "ACTUALIZACIÓN",
    )

    html = descargar_html_sbs(
        directorio_snapshot / "sbs_variables_spp.html"
    )
    datos_sbs_web = extraer_fondo3_sbs(html)
    datos_sbs_web.to_csv(
        directorio_snapshot / "sbs_fondo3_extraido.csv",
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )

    base_sbs, detalle_sbs = actualizar_base_sbs(
        processed,
        datos_sbs_web,
        directorio_backup,
        args.solo_auditar,
    )

    base_mercados, control_mercados, detalle_mercados = (
        actualizar_base_mercados(
            processed,
            directorio_backup,
            directorio_snapshot,
            args.solo_auditar,
        )
    )

    controles = validar_resultados(
        base_sbs,
        base_mercados,
    )

    rutas = {
        "resumen": (
            processed
            / "ca0001_modelo61_resumen_actualizacion.json"
        ),
        "control_mercados": (
            processed
            / "ca0001_modelo61_control_mercados.csv"
        ),
        "controles": (
            processed
            / "ca0001_modelo61_controles.csv"
        ),
    }

    control_mercados.to_csv(
        rutas["control_mercados"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    controles.to_csv(
        rutas["controles"],
        index=False,
        encoding="utf-8-sig",
    )

    resumen = {
        "version": "modelo61_actualizador_fuentes",
        "fecha_ejecucion": datetime.now().isoformat(),
        "modo": (
            "SOLO_AUDITORIA"
            if args.solo_auditar
            else "ACTUALIZACION"
        ),
        "sbs": detalle_sbs,
        "mercados": detalle_mercados,
        "controles": controles.to_dict(orient="records"),
        "directorio_auditoria": str(
            directorio_ejecucion.resolve()
        ),
        "nota": (
            "La página diaria de la SBS se usa como fuente oficial reciente. "
            "Los precios de mercado se descargan mediante yfinance. "
            "Las fuentes descargadas y los respaldos se conservan por ejecución."
        ),
    }

    rutas["resumen"].write_text(
        json.dumps(
            resumen,
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )

    print("\nACTUALIZACIÓN SBS")
    print("-" * 120)
    for clave, valor in detalle_sbs.items():
        print(f"{clave}: {valor}")

    print("\nACTUALIZACIÓN DE MERCADOS")
    print("-" * 120)
    for clave, valor in detalle_mercados.items():
        print(f"{clave}: {valor}")

    print("\nCONTROL DE TICKERS")
    print("-" * 120)
    print(control_mercados.to_string(index=False))

    print("\nCONTROLES FINALES")
    print("-" * 120)
    print(controles.to_string(index=False))

    print("\nArchivos creados:")
    for ruta in rutas.values():
        print(f" - {ruta.resolve()}")
    print(
        f" - Auditoría y respaldos: "
        f"{directorio_ejecucion.resolve()}"
    )

    estados_invalidos = controles[
        ~controles["estado"].astype(str).str.lower().eq("correcto")
    ]

    if not estados_invalidos.empty:
        print(
            "\nLa actualización terminó con controles por revisar. "
            "No ejecute el módulo 60 hasta revisar los avisos."
        )
        raise SystemExit(2)

    print(
        "\nSIGUIENTE PASO:\n"
        "python src\\60_orquestar_flujo_operativo_fondo3.py\n"
        "\nEl módulo 60 validará pronósticos anteriores, generará las "
        "nuevas estimaciones, las archivará y actualizará el panel."
    )


if __name__ == "__main__":
    main()
