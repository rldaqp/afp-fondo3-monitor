(function(){
  'use strict';
  const BRANCH='migracion-github-actions';
  const RAW='https://raw.githubusercontent.com/rldaqp/afp-fondo3-monitor/'+BRANCH+'/public/data/';
  const TRADE_KEY='profuturo_fondo3_trade_history_v3';
  const $=id=>document.getElementById(id);
  const finite=x=>x!==null&&x!==undefined&&x!==''&&Number.isFinite(Number(x));
  const vc=x=>finite(x)?Number(x).toFixed(7):'—';
  const pct=x=>finite(x)?`${Number(x)>=0?'+':''}${(Number(x)*100).toFixed(3)}%`:'—';
  const pctRaw=x=>finite(x)?`${Number(x)>=0?'+':''}${Number(x).toFixed(3)}%`:'—';
  const fmt=d=>{if(!d)return'—';const p=String(d).slice(0,10).split('-');return p.length===3?`${p[2]}/${p[1]}/${p[0]}`:String(d)};
  const money=x=>new Intl.NumberFormat('es-PE',{style:'currency',currency:'PEN'}).format(Number(x));
  const sigClass=s=>s==='SUBE'?'up':s==='BAJA'?'down':'flat';
  const numClass=x=>Number(x)>0?'pos':Number(x)<0?'neg':'zero';
  const uid=()=>`${Date.now()}-${Math.random().toString(16).slice(2)}`;
  let data=null;
  let ranges={qqqVc:30,qqqRet:30,newVc:30,newRet:30};

  async function getJson(name){
    const ts=Date.now(),urls=['data/'+name+'?ts='+ts,RAW+name+'?ts='+ts];let last;
    for(const u of urls){try{const r=await fetch(u,{cache:'no-store'});if(!r.ok)throw new Error('HTTP '+r.status);return await r.json()}catch(e){last=e}}
    throw last||new Error('No disponible '+name);
  }

  function ensureStyles(){
    if($('dualRolling30Styles'))return;
    const st=document.createElement('style');st.id='dualRolling30Styles';st.textContent=`
      .dual-root{margin-top:12px}.dual-head{display:flex;justify-content:space-between;align-items:flex-start;gap:10px}.dual-title{font-size:1.02rem;font-weight:900}.dual-sub{font-size:.72rem;color:#94a3b8;line-height:1.45;margin-top:3px}.dual-badge{border:1px solid #334155;border-radius:999px;padding:5px 9px;font-size:.7rem;font-weight:850;white-space:nowrap}.dual-compare{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-top:10px}.dual-mini{background:#0b1728;border:1px solid #243244;border-radius:10px;padding:9px}.dual-mini span{display:block;font-size:.67rem;color:#94a3b8}.dual-mini b{display:block;margin-top:3px;font-size:.86rem}.dual-model{margin-top:12px;border:1px solid #334155;border-radius:14px;padding:12px;background:#0d192b}.dual-model-head{display:flex;justify-content:space-between;gap:10px;align-items:flex-start}.dual-model-name{font-size:.94rem;font-weight:900}.dual-model-features{font-size:.69rem;color:#94a3b8;margin-top:3px}.dual-now{display:grid;grid-template-columns:repeat(4,1fr);gap:7px;margin-top:9px}.dual-now .dual-mini{background:#101d31}.dual-chart-block{margin-top:10px;background:#0b1728;border:1px solid #243244;border-radius:11px;padding:9px}.dual-chart-title{font-size:.8rem;font-weight:850;color:#e2e8f0;margin-bottom:6px}.dual-chart{height:310px}.dual-controls{display:flex;gap:5px;flex-wrap:wrap;margin-bottom:6px}.dual-controls button{border:1px solid #334155;background:#132238;color:#fff;border-radius:8px;padding:6px 9px;font-size:.7rem;font-weight:750}.dual-controls button.active{background:#2563eb}.dual-market{display:grid;grid-template-columns:repeat(3,1fr);gap:7px;margin-top:8px}.dual-asset{background:#101d31;border:1px solid #243244;border-radius:10px;padding:9px;min-width:0}.dual-asset .sym{font-size:.76rem;font-weight:850}.dual-asset .price{font-size:1rem;font-weight:900;margin-top:3px}.dual-asset .ret{font-size:.84rem;font-weight:850;margin-top:2px}.dual-asset .src{font-size:.64rem;color:#94a3b8;margin-top:4px;line-height:1.3;overflow-wrap:anywhere}.dual-note{font-size:.69rem;color:#94a3b8;line-height:1.45;margin-top:8px}.dual-op-select{margin:10px 0;padding:10px;border:1px solid #334155;border-radius:10px;background:#0b1728}.dual-op-select label{display:block;margin-bottom:5px}.dual-op-select select{width:100%;background:#07111f;color:#fff;border:1px solid #334155;border-radius:9px;padding:9px}
      @media(max-width:700px){.dual-head,.dual-model-head{display:block}.dual-badge{display:inline-block;margin-top:7px}.dual-compare,.dual-now{grid-template-columns:1fr 1fr}.dual-market{grid-template-columns:1fr 1fr}.dual-chart{height:285px}}
      @media(max-width:390px){.dual-compare,.dual-now,.dual-market{grid-template-columns:1fr}.dual-chart{height:270px}}
    `;document.head.appendChild(st);
  }

  function hideLegacy(){
    ['reduced6030Panel','modelInsightsPanel','marketPanel','marketExperimentalPanel','monitorHelp'].forEach(id=>{const e=$(id);if(e)e.style.display='none'});
    ['vcChart','signalChart'].forEach(id=>{const e=$(id);const p=e&&e.closest('.panel');if(p)p.style.display='none'});
    const audit=$('audit');if(audit&&audit.closest('.panel'))audit.closest('.panel').style.display='none';
  }

  function ensureTop(){
    const sub=document.querySelector('main.wrap>h1 + .sub');if(sub)sub.textContent='Comparación operativa · dos modelos OLS Rolling 30 · Profuturo Fondo 3';
    const grid=document.querySelector('main.wrap>section.grid');if(!grid)return null;
    const cards=[...grid.children];if(cards.length<4)return grid;
    cards[0].innerHTML='<div class="label">Último VC SBS</div><div class="value" id="sbsVc">—</div><div class="sub" id="sbsDate">—</div>';
    cards[1].innerHTML='<div class="label">Rolling 30 · QQQ</div><div class="value" id="dualTopQqqVc">—</div><div class="sub" id="dualTopQqqSig">—</div>';
    cards[2].innerHTML='<div class="label">Rolling 30 · nuevos tickers</div><div class="value" id="dualTopNewVc">—</div><div class="sub" id="dualTopNewSig">—</div>';
    cards[3].innerHTML='<div class="label">Backtest ciego · 3 VC</div><div class="value" id="dualTopWinner">—</div><div class="sub" id="dualTopMape">—</div>';
    return grid;
  }

  function modelHtml(key,title,features){
    return `<section class="dual-model" id="dualModel_${key}">
      <div class="dual-model-head"><div><div class="dual-model-name">${title}</div><div class="dual-model-features">${features.join(' · ')}</div></div><div class="dual-badge" id="dualBadge_${key}">Cargando…</div></div>
      <div class="dual-now">
        <div class="dual-mini"><span>VC estimado</span><b id="dualVc_${key}">—</b></div>
        <div class="dual-mini"><span>Retorno estimado</span><b id="dualRet_${key}">—</b></div>
        <div class="dual-mini"><span>Ancla SBS visible</span><b id="dualAnchor_${key}">—</b></div>
        <div class="dual-mini"><span>MAPE ciego 3 VC</span><b id="dualMape_${key}">—</b></div>
      </div>
      <div class="dual-chart-block"><div class="dual-chart-title">VC real SBS vs VC estimado</div><div class="dual-controls" data-chart="${key}Vc"><button data-days="7">7 días</button><button data-days="15">15 días</button><button data-days="30" class="active">30 días</button><button data-days="90">90 días</button><button data-days="all">Todo</button></div><div id="dualVcChart_${key}" class="dual-chart"></div></div>
      <div class="dual-chart-block"><div class="dual-chart-title">Retorno diario estimado y retorno real del VC</div><div class="dual-controls" data-chart="${key}Ret"><button data-days="7">7 días</button><button data-days="15">15 días</button><button data-days="30" class="active">30 días</button><button data-days="90">90 días</button><button data-days="all">Todo</button></div><div id="dualRetChart_${key}" class="dual-chart"></div></div>
      <div class="dual-chart-block"><div class="dual-chart-title">Visor intradía · factores del modelo</div><div id="dualMarket_${key}" class="dual-market"></div><div id="dualSource_${key}" class="dual-note"></div></div>
    </section>`;
  }

  function ensureUi(){
    ensureStyles();hideLegacy();const top=ensureTop();if(!top)return;
    if(!$('dualRolling30Root')){
      const root=document.createElement('section');root.className='panel dual-root';root.id='dualRolling30Root';
      root.innerHTML=`<div class="dual-head"><div><div class="dual-title">Dos modelos en seguimiento</div><div class="dual-sub">Se eliminan del visor los modelos anteriores. Ambos rolling 30 se miden en paralelo con el mismo criterio ciego: los últimos 3 VC SBS no se usan hasta revelar el error.</div></div><div class="dual-badge" id="dualUpdated">Cargando…</div></div>
      <div class="dual-compare"><div class="dual-mini"><span>Ganador MAPE ciego 3 VC</span><b id="dualWinner">—</b></div><div class="dual-mini"><span>QQQ · MAPE</span><b id="dualCmpQqq">—</b></div><div class="dual-mini"><span>Nuevos tickers · MAPE</span><b id="dualCmpNew">—</b></div><div class="dual-mini"><span>Diferencia VC actual</span><b id="dualCmpDiff">—</b></div></div>
      ${modelHtml('qqq','Modelo A · Rolling 30 + QQQ',['SPY','EEM','EPU','MCHI','USD/PEN','QQQ'])}
      ${modelHtml('new_tickers','Modelo B · Rolling 30 + nuevos tickers',['.INX','CPER','EEM','NDX','SPBLSCUP','USD/PEN'])}
      <div class="dual-note" id="dualRule"></div>`;
      top.insertAdjacentElement('afterend',root);
    }
    document.querySelectorAll('.dual-controls button').forEach(btn=>{if(btn.dataset.bound)return;btn.dataset.bound='1';btn.addEventListener('click',()=>{const box=btn.parentElement,key=box.dataset.chart;box.querySelectorAll('button').forEach(b=>b.classList.remove('active'));btn.classList.add('active');ranges[key]=btn.dataset.days==='all'?'all':Number(btn.dataset.days);renderCharts();});});
    ensureOperationSelector();
  }

  function rangeRows(rows,n){if(n==='all')return rows;return rows.slice(-Number(n));}
  function chartRows(m){
    const map=new Map();(m.history_one_step||[]).forEach(r=>map.set(r.fecha,{...r,kind:'hist'}));(m.forward_chain||[]).forEach(r=>{const old=map.get(r.fecha)||{};map.set(r.fecha,{...old,...r,actual_vc:old.actual_vc??r.actual_vc,actual_return:old.actual_return,kind:'forward'})});return [...map.values()].sort((a,b)=>a.fecha.localeCompare(b.fecha));
  }

  function plotVc(key,m){
    const el=$('dualVcChart_'+key);if(!el||!window.Plotly)return;const rows=rangeRows(chartRows(m),ranges[key+'Vc']);
    Plotly.react(el,[
      {x:rows.map(r=>r.fecha),y:rows.map(r=>finite(r.vc_estimated)?Number(r.vc_estimated):null),type:'scatter',mode:'lines+markers',name:'VC estimado',line:{width:2}},
      {x:rows.map(r=>r.fecha),y:rows.map(r=>finite(r.actual_vc)?Number(r.actual_vc):null),type:'scatter',mode:'lines+markers',name:'VC real SBS',line:{width:2}}
    ],{margin:{l:48,r:14,t:12,b:42},paper_bgcolor:'rgba(0,0,0,0)',plot_bgcolor:'rgba(0,0,0,0)',font:{color:'#cbd5e1',size:10},xaxis:{gridcolor:'#243244'},yaxis:{gridcolor:'#243244',title:'Valor cuota'},legend:{orientation:'h',y:1.12}},{responsive:true,displayModeBar:false});
  }

  function plotRet(key,m){
    const el=$('dualRetChart_'+key);if(!el||!window.Plotly)return;const rows=rangeRows(chartRows(m),ranges[key+'Ret']);
    Plotly.react(el,[
      {x:rows.map(r=>r.fecha),y:rows.map(r=>finite(r.return_estimated)?Number(r.return_estimated)*100:null),type:'bar',name:'Estimado %'},
      {x:rows.map(r=>r.fecha),y:rows.map(r=>finite(r.actual_return)?Number(r.actual_return)*100:null),type:'scatter',mode:'lines+markers',name:'Real SBS %',line:{width:2}}
    ],{margin:{l:48,r:14,t:12,b:42},paper_bgcolor:'rgba(0,0,0,0)',plot_bgcolor:'rgba(0,0,0,0)',font:{color:'#cbd5e1',size:10},xaxis:{gridcolor:'#243244'},yaxis:{gridcolor:'#243244',title:'Retorno %',zeroline:true,zerolinecolor:'#64748b'},legend:{orientation:'h',y:1.12}},{responsive:true,displayModeBar:false});
  }

  function renderCharts(){if(!data)return;plotVc('qqq',data.models.qqq);plotRet('qqq',data.models.qqq);plotVc('new_tickers',data.models.new_tickers);plotRet('new_tickers',data.models.new_tickers)}

  function assetHtml(a){const name=a.serie||a.ticker||'—',price=finite(a.precio_actual)?Number(a.precio_actual).toFixed(name.includes('USD')?4:2):'—',r=a.retorno_modelo??a.retorno;return `<div class="dual-asset"><div class="sym">${name}</div><div class="price">${price}</div><div class="ret ${numClass(r)}">${pct(r)}</div><div class="src">${a.estado||'Fuente pendiente'}${a.timestamp?'<br>'+fmt(a.timestamp):''}</div></div>`}

  function renderModel(key,m,blind){
    const c=m.current||{},sig=c.signal||'—';
    if($('dualVc_'+key))$('dualVc_'+key).textContent=vc(c.vc_estimated);
    if($('dualRet_'+key)){$('dualRet_'+key).textContent=`${sig} · ${pct(c.return_estimated)}`;$('dualRet_'+key).className=sigClass(sig)}
    if($('dualAnchor_'+key))$('dualAnchor_'+key).textContent=`${fmt(c.anchor_date)} · ${vc(c.anchor_vc)}`;
    if($('dualMape_'+key))$('dualMape_'+key).textContent=finite(blind&&blind.mape_pct)?Number(blind.mape_pct).toFixed(4)+'%':'—';
    if($('dualBadge_'+key)){$('dualBadge_'+key).textContent=`${sig} · ${fmt(c.fecha)}`;$('dualBadge_'+key).className='dual-badge '+sigClass(sig)}
    const g=$('dualMarket_'+key);if(g)g.innerHTML=(m.intraday_assets||[]).map(assetHtml).join('');
    if($('dualSource_'+key))$('dualSource_'+key).textContent=m.source_note||'';
  }

  function render(){
    if(!data)return;ensureUi();const s=data.latest_sbs||{},q=data.models.qqq,n=data.models.new_tickers,qb=data.blind3?.qqq_common||{},nb=data.blind3?.new_tickers_common||{};
    if($('sbsVc'))$('sbsVc').textContent=vc(s.vc);if($('sbsDate'))$('sbsDate').textContent=fmt(s.fecha)+' · SBS OFICIAL';
    if($('dualTopQqqVc'))$('dualTopQqqVc').textContent=vc(q.current?.vc_estimated);if($('dualTopQqqSig'))$('dualTopQqqSig').textContent=`${q.current?.signal||'—'} · ${pct(q.current?.return_estimated)}`;
    if($('dualTopNewVc'))$('dualTopNewVc').textContent=vc(n.current?.vc_estimated);if($('dualTopNewSig'))$('dualTopNewSig').textContent=`${n.current?.signal||'—'} · ${pct(n.current?.return_estimated)}`;
    if($('dualTopWinner'))$('dualTopWinner').textContent=data.comparison?.winner_blind3_mape||'—';if($('dualTopMape'))$('dualTopMape').textContent=`QQQ ${finite(qb.mape_pct)?Number(qb.mape_pct).toFixed(3):'—'}% · Nuevos ${finite(nb.mape_pct)?Number(nb.mape_pct).toFixed(3):'—'}%`;
    if($('dualWinner'))$('dualWinner').textContent=data.comparison?.winner_blind3_mape||'—';if($('dualCmpQqq'))$('dualCmpQqq').textContent=finite(qb.mape_pct)?Number(qb.mape_pct).toFixed(4)+'%':'—';if($('dualCmpNew'))$('dualCmpNew').textContent=finite(nb.mape_pct)?Number(nb.mape_pct).toFixed(4)+'%':'—';if($('dualCmpDiff'))$('dualCmpDiff').textContent=finite(data.comparison?.vc_difference)?`${Number(data.comparison.vc_difference)>=0?'+':''}${Number(data.comparison.vc_difference).toFixed(4)}`:'—';
    if($('dualUpdated'))$('dualUpdated').textContent=`${data.market_mode||'MERCADO'} · ${fmt(data.signal_date)}`;if($('dualRule'))$('dualRule').textContent=data.rule||'';
    renderModel('qqq',q,qb);renderModel('new_tickers',n,nb);renderCharts();ensureOperationSelector();
  }

  function ensureOperationSelector(){
    const op=$('operation');if(!op)return;if(!$('dualTradeModel')){const box=document.createElement('div');box.className='dual-op-select';box.innerHTML='<label>Modelo usado para calcular/registrar esta operación</label><select id="dualTradeModel"><option value="new_tickers">Modelo B · Rolling 30 + nuevos tickers</option><option value="qqq">Modelo A · Rolling 30 + QQQ</option></select>';op.insertBefore(box,op.firstChild)}
  }

  function selectedModel(){return $('dualTradeModel')?.value||'new_tickers'}
  function modelMaps(key){
    const m=data?.models?.[key],off=new Map(),est=new Map();if(!m)return{off,est,dates:[]};
    (m.history_one_step||[]).forEach(r=>{if(r.fecha&&finite(r.actual_vc))off.set(r.fecha,Number(r.actual_vc));if(r.fecha&&finite(r.vc_estimated))est.set(r.fecha,Number(r.vc_estimated))});
    (m.forward_chain||[]).forEach(r=>{if(r.fecha&&finite(r.vc_estimated))est.set(r.fecha,Number(r.vc_estimated));if(r.fecha&&finite(r.actual_vc))off.set(r.fecha,Number(r.actual_vc))});
    const s=data.latest_sbs;if(s?.fecha&&finite(s.vc))off.set(s.fecha,Number(s.vc));return{off,est,dates:[...new Set([...off.keys(),...est.keys()])].sort()};
  }
  function effective(ds,requested,dir){return dir==='entry'?(ds.find(d=>d>=requested)||requested):([...ds].reverse().find(d=>d<=requested)||requested)}
  function currentMode(){return document.querySelector('.tabs button.active')?.dataset.mode||'monitor'}

  function calcOperation(ev){
    if(!data)return;ev.preventDefault();ev.stopImmediatePropagation();const mode=currentMode();if(mode==='monitor')return;
    const req=$('entry')?.value,capital=Number($('capital')?.value||0);if(!req||!finite(capital)||capital<=0){if($('detail'))$('detail').textContent='Completa fecha y capital.';return}
    const key=selectedModel(),maps=modelMaps(key),entry=effective(maps.dates,req,'entry'),entryVc=maps.off.get(entry)??maps.est.get(entry);const outReq=mode==='closed'?$('exit')?.value:data.signal_date;if(!outReq||!finite(entryVc)){if($('detail'))$('detail').textContent='No existe VC para la fecha seleccionada.';return}
    const out=mode==='closed'?effective(maps.dates,outReq,'exit'):outReq,outVc=maps.off.get(out)??maps.est.get(out);if(!finite(outVc)){if($('detail'))$('detail').textContent='No existe VC para la salida/valoración.';return}
    const units=capital/entryVc,final=units*outVc,gain=final-capital,rent=final/capital-1,m=data.models[key];
    if($('mCapital'))$('mCapital').textContent=money(capital);if($('mFinal'))$('mFinal').textContent=money(final);if($('mGain'))$('mGain').textContent=money(gain);if($('mRent'))$('mRent').textContent=(rent*100).toFixed(2)+'%';
    if($('detail'))$('detail').innerHTML=`<b>${m.name}</b><br>Entrada efectiva: ${fmt(entry)} · VC ${vc(entryVc)}${maps.off.has(entry)?' · SBS OFICIAL':' · estimado'}<br>${mode==='closed'?'Salida':'Valoración'}: ${fmt(out)} · VC ${vc(outVc)}${maps.off.has(out)?' · SBS OFICIAL':' · estimado'}<br>Número de cuotas: ${units.toFixed(6)}<br>Ganancia/pérdida: <b>${money(gain)}</b>`;
  }

  function saveOperation(ev){
    if(!data)return;ev.preventDefault();ev.stopImmediatePropagation();const mode=currentMode();if(mode==='monitor'){if($('tradeMsg'))$('tradeMsg').textContent='Selecciona “Sigo dentro” o “Ya salí”.';return}
    const req=$('entry')?.value,capital=Number($('capital')?.value||0);if(!req||!finite(capital)||capital<=0){if($('tradeMsg'))$('tradeMsg').textContent='Completa fecha de entrada y capital.';return}
    const key=selectedModel(),m=data.models[key],maps=modelMaps(key),entry=effective(maps.dates,req,'entry');let exit=null,exitReq=null;if(mode==='closed'){exitReq=$('exit')?.value;if(!exitReq){if($('tradeMsg'))$('tradeMsg').textContent='Indica fecha de salida.';return}exit=effective(maps.dates,exitReq,'exit')}
    let rows=[];try{rows=JSON.parse(localStorage.getItem(TRADE_KEY)||'[]');if(!Array.isArray(rows))rows=[]}catch(e){rows=[]}
    rows.push({id:uid(),fund:'PROFUTURO',origin:'VISOR DUAL ROLLING30',model_key:key,model_name:m.name,created_at:new Date().toISOString(),confirmed:false,capital,entry_requested:req,entry_date:entry,entry_est_vc:maps.est.get(entry)??null,entry_sbs_vc:maps.off.get(entry)??null,exit_requested:exitReq,exit_date:exit,exit_est_vc:exit?maps.est.get(exit)??null:null,exit_sbs_vc:exit?maps.off.get(exit)??null:null});
    localStorage.setItem(TRADE_KEY,JSON.stringify(rows));window.dispatchEvent(new Event('fondo3-local-trade-change'));if($('tradeMsg'))$('tradeMsg').textContent=`Operación registrada con ${m.name}.`;
  }

  function bindOperationCapture(){
    if(document.documentElement.dataset.dualOpBound)return;document.documentElement.dataset.dualOpBound='1';
    document.addEventListener('click',ev=>{const id=ev.target&&ev.target.id;if(id==='calc')calcOperation(ev);else if(['tradeSaveBtn','tradeSaveInline','tradeSaveInlineHotfix'].includes(id))saveOperation(ev)},true);
  }

  async function refresh(){try{data=await getJson('dual_rolling30_monitor.json');render()}catch(e){ensureUi();const b=$('dualUpdated');if(b)b.textContent='Esperando datos duales · '+e.message}}
  function boot(){ensureUi();bindOperationCapture();refresh();setInterval(refresh,30000)}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();
