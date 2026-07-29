from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

import test_specific_portfolio as exp

OUT = exp.OUT


def join_predictions(predictions: dict[str, pd.DataFrame]) -> pd.DataFrame:
    paired = None
    for name, frame in predictions.items():
        z = frame[['fecha','actual','actual_signal','pred','pred_signal']].rename(
            columns={'pred':f'pred_{name}','pred_signal':f'signal_{name}'})
        if paired is None:
            paired = z
        else:
            paired = paired.merge(z[['fecha',f'pred_{name}',f'signal_{name}']],on='fecha',how='outer')
    return paired.sort_values('fecha').reset_index(drop=True)


def fair_scores(paired: pd.DataFrame, names: list[str]) -> tuple[dict, pd.DataFrame]:
    needed=[f'pred_{name}' for name in names]
    common=paired.dropna(subset=needed).sort_values('fecha').reset_index(drop=True)
    n=len(common); a=int(n*.6); b=int(n*.8)
    scores={}
    for name in names:
        frame=pd.DataFrame({
            'fecha':common['fecha'],
            'actual':common['actual'],
            'actual_signal':common['actual_signal'],
            'pred':common[f'pred_{name}'],
            'pred_signal':common[f'signal_{name}'],
        })
        scores[name]={
            'all':exp.metrics(frame),
            'validation':exp.metrics(frame.iloc[a:b]),
            'test':exp.metrics(frame.iloc[b:]),
            'last90':exp.metrics(frame.tail(90)),
        }
    return scores,common


def comparison_from_common(common: pd.DataFrame, name: str) -> dict:
    base_ok=common['signal_base7']==common['actual_signal']
    cand_ok=common[f'signal_{name}']==common['actual_signal']
    n=len(common); b=int(n*.8); test=common.iloc[b:]
    tb=test['signal_base7']==test['actual_signal']; tc=test[f'signal_{name}']==test['actual_signal']
    return {
        'corrected_all':common.loc[~base_ok&cand_ok,'fecha'].dt.strftime('%Y-%m-%d').tolist(),
        'created_all':common.loc[base_ok&~cand_ok,'fecha'].dt.strftime('%Y-%m-%d').tolist(),
        'corrected_test':test.loc[~tb&tc,'fecha'].dt.strftime('%Y-%m-%d').tolist(),
        'created_test':test.loc[tb&~tc,'fecha'].dt.strftime('%Y-%m-%d').tolist(),
    }


def main():
    inventory=exp.download_complementary_sources()
    monthly,local,bonds,foreign=exp.build_monthly()

    operational,chosen,failed=exp.prepare_daily(monthly.copy(),local,bonds,foreign)
    variants={
        'base7':exp.BASE,
        'plus_local':exp.BASE+['x_local_specific'],
        'plus_foreign':exp.BASE+['x_foreign_specific'],
        'plus_bonds':exp.BASE+['x_bond_specific'],
        'plus_forward':exp.BASE+['x_forward_specific'],
        'plus_proxy':exp.BASE+['x_specific_proxy'],
        'plus_specific_all':exp.BASE+['x_local_specific','x_foreign_specific','x_bond_specific','x_forward_specific'],
        'replace_usd_netfx':[x for x in exp.BASE if x!='ret_USD_PEN']+['x_net_fx'],
    }
    predictions={name:exp.walk(operational,features) for name,features in variants.items()}
    paired=join_predictions(predictions)
    scores,common=fair_scores(paired,list(variants))

    def key(name: str):
        m=scores[name]['validation']
        return (m.get('hits',-1),-m.get('mae_pp',999),-m.get('hard_reversals',999))
    selected=max(variants,key=key)
    comparisons={name:comparison_from_common(common,name) for name in variants if name!='base7'}

    # Diagnóstico oráculo: usa la cartera del cierre del mismo mes desde el primer día.
    # Tiene fuga deliberada y no puede ser seleccionado ni desplegado.
    oracle_monthly=monthly.copy()
    oracle_monthly['report_month']=pd.to_datetime(oracle_monthly['report_month'])
    oracle_monthly['available_date']=oracle_monthly['report_month'].dt.to_period('M').dt.start_time
    oracle,_,_=exp.prepare_daily(oracle_monthly,local,bonds,foreign)
    oracle=oracle[oracle['fecha']<=pd.Timestamp('2026-02-28')].copy()
    oracle=oracle[oracle['fecha'].dt.to_period('M')==pd.to_datetime(oracle['report_month']).dt.to_period('M')]
    oracle_variants={
        'oracle_base7':exp.BASE,
        'oracle_plus_local':exp.BASE+['x_local_specific'],
        'oracle_plus_proxy':exp.BASE+['x_specific_proxy'],
        'oracle_plus_specific_all':exp.BASE+['x_local_specific','x_foreign_specific','x_bond_specific','x_forward_specific'],
    }
    oracle_predictions={name:exp.walk(oracle,features) for name,features in oracle_variants.items()}
    oracle_paired=join_predictions(oracle_predictions)
    oracle_scores,oracle_common=fair_scores(oracle_paired,list(oracle_variants))

    target_dates=['2026-03-24','2026-03-27','2026-04-09','2026-06-01','2026-06-16','2026-06-18','2026-06-26','2026-07-02','2026-07-20']
    targets=paired[paired['fecha'].dt.strftime('%Y-%m-%d').isin(target_dates)].copy()
    coverage={
        'mapped_isins':chosen,
        'failed_isins':failed,
        'mean_daily_mapped_coverage':float(operational['mapped_coverage'].mean()),
        'latest_mapped_coverage':float(operational['mapped_coverage'].dropna().iloc[-1]),
    }
    result={
        'method':{
            'window':exp.WINDOW,'threshold':exp.THRESHOLD,'epsilon':exp.EPSILON,'alpha':exp.ALPHA,
            'operational_lag':'month end + 4 months + 15 days',
            'fair_comparison':'all models restricted to identical 173 prediction dates',
            'selection':'validation only; oracle excluded',
            'oracle':'same-month month-end holdings applied from month start; diagnostic with future leakage',
        },
        'selected_operational':selected,
        'scores_common':scores,
        'comparisons_common':comparisons,
        'oracle_scores_common':oracle_scores,
        'coverage':coverage,
        'source_inventory':inventory,
    }
    (OUT/'results.json').write_text(json.dumps(result,indent=2,ensure_ascii=False,default=str),encoding='utf-8')
    monthly.to_csv(OUT/'monthly_specific_exposures.csv',index=False)
    local.to_csv(OUT/'local_holdings.csv',index=False)
    bonds.to_csv(OUT/'bond_holdings.csv',index=False)
    foreign.to_csv(OUT/'foreign_holdings.csv',index=False)
    operational.to_csv(OUT/'daily_specific_features.csv',index=False)
    paired.to_csv(OUT/'paired_predictions.csv',index=False)
    common.to_csv(OUT/'common_predictions.csv',index=False)
    targets.to_csv(OUT/'target_dates.csv',index=False)
    oracle_paired.to_csv(OUT/'oracle_paired_predictions.csv',index=False)
    oracle_common.to_csv(OUT/'oracle_common_predictions.csv',index=False)
    (OUT/'source_inventory.json').write_text(json.dumps(inventory,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps(result,indent=2,ensure_ascii=False,default=str))
    print('\nTARGET DATES\n',targets.to_string(index=False))

if __name__=='__main__':
    main()
