(function(){
'use strict';

const INITIAL = 10000;
const STATE_KEY = 'comparador_fondo3_last_query_v6';
const OLD_STATE_KEY = 'comparador_fondo3_last_query_v5';
const DRIVE_KEY = 'fondo3_drive_sync_key_v1';
const PRO_URL_KEY = 'profuturo_fondo3_drive_sync_url_v3';
const HAB_URL_KEY = 'habitat_fondo3_drive_sync_url_v3';
const PRO_DEFAULT = 'https://script.google.com/macros/s/AKfycbxY9JqIeTnweKaEXAOs7hQ6KftlPgVsGOFPwOp7hqL5gJ47OuuHlAJBksTGdOQ2yc_Y0Q/exec';
const HAB_DEFAULT = 'https://script.google.com/macros/s/AKfycbxoYHkCu0cZPx_KsMlI0Jd5PEATgxBjZTR8oK8qs1cUjRHJbiK0t-bxkH5ACprgp81S7g/exec';

let DATA = null;
const $ = id => document.getElementById(id);
const finite = x => x !== null && x !== undefined && x !== '' && Number.isFinite(Number(x));
const money = x => finite(x) ? new Intl.NumberFormat('es-PE',{style:'currency',currency:'PEN',minimumFractionDigits:2,maximumFractionDigits:2}).format(Number(x)) : '—';
const signedMoney = x => finite(x) ? `${Number(x)>=0?'+':'-'}${money(Math.abs(Number(x)))}` : '—';
const pct = x => finite(x) ? `${Number(x)>=0?'+':''}${(Number(x)*100).toFixed(2)}%` : '—';
const pctAbs = x => finite(x) ? `${(Number(x)*100).toFixed(2)}%` : '—';
const vc = x => finite(x) ? Number(x).toFixed(7) : '—';
const fmt = s => { if(!s) return '—'; const p=String(s).slice(0,10).split('-'); return p.length===3 ? `${p[2]}/${p[1]}/${p[0]}` : String(s); };

function normalizeSource(s){
  if(s==='a') return 'niveles';
  if(s==='b') return 'retornos';
  return ['sbs','niveles','retornos'].includes(s) ? s : 'sbs';
}
function readState(){
  try{
    const current = JSON.parse(localStorage.getItem(STATE_KEY)||'null');
    if(current) return {...current,source:normalizeSource(current.source)};
    const old = JSON.parse(localStorage.getItem(OLD_STATE_KEY)||'{}')||{};
    return {...old,source:normalizeSource(old.source)};
  }catch(_e){ return {}; }
}
function saveState(extra={}){
  const old=readState();
  const active=document.querySelector('#operationPanel [data-opmode].active');
  const out={
    ...old,...extra,
    source:normalizeSource($('opSource')?.value||old.source||'sbs'),
    mode:active?.dataset.opmode||old.mode||'inside',
    entry:$('opEntry')?.value||old.entry||'',
    exit:$('opExit')?.value||old.exit||'',
    capital:$('opCapital')?.value||old.capital||'10000'
  };
  try{ localStorage.setItem(STATE_KEY,JSON.stringify(out)); }catch(_e){}
}

function officialMap(rows){
  const m=new Map();
  for(const r of (Array.isArray(rows)?rows:[])){
    const d=String(r?.fecha||'').slice(0,10), v=Number(r?.vc);
    const official=r?.es_oficial===true || String(r?.fuente||'').toUpperCase().includes('SBS');
    if(d && Number.isFinite(v) && v>0 && official) m.set(d,v);
  }
  return m;
}
function fixedActualMap(db){
  const m=new Map();
  for(const r of (Array.isArray(db?.rows)?db.rows:[])){
    const d=String(r?.fecha||'').slice(0,10), v=Number(r?.vc_sbs);
    if(d && Number.isFinite(v) && v>0) m.set(d,v);
  }
  const latestDate=String(db?.latest?.latest_sbs_date || db?.latest_sbs?.fecha || '').slice(0,10);
  const latestVc=Number(db?.latest?.latest_sbs_vc ?? db?.latest_sbs?.vc);
  if(latestDate && Number.isFinite(latestVc) && latestVc>0) m.set(latestDate,latestVc);
  return m;
}
function officialHybrid(series,fixed){
  const out=officialMap(series);
  for(const [d,v] of fixedActualMap(fixed)) out.set(d,v);
  return out;
}
function fixedModelMap(db,kind){
  const field=kind==='niveles'?'vc_niveles':'vc_retornos';
  const out=new Map();
  for(const r of (Array.isArray(db?.rows)?db.rows:[])){
    const d=String(r?.fecha||'').slice(0,10), v=Number(r?.[field]);
    if(d && Number.isFinite(v) && v>0) out.set(d,v);
  }
  return out;
}
function pair(pm,hm){
  return [...pm.keys()].filter(d=>hm.has(d)).sort().map(fecha=>({fecha,profuturo:pm.get(fecha),habitat:hm.get(fecha)}));
}
function modelWindow(db,kind){
  const byModel=Number(db?.models?.[kind]?.window);
  if(Number.isFinite(byModel) && byModel>0) return byModel;
  const key=kind==='niveles'?'n_levels':'n_returns';
  const byTrainSpecific=Number(db?.training?.[key]);
  if(Number.isFinite(byTrainSpecific) && byTrainSpecific>0) return byTrainSpecific;
  const byWindow=Number(db?.window);
  if(Number.isFinite(byWindow) && byWindow>0) return byWindow;
  const byTrain=Number(db?.training?.n);
  if(Number.isFinite(byTrain) && byTrain>0) return byTrain;
  return null;
}
function sourceName(src){
  return src==='niveles'?'Niveles':src==='retornos'?'Retornos':'SBS real';
}
function fundSourceLabel(src,fund){
  if(src==='sbs') return 'SBS real';
  const n=DATA?.windows?.[src]?.[fund];
  const fundName=fund==='habitat'?'Hábitat':'Profuturo';
  return `${sourceName(src)} · ${fundName}${n?` ${n} ruedas`:''}`;
}
function sourceHint(src){
  if(src==='sbs') return `Solo VC oficiales SBS · última fecha común ${fmt(DATA?.sets?.sbs?.at(-1)?.fecha)}`;
  const h=DATA?.windows?.[src]?.habitat, p=DATA?.windows?.[src]?.profuturo;
  return `${sourceName(src)} vigente · Hábitat ${h||'—'} ruedas · Profuturo ${p||'—'} ruedas`;
}

function volatility(values){
  if(values.length<3) return null;
  const rets=[];
  for(let i=1;i<values.length;i++) rets.push(values[i]/values[i-1]-1);
  if(rets.length<2) return null;
  const mean=rets.reduce((a,b)=>a+b,0)/rets.length;
  const variance=rets.reduce((a,b)=>a+(b-mean)**2,0)/(rets.length-1);
  return Math.sqrt(variance)*Math.sqrt(252);
}
function selectMain(period){
  const all=DATA?.sbs||[];
  if(period==='all') return all.slice();
  if(period==='2026') return all.filter(r=>r.fecha>='2026-01-01');
  const n=Number(period||30);
  return all.slice(Math.max(0,all.length-n));
}
function drawMain(period){
  const rows=selectMain(period);
  if(rows.length<2) return;
  const first=rows[0], last=rows.at(-1);
  const hv=rows.map(r=>r.habitat), pv=rows.map(r=>r.profuturo);
  const h=hv.map(v=>INITIAL*v/first.habitat), p=pv.map(v=>INITIAL*v/first.profuturo);
  const hr=h.at(-1)/INITIAL-1, pr=p.at(-1)/INITIAL-1;
  const vh=volatility(hv), vp=volatility(pv);
  $('periodText').textContent=`${fmt(first.fecha)} → ${fmt(last.fecha)} · ${rows.length} fechas SBS comunes`;
  $('retHab').textContent=pct(hr); $('retPro').textContent=pct(pr);
  $('capHab').textContent=`Capital final: ${money(h.at(-1))}`; $('capPro').textContent=`Capital final: ${money(p.at(-1))}`;
  $('volHab').textContent=vh===null?'—':pctAbs(vh); $('volPro').textContent=vp===null?'—':pctAbs(vp);
  $('retHab').classList.toggle('better',hr>pr); $('retPro').classList.toggle('better',pr>hr);
  $('volHab').classList.toggle('better',vh!==null&&vp!==null&&vh<vp); $('volPro').classList.toggle('better',vh!==null&&vp!==null&&vp<vh);
  $('summary').textContent=`Mayor rentabilidad: ${hr>pr?'Hábitat':pr>hr?'Profuturo':'Empate'} · Menor volatilidad: ${vh!==null&&vp!==null?(vh<vp?'Hábitat':vp<vh?'Profuturo':'Empate'):'—'}`;
  Plotly.react('chart',[
    {x:rows.map(r=>r.fecha),y:h,type:'scatter',mode:'lines',name:`Hábitat · ${money(h.at(-1))}`,line:{width:3},hovertemplate:'<b>Hábitat</b><br>%{x}<br>Capital: S/%{y:,.2f}<extra></extra>'},
    {x:rows.map(r=>r.fecha),y:p,type:'scatter',mode:'lines',name:`Profuturo · ${money(p.at(-1))}`,line:{width:3},hovertemplate:'<b>Profuturo</b><br>%{x}<br>Capital: S/%{y:,.2f}<extra></extra>'}
  ],{paper_bgcolor:'#0f1b2d',plot_bgcolor:'#0b1728',font:{color:'#e2e8f0',size:11},margin:{l:62,r:18,t:35,b:50},hovermode:'x unified',legend:{orientation:'h',y:1.12,x:0},xaxis:{gridcolor:'#243244',title:'Fecha SBS'},yaxis:{gridcolor:'#243244',title:'Valor de la inversión (S/)',tickprefix:'S/ '},showlegend:true},{responsive:true,displaylogo:false,displayModeBar:false});
  saveState({period});
}
function installMainControls(){
  const box=$('controls'); if(!box) return;
  box.innerHTML='';
  const saved=readState().period||'30';
  for(const [k,label] of [['30','30 sesiones'],['60','60 sesiones'],['90','90 sesiones'],['180','180 sesiones'],['2026','2026'],['all','Todo']]){
    const b=document.createElement('button'); b.type='button'; b.textContent=label; b.classList.toggle('active',k===saved);
    b.onclick=()=>{[...box.children].forEach(x=>x.classList.toggle('active',x===b));drawMain(k);}; box.appendChild(b);
  }
  drawMain(saved);
}

function opRows(){ return DATA?.sets?.[normalizeSource($('opSource')?.value||'sbs')]||[]; }
function mode(){ return document.querySelector('#operationPanel [data-opmode].active')?.dataset.opmode||'inside'; }
function exactRow(date,rows){ return rows.find(r=>r.fecha===date)||null; }
function paint(id,val,isPct=false){
  const e=$(id); if(!e) return;
  e.textContent=isPct?pct(val):signedMoney(val);
  e.classList.toggle('pos',Number(val)>0); e.classList.toggle('neg',Number(val)<0);
}
function setSourceHint(){
  const src=normalizeSource($('opSource')?.value||'sbs');
  if($('opSourceHint')) $('opSourceHint').textContent=sourceHint(src);
}
function setDateBounds(){
  const rows=opRows();
  if(!rows.length) return;
  const min=rows[0].fecha,max=rows.at(-1).fecha;
  for(const id of ['opEntry','opExit']){ const e=$(id); if(e){e.min=min;e.max=max;} }
}
function ensureDatesForSource(force=false){
  const rows=opRows(); if(!rows.length) return;
  const s=readState();
  const validEntry=exactRow($('opEntry')?.value,rows);
  const validExit=exactRow($('opExit')?.value,rows);
  if(force || !validEntry){
    const preferred=s.entry && exactRow(s.entry,rows) ? s.entry : rows[Math.max(0,rows.length-20)].fecha;
    $('opEntry').value=preferred;
  }
  if(force || !validExit){
    const preferred=s.exit && exactRow(s.exit,rows) ? s.exit : rows.at(-1).fecha;
    $('opExit').value=preferred;
  }
}
function unavailableMessage(src,which,date,rows){
  const latest=rows.at(-1)?.fecha, earliest=rows[0]?.fecha;
  if(src==='sbs' && which==='salida' && latest && date>latest){
    return `SBS real aún no tiene VC común para ${fmt(date)}. La última fecha SBS común es ${fmt(latest)}. Para valorar ${fmt(date)}, elige Niveles o Retornos.`;
  }
  return `${sourceName(src)}: no existe una fecha común exacta para ${which} ${fmt(date)}. Rango disponible: ${fmt(earliest)} → ${fmt(latest)}.`;
}
function calculate(){
  const src=normalizeSource($('opSource')?.value||'sbs'), rows=opRows();
  setSourceHint(); setDateBounds();
  if(rows.length<2){ $('opWinner').textContent=`${sourceName(src)}: no hay fechas comunes suficientes.`; return; }
  const req=$('opEntry')?.value, cap=Number($('opCapital')?.value||0);
  if(!req || !Number.isFinite(cap) || cap<=0){ $('opWinner').textContent='Completa fecha de entrada y monto.'; return; }
  const entry=exactRow(req,rows);
  if(!entry){ $('opWinner').textContent=unavailableMessage(src,'entrada',req,rows); return; }
  let exit, requestedExit='';
  if(mode()==='closed'){
    requestedExit=$('opExit')?.value;
    if(!requestedExit){ $('opWinner').textContent='Indica la fecha de salida.'; return; }
    exit=exactRow(requestedExit,rows);
    if(!exit){ $('opWinner').textContent=unavailableMessage(src,'salida',requestedExit,rows); return; }
  }else exit=rows.at(-1);
  if(!exit || exit.fecha<entry.fecha){ $('opWinner').textContent='La fecha de salida debe ser igual o posterior a la entrada.'; return; }

  const hf=cap*Number(exit.habitat)/Number(entry.habitat), pf=cap*Number(exit.profuturo)/Number(entry.profuturo);
  const hg=hf-cap, pg=pf-cap, hr=hf/cap-1, pr=pf/cap-1;
  $('opHabFinal').textContent=money(hf); $('opProFinal').textContent=money(pf);
  paint('opHabGain',hg); paint('opProGain',pg); paint('opHabRet',hr,true); paint('opProRet',pr,true);
  $('opHabMeta').textContent=`${fundSourceLabel(src,'habitat')} · ${fmt(entry.fecha)} VC ${vc(entry.habitat)} → ${fmt(exit.fecha)} VC ${vc(exit.habitat)} · escala propia Hábitat`;
  $('opProMeta').textContent=`${fundSourceLabel(src,'profuturo')} · ${fmt(entry.fecha)} VC ${vc(entry.profuturo)} → ${fmt(exit.fecha)} VC ${vc(exit.profuturo)} · escala propia Profuturo`;
  const winner=hf>pf?'Hábitat':pf>hf?'Profuturo':'Empate', diff=Math.abs(hf-pf);
  $('opHabCard').classList.toggle('winner',hf>pf); $('opProCard').classList.toggle('winner',pf>hf);
  const lead=src==='sbs'?'SBS real':`${sourceName(src)} · modelos vigentes`;
  $('opWinner').textContent=winner==='Empate' ? `${lead} · empate · ${fmt(entry.fecha)} → ${fmt(exit.fecha)} · ${money(hf)}.` : `${lead} · más rentable: ${winner} · ventaja ${money(diff)} · ${fmt(entry.fecha)} → ${fmt(exit.fecha)}.`;
  saveState();
}
function installOperation(){
  const p=$('operationPanel'); if(!p) return;
  p.innerHTML=`
    <div class="head"><div><h2>Operación comparada · Hábitat vs Profuturo</h2><div class="sub">Mismo monto y mismas fechas. Elige SBS real, Niveles o Retornos. Cada AFP usa automáticamente la ventana de su modelo vigente.</div></div></div>
    <div class="opmodes"><button type="button" class="opbtn active" data-opmode="inside">Sigo dentro</button><button type="button" class="opbtn" data-opmode="closed">Ya salí</button></div>
    <div class="opinputs">
      <label>Fuente de valoración<select id="opSource"><option value="sbs">SBS real</option><option value="niveles">Niveles · modelo vigente</option><option value="retornos">Retornos · modelo vigente</option></select><span id="opSourceHint" class="sourcehint"></span></label>
      <label>Fecha de entrada<input type="date" id="opEntry"></label>
      <label>Capital invertido (S/)<input type="number" id="opCapital" value="10000" min="1" step="100"></label>
      <label id="opExitWrap" class="ophidden">Fecha de salida<input type="date" id="opExit"></label>
      <button class="opbtn primary" id="opCalc" type="button">Calcular operación</button>
    </div>
    <div class="opwinner" id="opWinner">Cargando SBS y modelos vigentes…</div>
    <div class="opresults">
      <div class="opfund" id="opHabCard"><h3>Hábitat Fondo 3</h3><div class="opmetrics"><div class="opmini"><span>Capital final</span><b id="opHabFinal">—</b></div><div class="opmini"><span>Ganancia / pérdida</span><b id="opHabGain">—</b></div><div class="opmini"><span>Rentabilidad</span><b id="opHabRet">—</b></div></div><div class="opmeta" id="opHabMeta">—</div></div>
      <div class="opfund" id="opProCard"><h3>Profuturo Fondo 3</h3><div class="opmetrics"><div class="opmini"><span>Capital final</span><b id="opProFinal">—</b></div><div class="opmini"><span>Ganancia / pérdida</span><b id="opProGain">—</b></div><div class="opmini"><span>Rentabilidad</span><b id="opProRet">—</b></div></div><div class="opmeta" id="opProMeta">—</div></div>
    </div>
    <div class="note" style="margin-top:10px"><b>Importante:</b> “SBS real” solo permite fechas con VC oficial común. Niveles y Retornos usan los modelos vigentes de cada AFP y permiten fechas estimadas posteriores al último VC SBS cuando existen en ambos modelos. No se reemplaza silenciosamente una fecha solicitada por otra.</div>`;

  const s=readState();
  $('opSource').value=normalizeSource(s.source||'sbs');
  $('opCapital').value=s.capital||'10000';
  document.querySelectorAll('#operationPanel [data-opmode]').forEach(b=>{
    b.classList.toggle('active',b.dataset.opmode===(s.mode||'inside'));
    b.onclick=()=>{
      document.querySelectorAll('#operationPanel [data-opmode]').forEach(x=>x.classList.toggle('active',x===b));
      $('opExitWrap').classList.toggle('ophidden',b.dataset.opmode!=='closed');
      calculate();
    };
  });
  $('opExitWrap').classList.toggle('ophidden',(s.mode||'inside')!=='closed');
  ensureDatesForSource(true); setDateBounds(); setSourceHint();
  $('opCalc').onclick=calculate;
  ['opEntry','opCapital','opExit'].forEach(id=>$(id).addEventListener('change',calculate));
  $('opSource').addEventListener('change',()=>{ensureDatesForSource(true);setDateBounds();setSourceHint();calculate();});
  calculate();
}

function officialCompare(entryDate,exitDate,capital,isOpen){
  const rs=DATA?.sbs||[];
  if(!rs.length || !entryDate || !finite(capital) || Number(capital)<=0) return null;
  const entry=exactRow(String(entryDate).slice(0,10),rs); if(!entry) return null;
  const exit=isOpen ? rs.at(-1) : exactRow(String(exitDate||'').slice(0,10),rs);
  if(!exit || exit.fecha<entry.fecha) return null;
  const cap=Number(capital), pf=cap*exit.profuturo/entry.profuturo, hf=cap*exit.habitat/entry.habitat;
  return{entry,exit,cap,pf,hf,pg:pf-cap,hg:hf-cap,pr:pf/cap-1,hr:hf/cap-1,diff:pf-hf};
}
function jsonp(url,fund,key){
  return new Promise((resolve,reject)=>{
    if(!key) return reject(new Error('Falta la clave de Drive'));
    const cb='__cmpv6_'+Date.now()+'_'+Math.random().toString(16).slice(2), s=document.createElement('script'); let done=false;
    const finish=(e,d)=>{if(done)return;done=true;clearTimeout(t);try{delete window[cb]}catch(_e){}s.remove();e?reject(e):resolve(d)};
    const t=setTimeout(()=>finish(new Error('Apps Script no respondió')),15000);
    window[cb]=d=>d?.ok===true?finish(null,d):finish(new Error(d?.error||'Respuesta inválida'));
    const u=new URL(url); u.searchParams.set('action','list'); u.searchParams.set('fund',fund); u.searchParams.set('key',key); u.searchParams.set('callback',cb); u.searchParams.set('_',Date.now());
    s.onerror=()=>finish(new Error('No se pudo contactar Drive')); s.src=u.toString(); document.head.appendChild(s);
  });
}
function pAfter(ref,node){ if(ref?.parentNode) ref.parentNode.insertBefore(node,ref.nextSibling); }
function installDriveHistory(){
  if($('driveHistoryPanel')) return;
  const sec=document.createElement('section'); sec.id='driveHistoryPanel'; sec.className='drivehist';
  sec.innerHTML=`<div class="drivehistbar"><div><h2 style="margin:0">Histórico comparado · operaciones de Drive</h2><div class="sub">Cada operación registrada se recalcula con las mismas fechas y el mismo capital en ambas AFP usando SBS real.</div></div><div class="drivehistconnect"><input id="driveHistKey" type="password" autocomplete="off" placeholder="Clave Drive (solo si falta)"><button id="driveHistRefresh" type="button">Actualizar</button></div></div><div class="drivehiststatus" id="driveHistStatus">Buscando la conexión de Drive guardada en este navegador…</div><div class="drivehistlist" id="driveHistList"></div>`;
  pAfter($('operationPanel'),sec);
  $('driveHistKey').value=localStorage.getItem(DRIVE_KEY)||'';
  $('driveHistRefresh').onclick=()=>{const k=$('driveHistKey').value.trim();if(k)localStorage.setItem(DRIVE_KEY,k);loadDriveHistory();};
}
function renderDriveHistory(items){
  const box=$('driveHistList'); if(!box) return;
  const sorted=items.slice().sort((a,b)=>String(b.row.created_at||b.row.entry_date||'').localeCompare(String(a.row.created_at||a.row.entry_date||''))).slice(0,12);
  if(!sorted.length){box.innerHTML='<div class="sub">No hay operaciones en Drive.</div>';return;}
  box.innerHTML=sorted.map(({fund,row})=>{
    const r=officialCompare(row.entry_date,row.exit_date,row.capital,!row.exit_date), state=row.exit_date?'CERRADA':'ABIERTA';
    const oldModel=String(row.valuation_model||'qqq')==='new_tickers'?'B':'A';
    const meta=`Registrada en ${fund==='PROFUTURO'?'Profuturo':'Hábitat'} · ${state} · modelo histórico ${oldModel} · ${fmt(row.entry_date)} → ${row.exit_date?fmt(row.exit_date):'abierta'} · ${money(row.capital)}`;
    if(!r) return `<div class="drivehistcard"><div class="drivehisthead">${meta}</div><div class="drivehistwinner">Todavía no hay SBS comunes exactos para recalcular esta operación.</div></div>`;
    const winner=r.pf>r.hf?'Profuturo':r.hf>r.pf?'Hábitat':'Empate',adv=Math.abs(r.pf-r.hf);
    return `<div class="drivehistcard"><div class="drivehisthead">${fmt(r.entry.fecha)} → ${fmt(r.exit.fecha)} · ${money(r.cap)}</div><div class="drivehistmeta">${meta}</div><div class="drivehistline"><b>Profuturo Fondo 3</b><span class="drivehistnum ${r.pg>=0?'pos':'neg'}">${signedMoney(r.pg)}</span><span class="drivehistnum ${r.pr>=0?'pos':'neg'}">${pct(r.pr)}</span></div><div class="drivehistline"><b>Hábitat Fondo 3</b><span class="drivehistnum ${r.hg>=0?'pos':'neg'}">${signedMoney(r.hg)}</span><span class="drivehistnum ${r.hr>=0?'pos':'neg'}">${pct(r.hr)}</span></div><div class="drivehistwinner">Más rentable: <b>${winner}</b>${winner==='Empate'?'':` · ventaja ${money(adv)}`} · recálculo SBS real.</div></div>`;
  }).join('');
}
async function loadDriveHistory(){
  const key=(localStorage.getItem(DRIVE_KEY)||$('driveHistKey')?.value||'').trim();
  if(!key){$('driveHistStatus').textContent='Falta la clave. Si ya conectaste Drive en Profuturo o Hábitat desde este navegador, ingrésala una vez.';return;}
  if($('driveHistKey')) $('driveHistKey').value=key;
  $('driveHistStatus').textContent='Leyendo operaciones de las hojas Profuturo y Hábitat…';
  const pu=(localStorage.getItem(PRO_URL_KEY)||PRO_DEFAULT).trim(), hu=(localStorage.getItem(HAB_URL_KEY)||HAB_DEFAULT).trim();
  try{
    const [p,h]=await Promise.all([jsonp(pu,'PROFUTURO',key),jsonp(hu,'HABITAT',key)]);
    const pr=(Array.isArray(p.rows)?p.rows:[]).filter(r=>String(r.fund||'PROFUTURO').toUpperCase()==='PROFUTURO');
    const hr=(Array.isArray(h.rows)?h.rows:[]).filter(r=>String(r.fund||'HABITAT').toUpperCase()==='HABITAT');
    renderDriveHistory([...pr.map(row=>({fund:'PROFUTURO',row})),...hr.map(row=>({fund:'HABITAT',row}))]);
    $('driveHistStatus').textContent=`Drive conectado · ${pr.length} operaciones Profuturo · ${hr.length} operaciones Hábitat · se muestran las 12 más recientes.`;
  }catch(e){ $('driveHistStatus').textContent='No se pudo leer Drive: '+String(e.message||e); }
}

function showError(e){
  const err=$('error'); if(err){err.style.display='block';err.textContent='No se pudieron cargar los datos consolidados: '+String(e.message||e);}
}
async function boot(){
  try{
    const q='?c='+Date.now();
    const [ps,hs,pf,hf]=await Promise.all([
      fetch('../data/series.json'+q,{cache:'no-store'}).then(r=>{if(!r.ok)throw Error('Profuturo SBS');return r.json();}),
      fetch('../habitat/data/series.json'+q,{cache:'no-store'}).then(r=>{if(!r.ok)throw Error('Hábitat SBS');return r.json();}),
      fetch('../data/fixed_models_2026.json'+q,{cache:'no-store'}).then(r=>{if(!r.ok)throw Error('Profuturo modelos vigentes');return r.json();}),
      fetch('../habitat/data/fixed_models_2026.json'+q,{cache:'no-store'}).then(r=>{if(!r.ok)throw Error('Hábitat modelos vigentes');return r.json();})
    ]);
    const pOfficial=officialHybrid(ps,pf), hOfficial=officialHybrid(hs,hf);
    const sbs=pair(pOfficial,hOfficial);
    const niveles=pair(fixedModelMap(pf,'niveles'),fixedModelMap(hf,'niveles'));
    const retornos=pair(fixedModelMap(pf,'retornos'),fixedModelMap(hf,'retornos'));
    DATA={
      sbs,
      sets:{sbs,niveles,retornos},
      windows:{
        niveles:{profuturo:modelWindow(pf,'niveles'),habitat:modelWindow(hf,'niveles')},
        retornos:{profuturo:modelWindow(pf,'retornos'),habitat:modelWindow(hf,'retornos')}
      }
    };
    if(sbs.length<2) throw Error('No se encontraron valores cuota SBS comunes.');
    installMainControls(); installOperation(); installDriveHistory();
    if(localStorage.getItem(DRIVE_KEY)) loadDriveHistory();
  }catch(e){ showError(e); }
}

if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',boot,{once:true}); else boot();
})();
