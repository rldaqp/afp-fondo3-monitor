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

# Separar visualmente los factores que sí alimentan al OLS de los nuevos
# tickers que estamos probando en el 60/30. No se mezclan en el cálculo.
EXP_MARKER = "EXPERIMENTAL_MARKET_WATCHLIST_V1"
if EXP_MARKER not in html:
    official_grid = '<div id="marketGrid" class="market-grid"></div>'
    official_labeled = (
        '<div class="market-subtitle">Factores del OLS principal</div>'
        + official_grid
    )
    html = html.replace(official_grid, official_labeled, 1)

    experimental_block = f'''
<!-- {EXP_MARKER} -->
<div class="market-exp-block">
  <div class="market-subtitle market-exp-title">Nuevos tickers 60/30 · EXPERIMENTAL</div>
  <div id="marketExperimentalGrid" class="market-grid"></div>
  <div class="note market-exp-note">.INX, CPER, EEM, NDX, SPBLSCUP y USD/PEN. Se muestran para seguimiento del nuevo 60/30; todavía no reemplazan al OLS principal ni al challenger 60/30 vigente.</div>
</div>
'''
    html = html.replace(new_note, new_note + experimental_block, 1)

    experimental_css = r'''
<style id="experimentalMarketWatchlistCss">
.market-subtitle{margin:7px 0 8px;font-size:.76rem;font-weight:850;letter-spacing:.02em;color:#cbd5e1;text-transform:uppercase}
.market-exp-block{margin-top:16px;padding-top:12px;border-top:1px solid #243244}.market-exp-title{color:#93c5fd}.market-exp-note{margin-top:9px}.market-exp-block .market-source{white-space:normal;overflow:visible;text-overflow:clip;line-height:1.25}
</style>
'''
    html = html.replace('</head>', experimental_css + '</head>', 1)

    experimental_js = r'''
<script id="experimentalMarketWatchlistScript">
(function(){
  'use strict';
  const grid=()=>document.getElementById('marketExperimentalGrid');
  const cls=x=>Number(x)>0?'pos':Number(x)<0?'neg':'zero';
  const price=a=>{
    if(a.precio_actual===null||a.precio_actual===undefined||!Number.isFinite(Number(a.precio_actual)))return '—';
    const n=Number(a.precio_actual),digits=a.serie==='USD/PEN'?4:2;
    return n.toFixed(digits);
  };
  const ret=a=>{
    if(a.retorno===null||a.retorno===undefined||!Number.isFinite(Number(a.retorno)))return '<span class="zero">—</span>';
    const n=Number(a.retorno);
    return `<span class="${cls(n)}">${n>=0?'+':''}${(n*100).toFixed(2)}%</span>`;
  };
  function render(rows){
    const el=grid();if(!el)return;
    const wanted=['.INX','CPER','EEM','NDX','SPBLSCUP','USD/PEN'];
    const by=new Map((Array.isArray(rows)?rows:[]).map(x=>[x.serie,x]));
    el.innerHTML=wanted.map(name=>{
      const a=by.get(name)||{serie:name,precio_actual:null,retorno:null,estado:'Dato pendiente'};
      return `<div class="market-item"><div class="market-symbol">${a.serie}</div><div class="market-price">${price(a)}</div><div class="market-ret">${ret(a)}</div><div class="market-source">${a.estado||'Seguimiento experimental'}</div></div>`;
    }).join('');
  }
  function load(){
    fetch('data/live_market.json?experimental='+Date.now(),{cache:'no-store'})
      .then(r=>{if(!r.ok)throw new Error('HTTP '+r.status);return r.json()})
      .then(d=>render(d.experimental_assets))
      .catch(()=>render([]));
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',load,{once:true});else load();
  setTimeout(load,1200);
  setInterval(load,60000);
})();
</script>
'''
    html = html.replace('</body>', experimental_js + '</body>', 1)

# Mantener todas las lecturas del navegador en el mismo origen (GitHub Pages).
# El workflow intradía actualiza el JSON y solicita una nueva publicación de Pages.
raw_live = "https://raw.githubusercontent.com/rldaqp/afp-fondo3-monitor/migracion-github-actions/public/data/live_market.json"
html = html.replace(raw_live + "?ts='+Date.now()", "data/live_market.json?ts='+Date.now()")
html = html.replace(raw_live, "data/live_market.json")

HTML_PATH.write_text(html, encoding="utf-8")

# Última capa: el dato intradía solo puede reemplazar al cierre mientras esté
# vigente; además se incorpora al mismo gráfico y se evita caché de los JSON.
runpy.run_path(str(ROOT / "scripts" / "postprocess_live_consistency.py"), run_name="__main__")
print("Visor v4: gráfico limpio + USD/PEN notebook + nuevos tickers 60/30 + consistencia intradía/cierre.")
