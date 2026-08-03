from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML_PATH = ROOT / "public" / "index.html"
html = HTML_PATH.read_text(encoding="utf-8")

live_guard = r'''
  function liveSnapshotActive(){
    if(!liveData||!liveData.market_open||!String(liveData.mode||'').startsWith('INTRADÍA')||!Number.isFinite(Number(liveData.vc_estimated)))return false;
    const generated=new Date(liveData.generated_at_lima);
    const ageMinutes=(Date.now()-generated.getTime())/60000;
    if(!Number.isFinite(ageMinutes)||ageMinutes < -2||ageMinutes > 15)return false;
    try{
      const parts=Object.fromEntries(new Intl.DateTimeFormat('en-US',{timeZone:'America/New_York',weekday:'short',hour:'2-digit',minute:'2-digit',hour12:false}).formatToParts(new Date()).filter(x=>x.type!=='literal').map(x=>[x.type,x.value]));
      const minute=Number(parts.hour)*60+Number(parts.minute);
      return !['Sat','Sun'].includes(parts.weekday)&&minute>=570&&minute<970;
    }catch(e){return false}
  }
'''

if "function liveSnapshotActive()" not in html:
    html = html.replace("  function renderVC(){", live_guard + "\n  function renderVC(){", 1)

html = html.replace(
    "    let off=cutoff(allSeries.filter(x=>x.fuente==='SBS OFICIAL'),vcDays),est=cutoff(richSignals.filter(x=>x.vc_estimado!=null),vcDays);",
    "    let off=cutoff(allSeries.filter(x=>x.fuente==='SBS OFICIAL'),vcDays),estSource=richSignals.filter(x=>x.vc_estimado!=null);\n"
    "    if(liveSnapshotActive()){const point={fecha:liveData.signal_date,vc_estimado:Number(liveData.vc_estimated),ret_estimado:Number(liveData.return_estimated),senal:liveData.signal,tipo:'INTRADIA'};estSource=estSource.filter(x=>x.fecha!==point.fecha).concat([point]).sort((a,b)=>a.fecha.localeCompare(b.fecha))}\n"
    "    let est=cutoff(estSource,vcDays);",
    1,
)

html = html.replace(
    "    const p=cutoff(richSignals.filter(x=>x.ret_estimado!=null),retDays);",
    "    let signalSource=richSignals.filter(x=>x.ret_estimado!=null);\n"
    "    if(liveSnapshotActive()){const point={fecha:liveData.signal_date,vc_estimado:Number(liveData.vc_estimated),ret_estimado:Number(liveData.return_estimated),senal:liveData.signal,tipo:'INTRADIA'};signalSource=signalSource.filter(x=>x.fecha!==point.fecha).concat([point]).sort((a,b)=>a.fecha.localeCompare(b.fecha))}\n"
    "    const p=cutoff(signalSource,retDays);",
    1,
)

html = html.replace(
    "const live=liveData&&liveData.market_open&&String(liveData.mode).startsWith('INTRADÍA')&&Number.isFinite(Number(liveData.vc_estimated))",
    "const live=liveSnapshotActive()",
)
html = html.replace(
    "if(mode==='inside'&&liveData&&liveData.market_open&&String(liveData.mode).startsWith('INTRADÍA')&&Number.isFinite(Number(liveData.vc_estimated)))",
    "if(mode==='inside'&&liveSnapshotActive())",
)

html = html.replace(
    "  function renderMarket(){\n    if(!liveData)return;\n",
    "  function renderMarket(){\n    if(!liveData)return;\n"
    "    if(!liveSnapshotActive()){\n"
    "      const vc=latestData?Number(latestData.latest_estimated_vc):NaN,r=latestData?Number(latestData.latest_return_estimated):NaN,s=latestData?latestData.signal:'—';\n"
    "      $('marketMode').textContent='CIERRE DIARIO';$('marketMode').className='market-mode zero';\n"
    "      $('marketTime').innerHTML=`Cierre OLS: ${fmt(latestData&&latestData.latest_estimate_date)}<br>Actualizado: ${clock(latestData&&latestData.generated_at_lima,'America/Lima')} Lima`;\n"
    "      $('marketGrid').innerHTML=Number.isFinite(vc)?`<div class=\"market-item\"><div class=\"market-symbol\">VC estimado cierre</div><div class=\"market-price\">${vc.toFixed(7)}</div><div class=\"market-ret ${cls(r)}\">${r>=0?'+':''}${(r*100).toFixed(3)}%</div><div class=\"market-source\">Mismo valor del gráfico · Señal ${s}</div></div>`:'<div class=\"note\">Cierre todavía no disponible.</div>';\n"
    "      renderTop();return;\n"
    "    }\n",
    1,
)

for name in ("latest.json", "series.json", "signals.json", "operation_series.json", "model_insights.json"):
    html = html.replace(
        f"fetch('data/{name}',{{cache:'no-store'}})",
        f"fetch('data/{name}?ts='+Date.now(),{{cache:'no-store'}})",
    )

HTML_PATH.write_text(html, encoding="utf-8")
print("Visor: intradía vigente, cierre consistente y JSON sin caché.")
