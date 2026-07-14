from __future__ import annotations

import importlib.util
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.preprocessing import StandardScaler


AFPS = ["Habitat", "Integra", "Prima", "Profuturo"]
TRAIN_FRAC = 0.60
VALID_FRAC = 0.20
TEST_FRAC = 0.20
ALPHAS = [0.001, 0.01, 0.1, 1.0, 10.0]
MIN_FILAS = 600
DIAS_BUFFER_DESCARGA = 70


@dataclass
class ModeloTecnico:
    imputer: SimpleImputer
    scaler: StandardScaler
    ridge: Ridge
    columnas: list[str]
    alpha: float

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        x = X[self.columnas].replace([np.inf, -np.inf], np.nan)
        z = self.scaler.transform(self.imputer.transform(x))
        return self.ridge.predict(z)


def cargar_modulo79(raiz: Path):
    ruta = raiz / "src" / "79_congelar_modelo_y_estimar_prospectivamente.py"
    spec = importlib.util.spec_from_file_location("modelo79_operativo", ruta)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"No se pudo cargar {ruta}")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def escribir_csv(df: pd.DataFrame, ruta: Path) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(ruta, index=False, encoding="utf-8-sig", date_format="%Y-%m-%d")


def limpiar_retorno(serie: pd.Series) -> pd.Series:
    salida = pd.to_numeric(serie, errors="coerce").replace([np.inf, -np.inf], np.nan)
    return salida.clip(lower=-0.95, upper=3.0)


def rsi_desde_retornos(retornos: pd.Series, ventana: int = 14) -> pd.Series:
    r = limpiar_retorno(retornos)
    ganancias = r.clip(lower=0.0)
    perdidas = (-r.clip(upper=0.0))
    prom_gan = ganancias.rolling(ventana, min_periods=ventana).mean()
    prom_per = perdidas.rolling(ventana, min_periods=ventana).mean()
    rs = prom_gan / prom_per.replace(0.0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    rsi = rsi.where(prom_per.ne(0.0), 100.0)
    rsi = rsi.where(prom_gan.ne(0.0), 0.0)
    return rsi


def indicadores_factor(retornos: pd.Series, prefijo: str, lag: int) -> pd.DataFrame:
    r = limpiar_retorno(retornos)
    precio = (1.0 + r.fillna(0.0)).cumprod()
    precio = precio.where(r.notna().cumsum().gt(0))

    ema12 = precio.ewm(span=12, adjust=False, min_periods=12).mean()
    ema26 = precio.ewm(span=26, adjust=False, min_periods=26).mean()

    bruto = pd.DataFrame(index=r.index)
    bruto[f"{prefijo}__ret1"] = r
    bruto[f"{prefijo}__mom3"] = precio.pct_change(3, fill_method=None)
    bruto[f"{prefijo}__mom5"] = precio.pct_change(5, fill_method=None)
    bruto[f"{prefijo}__ma5_20"] = (
        precio.rolling(5, min_periods=5).mean()
        / precio.rolling(20, min_periods=20).mean()
        - 1.0
    )
    bruto[f"{prefijo}__rsi14"] = (rsi_desde_retornos(r, 14) - 50.0) / 50.0
    bruto[f"{prefijo}__vol10"] = r.rolling(10, min_periods=10).std()
    bruto[f"{prefijo}__macd12_26"] = ema12 / ema26 - 1.0

    return bruto.shift(int(lag))


def construir_features(panel_factores: pd.DataFrame, canasta_afp: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    panel = panel_factores.copy().sort_values("fecha_cuota")
    panel["fecha_cuota"] = pd.to_datetime(panel["fecha_cuota"], errors="coerce").dt.normalize()
    panel = panel.dropna(subset=["fecha_cuota"]).drop_duplicates("fecha_cuota", keep="last")
    panel = panel.set_index("fecha_cuota")

    bloques: list[pd.DataFrame] = []
    for _, fila in canasta_afp.sort_values("orden").iterrows():
        factor = str(fila["factor"])
        lag = int(pd.to_numeric(fila["lag"], errors="coerce"))
        if factor not in panel.columns:
            continue
        bloques.append(indicadores_factor(panel[factor], factor, lag))

    if not bloques:
        raise RuntimeError("No se pudieron construir indicadores técnicos.")

    features = pd.concat(bloques, axis=1)
    features = features.loc[:, ~features.columns.duplicated()].reset_index()
    columnas = [c for c in features.columns if c != "fecha_cuota"]
    return features, columnas


def dividir_60_20_20(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    n = len(df)
    if n < MIN_FILAS:
        raise RuntimeError(f"Muestra insuficiente para 60/20/20: {n} filas")
    corte_train = int(math.floor(n * TRAIN_FRAC))
    corte_valid = int(math.floor(n * (TRAIN_FRAC + VALID_FRAC)))
    train = df.iloc[:corte_train].copy()
    valid = df.iloc[corte_train:corte_valid].copy()
    test = df.iloc[corte_valid:].copy()
    if min(len(train), len(valid), len(test)) < 50:
        raise RuntimeError("Alguno de los bloques 60/20/20 quedó demasiado pequeño.")
    return train, valid, test


def direccion_correcta(y: np.ndarray, pred: np.ndarray) -> float:
    y = np.asarray(y, dtype=float)
    pred = np.asarray(pred, dtype=float)
    return float(np.mean(np.signbit(y) == np.signbit(pred)))


def metricas(y: np.ndarray, pred: np.ndarray) -> dict[str, float]:
    y = np.asarray(y, dtype=float)
    pred = np.asarray(pred, dtype=float)
    corr = np.corrcoef(y, pred)[0, 1] if len(y) > 2 and np.std(y) > 0 and np.std(pred) > 0 else np.nan
    return {
        "direccion": direccion_correcta(y, pred),
        "mae": float(mean_absolute_error(y, pred)),
        "rmse": float(mean_squared_error(y, pred) ** 0.5),
        "correlacion": float(corr) if np.isfinite(corr) else np.nan,
    }


def ajustar(X: pd.DataFrame, y: pd.Series, columnas: list[str], alpha: float) -> ModeloTecnico:
    x = X[columnas].replace([np.inf, -np.inf], np.nan)
    imputer = SimpleImputer(strategy="median")
    scaler = StandardScaler()
    x_imp = imputer.fit_transform(x)
    z = scaler.fit_transform(x_imp)
    ridge = Ridge(alpha=float(alpha))
    ridge.fit(z, y.astype(float))
    return ModeloTecnico(imputer, scaler, ridge, columnas, float(alpha))


def seleccionar_alpha(train: pd.DataFrame, valid: pd.DataFrame, columnas: list[str]) -> tuple[float, pd.DataFrame]:
    filas: list[dict[str, Any]] = []
    mejor: tuple[float, float, float] | None = None
    mejor_alpha = ALPHAS[0]
    for alpha in ALPHAS:
        modelo = ajustar(train, train["retorno_cuota"], columnas, alpha)
        pred = modelo.predict(valid)
        m = metricas(valid["retorno_cuota"].to_numpy(), pred)
        filas.append({"alpha": alpha, **m})
        clave = (m["direccion"], -m["rmse"], -alpha)
        if mejor is None or clave > mejor:
            mejor = clave
            mejor_alpha = alpha
    return mejor_alpha, pd.DataFrame(filas)


def rango_fechas(df: pd.DataFrame) -> tuple[str, str]:
    return (
        pd.to_datetime(df["fecha_cuota"].min()).date().isoformat(),
        pd.to_datetime(df["fecha_cuota"].max()).date().isoformat(),
    )


def procesar_afp(
    afp: str,
    base: pd.DataFrame,
    factores: pd.DataFrame,
    canasta_afp: pd.DataFrame,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    features, columnas = construir_features(factores, canasta_afp)
    objetivo = base.loc[
        base["afp"].astype(str).eq(afp),
        ["fecha_cuota", "cuota_sbs", "retorno_cuota"],
    ].copy()
    objetivo["fecha_cuota"] = pd.to_datetime(objetivo["fecha_cuota"], errors="coerce").dt.normalize()
    objetivo["cuota_sbs"] = pd.to_numeric(objetivo["cuota_sbs"], errors="coerce")
    objetivo["retorno_cuota"] = pd.to_numeric(objetivo["retorno_cuota"], errors="coerce")
    objetivo = objetivo.dropna(subset=["fecha_cuota"]).drop_duplicates("fecha_cuota", keep="last")

    dataset = features.merge(objetivo, on="fecha_cuota", how="left").sort_values("fecha_cuota")
    historico = dataset.dropna(subset=["retorno_cuota", "cuota_sbs"]).reset_index(drop=True)
    train, valid, test = dividir_60_20_20(historico)

    alpha, tabla_alphas = seleccionar_alpha(train, valid, columnas)
    tabla_alphas.insert(0, "afp", afp)

    modelo_train = ajustar(train, train["retorno_cuota"], columnas, alpha)
    pred_train = modelo_train.predict(train)
    pred_valid = modelo_train.predict(valid)

    train_valid = pd.concat([train, valid], ignore_index=True)
    modelo_80 = ajustar(train_valid, train_valid["retorno_cuota"], columnas, alpha)
    pred_test = modelo_80.predict(test)

    mt = metricas(train["retorno_cuota"].to_numpy(), pred_train)
    mv = metricas(valid["retorno_cuota"].to_numpy(), pred_valid)
    ms = metricas(test["retorno_cuota"].to_numpy(), pred_test)
    ftr0, ftr1 = rango_fechas(train)
    fva0, fva1 = rango_fechas(valid)
    fte0, fte1 = rango_fechas(test)

    resumen = {
        "afp": afp,
        "n_total": len(historico),
        "n_train_60": len(train),
        "n_valid_20": len(valid),
        "n_test_20": len(test),
        "fecha_train_inicio": ftr0,
        "fecha_train_fin": ftr1,
        "fecha_valid_inicio": fva0,
        "fecha_valid_fin": fva1,
        "fecha_test_inicio": fte0,
        "fecha_test_fin": fte1,
        "alpha_elegido": alpha,
        "n_indicadores": len(columnas),
        "direccion_train": mt["direccion"],
        "direccion_valid": mv["direccion"],
        "direccion_test": ms["direccion"],
        "mae_test": ms["mae"],
        "rmse_test": ms["rmse"],
        "correlacion_test": ms["correlacion"],
    }

    detalle_test = test[["fecha_cuota", "cuota_sbs", "retorno_cuota"]].copy()
    detalle_test.insert(0, "afp", afp)
    detalle_test["prediccion_retorno"] = pred_test
    detalle_test["direccion_correcta"] = np.signbit(detalle_test["retorno_cuota"]) == np.signbit(detalle_test["prediccion_retorno"])

    modelo_operativo = ajustar(historico, historico["retorno_cuota"], columnas, alpha)
    fecha_ancla = objetivo.dropna(subset=["cuota_sbs"])["fecha_cuota"].max()
    cuota_ancla = float(objetivo.loc[objetivo["fecha_cuota"].eq(fecha_ancla), "cuota_sbs"].iloc[-1])
    futuro = dataset[dataset["fecha_cuota"].gt(fecha_ancla)].copy()
    futuro = futuro[futuro[columnas].notna().mean(axis=1).ge(0.70)].copy()
    if futuro.empty:
        pronostico = pd.DataFrame()
    else:
        futuro["retorno_diario_estimado"] = modelo_operativo.predict(futuro)
        futuro["retorno_acumulado_estimado"] = (1.0 + futuro["retorno_diario_estimado"]).cumprod() - 1.0
        futuro["cuota_estimada"] = cuota_ancla * (1.0 + futuro["retorno_acumulado_estimado"])
        futuro["direccion_estimada"] = np.where(futuro["retorno_diario_estimado"].ge(0), "SUBE", "BAJA")
        futuro["afp"] = afp
        futuro["fecha_sbs_base"] = fecha_ancla
        futuro["cuota_sbs_base"] = cuota_ancla
        futuro["alpha_elegido"] = alpha
        pronostico = futuro[
            [
                "afp", "fecha_cuota", "fecha_sbs_base", "cuota_sbs_base",
                "retorno_diario_estimado", "retorno_acumulado_estimado",
                "cuota_estimada", "direccion_estimada", "alpha_elegido",
            ]
        ].copy()

    importancia = pd.DataFrame({
        "afp": afp,
        "indicador": columnas,
        "coeficiente_estandarizado": modelo_operativo.ridge.coef_,
    })
    importancia["abs_coeficiente"] = importancia["coeficiente_estandarizado"].abs()
    importancia = importancia.sort_values("abs_coeficiente", ascending=False)

    return resumen, tabla_alphas, detalle_test, pronostico, importancia


def fmt_pct(x: Any) -> str:
    n = pd.to_numeric(x, errors="coerce")
    return "-" if pd.isna(n) else f"{float(n) * 100:.2f}%"


def generar_html(metricas_df: pd.DataFrame, pronostico_df: pd.DataFrame, ruta: Path) -> None:
    filas = []
    for _, r in metricas_df.sort_values("afp").iterrows():
        filas.append(
            "<tr>"
            f"<td>{r['afp']}</td><td>{int(r['n_train_60'])}</td><td>{int(r['n_valid_20'])}</td>"
            f"<td>{int(r['n_test_20'])}</td><td>{fmt_pct(r['direccion_valid'])}</td>"
            f"<td>{fmt_pct(r['direccion_test'])}</td><td>{float(r['rmse_test']):.6f}</td>"
            f"<td>{float(r['alpha_elegido']):g}</td><td>{int(r['n_indicadores'])}</td>"
            "</tr>"
        )

    pron = []
    if not pronostico_df.empty:
        for _, r in pronostico_df.sort_values(["fecha_cuota", "afp"]).iterrows():
            pron.append(
                "<tr>"
                f"<td>{pd.to_datetime(r['fecha_cuota']).date().isoformat()}</td><td>{r['afp']}</td>"
                f"<td>{float(r['cuota_sbs_base']):.6f}</td><td>{float(r['cuota_estimada']):.6f}</td>"
                f"<td>{float(r['retorno_acumulado_estimado']) * 100:+.3f}%</td><td>{r['direccion_estimada']}</td>"
                "</tr>"
            )
    pron_html = "".join(pron) if pron else '<tr><td colspan="6">No hay fecha posterior con indicadores suficientes.</td></tr>'

    html = f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Modelo técnico 60/20/20 - AFP Fondo 3</title>
<style>
body{{font-family:Arial,sans-serif;background:#f4f7fb;color:#06234b;margin:0}}main{{max-width:1180px;margin:auto;padding:22px 14px 40px}}
section,header{{background:white;border:1px solid #dbe5f2;border-radius:10px;padding:17px;margin-bottom:15px}}h1,h2{{margin-top:0}}
p{{color:#536b8c;line-height:1.45}}.wrap{{overflow-x:auto}}table{{width:100%;border-collapse:collapse;min-width:850px}}th,td{{padding:9px;border-bottom:1px solid #dbe5f2;text-align:right}}th:first-child,td:first-child{{text-align:left}}th{{background:#f4f7fb}}
.note{{background:#fff7df}}
</style></head><body><main>
<header><h1>Modelo técnico experimental — división cronológica 60/20/20</h1><p>Indicadores: retorno, momentum 3 y 5 días, cruce de medias 5/20, RSI 14, volatilidad 10 y MACD 12/26. El 20% final permanece reservado para medir el desempeño fuera de muestra.</p></header>
<section><h2>Resultados por AFP</h2><div class="wrap"><table><thead><tr><th>AFP</th><th>Train 60%</th><th>Valid 20%</th><th>Test 20%</th><th>Dirección valid.</th><th>Dirección test</th><th>RMSE test</th><th>Alpha</th><th>Indicadores</th></tr></thead><tbody>{''.join(filas)}</tbody></table></div></section>
<section><h2>Estimación técnica actual</h2><div class="wrap"><table><thead><tr><th>Fecha</th><th>AFP</th><th>Cuota SBS base</th><th>Cuota estimada</th><th>Retorno acum.</th><th>Dirección</th></tr></thead><tbody>{pron_html}</tbody></table></div></section>
<section class="note"><p>Este modelo es un challenger experimental. No reemplaza los modelos Drive o GitHub hasta demostrar una mejora estable en el 20% de test y en comprobaciones futuras contra SBS.</p></section>
</main></body></html>"""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(html, encoding="utf-8")


def main() -> None:
    raiz = Path(__file__).resolve().parents[1]
    processed = raiz / "data" / "processed"
    public = raiz / "public" / "modelo-tecnico" / "index.html"
    m79 = cargar_modulo79(raiz)

    base = m79.leer_csv(processed / "ca0001_modelo56_base_alineada.csv")
    canasta = m79.leer_csv(processed / "ca0001_modelo78_canasta_final_podada.csv")
    base["fecha_cuota"] = pd.to_datetime(base["fecha_cuota"], errors="coerce").dt.normalize()

    registro = m79.construir_registro_factores(canasta)
    ultima_fecha = pd.Timestamp(base.loc[base["cuota_sbs"].notna(), "fecha_cuota"].max()).normalize()
    operativo, auditoria = m79.descargar_factores_operativos(
        registro,
        ultima_fecha - pd.Timedelta(days=DIAS_BUFFER_DESCARGA),
        pd.Timestamp.today().normalize(),
    )
    historico = m79.cargar_factores_historicos(processed)
    factores_requeridos = canasta["factor"].astype(str).drop_duplicates().tolist()
    factores = m79.combinar_historico_y_operativo(historico, operativo, factores_requeridos)

    resumenes: list[dict[str, Any]] = []
    alphas: list[pd.DataFrame] = []
    tests: list[pd.DataFrame] = []
    pronosticos: list[pd.DataFrame] = []
    importancias: list[pd.DataFrame] = []

    for afp in AFPS:
        resumen, tabla_alpha, detalle_test, pronostico, importancia = procesar_afp(
            afp,
            base,
            factores,
            canasta[canasta["afp"].astype(str).eq(afp)].copy(),
        )
        resumenes.append(resumen)
        alphas.append(tabla_alpha)
        tests.append(detalle_test)
        if not pronostico.empty:
            pronosticos.append(pronostico)
        importancias.append(importancia)

    metricas_df = pd.DataFrame(resumenes)
    alphas_df = pd.concat(alphas, ignore_index=True)
    test_df = pd.concat(tests, ignore_index=True)
    pronostico_df = pd.concat(pronosticos, ignore_index=True) if pronosticos else pd.DataFrame()
    importancia_df = pd.concat(importancias, ignore_index=True)

    escribir_csv(metricas_df, processed / "ca0001_modelo174_metricas_60_20_20.csv")
    escribir_csv(alphas_df, processed / "ca0001_modelo174_validacion_alphas.csv")
    escribir_csv(test_df, processed / "ca0001_modelo174_test_reservado.csv")
    escribir_csv(pronostico_df, processed / "ca0001_modelo174_pronostico_actual.csv")
    escribir_csv(importancia_df, processed / "ca0001_modelo174_importancia_indicadores.csv")
    escribir_csv(auditoria, processed / "ca0001_modelo174_auditoria_descargas.csv")

    manifiesto = {
        "version": "modelo174_tecnico_60_20_20",
        "fecha_hora_utc": datetime.now(timezone.utc).isoformat(),
        "division": {"train": TRAIN_FRAC, "validacion": VALID_FRAC, "test": TEST_FRAC},
        "regla_temporal": "Los bloques se forman en orden cronológico; no se barajan las fechas.",
        "seleccion": "Alpha se elige solo con validación, priorizando dirección y luego menor RMSE.",
        "test": "El 20% final no participa en selección ni ajuste previo a su evaluación.",
        "indicadores": ["ret1", "momentum3", "momentum5", "media5_20", "rsi14", "volatilidad10", "macd12_26"],
    }
    (processed / "ca0001_modelo174_manifiesto.json").write_text(
        json.dumps(manifiesto, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    generar_html(metricas_df, pronostico_df, public)
    print("Modelo técnico 60/20/20 generado:", public)


if __name__ == "__main__":
    main()
