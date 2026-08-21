from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

AFPS = ["Habitat", "Integra", "Prima", "Profuturo"]
FEATURES = [
    "retorno_medio_factores", "amplitud_factores_positivos",
    "amplitud_factores_negativos", "dispersion_factores", "min_factor",
    "max_factor", "factor_aceleracion", "factor_momentum_2",
    "factor_momentum_3", "factor_volatilidad_5", "momentum_sbs_3",
    "momentum_sbs_5", "vol_sbs_5", "vol_sbs_10", "aceleracion_sbs",
    "retroceso_sbs_max_5", "retroceso_sbs_max_10", "dias_desde_shock",
    "rebote_acumulado", "maximo_rebote",
    "retroceso_desde_maximo_rebote", "dias_positivos_desde_shock",
]


def leer_csv(ruta: Path) -> pd.DataFrame:
    ultimo: Exception | None = None
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return pd.read_csv(ruta, encoding=enc)
        except Exception as exc:
            ultimo = exc
    raise RuntimeError(f"No se pudo leer {ruta}: {ultimo}")


def escribir_csv(df: pd.DataFrame, ruta: Path) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(ruta, index=False, encoding="utf-8-sig", date_format="%Y-%m-%d")


def compuesto(s: pd.Series, ventana: int) -> pd.Series:
    r = pd.to_numeric(s, errors="coerce").replace([np.inf, -np.inf], np.nan)
    return (1.0 + r).rolling(ventana, min_periods=ventana).apply(np.prod, raw=True) - 1.0


def construir_episodios(g: pd.DataFrame, cfg: dict[str, Any]) -> tuple[pd.DataFrame, float]:
    g = g.sort_values("fecha_cuota").reset_index(drop=True).copy()
    r = pd.to_numeric(g["retorno_medio_factores"], errors="coerce")
    g["factor_aceleracion"] = r - r.shift(1)
    g["factor_momentum_2"] = compuesto(r, 2)
    g["factor_momentum_3"] = compuesto(r, 3)
    g["factor_volatilidad_5"] = r.rolling(5, min_periods=5).std()

    train = g[g["bloque_60_20_20"].eq("entrenamiento")]
    umbral_shock = float(
        train["retorno_medio_factores"].quantile(
            float(cfg["episodio"]["cuantil_shock_entrenamiento"])
        )
    )
    amplitud = float(cfg["episodio"]["amplitud_negativa_minima"])
    g["shock_mercado"] = (
        g["retorno_medio_factores"].le(umbral_shock)
        & g["amplitud_factores_negativos"].ge(amplitud)
    ).astype(int)

    max_dias = int(cfg["episodio"]["max_dias_desde_shock"])
    dias: list[float] = []
    acum: list[float] = []
    maximos: list[float] = []
    retrocesos: list[float] = []
    positivos: list[float] = []
    ultimo: int | None = None
    retorno_acum = maximo = 0.0
    n_positivos = 0

    for i, fila in g.iterrows():
        if int(fila["shock_mercado"]) == 1:
            ultimo = i
            retorno_acum = maximo = 0.0
            n_positivos = 0
            dias.append(0.0); acum.append(0.0); maximos.append(0.0)
            retrocesos.append(0.0); positivos.append(0.0)
            continue
        if ultimo is None or i - ultimo > max_dias:
            ultimo = None
            retorno_acum = maximo = 0.0
            n_positivos = 0
            dias.append(np.nan); acum.append(np.nan); maximos.append(np.nan)
            retrocesos.append(np.nan); positivos.append(np.nan)
            continue
        x = pd.to_numeric(fila["retorno_medio_factores"], errors="coerce")
        if pd.notna(x):
            retorno_acum = (1.0 + retorno_acum) * (1.0 + float(x)) - 1.0
            maximo = max(maximo, retorno_acum)
            n_positivos += int(float(x) > 0.0)
        dias.append(float(i - ultimo)); acum.append(retorno_acum)
        maximos.append(maximo); retrocesos.append(retorno_acum - maximo)
        positivos.append(float(n_positivos))

    g["dias_desde_shock"] = dias
    g["rebote_acumulado"] = acum
    g["maximo_rebote"] = maximos
    g["retroceso_desde_maximo_rebote"] = retrocesos
    g["dias_positivos_desde_shock"] = positivos
    g["en_episodio_rebote"] = (
        g["dias_desde_shock"].between(1, max_dias)
        & g["rebote_acumulado"].ge(float(cfg["episodio"]["rebote_acumulado_minimo"]))
        & g["dias_positivos_desde_shock"].ge(int(cfg["episodio"]["min_dias_positivos"]))
    )

    vol = pd.to_numeric(g["vol_sbs_10"], errors="coerce").combine_first(
        pd.to_numeric(g["vol_sbs_5"], errors="coerce")
    )
    g["umbral_caida_relevante"] = np.maximum(
        float(cfg["objetivo"]["caida_absoluta_minima"]),
        float(cfg["objetivo"]["multiplicador_volatilidad"]) * vol,
    )
    g["caida_relevante_t1"] = np.where(
        g["retorno_real_t1"].notna() & g["umbral_caida_relevante"].notna(),
        (g["retorno_real_t1"] <= -g["umbral_caida_relevante"]).astype(int),
        np.nan,
    )
    return g, umbral_shock


def ajustar(df: pd.DataFrame, c: float) -> Pipeline:
    if df["caida_relevante_t1"].nunique() < 2:
        raise RuntimeError("El ajuste necesita ambas clases")
    modelo = Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("scaler", StandardScaler()),
        ("modelo", LogisticRegression(
            C=float(c), class_weight="balanced", max_iter=1000,
            solver="liblinear", random_state=42,
        )),
    ])
    modelo.fit(df[FEATURES], df["caida_relevante_t1"].astype(int))
    return modelo


def metricas(df: pd.DataFrame, prob: np.ndarray, umbral: float) -> dict[str, float]:
    y = df["caida_relevante_t1"].astype(int).to_numpy()
    p = np.asarray(prob, dtype=float)
    alerta = p >= float(umbral)
    tp = int(np.sum(alerta & (y == 1))); fp = int(np.sum(alerta & (y == 0)))
    fn = int(np.sum((~alerta) & (y == 1))); tn = int(np.sum((~alerta) & (y == 0)))
    precision = tp / (tp + fp) if tp + fp else np.nan
    recall = tp / (tp + fn) if tp + fn else np.nan
    falsas = fp / (fp + tn) if fp + tn else np.nan
    auc = float(roc_auc_score(y, p)) if len(np.unique(y)) == 2 else np.nan
    ret = pd.to_numeric(df["retorno_real_t1"], errors="coerce").to_numpy(dtype=float)
    evitada = float(np.sum(-ret[alerta & (ret < 0.0)]))
    sacrificada = float(np.sum(ret[alerta & (ret > 0.0)]))
    neta = evitada - sacrificada
    return {
        "n": len(y), "prevalencia_pct": float(y.mean() * 100.0),
        "auc": auc, "brier": float(brier_score_loss(y, p)),
        "n_alertas": int(alerta.sum()),
        "precision_alerta_pct": precision * 100.0 if np.isfinite(precision) else np.nan,
        "cobertura_caidas_pct": recall * 100.0 if np.isfinite(recall) else np.nan,
        "falsas_alarmas_pct": falsas * 100.0 if np.isfinite(falsas) else np.nan,
        "perdida_evitada_suma_pct": evitada * 100.0,
        "ganancia_sacrificada_suma_pct": sacrificada * 100.0,
        "proteccion_neta_suma_pct": neta * 100.0,
        "proteccion_neta_media_por_episodio_pct": neta / max(len(y), 1) * 100.0,
    }


def puntaje(m: dict[str, float]) -> float:
    prev = m["prevalencia_pct"] / 100.0
    prec = 0.0 if pd.isna(m["precision_alerta_pct"]) else m["precision_alerta_pct"] / 100.0
    rec = 0.0 if pd.isna(m["cobertura_caidas_pct"]) else m["cobertura_caidas_pct"] / 100.0
    falsas = 0.0 if pd.isna(m["falsas_alarmas_pct"]) else m["falsas_alarmas_pct"] / 100.0
    neta = m["proteccion_neta_media_por_episodio_pct"] / 100.0
    return float(0.45 * (prec - prev) + 0.20 * rec - 0.20 * falsas + 35.0 * neta)


def seleccionar(train: pd.DataFrame, valid: pd.DataFrame, cfg: dict[str, Any]) -> tuple[float, float, pd.DataFrame]:
    filas: list[dict[str, Any]] = []
    for c in (0.05, 0.2, 1.0):
        modelo = ajustar(train, c)
        prob = modelo.predict_proba(valid[FEATURES])[:, 1]
        for u in cfg["seleccion"]["umbrales_probabilidad"]:
            m = metricas(valid, prob, float(u))
            filas.append({"C": c, "umbral_probabilidad": float(u), **m, "puntaje": puntaje(m)})
    tabla = pd.DataFrame(filas)
    elegibles = tabla[
        tabla["n_alertas"].ge(int(cfg["seleccion"]["min_alertas_validacion"]))
    ]
    if elegibles.empty:
        elegibles = tabla
    ganador = elegibles.sort_values(
        ["puntaje", "proteccion_neta_suma_pct", "precision_alerta_pct", "auc"],
        ascending=[False, False, False, False], na_position="last",
    ).iloc[0]
    return float(ganador["C"]), float(ganador["umbral_probabilidad"]), tabla


def walk_forward(eventos: pd.DataFrame, c: float, umbral: float, cfg: dict[str, Any]) -> pd.DataFrame:
    test = eventos[eventos["bloque_60_20_20"].eq("test_reservado")].sort_values("fecha_cuota")
    cada = int(cfg["walk_forward"]["reentrenar_cada_observaciones"])
    minimo = int(cfg["walk_forward"]["minimo_eventos_historial"])
    modelo: Pipeline | None = None
    desde = cada
    filas: list[dict[str, Any]] = []
    fechas_obj = pd.to_datetime(eventos["fecha_objetivo_t1"], errors="coerce").dt.normalize()

    for _, fila in test.iterrows():
        fecha = pd.Timestamp(fila["fecha_cuota"]).normalize()
        hist = eventos[fechas_obj < fecha].dropna(subset=["caida_relevante_t1"])
        if len(hist) < minimo or hist["caida_relevante_t1"].nunique() < 2:
            continue
        if modelo is None or desde >= cada:
            modelo = ajustar(hist, c)
            desde = 0
        p = float(modelo.predict_proba(pd.DataFrame([fila])[FEATURES])[:, 1][0])
        filas.append({
            "afp": fila["afp"], "fecha_cuota": fila["fecha_cuota"],
            "fecha_objetivo_t1": fila["fecha_objetivo_t1"],
            "retorno_real_t1": fila["retorno_real_t1"],
            "umbral_caida_relevante": fila["umbral_caida_relevante"],
            "caida_relevante_t1": fila["caida_relevante_t1"],
            "probabilidad_caida_relevante_t1": p,
            "umbral_probabilidad": umbral, "alerta_salida": p >= umbral,
            "n_historial_disponible": len(hist),
        })
        desde += 1
    return pd.DataFrame(filas)


def evaluar(afp: str, base: pd.DataFrame, cfg: dict[str, Any]):
    g = base[base["afp"].astype(str).eq(afp)].copy()
    g["fecha_cuota"] = pd.to_datetime(g["fecha_cuota"], errors="coerce").dt.normalize()
    g["fecha_objetivo_t1"] = pd.to_datetime(g["fecha_objetivo_t1"], errors="coerce").dt.normalize()
    g, umbral_shock = construir_episodios(g, cfg)
    eventos = g[g["en_episodio_rebote"] & g["caida_relevante_t1"].notna()].copy()
    train = eventos[eventos["bloque_60_20_20"].eq("entrenamiento")]
    valid = eventos[eventos["bloque_60_20_20"].eq("validacion")]
    test = eventos[eventos["bloque_60_20_20"].eq("test_reservado")]
    if min(len(train), len(valid), len(test)) < 100:
        raise RuntimeError(f"{afp}: episodios insuficientes")

    c, umbral, tabla = seleccionar(train, valid, cfg)
    tabla.insert(0, "afp", afp)
    estatico = ajustar(pd.concat([train, valid]), c)
    met_test = metricas(test, estatico.predict_proba(test[FEATURES])[:, 1], umbral)
    pred = walk_forward(eventos, c, umbral, cfg)
    met_walk = metricas(pred, pred["probabilidad_caida_relevante_t1"].to_numpy(), umbral)
    base_brier = float(
        ((pred["caida_relevante_t1"] - pred["caida_relevante_t1"].mean()) ** 2).mean()
    )
    criterios = {
        "cobertura_predicciones_min_90pct": len(pred) >= 0.90 * len(test),
        "alertas_min_20": met_walk["n_alertas"] >= 20,
        "auc_min_0_55": pd.notna(met_walk["auc"]) and met_walk["auc"] >= 0.55,
        "brier_mejor_que_base": met_walk["brier"] < base_brier,
        "precision_supera_prevalencia_8pp": (
            pd.notna(met_walk["precision_alerta_pct"])
            and met_walk["precision_alerta_pct"] >= met_walk["prevalencia_pct"] + 8.0
        ),
        "cobertura_caidas_min_15pct": (
            pd.notna(met_walk["cobertura_caidas_pct"])
            and met_walk["cobertura_caidas_pct"] >= 15.0
        ),
        "proteccion_neta_positiva": met_walk["proteccion_neta_suma_pct"] > 0.0,
    }
    resumen = {
        "afp": afp, "modelo_elegido": f"logistica_c{c:g}", "familia": "logistica",
        "umbral_probabilidad": umbral, "umbral_shock_factores": umbral_shock,
        "n_eventos_train": len(train), "n_eventos_valid": len(valid),
        "n_eventos_test": len(test), **{f"test_{k}": v for k, v in met_test.items()},
        **{f"walk_{k}": v for k, v in met_walk.items()},
        "walk_brier_base_prevalencia": base_brier,
        "criterios": json.dumps(criterios, ensure_ascii=False, sort_keys=True),
        "estado": "APROBADO_EXPERIMENTAL_V2" if all(criterios.values()) else "NO_APROBADO_V2",
    }
    return resumen, tabla, pred, criterios


def main() -> None:
    raiz = Path(__file__).resolve().parents[2]
    salida = raiz / "data" / "processed" / "modelo_salida"
    cfg = json.loads((raiz / "config" / "modelo_salida_v2.json").read_text(encoding="utf-8"))
    base = leer_csv(salida / "base_modelo_salida.csv")
    resumenes, tablas, predicciones, criterios = [], [], [], {}
    for afp in AFPS:
        resumen, tabla, pred, criterio = evaluar(afp, base, cfg)
        resumenes.append(resumen); tablas.append(tabla); predicciones.append(pred)
        criterios[afp] = criterio
    resumen = pd.DataFrame(resumenes)
    escribir_csv(resumen, salida / "v2_resumen.csv")
    escribir_csv(pd.concat(tablas, ignore_index=True), salida / "v2_candidatos_validacion.csv")
    escribir_csv(pd.concat(predicciones, ignore_index=True), salida / "v2_predicciones_walk_forward.csv")
    (salida / "v2_manifiesto.json").write_text(json.dumps({
        "version": "modelo_salida_v2_rebote",
        "regla_temporal": "Cada ajuste usa solo objetivos conocidos antes de la fecha de decision.",
        "features": FEATURES, "configuracion": cfg, "criterios": criterios,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    lineas = [
        "# Resultado modelo de salida V2: agotamiento de rebote", "",
        "| AFP | AUC walk | Precision | Cobertura de caidas | Proteccion neta | Estado |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for _, r in resumen.iterrows():
        lineas.append(
            f"| {r['afp']} | {r['walk_auc']:.3f} | {r['walk_precision_alerta_pct']:.2f}% | "
            f"{r['walk_cobertura_caidas_pct']:.2f}% | {r['walk_proteccion_neta_suma_pct']:+.2f}% | "
            f"{r['estado']} |"
        )
    lineas += ["", "La proteccion neta es perdida evitada menos ganancia sacrificada en una simulacion T+1.",
               "El modelo permanece experimental y no constituye una recomendacion financiera."]
    (raiz / "docs" / "modelo_salida_resultados_v2.md").write_text(
        "\n".join(lineas), encoding="utf-8"
    )
    print(resumen.to_string(index=False))


if __name__ == "__main__":
    main()
