from __future__ import annotations

import argparse
import html
import webbrowser
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd


AFPS = ["Habitat", "Integra", "Prima", "Profuturo"]
VENTANA_HISTORICA = 252
N_VELAS_HISTORICAS = 60


def leer_csv(ruta: Path, obligatorio: bool = False) -> pd.DataFrame:
    if not ruta.exists():
        if obligatorio:
            raise FileNotFoundError(f"Falta el archivo: {ruta}")
        return pd.DataFrame()

    ultimo_error = None

    for encoding in ["utf-8-sig", "latin-1", "utf-8"]:
        try:
            return pd.read_csv(ruta, encoding=encoding)
        except Exception as exc:
            ultimo_error = exc

    raise RuntimeError(f"No se pudo leer {ruta}: {ultimo_error}")


def cargar_base(processed: Path) -> pd.DataFrame:
    base = leer_csv(
        processed / "ca0001_modelo56_base_alineada.csv",
        obligatorio=True,
    )

    base["fecha_cuota"] = pd.to_datetime(
        base["fecha_cuota"],
        errors="coerce",
    ).dt.normalize()

    base["cuota_sbs"] = pd.to_numeric(
        base["cuota_sbs"],
        errors="coerce",
    )

    return (
        base.dropna(subset=["afp", "fecha_cuota", "cuota_sbs"])
        .drop_duplicates(
            subset=["afp", "fecha_cuota"],
            keep="last",
        )
        .sort_values(["afp", "fecha_cuota"])
    )


def estimacion_actual(
    afp: str,
    processed: Path,
) -> dict | None:
    intradia = leer_csv(
        processed / "ca0001_modelo99_historial_intradia_cuota.csv"
    )

    if not intradia.empty:
        intradia["timestamp"] = pd.to_datetime(
            intradia["timestamp"],
            errors="coerce",
        )

        intradia["fecha_objetivo"] = pd.to_datetime(
            intradia["fecha_objetivo"],
            errors="coerce",
        ).dt.normalize()

        intradia["cuota_estimada_intradia"] = pd.to_numeric(
            intradia["cuota_estimada_intradia"],
            errors="coerce",
        )

        intradia["cobertura_pct"] = pd.to_numeric(
            intradia["cobertura_pct"],
            errors="coerce",
        )

        x = (
            intradia[
                intradia["afp"]
                .astype(str)
                .eq(afp)
            ]
            .dropna(
                subset=[
                    "timestamp",
                    "fecha_objetivo",
                    "cuota_estimada_intradia",
                ]
            )
            .loc[
                lambda z:
                z["cobertura_pct"]
                .fillna(0)
                .ge(100)
            ]
            .sort_values("timestamp")
        )

        if not x.empty:
            fila = x.iloc[-1]

            return {
                "fecha": pd.Timestamp(
                    fila["fecha_objetivo"]
                ),
                "timestamp": pd.Timestamp(
                    fila["timestamp"]
                ),
                "cuota_estimada": float(
                    fila["cuota_estimada_intradia"]
                ),
                "fuente": "Estimación intradía más reciente",
            }

    snapshot = leer_csv(
        processed / "ca0001_modelo79_snapshot_estimacion_actual.csv"
    )

    if not snapshot.empty:
        snapshot["fecha_estimada"] = pd.to_datetime(
            snapshot["fecha_estimada"],
            errors="coerce",
        ).dt.normalize()

        snapshot["cuota_estimada"] = pd.to_numeric(
            snapshot["cuota_estimada"],
            errors="coerce",
        )

        snapshot["cobertura_factores_pct"] = pd.to_numeric(
            snapshot["cobertura_factores_pct"],
            errors="coerce",
        )

        x = snapshot[
            snapshot["afp"]
            .astype(str)
            .eq(afp)
        ].dropna(
            subset=[
                "fecha_estimada",
                "cuota_estimada",
            ]
        )

        x = x[
            x["cobertura_factores_pct"]
            .fillna(0)
            .ge(100)
        ]

        if not x.empty:
            fila = x.sort_values("fecha_estimada").iloc[-1]

            return {
                "fecha": pd.Timestamp(
                    fila["fecha_estimada"]
                ),
                "timestamp": pd.NaT,
                "cuota_estimada": float(
                    fila["cuota_estimada"]
                ),
                "fuente": "Pronóstico diario vigente",
            }

    return None


def construir_velas(
    oficial: pd.DataFrame,
    estimacion: dict | None,
) -> tuple[pd.DataFrame, dict | None]:
    x = oficial.sort_values("fecha_cuota").copy()

    x["retorno"] = x["cuota_sbs"].pct_change(
        fill_method=None
    )

    filas = []

    for i in range(1, len(x)):
        previo = x.iloc[
            max(1, i - VENTANA_HISTORICA):i
        ]["retorno"].dropna()

        if len(previo) < 30:
            continue

        apertura = float(
            x.iloc[i - 1]["cuota_sbs"]
        )

        cierre_real = float(
            x.iloc[i]["cuota_sbs"]
        )

        q10 = float(
            previo.quantile(0.10)
        )

        q90 = float(
            previo.quantile(0.90)
        )

        rango_bajo = apertura * (1.0 + q10)
        rango_alto = apertura * (1.0 + q90)

        filas.append(
            {
                "fecha": pd.Timestamp(
                    x.iloc[i]["fecha_cuota"]
                ),
                "open": apertura,
                "close": cierre_real,
                "low": min(
                    apertura,
                    cierre_real,
                    rango_bajo,
                ),
                "high": max(
                    apertura,
                    cierre_real,
                    rango_alto,
                ),
                "rango_bajo": rango_bajo,
                "rango_alto": rango_alto,
                "tipo": "Histórico oficial",
            }
        )

    historicas = pd.DataFrame(filas).tail(
        N_VELAS_HISTORICAS
    )

    actual = None

    if estimacion is not None and not x.empty:
        fecha_estimacion = pd.Timestamp(
            estimacion["fecha"]
        ).normalize()

        anteriores = x[
            x["fecha_cuota"].lt(
                fecha_estimacion
            )
        ]

        if anteriores.empty:
            anteriores = x

        ancla = anteriores.iloc[-1]

        cuota_base = float(
            ancla["cuota_sbs"]
        )

        fecha_base = pd.Timestamp(
            ancla["fecha_cuota"]
        )

        retornos_previos = (
            x[
                x["fecha_cuota"]
                .le(fecha_base)
            ]["retorno"]
            .dropna()
            .tail(VENTANA_HISTORICA)
        )

        if len(retornos_previos) >= 30:
            q10 = float(
                retornos_previos.quantile(0.10)
            )
            q90 = float(
                retornos_previos.quantile(0.90)
            )
            q25 = float(
                retornos_previos.quantile(0.25)
            )
            q75 = float(
                retornos_previos.quantile(0.75)
            )
        else:
            q10 = -0.01
            q90 = 0.01
            q25 = -0.005
            q75 = 0.005

        cuota_estimada = float(
            estimacion["cuota_estimada"]
        )

        retorno_estimado = (
            cuota_estimada / cuota_base - 1.0
        )

        rango_bajo = cuota_base * (1.0 + q10)
        rango_alto = cuota_base * (1.0 + q90)

        zona_central_baja = (
            cuota_base * (1.0 + q25)
        )

        zona_central_alta = (
            cuota_base * (1.0 + q75)
        )

        percentil = float(
            retornos_previos
            .le(retorno_estimado)
            .mean()
            * 100.0
        ) if not retornos_previos.empty else np.nan

        actual = {
            "fecha": fecha_estimacion,
            "fecha_base": fecha_base,
            "cuota_base": cuota_base,
            "cuota_estimada": cuota_estimada,
            "retorno_estimado_pct": (
                retorno_estimado * 100.0
            ),
            "low": min(
                cuota_base,
                cuota_estimada,
                rango_bajo,
            ),
            "high": max(
                cuota_base,
                cuota_estimada,
                rango_alto,
            ),
            "rango_bajo": rango_bajo,
            "rango_alto": rango_alto,
            "zona_central_baja": (
                zona_central_baja
            ),
            "zona_central_alta": (
                zona_central_alta
            ),
            "percentil": percentil,
            "fuente": estimacion["fuente"],
            "timestamp": estimacion["timestamp"],
        }

    return historicas, actual


def grafico_html(
    afp: str,
    historicas: pd.DataFrame,
    actual: dict | None,
) -> str:
    import plotly.graph_objects as go
    import plotly.io as pio

    fig = go.Figure()

    if not historicas.empty:
        fig.add_trace(
            go.Candlestick(
                x=historicas["fecha"],
                open=historicas["open"],
                high=historicas["high"],
                low=historicas["low"],
                close=historicas["close"],
                increasing=dict(
                    line=dict(
                        color="#159447",
                        width=1.5,
                    ),
                    fillcolor="#8fd3a8",
                ),
                decreasing=dict(
                    line=dict(
                        color="#d52236",
                        width=1.5,
                    ),
                    fillcolor="#ef9a9a",
                ),
                whiskerwidth=0.8,
                name="Rango histórico diario",
                hovertext=[
                    (
                        "Cuota anterior: "
                        f"{o:.6f}<br>"
                        "Cuota oficial: "
                        f"{c:.6f}<br>"
                        "Rango histórico bajo: "
                        f"{rb:.6f}<br>"
                        "Rango histórico alto: "
                        f"{ra:.6f}"
                    )
                    for o, c, rb, ra
                    in zip(
                        historicas["open"],
                        historicas["close"],
                        historicas["rango_bajo"],
                        historicas["rango_alto"],
                    )
                ],
                hoverinfo="text+x",
            )
        )

    if actual is not None:
        fecha = actual["fecha"]

        fig.add_trace(
            go.Candlestick(
                x=[fecha],
                open=[actual["cuota_base"]],
                high=[actual["high"]],
                low=[actual["low"]],
                close=[actual["cuota_estimada"]],
                increasing=dict(
                    line=dict(
                        color="#006d3c",
                        width=4,
                    ),
                    fillcolor="#00a85a",
                ),
                decreasing=dict(
                    line=dict(
                        color="#9d0018",
                        width=4,
                    ),
                    fillcolor="#e21c3b",
                ),
                whiskerwidth=1,
                name="Vela pronosticada actual",
                hovertext=[
                    (
                        "Cuota base: "
                        f"{actual['cuota_base']:.6f}<br>"
                        "Rango histórico bajo: "
                        f"{actual['rango_bajo']:.6f}<br>"
                        "Rango histórico alto: "
                        f"{actual['rango_alto']:.6f}<br>"
                        "Cuota estimada: "
                        f"{actual['cuota_estimada']:.6f}<br>"
                        "Percentil histórico: "
                        f"{actual['percentil']:.1f}%"
                    )
                ],
                hoverinfo="text+x",
            )
        )

        fig.add_trace(
            go.Scatter(
                x=[fecha],
                y=[actual["cuota_estimada"]],
                mode="markers+text",
                text=[
                    (
                        "Estimado "
                        f"{actual['cuota_estimada']:.6f}"
                    )
                ],
                textposition="middle right",
                marker=dict(
                    size=15,
                    symbol="diamond",
                    color="#6f2dbd",
                    line=dict(
                        width=2,
                        color="white",
                    ),
                ),
                name="Punto estimado",
                hovertemplate=(
                    "<b>Cuota estimada</b><br>"
                    "%{x|%d/%m/%Y}<br>"
                    "%{y:.6f}"
                    "<extra></extra>"
                ),
            )
        )

        fig.add_hline(
            y=actual["cuota_estimada"],
            line_dash="dash",
            line_width=2,
            annotation_text="Cuota estimada",
            annotation_position="top right",
        )

        fig.add_hrect(
            y0=actual["zona_central_baja"],
            y1=actual["zona_central_alta"],
            opacity=0.10,
            line_width=0,
            annotation_text="50% central histórico",
            annotation_position="inside top left",
        )

    fig.update_layout(
        title=dict(
            text=(
                f"{afp}: vela pronosticada "
                "y ubicación del estimado"
            ),
            x=0.02,
        ),
        height=600,
        margin=dict(
            l=70,
            r=90,
            t=85,
            b=70,
        ),
        paper_bgcolor="white",
        plot_bgcolor="white",
        hovermode="x unified",
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="left",
            x=0,
        ),
        xaxis=dict(
            title="Fecha",
            rangeslider=dict(
                visible=True,
                thickness=0.10,
            ),
            showgrid=True,
            gridcolor="#e7edf4",
        ),
        yaxis=dict(
            title="Valor cuota",
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
            "scrollZoom": True,
            "displaylogo": False,
            "doubleClick": "reset",
        },
    )


def crear_html(
    processed: Path,
    base: pd.DataFrame,
) -> Path:
    secciones = []

    for afp in AFPS:
        oficial = (
            base[
                base["afp"]
                .astype(str)
                .eq(afp)
            ]
            .copy()
        )

        estimacion = estimacion_actual(
            afp,
            processed,
        )

        historicas, actual = construir_velas(
            oficial,
            estimacion,
        )

        if actual is None:
            resumen = (
                "No existe una estimación vigente "
                "con cobertura completa."
            )
        else:
            hora = (
                pd.Timestamp(
                    actual["timestamp"]
                ).strftime(
                    "%d/%m/%Y %H:%M"
                )
                if pd.notna(
                    actual["timestamp"]
                )
                else "cierre diario"
            )

            resumen = (
                f"Base: "
                f"{actual['cuota_base']:.6f} · "
                f"Estimado: "
                f"{actual['cuota_estimada']:.6f} · "
                f"Variación: "
                f"{actual['retorno_estimado_pct']:+.3f}% · "
                f"Percentil histórico: "
                f"{actual['percentil']:.1f}% · "
                f"Fuente: "
                f"{actual['fuente']} · "
                f"Actualización: {hora}"
            )

        secciones.append(
            f"""
            <section class="seccion">
              <h2>{html.escape(afp)}</h2>
              <p class="resumen">
                {html.escape(resumen)}
              </p>
              {grafico_html(
                  afp,
                  historicas,
                  actual,
              )}
            </section>
            """
        )

    ruta = (
        processed
        / "ca0001_modelo111_vela_pronostico_historico.html"
    )

    documento = f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport"
      content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="300">
<title>Vela pronosticada AFP Fondo 3</title>
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
  background:linear-gradient(
    135deg,
    var(--azul),
    var(--azul2)
  );
  border-radius:16px;
  padding:25px 28px;
}}
header h1 {{
  margin:0 0 8px;
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
.aviso {{
  background:#fff7d6;
  border-left:6px solid #d7a400;
  border-radius:9px;
  padding:15px 17px;
  margin:16px 0;
  line-height:1.55;
}}
.seccion {{
  background:white;
  border:1px solid var(--borde);
  border-radius:15px;
  padding:20px;
  margin:18px 0;
  box-shadow:
    0 4px 15px rgba(20,50,90,.06);
}}
.seccion h2 {{
  color:var(--azul);
  margin:0 0 8px;
}}
.resumen {{
  color:var(--suave);
  line-height:1.5;
  font-weight:bold;
}}
</style>
</head>
<body>
<main>
<header>
  <h1>
    Vela pronosticada con rango histórico
  </h1>
  <p>
    Actualizado:
    <strong>
      {datetime.now().strftime("%d/%m/%Y %H:%M:%S")}
    </strong>
  </p>

  <a class="boton"
     href="ca0001_modelo80_dashboard.html">
    Monitor principal
  </a>

  <a class="boton"
     href="ca0001_modelo97_simulador_monto_fondo3.html">
    Simulador
  </a>

  <a class="boton"
     href="ca0001_modelo92_indicadores_didacticos.html">
    Indicadores
  </a>
</header>

<div class="aviso">
  <strong>Cómo leerla:</strong>
  el cuerpo de la última vela va desde la última cuota oficial
  hasta la cuota estimada. Las mechas utilizan el rango histórico
  entre los percentiles 10 y 90 de los retornos diarios anteriores.
  El rombo y la línea morada marcan exactamente la estimación.
  Así puedes ver si el pronóstico cae dentro de un movimiento
  habitual, cerca de un extremo o fuera del rango histórico.
  No representa máximos y mínimos intradía oficiales.
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
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--abrir",
        action="store_true",
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

    base = cargar_base(
        processed
    )

    pagina = crear_html(
        processed,
        base,
    )

    print(
        "\nVELA PRONOSTICADA ACTUALIZADA"
    )
    print("=" * 95)
    print(
        f"Página: {pagina.resolve()}"
    )

    if args.abrir:
        webbrowser.open(
            pagina.resolve().as_uri()
        )


if __name__ == "__main__":
    main()
