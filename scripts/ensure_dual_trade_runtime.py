from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "public" / "index.html"
RUNTIME = ROOT / "public" / "data" / "dual_trade_runtime_v1.js"
TAG = '<script src="data/dual_trade_runtime_v1.js?rev=DUALTRADEV2"></script>'

OLD_METRICS = "function rowMetrics(r){const re=finite(r.entry_est_vc)&&finite(r.exit_est_vc)&&Number(r.entry_est_vc)!==0?Number(r.exit_est_vc)/Number(r.entry_est_vc)-1:null;const rr=finite(r.entry_sbs_vc)&&finite(r.exit_sbs_vc)&&Number(r.entry_sbs_vc)!==0?Number(r.exit_sbs_vc)/Number(r.entry_sbs_vc)-1:null;const cap=finite(r.capital)?Number(r.capital):null;return{re,rr,ge:re!==null&&cap!==null?cap*re:null,gr:rr!==null&&cap!==null?cap*rr:null};}"
NEW_METRICS = "function rowMetrics(r){const entryBase=finite(r.entry_sbs_vc)?Number(r.entry_sbs_vc):(finite(r.entry_est_vc)?Number(r.entry_est_vc):null);const re=entryBase!==null&&entryBase!==0&&finite(r.exit_est_vc)?Number(r.exit_est_vc)/entryBase-1:null;const rr=finite(r.entry_sbs_vc)&&finite(r.exit_sbs_vc)&&Number(r.entry_sbs_vc)!==0?Number(r.exit_sbs_vc)/Number(r.entry_sbs_vc)-1:null;const cap=finite(r.capital)?Number(r.capital):null;return{re,rr,ge:re!==null&&cap!==null?cap*re:null,gr:rr!==null&&cap!==null?cap*rr:null};}"


def main() -> None:
    html = HTML.read_text(encoding="utf-8")
    if "Dos modelos Rolling 30" not in html and "dualTakeover" not in html:
        raise RuntimeError("public/index.html no parece ser el visor dual Profuturo")

    # Elimina cualquier versión anterior para evitar dobles listeners/botones.
    html = re.sub(
        r'\n?<script\s+src="data/dual_trade_runtime_v1\.js\?rev=[^"]+"\s*></script>',
        "",
        html,
        flags=re.I,
    )
    if "</body>" not in html:
        raise RuntimeError("HTML sin cierre </body>")
    html = html.replace("</body>", TAG + "\n</body>", 1)
    HTML.write_text(html, encoding="utf-8")

    js = RUNTIME.read_text(encoding="utf-8")
    if OLD_METRICS in js:
        js = js.replace(OLD_METRICS, NEW_METRICS, 1)
        RUNTIME.write_text(js, encoding="utf-8")
    elif "const entryBase=finite(r.entry_sbs_vc)" not in js:
        raise RuntimeError("No se reconoció la fórmula de rentabilidad del runtime")

    check = HTML.read_text(encoding="utf-8")
    js_check = RUNTIME.read_text(encoding="utf-8")
    assert check.count("dual_trade_runtime_v1.js") == 1
    for token in ("Registrar operación", "Conectar Drive", "profuturo_fondo3_trade_history_v3", "fondo3_drive_sync_key_v1"):
        assert token in js_check, token
    assert "const entryBase=finite(r.entry_sbs_vc)" in js_check
    print("Runtime de operaciones + Drive fijado y validado en Profuturo dual")


if __name__ == "__main__":
    main()
