from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


AFPS = ["Habitat", "Integra", "Prima", "Profuturo"]
MIN_COBERTURA_COLUMNA = 0.60
MIN_FILAS_CALIBRACION = 30

COLUMNAS_PROHIBIDAS = {
    "afp",
    "fecha_cuota",
    "fecha_objetivo_t1",
    "cuota_sbs",
    "retorno_cuota",
    "retorno_real_t1",
    "caida_t1",
    "bloque_60_20_20",
}


@dataclass
class ModeloCalibrado:
    modelo: Pipeline
    calibrador: LogisticRegression | None
    columnas: list[str]

    def predict_proba(self, df: pd.DataFrame) -> np.ndarray:
        raw = self.modelo.predict_proba(df[self.columnas])[:, 1]
        if self.calibrador is None:
            return np.clip(raw, 0.0, 1.0)
        calibrada = self.calibrador.predict_proba(raw.reshape(-1, 1))[:, 1]
        return np.clip(calibrada, 0.0, 1.0)


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


def leer_config(ruta: Path) -> dict[str, Any]:
    if not ruta.exists():
        raise FileNotFoundError(f"No existe la configuracion: {ruta}")
    return json.loads(ruta.read_text(encoding="utf-8"))


def columnas_utilizables(train: pd.DataFrame) -> list[str]:
    columnas: list[str] = []
    for columna in train.columns:
        if columna in COLUMNAS_PROHIBIDAS:
            continue
        serie = pd.to_numeric(train[columna], errors="coerce")
        if serie.notna().mean() < MIN_COBERTURA_COLUMNA:
            continue
        if serie.dropna().nunique() < 2:
            continue
        columnas.append(columna)
    if not columnas:
        raise RuntimeError("No quedaron variables utilizables para entrenar")
    return columnas


def candidatos_modelo() -> list[dict[str, Any]]:
    candidatos: list[dict[str, Any]] = []
    for c in (0.1, 1.0, 10.0):
        candidatos.append(
            {
                "codigo": f"logistica_c{c:g}",
                "familia": "regresion_logistica",
                "parametros": {"C": c},
            }
        )
    for profundidad in (2, 3):
        for tasa in (0.03, 0.05):
            candidatos.append(
                {
                    "codigo": f"gradient_d{profundidad}_lr{tasa:g}",
                    "familia": "gradient_boosting",
                    "parametros": {
                        "max_depth": profundidad,
                        "learning_rate": tasa,
                        "n_estimators": 160,
                    },
                }
            )
    return candidatos


def construir_pipeline(familia: str, parametros: dict[str, Any]) -> Pipeline:
    if familia == "regresion_logistica":
        return Pipeline(
            [
                ("imputer", SimpleImputer(strategy="median")),
                ("scaler", StandardScaler()),
                (
                    "modelo",
                    LogisticRegression(
                        C=float(parametros["C"]),
                        class_weight="balanced",
                        max_iter=3000,
                        random_state=42,
                    ),
                ),
            ]
        )

    if familia == "gradient_boosting":
        return Pipeline(
            [
                ("imputer", SimpleImputer(strategy="median")),
                (
                    "modelo",
                    GradientBoostingClassifier(
                        n_estimators=int(parametros["n_estimators"]),
                        learning_rate=float(parametros["learning_rate"]),
                        max_depth=int(parametros["max_depth"]),
                        random_state=42,
                    ),
                ),
            ]
        )

    raise ValueError(f"Familia no reconocida: {familia}")


def ajustar_calibrado(
    datos: pd.DataFrame,
    columnas: list[str],
    familia: str,
    parametros: dict[str, Any],
) -> ModeloCalibrado:
    datos = datos.sort_values("fecha_cuota").reset_index(drop=True)
    corte = int(math.floor(len(datos) * 0.80))
    if corte < 100 or len(datos) - corte < MIN_FILAS_CALIBRACION:
        raise RuntimeError("Muestra insuficiente para ajuste y calibracion interna")

    ajuste = datos.iloc[:corte].copy()
    calibracion = datos.iloc[corte:].copy()
    modelo = construir_pipeline(familia, parametros)
    modelo.fit(ajuste[columnas], ajuste["caida_t1"].astype(int))

    raw = modelo.predict_proba(calibracion[columnas])[:, 1]
    y_cal = calibracion["caida_t1"].astype(int).to_numpy()
    calibrador: LogisticRegression | None = None
    if len(np.unique(y_cal)) == 2 and len(y_cal) >= MIN_FILAS_CALIBRACION:
        calibrador = LogisticRegression(C=1e6, max_iter=2000, random_state=42)
        calibrador.fit(raw.reshape(-1, 1), y_cal)

    return ModeloCalibrado(modelo=modelo, calibrador=calibrador, columnas=columnas)


def metricas_probabilidad(y: np.ndarray, prob: np.ndarray) -> dict[str, float]:
    y = np.asarray(y, dtype=int)
    prob = np.asarray(prob, dtype=float)
    auc = np.nan
    if len(np.unique(y)) == 2:
        auc = float(roc_auc_score(y, prob))
    return {
        "brier": float(brier_score_loss(y, prob)),
        "auc": auc,
        "prevalencia_caida_pct": float(y.mean() * 100.0),
    }


def metricas_alerta(y: np.ndarray, prob: np.ndarray, umbral: float) -> dict[str, float]:
    y = np.asarray(y, dtype=int)
    alerta = np.asarray(prob, dtype=float) >= float(umbral)
    tp = int(np.sum(alerta & (y == 1)))
    fp = int(np.sum(alerta & (y == 0)))
    fn = int(np.sum((~alerta) & (y == 1)))
    tn = int(np.sum((~alerta) & (y == 0)))

    precision = tp / (tp + fp) if tp + fp else np.nan
    recall = tp / (tp + fn) if tp + fn else np.nan
    falsas = fp / (fp + tn) if fp + tn else np.nan
    cobertura = float(alerta.mean()) if len(alerta) else np.nan

    p = 0.0 if np.isnan(precision) else float(precision)
    r = 0.0 if np.isnan(recall) else float(recall)
    f = 0.0 if np.isnan(falsas) else float(falsas)
    puntaje = 0.55 * r + 0.35 * p - 0.10 * f

    return {
        "n": int(len(y)),
        "n_alertas": int(alerta.sum()),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision_alerta_pct": precision * 100.0 if not np.isnan(precision) else np.nan,
        "cobertura_caidas_pct": recall * 100.0 if not np.isnan(recall) else np.nan,
        "falsas_alarmas_pct": falsas * 100.0 if not np.isnan(falsas) else np.nan,
        "cobertura_alertas_pct": cobertura * 100.0 if not np.isnan(cobertura) else np.nan,
        "puntaje_control_riesgo": float(puntaje),
    }


def evidencia_riesgo(df: pd.DataFrame) -> pd.Series:
    evidencia = pd.Series(0, index=df.index, dtype=int)
    condiciones = [
        ("aceleracion_nowcast", lambda x: x < 0),
        ("aceleracion_sbs", lambda x: x < 0),
        ("retorno_medio_factores", lambda x: x < 0),
        ("amplitud_factores_negativos", lambda x: x >= 0.55),
        ("retroceso_sbs_max_5", lambda x: x < 0),
    ]
    for columna, regla in condiciones:
        if columna not in df.columns:
            continue
        serie = pd.to_numeric(df[columna], errors="coerce")
        evidencia = evidencia + regla(serie).fillna(False).astype(int)
    return evidencia


def clasificar_estado(prob: pd.Series, umbral: float, evidencia: pd.Series) -> pd.Series:
    continuidad = max(0.35, float(umbral) - 0.20)
    estado = pd.Series("SIN_SENAL", index=prob.index, dtype=object)
    estado.loc[(prob <= continuidad) & (evidencia == 0)] = "CONTINUIDAD"
    estado.loc[(prob >= umbral) | (evidencia >= 2)] = "VIGILANCIA"
    estado.loc[(prob >= umbral) & (evidencia >= 2)] = "RIESGO_ALTO"
    return estado


def evaluar_afp(
    afp: str,
    base: pd.DataFrame,
    config: dict[str, Any],
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    g = base[base["afp"].astype(str).eq(afp)].copy()
    g["fecha_cuota"] = pd.to_datetime(g["fecha_cuota"], errors="coerce").dt.normalize()
    g["fecha_objetivo_t1"] = pd.to_datetime(g["fecha_objetivo_t1"], errors="coerce").dt.normalize()
    g["caida_t1"] = pd.to_numeric(g["caida_t1"], errors="coerce")
    g = g.dropna(subset=["fecha_cuota", "caida_t1"]).sort_values("fecha_cuota")

    train = g[g["bloque_60_20_20"].eq("entrenamiento")].copy()
    valid = g[g["bloque_60_20_20"].eq("validacion")].copy()
    test = g[g["bloque_60_20_20"].eq("test_reservado")].copy()
    columnas = columnas_utilizables(train)

    umbrales = [float(x) for x in config["umbrales_validacion"]["probabilidad_riesgo"]]
    min_alertas_valid = int(config["umbrales_validacion"]["min_alertas_validacion"])
    filas_candidatos: list[dict[str, Any]] = []

    for candidato in candidatos_modelo():
        ajustado = ajustar_calibrado(
            train,
            columnas,
            candidato["familia"],
            candidato["parametros"],
        )
        prob_valid = ajustado.predict_proba(valid)
        met_prob = metricas_probabilidad(valid["caida_t1"].astype(int).to_numpy(), prob_valid)
        for umbral in umbrales:
            met_alerta = metricas_alerta(valid["caida_t1"].astype(int).to_numpy(), prob_valid, umbral)
            filas_candidatos.append(
                {
                    "afp": afp,
                    "modelo_codigo": candidato["codigo"],
                    "familia": candidato["familia"],
                    "parametros": json.dumps(candidato["parametros"], sort_keys=True),
                    "umbral": umbral,
                    **met_prob,
                    **met_alerta,
                }
            )

    tabla = pd.DataFrame(filas_candidatos)
    elegibles = tabla[tabla["n_alertas"].ge(min_alertas_valid)].copy()
    if elegibles.empty:
        elegibles = tabla.copy()
    elegibles = elegibles.sort_values(
        ["puntaje_control_riesgo", "brier", "cobertura_caidas_pct", "precision_alerta_pct"],
        ascending=[False, True, False, False],
        na_position="last",
    )
    ganador = elegibles.iloc[0]
    candidato = next(x for x in candidatos_modelo() if x["codigo"] == ganador["modelo_codigo"])
    umbral = float(ganador["umbral"])

    train_valid = pd.concat([train, valid], ignore_index=True).sort_values("fecha_cuota")
    modelo_final = ajustar_calibrado(
        train_valid,
        columnas,
        candidato["familia"],
        candidato["parametros"],
    )
    prob_test = modelo_final.predict_proba(test)
    met_prob_test = metricas_probabilidad(test["caida_t1"].astype(int).to_numpy(), prob_test)
    met_alerta_test = metricas_alerta(test["caida_t1"].astype(int).to_numpy(), prob_test, umbral)

    detalle = test[
        [
            "afp",
            "fecha_cuota",
            "fecha_objetivo_t1",
            "retorno_real_t1",
            "caida_t1",
        ]
    ].copy()
    detalle["probabilidad_caida_t1"] = prob_test
    detalle["umbral_elegido"] = umbral
    detalle["alerta_probabilistica"] = detalle["probabilidad_caida_t1"] >= umbral
    detalle["evidencias_adicionales"] = evidencia_riesgo(test).to_numpy()
    detalle["estado_salida"] = clasificar_estado(
        detalle["probabilidad_caida_t1"],
        umbral,
        detalle["evidencias_adicionales"],
    )
    detalle["acierto_alerta"] = np.where(
        detalle["alerta_probabilistica"],
        detalle["caida_t1"].astype(int).eq(1),
        np.nan,
    )

    riesgo_alto = detalle["estado_salida"].eq("RIESGO_ALTO")
    met_riesgo_alto = metricas_alerta(
        detalle["caida_t1"].astype(int).to_numpy(),
        riesgo_alto.astype(float).to_numpy(),
        0.5,
    )

    resumen = {
        "afp": afp,
        "modelo_elegido": candidato["codigo"],
        "familia": candidato["familia"],
        "umbral_elegido": umbral,
        "n_variables": len(columnas),
        "n_train": len(train),
        "n_valid": len(valid),
        "n_test": len(test),
        "valid_puntaje_control_riesgo": float(ganador["puntaje_control_riesgo"]),
        "valid_precision_alerta_pct": ganador["precision_alerta_pct"],
        "valid_cobertura_caidas_pct": ganador["cobertura_caidas_pct"],
        "valid_falsas_alarmas_pct": ganador["falsas_alarmas_pct"],
        "test_brier": met_prob_test["brier"],
        "test_auc": met_prob_test["auc"],
        "test_precision_alerta_pct": met_alerta_test["precision_alerta_pct"],
        "test_cobertura_caidas_pct": met_alerta_test["cobertura_caidas_pct"],
        "test_falsas_alarmas_pct": met_alerta_test["falsas_alarmas_pct"],
        "test_n_alertas": met_alerta_test["n_alertas"],
        "test_precision_riesgo_alto_pct": met_riesgo_alto["precision_alerta_pct"],
        "test_cobertura_caidas_riesgo_alto_pct": met_riesgo_alto["cobertura_caidas_pct"],
        "test_n_riesgo_alto": met_riesgo_alto["n_alertas"],
        "estado": "EXPERIMENTAL_PENDIENTE_WALK_FORWARD",
    }
    seleccion = {
        "afp": afp,
        "modelo_codigo": candidato["codigo"],
        "familia": candidato["familia"],
        "parametros": candidato["parametros"],
        "umbral_probabilidad": umbral,
        "columnas": columnas,
        "regla_seleccion": "Maximiza control de riesgo en validacion; desempata por menor Brier.",
    }
    return resumen, tabla, detalle, seleccion


def main() -> None:
    raiz = Path(__file__).resolve().parents[2]
    processed = raiz / "data" / "processed" / "modelo_salida"
    config = leer_config(raiz / "config" / "modelo_salida.json")
    base = leer_csv(processed / "base_modelo_salida.csv")

    resumenes: list[dict[str, Any]] = []
    candidatos: list[pd.DataFrame] = []
    detalles: list[pd.DataFrame] = []
    selecciones: dict[str, Any] = {}

    for afp in AFPS:
        resumen, tabla, detalle, seleccion = evaluar_afp(afp, base, config)
        resumenes.append(resumen)
        candidatos.append(tabla)
        detalles.append(detalle)
        selecciones[afp] = seleccion

    resumen_df = pd.DataFrame(resumenes)
    candidatos_df = pd.concat(candidatos, ignore_index=True)
    detalle_df = pd.concat(detalles, ignore_index=True)

    escribir_csv(resumen_df, processed / "resumen_modelos.csv")
    escribir_csv(candidatos_df, processed / "candidatos_validacion.csv")
    escribir_csv(detalle_df, processed / "predicciones_test_reservado.csv")
    (processed / "seleccion_modelos.json").write_text(
        json.dumps(selecciones, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("Modelos de salida 60/20/20 evaluados")
    print(resumen_df.to_string(index=False))


if __name__ == "__main__":
    main()
