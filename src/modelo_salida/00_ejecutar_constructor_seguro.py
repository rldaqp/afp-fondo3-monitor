from __future__ import annotations

import importlib.util
import runpy
import sys
from pathlib import Path


# Compatibilidad para módulos cargados dinámicamente que contienen dataclasses.
# Python 3.11 espera que el módulo ya exista en sys.modules cuando procesa
# las anotaciones de la clase. El módulo 79 se carga mediante module_from_spec,
# por lo que se registra inmediatamente antes de ejecutar su código.
_module_from_spec_original = importlib.util.module_from_spec


def module_from_spec_registrado(spec):
    modulo = _module_from_spec_original(spec)
    if spec.name:
        sys.modules[spec.name] = modulo
    return modulo


def main() -> None:
    importlib.util.module_from_spec = module_from_spec_registrado
    ruta = Path(__file__).with_name("01_construir_base_salida.py")
    runpy.run_path(str(ruta), run_name="__main__")


if __name__ == "__main__":
    main()
