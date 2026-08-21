(function(){
  'use strict';
  const BRANCH='migracion-github-actions';
  const CSV='https://raw.githubusercontent.com/rldaqp/afp-fondo3-monitor/'+BRANCH+'/data/analysis/googlefinance_alt_aligned_closes_20260402_20260820.csv';
  const LIVE='https://raw.githubusercontent.com/rldaqp/afp-fondo3-monitor/'+BRANCH+'/public/data/live_market.json';
  const finite=x=>x!==null&&x!==undefined&&x!==''&&Number.isFinite(Number(x));
  const fmt=d=>{const p=String(d||'').slice(0,10).split('-');return p.length===3?`${p[2]}/${p[1]}/${p[0]}`:String(d||'—')};
  const cls=x=>Number(x)>0?'pos':Number(x)<0?'neg':'zero';
  async function getText(url){const r=await fetch(url+'?ts='+Date.now(),{cache:'no-store'});if(!r.ok)throw new Error('HTTP '+r.status);return r.text();}
  async function getJson(url){const r=await fetch(url+'?ts='+Date.now(),{cache:'no-store'});if(!r.ok)throw new Error('HTTP '+r.status);return r.json();}
  function lastTwo(csv){
    const lines=csv.trim().split(/\r?\n/).filter(Boolean);if(lines.length<3)return null;
    const h=lines[0].split(',');const di=h.indexOf('fecha'),si=h.indexOf('SPBLSCUP');if(di<0||si<0)return null;
    const rows=lines.slice(1).map(l=>l.split(',')).map(r=>({date:r[di],value:Number(r[si])})).filter(r=>r.date&&Number.isFinite(r.value));
    return rows.length>=2?[rows.at(-2),rows.at(-1)]:null;
  }
  function card(){return [...document.querySelectorAll('#marketExperimentalGrid .market-item')].find(x=>x.querySelector('.market-symbol')?.textContent.trim()==='SPBLSCUP')||null;}
  async function paint(){
    try{
      const [live,csv]=await Promise.all([getJson(LIVE),getText(CSV)]);
      const sp=(live.experimental_assets||[]).find(x=>x.serie==='SPBLSCUP');if(!sp||finite(sp.retorno))return;
      const pair=lastTwo(csv);if(!pair)return;const [prev,last]=pair;
      const ret=last.value/prev.value-1;const el=card();if(!el)return;
      const retEl=el.querySelector('.market-ret');if(retEl)retEl.innerHTML=`<span class="${cls(ret)}">${ret>=0?'+':''}${(ret*100).toFixed(2)}%</span><div style="font-size:.66rem;color:#94a3b8;margin-top:2px">último cierre</div>`;
      const src=el.querySelector('.market-source');if(src)src.innerHTML=`ÚLTIMO CIERRE GOOGLE FINANCE GUARDADO · NUEVO 60/30 EXPERIMENTAL<br><b>Cierre ${fmt(last.date)} · vs ${fmt(prev.date)}</b><br><span style="font-size:.66rem">Sin cotización del ${fmt(live.signal_date)}; el modelo usa 0% provisional para SPBLSCUP hoy.</span>`;
      const audit=document.getElementById('audit');if(audit&&!audit.textContent.includes('SPBLSCUP'))audit.innerHTML+=`<br><span style="font-size:.72rem;color:#fbbf24">SPBLSCUP: último cierre ${fmt(last.date)}; dato ${fmt(live.signal_date)} pendiente, aporte provisional 0%.</span>`;
    }catch(e){}
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',()=>setTimeout(paint,1800),{once:true});else setTimeout(paint,1800);
  setInterval(paint,60000);
})();
