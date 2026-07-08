from __future__ import annotations

import json
import re
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from sklearn.feature_selection import mutual_info_regression


warnings.filterwarnings("ignore")

AFPS = ["Habitat", "Integra", "Prima", "Profuturo"]

FECHA_INICIO = "2014-12-01"
TOLERANCIA_ALINEACION_DIAS = 7
MIN_PRECIOS_ALIAS = 500
MIN_PARES_SCREEN = 700
LAGS = [0, 1, 2, 3]
UMBRAL_DUPLICADO = 0.995


# fx_modo:
# - USD: el índice ya está expresado en USD.
# - DIRECTO: el ticker FX informa USD por una unidad de moneda local.
# - INVERSO: el ticker FX informa unidades de moneda local por USD.
CATALOGO_INDICES: list[dict[str, Any]] = [
    {
        "indice": "S&P 500",
        "pais_region": "Estados Unidos",
        "moneda_local": "USD",
        "fx_ticker": None,
        "fx_modo": "USD",
        "aliases": ["^GSPC"],
    },
    {
        "indice": "Nasdaq Composite",
        "pais_region": "Estados Unidos",
        "moneda_local": "USD",
        "fx_ticker": None,
        "fx_modo": "USD",
        "aliases": ["^IXIC"],
    },
    {
        "indice": "Nasdaq 100",
        "pais_region": "Estados Unidos",
        "moneda_local": "USD",
        "fx_ticker": None,
        "fx_modo": "USD",
        "aliases": ["^NDX"],
    },
    {
        "indice": "Dow Jones Industrial Average",
        "pais_region": "Estados Unidos",
        "moneda_local": "USD",
        "fx_ticker": None,
        "fx_modo": "USD",
        "aliases": ["^DJI"],
    },
    {
        "indice": "Russell 2000",
        "pais_region": "Estados Unidos",
        "moneda_local": "USD",
        "fx_ticker": None,
        "fx_modo": "USD",
        "aliases": ["^RUT"],
    },
    {
        "indice": "DAX",
        "pais_region": "Alemania",
        "moneda_local": "EUR",
        "fx_ticker": "EURUSD=X",
        "fx_modo": "DIRECTO",
        "aliases": ["^GDAXI"],
    },
    {
        "indice": "MDAX",
        "pais_region": "Alemania",
        "moneda_local": "EUR",
        "fx_ticker": "EURUSD=X",
        "fx_modo": "DIRECTO",
        "aliases": ["^MDAXI"],
    },
    {
        "indice": "CAC 40",
        "pais_region": "Francia",
        "moneda_local": "EUR",
        "fx_ticker": "EURUSD=X",
        "fx_modo": "DIRECTO",
        "aliases": ["^FCHI"],
    },
    {
        "indice": "EURO STOXX 50",
        "pais_region": "Zona euro",
        "moneda_local": "EUR",
        "fx_ticker": "EURUSD=X",
        "fx_modo": "DIRECTO",
        "aliases": ["^STOXX50E"],
    },
    {
        "indice": "STOXX Europe 600",
        "pais_region": "Europa",
        "moneda_local": "EUR",
        "fx_ticker": "EURUSD=X",
        "fx_modo": "DIRECTO",
        "aliases": ["^STOXX"],
    },
    {
        "indice": "FTSE 100",
        "pais_region": "Reino Unido",
        "moneda_local": "GBP",
        "fx_ticker": "GBPUSD=X",
        "fx_modo": "DIRECTO",
        "aliases": ["^FTSE"],
    },
    {
        "indice": "SMI",
        "pais_region": "Suiza",
        "moneda_local": "CHF",
        "fx_ticker": "CHF=X",
        "fx_modo": "INVERSO",
        "aliases": ["^SSMI"],
    },
    {
        "indice": "AEX",
        "pais_region": "Países Bajos",
        "moneda_local": "EUR",
        "fx_ticker": "EURUSD=X",
        "fx_modo": "DIRECTO",
        "aliases": ["^AEX"],
    },
    {
        "indice": "IBEX 35",
        "pais_region": "España",
        "moneda_local": "EUR",
        "fx_ticker": "EURUSD=X",
        "fx_modo": "DIRECTO",
        "aliases": ["^IBEX"],
    },
    {
        "indice": "FTSE MIB",
        "pais_region": "Italia",
        "moneda_local": "EUR",
        "fx_ticker": "EURUSD=X",
        "fx_modo": "DIRECTO",
        "aliases": ["FTSEMIB.MI", "^FTMIB"],
    },
    {
        "indice": "Nikkei 225",
        "pais_region": "Japón",
        "moneda_local": "JPY",
        "fx_ticker": "JPY=X",
        "fx_modo": "INVERSO",
        "aliases": ["^N225"],
    },
    {
        "indice": "TOPIX",
        "pais_region": "Japón",
        "moneda_local": "JPY",
        "fx_ticker": "JPY=X",
        "fx_modo": "INVERSO",
        "aliases": ["^TOPX"],
    },
    {
        "indice": "Hang Seng",
        "pais_region": "Hong Kong",
        "moneda_local": "HKD",
        "fx_ticker": "HKD=X",
        "fx_modo": "INVERSO",
        "aliases": ["^HSI"],
    },
    {
        "indice": "Shanghai Composite",
        "pais_region": "China",
        "moneda_local": "CNY",
        "fx_ticker": "CNY=X",
        "fx_modo": "INVERSO",
        "aliases": ["000001.SS"],
    },
    {
        "indice": "CSI 300",
        "pais_region": "China",
        "moneda_local": "CNY",
        "fx_ticker": "CNY=X",
        "fx_modo": "INVERSO",
        "aliases": ["000300.SS"],
    },
    {
        "indice": "Shenzhen Component",
        "pais_region": "China",
        "moneda_local": "CNY",
        "fx_ticker": "CNY=X",
        "fx_modo": "INVERSO",
        "aliases": ["399001.SZ"],
    },
    {
        "indice": "Nifty 50",
        "pais_region": "India",
        "moneda_local": "INR",
        "fx_ticker": "INR=X",
        "fx_modo": "INVERSO",
        "aliases": ["^NSEI"],
    },
    {
        "indice": "BSE Sensex",
        "pais_region": "India",
        "moneda_local": "INR",
        "fx_ticker": "INR=X",
        "fx_modo": "INVERSO",
        "aliases": ["^BSESN"],
    },
    {
        "indice": "KOSPI",
        "pais_region": "Corea del Sur",
        "moneda_local": "KRW",
        "fx_ticker": "KRW=X",
        "fx_modo": "INVERSO",
        "aliases": ["^KS11"],
    },
    {
        "indice": "TAIEX",
        "pais_region": "Taiwán",
        "moneda_local": "TWD",
        "fx_ticker": "TWD=X",
        "fx_modo": "INVERSO",
        "aliases": ["^TWII"],
    },
    {
        "indice": "S&P/TSX Composite",
        "pais_region": "Canadá",
        "moneda_local": "CAD",
        "fx_ticker": "CAD=X",
        "fx_modo": "INVERSO",
        "aliases": ["^GSPTSE"],
    },
    {
        "indice": "S&P/ASX 200",
        "pais_region": "Australia",
        "moneda_local": "AUD",
        "fx_ticker": "AUDUSD=X",
        "fx_modo": "DIRECTO",
        "aliases": ["^AXJO"],
    },
    {
        "indice": "Bovespa",
        "pais_region": "Brasil",
        "moneda_local": "BRL",
        "fx_ticker": "BRL=X",
        "fx_modo": "INVERSO",
        "aliases": ["^BVSP"],
    },
    {
        "indice": "S&P/BMV IPC",
        "pais_region": "México",
        "moneda_local": "MXN",
        "fx_ticker": "MXN=X",
        "fx_modo": "INVERSO",
        "aliases": ["^MXX"],
    },
    {
        "indice": "S&P MERVAL",
        "pais_region": "Argentina",
        "moneda_local": "ARS",
        "fx_ticker": "ARS=X",
        "fx_modo": "INVERSO",
        "aliases": ["^MERV"],
    },
]


def slug(texto: str) -> str:
    x = texto.upper()
    x = re.sub(r"[^A-Z0-9]+", "_", x)
    return x.strip("_")


def leer_csv(ruta: Path) -> pd.DataFrame:
    ultimo: Exception | None = None
    for encoding in ["utf-8-sig", "latin-1"]:
        try:
            return pd.read_csv(ruta, encoding=encoding)
        except Exception as exc:
            ultimo = exc
    raise RuntimeError(f"No se pudo leer {ruta}: {ultimo}")


def extraer_serie(
    descarga: pd.DataFrame,
    ticker: str,
) -> pd.Series:
    if descarga.empty:
        return pd.Series(dtype=float)

    campos = ["Adj Close", "Close"]

    if isinstance(descarga.columns, pd.MultiIndex):
        nivel0 = descarga.columns.get_level_values(0)
        nivel1 = descarga.columns.get_level_values(1)

        for campo in campos:
            if campo in nivel0:
                bloque = descarga[campo]
                if isinstance(bloque, pd.Series):
                    serie = bloque
                elif ticker in bloque.columns:
                    serie = bloque[ticker]
                elif bloque.shape[1] == 1:
                    serie = bloque.iloc[:, 0]
                else:
                    continue
                return pd.to_numeric(serie, errors="coerce")

            if ticker in nivel0:
                bloque = descarga[ticker]
                if campo in bloque.columns:
                    return pd.to_numeric(
                        bloque[campo],
                        errors="coerce",
                    )

            if ticker in nivel1:
                bloque = descarga.xs(
                    ticker,
                    axis=1,
                    level=1,
                )
                if campo in bloque.columns:
                    return pd.to_numeric(
                        bloque[campo],
                        errors="coerce",
                    )

        return pd.Series(dtype=float)

    for campo in campos:
        if campo in descarga.columns:
            return pd.to_numeric(
                descarga[campo],
                errors="coerce",
            )

    return pd.Series(dtype=float)


def normalizar_indice(serie: pd.Series) -> pd.Series:
    x = serie.dropna().copy()
    fechas = pd.to_datetime(x.index, errors="coerce")

    try:
        fechas = fechas.tz_localize(None)
    except (TypeError, AttributeError):
        pass

    x.index = pd.DatetimeIndex(fechas).normalize()
    x = x[~x.index.isna()]
    x = x[~x.index.duplicated(keep="last")]
    return x.sort_index()


def descargar_ticker(
    ticker: str,
    fecha_fin: str,
) -> pd.Series:
    try:
        import yfinance as yf
    except ImportError as exc:
        raise RuntimeError(
            "Falta yfinance. Ejecuta: pip install yfinance"
        ) from exc

    datos = yf.download(
        ticker,
        start=FECHA_INICIO,
        end=fecha_fin,
        auto_adjust=False,
        progress=False,
        threads=False,
    )

    return normalizar_indice(
        extraer_serie(datos, ticker)
    )


def elegir_indices(
    fecha_fin: str,
) -> tuple[
    dict[str, dict[str, Any]],
    pd.DataFrame,
]:
    elegidos: dict[str, dict[str, Any]] = {}
    auditoria = []

    total = len(CATALOGO_INDICES)

    for numero, entrada in enumerate(
        CATALOGO_INDICES,
        start=1,
    ):
        print(
            f"  [{numero:02d}/{total:02d}] "
            f"{entrada['indice']} — {entrada['pais_region']}"
        )

        mejor = None

        for ticker in entrada["aliases"]:
            try:
                serie = descargar_ticker(
                    ticker,
                    fecha_fin,
                )
                estado = (
                    "CORRECTO"
                    if len(serie) >= MIN_PRECIOS_ALIAS
                    else "HISTORIA_INSUFICIENTE"
                )
            except Exception as exc:
                serie = pd.Series(dtype=float)
                estado = f"ERROR: {exc}"

            auditoria.append(
                {
                    "indice": entrada["indice"],
                    "pais_region": entrada["pais_region"],
                    "moneda_local": entrada["moneda_local"],
                    "alias_probado": ticker,
                    "estado": estado,
                    "n_precios": int(len(serie)),
                    "fecha_inicio": (
                        serie.index.min()
                        if not serie.empty else pd.NaT
                    ),
                    "fecha_fin": (
                        serie.index.max()
                        if not serie.empty else pd.NaT
                    ),
                }
            )

            if len(serie) < MIN_PRECIOS_ALIAS:
                continue

            candidato = {
                **entrada,
                "ticker_elegido": ticker,
                "serie": serie,
            }

            if (
                mejor is None
                or len(serie) > len(mejor["serie"])
            ):
                mejor = candidato

        if mejor is not None:
            elegidos[entrada["indice"]] = mejor

    return elegidos, pd.DataFrame(auditoria)


def alinear_nivel(
    fechas_objetivo: pd.DataFrame,
    serie: pd.Series,
) -> pd.DataFrame:
    mercado = serie.rename("nivel").reset_index()
    mercado.columns = ["fecha_mercado", "nivel"]

    mercado["fecha_mercado"] = pd.to_datetime(
        mercado["fecha_mercado"],
        errors="coerce",
    ).astype("datetime64[ns]")

    mercado = (
        mercado.dropna()
        .drop_duplicates("fecha_mercado", keep="last")
        .sort_values("fecha_mercado")
    )

    fechas = fechas_objetivo.copy()
    fechas["fecha_cuota"] = pd.to_datetime(
        fechas["fecha_cuota"],
        errors="coerce",
    ).astype("datetime64[ns]")

    fechas = (
        fechas.dropna()
        .drop_duplicates("fecha_cuota")
        .sort_values("fecha_cuota")
    )

    alineado = pd.merge_asof(
        fechas,
        mercado,
        left_on="fecha_cuota",
        right_on="fecha_mercado",
        direction="backward",
        tolerance=pd.Timedelta(
            days=TOLERANCIA_ALINEACION_DIAS
        ),
    )

    alineado["edad_cierre_dias"] = (
        alineado["fecha_cuota"]
        - alineado["fecha_mercado"]
    ).dt.days

    alineado["nuevo_cierre"] = (
        alineado["fecha_mercado"]
        .ne(alineado["fecha_mercado"].shift(1))
        .fillna(False)
    )

    return alineado


def obtener_local_a_usd(
    entrada: dict[str, Any],
    fx_descargados: dict[str, pd.Series],
    fechas: pd.DataFrame,
) -> pd.Series:
    modo = entrada["fx_modo"]

    if modo == "USD":
        return pd.Series(
            1.0,
            index=fechas["fecha_cuota"],
        )

    ticker = entrada["fx_ticker"]
    serie_fx = fx_descargados[ticker]
    alineado_fx = alinear_nivel(
        fechas,
        serie_fx,
    )

    fx = pd.Series(
        alineado_fx["nivel"].to_numpy(),
        index=alineado_fx["fecha_cuota"],
    )

    if modo == "DIRECTO":
        return fx

    if modo == "INVERSO":
        return 1.0 / fx.replace(0, np.nan)

    raise ValueError(f"fx_modo desconocido: {modo}")


def construir_factores(
    elegidos: dict[str, dict[str, Any]],
    fechas_cuota: pd.DataFrame,
    fecha_fin: str,
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
]:
    fx_necesarios = sorted(
        {
            entrada["fx_ticker"]
            for entrada in elegidos.values()
            if entrada["fx_ticker"] is not None
        }
        | {"PEN=X"}
    )

    fx_descargados = {}

    print("\nDescargando monedas para conversión a PEN...")

    for ticker in fx_necesarios:
        print(f"  - {ticker}")
        fx_descargados[ticker] = descargar_ticker(
            ticker,
            fecha_fin,
        )

    usdpen_alineado = alinear_nivel(
        fechas_cuota,
        fx_descargados["PEN=X"],
    )
    usdpen = pd.Series(
        usdpen_alineado["nivel"].to_numpy(),
        index=usdpen_alineado["fecha_cuota"],
    )

    panel = fechas_cuota.copy()
    catalogo = []
    auditoria = []

    for nombre, entrada in elegidos.items():
        alineado = alinear_nivel(
            fechas_cuota,
            entrada["serie"],
        )

        indice_local = pd.Series(
            alineado["nivel"].to_numpy(),
            index=alineado["fecha_cuota"],
        )
        nuevo_cierre = pd.Series(
            alineado["nuevo_cierre"].to_numpy(),
            index=alineado["fecha_cuota"],
        )
        edad = pd.Series(
            alineado["edad_cierre_dias"].to_numpy(),
            index=alineado["fecha_cuota"],
        )

        local_a_usd = obtener_local_a_usd(
            entrada,
            fx_descargados,
            fechas_cuota,
        )

        nivel_pen = indice_local * local_a_usd * usdpen

        retorno_local = indice_local.pct_change(
            fill_method=None
        )
        retorno_pen = nivel_pen.pct_change(
            fill_method=None
        )

        # Si no hubo nuevo cierre del índice, el retorno local es 0:
        # no apareció nueva información del mercado local.
        retorno_local = retorno_local.where(
            nuevo_cierre,
            0.0,
        )

        identificador = slug(
            f"{entrada['pais_region']}_{nombre}"
        )
        factor_local = f"ret_IDX_LOCAL_{identificador}"
        factor_pen = f"ret_IDX_PEN_{identificador}"

        panel[factor_local] = panel[
            "fecha_cuota"
        ].map(retorno_local)
        panel[factor_pen] = panel[
            "fecha_cuota"
        ].map(retorno_pen)

        for factor, moneda_modelo, transformacion in [
            (
                factor_local,
                entrada["moneda_local"],
                "retorno_indice_moneda_local",
            ),
            (
                factor_pen,
                "PEN",
                "indice_local_convertido_a_PEN",
            ),
        ]:
            catalogo.append(
                {
                    "factor": factor,
                    "indice": nombre,
                    "pais_region": entrada["pais_region"],
                    "ticker_elegido": entrada["ticker_elegido"],
                    "moneda_local": entrada["moneda_local"],
                    "moneda_modelo": moneda_modelo,
                    "transformacion": transformacion,
                    "fx_ticker": entrada["fx_ticker"],
                    "fx_modo": entrada["fx_modo"],
                }
            )

        auditoria.append(
            {
                "indice": nombre,
                "pais_region": entrada["pais_region"],
                "ticker_elegido": entrada["ticker_elegido"],
                "moneda_local": entrada["moneda_local"],
                "n_precios_originales": int(
                    len(entrada["serie"])
                ),
                "cobertura_nivel_alineado_pct": float(
                    indice_local.notna().mean() * 100.0
                ),
                "nuevo_cierre_pct": float(
                    nuevo_cierre.mean() * 100.0
                ),
                "edad_cierre_mediana_dias": float(
                    edad.dropna().median()
                ),
                "edad_cierre_p90_dias": float(
                    edad.dropna().quantile(0.90)
                ),
                "fecha_inicio": entrada["serie"].index.min(),
                "fecha_fin": entrada["serie"].index.max(),
            }
        )

    return (
        panel,
        pd.DataFrame(catalogo),
        pd.DataFrame(auditoria),
    )


def informacion_mutua(
    x: pd.Series,
    y: pd.Series,
) -> float:
    par = pd.concat([x, y], axis=1).dropna()

    if len(par) < MIN_PARES_SCREEN:
        return np.nan

    try:
        return float(
            mutual_info_regression(
                par.iloc[:, [0]].to_numpy(),
                par.iloc[:, 1].to_numpy(),
                random_state=42,
            )[0]
        )
    except Exception:
        return np.nan


def screening_train(
    base: pd.DataFrame,
    factores: pd.DataFrame,
    fin_train: pd.Timestamp,
) -> pd.DataFrame:
    panel = base.merge(
        factores,
        on="fecha_cuota",
        how="left",
    )

    columnas = [
        c for c in factores.columns
        if c != "fecha_cuota"
    ]

    filas = []

    for afp in AFPS:
        datos = panel[
            panel["afp"].astype(str).eq(afp)
            & panel["fecha_cuota"].le(fin_train)
        ].copy()

        y = datos["retorno_cuota"]

        for factor in columnas:
            candidatos = []

            for lag in LAGS:
                x = datos[factor].shift(lag)
                par = pd.concat([y, x], axis=1).dropna()

                if len(par) < MIN_PARES_SCREEN:
                    continue

                candidatos.append(
                    {
                        "lag": lag,
                        "n": len(par),
                        "spearman": float(
                            par.iloc[:, 0].corr(
                                par.iloc[:, 1],
                                method="spearman",
                            )
                        ),
                        "pearson": float(
                            par.iloc[:, 0].corr(
                                par.iloc[:, 1],
                                method="pearson",
                            )
                        ),
                        "mi": informacion_mutua(
                            par.iloc[:, 1],
                            par.iloc[:, 0],
                        ),
                    }
                )

            if not candidatos:
                continue

            mejor = max(
                candidatos,
                key=lambda z: abs(z["spearman"]),
            )

            filas.append(
                {
                    "afp": afp,
                    "factor": factor,
                    "mejor_lag_train": int(mejor["lag"]),
                    "n_train": int(mejor["n"]),
                    "cobertura_train_pct": float(
                        datos[factor].notna().mean()
                        * 100.0
                    ),
                    "spearman_train": mejor["spearman"],
                    "pearson_train": mejor["pearson"],
                    "mutual_information_train": mejor["mi"],
                    "abs_spearman_train": abs(
                        mejor["spearman"]
                    ),
                }
            )

    return (
        pd.DataFrame(filas)
        .sort_values(
            ["afp", "abs_spearman_train"],
            ascending=[True, False],
        )
        .reset_index(drop=True)
    )


def detectar_duplicados(
    factores: pd.DataFrame,
    base: pd.DataFrame,
    fin_train: pd.Timestamp,
) -> pd.DataFrame:
    fechas = (
        base[base["fecha_cuota"].le(fin_train)]
        [["fecha_cuota"]]
        .drop_duplicates()
    )

    x = fechas.merge(
        factores,
        on="fecha_cuota",
        how="left",
    ).drop(columns=["fecha_cuota"])

    corr = x.corr()
    columnas = list(corr.columns)
    filas = []

    for i, col1 in enumerate(columnas):
        for col2 in columnas[i + 1 :]:
            valor = corr.loc[col1, col2]

            if (
                pd.notna(valor)
                and abs(float(valor)) >= UMBRAL_DUPLICADO
            ):
                filas.append(
                    {
                        "factor_1": col1,
                        "factor_2": col2,
                        "correlacion_train": float(valor),
                    }
                )

    return pd.DataFrame(filas)


def crear_graficos(
    screening: pd.DataFrame,
    carpeta: Path,
) -> None:
    carpeta.mkdir(parents=True, exist_ok=True)

    for afp in AFPS:
        top = (
            screening[screening["afp"].eq(afp)]
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

        plt.figure(figsize=(12, 8))
        plt.barh(
            etiquetas,
            top["spearman_train"],
        )
        plt.axvline(0, linewidth=1)
        plt.xlabel("Spearman en entrenamiento")
        plt.title(
            f"Índices internacionales nativos — {afp}"
        )
        plt.tight_layout()
        plt.savefig(
            carpeta
            / f"01_indices_nativos_{afp.lower()}.png",
            dpi=160,
            bbox_inches="tight",
        )
        plt.close()


def main() -> None:
    raiz = Path(__file__).resolve().parents[1]
    processed = raiz / "data" / "processed"
    graficos = processed / "graficos_modelo74"
    processed.mkdir(parents=True, exist_ok=True)

    base = leer_csv(
        processed / "ca0001_modelo56_base_alineada.csv"
    )
    split = leer_csv(
        processed / "ca0001_modelo50_division_temporal.csv"
    )

    base["fecha_cuota"] = pd.to_datetime(
        base["fecha_cuota"],
        errors="coerce",
    ).dt.normalize()
    base["retorno_cuota"] = pd.to_numeric(
        base["retorno_cuota"],
        errors="coerce",
    )

    split["fecha_fin"] = pd.to_datetime(
        split["fecha_fin"],
        errors="coerce",
    )
    train = split[
        split["segmento"].astype(str).eq(
            "entrenamiento_descubrimiento"
        )
    ]

    if train.empty:
        raise RuntimeError(
            "No se encontró entrenamiento_descubrimiento."
        )

    fin_train = pd.Timestamp(
        train["fecha_fin"].iloc[0]
    ).normalize()

    fechas_cuota = (
        base[["fecha_cuota"]]
        .dropna()
        .drop_duplicates()
        .sort_values("fecha_cuota")
    )

    fecha_fin_descarga = (
        max(
            pd.Timestamp.today().normalize(),
            pd.Timestamp(base["fecha_cuota"].max())
            + pd.Timedelta(days=5),
        )
        + pd.Timedelta(days=1)
    ).strftime("%Y-%m-%d")

    print(
        "\nMÓDULO 74 — ÍNDICES INTERNACIONALES NATIVOS"
    )
    print("=" * 165)
    print(
        "Se comparan índices locales y sus versiones convertidas a PEN."
    )
    print(
        f"Descarga: {FECHA_INICIO} a {fecha_fin_descarga}"
    )

    elegidos, auditoria_descarga = elegir_indices(
        fecha_fin_descarga
    )

    if not elegidos:
        raise RuntimeError(
            "No se pudo descargar ningún índice."
        )

    factores, catalogo, auditoria_factores = (
        construir_factores(
            elegidos,
            fechas_cuota,
            fecha_fin_descarga,
        )
    )

    screen = screening_train(
        base,
        factores,
        fin_train,
    )

    screen = screen.merge(
        catalogo,
        on="factor",
        how="left",
    )

    duplicados = detectar_duplicados(
        factores,
        base,
        fin_train,
    )

    crear_graficos(
        screen,
        graficos,
    )

    rutas = {
        "auditoria_descarga": (
            processed
            / "ca0001_modelo74_auditoria_descarga_indices.csv"
        ),
        "catalogo": (
            processed
            / "ca0001_modelo74_catalogo_indices.csv"
        ),
        "factores": (
            processed
            / "ca0001_modelo74_factores_indices.csv"
        ),
        "auditoria_factores": (
            processed
            / "ca0001_modelo74_auditoria_factores_indices.csv"
        ),
        "screening": (
            processed
            / "ca0001_modelo74_screening_train_indices.csv"
        ),
        "top": (
            processed
            / "ca0001_modelo74_top20_por_afp.csv"
        ),
        "duplicados": (
            processed
            / "ca0001_modelo74_indices_casi_duplicados.csv"
        ),
        "resumen": (
            processed
            / "ca0001_modelo74_resumen.json"
        ),
    }

    auditoria_descarga.to_csv(
        rutas["auditoria_descarga"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    catalogo.to_csv(
        rutas["catalogo"],
        index=False,
        encoding="utf-8-sig",
    )
    factores.to_csv(
        rutas["factores"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    auditoria_factores.to_csv(
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
    screen.groupby(
        "afp",
        group_keys=False,
    ).head(20).to_csv(
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
        "version": "modelo74_indices_internacionales_nativos",
        "indices_catalogo": len(CATALOGO_INDICES),
        "indices_descargados": len(elegidos),
        "factores_generados": int(
            len([
                c for c in factores.columns
                if c != "fecha_cuota"
            ])
        ),
        "pares_casi_duplicados": int(
            len(duplicados)
        ),
        "fin_entrenamiento": str(
            fin_train.date()
        ),
        "nota": (
            "Los índices se prueban en moneda local y convertidos a PEN. "
            "Este módulo solo hace screening; la selección incremental "
            "se realizará en el módulo siguiente."
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

    print("\nAUDITORÍA DE ÍNDICES DESCARGADOS")
    print("-" * 165)
    print(
        auditoria_factores[
            [
                "indice",
                "pais_region",
                "ticker_elegido",
                "moneda_local",
                "n_precios_originales",
                "cobertura_nivel_alineado_pct",
                "nuevo_cierre_pct",
                "edad_cierre_mediana_dias",
                "edad_cierre_p90_dias",
                "fecha_inicio",
                "fecha_fin",
            ]
        ].to_string(index=False)
    )

    print("\nTOP 20 POR AFP — SOLO ENTRENAMIENTO")
    print("-" * 165)
    print(
        screen.groupby(
            "afp",
            group_keys=False,
        ).head(20)[
            [
                "afp",
                "indice",
                "pais_region",
                "ticker_elegido",
                "moneda_modelo",
                "factor",
                "mejor_lag_train",
                "n_train",
                "spearman_train",
                "pearson_train",
                "mutual_information_train",
            ]
        ].to_string(index=False)
    )

    print("\nRESUMEN")
    print("-" * 165)
    print(
        f"Índices descargados: {len(elegidos)} "
        f"de {len(CATALOGO_INDICES)}"
    )
    print(
        f"Factores generados: "
        f"{len(factores.columns) - 1}"
    )
    print(
        f"Pares casi duplicados: {len(duplicados)}"
    )

    print("\nARCHIVOS CREADOS")
    print("-" * 165)
    for ruta in rutas.values():
        print(f" - {ruta.resolve()}")
    print(f" - {graficos.resolve()}")

    print(
        "\nLECTURA:\n"
        "- Un ETF como EWG o EWJ es un proxy negociable; DAX, Nikkei "
        "o TOPIX son índices nativos. No son exactamente lo mismo.\n"
        "- La versión local mide el mercado del país; la versión PEN "
        "incorpora además el efecto cambiario.\n"
        "- El módulo siguiente comparará estos índices contra los ETF "
        "ya seleccionados y conservará solo el aporte incremental.\n"
        "- Una correlación alta no demuestra que la AFP tenga el índice "
        "o sus componentes."
    )


if __name__ == "__main__":
    main()
