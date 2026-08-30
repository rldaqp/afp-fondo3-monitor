import json
from pathlib import Path
import numpy as np
import pandas as pd

OUT=Path('analysis/test_poly_model_a_rolling30_oos.json')
COLS=['SPY','EEM','EPU','MCHI','USD_PEN','QQQ']


def metrics(y,p):
    y=np.asarray(y,float); p=np.asarray(p,float); e=p-y
    sse=float(np.sum(e*e)); sst=float(np.sum((y-y.mean())**2))
    r=float(np.corrcoef(y,p)[0,1]) if len(y)>1 else None
    return {'n':int(len(y)),'pearson_r':r,'corr2':None if r is None else r*r,
            'predictive_r2':float(1-sse/sst) if sst>0 else None,
            'mae':float(np.mean(np.abs(e))),'rmse':float(np.sqrt(np.mean(e*e))),
            'mape_pct':float(np.mean(np.abs(e/y))*100),'bias':float(np.mean(e))}


def fit_predict(train,row):
    mats=[np.ones(len(train))]; rv=[1.0]
    for c in COLS:
        x=train[c].astype(float).to_numpy()
        mu=float(x.mean()); sd=float(x.std(ddof=0)) or 1.0
        u=(x-mu)/sd; t=(float(row[c])-mu)/sd
        mats += [u,u*u]; rv += [t,t*t]
    X=np.column_stack(mats); y=train.VC.astype(float).to_numpy()
    beta=np.linalg.lstsq(X,y,rcond=None)[0]
    return float(np.dot(np.asarray(rv),beta))

# SBS VC history from visor series
s=json.loads(Path('public/data/series.json').read_text(encoding='utf-8'))
rows=s if isinstance(s,list) else (s.get('series') or s.get('data') or s.get('rows') or [])
vcrows=[]
for r in rows:
    d=str(r.get('fecha',''))[:10]
    try:v=float(r.get('vc'))
    except:continue
    if d and v>0: vcrows.append((pd.Timestamp(d),v))
vc=pd.DataFrame(vcrows,columns=['fecha','VC']).drop_duplicates('fecha').sort_values('fecha')

# Model A factors
m=pd.read_csv('data/rolling90/markets.csv')
m['fecha']=pd.to_datetime(m['fecha'])
keep=['fecha','SPY','EEM','EPU','MCHI','USD_PEN']
m=m[keep].copy()

q=pd.read_csv('data/analysis/qqq_googlefinance_closes_20260401_20260820.csv')
q['fecha']=pd.to_datetime(q['fecha'])
# audited/known closes after 20 Aug
extra=pd.DataFrame([
 {'fecha':'2026-08-21','QQQ':713.4400024414062},
 {'fecha':'2026-08-24','QQQ':706.3200073242188},
 {'fecha':'2026-08-25','QQQ':710.72},
 {'fecha':'2026-08-26','QQQ':711.37},
])
extra['fecha']=pd.to_datetime(extra['fecha'])
q=pd.concat([q,extra],ignore_index=True).drop_duplicates('fecha',keep='last').sort_values('fecha')

f=m.merge(q,on='fecha',how='inner')
df=vc.merge(f,on='fecha',how='inner').dropna(subset=['VC']+COLS).sort_values('fecha').reset_index(drop=True)

pred=[]
for i in range(30,len(df)):
    tr=df.iloc[i-30:i].copy(); row=df.iloc[i]
    p=fit_predict(tr,row)
    pred.append({'fecha':row.fecha.strftime('%Y-%m-%d'),'VC':float(row.VC),'poly_oos_vc':p,
                 'error':p-float(row.VC),'error_pct':(p/float(row.VC)-1)*100,
                 'train_start':tr.fecha.iloc[0].strftime('%Y-%m-%d'),
                 'train_end':tr.fecha.iloc[-1].strftime('%Y-%m-%d')})
pdff=pd.DataFrame(pred)
last30=pdff.tail(30).copy()

# clean A same dates
mon=json.loads(Path('public/data/dual_rolling30_monitor.json').read_text(encoding='utf-8'))
a=mon['models']['qqq']
amap={str(r.get('fecha'))[:10]:float(r['vc_estimated']) for r in a.get('history_one_step',[]) if r.get('vc_estimated') is not None and r.get('actual_vc') is not None}
common=last30[last30.fecha.isin(amap)].copy(); common['A_vc']=common.fecha.map(amap)

res={'spec':'TRUE one-step OOS Rolling 30, VC in levels, degree-2 additive polynomial, no interactions; factors SPY,EEM,EPU,MCHI,USD/PEN PD04638PD,QQQ. Each target uses exactly the preceding 30 complete rows and never uses target VC in fit.',
     'data':{'first':df.fecha.min().strftime('%Y-%m-%d'),'last':df.fecha.max().strftime('%Y-%m-%d'),'n':len(df)},
     'last30_dates':{'start':last30.fecha.iloc[0] if len(last30) else None,'end':last30.fecha.iloc[-1] if len(last30) else None},
     'poly_oos_last30':metrics(last30.VC,last30.poly_oos_vc),
     'common_with_A':{'n':len(common),'start':common.fecha.iloc[0] if len(common) else None,'end':common.fecha.iloc[-1] if len(common) else None,
                      'poly':metrics(common.VC,common.poly_oos_vc) if len(common) else None,
                      'A_clean':metrics(common.VC,common.A_vc) if len(common) else None},
     'rows':last30.to_dict('records')}
OUT.parent.mkdir(exist_ok=True)
OUT.write_text(json.dumps(res,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(res,ensure_ascii=False,indent=2))