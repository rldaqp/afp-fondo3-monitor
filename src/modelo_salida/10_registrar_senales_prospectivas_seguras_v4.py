from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


MAX_ANTIGUEDAD_CALENDARIO_DIAS = 5
AFPS = ["Habitat", "Integra", "Prima", "Profuturo"]


def cargar_modulo(nombre: str, ruta: Path):
    spec = importlib.util.spec_from_file_location(nombre, ruta)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"No se pudo cargar {ruta}")
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = modulo
    spec.loader.exec_module(modulo)
    return modulo


def escribir_csv(df: pd.DataFrame, ruta: Path) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(ruta, index=False, encoding="utf-8-sig", date_format="%Y-%m-%d")


def columnas_senal() -> list[str]:
    return [
        "signal_key", "generado_utc", "version_congelada", "config_hash_sha256",
        "model_id", "afp", "frecuencia", "fecha_decision", "fecha_objetivo",
        "fecha_objetivo_inferida", "modelo_codigo", "variante",
        "estado_validacion", "habilitado_senal", "en_episodio_rebote",
        "probabilidad_riesgo", "umbral_dinamico", "cobertura_objetivo",
        "supera_umbral", "alerta_habilitada", "estado_diario",
        "n_historial_disponible", "ultima_cuota_sbs_conocida",
        "dias_desde_shock", "rebote_desde_minimo_factor",
        "fraccion_recuperada_factor", "velocidad_rebote_factor",
        "retroceso_desde_maximo_factor",
    ]


def ultima_fecha_oficial(g: pd.DataFrame) -> pd.Timestamp | None:
    cuota = pd.to_numeric(g.get("cuota_sbs"), errors="coerce")
    fechas = pd.to_datetime(g.get("fecha_cuota"), errors="coerce").dt.normalize()
    validas = fechas[cuota.notna()]
    if validas.empty:
        return None
    return pd.Timestamp(validas.max()).normalize()


def buscar_fila_pendiente(g: pd.DataFrame, modulo09) -> tuple[pd.Series | None, dict[str, Any]]:
    hoy = pd.Timestamp(datetime.now(timezone.utc).date())
    factores = pd.to_numeric(g.get("retorno_medio_factores"), errors="coerce")
    retorno_objetivo = pd.to_numeric(g.get("retorno_real_t1"), errors="coerce")
    fechas = pd.to_datetime(g.get("fecha_cuota"), errors="coerce").dt.normalize()
    fecha_sbs = ultima_fecha_oficial(g)

    candidatos = g[
        fechas.notna()
        & factores.notna()
        & retorno_objetivo.isna()
    ].copy()
    if candidatos.empty:
        ultima_factor = fechas[factores.notna()].max() if factores.notna().any() else pd.NaT
        return None, {
            "estado_ejecucion": "SIN_OBJETIVO_PENDIENTE",
            "detalle": "No existe una fila cuya cuota objetivo siga sin conocerse.",
            "ultima_fecha_factores": ultima_factor,
            "ultima_fecha_sbs_base": fecha_sbs,
            "antiguedad_calendario_dias": (
                int((hoy - ultima_factor).days) if pd.notna(ultima_factor) else None
            ),
        }

    candidatos = candidatos.sort_values("fecha_cuota")
    fila = candidatos.iloc[-1]
    decision = pd.Timestamp(fila["fecha_cuota"]).normalize()
    objetivo, inferida = modulo09.fecha_objetivo(fila)
    antiguedad = int((hoy - decision).days)

    if fecha_sbs is not None and objetivo <= fecha_sbs:
        return None, {
            "estado_ejecucion": "OBJETIVO_YA_CONOCIDO",
            "detalle": "La fecha objetivo no es posterior a la ultima cuota SBS presente en la base.",
            "ultima_fecha_factores": decision,
            "ultima_fecha_sbs_base": fecha_sbs,
            "fecha_objetivo_candidata": objetivo,
            "fecha_objetivo_inferida": inferida,
            "antiguedad_calendario_dias": antiguedad,
        }
    if antiguedad > MAX_ANTIGUEDAD_CALENDARIO_DIAS:
        return None, {
            "estado_ejecucion": "DATOS_DESACTUALIZADOS",
            "detalle": (
                f"La ultima fila candidata tiene {antiguedad} dias de antiguedad; "
                f"el maximo permitido es {MAX_ANTIGUEDAD_CALENDARIO_DIAS}."
            ),
            "ultima_fecha_factores": decision,
            "ultima_fecha_sbs_base": fecha_sbs,
            "fecha_objetivo_candidata": objetivo,
            "fecha_objetivo_inferida": inferida,
            "antiguedad_calendario_dias": antiguedad,
        }

    return fila, {
        "estado_ejecucion": "FILA_PENDIENTE_VALIDA",
        "detalle": "La fecha es reciente y el resultado SBS objetivo aun no esta disponible en la base.",
        "ultima_fecha_factores": decision,
        "ultima_fecha_sbs_base": fecha_sbs,
        "fecha_objetivo_candidata": objetivo,
        "fecha_objetivo_inferida": inferida,
        "antiguedad_calendario_dias": antiguedad,
    }


def main() -> None:
    raiz = Path(__file__).resolve().parents[2]
    salida_modelo = raiz / "data" / "processed" / "modelo_salida"
    salida = raiz / "data" / "prospectivo" / "modelo_salida"
    salida.mkdir(parents=True, exist_ok=True)

    modulo09 = cargar_modulo(
        "registro_prospectivo_v4_base",
        raiz / "src" / "modelo_salida" / "09_registrar_senales_prospectivas_v4.py",
    )
    v2 = cargar_modulo(
        "modelo_salida_v2_para_registro_seguro",
        raiz / "src" / "modelo_salida" / "04_modelo_rebote_salida_v2.py",
    )
    v4 = cargar_modulo(
        "modelo_salida_v4_para_registro_seguro",
        raiz / "src" / "modelo_salida" / "06_modelo_selectivo_diario_v4.py",
    )

    ruta_config = raiz / "config" / "modelo_salida_v4_congelado.json"
    congelado = json.loads(ruta_config.read_text(encoding="utf-8"))
    if congelado.get("congelado") is not True or congelado.get("frecuencia") != "diaria":
        raise RuntimeError("La configuracion debe estar congelada y ser diaria")
    config_hash = hashlib.sha256(
        json.dumps(congelado, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    cfg_v4 = json.loads(
        (raiz / "config" / "modelo_salida_v4_selectivo_diario.json").read_text(
            encoding="utf-8"
        )
    )
    base = v2.leer_csv(salida_modelo / "base_modelo_salida.csv")

    preparados: dict[str, pd.DataFrame] = {}
    nuevas: list[dict[str, Any]] = []
    estados: list[dict[str, Any]] = []
    ahora = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    for afp in AFPS:
        especificacion = congelado["modelos"][afp]
        g = modulo09.preparar_afp(afp, base, cfg_v4, v2, v4)
        preparados[afp] = g
        fila, estado = buscar_fila_pendiente(g, modulo09)
        estados.append({
            "generado_utc": ahora,
            "afp": afp,
            "model_id": especificacion["model_id"],
            "habilitado_senal": bool(especificacion["habilitado_senal"]),
            **estado,
        })
        if fila is None:
            continue

        decision = pd.Timestamp(fila["fecha_cuota"]).normalize()
        g_hasta_decision = g[g["fecha_cuota"].le(decision)].copy()
        nuevas.append(
            modulo09.evaluar_modelo(
                afp,
                especificacion,
                g_hasta_decision,
                cfg_v4,
                congelado["version"],
                config_hash,
                v4,
            )
        )

    nuevas_df = pd.DataFrame(nuevas, columns=columnas_senal())
    ruta_historial = salida / "senales_diarias.csv"
    ruta_resultados = salida / "resultados_senales.csv"

    if nuevas_df.empty:
        historial = modulo09.leer_csv_opcional(ruta_historial)
        if historial.empty:
            historial = pd.DataFrame(columns=columnas_senal())
            escribir_csv(historial, ruta_historial)
    else:
        historial = modulo09.anexar_senales(nuevas_df, ruta_historial)

    resultados = modulo09.anexar_resultados(historial, preparados, ruta_resultados)
    escribir_csv(nuevas_df, salida / "ultima_senal.csv")
    estado_df = pd.DataFrame(estados)
    escribir_csv(estado_df, salida / "estado_ejecucion.csv")

    manifiesto = {
        "version": congelado["version"],
        "config_hash_sha256": config_hash,
        "frecuencia": "diaria",
        "generado_utc": ahora,
        "max_antiguedad_calendario_dias": MAX_ANTIGUEDAD_CALENDARIO_DIAS,
        "n_senales_nuevas": len(nuevas_df),
        "n_senales_prospectivas_acumuladas": len(historial),
        "n_resultados_verificados": len(resultados),
        "regla_append_only": True,
        "regla_frescura": (
            "Solo se registra cuando retorno_real_t1 esta ausente, la fecha objetivo "
            "es posterior a la ultima SBS de la base y la decision no supera cinco dias."
        ),
        "estado_ejecucion": estado_df.to_dict("records"),
        "senales_nuevas": nuevas_df.to_dict("records"),
    }
    (salida / "manifiesto_prospectivo.json").write_text(
        json.dumps(manifiesto, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    print(estado_df.to_string(index=False))
    if nuevas_df.empty:
        print("No se anadio ninguna senal prospectiva: no habia una fecha fresca y pendiente.")
    else:
        print(nuevas_df[[
            "afp", "fecha_decision", "fecha_objetivo", "probabilidad_riesgo",
            "umbral_dinamico", "estado_diario",
        ]].to_string(index=False))


if __name__ == "__main__":
    main()
