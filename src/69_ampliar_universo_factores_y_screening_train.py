from __future__ import annotations

import json
import math
import re
import warnings
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from sklearn.feature_selection import mutual_info_regression


warnings.filterwarnings("ignore")

AFPS = ["Habitat", "Integra", "Prima", "Profuturo"]
LAGS = [0, 1, 2, 3]
TOLERANCIA_MERCADO_DIAS = 7
MIN_OBSERVACIONES_SCREEN = 500
UMBRAL_DUPLICADO = 0.995


UNIVERSO = [
    # Mercado global y Estados Unidos
    {"ticker": "SPY", "nombre": "S&P 500 ETF", "categoria": "RV_GLOBAL_USA", "tipo": "USD_ASSET"},
    {"ticker": "QQQ", "nombre": "Nasdaq 100 ETF", "categoria": "RV_GLOBAL_USA", "tipo": "USD_ASSET"},
    {"ticker": "IWM", "nombre": "Russell 2000 ETF", "categoria": "RV_GLOBAL_USA", "tipo": "USD_ASSET"},
    {"ticker": "DIA", "nombre": "Dow Jones ETF", "categoria": "RV_GLOBAL_USA", "tipo": "USD_ASSET"},
    {"ticker": "VT", "nombre": "Total World Stock ETF", "categoria": "RV_GLOBAL", "tipo": "USD_ASSET"},
    {"ticker": "ACWI", "nombre": "MSCI All Country World ETF", "categoria": "RV_GLOBAL", "tipo": "USD_ASSET"},
    {"ticker": "EFA", "nombre": "Mercados desarrollados fuera de USA", "categoria": "RV_DESARROLLADOS", "tipo": "USD_ASSET"},
    {"ticker": "IEFA", "nombre": "Mercados desarrollados Core", "categoria": "RV_DESARROLLADOS", "tipo": "USD_ASSET"},
    {"ticker": "EEM", "nombre": "Mercados emergentes ETF", "categoria": "RV_EMERGENTES", "tipo": "USD_ASSET"},
    {"ticker": "VWO", "nombre": "Mercados emergentes Vanguard", "categoria": "RV_EMERGENTES", "tipo": "USD_ASSET"},
    {"ticker": "ILF", "nombre": "Latinoamérica 40 ETF", "categoria": "RV_LATAM", "tipo": "USD_ASSET"},

    # Países y regiones
    {"ticker": "EPU", "nombre": "Perú ETF", "categoria": "PAISES", "tipo": "USD_ASSET"},
    {"ticker": "EWZ", "nombre": "Brasil ETF", "categoria": "PAISES", "tipo": "USD_ASSET"},
    {"ticker": "EWW", "nombre": "México ETF", "categoria": "PAISES", "tipo": "USD_ASSET"},
    {"ticker": "ECH", "nombre": "Chile ETF", "categoria": "PAISES", "tipo": "USD_ASSET"},
    {"ticker": "ARGT", "nombre": "Argentina ETF", "categoria": "PAISES", "tipo": "USD_ASSET"},
    {"ticker": "GXG", "nombre": "Colombia ETF", "categoria": "PAISES", "tipo": "USD_ASSET"},
    {"ticker": "INDA", "nombre": "India ETF", "categoria": "PAISES", "tipo": "USD_ASSET"},
    {"ticker": "MCHI", "nombre": "China ETF", "categoria": "PAISES", "tipo": "USD_ASSET"},
    {"ticker": "EWY", "nombre": "Corea del Sur ETF", "categoria": "PAISES", "tipo": "USD_ASSET"},
    {"ticker": "EWT", "nombre": "Taiwán ETF", "categoria": "PAISES", "tipo": "USD_ASSET"},
    {"ticker": "EWJ", "nombre": "Japón ETF", "categoria": "PAISES", "tipo": "USD_ASSET"},
    {"ticker": "EWG", "nombre": "Alemania ETF", "categoria": "PAISES", "tipo": "USD_ASSET"},
    {"ticker": "EWU", "nombre": "Reino Unido ETF", "categoria": "PAISES", "tipo": "USD_ASSET"},

    # Sectores
    {"ticker": "XLB", "nombre": "Materiales USA", "categoria": "SECTORES", "tipo": "USD_ASSET"},
    {"ticker": "XLI", "nombre": "Industriales USA", "categoria": "SECTORES", "tipo": "USD_ASSET"},
    {"ticker": "XLF", "nombre": "Financiero USA", "categoria": "SECTORES", "tipo": "USD_ASSET"},
    {"ticker": "XLK", "nombre": "Tecnología USA", "categoria": "SECTORES", "tipo": "USD_ASSET"},
    {"ticker": "XLE", "nombre": "Energía USA", "categoria": "SECTORES", "tipo": "USD_ASSET"},
    {"ticker": "XLY", "nombre": "Consumo discrecional USA", "categoria": "SECTORES", "tipo": "USD_ASSET"},
    {"ticker": "XLP", "nombre": "Consumo básico USA", "categoria": "SECTORES", "tipo": "USD_ASSET"},
    {"ticker": "XLV", "nombre": "Salud USA", "categoria": "SECTORES", "tipo": "USD_ASSET"},
    {"ticker": "XLU", "nombre": "Utilities USA", "categoria": "SECTORES", "tipo": "USD_ASSET"},
    {"ticker": "XLC", "nombre": "Comunicaciones USA", "categoria": "SECTORES", "tipo": "USD_ASSET"},
    {"ticker": "VNQ", "nombre": "Real estate USA", "categoria": "SECTORES", "tipo": "USD_ASSET"},

    # Minería, materiales y transición energética
    {"ticker": "COPX", "nombre": "Minera de cobre ETF", "categoria": "MINERIA_MATERIALES", "tipo": "USD_ASSET"},
    {"ticker": "PICK", "nombre": "Minería global ETF", "categoria": "MINERIA_MATERIALES", "tipo": "USD_ASSET"},
    {"ticker": "REMX", "nombre": "Tierras raras ETF", "categoria": "MINERIA_MATERIALES", "tipo": "USD_ASSET"},
    {"ticker": "LIT", "nombre": "Litio y baterías ETF", "categoria": "MINERIA_MATERIALES", "tipo": "USD_ASSET"},
    {"ticker": "URA", "nombre": "Uranio ETF", "categoria": "MINERIA_MATERIALES", "tipo": "USD_ASSET"},
    {"ticker": "SLX", "nombre": "Acero global ETF", "categoria": "MINERIA_MATERIALES", "tipo": "USD_ASSET"},
    {"ticker": "ICLN", "nombre": "Energía limpia global", "categoria": "TRANSICION_ENERGETICA", "tipo": "USD_ASSET"},

    # Materias primas
    {"ticker": "GLD", "nombre": "Oro ETF", "categoria": "COMMODITIES", "tipo": "USD_ASSET"},
    {"ticker": "SLV", "nombre": "Plata ETF", "categoria": "COMMODITIES", "tipo": "USD_ASSET"},
    {"ticker": "GDX", "nombre": "Mineras de oro ETF", "categoria": "COMMODITIES", "tipo": "USD_ASSET"},
    {"ticker": "GDXJ", "nombre": "Mineras junior de oro ETF", "categoria": "COMMODITIES", "tipo": "USD_ASSET"},
    {"ticker": "USO", "nombre": "Petróleo WTI ETF", "categoria": "COMMODITIES", "tipo": "USD_ASSET"},
    {"ticker": "BNO", "nombre": "Petróleo Brent ETF", "categoria": "COMMODITIES", "tipo": "USD_ASSET"},
    {"ticker": "CPER", "nombre": "Cobre físico/futuros ETF", "categoria": "COMMODITIES", "tipo": "USD_ASSET"},
    {"ticker": "DBA", "nombre": "Agricultura ETF", "categoria": "COMMODITIES", "tipo": "USD_ASSET"},

    # Renta fija y crédito
    {"ticker": "SHY", "nombre": "Treasury 1-3 años", "categoria": "RENTA_FIJA", "tipo": "USD_ASSET"},
    {"ticker": "IEF", "nombre": "Treasury 7-10 años", "categoria": "RENTA_FIJA", "tipo": "USD_ASSET"},
    {"ticker": "TLT", "nombre": "Treasury 20+ años", "categoria": "RENTA_FIJA", "tipo": "USD_ASSET"},
    {"ticker": "TIP", "nombre": "Bonos protegidos por inflación", "categoria": "RENTA_FIJA", "tipo": "USD_ASSET"},
    {"ticker": "LQD", "nombre": "Crédito corporativo investment grade", "categoria": "CREDITO", "tipo": "USD_ASSET"},
    {"ticker": "HYG", "nombre": "Crédito high yield", "categoria": "CREDITO", "tipo": "USD_ASSET"},
    {"ticker": "EMB", "nombre": "Bonos soberanos emergentes USD", "categoria": "CREDITO_EMERGENTE", "tipo": "USD_ASSET"},
    {"ticker": "AGG", "nombre": "Bonos agregados USA", "categoria": "RENTA_FIJA", "tipo": "USD_ASSET"},
    {"ticker": "BNDX", "nombre": "Bonos internacionales", "categoria": "RENTA_FIJA", "tipo": "USD_ASSET"},

    # Empresas líquidas vinculadas a Perú/minería
    {"ticker": "SCCO", "nombre": "Southern Copper", "categoria": "ACCIONES_MINERAS", "tipo": "USD_ASSET"},
    {"ticker": "BVN", "nombre": "Buenaventura ADR", "categoria": "ACCIONES_PERU", "tipo": "USD_ASSET"},
    {"ticker": "BAP", "nombre": "Credicorp", "categoria": "ACCIONES_PERU", "tipo": "USD_ASSET"},
    {"ticker": "FCX", "nombre": "Freeport-McMoRan", "categoria": "ACCIONES_MINERAS", "tipo": "USD_ASSET"},
    {"ticker": "NEM", "nombre": "Newmont", "categoria": "ACCIONES_MINERAS", "tipo": "USD_ASSET"},
    {"ticker": "RIO", "nombre": "Rio Tinto ADR", "categoria": "ACCIONES_MINERAS", "tipo": "USD_ASSET"},
    {"ticker": "BHP", "nombre": "BHP ADR", "categoria": "ACCIONES_MINERAS", "tipo": "USD_ASSET"},
    {"ticker": "VALE", "nombre": "Vale ADR", "categoria": "ACCIONES_MINERAS", "tipo": "USD_ASSET"},

    # Volatilidad, tasas y divisas
    {"ticker": "^VIX", "nombre": "Índice VIX", "categoria": "VOLATILIDAD", "tipo": "INDEX_RETURN"},
    {"ticker": "^TNX", "nombre": "Tasa Treasury 10 años", "categoria": "TASAS", "tipo": "RATE_CHANGE"},
    {"ticker": "^FVX", "nombre": "Tasa Treasury 5 años", "categoria": "TASAS", "tipo": "RATE_CHANGE"},
    {"ticker": "^IRX", "nombre": "Tasa Treasury 13 semanas", "categoria": "TASAS", "tipo": "RATE_CHANGE"},
    {"ticker": "PEN=X", "nombre": "USD/PEN", "categoria": "FX", "tipo": "FX_RETURN"},
    {"ticker": "DX-Y.NYB", "nombre": "Índice dólar DXY", "categoria": "FX", "tipo": "FX_RETURN"},
    {"ticker": "EURUSD=X", "nombre": "EUR/USD", "categoria": "FX", "tipo": "FX_RETURN"},
    {"ticker": "JPY=X", "nombre": "USD/JPY", "categoria": "FX", "tipo": "FX_RETURN"},
    {"ticker": "BRL=X", "nombre": "USD/BRL", "categoria": "FX", "tipo": "FX_RETURN"},
    {"ticker": "CLP=X", "nombre": "USD/CLP", "categoria": "FX", "tipo": "FX_RETURN"},
    {"ticker": "COP=X", "nombre": "USD/COP", "categoria": "FX", "tipo": "FX_RETURN"},
    {"ticker": "MXN=X", "nombre": "USD/MXN", "categoria": "FX", "tipo": "FX_RETURN"},
]


def slug_ticker(ticker: str) -> str:
    texto = ticker.replace("^", "IDX_").replace("=", "_").replace("-", "_").replace(".", "_")
    texto = re.sub(r"[^A-Za-z0-9_]+", "_", texto)
    return texto.strip("_").upper()


def cargar_base(processed: Path) -> pd.DataFrame:
    ruta = processed / "ca0001_modelo56_base_alineada.csv"
    if not ruta.exists():
        raise FileNotFoundError("No existe ca0001_modelo56_base_alineada.csv.")

    df = leer_csv_flexible(ruta)
    df["fecha_cuota"] = pd.to_datetime(df["fecha_cuota"], errors="coerce").dt.normalize()
    df["retorno_cuota"] = pd.to_numeric(df["retorno_cuota"], errors="coerce")

    return (
        df.dropna(subset=["fecha_cuota", "afp", "retorno_cuota"])
        .sort_values(["afp", "fecha_cuota"])
        .reset_index(drop=True)
    )


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


def cargar_fin_entrenamiento(processed: Path) -> pd.Timestamp:
    ruta = processed / "ca0001_modelo50_division_temporal.csv"
    if not ruta.exists():
        raise FileNotFoundError("No existe ca0001_modelo50_division_temporal.csv.")

    df = leer_csv_flexible(ruta)
    df["fecha_fin"] = pd.to_datetime(df["fecha_fin"], errors="coerce")
    fila = df[df["segmento"].astype(str).eq("entrenamiento_descubrimiento")]

    if fila.empty:
        raise ValueError("No se encontró el final de entrenamiento.")

    return pd.Timestamp(fila["fecha_fin"].iloc[0]).normalize()


def extraer_cierre_descarga(descarga: pd.DataFrame, ticker: str) -> pd.Series:
    if descarga.empty:
        return pd.Series(dtype=float, name=ticker)

    if isinstance(descarga.columns, pd.MultiIndex):
        nivel0 = descarga.columns.get_level_values(0)
        nivel1 = descarga.columns.get_level_values(1)

        campo = "Adj Close" if "Adj Close" in nivel0 else "Close"
        if campo in nivel0:
            bloque = descarga[campo]
            if isinstance(bloque, pd.Series):
                serie = bloque
            elif ticker in bloque.columns:
                serie = bloque[ticker]
            elif len(bloque.columns) == 1:
                serie = bloque.iloc[:, 0]
            else:
                return pd.Series(dtype=float, name=ticker)
        elif ticker in nivel0:
            bloque = descarga[ticker]
            campo = "Adj Close" if "Adj Close" in bloque.columns else "Close"
            serie = bloque[campo]
        elif ticker in nivel1:
            bloque = descarga.xs(ticker, axis=1, level=1)
            campo = "Adj Close" if "Adj Close" in bloque.columns else "Close"
            serie = bloque[campo]
        else:
            return pd.Series(dtype=float, name=ticker)
    else:
        campo = "Adj Close" if "Adj Close" in descarga.columns else "Close"
        if campo not in descarga.columns:
            return pd.Series(dtype=float, name=ticker)
        serie = descarga[campo]

    serie = pd.to_numeric(serie, errors="coerce").dropna()
    serie.index = pd.to_datetime(serie.index, errors="coerce").tz_localize(None).normalize()
    serie = serie[~serie.index.duplicated(keep="last")]
    serie.name = ticker
    return serie


def descargar_precios(
    tickers: list[str],
    fecha_inicio: pd.Timestamp,
    fecha_fin: pd.Timestamp,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    try:
        import yfinance as yf
    except ImportError as exc:
        raise RuntimeError(
            "Falta yfinance. Instálalo con: pip install yfinance"
        ) from exc

    precios: dict[str, pd.Series] = {}
    auditoria: list[dict[str, Any]] = []

    for numero, ticker in enumerate(tickers, start=1):
        print(f"  [{numero:02d}/{len(tickers):02d}] Descargando {ticker}...")
        try:
            descarga = yf.download(
                ticker,
                start=fecha_inicio.strftime("%Y-%m-%d"),
                end=(fecha_fin + pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
                auto_adjust=False,
                progress=False,
                threads=False,
            )
            serie = extraer_cierre_descarga(descarga, ticker)

            if serie.empty:
                auditoria.append(
                    {
                        "ticker": ticker,
                        "estado_descarga": "SIN_DATOS",
                        "n_precios": 0,
                        "fecha_inicio": pd.NaT,
                        "fecha_fin": pd.NaT,
                    }
                )
                continue

            precios[ticker] = serie
            auditoria.append(
                {
                    "ticker": ticker,
                    "estado_descarga": "CORRECTO",
                    "n_precios": int(len(serie)),
                    "fecha_inicio": serie.index.min(),
                    "fecha_fin": serie.index.max(),
                }
            )
        except Exception as exc:
            auditoria.append(
                {
                    "ticker": ticker,
                    "estado_descarga": f"ERROR: {exc}",
                    "n_precios": 0,
                    "fecha_inicio": pd.NaT,
                    "fecha_fin": pd.NaT,
                }
            )

    panel = pd.concat(precios.values(), axis=1).sort_index() if precios else pd.DataFrame()
    return panel, auditoria


def alinear_nivel(
    fechas_cuota: pd.DataFrame,
    serie: pd.Series,
) -> pd.Series:
    """
    Alinea cada fecha de cuota con el último cierre disponible.

    Correcciones incluidas:
    - reconoce automáticamente el nombre de la columna de fecha;
    - elimina zonas horarias;
    - fuerza ambas claves de merge_asof a datetime64[ns];
    - elimina duplicados y ordena las fechas;
    - controla series vacías.
    """
    mercado = serie.rename("nivel").reset_index()
    cuotas = fechas_cuota.copy()

    if mercado.shape[1] < 2:
        indice = pd.to_datetime(
            cuotas["fecha_cuota"], errors="coerce"
        )
        try:
            indice = indice.dt.tz_localize(None)
        except (TypeError, AttributeError):
            pass
        indice = indice.dt.normalize().astype("datetime64[ns]")

        return pd.Series(
            np.nan,
            index=indice,
            name="nivel",
        )

    primera_columna = mercado.columns[0]
    mercado = mercado.rename(
        columns={primera_columna: "fecha_mercado"}
    )

    mercado["fecha_mercado"] = pd.to_datetime(
        mercado["fecha_mercado"], errors="coerce"
    )

    try:
        mercado["fecha_mercado"] = (
            mercado["fecha_mercado"].dt.tz_localize(None)
        )
    except (TypeError, AttributeError):
        pass

    mercado["fecha_mercado"] = (
        mercado["fecha_mercado"]
        .dt.normalize()
        .astype("datetime64[ns]")
    )

    mercado["nivel"] = pd.to_numeric(
        mercado["nivel"], errors="coerce"
    )

    mercado = (
        mercado.dropna(subset=["fecha_mercado", "nivel"])
        .drop_duplicates(subset=["fecha_mercado"], keep="last")
        .sort_values("fecha_mercado")
        .reset_index(drop=True)
    )

    cuotas["fecha_cuota"] = pd.to_datetime(
        cuotas["fecha_cuota"], errors="coerce"
    )

    try:
        cuotas["fecha_cuota"] = (
            cuotas["fecha_cuota"].dt.tz_localize(None)
        )
    except (TypeError, AttributeError):
        pass

    cuotas["fecha_cuota"] = (
        cuotas["fecha_cuota"]
        .dt.normalize()
        .astype("datetime64[ns]")
    )

    cuotas = (
        cuotas.dropna(subset=["fecha_cuota"])
        .drop_duplicates(subset=["fecha_cuota"], keep="last")
        .sort_values("fecha_cuota")
        .reset_index(drop=True)
    )

    if mercado.empty:
        return pd.Series(
            np.nan,
            index=cuotas["fecha_cuota"],
            name="nivel",
        )

    mercado["fecha_mercado"] = mercado[
        "fecha_mercado"
    ].astype("datetime64[ns]")

    cuotas["fecha_cuota"] = cuotas[
        "fecha_cuota"
    ].astype("datetime64[ns]")

    alineado = pd.merge_asof(
        cuotas,
        mercado,
        left_on="fecha_cuota",
        right_on="fecha_mercado",
        direction="backward",
        tolerance=pd.Timedelta(
            days=TOLERANCIA_MERCADO_DIAS
        ),
    )

    return pd.Series(
        alineado["nivel"].to_numpy(),
        index=alineado["fecha_cuota"],
        name="nivel",
    )

def construir_factores(
    precios: pd.DataFrame,
    metadata: pd.DataFrame,
    fechas: pd.DatetimeIndex,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    fechas_df = pd.DataFrame({"fecha_cuota": pd.DatetimeIndex(fechas).sort_values()})
    niveles_alineados: dict[str, pd.Series] = {}

    for ticker in precios.columns:
        niveles_alineados[ticker] = alinear_nivel(
            fechas_df,
            precios[ticker].dropna(),
        )

    niveles = pd.DataFrame(niveles_alineados, index=fechas_df["fecha_cuota"])
    factores = pd.DataFrame(index=niveles.index)
    catalogo_filas: list[dict[str, Any]] = []

    usdpen = niveles["PEN=X"] if "PEN=X" in niveles.columns else None

    for _, fila in metadata.iterrows():
        ticker = fila["ticker"]
        if ticker not in niveles.columns:
            continue

        tipo = fila["tipo"]
        slug = slug_ticker(ticker)
        nivel = niveles[ticker]

        if tipo == "USD_ASSET":
            nombre_usd = f"ret_USD_{slug}"
            factores[nombre_usd] = nivel.pct_change(fill_method=None)
            catalogo_filas.append(
                {
                    **fila.to_dict(),
                    "factor": nombre_usd,
                    "transformacion": "retorno_en_moneda_USD",
                    "moneda_modelo": "USD",
                }
            )

            if usdpen is not None:
                nombre_pen = f"ret_PEN_{slug}"
                nivel_pen = nivel * usdpen
                factores[nombre_pen] = nivel_pen.pct_change(fill_method=None)
                catalogo_filas.append(
                    {
                        **fila.to_dict(),
                        "factor": nombre_pen,
                        "transformacion": "retorno_convertido_a_PEN",
                        "moneda_modelo": "PEN",
                    }
                )

        elif tipo in {"INDEX_RETURN", "FX_RETURN"}:
            nombre = f"ret_{slug}"
            factores[nombre] = nivel.pct_change(fill_method=None)
            catalogo_filas.append(
                {
                    **fila.to_dict(),
                    "factor": nombre,
                    "transformacion": "retorno_porcentual",
                    "moneda_modelo": "NIVEL_ORIGINAL",
                }
            )

        elif tipo == "RATE_CHANGE":
            nombre = f"chg_{slug}"
            factores[nombre] = nivel.diff()
            catalogo_filas.append(
                {
                    **fila.to_dict(),
                    "factor": nombre,
                    "transformacion": "cambio_absoluto_de_tasa",
                    "moneda_modelo": "UNIDAD_INDICE",
                }
            )

    factores = factores.replace([np.inf, -np.inf], np.nan)
    factores.index.name = "fecha_cuota"
    catalogo = pd.DataFrame(catalogo_filas)

    return factores.reset_index(), catalogo


def mutual_information(x: pd.Series, y: pd.Series) -> float:
    datos = pd.concat([x, y], axis=1).dropna()
    if len(datos) < MIN_OBSERVACIONES_SCREEN:
        return np.nan

    try:
        valor = mutual_info_regression(
            datos.iloc[:, [0]].to_numpy(),
            datos.iloc[:, 1].to_numpy(),
            random_state=42,
        )[0]
        return float(valor)
    except Exception:
        return np.nan


def screening(
    base: pd.DataFrame,
    factores: pd.DataFrame,
    fin_train: pd.Timestamp,
) -> pd.DataFrame:
    panel = base.merge(factores, on="fecha_cuota", how="left")
    columnas_factores = [
        c for c in factores.columns if c != "fecha_cuota"
    ]
    filas = []

    for afp in AFPS:
        datos = panel[
            panel["afp"].eq(afp)
            & panel["fecha_cuota"].le(fin_train)
        ].copy()

        y = datos["retorno_cuota"]

        for factor in columnas_factores:
            resultados_lag = []

            for lag in LAGS:
                x = datos[factor].shift(lag)
                par = pd.concat([y, x], axis=1).dropna()
                n = len(par)

                if n < MIN_OBSERVACIONES_SCREEN:
                    resultados_lag.append(
                        {
                            "lag": lag,
                            "n": n,
                            "spearman": np.nan,
                            "pearson": np.nan,
                            "mi": np.nan,
                        }
                    )
                    continue

                spearman = float(par.iloc[:, 0].corr(par.iloc[:, 1], method="spearman"))
                pearson = float(par.iloc[:, 0].corr(par.iloc[:, 1], method="pearson"))
                mi = mutual_information(par.iloc[:, 1], par.iloc[:, 0])

                resultados_lag.append(
                    {
                        "lag": lag,
                        "n": n,
                        "spearman": spearman,
                        "pearson": pearson,
                        "mi": mi,
                    }
                )

            validos = [
                r for r in resultados_lag if pd.notna(r["spearman"])
            ]
            if not validos:
                continue

            mejor = max(validos, key=lambda r: abs(r["spearman"]))
            cobertura = float(datos[factor].notna().mean() * 100.0)

            filas.append(
                {
                    "afp": afp,
                    "factor": factor,
                    "mejor_lag_train": int(mejor["lag"]),
                    "n_train": int(mejor["n"]),
                    "cobertura_train_pct": cobertura,
                    "spearman_train": mejor["spearman"],
                    "pearson_train": mejor["pearson"],
                    "mutual_information_train": mejor["mi"],
                    "abs_spearman_train": abs(mejor["spearman"]),
                }
            )

    return (
        pd.DataFrame(filas)
        .sort_values(["afp", "abs_spearman_train"], ascending=[True, False])
        .reset_index(drop=True)
    )


def detectar_duplicados(
    factores: pd.DataFrame,
    fin_train: pd.Timestamp,
) -> pd.DataFrame:
    x = factores[
        factores["fecha_cuota"].le(fin_train)
    ].drop(columns=["fecha_cuota"])

    correlacion = x.corr(method="pearson", min_periods=MIN_OBSERVACIONES_SCREEN)
    columnas = correlacion.columns.tolist()
    filas = []

    for i, a in enumerate(columnas):
        for b in columnas[i + 1 :]:
            valor = correlacion.loc[a, b]
            if pd.notna(valor) and abs(valor) >= UMBRAL_DUPLICADO:
                filas.append(
                    {
                        "factor_a": a,
                        "factor_b": b,
                        "correlacion_train": float(valor),
                        "abs_correlacion_train": abs(float(valor)),
                    }
                )

    return (
        pd.DataFrame(filas)
        .sort_values("abs_correlacion_train", ascending=False)
        .reset_index(drop=True)
        if filas
        else pd.DataFrame(
            columns=[
                "factor_a",
                "factor_b",
                "correlacion_train",
                "abs_correlacion_train",
            ]
        )
    )


def auditoria_factores(
    factores: pd.DataFrame,
    catalogo: pd.DataFrame,
) -> pd.DataFrame:
    filas = []

    for factor in [c for c in factores.columns if c != "fecha_cuota"]:
        serie = factores[["fecha_cuota", factor]].dropna()
        metadato = catalogo[catalogo["factor"].eq(factor)]

        filas.append(
            {
                "factor": factor,
                "ticker": metadato["ticker"].iloc[0] if not metadato.empty else "",
                "nombre": metadato["nombre"].iloc[0] if not metadato.empty else "",
                "categoria": metadato["categoria"].iloc[0] if not metadato.empty else "",
                "transformacion": (
                    metadato["transformacion"].iloc[0]
                    if not metadato.empty
                    else ""
                ),
                "n_retornos": int(len(serie)),
                "cobertura_total_pct": float(
                    factores[factor].notna().mean() * 100.0
                ),
                "fecha_inicio": (
                    serie["fecha_cuota"].min() if not serie.empty else pd.NaT
                ),
                "fecha_fin": (
                    serie["fecha_cuota"].max() if not serie.empty else pd.NaT
                ),
                "desviacion_estandar": float(
                    factores[factor].std(ddof=1)
                ),
                "minimo": float(factores[factor].min()),
                "maximo": float(factores[factor].max()),
            }
        )

    return pd.DataFrame(filas).sort_values(
        ["categoria", "factor"]
    ).reset_index(drop=True)


def guardar_figura(ruta: Path) -> None:
    plt.tight_layout()
    plt.savefig(ruta, dpi=160, bbox_inches="tight")
    plt.close()


def crear_graficos(screen: pd.DataFrame, graficos: Path) -> None:
    graficos.mkdir(parents=True, exist_ok=True)

    for afp in AFPS:
        top = (
            screen[screen["afp"].eq(afp)]
            .head(20)
            .sort_values("abs_spearman_train")
        )
        if top.empty:
            continue

        etiquetas = [
            f"{factor} (L{lag})"
            for factor, lag in zip(
                top["factor"],
                top["mejor_lag_train"],
            )
        ]

        plt.figure(figsize=(11, 7))
        plt.barh(etiquetas, top["spearman_train"])
        plt.axvline(0, linewidth=1)
        plt.xlabel("Correlación Spearman en entrenamiento")
        plt.title(f"Top 20 factores ampliados — {afp}")
        guardar_figura(
            graficos / f"01_top_factores_{afp.lower()}.png"
        )


def main() -> None:
    raiz = Path(__file__).resolve().parents[1]
    processed = raiz / "data" / "processed"
    graficos = processed / "graficos_modelo69"
    processed.mkdir(parents=True, exist_ok=True)

    base = cargar_base(processed)
    fin_train = cargar_fin_entrenamiento(processed)

    metadata = pd.DataFrame(UNIVERSO).drop_duplicates("ticker")
    tickers = metadata["ticker"].tolist()

    fecha_inicio = pd.Timestamp(base["fecha_cuota"].min()) - pd.Timedelta(days=20)
    fecha_fin = max(
        pd.Timestamp.today().normalize(),
        pd.Timestamp(base["fecha_cuota"].max()) + pd.Timedelta(days=5),
    )

    print("\nMÓDULO 69 — EXPANSIÓN DEL UNIVERSO DE FACTORES")
    print("=" * 145)
    print(f"Periodo de descarga: {fecha_inicio.date()} a {fecha_fin.date()}")
    print(f"Series solicitadas: {len(tickers)}")
    print(
        "Se crearán retornos en USD y, para activos cotizados en USD, "
        "también retornos convertidos a soles."
    )

    precios, auditoria_descarga = descargar_precios(
        tickers,
        fecha_inicio,
        fecha_fin,
    )
    auditoria_descarga_df = pd.DataFrame(auditoria_descarga).merge(
        metadata,
        on="ticker",
        how="left",
    )

    if precios.empty:
        raise RuntimeError("No se descargó ninguna serie de mercado.")

    fechas_cuota = pd.DatetimeIndex(
        sorted(base["fecha_cuota"].unique())
    )
    factores, catalogo = construir_factores(
        precios,
        metadata,
        fechas_cuota,
    )

    auditoria_factores_df = auditoria_factores(
        factores,
        catalogo,
    )
    screen = screening(
        base,
        factores,
        fin_train,
    )
    duplicados = detectar_duplicados(
        factores,
        fin_train,
    )

    crear_graficos(screen, graficos)

    rutas = {
        "precios": processed / "ca0001_modelo69_precios_ampliados.csv",
        "factores": processed / "ca0001_modelo69_factores_ampliados.csv",
        "catalogo": processed / "ca0001_modelo69_catalogo_factores.csv",
        "auditoria_descarga": processed / "ca0001_modelo69_auditoria_descarga.csv",
        "auditoria_factores": processed / "ca0001_modelo69_auditoria_factores.csv",
        "screening": processed / "ca0001_modelo69_screening_train.csv",
        "top": processed / "ca0001_modelo69_top25_por_afp.csv",
        "duplicados": processed / "ca0001_modelo69_factores_casi_duplicados.csv",
        "resumen": processed / "ca0001_modelo69_resumen.json",
    }

    precios.reset_index(names="fecha_mercado").to_csv(
        rutas["precios"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    factores.to_csv(
        rutas["factores"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    catalogo.to_csv(
        rutas["catalogo"],
        index=False,
        encoding="utf-8-sig",
    )
    auditoria_descarga_df.to_csv(
        rutas["auditoria_descarga"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    auditoria_factores_df.to_csv(
        rutas["auditoria_factores"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    screen.to_csv(
        rutas["screening"],
        index=False,
        encoding="utf-8-sig",
    )
    screen.groupby("afp", group_keys=False).head(25).to_csv(
        rutas["top"],
        index=False,
        encoding="utf-8-sig",
    )
    duplicados.to_csv(
        rutas["duplicados"],
        index=False,
        encoding="utf-8-sig",
    )

    resumen = {
        "version": "modelo69_expansion_universo_factores",
        "fecha_inicio_descarga": str(fecha_inicio.date()),
        "fecha_fin_descarga": str(fecha_fin.date()),
        "fin_entrenamiento_screening": str(fin_train.date()),
        "tickers_solicitados": int(len(tickers)),
        "tickers_descargados": int(
            auditoria_descarga_df["estado_descarga"].eq("CORRECTO").sum()
        ),
        "factores_generados": int(
            len([c for c in factores.columns if c != "fecha_cuota"])
        ),
        "pares_casi_duplicados": int(len(duplicados)),
        "nota": (
            "El screening usa únicamente entrenamiento y sirve para explorar. "
            "No selecciona todavía el modelo final ni demuestra causalidad."
        ),
    }
    rutas["resumen"].write_text(
        json.dumps(resumen, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("\nAUDITORÍA DE DESCARGA")
    print("-" * 145)
    print(
        auditoria_descarga_df[
            [
                "ticker",
                "nombre",
                "categoria",
                "estado_descarga",
                "n_precios",
                "fecha_inicio",
                "fecha_fin",
            ]
        ].to_string(index=False)
    )

    print("\nRESUMEN DE FACTORES")
    print("-" * 145)
    print(
        f"Tickers correctos: "
        f"{auditoria_descarga_df['estado_descarga'].eq('CORRECTO').sum()} "
        f"de {len(auditoria_descarga_df)}"
    )
    print(
        f"Factores generados: "
        f"{len([c for c in factores.columns if c != 'fecha_cuota'])}"
    )
    print(
        f"Pares con correlación absoluta >= {UMBRAL_DUPLICADO}: "
        f"{len(duplicados)}"
    )

    print("\nTOP 20 FACTORES POR AFP — SOLO ENTRENAMIENTO")
    print("-" * 145)
    print(
        screen.groupby("afp", group_keys=False)
        .head(20)[
            [
                "afp",
                "factor",
                "mejor_lag_train",
                "n_train",
                "cobertura_train_pct",
                "spearman_train",
                "pearson_train",
                "mutual_information_train",
            ]
        ]
        .to_string(index=False)
    )

    print("\nARCHIVOS CREADOS")
    print("-" * 145)
    for ruta in rutas.values():
        print(f" - {ruta.resolve()}")
    print(f" - {graficos.resolve()}")

    print(
        "\nLECTURA CORRECTA:\n"
        "- Este módulo amplía la materia prima del modelo; todavía no elige "
        "la canasta definitiva.\n"
        "- Los retornos PEN incorporan simultáneamente el movimiento del activo "
        "y del USD/PEN.\n"
        "- Un factor con alta correlación no necesariamente es una tenencia de "
        "la AFP ni prueba causalidad.\n"
        "- El módulo 70 hará selección incremental solo con entrenamiento y "
        "validación, eliminando duplicados y comprobando aporte fuera de muestra."
    )


if __name__ == "__main__":
    main()
