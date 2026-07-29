from __future__ import annotations

from pathlib import Path
import json
import requests
import pandas as pd
import pdfplumber

OUT = Path('research_outputs/specific_portfolio_inspect')
RAW = OUT / 'raw'
RAW.mkdir(parents=True, exist_ok=True)
HEADERS = {'User-Agent': 'Mozilla/5.0'}

SOURCES = {
    'CA-0001-en2026.XLS': 'https://intranet2.sbs.gob.pe/estadistica/spp/2026/Enero/CA-0001-en2026.XLS',
    'CA-0001-di2025.XLS': 'https://intranet2.sbs.gob.pe/estadistica/spp/2025/Diciembre/CA-0001-di2025.XLS',
    'FP-1357-jn2026.XLS': 'https://intranet2.sbs.gob.pe/estadistica/financiera/2026/Junio/FP-1357-jn2026.XLS',
    'FP-1306-jn2026.XLS': 'https://intranet2.sbs.gob.pe/estadistica/financiera/2026/Junio/FP-1306-jn2026.XLS',
    'FP-1358-jn2026.XLS': 'https://intranet2.sbs.gob.pe/estadistica/financiera/2026/Junio/FP-1358-jn2026.XLS',
}
for number in ['4','5','6','7','8','10','11','12','13']:
    SOURCES[f'profuturo-2026-02-{number}.pdf'] = (
        'https://cdn.aglty.io/scotiabank-peru/Profuturo/PDF/personas/'
        f'reporte-cartera-inversiones/2026/febrero/{number}.pdf'
    )

summary = []
for name, url in SOURCES.items():
    path = RAW / name
    try:
        response = requests.get(url, timeout=90, headers=HEADERS)
        response.raise_for_status()
        path.write_bytes(response.content)
        row = {'name': name, 'url': url, 'size': len(response.content), 'status': 'ok'}
        if name.lower().endswith('.xls'):
            engine = 'openpyxl' if response.content[:2] == b'PK' else 'xlrd'
            book = pd.ExcelFile(path, engine=engine)
            row['engine'] = engine
            row['sheets'] = book.sheet_names
            row['sheet_shapes'] = {}
            for sheet in book.sheet_names[:12]:
                frame = pd.read_excel(path, sheet_name=sheet, header=None, engine=engine)
                row['sheet_shapes'][sheet] = list(frame.shape)
                print(f'\n===== {name} :: {sheet} {frame.shape} engine={engine} =====')
                print(frame.iloc[:35, :22].to_string(index=True, header=True))
        else:
            with pdfplumber.open(path) as pdf:
                row['pages'] = len(pdf.pages)
                print(f'\n===== {name} pages={len(pdf.pages)} =====')
                for i, page in enumerate(pdf.pages[:5]):
                    text = page.extract_text() or ''
                    print(f'--- page {i+1} ---')
                    print(text[:18000])
        summary.append(row)
    except Exception as exc:
        summary.append({'name': name, 'url': url, 'status': 'error', 'error': repr(exc)})
        print(f'ERROR {name}: {exc!r}')

(OUT / 'source_inventory.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding='utf-8')
