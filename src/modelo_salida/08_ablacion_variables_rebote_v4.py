from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


AFPS = ["Habitat", "Integra", "Prima", "Profuturo"]

BASE_FEATURES = [
    "retorno_medio_factores",
    "amplitud_factores_positivos",
    "amplitud_factores_negativos",
    "dispersion_factores",
    "factor_aceleracion",
    "factor_momentum_2",
    "factor_momentum_3",
    "factor_volatilidad_5",
    "momentum_sbs_3",
    "momentum_sbs_5",
    "vol_sbs_5",
    "vol_sbs_10",
    "aceleracion_sbs",
]

GRUPOS_REBOTE = {
    "distancia_temporal": [
        "dias_desde_shock",
        "dias_desde_minimo_factor",
        "dias_desde_minimo_sbs",
    ],
    "nivel_fraccion_recuperada": [
        "rebote_desde_minimo_factor",
        "fraccion_recuperada_factor",
        "rebote_desde_minimo_sbs",
        "fraccion_recuperada_sbs",
    ],
    "velocidad_rebote": [
        "velocidad_rebote_factor",
        "cambio_velocidad_rebote_factor",
        "velocidad_rebote_sbs",
        "cambio_velocidad_rebote_sbs",
    ],
    "retroceso_desde_maximo": [
        "retroceso_desde_maximo_factor",
        "retroceso_desde_maximo_sbs",
    ],
}


def cargar_modulo(nombre: str, ruta: Path):
    spec = importlib.util.spec_from_file_location(nombre, ruta)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"No se pudo cargar {ruta}")
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = modulo
    spec.loader.exec_module(modulo)
    return modulo


def variantes_features() -> dict[str, list[str]]:
    todos_rebote = [x for grupo in GRUPOS_REBOTE.values() for x in grupo]
    variantes: dict[str, list[str]] = {
        "base_sin_rebote": list(BASE_FEATURES),
        "completo": list(BASE_FEATURES) + todos_rebote,
    }
    for grupo, columnas in GRUPOS_REBOTE.items():
        variantes[f"completo_sin_{grupo}"] = (
            list(BASE_FEATURES) + [x for x in todos_rebote if x not in columnas]
        )
    return variantes


def preparar_eventos(
    afp: str,
    base: pd.DataFrame,
    cfg: dict[str, Any],
    v2,
    v4,
) -> pd.DataFrame:
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


def limpiar(v4, df: pd.DataFrame, features: list[str]) -> pd.DataFrame:
    faltan = [c for c in features if c not in df.columns]
    if faltan:
        raise RuntimeError(f"Faltan variables de ablacion: {faltan}")
    return v4.limpiar_numericos(df, features)


def seleccionar_en_validacion(
    eventos: pd.DataFrame,
    features: list[str],
    cfg: dict[str, Any],
    v4,
) -> tuple[pd.Series, pd.DataFrame]:
    train = eventos[eventos["bloque_60_20_20"].eq("entrenamiento")].copy()
    valid = eventos[eventos["bloque_60_20_20"].eq("validacion")].copy()
    if min(len(train), len(valid)) < 50:
        raise RuntimeError("Muestra insuficiente en entrenamiento o validacion")

    train = limpiar(v4, train, features)
    valid = limpiar(v4, valid, features)
    filas: list[dict[str, Any]] = []
    for codigo, modelo in v4.construir_modelos(cfg):
        modelo.fit(train[features], train["caida_relevante_t1"].astype(int))
        prob = modelo.predict_proba(valid[features])[:, 1]
        for cobertura in cfg["seleccion_selectiva"]["coberturas_objetivo"]:
            umbral = float(np.quantile(prob, 1.0 - float(cobertura)))
            alerta = prob >= umbral
            met = v4.metricas(valid, prob, alerta)
            filas.append({
                "modelo_codigo": codigo,
                "cobertura_objetivo": float(cobertura),
                "umbral_validacion": umbral,
                **met,
                "puntaje_validacion": v4.puntaje(met),
            })

    tabla = pd.DataFrame(filas)
    elegibles = tabla[
        tabla["n_alertas"].ge(
            int(cfg["seleccion_selectiva"]["min_alertas_validacion"])
        )
        & tabla["mejora_precision_pp"].ge(
            float(cfg["seleccion_selectiva"]["mejora_precision_minima_pp"])
        )
        & tabla["proteccion_neta_suma_pct"].gt(0.0)
    ]
    if elegibles.empty:
        elegibles = tabla[
            tabla["n_alertas"].ge(
                int(cfg["seleccion_selectiva"]["min_alertas_validacion"])
            )
        ]
    if elegibles.empty:
        elegibles = tabla
    ganador = elegibles.sort_values(
        ["puntaje_validacion", "mejora_precision_pp", "proteccion_neta_suma_pct", "auc"],
        ascending=[False, False, False, False],
        na_position="last",
    ).iloc[0]
    return ganador, tabla


def modelo_por_codigo(v4, cfg: dict[str, Any], codigo: str):
    for cod, modelo in v4.construir_modelos(cfg):
        if cod == codigo:
            return modelo
    raise RuntimeError(f"Modelo no encontrado: {codigo}")


def metricas_segmento(v4, nombre: str, df: pd.DataFrame) -> dict[str, Any]:
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


def walk_forward(
    afp: str,
    variante: str,
    eventos: pd.DataFrame,
    features: list[str],
    seleccion: pd.Series,
    cfg: dict[str, Any],
    v4,
) -> tuple[pd.DataFrame, dict[str, Any], pd.DataFrame]:
    test = eventos[eventos["bloque_60_20_20"].eq("test_reservado")].copy()
    test = test.sort_values("fecha_cuota")
    codigo = str(seleccion["modelo_codigo"])
    cobertura = float(seleccion["cobertura_objetivo"])
    cada = int(cfg["walk_forward"]["reentrenar_cada_observaciones"])
    minimo = int(cfg["walk_forward"]["minimo_eventos_historial"])
    ventana_umbral = 250
    fechas_obj = pd.to_datetime(eventos["fecha_objetivo_t1"], errors="coerce").dt.normalize()

    modelo = None
    umbral = np.nan
    desde = cada
    filas: list[dict[str, Any]] = []
    for _, fila in test.iterrows():
        fecha = pd.Timestamp(fila["fecha_cuota"]).normalize()
        hist = eventos[fechas_obj < fecha].dropna(subset=["caida_relevante_t1"]).copy()
        if len(hist) < minimo or hist["caida_relevante_t1"].nunique() < 2:
            continue
        if modelo is None or desde >= cada:
            modelo = modelo_por_codigo(v4, cfg, codigo)
            hist_limpio = limpiar(v4, hist, features)
            modelo.fit(hist_limpio[features], hist_limpio["caida_relevante_t1"].astype(int))
            calibracion = hist_limpio.tail(min(ventana_umbral, len(hist_limpio))).copy()
            prob_hist = modelo.predict_proba(calibracion[features])[:, 1]
            umbral = float(np.quantile(prob_hist, 1.0 - cobertura))
            desde = 0

        fila_df = limpiar(v4, pd.DataFrame([fila]), features)
        prob = float(modelo.predict_proba(fila_df[features])[:, 1][0])
        alerta = bool(prob >= umbral)
        filas.append({
            "afp": afp,
            "variante": variante,
            "fecha_cuota": fila["fecha_cuota"],
            "fecha_objetivo_t1": fila["fecha_objetivo_t1"],
            "retorno_real_t1": fila["retorno_real_t1"],
            "umbral_caida_relevante": fila["umbral_caida_relevante"],
            "caida_relevante_t1": fila["caida_relevante_t1"],
            "probabilidad_riesgo": prob,
            "umbral_dinamico": umbral,
            "alerta_salida": alerta,
            "estado_diario": "RIESGO_ALTO" if alerta else "SIN_SENAL",
            "modelo_codigo": codigo,
            "cobertura_objetivo": cobertura,
            "n_historial_disponible": len(hist),
        })
        desde += 1

    pred = pd.DataFrame(filas)
    if pred.empty:
        raise RuntimeError(f"Walk-forward vacio para {afp}/{variante}")
    met = v4.metricas(
        pred,
        pred["probabilidad_riesgo"].to_numpy(dtype=float),
        pred["alerta_salida"].astype(bool).to_numpy(),
    )
    corte = len(pred) // 2
    estabilidad = pd.DataFrame([
        metricas_segmento(v4, "primera_mitad", pred.iloc[:corte].copy()),
        metricas_segmento(v4, "segunda_mitad", pred.iloc[corte:].copy()),
    ])
    estabilidad.insert(0, "variante", variante)
    estabilidad.insert(0, "afp", afp)
    segunda = estabilidad[estabilidad["segmento"].eq("segunda_mitad")].iloc[0]
    resumen = {
        "afp": afp,
        "variante": variante,
        "n_features": len(features),
        "features": json.dumps(features, ensure_ascii=False),
        "modelo_codigo": codigo,
        "cobertura_objetivo": cobertura,
        **{f"walk_{k}": v for k, v in met.items()},
        "segunda_auc": segunda.get("auc"),
        "segunda_mejora_precision_pp": segunda.get("mejora_precision_pp"),
        "segunda_proteccion_neta_suma_pct": segunda.get("proteccion_neta_suma_pct"),
    }
    return pred, resumen, estabilidad


def construir_deltas(resumen: pd.DataFrame) -> pd.DataFrame:
    filas: list[dict[str, Any]] = []
    metricas = [
        "walk_auc",
        "walk_brier",
        "walk_precision_alerta_pct",
        "walk_mejora_precision_pp",
        "walk_cobertura_caidas_pct",
        "walk_falsas_alarmas_pct",
        "walk_proteccion_neta_suma_pct",
        "segunda_auc",
        "segunda_mejora_precision_pp",
        "segunda_proteccion_neta_suma_pct",
    ]
    for afp, g in resumen.groupby("afp"):
        full = g[g["variante"].eq("completo")].iloc[0]
        for variante, fila in g.set_index("variante").iterrows():
            if variante == "completo":
                continue
            salida = {"afp": afp, "comparacion": f"completo_menos_{variante}"}
            for met in metricas:
                salida[f"delta_{met}"] = float(full[met]) - float(fila[met])
            filas.append(salida)
    return pd.DataFrame(filas)


def elegir_para_congelar(resumen: pd.DataFrame) -> pd.DataFrame:
    filas: list[dict[str, Any]] = []
    for afp, g in resumen.groupby("afp"):
        elegible = g[
            g["walk_n_alertas"].ge(20)
            & g["walk_auc"].ge(0.55)
            & g["walk_mejora_precision_pp"].ge(8.0)
            & g["walk_cobertura_caidas_pct"].ge(15.0)
            & g["walk_proteccion_neta_suma_pct"].gt(0.0)
            & g["segunda_auc"].ge(0.52)
            & g["segunda_mejora_precision_pp"].ge(0.0)
            & g["segunda_proteccion_neta_suma_pct"].gt(0.0)
        ].copy()
        if elegible.empty:
            mejor = g.sort_values(
                ["segunda_proteccion_neta_suma_pct", "segunda_mejora_precision_pp", "walk_auc"],
                ascending=[False, False, False],
            ).iloc[0]
            estado = "NO_CONGELAR"
        else:
            mejor = elegible.sort_values(
                ["segunda_proteccion_neta_suma_pct", "segunda_mejora_precision_pp", "walk_auc", "n_features"],
                ascending=[False, False, False, True],
            ).iloc[0]
            estado = "CANDIDATO_A_CONGELAR"
        filas.append({
            "afp": afp,
            "variante_elegida": mejor["variante"],
            "modelo_codigo": mejor["modelo_codigo"],
            "cobertura_objetivo": mejor["cobertura_objetivo"],
            "n_features": mejor["n_features"],
            "features": mejor["features"],
            "walk_auc": mejor["walk_auc"],
            "walk_mejora_precision_pp": mejor["walk_mejora_precision_pp"],
            "walk_proteccion_neta_suma_pct": mejor["walk_proteccion_neta_suma_pct"],
            "segunda_auc": mejor["segunda_auc"],
            "segunda_mejora_precision_pp": mejor["segunda_mejora_precision_pp"],
            "segunda_proteccion_neta_suma_pct": mejor["segunda_proteccion_neta_suma_pct"],
            "estado": estado,
        })
    return pd.DataFrame(filas)


def main() -> None:
    raiz = Path(__file__).resolve().parents[2]
    salida = raiz / "data" / "processed" / "modelo_salida"
    v2 = cargar_modulo(
        "modelo_salida_v2_para_ablacion",
        raiz / "src" / "modelo_salida" / "04_modelo_rebote_salida_v2.py",
    )
    v4 = cargar_modulo(
        "modelo_salida_v4_para_ablacion",
        raiz / "src" / "modelo_salida" / "06_modelo_selectivo_diario_v4.py",
    )
    cfg = json.loads(
        (raiz / "config" / "modelo_salida_v4_selectivo_diario.json").read_text(
            encoding="utf-8"
        )
    )
    if cfg.get("frecuencia") != "diaria":
        raise RuntimeError("La ablacion debe conservar frecuencia diaria")
    base = v2.leer_csv(salida / "base_modelo_salida.csv")
    variantes = variantes_features()

    resumenes: list[dict[str, Any]] = []
    predicciones: list[pd.DataFrame] = []
    estabilidad: list[pd.DataFrame] = []
    candidatos_validacion: list[pd.DataFrame] = []
    for afp in AFPS:
        eventos = preparar_eventos(afp, base, cfg, v2, v4)
        for variante, features in variantes.items():
            seleccion, candidatos = seleccionar_en_validacion(
                eventos, features, cfg, v4
            )
            candidatos.insert(0, "variante", variante)
            candidatos.insert(0, "afp", afp)
            candidatos_validacion.append(candidatos)
            pred, resumen, est = walk_forward(
                afp, variante, eventos, features, seleccion, cfg, v4
            )
            predicciones.append(pred)
            resumenes.append(resumen)
            estabilidad.append(est)

    resumen_df = pd.DataFrame(resumenes)
    pred_df = pd.concat(predicciones, ignore_index=True)
    estabilidad_df = pd.concat(estabilidad, ignore_index=True)
    candidatos_df = pd.concat(candidatos_validacion, ignore_index=True)
    deltas_df = construir_deltas(resumen_df)
    congelar_df = elegir_para_congelar(resumen_df)

    v2.escribir_csv(resumen_df, salida / "v4_ablacion_resumen.csv")
    v2.escribir_csv(deltas_df, salida / "v4_ablacion_deltas.csv")
    v2.escribir_csv(estabilidad_df, salida / "v4_ablacion_estabilidad.csv")
    v2.escribir_csv(pred_df, salida / "v4_ablacion_predicciones.csv")
    v2.escribir_csv(candidatos_df, salida / "v4_ablacion_candidatos_validacion.csv")
    v2.escribir_csv(congelar_df, salida / "v4_ablacion_seleccion_congelar.csv")

    manifiesto = {
        "version": "modelo_salida_v4_ablacion_rebote",
        "frecuencia": "diaria",
        "metodo": (
            "Cada variante selecciona modelo y cobertura solo en validacion y se "
            "evalua walk-forward usando exclusivamente objetivos conocidos antes de t."
        ),
        "variantes": variantes,
        "grupos_rebote": GRUPOS_REBOTE,
        "seleccion_congelar": congelar_df.to_dict("records"),
    }
    (salida / "v4_ablacion_manifiesto.json").write_text(
        json.dumps(manifiesto, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    (raiz / "docs" / "modelo_salida_resultados_v4_ablacion.md").write_text(
        "\n".join([
            "# Prueba de ablacion — variables de rebote V4",
            "",
            "Frecuencia: **diaria**.",
            "",
            "## Seleccion para posible congelamiento",
            "",
            congelar_df.to_markdown(index=False),
            "",
            "## Diferencias del modelo completo frente a cada eliminacion",
            "",
            deltas_df.to_markdown(index=False),
            "",
            "Los resultados son historicos y experimentales; no constituyen una recomendacion financiera.",
        ]),
        encoding="utf-8",
    )
    print(congelar_df.to_string(index=False))
    print(deltas_df.to_string(index=False))


if __name__ == "__main__":
    main()
