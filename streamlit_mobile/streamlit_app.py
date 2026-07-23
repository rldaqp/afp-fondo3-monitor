from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

HERE = Path(__file__).resolve().parent
SBS_FILE = HERE / "data" / "sbs_profuturo_f3_fallback.csv"
SNAPSHOT_FILE = HERE / "data" / "model_snapshot_fallback.csv"
THRESHOLD = 0.001

st.set_page_config(
    page_title="Profuturo Fondo 3",
    page_icon="📈",
    layout="wide",
)


@st.cache_data(show_spinner=False)
def load_fallback_data():
    sbs = pd.read_csv(SBS_FILE, encoding="utf-8-sig")
    sbs["fecha"] = pd.to_datetime(sbs["fecha"], errors="coerce")
    sbs["valor_cuota"] = pd.to_numeric(
        sbs["valor_cuota"], errors="coerce"
    )

    snapshot = pd.read_csv(SNAPSHOT_FILE)
    snapshot["fecha"] = pd.to_datetime(snapshot["fecha"], errors="coerce")
    snapshot["ret_estimado"] = pd.to_numeric(
        snapshot["ret_estimado"], errors="coerce"
    )
    snapshot["valor_cuota_estimado"] = pd.to_numeric(
        snapshot["valor_cuota_estimado"], errors="coerce"
    )
    snapshot["valor_cuota"] = pd.to_numeric(
        snapshot["valor_cuota"], errors="coerce"
    )

    official_snapshot = snapshot.loc[
        snapshot["valor_cuota"].notna(), ["fecha", "valor_cuota"]
    ]
    sbs = (
        pd.concat([sbs, official_snapshot], ignore_index=True)
        .dropna(subset=["fecha", "valor_cuota"])
        .sort_values("fecha")
        .drop_duplicates("fecha", keep="last")
        .reset_index(drop=True)
    )

    pending = (
        snapshot.loc[
            snapshot["valor_cuota_estimado"].notna(),
            ["fecha", "valor_cuota_estimado", "ret_estimado", "senal"],
        ]
        .sort_values("fecha")
        .reset_index(drop=True)
    )

    all_vc = pd.concat(
        [
            sbs.rename(columns={"valor_cuota": "vc"}).assign(
                fuente="SBS OFICIAL"
            ),
            pending.rename(columns={"valor_cuota_estimado": "vc"}).assign(
                fuente="MODELO OLS — RESPALDO"
            ),
        ],
        ignore_index=True,
    )
    all_vc["fecha"] = pd.to_datetime(all_vc["fecha"], errors="coerce")
    all_vc["vc"] = pd.to_numeric(all_vc["vc"], errors="coerce")
    all_vc = (
        all_vc.dropna(subset=["fecha", "vc"])
        .sort_values("fecha")
        .drop_duplicates("fecha", keep="last")
        .reset_index(drop=True)
    )
    return sbs, snapshot, pending, all_vc


def first_on_or_after(frame, requested):
    rows = frame.loc[frame["fecha"] >= requested]
    return None if rows.empty else rows.iloc[0]


def last_on_or_before(frame, requested):
    rows = frame.loc[frame["fecha"] <= requested]
    return None if rows.empty else rows.iloc[-1]


def signal_figure(snapshot):
    data = snapshot.loc[
        snapshot["senal"].isin(["SUBE", "NEUTRO", "BAJA"])
    ].copy()
    levels = data["senal"].map({"BAJA": -1, "NEUTRO": 0, "SUBE": 1})
    colors = [
        [0.00, "#ef4444"],
        [0.2499, "#ef4444"],
        [0.25, "#f59e0b"],
        [0.7499, "#f59e0b"],
        [0.75, "#22c55e"],
        [1.00, "#22c55e"],
    ]
    fig = go.Figure(
        go.Heatmap(
            z=[levels.tolist()],
            x=data["fecha"],
            y=["Señal"],
            zmin=-1,
            zmax=1,
            colorscale=colors,
            xgap=1.5,
            customdata=np.array(
                [data[["senal", "ret_estimado"]].to_numpy()],
                dtype=object,
            ),
            hovertemplate=(
                "<b>%{x|%d/%m/%Y}</b><br>"
                "Señal: %{customdata[0]}<br>"
                "Retorno estimado: %{customdata[1]:+.3%}"
                "<extra></extra>"
            ),
            colorbar={
                "tickvals": [-1, 0, 1],
                "ticktext": ["BAJA", "NEUTRO", "SUBE"],
                "orientation": "h",
                "y": -0.55,
                "len": 0.65,
            },
        )
    )
    fig.update_layout(
        title="Historial de señales",
        height=260,
        margin={"l": 20, "r": 20, "t": 50, "b": 90},
        yaxis={"showticklabels": False, "fixedrange": True},
    )
    return fig


def return_figure(snapshot):
    data = snapshot.dropna(subset=["ret_estimado"]).copy()
    stems_x, stems_y = [], []
    for row in data.itertuples():
        stems_x.extend([row.fecha, row.fecha, None])
        stems_y.extend([0, row.ret_estimado * 100, None])

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=stems_x,
            y=stems_y,
            mode="lines",
            showlegend=False,
            hoverinfo="skip",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=data["fecha"],
            y=data["ret_estimado"] * 100,
            mode="markers",
            name="OLS rolling 90",
            customdata=data[["senal"]].to_numpy(),
            hovertemplate=(
                "<b>%{x|%d/%m/%Y}</b><br>"
                "Retorno: %{y:+.4f}%<br>"
                "Señal: %{customdata[0]}<extra></extra>"
            ),
        )
    )
    fig.add_hline(y=0)
    fig.add_hline(y=THRESHOLD * 100, line_dash="dot")
    fig.add_hline(y=-THRESHOLD * 100, line_dash="dot")
    fig.update_layout(
        title="Retorno diario estimado del valor cuota",
        height=420,
        yaxis_title="Retorno (%)",
        xaxis_title="Fecha",
    )
    return fig


def operation_figure(path, capital, entry_vc):
    units = capital / entry_vc
    path = path.copy()
    path["ganancia"] = units * path["vc"] - capital
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=path["fecha"],
            y=path["vc"],
            mode="lines+markers",
            name="Valor cuota",
            yaxis="y",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=path["fecha"],
            y=path["ganancia"],
            mode="lines+markers",
            name="Ganancia / pérdida",
            yaxis="y2",
        )
    )
    fig.update_layout(
        title="Valor cuota y ganancia/pérdida",
        height=430,
        hovermode="x unified",
        yaxis={"title": "Valor cuota", "tickformat": ".7f"},
        yaxis2={
            "title": "Ganancia/pérdida (S/)",
            "overlaying": "y",
            "side": "right",
            "tickprefix": "S/ ",
            "showgrid": False,
        },
        legend={"orientation": "h"},
    )
    return fig


sbs, snapshot, pending, all_vc = load_fallback_data()
last_official = sbs.iloc[-1]
latest = pending.iloc[-1]
latest_signal = latest["senal"]
latest_return = float(latest["ret_estimado"])
latest_vc = float(latest["valor_cuota_estimado"])

st.title("Monitor diario Profuturo Fondo 3")
st.caption(
    "OLS rolling 90 · umbral ±0.10 % · misma fotografía validada "
    "por el notebook"
)
st.warning(
    "Yahoo Finance está bloqueando temporalmente la IP de Streamlit "
    "(HTTP 429). La app usa la última ejecución OLS válida del notebook, "
    "con corte al 22/07/2026. Los datos posteriores no están actualizados."
)

cards = st.columns(4)
cards[0].metric(
    "Último VC oficial SBS",
    f"{last_official.valor_cuota:.7f}",
    f"{last_official.fecha:%d/%m/%Y}",
)
cards[1].metric(
    "VC estimado de respaldo",
    f"{latest_vc:.7f}",
    f"{latest.fecha:%d/%m/%Y}",
)
cards[2].metric("Señal", latest_signal, f"{latest_return:+.3%}")
cards[3].metric("Estado", "RESPALDO PROVISIONAL")

mode = st.radio(
    "¿Qué deseas hacer?",
    ["Solo monitorear", "Sigo dentro", "Ya salí"],
)

if mode != "Solo monitorear":
    st.subheader("Tu operación")
    min_date = all_vc["fecha"].min().date()
    max_date = all_vc["fecha"].max().date()
    default_entry = min(
        max(pd.Timestamp("2026-07-20").date(), min_date),
        max_date,
    )

    with st.form("operation_form"):
        entry_requested = pd.Timestamp(
            st.date_input(
                "Fecha de entrada",
                default_entry,
                min_value=min_date,
                max_value=max_date,
            )
        )
        capital = st.number_input(
            "Capital invertido (S/)",
            min_value=1.0,
            value=20000.0,
            step=100.0,
        )
        if mode == "Ya salí":
            exit_requested = pd.Timestamp(
                st.date_input(
                    "Fecha de salida",
                    max_date,
                    min_value=entry_requested.date(),
                    max_value=max_date,
                )
            )
        else:
            exit_requested = pd.Timestamp(all_vc["fecha"].max())
            st.write(
                f"Posición valorada con el respaldo al "
                f"{exit_requested:%d/%m/%Y}."
            )
        calculate = st.form_submit_button(
            "Calcular",
            type="primary",
            use_container_width=True,
        )

    if calculate:
        entry = first_on_or_after(all_vc, entry_requested)
        exit_row = last_on_or_before(all_vc, exit_requested)
        if entry is None or exit_row is None or exit_row.fecha < entry.fecha:
            st.error("No existe información válida para ese periodo.")
        else:
            units = float(capital) / float(entry.vc)
            final_value = units * float(exit_row.vc)
            st.session_state["operation_result"] = {
                "mode": mode,
                "entry_requested": entry_requested,
                "exit_requested": exit_requested,
                "entry_date": pd.Timestamp(entry.fecha),
                "exit_date": pd.Timestamp(exit_row.fecha),
                "entry_vc": float(entry.vc),
                "exit_vc": float(exit_row.vc),
                "entry_source": str(entry.fuente),
                "exit_source": str(exit_row.fuente),
                "capital": float(capital),
                "units": units,
                "final": final_value,
            }

    result = st.session_state.get("operation_result")
    if result and result["mode"] == mode:
        gain = result["final"] - result["capital"]
        profitability = result["final"] / result["capital"] - 1

        metrics = st.columns(4)
        metrics[0].metric("Capital", f"S/ {result['capital']:,.2f}")
        metrics[1].metric(
            "Valor actual/final", f"S/ {result['final']:,.2f}"
        )
        metrics[2].metric("Ganancia o pérdida", f"S/ {gain:,.2f}")
        metrics[3].metric("Rentabilidad", f"{profitability:+.2%}")

        st.info(
            f"Entrada usada: {result['entry_date']:%d/%m/%Y} · "
            f"VC {result['entry_vc']:.7f} · {result['entry_source']}.\n\n"
            f"Salida/valoración usada: {result['exit_date']:%d/%m/%Y} · "
            f"VC {result['exit_vc']:.7f} · {result['exit_source']}."
        )
        st.code(
            f"S/ {result['capital']:,.2f} × "
            f"({result['exit_vc']:.7f} / {result['entry_vc']:.7f}) "
            f"= S/ {result['final']:,.2f}"
        )

        path = all_vc.loc[
            (all_vc["fecha"] >= result["entry_date"])
            & (all_vc["fecha"] <= result["exit_date"])
        ]
        st.plotly_chart(
            operation_figure(
                path,
                result["capital"],
                result["entry_vc"],
            ),
            use_container_width=True,
        )

st.subheader("Retorno estimado del valor cuota")
st.plotly_chart(return_figure(snapshot), use_container_width=True)

st.subheader("Señales")
st.plotly_chart(signal_figure(snapshot), use_container_width=True)

with st.expander("Fuente y limitación actual"):
    st.write(
        "La SBS se combina con el respaldo local. Las proyecciones del "
        "21 y 22 de julio provienen de la última ejecución válida del "
        "notebook OLS rolling 90. La app no atribuye esos valores a una "
        "actualización nueva mientras Yahoo siga devolviendo HTTP 429."
    )

st.caption(
    "Estimación informativa; no garantiza resultados ni constituye "
    "recomendación financiera."
)
