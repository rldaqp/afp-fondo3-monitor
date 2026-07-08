from __future__ import annotations

import argparse
import json
import webbrowser
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd


AFPS = ["Habitat", "Integra", "Prima", "Profuturo"]

MAPE_RESPALDO = {
    "Habitat": 0.638053,
    "Integra": 0.718793,
    "Prima": 0.783118,
    "Profuturo": 0.751328,
}

DIRECCION_RESPALDO = {
    "Habitat": 83.642496,
    "Integra": 79.763912,
    "Prima": 81.281619,
    "Profuturo": 82.799325,
}


def leer_csv(
    ruta: Path,
    obligatorio: bool = False,
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


def cargar_datos(
    processed: Path,
) -> dict:
    base = leer_csv(
        processed
        / "ca0001_modelo56_base_alineada.csv",
        obligatorio=True,
    )

    pronosticos = leer_csv(
        processed
        / "ca0001_modelo79_primer_pronostico_congelado.csv"
    )

    snapshot = leer_csv(
        processed
        / "ca0001_modelo79_snapshot_estimacion_actual.csv"
    )

    intradia = leer_csv(
        processed
        / "ca0001_modelo99_historial_intradia_cuota.csv"
    )

    metricas = leer_csv(
        processed
        / "ca0001_modelo79a_correlaciones_finales.csv"
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
    )

    estimaciones = []

    if not pronosticos.empty:
        pronosticos["fecha_objetivo"] = pd.to_datetime(
            pronosticos["fecha_objetivo"],
            errors="coerce",
        ).dt.normalize()

        for columna in [
            "cuota_estimada",
            "cobertura_factores_pct",
        ]:
            pronosticos[columna] = pd.to_numeric(
                pronosticos[columna],
                errors="coerce",
            )

        if "run_id" not in pronosticos.columns:
            pronosticos["run_id"] = ""

        pronosticos = (
            pronosticos.dropna(
                subset=[
                    "afp",
                    "fecha_objetivo",
                    "cuota_estimada",
                ]
            )
            .loc[
                lambda x:
                x["cobertura_factores_pct"]
                .fillna(0)
                .ge(100)
            ]
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
        )

        for _, fila in pronosticos.iterrows():
            estimaciones.append(
                {
                    "afp": str(fila["afp"]),
                    "fecha": pd.Timestamp(
                        fila["fecha_objetivo"]
                    ),
                    "cuota": float(
                        fila["cuota_estimada"]
                    ),
                    "fuente": "Pronóstico congelado",
                }
            )

    if not snapshot.empty:
        snapshot["fecha_estimada"] = pd.to_datetime(
            snapshot["fecha_estimada"],
            errors="coerce",
        ).dt.normalize()

        for columna in [
            "cuota_estimada",
            "cobertura_factores_pct",
        ]:
            snapshot[columna] = pd.to_numeric(
                snapshot[columna],
                errors="coerce",
            )

        snapshot = snapshot.dropna(
            subset=[
                "afp",
                "fecha_estimada",
                "cuota_estimada",
            ]
        )

        snapshot = snapshot[
            snapshot["cobertura_factores_pct"]
            .fillna(0)
            .ge(100)
        ]

        for _, fila in snapshot.iterrows():
            estimaciones.append(
                {
                    "afp": str(fila["afp"]),
                    "fecha": pd.Timestamp(
                        fila["fecha_estimada"]
                    ),
                    "cuota": float(
                        fila["cuota_estimada"]
                    ),
                    "fuente": "Estimación vigente",
                }
            )

    estimaciones_df = pd.DataFrame(
        estimaciones
    )

    if not estimaciones_df.empty:
        estimaciones_df = (
            estimaciones_df.sort_values(
                [
                    "afp",
                    "fecha",
                ]
            )
            .drop_duplicates(
                subset=[
                    "afp",
                    "fecha",
                ],
                keep="last",
            )
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

        intradia[
            "cuota_estimada_intradia"
        ] = pd.to_numeric(
            intradia[
                "cuota_estimada_intradia"
            ],
            errors="coerce",
        )

        intradia[
            "cobertura_pct"
        ] = pd.to_numeric(
            intradia[
                "cobertura_pct"
            ],
            errors="coerce",
        )

        intradia = intradia.dropna(
            subset=[
                "afp",
                "timestamp",
                "fecha_objetivo",
                "cuota_estimada_intradia",
            ]
        )

        intradia = intradia[
            intradia["cobertura_pct"]
            .fillna(0)
            .ge(100)
        ]

    metricas_por_afp = {}

    for afp in AFPS:
        metricas_por_afp[afp] = {
            "mape": MAPE_RESPALDO[afp],
            "direccion": DIRECCION_RESPALDO[afp],
        }

    if not metricas.empty:
        for _, fila in metricas.iterrows():
            afp = str(
                fila.get(
                    "afp",
                    "",
                )
            )

            if afp not in metricas_por_afp:
                continue

            mape = pd.to_numeric(
                fila.get(
                    "mape_cuota_pct",
                    np.nan,
                ),
                errors="coerce",
            )

            direccion = pd.to_numeric(
                fila.get(
                    "direccion_acumulada_pct",
                    np.nan,
                ),
                errors="coerce",
            )

            if pd.notna(mape):
                metricas_por_afp[afp][
                    "mape"
                ] = float(mape)

            if pd.notna(direccion):
                metricas_por_afp[afp][
                    "direccion"
                ] = float(direccion)

    datos_afp = {}

    for afp in AFPS:
        oficial = (
            base[
                base["afp"]
                .astype(str)
                .eq(afp)
            ]
            .sort_values(
                "fecha_cuota"
            )
            .copy()
        )

        estimada = (
            estimaciones_df[
                estimaciones_df["afp"]
                .astype(str)
                .eq(afp)
            ]
            .sort_values("fecha")
            .copy()
            if not estimaciones_df.empty
            else pd.DataFrame()
        )

        oficial_puntos = [
            {
                "fecha": pd.Timestamp(
                    fila["fecha_cuota"]
                ).strftime(
                    "%Y-%m-%d"
                ),
                "cuota": float(
                    fila["cuota_sbs"]
                ),
                "fuente": "Oficial SBS",
            }
            for _, fila in oficial.iterrows()
        ]

        estimados_puntos = [
            {
                "fecha": pd.Timestamp(
                    fila["fecha"]
                ).strftime(
                    "%Y-%m-%d"
                ),
                "cuota": float(
                    fila["cuota"]
                ),
                "fuente": str(
                    fila["fuente"]
                ),
            }
            for _, fila in estimada.iterrows()
        ]

        velas_oficiales = []

        valores = oficial[
            [
                "fecha_cuota",
                "cuota_sbs",
            ]
        ].reset_index(drop=True)

        for i in range(
            1,
            len(valores),
        ):
            apertura = float(
                valores.loc[
                    i - 1,
                    "cuota_sbs",
                ]
            )

            cierre = float(
                valores.loc[
                    i,
                    "cuota_sbs",
                ]
            )

            velas_oficiales.append(
                {
                    "fecha": pd.Timestamp(
                        valores.loc[
                            i,
                            "fecha_cuota",
                        ]
                    ).strftime(
                        "%Y-%m-%d"
                    ),
                    "open": apertura,
                    "high": max(
                        apertura,
                        cierre,
                    ),
                    "low": min(
                        apertura,
                        cierre,
                    ),
                    "close": cierre,
                }
            )

        velas_sinteticas = []

        if not intradia.empty:
            x = (
                intradia[
                    intradia["afp"]
                    .astype(str)
                    .eq(afp)
                ]
                .sort_values(
                    "timestamp"
                )
                .copy()
            )

            for fecha, grupo in x.groupby(
                "fecha_objetivo"
            ):
                valores_intradia = pd.to_numeric(
                    grupo[
                        "cuota_estimada_intradia"
                    ],
                    errors="coerce",
                ).dropna()

                if len(
                    valores_intradia
                ) < 2:
                    continue

                velas_sinteticas.append(
                    {
                        "fecha": pd.Timestamp(
                            fecha
                        ).strftime(
                            "%Y-%m-%d"
                        ),
                        "open": float(
                            valores_intradia.iloc[0]
                        ),
                        "high": float(
                            valores_intradia.max()
                        ),
                        "low": float(
                            valores_intradia.min()
                        ),
                        "close": float(
                            valores_intradia.iloc[-1]
                        ),
                        "n": int(
                            len(
                                valores_intradia
                            )
                        ),
                    }
                )

        datos_afp[afp] = {
            "oficial": oficial_puntos,
            "estimado": estimados_puntos,
            "velas_oficiales": (
                velas_oficiales
            ),
            "velas_sinteticas": (
                velas_sinteticas
            ),
            "mape": metricas_por_afp[
                afp
            ]["mape"],
            "direccion": metricas_por_afp[
                afp
            ]["direccion"],
        }

    todas_fechas = []

    for afp in AFPS:
        todas_fechas.extend(
            [
                p["fecha"]
                for p in datos_afp[
                    afp
                ]["oficial"]
            ]
        )

        todas_fechas.extend(
            [
                p["fecha"]
                for p in datos_afp[
                    afp
                ]["estimado"]
            ]
        )

    return {
        "afps": datos_afp,
        "fecha_minima": min(
            todas_fechas
        ),
        "fecha_maxima": max(
            todas_fechas
        ),
    }


def crear_html(
    processed: Path,
    datos: dict,
) -> Path:
    ruta = (
        processed
        / "ca0001_modelo97_simulador_monto_fondo3.html"
    )

    datos_json = json.dumps(
        datos,
        ensure_ascii=False,
    )

    documento = f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport"
      content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="300">
<title>Simulador AFP Fondo 3</title>
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
* {{
  box-sizing:border-box;
}}
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
  font-size:30px;
}}
.boton {{
  display:inline-block;
  text-decoration:none;
  background:white;
  color:var(--azul);
  border:1px solid var(--borde);
  border-radius:9px;
  padding:10px 15px;
  margin:8px 7px 0 0;
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
.controles {{
  background:white;
  border:1px solid var(--borde);
  border-radius:15px;
  padding:20px;
  margin:18px 0;
}}
.campos {{
  display:grid;
  grid-template-columns:
    minmax(210px,1fr)
    minmax(190px,1fr)
    minmax(190px,1fr);
  gap:14px;
}}
.campo label {{
  display:block;
  color:var(--azul);
  font-weight:bold;
  margin-bottom:7px;
}}
.campo input {{
  width:100%;
  border:1px solid var(--borde);
  border-radius:9px;
  padding:12px;
  font-size:17px;
}}
.rapidos {{
  margin-top:13px;
}}
.grid {{
  display:grid;
  grid-template-columns:
    repeat(2,minmax(430px,1fr));
  gap:18px;
}}
.card {{
  background:white;
  border:1px solid var(--borde);
  border-radius:15px;
  padding:19px;
  box-shadow:
    0 4px 15px rgba(20,50,90,.06);
}}
.card h2 {{
  color:var(--azul);
  margin:0 0 13px;
}}
.periodo {{
  display:grid;
  grid-template-columns:1fr auto 1fr;
  gap:10px;
  align-items:center;
}}
.periodo span {{
  display:block;
  color:var(--suave);
  font-size:12px;
}}
.periodo strong {{
  display:block;
  margin-top:4px;
}}
.flecha {{
  color:var(--azul2);
  font-size:26px;
}}
.resultado {{
  margin:15px 0;
  border-radius:10px;
  padding:13px;
}}
.positivo {{
  background:#e8f7ed;
  color:#176437;
}}
.negativo {{
  background:#fdeaea;
  color:#a12626;
}}
.neutro {{
  background:#eef1f5;
  color:#556170;
}}
.resultado strong {{
  display:block;
  font-size:24px;
  margin:5px 0;
}}
.metricas {{
  display:grid;
  grid-template-columns:
    repeat(2,1fr);
  gap:9px;
}}
.metrica {{
  border:1px solid var(--borde);
  border-radius:9px;
  padding:10px;
}}
.metrica span {{
  display:block;
  color:var(--suave);
  font-size:12px;
}}
.metrica strong {{
  display:block;
  margin-top:4px;
}}
.lectura {{
  margin-top:13px;
  padding:11px;
  border-left:5px solid var(--azul2);
  background:#eef5ff;
  line-height:1.45;
}}
.grafico {{
  background:white;
  border:1px solid var(--borde);
  border-radius:15px;
  margin:18px 0;
  padding:13px;
}}
.grafico h2 {{
  color:var(--azul);
  margin-left:12px;
}}
.nota {{
  color:var(--suave);
  line-height:1.5;
  font-size:13px;
}}
.sin-velas {{
  background:#eef5ff;
  border-left:6px solid var(--azul2);
  border-radius:10px;
  padding:18px;
  margin:12px;
  line-height:1.55;
}}
.subtitulo-vela {{
  color:var(--azul2);
  margin:22px 12px 6px;
}}
@media(max-width:980px) {{
  .grid {{
    grid-template-columns:1fr;
  }}
}}
@media(max-width:760px) {{
  .campos {{
    grid-template-columns:1fr;
  }}
  .metricas {{
    grid-template-columns:1fr;
  }}
}}
</style>
</head>
<body>
<main>
<header>
  <h1>Simulador por periodo y velas del valor cuota</h1>
  <p>
    Selecciona cuánto ingresas,
    la fecha de ingreso y la fecha de salida.
  </p>

  <a class="boton"
     href="ca0001_modelo80_dashboard.html">
    Monitor de cuotas
  </a>

  <a class="boton"
     href="ca0001_modelo92_indicadores_didacticos.html">
    Indicadores del modelo
  </a>

  <a class="boton"
     href="ca0001_modelo102_tendencia_y_velas_cuota.html">
    Tendencia y velas
  </a>
  <a class="boton" href="ca0001_modelo111_vela_pronostico_historico.html">Vela pronosticada</a>
</header>

<div class="aviso">
  <strong>Lectura correcta:</strong>
  la cuota oficial histórica se muestra como línea porque la SBS
  publica un solo valor por día. Ya no se dibujan falsas velas
  usando únicamente la cuota anterior y la cuota actual.
  Las velas aparecen exclusivamente cuando existen varias
  estimaciones intradía guardadas para el mismo día; entonces sí
  representan primera, máxima, mínima y última estimación del modelo.
  La simulación es educativa y no representa una orden real.
</div>

<section class="controles">
  <div class="campos">
    <div class="campo">
      <label for="monto">
        Monto hipotético en soles
      </label>
      <input id="monto"
             type="number"
             min="0"
             step="100"
             value="100000">
    </div>

    <div class="campo">
      <label for="fechaIngreso">
        Fecha de ingreso solicitada
      </label>
      <input id="fechaIngreso"
             type="date"
             min="{datos['fecha_minima']}"
             max="{datos['fecha_maxima']}">
    </div>

    <div class="campo">
      <label for="fechaSalida">
        Fecha de salida solicitada
      </label>
      <input id="fechaSalida"
             type="date"
             min="{datos['fecha_minima']}"
             max="{datos['fecha_maxima']}">
    </div>
  </div>

  <div class="rapidos">
    <button class="boton"
            onclick="mantenerDias(1)">
      Mantener 1 día
    </button>
    <button class="boton"
            onclick="mantenerDias(5)">
      Mantener 5 días
    </button>
    <button class="boton"
            onclick="mantenerDias(7)">
      Mantener 1 semana
    </button>
    <button class="boton"
            onclick="mantenerDias(30)">
      Mantener 30 días
    </button>
    <button class="boton"
            onclick="usarUltimaFecha()">
      Salir en la última fecha disponible
    </button>
  </div>

  <p class="nota">
    Si eliges un fin de semana, feriado o una fecha sin cuota,
    el sistema mostrará expresamente la fecha de valorización
    realmente aplicada.
  </p>
</section>

<section class="grid"
         id="resultados"></section>

<section id="graficos"></section>
</main>

<script>
const datos = {datos_json};
const afps = ["Habitat","Integra","Prima","Profuturo"];

function dinero(valor) {{
  return new Intl.NumberFormat(
    "es-PE",
    {{
      style:"currency",
      currency:"PEN",
      minimumFractionDigits:2,
      maximumFractionDigits:2
    }}
  ).format(valor);
}}

function numero(valor, decimales=6) {{
  return new Intl.NumberFormat(
    "es-PE",
    {{
      minimumFractionDigits:decimales,
      maximumFractionDigits:decimales
    }}
  ).format(valor);
}}

function fechaBonita(valor) {{
  if (!valor) return "—";
  const p = valor.split("-");
  return `${{p[2]}}/${{p[1]}}/${{p[0]}}`;
}}

function sumarDias(fechaTexto,dias) {{
  const d = new Date(
    fechaTexto + "T12:00:00"
  );
  d.setDate(
    d.getDate() + dias
  );
  return d.toISOString().slice(0,10);
}}

function mantenerDias(dias) {{
  const ingreso =
    document.getElementById("fechaIngreso").value;
  if (!ingreso) return;
  document.getElementById(
    "fechaSalida"
  ).value = sumarDias(
    ingreso,
    dias
  );
  recalcular();
}}

function usarUltimaFecha() {{
  document.getElementById(
    "fechaSalida"
  ).value = datos.fecha_maxima;
  recalcular();
}}

function puntosCombinados(afp) {{
  const mapa = new Map();

  datos.afps[afp].estimado.forEach(p => {{
    mapa.set(
      p.fecha,
      {{
        ...p,
        prioridad:1
      }}
    );
  }});

  datos.afps[afp].oficial.forEach(p => {{
    mapa.set(
      p.fecha,
      {{
        ...p,
        prioridad:2
      }}
    );
  }});

  return Array.from(
    mapa.values()
  ).sort(
    (a,b) =>
      a.fecha.localeCompare(
        b.fecha
      )
  );
}}

function puntoIngreso(afp,solicitada) {{
  const oficiales =
    datos.afps[afp].oficial;

  const posterior = oficiales.find(
    p => p.fecha >= solicitada
  );

  return posterior ||
    oficiales[
      oficiales.length-1
    ];
}}

function puntoSalida(afp,solicitada) {{
  const puntos = puntosCombinados(afp)
    .filter(
      p => p.fecha <= solicitada
    );

  return puntos[
    puntos.length-1
  ];
}}

function trazaLineaEstimada(afp) {{
  const p = datos.afps[afp].estimado;

  return {{
    type:"scatter",
    mode:"lines+markers",
    name:"Pronóstico / estimación",
    x:p.map(x => x.fecha),
    y:p.map(x => x.cuota),
    line:{{
      width:2.4,
      dash:"dash",
      color:"#ef6c3e"
    }},
    marker:{{
      size:8,
      color:"#ef6c3e"
    }},
    hovertemplate:
      "<b>Estimación</b><br>"+
      "%{{x}}<br>"+
      "%{{y:.6f}}"+
      "<extra></extra>"
  }};
}}

function trazaVelasSinteticas(afp) {{
  const v =
    datos.afps[afp].velas_sinteticas;

  return {{
    type:"candlestick",
    name:"Vela sintética intradía",
    x:v.map(x => x.fecha),
    open:v.map(x => x.open),
    high:v.map(x => x.high),
    low:v.map(x => x.low),
    close:v.map(x => x.close),
    increasing:{{
      line:{{color:"#006d3c",width:3}},
      fillcolor:"#00a85a"
    }},
    decreasing:{{
      line:{{color:"#9d0018",width:3}},
      fillcolor:"#e21c3b"
    }},
    whiskerwidth:1,
    opacity:0.95,
    hovertemplate:
      "<b>%{{x}}</b><br>"+
      "Primera estimación: %{{open:.6f}}<br>"+
      "Máxima: %{{high:.6f}}<br>"+
      "Mínima: %{{low:.6f}}<br>"+
      "Última: %{{close:.6f}}"+
      "<extra></extra>"
  }};
}}

function trazaLineaOficial(afp) {{
  const p = datos.afps[afp].oficial;

  return {{
    type:"scatter",
    mode:"lines",
    name:"Cierre oficial SBS",
    x:p.map(x => x.fecha),
    y:p.map(x => x.cuota),
    line:{{
      width:1.5,
      color:"#225f9d"
    }},
    opacity:0.65,
    hovertemplate:
      "<b>Oficial SBS</b><br>"+
      "%{{x}}<br>"+
      "%{{y:.6f}}"+
      "<extra></extra>"
  }};
}}

function trazaSeleccion(
  entrada,
  salida
) {{
  return {{
    type:"scatter",
    mode:"markers+text",
    name:"Periodo simulado",
    x:[
      entrada.fecha,
      salida.fecha
    ],
    y:[
      entrada.cuota,
      salida.cuota
    ],
    text:[
      "Ingreso",
      "Salida"
    ],
    textposition:"top center",
    marker:{{
      size:13,
      symbol:[
        "triangle-up",
        "triangle-down"
      ],
      color:[
        "#5c2ca0",
        "#e67e22"
      ]
    }},
    hovertemplate:
      "%{{text}}<br>"+
      "%{{x}}<br>"+
      "%{{y:.6f}}"+
      "<extra></extra>"
  }};
}}

function dibujarHistorico(
  afp,
  entrada,
  salida
) {{
  const id =
    "historico-" +
    afp.toLowerCase();

  const trazas = [
    trazaLineaOficial(afp),
    trazaLineaEstimada(afp),
    trazaSeleccion(
      entrada,
      salida
    )
  ];

  const valoresVisibles = [];

  datos.afps[afp].oficial.forEach(p => {{
    if (
      p.fecha >= entrada.fecha &&
      p.fecha <= salida.fecha
    ) {{
      valoresVisibles.push(
        Number(p.cuota)
      );
    }}
  }});

  datos.afps[afp].estimado.forEach(p => {{
    if (
      p.fecha >= entrada.fecha &&
      p.fecha <= salida.fecha
    ) {{
      valoresVisibles.push(
        Number(p.cuota)
      );
    }}
  }});

  valoresVisibles.push(
    Number(entrada.cuota),
    Number(salida.cuota)
  );

  const valoresValidos =
    valoresVisibles.filter(
      Number.isFinite
    );

  const minimoVisible =
    Math.min(...valoresValidos);

  const maximoVisible =
    Math.max(...valoresValidos);

  const amplitudVisible =
    Math.max(
      maximoVisible - minimoVisible,
      Math.abs(maximoVisible) * 0.002,
      0.000001
    );

  const margenVisible =
    amplitudVisible * 0.15;

  Plotly.react(
    id,
    trazas,
    {{
      title:{{
        text:
          afp +
          ": cuota oficial y estimada",
        x:0.02
      }},
      height:480,
      margin:{{
        l:60,
        r:25,
        t:75,
        b:60
      }},
      paper_bgcolor:"white",
      plot_bgcolor:"white",
      hovermode:"x unified",
      legend:{{
        orientation:"h",
        y:1.03,
        x:0
      }},
      xaxis:{{
        title:"Fecha",
        range:[
          entrada.fecha,
          salida.fecha
        ],
        rangeslider:{{
          visible:true,
          thickness:0.10
        }},
        rangeselector:{{
          buttons:[
            {{
              count:5,
              label:"5 días",
              step:"day",
              stepmode:"backward"
            }},
            {{
              count:30,
              label:"1 mes",
              step:"day",
              stepmode:"backward"
            }},
            {{
              count:3,
              label:"3 meses",
              step:"month",
              stepmode:"backward"
            }},
            {{
              count:1,
              label:"1 año",
              step:"year",
              stepmode:"backward"
            }},
            {{
              step:"all",
              label:"Todo"
            }}
          ]
        }},
        showgrid:true,
        gridcolor:"#e7edf4"
      }},
      yaxis:{{
        title:"Valor cuota",
        range:[
          minimoVisible - margenVisible,
          maximoVisible + margenVisible
        ],
        fixedrange:false,
        showgrid:true,
        gridcolor:"#e7edf4"
      }}
    }},
    {{
      responsive:true,
      scrollZoom:true,
      displaylogo:false,
      doubleClick:"reset"
    }}
  );
}}

function dibujarVelasSinteticas(
  afp
) {{
  const id =
    "velas-" +
    afp.toLowerCase();

  const contenedor =
    document.getElementById(id);

  const velas =
    datos.afps[afp]
      .velas_sinteticas;

  if (
    !velas ||
    velas.length === 0
  ) {{
    contenedor.innerHTML = `
      <div class="sin-velas">
        Todavía no existen velas sintéticas históricas para
        ${{afp}}. No se mostrarán rectángulos artificiales.
        La primera vela aparecerá cuando el sistema haya guardado
        por lo menos dos estimaciones válidas del mismo día.
        Desde entonces quedará acumulada en el histórico.
      </div>
    `;
    return;
  }}

  const traza =
    trazaVelasSinteticas(afp);

  Plotly.react(
    id,
    [traza],
    {{
      title:{{
        text:
          afp +
          ": velas sintéticas reales del modelo",
        x:0.02
      }},
      height:510,
      margin:{{
        l:60,
        r:25,
        t:75,
        b:60
      }},
      paper_bgcolor:"white",
      plot_bgcolor:"white",
      showlegend:false,
      hovermode:"x unified",
      xaxis:{{
        title:"Día de estimación",
        type:"category",
        categoryorder:"array",
        categoryarray:
          velas.map(x => x.fecha),
        rangeslider:{{
          visible:false
        }},
        showgrid:true,
        gridcolor:"#e7edf4"
      }},
      yaxis:{{
        title:"Valor cuota estimado",
        autorange:true,
        fixedrange:false,
        showgrid:true,
        gridcolor:"#e7edf4"
      }}
    }},
    {{
      responsive:true,
      scrollZoom:true,
      displaylogo:false,
      doubleClick:"reset"
    }}
  );
}}

function recalcular() {{
  const monto =
    Number(
      document.getElementById(
        "monto"
      ).value
    ) || 0;

  const fechaIngreso =
    document.getElementById(
      "fechaIngreso"
    ).value;

  const fechaSalida =
    document.getElementById(
      "fechaSalida"
    ).value;

  if (
    !fechaIngreso ||
    !fechaSalida
  ) return;

  const resultados =
    document.getElementById(
      "resultados"
    );

  const graficos =
    document.getElementById(
      "graficos"
    );

  resultados.innerHTML = "";
  graficos.innerHTML = "";

  afps.forEach(afp => {{
    const entrada =
      puntoIngreso(
        afp,
        fechaIngreso
      );

    const salida =
      puntoSalida(
        afp,
        fechaSalida
      );

    if (!entrada || !salida) return;

    const cuotas =
      monto / entrada.cuota;

    const saldo =
      cuotas * salida.cuota;

    const ganancia =
      saldo - monto;

    const rentabilidad =
      (
        salida.cuota /
        entrada.cuota -
        1
      ) * 100;

    const dias =
      Math.round(
        (
          new Date(
            salida.fecha
            + "T12:00:00"
          )
          -
          new Date(
            entrada.fecha
            + "T12:00:00"
          )
        )
        /
        86400000
      );

    const estimada =
      salida.fuente
      !== "Oficial SBS";

    const mape =
      datos.afps[afp].mape;

    const errorMonetario =
      estimada
      ? saldo * mape / 100
      : 0;

    const rangoInferior =
      saldo - errorMonetario;

    const rangoSuperior =
      saldo + errorMonetario;

    const clase =
      ganancia > 0
      ? "positivo"
      : (
        ganancia < 0
        ? "negativo"
        : "neutro"
      );

    const card =
      document.createElement(
        "article"
      );

    card.className = "card";

    card.innerHTML = `
      <h2>${{afp}}</h2>

      <div class="periodo">
        <div>
          <span>
            Ingreso solicitado:
            ${{fechaBonita(fechaIngreso)}}
          </span>
          <strong>
            Aplicado:
            ${{fechaBonita(entrada.fecha)}}
          </strong>
          <small>
            Cuota oficial:
            ${{numero(entrada.cuota)}}
          </small>
        </div>

        <div class="flecha">→</div>

        <div>
          <span>
            Salida solicitada:
            ${{fechaBonita(fechaSalida)}}
          </span>
          <strong>
            Aplicado:
            ${{fechaBonita(salida.fecha)}}
          </strong>
          <small>
            ${{salida.fuente}}:
            ${{numero(salida.cuota)}}
          </small>
        </div>
      </div>

      <div class="resultado ${{clase}}">
        Saldo al salir
        <strong>
          ${{dinero(saldo)}}
        </strong>
        Ganancia o pérdida:
        ${{dinero(ganancia)}}
        (${{rentabilidad >= 0 ? "+" : ""}}
        ${{rentabilidad.toFixed(3)}}%)
      </div>

      <div class="metricas">
        <div class="metrica">
          <span>
            Cuotas hipotéticas
          </span>
          <strong>
            ${{numero(cuotas,4)}}
          </strong>
        </div>

        <div class="metrica">
          <span>
            Permanencia aplicada
          </span>
          <strong>
            ${{dias}} días calendario
          </strong>
        </div>

        <div class="metrica">
          <span>
            Fuente de salida
          </span>
          <strong>
            ${{salida.fuente}}
          </strong>
        </div>

        <div class="metrica">
          <span>
            Acierto histórico de dirección
          </span>
          <strong>
            ${{datos.afps[afp]
              .direccion.toFixed(1)}}%
          </strong>
        </div>

        <div class="metrica">
          <span>
            Error medio histórico
          </span>
          <strong>
            ${{
              estimada
              ? mape.toFixed(3) + "%"
              : "No aplica: salida oficial"
            }}
          </strong>
        </div>

        <div class="metrica">
          <span>
            Rango orientativo
          </span>
          <strong>
            ${{
              estimada
              ? dinero(rangoInferior)
                + " — "
                + dinero(rangoSuperior)
              : dinero(saldo)
            }}
          </strong>
        </div>
      </div>

      <div class="lectura">
        <strong>Lectura:</strong>
        ${{
          estimada
          ? "El resultado de salida todavía es un pronóstico. "
            + "El rango usa el error medio histórico como referencia, "
            + "no como garantía."
          : "La salida utiliza una cuota oficial histórica; "
            + "por eso este resultado no tiene error de pronóstico."
        }}
      </div>
    `;

    resultados.appendChild(
      card
    );

    const bloque =
      document.createElement(
        "section"
      );

    bloque.className = "grafico";

    bloque.innerHTML = `
      <h2>
        ${{afp}} — histórico y vela sintética
      </h2>

      <p class="nota">
        El gráfico superior usa líneas porque la SBS publica
        una sola cuota por día. El gráfico inferior muestra
        únicamente velas sintéticas construidas con varias
        estimaciones intradía válidas; no se fabrican máximos
        ni mínimos para días sin datos intradía.
      </p>

      <div id="historico-${{
        afp.toLowerCase()
      }}"></div>

      <h3 class="subtitulo-vela">
        Vela sintética del valor cuota estimado
      </h3>

      <div id="velas-${{
        afp.toLowerCase()
      }}"></div>
    `;

    graficos.appendChild(
      bloque
    );

    dibujarHistorico(
      afp,
      entrada,
      salida
    );

    dibujarVelasSinteticas(
      afp
    );
  }});
}}

document.getElementById(
  "monto"
).addEventListener(
  "input",
  recalcular
);

document.getElementById(
  "fechaIngreso"
).addEventListener(
  "change",
  recalcular
);

document.getElementById(
  "fechaSalida"
).addEventListener(
  "change",
  recalcular
);

const fechaMax =
  datos.fecha_maxima;

const fechaIngresoInicial =
  sumarDias(
    fechaMax,
    -30
  );

document.getElementById(
  "fechaIngreso"
).value =
  fechaIngresoInicial;

document.getElementById(
  "fechaSalida"
).value =
  fechaMax;

recalcular();
</script>
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
            "Genera el simulador por periodo "
            "y las velas del valor cuota."
        )
    )

    parser.add_argument(
        "--abrir",
        action="store_true",
        help="Abre el simulador al terminar.",
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

    datos = cargar_datos(
        processed
    )

    pagina = crear_html(
        processed,
        datos,
    )

    print(
        "\nSIMULADOR POR PERIODO Y VELAS ACTUALIZADO"
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
