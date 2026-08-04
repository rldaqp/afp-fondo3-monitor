"""Corrige únicamente la presentación del gráfico de AFP Hábitat Fondo 3.

- Mantiene en la primera línea todas las fechas de la serie temporal: VC SBS
  cuando existe y VC estimado cuando la SBS aún no publicó el dato.
- Mantiene además la línea OLS completa para comparar VC temporal vs estimado.
- Todos los tramos son líneas normales con marcadores pequeños; no hay líneas
  punteadas ni círculos grandes.

Este módulo solo modifica public/habitat/index.html.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML_PATH = ROOT / "public" / "habitat" / "index.html"

NEW_RENDER_VC = r'''  function renderVC(){
    // HABITAT_CHART_RESTORE_GAP_DATES_V3
    const timeline=cutoff(allSeries,vcDays).filter(x=>Number.isFinite(Number(x.vc)));
    let estSource=richSignals.filter(x=>x.vc_estimado!=null);
    if(liveSnapshotActive()){
      const point={fecha:liveData.signal_date,vc_estimado:Number(liveData.vc_estimated),ret_estimado:Number(liveData.return_estimated),senal:liveData.signal,tipo:'INTRADIA'};
      estSource=estSource.filter(x=>x.fecha!==point.fecha).concat([point]).sort((a,b)=>a.fecha.localeCompare(b.fecha));
    }
    const est=cutoff(estSource,vcDays);
    const q=modelInsights&&modelInsights.uncertainty?Number(modelInsights.uncertainty.relative_q80||0):0;
    let pendingStep=0,lower=[],upper=[];
    est.forEach(x=>{
      let scale=1;
      if(x.tipo==='PENDIENTE'){pendingStep+=1;scale=Math.sqrt(pendingStep)}
      const v=Number(x.vc_estimado);
      lower.push(v*(1-q*scale));
      upper.push(v*(1+q*scale));
    });

    const traces=[];
    if(q>0&&est.length){
      traces.push(
        {x:est.map(x=>x.fecha),y:lower,mode:'lines',line:{width:0},hoverinfo:'skip',showlegend:false},
        {x:est.map(x=>x.fecha),y:upper,mode:'lines',line:{width:0},fill:'tonexty',fillcolor:'rgba(96,165,250,.12)',name:'Banda histórica 80%',hoverinfo:'skip'}
      );
    }

    // Se conservan todas las fechas. Cuando falta el VC SBS, se usa el VC ya
    // estimado que existe en series.json, sin cambiar su fuente ni sus datos.
    traces.push({
      x:timeline.map(x=>x.fecha),
      y:timeline.map(x=>Number(x.vc)),
      mode:'lines+markers',
      connectgaps:false,
      name:'VC SBS real + fechas estimadas',
      line:{width:2},
      marker:{size:5},
      customdata:timeline.map(x=>x.fuente),
      hovertemplate:'<b>%{x}</b><br>VC: %{y:.7f}<br>Fuente: %{customdata}<extra></extra>'
    });

    // La línea completa del VC estimado OLS se mantiene durante todo el periodo,
    // incluidas las fechas del tramo 30/06–21/07.
    traces.push({
      x:est.map(x=>x.fecha),
      y:est.map(x=>Number(x.vc_estimado)),
      mode:'lines+markers',
      connectgaps:false,
      name:'VC estimado OLS',
      line:{width:2},
      marker:{size:5},
      customdata:est.map(x=>[x.senal,x.tipo]),
      hovertemplate:'<b>%{x}</b><br>VC estimado: %{y:.7f}<br>Señal: %{customdata[0]}<br>Estado: %{customdata[1]}<extra></extra>'
    });

    Plotly.react('vcChart',traces,{
      title:vcDays==='all'?'Todo el historial':`Últimos ${vcDays} días`,
      paper_bgcolor:'#0f1b2d',plot_bgcolor:'#0f1b2d',font:{color:'#fff',size:11},
      margin:{l:48,r:18,t:45,b:45},legend:{orientation:'h',font:{size:10}}
    },{responsive:true});
    active('.vc-controls',vcDays);
  }
'''


def main() -> None:
    if not HTML_PATH.exists():
        raise FileNotFoundError(f"No existe el visor de Hábitat: {HTML_PATH}")

    html = HTML_PATH.read_text(encoding="utf-8")
    pattern = re.compile(
        r"  function renderVC\(\)\{.*?\n  \}\n\n  function renderSignals\(\)\{",
        flags=re.DOTALL,
    )
    replacement = NEW_RENDER_VC + "\n  function renderSignals(){"
    updated, count = pattern.subn(replacement, html, count=1)
    if count != 1:
        raise RuntimeError("No se encontró una única función renderVC de Hábitat.")

    HTML_PATH.write_text(updated, encoding="utf-8")
    print("Hábitat: fechas 30/06–21/07 restauradas y ambas líneas completas.")


if __name__ == "__main__":
    main()
