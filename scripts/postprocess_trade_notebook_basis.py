from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML_PATH = ROOT / "public" / "index.html"
html = HTML_PATH.read_text(encoding="utf-8")

old = """  function metrics(r){\n    const re=finite(r.entry_est_vc)&&finite(r.exit_est_vc)&&Number(r.entry_est_vc)!==0?Number(r.exit_est_vc)/Number(r.entry_est_vc)-1:null;\n    const rr=finite(r.entry_sbs_vc)&&finite(r.exit_sbs_vc)&&Number(r.entry_sbs_vc)!==0?Number(r.exit_sbs_vc)/Number(r.entry_sbs_vc)-1:null;\n    const cap=finite(r.capital)?Number(r.capital):null;\n    const ge=re!==null&&cap!==null?cap*re:null;\n    const gr=rr!==null&&cap!==null?cap*rr:null;\n    return {re,rr,diff:re!==null&&rr!==null?rr-re:null,ge,gr};\n  }"""

new = """  function metrics(r){\n    // Rentabilidad de la OPERACION: las cuotas compradas se fijan con el VC real SBS de entrada.\n    // Mientras ese VC aún no exista, se usa provisionalmente el VC estimado de entrada.\n    // El VC estimado de salida queda congelado al guardar la operación.\n    const entryBase=finite(r.entry_sbs_vc)?Number(r.entry_sbs_vc):(finite(r.entry_est_vc)?Number(r.entry_est_vc):null);\n    const re=entryBase!==null&&finite(r.exit_est_vc)&&entryBase!==0?Number(r.exit_est_vc)/entryBase-1:null;\n    const rr=finite(r.entry_sbs_vc)&&finite(r.exit_sbs_vc)&&Number(r.entry_sbs_vc)!==0?Number(r.exit_sbs_vc)/Number(r.entry_sbs_vc)-1:null;\n    const cap=finite(r.capital)?Number(r.capital):null;\n    const ge=re!==null&&cap!==null?cap*re:null;\n    const gr=rr!==null&&cap!==null?cap*rr:null;\n    return {re,rr,diff:re!==null&&rr!==null?rr-re:null,ge,gr};\n  }"""

if old not in html:
    raise RuntimeError("No se encontró la fórmula anterior de rentabilidad del histórico")

html = html.replace(old, new, 1)
HTML_PATH.write_text(html, encoding="utf-8")
print("Histórico: P/L y retorno estimado calculados con VC SBS real de entrada, igual que la operación del notebook.")
