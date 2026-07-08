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
import matplotlib.pyplot as plt


AFPS = ["Habitat", "Integra", "Prima", "Profuturo"]
COBERTURA_MINIMA = 60.0
VENTANA_GRAFICO_DIAS = 150


def leer_csv(ruta: Path) -> pd.DataFrame:
    if not ruta.exists():
        return pd.DataFrame()

    ultimo_error = None

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
    ruta = (
        raiz
        / "src"
        / "80_monitor_sbs_y_validar_pronosticos.py"
    )

    if not ruta.exists():
        raise FileNotFoundError(
            f"No se encontró el módulo 80:\n{ruta}"
        )

    comando = [
        sys.executable,
        str(ruta),
    ]

    if pronosticar:
        comando.append("--pronosticar")

    proceso = subprocess.run(
        comando,
        cwd=str(raiz),
        check=False,
    )

    return int(proceso.returncode)


def preparar_datos(
    processed: Path,
) -> dict[str, pd.DataFrame]:
    base = leer_csv(
        processed
        / "ca0001_modelo56_base_alineada.csv"
    )

    pronosticos = leer_csv(
        processed
        / "ca0001_modelo79_primer_pronostico_congelado.csv"
    )

    evaluacion = leer_csv(
        processed
        / "ca0001_modelo80_evaluacion_prospectiva.csv"
    )

    metricas = leer_csv(
        processed
        / "ca0001_modelo80_metricas_prospectivas.csv"
    )

    oficiales_monitor = leer_csv(
        processed
        / "ca0001_modelo80_sbs_oficial_detectado.csv"
    )

    if not base.empty:
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

    if not pronosticos.empty:
        for columna in [
            "fecha_objetivo",
            "fecha_ultima_cuota_oficial",
        ]:
            if columna in pronosticos.columns:
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
            if columna in pronosticos.columns:
                pronosticos[columna] = pd.to_numeric(
                    pronosticos[columna],
                    errors="coerce",
                )

        # Elimina las filas defectuosas que aparecían como NaT.
        pronosticos = pronosticos.dropna(
            subset=[
                "afp",
                "fecha_objetivo",
                "cuota_estimada",
            ]
        )

        # Conserva la primera estimación realmente congelada.
        pronosticos = (
            pronosticos.sort_values(
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

    if not evaluacion.empty:
        evaluacion["fecha_objetivo"] = pd.to_datetime(
            evaluacion["fecha_objetivo"],
            errors="coerce",
        ).dt.normalize()

        evaluacion = evaluacion.dropna(
            subset=[
                "afp",
                "fecha_objetivo",
            ]
        )

    if not oficiales_monitor.empty:
        oficiales_monitor["fecha_cuota"] = pd.to_datetime(
            oficiales_monitor["fecha_cuota"],
            errors="coerce",
        ).dt.normalize()

        oficiales_monitor["cuota_sbs"] = pd.to_numeric(
            oficiales_monitor["cuota_sbs"],
            errors="coerce",
        )

    return {
        "base": base,
        "pronosticos": pronosticos,
        "evaluacion": evaluacion,
        "metricas": metricas,
        "oficiales_monitor": oficiales_monitor,
    }


def clasificar_pronosticos(
    base: pd.DataFrame,
    pronosticos: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if pronosticos.empty:
        vacio = pd.DataFrame()
        return vacio, vacio, vacio

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
        .drop_duplicates(
            subset=[
                "afp",
                "fecha_objetivo",
            ],
            keep="last",
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

    combinado[
        "retorno_acumulado_estimado_pct"
    ] = (
        combinado[
            "retorno_acumulado_estimado"
        ]
        * 100.0
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

    cobertura = combinado[
        "cobertura_factores_pct"
    ].fillna(0.0)

    valido = cobertura.ge(
        COBERTURA_MINIMA
    )

    publicado = combinado[
        "cuota_real_sbs"
    ].notna()

    pendientes_validos = combinado[
        valido & ~publicado
    ].copy()

    evaluados = combinado[
        valido & publicado
    ].copy()

    incompletos = combinado[
        ~valido & ~publicado
    ].copy()

    return (
        pendientes_validos,
        evaluados,
        incompletos,
    )


def ultima_cuota_por_afp(
    base: pd.DataFrame,
) -> pd.DataFrame:
    if base.empty:
        return pd.DataFrame()

    return (
        base.sort_values(
            "fecha_cuota"
        )
        .groupby(
            "afp",
            as_index=False,
        )
        .tail(1)
        [
            [
                "afp",
                "fecha_cuota",
                "cuota_sbs",
            ]
        ]
    )


def crear_graficos_actuales(
    base: pd.DataFrame,
    pronosticos_validos: pd.DataFrame,
    carpeta: Path,
) -> None:
    carpeta.mkdir(
        parents=True,
        exist_ok=True,
    )

    for afp in AFPS:
        real = base[
            base["afp"]
            .astype(str)
            .eq(afp)
        ].copy()

        if real.empty:
            continue

        ultima_fecha = real[
            "fecha_cuota"
        ].max()

        inicio = (
            ultima_fecha
            - pd.Timedelta(
                days=VENTANA_GRAFICO_DIAS
            )
        )

        real = real[
            real["fecha_cuota"]
            .ge(inicio)
        ].sort_values(
            "fecha_cuota"
        )

        pred = pronosticos_validos[
            pronosticos_validos["afp"]
            .astype(str)
            .eq(afp)
        ].copy()

        pred = pred[
            pred["fecha_objetivo"]
            .ge(inicio)
        ].sort_values(
            "fecha_objetivo"
        )

        plt.figure(
            figsize=(12, 5.2)
        )

        plt.plot(
            real["fecha_cuota"],
            real["cuota_sbs"],
            linewidth=2,
            label="Cuota real SBS",
        )

        if not pred.empty:
            # Conecta la proyección con la última cuota oficial.
            ancla = real.iloc[-1]

            fechas_pred = pd.concat(
                [
                    pd.Series(
                        [
                            ancla[
                                "fecha_cuota"
                            ]
                        ]
                    ),
                    pred[
                        "fecha_objetivo"
                    ].reset_index(
                        drop=True
                    ),
                ],
                ignore_index=True,
            )

            cuotas_pred = pd.concat(
                [
                    pd.Series(
                        [
                            ancla[
                                "cuota_sbs"
                            ]
                        ]
                    ),
                    pred[
                        "cuota_estimada"
                    ].reset_index(
                        drop=True
                    ),
                ],
                ignore_index=True,
            )

            plt.plot(
                fechas_pred,
                cuotas_pred,
                linestyle="--",
                marker="o",
                linewidth=2,
                label="Pronóstico congelado",
            )

            ultima_pred = pred.iloc[-1]

            plt.annotate(
                (
                    f"{ultima_pred['cuota_estimada']:.6f}\n"
                    f"{ultima_pred['direccion_estimada']}"
                ),
                (
                    ultima_pred[
                        "fecha_objetivo"
                    ],
                    ultima_pred[
                        "cuota_estimada"
                    ],
                ),
                xytext=(8, 8),
                textcoords="offset points",
            )

        plt.title(
            f"Seguimiento actual: cuota real y pronóstico — {afp}"
        )
        plt.xlabel("Fecha")
        plt.ylabel("Valor cuota")
        plt.grid(
            True,
            alpha=0.25,
        )
        plt.legend()
        plt.tight_layout()

        plt.savefig(
            carpeta
            / f"seguimiento_actual_{afp.lower()}.png",
            dpi=170,
            bbox_inches="tight",
        )

        plt.close()


def formato_fecha(
    valor,
) -> str:
    if pd.isna(valor):
        return "—"

    return pd.Timestamp(
        valor
    ).strftime(
        "%d/%m/%Y"
    )


def tarjeta_afp_html(
    afp: str,
    ultima_real: pd.DataFrame,
    pendientes: pd.DataFrame,
    evaluados: pd.DataFrame,
) -> str:
    real = ultima_real[
        ultima_real["afp"]
        .astype(str)
        .eq(afp)
    ]

    pendiente = pendientes[
        pendientes["afp"]
        .astype(str)
        .eq(afp)
    ].sort_values(
        "fecha_objetivo"
    )

    evaluado = evaluados[
        evaluados["afp"]
        .astype(str)
        .eq(afp)
    ].sort_values(
        "fecha_objetivo"
    )

    if real.empty:
        cuota_real = "—"
        fecha_real = "—"
    else:
        fila_real = real.iloc[-1]
        cuota_real = (
            f"{fila_real['cuota_sbs']:.6f}"
        )
        fecha_real = formato_fecha(
            fila_real["fecha_cuota"]
        )

    if not pendiente.empty:
        fila = pendiente.iloc[-1]
        cuota_estimada = (
            f"{fila['cuota_estimada']:.6f}"
        )
        fecha_estimada = formato_fecha(
            fila["fecha_objetivo"]
        )
        variacion = (
            f"{fila['retorno_acumulado_estimado_pct']:+.3f}%"
        )
        direccion = str(
            fila["direccion_estimada"]
        )
        estado = "Esperando publicación SBS"
        clase = (
            "sube"
            if direccion == "SUBE"
            else "baja"
        )
        detalle = (
            f"Cobertura: "
            f"{fila['cobertura_factores_pct']:.0f}%"
        )
    elif not evaluado.empty:
        fila = evaluado.iloc[-1]
        cuota_estimada = (
            f"{fila['cuota_estimada']:.6f}"
        )
        fecha_estimada = formato_fecha(
            fila["fecha_objetivo"]
        )
        variacion = (
            f"Error: {fila['error_pct']:+.3f}%"
        )
        direccion = "EVALUADO"
        estado = (
            f"Cuota real: "
            f"{fila['cuota_real_sbs']:.6f}"
        )
        clase = "evaluado"
        detalle = (
            f"Desviación: "
            f"{fila['desviacion_cuota']:+.6f}"
        )
    else:
        cuota_estimada = "—"
        fecha_estimada = "—"
        variacion = "—"
        direccion = "SIN PRONÓSTICO"
        estado = "Sin pronóstico válido pendiente"
        clase = "neutral"
        detalle = ""

    return f"""
    <article class="afp-card">
      <div class="afp-title">{html.escape(afp)}</div>
      <div class="datos-grid">
        <div>
          <span class="etiqueta">Última cuota SBS</span>
          <strong>{cuota_real}</strong>
          <small>{fecha_real}</small>
        </div>
        <div>
          <span class="etiqueta">Cuota estimada</span>
          <strong>{cuota_estimada}</strong>
          <small>{fecha_estimada}</small>
        </div>
      </div>
      <div class="estado {clase}">
        {html.escape(direccion)} · {html.escape(variacion)}
      </div>
      <p class="estado-texto">
        {html.escape(estado)}
      </p>
      <p class="detalle">{html.escape(detalle)}</p>
    </article>
    """


def tabla_pendientes_html(
    pendientes: pd.DataFrame,
) -> str:
    if pendientes.empty:
        return (
            "<p class='mensaje'>No existen pronósticos "
            "válidos pendientes de publicación.</p>"
        )

    tabla = pendientes.copy()

    tabla = tabla[
        [
            "afp",
            "fecha_objetivo",
            "cuota_ultima_oficial",
            "cuota_estimada",
            "retorno_acumulado_estimado_pct",
            "direccion_estimada",
            "cobertura_factores_pct",
        ]
    ].rename(
        columns={
            "afp": "AFP",
            "fecha_objetivo": "Fecha pronosticada",
            "cuota_ultima_oficial": "Cuota oficial de partida",
            "cuota_estimada": "Cuota estimada",
            "retorno_acumulado_estimado_pct": "Variación estimada (%)",
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


def tabla_evaluados_html(
    evaluados: pd.DataFrame,
) -> str:
    if evaluados.empty:
        return (
            "<p class='mensaje'>Todavía no existe una cuota "
            "SBS que coincida con un pronóstico congelado.</p>"
        )

    tabla = evaluados.copy()

    tabla = tabla[
        [
            "afp",
            "fecha_objetivo",
            "cuota_estimada",
            "cuota_real_sbs",
            "desviacion_cuota",
            "error_pct",
            "direccion_estimada",
        ]
    ].rename(
        columns={
            "afp": "AFP",
            "fecha_objetivo": "Fecha",
            "cuota_estimada": "Cuota estimada",
            "cuota_real_sbs": "Cuota real SBS",
            "desviacion_cuota": "Desviación",
            "error_pct": "Error (%)",
            "direccion_estimada": "Dirección pronosticada",
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


def tabla_metricas_html(
    metricas: pd.DataFrame,
) -> str:
    if metricas.empty:
        return (
            "<p class='mensaje'>Las métricas aparecerán "
            "cuando la SBS publique al menos una fecha "
            "pronosticada.</p>"
        )

    tabla = metricas.copy()

    tabla = tabla.rename(
        columns={
            "afp": "AFP",
            "n_pronosticos_evaluados": "Pronósticos evaluados",
            "mape_prospectivo_pct": "Error medio (%)",
            "sesgo_pct": "Sesgo (%)",
            "p90_error_abs_pct": "P90 error (%)",
            "error_maximo_abs_pct": "Error máximo (%)",
            "acierto_direccion_pct": "Acierto dirección (%)",
            "pearson_retorno": "Correlación retorno",
        }
    )

    return tabla.to_html(
        index=False,
        border=0,
        classes="tabla",
        float_format=lambda x: f"{x:.3f}",
    )


def crear_dashboard_amigable(
    processed: Path,
    datos: dict[str, pd.DataFrame],
    pendientes: pd.DataFrame,
    evaluados: pd.DataFrame,
    incompletos: pd.DataFrame,
    carpeta_graficos: Path,
) -> Path:
    base = datos["base"]
    metricas = datos["metricas"]
    oficiales = datos["oficiales_monitor"]

    ultima_real = ultima_cuota_por_afp(
        base
    )

    ultima_fecha_sbs = (
        oficiales["fecha_cuota"].max()
        if not oficiales.empty
        else base["fecha_cuota"].max()
    )

    tarjetas = "".join(
        tarjeta_afp_html(
            afp,
            ultima_real,
            pendientes,
            evaluados,
        )
        for afp in AFPS
    )

    graficos_actuales = "".join(
        f"""
        <article class="grafico-card">
          <h3>{afp}</h3>
          <img
            src="graficos_monitor_amigable/seguimiento_actual_{afp.lower()}.png"
            alt="Seguimiento actual de {afp}">
        </article>
        """
        for afp in AFPS
        if (
            carpeta_graficos
            / f"seguimiento_actual_{afp.lower()}.png"
        ).exists()
    )

    carpeta_historicos = (
        processed
        / "graficos_modelo79a"
    )

    graficos_historicos = "".join(
        f"""
        <article class="grafico-card">
          <h3>{afp}</h3>
          <img
            src="graficos_modelo79a/01_real_vs_estimada_{afp.lower()}.png"
            alt="Prueba histórica de {afp}">
        </article>
        """
        for afp in AFPS
        if (
            carpeta_historicos
            / f"01_real_vs_estimada_{afp.lower()}.png"
        ).exists()
    )

    aviso_incompletos = ""

    if not incompletos.empty:
        fechas = sorted(
            {
                formato_fecha(x)
                for x in incompletos[
                    "fecha_objetivo"
                ]
            }
        )

        aviso_incompletos = f"""
        <div class="aviso cobertura">
          Se ocultaron {len(incompletos)} estimaciones
          incompletas correspondientes a
          {html.escape(", ".join(fechas))}.
          Tenían menos de {COBERTURA_MINIMA:.0f}% de los
          indicadores disponibles y no se consideran
          pronósticos válidos.
        </div>
        """

    ruta = (
        processed
        / "ca0001_modelo80_dashboard.html"
    )

    contenido = f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta http-equiv="refresh" content="300">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Monitor AFP Fondo 3</title>
<style>
:root {{
  --fondo: #f3f6fb;
  --azul: #123e73;
  --azul2: #2563a6;
  --texto: #1e293b;
  --suave: #64748b;
  --borde: #dbe3ef;
  --blanco: #ffffff;
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0;
  background: var(--fondo);
  color: var(--texto);
  font-family: Arial, Helvetica, sans-serif;
}}
.contenedor {{
  width: min(1500px, 96%);
  margin: 0 auto;
  padding: 24px 0 50px;
}}
.encabezado {{
  background: linear-gradient(135deg, var(--azul), var(--azul2));
  color: white;
  padding: 24px 28px;
  border-radius: 16px;
  margin-bottom: 18px;
}}
.encabezado h1 {{
  margin: 0 0 8px;
  font-size: 30px;
}}
.encabezado p {{
  margin: 4px 0;
}}
.botones {{
  margin-top: 15px;
}}
.boton {{
  display: inline-block;
  border: 0;
  border-radius: 9px;
  padding: 10px 16px;
  margin-right: 8px;
  cursor: pointer;
  font-weight: bold;
  background: white;
  color: var(--azul);
}}
.aviso {{
  background: #fff7d6;
  border-left: 6px solid #d8a500;
  padding: 13px 16px;
  margin: 14px 0;
  border-radius: 8px;
}}
.cobertura {{
  background: #fff1f1;
  border-left-color: #c24141;
}}
.seccion {{
  background: var(--blanco);
  border: 1px solid var(--borde);
  border-radius: 15px;
  padding: 20px;
  margin: 18px 0;
  box-shadow: 0 4px 14px rgba(21, 45, 78, .06);
}}
.seccion h2 {{
  color: var(--azul);
  margin-top: 0;
}}
.afp-grid {{
  display: grid;
  grid-template-columns: repeat(4, minmax(220px, 1fr));
  gap: 14px;
}}
.afp-card {{
  border: 1px solid var(--borde);
  border-radius: 13px;
  padding: 16px;
  background: #fbfdff;
}}
.afp-title {{
  color: var(--azul);
  font-size: 21px;
  font-weight: bold;
  margin-bottom: 13px;
}}
.datos-grid {{
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 9px;
}}
.etiqueta {{
  color: var(--suave);
  display: block;
  font-size: 12px;
  margin-bottom: 4px;
}}
.datos-grid strong {{
  display: block;
  font-size: 18px;
}}
.datos-grid small {{
  color: var(--suave);
}}
.estado {{
  display: inline-block;
  margin-top: 14px;
  border-radius: 20px;
  padding: 7px 11px;
  font-weight: bold;
  font-size: 13px;
}}
.sube {{
  background: #e6f6ec;
  color: #176437;
}}
.baja {{
  background: #fdeaea;
  color: #a22626;
}}
.evaluado {{
  background: #e8f1ff;
  color: #205b9b;
}}
.neutral {{
  background: #eef1f5;
  color: #566170;
}}
.estado-texto {{
  margin: 10px 0 3px;
}}
.detalle {{
  color: var(--suave);
  margin: 0;
  font-size: 13px;
}}
.graficos-grid {{
  display: grid;
  grid-template-columns: repeat(2, minmax(320px, 1fr));
  gap: 18px;
}}
.grafico-card {{
  border: 1px solid var(--borde);
  border-radius: 12px;
  padding: 12px;
  background: white;
}}
.grafico-card h3 {{
  color: var(--azul);
  margin: 5px 5px 10px;
}}
.grafico-card img {{
  display: block;
  width: 100%;
  height: auto;
}}
.tabla-contenedor {{
  overflow-x: auto;
}}
.tabla {{
  border-collapse: collapse;
  width: 100%;
  min-width: 780px;
}}
.tabla th {{
  background: #eaf1fa;
  color: var(--azul);
  position: sticky;
  top: 0;
}}
.tabla th, .tabla td {{
  border-bottom: 1px solid var(--borde);
  padding: 9px 10px;
  text-align: right;
  white-space: nowrap;
}}
.tabla th:first-child, .tabla td:first-child {{
  text-align: left;
}}
.mensaje {{
  color: var(--suave);
}}
details summary {{
  cursor: pointer;
  color: var(--azul);
  font-weight: bold;
  padding: 6px 0;
}}
.explicacion {{
  line-height: 1.55;
}}
@media (max-width: 1000px) {{
  .afp-grid {{ grid-template-columns: repeat(2, 1fr); }}
}}
@media (max-width: 700px) {{
  .afp-grid, .graficos-grid {{
    grid-template-columns: 1fr;
  }}
  .contenedor {{ width: 95%; }}
}}
</style>
</head>
<body>
<main class="contenedor">
  <header class="encabezado">
    <h1>Monitor prospectivo AFP Fondo 3</h1>
    <p>
      <strong>Última cuota SBS detectada:</strong>
      {formato_fecha(ultima_fecha_sbs)}
    </p>
    <p>
      <strong>Tablero actualizado:</strong>
      {datetime.now().strftime("%d/%m/%Y %H:%M:%S")}
    </p>
    <div class="botones">
      <button class="boton" onclick="location.reload()">
        Actualizar vista
      </button>
      <button class="boton"
        onclick="document.getElementById('graficos-actuales').scrollIntoView({{behavior:'smooth'}})">
        Ver gráficos actuales
      </button>
    </div>
  </header>

  <div class="aviso">
    La cuota estimada es una aproximación estadística.
    La cuota oficial es la publicada por la SBS.
    El botón «Actualizar vista» recarga el tablero;
    el cálculo nuevo se realiza automáticamente por Windows
    o al usar el acceso directo «Actualizar Monitor AFP».
  </div>

  {aviso_incompletos}

  <section class="seccion">
    <h2>Resumen actual por AFP</h2>
    <div class="afp-grid">
      {tarjetas}
    </div>
  </section>

  <section class="seccion" id="graficos-actuales">
    <h2>Cómo va el modelo ahora</h2>
    <p class="mensaje">
      La línea continua es la cuota oficial SBS.
      La línea discontinua muestra los pronósticos congelados
      que todavía deben ser confirmados.
    </p>
    <div class="graficos-grid">
      {graficos_actuales or "<p class='mensaje'>No existen gráficos actuales.</p>"}
    </div>
  </section>

  <section class="seccion">
    <h2>Pronósticos válidos pendientes de SBS</h2>
    <div class="tabla-contenedor">
      {tabla_pendientes_html(pendientes)}
    </div>
  </section>

  <section class="seccion">
    <h2>Pronóstico frente a resultado oficial</h2>
    <div class="tabla-contenedor">
      {tabla_evaluados_html(evaluados)}
    </div>
  </section>

  <section class="seccion">
    <h2>Resultados prospectivos acumulados</h2>
    <div class="tabla-contenedor">
      {tabla_metricas_html(metricas)}
    </div>
  </section>

  <section class="seccion">
    <details open>
      <summary>
        Ver prueba histórica del modelo
      </summary>
      <p class="mensaje">
        Estos gráficos corresponden al último 20% reservado
        para prueba. Azul: cuota real SBS. Naranja: cuota
        estimada por el modelo.
      </p>
      <div class="graficos-grid">
        {graficos_historicos or "<p class='mensaje'>Ejecuta el módulo 79A para generar los gráficos históricos.</p>"}
      </div>
    </details>
  </section>

  <section class="seccion explicacion">
    <h2>Cómo interpretar el tablero</h2>
    <p>
      <strong>Cuota estimada:</strong> resultado producido antes
      de conocer la publicación SBS.
    </p>
    <p>
      <strong>Cobertura:</strong> porcentaje de indicadores que
      estuvieron disponibles. No es una probabilidad de acierto.
    </p>
    <p>
      <strong>Desviación:</strong> cuota estimada menos cuota real.
      Un valor positivo indica que el modelo estimó por encima.
    </p>
    <p>
      <strong>Error medio:</strong> diferencia porcentual promedio
      de los pronósticos ya evaluados.
    </p>
  </section>
</main>
</body>
</html>
"""

    ruta.write_text(
        contenido,
        encoding="utf-8",
    )

    return ruta


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Actualiza el monitor y crea un tablero visual amigable."
        )
    )

    parser.add_argument(
        "--pronosticar",
        action="store_true",
        help="Genera pronósticos nuevos antes de construir el tablero.",
    )

    parser.add_argument(
        "--abrir",
        action="store_true",
        help="Abre el tablero al terminar.",
    )

    parser.add_argument(
        "--sin-ejecutar-monitor",
        action="store_true",
        help="Solo reconstruye el tablero con los archivos existentes.",
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

    processed.mkdir(
        parents=True,
        exist_ok=True,
    )

    if not args.sin_ejecutar_monitor:
        codigo = ejecutar_modulo80(
            raiz,
            pronosticar=args.pronosticar,
        )

        if codigo != 0:
            raise RuntimeError(
                f"El módulo 80 terminó con código {codigo}."
            )

    datos = preparar_datos(
        processed
    )

    pendientes, evaluados, incompletos = (
        clasificar_pronosticos(
            datos["base"],
            datos["pronosticos"],
        )
    )

    # Para el gráfico se muestran todos los pronósticos válidos,
    # tanto pendientes como ya publicados.
    pronosticos_validos = pd.concat(
        [
            pendientes,
            evaluados,
        ],
        ignore_index=True,
    )

    carpeta_graficos = (
        processed
        / "graficos_monitor_amigable"
    )

    crear_graficos_actuales(
        datos["base"],
        pronosticos_validos,
        carpeta_graficos,
    )

    tablero = crear_dashboard_amigable(
        processed,
        datos,
        pendientes,
        evaluados,
        incompletos,
        carpeta_graficos,
    )

    print("\nMONITOR AMIGABLE ACTUALIZADO")
    print("=" * 90)
    print(f"Pronósticos pendientes válidos: {len(pendientes)}")
    print(f"Pronósticos ya evaluados: {len(evaluados)}")
    print(f"Estimaciones incompletas ocultadas: {len(incompletos)}")
    print(f"Tablero: {tablero.resolve()}")

    if args.abrir:
        webbrowser.open(
            tablero.resolve().as_uri()
        )


if __name__ == "__main__":
    main()
