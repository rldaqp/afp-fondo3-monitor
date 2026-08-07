from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
HTML_PATH = ROOT / "public" / "index.html"
html = HTML_PATH.read_text(encoding="utf-8")

START = "<!-- TRADE_CLOUD_V1_START -->"
END = "<!-- TRADE_CLOUD_V1_END -->"
html = re.sub(re.escape(START) + r".*?" + re.escape(END), "", html, flags=re.S)

css = r'''
<style id="tradeCloudStyles">
.cloud-box{margin-top:10px;padding:10px;border:1px solid #243244;border-radius:10px;background:#0b1728}
.cloud-title{font-size:.78rem;font-weight:800;margin-bottom:7px;color:#e2e8f0}.cloud-grid{display:grid;grid-template-columns:2fr 1.3fr auto;gap:7px}
.cloud-grid input{width:100%;background:#07111f;color:#fff;border:1px solid #334155;border-radius:8px;padding:9px;font-size:.75rem}.cloud-grid button{border:1px solid #1d4ed8;background:#2563eb;color:#fff;border-radius:8px;padding:9px 11px;font-weight:800}
.cloud-status{margin-top:7px;color:#94a3b8;font-size:.72rem;line-height:1.35}.cloud-ok{color:#4ade80}.cloud-warn{color:#fbbf24}.cloud-bad{color:#f87171}
@media(max-width:700px){.cloud-grid{grid-template-columns:1fr}.cloud-grid button{width:100%}}
</style>
'''

box = r'''
<div class="cloud-box" id="tradeCloudBox">
  <div class="cloud-title">Respaldo y sincronización en Google Drive · Profuturo</div>
  <div class="cloud-grid">
    <input id="tradeCloudUrl" type="url" inputmode="url" placeholder="URL de Apps Script que termina en /exec">
    <input id="tradeCloudKey" type="password" autocomplete="off" placeholder="Clave de la pestaña Config">
    <button id="tradeCloudConnect" type="button">Conectar Drive</button>
  </div>
  <div id="tradeCloudStatus" class="cloud-status">Las operaciones de Profuturo se guardan únicamente en la hoja Profuturo.</div>
</div>
'''

js = r'''
<script id="tradeCloudScript">
(function(){
  'use strict';
  const FUND='PROFUTURO';
  const DRIVE_SHEET='Profuturo';
  const TRADE_KEY='profuturo_fondo3_trade_history_v2';
  const URL_KEY='profuturo_fondo3_drive_sync_url_v2';
  const SECRET_KEY='fondo3_drive_sync_key_v1';
  const SNAP_KEY='profuturo_fondo3_drive_sync_snapshot_v2';
  const DEFAULT_URL='https://script.google.com/macros/s/AKfycbxY9JqIeTnweKaEXAOs7hQ6KftlPgVsGOFPwOp7hqL5gJ47OuuHlAJBksTGdOQ2yc_Y0Q/exec';
  let syncing=false,timer=null;
  const $=id=>document.getElementById(id);
  const read=(k,fb)=>{try{const x=JSON.parse(localStorage.getItem(k)||'');return x??fb}catch(e){return fb}};
  const rows=()=>read(TRADE_KEY,[]);
  const snapshot=()=>read(SNAP_KEY,null);
  const stable=x=>JSON.stringify(x,Object.keys(x||{}).sort());
  const setStatus=(txt,cls='')=>{const el=$('tradeCloudStatus');if(el){el.textContent=txt;el.className='cloud-status '+cls}};
  const cfg=()=>({url:(localStorage.getItem(URL_KEY)||DEFAULT_URL).trim(),key:(localStorage.getItem(SECRET_KEY)||'').trim()});

  function jsonp(action,extra={}){
    const c=cfg();
    if(!c.url||!c.key)return Promise.reject(new Error('Falta URL o clave de Drive'));
    return new Promise((resolve,reject)=>{
      const cb='__f3cb_'+Date.now()+'_'+Math.random().toString(16).slice(2);
      const s=document.createElement('script');
      const timeout=setTimeout(()=>done(new Error('Apps Script no devolvio JSONP. Revisa que la Web app este publicada para cualquier usuario y que soporte Profuturo/Habitat.')),15000);
      function done(err,data){clearTimeout(timeout);delete window[cb];s.remove();err?reject(err):resolve(data)}
      window[cb]=data=>{if(!data||data.ok!==true)done(new Error(data&&data.error?data.error:'Respuesta inválida'));else done(null,data)};
      const u=new URL(c.url);
      u.searchParams.set('action',action);u.searchParams.set('fund',FUND);u.searchParams.set('key',c.key);u.searchParams.set('callback',cb);u.searchParams.set('_',Date.now());
      Object.entries(extra).forEach(([k,v])=>u.searchParams.set(k,String(v)));
      s.onerror=()=>done(new Error('No se pudo contactar Apps Script'));
      s.src=u.toString();document.head.appendChild(s);
    });
  }

  function mapById(list){const m=new Map();(Array.isArray(list)?list:[]).forEach(x=>{if(x&&x.id)m.set(String(x.id),x)});return m}

  async function syncNow(initial=false){
    const c=cfg();if(!c.url||!c.key||syncing)return;
    syncing=true;setStatus('Sincronizando Profuturo con Drive…','cloud-warn');
    try{
      // TRADE_CLOUD_FUND_ROUTING_V2
      const probe=await jsonp('ping');
      if(probe.routing!==true||String(probe.fund||'').toUpperCase()!==FUND){
        throw new Error(`El puente de Drive aún no está actualizado para la hoja ${DRIVE_SHEET}.`);
      }
      const current=rows(),old=snapshot();
      if(old===null){
        for(const r of current){await jsonp('upsert',{payload:JSON.stringify({...r,fund:FUND})})}
      }else{
        const cm=mapById(current),sm=mapById(old);
        for(const [id,r] of cm){const prev=sm.get(id);if(!prev||stable(prev)!==stable(r))await jsonp('upsert',{payload:JSON.stringify({...r,fund:FUND})})}
        for(const id of sm.keys()){if(!cm.has(id))await jsonp('delete',{id})}
      }
      const out=await jsonp('list');
      const remote=Array.isArray(out.rows)?out.rows:[];
      localStorage.setItem(TRADE_KEY,JSON.stringify(remote));
      localStorage.setItem(SNAP_KEY,JSON.stringify(remote));
      setStatus(`Drive Profuturo conectado · ${remote.length} ${remote.length===1?'operación':'operaciones'} sincronizadas.`,'cloud-ok');
      window.dispatchEvent(new Event('fondo3-cloud-synced'));
      if(!initial)setTimeout(()=>location.reload(),180);
    }catch(e){setStatus('Drive no sincronizó: '+e.message,'cloud-bad')}
    finally{syncing=false}
  }

  async function connect(){
    const url=($('tradeCloudUrl')?.value||DEFAULT_URL).trim(),key=($('tradeCloudKey')?.value||'').trim();
    if(!/^https:\/\/script\.google\.com\/macros\/s\/.+\/exec(?:\?.*)?$/.test(url)){setStatus('La URL /exec de Apps Script no es válida.','cloud-bad');return}
    if(key.length<12){setStatus('La clave de sincronización no es válida.','cloud-bad');return}
    localStorage.setItem(URL_KEY,url);localStorage.setItem(SECRET_KEY,key);
    try{await syncNow(true)}catch(e){setStatus('No se pudo conectar: '+e.message,'cloud-bad')}
  }

  function boot(){
    if(!localStorage.getItem(URL_KEY))localStorage.setItem(URL_KEY,DEFAULT_URL);
    const c=cfg();if($('tradeCloudUrl'))$('tradeCloudUrl').value=c.url;if($('tradeCloudKey'))$('tradeCloudKey').value=c.key;
    if($('tradeCloudConnect'))$('tradeCloudConnect').onclick=connect;
    if(c.url&&c.key){setStatus('Drive Profuturo configurado. Verificando…','cloud-warn');setTimeout(()=>syncNow(true),900)}
    document.addEventListener('click',ev=>{if(ev.target.closest('#tradeHistoryPanel button')&&!ev.target.closest('#tradeCloudConnect'))setTimeout(()=>syncNow(true),350)},true);
    timer=setInterval(()=>syncNow(true),30000);
  }
  boot();
})();
</script>
'''

needle = '<div id="tradeMsg" class="trade-msg">'
pos = html.find(needle)
if pos < 0:
    raise RuntimeError("No se encontró tradeMsg para insertar la configuración Drive")
end_div = html.find('</div>', pos)
html = html[:end_div+6] + START + css + box + html[end_div+6:]
html = html.replace('</body>', js + END + '\n</body>', 1)

# El historial local también queda aislado desde el inicio.
html = re.sub(
    r"const KEY='[^']*';",
    "const KEY='profuturo_fondo3_trade_history_v2';",
    html,
    count=1,
)

required = [
    "const FUND='PROFUTURO';",
    "const KEY='profuturo_fondo3_trade_history_v2';",
    "const TRADE_KEY='profuturo_fondo3_trade_history_v2';",
    "const SNAP_KEY='profuturo_fondo3_drive_sync_snapshot_v2';",
    "u.searchParams.set('fund',FUND);",
    "TRADE_CLOUD_FUND_ROUTING_V2",
]
missing = [item for item in required if item not in html]
if missing:
    raise AssertionError(f"Faltan controles de separación Profuturo: {missing}")

HTML_PATH.write_text(html, encoding="utf-8")
print("Sincronización Drive Profuturo v2: almacenamiento y hoja independientes.")
