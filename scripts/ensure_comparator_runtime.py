from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]
HTML=ROOT/'public'/'comparador-fondos'/'index.html'
TAG='<script src="comparator_runtime_v2.js?rev=CMPV2-20260829"></script>'

def main():
    text=HTML.read_text(encoding='utf-8')
    if 'Fondo 3 · Hábitat vs Profuturo' not in text:
        raise RuntimeError('No se reconoció el comparador')
    text=re.sub(r'\n?<script src="comparator_runtime_v2\.js\?rev=[^"]+"></script>','',text)
    if '</body>' not in text:
        raise RuntimeError('HTML sin </body>')
    text=text.replace('</body>',TAG+'\n</body>',1)
    HTML.write_text(text,encoding='utf-8')
    check=HTML.read_text(encoding='utf-8')
    assert check.count('comparator_runtime_v2.js')==1
    assert (ROOT/'public'/'comparador-fondos'/'comparator_runtime_v2.js').is_file()
    print('Runtime comparador v2 instalado')

if __name__=='__main__':
    main()
