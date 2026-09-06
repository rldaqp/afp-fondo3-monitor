from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path('public/habitat/data/fixed_models_2026.csv')
LEVEL90_JSON = Path('analysis/habitat_window_stability.json')
OUT_JSON = Path('analysis/habitat_returns90_compare.json')
OUT_CSV = Path('analysis/habitat_returns90_compare.csv')
PUBLIC_JSON = Path('public/habitat/data/returns90_compare_diagnostic.json')

CUT = pd.Timestamp('2026-08-17')
VALID = pd.Timestamp('2026-08-18')
LATEST = pd.Timestamp('2026-09-02')
RET_FACTORS = ['ret_SPY', 'ret_EEM', 'ret_MCHI', 'ret_QQQ', 'ret_SPBLSCUP']


def fit_returns(frame: pd.DataFrame) -> dict:
    X = frame[RET_FACTORS].to_numpy(float)
    y = frame['ret_vc_sbs'].to_numpy(float)
    X1 = np.column_stack([np.ones(len(X)), X])
    b, *_ = np.linalg.lstsq(X1, y, rcond=None)
    fitted = X1 @ b
    ssr = float(np.sum((y - fitted) ** 2))
    sst = float(np.sum((y - y.mean()) ** 2))
    n = len(y)
    k = len(RET_FACTORS)
    r2 = float(1 - ssr / sst) if sst else None
    adj = None if r2 is None or n <= k + 1 else float(1 - (1-r2)*(n-1)/(n-k-1))
    return {
        'intercept': float(b[0]),
        'beta': {f: float(b[i+1]) for i, f in enumerate(RET_FACTORS)},
        'r2': r2,
        'adj_r2': adj,
        'n': n,
    }


def predict_return(model: dict, frame: pd.DataFrame) -> np.ndarray:
    X = frame[RET_FACTORS].to_numpy(float)
    b = np.array([model['beta'][f] for f in RET_FACTORS], dtype=float)
    return model['intercept'] + X @ b


def metrics(actual, pred) -> dict:
    a = np.asarray(actual, float)
    p = np.asarray(pred, float)
    ok = np.isfinite(a) & np.isfinite(p) & (a != 0)
    e = (p[ok] / a[ok] - 1) * 100
    sse = float(np.sum((a[ok] - p[ok]) ** 2))
    sst = float(np.sum((a[ok] - np.mean(a[ok])) ** 2))
    return {
        'n': int(ok.sum()),
        'mae_pct': float(np.mean(np.abs(e))),
        'rmse_pct': float(np.sqrt(np.mean(e**2))),
        'bias_pct': float(np.mean(e)),
        'max_abs_pct': float(np.max(np.abs(e))),
        'r2_vc_oos': float(1 - sse/sst) if sst else None,
    }


def main():
    df = pd.read_csv(DATA)
    df['fecha'] = pd.to_datetime(df['fecha'])
    df = df.sort_values('fecha').drop_duplicates('fecha', keep='last').reset_index(drop=True)
    num_cols = ['vc_sbs', 'vc_retornos', 'ret_vc_sbs'] + RET_FACTORS
    for c in num_cols:
        df[c] = pd.to_numeric(df[c], errors='coerce')

    train_pool = df[(df['fecha'] <= CUT)].dropna(subset=RET_FACTORS + ['ret_vc_sbs']).copy()
    train90 = train_pool.tail(90).copy()
    if len(train90) != 90:
        raise RuntimeError(f'Expected 90 return observations, got {len(train90)}')
    model90 = fit_returns(train90)

    # R2/fit of published 30-return model is stored in fixed_models_2026.json, but
    # for the comparison rows we use the already published vc_retornos series.
    # Refit 30 here only to report a like-for-like training R2 check.
    train30 = train_pool.tail(30).copy()
    model30 = fit_returns(train30)

    compare = df[(df['fecha'] >= CUT) & (df['fecha'] <= LATEST)].copy()
    pred_r90 = predict_return(model90, compare)
    compare['ret90_pred_return'] = pred_r90

    # Same operational rule as production Retornos: predicted return is applied
    # to the previous available SBS VC. For every published comparison date here,
    # previous SBS exists in the source data.
    vc_by_date = df.set_index('fecha')['vc_sbs']
    prev_real = []
    vc90 = []
    for i, row in compare.iterrows():
        d = row['fecha']
        prior = df[(df['fecha'] < d) & df['vc_sbs'].notna()].tail(1)
        if prior.empty:
            prev_real.append(np.nan)
            vc90.append(np.nan)
            continue
        anchor = float(prior['vc_sbs'].iloc[0])
        prev_real.append(anchor)
        vc90.append(anchor * (1 + float(row['ret90_pred_return'])))
    compare['prev_sbs_vc'] = prev_real
    compare['vc_retornos90'] = vc90

    # Bring frozen Levels90 values from previous diagnostic by date.
    level90 = json.loads(LEVEL90_JSON.read_text(encoding='utf-8'))
    level90_map = {
        pd.Timestamp(r['fecha']): r.get('anchored_90')
        for r in level90.get('anchored_rows', [])
    }
    compare['vc_niveles90'] = compare['fecha'].map(level90_map)
    compare['vc_retornos30'] = compare['vc_retornos']

    for c in ['vc_niveles90', 'vc_retornos90', 'vc_retornos30']:
        compare[c + '_error_pct'] = (compare[c] / compare['vc_sbs'] - 1) * 100

    val = compare[compare['fecha'] >= VALID].dropna(subset=['vc_sbs']).copy()
    result = {
        'fund': 'HÁBITAT Fondo 3',
        'cut_date': CUT.strftime('%Y-%m-%d'),
        'latest_sbs_date': LATEST.strftime('%Y-%m-%d'),
        'returns90': {
            'train_start': train90['fecha'].min().strftime('%Y-%m-%d'),
            'train_end': train90['fecha'].max().strftime('%Y-%m-%d'),
            'n': 90,
            'r2_train': model90['r2'],
            'adj_r2_train': model90['adj_r2'],
            'coefficients': {'intercept': model90['intercept'], **model90['beta']},
            'validation_vc_metrics': metrics(val['vc_sbs'], val['vc_retornos90']),
        },
        'returns30_refit_check': {
            'train_start': train30['fecha'].min().strftime('%Y-%m-%d'),
            'train_end': train30['fecha'].max().strftime('%Y-%m-%d'),
            'n': 30,
            'r2_train': model30['r2'],
            'adj_r2_train': model30['adj_r2'],
            'validation_vc_metrics_published': metrics(val['vc_sbs'], val['vc_retornos30']),
        },
        'levels90': {
            'r2_train': level90['anchored_at_2026_08_17']['90']['r2_train'],
            'validation_vc_metrics': metrics(val['vc_sbs'], val['vc_niveles90']),
        },
        'rows': [],
    }

    cols = [
        'fecha','vc_sbs','vc_niveles90','vc_niveles90_error_pct',
        'vc_retornos90','vc_retornos90_error_pct',
        'vc_retornos30','vc_retornos30_error_pct','ret90_pred_return','prev_sbs_vc'
    ]
    out = compare[cols].copy()
    for _, r in out.iterrows():
        item = {}
        for c in cols:
            if c == 'fecha':
                item[c] = r[c].strftime('%Y-%m-%d')
            elif pd.isna(r[c]):
                item[c] = None
            else:
                item[c] = float(r[c])
        result['rows'].append(item)

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    PUBLIC_JSON.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT_CSV, index=False)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    OUT_JSON.write_text(text, encoding='utf-8')
    PUBLIC_JSON.write_text(text, encoding='utf-8')
    print(text)


if __name__ == '__main__':
    main()
