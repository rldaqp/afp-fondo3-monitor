from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML_PATH = ROOT / "public" / "index.html"
html = HTML_PATH.read_text(encoding="utf-8")

if "MODEL_INSIGHTS_UI_V1" not in html:
    css = r'''
<!-- MODEL_INSIGHTS_UI_V1 -->
<style id="modelInsightsStyles">
.insight-head{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:9px}
.insight-title{font-size:.96rem;font-weight:850}.insight-badge{padding:4px 8px;border-radius:999px;font-size:.7rem;font-weight:850;border:1px solid #334155}
.insight-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}.insight-card{background:#0b1728;border:1px solid #243244;border-radius:11px;padding:10px;min-width:0}.insight-label{font-size:.7rem;color:#94a3b8}.insight-value{font-size:1.02rem;font-weight:850;margin-top:4px;overflow-wrap:anywhere}.insight-sub{font-size:.68rem;color:#94a3b8;margin-top:3px;line-height:1.3}
.insight-details{margin-top:10px;border-top:1px solid #243244;padding-top:8px}.insight-details summary{cursor:pointer;font-size:.78rem;font-weight:800;color:#cbd5e1;padding:5px 0}.factor-list{display:grid;gap:7px;margin-top:9px}.factor-row{display:grid;grid-template-columns:64px 1fr 58px;gap:7px;align-items:center;font-size:.72rem}.factor-track{height:7px;background:#172338;border-radius:999px;overflow:hidden}.factor-fill{height:100%;border-radius:999px;background:#64748b}.factor-fill.posbar{background:#22c55e}.factor-fill.negbar{background:#ef4444}.factor-value{text-align:right;font-variant-numeric:tabular-nums}.perf-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:7px;margin-top:10px}.perf-item{background:#0b1728;border:1px solid #243244;border-radius:9px;padding:8px}.perf-item b{display:block;font-size:.82rem}.perf-item span{font-size:.68rem;color:#94a3b8}.quality-ok{color:#4ade80}.quality-warn{color:#fbbf24}.quality-bad{color:#f87171}
@media(max-width:700px){.insight-grid{grid-template-columns:repeat(2,1fr)}.insight-card{padding:9px}.insight-value{font-size:1.05rem}.factor-row{grid-template-columns:58px 1fr 55px}}
@media(max-width:390px){.insight-grid{grid-template-columns:1fr 1fr;gap:6px}.insight-label{font-size:.66rem}.insight-sub{font-size:.64rem}.factor-row{grid-template-columns:54px 1fr 51px;gap:5px}}
</style>
'''
    html = html.replace("</head>", css + "</head>", 1)

    panel = r'''
<section class="panel" id="modelInsightsPanel">
  <div class="insight-head"><div class="insight-title">Confianza y calidad del modelo</div><div id="qualityBadge" class="insight-badge">Cargando…</div></div>
  <div class="insight-grid">
    <div class="insight-card"><div class="insight-label">Acierto de esta señal</div><div class="insight-value" id="confidenceValue">—</div><div class="insight-sub" id="confidenceSub">Histórico reciente</div></div>
    <div class="insight-card"><div class="insight-label">Banda histórica 80%</div><div class="insight-value" id="bandValue">—</div><div class="insight-sub">Error empírico del VC</div></div>
    <div class="insight-card"><div class="insight-label">Calidad de datos</div><div class="insight-value" id="qualityValue">—</div><div class="insight-sub" id="qualitySub">Ventana y fuentes</div></div>
    <div class="insight-card"><div class="insight-label">OLS vs sin cambio</div><div class="insight-value" id="benchmarkValue">—</div><div class="insight-sub">Comparación por MAE</div></div>
  </div>
  <details class="insight-details"><summary>Ver qué mueve la señal y rendimiento</summary>
    <div class="note">Aporte aproximado de cada factor al retorno estimado: coeficiente × retorno observado.</div>
    <div id="factorList" class="factor-list"></div>
    <div id="perfGrid" class="perf-grid"></div>
    <div id="qualityNotes" class="note" style="margin-top:9px"></div>
  </details>
</section>
'''
    marker = '<section class="panel"><div class="tabs">'
    if marker not in html:
        raise RuntimeError("No se encontró punto de inserción del panel móvil")
    html = html.replace(marker, panel + marker, 1)

# Añadir el objeto de insights al estado del visor.
html = html.replace(
    "let richSignals=[],allSeries=[],operationSeries=[],latestData=null,liveData=null,vcDays=90,retDays=90;",
    "let richSignals=[],allSeries=[],operationSeries=[],latestData=null,liveData=null,modelInsights=null,vcDays=90,retDays=90;",
    1,
)

# Banda empírica alrededor de la estimación OLS. Se amplía con sqrt(horizonte)
# para predicciones encadenadas pendientes; el histórico permanece a un paso.
new_render_vc = r'''  function renderVC(){
    let off=cutoff(allSeries.filter(x=>x.fuente==='SBS OFICIAL'),vcDays),est=cutoff(richSignals.filter(x=>x.vc_estimado!=null),vcDays);
    const q=modelInsights&&modelInsights.uncertainty?Number(modelInsights.uncertainty.relative_q80||0):0;
    let pendingStep=0,lower=[],upper=[];
    est.forEach(x=>{let scale=1;if(x.tipo==='PENDIENTE'){pendingStep+=1;scale=Math.sqrt(pendingStep)}const v=Number(x.vc_estimado);lower.push(v*(1-q*scale));upper.push(v*(1+q*scale))});
    const traces=[];
    if(q>0&&est.length){traces.push(
      {x:est.map(x=>x.fecha),y:lower,mode:'lines',line:{width:0},hoverinfo:'skip',showlegend:false},
      {x:est.map(x=>x.fecha),y:upper,mode:'lines',line:{width:0},fill:'tonexty',fillcolor:'rgba(96,165,250,.12)',name:'Banda histórica 80%',hoverinfo:'skip'}
    )}
    traces.push(
      {x:off.map(x=>x.fecha),y:off.map(x=>x.vc),mode:'lines+markers',name:'VC SBS real'},
      {x:est.map(x=>x.fecha),y:est.map(x=>x.vc_estimado),mode:'lines+markers',name:'VC estimado OLS',customdata:est.map(x=>x.senal),hovertemplate:'<b>%{x}</b><br>VC estimado: %{y:.7f}<br>Señal: %{customdata}<extra></extra>'}
    );
    Plotly.react('vcChart',traces,{title:vcDays==='all'?'Todo el historial':`Últimos ${vcDays} días`,paper_bgcolor:'#0f1b2d',plot_bgcolor:'#0f1b2d',font:{color:'#fff',size:11},margin:{l:48,r:18,t:45,b:45},legend:{orientation:'h',font:{size:10}}},{responsive:true});active('.vc-controls',vcDays)
  }'''
html, n = re.subn(
    r"  function renderVC\(\)\{.*?\n  \}\n\n  function renderSignals\(\)\{",
    new_render_vc + "\n\n  function renderSignals(){",
    html,
    count=1,
    flags=re.S,
)
if n != 1:
    raise RuntimeError(f"No se pudo sustituir renderVC: {n}")

# Render móvil compacto de confianza, calidad, benchmarks y contribuciones.
insights_js = r'''
  function insightPct(x,d=1){return x==null||!Number.isFinite(Number(x))?'—':(Number(x)*100).toFixed(d)+'%'}
  function liveContributions(){
    if(!(liveData&&liveData.market_open&&latestData&&latestData.coefficients))return null;
    const beta=latestData.coefficients,map={SPY:'ret_SPY',NEM:'ret_NEM',FCX:'ret_FCX',EPU:'ret_EPU',MCHI:'ret_MCHI',EEM:'ret_EEM',USD_PEN:'ret_USD_PEN'},out=[];
    out.push({label:'Base',contribution_pp:Number(beta.intercept||0)*100});
    (liveData.assets||[]).forEach(a=>{const k=map[a.serie],r=Number(a.retorno_modelo);if(k&&Number.isFinite(r)&&Number.isFinite(Number(beta[k])))out.push({label:a.serie==='USD_PEN'?'USD/PEN':a.serie,contribution_pp:Number(beta[k])*r*100})});
    return out.sort((a,b)=>Math.abs(b.contribution_pp)-Math.abs(a.contribution_pp));
  }
  function renderInsights(){
    if(!modelInsights)return;
    const c=modelInsights.confidence||{},u=modelInsights.uncertainty||{},q=modelInsights.quality||{},b=modelInsights.benchmarks||{},p=modelInsights.performance||{};
    const acc=c.historical_accuracy;
    $('confidenceValue').textContent=acc==null?'—':(Number(acc)*100).toFixed(0)+'% · '+(c.label||'');
    $('confidenceSub').textContent=`${modelInsights.current_signal||'—'} · n=${c.n||0} · no es probabilidad garantizada`;
    $('bandValue').textContent=u.relative_q80==null?'—':'±'+(Number(u.relative_q80)*100).toFixed(2)+'%';
    $('qualityValue').textContent=q.status||'—';
    $('qualitySub').textContent=`OLS ${q.training_n||0}/90 · FX ${q.fx_provisional?'provisional':'confirmado'}`;
    const qc=q.status==='OK'?'quality-ok':q.status==='REVISAR'?'quality-bad':'quality-warn';
    $('qualityValue').className='insight-value '+qc;$('qualityBadge').className='insight-badge '+qc;$('qualityBadge').textContent=q.status||'—';
    const imp=b.ols_mae_improvement_vs_zero;
    $('benchmarkValue').textContent=imp==null?'—':(imp>=0?'Mejor ':'Peor ')+(Math.abs(Number(imp))*100).toFixed(0)+'%';
    const contrib=liveContributions()||(modelInsights.contributions||[]);
    const max=Math.max(...contrib.map(x=>Math.abs(Number(x.contribution_pp)||0)),0.0001);
    $('factorList').innerHTML=contrib.map(x=>{const v=Number(x.contribution_pp)||0,w=Math.max(2,Math.abs(v)/max*100),cl=v>0?'posbar':v<0?'negbar':'';return `<div class="factor-row"><b>${x.label}</b><div class="factor-track"><div class="factor-fill ${cl}" style="width:${w.toFixed(1)}%"></div></div><div class="factor-value ${v>0?'pos':v<0?'neg':'zero'}">${v>=0?'+':''}${v.toFixed(3)} pp</div></div>`}).join('')||'<div class="note">Sin contribuciones disponibles.</div>';
    const items=[
      ['Acierto global',insightPct(p.classification_accuracy,0)],
      ['MAE retorno',p.mae_return_pp==null?'—':Number(p.mae_return_pp).toFixed(2)+' pp'],
      ['Acierto SUBE',insightPct(p.sube_accuracy,0)+' · n='+Number(p.sube_n||0)],
      ['Acierto BAJA',insightPct(p.baja_accuracy,0)+' · n='+Number(p.baja_n||0)],
      ['Base sin cambio',b.zero_change_mae_pp==null?'—':Number(b.zero_change_mae_pp).toFixed(2)+' pp MAE'],
      ['Dirección previa',insightPct(b.previous_direction_accuracy,0)]
    ];
    $('perfGrid').innerHTML=items.map(x=>`<div class="perf-item"><b>${x[1]}</b><span>${x[0]}</span></div>`).join('');
    const notes=[...(q.critical||[]),...(q.warnings||[])];$('qualityNotes').textContent=notes.length?notes.join(' · '):'Controles de integridad sin alertas.';
  }
'''
needle = "  function renderMarket(){"
if insights_js.strip() not in html:
    if needle not in html:
        raise RuntimeError("No se encontró renderMarket")
    html = html.replace(needle, insights_js + "\n" + needle, 1)

# Cada actualización live vuelve a calcular contribuciones si el mercado está abierto.
html = html.replace("renderTop()\n  }", "renderTop();renderInsights()\n  }", 1)

# Cargar model_insights.json junto con los otros datos del visor.
old_promise = """    fetch('data/latest.json',{cache:'no-store'}).then(r=>r.json()),\n    loadLive()\n  ]).then(([sig,ser,op,latest])=>{\n    richSignals=sig.sort((a,b)=>a.fecha.localeCompare(b.fecha));allSeries=ser.sort((a,b)=>a.fecha.localeCompare(b.fecha));operationSeries=op.sort((a,b)=>a.fecha.localeCompare(b.fecha));latestData=latest;\n    renderVC();renderSignals();renderTop();renderMarket();"""
new_promise = """    fetch('data/latest.json',{cache:'no-store'}).then(r=>r.json()),\n    fetch('data/model_insights.json',{cache:'no-store'}).then(r=>r.json()),\n    loadLive()\n  ]).then(([sig,ser,op,latest,insights])=>{\n    richSignals=sig.sort((a,b)=>a.fecha.localeCompare(b.fecha));allSeries=ser.sort((a,b)=>a.fecha.localeCompare(b.fecha));operationSeries=op.sort((a,b)=>a.fecha.localeCompare(b.fecha));latestData=latest;modelInsights=insights;\n    renderVC();renderSignals();renderTop();renderMarket();renderInsights();"""
if old_promise not in html:
    raise RuntimeError("No se encontró Promise principal para integrar insights")
html = html.replace(old_promise, new_promise, 1)

HTML_PATH.write_text(html, encoding="utf-8")
print("Visor móvil: confianza + banda 80% + factores + calidad + rendimiento.")
