from __future__ import annotations
import json
from pathlib import Path
import numpy as np, pandas as pd
ROOT=Path(__file__).resolve().parents[1]
FIXED=ROOT/'public/data/fixed_models_2026.csv'; MARKETS=ROOT/'data/rolling90/markets.csv'
OUT=ROOT/'analysis/filtered_sign_alpha_summary.csv'; DETAIL=ROOT/'analysis/filtered_sign_alpha_days.csv'
ALPHA={'US':{'QQQ_UP_SPY_DOWN':-0.0005335558407893152,'QQQ_DOWN_SPY_UP':-0.00005221602036314227},'PE':{'EPU_DOWN_SPBLSCUP_UP':-0.00034178301480873797,'EPU_UP_SPBLSCUP_DOWN':-0.00029128105678171584}}
THR=[0.0,1.0,1.5,2.0]; TRAIN_START=pd.Timestamp('2026-07-07');TRAIN_END=pd.Timestamp('2026-08-17');OOS_START=pd.Timestamp('2026-08-18');ROLL=30

def read(p):
 d=pd.read_csv(p);d['fecha']=pd.to_datetime(d.fecha).dt.normalize();return d.sort_values('fecha').drop_duplicates('fecha',keep='last')
def main():
 f=read(FIXED)
 for c in ['SPY','EEM','MCHI','QQQ','SPBLSCUP','vc_sbs','ret_vc_estimado']:f[c]=pd.to_numeric(f[c],errors='coerce')
 for c in ['SPY','EEM','MCHI','QQQ','SPBLSCUP']:f['ret_'+c]=f[c].pct_change(fill_method=None)
 f['target_ret']=f.vc_sbs/f.vc_sbs.shift(1)-1;f['base_ret']=f.ret_vc_estimado
 m=read(MARKETS);m['ret_EPU']=pd.to_numeric(m.ret_EPU,errors='coerce')
 d=f.merge(m[['fecha','ret_EPU']],on='fecha',how='left')
 d['D_US']=d.ret_QQQ-d.ret_SPY;d['D_PE']=d.ret_EPU-d.ret_SPBLSCUP
 for p in ['US','PE']:
  d['z_'+p]=(d['D_'+p]-d['D_'+p].rolling(ROLL,min_periods=ROLL).mean().shift(1))/d['D_'+p].rolling(ROLL,min_periods=ROLL).std(ddof=1).shift(1)
 d['pattern_US']=np.where((d.ret_QQQ>0)&(d.ret_SPY<0),'QQQ_UP_SPY_DOWN',np.where((d.ret_QQQ<0)&(d.ret_SPY>0),'QQQ_DOWN_SPY_UP',''))
 d['pattern_PE']=np.where((d.ret_EPU>0)&(d.ret_SPBLSCUP<0),'EPU_UP_SPBLSCUP_DOWN',np.where((d.ret_EPU<0)&(d.ret_SPBLSCUP>0),'EPU_DOWN_SPBLSCUP_UP',''))
 d['period']=np.where(d.fecha<TRAIN_START,'PRE',np.where(d.fecha<=TRAIN_END,'TRAIN','OOS'))
 summary=[];detail=[]
 for p in ['US','PE']:
  for t in THR:
   q=d[(d['pattern_'+p]!='')&d.target_ret.notna()&d.base_ret.notna()].copy()
   if t>0:q=q[q['z_'+p].abs()>=t].copy()
   q['alpha']=q['pattern_'+p].map(ALPHA[p]);q['corr_ret']=q.base_ret+q.alpha
   q['base_err']=(q.base_ret-q.target_ret).abs()*100;q['corr_err']=(q.corr_ret-q.target_ret).abs()*100
   q['outcome']=np.where(q.corr_err<q.base_err,'IMPROVES',np.where(q.corr_err>q.base_err,'WORSENS','TIE'))
   for per in ['PRE','TRAIN','OOS']:
    g=q[q.period==per]
    bm=float(g.base_err.mean()) if len(g) else None;cm=float(g.corr_err.mean()) if len(g) else None
    summary.append({'pair':p,'threshold_abs_z':t,'period':per,'n':int(len(g)),'improves':int((g.outcome=='IMPROVES').sum()),'worsens':int((g.outcome=='WORSENS').sum()),'ties':int((g.outcome=='TIE').sum()),'base_mae_pp':bm,'corr_mae_pp':cm,'mae_reduction_pct':None if not bm else float((bm-cm)/bm*100)})
   q['pair']=p;q['threshold_abs_z']=t;detail.append(q[['pair','threshold_abs_z','fecha','period','pattern_'+p,'z_'+p,'base_err','corr_err','outcome']])
 pd.DataFrame(summary).to_csv(OUT,index=False);pd.concat(detail,ignore_index=True).to_csv(DETAIL,index=False)
 print(pd.DataFrame(summary).to_csv(index=False))
if __name__=='__main__':main()
