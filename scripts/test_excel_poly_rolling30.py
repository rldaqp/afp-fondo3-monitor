import json
from pathlib import Path
import numpy as np
import pandas as pd
import requests

OUT=Path('analysis/test_excel_poly_rolling30.json')

def metrics(y,p):
    y=np.asarray(y,float); p=np.asarray(p,float); e=p-y
    sse=float(np.sum(e*e)); sst=float(np.sum((y-y.mean())**2))
    r=float(np.corrcoef(y,p)[0,1]) if len(y)>1 else None
    return {'n':int(len(y)),'pearson_r':r,'corr2':None if r is None else r*r,
            'predictive_r2':float(1-sse/sst) if sst>0 else None,
            'mae':float(np.mean(np.abs(e))),'rmse':float(np.sqrt(np.mean(e*e))),
            'mape_pct':float(np.mean(np.abs(e/y))*100),'bias':float(np.mean(e))}

def design_fit_predict(train, target, cols):
    mats=[np.ones(len(train))]; rv=[1.0]
    for c in cols:
        x=train[c].astype(float).to_numpy(); mu=float(x.mean()); sd=float(x.std(ddof=0)) or 1.0
        u=(x-mu)/sd; t=(float(target[c])-mu)/sd
        mats += [u,u*u]; rv += [t,t*t]
    X=np.column_stack(mats); y=train['VC'].astype(float).to_numpy()
    b=np.linalg.lstsq(X,y,rcond=None)[0]
    return float(np.asarray(rv)@b)

def fit_in_sample(df,cols):
    mats=[np.ones(len(df))]
    for c in cols:
        x=df[c].astype(float).to_numpy(); mu=float(x.mean()); sd=float(x.std(ddof=0)) or 1.0
        u=(x-mu)/sd; mats += [u,u*u]
    X=np.column_stack(mats); y=df.VC.astype(float).to_numpy(); b=np.linalg.lstsq(X,y,rcond=None)[0]
    return X@b

def fetch_bcrp_4060():
    # Endpoint público que sí responde en 2026; segunda serie = venta PD04640PD.
    url='https://estadisticas.bcrp.gob.pe/estadisticas/series/api/PD04639PD-PD04640PD/json/'
    r=requests.get(url,timeout=30,headers={'User-Agent':'Mozilla/5.0'}); j=r.json()
    out=[]
    for p in j.get('periods',[]):
        vals=p.get('values') or []
        if len(vals)<2 or vals[1] in ('n.d.',None,''): continue
        d=pd.to_datetime(p.get('name',''),dayfirst=True,errors='coerce')
        if pd.notna(d): out.append((d.normalize(),float(vals[1])))
    if len(out)<30: raise RuntimeError(f'PD04640PD insuficiente: {len(out)}')
    return pd.DataFrame(out,columns=['fecha','USD_PEN_4060']).drop_duplicates('fecha').sort_values('fecha')

# VC SBS
s=json.loads(Path('public/data/series.json').read_text(encoding='utf-8'))
rows=s if isinstance(s,list) else (s.get('series') or s.get('data') or s.get('rows') or [])
ss=[]
for r in rows:
    try:v=float(r.get('vc'))
    except:continue
    d=str(r.get('fecha',''))[:10]
    if d and v>0:ss.append((pd.Timestamp(d),v))
vc=pd.DataFrame(ss,columns=['fecha','VC']).drop_duplicates('fecha').sort_values('fecha')

# Índices; contiene .INX, EEM, NDX, SPBLSCUP hasta 20/08.
m=pd.read_csv('data/analysis/googlefinance_alt_aligned_closes_20260402_20260820.csv')
m['fecha']=pd.to_datetime(m.fecha); m=m[['fecha','.INX','EEM','NDX','SPBLSCUP']]

# Completar 21,24,25,26 con cierres de mercado; BVL según Excel auditado.
import yfinance as yf
ext=yf.download(['^GSPC','EEM','^NDX'],start='2026-08-21',end='2026-08-27',auto_adjust=False,progress=False,group_by='ticker',threads=False)
bvl={'2026-08-21':460.43,'2026-08-24':459.44,'2026-08-25':464.16,'2026-08-26':462.34}
add=[]
for ds,b in bvl.items():
    d=pd.Timestamp(ds)
    def cl(sym):
        try:return float(ext.loc[d,(sym,'Close')])
        except:return np.nan
    add.append({'fecha':d,'.INX':cl('^GSPC'),'EEM':cl('EEM'),'NDX':cl('^NDX'),'SPBLSCUP':b})
m=pd.concat([m,pd.DataFrame(add)],ignore_index=True).drop_duplicates('fecha',keep='last').sort_values('fecha')

fx=fetch_bcrp_4060()
# Construir calendario de factores y arrastrar TC cuando BCRP tiene n.d., como el Excel.
df=vc.merge(m,on='fecha',how='inner').merge(fx,on='fecha',how='left').sort_values('fecha')
df['USD_PEN_4060']=df['USD_PEN_4060'].ffill()
cols=['.INX','EEM','SPBLSCUP','USD_PEN_4060','NDX']
df=df.dropna(subset=['VC']+cols).reset_index(drop=True)

# PRUEBA QUE PIDIÓ EL USUARIO: últimos 30 valores, ajuste polinomial grado 2 sobre esos mismos 30.
last30=df.tail(30).copy(); last30['poly_fit']=fit_in_sample(last30,cols)

# Control adicional: rolling one-step, cada target usa 30 observaciones previas.
p=[]
for i in range(30,len(df)):
    tr=df.iloc[i-30:i]; row=df.iloc[i]
    p.append({'fecha':row.fecha.strftime('%Y-%m-%d'),'VC':float(row.VC),'poly_one_step':design_fit_predict(tr,row,cols)})
pos=pd.DataFrame(p); pos30=pos.tail(30) if len(pos)>=30 else pos

# Modelo A actual en mismas fechas del ajuste de 30 para comparación descriptiva.
mon=json.loads(Path('public/data/dual_rolling30_monitor.json').read_text(encoding='utf-8'))
a=mon['models']['qqq']; amap={str(r.get('fecha'))[:10]:float(r['vc_estimated']) for r in a.get('history_one_step',[]) if r.get('vc_estimated') is not None and r.get('actual_vc') is not None}
cmp=last30[last30.fecha.dt.strftime('%Y-%m-%d').isin(amap)].copy(); cmp['A_vc']=cmp.fecha.dt.strftime('%Y-%m-%d').map(amap)
res={
 'spec_excel':'Últimos 30 valores; VC en nivel; polinomial grado 2 aditivo sin interacciones; factores S&P500(.INX), EEM, BVL(SPBLSCUP), USD/PEN BCRP PD04640PD, NDX; ajuste sobre los mismos 30 como en Excel.',
 'window':{'start':last30.fecha.iloc[0].strftime('%Y-%m-%d'),'end':last30.fecha.iloc[-1].strftime('%Y-%m-%d'),'n':len(last30)},
 'excel_like_in_sample':metrics(last30.VC,last30.poly_fit),
 'common_with_A':{'n':len(cmp),'poly':metrics(cmp.VC,cmp.poly_fit) if len(cmp)>1 else None,'A':metrics(cmp.VC,cmp.A_vc) if len(cmp)>1 else None},
 'one_step_control':metrics(pos30.VC,pos30.poly_one_step) if len(pos30)>1 else None,
 'rows':[{**r,'fecha':r['fecha'].strftime('%Y-%m-%d')} for r in last30[['fecha','VC','.INX','EEM','SPBLSCUP','USD_PEN_4060','NDX','poly_fit']].to_dict('records')]
}
OUT.parent.mkdir(exist_ok=True); OUT.write_text(json.dumps(res,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(res,ensure_ascii=False,indent=2))