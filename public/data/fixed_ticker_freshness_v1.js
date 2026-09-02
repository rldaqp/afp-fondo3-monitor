(function(){
'use strict';
const LIVE_URL='data/fixed_models_intraday.json';
const STALE_MINUTES=12;
const $=id=>document.getElementById(id);

function nyParts(){
  const parts=new Intl.DateTimeFormat('en-US',{timeZone:'America/New_York',weekday:'short',hour:'2-digit',minute:'2-digit',hour12:false,year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date());
  const o={}; for(const p of parts)o[p.type]=p.value; return o;
}
function marketWindowNow(){
  const p=nyParts();
  if(['Sat','Sun'].includes(p.weekday))return false;
  const m=Number(p.hour)*60+Number(p.minute);
  return m>=570&&m<965;
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
function installStyle(){
  if($('tickerFreshnessStyle'))return;
  const st=document.createElement('style'); st.id='tickerFreshnessStyle';
  st.textContent=`
    .freshwarn{display:none;margin:0 0 7px;padding:7px 9px;border:1px solid #92400e;background:#451a03;color:#fde68a;border-radius:8px;font-size:.68rem;font-weight:800;line-height:1.35}
    .freshwarn.show{display:block}
    .tickerchip.stale{border-color:#b45309;box-shadow:inset 0 0 0 1px rgba(251,191,36,.12)}
    .prevbasis{font-size:.53rem;color:#9aa9bd;margin-top:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
    .staletxt{color:#fbbf24!important;font-weight:900}
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
async function refresh(){
  try{
    const r=await fetch(`${LIVE_URL}?fresh=${Date.now()}`,{cache:'no-store'}); if(!r.ok)throw new Error(`HTTP ${r.status}`);
    const d=await r.json(); const age=ageMinutes(d.generated_at_ny); const during=marketWindowNow();
    const stale=during&&(age===null||age>STALE_MINUTES); const warn=warningNode();
    decorateTickers(d,stale);
    if(stale){
      if(warn){warn.classList.add('show');warn.textContent=`⚠ Snapshot intradía desactualizado${age===null?'':` · hace ${age} min`}. Los colores no deben interpretarse como cotización actual hasta la próxima actualización.`}
      if($('factorStatus')){$('factorStatus').textContent=`DESACTUALIZADO${age===null?'':` · ${age} min`}`;$('factorStatus').classList.add('staletxt')}
      if($('marketMode')){$('marketMode').textContent='DATO DESACTUALIZADO';$('marketMode').classList.add('staletxt')}
      if($('updated'))$('updated').classList.add('staletxt');
    }else{
      if(warn)warn.classList.remove('show');
      if($('factorStatus'))$('factorStatus').classList.remove('staletxt');
      if($('marketMode'))$('marketMode').classList.remove('staletxt');
      if($('updated'))$('updated').classList.remove('staletxt');
    }
  }catch(e){console.warn('freshness visor',e)}
}
installStyle();
setTimeout(refresh,1200);
setInterval(refresh,60000);
window.addEventListener('load',()=>setTimeout(refresh,500));
})();
