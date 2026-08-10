from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MARKER = "// TRADE_HISTORY_FETCH_HELPER_V1"


def patch(path: Path) -> bool:
    html = path.read_text(encoding="utf-8")
    start = html.find('<script id="tradeHistoryScript">')
    end = html.find('<!-- TRADE_HISTORY_V1_END -->', start)
    if start < 0 or end < 0:
        raise RuntimeError(f"No se encontró el bloque tradeHistoryScript en {path}")

    block = html[start:end]
    if MARKER in block:
        return False

    if "fetchLiveJson(" not in block:
        raise RuntimeError(f"La bitácora no usa fetchLiveJson en {path}")
    if "  async function boot(){" not in block:
        raise RuntimeError(f"No se encontró boot() en la bitácora de {path}")

    helper = r'''
  // TRADE_HISTORY_FETCH_HELPER_V1
  function fetchLiveJson(primary,fallback){
    const load=url=>fetch(url,{cache:'no-store'}).then(r=>{
      if(!r.ok)throw new Error('HTTP '+r.status);
      return r.json();
    });
    return load(primary).catch(()=>load(fallback));
  }
'''

    block = block.replace("  async function boot(){", helper + "\n  async function boot(){", 1)
    html = html[:start] + block + html[end:]
    path.write_text(html, encoding="utf-8")
    return True


def main() -> None:
    targets = [
        ROOT / "public" / "index.html",
        ROOT / "public" / "habitat" / "index.html",
    ]
    changed = []
    for target in targets:
        if target.exists() and patch(target):
            changed.append(str(target.relative_to(ROOT)))
    print("Bitácora operativa corregida: " + (", ".join(changed) if changed else "sin cambios"))


if __name__ == "__main__":
    main()
