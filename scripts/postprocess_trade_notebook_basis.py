from pathlib import Path
import re

from postprocess_trade_cloud_fund_routing import patch as route_trade_cloud

ROOT = Path(__file__).resolve().parents[1]
HTML_PATH = ROOT / "public" / "index.html"
DRIVE_WEB_APP_URL = "https://script.google.com/macros/s/AKfycbxoYHkCu0cZPx_KsMlI0Jd5PEATgxBjZTR8oK8qs1cUjRHJbiK0t-bxkH5ACprgp81S7g/exec"
html = HTML_PATH.read_text(encoding="utf-8")

# Este paso también instala el handler robusto del botón OK · Guardar.
old = """  function metrics(r){\n    const re=finite(r.entry_est_vc)&&finite(r.exit_est_vc)&&Number(r.entry_est_vc)!==0?Number(r.exit_est_vc)/Number(r.entry_est_vc)-1:null;\n    const rr=finite(r.entry_sbs_vc)&&finite(r.exit_sbs_vc)&&Number(r.entry_sbs_vc)!==0?Number(r.exit_sbs_vc)/Number(r.entry_sbs_vc)-1:null;\n    const cap=finite(r.capital)?Number(r.capital):null;\n    const ge=re!==null&&cap!==null?cap*re:null;\n    const gr=rr!==null&&cap!==null?cap*rr:null;\n    return {re,rr,diff:re!==null&&rr!==null?rr-re:null,ge,gr};\n  }"""

new = """  function metrics(r){\n    // Rentabilidad de la OPERACION: las cuotas compradas se fijan con el VC real SBS de entrada.\n    // Mientras ese VC aún no exista, se usa provisionalmente el VC estimado de entrada.\n    // El VC estimado de salida queda congelado al guardar la operación.\n    const entryBase=finite(r.entry_sbs_vc)?Number(r.entry_sbs_vc):(finite(r.entry_est_vc)?Number(r.entry_est_vc):null);\n    const re=entryBase!==null&&finite(r.exit_est_vc)&&entryBase!==0?Number(r.exit_est_vc)/entryBase-1:null;\n    const rr=finite(r.entry_sbs_vc)&&finite(r.exit_sbs_vc)&&Number(r.entry_sbs_vc)!==0?Number(r.exit_sbs_vc)/Number(r.entry_sbs_vc)-1:null;\n    const cap=finite(r.capital)?Number(r.capital):null;\n    const ge=re!==null&&cap!==null?cap*re:null;\n    const gr=rr!==null&&cap!==null?cap*rr:null;\n    return {re,rr,diff:re!==null&&rr!==null?rr-re:null,ge,gr};\n  }"""

if old in html:
    html = html.replace(old, new, 1)
elif "const entryBase=finite(r.entry_sbs_vc)" not in html:
    raise RuntimeError("No se encontró la fórmula de rentabilidad del histórico")

HTML_PATH.write_text(html, encoding="utf-8")
route_trade_cloud("profuturo")
html = HTML_PATH.read_text(encoding="utf-8")
html, count = re.subn(
    r"const DEFAULT_URL='https://script\.google\.com/macros/s/[^']+/exec';",
    f"const DEFAULT_URL='{DRIVE_WEB_APP_URL}';",
    html,
    count=1,
)
if count != 1:
    raise RuntimeError("No se pudo actualizar la URL activa de Apps Script en Profuturo")
HTML_PATH.write_text(html, encoding="utf-8")
print("Histórico Profuturo: fórmula notebook, aislamiento Drive v3, botón Guardar robusto y URL web activa aplicados.")