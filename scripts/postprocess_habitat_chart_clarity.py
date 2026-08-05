"""Corrige únicamente la presentación del gráfico de AFP Hábitat Fondo 3.

- Verde: VC reales publicados por la SBS.
- Ámbar sólido: VC provisional para fechas con SBS pendiente, enlazado con los
  puntos oficiales inmediatamente anterior y posterior.
- Rojo: VC estimado OLS continuo durante todo el periodo.
- No se usan líneas punteadas ni marcadores grandes.

Este módulo solo modifica public/habitat/index.html.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML_PATH = ROOT / "public" / "habitat" / "index.html"

NEW_RENDER_VC = r'''  function renderVC(){
    // HABITAT_CHART_REAL_PROVISIONAL_OLS_V5
    const timeline=cutoff(allSeries,vcDays);
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
      if(x.tipo==='PENDIENTE'||x.tipo==='SBS_PENDIENTE'){pendingStep+=1;scale=Math.sqrt(pendingStep)}
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

    // Verde: únicamente valores efectivamente publicados por la SBS.
    traces.push({
      x:timeline.map(x=>x.fecha),
      y:timeline.map(x=>x.es_oficial===true?Number(x.vc):null),
      mode:'lines+markers',
      connectgaps:false,
      name:'VC SBS real (oficial)',
      line:{width:2,color:'#22c55e'},
      marker:{size:5,color:'#22c55e'},
      hovertemplate:'<b>%{x}</b><br>VC SBS oficial: %{y:.7f}<extra></extra>'
    });

    // Ámbar: muestra el VC provisional ya calculado para las fechas en que la
    // SBS aún no publicó. Los dos puntos de borde mantienen continuidad visual.
    const provisionalY=timeline.map((x,i)=>{
      const pending=x.es_oficial!==true;
      const previousPending=i>0&&timeline[i-1].es_oficial!==true;
      const nextPending=i<timeline.length-1&&timeline[i+1].es_oficial!==true;
      return pending||previousPending||nextPending?Number(x.vc):null;
    });
    traces.push({
      x:timeline.map(x=>x.fecha),
      y:provisionalY,
      mode:'lines+markers',
      connectgaps:false,
      name:'VC provisional · SBS pendiente',
      line:{width:2,color:'#f59e0b'},
      marker:{size:5,color:'#f59e0b'},
      customdata:timeline.map(x=>x.es_oficial===true?'Punto oficial de enlace':'Estimación provisional; SBS pendiente'),
      hovertemplate:'<b>%{x}</b><br>VC provisional: %{y:.7f}<br>%{customdata}<extra></extra>'
    });

    // Rojo: estimación OLS completa para comparar en todas las fechas.
    traces.push({
      x:est.map(x=>x.fecha),
      y:est.map(x=>Number(x.vc_estimado)),
      mode:'lines+markers',
      connectgaps:false,
      name:'VC estimado OLS',
      line:{width:2,color:'#ef4444'},
      marker:{size:5,color:'#ef4444'},
      customdata:est.map(x=>[x.senal,x.tipo,x.tipo==='SBS_PENDIENTE'?'SBS pendiente':'Fecha con VC oficial disponible']),
      hovertemplate:'<b>%{x}</b><br>VC estimado OLS: %{y:.7f}<br>Señal: %{customdata[0]}<br>%{customdata[2]}<extra></extra>'
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
    print("Hábitat: VC oficial, provisional y OLS separados con continuidad.")


if __name__ == "__main__":
    main()
