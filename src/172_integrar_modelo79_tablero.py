from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


AFPS = ["Habitat", "Integra", "Prima", "Profuturo"]
MODELO_CODIGO = "modelo79_congelado"


def leer_csv(ruta: Path) -> pd.DataFrame:
    if not ruta.exists():
        return pd.DataFrame()
    ultimo_error: Exception | None = None
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return pd.read_csv(ruta, encoding=encoding)
        except Exception as exc:
            ultimo_error = exc
    raise RuntimeError(f"No se pudo leer {ruta}: {ultimo_error}")


def escribir_csv(df: pd.DataFrame, ruta: Path) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(ruta, index=False, encoding="utf-8-sig")


def a_fecha(valores: Any) -> Any:
    try:
        return pd.to_datetime(valores, errors="coerce", format="mixed")
    except (TypeError, ValueError):
        return pd.to_datetime(valores, errors="coerce")


def normalizar_direccion(valor: Any, retorno: float) -> str:
    texto = str(valor).strip().upper()
    if texto in {"SUBE", "ALZA", "UP"}:
        return "Sube"
    if texto in {"BAJA", "DOWN"}:
        return "Baja"
    return "Sube" if retorno >= 0 else "Baja"


def cargar_modelo79(processed: Path) -> pd.DataFrame:
    partes = []
    for nombre in (
        "ca0001_modelo79_bitacora_todas_ejecuciones.csv",
        "ca0001_modelo79_detalle_estimaciones_run.csv",
    ):
        x = leer_csv(processed / nombre)
        if not x.empty:
            x = x.copy()
            x["_archivo"] = nombre
            partes.append(x)
    if not partes:
        raise FileNotFoundError(
            "No existe la bitacora ni el detalle prospectivo del Modelo 79."
        )

    x = pd.concat(partes, ignore_index=True, sort=False)
    requeridas = {
        "afp",
        "fecha_objetivo",
        "fecha_ultima_cuota_oficial",
        "cuota_ultima_oficial",
        "retorno_diario_estimado",
        "retorno_acumulado_estimado",
        "cuota_estimada",
    }
    faltantes = requeridas.difference(x.columns)
    if faltantes:
        raise ValueError(
            "Faltan columnas del Modelo 79: " + ", ".join(sorted(faltantes))
        )

    x["afp"] = x["afp"].astype(str).str.strip()
    x = x[x["afp"].isin(AFPS)].copy()
    x["fecha_objetivo"] = a_fecha(x["fecha_objetivo"])
    x["fecha_ultima_cuota_oficial"] = a_fecha(
        x["fecha_ultima_cuota_oficial"]
    )
    x["run_id"] = x.get("run_id", "").astype(str)
    x = x.dropna(subset=["fecha_objetivo", "fecha_ultima_cuota_oficial"])
    x = x.sort_values(["afp", "fecha_objetivo", "run_id", "_archivo"])
    return x.drop_duplicates(["afp", "fecha_objetivo"], keep="last")


def construir_umbrales(processed: Path) -> dict[str, dict[str, float | str]]:
    pred = leer_csv(processed / "overlay_direccion_predicciones.csv")
    seleccion = leer_csv(processed / "overlay_direccion_seleccion.csv")
    confianza = leer_csv(processed / "tablero_operativo_confianza_seleccion.csv")
    if pred.empty or seleccion.empty:
        return {}

    conf_map = (
        confianza.set_index("afp").to_dict("index")
        if not confianza.empty
        else {}
    )
    salida: dict[str, dict[str, float | str]] = {}
    for _, sel in seleccion.iterrows():
        afp = str(sel["afp"])
        codigo = str(sel["modelo_codigo"])
        col = "pred_base_calendario" if codigo == "base_calendario" else f"pred_{codigo}"
        g = pred[pred["afp"].astype(str).eq(afp)].copy()
        if col not in g.columns:
            continue
        train = g[g["bloque"].astype(str).eq("entrenamiento")]
        valores = (
            pd.to_numeric(train[col], errors="coerce")
            .abs()
            .replace([np.inf, -np.inf], np.nan)
            .dropna()
        )
        conf = conf_map.get(afp, {})
        salida[afp] = {
            "medio": float(valores.quantile(0.60)) if not valores.empty else np.inf,
            "verde": float(conf.get("umbral_abs_pred", np.inf)),
            "razon": str(conf.get("filtro", "Prediccion fuerte")),
        }
    return salida


def clasificar(
    afp: str,
    retorno: float,
    cobertura: float,
    nivel: Any,
    umbrales: dict[str, dict[str, float | str]],
) -> tuple[str, str, str]:
    if cobertura < 60.0 or str(nivel).strip().upper() not in {"ALTA", ""}:
        return "Gris", "No", "Cobertura insuficiente"
    cfg = umbrales.get(afp, {})
    magnitud = abs(retorno)
    if magnitud >= float(cfg.get("verde", np.inf)):
        return "Verde", "Si", str(cfg.get("razon", "Prediccion fuerte"))
    if magnitud >= float(cfg.get("medio", np.inf)):
        return "Amarillo", "Cuidado", "Senal media"
    return "Gris", "No", "Senal debil"


def cargar_oficiales(processed: Path) -> tuple[dict, dict]:
    pred = leer_csv(processed / "overlay_direccion_predicciones.csv")
    if pred.empty:
        return {}, {}
    pred["fecha"] = a_fecha(pred["fecha"])
    pred["valor_cuota"] = pd.to_numeric(pred.get("valor_cuota"), errors="coerce")
    pred["retorno_real"] = pd.to_numeric(pred.get("retorno_real"), errors="coerce")
    pred = pred.dropna(subset=["afp", "fecha", "valor_cuota"])
    pred = pred.sort_values(["afp", "fecha"]).drop_duplicates(
        ["afp", "fecha"], keep="last"
    )
    indice = pred.set_index(["afp", "fecha"])
    return indice["valor_cuota"].to_dict(), indice["retorno_real"].to_dict()


def construir_filas(
    modelo79: pd.DataFrame,
    processed: Path,
) -> pd.DataFrame:
    umbrales = construir_umbrales(processed)
    cuota_real_map, retorno_real_map = cargar_oficiales(processed)
    filas = []

    for afp, g in modelo79.groupby("afp", sort=True):
        g = g.sort_values("fecha_objetivo")
        estado: dict[pd.Timestamp, tuple[int, float]] = {}
        for _, row in g.iterrows():
            fecha = pd.Timestamp(row["fecha_objetivo"]).normalize()
            fecha_base = pd.Timestamp(row["fecha_ultima_cuota_oficial"]).normalize()
            cuota_base_sbs = pd.to_numeric(row["cuota_ultima_oficial"], errors="coerce")
            retorno = pd.to_numeric(row["retorno_diario_estimado"], errors="coerce")
            retorno_acum = pd.to_numeric(
                row["retorno_acumulado_estimado"], errors="coerce"
            )
            cuota_estimada = pd.to_numeric(row["cuota_estimada"], errors="coerce")
            cobertura = pd.to_numeric(row.get("cobertura_factores_pct"), errors="coerce")
            if pd.isna(cuota_base_sbs) or pd.isna(retorno) or pd.isna(cuota_estimada):
                continue
            cobertura = 0.0 if pd.isna(cobertura) else float(cobertura)
            retorno = float(retorno)
            retorno_acum = (
                float(retorno_acum)
                if pd.notna(retorno_acum)
                else float(cuota_estimada / cuota_base_sbs - 1.0)
            )

            ruedas_previas, cuota_previa = estado.get(
                fecha_base, (0, float(cuota_base_sbs))
            )
            ruedas = ruedas_previas + 1
            confianza, usar, razon = clasificar(
                afp,
                retorno,
                cobertura,
                row.get("nivel_cobertura_datos", ""),
                umbrales,
            )
            valor_real = cuota_real_map.get((afp, fecha), np.nan)
            retorno_real = retorno_real_map.get((afp, fecha), np.nan)
            resultado = "Pendiente SBS"
            acierto: bool | float = np.nan
            if pd.notna(valor_real):
                if pd.isna(retorno_real) and cuota_previa:
                    retorno_real = float(valor_real / cuota_previa - 1.0)
                if pd.notna(retorno_real):
                    acierto = bool(np.sign(retorno_real) == np.sign(retorno))
                    resultado = "Acierto" if acierto else "Fallo"
            error = (
                float(cuota_estimada - valor_real)
                if pd.notna(valor_real)
                else np.nan
            )
            error_pct = (
                abs(error / valor_real) * 100.0
                if pd.notna(error) and valor_real != 0
                else np.nan
            )

            filas.append(
                {
                    "fecha": fecha,
                    "afp": afp,
                    "modelo_codigo": MODELO_CODIGO,
                    "fuente_pronostico": "Modelo 79 congelado",
                    "retorno_estimado": retorno,
                    "retorno_estimado_pct": retorno * 100.0,
                    "direccion_estimada": normalizar_direccion(
                        row.get("direccion_estimada"), retorno
                    ),
                    "confianza": confianza,
                    "usar_senal": usar,
                    "razon": razon,
                    "fecha_base_sbs": fecha_base,
                    "cuota_base_sbs": float(cuota_base_sbs),
                    "ruedas_estimadas_desde_sbs": ruedas,
                    "cuota_base": cuota_previa,
                    "cuota_estimada": float(cuota_estimada),
                    "retorno_acumulado_estimado_desde_sbs": retorno_acum,
                    "retorno_acumulado_estimado_desde_sbs_pct": retorno_acum * 100.0,
                    "sbs_publicada": valor_real,
                    "retorno_real": retorno_real,
                    "error_cuota": error,
                    "error_abs_pct": error_pct,
                    "acierto_direccion": acierto,
                    "resultado": resultado,
                    "bloque": "prospectivo_modelo79",
                    "run_id": str(row.get("run_id", "")),
                }
            )
            estado[fecha_base] = (ruedas, float(cuota_estimada))

    return pd.DataFrame(filas).sort_values(["afp", "fecha"])


def actualizar_salidas(processed: Path, filas79: pd.DataFrame) -> pd.DataFrame:
    bitacora = leer_csv(processed / "tablero_operativo_bitacora_diaria.csv")
    if bitacora.empty:
        combinado = filas79.copy()
    else:
        bitacora["fecha"] = a_fecha(bitacora["fecha"])
        bitacora["_prioridad"] = 1
        filas79 = filas79.copy()
        filas79["_prioridad"] = 2
        combinado = pd.concat([bitacora, filas79], ignore_index=True, sort=False)
    combinado["run_id"] = combinado.get("run_id", "").fillna("").astype(str)
    orden = ["afp", "fecha", "run_id"]
    if "_prioridad" in combinado.columns:
        orden.insert(2, "_prioridad")
    combinado = combinado.sort_values(orden).drop_duplicates(
        ["afp", "fecha"], keep="last"
    )
    combinado = combinado.drop(columns=["_prioridad"], errors="ignore").sort_values(["afp", "fecha"])

    fecha_max = combinado["fecha"].max()
    ultima = combinado.groupby("afp", as_index=False).tail(1)
    ultimos = combinado[combinado["fecha"].ge(fecha_max - pd.Timedelta(days=30))]
    grafico = combinado[combinado["fecha"].ge(fecha_max - pd.Timedelta(days=24))][
        [
            "fecha",
            "afp",
            "sbs_publicada",
            "cuota_estimada",
            "cuota_base",
            "fecha_base_sbs",
            "cuota_base_sbs",
            "ruedas_estimadas_desde_sbs",
            "retorno_estimado_pct",
            "retorno_acumulado_estimado_desde_sbs_pct",
            "direccion_estimada",
            "error_cuota",
            "error_abs_pct",
            "resultado",
        ]
    ].rename(columns={"cuota_estimada": "modelo_overlay_estimado"})

    escribir_csv(combinado, processed / "tablero_operativo_bitacora_diaria.csv")
    escribir_csv(ultima, processed / "tablero_operativo_ultima_senal.csv")
    escribir_csv(ultimos, processed / "tablero_operativo_ultimos_dias.csv")
    escribir_csv(grafico, processed / "tablero_operativo_grafico.csv")
    return combinado


def validar(modelo79: pd.DataFrame, bitacora: pd.DataFrame, processed: Path) -> pd.DataFrame:
    esperada = (
        modelo79.groupby("afp", as_index=False)["fecha_objetivo"]
        .max()
        .rename(columns={"fecha_objetivo": "ultima_fecha_modelo79"})
    )
    publicada = (
        bitacora[bitacora["modelo_codigo"].eq(MODELO_CODIGO)]
        .groupby("afp", as_index=False)["fecha"]
        .max()
        .rename(columns={"fecha": "ultima_fecha_visora"})
    )
    auditoria = esperada.merge(publicada, on="afp", how="left")
    auditoria["estado"] = np.where(
        auditoria["ultima_fecha_visora"].ge(auditoria["ultima_fecha_modelo79"]),
        "CORRECTO",
        "DESACTUALIZADO",
    )
    escribir_csv(auditoria, processed / "tablero_operativo_auditoria_fechas.csv")
    fallas = auditoria[auditoria["estado"].ne("CORRECTO")]
    if not fallas.empty:
        raise RuntimeError(
            "El Modelo 79 tiene fechas que no llegaron al visor:\n"
            + fallas.to_string(index=False)
        )
    return auditoria


def main() -> None:
    raiz = Path(__file__).resolve().parents[1]
    processed = raiz / "data" / "processed"
    modelo79 = cargar_modelo79(processed)
    filas79 = construir_filas(modelo79, processed)
    if filas79.empty:
        raise RuntimeError("El Modelo 79 no produjo filas utilizables para el tablero.")
    bitacora = actualizar_salidas(processed, filas79)
    auditoria = validar(modelo79, bitacora, processed)

    ultima = bitacora.groupby("afp", as_index=False).tail(1)
    print("Fechas prospectivas del Modelo 79 integradas sin modificar la canasta")
    print(
        ultima[
            [
                "fecha",
                "afp",
                "direccion_estimada",
                "confianza",
                "cuota_estimada",
                "resultado",
            ]
        ].to_string(index=False)
    )
    print("\nAuditoria de fechas:")
    print(auditoria.to_string(index=False))


if __name__ == "__main__":
    main()
