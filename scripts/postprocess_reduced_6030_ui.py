from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML_PATH = ROOT / "public" / "index.html"
html = HTML_PATH.read_text(encoding="utf-8")

# Retira challengers visibles anteriores. El visor debe mostrar solo el 60/30.
for start, end in [
    ("<!-- SPY_QQQ_CHALLENGER_CSS START -->", "<!-- SPY_QQQ_CHALLENGER_CSS END -->"),
    ("<!-- SPY_QQQ_CHALLENGER_PANEL START -->", "<!-- SPY_QQQ_CHALLENGER_PANEL END -->"),
    ("<!-- SPY_QQQ_CHALLENGER_SCRIPT START -->", "<!-- SPY_QQQ_CHALLENGER_SCRIPT END -->"),
    ("<!-- QQQ_INCREMENTAL_CHALLENGER_UI_V1 START -->", "<!-- QQQ_INCREMENTAL_CHALLENGER_UI_V1 END -->"),
    ("<!-- QQQ_INCREMENTAL_CHALLENGER_PANEL_V1 START -->", "<!-- QQQ_INCREMENTAL_CHALLENGER_PANEL_V1 END -->"),
    ("<!-- QQQ_INCREMENTAL_CHALLENGER_SCRIPT_V1 START -->", "<!-- QQQ_INCREMENTAL_CHALLENGER_SCRIPT_V1 END -->"),
    ("<!-- REDUCED_6030_CHALLENGER_CSS START -->", "<!-- REDUCED_6030_CHALLENGER_CSS END -->"),
    ("<!-- REDUCED_6030_CHALLENGER_PANEL START -->", "<!-- REDUCED_6030_CHALLENGER_PANEL END -->"),
    ("<!-- REDUCED_6030_CHALLENGER_SCRIPT START -->", "<!-- REDUCED_6030_CHALLENGER_SCRIPT END -->"),
]:
    html = re.sub(re.escape(start) + r".*?" + re.escape(end), "", html, flags=re.S)

# Huber no forma parte del visor operativo.
html = re.sub(
    r"\s*<!-- HUBER_CHALLENGER_UI_V1 -->\s*<style id=\"huberChallengerStyles\">.*?</style>",
    "",
    html,
    flags=re.S,
)
html = re.sub(
    r"\s*<div(?: class=\"challenger-box\")? id=\"huberChallengerBox\"[^>]*>.*?(?=\s*<details class=\"insight-details\">)",
    "\n",
    html,
    count=1,
    flags=re.S,
)
html = html.replace("Challenger Huber · paralelo", "")

css = r'''
<!-- REDUCED_6030_CHALLENGER_CSS START -->
<style id="reduced6030Styles">
.r6030-panel{border-color:#334155}.r6030-head{display:flex;justify-content:space-between;gap:12px;align-items:flex-start;margin-bottom:10px}.r6030-title{font-size:.98rem;font-weight:900}.r6030-kicker{font-size:.7rem;color:#94a3b8;margin-top:3px;line-height:1.4}.r6030-badge{padding:5px 9px;border:1px solid #475569;border-radius:999px;font-size:.7rem;font-weight:900;white-space:nowrap}.r6030-grid{display:grid;grid-template-columns:1fr 1fr;gap:9px}.r6030-card{background:#0b1728;border:1px solid #243244;border-radius:12px;padding:11px}.r6030-label{font-size:.72rem;color:#94a3b8;font-weight:800}.r6030-signal{font-size:1.15rem;font-weight:950;margin-top:5px}.r6030-vc{font-size:1.18rem;font-weight:950;margin-top:4px}.r6030-ret{font-size:.76rem;color:#cbd5e1;margin-top:3px}.r6030-strip{display:grid;grid-template-columns:repeat(3,1fr);gap:7px;margin-top:9px}.r6030-mini{background:#101d31;border:1px solid #243244;border-radius:9px;padding:8px}.r6030-mini span{display:block;color:#94a3b8;font-size:.65rem}.r6030-mini b{display:block;margin-top:3px;font-size:.8rem}.r6030-note{font-size:.69rem;color:#94a3b8;line-height:1.45;margin-top:9px}.r6030-details{margin-top:9px}.r6030-details summary{cursor:pointer;color:#cbd5e1;font-size:.72rem;font-weight:800}.r6030-table{width:100%;border-collapse:collapse;font-size:.7rem;margin-top:7px}.r6030-table th,.r6030-table td{padding:6px 4px;border-top:1px solid #243244;text-align:right}.r6030-table th:first-child,.r6030-table td:first-child{text-align:left}
@media(max-width:700px){.r6030-head{display:block}.r6030-badge{display:inline-block;margin-top:7px}.r6030-grid{grid-template-columns:1fr 1fr}.r6030-strip{grid-template-columns:1fr 1fr}.r6030-mini:last-child{grid-column:1/-1}.r6030-vc{font-size:1.08rem}}
@media(max-width:390px){.r6030-grid{grid-template-columns:1fr}.r6030-strip{grid-template-columns:1fr 1fr}}
</style>
<!-- REDUCED_6030_CHALLENGER_CSS END -->
'''
html = html.replace("</head>", css + "</head>", 1)

panel = r'''
<!-- REDUCED_6030_CHALLENGER_PANEL START -->
<section class="panel r6030-panel" id="reduced6030Panel">
  <div class="r6030-head">
    <div>
      <div class="r6030-title">Comparación de VC estimado</div>
      <div class="r6030-kicker">OLS oficial vs Challenger 60/30 · sin NEM ni FCX + QQQ · cadena ciega sin reanclaje SBS dentro del bloque</div>
    </div>
    <div id="r6030Badge" class="r6030-badge">Cargando…</div>
  </div>
  <div class="r6030-grid">
    <div class="r6030-card">
      <div class="r6030-label">OLS OFICIAL · ROLLING 90</div>
      <div id="r6030OfficialSignal" class="r6030-signal">—</div>
      <div id="r6030OfficialVc" class="r6030-vc">—</div>
      <div id="r6030OfficialRet" class="r6030-ret">—</div>
    </div>
    <div class="r6030-card">
      <div class="r6030-label">60/30 SIN NEM-FCX + QQQ · CHALLENGER</div>
      <div id="r6030ChallengerSignal" class="r6030-signal">—</div>
      <div id="r6030ChallengerVc" class="r6030-vc">—</div>
      <div id="r6030ChallengerRet" class="r6030-ret">—</div>
    </div>
  </div>
  <div class="r6030-strip">
    <div class="r6030-mini"><span>Diferencia de VC</span><b id="r6030VcDiff">—</b></div>
    <div class="r6030-mini"><span>Ciclo congelado</span><b id="r6030Cycle">—</b></div>
    <div class="r6030-mini"><span>Backtest ciego · MAE VC</span><b id="r6030Backtest">—</b></div>
  </div>
  <details class="r6030-details"><summary>Ver validación y reglas del challenger</summary>
    <div style="overflow-x:auto"><table class="r6030-table"><thead><tr><th>Modelo</th><th>MAE VC</th><th>RMSE VC</th><th>Error final medio</th></tr></thead><tbody id="r6030Rows"></tbody></table></div>
    <div id="r6030Forward" class="r6030-note"></div>
  </details>
  <div id="r6030Note" class="r6030-note">El OLS rolling 90 continúa siendo oficial. El 60/30 es el único challenger y se contrasta en sombra contra SBS.</div>
</section>
<!-- REDUCED_6030_CHALLENGER_PANEL END -->
'''
marker = '<section class="panel" id="modelInsightsPanel">'
if marker in html:
    html = html.replace(marker, panel + marker, 1)
else:
    idx = html.find('<section class="panel">')
    if idx < 0:
        raise RuntimeError("No se encontro punto para insertar el challenger 60/30")
    html = html[:idx] + panel + html[idx:]

script = r'''
<!-- REDUCED_6030_CHALLENGER_SCRIPT START -->
<script id="reduced6030Script">
(function(){
  'use strict';
  const $=id=>document.getElementById(id);
  const pct=(x,d=3)=>x==null||!Number.isFinite(Number(x))?'—':(Number(x)*100).toFixed(d)+'%';
  const vc=x=>x==null||!Number.isFinite(Number(x))?'—':Number(x).toFixed(7);
  const num=x=>x==null||!Number.isFinite(Number(x))?'—':Number(x).toFixed(4);
  const cls=s=>s==='SUBE'?'up':s==='BAJA'?'down':'flat';
  function setSignal(id,s){const el=$(id);el.textContent=s||'—';el.className='r6030-signal '+cls(s)}
  fetch('data/reduced_6030_challenger.json?v='+Date.now(),{cache:'no-store'}).then(r=>{if(!r.ok)throw new Error('HTTP '+r.status);return r.json()}).then(d=>{
    const o=d.official||{},c=d.challenger||{},cmp=d.comparison||{},cy=d.cycle||{},bt=d.blind_backtest||{},fw=d.forward_sbs||{};
    setSignal('r6030OfficialSignal',o.signal);setSignal('r6030ChallengerSignal',c.signal);
    $('r6030OfficialVc').textContent='VC '+vc(o.vc_estimated);$('r6030ChallengerVc').textContent='VC '+vc(c.vc_estimated);
    $('r6030OfficialRet').textContent='Retorno '+pct(o.return_estimated);$('r6030ChallengerRet').textContent='Retorno '+pct(c.return_estimated);
    const diff=Number(cmp.vc_difference);$('r6030VcDiff').textContent=Number.isFinite(diff)?(diff>=0?'+':'')+diff.toFixed(7):'—';
    const same=!!cmp.same_signal;$('r6030Badge').textContent=same?'MISMA SEÑAL':'SEÑALES DISTINTAS';$('r6030Badge').className='r6030-badge '+(same?'challenger-ok':'challenger-diff');
    $('r6030Cycle').textContent=`${cy.cycle_day||0}/${cy.freeze_horizon||30} · entrenó ${cy.train_n||60}`;
    const bo=bt.official_current_7f||{},bc=bt.challenger_6030||{};
    $('r6030Backtest').textContent=`${num(bo.vc_mae)} → ${num(bc.vc_mae)}`;
    $('r6030Rows').innerHTML=`<tr><td>OLS actual</td><td>${num(bo.vc_mae)}</td><td>${num(bo.vc_rmse)}</td><td>${num(bo.mean_endpoint_abs_error)}</td></tr><tr><td>60/30 challenger</td><td>${num(bc.vc_mae)}</td><td>${num(bc.vc_rmse)}</td><td>${num(bc.mean_endpoint_abs_error)}</td></tr>`;
    const imp=bt.mae_improvement_pct==null?'—':Number(bt.mae_improvement_pct).toFixed(1)+'%';
    $('r6030Forward').textContent=`Backtest ciego: mejora MAE ${imp}; bloques ganados ${bt.challenger_better_blocks||0}/${bt.n_blocks||0}. Prueba futura SBS: ${fw.evaluated||0} evaluados · ${fw.pending||0} pendientes.`;
    $('r6030Note').textContent=`Ciclo desde ${cy.cycle_start||'—'} · ancla SBS ${cy.anchor_date||'—'} VC ${vc(cy.anchor_vc)} · entrenamiento ${cy.train_start||'—'} a ${cy.train_end||'—'}. SPY, EEM, EPU, MCHI, USD/PEN y QQQ; NEM y FCX excluidos. Los coeficientes quedan congelados 30 sesiones y el VC no se reancla con SBS dentro del bloque.`;
  }).catch(e=>{$('r6030Badge').textContent='NO DISPONIBLE';$('r6030Note').textContent='No se pudo cargar el challenger 60/30: '+e.message});
})();
</script>
<!-- REDUCED_6030_CHALLENGER_SCRIPT END -->
'''
html = html.replace("</body>", script + "</body>", 1)

if "60/30 SIN NEM-FCX + QQQ · CHALLENGER" not in html:
    raise RuntimeError("No quedo insertado el challenger 60/30")
if "QQQ INCREMENTAL · CHALLENGER" in html:
    raise RuntimeError("Persistio visible el challenger QQQ incremental anterior")
if "Challenger Huber · paralelo" in html or 'id="huberChallengerBox"' in html:
    raise RuntimeError("Persistio Huber visible")

HTML_PATH.write_text(html, encoding="utf-8")
print("UI 60/30 aplicada: unico challenger visible, sin NEM/FCX y con QQQ.")
