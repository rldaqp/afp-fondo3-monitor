from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
FIXED=ROOT/'public/data/fixed_models_2026.csv'; MARKETS=ROOT/'data/rolling90/markets.csv'
OUT=ROOT/'analysis/sign_only_improve_vs_worsen.json'; OUTCSV=ROOT/'analysis/sign_only_improve_vs_worsen.csv'
TRAIN_START=pd.Timestamp('2026-07-07'); TRAIN_END=pd.Timestamp('2026-08-17'); ROLL=30
ALPHA={
'US':{'QQQ_UP_SPY_DOWN':-0.0005335558407893152,'QQQ_DOWN_SPY_UP':-0.00005221602036314227},
'PE':{'EPU_DOWN_SPBLSCUP_UP':-0.00034178301480873797,'EPU_UP_SPBLSCUP_DOWN':-0.00029128105678171584}}

def read(p):
 d=pd.read_csv(p);d['fecha']=pd.to_datetime(d.fecha).dt.normalize();return d.sort_values('fecha').drop_duplicates('fecha',keep='last')
def mean_or_none(s):
 s=pd.to_numeric(s,errors='coerce').dropna(); return None if len(s)==0 else float(s.mean())
def summary(g,pair):
 return {'n':int(len(g)),'dates':[x.date().isoformat() for x in g.fecha],
 'mean_abs_z':mean_or_none(g['z_'+pair].abs()),'median_abs_z':None if g['z_'+pair].dropna().empty else float(g['z_'+pair].abs().median()),
 'mean_pair_spread_pp':mean_or_none(g['D_'+pair]*100),'mean_abs_pair_spread_pp':mean_or_none(g['D_'+pair].abs()*100),
 'mean_base_abs_error_pp':mean_or_none(g.base_abs_error_pp),'mean_ret_sbs_pct':mean_or_none(g.target_ret*100),
 'mean_SPY_pct':mean_or_none(g.ret_SPY*100),'mean_QQQ_pct':mean_or_none(g.ret_QQQ*100),
 'mean_EEM_pct':mean_or_none(g.ret_EEM*100),'mean_MCHI_pct':mean_or_none(g.ret_MCHI*100),
 'mean_EPU_pct':mean_or_none(g.ret_EPU*100),'mean_SPBLSCUP_pct':mean_or_none(g.ret_SPBLSCUP*100),
 'mean_USD_PEN_pct':mean_or_none(g.ret_USD_PEN*100),'mean_NEM_pct':mean_or_none(g.ret_NEM*100),'mean_FCX_pct':mean_or_none(g.ret_FCX*100),
 'simultaneous_other_pair_pct':float((g.other_pair).mean()*100) if len(g) else None,
 'mean_risk_off_count':mean_or_none(g.risk_off_count),'mean_em_gap_pp':mean_or_none((g.ret_MCHI-g.ret_EEM)*100)}

def main():
 f=read(FIXED)
 for c in ['SPY','EEM','MCHI','QQQ','SPBLSCUP','vc_sbs','ret_vc_estimado']:f[c]=pd.to_numeric(f[c],errors='coerce')
 for c in ['SPY','EEM','MCHI','QQQ','SPBLSCUP']:f['ret_'+c]=f[c].pct_change(fill_method=None)
 f['prev_sbs']=f.vc_sbs.shift(1);f['target_ret']=f.vc_sbs/f.prev_sbs-1;f['base_ret']=f.ret_vc_estimado
 m=read(MARKETS)
 for c in ['ret_EPU','ret_NEM','ret_FCX','ret_USD_PEN']:
  m[c]=pd.to_numeric(m[c],errors='coerce')
 d=f.merge(m[['fecha','ret_EPU','ret_NEM','ret_FCX','ret_USD_PEN']],on='fecha',how='left')
 d['D_US']=d.ret_QQQ-d.ret_SPY;d['D_PE']=d.ret_EPU-d.ret_SPBLSCUP
 for p in ['US','PE']:
  d['z_'+p]=(d['D_'+p]-d['D_'+p].rolling(ROLL,min_periods=ROLL).mean().shift(1))/d['D_'+p].rolling(ROLL,min_periods=ROLL).std(ddof=1).shift(1)
 d['pattern_US']=np.where((d.ret_QQQ>0)&(d.ret_SPY<0),'QQQ_UP_SPY_DOWN',np.where((d.ret_QQQ<0)&(d.ret_SPY>0),'QQQ_DOWN_SPY_UP',''))
 d['pattern_PE']=np.where((d.ret_EPU>0)&(d.ret_SPBLSCUP<0),'EPU_UP_SPBLSCUP_DOWN',np.where((d.ret_EPU<0)&(d.ret_SPBLSCUP>0),'EPU_DOWN_SPBLSCUP_UP',''))
 d['risk_off_count']=(d[['ret_SPY','ret_EEM','ret_MCHI','ret_SPBLSCUP']]<0).sum(axis=1)
 rows=[];res={}
 for pair in ['US','PE']:
  q=d[(d['pattern_'+pair]!='')&d.target_ret.notna()&d.base_ret.notna()].copy()
  q['other_pair']=np.where(pair=='US',d.loc[q.index,'pattern_PE']!='',d.loc[q.index,'pattern_US']!='')
  q['alpha']=q['pattern_'+pair].map(ALPHA[pair]);q['corrected']=q.base_ret+q.alpha
  q['base_abs_error_pp']=(q.base_ret-q.target_ret).abs()*100;q['corr_abs_error_pp']=(q.corrected-q.target_ret).abs()*100
  q['outcome']=np.where(q.corr_abs_error_pp<q.base_abs_error_pp,'IMPROVES',np.where(q.corr_abs_error_pp>q.base_abs_error_pp,'WORSENS','TIE'))
  q['period']=np.where(q.fecha<TRAIN_START,'PRE',np.where(q.fecha<=TRAIN_END,'TRAIN','OOS'))
  res[pair]={}
  for period in ['PRE','TRAIN','OOS']:
   p=q[q.period==period];res[pair][period]={'all':summary(p,pair)}
   for out in ['IMPROVES','WORSENS']:
    res[pair][period][out]=summary(p[p.outcome==out],pair)
  cols=['fecha','period','pattern_'+pair,'z_'+pair,'D_'+pair,'alpha','target_ret','base_ret','corrected','base_abs_error_pp','corr_abs_error_pp','outcome','ret_SPY','ret_QQQ','ret_EEM','ret_MCHI','ret_EPU','ret_SPBLSCUP','ret_USD_PEN','ret_NEM','ret_FCX','risk_off_count','other_pair']
  qq=q[cols].copy();qq.insert(0,'pair',pair);rows.append(qq)
 OUT.parent.mkdir(exist_ok=True);OUT.write_text(json.dumps({'alphas_from_current_training':ALPHA,'comparison':res},ensure_ascii=False,indent=2),encoding='utf-8')
 pd.concat(rows,ignore_index=True).to_csv(OUTCSV,index=False)
 print(json.dumps({'alphas_from_current_training':ALPHA,'comparison':res},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
