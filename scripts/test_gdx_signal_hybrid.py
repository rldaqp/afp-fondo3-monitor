from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
SRC=ROOT/'analysis/gdx_walkforward30_daily.csv'
OUT=ROOT/'analysis/gdx_signal_hybrid94.json'
OUTCSV=ROOT/'analysis/gdx_signal_hybrid94_daily.csv'

CORE=['ret_EEM_pct','ret_MCHI_pct','ret_SPBLSCUP_pct']
ALL5=['ret_SPY_pct','ret_EEM_pct','ret_MCHI_pct','ret_QQQ_pct','ret_SPBLSCUP_pct']

def sgn(x):
    return 1 if x>0 else (-1 if x<0 else 0)

def same_sign_count(row, cols, mag=0.0):
    gs=sgn(row.ret_GDX_pct)
    if gs==0: return 0
    n=0
    for c in cols:
        v=float(row[c])
        if abs(v)>=mag and sgn(v)==gs:
            n+=1
    return n

def metrics(err):
    x=np.asarray(err,float)
    return {'n':int(len(x)),'mae_pct':float(np.mean(np.abs(x))), 'rmse_pct':float(np.sqrt(np.mean(x*x))), 'bias_pct':float(np.mean(x))}

def improve(base,cand):
    return {'mae_reduction_pct':100*(base['mae_pct']-cand['mae_pct'])/base['mae_pct'],
            'rmse_reduction_pct':100*(base['rmse_pct']-cand['rmse_pct'])/base['rmse_pct']}

def rule_flags(df):
    rules={}
    for mag in [0.0,0.2,0.4,0.6]:
        rules[f'core2of3_mag{mag:.1f}']=df.apply(lambda r:same_sign_count(r,CORE,mag)>=2,axis=1)
    for mag in [0.0,0.2,0.4]:
        rules[f'all3core_mag{mag:.1f}']=df.apply(lambda r:same_sign_count(r,CORE,mag)>=3,axis=1)
    for mag in [0.0,0.2,0.4,0.6]:
        rules[f'all5_3of5_mag{mag:.1f}']=df.apply(lambda r:same_sign_count(r,ALL5,mag)>=3,axis=1)
    for mag in [0.0,0.2,0.4]:
        rules[f'combo3of5_core2_mag{mag:.1f}']=df.apply(lambda r:(same_sign_count(r,ALL5,mag)>=3 and same_sign_count(r,CORE,mag)>=2),axis=1)
    # variants requiring GDX itself to move materially
    for gmag in [0.5,1.0,1.5,2.0]:
        rules[f'core2of3_gdx{gmag:.1f}']=df.apply(lambda r:(abs(r.ret_GDX_pct)>=gmag and same_sign_count(r,CORE,0.0)>=2),axis=1)
    return rules

def main():
    d=pd.read_csv(SRC)
    d['fecha']=pd.to_datetime(d['fecha'])
    base=metrics(d.error_base_pct)
    always=metrics(d.error_gdx_pct)
    res={'design':'Use rolling-30 Base+GDX only when a contemporaneous sign-confirmation signal is active; otherwise use rolling-30 Base. Signals use only GDX plus existing Base factors.',
         'period':[str(d.fecha.min().date()),str(d.fecha.max().date())],'n':int(len(d)),
         'benchmarks':{'base':base,'gdx_always':always,'gdx_always_improvement':improve(base,always)},'rules':{}}
    flags=rule_flags(d)
    daily=d[['fecha','error_base_pct','error_gdx_pct','ret_GDX_pct']+ALL5].copy()
    for name,f in flags.items():
        f=np.asarray(f,bool)
        err=np.where(f,d.error_gdx_pct.to_numpy(float),d.error_base_pct.to_numpy(float))
        mh=metrics(err)
        sig=d.loc[f]
        nsig=d.loc[~f]
        sb=metrics(sig.error_base_pct) if len(sig) else {'n':0}
        sg=metrics(sig.error_gdx_pct) if len(sig) else {'n':0}
        wins=int((sig.error_gdx_pct.abs()<sig.error_base_pct.abs()).sum()) if len(sig) else 0
        losses=int((sig.error_gdx_pct.abs()>sig.error_base_pct.abs()).sum()) if len(sig) else 0
        monthly={}
        for m,g in d.assign(flag=f,hybrid_err=err).groupby(d.fecha.dt.to_period('M').astype(str)):
            mb=metrics(g.error_base_pct); mg=metrics(g.hybrid_err)
            monthly[m]={'n':int(len(g)),'signals':int(g.flag.sum()),'base_mae_pct':mb['mae_pct'],'hybrid_mae_pct':mg['mae_pct'],'mae_reduction_pct':100*(mb['mae_pct']-mg['mae_pct'])/mb['mae_pct']}
        res['rules'][name]={
            'signals':int(f.sum()),'signal_rate':float(f.mean()),
            'signal_days_base':sb,'signal_days_gdx':sg,
            'signal_days_improvement':improve(sb,sg) if len(sig) else None,
            'signal_wins':wins,'signal_losses':losses,'signal_win_rate':wins/max(1,wins+losses),
            'hybrid':mh,'hybrid_improvement_vs_base':improve(base,mh),
            'monthly':monthly
        }
        daily[name]=f
        daily[name+'_hybrid_error_pct']=err
    # rank by MAE reduction, but retain all outputs for audit
    ranking=sorted([{'rule':k,'signals':v['signals'],'mae_reduction_pct':v['hybrid_improvement_vs_base']['mae_reduction_pct'],
                     'rmse_reduction_pct':v['hybrid_improvement_vs_base']['rmse_reduction_pct'],'signal_win_rate':v['signal_win_rate']}
                    for k,v in res['rules'].items()],key=lambda x:x['mae_reduction_pct'],reverse=True)
    res['ranking']=ranking
    OUT.write_text(json.dumps(res,ensure_ascii=False,indent=2),encoding='utf-8')
    daily.to_csv(OUTCSV,index=False)
    print(json.dumps({'benchmarks':res['benchmarks'],'ranking':ranking},ensure_ascii=False,indent=2))

if __name__=='__main__': main()
