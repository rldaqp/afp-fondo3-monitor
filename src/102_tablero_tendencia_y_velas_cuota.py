from __future__ import annotations

import argparse
import html
import webbrowser
from datetime import datetime
from pathlib import Path

import pandas as pd

AFPS = ["Habitat", "Integra", "Prima", "Profuturo"]


def leer_csv(ruta: Path, obligatorio: bool = False) -> pd.DataFrame:
    if not ruta.exists():
        if obligatorio:
            raise FileNotFoundError(f"Falta el archivo: {ruta}")
        return pd.DataFrame()
    ultimo = None
    for enc in ["utf-8-sig", "latin-1", "utf-8"]:
        try:
            return pd.read_csv(ruta, encoding=enc)
        except Exception as exc:
            ultimo = exc
    raise RuntimeError(f"No se pudo leer {ruta}: {ultimo}")


def preparar(processed: Path):
    base = leer_csv(processed / "ca0001_modelo56_base_alineada.csv", True)
    pred = leer_csv(processed / "ca0001_modelo79_primer_pronostico_congelado.csv")
    intra = leer_csv(processed / "ca0001_modelo99_historial_intradia_cuota.csv")
    velas = leer_csv(processed / "ca0001_modelo99_velas_sinteticas_30min.csv")

    base["fecha_cuota"] = pd.to_datetime(base["fecha_cuota"], errors="coerce").dt.normalize()
    base["cuota_sbs"] = pd.to_numeric(base["cuota_sbs"], errors="coerce")
    base = (
        base.dropna(subset=["afp", "fecha_cuota", "cuota_sbs"])
        .drop_duplicates(["afp", "fecha_cuota"], keep="last")
        .sort_values(["afp", "fecha_cuota"])
    )

    if not pred.empty:
        pred["fecha_objetivo"] = pd.to_datetime(pred["fecha_objetivo"], errors="coerce").dt.normalize()
        pred["cuota_estimada"] = pd.to_numeric(pred["cuota_estimada"], errors="coerce")
        pred["cobertura_factores_pct"] = pd.to_numeric(pred["cobertura_factores_pct"], errors="coerce")
        pred = pred.dropna(subset=["afp", "fecha_objetivo", "cuota_estimada"])
        pred = pred[pred["cobertura_factores_pct"].fillna(0).ge(100)]
        orden = ["afp", "fecha_objetivo"] + (["run_id"] if "run_id" in pred.columns else [])
        pred = pred.sort_values(orden).drop_duplicates(["afp", "fecha_objetivo"], keep="first")

    if not intra.empty:
        intra["timestamp"] = pd.to_datetime(intra["timestamp"], errors="coerce")
        intra["fecha_objetivo"] = pd.to_datetime(intra["fecha_objetivo"], errors="coerce").dt.normalize()
        for c in ["cuota_estimada_intradia", "retorno_estimado_pct", "cobertura_pct", "cuota_base"]:
            if c in intra.columns:
                intra[c] = pd.to_numeric(intra[c], errors="coerce")
        intra = intra.dropna(subset=["afp", "timestamp", "cuota_estimada_intradia"])

    if not velas.empty:
        velas["bloque_30min"] = pd.to_datetime(velas["bloque_30min"], errors="coerce")
        for c in ["open", "high", "low", "close"]:
            velas[c] = pd.to_numeric(velas[c], errors="coerce")
        velas = velas.dropna(subset=["afp", "bloque_30min", "open", "high", "low", "close"])

    return base, pred, intra, velas


def grafico_historico(afp: str, base: pd.DataFrame, pred: pd.DataFrame) -> str:
    import plotly.graph_objects as go
    import plotly.io as pio

    real = base[base["afp"].astype(str).eq(afp)].sort_values("fecha_cuota")
    p = pred[pred["afp"].astype(str).eq(afp)].sort_values("fecha_objetivo") if not pred.empty else pd.DataFrame()

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=real["fecha_cuota"], y=real["cuota_sbs"], mode="lines",
        name="Cuota oficial SBS", line=dict(width=2.3),
        hovertemplate="<b>Cuota oficial SBS</b><br>Fecha: %{x|%d/%m/%Y}<br>Cuota: %{y:.6f}<extra></extra>",
    ))
    if not p.empty:
        fig.add_trace(go.Scatter(
            x=p["fecha_objetivo"], y=p["cuota_estimada"], mode="lines+markers",
            name="Pronóstico congelado", line=dict(width=2.5, dash="dash"), marker=dict(size=8),
            hovertemplate="<b>Pronóstico</b><br>Fecha: %{x|%d/%m/%Y}<br>Cuota estimada: %{y:.6f}<extra></extra>",
        ))

    fin = real["fecha_cuota"].max()
    if not p.empty:
        fin = max(fin, p["fecha_objetivo"].max())

    fig.update_layout(
        title=dict(text=f"{afp}: tendencia histórica diaria", x=0.02),
        height=470, margin=dict(l=60, r=25, t=72, b=60), hovermode="x unified",
        paper_bgcolor="white", plot_bgcolor="white",
        legend=dict(orientation="h", y=1.02, x=0),
        xaxis=dict(
            title="Fecha", range=[fin - pd.Timedelta(days=90), fin + pd.Timedelta(days=2)],
            rangeslider=dict(visible=True, thickness=0.10),
            rangeselector=dict(buttons=[
                dict(count=5, label="5 días", step="day", stepmode="backward"),
                dict(count=10, label="10 días", step="day", stepmode="backward"),
                dict(count=30, label="30 días", step="day", stepmode="backward"),
                dict(count=3, label="3 meses", step="month", stepmode="backward"),
                dict(count=6, label="6 meses", step="month", stepmode="backward"),
                dict(count=1, label="1 año", step="year", stepmode="backward"),
                dict(step="all", label="Todo"),
            ]), showgrid=True, gridcolor="#e8edf4",
        ),
        yaxis=dict(title="Valor cuota", autorange=True, fixedrange=False, showgrid=True, gridcolor="#e8edf4"),
    )
    return pio.to_html(fig, full_html=False, include_plotlyjs=False, config={"responsive": True, "scrollZoom": True, "displaylogo": False, "doubleClick": "reset"})


def grafico_intradia(afp: str, intra: pd.DataFrame, velas: pd.DataFrame) -> str:
    import plotly.graph_objects as go
    import plotly.io as pio
    from plotly.subplots import make_subplots

    h = intra[intra["afp"].astype(str).eq(afp)].sort_values("timestamp") if not intra.empty else pd.DataFrame()
    v = velas[velas["afp"].astype(str).eq(afp)].sort_values("bloque_30min") if not velas.empty else pd.DataFrame()

    if h.empty and v.empty:
        return '<div class="sin-intradia">Todavía no existen estimaciones intradía guardadas. El histórico diario de arriba sí está disponible. Las velas se acumularán desde la primera sesión válida posterior a la instalación.</div>'

    fig = make_subplots(rows=2, cols=1, vertical_spacing=0.14, row_heights=[0.42, 0.58], subplot_titles=["Estimación intradía cada cinco minutos", "Velas sintéticas de treinta minutos"])

    if not h.empty:
        ultima = sorted(pd.unique(h["fecha_objetivo"].dropna()))[-1]
        ha = h[h["fecha_objetivo"].eq(ultima)]
        fig.add_trace(go.Scatter(x=ha["timestamp"], y=ha["cuota_estimada_intradia"], mode="lines+markers", name="Cuota estimada cada 5 min"), row=1, col=1)
        if "cuota_base" in ha.columns:
            cb = pd.to_numeric(ha["cuota_base"], errors="coerce").dropna()
            if not cb.empty:
                fig.add_hline(y=float(cb.iloc[-1]), line_dash="dot", annotation_text="Cuota base", row=1, col=1)

    if not v.empty:
        etiquetas = [pd.Timestamp(x).strftime("%d/%m %H:%M") for x in v["bloque_30min"]]
        fig.add_trace(go.Candlestick(
            x=etiquetas, open=v["open"], high=v["high"], low=v["low"], close=v["close"],
            increasing=dict(line=dict(color="#159447", width=2), fillcolor="#37b865"),
            decreasing=dict(line=dict(color="#d52236", width=2), fillcolor="#ef334e"),
            whiskerwidth=0.9, name="Vela sintética 30 min",
        ), row=2, col=1)

    fig.update_layout(title=dict(text=f"{afp}: seguimiento intradía", x=0.02), height=760, margin=dict(l=65, r=28, t=92, b=60), paper_bgcolor="white", plot_bgcolor="white", hovermode="x unified", legend=dict(orientation="h", y=1.02, x=0))
    fig.update_yaxes(title="Valor cuota estimado", autorange=True, fixedrange=False, showgrid=True, gridcolor="#e7edf4", row=1, col=1)
    fig.update_xaxes(type="category", rangeslider=dict(visible=False), showgrid=True, gridcolor="#e7edf4", row=2, col=1)
    fig.update_yaxes(title="Valor cuota sintético", autorange=True, fixedrange=False, showgrid=True, gridcolor="#e7edf4", row=2, col=1)
    return pio.to_html(fig, full_html=False, include_plotlyjs=False, config={"responsive": True, "scrollZoom": True, "displaylogo": False, "doubleClick": "reset"})


def crear(processed: Path, base: pd.DataFrame, pred: pd.DataFrame, intra: pd.DataFrame, velas: pd.DataFrame) -> Path:
    secciones = []
    for afp in AFPS:
        secciones.append(
            f'<section class="seccion" id="{afp.lower()}"><h2>{html.escape(afp)}</h2>'
            f'<h3>Tendencia histórica diaria</h3><p class="ayuda">Esta parte siempre está disponible, incluso cuando hoy no hay sesión.</p>'
            f'{grafico_historico(afp, base, pred)}'
            f'<h3>Seguimiento intradía y velas sintéticas</h3><p class="ayuda">Conserva las sesiones anteriores ya registradas.</p>'
            f'{grafico_intradia(afp, intra, velas)}</section>'
        )

    ruta = processed / "ca0001_modelo102_tendencia_y_velas_cuota.html"
    documento = f'''<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="300"><title>Tendencia y velas AFP</title><script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script><style>body{{margin:0;background:#f3f6fb;font-family:Arial;color:#1f2937}}main{{width:min(1550px,96%);margin:auto;padding:22px 0 55px}}header{{color:white;background:linear-gradient(135deg,#123f73,#2768a8);border-radius:16px;padding:25px 28px}}.boton{{display:inline-block;text-decoration:none;background:white;color:#123f73;border-radius:9px;padding:10px 15px;margin:12px 7px 0 0;font-weight:bold}}.aviso{{background:#fff7d6;border-left:6px solid #d7a400;border-radius:9px;padding:14px 16px;margin:16px 0;line-height:1.55}}.seccion{{background:white;border:1px solid #d8e2ef;border-radius:15px;padding:20px;margin:18px 0}}.seccion h2{{color:#123f73}}.seccion h3{{color:#2768a8}}.ayuda{{color:#64748b}}.sin-intradia{{background:#eef5ff;border-left:6px solid #2768a8;border-radius:9px;padding:18px}}</style></head><body><main><header><h1>Tendencia histórica y velas de la cuota estimada</h1><p>Actualizado: <strong>{datetime.now().strftime("%d/%m/%Y %H:%M:%S")}</strong></p><a class="boton" href="ca0001_modelo80_dashboard.html">Monitor principal</a><a class="boton" href="ca0001_modelo92_indicadores_didacticos.html">Indicadores</a><a class="boton" href="ca0001_modelo97_simulador_monto_fondo3.html">Simulador</a></header><div class="aviso"><strong>Histórico e intradía:</strong> el histórico diario permanece visible aunque hoy no haya mercado. Las velas intradía se van acumulando desde la instalación.</div>{''.join(secciones)}</main></body></html>'''
    ruta.write_text(documento, encoding="utf-8")
    return ruta


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--abrir", action="store_true")
    args = parser.parse_args()
    raiz = Path(__file__).resolve().parents[1]
    processed = raiz / "data" / "processed"
    base, pred, intra, velas = preparar(processed)
    pagina = crear(processed, base, pred, intra, velas)
    print(f"Página: {pagina.resolve()}")
    if args.abrir:
        webbrowser.open(pagina.resolve().as_uri())


if __name__ == "__main__":
    main()
