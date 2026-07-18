from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


AFPS = ["Habitat", "Integra", "Prima", "Profuturo"]
COBERTURA_MINIMA = 60.0

MAPE_HISTORICO = {
    "Habitat": 0.638053,
    "Integra": 0.718793,
    "Prima": 0.783118,
    "Profuturo": 0.751328,
}

DIRECCION_HISTORICA = {
    "Habitat": 83.642496,
    "Integra": 79.763912,
    "Prima": 81.281619,
    "Profuturo": 82.799325,
}


PARAMETROS_MODELO = {
    "Habitat": {
        "modelo": "EW-Ridge",
        "alpha": 0.001,
        "half_life": 60,
        "factores": 9,
    },
    "Integra": {
        "modelo": "EW-Ridge",
        "alpha": 0.001,
        "half_life": 500,
        "factores": 4,
    },
    "Prima": {
        "modelo": "EW-Ridge",
        "alpha": 0.001,
        "half_life": 500,
        "factores": 3,
    },
    "Profuturo": {
        "modelo": "EW-Ridge",
        "alpha": 0.001,
        "half_life": 500,
        "factores": 5,
    },
}

NOMBRES_FACTORES = {
    "ret_USD_EPU": "ETF Perú (EPU)",
    "ret_USD_VT": "Acciones globales (VT)",
    "ret_USD_XLE": "Energía de EE. UU. (XLE)",
    "ret_PEN_REMX": "Minería global en soles (REMX)",
    "ret_USD_EFA": "Mercados desarrollados (EFA)",
    "ret_BVL_PEN_MINSUR": "Minsur",
    "ret_BVL_PEN_INRETAIL_PERU": "InRetail Perú",
    "ret_IDX_LOCAL_AUSTRALIA_S_P_ASX_200": "Bolsa de Australia",
    "ret_IDX_LOCAL_JAP_N_NIKKEI_225": "Bolsa de Japón",
    "ret_USD_COPX": "Cobre global (COPX)",
    "ret_USD_SPY": "S&P 500 (SPY)",
    "ret_PEN_FCX": "Freeport-McMoRan en soles",
    "ret_PEN_MCHI": "China en soles (MCHI)",
    "ret_USD_FCX": "Freeport-McMoRan (FCX)",
    "ret_USD_NEM": "Newmont (NEM)",
}


def leer_csv(ruta: Path, obligatorio: bool = False) -> pd.DataFrame:
    if not ruta.exists():
        if obligatorio:
            raise FileNotFoundError(f"Falta el archivo: {ruta}")
        return pd.DataFrame()

    ultimo_error: Exception | None = None
    for encoding in ("utf-8-sig", "latin-1", "utf-8"):
        try:
            return pd.read_csv(ruta, encoding=encoding)
        except Exception as exc:
            ultimo_error = exc

    raise RuntimeError(f"No se pudo leer {ruta}: {ultimo_error}")


def detectar_raiz_proyecto() -> Path:
    inicios = [Path(__file__).resolve().parent, Path.cwd().resolve()]
    revisados: list[Path] = []

    for inicio in inicios:
        for candidato in [inicio, *inicio.parents]:
            if candidato in revisados:
                continue
            revisados.append(candidato)
            if (candidato / "data" / "processed").is_dir():
                return candidato

    ubicaciones = "\n".join(f" - {p}" for p in revisados[:15])
    raise FileNotFoundError(
        "No pude encontrar la carpeta principal del proyecto.\n"
        "Debe contener data\\processed.\n\n"
        f"Carpetas revisadas:\n{ubicaciones}"
    )


def normalizar_afp(valor: Any) -> str:
    texto = str(valor).strip().lower()
    mapa = {
        "habitat": "Habitat",
        "integra": "Integra",
        "prima": "Prima",
        "profuturo": "Profuturo",
    }
    return mapa.get(texto, str(valor).strip())


def buscar_columna(df: pd.DataFrame, aliases: tuple[str, ...]) -> str | None:
    mapa = {str(c).strip().lower(): c for c in df.columns}
    for alias in aliases:
        if alias.lower() in mapa:
            return mapa[alias.lower()]
    return None


def a_fecha(serie: pd.Series) -> pd.Series:
    """
    Convierte fechas sin intercambiar mes y día.

    Reglas:
    - YYYY-MM-DD o YYYY/MM/DD: se interpreta como año-mes-día.
    - DD/MM/YYYY o DD-MM-YYYY: se interpreta como día-mes-año.
    """
    texto = serie.astype(str).str.strip()
    salida = pd.Series(pd.NaT, index=serie.index, dtype="datetime64[ns]")

    mascara_iso = texto.str.match(
        r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}(?:\s|$)",
        na=False,
    )

    if mascara_iso.any():
        salida.loc[mascara_iso] = pd.to_datetime(
            texto.loc[mascara_iso],
            errors="coerce",
            yearfirst=True,
            dayfirst=False,
        )

    mascara_no_iso = ~mascara_iso
    if mascara_no_iso.any():
        salida.loc[mascara_no_iso] = pd.to_datetime(
            texto.loc[mascara_no_iso],
            errors="coerce",
            dayfirst=True,
            yearfirst=False,
        )

    faltantes = salida.isna()
    if faltantes.any():
        salida.loc[faltantes] = pd.to_datetime(
            texto.loc[faltantes],
            errors="coerce",
        )

    return salida.dt.normalize()

def a_numero(serie: pd.Series) -> pd.Series:
    return pd.to_numeric(serie, errors="coerce")


def _normalizar_nombre_columna(valor: Any) -> str:
    return (
        str(valor)
        .strip()
        .lower()
        .replace("á", "a")
        .replace("é", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ú", "u")
        .replace("ñ", "n")
        .replace(" ", "_")
    )


def _extraer_oficial_desde_archivo(
    ruta: Path,
    prioridad: int,
) -> pd.DataFrame:
    """
    Reconoce dos estructuras:

    Formato largo:
      fecha | afp | valor_cuota | tipo_fondo

    Formato ancho:
      fecha | Habitat | Integra | Prima | Profuturo
    """
    df = leer_csv(ruta)
    if df.empty:
        return pd.DataFrame()

    # Mapa tolerante a espacios, mayúsculas y tildes.
    columnas_norm = {
        _normalizar_nombre_columna(c): c
        for c in df.columns
    }

    aliases_fecha = (
        "fecha_cuota",
        "fecha",
        "date",
        "fecha_valor_cuota",
        "fecha_de_cuota",
    )
    aliases_afp = (
        "afp",
        "administradora",
        "nombre_afp",
        "nombre_de_afp",
    )
    aliases_cuota = (
        "cuota_sbs",
        "valor_cuota",
        "valor_de_la_cuota",
        "cuota",
        "cuota_oficial",
        "valor",
    )
    aliases_fondo = (
        "fondo",
        "tipo_fondo",
        "tipo_de_fondo",
        "fondo_tipo",
        "numero_fondo",
    )

    c_fecha = next(
        (columnas_norm[x] for x in aliases_fecha if x in columnas_norm),
        None,
    )
    c_afp = next(
        (columnas_norm[x] for x in aliases_afp if x in columnas_norm),
        None,
    )
    c_cuota = next(
        (columnas_norm[x] for x in aliases_cuota if x in columnas_norm),
        None,
    )
    c_fondo = next(
        (columnas_norm[x] for x in aliases_fondo if x in columnas_norm),
        None,
    )

    if c_fecha is None:
        return pd.DataFrame()

    # ----------------------------
    # A. Formato largo
    # ----------------------------
    if c_afp is not None and c_cuota is not None:
        columnas = [c_afp, c_fecha, c_cuota]
        if c_fondo is not None:
            columnas.append(c_fondo)

        x = df[columnas].copy()

        if c_fondo is not None:
            fondo_texto = (
                x[c_fondo]
                .astype(str)
                .str.strip()
                .str.lower()
            )
            mascara_f3 = (
                fondo_texto.str.contains(r"(?:fondo\s*)?3", regex=True, na=False)
                | fondo_texto.eq("3")
                | fondo_texto.eq("3.0")
            )
            if mascara_f3.any():
                x = x.loc[mascara_f3].copy()

        x = x[[c_afp, c_fecha, c_cuota]]
        x.columns = ["afp", "fecha", "cuota_real"]

    # ----------------------------
    # B. Formato ancho
    # ----------------------------
    else:
        columnas_afp: dict[str, str] = {}
        for afp in AFPS:
            afp_norm = _normalizar_nombre_columna(afp)
            candidatos = [
                afp_norm,
                f"cuota_{afp_norm}",
                f"valor_cuota_{afp_norm}",
                f"{afp_norm}_fondo_3",
                f"{afp_norm}_fondo3",
            ]
            encontrada = next(
                (
                    columnas_norm[candidato]
                    for candidato in candidatos
                    if candidato in columnas_norm
                ),
                None,
            )
            if encontrada is not None:
                columnas_afp[afp] = encontrada

        if not columnas_afp:
            return pd.DataFrame()

        partes = []
        for afp, columna in columnas_afp.items():
            z = df[[c_fecha, columna]].copy()
            z.columns = ["fecha", "cuota_real"]
            z["afp"] = afp
            partes.append(z[["afp", "fecha", "cuota_real"]])

        x = pd.concat(partes, ignore_index=True)

    x["afp"] = x["afp"].map(normalizar_afp)
    x["fecha"] = a_fecha(x["fecha"])
    x["cuota_real"] = a_numero(x["cuota_real"])
    x["prioridad_fuente"] = prioridad
    x["fuente"] = ruta.name

    return (
        x.dropna(subset=["afp", "fecha", "cuota_real"])
        .loc[lambda z: z["afp"].isin(AFPS)]
        .loc[lambda z: z["cuota_real"].gt(0)]
        .drop_duplicates(["afp", "fecha"], keep="last")
        .reset_index(drop=True)
    )


def cargar_oficial(processed: Path) -> tuple[pd.DataFrame, str]:
    """
    Carga el histórico completo del valor cuota del Fondo 3.

    No recorta el histórico a 260 observaciones. También combina las fuentes
    conocidas para conservar las fechas antiguas desde 2016.
    """
    data_dir = processed.parent

    candidatos_conocidos = [
        # Histórico completo generado por el módulo 03 (fuente principal).
        processed / "sbs_fondo3_historico_largo.csv",
        processed / "sbs_fondo3_historico_ancho.csv",
        # Fuentes operativas/complementarias.
        processed / "sbs_fondo3_base_maestra.csv",
        processed / "ca0001_modelo80_sbs_oficial_detectado.csv",
        processed / "ca0001_modelo56_base_alineada.csv",
    ]

    # Buscar otras bases históricas del proyecto sin incluir predicciones.
    palabras_excluir = (
        "estimad",
        "pronostic",
        "predic",
        "intradia",
        "snapshot",
        "contribucion",
        "simulador",
        "vela",
    )

    adicionales = []
    for ruta in sorted(data_dir.rglob("*.csv")):
        nombre = ruta.name.lower()
        if ruta in candidatos_conocidos:
            continue
        if any(p in nombre for p in palabras_excluir):
            continue
        if any(p in nombre for p in ("sbs", "cuota", "fondo3", "fondo_3")):
            adicionales.append(ruta)

    candidatos = candidatos_conocidos + adicionales

    partes: list[pd.DataFrame] = []
    fuentes: list[str] = []

    for prioridad, ruta in enumerate(candidatos):
        if not ruta.exists():
            continue
        try:
            x = _extraer_oficial_desde_archivo(ruta, prioridad)
        except Exception as exc:
            print(f"Advertencia: no se pudo revisar {ruta.name}: {exc}")
            continue

        if not x.empty:
            partes.append(x)
            fuentes.append(ruta.name)

    if not partes:
        disponibles = "\n".join(
            f" - {p.name}"
            for p in sorted(data_dir.rglob("*.csv"))[:80]
        )
        raise FileNotFoundError(
            "No encontré una base oficial SBS utilizable.\n\n"
            "Se requiere AFP, fecha y valor cuota, ya sea en formato largo "
            "o con una columna por AFP.\n"
            f"CSV encontrados:\n{disponibles if disponibles else ' - Ninguno'}"
        )

    combinado = pd.concat(partes, ignore_index=True)

    # Para una AFP-fecha prevalece la fuente conocida de mayor prioridad.
    combinado = (
        combinado.sort_values(
            ["afp", "fecha", "prioridad_fuente"],
            ascending=[True, True, True],
        )
        .drop_duplicates(["afp", "fecha"], keep="first")
        .sort_values(["afp", "fecha"])
        .reset_index(drop=True)
    )

    print("\nHISTÓRICO COMPLETO CARGADO")
    advertencia_antiguedad = False

    for afp in AFPS:
        z = combinado[combinado["afp"].eq(afp)]
        if z.empty:
            print(f" - {afp}: sin datos")
            advertencia_antiguedad = True
            continue

        fecha_min = z["fecha"].min()
        fecha_max = z["fecha"].max()
        print(
            f" - {afp}: {len(z):,} valores | "
            f"{fecha_min.date()} a {fecha_max.date()}"
        )

        if fecha_min > pd.Timestamp("2016-12-31"):
            advertencia_antiguedad = True

    if advertencia_antiguedad:
        print(
            "\nADVERTENCIA: alguna AFP no comienza en 2016. "
            "Revise si la base histórica completa está dentro de la carpeta data."
        )

    return (
        combinado[["afp", "fecha", "cuota_real"]],
        ", ".join(dict.fromkeys(fuentes)),
    )


def normalizar_pronosticos(df: pd.DataFrame, fuente: str) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()

    c_afp = buscar_columna(df, ("afp",))
    c_fecha = buscar_columna(df, ("fecha_objetivo", "fecha_estimada", "fecha"))
    c_est = buscar_columna(df, ("cuota_estimada", "valor_cuota_estimado"))
    c_base = buscar_columna(df, ("cuota_ultima_oficial", "cuota_base"))
    c_fecha_base = buscar_columna(df, ("fecha_ultima_cuota_oficial", "fecha_base"))
    c_retorno = buscar_columna(
        df,
        ("retorno_acumulado_estimado_pct", "retorno_acumulado_estimado", "variacion_estimada_pct"),
    )
    c_direccion = buscar_columna(df, ("direccion_estimada", "direccion"))
    c_cobertura = buscar_columna(df, ("cobertura_factores_pct", "cobertura_pct"))
    c_run = buscar_columna(df, ("run_id", "timestamp", "fecha_hora"))

    if not all((c_afp, c_fecha, c_est)):
        return pd.DataFrame()

    x = pd.DataFrame()
    x["afp"] = df[c_afp].map(normalizar_afp)
    x["fecha_objetivo"] = a_fecha(df[c_fecha])
    x["cuota_estimada"] = a_numero(df[c_est])
    x["cuota_base"] = a_numero(df[c_base]) if c_base else np.nan
    x["fecha_base"] = a_fecha(df[c_fecha_base]) if c_fecha_base else pd.NaT
    x["direccion_estimada"] = (
        df[c_direccion].astype(str).str.strip()
        if c_direccion
        else ""
    )
    x["cobertura_pct"] = (
        a_numero(df[c_cobertura]).fillna(0.0)
        if c_cobertura
        else 100.0
    )

    if c_retorno:
        # Las columnas terminadas en "_pct" ya vienen expresadas en porcentaje.
        # No se multiplican por 100 para evitar mostrar 5.86% cuando en realidad
        # el cambio es aproximadamente 0.0586%.
        x["variacion_estimada_pct"] = a_numero(df[c_retorno])
    else:
        x["variacion_estimada_pct"] = np.nan

    x["run_id"] = df[c_run].astype(str) if c_run else ""
    x["fuente"] = fuente

    faltante_variacion = x["variacion_estimada_pct"].isna()
    calculable = faltante_variacion & x["cuota_base"].gt(0)
    x.loc[calculable, "variacion_estimada_pct"] = (
        x.loc[calculable, "cuota_estimada"]
        / x.loc[calculable, "cuota_base"]
        - 1.0
    ) * 100.0

    return (
        x.dropna(subset=["afp", "fecha_objetivo", "cuota_estimada"])
        .loc[lambda z: z["afp"].isin(AFPS)]
        .reset_index(drop=True)
    )


def cargar_pronosticos(processed: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    historico = normalizar_pronosticos(
        leer_csv(processed / "ca0001_modelo79_primer_pronostico_congelado.csv"),
        "PRIMER_PRONOSTICO_CONGELADO",
    )
    snapshot = normalizar_pronosticos(
        leer_csv(processed / "ca0001_modelo79_snapshot_estimacion_actual.csv"),
        "ESTIMACION_ACTUAL",
    )

    if not historico.empty:
        historico = (
            historico.sort_values(["afp", "fecha_objetivo", "run_id"])
            .drop_duplicates(["afp", "fecha_objetivo"], keep="first")
            .reset_index(drop=True)
        )

    if not snapshot.empty:
        snapshot = (
            snapshot.sort_values(["afp", "fecha_objetivo", "run_id"])
            .drop_duplicates(["afp", "fecha_objetivo"], keep="last")
            .reset_index(drop=True)
        )

    return historico, snapshot


def cargar_pronosticos_operativos(processed: Path) -> pd.DataFrame:
    df = leer_csv(processed / "tablero_operativo_bitacora_diaria.csv")
    if df.empty:
        return pd.DataFrame()

    requeridas = {"afp", "fecha", "cuota_estimada"}
    if not requeridas.issubset(df.columns):
        return pd.DataFrame()

    x = pd.DataFrame()
    x["afp"] = df["afp"].map(normalizar_afp)
    x["fecha_objetivo"] = a_fecha(df["fecha"])
    x["cuota_estimada"] = a_numero(df["cuota_estimada"])
    x["cuota_base"] = (
        a_numero(df["cuota_base"])
        if "cuota_base" in df.columns
        else np.nan
    )
    x["fecha_base"] = (
        a_fecha(df["fecha_base_sbs"])
        if "fecha_base_sbs" in df.columns
        else pd.NaT
    )
    x["direccion_estimada"] = (
        df["direccion_estimada"].astype(str).str.strip()
        if "direccion_estimada" in df.columns
        else ""
    )
    x["cobertura_pct"] = 100.0
    x["variacion_estimada_pct"] = (
        a_numero(df["retorno_acumulado_estimado_desde_sbs_pct"])
        if "retorno_acumulado_estimado_desde_sbs_pct" in df.columns
        else np.nan
    )
    x["run_id"] = (
        df["run_id"].astype(str)
        if "run_id" in df.columns
        else "tablero_operativo"
    )
    x["fuente"] = "TABLERO_OPERATIVO"

    return (
        x.dropna(subset=["afp", "fecha_objetivo", "cuota_estimada"])
        .loc[lambda z: z["afp"].isin(AFPS)]
        .sort_values(["afp", "fecha_objetivo", "run_id"])
        .drop_duplicates(["afp", "fecha_objetivo"], keep="last")
        .reset_index(drop=True)
    )



def _columna_por_alias(df: pd.DataFrame, aliases: tuple[str, ...]) -> str | None:
    mapa = {
        _normalizar_nombre_columna(c): c
        for c in df.columns
    }
    for alias in aliases:
        clave = _normalizar_nombre_columna(alias)
        if clave in mapa:
            return mapa[clave]
    return None


def _extraer_serie_modelo_desde_csv(
    ruta: Path,
    oficial: pd.DataFrame,
    prioridad: int,
) -> pd.DataFrame:
    """
    Recupera una serie histórica estimada del modelo.

    Admite dos casos:
    1. El CSV ya contiene valor cuota estimado.
    2. El CSV contiene retorno estimado; en ese caso reconstruye la cuota como
       cuota oficial previa Ã— (1 + retorno estimado).
    """
    df = leer_csv(ruta)
    if df.empty:
        return pd.DataFrame()

    c_tipo_modelo = _columna_por_alias(
        df,
        ("tipo_modelo", "modelo_tipo", "configuracion_modelo"),
    )
    if c_tipo_modelo is not None:
        tipo = df[c_tipo_modelo].astype(str).str.strip().str.upper()
        mascara_final = tipo.eq("CANASTA_PODADA")
        if mascara_final.any():
            df = df.loc[mascara_final].copy()

    c_afp = _columna_por_alias(
        df,
        ("afp", "administradora", "nombre_afp"),
    )
    c_fecha = _columna_por_alias(
        df,
        (
            "fecha_objetivo",
            "fecha_estimada",
            "fecha",
            "date",
            "fecha_cuota",
            "fecha_hoy_simulada",
        ),
    )
    if c_afp is None or c_fecha is None:
        return pd.DataFrame()

    c_cuota_est = _columna_por_alias(
        df,
        (
            "cuota_estimada",
            "valor_cuota_estimado",
            "valor_cuota_estimada",
            "cuota_modelo",
            "cuota_predicha",
            "valor_cuota_predicho",
            "prediccion_cuota",
            "y_pred_cuota",
            "cuota_estimado_modelo",
            "cuota_estimada_hoy",
        ),
    )
    c_cuota_real = _columna_por_alias(
        df,
        (
            "cuota_real",
            "cuota_sbs",
            "valor_cuota",
            "valor_cuota_real",
            "y_true_cuota",
            "cuota_real_hoy",
        ),
    )
    c_retorno_est = _columna_por_alias(
        df,
        (
            "retorno_estimado",
            "retorno_predicho",
            "ret_estimado",
            "ret_predicho",
            "retorno_modelo",
            "prediccion_retorno",
            "retorno_estimado_decimal",
            "retorno_predicho_decimal",
            "retorno_estimado_pct",
            "y_pred",
            "ret_pred",
            "prediccion",
        ),
    )
    c_retorno_real = _columna_por_alias(
        df,
        (
            "retorno_real",
            "ret_real",
            "y_true",
            "retorno_observado",
        ),
    )
    c_base = _columna_por_alias(
        df,
        (
            "cuota_base",
            "cuota_ultima_oficial",
            "valor_cuota_base",
            "cuota_anterior",
        ),
    )

    x = pd.DataFrame()
    x["afp"] = df[c_afp].map(normalizar_afp)
    x["fecha"] = a_fecha(df[c_fecha])

    # Caso A: cuota estimada explícita.
    if c_cuota_est is not None:
        x["cuota_estimada_historica"] = a_numero(df[c_cuota_est])

    # Algunos archivos usan y_pred/y_true tanto para cuota como para retorno.
    elif c_retorno_est is not None:
        pred = a_numero(df[c_retorno_est])
        real_ref = a_numero(df[c_retorno_real]) if c_retorno_real else pd.Series(np.nan, index=df.index)

        pred_mediana = pred.abs().median(skipna=True)
        real_mediana = real_ref.abs().median(skipna=True)

        # Si y_true/y_pred tienen magnitud de cuota, se usan como cuota.
        parece_cuota = (
            pd.notna(pred_mediana)
            and pred_mediana > 1.0
            and (pd.isna(real_mediana) or real_mediana > 1.0)
        )

        if parece_cuota:
            x["cuota_estimada_historica"] = pred
        else:
            retorno = pred.copy()
            nombre_norm = _normalizar_nombre_columna(c_retorno_est)

            # Las columnas con sufijo pct están en porcentaje.
            if "pct" in nombre_norm or "porcentaje" in nombre_norm:
                retorno = retorno / 100.0
            else:
                q95 = retorno.abs().quantile(0.95)
                # Un retorno diario AFP normalmente está en decimales pequeños.
                # Valores como 0.7 o 1.2 suelen ser porcentajes y se convierten.
                if pd.notna(q95) and q95 > 0.20:
                    retorno = retorno / 100.0

            if c_base is not None:
                base = a_numero(df[c_base])
                x["cuota_estimada_historica"] = base * (1.0 + retorno)
            else:
                x["retorno_estimado_decimal"] = retorno
                reconstruidas: list[pd.DataFrame] = []

                for afp in AFPS:
                    z = x[x["afp"].eq(afp)][
                        ["afp", "fecha", "retorno_estimado_decimal"]
                    ].copy()
                    if z.empty:
                        continue

                    o = oficial[oficial["afp"].eq(afp)][
                        ["fecha", "cuota_real"]
                    ].sort_values("fecha").copy()
                    if o.empty:
                        continue

                    z = z.sort_values("fecha")
                    # Para estimar la cuota de t se usa la última cuota real
                    # disponible estrictamente antes de t.
                    unido = pd.merge_asof(
                        z,
                        o.rename(columns={"fecha": "fecha_real_previa"}),
                        left_on="fecha",
                        right_on="fecha_real_previa",
                        direction="backward",
                        allow_exact_matches=False,
                    )
                    unido["cuota_estimada_historica"] = (
                        unido["cuota_real"]
                        * (1.0 + unido["retorno_estimado_decimal"])
                    )
                    reconstruidas.append(
                        unido[["afp", "fecha", "cuota_estimada_historica"]]
                    )

                if not reconstruidas:
                    return pd.DataFrame()
                x = pd.concat(reconstruidas, ignore_index=True)
    else:
        return pd.DataFrame()

    x["prioridad_modelo"] = prioridad
    x["fuente_modelo"] = ruta.name

    return (
        x.dropna(subset=["afp", "fecha", "cuota_estimada_historica"])
        .loc[lambda z: z["afp"].isin(AFPS)]
        .loc[lambda z: z["cuota_estimada_historica"].gt(0)]
        .drop_duplicates(["afp", "fecha"], keep="last")
        .sort_values(["afp", "fecha"])
        .reset_index(drop=True)
    )


def cargar_serie_historica_modelo(
    processed: Path,
    oficial: pd.DataFrame,
    pronosticos_congelados: pd.DataFrame,
) -> tuple[pd.DataFrame, str]:
    """
    Busca la línea histórica del modelo producida por el backtest / módulo 79A.

    No inventa estimaciones. Si no existe un archivo de backtest utilizable,
    usa únicamente los pronósticos congelados realmente guardados.
    """
    nombres_prioritarios = [
        "ca0001_modelo78_simulacion_publicacion_5d.csv",
        "ca0001_modelo56_simulacion_publicacion_5d.csv",
        "ca0001_modelo79a_serie_real_vs_estimada.csv",
        "ca0001_modelo79a_real_vs_estimado.csv",
        "ca0001_modelo79a_historico_real_estimado.csv",
        "ca0001_modelo79a_predicciones_historicas.csv",
        "ca0001_modelo79a_backtest.csv",
        "ca0001_modelo79_predicciones_test.csv",
        "ca0001_modelo78_backtest_canasta_final.csv",
    ]

    candidatos: list[Path] = []
    vistos: set[Path] = set()

    for nombre in nombres_prioritarios:
        ruta = processed / nombre
        if ruta.exists() and ruta not in vistos:
            candidatos.append(ruta)
            vistos.add(ruta)

    excluir = (
        "snapshot",
        "primer_pronostico",
        "contribucion",
        "parametro",
        "correlacion",
        "canasta_final_podada",
        "estimacion_actual",
    )
    incluir = (
        "79a",
        "backtest",
        "real_vs_estim",
        "historico_estim",
        "predicciones_test",
        "prediccion_historica",
        "simulacion_publicacion_5d",
    )

    for ruta in sorted(processed.glob("*.csv")):
        nombre = ruta.name.lower()
        if ruta in vistos:
            continue
        if any(token in nombre for token in excluir):
            continue
        if any(token in nombre for token in incluir):
            candidatos.append(ruta)
            vistos.add(ruta)

    partes: list[pd.DataFrame] = []
    fuentes: list[str] = []

    for prioridad, ruta in enumerate(candidatos):
        try:
            x = _extraer_serie_modelo_desde_csv(
                ruta,
                oficial,
                prioridad,
            )
        except Exception as exc:
            print(
                f"Advertencia: no se pudo interpretar la serie histórica "
                f"del modelo en {ruta.name}: {exc}"
            )
            continue

        if not x.empty:
            partes.append(x)
            fuentes.append(ruta.name)

    if partes:
        combinado = (
            pd.concat(partes, ignore_index=True)
            .sort_values(
                ["afp", "fecha", "prioridad_modelo"],
                ascending=[True, True, True],
            )
            .drop_duplicates(["afp", "fecha"], keep="first")
            .sort_values(["afp", "fecha"])
            .reset_index(drop=True)
        )
        fuente = ", ".join(dict.fromkeys(fuentes))
    else:
        # Respaldo honesto: solo los pronósticos prospectivos que sí fueron
        # congelados antes de conocer la cuota SBS.
        if pronosticos_congelados.empty:
            return pd.DataFrame(), "No encontrada"

        combinado = pronosticos_congelados[
            ["afp", "fecha_objetivo", "cuota_estimada"]
        ].copy()
        combinado.columns = ["afp", "fecha", "cuota_estimada_historica"]
        combinado["prioridad_modelo"] = 999
        combinado["fuente_modelo"] = "pronósticos congelados disponibles"
        combinado = (
            combinado.dropna()
            .drop_duplicates(["afp", "fecha"], keep="first")
            .sort_values(["afp", "fecha"])
            .reset_index(drop=True)
        )
        fuente = "pronósticos congelados disponibles"

    print("\nSERIE HISTÓRICA DEL MODELO")
    for afp in AFPS:
        z = combinado[combinado["afp"].eq(afp)]
        if z.empty:
            print(f" - {afp}: sin estimaciones históricas")
        else:
            print(
                f" - {afp}: {len(z):,} estimaciones | "
                f"{z['fecha'].min().date()} a {z['fecha'].max().date()}"
            )

    return combinado, fuente

def cargar_intradia(processed: Path) -> pd.DataFrame:
    ruta = processed / "ca0001_modelo99_historial_intradia_cuota.csv"
    df = leer_csv(ruta)
    requeridas = {"afp", "timestamp", "fecha_objetivo", "cuota_estimada_intradia"}
    if df.empty or not requeridas.issubset(df.columns):
        return pd.DataFrame()

    x = df.copy()
    x["afp"] = x["afp"].map(normalizar_afp)
    x["timestamp"] = pd.to_datetime(x["timestamp"], errors="coerce")
    x["fecha_objetivo"] = a_fecha(x["fecha_objetivo"])
    x["cuota_estimada_intradia"] = a_numero(x["cuota_estimada_intradia"])
    if "cobertura_pct" in x.columns:
        x["cobertura_pct"] = a_numero(x["cobertura_pct"])
    else:
        x["cobertura_pct"] = 100.0

    return (
        x.dropna(subset=["afp", "timestamp", "fecha_objetivo", "cuota_estimada_intradia"])
        .loc[lambda z: z["afp"].isin(AFPS)]
        .loc[lambda z: z["cuota_estimada_intradia"].gt(0)]
        .sort_values(["afp", "timestamp"])
        .reset_index(drop=True)
    )


def construir_vela_intradia(afp: str, intradia: pd.DataFrame) -> dict[str, Any] | None:
    if intradia.empty:
        return None

    z = intradia[intradia["afp"].eq(afp)].copy()
    if z.empty:
        return None

    z = z[z["cobertura_pct"].ge(COBERTURA_MINIMA)].copy()
    if z.empty:
        return None

    z["fecha_guardado"] = z["timestamp"].dt.normalize()
    ultima_fecha = z["fecha_guardado"].max()
    z = z[z["fecha_guardado"].eq(ultima_fecha)].sort_values("timestamp").copy()
    if z.empty:
        return None

    valores = z["cuota_estimada_intradia"]
    apertura = float(valores.iloc[0])
    maximo = float(valores.max())
    minimo = float(valores.min())
    cierre = float(valores.iloc[-1])
    z["hora_bloque"] = z["timestamp"].dt.floor("h")

    velas_horarias = []
    for hora, grupo in z.groupby("hora_bloque", sort=True):
        valores_hora = grupo["cuota_estimada_intradia"].astype(float)
        velas_horarias.append(
            {
                "hora": pd.Timestamp(hora).strftime("%H:%M"),
                "apertura": float(valores_hora.iloc[0]),
                "maximo": float(valores_hora.max()),
                "minimo": float(valores_hora.min()),
                "cierre": float(valores_hora.iloc[-1]),
                "n": int(len(valores_hora)),
            }
        )

    return {
        "fecha_guardado": fecha_texto(ultima_fecha),
        "fecha_objetivo": fecha_texto(z["fecha_objetivo"].iloc[-1]),
        "apertura": apertura,
        "maximo": maximo,
        "minimo": minimo,
        "cierre": cierre,
        "n_estimaciones": int(len(z)),
        "primer_registro": z["timestamp"].iloc[0].strftime("%H:%M:%S"),
        "ultimo_registro": z["timestamp"].iloc[-1].strftime("%H:%M:%S"),
        "variacion_pct": (cierre / apertura - 1.0) * 100.0 if apertura else None,
        "velas_horarias": velas_horarias,
        "serie": [
            {
                "hora": fila["timestamp"].strftime("%H:%M:%S"),
                "cuota": float(fila["cuota_estimada_intradia"]),
            }
            for _, fila in z.iterrows()
        ],
    }

def cargar_contribuciones(processed: Path) -> pd.DataFrame:
    ruta = processed / "ca0001_modelo79c_contribuciones_ultima_fecha.csv"
    df = leer_csv(ruta)
    requeridas = {
        "afp",
        "fecha_objetivo",
        "factor",
        "lag",
        "retorno_factor_decimal",
        "contribucion_al_retorno_estimado",
    }
    if df.empty or not requeridas.issubset(df.columns):
        return pd.DataFrame()

    x = df.copy()
    x["afp"] = x["afp"].map(normalizar_afp)
    x["fecha_objetivo"] = a_fecha(x["fecha_objetivo"])
    x["factor"] = x["factor"].astype(str)
    x["lag"] = a_numero(x["lag"]).fillna(0).astype(int)
    x["retorno_factor_pct"] = a_numero(x["retorno_factor_decimal"]) * 100.0
    x["aporte_pp"] = a_numero(x["contribucion_al_retorno_estimado"]) * 100.0
    x = x[
        x["afp"].isin(AFPS)
        & x["factor"].ne("INTERCEPTO")
        & x["aporte_pp"].notna()
    ].copy()
    return x.sort_values(["afp", "fecha_objetivo"]).reset_index(drop=True)


def cargar_metricas(processed: Path) -> dict[str, dict[str, float]]:
    salida = {
        afp: {
            "mape_historico": MAPE_HISTORICO[afp],
            "direccion_historica": DIRECCION_HISTORICA[afp],
        }
        for afp in AFPS
    }

    df = leer_csv(processed / "ca0001_modelo79a_correlaciones_finales.csv")
    if df.empty or "afp" not in df.columns:
        return salida

    for _, fila in df.iterrows():
        afp = normalizar_afp(fila.get("afp", ""))
        if afp not in salida:
            continue
        mape = pd.to_numeric(fila.get("mape_cuota_pct", np.nan), errors="coerce")
        direccion = pd.to_numeric(
            fila.get("direccion_acumulada_pct", np.nan),
            errors="coerce",
        )
        if pd.notna(mape):
            salida[afp]["mape_historico"] = float(mape)
        if pd.notna(direccion):
            salida[afp]["direccion_historica"] = float(direccion)

    return salida


def encontrar_actual(
    afp: str,
    snapshot: pd.DataFrame,
    historico: pd.DataFrame,
) -> pd.Series | None:
    candidatos = snapshot[snapshot["afp"].eq(afp)] if not snapshot.empty else pd.DataFrame()
    if candidatos.empty and not historico.empty:
        candidatos = historico[historico["afp"].eq(afp)]
    if candidatos.empty:
        return None
    return candidatos.sort_values(["fecha_objetivo", "run_id"]).iloc[-1]


def construir_validacion(
    afp: str,
    oficial: pd.DataFrame,
    historico: pd.DataFrame,
) -> pd.DataFrame:
    if historico.empty:
        return pd.DataFrame()

    p = historico[
        historico["afp"].eq(afp)
        & historico["cobertura_pct"].ge(COBERTURA_MINIMA)
    ].copy()
    o = oficial[oficial["afp"].eq(afp)][["fecha", "cuota_real"]].copy()

    if p.empty or o.empty:
        return pd.DataFrame()

    x = p.merge(
        o,
        left_on="fecha_objetivo",
        right_on="fecha",
        how="inner",
    )
    if x.empty:
        return x

    if x["cuota_base"].isna().any():
        mapa = o.set_index("fecha")["cuota_real"]
        faltantes = x["cuota_base"].isna()
        x.loc[faltantes, "cuota_base"] = x.loc[faltantes, "fecha_base"].map(mapa)

    x = x[x["cuota_base"].gt(0)].copy()
    if x.empty:
        return x

    x["error_pct"] = (x["cuota_estimada"] / x["cuota_real"] - 1.0) * 100.0
    x["error_abs_pct"] = x["error_pct"].abs()
    x["cambio_estimado_pct"] = (
        x["cuota_estimada"] / x["cuota_base"] - 1.0
    ) * 100.0
    x["cambio_real_pct"] = (
        x["cuota_real"] / x["cuota_base"] - 1.0
    ) * 100.0
    x["direccion_correcta"] = (
        np.sign(x["cambio_estimado_pct"].fillna(0.0))
        == np.sign(x["cambio_real_pct"].fillna(0.0))
    )

    return x.sort_values("fecha_objetivo").reset_index(drop=True)


def numero_o_none(valor: Any) -> float | None:
    try:
        n = float(valor)
        if math.isfinite(n):
            return n
    except Exception:
        pass
    return None


def fecha_texto(valor: Any) -> str | None:
    if valor is None or pd.isna(valor):
        return None
    return pd.Timestamp(valor).strftime("%Y-%m-%d")


def ultimo_dia_habil_hasta_hoy() -> pd.Timestamp:
    hoy = pd.Timestamp.now().normalize()
    while hoy.weekday() >= 5:
        hoy -= pd.Timedelta(days=1)
    return hoy


def dias_habiles_esperados(inicio_exclusivo: Any, fin_inclusivo: Any) -> list[pd.Timestamp]:
    inicio = pd.to_datetime(inicio_exclusivo, errors="coerce")
    fin = pd.to_datetime(fin_inclusivo, errors="coerce")
    if pd.isna(inicio) or pd.isna(fin) or fin <= inicio:
        return []
    dias = pd.bdate_range(inicio + pd.offsets.BDay(1), fin)
    return [pd.Timestamp(d).normalize() for d in dias]


def construir_modelo_proyectado(
    historico_modelo_afp: pd.DataFrame,
    pronosticos_afp: pd.DataFrame,
    ultimo_real: pd.Series | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if ultimo_real is None:
        return [], {
            "fecha_inicio": None,
            "fecha_fin": None,
            "fechas_habiles_esperadas": [],
            "fechas_habiles_cubiertas": [],
            "fechas_habiles_faltantes": [],
        }

    fecha_real = pd.Timestamp(ultimo_real["fecha"]).normalize()
    fin_esperado = max(fecha_real, ultimo_dia_habil_hasta_hoy())

    mh = historico_modelo_afp.copy()
    fecha_fin_historico = pd.NaT
    if not mh.empty:
        mh["fecha"] = a_fecha(mh["fecha"])
        mh = mh.dropna(subset=["fecha", "cuota_estimada_historica"])
        mh = mh[mh["fecha"].le(fecha_real)]
        if not mh.empty:
            fecha_fin_historico = mh["fecha"].max()
        mh = mh[["fecha", "cuota_estimada_historica"]].rename(
            columns={"cuota_estimada_historica": "cuota"}
        )
        mh["tipo"] = "historico"
    inicio_pronosticos = fecha_fin_historico if pd.notna(fecha_fin_historico) else fecha_real

    futuros = pronosticos_afp.copy()
    if not futuros.empty:
        futuros["fecha_objetivo"] = a_fecha(futuros["fecha_objetivo"])
        futuros["cuota_estimada"] = a_numero(futuros["cuota_estimada"])
        futuros = futuros.dropna(subset=["fecha_objetivo", "cuota_estimada"])
        futuros = futuros[
            futuros["fecha_objetivo"].gt(inicio_pronosticos)
            & futuros["fecha_objetivo"].le(fin_esperado)
            & futuros["cobertura_pct"].ge(COBERTURA_MINIMA)
        ]
        futuros = (
            futuros.sort_values(["fecha_objetivo", "run_id"])
            .drop_duplicates(["fecha_objetivo"], keep="last")
            [["fecha_objetivo", "cuota_estimada"]]
            .rename(columns={"fecha_objetivo": "fecha", "cuota_estimada": "cuota"})
        )
        futuros["tipo"] = np.where(
            futuros["fecha"].le(fecha_real),
            "pronostico_evaluado",
            "proyeccion",
        )
    else:
        futuros = pd.DataFrame(columns=["fecha", "cuota", "tipo"])

    partes = [x for x in (mh, futuros) if not x.empty]
    combinado = (
        pd.concat(partes, ignore_index=True)
        if partes
        else pd.DataFrame(columns=["fecha", "cuota", "tipo"])
    )
    if not combinado.empty:
        combinado = (
            combinado.sort_values(["fecha", "tipo"])
            .drop_duplicates(["fecha"], keep="last")
            .sort_values("fecha")
        )

    esperadas = dias_habiles_esperados(fecha_real, fin_esperado)
    cubiertas = set(
        a_fecha(
            futuros.get("fecha", pd.Series(dtype="datetime64[ns]")),
        )
        .dropna()
    )
    faltantes = [d for d in esperadas if d not in cubiertas]

    auditoria = {
        "fecha_inicio": fecha_texto(combinado["fecha"].min()) if not combinado.empty else None,
        "fecha_fin": fecha_texto(combinado["fecha"].max()) if not combinado.empty else None,
        "fecha_ultima_sbs": fecha_texto(fecha_real),
        "fecha_habil_objetivo": fecha_texto(fin_esperado),
        "fechas_habiles_esperadas": [fecha_texto(d) for d in esperadas],
        "fechas_habiles_cubiertas": [fecha_texto(d) for d in sorted(cubiertas)],
        "fechas_habiles_faltantes": [fecha_texto(d) for d in faltantes],
    }

    serie = [
        {
            "fecha": fecha_texto(row["fecha"]),
            "cuota": float(row["cuota"]),
            "tipo": str(row["tipo"]),
        }
        for _, row in combinado.iterrows()
    ]
    return serie, auditoria



def cargar_estado_canasta(processed: Path) -> dict[str, Any]:
    ruta = processed / "ca0001_modelo78_canasta_final_podada.csv"
    df = leer_csv(ruta)

    if df.empty:
        return {
            "activa": False,
            "archivo": ruta.name,
            "factores": 0,
            "afps": 0,
        }

    c_afp = buscar_columna(df, ("afp",))
    c_factor = buscar_columna(df, ("factor", "feature", "variable"))

    factores = (
        int(df[c_factor].astype(str).nunique())
        if c_factor is not None
        else int(len(df))
    )
    afps = (
        int(df[c_afp].map(normalizar_afp).nunique())
        if c_afp is not None
        else 0
    )

    return {
        "activa": True,
        "archivo": ruta.name,
        "factores": factores,
        "afps": afps,
    }


def construir_payload(
    oficial: pd.DataFrame,
    historico: pd.DataFrame,
    snapshot: pd.DataFrame,
    operativo: pd.DataFrame,
    contribuciones: pd.DataFrame,
    metricas: dict[str, dict[str, float]],
    fuente_oficial: str,
    estado_canasta: dict[str, Any],
    historico_modelo: pd.DataFrame,
    fuente_historico_modelo: str,
    intradia: pd.DataFrame,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "actualizado": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "fuente_oficial": fuente_oficial,
        "canasta": estado_canasta,
        "afps": {},
    }

    for afp in AFPS:
        o = oficial[oficial["afp"].eq(afp)].sort_values("fecha").copy()
        ultimo_real = o.iloc[-1] if not o.empty else None
        actual = encontrar_actual(afp, snapshot, historico)

        actual_dict: dict[str, Any] | None = None
        if actual is not None:
            fecha_obj = pd.Timestamp(actual["fecha_objetivo"])
            real_obj = o[o["fecha"].eq(fecha_obj)]
            cuota_real_obj = (
                float(real_obj["cuota_real"].iloc[-1])
                if not real_obj.empty
                else None
            )
            cuota_est = float(actual["cuota_estimada"])
            cuota_base = numero_o_none(actual.get("cuota_base", np.nan))
            if cuota_base is None and ultimo_real is not None:
                cuota_base = float(ultimo_real["cuota_real"])

            # La variación visible se calcula directamente con las cuotas.
            # Es la forma más segura de evitar errores de escala en archivos antiguos.
            variacion = None
            if cuota_base and cuota_base > 0:
                variacion = (cuota_est / cuota_base - 1.0) * 100.0
            if variacion is None:
                variacion = numero_o_none(
                    actual.get("variacion_estimada_pct", np.nan)
                )

            direccion = str(actual.get("direccion_estimada", "")).strip().upper()
            if not direccion or direccion in {"NAN", "NONE"}:
                direccion = "SUBE" if (variacion or 0.0) >= 0 else "BAJA"
            elif "ALZA" in direccion or "SUB" in direccion or "POSIT" in direccion:
                direccion = "SUBE"
            elif "BAJ" in direccion or "NEGAT" in direccion:
                direccion = "BAJA"

            estado = "ESPERANDO SBS"
            error_pct = None
            if cuota_real_obj is not None:
                estado = "SBS YA PUBLICÓ"
                error_pct = (cuota_est / cuota_real_obj - 1.0) * 100.0

            actual_dict = {
                "fecha_objetivo": fecha_texto(fecha_obj),
                "cuota_estimada": cuota_est,
                "cuota_base": cuota_base,
                "fecha_base": fecha_texto(actual.get("fecha_base", pd.NaT)),
                "variacion_estimada_pct": variacion,
                "direccion": direccion,
                "cobertura_pct": numero_o_none(actual.get("cobertura_pct", np.nan)),
                "estado": estado,
                "cuota_real_objetivo": cuota_real_obj,
                "error_pct": error_pct,
            }

        partes_pronostico = []
        if not historico.empty:
            partes_pronostico.append(
                historico[
                    historico["afp"].eq(afp)
                    & historico["cobertura_pct"].ge(COBERTURA_MINIMA)
                ].copy()
            )
        if not operativo.empty:
            partes_pronostico.append(
                operativo[
                    operativo["afp"].eq(afp)
                    & operativo["cobertura_pct"].ge(COBERTURA_MINIMA)
                ].copy()
            )
        p = (
            pd.concat(partes_pronostico, ignore_index=True, sort=False)
            if partes_pronostico
            else pd.DataFrame()
        )
        if actual is not None:
            p = pd.concat([p, pd.DataFrame([actual])], ignore_index=True)
        if not p.empty:
            p = (
                p.sort_values(["fecha_objetivo", "run_id"])
                .drop_duplicates(["fecha_objetivo"], keep="last")
                .tail(180)
            )

        factores_afp = contribuciones[contribuciones["afp"].eq(afp)].copy()
        if not factores_afp.empty:
            ultima_fecha = factores_afp["fecha_objetivo"].max()
            factores_afp = factores_afp[
                factores_afp["fecha_objetivo"].eq(ultima_fecha)
            ].copy()
            factores_afp["abs_aporte"] = factores_afp["aporte_pp"].abs()
            factores_afp = factores_afp.sort_values("abs_aporte", ascending=False)

        mh = historico_modelo[
            historico_modelo["afp"].eq(afp)
        ].sort_values("fecha").copy() if not historico_modelo.empty else pd.DataFrame()
        modelo_proyectado, auditoria_modelo_proyectado = construir_modelo_proyectado(
            mh,
            p,
            ultimo_real,
        )

        validacion = construir_validacion(afp, oficial, historico)
        validacion_reciente = validacion.tail(30).copy()
        vela_intradia = construir_vela_intradia(afp, intradia)

        mape_prospectivo = None
        direccion_prospectiva = None
        if not validacion.empty:
            mape_prospectivo = float(validacion["error_abs_pct"].mean())
            direccion_prospectiva = float(validacion["direccion_correcta"].mean() * 100.0)

        payload["afps"][afp] = {
            "historico_resumen": {
                "fecha_inicio": fecha_texto(o["fecha"].min()) if not o.empty else None,
                "fecha_fin": fecha_texto(o["fecha"].max()) if not o.empty else None,
                "n_valores": int(len(o)),
            },
            "oficial": [
                {"fecha": fecha_texto(f), "cuota": float(q)}
                for f, q in zip(o["fecha"], o["cuota_real"])
            ],
            "ultimo_oficial": (
                {
                    "fecha": fecha_texto(ultimo_real["fecha"]),
                    "cuota": float(ultimo_real["cuota_real"]),
                }
                if ultimo_real is not None
                else None
            ),
            "actual": actual_dict,
            "vela_intradia": vela_intradia,
            "modelo_historico": [
                {
                    "fecha": fecha_texto(fila["fecha"]),
                    "cuota": float(fila["cuota_estimada_historica"]),
                }
                for _, fila in mh.iterrows()
            ] if not mh.empty else [],
            "modelo_historico_resumen": {
                "fuente": fuente_historico_modelo,
                "n_estimaciones": int(len(mh)),
                "fecha_inicio": fecha_texto(mh["fecha"].min()) if not mh.empty else None,
                "fecha_fin": fecha_texto(mh["fecha"].max()) if not mh.empty else None,
            },
            "modelo_proyectado": modelo_proyectado,
            "modelo_proyectado_resumen": auditoria_modelo_proyectado,
            "pronosticos": [
                {
                    "fecha": fecha_texto(fila["fecha_objetivo"]),
                    "cuota": float(fila["cuota_estimada"]),
                    "cobertura": numero_o_none(fila.get("cobertura_pct", np.nan)),
                }
                for _, fila in p.iterrows()
            ] if not p.empty else [],
            "factores": [
                {
                    "factor": str(fila["factor"]),
                    "nombre": NOMBRES_FACTORES.get(
                        str(fila["factor"]),
                        str(fila["factor"]).replace("ret_", "").replace("_", " "),
                    ),
                    "ticker": str(fila.get("ticker", "") or ""),
                    "lag": int(fila["lag"]),
                    "retorno_factor_pct": numero_o_none(fila["retorno_factor_pct"]),
                    "aporte_pp": float(fila["aporte_pp"]),
                    "efecto": "EMPUJA HACIA ARRIBA" if fila["aporte_pp"] >= 0 else "EMPUJA HACIA ABAJO",
                }
                for _, fila in factores_afp.iterrows()
            ],
            "fecha_factores": (
                fecha_texto(factores_afp["fecha_objetivo"].iloc[0])
                if not factores_afp.empty
                else None
            ),
            "modelo": PARAMETROS_MODELO[afp],
            "metricas": {
                "mape_historico": metricas[afp]["mape_historico"],
                "direccion_historica": metricas[afp]["direccion_historica"],
                "n_validaciones_reales": int(len(validacion)),
                "mape_prospectivo": mape_prospectivo,
                "direccion_prospectiva": direccion_prospectiva,
            },
            "validacion": [
                {
                    "fecha": fecha_texto(fila["fecha_objetivo"]),
                    "estimado": float(fila["cuota_estimada"]),
                    "real": float(fila["cuota_real"]),
                    "error_pct": float(fila["error_pct"]),
                    "direccion_correcta": bool(fila["direccion_correcta"]),
                }
                for _, fila in validacion_reciente.iterrows()
            ],
        }

    return payload


def crear_html(processed: Path, payload: dict[str, Any]) -> Path:
    salida = processed / "ca0001_monitor_fondo3_actualizado.html"
    datos = json.dumps(payload, ensure_ascii=False)

    def fmt_numero_html(valor: Any, decimales: int = 6) -> str:
        try:
            numero = float(valor)
            if not math.isfinite(numero):
                return "Sin dato"
            return f"{numero:.{decimales}f}"
        except Exception:
            return "Sin dato"

    tarjetas: list[str] = []
    for afp in AFPS:
        d = payload["afps"].get(afp, {})
        real = d.get("ultimo_oficial") or {}
        actual = d.get("actual") or {}
        metricas_afp = d.get("metricas") or {}
        direccion = str(actual.get("direccion") or "SIN PRONÓSTICO")
        clase = (
            "sube"
            if direccion == "SUBE"
            else ("baja" if direccion == "BAJA" else "neutro")
        )
        flecha = (
            "↑"
            if direccion == "SUBE"
            else ("↓" if direccion == "BAJA" else "—")
        )
        variacion = actual.get("variacion_estimada_pct")
        variacion_texto = (
            f"{float(variacion):+.3f}%"
            if variacion is not None
            else "Sin estimación"
        )
        mape = metricas_afp.get("mape_historico")
        direccion_hist = metricas_afp.get("direccion_historica")
        rango = d.get("historico_resumen") or {}

        mape_texto = (
            f"±{float(mape):.3f}%"
            if mape is not None
            else "Sin dato"
        )
        direccion_hist_texto = (
            f"{float(direccion_hist):.1f}%"
            if direccion_hist is not None
            else "Sin dato"
        )

        tarjetas.append(
            f"""
            <article class="tarjeta">
              <h2>{afp}</h2>
              <div class="dato"><span>Última cuota SBS</span><strong>{fmt_numero_html(real.get("cuota"))}</strong></div>
              <div class="dato"><span>Fecha oficial</span><strong>{real.get("fecha") or "Sin dato"}</strong></div>
              <div class="dato"><span>Cuota estimada</span><strong>{fmt_numero_html(actual.get("cuota_estimada"))}</strong></div>
              <div class="dato"><span>Fecha objetivo</span><strong>{actual.get("fecha_objetivo") or "Sin pronóstico"}</strong></div>
              <div class="senal {clase}">
                <span class="flecha">{flecha}</span>
                <strong>{direccion}</strong><br>
                <span>{variacion_texto}</span>
              </div>
              <div class="dato"><span>Error histórico medio</span><strong>{mape_texto}</strong></div>
              <div class="dato"><span>Dirección histórica correcta</span><strong>{direccion_hist_texto}</strong></div>
              <div class="dato"><span>Histórico cargado</span><strong>{rango.get("fecha_inicio") or "?"} a {rango.get("fecha_fin") or "?"}</strong></div>
              <div class="estado">{actual.get("estado") or "SIN PRONÓSTICO"}</div>
            </article>
            """
        )

    tarjetas_hoy_html = "\n".join(tarjetas)


    html = r"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Type" content="text/html; charset=utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Monitor práctico AFP Fondo 3</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
:root{
  --azul:#123f73;
  --azul2:#2b6fb4;
  --fondo:#f3f6fb;
  --borde:#d7e2ef;
  --texto:#1f2937;
  --suave:#64748b;
  --verde:#0f8a46;
  --rojo:#c6283d;
  --naranja:#ef6c3e;
  --amarillo:#fff6cf;
}
*{box-sizing:border-box}
body{
  margin:0;
  background:var(--fondo);
  color:var(--texto);
  font-family:Arial,Helvetica,sans-serif;
}
main{
  width:min(1480px,96%);
  margin:auto;
  padding:18px 0 42px;
}
header{
  background:linear-gradient(135deg,var(--azul),var(--azul2));
  color:white;
  padding:20px 25px;
  border-radius:15px;
}
header h1{margin:0 0 6px;font-size:27px}
header p{margin:4px 0;line-height:1.4}
.actualizacion{font-size:12px;opacity:.9}
.nav{
  display:grid;
  grid-template-columns:repeat(4,1fr);
  gap:9px;
  margin:14px 0;
}
.nav button{
  border:1px solid var(--borde);
  background:white;
  color:var(--azul);
  padding:12px 8px;
  border-radius:10px;
  font-weight:bold;
  cursor:pointer;
  font-size:15px;
}
.nav button.activo{color:white;background:var(--azul)}
.vista{display:none}
.vista.activa{display:block}
.aviso{
  background:var(--amarillo);
  border-left:6px solid #d2a400;
  border-radius:10px;
  padding:11px 14px;
  margin-bottom:13px;
  line-height:1.45;
}
.grid-afp{
  display:grid;
  grid-template-columns:repeat(4,minmax(220px,1fr));
  gap:11px;
}
.tarjeta,.bloque,.mini,.control,.resultado{
  background:white;
  border:1px solid var(--borde);
  border-radius:13px;
}
.tarjeta{padding:15px}
.tarjeta h2{margin:0 0 10px;color:var(--azul);font-size:21px}
.dato{
  display:flex;
  justify-content:space-between;
  gap:8px;
  padding:6px 0;
  border-bottom:1px solid #edf2f7;
  font-size:13px;
}
.dato span{color:var(--suave)}
.dato strong{text-align:right}
.senal{
  margin-top:12px;
  border-radius:10px;
  padding:11px;
  text-align:center;
}
.sube{background:#e9f7ef;color:var(--verde)}
.baja{background:#fdecef;color:var(--rojo)}
.neutro{background:#eef3f8;color:var(--azul)}
.senal .flecha{display:block;font-size:29px;font-weight:bold}
.estado{
  margin-top:9px;
  border-radius:8px;
  padding:7px;
  font-size:11px;
  font-weight:bold;
  text-align:center;
  background:#eef3f8;
  color:var(--azul);
}
.selector{
  display:flex;
  gap:8px;
  flex-wrap:wrap;
  margin-bottom:11px;
}
.selector button{
  border:1px solid var(--borde);
  background:white;
  color:var(--azul);
  padding:8px 12px;
  border-radius:8px;
  font-weight:bold;
  cursor:pointer;
}
.selector button.activo{background:var(--azul);color:white}
.resumen-linea{
  display:grid;
  grid-template-columns:repeat(4,1fr);
  gap:9px;
  margin-bottom:11px;
}
.mini{padding:11px}
.mini span{display:block;color:var(--suave);font-size:12px;margin-bottom:4px}
.mini strong{color:var(--azul);font-size:17px}
.bloque{padding:12px;overflow:hidden}
.explicacion-modelo{
  display:grid;
  grid-template-columns:1.15fr 1fr 1.35fr;
  gap:11px;
  margin-top:12px;
}
.explicacion-card{
  background:white;
  border:1px solid var(--borde);
  border-radius:13px;
  padding:14px;
  line-height:1.45;
}
.explicacion-card h3{
  margin:0 0 9px;
  color:var(--azul);
  font-size:16px;
}
.formula-simple{
  background:#eef5ff;
  border-left:5px solid var(--azul2);
  border-radius:8px;
  padding:10px;
  font-size:14px;
  margin-top:8px;
}
.rango-estimado{
  font-size:21px;
  color:var(--azul);
  font-weight:bold;
  margin:8px 0;
}
.lista-factores{
  margin:7px 0 0;
  padding-left:18px;
  font-size:13px;
}
.etiqueta-metodo{
  display:inline-block;
  border-radius:999px;
  padding:4px 8px;
  margin:2px 4px 2px 0;
  background:#eef3f8;
  color:var(--azul);
  font-size:12px;
  font-weight:bold;
}
.estimador-visible{
  display:grid;
  grid-template-columns:repeat(5,1fr);
  gap:9px;
  margin:0 0 11px;
}
.estimador-celda{
  background:white;
  border:1px solid var(--borde);
  border-radius:11px;
  padding:11px;
}
.estimador-celda span{
  display:block;
  color:var(--suave);
  font-size:12px;
  margin-bottom:4px;
}
.estimador-celda strong{
  display:block;
  color:var(--azul);
  font-size:18px;
}
.estimador-celda.destacado{
  background:#fff2e9;
  border:2px solid var(--naranja);
}
.estimador-celda.destacado strong{
  color:#b84c24;
  font-size:22px;
}
.estimador-celda.rango{
  background:#fff8d8;
  border-color:#d2a400;
}
.grafico{
  width:100%;
  height:470px;
  min-height:470px;
}
.dos-columnas{
  display:grid;
  grid-template-columns:minmax(0,1.45fr) minmax(330px,.8fr);
  gap:12px;
}
table{width:100%;border-collapse:collapse}
th,td{
  padding:8px 6px;
  border-bottom:1px solid #e9eef5;
  text-align:left;
  font-size:13px;
}
th{color:var(--azul);background:#f7f9fc}
.num{text-align:right}
.positivo{color:var(--verde);font-weight:bold}
.negativo{color:var(--rojo);font-weight:bold}
.nota{font-size:12px;color:var(--suave);line-height:1.45;margin-top:9px}
.sin-datos{padding:25px 12px;text-align:center;color:var(--suave)}
.controles-simulador{
  display:grid;
  grid-template-columns:1fr 1fr 1fr 1fr;
  gap:11px;
  margin-bottom:12px;
}
.control{padding:13px}
.control label{
  display:block;
  color:var(--azul);
  font-weight:bold;
  font-size:13px;
  margin-bottom:7px;
}
.control input,.control select{
  width:100%;
  padding:10px;
  border:1px solid var(--borde);
  border-radius:8px;
  font-size:16px;
  background:white;
}
.resultados-simulador{
  display:grid;
  grid-template-columns:repeat(6,1fr);
  gap:9px;
  margin-bottom:12px;
}
.resultado{padding:13px}
.resultado span{display:block;color:var(--suave);font-size:12px;margin-bottom:5px}
.resultado strong{display:block;color:var(--azul);font-size:19px}
.lectura-simulador{
  margin-top:10px;
  padding:11px 13px;
  border-left:5px solid var(--azul2);
  background:#eef5ff;
  border-radius:8px;
  line-height:1.45;
}
@media(max-width:1080px){
  .grid-afp{grid-template-columns:repeat(2,1fr)}
  .dos-columnas{grid-template-columns:1fr}
  .explicacion-modelo{grid-template-columns:1fr}
  .estimador-visible{grid-template-columns:repeat(2,1fr)}
}
@media(max-width:760px){
  .nav{grid-template-columns:repeat(2,1fr)}
  .grid-afp,.resumen-linea,.resultados-simulador,.controles-simulador,.estimador-visible{grid-template-columns:1fr}
  .grafico{height:430px;min-height:430px}
}
</style>
</head>
<body>
<main>
<header>
  <h1>Monitor práctico — AFP Fondo 3</h1>
  <p>Seguimiento diario, histórico SBS completo desde 2015, pronóstico antes de la SBS y simulación de un monto.</p>
  <p class="actualizacion" id="actualizacion"></p>
</header>

<nav class="nav">
  <button class="activo" data-vista="hoy">1. Pronóstico diario</button>
  <button data-vista="evolucion">2. Evolución del valor cuota</button>
  <button data-vista="indices">3. Índices que lo mueven</button>
  <button data-vista="simulador">4. Simulador</button>
  <button data-vista="velaIntradia">5. Vela intradía</button>
</nav>

<section id="hoy" class="vista activa">
  <div class="aviso">
    Esta es la vista principal: compara la última cuota oficial SBS con la última estimación disponible del modelo.
    En feriados o fines de semana la fecha no avanza si los mercados que alimentan el modelo no tuvieron una nueva rueda.
  </div>
  <div id="tarjetasHoy" class="grid-afp">__TARJETAS_HOY__</div>
</section>

<section id="evolucion" class="vista">
  <div class="aviso">
    Línea azul: valor cuota real SBS. Línea naranja: proyección vigente del modelo desde la última cuota oficial.
  </div>
  <div id="selectorEvolucion" class="selector"></div>
  <div id="resumenEvolucion" class="resumen-linea"></div>
  <div id="estimadorVisible" class="estimador-visible"></div>
  <div id="detallePronosticoDiario" class="bloque" style="margin-bottom:11px"></div>
  <div class="bloque">
    <div id="graficoEvolucion" class="grafico"></div>
  </div>
  <div id="explicacionEvolucion" class="explicacion-modelo"></div>
</section>

<section id="indices" class="vista">
  <div class="aviso">
    Solo aparecen los índices del modelo de la AFP seleccionada. El aporte explica si cada señal empuja la estimación hacia arriba o hacia abajo.
  </div>
  <div id="selectorIndices" class="selector"></div>
  <div class="dos-columnas">
    <div class="bloque"><div id="graficoIndices" class="grafico"></div></div>
    <div class="bloque">
      <h3 id="tituloTablaIndices"></h3>
      <div id="tablaIndices"></div>
    </div>
  </div>
</section>

<section id="simulador" class="vista">
  <div class="aviso">
    Elige AFP, monto, fecha de ingreso y fecha de cierre.
    Las fechas históricas usan valores oficiales SBS. La única fecha futura calculable
    es la fecha exacta del pronóstico vigente del modelo. No se inventan proyecciones
    para días posteriores. El calendario de ingreso comienza en el primer valor oficial cargado. Tus selecciones quedan guardadas en este navegador.
  </div>

  <div class="controles-simulador">
    <div class="control">
      <label for="simAfp">AFP</label>
      <select id="simAfp"></select>
    </div>
    <div class="control">
      <label for="simMonto">Monto inicial en soles</label>
      <input id="simMonto" type="number" min="0" step="100" value="100000">
    </div>
    <div class="control">
      <label for="simFechaIngreso">Fecha de ingreso</label>
      <input id="simFechaIngreso" type="date">
    </div>
    <div class="control">
      <label for="simFechaSalida">Fecha de cierre</label>
      <input id="simFechaSalida" type="date">
    </div>
  </div>

  <div id="resultadosSimulador" class="resultados-simulador"></div>

  <div class="bloque">
    <div id="graficoSimulador" class="grafico"></div>
    <div id="lecturaSimulador" class="lectura-simulador"></div>
  </div>
</section>


<section id="velaIntradia" class="vista">
  <div class="aviso">
    Esta vista muestra velas intradía del valor cuota estimado usando únicamente valores guardados durante el día.
    La vela no usa cuotas oficiales intradía SBS: resume las estimaciones del valor cuota que el sistema fue registrando.
  </div>
  <div class="bloque metodologia-vela">
    <h3>Cómo se construye la vela del valor cuota</h3>
    <p>Para construirla como en MetaTrader, cada actualización guardada del valor cuota estimado se toma como un dato intradía. Luego se agrupa por hora de registro y cada hora forma una vela.</p>
    <ul>
      <li><strong>Apertura</strong> = primer valor estimado guardado en la hora.</li>
      <li><strong>Máximo</strong> = mayor valor estimado guardado en la hora.</li>
      <li><strong>Mínimo</strong> = menor valor estimado guardado en la hora.</li>
      <li><strong>Cierre</strong> = último valor estimado guardado en la hora.</li>
    </ul>
    <p class="nota">Si en una hora solo existe una actualización, apertura, máximo, mínimo y cierre serán iguales. Por eso también se muestra la línea de valores guardados.</p>
  </div>
  <div id="selectorVelaIntradia" class="selector"></div>
  <div id="resumenVelaIntradia" class="resumen-linea">
    <div class="sin-datos">Esperando estimaciones intradía guardadas del valor cuota.</div>
  </div>
  <div id="bloqueGraficoVelaIntradia" class="bloque" style="display:none">
    <div id="graficoVelaIntradia" class="grafico"></div>
    <div id="tablaVelaIntradia" class="tabla-wrap"></div>
  </div>
</section>

<p class="nota">
  Herramienta estadística educativa. Los índices son señales del modelo y no equivalen necesariamente a la composición exacta de la cartera de cada AFP.
</p>
</main>

<script>
const DATOS = __DATOS__;
let afpEvolucion = "Habitat";
let afpIndices = "Habitat";
let afpVelaIntradia = "Habitat";
let vistaActual = "hoy";
const textoCanasta = DATOS.estado_canasta?.texto || "canasta del modelo";

function fmtNumero(v,d=6){
  if(v===null||v===undefined||!Number.isFinite(Number(v))) return "Sin dato";
  return new Intl.NumberFormat("es-PE",{minimumFractionDigits:d,maximumFractionDigits:d}).format(Number(v));
}
function fmtPct(v,d=3){
  if(v===null||v===undefined||!Number.isFinite(Number(v))) return "Sin dato";
  const n=Number(v);
  return `${n>=0?"+":""}${n.toFixed(d)}%`;
}
function fmtDinero(v){
  if(v===null||v===undefined||!Number.isFinite(Number(v))) return "Sin dato";
  return new Intl.NumberFormat("es-PE",{style:"currency",currency:"PEN",minimumFractionDigits:2}).format(Number(v));
}
function claseNumero(v){return Number(v)>=0?"positivo":"negativo";}

function crearSelector(id,actual,accion){
  const cont=document.getElementById(id);
  cont.innerHTML="";
  Object.keys(DATOS.afps).forEach(afp=>{
    const b=document.createElement("button");
    b.textContent=afp;
    b.classList.toggle("activo",afp===actual);
    b.onclick=()=>accion(afp);
    cont.appendChild(b);
  });
}

function activarVista(nombre){
  vistaActual=nombre;
  document.querySelectorAll(".vista").forEach(v=>v.classList.toggle("activa",v.id===nombre));
  document.querySelectorAll(".nav button").forEach(b=>b.classList.toggle("activo",b.dataset.vista===nombre));

  requestAnimationFrame(()=>{
    try{
      if(nombre==="evolucion") renderEvolucion();
      if(nombre==="indices") renderIndices();
      if(nombre==="simulador") renderSimulador();
      if(nombre==="velaIntradia") renderVelaIntradia();
    }catch(e){
      const vista=document.getElementById(nombre);
      if(vista){
        vista.insertAdjacentHTML("beforeend",'<div class="sin-datos">La vista cambió, pero algún gráfico no terminó de cargar. Revisa la tabla de datos o recarga el monitor.</div>');
      }
      console.error(e);
    }
    setTimeout(()=>{
      document.querySelectorAll(".js-plotly-plot").forEach(g=>{
        try{if(window.Plotly) Plotly.Plots.resize(g);}catch(e){}
      });
    },80);
  });
}
document.querySelectorAll(".nav button").forEach(b=>{
  b.onclick=()=>activarVista(b.dataset.vista);
});

function renderVelaIntradia(){
  crearSelector("selectorVelaIntradia",afpVelaIntradia,afp=>{
    afpVelaIntradia=afp;
    renderVelaIntradia();
  });

  const d=DATOS.afps[afpVelaIntradia]||{};
  const vela=d.vela_intradia;
  const resumen=document.getElementById("resumenVelaIntradia");

  if(!vela){
    resumen.innerHTML=`
      <div class="sin-datos">
        Todavía no hay estimaciones intradía guardadas para construir la vela del valor cuota de ${afpVelaIntradia}.
        Cuando el sistema guarde valores durante el día, esta página mostrará velas por hora con apertura, máximo, mínimo y cierre.
      </div>`;
    const bloqueGrafico=document.getElementById("bloqueGraficoVelaIntradia");
    if(bloqueGrafico) bloqueGrafico.style.display="none";
    if(window.Plotly) Plotly.purge("graficoVelaIntradia");
    return;
  }

  const bloqueGrafico=document.getElementById("bloqueGraficoVelaIntradia");
  if(bloqueGrafico) bloqueGrafico.style.display="block";

  resumen.innerHTML=`
    <div class="mini-card"><span>AFP</span><strong>${afpVelaIntradia}</strong></div>
    <div class="mini-card"><span>Día guardado</span><strong>${vela.fecha_guardado||"Sin dato"}</strong></div>
    <div class="mini-card"><span>Fecha objetivo</span><strong>${vela.fecha_objetivo||"Sin dato"}</strong></div>
    <div class="mini-card"><span>Estimaciones guardadas</span><strong>${vela.n_estimaciones}</strong></div>
    <div class="mini-card"><span>Apertura del día</span><strong>${fmtNumero(vela.apertura)}</strong></div>
    <div class="mini-card"><span>Máximo del día</span><strong>${fmtNumero(vela.maximo)}</strong></div>
    <div class="mini-card"><span>Mínimo del día</span><strong>${fmtNumero(vela.minimo)}</strong></div>
    <div class="mini-card"><span>Cierre del día</span><strong>${fmtNumero(vela.cierre)}</strong></div>
    <div class="mini-card"><span>Variación del día</span><strong class="${claseNumero(vela.variacion_pct)}">${fmtPct(vela.variacion_pct)}</strong></div>
    <div class="mini-card"><span>Ventana</span><strong>${vela.primer_registro||"--"} a ${vela.ultimo_registro||"--"}</strong></div>`;

  const velasHorarias=vela.velas_horarias||[];
  const horas=(vela.serie||[]).map(x=>x.hora);
  const cuotas=(vela.serie||[]).map(x=>x.cuota);
  const tabla=document.getElementById("tablaVelaIntradia");
  if(tabla){
    tabla.innerHTML=`
      <table>
        <thead>
          <tr>
            <th>Hora</th>
            <th class="num">Apertura</th>
            <th class="num">Máximo</th>
            <th class="num">Mínimo</th>
            <th class="num">Cierre</th>
            <th class="num">Registros</th>
          </tr>
        </thead>
        <tbody>
          ${velasHorarias.map(v=>`
            <tr>
              <td><strong>${v.hora}</strong></td>
              <td class="num">${fmtNumero(v.apertura)}</td>
              <td class="num">${fmtNumero(v.maximo)}</td>
              <td class="num">${fmtNumero(v.minimo)}</td>
              <td class="num">${fmtNumero(v.cierre)}</td>
              <td class="num">${v.n}</td>
            </tr>
          `).join("")}
        </tbody>
      </table>
      <p class="nota">Cada fila es una vela horaria del valor cuota estimado guardado.</p>
    `;
  }

  if(!window.Plotly){
    document.getElementById("graficoVelaIntradia").innerHTML=
      '<div class="sin-datos">No se cargó la librería de gráficos. La tabla inferior muestra las velas horarias calculadas.</div>';
    return;
  }

  const trazas=[
    {
      type:"candlestick",
      x:velasHorarias.map(v=>v.hora),
      open:velasHorarias.map(v=>v.apertura),
      high:velasHorarias.map(v=>v.maximo),
      low:velasHorarias.map(v=>v.minimo),
      close:velasHorarias.map(v=>v.cierre),
      name:"Velas horarias",
      increasing:{line:{color:"#15803d"},fillcolor:"rgba(22,163,74,.28)"},
      decreasing:{line:{color:"#b91c1c"},fillcolor:"rgba(220,38,38,.25)"}
    },
    {
      type:"scatter",
      mode:"lines+markers",
      x:horas,
      y:cuotas,
      yaxis:"y2",
      name:"Actualizaciones guardadas",
      line:{color:"#2563eb",width:2},
      marker:{size:6}
    }
  ];

  Plotly.react("graficoVelaIntradia",trazas,{
    title:`${afpVelaIntradia}: velas horarias del valor cuota estimado`,
    height:520,
    margin:{l:62,r:52,t:70,b:60},
    paper_bgcolor:"white",
    plot_bgcolor:"white",
    showlegend:true,
    xaxis:{title:"Hora",rangeslider:{visible:false}},
    yaxis:{title:"OHLC por hora",gridcolor:"#e8edf5",domain:[0.42,1]},
    yaxis2:{title:"Valores guardados",gridcolor:"#eef2f7",domain:[0,0.30]},
    hovermode:"x unified"
  },{responsive:true,displayModeBar:false});
}
function renderHoy(){
  const cont=document.getElementById("tarjetasHoy");
  cont.innerHTML="";
  Object.entries(DATOS.afps).forEach(([afp,d])=>{
    const a=d.actual;
    const real=d.ultimo_oficial;
    const direccion=a?.direccion||"SIN PRONÓSTICO";
    const sube=direccion==="SUBE";
    const baja=direccion==="BAJA";
    const clase=sube?"sube":(baja?"baja":"neutro");
    const flecha=sube?"↑":(baja?"↓":"—");
    const tarjeta=document.createElement("article");
    tarjeta.className="tarjeta";
    tarjeta.innerHTML=`
      <h2>${afp}</h2>
      <div class="dato"><span>Última cuota SBS</span><strong>${real?fmtNumero(real.cuota):"Sin dato"}</strong></div>
      <div class="dato"><span>Fecha oficial</span><strong>${real?.fecha||"Sin dato"}</strong></div>
      <div class="dato"><span>Cuota estimada</span><strong>${a?fmtNumero(a.cuota_estimada):"Sin dato"}</strong></div>
      <div class="dato"><span>Última fecha con señal completa</span><strong>${a?.fecha_objetivo||"Sin dato"}</strong></div>
      <div class="senal ${clase}">
        <span class="flecha">${flecha}</span>
        <strong>${direccion}</strong><br>
        <span>${a?fmtPct(a.variacion_estimada_pct):"No hay estimación vigente"}</span>
      </div>
      <div class="dato"><span>Error histórico medio</span><strong>±${Number(d.metricas.mape_historico).toFixed(3)}%</strong></div>
      <div class="dato"><span>Dirección histórica correcta</span><strong>${Number(d.metricas.direccion_historica).toFixed(1)}%</strong></div>
      <div class="estado">${a?.estado||"SIN PRONÓSTICO"}</div>
    `;
    cont.appendChild(tarjeta);
  });
}

function sumarDiasFecha(fechaTexto,dias){
  const [y,m,d]=String(fechaTexto).slice(0,10).split("-").map(Number);
  const fecha=new Date(Date.UTC(y,m-1,d));
  fecha.setUTCDate(fecha.getUTCDate()+dias);
  return fecha.toISOString().slice(0,10);
}

function restarMesesFecha(fechaTexto,meses){
  const [y,m,d]=String(fechaTexto).slice(0,10).split("-").map(Number);
  const fecha=new Date(Date.UTC(y,m-1,d));
  fecha.setUTCMonth(fecha.getUTCMonth()-meses);
  return fecha.toISOString().slice(0,10);
}

function renderEvolucion(){
  crearSelector("selectorEvolucion",afpEvolucion,afp=>{
    afpEvolucion=afp;
    renderEvolucion();
  });

  const d=DATOS.afps[afpEvolucion];
  const a=d.actual;
  const real=d.ultimo_oficial;
  const metricas=d.metricas||{};
  const modelo=d.modelo||{};
  const factores=d.factores||[];
  const modeloHistorico=(d.modelo_historico||[])
    .filter(v=>!real || v.fecha<=real.fecha);
  const modeloProyectado=(d.modelo_proyectado&&d.modelo_proyectado.length
    ? d.modelo_proyectado
    : modeloHistorico);
  const resumenModeloHistorico=d.modelo_historico_resumen||{};
  const resumenModeloProyectado=d.modelo_proyectado_resumen||{};
  const trayectoriaPronostico=(d.pronosticos||[])
    .filter(v=>real && v.fecha>real.fecha && (!a || v.fecha<=a.fecha_objetivo))
    .sort((x,y)=>x.fecha.localeCompare(y.fecha));

  const mape=Number(metricas.mape_historico);
  const errorCuota=(a && Number.isFinite(mape))
    ? Number(a.cuota_estimada)*(mape/100)
    : null;
  const rangoInferior=(a && errorCuota!==null)
    ? Number(a.cuota_estimada)-errorCuota
    : null;
  const rangoSuperior=(a && errorCuota!==null)
    ? Number(a.cuota_estimada)+errorCuota
    : null;

  document.getElementById("resumenEvolucion").innerHTML=`
    <div class="mini">
      <span>AFP</span>
      <strong>${afpEvolucion}</strong>
      <small>Fondo 3</small>
    </div>
    <div class="mini">
      <span>Última fecha oficial</span>
      <strong>${real?.fecha||"Sin dato"}</strong>
      <small>Fuente SBS</small>
    </div>
    <div class="mini">
      <span>Fecha del pronóstico</span>
      <strong>${a?.fecha_objetivo||"Sin dato"}</strong>
      <small>Última señal completa</small>
    </div>
    <div class="mini">
      <span>Dirección histórica correcta</span>
      <strong>${Number.isFinite(Number(metricas.direccion_historica))?Number(metricas.direccion_historica).toFixed(1)+"%":"Sin dato"}</strong>
      <small>Prueba histórica</small>
    </div>
  `;

  const cuotaBase=a && a.cuota_base!=null ? a.cuota_base : (real ? real.cuota : null);
  const variacionPct=a?.variacion_estimada_pct!=null
    ? Number(a.variacion_estimada_pct)
    : null;

  document.getElementById("estimadorVisible").innerHTML=`
    <div class="estimador-celda">
      <span>Cuota base SBS</span>
      <strong>${cuotaBase!=null?fmtNumero(cuotaBase):"Sin dato"}</strong>
    </div>
    <div class="estimador-celda">
      <span>Retorno estimado</span>
      <strong class="${claseNumero(variacionPct||0)}">${variacionPct!=null?fmtPct(variacionPct):"Sin dato"}</strong>
    </div>
    <div class="estimador-celda destacado">
      <span>VALOR CUOTA ESTIMADO</span>
      <strong>${a?fmtNumero(a.cuota_estimada):"Sin dato"}</strong>
    </div>
    <div class="estimador-celda">
      <span>Error histórico medio</span>
      <strong>${Number.isFinite(mape)?`±${mape.toFixed(3)}%`:"Sin dato"}</strong>
    </div>
    <div class="estimador-celda rango">
      <span>Rango orientativo</span>
      <strong>${rangoInferior!==null?`${fmtNumero(rangoInferior)} – ${fmtNumero(rangoSuperior)}`:"Sin dato"}</strong>
    </div>
  `;


  document.getElementById("detallePronosticoDiario").innerHTML=`
    <h3 style="margin:4px 0 10px;color:#123f73">Trayectoria estimada día por día desde la última cuota SBS</h3>
    ${
      trayectoriaPronostico.length
        ? `<table>
            <thead>
              <tr>
                <th>Fecha</th>
                <th class="num">Cuota estimada</th>
                <th class="num">Cobertura</th>
                <th>Lectura</th>
              </tr>
            </thead>
            <tbody>
              ${trayectoriaPronostico.map((v,i)=>{
                const anterior=i===0 ? Number(real.cuota) : Number(trayectoriaPronostico[i-1].cuota);
                const cambio=anterior>0 ? (Number(v.cuota)/anterior-1)*100 : 0;
                return `
                  <tr>
                    <td><strong>${v.fecha}</strong></td>
                    <td class="num">${fmtNumero(v.cuota)}</td>
                    <td class="num">${v.cobertura!=null?Number(v.cobertura).toFixed(1)+"%":"Sin dato"}</td>
                    <td class="${claseNumero(cambio)}">${cambio>=0?"SUBE":"BAJA"} ${fmtPct(cambio)}</td>
                  </tr>`;
              }).join("")}
            </tbody>
          </table>
          <p class="nota">La primera fila parte de la cuota oficial del ${real?.fecha||""}. La última fila coincide con el pronóstico vigente mostrado arriba.</p>`
        : `<div class="sin-datos">
            No se encontraron filas intermedias en el archivo de detalle del modelo.
            Se muestra únicamente el último pronóstico vigente.
          </div>`
    }
  `;

  const trazas=[{
    type:"scatter",
    mode:"lines",
    x:d.oficial.map(v=>v.fecha),
    y:d.oficial.map(v=>v.cuota),
    name:"Valor cuota real SBS",
    line:{color:"#225f9d",width:3},
    hovertemplate:"<b>Real SBS</b><br>%{x}<br>%{y:.6f}<extra></extra>"
  }];

  if(modeloProyectado.length){
    trazas.push({
      type:"scatter",
      mode:"lines",
      x:modeloProyectado.map(v=>v.fecha),
      y:modeloProyectado.map(v=>v.cuota),
      name:"Modelo histórico y proyección",
      line:{color:"#ef6c3e",width:2.7,dash:"dot"},
      opacity:.92,
      customdata:modeloProyectado.map(v=>v.tipo||"historico"),
      hovertemplate:
        "<b>Modelo %{customdata}</b><br>"+
        "%{x}<br>Cuota: %{y:.6f}<extra></extra>"
    });
  }

  const shapes=[];
  const annotations=[];

  if(real && a){
    const puntosTrayectoria=trayectoriaPronostico.length
      ? trayectoriaPronostico
      : [{fecha:a.fecha_objetivo,cuota:a.cuota_estimada,cobertura:a.cobertura_pct}];

    const xTrayectoria=[real.fecha,...puntosTrayectoria.map(v=>v.fecha)];
    const yTrayectoria=[real.cuota,...puntosTrayectoria.map(v=>v.cuota)];
    const coberturaTrayectoria=[null,...puntosTrayectoria.map(v=>v.cobertura)];
    const etapaTrayectoria=[
      "SBS real",
      ...puntosTrayectoria.map(v=>`Estimación ${v.fecha}`)
    ];

    trazas.push({
      type:"scatter",
      mode:"lines+markers",
      x:xTrayectoria,
      y:yTrayectoria,
      name:"Estimación actual día por día",
      line:{color:"#b84c24",width:5,dash:"dash"},
      marker:{
        size:xTrayectoria.map((_,i)=>i===0?9:(i===xTrayectoria.length-1?17:12)),
        color:xTrayectoria.map((_,i)=>i===0?"#225f9d":(i===xTrayectoria.length-1?"#b84c24":"#ef6c3e")),
        line:{color:"white",width:2}
      },
      customdata:xTrayectoria.map((_,i)=>[
        etapaTrayectoria[i],
        coberturaTrayectoria[i]
      ]),
      hovertemplate:
        "<b>%{customdata[0]}</b><br>"+
        "Fecha: %{x}<br>"+
        "Cuota: %{y:.6f}<br>"+
        "Cobertura: %{customdata[1]:.1f}%"+
        "<extra></extra>"
    });

    // Banda horizontal de error alrededor del estimado.
    if(rangoInferior!==null && rangoSuperior!==null){
      const x0=sumarDiasFecha(a.fecha_objetivo,-5);
      const x1=sumarDiasFecha(a.fecha_objetivo,5);
      shapes.push({
        type:"rect",
        xref:"x",
        yref:"y",
        x0:x0,
        x1:x1,
        y0:rangoInferior,
        y1:rangoSuperior,
        fillcolor:"rgba(210,164,0,.18)",
        line:{color:"rgba(210,164,0,.75)",width:2},
        layer:"below"
      });
    }

    // Línea vertical y flecha para que el estimado no se pierda en el histórico completo.
    shapes.push({
      type:"line",
      xref:"x",
      yref:"paper",
      x0:a.fecha_objetivo,
      x1:a.fecha_objetivo,
      y0:0,
      y1:1,
      line:{color:"rgba(239,108,62,.45)",width:2,dash:"dot"}
    });

    annotations.push({
      x:a.fecha_objetivo,
      y:a.cuota_estimada,
      xref:"x",
      yref:"y",
      text:
        `<b>ESTIMADO ${fmtNumero(a.cuota_estimada)}</b><br>`+
        `${a.direccion||""} ${variacionPct!=null?fmtPct(variacionPct):""}<br>`+
        `${a.fecha_objetivo}`,
      showarrow:true,
      arrowhead:3,
      arrowsize:1.2,
      arrowwidth:2,
      arrowcolor:"#ef6c3e",
      ax:-115,
      ay:-70,
      bgcolor:"rgba(255,242,233,.96)",
      bordercolor:"#ef6c3e",
      borderwidth:2,
      borderpad:7,
      font:{color:"#9a3e1b",size:13},
      align:"left"
    });
  }

  const fechaFinal=a?.fecha_objetivo||real?.fecha;
  const rangoInicial=fechaFinal
    ? [restarMesesFecha(fechaFinal,12),sumarDiasFecha(fechaFinal,20)]
    : undefined;

  Plotly.react("graficoEvolucion",trazas,{
    autosize:true,
    height:500,
    title:{text:`${afpEvolucion}: cuota real SBS vs. cuota estimada por el modelo`,x:.02},
    paper_bgcolor:"white",
    plot_bgcolor:"white",
    margin:{l:65,r:55,t:75,b:55},
    hovermode:"x unified",
    legend:{orientation:"h",y:1.06,x:0},
    shapes:shapes,
    annotations:annotations,
    xaxis:{
      title:"Fecha",
      type:"date",
      range:rangoInicial,
      showgrid:true,
      gridcolor:"#e7edf4",
      rangeselector:{
        buttons:[
          {count:1,label:"1 mes",step:"month",stepmode:"backward"},
          {count:3,label:"3 meses",step:"month",stepmode:"backward"},
          {count:6,label:"6 meses",step:"month",stepmode:"backward"},
          {count:1,label:"1 año",step:"year",stepmode:"backward"},
          {step:"all",label:"Todo"}
        ]
      }
    },
    yaxis:{
      title:"Valor cuota",
      autorange:true,
      showgrid:true,
      gridcolor:"#e7edf4"
    }
  },{responsive:true,displaylogo:false,scrollZoom:true});

  const variacionDecimal=variacionPct!=null
    ? variacionPct/100
    : null;

  const factoresTexto=factores.length
    ? factores.map(v=>v.nombre).join(", ")
    : "No se encontró el detalle de factores del módulo 79C.";

  const topFactores=[...factores]
    .sort((x,y)=>Math.abs(Number(y.aporte_pp))-Math.abs(Number(x.aporte_pp)))
    .slice(0,3);

  document.getElementById("explicacionEvolucion").innerHTML=`
    <article class="explicacion-card">
      <h3>1. Cálculo del valor estimado</h3>
      <p>El modelo calcula el retorno esperado con la canasta fija de índices y lo aplica a la cuota base.</p>
      <div class="formula-simple">
        <strong>${cuotaBase!=null?fmtNumero(cuotaBase):"Sin dato"}</strong>
        x
        <strong>(1 ${variacionDecimal!=null && variacionDecimal>=0?"+":"−"} ${variacionDecimal!=null?Math.abs(variacionDecimal).toFixed(6):"?"})</strong>
        =
        <strong>${a?fmtNumero(a.cuota_estimada):"Sin dato"}</strong>
      </div>
      <p class="nota">
        La línea naranja punteada une la estimación histórica con la proyección vigente hasta el último día hábil cubierto.
        La línea naranja con puntos resalta las estimaciones actuales desde la última SBS.
      </p>
      <p class="nota">
        Serie histórica del modelo: <strong>${resumenModeloHistorico.n_estimaciones||0}</strong>
        estimaciones, desde <strong>${resumenModeloHistorico.fecha_inicio||"sin fecha"}</strong>
        hasta <strong>${resumenModeloHistorico.fecha_fin||"sin fecha"}</strong>.
        Fuente: ${resumenModeloHistorico.fuente||"no encontrada"}.
      </p>
      <p class="nota">
        Proyección visible: desde <strong>${resumenModeloProyectado.fecha_inicio||"sin fecha"}</strong>
        hasta <strong>${resumenModeloProyectado.fecha_fin||"sin fecha"}</strong>.
        Fechas hábiles esperadas: <strong>${(resumenModeloProyectado.fechas_habiles_esperadas||[]).join(", ")||"ninguna"}</strong>.
        Faltantes: <strong>${(resumenModeloProyectado.fechas_habiles_faltantes||[]).join(", ")||"ninguna"}</strong>.
      </p>
    </article>

    <article class="explicacion-card">
      <h3>2. Error y rango orientativo</h3>
      <p>Error absoluto medio histórico: <strong>${Number.isFinite(mape)?`±${mape.toFixed(3)}%`:"sin dato"}</strong>.</p>
      <div class="rango-estimado">
        ${rangoInferior!==null?`${fmtNumero(rangoInferior)} – ${fmtNumero(rangoSuperior)}`:"Sin rango"}
      </div>
      <p>
        Estimado ${a?fmtNumero(a.cuota_estimada):"sin dato"} ±
        ${errorCuota!==null?fmtNumero(errorCuota):"sin dato"} unidades de cuota.
      </p>
      <p class="nota">Es una referencia basada en el error medio del backtest, no una garantía.</p>
    </article>

    <article class="explicacion-card">
      <h3>3. Modelo e indicadores</h3>
      <div>
        <span class="etiqueta-metodo">${modelo.modelo||"EW-Ridge"}</span>
        <span class="etiqueta-metodo">Alpha ${modelo.alpha!=null?modelo.alpha:"sin dato"}</span>
        <span class="etiqueta-metodo">Vida media ${modelo.half_life!=null?modelo.half_life:"sin dato"} días</span>
        <span class="etiqueta-metodo">${factores.length} factores</span>
        <span class="etiqueta-metodo">Cobertura ${a?.cobertura_pct!=null?Number(a.cobertura_pct).toFixed(1)+"%":"sin dato"}</span>
      </div>
      <p><strong>Canasta:</strong> ${factoresTexto}</p>
      ${topFactores.length?`
        <p><strong>Mayores aportes al pronóstico:</strong></p>
        <ul class="lista-factores">
          ${topFactores.map(v=>`
            <li>
              ${v.nombre}:
              <strong class="${claseNumero(v.aporte_pp)}">
                ${Number(v.aporte_pp)>=0?"+":""}${Number(v.aporte_pp).toFixed(4)} p.p.
              </strong>
            </li>
          `).join("")}
        </ul>
      `:""}
      <p class="nota">Dirección histórica correcta: ${Number(metricas.direccion_historica).toFixed(1)}%.</p>
    </article>
  `;
}


function renderIndices(){
  crearSelector("selectorIndices",afpIndices,afp=>{
    afpIndices=afp;
    renderIndices();
  });

  const d=DATOS.afps[afpIndices];
  const factores=d.factores||[];
  document.getElementById("tituloTablaIndices").textContent=
    `${afpIndices} — señales de ${d.fecha_factores||"fecha no disponible"}`;

  if(!factores.length){
    document.getElementById("tablaIndices").innerHTML=
      '<div class="sin-datos">No se encontró información actualizada de los índices.</div>';
    Plotly.purge("graficoIndices");
    return;
  }

  const orden=[...factores].reverse();
  Plotly.react("graficoIndices",[{
    type:"bar",
    orientation:"h",
    y:orden.map(v=>v.nombre),
    x:orden.map(v=>v.aporte_pp),
    marker:{color:orden.map(v=>v.aporte_pp>=0?"#0f8a46":"#c6283d")},
    customdata:orden.map(v=>[v.retorno_factor_pct,v.lag]),
    hovertemplate:"<b>%{y}</b><br>Aporte: %{x:.4f} p.p.<br>Movimiento: %{customdata[0]:.3f}%<br>Rezago: %{customdata[1]} día(s)<extra></extra>"
  }],{
    autosize:true,
    height:470,
    title:{text:"Qué índices empujan el pronóstico",x:.02},
    paper_bgcolor:"white",
    plot_bgcolor:"white",
    margin:{l:210,r:20,t:60,b:50},
    xaxis:{title:"Aporte al retorno estimado (puntos porcentuales)",zeroline:true,zerolinecolor:"#64748b",showgrid:true,gridcolor:"#e7edf4"},
    yaxis:{automargin:true}
  },{responsive:true,displaylogo:false});

  document.getElementById("tablaIndices").innerHTML=`
    <table>
      <thead><tr><th>Indicador</th><th class="num">Movimiento</th><th class="num">Efecto</th></tr></thead>
      <tbody>
      ${factores.map(v=>`
        <tr>
          <td><strong>${v.nombre}</strong>${v.lag?`<br><small>Rezago: ${v.lag} día</small>`:""}</td>
          <td class="num ${claseNumero(v.retorno_factor_pct||0)}">${fmtPct(v.retorno_factor_pct)}</td>
          <td class="num ${claseNumero(v.aporte_pp)}">${v.aporte_pp>=0?"↑":"↓"} ${v.aporte_pp.toFixed(4)} p.p.</td>
        </tr>
      `).join("")}
      </tbody>
    </table>
    <p class="nota">El aporte no es un peso de cartera; es el efecto estadístico de la señal sobre el pronóstico.</p>
  `;
}

const CLAVE_SIMULADOR="afp_fondo3_simulador_v122";
const CLAVES_ANTERIORES=[];
let simuladorInicializado=false;

function leerPreferenciasSimulador(){
  try{
    const nuevo=localStorage.getItem(CLAVE_SIMULADOR);
    if(nuevo) return JSON.parse(nuevo);

    for(const clave of CLAVES_ANTERIORES){
      const anterior=localStorage.getItem(clave);
      if(anterior){
        const p=JSON.parse(anterior);
        if(p.fechaSalida==="ACTUAL") p.fechaSalida=null;
        return p;
      }
    }
    return {};
  }catch(e){
    return {};
  }
}

function guardarPreferenciasSimulador(){
  const preferencias={
    afp:document.getElementById("simAfp").value,
    monto:document.getElementById("simMonto").value,
    fechaIngreso:document.getElementById("simFechaIngreso").value,
    fechaSalida:document.getElementById("simFechaSalida").value
  };
  try{
    localStorage.setItem(CLAVE_SIMULADOR,JSON.stringify(preferencias));
  }catch(e){}
}

function ultimaCuotaEnOAntes(d,fecha){
  const candidatas=(d.oficial||[])
    .filter(v=>v.fecha<=fecha)
    .sort((a,b)=>a.fecha.localeCompare(b.fecha));
  return candidatas.length?candidatas[candidatas.length-1]:null;
}

function primeraFecha(d){
  return d.oficial?.length?d.oficial[0].fecha:null;
}

function inicializarSimulador(){
  if(simuladorInicializado) return;
  simuladorInicializado=true;

  const preferencias=leerPreferenciasSimulador();
  const selectAfp=document.getElementById("simAfp");

  Object.keys(DATOS.afps).forEach(afp=>{
    const op=document.createElement("option");
    op.value=afp;
    op.textContent=afp;
    selectAfp.appendChild(op);
  });

  if(preferencias.afp && DATOS.afps[preferencias.afp]){
    selectAfp.value=preferencias.afp;
  }

  if(preferencias.monto!==undefined && preferencias.monto!==""){
    document.getElementById("simMonto").value=preferencias.monto;
  }

  prepararCalendarios(
    preferencias.fechaIngreso,
    preferencias.fechaSalida
  );

  selectAfp.addEventListener("change",()=>{
    prepararCalendarios(
      document.getElementById("simFechaIngreso").value,
      document.getElementById("simFechaSalida").value
    );
    guardarPreferenciasSimulador();
    renderSimulador();
  });

  document.getElementById("simMonto").addEventListener("input",()=>{
    guardarPreferenciasSimulador();
    renderSimulador();
  });

  document.getElementById("simFechaIngreso").addEventListener("change",()=>{
    prepararCalendarios(
      document.getElementById("simFechaIngreso").value,
      document.getElementById("simFechaSalida").value
    );
    guardarPreferenciasSimulador();
    renderSimulador();
  });

  document.getElementById("simFechaSalida").addEventListener("change",()=>{
    guardarPreferenciasSimulador();
    renderSimulador();
  });
}

function prepararCalendarios(fechaIngresoPreferida=null,fechaSalidaPreferida=null){
  const afp=document.getElementById("simAfp").value||"Habitat";
  const d=DATOS.afps[afp];
  const inputIngreso=document.getElementById("simFechaIngreso");
  const inputSalida=document.getElementById("simFechaSalida");

  const minimo=primeraFecha(d);
  const ultimoOficial=d.ultimo_oficial?.fecha||minimo;
  const fechaPronostico=d.actual?.fecha_objetivo||ultimoOficial;

  const sugerenciaIngreso=
    fechaIngresoPreferida &&
    (!minimo || fechaIngresoPreferida>=minimo) &&
    (!ultimoOficial || fechaIngresoPreferida<=ultimoOficial)
      ? fechaIngresoPreferida
      : minimo;

  inputIngreso.min=minimo||"";
  inputIngreso.max=ultimoOficial||"";
  inputIngreso.value=sugerenciaIngreso||"";

  inputSalida.min=inputIngreso.value||minimo||"";

  // Se permite seleccionar cualquier fecha para seguimiento,
  // pero solo se calcula si existe cuota SBS o si coincide exactamente
  // con la fecha objetivo del pronóstico vigente.
  const sugerenciaSalida=
    fechaSalidaPreferida &&
    (!inputSalida.min || fechaSalidaPreferida>=inputSalida.min)
      ? fechaSalidaPreferida
      : fechaPronostico;

  inputSalida.value=sugerenciaSalida||"";
}

function obtenerEntrada(d,fechaElegida){
  const exacta=(d.oficial||[]).find(v=>v.fecha===fechaElegida);
  if(exacta){
    return {
      fechaSolicitada:fechaElegida,
      fechaUsada:exacta.fecha,
      cuota:exacta.cuota,
      exacta:true
    };
  }

  const anterior=ultimaCuotaEnOAntes(d,fechaElegida);
  if(!anterior) return null;

  return {
    fechaSolicitada:fechaElegida,
    fechaUsada:anterior.fecha,
    cuota:anterior.cuota,
    exacta:false
  };
}

function pronosticosFuturosDisponibles(d){
  const ultimoOficial=d.ultimo_oficial?.fecha||"";
  return (d.pronosticos||[])
    .filter(v=>v.fecha>ultimoOficial)
    .sort((a,b)=>a.fecha.localeCompare(b.fecha));
}

function obtenerSalida(d,fechaSalida){
  const exacta=(d.oficial||[]).find(v=>v.fecha===fechaSalida);
  if(exacta){
    return {
      disponible:true,
      fechaUsada:exacta.fecha,
      cuota:exacta.cuota,
      tipo:"Cuota oficial SBS",
      esPronostico:false
    };
  }

  const ultimoOficial=d.ultimo_oficial?.fecha||null;

  // Día histórico sin publicación: usa la última cuota oficial previa.
  if(ultimoOficial && fechaSalida<=ultimoOficial){
    const anterior=ultimaCuotaEnOAntes(d,fechaSalida);
    if(anterior){
      return {
        disponible:true,
        fechaUsada:anterior.fecha,
        fechaSolicitada:fechaSalida,
        cuota:anterior.cuota,
        tipo:"Última cuota oficial SBS disponible",
        esPronostico:false
      };
    }
  }

  // Puede existir más de una fecha estimada: por ejemplo 01/07 y 02/07.
  const pronosticos=pronosticosFuturosDisponibles(d);
  const estimacionExacta=pronosticos.find(v=>v.fecha===fechaSalida);

  if(estimacionExacta){
    return {
      disponible:true,
      fechaUsada:estimacionExacta.fecha,
      cuota:Number(estimacionExacta.cuota),
      cobertura:estimacionExacta.cobertura,
      tipo:`Estimación del modelo para ${estimacionExacta.fecha}`,
      esPronostico:true
    };
  }

  const fechasDisponibles=pronosticos.map(v=>v.fecha);

  return {
    disponible:false,
    fechaSolicitada:fechaSalida,
    ultimoOficial:ultimoOficial,
    fechasPronostico:fechasDisponibles,
    motivo:fechasDisponibles.length
      ? `No existe una estimación exacta para ${fechaSalida}. Las fechas estimadas disponibles son: ${fechasDisponibles.join(", ")}.`
      : "No existen estimaciones futuras guardadas por el modelo."
  };
}


function mostrarSalidaNoDisponible(d,entrada,fechaCierre,monto,salida){
  const historico=d.historico_resumen||{};
  const pronosticos=pronosticosFuturosDisponibles(d);
  const cuotas=monto/entrada.cuota;

  document.getElementById("resultadosSimulador").innerHTML=`
    <div class="resultado"><span>Cuota de ingreso</span><strong>${fmtNumero(entrada.cuota)}</strong></div>
    <div class="resultado"><span>Cuota de cierre</span><strong>Sin estimación</strong></div>
    <div class="resultado"><span>Valor al cierre</span><strong>No calculable</strong></div>
    <div class="resultado"><span>Ganancia o pérdida</span><strong>No calculable</strong></div>
    <div class="resultado"><span>Última cuota SBS</span><strong>${d.ultimo_oficial?.fecha||"Sin dato"}</strong></div>
    <div class="resultado"><span>Fechas estimadas</span><strong>${pronosticos.length?pronosticos.map(v=>v.fecha).join(" y "):"Sin dato"}</strong></div>
  `;

  const oficiales=(d.oficial||[])
    .filter(v=>v.fecha>=entrada.fechaUsada)
    .map(v=>({
      fecha:v.fecha,
      saldo:cuotas*v.cuota
    }));

  const trazas=[{
    type:"scatter",
    mode:"lines",
    x:oficiales.map(v=>v.fecha),
    y:oficiales.map(v=>v.saldo),
    name:"Valores oficiales SBS",
    line:{color:"#225f9d",width:3},
    hovertemplate:"<b>SBS real</b><br>%{x}<br>Saldo: S/ %{y:,.2f}<extra></extra>"
  }];

  if(pronosticos.length && d.ultimo_oficial){
    trazas.push({
      type:"scatter",
      mode:"lines+markers",
      x:[d.ultimo_oficial.fecha,...pronosticos.map(v=>v.fecha)],
      y:[
        cuotas*d.ultimo_oficial.cuota,
        ...pronosticos.map(v=>cuotas*Number(v.cuota))
      ],
      name:"Estimaciones del modelo",
      line:{color:"#ef6c3e",width:3,dash:"dash"},
      marker:{size:10,color:"#ef6c3e"},
      hovertemplate:"<b>Estimación del modelo</b><br>%{x}<br>Saldo: S/ %{y:,.2f}<extra></extra>"
    });
  }

  const valores=trazas.flatMap(t=>(t.y||[]).map(Number)).filter(Number.isFinite);
  const minY=Math.min(...valores);
  const maxY=Math.max(...valores);
  const pad=Math.max((maxY-minY)*0.12,Math.abs(maxY)*0.02,1);

  Plotly.react("graficoSimulador",trazas,{
    autosize:true,
    height:470,
    title:{
      text:`${document.getElementById("simAfp").value}: histórico y fechas estimadas disponibles`,
      x:.02
    },
    paper_bgcolor:"white",
    plot_bgcolor:"white",
    margin:{l:75,r:25,t:65,b:60},
    hovermode:"x unified",
    legend:{orientation:"h",y:1.04,x:0},
    xaxis:{
      title:"Fecha",
      type:"date",
      range:[
        entrada.fechaUsada,
        pronosticos.length
          ? pronosticos[pronosticos.length-1].fecha
          : d.ultimo_oficial.fecha
      ],
      showgrid:true,
      gridcolor:"#e7edf4"
    },
    yaxis:{
      title:"Valor de la simulación en soles",
      range:[minY-pad,maxY+pad],
      showgrid:true,
      gridcolor:"#e7edf4"
    }
  },{responsive:true,displaylogo:false,scrollZoom:true});

  document.getElementById("lecturaSimulador").innerHTML=`
    <strong>No se calculó la ganancia para ${fechaCierre}.</strong>
    ${salida.motivo}
    Selecciona exactamente una fecha estimada disponible.
    <br><strong>Histórico oficial cargado:</strong>
    ${historico.fecha_inicio||"sin inicio"} a ${historico.fecha_fin||"sin fin"}
    (${historico.n_valores||0} valores para esta AFP).
  `;
}


function renderSimulador(){
  inicializarSimulador();

  const afp=document.getElementById("simAfp").value||"Habitat";
  const monto=Number(document.getElementById("simMonto").value)||0;
  const fechaIngresoElegida=document.getElementById("simFechaIngreso").value;
  const fechaCierre=document.getElementById("simFechaSalida").value;
  const d=DATOS.afps[afp];

  const entrada=obtenerEntrada(d,fechaIngresoElegida);

  if(!entrada || !fechaCierre){
    document.getElementById("resultadosSimulador").innerHTML=
      '<div class="sin-datos">Selecciona una fecha de ingreso y una fecha de cierre.</div>';
    Plotly.purge("graficoSimulador");
    return;
  }

  if(fechaCierre<fechaIngresoElegida){
    document.getElementById("resultadosSimulador").innerHTML=
      '<div class="sin-datos">La fecha de cierre no puede ser anterior a la fecha de ingreso.</div>';
    Plotly.purge("graficoSimulador");
    return;
  }

  const salida=obtenerSalida(d,fechaCierre);

  if(!salida.disponible){
    mostrarSalidaNoDisponible(d,entrada,fechaCierre,monto,salida);
    guardarPreferenciasSimulador();
    return;
  }

  const cuotas=monto/entrada.cuota;
  const saldoSalida=cuotas*salida.cuota;
  const ganancia=saldoSalida-monto;
  const retorno=monto>0?(ganancia/monto*100):0;

  document.getElementById("resultadosSimulador").innerHTML=`
    <div class="resultado"><span>Cuota de ingreso</span><strong>${fmtNumero(entrada.cuota)}</strong></div>
    <div class="resultado"><span>Cuota de cierre</span><strong>${fmtNumero(salida.cuota)}</strong></div>
    <div class="resultado"><span>Cuotas hipotéticas</span><strong>${fmtNumero(cuotas,4)}</strong></div>
    <div class="resultado"><span>Valor al cierre</span><strong>${fmtDinero(saldoSalida)}</strong></div>
    <div class="resultado"><span>Ganancia o pérdida</span><strong class="${claseNumero(ganancia)}">${fmtDinero(ganancia)}</strong></div>
    <div class="resultado"><span>Rentabilidad</span><strong class="${claseNumero(retorno)}">${fmtPct(retorno)}</strong></div>
  `;

  const fechaLimiteOficial=
    salida.esPronostico
      ? d.ultimo_oficial.fecha
      : salida.fechaUsada;

  // Se usan todos los valores oficiales comprendidos entre la entrada y la salida.
  const oficiales=(d.oficial||[])
    .filter(v=>v.fecha>=entrada.fechaUsada && v.fecha<=fechaLimiteOficial)
    .map(v=>({
      fecha:v.fecha,
      saldo:cuotas*v.cuota
    }));

  const trazas=[{
    type:"scatter",
    mode:"lines",
    x:oficiales.map(v=>v.fecha),
    y:oficiales.map(v=>v.saldo),
    name:"Valores oficiales SBS",
    line:{color:"#225f9d",width:3},
    hovertemplate:"<b>%{x}</b><br>Saldo: S/ %{y:,.2f}<extra></extra>"
  }];

  if(salida.esPronostico){
    const trayectoria=pronosticosFuturosDisponibles(d)
      .filter(v=>v.fecha<=salida.fechaUsada);

    const xEstimado=[
      d.ultimo_oficial.fecha,
      ...trayectoria.map(v=>v.fecha)
    ];
    const yEstimado=[
      cuotas*d.ultimo_oficial.cuota,
      ...trayectoria.map(v=>cuotas*Number(v.cuota))
    ];

    trazas.push({
      type:"scatter",
      mode:"lines+markers",
      x:xEstimado,
      y:yEstimado,
      name:"Estimación del modelo",
      line:{color:"#ef6c3e",width:4,dash:"dash"},
      marker:{
        size:xEstimado.map((_,i)=>i===xEstimado.length-1?14:10),
        color:xEstimado.map((_,i)=>i===0?"#225f9d":"#ef6c3e"),
        line:{color:"white",width:2}
      },
      hovertemplate:"<b>Estimación del modelo</b><br>%{x}<br>Saldo estimado: S/ %{y:,.2f}<extra></extra>"
    });
  }else{
    trazas.push({
      type:"scatter",
      mode:"markers",
      x:[salida.fechaUsada],
      y:[saldoSalida],
      name:"Fecha de cierre",
      marker:{size:13,color:"#0f8a46"},
      hovertemplate:"<b>Cierre</b><br>%{x}<br>Saldo: S/ %{y:,.2f}<extra></extra>"
    });
  }

  const valores=trazas.flatMap(t=>(t.y||[]).map(Number)).filter(Number.isFinite);
  const minY=Math.min(...valores);
  const maxY=Math.max(...valores);
  const pad=Math.max((maxY-minY)*0.12,Math.abs(maxY)*0.02,1);

  Plotly.react("graficoSimulador",trazas,{
    autosize:true,
    height:470,
    title:{
      text:`${afp}: evolución de ${fmtDinero(monto)} desde ${fechaIngresoElegida} hasta ${fechaCierre}`,
      x:.02
    },
    paper_bgcolor:"white",
    plot_bgcolor:"white",
    margin:{l:75,r:25,t:65,b:60},
    hovermode:"x unified",
    legend:{orientation:"h",y:1.04,x:0},
    xaxis:{
      title:"Fecha",
      type:"date",
      showgrid:true,
      gridcolor:"#e7edf4"
    },
    yaxis:{
      title:"Valor de la simulación en soles",
      range:[minY-pad,maxY+pad],
      showgrid:true,
      gridcolor:"#e7edf4"
    }
  },{responsive:true,displaylogo:false,scrollZoom:true});

  let aclaracionIngreso="";
  if(!entrada.exacta){
    aclaracionIngreso=`
      <br><strong>Fecha de ingreso:</strong> el ${fechaIngresoElegida} no tuvo
      una cuota oficial propia. Se utilizó la última cuota SBS disponible del
      ${entrada.fechaUsada}.
    `;
  }

  let aclaracionSalida="";
  if(salida.fechaSolicitada && salida.fechaSolicitada!==salida.fechaUsada){
    aclaracionSalida=`
      <br><strong>Fecha de cierre:</strong> el ${salida.fechaSolicitada} no tuvo
      una cuota oficial propia. Se utilizó la última cuota SBS disponible del
      ${salida.fechaUsada}.
    `;
  }

  document.getElementById("lecturaSimulador").innerHTML=`
    <strong>Resultado:</strong>
    ingreso elegido el ${fechaIngresoElegida} con ${fmtDinero(monto)} y cierre
    el ${fechaCierre}, utilizando <strong>${salida.tipo}</strong>.
    El valor sería ${fmtDinero(saldoSalida)}.
    La <strong>ganancia o pérdida</strong> sería
    <strong class="${claseNumero(ganancia)}">${fmtDinero(ganancia)}</strong>,
    equivalente a
    <strong class="${claseNumero(retorno)}">${fmtPct(retorno)}</strong>.
    ${aclaracionIngreso}
    ${aclaracionSalida}
    <br><strong>Datos utilizados en el gráfico:</strong>
    ${oficiales.length} valores oficiales SBS
    ${salida.esPronostico
      ? `y ${pronosticosFuturosDisponibles(d).filter(v=>v.fecha<=salida.fechaUsada).length} estimación(es) diaria(s) del modelo.`
      : "hasta la fecha de cierre seleccionada."}
  `;

  guardarPreferenciasSimulador();
}


document.getElementById("actualizacion").textContent=
  `Actualizado: ${DATOS.actualizado} | Histórico SBS completo | ${textoCanasta}`;

</script>
</body>
</html>
"""
    html = html.replace("__DATOS__", datos)
    html = html.replace("__TARJETAS_HOY__", tarjetas_hoy_html)
    salida.write_text(html, encoding="utf-8-sig")
    return salida


def crear_lanzador(raiz: Path) -> Path:
    return raiz / "scripts" / "build_pages.py"


def asegurar_historico_completo(raiz: Path) -> None:
    """
    Verifica que exista el histórico oficial consolidado desde 2015.
    Si falta o comienza demasiado tarde, ejecuta el módulo 03 corregido.
    """
    processed = raiz / "data" / "processed"
    largo = processed / "sbs_fondo3_historico_largo.csv"

    necesita_actualizar = True
    if largo.exists():
        try:
            df = leer_csv(largo)
            if not df.empty:
                c_fecha = buscar_columna(df, ("fecha", "fecha_cuota"))
                if c_fecha is not None:
                    fechas = a_fecha(df[c_fecha]).dropna()
                    if not fechas.empty:
                        fecha_min = fechas.min()
                        fecha_max = fechas.max()
                        print(
                            "Histórico consolidado encontrado: "
                            f"{fecha_min.date()} a {fecha_max.date()} "
                            f"({len(df):,} filas)."
                        )
                        necesita_actualizar = (
                            fecha_min > pd.Timestamp("2016-12-31")
                        )
        except Exception as exc:
            print(f"Advertencia al revisar el histórico consolidado: {exc}")

    if not necesita_actualizar:
        return

    candidatos = [
        raiz / "src" / "03_consolidar_historico_fondo3_corregido.py",
        raiz / "src" / "03_consolidar_historico_fondo3.py",
        raiz / "03_consolidar_historico_fondo3_corregido.py",
        raiz / "03_consolidar_historico_fondo3.py",
    ]
    modulo = next((p for p in candidatos if p.exists()), None)

    if modulo is None:
        print(
            "ADVERTENCIA: no encontré el módulo 03 para reconstruir "
            "el histórico. El monitor usará las bases disponibles."
        )
        return

    print(
        "\nEl histórico completo no está disponible o comienza demasiado tarde.\n"
        f"Ejecutando {modulo.name} para consolidar valores SBS desde 2015..."
    )
    resultado = subprocess.run(
        [
            sys.executable,
            str(modulo),
            "--desde",
            "2015",
            "--hasta",
            str(datetime.now().year),
        ],
        cwd=str(raiz),
        check=False,
    )
    if resultado.returncode != 0:
        print(
            f"ADVERTENCIA: {modulo.name} terminó con código "
            f"{resultado.returncode}. Se usarán los datos disponibles."
        )


def ejecutar_actualizacion_modelo(raiz: Path) -> None:
    """
    Flujo diario:
    1. El módulo 80 consulta la SBS y, con --pronosticar, ejecuta el modelo 79.
    2. El módulo 79C actualiza la explicación por índices.
    """
    candidatos_80 = [
        raiz / "src" / "80_monitor_sbs_y_validar_pronosticos_CORREGIDO.py",
        raiz / "src" / "80_monitor_sbs_y_validar_pronosticos.py",
    ]
    candidatos_79 = [
        raiz / "src" / "79_congelar_modelo_y_estimar_prospectivamente_CORREGIDO.py",
        raiz / "src" / "79_congelar_modelo_y_estimar_prospectivamente.py",
        raiz / "79_congelar_modelo_y_estimar_prospectivamente_CORREGIDO.py",
        raiz / "79_congelar_modelo_y_estimar_prospectivamente.py",
    ]
    candidatos_79c = [
        raiz / "src" / "79C_exportar_ecuaciones_exactas_y_contribuciones_CORREGIDO.py",
        raiz / "src" / "79C_exportar_ecuaciones_exactas_y_contribuciones.py",
        raiz / "79C_exportar_ecuaciones_exactas_y_contribuciones_CORREGIDO.py",
        raiz / "79C_exportar_ecuaciones_exactas_y_contribuciones.py",
    ]

    modulo80 = next((p for p in candidatos_80 if p.exists()), None)
    if modulo80 is not None:
        print(f"\nConsultando SBS y actualizando el pronóstico con {modulo80.name}...")
        resultado = subprocess.run(
            [sys.executable, str(modulo80), "--pronosticar"],
            cwd=str(raiz),
            check=False,
        )
        if resultado.returncode != 0:
            print(
                f"Advertencia: {modulo80.name} terminó con código "
                f"{resultado.returncode}. Se usarán los últimos datos guardados."
            )
    else:
        print(
            "Advertencia: no encontré el módulo 80. "
            "Intentaré actualizar solamente el modelo 79."
        )
        modulo79 = next((p for p in candidatos_79 if p.exists()), None)
        if modulo79 is not None:
            resultado = subprocess.run(
                [sys.executable, str(modulo79)],
                cwd=str(raiz),
                check=False,
            )
            if resultado.returncode != 0:
                print(
                    f"Advertencia: {modulo79.name} terminó con código "
                    f"{resultado.returncode}."
                )
        else:
            print("Advertencia: tampoco encontré el módulo 79.")

    modulo79c = next((p for p in candidatos_79c if p.exists()), None)
    if modulo79c is not None:
        print(f"\nActualizando explicación por índices con {modulo79c.name}...")
        resultado = subprocess.run(
            [sys.executable, str(modulo79c)],
            cwd=str(raiz),
            check=False,
        )
        if resultado.returncode != 0:
            print(
                f"Advertencia: {modulo79c.name} terminó con código "
                f"{resultado.returncode}. Se usarán las últimas contribuciones guardadas."
            )
    else:
        print(
            "Advertencia: no encontré el módulo 79C. "
            "La vista de índices usará la última información disponible."
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Genera un monitor práctico del Fondo 3 con cinco vistas."
    )
    parser.add_argument("--abrir", action="store_true", help="Abre el monitor al terminar.")
    parser.add_argument(
        "--actualizar",
        action="store_true",
        help="Ejecuta primero los módulos 79 y 79C para renovar el pronóstico.",
    )
    args = parser.parse_args()

    raiz = detectar_raiz_proyecto()
    processed = raiz / "data" / "processed"

    print(f"Raíz del proyecto: {raiz}")
    asegurar_historico_completo(raiz)

    if args.actualizar:
        ejecutar_actualizacion_modelo(raiz)
        modulo99 = raiz / "src" / "99_cuota_sintetica_intradia.py"
        if modulo99.exists():
            resultado99 = subprocess.run(
                [sys.executable, str(modulo99)],
                cwd=str(raiz),
                check=False,
            )
            if resultado99.returncode != 0:
                print(
                    f"Advertencia: {modulo99.name} termin? con c?digo "
                    f"{resultado99.returncode}. Se usar? el historial intrad?a disponible."
                )

    oficial, fuente_oficial = cargar_oficial(processed)
    historico, snapshot = cargar_pronosticos(processed)
    operativo = cargar_pronosticos_operativos(processed)
    historico_modelo, fuente_historico_modelo = cargar_serie_historica_modelo(
        processed,
        oficial,
        historico,
    )
    contribuciones = cargar_contribuciones(processed)
    metricas = cargar_metricas(processed)
    estado_canasta = cargar_estado_canasta(processed)
    intradia = cargar_intradia(processed)

    payload = construir_payload(
        oficial,
        historico,
        snapshot,
        operativo,
        contribuciones,
        metricas,
        fuente_oficial,
        estado_canasta,
        historico_modelo,
        fuente_historico_modelo,
        intradia,
    )
    html = crear_html(processed, payload)
    lanzador = None
    if os.environ.get("GITHUB_ACTIONS") != "true":
        lanzador = crear_lanzador(raiz)

    print("\nMONITOR FONDO 3 ACTUALIZADO")
    print(f" - Página: {html.resolve()}")
    if lanzador is not None:
        print(f" - Acceso: {lanzador.resolve()}")
    print("\nContiene cinco vistas:")
    print(" 1. Pronostico diario")
    print(" 2. Evolucion del valor cuota")
    print(" 3. Indices que lo mueven")
    print(" 4. Simulador")
    print(" 5. Vela intradia")

    if args.abrir:
        try:
            os.startfile(str(html.resolve()))
        except Exception:
            webbrowser.open(html.resolve().as_uri())


if __name__ == "__main__":
    main()


