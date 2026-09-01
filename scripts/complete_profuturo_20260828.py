from __future__ import annotations

import csv
import json
from pathlib import Path

JSON_PATH = Path('public/data/fixed_models_2026.json')
CSV_PATH = Path('public/data/fixed_models_2026.csv')
FACTORS = ['SPY', 'EEM', 'MCHI', 'QQQ', 'SPBLSCUP']

# Cierres verificados del 28/08/2026.
# SPY, EEM y QQQ: Yahoo Finance; MCHI: iShares/mercado; SPBLSCUP ya estaba
# registrado en la serie del proyecto.
CLOSES_20260828 = {
    'SPY': 769.35,
    'EEM': 67.14,
    'MCHI': 55.23,
    'QQQ': 716.43,
    'SPBLSCUP': 454.70,
}
SOURCE_20260828 = 'CIERRES VERIFICADOS 28/08 · Yahoo Finance/iShares + Google Finance SPBLSCUP'


def level_value(prices: dict[str, float], coeff: dict[str, float]) -> float:
    return float(coeff['intercept']) + sum(float(coeff[k]) * float(prices[k]) for k in FACTORS)


def return_value(cur: dict[str, float], prev: dict[str, float], coeff: dict[str, float]) -> float:
    out = float(coeff['intercept'])
    for k in FACTORS:
        out += float(coeff[k]) * (float(cur[k]) / float(prev[k]) - 1.0)
    return out


def prices(row: dict) -> dict[str, float]:
    return {k: float(row[k]) for k in FACTORS}


def return_base(prev: dict) -> float:
    if prev.get('vc_sbs') is not None:
        return float(prev['vc_sbs'])
    if prev.get('vc_retornos') is not None:
        return float(prev['vc_retornos'])
    raise RuntimeError(f"No existe base de retorno para {prev.get('fecha')}")


def patch_json() -> dict:
    data = json.loads(JSON_PATH.read_text(encoding='utf-8'))
    rows = data['rows']
    by_date = {r['fecha']: r for r in rows}

    for d in ('2026-08-27', '2026-08-28', '2026-08-31'):
        if d not in by_date:
            raise RuntimeError(f'Falta la fila {d} en fixed_models_2026.json')

    level_coeff = data['models']['niveles']['coefficients']
    return_coeff = data['models']['retornos']['coefficients']

    r27 = by_date['2026-08-27']
    r28 = by_date['2026-08-28']
    r31 = by_date['2026-08-31']

    r28.update(CLOSES_20260828)
    r28['source'] = SOURCE_20260828
    r28['vc_niveles'] = level_value(CLOSES_20260828, level_coeff)
    r28['ret_vc_estimado'] = return_value(CLOSES_20260828, prices(r27), return_coeff)
    r28['vc_retornos'] = return_base(r27) * (1.0 + r28['ret_vc_estimado'])
    r28['error_niveles_pct'] = None
    r28['error_retornos_pct'] = None

    # El 31/08 ya tenía los factores completos. Se reconstruye el modelo de retornos
    # encadenándolo desde el 28/08, de acuerdo con la regla vigente cuando aún no hay SBS.
    r31['ret_vc_estimado'] = return_value(prices(r31), CLOSES_20260828, return_coeff)
    r31['vc_retornos'] = return_base(r28) * (1.0 + r31['ret_vc_estimado'])
    r31['error_retornos_pct'] = None

    latest = data.get('latest', {})
    if latest.get('market_date') == '2026-08-31':
        latest['vc_niveles'] = r31['vc_niveles']
        latest['ret_vc_estimado'] = r31['ret_vc_estimado']
        latest['vc_retornos'] = r31['vc_retornos']

    JSON_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return data


def patch_csv(data: dict) -> None:
    if not CSV_PATH.exists():
        return
    rows = data['rows']
    fieldnames = [
        'fecha', 'fase', 'SPY', 'EEM', 'MCHI', 'QQQ', 'SPBLSCUP', 'source',
        'vc_sbs', 'vc_niveles', 'ret_vc_estimado', 'vc_retornos',
        'error_niveles_pct', 'error_retornos_pct'
    ]
    with CSV_PATH.open('w', encoding='utf-8', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction='ignore')
        w.writeheader()
        for row in rows:
            w.writerow(row)


def main() -> None:
    data = patch_json()
    patch_csv(data)
    by_date = {r['fecha']: r for r in data['rows']}
    r28 = by_date['2026-08-28']
    r31 = by_date['2026-08-31']
    print(
        'Profuturo 28/08 completado: '
        f"VC niveles={r28['vc_niveles']:.7f}, "
        f"retorno={r28['ret_vc_estimado']*100:.4f}%, "
        f"VC retornos={r28['vc_retornos']:.7f}."
    )
    print(
        'Profuturo 31/08 encadenado: '
        f"retorno={r31['ret_vc_estimado']*100:.4f}%, "
        f"VC retornos={r31['vc_retornos']:.7f}."
    )


if __name__ == '__main__':
    main()
