from __future__ import annotations

from pathlib import Path
import pandas as pd
import requests

url = 'https://intranet2.sbs.gob.pe/estadistica/financiera/2025/Enero/FP-1356-en2025.XLS'
path = Path('FP-1356-en2025.XLS')
r = requests.get(url, timeout=60, headers={'User-Agent':'Mozilla/5.0'})
r.raise_for_status()
path.write_bytes(r.content)
df = pd.read_excel(path, sheet_name='Fondo3xIntru', header=None, engine='xlrd')
print('shape', df.shape)
with pd.option_context('display.max_rows', 120, 'display.max_columns', 30, 'display.width', 400):
    print(df.iloc[:120, :30].to_string(index=True, header=True))
