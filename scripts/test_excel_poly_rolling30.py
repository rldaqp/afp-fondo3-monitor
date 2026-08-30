import json, math, re
from pathlib import Path
from io import StringIO
import numpy as np
import pandas as pd
import requests

OUT=Path('analysis/test_excel_poly_rolling30.json')
BRANCH='migracion-github-actions'


def metrics(y,p):
    y=np.asarray(y,float); p=np.asarray(p,float)
    e=p-y
    sse=float(np.sum(e*e)); sst=float(np.sum((y-y.mean())**2))
    return {
      'n':int(len(y)),
      'pearson_r':float(np.corrcoef(y,p)[0,1]) if len(y)>1 else None,
      'corr2':float(np.corrcoef(y,p)[0,1]**2) if len(y)>1 else None,
      'predictive_r2':float(1-sse/sst) if sst>0 else None,
      'mae':float(np.mean(np.abs(e))),
      'rmse':float(np.sqrt(np.mean(e*e))),
      'mape_pct':float(np.mean(np.abs(e/y))*100),
      'bias':float(np.mean(e)),
    }


def poly_design(df, cols):
    # Polinomial simple grado 2, aditivo, sin interacciones: x y x^2.
    z=[]
    for c in cols:
        x=df[c].astype(float).to_numpy()
        mu=float(np.mean(x)); sd=float(np.std(x,ddof=0)) or 1.0
        u=(x-mu)/sd
        z += [u, u*u]
    return np.column_stack([np.ones(len(df))]+z)


def poly_fit_predict(train, row, cols):
    # Estandariza con SOLO el train y aplica el mismo escalado al target.
    mats=[np.ones(len(train))]; rv=[1.0]
    for c in cols:
        x=train[c].astype(float).to_numpy(); mu=float(np.mean(x)); sd=float(np.std(x,ddof=0)) or 1.0
        u=(x-mu)/sd; t=(float(row[c])-mu)/sd
        mats += [u,u*u]; rv += [t,t*t]
    X=np.column_stack(mats); y=train['VC'].astype(float).to_numpy()
    beta=np.linalg.lstsq(X,y,rcond=None)[0]
    return float(np.dot(np.asarray(rv,float),beta))


def fetch_bcrp_4060(start='2026-04-01',end='2026-08-28'):
    urls=[
      f'https://estadisticas.bcrp.gob.pe/estadisticas/series/api/PD04640PD/json/{start}/{end}/esp',
      f'https://estadisticas.bcrp.gob.pe/estadisticas/series/api/PD04640PD/json/{start}/{end}',
    ]
    for url in urls:
        try:
            r=requests.get(url,timeout=30,headers={'User-Agent':'Mozilla/5.0'})
            j=r.json()
            periods=j.get('periods',[])
            rows=[]
            for p in periods:
                name=p.get('name') or p.get('period') or ''
                vals=p.get('values') or []
                val=vals[0] if vals else None
                if val in (None,'n.d.',''):
                    continue
                # BCRP suele devolver dd.mm.yyyy / dd/mm/yyyy / yyyy-mm-dd según endpoint
                d=pd.to_datetime(name,dayfirst=True,errors='coerce')
                if pd.notna(d): rows.append((d.normalize(),float(str(val).replace(',','.'))))
            if rows:
                return pd.DataFrame(rows,columns=['fecha','USD_PEN_4060']).drop_duplicates('fecha').sort_values('fecha')
        except Exception as e:
            print('BCRP JSON fallo',url,type(e).__name__,e)
    # fallback HTML de resultados
    url=f'https://estadisticas.bcrp.gob.pe/estadisticas/series/diarias/resultados/PD04640PD/html/{start}/{end}/esp'
    r=requests.get(url,timeout=30,headers={'User-Agent':'Mozilla/5.0'})
    tabs=pd.read_html(StringIO(r.text),decimal='.',thousands=',')
    for t in tabs:
        if t.shape[1]>=2:
            a=t.iloc[:,0].astype(str); d=pd.to_datetime(a,dayfirst=True,errors='coerce')
            if d.notna().sum()>10:
                v=pd.to_numeric(t.iloc[:,1].astype(str).str.replace(',','.',regex=False),errors='coerce')
                o=pd.DataFrame({'fecha':d.dt.normalize(),'USD_PEN_4060':v}).dropna()
                if len(o)>10:return o.drop_duplicates('fecha').sort_values('fecha')
    raise RuntimeError('No se pudo obtener PD04640PD')

# SBS oficial
s=json.loads(Path('public/data/series.json').read_text(encoding='utf-8'))
rows=s if isinstance(s,list) else (s.get('series') or s.get('data') or s.get('rows') or [])
ss=[]
for r in rows:
    d=str(r.get('fecha',''))[:10]
    v=r.get('vc')
    official=(r.get('es_oficial') is True) or ('SBS' in str(r.get('fuente','')).upper())
    try:v=float(v)
    except:continue
    if d and v>0 and official:ss.append((pd.Timestamp(d),v))
vc=pd.DataFrame(ss,columns=['fecha','VC']).drop_duplicates('fecha').sort_values('fecha')
if len(vc)<60:
    # algunos series.json no marcan es_oficial; aceptar VC válidos si la serie es SBS del visor
    ss=[]
    for r in rows:
        d=str(r.get('fecha',''))[:10]
        try:v=float(r.get('vc'))
        except:continue
        if d and v>0:ss.append((pd.Timestamp(d),v))
    vc=pd.DataFrame(ss,columns=['fecha','VC']).drop_duplicates('fecha').sort_values('fecha')

# Factores base Google Finance / repositorio
m=pd.read_csv('data/analysis/googlefinance_alt_aligned_closes_20260402_20260820.csv')
m['fecha']=pd.to_datetime(m['fecha'])
m=m[['fecha','.INX','EEM','NDX','SPBLSCUP']].copy()

# Extender 21,24,25,26 con Yahoo para índices globales; BVL con cierres auditados/Excel.
try:
    import yfinance as yf
    ext=yf.download(['^GSPC','EEM','^NDX'],start='2026-08-21',end='2026-08-27',auto_adjust=False,progress=False,group_by='ticker',threads=False)
    add=[]
    bvl={'2026-08-21':460.43,'2026-08-24':459.44,'2026-08-25':464.16,'2026-08-26':462.34}
    for ds,b in bvl.items():
        d=pd.Timestamp(ds)
        def close(sym):
            try:return float(ext.loc[d,(sym,'Close')])
            except:return np.nan
        add.append({'fecha':d,'.INX':close('^GSPC'),'EEM':close('EEM'),'NDX':close('^NDX'),'SPBLSCUP':b})
    m=pd.concat([m,pd.DataFrame(add)],ignore_index=True).drop_duplicates('fecha',keep='last').sort_values('fecha')
except Exception as e:
    print('Yahoo extension fallo',e)

fx=fetch_bcrp_4060()
# Excel arrastra último dato cuando BCRP no publica n.d.; forward-fill SOLO sobre calendario de mercado al combinar.
df=vc.merge(m,on='fecha',how='inner').merge(fx,on='fecha',how='left').sort_values('fecha')
df['USD_PEN_4060']=df['USD_PEN_4060'].ffill()
cols=['.INX','EEM','SPBLSCUP','USD_PEN_4060','NDX']
df=df.dropna(subset=['VC']+cols).reset_index(drop=True)

pred=[]
for i in range(30,len(df)):
    tr=df.iloc[i-30:i].copy(); row=df.iloc[i]
    p=poly_fit_predict(tr,row,cols)
    pred.append({'fecha':row.fecha.strftime('%Y-%m-%d'),'VC':float(row.VC),'poly_vc':p,
                 'train_start':tr.fecha.iloc[0].strftime('%Y-%m-%d'),'train_end':tr.fecha.iloc[-1].strftime('%Y-%m-%d')})
pred_df=pd.DataFrame(pred)
last30=pred_df.tail(30).copy()

# Comparar contra A limpio/adaptativo en mismas fechas desde JSON actual
mon=json.loads(Path('public/data/dual_rolling30_monitor.json').read_text(encoding='utf-8'))
a=mon['models']['qqq']
amap={str(r.get('fecha'))[:10]:float(r['vc_estimated']) for r in a.get('history_one_step',[]) if r.get('vc_estimated') is not None and r.get('actual_vc') is not None}
common=last30[last30.fecha.isin(amap)].copy(); common['A_vc']=common.fecha.map(amap)
res={
 'spec':'Rolling 30; VC nivel; grado 2 aditivo sin interacciones; factores .INX, EEM, SPBLSCUP, BCRP PD04640PD, NDX; cada target usa exactamente 30 observaciones anteriores',
 'data_dates':{'first':df.fecha.min().strftime('%Y-%m-%d'),'last':df.fecha.max().strftime('%Y-%m-%d'),'n':len(df)},
 'poly_last30':metrics(last30.VC,last30.poly_vc),
 'poly_last30_start':last30.fecha.iloc[0] if len(last30) else None,
 'poly_last30_end':last30.fecha.iloc[-1] if len(last30) else None,
 'common_with_A':{
   'dates_n':len(common),
   'start':common.fecha.iloc[0] if len(common) else None,
   'end':common.fecha.iloc[-1] if len(common) else None,
   'poly':metrics(common.VC,common.poly_vc) if len(common) else None,
   'A':metrics(common.VC,common.A_vc) if len(common) else None,
 },
 'recent_rows':pred_df.tail(12).to_dict('records'),
 'last30_rows':last30.to_dict('records')
}
OUT.parent.mkdir(exist_ok=True)
OUT.write_text(json.dumps(res,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(res,ensure_ascii=False,indent=2))