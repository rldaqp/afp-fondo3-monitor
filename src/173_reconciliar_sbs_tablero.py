from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


AFPS = ["Habitat", "Integra", "Prima", "Profuturo"]


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


def normalizar_nombre(valor: Any) -> str:
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


def normalizar_afp(valor: Any) -> str:
    texto = str(valor).strip().lower()
    mapa = {
        "habitat": "Habitat",
        "integra": "Integra",
        "prima": "Prima",
        "profuturo": "Profuturo",
    }
    return mapa.get(texto, str(valor).strip())


def a_fecha(valores: Any) -> Any:
    try:
        return pd.to_datetime(valores, errors="coerce", format="mixed")
    except (TypeError, ValueError):
        return pd.to_datetime(valores, errors="coerce")


def extraer_oficial(ruta: Path, prioridad: int) -> pd.DataFrame:
    df = leer_csv(ruta)
    if df.empty:
        return pd.DataFrame()

    columnas = {normalizar_nombre(c): c for c in df.columns}
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
        "cuota_real",
        "valor",
    )
    aliases_fondo = (
        "fondo",
        "tipo_fondo",
        "tipo_de_fondo",
        "fondo_tipo",
        "numero_fondo",
    )

    c_fecha = next((columnas[x] for x in aliases_fecha if x in columnas), None)
    c_afp = next((columnas[x] for x in aliases_afp if x in columnas), None)
    c_cuota = next((columnas[x] for x in aliases_cuota if x in columnas), None)
    c_fondo = next((columnas[x] for x in aliases_fondo if x in columnas), None)

    if c_fecha is None:
        return pd.DataFrame()

    if c_afp is not None and c_cuota is not None:
        cols = [c_afp, c_fecha, c_cuota]
        if c_fondo is not None:
            cols.append(c_fondo)
        x = df[cols].copy()
        if c_fondo is not None:
            fondo = x[c_fondo].astype(str).str.strip().str.lower()
            mascara = (
                fondo.str.contains(r"(?:fondo\s*)?3", regex=True, na=False)
                | fondo.eq("3")
                | fondo.eq("3.0")
            )
            if mascara.any():
                x = x.loc[mascara].copy()
        x = x[[c_afp, c_fecha, c_cuota]]
        x.columns = ["afp", "fecha", "cuota_real"]
    else:
        columnas_afp: dict[str, str] = {}
        for afp in AFPS:
            clave = normalizar_nombre(afp)
            candidatos = (
                clave,
                f"cuota_{clave}",
                f"valor_cuota_{clave}",
                f"{clave}_fondo_3",
                f"{clave}_fondo3",
            )
            encontrada = next(
                (columnas[c] for c in candidatos if c in columnas),
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
    x["fecha"] = a_fecha(x["fecha"]).dt.normalize()
    x["cuota_real"] = pd.to_numeric(x["cuota_real"], errors="coerce")
    x["prioridad_fuente"] = prioridad
    x["fuente_sbs"] = ruta.name

    return (
        x.dropna(subset=["afp", "fecha", "cuota_real"])
        .loc[lambda z: z["afp"].isin(AFPS)]
        .loc[lambda z: z["cuota_real"].gt(0)]
        .drop_duplicates(["afp", "fecha"], keep="last")
        .reset_index(drop=True)
    )


def cargar_oficiales(processed: Path) -> pd.DataFrame:
    candidatos = [
        processed / "sbs_fondo3_historico_largo.csv",
        processed / "sbs_fondo3_historico_ancho.csv",
        processed / "sbs_fondo3_base_maestra.csv",
        processed / "sbs_fondo3_base_maestra_ancha.csv",
        processed / "ca0001_modelo80_sbs_oficial_detectado.csv",
        processed / "ca0001_modelo56_base_alineada.csv",
    ]

    partes: list[pd.DataFrame] = []
    for prioridad, ruta in enumerate(candidatos):
        if not ruta.exists():
            continue
        try:
            x = extraer_oficial(ruta, prioridad)
        except Exception as exc:
            print(f"Advertencia al leer {ruta.name}: {exc}")
            continue
        if not x.empty:
            partes.append(x)

    if not partes:
        raise FileNotFoundError(
            "No se encontro ninguna fuente oficial SBS utilizable para reconciliar el tablero."
        )

    oficial = pd.concat(partes, ignore_index=True)
    oficial = (
        oficial.sort_values(
            ["afp", "fecha", "prioridad_fuente"],
            ascending=[True, True, True],
        )
        .drop_duplicates(["afp", "fecha"], keep="first")
        .sort_values(["afp", "fecha"])
        .reset_index(drop=True)
    )
    oficial["retorno_real"] = oficial.groupby("afp")["cuota_real"].pct_change()
    return oficial


def actualizar_bitacora(processed: Path, oficial: pd.DataFrame) -> pd.DataFrame:
    ruta = processed / "tablero_operativo_bitacora_diaria.csv"
    bitacora = leer_csv(ruta)
    if bitacora.empty:
        raise FileNotFoundError(
            "Falta tablero_operativo_bitacora_diaria.csv. Ejecuta primero 170 y 172."
        )

    bitacora["fecha"] = a_fecha(bitacora["fecha"]).dt.normalize()
    bitacora["afp"] = bitacora["afp"].map(normalizar_afp)

    mapa_cuota = oficial.set_index(["afp", "fecha"])["cuota_real"].to_dict()
    mapa_retorno = oficial.set_index(["afp", "fecha"])["retorno_real"].to_dict()
    mapa_fuente = oficial.set_index(["afp", "fecha"])["fuente_sbs"].to_dict()

    claves = list(zip(bitacora["afp"], bitacora["fecha"]))
    cuota_oficial = pd.Series([mapa_cuota.get(k, np.nan) for k in claves], index=bitacora.index)
    retorno_oficial = pd.Series([mapa_retorno.get(k, np.nan) for k in claves], index=bitacora.index)
    fuente_oficial = pd.Series([mapa_fuente.get(k, "") for k in claves], index=bitacora.index)

    existe = cuota_oficial.notna()
    bitacora.loc[existe, "sbs_publicada"] = cuota_oficial.loc[existe]
    bitacora.loc[existe, "retorno_real"] = retorno_oficial.loc[existe]
    bitacora.loc[existe, "fuente_sbs"] = fuente_oficial.loc[existe]

    cuota_estimada = pd.to_numeric(bitacora.get("cuota_estimada"), errors="coerce")
    retorno_estimado = pd.to_numeric(bitacora.get("retorno_estimado"), errors="coerce")
    real = pd.to_numeric(bitacora.get("sbs_publicada"), errors="coerce")
    retorno_real = pd.to_numeric(bitacora.get("retorno_real"), errors="coerce")

    evaluable = real.notna() & cuota_estimada.notna()
    bitacora.loc[evaluable, "error_cuota"] = (
        cuota_estimada.loc[evaluable] - real.loc[evaluable]
    )
    bitacora.loc[evaluable, "error_abs_pct"] = (
        (cuota_estimada.loc[evaluable] - real.loc[evaluable]).abs()
        / real.loc[evaluable]
        * 100.0
    )

    direccion_evaluable = evaluable & retorno_estimado.notna() & retorno_real.notna()
    acierto = (
        np.sign(retorno_estimado.loc[direccion_evaluable])
        == np.sign(retorno_real.loc[direccion_evaluable])
    )
    bitacora.loc[direccion_evaluable, "acierto_direccion"] = acierto.to_numpy()
    bitacora.loc[direccion_evaluable, "resultado"] = np.where(
        acierto.to_numpy(), "Acierto", "Fallo"
    )

    pendientes = real.isna()
    bitacora.loc[pendientes, "resultado"] = "Pendiente SBS"

    bitacora = bitacora.sort_values(["afp", "fecha"]).reset_index(drop=True)
    escribir_csv(bitacora, ruta)

    fecha_max = bitacora["fecha"].max()
    ultima = bitacora.groupby("afp", as_index=False).tail(1)
    ultimos = bitacora[bitacora["fecha"].ge(fecha_max - pd.Timedelta(days=30))]
    grafico = bitacora[bitacora["fecha"].ge(fecha_max - pd.Timedelta(days=24))][
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

    escribir_csv(ultima, processed / "tablero_operativo_ultima_senal.csv")
    escribir_csv(ultimos, processed / "tablero_operativo_ultimos_dias.csv")
    escribir_csv(grafico, processed / "tablero_operativo_grafico.csv")
    return bitacora


def auditar(oficial: pd.DataFrame, bitacora: pd.DataFrame, processed: Path) -> pd.DataFrame:
    ultima_oficial = (
        oficial.sort_values(["afp", "fecha"])
        .groupby("afp", as_index=False)
        .tail(1)[["afp", "fecha", "cuota_real", "fuente_sbs"]]
        .rename(
            columns={
                "fecha": "ultima_fecha_sbs",
                "cuota_real": "ultima_cuota_sbs",
            }
        )
    )
    ultima_reconciliada = (
        bitacora[bitacora["sbs_publicada"].notna()]
        .groupby("afp", as_index=False)["fecha"]
        .max()
        .rename(columns={"fecha": "ultima_fecha_reconciliada"})
    )
    auditoria = ultima_oficial.merge(ultima_reconciliada, on="afp", how="left")
    auditoria["estado"] = np.where(
        auditoria["ultima_fecha_reconciliada"].ge(auditoria["ultima_fecha_sbs"]),
        "CORRECTO",
        "DESACTUALIZADO",
    )
    escribir_csv(auditoria, processed / "tablero_operativo_auditoria_sbs.csv")
    return auditoria


def main() -> None:
    raiz = Path(__file__).resolve().parents[1]
    processed = raiz / "data" / "processed"
    oficial = cargar_oficiales(processed)
    bitacora = actualizar_bitacora(processed, oficial)
    auditoria = auditar(oficial, bitacora, processed)

    print("Cuotas oficiales SBS reconciliadas sin modificar la canasta congelada")
    print(auditoria.to_string(index=False))


if __name__ == "__main__":
    main()
