(function(){
  'use strict';
  const $=id=>document.getElementById(id);
  const finite=x=>x!==null&&x!==undefined&&x!==''&&Number.isFinite(Number(x));
  const vc=x=>finite(x)?Number(x).toFixed(7):'—';
  const pct=x=>finite(x)?`${Number(x)>=0?'+':''}${(Number(x)*100).toFixed(3)}%`:'—';
  const fmt=d=>{if(!d)return'—';const p=String(d).slice(0,10).split('-');return p.length===3?`${p[2]}/${p[1]}/${p[0]}`:String(d)};
  const ranges={qqqVc:30,qqqRet:30,new_tickersVc:30,new_tickersRet:30};
  const LABEL={qqq:'Modelo A · Rolling 30 + QQQ',new_tickers:'Modelo B · Rolling 30 + nuevos tickers'};
  let data=null;

  async function load(){
    const r=await fetch('data/dual_rolling30_monitor.json?dual='+Date.now(),{cache:'no-store'});
    if(!r.ok)throw new Error('HTTP '+r.status);
    return r.json();
  }

  function hideLegacy(){
    ['reduced6030Panel','modelInsightsPanel','marketPanel','marketExperimentalPanel','monitorHelp','audit'].forEach(id=>{
      const e=$(id);if(!e)return;const p=e.closest&&e.closest('.panel');(p||e).style.display='none';
    });
    ['vcChart','signalChart'].forEach(id=>{const e=$(id);const p=e&&e.closest('.panel');if(p)p.style.display='none'});
    const old=$('dualRolling30Root');if(old)old.style.display='none';
    document.querySelectorAll('.panel').forEach(p=>{
      if(p.id==='dualTakeoverV3')return;
      const t=String(p.textContent||'').replace(/\s+/g,' ').trim();
      if(/Comparación de VC estimado|Confianza y calidad del modelo|VC real vs VC estimado|Retorno estimado diario del VC y señal|Mercado ahora|OLS OFICIAL · ROLLING 90|60\/30 SIN NEM/i.test(t))p.style.display='none';
    });
    const h1=document.querySelector('main.wrap>h1');if(h1)h1.textContent='Profuturo Fondo 3';
    const sub=document.querySelector('main.wrap>h1 + .sub');if(sub)sub.textContent='Comparación operativa · solo dos modelos OLS Rolling 30 · seguimiento contra SBS';
  }

  function ensureStyles(){
    if($('dualTakeoverV3Styles'))return;
    const s=document.createElement('style');s.id='dualTakeoverV3Styles';s.textContent=`
      #dualTakeoverV3{display:block!important}.dv3-head{display:flex;justify-content:space-between;gap:10px;align-items:flex-start}.dv3-title{font-size:1.02rem;font-weight:900}.dv3-sub{font-size:.72rem;color:#94a3b8;line-height:1.45;margin-top:3px}.dv3-model{margin-top:12px;border:1px solid #334155;border-radius:14px;padding:12px;background:#0d192b}.dv3-model h3{margin:0;font-size:.95rem}.dv3-features{font-size:.69rem;color:#94a3b8;margin-top:4px}.dv3-now{display:grid;grid-template-columns:repeat(4,1fr);gap:7px;margin-top:9px}.dv3-mini{background:#101d31;border:1px solid #243244;border-radius:10px;padding:9px}.dv3-mini span{display:block;font-size:.67rem;color:#94a3b8}.dv3-mini b{display:block;margin-top:3px;font-size:.88rem}.dv3-chartbox{margin-top:10px;background:#0b1728;border:1px solid #243244;border-radius:11px;padding:9px}.dv3-charttitle{font-size:.8rem;font-weight:850;margin-bottom:6px}.dv3-controls{display:flex;gap:5px;flex-wrap:wrap;margin-bottom:6px}.dv3-controls button{border:1px solid #334155;background:#132238;color:#fff;border-radius:8px;padding:6px 9px;font-size:.7rem;font-weight:750}.dv3-controls button.active{background:#2563eb}.dv3-chart{height:310px}.dv3-market{display:grid;grid-template-columns:repeat(3,1fr);gap:7px}.dv3-asset{background:#101d31;border:1px solid #243244;border-radius:10px;padding:9px}.dv3-asset .sym{font-size:.76rem;font-weight:850}.dv3-asset .price{font-size:1rem;font-weight:900;margin-top:3px}.dv3-asset .ret{font-size:.84rem;font-weight:850;margin-top:2px}.dv3-asset .src{font-size:.64rem;color:#94a3b8;margin-top:4px;line-height:1.3;overflow-wrap:anywhere}.dv3-note{font-size:.69rem;color:#94a3b8;line-height:1.45;margin-top:8px}.dv3-up{color:#4ade80}.dv3-down{color:#f87171}.dv3-flat{color:#fbbf24}
      @media(max-width:700px){.dv3-now{grid-template-columns:1fr 1fr}.dv3-market{grid-template-columns:1fr 1fr}.dv3-chart{height:285px}}
      @media(max-width:390px){.dv3-now,.dv3-market{grid-template-columns:1fr}.dv3-chart{height:270px}}
    `;document.head.appendChild(s);
  }

  function ensureTop(){
    const grid=document.querySelector('main.wrap>section.grid');if(!grid)return null;
    grid.innerHTML=`
      <div class="card"><div class="label">Último VC SBS oficial</div><div class="value" id="dv3SbsVc">—</div><div class="sub" id="dv3SbsDate">—</div></div>
      <div class="card"><div class="label">Modelo A · Rolling 30 + QQQ</div><div class="value" id="dv3TopAVc">—</div><div class="sub" id="dv3TopASig">—</div></div>
      <div class="card"><div class="label">Modelo B · Rolling 30 + nuevos tickers</div><div class="value" id="dv3TopBVc">—</div><div class="sub" id="dv3TopBSig">—</div></div>
      <div class="card"><div class="label">Comparación actual</div><div class="value" id="dv3Winner">—</div><div class="sub" id="dv3Diff">—</div></div>`;
    return grid;
  }

  function controls(key,type){
    return `<div class="dv3-controls" data-key="${key}" data-type="${type}"><button data-days="7">7 días</button><button data-days="15">15 días</button><button data-days="30" class="active">30 días</button><button data-days="90">90 días</button><button data-days="all">Todo</button></div>`;
  }

  function modelHtml(key){
    const m=data.models[key],c=m.current||{};
    const features=(m.features_display||[]).join(' · ');
    const blind=key==='qqq'?data.blind3?.qqq_common:data.blind3?.new_tickers_common;
    return `<section class="dv3-model" id="dv3Model_${key}">
      <h3>${LABEL[key]}</h3><div class="dv3-features">${features}</div>
      <div class="dv3-now">
        <div class="dv3-mini"><span>VC estimado actual</span><b>${vc(c.vc_estimated)}</b></div>
        <div class="dv3-mini"><span>Retorno estimado</span><b class="${c.return_estimated>0?'dv3-up':c.return_estimated<0?'dv3-down':'dv3-flat'}">${pct(c.return_estimated)} · ${c.signal||'—'}</b></div>
        <div class="dv3-mini"><span>Ancla SBS usada</span><b>${fmt(c.anchor_date)} · ${vc(c.anchor_vc)}</b></div>
        <div class="dv3-mini"><span>MAPE ciego 3 VC</span><b>${finite(blind?.mape_pct)?Number(blind.mape_pct).toFixed(3)+'%':'—'}</b></div>
      </div>
      <div class="dv3-chartbox"><div class="dv3-charttitle">Factores intradía / último corte</div><div class="dv3-market" id="dv3Market_${key}"></div><div class="dv3-note" id="dv3Source_${key}"></div></div>
      <div class="dv3-chartbox"><div class="dv3-charttitle">VC estimado vs VC real SBS · histórico + seguimiento</div>${controls(key,'Vc')}<div id="dv3Vc_${key}" class="dv3-chart"></div><div class="dv3-note" id="dv3VcNote_${key}"></div></div>
      <div class="dv3-chartbox"><div class="dv3-charttitle">Retorno estimado vs retorno real SBS · gráfico de puntos</div>${controls(key,'Ret')}<div id="dv3Ret_${key}" class="dv3-chart"></div><div class="dv3-note" id="dv3RetNote_${key}"></div></div>
    </section>`;
  }

  function ensureRoot(){
    hideLegacy();ensureStyles();const grid=ensureTop();if(!grid)return null;
    let root=$('dualTakeoverV3');
    if(!root){root=document.createElement('section');root.className='panel';root.id='dualTakeoverV3';grid.insertAdjacentElement('afterend',root)}
    root.innerHTML=`<div class="dv3-head"><div><div class="dv3-title">Dos modelos Rolling 30 en seguimiento</div><div class="dv3-sub">El visor antiguo Rolling 90/60-30 queda fuera de esta comparación. Ambos modelos se miden con el mismo VC SBS oficial.</div></div><div class="dv3-sub" id="dv3Updated"></div></div>${modelHtml('qqq')}${modelHtml('new_tickers')}<div class="dv3-note" id="dv3Rule"></div>`;
    bind();return root;
  }

  function rowsFor(key){
    const m=data?.models?.[key];if(!m)return [];
    const map=new Map();
    (m.history_one_step||[]).forEach(r=>{if(r&&r.fecha&&finite(r.vc_estimated))map.set(r.fecha,{...r,_kind:r.validation||'histórico'})});
    (m.history_operational||[]).forEach(r=>{if(r&&r.fecha&&finite(r.vc_estimated))map.set(r.fecha,{fecha:r.fecha,base_vc:r.base_vc,vc_estimated:r.vc_estimated,actual_vc:r.actual_vc,return_estimated:r.return_estimated,actual_return:r.actual_return_daily,signal:r.signal,_kind:r.frozen?'operacional guardado':'operacional'})});
    (m.forward_chain||[]).forEach(r=>{if(!r||!r.fecha||!finite(r.vc_estimated))return;const old=map.get(r.fecha)||{};map.set(r.fecha,{...old,...r,actual_vc:old.actual_vc??r.actual_vc,actual_return:old.actual_return,_kind:old._kind||'seguimiento'})});
    return [...map.values()].sort((a,b)=>String(a.fecha).localeCompare(String(b.fecha)));
  }

  function inRange(rows,days){
    if(days==='all'||!rows.length)return rows;
    const last=new Date(String(rows.at(-1).fecha).slice(0,10)+'T00:00:00'),cut=new Date(last);cut.setDate(cut.getDate()-Number(days));
    return rows.filter(r=>new Date(String(r.fecha).slice(0,10)+'T00:00:00')>=cut);
  }
  function sigColor(s){return s==='SUBE'?'#4ade80':s==='BAJA'?'#f87171':'#fbbf24'}

  function plotVc(key){
    if(!window.Plotly)return;const el=$('dv3Vc_'+key);if(!el)return;
    const rows=inRange(rowsFor(key),ranges[key+'Vc']);
    Plotly.react(el,[
      {x:rows.map(r=>r.fecha),y:rows.map(r=>finite(r.vc_estimated)?Number(r.vc_estimated):null),type:'scatter',mode:'lines+markers',name:'VC estimado rolling 30',line:{width:2,color:'#38bdf8'},marker:{size:6,color:'#38bdf8'},hovertemplate:'<b>%{x}</b><br>VC estimado %{y:.7f}<extra></extra>'},
      {x:rows.map(r=>r.fecha),y:rows.map(r=>finite(r.actual_vc)?Number(r.actual_vc):null),type:'scatter',mode:'lines+markers',name:'VC real SBS',line:{width:2,color:'#fb923c'},marker:{size:6,color:'#fb923c',symbol:'diamond'},hovertemplate:'<b>%{x}</b><br>VC SBS %{y:.7f}<extra></extra>'}
    ],{margin:{l:48,r:14,t:12,b:42},paper_bgcolor:'rgba(0,0,0,0)',plot_bgcolor:'rgba(0,0,0,0)',font:{color:'#cbd5e1',size:10},xaxis:{gridcolor:'#243244'},yaxis:{gridcolor:'#243244',title:'Valor cuota'},legend:{orientation:'h',y:1.13}},{responsive:true,displayModeBar:false});
    const n=$('dv3VcNote_'+key);if(n)n.textContent=`Mostrando ${rows.length} puntos · ${rows.length?fmt(rows[0].fecha):'—'} a ${rows.length?fmt(rows.at(-1).fecha):'—'}`;
  }

  function plotRet(key){
    if(!window.Plotly)return;const el=$('dv3Ret_'+key);if(!el)return;
    const rows=inRange(rowsFor(key),ranges[key+'Ret']);
    const sx=[],sy=[];rows.forEach(r=>{if(finite(r.return_estimated)){sx.push(r.fecha,r.fecha,null);sy.push(0,Number(r.return_estimated)*100,null)}});
    Plotly.react(el,[
      {x:sx,y:sy,type:'scatter',mode:'lines',line:{width:1,color:'#64748b'},hoverinfo:'skip',showlegend:false,connectgaps:false},
      {x:rows.map(r=>r.fecha),y:rows.map(r=>finite(r.return_estimated)?Number(r.return_estimated)*100:null),type:'scatter',mode:'markers',name:'Retorno estimado',marker:{size:8,color:rows.map(r=>sigColor(r.signal)),line:{width:1,color:'#0f172a'}},hovertemplate:'<b>%{x}</b><br>Estimado %{y:+.3f}%<extra></extra>'},
      {x:rows.map(r=>r.fecha),y:rows.map(r=>finite(r.actual_return)?Number(r.actual_return)*100:null),type:'scatter',mode:'markers',name:'Retorno real SBS',marker:{size:7,color:'#fb923c',symbol:'diamond'},hovertemplate:'<b>%{x}</b><br>SBS %{y:+.3f}%<extra></extra>'}
    ],{margin:{l:48,r:14,t:12,b:42},paper_bgcolor:'rgba(0,0,0,0)',plot_bgcolor:'rgba(0,0,0,0)',font:{color:'#cbd5e1',size:10},xaxis:{gridcolor:'#243244'},yaxis:{gridcolor:'#243244',title:'Retorno %',zeroline:true,zerolinecolor:'#94a3b8'},legend:{orientation:'h',y:1.13},shapes:[{type:'line',xref:'paper',x0:0,x1:1,y0:.1,y1:.1,line:{color:'#64748b',width:1,dash:'dot'}},{type:'line',xref:'paper',x0:0,x1:1,y0:-.1,y1:-.1,line:{color:'#64748b',width:1,dash:'dot'}}]},{responsive:true,displayModeBar:false});
    const n=$('dv3RetNote_'+key);if(n)n.textContent=`Mostrando ${rows.length} puntos · ${rows.length?fmt(rows[0].fecha):'—'} a ${rows.length?fmt(rows.at(-1).fecha):'—'}`;
  }

  function assetHtml(a){
    const name=a.serie||a.ticker||'—',r=a.retorno_modelo??a.retorno,price=finite(a.precio_actual)?Number(a.precio_actual).toFixed(String(name).includes('USD')?4:2):'s/p';
    return `<div class="dv3-asset"><div class="sym">${name}</div><div class="price">${price}</div><div class="ret ${finite(r)?(Number(r)>0?'dv3-up':Number(r)<0?'dv3-down':'dv3-flat'):'dv3-flat'}">${pct(r)}</div><div class="src">${a.estado||'Fuente pendiente'}${a.timestamp?'<br>'+String(a.timestamp).replace('T',' ').slice(0,16):''}</div></div>`;
  }

  function renderMarket(key){
    const m=data.models[key],grid=$('dv3Market_'+key),rows=Array.isArray(m.intraday_assets)?m.intraday_assets:[];if(grid)grid.innerHTML=rows.map(assetHtml).join('');
    const note=$('dv3Source_'+key);if(note)note.textContent=`${data.market_open?'MERCADO ABIERTO':'CIERRE / ÚLTIMO CORTE'} · ${rows.length} factores visibles · ${m.source_note||''}`;
  }

  function renderTop(){
    const s=data.latest_sbs||{},a=data.models.qqq.current||{},b=data.models.new_tickers.current||{};
    if($('dv3SbsVc'))$('dv3SbsVc').textContent=vc(s.vc);if($('dv3SbsDate'))$('dv3SbsDate').textContent=`${fmt(s.fecha)} · SBS OFICIAL`;
    if($('dv3TopAVc'))$('dv3TopAVc').textContent=vc(a.vc_estimated);if($('dv3TopASig'))$('dv3TopASig').textContent=`${fmt(a.fecha)} · ${a.signal||'—'} · ${pct(a.return_estimated)}`;
    if($('dv3TopBVc'))$('dv3TopBVc').textContent=vc(b.vc_estimated);if($('dv3TopBSig'))$('dv3TopBSig').textContent=`${fmt(b.fecha)} · ${b.signal||'—'} · ${pct(b.return_estimated)}`;
    const w=data.comparison?.winner_blind3_mape||'—',d=data.comparison?.vc_difference;if($('dv3Winner'))$('dv3Winner').textContent=w;if($('dv3Diff'))$('dv3Diff').textContent=`B - A: ${finite(d)?Number(d).toFixed(4):'—'} VC`;
    if($('dv3Updated'))$('dv3Updated').textContent=`Último corte: ${String(data.generated_at_lima||'').replace('T',' ').slice(0,16)}`;
  }

  function bind(){
    const root=$('dualTakeoverV3');if(!root||root.dataset.bound)return;root.dataset.bound='1';
    root.addEventListener('click',ev=>{
      const b=ev.target.closest('.dv3-controls button[data-days]');if(!b)return;
      ev.preventDefault();ev.stopImmediatePropagation();const box=b.closest('.dv3-controls');box.querySelectorAll('button').forEach(x=>x.classList.remove('active'));b.classList.add('active');
      const key=box.dataset.key,type=box.dataset.type,val=b.dataset.days==='all'?'all':Number(b.dataset.days);ranges[key+type]=val;type==='Vc'?plotVc(key):plotRet(key);
    },true);
  }

  function render(){
    if(!data)return;ensureRoot();renderTop();for(const key of ['qqq','new_tickers']){renderMarket(key);plotVc(key);plotRet(key)};
    const q=rowsFor('qqq'),n=rowsFor('new_tickers'),meta=data.history_chart_meta||{};if($('dv3Rule'))$('dv3Rule').textContent=`Histórico disponible: Modelo A ${q.length} puntos · Modelo B ${n.length} puntos · comparación común ${meta.n_common||Math.min(q.length,n.length)} observaciones. Los botones filtran períodos diferentes.`;
    hideLegacy();
  }

  async function refresh(){try{data=await load();render()}catch(e){console.error('DUAL TAKEOVER V3',e)}}
  function boot(){refresh();setInterval(refresh,30000);setInterval(hideLegacy,1500);new MutationObserver(()=>hideLegacy()).observe(document.body,{childList:true,subtree:true});}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();