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

    # Retira la versión anterior de panel grande para no sobrecargar el visor.
    for start, end in (
        (CSS_START, CSS_END),
        (PANEL_START, PANEL_END),
        (SCRIPT_START, SCRIPT_END),
    ):
        html = remove_block(html, start, end)

    # Limpia una inserción compacta previa, si existe.
    html = re.sub(r'<div id="vcPrecisionCompact"[^>]*>.*?</div>', "", html, flags=re.S)

    # En el visor, la constante del modelo debe mostrarse como tal y no como "Base".
    # No altera el intercepto ni ningún cálculo OLS; solo cambia la etiqueta visible.
    html = html.replace(
        "out.push({label:'Base',contribution_pp:Number(beta.intercept||0)*100});",
        "out.push({label:'Constante',contribution_pp:Number(beta.intercept||0)*100});",
    )
    html = html.replace(
        '<b>${x.label}</b><div class="factor-track">',
        '<b>${x.label===\'Base\'?\'Constante\':x.label}</b><div class="factor-track">',
    )

    css = r'''<!-- INVESTMENT_SIGNAL_1PCT_CSS START -->
<style id="investmentSignal1PctStyles">
.vc-precision-compact{display:none;margin-top:4px;font-size:.72rem;font-weight:800;color:#cbd5e1;line-height:1.25}
</style>
<!-- INVESTMENT_SIGNAL_1PCT_CSS END -->
'''
    html = html.replace("</head>", css + "</head>", 1)

    ret_marker = '<div class="sub" id="ret">—</div>'
    if ret_marker not in html:
        raise RuntimeError("No se encontró la línea de retorno de la tarjeta Señal")
    html = html.replace(
        ret_marker,
        ret_marker + '<div id="vcPrecisionCompact" class="vc-precision-compact"></div>',
        1,
    )

    script = r'''<!-- INVESTMENT_SIGNAL_1PCT_SCRIPT START -->
<script id="investmentSignal1PctScript">
(function(){
  'use strict';
  const THRESHOLD_PCT=1.0;
  const target=document.getElementById('vcPrecisionCompact');
  const retNode=document.getElementById('ret');
  if(!target||!retNode)return;

  let accuracy=null;
  function currentReturnPct(){
    const txt=String(retNode.textContent||'').replace(',', '.');
    const m=txt.match(/([+-]?\d+(?:\.\d+)?)\s*%/);
    return m?Number(m[1]):NaN;
  }
  function render(){
    const r=currentReturnPct();
    if(Number.isFinite(r)&&Math.abs(r)>=THRESHOLD_PCT&&Number.isFinite(accuracy)){
      target.textContent='Precisión VC: '+accuracy.toFixed(1)+'%';
      target.style.display='block';
    }else{
      target.textContent='';
      target.style.display='none';
    }
  }

  fetch('data/vc_accuracy_1pct.json?ts='+Date.now(),{cache:'no-store'})
    .then(r=>{if(!r.ok)throw new Error(String(r.status));return r.json()})
    .then(x=>{accuracy=Number(x.accuracy)*100;render()})
    .catch(()=>{accuracy=null;render()});

  new MutationObserver(render).observe(retNode,{childList:true,subtree:true,characterData:true});
  render();
})();

// SBS_TOP_CARD_RUNTIME_V1
// La tarjeta SBS no depende del resto del visor: lee directamente latest.json.
// Esto evita que quede en "—" si otro postproceso retira o cambia el arranque legado.
(function(){
  'use strict';
  const byId=id=>document.getElementById(id);
  const fmt=d=>{
    if(!d)return '—';
    const p=String(d).slice(0,10).split('-');
    return p.length===3?`${p[2]}/${p[1]}/${p[0]}`:String(d);
  };
  function paintSbs(l){
    if(!l)return;
    const value=Number(l.latest_sbs_vc);
    const vcNode=byId('sbsVc'),dateNode=byId('sbsDate'),windowNode=byId('window');
    if(vcNode)vcNode.textContent=Number.isFinite(value)?value.toFixed(7):'—';
    if(dateNode)dateNode.textContent=fmt(l.latest_sbs_date);
    if(windowNode)windowNode.textContent=`${fmt(l.training_start)} → ${fmt(l.training_end)}`;
  }
  const loadSbs=()=>fetch('data/latest.json?ts='+Date.now(),{cache:'no-store'})
    .then(r=>{if(!r.ok)throw new Error(String(r.status));return r.json()})
    .then(paintSbs)
    .catch(()=>{});
  if(document.readyState==='loading'){
    document.addEventListener('DOMContentLoaded',loadSbs,{once:true});
  }else{
    loadSbs();
  }
  setTimeout(loadSbs,700);
  setTimeout(loadSbs,1800);
})();
</script>
<!-- INVESTMENT_SIGNAL_1PCT_SCRIPT END -->
'''
    html = html.replace("</body>", script + "</body>", 1)

    required = [
        "vcPrecisionCompact",
        "Precisión VC:",
        "data/vc_accuracy_1pct.json",
        "THRESHOLD_PCT=1.0",
        "Constante",
        "SBS_TOP_CARD_RUNTIME_V1",
        "latest_sbs_vc",
    ]
    missing = [item for item in required if item not in html]
    if missing:
        raise AssertionError(f"Precisión compacta del VC incompleta: {missing}")
    if "investmentSignal1PctPanel" in html:
        raise AssertionError("El panel grande de señal de inversión no fue retirado")

    HTML_PATH.write_text(html, encoding="utf-8")
    print("Profuturo: precisión VC compacta y carga independiente del último VC SBS activadas.")


if __name__ == "__main__":
    main()
