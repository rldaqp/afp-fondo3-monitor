from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd
import yfinance as yf

ROOT=Path(__file__).resolve().parents[1]
FIXED=ROOT/'public/data/fixed_models_2026.csv'
GDX_DAILY=ROOT/'analysis/gdx_walkforward30_daily.csv'
OUT=ROOT/'analysis/separate_gdx_pe_walkforward.json'
OUTCSV=ROOT/'analysis/separate_gdx_pe_walkforward_daily.csv'
BASE=['ret_SPY','ret_EEM','ret_MCHI','ret_QQQ','ret_SPBLSCUP']
PE_THRESH=1.5


def metrics(err):
    x=np.asarray(pd.Series(err).dropna(),float)
    return {'n':int(len(x)),'mae_pct':float(np.mean(np.abs(x))),
            'rmse_pct':float(np.sqrt(np.mean(x*x))), 'bias_pct':float(np.mean(x))}

def improve(base,cand):
    return {'mae_reduction_pct':100*(base['mae_pct']-cand['mae_pct'])/base['mae_pct'],
            'rmse_reduction_pct':100*(base['rmse_pct']-cand['rmse_pct'])/base['rmse_pct']}

def fit_ols(df,features):
    X=np.column_stack([np.ones(len(df))]+[df[c].to_numpy(float) for c in features])
    y=df.target_ret.to_numpy(float)
    b=np.linalg.lstsq(X,y,rcond=None)[0]
    pred=X@b
    ssr=np.sum((y-pred)**2); sst=np.sum((y-y.mean())**2)
    r2=1-ssr/sst if sst>0 else np.nan
    n=len(y); k=len(features)
    adj=1-(1-r2)*(n-1)/(n-k-1) if n>k+1 else np.nan
    return b,pred,float(r2),float(adj)

def fetch_epu():
    q=yf.download('EPU',start='2025-12-01',end='2026-09-02',auto_adjust=False,progress=False,threads=False)
    if isinstance(q.columns,pd.MultiIndex): q.columns=q.columns.get_level_values(0)
    c='Adj Close' if 'Adj Close' in q.columns else 'Close'
    s=pd.to_numeric(q[c],errors='coerce').dropna()
    return pd.DataFrame({'fecha':pd.to_datetime(s.index).tz_localize(None).normalize(),'EPU':s.values})

def sgn(x): return 1 if x>0 else (-1 if x<0 else 0)

def main():
    d=pd.read_csv(FIXED)
    d['fecha']=pd.to_datetime(d['fecha']).dt.normalize()
    d=d.sort_values('fecha').drop_duplicates('fecha',keep='last')
    for c in ['SPY','EEM','MCHI','QQQ','SPBLSCUP','vc_sbs']:
        d[c]=pd.to_numeric(d[c],errors='coerce')
    # known corrected SBS latest used by project
    corr={pd.Timestamp('2026-08-14'):70.8740985,pd.Timestamp('2026-08-17'):71.5395979,pd.Timestamp('2026-08-27'):72.3323679}
    for dt,val in corr.items(): d.loc[d.fecha.eq(dt),'vc_sbs']=val
    for c in ['SPY','EEM','MCHI','QQQ','SPBLSCUP']:
        d['ret_'+c]=d[c].pct_change(fill_method=None)
    d['target_ret']=d.vc_sbs/d.vc_sbs.shift(1)-1
    d=d.merge(fetch_epu(),on='fecha',how='left')
    d['ret_EPU']=d.EPU.pct_change(fill_method=None)
    d['spread_pe']=d.ret_EPU-d.ret_SPBLSCUP
    # strict prior-30 z: current observation not in mean/sd
    d['pe_mean30']=d.spread_pe.rolling(30,min_periods=30).mean().shift(1)
    d['pe_sd30']=d.spread_pe.rolling(30,min_periods=30).std(ddof=1).shift(1)
    d['z_pe']=(d.spread_pe-d.pe_mean30)/d.pe_sd30
    d['x_pe']=d.z_pe.where(d.z_pe.abs()>=PE_THRESH,0.0)

    gd=pd.read_csv(GDX_DAILY)
    gd['fecha']=pd.to_datetime(gd.fecha).dt.normalize()
    # GDX current candidate: abs>=1% and at least 2/3 EEM MCHI SPBL same sign
    gd['gdx_signal_1pct']=gd.apply(lambda r: abs(r.ret_GDX_pct)>=1.0 and sum(sgn(r[c])==sgn(r.ret_GDX_pct) and sgn(r.ret_GDX_pct)!=0 for c in ['ret_EEM_pct','ret_MCHI_pct','ret_SPBLSCUP_pct'])>=2,axis=1)
    gd['err_gdx_signal_pct']=np.where(gd.gdx_signal_1pct,gd.error_gdx_pct,gd.error_base_pct)

    rows=[]
    r2s=[]
    for _,gr in gd.iterrows():
        dt=gr.fecha
        hist=d[(d.fecha<dt)&d.vc_sbs.notna()].dropna(subset=['target_ret']+BASE).tail(30).copy()
        cur=d[d.fecha.eq(dt)].copy()
        if len(hist)!=30 or len(cur)!=1: continue
        cur=cur.iloc[0]
        if not all(pd.notna(cur[c]) for c in BASE): continue
        b,pfit,r2,adj=fit_ols(hist,BASE)
        resid_pp=(hist.target_ret.to_numpy(float)-pfit)*100
        x=hist.x_pe.fillna(0).to_numpy(float)
        den=float(np.dot(x,x)); gamma=float(np.dot(x,resid_pp)/den) if den>0 else 0.0
        xt=float(cur.x_pe) if pd.notna(cur.x_pe) else 0.0
        xb=np.array([1.0]+[float(cur[c]) for c in BASE])
        ret_base=float(xb@b)
        ret_pe=ret_base+(gamma*xt)/100.0
        prev=hist.iloc[-1]
        prev_vc=float(prev.vc_sbs)
        actual=float(cur.vc_sbs) if pd.notna(cur.vc_sbs) else np.nan
        vc_base=prev_vc*(1+ret_base); vc_pe=prev_vc*(1+ret_pe)
        eb=(vc_base/actual-1)*100 if np.isfinite(actual) else np.nan
        ep=(vc_pe/actual-1)*100 if np.isfinite(actual) else np.nan
        # training R2 after PE residual correction
        fit_pe=pfit+(gamma*x)/100.0
        y=hist.target_ret.to_numpy(float); ssr=np.sum((y-fit_pe)**2); sst=np.sum((y-y.mean())**2)
        r2pe=1-ssr/sst if sst>0 else np.nan
        # adjusted R2 treat PE layer as one extra fitted parameter
        n=len(y); k=6
        adjpe=1-(1-r2pe)*(n-1)/(n-k-1) if n>k+1 else np.nan
        r2s.append((r2,adj,r2pe,adjpe))
        rows.append({'fecha':str(dt.date()),'vc_real':actual,'vc_prev_real':prev_vc,
                     'error_base_pct':eb,'error_pe_pct':ep,'z_pe':float(cur.z_pe) if pd.notna(cur.z_pe) else None,
                     'pe_active':bool(abs(xt)>0),'gamma_pe_pp_per_z':gamma,
                     'train_r2_base':r2,'train_adj_r2_base':adj,'train_r2_pe':r2pe,'train_adj_r2_pe':adjpe})
    pe=pd.DataFrame(rows)
    # align exact common dates with GDX historical test
    g=gd[['fecha','error_base_pct','error_gdx_pct','err_gdx_signal_pct','gdx_signal_1pct']].copy()
    g['fecha']=g.fecha.dt.strftime('%Y-%m-%d')
    allx=pe.merge(g,on='fecha',how='inner',suffixes=('_pebase','_gbase'))
    # base from two independent computations should be nearly identical; use PE recomputation base for fair PE and original rolling base for GDX
    base=metrics(allx.error_base_pct_pebase)
    pe_m=metrics(allx.error_pe_pct)
    gbase=metrics(allx.error_base_pct_gbase)
    galways=metrics(allx.error_gdx_pct)
    gsig=metrics(allx.err_gdx_signal_pct)
    pe_active=allx[allx.pe_active]
    g_active=allx[allx.gdx_signal_1pct]
    result={
      'design':'Strict rolling-30 walk-forward. Each target uses only prior observations. GDX and PE rules evaluated separately.',
      'period':[allx.fecha.min(),allx.fecha.max()],'n':int(len(allx)),
      'gdx_rule':'Base+GDX only when |GDX|>=1% and >=2 of EEM/MCHI/SPBLSCUP share GDX sign.',
      'pe_rule':'Base plus gamma*x_PE where x_PE=z(EPU-SPBLSCUP) only for |z|>=1.5; z and gamma prior-only.',
      'gdx':{'base':gbase,'always':galways,'always_vs_base':improve(gbase,galways),'signal':gsig,'signal_vs_base':improve(gbase,gsig),
             'signals':int(g_active.shape[0]),'signal_wins':int((g_active.error_gdx_pct.abs()<g_active.error_base_pct_gbase.abs()).sum()),
             'signal_losses':int((g_active.error_gdx_pct.abs()>g_active.error_base_pct_gbase.abs()).sum())},
      'pe':{'base':base,'rule':pe_m,'rule_vs_base':improve(base,pe_m),'signals':int(pe_active.shape[0]),
            'signal_wins':int((pe_active.error_pe_pct.abs()<pe_active.error_base_pct_pebase.abs()).sum()),
            'signal_losses':int((pe_active.error_pe_pct.abs()>pe_active.error_base_pct_pebase.abs()).sum()),
            'signal_base':metrics(pe_active.error_base_pct_pebase) if len(pe_active) else None,
            'signal_rule':metrics(pe_active.error_pe_pct) if len(pe_active) else None},
      'rolling_training_fit':{
          'avg_r2_base':float(np.mean([x[0] for x in r2s])),'avg_adj_r2_base':float(np.mean([x[1] for x in r2s])),
          'avg_r2_pe':float(np.mean([x[2] for x in r2s])),'avg_adj_r2_pe':float(np.mean([x[3] for x in r2s])),
          'pe_adj_r2_better_windows':int(sum(x[3]>x[1] for x in r2s)),'total_windows':len(r2s)},
      'monthly':{}
    }
    for m,grp in allx.assign(month=lambda z:z.fecha.str[:7]).groupby('month'):
        bm=metrics(grp.error_base_pct_pebase); pm=metrics(grp.error_pe_pct)
        gb=metrics(grp.error_base_pct_gbase); gs=metrics(grp.err_gdx_signal_pct)
        result['monthly'][m]={'n':int(len(grp)),'gdx_signal_mae_reduction_pct':improve(gb,gs)['mae_reduction_pct'],
                              'pe_mae_reduction_pct':improve(bm,pm)['mae_reduction_pct'],
                              'gdx_signals':int(grp.gdx_signal_1pct.sum()),'pe_signals':int(grp.pe_active.sum())}
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    allx.to_csv(OUTCSV,index=False)
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__': main()
