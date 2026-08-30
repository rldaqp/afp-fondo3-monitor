from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data' / 'rolling90'
ANALYSIS = ROOT / 'data' / 'analysis'
OUT = ROOT / 'analysis' / 'compare_profuturo_rolling_windows_horizons.json'

BASE_FEATURES = ['ret_SPY','ret_EEM','ret_EPU','ret_MCHI','ret_USD_PEN','ret_QQQ']
WINDOWS = [20,25,30]
HORIZONS = [30,60,90]


def read_csv(path: Path) -> pd.DataFrame:
    d=pd.read_csv(path)
    d['fecha']=pd.to_datetime(d['fecha'],errors='coerce').dt.normalize()
    return d.dropna(subset=['fecha']).sort_values('fecha').drop_duplicates('fecha',keep='last').reset_index(drop=True)


def close_series(ticker: str, start='2025-10-01', end='2026-08-29') -> pd.DataFrame:
    raw=yf.download(ticker,start=start,end=end,auto_adjust=False,actions=False,progress=False,threads=False)
    if raw.empty: raise RuntimeError(f'Yahoo sin datos {ticker}')
    if isinstance(raw.columns,pd.MultiIndex):
        s=pd.to_numeric(raw[('Close',ticker)] if ('Close',ticker) in raw.columns else raw.xs('Close',axis=1,level=0).iloc[:,0],errors='coerce')
    else:
        s=pd.to_numeric(raw['Close'],errors='coerce')
    s=s.dropna(); idx=pd.to_datetime(s.index)
    if getattr(idx,'tz',None) is not None: idx=idx.tz_localize(None)
    d=pd.DataFrame({'fecha':idx.normalize(),ticker:s.to_numpy(float)}).sort_values('fecha').drop_duplicates('fecha',keep='last')
    d[f'ret_{ticker}']=d[ticker].pct_change(fill_method=None)
    return d.reset_index(drop=True)


def metrics(df: pd.DataFrame) -> dict:
    y=df.actual_vc.to_numpy(float); p=df.vc_estimated.to_numpy(float); e=p-y
    corr=float(np.corrcoef(p,y)[0,1])
    sse=float(np.sum(e**2)); sst=float(np.sum((y-y.mean())**2))
    return {
        'n':int(len(df)), 'start':df.fecha.iloc[0].date().isoformat(), 'end':df.fecha.iloc[-1].date().isoformat(),
        'pearson_r':corr, 'corr2':corr*corr, 'predictive_r2':float(1-sse/sst),
        'mae':float(np.mean(np.abs(e))), 'rmse':float(np.sqrt(np.mean(e**2))),
        'mape_pct':float(np.mean(np.abs(e/y))*100), 'bias':float(np.mean(e))
    }


def build_variant(frame: pd.DataFrame, sbs: pd.DataFrame, train_n: int) -> pd.DataFrame:
    rows=[]
    for i in range(train_n,len(frame)):
        train=frame.iloc[i-train_n:i]; cur=frame.iloc[i]
        beta=np.linalg.lstsq(np.c_[np.ones(train_n),train[BASE_FEATURES].to_numpy(float)],train.ret_target.to_numpy(float),rcond=None)[0]
        pred_ret=float(np.r_[1.0,cur[BASE_FEATURES].to_numpy(float)]@beta)
        prev=sbs.loc[sbs.fecha.lt(cur.fecha)].tail(1)
        if prev.empty: continue
        base=float(prev.valor_cuota.iloc[-1]); est=base*(1+pred_ret)
        rows.append({'fecha':cur.fecha,'base_vc':base,'vc_estimated':est,'actual_vc':float(cur.valor_cuota),'return_estimated':pred_ret})
    return pd.DataFrame(rows)


def evaluate_source(frame: pd.DataFrame, sbs: pd.DataFrame) -> dict:
    variants={w:build_variant(frame,sbs,w) for w in WINDOWS}
    common=set.intersection(*(set(v.fecha) for v in variants.values()))
    common_sorted=pd.DatetimeIndex(sorted(common))
    out={'available_common_predictions':int(len(common_sorted)),'windows':{}}
    for h in HORIZONS:
        if len(common_sorted)<h:
            out['windows'][str(h)]={'available':False,'n_available':int(len(common_sorted))}
            continue
        dates=common_sorted[-h:]
        block={}
        for w,v in variants.items():
            x=v[v.fecha.isin(dates)].sort_values('fecha').reset_index(drop=True)
            block[f'R{w}']=metrics(x)
        out['windows'][str(h)]={'available':True,'dates':[d.date().isoformat() for d in dates],'metrics':block}
    return out


def main():
    sbs=read_csv(DATA/'sbs_profuturo_f3.csv')
    sbs['valor_cuota']=pd.to_numeric(sbs['valor_cuota'],errors='coerce')
    sbs=sbs.dropna(subset=['valor_cuota']).copy()
    sbs['ret_target']=sbs.valor_cuota.pct_change(fill_method=None)

    markets=read_csv(DATA/'markets.csv')
    q=close_series('QQQ')

    # Panel largo: usa la serie histórica USD/PEN ya almacenada en markets.csv.
    longf=(markets[['fecha','ret_SPY','ret_EEM','ret_EPU','ret_MCHI','ret_USD_PEN']]
           .merge(q[['fecha','ret_QQQ']],on='fecha',how='inner'))
    long_frame=(sbs[['fecha','valor_cuota','ret_target']].merge(longf,on='fecha',how='inner')
                .dropna(subset=['ret_target',*BASE_FEATURES]).sort_values('fecha').reset_index(drop=True))

    # Panel oficial reciente: sustituye USD/PEN por cache BCRP PD04638PD del repo.
    b=read_csv(DATA/'bcrp_pd04638_cache.csv')
    b['USD_PEN']=pd.to_numeric(b['USD_PEN_BCRP'],errors='coerce')
    b=b.dropna(subset=['USD_PEN']).sort_values('fecha').drop_duplicates('fecha',keep='last')
    b['ret_USD_PEN']=b['USD_PEN'].pct_change(fill_method=None)
    officialf=(markets[['fecha','ret_SPY','ret_EEM','ret_EPU','ret_MCHI']]
               .merge(q[['fecha','ret_QQQ']],on='fecha',how='inner')
               .merge(b[['fecha','ret_USD_PEN']],on='fecha',how='inner'))
    official_frame=(sbs[['fecha','valor_cuota','ret_target']].merge(officialf,on='fecha',how='inner')
                    .dropna(subset=['ret_target',*BASE_FEATURES]).sort_values('fecha').reset_index(drop=True))

    payload={
      'purpose':'Diagnóstico; no modifica el visor. Valida Rolling 20, 25 y 30 en 30, 60 y 90 pronósticos one-step.',
      'features':BASE_FEATURES,
      'method':'OLS con intercepto; entrenamiento móvil estrictamente anterior a cada fecha; base VC = último SBS conocido anterior; evaluación one-step.',
      'panels':{
        'LONG_HISTORY_MARKETS_FX':{
          'note':'Panel 30/60/90 usando ret_USD_PEN histórico almacenado en markets.csv para disponer de profundidad suficiente.',
          **evaluate_source(long_frame,sbs)
        },
        'OFFICIAL_BCRP_PD04638_CACHE':{
          'note':'Control reciente usando exclusivamente cache oficial BCRP PD04638PD disponible en el repositorio; puede no alcanzar 90 pronósticos.',
          **evaluate_source(official_frame,sbs)
        }
      }
    }
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(payload,ensure_ascii=False,indent=2))

if __name__=='__main__': main()
