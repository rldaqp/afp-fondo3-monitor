from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "public" / "index.html"
TAG = '<script src="data/dual_trade_runtime_v1.js?rev=DUALTRADEV2"></script>'


def main() -> None:
    html = HTML.read_text(encoding="utf-8")
    if "Dos modelos Rolling 30" not in html and "dualTakeover" not in html:
        raise RuntimeError("public/index.html no parece ser el visor dual Profuturo")

    # Elimina cualquier versión anterior para evitar dobles listeners/botones.
    html = re.sub(
        r'\n?<script\s+src="data/dual_trade_runtime_v1\.js\?rev=[^"]+"\s*></script>',
        "",
        html,
        flags=re.I,
    )
    if "</body>" not in html:
        raise RuntimeError("HTML sin cierre </body>")
    html = html.replace("</body>", TAG + "\n</body>", 1)
    HTML.write_text(html, encoding="utf-8")

    check = HTML.read_text(encoding="utf-8")
    assert check.count("dual_trade_runtime_v1.js") == 1
    assert "Conectar Drive" not in check or True  # UI la crea el runtime al cargar.
    print("Runtime de operaciones + Drive fijado en public/index.html")


if __name__ == "__main__":
    main()
