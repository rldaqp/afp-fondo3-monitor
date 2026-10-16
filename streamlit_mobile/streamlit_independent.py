from __future__ import annotations

import io
import re
import time as time_module
import unicodedata
from datetime import datetime, time
from pathlib import Path
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
from bs4 import BeautifulSoup

# -----------------------------------------------------------------------------
# CONFIGURACIÓN DEL MODELO
# -----------------------------------------------------------------------------
ASSETS = ["SPY", "NEM", "FCX", "EPU", "MCHI"]
STOOQ_SYMBOLS = {
    "SPY": "spy.us",
    "NEM": "nem.us",
    "FCX": "fcx.us",
    "EPU": "epu.us",
    "MCHI": "mchi.us",
}
FEATURES = [f"ret_{ticker}" for ticker in ASSETS] + ["ret_USD_PEN"]
WINDOW = 90
THRESHOLD = 0.001
START_DATE = pd.Timestamp("2024-12-31")
LIMA = ZoneInfo("America/Lima")
NY = ZoneInfo("America/New_York")

SBS_INDEX = (
    "https://www.sbs.gob.pe/app/stats/"
    "EstadisticaSistemaFinancieroResultados.asp?c=FP-1359"
)
SBS_DAILY = (
    "https://www.sbs.gob.pe/app/spp/variablesSPP_net/"
    "PagSS/variables_spp.aspx"
)
BCRP = "https://estadisticas.bcrp.gob.pe/estadisticas/series/api/PD04646PD/json"
UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/126 Safari/537.36"
    )
}

HERE = Path(__file__).resolve().parent
SBS_FALLBACK = HERE / "data" / "sbs_profuturo_f3_fallback.csv"


def norm(value) -> str:
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(text.lower().split())


def parse_num(value):
    number = pd.to_numeric(
        str(value).replace("\xa0", "").replace(" ", "").replace(",", ""),
        errors="coerce",
    )
    return None if pd.isna(number) else float(number)


def parse_bcrp_date(value):
    match = re.search(
        r"(\d{1,2})[.\-/ ]+([A-Za-zÁÉÍÓÚáéíóú]{3,5})[.\-/ ]+(\d{2,4})",
        str(value),
    )
    if not match:
        return pd.NaT
    day, month_text, year = match.groups()
    month_text = norm(month_text)
    month = {
        "ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
        "jul": 7, "ago": 8, "set": 9, "sep": 9, "sept": 9,
        "oct": 10, "nov": 11, "dic": 12,
    }.get(month_text)
    if not month:
        return pd.NaT
    year_number = int(year)
    if year_number < 100:
        year_number += 2000
    try:
        return pd.Timestamp(year_number, month, int(day))
    except ValueError:
        return pd.NaT


@st.cache_data(ttl=3600, show_spinner=False)
def load_sbs_independent() -> tuple[pd.DataFrame, str]:
    """Descarga SBS directamente. El respaldo solo se usa si la SBS falla."""
    session = requests.Session()
    session.headers.update(UA)
    frames: list[pd.DataFrame] = []
    online_ok = False
    errors: list[str] = []

    try:
        response = session.get(SBS_INDEX, timeout=45)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "lxml")
        links = []
        for anchor in soup.find_all("a", href=True):
            url = urljoin(SBS_INDEX, anchor["href"])
            if (
                "FP-1359" in url.upper()
                and url.lower().endswith(".xls")
                and re.search(r"202[5-9]", url)
            ):
                links.append(url)

        for url in sorted(set(links)):
            try:
                file_response = session.get(url, timeout=60)
                file_response.raise_for_status()
                raw = pd.read_excel(
                    io.BytesIO(file_response.content),
                    sheet_name="VC-Diario-Fondo3",
                    header=None,
                    engine="xlrd",
                )
                header_row = next(
                    i
                    for i in range(min(20, len(raw)))
                    if "dia" in [norm(v) for v in raw.iloc[i]]
                    and "profuturo" in [norm(v) for v in raw.iloc[i]]
                )
                header = [norm(v) for v in raw.iloc[header_row]]
                data = raw.iloc[
                    header_row + 1 :,
                    [header.index("dia"), header.index("profuturo")],
                ].copy()
                data.columns = ["fecha", "valor_cuota"]
                data["fecha"] = pd.to_datetime(data["fecha"], errors="coerce")
                data["valor_cuota"] = pd.to_numeric(
                    data["valor_cuota"], errors="coerce"
                )
                frames.append(data.dropna())
            except Exception as error:
                errors.append(f"XLS SBS: {type(error).__name__}")

        if frames:
            online_ok = True
    except Exception as error:
        errors.append(f"Índice SBS: {type(error).__name__}")

    if SBS_FALLBACK.exists():
        fallback = pd.read_csv(SBS_FALLBACK, encoding="utf-8-sig")
        fallback["fecha"] = pd.to_datetime(fallback["fecha"], errors="coerce")
        fallback["valor_cuota"] = pd.to_numeric(
            fallback["valor_cuota"], errors="coerce"
        )
        frames.insert(0, fallback.dropna(subset=["fecha", "valor_cuota"]))

    if not frames:
        raise RuntimeError("No se pudo obtener SBS ni existe respaldo local.")

    sbs = (
        pd.concat(frames, ignore_index=True)
        .sort_values("fecha")
        .drop_duplicates("fecha", keep="last")
        .reset_index(drop=True)
    )

    # Página diaria de SBS para completar publicaciones recientes.
    try:
        page = session.get(SBS_DAILY, timeout=40)
        page.raise_for_status()
        soup = BeautifulSoup(page.content, "lxml")
        dates = []
        for node in soup.find_all(string=True):
            text = " ".join(str(node).split())
            if "informacion al" in norm(text):
                match = re.search(r"\d{2}/\d{2}/\d{4}", text)
                if match:
                    dates.append(pd.to_datetime(match.group(), format="%d/%m/%Y"))
        values = []
        for table in soup.find_all("table"):
            for row in table.find_all("tr"):
                cells = row.find_all(["th", "td"], recursive=False)
                texts = [" ".join(cell.get_text(" ", strip=True).split()) for cell in cells]
                if texts and norm(texts[0]) == "profuturo" and len(texts) >= 10:
                    value = parse_num(texts[9])
                    if value is not None:
                        values.append(value)
        dates = list(dict.fromkeys(dates))
        if len(dates) == len(values) and dates:
            recent = pd.DataFrame({"fecha": dates, "valor_cuota": values})
            sbs = (
                pd.concat([sbs, recent], ignore_index=True)
                .sort_values("fecha")
                .drop_duplicates("fecha", keep="last")
                .reset_index(drop=True)
            )
            online_ok = True
    except Exception as error:
        errors.append(f"SBS diaria: {type(error).__name__}")

    source = "SBS EN LÍNEA" if online_ok else "RESPALDO SBS"
    detail = " · ".join(errors[-3:]) if errors else ""
    return sbs, source + (f" · {detail}" if detail else "")


def _get_text_with_retry(url: str, attempts: int = 3) -> str:
    last_error = None
    for attempt in range(attempts):
        try:
            response = requests.get(url, headers=UA, timeout=35)
            response.raise_for_status()
            text = response.text.strip()
            if text:
                return text
        except Exception as error:
            last_error = error
            if attempt + 1 < attempts:
                time_module.sleep(0.8 * (attempt + 1))
    raise RuntimeError(f"No respondió {url}: {type(last_error).__name__}")


@st.cache_data(ttl=1800, show_spinner=False)
def load_stooq_daily(ticker: str) -> pd.DataFrame:
    symbol = STOOQ_SYMBOLS[ticker]
    start = START_DATE.strftime("%Y%m%d")
    end = pd.Timestamp.now(tz="America/Lima").strftime("%Y%m%d")
    url = (
        "https://stooq.com/q/d/l/"
        f"?s={symbol}&d1={start}&d2={end}&i=d"
    )
    text = _get_text_with_retry(url)
    frame = pd.read_csv(io.StringIO(text))
    if frame.empty or "Date" not in frame.columns or "Close" not in frame.columns:
        raise RuntimeError(f"Stooq devolvió datos inválidos para {ticker}.")
    result = frame[["Date", "Close"]].copy()
    result.columns = ["fecha", ticker]
    result["fecha"] = pd.to_datetime(result["fecha"], errors="coerce")
    result[ticker] = pd.to_numeric(result[ticker], errors="coerce")
    return result.dropna().sort_values("fecha").drop_duplicates("fecha", keep="last")


@st.cache_data(ttl=900, show_spinner=False)
def load_stooq_quote(ticker: str) -> dict | None:
    symbol = STOOQ_SYMBOLS[ticker]
    url = f"https://stooq.com/q/l/?s={symbol}&f=sd2t2ohlcv&h&e=csv"
    try:
        text = _get_text_with_retry(url, attempts=2)
        frame = pd.read_csv(io.StringIO(text))
        if frame.empty:
            return None
        row = frame.iloc[0]
        close = pd.to_numeric(row.get("Close"), errors="coerce")
        date_value = pd.to_datetime(row.get("Date"), errors="coerce")
        if pd.isna(close) or pd.isna(date_value):
            return None
        return {"fecha": pd.Timestamp(date_value).normalize(), "precio": float(close)}
    except Exception:
        return None


@st.cache_data(ttl=1800, show_spinner=False)
def load_bcrp_independent() -> pd.DataFrame:
    today = pd.Timestamp.now(tz="America/Lima").tz_localize(None).normalize()
    start = START_DATE
    fmt = lambda d: f"{d.year}-{d.month}-{d.day}"
    url = f"{BCRP}/{fmt(start)}/{fmt(today)}/esp"
    response = requests.get(url, timeout=40, headers=UA)
    response.raise_for_status()
    payload = response.json()
    rows = []
    for period in payload.get("periods", []):
        date_value = parse_bcrp_date(period.get("name"))
        values = period.get("values", [])
        number = pd.to_numeric(
            str(values[0]).replace(",", "") if values else None,
            errors="coerce",
        )
        if pd.notna(date_value) and pd.notna(number):
            rows.append({"fecha": date_value, "USD_PEN": float(number)})
    if not rows:
        raise RuntimeError("BCRP no devolvió USD/PEN.")
    return pd.DataFrame(rows).sort_values("fecha").drop_duplicates("fecha", keep="last")


@st.cache_data(ttl=1800, show_spinner=False)
def load_markets_independent() -> tuple[pd.DataFrame, dict]:
    """Recolecta índices y USD/PEN sin usar ningún archivo del notebook."""
    frames = []
    status = {}
    for ticker in ASSETS:
        frame = load_stooq_daily(ticker)
        frames.append(frame)
        status[ticker] = {
            "fuente": "STOOQ",
            "fecha": frame["fecha"].max().strftime("%Y-%m-%d"),
        }

    market = frames[0]
    for frame in frames[1:]:
        market = market.merge(frame, on="fecha", how="outer")

    fx = load_bcrp_independent()
    market = market.merge(fx, on="fecha", how="outer").sort_values("fecha")
    status["USD_PEN"] = {
        "fuente": "BCRP",
        "fecha": fx["fecha"].max().strftime("%Y-%m-%d"),
    }

    for variable in ASSETS + ["USD_PEN"]:
        valid = market[["fecha", variable]].dropna().copy()
        valid[f"ret_{variable}"] = valid[variable].pct_change(fill_method=None)
        market = market.merge(
            valid[["fecha", f"ret_{variable}"]],
            on="fecha",
            how="left",
        )

    return market.reset_index(drop=True), status


def market_clock(mode: str) -> tuple[bool, str, datetime, datetime]:
    now_lima = datetime.now(LIMA)
    now_ny = now_lima.astimezone(NY)
    open_now = (
        now_ny.weekday() < 5
        and time(9, 30) <= now_ny.time() < time(16, 10)
    )
    close_lima = now_ny.replace(
        hour=16, minute=0, second=0, microsecond=0
    ).astimezone(LIMA)
    if mode == "Ya salí":
        return False, "CIERRES DIARIOS", now_lima, close_lima
    return (
        (True, "INTRADÍA PROVISIONAL", now_lima, close_lima)
        if open_now
        else (False, "CIERRES DIARIOS", now_lima, close_lima)
    )


def add_intraday_if_available(
    market: pd.DataFrame,
    status: dict,
) -> tuple[pd.DataFrame, bool]:
    rows = []
    complete = True
    for ticker in ASSETS:
        quote = load_stooq_quote(ticker)
        if quote is None:
            complete = False
            continue
        rows.append((ticker, quote["fecha"], quote["precio"]))

    if len(rows) != len(ASSETS):
        return market, False

    target_date = max(row[1] for row in rows)
    if target_date <= market["fecha"].max():
        return market, complete

    new_row = {"fecha": target_date}
    for ticker, quote_date, price in rows:
        previous = market.loc[
            (market["fecha"] < target_date) & market[ticker].notna()
        ].sort_values("fecha")
        if previous.empty:
            return market, False
        new_row[ticker] = price
        new_row[f"ret_{ticker}"] = price / float(previous.iloc[-1][ticker]) - 1
        complete &= quote_date == target_date
        status[ticker] = {"fuente": "STOOQ INTRADÍA", "fecha": str(target_date.date())}

    fx_today = market.loc[
        market["fecha"].eq(target_date) & market["USD_PEN"].notna()
    ]
    if fx_today.empty:
        new_row["ret_USD_PEN"] = 0.0
        complete = False
    else:
        previous_fx = market.loc[
            (market["fecha"] < target_date) & market["USD_PEN"].notna()
        ].sort_values("fecha")
        new_row["USD_PEN"] = float(fx_today.iloc[-1]["USD_PEN"])
        new_row["ret_USD_PEN"] = (
            float(fx_today.iloc[-1]["USD_PEN"])
            / float(previous_fx.iloc[-1]["USD_PEN"])
            - 1
        )

    augmented = pd.concat([market, pd.DataFrame([new_row])], ignore_index=True)
    return augmented.sort_values("fecha").reset_index(drop=True), complete


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


def model_outputs(
    sbs: pd.DataFrame,
    market: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    s = sbs.copy()
    s["ret_profuturo"] = s["valor_cuota"].pct_change(fill_method=None)
    # Fecha no comparable por el salto observado en la fuente original.
    s.loc[s["fecha"].eq(pd.Timestamp("2026-07-06")), "ret_profuturo"] = np.nan

    data = (
        s.merge(market[["fecha", *FEATURES]], on="fecha", how="inner")
        .dropna(subset=["ret_profuturo", *FEATURES])
        .sort_values("fecha")
        .reset_index(drop=True)
    )
    if len(data) <= WINDOW:
        raise RuntimeError(
            f"Solo hay {len(data)} observaciones completas; se necesitan más de {WINDOW}."
        )

    historical = []
    for i in range(WINDOW, len(data)):
        train = data.iloc[i - WINDOW : i]
        current = data.iloc[i]
        beta = fit_ols(train)
        prediction = float(
            np.r_[1.0, current[FEATURES].to_numpy(float)] @ beta
        )
        historical.append(
            {
                "fecha": current.fecha,
                "valor_cuota": current.valor_cuota,
                "ret_profuturo": current.ret_profuturo,
                "ret_estimado": prediction,
                "senal": classify(prediction),
                "ventana_fin": train.iloc[-1].fecha,
            }
        )
    historical = pd.DataFrame(historical)

    last_sbs_date = pd.Timestamp(sbs["fecha"].max())
    pending_features = (
        market.loc[market["fecha"] > last_sbs_date, ["fecha", *FEATURES]]
        .dropna(subset=FEATURES)
        .sort_values("fecha")
        .reset_index(drop=True)
    )

    pending = []
    vc_base = float(sbs.sort_values("fecha").iloc[-1]["valor_cuota"])
    training = data.tail(WINDOW)
    beta = fit_ols(training)

    for _, row in pending_features.iterrows():
        prediction = float(np.r_[1.0, row[FEATURES].to_numpy(float)] @ beta)
        vc_estimated = vc_base * (1 + prediction)
        pending.append(
            {
                "fecha": row.fecha,
                "valor_cuota_base": vc_base,
                "ret_estimado": prediction,
                "valor_cuota_estimado": vc_estimated,
                "senal": classify(prediction),
                "ventana_fin": training.iloc[-1].fecha,
            }
        )
        vc_base = vc_estimated

    return historical, pd.DataFrame(pending)


def first_on_or_after(frame: pd.DataFrame, requested: pd.Timestamp):
    rows = frame.loc[frame["fecha"] >= requested].sort_values("fecha")
    return None if rows.empty else rows.iloc[0]


def last_on_or_before(frame: pd.DataFrame, requested: pd.Timestamp):
    rows = frame.loc[frame["fecha"] <= requested].sort_values("fecha")
    return None if rows.empty else rows.iloc[-1]


def source_name(row: pd.Series) -> str:
    return "SBS OFICIAL" if row["fuente"] == "SBS" else "MODELO OLS"


def stem_chart(frame: pd.DataFrame) -> go.Figure:
    data = frame.dropna(subset=["fecha", "ret_estimado"]).tail(90).copy()
    x_lines, y_lines = [], []
    for _, row in data.iterrows():
        x_lines.extend([row.fecha, row.fecha, None])
        y_lines.extend([0, row.ret_estimado * 100, None])
    figure = go.Figure()
    figure.add_trace(
        go.Scatter(
            x=x_lines, y=y_lines, mode="lines", showlegend=False,
            hoverinfo="skip", line={"width": 1.2},
        )
    )
    figure.add_trace(
        go.Scatter(
            x=data.fecha,
            y=data.ret_estimado * 100,
            mode="markers",
            name="Retorno estimado",
            customdata=data[["senal"]].to_numpy(),
            hovertemplate=(
                "<b>%{x|%d/%m/%Y}</b><br>Retorno: %{y:+.4f}%<br>"
                "Señal: %{customdata[0]}<extra></extra>"
            ),
        )
    )
    figure.add_hline(y=0, line_width=1)
    figure.update_layout(
        title="Retorno diario estimado del valor cuota",
        height=420,
        yaxis={"title": "Retorno (%)", "ticksuffix": "%"},
        xaxis={"title": "Fecha"},
        margin={"l": 55, "r": 25, "t": 55, "b": 55},
    )
    return figure


def signal_band(history: pd.DataFrame, pending: pd.DataFrame) -> go.Figure:
    frames = [history[["fecha", "senal", "ret_estimado"]].assign(fuente="SBS")]
    if not pending.empty:
        frames.append(
            pending[["fecha", "senal", "ret_estimado"]].assign(fuente="MODELO")
        )
    data = (
        pd.concat(frames, ignore_index=True)
        .sort_values("fecha")
        .drop_duplicates("fecha", keep="last")
    )
    data = data.loc[data.senal.isin(["SUBE", "NEUTRO", "BAJA"])].tail(120)
    numeric = data.senal.map({"BAJA": -1, "NEUTRO": 0, "SUBE": 1})
    colors = [
        [0.00, "#ef4444"], [0.2499, "#ef4444"],
        [0.25, "#f59e0b"], [0.7499, "#f59e0b"],
        [0.75, "#22c55e"], [1.00, "#22c55e"],
    ]
    figure = go.Figure(
        go.Heatmap(
            z=[numeric.tolist()],
            x=data.fecha,
            y=["Señal"],
            zmin=-1,
            zmax=1,
            colorscale=colors,
            xgap=1.5,
            customdata=np.array(
                [data[["senal", "ret_estimado", "fuente"]].to_numpy()],
                dtype=object,
            ),
            hovertemplate=(
                "<b>%{x|%d/%m/%Y}</b><br>Señal: %{customdata[0]}<br>"
                "Retorno: %{customdata[1]:+.3%}<br>Fuente: %{customdata[2]}"
                "<extra></extra>"
            ),
            colorbar={
                "tickvals": [-1, 0, 1],
                "ticktext": ["BAJA", "NEUTRO", "SUBE"],
                "orientation": "h",
                "y": -0.55,
                "len": 0.65,
            },
        )
    )
    figure.update_layout(
        title="Historial de señales",
        height=270,
        margin={"l": 20, "r": 20, "t": 50, "b": 90},
        yaxis={"showticklabels": False, "fixedrange": True},
    )
    return figure


# -----------------------------------------------------------------------------
# APLICACIÓN STREAMLIT AUTÓNOMA
# -----------------------------------------------------------------------------
st.title("Monitor diario Profuturo Fondo 3")
st.caption(
    "Aplicación autónoma · descarga sus propios datos · OLS rolling 90 · "
    f"umbral ±{THRESHOLD:.2%}"
)

mode = st.radio(
    "¿Qué deseas hacer?",
    ["Solo monitorear", "Sigo dentro", "Ya salí"],
)
use_intraday, temporal_mode, now_lima, close_lima = market_clock(mode)

status_cols = st.columns(3)
status_cols[0].metric("Modo de mercado", temporal_mode)
status_cols[1].metric("Hora Lima", now_lima.strftime("%d/%m %H:%M"))
status_cols[2].metric("Cierre EE. UU.", close_lima.strftime("%H:%M"))

if mode == "Ya salí":
    st.info("Operación cerrada: solo se usan cierres diarios.")
elif use_intraday:
    st.warning("Mercado abierto: la última estimación puede ser provisional.")
else:
    st.success("Mercado cerrado: se utilizan cierres diarios disponibles.")

if st.button(
    "Actualizar SBS, índices, dólar y modelo",
    type="primary",
    use_container_width=True,
):
    st.cache_data.clear()
    st.rerun()

with st.spinner("Descargando SBS, Stooq y BCRP; entrenando OLS rolling 90..."):
    try:
        sbs, sbs_source = load_sbs_independent()
        market, source_status = load_markets_independent()
        intraday_complete = True
        if use_intraday:
            market, intraday_complete = add_intraday_if_available(
                market, source_status
            )
        history, pending = model_outputs(sbs, market)
    except Exception as error:
        st.error("No se pudo completar la actualización independiente.")
        st.exception(error)
        st.stop()

last_sbs = sbs.sort_values("fecha").iloc[-1]
if not pending.empty:
    latest = pending.iloc[-1]
    latest_vc = float(latest.valor_cuota_estimado)
    latest_source = "MODELO OLS"
else:
    latest = history.iloc[-1]
    latest_vc = float(latest.valor_cuota)
    latest_source = "SBS"

cards = st.columns(4)
cards[0].metric(
    "Último VC SBS",
    f"{float(last_sbs.valor_cuota):.7f}",
    f"{last_sbs.fecha:%d/%m/%Y}",
)
cards[1].metric(
    "VC más reciente",
    f"{latest_vc:.7f}",
    f"{latest.fecha:%d/%m/%Y}",
)
cards[2].metric(
    "Señal",
    str(latest.senal),
    f"{float(latest.ret_estimado):+.3%}",
)
cards[3].metric(
    "Fuente VC",
    latest_source,
    "PROVISIONAL" if latest_source != "SBS" else "OFICIAL",
)

st.caption(
    f"SBS: {sbs_source} · Índices: Stooq · USD/PEN: BCRP · "
    f"Intradiario completo: {'sí' if intraday_complete else 'no'}"
)

all_vc = pd.concat(
    [
        sbs[["fecha", "valor_cuota"]]
        .rename(columns={"valor_cuota": "vc"})
        .assign(fuente="SBS"),
        (
            pending[["fecha", "valor_cuota_estimado"]]
            .rename(columns={"valor_cuota_estimado": "vc"})
            .assign(fuente="MODELO OLS")
            if not pending.empty
            else pd.DataFrame(columns=["fecha", "vc", "fuente"])
        ),
    ],
    ignore_index=True,
)
all_vc["fecha"] = pd.to_datetime(all_vc["fecha"], errors="coerce").dt.normalize()
all_vc["vc"] = pd.to_numeric(all_vc["vc"], errors="coerce")
all_vc = (
    all_vc.dropna(subset=["fecha", "vc"])
    .sort_values("fecha")
    .drop_duplicates("fecha", keep="last")
    .reset_index(drop=True)
)

if mode != "Solo monitorear":
    st.subheader("Tu operación")
    min_date = all_vc.fecha.min().date()
    max_date = all_vc.fecha.max().date()
    default_entry = min(
        max(pd.Timestamp("2026-07-20").date(), min_date),
        max_date,
    )

    with st.form("operation_form"):
        entry_requested = pd.Timestamp(
            st.date_input(
                "Fecha de entrada",
                default_entry,
                min_value=min_date,
                max_value=max_date,
            )
        )
        capital = st.number_input(
            "Capital invertido (S/)",
            min_value=1.0,
            value=20000.0,
            step=100.0,
        )
        if mode == "Ya salí":
            exit_requested = pd.Timestamp(
                st.date_input(
                    "Fecha de salida",
                    max_date,
                    min_value=entry_requested.date(),
                    max_value=max_date,
                )
            )
        else:
            exit_requested = pd.Timestamp(all_vc.fecha.max())
            st.write(f"Posición valorada al {exit_requested:%d/%m/%Y}.")

        calculate = st.form_submit_button(
            "Calcular",
            type="primary",
            use_container_width=True,
        )

    if calculate:
        entry = first_on_or_after(all_vc, entry_requested)
        exit_row = last_on_or_before(all_vc, exit_requested)
        if entry is None or exit_row is None:
            st.error("No hay valor cuota disponible para ese período.")
        elif exit_row.fecha < entry.fecha:
            st.error("La fecha efectiva de salida es anterior a la entrada.")
        else:
            units = float(capital) / float(entry.vc)
            final_value = units * float(exit_row.vc)
            st.session_state["operation_result"] = {
                "mode": mode,
                "entry_req": entry_requested,
                "exit_req": exit_requested,
                "entry_date": pd.Timestamp(entry.fecha),
                "exit_date": pd.Timestamp(exit_row.fecha),
                "entry_vc": float(entry.vc),
                "exit_vc": float(exit_row.vc),
                "entry_source": source_name(entry),
                "exit_source": source_name(exit_row),
                "capital": float(capital),
                "units": units,
                "final": final_value,
            }

    operation = st.session_state.get("operation_result")
    if operation and operation["mode"] == mode:
        gain = operation["final"] - operation["capital"]
        profitability = operation["final"] / operation["capital"] - 1

        metrics = st.columns(4)
        metrics[0].metric("Capital", f"S/ {operation['capital']:,.2f}")
        metrics[1].metric(
            "Valor actual/final", f"S/ {operation['final']:,.2f}"
        )
        metrics[2].metric("Ganancia o pérdida", f"S/ {gain:,.2f}")
        metrics[3].metric("Rentabilidad", f"{profitability:+.2%}")

        if operation["exit_source"] == "SBS OFICIAL":
            st.success("Resultado con valor cuota oficial SBS.")
        else:
            st.warning(
                "Resultado provisional: el valor cuota final fue estimado por el OLS."
            )

        st.write(
            f"Entrada: solicitada {operation['entry_req']:%d/%m/%Y}; "
            f"usada {operation['entry_date']:%d/%m/%Y}; "
            f"VC {operation['entry_vc']:.7f} ({operation['entry_source']})."
        )
        st.write(
            f"Salida/valoración: solicitada {operation['exit_req']:%d/%m/%Y}; "
            f"usada {operation['exit_date']:%d/%m/%Y}; "
            f"VC {operation['exit_vc']:.7f} ({operation['exit_source']})."
        )
        st.code(
            f"S/ {operation['capital']:,.2f} × "
            f"({operation['exit_vc']:.7f} / {operation['entry_vc']:.7f}) "
            f"= S/ {operation['final']:,.2f}"
        )

        trajectory = all_vc.loc[
            (all_vc.fecha >= operation["entry_date"])
            & (all_vc.fecha <= operation["exit_date"])
        ].copy()
        trajectory["gain"] = (
            operation["units"] * trajectory.vc - operation["capital"]
        )

        figure = go.Figure()
        figure.add_trace(
            go.Scatter(
                x=trajectory.fecha,
                y=trajectory.vc,
                mode="lines+markers",
                name="Valor cuota",
                yaxis="y",
            )
        )
        figure.add_trace(
            go.Scatter(
                x=trajectory.fecha,
                y=trajectory.gain,
                mode="lines+markers",
                name="Ganancia / pérdida",
                yaxis="y2",
            )
        )
        figure.update_layout(
            title="Valor cuota y ganancia/pérdida",
            height=430,
            hovermode="x unified",
            yaxis={"title": "Valor cuota", "tickformat": ".7f"},
            yaxis2={
                "title": "Ganancia/pérdida (S/)",
                "overlaying": "y",
                "side": "right",
                "tickprefix": "S/ ",
                "showgrid": False,
            },
            legend={"orientation": "h"},
        )
        st.plotly_chart(figure, use_container_width=True)

st.subheader("Retorno estimado del valor cuota")
model_series = pd.concat(
    [
        history[["fecha", "ret_estimado", "senal"]],
        pending[["fecha", "ret_estimado", "senal"]]
        if not pending.empty
        else pd.DataFrame(columns=["fecha", "ret_estimado", "senal"]),
    ],
    ignore_index=True,
).sort_values("fecha")
st.plotly_chart(stem_chart(model_series), use_container_width=True)

st.subheader("Señales")
st.plotly_chart(signal_band(history, pending), use_container_width=True)

with st.expander("Fuentes y auditoría"):
    source_table = pd.DataFrame(
        [
            {"Variable": name, **details}
            for name, details in source_status.items()
        ]
    )
    st.dataframe(source_table, hide_index=True, use_container_width=True)

    validation = history[history.fecha.dt.year == 2026]
    if validation.empty:
        direction = np.nan
    else:
        direction = np.mean(
            np.sign(validation.ret_profuturo)
            == np.sign(validation.ret_estimado)
        )

    audit = pd.DataFrame(
        [
            ["Motor", f"OLS rolling {WINDOW}", "APROBADO"],
            ["Notebook", "No se leen resultados ni archivos del notebook", "INDEPENDIENTE"],
            ["Índices", "Stooq descargado por Streamlit", "INDEPENDIENTE"],
            ["USD/PEN", "BCRP descargado por Streamlit", "INDEPENDIENTE"],
            ["SBS", sbs_source, "EN LÍNEA / RESPALDO"],
            ["Sin anticipación", "ventana_fin < fecha", "APROBADO" if (history.ventana_fin < history.fecha).all() else "REVISAR"],
            ["Umbral", f"±{THRESHOLD:.2%}", "APROBADO"],
            ["Dirección 2026", f"{direction:.1%}" if pd.notna(direction) else "—", "REFERENCIA"],
        ],
        columns=["Control", "Resultado", "Estado"],
    )
    st.dataframe(audit, hide_index=True, use_container_width=True)

st.caption(
    "La aplicación descarga y procesa sus propios datos en Streamlit Cloud. "
    "El notebook no alimenta esta aplicación. Estimación informativa; no garantiza resultados."
)
