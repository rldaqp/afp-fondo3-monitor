from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML_PATH = ROOT / "public" / "index.html"
html = HTML_PATH.read_text(encoding="utf-8")

# 1) El panel Huber ya fue retirado visualmente. También se elimina su JS
# heredado para evitar referencias a huberValue/huberSub inexistentes.
html = re.sub(
    r"\n\s*const hub=currentHuber\(\),olsSignal=.*?\n\s*const contrib=liveContributions\(\)\|\|\(modelInsights\.contributions\|\|\[\]\);",
    "\n    const contrib=liveContributions()||(modelInsights.contributions||[]);",
    html,
    count=1,
    flags=re.S,
)
html = html.replace("$('huberValue').textContent", "void 0 && $('huberValue').textContent")
html = html.replace("$('huberSub').textContent", "void 0 && $('huberSub').textContent")

# 2) Selector histórico del challenger 60/30. Se conserva en el HTML legado
# porque otros validadores lo esperan, aunque el runtime dual lo oculta en pantalla.
START = "<!-- REDUCED_6030_HISTORY_SELECTOR START -->"
END = "<!-- REDUCED_6030_HISTORY_SELECTOR END -->"
html = re.sub(re.escape(START) + r".*?" + re.escape(END), "", html, flags=re.S)
selector = r'''
<!-- REDUCED_6030_HISTORY_SELECTOR START -->
<div class="r6030-history" style="margin-top:12px;padding:10px;background:#0b1728;border:1px solid #243244;border-radius:11px">
  <div style="font-size:.78rem;font-weight:850;margin-bottom:7px">Consultar otra fecha del challenger</div>
  <div style="display:grid;grid-template-columns:minmax(150px,220px) 1fr;gap:8px;align-items:end">
    <label style="display:block"><span style="display:block;margin-bottom:4px">Fecha disponible</span><input id="r6030HistoryDate" type="date" style="width:100%;background:#07111f;color:#fff;border:1px solid #334155;border-radius:9px;padding:9px"></label>
    <div id="r6030HistoryStatus" class="r6030-note" style="margin:0">Cargando historial…</div>
  </div>
  <div id="r6030HistoryResult" style="display:grid;grid-template-columns:repeat(4,1fr);gap:7px;margin-top:9px"></div>
</div>
<!-- REDUCED_6030_HISTORY_SELECTOR END -->
'''
needle = '  <details class="r6030-details">'
if needle not in html:
    raise RuntimeError("No se encontro el panel 60/30 para insertar selector historico")
html = html.replace(needle, selector + "\n" + needle, 1)

if "REDUCED_6030_HISTORY_CSS" not in html:
    css = r'''
<!-- REDUCED_6030_HISTORY_CSS -->
<style>
@media(max-width:700px){.r6030-history>div:nth-child(2){grid-template-columns:1fr!important}#r6030HistoryResult{grid-template-columns:1fr 1fr!important}}
@media(max-width:390px){#r6030HistoryResult{grid-template-columns:1fr!important}}
</style>
'''
    html = html.replace("</head>", css + "</head>", 1)

SSTART = "<!-- REDUCED_6030_HISTORY_SCRIPT START -->"
SEND = "<!-- REDUCED_6030_HISTORY_SCRIPT END -->"
html = re.sub(re.escape(SSTART) + r".*?" + re.escape(SEND), "", html, flags=re.S)
script = r'''
<!-- REDUCED_6030_HISTORY_SCRIPT START -->
<script id="reduced6030HistoryScript">
(function(){
  'use strict';
  const $=id=>document.getElementById(id);
  const fmt=d=>{if(!d)return '—';const p=String(d).slice(0,10).split('-');return p.length===3?`${p[2]}/${p[1]}/${p[0]}`:d};
  const vc=x=>x==null||!Number.isFinite(Number(x))?'—':Number(x).toFixed(7);
  const ret=x=>x==null||!Number.isFinite(Number(x))?'—':`${Number(x)>=0?'+':''}${(Number(x)*100).toFixed(3)}%`;
  const diff=x=>x==null||!Number.isFinite(Number(x))?'—':`${Number(x)>=0?'+':''}${Number(x).toFixed(7)}`;
  const card=(label,value,sub='')=>`<div class="r6030-mini"><span>${label}</span><b>${value}</b>${sub?`<span style="margin-top:3px">${sub}</span>`:''}</div>`;
  let rows=[];
  function render(date){
    const status=$('r6030HistoryStatus'),box=$('r6030HistoryResult');
    if(!status||!box)return;
    const r=rows.find(x=>x.fecha===date);
    if(!r){status.textContent='No hay una observación del modelo para esa fecha. Elige una fecha disponible.';box.innerHTML='';return;}
    const actual=r.actual_vc==null?null:Number(r.actual_vc),chall=Number(r.challenger_vc),official=r.official_vc==null?null:Number(r.official_vc);
    const cd=actual==null?null:chall-actual,od=actual==null||official==null?null:official-actual;
    const source=String(r.source||'').includes('SOMBRA')?'registro forward real':String(r.source||'').includes('ANCLA')?'ancla SBS':'backtest ciego';
    status.textContent=`${fmt(r.fecha)} · ${source}${r.train_start?` · entrenó ${fmt(r.train_start)}–${fmt(r.train_end)}`:''}`;
    box.innerHTML=card('VC challenger 60/30',vc(chall),`Retorno ${ret(r.challenger_return)}`)+card('VC real SBS',vc(actual),actual==null?'Aún no publicado':'')+card('Diferencia challenger',diff(cd),actual==null?'Pendiente SBS':`Error abs. ${vc(Math.abs(cd))}`)+card('VC modelo oficial',vc(official),actual==null||official==null?'':`Dif. real ${diff(od)}`);
  }
  fetch('data/reduced_6030_history.json?v='+Date.now(),{cache:'no-store'})
    .then(r=>{if(!r.ok)throw new Error('HTTP '+r.status);return r.json()})
    .then(d=>{
      const back=Array.isArray(d.backtest_history)?d.backtest_history:[],op=Array.isArray(d.operational_history)?d.operational_history:[];
      const map=new Map();back.forEach(r=>map.set(r.fecha,r));
      op.forEach(r=>{if(!String(r.source||'').includes('ANCLA')||!map.has(r.fecha))map.set(r.fecha,r)});
      rows=[...map.values()].filter(r=>r&&r.fecha&&Number.isFinite(Number(r.challenger_vc))).sort((a,b)=>a.fecha.localeCompare(b.fecha));
      const input=$('r6030HistoryDate'),status=$('r6030HistoryStatus');if(!input||!status)return;
      if(!rows.length){status.textContent='Historial no disponible.';return;}
      input.min=rows[0].fecha;input.max=rows.at(-1).fecha;input.value=rows.at(-1).fecha;
      input.onchange=()=>render(input.value);render(input.value);
    })
    .catch(e=>{const s=$('r6030HistoryStatus');if(s)s.textContent='No se pudo cargar el historial 60/30: '+e.message});
})();
</script>
<!-- REDUCED_6030_HISTORY_SCRIPT END -->
'''
html = html.replace("</body>", script + "</body>", 1)

# 3) Runtimes permanentes. Los runtimes anteriores se conservan para compatibilidad
# de operaciones/datos, pero el runtime dual se carga al final y deja visibles solo
# los dos modelos Rolling 30 aprobados para seguimiento.
for pattern in (
    r'\n?<script src="data/alt_runtime_v4\.js\?rev=[^"]+"></script>',
    r'\n?<script src="data/alt_runtime_v5\.js\?rev=[^"]+"></script>',
    r'\n?<script src="data/spblscup_stale_fix\.js\?rev=[^"]+"></script>',
    r'\n?<script src="data/visor_hotfix_v1\.js\?rev=[^"]+"></script>',
    r'\n?<script src="data/dual_rolling30_runtime_v1\.js\?rev=[^"]+"></script>',
):
    html = re.sub(pattern, '', html)

runtime_tags = [
    '<script src="data/alt_runtime_v5.js?rev=ALT6030V5"></script>',
    '<script src="data/spblscup_stale_fix.js?rev=SPBLCLOSEV1"></script>',
    '<script src="data/visor_hotfix_v1.js?rev=VISORHOTFIX1"></script>',
    '<script src="data/dual_rolling30_runtime_v1.js?rev=DUALROLL30V1"></script>',
]
html = html.replace("</body>", "\n".join(runtime_tags) + "\n</body>", 1)

if "r6030HistoryDate" not in html:
    raise RuntimeError("No quedo insertado selector historico 60/30")
if "$('huberValue').textContent" in html or "$('huberSub').textContent" in html:
    raise RuntimeError("Persistieron referencias DOM Huber que pueden romper el visor")
for required in (
    "alt_runtime_v5.js?rev=ALT6030V5",
    "spblscup_stale_fix.js?rev=SPBLCLOSEV1",
    "visor_hotfix_v1.js?rev=VISORHOTFIX1",
    "dual_rolling30_runtime_v1.js?rev=DUALROLL30V1",
):
    if required not in html:
        raise RuntimeError(f"No quedo fijado el runtime requerido: {required}")

HTML_PATH.write_text(html, encoding="utf-8")
print("Runtime dual Rolling30 fijado al final del visor.")

# Genera también la auditoría comparativa exacta de los últimos 20 VC SBS.
subprocess.run([sys.executable, str(ROOT / "scripts" / "recheck_6030_exact20.py")], check=True)
