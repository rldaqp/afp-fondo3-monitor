from __future__ import annotations

import base64
import runpy
import sys
import tempfile
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
CACHE_DIR = Path(tempfile.gettempdir()) / "afp_profuturo_streamlit_bundle"
MARKER = CACHE_DIR / ".ready"

if not MARKER.exists():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    encoded = "".join(
        part.read_text(encoding="ascii")
        for part in sorted(HERE.glob("bundle.part*"))
    )
    zip_path = CACHE_DIR / "bundle.zip"
    zip_path.write_bytes(base64.b64decode(encoded))
    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(CACHE_DIR)
    MARKER.write_text("ok", encoding="utf-8")

sys.path.insert(0, str(CACHE_DIR))
runpy.run_path(str(CACHE_DIR / "streamlit_app.py"), run_name="__main__")
