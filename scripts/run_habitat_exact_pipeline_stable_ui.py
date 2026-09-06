from __future__ import annotations

from pathlib import Path

import build_habitat_profuturo_parity as ui
import run_habitat_exact_pipeline as pipeline


ORIGINAL_BUILD_HTML = ui.build_html
ORIGINAL_CLARIFY_CHART = pipeline.clarify_habitat_chart
ORIGINAL_ROUTE_TRADE_CLOUD = pipeline.route_trade_cloud


def dual_ui_is_active() -> bool:
    """Reconoce la interfaz A/B vigente sin depender de IDs de la UI antigua."""
    target = ui.HABITAT / "index.html"
    if not target.exists() or target.stat().st_size <= 1000:
        return False

    html = target.read_text(encoding="utf-8")
    required = (
        "Hábitat Fondo 3",
        "Modelo A · Rolling 30 + QQQ",
        "Modelo B · Rolling 30 + nuevos tickers",
        "data/dual_rolling30_monitor.json",
    )
    return all(token in html for token in required)


def stable_build_html() -> None:
    """Conserva el visor Hábitat ya validado en vez de clonarlo del Profuturo actual.

    Profuturo pasó a una interfaz propia de dos modelos Rolling 30. El HTML de
    Hábitat sigue teniendo su estructura, IDs, histórico de operaciones y QQQ
    incremental propios; por tanto ya no debe regenerarse a partir del HTML de
    Profuturo en cada actualización de datos.
    """
    if dual_ui_is_active():
        print("HTML dual A/B de Hábitat conservado; solo se actualizan los datos.")
        return

    # Solo para una instalación nueva sin visor Hábitat previo.
    ORIGINAL_BUILD_HTML()


def stable_clarify_chart() -> None:
    """Evita aplicar el render OLS antiguo sobre la interfaz dual A/B."""
    if dual_ui_is_active():
        print("Gráficos duales A/B conservados; se omite el postproceso OLS legado.")
        return
    ORIGINAL_CLARIFY_CHART()


def stable_route_trade_cloud(target: str) -> None:
    """La interfaz dual usa su runtime externo y no scripts embebidos legados."""
    if target == "habitat" and dual_ui_is_active():
        print("Runtime dual de operaciones conservado; se omite el enrutador legado.")
        return
    ORIGINAL_ROUTE_TRADE_CLOUD(target)


# build_habitat_exact_parity mantiene una referencia al mismo módulo ui.
ui.build_html = stable_build_html
pipeline.habitat_ols.ui.build_html = stable_build_html
pipeline.clarify_habitat_chart = stable_clarify_chart
pipeline.route_trade_cloud = stable_route_trade_cloud


if __name__ == "__main__":
    pipeline.main()
