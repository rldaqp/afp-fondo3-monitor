(()=>{'use strict';
function ensureThreshold(){
 const g=document.getElementById('chartRet');
 if(!g||!window.Plotly||!Array.isArray(g.data)||!g.data.length)return;
 if(g.data.some(t=>t&&t.name==='Umbral ingreso +1%'))return;
 const xs=[];for(const t of g.data){if(Array.isArray(t?.x))for(const x of t.x)if(x)xs.push(x)}
 if(!xs.length)return;xs.sort();
 Plotly.addTraces(g,{x:[xs[0],xs[xs.length-1]],y:[1,1],type:'scatter',mode:'lines',name:'Umbral ingreso +1%',line:{color:'#22c55e',width:2,dash:'dash'},hovertemplate:'Umbral de ingreso: +1.000%<extra></extra>'}).catch(()=>{});
}
function boot(){setTimeout(ensureThreshold,1200);setInterval(ensureThreshold,1800)}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();
