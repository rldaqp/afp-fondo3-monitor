(function(){
  'use strict';
  const RAW='https://raw.githubusercontent.com/rldaqp/afp-fondo3-monitor/migracion-github-actions/public/data/';
  const $=id=>document.getElementById(id);
  const finite=x=>x!==null&&x!==undefined&&x!==''&&Number.isFinite(Number(x));
  let payload=null;
  const ranges={qqqVc:30,qqqRet:30,new_tickersVc:30,new_tickersRet:30};

  async function load(){
    const ts=Date.now();
    for(const u of ['data/dual_rolling30_monitor.json?shadow='+ts,RAW+'dual_rolling30_monitor.json?shadow='+ts]){
      try{const r=await fetch(u,{cache:'no-store'});if(r.ok)return await r.json()}catch(e){}
    }
    throw new Error('dual_rolling30_monitor.json no disponible');
  }
  function rowsFor(m){
    const map=new Map();
    (m.history_one_step||[]).forEach(r=>map.set(r.fecha,{...r,_kind:'referencia'}));
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
        _kind:'operacional congelado'
      });
    });
    (m.forward_chain||[]).forEach(r=>{
      const old=map.get(r.fecha)||{};
      // La fecha todavía abierta puede moverse intradía. Una fecha congelada del
      // history_operational nunca se reemplaza por un recálculo posterior.
      if(old._kind==='operacional congelado' && old.actual_vc!=null)return;
      if(old._kind==='operacional congelado' && r.fecha!==payload.signal_date)return;
      map.set(r.fecha,{...old,...r,actual_vc:old.actual_vc??r.actual_vc,actual_return:old.actual_return,_kind:old._kind||'forward'});
    });
    return [...map.values()].filter(r=>r.fecha).sort((a,b)=>a.fecha.localeCompare(b.fecha));
  }
  function slice(rows,n){return n==='all'?rows:rows.slice(-Number(n||30));}
  function plot(key,type){
    if(!payload||!window.Plotly)return;
    const m=payload.models&&payload.models[key];if(!m)return;
    const rows=slice(rowsFor(m),ranges[key+(type==='vc'?'Vc':'Ret')]);
    const el=$(type==='vc'?'dualVcChart_'+key:'dualRetChart_'+key);if(!el)return;
    const common={margin:{l:48,r:14,t:12,b:42},paper_bgcolor:'rgba(0,0,0,0)',plot_bgcolor:'rgba(0,0,0,0)',font:{color:'#cbd5e1',size:10},xaxis:{gridcolor:'#243244'},legend:{orientation:'h',y:1.12}};
    if(type==='vc'){
      Plotly.react(el,[
        {x:rows.map(r=>r.fecha),y:rows.map(r=>finite(r.vc_estimated)?Number(r.vc_estimated):null),type:'scatter',mode:'lines+markers',name:'VC estimado guardado',line:{width:2},customdata:rows.map(r=>r._kind||''),hovertemplate:'%{x}<br>Estimado %{y:.7f}<br>%{customdata}<extra></extra>'},
        {x:rows.map(r=>r.fecha),y:rows.map(r=>finite(r.actual_vc)?Number(r.actual_vc):null),type:'scatter',mode:'lines+markers',name:'VC real SBS',line:{width:2},hovertemplate:'%{x}<br>SBS %{y:.7f}<extra></extra>'}
      ],{...common,yaxis:{gridcolor:'#243244',title:'Valor cuota'}},{responsive:true,displayModeBar:false});
    }else{
      Plotly.react(el,[
        {x:rows.map(r=>r.fecha),y:rows.map(r=>finite(r.return_estimated)?Number(r.return_estimated)*100:null),type:'bar',name:'Retorno estimado %'},
        {x:rows.map(r=>r.fecha),y:rows.map(r=>finite(r.actual_return)?Number(r.actual_return)*100:null),type:'scatter',mode:'lines+markers',name:'Retorno real SBS %',line:{width:2}}
      ],{...common,yaxis:{gridcolor:'#243244',title:'Retorno %',zeroline:true,zerolinecolor:'#64748b'}},{responsive:true,displayModeBar:false});
    }
  }
  function metricText(key){
    const m=payload.models?.[key]||{}, b=key==='qqq'?payload.blind3?.qqq_common:payload.blind3?.new_tickers_common, o=m.operational_metrics||{};
    const blind=finite(b?.mape_pct)?Number(b.mape_pct).toFixed(3)+'%':'—';
    const live=finite(o.mape_pct)?Number(o.mape_pct).toFixed(3)+'% (n='+Number(o.n||0)+')':'pendiente';
    return `Ciego ${blind} · vivo ${live}`;
  }
  function render(){
    if(!payload)return;
    for(const key of ['qqq','new_tickers']){
      const el=$('dualMape_'+key);if(el)el.textContent=metricText(key);
      const model=$('dualModel_'+key);if(model){const titles=model.querySelectorAll('.dual-chart-title');if(titles[0])titles[0].textContent='VC real SBS vs VC estimado guardado (sin ajuste retroactivo)';if(titles[1])titles[1].textContent='Retorno estimado guardado vs retorno real SBS';}
      plot(key,'vc');plot(key,'ret');
    }
    const rule=$('dualRule');if(rule&&payload.operational_history_rule)rule.textContent=payload.rule+' '+payload.operational_history_rule;
    const top=$('dualTopMape');if(top){const q=payload.models?.qqq?.operational_metrics||{},n=payload.models?.new_tickers?.operational_metrics||{};const qx=finite(q.mape_pct)?Number(q.mape_pct).toFixed(3)+'%':'—',nx=finite(n.mape_pct)?Number(n.mape_pct).toFixed(3)+'%':'—';top.textContent=`Ciego: QQQ ${Number(payload.blind3?.qqq_common?.mape_pct||0).toFixed(3)}% · Nuevos ${Number(payload.blind3?.new_tickers_common?.mape_pct||0).toFixed(3)}% · Vivo: QQQ ${qx} · Nuevos ${nx}`;}
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
  async function refresh(){try{payload=await load();bindControls();render()}catch(e){}}
  function boot(){refresh();setInterval(refresh,30000);new MutationObserver(()=>{bindControls();if(payload)setTimeout(render,0)}).observe(document.body,{childList:true,subtree:true})}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();
