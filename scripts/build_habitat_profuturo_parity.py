from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "rolling90"
PUBLIC = ROOT / "public"
HABITAT = PUBLIC / "habitat"
HABITAT_DATA = HABITAT / "data"
HABITAT_DATA.mkdir(parents=True, exist_ok=True)

WINDOW = 90
THRESHOLD = 0.001
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
PRICE_COLUMNS = {
    "SPY": "SPY",
    "NEM": "NEM",
    "FCX": "FCX",
    "EPU": "EPU",
    "MCHI": "MCHI",
    "EEM": "EEM",
    "USD_PEN": "USD_PEN",
}
RETURN_COLUMNS = {
    "SPY": "ret_SPY",
    "NEM": "ret_NEM",
    "FCX": "ret_FCX",
    "EPU": "ret_EPU",
    "MCHI": "ret_MCHI",
    "EEM": "ret_EEM",
    "USD_PEN": "ret_USD_PEN",
}


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        raise RuntimeError(f"No existe o está vacío: {path.relative_to(ROOT)}")
    frame = pd.read_csv(path)
    if "fecha" in frame.columns:
        frame["fecha"] = pd.to_datetime(frame["fecha"], errors="coerce")
    return frame


def classify(value: float) -> str:
    if value > THRESHOLD:
        return "SUBE"
    if value < -THRESHOLD:
        return "BAJA"
    return "NEUTRO"


def fit_ols(train: pd.DataFrame) -> np.ndarray:
    x_values = train[FEATURES].to_numpy(float)
    y_values = train["ret_habitat"].to_numpy(float)
    return np.linalg.lstsq(
        np.c_[np.ones(len(x_values)), x_values],
        y_values,
        rcond=None,
    )[0]


def load_market() -> pd.DataFrame:
    market = read_csv(DATA / "markets.csv")
    for column in [*PRICE_COLUMNS.values(), *FEATURES]:
        if column not in market.columns:
            market[column] = np.nan
        market[column] = pd.to_numeric(market[column], errors="coerce")

    pending_path = DATA / "pending_predictions.csv"
    if pending_path.exists() and pending_path.stat().st_size:
        pending = read_csv(pending_path)
        available = [column for column in FEATURES if column in pending.columns]
        if available:
            pending = pending[["fecha", *available]].drop_duplicates("fecha", keep="last")
            market = market.merge(
                pending,
                on="fecha",
                how="outer",
                suffixes=("", "_pending"),
            )
            for column in available:
                market[column] = market[column].fillna(market[f"{column}_pending"])
                market = market.drop(columns=[f"{column}_pending"])

    return (
        market.dropna(subset=["fecha"])
        .sort_values("fecha")
        .drop_duplicates("fecha", keep="last")
        .reset_index(drop=True)
    )


def write_json(name: str, payload: object) -> None:
    (HABITAT_DATA / name).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def build_rich_series() -> tuple[list[dict], list[dict], list[dict], pd.DataFrame]:
    official = read_csv(DATA / "sbs_habitat_f3.csv")
    official["valor_cuota"] = pd.to_numeric(official["valor_cuota"], errors="coerce")
    official = (
        official.dropna(subset=["fecha", "valor_cuota"])
        .sort_values("fecha")
        .drop_duplicates("fecha", keep="last")
        .reset_index(drop=True)
    )
    official["vc_previo"] = official["valor_cuota"].shift(1)
    official["ret_habitat"] = official["valor_cuota"].pct_change(fill_method=None)

    market = load_market()
    model_data = (
        official.merge(market[["fecha", *FEATURES]], on="fecha", how="inner")
        .dropna(subset=["vc_previo", "ret_habitat", *FEATURES])
        .sort_values("fecha")
        .reset_index(drop=True)
    )
    if len(model_data) < WINDOW:
        raise RuntimeError(
            f"Hábitat solo tiene {len(model_data)} observaciones completas; "
            f"se requieren {WINDOW}."
        )

    historical: list[dict] = []
    historical_by_date: dict[str, dict] = {}
    for index in range(WINDOW, len(model_data)):
        train = model_data.iloc[index - WINDOW:index]
        current = model_data.iloc[index]
        beta = fit_ols(train)
        prediction = float(
            np.r_[1.0, current[FEATURES].to_numpy(float)] @ beta
        )
        estimated_vc = float(current["vc_previo"]) * (1.0 + prediction)
        row = {
            "fecha": pd.Timestamp(current["fecha"]).strftime("%Y-%m-%d"),
            "ret_estimado": prediction,
            "senal": classify(prediction),
            "vc_real": float(current["valor_cuota"]),
            "vc_estimado": estimated_vc,
            "tipo": "HISTORICO",
        }
        historical.append(row)
        historical_by_date[row["fecha"]] = row

    train = model_data.tail(WINDOW)
    beta = fit_ols(train)
    last_official = official.iloc[-1]
    last_official_date = pd.Timestamp(last_official["fecha"])
    current_vc = float(last_official["valor_cuota"])

    pending_rows: list[dict] = []
    pending_market = (
        market.loc[market["fecha"] > last_official_date, ["fecha", *FEATURES]]
        .dropna(subset=FEATURES)
        .sort_values("fecha")
    )
    for _, current in pending_market.iterrows():
        prediction = float(
            np.r_[1.0, current[FEATURES].to_numpy(float)] @ beta
        )
        current_vc *= 1.0 + prediction
        pending_rows.append(
            {
                "fecha": pd.Timestamp(current["fecha"]).strftime("%Y-%m-%d"),
                "ret_estimado": prediction,
                "senal": classify(prediction),
                "vc_real": None,
                "vc_estimado": current_vc,
                "tipo": "PENDIENTE",
            }
        )

    rich_signals = [*historical, *pending_rows]

    operation_series: list[dict] = []
    official_series: list[dict] = []
    for _, row in official.iterrows():
        date = pd.Timestamp(row["fecha"]).strftime("%Y-%m-%d")
        prediction = historical_by_date.get(date)
        record = {
            "fecha": date,
            "vc": float(row["valor_cuota"]),
            "fuente": "SBS OFICIAL",
            "es_oficial": True,
            "senal": prediction["senal"] if prediction else None,
            "ret_estimado": prediction["ret_estimado"] if prediction else None,
        }
        official_series.append(record)
        operation_series.append(record.copy())

    for row in pending_rows:
        record = {
            "fecha": row["fecha"],
            "vc": float(row["vc_estimado"]),
            "fuente": "MODELO OLS",
            "es_oficial": False,
            "senal": row["senal"],
            "ret_estimado": row["ret_estimado"],
        }
        official_series.append(record)
        operation_series.append(record.copy())

    official_series.sort(key=lambda row: row["fecha"])
    operation_series.sort(key=lambda row: row["fecha"])
    return rich_signals, official_series, operation_series, market


def enrich_latest_and_insights(
    rich_signals: list[dict],
    market: pd.DataFrame,
) -> tuple[dict, dict]:
    latest_path = HABITAT_DATA / "latest.json"
    insights_path = HABITAT_DATA / "model_insights.json"
    latest = json.loads(latest_path.read_text(encoding="utf-8"))
    insights = json.loads(insights_path.read_text(encoding="utf-8"))

    historical = [row for row in rich_signals if row["tipo"] == "HISTORICO"]
    sbs = read_csv(DATA / "sbs_habitat_f3.csv")
    sbs["valor_cuota"] = pd.to_numeric(sbs["valor_cuota"], errors="coerce")
    sbs = sbs.dropna(subset=["fecha", "valor_cuota"]).sort_values("fecha")
    sbs["ret_real"] = sbs["valor_cuota"].pct_change(fill_method=None)
    real_returns = {
        pd.Timestamp(row["fecha"]).strftime("%Y-%m-%d"): float(row["ret_real"])
        for _, row in sbs.dropna(subset=["ret_real"]).iterrows()
    }

    evaluated = []
    for row in historical:
        actual = real_returns.get(row["fecha"])
        if actual is None:
            continue
        evaluated.append(
            {
                **row,
                "ret_real": actual,
                "senal_real": classify(actual),
                "correcta": row["senal"] == classify(actual),
            }
        )

    performance = insights.setdefault("performance", {})
    for signal_name, key in [("SUBE", "sube"), ("BAJA", "baja"), ("NEUTRO", "neutro")]:
        subset = [row for row in evaluated if row["senal"] == signal_name]
        performance[f"{key}_n"] = len(subset)
        performance[f"{key}_accuracy"] = (
            sum(bool(row["correcta"]) for row in subset) / len(subset)
            if subset
            else None
        )

    benchmarks = insights.setdefault("benchmarks", {})
    ols_mae = float(benchmarks.get("ols_mae_pp") or 0.0)
    zero_mae = float(benchmarks.get("zero_change_mae_pp") or 0.0)
    benchmarks["ols_mae_improvement_vs_zero"] = (
        1.0 - ols_mae / zero_mae if zero_mae > 0 else None
    )

    confidence = insights.setdefault("confidence", {})
    confidence["label"] = insights.get("current_signal", latest.get("signal", "—"))

    quality = insights.setdefault("quality", {})
    quality.setdefault("critical", [])
    quality.setdefault("warnings", [])
    quality["fx_provisional"] = bool(latest.get("latest_fx_provisional", False))

    insights["challenger_huber"] = {
        "status": "NO APLICA EN HÁBITAT",
        "error": "El visor Hábitat mantiene únicamente su modelo OLS propio.",
    }

    latest_official = sbs.iloc[-1]
    latest_official_date = pd.Timestamp(latest_official["fecha"])
    latest_official_vc = float(latest_official["valor_cuota"])

    daily_path = DATA / "sbs_habitat_f3_daily.csv"
    daily = read_csv(daily_path) if daily_path.exists() and daily_path.stat().st_size else pd.DataFrame()
    if not daily.empty:
        for column in ["cuotas_fondo", "valor_fondo", "valor_cuota"]:
            daily[column] = pd.to_numeric(daily[column], errors="coerce")
        daily = daily.dropna(subset=["fecha", "cuotas_fondo", "valor_fondo", "valor_cuota"]).sort_values("fecha")
    daily_latest = daily.iloc[-1] if not daily.empty else None

    def period_change(days: int) -> float | None:
        target = latest_official_date - pd.Timedelta(days=days)
        previous = sbs.loc[sbs["fecha"] <= target]
        if previous.empty:
            return None
        base = float(previous.iloc[-1]["valor_cuota"])
        return latest_official_vc / base - 1.0 if base > 0 else None

    year_start = sbs.loc[sbs["fecha"] >= pd.Timestamp(latest_official_date.year, 1, 1)]
    ytd = None
    if not year_start.empty:
        base = float(year_start.iloc[0]["valor_cuota"])
        ytd = latest_official_vc / base - 1.0 if base > 0 else None

    latest["latest_sbs_date"] = latest_official_date.strftime("%Y-%m-%d")
    latest["latest_sbs_vc"] = latest_official_vc
    latest["official_indicators"] = {
        "date": latest_official_date.strftime("%Y-%m-%d"),
        "unit_value": latest_official_vc,
        "fund_quotas": (
            None if daily_latest is None else float(daily_latest["cuotas_fondo"])
        ),
        "fund_value_pen": (
            None if daily_latest is None else float(daily_latest["valor_fondo"])
        ),
        "change_1d": period_change(1),
        "change_7d": period_change(7),
        "change_30d": period_change(30),
        "change_90d": period_change(90),
        "change_ytd": ytd,
        "source": "SBS · Variables SPP",
        "source_url": "https://www.sbs.gob.pe/sistema-privado-de-pensiones/variables-spp",
    }

    latest["estimate_type"] = "CIERRE DIARIO · MODELO OLS HÁBITAT"
    latest["parity_rule"] = (
        "Modelo propio de Hábitat; cada VC histórico estimado parte del VC SBS "
        "anterior y aplica el retorno OLS de la fecha."
    )
    latest["parity_verified"] = True
    latest["model_factors"] = [
        "SPY", "NEM", "FCX", "EPU", "MCHI", "EEM", "USD_PEN"
    ]
    latest["live_engine"] = "CIERRE DIARIO HÁBITAT"
    latest["generated_at_lima"] = datetime.now(LIMA).isoformat()
    latest.setdefault("sources", {})["market"] = (
        "Yahoo Finance y USD/PEN de la serie compartida del monitor"
    )

    return latest, insights


def build_live_market(latest: dict, market: pd.DataFrame) -> dict:
    complete = market.dropna(subset=FEATURES).sort_values("fecha")
    if complete.empty:
        raise RuntimeError("No hay una fila de mercado completa para Hábitat.")
    current = complete.iloc[-1]
    current_index = int(current.name)
    previous = market.loc[:current_index - 1].dropna(subset=["fecha"]).tail(1)
    previous_row = previous.iloc[-1] if not previous.empty else current

    assets = []
    for symbol, price_column in PRICE_COLUMNS.items():
        return_column = RETURN_COLUMNS[symbol]
        price = current.get(price_column)
        previous_price = previous_row.get(price_column)
        assets.append(
            {
                "serie": symbol,
                "ticker": "PEN=X" if symbol == "USD_PEN" else symbol,
                "timestamp": pd.Timestamp(current["fecha"]).strftime("%Y-%m-%d"),
                "precio_anterior": (
                    None if pd.isna(previous_price) else float(previous_price)
                ),
                "precio_actual": None if pd.isna(price) else float(price),
                "retorno": float(current[return_column]),
                "retorno_modelo": float(current[return_column]),
                "estado": "CIERRE DIARIO · USADO POR MODELO HÁBITAT",
                "usado_modelo": True,
            }
        )

    return {
        "generated_at_lima": datetime.now(LIMA).isoformat(),
        "mode": "CIERRE DIARIO",
        "market_open": False,
        "signal_date": latest["latest_estimate_date"],
        "vc_estimated": float(latest["latest_estimated_vc"]),
        "return_estimated": float(latest["latest_return_estimated"]),
        "signal": latest["signal"],
        "assets": assets,
        "action": "CIERRE",
        "engine": "MODELO OLS HÁBITAT",
        "fx_rule": "USD/PEN de la serie compartida utilizada por el modelo.",
        "fx_source": "SERIE COMPARTIDA",
        "fx_provisional": False,
    }


INDICATORS_PANEL = """
<!-- HABITAT_SBS_INDICATORS_V1 START -->
<section class="panel" id="sbsOfficialIndicators">
  <div class="chart-title">Indicadores oficiales SBS del Fondo 3</div>
  <div class="sub" id="officialIndicatorDate">Última información oficial: —</div>
  <div class="insight-grid" style="margin-top:10px">
    <div class="insight-card"><div class="insight-label">Valor cuota oficial</div><div class="insight-value" id="officialUnitValue">—</div></div>
    <div class="insight-card"><div class="insight-label">Cuotas del fondo</div><div class="insight-value" id="officialFundQuotas">—</div></div>
    <div class="insight-card"><div class="insight-label">Valor total del fondo</div><div class="insight-value" id="officialFundValue">—</div></div>
    <div class="insight-card"><div class="insight-label">Variación diaria</div><div class="insight-value" id="officialChange1d">—</div></div>
    <div class="insight-card"><div class="insight-label">Variación 7 días</div><div class="insight-value" id="officialChange7d">—</div></div>
    <div class="insight-card"><div class="insight-label">Variación 30 días</div><div class="insight-value" id="officialChange30d">—</div></div>
    <div class="insight-card"><div class="insight-label">Variación 90 días</div><div class="insight-value" id="officialChange90d">—</div></div>
    <div class="insight-card"><div class="insight-label">Acumulado del año</div><div class="insight-value" id="officialChangeYtd">—</div></div>
  </div>
  <div class="note" style="margin-top:9px">Fuente: Variables SPP de la SBS.</div>
</section>
<!-- HABITAT_SBS_INDICATORS_V1 END -->
"""

INDICATORS_SCRIPT = """
<!-- HABITAT_SBS_INDICATORS_JS_V1 START -->
<script>
(async function(){
  const pctOfficial = value => value == null || Number.isNaN(Number(value)) ? '—' : `${Number(value) >= 0 ? '+' : ''}${(Number(value) * 100).toFixed(2)}%`;
  const numberOfficial = value => value == null ? '—' : new Intl.NumberFormat('es-PE', {maximumFractionDigits:2}).format(Number(value));
  const moneyOfficial = value => value == null ? '—' : `S/ ${new Intl.NumberFormat('es-PE', {maximumFractionDigits:2}).format(Number(value))}`;
  try {
    const response = await fetch('data/latest.json', {cache:'no-store'});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const latest = await response.json();
    const data = latest.official_indicators || {};
    const displayDate = data.date ? data.date.split('-').reverse().join('/') : '—';
    document.getElementById('officialIndicatorDate').textContent = `Última información oficial: ${displayDate}`;
    document.getElementById('officialUnitValue').textContent = data.unit_value == null ? '—' : Number(data.unit_value).toFixed(7);
    document.getElementById('officialFundQuotas').textContent = numberOfficial(data.fund_quotas);
    document.getElementById('officialFundValue').textContent = moneyOfficial(data.fund_value_pen);
    document.getElementById('officialChange1d').textContent = pctOfficial(data.change_1d);
    document.getElementById('officialChange7d').textContent = pctOfficial(data.change_7d);
    document.getElementById('officialChange30d').textContent = pctOfficial(data.change_30d);
    document.getElementById('officialChange90d').textContent = pctOfficial(data.change_90d);
    document.getElementById('officialChangeYtd').textContent = pctOfficial(data.change_ytd);
  } catch (error) {
    document.getElementById('officialIndicatorDate').textContent = `No se pudieron cargar los indicadores SBS: ${error.message}`;
  }
})();
</script>
<!-- HABITAT_SBS_INDICATORS_JS_V1 END -->
"""


def build_html() -> None:
    template_path = PUBLIC / "index.html"
    if not template_path.exists():
        raise RuntimeError("No existe public/index.html para usar como plantilla.")
    html = template_path.read_text(encoding="utf-8")

    replacements = {
        "Profuturo Fondo 3": "Hábitat Fondo 3",
        "Profuturo": "Hábitat",
        "datos independientes del notebook": "modelo propio con datos oficiales SBS",
        "PARIDAD NOTEBOOK": "MODELO HÁBITAT",
        "Fórmula notebook": "Fórmula de operación",
        "exactamente como el notebook": "según las fuentes disponibles",
        "fondo3_trade_history_v1": "habitat_fondo3_trade_history_v1",
        "fondo3_drive_sync_url_v1": "habitat_fondo3_drive_sync_url_v1",
        "fondo3_trade_cloud_file_id_v1": "habitat_fondo3_trade_cloud_file_id_v1",
    }
    for old, new in replacements.items():
        html = html.replace(old, new)

    html = html.replace(
        "</head>",
        "<style>#huberChallengerBox{display:none!important}</style></head>",
        1,
    )
    marker = '<section class="panel" id="modelInsightsPanel">'
    if marker not in html:
        raise RuntimeError("No se encontró el panel de calidad del visor Profuturo.")
    html = html.replace(marker, INDICATORS_PANEL + "\n" + marker, 1)
    html = html.replace(
        "</body>",
        INDICATORS_SCRIPT + "\n</body>",
        1,
    )
    HABITAT.joinpath("index.html").write_text(html, encoding="utf-8")


def main() -> None:
    rich_signals, series, operation_series, market = build_rich_series()
    latest, insights = enrich_latest_and_insights(rich_signals, market)
    live_market = build_live_market(latest, market)

    write_json("signals.json", rich_signals)
    write_json("series.json", series)
    write_json("operation_series.json", operation_series)
    write_json("latest.json", latest)
    write_json("model_insights.json", insights)
    write_json("live_market.json", live_market)
    build_html()

    historical = [row for row in rich_signals if row["tipo"] == "HISTORICO"]
    pending = [row for row in rich_signals if row["tipo"] == "PENDIENTE"]
    print(
        "Visor Hábitat alineado con Profuturo · "
        f"{len(historical)} VC históricos estimados · "
        f"{len(pending)} VC pendientes · ventanas 7/15/30/90/Todo."
    )


if __name__ == "__main__":
    main()
