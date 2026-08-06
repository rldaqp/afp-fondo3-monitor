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
        "url_key": "profuturo_fondo3_drive_sync_url_v2",
        "snapshot_key": "profuturo_fondo3_drive_sync_snapshot_v2",
    },
    "habitat": {
        "html": ROOT / "public" / "habitat" / "index.html",
        "fund": "HABITAT",
        "sheet": "Habitat",
        "trade_key": "habitat_fondo3_trade_history_v2",
        "url_key": "habitat_fondo3_drive_sync_url_v2",
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
    cloud = replace_constant(cloud, "TRADE_KEY", cfg["trade_key"])
    cloud = replace_constant(cloud, "URL_KEY", cfg["url_key"])
    cloud = replace_constant(cloud, "SNAP_KEY", cfg["snapshot_key"])

    if re.search(r"const FUND='[^']*';", cloud):
        cloud = re.sub(r"const FUND='[^']*';", f"const FUND='{cfg['fund']}';", cloud)
    else:
        cloud = cloud.replace(
            "  'use strict';\n",
            "  'use strict';\n"
            f"  const FUND='{cfg['fund']}';\n"
            f"  const DRIVE_SHEET='{cfg['sheet']}';\n",
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

    html = html[:history_start] + history + html[history_end:cloud_start] + cloud + html[cloud_end:]

    required = [
        f"const FUND='{cfg['fund']}';",
        f"const KEY='{cfg['trade_key']}';",
        f"const TRADE_KEY='{cfg['trade_key']}';",
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
