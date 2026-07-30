from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML_PATH = ROOT / "public" / "index.html"
if not HTML_PATH.exists():
    raise FileNotFoundError(HTML_PATH)
html = HTML_PATH.read_text(encoding="utf-8")

vc_panel = (
    '<section class="panel"><div class="chart-title">VC real vs VC estimado</div>'
    '<div class="chart-controls vc-controls" aria-label="Rango del VC">'
    '<button id="vc7" data-days="7">7 días</button>'
    '<button id="vc15" data-days="15">15 días</button>'
    '<button id="vc30" data-days="30">30 días</button>'
    '<button id="vc90" data-days="90" class="primary">90 días</button>'
    '<button id="vcAll" data-days="all">Todo</button>'
    '</div><div id="vcChart" class="chart"></div></section>'
)
ret_panel = (
    '<section class="panel"><div class="chart-title">Retorno estimado diario del VC y señal</div>'
    '<div class="chart-controls ret-controls" aria-label="Rango de retornos">'
    '<button id="ret7" data-days="7">7 días</button>'
    '<button id="ret15" data-days="15">15 días</button>'
    '<button id="ret30" data-days="30">30 días</button>'
    '<button id="ret90" data-days="90" class="primary">90 días</button>'
    '<button id="retAll" data-days="all">Todo</button>'
    '</div><div id="signalChart" class="chart"></div></section>'
)

html = html.replace('<section class="panel"><div id="vcChart" class="chart"></div></section>', vc_panel, 1)
html = html.replace('<section class="panel"><div id="signalChart" class="chart"></div></section>', ret_panel, 1)

mobile_css = r'''
<style>
.chart-title{font-size:.96rem;font-weight:800;margin:0 0 8px;color:#f8fafc}
.chart-controls{display:flex;gap:7px;flex-wrap:wrap;margin-bottom:10px}
.chart-controls button{flex:1 1 auto;min-width:60px;border:1px solid #334155;background:#132238;color:#fff;border-radius:9px;padding:9px 8px;font-weight:700}
.chart-controls button.primary{background:#2563eb}
#ret{font-size:1rem;font-weight:800;color:#e2e8f0;margin-top:6px;line-height:1.25}
.monitor-help{margin:8px 0 10px;padding:10px 12px;border:1px solid #243244;border-radius:10px;background:#0b1728;color:#cbd5e1;font-size:.84rem;line-height:1.4}
#detail{margin-top:10px;line-height:1.5}
.market-head{display:flex;justify-content:space-between;gap:10px;align-items:flex-start;margin-bottom:10px}.market-mode{font-weight:850}.market-time{font-size:.74rem;color:#94a3b8;text-align:right;line-height:1.45}
.market-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}.market-item{background:#0b1728;border:1px solid #243244;border-radius:11px;padding:10px}.market-symbol{font-size:.82rem;color:#cbd5e1;font-weight:800}.market-price{font-size:1.05rem;font-weight:850;margin-top:3px}.market-ret{font-size:.9rem;font-weight:800;margin-top:3px}.market-source{font-size:.68rem;color:#94a3b8;margin-top:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.pos{color:#4ade80}.neg{color:#f87171}.zero{color:#fbbf24}
@media(max-width:700px){.wrap{padding:10px}.card,.panel{padding:11px}.value{font-size:1.2rem}#ret{font-size:1.02rem}.chart{height:300px}.chart-controls button{padding:9px 5px;font-size:.79rem}.market-grid{grid-template-columns:repeat(2,1fr)}.market-head{display:block}.market-time{text-align:left;margin-top:5px}}
</style>
'''
html = html.replace('</head>', mobile_css + '</head>', 1)

help_box = '<div id="monitorHelp" class="monitor-help"><b>Retorno estimado del VC:</b> variación diaria estimada por el OLS. Cada punto se dibuja desde el eje 0. Durante mercado abierto es provisional; al cierre usa cierres diarios.</div>'
marker = '</section>\n<section class="panel"><div class="tabs">'
if marker in html:
    html = html.replace(marker, '</section>' + help_box + '\n<section class="panel"><div class="tabs">', 1)

market_panel = '''
<section class="panel" id="marketPanel">
  <div class="market-head"><div><div class="chart-title">Mercado ahora</div><div id="marketMode" class="market-mode">Cargando…</div></div><div id="marketTime" class="market-time">—</div></div>
  <div id="marketGrid" class="market-grid"></div>
  <div class="note" style="margin-top:9px">SPY, NEM, FCX, EPU y MCHI: Yahoo Finance. Durante mercado abierto se muestran cotizaciones intradía; fuera de mercado se muestran cierres. USD/PEN: BCRP primero y Yahoo PEN=X solo como respaldo reciente.</div>
</section>
'''
html = html.replace('<section class="panel"><b>Auditoría</b>', market_panel + '<section class="panel"><b>Auditoría</b>', 1)

extra_js = r'''
<script>
(function(){
  let richSignals=[],allSeries=[],operationSeries=[],latestData=null,liveData=null,vcDays=90,retDays=90;
  const $=id=>document.getElementById(id),money=x=>new Intl.NumberFormat('es-PE',{style:'currency',currency:'PEN'}).format(x),pct=x=>(Number(x)*100).toFixed(2)+'%';
  const fmt=x=>{if(!x)return'—';let[y,m,d]=String(x).slice(0,10).split('-');return d+'/'+m+'/'+y};
  const signalColor=s=>s==='SUBE'?'#4ade80':s==='BAJA'?'#f87171':'#fbbf24',cls=x=>Number(x)>0?'pos':Number(x)<0?'neg':'zero';
  function cutoff(items,days){if(days==='all'||!items.length)return items;const ds=items.map(x=>x.fecha).sort(),mx=new Date(ds.at(-1)+'T00:00:00'),mn=new Date(mx);mn.setDate(mn.getDate()-Number(days));return items.filter(x=>new Date(x.fecha+'T00:00:00')>=mn)}
  function active(sel,days){document.querySelectorAll(sel+' button').forEach(b=>b.classList.toggle('primary',String(b.dataset.days)===String(days)))}
  function clock(iso,tz){try{return new Intl.DateTimeFormat('es-PE',{timeZone:tz,hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(iso))}catch(e){return'—'}}

  function renderVC(){
    let off=cutoff(allSeries.filter(x=>x.fuente==='SBS OFICIAL'),vcDays),est=cutoff(richSignals.filter(x=>x.vc_estimado!=null),vcDays);
    Plotly.react('vcChart',[
      {x:off.map(x=>x.fecha),y:off.map(x=>x.vc),mode:'lines+markers',name:'VC SBS real'},
      {x:est.map(x=>x.fecha),y:est.map(x=>x.vc_estimado),mode:'lines+markers',name:'VC estimado OLS',customdata:est.map(x=>x.senal),hovertemplate:'<b>%{x}</b><br>VC estimado: %{y:.7f}<br>Señal: %{customdata}<extra></extra>'}
    ],{title:vcDays==='all'?'Todo el historial':`Últimos ${vcDays} días`,paper_bgcolor:'#0f1b2d',plot_bgcolor:'#0f1b2d',font:{color:'#fff',size:11},margin:{l:48,r:18,t:45,b:45},legend:{orientation:'h'}},{responsive:true});active('.vc-controls',vcDays)
  }

  function renderSignals(){
    const p=cutoff(richSignals.filter(x=>x.ret_estimado!=null),retDays);
    const sx=[],sy=[];
    p.forEach(x=>{sx.push(x.fecha,x.fecha,null);sy.push(0,Number(x.ret_estimado)*100,null)});
    Plotly.react('signalChart',[
      {x:sx,y:sy,mode:'lines',name:'Tallo desde 0',line:{width:1},hoverinfo:'skip',showlegend:false},
      {x:p.map(x=>x.fecha),y:p.map(x=>Number(x.ret_estimado)*100),mode:'markers',name:'Retorno estimado VC',marker:{color:p.map(x=>signalColor(x.senal)),size:9},customdata:p.map(x=>x.senal),hovertemplate:'<b>%{x}</b><br>Retorno estimado VC: %{y:+.3f}%<br>Señal: %{customdata}<extra></extra>'}
    ],{title:retDays==='all'?'Todo el historial':`Últimos ${retDays} días`,paper_bgcolor:'#0f1b2d',plot_bgcolor:'#0f1b2d',font:{color:'#fff',size:11},margin:{l:48,r:18,t:45,b:45},shapes:[{type:'line',xref:'paper',x0:0,x1:1,y0:0,y1:0,line:{width:1}},{type:'line',xref:'paper',x0:0,x1:1,y0:.1,y1:.1,line:{dash:'dot'}},{type:'line',xref:'paper',x0:0,x1:1,y0:-.1,y1:-.1,line:{dash:'dot'}}]},{responsive:true});active('.ret-controls',retDays)
  }

  function renderTop(){if(!latestData)return;const live=liveData&&liveData.market_open&&String(liveData.mode).startsWith('INTRADÍA')&&Number.isFinite(Number(liveData.vc_estimated)),vc=live?Number(liveData.vc_estimated):Number(latestData.latest_estimated_vc),r=live?Number(liveData.return_estimated):Number(latestData.latest_return_estimated),s=live?liveData.signal:latestData.signal,d=live?liveData.signal_date:latestData.latest_estimate_date;$('estVc').textContent=vc.toFixed(7);$('estDate').textContent=fmt(d)+' · '+(live?'INTRADÍA PROVISIONAL':'CIERRE DIARIO');$('signal').textContent=s;$('signal').className='value signal '+(s==='SUBE'?'up':s==='BAJA'?'down':'flat');$('ret').textContent=`Retorno estimado VC (día): ${(r*100).toFixed(3)}%`;const h=$('monitorHelp');if(h)h.innerHTML=`<b>${live?'INTRADÍA PROVISIONAL':'CIERRE DIARIO'} · Retorno estimado del VC: ${(r*100).toFixed(3)}% · Señal ${s}</b><br>${live?'Usa el último corte intradía disponible de Yahoo y puede cambiar hasta el cierre.':'Usa cierres diarios disponibles. No es la rentabilidad acumulada de tu inversión.'}`}

  function renderMarket(){
    if(!liveData)return;
    $('marketMode').textContent=liveData.mode||'—';$('marketMode').className='market-mode '+(liveData.market_open?'pos':'zero');
    const stamps=(liveData.assets||[]).map(a=>a.timestamp).filter(x=>String(x||'').includes('T'));
    if(liveData.market_open&&stamps.length){const last=stamps.sort().at(-1);$('marketTime').innerHTML=`Corte Yahoo: ${clock(last,'America/New_York')} NY · ${clock(last,'America/Lima')} Lima<br>Visor actualizado: ${clock(liveData.generated_at_lima,'America/Lima')} Lima`}
    else{$('marketTime').innerHTML=`Cierre utilizado: ${fmt(liveData.signal_date)}<br>Visor actualizado: ${clock(liveData.generated_at_lima,'America/Lima')} Lima`}
    $('marketGrid').innerHTML=(liveData.assets||[]).map(a=>`<div class="market-item"><div class="market-symbol">${a.serie}</div><div class="market-price">${Number(a.precio_actual).toFixed(a.serie==='USD_PEN'?4:2)}</div><div class="market-ret ${cls(a.retorno)}">${Number(a.retorno)>=0?'+':''}${(Number(a.retorno)*100).toFixed(2)}%</div><div class="market-source">${a.estado||''}</div></div>`).join('')||'<div class="note">Cotización intradía no disponible; se mantiene el último cierre.</div>';renderTop()
  }

  // El gráfico y la simulación comparten todos los VC oficiales SBS; la serie de
  // operación añade después los VC pendientes del modelo y se valida contra series.json.
  function calcNotebook(){
    const bt=document.querySelector('.tabs button.active'),mode=bt?bt.dataset.mode:'monitor';if(mode==='monitor')return;
    const entryDate=$('entry').value,capital=Number($('capital').value);if(!entryDate||!capital||capital<=0){$('detail').textContent='Completa fecha y capital.';return}
    const exitDate=mode==='closed'?$('exit').value:operationSeries.at(-1)?.fecha;
    let interval=operationSeries.filter(x=>x.fecha>=entryDate&&x.fecha<=exitDate&&Number.isFinite(Number(x.vc)));
    if(!interval.length){$('detail').textContent='No existe un valor cuota disponible en la línea temporal del monitor entre las fechas seleccionadas.';return}
    const a=interval[0];let b=interval.at(-1),liveUsed=false;
    if(mode==='inside'&&liveData&&liveData.market_open&&String(liveData.mode).startsWith('INTRADÍA')&&Number.isFinite(Number(liveData.vc_estimated))){b={fecha:liveData.signal_date,vc:Number(liveData.vc_estimated),fuente:'MODELO OLS · INTRADÍA PROVISIONAL'};liveUsed=true}
    const vi=Number(a.vc),vo=Number(b.vc),units=capital/vi,final=units*vo,gain=final-capital,rent=final/capital-1;
    $('mCapital').textContent=money(capital);$('mFinal').textContent=money(final);$('mGain').textContent=money(gain);$('mRent').textContent=pct(rent);
    const provisional=liveUsed||b.fuente!=='SBS OFICIAL',tag=provisional?'RESULTADO PROVISIONAL · VC MODELO':'RESULTADO CON VC OFICIAL SBS',adjusted=(a.fecha!==entryDate||(mode==='closed'&&b.fecha!==$('exit').value))?' · Fechas ajustadas a las observaciones disponibles del monitor.':'';
    $('detail').innerHTML=`<b>${tag}</b><br>Entrada efectiva: ${fmt(a.fecha)} · VC ${vi.toFixed(7)} · ${a.fuente}<br>${mode==='closed'?'Salida':'Valoración'} efectiva: ${fmt(b.fecha)} · VC ${vo.toFixed(7)} · ${b.fuente}<br>Número de cuotas: ${units.toFixed(6)}<br>Fórmula notebook: ${money(capital)} × (${vo.toFixed(7)} / ${vi.toFixed(7)}) = <b>${money(final)}</b><br>Ganancia/pérdida: <b>${money(gain)}</b>${adjusted}${mode==='closed'?'<br><b>Operación cerrada: no se utiliza intradía.</b>':''}`;
    let g=interval.slice();if(liveUsed)g=[...g,b];Plotly.react('opChart',[{x:g.map(x=>x.fecha),y:g.map(x=>Number(x.vc)),mode:'lines+markers',name:'VC'},{x:g.map(x=>x.fecha),y:g.map(x=>units*Number(x.vc)-capital),mode:'lines+markers',name:'Ganancia',yaxis:'y2'}],{title:'Valor cuota y ganancia/pérdida',paper_bgcolor:'#0f1b2d',plot_bgcolor:'#0f1b2d',font:{color:'#fff',size:11},margin:{l:48,r:48,t:55,b:45},yaxis2:{overlaying:'y',side:'right'},legend:{orientation:'h'}},{responsive:true})
  }

  function loadLive(){return fetch('data/live_market.json?ts='+Date.now(),{cache:'no-store'}).then(r=>r.json()).then(x=>{liveData=x;renderMarket();return x}).catch(()=>null)}
  Promise.all([
    fetch('data/signals.json',{cache:'no-store'}).then(r=>r.json()),
    fetch('data/series.json',{cache:'no-store'}).then(r=>r.json()),
    fetch('data/operation_series.json',{cache:'no-store'}).then(r=>r.json()),
    fetch('data/latest.json',{cache:'no-store'}).then(r=>r.json()),
    loadLive()
  ]).then(([sig,ser,op,latest])=>{
    richSignals=sig.sort((a,b)=>a.fecha.localeCompare(b.fecha));allSeries=ser.sort((a,b)=>a.fecha.localeCompare(b.fecha));operationSeries=op.sort((a,b)=>a.fecha.localeCompare(b.fecha));latestData=latest;
    renderVC();renderSignals();renderTop();renderMarket();
    document.querySelectorAll('.vc-controls button').forEach(b=>b.onclick=()=>{vcDays=b.dataset.days==='all'?'all':Number(b.dataset.days);renderVC()});
    document.querySelectorAll('.ret-controls button').forEach(b=>b.onclick=()=>{retDays=b.dataset.days==='all'?'all':Number(b.dataset.days);renderSignals()});
    $('calc').onclick=calcNotebook;
    if(operationSeries.length){$('entry').min=operationSeries[0].fecha;$('entry').max=operationSeries.at(-1).fecha;$('exit').min=operationSeries[0].fecha;$('exit').max=operationSeries.at(-1).fecha}
    setInterval(loadLive,60000)
  }).catch(e=>{const box=$('error');if(box)box.innerHTML='<div class="error">No se pudieron cargar resultados: '+e+'</div>'});
})();
</script>
'''

html = html.replace('</body>', extra_js + '</body>', 1)
HTML_PATH.write_text(html, encoding="utf-8")
print("Visor móvil v3: gráfico y simulación usan todos los VC SBS + pendientes.")
