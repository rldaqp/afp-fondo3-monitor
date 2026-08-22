(function(){
  'use strict';
  const $=id=>document.getElementById(id);
  const finite=x=>x!==null&&x!==undefined&&x!==''&&Number.isFinite(Number(x));
  const ranges={qqqVc:30,qqqRet:30,new_tickersVc:30,new_tickersRet:30};
  const labels={qqq:'Modelo A · Rolling 30 + QQQ',new_tickers:'Modelo B · Rolling 30 + nuevos tickers'};
  let data=null;

  async function load(){
    const r=await fetch('data/dual_rolling30_monitor.json?v2='+Date.now(),{cache:'no-store'});
    if(!r.ok)throw new Error('HTTP '+r.status);
    return r.json();
  }

  function rowsFor(key){
    const m=data?.models?.[key];
    if(!m)return [];
    const map=new Map();
    (m.history_one_step||[]).forEach(r=>{
      if(r&&r.fecha&&finite(r.vc_estimated))map.set(r.fecha,{...r,_kind:r.validation||'histórico',_horizon:r.horizon_sessions?String(r.horizon_sessions)+' sesiones':'histórico'});
    });
    (m.history_operational||[]).forEach(r=>{
      if(!r||!r.fecha||!finite(r.vc_estimated))return;
      map.set(r.fecha,{
        fecha:r.fecha,base_vc:r.base_vc,vc_estimated:r.vc_estimated,actual_vc:r.actual_vc,
        return_estimated:r.return_estimated,actual_return:r.actual_return_daily,signal:r.signal,error_pct:r.error_pct,
        _kind:r.frozen?'operacional guardado':'intradía provisional',_horizon:'1 sesión'
      });
    });
    (m.forward_chain||[]).forEach(r=>{
      if(!r||!r.fecha||!finite(r.vc_estimated))return;
      const old=map.get(r.fecha)||{};
      if(/operacional guardado/i.test(String(old._kind||''))&&old.actual_vc!=null)return;
      map.set(r.fecha,{...old,...r,actual_vc:old.actual_vc??r.actual_vc,actual_return:old.actual_return,_kind:old._kind||'seguimiento provisional',_horizon:old._horizon||'1 sesión'});
    });
    return [...map.values()].sort((a,b)=>String(a.fecha).localeCompare(String(b.fecha)));
  }

  function inRange(rows,days){
    if(days==='all'||!rows.length)return rows;
    const last=new Date(String(rows.at(-1).fecha).slice(0,10)+'T00:00:00');
    const first=new Date(last);first.setDate(first.getDate()-Number(days));
    return rows.filter(r=>new Date(String(r.fecha).slice(0,10)+'T00:00:00')>=first);
  }

  function signalColor(s){return s==='SUBE'?'#4ade80':s==='BAJA'?'#f87171':'#fbbf24'}
  function symbol(r){return /provisional|intradía/i.test(String(r._kind||''))?'circle-open':(/operacional guardado/i.test(String(r._kind||''))?'square':'circle')}

  function plotVc(key){
    if(!window.Plotly)return;
    const el=$('dualVcChart_'+key);if(!el)return;
    const rows=inRange(rowsFor(key),ranges[key+'Vc']);
    Plotly.react(el,[
      {x:rows.map(r=>r.fecha),y:rows.map(r=>finite(r.vc_estimated)?Number(r.vc_estimated):null),type:'scatter',mode:'lines+markers',name:'VC estimado rolling 30',line:{width:2,color:'#38bdf8'},marker:{size:7,color:'#38bdf8',symbol:rows.map(symbol)},customdata:rows.map(r=>[r._kind||'',r._horizon||'',r.signal||'—']),hovertemplate:'<b>%{x}</b><br>Estimado %{y:.7f}<br>%{customdata[0]} · %{customdata[1]} · %{customdata[2]}<extra></extra>'},
      {x:rows.map(r=>r.fecha),y:rows.map(r=>finite(r.actual_vc)?Number(r.actual_vc):null),type:'scatter',mode:'lines+markers',name:'VC real SBS',line:{width:2,color:'#fb923c'},marker:{size:6,color:'#fb923c',symbol:'diamond'},hovertemplate:'<b>%{x}</b><br>SBS %{y:.7f}<extra></extra>'}
    ],{margin:{l:48,r:14,t:12,b:42},paper_bgcolor:'rgba(0,0,0,0)',plot_bgcolor:'rgba(0,0,0,0)',font:{color:'#cbd5e1',size:10},xaxis:{gridcolor:'#243244'},yaxis:{gridcolor:'#243244',title:'Valor cuota'},legend:{orientation:'h',y:1.13}},{responsive:true,displayModeBar:false});
  }

  function stems(rows,field){
    const x=[],y=[];
    rows.forEach(r=>{if(!finite(r[field]))return;x.push(r.fecha,r.fecha,null);y.push(0,Number(r[field])*100,null)});
    return{x,y};
  }

  function plotRet(key){
    if(!window.Plotly)return;
    const el=$('dualRetChart_'+key);if(!el)return;
    const rows=inRange(rowsFor(key),ranges[key+'Ret']);
    const se=stems(rows,'return_estimated'),sr=stems(rows,'actual_return');
    Plotly.react(el,[
      {x:se.x,y:se.y,type:'scatter',mode:'lines',line:{width:1,color:'#64748b'},hoverinfo:'skip',showlegend:false,connectgaps:false},
      {x:sr.x,y:sr.y,type:'scatter',mode:'lines',line:{width:1,color:'#7c2d12'},hoverinfo:'skip',showlegend:false,connectgaps:false},
      {x:rows.map(r=>r.fecha),y:rows.map(r=>finite(r.return_estimated)?Number(r.return_estimated)*100:null),type:'scatter',mode:'markers',name:'Retorno estimado',marker:{size:8,color:rows.map(r=>signalColor(r.signal)),symbol:rows.map(symbol),line:{width:1,color:'#0f172a'}},customdata:rows.map(r=>[r._kind||'',r._horizon||'',r.signal||'—']),hovertemplate:'<b>%{x}</b><br>Estimado %{y:+.3f}%<br>%{customdata[0]} · %{customdata[1]} · %{customdata[2]}<extra></extra>'},
      {x:rows.map(r=>r.fecha),y:rows.map(r=>finite(r.actual_return)?Number(r.actual_return)*100:null),type:'scatter',mode:'markers',name:'Retorno real SBS',marker:{size:7,color:'#fb923c',symbol:'diamond'},hovertemplate:'<b>%{x}</b><br>SBS %{y:+.3f}%<extra></extra>'}
    ],{margin:{l:48,r:14,t:12,b:42},paper_bgcolor:'rgba(0,0,0,0)',plot_bgcolor:'rgba(0,0,0,0)',font:{color:'#cbd5e1',size:10},xaxis:{gridcolor:'#243244'},yaxis:{gridcolor:'#243244',title:'Retorno %',zeroline:true,zerolinecolor:'#94a3b8'},legend:{orientation:'h',y:1.13},shapes:[{type:'line',xref:'paper',x0:0,x1:1,y0:.1,y1:.1,line:{color:'#64748b',width:1,dash:'dot'}},{type:'line',xref:'paper',x0:0,x1:1,y0:-.1,y1:-.1,line:{color:'#64748b',width:1,dash:'dot'}}]},{responsive:true,displayModeBar:false});
  }

  function assetHtml(a){
    const name=a.serie||a.ticker||'—';
    const price=finite(a.precio_actual)?Number(a.precio_actual).toFixed(String(name).includes('USD')?4:2):'s/p';
    const r=a.retorno_modelo??a.retorno;
    const ret=finite(r)?`${Number(r)>=0?'+':''}${(Number(r)*100).toFixed(3)}%`:'—';
    const cls=finite(r)?(Number(r)>0?'pos':Number(r)<0?'neg':'zero'):'zero';
    return `<div class="dual-asset"><div class="sym">${name}</div><div class="price">${price}</div><div class="ret ${cls}">${ret}</div><div class="src">${a.estado||'Fuente pendiente'}${a.timestamp?'<br>'+String(a.timestamp).replace('T',' ').slice(0,16):''}</div></div>`;
  }

  function renderAssets(key){
    const m=data?.models?.[key],grid=$('dualMarket_'+key);if(!m||!grid)return;
    const rows=Array.isArray(m.intraday_assets)?m.intraday_assets:[];
    grid.innerHTML=rows.length?rows.map(assetHtml).join(''):'<div class="dual-note">Sin factores disponibles.</div>';
    const note=$('dualSource_'+key);
    if(note)note.textContent=`${data.market_open?'MERCADO ABIERTO':'CIERRE / ÚLTIMO CORTE'} · ${rows.length} factores visibles · ${m.source_note||''}`;
  }

  function arrange(key){
    const model=$('dualModel_'+key);if(!model)return;
    const market=$('dualMarket_'+key)?.closest('.dual-chart-block');
    const vc=$('dualVcChart_'+key)?.closest('.dual-chart-block');
    const ret=$('dualRetChart_'+key)?.closest('.dual-chart-block');
    if(market&&vc&&market.nextElementSibling!==vc)model.insertBefore(market,vc);
    if(market){const t=market.querySelector('.dual-chart-title');if(t)t.textContent=labels[key]+' · factores intradía / último corte';}
    if(vc){const t=vc.querySelector('.dual-chart-title');if(t)t.textContent=labels[key]+' · VC estimado vs VC real SBS · histórico completo + seguimiento';}
    if(ret){const t=ret.querySelector('.dual-chart-title');if(t)t.textContent=labels[key]+' · retorno estimado vs real · histórico completo + seguimiento';}
  }

  function bind(){
    document.querySelectorAll('.dual-controls').forEach(box=>{
      if(box.dataset.v2Bound)return;box.dataset.v2Bound='1';
      box.addEventListener('click',ev=>{
        const b=ev.target.closest('button[data-days]');if(!b)return;
        ev.preventDefault();ev.stopImmediatePropagation();
        box.querySelectorAll('button').forEach(x=>x.classList.remove('active'));b.classList.add('active');
        const key=box.dataset.chart;if(!key)return;
        ranges[key]=b.dataset.days==='all'?'all':Number(b.dataset.days);
        if(key.endsWith('Vc'))plotVc(key.slice(0,-2));else if(key.endsWith('Ret'))plotRet(key.slice(0,-3));
      },true);
    });
  }

  function render(){
    if(!data)return;
    for(const key of ['qqq','new_tickers']){arrange(key);renderAssets(key);plotVc(key);plotRet(key)}
    bind();
    const q=rowsFor('qqq'),n=rowsFor('new_tickers');
    const rule=$('dualRule');
    if(rule){
      const meta=data.history_chart_meta||{};
      rule.textContent=`Histórico cargado en gráficos: Modelo A ${q.length} puntos · Modelo B ${n.length} puntos. Histórico comparable: ${meta.n_common||'—'} observaciones, ${meta.start||'—'} a ${meta.end||'—'}. Los botones 7/15/30/90/Todo filtran por fecha.`;
    }
  }

  async function refresh(){
    try{data=await load();render()}catch(e){console.error('DUAL HISTORY V2',e)}
  }

  function boot(){
    refresh();setInterval(refresh,30000);
    new MutationObserver(()=>{if(data&&$('dualRolling30Root')){bind();render()}}).observe(document.body,{childList:true,subtree:true});
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();
