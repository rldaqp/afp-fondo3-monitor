from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd
import yfinance as yf

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'data'/'rolling90'
OUT=ROOT/'analysis'/'custom_qqq_variants_20260818_20.json'
WINDOW=90
THRESHOLD=.001
DATES=[pd.Timestamp('2026-08-18'),pd.Timestamp('2026-08-19'),pd.Timestamp('2026-08-20')]
EXCLUDED_RETURN_DATES={pd.Timestamp('2026-07-06')}

def classify(v): return 'SUBE' if v>THRESHOLD else ('BAJA' if v<-THRESHOLD else 'NEUTRO')
def read_csv(p):
    d=pd.read_csv(p); d['fecha']=pd.to_datetime(d['fecha'],errors='coerce'); return d.dropna(subset=['fecha']).sort_values('fecha').drop_duplicates('fecha',keep='last').reset_index(drop=True)
def extract_close(raw,t):
    if isinstance(raw.columns,pd.MultiIndex):
        for k in [('Close',t),(t,'Close')]:
            if k in raw.columns:return pd.to_numeric(raw[k],errors='coerce').dropna()
        if 'Close' in raw.columns.get_level_values(0):
            b=raw.xs('Close',axis=1,level=0)
            if t in b.columns:return pd.to_numeric(b[t],errors='coerce').dropna()
    if 'Close' in raw.columns:return pd.to_numeric(raw['Close'],errors='coerce').dropna()
    return pd.Series(dtype=float)
def load_yahoo(t):
    raw=yf.download(t,start='2024-12-30',end='2026-08-22',auto_adjust=False,actions=False,progress=False,threads=False)
    s=extract_close(raw,t)
    idx=pd.to_datetime(s.index)
    if getattr(idx,'tz',None) is not None: idx=idx.tz_localize(None)
    d=pd.DataFrame({'fecha':idx.normalize(),t:s.to_numpy(float)}).sort_values('fecha').drop_duplicates('fecha',keep='last')
    d[f'ret_{t}']=d[t].pct_change(fill_method=None)
    return d

def fit(train,features,target='ret_target'):
    X=train[features].to_numpy(float); y=train[target].to_numpy(float)
    return np.linalg.lstsq(np.c_[np.ones(len(X)),X],y,rcond=None)[0]
def pred(beta,row,features): return float(np.r_[1.0,row[features].to_numpy(float)]@beta)

def calc_variant(markets,sbs,qqq,penx,features):
    # training dataset requires real SBS and historical BCRP FX
    hist=(sbs[['fecha','valor_cuota','ret_target']].merge(markets[['fecha',*features]],on='fecha',how='inner')
          .merge(qqq[['fecha','ret_QQQ']],on='fecha',how='inner').dropna(subset=['ret_target',*features,'ret_QQQ'])
          .sort_values('fecha').drop_duplicates('fecha',keep='last').reset_index(drop=True))
    out=[]; previous_est=None
    for dt in DATES:
        train=hist.loc[hist['fecha']<dt].tail(WINDOW).copy()
        if len(train)<WINDOW: raise RuntimeError(f'train insuficiente {dt}: {len(train)}')
        row=markets.loc[markets['fecha'].eq(dt),['fecha',*features]].copy()
        if row.empty: raise RuntimeError(f'falta mercado {dt}')
        # 20/08: BCRP aún puede faltar; usar PEN=X provisional solo para predicción pendiente
        if 'ret_USD_PEN' in features and pd.isna(row.iloc[0]['ret_USD_PEN']):
            px=penx.loc[penx['fecha'].eq(dt),'ret_PEN=X']
            if px.empty or not np.isfinite(float(px.iloc[0])): raise RuntimeError(f'falta FX provisional {dt}')
            row.loc[:,'ret_USD_PEN']=float(px.iloc[0])
        row=row.merge(qqq.loc[qqq['fecha'].eq(dt),['fecha','ret_QQQ']],on='fecha',how='inner')
        if row.empty or row[[*features,'ret_QQQ']].isna().any(axis=None): raise RuntimeError(f'factores incompletos {dt}')
        r=row.iloc[0]
        X=train[features].to_numpy(float); q=train['ret_QQQ'].to_numpy(float)
        qb=np.linalg.lstsq(np.c_[np.ones(len(X)),X],q,rcond=None)[0]
        train['ret_QQQ_resid']=q-np.c_[np.ones(len(X)),X]@qb
        qexp=float(np.r_[1.0,r[features].to_numpy(float)]@qb)
        qres=float(r['ret_QQQ']-qexp)
        qfeatures=features+['ret_QQQ_resid']
        b=fit(train,qfeatures)
        rr=r.copy(); rr['ret_QQQ_resid']=qres
        re=pred(b,rr,qfeatures)
        # Base: si existe SBS real del día anterior, usarlo; si no, encadenar el estimado previo.
        prev_date=dt-pd.Timedelta(days=1)
        real_prev=sbs.loc[sbs['fecha']<dt].sort_values('fecha').tail(1)
        if not real_prev.empty and pd.Timestamp(real_prev.iloc[0]['fecha'])>=pd.Timestamp('2026-08-17'):
            base=float(real_prev.iloc[0]['valor_cuota'])
            base_date=pd.Timestamp(real_prev.iloc[0]['fecha']).strftime('%Y-%m-%d')
            # para 20, si el último SBS sigue siendo 18, encadenar 19 estimado
            if dt==pd.Timestamp('2026-08-20') and pd.Timestamp(real_prev.iloc[0]['fecha'])<pd.Timestamp('2026-08-19') and previous_est is not None:
                base=float(previous_est); base_date='2026-08-19 estimado'
        else:
            if previous_est is None: raise RuntimeError('sin base')
            base=float(previous_est); base_date='estimado previo'
        vc=base*(1+re); previous_est=vc
        out.append({'fecha':dt.strftime('%Y-%m-%d'),'base_vc':base,'base_date':base_date,'return_estimated':re,'signal':classify(re),'vc_estimated':vc,'qqq_return':float(r['ret_QQQ']),'qqq_expected':qexp,'qqq_residual':qres,'fx_return_used':float(r['ret_USD_PEN']) if 'ret_USD_PEN' in features else None,'training_start':train.iloc[0]['fecha'].strftime('%Y-%m-%d'),'training_end':train.iloc[-1]['fecha'].strftime('%Y-%m-%d')})
    return out

def main():
    markets=read_csv(DATA/'markets.csv'); sbs=read_csv(DATA/'sbs_profuturo_f3.csv')
    sbs['valor_cuota']=pd.to_numeric(sbs['valor_cuota'],errors='coerce'); sbs=sbs.dropna(subset=['valor_cuota']).copy(); sbs['ret_target']=sbs['valor_cuota'].pct_change(fill_method=None)
    for d in EXCLUDED_RETURN_DATES: sbs.loc[sbs['fecha'].eq(d),'ret_target']=np.nan
    qqq=load_yahoo('QQQ'); penx=load_yahoo('PEN=X')
    a=['ret_SPY','ret_EEM','ret_EPU','ret_MCHI','ret_USD_PEN']
    b=['ret_SPY','ret_EEM','ret_EPU','ret_USD_PEN']
    payload={'fund':'PROFUTURO Fondo 3','method':'OLS rolling 90 + QQQ incremental residualizado. Variante A excluye NEM/FCX. Variante B excluye NEM/FCX/MCHI. Histórico FX BCRP; 20/08 usa PEN=X provisional si BCRP falta.','exclude_nem_fcx_keep_qqq':calc_variant(markets,sbs,qqq,penx,a),'exclude_nem_fcx_mchi_keep_qqq':calc_variant(markets,sbs,qqq,penx,b)}
    OUT.parent.mkdir(parents=True,exist_ok=True); OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8'); print(json.dumps(payload,ensure_ascii=False,indent=2))
if __name__=='__main__': main()
