from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd
import yfinance as yf

ROOT=Path(__file__).resolve().parents[1]
FIXED=ROOT/'public/data/fixed_models_2026.csv'
MARKETS=ROOT/'data/rolling90/markets.csv'
OUT=ROOT/'analysis/consensus_energy_candidates.json'
OUTCSV=ROOT/'analysis/consensus_energy_candidates.csv'
TRAIN_START=pd.Timestamp('2026-07-07'); TRAIN_END=pd.Timestamp('2026-08-17')
ALPHA={
'US':{'QQQ_UP_SPY_DOWN':-0.0005335558407893152,'QQQ_DOWN_SPY_UP':-0.00005221602036314227},
'PE':{'EPU_DOWN_SPBLSCUP_UP':-0.00034178301480873797,'EPU_UP_SPBLSCUP_DOWN':-0.00029128105678171584}}
ENERGY=['XLE','XOP','USO','XOM','COP']
EXTRA=['EPU','NEM','FCX','USD_PEN']

def read(p):
 d=pd.read_csv(p); d['fecha']=pd.to_datetime(d.fecha).dt.normalize(); return d.sort_values('fecha').drop_duplicates('fecha',keep='last')

def metrics(y,p):
 e=p-y
 return {'n':int(len(y)),'mae_pp':float(np.mean(np.abs(e))*100),'rmse_pp':float(np.sqrt(np.mean(e*e))*100),'bias_pp':float(np.mean(e)*100),'direction_accuracy':float(np.mean(np.sign(p)==np.sign(y)))} if len(y) else {'n':0}

def improvement(a,b):
 return {'mae_reduction_pct':100*(a['mae_pp']-b['mae_pp'])/a['mae_pp'] if a.get('n') and a['mae_pp'] else None,
         'rmse_reduction_pct':100*(a['rmse_pp']-b['rmse_pp'])/a['rmse_pp'] if a.get('n') and a['rmse_pp'] else None}

def fetch_ticker(t):
 q=yf.download(t,start='2025-12-01',end='2026-09-03',auto_adjust=False,progress=False,threads=False)
 if q.empty:return pd.DataFrame(columns=['fecha','ret_'+t])
 if isinstance(q.columns,pd.MultiIndex): q.columns=q.columns.get_level_values(0)
 col='Adj Close' if 'Adj Close' in q.columns else 'Close'
 s=pd.to_numeric(q[col],errors='coerce').dropna(); r=s.pct_change(fill_method=None)
 return pd.DataFrame({'fecha':pd.to_datetime(r.index).tz_localize(None).normalize(),'ret_'+t:r.values})

def gamma_no_intercept(x,r):
 ok=np.isfinite(x)&np.isfinite(r); x=x[ok];r=r[ok]
 return float(np.dot(x,r)/np.dot(x,x)) if len(x) and np.dot(x,x)>0 else np.nan

def overlay_candidate(d,c):
 tr=d[(d.fecha>=TRAIN_START)&(d.fecha<=TRAIN_END)&d.target_ret.notna()&d.base_ret.notna()&d[c].notna()].copy()
 oo=d[(d.fecha>TRAIN_END)&d.target_ret.notna()&d.base_ret.notna()&d[c].notna()].copy()
 pre=d[(d.fecha<TRAIN_START)&d.target_ret.notna()&d.base_ret.notna()&d[c].notna()].copy()
 if len(tr)<8:return {'train_n':int(len(tr))}
 resid=(tr.target_ret-tr.base_ret).to_numpy(); x=tr[c].to_numpy(); g=gamma_no_intercept(x,resid)
 # LOO overlay to reduce in-sample optimism
 loo=[]
 for i in range(len(tr)):
  mask=np.ones(len(tr),dtype=bool);mask[i]=False; gi=gamma_no_intercept(x[mask],resid[mask]);loo.append(tr.base_ret.iloc[i]+(0 if not np.isfinite(gi) else gi*x[i]))
 mb=metrics(tr.target_ret.to_numpy(),tr.base_ret.to_numpy()); ml=metrics(tr.target_ret.to_numpy(),np.array(loo))
 out={'gamma':g,'gamma_pp_per_1pct_factor':g,'train_loo_base':mb,'train_loo_corrected':ml,'train_loo_improvement':improvement(mb,ml)}
 for name,q in [('pre',pre),('oos',oo)]:
  b=metrics(q.target_ret.to_numpy(),q.base_ret.to_numpy()); p=q.base_ret.to_numpy()+g*q[c].to_numpy(); m=metrics(q.target_ret.to_numpy(),p)
  out[name]={'base':b,'corrected':m,'improvement':improvement(b,m)}
 return out

def ols6_candidate(d,c):
 cols=['ret_SPY','ret_EEM','ret_MCHI','ret_QQQ','ret_SPBLSCUP']
 tr=d[(d.fecha>=TRAIN_START)&(d.fecha<=TRAIN_END)&d.target_ret.notna()].dropna(subset=cols+[c]).copy()
 oo=d[(d.fecha>TRAIN_END)&d.target_ret.notna()].dropna(subset=cols+[c]).copy()
 if len(tr)<12:return {'train_n':int(len(tr))}
 def fitpred(train,test,features):
  X=np.column_stack([np.ones(len(train))]+[train[x].to_numpy() for x in features]); y=train.target_ret.to_numpy(); b=np.linalg.lstsq(X,y,rcond=None)[0]
  Z=np.column_stack([np.ones(len(test))]+[test[x].to_numpy() for x in features]); return b,Z@b
 b5,p5=fitpred(tr,oo,cols); b6,p6=fitpred(tr,oo,cols+[c])
 m5=metrics(oo.target_ret.to_numpy(),p5);m6=metrics(oo.target_ret.to_numpy(),p6)
 return {'train_n':int(len(tr)),'oos_n':int(len(oo)),'base5_oos':m5,'plus_candidate_oos':m6,'improvement':improvement(m5,m6),'candidate_beta':float(b6[-1])}

def consensus_test(d,pair,k):
 if pair=='US': conf=['ret_EEM','ret_MCHI','ret_EPU','ret_SPBLSCUP','ret_NEM','ret_FCX']; pat='pattern_US'; a='ret_SPY';b='ret_QQQ'
 else: conf=['ret_SPY','ret_QQQ','ret_EEM','ret_MCHI','ret_NEM','ret_FCX']; pat='pattern_PE';a='ret_EPU';b='ret_SPBLSCUP'
 q=d[(d[pat]!='')&d.target_ret.notna()&d.base_ret.notna()].copy(); rows=[]
 for _,r in q.iterrows():
  vals=[r[x] for x in conf if pd.notna(r[x]) and r[x]!=0]; pos=sum(v>0 for v in vals);neg=sum(v<0 for v in vals)
  majority=1 if pos>neg else (-1 if neg>pos else 0); mc=max(pos,neg)
  sa=np.sign(r[a]);sb=np.sign(r[b]); active=(majority!=0 and mc>=k and ((sa==majority)!=(sb==majority)))
  aligned=a if sa==majority and sb!=majority else (b if sb==majority and sa!=majority else '')
  outlier=b if aligned==a else (a if aligned==b else '')
  alpha=ALPHA[pair].get(r[pat],0.0) if active else 0.0; corr=r.base_ret+alpha
  rows.append({'fecha':r.fecha,'period':'PRE' if r.fecha<TRAIN_START else ('TRAIN' if r.fecha<=TRAIN_END else 'OOS'),'active':active,'majority_count':mc,'n_conf':len(vals),'majority_sign':majority,'aligned':aligned,'outlier':outlier,'pattern':r[pat],'base':r.base_ret,'target':r.target_ret,'corr':corr})
 z=pd.DataFrame(rows); out={}
 for per in ['PRE','TRAIN','OOS']:
  p=z[(z.period==per)&z.active]
  bm=metrics(p.target.to_numpy(),p.base.to_numpy());cm=metrics(p.target.to_numpy(),p.corr.to_numpy())
  out[per]={'active_n':int(len(p)),'improves':int(np.sum(np.abs(p['corr']-p.target)<np.abs(p.base-p.target))) if len(p) else 0,'worsens':int(np.sum(np.abs(p['corr']-p.target)>np.abs(p.base-p.target))) if len(p) else 0,'base':bm,'corrected':cm,'improvement':improvement(bm,cm),'dates':[x.date().isoformat() for x in p.fecha]}
 return out,z

def main():
 f=read(FIXED)
 for c in ['SPY','EEM','MCHI','QQQ','SPBLSCUP','vc_sbs','ret_vc_estimado']:f[c]=pd.to_numeric(f[c],errors='coerce')
 for c in ['SPY','EEM','MCHI','QQQ','SPBLSCUP']:f['ret_'+c]=f[c].pct_change(fill_method=None)
 f['target_ret']=f.vc_sbs/f.vc_sbs.shift(1)-1;f['base_ret']=f.ret_vc_estimado
 m=read(MARKETS)
 keep=['fecha']
 for x in EXTRA:
  c='ret_'+x
  if c in m.columns:m[c]=pd.to_numeric(m[c],errors='coerce');keep.append(c)
 d=f.merge(m[keep],on='fecha',how='left')
 for t in ENERGY:d=d.merge(fetch_ticker(t),on='fecha',how='left')
 d['pattern_US']=np.where((d.ret_QQQ>0)&(d.ret_SPY<0),'QQQ_UP_SPY_DOWN',np.where((d.ret_QQQ<0)&(d.ret_SPY>0),'QQQ_DOWN_SPY_UP',''))
 d['pattern_PE']=np.where((d.ret_EPU>0)&(d.ret_SPBLSCUP<0),'EPU_UP_SPBLSCUP_DOWN',np.where((d.ret_EPU<0)&(d.ret_SPBLSCUP>0),'EPU_DOWN_SPBLSCUP_UP',''))
 candidates=['ret_'+x for x in EXTRA+ENERGY]
 result={'candidate_overlay':{},'ols_add_one':{},'consensus':{}}
 for c in candidates:
  if c in d.columns:
   result['candidate_overlay'][c]=overlay_candidate(d,c);result['ols_add_one'][c]=ols6_candidate(d,c)
 cons_rows=[]
 for pair in ['US','PE']:
  result['consensus'][pair]={}
  for k in [3,4,5,6]:
   r,z=consensus_test(d,pair,k);result['consensus'][pair][str(k)]=r
   if len(z):z.insert(0,'pair',pair);z.insert(1,'k',k);cons_rows.append(z)
 # ranking by OOS overlay MAE reduction
 ranking=[]
 for c,r in result['candidate_overlay'].items():
  imp=r.get('oos',{}).get('improvement',{}).get('mae_reduction_pct')
  tr=r.get('train_loo_improvement',{}).get('mae_reduction_pct')
  pre=r.get('pre',{}).get('improvement',{}).get('mae_reduction_pct')
  ranking.append({'candidate':c,'train_loo_mae_improvement_pct':tr,'oos_mae_improvement_pct':imp,'pre_mae_improvement_pct':pre,'gamma':r.get('gamma')})
 ranking=sorted(ranking,key=lambda x:(-999 if x['oos_mae_improvement_pct'] is None else x['oos_mae_improvement_pct']),reverse=True);result['ranking_overlay']=ranking
 OUT.parent.mkdir(exist_ok=True);OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
 pd.DataFrame(ranking).to_csv(OUTCSV,index=False)
 if cons_rows:pd.concat(cons_rows,ignore_index=True).to_csv(ROOT/'analysis/consensus_rule_days.csv',index=False)
 print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
