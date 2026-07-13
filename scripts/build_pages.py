from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"
PUBLIC = ROOT / "public"


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, cwd=ROOT, check=True)


def copy_if_exists(src: Path, dst: Path) -> None:
    if src.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Actualiza el monitor Fondo 3 y prepara la carpeta public para GitHub Pages."
    )
    parser.add_argument(
        "--skip-update",
        action="store_true",
        help="Solo copia el HTML ya generado a public, sin ejecutar la actualizacion.",
    )
    args = parser.parse_args()

    if not args.skip_update:
        run([sys.executable, "129_monitor_fondo3_ACTUALIZA_Y_ABRE.py", "--actualizar"])
        run([sys.executable, "src/descargar_sbs_actual.py"])
        run([sys.executable, "src/04_construir_base_maestra_fondo3.py"])
        run([sys.executable, "src/07_descargar_factores_mercado.py"])

    run([sys.executable, "src/131_comparar_metricas_modelos.py"])
    run([sys.executable, "src/137_descargar_tickers_directos_cartera.py"])
    run([sys.executable, "src/136_construir_cartera_replicante_instrumental.py"])
    run([sys.executable, "src/139_reconstruccion_dinamica_cartera_implicita.py"])
    run([sys.executable, "src/141_explorar_senales_forecast_t1.py"])
    run([sys.executable, "src/138_competencia_pronostico_t1_series_tiempo.py"])
    run([sys.executable, "src/140_pronostico_operativo_cartera_dinamica_factores.py"])
    run([sys.executable, "src/142_modelo_direccion_t1.py"])
    run([sys.executable, "src/143_diagnostico_fallos_direccion.py"])
    run([sys.executable, "src/144_confianza_direccion.py"])
    run([sys.executable, "src/145_ultimas_senales_operativas.py"])
    run([sys.executable, "src/146_test_final_modelo_recomendado.py"])
    run([sys.executable, "src/148_diagnostico_post_test_y_siguiente_prueba.py"])
    run([sys.executable, "src/149_laboratorio_post_test_acciones_por_afp.py"])
    run([sys.executable, "src/150_formalizar_filtro_senal_fuerte_walkforward.py"])
    run([sys.executable, "src/153_priorizar_aprendizaje_cartera.py"])
    run([sys.executable, "src/154_priorizar_reemplazos_proxy_por_ticker.py"])
    run([sys.executable, "src/157_descargar_tickers_pendientes_reemplazo.py"])
    run([sys.executable, "src/154_priorizar_reemplazos_proxy_por_ticker.py"])
    run([sys.executable, "src/155_experimento_reemplazo_proxy_por_ticker.py"])
    run([sys.executable, "src/156_forecast_t1_con_cartera_proxy_ticker.py"])
    run([sys.executable, "src/160_experimento_instrumentos_especificos.py"])
    run([sys.executable, "src/161_experimento_bloques_mercado.py"])
    run([sys.executable, "src/162_forecast_t1_bloques_mercado.py"])
    run([sys.executable, "src/158_experimento_rezagos_valorizacion.py"])
    run([sys.executable, "src/159_estimacion_publicacion_calendario.py"])
    run([sys.executable, "src/166_filtrar_tickers_cartera_replicante.py"])
    run([sys.executable, "src/167_optimizar_calendario_publicacion_por_afp.py"])
    run([sys.executable, "src/168_regimenes_confianza_publicacion.py"])
    run([sys.executable, "src/169_overlay_direccion_integra_profuturo.py"])
    run([sys.executable, "src/163_ultimas_estimaciones_publicacion.py"])
    run([sys.executable, "src/164_extender_sbs_bat_y_comparar.py"])
    run([sys.executable, "src/165_preparar_grafico_estimado_vs_sbs.py"])
    run([sys.executable, "src/147_decision_modelo_final.py"])
    run([sys.executable, "src/151_evaluar_modelo_final_consolidado.py"])
    run([sys.executable, "src/133_mapear_cartera_replicante_y_generar_visor.py"])
    run([sys.executable, "src/152_generar_visor_final_limpio.py"])
    run([sys.executable, "src/170_preparar_tablero_operativo_diario.py"])
    run([sys.executable, "src/171_generar_visor_operativo_simple.py"])

    PUBLIC.mkdir(parents=True, exist_ok=True)

    copy_if_exists(
        PROCESSED / "ca0001_monitor_fondo3_actualizado.html",
        PUBLIC / "index.html",
    )
    copy_if_exists(
        PROCESSED / "ca0001_modelo99_cuota_sintetica_intradia.html",
        PUBLIC / "vela-intradia.html",
    )
    copy_if_exists(
        PROCESSED / "ca0001_modelo97_simulador_monto_fondo3.html",
        PUBLIC / "simulador.html",
    )
    copy_if_exists(
        PROCESSED / "ca0001_modelo80_dashboard.html",
        PUBLIC / "dashboard.html",
    )
    copy_if_exists(
        PROCESSED / "ca0001_modelo111_vela_pronostico_historico.html",
        PUBLIC / "vela-diaria.html",
    )
    copy_if_exists(
        PROCESSED / "cartera_replicante_visor.html",
        PUBLIC / "cartera-replicante" / "index.html",
    )

    if not (PUBLIC / "index.html").exists():
        raise FileNotFoundError(
            "No se genero public/index.html. Revisa data/processed/ca0001_monitor_fondo3_actualizado.html."
        )

    print(f"GitHub Pages listo en: {(PUBLIC / 'index.html').resolve()}")


if __name__ == "__main__":
    main()
