from __future__ import annotations

import json
from pathlib import Path
import numpy as np
import pandas as pd
import yfinance as yf

ROOT=Path(__file__).resolve().parents[1]
R90=ROOT/'data'/'rolling90'
ANA=ROOT/'data'/'analysis'
OUT=ROOT/'analysis'/'profuturo_bvl_influence.json'

BASE=['ret_SPY','ret_EEM','ret_MCHI','ret_USD_PEN','ret_QQQ']
MODELS={
 'NO_PERU':BASE,
 'EPU_ONLY':BASE+['ret_EPU'],
 'BVL_ONLY':BASE+['ret_SPBLSCUP'],
 'EPU_PLUS_BVL':BASE+['ret_EPU','ret_SPBLSCUP'],
}
WINDOWS=[20,25,30]
HORIZONS=[30,60,90]


def read_csv(p):
 d=pd.read_csv(p); d['fecha']=pd.to_datetime(d['fecha'],errors='coerce').dt.normalize()
 return d.dropna(subset=['fecha']).sort_values('fecha').drop_duplicates('fecha',keep='last').reset_index(drop=True)

def yahoo_ret(ticker,start='2026-02-01',end='2026-08-29'):
 r=yf.download(ticker,start=start,end=end,auto_adjust=False,actions=False,progress=False,threads=False)
 if isinstance(r.columns,pd.MultiIndex): s=pd.to_numeric(r[('Close',ticker)] if ('Close',ticker) in r.columns else r.xs('Close',axis=1,level=0).iloc[:,0],errors='coerce')
 else: s=pd.to_numeric(r['Close'],errors='coerce')
 s=s.dropna(); idx=pd.to_datetime(s.index)
 if getattr(idx,'tz',None) is not None: idx=idx.tz_localize(None)
 d=pd.DataFrame({'fecha':idx.normalize(),'close':s.to_numpy(float)}).sort_values('fecha').drop_duplicates('fecha',keep='last')
 d['ret_QQQ']=d.close.pct_change(fill_method=None); return d[['fecha','ret_QQQ']]

def vif_values(xdf):
 vals={}; X=xdf.to_numpy(float)
 for j,c in enumerate(xdf.columns):
  y=X[:,j]; others=np.delete(X,j,axis=1)
  Z=np.c_[np.ones(len(y)),others]
  b=np.linalg.lstsq(Z,y,rcond=None)[0]; e=y-Z@b
  sse=float(e@e); sst=float(((y-y.mean())**2).sum())
  r2=1-sse/sst if sst>0 else np.nan
  vals[c]=float(1/(1-r2)) if np.isfinite(r2) and r2<0.999999999 else float('inf')
 return vals

def fit(train,features):
 X=np.c_[np.ones(len(train)),train[features].to_numpy(float)]
 y=train.ret_target.to_numpy(float)
 b=np.linalg.lstsq(X,y,rcond=None)[0]
 return b

def pred_rows(frame,sbs,features,n):
 rows=[]
 for i in range(n,len(frame)):
  tr=frame.iloc[i-n:i]
  cur=frame.iloc[i]
  b=fit(tr,features)
  pr=float(np.r_[1.,cur[features].to_numpy(float)]@b)
  prev=sbs[sbs.fecha.lt(cur.fecha)].tail(1)
  if prev.empty: continue
  base=float(prev.valor_cuota.iloc[0]); est=base*(1+pr)
  rows.append({'fecha':cur.fecha,'actual_vc':float(cur.valor_cuota),'est':est,'pred_ret':pr,
               'beta_bvl':float(b[1+features.index('ret_SPBLSCUP')]) if 'ret_SPBLSCUP' in features else None})
 return pd.DataFrame(rows)

def metrics(d):
 y=d.actual_vc.to_numpy(float); p=d.est.to_numpy(float); e=p-y
 corr=float(np.corrcoef(y,p)[0,1]); sse=float((e**2).sum()); sst=float(((y-y.mean())**2).sum())
 return {'n':len(d),'start':d.fecha.iloc[0].date().isoformat(),'end':d.fecha.iloc[-1].date().isoformat(),
         'pearson_r':corr,'predictive_r2':float(1-sse/sst),'mae':float(np.mean(np.abs(e))),
         'rmse':float(np.sqrt(np.mean(e**2))),'mape_pct':float(np.mean(np.abs(e/y))*100),'bias':float(np.mean(e))}

def main():
 sbs=read_csv(R90/'sbs_profuturo_f3.csv'); sbs['valor_cuota']=pd.to_numeric(sbs.valor_cuota,errors='coerce'); sbs=sbs.dropna(subset=['valor_cuota']); sbs['ret_target']=sbs.valor_cuota.pct_change(fill_method=None)
 m=read_csv(R90/'markets.csv')
 q=yahoo_ret('QQQ')
 sp=read_csv(ANA/'googlefinance_alt_6030_returns_20260303_20260820.csv')[['fecha','ret_SPBLSCUP']]
 # Extensión verificada del índice local tras el 20/08; retornos calculados de cierres 446.70, 460.43, 459.23, 464.16, 462.25.
 extra=pd.DataFrame({'fecha':pd.to_datetime(['2026-08-21','2026-08-24','2026-08-25','2026-08-26']),
                     'ret_SPBLSCUP':[460.43/446.70-1,459.23/460.43-1,464.16/459.23-1,462.25/464.16-1]})
 sp=pd.concat([sp,extra],ignore_index=True).sort_values('fecha').drop_duplicates('fecha',keep='last')
 cols=['fecha','ret_SPY','ret_EEM','ret_EPU','ret_MCHI','ret_USD_PEN']
 f=sbs[['fecha','valor_cuota','ret_target']].merge(m[cols],on='fecha',how='inner').merge(q,on='fecha',how='inner').merge(sp,on='fecha',how='inner')
 allf=sorted(set(sum(MODELS.values(),[])))
 f=f.dropna(subset=['ret_target',*allf]).sort_values('fecha').reset_index(drop=True)
 payload={'purpose':'Medir influencia marginal de la BVL (SPBLSCUP) sobre el retorno/VC de Profuturo Fondo 3 controlando USA, emergentes, China, Nasdaq y USD/PEN.',
          'interpretation':'beta_bvl es sensibilidad estadística, no peso contable de cartera.', 'models':MODELS,'windows':{}}
 for n in WINDOWS:
  preds={k:pred_rows(f,sbs,v,n) for k,v in MODELS.items()}
  common=set.intersection(*(set(x.fecha) for x in preds.values()))
  common=sorted(common)
  wb={}
  for h in HORIZONS:
   if len(common)<h: wb[str(h)]={'available':False,'n_available':len(common)}; continue
   dates=set(common[-h:]); block={}
   for k,d in preds.items(): block[k]=metrics(d[d.fecha.isin(dates)].sort_values('fecha').reset_index(drop=True))
   block['incremental_r2_BVL_vs_NO_PERU']=block['BVL_ONLY']['predictive_r2']-block['NO_PERU']['predictive_r2']
   block['incremental_r2_BVL_given_EPU']=block['EPU_PLUS_BVL']['predictive_r2']-block['EPU_ONLY']['predictive_r2']
   wb[str(h)]=block
  payload['windows'][f'R{n}']=wb
 # Current rolling betas and exact attribution on 24/08 using each window.
 target=pd.Timestamp('2026-08-24'); idx=f.index[f.fecha.eq(target)]
 payload['attribution_2026_08_24']={}
 if len(idx):
  i=int(idx[0]); cur=f.iloc[i]; actual_ret=float(cur.ret_target)
  for n in WINDOWS:
   if i<n: continue
   tr=f.iloc[i-n:i]
   row={'actual_return':actual_ret,'factor_returns':{c:float(cur[c]) for c in allf}}
   for name,features in MODELS.items():
    b=fit(tr,features); contrib={features[j]:float(b[j+1]*cur[features[j]]) for j in range(len(features))}
    pred=float(b[0]+sum(contrib.values()))
    rec={'intercept':float(b[0]),'predicted_return':pred,'coefficients':{features[j]:float(b[j+1]) for j in range(len(features))},'contributions':contrib,'vif':vif_values(tr[features])}
    if 'ret_SPBLSCUP' in features:
     rec['beta_bvl']=rec['coefficients']['ret_SPBLSCUP']; rec['bvl_contribution_pp']=100*contrib['ret_SPBLSCUP']; rec['bvl_share_of_abs_predicted_return_pct']=float(100*abs(contrib['ret_SPBLSCUP'])/abs(pred)) if pred else None
    row[name]=rec
   payload['attribution_2026_08_24'][f'R{n}']=row
 OUT.parent.mkdir(parents=True,exist_ok=True); OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8'); print(json.dumps(payload,ensure_ascii=False,indent=2))

if __name__=='__main__': main()
