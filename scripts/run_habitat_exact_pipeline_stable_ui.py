from __future__ import annotations

from pathlib import Path

import build_habitat_profuturo_parity as ui
import run_habitat_exact_pipeline as pipeline


ORIGINAL_BUILD_HTML = ui.build_html


def stable_build_html() -> None:
    """Conserva el visor Hábitat ya validado en vez de clonarlo del Profuturo actual.

    Profuturo pasó a una interfaz propia de dos modelos Rolling 30. El HTML de
    Hábitat sigue teniendo su estructura, IDs, histórico de operaciones y QQQ
    incremental propios; por tanto ya no debe regenerarse a partir del HTML de
    Profuturo en cada actualización de datos.
    """
    target = ui.HABITAT / "index.html"
    if target.exists() and target.stat().st_size > 1000:
        html = target.read_text(encoding="utf-8")
        required = (
            "Hábitat Fondo 3",
            "tradeHistoryPanel",
            "modelInsightsPanel",
        )
        if all(token in html for token in required):
            print("HTML Hábitat estable conservado; solo se actualizan datos y postprocesadores propios.")
            return

    # Solo para una instalación nueva sin visor Hábitat previo.
    ORIGINAL_BUILD_HTML()


# build_habitat_exact_parity mantiene una referencia al mismo módulo ui.
ui.build_html = stable_build_html
pipeline.habitat_ols.ui.build_html = stable_build_html


if __name__ == "__main__":
    pipeline.main()
