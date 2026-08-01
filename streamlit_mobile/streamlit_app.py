"""Punto de entrada de Streamlit Community Cloud.

La aplicación activa es completamente autónoma: descarga SBS, índices de
mercado y USD/PEN por su cuenta, ejecuta OLS rolling 90 y calcula la cartera.
No consume resultados, snapshots ni archivos generados por el notebook.
"""

from pathlib import Path
import runpy

import streamlit as st

HERE = Path(__file__).resolve().parent
APP_FILE = HERE / "streamlit_independent.py"

st.set_page_config(
    page_title="Profuturo Fondo 3",
    page_icon="📈",
    layout="wide",
)

loading = st.empty()
loading.info(
    "Descargando SBS, índices y USD/PEN; ejecutando OLS rolling 90…"
)

try:
    runpy.run_path(str(APP_FILE), run_name="__main__")
    loading.empty()
except Exception as error:
    loading.empty()
    st.error("La aplicación autónoma no pudo completar la actualización.")
    st.exception(error)
    st.stop()
