from __future__ import annotations

import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


LIVE_GUARD = r'''
  function liveSnapshotActive(){
    if(!liveData||!Number.isFinite(Number(liveData.vc_estimated)))return false;
    const mode=String(liveData.mode||'');
    if(!mode.startsWith('INTRAD')&&!mode.startsWith('CIERRE'))return false;
    const d=String(liveData.signal_date||'').slice(0,10);
    if(mode.startsWith('CIERRE')){const latest=String((latestData&&latestData.latest_estimate_date)||'').slice(0,10);return !latest||d>=latest}
    try{
      const parts=Object.fromEntries(new Intl.DateTimeFormat('en-US',{timeZone:'America/Lima',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date()).filter(x=>x.type!=='literal').map(x=>[x.type,x.value]));
      return d===`${parts.year}-${parts.month}-${parts.day}`;
    }catch(e){return d===new Date().toISOString().slice(0,10)}
  }
  function liveSnapshotLabel(){return String((liveData&&liveData.mode)||'').startsWith('INTRAD')?'INTRADÍA PROVISIONAL':'CIERRE DIARIO'}
'''


def ensure_cache_busting(html: str) -> str:
    for name in (
        "latest.json",
        "series.json",
        "signals.json",
        "operation_series.json",
        "model_insights.json",
    ):
        html = html.replace(
            f"fetch('data/{name}',{{cache:'no-store'}})",
            f"fetch('data/{name}?ts='+Date.now(),{{cache:'no-store'}})",
        )
    return html


def ensure_live_guard(html: str) -> str:
    if "function liveSnapshotActive()" not in html:
        html = html.replace("  function renderVC(){", LIVE_GUARD + "\n  function renderVC(){", 1)
    elif "function liveSnapshotLabel()" not in html:
        html = html.replace(
            "  function renderVC(){",
            "  function liveSnapshotLabel(){return String((liveData&&liveData.mode)||'').startsWith('INTRAD')?'INTRADÍA PROVISIONAL':'CIERRE DIARIO'}\n\n  function renderVC(){",
            1,
        )

    html = html.replace(
        "liveData.market_open&&String(liveData.mode).startsWith('INTRADÍA')&&Number.isFinite(Number(liveData.vc_estimated))",
        "liveSnapshotActive()",
    )
    html = html.replace(
        "liveData.market_open&&String(liveData.mode).startsWith('INTRADÃA')&&Number.isFinite(Number(liveData.vc_estimated))",
        "liveSnapshotActive()",
    )
    html = html.replace(
        "if(!liveData||!String(liveData.mode||'').startsWith('INTRAD')||!Number.isFinite(Number(liveData.vc_estimated)))return false;",
        "if(!liveData||!Number.isFinite(Number(liveData.vc_estimated)))return false;\n    const mode=String(liveData.mode||'');\n    if(!mode.startsWith('INTRAD')&&!mode.startsWith('CIERRE'))return false;",
    )
    html = html.replace(
        "    const d=String(liveData.signal_date||'').slice(0,10);\n    try{",
        "    const d=String(liveData.signal_date||'').slice(0,10);\n    if(mode.startsWith('CIERRE')){const latest=String((latestData&&latestData.latest_estimate_date)||'').slice(0,10);return !latest||d>=latest}\n    try{",
    )
    return html


def ensure_intraday_insights_consistency(html: str) -> str:
    """Usa el mismo snapshot vigente en señal, aportes y challenger Huber.

    Al terminar la sesión, el último corte intradía de hoy se conserva con
    market_open=false hasta que exista el cierre diario. La cabecera ya lo
    considera activo mediante liveSnapshotActive(); los insights deben hacer
    exactamente lo mismo para no retroceder al día anterior.
    """
    html = html.replace(
        "if(!(liveData&&liveData.market_open&&latestData&&latestData.coefficients))return null;",
        "if(!(liveData&&liveSnapshotActive()&&latestData&&latestData.coefficients))return null;",
    )
    html = html.replace(
        "if(liveData&&liveData.market_open&&h.coefficients){",
        "if(liveData&&liveSnapshotActive()&&h.coefficients){",
    )
    html = html.replace(
        "const hub=currentHuber(),olsSignal=liveData&&liveData.market_open?liveData.signal:",
        "const hub=currentHuber(),olsSignal=liveData&&liveSnapshotActive()?liveData.signal:",
    )
    return html


def ensure_intraday_series_points(html: str) -> str:
    html = html.replace(
        "    let off=cutoff(allSeries.filter(x=>x.fuente==='SBS OFICIAL'),vcDays),est=cutoff(richSignals.filter(x=>x.vc_estimado!=null),vcDays);",
        "    let off=cutoff(allSeries.filter(x=>x.fuente==='SBS OFICIAL'),vcDays),estSource=richSignals.filter(x=>x.vc_estimado!=null);\n"
        "    if(liveSnapshotActive()){const point={fecha:liveData.signal_date,vc_estimado:Number(liveData.vc_estimated),ret_estimado:Number(liveData.return_estimated),senal:liveData.signal,tipo:liveSnapshotLabel()};estSource=estSource.filter(x=>x.fecha!==point.fecha).concat([point]).sort((a,b)=>a.fecha.localeCompare(b.fecha))}\n"
        "    let est=cutoff(estSource,vcDays);",
        1,
    )
    html = html.replace(
        "    const p=cutoff(richSignals.filter(x=>x.ret_estimado!=null),retDays);",
        "    let signalSource=richSignals.filter(x=>x.ret_estimado!=null);\n"
        "    if(liveSnapshotActive()){const point={fecha:liveData.signal_date,vc_estimado:Number(liveData.vc_estimated),ret_estimado:Number(liveData.return_estimated),senal:liveData.signal,tipo:liveSnapshotLabel()};signalSource=signalSource.filter(x=>x.fecha!==point.fecha).concat([point]).sort((a,b)=>a.fecha.localeCompare(b.fecha))}\n"
        "    const p=cutoff(signalSource,retDays);",
        1,
    )
    html = html.replace(
        "if(mode==='inside'&&liveData&&liveData.market_open&&String(liveData.mode).startsWith('INTRADÍA')&&Number.isFinite(Number(liveData.vc_estimated)))",
        "if(mode==='inside'&&liveSnapshotActive())",
    )
    html = html.replace(
        "if(mode==='inside'&&liveData&&liveData.market_open&&String(liveData.mode).startsWith('INTRADÃA')&&Number.isFinite(Number(liveData.vc_estimated)))",
        "if(mode==='inside'&&liveSnapshotActive())",
    )
    return html


def ensure_market_fallback(html: str) -> str:
    old_closed_block = r'''    if(!liveSnapshotActive()){
      const vc=latestData?Number(latestData.latest_estimated_vc):NaN,r=latestData?Number(latestData.latest_return_estimated):NaN,s=latestData?latestData.signal:'â€”';
      $('marketMode').textContent='CIERRE DIARIO';$('marketMode').className='market-mode zero';
      $('marketTime').innerHTML=`Cierre OLS: ${fmt(latestData&&latestData.latest_estimate_date)}<br>Actualizado: ${clock(latestData&&latestData.generated_at_lima,'America/Lima')} Lima`;
      $('marketGrid').innerHTML=Number.isFinite(vc)?`<div class="market-item"><div class="market-symbol">VC estimado cierre</div><div class="market-price">${vc.toFixed(7)}</div><div class="market-ret ${cls(r)}">${r>=0?'+':''}${(r*100).toFixed(3)}%</div><div class="market-source">Mismo valor del grÃ¡fico Â· SeÃ±al ${s}</div></div>`:'<div class="note">Cierre todavÃ­a no disponible.</div>';
      renderTop();return;
    }
'''
    new_closed_block = r'''    if(!liveSnapshotActive()){
      // MARKET_INDICATORS_PRESERVED_V2
      const vc=latestData?Number(latestData.latest_estimated_vc):NaN,r=latestData?Number(latestData.latest_return_estimated):NaN,s=latestData?latestData.signal:'â€”';
      const assets=(liveData&&Array.isArray(liveData.assets))?liveData.assets:[];
      const stamps=assets.map(a=>a.timestamp).filter(Boolean).sort();
      const lastStamp=stamps.length?stamps.at(-1):null;
      $('marketMode').textContent=assets.length?'ULTIMO CORTE DE INDICADORES · CIERRE OLS VIGENTE':'CIERRE DIARIO';
      $('marketMode').className='market-mode zero';
      $('marketTime').innerHTML=`VC cierre OLS: ${fmt(latestData&&latestData.latest_estimate_date)}<br>${lastStamp?'Indicadores: '+(String(lastStamp).includes('T')?clock(lastStamp,'America/Lima')+' Lima':fmt(lastStamp)):'Indicadores sin corte disponible'}`;
      const cards=assets.map(a=>{const p=Number(a.precio_actual),rr=Number(a.retorno);return `<div class="market-item"><div class="market-symbol">${a.serie}</div><div class="market-price">${Number.isFinite(p)?p.toFixed(a.serie==='USD_PEN'?4:2):'—'}</div><div class="market-ret ${cls(rr)}">${Number.isFinite(rr)?(rr>=0?'+':'')+(rr*100).toFixed(2)+'%':'—'}</div><div class="market-source">${a.estado||'Ultimo dato disponible'} · corte informativo</div></div>`}).join('');
      const closeCard=Number.isFinite(vc)?`<div class="market-item"><div class="market-symbol">VC estimado cierre</div><div class="market-price">${vc.toFixed(7)}</div><div class="market-ret ${cls(r)}">${r>=0?'+':''}${(r*100).toFixed(3)}%</div><div class="market-source">Mismo valor del grafico · Señal ${s}</div></div>`:'<div class="note">Cierre todavia no disponible.</div>';
      $('marketGrid').innerHTML=(cards||'<div class="note">No hay indicadores guardados.</div>')+closeCard;
      renderTop();return;
    }
'''
    if old_closed_block in html:
        return html.replace(old_closed_block, new_closed_block, 1)
    if "MARKET_INDICATORS_PRESERVED_V2" not in html:
        return html.replace(
            "  function renderMarket(){\n    if(!liveData)return;\n",
            "  function renderMarket(){\n    if(!liveData)return;\n" + new_closed_block,
            1,
        )
    return html


def ensure_live_fetch_fallback(html: str, raw_live: str) -> str:
    raw_prof = (
        "https://raw.githubusercontent.com/rldaqp/afp-fondo3-monitor/"
        "migracion-github-actions/public/data/live_market.json"
    )
    raw_hab = (
        "https://raw.githubusercontent.com/rldaqp/afp-fondo3-monitor/"
        "migracion-github-actions/public/habitat/data/live_market.json"
    )
    html = html.replace(raw_prof, raw_live).replace(raw_hab, raw_live)

    html = html.replace(
        "fetch('data/live_market.json?ts='+Date.now()",
        f"fetch('{raw_live}?ts='+Date.now()",
    )
    html = html.replace("fetch('data/live_market.json'", f"fetch('{raw_live}'")

    if "function fetchLiveJson(primary,fallback)" not in html:
        html = html.replace(
            "  function loadLive(){",
            "  function fetchLiveJson(primary,fallback){return fetch(primary,{cache:'no-store'}).catch(()=>fetch(fallback,{cache:'no-store'})).then(r=>r.json())}\n"
            "  function loadLive(){",
            1,
        )

    raw_fetch = f"fetch('{raw_live}?ts='+Date.now(),{{cache:'no-store'}}).then(r=>r.json())"
    fallback_fetch = (
        "fetchLiveJson('data/live_market.json?ts='+Date.now(),"
        f"'{raw_live}?ts='+Date.now())"
    )
    html = html.replace(raw_fetch, fallback_fetch)
    html = html.replace(
        f"function loadLive(){{return fetch('{raw_live}?ts='+Date.now(),{{cache:'no-store'}}).then(r=>r.json()).then(x=>{{liveData=x;renderMarket();return x}}).catch(()=>null)}}",
        f"function loadLive(){{const ts=Date.now();return fetchLiveJson('data/live_market.json?ts='+ts,'{raw_live}?ts='+ts).then(x=>{{liveData=x;renderMarket();return x}}).catch(()=>null)}}",
    )
    html = html.replace(
        "function loadLive(){return fetchLiveJson('data/live_market.json?ts='+Date.now(),"
        f"'{raw_live}?ts='+Date.now()).then(x=>{{liveData=x;renderMarket();return x}}).catch(()=>null)}}",
        f"function loadLive(){{const ts=Date.now();return fetchLiveJson('data/live_market.json?ts='+ts,'{raw_live}?ts='+ts).then(x=>{{liveData=x;renderMarket();return x}}).catch(()=>null)}}",
    )
    return html


def process(path: Path, raw_live: str) -> None:
    html = path.read_text(encoding="utf-8")
    html = ensure_cache_busting(html)
    html = ensure_live_guard(html)
    html = ensure_intraday_insights_consistency(html)
    html = ensure_intraday_series_points(html)
    html = ensure_market_fallback(html)
    html = ensure_live_fetch_fallback(html, raw_live)
    path.write_text(html, encoding="utf-8")


def resolve_target() -> str:
    if len(sys.argv) > 1:
        arg = sys.argv[1].strip().lower()
        if arg in {"profuturo", "habitat", "both"}:
            return arg

    workflow = os.environ.get("GITHUB_WORKFLOW", "").strip().lower()
    if "hábitat" in workflow or "habitat" in workflow:
        return "habitat"
    if "rolling 90" in workflow or "profuturo" in workflow:
        return "profuturo"
    return "both"


target = resolve_target()

if target in {"profuturo", "both"}:
    process(
        ROOT / "public" / "index.html",
        "https://raw.githubusercontent.com/rldaqp/afp-fondo3-monitor/"
        "migracion-github-actions/public/data/live_market.json",
    )

if target in {"habitat", "both"}:
    habitat_path = ROOT / "public" / "habitat" / "index.html"
    if habitat_path.exists():
        process(
            habitat_path,
            "https://raw.githubusercontent.com/rldaqp/afp-fondo3-monitor/"
            "migracion-github-actions/public/habitat/data/live_market.json",
        )

print(f"Visor {target}: snapshot vigente visible con fallback local y raw.")
