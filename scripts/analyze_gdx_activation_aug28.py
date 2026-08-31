from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd
import yfinance as yf

ROOT=Path(__file__).resolve().parents[1]
FIXED=ROOT/'public/data/fixed_models_2026.csv'
OUT=ROOT/'analysis/gdx_activation_aug28.json'
OUTCSV=ROOT/'analysis/gdx_activation_aug28_daily.csv'
TRAIN_START=pd.Timestamp('2026-07-07')
TRAIN_END=pd.Timestamp('2026-08-17')
BASE=['ret_SPY','ret_EEM','ret_MCHI','ret_QQQ','ret_SPBLSCUP']
EXTRA=['GDX','GLD','EPU','NEM','FCX','USO']
SBS_MANUAL={pd.Timestamp('2026-08-27'):72.3323679}

def fetch_ret(t):
    q=yf.download(t,start='2026-06-25',end='2026-09-02',auto_adjust=False,progress=False,threads=False)
    if q.empty: return pd.DataFrame(columns=['fecha','ret_'+t])
    if isinstance(q.columns,pd.MultiIndex): q.columns=q.columns.get_level_values(0)
    c='Adj Close' if 'Adj Close' in q.columns else 'Close'
    s=pd.to_numeric(q[c],errors='coerce').dropna()
    r=s.pct_change(fill_method=None)
    return pd.DataFrame({'fecha':pd.to_datetime(r.index).tz_localize(None).normalize(),'ret_'+t:r.values})

def fit_beta(d,features):
    tr=d[(d.fecha>=TRAIN_START)&(d.fecha<=TRAIN_END)].dropna(subset=['target_ret']+features).copy()
    X=np.column_stack([np.ones(len(tr))]+[tr[c].to_numpy(float) for c in features])
    y=tr.target_ret.to_numpy(float)
    b=np.linalg.lstsq(X,y,rcond=None)[0]
    p=X@b
    ssr=np.sum((y-p)**2); sst=np.sum((y-y.mean())**2)
    r2=1-ssr/sst
    n=len(y); k=len(features)
    adj=1-(1-r2)*(n-1)/(n-k-1)
    se=np.sqrt(ssr/(n-k-1))
    return tr,b,{'n':n,'r2':float(r2),'adj_r2':float(adj),'standard_error':float(se)}

def pred_row(r,b,features):
    x=np.array([1.0]+[float(r[c]) for c in features])
    return float(x@b)

def main():
    d=pd.read_csv(FIXED)
    d['fecha']=pd.to_datetime(d['fecha']).dt.normalize()
    d=d.sort_values('fecha').drop_duplicates('fecha',keep='last')
    for c in ['SPY','EEM','MCHI','QQQ','SPBLSCUP','vc_sbs']:
        d[c]=pd.to_numeric(d[c],errors='coerce')
    for dt,val in SBS_MANUAL.items():
        d.loc[d.fecha.eq(dt),'vc_sbs']=val
    for c in ['SPY','EEM','MCHI','QQQ','SPBLSCUP']:
        d['ret_'+c]=d[c].pct_change(fill_method=None)
    d['target_ret']=d['vc_sbs']/d['vc_sbs'].shift(1)-1
    for t in EXTRA:
        d=d.merge(fetch_ret(t),on='fecha',how='left')

    tr0,b0,st0=fit_beta(d,BASE)
    trg,bg,stg=fit_beta(d,BASE+['ret_GDX'])

    rows=[]
    for _,r in d[d.fecha>TRAIN_END].iterrows():
        if not all(pd.notna(r[c]) for c in BASE+['ret_GDX']): continue
        rb=pred_row(r,b0,BASE); rg=pred_row(r,bg,BASE+['ret_GDX'])
        prev=d[d.fecha<r.fecha].dropna(subset=['vc_sbs']).tail(1)
        prev_vc=float(prev.vc_sbs.iloc[0]) if len(prev) else np.nan
        prev_date=str(prev.fecha.iloc[0].date()) if len(prev) else None
        vb=prev_vc*(1+rb) if np.isfinite(prev_vc) else np.nan
        vg=prev_vc*(1+rg) if np.isfinite(prev_vc) else np.nan
        actual=float(r.vc_sbs) if pd.notna(r.vc_sbs) else np.nan
        eb=(vb/actual-1)*100 if np.isfinite(actual) else np.nan
        eg=(vg/actual-1)*100 if np.isfinite(actual) else np.nan
        row={'fecha':str(r.fecha.date()),'prev_sbs_date':prev_date,'vc_prev_real':prev_vc,'vc_real':actual if np.isfinite(actual) else None,
             'ret_base_pct':rb*100,'ret_gdx_pct':rg*100,'vc_base':vb,'vc_gdx':vg,
             'error_base_pct':eb if np.isfinite(eb) else None,'error_gdx_pct':eg if np.isfinite(eg) else None,
             'gdx_improves': bool(abs(eg)<abs(eb)) if np.isfinite(eg) else None}
        for c in BASE+['ret_GDX','ret_GLD','ret_EPU','ret_NEM','ret_FCX','ret_USO']:
            row[c]=float(r[c]*100) if pd.notna(r[c]) else None
        if pd.notna(r.get('ret_GLD')): row['gdx_minus_gld_pp']=(float(r['ret_GDX'])-float(r['ret_GLD']))*100
        row['qqq_minus_spy_pp']=(float(r['ret_QQQ'])-float(r['ret_SPY']))*100
        rows.append(row)
    q=pd.DataFrame(rows)
    known=q[q.vc_real.notna()].copy()
    def met(errcol):
        x=known[errcol].dropna().to_numpy(float)
        return {'n':int(len(x)),'mae_pct':float(np.mean(np.abs(x))),'rmse_pct':float(np.sqrt(np.mean(x*x))),'bias_pct':float(np.mean(x))}
    mb=met('error_base_pct'); mg=met('error_gdx_pct')
    improve={'mae_reduction_pct':100*(mb['mae_pct']-mg['mae_pct'])/mb['mae_pct'],
             'rmse_reduction_pct':100*(mb['rmse_pct']-mg['rmse_pct'])/mb['rmse_pct']}
    context_cols=['ret_GDX','ret_GLD','gdx_minus_gld_pp','ret_EPU','ret_NEM','ret_FCX','ret_USO','ret_SPY','ret_QQQ','qqq_minus_spy_pp','ret_EEM','ret_MCHI','ret_SPBLSCUP']
    groups={}
    for flag,name in [(True,'improves'),(False,'worsens')]:
        z=known[known.gdx_improves.eq(flag)]
        groups[name]={'n':int(len(z)),'dates':z.fecha.tolist(),'means_pct_or_pp':{c:(float(z[c].mean()) if c in z and z[c].notna().any() else None) for c in context_cols}}
    result={'training':['2026-07-07','2026-08-17'],'base5_training':st0,'gdx_training':stg,
            'base5_coefficients':{'intercept':float(b0[0]),**{c:float(v) for c,v in zip(BASE,b0[1:])}},
            'gdx_coefficients':{'intercept':float(bg[0]),**{c:float(v) for c,v in zip(BASE+['ret_GDX'],bg[1:])}},
            'known_oos_metrics':{'base':mb,'gdx':mg,'improvement':improve},'groups':groups,
            'rows':rows,'note':'27/08 SBS manual verificado en pagina oficial; 28/08 se calcula reanclado al 27 real y queda sin error si SBS 28 no esta disponible.'}
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    q.to_csv(OUTCSV,index=False)
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__': main()
