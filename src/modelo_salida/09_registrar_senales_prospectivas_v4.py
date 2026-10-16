from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from datetime import datetime, timezone
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


def leer_csv_opcional(ruta: Path) -> pd.DataFrame:
    if not ruta.exists() or ruta.stat().st_size == 0:
        return pd.DataFrame()
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return pd.read_csv(ruta, encoding=enc)
        except Exception:
            continue
    raise RuntimeError(f"No se pudo leer {ruta}")


def escribir_csv(df: pd.DataFrame, ruta: Path) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(ruta, index=False, encoding="utf-8-sig", date_format="%Y-%m-%d")


def modelo_por_codigo(v4, cfg_v4: dict[str, Any], codigo: str):
    for cod, modelo in v4.construir_modelos(cfg_v4):
        if cod == codigo:
            return modelo
    raise RuntimeError(f"Modelo congelado no encontrado: {codigo}")


def preparar_afp(
    afp: str,
    base: pd.DataFrame,
    cfg_v4: dict[str, Any],
    v2,
    v4,
) -> pd.DataFrame:
    g = base[base["afp"].astype(str).eq(afp)].copy()
    if g.empty:
        raise RuntimeError(f"No hay datos para {afp}")
    g["fecha_cuota"] = pd.to_datetime(g["fecha_cuota"], errors="coerce").dt.normalize()
    g["fecha_objetivo_t1"] = pd.to_datetime(
        g["fecha_objetivo_t1"], errors="coerce"
    ).dt.normalize()
    g, _ = v2.construir_episodios(g, cfg_v4["configuracion_episodios"])
    g = v4.agregar_rebote_relativo(g)
    return g.sort_values("fecha_cuota").reset_index(drop=True)


def fecha_objetivo(fila: pd.Series) -> tuple[pd.Timestamp, bool]:
    fecha = pd.to_datetime(fila.get("fecha_objetivo_t1"), errors="coerce")
    if pd.notna(fecha):
        return pd.Timestamp(fecha).normalize(), False
    decision = pd.Timestamp(fila["fecha_cuota"]).normalize()
    return (decision + pd.offsets.BDay(1)).normalize(), True


def seleccionar_fila_decision(g: pd.DataFrame, features: list[str]) -> pd.Series:
    candidatos = g[g["fecha_cuota"].notna()].copy()
    if "retorno_medio_factores" in candidatos.columns:
        candidatos = candidatos[
            pd.to_numeric(candidatos["retorno_medio_factores"], errors="coerce").notna()
        ]
    if candidatos.empty:
        raise RuntimeError("No existe una fila reciente con factores de mercado")
    faltan = [c for c in features if c not in candidatos.columns]
    if faltan:
        raise RuntimeError(f"Faltan variables congeladas: {faltan}")
    return candidatos.iloc[-1]


def evaluar_modelo(
    afp: str,
    especificacion: dict[str, Any],
    g: pd.DataFrame,
    cfg_v4: dict[str, Any],
    version: str,
    config_hash: str,
    v4,
) -> dict[str, Any]:
    features = list(especificacion["features"])
    fila = seleccionar_fila_decision(g, features)
    decision = pd.Timestamp(fila["fecha_cuota"]).normalize()
    objetivo, objetivo_inferido = fecha_objetivo(fila)

    fechas_obj = pd.to_datetime(g["fecha_objetivo_t1"], errors="coerce").dt.normalize()
    hist = g[
        g["en_episodio_rebote"]
        & g["caida_relevante_t1"].notna()
        & (fechas_obj < decision)
    ].copy()
    if len(hist) < int(cfg_v4["walk_forward"]["minimo_eventos_historial"]):
        raise RuntimeError(
            f"Historial insuficiente para {afp}: {len(hist)} observaciones"
        )
    if hist["caida_relevante_t1"].nunique() < 2:
        raise RuntimeError(f"El historial de {afp} no contiene ambas clases")

    hist = v4.limpiar_numericos(hist, features)
    modelo = modelo_por_codigo(v4, cfg_v4, str(especificacion["modelo_codigo"]))
    modelo.fit(hist[features], hist["caida_relevante_t1"].astype(int))
    calibracion = hist.tail(min(250, len(hist))).copy()
    prob_hist = modelo.predict_proba(calibracion[features])[:, 1]
    cobertura = float(especificacion["cobertura_objetivo"])
    umbral = float(np.quantile(prob_hist, 1.0 - cobertura))

    fila_df = v4.limpiar_numericos(pd.DataFrame([fila]), features)
    probabilidad = float(modelo.predict_proba(fila_df[features])[:, 1][0])
    en_episodio = bool(fila.get("en_episodio_rebote", False))
    supera_umbral = bool(probabilidad >= umbral)
    habilitado = bool(especificacion["habilitado_senal"])

    if not en_episodio:
        estado_diario = "FUERA_DE_EPISODIO"
        alerta_habilitada = False
    elif habilitado:
        estado_diario = "RIESGO_ALTO" if supera_umbral else "SIN_SENAL"
        alerta_habilitada = supera_umbral
    else:
        estado_diario = "SOMBRA_RIESGO_ALTO" if supera_umbral else "SOMBRA_SIN_SENAL"
        alerta_habilitada = False

    ahora = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    key = f"{especificacion['model_id']}|{decision.date()}|{objetivo.date()}"
    return {
        "signal_key": key,
        "generado_utc": ahora,
        "version_congelada": version,
        "config_hash_sha256": config_hash,
        "model_id": especificacion["model_id"],
        "afp": afp,
        "frecuencia": "diaria",
        "fecha_decision": decision.date().isoformat(),
        "fecha_objetivo": objetivo.date().isoformat(),
        "fecha_objetivo_inferida": objetivo_inferido,
        "modelo_codigo": especificacion["modelo_codigo"],
        "variante": especificacion["variante"],
        "estado_validacion": especificacion["estado_validacion"],
        "habilitado_senal": habilitado,
        "en_episodio_rebote": en_episodio,
        "probabilidad_riesgo": probabilidad,
        "umbral_dinamico": umbral,
        "cobertura_objetivo": cobertura,
        "supera_umbral": supera_umbral,
        "alerta_habilitada": alerta_habilitada,
        "estado_diario": estado_diario,
        "n_historial_disponible": len(hist),
        "ultima_cuota_sbs_conocida": pd.to_numeric(
            fila.get("cuota_sbs_conocida"), errors="coerce"
        ),
        "dias_desde_shock": pd.to_numeric(
            fila.get("dias_desde_shock"), errors="coerce"
        ),
        "rebote_desde_minimo_factor": pd.to_numeric(
            fila.get("rebote_desde_minimo_factor"), errors="coerce"
        ),
        "fraccion_recuperada_factor": pd.to_numeric(
            fila.get("fraccion_recuperada_factor"), errors="coerce"
        ),
        "velocidad_rebote_factor": pd.to_numeric(
            fila.get("velocidad_rebote_factor"), errors="coerce"
        ),
        "retroceso_desde_maximo_factor": pd.to_numeric(
            fila.get("retroceso_desde_maximo_factor"), errors="coerce"
        ),
    }


def anexar_senales(nuevas: pd.DataFrame, ruta: Path) -> pd.DataFrame:
    anterior = leer_csv_opcional(ruta)
    if anterior.empty:
        combinado = nuevas.copy()
    else:
        existentes = set(anterior["signal_key"].astype(str))
        agregar = nuevas[~nuevas["signal_key"].astype(str).isin(existentes)].copy()
        combinado = pd.concat([anterior, agregar], ignore_index=True)
    combinado = combinado.drop_duplicates(subset=["signal_key"], keep="first")
    combinado = combinado.sort_values(["fecha_decision", "afp", "model_id"])
    escribir_csv(combinado, ruta)
    return combinado


def anexar_resultados(
    senales: pd.DataFrame,
    preparados: dict[str, pd.DataFrame],
    ruta: Path,
) -> pd.DataFrame:
    anterior = leer_csv_opcional(ruta)
    keys_previas = set(anterior["signal_key"].astype(str)) if not anterior.empty else set()
    filas: list[dict[str, Any]] = []
    for _, senal in senales.iterrows():
        key = str(senal["signal_key"])
        if key in keys_previas:
            continue
        afp = str(senal["afp"])
        g = preparados.get(afp)
        if g is None:
            continue
        decision = pd.Timestamp(senal["fecha_decision"]).normalize()
        objetivo = pd.Timestamp(senal["fecha_objetivo"]).normalize()
        fechas_obj = pd.to_datetime(g["fecha_objetivo_t1"], errors="coerce").dt.normalize()
        coincidencia = g[
            g["fecha_cuota"].eq(decision)
            & fechas_obj.eq(objetivo)
            & g["retorno_real_t1"].notna()
        ]
        if coincidencia.empty:
            continue
        real = coincidencia.iloc[-1]
        retorno = float(real["retorno_real_t1"])
        caida = bool(int(real["caida_relevante_t1"]))
        supera = str(senal.get("supera_umbral", "False")).lower() in {"true", "1"}
        habilitada = str(senal.get("habilitado_senal", "False")).lower() in {"true", "1"}
        if habilitada:
            resultado = (
                "ALERTA_Y_CAIDA" if supera and caida
                else "ALERTA_SIN_CAIDA" if supera and not caida
                else "SIN_ALERTA_Y_CAIDA" if (not supera) and caida
                else "SIN_ALERTA_SIN_CAIDA"
            )
        else:
            resultado = "RESULTADO_MODELO_SOMBRA"
        filas.append({
            "signal_key": key,
            "verificado_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "model_id": senal["model_id"],
            "afp": afp,
            "fecha_decision": senal["fecha_decision"],
            "fecha_objetivo": senal["fecha_objetivo"],
            "estado_emitido": senal["estado_diario"],
            "probabilidad_emitida": senal["probabilidad_riesgo"],
            "umbral_emitido": senal["umbral_dinamico"],
            "retorno_real_t1": retorno,
            "caida_relevante_real": caida,
            "resultado": resultado,
        })
    if filas:
        nuevo = pd.DataFrame(filas)
        combinado = pd.concat([anterior, nuevo], ignore_index=True) if not anterior.empty else nuevo
    else:
        combinado = anterior.copy()
    if not combinado.empty:
        combinado = combinado.drop_duplicates(subset=["signal_key"], keep="first")
        combinado = combinado.sort_values(["fecha_objetivo", "afp", "model_id"])
    escribir_csv(combinado, ruta)
    return combinado


def main() -> None:
    raiz = Path(__file__).resolve().parents[2]
    salida_modelo = raiz / "data" / "processed" / "modelo_salida"
    salida_prospectiva = raiz / "data" / "prospectivo" / "modelo_salida"
    ruta_config = raiz / "config" / "modelo_salida_v4_congelado.json"
    texto_config = ruta_config.read_text(encoding="utf-8")
    congelado = json.loads(texto_config)
    config_hash = hashlib.sha256(
        json.dumps(congelado, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    if not congelado.get("congelado") or congelado.get("frecuencia") != "diaria":
        raise RuntimeError("La configuracion debe estar congelada y ser diaria")

    v2 = cargar_modulo(
        "modelo_salida_v2_para_prospectivo",
        raiz / "src" / "modelo_salida" / "04_modelo_rebote_salida_v2.py",
    )
    v4 = cargar_modulo(
        "modelo_salida_v4_para_prospectivo",
        raiz / "src" / "modelo_salida" / "06_modelo_selectivo_diario_v4.py",
    )
    cfg_v4 = json.loads(
        (raiz / "config" / "modelo_salida_v4_selectivo_diario.json").read_text(
            encoding="utf-8"
        )
    )
    base = v2.leer_csv(salida_modelo / "base_modelo_salida.csv")

    preparados: dict[str, pd.DataFrame] = {}
    filas: list[dict[str, Any]] = []
    for afp, especificacion in congelado["modelos"].items():
        g = preparar_afp(afp, base, cfg_v4, v2, v4)
        preparados[afp] = g
        filas.append(
            evaluar_modelo(
                afp,
                especificacion,
                g,
                cfg_v4,
                congelado["version"],
                config_hash,
                v4,
            )
        )

    actuales = pd.DataFrame(filas)
    ruta_senales = salida_prospectiva / "senales_diarias.csv"
    ruta_resultados = salida_prospectiva / "resultados_senales.csv"
    historial = anexar_senales(actuales, ruta_senales)
    resultados = anexar_resultados(historial, preparados, ruta_resultados)
    escribir_csv(actuales, salida_prospectiva / "ultima_senal.csv")

    manifiesto = {
        "version": congelado["version"],
        "config_hash_sha256": config_hash,
        "frecuencia": "diaria",
        "generado_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "n_senales_historicas": len(historial),
        "n_resultados_verificados": len(resultados),
        "regla_append_only": True,
        "senales_actuales": actuales.to_dict("records"),
    }
    salida_prospectiva.mkdir(parents=True, exist_ok=True)
    (salida_prospectiva / "manifiesto_prospectivo.json").write_text(
        json.dumps(manifiesto, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(actuales[[
        "afp", "fecha_decision", "fecha_objetivo", "estado_validacion",
        "probabilidad_riesgo", "umbral_dinamico", "estado_diario",
    ]].to_string(index=False))


if __name__ == "__main__":
    main()
