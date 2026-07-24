from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
HTML_PATH = ROOT / "public" / "index.html"
html = HTML_PATH.read_text(encoding="utf-8")

START = "<!-- TRADE_HISTORY_V1_START -->"
END = "<!-- TRADE_HISTORY_V1_END -->"
html = re.sub(re.escape(START) + r".*?" + re.escape(END), "", html, flags=re.S)

css = r'''
<style id="tradeHistoryStyles">
.trade-wrap{overflow-x:auto;-webkit-overflow-scrolling:touch;margin-top:10px}
.trade-table{width:100%;min-width:1180px;border-collapse:separate;border-spacing:0;font-size:.74rem}
.trade-table th,.trade-table td{padding:8px 7px;border-bottom:1px solid #243244;text-align:right;white-space:nowrap}
.trade-table th{color:#94a3b8;font-weight:750;background:#0b1728;position:sticky;top:0;z-index:1}
.trade-table th:first-child,.trade-table td:first-child,.trade-table th:nth-child(2),.trade-table td:nth-child(2){text-align:left}
.trade-actions{display:flex;gap:5px;justify-content:flex-end}.trade-btn{border:1px solid #334155;background:#132238;color:#fff;border-radius:8px;padding:7px 9px;font-weight:750;font-size:.72rem}.trade-btn.ok{background:#166534}.trade-btn.del{background:#7f1d1d}.trade-btn.close{background:#1d4ed8}
.trade-badge{display:inline-block;padding:3px 7px;border-radius:999px;font-size:.67rem;font-weight:800}.trade-open{background:#78350f;color:#fde68a}.trade-closed{background:#164e63;color:#a5f3fc}.trade-confirmed{background:#14532d;color:#bbf7d0}.trade-pending{color:#fbbf24}.trade-real{color:#4ade80}.trade-diff-pos{color:#4ade80}.trade-diff-neg{color:#f87171}
.trade-toolbar{display:grid;grid-template-columns:1fr auto;gap:8px;align-items:center;margin-top:10px}.trade-save{width:100%;border:1px solid #1d4ed8;background:#2563eb;color:#fff;border-radius:10px;padding:11px;font-weight:800}.trade-msg{color:#94a3b8;font-size:.75rem;line-height:1.4;margin-top:7px}
@media(max-width:700px){.trade-toolbar{grid-template-columns:1fr}.trade-table{font-size:.72rem}.trade-table th,.trade-table td{padding:7px 6px}}
</style>
'''

panel = r'''
<section class="panel" id="tradeHistoryPanel">
  <div class="chart-title">Histórico de entradas y salidas</div>
  <div class="note">Cada vez que presiones <b>OK · Guardar</b>, el VC estimado queda congelado. Cuando la SBS publique el VC oficial de esa fecha, se completa automáticamente y se calcula el retorno real frente al estimado.</div>
  <div class="trade-toolbar">
    <button class="trade-save" id="tradeSaveBtn" type="button">✓ OK · Guardar operación actual</button>
    <div class="note" id="tradeCount">0 operaciones</div>
  </div>
  <div id="tradeMsg" class="trade-msg">El histórico se guarda en este navegador del celular.</div>
  <div class="trade-wrap">
    <table class="trade-table">
      <thead><tr>
        <th>Estado</th><th>Entrada</th><th>VC est. entrada</th><th>VC SBS entrada</th>
        <th>Salida</th><th>VC est. salida</th><th>VC SBS salida</th>
        <th>Ret. estimado</th><th>Ret. SBS</th><th>Dif. retorno</th><th>Capital</th><th>Acciones</th>
      </tr></thead>
      <tbody id="tradeHistoryBody"><tr><td colspan="12" style="text-align:center;color:#94a3b8">Sin operaciones guardadas.</td></tr></tbody>
    </table>
  </div>
</section>
'''

js = r'''
<script id="tradeHistoryScript">
(function(){
  'use strict';
  const KEY='fondo3_trade_history_v1';
  let signals=[],ops=[],live=null;
  const $=id=>document.getElementById(id);
  const finite=x=>Number.isFinite(Number(x));
  const fmt=d=>{if(!d)return '—';const p=String(d).slice(0,10).split('-');return p.length===3?`${p[2]}/${p[1]}/${p[0]}`:String(d)};
  const vc=x=>finite(x)?Number(x).toFixed(7):'—';
  const pct=x=>finite(x)?`${Number(x)>=0?'+':''}${(Number(x)*100).toFixed(2)}%`:'—';
  const pp=x=>finite(x)?`${Number(x)>=0?'+':''}${(Number(x)*100).toFixed(2)} pp`:'—';
  const money=x=>finite(x)?new Intl.NumberFormat('es-PE',{style:'currency',currency:'PEN'}).format(Number(x)):'—';
  const uid=()=>`${Date.now()}-${Math.random().toString(16).slice(2)}`;

  function loadRows(){try{const x=JSON.parse(localStorage.getItem(KEY)||'[]');return Array.isArray(x)?x:[]}catch(e){return []}}
  function saveRows(rows){localStorage.setItem(KEY,JSON.stringify(rows))}
  function signalAt(date){return signals.find(x=>x.fecha===date)||null}
  function officialAt(date){const s=signalAt(date);return s&&finite(s.vc_real)?Number(s.vc_real):null}
  function estimateAt(date){
    if(live&&live.market_open&&live.signal_date===date&&finite(live.vc_estimated))return Number(live.vc_estimated);
    const s=signalAt(date);return s&&finite(s.vc_estimado)?Number(s.vc_estimado):null;
  }
  function entryEffective(requested){return ops.find(x=>x.fecha>=requested)||null}
  function exitEffective(requested){return [...ops].reverse().find(x=>x.fecha<=requested)||null}

  function reconcile(rows){
    let changed=false;
    rows.forEach(r=>{
      const ei=officialAt(r.entry_date);
      if(ei!==null&&r.entry_sbs_vc!==ei){r.entry_sbs_vc=ei;changed=true}
      if(r.exit_date){const xo=officialAt(r.exit_date);if(xo!==null&&r.exit_sbs_vc!==xo){r.exit_sbs_vc=xo;changed=true}}
    });
    if(changed)saveRows(rows);
    return rows;
  }

  function metrics(r){
    const re=finite(r.entry_est_vc)&&finite(r.exit_est_vc)?Number(r.exit_est_vc)/Number(r.entry_est_vc)-1:null;
    const rr=finite(r.entry_sbs_vc)&&finite(r.exit_sbs_vc)?Number(r.exit_sbs_vc)/Number(r.entry_sbs_vc)-1:null;
    return {re,rr,diff:re!==null&&rr!==null?rr-re:null};
  }

  function render(){
    const rows=reconcile(loadRows()).sort((a,b)=>String(b.created_at).localeCompare(String(a.created_at)));
    const body=$('tradeHistoryBody');if(!body)return;
    $('tradeCount').textContent=`${rows.length} ${rows.length===1?'operación':'operaciones'}`;
    if(!rows.length){body.innerHTML='<tr><td colspan="12" style="text-align:center;color:#94a3b8">Sin operaciones guardadas.</td></tr>';return}
    body.innerHTML=rows.map(r=>{
      const m=metrics(r),closed=!!r.exit_date,confirmed=!!r.confirmed;
      const state=closed?'<span class="trade-badge trade-closed">CERRADA</span>':'<span class="trade-badge trade-open">ABIERTA</span>';
      const ok=confirmed?'<span class="trade-badge trade-confirmed">OK</span>':`<button class="trade-btn ok" data-trade-ok="${r.id}">✓ OK</button>`;
      const close=!closed?`<button class="trade-btn close" data-trade-close="${r.id}">Cerrar</button>`:'';
      const sbsE=finite(r.entry_sbs_vc)?`<span class="trade-real">${vc(r.entry_sbs_vc)}</span>`:'<span class="trade-pending">Pendiente</span>';
      const sbsX=closed?(finite(r.exit_sbs_vc)?`<span class="trade-real">${vc(r.exit_sbs_vc)}</span>`:'<span class="trade-pending">Pendiente</span>'):'—';
      const dc=m.diff===null?'':(m.diff>=0?'trade-diff-pos':'trade-diff-neg');
      return `<tr>
        <td>${state}${confirmed?' '+ok:''}</td><td>${fmt(r.entry_date)}</td><td>${vc(r.entry_est_vc)}</td><td>${sbsE}</td>
        <td>${closed?fmt(r.exit_date):'—'}</td><td>${closed?vc(r.exit_est_vc):'—'}</td><td>${sbsX}</td>
        <td>${pct(m.re)}</td><td>${pct(m.rr)}</td><td class="${dc}">${pp(m.diff)}</td><td>${money(r.capital)}</td>
        <td><div class="trade-actions">${!confirmed?ok:''}${close}<button class="trade-btn del" data-trade-del="${r.id}">Eliminar</button></div></td>
      </tr>`
    }).join('');
    body.querySelectorAll('[data-trade-ok]').forEach(b=>b.onclick=()=>confirmRow(b.dataset.tradeOk));
    body.querySelectorAll('[data-trade-del]').forEach(b=>b.onclick=()=>deleteRow(b.dataset.tradeDel));
    body.querySelectorAll('[data-trade-close]').forEach(b=>b.onclick=()=>prepareClose(b.dataset.tradeClose));
  }

  function confirmRow(id){const rows=loadRows(),r=rows.find(x=>x.id===id);if(!r)return;r.confirmed=true;r.confirmed_at=new Date().toISOString();saveRows(rows);render();$('tradeMsg').textContent='Operación marcada OK.'}
  function deleteRow(id){if(!confirm('¿Eliminar esta operación del histórico?'))return;saveRows(loadRows().filter(x=>x.id!==id));render();$('tradeMsg').textContent='Operación eliminada.'}
  function prepareClose(id){
    const r=loadRows().find(x=>x.id===id);if(!r)return;
    const tab=document.querySelector('.tabs button[data-mode="closed"]');if(tab)tab.click();
    if($('entry'))$('entry').value=r.entry_requested||r.entry_date;
    if($('capital'))$('capital').value=r.capital||25000;
    if($('exit'))$('exit').value=live&&live.signal_date?live.signal_date:(signals.at(-1)?.fecha||'');
    document.querySelector('.tabs')?.scrollIntoView({behavior:'smooth',block:'center'});
    $('tradeMsg').textContent='Operación abierta cargada. Indica la fecha de salida, calcula y presiona OK · Guardar.';
  }

  function saveCurrent(){
    const mode=document.querySelector('.tabs button.active')?.dataset.mode||'monitor';
    if(mode==='monitor'){$('tradeMsg').textContent='Selecciona “Sigo dentro” o “Ya salí” antes de guardar.';return}
    const er=$('entry')?.value,cap=Number($('capital')?.value||0);
    if(!er||!finite(cap)||cap<=0){$('tradeMsg').textContent='Completa fecha de entrada y capital.';return}
    const ep=entryEffective(er);if(!ep){$('tradeMsg').textContent='No existe una fecha efectiva de entrada en la línea del monitor.';return}
    const entryEst=estimateAt(ep.fecha);
    let exitDate=null,exitRequested=null,exitEst=null;
    if(mode==='closed'){
      exitRequested=$('exit')?.value;
      if(!exitRequested){$('tradeMsg').textContent='Indica la fecha de salida.';return}
      const xp=exitEffective(exitRequested);if(!xp||xp.fecha<ep.fecha){$('tradeMsg').textContent='La fecha de salida no es válida.';return}
      exitDate=xp.fecha;exitEst=estimateAt(exitDate);
    }
    const rows=loadRows();
    let row=rows.find(x=>!x.exit_date&&x.entry_date===ep.fecha);
    if(row&&mode==='closed'){
      row.exit_requested=exitRequested;row.exit_date=exitDate;row.exit_est_vc=exitEst;row.exit_sbs_vc=officialAt(exitDate);row.closed_at=new Date().toISOString();row.confirmed=false;
    }else{
      row={id:uid(),created_at:new Date().toISOString(),confirmed:false,capital:cap,entry_requested:er,entry_date:ep.fecha,entry_est_vc:entryEst,entry_sbs_vc:officialAt(ep.fecha),exit_requested:exitRequested,exit_date:exitDate,exit_est_vc:exitEst,exit_sbs_vc:exitDate?officialAt(exitDate):null};
      rows.push(row);
    }
    saveRows(rows);render();
    $('tradeMsg').textContent=mode==='closed'?'Operación cerrada guardada. El estimado quedó congelado; la SBS se completará cuando esté disponible.':'Entrada guardada como operación abierta.';
  }

  async function boot(){
    try{
      const [s,o,l]=await Promise.all([
        fetch('data/signals.json?ts='+Date.now(),{cache:'no-store'}).then(r=>r.json()),
        fetch('data/operation_series.json?ts='+Date.now(),{cache:'no-store'}).then(r=>r.json()),
        fetch('data/live_market.json?ts='+Date.now(),{cache:'no-store'}).then(r=>r.json()).catch(()=>null)
      ]);
      signals=(s||[]).sort((a,b)=>a.fecha.localeCompare(b.fecha));ops=(o||[]).sort((a,b)=>a.fecha.localeCompare(b.fecha));live=l;
      $('tradeSaveBtn').onclick=saveCurrent;render();
    }catch(e){$('tradeMsg').textContent='No se pudo cargar la bitácora: '+e}
  }
  boot();
})();
</script>
'''

marker = '<section class="panel"><div class="chart-title">VC real vs VC estimado</div>'
if marker not in html:
    raise RuntimeError("No se encontró el punto de inserción para el histórico de operaciones")
html = html.replace(marker, START + css + panel + marker, 1)
html = html.replace('</body>', js + END + '\n</body>', 1)

HTML_PATH.write_text(html, encoding="utf-8")
print("Histórico de entradas/salidas v1 inyectado: localStorage + conciliación SBS + OK/Eliminar.")
