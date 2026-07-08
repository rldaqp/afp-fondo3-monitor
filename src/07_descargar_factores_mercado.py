from __future__ import annotations

import time
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf


# Primera canasta de factores: amplia, interpretable y manejable.
# Todavía no incluye acciones individuales.
ACTIVOS = {
    # Mercados amplios y regiones
    "ACWI": {"nombre": "Acciones globales", "grupo": "mercado", "moneda": "USD"},
    "SPY": {"nombre": "Estados Unidos - S&P 500", "grupo": "mercado", "moneda": "USD"},
    "QQQ": {"nombre": "Estados Unidos - Nasdaq 100", "grupo": "mercado", "moneda": "USD"},
    "EEM": {"nombre": "Mercados emergentes", "grupo": "mercado", "moneda": "USD"},
    "ILF": {"nombre": "América Latina", "grupo": "mercado", "moneda": "USD"},
    "EPU": {"nombre": "Perú - ETF", "grupo": "mercado", "moneda": "USD"},
    "VGK": {"nombre": "Europa", "grupo": "region", "moneda": "USD"},
    "EWJ": {"nombre": "Japón", "grupo": "region", "moneda": "USD"},
    "MCHI": {"nombre": "China", "grupo": "region", "moneda": "USD"},

    # Sectores
    "XLK": {"nombre": "Tecnología", "grupo": "sector", "moneda": "USD"},
    "XLF": {"nombre": "Finanzas", "grupo": "sector", "moneda": "USD"},
    "XLE": {"nombre": "Energía", "grupo": "sector", "moneda": "USD"},
    "XLB": {"nombre": "Materiales", "grupo": "sector", "moneda": "USD"},
    "XLI": {"nombre": "Industria", "grupo": "sector", "moneda": "USD"},
    "XLV": {"nombre": "Salud", "grupo": "sector", "moneda": "USD"},
    "XLY": {"nombre": "Consumo discrecional", "grupo": "sector", "moneda": "USD"},
    "XLP": {"nombre": "Consumo básico", "grupo": "sector", "moneda": "USD"},

    # Materias primas y empresas relacionadas
    "GLD": {"nombre": "Oro", "grupo": "materia_prima", "moneda": "USD"},
    "CPER": {"nombre": "Cobre", "grupo": "materia_prima", "moneda": "USD"},
    "COPX": {"nombre": "Mineras de cobre", "grupo": "materia_prima", "moneda": "USD"},
    "USO": {"nombre": "Petróleo", "grupo": "materia_prima", "moneda": "USD"},

    # Renta fija
    "TLT": {"nombre": "Bonos Tesoro EE. UU. largo plazo", "grupo": "bonos", "moneda": "USD"},
    "LQD": {"nombre": "Bonos corporativos grado inversión", "grupo": "bonos", "moneda": "USD"},
    "HYG": {"nombre": "Bonos corporativos alto rendimiento", "grupo": "bonos", "moneda": "USD"},

    # Riesgo, dólar y tipo de cambio
    "^VIX": {"nombre": "Volatilidad VIX", "grupo": "riesgo", "moneda": "INDICE"},
    "DX-Y.NYB": {"nombre": "Índice dólar DXY", "grupo": "moneda", "moneda": "INDICE"},
    "PEN=X": {"nombre": "Tipo de cambio USD/PEN", "grupo": "moneda", "moneda": "PEN_POR_USD"},
}

REINTENTOS = 3
PAUSA_SEGUNDOS = 1.0


def limpiar_nombre_ticker(ticker: str) -> str:
    return (
        ticker.replace("^", "IDX_")
        .replace("=", "_")
        .replace(".", "_")
        .replace("-", "_")
    )


def descargar_ticker(
    ticker: str,
    fecha_inicio: str,
    fecha_fin_exclusiva: str,
) -> pd.DataFrame:
    ultimo_error: Exception | None = None

    for intento in range(1, REINTENTOS + 1):
        try:
            datos = yf.download(
                ticker,
                start=fecha_inicio,
                end=fecha_fin_exclusiva,
                interval="1d",
                auto_adjust=True,
                repair=True,
                progress=False,
                threads=False,
                multi_level_index=False,
                timeout=30,
            )

            if datos is None or datos.empty:
                raise ValueError("La descarga no devolvió observaciones.")

            if "Close" not in datos.columns:
                raise ValueError(
                    f"No se encontró la columna Close. Columnas: {list(datos.columns)}"
                )

            salida = datos.reset_index()
            columna_fecha = "Date" if "Date" in salida.columns else salida.columns[0]

            salida = salida.rename(
                columns={
                    columna_fecha: "fecha",
                    "Open": "apertura",
                    "High": "maximo",
                    "Low": "minimo",
                    "Close": "cierre_ajustado",
                    "Volume": "volumen",
                }
            )

            columnas = [
                c
                for c in [
                    "fecha",
                    "apertura",
                    "maximo",
                    "minimo",
                    "cierre_ajustado",
                    "volumen",
                ]
                if c in salida.columns
            ]
            salida = salida[columnas].copy()

            salida["fecha"] = pd.to_datetime(salida["fecha"], errors="coerce")
            if getattr(salida["fecha"].dt, "tz", None) is not None:
                salida["fecha"] = salida["fecha"].dt.tz_localize(None)

            salida = salida.dropna(subset=["fecha", "cierre_ajustado"])
            salida = salida.sort_values("fecha").drop_duplicates("fecha")
            salida["ticker"] = ticker

            return salida

        except Exception as error:
            ultimo_error = error
            print(
                f"  Intento {intento}/{REINTENTOS} falló para {ticker}: {error}"
            )
            time.sleep(PAUSA_SEGUNDOS * intento)

    raise RuntimeError(
        f"No fue posible descargar {ticker}: {ultimo_error}"
    )


def calcular_retornos(
    precios: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    retornos_simples = precios.pct_change(fill_method=None)
    retornos_log = np.log(precios / precios.shift(1))
    return retornos_simples, retornos_log


def convertir_activos_usd_a_pen(
    retornos_usd: pd.DataFrame,
) -> pd.DataFrame:
    if "PEN=X" not in retornos_usd.columns:
        raise ValueError(
            "No existe PEN=X; no se pueden convertir los activos USD a soles."
        )

    retorno_fx = retornos_usd["PEN=X"]
    salida = pd.DataFrame(index=retornos_usd.index)

    for ticker, metadata in ACTIVOS.items():
        if ticker not in retornos_usd.columns:
            continue

        retorno = retornos_usd[ticker]

        if metadata["moneda"] == "USD":
            # Retorno exacto del activo USD expresado en PEN:
            # (1 + r_activo_USD) * (1 + r_USDPEN) - 1
            salida[ticker] = (
                (1.0 + retorno) * (1.0 + retorno_fx) - 1.0
            )
        else:
            # Para VIX, DXY y el propio USD/PEN se conserva su variación nativa.
            salida[ticker] = retorno

    return salida


def crear_factores_modelo(
    retornos_pen: pd.DataFrame,
) -> pd.DataFrame:
    """
    Construye una tabla lista para modelar. Los activos cotizados en USD
    quedan expresados en soles; VIX, DXY y USD/PEN conservan su variación.
    """
    factores = retornos_pen.copy()
    factores.columns = [
        f"ret_{limpiar_nombre_ticker(c)}" for c in factores.columns
    ]

    # Variables adicionales útiles.
    if "ret_PEN_X" in factores.columns:
        factores["fx_usdpen"] = factores["ret_PEN_X"]

    if "ret_IDX_VIX" in factores.columns:
        factores["vix_retorno"] = factores["ret_IDX_VIX"]

    factores = factores.reset_index().rename(columns={"index": "fecha"})
    return factores


def main() -> None:
    raiz = Path(__file__).resolve().parents[1]
    processed = raiz / "data" / "processed"
    raw = raiz / "data" / "raw" / "mercados"
    raw.mkdir(parents=True, exist_ok=True)
    processed.mkdir(parents=True, exist_ok=True)

    ruta_afp = processed / "sbs_fondo3_base_maestra.csv"
    if not ruta_afp.exists():
        raise FileNotFoundError(
            f"No existe la base maestra del Fondo 3: {ruta_afp}"
        )

    afp = pd.read_csv(ruta_afp, parse_dates=["fecha"])
    fecha_inicial = afp["fecha"].min() - pd.Timedelta(days=15)

    # Se descarga hasta mañana porque yfinance trata end como fecha exclusiva.
    fecha_final_exclusiva = date.today() + timedelta(days=1)

    inicio_txt = fecha_inicial.strftime("%Y-%m-%d")
    fin_txt = fecha_final_exclusiva.strftime("%Y-%m-%d")

    print(
        f"Descargando {len(ACTIVOS)} factores desde {inicio_txt} "
        f"hasta {fin_txt}..."
    )

    series_cierre: dict[str, pd.Series] = {}
    coberturas: list[dict] = []
    errores: list[dict] = []

    for numero, (ticker, metadata) in enumerate(ACTIVOS.items(), start=1):
        print(
            f"\n[{numero}/{len(ACTIVOS)}] {ticker} — {metadata['nombre']}"
        )

        try:
            datos = descargar_ticker(ticker, inicio_txt, fin_txt)

            nombre_archivo = limpiar_nombre_ticker(ticker)
            ruta_raw = raw / f"{nombre_archivo}.csv"
            datos.to_csv(
                ruta_raw,
                index=False,
                encoding="utf-8-sig",
                date_format="%Y-%m-%d",
            )

            serie = datos.set_index("fecha")["cierre_ajustado"]
            serie.name = ticker
            series_cierre[ticker] = serie

            coberturas.append(
                {
                    "ticker": ticker,
                    "nombre": metadata["nombre"],
                    "grupo": metadata["grupo"],
                    "moneda": metadata["moneda"],
                    "fecha_inicial": datos["fecha"].min(),
                    "fecha_final": datos["fecha"].max(),
                    "observaciones": len(datos),
                    "estado": "correcto",
                    "error": "",
                }
            )

            print(
                f"  Correcto: {len(datos):,} observaciones | "
                f"{datos['fecha'].min().date()} a "
                f"{datos['fecha'].max().date()}"
            )

        except Exception as error:
            errores.append(
                {
                    "ticker": ticker,
                    "nombre": metadata["nombre"],
                    "error": str(error),
                }
            )
            coberturas.append(
                {
                    "ticker": ticker,
                    "nombre": metadata["nombre"],
                    "grupo": metadata["grupo"],
                    "moneda": metadata["moneda"],
                    "fecha_inicial": pd.NaT,
                    "fecha_final": pd.NaT,
                    "observaciones": 0,
                    "estado": "error",
                    "error": str(error),
                }
            )
            print(f"  ERROR definitivo: {error}")

        time.sleep(PAUSA_SEGUNDOS)

    if not series_cierre:
        raise RuntimeError(
            "No se pudo descargar ningún factor de mercado."
        )

    precios = pd.concat(series_cierre.values(), axis=1).sort_index()
    precios.index.name = "fecha"

    retornos_locales, retornos_log_locales = calcular_retornos(precios)

    if "PEN=X" in retornos_locales.columns:
        retornos_pen = convertir_activos_usd_a_pen(retornos_locales)
        factores_modelo = crear_factores_modelo(retornos_pen)
    else:
        print(
            "\nADVERTENCIA: PEN=X falló. Se guardarán retornos locales, "
            "pero todavía no estarán convertidos a soles."
        )
        retornos_pen = pd.DataFrame(index=precios.index)
        factores_modelo = (
            retornos_locales.reset_index()
            .rename(
                columns={
                    c: f"ret_{limpiar_nombre_ticker(c)}"
                    for c in retornos_locales.columns
                }
            )
        )

    catalogo = pd.DataFrame(
        [
            {
                "ticker": ticker,
                **metadata,
                "columna_modelo": f"ret_{limpiar_nombre_ticker(ticker)}",
            }
            for ticker, metadata in ACTIVOS.items()
        ]
    )

    cobertura = pd.DataFrame(coberturas)

    archivos = {
        "precios": processed / "mercados_precios_ajustados.csv",
        "retornos_locales": processed / "mercados_retornos_locales.csv",
        "retornos_log": processed / "mercados_retornos_log_locales.csv",
        "retornos_pen": processed / "mercados_retornos_en_pen.csv",
        "factores_modelo": processed / "mercados_factores_modelo.csv",
        "catalogo": processed / "mercados_catalogo_factores.csv",
        "cobertura": processed / "mercados_control_cobertura.csv",
        "errores": processed / "mercados_errores_descarga.csv",
    }

    precios.reset_index().to_csv(
        archivos["precios"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    retornos_locales.reset_index().to_csv(
        archivos["retornos_locales"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    retornos_log_locales.reset_index().to_csv(
        archivos["retornos_log"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    retornos_pen.reset_index().to_csv(
        archivos["retornos_pen"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    factores_modelo.to_csv(
        archivos["factores_modelo"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    catalogo.to_csv(
        archivos["catalogo"],
        index=False,
        encoding="utf-8-sig",
    )
    cobertura.to_csv(
        archivos["cobertura"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    pd.DataFrame(errores).to_csv(
        archivos["errores"],
        index=False,
        encoding="utf-8-sig",
    )

    print("\nDescarga de mercados terminada.")
    print(f"Factores correctos: {(cobertura['estado'] == 'correcto').sum()}")
    print(f"Factores con error: {(cobertura['estado'] == 'error').sum()}")
    print(
        "Rango conjunto de precios:",
        precios.index.min().date(),
        "a",
        precios.index.max().date(),
    )

    print("\nArchivos creados:")
    for ruta in archivos.values():
        print(f" - {ruta.resolve()}")

    if errores:
        print("\nFactores con error:")
        print(pd.DataFrame(errores).to_string(index=False))


if __name__ == "__main__":
    main()
