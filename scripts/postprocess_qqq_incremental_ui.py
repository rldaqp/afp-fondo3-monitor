from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML_PATH = ROOT / "public" / "index.html"
html = HTML_PATH.read_text(encoding="utf-8")

# Retira el panel antiguo que comparaba QQQ como sustituto de SPY. Ese no es el
# challenger aprobado: ahora usamos únicamente la señal incremental de QQQ.
for start, end in [
    ("<!-- SPY_QQQ_CHALLENGER_CSS START -->", "<!-- SPY_QQQ_CHALLENGER_CSS END -->"),
    ("<!-- SPY_QQQ_CHALLENGER_PANEL START -->", "<!-- SPY_QQQ_CHALLENGER_PANEL END -->"),
    ("<!-- SPY_QQQ_CHALLENGER_SCRIPT START -->", "<!-- SPY_QQQ_CHALLENGER_SCRIPT END -->"),
    ("<!-- QQQ_INCREMENTAL_CHALLENGER_UI_V1 START -->", "<!-- QQQ_INCREMENTAL_CHALLENGER_UI_V1 END -->"),
    ("<!-- QQQ_INCREMENTAL_CHALLENGER_PANEL_V1 START -->", "<!-- QQQ_INCREMENTAL_CHALLENGER_PANEL_V1 END -->"),
    ("<!-- QQQ_INCREMENTAL_CHALLENGER_SCRIPT_V1 START -->", "<!-- QQQ_INCREMENTAL_CHALLENGER_SCRIPT_V1 END -->"),
]:
    html = re.sub(re.escape(start) + r".*?" + re.escape(end), "", html, flags=re.S)

# Huber deja de mostrarse. Conservamos nodos ocultos para que cualquier JS
# heredado que todavía los consulte no rompa el resto del visor.
html = re.sub(
    r'<div class="challenger-box" id="huberChallengerBox">.*?</div>\s*</div>',
    '<div id="huberChallengerBox" hidden><span id="huberValue"></span><span id="huberSub"></span></div>',
    html,
    count=1,
    flags=re.S,
)
html = html.replace("Challenger Huber · paralelo", "")
html = re.sub(
    r"\$\('qualitySub'\)\.textContent=`OLS \$\{q\.training_n\|\|0\}/90 · Huber \$\{h\.training&&h\.training\.n\?h\.training\.n:0\}/90 · FX \$\{q\.fx_provisional\?'provisional':'confirmado'\}`;",
    "$('qualitySub').textContent=`OLS ${q.training_n||0}/90 · FX ${q.fx_provisional?'provisional':'confirmado'}`;",
    html,
    count=1,
)

css = r'''
<!-- QQQ_INCREMENTAL_CHALLENGER_UI_V1 START -->
<style id="qqqIncrementalStyles">
.qqqi-panel{border-color:#334155}.qqqi-head{display:flex;justify-content:space-between;gap:12px;align-items:flex-start;margin-bottom:10px}.qqqi-title{font-size:.98rem;font-weight:900}.qqqi-kicker{font-size:.7rem;color:#94a3b8;margin-top:3px;line-height:1.35}.qqqi-badge{padding:5px 9px;border:1px solid #475569;border-radius:999px;font-size:.7rem;font-weight:900;white-space:nowrap}.qqqi-grid{display:grid;grid-template-columns:1fr 1fr;gap:9px}.qqqi-card{background:#0b1728;border:1px solid #243244;border-radius:12px;padding:11px}.qqqi-label{font-size:.72rem;color:#94a3b8;font-weight:800}.qqqi-signal{font-size:1.15rem;font-weight:950;margin-top:5px}.qqqi-vc{font-size:1.18rem;font-weight:950;margin-top:4px}.qqqi-ret{font-size:.76rem;color:#cbd5e1;margin-top:3px}.qqqi-strip{display:grid;grid-template-columns:repeat(3,1fr);gap:7px;margin-top:9px}.qqqi-mini{background:#101d31;border:1px solid #243244;border-radius:9px;padding:8px}.qqqi-mini span{display:block;color:#94a3b8;font-size:.65rem}.qqqi-mini b{display:block;margin-top:3px;font-size:.8rem}.qqqi-note{font-size:.68rem;color:#94a3b8;line-height:1.4;margin-top:8px}.qqqi-details{margin-top:8px}.qqqi-details summary{cursor:pointer;color:#cbd5e1;font-size:.72rem;font-weight:800}.qqqi-table{width:100%;border-collapse:collapse;font-size:.69rem;margin-top:7px}.qqqi-table th,.qqqi-table td{padding:6px 4px;border-top:1px solid #243244;text-align:right}.qqqi-table th:first-child,.qqqi-table td:first-child{text-align:left}
@media(max-width:700px){.qqqi-head{display:block}.qqqi-badge{display:inline-block;margin-top:7px}.qqqi-grid{grid-template-columns:1fr 1fr}.qqqi-strip{grid-template-columns:1fr 1fr}.qqqi-mini:last-child{grid-column:1/-1}.qqqi-vc{font-size:1.08rem}}
@media(max-width:390px){.qqqi-grid{grid-template-columns:1fr}.qqqi-strip{grid-template-columns:1fr 1fr}}
</style>
<!-- QQQ_INCREMENTAL_CHALLENGER_UI_V1 END -->
'''
html = html.replace("</head>", css + "</head>", 1)

panel = r'''
<!-- QQQ_INCREMENTAL_CHALLENGER_PANEL_V1 START -->
<section class="panel qqqi-panel" id="qqqIncrementalPanel">
  <div class="qqqi-head">
    <div><div class="qqqi-title">Comparación de VC estimado</div><div class="qqqi-kicker">OLS oficial vs QQQ incremental residualizado · mismo VC base · challenger en sombra</div></div>
    <div id="qqqiBadge" class="qqqi-badge">Cargando…</div>
  </div>
  <div class="qqqi-grid">
    <div class="qqqi-card">
      <div class="qqqi-label">OLS OFICIAL</div>
      <div id="qqqiOfficialSignal" class="qqqi-signal">—</div>
      <div id="qqqiOfficialVc" class="qqqi-vc">—</div>
      <div id="qqqiOfficialRet" class="qqqi-ret">—</div>
    </div>
    <div class="qqqi-card">
      <div class="qqqi-label">QQQ INCREMENTAL · CHALLENGER</div>
      <div id="qqqiChallengerSignal" class="qqqi-signal">—</div>
      <div id="qqqiChallengerVc" class="qqqi-vc">—</div>
      <div id="qqqiChallengerRet" class="qqqi-ret">—</div>
    </div>
  </div>
  <div class="qqqi-strip">
    <div class="qqqi-mini"><span>Diferencia de VC</span><b id="qqqiVcDiff">—</b></div>
    <div class="qqqi-mini"><span>Backtest 90d · MAE</span><b id="qqqiMae90">—</b></div>
    <div class="qqqi-mini"><span>Prueba futura SBS</span><b id="qqqiForward">—</b></div>
  </div>
  <details class="qqqi-details"><summary>Ver desempeño 30 / 60 / 90 / 180 / histórico</summary>
    <div style="overflow-x:auto"><table class="qqqi-table"><thead><tr><th>Ventana</th><th>MAE OLS</th><th>MAE QQQ inc.</th><th>Acierto OLS</th><th>Acierto QQQ inc.</th><th>Δ MAE</th></tr></thead><tbody id="qqqiRows"></tbody></table></div>
  </details>
  <div id="qqqiNote" class="qqqi-note">El OLS continúa siendo la señal oficial. El challenger se evalúa en paralelo contra los VC que publique la SBS.</div>
</section>
<!-- QQQ_INCREMENTAL_CHALLENGER_PANEL_V1 END -->
'''

# Inserta inmediatamente antes del panel de calidad del modelo. Si no existe,
# lo ubica antes del primer panel posterior al resumen principal.
marker = '<section class="panel" id="modelInsightsPanel">'
if marker in html:
    html = html.replace(marker, panel + marker, 1)
else:
    idx = html.find('<section class="panel">')
    if idx < 0:
        raise RuntimeError("No se encontró punto para insertar el challenger QQQ")
    html = html[:idx] + panel + html[idx:]

script = r'''
<!-- QQQ_INCREMENTAL_CHALLENGER_SCRIPT_V1 START -->
<script id="qqqIncrementalScript">
(function(){
  'use strict';
  const $=id=>document.getElementById(id);
  const pct=(x,d=3)=>x==null||!Number.isFinite(Number(x))?'—':(Number(x)*100).toFixed(d)+'%';
  const vc=x=>x==null||!Number.isFinite(Number(x))?'—':Number(x).toFixed(7);
  const cls=s=>s==='SUBE'?'up':s==='BAJA'?'down':'flat';
  const fmtMae=x=>x==null||!Number.isFinite(Number(x))?'—':(Number(x)*100).toFixed(3)+'%';
  const fmtAcc=x=>x==null||!Number.isFinite(Number(x))?'—':(Number(x)*100).toFixed(1)+'%';
  function setSignal(id,s){const el=$(id);el.textContent=s||'—';el.className='qqqi-signal '+cls(s)}
  fetch('data/qqq_incremental_challenger.json?v='+Date.now(),{cache:'no-store'}).then(r=>{if(!r.ok)throw new Error('HTTP '+r.status);return r.json()}).then(d=>{
    const o=d.official||{},c=d.challenger||{},cmp=d.comparison||{},bt=d.performance_backtest||{},w=bt.windows||{},f=d.shadow_forward||{};
    setSignal('qqqiOfficialSignal',o.signal);setSignal('qqqiChallengerSignal',c.signal);
    $('qqqiOfficialVc').textContent='VC '+vc(o.vc_estimated);$('qqqiChallengerVc').textContent='VC '+vc(c.vc_estimated);
    $('qqqiOfficialRet').textContent='Retorno '+pct(o.return_estimated);$('qqqiChallengerRet').textContent='Retorno '+pct(c.return_estimated);
    const diff=Number(cmp.vc_difference);$('qqqiVcDiff').textContent=Number.isFinite(diff)?(diff>=0?'+':'')+diff.toFixed(7):'—';
    const same=!!cmp.same_signal;$('qqqiBadge').textContent=same?'MISMA SEÑAL':'SEÑALES DISTINTAS';$('qqqiBadge').className='qqqi-badge '+(same?'challenger-ok':'challenger-diff');
    const m90=w['90']||{};$('qqqiMae90').textContent=`${fmtMae(m90.official_mae)} → ${fmtMae(m90.challenger_mae)}`;
    $('qqqiForward').textContent=(f.n||0)+' evaluados · '+(f.pending||0)+' pendientes';
    const labels={'30':'30 días','60':'60 días','90':'90 días','180':'180 días','ALL':'Histórico'};
    $('qqqiRows').innerHTML=['30','60','90','180','ALL'].map(k=>{const r=w[k]||{};const imp=r.mae_improvement_pct;return `<tr><td>${labels[k]}</td><td>${fmtMae(r.official_mae)}</td><td>${fmtMae(r.challenger_mae)}</td><td>${fmtAcc(r.official_direction_accuracy)}</td><td>${fmtAcc(r.challenger_direction_accuracy)}</td><td>${imp==null?'—':(Number(imp)>=0?'+':'')+Number(imp).toFixed(2)+'%'}</td></tr>`}).join('');
    const source=d.qqq&&d.qqq.source?d.qqq.source:'QQQ';
    $('qqqiNote').textContent=`Fecha ${d.signal_date||'—'} · ${source} · QQQ residual ${pct(d.qqq&&d.qqq.residual,3)}. OLS sigue oficial; el challenger queda registrado para contraste futuro con SBS.`;
  }).catch(e=>{$('qqqiBadge').textContent='NO DISPONIBLE';$('qqqiNote').textContent='No se pudo cargar el challenger QQQ incremental: '+e.message});
})();
</script>
<!-- QQQ_INCREMENTAL_CHALLENGER_SCRIPT_V1 END -->
'''
html = html.replace("</body>", script + "</body>", 1)

# Comprobaciones anti-regresión del postprocesado.
if "QQQ INCREMENTAL · CHALLENGER" not in html:
    raise RuntimeError("No quedó insertado el panel QQQ incremental")
if "SPY_QQQ_CHALLENGER_PANEL START" in html:
    raise RuntimeError("Persistió el panel antiguo SPY vs QQQ")
if "Challenger Huber · paralelo" in html:
    raise RuntimeError("Persistió Huber visible")

HTML_PATH.write_text(html, encoding="utf-8")
print("UI QQQ incremental aplicada; Huber retirado de la vista.")
