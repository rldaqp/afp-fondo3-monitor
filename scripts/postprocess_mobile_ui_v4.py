from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
HTML_PATH = ROOT / "public" / "index.html"
html = HTML_PATH.read_text(encoding="utf-8")

# El gráfico de retornos no necesita leyenda: los colores y el hover ya muestran
# la señal; cada punto conserva su tallo independiente desde cero.
html = html.replace(
    "mode:'markers',name:'Retorno estimado VC',marker:",
    "mode:'markers',name:'Retorno estimado VC',showlegend:false,marker:",
)
html = html.replace(
    "margin:{l:48,r:18,t:45,b:45},shapes:[{type:'line',xref:'paper',x0:0,x1:1,y0:0,y1:0",
    "margin:{l:48,r:18,t:45,b:45},showlegend:false,shapes:[{type:'line',xref:'paper',x0:0,x1:1,y0:0,y1:1-1",
)
html = html.replace("y0:0,y1:1-1", "y0:0,y1:0")

old_note = (
    "SPY, NEM, FCX, EPU y MCHI: Yahoo Finance. Durante mercado abierto se muestran "
    "cotizaciones intradía; fuera de mercado se muestran cierres. USD/PEN: BCRP primero "
    "y Yahoo PEN=X solo como respaldo reciente."
)
new_note = (
    "SPY, NEM, FCX, EPU y MCHI: Yahoo Finance. USD/PEN del MODELO: BCRP. "
    "Si BCRP aún no publicó la fecha, el modelo usa 0 % provisional, exactamente como el notebook. "
    "PEN=X puede mostrarse solo como referencia visual y nunca sustituye al BCRP en el cálculo."
)
html = html.replace(old_note, new_note)

old_card = "<div class=\"market-source\">${a.estado||''}</div></div>"
new_card = "<div class=\"market-source\">${a.estado||''}${a.retorno_modelo!=null&&Number(a.retorno_modelo)!==Number(a.retorno)?'<br>Modelo: '+(Number(a.retorno_modelo)*100).toFixed(2)+'%':''}</div></div>"
html = html.replace(old_card, new_card)

# Mantener todas las lecturas del navegador en el mismo origen (GitHub Pages).
# El workflow intradía actualiza el JSON y solicita una nueva publicación de Pages.
raw_live = "https://raw.githubusercontent.com/rldaqp/afp-fondo3-monitor/migracion-github-actions/public/data/live_market.json"
html = html.replace(raw_live + "?ts='+Date.now()", "data/live_market.json?ts='+Date.now()")
html = html.replace(raw_live, "data/live_market.json")

HTML_PATH.write_text(html, encoding="utf-8")

# Última capa: el dato intradía solo puede reemplazar al cierre mientras esté
# vigente; además se incorpora al mismo gráfico y se evita caché de los JSON.
runpy.run_path(str(ROOT / "scripts" / "postprocess_live_consistency.py"), run_name="__main__")
print("Visor v4: gráfico limpio + USD/PEN notebook + consistencia intradía/cierre.")
