from __future__ import annotations

import pandas as pd
import requests
from pathlib import Path

URL = 'https://intranet2.sbs.gob.pe/estadistica/financiera/2026/Junio/FP-1356-jn2026.XLS'
OUT = Path('FP-1356-jn2026.XLS')

r = requests.get(URL, timeout=60, headers={'User-Agent': 'Mozilla/5.0'})
r.raise_for_status()
OUT.write_bytes(r.content)
print('downloaded', len(r.content))

book = pd.ExcelFile(OUT, engine='xlrd')
print('sheets', book.sheet_names)
for name in book.sheet_names:
    df = pd.read_excel(OUT, sheet_name=name, header=None, engine='xlrd')
    print('\nSHEET', name, 'shape', df.shape)
    with pd.option_context('display.max_rows', 120, 'display.max_columns', 40, 'display.width', 300):
        print(df.iloc[:120, :40].to_string(index=True, header=True))
