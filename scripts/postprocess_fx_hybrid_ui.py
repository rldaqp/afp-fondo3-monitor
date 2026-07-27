from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML_PATH = ROOT / "public" / "index.html"
html = HTML_PATH.read_text(encoding="utf-8")

old_notes = [
    "SPY, NEM, FCX, EPU y MCHI: Yahoo Finance. USD/PEN del MODELO: BCRP. Si BCRP aún no publicó la fecha, el modelo usa 0 % provisional, exactamente como el notebook. PEN=X puede mostrarse solo como referencia visual y nunca sustituye al BCRP en el cálculo.",
    "SPY, NEM, FCX, EPU y MCHI: Yahoo Finance. Durante mercado abierto se muestran cotizaciones intradía; fuera de mercado se muestran cierres. USD/PEN: BCRP primero y Yahoo PEN=X solo como respaldo reciente.",
]
new_note = (
    "SPY, NEM, FCX, EPU y MCHI: Yahoo Finance. USD/PEN: BCRP para histórico y entrenamiento. "
    "Si BCRP aún no publicó la fecha, el modelo usa Yahoo PEN=X de forma provisional; "
    "solo usa 0 % cuando ninguna de las dos fuentes está disponible."
)
for note in old_notes:
    html = html.replace(note, new_note)

# En celular la procedencia del dato debe verse completa, no cortada con puntos suspensivos.
html = html.replace(
    ".market-source{font-size:.68rem;color:#94a3b8;margin-top:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}",
    ".market-source{font-size:.68rem;color:#94a3b8;margin-top:4px;white-space:normal;line-height:1.28;overflow-wrap:anywhere}",
)

# Evitar que un precio no disponible se vea como 0.0000 en la tarjeta USD/PEN.
old_price = "${Number(a.precio_actual).toFixed(a.serie==='USD_PEN'?4:2)}"
new_price = "${a.precio_actual==null?'—':Number(a.precio_actual).toFixed(a.serie==='USD_PEN'?4:2)}"
html = html.replace(old_price, new_price)

HTML_PATH.write_text(html, encoding="utf-8")
print("Visor móvil: regla FX híbrida visible y tarjetas legibles.")
