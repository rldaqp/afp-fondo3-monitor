from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


def cargar_modulo(nombre: str, ruta: Path):
    spec = importlib.util.spec_from_file_location(nombre, ruta)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"No se pudo cargar {ruta}")
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = modulo
    spec.loader.exec_module(modulo)
    return modulo


def modelo_por_codigo(v4, cfg: dict[str, Any], codigo: str):
    for cod, modelo in v4.construir_modelos(cfg):
        if cod == codigo:
            return modelo
    raise RuntimeError(f"Modelo no encontrado: {codigo}")


def preparar_eventos(afp: str, base: pd.DataFrame, cfg: dict[str, Any], v2, v4) -> pd.DataFrame:
    g = base[base["afp"].astype(str).eq(afp)].copy()
    g["fecha_cuota"] = pd.to_datetime(g["fecha_cuota"], errors="coerce").dt.normalize()
    g["fecha_objetivo_t1"] = pd.to_datetime(
        g["fecha_objetivo_t1"], errors="coerce"
    ).dt.normalize()
    g, _ = v2.construir_episodios(g, cfg["configuracion_episodios"])
    g = v4.agregar_rebote_relativo(g)
    eventos = g[
        g["en_episodio_rebote"]
        & g["caida_relevante_t1"].notna()
    ].copy()
    return eventos.sort_values("fecha_cuota").reset_index(drop=True)


def evaluar_segmento(v4, nombre: str, df: pd.DataFrame) -> dict[str, Any]:
    if df.empty:
        return {"segmento": nombre, "n": 0}
    return {
        "segmento": nombre,
        **v4.metricas(
            df,
            df["probabilidad_riesgo"].to_numpy(dtype=float),
            df["alerta_salida"].astype(bool).to_numpy(),
        ),
    }


def walk_forward_afp(
    afp: str,
    eventos: pd.DataFrame,
    seleccion: pd.Series,
    cfg: dict[str, Any],
    v4,
) -> tuple[pd.DataFrame, dict[str, Any], pd.DataFrame]:
    test = eventos[eventos["bloque_60_20_20"].eq("test_reservado")].copy()
    test = test.sort_values("fecha_cuota")
    codigo = str(seleccion["modelo_elegido"])
    cobertura = float(seleccion["cobertura_objetivo_validacion"])
    modo = str(seleccion["modo_selectivo"])
    zonas = json.loads(str(seleccion["zonas_seleccionadas"]))

    cada = int(cfg["walk_forward"]["reentrenar_cada_observaciones"])
    minimo = int(cfg["walk_forward"]["minimo_eventos_historial"])
    ventana_umbral = 250
    modelo = None
    umbral = np.nan
    desde = cada
    filas: list[dict[str, Any]] = []
    fechas_obj = pd.to_datetime(eventos["fecha_objetivo_t1"], errors="coerce").dt.normalize()

    for _, fila in test.iterrows():
        fecha = pd.Timestamp(fila["fecha_cuota"]).normalize()
        hist = eventos[fechas_obj < fecha].dropna(subset=["caida_relevante_t1"]).copy()
        if len(hist) < minimo or hist["caida_relevante_t1"].nunique() < 2:
            continue

        if modelo is None or desde >= cada:
            modelo = modelo_por_codigo(v4, cfg, codigo)
            modelo.fit(v4.limpiar_numericos(hist, v4.FEATURES)[v4.FEATURES], hist["caida_relevante_t1"].astype(int))
            calibracion = hist.tail(min(ventana_umbral, len(hist))).copy()
            calibracion = v4.limpiar_numericos(calibracion, v4.FEATURES)
            prob_hist = modelo.predict_proba(calibracion[v4.FEATURES])[:, 1]
            umbral = float(np.quantile(prob_hist, 1.0 - cobertura))
            desde = 0

        fila_df = pd.DataFrame([fila])
        fila_df = v4.limpiar_numericos(fila_df, v4.FEATURES)
        prob = float(modelo.predict_proba(fila_df[v4.FEATURES])[:, 1][0])
        alerta = prob >= umbral
        if modo == "probabilidad_y_zona":
            alerta = bool(alerta and v4.mascara_zonas(fila_df, zonas)[0])

        filas.append({
            "afp": afp,
            "fecha_cuota": fila["fecha_cuota"],
            "fecha_objetivo_t1": fila["fecha_objetivo_t1"],
            "retorno_real_t1": fila["retorno_real_t1"],
            "umbral_caida_relevante": fila["umbral_caida_relevante"],
            "caida_relevante_t1": fila["caida_relevante_t1"],
            "probabilidad_riesgo": prob,
            "umbral_dinamico": umbral,
            "cobertura_objetivo": cobertura,
            "alerta_salida": bool(alerta),
            "estado_diario": "RIESGO_ALTO" if alerta else "SIN_SENAL",
            "n_historial_disponible": len(hist),
            "modelo_codigo": codigo,
            "modo_selectivo": modo,
            "rebote_desde_minimo_factor": fila.get("rebote_desde_minimo_factor"),
            "fraccion_recuperada_factor": fila.get("fraccion_recuperada_factor"),
            "velocidad_rebote_factor": fila.get("velocidad_rebote_factor"),
            "cambio_velocidad_rebote_factor": fila.get("cambio_velocidad_rebote_factor"),
            "retroceso_desde_maximo_factor": fila.get("retroceso_desde_maximo_factor"),
        })
        desde += 1

    pred = pd.DataFrame(filas)
    if pred.empty:
        raise RuntimeError(f"Walk-forward vacio para {afp}")

    met = v4.metricas(
        pred,
        pred["probabilidad_riesgo"].to_numpy(dtype=float),
        pred["alerta_salida"].astype(bool).to_numpy(),
    )
    corte = len(pred) // 2
    estabilidad = pd.DataFrame([
        evaluar_segmento(v4, "primera_mitad", pred.iloc[:corte].copy()),
        evaluar_segmento(v4, "segunda_mitad", pred.iloc[corte:].copy()),
    ])

    criterios = cfg["criterios_aprobacion"]
    principal = {
        "alertas_minimas": met["n_alertas"] >= int(criterios["min_alertas_test"]),
        "auc_minimo": met["auc"] >= float(criterios["min_auc_test"]),
        "mejora_precision_minima": met["mejora_precision_pp"] >= float(
            criterios["min_mejora_precision_pp"]
        ),
        "cobertura_caidas_minima": met["cobertura_caidas_pct"] >= float(
            criterios["min_cobertura_caidas_pct"]
        ),
        "proteccion_neta_positiva": met["proteccion_neta_suma_pct"] > 0.0,
    }
    estabilidad_ok = {
        "proteccion_positiva_primera": float(
            estabilidad.iloc[0].get("proteccion_neta_suma_pct", np.nan)
        ) > 0.0,
        "proteccion_positiva_segunda": float(
            estabilidad.iloc[1].get("proteccion_neta_suma_pct", np.nan)
        ) > 0.0,
        "mejora_precision_no_negativa_segunda": float(
            estabilidad.iloc[1].get("mejora_precision_pp", np.nan)
        ) >= 0.0,
        "auc_segunda_min_0_52": float(estabilidad.iloc[1].get("auc", np.nan)) >= 0.52,
    }
    if all(principal.values()) and all(estabilidad_ok.values()):
        estado = "APROBADO_PARA_SEGUIMIENTO_PROSPECTIVO"
    elif all(principal.values()):
        estado = "PROMETEDOR_PERO_INESTABLE"
    else:
        estado = "EXPERIMENTAL_NO_APROBADO"

    resumen = {
        "afp": afp,
        "frecuencia": "diaria",
        "modelo_codigo": codigo,
        "modo_selectivo": modo,
        "cobertura_objetivo": cobertura,
        **{f"walk_{k}": v for k, v in met.items()},
        "criterios_principales": json.dumps(principal, ensure_ascii=False, sort_keys=True),
        "criterios_estabilidad": json.dumps(estabilidad_ok, ensure_ascii=False, sort_keys=True),
        "estado": estado,
    }
    estabilidad.insert(0, "afp", afp)
    return pred, resumen, estabilidad


def main() -> None:
    raiz = Path(__file__).resolve().parents[2]
    salida = raiz / "data" / "processed" / "modelo_salida"
    v2 = cargar_modulo(
        "modelo_salida_v2_para_walk_v4",
        raiz / "src" / "modelo_salida" / "04_modelo_rebote_salida_v2.py",
    )
    v4 = cargar_modulo(
        "modelo_salida_v4_para_walk",
        raiz / "src" / "modelo_salida" / "06_modelo_selectivo_diario_v4.py",
    )
    cfg = json.loads(
        (raiz / "config" / "modelo_salida_v4_selectivo_diario.json").read_text(
            encoding="utf-8"
        )
    )
    base = v2.leer_csv(salida / "base_modelo_salida.csv")
    seleccion = v2.leer_csv(salida / "v4_resumen.csv")

    predicciones: list[pd.DataFrame] = []
    resumenes: list[dict[str, Any]] = []
    estabilidad: list[pd.DataFrame] = []
    for afp in cfg["afps"]:
        eventos = preparar_eventos(afp, base, cfg, v2, v4)
        fila_sel = seleccion[seleccion["afp"].astype(str).eq(afp)].iloc[0]
        pred, resumen, est = walk_forward_afp(afp, eventos, fila_sel, cfg, v4)
        predicciones.append(pred)
        resumenes.append(resumen)
        estabilidad.append(est)

    pred_df = pd.concat(predicciones, ignore_index=True)
    resumen_df = pd.DataFrame(resumenes)
    estabilidad_df = pd.concat(estabilidad, ignore_index=True)

    v2.escribir_csv(pred_df, salida / "v4_walk_forward_predicciones_diarias.csv")
    v2.escribir_csv(resumen_df, salida / "v4_walk_forward_resumen.csv")
    v2.escribir_csv(estabilidad_df, salida / "v4_walk_forward_estabilidad.csv")
    (salida / "v4_walk_forward_manifiesto.json").write_text(
        json.dumps({
            "version": "modelo_salida_v4_walk_forward_diario",
            "frecuencia": "diaria",
            "regla": (
                "Para cada dia t, el entrenamiento solo incluye filas cuya fecha objetivo "
                "era anterior a t. El umbral se recalcula por cuantiles usando hasta 250 "
                "episodios historicos y conserva la cobertura seleccionada en validacion."
            ),
            "resumen": resumenes,
        }, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    (raiz / "docs" / "modelo_salida_resultados_v4_walk_forward.md").write_text(
        "\n".join([
            "# Auditoria walk-forward diaria — V4",
            "",
            resumen_df.to_markdown(index=False),
            "",
            "La salida SIN_SENAL es valida y esperada.",
            "No constituye una recomendacion financiera.",
        ]),
        encoding="utf-8",
    )
    print(resumen_df.to_string(index=False))
    print(estabilidad_df.to_string(index=False))


if __name__ == "__main__":
    main()
