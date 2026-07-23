"""Punto de entrada seguro de Streamlit Community Cloud.

Ejecuta la aplicación completa en cada rerun. No usa una importación
convencional porque Python conserva los módulos importados en memoria y
Streamlit podría mostrar una página vacía en las siguientes ejecuciones.
"""

from pathlib import Path
import runpy

import streamlit as st

HERE = Path(__file__).resolve().parent
APP_FILE = HERE / "streamlit_unified.py"

st.set_page_config(
    page_title="Profuturo Fondo 3",
    page_icon="📈",
    layout="wide",
)

loading = st.empty()
loading.info("Cargando datos SBS, índices y modelo OLS rolling 90…")

try:
    runpy.run_path(str(APP_FILE), run_name="__main__")
    loading.empty()
except Exception as error:
    loading.empty()
    st.error("La aplicación unificada no pudo iniciar.")
    st.exception(error)
    st.stop()
