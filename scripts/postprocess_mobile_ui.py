from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML_PATH = ROOT / "public" / "index.html"

if not HTML_PATH.exists():
    raise FileNotFoundError(HTML_PATH)

html = HTML_PATH.read_text(encoding="utf-8")

# Controles compactos para celular: 7 / 15 / 30 / 90 días / todo.
controls = (
    '<section class="panel"><div class="chart-controls" aria-label="Rango del gráfico">'
    '<button id="vc7" data-days="7">7 días</button>'
    '<button id="vc15" data-days="15">15 días</button>'
    '<button id="vc30" data-days="30">30 días</button>'
    '<button id="vc90" data-days="90" class="primary">90 días</button>'
    '<button id="vcAll" data-days="all">Todo</button>'
    '</div><div id="vcChart" class="chart"></div></section>'
)
html = re.sub(
    r'<section class="panel"><div class="chart-controls">.*?<div id="vcChart" class="chart"></div></section>',
    controls,
    html,
    count=1,
    flags=re.S,
)

# El script enriquecido anterior se reemplaza por una sola versión para evitar
# que dos renderizadores compitan entre sí.
html = re.sub(
    r'\n<script>\s*\(function\(\)\{\s*let richSignals=.*?</script>\s*',
    '\n',
    html,
    count=1,
    flags=re.S,
)

# Mejora de lectura en celular y explicación del retorno.
mobile_css = r'''
<style>
.chart-controls{display:flex;gap:7px;flex-wrap:wrap;margin-bottom:10px}
.chart-controls button{flex:1 1 auto;min-width:64px;border:1px solid #334155;background:#132238;color:#fff;border-radius:9px;padding:9px 10px;font-weight:700}
.chart-controls button.primary{background:#2563eb}
#ret{font-size:1rem;font-weight:800;color:#e2e8f0;margin-top:6px;line-height:1.25}
.monitor-help{margin:8px 0 2px;padding:10px 12px;border:1px solid #243244;border-radius:10px;background:#0b1728;color:#cbd5e1;font-size:.84rem;line-height:1.35}
#detail{margin-top:10px;line-height:1.45}
@media(max-width:700px){
  .wrap{padding:10px}.card,.panel{padding:11px}.value{font-size:1.2rem}
  #ret{font-size:1.02rem}.chart{height:300px}.chart-controls button{padding:9px 7px;font-size:.82rem}
}
</style>
'''
html = html.replace('</head>', mobile_css + '</head>', 1)

help_box = (
    '<div id="monitorHelp" class="monitor-help">'
    '<b>Retorno estimado del VC (día):</b> es la variación diaria que el modelo OLS '
    'estima para el valor cuota de la fecha mostrada. No es la rentabilidad acumulada de tu inversión.'
    '</div>'
)
marker = '</section>\n<section class="panel"><div class="tabs">'
if marker in html:
    html = html.replace(marker, '</section>' + help_box + '\n<section class="panel"><div class="tabs">', 1)

extra_js = r'''
<script>
(function(){
  let richSignals=[], allSeries=[], vcDays=90;
  const $=id=>document.getElementById(id);
  const money=x=>new Intl.NumberFormat('es-PE',{style:'currency',currency:'PEN'}).format(x);
  const pct=x=>(x*100).toFixed(2)+'%';
  const fmt=x=>{if(!x)return'—';let[y,m,d]=String(x).slice(0,10).split('-');return d+'/'+m+'/'+y};
  const signalColor=s=>s==='SUBE'?'#4ade80':s==='BAJA'?'#f87171':'#fbbf24';

  function cutoff(items,days){
    if(days==='all'||!items.length)return items;
    const dates=items.map(x=>x.fecha).sort();
    const max=new Date(dates.at(-1)+'T00:00:00');
    const min=new Date(max); min.setDate(min.getDate()-Number(days));
    return items.filter(x=>new Date(x.fecha+'T00:00:00')>=min);
  }

  function renderVC(){
    let official=allSeries.filter(x=>x.fuente==='SBS OFICIAL');
    let estimated=richSignals.filter(x=>x.vc_estimado!=null);
    official=cutoff(official,vcDays); estimated=cutoff(estimated,vcDays);
    const title=vcDays==='all'?'VC real vs estimado · todo el historial':`VC real vs estimado · últimos ${vcDays} días`;
    Plotly.react('vcChart',[
      {x:official.map(x=>x.fecha),y:official.map(x=>x.vc),mode:'lines+markers',name:'VC SBS real'},
      {x:estimated.map(x=>x.fecha),y:estimated.map(x=>x.vc_estimado),mode:'lines+markers',name:'VC estimado OLS',customdata:estimated.map(x=>x.senal),hovertemplate:'<b>%{x}</b><br>VC estimado: %{y:.7f}<br>Señal: %{customdata}<extra></extra>'}
    ],{title,paper_bgcolor:'#0f1b2d',plot_bgcolor:'#0f1b2d',font:{color:'#fff',size:11},margin:{l:48,r:18,t:55,b:45},legend:{orientation:'h'}},{responsive:true});
    document.querySelectorAll('.chart-controls button').forEach(b=>b.classList.toggle('primary',String(b.dataset.days)===String(vcDays)));
  }

  function renderSignals(){
    const points=richSignals.filter(x=>x.ret_estimado!=null).slice(-90);
    Plotly.react('signalChart',[{
      x:points.map(x=>x.fecha),y:points.map(x=>x.ret_estimado*100),mode:'lines+markers',name:'Retorno estimado VC',
      marker:{color:points.map(x=>signalColor(x.senal)),size:8},customdata:points.map(x=>x.senal),
      hovertemplate:'<b>%{x}</b><br>Retorno estimado VC: %{y:+.3f}%<br>Señal: %{customdata}<extra></extra>'
    }],{title:'Retorno estimado diario del VC y señal · últimas 90 observaciones',paper_bgcolor:'#0f1b2d',plot_bgcolor:'#0f1b2d',font:{color:'#fff',size:11},margin:{l:48,r:18,t:55,b:45},shapes:[{type:'line',xref:'paper',x0:0,x1:1,y0:.1,y1:.1,line:{dash:'dot'}},{type:'line',xref:'paper',x0:0,x1:1,y0:-.1,y1:-.1,line:{dash:'dot'}}]},{responsive:true});
  }

  // Réplica de la regla del notebook:
  // 1) filtrar desde la fecha de entrada hasta la fecha de salida;
  // 2) entrada = primera observación disponible del intervalo;
  // 3) salida = última observación disponible del intervalo;
  // 4) monto = capital * VC_salida / VC_entrada.
  function calcNotebook(){
    const active=document.querySelector('.tabs button.active');
    const mode=active?active.dataset.mode:'monitor';
    if(mode==='monitor')return;
    const entryDate=$('entry').value;
    const exitDate=mode==='closed'?$('exit').value:allSeries.at(-1)?.fecha;
    const capital=Number($('capital').value);
    if(!entryDate||!exitDate||!capital||capital<=0){$('detail').textContent='Completa fechas y capital.';return;}

    const interval=allSeries.filter(x=>x.fecha>=entryDate&&x.fecha<=exitDate&&Number.isFinite(Number(x.vc)));
    if(!interval.length){$('detail').textContent='No existe un valor cuota disponible entre las fechas seleccionadas.';return;}
    const a=interval[0], b=interval.at(-1);
    if(b.fecha<a.fecha){$('detail').textContent='La salida no puede ser anterior a la entrada.';return;}

    const vcIn=Number(a.vc), vcOut=Number(b.vc);
    const units=capital/vcIn;
    const final=capital*(vcOut/vcIn);
    const gain=final-capital;
    const rent=final/capital-1;
    $('mCapital').textContent=money(capital);
    $('mFinal').textContent=money(final);
    $('mGain').textContent=money(gain);
    $('mRent').textContent=pct(rent);
    const provisional=b.fuente!=='SBS OFICIAL';
    const tag=provisional?'RESULTADO PROVISIONAL · VC MODELO':'RESULTADO CON VC OFICIAL SBS';
    const adjusted=(a.fecha!==entryDate||b.fecha!==exitDate)?' · Se ajustaron las fechas a observaciones disponibles.':'';
    $('detail').innerHTML=`<b>${tag}</b><br>Entrada efectiva: ${fmt(a.fecha)} · VC ${vcIn.toFixed(7)} · ${a.fuente}<br>Salida/valoración efectiva: ${fmt(b.fecha)} · VC ${vcOut.toFixed(7)} · ${b.fuente}<br>Fórmula: ${money(capital)} × (${vcOut.toFixed(7)} / ${vcIn.toFixed(7)}) = <b>${money(final)}</b>${adjusted}`;

    Plotly.react('opChart',[
      {x:interval.map(x=>x.fecha),y:interval.map(x=>Number(x.vc)),mode:'lines+markers',name:'VC'},
      {x:interval.map(x=>x.fecha),y:interval.map(x=>units*Number(x.vc)-capital),mode:'lines+markers',name:'Ganancia',yaxis:'y2'}
    ],{title:'Valor cuota y ganancia/pérdida',paper_bgcolor:'#0f1b2d',plot_bgcolor:'#0f1b2d',font:{color:'#fff',size:11},margin:{l:48,r:48,t:55,b:45},yaxis2:{overlaying:'y',side:'right'},legend:{orientation:'h'}},{responsive:true});
  }

  Promise.all([
    fetch('data/signals.json',{cache:'no-store'}).then(r=>r.json()),
    fetch('data/series.json',{cache:'no-store'}).then(r=>r.json()),
    fetch('data/latest.json',{cache:'no-store'}).then(r=>r.json())
  ]).then(([sig,ser,latest])=>{
    richSignals=sig.sort((a,b)=>a.fecha.localeCompare(b.fecha));
    allSeries=ser.sort((a,b)=>a.fecha.localeCompare(b.fecha));
    renderVC();renderSignals();
    document.querySelectorAll('.chart-controls button').forEach(b=>b.onclick=()=>{vcDays=b.dataset.days==='all'?'all':Number(b.dataset.days);renderVC()});
    $('calc').onclick=calcNotebook;
    $('ret').textContent=`Retorno estimado VC (día): ${(Number(latest.latest_return_estimated)*100).toFixed(3)}%`;
    const help=$('monitorHelp');
    if(help) help.innerHTML=`<b>Retorno estimado del VC (día): ${(Number(latest.latest_return_estimated)*100).toFixed(3)}%</b><br>Es la variación diaria estimada por el OLS para el valor cuota del ${fmt(latest.latest_estimate_date)}. No es tu rentabilidad acumulada. La señal asociada es <b>${latest.signal}</b>.`;
  }).catch(e=>{const box=$('error');if(box)box.innerHTML='<div class="error">No se pudieron cargar resultados: '+e+'</div>'});
})();
</script>
'''
html = html.replace('</body>', extra_js + '</body>', 1)
HTML_PATH.write_text(html, encoding="utf-8")
print('Visor móvil postprocesado: cálculo tipo notebook + rangos 7/15/30/90/Todo.')
