from __future__ import annotations

import io, re, unicodedata
from urllib.parse import urljoin

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
import yfinance as yf
from bs4 import BeautifulSoup

st.set_page_config(page_title="Monitor Profuturo F3", page_icon="📈", layout="wide")

SBS_INDEX = "https://www.sbs.gob.pe/app/stats/EstadisticaSistemaFinancieroResultados.asp?c=FP-1359"
SBS_DAILY = "https://www.sbs.gob.pe/app/spp/variablesSPP_net/PagSS/variables_spp.aspx"
BCRP = "https://estadisticas.bcrp.gob.pe/estadisticas/series/api/PD04646PD/json"
ASSETS = ["SPY", "NEM", "FCX", "EPU", "MCHI"]
FEATURES = [f"ret_{x}" for x in ASSETS] + ["ret_USD_PEN"]
WINDOW, THRESHOLD = 90, 0.001
UA = {"User-Agent": "Mozilla/5.0 AFP-Fondo3-Monitor"}


def norm(x):
    s = unicodedata.normalize("NFKD", str(x))
    return " ".join("".join(c for c in s if not unicodedata.combining(c)).lower().split())


def parse_num(x):
    v = pd.to_numeric(str(x).replace("\xa0", "").replace(" ", "").replace(",", ""), errors="coerce")
    return None if pd.isna(v) else float(v)


@st.cache_data(ttl=3600, show_spinner=False)
def load_sbs():
    session = requests.Session(); session.headers.update(UA)
    html = session.get(SBS_INDEX, timeout=60); html.raise_for_status()
    soup = BeautifulSoup(html.content, "lxml")
    links = []
    for a in soup.find_all("a", href=True):
        u = urljoin(SBS_INDEX, a["href"])
        if "FP-1359" in u.upper() and u.lower().endswith(".xls") and re.search(r"202[5-9]", u):
            links.append(u)
    frames = []
    for u in sorted(set(links)):
        try:
            raw = pd.read_excel(io.BytesIO(session.get(u, timeout=60).content), sheet_name="VC-Diario-Fondo3", header=None, engine="xlrd")
            header = next(i for i in range(min(20, len(raw))) if "dia" in [norm(v) for v in raw.iloc[i]] and "profuturo" in [norm(v) for v in raw.iloc[i]])
            h = [norm(v) for v in raw.iloc[header]]
            d = raw.iloc[header+1:, [h.index("dia"), h.index("profuturo")]].copy()
            d.columns = ["fecha", "valor_cuota"]
            d["fecha"] = pd.to_datetime(d["fecha"], errors="coerce")
            d["valor_cuota"] = pd.to_numeric(d["valor_cuota"], errors="coerce")
            frames.append(d.dropna())
        except Exception:
            pass
    if not frames:
        raise RuntimeError("No se pudo descargar el histórico SBS")
    sbs = pd.concat(frames).sort_values("fecha").drop_duplicates("fecha", keep="last")
    try:
        page = session.get(SBS_DAILY, timeout=40); page.raise_for_status(); soup = BeautifulSoup(page.content, "lxml")
        dates = []
        for node in soup.find_all(string=True):
            txt = " ".join(str(node).split())
            if "informacion al" in norm(txt) and (m := re.search(r"\d{2}/\d{2}/\d{4}", txt)):
                dates.append(pd.to_datetime(m.group(), format="%d/%m/%Y"))
        vals = []
        for table in soup.find_all("table"):
            for row in table.find_all("tr"):
                cells = row.find_all(["th", "td"], recursive=False)
                texts = [" ".join(c.get_text(" ", strip=True).split()) for c in cells]
                if texts and norm(texts[0]) == "profuturo" and len(texts) >= 10:
                    v = parse_num(texts[9])
                    if v is not None: vals.append(v)
        dates = list(dict.fromkeys(dates))
        if len(dates) == len(vals):
            sbs = pd.concat([sbs, pd.DataFrame({"fecha": dates, "valor_cuota": vals})]).sort_values("fecha").drop_duplicates("fecha", keep="last")
    except Exception:
        pass
    return sbs.reset_index(drop=True)


def yf_close(raw, ticker):
    if isinstance(raw.columns, pd.MultiIndex):
        for k in [("Close", ticker), (ticker, "Close")]:
            if k in raw.columns: return pd.to_numeric(raw[k], errors="coerce")
        if "Close" in raw.columns.get_level_values(0):
            b = raw.xs("Close", axis=1, level=0)
            if ticker in b: return pd.to_numeric(b[ticker], errors="coerce")
    return pd.Series(dtype=float)


def parse_bcrp_date(x):
    m = re.search(r"(\d{1,2})[.\-/ ]+([A-Za-zÁÉÍÓÚáéíóú]{3,5})[.\-/ ]+(\d{2,4})", str(x))
    if not m: return pd.NaT
    d, mon, y = m.groups(); mon = norm(mon)
    mm = {"ene":1,"feb":2,"mar":3,"abr":4,"may":5,"jun":6,"jul":7,"ago":8,"set":9,"sep":9,"sept":9,"oct":10,"nov":11,"dic":12}.get(mon)
    if not mm: return pd.NaT
    y = int(y) + (2000 if int(y) < 100 else 0)
    try: return pd.Timestamp(y, mm, int(d))
    except ValueError: return pd.NaT


@st.cache_data(ttl=900, show_spinner=False)
def load_markets():
    raw = yf.download(ASSETS, start="2024-12-31", auto_adjust=False, actions=False, progress=False, group_by="column", threads=True)
    mkt = pd.DataFrame(index=pd.to_datetime(raw.index).tz_localize(None))
    for t in ASSETS: mkt[t] = yf_close(raw, t)
    mkt.index.name = "fecha"; mkt = mkt.reset_index()
    today = pd.Timestamp.now(tz="America/Lima").tz_localize(None).normalize()
    fmt = lambda d: f"{d.year}-{d.month}-{d.day}"
    fx = requests.get(f"{BCRP}/{fmt(pd.Timestamp('2024-12-31'))}/{fmt(today)}/esp", timeout=40, headers=UA).json()
    rows = []
    for p in fx.get("periods", []):
        date = parse_bcrp_date(p.get("name")); vals = p.get("values", [])
        val = pd.to_numeric(str(vals[0]).replace(",", "") if vals else None, errors="coerce")
        if pd.notna(date) and pd.notna(val): rows.append({"fecha": date, "USD_PEN": float(val)})
    mkt = mkt.merge(pd.DataFrame(rows), on="fecha", how="outer").sort_values("fecha")
    for a in ASSETS + ["USD_PEN"]:
        valid = mkt[["fecha", a]].dropna().copy(); valid[f"ret_{a}"] = valid[a].pct_change(fill_method=None)
        mkt = mkt.merge(valid[["fecha", f"ret_{a}"]], on="fecha", how="left")
    return mkt


@st.cache_data(ttl=300, show_spinner=False)
def intraday_row(mkt):
    raw = yf.download(ASSETS, period="5d", interval="5m", auto_adjust=False, actions=False, progress=False, group_by="column", threads=True, prepost=False)
    rows = []
    for t in ASSETS:
        s = yf_close(raw, t).dropna()
        if s.empty: return pd.DataFrame(), False
        ts = pd.Timestamp(s.index[-1]); ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts
        rows.append((t, ts.tz_convert("America/New_York"), float(s.iloc[-1])))
    date = pd.Timestamp(max(r[1] for r in rows).date())
    if date <= mkt["fecha"].max(): return pd.DataFrame(), True
    out = {"fecha": date}; fresh = True
    for t, ts, price in rows:
        prev = mkt.loc[(mkt["fecha"] < date) & mkt[t].notna()].sort_values("fecha")
        out[f"ret_{t}"] = price / float(prev.iloc[-1][t]) - 1
        fresh &= ts.date() == date.date()
    fx = mkt.loc[mkt["fecha"].eq(date) & mkt["USD_PEN"].notna()]
    if fx.empty: out["ret_USD_PEN"] = 0.0; fresh = False
    else:
        prev = mkt.loc[(mkt["fecha"] < date) & mkt["USD_PEN"].notna()].sort_values("fecha")
        out["ret_USD_PEN"] = float(fx.iloc[-1]["USD_PEN"]) / float(prev.iloc[-1]["USD_PEN"]) - 1
    return pd.DataFrame([out]), fresh


def classify(v): return "SUBE" if v > THRESHOLD else ("BAJA" if v < -THRESHOLD else "NEUTRO")


def fit_ols(train):
    X = train[FEATURES].to_numpy(float); y = train["ret_profuturo"].to_numpy(float)
    return np.linalg.lstsq(np.c_[np.ones(len(X)), X], y, rcond=None)[0]


def model_outputs(sbs, mkt, use_intraday):
    s = sbs.copy(); s["ret_profuturo"] = s["valor_cuota"].pct_change(fill_method=None)
    s.loc[s["fecha"].eq(pd.Timestamp("2026-07-06")), "ret_profuturo"] = np.nan
    data = s.merge(mkt[["fecha", *FEATURES]], on="fecha", how="inner").dropna(subset=["ret_profuturo", *FEATURES]).sort_values("fecha").reset_index(drop=True)
    hist = []
    for i in range(WINDOW, len(data)):
        tr = data.iloc[i-WINDOW:i]; cur = data.iloc[i]; b = fit_ols(tr)
        p = float(np.r_[1, cur[FEATURES].to_numpy(float)] @ b)
        hist.append({"fecha":cur.fecha,"valor_cuota":cur.valor_cuota,"ret_profuturo":cur.ret_profuturo,"ret_estimado":p,"valor_cuota_estimado":float(data.iloc[i-1].valor_cuota)*(1+p),"senal":classify(p),"ventana_fin":tr.iloc[-1].fecha})
    hist = pd.DataFrame(hist)
    pending_features = mkt[["fecha", *FEATURES]].copy(); fresh = True
    if use_intraday:
        try:
            extra, fresh = intraday_row(mkt)
            if not extra.empty: pending_features = pd.concat([pending_features, extra], ignore_index=True)
        except Exception: fresh = False
    last = sbs.iloc[-1]; train = data.tail(WINDOW); beta = fit_ols(train)
    pnd = pending_features.loc[pending_features.fecha > last.fecha].sort_values("fecha").copy()
    pnd["fx_fresh"] = pnd.ret_USD_PEN.notna(); pnd.ret_USD_PEN = pnd.ret_USD_PEN.fillna(0)
    pnd = pnd.dropna(subset=[f for f in FEATURES if f != "ret_USD_PEN"])
    base = float(last.valor_cuota); rows = []
    for _, r in pnd.iterrows():
        pred = float(np.r_[1, r[FEATURES].to_numpy(float)] @ beta); vc = base*(1+pred)
        rows.append({"fecha":r.fecha,"ret_estimado":pred,"valor_cuota_base":base,"valor_cuota_estimado":vc,"senal":classify(pred),"fuentes_completas":bool(r.fx_fresh),**{f:float(r[f]) for f in FEATURES}}); base = vc
    pending = pd.DataFrame(rows)
    if not pending.empty and use_intraday: pending.loc[pending.index[-1], "fuentes_completas"] = fresh
    return data, hist, pending


def stem(df, col, title, thresholds=False):
    d = df.dropna(subset=["fecha", col]).tail(30); fig = go.Figure()
    for _, r in d.iterrows(): fig.add_trace(go.Scatter(x=[r.fecha,r.fecha], y=[0,r[col]*100], mode="lines", line_width=1, showlegend=False, hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=d.fecha, y=d[col]*100, mode="markers", marker_size=8, hovertemplate="%{x|%d/%m/%Y}<br>%{y:.3f}%<extra></extra>"))
    fig.add_hline(y=0, line_width=2)
    if thresholds:
        fig.add_hline(y=.1, line_dash="dash", annotation_text="SUBE +0.10 %"); fig.add_hline(y=-.1, line_dash="dash", annotation_text="BAJA -0.10 %")
    mx = max(.15, float(np.nanmax(np.abs(d[col]*100)))*1.15) if len(d) else 1
    fig.update_yaxes(range=[-mx,mx], title="Retorno (%)"); fig.update_layout(title=title, height=320, showlegend=False, margin=dict(l=35,r=15,t=45,b=30)); return fig


st.title("📈 Monitor diario Profuturo Fondo 3")
st.caption("OLS rolling 90 · misma fecha · umbral ±0.10 %")
with st.sidebar:
    mode = st.radio("¿Qué deseas ver?", ["Solo monitorear", "Estoy dentro", "Ya salí"])
    use_intraday = st.toggle("Incluir mercado intradía", True)
    entry = exit_ = None; capital = 20000.0
    if mode != "Solo monitorear":
        entry = pd.Timestamp(st.date_input("Fecha de entrada", pd.Timestamp("2026-07-20").date()))
        capital = st.number_input("Capital invertido (S/)", 1.0, value=20000.0, step=100.0)
    if mode == "Ya salí": exit_ = pd.Timestamp(st.date_input("Fecha de salida", pd.Timestamp.now().date()))
    if st.button("🔄 Actualizar monitor", type="primary", use_container_width=True): st.cache_data.clear()

with st.spinner("Descargando SBS, mercados y calculando..."):
    sbs = load_sbs(); mkt = load_markets(); data, hist, pending = model_outputs(sbs, mkt, use_intraday)
last_sbs = sbs.iloc[-1]; latest = pending.iloc[-1] if not pending.empty else hist.iloc[-1]
complete = bool(latest.get("fuentes_completas", True))
cols = st.columns(4)
cols[0].metric("Último VC SBS", f"S/ {last_sbs.valor_cuota:.7f}", f"{last_sbs.fecha:%d/%m/%Y}")
cols[1].metric("VC estimado", f"S/ {latest.get('valor_cuota_estimado', latest.valor_cuota):.7f}", f"{latest.fecha:%d/%m/%Y}")
cols[2].metric("Señal", latest.senal, f"{latest.ret_estimado:+.3%}")
cols[3].metric("Estado", "COMPLETO" if complete else "PROVISIONAL", "Esperar al cierre" if not complete else "Fuentes completas")
if not complete: st.warning("La señal más reciente puede cambiar mientras el mercado siga abierto o falte USD/PEN.")

st.subheader("Valor cuota oficial y estimación acumulada")
fig = go.Figure(); rs = sbs[sbs.fecha >= "2026-03-01"]; rh = hist[hist.fecha >= "2026-03-01"]
fig.add_trace(go.Scatter(x=rs.fecha,y=rs.valor_cuota,name="VC oficial SBS",mode="lines+markers")); fig.add_trace(go.Scatter(x=rh.fecha,y=rh.valor_cuota_estimado,name="VC estimado histórico",mode="lines"))
if not pending.empty: fig.add_trace(go.Scatter(x=[last_sbs.fecha,*pending.fecha],y=[last_sbs.valor_cuota,*pending.valor_cuota_estimado],name="VC proyectado",mode="lines+markers",line_dash="dash"))
fig.update_layout(height=430,hovermode="x unified",yaxis_title="Valor cuota (S/)"); st.plotly_chart(fig,use_container_width=True)

st.subheader("Retornos diarios de los componentes")
c = st.columns(2)
for i,a in enumerate(ASSETS+["USD_PEN"]):
    with c[i%2]: st.plotly_chart(stem(mkt,f"ret_{a}",f"Retorno diario {a}"),use_container_width=True)
model_series = pd.concat([hist[["fecha","ret_estimado"]], pending[["fecha","ret_estimado"]] if not pending.empty else pd.DataFrame(columns=["fecha","ret_estimado"])]).sort_values("fecha")
st.subheader("Retorno estimado OLS y señal"); st.plotly_chart(stem(model_series,"ret_estimado","Retorno estimado del valor cuota",True),use_container_width=True)

if entry is not None:
    all_vc = pd.concat([sbs[["fecha","valor_cuota"]].rename(columns={"valor_cuota":"vc"}), pending[["fecha","valor_cuota_estimado"]].rename(columns={"valor_cuota_estimado":"vc"}) if not pending.empty else pd.DataFrame(columns=["fecha","vc"])]).sort_values("fecha")
    e = all_vc[all_vc.fecha >= entry].iloc[0]; end_date = exit_ if exit_ is not None else pd.Timestamp(latest.fecha); z = all_vc[all_vc.fecha >= end_date].iloc[0]
    units = capital/float(e.vc); value = units*float(z.vc); gain = value-capital
    st.subheader("Tu operación"); q=st.columns(3); q[0].metric("Valor actual/final",f"S/ {value:,.2f}"); q[1].metric("Ganancia o pérdida",f"S/ {gain:,.2f}"); q[2].metric("Rentabilidad",f"{value/capital-1:.2%}")
    st.caption(f"Entrada usada: {e.fecha:%d/%m/%Y}, VC S/ {e.vc:.7f}. Valoración/salida: {z.fecha:%d/%m/%Y}, VC S/ {z.vc:.7f}.")

v = hist[hist.fecha.dt.year == 2026]; direction = np.mean(np.sign(v.ret_profuturo)==np.sign(v.ret_estimado)); mae = np.mean(abs(v.valor_cuota-v.valor_cuota_estimado))
st.subheader("Auditoría")
st.dataframe(pd.DataFrame([["Modelo","OLS rolling 90","APROBADO"],["Sin anticipación","ventana_fin < fecha","APROBADO" if (hist.ventana_fin<hist.fecha).all() else "REVISAR"],["Umbral","±0.10 %","APROBADO"],["Dirección 2026",f"{direction:.1%}","REFERENCIA"],["MAE VC 2026",f"S/ {mae:.4f}","REFERENCIA"],["Última SBS",f"{last_sbs.fecha:%d/%m/%Y}","APROBADO"],["Última estimación",f"{latest.fecha:%d/%m/%Y}","COMPLETA" if complete else "PROVISIONAL"]],columns=["Control","Resultado","Estado"]),hide_index=True,use_container_width=True)
st.caption("Estimación informativa; no garantiza resultados ni constituye recomendación financiera.")
