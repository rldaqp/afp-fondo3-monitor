import json
from pathlib import Path
import numpy as np
import pandas as pd

COLS=['SPY','EEM','EPU','MCHI','USD_PEN','QQQ']
DEGREES=range(1,9)


def metrics(y,p):
    y=np.asarray(y,float); p=np.asarray(p,float); e=p-y
    sse=float(np.sum(e*e)); sst=float(np.sum((y-y.mean())**2))
    r=float(np.corrcoef(y,p)[0,1]) if np.std(p)>0 else None
    return {
        'n':int(len(y)),
        'pearson_r':r,
        'corr2':None if r is None else r*r,
        'r2':float(1-sse/sst) if sst>0 else None,
        'mae':float(np.mean(np.abs(e))),
        'rmse':float(np.sqrt(np.mean(e*e))),
        'mape_pct':float(np.mean(np.abs(e/y))*100),
        'bias':float(np.mean(e)),
        'sse':sse,
    }


def design(df, cols, degree):
    mats=[np.ones(len(df))]
    for c in cols:
        x=df[c].astype(float).to_numpy()
        mu=float(x.mean()); sd=float(x.std(ddof=0)) or 1.0
        u=(x-mu)/sd
        for p in range(1,degree+1):
            mats.append(u**p)
    return np.column_stack(mats)

# Exact same 30-date sample used in prior Model A polynomial test
mon=json.loads(Path('public/data/dual_rolling30_monitor.json').read_text(encoding='utf-8'))
a=mon['models']['qqq']
rows=[]
for r in a.get('history_one_step',[]):
    if r.get('actual_vc') is not None:
        rows.append((str(r['fecha'])[:10],float(r['actual_vc'])))
vc=pd.DataFrame(rows,columns=['fecha','VC']).drop_duplicates('fecha').sort_values('fecha').tail(30)
vc['fecha']=pd.to_datetime(vc['fecha'])

m=pd.read_csv('data/rolling90/markets.csv'); m['fecha']=pd.to_datetime(m['fecha'])
m=m[['fecha','SPY','EEM','EPU','MCHI']].copy()

fx=pd.read_csv('data/rolling90/bcrp_pd04638_cache.csv'); fx['fecha']=pd.to_datetime(fx['fecha'])
vcols=[c for c in fx.columns if c!='fecha']; fx=fx[['fecha',vcols[0]]].rename(columns={vcols[0]:'USD_PEN'})

q=pd.read_csv('data/analysis/qqq_googlefinance_closes_20260401_20260820.csv'); q['fecha']=pd.to_datetime(q['fecha'])
extra=pd.DataFrame([
 {'fecha':pd.Timestamp('2026-08-21'),'QQQ':713.4400024414062},
 {'fecha':pd.Timestamp('2026-08-24'),'QQQ':706.3200073242188},
 {'fecha':pd.Timestamp('2026-08-25'),'QQQ':710.72},
 {'fecha':pd.Timestamp('2026-08-26'),'QQQ':711.37},
])
q=pd.concat([q,extra],ignore_index=True).drop_duplicates('fecha',keep='last')

df=vc.merge(m,on='fecha',how='left').merge(fx,on='fecha',how='left').merge(q,on='fecha',how='left')
if df[COLS].isna().any(axis=1).any():
    raise RuntimeError('Missing factors:\n'+df[df[COLS].isna().any(axis=1)][['fecha']+COLS].to_string(index=False))

y=df.VC.to_numpy(float)
results=[]
preds={}
for degree in DEGREES:
    X=design(df,COLS,degree)
    beta,resid,rank,svals=np.linalg.lstsq(X,y,rcond=None)
    pred=X@beta
    met=metrics(y,pred)
    met.update({
        'degree':degree,
        'n_parameters':int(X.shape[1]),
        'matrix_rank':int(rank),
        'condition_number':float(svals[0]/svals[-1]) if len(svals) and svals[-1]>0 else None,
    })
    results.append(met)
    preds[degree]=pred

# Optimize exactly by maximum in-sample R2; for ties within numerical tolerance choose lower degree
maxr=max(r['r2'] for r in results)
best=min((r for r in results if maxr-r['r2'] <= 1e-10), key=lambda r:r['degree'])
bdeg=best['degree']; bp=preds[bdeg]
rowsout=[]
for i,row in df.iterrows():
    rowsout.append({
        'fecha':row.fecha.strftime('%Y-%m-%d'),
        'VC':float(row.VC),
        'best_fit_vc':float(bp[i]),
        'error':float(bp[i]-row.VC),
        'error_pct':float((bp[i]/row.VC-1)*100),
    })

res={
 'spec':'Excel-style search of polynomial order on same latest 30 observations. Additive powers per Model A factor, no interactions. Objective=max in-sample R2.',
 'factors':COLS,
 'dates':{'start':df.fecha.min().strftime('%Y-%m-%d'),'end':df.fecha.max().strftime('%Y-%m-%d'),'n':int(len(df))},
 'orders':results,
 'best_by_r2':best,
 'best_rows':rowsout,
 'warning':'With 30 observations and 6 factors, degree 5 has 31 coefficients including intercept, so the model has enough parameters to interpolate the sample. R2 near 1 at degree >=5 is therefore mechanical overfit, even though it is the literal winner under max-R2-only selection.'
}
Path('analysis').mkdir(exist_ok=True)
Path('analysis/test_poly_orders_model_a_last30.json').write_text(json.dumps(res,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(res,ensure_ascii=False,indent=2))
