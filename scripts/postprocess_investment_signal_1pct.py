from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML_PATH = ROOT / "public" / "index.html"

CSS_START = "<!-- INVESTMENT_SIGNAL_1PCT_CSS START -->"
CSS_END = "<!-- INVESTMENT_SIGNAL_1PCT_CSS END -->"
PANEL_START = "<!-- INVESTMENT_SIGNAL_1PCT_PANEL START -->"
PANEL_END = "<!-- INVESTMENT_SIGNAL_1PCT_PANEL END -->"
SCRIPT_START = "<!-- INVESTMENT_SIGNAL_1PCT_SCRIPT START -->"
SCRIPT_END = "<!-- INVESTMENT_SIGNAL_1PCT_SCRIPT END -->"


def remove_block(html: str, start: str, end: str) -> str:
    return re.sub(re.escape(start) + r".*?" + re.escape(end) + r"\n?", "", html, flags=re.S)


def main() -> None:
    html = HTML_PATH.read_text(encoding="utf-8")

    for start, end in (
        (CSS_START, CSS_END),
        (PANEL_START, PANEL_END),
        (SCRIPT_START, SCRIPT_END),
    ):
        html = remove_block(html, start, end)

    css = r'''<!-- INVESTMENT_SIGNAL_1PCT_CSS START -->
<style id="investmentSignal1PctStyles">
.invest1-head{display:flex;justify-content:space-between;gap:12px;align-items:flex-start;margin-bottom:10px}.invest1-title{font-size:.96rem;font-weight:850}.invest1-kicker{font-size:.69rem;color:#94a3b8;margin-top:3px;line-height:1.35}.invest1-badge{padding:6px 11px;border-radius:999px;border:1px solid #475569;font-size:.76rem;font-weight:900;white-space:nowrap}.invest1-enter{color:#4ade80}.invest1-wait{color:#fbbf24}.invest1-exit{color:#f87171}.invest1-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}.invest1-card{background:#0b1728;border:1px solid #243244;border-radius:11px;padding:10px}.invest1-label{font-size:.69rem;color:#94a3b8}.invest1-value{font-size:1.02rem;font-weight:900;margin-top:4px}.invest1-note{font-size:.7rem;color:#cbd5e1;line-height:1.45;margin-top:9px}.invest1-rule{font-size:.67rem;color:#94a3b8;margin-top:6px;line-height:1.4}
@media(max-width:700px){.invest1-head{display:block}.invest1-badge{display:inline-block;margin-top:7px}.invest1-grid{grid-template-columns:1fr 1fr}.invest1-card:last-child{grid-column:1/-1}}
</style>
<!-- INVESTMENT_SIGNAL_1PCT_CSS END -->
'''
    html = html.replace("</head>", css + "</head>", 1)

    panel = r'''<!-- INVESTMENT_SIGNAL_1PCT_PANEL START -->
<section class="panel" id="investmentSignal1PctPanel">
  <div class="invest1-head">
    <div>
      <div class="invest1-title">Señal de inversión · umbral 1%</div>
      <div class="invest1-kicker">Capa táctica sobre el VC estimado; no cambia la señal oficial SUBE / BAJA / NEUTRO.</div>
    </div>
    <div id="invest1Badge" class="invest1-badge invest1-wait">Cargando…</div>
  </div>
  <div class="invest1-grid">
    <div class="invest1-card"><div class="invest1-label">Margen estimado vs último VC SBS</div><div id="invest1Margin" class="invest1-value">—</div></div>
    <div class="invest1-card"><div class="invest1-label">VC SBS de referencia</div><div id="invest1Sbs" class="invest1-value">—</div></div>
    <div class="invest1-card"><div class="invest1-label">VC estimado usado</div><div id="invest1Estimated" class="invest1-value">—</div></div>
  </div>
  <div id="invest1Note" class="invest1-note">—</div>
  <div class="invest1-rule"><b>Regla:</b> +1.00% o más = ENTRAR · entre −1.00% y +1.00% = ESPERAR · −1.00% o menos = SALIR / NO ENTRAR. Es una regla del visor basada en el modelo, no una garantía de rentabilidad.</div>
</section>
<!-- INVESTMENT_SIGNAL_1PCT_PANEL END -->
'''

    marker = '<section class="panel" id="spyQqqChallengerPanel">'
    if marker not in html:
        marker = '<section class="panel" id="modelInsightsPanel">'
    if marker not in html:
        raise RuntimeError("No se encontró punto de inserción para la señal de inversión")
    html = html.replace(marker, panel + marker, 1)

    script = r'''<!-- INVESTMENT_SIGNAL_1PCT_SCRIPT START -->
<script id="investmentSignal1PctScript">
(function(){
  'use strict';
  const THRESHOLD=0.01;
  const finite=x=>Number.isFinite(Number(x));
  const pct=x=>(Number(x)*100).toFixed(2)+'%';
  const vc=x=>Number(x).toFixed(7);
  function render(latest,live){
    const sbs=Number(latest.latest_sbs_vc);
    const useLive=!!(live&&live.market_open&&finite(live.vc_estimated));
    const estimated=useLive?Number(live.vc_estimated):Number(latest.latest_estimated_vc);
    if(!finite(sbs)||!finite(estimated)||sbs<=0){throw new Error('VC insuficiente')}
    const margin=estimated/sbs-1;
    let label='ESPERAR',cls='invest1-wait',text='El margen estimado todavía no supera el filtro de ±1.00%.';
    if(margin>=THRESHOLD){label='ENTRAR';cls='invest1-enter';text='El VC estimado está al menos 1.00% por encima del último VC oficial SBS.'}
    else if(margin<=-THRESHOLD){label='SALIR / NO ENTRAR';cls='invest1-exit';text='El VC estimado está al menos 1.00% por debajo del último VC oficial SBS.'}
    const badge=document.getElementById('invest1Badge');badge.textContent=label;badge.className='invest1-badge '+cls;
    const m=document.getElementById('invest1Margin');m.textContent=(margin>=0?'+':'')+pct(margin);m.className='invest1-value '+(margin>=THRESHOLD?'pos':margin<=-THRESHOLD?'neg':'zero');
    document.getElementById('invest1Sbs').textContent=vc(sbs);
    document.getElementById('invest1Estimated').textContent=vc(estimated);
    const source=useLive?'intradía provisional':'último cálculo oficial del visor';
    document.getElementById('invest1Note').textContent=`${text} Margen actual: ${(margin>=0?'+':'')+pct(margin)} · fuente: ${source}.`;
  }
  Promise.all([
    fetch('data/latest.json?ts='+Date.now(),{cache:'no-store'}).then(r=>{if(!r.ok)throw new Error('latest '+r.status);return r.json()}),
    fetch('data/live_market.json?ts='+Date.now(),{cache:'no-store'}).then(r=>r.ok?r.json():null).catch(()=>null)
  ]).then(([latest,live])=>render(latest,live)).catch(e=>{
    const badge=document.getElementById('invest1Badge');if(badge){badge.textContent='NO DISPONIBLE';badge.className='invest1-badge invest1-wait'}
    const note=document.getElementById('invest1Note');if(note)note.textContent='No se pudo calcular la señal de inversión: '+e.message;
  });
})();
</script>
<!-- INVESTMENT_SIGNAL_1PCT_SCRIPT END -->
'''
    html = html.replace("</body>", script + "</body>", 1)

    required = [
        "investmentSignal1PctPanel",
        "investmentSignal1PctScript",
        "Señal de inversión · umbral 1%",
        "SALIR / NO ENTRAR",
        "const THRESHOLD=0.01",
    ]
    missing = [item for item in required if item not in html]
    if missing:
        raise AssertionError(f"Señal de inversión incompleta: {missing}")

    HTML_PATH.write_text(html, encoding="utf-8")
    print("Profuturo: señal de inversión ±1% añadida sin alterar OLS oficial.")


if __name__ == "__main__":
    main()
