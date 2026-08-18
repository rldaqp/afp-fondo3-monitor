from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACTIVE_WEB_APP = "https://script.google.com/macros/s/AKfycbxoYHkCu0cZPx_KsMlI0Jd5PEATgxBjZTR8oK8qs1cUjRHJbiK0t-bxkH5ACprgp81S7g/exec"

CONFIG = {
    "profuturo": ROOT / "public" / "index.html",
    "habitat": ROOT / "public" / "habitat" / "index.html",
}

SPY_QQQ_SOURCE = ROOT / "data" / "rolling90" / "profuturo_spy_qqq_windows.json"
SPY_QQQ_PUBLIC = ROOT / "public" / "data" / "spy_qqq_challenger.json"
SPY_QQQ_COMPARE = ROOT / "scripts" / "compare_profuturo_spy_qqq_windows.py"


def block(html: str, script_id: str) -> tuple[int, int, str]:
    start = html.find(f'<script id="{script_id}">')
    if start < 0:
        raise RuntimeError(f"No se encontró {script_id}")
    end = html.find("</script>", start)
    if end < 0:
        raise RuntimeError(f"Bloque incompleto: {script_id}")
    return start, end, html[start:end]


def patch_history(history: str) -> str:
    # El histórico es un IIFE separado: su fetch live debe ser local.
    helper = (
        "  function fetchTradeLiveJson(primary,fallback){return fetch(primary,{cache:'no-store'}).then(r=>{if(!r.ok)throw new Error('HTTP '+r.status);return r.json()}).catch(()=>fetch(fallback,{cache:'no-store'}).then(r=>{if(!r.ok)throw new Error('HTTP '+r.status);return r.json()}))}\n"
    )
    if "function fetchTradeLiveJson(" not in history:
        anchor = "  function signalAt(date){"
        if anchor not in history:
            raise RuntimeError("No se encontró signalAt")
        history = history.replace(anchor, helper + anchor, 1)
    history = history.replace("fetchLiveJson(", "fetchTradeLiveJson(")

    # Si la fecha solicitada todavía no existe en la línea del monitor, se guarda
    # como PENDIENTE y se completa automáticamente cuando aparezca el primer VC
    # efectivo igual o posterior. Así OK · Guardar nunca pierde una operación nueva.
    history = re.sub(
        r"    const ep=entryEffective\(er\);if\(!ep\)\{\$\('tradeMsg'\)\.textContent='No existe una fecha efectiva de entrada en la línea del monitor\.';return\}\n"
        r"    const entryEst=estimateAt\(ep\.fecha\),entryOfficial=officialAt\(ep\.fecha\);\n"
        r"    if\(!finite\(entryEst\)&&entryOfficial===null\)\{\$\('tradeMsg'\)\.textContent='Todavía no existe un VC estimado u oficial para la fecha efectiva de entrada\.';return\}",
        "    const ep=entryEffective(er)||{fecha:er,vc:null,fuente:'PENDIENTE'};\n"
        "    const entryEst=estimateAt(ep.fecha),entryOfficial=officialAt(ep.fecha);",
        history,
        count=1,
    )

    reconcile = """  function reconcile(rows){
    let changed=false;
    rows.forEach(r=>{
      const requested=r.entry_requested||r.entry_date;
      const ep=entryEffective(requested);
      if(ep){
        if(r.entry_date!==ep.fecha){r.entry_date=ep.fecha;changed=true}
        if(!finite(r.entry_est_vc)){const ee=estimateAt(ep.fecha);if(finite(ee)){r.entry_est_vc=Number(ee);changed=true}}
        const ei=officialAt(ep.fecha);
        if(ei!==null&&r.entry_sbs_vc!==ei){r.entry_sbs_vc=ei;changed=true}
      }
      if(r.exit_date){
        const xo=officialAt(r.exit_date);
        if(xo!==null&&r.exit_sbs_vc!==xo){r.exit_sbs_vc=xo;changed=true}
      }
    });
    if(changed)saveRows(rows);
    return rows;
  }

"""
    history, count = re.subn(
        r"  function reconcile\(rows\)\{.*?\n  \}\n\n(?=  function metrics\(r\)\{)",
        reconcile,
        history,
        count=1,
        flags=re.S,
    )
    if count != 1:
        raise RuntimeError("No se pudo actualizar reconcile")

    # El handler se instala antes de cualquier fetch.
    history = history.replace(
        "  async function boot(){\n    try{",
        "  async function boot(){\n    if($('tradeSaveBtn'))$('tradeSaveBtn').onclick=saveCurrent;\n    try{",
        1,
    )
    history = history.replace("      $('tradeSaveBtn').onclick=saveCurrent;render();", "      render();", 1)

    required = [
        "function fetchTradeLiveJson(",
        "const ep=entryEffective(er)||{fecha:er,vc:null,fuente:'PENDIENTE'};",
        "const requested=r.entry_requested||r.entry_date;",
        "if($('tradeSaveBtn'))$('tradeSaveBtn').onclick=saveCurrent;",
    ]
    missing = [x for x in required if x not in history]
    if missing:
        raise AssertionError(f"Histórico sin correcciones runtime: {missing}")
    if "No existe una fecha efectiva de entrada en la línea del monitor." in history:
        raise AssertionError("Sigue activo el bloqueo de fecha efectiva")
    return history


def patch_cloud(cloud: str) -> str:
    cloud, count = re.subn(
        r"const DEFAULT_URL='https://script\.google\.com/macros/s/[^']+/exec';",
        f"const DEFAULT_URL='{ACTIVE_WEB_APP}';",
        cloud,
        count=1,
    )
    if count != 1:
        raise RuntimeError("No se pudo fijar la aplicación web activa")

    # La URL es infraestructura del visor, no una preferencia del navegador.
    # Se sobrescribe el valor antiguo almacenado en localStorage al abrir la página.
    cloud = cloud.replace(
        "    if(!localStorage.getItem(URL_KEY))localStorage.setItem(URL_KEY,DEFAULT_URL);",
        "    localStorage.setItem(URL_KEY,DEFAULT_URL);",
        1,
    )
    if "    localStorage.setItem(URL_KEY,DEFAULT_URL);" not in cloud:
        raise AssertionError("No quedó activa la migración automática de URL")
    return cloud


def refresh_spy_qqq_data() -> None:
    """Actualiza el challenger sin poner en riesgo la señal oficial si Yahoo falla."""
    try:
        subprocess.run([sys.executable, str(SPY_QQQ_COMPARE)], cwd=ROOT, check=True)
    except Exception as exc:
        print(f"Aviso: no se pudo refrescar SPY vs QQQ ({type(exc).__name__}: {exc}). Se conserva el último resultado.")
    if not SPY_QQQ_SOURCE.exists():
        raise RuntimeError("No existe un resultado SPY vs QQQ para publicar")
    payload = json.loads(SPY_QQQ_SOURCE.read_text(encoding="utf-8"))
    if payload.get("fund") != "PROFUTURO" or "windows" not in payload:
        raise RuntimeError("Resultado SPY vs QQQ inválido")
    SPY_QQQ_PUBLIC.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SPY_QQQ_SOURCE, SPY_QQQ_PUBLIC)


def patch_spy_qqq_panel(html: str) -> str:
    css_re = re.compile(r"<!-- SPY_QQQ_CHALLENGER_CSS START -->.*?<!-- SPY_QQQ_CHALLENGER_CSS END -->\n?", re.S)
    panel_re = re.compile(r"<!-- SPY_QQQ_CHALLENGER_PANEL START -->.*?<!-- SPY_QQQ_CHALLENGER_PANEL END -->\n?", re.S)
    script_re = re.compile(r"<!-- SPY_QQQ_CHALLENGER_SCRIPT START -->.*?<!-- SPY_QQQ_CHALLENGER_SCRIPT END -->\n?", re.S)
    html = css_re.sub("", html)
    html = panel_re.sub("", html)
    html = script_re.sub("", html)

    css = r'''<!-- SPY_QQQ_CHALLENGER_CSS START -->
<style id="spyQqqChallengerStyles">
.spyqqq-head{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;margin-bottom:10px}.spyqqq-title{font-size:.96rem;font-weight:850}.spyqqq-kicker{font-size:.68rem;color:#94a3b8;margin-top:2px}.spyqqq-badge{padding:5px 10px;border-radius:999px;font-size:.72rem;font-weight:900;border:1px solid #475569;white-space:nowrap}.spyqqq-mixed{color:#fbbf24}.spyqqq-qqq{color:#38bdf8}.spyqqq-spy{color:#4ade80}.spyqqq-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:8px;margin-bottom:9px}.spyqqq-card{background:#0b1728;border:1px solid #243244;border-radius:11px;padding:10px}.spyqqq-card b{font-size:.82rem}.spyqqq-big{font-size:1.05rem;font-weight:900;margin-top:4px}.spyqqq-sub{font-size:.68rem;color:#94a3b8;margin-top:3px;line-height:1.35}.spyqqq-table{width:100%;border-collapse:collapse;font-size:.72rem;margin-top:8px}.spyqqq-table th,.spyqqq-table td{padding:7px 5px;border-top:1px solid #243244;text-align:right}.spyqqq-table th:first-child,.spyqqq-table td:first-child{text-align:left}.spyqqq-win{font-weight:850;color:#e2e8f0}.spyqqq-note{font-size:.68rem;color:#94a3b8;line-height:1.4;margin-top:8px}
@media(max-width:700px){.spyqqq-head{display:block}.spyqqq-badge{display:inline-block;margin-top:7px}.spyqqq-grid{grid-template-columns:1fr 1fr}.spyqqq-table{font-size:.68rem}.spyqqq-table th,.spyqqq-table td{padding:6px 3px}}
</style>
<!-- SPY_QQQ_CHALLENGER_CSS END -->
'''
    html = html.replace("</head>", css + "</head>", 1)

    panel = r'''<!-- SPY_QQQ_CHALLENGER_PANEL START -->
<section class="panel" id="spyQqqChallengerPanel">
  <div class="spyqqq-head">
    <div><div class="spyqqq-title">Mercado USA · SPY vs Nasdaq QQQ</div><div class="spyqqq-kicker">Challenger diario · no modifica la señal oficial OLS</div></div>
    <div id="spyQqqDominance" class="spyqqq-badge">Cargando…</div>
  </div>
  <div class="spyqqq-grid">
    <div class="spyqqq-card"><b>SPY · modelo actual</b><div class="spyqqq-big" id="spyQqqSpy90">—</div><div class="spyqqq-sub" id="spyQqqSpySub">Últimas 90 predicciones</div></div>
    <div class="spyqqq-card"><b>Nasdaq QQQ · challenger</b><div class="spyqqq-big" id="spyQqqQqq90">—</div><div class="spyqqq-sub" id="spyQqqQqqSub">Últimas 90 predicciones</div></div>
  </div>
  <details><summary>Ver comparación 30 / 60 / 90 / 180 / histórico</summary>
    <div style="overflow-x:auto"><table class="spyqqq-table"><thead><tr><th>Ventana</th><th>SPY acierto</th><th>QQQ acierto</th><th>SPY MAE</th><th>QQQ MAE</th><th>Mejor</th></tr></thead><tbody id="spyQqqRows"></tbody></table></div>
  </details>
  <div class="spyqqq-note" id="spyQqqNote">El modelo oficial sigue usando SPY. Este panel observa si Nasdaq QQQ muestra una ventaja estable antes de considerar cualquier cambio.</div>
</section>
<!-- SPY_QQQ_CHALLENGER_PANEL END -->
'''
    marker = '<section class="panel" id="modelInsightsPanel">'
    if marker not in html:
        marker = '<section class="panel"><div class="tabs">'
    if marker not in html:
        raise RuntimeError("No se encontró punto para insertar el challenger SPY/QQQ")
    html = html.replace(marker, panel + marker, 1)

    script = r'''<!-- SPY_QQQ_CHALLENGER_SCRIPT START -->
<script id="spyQqqChallengerScript">
(function(){
  'use strict';
  const pct=x=>x==null?'—':(Number(x)*100).toFixed(1)+'%';
  const mae=x=>x==null?'—':(Number(x)*100).toFixed(3)+'%';
  const labels={'30':'30','60':'60','90':'90','180':'180','ALL':'Histórico'};
  function dominance(w){
    const core=['60','90','180','ALL'];let qm=0,sm=0,qd=0,sd=0;
    core.forEach(k=>{const r=w[k];if(!r)return;if(r.winner_mae==='QQQ')qm++;else if(r.winner_mae==='SPY')sm++;if(r.winner_direction==='QQQ')qd++;else if(r.winner_direction==='SPY')sd++;});
    if(qm>=3&&qd>=2)return {label:'NASDAQ QQQ DOMINANTE',cls:'spyqqq-qqq'};
    if(sm>=3&&sd>=2)return {label:'SPY DOMINANTE',cls:'spyqqq-spy'};
    return {label:'MERCADO USA · MIXTO',cls:'spyqqq-mixed'};
  }
  function better(r){
    if(!r)return '—';
    const ma=r.winner_mae,di=r.winner_direction;
    if(di==='EMPATE')return ma==='QQQ'?'QQQ ≈ SPY':'SPY ≈ QQQ';
    if(ma===di)return ma;
    return 'MIXTO';
  }
  fetch('data/spy_qqq_challenger.json?ts='+Date.now(),{cache:'no-store'}).then(r=>{if(!r.ok)throw new Error('HTTP '+r.status);return r.json()}).then(d=>{
    const w=d.windows||{},d90=w['90'];if(!d90)throw new Error('Sin ventana 90');
    const dom=dominance(w),badge=document.getElementById('spyQqqDominance');badge.textContent=dom.label;badge.className='spyqqq-badge '+dom.cls;
    document.getElementById('spyQqqSpy90').textContent=pct(d90.SPY.direction_accuracy)+' acierto';
    document.getElementById('spyQqqQqq90').textContent=pct(d90.QQQ.direction_accuracy)+' acierto';
    document.getElementById('spyQqqSpySub').textContent='MAE '+mae(d90.SPY.mae)+' · rolling 90';
    document.getElementById('spyQqqQqqSub').textContent='MAE '+mae(d90.QQQ.mae)+' · rolling 90';
    document.getElementById('spyQqqRows').innerHTML=['30','60','90','180','ALL'].map(k=>{const r=w[k];if(!r)return '';const b=better(r);return `<tr><td>${labels[k]}</td><td>${pct(r.SPY.direction_accuracy)}</td><td>${pct(r.QQQ.direction_accuracy)}</td><td>${mae(r.SPY.mae)}</td><td>${mae(r.QQQ.mae)}</td><td class="spyqqq-win">${b}</td></tr>`}).join('');
    const last=d.last_prediction||'—';document.getElementById('spyQqqNote').textContent=`Último VC SBS evaluado: ${last}. La señal oficial continúa con SPY; QQQ solo actúa como challenger hasta demostrar una ventaja estable en varias ventanas.`;
  }).catch(e=>{const b=document.getElementById('spyQqqDominance');if(b){b.textContent='CHALLENGER NO DISPONIBLE';b.className='spyqqq-badge spyqqq-mixed'}const n=document.getElementById('spyQqqNote');if(n)n.textContent='No se pudo cargar el contraste SPY/QQQ: '+e.message;});
})();
</script>
<!-- SPY_QQQ_CHALLENGER_SCRIPT END -->
'''
    html = html.replace("</body>", script + "</body>", 1)
    required = ["spyQqqChallengerPanel", "spyQqqChallengerScript", "MERCADO USA · MIXTO", "spy_qqq_challenger.json"]
    missing = [x for x in required if x not in html]
    if missing:
        raise AssertionError(f"Panel SPY/QQQ incompleto: {missing}")
    return html


def patch(target: str) -> None:
    path = CONFIG[target]
    html = path.read_text(encoding="utf-8")
    hs, he, history = block(html, "tradeHistoryScript")
    cs, ce, cloud = block(html, "tradeCloudScript")
    history = patch_history(history)
    cloud = patch_cloud(cloud)
    html = html[:hs] + history + html[he:cs] + cloud + html[ce:]
    if target == "profuturo":
        refresh_spy_qqq_data()
        html = patch_spy_qqq_panel(html)
    path.write_text(html, encoding="utf-8")
    if target == "profuturo":
        print("profuturo: Guardar corregido y challenger diario SPY vs Nasdaq QQQ publicado sin alterar la señal oficial.")
    else:
        print("habitat: Guardar admite operación pendiente y fuerza la Web App activa.")


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1].lower() not in CONFIG:
        raise SystemExit("Uso: python postprocess_trade_runtime_fixes.py [profuturo|habitat]")
    patch(sys.argv[1].lower())


if __name__ == "__main__":
    main()
