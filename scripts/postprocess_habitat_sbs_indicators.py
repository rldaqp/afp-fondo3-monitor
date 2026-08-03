from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "rolling90"
PUBLIC = ROOT / "public" / "habitat"
LATEST_PATH = PUBLIC / "data" / "latest.json"
INDEX_PATH = PUBLIC / "index.html"
HISTORY_PATH = DATA / "sbs_habitat_f3.csv"
DAILY_PATH = DATA / "sbs_habitat_f3_daily.csv"
SOURCE_URL = "https://www.sbs.gob.pe/sistema-privado-de-pensiones/variables-spp"
START_MARKER = "<!-- HABITAT_SBS_INDICATORS_V1 START -->"
END_MARKER = "<!-- HABITAT_SBS_INDICATORS_V1 END -->"
SCRIPT_START = "<!-- HABITAT_SBS_INDICATORS_JS_V1 START -->"
SCRIPT_END = "<!-- HABITAT_SBS_INDICATORS_JS_V1 END -->"


def load_frame(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    frame["fecha"] = pd.to_datetime(frame["fecha"], errors="coerce")
    return frame.dropna(subset=["fecha"]).sort_values("fecha").drop_duplicates("fecha", keep="last")


def change_from(history: pd.DataFrame, latest_date: pd.Timestamp, latest_vc: float, days: int) -> float | None:
    eligible = history.loc[history["fecha"] <= latest_date - pd.Timedelta(days=days)]
    if eligible.empty:
        return None
    base = float(eligible.iloc[-1]["valor_cuota"])
    return latest_vc / base - 1.0 if base > 0 else None


def previous_change(history: pd.DataFrame, latest_vc: float) -> float | None:
    if len(history) < 2:
        return None
    base = float(history.iloc[-2]["valor_cuota"])
    return latest_vc / base - 1.0 if base > 0 else None


def ytd_change(history: pd.DataFrame, latest_date: pd.Timestamp, latest_vc: float) -> float | None:
    current_year = history.loc[history["fecha"].dt.year == latest_date.year]
    if current_year.empty:
        return None
    base = float(current_year.iloc[0]["valor_cuota"])
    return latest_vc / base - 1.0 if base > 0 else None


def remove_marked(html: str, start: str, end: str) -> str:
    pattern = re.compile(re.escape(start) + r".*?" + re.escape(end), re.DOTALL)
    return pattern.sub("", html)


def patch_html() -> None:
    html = INDEX_PATH.read_text(encoding="utf-8")
    html = remove_marked(html, START_MARKER, END_MARKER)
    html = remove_marked(html, SCRIPT_START, SCRIPT_END)

    block = f"""
{START_MARKER}
<section class="panel" id="sbsOfficialIndicators">
  <b>Indicadores oficiales SBS del Fondo 3</b>
  <div class="sub" id="officialIndicatorDate">Última información oficial: —</div>
  <div class="insights" style="margin-top:10px">
    <div class="insight"><div class="label">Valor cuota oficial</div><div class="value" id="officialUnitValue">—</div></div>
    <div class="insight"><div class="label">Cuotas del fondo</div><div class="value" id="officialFundQuotas">—</div></div>
    <div class="insight"><div class="label">Valor total del fondo</div><div class="value" id="officialFundValue">—</div></div>
    <div class="insight"><div class="label">Variación diaria</div><div class="value" id="officialChange1d">—</div></div>
    <div class="insight"><div class="label">Variación 7 días</div><div class="value" id="officialChange7d">—</div></div>
    <div class="insight"><div class="label">Variación 30 días</div><div class="value" id="officialChange30d">—</div></div>
    <div class="insight"><div class="label">Variación 90 días</div><div class="value" id="officialChange90d">—</div></div>
    <div class="insight"><div class="label">Acumulado del año</div><div class="value" id="officialChangeYtd">—</div></div>
  </div>
  <div class="note" style="margin-top:9px">Fuente: <a href="{SOURCE_URL}" target="_blank" rel="noopener" style="color:#93c5fd">Variables SPP de la SBS</a>.</div>
</section>
{END_MARKER}
"""
    anchor = '<section class="panel"><b>Confianza y calidad del modelo</b>'
    if anchor not in html:
        raise RuntimeError("No se encontró el panel de confianza del visor Hábitat.")
    html = html.replace(anchor, block + "\n" + anchor, 1)

    script = f"""
{SCRIPT_START}
<script>
(async function(){{
  const pct = value => value == null || Number.isNaN(Number(value)) ? '—' : `${{Number(value) >= 0 ? '+' : ''}}${{(Number(value) * 100).toFixed(2)}}%`;
  const number = value => value == null ? '—' : new Intl.NumberFormat('es-PE', {{maximumFractionDigits:2}}).format(Number(value));
  const money = value => value == null ? '—' : `S/ ${{new Intl.NumberFormat('es-PE', {{maximumFractionDigits:2}}).format(Number(value))}}`;
  try {{
    const response = await fetch('data/latest.json', {{cache:'no-store'}});
    if (!response.ok) throw new Error(`HTTP ${{response.status}}`);
    const latest = await response.json();
    const data = latest.official_indicators || {{}};
    document.getElementById('officialIndicatorDate').textContent = `Última información oficial: ${{data.date || '—'}}`;
    document.getElementById('officialUnitValue').textContent = data.unit_value == null ? '—' : Number(data.unit_value).toFixed(7);
    document.getElementById('officialFundQuotas').textContent = number(data.fund_quotas);
    document.getElementById('officialFundValue').textContent = money(data.fund_value_pen);
    document.getElementById('officialChange1d').textContent = pct(data.change_1d);
    document.getElementById('officialChange7d').textContent = pct(data.change_7d);
    document.getElementById('officialChange30d').textContent = pct(data.change_30d);
    document.getElementById('officialChange90d').textContent = pct(data.change_90d);
    document.getElementById('officialChangeYtd').textContent = pct(data.change_ytd);
  }} catch (error) {{
    document.getElementById('officialIndicatorDate').textContent = `No se pudieron cargar los indicadores SBS: ${{error.message}}`;
  }}
}})();
</script>
{SCRIPT_END}
"""
    if "</body>" not in html:
        raise RuntimeError("El HTML de Hábitat no tiene cierre body.")
    html = html.replace("</body>", script + "\n</body>", 1)
    INDEX_PATH.write_text(html, encoding="utf-8")


def main() -> None:
    daily = load_frame(DAILY_PATH)
    history = load_frame(HISTORY_PATH)
    history["valor_cuota"] = pd.to_numeric(history["valor_cuota"], errors="coerce")
    for column in ("cuotas_fondo", "valor_fondo", "valor_cuota"):
        daily[column] = pd.to_numeric(daily[column], errors="coerce")
    history = history.dropna(subset=["valor_cuota"])
    daily = daily.dropna(subset=["cuotas_fondo", "valor_fondo", "valor_cuota"])
    if history.empty or daily.empty:
        raise RuntimeError("No hay datos SBS suficientes para crear los indicadores de Hábitat.")

    official = daily.iloc[-1]
    latest_date = pd.Timestamp(official["fecha"])
    latest_vc = float(official["valor_cuota"])
    history = history.loc[history["fecha"] <= latest_date].copy()

    indicators = {
        "date": latest_date.strftime("%Y-%m-%d"),
        "unit_value": latest_vc,
        "fund_quotas": float(official["cuotas_fondo"]),
        "fund_value_pen": float(official["valor_fondo"]),
        "change_1d": previous_change(history, latest_vc),
        "change_7d": change_from(history, latest_date, latest_vc, 7),
        "change_30d": change_from(history, latest_date, latest_vc, 30),
        "change_90d": change_from(history, latest_date, latest_vc, 90),
        "change_ytd": ytd_change(history, latest_date, latest_vc),
        "source": "SBS · Variables SPP",
        "source_url": SOURCE_URL,
    }

    latest = json.loads(LATEST_PATH.read_text(encoding="utf-8"))
    latest["latest_sbs_date"] = indicators["date"]
    latest["latest_sbs_vc"] = latest_vc
    latest["official_indicators"] = indicators
    latest.setdefault("sources", {})["sbs_daily"] = "SBS · Variables SPP · Información diaria"
    LATEST_PATH.write_text(json.dumps(latest, ensure_ascii=False, indent=2), encoding="utf-8")

    patch_html()
    print(json.dumps(indicators, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
