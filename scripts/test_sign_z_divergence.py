from __future__ import annotations

import json
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
FIXED = ROOT/'public/data/fixed_models_2026.csv'
MARKETS = ROOT/'data/rolling90/markets.csv'
OUT_JSON = ROOT/'analysis/sign_z_divergence_test.json'
OUT_CSV = ROOT/'analysis/sign_z_divergence_days.csv'

TRAIN_START=pd.Timestamp('2026-07-07'); TRAIN_END=pd.Timestamp('2026-08-17')
OOS_START=pd.Timestamp('2026-08-18'); OOS_END=pd.Timestamp('2026-08-26')
THRESHOLDS=[1.0,1.5,2.0]
ROLL=30


def read(path):
    d=pd.read_csv(path); d['fecha']=pd.to_datetime(d['fecha']).dt.normalize(); return d.sort_values('fecha').drop_duplicates('fecha',keep='last')

def metrics(d, pred):
    q=d.dropna(subset=['target_ret',pred])
    if len(q)==0: return {'n':0}
    e=(q[pred]-q['target_ret'])*100
    return {'n':int(len(q)),'mae_pp':float(e.abs().mean()),'rmse_pp':float(np.sqrt((e**2).mean())),'bias_pp':float(e.mean()),'direction_accuracy':float((np.sign(q[pred])==np.sign(q['target_ret'])).mean())}

def improve(b,c):
    def f(k):
        if not b.get(k) or c.get(k) is None:return None
        return float((b[k]-c[k])/b[k]*100)
    return {'mae_reduction_pct':f('mae_pp'),'rmse_reduction_pct':f('rmse_pp')}

def fit_gamma(train, xcol, residcol):
    q=train[(train[xcol]!=0)&train[xcol].notna()&train[residcol].notna()]
    if len(q)<2: return {'n':int(len(q)),'gamma':None,'gamma_pp_per_z':None}
    x=q[xcol].to_numpy(float); y=q[residcol].to_numpy(float)
    g=float(x@y/(x@x)) if float(x@x)>0 else None
    return {'n':int(len(q)),'gamma':g,'gamma_pp_per_z':None if g is None else g*100}

def main():
    f=read(FIXED)
    for c in ['SPY','EEM','MCHI','QQQ','SPBLSCUP','vc_sbs','vc_niveles','ret_vc_estimado']:
        f[c]=pd.to_numeric(f[c],errors='coerce')
    # returns from exact series used by fixed model
    for c in ['SPY','EEM','MCHI','QQQ','SPBLSCUP']:
        f['ret_'+c]=f[c].pct_change(fill_method=None)
    f['prev_vc_sbs']=f['vc_sbs'].shift(1)
    f['target_ret']=f['vc_sbs']/f['prev_vc_sbs']-1
    f['base_ret_retornos']=f['ret_vc_estimado']
    f['base_ret_niveles']=f['vc_niveles']/f['prev_vc_sbs']-1

    m=read(MARKETS)
    for c in ['ret_EPU','ret_NEM','ret_FCX','ret_MCHI','ret_EEM','ret_USD_PEN']:
        if c in m:m[c]=pd.to_numeric(m[c],errors='coerce')
    keep=[c for c in ['fecha','ret_EPU','ret_NEM','ret_FCX','ret_MCHI','ret_EEM','ret_USD_PEN'] if c in m]
    d=f.merge(m[keep],on='fecha',how='left',suffixes=('','_m'))
    # prefer fixed model MCHI/EEM returns for internal consistency
    d['D_US']=d['ret_QQQ']-d['ret_SPY']
    d['D_PE']=d['ret_EPU']-d['ret_SPBLSCUP']
    for pair in ['US','PE']:
        D='D_'+pair
        d['mu_'+pair]=d[D].rolling(ROLL,min_periods=ROLL).mean().shift(1)
        d['sd_'+pair]=d[D].rolling(ROLL,min_periods=ROLL).std(ddof=1).shift(1)
        d['z_'+pair]=(d[D]-d['mu_'+pair])/d['sd_'+pair]
    d['pattern_US']=np.where((d['ret_QQQ']>0)&(d['ret_SPY']<0),'QQQ_UP_SPY_DOWN',np.where((d['ret_QQQ']<0)&(d['ret_SPY']>0),'QQQ_DOWN_SPY_UP',''))
    d['pattern_PE']=np.where((d['ret_EPU']>0)&(d['ret_SPBLSCUP']<0),'EPU_UP_SPBLSCUP_DOWN',np.where((d['ret_EPU']<0)&(d['ret_SPBLSCUP']>0),'EPU_DOWN_SPBLSCUP_UP',''))
    d['other_divergence_count']=(d['pattern_US']!='').astype(int)+(d['pattern_PE']!='').astype(int)
    d['em_spread']=d['ret_MCHI']-d['ret_EEM']
    d['risk_off_count']=((d[['ret_SPY','ret_EEM','ret_MCHI','ret_SPBLSCUP']]<0).sum(axis=1))

    results={}
    detail=[]
    for model in ['retornos','niveles']:
        base='base_ret_'+model
        resid='resid_'+model
        d[resid]=d['target_ret']-d[base]
        train=d[(d.fecha>=TRAIN_START)&(d.fecha<=TRAIN_END)].copy()
        pre=d[d.fecha<TRAIN_START].copy(); oos=d[(d.fecha>=OOS_START)&(d.fecha<=OOS_END)].copy()
        mod={}
        for thr in THRESHOLDS:
            # features only when signs are opposite AND abs(z)>=threshold
            for pair in ['US','PE']:
                d[f'x_{pair}_{thr}']=np.where((d[f'pattern_{pair}']!='')&(d[f'z_{pair}'].abs()>=thr),d[f'z_{pair}'],0.0)
            train=d[(d.fecha>=TRAIN_START)&(d.fecha<=TRAIN_END)].copy(); pre=d[d.fecha<TRAIN_START].copy(); oos=d[(d.fecha>=OOS_START)&(d.fecha<=OOS_END)].copy()
            fits={pair:fit_gamma(train,f'x_{pair}_{thr}',resid) for pair in ['US','PE']}
            cfg={}
            for feature_set in ['US','PE','BOTH']:
                sets=['US','PE'] if feature_set=='BOTH' else [feature_set]
                for frame in [pre,train,oos]:
                    corr=np.zeros(len(frame),dtype=float)
                    active=np.zeros(len(frame),dtype=bool)
                    for pair in sets:
                        g=fits[pair]['gamma']
                        x=frame[f'x_{pair}_{thr}'].fillna(0).to_numpy(float)
                        if g is not None:corr+=g*x
                        active|=(x!=0)
                    frame['corr']=corr; frame['corrected']=frame[base]+corr; frame['active']=active
                cfg[feature_set]={'fits':{p:fits[p] for p in sets},'train_active':int(train.active.sum()),'pre_active':int(pre.active.sum()),'oos_active':int(oos.active.sum())}
                for name,frame in [('pre',pre),('train',train),('oos',oos)]:
                    b=metrics(frame[frame.active],base); c=metrics(frame[frame.active],'corrected')
                    cfg[feature_set][name+'_active']={'base':b,'corrected':c,'improvement':improve(b,c)}
                    ball=metrics(frame,base); call=metrics(frame,'corrected')
                    cfg[feature_set][name+'_all']={'base':ball,'corrected':call,'improvement':improve(ball,call)}
                # collect per-day active rows for context
                for period,frame in [('pre',pre),('train',train),('oos',oos)]:
                    q=frame[frame.active].copy()
                    if len(q):
                        q['model']=model;q['threshold']=thr;q['feature_set']=feature_set;q['period']=period
                        q['base_abs_err_pp']=(q[base]-q.target_ret).abs()*100
                        q['corr_abs_err_pp']=(q.corrected-q.target_ret).abs()*100
                        q['outcome']=np.where(q.corr_abs_err_pp<q.base_abs_err_pp,'IMPROVES',np.where(q.corr_abs_err_pp>q.base_abs_err_pp,'WORSENS','TIE'))
                        detail.append(q)
            mod[str(thr)]=cfg
        results[model]=mod

    # context summary for sign-only divergence dates, independent from any correction model
    contexts={}
    for pair in ['US','PE']:
        q=d[(d[f'pattern_{pair}']!='')&d.target_ret.notna()].copy()
        contexts[pair]={}
        for pat,g in q.groupby('pattern_'+pair):
            contexts[pair][pat]={
                'n':int(len(g)),
                'dates':[x.date().isoformat() for x in g.fecha],
                'mean_abs_z':float(g['z_'+pair].abs().mean()) if g['z_'+pair].notna().any() else None,
                'mean_ret_SPY_pct':float(g.ret_SPY.mean()*100),
                'mean_ret_QQQ_pct':float(g.ret_QQQ.mean()*100),
                'mean_ret_EEM_pct':float(g.ret_EEM.mean()*100),
                'mean_ret_MCHI_pct':float(g.ret_MCHI.mean()*100),
                'mean_ret_SPBLSCUP_pct':float(g.ret_SPBLSCUP.mean()*100),
                'mean_ret_EPU_pct':float(g.ret_EPU.mean()*100),
                'mean_ret_USD_PEN_pct':float(g.ret_USD_PEN.mean()*100) if 'ret_USD_PEN' in g else None,
                'simultaneous_other_pair_days':int((g.other_divergence_count>1).sum()),
            }
    out={'model_version':'v2-sbs-corrected-20260831','definition':'correction only if pair has opposite signs AND abs(z prior-30)>=threshold; gamma fitted on 07/07-17/08 residuals without intercept','thresholds':THRESHOLDS,'results':results,'sign_only_context':contexts}
    OUT_JSON.parent.mkdir(exist_ok=True);OUT_JSON.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    if detail:
        det=pd.concat(detail,ignore_index=True)
        cols=['model','period','threshold','feature_set','fecha','pattern_US','pattern_PE','z_US','z_PE','ret_SPY','ret_QQQ','ret_EPU','ret_SPBLSCUP','ret_EEM','ret_MCHI','ret_USD_PEN','ret_NEM','ret_FCX','target_ret','base_ret_retornos','base_ret_niveles','corr','corrected','base_abs_err_pp','corr_abs_err_pp','outcome','other_divergence_count','risk_off_count','em_spread']
        det[[c for c in cols if c in det]].to_csv(OUT_CSV,index=False)
    print(json.dumps(out,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
