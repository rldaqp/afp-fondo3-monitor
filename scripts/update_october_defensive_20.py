"""Actualiza las series experimentales al 20% tras cada cierre y revisión SBS."""
import json
import math
from pathlib import Path
base=json.loads(Path("public/data/fixed_models_2026.json").read_text())
p=Path("public/data/experimento_defensivo_octubre_2026.json")
exp=json.loads(p.read_text())
assert base["model_version"]==exp["fuente_version"]
rows=base["rows"]
old=[o for o in exp["observaciones"] if o["fecha"]<"2026-10-08"]
# Reconstruir siempre todas las ruedas desde el 08/10 con la base vigente.
prev_n=prev_r=None
for i,r in enumerate(rows):
    if not ("2026-10-08"<=r["fecha"]<"2026-11-01"): continue
    prior=rows[i-1]
    sbs=prior.get("vc_sbs")
    official=isinstance(sbs,(int,float)) and math.isfinite(sbs)
    an=float(sbs) if official else prev_n
    ar=float(sbs) if official else prev_r
    if an is None or ar is None: raise ValueError("Falta anclaje para "+r["fecha"])
    n=an+.8*(r["vc_niveles"]-prior["vc_niveles"])
    ret=ar*(1+.8*r["ret_vc_estimado"])
    actual=r.get("vc_sbs")
    old.append(dict(fecha=r["fecha"],vc_sbs=actual,vc_sbs_origen="monitor" if actual is not None else "pendiente",vc_sbs_anterior=sbs if official else None,anclaje_tipo="SBS oficial de rueda anterior" if official else "encadenado desde proyección 20% de rueda anterior",anclaje_niveles=an,anclaje_retornos=ar,vc_niveles_visor=r["vc_niveles"],vc_niveles_defensivo=n,vc_retornos_visor=r["vc_retornos"],vc_retornos_defensivo=ret,error_abs_niveles_defensivo=abs(n-actual) if actual is not None else None,error_abs_retornos_defensivo=abs(ret-actual) if actual is not None else None))
    prev_n,prev_r=n,ret
dates=[o["fecha"] for o in old]
assert dates==sorted(set(dates))
expected=[r["fecha"] for r in rows if "2026-10-08"<=r["fecha"]<"2026-11-01"]
assert [o["fecha"] for o in old if o["fecha"]>="2026-10-08"]==expected, "El comparativo 20% omite ruedas"
assert all(isinstance(o.get("vc_retornos_defensivo"),(int,float)) and math.isfinite(o["vc_retornos_defensivo"]) for o in old if o["fecha"]>="2026-10-08"), "Retornos 20% incompleto"
exp["observaciones"]=old
exp["fuente_generado"]=base["generated_at_lima"]
exp["formula_niveles"]="ancla_niveles + 0.8 * (niveles_hoy - niveles_ayer)"
exp["formula_retornos"]="ancla_retornos * (1 + 0.8 * retorno_estimado_hoy)"
p.write_text(json.dumps(exp,ensure_ascii=False,indent=2)+"\n")
print("Comparativo 20% hasta",dates[-1])
