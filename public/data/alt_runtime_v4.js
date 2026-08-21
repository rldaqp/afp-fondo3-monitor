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
  let altData=null;

  function stampLabel(stamp){
    if(!stamp)return 'Hora no disponible';
    const s=String(stamp);
    if(s.includes('T'))return `Corte ${clock(s,'America/New_York')} NY · ${clock(s,'America/Lima')} Lima`;
    return `Cierre ${fmt(s)}`;
  }

  async function getJson(name){
    const ts=Date.now();
    const urls=[RAW+name+'?ts='+ts,'data/'+name+'?ts='+ts];
    let last=null;
    for(const url of urls){
      try{
        const r=await fetch(url,{cache:'no-store'});
        if(!r.ok)throw new Error('HTTP '+r.status);
        return await r.json();
      }catch(e){last=e;}
    }
    throw last||new Error('No disponible '+name);
  }

  function ensureStyles(){
    if($('alt6030RuntimeStyles'))return;
    const st=document.createElement('style');
    st.id='alt6030RuntimeStyles';
    st.textContent='@media(min-width:701px){#reduced6030Panel .r6030-grid{grid-template-columns:repeat(3,minmax(0,1fr))!important}}@media(max-width:700px){#reduced6030Panel .r6030-grid{grid-template-columns:1fr!important}}';
    document.head.appendChild(st);
  }

  function ensureCompareUi(){
    const panel=$('reduced6030Panel');
    if(!panel)return;
    const kicker=panel.querySelector('.r6030-kicker');
    if(kicker)kicker.textContent='OLS oficial vs dos modelos 60/30 · cadenas ciegas sin reanclaje SBS dentro del bloque';
    const grid=panel.querySelector('.r6030-grid');
    if(grid&&!$('r6030AltCard')){
      const card=document.createElement('div');
      card.className='r6030-card';card.id='r6030AltCard';card.style.borderColor='#3b82f6';
      card.innerHTML='<div class="r6030-label">60/30 NUEVOS TICKERS · EXPERIMENTAL</div><div id="r6030AltSignal" class="r6030-signal">CARGANDO…</div><div id="r6030AltVc" class="r6030-vc">VC —</div><div id="r6030AltRet" class="r6030-ret">Retorno —</div><div class="r6030-note">.INX · CPER · EEM · NDX · SPBLSCUP · USD/PEN</div>';
      grid.appendChild(card);
    }
    if(!$('r6030AltHistory')){
      const currentHistory=panel.querySelector('.r6030-history');
      const details=panel.querySelector('.r6030-details');
      const box=document.createElement('div');
      box.className='r6030-history';box.id='r6030AltHistory';
      box.innerHTML='<div class="r6030-history-title">Ver nuevos tickers 60/30 en otra fecha</div><div class="r6030-history-controls"><input type="date" id="r6030AltDate"><button type="button" id="r6030AltDateBtn">Ver fecha</button></div><div id="r6030AltDateResult" class="r6030-history-result">Cargando histórico…</div>';
      if(details)panel.insertBefore(box,details);else if(currentHistory)currentHistory.after(box);else panel.appendChild(box);
    }
    const btn=$('r6030AltDateBtn'),input=$('r6030AltDate');
    if(btn&&!btn.dataset.bound){btn.dataset.bound='1';btn.addEventListener('click',renderAltHistory);}
    if(input&&!input.dataset.bound){input.dataset.bound='1';input.addEventListener('change',renderAltHistory);}
  }

  function ensureMarketUi(){
    let panel=$('marketExperimentalPanel');
    const audit=$('audit');
    if(!panel){
      panel=document.createElement('section');panel.className='panel';panel.id='marketExperimentalPanel';
      panel.innerHTML='<div class="market-head"><div><div class="chart-title">Nuevos tickers 60/30</div><div class="market-mode" style="color:#93c5fd">EXPERIMENTAL · SEGUIMIENTO</div></div><div class="market-time" id="marketExperimentalTime">Cargando corte…</div></div><div id="marketExperimentalGrid" class="market-grid"></div><div class="note" style="margin-top:9px">.INX · CPER · EEM · NDX · SPBLSCUP · USD/PEN. El horario mostrado corresponde al dato usado en cada tarjeta.</div>';
      if(audit&&audit.closest('section'))audit.closest('section').before(panel);else document.querySelector('main')?.appendChild(panel);
    }else{
      let head=panel.querySelector('.market-time');
      if(head&&!head.id)head.id='marketExperimentalTime';
      const note=panel.querySelector('.note');
      if(note)note.textContent='.INX · CPER · EEM · NDX · SPBLSCUP · USD/PEN. El horario mostrado corresponde al dato usado en cada tarjeta.';
    }
  }

  function ensureUi(){ensureStyles();ensureCompareUi();ensureMarketUi();}

  function repairTop(latest){
    if(!latest)return;
    if($('sbsVc')&&finite(latest.latest_sbs_vc))$('sbsVc').textContent=vc(latest.latest_sbs_vc);
    if($('sbsDate'))$('sbsDate').textContent=fmt(latest.latest_sbs_date);
    if($('window'))$('window').textContent=`${fmt(latest.training_start)} → ${fmt(latest.training_end)}`;
  }

  function renderMarket(live){
    ensureMarketUi();
    const wanted=['.INX','CPER','EEM','NDX','SPBLSCUP','USD/PEN'];
    const rows=Array.isArray(live&&live.experimental_assets)?live.experimental_assets:[];
    const by=new Map(rows.map(x=>[x.serie,x]));
    const grid=$('marketExperimentalGrid');
    if(grid)grid.innerHTML=wanted.map(name=>{
      const a=by.get(name)||{serie:name};
      const price=finite(a.precio_actual)?Number(a.precio_actual).toFixed(name==='USD/PEN'?4:2):'—';
      const rr=finite(a.retorno)?`<span class="${clsNum(a.retorno)}">${pct2(a.retorno)}</span>`:'<span class="zero">—</span>';
      return `<div class="market-item"><div class="market-symbol">${name}</div><div class="market-price">${price}</div><div class="market-ret">${rr}</div><div class="market-source">${a.estado||'Dato pendiente'}<br><b>${stampLabel(a.timestamp)}</b></div></div>`;
    }).join('');
    const timed=rows.map(x=>x.timestamp).filter(x=>String(x||'').includes('T')).sort();
    const head=$('marketExperimentalTime');
    if(head){const cut=timed.length?timed.at(-1):null;head.innerHTML=`${cut?stampLabel(cut):'Sin corte intradía'}<br>Visor: ${clock(live&&live.generated_at_lima,'America/Lima')} Lima`;}
  }

  function renderAltModel(){
    ensureCompareUi();
    if(!altData)return;
    const m=altData.model||{},s=m.signal||'—';
    if($('r6030AltSignal')){$('r6030AltSignal').textContent=s;$('r6030AltSignal').className='r6030-signal '+clsSignal(s);}
    if($('r6030AltVc'))$('r6030AltVc').textContent='VC '+vc(m.vc_estimated);
    if($('r6030AltRet'))$('r6030AltRet').textContent='Retorno '+pct(m.return_estimated);
    const input=$('r6030AltDate');
    if(input){input.min=altData.history_min_date||'';input.max=altData.history_max_date||altData.signal_date||'';if(!input.value)input.value=altData.signal_date||altData.history_max_date||'';}
    renderAltHistory();
  }

  function renderAltHistory(){
    const input=$('r6030AltDate'),box=$('r6030AltDateResult');
    if(!input||!box||!altData)return;
    const d=input.value;
    const op=(altData.operational_history||[]).find(x=>x.fecha===d);
    const bt=((altData.backtest_exact20||{}).rows||[]).find(x=>x.fecha===d);
    const r=op||bt;
    if(!r){box.textContent='No hay una observación del nuevo 60/30 para esa fecha.';return;}
    if(String(r.source||'').includes('ANCLA')){box.textContent=`Fecha ${fmt(d)} · ANCLA SBS DEL CICLO · VC ${vc(r.vc)} · punto de partida, no predicción.`;return;}
    const parts=[`Fecha ${fmt(d)} · ${r.source||'60/30 nuevos tickers'}`,`VC ${vc(r.vc)}`,`retorno ${pct(r.return)}`,`señal ${r.signal||'—'}`];
    if(finite(r.actual_vc))parts.push(`SBS real ${vc(r.actual_vc)} · error ${finite(r.abs_error)?Number(r.abs_error).toFixed(4):Math.abs(Number(r.vc)-Number(r.actual_vc)).toFixed(4)}`);else parts.push('SBS real pendiente');
    box.textContent=parts.join(' · ');
  }

  function renderAudit(latest,live,challenger,alt){
    const box=$('audit');if(!box)return;
    const issues=[];
    if(!live||!live.generated_at_lima)issues.push('snapshot OLS sin hora');
    if(!challenger||!live||challenger.signal_date!==live.signal_date)issues.push('challenger 60/30 desalineado');
    if(!alt||!live||alt.signal_date!==live.signal_date)issues.push('nuevos tickers 60/30 desalineados');
    const exp=live&&Array.isArray(live.experimental_assets)?live.experimental_assets:[];
    if(exp.length!==6)issues.push(`tickers experimentales ${exp.length}/6`);
    const status=issues.length?'REVISAR':'OK';
    const cut=live&&live.generated_at_lima?clock(live.generated_at_lima,'America/Lima')+' Lima':'—';
    box.innerHTML=`<b class="${issues.length?'neg':'pos'}">${status}</b> · corte ${cut} · OLS ${fmt(live&&live.signal_date)} · Challenger ${fmt(challenger&&challenger.signal_date)} · Nuevos tickers ${fmt(alt&&alt.signal_date)} · SBS último ${fmt(latest&&latest.latest_sbs_date)}${issues.length?'<br>'+issues.join(' · '):'<br>3 modelos y 6 tickers experimentales cargados.'}`;
  }

  async function loadAll(){
    ensureUi();
    let latest=null,live=null,challenger=null,alt=null;
    try{live=await getJson('live_market.json');renderMarket(live);}catch(e){}
    try{alt=await getJson('alt_6030_experimental.json');altData=alt;renderAltModel();}catch(e){if($('r6030AltSignal')){$('r6030AltSignal').textContent='NO DISPONIBLE';$('r6030AltSignal').className='r6030-signal down';}if($('r6030AltDateResult'))$('r6030AltDateResult').textContent='No se pudo cargar el histórico del nuevo 60/30.';}
    try{challenger=await getJson('reduced_6030_challenger.json');}catch(e){}
    try{latest=await getJson('latest.json');repairTop(latest);}catch(e){}
    renderAudit(latest,live,challenger,alt);
    if(challenger&&alt){
      const sigs=[challenger.official&&challenger.official.signal,challenger.challenger&&challenger.challenger.signal,alt.model&&alt.model.signal].filter(Boolean);
      const b=$('r6030Badge');if(b&&sigs.length===3)b.textContent=(new Set(sigs).size===1)?'3 MODELOS · MISMA SEÑAL':'3 MODELOS · SEÑALES DISTINTAS';
    }
  }

  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',loadAll,{once:true});else loadAll();
  setTimeout(loadAll,900);
  setInterval(loadAll,60000);
})();
