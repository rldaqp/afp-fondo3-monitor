from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


AFPS = ["Habitat", "Integra", "Prima", "Profuturo"]
MIN_COBERTURA_VALIDACION_CONFIANZA = 5.0


def leer_csv(ruta: Path) -> pd.DataFrame:
    if not ruta.exists():
        return pd.DataFrame()
    return pd.read_csv(ruta)


def escribir_csv(df: pd.DataFrame, ruta: Path) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(ruta, index=False, encoding="utf-8-sig")


def pct_dir(valor: float) -> str:
    return "Sube" if valor >= 0 else "Baja"


def metricas(g: pd.DataFrame, pred_col: str) -> dict[str, float]:
    tmp = g.dropna(subset=["retorno_real", "valor_cuota", "cuota_previa"]).copy()
    if tmp.empty:
        return {
            "observaciones": 0.0,
            "rmse": np.nan,
            "mae": np.nan,
            "mape": np.nan,
            "direccion": np.nan,
            "correlacion": np.nan,
        }
    y = pd.to_numeric(tmp["retorno_real"], errors="coerce")
    pred = pd.to_numeric(tmp[pred_col], errors="coerce").replace([np.inf, -np.inf], np.nan).fillna(0.0)
    cuota_real = pd.to_numeric(tmp["valor_cuota"], errors="coerce")
    cuota_pred = pd.to_numeric(tmp["cuota_previa"], errors="coerce") * (1.0 + pred)
    err = cuota_pred - cuota_real
    corr = np.nan
    if y.std(ddof=1) > 0 and pred.std(ddof=1) > 0:
        corr = float(y.corr(pred))
    return {
        "observaciones": float(len(tmp)),
        "rmse": float(np.sqrt(np.mean(err * err))),
        "mae": float(np.mean(np.abs(err))),
        "mape": float(np.mean(np.abs(err / cuota_real)) * 100.0),
        "direccion": float(np.mean(np.sign(y) == np.sign(pred)) * 100.0),
        "correlacion": corr,
    }


def construir_confianza(pred: pd.DataFrame, seleccion: pd.DataFrame) -> pd.DataFrame:
    rows = []
    filtros = {"overlay_top30": 0.70, "overlay_top20": 0.80, "overlay_top10": 0.90}
    for _, sel in seleccion.iterrows():
        afp = str(sel["afp"])
        codigo = str(sel["modelo_codigo"])
        pred_col = "pred_base_calendario" if codigo == "base_calendario" else f"pred_{codigo}"
        g = pred[pred["afp"].eq(afp)].copy().sort_values("fecha")
        train = g[g["bloque"].eq("entrenamiento")].copy()
        abs_train = pd.to_numeric(train[pred_col], errors="coerce").abs().replace([np.inf, -np.inf], np.nan).dropna()
        if abs_train.empty:
            continue
        for filtro, q in filtros.items():
            umbral = float(abs_train.quantile(q))
            g[filtro] = pd.to_numeric(g[pred_col], errors="coerce").abs() >= umbral
            for bloque in ["validacion", "test_final"]:
                gb = g[g["bloque"].eq(bloque)].dropna(subset=["retorno_real", "valor_cuota", "cuota_previa"]).copy()
                sub = gb[gb[filtro]].copy()
                met = metricas(sub, pred_col)
                cobertura = float(len(sub) / len(gb) * 100.0) if len(gb) else 0.0
                rows.append(
                    {
                        "afp": afp,
                        "filtro_codigo": filtro,
                        "filtro": {
                            "overlay_top30": "Prediccion fuerte top 30%",
                            "overlay_top20": "Prediccion fuerte top 20%",
                            "overlay_top10": "Prediccion fuerte top 10%",
                        }[filtro],
                        "umbral_abs_pred": umbral,
                        "bloque": bloque,
                        "cobertura_pct": cobertura,
                        **met,
                    }
                )
    conf = pd.DataFrame(rows)
    seleccion_rows = []
    for afp, g in conf[conf["bloque"].eq("validacion")].groupby("afp", sort=True):
        cand = g[g["cobertura_pct"].ge(MIN_COBERTURA_VALIDACION_CONFIANZA)].copy()
        if cand.empty:
            cand = g.copy()
        cand = cand.sort_values(["direccion", "cobertura_pct", "rmse"], ascending=[False, False, True])
        ganador = cand.iloc[0]
        test = conf[
            conf["afp"].eq(afp)
            & conf["filtro_codigo"].eq(ganador["filtro_codigo"])
            & conf["bloque"].eq("test_final")
        ]
        if test.empty:
            continue
        tr = test.iloc[0]
        seleccion_rows.append(
            {
                "afp": afp,
                "filtro_codigo": ganador["filtro_codigo"],
                "filtro": ganador["filtro"],
                "umbral_abs_pred": ganador["umbral_abs_pred"],
                "direccion_validacion": ganador["direccion"],
                "cobertura_validacion_pct": ganador["cobertura_pct"],
                "direccion_test": tr["direccion"],
                "cobertura_test_pct": tr["cobertura_pct"],
                "rmse_test": tr["rmse"],
                "resultado": "Alta confianza" if tr["direccion"] >= 72 else "No usar como alta confianza",
            }
        )
    return conf, pd.DataFrame(seleccion_rows)


def construir_bitacora(pred: pd.DataFrame, seleccion: pd.DataFrame, confianza_sel: pd.DataFrame) -> pd.DataFrame:
    conf_map = confianza_sel.set_index("afp").to_dict("index") if not confianza_sel.empty else {}
    rows = []
    for _, sel in seleccion.sort_values("afp").iterrows():
        afp = str(sel["afp"])
        codigo = str(sel["modelo_codigo"])
        pred_col = "pred_base_calendario" if codigo == "base_calendario" else f"pred_{codigo}"
        g = pred[pred["afp"].eq(afp)].copy().sort_values("fecha")
        if pred_col not in g.columns:
            continue
        train = g[g["bloque"].eq("entrenamiento")].copy()
        abs_train = pd.to_numeric(train[pred_col], errors="coerce").abs().replace([np.inf, -np.inf], np.nan).dropna()
        umbral_medio = float(abs_train.quantile(0.60)) if not abs_train.empty else np.inf
        conf = conf_map.get(afp, {})
        umbral_verde = float(conf.get("umbral_abs_pred", np.inf))

        ultima_cuota = np.nan
        ultima_cuota_oficial = np.nan
        ultima_fecha_sbs = pd.NaT
        ruedas_pendientes_desde_sbs = 0
        for _, row in g.iterrows():
            fecha = row["fecha"]
            pred_ret = pd.to_numeric(row.get(pred_col), errors="coerce")
            pred_ret = 0.0 if pd.isna(pred_ret) else float(pred_ret)
            valor_real = pd.to_numeric(row.get("valor_cuota"), errors="coerce")
            cuota_previa = pd.to_numeric(row.get("cuota_previa"), errors="coerce")
            if pd.isna(cuota_previa) and pd.notna(ultima_cuota):
                cuota_previa = float(ultima_cuota)
            cuota_estimada = cuota_previa * (1.0 + pred_ret) if pd.notna(cuota_previa) else np.nan
            fecha_base_sbs = ultima_fecha_sbs
            cuota_base_sbs = ultima_cuota_oficial
            ruedas_estimadas = 0
            if pd.notna(cuota_previa):
                ruedas_estimadas = 1 if pd.notna(valor_real) else ruedas_pendientes_desde_sbs + 1
            retorno_acumulado = np.nan
            if pd.notna(cuota_base_sbs) and pd.notna(cuota_estimada) and cuota_base_sbs != 0:
                retorno_acumulado = cuota_estimada / cuota_base_sbs - 1.0

            abs_pred = abs(pred_ret)
            if abs_pred >= umbral_verde:
                confianza = "Verde"
                usar = "Si"
                razon = str(conf.get("filtro", "Prediccion fuerte"))
            elif abs_pred >= umbral_medio:
                confianza = "Amarillo"
                usar = "Cuidado"
                razon = "Senal media"
            else:
                confianza = "Gris"
                usar = "No"
                razon = "Senal debil"

            retorno_real = pd.to_numeric(row.get("retorno_real"), errors="coerce")
            acierto = np.nan
            resultado = "Pendiente SBS"
            if pd.notna(retorno_real):
                acierto = bool(np.sign(retorno_real) == np.sign(pred_ret))
                resultado = "Acierto" if acierto else "Fallo"
            error_cuota = cuota_estimada - valor_real if pd.notna(cuota_estimada) and pd.notna(valor_real) else np.nan
            error_abs_pct = (
                abs(error_cuota / valor_real) * 100.0
                if pd.notna(error_cuota) and pd.notna(valor_real) and valor_real != 0
                else np.nan
            )

            rows.append(
                {
                    "fecha": pd.Timestamp(fecha).date().isoformat() if pd.notna(fecha) else "",
                    "afp": afp,
                    "modelo_codigo": codigo,
                    "retorno_estimado": pred_ret,
                    "retorno_estimado_pct": pred_ret * 100.0,
                    "direccion_estimada": pct_dir(pred_ret),
                    "confianza": confianza,
                    "usar_senal": usar,
                    "razon": razon,
                    "fecha_base_sbs": (
                        pd.Timestamp(fecha_base_sbs).date().isoformat()
                        if pd.notna(fecha_base_sbs)
                        else ""
                    ),
                    "cuota_base_sbs": cuota_base_sbs,
                    "ruedas_estimadas_desde_sbs": ruedas_estimadas,
                    "cuota_base": cuota_previa,
                    "cuota_estimada": cuota_estimada,
                    "retorno_acumulado_estimado_desde_sbs": retorno_acumulado,
                    "retorno_acumulado_estimado_desde_sbs_pct": retorno_acumulado * 100.0
                    if pd.notna(retorno_acumulado)
                    else np.nan,
                    "sbs_publicada": valor_real,
                    "retorno_real": retorno_real,
                    "error_cuota": error_cuota,
                    "error_abs_pct": error_abs_pct,
                    "acierto_direccion": acierto,
                    "resultado": resultado,
                    "bloque": row.get("bloque"),
                }
            )

            if pd.notna(valor_real):
                ultima_cuota = float(valor_real)
                ultima_cuota_oficial = float(valor_real)
                ultima_fecha_sbs = pd.Timestamp(fecha)
                ruedas_pendientes_desde_sbs = 0
            elif pd.notna(cuota_estimada):
                ultima_cuota = float(cuota_estimada)
                ruedas_pendientes_desde_sbs += 1
    out = pd.DataFrame(rows)
    out["fecha"] = pd.to_datetime(out["fecha"], errors="coerce")
    return out.sort_values(["afp", "fecha"])


def main() -> None:
    raiz = Path(__file__).resolve().parents[1]
    processed = raiz / "data" / "processed"
    pred = leer_csv(processed / "overlay_direccion_predicciones.csv")
    seleccion = leer_csv(processed / "overlay_direccion_seleccion.csv")
    if pred.empty or seleccion.empty:
        raise FileNotFoundError("Falta correr src/169_overlay_direccion_integra_profuturo.py")
    pred["fecha"] = pd.to_datetime(pred["fecha"], errors="coerce")

    conf_metricas, conf_sel = construir_confianza(pred, seleccion)
    bitacora = construir_bitacora(pred, seleccion, conf_sel)
    ultima = bitacora.sort_values(["afp", "fecha"]).groupby("afp", as_index=False).tail(1)
    ultimos_dias = bitacora[bitacora["fecha"].ge(bitacora["fecha"].max() - pd.Timedelta(days=30))].copy()
    grafico = bitacora[bitacora["fecha"].ge(bitacora["fecha"].max() - pd.Timedelta(days=24))][
        [
            "fecha",
            "afp",
            "sbs_publicada",
            "cuota_estimada",
            "cuota_base",
            "fecha_base_sbs",
            "cuota_base_sbs",
            "ruedas_estimadas_desde_sbs",
            "retorno_estimado_pct",
            "retorno_acumulado_estimado_desde_sbs_pct",
            "direccion_estimada",
            "error_cuota",
            "error_abs_pct",
            "resultado",
        ]
    ].rename(columns={"cuota_estimada": "modelo_overlay_estimado"})

    metricas_overlay = leer_csv(processed / "overlay_direccion_seleccion.csv")
    resumen = metricas_overlay[
        [
            "afp",
            "direccion_validacion",
            "direccion_test",
            "direccion_base_test",
            "delta_dir_test_vs_base",
            "rmse_test",
            "cumple_72_test",
        ]
    ].merge(
        conf_sel[
            [
                "afp",
                "filtro",
                "direccion_test",
                "cobertura_test_pct",
            ]
        ].rename(
            columns={
                "direccion_test": "direccion_alta_confianza_test",
                "cobertura_test_pct": "cobertura_alta_confianza_pct",
            }
        ),
        on="afp",
        how="left",
    )

    escribir_csv(conf_metricas, processed / "tablero_operativo_confianza_metricas.csv")
    escribir_csv(conf_sel, processed / "tablero_operativo_confianza_seleccion.csv")
    escribir_csv(bitacora, processed / "tablero_operativo_bitacora_diaria.csv")
    escribir_csv(ultima, processed / "tablero_operativo_ultima_senal.csv")
    escribir_csv(ultimos_dias, processed / "tablero_operativo_ultimos_dias.csv")
    escribir_csv(grafico, processed / "tablero_operativo_grafico.csv")
    escribir_csv(resumen, processed / "tablero_operativo_resumen_metricas.csv")
    (processed / "tablero_operativo_resumen.json").write_text(
        json.dumps(
            {
                "objetivo": "Visor diario simple para probar el modelo contra la publicacion SBS dia a dia.",
                "uso": "Mirar despues del cierre de mercados y antes de la publicacion SBS. No es forecast T+1 puro.",
                "verde": "Senal fuerte; se usa como semaforo operativo.",
                "amarillo": "Senal media; mirar con cuidado.",
                "gris": "Senal debil; no usar como decision.",
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print("Tablero operativo preparado")
    print(ultima[["fecha", "afp", "direccion_estimada", "confianza", "usar_senal", "cuota_estimada", "resultado"]].to_string(index=False))


if __name__ == "__main__":
    main()
