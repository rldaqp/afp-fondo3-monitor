from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML_PATH = ROOT / "public" / "habitat" / "index.html"
html = HTML_PATH.read_text(encoding="utf-8")

# La plantilla de Hábitat se construye a partir de la visual de Profuturo y puede
# heredar sus bloques QQQ. Antes de insertar el panel propio de Hábitat retiramos
# tanto el contraste antiguo SPY-vs-QQQ como cualquier QQQ incremental genérico.
for start, end in [
    ("<!-- SPY_QQQ_CHALLENGER_CSS START -->", "<!-- SPY_QQQ_CHALLENGER_CSS END -->"),
    ("<!-- SPY_QQQ_CHALLENGER_PANEL START -->", "<!-- SPY_QQQ_CHALLENGER_PANEL END -->"),
    ("<!-- SPY_QQQ_CHALLENGER_SCRIPT START -->", "<!-- SPY_QQQ_CHALLENGER_SCRIPT END -->"),
    ("<!-- QQQ_INCREMENTAL_CHALLENGER_UI_V1 START -->", "<!-- QQQ_INCREMENTAL_CHALLENGER_UI_V1 END -->"),
    ("<!-- QQQ_INCREMENTAL_CHALLENGER_PANEL_V1 START -->", "<!-- QQQ_INCREMENTAL_CHALLENGER_PANEL_V1 END -->"),
    ("<!-- QQQ_INCREMENTAL_CHALLENGER_SCRIPT_V1 START -->", "<!-- QQQ_INCREMENTAL_CHALLENGER_SCRIPT_V1 END -->"),
    ("<!-- HABITAT_QQQ_INCREMENTAL_UI_V1 START -->", "<!-- HABITAT_QQQ_INCREMENTAL_UI_V1 END -->"),
    ("<!-- HABITAT_QQQ_INCREMENTAL_PANEL_V1 START -->", "<!-- HABITAT_QQQ_INCREMENTAL_PANEL_V1 END -->"),
    ("<!-- HABITAT_QQQ_INCREMENTAL_SCRIPT_V1 START -->", "<!-- HABITAT_QQQ_INCREMENTAL_SCRIPT_V1 END -->"),
]:
    html = re.sub(re.escape(start) + r".*?" + re.escape(end), "", html, flags=re.S)

css = r'''
<!-- HABITAT_QQQ_INCREMENTAL_UI_V1 START -->
<style id="habitatQqqIncrementalStyles">
.hqqqi-panel{border-color:#334155}.hqqqi-head{display:flex;justify-content:space-between;gap:12px;align-items:flex-start;margin-bottom:10px}.hqqqi-title{font-size:.98rem;font-weight:900}.hqqqi-kicker{font-size:.7rem;color:#94a3b8;margin-top:3px;line-height:1.35}.hqqqi-badge{padding:5px 9px;border:1px solid #475569;border-radius:999px;font-size:.7rem;font-weight:900;white-space:nowrap}.hqqqi-grid{display:grid;grid-template-columns:1fr 1fr;gap:9px}.hqqqi-card{background:#0b1728;border:1px solid #243244;border-radius:12px;padding:11px}.hqqqi-label{font-size:.72rem;color:#94a3b8;font-weight:800}.hqqqi-signal{font-size:1.15rem;font-weight:950;margin-top:5px}.hqqqi-vc{font-size:1.18rem;font-weight:950;margin-top:4px}.hqqqi-ret{font-size:.76rem;color:#cbd5e1;margin-top:3px}.hqqqi-strip{display:grid;grid-template-columns:repeat(3,1fr);gap:7px;margin-top:9px}.hqqqi-mini{background:#101d31;border:1px solid #243244;border-radius:9px;padding:8px}.hqqqi-mini span{display:block;color:#94a3b8;font-size:.65rem}.hqqqi-mini b{display:block;margin-top:3px;font-size:.8rem}.hqqqi-note{font-size:.68rem;color:#94a3b8;line-height:1.4;margin-top:8px}.hqqqi-details{margin-top:8px}.hqqqi-details summary{cursor:pointer;color:#cbd5e1;font-size:.72rem;font-weight:800}.hqqqi-table{width:100%;border-collapse:collapse;font-size:.69rem;margin-top:7px}.hqqqi-table th,.hqqqi-table td{padding:6px 4px;border-top:1px solid #243244;text-align:right}.hqqqi-table th:first-child,.hqqqi-table td:first-child{text-align:left}
@media(max-width:700px){.hqqqi-head{display:block}.hqqqi-badge{display:inline-block;margin-top:7px}.hqqqi-grid{grid-template-columns:1fr 1fr}.hqqqi-strip{grid-template-columns:1fr 1fr}.hqqqi-mini:last-child{grid-column:1/-1}.hqqqi-vc{font-size:1.08rem}}
@media(max-width:390px){.hqqqi-grid{grid-template-columns:1fr}.hqqqi-strip{grid-template-columns:1fr 1fr}}
</style>
<!-- HABITAT_QQQ_INCREMENTAL_UI_V1 END -->
'''
html = html.replace("</head>", css + "</head>", 1)

panel = r'''
<!-- HABITAT_QQQ_INCREMENTAL_PANEL_V1 START -->
<section class="panel hqqqi-panel" id="habitatQqqIncrementalPanel">
  <div class="hqqqi-head">
    <div><div class="hqqqi-title">Comparación de VC estimado</div><div class="hqqqi-kicker">OLS oficial Hábitat vs QQQ incremental residualizado · mismo VC base · challenger en sombra</div></div>
    <div id="hqqqiBadge" class="hqqqi-badge">Cargando…</div>
  </div>
  <div class="hqqqi-grid">
    <div class="hqqqi-card">
      <div class="hqqqi-label">OLS OFICIAL · HÁBITAT</div>
      <div id="hqqqiOfficialSignal" class="hqqqi-signal">—</div>
      <div id="hqqqiOfficialVc" class="hqqqi-vc">—</div>
      <div id="hqqqiOfficialRet" class="hqqqi-ret">—</div>
    </div>
    <div class="hqqqi-card">
      <div class="hqqqi-label">QQQ INCREMENTAL · CHALLENGER</div>
      <div id="hqqqiChallengerSignal" class="hqqqi-signal">—</div>
      <div id="hqqqiChallengerVc" class="hqqqi-vc">—</div>
      <div id="hqqqiChallengerRet" class="hqqqi-ret">—</div>
    </div>
  </div>
  <div class="hqqqi-strip">
    <div class="hqqqi-mini"><span>Diferencia de VC</span><b id="hqqqiVcDiff">—</b></div>
    <div class="hqqqi-mini"><span>Backtest 90d · MAE</span><b id="hqqqiMae90">—</b></div>
    <div class="hqqqi-mini"><span>Prueba futura SBS</span><b id="hqqqiForward">—</b></div>
  </div>
  <details class="hqqqi-details"><summary>Ver desempeño 30 / 60 / 90 / 180 / histórico</summary>
    <div style="overflow-x:auto"><table class="hqqqi-table"><thead><tr><th>Ventana</th><th>MAE OLS</th><th>MAE QQQ inc.</th><th>Acierto OLS</th><th>Acierto QQQ inc.</th><th>Δ MAE</th></tr></thead><tbody id="hqqqiRows"></tbody></table></div>
  </details>
  <div id="hqqqiNote" class="hqqqi-note">El OLS de Hábitat continúa siendo la señal oficial. QQQ se evalúa únicamente como información incremental.</div>
</section>
<!-- HABITAT_QQQ_INCREMENTAL_PANEL_V1 END -->
'''

marker = "<!-- HABITAT_SBS_INDICATORS_V1 START -->"
if marker in html:
    html = html.replace(marker, panel + marker, 1)
elif '<section class="panel" id="modelInsightsPanel">' in html:
    html = html.replace('<section class="panel" id="modelInsightsPanel">', panel + '<section class="panel" id="modelInsightsPanel">', 1)
else:
    raise RuntimeError("No se encontró punto de inserción para el challenger QQQ de Hábitat")

script = r'''
<!-- HABITAT_QQQ_INCREMENTAL_SCRIPT_V1 START -->
<script id="habitatQqqIncrementalScript">
(function(){
  'use strict';
  const $=id=>document.getElementById(id);
  const pct=(x,d=3)=>x==null||!Number.isFinite(Number(x))?'—':(Number(x)*100).toFixed(d)+'%';
  const vc=x=>x==null||!Number.isFinite(Number(x))?'—':Number(x).toFixed(7);
  const cls=s=>s==='SUBE'?'up':s==='BAJA'?'down':'flat';
  const fmtMae=x=>x==null||!Number.isFinite(Number(x))?'—':(Number(x)*100).toFixed(3)+'%';
  const fmtAcc=x=>x==null||!Number.isFinite(Number(x))?'—':(Number(x)*100).toFixed(1)+'%';
  function setSignal(id,s){const el=$(id);el.textContent=s||'—';el.className='hqqqi-signal '+cls(s)}
  fetch('data/qqq_incremental_challenger.json?v='+Date.now(),{cache:'no-store'}).then(r=>{if(!r.ok)throw new Error('HTTP '+r.status);return r.json()}).then(d=>{
    const o=d.official||{},c=d.challenger||{},cmp=d.comparison||{},bt=d.performance_backtest||{},w=bt.windows||{},f=d.shadow_forward||{};
    setSignal('hqqqiOfficialSignal',o.signal);setSignal('hqqqiChallengerSignal',c.signal);
    $('hqqqiOfficialVc').textContent='VC '+vc(o.vc_estimated);$('hqqqiChallengerVc').textContent='VC '+vc(c.vc_estimated);
    $('hqqqiOfficialRet').textContent='Retorno '+pct(o.return_estimated);$('hqqqiChallengerRet').textContent='Retorno '+pct(c.return_estimated);
    const diff=Number(cmp.vc_difference);$('hqqqiVcDiff').textContent=Number.isFinite(diff)?(diff>=0?'+':'')+diff.toFixed(7):'—';
    const same=!!cmp.same_signal;$('hqqqiBadge').textContent=same?'MISMA SEÑAL':'SEÑALES DISTINTAS';$('hqqqiBadge').className='hqqqi-badge '+(same?'challenger-ok':'challenger-diff');
    const m90=w['90']||{};$('hqqqiMae90').textContent=`${fmtMae(m90.official_mae)} → ${fmtMae(m90.challenger_mae)}`;
    $('hqqqiForward').textContent=(f.n||0)+' evaluados · '+(f.pending||0)+' pendientes';
    const labels={'30':'30 días','60':'60 días','90':'90 días','180':'180 días','ALL':'Histórico'};
    $('hqqqiRows').innerHTML=['30','60','90','180','ALL'].map(k=>{const r=w[k]||{};const imp=r.mae_improvement_pct;return `<tr><td>${labels[k]}</td><td>${fmtMae(r.official_mae)}</td><td>${fmtMae(r.challenger_mae)}</td><td>${fmtAcc(r.official_direction_accuracy)}</td><td>${fmtAcc(r.challenger_direction_accuracy)}</td><td>${imp==null?'—':(Number(imp)>=0?'+':'')+Number(imp).toFixed(2)+'%'}</td></tr>`}).join('');
    const source=d.qqq&&d.qqq.source?d.qqq.source:'QQQ';
    $('hqqqiNote').textContent=`Fecha ${d.signal_date||'—'} · ${source} · QQQ residual ${pct(d.qqq&&d.qqq.residual,3)}. Ambos VC usan exactamente la misma base; el OLS de Hábitat sigue oficial.`;
  }).catch(e=>{$('hqqqiBadge').textContent='NO DISPONIBLE';$('hqqqiNote').textContent='No se pudo cargar el challenger QQQ incremental de Hábitat: '+e.message});
})();
</script>
<!-- HABITAT_QQQ_INCREMENTAL_SCRIPT_V1 END -->
'''
html = html.replace("</body>", script + "</body>", 1)

if "QQQ INCREMENTAL · CHALLENGER" not in html:
    raise RuntimeError("No quedó insertado el panel QQQ incremental de Hábitat")
if "SPY_QQQ_CHALLENGER_PANEL START" in html or "Mercado USA · SPY vs Nasdaq QQQ" in html:
    raise RuntimeError("Persistió el panel antiguo SPY vs QQQ en Hábitat")
if "QQQ_INCREMENTAL_CHALLENGER_PANEL_V1 START" in html or 'id="qqqIncrementalPanel"' in html:
    raise RuntimeError("Persistió el panel QQQ genérico de Profuturo dentro de Hábitat")
if html.count("HABITAT_QQQ_INCREMENTAL_PANEL_V1 START") != 1:
    raise RuntimeError("El panel QQQ de Hábitat quedó duplicado")

HTML_PATH.write_text(html, encoding="utf-8")
print("Hábitat: único panel QQQ incremental aplicado; herencias de Profuturo retiradas.")
