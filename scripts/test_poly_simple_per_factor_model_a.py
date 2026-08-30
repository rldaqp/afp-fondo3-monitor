import json
from pathlib import Path
import numpy as np
import pandas as pd

OUT=Path('analysis/test_poly_simple_per_factor_model_a.json')
FACTORS=['SPY','EEM','EPU','MCHI','USD_PEN','QQQ']


def metrics(y,p):
    y=np.asarray(y,float); p=np.asarray(p,float); e=p-y
    sse=float(np.sum(e*e)); sst=float(np.sum((y-y.mean())**2))
    r=float(np.corrcoef(y,p)[0,1]) if len(y)>1 else None
    return {'n':int(len(y)),'pearson_r':r,'corr2':None if r is None else r*r,
            'predictive_r2':float(1-sse/sst) if sst>0 else None,
            'mae':float(np.mean(np.abs(e))),'rmse':float(np.sqrt(np.mean(e*e))),
            'mape_pct':float(np.mean(np.abs(e/y))*100),'bias':float(np.mean(e))}


def quad_predict(train,row,c):
    x=train[c].astype(float).to_numpy(); y=train.VC.astype(float).to_numpy()
    mu=float(x.mean()); sd=float(x.std(ddof=0)) or 1.0
    u=(x-mu)/sd; t=(float(row[c])-mu)/sd
    X=np.column_stack([np.ones(len(train)),u,u*u])
    b=np.linalg.lstsq(X,y,rcond=None)[0]
    return float(np.dot([1,t,t*t],b))

# VC SBS actuals from current monitor history, which has corrected official actual_vc values
mon=json.loads(Path('public/data/dual_rolling30_monitor.json').read_text(encoding='utf-8'))
a=mon['models']['qqq']
actual={}
for r in a.get('history_one_step',[]):
    d=str(r.get('fecha',''))[:10]; v=r.get('actual_vc')
    if v is not None: actual[d]=float(v)
# add latest known actuals if present elsewhere in model history
for key in ['history_operational']:
    for r in a.get(key,[]):
        d=str(r.get('fecha',''))[:10]; v=r.get('actual_vc')
        if v is not None and d not in actual: actual[d]=float(v)
vc=pd.DataFrame([(pd.Timestamp(d),v) for d,v in actual.items()],columns=['fecha','VC']).drop_duplicates('fecha').sort_values('fecha')

m=pd.read_csv('data/rolling90/markets.csv'); m['fecha']=pd.to_datetime(m['fecha'])
m=m[['fecha','SPY','EEM','EPU','MCHI','USD_PEN']].copy()
q=pd.read_csv('data/analysis/qqq_googlefinance_closes_20260401_20260820.csv'); q['fecha']=pd.to_datetime(q['fecha'])
extra=pd.DataFrame([
 {'fecha':'2026-08-21','QQQ':713.4400024414062},
 {'fecha':'2026-08-24','QQQ':706.3200073242188},
 {'fecha':'2026-08-25','QQQ':710.72},
 {'fecha':'2026-08-26','QQQ':711.37},
]); extra['fecha']=pd.to_datetime(extra['fecha'])
q=pd.concat([q,extra],ignore_index=True).drop_duplicates('fecha',keep='last').sort_values('fecha')

df=vc.merge(m,on='fecha',how='inner').merge(q,on='fecha',how='inner').dropna(subset=['VC']+FACTORS).sort_values('fecha').reset_index(drop=True)

rows=[]
for i in range(30,len(df)):
    tr=df.iloc[i-30:i].copy(); row=df.iloc[i]
    preds={c:quad_predict(tr,row,c) for c in FACTORS}
    vals=np.array(list(preds.values()),float)
    # Rule 1: equal-weight mean of six independent simple quadratic estimates
    mean6=float(vals.mean())
    # Rule 2: median, robust simple combination
    med6=float(np.median(vals))
    # Rule 3: inverse in-sample RMSE weighting computed only on training window for each factor
    rms=[]
    for c in FACTORS:
        x=tr[c].astype(float).to_numpy(); y=tr.VC.astype(float).to_numpy(); mu=float(x.mean()); sd=float(x.std(ddof=0)) or 1.0
        u=(x-mu)/sd; X=np.column_stack([np.ones(len(tr)),u,u*u]); b=np.linalg.lstsq(X,y,rcond=None)[0]
        fit=X@b; rm=float(np.sqrt(np.mean((fit-y)**2))); rms.append(max(rm,1e-8))
    w=1/np.square(np.asarray(rms)); w=w/w.sum(); invrmse=float(np.dot(w,vals))
    rec={'fecha':row.fecha.strftime('%Y-%m-%d'),'VC':float(row.VC),'mean6':mean6,'median6':med6,'invrmse6':invrmse,
         'train_start':tr.fecha.iloc[0].strftime('%Y-%m-%d'),'train_end':tr.fecha.iloc[-1].strftime('%Y-%m-%d')}
    for c,v in preds.items(): rec['pred_'+c]=float(v)
    for c,ww in zip(FACTORS,w): rec['w_'+c]=float(ww)
    rows.append(rec)

p=pd.DataFrame(rows); last30=p.tail(30).copy()
# Current A clean/adaptive same dates
amap={str(r.get('fecha'))[:10]:float(r['vc_estimated']) for r in a.get('history_one_step',[]) if r.get('vc_estimated') is not None and r.get('actual_vc') is not None}
common=last30[last30.fecha.isin(amap)].copy(); common['A_vc']=common.fecha.map(amap)

out={
 'spec':'TRUE one-step Rolling30. Six separate univariate quadratic regressions VC~x+x^2 for SPY,EEM,EPU,MCHI,USD_PEN,QQQ; target never used in fit. Combination tested: equal mean, median, inverse-training-RMSE weighted mean.',
 'dates':{'start':last30.fecha.iloc[0],'end':last30.fecha.iloc[-1],'n':len(last30)},
 'metrics':{
   'mean6':metrics(last30.VC,last30.mean6),
   'median6':metrics(last30.VC,last30.median6),
   'invrmse6':metrics(last30.VC,last30.invrmse6),
   'individual':{c:metrics(last30.VC,last30['pred_'+c]) for c in FACTORS}
 },
 'common_with_A':{
   'n':len(common),'start':common.fecha.iloc[0] if len(common) else None,'end':common.fecha.iloc[-1] if len(common) else None,
   'mean6':metrics(common.VC,common.mean6) if len(common) else None,
   'median6':metrics(common.VC,common.median6) if len(common) else None,
   'invrmse6':metrics(common.VC,common.invrmse6) if len(common) else None,
   'A':metrics(common.VC,common.A_vc) if len(common) else None
 },
 'recent_rows':last30.tail(10).to_dict('records'),
 'rows':last30.to_dict('records')
}
OUT.parent.mkdir(exist_ok=True)
OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(out,ensure_ascii=False,indent=2))
