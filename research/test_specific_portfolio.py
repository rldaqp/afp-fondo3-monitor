from __future__ import annotations

import json
import math
import re
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import yfinance as yf
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import HuberRegressor
from sklearn.metrics import r2_score
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data' / 'rolling90'
OUT = ROOT / 'research_outputs' / 'specific_portfolio'
RAW = OUT / 'raw'
OUT.mkdir(parents=True, exist_ok=True)
RAW.mkdir(parents=True, exist_ok=True)

WINDOW = 90
THRESHOLD = 0.001
EPSILON = 1.1
ALPHA = 0.0001
HEADERS = {'User-Agent': 'Mozilla/5.0'}

BASE = ['ret_SPY','ret_NEM','ret_FCX','ret_EPU','ret_MCHI','ret_EEM','ret_USD_PEN']
MONTHS = {
    1: ('Enero','en'), 2: ('Febrero','fe'), 3: ('Marzo','ma'),
    4: ('Abril','ab'), 5: ('Mayo','my'), 6: ('Junio','jn'),
    7: ('Julio','jl'), 8: ('Agosto','ag'), 9: ('Setiembre','se'),
    10: ('Octubre','oc'), 11: ('Noviembre','no'), 12: ('Diciembre','di'),
}

# Mapeos verificables por ISIN. Los instrumentos sin precio público quedan en el residual proxy.
LOCAL_MAP = {
    'PAL1801171A1': ['INRETC1.LM'],
    'PEP116001004': ['BBVAC1.LM'],
    'PEP239501005': ['CPACASC1.LM'],
    'PEP736001004': ['FERREYC1.LM'],
    'PEP736581005': ['AENZAC1.LM','AENZA'],
    'US2044481040': ['BVN'],
    'GB00B1FW5029': ['HOC.L'],
    'PEP622005002': ['MINSURI1.LM'],
    'HK1208013172': ['1208.HK'],
    'BMG2519Y1084': ['BAP'],
    'PEP702101002': ['ENGIEC1.LM'],
    'PEP701011004': ['ENDISPC1.LM'],
}
FOREIGN_MAP = {
    'US4227041062': ['HL'],
    'US4642875235': ['SOXX'],
    'US4642873909': ['ILF'],
    'US4642864007': ['EWZ'],
    'US46435G1022': ['ICVT'],
    'US4642867729': ['EWY'],
    'US92189F1066': ['GDX'],
    'US92189H6071': ['OIH'],
    'US92189H8051': ['REMX'],
    'US9220427424': ['VT'],
    'US5007673065': ['KWEB'],
    'US78464A7550': ['XME'],
    'US00214Q8078': ['ARKX'],
}
FX_TICKERS = {
    'EUR': ('EURUSD=X', 1.0), 'GBP': ('GBPUSD=X', 1.0),
    'AUD': ('AUDUSD=X', 1.0), 'JPY': ('JPY=X', -1.0),
    'BRL': ('BRL=X', -1.0), 'CLP': ('CLP=X', -1.0),
    'COP': ('COP=X', -1.0), 'KRW': ('KRW=X', -1.0),
    'HKD': ('HKD=X', -1.0), 'MXN': ('MXN=X', -1.0),
    'CAD': ('CAD=X', -1.0), 'CHF': ('CHF=X', -1.0),
}


def classify(x: float) -> str:
    if x > THRESHOLD: return 'SUBE'
    if x < -THRESHOLD: return 'BAJA'
    return 'NEUTRO'


def month_iter(start: str, end: str):
    p = pd.Timestamp(start).to_period('M')
    q = pd.Timestamp(end).to_period('M')
    while p <= q:
        yield p.to_timestamp('M')
        p += 1


def download(url: str, path: Path, minimum: int = 5000) -> Path:
    if path.exists() and path.stat().st_size >= minimum:
        return path
    r = requests.get(url, timeout=90, headers=HEADERS)
    r.raise_for_status()
    if len(r.content) < minimum:
        raise RuntimeError(f'Archivo pequeño {url}: {len(r.content)}')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(r.content)
    return path


def ca_path(month_end: pd.Timestamp) -> Path:
    folder, code = MONTHS[int(month_end.month)]
    name = f'CA-0001-{code}{month_end.year}.XLS'
    url = f'https://intranet2.sbs.gob.pe/estadistica/spp/{month_end.year}/{folder}/{name}'
    return download(url, RAW / 'ca0001' / name, 20000)


def download_complementary_sources() -> list[dict[str, object]]:
    inventory = []
    for month_end in month_iter('2025-01-31','2026-06-30'):
        folder, code = MONTHS[int(month_end.month)]
        year = month_end.year
        for report in ['FP-1357','FP-1358']:
            name = f'{report}-{code}{year}.XLS'
            url = f'https://intranet2.sbs.gob.pe/estadistica/financiera/{year}/{folder}/{name}'
            try:
                p = download(url, RAW / report.lower() / name, 10000)
                inventory.append({'name':name,'url':url,'size':p.stat().st_size,'status':'ok'})
            except Exception as exc:
                inventory.append({'name':name,'url':url,'status':'error','error':repr(exc)})
    for report in ['FP-1306']:
        name = f'{report}-jn2026.XLS'
        url = f'https://intranet2.sbs.gob.pe/estadistica/financiera/2026/Junio/{name}'
        try:
            p = download(url, RAW / report.lower() / name, 10000)
            inventory.append({'name':name,'url':url,'size':p.stat().st_size,'status':'ok'})
        except Exception as exc:
            inventory.append({'name':name,'url':url,'status':'error','error':repr(exc)})
    for number in ['4','5','6','7','8','10','11','12','13']:
        name = f'profuturo-2026-02-{number}.pdf'
        url = ('https://cdn.aglty.io/scotiabank-peru/Profuturo/PDF/personas/'
               f'reporte-cartera-inversiones/2026/febrero/{number}.pdf')
        try:
            p = download(url, RAW / 'profuturo' / name, 10000)
            inventory.append({'name':name,'url':url,'size':p.stat().st_size,'status':'ok'})
        except Exception as exc:
            inventory.append({'name':name,'url':url,'status':'error','error':repr(exc)})
    return inventory


def norm(x: object) -> str:
    if pd.isna(x): return ''
    return re.sub(r'\s+',' ',str(x)).strip().upper()


def find_pr03(frame: pd.DataFrame) -> tuple[int,int,int]:
    for row in range(min(12,len(frame))):
        for col in range(frame.shape[1]):
            if norm(frame.iloc[row,col]) == 'PR03':
                return row, col, col + 1
    raise RuntimeError('No se encontró PR03')


def leaf_positions(frame: pd.DataFrame, amount_col: int, pct_col: int) -> list[dict[str,object]]:
    rows=[]
    for i in range(len(frame)):
        key=norm(frame.iloc[i,0])
        if re.fullmatch(r'[A-Z]{2}[A-Z0-9]{10}',key):
            amount=pd.to_numeric(pd.Series([frame.iloc[i,amount_col]]),errors='coerce').iloc[0]
            pct=pd.to_numeric(pd.Series([frame.iloc[i,pct_col]]),errors='coerce').iloc[0]
            if pd.notna(amount) and abs(float(amount))>1e-8:
                rows.append({'isin':key,'currency':norm(frame.iloc[i,1]),
                             'coupon':pd.to_numeric(pd.Series([frame.iloc[i,2]]),errors='coerce').iloc[0],
                             'duration':pd.to_numeric(pd.Series([frame.iloc[i,3]]),errors='coerce').iloc[0],
                             'amount':float(amount),'weight':float(pct) if pd.notna(pct) else np.nan})
    return rows


def row_pct(frame: pd.DataFrame, label: str, pct_col: int, optional: bool=True) -> float:
    target=label.upper()
    for i in range(len(frame)):
        if target in norm(frame.iloc[i,0]):
            v=pd.to_numeric(pd.Series([frame.iloc[i,pct_col]]),errors='coerce').iloc[0]
            if pd.notna(v): return float(v)
    if optional: return 0.0
    raise RuntimeError(f'No se encontró {label}')


def parse_forwards(frame: pd.DataFrame, amount_col: int, pct_col: int) -> dict[str,float]:
    exposures: dict[str,float] = {}
    i=0
    codes=set(FX_TICKERS)|{'USD','PEN'}
    while i < len(frame)-3:
        base=norm(frame.iloc[i,0])
        quote=norm(frame.iloc[i+1,0])
        action1=norm(frame.iloc[i+2,0])
        action2=norm(frame.iloc[i+3,0])
        if base in codes and quote in codes and action1=='COMPRA' and action2=='VENTA':
            buy=pd.to_numeric(pd.Series([frame.iloc[i+2,pct_col]]),errors='coerce').iloc[0]
            sell=pd.to_numeric(pd.Series([frame.iloc[i+3,pct_col]]),errors='coerce').iloc[0]
            net=(0.0 if pd.isna(buy) else float(buy))-(0.0 if pd.isna(sell) else float(sell))
            exposures[base]=exposures.get(base,0.0)+net
            exposures[quote]=exposures.get(quote,0.0)-net
            i += 4
        else:
            i += 1
    return exposures


def parse_month(month_end: pd.Timestamp) -> tuple[dict[str,object],list[dict],list[dict],list[dict]]:
    path=ca_path(month_end)
    local=pd.read_excel(path,sheet_name='4',header=None,engine='openpyxl')
    bonds=pd.read_excel(path,sheet_name='6',header=None,engine='openpyxl')
    foreign=pd.read_excel(path,sheet_name='10',header=None,engine='openpyxl')
    forwards=pd.read_excel(path,sheet_name='12',header=None,engine='openpyxl')
    _,la,lp=find_pr03(local); _,ba,bp=find_pr03(bonds); _,fa,fp=find_pr03(foreign); _,xa,xp=find_pr03(forwards)
    local_pos=leaf_positions(local,la,lp)
    bond_pos=leaf_positions(bonds,ba,bp)
    foreign_pos=leaf_positions(foreign,fa,fp)
    fx=parse_forwards(forwards,xa,xp)
    row={
        'report_month':month_end.date().isoformat(),
        # Profuturo informa que el detalle público tiene aproximadamente cuatro meses de antigüedad.
        'available_date':(month_end+pd.offsets.MonthEnd(4)+pd.Timedelta(days=15)).date().isoformat(),
        'local_total':sum(x['weight'] for x in local_pos if not math.isnan(x['weight'])),
        'foreign_isin_total':sum(x['weight'] for x in foreign_pos if not math.isnan(x['weight'])),
        'foreign_liquid_total':row_pct(foreign,'FONDOS MUTUOS DEL EXTRANJERO',fp),
        'foreign_equity_total':row_pct(foreign,'ACCIONES EN EL EXTRANJERO',fp),
        'foreign_alt_total':row_pct(foreign,'FONDO MUTUO ALTERNATIVO EXTRANJERO',fp),
        'foreign_total':row_pct(foreign,'TOTAL GENERAL',fp),
        'bond_total':sum(x['weight'] for x in bond_pos if not math.isnan(x['weight'])),
        'forward_gross':row_pct(forwards,'TOTAL',xp),
    }
    for c in sorted(set(FX_TICKERS)|{'USD','PEN'}): row[f'fwd_net_{c}']=fx.get(c,0.0)
    return row,local_pos,bond_pos,foreign_pos


def download_close(ticker: str,start: str,end: str) -> pd.Series | None:
    try:
        raw=yf.download(ticker,start=start,end=end,auto_adjust=False,progress=False,threads=False)
        if raw.empty: return None
        close=raw['Close']
        if isinstance(close,pd.DataFrame): close=close.iloc[:,0]
        close=pd.to_numeric(close,errors='coerce').dropna()
        close.index=pd.to_datetime(close.index,errors='coerce').tz_localize(None)
        close.name=ticker
        return close
    except Exception:
        return None


def resolve_tickers(start: str,end: str) -> tuple[pd.DataFrame,dict[str,str],list[str]]:
    candidates={**LOCAL_MAP,**FOREIGN_MAP}
    chosen: dict[str,str]={}
    series=[]; failed=[]
    cache: dict[str,pd.Series|None]={}
    for isin,options in candidates.items():
        selected=None
        for ticker in options:
            if ticker not in cache: cache[ticker]=download_close(ticker,start,end)
            s=cache[ticker]
            if s is not None and s.notna().sum()>=100:
                selected=ticker; break
        if selected:
            chosen[isin]=selected
            if selected not in [x.name for x in series]: series.append(cache[selected])
        else: failed.append(isin)
    extra=['SHY','IEF','TLT','EMLC']+[v[0] for v in FX_TICKERS.values()]
    for ticker in extra:
        if ticker not in cache: cache[ticker]=download_close(ticker,start,end)
        if cache[ticker] is not None and ticker not in [x.name for x in series]: series.append(cache[ticker])
    closes=pd.concat(series,axis=1).sort_index() if series else pd.DataFrame()
    return closes,chosen,failed


def build_monthly() -> tuple[pd.DataFrame,pd.DataFrame,pd.DataFrame,pd.DataFrame]:
    summaries=[]; local_rows=[]; bond_rows=[]; foreign_rows=[]
    for month_end in month_iter('2025-01-31','2026-02-28'):
        row,local,bonds,foreign=parse_month(month_end)
        summaries.append(row)
        for x in local: local_rows.append({'report_month':row['report_month'],**x})
        for x in bonds: bond_rows.append({'report_month':row['report_month'],**x})
        for x in foreign: foreign_rows.append({'report_month':row['report_month'],**x})
    return pd.DataFrame(summaries),pd.DataFrame(local_rows),pd.DataFrame(bond_rows),pd.DataFrame(foreign_rows)


def prepare_daily(monthly: pd.DataFrame,local: pd.DataFrame,bonds: pd.DataFrame,foreign: pd.DataFrame):
    sbs=pd.read_csv(DATA/'sbs_profuturo_f3.csv')
    markets=pd.read_csv(DATA/'markets.csv')
    sbs['fecha']=pd.to_datetime(sbs['fecha']); sbs['valor_cuota']=pd.to_numeric(sbs['valor_cuota'],errors='coerce')
    sbs=sbs.dropna(subset=['fecha','valor_cuota']).sort_values('fecha').drop_duplicates('fecha',keep='last')
    sbs['ret_profuturo']=sbs['valor_cuota'].pct_change(fill_method=None)
    markets['fecha']=pd.to_datetime(markets['fecha'])
    for c in BASE: markets[c]=pd.to_numeric(markets[c],errors='coerce')
    start=(markets['fecha'].min()-pd.Timedelta(days=15)).date().isoformat()
    end=(markets['fecha'].max()+pd.Timedelta(days=4)).date().isoformat()
    closes,chosen,failed=resolve_tickers(start,end)
    extras=closes.pct_change(fill_method=None).add_prefix('ret_').reset_index().rename(columns={'index':'fecha','Date':'fecha'})
    extras['fecha']=pd.to_datetime(extras['fecha'])
    data=sbs[['fecha','valor_cuota','ret_profuturo']].merge(markets,on='fecha',how='inner').merge(extras,on='fecha',how='left')
    monthly['report_month']=pd.to_datetime(monthly['report_month']); monthly['available_date']=pd.to_datetime(monthly['available_date'])
    data=pd.merge_asof(data.sort_values('fecha'),monthly.sort_values('available_date'),left_on='fecha',right_on='available_date',direction='backward')

    local_by={k:g for k,g in local.groupby(pd.to_datetime(local['report_month']))}
    bond_by={k:g for k,g in bonds.groupby(pd.to_datetime(bonds['report_month']))}
    foreign_by={k:g for k,g in foreign.groupby(pd.to_datetime(foreign['report_month']))}
    local_contrib=[]; foreign_contrib=[]; bond_contrib=[]; forward_contrib=[]; coverage=[]
    global_eq=data[['ret_SPY','ret_EEM','ret_MCHI']].mean(axis=1,skipna=False)
    for idx,row in data.iterrows():
        month=row.get('report_month')
        if pd.isna(month):
            local_contrib.append(np.nan); foreign_contrib.append(np.nan); bond_contrib.append(np.nan); forward_contrib.append(np.nan); coverage.append(np.nan); continue
        month=pd.Timestamp(month)
        lg=local_by.get(month,pd.DataFrame()); fg=foreign_by.get(month,pd.DataFrame()); bg=bond_by.get(month,pd.DataFrame())
        lc=0.0; direct_local=0.0
        for _,p in lg.iterrows():
            ticker=chosen.get(p['isin']); ret=row.get(f'ret_{ticker}') if ticker else np.nan
            if ticker and pd.notna(ret): lc += float(p['weight'])*float(ret); direct_local += float(p['weight'])
        local_total=float(row['local_total'])
        lc += max(local_total-direct_local,0.0)*float(row['ret_EPU'])
        fc=0.0; direct_foreign=0.0
        for _,p in fg.iterrows():
            ticker=chosen.get(p['isin']); ret=row.get(f'ret_{ticker}') if ticker else np.nan
            if ticker and pd.notna(ret): fc += float(p['weight'])*float(ret); direct_foreign += float(p['weight'])
        liquid=max(float(row['foreign_liquid_total'])+float(row['foreign_equity_total']),0.0)
        fc += max(liquid-direct_foreign,0.0)*float(global_eq.iloc[idx])
        bc=0.0
        for _,p in bg.iterrows():
            w=float(p['weight']); dur=p['duration']; cur=p['currency']
            if pd.isna(dur): ticker='EMLC' if cur=='PEN' else 'IEF'
            elif float(dur)<=1: ticker='SHY'
            elif float(dur)<=5: ticker='EMLC' if cur=='PEN' else 'IEF'
            else: ticker='EMLC' if cur=='PEN' else 'TLT'
            ret=row.get(f'ret_{ticker}')
            if pd.notna(ret): bc += w*float(ret)
        fwc=float(row.get('fwd_net_USD',0.0))*float(row['ret_USD_PEN'])
        for currency,(ticker,sign) in FX_TICKERS.items():
            ret=row.get(f'ret_{ticker}')
            if pd.notna(ret): fwc += float(row.get(f'fwd_net_{currency}',0.0))*sign*float(ret)
        local_contrib.append(lc); foreign_contrib.append(fc); bond_contrib.append(bc); forward_contrib.append(fwc)
        denom=max(local_total+liquid,1e-12); coverage.append((direct_local+direct_foreign)/denom)
    data['x_local_specific']=local_contrib
    data['x_foreign_specific']=foreign_contrib
    data['x_bond_specific']=bond_contrib
    data['x_forward_specific']=forward_contrib
    data['x_net_fx']=data['foreign_total']*data['ret_USD_PEN']+data['x_forward_specific']
    data['x_specific_proxy']=data[['x_local_specific','x_foreign_specific','x_bond_specific','x_forward_specific']].sum(axis=1,min_count=4)
    data['mapped_coverage']=coverage
    return data,chosen,failed


def fit_predict(train: pd.DataFrame,test: pd.DataFrame,features: list[str]) -> float:
    sx=StandardScaler().fit(train[features])
    sy=StandardScaler().fit(train[['ret_profuturo']]*1)
    model=HuberRegressor(epsilon=EPSILON,alpha=ALPHA,max_iter=2000)
    with warnings.catch_warnings():
        warnings.simplefilter('ignore',ConvergenceWarning)
        model.fit(sx.transform(train[features]),sy.transform(train[['ret_profuturo']]).ravel())
    return float(sy.inverse_transform(model.predict(sx.transform(test[features])).reshape(-1,1))[0,0])


def walk(data: pd.DataFrame,features: list[str]) -> pd.DataFrame:
    clean=data[['fecha','ret_profuturo',*features]].replace([np.inf,-np.inf],np.nan).dropna().sort_values('fecha').reset_index(drop=True)
    rows=[]
    for i in range(WINDOW,len(clean)):
        train=clean.iloc[i-WINDOW:i]; test=clean.iloc[[i]]
        pred=fit_predict(train,test,features); actual=float(test['ret_profuturo'].iloc[0])
        rows.append({'fecha':test['fecha'].iloc[0],'actual':actual,'pred':pred,'actual_signal':classify(actual),'pred_signal':classify(pred)})
    return pd.DataFrame(rows)


def metrics(df: pd.DataFrame) -> dict[str,object]:
    if df.empty: return {'n':0}
    err=df['pred']-df['actual']; hit=df['pred_signal']==df['actual_signal']
    hard=((df['pred_signal']=='SUBE')&(df['actual_signal']=='BAJA'))|((df['pred_signal']=='BAJA')&(df['actual_signal']=='SUBE'))
    out={'n':len(df),'hits':int(hit.sum()),'accuracy':float(hit.mean()),'mae_pp':float(err.abs().mean()*100),'rmse_pp':float(np.sqrt(np.mean(err**2))*100),'hard_reversals':int(hard.sum())}
    out['r2']=float(r2_score(df['actual'],df['pred'])) if len(df)>1 else None
    for signal in ['SUBE','BAJA','NEUTRO']:
        part=df[df['actual_signal']==signal]; out[signal.lower()]={'n':len(part),'hits':int((part['pred_signal']==signal).sum()),'accuracy':float((part['pred_signal']==signal).mean()) if len(part) else None}
    return out


def slices(df: pd.DataFrame) -> dict[str,dict]:
    n=len(df); a=int(n*.6); b=int(n*.8)
    return {'all':metrics(df),'validation':metrics(df.iloc[a:b]),'test':metrics(df.iloc[b:]),'last90':metrics(df.tail(90))}


def compare(base: pd.DataFrame,cand: pd.DataFrame) -> dict[str,object]:
    m=base.merge(cand,on='fecha',suffixes=('_base','_cand'))
    base_ok=m['pred_signal_base']==m['actual_signal_base']; cand_ok=m['pred_signal_cand']==m['actual_signal_cand']
    return {'common_n':len(m),'corrected':m.loc[~base_ok&cand_ok,'fecha'].dt.strftime('%Y-%m-%d').tolist(),'created':m.loc[base_ok&~cand_ok,'fecha'].dt.strftime('%Y-%m-%d').tolist()}


def main():
    inventory=download_complementary_sources()
    monthly,local,bonds,foreign=build_monthly()
    data,chosen,failed=prepare_daily(monthly,local,bonds,foreign)
    variants={
        'base7':BASE,
        'plus_local':BASE+['x_local_specific'],
        'plus_foreign':BASE+['x_foreign_specific'],
        'plus_bonds':BASE+['x_bond_specific'],
        'plus_forward':BASE+['x_forward_specific'],
        'plus_proxy':BASE+['x_specific_proxy'],
        'plus_specific_all':BASE+['x_local_specific','x_foreign_specific','x_bond_specific','x_forward_specific'],
        'replace_usd_netfx':[x for x in BASE if x!='ret_USD_PEN']+['x_net_fx'],
    }
    predictions={name:walk(data,features) for name,features in variants.items()}
    scores={name:slices(df) for name,df in predictions.items()}
    # Selección estrictamente en validación: aciertos, MAE, reversiones.
    def key(name: str):
        m=scores[name]['validation']; return (m.get('hits',-1),-m.get('mae_pp',999),-m.get('hard_reversals',999))
    selected=max(variants,key=key)
    comparisons={name:compare(predictions['base7'],df) for name,df in predictions.items() if name!='base7'}
    paired=None
    for name,df in predictions.items():
        z=df[['fecha','actual','actual_signal','pred','pred_signal']].rename(columns={'pred':f'pred_{name}','pred_signal':f'signal_{name}'})
        if paired is None: paired=z
        else: paired=paired.merge(z[['fecha',f'pred_{name}',f'signal_{name}']],on='fecha',how='outer')
    target_dates=['2026-03-24','2026-03-27','2026-04-09','2026-06-01','2026-06-16','2026-06-18','2026-06-26','2026-07-02','2026-07-20']
    targets=paired[paired['fecha'].dt.strftime('%Y-%m-%d').isin(target_dates)].copy() if paired is not None else pd.DataFrame()
    coverage={'mapped_isins':chosen,'failed_isins':failed,'mean_daily_mapped_coverage':float(data['mapped_coverage'].mean()),'latest_mapped_coverage':float(data['mapped_coverage'].dropna().iloc[-1])}
    result={'method':{'window':WINDOW,'threshold':THRESHOLD,'epsilon':EPSILON,'alpha':ALPHA,'operational_lag':'month end + 4 months + 15 days','selection':'validation only'},'selected':selected,'scores':scores,'comparisons':comparisons,'coverage':coverage,'source_inventory':inventory}
    (OUT/'results.json').write_text(json.dumps(result,indent=2,ensure_ascii=False,default=str),encoding='utf-8')
    monthly.to_csv(OUT/'monthly_specific_exposures.csv',index=False)
    local.to_csv(OUT/'local_holdings.csv',index=False); bonds.to_csv(OUT/'bond_holdings.csv',index=False); foreign.to_csv(OUT/'foreign_holdings.csv',index=False)
    data.to_csv(OUT/'daily_specific_features.csv',index=False)
    paired.to_csv(OUT/'paired_predictions.csv',index=False); targets.to_csv(OUT/'target_dates.csv',index=False)
    (OUT/'source_inventory.json').write_text(json.dumps(inventory,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps(result,indent=2,ensure_ascii=False,default=str))
    print('\nTARGET DATES\n',targets.to_string(index=False))

if __name__=='__main__': main()
