from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd
import yfinance as yf

ROOT=Path(__file__).resolve().parents[1]
FIXED=ROOT/'public/data/fixed_models_2026.csv'
OUT=ROOT/'analysis/gold_train_0707_0727.json'
OUTCSV=ROOT/'analysis/gold_train_0707_0727_daily.csv'
TRAIN_START=pd.Timestamp('2026-07-07')
TRAIN_END=pd.Timestamp('2026-07-27')
BASE=['ret_SPY','ret_EEM','ret_MCHI','ret_QQQ','ret_SPBLSCUP']
MODELS={
    'BASE5': [],
    'BASE5_GLD': ['ret_GLD'],
    'BASE5_GDX': ['ret_GDX'],
    'BASE5_GLD_GDX': ['ret_GLD','ret_GDX'],
}

def read_fixed():
    d=pd.read_csv(FIXED)
    d['fecha']=pd.to_datetime(d['fecha']).dt.normalize()
    d=d.sort_values('fecha').drop_duplicates('fecha',keep='last')
    for c in ['SPY','EEM','MCHI','QQQ','SPBLSCUP','vc_sbs']:
        d[c]=pd.to_numeric(d[c],errors='coerce')
    for c in ['SPY','EEM','MCHI','QQQ','SPBLSCUP']:
        d['ret_'+c]=d[c].pct_change(fill_method=None)
    d['target_ret']=d['vc_sbs']/d['vc_sbs'].shift(1)-1
    d['vc_prev_real']=d['vc_sbs'].shift(1)
    return d

def fetch_ret(ticker):
    q=yf.download(ticker,start='2026-06-01',end='2026-09-03',auto_adjust=False,progress=False,threads=False)
    if q.empty:
        return pd.DataFrame(columns=['fecha','ret_'+ticker])
    if isinstance(q.columns,pd.MultiIndex):
        q.columns=q.columns.get_level_values(0)
    col='Adj Close' if 'Adj Close' in q.columns else 'Close'
    s=pd.to_numeric(q[col],errors='coerce').dropna()
    r=s.pct_change(fill_method=None)
    return pd.DataFrame({'fecha':pd.to_datetime(r.index).tz_localize(None).normalize(),'ret_'+ticker:r.values})

def fit_ols(train,features):
    X=np.column_stack([np.ones(len(train))]+[train[c].to_numpy(float) for c in features])
    y=train['target_ret'].to_numpy(float)
    b=np.linalg.lstsq(X,y,rcond=None)[0]
    pred=X@b
    ss_res=float(np.sum((y-pred)**2))
    ss_tot=float(np.sum((y-y.mean())**2))
    r2=1-ss_res/ss_tot if ss_tot>0 else np.nan
    n=len(y); p=len(features)
    adj=1-(1-r2)*(n-1)/(n-p-1) if n>p+1 else np.nan
    se=float(np.sqrt(ss_res/(n-p-1))) if n>p+1 else np.nan
    return b,r2,adj,se

def predict(df,b,features):
    Z=np.column_stack([np.ones(len(df))]+[df[c].to_numpy(float) for c in features])
    return Z@b

def metrics(y,p):
    y=np.asarray(y,float);p=np.asarray(p,float)
    ok=np.isfinite(y)&np.isfinite(p);y=y[ok];p=p[ok]
    if not len(y): return {'n':0}
    e=p-y
    return {
        'n':int(len(y)),
        'mae_pp':float(np.mean(np.abs(e))*100),
        'rmse_pp':float(np.sqrt(np.mean(e*e))*100),
        'bias_pp':float(np.mean(e)*100),
        'direction_accuracy':float(np.mean(np.sign(p)==np.sign(y))),
    }

def vc_metrics(real,est):
    real=np.asarray(real,float);est=np.asarray(est,float)
    ok=np.isfinite(real)&np.isfinite(est);real=real[ok];est=est[ok]
    if not len(real): return {'n':0}
    pct=(est-real)/real
    return {
        'n':int(len(real)),
        'mae_pct':float(np.mean(np.abs(pct))*100),
        'rmse_pct':float(np.sqrt(np.mean(pct*pct))*100),
        'bias_pct':float(np.mean(pct)*100),
    }

def main():
    d=read_fixed()
    for t in ['GLD','GDX']:
        d=d.merge(fetch_ret(t),on='fecha',how='left')

    result={
        'training':[TRAIN_START.date().isoformat(),TRAIN_END.date().isoformat()],
        'validation_start':'2026-07-28',
        'models':{},
    }
    daily=[]

    for name,extra in MODELS.items():
        features=BASE+extra
        tr=d[(d.fecha>=TRAIN_START)&(d.fecha<=TRAIN_END)].dropna(subset=['target_ret']+features).copy()
        va=d[d.fecha>TRAIN_END].dropna(subset=['target_ret','vc_sbs','vc_prev_real']+features).copy()
        b,r2,adj,se=fit_ols(tr,features)
        va['pred_ret']=predict(va,b,features)
        va['vc_est']=va['vc_prev_real']*(1+va['pred_ret'])
        va['err_vc_pct']=(va['vc_est']-va['vc_sbs'])/va['vc_sbs']*100
        va['err_ret_pp']=(va['pred_ret']-va['target_ret'])*100
        result['models'][name]={
            'features':features,
            'train_n':int(len(tr)),
            'r2':float(r2),
            'adj_r2':float(adj),
            'standard_error':float(se),
            'coefficients':{'intercept':float(b[0]),**{c:float(v) for c,v in zip(features,b[1:])}},
            'validation_return':metrics(va['target_ret'],va['pred_ret']),
            'validation_vc':vc_metrics(va['vc_sbs'],va['vc_est']),
            'validation_n':int(len(va)),
            'validation_end':va['fecha'].max().date().isoformat() if len(va) else None,
        }
        for _,r in va.iterrows():
            daily.append({
                'model':name,
                'fecha':r['fecha'].date().isoformat(),
                'vc_prev_real':float(r['vc_prev_real']),
                'ret_real_pct':float(r['target_ret']*100),
                'ret_est_pct':float(r['pred_ret']*100),
                'vc_real':float(r['vc_sbs']),
                'vc_est':float(r['vc_est']),
                'error_vc_pct':float(r['err_vc_pct']),
            })

    # compact comparisons against BASE5
    base=result['models']['BASE5']
    for name,m in result['models'].items():
        if name=='BASE5':
            m['vs_base5']={'mae_vc_reduction_pct':0.0,'rmse_vc_reduction_pct':0.0}
        else:
            bma=base['validation_vc']['mae_pct'];brm=base['validation_vc']['rmse_pct']
            mma=m['validation_vc']['mae_pct'];mrm=m['validation_vc']['rmse_pct']
            m['vs_base5']={
                'mae_vc_reduction_pct':float(100*(bma-mma)/bma) if bma else None,
                'rmse_vc_reduction_pct':float(100*(brm-mrm)/brm) if brm else None,
            }

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    pd.DataFrame(daily).to_csv(OUTCSV,index=False)
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':
    main()
