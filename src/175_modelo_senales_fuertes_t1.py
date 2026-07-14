from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd


AFPS = ["Habitat", "Integra", "Prima", "Profuturo"]
TRAIN_FRAC = 0.60
VALID_FRAC = 0.20
TEST_FRAC = 0.20
MIN_TOTAL = 300
MIN_SENALES_VALIDACION = 12
MIN_SENALES_TEST = 12


def leer_csv(ruta: Path) -> pd.DataFrame:
    if not ruta.exists():
        raise FileNotFoundError(f"No existe el archivo requerido: {ruta}")
    ultimo_error: Exception | None = None
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return pd.read_csv(ruta, encoding=encoding)
        except Exception as exc:
            ultimo_error = exc
    raise RuntimeError(f"No se pudo leer {ruta}: {ultimo_error}")


def escribir_csv(df: pd.DataFrame, ruta: Path) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(ruta, index=False, encoding="utf-8-sig", date_format="%Y-%m-%d")


def signo(serie: pd.Series) -> pd.Series:
    x = pd.to_numeric(serie, errors="coerce")
    return pd.Series(np.where(x > 0, 1, np.where(x < 0, -1, 0)), index=serie.index)


def dividir_60_20_20(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    n = len(df)
    if n < MIN_TOTAL:
        raise RuntimeError(f"Muestra insuficiente para 60/20/20: {n} observaciones")
    corte_train = int(math.floor(n * TRAIN_FRAC))
    corte_valid = int(math.floor(n * (TRAIN_FRAC + VALID_FRAC)))
    train = df.iloc[:corte_train].copy()
    valid = df.iloc[corte_train:corte_valid].copy()
    test = df.iloc[corte_valid:].copy()
    if min(len(train), len(valid), len(test)) < 40:
        raise RuntimeError("Alguno de los bloques 60/20/20 quedó demasiado pequeño")
    return train, valid, test


def preparar_t1(bitacora: pd.DataFrame, afp: str) -> pd.DataFrame:
    requeridas = {"fecha", "afp", "retorno_estimado", "retorno_real"}
    faltantes = requeridas.difference(bitacora.columns)
    if faltantes:
        raise KeyError(f"Faltan columnas en la bitácora: {sorted(faltantes)}")

    g = bitacora[bitacora["afp"].astype(str).eq(afp)].copy()
    g["fecha"] = pd.to_datetime(g["fecha"], errors="coerce").dt.normalize()
    g["retorno_estimado"] = pd.to_numeric(g["retorno_estimado"], errors="coerce")
    g["retorno_real"] = pd.to_numeric(g["retorno_real"], errors="coerce")
    g = g.dropna(subset=["fecha"]).drop_duplicates("fecha", keep="last").sort_values("fecha")

    # La señal disponible al cierre de t se compara con el retorno SBS de la
    # siguiente fecha disponible. No se usa el retorno real de t para predecir t+1.
    g["fecha_objetivo_t1"] = g["fecha"].shift(-1)
    g["retorno_real_t1"] = g["retorno_real"].shift(-1)
    g["magnitud_senal"] = g["retorno_estimado"].abs()
    g["signo_senal"] = signo(g["retorno_estimado"])
    g["signo_senal_previa"] = g["signo_senal"].shift(1)
    g["magnitud_previa"] = g["magnitud_senal"].shift(1)
    g["persistente"] = g["signo_senal"].eq(g["signo_senal_previa"])
    g["acelerando"] = g["persistente"] & g["magnitud_senal"].ge(g["magnitud_previa"])
    g["signo_real_t1"] = signo(g["retorno_real_t1"])
    g["acierto_t1"] = g["signo_senal"].eq(g["signo_real_t1"])

    # Se excluyen señales o retornos exactamente cero para que un empate no
    # cuente artificialmente como acierto de dirección.
    g = g.dropna(subset=["retorno_estimado", "retorno_real_t1", "fecha_objetivo_t1"])
    g = g[g["signo_senal"].ne(0) & g["signo_real_t1"].ne(0)].reset_index(drop=True)
    return g


def metricas_regla(df: pd.DataFrame, mascara: pd.Series) -> dict[str, float]:
    sub = df.loc[mascara.fillna(False)].copy()
    n = len(sub)
    cobertura = float(n / len(df) * 100.0) if len(df) else 0.0
    if n == 0:
        return {
            "n_senales": 0,
            "cobertura_pct": cobertura,
            "direccion_pct": np.nan,
            "retorno_medio_t1_pct": np.nan,
            "retorno_mediano_t1_pct": np.nan,
        }
    retorno_alineado = sub["retorno_real_t1"] * sub["signo_senal"]
    return {
        "n_senales": int(n),
        "cobertura_pct": cobertura,
        "direccion_pct": float(sub["acierto_t1"].mean() * 100.0),
        "retorno_medio_t1_pct": float(retorno_alineado.mean() * 100.0),
        "retorno_mediano_t1_pct": float(retorno_alineado.median() * 100.0),
    }


def construir_reglas(train: pd.DataFrame) -> tuple[dict[str, Callable[[pd.DataFrame], pd.Series]], dict[str, float]]:
    magnitud = train["magnitud_senal"].dropna()
    if magnitud.empty:
        raise RuntimeError("No hay magnitudes de señal en entrenamiento")
    umbrales = {
        "top30": float(magnitud.quantile(0.70)),
        "top20": float(magnitud.quantile(0.80)),
        "top10": float(magnitud.quantile(0.90)),
    }

    reglas: dict[str, Callable[[pd.DataFrame], pd.Series]] = {
        "top30": lambda x: x["magnitud_senal"].ge(umbrales["top30"]),
        "top20": lambda x: x["magnitud_senal"].ge(umbrales["top20"]),
        "top10": lambda x: x["magnitud_senal"].ge(umbrales["top10"]),
        "top30_persistente": lambda x: x["magnitud_senal"].ge(umbrales["top30"]) & x["persistente"],
        "top20_persistente": lambda x: x["magnitud_senal"].ge(umbrales["top20"]) & x["persistente"],
        "top10_persistente": lambda x: x["magnitud_senal"].ge(umbrales["top10"]) & x["persistente"],
        "top20_acelerando": lambda x: x["magnitud_senal"].ge(umbrales["top20"]) & x["acelerando"],
        "top10_acelerando": lambda x: x["magnitud_senal"].ge(umbrales["top10"]) & x["acelerando"],
    }
    return reglas, umbrales


def descripcion_regla(codigo: str) -> str:
    nombres = {
        "top30": "Magnitud dentro del 30% más fuerte",
        "top20": "Magnitud dentro del 20% más fuerte",
        "top10": "Magnitud dentro del 10% más fuerte",
        "top30_persistente": "Top 30% y misma dirección que la señal anterior",
        "top20_persistente": "Top 20% y misma dirección que la señal anterior",
        "top10_persistente": "Top 10% y misma dirección que la señal anterior",
        "top20_acelerando": "Top 20%, persistente y con magnitud creciente",
        "top10_acelerando": "Top 10%, persistente y con magnitud creciente",
    }
    return nombres.get(codigo, codigo)


def procesar_afp(bitacora: pd.DataFrame, afp: str) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    datos = preparar_t1(bitacora, afp)
    train, valid, test = dividir_60_20_20(datos)
    reglas, umbrales = construir_reglas(train)

    candidatos: list[dict[str, Any]] = []
    for codigo, regla in reglas.items():
        mv = metricas_regla(valid, regla(valid))
        mt = metricas_regla(test, regla(test))
        candidatos.append(
            {
                "afp": afp,
                "regla_codigo": codigo,
                "regla": descripcion_regla(codigo),
                "umbral_top30": umbrales["top30"],
                "umbral_top20": umbrales["top20"],
                "umbral_top10": umbrales["top10"],
                **{f"valid_{k}": v for k, v in mv.items()},
                **{f"test_{k}": v for k, v in mt.items()},
            }
        )

    tabla = pd.DataFrame(candidatos)
    elegibles = tabla[tabla["valid_n_senales"].ge(MIN_SENALES_VALIDACION)].copy()
    if elegibles.empty:
        elegibles = tabla.copy()
    elegibles = elegibles.sort_values(
        ["valid_direccion_pct", "valid_n_senales", "valid_retorno_mediano_t1_pct"],
        ascending=[False, False, False],
        na_position="last",
    )
    ganador = elegibles.iloc[0]
    codigo = str(ganador["regla_codigo"])
    regla = reglas[codigo]

    base_valid = metricas_regla(valid, pd.Series(True, index=valid.index))
    base_test = metricas_regla(test, pd.Series(True, index=test.index))
    met_test = metricas_regla(test, regla(test))

    # La magnitud esperada se calibra con train + validación, sin usar el test.
    calibracion = pd.concat([train, valid], ignore_index=True)
    cal_sub = calibracion.loc[regla(calibracion)].copy()
    if cal_sub.empty:
        prob_acierto = np.nan
        retorno_esperado = np.nan
    else:
        prob_acierto = float(cal_sub["acierto_t1"].mean())
        retorno_esperado = float((cal_sub["retorno_real_t1"] * cal_sub["signo_senal"]).median())

    estado = "APROBADO_TEST" if (
        met_test["n_senales"] >= MIN_SENALES_TEST
        and pd.notna(met_test["direccion_pct"])
        and met_test["direccion_pct"] >= 60.0
        and met_test["direccion_pct"] >= base_test["direccion_pct"] + 2.0
    ) else "EXPERIMENTAL_NO_APROBADO"

    resumen = {
        "afp": afp,
        "n_total": len(datos),
        "n_train_60": len(train),
        "n_valid_20": len(valid),
        "n_test_20": len(test),
        "fecha_train_inicio": train["fecha"].min(),
        "fecha_train_fin": train["fecha"].max(),
        "fecha_valid_inicio": valid["fecha"].min(),
        "fecha_valid_fin": valid["fecha"].max(),
        "fecha_test_inicio": test["fecha"].min(),
        "fecha_test_fin": test["fecha"].max(),
        "regla_elegida": codigo,
        "regla_descripcion": descripcion_regla(codigo),
        "umbral_abs_retorno_estimado": float(
            umbrales["top30"] if "top30" in codigo else umbrales["top10"] if "top10" in codigo else umbrales["top20"]
        ),
        "direccion_base_valid_pct": base_valid["direccion_pct"],
        "direccion_regla_valid_pct": ganador["valid_direccion_pct"],
        "cobertura_regla_valid_pct": ganador["valid_cobertura_pct"],
        "n_regla_valid": int(ganador["valid_n_senales"]),
        "direccion_base_test_pct": base_test["direccion_pct"],
        "direccion_regla_test_pct": met_test["direccion_pct"],
        "mejora_test_pp": met_test["direccion_pct"] - base_test["direccion_pct"] if pd.notna(met_test["direccion_pct"]) else np.nan,
        "cobertura_regla_test_pct": met_test["cobertura_pct"],
        "n_regla_test": met_test["n_senales"],
        "probabilidad_historica_calibracion": prob_acierto,
        "retorno_alineado_mediano_calibracion": retorno_esperado,
        "estado": estado,
    }

    detalle_test = test.copy()
    detalle_test["regla_elegida"] = codigo
    detalle_test["senal_fuerte"] = regla(test).to_numpy()

    # Señal operacional: última predicción disponible, incluso si SBS todavía no
    # ha publicado la cuota del siguiente día.
    vivo = bitacora[bitacora["afp"].astype(str).eq(afp)].copy()
    vivo["fecha"] = pd.to_datetime(vivo["fecha"], errors="coerce").dt.normalize()
    vivo["retorno_estimado"] = pd.to_numeric(vivo["retorno_estimado"], errors="coerce")
    vivo = vivo.dropna(subset=["fecha", "retorno_estimado"]).drop_duplicates("fecha", keep="last").sort_values("fecha")
    ultima = vivo.iloc[-1]
    previa = vivo.iloc[-2] if len(vivo) >= 2 else None
    fila_actual = pd.DataFrame(
        {
            "magnitud_senal": [abs(float(ultima["retorno_estimado"]))],
            "signo_senal": [1 if float(ultima["retorno_estimado"]) > 0 else -1],
            "signo_senal_previa": [
                (1 if float(previa["retorno_estimado"]) > 0 else -1) if previa is not None else np.nan
            ],
            "magnitud_previa": [abs(float(previa["retorno_estimado"])) if previa is not None else np.nan],
        }
    )
    fila_actual["persistente"] = fila_actual["signo_senal"].eq(fila_actual["signo_senal_previa"])
    fila_actual["acelerando"] = fila_actual["persistente"] & fila_actual["magnitud_senal"].ge(fila_actual["magnitud_previa"])
    fuerte = bool(regla(fila_actual).iloc[0])
    direccion = "SUBE" if float(ultima["retorno_estimado"]) > 0 else "BAJA"
    fecha_senal = pd.Timestamp(ultima["fecha"])
    fecha_objetivo = fecha_senal + pd.offsets.BDay(1)
    senal_viva = {
        "afp": afp,
        "fecha_senal": fecha_senal,
        "fecha_objetivo_t1_referencial": fecha_objetivo,
        "retorno_estimado_origen": float(ultima["retorno_estimado"]),
        "direccion_t1": direccion if fuerte else "SIN_SEÑAL_FUERTE",
        "senal_fuerte": fuerte,
        "regla_elegida": codigo,
        "regla_descripcion": descripcion_regla(codigo),
        "probabilidad_historica_calibracion": prob_acierto,
        "retorno_t1_estimado_alineado": retorno_esperado,
        "retorno_t1_estimado": retorno_esperado * (1 if direccion == "SUBE" else -1) if pd.notna(retorno_esperado) and fuerte else np.nan,
        "estado_modelo": estado,
    }
    return resumen, tabla, detalle_test, senal_viva


def fmt_pct(valor: Any, escala_100: bool = False) -> str:
    n = pd.to_numeric(valor, errors="coerce")
    if pd.isna(n):
        return "-"
    x = float(n) * (100.0 if escala_100 else 1.0)
    return f"{x:.2f}%"


def generar_html(resumen: pd.DataFrame, vivo: pd.DataFrame, ruta: Path) -> None:
    filas_resumen: list[str] = []
    for _, r in resumen.sort_values("afp").iterrows():
        filas_resumen.append(
            "<tr>"
            f"<td>{r['afp']}</td>"
            f"<td>{r['regla_descripcion']}</td>"
            f"<td>{fmt_pct(r['direccion_regla_valid_pct'])}</td>"
            f"<td>{fmt_pct(r['direccion_regla_test_pct'])}</td>"
            f"<td>{fmt_pct(r['direccion_base_test_pct'])}</td>"
            f"<td>{float(r['mejora_test_pp']):+.2f} pp</td>"
            f"<td>{int(r['n_regla_test'])}</td>"
            f"<td>{fmt_pct(r['cobertura_regla_test_pct'])}</td>"
            f"<td>{r['estado']}</td>"
            "</tr>"
        )

    filas_vivo: list[str] = []
    for _, r in vivo.sort_values("afp").iterrows():
        clase = "ok" if bool(r["senal_fuerte"]) and r["estado_modelo"] == "APROBADO_TEST" else "wait"
        retorno = fmt_pct(r["retorno_t1_estimado"], escala_100=True)
        prob = fmt_pct(r["probabilidad_historica_calibracion"], escala_100=True)
        filas_vivo.append(
            "<tr>"
            f"<td>{r['afp']}</td>"
            f"<td>{pd.to_datetime(r['fecha_senal']).date().isoformat()}</td>"
            f"<td>{pd.to_datetime(r['fecha_objetivo_t1_referencial']).date().isoformat()}</td>"
            f"<td>{r['direccion_t1']}</td>"
            f"<td><span class='{clase}'>{'FUERTE' if bool(r['senal_fuerte']) else 'NO FUERTE'}</span></td>"
            f"<td>{prob}</td>"
            f"<td>{retorno}</td>"
            f"<td>{r['regla_descripcion']}</td>"
            "</tr>"
        )

    html = f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Señales fuertes T+1 - AFP Fondo 3</title>
<style>
:root{{--bg:#f4f7fb;--panel:#fff;--ink:#06234b;--muted:#536b8c;--line:#dbe5f2;--green:#107c41;--yellow:#8a5a00;font-family:Arial,sans-serif}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink)}}main{{max-width:1220px;margin:auto;padding:24px 14px 40px}}
header,section{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:18px;margin-bottom:16px}}h1,h2{{margin-top:0}}p{{color:var(--muted);line-height:1.5}}
.wrap{{overflow-x:auto}}table{{width:100%;border-collapse:collapse;min-width:1050px}}th,td{{padding:10px 8px;border-bottom:1px solid var(--line);text-align:right}}th{{background:#f4f7fb}}th:first-child,td:first-child{{text-align:left;font-weight:700}}
.ok,.wait{{display:inline-block;padding:4px 8px;border-radius:999px;font-weight:700}}.ok{{color:var(--green);background:#e8f5ee}}.wait{{color:var(--yellow);background:#fff7df}}
.note{{background:#fff7df}}
</style>
</head><body><main>
<header><h1>Modelo de señales fuertes para el siguiente día de mercado (T+1)</h1>
<p>La señal se calcula con la predicción disponible al cierre del día t y se enfrenta a la dirección de la siguiente cuota SBS disponible. La separación es cronológica: 60% entrenamiento, 20% validación para elegir la regla y 20% test reservado.</p></header>
<section><h2>Qué significa señal fuerte</h2>
<p>El modelo prueba señales ubicadas en el 30%, 20% o 10% de mayor magnitud histórica. También prueba si la señal mantiene la misma dirección que la anterior y si su magnitud está aumentando. Los umbrales se calculan exclusivamente en el 60% de entrenamiento; la regla se elige en validación y recién después se mide en el test final.</p></section>
<section><h2>Resultado fuera de muestra</h2><div class="wrap"><table><thead><tr><th>AFP</th><th>Regla elegida</th><th>Dirección valid.</th><th>Dirección test</th><th>Base test</th><th>Mejora</th><th>Señales test</th><th>Cobertura</th><th>Estado</th></tr></thead><tbody>{''.join(filas_resumen)}</tbody></table></div></section>
<section><h2>Señal disponible para T+1</h2><div class="wrap"><table><thead><tr><th>AFP</th><th>Fecha señal</th><th>Objetivo referencial</th><th>Dirección</th><th>Fuerza</th><th>Prob. histórica</th><th>Retorno estimado</th><th>Regla</th></tr></thead><tbody>{''.join(filas_vivo)}</tbody></table></div></section>
<section class="note"><p><strong>Momento de recepción:</strong> puede publicarse la noche anterior a la fecha objetivo, después de que hayan cerrado y se hayan descargado todos los mercados usados por el modelo. “APROBADO_TEST” exige al menos 60% de dirección en señales fuertes, una mejora mínima de 2 puntos porcentuales frente a usar todas las señales y al menos {MIN_SENALES_TEST} observaciones en test. No equivale a una recomendación de compra.</p></section>
</main></body></html>"""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(html, encoding="utf-8")


def main() -> None:
    raiz = Path(__file__).resolve().parents[1]
    processed = raiz / "data" / "processed"
    public = raiz / "public" / "modelo-senales-t1" / "index.html"
    bitacora = leer_csv(processed / "tablero_operativo_bitacora_diaria.csv")

    resumenes: list[dict[str, Any]] = []
    candidatos: list[pd.DataFrame] = []
    tests: list[pd.DataFrame] = []
    vivas: list[dict[str, Any]] = []
    errores: list[dict[str, str]] = []

    for afp in AFPS:
        try:
            resumen, tabla, detalle, viva = procesar_afp(bitacora, afp)
            resumenes.append(resumen)
            candidatos.append(tabla)
            tests.append(detalle)
            vivas.append(viva)
        except Exception as exc:
            errores.append({"afp": afp, "error": str(exc)})

    if not resumenes:
        raise RuntimeError("No se pudo estimar ninguna AFP: " + json.dumps(errores, ensure_ascii=False))

    resumen_df = pd.DataFrame(resumenes)
    candidatos_df = pd.concat(candidatos, ignore_index=True) if candidatos else pd.DataFrame()
    test_df = pd.concat(tests, ignore_index=True) if tests else pd.DataFrame()
    vivo_df = pd.DataFrame(vivas)
    errores_df = pd.DataFrame(errores)

    escribir_csv(resumen_df, processed / "ca0001_modelo175_resumen_senales_t1.csv")
    escribir_csv(candidatos_df, processed / "ca0001_modelo175_reglas_candidatas.csv")
    escribir_csv(test_df, processed / "ca0001_modelo175_test_reservado.csv")
    escribir_csv(vivo_df, processed / "ca0001_modelo175_senal_actual_t1.csv")
    if not errores_df.empty:
        escribir_csv(errores_df, processed / "ca0001_modelo175_errores.csv")

    manifiesto = {
        "version": "modelo175_senales_fuertes_t1",
        "objetivo": "Usar la señal del cierre de t para anticipar la dirección de la siguiente cuota SBS disponible.",
        "division": {"entrenamiento": TRAIN_FRAC, "validacion": VALID_FRAC, "test": TEST_FRAC},
        "reglas": [descripcion_regla(x) for x in [
            "top30", "top20", "top10", "top30_persistente", "top20_persistente",
            "top10_persistente", "top20_acelerando", "top10_acelerando",
        ]],
        "criterio_aprobacion": {
            "direccion_test_min_pct": 60.0,
            "mejora_sobre_base_min_pp": 2.0,
            "n_senales_test_min": MIN_SENALES_TEST,
        },
        "advertencia": "Una señal fuerte es una condición estadística histórica, no una recomendación financiera.",
    }
    (processed / "ca0001_modelo175_manifiesto.json").write_text(
        json.dumps(manifiesto, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    generar_html(resumen_df, vivo_df, public)
    print("Modelo de señales fuertes T+1 generado:", public)
    print(resumen_df[["afp", "regla_elegida", "direccion_regla_test_pct", "n_regla_test", "estado"]].to_string(index=False))


if __name__ == "__main__":
    main()
