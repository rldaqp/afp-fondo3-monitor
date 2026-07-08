from __future__ import annotations

import argparse
import html
import subprocess
import sys
import webbrowser
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd


AFPS = ["Habitat", "Integra", "Prima", "Profuturo"]
COBERTURA_MINIMA = 100.0


def asegurar_plotly() -> None:
    try:
        import plotly  # noqa: F401
        return
    except ImportError:
        print("Instalando Plotly para los gráficos interactivos...")
        proceso = subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "plotly",
            ],
            check=False,
        )
        if proceso.returncode != 0:
            raise RuntimeError(
                "No se pudo instalar Plotly automáticamente."
            )


def leer_csv(ruta: Path) -> pd.DataFrame:
    if not ruta.exists():
        return pd.DataFrame()

    ultimo_error: Exception | None = None

    for encoding in ["utf-8-sig", "latin-1", "utf-8"]:
        try:
            return pd.read_csv(ruta, encoding=encoding)
        except Exception as exc:
            ultimo_error = exc

    raise RuntimeError(f"No se pudo leer {ruta}: {ultimo_error}")


def ejecutar_modulo80(
    raiz: Path,
    pronosticar: bool,
) -> int:
    modulo80 = (
        raiz
        / "src"
        / "80_monitor_sbs_y_validar_pronosticos.py"
    )

    if not modulo80.exists():
        raise FileNotFoundError(
            f"No se encontró el módulo 80:\n{modulo80}"
        )

    comando = [
        sys.executable,
        str(modulo80),
    ]

    if pronosticar:
        comando.append("--pronosticar")

    resultado = subprocess.run(
        comando,
        cwd=str(raiz),
        check=False,
    )

    return int(resultado.returncode)


def preparar_datos(
    processed: Path,
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
]:
    base = leer_csv(
        processed
        / "ca0001_modelo56_base_alineada.csv"
    )

    pronosticos = leer_csv(
        processed
        / "ca0001_modelo79_primer_pronostico_congelado.csv"
    )

    metricas = leer_csv(
        processed
        / "ca0001_modelo80_metricas_prospectivas.csv"
    )

    if base.empty:
        raise RuntimeError(
            "No existe la base histórica del modelo."
        )

    base["fecha_cuota"] = pd.to_datetime(
        base["fecha_cuota"],
        errors="coerce",
    ).dt.normalize()

    base["cuota_sbs"] = pd.to_numeric(
        base["cuota_sbs"],
        errors="coerce",
    )

    base = (
        base.dropna(
            subset=[
                "afp",
                "fecha_cuota",
                "cuota_sbs",
            ]
        )
        .drop_duplicates(
            subset=[
                "afp",
                "fecha_cuota",
            ],
            keep="last",
        )
        .sort_values(
            [
                "afp",
                "fecha_cuota",
            ]
        )
        .reset_index(drop=True)
    )

    if not pronosticos.empty:
        for columna in [
            "fecha_objetivo",
            "fecha_ultima_cuota_oficial",
        ]:
            pronosticos[columna] = pd.to_datetime(
                pronosticos[columna],
                errors="coerce",
            ).dt.normalize()

        for columna in [
            "cuota_ultima_oficial",
            "cuota_estimada",
            "retorno_acumulado_estimado",
            "cobertura_factores_pct",
        ]:
            pronosticos[columna] = pd.to_numeric(
                pronosticos[columna],
                errors="coerce",
            )

        pronosticos = (
            pronosticos.dropna(
                subset=[
                    "afp",
                    "fecha_objetivo",
                    "cuota_estimada",
                ]
            )
            .sort_values(
                [
                    "afp",
                    "fecha_objetivo",
                    "run_id",
                ]
            )
            .drop_duplicates(
                subset=[
                    "afp",
                    "fecha_objetivo",
                ],
                keep="first",
            )
            .reset_index(drop=True)
        )

        pronosticos["variacion_estimada_pct"] = (
            pronosticos[
                "retorno_acumulado_estimado"
            ]
            * 100.0
        )

        pronosticos["pronostico_valido"] = (
            pronosticos[
                "cobertura_factores_pct"
            ]
            .fillna(0.0)
            .ge(COBERTURA_MINIMA)
        )

    return base, pronosticos, metricas


def combinar_pronosticos_reales(
    base: pd.DataFrame,
    pronosticos: pd.DataFrame,
) -> pd.DataFrame:
    if pronosticos.empty:
        return pronosticos.copy()

    reales = (
        base[
            [
                "afp",
                "fecha_cuota",
                "cuota_sbs",
            ]
        ]
        .rename(
            columns={
                "fecha_cuota": "fecha_objetivo",
                "cuota_sbs": "cuota_real_sbs",
            }
        )
    )

    combinado = pronosticos.merge(
        reales,
        on=[
            "afp",
            "fecha_objetivo",
        ],
        how="left",
    )

    combinado["desviacion_cuota"] = (
        combinado["cuota_estimada"]
        - combinado["cuota_real_sbs"]
    )

    combinado["error_pct"] = (
        combinado["cuota_estimada"]
        / combinado["cuota_real_sbs"]
        - 1.0
    ) * 100.0

    combinado["estado"] = np.where(
        combinado["pronostico_valido"].eq(False),
        "INCOMPLETO",
        np.where(
            combinado["cuota_real_sbs"].notna(),
            "EVALUADO",
            "ESPERANDO SBS",
        ),
    )

    return combinado


def formato_fecha(valor) -> str:
    if pd.isna(valor):
        return "—"

    return pd.Timestamp(valor).strftime("%d/%m/%Y")


def formato_numero(
    valor,
    decimales: int = 6,
) -> str:
    if pd.isna(valor):
        return "—"

    return f"{float(valor):.{decimales}f}"


def ultima_cuota(
    base: pd.DataFrame,
    afp: str,
) -> pd.Series | None:
    x = base[
        base["afp"].astype(str).eq(afp)
    ].sort_values("fecha_cuota")

    if x.empty:
        return None

    return x.iloc[-1]


def ultimo_pronostico_valido(
    combinado: pd.DataFrame,
    afp: str,
) -> pd.Series | None:
    x = combinado[
        combinado["afp"].astype(str).eq(afp)
        & combinado["pronostico_valido"].eq(True)
    ].sort_values("fecha_objetivo")

    if x.empty:
        return None

    return x.iloc[-1]


def tarjeta_afp(
    afp: str,
    base: pd.DataFrame,
    combinado: pd.DataFrame,
) -> str:
    real = ultima_cuota(
        base,
        afp,
    )

    pron = ultimo_pronostico_valido(
        combinado,
        afp,
    )

    if real is None:
        return ""

    cuota_real = float(real["cuota_sbs"])
    fecha_real = real["fecha_cuota"]

    if pron is None:
        return f"""
        <article class="afp-card">
          <h3>{html.escape(afp)}</h3>
          <div class="cuota-principal">
            {cuota_real:.6f}
          </div>
          <div class="fecha">{formato_fecha(fecha_real)}</div>
          <div class="estado neutral">SIN PRONÓSTICO VÁLIDO</div>
        </article>
        """

    cuota_estim = float(pron["cuota_estimada"])
    diferencia = cuota_estim - cuota_real
    variacion = float(pron["variacion_estimada_pct"])
    direccion = str(pron["direccion_estimada"])
    cobertura = float(pron["cobertura_factores_pct"])
    estado = str(pron["estado"])

    clase = (
        "sube"
        if direccion == "SUBE"
        else "baja"
    )

    if estado == "EVALUADO":
        estado_texto = (
            f"Cuota real publicada: "
            f"{float(pron['cuota_real_sbs']):.6f}"
        )
        detalle = (
            f"Error: {float(pron['error_pct']):+.3f}% · "
            f"Desviación: "
            f"{float(pron['desviacion_cuota']):+.6f}"
        )
    else:
        estado_texto = "Esperando publicación de la SBS"
        detalle = (
            f"Diferencia estimada frente al último oficial: "
            f"{diferencia:+.6f}"
        )

    return f"""
    <article class="afp-card">
      <h3>{html.escape(afp)}</h3>

      <div class="comparacion">
        <div>
          <span>Última cuota oficial</span>
          <strong>{cuota_real:.6f}</strong>
          <small>{formato_fecha(fecha_real)}</small>
        </div>
        <div class="flecha">→</div>
        <div>
          <span>Cuota estimada</span>
          <strong>{cuota_estim:.6f}</strong>
          <small>{formato_fecha(pron['fecha_objetivo'])}</small>
        </div>
      </div>

      <div class="estado {clase}">
        {html.escape(direccion)}
        · {variacion:+.3f}%
      </div>

      <p class="mensaje-estado">
        {html.escape(estado_texto)}
      </p>

      <p class="detalle">
        {html.escape(detalle)}
      </p>

      <div class="cobertura">
        Cobertura de datos: {cobertura:.0f}%
      </div>
    </article>
    """


def grafico_interactivo(
    afp: str,
    base: pd.DataFrame,
    combinado: pd.DataFrame,
) -> str:
    import plotly.graph_objects as go
    import plotly.io as pio

    real = (
        base[
            base["afp"].astype(str).eq(afp)
        ]
        .sort_values("fecha_cuota")
        .copy()
    )

    pred = (
        combinado[
            combinado["afp"].astype(str).eq(afp)
            & combinado["pronostico_valido"].eq(True)
        ]
        .sort_values("fecha_objetivo")
        .copy()
    )

    fig = go.Figure()

    fig.add_trace(
        go.Scatter(
            x=real["fecha_cuota"],
            y=real["cuota_sbs"],
            mode="lines",
            name="Cuota real SBS",
            line=dict(
                width=2.4,
            ),
            hovertemplate=(
                "<b>Cuota real SBS</b><br>"
                "Fecha: %{x|%d/%m/%Y}<br>"
                "Cuota: %{y:.6f}"
                "<extra></extra>"
            ),
        )
    )

    if not pred.empty:
        ancla_fecha = pred[
            "fecha_ultima_cuota_oficial"
        ].iloc[0]

        ancla_cuota = pred[
            "cuota_ultima_oficial"
        ].iloc[0]

        x_pred = [
            ancla_fecha,
            *pred["fecha_objetivo"].tolist(),
        ]

        y_pred = [
            ancla_cuota,
            *pred["cuota_estimada"].tolist(),
        ]

        fig.add_trace(
            go.Scatter(
                x=x_pred,
                y=y_pred,
                mode="lines+markers",
                name="Pronóstico congelado",
                line=dict(
                    width=3,
                    dash="dash",
                ),
                marker=dict(
                    size=9,
                ),
                hovertemplate=(
                    "<b>Pronóstico</b><br>"
                    "Fecha: %{x|%d/%m/%Y}<br>"
                    "Cuota estimada: %{y:.6f}"
                    "<extra></extra>"
                ),
            )
        )

        evaluados = pred[
            pred["cuota_real_sbs"].notna()
        ]

        if not evaluados.empty:
            fig.add_trace(
                go.Scatter(
                    x=evaluados["fecha_objetivo"],
                    y=evaluados["cuota_real_sbs"],
                    mode="markers",
                    name="Resultado SBS evaluado",
                    marker=dict(
                        size=11,
                        symbol="diamond",
                    ),
                    customdata=np.column_stack(
                        [
                            evaluados[
                                "cuota_estimada"
                            ],
                            evaluados[
                                "error_pct"
                            ],
                        ]
                    ),
                    hovertemplate=(
                        "<b>Resultado publicado</b><br>"
                        "Fecha: %{x|%d/%m/%Y}<br>"
                        "Cuota SBS: %{y:.6f}<br>"
                        "Estimación: %{customdata[0]:.6f}<br>"
                        "Error: %{customdata[1]:+.3f}%"
                        "<extra></extra>"
                    ),
                )
            )

    fecha_maxima = real["fecha_cuota"].max()

    if not pred.empty:
        fecha_maxima = max(
            fecha_maxima,
            pred["fecha_objetivo"].max(),
        )

    fecha_inicio = (
        fecha_maxima
        - pd.Timedelta(days=10)
    )

    fig.update_layout(
        title=dict(
            text=f"{afp}: cuota oficial y pronóstico",
            x=0.02,
        ),
        height=500,
        margin=dict(
            l=55,
            r=25,
            t=60,
            b=55,
        ),
        hovermode="x unified",
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="left",
            x=0,
        ),
        paper_bgcolor="white",
        plot_bgcolor="white",
        xaxis=dict(
            title="Fecha",
            range=[
                fecha_inicio,
                fecha_maxima
                + pd.Timedelta(days=2),
            ],
            rangeslider=dict(
                visible=True,
                thickness=0.10,
            ),
            rangeselector=dict(
                buttons=[
                    dict(
                        count=5,
                        label="5 días",
                        step="day",
                        stepmode="backward",
                    ),
                    dict(
                        count=10,
                        label="10 días",
                        step="day",
                        stepmode="backward",
                    ),
                    dict(
                        count=15,
                        label="15 días",
                        step="day",
                        stepmode="backward",
                    ),
                    dict(
                        count=20,
                        label="20 días",
                        step="day",
                        stepmode="backward",
                    ),
                    dict(
                        count=25,
                        label="25 días",
                        step="day",
                        stepmode="backward",
                    ),
                    dict(
                        count=30,
                        label="30 días",
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
            gridcolor="#e8edf4",
        ),
        yaxis=dict(
            title="Valor cuota",
            autorange=True,
            fixedrange=False,
            showgrid=True,
            gridcolor="#e8edf4",
        ),
    )

    config = {
        "responsive": True,
        "scrollZoom": True,
        "displaylogo": False,
        "modeBarButtonsToAdd": [
            "drawline",
            "eraseshape",
        ],
        "toImageButtonOptions": {
            "format": "png",
            "filename": f"monitor_{afp.lower()}",
            "scale": 2,
        },
    }

    return pio.to_html(
        fig,
        full_html=False,
        include_plotlyjs=False,
        config=config,
    )


def tabla_pendientes(
    combinado: pd.DataFrame,
) -> str:
    pendientes = combinado[
        combinado["pronostico_valido"].eq(True)
        & combinado["cuota_real_sbs"].isna()
    ].copy()

    if pendientes.empty:
        return (
            "<p class='vacio'>"
            "No existen pronósticos válidos pendientes."
            "</p>"
        )

    tabla = pendientes[
        [
            "afp",
            "fecha_objetivo",
            "cuota_ultima_oficial",
            "cuota_estimada",
            "variacion_estimada_pct",
            "direccion_estimada",
            "cobertura_factores_pct",
        ]
    ].rename(
        columns={
            "afp": "AFP",
            "fecha_objetivo": "Fecha pronosticada",
            "cuota_ultima_oficial": "Última cuota oficial",
            "cuota_estimada": "Cuota estimada",
            "variacion_estimada_pct": "Variación estimada (%)",
            "direccion_estimada": "Dirección",
            "cobertura_factores_pct": "Cobertura (%)",
        }
    )

    tabla[
        "Fecha pronosticada"
    ] = tabla[
        "Fecha pronosticada"
    ].map(formato_fecha)

    return tabla.to_html(
        index=False,
        border=0,
        classes="tabla",
        float_format=lambda x: f"{x:.6f}",
    )


def tabla_evaluados(
    combinado: pd.DataFrame,
) -> str:
    evaluados = combinado[
        combinado["pronostico_valido"].eq(True)
        & combinado["cuota_real_sbs"].notna()
    ].copy()

    if evaluados.empty:
        return (
            "<p class='vacio'>"
            "La SBS todavía no publicó ninguna de las fechas "
            "pronosticadas."
            "</p>"
        )

    tabla = evaluados[
        [
            "afp",
            "fecha_objetivo",
            "cuota_estimada",
            "cuota_real_sbs",
            "desviacion_cuota",
            "error_pct",
        ]
    ].rename(
        columns={
            "afp": "AFP",
            "fecha_objetivo": "Fecha",
            "cuota_estimada": "Cuota estimada",
            "cuota_real_sbs": "Cuota real SBS",
            "desviacion_cuota": "Desviación",
            "error_pct": "Error (%)",
        }
    )

    tabla["Fecha"] = tabla[
        "Fecha"
    ].map(formato_fecha)

    return tabla.to_html(
        index=False,
        border=0,
        classes="tabla",
        float_format=lambda x: f"{x:.6f}",
    )


def tabla_metricas(
    metricas: pd.DataFrame,
) -> str:
    if metricas.empty:
        return (
            "<p class='vacio'>"
            "Las métricas aparecerán después de comparar "
            "pronósticos con cuotas SBS reales."
            "</p>"
        )

    nombres = {
        "afp": "AFP",
        "n_pronosticos_evaluados": "Evaluados",
        "mape_prospectivo_pct": "Error medio (%)",
        "sesgo_pct": "Sesgo (%)",
        "p90_error_abs_pct": "P90 error (%)",
        "error_maximo_abs_pct": "Error máximo (%)",
        "acierto_direccion_pct": "Dirección acertada (%)",
        "pearson_retorno": "Correlación retorno",
    }

    tabla = metricas.rename(
        columns=nombres
    )

    return tabla.to_html(
        index=False,
        border=0,
        classes="tabla",
        float_format=lambda x: f"{x:.3f}",
    )


def crear_html(
    processed: Path,
    base: pd.DataFrame,
    combinado: pd.DataFrame,
    metricas: pd.DataFrame,
) -> Path:
    ultima_fecha = base[
        "fecha_cuota"
    ].max()

    tarjetas = "".join(
        tarjeta_afp(
            afp,
            base,
            combinado,
        )
        for afp in AFPS
    )

    graficos = "".join(
        f"""
        <article class="grafico-card">
          {grafico_interactivo(
              afp,
              base,
              combinado,
          )}
        </article>
        """
        for afp in AFPS
    )

    incompletos = combinado[
        combinado["pronostico_valido"].eq(False)
    ]

    aviso_incompletos = ""

    if not incompletos.empty:
        aviso_incompletos = f"""
        <div class="alerta alerta-roja">
          Se ocultaron {len(incompletos)} estimaciones con
          menos de {COBERTURA_MINIMA:.0f}% de cobertura.
          No se consideran pronósticos válidos.
        </div>
        """

    ruta = (
        processed
        / "ca0001_modelo80_dashboard.html"
    )

    documento = f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport"
      content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="300">
<title>Monitor AFP Fondo 3</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
:root {{
  --azul:#123f73;
  --azul2:#2768a8;
  --fondo:#f3f6fb;
  --borde:#d9e2ef;
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
  padding:25px 28px;
  margin-bottom:16px;
}}
header h1 {{
  margin:0 0 8px;
  font-size:30px;
}}
header p {{
  margin:5px 0;
}}
.boton {{
  display:inline-block;
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
  border-radius:9px;
  padding:13px 16px;
  margin:14px 0;
}}
.alerta-roja {{
  background:#fff0f0;
  border-left-color:#c34242;
}}
.seccion {{
  background:white;
  border:1px solid var(--borde);
  border-radius:15px;
  padding:20px;
  margin:17px 0;
  box-shadow:0 4px 15px rgba(20,50,90,.06);
}}
.seccion h2 {{
  color:var(--azul);
  margin:0 0 10px;
}}
.afp-grid {{
  display:grid;
  grid-template-columns:repeat(4,minmax(245px,1fr));
  gap:14px;
}}
.afp-card {{
  background:#fbfdff;
  border:1px solid var(--borde);
  border-radius:14px;
  padding:17px;
}}
.afp-card h3 {{
  color:var(--azul);
  font-size:21px;
  margin:0 0 14px;
}}
.comparacion {{
  display:grid;
  grid-template-columns:1fr auto 1fr;
  gap:9px;
  align-items:center;
}}
.comparacion span {{
  display:block;
  color:var(--suave);
  font-size:12px;
}}
.comparacion strong {{
  display:block;
  font-size:19px;
  margin:4px 0;
}}
.comparacion small {{
  color:var(--suave);
}}
.flecha {{
  color:var(--azul2);
  font-size:25px;
}}
.estado {{
  display:inline-block;
  margin-top:14px;
  padding:7px 11px;
  border-radius:20px;
  font-weight:bold;
  font-size:13px;
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
.mensaje-estado {{
  margin:10px 0 4px;
  font-weight:bold;
}}
.detalle,.cobertura {{
  color:var(--suave);
  font-size:13px;
  margin:4px 0;
}}
.graficos-grid {{
  display:grid;
  grid-template-columns:repeat(2,minmax(420px,1fr));
  gap:18px;
}}
.grafico-card {{
  border:1px solid var(--borde);
  border-radius:13px;
  padding:10px;
  overflow:hidden;
}}
.ayuda {{
  color:var(--suave);
  line-height:1.55;
}}
.ayuda strong {{
  color:var(--texto);
}}
.tabla-wrap {{
  overflow-x:auto;
}}
.tabla {{
  border-collapse:collapse;
  width:100%;
  min-width:800px;
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
.tabla th:first-child,.tabla td:first-child {{
  text-align:left;
}}
.vacio {{
  color:var(--suave);
}}
details summary {{
  cursor:pointer;
  color:var(--azul);
  font-weight:bold;
  padding:6px 0;
}}
@media(max-width:1050px) {{
  .afp-grid {{
    grid-template-columns:repeat(2,1fr);
  }}
}}
@media(max-width:760px) {{
  .afp-grid,.graficos-grid {{
    grid-template-columns:1fr;
  }}
}}
</style>
</head>
<body>
<main>
<header>
  <h1>Monitor interactivo AFP Fondo 3</h1>
  <p>
    <strong>Última cuota oficial SBS:</strong>
    {formato_fecha(ultima_fecha)}
  </p>
  <p>
    <strong>Actualizado:</strong>
    {datetime.now().strftime("%d/%m/%Y %H:%M:%S")}
  </p>
  <button class="boton"
          onclick="location.reload()">
    Recargar tablero
  </button>
  <button class="boton"
          onclick="document.getElementById('graficos').scrollIntoView({{behavior:'smooth'}})">
    Ir a gráficos
  </button>
  <a class="boton"
     href="ca0001_modelo92_indicadores_didacticos.html">
    Ver indicadores del modelo
  </a>
  <a class="boton" href="ca0001_modelo102_tendencia_y_velas_cuota.html">Tendencia y velas de la cuota</a>
  <a class="boton" href="ca0001_modelo97_simulador_monto_fondo3.html">Simular ingreso y salida</a>
  <a class="boton" href="ca0001_modelo111_vela_pronostico_historico.html">Vela pronosticada</a>
</header>

<div class="alerta">
  <strong>Lectura sencilla:</strong>
  la cuota estimada no es la cuota oficial.
  El monitor solo presenta una estimación cuando están disponibles
  todos los indicadores requeridos por esa AFP.
  Fines de semana, feriados o jornadas incompletas no generan
  una cuota estimada válida.
</div>

{aviso_incompletos}

<section class="seccion">
  <h2>Resumen actual</h2>
  <div class="afp-grid">
    {tarjetas}
  </div>
</section>

<section class="seccion" id="graficos">
  <h2>Gráficos interactivos por AFP</h2>
  <p class="ayuda">
    <strong>Línea continua:</strong> cuota real SBS.
    <strong>Línea discontinua:</strong> únicamente estimaciones
    con 100% de los indicadores disponibles.
    No se proyectan cinco días por obligación:
    se muestran solo las fechas reales de mercado que ya cuentan
    con todos los datos necesarios y que la SBS todavía no publica.
    Los botones 5, 10, 15, 20, 25 y 30 días solo cambian
    la ampliación visual del gráfico; no crean pronósticos.
    Arrastra el mouse para ampliar, usa la rueda para zoom
    y haz doble clic para volver a la vista completa.
  </p>
  <div class="graficos-grid">
    {graficos}
  </div>
</section>

<section class="seccion">
  <h2>Estimaciones válidas todavía no publicadas por la SBS</h2>
  <div class="tabla-wrap">
    {tabla_pendientes(combinado)}
  </div>
</section>

<section class="seccion">
  <h2>Pronósticos ya comparados con la SBS</h2>
  <div class="tabla-wrap">
    {tabla_evaluados(combinado)}
  </div>
</section>

<section class="seccion">
  <h2>Resultados acumulados del modelo</h2>
  <div class="tabla-wrap">
    {tabla_metricas(metricas)}
  </div>
</section>

<section class="seccion">
  <details>
    <summary>¿Qué significa cada dato?</summary>
    <p class="ayuda">
      <strong>Cuota estimada:</strong>
      valor calculado por EW-Ridge antes de conocer la cuota SBS.
      <br>
      <strong>Variación estimada:</strong>
      cambio acumulado desde la última cuota oficial utilizada como
      punto de partida.
      <br>
      <strong>Cobertura:</strong>
      porcentaje de indicadores disponibles. No es una probabilidad
      de acierto.
      <br>
      <strong>Desviación:</strong>
      cuota estimada menos cuota real SBS.
      <br>
      <strong>Error:</strong>
      desviación expresada como porcentaje de la cuota real.
    </p>
  </details>
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
            "Actualiza datos y construye un tablero AFP interactivo."
        )
    )

    parser.add_argument(
        "--pronosticar",
        action="store_true",
        help="Actualiza también el pronóstico del modelo.",
    )

    parser.add_argument(
        "--abrir",
        action="store_true",
        help="Abre el tablero al finalizar.",
    )

    parser.add_argument(
        "--solo-tablero",
        action="store_true",
        help="Reconstruye el HTML sin consultar la SBS.",
    )

    args = parser.parse_args()

    asegurar_plotly()

    raiz = Path(
        __file__
    ).resolve().parents[1]

    processed = (
        raiz
        / "data"
        / "processed"
    )

    if not args.solo_tablero:
        codigo = ejecutar_modulo80(
            raiz,
            pronosticar=args.pronosticar,
        )

        if codigo != 0:
            raise RuntimeError(
                f"El módulo 80 terminó con código {codigo}."
            )

    base, pronosticos, metricas = preparar_datos(
        processed
    )

    combinado = combinar_pronosticos_reales(
        base,
        pronosticos,
    )

    tablero = crear_html(
        processed,
        base,
        combinado,
        metricas,
    )

    validos = combinado[
        combinado["pronostico_valido"].eq(True)
    ]

    pendientes = validos[
        validos["cuota_real_sbs"].isna()
    ]

    evaluados = validos[
        validos["cuota_real_sbs"].notna()
    ]

    print("\nTABLERO INTERACTIVO ACTUALIZADO")
    print("=" * 90)
    print(f"Pronósticos pendientes: {len(pendientes)}")
    print(f"Pronósticos evaluados: {len(evaluados)}")
    print(f"Archivo: {tablero.resolve()}")

    if args.abrir:
        webbrowser.open(
            tablero.resolve().as_uri()
        )


if __name__ == "__main__":
    main()
