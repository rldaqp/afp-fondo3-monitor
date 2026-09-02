(function(){
'use strict';
const LIVE_URL='data/fixed_models_intraday.json';
const STALE_MINUTES=12;
const $=id=>document.getElementById(id);

function zoneParts(date=new Date(),zone='America/New_York'){
  const parts=new Intl.DateTimeFormat('en-US',{timeZone:zone,weekday:'short',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false,year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(date);
  const o={}; for(const p of parts)o[p.type]=p.value; return o;
}
function key(p){return `${p.year}-${p.month}-${p.day}`}
function minutes(p){return Number(p.hour)*60+Number(p.minute)}
function marketState(){
  const p=zoneParts();
  const weekday=!['Sat','Sun'].includes(p.weekday);
  const m=minutes(p);
  return {parts:p,open:weekday&&m>=570&&m<960,afterClose:weekday&&m>=960,minute:m};
}
function ageMinutes(iso){
  const t=Date.parse(iso||'');
  return Number.isFinite(t)?Math.max(0,Math.floor((Date.now()-t)/60000)):null;
}
function fmtDate(s){
  if(!s)return '—';
  const p=String(s).slice(0,10).split('-');
  return p.length===3?`${p[2]}/${p[1]}/${p[0]}`:String(s);
}
function fmtLima(iso){
  const d=new Date(iso||'');
  if(!Number.isFinite(d.getTime()))return '—';
  return new Intl.DateTimeFormat('es-PE',{timeZone:'America/Lima',year:'numeric',month:'numeric',day:'numeric',hour:'numeric',minute:'2-digit',second:'2-digit',hour12:true}).format(d);
}
function installStyle(){
  if($('tickerFreshnessStyle'))return;
  const st=document.createElement('style'); st.id='tickerFreshnessStyle';
  st.textContent=`
    .freshwarn{display:none;margin:0 0 7px;padding:7px 9px;border:1px solid #92400e;background:#451a03;color:#fde68a;border-radius:8px;font-size:.68rem;font-weight:800;line-height:1.35}
    .freshwarn.show{display:block}
    .tickerchip.stale{border-color:#b45309;box-shadow:inset 0 0 0 1px rgba(251,191,36,.12)}
    .prevbasis{font-size:.53rem;color:#9aa9bd;margin-top:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
    .staletxt{color:#fbbf24!important;font-weight:900}
    .closetxt{color:#93c5fd!important;font-weight:900}
  `;
  document.head.appendChild(st);
}
function warningNode(){
  let n=$('tickerFreshnessWarn'); if(n)return n;
  const dock=document.querySelector('.marketdock'); if(!dock)return null;
  n=document.createElement('div'); n.id='tickerFreshnessWarn'; n.className='freshwarn';
  const bar=$('tickerbar'); dock.insertBefore(n,bar||dock.firstChild); return n;
}
function decorateTickers(data,stale){
  const map=new Map((data.tickers||[]).map(x=>[String(x.ticker),x]));
  document.querySelectorAll('.tickerchip').forEach(chip=>{
    const sym=chip.querySelector('.sym')?.textContent?.trim(); const t=map.get(sym); if(!t)return;
    chip.classList.toggle('stale',stale);
    let p=chip.querySelector('.prevbasis'); if(!p){p=document.createElement('div');p.className='prevbasis';chip.appendChild(p)}
    const basis=t.previous_close_basis==='CIERRE BASE FIJA'?'base fija':(t.previous_close_basis||'referencia');
    p.textContent=`Prev. ${fmtDate(t.previous_close_date)} · ${basis}`;
    p.title=`Cierre usado: ${t.price_previous ?? '—'} · Regla: ${data.previous_close_rule||basis}`;
  });
}
function setClass(el,cls,on){if(el)el.classList.toggle(cls,on)}
async function refresh(){
  try{
    const r=await fetch(`${LIVE_URL}?fresh=${Date.now()}`,{cache:'no-store'}); if(!r.ok)throw new Error(`HTTP ${r.status}`);
    const d=await r.json();
    const stamp=d.generated_at_lima||d.generated_at_ny;
    const age=ageMinutes(stamp);
    const ms=marketState();
    const snapDate=new Date(d.generated_at_ny||d.generated_at_lima||'');
    const sp=Number.isFinite(snapDate.getTime())?zoneParts(snapDate):null;
    const sameNyDay=sp&&key(sp)===key(ms.parts);
    const snapMinute=sp?minutes(sp):null;
    const staleOpen=ms.open&&(age===null||age>STALE_MINUTES);
    const closePending=ms.afterClose&&sameNyDay&&snapMinute!==null&&snapMinute<955;
    const warn=warningNode();
    decorateTickers(d,staleOpen||closePending);

    if($('updated')){
      $('updated').textContent=`Último cálculo: ${fmtLima(stamp)}${age!==null&&age>1?` · hace ${age} min`:''}`;
      setClass($('updated'),'staletxt',staleOpen||closePending);
    }
    if($('marketStamp'))$('marketStamp').textContent=`Corte del modelo: ${fmtLima(stamp)}`;
    if($('marketDate'))$('marketDate').textContent=fmtDate(d.signal_date);

    if(staleOpen){
      if(warn){warn.classList.add('show');warn.textContent=`⚠ Snapshot intradía desactualizado${age===null?'':` · hace ${age} min`}. Mercado abierto: los valores no deben interpretarse como cotización actual hasta una nueva actualización.`}
      if($('factorStatus'))$('factorStatus').textContent=`DESACTUALIZADO${age===null?'':` · ${age} min`}`;
      if($('marketMode'))$('marketMode').textContent='MERCADO ABIERTO · DATO DESACTUALIZADO';
    }else if(closePending){
      if(warn){warn.classList.add('show');warn.textContent=`⚠ El mercado ya cerró y el último cálculo disponible es anterior al cierre (${fmtLima(stamp)}). Falta confirmar el snapshot final de cierre.`}
      if($('factorStatus'))$('factorStatus').textContent='CIERRE PENDIENTE · ÚLTIMO CORTE PRE-CIERRE';
      if($('marketMode'))$('marketMode').textContent='MERCADO CERRADO · CIERRE PENDIENTE';
    }else if(ms.open){
      if(warn)warn.classList.remove('show');
      if($('factorStatus'))$('factorStatus').textContent=`INTRADÍA · ${fmtDate(d.signal_date)} · ${d.fresh_factors??'—'}/${d.total_factors??'—'} actualizados`;
      if($('marketMode'))$('marketMode').textContent='MERCADO ABIERTO · DATOS INTRADÍA';
    }else{
      if(warn)warn.classList.remove('show');
      if($('factorStatus'))$('factorStatus').textContent=`CIERRE / ÚLTIMO SNAPSHOT · ${fmtDate(d.signal_date)}`;
      if($('marketMode'))$('marketMode').textContent='MERCADO CERRADO · ÚLTIMO DATO';
    }

    setClass($('factorStatus'),'staletxt',staleOpen||closePending);
    setClass($('marketMode'),'staletxt',staleOpen||closePending);
    setClass($('marketMode'),'closetxt',!ms.open&&!staleOpen&&!closePending);
  }catch(e){console.warn('freshness visor',e)}
}
installStyle();
setTimeout(refresh,350);
setInterval(refresh,60000);
window.addEventListener('load',()=>setTimeout(refresh,150));
})();
