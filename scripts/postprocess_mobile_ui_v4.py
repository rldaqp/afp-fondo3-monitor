from pathlib import Path

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
# Reparar la expresión 1-1 a un cero literal para mantener JS simple.
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

# La tarjeta USD/PEN puede tener un retorno visual distinto del retorno usado por
# el modelo. Cuando existe ese campo, mostrarlo explícitamente debajo del estado.
old_card = "<div class=\"market-source\">${a.estado||''}</div></div>"
new_card = "<div class=\"market-source\">${a.estado||''}${a.retorno_modelo!=null&&Number(a.retorno_modelo)!==Number(a.retorno)?'<br>Modelo: '+(Number(a.retorno_modelo)*100).toFixed(2)+'%':''}</div></div>"
html = html.replace(old_card, new_card)

# Mercado ahora debe leer el snapshot vivo del repositorio, no la copia estática
# de GitHub Pages. El parámetro ts evita reutilizar una respuesta cacheada.
raw_live = "https://raw.githubusercontent.com/rldaqp/afp-fondo3-monitor/migracion-github-actions/public/data/live_market.json"
html = html.replace(
    "fetch('data/live_market.json?ts='+Date.now(),{cache:'no-store'})",
    f"fetch('{raw_live}?ts='+Date.now(),{{cache:'no-store'}})",
)
html = html.replace(
    "fetch('data/live_market.json',{cache:'no-store'})",
    f"fetch('{raw_live}?ts='+Date.now(),{{cache:'no-store'}})",
)

if raw_live not in html:
    raise RuntimeError("No se pudo enlazar Mercado ahora con el snapshot vivo del repositorio")

HTML_PATH.write_text(html, encoding="utf-8")
print("Visor v4: gráfico limpio + USD/PEN notebook + Mercado ahora directo desde repositorio.")
