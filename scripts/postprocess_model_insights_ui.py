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

if "HUBER_CHALLENGER_UI_V1" not in html:
    challenger_css = r'''
<!-- HUBER_CHALLENGER_UI_V1 -->
<style id="huberChallengerStyles">
.challenger-box{margin-top:9px;padding:10px 11px;border:1px solid #334155;border-radius:11px;background:#101d31;display:flex;justify-content:space-between;gap:12px;align-items:center}
.challenger-kicker{font-size:.68rem;color:#94a3b8;font-weight:800;text-transform:uppercase;letter-spacing:.04em}.challenger-value{font-size:1.05rem;font-weight:900;margin-top:3px}.challenger-sub{font-size:.7rem;color:#cbd5e1;text-align:right;line-height:1.35;max-width:58%}.challenger-warn{color:#fbbf24}.challenger-ok{color:#4ade80}.challenger-diff{color:#f59e0b}
@media(max-width:700px){.challenger-box{display:block}.challenger-sub{text-align:left;max-width:none;margin-top:5px}}
</style>
'''
    html = html.replace("</head>", challenger_css + "</head>", 1)

challenger_panel = r'''
  <div class="challenger-box" id="huberChallengerBox">
    <div><div class="challenger-kicker">Challenger Huber · paralelo</div><div class="challenger-value" id="huberValue">—</div></div>
    <div class="challenger-sub" id="huberSub">OLS continúa como señal principal.</div>
  </div>
'''
if 'id="huberChallengerBox"' not in html:
    marker = '  <details class="insight-details">'
    if marker not in html:
        raise RuntimeError("No se encontró el panel de insights para insertar Huber")
    html = html.replace(marker, challenger_panel + marker, 1)

html = html.replace(
    "let richSignals=[],allSeries=[],operationSeries=[],latestData=null,liveData=null,vcDays=90,retDays=90;",
    "let richSignals=[],allSeries=[],operationSeries=[],latestData=null,liveData=null,modelInsights=null,vcDays=90,retDays=90;",
    1,
)

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

insights_js = r'''  function insightPct(x,d=1){return x==null||!Number.isFinite(Number(x))?'—':(Number(x)*100).toFixed(d)+'%'}
  function liveContributions(){
    if(!(liveData&&liveData.market_open&&latestData&&latestData.coefficients))return null;
    const beta=latestData.coefficients,map={SPY:'ret_SPY',NEM:'ret_NEM',FCX:'ret_FCX',EPU:'ret_EPU',MCHI:'ret_MCHI',EEM:'ret_EEM',USD_PEN:'ret_USD_PEN'},out=[];
    out.push({label:'Base',contribution_pp:Number(beta.intercept||0)*100});
    (liveData.assets||[]).forEach(a=>{const k=map[a.serie],r=Number(a.retorno_modelo);if(k&&Number.isFinite(r)&&Number.isFinite(Number(beta[k])))out.push({label:a.serie==='USD_PEN'?'USD/PEN':a.serie,contribution_pp:Number(beta[k])*r*100})});
    return out.sort((a,b)=>Math.abs(b.contribution_pp)-Math.abs(a.contribution_pp));
  }
  function classifyModelReturn(r){return Number(r)>.001?'SUBE':Number(r)<-.001?'BAJA':'NEUTRO'}
  function currentHuber(){
    const h=modelInsights&&modelInsights.challenger_huber;if(!h||h.status!=='CHALLENGER ACTIVO')return null;
    if(liveData&&liveData.market_open&&h.coefficients){
      const beta=h.coefficients,map={SPY:'ret_SPY',NEM:'ret_NEM',FCX:'ret_FCX',EPU:'ret_EPU',MCHI:'ret_MCHI',EEM:'ret_EEM',USD_PEN:'ret_USD_PEN'};
      let r=Number(beta.intercept||0),used=0;
      (liveData.assets||[]).forEach(a=>{const k=map[a.serie],v=Number(a.retorno_modelo);if(k&&Number.isFinite(v)&&Number.isFinite(Number(beta[k]))){r+=Number(beta[k])*v;used+=1}});
      if(used===7)return {fecha:liveData.signal_date,ret_estimado:r,senal:classifyModelReturn(r),live:true};
    }
    return h.current||null;
  }
  function renderInsights(){
    if(!modelInsights)return;
    const c=modelInsights.confidence||{},u=modelInsights.uncertainty||{},q=modelInsights.quality||{},b=modelInsights.benchmarks||{},p=modelInsights.performance||{},h=modelInsights.challenger_huber||{},hp=h.performance||{},hc=h.comparison_vs_ols||{};
    const acc=c.historical_accuracy;
    $('confidenceValue').textContent=acc==null?'—':(Number(acc)*100).toFixed(0)+'% · '+(c.label||'');
    $('confidenceSub').textContent=`${modelInsights.current_signal||'—'} · n=${c.n||0} · no es probabilidad garantizada`;
    $('bandValue').textContent=u.relative_q80==null?'—':'±'+(Number(u.relative_q80)*100).toFixed(2)+'%';
    $('qualityValue').textContent=q.status||'—';
    $('qualitySub').textContent=`OLS ${q.training_n||0}/90 · Huber ${h.training&&h.training.n?h.training.n:0}/90 · FX ${q.fx_provisional?'provisional':'confirmado'}`;
    const qc=q.status==='OK'?'quality-ok':q.status==='REVISAR'?'quality-bad':'quality-warn';
    $('qualityValue').className='insight-value '+qc;$('qualityBadge').className='insight-badge '+qc;$('qualityBadge').textContent=q.status||'—';
    const imp=b.ols_mae_improvement_vs_zero;
    $('benchmarkValue').textContent=imp==null?'—':(imp>=0?'Mejor ':'Peor ')+(Math.abs(Number(imp))*100).toFixed(0)+'%';

    const hub=currentHuber(),olsSignal=liveData&&liveData.market_open?liveData.signal:(latestData?latestData.signal:modelInsights.current_signal);
    if(hub){
      const same=String(hub.senal)===String(olsSignal),hv=$('huberValue'),hs=$('huberSub');
      hv.textContent=`${hub.senal} · ${(Number(hub.ret_estimado)*100).toFixed(3)}%`;
      hv.className='challenger-value '+(hub.senal==='SUBE'?'up':hub.senal==='BAJA'?'down':'flat');
      const score=hp.classification_accuracy==null?'—':`${hp.correct||0}/${hp.window_n||0} · ${(Number(hp.classification_accuracy)*100).toFixed(1)}%`;
      hs.textContent=`${same?'Coincide':'Difiere'} con OLS · ${score}${hub.live?' · intradía':''} · OLS sigue oficial`;
      hs.className='challenger-sub '+(same?'challenger-ok':'challenger-diff');
    }else{
      $('huberValue').textContent=h.status||'NO DISPONIBLE';$('huberValue').className='challenger-value challenger-warn';$('huberSub').textContent=h.error||'OLS continúa como señal principal.';
    }

    const contrib=liveContributions()||(modelInsights.contributions||[]);
    const max=Math.max(...contrib.map(x=>Math.abs(Number(x.contribution_pp)||0)),0.0001);
    $('factorList').innerHTML=contrib.map(x=>{const v=Number(x.contribution_pp)||0,w=Math.max(2,Math.abs(v)/max*100),cl=v>0?'posbar':v<0?'negbar':'';return `<div class="factor-row"><b>${x.label}</b><div class="factor-track"><div class="factor-fill ${cl}" style="width:${w.toFixed(1)}%"></div></div><div class="factor-value ${v>0?'pos':v<0?'neg':'zero'}">${v>=0?'+':''}${v.toFixed(3)} pp</div></div>`}).join('')||'<div class="note">Sin contribuciones disponibles.</div>';
    const items=[
      ['Acierto OLS',insightPct(p.classification_accuracy,0)],
      ['MAE OLS',p.mae_return_pp==null?'—':Number(p.mae_return_pp).toFixed(2)+' pp'],
      ['Acierto Huber',hp.classification_accuracy==null?'—':insightPct(hp.classification_accuracy,0)],
      ['MAE Huber',hp.mae_return_pp==null?'—':Number(hp.mae_return_pp).toFixed(2)+' pp'],
      ['Mejora Huber',hc.net_correct==null?'—':`${Number(hc.net_correct)>=0?'+':''}${Number(hc.net_correct)} aciertos`],
      ['Errores corregidos',hc.corrected_errors==null?'—':`${hc.corrected_errors} · nuevos ${hc.new_errors||0}`],
      ['Acierto SUBE OLS',insightPct(p.sube_accuracy,0)+' · n='+Number(p.sube_n||0)],
      ['Acierto BAJA OLS',insightPct(p.baja_accuracy,0)+' · n='+Number(p.baja_n||0)]
    ];
    $('perfGrid').innerHTML=items.map(x=>`<div class="perf-item"><b>${x[1]}</b><span>${x[0]}</span></div>`).join('');
    const notes=[...(q.critical||[]),...(q.warnings||[])];$('qualityNotes').textContent=notes.length?notes.join(' · '):'Controles de integridad sin alertas. Huber se registra como challenger y no reemplaza la señal OLS.';
  }
'''
html, n = re.subn(
    r"  function insightPct\(.*?\n  function renderMarket\(\)\{",
    insights_js + "\n  function renderMarket(){",
    html,
    count=1,
    flags=re.S,
)
if n == 0:
    needle = "  function renderMarket(){"
    if needle not in html:
        raise RuntimeError("No se encontró renderMarket")
    html = html.replace(needle, insights_js + "\n" + needle, 1)

if "renderTop();renderInsights()" not in html:
    html = html.replace("renderTop()\n  }", "renderTop();renderInsights()\n  }", 1)

if "fetch('data/model_insights.json'" not in html:
    old_promise = """    fetch('data/latest.json',{cache:'no-store'}).then(r=>r.json()),
    loadLive()
  ]).then(([sig,ser,op,latest])=>{
    richSignals=sig.sort((a,b)=>a.fecha.localeCompare(b.fecha));allSeries=ser.sort((a,b)=>a.fecha.localeCompare(b.fecha));operationSeries=op.sort((a,b)=>a.fecha.localeCompare(b.fecha));latestData=latest;
    renderVC();renderSignals();renderTop();renderMarket();"""
    new_promise = """    fetch('data/latest.json',{cache:'no-store'}).then(r=>r.json()),
    fetch('data/model_insights.json',{cache:'no-store'}).then(r=>r.json()),
    loadLive()
  ]).then(([sig,ser,op,latest,insights])=>{
    richSignals=sig.sort((a,b)=>a.fecha.localeCompare(b.fecha));allSeries=ser.sort((a,b)=>a.fecha.localeCompare(b.fecha));operationSeries=op.sort((a,b)=>a.fecha.localeCompare(b.fecha));latestData=latest;modelInsights=insights;
    renderVC();renderSignals();renderTop();renderMarket();renderInsights();"""
    if old_promise not in html:
        raise RuntimeError("No se encontró Promise principal para integrar insights")
    html = html.replace(old_promise, new_promise, 1)

if "Challenger Huber" not in html or "huberValue" not in html:
    raise AssertionError("No se integró el challenger Huber en el HTML")

HTML_PATH.write_text(html, encoding="utf-8")
print("Visor móvil: OLS principal + Huber challenger paralelo + métricas comparadas.")
