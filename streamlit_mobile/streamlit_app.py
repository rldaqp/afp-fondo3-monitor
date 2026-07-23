"""Punto de entrada seguro de Streamlit Community Cloud.

Ejecuta la aplicación completa en cada rerun y corrige el conflicto entre
la clave del formulario y la clave usada para guardar la operación.
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

# La versión unificada creó el formulario con la clave "operation" y después
# intentó guardar el resultado en st.session_state.operation. Streamlit no
# permite modificar la clave de un widget ya instanciado. Se cambia solamente
# la clave interna del formulario y se conserva "operation" para el resultado.
_original_form = st.form


def _form_without_state_conflict(key, *args, **kwargs):
    safe_key = "operation_form" if key == "operation" else key
    return _original_form(safe_key, *args, **kwargs)


st.form = _form_without_state_conflict

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
