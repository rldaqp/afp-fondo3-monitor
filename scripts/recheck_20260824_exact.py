from __future__ import annotations

import ast
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
OUT = ROOT / 'analysis' / 'recheck_20260824_exact.json'

ANCHOR_DATE = pd.Timestamp('2026-08-20')
TARGET_DATES = [pd.Timestamp('2026-08-21'), pd.Timestamp('2026-08-24')]
TRAIN = 30
QQQ_FEATURES = ['ret_SPY','ret_EEM','ret_EPU','ret_MCHI','ret_USD_PEN','ret_QQQ']
NEW_FEATURES = ['ret_.INX','ret_CPER','ret_EEM_alt','ret_NDX','ret_SPBLSCUP','ret_USD_PEN_alt']
BCRP_URL='https://estadisticas.bcrp.gob.pe/estadisticas/series/api/PD04638PD/json'
MESES={'ene':1,'feb':2,'mar':3,'abr':4,'may':5,'jun':6,'jul':7,'ago':8,'set':9,'sep':9,'oct':10,'nov':11,'dic':12}


def read_csv(path: Path) -> pd.DataFrame:
    d=pd.read_csv(path)
    d['fecha']=pd.to_datetime(d['fecha'],errors='coerce').dt.normalize()
    return d.dropna(subset=['fecha']).sort_values('fecha').drop_duplicates('fecha',keep='last').reset_index(drop=True)


def parse_bcrp_date(text: str) -> pd.Timestamp:
    s=str(text).lower().strip()
    m=re.search(r'(\d{1,2})[.\-/ ]+([a-záéíóú]+)[.\-/ ]+(\d{2,4})',s)
    if not m:return pd.NaT
    mon=m.group(2)[:3]
    for a,b in (('á','a'),('é','e'),('í','i'),('ó','o'),('ú','u')):mon=mon.replace(a,b)
    year=int(m.group(3));year=year+2000 if year<100 else year
    return pd.Timestamp(year,MESES[mon],int(m.group(1))) if mon in MESES else pd.NaT


def load_bcrp() -> pd.DataFrame:
    r=requests.get(BCRP_URL,timeout=30,headers={'User-Agent':'Mozilla/5.0'});r.raise_for_status()
    rows=[]
    for p in r.json().get('periods',[]):
        d=parse_bcrp_date(p.get('name'));v=pd.to_numeric(pd.Series([(p.get('values') or [None])[0]]),errors='coerce').iloc[0]
        if pd.notna(d) and pd.notna(v): rows.append({'fecha':d.normalize(),'USD_PEN_BCRP':float(v)})
    x=pd.DataFrame(rows).sort_values('fecha').drop_duplicates('fecha',keep='last')
    x['ret_bcrp']=x['USD_PEN_BCRP'].pct_change(fill_method=None)
    return x.reset_index(drop=True)


def close_series(ticker: str, start: str='2026-05-01', end: str='2026-08-25') -> pd.DataFrame:
    raw=yf.download(ticker,start=start,end=end,auto_adjust=False,actions=False,progress=False,threads=False)
    if raw.empty: raise RuntimeError(f'Yahoo sin datos {ticker}')
    if isinstance(raw.columns,pd.MultiIndex):
        if ('Close',ticker) in raw.columns:s=pd.to_numeric(raw[('Close',ticker)],errors='coerce')
        else:
            b=raw.xs('Close',axis=1,level=0);s=pd.to_numeric(b.iloc[:,0],errors='coerce')
    else:s=pd.to_numeric(raw['Close'],errors='coerce')
    s=s.dropna();idx=pd.to_datetime(s.index)
    if getattr(idx,'tz',None) is not None:idx=idx.tz_localize(None)
    d=pd.DataFrame({'fecha':idx.normalize(),ticker:s.to_numpy(float)}).sort_values('fecha').drop_duplicates('fecha',keep='last')
    d[f'ret_{ticker}']=d[ticker].pct_change(fill_method=None)
    return d.reset_index(drop=True)


def fit(train: pd.DataFrame, features: list[str]) -> np.ndarray:
    X=train[features].to_numpy(float);y=train['ret_target'].to_numpy(float)
    return np.linalg.lstsq(np.c_[np.ones(len(X)),X],y,rcond=None)[0]


def predict(beta: np.ndarray, row: pd.Series|dict, features: list[str]) -> float:
    return float(np.r_[1.0,[float(row[f]) for f in features]]@beta)


def beta_dict(beta,features): return {k:float(v) for k,v in zip(['intercept',*features],beta)}


def main():
    sbs=read_csv(DATA/'sbs_profuturo_f3.csv');sbs['valor_cuota']=pd.to_numeric(sbs['valor_cuota'],errors='coerce');sbs=sbs.dropna(subset=['valor_cuota']).copy();sbs['ret_target']=sbs['valor_cuota'].pct_change(fill_method=None)
    bcrp=load_bcrp()
    bmap=bcrp.set_index('fecha')
    for d in [pd.Timestamp('2026-08-20'),*TARGET_DATES]:
        if d not in bmap.index: raise RuntimeError(f'BCRP falta {d.date()}')

    # QQQ model: use exact daily closes for QQQ and exact BCRP return, not markets.csv FX column.
    markets=read_csv(DATA/'markets.csv')
    q=close_series('QQQ','2026-05-01','2026-08-25').rename(columns={'ret_QQQ':'ret_QQQ'})
    qf=markets[['fecha','ret_SPY','ret_EEM','ret_EPU','ret_MCHI']].merge(q[['fecha','QQQ','ret_QQQ']],on='fecha',how='inner').merge(bcrp[['fecha','USD_PEN_BCRP','ret_bcrp']],on='fecha',how='inner')
    qf['ret_USD_PEN']=qf['ret_bcrp']
    qc=sbs[['fecha','valor_cuota','ret_target']].merge(qf[['fecha',*QQQ_FEATURES]],on='fecha',how='inner').dropna(subset=['ret_target',*QQQ_FEATURES]).sort_values('fecha')
    qt=qc.loc[qc['fecha']<=ANCHOR_DATE].tail(TRAIN).copy()
    if len(qt)!=TRAIN: raise RuntimeError(f'QQQ train {len(qt)}')
    qb=fit(qt,QQQ_FEATURES)
    qvc=float(sbs.loc[sbs['fecha'].eq(ANCHOR_DATE),'valor_cuota'].iloc[-1])
    qrows=[]
    for d in TARGET_DATES:
        row=qf.loc[qf['fecha'].eq(d)]
        if row.empty:raise RuntimeError(f'QQQ factors falta {d.date()}')
        rr=predict(qb,row.iloc[-1],QQQ_FEATURES);base=qvc;qvc=base*(1+rr)
        qrows.append({'fecha':d.date().isoformat(),'base_vc':base,'return_estimated':rr,'vc_estimated':qvc,'factors':{f:float(row.iloc[-1][f]) for f in QQQ_FEATURES},'closes':{'SPY':float(markets.loc[markets.fecha.eq(d),'SPY'].iloc[-1]),'EEM':float(markets.loc[markets.fecha.eq(d),'EEM'].iloc[-1]),'EPU':float(markets.loc[markets.fecha.eq(d),'EPU'].iloc[-1]),'MCHI':float(markets.loc[markets.fecha.eq(d),'MCHI'].iloc[-1]),'QQQ':float(row.iloc[-1]['QQQ']),'USD_PEN_BCRP':float(row.iloc[-1]['USD_PEN_BCRP'])}})

    # New tickers: train on stored exact historical returns, but replace FX with exact BCRP.
    alt=read_csv(ANALYSIS/'googlefinance_alt_6030_returns_20260303_20260820.csv').rename(columns={'ret_EEM':'ret_EEM_alt','ret_USD_PEN':'ret_USD_PEN_alt_old'})
    alt=alt.merge(bcrp[['fecha','ret_bcrp']],on='fecha',how='left');alt['ret_USD_PEN_alt']=alt['ret_bcrp']
    nc=sbs[['fecha','valor_cuota','ret_target']].merge(alt[['fecha',*NEW_FEATURES]],on='fecha',how='inner').dropna(subset=['ret_target',*NEW_FEATURES]).sort_values('fecha')
    nt=nc.loc[nc['fecha']<=ANCHOR_DATE].tail(TRAIN).copy()
    if len(nt)!=TRAIN: raise RuntimeError(f'NEW train {len(nt)}')
    nb=fit(nt,NEW_FEATURES)

    # Exact/equivalent closes for 21 and 24. SPBLSCUP is sourced from the repo's exact Google-derived returns.
    yfmap={'.INX':'^GSPC','CPER':'CPER','EEM':'EEM','NDX':'^NDX'}
    closes={}
    for name,ticker in yfmap.items(): closes[name]=close_series(ticker,'2026-08-19','2026-08-25')
    shadow=pd.read_csv(DATA/'alt_6030_shadow.csv')
    s21=shadow.loc[shadow['fecha'].astype(str).str[:10].eq('2026-08-21')].tail(1)
    if s21.empty: raise RuntimeError('Falta shadow 21 para SPBLSCUP')
    fr21=ast.literal_eval(s21.iloc[-1]['factor_returns'])
    live=read_csv(ANALYSIS/'googlefinance_alt_rolling30_live_returns.csv')
    r24=float(live.loc[live.fecha.eq(pd.Timestamp('2026-08-24')),'ret_SPBLSCUP'].iloc[-1])
    sp20=446.70;sp21=sp20*(1+float(fr21['ret_SPBLSCUP']));sp24=sp21*(1+r24)

    nf_rows=[]
    for d in TARGET_DATES:
        r={'fecha':d}
        for name,ticker in yfmap.items():
            df=closes[name];same=df.loc[df.fecha.eq(d)]
            if same.empty:raise RuntimeError(f'Falta {name} {d.date()}')
            r[{'.INX':'ret_.INX','CPER':'ret_CPER','EEM':'ret_EEM_alt','NDX':'ret_NDX'}[name]]=float(same.iloc[-1][f'ret_{ticker}'])
            r[name]=float(same.iloc[-1][ticker])
        if d==pd.Timestamp('2026-08-21'):
            r['ret_SPBLSCUP']=float(fr21['ret_SPBLSCUP']);r['SPBLSCUP']=sp21
        else:
            r['ret_SPBLSCUP']=r24;r['SPBLSCUP']=sp24
        r['ret_USD_PEN_alt']=float(bmap.loc[d,'ret_bcrp']);r['USD_PEN_BCRP']=float(bmap.loc[d,'USD_PEN_BCRP'])
        nf_rows.append(r)

    nvc=float(sbs.loc[sbs.fecha.eq(ANCHOR_DATE),'valor_cuota'].iloc[-1]);nrows=[]
    for r in nf_rows:
        rr=predict(nb,r,NEW_FEATURES);base=nvc;nvc=base*(1+rr)
        nrows.append({'fecha':r['fecha'].date().isoformat(),'base_vc':base,'return_estimated':rr,'vc_estimated':nvc,'factors':{f:float(r[f]) for f in NEW_FEATURES},'closes':{k:float(r[k]) for k in ['.INX','CPER','EEM','NDX','SPBLSCUP','USD_PEN_BCRP']}})

    actual24=float(sbs.loc[sbs.fecha.eq(pd.Timestamp('2026-08-24')),'valor_cuota'].iloc[-1])
    actual21=float(sbs.loc[sbs.fecha.eq(pd.Timestamp('2026-08-21')),'valor_cuota'].iloc[-1])
    # One-step diagnostic after 21 became known: uses the SAME 24 market return but actual 21 VC as base; not used as blind score.
    q24_one=actual21*(1+qrows[-1]['return_estimated']);n24_one=actual21*(1+nrows[-1]['return_estimated'])
    payload={
      'rule':'Recalculo exacto de 24/08 como se habría hecho al cierre: ancla SBS disponible 20/08; 21 y 24 no se usan para entrenar ni reanclar. Se encadenan 21 y 24 con cierres diarios; USD/PEN es BCRP PD04638PD oficial de cada fecha.',
      'anchor':{'fecha':'2026-08-20','vc':float(sbs.loc[sbs.fecha.eq(ANCHOR_DATE),'valor_cuota'].iloc[-1])},
      'bcrp':{d.date().isoformat():float(bmap.loc[d,'USD_PEN_BCRP']) for d in [ANCHOR_DATE,*TARGET_DATES]},
      'qqq':{'train_start':qt.iloc[0].fecha.date().isoformat(),'train_end':qt.iloc[-1].fecha.date().isoformat(),'train_n':len(qt),'coefficients':beta_dict(qb,QQQ_FEATURES),'chain':qrows,'vc_24_blind':qvc,'error_pct_vs_sbs_24':(qvc/actual24-1)*100,'vc_24_one_step_after_21_known':q24_one},
      'new_tickers':{'train_start':nt.iloc[0].fecha.date().isoformat(),'train_end':nt.iloc[-1].fecha.date().isoformat(),'train_n':len(nt),'coefficients':beta_dict(nb,NEW_FEATURES),'chain':nrows,'vc_24_blind':nvc,'error_pct_vs_sbs_24':(nvc/actual24-1)*100,'vc_24_one_step_after_21_known':n24_one},
      'sbs_actual_21':actual21,
      'sbs_actual_24':actual24,
      'note':'Los valores one-step se muestran solo como diagnóstico posterior. Para medir el pronóstico real del 24 se usan vc_24_blind, que no conocen VC SBS del 21 ni del 24.'
    }
    OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(payload,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
