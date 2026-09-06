from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path('public/habitat/data/fixed_models_2026.csv')
OUT = Path('analysis/habitat_holdout7_compare_30_90.json')
PUBLIC = Path('public/habitat/data/holdout7_compare_30_90.json')

FACTORS = ['SPY','EEM','MCHI','QQQ','SPBLSCUP']
RET_FACTORS = ['ret_SPY','ret_EEM','ret_MCHI','ret_QQQ','ret_SPBLSCUP']
N_HOLDOUT = 7


def ols(frame, xcols, ycol):
    X = frame[xcols].to_numpy(float)
    y = frame[ycol].to_numpy(float)
    X1 = np.column_stack([np.ones(len(X)), X])
    b, *_ = np.linalg.lstsq(X1, y, rcond=None)
    fitted = X1 @ b
    sse = float(np.sum((y-fitted)**2))
    sst = float(np.sum((y-y.mean())**2))
    r2 = 1 - sse/sst if sst else np.nan
    p = len(xcols)
    adj = 1 - (1-r2)*(len(y)-1)/(len(y)-p-1)
    return b, float(r2), float(adj), fitted


def pred(b, frame, xcols):
    X = frame[xcols].to_numpy(float)
    return b[0] + X @ b[1:]


def metrics(actual, predv):
    a=np.asarray(actual,float); p=np.asarray(predv,float)
    e=(p/a-1)*100
    sse=float(np.sum((a-p)**2)); sst=float(np.sum((a-a.mean())**2))
    return {
      'n': int(len(a)),
      'mae_pct': float(np.mean(np.abs(e))),
      'rmse_pct': float(np.sqrt(np.mean(e**2))),
      'bias_pct': float(np.mean(e)),
      'max_abs_pct': float(np.max(np.abs(e))),
      'r2_vc_oos': float(1-sse/sst) if sst else None,
    }


def main():
    df=pd.read_csv(DATA)
    df['fecha']=pd.to_datetime(df['fecha'])
    df=df.sort_values('fecha').drop_duplicates('fecha',keep='last').reset_index(drop=True)
    for c in FACTORS+RET_FACTORS+['vc_sbs','ret_vc_sbs']:
        df[c]=pd.to_numeric(df[c],errors='coerce')

    real=df.dropna(subset=FACTORS+RET_FACTORS+['vc_sbs','ret_vc_sbs']).copy().reset_index(drop=True)
    hold=real.tail(N_HOLDOUT).copy().reset_index(drop=True)
    cutoff=hold['fecha'].min()
    train_pool=real[real['fecha']<cutoff].copy()
    train30=train_pool.tail(30).copy().reset_index(drop=True)
    train90=train_pool.tail(90).copy().reset_index(drop=True)

    bL30,r2L30,adjL30,fitL30=ols(train30,FACTORS,'vc_sbs')
    bL90,r2L90,adjL90,fitL90=ols(train90,FACTORS,'vc_sbs')
    bR30,r2R30,adjR30,fitR30=ols(train30,RET_FACTORS,'ret_vc_sbs')

    hold['vc_niveles30']=pred(bL30,hold,FACTORS)
    hold['vc_niveles90']=pred(bL90,hold,FACTORS)
    hold['ret30_pred']=pred(bR30,hold,RET_FACTORS)

    real_prev=real[['fecha','vc_sbs']].copy()
    real_prev['prev_sbs_vc']=real_prev['vc_sbs'].shift(1)
    pmap=real_prev.set_index('fecha')['prev_sbs_vc']
    hold['prev_sbs_vc']=hold['fecha'].map(pmap)
    hold['vc_retornos30']=hold['prev_sbs_vc']*(1+hold['ret30_pred'])

    rows=[]
    for _,r in hold.iterrows():
      rows.append({
       'fecha':r.fecha.strftime('%Y-%m-%d'),
       'vc_sbs':float(r.vc_sbs),
       'vc_niveles30':float(r.vc_niveles30),
       'error_niveles30_pct':float((r.vc_niveles30/r.vc_sbs-1)*100),
       'vc_niveles90':float(r.vc_niveles90),
       'error_niveles90_pct':float((r.vc_niveles90/r.vc_sbs-1)*100),
       'vc_retornos30':float(r.vc_retornos30),
       'error_retornos30_pct':float((r.vc_retornos30/r.vc_sbs-1)*100),
       'retorno_real_pct':float(r.ret_vc_sbs*100),
       'retorno_estimado30_pct':float(r.ret30_pred*100),
      })

    out={
      'fund':'HÁBITAT Fondo 3',
      'logic':'Mismo holdout de 7 últimas fechas SBS; Niveles 30 y Retornos 30 usan 30 observaciones previas; Niveles 90 usa 90 observaciones previas. Ningún modelo usa las 7 fechas de validación para estimar coeficientes.',
      'holdout':{
        'start':hold.fecha.min().strftime('%Y-%m-%d'),
        'end':hold.fecha.max().strftime('%Y-%m-%d'),
        'n':int(len(hold)),
      },
      'levels30':{
        'training':{'start':train30.fecha.min().strftime('%Y-%m-%d'),'end':train30.fecha.max().strftime('%Y-%m-%d'),'n':int(len(train30))},
        'r2_train':r2L30,'adj_r2_train':adjL30,
        'coefficients':dict(zip(['intercept']+FACTORS,[float(x) for x in bL30])),
        'train_metrics':metrics(train30.vc_sbs,fitL30),
        'holdout_metrics':metrics(hold.vc_sbs,hold.vc_niveles30),
      },
      'levels90':{
        'training':{'start':train90.fecha.min().strftime('%Y-%m-%d'),'end':train90.fecha.max().strftime('%Y-%m-%d'),'n':int(len(train90))},
        'r2_train':r2L90,'adj_r2_train':adjL90,
        'coefficients':dict(zip(['intercept']+FACTORS,[float(x) for x in bL90])),
        'train_metrics':metrics(train90.vc_sbs,fitL90),
        'holdout_metrics':metrics(hold.vc_sbs,hold.vc_niveles90),
      },
      'returns30':{
        'training':{'start':train30.fecha.min().strftime('%Y-%m-%d'),'end':train30.fecha.max().strftime('%Y-%m-%d'),'n':int(len(train30))},
        'r2_train':r2R30,'adj_r2_train':adjR30,
        'coefficients':dict(zip(['intercept']+RET_FACTORS,[float(x) for x in bR30])),
        'train_return_mae_pct':float(np.mean(np.abs((fitR30-train30.ret_vc_sbs.to_numpy())*100))),
        'holdout_metrics':metrics(hold.vc_sbs,hold.vc_retornos30),
      },
      'rows':rows,
    }
    OUT.parent.mkdir(parents=True,exist_ok=True); PUBLIC.parent.mkdir(parents=True,exist_ok=True)
    txt=json.dumps(out,ensure_ascii=False,indent=2)
    OUT.write_text(txt,encoding='utf-8'); PUBLIC.write_text(txt,encoding='utf-8')
    print(txt)

if __name__=='__main__': main()
