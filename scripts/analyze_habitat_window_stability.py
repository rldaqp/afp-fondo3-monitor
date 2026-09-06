from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path('public/habitat/data/fixed_models_2026.csv')
OUT_JSON = Path('analysis/habitat_window_stability.json')
OUT_CSV = Path('analysis/habitat_window_stability.csv')
PUBLIC_JSON = Path('public/habitat/data/window_stability_diagnostic.json')

FACTORS = ['SPY', 'EEM', 'MCHI', 'QQQ', 'SPBLSCUP']
WINDOWS = [30, 50, 60, 90]
START = pd.Timestamp('2026-07-07')
CUT = pd.Timestamp('2026-08-17')
VALID = pd.Timestamp('2026-08-18')

FACTOR_SETS = {
    'full_5': FACTORS,
    'no_mchi': [f for f in FACTORS if f != 'MCHI'],
    'no_spblscup': [f for f in FACTORS if f != 'SPBLSCUP'],
    'no_mchi_spblscup': [f for f in FACTORS if f not in {'MCHI', 'SPBLSCUP'}],
}


def fit(frame: pd.DataFrame, factors: list[str]) -> dict:
    X = frame[factors].to_numpy(float)
    y = frame['vc_sbs'].to_numpy(float)
    X1 = np.column_stack([np.ones(len(X)), X])
    b, *_ = np.linalg.lstsq(X1, y, rcond=None)
    fitted = X1 @ b
    ssr = float(np.sum((y - fitted) ** 2))
    sst = float(np.sum((y - y.mean()) ** 2))
    return {
        'intercept': float(b[0]),
        'beta': {f: float(b[i + 1]) for i, f in enumerate(factors)},
        'r2': float(1 - ssr / sst) if sst else None,
    }


def predict(model: dict, frame: pd.DataFrame, factors: list[str]) -> np.ndarray:
    if frame.empty:
        return np.array([], dtype=float)
    X = frame[factors].to_numpy(float)
    b = np.array([model['beta'][f] for f in factors], dtype=float)
    return model['intercept'] + X @ b


def metric(actual, pred) -> dict:
    a = np.asarray(actual, float)
    p = np.asarray(pred, float)
    ok = np.isfinite(a) & np.isfinite(p) & (a != 0)
    if not ok.any():
        return {'n': 0, 'mae_pct': None, 'rmse_pct': None, 'bias_pct': None, 'max_abs_pct': None}
    e = (p[ok] / a[ok] - 1) * 100
    return {
        'n': int(ok.sum()),
        'mae_pct': float(np.mean(np.abs(e))),
        'rmse_pct': float(np.sqrt(np.mean(e ** 2))),
        'bias_pct': float(np.mean(e)),
        'max_abs_pct': float(np.max(np.abs(e))),
    }


def rows_with_errors(frame: pd.DataFrame, pred_cols: list[str]) -> list[dict]:
    out = []
    for _, r in frame.iterrows():
        item = {'fecha': r['fecha'].strftime('%Y-%m-%d'), 'vc_sbs': float(r['vc_sbs'])}
        for c in pred_cols:
            v = r.get(c, np.nan)
            item[c] = None if pd.isna(v) else float(v)
            item[c + '_error_pct'] = None if pd.isna(v) else float((v / r['vc_sbs'] - 1) * 100)
        out.append(item)
    return out


def main():
    df = pd.read_csv(DATA)
    df['fecha'] = pd.to_datetime(df['fecha'])
    df = df.sort_values('fecha').drop_duplicates('fecha', keep='last').reset_index(drop=True)
    for c in FACTORS + ['vc_sbs', 'vc_niveles', 'vc_retornos']:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors='coerce')

    real = df.dropna(subset=FACTORS + ['vc_sbs']).copy().reset_index(drop=True)
    latest_date = real['fecha'].max()
    latest_vc = float(real.loc[real['fecha'].idxmax(), 'vc_sbs'])
    pre20_dates = list(real.loc[real['fecha'] < START, 'fecha'].tail(20))

    original = real[(real['fecha'] >= START) & (real['fecha'] <= CUT)].copy()
    validation = real[real['fecha'] >= VALID].copy()
    anchor_pool = real[real['fecha'] <= CUT].copy()
    after_latest = df[(df['fecha'] > latest_date) & df[FACTORS].notna().all(axis=1)].copy()

    result = {
        'fund': 'HÁBITAT Fondo 3',
        'note': 'Los factores son proxies estadísticos, no tenencias declaradas.',
        'factors': FACTORS,
        'windows': WINDOWS,
        'original_training': {'start': '2026-07-07', 'end': '2026-08-17', 'n': 30},
        'latest_sbs': {'date': latest_date.strftime('%Y-%m-%d'), 'vc': latest_vc},
        'anchored_at_2026_08_17': {},
        'walk_forward': {},
        'factor_ablation_anchored_validation': {},
    }

    # 1) Modelos congelados en 17/08: comparación justa 30/50/60/90 hacia adelante.
    anchored_rows = real[(real['fecha'] >= START) & (real['fecha'] <= latest_date)][['fecha', 'vc_sbs'] + FACTORS].copy()
    for w in WINDOWS:
        train = anchor_pool.tail(w)
        if len(train) < w:
            continue
        m = fit(train, FACTORS)
        anchored_rows[f'anchored_{w}'] = predict(m, anchored_rows, FACTORS)
        pred_train = predict(m, train, FACTORS)
        pred_orig = predict(m, original, FACTORS)
        pred_val = predict(m, validation, FACTORS)
        cut_row = original[original['fecha'] == CUT]
        cut_est = float(predict(m, cut_row, FACTORS)[0])
        projections = []
        for i, (_, r) in enumerate(after_latest.iterrows()):
            projections.append({
                'fecha': r['fecha'].strftime('%Y-%m-%d'),
                'vc_est': float(predict(m, pd.DataFrame([r]), FACTORS)[0]),
            })
        result['anchored_at_2026_08_17'][str(w)] = {
            'train_start': train['fecha'].min().strftime('%Y-%m-%d'),
            'train_end': train['fecha'].max().strftime('%Y-%m-%d'),
            'n': int(len(train)),
            'r2_train': m['r2'],
            'coefficients': {'intercept': m['intercept'], **m['beta']},
            'train_metrics': metric(train['vc_sbs'], pred_train),
            'original_period_metrics': metric(original['vc_sbs'], pred_orig),
            'validation_metrics': metric(validation['vc_sbs'], pred_val),
            'cut_2026_08_17': {
                'vc_sbs': float(cut_row['vc_sbs'].iloc[0]),
                'vc_est': cut_est,
                'error_pct': float((cut_est / cut_row['vc_sbs'].iloc[0] - 1) * 100),
            },
            'projection_after_latest_sbs': projections,
        }

    result['anchored_rows'] = rows_with_errors(
        anchored_rows,
        [f'anchored_{w}' for w in WINDOWS if f'anchored_{w}' in anchored_rows.columns],
    )

    # Ajuste publicado actual de 30 observaciones dentro de su ventana original.
    if 'vc_niveles' in df.columns:
        published = df[(df['fecha'] >= START) & (df['fecha'] <= CUT)][['fecha', 'vc_sbs', 'vc_niveles']].dropna().copy()
        result['published_fixed_30_training_fit'] = {
            'metrics': metric(published['vc_sbs'], published['vc_niveles']),
            'rows': rows_with_errors(published, ['vc_niveles']),
        }

    # 2) Walk-forward estricto: para cada día solo se usan las W observaciones reales anteriores.
    first_eval = pre20_dates[0] if pre20_dates else START
    targets = real[(real['fecha'] >= first_eval) & (real['fecha'] <= latest_date)].copy()
    wf_rows = []
    for _, target in targets.iterrows():
        rec = {'fecha': target['fecha'], 'vc_sbs': float(target['vc_sbs'])}
        prior = real[real['fecha'] < target['fecha']]
        for w in WINDOWS:
            tr = prior.tail(w)
            if len(tr) == w:
                m = fit(tr, FACTORS)
                rec[f'wf_{w}'] = float(predict(m, pd.DataFrame([target]), FACTORS)[0])
            else:
                rec[f'wf_{w}'] = np.nan
        wf_rows.append(rec)
    wf = pd.DataFrame(wf_rows)

    for w in WINDOWS:
        c = f'wf_{w}'
        segments = {
            'pre20_before_07jul': wf[wf['fecha'].isin(pre20_dates)],
            'original_period_07jul_17aug': wf[(wf['fecha'] >= START) & (wf['fecha'] <= CUT)],
            'validation_18aug_latest': wf[wf['fecha'] >= VALID],
            'combined_07jul_latest': wf[wf['fecha'] >= START],
        }
        result['walk_forward'][str(w)] = {
            k: metric(v['vc_sbs'], v[c]) for k, v in segments.items()
        }
    result['walk_forward_rows'] = rows_with_errors(wf, [f'wf_{w}' for w in WINDOWS])

    # 3) Prueba de hipótesis cartera/proxy: quitar MCHI y/o SPBLSCUP, congelando también al 17/08.
    for set_name, factors in FACTOR_SETS.items():
        result['factor_ablation_anchored_validation'][set_name] = {}
        for w in WINDOWS:
            tr = anchor_pool.dropna(subset=factors + ['vc_sbs']).tail(w)
            if len(tr) < w:
                continue
            m = fit(tr, factors)
            pv = predict(m, validation, factors)
            result['factor_ablation_anchored_validation'][set_name][str(w)] = {
                'validation_metrics': metric(validation['vc_sbs'], pv),
                'coefficients': {'intercept': m['intercept'], **m['beta']},
            }

    ranking = []
    for w, b in result['anchored_at_2026_08_17'].items():
        vm = b['validation_metrics']
        ranking.append({'window': int(w), **vm})
    ranking.sort(key=lambda x: x['mae_pct'] if x['mae_pct'] is not None else 1e9)
    result['ranking_anchored_validation'] = ranking

    # CSV legible: VC real, modelos congelados y walk-forward desde 07/07 hasta último SBS.
    flat = anchored_rows.copy()
    wf_index = wf.set_index('fecha')
    for w in WINDOWS:
        flat[f'wf_{w}'] = flat['fecha'].map(wf_index[f'wf_{w}'])
    if 'vc_niveles' in df.columns:
        fixed_map = df.set_index('fecha')['vc_niveles']
        flat['published_fixed_30'] = flat['fecha'].map(fixed_map)
    flat = flat.drop(columns=FACTORS)

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    PUBLIC_JSON.parent.mkdir(parents=True, exist_ok=True)
    flat.to_csv(OUT_CSV, index=False)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    OUT_JSON.write_text(text, encoding='utf-8')
    PUBLIC_JSON.write_text(text, encoding='utf-8')

    print(json.dumps({
        'latest_sbs': result['latest_sbs'],
        'ranking_anchored_validation': result['ranking_anchored_validation'],
        'cut_values': {w: result['anchored_at_2026_08_17'][str(w)]['cut_2026_08_17'] for w in WINDOWS},
        'walk_forward': result['walk_forward'],
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
