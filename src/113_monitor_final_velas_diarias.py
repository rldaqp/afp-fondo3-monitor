from __future__ import annotations

import argparse
import json
import math
import re
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


AFPS = ["Habitat", "Integra", "Prima", "Profuturo"]
COBERTURA_MINIMA = 100.0
MAX_DIAS_GRAFICO = 90
ZONA_HORARIA = "America/Lima"

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


def leer_csv(ruta: Path, obligatorio: bool = False) -> pd.DataFrame:
    if not ruta.exists():
        if obligatorio:
            raise FileNotFoundError(f"Falta el archivo: {ruta}")
        return pd.DataFrame()

    ultimo_error: Exception | None = None
    for encoding in ("utf-8-sig", "latin-1", "utf-8"):
        try:
            return pd.read_csv(ruta, encoding=encoding)
        except Exception as exc:  # pragma: no cover - tolerancia de archivos locales
            ultimo_error = exc

    raise RuntimeError(f"No se pudo leer {ruta}: {ultimo_error}")


def escribir_csv(df: pd.DataFrame, ruta: Path) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(
        ruta,
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d %H:%M:%S",
    )


def normalizar_afp(valor: Any) -> str:
    texto = str(valor).strip().lower()
    mapa = {
        "habitat": "Habitat",
        "integra": "Integra",
        "prima": "Prima",
        "profuturo": "Profuturo",
    }
    return mapa.get(texto, str(valor).strip())


def parsear_run_id(valor: Any) -> pd.Timestamp:
    texto = str(valor).strip()
    patrones = [
        (r"^(\d{8})T(\d{6})Z$", "%Y%m%d%H%M%S"),
        (r"^(\d{8})_(\d{6})$", "%Y%m%d%H%M%S"),
        (r"^(\d{14})$", "%Y%m%d%H%M%S"),
    ]

    for patron, formato in patrones:
        m = re.match(patron, texto)
        if not m:
            continue
        compacto = "".join(m.groups())
        try:
            marca = pd.Timestamp(datetime.strptime(compacto, formato))
            # Los run_id del módulo 79 están en UTC.
            if texto.endswith("Z"):
                return (
                    marca.tz_localize("UTC")
                    .tz_convert(ZONA_HORARIA)
                    .tz_localize(None)
                )
            return marca
        except ValueError:
            pass

    marca = pd.to_datetime(texto, errors="coerce", utc=True)
    if pd.isna(marca):
        return pd.NaT

    try:
        return marca.tz_convert(ZONA_HORARIA).tz_localize(None)
    except Exception:
        return pd.Timestamp(marca).tz_localize(None)


def cargar_oficial(processed: Path) -> pd.DataFrame:
    candidatos = [
        processed / "ca0001_modelo80_sbs_oficial_detectado.csv",
        processed / "ca0001_modelo56_base_alineada.csv",
    ]

    partes: list[pd.DataFrame] = []
    for ruta in candidatos:
        df = leer_csv(ruta)
        if df.empty:
            continue

        fecha_col = None
        cuota_col = None
        for nombre in ("fecha_cuota", "fecha", "fecha_objetivo"):
            if nombre in df.columns:
                fecha_col = nombre
                break
        for nombre in ("cuota_sbs", "cuota", "valor_cuota"):
            if nombre in df.columns:
                cuota_col = nombre
                break

        if fecha_col is None or cuota_col is None or "afp" not in df.columns:
            continue

        x = df[["afp", fecha_col, cuota_col]].copy()
        x.columns = ["afp", "fecha", "cuota_oficial"]
        x["afp"] = x["afp"].map(normalizar_afp)
        x["fecha"] = pd.to_datetime(x["fecha"], errors="coerce").dt.normalize()
        x["cuota_oficial"] = pd.to_numeric(x["cuota_oficial"], errors="coerce")
        x = x.dropna(subset=["afp", "fecha", "cuota_oficial"])
        partes.append(x)

    if not partes:
        raise FileNotFoundError(
            "No se encontró una base oficial SBS utilizable en data\\processed."
        )

    return (
        pd.concat(partes, ignore_index=True)
        .drop_duplicates(subset=["afp", "fecha"], keep="first")
        .sort_values(["afp", "fecha"])
        .reset_index(drop=True)
    )


def cargar_snapshots_intradia(processed: Path) -> pd.DataFrame:
    ruta = processed / "ca0001_modelo99_historial_intradia_cuota.csv"
    df = leer_csv(ruta)
    if df.empty:
        return pd.DataFrame(
            columns=[
                "afp",
                "fecha_objetivo",
                "timestamp",
                "cuota_estimada",
                "cobertura_pct",
                "fuente",
            ]
        )

    requeridas = {"afp", "timestamp", "cuota_estimada_intradia"}
    if not requeridas.issubset(df.columns):
        return pd.DataFrame()

    x = pd.DataFrame()
    x["afp"] = df["afp"].map(normalizar_afp)
    x["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")

    if "fecha_objetivo" in df.columns:
        x["fecha_objetivo"] = pd.to_datetime(
            df["fecha_objetivo"], errors="coerce"
        ).dt.normalize()
    else:
        x["fecha_objetivo"] = x["timestamp"].dt.normalize()

    x["cuota_estimada"] = pd.to_numeric(
        df["cuota_estimada_intradia"], errors="coerce"
    )
    x["cobertura_pct"] = pd.to_numeric(
        df.get("cobertura_pct", COBERTURA_MINIMA), errors="coerce"
    ).fillna(0.0)
    x["fuente"] = "INTRADIA_5_MIN"

    return (
        x.dropna(subset=["afp", "fecha_objetivo", "timestamp", "cuota_estimada"])
        .loc[lambda z: z["cobertura_pct"].ge(COBERTURA_MINIMA)]
        .sort_values(["afp", "timestamp"])
        .drop_duplicates(subset=["afp", "timestamp"], keep="last")
        .reset_index(drop=True)
    )


def cargar_ejecuciones_modelo(processed: Path) -> pd.DataFrame:
    ruta = processed / "ca0001_modelo79_bitacora_todas_ejecuciones.csv"
    df = leer_csv(ruta)
    if df.empty:
        return pd.DataFrame()

    requeridas = {"afp", "fecha_objetivo", "cuota_estimada"}
    if not requeridas.issubset(df.columns):
        return pd.DataFrame()

    x = pd.DataFrame()
    x["afp"] = df["afp"].map(normalizar_afp)
    x["fecha_objetivo"] = pd.to_datetime(
        df["fecha_objetivo"], errors="coerce"
    ).dt.normalize()
    x["cuota_estimada"] = pd.to_numeric(df["cuota_estimada"], errors="coerce")
    x["cobertura_pct"] = pd.to_numeric(
        df.get("cobertura_factores_pct", COBERTURA_MINIMA), errors="coerce"
    ).fillna(0.0)

    if "run_id" in df.columns:
        x["timestamp"] = df["run_id"].map(parsear_run_id)
    else:
        x["timestamp"] = pd.NaT

    # Si no se pudo recuperar hora, se coloca mediodía solamente para ordenar.
    mascara = x["timestamp"].isna() & x["fecha_objetivo"].notna()
    x.loc[mascara, "timestamp"] = (
        x.loc[mascara, "fecha_objetivo"] + pd.Timedelta(hours=12)
    )
    x["fuente"] = "EJECUCION_MODELO79"

    return (
        x.dropna(subset=["afp", "fecha_objetivo", "timestamp", "cuota_estimada"])
        .loc[lambda z: z["cobertura_pct"].ge(COBERTURA_MINIMA)]
        .sort_values(["afp", "timestamp"])
        .drop_duplicates(
            subset=["afp", "fecha_objetivo", "timestamp", "cuota_estimada"],
            keep="last",
        )
        .reset_index(drop=True)
    )


def cargar_snapshot_vigente(processed: Path) -> pd.DataFrame:
    ruta = processed / "ca0001_modelo79_snapshot_estimacion_actual.csv"
    df = leer_csv(ruta)
    if df.empty:
        return pd.DataFrame()

    requeridas = {"afp", "fecha_estimada", "cuota_estimada"}
    if not requeridas.issubset(df.columns):
        return pd.DataFrame()

    x = pd.DataFrame()
    x["afp"] = df["afp"].map(normalizar_afp)
    x["fecha_objetivo"] = pd.to_datetime(
        df["fecha_estimada"], errors="coerce"
    ).dt.normalize()
    x["cuota_estimada"] = pd.to_numeric(df["cuota_estimada"], errors="coerce")
    x["cobertura_pct"] = pd.to_numeric(
        df.get("cobertura_factores_pct", COBERTURA_MINIMA), errors="coerce"
    ).fillna(0.0)

    if "run_id" in df.columns:
        x["timestamp"] = df["run_id"].map(parsear_run_id)
    else:
        x["timestamp"] = pd.Timestamp.now(tz=ZONA_HORARIA).tz_localize(None)

    x["fuente"] = "SNAPSHOT_VIGENTE"

    return (
        x.dropna(subset=["afp", "fecha_objetivo", "timestamp", "cuota_estimada"])
        .loc[lambda z: z["cobertura_pct"].ge(COBERTURA_MINIMA)]
        .reset_index(drop=True)
    )


def cargar_metricas(processed: Path) -> dict[str, dict[str, float]]:
    salida = {
        afp: {
            "mape": MAPE_RESPALDO[afp],
            "direccion": DIRECCION_RESPALDO[afp],
        }
        for afp in AFPS
    }

    ruta = processed / "ca0001_modelo79a_correlaciones_finales.csv"
    df = leer_csv(ruta)
    if df.empty or "afp" not in df.columns:
        return salida

    for _, fila in df.iterrows():
        afp = normalizar_afp(fila["afp"])
        if afp not in salida:
            continue

        mape = pd.to_numeric(fila.get("mape_cuota_pct", np.nan), errors="coerce")
        direccion = pd.to_numeric(
            fila.get("direccion_acumulada_pct", np.nan), errors="coerce"
        )
        if pd.notna(mape):
            salida[afp]["mape"] = float(mape)
        if pd.notna(direccion):
            salida[afp]["direccion"] = float(direccion)

    return salida


def consolidar_estimaciones(processed: Path) -> pd.DataFrame:
    partes = [
        cargar_snapshots_intradia(processed),
        cargar_ejecuciones_modelo(processed),
        cargar_snapshot_vigente(processed),
    ]
    partes = [x for x in partes if not x.empty]

    if not partes:
        return pd.DataFrame(
            columns=[
                "afp",
                "fecha_objetivo",
                "timestamp",
                "cuota_estimada",
                "cobertura_pct",
                "fuente",
            ]
        )

    x = pd.concat(partes, ignore_index=True)
    x["timestamp"] = pd.to_datetime(x["timestamp"], errors="coerce")
    x["fecha_objetivo"] = pd.to_datetime(
        x["fecha_objetivo"], errors="coerce"
    ).dt.normalize()
    x["cuota_estimada"] = pd.to_numeric(x["cuota_estimada"], errors="coerce")
    x["cobertura_pct"] = pd.to_numeric(x["cobertura_pct"], errors="coerce")

    # Prioridad: intradía real > snapshot vigente > ejecución diaria.
    prioridad = {
        "EJECUCION_MODELO79": 1,
        "SNAPSHOT_VIGENTE": 2,
        "INTRADIA_5_MIN": 3,
    }
    x["prioridad"] = x["fuente"].map(prioridad).fillna(0)

    return (
        x.dropna(subset=["afp", "fecha_objetivo", "timestamp", "cuota_estimada"])
        .sort_values(["afp", "fecha_objetivo", "timestamp", "prioridad"])
        .drop_duplicates(
            subset=["afp", "fecha_objetivo", "timestamp"], keep="last"
        )
        .sort_values(["afp", "timestamp"])
        .reset_index(drop=True)
    )


def construir_velas_diarias(estimaciones: pd.DataFrame) -> pd.DataFrame:
    if estimaciones.empty:
        return pd.DataFrame(
            columns=[
                "afp",
                "fecha",
                "open",
                "high",
                "low",
                "close",
                "n_estimaciones",
                "primera_hora",
                "ultima_hora",
                "estado",
                "fuentes",
            ]
        )

    filas: list[dict[str, Any]] = []
    for (afp, fecha), grupo in estimaciones.groupby(["afp", "fecha_objetivo"]):
        grupo = grupo.sort_values(["timestamp", "prioridad"])
        valores = grupo["cuota_estimada"].dropna()
        if valores.empty:
            continue

        # Con una observación se conserva como vela provisional sin mecha.
        # A partir de dos observaciones ya existe OHLC intradía informativo.
        open_ = float(valores.iloc[0])
        high = float(valores.max())
        low = float(valores.min())
        close = float(valores.iloc[-1])
        n = int(len(valores))

        ultima_ts = pd.Timestamp(grupo["timestamp"].iloc[-1])
        hoy = pd.Timestamp.now(tz=ZONA_HORARIA).tz_localize(None).normalize()
        estado = "EN_FORMACION" if pd.Timestamp(fecha).normalize() >= hoy else "CERRADA"

        filas.append(
            {
                "afp": afp,
                "fecha": pd.Timestamp(fecha).normalize(),
                "open": open_,
                "high": max(high, open_, close),
                "low": min(low, open_, close),
                "close": close,
                "n_estimaciones": n,
                "primera_hora": pd.Timestamp(grupo["timestamp"].iloc[0]),
                "ultima_hora": ultima_ts,
                "estado": estado,
                "fuentes": " | ".join(sorted(set(grupo["fuente"].astype(str)))),
            }
        )

    return pd.DataFrame(filas).sort_values(["afp", "fecha"]).reset_index(drop=True)


def preparar_payload(
    oficial: pd.DataFrame,
    velas: pd.DataFrame,
    metricas: dict[str, dict[str, float]],
) -> dict[str, Any]:
    payload: dict[str, Any] = {"afps": {}, "actualizado": datetime.now().isoformat()}

    for afp in AFPS:
        o = oficial[oficial["afp"].eq(afp)].sort_values("fecha")
        v = velas[velas["afp"].eq(afp)].sort_values("fecha")

        o_reciente = o.tail(500)
        v_reciente = v.tail(MAX_DIAS_GRAFICO)

        ultimo_oficial = None
        if not o.empty:
            fila = o.iloc[-1]
            ultimo_oficial = {
                "fecha": pd.Timestamp(fila["fecha"]).strftime("%Y-%m-%d"),
                "cuota": float(fila["cuota_oficial"]),
            }

        ultima_vela = None
        if not v.empty:
            fila = v.iloc[-1]
            ultima_vela = {
                "fecha": pd.Timestamp(fila["fecha"]).strftime("%Y-%m-%d"),
                "open": float(fila["open"]),
                "high": float(fila["high"]),
                "low": float(fila["low"]),
                "close": float(fila["close"]),
                "n_estimaciones": int(fila["n_estimaciones"]),
                "estado": str(fila["estado"]),
                "ultima_hora": pd.Timestamp(fila["ultima_hora"]).strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
                "fuentes": str(fila["fuentes"]),
            }

        payload["afps"][afp] = {
            "oficial": [
                {
                    "fecha": pd.Timestamp(f).strftime("%Y-%m-%d"),
                    "cuota": float(q),
                }
                for f, q in zip(o_reciente["fecha"], o_reciente["cuota_oficial"])
            ],
            "velas": [
                {
                    "fecha": pd.Timestamp(fila["fecha"]).strftime("%Y-%m-%d"),
                    "open": float(fila["open"]),
                    "high": float(fila["high"]),
                    "low": float(fila["low"]),
                    "close": float(fila["close"]),
                    "n_estimaciones": int(fila["n_estimaciones"]),
                    "estado": str(fila["estado"]),
                    "primera_hora": pd.Timestamp(fila["primera_hora"]).strftime(
                        "%H:%M"
                    ),
                    "ultima_hora": pd.Timestamp(fila["ultima_hora"]).strftime(
                        "%H:%M"
                    ),
                    "fuentes": str(fila["fuentes"]),
                }
                for _, fila in v_reciente.iterrows()
            ],
            "ultimo_oficial": ultimo_oficial,
            "ultima_vela": ultima_vela,
            "mape": float(metricas[afp]["mape"]),
            "direccion": float(metricas[afp]["direccion"]),
            "n_velas": int(len(v)),
            "primera_vela": (
                pd.Timestamp(v["fecha"].min()).strftime("%Y-%m-%d")
                if not v.empty
                else None
            ),
        }

    return payload


def crear_html(processed: Path, payload: dict[str, Any]) -> Path:
    ruta = processed / "ca0001_monitor_final_velas_diarias.html"
    datos_json = json.dumps(payload, ensure_ascii=False)

    documento = f'''<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="300">
<title>Monitor AFP Fondo 3 — velas sintéticas diarias</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
:root {{
  --azul:#123f73;
  --azul2:#2b6fb4;
  --fondo:#f3f6fb;
  --borde:#d7e2ef;
  --texto:#1f2937;
  --suave:#64748b;
  --morado:#6f2dbd;
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
  padding:22px 0 50px;
}}
header {{
  background:linear-gradient(135deg,var(--azul),var(--azul2));
  color:white;
  border-radius:16px;
  padding:24px 28px;
}}
header h1 {{ margin:0 0 8px; }}
.nav {{
  display:flex;
  flex-wrap:wrap;
  gap:8px;
  margin-top:14px;
}}
.nav a,.nav button {{
  border:0;
  background:white;
  color:var(--azul);
  text-decoration:none;
  padding:10px 15px;
  border-radius:9px;
  font-weight:bold;
  cursor:pointer;
}}
.aviso {{
  margin:16px 0;
  padding:14px 16px;
  border-left:6px solid #d7a400;
  background:#fff7d6;
  border-radius:10px;
  line-height:1.55;
}}
.tabs {{
  display:flex;
  flex-wrap:wrap;
  gap:8px;
  margin:16px 0;
}}
.tabs button {{
  border:1px solid var(--borde);
  background:white;
  color:var(--azul);
  padding:10px 15px;
  border-radius:9px;
  font-weight:bold;
  cursor:pointer;
}}
.tabs button.activo {{
  background:var(--azul);
  color:white;
}}
.resumen {{
  display:grid;
  grid-template-columns:repeat(6,minmax(145px,1fr));
  gap:11px;
  margin-bottom:15px;
}}
.card {{
  background:white;
  border:1px solid var(--borde);
  border-radius:12px;
  padding:13px;
}}
.card span {{
  display:block;
  color:var(--suave);
  font-size:12px;
  margin-bottom:5px;
}}
.card strong {{
  display:block;
  color:var(--azul);
  font-size:18px;
}}
.panel {{
  background:white;
  border:1px solid var(--borde);
  border-radius:15px;
  padding:10px;
}}
.detalle {{
  display:grid;
  grid-template-columns:1.35fr 1fr;
  gap:14px;
  margin-top:14px;
}}
.caja {{
  background:white;
  border:1px solid var(--borde);
  border-radius:12px;
  padding:15px;
  line-height:1.55;
}}
table {{ width:100%; border-collapse:collapse; }}
td {{ padding:8px 5px; border-bottom:1px solid #edf2f7; }}
td:last-child {{ text-align:right; font-weight:bold; }}
.estado-formacion {{ color:#9a5a00 !important; }}
.estado-cerrada {{ color:#176437 !important; }}
.sin-datos {{
  background:#eef5ff;
  border-left:6px solid var(--azul2);
  padding:18px;
  border-radius:10px;
  margin:15px;
  line-height:1.55;
}}
@media(max-width:1050px) {{
  .resumen {{ grid-template-columns:repeat(3,1fr); }}
}}
@media(max-width:800px) {{
  .resumen {{ grid-template-columns:repeat(2,1fr); }}
  .detalle {{ grid-template-columns:1fr; }}
}}
</style>
</head>
<body>
<main>
<header>
  <h1>Monitor final — velas sintéticas diarias del valor cuota</h1>
  <p>
    Una vela por cada jornada registrada. La línea azul es el valor cuota real SBS;
    el cierre de cada vela es el pronóstico sintético de esa fecha.
  </p>
  <div class="nav">
    <a href="ca0001_monitor_final_velas_diarias.html">Monitor y velas</a>
    <a href="ca0001_modelo92_indicadores_didacticos.html">Indicadores</a>
    <a href="ca0001_modelo97_simulador_monto_fondo3.html">Simulador</a>
    <button onclick="location.reload()">Actualizar vista</button>
  </div>
</header>

<div class="aviso">
  <strong>Regla exacta:</strong>
  apertura = primera estimación válida del día; máximo = mayor estimación;
  mínimo = menor estimación; cierre = última estimación válida. Por construcción,
  el cierre de la vela coincide con el pronóstico vigente mostrado por el monitor.
  Cuando la SBS publica, la línea azul permite medir la diferencia real sin modificar la vela.
  Las velas anteriores solo existen para fechas en las que el sistema conservó ejecuciones
  o estimaciones intradía; no se inventan OHLC históricos.
</div>

<div id="tabs" class="tabs"></div>
<section id="resumen" class="resumen"></section>
<section class="panel">
  <div id="grafico" style="height:670px;"></div>
</section>
<section class="detalle">
  <div class="caja">
    <h3>Qué muestra este gráfico</h3>
    <p>
      <strong>Velas verdes y rojas:</strong> recorrido diario del valor cuota sintético.
      <strong>Línea azul:</strong> cuota oficial SBS.
      <strong>Línea naranja discontinua:</strong> cierre sintético de cada vela, es decir,
      el pronóstico diario del modelo.
      <strong>Rombo morado:</strong> último pronóstico disponible.
    </p>
    <p id="coberturaHistorica"></p>
  </div>
  <div class="caja">
    <h3 id="tituloDetalle">Detalle de la vela</h3>
    <table id="detalleVela"></table>
  </div>
</section>
</main>
<script>
const datos = {datos_json};
let afpActual = "Habitat";

function fmt(v, d=6) {{
  if (v === null || v === undefined || Number.isNaN(Number(v))) return "—";
  return new Intl.NumberFormat("es-PE", {{
    minimumFractionDigits:d,
    maximumFractionDigits:d
  }}).format(Number(v));
}}

function fechaBonita(v) {{
  if (!v) return "—";
  const p = v.substring(0,10).split("-");
  return `${{p[2]}}/${{p[1]}}/${{p[0]}}`;
}}

function crearTabs() {{
  const cont = document.getElementById("tabs");
  Object.keys(datos.afps).forEach(nombre => {{
    const b = document.createElement("button");
    b.textContent = nombre;
    b.dataset.afp = nombre;
    b.onclick = () => {{
      afpActual = nombre;
      render();
    }};
    cont.appendChild(b);
  }});
}}

function mostrarDetalle(vela, oficialMap) {{
  if (!vela) {{
    document.getElementById("tituloDetalle").textContent = "Detalle de la vela";
    document.getElementById("detalleVela").innerHTML = `
      <tr><td colspan="2">Aún no hay velas sintéticas guardadas.</td></tr>
    `;
    return;
  }}

  const real = oficialMap.get(vela.fecha);
  const error = real === undefined ? null : real - vela.close;

  document.getElementById("tituloDetalle").textContent =
    `Vela del ${{fechaBonita(vela.fecha)}}`;

  document.getElementById("detalleVela").innerHTML = `
    <tr><td>Apertura sintética</td><td>${{fmt(vela.open)}}</td></tr>
    <tr><td>Máximo sintético</td><td>${{fmt(vela.high)}}</td></tr>
    <tr><td>Mínimo sintético</td><td>${{fmt(vela.low)}}</td></tr>
    <tr><td>Cierre / pronóstico</td><td>${{fmt(vela.close)}}</td></tr>
    <tr><td>Cuota real SBS</td><td>${{real === undefined ? "Pendiente" : fmt(real)}}</td></tr>
    <tr><td>Error real - estimado</td><td>${{error === null ? "Pendiente" : (error >= 0 ? "+" : "") + fmt(error)}}</td></tr>
    <tr><td>Estimaciones utilizadas</td><td>${{vela.n_estimaciones}}</td></tr>
    <tr><td>Primera / última hora</td><td>${{vela.primera_hora}} — ${{vela.ultima_hora}}</td></tr>
    <tr><td>Estado</td><td>${{vela.estado}}</td></tr>
  `;
}}

function renderResumen(d) {{
  const oficial = d.ultimo_oficial;
  const vela = d.ultima_vela;
  const diferencia = (oficial && vela)
    ? (vela.close / oficial.cuota - 1) * 100
    : null;

  const estadoClase = vela && vela.estado === "EN_FORMACION"
    ? "estado-formacion"
    : "estado-cerrada";

  document.getElementById("resumen").innerHTML = `
    <div class="card"><span>AFP</span><strong>${{afpActual}}</strong></div>
    <div class="card"><span>Última cuota oficial SBS</span><strong>${{oficial ? fmt(oficial.cuota) : "—"}}</strong></div>
    <div class="card"><span>Pronóstico / cierre sintético</span><strong>${{vela ? fmt(vela.close) : "—"}}</strong></div>
    <div class="card"><span>Variación frente a última oficial</span><strong>${{diferencia === null ? "—" : (diferencia >= 0 ? "+" : "") + diferencia.toFixed(3) + "%"}}</strong></div>
    <div class="card"><span>Error medio histórico</span><strong>±${{d.mape.toFixed(3)}}%</strong></div>
    <div class="card"><span>Estado de la última vela</span><strong class="${{estadoClase}}">${{vela ? vela.estado.replace("_"," ") : "SIN DATOS"}}</strong></div>
  `;

  document.getElementById("coberturaHistorica").innerHTML = d.n_velas > 0
    ? `<strong>Histórico sintético guardado:</strong> ${{d.n_velas}} días, desde ${{fechaBonita(d.primera_vela)}}. Las fechas anteriores permanecen solamente como línea oficial porque no existen observaciones intradía guardadas.`
    : `<strong>Aún no hay velas sintéticas:</strong> comenzarán a acumularse cuando el recolector guarde estimaciones durante una sesión válida.`;
}}

function renderGrafico(d) {{
  const velas = d.velas;
  const oficial = d.oficial;
  const oficialMap = new Map(oficial.map(x => [x.fecha, x.cuota]));

  if (velas.length === 0) {{
    Plotly.purge("grafico");
    document.getElementById("grafico").innerHTML = `
      <div class="sin-datos">
        No existen todavía observaciones suficientes para formar velas sintéticas diarias.
        La línea oficial seguirá disponible cuando comience la recolección.
      </div>
    `;
    mostrarDetalle(null, oficialMap);
    return;
  }}

  const fechasVelas = velas.map(v => v.fecha);
  const cierres = velas.map(v => v.close);
  const ultima = velas[velas.length - 1];

  const trazas = [
    {{
      type:"candlestick",
      x:fechasVelas,
      open:velas.map(v => v.open),
      high:velas.map(v => v.high),
      low:velas.map(v => v.low),
      close:cierres,
      name:"Velas sintéticas diarias",
      increasing:{{
        line:{{color:"#0a7f3f",width:2}},
        fillcolor:"#45c676"
      }},
      decreasing:{{
        line:{{color:"#b11f32",width:2}},
        fillcolor:"#ef4257"
      }},
      whiskerwidth:0.9,
      customdata:velas.map(v => [
        v.n_estimaciones,
        v.estado,
        oficialMap.has(v.fecha) ? oficialMap.get(v.fecha) : null
      ]),
      hovertemplate:
        "<b>%{{x}}</b><br>"+
        "Apertura: %{{open:.6f}}<br>"+
        "Máximo: %{{high:.6f}}<br>"+
        "Mínimo: %{{low:.6f}}<br>"+
        "Cierre / pronóstico: %{{close:.6f}}<br>"+
        "Estimaciones: %{{customdata[0]}}<br>"+
        "Estado: %{{customdata[1]}}<br>"+
        "Cuota SBS: %{{customdata[2]:.6f}}"+
        "<extra></extra>"
    }},
    {{
      type:"scatter",
      mode:"lines+markers",
      x:oficial.map(v => v.fecha),
      y:oficial.map(v => v.cuota),
      name:"Cuota oficial SBS",
      line:{{color:"#225f9d",width:2.7}},
      marker:{{size:5}},
      hovertemplate:
        "<b>Cuota oficial SBS</b><br>%{{x}}<br>%{{y:.6f}}<extra></extra>"
    }},
    {{
      type:"scatter",
      mode:"lines+markers",
      x:fechasVelas,
      y:cierres,
      name:"Cierre sintético / pronóstico",
      line:{{color:"#ef6c3e",width:2.2,dash:"dash"}},
      marker:{{size:5,color:"#ef6c3e"}},
      hovertemplate:
        "<b>Cierre sintético</b><br>%{{x}}<br>%{{y:.6f}}<extra></extra>"
    }},
    {{
      type:"scatter",
      mode:"markers+text",
      x:[ultima.fecha],
      y:[ultima.close],
      text:[`Pronóstico ${{fmt(ultima.close)}}`],
      textposition:"middle right",
      marker:{{
        size:18,
        symbol:"diamond",
        color:"#6f2dbd",
        line:{{color:"white",width:2}}
      }},
      name:"Último pronóstico",
      hovertemplate:
        "<b>Último pronóstico</b><br>%{{x}}<br>%{{y:.6f}}<extra></extra>"
    }}
  ];

  const y = velas.flatMap(v => [v.high,v.low])
    .concat(oficial.map(v => v.cuota));
  const minY = Math.min(...y);
  const maxY = Math.max(...y);
  const margen = Math.max((maxY-minY)*0.10, Math.abs(maxY)*0.001);

  Plotly.react("grafico", trazas, {{
    title:{{
      text:`${{afpActual}}: velas sintéticas día a día + cuota real SBS`,
      x:0.02
    }},
    height:670,
    paper_bgcolor:"white",
    plot_bgcolor:"white",
    margin:{{l:70,r:155,t:85,b:75}},
    hovermode:"x unified",
    legend:{{orientation:"h",y:1.04,x:0}},
    xaxis:{{
      title:"Fecha",
      type:"date",
      rangeslider:{{visible:true,thickness:0.10}},
      rangeselector:{{
        buttons:[
          {{count:10,label:"10 días",step:"day",stepmode:"backward"}},
          {{count:30,label:"30 días",step:"day",stepmode:"backward"}},
          {{count:3,label:"3 meses",step:"month",stepmode:"backward"}},
          {{step:"all",label:"Todo"}}
        ]
      }},
      rangebreaks:[{{bounds:["sat","mon"]}}],
      showgrid:true,
      gridcolor:"#e7edf4"
    }},
    yaxis:{{
      title:"Valor cuota",
      range:[minY-margen,maxY+margen],
      fixedrange:false,
      showgrid:true,
      gridcolor:"#e7edf4"
    }},
    shapes:[{{
      type:"line",
      x0:ultima.fecha,
      x1:ultima.fecha,
      y0:minY-margen,
      y1:maxY+margen,
      line:{{color:"rgba(111,45,189,.30)",width:2,dash:"dot"}}
    }}]
  }}, {{
    responsive:true,
    scrollZoom:true,
    displaylogo:false,
    doubleClick:"reset"
  }});

  const grafico = document.getElementById("grafico");
  grafico.on("plotly_click", e => {{
    const fecha = String(e.points[0].x).substring(0,10);
    const vela = velas.find(v => v.fecha === fecha);
    if (vela) mostrarDetalle(vela, oficialMap);
  }});

  mostrarDetalle(ultima, oficialMap);
}}

function render() {{
  document.querySelectorAll("#tabs button").forEach(b => {{
    b.classList.toggle("activo",b.dataset.afp===afpActual);
  }});
  const d = datos.afps[afpActual];
  renderResumen(d);
  renderGrafico(d);
}}

crearTabs();
render();
</script>
</body>
</html>'''

    ruta.write_text(documento, encoding="utf-8")
    return ruta


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Genera el monitor final con una vela sintética por cada día."
    )
    parser.add_argument("--abrir", action="store_true")
    args = parser.parse_args()

    raiz = Path(__file__).resolve().parents[1]
    processed = raiz / "data" / "processed"
    processed.mkdir(parents=True, exist_ok=True)

    oficial = cargar_oficial(processed)
    estimaciones = consolidar_estimaciones(processed)
    velas = construir_velas_diarias(estimaciones)
    metricas = cargar_metricas(processed)

    escribir_csv(
        velas,
        processed / "ca0001_monitor_final_velas_diarias.csv",
    )

    payload = preparar_payload(oficial, velas, metricas)
    pagina = crear_html(processed, payload)

    print("\nMONITOR FINAL DE VELAS DIARIAS ACTUALIZADO")
    print("=" * 100)
    print(f"Observaciones estimadas consolidadas: {len(estimaciones)}")
    print(f"Velas sintéticas diarias: {len(velas)}")
    for afp in AFPS:
        n = int((velas["afp"].eq(afp)).sum()) if not velas.empty else 0
        print(f" - {afp}: {n} velas")
    print(f"Página: {pagina.resolve()}")

    if args.abrir:
        webbrowser.open(pagina.resolve().as_uri())


if __name__ == "__main__":
    main()
