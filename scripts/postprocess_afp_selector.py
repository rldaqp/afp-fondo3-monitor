from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "public" / "index.html"
MARKER = "AFP_SELECTOR_V1"

STYLE = """
<style id="afpSelectorStyles">
.afp-selector{display:grid;grid-template-columns:1fr 1fr;gap:9px;margin:12px 0}.afp-selector label{font-size:.72rem;color:#94a3b8}.afp-selector select{width:100%;background:#07111f;color:#fff;border:1px solid #334155;border-radius:9px;padding:10px}
@media(max-width:700px){.afp-selector{grid-template-columns:1fr}}
</style>
"""
BLOCK = """
<!-- AFP_SELECTOR_V1 -->
<div class="afp-selector"><div><label>AFP</label><select id="globalAfpSelector"><option value="./" selected>Profuturo</option><option value="habitat/">Hábitat</option></select></div><div><label>Fondo</label><select disabled><option>Fondo 3</option></select></div></div>
<script>document.getElementById('globalAfpSelector').addEventListener('change',function(){location.href=this.value;});</script>
"""


def main() -> None:
    html = INDEX.read_text(encoding="utf-8")
    if MARKER in html:
        print("Selector AFP ya presente.")
        return
    html = html.replace("</head>", STYLE + "\n</head>", 1)
    html = html.replace('<main class="wrap">', '<main class="wrap">\n' + BLOCK, 1)
    INDEX.write_text(html, encoding="utf-8")
    print("Selector AFP Profuturo/Hábitat agregado.")


if __name__ == "__main__":
    main()
