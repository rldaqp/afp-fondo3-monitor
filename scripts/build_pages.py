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
        help="Solo prepara public con los archivos ya generados.",
    )
    args = parser.parse_args()

    # Actualización principal. Se evita ejecutar aquí la cadena experimental
    # de scripts 136-171 porque algunos archivos no están versionados en GitHub
    # y hacían fallar toda la publicación automática.
    if not args.skip_update:
        run([sys.executable, "129_monitor_fondo3_ACTUALIZA_Y_ABRE.py", "--actualizar"])

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

    # Se conserva public/cartera-replicante/index.html ya publicado en el
    # repositorio. Solo se reemplaza cuando existe un visor nuevo generado.
    copy_if_exists(
        PROCESSED / "cartera_replicante_visor.html",
        PUBLIC / "cartera-replicante" / "index.html",
    )

    if not (PUBLIC / "index.html").exists():
        raise FileNotFoundError(
            "No se genero public/index.html. Revisa data/processed/ca0001_monitor_fondo3_actualizado.html."
        )

    cartera = PUBLIC / "cartera-replicante" / "index.html"
    if not cartera.exists():
        raise FileNotFoundError(
            "No existe public/cartera-replicante/index.html."
        )

    print(f"GitHub Pages listo en: {(PUBLIC / 'index.html').resolve()}")
    print(f"Cartera replicante disponible en: {cartera.resolve()}")


if __name__ == "__main__":
    main()
