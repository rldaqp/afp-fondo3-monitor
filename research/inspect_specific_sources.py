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
for number in ['4','5','8','11','12','13']:
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
            book = pd.ExcelFile(path, engine='xlrd')
            row['sheets'] = book.sheet_names
            row['sheet_shapes'] = {}
            for sheet in book.sheet_names[:8]:
                frame = pd.read_excel(path, sheet_name=sheet, header=None, engine='xlrd')
                row['sheet_shapes'][sheet] = list(frame.shape)
                print(f'\n===== {name} :: {sheet} {frame.shape} =====')
                print(frame.iloc[:25, :18].to_string(index=True, header=True))
        else:
            with pdfplumber.open(path) as pdf:
                row['pages'] = len(pdf.pages)
                print(f'\n===== {name} pages={len(pdf.pages)} =====')
                for i, page in enumerate(pdf.pages[:3]):
                    text = page.extract_text() or ''
                    print(f'--- page {i+1} ---')
                    print(text[:12000])
        summary.append(row)
    except Exception as exc:
        summary.append({'name': name, 'url': url, 'status': 'error', 'error': repr(exc)})
        print(f'ERROR {name}: {exc!r}')

(OUT / 'source_inventory.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding='utf-8')
