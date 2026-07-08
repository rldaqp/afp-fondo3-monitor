from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


AFPS = ["Habitat", "Integra", "Prima", "Profuturo"]
INTERVALOS_INTRADIA = [
    ("5m", "5d"),
    ("15m", "5d"),
    ("30m", "5d"),
    ("60m", "1mo"),
]
COBERTURA_REQUERIDA = 100.0
MINUTOS_VELA_SINTETICA = 30
ZONA_HORARIA = "America/Lima"


def asegurar_dependencias() -> None:
    faltantes = []

    for paquete, modulo in [
        ("yfinance", "yfinance"),
        ("plotly", "plotly"),
    ]:
        try:
            __import__(modulo)
        except ImportError:
            faltantes.append(paquete)

    if not faltantes:
        return

    proceso = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            *faltantes,
        ],
        check=False,
    )

    if proceso.returncode != 0:
        raise RuntimeError(
            "No se pudieron instalar las dependencias."
        )


def leer_csv(
    ruta: Path,
    obligatorio: bool = True,
) -> pd.DataFrame:
    if not ruta.exists():
        if obligatorio:
            raise FileNotFoundError(
                f"Falta el archivo: {ruta}"
            )
        return pd.DataFrame()

    ultimo_error: Exception | None = None

    for encoding in [
        "utf-8-sig",
        "latin-1",
        "utf-8",
    ]:
        try:
            return pd.read_csv(
                ruta,
                encoding=encoding,
            )
        except Exception as exc:
            ultimo_error = exc

    raise RuntimeError(
        f"No se pudo leer {ruta}: {ultimo_error}"
    )


def escribir_csv(
    df: pd.DataFrame,
    ruta: Path,
) -> None:
    df.to_csv(
        ruta,
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d %H:%M:%S",
    )


def adquirir_bloqueo(
    ruta: Path,
) -> int | None:
    ruta.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    if ruta.exists():
        edad = (
            time.time()
            - ruta.stat().st_mtime
        )

        if edad < 15 * 60:
            print(
                "Ya existe una actualización en curso. "
                "Se omite esta ejecución."
            )
            return None

        ruta.unlink(
            missing_ok=True
        )

    try:
        descriptor = os.open(
            str(ruta),
            os.O_CREAT
            | os.O_EXCL
            | os.O_WRONLY,
        )

        os.write(
            descriptor,
            str(os.getpid()).encode(
                "utf-8"
            ),
        )

        return descriptor

    except FileExistsError:
        return None


def liberar_bloqueo(
    descriptor: int | None,
    ruta: Path,
) -> None:
    if descriptor is not None:
        try:
            os.close(
                descriptor
            )
        except OSError:
            pass

    ruta.unlink(
        missing_ok=True
    )


def a_lima(
    indice: pd.Index,
) -> pd.DatetimeIndex:
    fechas = pd.DatetimeIndex(
        pd.to_datetime(
            indice,
            errors="coerce",
        )
    )

    try:
        if fechas.tz is not None:
            fechas = (
                fechas
                .tz_convert(
                    ZONA_HORARIA
                )
                .tz_localize(None)
            )
    except Exception:
        pass

    return fechas


def extraer_close(
    descarga: pd.DataFrame,
    ticker: str,
) -> pd.Series:
    if descarga.empty:
        return pd.Series(dtype=float)

    if isinstance(
        descarga.columns,
        pd.MultiIndex,
    ):
        for campo in [
            "Adj Close",
            "Close",
        ]:
            if campo not in descarga.columns.get_level_values(
                0
            ):
                continue

            bloque = descarga[
                campo
            ]

            if isinstance(
                bloque,
                pd.Series,
            ):
                serie = bloque
            elif ticker in bloque.columns:
                serie = bloque[
                    ticker
                ]
            elif bloque.shape[1] == 1:
                serie = bloque.iloc[
                    :,
                    0,
                ]
            else:
                continue

            serie = pd.to_numeric(
                serie,
                errors="coerce",
            )

            serie.index = a_lima(
                serie.index
            )

            return (
                serie.dropna()
                .loc[
                    lambda x:
                    ~x.index.isna()
                ]
                .loc[
                    lambda x:
                    ~x.index.duplicated(
                        keep="last"
                    )
                ]
                .sort_index()
            )

        return pd.Series(dtype=float)

    for campo in [
        "Adj Close",
        "Close",
    ]:
        if campo in descarga.columns:
            serie = pd.to_numeric(
                descarga[
                    campo
                ],
                errors="coerce",
            )

            serie.index = a_lima(
                serie.index
            )

            return (
                serie.dropna()
                .loc[
                    lambda x:
                    ~x.index.isna()
                ]
                .loc[
                    lambda x:
                    ~x.index.duplicated(
                        keep="last"
                    )
                ]
                .sort_index()
            )

    return pd.Series(dtype=float)


def descargar_intradia(
    ticker: str,
) -> tuple[
    pd.Series,
    str,
]:
    import yfinance as yf

    ultimo_error = ""

    for intervalo, periodo in (
        INTERVALOS_INTRADIA
    ):
        try:
            datos = yf.download(
                ticker,
                period=periodo,
                interval=intervalo,
                auto_adjust=False,
                progress=False,
                threads=False,
                prepost=False,
            )

            serie = extraer_close(
                datos,
                ticker,
            )

            if len(serie) >= 2:
                return (
                    serie,
                    intervalo,
                )

            ultimo_error = (
                f"sin datos suficientes "
                f"en {intervalo}"
            )

        except Exception as exc:
            ultimo_error = str(
                exc
            )

    return (
        pd.Series(dtype=float),
        ultimo_error,
    )


def descargar_diario(
    ticker: str,
) -> pd.Series:
    import yfinance as yf

    try:
        datos = yf.download(
            ticker,
            period="3mo",
            interval="1d",
            auto_adjust=False,
            progress=False,
            threads=False,
            prepost=False,
        )

        return extraer_close(
            datos,
            ticker,
        )

    except Exception:
        return pd.Series(
            dtype=float
        )


def cierres_sesion(
    serie: pd.Series,
) -> pd.Series:
    if serie.empty:
        return pd.Series(
            dtype=float
        )

    x = (
        serie.dropna()
        .sort_index()
    )

    return x.groupby(
        x.index.normalize()
    ).last()


def retorno_actual_desde_cierre_previo(
    serie: pd.Series,
) -> tuple[
    float,
    pd.Timestamp | None,
    float,
]:
    if serie.empty:
        return (
            np.nan,
            None,
            np.nan,
        )

    x = serie.dropna().sort_index()

    sesiones = cierres_sesion(
        x
    )

    if len(sesiones) < 2:
        return (
            np.nan,
            x.index[-1],
            float(x.iloc[-1]),
        )

    cierre_previo = float(
        sesiones.iloc[-2]
    )

    precio_actual = float(
        x.iloc[-1]
    )

    retorno = (
        precio_actual
        / cierre_previo
        - 1.0
    )

    return (
        retorno,
        x.index[-1],
        precio_actual,
    )


def retorno_rezagado_diario(
    serie_diaria: pd.Series,
    fecha_objetivo: pd.Timestamp,
) -> float:
    if serie_diaria.empty:
        return np.nan

    x = (
        serie_diaria.dropna()
        .sort_index()
    )

    retornos = x.pct_change(
        fill_method=None
    )

    anteriores = retornos[
        retornos.index.normalize()
        < fecha_objetivo.normalize()
    ].dropna()

    if anteriores.empty:
        return np.nan

    return float(
        anteriores.iloc[-1]
    )


def alinear_y_multiplicar(
    activo: pd.Series,
    fx: pd.Series,
) -> pd.Series:
    if activo.empty or fx.empty:
        return pd.Series(
            dtype=float
        )

    union = (
        activo.index
        .union(
            fx.index
        )
        .sort_values()
    )

    activo_a = activo.reindex(
        union
    ).ffill()

    fx_a = fx.reindex(
        union
    ).ffill()

    convertido = (
        activo_a
        * fx_a
    ).dropna()

    return convertido[
        convertido.index.isin(
            activo.index
        )
    ]


def es_factor_pen(
    factor: str,
) -> bool:
    return (
        factor.startswith(
            "ret_PEN_"
        )
        and not factor.startswith(
            "ret_BVL_PEN_"
        )
    )


def obtener_base_cuota(
    afp: str,
    fecha_objetivo: pd.Timestamp,
    base: pd.DataFrame,
    pronosticos: pd.DataFrame,
) -> tuple[
    pd.Timestamp,
    float,
]:
    oficiales = base[
        base["afp"]
        .astype(str)
        .eq(afp)
    ].copy()

    oficiales[
        "fecha_cuota"
    ] = pd.to_datetime(
        oficiales[
            "fecha_cuota"
        ],
        errors="coerce",
    ).dt.normalize()

    oficiales[
        "cuota_sbs"
    ] = pd.to_numeric(
        oficiales[
            "cuota_sbs"
        ],
        errors="coerce",
    )

    oficiales = oficiales[
        oficiales[
            "fecha_cuota"
        ].lt(
            fecha_objetivo
        )
    ].dropna(
        subset=[
            "fecha_cuota",
            "cuota_sbs",
        ]
    )

    if oficiales.empty:
        raise RuntimeError(
            f"No existe cuota base para {afp}."
        )

    oficial = oficiales.sort_values(
        "fecha_cuota"
    ).iloc[-1]

    fecha_base = pd.Timestamp(
        oficial["fecha_cuota"]
    )

    cuota_base = float(
        oficial["cuota_sbs"]
    )

    if not pronosticos.empty:
        x = pronosticos[
            pronosticos["afp"]
            .astype(str)
            .eq(afp)
        ].copy()

        x[
            "fecha_objetivo"
        ] = pd.to_datetime(
            x[
                "fecha_objetivo"
            ],
            errors="coerce",
        ).dt.normalize()

        x[
            "cuota_estimada"
        ] = pd.to_numeric(
            x[
                "cuota_estimada"
            ],
            errors="coerce",
        )

        x[
            "cobertura_factores_pct"
        ] = pd.to_numeric(
            x[
                "cobertura_factores_pct"
            ],
            errors="coerce",
        )

        x = x[
            x[
                "fecha_objetivo"
            ].gt(
                fecha_base
            )
            & x[
                "fecha_objetivo"
            ].lt(
                fecha_objetivo
            )
            & x[
                "cobertura_factores_pct"
            ].ge(
                COBERTURA_REQUERIDA
            )
        ].dropna(
            subset=[
                "fecha_objetivo",
                "cuota_estimada",
            ]
        )

        if not x.empty:
            pron = x.sort_values(
                "fecha_objetivo"
            ).iloc[-1]

            fecha_base = pd.Timestamp(
                pron[
                    "fecha_objetivo"
                ]
            )

            cuota_base = float(
                pron[
                    "cuota_estimada"
                ]
            )

    return (
        fecha_base,
        cuota_base,
    )


def calcular_snapshot(
    raiz: Path,
) -> pd.DataFrame:
    processed = (
        raiz
        / "data"
        / "processed"
    )

    canasta = leer_csv(
        processed
        / "ca0001_modelo78_canasta_final_podada.csv"
    )

    parametros = leer_csv(
        processed
        / "ca0001_modelo79c_parametros_ecuaciones.csv"
    )

    base = leer_csv(
        processed
        / "ca0001_modelo56_base_alineada.csv"
    )

    pronosticos = leer_csv(
        processed
        / "ca0001_modelo79_primer_pronostico_congelado.csv",
        obligatorio=False,
    )

    for columna in [
        "lag",
        "orden",
    ]:
        canasta[
            columna
        ] = pd.to_numeric(
            canasta[
                columna
            ],
            errors="coerce",
        ).fillna(
            0
        ).astype(
            int
        )

    parametros[
        "lag"
    ] = pd.to_numeric(
        parametros[
            "lag"
        ],
        errors="coerce",
    ).fillna(
        0
    ).astype(
        int
    )

    tickers = sorted(
        set(
            canasta[
                "ticker"
            ]
            .dropna()
            .astype(str)
        )
        | {"PEN=X"}
    )

    intradia: dict[
        str,
        pd.Series,
    ] = {}

    diarios: dict[
        str,
        pd.Series,
    ] = {}

    intervalos: dict[
        str,
        str,
    ] = {}

    for numero, ticker in enumerate(
        tickers,
        start=1,
    ):
        print(
            f"[{numero:02d}/{len(tickers):02d}] "
            f"Actualizando {ticker}"
        )

        serie_i, intervalo = (
            descargar_intradia(
                ticker
            )
        )

        intradia[
            ticker
        ] = serie_i

        intervalos[
            ticker
        ] = intervalo

        diarios[
            ticker
        ] = descargar_diario(
            ticker
        )

    epu = intradia.get(
        "EPU",
        pd.Series(dtype=float),
    )

    if epu.empty:
        print(
            "SIN NUEVO SNAPSHOT: EPU no tiene datos intradía "
            "disponibles en este momento. No se fabricará una "
            "estimación."
        )
        return pd.DataFrame()

    fecha_objetivo = pd.Timestamp(
        epu.index[-1]
    ).normalize()

    ahora_lima = pd.Timestamp.now(
        tz=ZONA_HORARIA
    ).tz_localize(
        None
    )

    # No guardar fines de semana, feriados ni sesiones antiguas.
    # Esto no es un error: simplemente no existe una observación
    # nueva y válida para incorporar al historial.
    if (
        fecha_objetivo.dayofweek
        >= 5
        or (
            ahora_lima.normalize()
            - fecha_objetivo
        ).days
        > 0
    ):
        print(
            "SIN NUEVO SNAPSHOT: la última sesión intradía "
            f"disponible es {fecha_objetivo.date()} y hoy es "
            f"{ahora_lima.date()}. No se generará una cuota "
            "sintética con datos antiguos."
        )
        return pd.DataFrame()

    fx_i = intradia.get(
        "PEN=X",
        pd.Series(dtype=float),
    )

    fx_d = diarios.get(
        "PEN=X",
        pd.Series(dtype=float),
    )

    filas = []

    for afp in AFPS:
        canasta_afp = (
            canasta[
                canasta[
                    "afp"
                ]
                .astype(str)
                .eq(afp)
            ]
            .sort_values(
                "orden"
            )
            .copy()
        )

        if canasta_afp.empty:
            continue

        contribuciones = []
        detalles = []
        disponibles = 0

        interceptos = []

        for _, fila in canasta_afp.iterrows():
            factor = str(
                fila[
                    "factor"
                ]
            )

            ticker = str(
                fila[
                    "ticker"
                ]
            )

            lag = int(
                fila[
                    "lag"
                ]
            )

            p = parametros[
                parametros[
                    "afp"
                ]
                .astype(str)
                .eq(afp)
                & parametros[
                    "factor"
                ]
                .astype(str)
                .eq(factor)
                & parametros[
                    "lag"
                ].eq(lag)
            ]

            if p.empty:
                detalles.append(
                    {
                        "factor": factor,
                        "ticker": ticker,
                        "estado": (
                            "SIN PARAMETROS"
                        ),
                    }
                )
                continue

            media = float(
                p[
                    "media_entrenamiento"
                ].iloc[0]
            )

            desviacion = float(
                p[
                    "desviacion_entrenamiento"
                ].iloc[0]
            )

            beta = float(
                p[
                    "coeficiente_estandarizado"
                ].iloc[0]
            )

            interceptos.append(
                float(
                    p[
                        "intercepto_estandarizado"
                    ].iloc[0]
                )
            )

            serie_i = intradia.get(
                ticker,
                pd.Series(dtype=float),
            )

            serie_d = diarios.get(
                ticker,
                pd.Series(dtype=float),
            )

            if es_factor_pen(
                factor
            ):
                serie_i_modelo = (
                    alinear_y_multiplicar(
                        serie_i,
                        fx_i,
                    )
                )

                serie_d_modelo = (
                    alinear_y_multiplicar(
                        serie_d,
                        fx_d,
                    )
                )
            else:
                serie_i_modelo = (
                    serie_i
                )

                serie_d_modelo = (
                    serie_d
                )

            if lag == 0:
                retorno, marca, _ = (
                    retorno_actual_desde_cierre_previo(
                        serie_i_modelo
                    )
                )
            else:
                retorno = (
                    retorno_rezagado_diario(
                        serie_d_modelo,
                        fecha_objetivo,
                    )
                )

                marca = (
                    serie_d_modelo.index[-1]
                    if not serie_d_modelo.empty
                    else None
                )

            if (
                pd.isna(
                    retorno
                )
                or desviacion == 0
            ):
                detalles.append(
                    {
                        "factor": factor,
                        "ticker": ticker,
                        "estado": (
                            "SIN DATO VALIDO"
                        ),
                    }
                )
                continue

            z = (
                retorno
                - media
            ) / desviacion

            aporte = (
                beta
                * z
            )

            contribuciones.append(
                aporte
            )

            disponibles += 1

            detalles.append(
                {
                    "factor": factor,
                    "ticker": ticker,
                    "lag": lag,
                    "retorno_factor_pct": (
                        retorno
                        * 100.0
                    ),
                    "z": z,
                    "aporte_pct": (
                        aporte
                        * 100.0
                    ),
                    "ultimo_dato": (
                        str(marca)
                        if marca is not None
                        else ""
                    ),
                    "intervalo": intervalos.get(
                        ticker,
                        "",
                    ),
                    "estado": "CORRECTO",
                }
            )

        total_factores = len(
            canasta_afp
        )

        cobertura = (
            disponibles
            / max(
                total_factores,
                1,
            )
            * 100.0
        )

        if cobertura < COBERTURA_REQUERIDA:
            print(
                f"{afp}: cobertura "
                f"{cobertura:.1f}%, "
                "no se registra."
            )
            continue

        intercepto = (
            interceptos[0]
            if interceptos
            else 0.0
        )

        retorno_estimado = (
            intercepto
            + float(
                np.sum(
                    contribuciones
                )
            )
        )

        fecha_base, cuota_base = (
            obtener_base_cuota(
                afp,
                fecha_objetivo,
                base,
                pronosticos,
            )
        )

        cuota_estimada = (
            cuota_base
            * (
                1.0
                + retorno_estimado
            )
        )

        marca_snapshot = (
            ahora_lima.floor(
                "5min"
            )
        )

        filas.append(
            {
                "timestamp": marca_snapshot,
                "fecha_objetivo": (
                    fecha_objetivo
                ),
                "afp": afp,
                "fecha_base": fecha_base,
                "cuota_base": cuota_base,
                "retorno_estimado_pct": (
                    retorno_estimado
                    * 100.0
                ),
                "cuota_estimada_intradia": (
                    cuota_estimada
                ),
                "cobertura_pct": cobertura,
                "n_factores": (
                    total_factores
                ),
                "n_disponibles": (
                    disponibles
                ),
                "detalle_json": json.dumps(
                    detalles,
                    ensure_ascii=False,
                ),
            }
        )

    columnas = [
        "afp",
        "fecha_objetivo",
        "bloque_30min",
        "open",
        "high",
        "low",
        "close",
        "n_snapshots",
    ]
    return pd.DataFrame(
        filas,
        columns=columnas,
    )


def anexar_historial(
    nuevos: pd.DataFrame,
    ruta: Path,
) -> pd.DataFrame:
    anterior = leer_csv(
        ruta,
        obligatorio=False,
    )

    combinado = pd.concat(
        [
            anterior,
            nuevos,
        ],
        ignore_index=True,
    )

    combinado[
        "timestamp"
    ] = pd.to_datetime(
        combinado[
            "timestamp"
        ],
        errors="coerce",
    )

    combinado[
        "fecha_objetivo"
    ] = pd.to_datetime(
        combinado[
            "fecha_objetivo"
        ],
        errors="coerce",
    ).dt.normalize()

    combinado = (
        combinado.dropna(
            subset=[
                "timestamp",
                "afp",
                "cuota_estimada_intradia",
            ]
        )
        .sort_values(
            [
                "timestamp",
                "afp",
            ]
        )
        .drop_duplicates(
            subset=[
                "timestamp",
                "afp",
            ],
            keep="last",
        )
        .reset_index(
            drop=True
        )
    )

    escribir_csv(
        combinado,
        ruta,
    )

    return combinado


def crear_velas_30min(
    historial: pd.DataFrame,
) -> pd.DataFrame:
    if historial.empty:
        return pd.DataFrame()

    x = historial.copy()

    x[
        "timestamp"
    ] = pd.to_datetime(
        x[
            "timestamp"
        ],
        errors="coerce",
    )

    x[
        "bloque_30min"
    ] = x[
        "timestamp"
    ].dt.floor(
        f"{MINUTOS_VELA_SINTETICA}min"
    )

    filas = []

    for (
        afp,
        fecha,
        bloque,
    ), grupo in x.groupby(
        [
            "afp",
            "fecha_objetivo",
            "bloque_30min",
        ]
    ):
        grupo = grupo.sort_values(
            "timestamp"
        )

        if len(grupo) < 2:
            continue

        valores = pd.to_numeric(
            grupo[
                "cuota_estimada_intradia"
            ],
            errors="coerce",
        ).dropna()

        if len(valores) < 2:
            continue

        filas.append(
            {
                "afp": afp,
                "fecha_objetivo": fecha,
                "bloque_30min": bloque,
                "open": float(
                    valores.iloc[0]
                ),
                "high": float(
                    valores.max()
                ),
                "low": float(
                    valores.min()
                ),
                "close": float(
                    valores.iloc[-1]
                ),
                "n_snapshots": int(
                    len(valores)
                ),
            }
        )

    return pd.DataFrame(
        filas
    )


def grafico_afp_html(
    afp: str,
    historial: pd.DataFrame,
    velas: pd.DataFrame,
) -> str:
    columnas_vela = [
        "afp",
        "fecha_objetivo",
        "bloque_30min",
        "open",
        "high",
        "low",
        "close",
        "n_snapshots",
    ]
    if velas.empty or "afp" not in velas.columns:
        velas = pd.DataFrame(columns=columnas_vela)

    import plotly.graph_objects as go
    import plotly.io as pio
    from plotly.subplots import make_subplots

    h = (
        historial[
            historial[
                "afp"
            ]
            .astype(str)
            .eq(afp)
        ]
        .sort_values(
            "timestamp"
        )
        .copy()
    )

    v = (
        velas[
            velas[
                "afp"
            ]
            .astype(str)
            .eq(afp)
        ]
        .sort_values(
            "bloque_30min"
        )
        .copy()
    )

    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=False,
        vertical_spacing=0.13,
        row_heights=[
            0.42,
            0.58,
        ],
        subplot_titles=[
            (
                "Estimación cada cinco minutos"
            ),
            (
                "Velas sintéticas de 30 minutos"
            ),
        ],
    )

    if not h.empty:
        fecha_ultima = h[
            "fecha_objetivo"
        ].max()

        h_actual = h[
            h[
                "fecha_objetivo"
            ].eq(
                fecha_ultima
            )
        ]

        fig.add_trace(
            go.Scatter(
                x=h_actual[
                    "timestamp"
                ],
                y=h_actual[
                    "cuota_estimada_intradia"
                ],
                mode="lines+markers",
                name=(
                    "Cuota estimada "
                    "cada 5 min"
                ),
                hovertemplate=(
                    "<b>%{x|%d/%m %H:%M}</b><br>"
                    "Cuota estimada: "
                    "%{y:.6f}"
                    "<extra></extra>"
                ),
            ),
            row=1,
            col=1,
        )

        cuota_base = float(
            h_actual[
                "cuota_base"
            ].iloc[-1]
        )

        fig.add_hline(
            y=cuota_base,
            line_dash="dot",
            annotation_text=(
                "Cuota base"
            ),
            row=1,
            col=1,
        )

    if not v.empty:
        etiquetas = [
            pd.Timestamp(
                x
            ).strftime(
                "%d/%m %H:%M"
            )
            for x in v[
                "bloque_30min"
            ]
        ]

        fig.add_trace(
            go.Candlestick(
                x=etiquetas,
                open=v["open"],
                high=v["high"],
                low=v["low"],
                close=v["close"],
                increasing=dict(
                    line=dict(
                        color="#159447",
                        width=2,
                    ),
                    fillcolor="#37b865",
                ),
                decreasing=dict(
                    line=dict(
                        color="#d52236",
                        width=2,
                    ),
                    fillcolor="#ef334e",
                ),
                whiskerwidth=0.9,
                name=(
                    "Vela sintética "
                    "30 min"
                ),
                hovertemplate=(
                    "<b>%{x}</b><br>"
                    "Primera estimación: "
                    "%{open:.6f}<br>"
                    "Máxima: %{high:.6f}<br>"
                    "Mínima: %{low:.6f}<br>"
                    "Última: %{close:.6f}"
                    "<extra></extra>"
                ),
            ),
            row=2,
            col=1,
        )

    fig.update_layout(
        title=dict(
            text=(
                f"{afp}: evolución intradía "
                "del valor cuota estimado"
            ),
            x=0.02,
        ),
        height=760,
        margin=dict(
            l=65,
            r=28,
            t=90,
            b=60,
        ),
        paper_bgcolor="white",
        plot_bgcolor="white",
        showlegend=True,
        hovermode="x unified",
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="left",
            x=0,
        ),
    )

    fig.update_xaxes(
        showgrid=True,
        gridcolor="#e7edf4",
        row=1,
        col=1,
    )

    fig.update_yaxes(
        title="Valor cuota estimado",
        showgrid=True,
        gridcolor="#e7edf4",
        fixedrange=False,
        row=1,
        col=1,
    )

    fig.update_xaxes(
        type="category",
        showgrid=True,
        gridcolor="#e7edf4",
        rangeslider=dict(
            visible=False
        ),
        row=2,
        col=1,
    )

    fig.update_yaxes(
        title="Valor cuota sintético",
        showgrid=True,
        gridcolor="#e7edf4",
        fixedrange=False,
        row=2,
        col=1,
    )

    return pio.to_html(
        fig,
        full_html=False,
        include_plotlyjs=False,
        config={
            "responsive": True,
            "displaylogo": False,
            "scrollZoom": True,
            "doubleClick": "reset",
        },
    )


def crear_html(
    processed: Path,
    historial: pd.DataFrame,
    velas: pd.DataFrame,
) -> Path:
    import plotly  # noqa: F401

    secciones = []

    for afp in AFPS:
        x = historial[
            historial[
                "afp"
            ]
            .astype(str)
            .eq(afp)
        ].sort_values(
            "timestamp"
        )

        if x.empty:
            resumen = (
                "Todavía no existen "
                "estimaciones intradía."
            )
        else:
            ultima = x.iloc[-1]

            resumen = (
                f"Última estimación: "
                f"{float(ultima['cuota_estimada_intradia']):.6f} "
                f"· Variación: "
                f"{float(ultima['retorno_estimado_pct']):+.3f}% "
                f"· Cobertura: "
                f"{float(ultima['cobertura_pct']):.0f}% "
                f"· Hora: "
                f"{pd.Timestamp(ultima['timestamp']).strftime('%d/%m/%Y %H:%M')}"
            )

        secciones.append(
            f"""
            <section class="seccion" id="{afp.lower()}">
              <h2>{afp}</h2>
              <p class="resumen">
                {resumen}
              </p>
              {grafico_afp_html(
                  afp,
                  historial,
                  velas,
              )}
            </section>
            """
        )

    ruta = (
        processed
        / "ca0001_modelo99_cuota_sintetica_intradia.html"
    )

    documento = f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport"
      content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="300">
<title>Cuota estimada intradía AFP</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
:root {{
  --azul:#123f73;
  --azul2:#2768a8;
  --fondo:#f3f6fb;
  --borde:#d8e2ef;
  --texto:#1f2937;
  --suave:#64748b;
}}
* {{ box-sizing:border-box; }}
body {{
  margin:0;
  background:var(--fondo);
  color:var(--texto);
  font-family:Arial, Helvetica, sans-serif;
}}
main {{
  width:min(1500px,96%);
  margin:auto;
  padding:22px 0 55px;
}}
header {{
  color:white;
  background:linear-gradient(135deg,var(--azul),var(--azul2));
  border-radius:16px;
  padding:25px 28px;
}}
header h1 {{
  margin:0 0 8px;
  font-size:30px;
}}
.boton {{
  display:inline-block;
  text-decoration:none;
  background:white;
  color:var(--azul);
  border:0;
  border-radius:9px;
  padding:10px 15px;
  margin:12px 7px 0 0;
  font-weight:bold;
  cursor:pointer;
}}
.aviso {{
  background:#fff7d6;
  border-left:6px solid #d7a400;
  border-radius:9px;
  padding:14px 16px;
  margin:16px 0;
  line-height:1.55;
}}
.seccion {{
  background:white;
  border:1px solid var(--borde);
  border-radius:15px;
  padding:20px;
  margin:18px 0;
  box-shadow:0 4px 15px rgba(20,50,90,.06);
}}
.seccion h2 {{
  color:var(--azul);
  margin:0 0 8px;
}}
.resumen {{
  color:var(--suave);
  font-weight:bold;
}}
</style>
</head>
<body>
<main>
<header>
  <h1>Valor cuota estimado durante el día</h1>
  <p>
    Actualización local:
    <strong>
      {datetime.now().strftime("%d/%m/%Y %H:%M:%S")}
    </strong>
  </p>

  <a class="boton"
     href="ca0001_modelo80_dashboard.html">
    Monitor principal
  </a>

  <a class="boton"
     href="ca0001_modelo92_indicadores_didacticos.html">
    Indicadores del modelo
  </a>

  <a class="boton"
     href="ca0001_modelo97_simulador_monto_fondo3.html">
    Simular monto
  </a>

  <button class="boton"
          onclick="location.reload()">
    Recargar página
  </button>
</header>

<div class="aviso">
  <strong>Qué representa:</strong>
  la línea muestra una estimación recalculada cada cinco minutos.
  Las velas agrupan seis estimaciones en bloques de treinta minutos:
  primera, máxima, mínima y última estimación del bloque.
  Son velas sintéticas del modelo, no cuotas oficiales ni operaciones
  ejecutadas por la AFP. Solo se registran cuando la cobertura es 100%.
</div>

{''.join(secciones)}
</main>
</body>
</html>
"""

    ruta.write_text(
        documento,
        encoding="utf-8",
    )

    return ruta



def crear_html_espera(
    processed: Path,
    mensaje: str,
) -> Path:
    ruta = (
        processed
        / "ca0001_modelo99_cuota_sintetica_intradia.html"
    )

    documento = f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport"
      content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="300">
<title>Cuota estimada intradía AFP</title>
<style>
:root {{
  --azul:#123f73;
  --azul2:#2768a8;
  --fondo:#f3f6fb;
  --borde:#d8e2ef;
  --texto:#1f2937;
}}
* {{ box-sizing:border-box; }}
body {{
  margin:0;
  background:var(--fondo);
  color:var(--texto);
  font-family:Arial, Helvetica, sans-serif;
}}
main {{
  width:min(1050px,94%);
  margin:auto;
  padding:28px 0;
}}
header {{
  color:white;
  background:linear-gradient(135deg,var(--azul),var(--azul2));
  border-radius:16px;
  padding:25px 28px;
}}
.tarjeta {{
  margin-top:18px;
  background:white;
  border:1px solid var(--borde);
  border-radius:15px;
  padding:24px;
}}
.estado {{
  background:#fff7d6;
  border-left:6px solid #d7a400;
  padding:15px;
  border-radius:9px;
  line-height:1.55;
}}
.boton {{
  display:inline-block;
  text-decoration:none;
  background:white;
  color:var(--azul);
  border-radius:9px;
  padding:10px 15px;
  margin:12px 7px 0 0;
  font-weight:bold;
}}
</style>
</head>
<body>
<main>
<header>
  <h1>Valor cuota estimado durante el día</h1>
  <p>
    Actualización local:
    <strong>
      {datetime.now().strftime("%d/%m/%Y %H:%M:%S")}
    </strong>
  </p>
  <a class="boton"
     href="ca0001_modelo80_dashboard.html">
    Monitor principal
  </a>
  <a class="boton"
     href="ca0001_modelo92_indicadores_didacticos.html">
    Indicadores del modelo
  </a>
</header>

<section class="tarjeta">
  <h2>Esperando una sesión válida</h2>
  <div class="estado">
    {mensaje}
  </div>
  <p>
    El sistema no crea velas con datos antiguos, fines de semana,
    feriados ni cobertura incompleta. La primera línea aparecerá
    cuando exista una sesión actual y estén disponibles todos los
    factores del modelo.
  </p>
  <p>
    La primera vela sintética de 30 minutos necesitará al menos
    dos estimaciones válidas dentro del bloque; se completará
    progresivamente a medida que se acumulen observaciones.
  </p>
</section>
</main>
</body>
</html>
"""

    ruta.write_text(
        documento,
        encoding="utf-8",
    )

    return ruta

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Registra y grafica la cuota estimada intradía."
        )
    )

    parser.add_argument(
        "--abrir",
        action="store_true",
        help="Abre la página al terminar.",
    )

    args = parser.parse_args()

    asegurar_dependencias()

    raiz = Path(
        __file__
    ).resolve().parents[1]

    processed = (
        raiz
        / "data"
        / "processed"
    )

    bloqueo = (
        processed
        / ".modelo99_intradia.lock"
    )

    descriptor = adquirir_bloqueo(
        bloqueo
    )

    if descriptor is None:
        return

    try:
        nuevos = calcular_snapshot(
            raiz
        )

        historial_ruta = (
            processed
            / "ca0001_modelo99_historial_intradia_cuota.csv"
        )

        if nuevos.empty:
            historial = leer_csv(
                historial_ruta,
                obligatorio=False,
            )
        else:
            historial = anexar_historial(
                nuevos,
                historial_ruta,
            )

        if historial.empty:
            mensaje = (
                "No existe una sesión intradía actual con 100% "
                "de cobertura. Esto es normal fuera de días de "
                "mercado o antes de que todos los factores estén "
                "disponibles."
            )

            pagina = crear_html_espera(
                processed,
                mensaje,
            )

            print(
                "Todavía no hay snapshots válidos. "
                "Se creó una página de espera sin inventar datos."
            )
            print(
                f"Página: {pagina.resolve()}"
            )

            if args.abrir:
                webbrowser.open(
                    pagina.resolve().as_uri()
                )

            return

        historial[
            "timestamp"
        ] = pd.to_datetime(
            historial[
                "timestamp"
            ],
            errors="coerce",
        )

        historial[
            "fecha_objetivo"
        ] = pd.to_datetime(
            historial[
                "fecha_objetivo"
            ],
            errors="coerce",
        ).dt.normalize()

        velas = crear_velas_30min(
            historial
        )

        escribir_csv(
            velas,
            processed
            / "ca0001_modelo99_velas_sinteticas_30min.csv",
        )

        pagina = crear_html(
            processed,
            historial,
            velas,
        )

        print(
            "\nCUOTA SINTÉTICA INTRADÍA ACTUALIZADA"
        )
        print("=" * 100)
        print(
            f"Nuevos snapshots: {len(nuevos)}"
        )
        print(
            f"Historial total: {len(historial)}"
        )
        print(
            f"Velas de 30 min: {len(velas)}"
        )
        print(
            f"Página: {pagina.resolve()}"
        )

        if args.abrir:
            webbrowser.open(
                pagina.resolve().as_uri()
            )

    finally:
        liberar_bloqueo(
            descriptor,
            bloqueo,
        )


if __name__ == "__main__":
    main()
