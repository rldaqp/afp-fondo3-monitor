from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path('public/data/fixed_models_2026.csv')
OUT = Path('analysis/profuturo_holdout7_30_90.json')
PUBLIC = Path('public/data/profuturo_holdout7_30_90.json')

FACTORS = ['SPY','EEM','MCHI','QQQ','SPBLSCUP']
RET_FACTORS = [f'ret_{x}' for x in FACTORS]
N_HOLDOUT = 7


def ols(frame: pd.DataFrame, xcols: list[str], ycol: str):
    d = frame[[ycol, *xcols]].dropna().copy()
    X = d[xcols].to_numpy(float)
    y = d[ycol].to_numpy(float)
    X1 = np.column_stack([np.ones(len(X)), X])
    b, *_ = np.linalg.lstsq(X1, y, rcond=None)
    fitted = X1 @ b
    sse = float(np.sum((y-fitted)**2))
    sst = float(np.sum((y-y.mean())**2))
    r2 = 1 - sse/sst if sst else np.nan
    p = len(xcols)
    adj = 1 - (1-r2)*(len(y)-1)/(len(y)-p-1)
    return d, b, float(r2), float(adj), fitted


def pred(b, frame: pd.DataFrame, xcols: list[str]):
    X = frame[xcols].to_numpy(float)
    return b[0] + X @ b[1:]


def metrics(actual, predv):
    a = np.asarray(actual, float)
    p = np.asarray(predv, float)
    e = (p/a - 1) * 100
    sse = float(np.sum((a-p)**2))
    sst = float(np.sum((a-a.mean())**2))
    return {
        'n': int(len(a)),
        'mae_pct': float(np.mean(np.abs(e))),
        'rmse_pct': float(np.sqrt(np.mean(e**2))),
        'bias_pct': float(np.mean(e)),
        'max_abs_pct': float(np.max(np.abs(e))),
        'r2_vc_oos': float(1-sse/sst) if sst else None,
    }


def model_block(train, b, r2, adj, fitted, xcols, ycol, hold_actual, hold_pred):
    return {
        'training': {
            'start': train.fecha.min().strftime('%Y-%m-%d'),
            'end': train.fecha.max().strftime('%Y-%m-%d'),
            'n': int(len(train)),
        },
        'r2_train': r2,
        'adj_r2_train': adj,
        'coefficients': dict(zip(['intercept'] + xcols, [float(x) for x in b])),
        'train_metrics': metrics(train[ycol], fitted) if ycol == 'vc_sbs' else {
            'n': int(len(train)),
            'mae_return_pct': float(np.mean(np.abs((fitted-train[ycol].to_numpy(float))*100))),
            'rmse_return_pct': float(np.sqrt(np.mean(((fitted-train[ycol].to_numpy(float))*100)**2))),
        },
        'holdout_metrics': metrics(hold_actual, hold_pred),
    }


def main():
    df = pd.read_csv(DATA)
    df['fecha'] = pd.to_datetime(df['fecha'], errors='coerce')
    df = df.dropna(subset=['fecha']).sort_values('fecha').drop_duplicates('fecha', keep='last').reset_index(drop=True)

    for c in FACTORS + ['vc_sbs']:
        df[c] = pd.to_numeric(df[c], errors='coerce')
    for c in FACTORS:
        df[f'ret_{c}'] = df[c].pct_change(fill_method=None)
    df['ret_vc_sbs'] = df['vc_sbs'].pct_change(fill_method=None)

    # Las 7 últimas observaciones SBS reales definen el holdout.
    actual_rows = df.dropna(subset=FACTORS + ['vc_sbs']).copy()
    hold = actual_rows.tail(N_HOLDOUT).copy().reset_index(drop=True)
    cutoff = hold['fecha'].min()

    # Pool para Niveles: VC y factores completos antes del holdout.
    level_pool = df[(df['fecha'] < cutoff)].dropna(subset=FACTORS + ['vc_sbs']).copy()
    trainL30 = level_pool.tail(30).copy().reset_index(drop=True)
    trainL90 = level_pool.tail(90).copy().reset_index(drop=True)

    # Pool para Retornos: retorno SBS y retornos de factores completos antes del holdout.
    return_pool = df[(df['fecha'] < cutoff)].dropna(subset=RET_FACTORS + ['ret_vc_sbs']).copy()
    trainR30 = return_pool.tail(30).copy().reset_index(drop=True)
    trainR90 = return_pool.tail(90).copy().reset_index(drop=True)

    if len(trainL90) < 90 or len(trainR90) < 90:
        raise RuntimeError(f'Muestra insuficiente: niveles90={len(trainL90)}, retornos90={len(trainR90)}')

    dL30,bL30,r2L30,adjL30,fitL30 = ols(trainL30, FACTORS, 'vc_sbs')
    dL90,bL90,r2L90,adjL90,fitL90 = ols(trainL90, FACTORS, 'vc_sbs')
    dR30,bR30,r2R30,adjR30,fitR30 = ols(trainR30, RET_FACTORS, 'ret_vc_sbs')
    dR90,bR90,r2R90,adjR90,fitR90 = ols(trainR90, RET_FACTORS, 'ret_vc_sbs')

    hold['vc_niveles30'] = pred(bL30, hold, FACTORS)
    hold['vc_niveles90'] = pred(bL90, hold, FACTORS)

    # Retornos del holdout se calculan sobre las variaciones de mercado ya observadas.
    # Como las 7 fechas son consecutivas con VC SBS publicado, la base es el VC SBS real de la rueda anterior.
    hold['ret30_pred'] = pred(bR30, hold, RET_FACTORS)
    hold['ret90_pred'] = pred(bR90, hold, RET_FACTORS)

    prev = df[['fecha','vc_sbs']].copy()
    prev['prev_sbs_vc'] = prev['vc_sbs'].shift(1)
    pmap = prev.set_index('fecha')['prev_sbs_vc']
    hold['prev_sbs_vc'] = hold['fecha'].map(pmap)
    if hold['prev_sbs_vc'].isna().any():
        raise RuntimeError('Alguna fecha del holdout no tiene VC SBS real inmediatamente anterior')
    hold['vc_retornos30'] = hold['prev_sbs_vc'] * (1 + hold['ret30_pred'])
    hold['vc_retornos90'] = hold['prev_sbs_vc'] * (1 + hold['ret90_pred'])

    rows = []
    for _, r in hold.iterrows():
        rows.append({
            'fecha': r.fecha.strftime('%Y-%m-%d'),
            'vc_sbs': float(r.vc_sbs),
            'vc_niveles30': float(r.vc_niveles30),
            'error_niveles30_pct': float((r.vc_niveles30/r.vc_sbs-1)*100),
            'vc_niveles90': float(r.vc_niveles90),
            'error_niveles90_pct': float((r.vc_niveles90/r.vc_sbs-1)*100),
            'vc_retornos30': float(r.vc_retornos30),
            'error_retornos30_pct': float((r.vc_retornos30/r.vc_sbs-1)*100),
            'vc_retornos90': float(r.vc_retornos90),
            'error_retornos90_pct': float((r.vc_retornos90/r.vc_sbs-1)*100),
            'retorno_real_pct': float(r.ret_vc_sbs*100),
            'retorno_estimado30_pct': float(r.ret30_pred*100),
            'retorno_estimado90_pct': float(r.ret90_pred*100),
        })

    out = {
        'fund': 'PROFUTURO Fondo 3',
        'logic': 'Prueba aislada. Se dejan fuera las 7 últimas fechas con VC SBS real. Niveles 30/90 y Retornos 30/90 se ajustan solo con observaciones anteriores. Retornos aplica el retorno estimado al VC SBS real de la rueda anterior. Producción no se modifica.',
        'holdout': {
            'start': hold.fecha.min().strftime('%Y-%m-%d'),
            'end': hold.fecha.max().strftime('%Y-%m-%d'),
            'n': int(len(hold)),
        },
        'levels30': model_block(dL30,bL30,r2L30,adjL30,fitL30,FACTORS,'vc_sbs',hold.vc_sbs,hold.vc_niveles30),
        'levels90': model_block(dL90,bL90,r2L90,adjL90,fitL90,FACTORS,'vc_sbs',hold.vc_sbs,hold.vc_niveles90),
        'returns30': model_block(dR30,bR30,r2R30,adjR30,fitR30,RET_FACTORS,'ret_vc_sbs',hold.vc_sbs,hold.vc_retornos30),
        'returns90': model_block(dR90,bR90,r2R90,adjR90,fitR90,RET_FACTORS,'ret_vc_sbs',hold.vc_sbs,hold.vc_retornos90),
        'rows': rows,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    PUBLIC.parent.mkdir(parents=True, exist_ok=True)
    txt = json.dumps(out, ensure_ascii=False, indent=2)
    OUT.write_text(txt, encoding='utf-8')
    PUBLIC.write_text(txt, encoding='utf-8')
    print(txt)


if __name__ == '__main__':
    main()
