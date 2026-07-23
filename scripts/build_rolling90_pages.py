from __future__ import annotations

import io
import json
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests
import yfinance as yf
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "rolling90"
PUBLIC = ROOT / "public"
PUBLIC_DATA = PUBLIC / "data"
DATA.mkdir(parents=True, exist_ok=True)
PUBLIC_DATA.mkdir(parents=True, exist_ok=True)

ASSETS = ["SPY", "NEM", "FCX", "EPU", "MCHI"]
FEATURES = [f"ret_{x}" for x in ASSETS] + ["ret_USD_PEN"]
WINDOW = 90
THRESHOLD = 0.001
START = pd.Timestamp("2024-12-31")
LIMA = ZoneInfo("America/Lima")
EXCLUDED_RETURN_DATES = {pd.Timestamp("2026-07-06")}

SBS_INDEX = "https://www.sbs.gob.pe/app/stats/EstadisticaSistemaFinancieroResultados.asp?c=FP-1359"
SBS_DAILY = "https://www.sbs.gob.pe/app/spp/variablesSPP_net/PagSS/variables_spp.aspx"
BCRP = "https://estadisticas.bcrp.gob.pe/estadisticas/series/api/PD04646PD/json"
HEADERS = {"User-Agent": "Mozilla/5.0 AFP-Fondo3-GitHubActions"}


def norm(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(text.lower().split())


def parse_num(value: object) -> float | None:
    number = pd.to_numeric(
        str(value).replace("\xa0", "").replace(" ", "").replace(",", ""),
        errors="coerce",
    )
    return None if pd.isna(number) else float(number)


def parse_bcrp_date(value: object):
    match = re.search(
        r"(\d{1,2})[.\-/ ]+([A-Za-zÁÉÍÓÚáéíóú]{3,5})[.\-/ ]+(\d{2,4})",
        str(value),
    )
    if not match:
        return pd.NaT
    day, month_text, year = match.groups()
    month = {
        "ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
        "jul": 7, "ago": 8, "set": 9, "sep": 9, "sept": 9,
        "oct": 10, "nov": 11, "dic": 12,
    }.get(norm(month_text))
    if not month:
        return pd.NaT
    year_number = int(year) + (2000 if int(year) < 100 else 0)
    try:
        return pd.Timestamp(year_number, month, int(day))
    except ValueError:
        return pd.NaT


def read_saved(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    frame = pd.read_csv(path)
    if "fecha" in frame.columns:
        frame["fecha"] = pd.to_datetime(frame["fecha"], errors="coerce")
    return frame


def save_csv(frame: pd.DataFrame, path: Path) -> None:
    out = frame.copy()
    for col in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[col]):
            out[col] = out[col].dt.strftime("%Y-%m-%d")
    out.to_csv(path, index=False, encoding="utf-8")


def download_sbs() -> tuple[pd.DataFrame, list[str]]:
    session = requests.Session()
    session.headers.update(HEADERS)
    frames: list[pd.DataFrame] = []
    warnings: list[str] = []

    try:
        page = session.get(SBS_INDEX, timeout=45)
        page.raise_for_status()
        soup = BeautifulSoup(page.content, "lxml")
        links = []
        for anchor in soup.find_all("a", href=True):
            url = urljoin(SBS_INDEX, anchor["href"])
            if "FP-1359" in url.upper() and url.lower().endswith(".xls") and re.search(r"202[4-9]", url):
                links.append(url)
        for url in sorted(set(links)):
            try:
                response = session.get(url, timeout=60)
                response.raise_for_status()
                raw = pd.read_excel(
                    io.BytesIO(response.content),
                    sheet_name="VC-Diario-Fondo3",
                    header=None,
                    engine="xlrd",
                )
                header_row = next(
                    i for i in range(min(25, len(raw)))
                    if "dia" in [norm(v) for v in raw.iloc[i]]
                    and "profuturo" in [norm(v) for v in raw.iloc[i]]
                )
                header = [norm(v) for v in raw.iloc[header_row]]
                block = raw.iloc[
                    header_row + 1:,
                    [header.index("dia"), header.index("profuturo")],
                ].copy()
                block.columns = ["fecha", "valor_cuota"]
                block["fecha"] = pd.to_datetime(block["fecha"], errors="coerce")
                block["valor_cuota"] = pd.to_numeric(block["valor_cuota"], errors="coerce")
                frames.append(block.dropna())
            except Exception as exc:
                warnings.append(f"SBS XLS: {type(exc).__name__}")
    except Exception as exc:
        warnings.append(f"SBS índice: {type(exc).__name__}: {exc}")

    online = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=["fecha", "valor_cuota"])

    try:
        page = session.get(SBS_DAILY, timeout=40)
        page.raise_for_status()
        soup = BeautifulSoup(page.content, "lxml")
        dates = []
        values = []
        for node in soup.find_all(string=True):
            text = " ".join(str(node).split())
            if "informacion al" in norm(text):
                found = re.search(r"\d{2}/\d{2}/\d{4}", text)
                if found:
                    dates.append(pd.to_datetime(found.group(), format="%d/%m/%Y"))
        for table in soup.find_all("table"):
            for row in table.find_all("tr"):
                cells = row.find_all(["th", "td"], recursive=False)
                texts = [" ".join(cell.get_text(" ", strip=True).split()) for cell in cells]
                if texts and norm(texts[0]) == "profuturo" and len(texts) >= 10:
                    value = parse_num(texts[9])
                    if value is not None:
                        values.append(value)
        dates = list(dict.fromkeys(dates))
        if dates and len(dates) == len(values):
            online = pd.concat([
                online,
                pd.DataFrame({"fecha": dates, "valor_cuota": values}),
            ], ignore_index=True)
    except Exception as exc:
        warnings.append(f"SBS diaria: {type(exc).__name__}: {exc}")

    online["fecha"] = pd.to_datetime(online["fecha"], errors="coerce")
    online["valor_cuota"] = pd.to_numeric(online["valor_cuota"], errors="coerce")
    online = online.dropna().sort_values("fecha").drop_duplicates("fecha", keep="last")
    return online, warnings


def load_sbs() -> tuple[pd.DataFrame, str, list[str]]:
    path = DATA / "sbs_profuturo_f3.csv"
    saved = read_saved(path)
    online, warnings = download_sbs()
    frames = [frame for frame in (saved, online) if not frame.empty]
    if not frames:
        raise RuntimeError("No hay datos SBS disponibles.")
    sbs = pd.concat(frames, ignore_index=True)
    sbs["fecha"] = pd.to_datetime(sbs["fecha"], errors="coerce")
    sbs["valor_cuota"] = pd.to_numeric(sbs["valor_cuota"], errors="coerce")
    sbs = (
        sbs.dropna()
        .loc[lambda x: x["fecha"] >= START]
        .sort_values("fecha")
        .drop_duplicates("fecha", keep="last")
        .reset_index(drop=True)
    )
    save_csv(sbs, path)
    return sbs, ("SBS EN LÍNEA" if not online.empty else "SBS GUARDADA"), warnings


def extract_close(raw: pd.DataFrame, ticker: str) -> pd.Series:
    if isinstance(raw.columns, pd.MultiIndex):
        for key in [("Close", ticker), (ticker, "Close")]:
            if key in raw.columns:
                return pd.to_numeric(raw[key], errors="coerce")
        if "Close" in raw.columns.get_level_values(0):
            block = raw.xs("Close", axis=1, level=0)
            if ticker in block.columns:
                return pd.to_numeric(block[ticker], errors="coerce")
    return pd.Series(dtype=float)


def download_yahoo() -> pd.DataFrame:
    end = (pd.Timestamp.now(tz="America/Lima") + pd.Timedelta(days=2)).strftime("%Y-%m-%d")
    raw = yf.download(
        ASSETS,
        start=START.strftime("%Y-%m-%d"),
        end=end,
        auto_adjust=False,
        actions=False,
        progress=False,
        group_by="column",
        threads=False,
    )
    if raw.empty:
        raise RuntimeError("Yahoo Finance no devolvió datos.")
    index = pd.to_datetime(raw.index)
    if getattr(index, "tz", None) is not None:
        index = index.tz_localize(None)
    market = pd.DataFrame({"fecha": index})
    for ticker in ASSETS:
        close = extract_close(raw, ticker)
        if close.empty:
            raise RuntimeError(f"Yahoo Finance no devolvió {ticker}.")
        market[ticker] = close.to_numpy()
    return market.sort_values("fecha").drop_duplicates("fecha", keep="last")


def load_bcrp() -> pd.DataFrame:
    today = pd.Timestamp.now(tz="America/Lima").tz_localize(None).normalize()
    fmt = lambda d: f"{d.year}-{d.month}-{d.day}"
    url = f"{BCRP}/{fmt(START)}/{fmt(today)}/esp"
    response = requests.get(url, timeout=40, headers=HEADERS)
    response.raise_for_status()
    rows = []
    for period in response.json().get("periods", []):
        date_value = parse_bcrp_date(period.get("name"))
        values = period.get("values", [])
        value = pd.to_numeric(str(values[0]).replace(",", "") if values else None, errors="coerce")
        if pd.notna(date_value) and pd.notna(value):
            rows.append({"fecha": date_value, "USD_PEN": float(value)})
    if not rows:
        raise RuntimeError("BCRP no devolvió USD/PEN.")
    return pd.DataFrame(rows).sort_values("fecha").drop_duplicates("fecha", keep="last")


def load_markets() -> tuple[pd.DataFrame, str, list[str]]:
    path = DATA / "markets.csv"
    saved = read_saved(path)
    warnings: list[str] = []
    fresh = pd.DataFrame()
    source = "DATOS GUARDADOS"

    try:
        basket = download_yahoo()
        fx = load_bcrp()
        fresh = basket.merge(fx, on="fecha", how="outer")
        source = "YAHOO FINANCE + BCRP"
    except Exception as exc:
        warnings.append(f"Mercados: {type(exc).__name__}: {exc}")

    if fresh.empty and saved.empty:
        raise RuntimeError("No se pudieron descargar mercados y todavía no existe respaldo guardado.")

    base_cols = ["fecha", *ASSETS, "USD_PEN"]
    if fresh.empty:
        market = saved.copy()
    elif saved.empty:
        market = fresh.copy()
    else:
        for col in base_cols:
            if col not in saved.columns:
                saved[col] = np.nan
            if col not in fresh.columns:
                fresh[col] = np.nan
        market = pd.concat([saved[base_cols], fresh[base_cols]], ignore_index=True)
        market = market.sort_values("fecha").groupby("fecha", as_index=False).last()

    market["fecha"] = pd.to_datetime(market["fecha"], errors="coerce")
    for variable in ASSETS + ["USD_PEN"]:
        market[variable] = pd.to_numeric(market[variable], errors="coerce")
    market = market.dropna(subset=["fecha"]).sort_values("fecha").drop_duplicates("fecha", keep="last")

    for variable in ASSETS + ["USD_PEN"]:
        valid = market[["fecha", variable]].dropna().copy()
        valid[f"ret_{variable}"] = valid[variable].pct_change(fill_method=None)
        market = market.drop(columns=[f"ret_{variable}"], errors="ignore").merge(
            valid[["fecha", f"ret_{variable}"]], on="fecha", how="left"
        )

    save_csv(market, path)
    return market.reset_index(drop=True), source, warnings


def classify(value: float) -> str:
    if value > THRESHOLD:
        return "SUBE"
    if value < -THRESHOLD:
        return "BAJA"
    return "NEUTRO"


def fit_ols(train: pd.DataFrame) -> np.ndarray:
    X = train[FEATURES].to_numpy(float)
    y = train["ret_profuturo"].to_numpy(float)
    return np.linalg.lstsq(np.c_[np.ones(len(X)), X], y, rcond=None)[0]


def run_model(sbs: pd.DataFrame, market: pd.DataFrame):
    s = sbs.copy()
    s["ret_profuturo"] = s["valor_cuota"].pct_change(fill_method=None)
    for date_value in EXCLUDED_RETURN_DATES:
        s.loc[s["fecha"].eq(date_value), "ret_profuturo"] = np.nan

    data = (
        s.merge(market[["fecha", *FEATURES]], on="fecha", how="inner")
        .dropna(subset=["ret_profuturo", *FEATURES])
        .sort_values("fecha")
        .reset_index(drop=True)
    )
    if len(data) < WINDOW:
        raise RuntimeError(f"Solo hay {len(data)} observaciones completas; se requieren {WINDOW}.")

    historical = []
    for i in range(WINDOW, len(data)):
        train = data.iloc[i - WINDOW:i]
        current = data.iloc[i]
        beta = fit_ols(train)
        pred = float(np.r_[1.0, current[FEATURES].to_numpy(float)] @ beta)
        historical.append({
            "fecha": current.fecha,
            "valor_cuota": float(current.valor_cuota),
            "ret_profuturo": float(current.ret_profuturo),
            "ret_estimado": pred,
            "senal": classify(pred),
            "ventana_inicio": train.iloc[0].fecha,
            "ventana_fin": train.iloc[-1].fecha,
            "n_entrenamiento": WINDOW,
        })
    historical = pd.DataFrame(historical)

    train = data.tail(WINDOW).copy()
    beta = fit_ols(train)
    latest_sbs = sbs.sort_values("fecha").iloc[-1]
    last_sbs_date = pd.Timestamp(latest_sbs.fecha)
    pending_features = (
        market.loc[market["fecha"] > last_sbs_date, ["fecha", *FEATURES]]
        .dropna(subset=FEATURES)
        .sort_values("fecha")
    )

    pending = []
    vc_base = float(latest_sbs.valor_cuota)
    for _, row in pending_features.iterrows():
        pred = float(np.r_[1.0, row[FEATURES].to_numpy(float)] @ beta)
        vc_est = vc_base * (1 + pred)
        pending.append({
            "fecha": row.fecha,
            "valor_cuota_base": vc_base,
            "ret_estimado": pred,
            "valor_cuota_estimado": vc_est,
            "senal": classify(pred),
            "ventana_inicio": train.iloc[0].fecha,
            "ventana_fin": train.iloc[-1].fecha,
            "n_entrenamiento": WINDOW,
        })
        vc_base = vc_est
    pending = pd.DataFrame(pending)

    complete_market = market.dropna(subset=FEATURES)
    meta = {
        "train_start": pd.Timestamp(train.iloc[0].fecha),
        "train_end": pd.Timestamp(train.iloc[-1].fecha),
        "train_n": len(train),
        "latest_sbs_date": last_sbs_date,
        "latest_sbs_vc": float(latest_sbs.valor_cuota),
        "latest_market_date": pd.Timestamp(complete_market.fecha.max()),
        "beta": beta.tolist(),
    }
    return historical, pending, meta


def build_series(sbs: pd.DataFrame, pending: pd.DataFrame) -> pd.DataFrame:
    official = sbs[["fecha", "valor_cuota"]].rename(columns={"valor_cuota": "vc"}).copy()
    official["fuente"] = "SBS OFICIAL"
    official["senal"] = None
    official["ret_estimado"] = np.nan
    if pending.empty:
        return official.sort_values("fecha").reset_index(drop=True)
    projected = pending[["fecha", "valor_cuota_estimado", "senal", "ret_estimado"]].rename(
        columns={"valor_cuota_estimado": "vc"}
    )
    projected["fuente"] = "MODELO OLS"
    return pd.concat([official, projected], ignore_index=True).sort_values("fecha").drop_duplicates("fecha", keep="last")


def json_default(value):
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(type(value).__name__)


def build_html() -> str:
    return '''<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#07111f"><title>Profuturo Fondo 3 · Rolling 90</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
:root{color-scheme:dark;--bg:#07111f;--card:#0f1b2d;--muted:#94a3b8;--line:#243244;--text:#f8fafc}*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif}.wrap{max-width:980px;margin:auto;padding:14px}
h1{font-size:1.45rem;margin:5px 0}.sub,.note{color:var(--muted);font-size:.82rem}.grid,.metricrow{display:grid;grid-template-columns:repeat(4,1fr);gap:9px;margin:14px 0}
.card,.panel{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:13px}.panel{margin:11px 0}.label{color:var(--muted);font-size:.76rem}.value{font-size:1.14rem;font-weight:700;margin-top:5px}.signal{font-size:1.5rem}.up{color:#4ade80}.down{color:#f87171}.flat{color:#fbbf24}
.tabs{display:grid;grid-template-columns:repeat(3,1fr);gap:7px}.tabs button,.primary{border:1px solid #334155;background:#132238;color:#fff;border-radius:10px;padding:11px;font-weight:650}.tabs button.active,.primary{background:#2563eb}
.inputs{display:grid;grid-template-columns:repeat(3,1fr);gap:9px;margin-top:12px}input{width:100%;background:#07111f;color:#fff;border:1px solid #334155;border-radius:9px;padding:10px}label{font-size:.76rem;color:var(--muted)}.hidden{display:none}.chart{height:365px}.error{background:#451a1a;padding:12px;border-radius:10px}
@media(max-width:700px){.grid,.metricrow{grid-template-columns:repeat(2,1fr)}.inputs{grid-template-columns:1fr}.chart{height:320px}}
</style></head><body><main class="wrap">
<h1>Profuturo Fondo 3</h1><div class="sub">GitHub Actions · OLS Rolling 90 · umbral ±0.10% · datos independientes del notebook</div><div id="error"></div>
<section class="grid"><div class="card"><div class="label">Último VC SBS</div><div class="value" id="sbsVc">—</div><div class="sub" id="sbsDate">—</div></div>
<div class="card"><div class="label">VC más reciente</div><div class="value" id="estVc">—</div><div class="sub" id="estDate">—</div></div>
<div class="card"><div class="label">Señal</div><div class="value signal" id="signal">—</div><div class="sub" id="ret">—</div></div>
<div class="card"><div class="label">Ventana vigente</div><div class="value">90</div><div class="sub" id="window">—</div></div></section>
<section class="panel"><div class="tabs"><button class="active" data-mode="monitor">Solo monitorear</button><button data-mode="inside">Sigo dentro</button><button data-mode="closed">Ya salí</button></div>
<div id="operation" class="hidden"><div class="inputs"><div><label>Fecha de entrada</label><input type="date" id="entry"></div><div><label>Capital invertido (S/)</label><input type="number" id="capital" value="25000" min="1" step="100"></div><div id="exitBox" class="hidden"><label>Fecha de salida</label><input type="date" id="exit"></div></div>
<button class="primary" id="calc" style="width:100%;margin-top:10px">Calcular</button><div class="metricrow"><div class="card"><div class="label">Capital</div><div class="value" id="mCapital">—</div></div><div class="card"><div class="label">Valor actual/final</div><div class="value" id="mFinal">—</div></div><div class="card"><div class="label">Ganancia/pérdida</div><div class="value" id="mGain">—</div></div><div class="card"><div class="label">Rentabilidad</div><div class="value" id="mRent">—</div></div></div><div class="note" id="detail"></div><div id="opChart" class="chart"></div></div></section>
<section class="panel"><div id="vcChart" class="chart"></div></section><section class="panel"><div id="signalChart" class="chart"></div></section><section class="panel"><b>Auditoría</b><div class="note" id="audit">Cargando…</div></section>
<script>
let latest,series=[],mode='monitor';const money=x=>new Intl.NumberFormat('es-PE',{style:'currency',currency:'PEN'}).format(x),pct=x=>(x*100).toFixed(2)+'%',fmt=x=>{if(!x)return'—';let[y,m,d]=x.slice(0,10).split('-');return d+'/'+m+'/'+y};
const after=d=>series.find(x=>x.fecha>=d),before=d=>[...series].reverse().find(x=>x.fecha<=d);
function calc(){if(mode==='monitor')return;let a=after(entry.value),b=before(mode==='closed'?exit.value:series.at(-1).fecha),c=Number(capital.value);if(!a||!b||b.fecha<a.fecha||!c){detail.textContent='No existe información válida para ese periodo.';return}let u=c/a.vc,f=u*b.vc,g=f-c,r=f/c-1;mCapital.textContent=money(c);mFinal.textContent=money(f);mGain.textContent=money(g);mRent.textContent=pct(r);detail.textContent=`Entrada usada ${fmt(a.fecha)} · VC ${a.vc.toFixed(7)} · ${a.fuente}. Salida/valoración ${fmt(b.fecha)} · VC ${b.vc.toFixed(7)} · ${b.fuente}.`;let p=series.filter(x=>x.fecha>=a.fecha&&x.fecha<=b.fecha);Plotly.newPlot('opChart',[{x:p.map(x=>x.fecha),y:p.map(x=>x.vc),mode:'lines+markers',name:'VC'},{x:p.map(x=>x.fecha),y:p.map(x=>u*x.vc-c),mode:'lines+markers',name:'Ganancia',yaxis:'y2'}],{title:'Valor cuota y ganancia/pérdida',paper_bgcolor:'#0f1b2d',plot_bgcolor:'#0f1b2d',font:{color:'#fff'},yaxis2:{overlaying:'y',side:'right'},legend:{orientation:'h'}},{responsive:true})}
document.querySelectorAll('.tabs button').forEach(b=>b.onclick=()=>{mode=b.dataset.mode;document.querySelectorAll('.tabs button').forEach(x=>x.classList.toggle('active',x===b));operation.classList.toggle('hidden',mode==='monitor');exitBox.classList.toggle('hidden',mode!=='closed')});calc.onclick=calc;
Promise.all([fetch('data/latest.json',{cache:'no-store'}).then(r=>r.json()),fetch('data/series.json',{cache:'no-store'}).then(r=>r.json())]).then(([l,s])=>{latest=l;series=s.sort((a,b)=>a.fecha.localeCompare(b.fecha));sbsVc.textContent=Number(l.latest_sbs_vc).toFixed(7);sbsDate.textContent=fmt(l.latest_sbs_date);estVc.textContent=Number(l.latest_estimated_vc).toFixed(7);estDate.textContent=fmt(l.latest_estimate_date)+' · '+l.estimate_type;signal.textContent=l.signal;signal.className='value signal '+(l.signal==='SUBE'?'up':l.signal==='BAJA'?'down':'flat');ret.textContent=(l.latest_return_estimated*100).toFixed(3)+'%';window.textContent=fmt(l.training_start)+' → '+fmt(l.training_end);audit.innerHTML=`Actualizado: ${new Date(l.generated_at_lima).toLocaleString('es-PE')}<br>Último mercado completo: ${fmt(l.latest_market_date)}<br>Fuentes: ${l.sources.market} · ${l.sources.sbs}<br>El OLS se recalibra con las últimas 90 observaciones completas cada vez que entra un nuevo VC oficial SBS.`;entry.min=series[0].fecha;entry.max=series.at(-1).fecha;entry.value=l.latest_sbs_date;exit.min=series[0].fecha;exit.max=series.at(-1).fecha;exit.value=series.at(-1).fecha;let off=series.filter(x=>x.fuente==='SBS OFICIAL'),mod=series.filter(x=>x.fuente==='MODELO OLS');Plotly.newPlot('vcChart',[{x:off.map(x=>x.fecha),y:off.map(x=>x.vc),mode:'lines',name:'VC SBS'},{x:mod.map(x=>x.fecha),y:mod.map(x=>x.vc),mode:'lines+markers',name:'VC modelo'}],{title:'Valor cuota oficial y estimado',paper_bgcolor:'#0f1b2d',plot_bgcolor:'#0f1b2d',font:{color:'#fff'},legend:{orientation:'h'}},{responsive:true});Plotly.newPlot('signalChart',[{x:mod.map(x=>x.fecha),y:mod.map(x=>x.ret_estimado*100),mode:'lines+markers',name:'Retorno OLS'}],{title:'Retorno estimado',paper_bgcolor:'#0f1b2d',plot_bgcolor:'#0f1b2d',font:{color:'#fff'},shapes:[{type:'line',xref:'paper',x0:0,x1:1,y0:.1,y1:.1,line:{dash:'dot'}},{type:'line',xref:'paper',x0:0,x1:1,y0:-.1,y1:-.1,line:{dash:'dot'}}]},{responsive:true})}).catch(e=>error.innerHTML='<div class="error">No se pudieron cargar resultados: '+e+'</div>');
</script></main></body></html>'''


def main() -> None:
    sbs, sbs_source, sbs_warnings = load_sbs()
    market, market_source, market_warnings = load_markets()
    historical, pending, meta = run_model(sbs, market)
    series = build_series(sbs, pending)

    if not pending.empty:
        row = pending.iloc[-1]
        latest_vc = float(row.valor_cuota_estimado)
        latest_return = float(row.ret_estimado)
        signal = str(row.senal)
        estimate_date = pd.Timestamp(row.fecha)
        estimate_type = "MODELO OLS"
    else:
        row = historical.iloc[-1]
        latest_vc = float(meta["latest_sbs_vc"])
        latest_return = float(row.ret_estimado)
        signal = str(row.senal)
        estimate_date = pd.Timestamp(meta["latest_sbs_date"])
        estimate_type = "SBS AL DÍA"

    now = datetime.now(LIMA)
    latest = {
        "generated_at_lima": now.isoformat(),
        "model": "OLS rolling 90",
        "window": WINDOW,
        "threshold": THRESHOLD,
        "training_start": meta["train_start"],
        "training_end": meta["train_end"],
        "training_n": meta["train_n"],
        "latest_sbs_date": meta["latest_sbs_date"],
        "latest_sbs_vc": meta["latest_sbs_vc"],
        "latest_market_date": meta["latest_market_date"],
        "latest_estimate_date": estimate_date,
        "latest_estimated_vc": latest_vc,
        "latest_return_estimated": latest_return,
        "signal": signal,
        "estimate_type": estimate_type,
        "sources": {"sbs": sbs_source, "market": market_source},
        "warnings": [*sbs_warnings, *market_warnings][-10:],
        "coefficients": {"intercept": meta["beta"][0], **{k: v for k, v in zip(FEATURES, meta["beta"][1:])}},
    }

    (PUBLIC_DATA / "latest.json").write_text(json.dumps(latest, ensure_ascii=False, indent=2, default=json_default), encoding="utf-8")
    series_out = series.copy()
    series_out["fecha"] = series_out["fecha"].dt.strftime("%Y-%m-%d")
    (PUBLIC_DATA / "series.json").write_text(series_out.to_json(orient="records", force_ascii=False), encoding="utf-8")
    save_csv(series, PUBLIC_DATA / "series.csv")
    save_csv(historical, DATA / "historical_predictions.csv")
    save_csv(pending, DATA / "pending_predictions.csv")
    (PUBLIC / "index.html").write_text(build_html(), encoding="utf-8")

    print("OLS rolling 90 actualizado")
    print(f"Ventana: {meta['train_start']:%Y-%m-%d} -> {meta['train_end']:%Y-%m-%d}")
    print(f"Último SBS: {meta['latest_sbs_date']:%Y-%m-%d}")
    print(f"Último mercado: {meta['latest_market_date']:%Y-%m-%d}")
    print(f"Señal: {signal} · retorno {latest_return:+.4%} · VC {latest_vc:.7f}")


if __name__ == "__main__":
    main()
