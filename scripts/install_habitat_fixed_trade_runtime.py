from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "public" / "data" / "fixed_trade_runtime_v1.js"
OUT = ROOT / "public" / "habitat" / "data" / "fixed_trade_runtime_v1.js"
HABITAT_DRIVE_URL = "https://script.google.com/macros/s/AKfycbxoYHkCu0cZPx_KsMlI0Jd5PEATgxBjZTR8oK8qs1cUjRHJbiK0t-bxkH5ACprgp81S7g/exec"


def main() -> None:
    if not SOURCE.exists():
        raise RuntimeError(f"Falta runtime Profuturo de referencia: {SOURCE}")

    text = SOURCE.read_text(encoding="utf-8")
    # Mantenemos exactamente la misma lógica operativa del visor Profuturo y
    # cambiamos únicamente identidad, almacenamiento y endpoint de Hábitat.
    text = text.replace("const FUND='PROFUTURO';", "const FUND='HABITAT';")
    text = text.replace(
        "VISOR GITHUB · PROFUTURO · NIVELES/RETORNOS",
        "VISOR GITHUB · HABITAT · NIVELES/RETORNOS",
    )
    text = text.replace("profuturo_fondo3", "habitat_fondo3")
    text = text.replace("Profuturo Fondo 3", "Hábitat Fondo 3")
    text = text.replace("Profuturo", "Hábitat")
    text = re.sub(
        r"const DEFAULT_URL='[^']*';",
        f"const DEFAULT_URL='{HABITAT_DRIVE_URL}';",
        text,
        count=1,
    )

    if "PROFUTURO" in text or "Profuturo" in text or "profuturo_fondo3" in text:
        raise RuntimeError("Persisten referencias de Profuturo en el runtime Hábitat")
    required = [
        "const FUND='HABITAT';",
        "data/fixed_models_2026.json",
        "data/fixed_models_intraday.json",
        "habitat_fondo3_trade_history_v3",
        "Hábitat Fondo 3",
        HABITAT_DRIVE_URL,
        "Modelo niveles",
        "Modelo retornos",
    ]
    for marker in required:
        if marker not in text:
            raise RuntimeError(f"Runtime Hábitat incompleto: falta {marker}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    print("Runtime de operaciones Hábitat instalado desde la lógica Profuturo:", OUT)


if __name__ == "__main__":
    main()
