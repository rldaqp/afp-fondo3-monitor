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
) -> pd.DataFrame:
    if not ruta.exists():
        raise FileNotFoundError(f"Falta el archivo: {ruta}")

    ultimo_error: Exception | None = None

    for encoding in ["utf-8-sig", "latin-1", "utf-8"]:
        try:
            return pd.read_csv(ruta, encoding=encoding)
        except Exception as exc:
            ultimo_error = exc

    raise RuntimeError(f"No se pudo leer {ruta}: {ultimo_error}")


def extraer_bloque_ticker(
    descarga: pd.DataFrame,
    ticker: str,
) -> pd.DataFrame:
    if descarga.empty:
        return pd.DataFrame()

    if isinstance(descarga.columns, pd.MultiIndex):
        if ticker in descarga.columns.get_level_values(-1):
            bloque = descarga.xs(
                ticker,
                axis=1,
                level=-1,
                drop_level=True,
            )
        elif ticker in descarga.columns.get_level_values(0):
            bloque = descarga[ticker]
        else:
            bloque = descarga.copy()
    else:
        bloque = descarga.copy()

    requeridas = [
        "Open",
        "High",
        "Low",
        "Close",
    ]

    faltantes = [
        c
        for c in requeridas
        if c not in bloque.columns
    ]

    if faltantes:
        return pd.DataFrame()

    salida = bloque[
        requeridas
    ].copy()

    for columna in requeridas:
        salida[columna] = pd.to_numeric(
            salida[columna],
            errors="coerce",
        )

    salida = salida.dropna(
        how="all"
    )

    indice = pd.DatetimeIndex(
        pd.to_datetime(
            salida.index,
            errors="coerce",
        )
    )

    salida.index = indice
    salida = salida[
        ~salida.index.isna()
    ]

    try:
        if salida.index.tz is not None:
            salida.index = (
                salida.index
                .tz_convert("America/Lima")
                .tz_localize(None)
            )
    except Exception:
        pass

    return (
        salida[
            ~salida.index.duplicated(
                keep="last"
            )
        ]
        .sort_index()
    )


def descargar_ohlc(
    ticker: str,
) -> tuple[
    pd.DataFrame,
    str,
]:
    import yfinance as yf

    intentos = [
        ("5m", "5d"),
        ("15m", "5d"),
        ("30m", "5d"),
        ("60m", "1mo"),
        ("1d", "3mo"),
    ]

    ultimo_error = ""

    for intervalo, periodo in intentos:
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

            bloque = extraer_bloque_ticker(
                datos,
                ticker,
            )

            if len(bloque) >= 2:
                return bloque, intervalo

            ultimo_error = (
                f"sin suficientes datos en {intervalo}"
            )

        except Exception as exc:
            ultimo_error = str(exc)

    return pd.DataFrame(), ultimo_error


def retorno_actual(
    ohlc: pd.DataFrame,
) -> tuple[
    float,
    float,
    pd.Timestamp | None,
]:
    if ohlc.empty:
        return np.nan, np.nan, None

    cierre = ohlc["Close"].dropna()

    if cierre.empty:
        return np.nan, np.nan, None

    fechas = pd.Series(
        cierre.index.date,
        index=cierre.index,
    )

    dias = list(
        pd.unique(fechas)
    )

    ultimo = float(
        cierre.iloc[-1]
    )

    if len(dias) >= 2:
        previo = cierre[
            fechas.eq(dias[-2])
        ]
        base = (
            float(previo.iloc[-1])
            if not previo.empty
            else float(cierre.iloc[0])
        )
    else:
        base = float(cierre.iloc[0])

    variacion = (
        ultimo / base - 1.0
        if base != 0
        else np.nan
    )

    return (
        ultimo,
        variacion,
        cierre.index[-1],
    )


def preparar_panel(
    canasta: pd.DataFrame,
    parametros: pd.DataFrame,
) -> tuple[
    pd.DataFrame,
    dict[str, pd.DataFrame],
]:
    requeridos = (
        canasta[
            [
                "afp",
                "orden",
                "factor",
                "ticker",
                "nombre",
                "lag",
            ]
        ]
        .sort_values(
            [
                "afp",
                "orden",
            ]
        )
        .copy()
    )

    tickers = sorted(
        requeridos[
            "ticker"
        ]
        .dropna()
        .astype(str)
        .unique()
    )

    datos_ticker: dict[
        str,
        pd.DataFrame,
    ] = {}

    intervalos = {}

    for numero, ticker in enumerate(
        tickers,
        start=1,
    ):
        print(
            f"[{numero:02d}/{len(tickers):02d}] "
            f"Actualizando {ticker}"
        )

        ohlc, intervalo = descargar_ohlc(
            ticker
        )

        datos_ticker[ticker] = ohlc
        intervalos[ticker] = intervalo

    filas = []

    for _, fila in requeridos.iterrows():
        afp = str(fila["afp"])
        factor = str(fila["factor"])
        ticker = str(fila["ticker"])
        lag = int(fila["lag"])

        ohlc = datos_ticker.get(
            ticker,
            pd.DataFrame(),
        )

        precio, variacion, timestamp = (
            retorno_actual(
                ohlc
            )
        )

        p = parametros[
            parametros["afp"]
            .astype(str)
            .eq(afp)
            & parametros["factor"]
            .astype(str)
            .eq(factor)
            & pd.to_numeric(
                parametros["lag"],
                errors="coerce",
            )
            .fillna(-999)
            .astype(int)
            .eq(lag)
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

            if (
                "intercepto_estandarizado"
                in p.columns
            ):
                intercepto = float(
                    p[
                        "intercepto_estandarizado"
                    ].iloc[0]
                )

            if (
                pd.notna(variacion)
                and desviacion != 0
            ):
                z = (
                    variacion - media
                ) / desviacion

                contribucion = (
                    beta * z
                ) * 100.0

        filas.append(
            {
                "afp": afp,
                "orden": int(
                    fila["orden"]
                ),
                "factor": factor,
                "ticker": ticker,
                "nombre": fila["nombre"],
                "lag": lag,
                "ultimo_precio": precio,
                "variacion_actual_pct": (
                    variacion * 100.0
                    if pd.notna(variacion)
                    else np.nan
                ),
                "aporte_parcial_pct": contribucion,
                "intercepto_pct": (
                    intercepto * 100.0
                    if pd.notna(intercepto)
                    else np.nan
                ),
                "ultimo_dato": timestamp,
                "intervalo": intervalos.get(
                    ticker,
                    "SIN DATOS",
                ),
                "estado": (
                    "DISPONIBLE"
                    if not ohlc.empty
                    else "SIN DATOS"
                ),
            }
        )

    return (
        pd.DataFrame(filas),
        datos_ticker,
    )


def grafico_aportes_html(
    afp: str,
    panel: pd.DataFrame,
) -> str:
    import plotly.graph_objects as go
    import plotly.io as pio
    from plotly.subplots import make_subplots

    x = (
        panel[
            panel["afp"]
            .astype(str)
            .eq(afp)
        ]
        .copy()
    )

    x[
        "aporte_parcial_pct"
    ] = pd.to_numeric(
        x[
            "aporte_parcial_pct"
        ],
        errors="coerce",
    ).fillna(0.0)

    x["etiqueta"] = [
        f"{ticker} — {nombre}"
        for ticker, nombre in zip(
            x["ticker"],
            x["nombre"],
        )
    ]

    suma_absoluta = float(
        x[
            "aporte_parcial_pct"
        ].abs().sum()
    )

    if suma_absoluta > 0:
        x[
            "participacion_senal_pct"
        ] = (
            x[
                "aporte_parcial_pct"
            ].abs()
            / suma_absoluta
            * 100.0
        )
    else:
        x[
            "participacion_senal_pct"
        ] = 0.0

    x["direccion_aporte"] = np.where(
        x[
            "aporte_parcial_pct"
        ].gt(0),
        "EMPUJA ARRIBA",
        np.where(
            x[
                "aporte_parcial_pct"
            ].lt(0),
            "EMPUJA ABAJO",
            "NEUTRO",
        ),
    )

    x_aporte = x.sort_values(
        "aporte_parcial_pct"
    )

    x_relativo = x.sort_values(
        "participacion_senal_pct"
    )

    suma_neta = float(
        x[
            "aporte_parcial_pct"
        ].sum()
    )

    if (
        "intercepto_pct"
        in x.columns
    ):
        interceptos = pd.to_numeric(
            x[
                "intercepto_pct"
            ],
            errors="coerce",
        ).dropna()
    else:
        interceptos = pd.Series(
            dtype=float
        )

    intercepto = (
        float(
            interceptos.iloc[0]
        )
        if not interceptos.empty
        else 0.0
    )

    retorno_total = (
        suma_neta
        + intercepto
    )

    fig = make_subplots(
        rows=2,
        cols=1,
        vertical_spacing=0.24,
        subplot_titles=[
            (
                "Aporte al retorno estimado "
                "(puntos porcentuales)"
            ),
            (
                "Participación relativa en la señal "
                "(suma 100%)"
            ),
        ],
    )

    fig.add_trace(
        go.Bar(
            x=x_aporte[
                "aporte_parcial_pct"
            ],
            y=x_aporte[
                "etiqueta"
            ],
            orientation="h",
            customdata=np.column_stack(
                [
                    x_aporte[
                        "variacion_actual_pct"
                    ].fillna(np.nan),
                    x_aporte["lag"],
                    x_aporte[
                        "direccion_aporte"
                    ],
                ]
            ),
            hovertemplate=(
                "<b>%{y}</b><br>"
                "Aporte: %{x:+.4f} puntos porcentuales<br>"
                "Variación del indicador: "
                "%{customdata[0]:+.3f}%<br>"
                "Rezago: %{customdata[1]:.0f}<br>"
                "%{customdata[2]}"
                "<extra></extra>"
            ),
        ),
        row=1,
        col=1,
    )

    fig.add_vline(
        x=0,
        line_dash="dot",
        row=1,
        col=1,
    )

    fig.add_trace(
        go.Bar(
            x=x_relativo[
                "participacion_senal_pct"
            ],
            y=x_relativo[
                "etiqueta"
            ],
            orientation="h",
            customdata=np.column_stack(
                [
                    x_relativo[
                        "aporte_parcial_pct"
                    ],
                    x_relativo[
                        "direccion_aporte"
                    ],
                ]
            ),
            hovertemplate=(
                "<b>%{y}</b><br>"
                "Participación relativa: %{x:.2f}%<br>"
                "Aporte original: "
                "%{customdata[0]:+.4f} puntos porcentuales<br>"
                "%{customdata[1]}"
                "<extra></extra>"
            ),
        ),
        row=2,
        col=1,
    )

    fig.update_layout(
        title=dict(
            text=(
                f"{afp}: contribución al retorno "
                "y fuerza relativa de la señal"
            ),
            x=0.02,
        ),
        height=max(
            660,
            220 + len(x) * 82,
        ),
        margin=dict(
            l=220,
            r=35,
            t=95,
            b=95,
        ),
        paper_bgcolor="white",
        plot_bgcolor="white",
        showlegend=False,
    )

    fig.add_annotation(
        text=(
            f"Suma neta de indicadores: "
            f"{suma_neta:+.4f}% · "
            f"Componente base: "
            f"{intercepto:+.4f}% · "
            f"Retorno total estimado: "
            f"{retorno_total:+.4f}%"
        ),
        x=0,
        xref="paper",
        y=-0.14,
        yref="paper",
        showarrow=False,
        align="left",
        font=dict(
            size=13,
        ),
    )

    fig.update_xaxes(
        title=(
            "Puntos porcentuales del retorno estimado"
        ),
        showgrid=True,
        gridcolor="#e7edf4",
        zeroline=True,
        row=1,
        col=1,
    )

    fig.update_xaxes(
        title=(
            "Participación relativa de la señal (%)"
        ),
        range=[
            0,
            100,
        ],
        showgrid=True,
        gridcolor="#e7edf4",
        row=2,
        col=1,
    )

    fig.update_yaxes(
        title="",
        row=1,
        col=1,
    )

    fig.update_yaxes(
        title="",
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
        },
    )

def grafico_velas_html(
    ticker: str,
    nombre: str,
    ohlc: pd.DataFrame,
) -> str:
    import plotly.graph_objects as go
    import plotly.io as pio

    if ohlc.empty:
        return (
            "<p class='sin-datos'>"
            "No existen datos suficientes para este indicador."
            "</p>"
        )

    fig = go.Figure(
        data=[
            go.Candlestick(
                x=ohlc.index,
                open=ohlc["Open"],
                high=ohlc["High"],
                low=ohlc["Low"],
                close=ohlc["Close"],
                increasing_line_color="#1f9d55",
                decreasing_line_color="#d14343",
                name=ticker,
                hovertext=nombre,
            )
        ]
    )

    fig.update_layout(
        title=dict(
            text=f"{ticker} — {nombre}",
            x=0.02,
        ),
        height=360,
        margin=dict(
            l=55,
            r=25,
            t=58,
            b=50,
        ),
        paper_bgcolor="white",
        plot_bgcolor="white",
        xaxis=dict(
            title="Fecha y hora",
            rangeslider=dict(
                visible=False
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
            showgrid=True,
            gridcolor="#e7edf4",
        ),
        yaxis=dict(
            title="Precio del indicador",
            autorange=True,
            fixedrange=False,
            showgrid=True,
            gridcolor="#e7edf4",
        ),
    )

    return pio.to_html(
        fig,
        full_html=False,
        include_plotlyjs=False,
        config={
            "responsive": True,
            "displaylogo": False,
            "scrollZoom": True,
        },
    )


def tarjeta_indicador_html(
    fila: pd.Series,
    ohlc: pd.DataFrame,
) -> str:
    variacion = fila[
        "variacion_actual_pct"
    ]

    aporte = fila[
        "aporte_parcial_pct"
    ]

    if pd.isna(variacion):
        lectura = "SIN DATOS"
        clase = "neutral"
    elif variacion > 0:
        lectura = "SUBE"
        clase = "sube"
    elif variacion < 0:
        lectura = "BAJA"
        clase = "baja"
    else:
        lectura = "SIN CAMBIO"
        clase = "neutral"

    if pd.isna(aporte):
        aporte_texto = "—"
    else:
        aporte_texto = (
            f"{float(aporte):+.4f}%"
        )

    fecha = (
        pd.Timestamp(
            fila["ultimo_dato"]
        ).strftime(
            "%d/%m/%Y %H:%M"
        )
        if pd.notna(
            fila["ultimo_dato"]
        )
        else "—"
    )

    return f"""
    <article class="indicador-card">
      <div class="indicador-cabecera">
        <div>
          <h4>{html.escape(str(fila['ticker']))}</h4>
          <p>{html.escape(str(fila['nombre']))}</p>
        </div>
        <span class="estado {clase}">
          {html.escape(lectura)}
        </span>
      </div>

      <div class="indicador-datos">
        <div>
          <span>Variación actual</span>
          <strong>
            {
                "—"
                if pd.isna(variacion)
                else f"{float(variacion):+.3f}%"
            }
          </strong>
        </div>
        <div>
          <span>Aporte al modelo</span>
          <strong>{aporte_texto}</strong>
        </div>
        <div>
          <span>Rezago</span>
          <strong>{int(fila['lag'])}</strong>
        </div>
        <div>
          <span>Último dato</span>
          <strong>{fecha}</strong>
        </div>
      </div>

      <details>
        <summary>
          Ver gráfico de velas del indicador real
        </summary>
        <p class="nota-vela">
          Estas velas corresponden al activo o índice real,
          no al valor cuota estimado.
        </p>
        {grafico_velas_html(
            str(fila['ticker']),
            str(fila['nombre']),
            ohlc,
        )}
      </details>
    </article>
    """


def seccion_afp_html(
    afp: str,
    panel: pd.DataFrame,
    datos_ticker: dict[
        str,
        pd.DataFrame,
    ],
) -> str:
    x = (
        panel[
            panel["afp"]
            .astype(str)
            .eq(afp)
        ]
        .sort_values("orden")
    )

    tarjetas = "".join(
        tarjeta_indicador_html(
            fila,
            datos_ticker.get(
                str(fila["ticker"]),
                pd.DataFrame(),
            ),
        )
        for _, fila in x.iterrows()
    )

    return f"""
    <section class="seccion" id="{afp.lower()}">
      <h2>{html.escape(afp)}</h2>

      <p class="explicacion">
        El primer gráfico expresa cuánto aporta cada indicador
        al movimiento estimado, en puntos porcentuales; por eso
        no suma 100%. El segundo normaliza la fuerza absoluta
        de los indicadores y sí suma 100%, pero no representa
        la composición real de la cartera de la AFP.
        Después puedes abrir la vela de cada indicador real.
      </p>

      <div class="grafico-aportes">
        {grafico_aportes_html(
            afp,
            panel,
        )}
      </div>

      <div class="indicadores-grid">
        {tarjetas}
      </div>
    </section>
    """


def crear_html(
    processed: Path,
    panel: pd.DataFrame,
    datos_ticker: dict[
        str,
        pd.DataFrame,
    ],
) -> Path:
    secciones = "".join(
        seccion_afp_html(
            afp,
            panel,
            datos_ticker,
        )
        for afp in AFPS
    )

    ruta = (
        processed
        / "ca0001_modelo92_indicadores_didacticos.html"
    )

    documento = f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport"
      content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="300">
<title>Indicadores del modelo AFP</title>
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
  width:min(1550px,96%);
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
  border:0;
  background:white;
  color:var(--azul);
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
.explicacion {{
  color:var(--suave);
  line-height:1.55;
}}
.grafico-aportes {{
  border:1px solid var(--borde);
  border-radius:12px;
  margin:14px 0 18px;
  padding:6px;
}}
.indicadores-grid {{
  display:grid;
  grid-template-columns:repeat(2,minmax(390px,1fr));
  gap:16px;
}}
.indicador-card {{
  border:1px solid var(--borde);
  border-radius:13px;
  padding:15px;
  background:#fbfdff;
}}
.indicador-cabecera {{
  display:flex;
  justify-content:space-between;
  gap:12px;
  align-items:flex-start;
}}
.indicador-cabecera h4 {{
  color:var(--azul);
  font-size:18px;
  margin:0 0 4px;
}}
.indicador-cabecera p {{
  color:var(--suave);
  margin:0;
}}
.estado {{
  padding:7px 11px;
  border-radius:20px;
  font-weight:bold;
  font-size:12px;
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
.indicador-datos {{
  display:grid;
  grid-template-columns:repeat(2,1fr);
  gap:10px;
  margin:14px 0;
}}
.indicador-datos div {{
  background:white;
  border:1px solid var(--borde);
  border-radius:9px;
  padding:10px;
}}
.indicador-datos span {{
  display:block;
  color:var(--suave);
  font-size:12px;
  margin-bottom:4px;
}}
.indicador-datos strong {{
  display:block;
}}
details summary {{
  color:var(--azul);
  font-weight:bold;
  cursor:pointer;
  padding:8px 0;
}}
.nota-vela {{
  color:var(--suave);
  font-size:13px;
}}
.sin-datos {{
  color:var(--suave);
}}
@media(max-width:900px) {{
  .indicadores-grid {{
    grid-template-columns:1fr;
  }}
}}
</style>
</head>
<body>
<main>
<header>
  <h1>Qué indicadores están moviendo cada AFP</h1>
  <p>
    Última actualización:
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
  <a class="boton" href="ca0001_modelo111_vela_pronostico_historico.html">Vela pronosticada</a>
</header>

<div class="aviso">
  <strong>Cómo leer esta página:</strong>
  el gráfico de barras muestra el aporte parcial de cada
  indicador a la señal del modelo.
  Las velas japonesas se usan únicamente para los índices,
  ETF o acciones reales, porque esos instrumentos sí tienen
  apertura, máximo, mínimo y cierre.
  No se construyen velas artificiales para el valor cuota.
</div>

{secciones}
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
            "Construye la página didáctica de indicadores del modelo."
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

    panel, datos_ticker = preparar_panel(
        canasta,
        parametros,
    )

    panel.to_csv(
        processed
        / "ca0001_modelo92_indicadores_didacticos.csv",
        index=False,
        encoding="utf-8-sig",
    )

    pagina = crear_html(
        processed,
        panel,
        datos_ticker,
    )

    print("\nPÁGINA DIDÁCTICA DE INDICADORES ACTUALIZADA")
    print("=" * 100)
    print(f"Página: {pagina.resolve()}")

    if args.abrir:
        webbrowser.open(
            pagina.resolve().as_uri()
        )


if __name__ == "__main__":
    main()
