from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path('public/habitat/data/fixed_models_2026.csv')
OUT = Path('analysis/habitat_holdout7_30.json')
PUBLIC = Path('public/habitat/data/holdout7_30_diagnostic.json')

FACTORS = ['SPY','EEM','MCHI','QQQ','SPBLSCUP']
RET_FACTORS = ['ret_SPY','ret_EEM','ret_MCHI','ret_QQQ','ret_SPBLSCUP']
N_TRAIN = 30
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
    train=train_pool.tail(N_TRAIN).copy().reset_index(drop=True)

    bL,r2L,adjL,fitL=ols(train,FACTORS,'vc_sbs')
    bR,r2R,adjR,fitR=ols(train,RET_FACTORS,'ret_vc_sbs')

    hold['vc_niveles30_new']=pred(bL,hold,FACTORS)
    hold['ret30_pred']=pred(bR,hold,RET_FACTORS)
    # Same operational rule as production: apply predicted return to prior real SBS VC.
    prev_real = real.set_index('fecha')['vc_sbs'].shift(1)
    # Build previous real VC by row order, including first holdout's prior day.
    real_prev = real[['fecha','vc_sbs']].copy()
    real_prev['prev_sbs_vc']=real_prev['vc_sbs'].shift(1)
    pmap=real_prev.set_index('fecha')['prev_sbs_vc']
    hold['prev_sbs_vc']=hold['fecha'].map(pmap)
    hold['vc_retornos30_new']=hold['prev_sbs_vc']*(1+hold['ret30_pred'])

    rows=[]
    for _,r in hold.iterrows():
      item={
       'fecha':r.fecha.strftime('%Y-%m-%d'),
       'vc_sbs':float(r.vc_sbs),
       'vc_niveles30':float(r.vc_niveles30_new),
       'error_niveles30_pct':float((r.vc_niveles30_new/r.vc_sbs-1)*100),
       'vc_retornos30':float(r.vc_retornos30_new),
       'error_retornos30_pct':float((r.vc_retornos30_new/r.vc_sbs-1)*100),
       'retorno_real_pct':float(r.ret_vc_sbs*100),
       'retorno_estimado30_pct':float(r.ret30_pred*100),
      }
      rows.append(item)

    out={
      'fund':'HÁBITAT Fondo 3',
      'logic':'30 observaciones de entrenamiento; 7 últimas fechas SBS completamente fuera de muestra.',
      'training':{
        'start':train.fecha.min().strftime('%Y-%m-%d'),
        'end':train.fecha.max().strftime('%Y-%m-%d'),
        'n':int(len(train)),
      },
      'holdout':{
        'start':hold.fecha.min().strftime('%Y-%m-%d'),
        'end':hold.fecha.max().strftime('%Y-%m-%d'),
        'n':int(len(hold)),
      },
      'levels30':{
        'r2_train':r2L,'adj_r2_train':adjL,
        'coefficients':dict(zip(['intercept']+FACTORS,[float(x) for x in bL])),
        'train_metrics':metrics(train.vc_sbs,fitL),
        'holdout_metrics':metrics(hold.vc_sbs,hold.vc_niveles30_new),
      },
      'returns30':{
        'r2_train':r2R,'adj_r2_train':adjR,
        'coefficients':dict(zip(['intercept']+RET_FACTORS,[float(x) for x in bR])),
        'train_return_mae_pct':float(np.mean(np.abs((fitR-train.ret_vc_sbs.to_numpy())*100))),
        'holdout_metrics':metrics(hold.vc_sbs,hold.vc_retornos30_new),
      },
      'rows':rows,
    }
    OUT.parent.mkdir(parents=True,exist_ok=True); PUBLIC.parent.mkdir(parents=True,exist_ok=True)
    txt=json.dumps(out,ensure_ascii=False,indent=2)
    OUT.write_text(txt,encoding='utf-8'); PUBLIC.write_text(txt,encoding='utf-8')
    print(txt)

if __name__=='__main__': main()
