from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

HERE = Path(__file__).resolve().parent
CORE_URL = (
    "https://raw.githubusercontent.com/rldaqp/afp-fondo3-monitor/"
    "8a0c268c0b13676c6f67dd38a76ee2e50058c288/"
    "streamlit_mobile/streamlit_app.py"
)
FALLBACK = HERE / "data" / "sbs_profuturo_f3_fallback.csv"
CORRECT_SBS_INDEX = (
    "https://www.sbs.gob.pe/app/stats_net/stats/"
    "EstadisticaSistemaFinancieroResultados.aspx?c=FP-1359"
)


def load_core() -> dict:
    response = requests.get(CORE_URL, timeout=45)
    response.raise_for_status()
    source = response.text
    marker = 'st.title("📈 Monitor diario Profuturo Fondo 3")'
    if marker not in source:
        raise RuntimeError("No se pudo separar el núcleo del monitor.")
    definitions = source.split(marker, 1)[0]
    namespace = {
        "__name__": "afp_monitor_core",
        "__file__": str(HERE / "core_original.py"),
    }
    exec(compile(definitions, "core_original.py", "exec"), namespace)
    namespace["SBS_INDEX"] = CORRECT_SBS_INDEX
    return namespace


try:
    core = load_core()
except Exception as error:
    st.error("No se pudo cargar el núcleo del modelo desde GitHub.")
    st.exception(error)
    st.stop()

ASSETS = core["ASSETS"]
FEATURES = core["FEATURES"]
THRESHOLD = core["THRESHOLD"]


def safe_load_sbs() -> tuple[pd.DataFrame, str]:
    online = pd.DataFrame()
    note = ""
    try:
        online = core["load_sbs"]()
        if online is None:
            online = pd.DataFrame()
    except Exception as error:
        note = f"La SBS no respondió: {type(error).__name__}."

    fallback = pd.read_csv(FALLBACK, encoding="utf-8-sig")
    fallback["fecha"] = pd.to_datetime(fallback["fecha"], errors="coerce")
    fallback["valor_cuota"] = pd.to_numeric(
        fallback["valor_cuota"], errors="coerce"
    )
    fallback = fallback.dropna(subset=["fecha", "valor_cuota"])

    frames = [fallback]
    if not online.empty and {"fecha", "valor_cuota"}.issubset(online.columns):
        online = online.copy()
        online["fecha"] = pd.to_datetime(online["fecha"], errors="coerce")
        online["valor_cuota"] = pd.to_numeric(
            online["valor_cuota"], errors="coerce"
        )
        frames.append(online.dropna(subset=["fecha", "valor_cuota"]))

    sbs = (
        pd.concat(frames, ignore_index=True)
        .sort_values("fecha")
        .drop_duplicates("fecha", keep="last")
        .reset_index(drop=True)
    )
    source = "SBS en línea + respaldo" if len(frames) > 1 else "respaldo local"
    return sbs, source + ((". " + note) if note else "")


def first_vc(all_vc: pd.DataFrame, requested: pd.Timestamp):
    rows = all_vc.loc[all_vc["fecha"] >= requested].sort_values("fecha")
    return None if rows.empty else rows.iloc[0]


st.title("Monitor diario Profuturo Fondo 3")
st.caption("OLS rolling 90 · misma fecha · umbral ±0.10 %")

mode = st.radio(
    "¿Qué deseas hacer?",
    ["Solo monitorear", "Registrar compra y sigo dentro", "Registrar compra y salida"],
    help="El monitor funciona siempre. Registrar una operación solo añade el seguimiento de tu dinero.",
)
use_intraday = st.toggle("Incluir datos intradía del mercado", value=True)
if st.button("Actualizar mercado y señal", type="primary", use_container_width=True):
    st.cache_data.clear()
    st.rerun()

with st.spinner("Actualizando SBS, mercados y modelo..."):
    try:
        sbs, sbs_note = safe_load_sbs()
        market = core["load_markets"]()
        data, history, pending = core["model_outputs"](
            sbs, market, use_intraday
        )
    except Exception as error:
        st.error("No se pudo completar el cálculo del monitor.")
        st.exception(error)
        st.stop()

if sbs.empty or history.empty:
    st.error("No hay suficientes datos para calcular el modelo.")
    st.stop()

last_sbs = sbs.iloc[-1]
latest = pending.iloc[-1] if not pending.empty else history.iloc[-1]
complete = bool(latest.get("fuentes_completas", True))

cards = st.columns(4)
cards[0].metric(
    "Último VC SBS",
    f"S/ {last_sbs.valor_cuota:.7f}",
    f"{last_sbs.fecha:%d/%m/%Y}",
)
cards[1].metric(
    "VC estimado",
    f"S/ {latest.get('valor_cuota_estimado', latest.valor_cuota):.7f}",
    f"{latest.fecha:%d/%m/%Y}",
)
cards[2].metric("Señal", latest.senal, f"{latest.ret_estimado:+.3%}")
cards[3].metric(
    "Estado",
    "COMPLETO" if complete else "PROVISIONAL",
    "Fuentes completas" if complete else "Esperar al cierre",
)
st.caption(f"Fuente de valor cuota: {sbs_note}")
if not complete:
    st.warning("La señal más reciente todavía puede cambiar.")

all_vc = pd.concat(
    [
        sbs[["fecha", "valor_cuota"]]
        .rename(columns={"valor_cuota": "vc"})
        .assign(fuente="SBS"),
        (
            pending[["fecha", "valor_cuota_estimado"]]
            .rename(columns={"valor_cuota_estimado": "vc"})
            .assign(fuente="MODELO OLS")
            if not pending.empty
            else pd.DataFrame(columns=["fecha", "vc", "fuente"])
        ),
    ],
    ignore_index=True,
).sort_values("fecha").drop_duplicates("fecha", keep="last")

if mode != "Solo monitorear":
    st.subheader("Tu operación ejecutada")
    st.info("Ingresa los datos de la compra que realmente realizaste. Esto no modifica el modelo.")
    with st.form("operacion"):
        entry_date = pd.Timestamp(
            st.date_input(
                "Fecha en que compraste",
                value=pd.Timestamp("2026-07-20").date(),
            )
        )
        capital = st.number_input(
            "Monto invertido (S/)", min_value=1.0, value=20000.0, step=100.0
        )
        manual_entry = st.checkbox("Conozco el valor cuota exacto de compra")
        entry_vc_input = st.number_input(
            "Valor cuota de compra",
            min_value=0.0,
            value=0.0,
            format="%.7f",
            disabled=not manual_entry,
        )

        if mode == "Registrar compra y salida":
            exit_date = pd.Timestamp(
                st.date_input(
                    "Fecha en que saliste",
                    value=pd.Timestamp.now(tz="America/Lima").date(),
                )
            )
            manual_exit = st.checkbox("Conozco el valor cuota exacto de salida")
            exit_vc_input = st.number_input(
                "Valor cuota de salida",
                min_value=0.0,
                value=0.0,
                format="%.7f",
                disabled=not manual_exit,
            )
        else:
            exit_date = pd.Timestamp(latest.fecha)
            manual_exit = False
            exit_vc_input = 0.0
            st.write(f"La compra sigue abierta y se valorará al {exit_date:%d/%m/%Y}.")

        calculate = st.form_submit_button(
            "Guardar operación y calcular",
            type="primary",
            use_container_width=True,
        )

    if calculate:
        entry_row = first_vc(all_vc, entry_date)
        exit_row = first_vc(all_vc, exit_date)
        if entry_row is None:
            st.error("No hay un valor cuota disponible desde la fecha de compra.")
        elif exit_row is None:
            st.error("No hay un valor cuota disponible desde la fecha de salida.")
        elif exit_date < entry_date:
            st.error("La fecha de salida no puede ser anterior a la compra.")
        else:
            entry_vc = (
                float(entry_vc_input)
                if manual_entry and entry_vc_input > 0
                else float(entry_row.vc)
            )
            exit_vc = (
                float(exit_vc_input)
                if manual_exit and exit_vc_input > 0
                else float(exit_row.vc)
            )
            units = float(capital) / entry_vc
            final_value = units * exit_vc
            st.session_state["operation"] = {
                "entry_date": entry_date,
                "exit_date": exit_date,
                "entry_vc": entry_vc,
                "exit_vc": exit_vc,
                "capital": float(capital),
                "units": units,
                "final_value": final_value,
                "entry_source": "MANUAL" if manual_entry else entry_row.fuente,
                "exit_source": "MANUAL" if manual_exit else exit_row.fuente,
            }

    operation = st.session_state.get("operation")
    if operation:
        result = st.columns(4)
        result[0].metric("Capital", f"S/ {operation['capital']:,.2f}")
        result[1].metric("Valor actual/final", f"S/ {operation['final_value']:,.2f}")
        result[2].metric(
            "Ganancia o pérdida",
            f"S/ {operation['final_value'] - operation['capital']:,.2f}",
        )
        result[3].metric(
            "Rentabilidad",
            f"{operation['final_value'] / operation['capital'] - 1:.2%}",
        )
        st.write(
            f"Compra: {operation['entry_date']:%d/%m/%Y}, VC S/ {operation['entry_vc']:.7f} "
            f"({operation['entry_source']}). Valoración/salida: {operation['exit_date']:%d/%m/%Y}, "
            f"VC S/ {operation['exit_vc']:.7f} ({operation['exit_source']})."
        )
        trajectory = all_vc.loc[
            (all_vc.fecha >= operation["entry_date"])
            & (all_vc.fecha <= operation["exit_date"])
        ].copy()
        trajectory["cartera"] = operation["units"] * trajectory["vc"]
        figure = go.Figure()
        figure.add_trace(
            go.Scatter(
                x=trajectory.fecha,
                y=trajectory.cartera,
                mode="lines+markers",
                name="Cartera",
            )
        )
        figure.add_hline(
            y=operation["capital"],
            line_dash="dot",
            annotation_text="Capital inicial",
        )
        figure.update_layout(
            title="Evolución de tu compra",
            yaxis_title="Valor de la cartera (S/)",
            height=380,
        )
        st.plotly_chart(figure, use_container_width=True)

st.subheader("Valor cuota oficial y estimación acumulada")
vc = go.Figure()
recent_sbs = sbs[sbs.fecha >= "2026-03-01"]
recent_history = history[history.fecha >= "2026-03-01"]
vc.add_trace(
    go.Scatter(
        x=recent_sbs.fecha,
        y=recent_sbs.valor_cuota,
        name="VC oficial SBS",
        mode="lines+markers",
    )
)
vc.add_trace(
    go.Scatter(
        x=recent_history.fecha,
        y=recent_history.valor_cuota_estimado,
        name="VC estimado histórico",
        mode="lines",
    )
)
if not pending.empty:
    vc.add_trace(
        go.Scatter(
            x=[last_sbs.fecha, *pending.fecha],
            y=[last_sbs.valor_cuota, *pending.valor_cuota_estimado],
            name="VC proyectado",
            mode="lines+markers",
            line_dash="dash",
        )
    )
vc.update_layout(height=430, hovermode="x unified", yaxis_title="Valor cuota (S/)")
st.plotly_chart(vc, use_container_width=True)

st.subheader("Retornos diarios de los componentes")
columns = st.columns(2)
for index, asset in enumerate(ASSETS + ["USD_PEN"]):
    with columns[index % 2]:
        st.plotly_chart(
            core["stem"](market, f"ret_{asset}", f"Retorno diario {asset}"),
            use_container_width=True,
        )

model_series = pd.concat(
    [
        history[["fecha", "ret_estimado"]],
        (
            pending[["fecha", "ret_estimado"]]
            if not pending.empty
            else pd.DataFrame(columns=["fecha", "ret_estimado"])
        ),
    ],
    ignore_index=True,
).sort_values("fecha")
st.subheader("Retorno estimado OLS y señal")
st.plotly_chart(
    core["stem"](
        model_series,
        "ret_estimado",
        "Retorno estimado del valor cuota",
        True,
    ),
    use_container_width=True,
)

validation = history[history.fecha.dt.year == 2026]
direction = np.mean(
    np.sign(validation.ret_profuturo) == np.sign(validation.ret_estimado)
)
mae = np.mean(abs(validation.valor_cuota - validation.valor_cuota_estimado))
st.subheader("Auditoría")
st.dataframe(
    pd.DataFrame(
        [
            ["Modelo", "OLS rolling 90", "APROBADO"],
            [
                "Sin anticipación",
                "ventana_fin < fecha",
                "APROBADO"
                if (history.ventana_fin < history.fecha).all()
                else "REVISAR",
            ],
            ["Umbral", "±0.10 %", "APROBADO"],
            ["Dirección 2026", f"{direction:.1%}", "REFERENCIA"],
            ["MAE VC 2026", f"S/ {mae:.4f}", "REFERENCIA"],
            ["Última SBS", f"{last_sbs.fecha:%d/%m/%Y}", "APROBADO"],
            [
                "Última estimación",
                f"{latest.fecha:%d/%m/%Y}",
                "COMPLETA" if complete else "PROVISIONAL",
            ],
        ],
        columns=["Control", "Resultado", "Estado"],
    ),
    hide_index=True,
    use_container_width=True,
)
st.caption("Estimación informativa; no garantiza resultados ni constituye recomendación financiera.")
