from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd
import yfinance as yf

ROOT=Path(__file__).resolve().parents[1]
FIXED=ROOT/'public/data/fixed_models_2026.csv'
OUT=ROOT/'analysis/gold_candidates_test.json'
OUTCSV=ROOT/'analysis/gold_candidates_test.csv'
TRAIN_START=pd.Timestamp('2026-07-07')
TRAIN_END=pd.Timestamp('2026-08-17')
BASE=['ret_SPY','ret_EEM','ret_MCHI','ret_QQQ','ret_SPBLSCUP']
CAND=['GLD','GDX']

def read_fixed():
    d=pd.read_csv(FIXED)
    d['fecha']=pd.to_datetime(d['fecha']).dt.normalize()
    d=d.sort_values('fecha').drop_duplicates('fecha',keep='last')
    for c in ['SPY','EEM','MCHI','QQQ','SPBLSCUP','vc_sbs','ret_vc_estimado']:
        d[c]=pd.to_numeric(d[c],errors='coerce')
    for c in ['SPY','EEM','MCHI','QQQ','SPBLSCUP']:
        d['ret_'+c]=d[c].pct_change(fill_method=None)
    d['target_ret']=d['vc_sbs']/d['vc_sbs'].shift(1)-1
    d['base_ret_fixed']=d['ret_vc_estimado']
    return d

def fetch_ret(ticker):
    q=yf.download(ticker,start='2025-12-01',end='2026-09-03',auto_adjust=False,progress=False,threads=False)
    if q.empty:
        return pd.DataFrame(columns=['fecha','ret_'+ticker])
    if isinstance(q.columns,pd.MultiIndex):
        q.columns=q.columns.get_level_values(0)
    col='Adj Close' if 'Adj Close' in q.columns else 'Close'
    s=pd.to_numeric(q[col],errors='coerce').dropna()
    r=s.pct_change(fill_method=None)
    return pd.DataFrame({'fecha':pd.to_datetime(r.index).tz_localize(None).normalize(),'ret_'+ticker:r.values})

def metrics(y,p):
    y=np.asarray(y,float); p=np.asarray(p,float)
    ok=np.isfinite(y)&np.isfinite(p); y=y[ok]; p=p[ok]
    if not len(y): return {'n':0}
    e=p-y
    return {'n':int(len(y)),'mae_pp':float(np.mean(np.abs(e))*100),'rmse_pp':float(np.sqrt(np.mean(e*e))*100),'bias_pp':float(np.mean(e)*100),'direction_accuracy':float(np.mean(np.sign(p)==np.sign(y)))}

def improve(a,b):
    if not a.get('n') or not b.get('n'): return {'mae_reduction_pct':None,'rmse_reduction_pct':None}
    return {'mae_reduction_pct':float(100*(a['mae_pp']-b['mae_pp'])/a['mae_pp']) if a['mae_pp'] else None,
            'rmse_reduction_pct':float(100*(a['rmse_pp']-b['rmse_pp'])/a['rmse_pp']) if a['rmse_pp'] else None}

def gamma0(x,r):
    x=np.asarray(x,float); r=np.asarray(r,float); ok=np.isfinite(x)&np.isfinite(r); x=x[ok]; r=r[ok]
    den=np.dot(x,x)
    return float(np.dot(x,r)/den) if len(x) and den>0 else np.nan

def overlay(d,c):
    tr=d[(d.fecha>=TRAIN_START)&(d.fecha<=TRAIN_END)].dropna(subset=['target_ret','base_ret_fixed',c]).copy()
    pre=d[d.fecha<TRAIN_START].dropna(subset=['target_ret','base_ret_fixed',c]).copy()
    oos=d[d.fecha>TRAIN_END].dropna(subset=['target_ret','base_ret_fixed',c]).copy()
    resid=(tr.target_ret-tr.base_ret_fixed).to_numpy(); x=tr[c].to_numpy(); g=gamma0(x,resid)
    loo=[]
    for i in range(len(tr)):
        mask=np.ones(len(tr),dtype=bool); mask[i]=False
        gi=gamma0(x[mask],resid[mask])
        loo.append(tr.base_ret_fixed.iloc[i]+gi*x[i])
    mb=metrics(tr.target_ret,tr.base_ret_fixed); ml=metrics(tr.target_ret,np.array(loo))
    out={'gamma':g,'train_loo_base':mb,'train_loo_corrected':ml,'train_loo_improvement':improve(mb,ml)}
    for name,q in [('pre',pre),('oos',oos)]:
        b=metrics(q.target_ret,q.base_ret_fixed)
        m=metrics(q.target_ret,q.base_ret_fixed+g*q[c])
        out[name]={'base':b,'corrected':m,'improvement':improve(b,m)}
    return out

def fit(train,test,features):
    X=np.column_stack([np.ones(len(train))]+[train[c].to_numpy() for c in features])
    y=train.target_ret.to_numpy()
    b=np.linalg.lstsq(X,y,rcond=None)[0]
    Z=np.column_stack([np.ones(len(test))]+[test[c].to_numpy() for c in features])
    return b,Z@b

def ols_compare(d,extra):
    cols=BASE+extra
    tr=d[(d.fecha>=TRAIN_START)&(d.fecha<=TRAIN_END)].dropna(subset=['target_ret']+cols).copy()
    oo=d[d.fecha>TRAIN_END].dropna(subset=['target_ret']+cols).copy()
    b0,p0=fit(tr,oo,BASE)
    bx,px=fit(tr,oo,cols)
    m0=metrics(oo.target_ret,p0); mx=metrics(oo.target_ret,px)
    return {'features':extra,'train_n':int(len(tr)),'oos_n':int(len(oo)),'base5_oos':m0,'candidate_oos':mx,'improvement':improve(m0,mx),'coefficients':{'intercept':float(bx[0]),**{c:float(v) for c,v in zip(cols,bx[1:])}}}

def main():
    d=read_fixed()
    for t in CAND:
        d=d.merge(fetch_ret(t),on='fecha',how='left')
    result={'model_version':'v2-sbs-corrected-20260831','training':['2026-07-07','2026-08-17'],'overlay':{},'ols':{}}
    for t in CAND:
        result['overlay'][t]=overlay(d,'ret_'+t)
        result['ols'][t]=ols_compare(d,['ret_'+t])
    result['ols']['GLD_GDX']=ols_compare(d,['ret_GLD','ret_GDX'])
    tr=d[(d.fecha>=TRAIN_START)&(d.fecha<=TRAIN_END)].dropna(subset=['ret_GLD','ret_GDX'])
    result['train_corr_GLD_GDX']=float(tr['ret_GLD'].corr(tr['ret_GDX']))
    rows=[]
    for name,r in result['ols'].items():
        rows.append({'model':name,'oos_n':r['oos_n'],'mae_base_pp':r['base5_oos']['mae_pp'],'mae_candidate_pp':r['candidate_oos']['mae_pp'],'mae_reduction_pct':r['improvement']['mae_reduction_pct'],'rmse_base_pp':r['base5_oos']['rmse_pp'],'rmse_candidate_pp':r['candidate_oos']['rmse_pp'],'rmse_reduction_pct':r['improvement']['rmse_reduction_pct']})
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    pd.DataFrame(rows).to_csv(OUTCSV,index=False)
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__': main()
