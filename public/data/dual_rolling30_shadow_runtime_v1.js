(function(){
  'use strict';
  const RAW='https://raw.githubusercontent.com/rldaqp/afp-fondo3-monitor/migracion-github-actions/public/data/';
  const $=id=>document.getElementById(id);
  const finite=x=>x!==null&&x!==undefined&&x!==''&&Number.isFinite(Number(x));
  let payload=null;
  const ranges={qqqVc:30,qqqRet:30,new_tickersVc:30,new_tickersRet:30};
  const MODEL_LABEL={qqq:'Modelo A · Rolling 30 + QQQ',new_tickers:'Modelo B · Rolling 30 + nuevos tickers'};

  function ensureLegacyCompat(){
    let box=$('dualLegacyCompat');
    if(!box){
      box=document.createElement('div');box.id='dualLegacyCompat';box.style.display='none';document.body.appendChild(box);
    }
    ['estVc','estDate','signal','ret','window','vcPrecisionCompact'].forEach(id=>{
      if(!$(id)){const e=document.createElement('span');e.id=id;box.appendChild(e)}
    });
  }

  function clearKnownLegacyError(){
    const e=$('error');
    if(e&&/Cannot set properties of null|setting ['\"]?textContent/i.test(String(e.textContent||'')))e.innerHTML='';
  }

  async function load(){
    const ts=Date.now();
    for(const u of ['data/dual_rolling30_monitor.json?shadow='+ts,RAW+'dual_rolling30_monitor.json?shadow='+ts]){
      try{const r=await fetch(u,{cache:'no-store'});if(r.ok)return await r.json()}catch(e){}
    }
    throw new Error('dual_rolling30_monitor.json no disponible');
  }

  function rowsFor(m){
    const map=new Map();
    (m.history_one_step||[]).forEach(r=>map.set(r.fecha,{...r,_kind:'histórico ciego'}));
    (m.history_operational||[]).forEach(r=>{
      if(!r||!r.fecha||!finite(r.vc_estimated))return;
      map.set(r.fecha,{
        fecha:r.fecha,
        base_vc:r.base_vc,
        vc_estimated:r.vc_estimated,
        actual_vc:r.actual_vc,
        return_estimated:r.return_estimated,
        actual_return:r.actual_return_daily,
        signal:r.signal,
        error_pct:r.error_pct,
        frozen:r.frozen,
        _kind:r.frozen?'operacional guardado':'intradía provisional'
      });
    });
    (m.forward_chain||[]).forEach(r=>{
      const old=map.get(r.fecha)||{};
      if(old._kind==='operacional guardado'&&old.actual_vc!=null)return;
      if(old._kind==='operacional guardado'&&r.fecha!==payload.signal_date)return;
      map.set(r.fecha,{...old,...r,actual_vc:old.actual_vc??r.actual_vc,actual_return:old.actual_return,_kind:old._kind||'provisional'});
    });
    return [...map.values()].filter(r=>r.fecha).sort((a,b)=>a.fecha.localeCompare(b.fecha));
  }

  function inRange(rows,n){
    if(n==='all'||!rows.length)return rows;
    const last=String(rows.at(-1).fecha).slice(0,10),max=new Date(last+'T00:00:00'),min=new Date(max);
    min.setDate(min.getDate()-Number(n));
    return rows.filter(r=>new Date(String(r.fecha).slice(0,10)+'T00:00:00')>=min);
  }

  function signalColor(s){return s==='SUBE'?'#4ade80':s==='BAJA'?'#f87171':'#fbbf24'}
  function estimateSymbol(r){return /provisional|intradía/i.test(String(r._kind||''))?'circle-open':(/operacional guardado/i.test(String(r._kind||''))?'square':'circle')}

  function plotVc(key){
    if(!payload||!window.Plotly)return;
    const m=payload.models&&payload.models[key];if(!m)return;
    const rows=inRange(rowsFor(m),ranges[key+'Vc']);
    const el=$('dualVcChart_'+key);if(!el)return;
    const estimated={
      x:rows.map(r=>r.fecha),y:rows.map(r=>finite(r.vc_estimated)?Number(r.vc_estimated):null),
      type:'scatter',mode:'lines+markers',name:'VC estimado rolling 30',
      line:{width:2,color:'#38bdf8'},marker:{size:8,color:'#38bdf8',symbol:rows.map(estimateSymbol)},
      customdata:rows.map(r=>[r._kind||'',r.signal||'—']),
      hovertemplate:'<b>%{x}</b><br>VC estimado: %{y:.7f}<br>%{customdata[0]} · %{customdata[1]}<extra></extra>'
    };
    const real={
      x:rows.map(r=>r.fecha),y:rows.map(r=>finite(r.actual_vc)?Number(r.actual_vc):null),
      type:'scatter',mode:'lines+markers',name:'VC real SBS',line:{width:2,color:'#fb923c'},marker:{size:7,color:'#fb923c',symbol:'diamond'},
      hovertemplate:'<b>%{x}</b><br>VC SBS: %{y:.7f}<extra></extra>'
    };
    Plotly.react(el,[estimated,real],{
      margin:{l:48,r:14,t:12,b:42},paper_bgcolor:'rgba(0,0,0,0)',plot_bgcolor:'rgba(0,0,0,0)',font:{color:'#cbd5e1',size:10},
      xaxis:{gridcolor:'#243244'},yaxis:{gridcolor:'#243244',title:'Valor cuota'},legend:{orientation:'h',y:1.13}
    },{responsive:true,displayModeBar:false});
  }

  function stemXY(rows,field){
    const x=[],y=[];
    rows.forEach(r=>{if(!finite(r[field]))return;x.push(r.fecha,r.fecha,null);y.push(0,Number(r[field])*100,null)});
    return{x,y};
  }

  function plotRet(key){
    if(!payload||!window.Plotly)return;
    const m=payload.models&&payload.models[key];if(!m)return;
    const rows=inRange(rowsFor(m),ranges[key+'Ret']);
    const el=$('dualRetChart_'+key);if(!el)return;
    const estStem=stemXY(rows,'return_estimated'),realStem=stemXY(rows,'actual_return');
    Plotly.react(el,[
      {x:estStem.x,y:estStem.y,type:'scatter',mode:'lines',name:'Tallo estimado',line:{width:1,color:'#64748b'},hoverinfo:'skip',showlegend:false,connectgaps:false},
      {x:realStem.x,y:realStem.y,type:'scatter',mode:'lines',name:'Tallo SBS',line:{width:1,color:'#7c2d12'},hoverinfo:'skip',showlegend:false,connectgaps:false},
      {
        x:rows.map(r=>r.fecha),y:rows.map(r=>finite(r.return_estimated)?Number(r.return_estimated)*100:null),type:'scatter',mode:'markers',name:'Retorno estimado',
        marker:{size:9,color:rows.map(r=>signalColor(r.signal)),symbol:rows.map(estimateSymbol),line:{width:1,color:'#0f172a'}},
        customdata:rows.map(r=>[r.signal||'—',r._kind||'']),hovertemplate:'<b>%{x}</b><br>Estimado: %{y:+.3f}%<br>%{customdata[0]} · %{customdata[1]}<extra></extra>'
      },
      {
        x:rows.map(r=>r.fecha),y:rows.map(r=>finite(r.actual_return)?Number(r.actual_return)*100:null),type:'scatter',mode:'markers',name:'Retorno real SBS',
        marker:{size:8,color:'#fb923c',symbol:'diamond'},hovertemplate:'<b>%{x}</b><br>SBS real: %{y:+.3f}%<extra></extra>'
      }
    ],{
      margin:{l:48,r:14,t:12,b:42},paper_bgcolor:'rgba(0,0,0,0)',plot_bgcolor:'rgba(0,0,0,0)',font:{color:'#cbd5e1',size:10},
      xaxis:{gridcolor:'#243244'},yaxis:{gridcolor:'#243244',title:'Retorno %',zeroline:true,zerolinecolor:'#94a3b8'},legend:{orientation:'h',y:1.13},
      shapes:[
        {type:'line',xref:'paper',x0:0,x1:1,y0:.1,y1:.1,line:{color:'#64748b',width:1,dash:'dot'}},
        {type:'line',xref:'paper',x0:0,x1:1,y0:-.1,y1:-.1,line:{color:'#64748b',width:1,dash:'dot'}}
      ]
    },{responsive:true,displayModeBar:false});
  }

  function plot(key,type){type==='vc'?plotVc(key):plotRet(key)}

  function metricText(key){
    const m=payload.models?.[key]||{},b=key==='qqq'?payload.blind3?.qqq_common:payload.blind3?.new_tickers_common,o=m.operational_metrics||{};
    const blind=finite(b?.mape_pct)?Number(b.mape_pct).toFixed(3)+'%':'—';
    const live=finite(o.mape_pct)?Number(o.mape_pct).toFixed(3)+'% (n='+Number(o.n||0)+')':'pendiente';
    return `Ciego ${blind} · vivo ${live}`;
  }

  function render(){
    if(!payload)return;
    ensureLegacyCompat();clearKnownLegacyError();
    for(const key of ['qqq','new_tickers']){
      const el=$('dualMape_'+key);if(el)el.textContent=metricText(key);
      const model=$('dualModel_'+key);
      if(model){
        const titles=model.querySelectorAll('.dual-chart-title'),label=MODEL_LABEL[key];
        if(titles[0])titles[0].textContent=label+' · VC SBS vs VC estimado · seguimiento guardado (sin ajuste retroactivo)';
        if(titles[1])titles[1].textContent=label+' · retorno diario estimado vs real · gráfico de puntos';
        if(titles[2])titles[2].textContent=label+' · visor intradía / último corte';
      }
      plot(key,'vc');plot(key,'ret');
    }
    const rule=$('dualRule');if(rule&&payload.operational_history_rule)rule.textContent=payload.rule+' '+payload.operational_history_rule;
    const top=$('dualTopMape');
    if(top){
      const q=payload.models?.qqq?.operational_metrics||{},n=payload.models?.new_tickers?.operational_metrics||{};
      const qx=finite(q.mape_pct)?Number(q.mape_pct).toFixed(3)+'%':'—',nx=finite(n.mape_pct)?Number(n.mape_pct).toFixed(3)+'%':'—';
      const qb=payload.blind3?.qqq_common?.mape_pct,nb=payload.blind3?.new_tickers_common?.mape_pct;
      top.textContent=`Ciego: QQQ ${finite(qb)?Number(qb).toFixed(3):'—'}% · Nuevos ${finite(nb)?Number(nb).toFixed(3):'—'}% · Vivo: QQQ ${qx} · Nuevos ${nx}`;
    }
  }

  function bindControls(){
    document.querySelectorAll('.dual-controls').forEach(box=>{
      if(box.dataset.shadowBound)return;box.dataset.shadowBound='1';
      box.addEventListener('click',ev=>{
        const b=ev.target.closest('button[data-days]');if(!b)return;
        const key=box.dataset.chart;if(!key)return;
        ranges[key]=b.dataset.days==='all'?'all':Number(b.dataset.days);
        setTimeout(render,0);
      },true);
    });
  }

  async function refresh(){
    try{payload=await load();bindControls();render()}
    catch(e){ensureLegacyCompat()}
  }
  function boot(){
    ensureLegacyCompat();
    refresh();setInterval(refresh,30000);
    new MutationObserver(()=>{ensureLegacyCompat();bindControls();if(payload)setTimeout(render,0)}).observe(document.body,{childList:true,subtree:true});
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();