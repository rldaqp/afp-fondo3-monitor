from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data' / 'rolling90'
ALT = ROOT / 'data' / 'analysis' / 'googlefinance_alt_6030_returns_20260303_20260820.csv'
OUT = ROOT / 'analysis' / 'epu_spbl_disagreement_analysis.json'

WINDOWS = [20,25,30]
CONTROL = ['ret_SPY','ret_EEM','ret_MCHI','ret_USD_PEN','ret_QQQ']


def read_csv(path: Path) -> pd.DataFrame:
    d = pd.read_csv(path)
    d['fecha'] = pd.to_datetime(d['fecha'], errors='coerce').dt.normalize()
    return d.dropna(subset=['fecha']).sort_values('fecha').drop_duplicates('fecha', keep='last').reset_index(drop=True)


def close_series(ticker: str, start='2026-02-15', end='2026-08-29') -> pd.DataFrame:
    raw = yf.download(ticker, start=start, end=end, auto_adjust=False, actions=False, progress=False, threads=False)
    if raw.empty:
        raise RuntimeError(f'Yahoo sin datos {ticker}')
    if isinstance(raw.columns, pd.MultiIndex):
        s = pd.to_numeric(raw[('Close',ticker)] if ('Close',ticker) in raw.columns else raw.xs('Close',axis=1,level=0).iloc[:,0], errors='coerce')
    else:
        s = pd.to_numeric(raw['Close'], errors='coerce')
    s = s.dropna(); idx = pd.to_datetime(s.index)
    if getattr(idx,'tz',None) is not None: idx = idx.tz_localize(None)
    d = pd.DataFrame({'fecha':idx.normalize(), ticker:s.to_numpy(float)}).sort_values('fecha').drop_duplicates('fecha', keep='last')
    d[f'ret_{ticker}'] = d[ticker].pct_change(fill_method=None)
    return d.reset_index(drop=True)


def fit_predict(train: pd.DataFrame, cur: pd.Series, features: list[str]) -> tuple[float, dict]:
    X = np.c_[np.ones(len(train)), train[features].to_numpy(float)]
    y = train['ret_target'].to_numpy(float)
    beta = np.linalg.lstsq(X, y, rcond=None)[0]
    pred = float(np.r_[1.0, cur[features].to_numpy(float)] @ beta)
    return pred, {'intercept':float(beta[0]), **{f:float(beta[i+1]) for i,f in enumerate(features)}}


def main():
    sbs = read_csv(DATA/'sbs_profuturo_f3.csv')
    sbs['valor_cuota'] = pd.to_numeric(sbs['valor_cuota'], errors='coerce')
    sbs = sbs.dropna(subset=['valor_cuota']).copy()
    sbs['ret_target'] = sbs['valor_cuota'].pct_change(fill_method=None)

    markets = read_csv(DATA/'markets.csv')
    qqq = close_series('QQQ')
    alt = read_csv(ALT)

    # SPBLSCUP historical series from repo; refresh recent tail from Yahoo when available.
    spbl = alt[['fecha','ret_SPBLSCUP']].copy()
    try:
        live = close_series('^SPBLPGPT')
        # Yahoo ticker availability may vary; only use if it exists and has plausible observations.
        if 'ret_^SPBLPGPT' in live.columns and live['ret_^SPBLPGPT'].notna().sum() > 5:
            live = live.rename(columns={'ret_^SPBLPGPT':'ret_SPBLSCUP'})[['fecha','ret_SPBLSCUP']]
            spbl = pd.concat([spbl, live], ignore_index=True).sort_values('fecha').drop_duplicates('fecha', keep='last')
    except Exception:
        pass

    # Explicit corrected recent returns already verified for SPBLSCUP.
    corrected = pd.DataFrame({
        'fecha':pd.to_datetime(['2026-08-21','2026-08-24','2026-08-25','2026-08-26']),
        'ret_SPBLSCUP':[460.43/446.70-1, 459.23/460.43-1, 464.16/459.23-1, 462.25/464.16-1]
    })
    spbl = pd.concat([spbl, corrected], ignore_index=True).sort_values('fecha').drop_duplicates('fecha', keep='last')

    f = (markets[['fecha','ret_SPY','ret_EEM','ret_EPU','ret_MCHI','ret_USD_PEN']]
         .merge(qqq[['fecha','ret_QQQ']], on='fecha', how='inner')
         .merge(spbl[['fecha','ret_SPBLSCUP']], on='fecha', how='inner'))
    frame = (sbs[['fecha','valor_cuota','ret_target']].merge(f,on='fecha',how='inner')
             .dropna(subset=['ret_target',*CONTROL,'ret_EPU','ret_SPBLSCUP'])
             .sort_values('fecha').reset_index(drop=True))

    last90 = frame.tail(90).copy()
    last90['sign_epu'] = np.sign(last90['ret_EPU'])
    last90['sign_spbl'] = np.sign(last90['ret_SPBLSCUP'])
    dis = last90[(last90.sign_epu != 0) & (last90.sign_spbl != 0) & (last90.sign_epu != last90.sign_spbl)].copy()

    rows=[]
    for _, cur in dis.iterrows():
        row = {
            'fecha':cur.fecha.date().isoformat(),
            'actual_return':float(cur.ret_target),
            'epu_return':float(cur.ret_EPU),
            'spbl_return':float(cur.ret_SPBLSCUP),
            'raw_direction_hit_epu': bool(np.sign(cur.ret_EPU)==np.sign(cur.ret_target)),
            'raw_direction_hit_spbl': bool(np.sign(cur.ret_SPBLSCUP)==np.sign(cur.ret_target)),
            'raw_abs_gap_epu_pp': float(abs(cur.ret_EPU-cur.ret_target)*100),
            'raw_abs_gap_spbl_pp': float(abs(cur.ret_SPBLSCUP-cur.ret_target)*100),
            'rolling':{}
        }
        pos = frame.index[frame.fecha.eq(cur.fecha)]
        if len(pos)==0: continue
        i = int(pos[0])
        for w in WINDOWS:
            if i < w: continue
            tr = frame.iloc[i-w:i]
            epu_features = CONTROL + ['ret_EPU']
            spbl_features = CONTROL + ['ret_SPBLSCUP']
            pe, be = fit_predict(tr, cur, epu_features)
            ps, bs = fit_predict(tr, cur, spbl_features)
            row['rolling'][f'R{w}'] = {
                'epu_model_pred_return':pe,
                'spbl_model_pred_return':ps,
                'epu_model_direction_hit':bool(np.sign(pe)==np.sign(cur.ret_target)),
                'spbl_model_direction_hit':bool(np.sign(ps)==np.sign(cur.ret_target)),
                'epu_model_abs_error_pp':float(abs(pe-cur.ret_target)*100),
                'spbl_model_abs_error_pp':float(abs(ps-cur.ret_target)*100),
                'better_magnitude':'EPU' if abs(pe-cur.ret_target) < abs(ps-cur.ret_target) else ('SPBLSCUP' if abs(ps-cur.ret_target) < abs(pe-cur.ret_target) else 'TIE'),
                'beta_epu':be['ret_EPU'],
                'beta_spbl':bs['ret_SPBLSCUP']
            }
        rows.append(row)

    summary={}
    for w in WINDOWS:
        k=f'R{w}'; valid=[r for r in rows if k in r['rolling']]
        if not valid: continue
        e_hits=sum(r['rolling'][k]['epu_model_direction_hit'] for r in valid)
        s_hits=sum(r['rolling'][k]['spbl_model_direction_hit'] for r in valid)
        e_mae=np.mean([r['rolling'][k]['epu_model_abs_error_pp'] for r in valid])
        s_mae=np.mean([r['rolling'][k]['spbl_model_abs_error_pp'] for r in valid])
        e_better=sum(r['rolling'][k]['better_magnitude']=='EPU' for r in valid)
        s_better=sum(r['rolling'][k]['better_magnitude']=='SPBLSCUP' for r in valid)
        summary[k]={
            'n_disagreement_days':len(valid),
            'epu_direction_hits':int(e_hits),
            'spbl_direction_hits':int(s_hits),
            'epu_direction_hit_rate_pct':float(100*e_hits/len(valid)),
            'spbl_direction_hit_rate_pct':float(100*s_hits/len(valid)),
            'epu_mean_abs_error_pp':float(e_mae),
            'spbl_mean_abs_error_pp':float(s_mae),
            'epu_better_magnitude_days':int(e_better),
            'spbl_better_magnitude_days':int(s_better)
        }

    payload={
        'purpose':'En los últimos 90 días válidos, identificar fechas donde EPU y SPBLSCUP tuvieron signo opuesto y comparar cuál representó mejor el retorno real del VC, tanto en bruto como dentro de modelos multivariables controlados.',
        'controls':CONTROL,
        'disagreement_definition':'sign(ret_EPU) != sign(ret_SPBLSCUP), excluyendo retornos cero.',
        'n_last90':int(len(last90)),
        'n_disagreement_days':int(len(rows)),
        'summary_controlled_models':summary,
        'days':rows
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(payload, ensure_ascii=False, indent=2))

if __name__=='__main__':
    main()
