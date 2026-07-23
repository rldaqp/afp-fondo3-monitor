from __future__ import annotations

import importlib.util
import io
import json
import re
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "scripts" / "build_rolling90_pages.py"

spec = importlib.util.spec_from_file_location("rolling90_engine", ENGINE)
if spec is None or spec.loader is None:
    raise RuntimeError(f"No se pudo cargar {ENGINE}")
engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)

_original_download_yahoo = engine.download_yahoo
_original_download_sbs = engine.download_sbs
_original_load_bcrp = engine.load_bcrp


def _get_text(url: str, attempts: int = 3) -> str:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            response = requests.get(url, headers=engine.HEADERS, timeout=45)
            response.raise_for_status()
            text = response.text.strip()
            if text:
                return text
        except Exception as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(1.0 + attempt)
    raise RuntimeError(
        f"No respondió {url}: {type(last_error).__name__}: {last_error}"
    )


def _parse_sbs_daily_blocks() -> pd.DataFrame:
    """Lee cada tabla diaria SBS que contenga una sola fecha y la fila PROFUTURO."""
    response = requests.get(engine.SBS_DAILY, headers=engine.HEADERS, timeout=45)
    response.raise_for_status()
    soup = BeautifulSoup(response.content, "lxml")
    rows: list[dict[str, object]] = []

    for table in soup.find_all("table"):
        table_text = " ".join(table.stripped_strings)
        date_matches = list(dict.fromkeys(re.findall(r"\d{2}/\d{2}/\d{4}", table_text)))
        if len(date_matches) != 1:
            continue

        fecha = pd.to_datetime(date_matches[0], format="%d/%m/%Y")
        valor = None
        for tr in table.find_all("tr"):
            if tr.find_parent("table") is not table:
                continue
            cells = tr.find_all(["th", "td"], recursive=False)
            if not cells:
                continue
            texts = [" ".join(cell.get_text(" ", strip=True).split()) for cell in cells]
            if texts and engine.norm(texts[0]) == "profuturo" and len(texts) >= 10:
                valor = engine.parse_num(texts[9])
                break

        if valor is not None:
            rows.append({"fecha": fecha, "valor_cuota": float(valor)})

    if not rows:
        raise RuntimeError("No se pudieron extraer tablas diarias SBS de Profuturo Fondo 3")

    daily = pd.DataFrame(rows)
    daily["fecha"] = pd.to_datetime(daily["fecha"], errors="coerce")
    daily["valor_cuota"] = pd.to_numeric(daily["valor_cuota"], errors="coerce")
    return (
        daily.dropna()
        .sort_values("fecha")
        .drop_duplicates("fecha", keep="last")
        .reset_index(drop=True)
    )


def download_sbs_resilient() -> tuple[pd.DataFrame, list[str]]:
    base, warnings = _original_download_sbs()
    try:
        daily = _parse_sbs_daily_blocks()
        combined = pd.concat([base, daily], ignore_index=True)
        combined["fecha"] = pd.to_datetime(combined["fecha"], errors="coerce")
        combined["valor_cuota"] = pd.to_numeric(combined["valor_cuota"], errors="coerce")
        combined = (
            combined.dropna()
            .sort_values("fecha")
            .drop_duplicates("fecha", keep="last")
            .reset_index(drop=True)
        )
        print(
            "SBS diaria incorporada hasta "
            f"{combined['fecha'].max():%Y-%m-%d} · "
            f"VC {combined.iloc[-1]['valor_cuota']:.7f}"
        )
        return combined, warnings
    except Exception as exc:
        warnings.append(f"SBS diaria por tablas: {type(exc).__name__}: {exc}")
        return base, warnings


def _download_stooq_ticker(ticker: str) -> pd.DataFrame:
    symbols = {
        "SPY": "spy.us",
        "NEM": "nem.us",
        "FCX": "fcx.us",
        "EPU": "epu.us",
        "MCHI": "mchi.us",
    }
    symbol = symbols[ticker]
    start = engine.START.strftime("%Y%m%d")
    end = pd.Timestamp.now(tz="America/Lima").strftime("%Y%m%d")
    url = f"https://stooq.com/q/d/l/?s={symbol}&d1={start}&d2={end}&i=d"
    text = _get_text(url)
    frame = pd.read_csv(io.StringIO(text))
    if frame.empty or "Date" not in frame.columns or "Close" not in frame.columns:
        raise RuntimeError(f"Stooq devolvió datos inválidos para {ticker}")
    out = frame[["Date", "Close"]].copy()
    out.columns = ["fecha", ticker]
    out["fecha"] = pd.to_datetime(out["fecha"], errors="coerce")
    out[ticker] = pd.to_numeric(out[ticker], errors="coerce")
    return (
        out.dropna()
        .sort_values("fecha")
        .drop_duplicates("fecha", keep="last")
        .reset_index(drop=True)
    )


def _download_stooq() -> pd.DataFrame:
    frames = [_download_stooq_ticker(ticker) for ticker in engine.ASSETS]
    market = frames[0]
    for frame in frames[1:]:
        market = market.merge(frame, on="fecha", how="outer")
    return market.sort_values("fecha").drop_duplicates("fecha", keep="last")


def download_market_resilient() -> pd.DataFrame:
    try:
        market = _original_download_yahoo()
        print("Mercado descargado desde Yahoo Finance")
        return market
    except Exception as yahoo_error:
        print(
            "Yahoo Finance no respondió; se usa Stooq como respaldo: "
            f"{type(yahoo_error).__name__}: {yahoo_error}"
        )
        market = _download_stooq()
        print("Mercado descargado desde Stooq")
        return market


def _download_yahoo_usd_pen() -> pd.DataFrame:
    """Descarga PEN=X. Se usa solo para completar fechas ausentes en BCRP."""
    end = (pd.Timestamp.now(tz="America/Lima") + pd.Timedelta(days=2)).strftime("%Y-%m-%d")
    raw = engine.yf.download(
        "PEN=X",
        start=engine.START.strftime("%Y-%m-%d"),
        end=end,
        auto_adjust=False,
        actions=False,
        progress=False,
        threads=False,
    )
    if raw.empty:
        raise RuntimeError("Yahoo Finance no devolvió PEN=X")

    if isinstance(raw.columns, pd.MultiIndex):
        close = None
        for key in [("Close", "PEN=X"), ("PEN=X", "Close")]:
            if key in raw.columns:
                close = pd.to_numeric(raw[key], errors="coerce")
                break
        if close is None and "Close" in raw.columns.get_level_values(0):
            block = raw.xs("Close", axis=1, level=0)
            close = pd.to_numeric(block.iloc[:, 0], errors="coerce")
    else:
        close = pd.to_numeric(raw["Close"], errors="coerce") if "Close" in raw.columns else None

    if close is None:
        raise RuntimeError("Yahoo Finance no devolvió cierre para PEN=X")

    index = pd.to_datetime(raw.index)
    if getattr(index, "tz", None) is not None:
        index = index.tz_localize(None)
    out = pd.DataFrame({"fecha": index, "USD_PEN_YAHOO": np.asarray(close, dtype=float)})
    return out.dropna().sort_values("fecha").drop_duplicates("fecha", keep="last")


def load_fx_resilient() -> pd.DataFrame:
    """BCRP es la fuente principal; Yahoo PEN=X completa solo fechas faltantes."""
    bcrp_error = None
    yahoo_error = None
    try:
        bcrp = _original_load_bcrp().rename(columns={"USD_PEN": "USD_PEN_BCRP"})
    except Exception as exc:
        bcrp_error = exc
        bcrp = pd.DataFrame(columns=["fecha", "USD_PEN_BCRP"])

    try:
        yahoo = _download_yahoo_usd_pen()
    except Exception as exc:
        yahoo_error = exc
        yahoo = pd.DataFrame(columns=["fecha", "USD_PEN_YAHOO"])

    if bcrp.empty and yahoo.empty:
        raise RuntimeError(
            "No se pudo obtener USD/PEN ni de BCRP ni de Yahoo PEN=X. "
            f"BCRP={bcrp_error}; Yahoo={yahoo_error}"
        )

    if bcrp.empty:
        merged = yahoo.copy()
        merged["USD_PEN"] = merged["USD_PEN_YAHOO"]
    elif yahoo.empty:
        merged = bcrp.copy()
        merged["USD_PEN"] = merged["USD_PEN_BCRP"]
    else:
        merged = bcrp.merge(yahoo, on="fecha", how="outer")
        merged["USD_PEN"] = merged["USD_PEN_BCRP"].combine_first(merged["USD_PEN_YAHOO"])

    latest_bcrp = bcrp["fecha"].max() if not bcrp.empty else None
    latest_yahoo = yahoo["fecha"].max() if not yahoo.empty else None
    latest_final = merged.loc[merged["USD_PEN"].notna(), "fecha"].max()
    print(
        "USD/PEN: prioridad BCRP, Yahoo PEN=X como respaldo · "
        f"BCRP={latest_bcrp} · Yahoo={latest_yahoo} · final={latest_final}"
    )
    return (
        merged[["fecha", "USD_PEN"]]
        .dropna()
        .sort_values("fecha")
        .drop_duplicates("fecha", keep="last")
        .reset_index(drop=True)
    )


def _publish_rich_history() -> None:
    """Publica histórico de señales/retornos y mejora los dos gráficos del celular."""
    hist_path = ROOT / "data" / "rolling90" / "historical_predictions.csv"
    pending_path = ROOT / "data" / "rolling90" / "pending_predictions.csv"
    sbs_path = ROOT / "data" / "rolling90" / "sbs_profuturo_f3.csv"
    public_data = ROOT / "public" / "data"
    public_data.mkdir(parents=True, exist_ok=True)

    hist = pd.read_csv(hist_path) if hist_path.exists() else pd.DataFrame()
    pending = pd.read_csv(pending_path) if pending_path.exists() else pd.DataFrame()
    sbs = pd.read_csv(sbs_path) if sbs_path.exists() else pd.DataFrame()

    records: list[dict[str, object]] = []
    if not hist.empty and not sbs.empty:
        hist["fecha"] = pd.to_datetime(hist["fecha"], errors="coerce")
        sbs["fecha"] = pd.to_datetime(sbs["fecha"], errors="coerce")
        sbs["valor_cuota"] = pd.to_numeric(sbs["valor_cuota"], errors="coerce")
        sbs = sbs.sort_values("fecha").drop_duplicates("fecha", keep="last")
        sbs["vc_previo"] = sbs["valor_cuota"].shift(1)
        h = hist.merge(sbs[["fecha", "vc_previo"]], on="fecha", how="left")
        h["ret_estimado"] = pd.to_numeric(h["ret_estimado"], errors="coerce")
        h["valor_cuota"] = pd.to_numeric(h["valor_cuota"], errors="coerce")
        h["vc_estimado"] = h["vc_previo"] * (1.0 + h["ret_estimado"])
        for _, row in h.dropna(subset=["fecha", "ret_estimado"]).iterrows():
            records.append({
                "fecha": row["fecha"].strftime("%Y-%m-%d"),
                "ret_estimado": float(row["ret_estimado"]),
                "senal": str(row["senal"]),
                "vc_real": None if pd.isna(row["valor_cuota"]) else float(row["valor_cuota"]),
                "vc_estimado": None if pd.isna(row["vc_estimado"]) else float(row["vc_estimado"]),
                "tipo": "HISTORICO",
            })

    if not pending.empty:
        pending["fecha"] = pd.to_datetime(pending["fecha"], errors="coerce")
        for _, row in pending.dropna(subset=["fecha", "ret_estimado"]).iterrows():
            records.append({
                "fecha": row["fecha"].strftime("%Y-%m-%d"),
                "ret_estimado": float(row["ret_estimado"]),
                "senal": str(row["senal"]),
                "vc_real": None,
                "vc_estimado": float(row["valor_cuota_estimado"]),
                "tipo": "PENDIENTE",
            })

    records.sort(key=lambda x: str(x["fecha"]))
    (public_data / "signals.json").write_text(
        json.dumps(records, ensure_ascii=False), encoding="utf-8"
    )

    latest_path = public_data / "latest.json"
    if latest_path.exists():
        latest = json.loads(latest_path.read_text(encoding="utf-8"))
        latest.setdefault("sources", {})["fx"] = "BCRP; Yahoo PEN=X solo para fechas faltantes"
        latest["sources"]["market"] = "Yahoo Finance (Stooq respaldo) + USD/PEN BCRP/Yahoo"
        latest_path.write_text(json.dumps(latest, ensure_ascii=False, indent=2), encoding="utf-8")

    html_path = ROOT / "public" / "index.html"
    html = html_path.read_text(encoding="utf-8")
    controls = (
        '<section class="panel"><div class="chart-controls">'
        '<button id="vc90" class="primary">Últimos 90 días</button>'
        '<button id="vcAll">Todo</button></div><div id="vcChart" class="chart"></div></section>'
    )
    html = html.replace(
        '<section class="panel"><div id="vcChart" class="chart"></div></section>',
        controls,
        1,
    )
    html = html.replace(
        "</style>",
        ".chart-controls{display:flex;gap:8px;margin-bottom:8px}.chart-controls button{border:1px solid #334155;background:#132238;color:#fff;border-radius:9px;padding:8px 12px;font-weight:650}.chart-controls button.primary{background:#2563eb}</style>",
        1,
    )

    extra_js = r'''
<script>
(function(){
  let richSignals=[], allSeries=[], vcMode='90';
  const signalColor=s=>s==='SUBE'?'#4ade80':s==='BAJA'?'#f87171':'#fbbf24';
  function cutoff90(items){
    if(!items.length) return items;
    const max=new Date(items.map(x=>x.fecha).sort().at(-1)+'T00:00:00');
    const min=new Date(max); min.setDate(min.getDate()-90);
    return items.filter(x=>new Date(x.fecha+'T00:00:00')>=min);
  }
  function renderVC(){
    let official=allSeries.filter(x=>x.fuente==='SBS OFICIAL');
    let estimated=richSignals.filter(x=>x.vc_estimado!=null);
    if(vcMode==='90'){ official=cutoff90(official); estimated=cutoff90(estimated); }
    Plotly.react('vcChart',[
      {x:official.map(x=>x.fecha),y:official.map(x=>x.vc),mode:'lines+markers',name:'VC SBS real'},
      {x:estimated.map(x=>x.fecha),y:estimated.map(x=>x.vc_estimado),mode:'lines+markers',name:'VC estimado OLS',customdata:estimated.map(x=>x.senal),hovertemplate:'<b>%{x}</b><br>VC estimado: %{y:.7f}<br>Señal: %{customdata}<extra></extra>'}
    ],{title:vcMode==='90'?'VC real vs estimado · últimos 90 días':'VC real vs estimado · todo el historial',paper_bgcolor:'#0f1b2d',plot_bgcolor:'#0f1b2d',font:{color:'#fff'},legend:{orientation:'h'}},{responsive:true});
    document.getElementById('vc90').classList.toggle('primary',vcMode==='90');
    document.getElementById('vcAll').classList.toggle('primary',vcMode==='all');
  }
  function renderSignals(){
    const points=richSignals.filter(x=>x.ret_estimado!=null).slice(-90);
    Plotly.react('signalChart',[{
      x:points.map(x=>x.fecha),y:points.map(x=>x.ret_estimado*100),mode:'lines+markers',name:'Retorno OLS',
      marker:{color:points.map(x=>signalColor(x.senal)),size:8},customdata:points.map(x=>x.senal),
      hovertemplate:'<b>%{x}</b><br>Retorno estimado: %{y:+.3f}%<br>Señal: %{customdata}<extra></extra>'
    }],{title:'Retornos estimados y señal · últimas 90 observaciones',paper_bgcolor:'#0f1b2d',plot_bgcolor:'#0f1b2d',font:{color:'#fff'},shapes:[{type:'line',xref:'paper',x0:0,x1:1,y0:.1,y1:.1,line:{dash:'dot'}},{type:'line',xref:'paper',x0:0,x1:1,y0:-.1,y1:-.1,line:{dash:'dot'}}]},{responsive:true});
  }
  Promise.all([
    fetch('data/signals.json',{cache:'no-store'}).then(r=>r.json()),
    fetch('data/series.json',{cache:'no-store'}).then(r=>r.json())
  ]).then(([sig,ser])=>{
    richSignals=sig.sort((a,b)=>a.fecha.localeCompare(b.fecha));
    allSeries=ser.sort((a,b)=>a.fecha.localeCompare(b.fecha));
    renderVC(); renderSignals();
    document.getElementById('vc90').onclick=()=>{vcMode='90';renderVC()};
    document.getElementById('vcAll').onclick=()=>{vcMode='all';renderVC()};
  });
})();
</script>
'''
    html = html.replace("</body>", extra_js + "</body>", 1)
    html_path.write_text(html, encoding="utf-8")


engine.download_sbs = download_sbs_resilient
engine.download_yahoo = download_market_resilient
engine.load_bcrp = load_fx_resilient
engine.main()
_publish_rich_history()
