from __future__ import annotations

import html
from pathlib import Path

import pandas as pd


AFPS = ["Habitat", "Integra", "Prima", "Profuturo"]


def leer_csv(ruta: Path) -> pd.DataFrame:
    if not ruta.exists():
        raise FileNotFoundError(f"No existe: {ruta}")
    return pd.read_csv(ruta)


def pct(valor: object, decimales: int = 2) -> str:
    x = pd.to_numeric(valor, errors="coerce")
    if pd.isna(x):
        return "-"
    return f"{x:.{decimales}f}%"


def num(valor: object, decimales: int = 4) -> str:
    x = pd.to_numeric(valor, errors="coerce")
    if pd.isna(x):
        return "-"
    return f"{x:.{decimales}f}"


def esc(valor: object) -> str:
    if pd.isna(valor):
        return ""
    return html.escape(str(valor))


def etiqueta_modelo(modelo: str) -> str:
    if "Actual monitor" in modelo:
        return "Monitor actual"
    if "M1_pesos_reales" in modelo:
        return "Pesos reales"
    if "M2_hibrido" in modelo:
        return "Hibrido"
    if "M0_sin_pesos" in modelo:
        return "Sin pesos"
    return modelo


def preparar(comparativa: pd.DataFrame) -> pd.DataFrame:
    df = comparativa.copy()
    df["rmse_retorno"] = pd.to_numeric(df["rmse_retorno"], errors="coerce")
    df["mae_retorno"] = pd.to_numeric(df["mae_retorno"], errors="coerce")
    df["direccion_pct"] = pd.to_numeric(df["direccion_pct"], errors="coerce")
    df["r2"] = pd.to_numeric(df["r2"], errors="coerce")
    df["mape_cuota_pct"] = pd.to_numeric(df["mape_cuota_pct"], errors="coerce")
    df["correlacion"] = pd.to_numeric(df.get("correlacion"), errors="coerce")
    df["modelo_corto"] = df["modelo"].map(etiqueta_modelo)
    return df


def ganadores_por_afp(df: pd.DataFrame) -> pd.DataFrame:
    filas = []
    for afp in AFPS:
        x = df[df["afp"].eq(afp)].copy()
        if x.empty:
            continue
        actual = x[x["familia_comparacion"].eq("modelo_actual_monitor")]
        pesos = x[x["familia_comparacion"].eq("mejor_modelo_pesos_reales")]
        fila_actual = actual.iloc[0] if not actual.empty else None
        fila_pesos = pesos.iloc[0] if not pesos.empty else None

        if fila_actual is not None and fila_pesos is not None:
            ganador_error = (
                fila_actual
                if fila_actual["rmse_retorno"] <= fila_pesos["rmse_retorno"]
                else fila_pesos
            )
            ganador_dir = (
                fila_actual
                if fila_actual["direccion_pct"] >= fila_pesos["direccion_pct"]
                else fila_pesos
            )
            decision = (
                "Mantener monitor actual"
                if ganador_error["familia_comparacion"] == "modelo_actual_monitor"
                else "Seguir cartera/pesos reales"
            )
        else:
            ganador_error = x.sort_values("rmse_retorno").iloc[0]
            ganador_dir = x.sort_values("direccion_pct", ascending=False).iloc[0]
            decision = "Revisar datos"

        filas.append(
            {
                "afp": afp,
                "modelo_menor_error": ganador_error["modelo_corto"],
                "rmse": ganador_error["rmse_retorno"],
                "modelo_mejor_direccion": ganador_dir["modelo_corto"],
                "direccion": ganador_dir["direccion_pct"],
                "decision": decision,
            }
        )
    return pd.DataFrame(filas)


def barras_modelo(df: pd.DataFrame, metrica: str, menor_mejor: bool) -> str:
    valores = pd.to_numeric(df[metrica], errors="coerce")
    maximo = valores.max(skipna=True)
    if pd.isna(maximo) or maximo <= 0:
        maximo = 1.0

    partes = []
    for afp in AFPS:
        x = df[df["afp"].eq(afp)]
        if x.empty:
            continue
        partes.append(f'<section class="mini-panel"><h3>{esc(afp)}</h3>')
        for _, fila in x.iterrows():
            valor = fila[metrica]
            ancho = max(4, min(100, float(valor) / maximo * 100)) if pd.notna(valor) else 4
            clase = "good" if (
                (menor_mejor and valor == x[metrica].min())
                or ((not menor_mejor) and valor == x[metrica].max())
            ) else ""
            texto = num(valor, 4) if metrica != "direccion_pct" else pct(valor, 2)
            partes.append(
                f"""
                <div class="bar-row">
                  <div class="bar-label">{esc(fila['modelo_corto'])}</div>
                  <div class="bar-track"><span class="{clase}" style="width:{ancho:.1f}%"></span></div>
                  <div class="bar-value">{texto}</div>
                </div>
                """
            )
        partes.append("</section>")
    return "\n".join(partes)


def tabla_decision(ganadores: pd.DataFrame) -> str:
    filas = []
    for _, fila in ganadores.iterrows():
        filas.append(
            f"""
            <tr>
              <td>{esc(fila['afp'])}</td>
              <td>{esc(fila['modelo_menor_error'])}</td>
              <td>{num(fila['rmse'], 4)}</td>
              <td>{esc(fila['modelo_mejor_direccion'])}</td>
              <td>{pct(fila['direccion'], 2)}</td>
              <td><strong>{esc(fila['decision'])}</strong></td>
            </tr>
            """
        )
    return "\n".join(filas)


def generar_html(df: pd.DataFrame, ganadores: pd.DataFrame) -> str:
    css = """
    :root {
      --azul: #174a7c;
      --azul2: #2f73b7;
      --fondo: #eef3f9;
      --linea: #cbd9ea;
      --texto: #0b2340;
      --muted: #526b8a;
      --verde: #0f8a4b;
      --amarillo: #fff4cc;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Arial, Helvetica, sans-serif;
      color: var(--texto);
      background: var(--fondo);
    }
    .wrap {
      width: min(1200px, calc(100% - 32px));
      margin: 24px auto 48px;
    }
    header {
      background: linear-gradient(120deg, var(--azul), var(--azul2));
      color: white;
      border-radius: 8px;
      padding: 24px 28px;
    }
    h1 { margin: 0 0 8px; font-size: clamp(26px, 4vw, 36px); }
    .sub { margin: 0; font-size: 16px; line-height: 1.45; }
    .nav {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin: 14px 0 18px;
    }
    .nav a {
      color: var(--azul);
      background: white;
      border: 1px solid var(--linea);
      border-radius: 6px;
      padding: 10px 12px;
      text-decoration: none;
      font-weight: 700;
    }
    .note {
      background: var(--amarillo);
      border-left: 6px solid #d7a900;
      border-radius: 8px;
      padding: 14px 16px;
      margin: 18px 0;
      line-height: 1.45;
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 16px;
      margin-top: 16px;
    }
    .panel, .mini-panel {
      background: white;
      border: 1px solid var(--linea);
      border-radius: 8px;
      padding: 16px;
    }
    .panel h2, .mini-panel h3 {
      margin: 0 0 12px;
      font-size: 20px;
    }
    .mini-panel h3 { font-size: 16px; }
    .bar-row {
      display: grid;
      grid-template-columns: 120px 1fr 72px;
      gap: 10px;
      align-items: center;
      margin: 10px 0;
      min-height: 24px;
    }
    .bar-label, .bar-value { font-size: 13px; color: var(--muted); }
    .bar-value { text-align: right; font-variant-numeric: tabular-nums; }
    .bar-track {
      height: 12px;
      background: #e8eef6;
      border-radius: 999px;
      overflow: hidden;
    }
    .bar-track span {
      display: block;
      height: 100%;
      background: #7b9bc2;
    }
    .bar-track span.good { background: var(--verde); }
    table {
      width: 100%;
      border-collapse: collapse;
      background: white;
      border: 1px solid var(--linea);
      border-radius: 8px;
      overflow: hidden;
    }
    th, td {
      padding: 10px 12px;
      border-bottom: 1px solid #e6edf5;
      text-align: left;
      font-size: 14px;
    }
    th { background: #f7f9fc; color: #244766; }
    tr:last-child td { border-bottom: none; }
    .small { color: var(--muted); font-size: 13px; line-height: 1.4; }
    @media (max-width: 860px) {
      .grid { grid-template-columns: 1fr; }
      .bar-row { grid-template-columns: 92px 1fr 62px; }
      th, td { font-size: 13px; padding: 9px; }
    }
    """

    return f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Comparativa de modelos Fondo 3</title>
  <style>{css}</style>
</head>
<body>
  <main class="wrap">
    <header>
      <h1>Comparativa de modelos Fondo 3</h1>
      <p class="sub">Resumen visual para decidir que modelo conviene seguir desarrollando.</p>
    </header>

    <nav class="nav">
      <a href="./index.html">Monitor</a>
      <a href="./vela-intradia.html">Vela intradia</a>
      <a href="./simulador.html">Simulador</a>
      <a href="./modelos.html">Modelos</a>
    </nav>

    <section class="note">
      El modelo actual se mantiene como referencia. Los modelos con pesos reales muestran si la cartera publicada por SBS puede mejorar la estimacion. La decision final debe hacerse comparando todos los modelos en el mismo periodo y con la misma regla.
    </section>

    <section class="panel">
      <h2>Decision rapida por AFP</h2>
      <table>
        <thead>
          <tr>
            <th>AFP</th>
            <th>Menor error</th>
            <th>RMSE</th>
            <th>Mejor direccion</th>
            <th>Direccion</th>
            <th>Lectura</th>
          </tr>
        </thead>
        <tbody>
          {tabla_decision(ganadores)}
        </tbody>
      </table>
      <p class="small">RMSE menor es mejor. Direccion mayor es mejor.</p>
    </section>

    <section class="grid">
      <div class="panel">
        <h2>Error por modelo</h2>
        {barras_modelo(df, "rmse_retorno", menor_mejor=True)}
      </div>
      <div class="panel">
        <h2>Acierto de direccion</h2>
        {barras_modelo(df, "direccion_pct", menor_mejor=False)}
      </div>
    </section>

    <section class="note">
      Lectura actual: el monitor actual tiene mejor error y direccion en estas tablas. Los pesos reales son prometedores, pero todavia deben convertirse en una cartera replicante intradia completa y evaluarse con la misma prueba.
    </section>
  </main>
</body>
</html>
"""


def main() -> None:
    raiz = Path(__file__).resolve().parents[1]
    processed = raiz / "data" / "processed"

    comparativa = leer_csv(processed / "comparativa_metricas_modelos_resumen.csv")
    df = preparar(comparativa)
    ganadores = ganadores_por_afp(df)
    html_text = generar_html(df, ganadores)

    salida = processed / "comparativa_metricas_modelos.html"
    salida.write_text(html_text, encoding="utf-8")
    print(f"Vista creada: {salida}")


if __name__ == "__main__":
    main()

