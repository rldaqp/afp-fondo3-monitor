from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.metrics import roc_auc_score


def cargar_modulo(nombre: str, ruta: Path):
    spec = importlib.util.spec_from_file_location(nombre, ruta)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"No se pudo cargar {ruta}")
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = modulo
    spec.loader.exec_module(modulo)
    return modulo


def variantes(features: list[str]) -> dict[str, list[str]]:
    distancia = {
        "dias_desde_minimo_factor", "dias_desde_minimo_sbs",
        "rebote_desde_minimo_factor", "rebote_desde_minimo_sbs",
    }
    recuperacion = {
        "fraccion_recuperada_factor", "fraccion_recuperada_sbs",
    }
    velocidad = {
        "velocidad_rebote_factor", "velocidad_rebote_sbs",
        "cambio_velocidad_rebote_factor", "cambio_velocidad_rebote_sbs",
    }
    todos = distancia | recuperacion | velocidad
    return {
        "completo": list(features),
        "sin_distancia_minimo": [x for x in features if x not in distancia],
        "sin_fraccion_recuperada": [x for x in features if x not in recuperacion],
        "sin_velocidad_rebote": [x for x in features if x not in velocidad],
        "sin_variables_rebote": [x for x in features if x not in todos],
        "solo_variables_rebote": [x for x in features if x in todos],
    }


def metricas(df: pd.DataFrame, prob: np.ndarray, alerta: np.ndarray) -> dict[str, float]:
    y = df["caida_relevante_t1"].astype(int).to_numpy()
    p = np.asarray(prob, dtype=float)
    a = np.asarray(alerta, dtype=bool)
    tp = int(np.sum(a & (y == 1)))
    fp = int(np.sum(a & (y == 0)))
    fn = int(np.sum((~a) & (y == 1)))
    tn = int(np.sum((~a) & (y == 0)))
    precision = tp / (tp + fp) if tp + fp else np.nan
    recall = tp / (tp + fn) if tp + fn else np.nan
    falsas = fp / (fp + tn) if fp + tn else np.nan
    auc = float(roc_auc_score(y, p)) if len(np.unique(y)) == 2 else np.nan
    ret = pd.to_numeric(df["retorno_real_t1"], errors="coerce").to_numpy(dtype=float)
    evitada = float(np.sum(-ret[a & (ret < 0.0)]))
    sacrificada = float(np.sum(ret[a & (ret > 0.0)]))
    prev = float(y.mean())
    return {
        "n": len(y),
        "prevalencia_pct": prev * 100.0,
        "auc": auc,
        "n_alertas": int(a.sum()),
        "cobertura_dias_pct": float(a.mean() * 100.0),
        "precision_alerta_pct": precision * 100.0 if np.isfinite(precision) else np.nan,
        "mejora_precision_pp": (precision - prev) * 100.0 if np.isfinite(precision) else np.nan,
        "cobertura_caidas_pct": recall * 100.0 if np.isfinite(recall) else np.nan,
        "falsas_alarmas_pct": falsas * 100.0 if np.isfinite(falsas) else np.nan,
        "proteccion_neta_suma_pct": (evitada - sacrificada) * 100.0,
    }


def puntaje(m: dict[str, float]) -> float:
    lift = 0.0 if pd.isna(m["mejora_precision_pp"]) else m["mejora_precision_pp"] / 100.0
    recall = 0.0 if pd.isna(m["cobertura_caidas_pct"]) else m["cobertura_caidas_pct"] / 100.0
    falsas = 0.0 if pd.isna(m["falsas_alarmas_pct"]) else m["falsas_alarmas_pct"] / 100.0
    neta = m["proteccion_neta_suma_pct"] / 100.0 / max(m["n"], 1)
    return float(0.50 * lift + 0.20 * recall - 0.15 * falsas + 35.0 * neta)


def preparar_eventos(afp: str, base: pd.DataFrame, cfg: dict[str, Any], v2, v4) -> pd.DataFrame:
    g = base[base["afp"].astype(str).eq(afp)].copy()
    g["fecha_cuota"] = pd.to_datetime(g["fecha_cuota"], errors="coerce").dt.normalize()
    g["fecha_objetivo_t1"] = pd.to_datetime(g["fecha_objetivo_t1"], errors="coerce").dt.normalize()
    g, _ = v2.construir_episodios(g, cfg["configuracion_episodios"])
    g = v4.agregar_rebote_relativo(g)
    return g[g["en_episodio_rebote"] & g["caida_relevante_t1"].notna()].copy()


def seleccionar(train: pd.DataFrame, valid: pd.DataFrame, features: list[str], cfg: dict[str, Any], v4):
    filas: list[dict[str, Any]] = []
    modelos: dict[str, Any] = {}
    for codigo, modelo in v4.construir_modelos(cfg):
        modelo = clone(modelo)
        modelo.fit(train[features], train["caida_relevante_t1"].astype(int))
        modelos[codigo] = modelo
        prob = modelo.predict_proba(valid[features])[:, 1]
        for cobertura in cfg["seleccion_selectiva"]["coberturas_objetivo"]:
            umbral = float(np.quantile(prob, 1.0 - float(cobertura)))
            m = metricas(valid, prob, prob >= umbral)
            filas.append({
                "modelo_codigo": codigo,
                "cobertura_objetivo": float(cobertura),
                "umbral_probabilidad": umbral,
                **m,
                "puntaje_validacion": puntaje(m),
            })
    tabla = pd.DataFrame(filas)
    elegibles = tabla[
        tabla["n_alertas"].ge(int(cfg["seleccion_selectiva"]["min_alertas_validacion"]))
        & tabla["mejora_precision_pp"].ge(float(cfg["seleccion_selectiva"]["mejora_precision_minima_pp"]))
        & tabla["proteccion_neta_suma_pct"].gt(0.0)
    ]
    if elegibles.empty:
        elegibles = tabla[tabla["n_alertas"].ge(int(cfg["seleccion_selectiva"]["min_alertas_validacion"]))]
    if elegibles.empty:
        elegibles = tabla
    ganador = elegibles.sort_values(
        ["puntaje_validacion", "mejora_precision_pp", "proteccion_neta_suma_pct", "auc"],
        ascending=[False, False, False, False], na_position="last"
    ).iloc[0]
    return ganador, modelos[str(ganador["modelo_codigo"])], tabla


def walk_forward(eventos: pd.DataFrame, features: list[str], ganador: pd.Series, cfg: dict[str, Any], v4) -> pd.DataFrame:
    test = eventos[eventos["bloque_60_20_20"].eq("test_reservado")].sort_values("fecha_cuota")
    todas_fechas = pd.to_datetime(eventos["fecha_objetivo_t1"], errors="coerce").dt.normalize()
    cada = int(cfg["walk_forward"]["reentrenar_cada_observaciones"])
    minimo = int(cfg["walk_forward"]["minimo_eventos_historial"])
    modelo = None
    desde = cada
    filas: list[dict[str, Any]] = []
    codigo_objetivo = str(ganador["modelo_codigo"])
    cobertura = float(ganador["cobertura_objetivo"])

    for _, fila in test.iterrows():
        fecha = pd.Timestamp(fila["fecha_cuota"]).normalize()
        hist = eventos[todas_fechas < fecha].dropna(subset=["caida_relevante_t1"]).copy()
        if len(hist) < minimo or hist["caida_relevante_t1"].nunique() < 2:
            continue
        if modelo is None or desde >= cada:
            modelos = dict(v4.construir_modelos(cfg))
            modelo = clone(modelos[codigo_objetivo])
            modelo.fit(hist[features], hist["caida_relevante_t1"].astype(int))
            prob_hist = modelo.predict_proba(hist[features])[:, 1]
            umbral = float(np.quantile(prob_hist, 1.0 - cobertura))
            desde = 0
        p = float(modelo.predict_proba(pd.DataFrame([fila])[features])[:, 1][0])
        filas.append({
            "afp": fila["afp"],
            "fecha_cuota": fila["fecha_cuota"],
            "fecha_objetivo_t1": fila["fecha_objetivo_t1"],
            "retorno_real_t1": fila["retorno_real_t1"],
            "caida_relevante_t1": fila["caida_relevante_t1"],
            "probabilidad_riesgo": p,
            "umbral_probabilidad": umbral,
            "alerta_salida": p >= umbral,
        })
        desde += 1
    return pd.DataFrame(filas)


def main() -> None:
    raiz = Path(__file__).resolve().parents[2]
    salida = raiz / "data" / "processed" / "modelo_salida"
    cfg = json.loads((raiz / "config" / "modelo_salida_v4_selectivo_diario.json").read_text(encoding="utf-8"))
    v2 = cargar_modulo("v2_ablacion", raiz / "src" / "modelo_salida" / "04_modelo_rebote_salida_v2.py")
    v4 = cargar_modulo("v4_ablacion", raiz / "src" / "modelo_salida" / "06_modelo_selectivo_diario_v4.py")
    base = v2.leer_csv(salida / "base_modelo_salida.csv")

    resultados: list[dict[str, Any]] = []
    candidatos: list[pd.DataFrame] = []
    predicciones: list[pd.DataFrame] = []
    sets = variantes(list(v4.FEATURES))

    for afp in cfg["afps"]:
        eventos = preparar_eventos(afp, base, cfg, v2, v4)
        train = eventos[eventos["bloque_60_20_20"].eq("entrenamiento")].copy()
        valid = eventos[eventos["bloque_60_20_20"].eq("validacion")].copy()
        for nombre, features in sets.items():
            ganador, _, tabla = seleccionar(train, valid, features, cfg, v4)
            tabla.insert(0, "variante", nombre)
            tabla.insert(0, "afp", afp)
            candidatos.append(tabla)
            pred = walk_forward(eventos, features, ganador, cfg, v4)
            if pred.empty:
                continue
            m = metricas(pred, pred["probabilidad_riesgo"].to_numpy(), pred["alerta_salida"].to_numpy())
            resultados.append({
                "afp": afp,
                "frecuencia": "diaria",
                "variante": nombre,
                "n_features": len(features),
                "features": json.dumps(features, ensure_ascii=False),
                "modelo_codigo": ganador["modelo_codigo"],
                "cobertura_objetivo": ganador["cobertura_objetivo"],
                **{f"walk_{k}": v for k, v in m.items()},
            })
            pred.insert(0, "variante", nombre)
            predicciones.append(pred)

    resumen = pd.DataFrame(resultados)
    base_completa = resumen[resumen["variante"].eq("completo")][
        ["afp", "walk_auc", "walk_mejora_precision_pp", "walk_cobertura_caidas_pct", "walk_proteccion_neta_suma_pct"]
    ].rename(columns={
        "walk_auc": "base_auc",
        "walk_mejora_precision_pp": "base_mejora_precision_pp",
        "walk_cobertura_caidas_pct": "base_cobertura_caidas_pct",
        "walk_proteccion_neta_suma_pct": "base_proteccion_neta_suma_pct",
    })
    resumen = resumen.merge(base_completa, on="afp", how="left")
    resumen["delta_auc_vs_completo"] = resumen["walk_auc"] - resumen["base_auc"]
    resumen["delta_mejora_precision_pp_vs_completo"] = resumen["walk_mejora_precision_pp"] - resumen["base_mejora_precision_pp"]
    resumen["delta_cobertura_caidas_pp_vs_completo"] = resumen["walk_cobertura_caidas_pct"] - resumen["base_cobertura_caidas_pct"]
    resumen["delta_proteccion_neta_pp_vs_completo"] = resumen["walk_proteccion_neta_suma_pct"] - resumen["base_proteccion_neta_suma_pct"]

    def score_fila(r):
        return float(
            0.35 * r["walk_auc"]
            + 0.30 * (r["walk_mejora_precision_pp"] / 100.0)
            + 0.20 * (r["walk_cobertura_caidas_pct"] / 100.0)
            + 0.15 * np.tanh(r["walk_proteccion_neta_suma_pct"] / 10.0)
        )

    resumen["puntaje_congelacion"] = resumen.apply(score_fila, axis=1)
    ganadores = resumen.sort_values(
        ["afp", "puntaje_congelacion", "walk_proteccion_neta_suma_pct", "walk_auc"],
        ascending=[True, False, False, False]
    ).groupby("afp", as_index=False).head(1)

    v2.escribir_csv(resumen, salida / "v4_ablacion_resumen.csv")
    v2.escribir_csv(pd.concat(candidatos, ignore_index=True), salida / "v4_ablacion_candidatos_validacion.csv")
    v2.escribir_csv(pd.concat(predicciones, ignore_index=True), salida / "v4_ablacion_predicciones_walk_forward.csv")
    v2.escribir_csv(ganadores, salida / "v4_ablacion_ganadores.csv")
    (salida / "v4_ablacion_manifiesto.json").write_text(json.dumps({
        "version": "v4_ablacion_rebote_diaria",
        "frecuencia": "diaria",
        "variantes": {k: v for k, v in sets.items()},
        "regla": "Cada variante usa las mismas fechas, objetivo, modelos candidatos y walk-forward. Solo cambia el conjunto de variables.",
        "ganadores": ganadores.to_dict("records"),
    }, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    lineas = ["# Prueba de ablacion V4 diaria", "", "Comparacion walk-forward con las mismas fechas y el mismo objetivo.", ""]
    for _, r in ganadores.iterrows():
        lineas += [
            f"## {r['afp']}",
            f"- Mejor variante: **{r['variante']}**",
            f"- AUC: {r['walk_auc']:.3f}",
            f"- Mejora de precision: {r['walk_mejora_precision_pp']:+.2f} pp",
            f"- Cobertura de caidas: {r['walk_cobertura_caidas_pct']:.2f}%",
            f"- Proteccion neta: {r['walk_proteccion_neta_suma_pct']:+.2f}%",
            "",
        ]
    (raiz / "docs" / "modelo_salida_ablacion_v4.md").write_text("\n".join(lineas), encoding="utf-8")
    print(ganadores[["afp", "variante", "walk_auc", "walk_mejora_precision_pp", "walk_cobertura_caidas_pct", "walk_proteccion_neta_suma_pct"]].to_string(index=False))


if __name__ == "__main__":
    main()
