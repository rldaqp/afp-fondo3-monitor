(function(){
  'use strict';
  const RAW='https://raw.githubusercontent.com/rldaqp/afp-fondo3-monitor/migracion-github-actions/public/data/';
  const RAW_BLIND='https://raw.githubusercontent.com/rldaqp/afp-fondo3-monitor/migracion-github-actions/analysis/backtest_blind3_rolling30_common.csv';
  const $=id=>document.getElementById(id);
  const finite=x=>x!==null&&x!==undefined&&x!==''&&Number.isFinite(Number(x));
  const classify=x=>Number(x)>0.001?'SUBE':Number(x)<-0.001?'BAJA':'NEUTRO';
  let payload=null;
  let blindHistory={qqq:[],new_tickers:[]};
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

  function parseBlindCsv(text){
    const out={qqq:[],new_tickers:[]};
    String(text||'').split(/\r?\n/).slice(1).forEach(line=>{
      if(!line.trim())return;
      const p=line.split(',',8);
      if(p.length<8||Number(p[0])!==3)return;
      const fecha=p[1],base=Number(p[3]),actual=Number(p[4]),qqq=Number(p[5]),nuevo=Number(p[7]);
      if(!fecha||![base,actual,qqq,nuevo].every(Number.isFinite))return;
      const make=est=>{
        const re=est/base-1,rr=actual/base-1;
        return {fecha,base_vc:base,vc_estimated:est,actual_vc:actual,return_estimated:re,actual_return:rr,signal:classify(re),_kind:'backtest ciego 3 VC',horizon:'3 VC'};
      };
      out.qqq.push(make(qqq));out.new_tickers.push(make(nuevo));
    });
    out.qqq.sort((a,b)=>a.fecha.localeCompare(b.fecha));out.new_tickers.sort((a,b)=>a.fecha.localeCompare(b.fecha));
    return out;
  }

  async function loadBlindHistory(){
    try{
      const r=await fetch(RAW_BLIND+'?ts='+Date.now(),{cache:'no-store'});
      if(!r.ok)throw new Error('HTTP '+r.status);
      blindHistory=parseBlindCsv(await r.text());
    }catch(e){blindHistory={qqq:[],new_tickers:[]};}
  }

  function rowsFor(key,m){
    const map=new Map();
    (blindHistory[key]||[]).forEach(r=>map.set(r.fecha,{...r}));
    (m.history_one_step||[]).forEach(r=>map.set(r.fecha,{...map.get(r.fecha),...r,_kind:'backtest ciego 3 VC',horizon:'3 VC'}));
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
        _kind:r.frozen?'operacional guardado':'intradía provisional',
        horizon:'1 sesión'
      });
    });
    (m.forward_chain||[]).forEach(r=>{
      const old=map.get(r.fecha)||{};
      if(old._kind==='operacional guardado'&&old.actual_vc!=null)return;
      if(old._kind==='operacional guardado'&&r.fecha!==payload.signal_date)return;
      map.set(r.fecha,{...old,...r,actual_vc:old.actual_vc??r.actual_vc,actual_return:old.actual_return,_kind:old._kind||'provisional',horizon:old.horizon||'1 sesión'});
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
    const rows=inRange(rowsFor(key,m),ranges[key+'Vc']);
    const el=$('dualVcChart_'+key);if(!el)return;
    const estimated={
      x:rows.map(r=>r.fecha),y:rows.map(r=>finite(r.vc_estimated)?Number(r.vc_estimated):null),
      type:'scatter',mode:'lines+markers',name:'VC estimado rolling 30',
      line:{width:2,color:'#38bdf8'},marker:{size:7,color:'#38bdf8',symbol:rows.map(estimateSymbol)},
      customdata:rows.map(r=>[r._kind||'',r.signal||'—',r.horizon||'']),
      hovertemplate:'<b>%{x}</b><br>VC estimado: %{y:.7f}<br>%{customdata[0]} · %{customdata[1]}<br>Horizonte: %{customdata[2]}<extra></extra>'
    };
    const real={
      x:rows.map(r=>r.fecha),y:rows.map(r=>finite(r.actual_vc)?Number(r.actual_vc):null),
      type:'scatter',mode:'lines+markers',name:'VC real SBS',line:{width:2,color:'#fb923c'},marker:{size:6,color:'#fb923c',symbol:'diamond'},
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
    const rows=inRange(rowsFor(key,m),ranges[key+'Ret']);
    const el=$('dualRetChart_'+key);if(!el)return;
    const estStem=stemXY(rows,'return_estimated'),realStem=stemXY(rows,'actual_return');
    Plotly.react(el,[
      {x:estStem.x,y:estStem.y,type:'scatter',mode:'lines',line:{width:1,color:'#64748b'},hoverinfo:'skip',showlegend:false,connectgaps:false},
      {x:realStem.x,y:realStem.y,type:'scatter',mode:'lines',line:{width:1,color:'#7c2d12'},hoverinfo:'skip',showlegend:false,connectgaps:false},
      {
        x:rows.map(r=>r.fecha),y:rows.map(r=>finite(r.return_estimated)?Number(r.return_estimated)*100:null),type:'scatter',mode:'markers',name:'Retorno estimado',
        marker:{size:8,color:rows.map(r=>signalColor(r.signal)),symbol:rows.map(estimateSymbol),line:{width:1,color:'#0f172a'}},
        customdata:rows.map(r=>[r.signal||'—',r._kind||'',r.horizon||'']),hovertemplate:'<b>%{x}</b><br>Estimado: %{y:+.3f}%<br>%{customdata[0]} · %{customdata[1]}<br>Horizonte: %{customdata[2]}<extra></extra>'
      },
      {
        x:rows.map(r=>r.fecha),y:rows.map(r=>finite(r.actual_return)?Number(r.actual_return)*100:null),type:'scatter',mode:'markers',name:'Retorno real SBS',
        marker:{size:7,color:'#fb923c',symbol:'diamond'},hovertemplate:'<b>%{x}</b><br>SBS real: %{y:+.3f}%<extra></extra>'
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

  function marketBlock(key){const el=$('dualMarket_'+key);return el?el.closest('.dual-chart-block'):null}
  function vcBlock(key){const el=$('dualVcChart_'+key);return el?el.closest('.dual-chart-block'):null}
  function retBlock(key){const el=$('dualRetChart_'+key);return el?el.closest('.dual-chart-block'):null}

  function stampText(s){
    if(!s)return 'sin hora';
    const x=String(s);if(!x.includes('T'))return x.slice(0,10);
    return x.replace('T',' ').slice(0,16);
  }

  function assetHtml(a){
    const name=a.serie||a.ticker||'—',raw=a.precio_actual,price=finite(raw)?Number(raw).toFixed(String(name).includes('USD')?4:2):'s/p',r=a.retorno_modelo??a.retorno;
    const ret=finite(r)?`${Number(r)>=0?'+':''}${(Number(r)*100).toFixed(3)}%`:'—';
    const cls=finite(r)?(Number(r)>0?'pos':Number(r)<0?'neg':'zero'):'zero';
    return `<div class="dual-asset"><div class="sym">${name}</div><div class="price">${price}</div><div class="ret ${cls}">${ret}</div><div class="src">${a.estado||'Fuente pendiente'}<br>${stampText(a.timestamp)}</div></div>`;
  }

  function renderMarket(key){
    const m=payload?.models?.[key],grid=$('dualMarket_'+key);if(!m||!grid)return;
    const rows=Array.isArray(m.intraday_assets)?m.intraday_assets:[];
    grid.innerHTML=rows.length?rows.map(assetHtml).join(''):'<div class="dual-note">Sin cotizaciones intradía disponibles en este corte.</div>';
    const note=$('dualSource_'+key);
    if(note)note.textContent=`${payload.market_open?'MERCADO ABIERTO':'CIERRE / ÚLTIMO CORTE'} · ${rows.length} factores visibles · ${m.source_note||''}`;
  }

  function arrangeModel(key){
    const model=$('dualModel_'+key);if(!model)return;
    const mb=marketBlock(key),vb=vcBlock(key),rb=retBlock(key),label=MODEL_LABEL[key];
    if(mb&&vb&&mb!==vb)model.insertBefore(mb,vb);
    if(mb){const t=mb.querySelector('.dual-chart-title');if(t)t.textContent=label+' · factores intradía / último corte';}
    if(vb){const t=vb.querySelector('.dual-chart-title');if(t)t.textContent=label+' · histórico VC estimado vs VC real SBS · backtest ciego 3 VC + seguimiento';}
    if(rb){const t=rb.querySelector('.dual-chart-title');if(t)t.textContent=label+' · retorno estimado vs real · puntos históricos y seguimiento';}
  }

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
      arrangeModel(key);renderMarket(key);plotVc(key);plotRet(key);
    }
    const rule=$('dualRule');
    if(rule){
      const n=Math.min(blindHistory.qqq.length,blindHistory.new_tickers.length);
      rule.textContent=`Histórico visible: ${n} observaciones comparables del backtest ciego de 3 VC, desde ${n?blindHistory.qqq[0].fecha:'—'} hasta ${n?blindHistory.qqq.at(-1).fecha:'—'}. `+(payload.operational_history_rule||payload.rule||'');
    }
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
    try{
      const [p]=await Promise.all([load(),loadBlindHistory()]);
      payload=p;bindControls();render();
    }catch(e){ensureLegacyCompat();}
  }
  function boot(){
    ensureLegacyCompat();
    refresh();setInterval(refresh,30000);
    new MutationObserver(()=>{ensureLegacyCompat();bindControls();if(payload)setTimeout(render,0)}).observe(document.body,{childList:true,subtree:true});
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();