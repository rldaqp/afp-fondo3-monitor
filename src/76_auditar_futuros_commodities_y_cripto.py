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
LAGS = [0, 1, 2, 3]

MIN_PRECIOS = 500
MIN_PARES_SCREEN = 700
TOLERANCIA_ALINEACION_DIAS = 4
UMBRAL_DUPLICADO = 0.995
UMBRAL_RETORNO_EXTREMO = 0.15


CATALOGO = [
    # Futuros de índices
    {
        "ticker": "ES=F",
        "nombre": "E-mini S&P 500",
        "categoria": "FUTURO_INDICE",
        "moneda": "USD",
    },
    {
        "ticker": "NQ=F",
        "nombre": "E-mini Nasdaq 100",
        "categoria": "FUTURO_INDICE",
        "moneda": "USD",
    },
    {
        "ticker": "YM=F",
        "nombre": "E-mini Dow Jones",
        "categoria": "FUTURO_INDICE",
        "moneda": "USD",
    },
    {
        "ticker": "RTY=F",
        "nombre": "E-mini Russell 2000",
        "categoria": "FUTURO_INDICE",
        "moneda": "USD",
    },

    # Energía
    {
        "ticker": "CL=F",
        "nombre": "Petróleo WTI",
        "categoria": "FUTURO_ENERGIA",
        "moneda": "USD",
    },
    {
        "ticker": "BZ=F",
        "nombre": "Petróleo Brent",
        "categoria": "FUTURO_ENERGIA",
        "moneda": "USD",
    },
    {
        "ticker": "NG=F",
        "nombre": "Gas natural",
        "categoria": "FUTURO_ENERGIA",
        "moneda": "USD",
    },
    {
        "ticker": "RB=F",
        "nombre": "Gasolina RBOB",
        "categoria": "FUTURO_ENERGIA",
        "moneda": "USD",
    },
    {
        "ticker": "HO=F",
        "nombre": "Heating Oil",
        "categoria": "FUTURO_ENERGIA",
        "moneda": "USD",
    },

    # Metales
    {
        "ticker": "GC=F",
        "nombre": "Oro",
        "categoria": "FUTURO_METAL",
        "moneda": "USD",
    },
    {
        "ticker": "SI=F",
        "nombre": "Plata",
        "categoria": "FUTURO_METAL",
        "moneda": "USD",
    },
    {
        "ticker": "HG=F",
        "nombre": "Cobre",
        "categoria": "FUTURO_METAL",
        "moneda": "USD",
    },
    {
        "ticker": "PL=F",
        "nombre": "Platino",
        "categoria": "FUTURO_METAL",
        "moneda": "USD",
    },
    {
        "ticker": "PA=F",
        "nombre": "Paladio",
        "categoria": "FUTURO_METAL",
        "moneda": "USD",
    },

    # Agricultura
    {
        "ticker": "ZC=F",
        "nombre": "Maíz",
        "categoria": "FUTURO_AGRICOLA",
        "moneda": "USD",
    },
    {
        "ticker": "ZW=F",
        "nombre": "Trigo",
        "categoria": "FUTURO_AGRICOLA",
        "moneda": "USD",
    },
    {
        "ticker": "ZS=F",
        "nombre": "Soya",
        "categoria": "FUTURO_AGRICOLA",
        "moneda": "USD",
    },

    # Bonos y dólar
    {
        "ticker": "ZN=F",
        "nombre": "Treasury 10 años futuro",
        "categoria": "FUTURO_BONOS",
        "moneda": "USD",
    },
    {
        "ticker": "ZB=F",
        "nombre": "Treasury largo plazo futuro",
        "categoria": "FUTURO_BONOS",
        "moneda": "USD",
    },
    {
        "ticker": "DX=F",
        "nombre": "Índice dólar futuro",
        "categoria": "FUTURO_FX",
        "moneda": "USD",
    },

    # Criptoactivos
    {
        "ticker": "BTC-USD",
        "nombre": "Bitcoin",
        "categoria": "CRIPTO",
        "moneda": "USD",
    },
    {
        "ticker": "ETH-USD",
        "nombre": "Ethereum",
        "categoria": "CRIPTO",
        "moneda": "USD",
    },
    {
        "ticker": "LTC-USD",
        "nombre": "Litecoin",
        "categoria": "CRIPTO",
        "moneda": "USD",
    },
    {
        "ticker": "XRP-USD",
        "nombre": "XRP",
        "categoria": "CRIPTO",
        "moneda": "USD",
    },
]


def slug(texto: str) -> str:
    x = texto.upper()
    x = re.sub(r"[^A-Z0-9]+", "_", x)
    return x.strip("_")


def leer_csv(ruta: Path) -> pd.DataFrame:
    ultimo = None
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


def normalizar_serie(serie: pd.Series) -> pd.Series:
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


def descargar(
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

    return normalizar_serie(
        extraer_serie(datos, ticker)
    )


def retorno_seguro(precios: pd.Series) -> tuple[pd.Series, int]:
    p = precios.astype(float).copy()

    anterior = p.shift(1)
    no_positivo = (
        p.le(0)
        | anterior.le(0)
    )

    retorno = p.pct_change(fill_method=None)
    retorno = retorno.mask(no_positivo)

    return retorno, int(no_positivo.sum())


def alinear_retorno(
    fechas: pd.DataFrame,
    retorno: pd.Series,
) -> pd.DataFrame:
    mercado = retorno.rename("retorno").reset_index()
    mercado.columns = ["fecha_mercado", "retorno"]

    mercado["fecha_mercado"] = pd.to_datetime(
        mercado["fecha_mercado"],
        errors="coerce",
    ).astype("datetime64[ns]")

    mercado = (
        mercado.dropna(subset=["fecha_mercado"])
        .drop_duplicates("fecha_mercado", keep="last")
        .sort_values("fecha_mercado")
    )

    objetivo = fechas.copy()
    objetivo["fecha_cuota"] = pd.to_datetime(
        objetivo["fecha_cuota"],
        errors="coerce",
    ).astype("datetime64[ns]")

    objetivo = (
        objetivo.dropna()
        .drop_duplicates("fecha_cuota")
        .sort_values("fecha_cuota")
    )

    salida = pd.merge_asof(
        objetivo,
        mercado,
        left_on="fecha_cuota",
        right_on="fecha_mercado",
        direction="backward",
        tolerance=pd.Timedelta(
            days=TOLERANCIA_ALINEACION_DIAS
        ),
    )

    salida["edad_dias"] = (
        salida["fecha_cuota"]
        - salida["fecha_mercado"]
    ).dt.days

    return salida


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


def construir_factores(
    fechas: pd.DataFrame,
    fecha_fin: str,
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
]:
    usdpen = descargar("PEN=X", fecha_fin)

    if usdpen.empty:
        raise RuntimeError(
            "No se pudo descargar USD/PEN."
        )

    retorno_usdpen, _ = retorno_seguro(usdpen)
    fx_alineado = alinear_retorno(
        fechas,
        retorno_usdpen,
    )
    fx = pd.Series(
        fx_alineado["retorno"].to_numpy(),
        index=fx_alineado["fecha_cuota"],
    )

    panel = fechas.copy()
    catalogo = []
    auditoria = []

    total = len(CATALOGO)

    for numero, item in enumerate(CATALOGO, start=1):
        ticker = item["ticker"]
        nombre = item["nombre"]

        print(
            f"  [{numero:02d}/{total:02d}] "
            f"{ticker} — {nombre}"
        )

        try:
            precios = descargar(
                ticker,
                fecha_fin,
            )
        except Exception as exc:
            precios = pd.Series(dtype=float)
            estado = f"ERROR: {exc}"
        else:
            estado = (
                "CORRECTO"
                if len(precios) >= MIN_PRECIOS
                else "HISTORIA_INSUFICIENTE"
            )

        if precios.empty:
            auditoria.append(
                {
                    **item,
                    "estado": estado,
                    "n_precios": 0,
                    "fecha_inicio": pd.NaT,
                    "fecha_fin": pd.NaT,
                    "n_no_positivos": 0,
                    "retornos_extremos_pct": np.nan,
                    "cobertura_alineada_pct": 0.0,
                }
            )
            continue

        retorno_usd, n_no_positivos = retorno_seguro(
            precios
        )
        alineado = alinear_retorno(
            fechas,
            retorno_usd,
        )

        ret_usd = pd.Series(
            alineado["retorno"].to_numpy(),
            index=alineado["fecha_cuota"],
        )

        ret_pen = (
            (1.0 + ret_usd)
            * (1.0 + fx)
            - 1.0
        )

        identificador = slug(
            f"{item['categoria']}_{nombre}"
        )

        factor_usd = f"ret_USD_{identificador}"
        factor_pen = f"ret_PEN_{identificador}"

        panel[factor_usd] = panel[
            "fecha_cuota"
        ].map(ret_usd)
        panel[factor_pen] = panel[
            "fecha_cuota"
        ].map(ret_pen)

        for factor, moneda_modelo, transformacion in [
            (
                factor_usd,
                "USD",
                "retorno_continuo_en_USD",
            ),
            (
                factor_pen,
                "PEN",
                "retorno_USD_convertido_a_PEN",
            ),
        ]:
            catalogo.append(
                {
                    "factor": factor,
                    "ticker": ticker,
                    "nombre": nombre,
                    "categoria": item["categoria"],
                    "moneda_modelo": moneda_modelo,
                    "transformacion": transformacion,
                }
            )

        extremos = retorno_usd.abs().gt(
            UMBRAL_RETORNO_EXTREMO
        )

        auditoria.append(
            {
                **item,
                "estado": estado,
                "n_precios": int(len(precios)),
                "fecha_inicio": precios.index.min(),
                "fecha_fin": precios.index.max(),
                "n_no_positivos": n_no_positivos,
                "retornos_extremos_pct": float(
                    extremos.mean() * 100.0
                ),
                "cobertura_alineada_pct": float(
                    ret_usd.notna().mean()
                    * 100.0
                ),
                "edad_mediana_dias": float(
                    alineado["edad_dias"]
                    .dropna()
                    .median()
                ),
                "edad_p90_dias": float(
                    alineado["edad_dias"]
                    .dropna()
                    .quantile(0.90)
                ),
            }
        )

    return (
        panel,
        pd.DataFrame(catalogo),
        pd.DataFrame(auditoria),
    )


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
                        "n": int(len(par)),
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
                    "mejor_lag_train": mejor["lag"],
                    "n_train": mejor["n"],
                    "cobertura_train_pct": float(
                        datos[factor]
                        .notna()
                        .mean()
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
        base[
            base["fecha_cuota"].le(fin_train)
        ][["fecha_cuota"]]
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
                and abs(float(valor))
                >= UMBRAL_DUPLICADO
            ):
                filas.append(
                    {
                        "factor_1": col1,
                        "factor_2": col2,
                        "correlacion_train": float(
                            valor
                        ),
                    }
                )

    return pd.DataFrame(filas)


def crear_graficos(
    screen: pd.DataFrame,
    carpeta: Path,
) -> None:
    carpeta.mkdir(
        parents=True,
        exist_ok=True,
    )

    for afp in AFPS:
        top = (
            screen[
                screen["afp"].astype(str).eq(afp)
            ]
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
            f"Futuros, commodities y cripto — {afp}"
        )
        plt.tight_layout()
        plt.savefig(
            carpeta
            / f"01_futuros_cripto_{afp.lower()}.png",
            dpi=160,
            bbox_inches="tight",
        )
        plt.close()


def main() -> None:
    raiz = Path(__file__).resolve().parents[1]
    processed = raiz / "data" / "processed"
    graficos = processed / "graficos_modelo76"
    processed.mkdir(
        parents=True,
        exist_ok=True,
    )

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

    fechas = (
        base[["fecha_cuota"]]
        .dropna()
        .drop_duplicates()
        .sort_values("fecha_cuota")
    )

    fecha_fin_descarga = (
        max(
            pd.Timestamp.today().normalize(),
            pd.Timestamp(
                base["fecha_cuota"].max()
            )
            + pd.Timedelta(days=5),
        )
        + pd.Timedelta(days=1)
    ).strftime("%Y-%m-%d")

    print(
        "\nMÓDULO 76 — FUTUROS, COMMODITIES Y CRIPTO"
    )
    print("=" * 160)
    print(
        "Se prueban futuros nativos y criptoactivos en USD y PEN."
    )
    print(
        f"Descarga: {FECHA_INICIO} a {fecha_fin_descarga}"
    )

    factores, catalogo, auditoria = construir_factores(
        fechas,
        fecha_fin_descarga,
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
        "factores": (
            processed
            / "ca0001_modelo76_factores_futuros_cripto.csv"
        ),
        "catalogo": (
            processed
            / "ca0001_modelo76_catalogo_futuros_cripto.csv"
        ),
        "auditoria": (
            processed
            / "ca0001_modelo76_auditoria_descarga.csv"
        ),
        "screening": (
            processed
            / "ca0001_modelo76_screening_train.csv"
        ),
        "top": (
            processed
            / "ca0001_modelo76_top20_por_afp.csv"
        ),
        "duplicados": (
            processed
            / "ca0001_modelo76_factores_casi_duplicados.csv"
        ),
        "resumen": (
            processed
            / "ca0001_modelo76_resumen.json"
        ),
    }

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
    auditoria.to_csv(
        rutas["auditoria"],
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
        "version": "modelo76_futuros_commodities_cripto",
        "instrumentos_catalogo": len(CATALOGO),
        "instrumentos_descargados": int(
            auditoria["n_precios"].ge(
                MIN_PRECIOS
            ).sum()
        ),
        "factores_generados": int(
            len(factores.columns) - 1
        ),
        "pares_casi_duplicados": int(
            len(duplicados)
        ),
        "fin_entrenamiento": str(
            fin_train.date()
        ),
        "nota": (
            "Los futuros continuos pueden contener efectos de rollover. "
            "Cripto opera 24/7. Este módulo solo hace screening; "
            "el aporte incremental se evaluará después."
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

    print("\nAUDITORÍA DE DESCARGA")
    print("-" * 160)
    print(
        auditoria[
            [
                "ticker",
                "nombre",
                "categoria",
                "estado",
                "n_precios",
                "fecha_inicio",
                "fecha_fin",
                "n_no_positivos",
                "retornos_extremos_pct",
                "cobertura_alineada_pct",
                "edad_mediana_dias",
                "edad_p90_dias",
            ]
        ].to_string(index=False)
    )

    print("\nTOP 20 POR AFP — SOLO ENTRENAMIENTO")
    print("-" * 160)
    print(
        screen.groupby(
            "afp",
            group_keys=False,
        ).head(20)[
            [
                "afp",
                "ticker",
                "nombre",
                "categoria",
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

    print("\nARCHIVOS CREADOS")
    print("-" * 160)
    for ruta in rutas.values():
        print(f" - {ruta.resolve()}")
    print(f" - {graficos.resolve()}")

    print(
        "\nLECTURA:\n"
        "- Oro, petróleo, cobre y bonos ya tenían ETF/proxies; aquí "
        "se prueba el futuro nativo.\n"
        "- Un futuro continuo puede tener saltos de rollover, por eso "
        "se auditan retornos extremos y precios no positivos.\n"
        "- Cripto puede servir como proxy de apetito por riesgo, aunque "
        "no sea una tenencia confirmada de las AFP.\n"
        "- La correlación individual no basta: el módulo siguiente "
        "medirá si aportan algo después de los factores ya elegidos."
    )


if __name__ == "__main__":
    main()
