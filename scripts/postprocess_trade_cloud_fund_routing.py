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
        "trade_key": "profuturo_fondo3_trade_history_v2",
        "legacy_keys": ["fondo3_trade_history_v1", "profuturo_fondo3_trade_history_v1"],
        "url_key": "profuturo_fondo3_drive_sync_url_v3",
        "snapshot_key": "profuturo_fondo3_drive_sync_snapshot_v2",
    },
    "habitat": {
        "html": ROOT / "public" / "habitat" / "index.html",
        "fund": "HABITAT",
        "sheet": "Habitat",
        "trade_key": "habitat_fondo3_trade_history_v2",
        "legacy_keys": ["habitat_fondo3_trade_history_v1"],
        "url_key": "habitat_fondo3_drive_sync_url_v3",
        "snapshot_key": "habitat_fondo3_drive_sync_snapshot_v2",
    },
}


def replace_constant(text: str, name: str, value: str) -> str:
    pattern = rf"const {re.escape(name)}='[^']*';"
    replacement = f"const {name}='{value}';"
    updated, count = re.subn(pattern, replacement, text)
    if count == 0:
        raise RuntimeError(f"No se encontró la constante {name}.")
    return updated


def js_array(values: list[str]) -> str:
    return "[" + ",".join(f"'{value}'" for value in values) + "]"


def ensure_history_migration(history: str, keys: list[str]) -> str:
    legacy_line = f"  const LEGACY_KEYS={js_array(keys)};"
    history = re.sub(r"  const LEGACY_KEYS=\[[^\]]*\];", legacy_line, history)
    if legacy_line not in history:
        history = history.replace(
            "  let signals=[],timeline=[],live=null;\n",
            legacy_line + "\n  let signals=[],timeline=[],live=null;\n",
            1,
        )

    old_loader = (
        "  function loadRows(){try{const x=JSON.parse(localStorage.getItem(KEY)||'[]');"
        "return Array.isArray(x)?x:[]}catch(e){return []}}\n"
        "  function saveRows(rows){localStorage.setItem(KEY,JSON.stringify(rows))}"
    )
    new_loader = (
        "  function readRowsFrom(k){try{const x=JSON.parse(localStorage.getItem(k)||'[]');"
        "return Array.isArray(x)?x:[]}catch(e){return []}}\n"
        "  function normalizeRows(list,source){return (Array.isArray(list)?list:[]).filter(x=>x&&typeof x==='object').map((x,i)=>x.id?x:{...x,id:`legacy-${source}-${i}-${x.created_at||''}-${x.entry_date||''}-${x.exit_date||''}`})}\n"
        "  function mergeRows(groups){const m=new Map();groups.flat().forEach(r=>{if(r&&r.id)m.set(String(r.id),{...(m.get(String(r.id))||{}),...r})});return [...m.values()]}\n"
        "  function loadRows(){const current=normalizeRows(readRowsFrom(KEY),KEY),legacy=LEGACY_KEYS.flatMap(k=>normalizeRows(readRowsFrom(k),k));if(!legacy.length)return current;const merged=mergeRows([legacy,current]);if(merged.length!==current.length)localStorage.setItem(KEY,JSON.stringify(merged));return merged}\n"
        "  function saveRows(rows){localStorage.setItem(KEY,JSON.stringify(rows))}"
    )
    if old_loader in history:
        history = history.replace(old_loader, new_loader, 1)
    elif "function loadRows(){const current=normalizeRows" not in history:
        raise RuntimeError("No se pudo incorporar la migracion local de operaciones.")
    return history


def ensure_cloud_migration(cloud: str, keys: list[str]) -> str:
    legacy_line = f"  const LEGACY_KEYS={js_array(keys)};"
    cloud = re.sub(r"  const LEGACY_KEYS=\[[^\]]*\];", legacy_line, cloud)
    if legacy_line not in cloud:
        cloud = cloud.replace(
            "  const URL_KEY=",
            legacy_line + "\n  const URL_KEY=",
            1,
        )

    old_rows = (
        "  const read=(k,fb)=>{try{const x=JSON.parse(localStorage.getItem(k)||'');return x??fb}catch(e){return fb}};\n"
        "  const rows=()=>read(TRADE_KEY,[]);"
    )
    new_rows = (
        "  const read=(k,fb)=>{try{const x=JSON.parse(localStorage.getItem(k)||'');return x??fb}catch(e){return fb}};\n"
        "  function normalizeRows(list,source){return (Array.isArray(list)?list:[]).filter(x=>x&&typeof x==='object').map((x,i)=>x.id?x:{...x,id:`legacy-${source}-${i}-${x.created_at||''}-${x.entry_date||''}-${x.exit_date||''}`})}\n"
        "  function mergeRows(groups){const m=new Map();groups.flat().forEach(r=>{if(r&&r.id)m.set(String(r.id),{...(m.get(String(r.id))||{}),...r})});return [...m.values()]}\n"
        "  function migrateRows(){const current=normalizeRows(read(TRADE_KEY,[]),TRADE_KEY),legacy=LEGACY_KEYS.flatMap(k=>normalizeRows(read(k,[]),k));if(!legacy.length)return current;const merged=mergeRows([legacy,current]);if(merged.length!==current.length)localStorage.setItem(TRADE_KEY,JSON.stringify(merged));return merged}\n"
        "  const rows=()=>migrateRows();"
    )
    if old_rows in cloud:
        cloud = cloud.replace(old_rows, new_rows, 1)
    elif "const rows=()=>migrateRows();" not in cloud:
        raise RuntimeError("No se pudo incorporar la migracion Drive de operaciones.")
    return cloud


def patch(target: str) -> None:
    cfg = CONFIG[target]
    path: Path = cfg["html"]
    html = path.read_text(encoding="utf-8")

    history_start = html.find('<script id="tradeHistoryScript">')
    cloud_start = html.find('<script id="tradeCloudScript">')
    if history_start < 0 or cloud_start < 0:
        raise RuntimeError(f"{target}: no se encontraron los bloques de operaciones y Drive.")

    history_end = html.find("</script>", history_start)
    cloud_end = html.find("</script>", cloud_start)
    if history_end < 0 or cloud_end < 0:
        raise RuntimeError(f"{target}: bloque JavaScript incompleto.")

    history = html[history_start:history_end]
    cloud = html[cloud_start:cloud_end]

    history = replace_constant(history, "KEY", cfg["trade_key"])
    history = ensure_history_migration(history, cfg["legacy_keys"])
    cloud = replace_constant(cloud, "TRADE_KEY", cfg["trade_key"])
    cloud = ensure_cloud_migration(cloud, cfg["legacy_keys"])
    cloud = replace_constant(cloud, "URL_KEY", cfg["url_key"])
    cloud = replace_constant(cloud, "SNAP_KEY", cfg["snapshot_key"])

    if re.search(r"const FUND='[^']*';", cloud):
        cloud = re.sub(
            r"const FUND='[^']*';",
            f"const FUND='{cfg['fund']}';",
            cloud,
        )
    else:
        cloud = cloud.replace(
            "  'use strict';\n",
            "  'use strict';\n"
            f"  const FUND='{cfg['fund']}';\n"
            f"  const DRIVE_SHEET='{cfg['sheet']}';\n",
            1,
        )

    if re.search(r"const DRIVE_SHEET='[^']*';", cloud):
        cloud = re.sub(
            r"const DRIVE_SHEET='[^']*';",
            f"const DRIVE_SHEET='{cfg['sheet']}';",
            cloud,
        )
    else:
        fund_line = f"  const FUND='{cfg['fund']}';\n"
        cloud = cloud.replace(
            fund_line,
            fund_line + f"  const DRIVE_SHEET='{cfg['sheet']}';\n",
            1,
        )

    old_params = (
        "u.searchParams.set('action',action);"
        "u.searchParams.set('key',c.key);"
        "u.searchParams.set('callback',cb);"
        "u.searchParams.set('_',Date.now());"
    )
    new_params = (
        "u.searchParams.set('action',action);"
        "u.searchParams.set('fund',FUND);"
        "u.searchParams.set('key',c.key);"
        "u.searchParams.set('callback',cb);"
        "u.searchParams.set('_',Date.now());"
    )
    if old_params in cloud:
        cloud = cloud.replace(old_params, new_params, 1)
    elif new_params not in cloud:
        raise RuntimeError(f"{target}: no se pudo incorporar el parámetro fund.")

    marker = "// TRADE_CLOUD_FUND_ROUTING_V2"
    if marker not in cloud:
        needle = "    try{\n      const current=rows(),old=snapshot();"
        replacement = (
            "    try{\n"
            f"      {marker}\n"
            "      const probe=await jsonp('ping');\n"
            "      if(probe.routing!==true||String(probe.fund||'').toUpperCase()!==FUND){\n"
            "        throw new Error(`El puente de Drive aún no está actualizado para la hoja ${DRIVE_SHEET}.`);\n"
            "      }\n"
            "      const current=rows(),old=snapshot();"
        )
        if needle not in cloud:
            raise RuntimeError(f"{target}: no se encontró el inicio de syncNow.")
        cloud = cloud.replace(needle, replacement, 1)

    cloud = cloud.replace(
        "Drive conectado · ${remote.length}",
        "Drive ${DRIVE_SHEET} conectado · ${remote.length}",
    )

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
        f"const LEGACY_KEYS={js_array(cfg['legacy_keys'])};",
        f"const SNAP_KEY='{cfg['snapshot_key']}';",
        "u.searchParams.set('fund',FUND);",
        marker,
    ]
    missing = [item for item in required if item not in html]
    if missing:
        raise AssertionError(f"{target}: faltan controles de separación: {missing}")

    path.write_text(html, encoding="utf-8")
    print(
        f"{target}: operaciones aisladas en almacenamiento local y hoja Drive "
        f"{cfg['sheet']} ({cfg['fund']})."
    )


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1].lower() not in CONFIG:
        allowed = " | ".join(CONFIG)
        raise SystemExit(f"Uso: python {Path(__file__).name} [{allowed}]")
    patch(sys.argv[1].lower())


if __name__ == "__main__":
    main()
