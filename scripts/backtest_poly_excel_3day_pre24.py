import json
from pathlib import Path
import numpy as np
import pandas as pd

FACTORS=['SPY','EEM','EPU','MCHI','USD_PEN','QQQ']
CUTOFF=pd.Timestamp('2026-08-24')
TRAIN_N=30
H=3


def met(y,p):
    y=np.asarray(y,float); p=np.asarray(p,float); e=p-y
    sse=float(np.sum(e*e)); sst=float(np.sum((y-y.mean())**2))
    r=float(np.corrcoef(y,p)[0,1]) if len(y)>1 and np.std(y)>0 and np.std(p)>0 else None
    return {
      'n':len(y),'pearson_r':r,'predictive_r2':float(1-sse/sst) if sst>0 else None,
      'mae':float(np.mean(np.abs(e))),'rmse':float(np.sqrt(np.mean(e*e))),
      'mape_pct':float(np.mean(np.abs(e/y))*100),'bias':float(np.mean(e))
    }

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

def predict(df,beta,stats,degree):
    mats=[np.ones(len(df))]
    for c in FACTORS:
        mu,sd=stats[c]; u=(df[c].astype(float).to_numpy()-mu)/sd
        for k in range(1,degree+1): mats.append(u**k)
    return np.column_stack(mats)@beta

# official VC from clean A history
mon=json.loads(Path('public/data/dual_rolling30_monitor.json').read_text(encoding='utf-8'))
rows=[]
for r in mon['models']['qqq']['history_one_step']:
    if r.get('actual_vc') is not None:
        rows.append((pd.Timestamp(str(r['fecha'])[:10]),float(r['actual_vc'])))
vc=pd.DataFrame(rows,columns=['fecha','VC']).drop_duplicates('fecha').sort_values('fecha')

m=pd.read_csv('data/rolling90/markets.csv'); m['fecha']=pd.to_datetime(m['fecha'])
m=m[['fecha','SPY','EEM','EPU','MCHI']]
fx=pd.read_csv('data/rolling90/bcrp_pd04638_cache.csv'); fx['fecha']=pd.to_datetime(fx['fecha'])
val=[c for c in fx.columns if c!='fecha'][0]; fx=fx[['fecha',val]].rename(columns={val:'USD_PEN'})
q=pd.read_csv('data/analysis/qqq_googlefinance_closes_20260401_20260820.csv'); q['fecha']=pd.to_datetime(q['fecha'])
extra=pd.DataFrame([
 {'fecha':pd.Timestamp('2026-08-21'),'QQQ':713.4400024414062},
 {'fecha':pd.Timestamp('2026-08-24'),'QQQ':706.3200073242188},
 {'fecha':pd.Timestamp('2026-08-25'),'QQQ':710.72},
 {'fecha':pd.Timestamp('2026-08-26'),'QQQ':711.37},
])
q=pd.concat([q,extra],ignore_index=True).drop_duplicates('fecha',keep='last')

df=vc.merge(m,on='fecha',how='left').merge(fx,on='fecha',how='left').merge(q,on='fecha',how='left')
df=df.dropna(subset=FACTORS).sort_values('fecha').reset_index(drop=True)
df=df[df.fecha < CUTOFF].reset_index(drop=True)

# Non-overlapping conceptual 3-day holdouts are not required; use every possible origin, each trains on prior 30 and predicts next 3 without retraining.
blocks=[]
all4=[]; all5=[]
for end_idx in range(TRAIN_N-1, len(df)-H):
    train=df.iloc[end_idx-TRAIN_N+1:end_idx+1].copy()
    test=df.iloc[end_idx+1:end_idx+1+H].copy()
    if len(test)<H or test.fecha.max()>=CUTOFF: continue
    cand=[]
    for d in range(1,5):
        b,s,r2,rank,cond=fit_poly(train,d); cand.append((r2,d,b,s,rank,cond))
    cand.sort(key=lambda z:(z[0],-z[1]),reverse=True)
    r2,d,b,s,rank,cond=cand[0]
    p=predict(test,b,s,d)
    # pure Excel objective through degree 5 as separate diagnostic
    cand5=[]
    for dd in range(1,6):
        bb,ss,rr,ra,co=fit_poly(train,dd); cand5.append((rr,dd,bb,ss,ra,co))
    cand5.sort(key=lambda z:(z[0],-z[1]),reverse=True)
    rr5,d5,b5,s5,rank5,cond5=cand5[0]; p5=predict(test,b5,s5,d5)
    br={'train_start':train.fecha.iloc[0].strftime('%Y-%m-%d'),'train_end':train.fecha.iloc[-1].strftime('%Y-%m-%d'),
        'selected_degree_1_4':d,'train_r2_1_4':r2,'rank_1_4':rank,'cond_1_4':cond,
        'selected_degree_1_5':d5,'train_r2_1_5':rr5,'rank_1_5':rank5,'cond_1_5':cond5,'predictions':[]}
    for j,(_,r) in enumerate(test.iterrows()):
        rec={'fecha':r.fecha.strftime('%Y-%m-%d'),'vc_sbs':float(r.VC),'vc_pred_order_le4':float(p[j]),'error_pct_le4':float((p[j]/r.VC-1)*100),
             'vc_pred_order_le5':float(p5[j]),'error_pct_le5':float((p5[j]/r.VC-1)*100),'horizon':j+1}
        br['predictions'].append(rec); all4.append((float(r.VC),float(p[j]))); all5.append((float(r.VC),float(p5[j])))
    blocks.append(br)

# Final block immediately before 24: train through 18, predict 19/20/21 if available.
final_block=None
for b in blocks:
    if b['predictions'][-1]['fecha']=='2026-08-21': final_block=b

res={'spec':'Backtest Excel-style polynomial levels. Each origin uses prior 30 known SBS VC + Model A factor levels; choose degree maximizing in-sample R2; then freeze equation and predict next 3 valid SBS dates without retraining. All test dates strictly before 2026-08-24.',
     'factors':FACTORS,'train_n':TRAIN_N,'holdout_days':H,'n_blocks':len(blocks),
     'aggregate_order_1_4':met([x[0] for x in all4],[x[1] for x in all4]) if all4 else None,
     'aggregate_order_1_5':met([x[0] for x in all5],[x[1] for x in all5]) if all5 else None,
     'final_block_pre24':final_block,'blocks':blocks}
Path('analysis').mkdir(exist_ok=True)
Path('analysis/backtest_poly_excel_3day_pre24.json').write_text(json.dumps(res,indent=2,ensure_ascii=False),encoding='utf-8')
print(json.dumps(res,indent=2,ensure_ascii=False))
