(function(){
  'use strict';
  const BRANCH='migracion-github-actions';
  const RAW='https://raw.githubusercontent.com/rldaqp/afp-fondo3-monitor/'+BRANCH+'/public/data/';
  const $=id=>document.getElementById(id);
  const fmt=d=>{if(!d)return'—';const p=String(d).slice(0,10).split('-');return p.length===3?`${p[2]}/${p[1]}/${p[0]}`:String(d)};
  const vc=x=>x==null||!Number.isFinite(Number(x))?'—':Number(x).toFixed(7);
  const pct=x=>x==null||!Number.isFinite(Number(x))?'—':`${Number(x)>=0?'+':''}${(Number(x)*100).toFixed(3)}%`;

  async function getJson(name){
    const ts=Date.now();
    const urls=['data/'+name+'?ts='+ts,RAW+name+'?ts='+ts];
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

  function stamp(value){
    if(!value)return'—';
    try{return new Intl.DateTimeFormat('es-PE',{dateStyle:'short',timeStyle:'medium',timeZone:'America/Lima'}).format(new Date(value));}
    catch(e){return String(value);}
  }

  async function updateAudit(){
    const box=$('audit');
    if(!box)return;
    try{
      const [sbs,alt,deploy]=await Promise.all([
        getJson('sbs_sync_status.json').catch(()=>null),
        getJson('alt_6030_experimental.json').catch(()=>null),
        getJson('alt6030_deploy_status.json').catch(()=>null)
      ]);
      const m=alt&&alt.model||{};
      const parts=[];
      if(sbs){
        parts.push(`SBS: ${fmt(sbs.latest_remote_date)} · VC ${vc(sbs.latest_remote_vc_profuturo_f3)} · ${sbs.method||'fuente oficial'}`);
      }else if(m.sbs_anchor_date){
        parts.push(`SBS: ${fmt(m.sbs_anchor_date)} · VC ${vc(m.sbs_anchor_vc)}`);
      }else{
        parts.push('SBS: sin estado disponible');
      }
      if(alt){
        parts.push(`Nuevo 60/30: ${fmt(alt.signal_date)} · VC ${vc(m.vc_estimated)} · ${pct(m.return_estimated)} · ${m.signal||'—'}`);
      }
      if(alt&&alt.generated_at_lima)parts.push(`cálculo ${stamp(alt.generated_at_lima)}`);
      if(deploy&&deploy.deployed_at_utc)parts.push(`visor publicado ${stamp(deploy.deployed_at_utc)}`);
      box.textContent=parts.join(' · ');
    }catch(e){
      box.textContent='Auditoría no disponible: '+(e&&e.message?e.message:String(e));
    }
  }

  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',updateAudit,{once:true});else updateAudit();
  setTimeout(updateAudit,1500);
  setInterval(updateAudit,30000);
})();
