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
    d['vc_prev_real']=d['vc_sbs'].shift(1)
    d['target_ret']=d['vc_sbs']/d['vc_prev_real']-1
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

def design(df,features):
    return np.column_stack([np.ones(len(df))]+[df[c].to_numpy() for c in features])

def fit_coeff(train,features):
    X=design(train,features); y=train.target_ret.to_numpy()
    return np.linalg.lstsq(X,y,rcond=None)[0]

def predict(df,features,b):
    return design(df,features)@b

def fit_stats(train,features,b):
    y=train.target_ret.to_numpy(); p=predict(train,features,b)
    resid=y-p; sse=float(np.dot(resid,resid)); sst=float(np.dot(y-y.mean(),y-y.mean()))
    r2=1-sse/sst if sst>0 else np.nan
    n=len(y); k=len(features)
    adj=1-(1-r2)*(n-1)/(n-k-1) if n>k+1 else np.nan
    se=float(np.sqrt(sse/(n-k-1))) if n>k+1 else np.nan
    return {'n':int(n),'r2':float(r2),'adj_r2':float(adj),'standard_error':se}

def vc_metrics(q,p):
    vc_est=q.vc_prev_real.to_numpy()*(1+np.asarray(p,float)); vc=q.vc_sbs.to_numpy()
    ok=np.isfinite(vc_est)&np.isfinite(vc)&(vc!=0); e=(vc_est[ok]/vc[ok]-1)*100
    return {'n':int(ok.sum()),'mae_pct':float(np.mean(np.abs(e))),'rmse_pct':float(np.sqrt(np.mean(e*e))),'bias_pct':float(np.mean(e))}

def ols_compare(d,extra):
    cols=BASE+extra
    tr=d[(d.fecha>=TRAIN_START)&(d.fecha<=TRAIN_END)].dropna(subset=['target_ret']+cols).copy()
    oo=d[d.fecha>TRAIN_END].dropna(subset=['target_ret','vc_prev_real','vc_sbs']+cols).copy()
    b0=fit_coeff(tr,BASE); bx=fit_coeff(tr,cols)
    p0=predict(oo,BASE,b0); px=predict(oo,cols,bx)
    m0=metrics(oo.target_ret,p0); mx=metrics(oo.target_ret,px)
    v0=vc_metrics(oo,p0); vx=vc_metrics(oo,px)
    rows=[]
    for i,(_,r) in enumerate(oo.iterrows()):
        vc0=float(r.vc_prev_real*(1+p0[i])); vcx=float(r.vc_prev_real*(1+px[i])); real=float(r.vc_sbs)
        rows.append({'fecha':r.fecha.strftime('%Y-%m-%d'),'vc_prev_real':float(r.vc_prev_real),'vc_real':real,
                     'ret_real_pct':float(r.target_ret*100),'ret_base_pct':float(p0[i]*100),'ret_candidate_pct':float(px[i]*100),
                     'vc_base':vc0,'vc_candidate':vcx,'error_base_pct':float((vc0/real-1)*100),'error_candidate_pct':float((vcx/real-1)*100)})
    return {
        'features':extra,'train_n':int(len(tr)),'oos_n':int(len(oo)),
        'base5_training':fit_stats(tr,BASE,b0),'candidate_training':fit_stats(tr,cols,bx),
        'base5_oos':m0,'candidate_oos':mx,'improvement':improve(m0,mx),
        'base5_vc_oos':v0,'candidate_vc_oos':vx,
        'base5_coefficients':{'intercept':float(b0[0]),**{c:float(v) for c,v in zip(BASE,b0[1:])}},
        'coefficients':{'intercept':float(bx[0]),**{c:float(v) for c,v in zip(cols,bx[1:])}},
        'oos_rows':rows
    }

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
        rows.append({'model':name,'train_n':r['train_n'],'r2':r['candidate_training']['r2'],'adj_r2':r['candidate_training']['adj_r2'],
                     'oos_n':r['oos_n'],'mae_base_pp':r['base5_oos']['mae_pp'],'mae_candidate_pp':r['candidate_oos']['mae_pp'],
                     'mae_reduction_pct':r['improvement']['mae_reduction_pct'],'rmse_base_pp':r['base5_oos']['rmse_pp'],
                     'rmse_candidate_pp':r['candidate_oos']['rmse_pp'],'rmse_reduction_pct':r['improvement']['rmse_reduction_pct'],
                     'vc_mae_base_pct':r['base5_vc_oos']['mae_pct'],'vc_mae_candidate_pct':r['candidate_vc_oos']['mae_pct']})
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    pd.DataFrame(rows).to_csv(OUTCSV,index=False)
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__': main()
