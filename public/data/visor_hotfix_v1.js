(function(){
  'use strict';
  const BRANCH='migracion-github-actions';
  const RAW='https://raw.githubusercontent.com/rldaqp/afp-fondo3-monitor/'+BRANCH+'/public/data/';
  const TRADE_KEY='profuturo_fondo3_trade_history_v3';
  const FUND='PROFUTURO';
  const ORIGIN='VISOR GITHUB · PROFUTURO';
  const $=id=>document.getElementById(id);
  const finite=x=>x!==null&&x!==undefined&&x!==''&&Number.isFinite(Number(x));
  const fmt=d=>{if(!d)return'—';const p=String(d).slice(0,10).split('-');return p.length===3?`${p[2]}/${p[1]}/${p[0]}`:String(d)};
  const money=x=>new Intl.NumberFormat('es-PE',{style:'currency',currency:'PEN'}).format(Number(x));
  const uid=()=>`${Date.now()}-${Math.random().toString(16).slice(2)}`;
  let alt=null,series=[],signals=[];

  async function getJson(name){
    const ts=Date.now(),urls=['data/'+name+'?ts='+ts,RAW+name+'?ts='+ts];let last=null;
    for(const u of urls){try{const r=await fetch(u,{cache:'no-store'});if(!r.ok)throw new Error('HTTP '+r.status);return await r.json()}catch(e){last=e}}
    throw last||new Error('No disponible '+name);
  }

  function officialMap(){
    const m=new Map();
    (series||[]).forEach(r=>{if(r&&r.fecha&&r.fuente==='SBS OFICIAL'&&finite(r.vc))m.set(String(r.fecha).slice(0,10),Number(r.vc))});
    ((alt&&alt.operational_history)||[]).forEach(r=>{if(r&&r.fecha&&finite(r.actual_vc))m.set(String(r.fecha).slice(0,10),Number(r.actual_vc))});
    const model=alt&&alt.model||{};if(model.sbs_anchor_date&&finite(model.sbs_anchor_vc))m.set(String(model.sbs_anchor_date).slice(0,10),Number(model.sbs_anchor_vc));
    return m;
  }

  function estimateMap(){
    const m=new Map();
    (signals||[]).forEach(r=>{if(r&&r.fecha&&finite(r.vc_estimado))m.set(String(r.fecha).slice(0,10),Number(r.vc_estimado))});
    ((alt&&alt.operational_history)||[]).forEach(r=>{if(r&&r.fecha&&finite(r.vc))m.set(String(r.fecha).slice(0,10),Number(r.vc))});
    if(alt&&alt.signal_date&&finite(alt.model&&alt.model.vc_estimated))m.set(String(alt.signal_date).slice(0,10),Number(alt.model.vc_estimated));
    return m;
  }

  function timelineDates(){
    const s=new Set();
    (series||[]).forEach(r=>{if(r&&r.fecha)s.add(String(r.fecha).slice(0,10))});
    ((alt&&alt.operational_history)||[]).forEach(r=>{if(r&&r.fecha)s.add(String(r.fecha).slice(0,10))});
    if(alt&&alt.signal_date)s.add(String(alt.signal_date).slice(0,10));
    return [...s].sort();
  }

  function effective(requested,direction){
    const ds=timelineDates();
    if(direction==='entry')return ds.find(d=>d>=requested)||requested;
    return [...ds].reverse().find(d=>d<=requested)||requested;
  }

  function updateTopSbs(){
    const m=alt&&alt.model||{};if(!m.sbs_anchor_date||!finite(m.sbs_anchor_vc))return;
    const v=$('sbsVc'),d=$('sbsDate');if(v)v.textContent=Number(m.sbs_anchor_vc).toFixed(7);if(d)d.textContent=fmt(m.sbs_anchor_date)+' · SBS OFICIAL';
  }

  function currentMode(){return document.querySelector('.tabs button.active')?.dataset.mode||'monitor'}

  function bindOperationTabs(){
    const tabs=[...document.querySelectorAll('.tabs button[data-mode]')],op=$('operation'),exitBox=$('exitBox');
    tabs.forEach(btn=>{
      btn.disabled=false;btn.removeAttribute('disabled');btn.removeAttribute('aria-disabled');btn.style.pointerEvents='auto';btn.style.opacity='1';btn.style.cursor='pointer';
      btn.onclick=()=>{
        tabs.forEach(x=>x.classList.toggle('active',x===btn));
        const mode=btn.dataset.mode;if(op)op.classList.toggle('hidden',mode==='monitor');if(exitBox)exitBox.classList.toggle('hidden',mode!=='closed');
        const max=(alt&&alt.signal_date)||timelineDates().at(-1)||'';
        if($('entry')){const ds=timelineDates();if(ds.length)$('entry').min=ds[0];if(max)$('entry').max=max;if(mode!=='monitor'&&!$('entry').value)$('entry').value=max;}
        if($('exit')){const ds=timelineDates();if(ds.length)$('exit').min=ds[0];if(max)$('exit').max=max;if(mode==='closed'&&!$('exit').value)$('exit').value=max;}
        if($('tradeMsg'))$('tradeMsg').textContent=mode==='inside'?'Sigo dentro activo. Completa fecha/capital y presiona Registrar operación.':mode==='closed'?'Ya salí activo. Completa entrada/salida/capital y presiona Registrar operación.':'Solo monitoreo.';
      };
    });
    const save=$('tradeSaveBtn');if(save){save.disabled=false;save.removeAttribute('disabled');save.removeAttribute('aria-disabled');save.style.pointerEvents='auto';save.style.opacity='1';save.style.cursor='pointer';save.onclick=saveCurrentHotfix;}
    if(op&&!$('tradeSaveInlineHotfix')){
      const b=document.createElement('button');b.type='button';b.id='tradeSaveInlineHotfix';b.className='primary';b.style.cssText='width:100%;margin-top:10px;background:#15803d;border-color:#16a34a';b.textContent='✓ Registrar operación';b.onclick=saveCurrentHotfix;op.appendChild(b);
    }
    const calc=$('calc');if(calc){calc.disabled=false;calc.removeAttribute('disabled');calc.style.pointerEvents='auto';calc.onclick=calcHotfix;}
  }

  function readTrades(){try{const x=JSON.parse(localStorage.getItem(TRADE_KEY)||'[]');return Array.isArray(x)?x:[]}catch(e){return []}}
  function writeTrades(rows){localStorage.setItem(TRADE_KEY,JSON.stringify(rows));window.dispatchEvent(new Event('fondo3-local-trade-change'));}

  function patchExistingTrades(){
    const off=officialMap(),rows=readTrades();let changed=false;
    rows.forEach(r=>{
      if(r.entry_date&&off.has(String(r.entry_date).slice(0,10))&&Number(r.entry_sbs_vc)!==off.get(String(r.entry_date).slice(0,10))){r.entry_sbs_vc=off.get(String(r.entry_date).slice(0,10));changed=true}
      if(r.exit_date&&off.has(String(r.exit_date).slice(0,10))&&Number(r.exit_sbs_vc)!==off.get(String(r.exit_date).slice(0,10))){r.exit_sbs_vc=off.get(String(r.exit_date).slice(0,10));changed=true}
    });
    if(changed)localStorage.setItem(TRADE_KEY,JSON.stringify(rows));
  }

  function saveCurrentHotfix(){
    const mode=currentMode();if(mode==='monitor'){if($('tradeMsg'))$('tradeMsg').textContent='Selecciona “Sigo dentro” o “Ya salí” antes de registrar.';return;}
    const requested=$('entry')?.value,capital=Number($('capital')?.value||0);if(!requested||!finite(capital)||capital<=0){if($('tradeMsg'))$('tradeMsg').textContent='Completa fecha de entrada y capital.';return;}
    const off=officialMap(),est=estimateMap();const entryDate=effective(requested,'entry');
    let exitRequested=null,exitDate=null;
    if(mode==='closed'){exitRequested=$('exit')?.value;if(!exitRequested){if($('tradeMsg'))$('tradeMsg').textContent='Indica la fecha de salida.';return;}exitDate=effective(exitRequested,'exit');if(exitDate<entryDate){if($('tradeMsg'))$('tradeMsg').textContent='La fecha de salida no es válida.';return;}}
    const rows=readTrades();let row=rows.find(r=>!r.exit_date&&String(r.entry_date)===entryDate);
    if(row&&mode==='closed'){
      row.exit_requested=exitRequested;row.exit_date=exitDate;row.exit_est_vc=est.has(exitDate)?est.get(exitDate):null;row.exit_sbs_vc=off.has(exitDate)?off.get(exitDate):null;row.closed_at=new Date().toISOString();row.confirmed=false;row.capital=capital;
    }else{
      row={id:uid(),fund:FUND,origin:ORIGIN,created_at:new Date().toISOString(),confirmed:false,capital,entry_requested:requested,entry_date:entryDate,entry_est_vc:est.has(entryDate)?est.get(entryDate):null,entry_sbs_vc:off.has(entryDate)?off.get(entryDate):null,exit_requested:exitRequested,exit_date:exitDate,exit_est_vc:exitDate&&est.has(exitDate)?est.get(exitDate):null,exit_sbs_vc:exitDate&&off.has(exitDate)?off.get(exitDate):null};rows.push(row);
    }
    writeTrades(rows);if($('tradeMsg'))$('tradeMsg').textContent=mode==='closed'?'Operación cerrada registrada.':'Operación abierta registrada.';
    setTimeout(()=>window.dispatchEvent(new Event('fondo3-cloud-synced')),50);
  }

  function calcHotfix(){
    const mode=currentMode();if(mode==='monitor')return;
    const requested=$('entry')?.value,capital=Number($('capital')?.value||0);if(!requested||!finite(capital)||capital<=0){if($('detail'))$('detail').textContent='Completa fecha y capital.';return;}
    const off=officialMap(),est=estimateMap(),entryDate=effective(requested,'entry');
    const entryVc=off.has(entryDate)?off.get(entryDate):(est.has(entryDate)?est.get(entryDate):null);
    const outReq=mode==='closed'?$('exit')?.value:((alt&&alt.signal_date)||timelineDates().at(-1));if(!outReq||!finite(entryVc)){if($('detail'))$('detail').textContent='No existe VC para calcular la operación.';return;}
    const outDate=mode==='closed'?effective(outReq,'exit'):outReq;const outVc=off.has(outDate)?off.get(outDate):(est.has(outDate)?est.get(outDate):null);if(!finite(outVc)){if($('detail'))$('detail').textContent='No existe VC para la valoración/salida seleccionada.';return;}
    const units=capital/entryVc,final=units*outVc,gain=final-capital,rent=final/capital-1;
    if($('mCapital'))$('mCapital').textContent=money(capital);if($('mFinal'))$('mFinal').textContent=money(final);if($('mGain'))$('mGain').textContent=money(gain);if($('mRent'))$('mRent').textContent=(rent*100).toFixed(2)+'%';
    if($('detail'))$('detail').innerHTML=`<b>${off.has(outDate)?'VC SBS OFICIAL':'VC ESTIMADO'}</b><br>Entrada efectiva: ${fmt(entryDate)} · VC ${Number(entryVc).toFixed(7)}${off.has(entryDate)?' · SBS OFICIAL':' · estimado'}<br>${mode==='closed'?'Salida':'Valoración'}: ${fmt(outDate)} · VC ${Number(outVc).toFixed(7)}${off.has(outDate)?' · SBS OFICIAL':' · estimado'}<br>Número de cuotas: ${units.toFixed(6)}<br>Ganancia/pérdida: <b>${money(gain)}</b>`;
  }

  async function refresh(){
    try{[alt,series,signals]=await Promise.all([getJson('alt_6030_experimental.json'),getJson('series.json').catch(()=>[]),getJson('signals.json').catch(()=>[])]);updateTopSbs();patchExistingTrades();bindOperationTabs();}
    catch(e){bindOperationTabs();if($('tradeMsg'))$('tradeMsg').textContent='Controles activos; esperando actualización de datos: '+e.message;}
  }

  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',refresh,{once:true});else refresh();
  setTimeout(refresh,1500);setInterval(refresh,30000);
})();
