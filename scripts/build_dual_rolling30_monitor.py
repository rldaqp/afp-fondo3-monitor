from __future__ import annotations

import json
import re
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "rolling90"
ANALYSIS = ROOT / "data" / "analysis"
PUBLIC = ROOT / "public" / "data"
OUT = PUBLIC / "dual_rolling30_monitor.json"
LIVE = PUBLIC / "live_market.json"
BACKTEST = ROOT / "analysis" / "backtest_blind3_rolling30_resid_newtickers.json"
ALT_BASE = ANALYSIS / "googlefinance_alt_6030_returns_20260303_20260820.csv"
ALT_LIVE = ANALYSIS / "googlefinance_alt_rolling30_live_returns.csv"
SHADOW = DATA / "dual_rolling30_shadow.csv"

TRAIN = 30
THRESHOLD = 0.001
LIMA = ZoneInfo("America/Lima")
QQQ_FEATURES = ["ret_SPY", "ret_EEM", "ret_EPU", "ret_MCHI", "ret_USD_PEN", "ret_QQQ"]
NEW_FEATURES = ["ret_.INX", "ret_CPER", "ret_EEM_alt", "ret_NDX", "ret_SPBLSCUP", "ret_USD_PEN_alt"]
BCRP_URL = "https://estadisticas.bcrp.gob.pe/estadisticas/series/api/PD04638PD/json"
MESES = {"ene":1,"feb":2,"mar":3,"abr":4,"may":5,"jun":6,"jul":7,"ago":8,"set":9,"sep":9,"oct":10,"nov":11,"dic":12}


def finite(v) -> bool:
    try:
        return v is not None and np.isfinite(float(v))
    except Exception:
        return False


def classify(v: float) -> str:
    return "SUBE" if v > THRESHOLD else ("BAJA" if v < -THRESHOLD else "NEUTRO")


def read_csv(path: Path) -> pd.DataFrame:
    d = pd.read_csv(path)
    d["fecha"] = pd.to_datetime(d["fecha"], errors="coerce").dt.normalize()
    return d.dropna(subset=["fecha"]).sort_values("fecha").drop_duplicates("fecha", keep="last").reset_index(drop=True)


def fit(train: pd.DataFrame, features: list[str]) -> tuple[np.ndarray, dict[str,float]]:
    X = train[features].to_numpy(float)
    y = train["ret_target"].to_numpy(float)
    beta = np.linalg.lstsq(np.c_[np.ones(len(X)), X], y, rcond=None)[0]
    return beta, {k: float(v) for k,v in zip(["intercept", *features], beta)}


def predict(beta: np.ndarray, row: pd.Series | dict, features: list[str]) -> float:
    vals = np.array([float(row[f]) for f in features], dtype=float)
    return float(np.r_[1.0, vals] @ beta)


def extract_close(raw: pd.DataFrame, ticker: str) -> pd.Series:
    if raw.empty:
        return pd.Series(dtype=float)
    if isinstance(raw.columns, pd.MultiIndex):
        for key in [("Close", ticker), (ticker, "Close")]:
            if key in raw.columns:
                return pd.to_numeric(raw[key], errors="coerce").dropna()
        if "Close" in raw.columns.get_level_values(0):
            b = raw.xs("Close", axis=1, level=0)
            if ticker in b.columns:
                return pd.to_numeric(b[ticker], errors="coerce").dropna()
    if "Close" in raw.columns:
        return pd.to_numeric(raw["Close"], errors="coerce").dropna()
    return pd.Series(dtype=float)


def load_qqq_daily(start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    raw = yf.download("QQQ", start=(start-pd.Timedelta(days=15)).strftime("%Y-%m-%d"), end=(end+pd.Timedelta(days=3)).strftime("%Y-%m-%d"), auto_adjust=False, actions=False, progress=False, threads=False)
    s = extract_close(raw, "QQQ")
    if s.empty:
        raise RuntimeError("No se pudo obtener QQQ diario")
    idx = pd.to_datetime(s.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    q = pd.DataFrame({"fecha": idx.normalize(), "QQQ": s.to_numpy(float)})
    q = q.sort_values("fecha").drop_duplicates("fecha", keep="last")
    q["ret_QQQ"] = q["QQQ"].pct_change(fill_method=None)
    return q.reset_index(drop=True)


def qqq_snapshot(signal_date: pd.Timestamp, qdaily: pd.DataFrame, market_open: bool) -> dict:
    prev = qdaily.loc[qdaily["fecha"] < signal_date].tail(1)
    if prev.empty:
        raise RuntimeError("QQQ no tiene cierre previo")
    prev_close = float(prev.iloc[-1]["QQQ"])
    same = qdaily.loc[qdaily["fecha"].eq(signal_date)]
    current = None
    stamp = signal_date.date().isoformat()
    source = None
    if market_open or same.empty:
        try:
            intr = yf.Ticker("QQQ").history(period="5d", interval="5m", auto_adjust=False, actions=False)
            if not intr.empty:
                idx = pd.to_datetime(intr.index)
                dates = pd.Series(idx.date, index=intr.index)
                rows = intr.loc[dates == signal_date.date()]
                if not rows.empty:
                    current = float(pd.to_numeric(rows["Close"], errors="coerce").dropna().iloc[-1])
                    stamp = str(rows.index[-1])
                    source = "YAHOO QQQ 5M · INTRADÍA"
        except Exception as exc:
            print("QQQ 5m no disponible:", type(exc).__name__, exc)
    if current is None and not same.empty:
        current = float(same.iloc[-1]["QQQ"])
        source = "YAHOO QQQ · CIERRE"
    if current is None:
        raise RuntimeError("No se pudo obtener QQQ de la sesión actual")
    return {"serie":"QQQ","ticker":"QQQ","timestamp":stamp,"precio_anterior":prev_close,"precio_actual":current,"retorno":current/prev_close-1.0,"retorno_modelo":current/prev_close-1.0,"estado":source,"usado_modelo":True}


def parse_bcrp_date(text: str) -> pd.Timestamp:
    s = str(text).lower().strip()
    m = re.search(r"(\d{1,2})[.\-/ ]+([a-záéíóú]+)[.\-/ ]+(\d{2,4})", s)
    if not m:
        return pd.NaT
    mon = m.group(2)[:3]
    for a,b in (("á","a"),("é","e"),("í","i"),("ó","o"),("ú","u")):
        mon = mon.replace(a,b)
    year = int(m.group(3)); year = year + 2000 if year < 100 else year
    month = MESES.get(mon)
    return pd.Timestamp(year, month, int(m.group(1))) if month else pd.NaT


def load_bcrp_returns() -> pd.DataFrame:
    try:
        r = requests.get(BCRP_URL, timeout=30, headers={"User-Agent":"Mozilla/5.0"})
        r.raise_for_status()
        rows=[]
        for p in r.json().get("periods",[]):
            d=parse_bcrp_date(p.get("name")); v=pd.to_numeric(pd.Series([(p.get("values") or [None])[0]]),errors="coerce").iloc[0]
            if pd.notna(d) and pd.notna(v): rows.append({"fecha":pd.Timestamp(d).normalize(),"USD_PEN_BCRP":float(v)})
        x=pd.DataFrame(rows).sort_values("fecha").drop_duplicates("fecha",keep="last")
        x["ret_USD_PEN_alt"]=x["USD_PEN_BCRP"].pct_change(fill_method=None)
        return x
    except Exception as exc:
        print("BCRP no disponible para extender nuevos tickers:", type(exc).__name__, exc)
        return pd.DataFrame(columns=["fecha","USD_PEN_BCRP","ret_USD_PEN_alt"])


def load_new_factors() -> pd.DataFrame:
    base = read_csv(ALT_BASE).rename(columns={"ret_EEM":"ret_EEM_alt","ret_USD_PEN":"ret_USD_PEN_alt"})
    for c in NEW_FEATURES:
        base[c]=pd.to_numeric(base[c],errors="coerce")
    base=base[["fecha",*NEW_FEATURES]].dropna(subset=NEW_FEATURES)
    if not ALT_LIVE.exists():
        return base.sort_values("fecha").drop_duplicates("fecha",keep="last").reset_index(drop=True)
    inc=read_csv(ALT_LIVE).rename(columns={"ret_EEM":"ret_EEM_alt"})
    inc_cols=["ret_.INX","ret_CPER","ret_EEM_alt","ret_NDX","ret_SPBLSCUP"]
    for c in inc_cols:
        inc[c]=pd.to_numeric(inc[c],errors="coerce")
    fx=load_bcrp_returns()[["fecha","ret_USD_PEN_alt"]]
    inc=inc[["fecha",*inc_cols]].merge(fx,on="fecha",how="left")
    inc=inc.dropna(subset=NEW_FEATURES)
    out=pd.concat([base,inc],ignore_index=True)
    return out.sort_values("fecha").drop_duplicates("fecha",keep="last").reset_index(drop=True)


def sbs_frame() -> pd.DataFrame:
    s=read_csv(DATA/"sbs_profuturo_f3.csv")
    s["valor_cuota"]=pd.to_numeric(s["valor_cuota"],errors="coerce")
    s=s.dropna(subset=["valor_cuota"]).copy()
    s["prev_vc"]=s["valor_cuota"].shift(1); s["prev_date"]=s["fecha"].shift(1); s["ret_target"]=s["valor_cuota"].pct_change(fill_method=None)
    return s


def build_common(sbs: pd.DataFrame, factors: pd.DataFrame, features: list[str]) -> pd.DataFrame:
    f=factors[["fecha",*features]].copy()
    for c in features: f[c]=pd.to_numeric(f[c],errors="coerce")
    common=sbs[["fecha","valor_cuota","prev_vc","prev_date","ret_target"]].merge(f,on="fecha",how="inner")
    return common.dropna(subset=["ret_target","prev_vc",*features]).sort_values("fecha").drop_duplicates("fecha",keep="last").reset_index(drop=True)


def one_step_history(common: pd.DataFrame, features: list[str], limit: int=140) -> list[dict]:
    rows=[]
    for i in range(TRAIN, len(common)):
        target=common.iloc[i]; train=common.iloc[max(0,i-TRAIN):i].copy()
        if len(train)!=TRAIN: continue
        beta,_=fit(train,features); rr=predict(beta,target,features); est=float(target["prev_vc"])*(1.0+rr); actual=float(target["valor_cuota"])
        rows.append({"fecha":pd.Timestamp(target["fecha"]).date().isoformat(),"base_date":pd.Timestamp(target["prev_date"]).date().isoformat(),"base_vc":float(target["prev_vc"]),"vc_estimated":est,"actual_vc":actual,"return_estimated":rr,"actual_return":actual/float(target["prev_vc"])-1.0,"signal":classify(rr),"error_pct":(est/actual-1.0)*100.0,"train_start":pd.Timestamp(train.iloc[0]["fecha"]).date().isoformat(),"train_end":pd.Timestamp(train.iloc[-1]["fecha"]).date().isoformat()})
    return rows[-limit:]


def history_metrics(rows: list[dict]) -> dict:
    if not rows: return {"n":0}
    e=np.array([r["vc_estimated"]-r["actual_vc"] for r in rows],dtype=float); a=np.array([r["actual_vc"] for r in rows],dtype=float)
    return {"n":len(rows),"mae_vc":float(np.mean(np.abs(e))),"rmse_vc":float(np.sqrt(np.mean(e**2))),"mape_pct":float(np.mean(np.abs(e/a))*100.0)}


def frozen_fallbacks(model_key: str, anchor_date: pd.Timestamp, signal_date: pd.Timestamp) -> dict[pd.Timestamp,dict]:
    if not SHADOW.exists():
        return {}
    try:
        d=pd.read_csv(SHADOW)
        d["fecha"]=pd.to_datetime(d["fecha"],errors="coerce").dt.normalize()
        frozen=d.get("frozen",False).astype(str).str.lower().isin({"true","1","yes"}) if "frozen" in d else pd.Series(False,index=d.index)
        x=d.loc[d["model_key"].astype(str).eq(model_key) & frozen & (d["fecha"]>anchor_date) & (d["fecha"]<=signal_date)].copy()
        x["vc_estimated"]=pd.to_numeric(x["vc_estimated"],errors="coerce")
        x["return_estimated"]=pd.to_numeric(x["return_estimated"],errors="coerce")
        x=x.dropna(subset=["fecha","vc_estimated"]).sort_values("fecha").drop_duplicates("fecha",keep="last")
        return {pd.Timestamp(r["fecha"]).normalize():r.to_dict() for _,r in x.iterrows()}
    except Exception as exc:
        print("Shadow fallback no disponible:",model_key,type(exc).__name__,exc); return {}


def forward_chain(common: pd.DataFrame, factors: pd.DataFrame, features: list[str], sbs: pd.DataFrame, signal_date: pd.Timestamp, model_key: str) -> tuple[list[dict],dict]:
    latest=sbs.iloc[-1]; anchor_date=pd.Timestamp(latest["fecha"]).normalize(); vc=float(latest["valor_cuota"])
    train=common.loc[common["fecha"]<=anchor_date].tail(TRAIN).copy()
    if len(train)!=TRAIN: raise RuntimeError(f"Train rolling30 incompleto al ancla {anchor_date.date()}: {len(train)}")
    beta,coeff=fit(train,features)
    hidden=factors.loc[(factors["fecha"]>anchor_date)&(factors["fecha"]<=signal_date),["fecha",*features]].dropna(subset=features).sort_values("fecha").drop_duplicates("fecha",keep="last")
    hmap={pd.Timestamp(r["fecha"]).normalize():r for _,r in hidden.iterrows()}
    fallbacks=frozen_fallbacks(model_key,anchor_date,signal_date)
    dates=sorted(set(hmap)|set(fallbacks))
    rows=[]; fallback_used=[]
    for d in dates:
        if d in hmap:
            r=hmap[d]; rr=predict(beta,r,features); base=vc; vc=base*(1.0+rr)
            rows.append({"fecha":d.date().isoformat(),"base_vc":base,"vc_estimated":vc,"return_estimated":rr,"signal":classify(rr),"actual_vc":None,"chain_source":"FACTORES SESIÓN"})
        else:
            fr=fallbacks[d]; base=vc; vc=float(fr["vc_estimated"]); rr=vc/base-1.0
            rows.append({"fecha":d.date().isoformat(),"base_vc":base,"vc_estimated":vc,"return_estimated":rr,"signal":classify(rr),"actual_vc":None,"chain_source":"PREDICCIÓN OPERACIONAL CONGELADA · FALLBACK CONTINUIDAD"})
            fallback_used.append(d.date().isoformat())
    if not rows and anchor_date==signal_date:
        hist=one_step_history(common,features,1)
        if hist: rows=[{**hist[-1],"actual_vc":float(latest["valor_cuota"]),"chain_source":"HISTÓRICO ONE-STEP"}]
    if not rows:
        rows=[{"fecha":signal_date.date().isoformat(),"base_vc":float(latest["valor_cuota"]),"vc_estimated":float(latest["valor_cuota"]),"return_estimated":0.0,"signal":"NEUTRO","actual_vc":float(latest["valor_cuota"]),"chain_source":"ANCLA SBS"}]
    meta={"anchor_date":anchor_date.date().isoformat(),"anchor_vc":float(latest["valor_cuota"]),"train_start":pd.Timestamp(train.iloc[0]["fecha"]).date().isoformat(),"train_end":pd.Timestamp(train.iloc[-1]["fecha"]).date().isoformat(),"train_n":len(train),"coefficients":coeff,"blind_chain_sessions":len(rows),"fallback_frozen_sessions":fallback_used}
    return rows,meta


def qqq_intraday_assets(live: dict, qqq: dict) -> list[dict]:
    wanted=["SPY","EEM","EPU","MCHI","USD_PEN"]; by={str(x.get("serie")):x for x in live.get("assets",[])}; out=[]
    for n in wanted:
        if n in by: out.append(by[n])
    out.append(qqq); return out


def new_intraday_values(live: dict, signal_date: pd.Timestamp, new_hist: pd.DataFrame) -> tuple[dict[str,float],list[dict]]:
    by={str(x.get("serie")):x for x in live.get("experimental_assets",[])}
    mapping={"ret_.INX":".INX","ret_CPER":"CPER","ret_EEM_alt":"EEM","ret_NDX":"NDX","ret_SPBLSCUP":"SPBLSCUP","ret_USD_PEN_alt":"USD/PEN"}
    vals={}; assets=[]; hist_same=new_hist.loc[new_hist["fecha"].eq(signal_date)]
    for f,n in mapping.items():
        row=dict(by.get(n,{"serie":n})); raw=row.get("retorno_modelo") if row.get("retorno_modelo") is not None else row.get("retorno")
        if not finite(raw) and not hist_same.empty and finite(hist_same.iloc[-1].get(f)):
            raw=float(hist_same.iloc[-1][f]); row["retorno"]=raw; row["retorno_modelo"]=raw; row["estado"]="HISTÓRICO EXACTO · SESIÓN CERRADA"
        if not finite(raw): raise RuntimeError(f"Falta {n} para rolling30 nuevos tickers")
        vals[f]=float(raw); assets.append(row)
    return vals,assets


def extend_with_live(factors: pd.DataFrame, signal_date: pd.Timestamp, values: dict[str,float], features:list[str]) -> pd.DataFrame:
    row={"fecha":signal_date,**values}; x=pd.concat([factors,pd.DataFrame([row])],ignore_index=True)
    for c in features: x[c]=pd.to_numeric(x[c],errors="coerce")
    return x.sort_values("fecha").drop_duplicates("fecha",keep="last").reset_index(drop=True)


def load_blind3() -> dict:
    if not BACKTEST.exists(): return {}
    try:
        b=json.loads(BACKTEST.read_text(encoding="utf-8")); common=b.get("common_exact_comparison",{}).get("3",{}); full=b.get("full_six_month_residual",{}).get("3",{})
        return {"rule":b.get("blind_rule"),"common_period":{"start":common.get("date_start"),"end":common.get("date_end")},"qqq_common":common.get("raw_qqq",{}),"new_tickers_common":common.get("new_tickers",{}),"qqq_full_six_month":full.get("raw_qqq",{}),"pairwise":common.get("pairwise",{})}
    except Exception as exc:
        print("Backtest ciego no disponible:",exc); return {}


def main() -> None:
    live=json.loads(LIVE.read_text(encoding="utf-8")); signal_date=pd.Timestamp(str(live.get("signal_date"))).normalize(); sbs=sbs_frame(); latest_sbs=sbs.iloc[-1]
    markets=read_csv(DATA/"markets.csv"); qdaily=load_qqq_daily(markets["fecha"].min(),signal_date); qqq_now=qqq_snapshot(signal_date,qdaily,bool(live.get("market_open")))
    qf=markets.merge(qdaily[["fecha","ret_QQQ"]],on="fecha",how="left")[["fecha",*QQQ_FEATURES]].copy()
    for c in QQQ_FEATURES: qf[c]=pd.to_numeric(qf[c],errors="coerce")
    qf=qf.dropna(subset=QQQ_FEATURES).sort_values("fecha").drop_duplicates("fecha",keep="last").reset_index(drop=True)
    qlive={}; lby={str(x.get("serie")):x for x in live.get("assets",[])}
    for f,n in {"ret_SPY":"SPY","ret_EEM":"EEM","ret_EPU":"EPU","ret_MCHI":"MCHI","ret_USD_PEN":"USD_PEN"}.items():
        r=lby.get(n,{}); raw=r.get("retorno_modelo") if r.get("retorno_modelo") is not None else r.get("retorno")
        if not finite(raw): raise RuntimeError(f"Falta {n} en live_market")
        qlive[f]=float(raw)
    qlive["ret_QQQ"]=float(qqq_now["retorno"]); qf_live=extend_with_live(qf,signal_date,qlive,QQQ_FEATURES); qcommon=build_common(sbs,qf,QQQ_FEATURES)

    nf=load_new_factors(); nlive,nassets=new_intraday_values(live,signal_date,nf); nf_live=extend_with_live(nf,signal_date,nlive,NEW_FEATURES); ncommon=build_common(sbs,nf,NEW_FEATURES)
    qhist=one_step_history(qcommon,QQQ_FEATURES); nhist=one_step_history(ncommon,NEW_FEATURES)
    qforward,qmeta=forward_chain(qcommon,qf_live,QQQ_FEATURES,sbs,signal_date,"qqq"); nforward,nmeta=forward_chain(ncommon,nf_live,NEW_FEATURES,sbs,signal_date,"new_tickers")
    blind=load_blind3(); qcur={**qforward[-1],**qmeta}; ncur={**nforward[-1],**nmeta}
    qm=blind.get("qqq_common",{}); nm=blind.get("new_tickers_common",{}); winner="—"
    if finite(qm.get("mape_pct")) and finite(nm.get("mape_pct")): winner="NUEVOS TICKERS" if float(nm["mape_pct"])<float(qm["mape_pct"]) else "QQQ"
    payload={"generated_at_lima":pd.Timestamp.now(tz=LIMA).isoformat(),"fund":"PROFUTURO Fondo 3","signal_date":signal_date.date().isoformat(),"market_mode":live.get("mode"),"market_open":bool(live.get("market_open")),"latest_sbs":{"fecha":pd.Timestamp(latest_sbs["fecha"]).date().isoformat(),"vc":float(latest_sbs["valor_cuota"])},"rule":"Solo quedan dos modelos visibles. Ambos son OLS rolling 30 y se recalibran con las últimas 30 observaciones conocidas. Si SBS está atrasada, se encadenan los días faltantes sin usar los VC ocultos; cuando SBS publica, el siguiente cálculo vuelve a anclarse automáticamente al VC real. Si falta una fila de factores de una sesión ya congelada, se conserva la predicción operacional congelada de esa sesión como puente y nunca se salta el día.","models":{"qqq":{"key":"qqq","name":"Rolling 30 · QQQ","short":"QQQ","features_display":["SPY","EEM","EPU","MCHI","USD/PEN","QQQ"],"features":QQQ_FEATURES,"current":qcur,"forward_chain":qforward,"history_one_step":qhist,"history_metrics":history_metrics(qhist),"intraday_assets":qqq_intraday_assets(live,qqq_now),"source_note":"SPY/EEM/EPU/MCHI y QQQ: Yahoo Finance; USD/PEN se normaliza después con la regla BCRP/TuCambista común."},"new_tickers":{"key":"new_tickers","name":"Rolling 30 · nuevos tickers","short":"Nuevos tickers","features_display":[".INX","CPER","EEM","NDX","SPBLSCUP","USD/PEN"],"features":NEW_FEATURES,"current":ncur,"forward_chain":nforward,"history_one_step":nhist,"history_metrics":history_metrics(nhist),"intraday_assets":nassets,"source_note":"Histórico: retornos exactos guardados/validados para .INX, CPER, EEM, NDX y SPBLSCUP; USD/PEN se normaliza después con la regla BCRP/TuCambista común."}},"blind3":blind,"comparison":{"winner_blind3_mape":winner,"vc_difference":float(ncur["vc_estimated"])-float(qcur["vc_estimated"]),"return_difference":float(ncur["return_estimated"])-float(qcur["return_estimated"])}}
    OUT.parent.mkdir(parents=True,exist_ok=True); OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"signal_date":payload["signal_date"],"latest_sbs":payload["latest_sbs"],"qqq":qcur,"new_tickers":ncur,"winner":winner},ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
