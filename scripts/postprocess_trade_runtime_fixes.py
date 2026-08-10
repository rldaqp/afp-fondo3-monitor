from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACTIVE_WEB_APP = "https://script.google.com/macros/s/AKfycbxoYHkCu0cZPx_KsMlI0Jd5PEATgxBjZTR8oK8qs1cUjRHJbiK0t-bxkH5ACprgp81S7g/exec"

CONFIG = {
    "profuturo": ROOT / "public" / "index.html",
    "habitat": ROOT / "public" / "habitat" / "index.html",
}


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


def patch(target: str) -> None:
    path = CONFIG[target]
    html = path.read_text(encoding="utf-8")
    hs, he, history = block(html, "tradeHistoryScript")
    cs, ce, cloud = block(html, "tradeCloudScript")
    history = patch_history(history)
    cloud = patch_cloud(cloud)
    html = html[:hs] + history + html[he:cs] + cloud + html[ce:]
    path.write_text(html, encoding="utf-8")
    print(f"{target}: Guardar admite operación pendiente y fuerza la Web App activa.")


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1].lower() not in CONFIG:
        raise SystemExit("Uso: python postprocess_trade_runtime_fixes.py [profuturo|habitat]")
    patch(sys.argv[1].lower())


if __name__ == "__main__":
    main()
