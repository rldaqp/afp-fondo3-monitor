from __future__ import annotations

import html
import json
from pathlib import Path

import numpy as np
import pandas as pd


AFPS = ["Habitat", "Integra", "Prima", "Profuturo"]


def leer_csv(ruta: Path) -> pd.DataFrame:
    if not ruta.exists():
        return pd.DataFrame()
    return pd.read_csv(ruta)


def fmt_pct(valor: object, dec: int = 2, signed: bool = False) -> str:
    num = pd.to_numeric(valor, errors="coerce")
    if pd.isna(num):
        return "-"
    prefijo = "+" if signed and num > 0 else ""
    return f"{prefijo}{num:.{dec}f}%"


def fmt_pp(valor: object, dec: int = 2) -> str:
    num = pd.to_numeric(valor, errors="coerce")
    if pd.isna(num):
        return "-"
    prefijo = "+" if num > 0 else ""
    return f"{prefijo}{num:.{dec}f} pp"


def fmt_num(valor: object, dec: int = 4) -> str:
    num = pd.to_numeric(valor, errors="coerce")
    if pd.isna(num):
        return "-"
    return f"{num:.{dec}f}"


def fmt_int(valor: object) -> str:
    num = pd.to_numeric(valor, errors="coerce")
    if pd.isna(num):
        return "-"
    return str(int(num))


def fmt_fecha(valor: object) -> str:
    fecha = pd.to_datetime(valor, errors="coerce")
    if pd.isna(fecha):
        return "-"
    return fecha.date().isoformat()


def fmt_fecha_corta(valor: object) -> str:
    fecha = pd.to_datetime(valor, errors="coerce")
    if pd.isna(fecha):
        return "-"
    return fecha.strftime("%d/%m")


def esc(valor: object) -> str:
    if pd.isna(valor):
        return "-"
    return html.escape(str(valor))


def badge(texto: object, clase: str = "") -> str:
    valor = esc(texto)
    clase_extra = f" {clase}" if clase else ""
    return f'<span class="badge{clase_extra}">{valor}</span>'


def badge_confianza(valor: object) -> str:
    texto = "" if pd.isna(valor) else str(valor)
    clases = {
        "Verde": "ok",
        "Amarillo": "warn",
        "Gris": "muted",
    }
    return badge(texto or "-", clases.get(texto, "muted"))


def badge_resultado(valor: object) -> str:
    texto = "" if pd.isna(valor) else str(valor)
    clases = {
        "Acierto": "ok",
        "Fallo": "bad",
        "Pendiente SBS": "wait",
        "Pasa": "ok",
    }
    return badge(texto or "-", clases.get(texto, "muted"))


def badge_direccion(valor: object) -> str:
    texto = "" if pd.isna(valor) else str(valor)
    return badge(texto or "-", "up" if texto == "Sube" else "down")


def card(titulo: str, valor: str, detalle: str = "") -> str:
    return f"""
      <article class="kpi">
        <span>{html.escape(titulo)}</span>
        <strong>{valor}</strong>
        <small>{html.escape(detalle)}</small>
      </article>
    """


def tabla_senal(ultima: pd.DataFrame) -> str:
    filas = []
    for _, row in ultima.sort_values("afp").iterrows():
        filas.append(
            "<tr>"
            f"<td>{esc(row.get('afp'))}</td>"
            f"<td>{fmt_fecha(row.get('fecha_base_sbs'))}</td>"
            f"<td>{fmt_fecha(row.get('fecha'))}</td>"
            f"<td>{fmt_int(row.get('ruedas_estimadas_desde_sbs'))}</td>"
            f"<td>{badge_direccion(row.get('direccion_estimada'))}</td>"
            f"<td>{badge_confianza(row.get('confianza'))}</td>"
            f"<td>{esc(row.get('usar_senal'))}</td>"
            f"<td>{fmt_pct(row.get('retorno_estimado_pct'), 3, signed=True)}</td>"
            f"<td>{fmt_pct(row.get('retorno_acumulado_estimado_desde_sbs_pct'), 3, signed=True)}</td>"
            f"<td>{fmt_num(row.get('cuota_estimada'))}</td>"
            f"<td>{fmt_num(row.get('sbs_publicada'))}</td>"
            f"<td>{fmt_num(row.get('error_cuota'))}</td>"
            f"<td>{badge_resultado(row.get('resultado'))}</td>"
            "</tr>"
        )
    return """
      <table>
        <thead>
          <tr>
            <th>AFP</th><th>Fecha SBS base</th><th>Fecha a comprobar</th><th>Ruedas acum.</th>
            <th>Direccion</th><th>Confianza</th><th>Usar</th><th>Ret. dia</th>
            <th>Ret. acum.</th><th>Cuota estimada</th><th>SBS publicada</th><th>Error cuota</th><th>Estado</th>
          </tr>
        </thead>
        <tbody>
    """ + "\n".join(filas) + """
        </tbody>
      </table>
    """


def tabla_metricas(resumen: pd.DataFrame) -> str:
    filas = []
    for _, row in resumen.sort_values("afp").iterrows():
        pasa = "Pasa" if str(row.get("cumple_72_test")).lower() == "true" else "No pasa"
        filas.append(
            "<tr>"
            f"<td>{esc(row.get('afp'))}</td>"
            f"<td>{fmt_pct(row.get('direccion_test'))}</td>"
            f"<td>{fmt_pct(row.get('direccion_base_test'))}</td>"
            f"<td>{fmt_pp(row.get('delta_dir_test_vs_base'))}</td>"
            f"<td>{fmt_num(row.get('rmse_test'))}</td>"
            f"<td>{fmt_pct(row.get('direccion_alta_confianza_test'))}</td>"
            f"<td>{fmt_pct(row.get('cobertura_alta_confianza_pct'))}</td>"
            f"<td>{badge_resultado(pasa)}</td>"
            "</tr>"
        )
    return """
      <table>
        <thead>
          <tr>
            <th>AFP</th><th>Dir. test</th><th>Dir. antes</th><th>Mejora</th>
            <th>RMSE cuota</th><th>Dir. senal fuerte</th><th>Dias con senal fuerte</th><th>Resultado</th>
          </tr>
        </thead>
        <tbody>
    """ + "\n".join(filas) + """
        </tbody>
      </table>
    """


def tabla_bitacora(bitacora: pd.DataFrame) -> str:
    filas = []
    bitacora = bitacora.sort_values(["afp", "fecha"]).groupby("afp", as_index=False).tail(5)
    bitacora = bitacora.sort_values(["fecha", "afp"], ascending=[False, True])
    for _, row in bitacora.iterrows():
        filas.append(
            "<tr>"
            f"<td>{fmt_fecha(row.get('fecha'))}</td>"
            f"<td>{esc(row.get('afp'))}</td>"
            f"<td>{fmt_fecha(row.get('fecha_base_sbs'))}</td>"
            f"<td>{fmt_int(row.get('ruedas_estimadas_desde_sbs'))}</td>"
            f"<td>{badge_direccion(row.get('direccion_estimada'))}</td>"
            f"<td>{badge_confianza(row.get('confianza'))}</td>"
            f"<td>{fmt_num(row.get('cuota_estimada'))}</td>"
            f"<td>{fmt_num(row.get('sbs_publicada'))}</td>"
            f"<td>{fmt_num(row.get('error_cuota'))}</td>"
            f"<td>{fmt_pct(row.get('error_abs_pct'))}</td>"
            f"<td>{badge_resultado(row.get('resultado'))}</td>"
            "</tr>"
        )
    return """
      <table>
        <thead>
          <tr>
            <th>Fecha</th><th>AFP</th><th>SBS base</th><th>Ruedas</th><th>Senal</th><th>Confianza</th>
            <th>Cuota estimada</th><th>SBS publicada</th><th>Error cuota</th><th>Error %</th><th>Revision</th>
          </tr>
        </thead>
        <tbody>
    """ + "\n".join(filas) + """
        </tbody>
      </table>
    """


def tabla_pendientes(bitacora: pd.DataFrame) -> str:
    pendientes = bitacora[bitacora["sbs_publicada"].isna()].copy()
    if pendientes.empty:
        return "<p>No hay cuotas pendientes de SBS en este momento.</p>"
    pendientes = pendientes.sort_values(["fecha", "afp"])
    filas = []
    for _, row in pendientes.iterrows():
        filas.append(
            "<tr>"
            f"<td>{fmt_fecha(row.get('fecha'))}</td>"
            f"<td>{esc(row.get('afp'))}</td>"
            f"<td>{fmt_fecha(row.get('fecha_base_sbs'))}</td>"
            f"<td>{fmt_int(row.get('ruedas_estimadas_desde_sbs'))}</td>"
            f"<td>{fmt_pct(row.get('retorno_estimado_pct'), 3, signed=True)}</td>"
            f"<td>{fmt_pct(row.get('retorno_acumulado_estimado_desde_sbs_pct'), 3, signed=True)}</td>"
            f"<td>{fmt_num(row.get('cuota_estimada'))}</td>"
            f"<td>{fmt_num(row.get('sbs_publicada'))}</td>"
            f"<td>{fmt_num(row.get('error_cuota'))}</td>"
            "</tr>"
        )
    return """
      <table>
        <thead>
          <tr>
            <th>Fecha pendiente</th><th>AFP</th><th>SBS base</th><th>Ruedas</th>
            <th>Ret. dia</th><th>Ret. acum.</th><th>Cuota estimada</th>
            <th>SBS publicada</th><th>Error cuota</th>
          </tr>
        </thead>
        <tbody>
    """ + "\n".join(filas) + """
        </tbody>
      </table>
    """


def preparar_datos_grafico(grafico: pd.DataFrame) -> str:
    cols = [
        "fecha",
        "afp",
        "sbs_publicada",
        "modelo_overlay_estimado",
        "cuota_base",
        "fecha_base_sbs",
        "cuota_base_sbs",
        "ruedas_estimadas_desde_sbs",
        "retorno_estimado_pct",
        "retorno_acumulado_estimado_desde_sbs_pct",
        "direccion_estimada",
        "resultado",
    ]
    datos = {afp: [] for afp in AFPS}
    if grafico.empty:
        return json.dumps(datos, ensure_ascii=False)

    tmp = grafico.copy()
    tmp["fecha"] = pd.to_datetime(tmp["fecha"], errors="coerce")
    tmp = tmp.dropna(subset=["fecha"]).sort_values(["afp", "fecha"])
    for afp, g in tmp.groupby("afp", sort=True):
        if afp not in datos:
            continue
        for _, row in g.iterrows():
            item = {}
            for col in cols:
                valor = row.get(col)
                if col == "fecha" or col == "fecha_base_sbs":
                    item[col] = fmt_fecha(valor)
                else:
                    num = pd.to_numeric(valor, errors="coerce")
                    item[col] = None if pd.isna(num) else float(num)
                    if col in ["direccion_estimada", "resultado"]:
                        item[col] = None if pd.isna(valor) else str(valor)
            datos[str(afp)].append(item)
    return json.dumps(datos, ensure_ascii=False)


def grafico_terminal() -> str:
    botones = "\n".join(
        f'<button class="afp-tab{" active" if i == 0 else ""}" type="button" data-afp="{html.escape(afp)}">{html.escape(afp)}</button>'
        for i, afp in enumerate(AFPS)
    )
    return f"""
      <div class="terminal-chart">
        <div class="terminal-toolbar">
          <div class="afp-tabs">{botones}</div>
          <div class="chart-status">
            <span id="chart-afp">Habitat</span>
            <span id="chart-date">-</span>
            <span>SBS <strong id="chart-sbs">-</strong></span>
            <span>Modelo <strong id="chart-model">-</strong></span>
            <span id="chart-pending">-</span>
          </div>
        </div>
        <div class="chart-layout">
          <div class="terminal-frame">
            <svg id="quota-chart" viewBox="0 0 980 430" role="img" aria-label="Grafica interactiva SBS vs modelo"></svg>
          </div>
          <aside id="chart-detail" class="chart-detail" aria-live="polite">
            <span class="detail-kicker">Detalle</span>
            <strong>Selecciona un punto</strong>
            <p>Mueve el mouse o toca la grafica para ver fecha y cuota estimada.</p>
          </aside>
        </div>
        <p class="terminal-help">Mueve el mouse o toca la grafica. El detalle aparece a la derecha y los valores exactos tambien estan abajo en la tabla.</p>
      </div>
    """


def script_grafico(grafico: pd.DataFrame) -> str:
    datos = preparar_datos_grafico(grafico)
    script = r"""
    <script>
    const CHART_DATA = __CHART_DATA__;
    const AFPS = ["Habitat", "Integra", "Prima", "Profuturo"];
    const svg = document.getElementById("quota-chart");
    const detail = document.getElementById("chart-detail");
    const statusAfp = document.getElementById("chart-afp");
    const statusDate = document.getElementById("chart-date");
    const statusSbs = document.getElementById("chart-sbs");
    const statusModel = document.getElementById("chart-model");
    const statusPending = document.getElementById("chart-pending");
    const NS = "http://www.w3.org/2000/svg";
    const box = { w: 980, h: 430, l: 72, r: 34, t: 28, b: 54 };
    let activeAfp = "Habitat";
    let activePoints = [];

    function fmtNum(v) {
      return v === null || Number.isNaN(v) ? "-" : Number(v).toFixed(4);
    }

    function fmtPct(v) {
      if (v === null || Number.isNaN(v)) return "-";
      const n = Number(v);
      return `${n > 0 ? "+" : ""}${n.toFixed(3)}%`;
    }

    function fmtDateShort(iso) {
      if (!iso || iso === "-") return "-";
      const [y, m, d] = iso.split("-");
      return `${d}/${m}`;
    }

    function el(tag, attrs = {}, text = "") {
      const node = document.createElementNS(NS, tag);
      for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
      if (text) node.textContent = text;
      return node;
    }

    function valuesFor(rows) {
      const vals = [];
      rows.forEach(r => {
        if (r.sbs_publicada !== null) vals.push(r.sbs_publicada);
        if (r.modelo_overlay_estimado !== null) vals.push(r.modelo_overlay_estimado);
      });
      return vals;
    }

    function yScale(value, min, max) {
      const inner = box.h - box.t - box.b;
      return box.t + (max - value) / Math.max(max - min, 0.000001) * inner;
    }

    function xScale(index, total) {
      const inner = box.w - box.l - box.r;
      return box.l + index / Math.max(total - 1, 1) * inner;
    }

    function pathFor(points) {
      return points.map((p, i) => `${i === 0 ? "M" : "L"}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ");
    }

    function addPath(points, cls) {
      if (points.length < 2) return;
      svg.appendChild(el("path", { d: pathFor(points), class: cls }));
    }

    function addCircle(p, cls) {
      svg.appendChild(el("circle", { cx: p.x, cy: p.y, r: 4.4, class: cls }));
    }

    function renderGrid(min, max, rows) {
      const plotBottom = box.h - box.b;
      const plotRight = box.w - box.r;
      for (let i = 0; i <= 5; i += 1) {
        const y = box.t + (plotBottom - box.t) * i / 5;
        svg.appendChild(el("line", { x1: box.l, y1: y, x2: plotRight, y2: y, class: "grid-line" }));
        const value = max - (max - min) * i / 5;
        svg.appendChild(el("text", { x: box.l - 10, y: y + 4, "text-anchor": "end", class: "axis-label" }, value.toFixed(4)));
      }
      const tickIndexes = [0, Math.floor((rows.length - 1) / 2), rows.length - 1].filter((v, i, a) => a.indexOf(v) === i);
      tickIndexes.forEach(idx => {
        const x = xScale(idx, rows.length);
        svg.appendChild(el("line", { x1: x, y1: box.t, x2: x, y2: plotBottom, class: "grid-line vertical" }));
        svg.appendChild(el("text", { x, y: plotBottom + 26, "text-anchor": "middle", class: "axis-label" }, fmtDateShort(rows[idx].fecha)));
      });
      svg.appendChild(el("rect", { x: box.l, y: box.t, width: plotRight - box.l, height: plotBottom - box.t, class: "plot-border" }));
    }

    function rowToPoint(row, index, min, max, key) {
      const value = row[key];
      if (value === null || Number.isNaN(value)) return null;
      return {
        x: xScale(index, activePoints.length),
        y: yScale(value, min, max),
        value,
        row,
        index
      };
    }

    function updateStatus(row) {
      statusAfp.textContent = activeAfp;
      statusDate.textContent = row ? row.fecha : "-";
      statusSbs.textContent = row ? fmtNum(row.sbs_publicada) : "-";
      statusModel.textContent = row ? fmtNum(row.modelo_overlay_estimado) : "-";
      if (!row) {
        statusPending.textContent = "-";
        statusPending.className = "";
        return;
      }
      const pending = row.sbs_publicada === null;
      statusPending.textContent = pending ? `Pendiente SBS, ${row.ruedas_estimadas_desde_sbs || "-"} rueda(s)` : "Con SBS";
      statusPending.className = pending ? "pending-pill" : "ok-pill";
    }

    function updateDetail(row) {
      if (!row) {
        detail.innerHTML = `
          <span class="detail-kicker">Detalle</span>
          <strong>Sin dato seleccionado</strong>
          <p>Mueve el mouse o toca la grafica.</p>
        `;
        return;
      }
      const pending = row.sbs_publicada === null;
      detail.innerHTML = `
        <span class="detail-kicker">${pending ? "Pendiente SBS" : "Con SBS"}</span>
        <strong>${activeAfp} ${row.fecha}</strong>
        <dl>
          <div><dt>SBS</dt><dd>${fmtNum(row.sbs_publicada)}</dd></div>
          <div><dt>Modelo</dt><dd>${fmtNum(row.modelo_overlay_estimado)}</dd></div>
          <div><dt>Ret. dia</dt><dd>${fmtPct(row.retorno_estimado_pct)}</dd></div>
          <div><dt>Ret. acum.</dt><dd>${fmtPct(row.retorno_acumulado_estimado_desde_sbs_pct)}</dd></div>
          <div><dt>Ruedas</dt><dd>${row.ruedas_estimadas_desde_sbs || "-"}</dd></div>
        </dl>
        <p>${pending ? "Esperando publicacion SBS para medir error." : "Ya tiene cuota SBS publicada."}</p>
      `;
      updateStatus(row);
    }

    function renderChart(afp) {
      activeAfp = afp;
      const rows = (CHART_DATA[afp] || []).filter(r => r.fecha);
      activePoints = rows;
      svg.replaceChildren();
      statusAfp.textContent = afp;
      if (!rows.length) return;

      const vals = valuesFor(rows);
      const rawMin = Math.min(...vals);
      const rawMax = Math.max(...vals);
      const pad = Math.max((rawMax - rawMin) * 0.12, 0.02);
      const min = rawMin - pad;
      const max = rawMax + pad;
      renderGrid(min, max, rows);

      const sbsPts = [];
      const modelSolid = [];
      const modelPending = [];
      rows.forEach((row, idx) => {
        const sbs = rowToPoint(row, idx, min, max, "sbs_publicada");
        const model = rowToPoint(row, idx, min, max, "modelo_overlay_estimado");
        if (sbs) sbsPts.push(sbs);
        if (model && row.sbs_publicada !== null) modelSolid.push(model);
      });
      const pendingRows = rows.filter(r => r.sbs_publicada === null && r.modelo_overlay_estimado !== null);
      if (pendingRows.length && modelSolid.length) modelPending.push(modelSolid[modelSolid.length - 1]);
      pendingRows.forEach(row => {
        const idx = rows.indexOf(row);
        const point = rowToPoint(row, idx, min, max, "modelo_overlay_estimado");
        if (point) modelPending.push(point);
      });

      addPath(sbsPts, "line-sbs");
      addPath(modelSolid, "line-model");
      addPath(modelPending, "line-pending");
      sbsPts.forEach(p => addCircle(p, "dot-sbs"));
      modelSolid.forEach(p => addCircle(p, "dot-model"));
      modelPending.slice(1).forEach(p => addCircle(p, "dot-pending"));

      const crossX = el("line", { x1: 0, y1: box.t, x2: 0, y2: box.h - box.b, class: "crosshair", visibility: "hidden" });
      const crossY = el("line", { x1: box.l, y1: 0, x2: box.w - box.r, y2: 0, class: "crosshair", visibility: "hidden" });
      svg.appendChild(crossX);
      svg.appendChild(crossY);
      const overlay = el("rect", { x: box.l, y: box.t, width: box.w - box.l - box.r, height: box.h - box.t - box.b, fill: "transparent", class: "hover-zone" });
      svg.appendChild(overlay);

      function locate(event) {
        const rect = svg.getBoundingClientRect();
        const svgX = (event.clientX - rect.left) / rect.width * box.w;
        const idx = Math.max(0, Math.min(rows.length - 1, Math.round((svgX - box.l) / (box.w - box.l - box.r) * (rows.length - 1))));
        const row = rows[idx];
        const yValue = row.modelo_overlay_estimado ?? row.sbs_publicada;
        const x = xScale(idx, rows.length);
        const y = yValue === null ? box.t : yScale(yValue, min, max);
        crossX.setAttribute("x1", x);
        crossX.setAttribute("x2", x);
        crossY.setAttribute("y1", y);
        crossY.setAttribute("y2", y);
        crossX.setAttribute("visibility", "visible");
        crossY.setAttribute("visibility", "visible");
        updateDetail(row);
      }
      overlay.addEventListener("pointermove", locate);
      overlay.addEventListener("pointerdown", locate);
      overlay.addEventListener("pointerleave", () => {
        crossX.setAttribute("visibility", "hidden");
        crossY.setAttribute("visibility", "hidden");
        updateStatus(rows[rows.length - 1]);
        updateDetail(rows[rows.length - 1]);
      });
      updateStatus(rows[rows.length - 1]);
      updateDetail(rows[rows.length - 1]);
    }

    document.querySelectorAll(".afp-tab").forEach(button => {
      button.addEventListener("click", () => {
        document.querySelectorAll(".afp-tab").forEach(b => b.classList.remove("active"));
        button.classList.add("active");
        renderChart(button.dataset.afp);
      });
    });
    renderChart(activeAfp);
    </script>
    """
    return script.replace("__CHART_DATA__", datos)


def construir_html(raiz: Path) -> str:
    processed = raiz / "data" / "processed"
    ultima = leer_csv(processed / "tablero_operativo_ultima_senal.csv")
    resumen = leer_csv(processed / "tablero_operativo_resumen_metricas.csv")
    bitacora = leer_csv(processed / "tablero_operativo_ultimos_dias.csv")
    grafico = leer_csv(processed / "tablero_operativo_grafico.csv")
    confianza = leer_csv(processed / "tablero_operativo_confianza_seleccion.csv")

    for df in [ultima, bitacora, grafico]:
        if not df.empty and "fecha" in df.columns:
            df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce")

    fecha_ultima = fmt_fecha(ultima["fecha"].max()) if not ultima.empty else "-"
    ultima_sbs = fmt_fecha(pd.to_datetime(ultima.get("fecha_base_sbs", pd.Series(dtype=str)), errors="coerce").max()) if not ultima.empty else "-"
    ruedas_max = pd.to_numeric(ultima.get("ruedas_estimadas_desde_sbs", pd.Series(dtype=float)), errors="coerce").max()
    pendientes = int((ultima.get("resultado", pd.Series(dtype=str)) == "Pendiente SBS").sum()) if not ultima.empty else 0
    pasan = int((resumen.get("cumple_72_test", pd.Series(dtype=str)).astype(str).str.lower() == "true").sum()) if not resumen.empty else 0
    dir_min = pd.to_numeric(resumen.get("direccion_test", pd.Series(dtype=float)), errors="coerce").min()
    dir_max = pd.to_numeric(resumen.get("direccion_test", pd.Series(dtype=float)), errors="coerce").max()
    conf_min = pd.to_numeric(confianza.get("direccion_test", pd.Series(dtype=float)), errors="coerce").min()
    conf_max = pd.to_numeric(confianza.get("direccion_test", pd.Series(dtype=float)), errors="coerce").max()

    css = """
    :root {
      --bg: #f4f7fb;
      --panel: #ffffff;
      --ink: #06234b;
      --muted: #4d668a;
      --line: #dbe5f2;
      --blue: #1f5fbf;
      --orange: #d46a1f;
      --green: #107c41;
      --yellow: #8a5a00;
      --red: #b42318;
      font-family: Arial, Helvetica, sans-serif;
    }
    * { box-sizing: border-box; }
    body { margin: 0; background: var(--bg); color: var(--ink); }
    main { max-width: 1180px; margin: 0 auto; padding: 28px 18px 42px; }
    header { margin-bottom: 18px; }
    h1 { margin: 0 0 8px; font-size: 30px; line-height: 1.15; letter-spacing: 0; }
    h2 { margin: 0 0 10px; font-size: 21px; letter-spacing: 0; }
    p { margin: 0; color: var(--muted); line-height: 1.45; }
    section { margin-top: 18px; background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 18px; }
    .hero { background: #ffffff; border-bottom: 1px solid var(--line); }
    .hero strong { color: var(--ink); }
    .kpis { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 12px; margin-top: 16px; }
    .kpi { background: #f8fbff; border: 1px solid var(--line); border-radius: 8px; padding: 14px; min-height: 94px; }
    .kpi span, .kpi small { display: block; color: var(--muted); }
    .kpi strong { display: block; margin: 8px 0 5px; font-size: 24px; line-height: 1.1; }
    .flow { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin-top: 12px; }
    .step { background: #f8fbff; border: 1px solid var(--line); border-radius: 8px; padding: 13px; }
    .step strong { display: block; margin-bottom: 6px; }
    .table-wrap { overflow-x: auto; }
    table { width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 14px; }
    th { text-align: left; color: #123863; background: #f4f7fb; font-weight: 700; }
    th, td { padding: 10px 9px; border-bottom: 1px solid var(--line); vertical-align: middle; }
    .badge { display: inline-flex; align-items: center; min-height: 24px; padding: 3px 9px; border-radius: 999px; background: #eef3f9; color: var(--muted); font-weight: 700; white-space: nowrap; }
    .badge.ok, .badge.up { background: #e8f5ee; color: var(--green); }
    .badge.warn, .badge.wait { background: #fff7df; color: var(--yellow); }
    .badge.bad, .badge.down { background: #fdebea; color: var(--red); }
    .badge.muted { background: #eef3f9; color: var(--muted); }
    .terminal-chart { margin-top: 12px; border: 1px solid var(--line); border-radius: 8px; overflow: hidden; background: #ffffff; color: var(--ink); }
    .terminal-toolbar { display: flex; justify-content: space-between; gap: 12px; align-items: center; padding: 10px 12px; border-bottom: 1px solid var(--line); background: #f8fbff; }
    .afp-tabs { display: flex; gap: 8px; flex-wrap: wrap; }
    .afp-tab { border: 1px solid #c8d7eb; background: #ffffff; color: #123863; border-radius: 6px; padding: 7px 10px; font-weight: 700; cursor: pointer; }
    .afp-tab.active { background: #1f5fbf; border-color: #1f5fbf; color: #ffffff; }
    .chart-status { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; color: var(--muted); font-size: 13px; }
    .chart-status strong, #chart-afp { color: var(--ink); }
    .pending-pill, .ok-pill { padding: 3px 8px; border-radius: 999px; font-weight: 700; }
    .pending-pill { color: #8a5a00; background: #fff3d4; }
    .ok-pill { color: #107c41; background: #e8f5ee; }
    .chart-layout { display: grid; grid-template-columns: minmax(0, 1fr) 260px; min-height: 440px; }
    .terminal-frame { position: relative; height: 440px; background: linear-gradient(180deg, #ffffff 0%, #f8fbff 100%); }
    #quota-chart { display: block; width: 100%; height: 100%; touch-action: none; }
    .grid-line { stroke: #e3ebf6; stroke-width: 1; }
    .grid-line.vertical { stroke-dasharray: 4 8; }
    .plot-border { fill: none; stroke: #c8d7eb; stroke-width: 1; }
    .axis-label { fill: #5d7494; font-size: 13px; }
    .line-sbs { fill: none; stroke: #1f77d0; stroke-width: 3; }
    .line-model { fill: none; stroke: #d46a1f; stroke-width: 3; }
    .line-pending { fill: none; stroke: #d46a1f; stroke-width: 3; stroke-dasharray: 8 8; }
    .dot-sbs { fill: #1f77d0; stroke: #ffffff; stroke-width: 2; }
    .dot-model { fill: #d46a1f; stroke: #ffffff; stroke-width: 2; }
    .dot-pending { fill: #f2a35e; stroke: #ffffff; stroke-width: 2; }
    .crosshair { stroke: #536f91; stroke-width: 1; stroke-dasharray: 4 5; opacity: 0.72; pointer-events: none; }
    .chart-detail { border-left: 1px solid var(--line); background: #f8fbff; padding: 16px; color: var(--ink); }
    .chart-detail .detail-kicker { display: inline-flex; margin-bottom: 10px; padding: 4px 8px; border-radius: 999px; background: #eef3f9; color: var(--muted); font-size: 12px; font-weight: 700; }
    .chart-detail strong { display: block; margin-bottom: 12px; font-size: 18px; }
    .chart-detail p { font-size: 13px; }
    .chart-detail dl { margin: 0 0 12px; display: grid; gap: 8px; }
    .chart-detail dl div { display: flex; justify-content: space-between; gap: 14px; padding-bottom: 7px; border-bottom: 1px solid var(--line); }
    .chart-detail dt { color: var(--muted); font-size: 13px; }
    .chart-detail dd { margin: 0; font-weight: 700; text-align: right; }
    .terminal-help { padding: 9px 12px 12px; color: var(--muted); font-size: 13px; border-top: 1px solid var(--line); }
    .legend { display: flex; gap: 16px; flex-wrap: wrap; margin-top: 10px; color: var(--muted); font-size: 13px; }
    .legend span::before { content: ""; display: inline-block; width: 18px; height: 3px; margin-right: 6px; vertical-align: middle; background: var(--blue); }
    .legend .model::before { background: var(--orange); }
    .legend .pending::before { background: repeating-linear-gradient(90deg, var(--orange), var(--orange) 6px, transparent 6px, transparent 10px); }
    .note { background: #f8fbff; }
    .small { font-size: 13px; }
    @media (max-width: 840px) {
      main { padding: 18px 10px 30px; }
      .kpis, .flow, .charts, .chart-layout { grid-template-columns: 1fr; }
      .chart-detail { border-left: 0; border-top: 1px solid var(--line); }
      h1 { font-size: 25px; }
      section { padding: 14px; }
    }
    """

    return f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Fondo 3 AFP - tablero operativo</title>
  <style>{css}</style>
</head>
<body>
  <main>
    <header class="hero">
      <h1>Fondo 3 AFP - tablero operativo</h1>
      <p><strong>Objetivo simple:</strong> guardar cada senal del modelo, esperar la publicacion SBS y revisar si acerto. No dice que la AFP tenga exactamente esos activos; es una cartera sintetica con proxies.</p>
      <div class="kpis">
        {card("Ultima SBS base", ultima_sbs, "desde esta cuota parte el calculo")}
        {card("Fecha a comprobar", fecha_ultima, f"{pendientes} AFP pendientes de SBS")}
        {card("Ruedas acumuladas", fmt_int(ruedas_max), "dias de mercado desde la SBS base")}
        {card("Pasan test final", f"{pasan}/4 AFP", "ultimo 20% reservado")}
        {card("Direccion test", f"{fmt_pct(dir_min)} a {fmt_pct(dir_max)}", "acierto diario fuera de muestra")}
      </div>
    </header>

    <section>
      <h2>1. Como lo probamos manana</h2>
      <div class="flow">
        <div class="step"><strong>Paso 1</strong><p>Despues del cierre de mercado se actualiza el visor. Sale una fila nueva con cuota estimada y direccion.</p></div>
        <div class="step"><strong>Paso 2</strong><p>Si la confianza es verde, la senal se puede mirar como semaforo fuerte. Amarillo es cuidado. Gris no se usa.</p></div>
        <div class="step"><strong>Paso 3</strong><p>Cuando SBS publique la misma fecha, la bitacora muestra Error cuota, Error % y cambia a Acierto o Fallo.</p></div>
      </div>
    </section>

    <section>
      <h2>2. Semaforo actual</h2>
      <p>Esta es la parte que se mira primero. Fecha SBS base es la ultima cuota oficial usada. Ruedas acum. dice si la estimacion es de 1 dia o de varios dias encadenados.</p>
      <div class="table-wrap">{tabla_senal(ultima)}</div>
    </section>

    <section>
      <h2>3. Resultado del modelo</h2>
      <p>La columna que manda es Dir. test. Compara el modelo contra el ultimo 20% que no se uso para escogerlo.</p>
      <div class="table-wrap">{tabla_metricas(resumen)}</div>
    </section>

    <section>
      <h2>4. Grafica SBS vs modelo</h2>
      <p>Azul es la cuota publicada por SBS. Naranja es lo estimado por el modelo. La parte punteada son fechas pendientes de publicacion SBS.</p>
      <div class="legend"><span>SBS</span><span class="model">Modelo</span><span class="pending">Pendiente</span></div>
      {grafico_terminal()}
    </section>

    <section>
      <h2>5. Cuotas pendientes por fecha</h2>
      <p>Aqui se ve exacto que cuota estimada corresponde a cada fecha pendiente. Si hay 2 o 3 ruedas acumuladas, lo dira en la columna Ruedas.</p>
      <div class="table-wrap">{tabla_pendientes(bitacora)}</div>
    </section>

    <section>
      <h2>6. Bitacora de comprobacion</h2>
      <p>Aqui se mide el error. Si SBS publicada esta vacio, todavia no hay contra que comparar. Cuando llegue, se llena Error cuota y Error %.</p>
      <div class="table-wrap">{tabla_bitacora(bitacora)}</div>
    </section>

    <section class="note">
      <h2>Lectura corta</h2>
      <p class="small">Hoy no buscamos llenar la pantalla de experimentos. El tablero queda para operar: senal, test, grafica y bitacora. La validacion ya paso 72% de direccion en el test final para las cuatro AFP, pero la conclusion definitiva debe seguir con control walk-forward para vigilar sobreajuste.</p>
    </section>
  </main>
  {script_grafico(grafico)}
</body>
</html>
"""


def main() -> None:
    raiz = Path(__file__).resolve().parents[1]
    html_text = construir_html(raiz)
    processed_html = raiz / "data" / "processed" / "cartera_replicante_visor.html"
    public_html = raiz / "public" / "cartera-replicante" / "index.html"
    processed_html.write_text(html_text, encoding="utf-8")
    public_html.parent.mkdir(parents=True, exist_ok=True)
    public_html.write_text(html_text, encoding="utf-8")
    print(f"Visor operativo simple generado: {public_html}")


if __name__ == "__main__":
    main()
