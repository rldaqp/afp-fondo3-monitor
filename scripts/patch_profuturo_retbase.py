from pathlib import Path

path = Path('public/index.html')
html = path.read_text(encoding='utf-8')
changed = False

# La variación diaria del modelo de niveles debe comparar la ecuación de hoy
# contra LA MISMA ecuación evaluada con los precios "Prev." del snapshot.
# No debe compararse contra un VC previo generado con otro corte de precios.
helper = "function liveLevelBase(){const c=BASE?.models?.niveles?.coefficients||{},ts=LIVE?.tickers||[];if(!ts.length||!finite(c.intercept))return null;let out=Number(c.intercept);for(const t of ts){const k=String(t.ticker||''),p=t.price_previous,b=c[k];if(!finite(p)||!finite(b))return null;out+=Number(b)*Number(p)}return out}"

old_level_returns = "function levelReturns(rows){return rows.map(r=>{if(r.live){const p=(BASE?.rows||[]).at(-1);return p&&finite(p.vc_niveles)&&finite(r.vc_niveles)?Number(r.vc_niveles)/Number(p.vc_niveles)-1:null}"
new_level_returns = helper + "function levelReturns(rows){return rows.map(r=>{if(r.live){const p=liveLevelBase();return finite(p)&&finite(r.vc_niveles)&&Number(p)!==0?Number(r.vc_niveles)/Number(p)-1:null}"
if helper not in html:
    if old_level_returns not in html:
        raise RuntimeError('No se encontró levelReturns esperado; no se aplica un cambio inseguro.')
    html = html.replace(old_level_returns, new_level_returns, 1)
    changed = True

# Para el gráfico de VC, mientras el snapshot de hoy está activo, el punto previo
# del modelo de niveles se muestra con la base comparable calculada desde "Prev.".
old_augment = "function augmentLive(rows,n){if(LIVE?.signal_date&&LIVE?.models?.niveles&&LIVE?.models?.retornos){const liveDate=String(LIVE.signal_date),existing=rows.find(z=>String(z.fecha)===liveDate),point={fecha:LIVE.signal_date,vc_sbs:existing&&finite(existing.vc_sbs)?Number(existing.vc_sbs):null,vc_niveles:Number(LIVE.models.niveles.vc_intraday),vc_retornos:Number(LIVE.models.retornos.vc_intraday),ret_vc_estimado:Number(LIVE.models.retornos.return_intraday),live:true};rows=rows.filter(z=>String(z.fecha)!==liveDate).concat([point]).sort((a,b)=>String(a.fecha).localeCompare(String(b.fecha)));if(n!=='2026'&&rows.length>Number(n))rows=rows.slice(-Number(n))}return rows}"
new_augment = "function augmentLive(rows,n){if(LIVE?.signal_date&&LIVE?.models?.niveles&&LIVE?.models?.retornos){const liveDate=String(LIVE.signal_date),existing=rows.find(z=>String(z.fecha)===liveDate),point={fecha:LIVE.signal_date,vc_sbs:existing&&finite(existing.vc_sbs)?Number(existing.vc_sbs):null,vc_niveles:Number(LIVE.models.niveles.vc_intraday),vc_retornos:Number(LIVE.models.retornos.vc_intraday),ret_vc_estimado:Number(LIVE.models.retornos.return_intraday),live:true};rows=rows.filter(z=>String(z.fecha)!==liveDate);const lb=liveLevelBase(),prior=[...rows].reverse().find(z=>String(z.fecha)<liveDate);if(prior&&finite(lb)&&!finite(prior.vc_sbs))prior.vc_niveles=Number(lb);rows=rows.concat([point]).sort((a,b)=>String(a.fecha).localeCompare(String(b.fecha)));if(n!=='2026'&&rows.length>Number(n))rows=rows.slice(-Number(n))}return rows}"
if new_augment not in html:
    if old_augment not in html:
        raise RuntimeError('No se encontró augmentLive esperado; no se aplica un cambio inseguro.')
    html = html.replace(old_augment, new_augment, 1)
    changed = True

# Alinea la tarjeta de niveles y mantiene la base correcta del modelo de retornos.
old_fragment = "lastRet=[...rows].reverse().find(z=>finite(z.vc_retornos)),retBase=finite(LIVE?.models?.retornos?.base_vc)?Number(LIVE.models.retornos.base_vc):finite(L.vc_retornos)?Number(L.vc_retornos):lastRet?Number(lastRet.vc_retornos):null,lv=finite(liveLv)?Number(liveLv):finite(L.vc_niveles)?Number(L.vc_niveles):null"
new_fragment = "lastRet=[...rows].reverse().find(z=>finite(z.vc_retornos)),levelBase=liveLevelBase(),retBase=finite(LIVE?.models?.retornos?.base_vc)?Number(LIVE.models.retornos.base_vc):finite(L.vc_retornos)?Number(L.vc_retornos):lastRet?Number(lastRet.vc_retornos):null,lv=finite(liveLv)?Number(liveLv):finite(L.vc_niveles)?Number(L.vc_niveles):null"
if new_fragment not in html:
    if old_fragment not in html:
        raise RuntimeError('No se encontró la base de renderLive esperada.')
    html = html.replace(old_fragment, new_fragment, 1)
    changed = True

old_lr = "lr=finite(liveLv)&&finite(L.vc_niveles)&&Number(L.vc_niveles)!==0?Number(liveLv)/Number(L.vc_niveles)-1:"
new_lr = "lr=finite(liveLv)&&finite(levelBase)&&Number(levelBase)!==0?Number(liveLv)/Number(levelBase)-1:"
if new_lr not in html:
    if old_lr not in html:
        raise RuntimeError('No se encontró el cálculo lr esperado.')
    html = html.replace(old_lr, new_lr, 1)
    changed = True

old_close = "$('levClose').textContent=vc(L.vc_niveles);$('retClose').textContent=vc(retBase);"
new_close = "$('levClose').textContent=vc(finite(levelBase)?levelBase:L.vc_niveles);$('retClose').textContent=vc(retBase);"
if new_close not in html:
    if old_close not in html:
        raise RuntimeError('No se encontró la salida de cierres esperada.')
    html = html.replace(old_close, new_close, 1)
    changed = True

if changed:
    path.write_text(html, encoding='utf-8')
    print('Profuturo: niveles y retornos alineados con sus bases comparables.')
else:
    print('Profuturo: alineación diaria ya aplicada.')
