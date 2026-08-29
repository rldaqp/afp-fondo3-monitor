from __future__ import annotations
import json, sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import build_dual_rolling30_monitor as m

DATA=ROOT/'data'/'rolling90'
AN=ROOT/'data'/'analysis'
OUT=AN/'tmp_compare_a_spbl_cper_result.json'
TRAIN=30
CUR=['ret_SPY','ret_EEM','ret_EPU','ret_MCHI','ret_USD_PEN','ret_QQQ']
VAR=['ret_SPY','ret_EEM','ret_SPBLSCUP','ret_MCHI','ret_USD_PEN','ret_QQQ','ret_CPER']

def normalize_bcrp(markets: pd.DataFrame)->pd.DataFrame:
    cache=DATA/'bcrp_pd04638_cache.csv'
    b=pd.read_csv(cache)
    b['fecha']=pd.to_datetime(b['fecha'],errors='coerce').dt.normalize()
    b['USD_PEN_BCRP']=pd.to_numeric(b['USD_PEN_BCRP'],errors='coerce')
    b=b.dropna().sort_values('fecha').drop_duplicates('fecha',keep='last')
    b['ret_BCRP']=b['USD_PEN_BCRP'].pct_change(fill_method=None)
    x=markets.merge(b[['fecha','USD_PEN_BCRP','ret_BCRP']],on='fecha',how='left')
    mask=x['USD_PEN_BCRP'].notna(); rmask=x['ret_BCRP'].notna()
    x.loc[mask,'USD_PEN']=x.loc[mask,'USD_PEN_BCRP']
    x.loc[rmask,'ret_USD_PEN']=x.loc[rmask,'ret_BCRP']
    return x.drop(columns=['USD_PEN_BCRP','ret_BCRP'])

def alt_factors()->pd.DataFrame:
    a=m.read_csv(AN/'googlefinance_alt_6030_returns_20260303_20260820.csv')
    l=m.read_csv(AN/'googlefinance_alt_rolling30_live_returns.csv')
    cols=['fecha','ret_CPER','ret_SPBLSCUP']
    a=a[cols].copy(); l=l[cols].copy()
    z=pd.concat([a,l],ignore_index=True)
    for c in cols[1:]: z[c]=pd.to_numeric(z[c],errors='coerce')
    return z.dropna(subset=cols[1:]).sort_values('fecha').drop_duplicates('fecha',keep='last').reset_index(drop=True)

def sbs_frame()->pd.DataFrame:
    s=m.read_csv(DATA/'sbs_profuturo_f3.csv')
    s['valor_cuota']=pd.to_numeric(s['valor_cuota'],errors='coerce')
    s=s.dropna(subset=['valor_cuota']).sort_values('fecha').drop_duplicates('fecha',keep='last').reset_index(drop=True)
    s['prev_vc']=s['valor_cuota'].shift(1); s['ret_target']=s['valor_cuota'].pct_change(fill_method=None)
    return s

def predictions(common:pd.DataFrame, features:list[str])->pd.DataFrame:
    rows=[]
    for i in range(TRAIN,len(common)):
        tr=common.iloc[i-TRAIN:i].copy(); r=common.iloc[i]
        beta,_=m.fit(tr,features); rr=m.predict(beta,r,features)
        est=float(r['prev_vc'])*(1+rr)
        rows.append({'fecha':pd.Timestamp(r['fecha']),'est':est,'actual':float(r['valor_cuota'])})
    return pd.DataFrame(rows)

def metrics(p:pd.DataFrame)->dict:
    p=p.tail(30).reset_index(drop=True)
    e=p['est']-p['actual']
    return {'n':len(p),'start':p.iloc[0].fecha.date().isoformat(),'end':p.iloc[-1].fecha.date().isoformat(),
            'corr_vc':float(np.corrcoef(p['est'],p['actual'])[0,1]),
            'r2_corr':float(np.corrcoef(p['est'],p['actual'])[0,1]**2),
            'mae_vc':float(e.abs().mean()),'rmse_vc':float(np.sqrt(np.mean(e.to_numpy()**2)))}

def main():
    markets=normalize_bcrp(m.read_csv(DATA/'markets.csv'))
    sbs=sbs_frame(); latest=sbs['fecha'].max()
    q=m.load_qqq_daily(markets['fecha'].min(),latest)
    mf=markets.merge(q[['fecha','ret_QQQ']],on='fecha',how='left')
    for c in CUR: mf[c]=pd.to_numeric(mf[c],errors='coerce')
    curfac=mf[['fecha',*CUR]].dropna(subset=CUR).sort_values('fecha').drop_duplicates('fecha',keep='last')
    native=sbs[['fecha','valor_cuota','prev_vc','ret_target']].merge(curfac,on='fecha',how='inner').dropna(subset=['prev_vc','ret_target',*CUR]).sort_values('fecha').reset_index(drop=True)
    alt=alt_factors()
    fac=curfac.merge(alt,on='fecha',how='inner').dropna(subset=VAR).sort_values('fecha').reset_index(drop=True)
    common=sbs[['fecha','valor_cuota','prev_vc','ret_target']].merge(fac,on='fecha',how='inner').dropna(subset=['prev_vc','ret_target',*VAR]).sort_values('fecha').reset_index(drop=True)
    pn=predictions(native,CUR); pc=predictions(common,CUR); pv=predictions(common,VAR)
    tailc=pc.tail(30).reset_index(drop=True); tailv=pv.tail(30).reset_index(drop=True)
    assert tailc['fecha'].equals(tailv['fecha'])
    payload={'method':'OLS rolling 30 one-step. Variante reemplaza EPU por SPBLSCUP y agrega CPER. Comparacion justa usa las mismas fechas completas para ambos modelos.',
             'current_features':CUR,'variant_features':VAR,
             'model_a_native_last30':metrics(pn),'model_a_common_last30':metrics(pc),'variant_common_last30':metrics(pv),
             'corr_delta_common':metrics(pv)['corr_vc']-metrics(pc)['corr_vc'],
             'mae_delta_common':metrics(pv)['mae_vc']-metrics(pc)['mae_vc'],
             'common_dates_last30':[d.date().isoformat() for d in tailc['fecha']]}
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(payload,ensure_ascii=False,indent=2))
if __name__=='__main__': main()
