from __future__ import annotations
import json
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'public' / 'data' / 'dual_rolling30_monitor.json'
OUT = ROOT / 'data' / 'analysis' / 'tmp_ab_r2_result.json'

def metric(model):
    rows = [r for r in model.get('history_one_step', []) if r.get('actual_vc') is not None and r.get('vc_estimated') is not None]
    rows = rows[-30:]
    y = np.array([float(r['actual_vc']) for r in rows], dtype=float)
    p = np.array([float(r['vc_estimated']) for r in rows], dtype=float)
    corr = float(np.corrcoef(p, y)[0,1])
    return {
        'n': len(rows),
        'start': rows[0]['fecha'],
        'end': rows[-1]['fecha'],
        'corr_vc': corr,
        'r2_corr': corr*corr,
    }

def main():
    dual = json.loads(SRC.read_text(encoding='utf-8'))
    result = {
        'source_generated_at_lima': dual.get('generated_at_lima'),
        'latest_sbs': dual.get('latest_sbs'),
        'method': 'R2 = Pearson correlation squared between vc_estimated and actual_vc over each current model latest 30 completed history_one_step pairs.',
        'modelo_a_qqq': metric(dual['models']['qqq']),
        'modelo_b_new_tickers': metric(dual['models']['new_tickers']),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
