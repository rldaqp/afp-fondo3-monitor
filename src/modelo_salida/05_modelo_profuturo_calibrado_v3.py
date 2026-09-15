from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


def cargar_v2(raiz: Path):
    ruta = raiz / "src" / "modelo_salida" / "04_modelo_rebote_salida_v2.py"
    spec = importlib.util.spec_from_file_location("modelo_salida_v2_base", ruta)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"No se pudo cargar {ruta}")
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = modulo
    spec.loader.exec_module(modulo)
    return modulo


def base_modelo(df: pd.DataFrame, c: float, balanceado: bool, features: list[str]) -> Pipeline:
    modelo = Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("scaler", StandardScaler()),
        ("modelo", LogisticRegression(
            C=float(c),
            class_weight="balanced" if balanceado else None,
            max_iter=1000,
            solver="liblinear",
            random_state=42,
        )),
    ])
    modelo.fit(df[features], df["caida_relevante_t1"].astype(int))
    return modelo


def ajustar_calibrador(raw: np.ndarray, y: pd.Series, metodo: str):
    if metodo == "platt":
        calibrador = LogisticRegression(C=1e6, max_iter=1000, random_state=42)
        calibrador.fit(raw.reshape(-1, 1), y.astype(int))
        return calibrador
    if metodo == "isotonic":
        calibrador = IsotonicRegression(out_of_bounds="clip")
        calibrador.fit(raw, y.astype(int))
        return calibrador
    raise ValueError(f"Calibrador desconocido: {metodo}")


def calibrar(raw: np.ndarray, calibrador, metodo: str) -> np.ndarray:
    if metodo == "platt":
        return calibrador.predict_proba(raw.reshape(-1, 1))[:, 1]
    if metodo == "isotonic":
        return np.asarray(calibrador.predict(raw), dtype=float)
    raise ValueError(f"Calibrador desconocido: {metodo}")


def metricas(df: pd.DataFrame, prob: np.ndarray, umbral: float) -> dict[str, float]:
    y = df["caida_relevante_t1"].astype(int).to_numpy()
    p = np.asarray(prob, dtype=float)
    alerta = p >= float(umbral)
    tp = int(np.sum(alerta & (y == 1)))
    fp = int(np.sum(alerta & (y == 0)))
    fn = int(np.sum((~alerta) & (y == 1)))
    tn = int(np.sum((~alerta) & (y == 0)))
    precision = tp / (tp + fp) if tp + fp else np.nan
    recall = tp / (tp + fn) if tp + fn else np.nan
    falsas = fp / (fp + tn) if fp + tn else np.nan
    auc = float(roc_auc_score(y, p)) if len(np.unique(y)) == 2 else np.nan
    ret = pd.to_numeric(df["retorno_real_t1"], errors="coerce").to_numpy(dtype=float)
    evitada = float(np.sum(-ret[alerta & (ret < 0.0)]))
    sacrificada = float(np.sum(ret[alerta & (ret > 0.0)]))
    return {
        "n": len(y),
        "prevalencia_pct": float(y.mean() * 100.0),
        "auc": auc,
        "brier": float(brier_score_loss(y, p)),
        "n_alertas": int(alerta.sum()),
        "precision_alerta_pct": precision * 100.0 if np.isfinite(precision) else np.nan,
        "cobertura_caidas_pct": recall * 100.0 if np.isfinite(recall) else np.nan,
        "falsas_alarmas_pct": falsas * 100.0 if np.isfinite(falsas) else np.nan,
        "perdida_evitada_suma_pct": evitada * 100.0,
        "ganancia_sacrificada_suma_pct": sacrificada * 100.0,
        "proteccion_neta_suma_pct": (evitada - sacrificada) * 100.0,
    }


def puntaje(m: dict[str, float]) -> float:
    prev = m["prevalencia_pct"] / 100.0
    prec = 0.0 if pd.isna(m["precision_alerta_pct"]) else m["precision_alerta_pct"] / 100.0
    rec = 0.0 if pd.isna(m["cobertura_caidas_pct"]) else m["cobertura_caidas_pct"] / 100.0
    falsas = 0.0 if pd.isna(m["falsas_alarmas_pct"]) else m["falsas_alarmas_pct"] / 100.0
    neta = m["proteccion_neta_suma_pct"] / 100.0 / max(m["n"], 1)
    brier = m["brier"]
    return float(
        0.45 * (prec - prev)
        + 0.20 * rec
        - 0.15 * falsas
        + 35.0 * neta
        - 0.10 * brier
    )


def evaluar_segmento(nombre: str, df: pd.DataFrame, prob: np.ndarray, umbral: float) -> dict[str, Any]:
    return {"segmento": nombre, **metricas(df, prob, umbral)}


def main() -> None:
    raiz = Path(__file__).resolve().parents[2]
    salida = raiz / "data" / "processed" / "modelo_salida"
    cfg = json.loads(
        (raiz / "config" / "modelo_salida_v3_profuturo.json").read_text(encoding="utf-8")
    )
    v2 = cargar_v2(raiz)
    base = v2.leer_csv(salida / "base_modelo_salida.csv")
    base["fecha_cuota"] = pd.to_datetime(base["fecha_cuota"], errors="coerce").dt.normalize()
    base["fecha_objetivo_t1"] = pd.to_datetime(
        base["fecha_objetivo_t1"], errors="coerce"
    ).dt.normalize()

    afp = str(cfg["afp"])
    g = base[base["afp"].astype(str).eq(afp)].copy()
    episodios, umbral_shock = v2.construir_episodios(g, cfg["configuracion_v2"])
    eventos = episodios[
        episodios["en_episodio_rebote"]
        & episodios["caida_relevante_t1"].notna()
    ].copy()
    train = eventos[eventos["bloque_60_20_20"].eq("entrenamiento")].copy()
    valid = eventos[eventos["bloque_60_20_20"].eq("validacion")].copy()
    test = eventos[eventos["bloque_60_20_20"].eq("test_reservado")].copy()
    features = list(v2.FEATURES)

    candidatos: list[dict[str, Any]] = []
    objetos: dict[tuple[float, bool, str], tuple[Pipeline, Any]] = {}
    for c in cfg["candidatos"]["C"]:
        for balanceado in cfg["candidatos"]["balanceado"]:
            modelo = base_modelo(train, float(c), bool(balanceado), features)
            raw_valid = modelo.predict_proba(valid[features])[:, 1]
            for metodo in cfg["candidatos"]["calibrador"]:
                calibrador = ajustar_calibrador(
                    raw_valid,
                    valid["caida_relevante_t1"],
                    str(metodo),
                )
                prob_valid = calibrar(raw_valid, calibrador, str(metodo))
                objetos[(float(c), bool(balanceado), str(metodo))] = (modelo, calibrador)
                for umbral in cfg["seleccion"]["umbrales_probabilidad"]:
                    m = metricas(valid, prob_valid, float(umbral))
                    candidatos.append({
                        "C": float(c),
                        "balanceado": bool(balanceado),
                        "calibrador": str(metodo),
                        "umbral_probabilidad": float(umbral),
                        **m,
                        "puntaje_validacion": puntaje(m),
                    })

    tabla = pd.DataFrame(candidatos)
    tabla["mejora_precision_pp"] = (
        tabla["precision_alerta_pct"] - tabla["prevalencia_pct"]
    )
    prevalencia_valid = float(valid["caida_relevante_t1"].mean())
    tabla["brier_base_validacion"] = prevalencia_valid * (1.0 - prevalencia_valid)
    elegibles = tabla[
        tabla["n_alertas"].ge(int(cfg["seleccion"]["min_alertas_validacion"]))
        & tabla["mejora_precision_pp"].ge(
            float(cfg["seleccion"]["mejora_precision_minima_pp"])
        )
        & tabla["proteccion_neta_suma_pct"].gt(0.0)
        & tabla["brier"].lt(tabla["brier_base_validacion"])
    ]
    if elegibles.empty:
        elegibles = tabla[
            tabla["n_alertas"].ge(int(cfg["seleccion"]["min_alertas_validacion"]))
        ]
    if elegibles.empty:
        elegibles = tabla
    ganador = elegibles.sort_values(
        [
            "proteccion_neta_suma_pct",
            "precision_alerta_pct",
            "brier",
            "auc",
        ],
        ascending=[False, False, True, False],
        na_position="last",
    ).iloc[0]

    clave = (
        float(ganador["C"]),
        bool(ganador["balanceado"]),
        str(ganador["calibrador"]),
    )
    modelo, calibrador = objetos[clave]
    raw_test = modelo.predict_proba(test[features])[:, 1]
    prob_test = calibrar(raw_test, calibrador, clave[2])
    umbral = float(ganador["umbral_probabilidad"])
    met_total = metricas(test, prob_test, umbral)
    corte = len(test) // 2
    segmentos = pd.DataFrame([
        evaluar_segmento("test_primera_mitad", test.iloc[:corte], prob_test[:corte], umbral),
        evaluar_segmento("test_segunda_mitad", test.iloc[corte:], prob_test[corte:], umbral),
    ])
    brier_base = float(
        ((test["caida_relevante_t1"] - test["caida_relevante_t1"].mean()) ** 2).mean()
    )

    criterios_principales = {
        "alertas_min_20": met_total["n_alertas"] >= 20,
        "auc_min_0_55": met_total["auc"] >= 0.55,
        "brier_mejor_que_base": met_total["brier"] < brier_base,
        "precision_supera_prevalencia_8pp": (
            met_total["precision_alerta_pct"] >= met_total["prevalencia_pct"] + 8.0
        ),
        "cobertura_caidas_min_15pct": met_total["cobertura_caidas_pct"] >= 15.0,
        "proteccion_neta_positiva": met_total["proteccion_neta_suma_pct"] > 0.0,
    }
    criterios_estabilidad = {
        "auc_primera_mitad_min_0_55": float(segmentos.iloc[0]["auc"]) >= 0.55,
        "auc_segunda_mitad_min_0_55": float(segmentos.iloc[1]["auc"]) >= 0.55,
        "proteccion_neta_positiva_primera_mitad": (
            float(segmentos.iloc[0]["proteccion_neta_suma_pct"]) > 0.0
        ),
        "proteccion_neta_positiva_segunda_mitad": (
            float(segmentos.iloc[1]["proteccion_neta_suma_pct"]) > 0.0
        ),
    }
    if all(criterios_principales.values()) and all(criterios_estabilidad.values()):
        estado = "APROBADO_PARA_SEGUIMIENTO_PROSPECTIVO"
    elif all(criterios_principales.values()):
        estado = "PROMETEDOR_PERO_INESTABLE"
    else:
        estado = "NO_APROBADO_V3"

    pred = test[
        [
            "afp",
            "fecha_cuota",
            "fecha_objetivo_t1",
            "retorno_real_t1",
            "umbral_caida_relevante",
            "caida_relevante_t1",
        ]
    ].copy()
    pred["probabilidad_calibrada"] = prob_test
    pred["umbral_probabilidad"] = umbral
    pred["alerta_salida"] = prob_test >= umbral

    resumen = pd.DataFrame([{
        "afp": afp,
        "C": clave[0],
        "balanceado": clave[1],
        "calibrador": clave[2],
        "umbral_probabilidad": umbral,
        "umbral_shock_factores": umbral_shock,
        "n_train": len(train),
        "n_valid": len(valid),
        "n_test": len(test),
        **met_total,
        "brier_base_prevalencia": brier_base,
        "criterios_principales": json.dumps(
            criterios_principales, ensure_ascii=False, sort_keys=True
        ),
        "criterios_estabilidad": json.dumps(
            criterios_estabilidad, ensure_ascii=False, sort_keys=True
        ),
        "estado": estado,
    }])

    v2.escribir_csv(tabla, salida / "v3_profuturo_candidatos_validacion.csv")
    v2.escribir_csv(pred, salida / "v3_profuturo_predicciones_test.csv")
    v2.escribir_csv(segmentos, salida / "v3_profuturo_estabilidad_temporal.csv")
    v2.escribir_csv(resumen, salida / "v3_profuturo_resumen.csv")
    (salida / "v3_profuturo_manifiesto.json").write_text(
        json.dumps({
            "version": "modelo_salida_v3_profuturo_calibrado",
            "regla": (
                "Modelo base entrenado con 60%; calibrador y umbral elegidos con "
                "validacion; el 20% final permanece intacto hasta la evaluacion."
            ),
            "configuracion": cfg,
            "ganador": ganador.to_dict(),
            "criterios_principales": criterios_principales,
            "criterios_estabilidad": criterios_estabilidad,
            "estado": estado,
        }, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    (raiz / "docs" / "modelo_salida_resultados_v3_profuturo.md").write_text(
        "\n".join([
            "# Modelo de salida V3 — Profuturo",
            "",
            f"Estado: **{estado}**",
            "",
            f"- AUC test: {met_total['auc']:.3f}",
            f"- Brier: {met_total['brier']:.4f} frente a base {brier_base:.4f}",
            f"- Precision de alerta: {met_total['precision_alerta_pct']:.2f}%",
            f"- Cobertura de caidas: {met_total['cobertura_caidas_pct']:.2f}%",
            f"- Proteccion neta simulada: {met_total['proteccion_neta_suma_pct']:+.2f}%",
            "",
            "La prueba final es historica y no reemplaza el seguimiento prospectivo.",
            "No constituye una recomendacion financiera.",
        ]),
        encoding="utf-8",
    )
    print(resumen.to_string(index=False))
    print(segmentos.to_string(index=False))


if __name__ == "__main__":
    main()
