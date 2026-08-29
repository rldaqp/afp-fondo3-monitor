from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

TARGETS = [
    {
        "name": "Profuturo",
        "html": ROOT / "public" / "index.html",
        "runtime": ROOT / "public" / "data" / "dual_trade_runtime_v1.js",
        "src": "data/dual_trade_runtime_v1.js?rev=DUALTRADEV3",
        "fund_token": "const FUND='PROFUTURO';",
        "trade_key": "profuturo_fondo3_trade_history_v3",
    },
    {
        "name": "Hábitat",
        "html": ROOT / "public" / "habitat" / "index.html",
        "runtime": ROOT / "public" / "habitat" / "data" / "dual_trade_runtime_v1.js",
        "src": "data/dual_trade_runtime_v1.js?rev=DUALTRADEV3",
        "fund_token": "const FUND='HABITAT';",
        "trade_key": "habitat_fondo3_trade_history_v3",
    },
]

OLD_METRICS = "function rowMetrics(r){const re=finite(r.entry_est_vc)&&finite(r.exit_est_vc)&&Number(r.entry_est_vc)!==0?Number(r.exit_est_vc)/Number(r.entry_est_vc)-1:null;const rr=finite(r.entry_sbs_vc)&&finite(r.exit_sbs_vc)&&Number(r.entry_sbs_vc)!==0?Number(r.exit_sbs_vc)/Number(r.entry_sbs_vc)-1:null;const cap=finite(r.capital)?Number(r.capital):null;return{re,rr,ge:re!==null&&cap!==null?cap*re:null,gr:rr!==null&&cap!==null?cap*rr:null};}"
NEW_METRICS = "function rowMetrics(r){const entryBase=finite(r.entry_sbs_vc)?Number(r.entry_sbs_vc):(finite(r.entry_est_vc)?Number(r.entry_est_vc):null);const re=entryBase!==null&&entryBase!==0&&finite(r.exit_est_vc)?Number(r.exit_est_vc)/entryBase-1:null;const rr=finite(r.entry_sbs_vc)&&finite(r.exit_sbs_vc)&&Number(r.entry_sbs_vc)!==0?Number(r.exit_sbs_vc)/Number(r.entry_sbs_vc)-1:null;const cap=finite(r.capital)?Number(r.capital):null;return{re,rr,ge:re!==null&&cap!==null?cap*re:null,gr:rr!==null&&cap!==null?cap*rr:null};}"


def ensure_target(target: dict[str, object]) -> None:
    name = str(target["name"])
    html_path = Path(target["html"])
    runtime_path = Path(target["runtime"])
    src = str(target["src"])

    html = html_path.read_text(encoding="utf-8")
    if "Rolling 30" not in html and "dualTakeover" not in html:
        raise RuntimeError(f"{html_path} no parece ser visor dual Rolling 30")

    # Quita cualquier referencia previa para evitar dos paneles/listeners.
    html = re.sub(
        r'\n?<script\s+src="data/dual_trade_runtime_v1\.js(?:\?rev=[^"]+)?"\s*></script>',
        "",
        html,
        flags=re.I,
    )
    if "</body>" not in html:
        raise RuntimeError(f"{name}: HTML sin cierre </body>")
    tag = f'<script src="{src}"></script>'
    html = html.replace("</body>", tag + "\n</body>", 1)
    html_path.write_text(html, encoding="utf-8")

    js = runtime_path.read_text(encoding="utf-8")
    if OLD_METRICS in js:
        js = js.replace(OLD_METRICS, NEW_METRICS, 1)
        runtime_path.write_text(js, encoding="utf-8")

    check = html_path.read_text(encoding="utf-8")
    js_check = runtime_path.read_text(encoding="utf-8")
    assert check.count("dual_trade_runtime_v1.js") == 1, name
    for token in (
        "Registrar operación",
        "Conectar Drive",
        str(target["fund_token"]),
        str(target["trade_key"]),
        "fondo3_drive_sync_key_v1",
    ):
        assert token in js_check, f"{name}: falta {token}"
    print(f"{name}: operaciones entrada/salida + Drive aseguradas")


def main() -> None:
    for target in TARGETS:
        ensure_target(target)
    print("Runtime de operaciones + Drive validado en Profuturo y Hábitat")


if __name__ == "__main__":
    main()
