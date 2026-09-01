from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd
import yfinance as yf

ROOT=Path(__file__).resolve().parents[1]
FIXED=ROOT/'public/data/fixed_models_2026.csv'
OUT=ROOT/'analysis/gdx_walkforward30.json'
OUTCSV=ROOT/'analysis/gdx_walkforward30_daily.csv'
BASE=['ret_SPY','ret_EEM','ret_MCHI','ret_QQQ','ret_SPBLSCUP']
CAND=BASE+['ret_GDX']
DIRECT_START=pd.Timestamp('2026-02-19')
SBS_MANUAL={pd.Timestamp('2026-08-27'):72.3323679}


def metrics(y,p):
    y=np.asarray(y,float); p=np.asarray(p,float)
    ok=np.isfinite(y)&np.isfinite(p); y=y[ok]; p=p[ok]
    e=p-y
    return {
        'n':int(len(y)),
        'mae_pp':float(np.mean(np.abs(e))*100) if len(y) else None,
        'rmse_pp':float(np.sqrt(np.mean(e*e))*100) if len(y) else None,
        'bias_pp':float(np.mean(e)*100) if len(y) else None,
        'direction_accuracy':float(np.mean(np.sign(p)==np.sign(y))) if len(y) else None,
    }

def vc_metrics(actual,pred):
    a=np.asarray(actual,float); p=np.asarray(pred,float)
    ok=np.isfinite(a)&np.isfinite(p); a=a[ok]; p=p[ok]
    e=(p/a-1)*100
    return {
        'n':int(len(a)),
        'mae_pct':float(np.mean(np.abs(e))) if len(a) else None,
        'rmse_pct':float(np.sqrt(np.mean(e*e))) if len(a) else None,
        'bias_pct':float(np.mean(e)) if len(a) else None,
    }

def fit_stats(train,features):
    X=np.column_stack([np.ones(len(train))]+[train[c].to_numpy(float) for c in features])
    y=train.target_ret.to_numpy(float)
    b=np.linalg.lstsq(X,y,rcond=None)[0]
    pred=X@b
    ssr=float(np.sum((y-pred)**2)); sst=float(np.sum((y-y.mean())**2))
    r2=1-ssr/sst if sst>0 else np.nan
    n=len(y); k=len(features)
    adj=1-(1-r2)*(n-1)/(n-k-1) if n>k+1 else np.nan
    se=np.sqrt(ssr/(n-k-1)) if n>k+1 else np.nan
    return b,{'r2':float(r2),'adj_r2':float(adj),'standard_error':float(se)}

def pred_one(row,b,features):
    return float(np.array([1.0]+[float(row[c]) for c in features])@b)

def main():
    d=pd.read_csv(FIXED)
    d['fecha']=pd.to_datetime(d.fecha).dt.normalize()
    d=d.sort_values('fecha').drop_duplicates('fecha',keep='last').reset_index(drop=True)
    for c in ['SPY','EEM','MCHI','QQQ','SPBLSCUP','vc_sbs']:
        d[c]=pd.to_numeric(d[c],errors='coerce')
    for dt,v in SBS_MANUAL.items():
        d.loc[d.fecha.eq(dt),'vc_sbs']=v
    for c in ['SPY','EEM','MCHI','QQQ','SPBLSCUP']:
        d['ret_'+c]=d[c].pct_change(fill_method=None)
    d['target_ret']=d.vc_sbs/d.vc_sbs.shift(1)-1

    q=yf.download('GDX',start='2026-01-01',end='2026-09-02',auto_adjust=False,progress=False,threads=False)
    if isinstance(q.columns,pd.MultiIndex): q.columns=q.columns.get_level_values(0)
    col='Adj Close' if 'Adj Close' in q.columns else 'Close'
    s=pd.to_numeric(q[col],errors='coerce').dropna()
    rg=s.pct_change(fill_method=None)
    gd=pd.DataFrame({'fecha':pd.to_datetime(rg.index).tz_localize(None).normalize(),'ret_GDX':rg.values})
    d=d.merge(gd,on='fecha',how='left')

    # Only SBS-direct era is allowed in the rolling training pool.
    pool=d[d.fecha>=DIRECT_START].copy().reset_index(drop=True)
    rows=[]
    for i in range(len(pool)):
        r=pool.iloc[i]
        if not all(pd.notna(r[c]) for c in CAND+['target_ret','vc_sbs']):
            continue
        prior=pool.iloc[:i].dropna(subset=CAND+['target_ret','vc_sbs']).copy()
        if len(prior)<30:
            continue
        tr=prior.tail(30).copy()
        b0,s0=fit_stats(tr,BASE)
        bg,sg=fit_stats(tr,CAND)
        p0=pred_one(r,b0,BASE); pg=pred_one(r,bg,CAND)
        prev=pool[(pool.fecha<r.fecha)&pool.vc_sbs.notna()].tail(1)
        if prev.empty: continue
        prev_v=float(prev.vc_sbs.iloc[0]); prev_date=prev.fecha.iloc[0]
        vc0=prev_v*(1+p0); vcg=prev_v*(1+pg); actual=float(r.vc_sbs)
        e0=(vc0/actual-1)*100; eg=(vcg/actual-1)*100
        rows.append({
            'fecha':str(r.fecha.date()),'train_start':str(tr.fecha.iloc[0].date()),'train_end':str(tr.fecha.iloc[-1].date()),
            'prev_sbs_date':str(prev_date.date()),'vc_prev_real':prev_v,'vc_real':actual,
            'ret_real_pct':float(r.target_ret*100),'ret_base_pct':p0*100,'ret_gdx_pct':pg*100,
            'vc_base':vc0,'vc_gdx':vcg,'error_base_pct':e0,'error_gdx_pct':eg,
            'gdx_improves':bool(abs(eg)<abs(e0)),
            'train_r2_base':s0['r2'],'train_adj_r2_base':s0['adj_r2'],'train_r2_gdx':sg['r2'],'train_adj_r2_gdx':sg['adj_r2'],
            'ret_GDX_pct':float(r.ret_GDX*100),
            'ret_SPY_pct':float(r.ret_SPY*100),'ret_EEM_pct':float(r.ret_EEM*100),'ret_MCHI_pct':float(r.ret_MCHI*100),
            'ret_QQQ_pct':float(r.ret_QQQ*100),'ret_SPBLSCUP_pct':float(r.ret_SPBLSCUP*100),
        })
    z=pd.DataFrame(rows)
    if z.empty: raise RuntimeError('No walk-forward rows')

    mret0=metrics(z.ret_real_pct/100,z.ret_base_pct/100); mretg=metrics(z.ret_real_pct/100,z.ret_gdx_pct/100)
    mvc0=vc_metrics(z.vc_real,z.vc_base); mvcg=vc_metrics(z.vc_real,z.vc_gdx)
    improvement={
        'mae_vc_reduction_pct':100*(mvc0['mae_pct']-mvcg['mae_pct'])/mvc0['mae_pct'],
        'rmse_vc_reduction_pct':100*(mvc0['rmse_pct']-mvcg['rmse_pct'])/mvc0['rmse_pct'],
        'wins':int(z.gdx_improves.sum()),'losses':int((~z.gdx_improves).sum()),'win_rate':float(z.gdx_improves.mean())
    }
    monthly={}
    z['month']=pd.to_datetime(z.fecha).dt.to_period('M').astype(str)
    for mo,qm in z.groupby('month'):
        a0=vc_metrics(qm.vc_real,qm.vc_base); ag=vc_metrics(qm.vc_real,qm.vc_gdx)
        monthly[mo]={
            'n':int(len(qm)),'base':a0,'gdx':ag,
            'mae_reduction_pct':100*(a0['mae_pct']-ag['mae_pct'])/a0['mae_pct'] if a0['mae_pct'] else None,
            'wins':int(qm.gdx_improves.sum()),'losses':int((~qm.gdx_improves).sum())
        }
    r2_summary={
        'avg_r2_base':float(z.train_r2_base.mean()),'avg_r2_gdx':float(z.train_r2_gdx.mean()),
        'avg_adj_r2_base':float(z.train_adj_r2_base.mean()),'avg_adj_r2_gdx':float(z.train_adj_r2_gdx.mean()),
        'median_adj_r2_delta':float((z.train_adj_r2_gdx-z.train_adj_r2_base).median()),
        'adj_r2_gdx_better_windows':int((z.train_adj_r2_gdx>z.train_adj_r2_base).sum()),
        'total_windows':int(len(z))
    }
    # Current fixed 07-Jul to 17-Aug comparison for reference.
    current=d[(d.fecha>=pd.Timestamp('2026-07-07'))&(d.fecha<=pd.Timestamp('2026-08-17'))].dropna(subset=CAND+['target_ret']).copy()
    _,cur0=fit_stats(current,BASE); _,curg=fit_stats(current,CAND)

    result={
        'design':'Walk-forward rolling 30. Each target day is predicted from the immediately prior 30 direct-SBS observations only.',
        'direct_sbs_start':str(DIRECT_START.date()),
        'walkforward_start':str(z.fecha.iloc[0]),'walkforward_end':str(z.fecha.iloc[-1]),'n':int(len(z)),
        'current_0707_0817':{'n':int(len(current)),'base5':cur0,'base5_gdx':curg},
        'walkforward_return':{'base':mret0,'gdx':mretg},
        'walkforward_vc':{'base':mvc0,'gdx':mvcg,'improvement':improvement},
        'rolling_training_r2':r2_summary,'monthly':monthly,
        'best_gdx_days':z.assign(delta=np.abs(z.error_base_pct)-np.abs(z.error_gdx_pct)).nlargest(10,'delta')[['fecha','error_base_pct','error_gdx_pct','delta']].to_dict('records'),
        'worst_gdx_days':z.assign(delta=np.abs(z.error_base_pct)-np.abs(z.error_gdx_pct)).nsmallest(10,'delta')[['fecha','error_base_pct','error_gdx_pct','delta']].to_dict('records')
    }
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    z.drop(columns=['month']).to_csv(OUTCSV,index=False)
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__': main()
