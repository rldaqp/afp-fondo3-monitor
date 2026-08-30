import json
from pathlib import Path
import numpy as np
import pandas as pd

# exact same logic as previous Excel-style test: fit degree-2 additive polynomial on the same latest 30 observations and score in-sample.
# Model A factors: SPY, EEM, EPU, MCHI, USD/PEN (PD04638 cache used by visor), QQQ.

def metrics(y,p):
    y=np.asarray(y,float); p=np.asarray(p,float); e=p-y
    sse=float(np.sum(e*e)); sst=float(np.sum((y-y.mean())**2))
    r=float(np.corrcoef(y,p)[0,1])
    return dict(n=len(y),pearson_r=r,corr2=r*r,predictive_r2=float(1-sse/sst),mae=float(np.mean(np.abs(e))),rmse=float(np.sqrt(np.mean(e*e))),mape_pct=float(np.mean(np.abs(e/y))*100),bias=float(np.mean(e)))

def design(df, cols):
    mats=[np.ones(len(df))]
    stats={}
    for c in cols:
        x=df[c].astype(float).to_numpy(); mu=float(x.mean()); sd=float(x.std(ddof=0)) or 1.0
        u=(x-mu)/sd; mats += [u,u*u]; stats[c]=(mu,sd)
    return np.column_stack(mats),stats

# Actual VC series from current clean Model A historical one-step rows, which carry actual_vc on the exact valid dates.
mon=json.loads(Path('public/data/dual_rolling30_monitor.json').read_text(encoding='utf-8'))
a=mon['models']['qqq']
rows=[]
for r in a.get('history_one_step',[]):
    if r.get('actual_vc') is not None:
        rows.append((str(r['fecha'])[:10],float(r['actual_vc'])))
vc=pd.DataFrame(rows,columns=['fecha','VC']).drop_duplicates('fecha').sort_values('fecha')
# exact latest 30 valid dates
vc=vc.tail(30).copy()
vc['fecha']=pd.to_datetime(vc['fecha'])

m=pd.read_csv('data/rolling90/markets.csv')
m['fecha']=pd.to_datetime(m['fecha'])
m=m[['fecha','SPY','EEM','EPU','MCHI']].copy()

fx=pd.read_csv('data/rolling90/bcrp_pd04638_cache.csv')
fx['fecha']=pd.to_datetime(fx['fecha'])
# tolerate cache column names
vcols=[c for c in fx.columns if c!='fecha']
fx=fx[['fecha',vcols[0]]].rename(columns={vcols[0]:'USD_PEN'})

q=pd.read_csv('data/analysis/qqq_googlefinance_closes_20260401_20260820.csv')
q['fecha']=pd.to_datetime(q['fecha'])
# audited reliable closes after 20/08
extra=pd.DataFrame([
 {'fecha':pd.Timestamp('2026-08-21'),'QQQ':713.4400024414062},
 {'fecha':pd.Timestamp('2026-08-24'),'QQQ':706.3200073242188},
 {'fecha':pd.Timestamp('2026-08-25'),'QQQ':710.72},
 {'fecha':pd.Timestamp('2026-08-26'),'QQQ':711.37},
])
q=pd.concat([q,extra],ignore_index=True).drop_duplicates('fecha',keep='last')

df=vc.merge(m,on='fecha',how='left').merge(fx,on='fecha',how='left').merge(q,on='fecha',how='left')
cols=['SPY','EEM','EPU','MCHI','USD_PEN','QQQ']
missing=df[df[cols].isna().any(axis=1)]
if len(missing):
    raise RuntimeError('Missing factors: '+missing[['fecha']+cols].to_string(index=False))

X,stats=design(df,cols); y=df.VC.to_numpy(float)
beta=np.linalg.lstsq(X,y,rcond=None)[0]; pred=X@beta
out=df[['fecha','VC']].copy(); out['poly_A_vc']=pred; out['error']=pred-y; out['error_pct']=(pred/y-1)*100
res={
 'spec':'In-sample latest 30, degree-2 additive polynomial in levels, no interactions; Model A tickers SPY,EEM,EPU,MCHI,USD/PEN PD04638PD,QQQ',
 'dates':{'start':df.fecha.min().strftime('%Y-%m-%d'),'end':df.fecha.max().strftime('%Y-%m-%d'),'n':len(df)},
 'metrics':metrics(y,pred),
 'coefficients':beta.tolist(),
 'rows':[{**r,'fecha':r['fecha'].strftime('%Y-%m-%d')} for r in out.to_dict('records')]
}
Path('analysis').mkdir(exist_ok=True)
Path('analysis/test_poly_model_a_last30.json').write_text(json.dumps(res,indent=2,ensure_ascii=False),encoding='utf-8')
print(json.dumps(res,indent=2,ensure_ascii=False))
