import json
from pathlib import Path
import numpy as np
import pandas as pd

OUT=Path('analysis/test_poly_returns_per_factor_model_a.json')
FACTORS=['ret_SPY','ret_EEM','ret_EPU','ret_MCHI','ret_USD_PEN','ret_QQQ']


def metrics(y,p):
    y=np.asarray(y,float); p=np.asarray(p,float); e=p-y
    sse=float(np.sum(e*e)); sst=float(np.sum((y-y.mean())**2))
    r=float(np.corrcoef(y,p)[0,1]) if len(y)>1 else None
    return {'n':int(len(y)),'pearson_r':r,'corr2':None if r is None else r*r,
            'predictive_r2':float(1-sse/sst) if sst>0 else None,
            'mae':float(np.mean(np.abs(e))),'rmse':float(np.sqrt(np.mean(e*e))),
            'mape_pct':float(np.mean(np.abs(e/y))*100),'bias':float(np.mean(e))}


def fit_quad(x,y,t):
    x=np.asarray(x,float); y=np.asarray(y,float)
    mu=float(x.mean()); sd=float(x.std(ddof=0)) or 1.0
    u=(x-mu)/sd; z=(float(t)-mu)/sd
    X=np.column_stack([np.ones(len(x)),u,u*u])
    b=np.linalg.lstsq(X,y,rcond=None)[0]
    pred=float(b[0]+b[1]*z+b[2]*z*z)
    ins=X@b
    rmse=float(np.sqrt(np.mean((ins-y)**2)))
    return pred,rmse

# VC oficial: preferir actual_vc de history_one_step porque es la serie SBS validada usada por el visor
mon=json.loads(Path('public/data/dual_rolling30_monitor.json').read_text(encoding='utf-8'))
a=mon['models']['qqq']
vcmap={}
for r in a.get('history_one_step',[]):
    d=str(r.get('fecha',''))[:10]
    v=r.get('actual_vc')
    if d and v is not None:
        vcmap[d]=float(v)
# complementar desde series.json sólo fechas faltantes
s=json.loads(Path('public/data/series.json').read_text(encoding='utf-8'))
rows=s if isinstance(s,list) else (s.get('series') or s.get('data') or s.get('rows') or [])
for r in rows:
    d=str(r.get('fecha',''))[:10]
    if d in vcmap: continue
    try:v=float(r.get('vc'))
    except:continue
    if d and v>0: vcmap[d]=v
vc=pd.DataFrame([(pd.Timestamp(d),v) for d,v in vcmap.items()],columns=['fecha','VC']).sort_values('fecha').drop_duplicates('fecha')
vc['ret_vc']=vc['VC'].pct_change()
vc['base_vc']=vc['VC'].shift(1)

# Factores A desde markets y QQQ
m=pd.read_csv('data/rolling90/markets.csv')
m['fecha']=pd.to_datetime(m['fecha'])
m=m[['fecha','ret_SPY','ret_EEM','ret_EPU','ret_MCHI','ret_USD_PEN']].copy()
q=pd.read_csv('data/analysis/qqq_googlefinance_closes_20260401_20260820.csv')
q['fecha']=pd.to_datetime(q['fecha'])
extra=pd.DataFrame([
 {'fecha':'2026-08-21','QQQ':713.4400024414062},
 {'fecha':'2026-08-24','QQQ':706.3200073242188},
 {'fecha':'2026-08-25','QQQ':710.72},
 {'fecha':'2026-08-26','QQQ':711.37},
])
extra['fecha']=pd.to_datetime(extra['fecha'])
q=pd.concat([q,extra],ignore_index=True).drop_duplicates('fecha',keep='last').sort_values('fecha')
q['ret_QQQ']=q['QQQ'].pct_change()
f=m.merge(q[['fecha','ret_QQQ']],on='fecha',how='inner')

df=vc.merge(f,on='fecha',how='inner').dropna(subset=['ret_vc','base_vc']+FACTORS).sort_values('fecha').reset_index(drop=True)

pred=[]
for i in range(30,len(df)):
    tr=df.iloc[i-30:i].copy(); row=df.iloc[i]
    per={}; rms={}
    for c in FACTORS:
        p,r=fit_quad(tr[c],tr['ret_vc'],row[c]); per[c]=p; rms[c]=r
    vals=np.array([per[c] for c in FACTORS],float)
    inv=np.array([1/max(rms[c],1e-12) for c in FACTORS],float); inv=inv/inv.sum()
    ret_mean=float(vals.mean())
    ret_median=float(np.median(vals))
    ret_w=float(np.dot(inv,vals))
    # control: regresion lineal de segundo nivel conjunta aditiva sobre retornos (sin interacciones)
    mats=[np.ones(len(tr))]; rv=[1.0]
    for c in FACTORS:
        x=tr[c].to_numpy(float); mu=x.mean(); sd=x.std(ddof=0) or 1.0
        u=(x-mu)/sd; z=(float(row[c])-mu)/sd
        mats += [u,u*u]; rv += [z,z*z]
    X=np.column_stack(mats); b=np.linalg.lstsq(X,tr['ret_vc'].to_numpy(float),rcond=None)[0]
    ret_joint=float(np.dot(np.asarray(rv,float),b))
    base=float(row.base_vc); actual=float(row.VC)
    rec={'fecha':row.fecha.strftime('%Y-%m-%d'),'VC':actual,'base_vc':base,
         'ret_actual':float(row.ret_vc),'ret_mean6':ret_mean,'ret_median6':ret_median,
         'ret_invrmse6':ret_w,'ret_joint_quad':ret_joint,
         'vc_mean6':base*(1+ret_mean),'vc_median6':base*(1+ret_median),
         'vc_invrmse6':base*(1+ret_w),'vc_joint_quad':base*(1+ret_joint),
         'train_start':tr.fecha.iloc[0].strftime('%Y-%m-%d'),'train_end':tr.fecha.iloc[-1].strftime('%Y-%m-%d')}
    for c in FACTORS: rec['retpred_'+c]=per[c]
    pred.append(rec)

p=pd.DataFrame(pred); last=p.tail(30).copy()
amap={str(r.get('fecha'))[:10]:float(r['vc_estimated']) for r in a.get('history_one_step',[]) if r.get('vc_estimated') is not None and r.get('actual_vc') is not None}
common=last[last.fecha.isin(amap)].copy(); common['A_vc']=common.fecha.map(amap)
res={
 'spec':'TRUE one-step Rolling30 on returns. Six separate quadratic regressions ret_VC~ret_factor+ret_factor^2; combine by mean/median/inverse train RMSE, then apply predicted return to prior official VC. Also joint additive quadratic return model control.',
 'dates':{'start':last.fecha.iloc[0] if len(last) else None,'end':last.fecha.iloc[-1] if len(last) else None,'n':len(last)},
 'metrics':{
   'mean6':metrics(last.VC,last.vc_mean6),'median6':metrics(last.VC,last.vc_median6),
   'invrmse6':metrics(last.VC,last.vc_invrmse6),'joint_quad':metrics(last.VC,last.vc_joint_quad),
 },
 'common_with_A':{
   'n':len(common),'A':metrics(common.VC,common.A_vc) if len(common) else None,
   'mean6':metrics(common.VC,common.vc_mean6) if len(common) else None,
   'median6':metrics(common.VC,common.vc_median6) if len(common) else None,
   'invrmse6':metrics(common.VC,common.vc_invrmse6) if len(common) else None,
   'joint_quad':metrics(common.VC,common.vc_joint_quad) if len(common) else None,
 },
 'recent_rows':p.tail(12).to_dict('records'),
 'last30_rows':last.to_dict('records')
}
OUT.parent.mkdir(exist_ok=True)
OUT.write_text(json.dumps(res,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(res,ensure_ascii=False,indent=2))