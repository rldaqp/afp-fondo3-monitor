"""Punto de entrada seguro de Streamlit Community Cloud."""

from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

try:
    from streamlit_unified import *  # noqa: F401,F403
except Exception as error:
    import streamlit as st

    st.error("La aplicación unificada no pudo iniciar.")
    st.exception(error)
    st.stop()
