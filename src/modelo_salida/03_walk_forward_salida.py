from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss


AFPS = ["Habitat", "Integra", "Prima", "Profuturo"]
REENTRENAR_CADA = 20
MIN_HISTORIA = 600


def cargar_modulo02(raiz: Path):
    ruta = raiz / "src" / "modelo_salida" / "02_entrenar_modelos_60_20_20.py"
    spec = importlib.util.spec_from_file_location("modelo_salida_entrenamiento", ruta)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"No se pudo cargar {ruta}")
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = modulo
    spec.loader.exec_module(modulo)
    return modulo


def leer_csv(ruta: Path) -> pd.DataFrame:
    if not ruta.exists():
        raise FileNotFoundError(f"No existe el archivo requerido: {ruta}")
    ultimo_error: Exception | None = None
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return pd.read_csv(ruta, encoding=encoding, low_memory=False)
        except Exception as exc:
            ultimo_error = exc
    raise RuntimeError(f"No se pudo leer {ruta}: {ultimo_error}")


def escribir_csv(df: pd.DataFrame, ruta: Path) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(ruta, index=False, encoding="utf-8-sig", date_format="%Y-%m-%d")


def valor_numerico(valor: Any) -> float:
    x = pd.to_numeric(valor, errors="coerce")
    return float(x) if pd.notna(x) else np.nan


def procesar_afp(
    afp: str,
    base: pd.DataFrame,
    seleccion: dict[str, Any],
    modulo02,
) -> tuple[dict[str, Any], pd.DataFrame]:
    g = base[base["afp"].astype(str).eq(afp)].copy()
    g["fecha_cuota"] = pd.to_datetime(g["fecha_cuota"], errors="coerce").dt.normalize()
    g["fecha_objetivo_t1"] = pd.to_datetime(g["fecha_objetivo_t1"], errors="coerce").dt.normalize()
    g["caida_t1"] = pd.to_numeric(g["caida_t1"], errors="coerce")
    g["retorno_real_t1"] = pd.to_numeric(g["retorno_real_t1"], errors="coerce")
    g = g.dropna(subset=["fecha_cuota", "fecha_objetivo_t1", "caida_t1"]).sort_values("fecha_cuota")

    test = g[g["bloque_60_20_20"].eq("test_reservado")].copy().reset_index(drop=True)
    inicial = g[g["bloque_60_20_20"].isin(["entrenamiento", "validacion"])].copy()
    if test.empty or len(inicial) < MIN_HISTORIA:
        raise RuntimeError(f"Muestra insuficiente para walk-forward en {afp}")

    columnas = [str(c) for c in seleccion["columnas"] if str(c) in g.columns]
    if not columnas:
        raise RuntimeError(f"No quedaron columnas para {afp}")

    familia = str(seleccion["familia"])
    parametros = dict(seleccion["parametros"])
    umbral = float(seleccion["umbral_probabilidad"])

    modelo = None
    fecha_ultimo_ajuste = pd.NaT
    n_ultimo_ajuste = 0
    filas: list[dict[str, Any]] = []

    for numero, (_, fila) in enumerate(test.iterrows()):
        fecha_decision = pd.Timestamp(fila["fecha_cuota"])

        # Regla de publicación: al decidir en t no se incorpora una fila cuyo
        # resultado objetivo corresponda a t. Solo se usan objetivos anteriores
        # a la fecha de decisión, evitando aprender de una cuota aún no publicada.
        historia = g[
            g["fecha_objetivo_t1"].lt(fecha_decision)
            & g["caida_t1"].notna()
        ].copy().sort_values("fecha_cuota")

        if len(historia) < MIN_HISTORIA:
            continue

        debe_ajustar = modelo is None or numero % REENTRENAR_CADA == 0
        if debe_ajustar:
            modelo = modulo02.ajustar_calibrado(
                historia,
                columnas,
                familia,
                parametros,
            )
            fecha_ultimo_ajuste = fecha_decision
            n_ultimo_ajuste = len(historia)

        fila_df = pd.DataFrame([fila])
        probabilidad = float(modelo.predict_proba(fila_df)[0])
        evidencia = int(modulo02.evidencia_riesgo(fila_df).iloc[0])
        estado = str(
            modulo02.clasificar_estado(
                pd.Series([probabilidad]),
                umbral,
                pd.Series([evidencia]),
            ).iloc[0]
        )

        filas.append(
            {
                "afp": afp,
                "fecha_decision": fecha_decision,
                "fecha_objetivo_t1": fila["fecha_objetivo_t1"],
                "retorno_real_t1": valor_numerico(fila["retorno_real_t1"]),
                "caida_t1": int(fila["caida_t1"]),
                "probabilidad_caida_t1": probabilidad,
                "umbral_probabilidad": umbral,
                "alerta_probabilistica": probabilidad >= umbral,
                "evidencias_adicionales": evidencia,
                "estado_salida": estado,
                "fecha_ultimo_ajuste": fecha_ultimo_ajuste,
                "n_historia_ultimo_ajuste": n_ultimo_ajuste,
                "regla_publicacion": "fecha_objetivo_entrenamiento < fecha_decision",
            }
        )

    detalle = pd.DataFrame(filas)
    if detalle.empty:
        raise RuntimeError(f"No se generaron predicciones walk-forward para {afp}")

    y = detalle["caida_t1"].astype(int).to_numpy()
    prob = detalle["probabilidad_caida_t1"].astype(float).to_numpy()
    met_prob = modulo02.metricas_probabilidad(y, prob)
    met_alerta = modulo02.metricas_alerta(y, prob, umbral)

    riesgo_alto = detalle["estado_salida"].eq("RIESGO_ALTO").astype(float).to_numpy()
    met_riesgo_alto = modulo02.metricas_alerta(y, riesgo_alto, 0.5)

    prevalencia_inicial = float(inicial["caida_t1"].astype(int).mean())
    prob_base = np.full(len(y), prevalencia_inicial, dtype=float)
    brier_base = float(brier_score_loss(y, prob_base))
    prevalencia_test = float(np.mean(y) * 100.0)
    precision = met_alerta["precision_alerta_pct"]
    mejora_precision = precision - prevalencia_test if pd.notna(precision) else np.nan

    criterios = {
        "cobertura_predicciones_min_90pct": len(detalle) >= int(len(test) * 0.90),
        "alertas_min_20": met_alerta["n_alertas"] >= 20,
        "auc_min_0_55": pd.notna(met_prob["auc"]) and met_prob["auc"] >= 0.55,
        "brier_mejor_que_base": met_prob["brier"] < brier_base,
        "precision_supera_prevalencia_5pp": pd.notna(mejora_precision) and mejora_precision >= 5.0,
        "cobertura_caidas_min_20pct": pd.notna(met_alerta["cobertura_caidas_pct"])
        and met_alerta["cobertura_caidas_pct"] >= 20.0,
    }
    aprobado = all(criterios.values())

    resumen = {
        "afp": afp,
        "modelo_codigo": seleccion["modelo_codigo"],
        "familia": familia,
        "umbral_probabilidad": umbral,
        "n_variables": len(columnas),
        "reentrenar_cada_observaciones": REENTRENAR_CADA,
        "n_test_original": len(test),
        "n_predicciones_walk_forward": len(detalle),
        "prevalencia_caida_test_pct": prevalencia_test,
        "brier_base_prevalencia": brier_base,
        "walk_brier": met_prob["brier"],
        "walk_auc": met_prob["auc"],
        "walk_precision_alerta_pct": met_alerta["precision_alerta_pct"],
        "walk_cobertura_caidas_pct": met_alerta["cobertura_caidas_pct"],
        "walk_falsas_alarmas_pct": met_alerta["falsas_alarmas_pct"],
        "walk_n_alertas": met_alerta["n_alertas"],
        "walk_mejora_precision_vs_prevalencia_pp": mejora_precision,
        "walk_precision_riesgo_alto_pct": met_riesgo_alto["precision_alerta_pct"],
        "walk_cobertura_caidas_riesgo_alto_pct": met_riesgo_alto["cobertura_caidas_pct"],
        "walk_n_riesgo_alto": met_riesgo_alto["n_alertas"],
        "criterios": json.dumps(criterios, ensure_ascii=False, sort_keys=True),
        "estado": "APROBADO_WALK_FORWARD" if aprobado else "NO_APROBADO_WALK_FORWARD",
    }
    return resumen, detalle


def main() -> None:
    raiz = Path(__file__).resolve().parents[2]
    processed = raiz / "data" / "processed" / "modelo_salida"
    base = leer_csv(processed / "base_modelo_salida.csv")
    selecciones = json.loads((processed / "seleccion_modelos.json").read_text(encoding="utf-8"))
    modulo02 = cargar_modulo02(raiz)

    resumenes: list[dict[str, Any]] = []
    detalles: list[pd.DataFrame] = []

    for afp in AFPS:
        resumen, detalle = procesar_afp(afp, base, selecciones[afp], modulo02)
        resumenes.append(resumen)
        detalles.append(detalle)

    resumen_df = pd.DataFrame(resumenes)
    detalle_df = pd.concat(detalles, ignore_index=True)
    escribir_csv(resumen_df, processed / "walk_forward_resumen.csv")
    escribir_csv(detalle_df, processed / "walk_forward_predicciones.csv")

    manifiesto = {
        "version": "modelo_salida_walk_forward_v1",
        "generado_utc": datetime.now(timezone.utc).isoformat(),
        "objetivo": "Auditar la probabilidad de caída T+1 con reentrenamiento expansivo y retraso de publicación.",
        "regla_temporal": "Para decidir en t se entrena solo con filas cuya fecha_objetivo_t1 sea estrictamente anterior a t.",
        "reentrenamiento": f"Cada {REENTRENAR_CADA} observaciones del test reservado.",
        "seleccion_congelada": "Familia, parámetros, variables y umbral proceden exclusivamente de validación.",
        "criterios_aprobacion": [
            "Cobertura de predicciones de al menos 90% del test",
            "Al menos 20 alertas",
            "AUC de al menos 0.55",
            "Brier menor que el pronóstico base por prevalencia",
            "Precisión al menos 5 puntos porcentuales sobre la prevalencia",
            "Cobertura de caídas de al menos 20%",
        ],
        "advertencia": "Una aprobación estadística no elimina el riesgo de mercado ni constituye recomendación financiera.",
    }
    (processed / "walk_forward_manifiesto.json").write_text(
        json.dumps(manifiesto, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("Walk-forward del modelo de salida completado")
    print(resumen_df.to_string(index=False))


if __name__ == "__main__":
    main()
