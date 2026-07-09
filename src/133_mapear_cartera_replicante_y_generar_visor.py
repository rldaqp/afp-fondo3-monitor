from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

import pandas as pd


AFPS = ["Habitat", "Integra", "Prima", "Profuturo"]


def leer_csv(ruta: Path) -> pd.DataFrame:
    if not ruta.exists():
        raise FileNotFoundError(f"No existe: {ruta}")
    return pd.read_csv(ruta)


def cargar_json(ruta: Path) -> dict[str, Any]:
    if not ruta.exists():
        return {}
    return json.loads(ruta.read_text(encoding="utf-8"))


def escribir_csv(df: pd.DataFrame, ruta: Path) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(ruta, index=False, encoding="utf-8-sig")


def esc(x: object) -> str:
    if pd.isna(x):
        return ""
    return html.escape(str(x))


def pct(x: object, decimales: int = 2) -> str:
    y = pd.to_numeric(x, errors="coerce")
    if pd.isna(y):
        return "-"
    return f"{y:.{decimales}f}%"


def elegir_figi(datos: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not datos:
        return None

    for exch in ("US", "UW", "UN", "UP", "UA", "LN", "LX", "ID", "MM"):
        for item in datos:
            if item.get("exchCode") == exch and item.get("ticker"):
                return item

    for item in datos:
        if item.get("ticker"):
            return item
    return datos[0]


def proxy_por_texto(texto: str, moneda: str) -> tuple[str, str]:
    t = texto.upper()

    reglas = [
        (("S&P", "SP 500", "USA", "US ", "NORTH AMERICA"), "SPY", "renta variable USA"),
        (("CHINA", "CSI", "GREATER CHINA"), "MCHI", "China"),
        (("JAPAN", "NIKKEI", "JAPON"), "EWJ", "Japon"),
        (("EURO", "EUROPE", "EUROPA"), "VGK", "Europa"),
        (("EMERGING", "EMERGENTE"), "EEM", "mercados emergentes"),
        (("LATIN", "LATAM", "BRAZIL", "BRASIL"), "ILF", "Latinoamerica"),
        (("TECH", "DIGITAL", "CLOUD", "SEMICON"), "XLK", "tecnologia"),
        (("ENERGY", "OIL", "GAS"), "XLE", "energia"),
        (("MINING", "MINER", "COPPER", "COBRE"), "COPX", "mineria/cobre"),
        (("GOLD", "ORO"), "GLD", "oro"),
        (("BOND", "TREASURY", "CREDIT", "DEBT", "FIXED"), "LQD", "renta fija global"),
        (("INFRA", "INFRASTRUCTURE"), "IGF", "infraestructura"),
        (("PRIVATE", "PRIV", "EQT", "ANTIN", "CINVEN", "PLATINUM", "HAMILTON"), "proxy_alternativos", "alternativos privados"),
    ]
    for claves, proxy, categoria in reglas:
        if any(clave in t for clave in claves):
            return proxy, categoria

    if moneda == "USD":
        return "ACWI", "renta variable global USD"
    if moneda in {"EUR", "GBP", "JPY"}:
        return "ACWI+FX", "global exterior con tipo de cambio"
    if moneda == "PEN":
        return "BVL/PEN", "mercado local pendiente"
    return "proxy_pendiente", "pendiente clasificacion"


def mapear_instrumentos(base: pd.DataFrame, cache: dict[str, Any]) -> pd.DataFrame:
    filas = []
    for _, fila in base.iterrows():
        instrumento_id = str(fila.get("instrumento_id", "")).strip()
        moneda = str(fila.get("moneda", "")).strip().upper()
        texto = " ".join(
            str(fila.get(c, ""))
            for c in ["instrumento_id", "entidad_administradora", "grupo"]
        )

        datos = (cache.get(instrumento_id) or {}).get("data") or []
        figi = elegir_figi(datos)

        ticker = ""
        nombre = ""
        exchange = ""
        tipo = ""
        estado = "proxy_pendiente"
        fuente = "proxy"
        proxy, categoria_proxy = proxy_por_texto(texto, moneda)
        nota = "Sin match OpenFIGI; usar proxy por categoria."

        if instrumento_id.upper().startswith("PRIV"):
            estado = "proxy_privado"
            fuente = "proxy"
            proxy = "proxy_alternativos"
            categoria_proxy = "alternativos privados"
            nota = "Instrumento privado: no tendra precio intradia directo."
        elif figi:
            ticker = str(figi.get("ticker") or "")
            nombre = str(figi.get("name") or figi.get("securityDescription") or "")
            exchange = str(figi.get("exchCode") or "")
            tipo = str(figi.get("securityType2") or figi.get("securityType") or "")
            proxy, categoria_proxy = proxy_por_texto(nombre + " " + texto, moneda)
            if exchange == "US" and ticker:
                estado = "ticker_intradia_probable"
                fuente = "yfinance"
                nota = "Ticker US: candidato directo para precio intradia."
            elif ticker:
                estado = "ticker_no_us_requiere_fuente"
                fuente = "openfigi_mas_proxy"
                nota = "Tiene ticker, pero falta confirmar proveedor intradia."

        nueva = fila.to_dict()
        nueva.update(
            {
                "ticker_openfigi": ticker,
                "nombre_openfigi": nombre,
                "exchange_openfigi": exchange,
                "tipo_openfigi": tipo,
                "proxy_sugerido": proxy,
                "categoria_proxy": categoria_proxy,
                "fuente_precio_propuesta": fuente,
                "estado_mapeo_precio": estado,
                "nota_mapeo": nota,
            }
        )
        filas.append(nueva)

    return pd.DataFrame(filas)


def resumen_mapeo(mapeo: pd.DataFrame) -> pd.DataFrame:
    x = mapeo.copy()
    x["peso_fondo"] = pd.to_numeric(x["peso_fondo"], errors="coerce").fillna(0.0)
    rows = []
    for afp in AFPS:
        a = x[x["afp"].eq(afp)]
        total = a["peso_fondo"].sum()
        directo = a.loc[a["estado_mapeo_precio"].eq("ticker_intradia_probable"), "peso_fondo"].sum()
        no_us = a.loc[a["estado_mapeo_precio"].eq("ticker_no_us_requiere_fuente"), "peso_fondo"].sum()
        privado = a.loc[a["estado_mapeo_precio"].eq("proxy_privado"), "peso_fondo"].sum()
        pendiente = a.loc[a["estado_mapeo_precio"].eq("proxy_pendiente"), "peso_fondo"].sum()
        rows.append(
            {
                "afp": afp,
                "instrumentos": int(a["instrumento_id"].nunique()),
                "peso_base_cartera_pct": total * 100.0,
                "ticker_intradia_probable_pct": directo * 100.0,
                "ticker_no_us_requiere_fuente_pct": no_us * 100.0,
                "proxy_privado_pct": privado * 100.0,
                "proxy_pendiente_pct": pendiente * 100.0,
            }
        )
    return pd.DataFrame(rows)


def top_pendientes(mapeo: pd.DataFrame, n: int = 12) -> pd.DataFrame:
    x = mapeo.copy()
    x["peso_fondo"] = pd.to_numeric(x["peso_fondo"], errors="coerce").fillna(0.0)
    return (
        x.sort_values("peso_fondo", ascending=False)
        .head(n)
        [
            [
                "afp",
                "instrumento_id",
                "moneda",
                "peso_fondo_pct",
                "ticker_openfigi",
                "exchange_openfigi",
                "proxy_sugerido",
                "estado_mapeo_precio",
                "entidad_administradora",
            ]
        ]
    )


def barras_resumen(resumen: pd.DataFrame) -> str:
    partes = []
    segmentos = [
        ("ticker_intradia_probable_pct", "Directo", "directo"),
        ("ticker_no_us_requiere_fuente_pct", "Ticker no US", "nous"),
        ("proxy_privado_pct", "Privado", "privado"),
        ("proxy_pendiente_pct", "Pendiente", "pendiente"),
    ]
    for _, fila in resumen.iterrows():
        partes.append(f"<section class='afp-card'><h3>{esc(fila['afp'])}</h3>")
        partes.append("<div class='stack'>")
        for col, label, cls in segmentos:
            valor = float(fila[col])
            width = max(0.0, min(100.0, valor))
            if width <= 0:
                continue
            partes.append(
                f"<span class='{cls}' style='width:{width:.2f}%' title='{label}: {valor:.2f}%'></span>"
            )
        partes.append("</div>")
        partes.append(
            f"""
            <div class='metrics'>
              <span>Base: <strong>{pct(fila['peso_base_cartera_pct'])}</strong></span>
              <span>Directo: <strong>{pct(fila['ticker_intradia_probable_pct'])}</strong></span>
              <span>Requiere fuente: <strong>{pct(fila['ticker_no_us_requiere_fuente_pct'])}</strong></span>
              <span>Privado/proxy: <strong>{pct(fila['proxy_privado_pct'])}</strong></span>
            </div>
            """
        )
        partes.append("</section>")
    return "\n".join(partes)


def tabla_top(df: pd.DataFrame) -> str:
    rows = []
    for _, f in df.iterrows():
        rows.append(
            f"""
            <tr>
              <td>{esc(f['afp'])}</td>
              <td>{esc(f['instrumento_id'])}</td>
              <td>{pct(f['peso_fondo_pct'])}</td>
              <td>{esc(f['ticker_openfigi']) or '-'}</td>
              <td>{esc(f['exchange_openfigi']) or '-'}</td>
              <td>{esc(f['proxy_sugerido'])}</td>
              <td>{esc(f['estado_mapeo_precio'])}</td>
            </tr>
            """
        )
    return "\n".join(rows)


def generar_visor(resumen: pd.DataFrame, top: pd.DataFrame) -> str:
    css = """
    :root {
      --bg: #eef3f8; --ink: #0b2340; --muted: #526b8a;
      --blue: #174a7c; --line: #cad8e8; --green: #11844f;
      --orange: #d78318; --violet: #7761b7; --red: #b84242;
    }
    * { box-sizing: border-box; }
    body { margin:0; font-family: Arial, Helvetica, sans-serif; background:var(--bg); color:var(--ink); }
    main { width:min(1160px, calc(100% - 32px)); margin:24px auto 48px; }
    header { background:linear-gradient(120deg,#133f70,#2d70ad); color:#fff; border-radius:8px; padding:24px 28px; }
    h1 { margin:0 0 8px; font-size:clamp(25px,4vw,34px); }
    h2 { margin:0 0 14px; font-size:22px; }
    h3 { margin:0 0 10px; font-size:18px; }
    .sub { margin:0; line-height:1.45; }
    .note { margin:18px 0; padding:14px 16px; border-left:6px solid #d7a900; background:#fff4cc; border-radius:8px; line-height:1.45; }
    .panel, .afp-card { background:#fff; border:1px solid var(--line); border-radius:8px; padding:16px; }
    .grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:14px; }
    .stack { display:flex; height:18px; overflow:hidden; background:#e7eef7; border-radius:999px; }
    .stack span { display:block; height:100%; }
    .directo { background:var(--green); }
    .nous { background:var(--orange); }
    .privado { background:var(--violet); }
    .pendiente { background:var(--red); }
    .metrics { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:6px 10px; margin-top:12px; color:var(--muted); font-size:13px; }
    .legend { display:flex; flex-wrap:wrap; gap:10px; color:var(--muted); font-size:13px; margin:10px 0 0; }
    .legend span::before { content:""; display:inline-block; width:11px; height:11px; border-radius:50%; margin-right:6px; vertical-align:-1px; background:#999; }
    .legend .l1::before { background:var(--green); }
    .legend .l2::before { background:var(--orange); }
    .legend .l3::before { background:var(--violet); }
    .legend .l4::before { background:var(--red); }
    table { width:100%; border-collapse:collapse; background:#fff; border:1px solid var(--line); border-radius:8px; overflow:hidden; }
    th, td { padding:10px 11px; border-bottom:1px solid #e7eef6; text-align:left; font-size:14px; }
    th { background:#f7f9fc; color:#244766; }
    .steps { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:14px; }
    .step { background:#fff; border:1px solid var(--line); border-radius:8px; padding:14px; }
    .step strong { display:block; margin-bottom:6px; }
    @media(max-width:850px){ .grid,.steps{grid-template-columns:1fr;} .metrics{grid-template-columns:1fr;} th,td{font-size:13px;padding:8px;} }
    """
    return f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Proyecto cartera replicante Fondo 3</title>
  <style>{css}</style>
</head>
<body>
<main>
  <header>
    <h1>Proyecto cartera replicante Fondo 3</h1>
    <p class="sub">Visor independiente para construir el modelo intradia basado en la cartera real publicada por SBS.</p>
  </header>

  <section class="note">
    Este visor no reemplaza el monitor diario. Sirve para seguir el nuevo proyecto: identificar instrumentos, mapearlos a ticker o proxy y medir cuanta cartera puede valorizarse intradia.
  </section>

  <section class="panel">
    <h2>Estado del mapeo inicial</h2>
    <div class="legend">
      <span class="l1">Ticker intradia probable</span>
      <span class="l2">Ticker no US requiere fuente</span>
      <span class="l3">Privado/proxy</span>
      <span class="l4">Pendiente</span>
    </div>
  </section>

  <section class="grid">
    {barras_resumen(resumen)}
  </section>

  <section class="note">
    Siguiente parte correcta: confirmar los tickers directos, elegir proveedor para instrumentos no US y asignar proxy a fondos privados o instrumentos sin precio intradia.
  </section>

  <section class="panel">
    <h2>Instrumentos de mayor peso para revisar primero</h2>
    <table>
      <thead>
        <tr>
          <th>AFP</th><th>Instrumento</th><th>Peso</th><th>Ticker</th><th>Bolsa</th><th>Proxy</th><th>Estado</th>
        </tr>
      </thead>
      <tbody>{tabla_top(top)}</tbody>
    </table>
  </section>

  <section class="steps" style="margin-top:16px">
    <div class="step"><strong>1. Mapear</strong>ISIN o instrumento SBS a ticker, fuente o proxy.</div>
    <div class="step"><strong>2. Valorizar</strong>Descargar precios intradia y calcular peso por movimiento.</div>
    <div class="step"><strong>3. Evaluar</strong>Comparar contra cuota SBS cuando se publique.</div>
  </section>
</main>
</body>
</html>"""


def main() -> None:
    raiz = Path(__file__).resolve().parents[1]
    processed = raiz / "data" / "processed"
    base = leer_csv(processed / "cartera_replicante_intradia_base_ultimo_mes.csv")
    cache = cargar_json(processed / "ca0001_openfigi_cache_isin.json")

    mapeo = mapear_instrumentos(base, cache)
    resumen = resumen_mapeo(mapeo)
    top = top_pendientes(mapeo)

    escribir_csv(mapeo, processed / "cartera_replicante_intradia_mapeo_inicial.csv")
    escribir_csv(resumen, processed / "cartera_replicante_intradia_resumen_mapeo.csv")

    visor = generar_visor(resumen, top)
    (processed / "cartera_replicante_visor.html").write_text(visor, encoding="utf-8")

    print("Mapeo inicial creado")
    print(resumen.to_string(index=False))


if __name__ == "__main__":
    main()

