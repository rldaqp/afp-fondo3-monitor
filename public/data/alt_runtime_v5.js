(function(){
  'use strict';
  const BRANCH='migracion-github-actions';
  const RAW='https://raw.githubusercontent.com/rldaqp/afp-fondo3-monitor/'+BRANCH+'/public/data/';
  const $=id=>document.getElementById(id);
  const finite=x=>x!==null&&x!==undefined&&x!==''&&Number.isFinite(Number(x));
  const vc=x=>finite(x)?Number(x).toFixed(7):'—';
  const pct=x=>finite(x)?`${Number(x)>=0?'+':''}${(Number(x)*100).toFixed(3)}%`:'—';
  const pct2=x=>finite(x)?`${Number(x)>=0?'+':''}${(Number(x)*100).toFixed(2)}%`:'—';
  const fmt=d=>{if(!d)return'—';const p=String(d).slice(0,10).split('-');return p.length===3?`${p[2]}/${p[1]}/${p[0]}`:String(d)};
  const clsSignal=s=>s==='SUBE'?'up':s==='BAJA'?'down':'flat';
  const clsNum=x=>Number(x)>0?'pos':Number(x)<0?'neg':'zero';
  const clock=(iso,tz)=>{try{return new Intl.DateTimeFormat('es-PE',{timeZone:tz,hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(iso))}catch(e){return'—'}};
  let altData=null, liveData=null, challengerData=null;

  async function getJson(name){
    const ts=Date.now();
    const urls=['data/'+name+'?ts='+ts,RAW+name+'?ts='+ts];
    let last=null;
    for(const url of urls){
      try{const r=await fetch(url,{cache:'no-store'});if(!r.ok)throw new Error('HTTP '+r.status);return await r.json();}
      catch(e){last=e;}
    }
    throw last||new Error('No disponible '+name);
  }

  function ensureStyles(){
    if($('alt6030RuntimeStylesV5'))return;
    const st=document.createElement('style');st.id='alt6030RuntimeStylesV5';
    st.textContent=`
      @media(min-width:701px){#reduced6030Panel .r6030-grid{grid-template-columns:repeat(3,minmax(0,1fr))!important}}
      @media(max-width:700px){#reduced6030Panel .r6030-grid{grid-template-columns:1fr!important}}
      .alt-v5-status{margin-top:8px;padding:8px;border:1px solid #243244;border-radius:9px;background:#081526;font-size:.7rem;line-height:1.45;color:#cbd5e1}
      .alt-v5-compare{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-top:8px}.alt-v5-mini{padding:7px;border:1px solid #243244;border-radius:8px;background:#101d31}.alt-v5-mini span{display:block;color:#94a3b8;font-size:.63rem}.alt-v5-mini b{display:block;margin-top:2px;font-size:.78rem}
      #alt6030Chart{height:300px;margin-top:8px}.trade-inline-actions{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:9px}.trade-inline-save{border:1px solid #16a34a;background:#15803d;color:#fff;border-radius:10px;padding:11px;font-weight:850;cursor:pointer}.trade-inline-save:hover{background:#16a34a}.trade-inline-note{font-size:.7rem;color:#94a3b8;margin-top:6px;line-height:1.4}
      @media(max-width:700px){.alt-v5-compare{grid-template-columns:1fr 1fr}.alt-v5-mini:last-child{grid-column:1/-1}.trade-inline-actions{grid-template-columns:1fr}}
    `;
    document.head.appendChild(st);
  }

  function ensureCompareUi(){
    const panel=$('reduced6030Panel');if(!panel)return;
    const kicker=panel.querySelector('.r6030-kicker');
    if(kicker)kicker.textContent='OLS oficial vs Challenger 60/30 vs nuevos tickers 60/30 reanclado con SBS';
    const grid=panel.querySelector('.r6030-grid');
    if(grid&&!$('r6030AltCard')){
      const card=document.createElement('div');card.className='r6030-card';card.id='r6030AltCard';card.style.borderColor='#3b82f6';
      card.innerHTML=`<div class="r6030-label">60/30 NUEVOS TICKERS · REANCLADO</div><div id="r6030AltSignal" class="r6030-signal">CARGANDO…</div><div id="r6030AltVc" class="r6030-vc">VC —</div><div id="r6030AltRet" class="r6030-ret">Retorno —</div><div id="r6030AltMeta" class="r6030-note">.INX · CPER · EEM · NDX · SPBLSCUP · USD/PEN</div><div id="r6030AltCompare" class="alt-v5-compare"></div><div id="r6030AltStatus" class="alt-v5-status">Cargando reglas operativas…</div>`;
      grid.appendChild(card);
    }
    if(!$('r6030AltHistoryV5')){
      const details=panel.querySelector('.r6030-details');
      const box=document.createElement('div');box.className='r6030-history';box.id='r6030AltHistoryV5';
      box.innerHTML=`<div class="r6030-history-title">Nuevos tickers · últimos 20 · VC estimado vs SBS real</div><div id="r6030AltMetrics" class="r6030-note">Cargando validación…</div><div id="alt6030Chart"></div><div class="r6030-history-controls"><input type="date" id="r6030AltDate"><button type="button" id="r6030AltDateBtn">Ver fecha</button></div><div id="r6030AltDateResult" class="r6030-history-result">Elige una fecha.</div>`;
      if(details)panel.insertBefore(box,details);else panel.appendChild(box);
    }
    const btn=$('r6030AltDateBtn'),input=$('r6030AltDate');
    if(btn&&!btn.dataset.v5bound){btn.dataset.v5bound='1';btn.addEventListener('click',renderAltDate);}
    if(input&&!input.dataset.v5bound){input.dataset.v5bound='1';input.addEventListener('change',renderAltDate);}
  }

  function ensureMarketUi(){
    let panel=$('marketExperimentalPanel');
    if(panel)return;
    const audit=$('audit');panel=document.createElement('section');panel.className='panel';panel.id='marketExperimentalPanel';
    panel.innerHTML='<div class="market-head"><div><div class="chart-title">Nuevos tickers 60/30</div><div class="market-mode" style="color:#93c5fd">EXPERIMENTAL · REANCLADO SBS</div></div><div class="market-time" id="marketExperimentalTime">Cargando…</div></div><div id="marketExperimentalGrid" class="market-grid"></div><div class="note" style="margin-top:9px">.INX · CPER · EEM · NDX · SPBLSCUP · USD/PEN. SPBLSCUP debe tener dato de la sesión; no se sustituye por 0%.</div>';
    if(audit&&audit.closest('section'))audit.closest('section').before(panel);else document.querySelector('main')?.appendChild(panel);
  }

  function ensureOperationControls(){
    const tabs=[...document.querySelectorAll('.tabs button[data-mode]')];
    const op=$('operation'),exitBox=$('exitBox');
    tabs.forEach(btn=>{
      btn.disabled=false;btn.removeAttribute('aria-disabled');
      if(btn.dataset.v5bound)return;btn.dataset.v5bound='1';
      btn.addEventListener('click',()=>{
        tabs.forEach(x=>x.classList.toggle('active',x===btn));
        const mode=btn.dataset.mode;
        if(op)op.classList.toggle('hidden',mode==='monitor');
        if(exitBox)exitBox.classList.toggle('hidden',mode!=='closed');
        const max=(altData&&altData.signal_date)||(liveData&&liveData.signal_date)||'';
        if($('entry')&&max)$('entry').max=max;
        if($('exit')&&max){$('exit').max=max;if(mode==='closed'&&!$('exit').value)$('exit').value=max;}
        if($('tradeMsg'))$('tradeMsg').textContent=mode==='inside'?'Modo entrada/posición abierta activo. Completa fecha y capital, calcula y registra.':mode==='closed'?'Modo cierre activo. Completa entrada, salida y capital, calcula y registra.':'Solo monitoreo.';
      });
    });
    if(op&&!$('tradeSaveInline')){
      const wrap=document.createElement('div');wrap.className='trade-inline-actions';
      const b=document.createElement('button');b.type='button';b.id='tradeSaveInline';b.className='trade-inline-save';b.textContent='✓ Registrar operación';
      b.addEventListener('click',()=>{const target=$('tradeSaveBtn');if(target){target.disabled=false;target.click();document.querySelector('#tradeHistoryPanel')?.scrollIntoView({behavior:'smooth',block:'start'});}else if($('tradeMsg'))$('tradeMsg').textContent='El módulo de histórico todavía está cargando; intenta nuevamente en unos segundos.';});
      wrap.appendChild(b);op.appendChild(wrap);
      const note=document.createElement('div');note.className='trade-inline-note';note.textContent='La operación queda guardada en el histórico del visor. La estimación se congela al registrar y se completa con SBS cuando el VC oficial aparezca.';op.appendChild(note);
    }
    const save=$('tradeSaveBtn');if(save){save.disabled=false;save.removeAttribute('aria-disabled');}
  }

  function ensureUi(){ensureStyles();ensureCompareUi();ensureMarketUi();ensureOperationControls();}

  function renderMarket(){
    ensureMarketUi();const wanted=['.INX','CPER','EEM','NDX','SPBLSCUP','USD/PEN'];
    const rows=Array.isArray(liveData&&liveData.experimental_assets)?liveData.experimental_assets:[];const by=new Map(rows.map(x=>[x.serie,x]));
    const fx=altData&&altData.fx_operational;
    const grid=$('marketExperimentalGrid');if(!grid)return;
    grid.innerHTML=wanted.map(name=>{
      let a=by.get(name)||{serie:name};
      if(name==='USD/PEN'&&fx&&finite(fx.value))a={...a,precio_actual:fx.value,retorno:fx.return,estado:fx.source};
      const price=finite(a.precio_actual)?Number(a.precio_actual).toFixed(name==='USD/PEN'?4:2):'—';
      const rr=finite(a.retorno)?`<span class="${clsNum(a.retorno)}">${pct2(a.retorno)}</span>`:'<span class="zero">—</span>';
      return `<div class="market-item"><div class="market-symbol">${name}</div><div class="market-price">${price}</div><div class="market-ret">${rr}</div><div class="market-source">${a.estado||'Dato pendiente'}<br><b>${a.timestamp?fmt(a.timestamp):''}</b></div></div>`;
    }).join('');
    const head=$('marketExperimentalTime');if(head)head.innerHTML=`Fecha ${fmt((altData&&altData.signal_date)||(liveData&&liveData.signal_date))}<br>Actualizado ${clock((altData&&altData.generated_at_lima)||(liveData&&liveData.generated_at_lima),'America/Lima')} Lima`;
  }

  function renderAlt(){
    ensureCompareUi();if(!altData)return;
    const m=altData.model||{},s=m.signal||'—';
    if($('r6030AltSignal')){$('r6030AltSignal').textContent=s;$('r6030AltSignal').className='r6030-signal '+clsSignal(s);}
    if($('r6030AltVc'))$('r6030AltVc').textContent='VC '+vc(m.vc_estimated);
    if($('r6030AltRet'))$('r6030AltRet').textContent='Retorno '+pct(m.return_estimated);
    if($('r6030AltMeta'))$('r6030AltMeta').textContent=`.INX · CPER · EEM · NDX · SPBLSCUP · USD/PEN · ancla SBS ${fmt(m.sbs_anchor_date)} = ${vc(m.sbs_anchor_vc)}`;
    const official=challengerData&&challengerData.official,chall=challengerData&&challengerData.challenger;
    const difOfficial=official&&finite(official.vc_estimated)&&finite(m.vc_estimated)?Number(m.vc_estimated)-Number(official.vc_estimated):null;
    const difChall=chall&&finite(chall.vc_estimated)&&finite(m.vc_estimated)?Number(m.vc_estimated)-Number(chall.vc_estimated):null;
    if($('r6030AltCompare'))$('r6030AltCompare').innerHTML=`<div class="alt-v5-mini"><span>vs OLS oficial</span><b>${finite(difOfficial)?(difOfficial>=0?'+':'')+difOfficial.toFixed(4):'—'}</b></div><div class="alt-v5-mini"><span>vs Challenger</span><b>${finite(difChall)?(difChall>=0?'+':'')+difChall.toFixed(4):'—'}</b></div><div class="alt-v5-mini"><span>Backtest reanclado MAE</span><b>${finite(altData.backtest_exact20&&altData.backtest_exact20.mae_vc)?Number(altData.backtest_exact20.mae_vc).toFixed(4):'—'}</b></div>`;
    const fx=altData.fx_operational||{};
    if($('r6030AltStatus'))$('r6030AltStatus').innerHTML=`<b>${m.reanchored_with_latest_sbs?'REANCLADO CON SBS':'SIN REANCLAJE'}</b> · beta 60/30 congelado.<br>FX: ${fx.source||'histórico BCRP'}${fx.provisional?' · PROVISIONAL':''}.<br>El nuevo modelo no usa 0% artificial para SPBLSCUP.`;
    const input=$('r6030AltDate');if(input){input.min=altData.history_min_date||'';input.max=altData.history_max_date||altData.signal_date||'';if(!input.value)input.value=altData.signal_date||'';}
    renderAltDate();renderAltChart();ensureOperationControls();
  }

  function combinedHistory(){
    const map=new Map();
    const bt=((altData&&altData.backtest_exact20)||{}).rows||[];bt.forEach(r=>map.set(r.fecha,{...r,tipo:'HISTÓRICO REANCLADO'}));
    const op=(altData&&altData.operational_history)||[];op.forEach(r=>map.set(r.fecha,{...r,tipo:'OPERATIVO'}));
    return [...map.values()].filter(r=>r.fecha&&finite(r.vc)).sort((a,b)=>a.fecha.localeCompare(b.fecha)).slice(-20);
  }

  function renderAltChart(){
    const el=$('alt6030Chart');if(!el||!window.Plotly||!altData)return;
    const rows=combinedHistory();
    const x=rows.map(r=>r.fecha),est=rows.map(r=>finite(r.vc)?Number(r.vc):null),real=rows.map(r=>finite(r.actual_vc)?Number(r.actual_vc):null);
    Plotly.react(el,[
      {x,y:est,type:'scatter',mode:'lines+markers',name:'VC estimado nuevo 60/30',line:{width:2}},
      {x,y:real,type:'scatter',mode:'lines+markers',name:'VC real SBS',line:{width:2}}
    ],{margin:{l:48,r:16,t:12,b:45},paper_bgcolor:'rgba(0,0,0,0)',plot_bgcolor:'rgba(0,0,0,0)',font:{color:'#cbd5e1',size:11},xaxis:{gridcolor:'#243244'},yaxis:{gridcolor:'#243244',title:'Valor cuota'},legend:{orientation:'h',y:1.14},showlegend:true},{responsive:true,displayModeBar:false});
    const bt=altData.backtest_exact20||{};if($('r6030AltMetrics'))$('r6030AltMetrics').textContent=`Últimos 20 reanclados · MAE ${finite(bt.mae_vc)?Number(bt.mae_vc).toFixed(4):'—'} · RMSE ${finite(bt.rmse_vc)?Number(bt.rmse_vc).toFixed(4):'—'} · MAPE ${finite(bt.mape_pct)?Number(bt.mape_pct).toFixed(3)+'%':'—'}`;
  }

  function renderAltDate(){
    const input=$('r6030AltDate'),box=$('r6030AltDateResult');if(!input||!box||!altData)return;
    const d=input.value,r=combinedHistory().find(x=>x.fecha===d);if(!r){box.textContent='No hay observación para esa fecha.';return;}
    const parts=[`Fecha ${fmt(d)} · ${r.tipo||r.source||''}`,`base ${vc(r.base_vc)}`,`VC estimado ${vc(r.vc)}`,`retorno ${pct(r.return)}`,`señal ${r.signal||'—'}`];
    if(finite(r.actual_vc))parts.push(`SBS ${vc(r.actual_vc)} · error ${finite(r.error_pct)?Number(r.error_pct).toFixed(3)+'%':finite(r.abs_error)?Number(r.abs_error).toFixed(4):'—'}`);else parts.push('SBS pendiente');
    box.textContent=parts.join(' · ');
  }

  async function loadAll(){
    ensureUi();
    try{[liveData,challengerData,altData]=await Promise.all([getJson('live_market.json'),getJson('reduced_6030_challenger.json'),getJson('alt_6030_experimental.json')]);}
    catch(e){const s=$('r6030AltStatus');if(s)s.textContent='Nuevo 60/30 no disponible: '+e;return;}
    renderMarket();renderAlt();
  }

  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',loadAll,{once:true});else loadAll();
  setTimeout(loadAll,1200);setInterval(loadAll,60000);
})();
