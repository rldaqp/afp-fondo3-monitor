import json
from pathlib import Path
import numpy as np
import pandas as pd

FACTORS=['SPY','EEM','EPU','MCHI','USD_PEN','QQQ']
TARGETS=[pd.Timestamp('2026-08-19'),pd.Timestamp('2026-08-20'),pd.Timestamp('2026-08-21')]
TRAIN_N=30
MAX_DEG=4

def fit_poly(train, degree):
    mats=[np.ones(len(train))]; stats={}
    for c in FACTORS:
        x=train[c].astype(float).to_numpy(); mu=float(x.mean()); sd=float(x.std(ddof=0)) or 1.0
        u=(x-mu)/sd; stats[c]=(mu,sd)
        for k in range(1,degree+1): mats.append(u**k)
    X=np.column_stack(mats); y=train.VC.to_numpy(float)
    beta=np.linalg.lstsq(X,y,rcond=None)[0]
    pred=X@beta
    sse=float(np.sum((pred-y)**2)); sst=float(np.sum((y-y.mean())**2))
    r2=float(1-sse/sst)
    return beta,stats,r2,int(np.linalg.matrix_rank(X)),float(np.linalg.cond(X))

def predict(row,beta,stats,degree):
    vals=[1.0]
    for c in FACTORS:
        mu,sd=stats[c]; u=(float(row[c])-mu)/sd
        for k in range(1,degree+1): vals.append(u**k)
    return float(np.dot(np.array(vals),beta))

mon=json.loads(Path('public/data/dual_rolling30_monitor.json').read_text(encoding='utf-8'))
rows=[]
for r in mon['models']['qqq']['history_one_step']:
    if r.get('actual_vc') is not None:
        rows.append((pd.Timestamp(str(r['fecha'])[:10]),float(r['actual_vc'])))
vc=pd.DataFrame(rows,columns=['fecha','VC']).drop_duplicates('fecha').sort_values('fecha')

m=pd.read_csv('data/rolling90/markets.csv'); m['fecha']=pd.to_datetime(m['fecha']); m=m[['fecha','SPY','EEM','EPU','MCHI']]
fx=pd.read_csv('data/rolling90/bcrp_pd04638_cache.csv'); fx['fecha']=pd.to_datetime(fx['fecha']); val=[c for c in fx.columns if c!='fecha'][0]; fx=fx[['fecha',val]].rename(columns={val:'USD_PEN'})
q=pd.read_csv('data/analysis/qqq_googlefinance_closes_20260401_20260820.csv'); q['fecha']=pd.to_datetime(q['fecha'])
q=pd.concat([q,pd.DataFrame([{'fecha':pd.Timestamp('2026-08-21'),'QQQ':713.4400024414062}])],ignore_index=True).drop_duplicates('fecha',keep='last')

df=vc.merge(m,on='fecha').merge(fx,on='fecha').merge(q,on='fecha').dropna(subset=FACTORS).sort_values('fecha').reset_index(drop=True)

out=[]
for t in TARGETS:
    test=df[df.fecha==t]
    if test.empty: continue
    prior=df[df.fecha<t].tail(TRAIN_N)
    if len(prior)!=TRAIN_N: raise RuntimeError(f'Need 30 prior rows for {t.date()}')
    candidates=[]
    for d in range(1,MAX_DEG+1):
        b,s,r2,rank,cond=fit_poly(prior,d)
        candidates.append((r2,d,b,s,rank,cond))
    candidates.sort(key=lambda z:(z[0],-z[1]), reverse=True)
    r2,d,b,s,rank,cond=candidates[0]
    pred=predict(test.iloc[0],b,s,d)
    actual=float(test.iloc[0].VC)
    out.append({
      'fecha':t.strftime('%Y-%m-%d'),'train_start':prior.fecha.iloc[0].strftime('%Y-%m-%d'),'train_end':prior.fecha.iloc[-1].strftime('%Y-%m-%d'),
      'selected_degree':d,'train_r2':r2,'rank':rank,'condition_number':cond,
      'vc_sbs':actual,'vc_pred':pred,'error_abs':pred-actual,'error_pct':(pred/actual-1)*100
    })

y=np.array([r['vc_sbs'] for r in out]); p=np.array([r['vc_pred'] for r in out]); e=p-y
res={'spec':'TRUE one-step Excel-style backtest: for each target day use only prior 30 SBS VC + factor levels, select degree 1..4 by max in-sample R2, predict only that next day, then roll/retrain for following target.',
     'targets':[r['fecha'] for r in out],'rows':out,
     'summary':{'mae':float(np.mean(np.abs(e))),'rmse':float(np.sqrt(np.mean(e*e))),'mape_pct':float(np.mean(np.abs(e/y))*100),'bias':float(np.mean(e))}}
Path('analysis/backtest_poly_excel_one_step_pre24.json').write_text(json.dumps(res,indent=2,ensure_ascii=False),encoding='utf-8')
print(json.dumps(res,indent=2,ensure_ascii=False))
