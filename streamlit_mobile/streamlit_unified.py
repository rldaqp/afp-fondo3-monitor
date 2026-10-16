from __future__ import annotations

from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

HERE = Path(__file__).resolve().parent
CORE_SHA = "8a0c268c0b13676c6f67dd38a76ee2e50058c288"
CORE_URL = (
    "https://raw.githubusercontent.com/rldaqp/afp-fondo3-monitor/"
    f"{CORE_SHA}/streamlit_mobile/streamlit_app.py"
)
FALLBACK = HERE / "data" / "sbs_profuturo_f3_fallback.csv"
SBS_INDEX = (
    "https://www.sbs.gob.pe/app/stats_net/stats/"
    "EstadisticaSistemaFinancieroResultados.aspx?c=FP-1359"
)
LIMA = ZoneInfo("America/Lima")
NY = ZoneInfo("America/New_York")


def load_core() -> dict:
    response = requests.get(CORE_URL, timeout=45)
    response.raise_for_status()
    source = response.text
    marker = 'st.title("📈 Monitor diario Profuturo Fondo 3")'
    definitions = source.split(marker, 1)[0]
    if definitions == source:
        raise RuntimeError("No se pudo separar el núcleo OLS.")
    namespace = {
        "__name__": "afp_monitor_core",
        "__file__": str(HERE / "core_original.py"),
    }
    exec(compile(definitions, "core_original.py", "exec"), namespace)
    namespace["SBS_INDEX"] = SBS_INDEX
    return namespace


try:
    core = load_core()
except Exception as error:
    st.error("No se pudo cargar el núcleo OLS desde GitHub.")
    st.exception(error)
    st.stop()

WINDOW = int(core["WINDOW"])
THRESHOLD = float(core["THRESHOLD"])


def load_sbs_safe() -> tuple[pd.DataFrame, str]:
    online = pd.DataFrame()
    warning = ""
    try:
        online = core["load_sbs"]()
    except Exception as error:
        warning = f" La SBS no respondió: {type(error).__name__}."

    fallback = pd.read_csv(FALLBACK, encoding="utf-8-sig")
    for frame in (fallback, online):
        if not frame.empty:
            frame["fecha"] = pd.to_datetime(frame["fecha"], errors="coerce")
            frame["valor_cuota"] = pd.to_numeric(
                frame["valor_cuota"], errors="coerce"
            )
    frames = [fallback.dropna(subset=["fecha", "valor_cuota"])]
    if not online.empty:
        frames.append(online.dropna(subset=["fecha", "valor_cuota"]))
    result = (
        pd.concat(frames, ignore_index=True)
        .sort_values("fecha")
        .drop_duplicates("fecha", keep="last")
        .reset_index(drop=True)
    )
    source = "SBS en línea + respaldo" if len(frames) == 2 else "respaldo local"
    return result, source + warning


def market_mode(mode: str) -> tuple[bool, str, datetime, datetime]:
    now_lima = datetime.now(LIMA)
    now_ny = now_lima.astimezone(NY)
    open_now = (
        now_ny.weekday() < 5
        and time(9, 30) <= now_ny.time() < time(16, 10)
    )
    close_lima = now_ny.replace(
        hour=16, minute=0, second=0, microsecond=0
    ).astimezone(LIMA)
    if mode == "Ya salí":
        return False, "CIERRES DIARIOS", now_lima, close_lima
    return (
        (True, "INTRADÍA PROVISIONAL", now_lima, close_lima)
        if open_now
        else (False, "CIERRES DIARIOS", now_lima, close_lima)
    )


def first_on_or_after(frame: pd.DataFrame, requested: pd.Timestamp):
    rows = frame.loc[frame.fecha >= requested].sort_values("fecha")
    return None if rows.empty else rows.iloc[0]


def last_on_or_before(frame: pd.DataFrame, requested: pd.Timestamp):
    rows = frame.loc[frame.fecha <= requested].sort_values("fecha")
    return None if rows.empty else rows.iloc[-1]


def source_name(row: pd.Series) -> str:
    return "SBS OFICIAL" if row.fuente == "SBS" else "MODELO OLS"


def signal_band(history: pd.DataFrame, pending: pd.DataFrame) -> go.Figure:
    frames = [history[["fecha", "senal", "ret_estimado"]].assign(fuente="SBS")]
    if not pending.empty:
        frames.append(
            pending[["fecha", "senal", "ret_estimado"]].assign(
                fuente="MODELO OLS"
            )
        )
    data = (
        pd.concat(frames, ignore_index=True)
        .sort_values("fecha")
        .drop_duplicates("fecha", keep="last")
    )
    data = data.loc[data.senal.isin(["SUBE", "NEUTRO", "BAJA"])].tail(120)
    numeric = data.senal.map({"BAJA": -1, "NEUTRO": 0, "SUBE": 1})
    colors = [
        [0.00, "#ef4444"], [0.2499, "#ef4444"],
        [0.25, "#f59e0b"], [0.7499, "#f59e0b"],
        [0.75, "#22c55e"], [1.00, "#22c55e"],
    ]
    figure = go.Figure(
        go.Heatmap(
            z=[numeric.tolist()], x=data.fecha, y=["Señal"],
            zmin=-1, zmax=1, colorscale=colors, xgap=1.5,
            customdata=np.array(
                [data[["senal", "ret_estimado", "fuente"]].to_numpy()],
                dtype=object,
            ),
            hovertemplate=(
                "<b>%{x|%d/%m/%Y}</b><br>Señal: %{customdata[0]}<br>"
                "Retorno: %{customdata[1]:+.3%}<br>"
                "Fuente: %{customdata[2]}<extra></extra>"
            ),
            colorbar={
                "tickvals": [-1, 0, 1],
                "ticktext": ["BAJA", "NEUTRO", "SUBE"],
                "orientation": "h", "y": -0.55, "len": 0.65,
            },
        )
    )
    figure.update_layout(
        title="Historial de señales", height=260,
        margin={"l": 20, "r": 20, "t": 50, "b": 90},
        yaxis={"showticklabels": False, "fixedrange": True},
    )
    return figure


st.title("Monitor diario Profuturo Fondo 3")
st.caption(
    f"OLS rolling {WINDOW} · misma fecha · umbral ±{THRESHOLD:.2%} · "
    "mismo criterio operativo del notebook"
)
mode = st.radio("¿Qué deseas hacer?", ["Solo monitorear", "Sigo dentro", "Ya salí"])
use_intraday, temporal_mode, now_lima, close_lima = market_mode(mode)

status = st.columns(3)
status[0].metric("Datos de mercado", temporal_mode)
status[1].metric("Hora en Lima", now_lima.strftime("%d/%m %H:%M"))
status[2].metric("Cierre EE. UU.", close_lima.strftime("%H:%M"))
if mode == "Ya salí":
    st.info("Una operación cerrada usa solo cierres diarios, nunca intradía.")
elif use_intraday:
    st.warning("El mercado está abierto: el resultado más reciente es provisional.")
else:
    st.success("Se están utilizando cierres diarios.")

if st.button("Actualizar SBS, índices y modelo", type="primary", use_container_width=True):
    st.cache_data.clear()
    st.rerun()

with st.spinner("Actualizando fuentes y ejecutando OLS rolling 90..."):
    try:
        sbs, sbs_source = load_sbs_safe()
        markets = core["load_markets"]()
        _, history, pending = core["model_outputs"](
            sbs, markets, use_intraday
        )
    except Exception as error:
        st.error("No se pudo ejecutar el monitor.")
        st.exception(error)
        st.stop()

last_sbs = sbs.iloc[-1]
latest = pending.iloc[-1] if not pending.empty else history.iloc[-1]
latest_vc = float(
    latest["valor_cuota_estimado"]
    if "valor_cuota_estimado" in latest.index
    else latest["valor_cuota"]
)
complete = bool(latest.get("fuentes_completas", True)) and not use_intraday

cards = st.columns(4)
cards[0].metric("Último VC SBS", f"{last_sbs.valor_cuota:.7f}", f"{last_sbs.fecha:%d/%m/%Y}")
cards[1].metric("VC más reciente", f"{latest_vc:.7f}", f"{latest.fecha:%d/%m/%Y}")
cards[2].metric("Señal", str(latest.senal), f"{latest.ret_estimado:+.3%}")
cards[3].metric("Estado", "COMPLETO" if complete else "PROVISIONAL")
st.caption(f"Fuente SBS: {sbs_source} · núcleo {CORE_SHA[:8]} · {temporal_mode}")

all_vc = pd.concat(
    [
        sbs[["fecha", "valor_cuota"]].rename(
            columns={"valor_cuota": "vc"}
        ).assign(fuente="SBS"),
        (
            pending[["fecha", "valor_cuota_estimado"]].rename(
                columns={"valor_cuota_estimado": "vc"}
            ).assign(fuente="MODELO OLS")
            if not pending.empty
            else pd.DataFrame(columns=["fecha", "vc", "fuente"])
        ),
    ], ignore_index=True,
)
all_vc.fecha = pd.to_datetime(all_vc.fecha, errors="coerce").dt.normalize()
all_vc.vc = pd.to_numeric(all_vc.vc, errors="coerce")
all_vc = all_vc.dropna().sort_values("fecha").drop_duplicates("fecha", keep="last")

if mode != "Solo monitorear":
    st.subheader("Tu operación")
    min_date, max_date = all_vc.fecha.min().date(), all_vc.fecha.max().date()
    default_entry = min(max(pd.Timestamp("2026-07-20").date(), min_date), max_date)
    with st.form("operation"):
        entry_requested = pd.Timestamp(
            st.date_input("Fecha de entrada", default_entry, min_value=min_date, max_value=max_date)
        )
        capital = st.number_input("Capital invertido (S/)", 1.0, value=20000.0, step=100.0)
        if mode == "Ya salí":
            exit_requested = pd.Timestamp(
                st.date_input("Fecha de salida", max_date, min_value=entry_requested.date(), max_value=max_date)
            )
        else:
            exit_requested = pd.Timestamp(all_vc.fecha.max())
            st.write(f"Posición abierta valorada al {exit_requested:%d/%m/%Y}.")
        calculate = st.form_submit_button("Calcular", type="primary", use_container_width=True)

    if calculate:
        entry = first_on_or_after(all_vc, entry_requested)
        exit_row = last_on_or_before(all_vc, exit_requested)
        if entry is None or exit_row is None:
            st.error("No existe valor cuota para el periodo seleccionado.")
        elif exit_row.fecha < entry.fecha:
            st.error("La fecha efectiva de salida es anterior a la entrada.")
        else:
            units = float(capital) / float(entry.vc)
            final_value = units * float(exit_row.vc)
            st.session_state.operation = {
                "mode": mode, "entry_req": entry_requested, "exit_req": exit_requested,
                "entry_date": pd.Timestamp(entry.fecha), "exit_date": pd.Timestamp(exit_row.fecha),
                "entry_vc": float(entry.vc), "exit_vc": float(exit_row.vc),
                "entry_source": source_name(entry), "exit_source": source_name(exit_row),
                "capital": float(capital), "units": units, "final": final_value,
            }

    op = st.session_state.get("operation")
    if op and op["mode"] == mode:
        gain = op["final"] - op["capital"]
        profitability = op["final"] / op["capital"] - 1
        metrics = st.columns(4)
        metrics[0].metric("Capital", f"S/ {op['capital']:,.2f}")
        metrics[1].metric("Valor actual/final", f"S/ {op['final']:,.2f}")
        metrics[2].metric("Ganancia o pérdida", f"S/ {gain:,.2f}")
        metrics[3].metric("Rentabilidad", f"{profitability:+.2%}")
        if op["exit_source"] == "SBS OFICIAL":
            st.success("Resultado con valor cuota oficial SBS.")
        else:
            st.warning("Resultado provisional: el VC final proviene del modelo OLS.")
        st.write(
            f"Entrada solicitada {op['entry_req']:%d/%m/%Y}; usada {op['entry_date']:%d/%m/%Y}; "
            f"VC {op['entry_vc']:.7f} ({op['entry_source']})."
        )
        st.write(
            f"Salida/valoración solicitada {op['exit_req']:%d/%m/%Y}; usada {op['exit_date']:%d/%m/%Y}; "
            f"VC {op['exit_vc']:.7f} ({op['exit_source']})."
        )
        st.code(
            f"S/ {op['capital']:,.2f} × ({op['exit_vc']:.7f} / {op['entry_vc']:.7f}) "
            f"= S/ {op['final']:,.2f}"
        )

        trajectory = all_vc.loc[
            (all_vc.fecha >= op["entry_date"]) & (all_vc.fecha <= op["exit_date"])
        ].copy()
        trajectory["gain"] = op["units"] * trajectory.vc - op["capital"]
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=trajectory.fecha, y=trajectory.vc, mode="lines+markers", name="Valor cuota", yaxis="y"))
        fig.add_trace(go.Scatter(x=trajectory.fecha, y=trajectory.gain, mode="lines+markers", name="Ganancia/pérdida", yaxis="y2"))
        fig.update_layout(
            title="Valor cuota y ganancia/pérdida", height=430, hovermode="x unified",
            yaxis={"title": "Valor cuota", "tickformat": ".7f"},
            yaxis2={"title": "Ganancia/pérdida (S/)", "overlaying": "y", "side": "right", "tickprefix": "S/ ", "showgrid": False},
            legend={"orientation": "h"},
        )
        st.plotly_chart(fig, use_container_width=True)

st.subheader("Retorno estimado del valor cuota")
model_series = pd.concat(
    [history[["fecha", "ret_estimado"]], pending[["fecha", "ret_estimado"]] if not pending.empty else pd.DataFrame(columns=["fecha", "ret_estimado"])],
    ignore_index=True,
).sort_values("fecha")
st.plotly_chart(core["stem"](model_series, "ret_estimado", "Retorno diario OLS", True), use_container_width=True)

st.subheader("Señales")
st.plotly_chart(signal_band(history, pending), use_container_width=True)

with st.expander("Auditoría y corte de datos"):
    validation = history[history.fecha.dt.year == 2026]
    direction = np.mean(np.sign(validation.ret_profuturo) == np.sign(validation.ret_estimado))
    audit = pd.DataFrame(
        [
            ["Modelo", f"OLS rolling {WINDOW}", "APROBADO"],
            ["Sin anticipación", "ventana_fin < fecha", "APROBADO" if (history.ventana_fin < history.fecha).all() else "REVISAR"],
            ["Umbral", f"±{THRESHOLD:.2%}", "APROBADO"],
            ["Entrada", "Primera fecha disponible >= solicitada", "APROBADO"],
            ["Salida", "Última fecha disponible <= solicitada", "APROBADO"],
            ["Operación cerrada", "Solo cierres diarios", "APROBADO" if mode != "Ya salí" or not use_intraday else "REVISAR"],
            ["Última SBS", f"{last_sbs.fecha:%d/%m/%Y}", "APROBADO"],
            ["Última estimación", f"{latest.fecha:%d/%m/%Y}", "COMPLETA" if complete else "PROVISIONAL"],
            ["Dirección 2026", f"{direction:.1%}", "REFERENCIA"],
        ], columns=["Control", "Resultado", "Estado"]
    )
    st.dataframe(audit, hide_index=True, use_container_width=True)

st.caption("Estimación informativa; no garantiza resultados ni constituye recomendación financiera.")
