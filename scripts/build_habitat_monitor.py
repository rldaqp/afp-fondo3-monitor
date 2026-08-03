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
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "rolling90"
PUBLIC = ROOT / "public" / "habitat"
PUBLIC_DATA = PUBLIC / "data"
DATA.mkdir(parents=True, exist_ok=True)
PUBLIC_DATA.mkdir(parents=True, exist_ok=True)

AFP_NAME = "Hábitat"
AFP_KEY = "habitat"
WINDOW = 90
THRESHOLD = 0.001
START = pd.Timestamp("2024-12-31")
LIMA = ZoneInfo("America/Lima")
FEATURES = [
    "ret_SPY",
    "ret_NEM",
    "ret_FCX",
    "ret_EPU",
    "ret_MCHI",
    "ret_EEM",
    "ret_USD_PEN",
]
SBS_INDEX = "https://www.sbs.gob.pe/app/stats/EstadisticaSistemaFinancieroResultados.asp?c=FP-1359"
SBS_DAILY = "https://www.sbs.gob.pe/app/spp/variablesSPP_net/PagSS/variables_spp.aspx"
HEADERS = {"User-Agent": "Mozilla/5.0 AFP-Habitat-Fondo3-GitHubActions"}


def norm(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return " ".join(text.lower().split())


def parse_num(value: object) -> float | None:
    number = pd.to_numeric(
        str(value).replace("\xa0", "").replace(" ", "").replace(",", ""),
        errors="coerce",
    )
    return None if pd.isna(number) else float(number)


def read_saved(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    frame = pd.read_csv(path)
    if "fecha" in frame.columns:
        frame["fecha"] = pd.to_datetime(frame["fecha"], errors="coerce")
    return frame


def save_csv(frame: pd.DataFrame, path: Path) -> None:
    out = frame.copy()
    for column in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[column]):
            out[column] = out[column].dt.strftime("%Y-%m-%d")
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
        links: list[str] = []
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
                    row
                    for row in range(min(25, len(raw)))
                    if "dia" in [norm(value) for value in raw.iloc[row]]
                    and AFP_KEY in [norm(value) for value in raw.iloc[row]]
                )
                header = [norm(value) for value in raw.iloc[header_row]]
                block = raw.iloc[
                    header_row + 1 :,
                    [header.index("dia"), header.index(AFP_KEY)],
                ].copy()
                block.columns = ["fecha", "valor_cuota"]
                block["fecha"] = pd.to_datetime(block["fecha"], errors="coerce")
                block["valor_cuota"] = pd.to_numeric(block["valor_cuota"], errors="coerce")
                frames.append(block.dropna())
            except Exception as exc:
                warnings.append(f"SBS XLS: {type(exc).__name__}")
    except Exception as exc:
        warnings.append(f"SBS índice: {type(exc).__name__}: {exc}")

    online = (
        pd.concat(frames, ignore_index=True)
        if frames
        else pd.DataFrame(columns=["fecha", "valor_cuota"])
    )

    try:
        page = session.get(SBS_DAILY, timeout=40)
        page.raise_for_status()
        soup = BeautifulSoup(page.content, "lxml")
        dates: list[pd.Timestamp] = []
        values: list[float] = []
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
                if texts and norm(texts[0]) == AFP_KEY and len(texts) >= 10:
                    value = parse_num(texts[9])
                    if value is not None:
                        values.append(value)
        dates = list(dict.fromkeys(dates))
        if dates and len(dates) == len(values):
            online = pd.concat(
                [online, pd.DataFrame({"fecha": dates, "valor_cuota": values})],
                ignore_index=True,
            )
    except Exception as exc:
        warnings.append(f"SBS diaria: {type(exc).__name__}: {exc}")

    online["fecha"] = pd.to_datetime(online["fecha"], errors="coerce")
    online["valor_cuota"] = pd.to_numeric(online["valor_cuota"], errors="coerce")
    online = online.dropna().sort_values("fecha").drop_duplicates("fecha", keep="last")
    return online, warnings


def load_sbs() -> tuple[pd.DataFrame, str, list[str]]:
    path = DATA / "sbs_habitat_f3.csv"
    saved = read_saved(path)
    online, warnings = download_sbs()
    frames = [frame for frame in (saved, online) if not frame.empty]
    if not frames:
        raise RuntimeError("No hay datos SBS de Hábitat Fondo 3 disponibles.")
    sbs = pd.concat(frames, ignore_index=True)
    sbs["fecha"] = pd.to_datetime(sbs["fecha"], errors="coerce")
    sbs["valor_cuota"] = pd.to_numeric(sbs["valor_cuota"], errors="coerce")
    sbs = (
        sbs.dropna()
        .loc[lambda frame: frame["fecha"] >= START]
        .sort_values("fecha")
        .drop_duplicates("fecha", keep="last")
        .reset_index(drop=True)
    )
    save_csv(sbs, path)
    return sbs, ("SBS EN LÍNEA" if not online.empty else "SBS GUARDADA"), warnings


def load_market() -> pd.DataFrame:
    market_path = DATA / "markets.csv"
    if not market_path.exists():
        raise RuntimeError("No existe data/rolling90/markets.csv; ejecute primero el monitor principal.")
    market = pd.read_csv(market_path)
    market["fecha"] = pd.to_datetime(market["fecha"], errors="coerce")
    for feature in FEATURES:
        if feature not in market.columns:
            market[feature] = np.nan
        market[feature] = pd.to_numeric(market[feature], errors="coerce")

    pending_path = DATA / "pending_predictions.csv"
    if pending_path.exists() and pending_path.stat().st_size:
        pending = pd.read_csv(pending_path)
        pending["fecha"] = pd.to_datetime(pending["fecha"], errors="coerce")
        available = [feature for feature in FEATURES if feature in pending.columns]
        if available:
            pending = pending[["fecha", *available]].drop_duplicates("fecha", keep="last")
            market = market.merge(pending, on="fecha", how="outer", suffixes=("", "_pending"))
            for feature in available:
                market[feature] = market[feature].fillna(market[f"{feature}_pending"])
                market = market.drop(columns=[f"{feature}_pending"])

    return market.dropna(subset=["fecha"]).sort_values("fecha").drop_duplicates("fecha", keep="last")


def classify(value: float) -> str:
    if value > THRESHOLD:
        return "SUBE"
    if value < -THRESHOLD:
        return "BAJA"
    return "NEUTRO"


def fit_ols(train: pd.DataFrame) -> np.ndarray:
    x_values = train[FEATURES].to_numpy(float)
    y_values = train["ret_habitat"].to_numpy(float)
    return np.linalg.lstsq(np.c_[np.ones(len(x_values)), x_values], y_values, rcond=None)[0]


def json_records(frame: pd.DataFrame) -> list[dict[str, object]]:
    out = frame.copy()
    for column in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[column]):
            out[column] = out[column].dt.strftime("%Y-%m-%d")
    return json.loads(out.to_json(orient="records", force_ascii=False))


def run_model(sbs: pd.DataFrame, market: pd.DataFrame) -> tuple[dict, list, list, dict]:
    official = sbs.copy()
    official["ret_habitat"] = official["valor_cuota"].pct_change(fill_method=None)
    data = (
        official.merge(market[["fecha", *FEATURES]], on="fecha", how="inner")
        .dropna(subset=["ret_habitat", *FEATURES])
        .sort_values("fecha")
        .reset_index(drop=True)
    )
    if len(data) < WINDOW:
        raise RuntimeError(f"Hábitat solo tiene {len(data)} observaciones completas; se requieren {WINDOW}.")

    historical_rows: list[dict[str, object]] = []
    for index in range(WINDOW, len(data)):
        train = data.iloc[index - WINDOW : index]
        current = data.iloc[index]
        beta = fit_ols(train)
        prediction = float(np.r_[1.0, current[FEATURES].to_numpy(float)] @ beta)
        historical_rows.append(
            {
                "fecha": current["fecha"],
                "vc": float(current["valor_cuota"]),
                "ret_real": float(current["ret_habitat"]),
                "ret_estimado": prediction,
                "senal": classify(prediction),
                "senal_real": classify(float(current["ret_habitat"])),
            }
        )
    historical = pd.DataFrame(historical_rows)

    train = data.tail(WINDOW).copy()
    beta = fit_ols(train)
    latest_official = official.iloc[-1]
    base_vc = float(latest_official["valor_cuota"])
    last_sbs_date = pd.Timestamp(latest_official["fecha"])
    pending_features = (
        market.loc[market["fecha"] > last_sbs_date, ["fecha", *FEATURES]]
        .dropna(subset=FEATURES)
        .sort_values("fecha")
    )

    pending_rows: list[dict[str, object]] = []
    current_vc = base_vc
    for _, row in pending_features.iterrows():
        prediction = float(np.r_[1.0, row[FEATURES].to_numpy(float)] @ beta)
        current_vc *= 1.0 + prediction
        pending_rows.append(
            {
                "fecha": row["fecha"],
                "vc": current_vc,
                "fuente": "MODELO OLS",
                "es_oficial": False,
                "senal": classify(prediction),
                "ret_estimado": prediction,
            }
        )

    official_series = official[["fecha", "valor_cuota"]].rename(columns={"valor_cuota": "vc"})
    official_series["fuente"] = "SBS OFICIAL"
    official_series["es_oficial"] = True
    official_series["senal"] = None
    official_series["ret_estimado"] = None
    pending_frame = pd.DataFrame(pending_rows)
    series = pd.concat([official_series, pending_frame], ignore_index=True, sort=False)
    series = series.sort_values("fecha").drop_duplicates("fecha", keep="last")

    signal_frame = historical[["fecha", "ret_estimado", "senal"]].copy()
    if not pending_frame.empty:
        signal_frame = pd.concat(
            [signal_frame, pending_frame[["fecha", "ret_estimado", "senal"]]],
            ignore_index=True,
        )
    signal_frame = signal_frame.sort_values("fecha").drop_duplicates("fecha", keep="last")

    if not pending_frame.empty:
        current = pending_frame.iloc[-1]
        latest_estimate_date = pd.Timestamp(current["fecha"])
        latest_estimated_vc = float(current["vc"])
        latest_return = float(current["ret_estimado"])
        latest_signal = str(current["senal"])
        estimate_type = "CIERRE DISPONIBLE · MODELO OLS HÁBITAT"
        current_features = pending_features.iloc[-1]
    else:
        last_hist = historical.iloc[-1]
        latest_estimate_date = last_sbs_date
        latest_estimated_vc = base_vc
        latest_return = float(last_hist["ret_estimado"])
        latest_signal = str(last_hist["senal"])
        estimate_type = "ÚLTIMO VC OFICIAL SBS"
        current_features = data.iloc[-1]

    recent = historical.tail(WINDOW).copy()
    recent["correcta"] = recent["senal"] == recent["senal_real"]
    accuracy = float(recent["correcta"].mean()) if not recent.empty else 0.0
    same_signal = recent.loc[recent["senal"] == latest_signal]
    signal_accuracy = float(same_signal["correcta"].mean()) if not same_signal.empty else 0.0
    errors = (recent["ret_estimado"] - recent["ret_real"]).abs()
    ols_mae = float(errors.mean()) if not errors.empty else 0.0
    zero_mae = float(recent["ret_real"].abs().mean()) if not recent.empty else 0.0
    q80 = float(errors.quantile(0.80)) if not errors.empty else 0.0

    labels = {
        "ret_SPY": "SPY",
        "ret_NEM": "NEM",
        "ret_FCX": "FCX",
        "ret_EPU": "EPU",
        "ret_MCHI": "MCHI",
        "ret_EEM": "EEM",
        "ret_USD_PEN": "USD/PEN",
    }
    coefficients = {"intercept": float(beta[0])}
    contributions = [
        {
            "feature": "intercept",
            "label": "Base",
            "value": 1.0,
            "coefficient": float(beta[0]),
            "contribution_pp": float(beta[0] * 100),
        }
    ]
    for position, feature in enumerate(FEATURES, start=1):
        value = float(current_features[feature])
        coefficient = float(beta[position])
        coefficients[feature] = coefficient
        contributions.append(
            {
                "feature": feature,
                "label": labels[feature],
                "value": value,
                "coefficient": coefficient,
                "contribution_pp": coefficient * value * 100,
            }
        )
    contributions.sort(key=lambda item: abs(float(item["contribution_pp"])), reverse=True)

    latest = {
        "afp": AFP_NAME,
        "fund": 3,
        "generated_at_lima": datetime.now(LIMA).isoformat(),
        "model": "OLS rolling 90",
        "window": WINDOW,
        "threshold": THRESHOLD,
        "training_start": train.iloc[0]["fecha"].strftime("%Y-%m-%d"),
        "training_end": train.iloc[-1]["fecha"].strftime("%Y-%m-%d"),
        "training_n": len(train),
        "latest_sbs_date": last_sbs_date.strftime("%Y-%m-%d"),
        "latest_sbs_vc": base_vc,
        "latest_market_date": market["fecha"].max().strftime("%Y-%m-%d"),
        "latest_estimate_date": latest_estimate_date.strftime("%Y-%m-%d"),
        "latest_estimated_vc": latest_estimated_vc,
        "latest_return_estimated": latest_return,
        "signal": latest_signal,
        "estimate_type": estimate_type,
        "coefficients": coefficients,
        "sources": {
            "sbs": "SBS oficial · Fondo 3 · AFP Hábitat",
            "market": "Serie de mercado compartida por el monitor principal",
        },
    }
    insights = {
        "generated_for": latest_estimate_date.strftime("%Y-%m-%d"),
        "current_signal": latest_signal,
        "confidence": {
            "historical_accuracy": signal_accuracy,
            "n": int(len(same_signal)),
            "description": "Aciertos históricos de la misma clase de señal; no es una garantía futura.",
        },
        "performance": {
            "window_n": int(len(recent)),
            "classification_accuracy": accuracy,
            "mae_return_pp": ols_mae * 100,
        },
        "uncertainty": {
            "relative_q80": q80,
            "label": "Banda empírica 80%",
        },
        "benchmarks": {
            "zero_change_mae_pp": zero_mae * 100,
            "ols_mae_pp": ols_mae * 100,
        },
        "contributions": contributions,
        "quality": {
            "status": "OK",
            "warnings": [],
            "training_n": len(train),
            "latest_sbs_date": last_sbs_date.strftime("%Y-%m-%d"),
        },
    }

    return latest, json_records(series), json_records(signal_frame), insights


HTML = r'''<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#07111f"><title>Hábitat Fondo 3 · Rolling 90</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
:root{color-scheme:dark;--bg:#07111f;--card:#0f1b2d;--muted:#94a3b8;--line:#243244;--text:#f8fafc;--primary:#16a34a}*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif}.wrap{max-width:980px;margin:auto;padding:14px}
h1{font-size:1.45rem;margin:5px 0}.sub,.note{color:var(--muted);font-size:.82rem;line-height:1.45}.selector{display:grid;grid-template-columns:1fr 1fr;gap:9px;margin:12px 0}.selector label{font-size:.72rem;color:var(--muted)}
select,input{width:100%;background:#07111f;color:#fff;border:1px solid #334155;border-radius:9px;padding:10px}.grid,.metricrow{display:grid;grid-template-columns:repeat(4,1fr);gap:9px;margin:14px 0}
.card,.panel{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:13px}.panel{margin:11px 0}.label{color:var(--muted);font-size:.76rem}.value{font-size:1.14rem;font-weight:750;margin-top:5px}.signal{font-size:1.5rem}.up{color:#4ade80}.down{color:#f87171}.flat{color:#fbbf24}
.tabs{display:grid;grid-template-columns:repeat(3,1fr);gap:7px}.tabs button,.primary,.range button{border:1px solid #334155;background:#132238;color:#fff;border-radius:10px;padding:11px;font-weight:700}.tabs button.active,.primary,.range button.active{background:var(--primary)}
.inputs{display:grid;grid-template-columns:repeat(3,1fr);gap:9px;margin-top:12px}.hidden{display:none}.chart{height:350px}.error{background:#451a1a;padding:12px;border-radius:10px}.range{display:flex;gap:6px;flex-wrap:wrap;margin:8px 0}.range button{padding:8px 10px}
.insights{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}.insight{background:#0b1728;border:1px solid #243244;border-radius:11px;padding:10px}.factor{display:grid;grid-template-columns:75px 1fr 70px;gap:8px;margin:7px 0;font-size:.75rem}.bar{height:8px;background:#172338;border-radius:999px;overflow:hidden}.fill{height:100%;background:#64748b}
@media(max-width:700px){.grid,.metricrow,.insights{grid-template-columns:repeat(2,1fr)}.inputs,.selector{grid-template-columns:1fr}.chart{height:310px}.wrap{padding:10px}}
</style></head><body><main class="wrap">
<div class="selector"><div><label>AFP</label><select id="afp"><option value="../index.html">Profuturo</option><option value="./" selected>Hábitat</option></select></div><div><label>Fondo</label><select disabled><option>Fondo 3</option></select></div></div>
<h1>Hábitat Fondo 3</h1><div class="sub">GitHub Actions · OLS Rolling 90 propio · umbral ±0.10% · datos oficiales SBS</div><div id="error"></div>
<section class="grid"><div class="card"><div class="label">Último VC SBS</div><div class="value" id="sbsVc">—</div><div class="sub" id="sbsDate">—</div></div><div class="card"><div class="label">VC más reciente</div><div class="value" id="estVc">—</div><div class="sub" id="estDate">—</div></div><div class="card"><div class="label">Señal</div><div class="value signal" id="signal">—</div><div class="sub" id="ret">—</div></div><div class="card"><div class="label">Ventana vigente</div><div class="value">90</div><div class="sub" id="window">—</div></div></section>
<section class="panel"><b>Confianza y calidad del modelo</b><div class="insights" style="margin-top:10px"><div class="insight"><div class="label">Aciertos de esta señal</div><div class="value" id="confidence">—</div><div class="sub" id="confidenceN">—</div></div><div class="insight"><div class="label">Acierto global</div><div class="value" id="accuracy">—</div><div class="sub">Últimas observaciones evaluables</div></div><div class="insight"><div class="label">Banda histórica 80%</div><div class="value" id="band">—</div><div class="sub">Error del retorno estimado</div></div><div class="insight"><div class="label">OLS vs sin cambio</div><div class="value" id="benchmark">—</div><div class="sub">MAE del retorno diario</div></div></div><details style="margin-top:10px"><summary>Ver qué mueve la señal</summary><div id="factors"></div></details></section>
<section class="panel"><div class="range"><button data-days="30">30 días</button><button data-days="90" class="active">90 días</button><button data-days="all">Todo</button></div><div id="vcChart" class="chart"></div></section>
<section class="panel"><div class="tabs"><button class="active" data-mode="monitor">Solo monitorear</button><button data-mode="inside">Sigo dentro</button><button data-mode="closed">Ya salí</button></div><div id="operation" class="hidden"><div class="inputs"><div><label>Fecha de entrada</label><input type="date" id="entry"></div><div><label>Capital invertido (S/)</label><input type="number" id="capital" value="100" min="1" step="10"></div><div id="exitBox" class="hidden"><label>Fecha de salida</label><input type="date" id="exit"></div></div><button class="primary" id="calc" style="width:100%;margin-top:10px">Calcular</button><div class="metricrow"><div class="card"><div class="label">Capital</div><div class="value" id="mCapital">—</div></div><div class="card"><div class="label">Valor actual/final</div><div class="value" id="mFinal">—</div></div><div class="card"><div class="label">Ganancia/pérdida</div><div class="value" id="mGain">—</div></div><div class="card"><div class="label">Rentabilidad</div><div class="value" id="mRent">—</div></div></div><div class="note" id="detail"></div><div id="opChart" class="chart"></div></div></section>
<section class="panel"><b>Auditoría</b><div class="note" id="audit">Cargando…</div></section>
<script>
let latest,series=[],insights,mode='monitor',days=90;const $=id=>document.getElementById(id),money=x=>new Intl.NumberFormat('es-PE',{style:'currency',currency:'PEN'}).format(x),pct=(x,d=2)=>(x*100).toFixed(d)+'%',fmt=x=>{if(!x)return'—';let[y,m,d]=x.slice(0,10).split('-');return d+'/'+m+'/'+y};
$('afp').onchange=e=>location.href=e.target.value;const after=d=>series.find(x=>x.fecha>=d),before=d=>[...series].reverse().find(x=>x.fecha<=d);
function chart(){let p=days==='all'?series:series.slice(-Number(days));let off=p.filter(x=>x.es_oficial),mod=p.filter(x=>!x.es_oficial);Plotly.newPlot('vcChart',[{x:off.map(x=>x.fecha),y:off.map(x=>x.vc),mode:'lines',name:'VC SBS'},{x:mod.map(x=>x.fecha),y:mod.map(x=>x.vc),mode:'lines+markers',name:'VC modelo'}],{title:'Valor cuota oficial y estimado',paper_bgcolor:'#0f1b2d',plot_bgcolor:'#0f1b2d',font:{color:'#fff'},legend:{orientation:'h'},margin:{l:52,r:20,t:45,b:45}},{responsive:true})}
function calc(){if(mode==='monitor')return;let a=after($('entry').value),b=before(mode==='closed'?$('exit').value:series.at(-1).fecha),c=Number($('capital').value);if(!a||!b||b.fecha<a.fecha||!c){$('detail').textContent='No existe información válida para ese periodo.';return}let units=c/a.vc,final=units*b.vc,gain=final-c,r=final/c-1;$('mCapital').textContent=money(c);$('mFinal').textContent=money(final);$('mGain').textContent=money(gain);$('mRent').textContent=pct(r);$('detail').textContent=`Entrada usada ${fmt(a.fecha)} · VC ${Number(a.vc).toFixed(7)} · ${a.fuente}. Salida/valoración ${fmt(b.fecha)} · VC ${Number(b.vc).toFixed(7)} · ${b.fuente}.`;let p=series.filter(x=>x.fecha>=a.fecha&&x.fecha<=b.fecha);Plotly.newPlot('opChart',[{x:p.map(x=>x.fecha),y:p.map(x=>units*x.vc),mode:'lines',name:'Valor de inversión'}],{title:'Evolución de la inversión',paper_bgcolor:'#0f1b2d',plot_bgcolor:'#0f1b2d',font:{color:'#fff'},margin:{l:60,r:20,t:45,b:45}},{responsive:true})}
document.querySelectorAll('.tabs button').forEach(button=>button.onclick=()=>{mode=button.dataset.mode;document.querySelectorAll('.tabs button').forEach(x=>x.classList.toggle('active',x===button));$('operation').classList.toggle('hidden',mode==='monitor');$('exitBox').classList.toggle('hidden',mode!=='closed')});document.querySelectorAll('.range button').forEach(button=>button.onclick=()=>{days=button.dataset.days;document.querySelectorAll('.range button').forEach(x=>x.classList.toggle('active',x===button));chart()});$('calc').onclick=calc;
Promise.all([fetch('data/latest.json',{cache:'no-store'}).then(r=>r.json()),fetch('data/series.json',{cache:'no-store'}).then(r=>r.json()),fetch('data/model_insights.json',{cache:'no-store'}).then(r=>r.json())]).then(([l,s,i])=>{latest=l;series=s.sort((a,b)=>a.fecha.localeCompare(b.fecha));insights=i;$('sbsVc').textContent=Number(l.latest_sbs_vc).toFixed(7);$('sbsDate').textContent=fmt(l.latest_sbs_date);$('estVc').textContent=Number(l.latest_estimated_vc).toFixed(7);$('estDate').textContent=fmt(l.latest_estimate_date)+' · '+l.estimate_type;$('signal').textContent=l.signal;$('signal').className='value signal '+(l.signal==='SUBE'?'up':l.signal==='BAJA'?'down':'flat');$('ret').textContent='Retorno estimado: '+pct(l.latest_return_estimated,3);$('window').textContent=fmt(l.training_start)+' → '+fmt(l.training_end);$('confidence').textContent=pct(i.confidence.historical_accuracy,1);$('confidenceN').textContent=`${i.confidence.n} señales comparables`; $('accuracy').textContent=pct(i.performance.classification_accuracy,1);$('band').textContent='±'+pct(i.uncertainty.relative_q80,2);$('benchmark').textContent=`${i.benchmarks.ols_mae_pp.toFixed(2)} pp vs ${i.benchmarks.zero_change_mae_pp.toFixed(2)} pp`;$('factors').innerHTML=i.contributions.map(x=>{let w=Math.min(100,Math.abs(x.contribution_pp)*40);return `<div class="factor"><b>${x.label}</b><div class="bar"><div class="fill" style="width:${w}%"></div></div><span>${x.contribution_pp>=0?'+':''}${x.contribution_pp.toFixed(3)} pp</span></div>`}).join('');$('audit').innerHTML=`Actualizado: ${new Date(l.generated_at_lima).toLocaleString('es-PE')}<br>Último mercado: ${fmt(l.latest_market_date)}<br>Fuentes: ${l.sources.market} · ${l.sources.sbs}<br>El modelo de Hábitat se entrena por separado y no reutiliza coeficientes de Profuturo.`;$('entry').min=series[0].fecha;$('entry').max=series.at(-1).fecha;$('entry').value=l.latest_sbs_date;$('exit').min=series[0].fecha;$('exit').max=series.at(-1).fecha;$('exit').value=series.at(-1).fecha;chart()}).catch(e=>$('error').innerHTML='<div class="error">No se pudieron cargar resultados de Hábitat: '+e+'</div>');
</script></main></body></html>'''


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    sbs, sbs_source, warnings = load_sbs()
    market = load_market()
    latest, series, signals, insights = run_model(sbs, market)
    latest["sbs_download_status"] = sbs_source
    latest["warnings"] = warnings
    write_json(PUBLIC_DATA / "latest.json", latest)
    write_json(PUBLIC_DATA / "series.json", series)
    write_json(PUBLIC_DATA / "signals.json", signals)
    write_json(PUBLIC_DATA / "model_insights.json", insights)
    PUBLIC.joinpath("index.html").write_text(HTML, encoding="utf-8")
    print(json.dumps(latest, ensure_ascii=False, indent=2))
    print(f"Hábitat: {len(series)} puntos publicados; {len(signals)} señales.")


if __name__ == "__main__":
    main()
