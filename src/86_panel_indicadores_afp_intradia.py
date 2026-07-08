from __future__ import annotations

import argparse
import html
import subprocess
import sys
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


AFPS = ["Habitat", "Integra", "Prima", "Profuturo"]
INTERVALOS = [
    ("5m", "5d"),
    ("15m", "5d"),
    ("30m", "5d"),
    ("60m", "1mo"),
    ("1d", "3mo"),
]
COBERTURA_MINIMA = 60.0


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

    print(
        "Instalando dependencias: "
        + ", ".join(faltantes)
    )

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
            raise FileNotFoundError(f"Falta el archivo: {ruta}")
        return pd.DataFrame()

    ultimo_error: Exception | None = None

    for encoding in ["utf-8-sig", "latin-1", "utf-8"]:
        try:
            return pd.read_csv(ruta, encoding=encoding)
        except Exception as exc:
            ultimo_error = exc

    raise RuntimeError(f"No se pudo leer {ruta}: {ultimo_error}")


def extraer_close(
    descarga: pd.DataFrame,
    ticker: str,
) -> pd.Series:
    if descarga.empty:
        return pd.Series(dtype=float)

    if isinstance(descarga.columns, pd.MultiIndex):
        for campo in ["Adj Close", "Close"]:
            if campo in descarga.columns.get_level_values(0):
                bloque = descarga[campo]

                if isinstance(bloque, pd.Series):
                    serie = bloque
                elif ticker in bloque.columns:
                    serie = bloque[ticker]
                elif bloque.shape[1] == 1:
                    serie = bloque.iloc[:, 0]
                else:
                    continue

                return pd.to_numeric(
                    serie,
                    errors="coerce",
                )

        return pd.Series(dtype=float)

    for campo in ["Adj Close", "Close"]:
        if campo in descarga.columns:
            return pd.to_numeric(
                descarga[campo],
                errors="coerce",
            )

    return pd.Series(dtype=float)


def descargar_serie(
    ticker: str,
) -> tuple[pd.Series, str, str]:
    import yfinance as yf

    ultimo_error = ""

    for intervalo, periodo in INTERVALOS:
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
            ).dropna()

            if len(serie) < 2:
                ultimo_error = (
                    f"sin datos suficientes en {intervalo}"
                )
                continue

            indice = pd.DatetimeIndex(
                pd.to_datetime(
                    serie.index,
                    errors="coerce",
                )
            )

            serie.index = indice
            serie = serie[
                ~serie.index.isna()
            ]

            try:
                if serie.index.tz is not None:
                    serie.index = (
                        serie.index
                        .tz_convert(
                            "America/Lima"
                        )
                        .tz_localize(None)
                    )
            except Exception:
                pass

            serie = serie[
                ~serie.index.duplicated(
                    keep="last"
                )
            ].sort_index()

            if len(serie) >= 2:
                return (
                    serie,
                    intervalo,
                    periodo,
                )

        except Exception as exc:
            ultimo_error = str(exc)

    return (
        pd.Series(dtype=float),
        "SIN_DATOS",
        ultimo_error,
    )


def clasificar_transformacion(
    factor: str,
) -> str:
    if factor.startswith("ret_PEN_"):
        return "CONVERTIR_A_PEN"

    if factor.startswith("ret_BVL_PEN_"):
        return "LOCAL_PEN"

    if factor.startswith("ret_IDX_LOCAL_"):
        return "INDICE_LOCAL"

    if factor.startswith("ret_USD_"):
        return "USD"

    return "OTRO"


def alinear_fx(
    precio: pd.Series,
    fx: pd.Series,
) -> pd.Series:
    if precio.empty or fx.empty:
        return pd.Series(dtype=float)

    union = (
        precio.index
        .union(fx.index)
        .sort_values()
    )

    precio_a = precio.reindex(
        union
    ).ffill(
        limit=30
    )

    fx_a = fx.reindex(
        union
    ).ffill(
        limit=30
    )

    convertido = (
        precio_a * fx_a
    ).dropna()

    return convertido[
        convertido.index.isin(
            precio.index
        )
    ]


def retorno_desde_cierre_previo(
    serie: pd.Series,
) -> tuple[
    float,
    float,
    float,
    pd.Timestamp | None,
]:
    if serie.empty:
        return (
            np.nan,
            np.nan,
            np.nan,
            None,
        )

    x = serie.dropna().sort_index()

    if len(x) < 2:
        return (
            float(x.iloc[-1]),
            np.nan,
            np.nan,
            x.index[-1],
        )

    fechas = pd.Series(
        x.index.date,
        index=x.index,
    )

    dias = list(
        pd.unique(fechas)
    )

    ultimo_precio = float(
        x.iloc[-1]
    )

    if len(dias) >= 2:
        dia_actual = dias[-1]
        dia_previo = dias[-2]

        previo = x[
            fechas.eq(dia_previo)
        ]

        if previo.empty:
            base = float(
                x.iloc[0]
            )
        else:
            base = float(
                previo.iloc[-1]
            )
    else:
        base = float(
            x.iloc[0]
        )

    if base == 0:
        retorno = np.nan
    else:
        retorno = (
            ultimo_precio / base - 1.0
        )

    return (
        ultimo_precio,
        base,
        retorno,
        x.index[-1],
    )


def serie_variacion_pct(
    serie: pd.Series,
) -> pd.Series:
    if serie.empty:
        return pd.Series(dtype=float)

    x = serie.dropna().sort_index()

    if x.empty:
        return pd.Series(dtype=float)

    fechas = pd.Series(
        x.index.date,
        index=x.index,
    )

    dias = list(
        pd.unique(fechas)
    )

    if len(dias) >= 2:
        previo = x[
            fechas.eq(
                dias[-2]
            )
        ]

        base = (
            float(previo.iloc[-1])
            if not previo.empty
            else float(x.iloc[0])
        )
    else:
        base = float(
            x.iloc[0]
        )

    if base == 0:
        return pd.Series(
            np.nan,
            index=x.index,
        )

    return (
        x / base - 1.0
    ) * 100.0


def construir_panel(
    canasta: pd.DataFrame,
    parametros: pd.DataFrame,
) -> tuple[
    pd.DataFrame,
    dict[str, pd.Series],
    pd.DataFrame,
]:
    requeridos = (
        canasta[
            [
                "factor",
                "ticker",
                "nombre",
                "afp",
                "lag",
                "orden",
            ]
        ]
        .copy()
        .sort_values(
            [
                "afp",
                "orden",
            ]
        )
    )

    tickers = sorted(
        set(
            requeridos[
                "ticker"
            ]
            .dropna()
            .astype(str)
        )
        | (
            {"PEN=X"}
            if requeridos[
                "factor"
            ]
            .astype(str)
            .str.startswith(
                "ret_PEN_"
            )
            .any()
            else set()
        )
    )

    descargas: dict[str, pd.Series] = {}
    auditoria = []

    for numero, ticker in enumerate(
        tickers,
        start=1,
    ):
        print(
            f"[{numero:02d}/{len(tickers):02d}] "
            f"Actualizando {ticker}"
        )

        serie, intervalo, periodo = (
            descargar_serie(
                ticker
            )
        )

        descargas[ticker] = serie

        auditoria.append(
            {
                "ticker": ticker,
                "intervalo": intervalo,
                "periodo": periodo,
                "n_puntos": int(
                    len(serie)
                ),
                "ultima_actualizacion": (
                    serie.index[-1]
                    if not serie.empty
                    else pd.NaT
                ),
                "estado": (
                    "CORRECTO"
                    if not serie.empty
                    else "SIN_DATOS"
                ),
            }
        )

    fx = descargas.get(
        "PEN=X",
        pd.Series(dtype=float),
    )

    series_factor: dict[
        str,
        pd.Series,
    ] = {}

    filas = []

    for _, fila in requeridos.iterrows():
        factor = str(
            fila["factor"]
        )

        ticker = str(
            fila["ticker"]
        )

        serie_original = descargas.get(
            ticker,
            pd.Series(dtype=float),
        )

        transformacion = (
            clasificar_transformacion(
                factor
            )
        )

        if (
            transformacion
            == "CONVERTIR_A_PEN"
        ):
            serie_modelo = alinear_fx(
                serie_original,
                fx,
            )
        else:
            serie_modelo = (
                serie_original.copy()
            )

        series_factor[factor] = (
            serie_variacion_pct(
                serie_modelo
            )
        )

        (
            precio_actual,
            precio_base,
            retorno_actual,
            timestamp,
        ) = retorno_desde_cierre_previo(
            serie_modelo
        )

        p = parametros[
            parametros["afp"]
            .astype(str)
            .eq(str(fila["afp"]))
            & parametros[
                "factor"
            ]
            .astype(str)
            .eq(factor)
            & pd.to_numeric(
                parametros["lag"],
                errors="coerce",
            )
            .fillna(-999)
            .astype(int)
            .eq(
                int(fila["lag"])
            )
        ]

        media = np.nan
        desviacion = np.nan
        beta = np.nan
        contribucion = np.nan
        intercepto = np.nan

        if not p.empty:
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

            intercepto = float(
                p[
                    "intercepto_estandarizado"
                ].iloc[0]
            )

            if (
                pd.notna(
                    retorno_actual
                )
                and desviacion != 0
            ):
                z = (
                    retorno_actual
                    - media
                ) / desviacion

                contribucion = (
                    beta * z
                )
            else:
                z = np.nan
        else:
            z = np.nan

        filas.append(
            {
                "afp": fila["afp"],
                "orden": int(
                    fila["orden"]
                ),
                "factor": factor,
                "ticker": ticker,
                "nombre": fila["nombre"],
                "lag": int(
                    fila["lag"]
                ),
                "transformacion": (
                    transformacion
                ),
                "precio_actual": (
                    precio_actual
                ),
                "precio_cierre_previo": (
                    precio_base
                ),
                "variacion_actual_pct": (
                    retorno_actual
                    * 100.0
                    if pd.notna(
                        retorno_actual
                    )
                    else np.nan
                ),
                "ultima_actualizacion": (
                    timestamp
                ),
                "media_modelo": media,
                "desviacion_modelo": (
                    desviacion
                ),
                "coeficiente_modelo": beta,
                "z_intradia": z,
                "contribucion_parcial_pct": (
                    contribucion
                    * 100.0
                    if pd.notna(
                        contribucion
                    )
                    else np.nan
                ),
                "intercepto_modelo": (
                    intercepto
                ),
                "estado_dato": (
                    "DISPONIBLE"
                    if not serie_modelo.empty
                    else "SIN DATOS"
                ),
            }
        )

    panel = pd.DataFrame(
        filas
    )

    auditoria_df = pd.DataFrame(
        auditoria
    )

    return (
        panel,
        series_factor,
        auditoria_df,
    )


def resumen_afp(
    panel: pd.DataFrame,
) -> pd.DataFrame:
    filas = []

    for afp in AFPS:
        x = panel[
            panel["afp"]
            .astype(str)
            .eq(afp)
        ].copy()

        if x.empty:
            continue

        disponibles = x[
            "variacion_actual_pct"
        ].notna()

        cobertura = (
            disponibles.mean()
            * 100.0
        )

        contribuciones = pd.to_numeric(
            x[
                "contribucion_parcial_pct"
            ],
            errors="coerce",
        )

        p_intercepto = pd.to_numeric(
            x[
                "intercepto_modelo"
            ],
            errors="coerce",
        ).dropna()

        intercepto_pct = (
            float(
                p_intercepto.iloc[0]
            )
            * 100.0
            if not p_intercepto.empty
            else np.nan
        )

        señal = (
            contribuciones.sum(
                min_count=1
            )
            + intercepto_pct
            if pd.notna(
                intercepto_pct
            )
            else contribuciones.sum(
                min_count=1
            )
        )

        filas.append(
            {
                "afp": afp,
                "n_indicadores": int(
                    len(x)
                ),
                "n_disponibles": int(
                    disponibles.sum()
                ),
                "cobertura_pct": float(
                    cobertura
                ),
                "senal_parcial_intradia_pct": (
                    float(señal)
                    if pd.notna(señal)
                    else np.nan
                ),
                "lectura": (
                    "SUBE"
                    if pd.notna(señal)
                    and señal > 0
                    else (
                        "BAJA"
                        if pd.notna(señal)
                        and señal < 0
                        else "SIN SEÑAL"
                    )
                ),
            }
        )

    return pd.DataFrame(
        filas
    )


def formato_numero(
    valor: Any,
    decimales: int = 3,
) -> str:
    if pd.isna(valor):
        return "—"

    return f"{float(valor):.{decimales}f}"


def grafico_afp_html(
    afp: str,
    panel: pd.DataFrame,
    series_factor: dict[
        str,
        pd.Series,
    ],
) -> str:
    import plotly.graph_objects as go
    import plotly.io as pio

    x = panel[
        panel["afp"]
        .astype(str)
        .eq(afp)
    ].sort_values("orden")

    fig = go.Figure()

    for _, fila in x.iterrows():
        factor = str(
            fila["factor"]
        )

        serie = series_factor.get(
            factor,
            pd.Series(dtype=float),
        )

        if serie.empty:
            continue

        etiqueta = (
            f"{fila['ticker']} — "
            f"{fila['nombre']}"
        )

        fig.add_trace(
            go.Scatter(
                x=serie.index,
                y=serie.values,
                mode="lines",
                name=etiqueta,
                hovertemplate=(
                    f"<b>{html.escape(str(fila['ticker']))}</b><br>"
                    "Hora: %{x|%d/%m %H:%M}<br>"
                    "Variación: %{y:+.3f}%"
                    "<extra></extra>"
                ),
            )
        )

    fig.add_hline(
        y=0,
        line_dash="dot",
        opacity=0.5,
    )

    fig.update_layout(
        title=dict(
            text=(
                f"{afp}: variación de los "
                "indicadores desde el cierre previo"
            ),
            x=0.02,
        ),
        height=520,
        margin=dict(
            l=55,
            r=25,
            t=70,
            b=55,
        ),
        hovermode="x unified",
        legend=dict(
            orientation="h",
            yanchor="top",
            y=-0.25,
            xanchor="left",
            x=0,
        ),
        paper_bgcolor="white",
        plot_bgcolor="white",
        xaxis=dict(
            title="Hora de mercado",
            showgrid=True,
            gridcolor="#e6ecf3",
            rangeslider=dict(
                visible=True,
                thickness=0.09,
            ),
            rangeselector=dict(
                buttons=[
                    dict(
                        count=1,
                        label="Hoy",
                        step="day",
                        stepmode="backward",
                    ),
                    dict(
                        count=2,
                        label="2 días",
                        step="day",
                        stepmode="backward",
                    ),
                    dict(
                        count=5,
                        label="5 días",
                        step="day",
                        stepmode="backward",
                    ),
                    dict(
                        step="all",
                        label="Todo",
                    ),
                ],
            ),
        ),
        yaxis=dict(
            title="Variación desde cierre previo (%)",
            autorange=True,
            fixedrange=False,
            showgrid=True,
            gridcolor="#e6ecf3",
            zeroline=True,
        ),
    )

    config = {
        "responsive": True,
        "scrollZoom": True,
        "displaylogo": False,
        "toImageButtonOptions": {
            "format": "png",
            "filename": (
                f"indicadores_{afp.lower()}"
            ),
            "scale": 2,
        },
    }

    return pio.to_html(
        fig,
        full_html=False,
        include_plotlyjs=False,
        config=config,
    )


def tarjetas_resumen_html(
    resumen: pd.DataFrame,
) -> str:
    tarjetas = []

    for _, fila in resumen.iterrows():
        lectura = str(
            fila["lectura"]
        )

        clase = (
            "sube"
            if lectura == "SUBE"
            else (
                "baja"
                if lectura == "BAJA"
                else "neutral"
            )
        )

        tarjetas.append(
            f"""
            <article class="resumen-card">
              <h3>{html.escape(str(fila['afp']))}</h3>
              <div class="senal {clase}">
                {html.escape(lectura)}
                · {formato_numero(
                    fila['senal_parcial_intradia_pct'],
                    3
                )}%
              </div>
              <p>
                Indicadores disponibles:
                <strong>
                  {int(fila['n_disponibles'])}/
                  {int(fila['n_indicadores'])}
                </strong>
              </p>
              <p>
                Cobertura:
                <strong>
                  {fila['cobertura_pct']:.0f}%
                </strong>
              </p>
              <small>
                Señal parcial; cambia mientras los mercados
                siguen abiertos.
              </small>
            </article>
            """
        )

    return "".join(
        tarjetas
    )


def tabla_afp_html(
    afp: str,
    panel: pd.DataFrame,
) -> str:
    x = panel[
        panel["afp"]
        .astype(str)
        .eq(afp)
    ].copy()

    if x.empty:
        return (
            "<p>No existen indicadores.</p>"
        )

    tabla = x[
        [
            "ticker",
            "nombre",
            "lag",
            "precio_actual",
            "variacion_actual_pct",
            "contribucion_parcial_pct",
            "ultima_actualizacion",
            "estado_dato",
        ]
    ].rename(
        columns={
            "ticker": "Ticker",
            "nombre": "Indicador",
            "lag": "Rezago",
            "precio_actual": "Último precio",
            "variacion_actual_pct": "Variación actual (%)",
            "contribucion_parcial_pct": "Aporte parcial AFP (%)",
            "ultima_actualizacion": "Último dato",
            "estado_dato": "Estado",
        }
    )

    tabla[
        "Último dato"
    ] = pd.to_datetime(
        tabla[
            "Último dato"
        ],
        errors="coerce",
    ).dt.strftime(
        "%d/%m/%Y %H:%M"
    )

    return tabla.to_html(
        index=False,
        border=0,
        classes="tabla",
        float_format=lambda z: f"{z:.4f}",
    )


def crear_html(
    processed: Path,
    panel: pd.DataFrame,
    series_factor: dict[
        str,
        pd.Series,
    ],
    resumen: pd.DataFrame,
) -> Path:
    secciones = []

    for afp in AFPS:
        grafico = grafico_afp_html(
            afp,
            panel,
            series_factor,
        )

        tabla = tabla_afp_html(
            afp,
            panel,
        )

        secciones.append(
            f"""
            <section class="seccion" id="{afp.lower()}">
              <h2>{html.escape(afp)}</h2>
              <p class="ayuda">
                El gráfico compara todos los indicadores de
                {html.escape(afp)} en una misma escala porcentual.
                Coloca el cursor para ver el valor exacto,
                arrastra para ampliar y usa la rueda para zoom.
              </p>
              <div class="grafico">
                {grafico}
              </div>
              <details>
                <summary>
                  Ver detalle numérico de los indicadores
                </summary>
                <div class="tabla-wrap">
                  {tabla}
                </div>
              </details>
            </section>
            """
        )

    ruta = (
        processed
        / "ca0001_modelo86_indicadores_intradia.html"
    )

    documento = f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport"
      content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="300">
<title>Indicadores AFP Fondo 3</title>
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
  width:min(1550px, 96%);
  margin:auto;
  padding:22px 0 55px;
}}
header {{
  color:white;
  background:linear-gradient(135deg,var(--azul),var(--azul2));
  border-radius:16px;
  padding:24px 28px;
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
.alerta {{
  background:#fff7d6;
  border-left:6px solid #d7a400;
  padding:13px 16px;
  margin:15px 0;
  border-radius:9px;
  line-height:1.5;
}}
.resumen-grid {{
  display:grid;
  grid-template-columns:repeat(4,minmax(230px,1fr));
  gap:14px;
  margin:17px 0;
}}
.resumen-card {{
  background:white;
  border:1px solid var(--borde);
  border-radius:14px;
  padding:17px;
}}
.resumen-card h3 {{
  color:var(--azul);
  margin:0 0 12px;
}}
.senal {{
  display:inline-block;
  padding:7px 11px;
  border-radius:20px;
  font-weight:bold;
}}
.sube {{
  background:#e7f7ec;
  color:#176437;
}}
.baja {{
  background:#fdeaea;
  color:#a12626;
}}
.neutral {{
  background:#eef1f5;
  color:#556170;
}}
.resumen-card p {{
  margin:10px 0;
}}
.resumen-card small {{
  color:var(--suave);
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
.ayuda {{
  color:var(--suave);
  line-height:1.5;
}}
.grafico {{
  width:100%;
  overflow:hidden;
}}
details summary {{
  color:var(--azul);
  font-weight:bold;
  cursor:pointer;
  padding:10px 0;
}}
.tabla-wrap {{
  overflow-x:auto;
}}
.tabla {{
  border-collapse:collapse;
  width:100%;
  min-width:920px;
}}
.tabla th {{
  background:#eaf1fa;
  color:var(--azul);
}}
.tabla th,.tabla td {{
  padding:9px 10px;
  border-bottom:1px solid var(--borde);
  text-align:right;
  white-space:nowrap;
}}
.tabla th:nth-child(1),
.tabla td:nth-child(1),
.tabla th:nth-child(2),
.tabla td:nth-child(2) {{
  text-align:left;
}}
@media(max-width:1000px) {{
  .resumen-grid {{
    grid-template-columns:repeat(2,1fr);
  }}
}}
@media(max-width:650px) {{
  .resumen-grid {{
    grid-template-columns:1fr;
  }}
}}
</style>
</head>
<body>
<main>
<header>
  <h1>Indicadores intradía por AFP</h1>
  <p>
    Última actualización local:
    <strong>
      {datetime.now().strftime("%d/%m/%Y %H:%M:%S")}
    </strong>
  </p>

  <a class="boton"
     href="ca0001_modelo80_dashboard.html">
    Volver al monitor de cuotas
  </a>

  <button class="boton"
          onclick="location.reload()">
    Recargar página
  </button>
</header>

<div class="alerta">
  Esta página muestra datos gratuitos de mercado y una
  <strong>señal parcial intradía</strong>.
  No es todavía el pronóstico diario definitivo:
  los mercados operan en horarios diferentes y algunos datos
  pueden llegar con retraso. El pronóstico formal se congela
  cuando están disponibles los cierres utilizados por el modelo.
</div>

<div class="resumen-grid">
  {tarjetas_resumen_html(resumen)}
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


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Actualiza los indicadores intradía de las canastas AFP."
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

    canasta = leer_csv(
        processed
        / "ca0001_modelo78_canasta_final_podada.csv"
    )

    parametros = leer_csv(
        processed
        / "ca0001_modelo79c_parametros_ecuaciones.csv"
    )

    for columna in [
        "lag",
        "orden",
    ]:
        canasta[columna] = pd.to_numeric(
            canasta[columna],
            errors="coerce",
        ).fillna(0).astype(int)

    parametros["lag"] = pd.to_numeric(
        parametros["lag"],
        errors="coerce",
    ).fillna(0).astype(int)

    (
        panel,
        series_factor,
        auditoria,
    ) = construir_panel(
        canasta,
        parametros,
    )

    resumen = resumen_afp(
        panel
    )

    panel.to_csv(
        processed
        / "ca0001_modelo86_indicadores_intradia.csv",
        index=False,
        encoding="utf-8-sig",
    )

    auditoria.to_csv(
        processed
        / "ca0001_modelo86_auditoria_descargas.csv",
        index=False,
        encoding="utf-8-sig",
    )

    resumen.to_csv(
        processed
        / "ca0001_modelo86_resumen_intradia.csv",
        index=False,
        encoding="utf-8-sig",
    )

    pagina = crear_html(
        processed,
        panel,
        series_factor,
        resumen,
    )

    print("\nPANEL DE INDICADORES ACTUALIZADO")
    print("=" * 100)
    print(resumen.to_string(index=False))
    print(f"\nPágina: {pagina.resolve()}")

    if args.abrir:
        webbrowser.open(
            pagina.resolve().as_uri()
        )


if __name__ == "__main__":
    main()
