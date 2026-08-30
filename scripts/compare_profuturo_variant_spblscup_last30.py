from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data' / 'rolling90'
ANALYSIS = ROOT / 'data' / 'analysis'
MONITOR = ROOT / 'public' / 'data' / 'dual_rolling30_monitor.json'
OUT = ROOT / 'analysis' / 'compare_profuturo_variant_spblscup_last30.json'

FEATURE_SETS = {
    'A_ROLLING30_RECALC': (30, ['ret_SPY','ret_EEM','ret_EPU','ret_MCHI','ret_USD_PEN','ret_QQQ']),
    'A_PLUS_SPBLSCUP_R30': (30, ['ret_SPY','ret_EEM','ret_EPU','ret_MCHI','ret_USD_PEN','ret_QQQ','ret_SPBLSCUP']),
    'A_ROLLING15': (15, ['ret_SPY','ret_EEM','ret_EPU','ret_MCHI','ret_USD_PEN','ret_QQQ']),
    'A_PLUS_SPBLSCUP_R15': (15, ['ret_SPY','ret_EEM','ret_EPU','ret_MCHI','ret_USD_PEN','ret_QQQ','ret_SPBLSCUP']),
}


def read_csv(path: Path) -> pd.DataFrame:
    d=pd.read_csv(path)
    d['fecha']=pd.to_datetime(d['fecha'],errors='coerce').dt.normalize()
    return d.dropna(subset=['fecha']).sort_values('fecha').drop_duplicates('fecha',keep='last').reset_index(drop=True)


def load_bcrp() -> pd.DataFrame:
    x=read_csv(DATA/'bcrp_pd04638_cache.csv')
    x['USD_PEN']=pd.to_numeric(x['USD_PEN_BCRP'],errors='coerce')
    x=x.dropna(subset=['USD_PEN']).sort_values('fecha').drop_duplicates('fecha',keep='last')
    x['ret_USD_PEN']=x['USD_PEN'].pct_change(fill_method=None)
    return x[['fecha','USD_PEN','ret_USD_PEN']].reset_index(drop=True)


def close_series(ticker: str, start='2026-03-01', end='2026-08-29') -> pd.DataFrame:
    raw=yf.download(ticker,start=start,end=end,auto_adjust=False,actions=False,progress=False,threads=False)
    if raw.empty: raise RuntimeError(f'Yahoo sin datos {ticker}')
    if isinstance(raw.columns,pd.MultiIndex):
        s=pd.to_numeric(raw[('Close',ticker)] if ('Close',ticker) in raw.columns else raw.xs('Close',axis=1,level=0).iloc[:,0],errors='coerce')
    else:s=pd.to_numeric(raw['Close'],errors='coerce')
    s=s.dropna();idx=pd.to_datetime(s.index)
    if getattr(idx,'tz',None) is not None:idx=idx.tz_localize(None)
    d=pd.DataFrame({'fecha':idx.normalize(),ticker:s.to_numpy(float)}).sort_values('fecha').drop_duplicates('fecha',keep='last')
    d[f'ret_{ticker}']=d[ticker].pct_change(fill_method=None)
    return d.reset_index(drop=True)


def metrics(df: pd.DataFrame) -> dict:
    y=df.actual_vc.to_numpy(float); p=df.vc_estimated.to_numpy(float); e=p-y
    corr=float(np.corrcoef(p,y)[0,1])
    sse=float(np.sum(e**2)); sst=float(np.sum((y-y.mean())**2))
    return {'n':int(len(df)),'start':df.fecha.iloc[0].date().isoformat(),'end':df.fecha.iloc[-1].date().isoformat(),
            'pearson_r':corr,'corr2':corr*corr,'predictive_r2':1-sse/sst,'mae':float(np.mean(np.abs(e))),
            'rmse':float(np.sqrt(np.mean(e**2))),'mape_pct':float(np.mean(np.abs(e/y))*100),'bias':float(np.mean(e))}


def build_variant(frame: pd.DataFrame, sbs: pd.DataFrame, train_n: int, features: list[str]) -> pd.DataFrame:
    rows=[]
    for i in range(train_n,len(frame)):
        train=frame.iloc[i-train_n:i]; cur=frame.iloc[i]
        beta=np.linalg.lstsq(np.c_[np.ones(train_n),train[features].to_numpy(float)],train.ret_target.to_numpy(float),rcond=None)[0]
        pred_ret=float(np.r_[1.0,cur[features].to_numpy(float)]@beta)
        prev=sbs.loc[sbs.fecha.lt(cur.fecha)].tail(1)
        if prev.empty: continue
        base=float(prev.valor_cuota.iloc[-1]); est=base*(1+pred_ret)
        rows.append({'fecha':cur.fecha,'base_vc':base,'vc_estimated':est,'actual_vc':float(cur.valor_cuota),'return_estimated':pred_ret})
    return pd.DataFrame(rows)


def main():
    sbs=read_csv(DATA/'sbs_profuturo_f3.csv');sbs['valor_cuota']=pd.to_numeric(sbs['valor_cuota'],errors='coerce');sbs=sbs.dropna(subset=['valor_cuota']).copy();sbs['ret_target']=sbs.valor_cuota.pct_change(fill_method=None)
    markets=read_csv(DATA/'markets.csv')
    q=close_series('QQQ'); b=load_bcrp()
    hist=read_csv(ANALYSIS/'googlefinance_alt_6030_returns_20260303_20260820.csv')[['fecha','ret_SPBLSCUP']]
    live=read_csv(ANALYSIS/'googlefinance_alt_rolling30_live_returns.csv')[['fecha','ret_SPBLSCUP']]
    sp=pd.concat([hist,live],ignore_index=True).sort_values('fecha').drop_duplicates('fecha',keep='last')
    f=(markets[['fecha','ret_SPY','ret_EEM','ret_EPU','ret_MCHI']]
       .merge(q[['fecha','ret_QQQ']],on='fecha',how='inner')
       .merge(b[['fecha','ret_USD_PEN']],on='fecha',how='inner')
       .merge(sp,on='fecha',how='left'))
    all_features=sorted({x for _,fs in FEATURE_SETS.values() for x in fs})
    frame=sbs[['fecha','valor_cuota','ret_target']].merge(f,on='fecha',how='inner').dropna(subset=['ret_target',*all_features]).sort_values('fecha').reset_index(drop=True)

    variants={name:build_variant(frame,sbs,n,fs) for name,(n,fs) in FEATURE_SETS.items()}
    m=json.loads(MONITOR.read_text(encoding='utf-8'))
    def clean_hist(key):
        h=pd.DataFrame(m['models'][key]['history_one_step'])
        h['fecha']=pd.to_datetime(h['fecha']).dt.normalize()
        h=h.dropna(subset=['vc_estimated','actual_vc']).sort_values('fecha').drop_duplicates('fecha',keep='last')
        return h[['fecha','vc_estimated','actual_vc']]
    a=clean_hist('qqq'); bb=clean_hist('new_tickers')

    common=set(a.fecha)&set(bb.fecha)
    for v in variants.values(): common &= set(v.fecha)
    common=pd.DatetimeIndex(sorted(common)[-30:])

    aligned={'A_QQQ_VISOR_R30':a[a.fecha.isin(common)].sort_values('fecha').reset_index(drop=True),
             'B_NEW_TICKERS_VISOR_R30':bb[bb.fecha.isin(common)].sort_values('fecha').reset_index(drop=True)}
    for name,v in variants.items(): aligned[name]=v[v.fecha.isin(common)].sort_values('fecha').reset_index(drop=True)

    payload={'purpose':'Diagnóstico; no modifica modelos del visor. Compara Rolling 30 y Rolling 15 sobre las mismas 30 fechas recientes con VC SBS real.',
             'dates':[d.date().isoformat() for d in common],
             'feature_sets':{k:{'train_n':n,'features':fs} for k,(n,fs) in FEATURE_SETS.items()},
             'metrics':{k:metrics(v) for k,v in aligned.items()},
             'rows':{k:v.assign(fecha=v.fecha.dt.strftime('%Y-%m-%d')).to_dict('records') for k,v in aligned.items()}}
    OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(payload,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
