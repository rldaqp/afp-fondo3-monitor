from __future__ import annotations

import importlib.util
import json
import sys
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

FEATURES = [
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
    "dias_desde_shock",
    "rebote_desde_minimo_factor",
    "fraccion_recuperada_factor",
    "velocidad_rebote_factor",
    "cambio_velocidad_rebote_factor",
    "dias_desde_minimo_factor",
    "rebote_desde_minimo_sbs",
    "fraccion_recuperada_sbs",
    "velocidad_rebote_sbs",
    "cambio_velocidad_rebote_sbs",
    "dias_desde_minimo_sbs",
    "retroceso_desde_maximo_factor",
    "retroceso_desde_maximo_sbs",
]

ZONE_COLUMNS = [
    "zona_etapa_recuperacion_factor",
    "zona_dias_rebote",
    "zona_impulso_factor",
    "zona_retroceso_factor",
    "zona_etapa_impulso",
    "zona_dias_impulso",
]


def cargar_v2(raiz: Path):
    ruta = raiz / "src" / "modelo_salida" / "04_modelo_rebote_salida_v2.py"
    spec = importlib.util.spec_from_file_location("modelo_salida_v2_para_v4", ruta)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"No se pudo cargar {ruta}")
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = modulo
    spec.loader.exec_module(modulo)
    return modulo


def limpiar_numericos(df: pd.DataFrame, columnas: list[str]) -> pd.DataFrame:
    out = df.copy()
    for col in columnas:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce").replace(
                [np.inf, -np.inf], np.nan
            )
    return out


def agregar_rebote_relativo(g: pd.DataFrame) -> pd.DataFrame:
    g = g.sort_values("fecha_cuota").reset_index(drop=True).copy()

    acum_factor: list[float] = []
    minimo_factor: list[float] = []
    rebote_factor: list[float] = []
    recuperacion_factor: list[float] = []
    dias_min_factor: list[float] = []
    velocidad_factor: list[float] = []
    retroceso_factor: list[float] = []

    minimo_sbs: list[float] = []
    rebote_sbs: list[float] = []
    recuperacion_sbs: list[float] = []
    dias_min_sbs: list[float] = []
    velocidad_sbs: list[float] = []
    retroceso_sbs: list[float] = []

    activo = False
    cum = trough = peak = 0.0
    trough_idx_factor = 0
    anchor_sbs = trough_sbs = peak_sbs = np.nan
    trough_idx_sbs = 0

    max_dias = int(pd.to_numeric(g["dias_desde_shock"], errors="coerce").max(skipna=True) or 10)

    for i, fila in g.iterrows():
        shock = int(pd.to_numeric(fila.get("shock_mercado"), errors="coerce") or 0)
        ret_factor = pd.to_numeric(fila.get("retorno_medio_factores"), errors="coerce")
        cuota = pd.to_numeric(fila.get("cuota_sbs_conocida"), errors="coerce")

        if shock == 1:
            activo = True
            cum = float(ret_factor) if pd.notna(ret_factor) else 0.0
            trough = cum
            peak = cum
            trough_idx_factor = i
            anchor_sbs = float(cuota) if pd.notna(cuota) else np.nan
            trough_sbs = anchor_sbs
            peak_sbs = anchor_sbs
            trough_idx_sbs = i
        elif activo:
            dias = pd.to_numeric(fila.get("dias_desde_shock"), errors="coerce")
            if pd.isna(dias) or float(dias) > max_dias:
                activo = False
            elif pd.notna(ret_factor):
                cum = (1.0 + cum) * (1.0 + float(ret_factor)) - 1.0
                if cum < trough:
                    trough = cum
                    trough_idx_factor = i
                peak = max(peak, cum)
            if pd.notna(cuota):
                cuota_f = float(cuota)
                if pd.isna(trough_sbs) or cuota_f < trough_sbs:
                    trough_sbs = cuota_f
                    trough_idx_sbs = i
                if pd.isna(peak_sbs):
                    peak_sbs = cuota_f
                else:
                    peak_sbs = max(peak_sbs, cuota_f)

        if not activo:
            acum_factor.append(np.nan)
            minimo_factor.append(np.nan)
            rebote_factor.append(np.nan)
            recuperacion_factor.append(np.nan)
            dias_min_factor.append(np.nan)
            velocidad_factor.append(np.nan)
            retroceso_factor.append(np.nan)
            minimo_sbs.append(np.nan)
            rebote_sbs.append(np.nan)
            recuperacion_sbs.append(np.nan)
            dias_min_sbs.append(np.nan)
            velocidad_sbs.append(np.nan)
            retroceso_sbs.append(np.nan)
            continue

        reb_f = (1.0 + cum) / (1.0 + trough) - 1.0 if trough > -0.999 else np.nan
        perdida_f = abs(trough) if trough < 0.0 else np.nan
        rec_f = reb_f / perdida_f if pd.notna(reb_f) and pd.notna(perdida_f) and perdida_f > 0 else np.nan
        dmin_f = float(i - trough_idx_factor)
        vel_f = reb_f / max(dmin_f, 1.0) if pd.notna(reb_f) else np.nan
        retro_f = (1.0 + cum) / (1.0 + peak) - 1.0 if peak > -0.999 else np.nan

        if pd.notna(cuota) and pd.notna(trough_sbs) and trough_sbs > 0:
            cuota_f = float(cuota)
            reb_s = cuota_f / trough_sbs - 1.0
            perdida_s = anchor_sbs / trough_sbs - 1.0 if pd.notna(anchor_sbs) and anchor_sbs > 0 else np.nan
            rec_s = reb_s / perdida_s if pd.notna(perdida_s) and perdida_s > 0 else np.nan
            dmin_s = float(i - trough_idx_sbs)
            vel_s = reb_s / max(dmin_s, 1.0)
            retro_s = cuota_f / peak_sbs - 1.0 if pd.notna(peak_sbs) and peak_sbs > 0 else np.nan
        else:
            reb_s = rec_s = dmin_s = vel_s = retro_s = np.nan

        acum_factor.append(cum)
        minimo_factor.append(trough)
        rebote_factor.append(reb_f)
        recuperacion_factor.append(rec_f)
        dias_min_factor.append(dmin_f)
        velocidad_factor.append(vel_f)
        retroceso_factor.append(retro_f)
        minimo_sbs.append(trough_sbs)
        rebote_sbs.append(reb_s)
        recuperacion_sbs.append(rec_s)
        dias_min_sbs.append(dmin_s)
        velocidad_sbs.append(vel_s)
        retroceso_sbs.append(retro_s)

    g["nivel_acumulado_factor_desde_shock"] = acum_factor
    g["minimo_factor_desde_shock"] = minimo_factor
    g["rebote_desde_minimo_factor"] = rebote_factor
    g["fraccion_recuperada_factor"] = recuperacion_factor
    g["dias_desde_minimo_factor"] = dias_min_factor
    g["velocidad_rebote_factor"] = velocidad_factor
    g["retroceso_desde_maximo_factor"] = retroceso_factor
    g["minimo_sbs_conocido_desde_shock"] = minimo_sbs
    g["rebote_desde_minimo_sbs"] = rebote_sbs
    g["fraccion_recuperada_sbs"] = recuperacion_sbs
    g["dias_desde_minimo_sbs"] = dias_min_sbs
    g["velocidad_rebote_sbs"] = velocidad_sbs
    g["retroceso_desde_maximo_sbs"] = retroceso_sbs

    episodio = g["shock_mercado"].fillna(0).astype(int).cumsum()
    g["cambio_velocidad_rebote_factor"] = g.groupby(episodio)[
        "velocidad_rebote_factor"
    ].diff()
    g["cambio_velocidad_rebote_sbs"] = g.groupby(episodio)[
        "velocidad_rebote_sbs"
    ].diff()

    g["zona_etapa_recuperacion_factor"] = pd.cut(
        g["fraccion_recuperada_factor"],
        bins=[-np.inf, 0.25, 0.50, 0.75, 1.00, np.inf],
        labels=["menos_25", "25_50", "50_75", "75_100", "mas_100"],
    ).astype("string")
    g["zona_dias_rebote"] = pd.cut(
        g["dias_desde_shock"],
        bins=[0, 2, 4, 7, np.inf],
        labels=["dias_1_2", "dias_3_4", "dias_5_7", "dias_8_10"],
    ).astype("string")
    g["zona_impulso_factor"] = np.select(
        [
            g["cambio_velocidad_rebote_factor"].gt(0.0002),
            g["cambio_velocidad_rebote_factor"].lt(-0.0002),
        ],
        ["acelerando", "desacelerando"],
        default="estable",
    )
    g["zona_retroceso_factor"] = pd.cut(
        g["retroceso_desde_maximo_factor"],
        bins=[-np.inf, -0.005, -0.002, -0.0005, np.inf],
        labels=["retroceso_fuerte", "retroceso_medio", "retroceso_leve", "sin_retroceso"],
    ).astype("string")
    g["zona_etapa_impulso"] = (
        g["zona_etapa_recuperacion_factor"].fillna("sin_etapa")
        + "|"
        + pd.Series(g["zona_impulso_factor"], index=g.index).fillna("sin_impulso")
    )
    g["zona_dias_impulso"] = (
        g["zona_dias_rebote"].fillna("sin_dias")
        + "|"
        + pd.Series(g["zona_impulso_factor"], index=g.index).fillna("sin_impulso")
    )
    return limpiar_numericos(g, FEATURES)


def construir_modelos(cfg: dict[str, Any]) -> list[tuple[str, Pipeline]]:
    modelos: list[tuple[str, Pipeline]] = []
    for c in cfg["modelos"]["logistica_C"]:
        for balanceado in (False, True):
            modelos.append((
                f"logistica_C{c}_{'bal' if balanceado else 'normal'}",
                Pipeline([
                    ("imputer", SimpleImputer(strategy="median")),
                    ("scaler", StandardScaler()),
                    ("modelo", LogisticRegression(
                        C=float(c),
                        class_weight="balanced" if balanceado else None,
                        max_iter=1500,
                        solver="liblinear",
                        random_state=42,
                    )),
                ]),
            ))
    for pars in cfg["modelos"]["gradient_boosting"]:
        codigo = f"gb_d{pars['max_depth']}_n{pars['n_estimators']}"
        modelos.append((
            codigo,
            Pipeline([
                ("imputer", SimpleImputer(strategy="median")),
                ("modelo", GradientBoostingClassifier(
                    n_estimators=int(pars["n_estimators"]),
                    learning_rate=float(pars["learning_rate"]),
                    max_depth=int(pars["max_depth"]),
                    random_state=42,
                )),
            ]),
        ))
    return modelos


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
    prevalencia = float(y.mean())
    return {
        "n": int(len(y)),
        "prevalencia_pct": prevalencia * 100.0,
        "auc": auc,
        "brier": float(brier_score_loss(y, p)),
        "n_alertas": int(a.sum()),
        "cobertura_dias_pct": float(a.mean() * 100.0),
        "precision_alerta_pct": precision * 100.0 if np.isfinite(precision) else np.nan,
        "mejora_precision_pp": (precision - prevalencia) * 100.0 if np.isfinite(precision) else np.nan,
        "cobertura_caidas_pct": recall * 100.0 if np.isfinite(recall) else np.nan,
        "falsas_alarmas_pct": falsas * 100.0 if np.isfinite(falsas) else np.nan,
        "perdida_evitada_suma_pct": evitada * 100.0,
        "ganancia_sacrificada_suma_pct": sacrificada * 100.0,
        "proteccion_neta_suma_pct": (evitada - sacrificada) * 100.0,
    }


def tabla_zonas(valid: pd.DataFrame, cfg: dict[str, Any]) -> pd.DataFrame:
    filas: list[dict[str, Any]] = []
    base = float(valid["caida_relevante_t1"].mean())
    for col in ZONE_COLUMNS:
        for valor, grupo in valid.groupby(col, dropna=False):
            if pd.isna(valor):
                continue
            alerta = np.ones(len(grupo), dtype=bool)
            m = metricas(grupo, np.full(len(grupo), base), alerta)
            filas.append({
                "zona_columna": col,
                "zona_valor": str(valor),
                **m,
            })
    tabla = pd.DataFrame(filas)
    if tabla.empty:
        return tabla
    tabla["zona_elegible"] = (
        tabla["n"].ge(int(cfg["seleccion_selectiva"]["min_eventos_zona"]))
        & tabla["mejora_precision_pp"].ge(
            float(cfg["seleccion_selectiva"]["mejora_precision_minima_pp"])
        )
        & tabla["proteccion_neta_suma_pct"].gt(0.0)
    )
    return tabla.sort_values(
        ["zona_elegible", "mejora_precision_pp", "proteccion_neta_suma_pct", "n"],
        ascending=[False, False, False, False],
    )


def mascara_zonas(df: pd.DataFrame, zonas: list[dict[str, str]]) -> np.ndarray:
    if not zonas:
        return np.ones(len(df), dtype=bool)
    mascara = np.zeros(len(df), dtype=bool)
    for zona in zonas:
        col = zona["zona_columna"]
        valor = zona["zona_valor"]
        mascara |= df[col].astype("string").fillna("<NA>").eq(valor).to_numpy()
    return mascara


def puntaje(m: dict[str, float]) -> float:
    lift = 0.0 if pd.isna(m["mejora_precision_pp"]) else m["mejora_precision_pp"] / 100.0
    recall = 0.0 if pd.isna(m["cobertura_caidas_pct"]) else m["cobertura_caidas_pct"] / 100.0
    falsas = 0.0 if pd.isna(m["falsas_alarmas_pct"]) else m["falsas_alarmas_pct"] / 100.0
    neta_media = m["proteccion_neta_suma_pct"] / 100.0 / max(m["n"], 1)
    return float(0.50 * lift + 0.20 * recall - 0.15 * falsas + 35.0 * neta_media)


def evaluar_afp(afp: str, base: pd.DataFrame, cfg: dict[str, Any], v2):
    g = base[base["afp"].astype(str).eq(afp)].copy()
    g["fecha_cuota"] = pd.to_datetime(g["fecha_cuota"], errors="coerce").dt.normalize()
    g["fecha_objetivo_t1"] = pd.to_datetime(
        g["fecha_objetivo_t1"], errors="coerce"
    ).dt.normalize()
    g, umbral_shock = v2.construir_episodios(g, cfg["configuracion_episodios"])
    g = agregar_rebote_relativo(g)
    eventos = g[
        g["en_episodio_rebote"]
        & g["caida_relevante_t1"].notna()
    ].copy()
    train = eventos[eventos["bloque_60_20_20"].eq("entrenamiento")].copy()
    valid = eventos[eventos["bloque_60_20_20"].eq("validacion")].copy()
    test = eventos[eventos["bloque_60_20_20"].eq("test_reservado")].copy()

    if min(len(train), len(valid), len(test)) < 50:
        raise RuntimeError(f"Muestra insuficiente para {afp}")

    zonas_tabla = tabla_zonas(valid, cfg)
    zonas_elegibles = zonas_tabla[zonas_tabla["zona_elegible"]].head(
        int(cfg["seleccion_selectiva"]["max_zonas_seleccionadas"])
    )
    zonas = zonas_elegibles[["zona_columna", "zona_valor"]].to_dict("records")
    mask_valid_zona = mascara_zonas(valid, zonas)

    candidatos: list[dict[str, Any]] = []
    modelos_ajustados: dict[str, Pipeline] = {}
    for codigo, modelo in construir_modelos(cfg):
        modelo.fit(train[FEATURES], train["caida_relevante_t1"].astype(int))
        modelos_ajustados[codigo] = modelo
        prob = modelo.predict_proba(valid[FEATURES])[:, 1]
        for cobertura in cfg["seleccion_selectiva"]["coberturas_objetivo"]:
            umbral = float(np.quantile(prob, 1.0 - float(cobertura)))
            alerta_prob = prob >= umbral
            for modo, alerta in (
                ("probabilidad", alerta_prob),
                ("probabilidad_y_zona", alerta_prob & mask_valid_zona),
            ):
                m = metricas(valid, prob, alerta)
                candidatos.append({
                    "afp": afp,
                    "modelo_codigo": codigo,
                    "modo_selectivo": modo,
                    "cobertura_objetivo": float(cobertura),
                    "umbral_probabilidad": umbral,
                    "zonas": json.dumps(zonas, ensure_ascii=False, sort_keys=True),
                    **m,
                    "puntaje_validacion": puntaje(m),
                })

    tabla = pd.DataFrame(candidatos)
    elegibles = tabla[
        tabla["n_alertas"].ge(int(cfg["seleccion_selectiva"]["min_alertas_validacion"]))
        & tabla["mejora_precision_pp"].ge(
            float(cfg["seleccion_selectiva"]["mejora_precision_minima_pp"])
        )
        & tabla["proteccion_neta_suma_pct"].gt(0.0)
    ]
    if elegibles.empty:
        elegibles = tabla[
            tabla["n_alertas"].ge(int(cfg["seleccion_selectiva"]["min_alertas_validacion"]))
        ]
    if elegibles.empty:
        elegibles = tabla
    ganador = elegibles.sort_values(
        ["puntaje_validacion", "mejora_precision_pp", "proteccion_neta_suma_pct", "auc"],
        ascending=[False, False, False, False],
        na_position="last",
    ).iloc[0]

    modelo = modelos_ajustados[str(ganador["modelo_codigo"])]
    prob_test = modelo.predict_proba(test[FEATURES])[:, 1]
    alerta_test = prob_test >= float(ganador["umbral_probabilidad"])
    if ganador["modo_selectivo"] == "probabilidad_y_zona":
        alerta_test &= mascara_zonas(test, zonas)
    met_test = metricas(test, prob_test, alerta_test)

    criterios = cfg["criterios_aprobacion"]
    aprobacion = {
        "alertas_minimas": met_test["n_alertas"] >= int(criterios["min_alertas_test"]),
        "auc_minimo": met_test["auc"] >= float(criterios["min_auc_test"]),
        "mejora_precision_minima": met_test["mejora_precision_pp"] >= float(
            criterios["min_mejora_precision_pp"]
        ),
        "cobertura_caidas_minima": met_test["cobertura_caidas_pct"] >= float(
            criterios["min_cobertura_caidas_pct"]
        ),
        "proteccion_neta_positiva": met_test["proteccion_neta_suma_pct"] > 0.0,
    }
    estado = (
        "APROBADO_PARA_SEGUIMIENTO_PROSPECTIVO"
        if all(aprobacion.values())
        else "EXPERIMENTAL_NO_APROBADO"
    )

    detalle = test[
        [
            "afp", "fecha_cuota", "fecha_objetivo_t1", "retorno_real_t1",
            "umbral_caida_relevante", "caida_relevante_t1",
            "dias_desde_shock", "rebote_desde_minimo_factor",
            "fraccion_recuperada_factor", "velocidad_rebote_factor",
            "cambio_velocidad_rebote_factor", "retroceso_desde_maximo_factor",
            "zona_etapa_recuperacion_factor", "zona_dias_rebote",
            "zona_impulso_factor", "zona_retroceso_factor",
        ]
    ].copy()
    detalle["probabilidad_riesgo"] = prob_test
    detalle["umbral_probabilidad"] = float(ganador["umbral_probabilidad"])
    detalle["alerta_salida"] = alerta_test
    detalle["estado_diario"] = np.where(alerta_test, "RIESGO_ALTO", "SIN_SENAL")

    resumen = {
        "afp": afp,
        "frecuencia": "diaria",
        "modelo_elegido": ganador["modelo_codigo"],
        "modo_selectivo": ganador["modo_selectivo"],
        "cobertura_objetivo_validacion": ganador["cobertura_objetivo"],
        "umbral_probabilidad": ganador["umbral_probabilidad"],
        "umbral_shock_factores": umbral_shock,
        "n_train": len(train),
        "n_valid": len(valid),
        "n_test": len(test),
        "zonas_seleccionadas": json.dumps(zonas, ensure_ascii=False, sort_keys=True),
        **{f"test_{k}": v for k, v in met_test.items()},
        "criterios": json.dumps(aprobacion, ensure_ascii=False, sort_keys=True),
        "estado": estado,
    }
    return resumen, tabla, zonas_tabla.assign(afp=afp), detalle


def main() -> None:
    raiz = Path(__file__).resolve().parents[2]
    salida = raiz / "data" / "processed" / "modelo_salida"
    cfg = json.loads(
        (raiz / "config" / "modelo_salida_v4_selectivo_diario.json").read_text(
            encoding="utf-8"
        )
    )
    if cfg.get("frecuencia") != "diaria":
        raise RuntimeError("La V4 debe operar exclusivamente con frecuencia diaria")
    v2 = cargar_v2(raiz)
    base = v2.leer_csv(salida / "base_modelo_salida.csv")

    resumenes: list[dict[str, Any]] = []
    candidatos: list[pd.DataFrame] = []
    zonas: list[pd.DataFrame] = []
    detalles: list[pd.DataFrame] = []
    for afp in cfg["afps"]:
        resumen, tabla, tabla_zonas_afp, detalle = evaluar_afp(afp, base, cfg, v2)
        resumenes.append(resumen)
        candidatos.append(tabla)
        zonas.append(tabla_zonas_afp)
        detalles.append(detalle)

    resumen_df = pd.DataFrame(resumenes)
    candidatos_df = pd.concat(candidatos, ignore_index=True)
    zonas_df = pd.concat(zonas, ignore_index=True)
    detalle_df = pd.concat(detalles, ignore_index=True)

    v2.escribir_csv(resumen_df, salida / "v4_resumen.csv")
    v2.escribir_csv(candidatos_df, salida / "v4_candidatos_validacion.csv")
    v2.escribir_csv(zonas_df, salida / "v4_evidencia_zonas_rebote.csv")
    v2.escribir_csv(detalle_df, salida / "v4_predicciones_test_diarias.csv")
    (salida / "v4_manifiesto.json").write_text(
        json.dumps({
            "version": cfg["version"],
            "frecuencia": "diaria",
            "regla_temporal": (
                "Cada fila usa informacion disponible al cierre del dia t y se evalua "
                "contra la siguiente fecha SBS. No usa datos horarios ni semanales."
            ),
            "regla_selectiva": (
                "El modelo puede emitir SIN_SENAL. Modelo, cobertura, umbral y zonas "
                "se eligen solo en validacion; el test final no participa en la seleccion."
            ),
            "configuracion": cfg,
            "resumen": resumenes,
        }, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    (raiz / "docs" / "modelo_salida_resultados_v4.md").write_text(
        "\n".join([
            "# Modelo de salida V4 — selectivo diario",
            "",
            "La V4 mide el rebote desde su minimo, la fraccion recuperada, la velocidad,",
            "la desaceleracion y el retroceso desde el maximo del rebote.",
            "",
            "No intenta predecir todos los dias. Puede responder SIN_SENAL.",
            "",
            resumen_df.to_markdown(index=False),
            "",
            "Modelo experimental. No constituye una recomendacion financiera.",
        ]),
        encoding="utf-8",
    )
    print(resumen_df.to_string(index=False))


if __name__ == "__main__":
    main()
