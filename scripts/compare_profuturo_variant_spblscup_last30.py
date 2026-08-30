from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data' / 'rolling90'
ANALYSIS = ROOT / 'data' / 'analysis'
MONITOR = ROOT / 'public' / 'data' / 'dual_rolling30_monitor.json'
OUT = ROOT / 'analysis' / 'compare_profuturo_variant_spblscup_last30.json'
TRAIN = 30
FEATURES = ['ret_SPY','ret_EEM','ret_USD_PEN','ret_QQQ','ret_SPBLSCUP']
BCRP_URL='https://estadisticas.bcrp.gob.pe/estadisticas/series/api/PD04638PD/json'
MESES={'ene':1,'feb':2,'mar':3,'abr':4,'may':5,'jun':6,'jul':7,'ago':8,'set':9,'sep':9,'oct':10,'nov':11,'dic':12}


def read_csv(path: Path) -> pd.DataFrame:
    d=pd.read_csv(path)
    d['fecha']=pd.to_datetime(d['fecha'],errors='coerce').dt.normalize()
    return d.dropna(subset=['fecha']).sort_values('fecha').drop_duplicates('fecha',keep='last').reset_index(drop=True)


def parse_bcrp_date(text: str) -> pd.Timestamp:
    s=str(text).lower().strip();m=re.search(r'(\d{1,2})[.\-/ ]+([a-záéíóú]+)[.\-/ ]+(\d{2,4})',s)
    if not m:return pd.NaT
    mon=m.group(2)[:3]
    for a,b in (('á','a'),('é','e'),('í','i'),('ó','o'),('ú','u')):mon=mon.replace(a,b)
    y=int(m.group(3));y=y+2000 if y<100 else y
    return pd.Timestamp(y,MESES[mon],int(m.group(1))) if mon in MESES else pd.NaT


def load_bcrp() -> pd.DataFrame:
    r=requests.get(BCRP_URL,timeout=30,headers={'User-Agent':'Mozilla/5.0'});r.raise_for_status()
    rows=[]
    for p in r.json().get('periods',[]):
        d=parse_bcrp_date(p.get('name')); v=pd.to_numeric(pd.Series([(p.get('values') or [None])[0]]),errors='coerce').iloc[0]
        if pd.notna(d) and pd.notna(v):rows.append({'fecha':d.normalize(),'USD_PEN':float(v)})
    x=pd.DataFrame(rows).sort_values('fecha').drop_duplicates('fecha',keep='last')
    x['ret_USD_PEN']=x['USD_PEN'].pct_change(fill_method=None)
    return x.reset_index(drop=True)


def close_series(ticker: str, start='2026-04-01', end='2026-08-29') -> pd.DataFrame:
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
    return {'n':len(df),'start':df.fecha.iloc[0].date().isoformat(),'end':df.fecha.iloc[-1].date().isoformat(),
            'pearson_r':corr,'corr2':corr*corr,'predictive_r2':1-sse/sst,'mae':float(np.mean(np.abs(e))),
            'rmse':float(np.sqrt(np.mean(e**2))),'mape_pct':float(np.mean(np.abs(e/y))*100),'bias':float(np.mean(e))}


def main():
    sbs=read_csv(DATA/'sbs_profuturo_f3.csv');sbs['valor_cuota']=pd.to_numeric(sbs['valor_cuota'],errors='coerce');sbs=sbs.dropna(subset=['valor_cuota']).copy();sbs['ret_target']=sbs.valor_cuota.pct_change(fill_method=None)
    markets=read_csv(DATA/'markets.csv')
    q=close_series('QQQ'); b=load_bcrp()
    hist=read_csv(ANALYSIS/'googlefinance_alt_6030_returns_20260303_20260820.csv')[['fecha','ret_SPBLSCUP']]
    live=read_csv(ANALYSIS/'googlefinance_alt_rolling30_live_returns.csv')[['fecha','ret_SPBLSCUP']]
    sp=pd.concat([hist,live],ignore_index=True).sort_values('fecha').drop_duplicates('fecha',keep='last')
    f=markets[['fecha','ret_SPY','ret_EEM']].merge(q[['fecha','ret_QQQ']],on='fecha',how='inner').merge(b[['fecha','ret_USD_PEN']],on='fecha',how='inner').merge(sp,on='fecha',how='inner')
    frame=sbs[['fecha','valor_cuota','ret_target']].merge(f,on='fecha',how='inner').dropna(subset=['ret_target',*FEATURES]).sort_values('fecha').reset_index(drop=True)
    rows=[]
    for i in range(TRAIN,len(frame)):
        train=frame.iloc[i-TRAIN:i]; cur=frame.iloc[i]
        beta=np.linalg.lstsq(np.c_[np.ones(TRAIN),train[FEATURES].to_numpy(float)],train.ret_target.to_numpy(float),rcond=None)[0]
        pred_ret=float(np.r_[1.0,cur[FEATURES].to_numpy(float)]@beta)
        prev=sbs.loc[sbs.fecha.lt(cur.fecha)].tail(1)
        if prev.empty: continue
        base=float(prev.valor_cuota.iloc[-1]); est=base*(1+pred_ret)
        rows.append({'fecha':cur.fecha,'base_vc':base,'vc_estimated':est,'actual_vc':float(cur.valor_cuota),'return_estimated':pred_ret})
    v=pd.DataFrame(rows)

    m=json.loads(MONITOR.read_text(encoding='utf-8'))
    def clean_hist(key):
        h=pd.DataFrame(m['models'][key]['history_one_step'])
        h['fecha']=pd.to_datetime(h['fecha']).dt.normalize()
        h=h.dropna(subset=['vc_estimated','actual_vc']).sort_values('fecha').drop_duplicates('fecha',keep='last')
        return h[['fecha','vc_estimated','actual_vc']]
    a=clean_hist('qqq'); bb=clean_hist('new_tickers')
    common=sorted(set(v.fecha)&set(a.fecha)&set(bb.fecha))[-30:]
    common=pd.DatetimeIndex(common)
    vv=v[v.fecha.isin(common)].sort_values('fecha').reset_index(drop=True)
    aa=a[a.fecha.isin(common)].sort_values('fecha').reset_index(drop=True)
    bbb=bb[bb.fecha.isin(common)].sort_values('fecha').reset_index(drop=True)
    payload={'purpose':'Diagnóstico; no modifica modelos del visor. Comparación sobre las mismas 30 fechas más recientes con VC SBS real.',
             'variant_features':FEATURES,'dates':[d.date().isoformat() for d in common],
             'metrics':{'A_QQQ':metrics(aa),'B_NEW_TICKERS':metrics(bbb),'C_SPY_EEM_USDPEN_QQQ_SPBLSCUP':metrics(vv)},
             'variant_rows':vv.assign(fecha=vv.fecha.dt.strftime('%Y-%m-%d')).to_dict('records')}
    OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(payload,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
