from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd
import yfinance as yf

ROOT=Path(__file__).resolve().parents[1]
SRC=ROOT/'public/data/fixed_models_2026.csv'
OUT=ROOT/'analysis/combined_gdx_pe_rule.json'
OUTCSV=ROOT/'analysis/combined_gdx_pe_rule_daily.csv'
TRAIN_START=pd.Timestamp('2026-07-07')
TRAIN_END=pd.Timestamp('2026-08-17')
BASE=['ret_SPY','ret_EEM','ret_MCHI','ret_QQQ','ret_SPBLSCUP']
CORE=['ret_EEM','ret_MCHI','ret_SPBLSCUP']
PE_THRESHOLD=1.5
GDX_MAG=0.01
SBS_MANUAL={pd.Timestamp('2026-08-27'):72.3323679}

def fetch_ret(ticker):
    q=yf.download(ticker,start='2026-05-01',end='2026-09-02',auto_adjust=False,progress=False,threads=False)
    if q.empty:
        return pd.DataFrame(columns=['fecha',f'ret_{ticker}'])
    if isinstance(q.columns,pd.MultiIndex): q.columns=q.columns.get_level_values(0)
    c='Adj Close' if 'Adj Close' in q.columns else 'Close'
    s=pd.to_numeric(q[c],errors='coerce').dropna()
    r=s.pct_change(fill_method=None)
    return pd.DataFrame({'fecha':pd.to_datetime(r.index).tz_localize(None).normalize(),f'ret_{ticker}':r.values})

def ols(d,features):
    X=np.column_stack([np.ones(len(d))]+[d[c].to_numpy(float) for c in features])
    y=d.target_ret.to_numpy(float)
    b=np.linalg.lstsq(X,y,rcond=None)[0]
    p=X@b
    ssr=float(np.sum((y-p)**2)); sst=float(np.sum((y-y.mean())**2))
    r2=1-ssr/sst
    return b,p,r2

def predict(df,b,features):
    X=np.column_stack([np.ones(len(df))]+[df[c].to_numpy(float) for c in features])
    return X@b

def r2_score(y,p):
    y=np.asarray(y,float); p=np.asarray(p,float)
    return float(1-np.sum((y-p)**2)/np.sum((y-y.mean())**2))

def metrics(err):
    x=np.asarray(err,float)
    return {'n':int(len(x)),'mae_pct':float(np.mean(np.abs(x))*100),'rmse_pct':float(np.sqrt(np.mean(x*x))*100),'bias_pct':float(np.mean(x)*100)}

def improvement(base,cand):
    return {'mae_reduction_pct':100*(base['mae_pct']-cand['mae_pct'])/base['mae_pct'],
            'rmse_reduction_pct':100*(base['rmse_pct']-cand['rmse_pct'])/base['rmse_pct']}

def same_sign(a,b):
    return (a>0 and b>0) or (a<0 and b<0)

def main():
    d=pd.read_csv(SRC)
    d['fecha']=pd.to_datetime(d['fecha']).dt.normalize()
    d=d.sort_values('fecha').drop_duplicates('fecha',keep='last')
    for c in ['SPY','EEM','MCHI','QQQ','SPBLSCUP','vc_sbs']:
        d[c]=pd.to_numeric(d[c],errors='coerce')
    for dt,v in SBS_MANUAL.items():
        d.loc[d.fecha.eq(dt),'vc_sbs']=v
    for c in ['SPY','EEM','MCHI','QQQ','SPBLSCUP']:
        d['ret_'+c]=d[c].pct_change(fill_method=None)
    d['target_ret']=d.vc_sbs/d.vc_sbs.shift(1)-1
    for t in ['GDX','EPU']:
        d=d.merge(fetch_ret(t),on='fecha',how='left')

    # PE spread z uses only prior 30 observations (shifted rolling stats)
    d['pe_spread']=d.ret_EPU-d.ret_SPBLSCUP
    d['pe_mu30_prior']=d.pe_spread.shift(1).rolling(30,min_periods=30).mean()
    d['pe_sd30_prior']=d.pe_spread.shift(1).rolling(30,min_periods=30).std(ddof=1)
    d['z_pe']=(d.pe_spread-d.pe_mu30_prior)/d.pe_sd30_prior
    d['x_pe']=d.z_pe.where(d.z_pe.abs()>=PE_THRESHOLD,0.0).fillna(0.0)

    tr=d[(d.fecha>=TRAIN_START)&(d.fecha<=TRAIN_END)].dropna(subset=['target_ret']+BASE+['ret_GDX','x_pe']).copy()
    assert len(tr)==30, len(tr)
    b0,p0,r20=ols(tr,BASE)
    bg,pg,r2g=ols(tr,BASE+['ret_GDX'])

    # contemporaneous GDX activation signal
    def gdx_flag(row):
        g=float(row.ret_GDX)
        if abs(g)<GDX_MAG or g==0: return False
        n=sum(same_sign(g,float(row[c])) for c in CORE)
        return n>=2
    tr['gdx_signal']=tr.apply(gdx_flag,axis=1)
    p_h=np.where(tr.gdx_signal.to_numpy(bool),pg,p0)

    # Fit PE gamma on base residual and on hybrid residual using training only.
    x=tr.x_pe.to_numpy(float)
    def gamma_from(resid):
        den=float(np.dot(x,x))
        return float(np.dot(x,resid)/den) if den>0 else 0.0
    gamma_base=gamma_from(tr.target_ret.to_numpy(float)-p0)
    gamma_gdx=gamma_from(tr.target_ret.to_numpy(float)-pg)
    gamma_hybrid=gamma_from(tr.target_ret.to_numpy(float)-p_h)
    p_base_pe=p0+gamma_base*x
    p_gdx_pe=pg+gamma_gdx*x
    p_combined=p_h+gamma_hybrid*x

    train_stats={
        'n':30,
        'base_r2':r20,
        'gdx_always_r2':r2g,
        'gdx_hybrid_r2':r2_score(tr.target_ret,p_h),
        'base_pe_r2':r2_score(tr.target_ret,p_base_pe),
        'gdx_always_pe_r2':r2_score(tr.target_ret,p_gdx_pe),
        'combined_hybrid_pe_r2':r2_score(tr.target_ret,p_combined),
        'gdx_signal_days':int(tr.gdx_signal.sum()),
        'pe_shock_days':int((tr.x_pe!=0).sum()),
        'gamma_pe_on_base_pp_per_z':gamma_base*100,
        'gamma_pe_on_gdx_pp_per_z':gamma_gdx*100,
        'gamma_pe_on_hybrid_pp_per_z':gamma_hybrid*100,
        'coeff_base':{'intercept':float(b0[0]),**{f:float(v) for f,v in zip(BASE,b0[1:])}},
        'coeff_gdx':{'intercept':float(bg[0]),**{f:float(v) for f,v in zip(BASE+['ret_GDX'],bg[1:])}},
    }

    oo=d[(d.fecha>TRAIN_END)&d.vc_sbs.notna()].dropna(subset=BASE+['ret_GDX','x_pe','target_ret']).copy()
    p0o=predict(oo,b0,BASE); pgo=predict(oo,bg,BASE+['ret_GDX'])
    oo['gdx_signal']=oo.apply(gdx_flag,axis=1)
    pho=np.where(oo.gdx_signal.to_numpy(bool),pgo,p0o)
    xo=oo.x_pe.to_numpy(float)
    preds={
        'base':p0o,
        'gdx_always':pgo,
        'gdx_signal':pho,
        'base_pe':p0o+gamma_base*xo,
        'gdx_always_pe':pgo+gamma_gdx*xo,
        'combined':pho+gamma_hybrid*xo,
    }
    # use real previous SBS row-by-row
    prev_map=[]
    for dt in oo.fecha:
        prev=d[(d.fecha<dt)&d.vc_sbs.notna()].tail(1)
        prev_map.append(float(prev.vc_sbs.iloc[0]))
    prev=np.array(prev_map,float); actual=oo.vc_sbs.to_numpy(float)
    actual_ret=oo.target_ret.to_numpy(float)
    outrows=[]; metric={}
    for name,p in preds.items():
        vc=prev*(1+p)
        err=vc/actual-1
        metric[name]=metrics(err)
    baseM=metric['base']
    for name in metric:
        if name!='base': metric[name]['vs_base']=improvement(baseM,metric[name])

    for i,(_,r) in enumerate(oo.iterrows()):
        row={'fecha':str(r.fecha.date()),'vc_real':float(r.vc_sbs),'vc_prev_real':float(prev[i]),
             'ret_real_pct':float(actual_ret[i]*100),'gdx_signal':bool(r.gdx_signal),
             'ret_GDX_pct':float(r.ret_GDX*100),'z_pe':float(r.z_pe) if pd.notna(r.z_pe) else None,
             'pe_active':bool(r.x_pe!=0),'ret_EPU_pct':float(r.ret_EPU*100),'ret_SPBLSCUP_pct':float(r.ret_SPBLSCUP*100),
             'ret_EEM_pct':float(r.ret_EEM*100),'ret_MCHI_pct':float(r.ret_MCHI*100)}
        for name,p in preds.items():
            vc=float(prev[i]*(1+p[i])); e=(vc/actual[i]-1)*100
            row[f'ret_{name}_pct']=float(p[i]*100); row[f'vc_{name}']=vc; row[f'err_{name}_pct']=float(e)
        outrows.append(row)

    res={'design':'Train all parameters only on 2026-07-07..2026-08-17 (30 sessions), freeze, validate 2026-08-18..2026-08-27 with real SBS VC.',
         'gdx_rule':'Use Base+GDX only if |GDX return| >= 1% and at least 2 of EEM/MCHI/SPBLSCUP share GDX sign; otherwise Base.',
         'pe_rule':'x_PE = z(EPU-SPBLSCUP spread vs prior 30 sessions) only when |z|>=1.5; gamma fitted on training residual only.',
         'training':train_stats,'oos_metrics':metric,'oos_n':int(len(oo)),'rows':outrows}
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(res,ensure_ascii=False,indent=2),encoding='utf-8')
    pd.DataFrame(outrows).to_csv(OUTCSV,index=False)
    print(json.dumps(res,ensure_ascii=False,indent=2))

if __name__=='__main__': main()
