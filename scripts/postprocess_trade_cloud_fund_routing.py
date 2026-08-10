from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

CONFIG = {
    "profuturo": {
        "html": ROOT / "public" / "index.html",
        "fund": "PROFUTURO",
        "sheet": "Profuturo",
        "trade_key": "profuturo_fondo3_trade_history_v3",
        "url_key": "profuturo_fondo3_drive_sync_url_v3",
        "snapshot_key": "profuturo_fondo3_drive_sync_snapshot_v3",
        "origin": "VISOR GITHUB · PROFUTURO",
        "label": "Profuturo",
    },
    "habitat": {
        "html": ROOT / "public" / "habitat" / "index.html",
        "fund": "HABITAT",
        "sheet": "Habitat",
        "trade_key": "habitat_fondo3_trade_history_v3",
        "url_key": "habitat_fondo3_drive_sync_url_v3",
        "snapshot_key": "habitat_fondo3_drive_sync_snapshot_v3",
        "origin": "VISOR GITHUB · HABITAT",
        "label": "Hábitat",
    },
}


def replace_constant(text: str, name: str, value: str) -> str:
    pattern = rf"const {re.escape(name)}='[^']*';"
    replacement = f"const {name}='{value}';"
    updated, count = re.subn(pattern, replacement, text)
    if count == 0:
        raise RuntimeError(f"No se encontró la constante {name}.")
    return updated


def script_block(html: str, script_id: str) -> tuple[int, int, str]:
    start = html.find(f'<script id="{script_id}">')
    if start < 0:
        raise RuntimeError(f"No se encontró {script_id}.")
    end = html.find("</script>", start)
    if end < 0:
        raise RuntimeError(f"Bloque incompleto: {script_id}.")
    return start, end, html[start:end]


def patch_history(history: str, cfg: dict[str, str]) -> str:
    history = replace_constant(history, "KEY", cfg["trade_key"])

    if "const FUND='" not in history:
        history = history.replace(
            "  'use strict';\n",
            "  'use strict';\n"
            f"  const FUND='{cfg['fund']}';\n"
            f"  const ORIGIN='{cfg['origin']}';\n",
            1,
        )
    else:
        history = re.sub(r"const FUND='[^']*';", f"const FUND='{cfg['fund']}';", history, count=1)
        if "const ORIGIN='" in history:
            history = re.sub(r"const ORIGIN='[^']*';", f"const ORIGIN='{cfg['origin']}';", history, count=1)
        else:
            history = history.replace(
                f"  const FUND='{cfg['fund']}';\n",
                f"  const FUND='{cfg['fund']}';\n  const ORIGIN='{cfg['origin']}';\n",
                1,
            )

    # No se migran claves antiguas: cada AFP usa un almacén local v3 exclusivo.
    end_storage = history.find("  function signalAt(")
    if end_storage < 0:
        raise RuntimeError("No se encontró signalAt en el histórico.")
    starts = [
        pos for pos in (
            history.find("  const LEGACY_KEYS="),
            history.find("  function readRowsFrom("),
            history.find("  function loadRows("),
        ) if pos >= 0
    ]
    if not starts:
        raise RuntimeError("No se encontró el bloque de almacenamiento local.")
    start_storage = min(starts)
    storage = (
        "  const LEGACY_KEYS=[];\n"
        "  function readRowsFrom(k){try{const x=JSON.parse(localStorage.getItem(k)||'[]');return Array.isArray(x)?x:[]}catch(e){return []}}\n"
        "  function normalizeRows(list,source){return (Array.isArray(list)?list:[]).filter(x=>x&&typeof x==='object').map((x,i)=>x.id?x:{...x,id:`legacy-${source}-${i}-${x.created_at||''}-${x.entry_date||''}-${x.exit_date||''}`})}\n"
        "  function loadRows(){return normalizeRows(readRowsFrom(KEY),KEY).filter(r=>String(r.fund||FUND).toUpperCase()===FUND)}\n"
        "  function saveRows(rows){const clean=(Array.isArray(rows)?rows:[]).filter(r=>String(r.fund||FUND).toUpperCase()===FUND).map(r=>({...r,fund:FUND,origin:ORIGIN}));localStorage.setItem(KEY,JSON.stringify(clean));window.dispatchEvent(new Event('fondo3-local-trade-change'))}\n"
    )
    history = history[:start_storage] + storage + history[end_storage:]

    history = re.sub(
        r"row=\{id:uid\(\),(?:fund:FUND,origin:ORIGIN,)?created_at:",
        "row={id:uid(),fund:FUND,origin:ORIGIN,created_at:",
        history,
        count=1,
    )

    marker = "    row.fund=FUND;row.origin=ORIGIN;\n    saveRows(rows);render();"
    if marker not in history:
        history = history.replace(
            "    saveRows(rows);render();\n    $('tradeMsg').textContent=",
            marker + "\n    $('tradeMsg').textContent=",
            1,
        )

    # Reemplaza la línea completa. La expresión anterior podía dejar un fragmento
    # duplicado al aplicar el parche por segunda vez y rompía todo el script JS,
    # por lo que el botón OK · Guardar quedaba sin handler.
    listener = "  window.addEventListener('fondo3-cloud-synced',()=>{render();$('tradeMsg').textContent='Operación guardada y sincronizada con Drive.'});"
    history, count = re.subn(
        r"(?m)^\s*window\.addEventListener\('fondo3-cloud-synced'.*$",
        listener,
        history,
        count=1,
    )
    if count == 0:
        history = history.replace("  boot();", listener + "\n  boot();", 1)

    if "});$('tradeMsg').textContent='Operación guardada y sincronizada con Drive.'});" in history:
        raise AssertionError("Quedó un listener duplicado y el JavaScript sería inválido.")
    return history


def patch_cloud(cloud: str, cfg: dict[str, str]) -> str:
    cloud = replace_constant(cloud, "TRADE_KEY", cfg["trade_key"])
    cloud = replace_constant(cloud, "URL_KEY", cfg["url_key"])
    cloud = replace_constant(cloud, "SNAP_KEY", cfg["snapshot_key"])

    if "const FUND='" in cloud:
        cloud = re.sub(r"const FUND='[^']*';", f"const FUND='{cfg['fund']}';", cloud, count=1)
    else:
        cloud = cloud.replace("  'use strict';\n", "  'use strict';\n" + f"  const FUND='{cfg['fund']}';\n", 1)

    if "const DRIVE_SHEET='" in cloud:
        cloud = re.sub(r"const DRIVE_SHEET='[^']*';", f"const DRIVE_SHEET='{cfg['sheet']}';", cloud, count=1)
    else:
        cloud = cloud.replace(
            f"  const FUND='{cfg['fund']}';\n",
            f"  const FUND='{cfg['fund']}';\n  const DRIVE_SHEET='{cfg['sheet']}';\n",
            1,
        )

    cloud = re.sub(r"  const LEGACY_KEYS=\[[^\n]*\];\n", "  const LEGACY_KEYS=[];\n", cloud, count=1)
    if "  const LEGACY_KEYS=[];" not in cloud:
        cloud = cloud.replace(
            f"  const TRADE_KEY='{cfg['trade_key']}';\n",
            f"  const TRADE_KEY='{cfg['trade_key']}';\n  const LEGACY_KEYS=[];\n",
            1,
        )

    cloud = re.sub(
        r"  let syncing=false,timer=null(?:,pending=false)?;",
        "  let syncing=false,timer=null,pending=false;",
        cloud,
        count=1,
    )

    read_start = cloud.find("  const read=(k,fb)=>")
    snapshot_start = cloud.find("  const snapshot=", read_start)
    if read_start < 0 or snapshot_start < 0:
        raise RuntimeError("No se encontró el almacenamiento del bloque Drive.")
    storage = (
        "  const read=(k,fb)=>{try{const x=JSON.parse(localStorage.getItem(k)||'');return x??fb}catch(e){return fb}};\n"
        "  function normalizeRows(list,source){return (Array.isArray(list)?list:[]).filter(x=>x&&typeof x==='object').map((x,i)=>x.id?x:{...x,id:`legacy-${source}-${i}-${x.created_at||''}-${x.entry_date||''}-${x.exit_date||''}`})}\n"
        "  function migrateRows(){return normalizeRows(read(TRADE_KEY,[]),TRADE_KEY).filter(r=>String(r.fund||FUND).toUpperCase()===FUND)}\n"
        "  const rows=()=>migrateRows();\n"
    )
    cloud = cloud[:read_start] + storage + cloud[snapshot_start:]

    if "u.searchParams.set('fund',FUND);" not in cloud:
        cloud = cloud.replace(
            "u.searchParams.set('action',action);",
            "u.searchParams.set('action',action);u.searchParams.set('fund',FUND);",
            1,
        )

    sync_start = cloud.find("  async function syncNow(")
    connect_start = cloud.find("  async function connect(){", sync_start)
    if sync_start < 0 or connect_start < 0:
        raise RuntimeError("No se encontró syncNow/connect.")

    label = cfg["label"]
    sync = f'''  async function syncNow(initial=false){{
    const c=cfg();if(!c.url||!c.key)return;
    if(syncing){{pending=true;return}}
    syncing=true;setStatus('Sincronizando {label} con Drive…','cloud-warn');
    try{{
      // TRADE_CLOUD_FUND_ROUTING_V3
      const probe=await jsonp('ping');
      if(probe.routing!==true||String(probe.fund||'').toUpperCase()!==FUND){{
        throw new Error(`El puente de Drive aún no está actualizado para la hoja ${{DRIVE_SHEET}}.`);
      }}
      const current=rows(),old=snapshot();
      if(old===null){{
        for(const r of current){{await jsonp('upsert',{{payload:JSON.stringify({{...r,fund:FUND}})}})}}
      }}else{{
        const cm=mapById(current),sm=mapById(old);
        for(const [id,r] of cm){{const prev=sm.get(id);if(!prev||stable(prev)!==stable(r))await jsonp('upsert',{{payload:JSON.stringify({{...r,fund:FUND}})}})}}
        for(const id of sm.keys()){{if(!cm.has(id))await jsonp('delete',{{id}})}}
      }}
      const out=await jsonp('list');
      const remote=(Array.isArray(out.rows)?out.rows:[]).filter(r=>String(r.fund||FUND).toUpperCase()===FUND);
      if(!pending)localStorage.setItem(TRADE_KEY,JSON.stringify(remote));
      localStorage.setItem(SNAP_KEY,JSON.stringify(remote));
      setStatus(`Drive {label} conectado · ${{remote.length}} ${{remote.length===1?'operación':'operaciones'}} sincronizadas.`,'cloud-ok');
      window.dispatchEvent(new Event('fondo3-cloud-synced'));
      if(!initial)setTimeout(()=>location.reload(),180);
    }}catch(e){{setStatus('Drive no sincronizó: '+e.message,'cloud-bad')}}
    finally{{syncing=false;if(pending){{pending=false;setTimeout(()=>syncNow(true),0)}}}}
  }}

'''
    cloud = cloud[:sync_start] + sync + cloud[connect_start:]

    boot_start = cloud.find("  function boot(){")
    boot_call = cloud.find("  boot();", boot_start)
    if boot_start < 0 or boot_call < 0:
        raise RuntimeError("No se encontró boot del bloque Drive.")
    boot_end = boot_call + len("  boot();")
    boot = f'''  function boot(){{
    if(!localStorage.getItem(URL_KEY))localStorage.setItem(URL_KEY,DEFAULT_URL);
    const c=cfg();if($('tradeCloudUrl'))$('tradeCloudUrl').value=c.url;if($('tradeCloudKey'))$('tradeCloudKey').value=c.key;
    if($('tradeCloudConnect'))$('tradeCloudConnect').onclick=connect;
    if(c.url&&c.key){{setStatus('Drive {label} configurado. Verificando…','cloud-warn');setTimeout(()=>syncNow(true),900)}}
    window.addEventListener('fondo3-local-trade-change',()=>{{pending=true;syncNow(true)}});
    timer=setInterval(()=>syncNow(true),30000);
  }}
  boot();'''
    cloud = cloud[:boot_start] + boot + cloud[boot_end:]

    return cloud


def patch(target: str) -> None:
    cfg = CONFIG[target]
    path: Path = cfg["html"]
    html = path.read_text(encoding="utf-8")

    history_start, history_end, history = script_block(html, "tradeHistoryScript")
    cloud_start, cloud_end, cloud = script_block(html, "tradeCloudScript")

    history = patch_history(history, cfg)
    cloud = patch_cloud(cloud, cfg)

    html = (
        html[:history_start]
        + history
        + html[history_end:cloud_start]
        + cloud
        + html[cloud_end:]
    )

    required = [
        f"const FUND='{cfg['fund']}';",
        f"const DRIVE_SHEET='{cfg['sheet']}';",
        f"const KEY='{cfg['trade_key']}';",
        f"const TRADE_KEY='{cfg['trade_key']}';",
        "const LEGACY_KEYS=[];",
        f"const SNAP_KEY='{cfg['snapshot_key']}';",
        "u.searchParams.set('fund',FUND);",
        "TRADE_CLOUD_FUND_ROUTING_V3",
        "fondo3-local-trade-change",
        f"const ORIGIN='{cfg['origin']}';",
        "Operación guardada y sincronizada con Drive.",
    ]
    missing = [item for item in required if item not in html]
    if missing:
        raise AssertionError(f"{target}: faltan controles v3 de separación: {missing}")

    path.write_text(html, encoding="utf-8")
    print(f"{target}: separación permanente v3 activa en {cfg['sheet']} y botón Guardar operativo.")


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1].lower() not in CONFIG:
        allowed = " | ".join(CONFIG)
        raise SystemExit(f"Uso: python {Path(__file__).name} [{allowed}]")
    patch(sys.argv[1].lower())


if __name__ == "__main__":
    main()
