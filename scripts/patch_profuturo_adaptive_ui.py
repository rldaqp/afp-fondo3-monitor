from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
P = ROOT / "public" / "index.html"


def main():
    s = P.read_text(encoding="utf-8")
    replacements = {
        "<title>Profuturo Fondo 3 · Dos modelos Rolling 30</title>": "<title>Profuturo Fondo 3 · Modelo A adaptativo EPU/BVL</title>",
        "Comparación operativa · dos modelos OLS Rolling 30 · histórico diario one-step separado de la validación blind3": "Comparación operativa · Modelo A Rolling 30 adaptativo EPU/BVL · histórico diario reconstruido one-step sin lookahead",
        "Modelo A · Rolling 30 + QQQ": "Modelo A · Rolling 30 adaptativo EPU/BVL",
        "SPY · EEM · EPU · MCHI · USD/PEN · QQQ": "SPY · EEM · MCHI · USD/PEN · QQQ · Perú: EPU/SPBLSCUP",
        "Mercado ahora · factores realmente usados": "Mercado ahora · factores y señal Perú realmente usada",
    }
    for old, new in replacements.items():
        s = s.replace(old, new)

    # Añade una nota visible bajo el encabezado del Modelo A, sin tocar la lógica
    # de gráficos. La señal exacta usada por sesión queda además dentro del JSON.
    marker = '<div class="sub">SPY · EEM · MCHI · USD/PEN · QQQ · Perú: EPU/SPBLSCUP</div>'
    note = marker + '<div class="small">Regla Perú: EPU normalmente; SPBLSCUP cuando ambos tienen signo opuesto al cierre.</div>'
    if marker in s and note not in s:
        s = s.replace(marker, note, 1)

    P.write_text(s, encoding="utf-8")
    print("UI adaptativa EPU/BVL aplicada")


if __name__ == "__main__":
    main()
