(function(){
'use strict';
const DATA_URL='data/fixed_models_2026.json';
const LIVE_URL='data/fixed_models_intraday.json';
const FUND='PROFUTURO';
const ORIGIN='VISOR GITHUB · PROFUTURO · NIVELES/RETORNOS';
const TRADE_KEY='profuturo_fondo3_trade_history_v3';
const LEGACY_KEYS=['profuturo_fondo3_trade_history_v2','fondo3_trade_history_v1','profuturo_fondo3_trade_history_v1'];
const URL_KEY='profuturo_fondo3_drive_sync_url_v3';
const SECRET_KEY='fondo3_drive_sync_key_v1';
const SNAP_KEY='profuturo_fondo3_drive_sync_snapshot_v3';
const DEFAULT_URL='https://script.google.com/macros/s/AKfycbxY9JqIeTnweKaEXAOs7hQ6KftlPgVsGOFPwOp7hqL5gJ47OuuHlAJBksTGdOQ2yc_Y0Q/exec';
let DB=null,LIVE=null,syncing=false,pendingSync=false,dataError=null,hasCalculated=false;
const $=id=>document.getElementById(id);
const finite=x=>x!==null&&x!==undefined&&x!==''&&Number.isFinite(Number(x));
const fmt=d=>{if(!d)return'—';const p=String(d).slice(0,10).split('-');return p.length===3?`${p[2]}/${p[1]}/${p[0]}`:String(d)};
const vc=x=>finite(x)?Number(x).toFixed(7):'—';
const pct=x=>finite(x)?`${Number(x)>=0?'+':''}${(Number(x)*100).toFixed(2)}%`:'—';
const money=x=>finite(x)?new Intl.NumberFormat('es-PE',{style:'currency',currency:'PEN'}).format(Number(x)):'—';
const uid=()=>`${Date.now()}-${Math.random().toString(16).slice(2)}`;

function readJson(k,fb){try{const x=JSON.parse(localStorage.getItem(k)||'');return x??fb}catch(e){return fb}}
function normalize(list,source){return(Array.isArray(list)?list:[]).filter(x=>x&&typeof x==='object').map((x,i)=>x.id?x:{...x,id:`legacy-${source}-${i}-${x.created_at||''}-${x.entry_date||''}`})}
function loadRows(){
  const groups=[normalize(readJson(TRADE_KEY,[]),TRADE_KEY),...LEGACY_KEYS.map(k=>normalize(readJson(k,[]),k))];
  const m=new Map();
  groups.flat().forEach(r=>{if(!r||!r.id)return;if(r.fund&&String(r.fund).toUpperCase()!==FUND)return;m.set(String(r.id),{...(m.get(String(r.id))||{}),...r,fund:FUND})});
  const rows=[...m.values()];
  if(JSON.stringify(rows)!==JSON.stringify(normalize(readJson(TRADE_KEY,[]),TRADE_KEY)))localStorage.setItem(TRADE_KEY,JSON.stringify(rows));
  return rows;
}
function saveRows(rows,notify=true){
  const clean=(Array.isArray(rows)?rows:[]).map(r=>({...r,fund:FUND,origin:r.origin||ORIGIN}));
  localStorage.setItem(TRADE_KEY,JSON.stringify(clean));
  if(notify)window.dispatchEvent(new Event('fondo3-local-trade-change'));
}
function modelLabel(k){
  if(k==='niveles')return'Modelo niveles';
  if(k==='retornos')return'Modelo retornos';
  if(k==='new_tickers')return'Modelo anterior B';
  if(k==='qqq')return'Modelo anterior A';
  return String(k||'Modelo');
}
function modelField(k){return k==='niveles'?'vc_niveles':'vc_retornos'}
function rows(){return Array.isArray(DB?.rows)?DB.rows:[]}
function officialMap(){const out=new Map();for(const r of rows())if(r?.fecha&&finite(r.vc_sbs))out.set(String(r.fecha).slice(0,10),Number(r.vc_sbs));return out}
function historicalDates(){return[...new Set(rows().filter(r=>r?.fecha).map(r=>String(r.fecha).slice(0,10)))].sort()}
function liveDate(){
  const d=String(LIVE?.signal_date||'').slice(0,10),last=historicalDates().at(-1)||'';
  const complete=['niveles','retornos'].every(k=>finite(LIVE?.models?.[k]?.vc_intraday)&&Number(LIVE.models[k].vc_intraday)>0);
  return /^\d{4}-\d{2}-\d{2}$/.test(d)&&complete&&(!last||d>=last)?d:null;
}
function estimateMap(k){
  const f=modelField(k),out=new Map();
  for(const r of rows())if(r?.fecha&&finite(r[f]))out.set(String(r.fecha).slice(0,10),Number(r[f]));
  const d=liveDate(),v=LIVE?.models?.[k]?.vc_intraday;if(d&&finite(v))out.set(d,Number(v));
  return out;
}
function timelineDates(){const ds=historicalDates(),d=liveDate();return d?[...new Set([...ds,d])].sort():ds}
function effective(requested,direction){const ds=timelineDates();if(direction==='entry')return ds.find(d=>d>=requested)||null;return[...ds].reverse().find(d=>d<=requested)||null}
function selectedModel(){return $('tradeModel')?.value||'retornos'}
function estimatedAt(date,key){const m=estimateMap(key);return m.has(date)?m.get(date):null}
function actualAt(date){const m=officialMap();return m.has(date)?m.get(date):null}
function liveQuality(){
  const expected=['SPY','EEM','MCHI','QQQ','SPBLSCUP'],d=liveDate(),tickers=Array.isArray(LIVE?.tickers)?LIVE.tickers:[];
  const pending=expected.filter(name=>{const matches=tickers.filter(t=>t?.ticker===name);return matches.length!==1||matches[0].fresh!==true||String(matches[0].timestamp||'').slice(0,10)!==d||(!LIVE?.market_open&&matches[0].close_confirmed===false)});
  return{fresh:expected.length-pending.length,total:expected.length,pending};
}
function valueSource(date,official){
  if(official!==null)return'SBS OFICIAL';
  if(date!==liveDate())return'ESTIMADO · SBS PENDIENTE';
  const q=liveQuality(),label=LIVE?.market_open?'SNAPSHOT INTRADÍA':q.pending.length?'CIERRE PROVISIONAL':'CIERRE ESTIMADO';
  return`${label}${q.pending.length?` · ${q.fresh}/${q.total} FACTORES`:''} · SBS PENDIENTE`;
}
function renderDataStatus(){
  const el=$('tradeDataStatus');if(!el)return;
  if(dataError){el.className='trademsg pending';el.textContent=dataError;return}
  const d=liveDate();el.className='trademsg';
  if(!d){el.textContent=`Histórico disponible hasta ${fmt(historicalDates().at(-1))}. No hay un snapshot más reciente utilizable.`;return}
  const q=liveQuality(),sbs=actualAt(d)===null?'VC SBS de esa fecha pendiente.':'VC SBS de esa fecha disponible.';
  if(q.pending.length){el.className+=' pending';el.textContent=`CÁLCULO PROVISIONAL · ${fmt(d)} · factores actualizados ${q.fresh}/${q.total}. Pendientes: ${q.pending.join(', ')}. No es un cierre consolidado. ${sbs}`}
  else el.textContent=`${LIVE?.market_open?'Snapshot intradía provisional':'Cierre estimado'} disponible: ${fmt(d)} · factores actualizados ${q.fresh}/${q.total}. ${sbs}`;
}
function refreshDateInputs(reset=false){
  const ds=timelineDates(),min=ds[0]||'',max=ds.at(-1)||'';
  for(const id of ['tradeEntry','tradeExit']){const input=$(id);if(!input)continue;const oldMax=input.max||'';input.min=min;input.max=max;if(max&&(reset||!input.value||input.value===oldMax))input.value=max}
  renderDataStatus();
}

function installStyles(){
  if($('fixedTradeStyles'))return;
  const st=document.createElement('style');st.id='fixedTradeStyles';st.textContent=`
  .tradepanel{border:1px solid var(--line);background:var(--card);border-radius:15px;padding:14px;margin:14px 0}.tradehead{display:flex;justify-content:space-between;gap:10px;align-items:flex-start;flex-wrap:wrap}.tradetabs{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-top:10px}.tradetabs button,.tradebtn{border:1px solid #35465d;background:#132943;color:#fff;border-radius:9px;padding:9px;font-weight:800;cursor:pointer}.tradetabs button.active,.tradebtn.primary{background:#1f5275;border-color:#42c8f5}.tradeinputs{display:grid;grid-template-columns:repeat(4,1fr);gap:7px;margin-top:9px}.tradeinputs label{font-size:.7rem;color:var(--muted)}.tradeinputs input,.tradeinputs select,.cloudgrid input{width:100%;margin-top:4px;background:#07111f;color:#fff;border:1px solid #35465d;border-radius:8px;padding:9px}.trademetrics{display:grid;grid-template-columns:repeat(4,1fr);gap:7px;margin-top:9px}.trademini{background:#0a1726;border:1px solid var(--line);border-radius:9px;padding:8px}.trademini span{font-size:.68rem;color:var(--muted)}.trademini b{display:block;margin-top:3px;font-size:.88rem}.trademsg{font-size:.72rem;color:var(--muted);margin-top:7px;line-height:1.45}.tradehidden{display:none!important}.tradeactions{display:grid;grid-template-columns:1fr 1fr;gap:7px;margin-top:9px}.tradebtn.save{background:#15803d;border-color:#16a34a}.tradehistory{overflow-x:auto;margin-top:10px}.tradetable{width:100%;min-width:1120px;border-collapse:collapse;font-size:.69rem}.tradetable th,.tradetable td{border-bottom:1px solid var(--line);padding:7px 6px;text-align:right;white-space:nowrap}.tradetable th:first-child,.tradetable td:first-child{text-align:left}.tb{display:inline-block;border-radius:999px;padding:3px 6px;font-weight:850;font-size:.62rem}.bopen{background:#78350f;color:#fde68a}.bclosed{background:#164e63;color:#a5f3fc}.bconfirm{background:#14532d;color:#bbf7d0}.pending{color:#fbbf24}.real{color:#4ade80}.cloudbox{margin-top:10px;padding:9px;border:1px solid #29415e;border-radius:9px;background:#0a1625}.cloudgrid{display:grid;grid-template-columns:2fr 1.2fr auto;gap:6px}.cloudgrid button{border:1px solid #1d4ed8;background:#2563eb;color:#fff;border-radius:8px;padding:9px 11px;font-weight:800;cursor:pointer}.cloudstatus{font-size:.68rem;color:var(--muted);margin-top:6px}.cloud-ok{color:#4ade80}.cloud-warn{color:#fbbf24}.cloud-bad{color:#f87171}.traderowbtn{border:1px solid #35465d;background:#132238;color:#fff;border-radius:7px;padding:5px 7px;font-size:.62rem;cursor:pointer}.traderowbtn.del{background:#7f1d1d}.traderowbtn.ok{background:#166534}
  @media(max-width:850px){.tradeinputs,.trademetrics{grid-template-columns:repeat(2,1fr)}.cloudgrid{grid-template-columns:1fr}}@media(max-width:520px){.tradeinputs,.trademetrics{grid-template-columns:1fr 1fr}.tradetabs{grid-template-columns:1fr}}
  `;document.head.appendChild(st);
}
function installPanel(){
  if($('fixedTradePanel'))return;
  const panel=document.createElement('section');panel.className='tradepanel';panel.id='fixedTradePanel';panel.innerHTML=`
  <div class="tradehead"><div><h2 style="margin:0">Mis operaciones · Profuturo Fondo 3</h2><div class="sub">Mismo registro y sincronización con tu hoja “Operaciones Fondo 3” en Drive. Las nuevas operaciones pueden valorarse con Niveles o Retornos.</div></div><div class="small" id="tradeCloudBadge">Drive: verificando…</div></div>
  <div class="tradetabs"><button type="button" data-trademode="monitor" class="active">Solo monitorear</button><button type="button" data-trademode="inside">Sigo dentro</button><button type="button" data-trademode="closed">Ya salí</button></div>
  <div id="tradeForm" class="tradehidden">
    <div class="tradeinputs">
      <label>Modelo para valoración<select id="tradeModel"><option value="retornos">Modelo retornos</option><option value="niveles">Modelo niveles</option></select></label>
      <label>Fecha de entrada<input type="date" id="tradeEntry"></label>
      <label>Capital invertido (S/)<input type="number" id="tradeCapital" value="25000" min="1" step="100"></label>
      <label id="tradeExitWrap" class="tradehidden">Fecha de salida<input type="date" id="tradeExit"></label>
    </div>
    <div class="tradeactions"><button class="tradebtn primary" id="tradeCalc" type="button">Calcular</button><button class="tradebtn save" id="tradeSave" type="button">✓ Registrar operación</button></div>
    <div class="trademetrics"><div class="trademini"><span>Capital</span><b id="tradeMCap">—</b></div><div class="trademini"><span>Valor actual/final</span><b id="tradeMFinal">—</b></div><div class="trademini"><span>Ganancia/pérdida</span><b id="tradeMGain">—</b></div><div class="trademini"><span>Rentabilidad</span><b id="tradeMRet">—</b></div></div>
    <div class="trademsg" id="tradeDetail">Elige modo, fecha y capital. Si SBS aún no publicó esa fecha, se usa el modelo seleccionado para la valoración provisional.</div>
    <div class="trademsg" id="tradeDataStatus" role="status"></div>
  </div>
  <div class="cloudbox"><div style="font-size:.74rem;font-weight:850">Google Drive · Operaciones Fondo 3</div><div class="cloudgrid"><input id="tradeCloudUrl" type="url" placeholder="URL Apps Script /exec"><input id="tradeCloudKey" type="password" autocomplete="off" placeholder="Clave de Config"><button id="tradeCloudConnect" type="button">Conectar Drive</button></div><div class="cloudstatus" id="tradeCloudStatus">Cargando configuración anterior…</div></div>
  <div style="display:flex;justify-content:space-between;gap:8px;align-items:center;margin-top:10px"><h3 style="margin:0">Histórico de entradas y salidas</h3><div class="small" id="tradeCount">0 operaciones</div></div>
  <div class="tradehistory"><table class="tradetable"><thead><tr><th>Estado</th><th>Entrada</th><th>Modelo</th><th>VC est. entrada</th><th>VC SBS entrada</th><th>Salida</th><th>VC est. salida</th><th>VC SBS salida</th><th>Ret. est.</th><th>Ret. SBS</th><th>Gan./Pérd. est.</th><th>Gan./Pérd. SBS</th><th>Capital</th><th>Acciones</th></tr></thead><tbody id="tradeBody"></tbody></table></div>`;
  const anchor=$('operationsAnchor')||document.querySelector('main')||document.body;anchor.appendChild(panel);
}
function currentMode(){return document.querySelector('[data-trademode].active')?.dataset.trademode||'monitor'}
function bindTabs(){document.querySelectorAll('[data-trademode]').forEach(btn=>btn.onclick=()=>{document.querySelectorAll('[data-trademode]').forEach(x=>x.classList.toggle('active',x===btn));const mode=btn.dataset.trademode;$('tradeForm').classList.toggle('tradehidden',mode==='monitor');$('tradeExitWrap').classList.toggle('tradehidden',mode!=='closed');refreshDateInputs();$('tradeDetail').textContent=mode==='inside'?'Posición abierta: el último cierre/snapshot del visor puede usarse aunque el VC SBS siga pendiente.':'Cierre: indica entrada, salida y capital.'})}
function calc(){
  if(dataError){renderDataStatus();return}
  const mode=currentMode();if(mode==='monitor')return;
  const entryReq=$('tradeEntry').value,cap=Number($('tradeCapital').value||0),key=selectedModel();
  if(!entryReq||!finite(cap)||cap<=0){$('tradeDetail').textContent='Completa fecha de entrada y capital.';return}
  const ed=effective(entryReq,'entry');if(!ed){$('tradeDetail').textContent='No existe fecha efectiva de entrada.';return}
  const eo=actualAt(ed),ee=estimatedAt(ed,key),ev=eo??ee;if(!finite(ev)){$('tradeDetail').textContent='No hay VC disponible para la entrada.';return}
  let xd=null,xo=null,xe=null,xv=null;
  if(mode==='closed'){const xreq=$('tradeExit').value;if(!xreq){$('tradeDetail').textContent='Indica fecha de salida.';return}xd=effective(xreq,'exit');if(!xd||xd<ed){$('tradeDetail').textContent='La fecha de salida no es válida.';return}xo=actualAt(xd);xe=estimatedAt(xd,key);xv=xo??xe}else{xd=timelineDates().at(-1);xo=actualAt(xd);xe=estimatedAt(xd,key);xv=xo??xe}
  if(!finite(xv)){$('tradeDetail').textContent='No hay VC disponible para valorar la posición.';return}
  const units=cap/Number(ev),final=units*Number(xv),gain=final-cap,ret=final/cap-1;
  hasCalculated=true;
  $('tradeMCap').textContent=money(cap);$('tradeMFinal').textContent=money(final);$('tradeMGain').textContent=money(gain);$('tradeMRet').textContent=pct(ret);
  const nE=estimatedAt(ed,'niveles'),rE=estimatedAt(ed,'retornos'),nX=estimatedAt(xd,'niveles'),rX=estimatedAt(xd,'retornos');
  $('tradeDetail').innerHTML=`<b>${modelLabel(key)}</b> · entrada ${fmt(ed)}: ${vc(ev)} · ${valueSource(ed,eo)}<br>${mode==='closed'?'Salida':'Valoración'} ${fmt(xd)}: ${vc(xv)} · ${valueSource(xd,xo)}<br>Niveles: ${vc(nE)} → ${vc(nX)} · Retornos: ${vc(rE)} → ${vc(rX)} · cuotas: ${units.toFixed(6)}`;
}
function saveCurrent(){
  if(dataError){renderDataStatus();return}
  const mode=currentMode();if(mode==='monitor'){$('tradeDetail').textContent='Selecciona “Sigo dentro” o “Ya salí”.';return}
  const er=$('tradeEntry').value,cap=Number($('tradeCapital').value||0),key=selectedModel();if(!er||!finite(cap)||cap<=0){$('tradeDetail').textContent='Completa fecha de entrada y capital.';return}
  const ed=effective(er,'entry');if(!ed){$('tradeDetail').textContent='No existe fecha efectiva de entrada.';return}
  const eN=estimatedAt(ed,'niveles'),eR=estimatedAt(ed,'retornos'),eO=actualAt(ed),eSel=estimatedAt(ed,key);if(!finite(eO)&&!finite(eSel)){$('tradeDetail').textContent='No existe VC para registrar la entrada.';return}
  let xreq=null,xd=null,xN=null,xR=null,xO=null,xSel=null;
  if(mode==='closed'){xreq=$('tradeExit').value;if(!xreq){$('tradeDetail').textContent='Indica fecha de salida.';return}xd=effective(xreq,'exit');if(!xd||xd<ed){$('tradeDetail').textContent='Salida no válida.';return}xN=estimatedAt(xd,'niveles');xR=estimatedAt(xd,'retornos');xO=actualAt(xd);xSel=estimatedAt(xd,key);if(!finite(xO)&&!finite(xSel)){$('tradeDetail').textContent='No existe VC para registrar la salida.';return}}
  const rs=loadRows();let row=rs.find(r=>!r.exit_date&&String(r.entry_date)===ed);
  const common={capital:cap,valuation_model:key,entry_requested:er,entry_date:ed,entry_est_vc:eSel,entry_model_a_vc:eN,entry_model_b_vc:eR,entry_sbs_vc:eO,exit_requested:xreq,exit_date:xd,exit_est_vc:xSel,exit_model_a_vc:xN,exit_model_b_vc:xR,exit_sbs_vc:xO};
  if(row&&mode==='closed')Object.assign(row,common,{closed_at:new Date().toISOString(),confirmed:false});
  else{row={id:uid(),fund:FUND,origin:ORIGIN,created_at:new Date().toISOString(),confirmed:false,...common};rs.push(row)}
  saveRows(rs);renderHistory();$('tradeDetail').textContent=mode==='closed'?'Operación cerrada registrada. Sincronizando con Drive…':'Operación abierta registrada. Sincronizando con Drive…';
}
function reconcile(rs){let changed=false;for(const r of rs){const e=actualAt(String(r.entry_date||'').slice(0,10));if(e!==null&&!finite(r.entry_sbs_vc)){r.entry_sbs_vc=e;changed=true}if(r.exit_date){const x=actualAt(String(r.exit_date).slice(0,10));if(x!==null&&!finite(r.exit_sbs_vc)){r.exit_sbs_vc=x;changed=true}}}if(changed)saveRows(rs);return rs}
function rowMetrics(r){const entryBase=finite(r.entry_sbs_vc)?Number(r.entry_sbs_vc):(finite(r.entry_est_vc)?Number(r.entry_est_vc):null);const re=entryBase!==null&&entryBase!==0&&finite(r.exit_est_vc)?Number(r.exit_est_vc)/entryBase-1:null;const rr=finite(r.entry_sbs_vc)&&finite(r.exit_sbs_vc)&&Number(r.entry_sbs_vc)!==0?Number(r.exit_sbs_vc)/Number(r.entry_sbs_vc)-1:null;const cap=finite(r.capital)?Number(r.capital):null;return{re,rr,ge:re!==null&&cap!==null?cap*re:null,gr:rr!==null&&cap!==null?cap*rr:null}}
function renderHistory(){
  const rs=reconcile(loadRows()).sort((a,b)=>String(b.created_at||'').localeCompare(String(a.created_at||''))),body=$('tradeBody');if(!body)return;$('tradeCount').textContent=`${rs.length} ${rs.length===1?'operación':'operaciones'}`;
  if(!rs.length){body.innerHTML='<tr><td colspan="14" style="text-align:center;color:#9aa9bd">Sin operaciones guardadas.</td></tr>';return}
  body.innerHTML=rs.map(r=>{const m=rowMetrics(r),closed=!!r.exit_date,state=closed?'<span class="tb bclosed">CERRADA</span>':'<span class="tb bopen">ABIERTA</span>',sE=finite(r.entry_sbs_vc)?`<span class="real">${vc(r.entry_sbs_vc)}</span>`:'<span class="pending">Pendiente</span>',sX=closed?(finite(r.exit_sbs_vc)?`<span class="real">${vc(r.exit_sbs_vc)}</span>`:'<span class="pending">Pendiente</span>'):'—';return`<tr><td>${state}${r.confirmed?' <span class="tb bconfirm">OK</span>':''}</td><td>${fmt(r.entry_date)}</td><td>${modelLabel(r.valuation_model)}</td><td>${vc(r.entry_est_vc)}</td><td>${sE}</td><td>${closed?fmt(r.exit_date):'—'}</td><td>${closed?vc(r.exit_est_vc):'—'}</td><td>${sX}</td><td>${pct(m.re)}</td><td>${pct(m.rr)}</td><td>${money(m.ge)}</td><td>${m.gr===null?'Pendiente':money(m.gr)}</td><td>${money(r.capital)}</td><td><button class="traderowbtn ok" data-ok="${r.id}">✓ OK</button> <button class="traderowbtn del" data-del="${r.id}">Eliminar</button></td></tr>`}).join('');
  body.querySelectorAll('[data-ok]').forEach(b=>b.onclick=()=>{const a=loadRows(),r=a.find(x=>x.id===b.dataset.ok);if(r){r.confirmed=true;r.confirmed_at=new Date().toISOString();saveRows(a);renderHistory()}});
  body.querySelectorAll('[data-del]').forEach(b=>b.onclick=()=>{if(confirm('¿Eliminar esta operación?')){saveRows(loadRows().filter(x=>x.id!==b.dataset.del));renderHistory()}});
}
function cfg(){return{url:(localStorage.getItem(URL_KEY)||DEFAULT_URL).trim(),key:(localStorage.getItem(SECRET_KEY)||'').trim()}}
function cloudStatus(txt,cls=''){if($('tradeCloudStatus')){$('tradeCloudStatus').textContent=txt;$('tradeCloudStatus').className='cloudstatus '+cls}if($('tradeCloudBadge'))$('tradeCloudBadge').textContent=txt}
function jsonp(action,extra={}){const c=cfg();if(!c.url||!c.key)return Promise.reject(new Error('Falta URL o clave de Drive'));return new Promise((resolve,reject)=>{const cb='__fixedtrade_'+Date.now()+'_'+Math.random().toString(16).slice(2),s=document.createElement('script');let done=false;const finish=(err,data)=>{if(done)return;done=true;clearTimeout(t);try{delete window[cb]}catch(_e){}s.remove();err?reject(err):resolve(data)};const t=setTimeout(()=>finish(new Error('Apps Script no respondió')),15000);window[cb]=data=>{if(!data||data.ok!==true)finish(new Error(data?.error||'Respuesta inválida'));else finish(null,data)};const u=new URL(c.url);u.searchParams.set('action',action);u.searchParams.set('fund',FUND);u.searchParams.set('key',c.key);u.searchParams.set('callback',cb);u.searchParams.set('_',Date.now());Object.entries(extra).forEach(([k,v])=>u.searchParams.set(k,String(v)));s.onerror=()=>finish(new Error('No se pudo contactar Apps Script'));s.src=u.toString();document.head.appendChild(s)})}
function mapById(list){const m=new Map();(Array.isArray(list)?list:[]).forEach(x=>{if(x?.id)m.set(String(x.id),x)});return m}
function stable(x){if(!x||typeof x!=='object')return JSON.stringify(x);const o={};Object.keys(x).sort().forEach(k=>o[k]=x[k]);return JSON.stringify(o)}
async function syncNow(){
  const c=cfg();if(!c.url||!c.key)return;if(syncing){pendingSync=true;return}syncing=true;cloudStatus('Drive Profuturo: sincronizando…','cloud-warn');
  try{
    const probe=await jsonp('ping');if(probe.routing!==true||String(probe.fund||'').toUpperCase()!==FUND)throw new Error('El puente no está enroutando a la hoja Profuturo');
    const current=loadRows(),old=readJson(SNAP_KEY,null);
    if(old===null){for(const r of current)await jsonp('upsert',{payload:JSON.stringify({...r,fund:FUND})})}
    else{const cm=mapById(current),sm=mapById(old);for(const[id,r]of cm){const p=sm.get(id);if(!p||stable(p)!==stable(r))await jsonp('upsert',{payload:JSON.stringify({...r,fund:FUND})})}for(const id of sm.keys())if(!cm.has(id))await jsonp('delete',{id})}
    const out=await jsonp('list'),remote=(Array.isArray(out.rows)?out.rows:[]).filter(r=>String(r.fund||FUND).toUpperCase()===FUND);
    localStorage.setItem(TRADE_KEY,JSON.stringify(remote));localStorage.setItem(SNAP_KEY,JSON.stringify(remote));cloudStatus(`Drive Profuturo conectado · ${remote.length} ${remote.length===1?'operación':'operaciones'}.`,'cloud-ok');renderHistory();
  }catch(e){cloudStatus('Drive no sincronizó: '+e.message,'cloud-bad')}
  finally{syncing=false;if(pendingSync){pendingSync=false;setTimeout(syncNow,0)}}
}
function connectDrive(){const url=($('tradeCloudUrl')?.value||DEFAULT_URL).trim(),key=($('tradeCloudKey')?.value||'').trim();if(!/^https:\/\/script\.google\.com\/macros\/s\/.+\/exec(?:\?.*)?$/.test(url)){cloudStatus('URL /exec no válida.','cloud-bad');return}if(key.length<12){cloudStatus('Clave de Drive no válida.','cloud-bad');return}localStorage.setItem(URL_KEY,url);localStorage.setItem(SECRET_KEY,key);syncNow()}
async function fetchJson(url){const r=await fetch(url+'?v='+Date.now(),{cache:'no-store'});if(!r.ok)throw new Error(`${url}: HTTP ${r.status}`);return r.json()}
async function loadData(){try{const [base,live]=await Promise.all([fetchJson(DATA_URL),fetchJson(LIVE_URL)]);if((base.data_revision||live.base_revision)&&base.data_revision!==live.base_revision)throw new Error('Publicación en transición: la calculadora espera histórico y snapshot del mismo corte.');DB=base;LIVE=live;dataError=null;$('tradeCalc').disabled=false;$('tradeSave').disabled=false}catch(e){dataError=e.message;$('tradeCalc').disabled=true;$('tradeSave').disabled=true;renderDataStatus();throw e}}
async function boot(){
  installStyles();installPanel();bindTabs();$('tradeCalc').onclick=calc;$('tradeSave').onclick=saveCurrent;$('tradeCloudConnect').onclick=connectDrive;
  if(!localStorage.getItem(URL_KEY))localStorage.setItem(URL_KEY,DEFAULT_URL);const c=cfg();$('tradeCloudUrl').value=c.url;$('tradeCloudKey').value=c.key;
  try{await loadData();refreshDateInputs(true);renderHistory();cloudStatus(c.key?'Drive Profuturo configurado. Verificando…':'Drive listo: se conserva la misma conexión anterior; ingresa tu clave solo si este navegador no la conserva.',c.key?'cloud-warn':'');if(c.key)setTimeout(syncNow,500)}
  catch(e){$('tradeDetail').textContent='No se pudieron cargar los datos del visor: '+e.message;cloudStatus('Drive disponible; datos del visor pendientes.','cloud-warn')}
  window.addEventListener('fondo3-local-trade-change',()=>syncNow());setInterval(()=>{if(cfg().key)syncNow()},30000);setInterval(async()=>{try{await loadData();refreshDateInputs();renderHistory();if(hasCalculated)calc()}catch(_e){}},30000);
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();
