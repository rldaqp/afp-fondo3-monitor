from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests


OPENFIGI_URL = "https://api.openfigi.com/v3/mapping"
TIMEOUT_SEGUNDOS = 90
MAX_REINTENTOS = 4


def leer_csv(ruta: Path, fechas: list[str] | None = None) -> pd.DataFrame:
    if not ruta.exists():
        raise FileNotFoundError(f"No existe: {ruta}")

    return pd.read_csv(
        ruta,
        parse_dates=fechas or [],
    )


def limpiar_texto(valor: object) -> str:
    if pd.isna(valor):
        return ""
    return re.sub(r"\s+", " ", str(valor)).strip()


def normalizar_nombre(valor: object) -> str:
    texto = limpiar_texto(valor).upper()
    texto = re.sub(r"[^A-Z0-9]+", " ", texto)
    return re.sub(r"\s+", " ", texto).strip()


def moda_no_vacia(serie: pd.Series) -> str:
    valores = [
        limpiar_texto(x)
        for x in serie
        if limpiar_texto(x)
    ]
    if not valores:
        return ""

    conteos = pd.Series(valores).value_counts()
    return str(conteos.index[0])


def validar_formato_isin(isin: str) -> bool:
    return bool(
        re.fullmatch(
            r"[A-Z]{2}[A-Z0-9]{9}[0-9]",
            isin.upper(),
        )
    )


def expandir_isin(isin: str) -> str:
    partes = []

    for caracter in isin.upper():
        if caracter.isdigit():
            partes.append(caracter)
        elif "A" <= caracter <= "Z":
            partes.append(str(ord(caracter) - 55))
        else:
            return ""

    return "".join(partes)


def validar_checksum_isin(isin: str) -> bool:
    if not validar_formato_isin(isin):
        return False

    expandido = expandir_isin(isin)
    if not expandido:
        return False

    total = 0
    duplicar = False

    for caracter in reversed(expandido):
        digito = int(caracter)

        if duplicar:
            digito *= 2
            if digito > 9:
                digito -= 9

        total += digito
        duplicar = not duplicar

    return total % 10 == 0


def corregir_checksum_posible(identificador: str) -> str:
    codigo = limpiar_texto(identificador).upper().replace(" ", "")

    if len(codigo) != 12:
        return ""
    if not re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}[A-Z0-9]", codigo):
        return ""

    base = codigo[:11]

    for digito in "0123456789":
        candidato = base + digito
        if validar_checksum_isin(candidato):
            return candidato

    return ""


def preparar_universo(df: pd.DataFrame) -> pd.DataFrame:
    salida = df.copy()

    if "isin_normalizado" not in salida.columns:
        raise ValueError(
            "El universo no contiene la columna isin_normalizado."
        )

    salida["isin_normalizado"] = (
        salida["isin_normalizado"]
        .fillna("")
        .astype(str)
        .str.upper()
        .str.replace(r"\s+", "", regex=True)
    )

    for columna in [
        "clasificacion_identificador",
        "gestora_reportada",
        "moneda_reportada",
        "lista_afp",
    ]:
        if columna not in salida.columns:
            salida[columna] = ""
        salida[columna] = salida[columna].fillna("").astype(str)

    for columna in [
        "peso_max_total_fondo_pct",
        "peso_mediano_total_fondo_pct",
        "peso_max_exterior_pct",
        "meses_presentes",
        "afp_presentes",
    ]:
        if columna not in salida.columns:
            salida[columna] = np.nan
        salida[columna] = pd.to_numeric(
            salida[columna],
            errors="coerce",
        )

    return salida


def preparar_resultados(df: pd.DataFrame) -> pd.DataFrame:
    salida = df.copy()

    for columna in [
        "isin",
        "figi",
        "compositeFIGI",
        "shareClassFIGI",
        "ticker",
        "name",
        "exchCode",
        "marketSector",
        "securityType",
        "securityType2",
        "securityDescription",
    ]:
        if columna not in salida.columns:
            salida[columna] = ""
        salida[columna] = salida[columna].fillna("").astype(str)

    salida["isin"] = (
        salida["isin"]
        .str.upper()
        .str.replace(r"\s+", "", regex=True)
    )
    salida["name_norm"] = salida["name"].map(normalizar_nombre)
    salida["ticker_norm"] = salida["ticker"].map(normalizar_nombre)
    salida["security_type_norm"] = salida[
        "securityType2"
    ].map(normalizar_nombre)
    salida["composite_norm"] = salida[
        "compositeFIGI"
    ].map(limpiar_texto)
    salida["shareclass_norm"] = salida[
        "shareClassFIGI"
    ].map(limpiar_texto)

    if "puntaje_seleccion" not in salida.columns:
        salida["puntaje_seleccion"] = 0.0
    salida["puntaje_seleccion"] = pd.to_numeric(
        salida["puntaje_seleccion"],
        errors="coerce",
    ).fillna(0.0)

    if "numero_resultado" not in salida.columns:
        salida["numero_resultado"] = np.arange(
            1,
            len(salida) + 1,
        )

    return salida


def clasificar_ambiguedad_grupo(grupo: pd.DataFrame) -> dict[str, Any]:
    resultados = len(grupo)
    shareclasses = {
        x
        for x in grupo["shareclass_norm"]
        if limpiar_texto(x)
    }
    composites = {
        x
        for x in grupo["composite_norm"]
        if limpiar_texto(x)
    }
    nombres = {
        x
        for x in grupo["name_norm"]
        if limpiar_texto(x)
    }
    tickers = {
        x
        for x in grupo["ticker_norm"]
        if limpiar_texto(x)
    }
    tipos = {
        x
        for x in grupo["security_type_norm"]
        if limpiar_texto(x)
    }

    if resultados == 1:
        clase = "unico"
        razon = "un_solo_resultado"
    elif len(shareclasses) == 1 and shareclasses:
        clase = "ambiguedad_benigna"
        razon = "misma_shareclass_figi"
    elif len(composites) == 1 and composites:
        clase = "ambiguedad_benigna"
        razon = "misma_composite_figi"
    elif len(nombres) == 1 and len(tipos) <= 1:
        clase = "ambiguedad_benigna"
        razon = "mismo_nombre_y_tipo"
    elif len(nombres) == 1 and len(tickers) <= 1:
        clase = "ambiguedad_benigna"
        razon = "mismo_nombre_y_ticker"
    else:
        clase = "ambiguedad_sustantiva"
        razon = "multiples_identidades_economicas"

    return {
        "numero_resultados": resultados,
        "shareclass_unicas": len(shareclasses),
        "composite_unicas": len(composites),
        "nombres_unicos": len(nombres),
        "tickers_unicos": len(tickers),
        "tipos_unicos": len(tipos),
        "clase_ambiguedad": clase,
        "razon_ambiguedad": razon,
    }


def construir_control_ambiguedad(
    resultados: pd.DataFrame,
) -> pd.DataFrame:
    filas = []

    for isin, grupo in resultados.groupby("isin"):
        fila = {"isin": isin}
        fila.update(clasificar_ambiguedad_grupo(grupo))
        filas.append(fila)

    return pd.DataFrame(filas)


def puntuar_canonico(
    grupo: pd.DataFrame,
) -> pd.DataFrame:
    salida = grupo.copy()

    shareclass_moda = moda_no_vacia(
        salida["shareclass_norm"]
    )
    composite_moda = moda_no_vacia(
        salida["composite_norm"]
    )
    nombre_moda = moda_no_vacia(
        salida["name_norm"]
    )
    tipo_moda = moda_no_vacia(
        salida["security_type_norm"]
    )

    salida["score_canonico"] = salida[
        "puntaje_seleccion"
    ].fillna(0.0)

    if shareclass_moda:
        salida["score_canonico"] += np.where(
            salida["shareclass_norm"].eq(shareclass_moda),
            100.0,
            0.0,
        )
    if composite_moda:
        salida["score_canonico"] += np.where(
            salida["composite_norm"].eq(composite_moda),
            50.0,
            0.0,
        )
    if nombre_moda:
        salida["score_canonico"] += np.where(
            salida["name_norm"].eq(nombre_moda),
            25.0,
            0.0,
        )
    if tipo_moda:
        salida["score_canonico"] += np.where(
            salida["security_type_norm"].eq(tipo_moda),
            10.0,
            0.0,
        )

    salida["score_canonico"] += np.where(
        salida["shareClassFIGI"].str.len() > 0,
        8.0,
        0.0,
    )
    salida["score_canonico"] += np.where(
        salida["compositeFIGI"].str.len() > 0,
        5.0,
        0.0,
    )
    salida["score_canonico"] += np.where(
        salida["ticker"].str.len() > 0,
        2.0,
        0.0,
    )
    salida["score_canonico"] += np.where(
        salida["name"].str.len() > 0,
        1.0,
        0.0,
    )

    return salida


def seleccionar_canonicos(
    resultados: pd.DataFrame,
    control: pd.DataFrame,
) -> pd.DataFrame:
    seleccionados = []

    for isin, grupo in resultados.groupby("isin"):
        scored = puntuar_canonico(grupo)
        mejor = (
            scored.sort_values(
                [
                    "score_canonico",
                    "puntaje_seleccion",
                    "numero_resultado",
                ],
                ascending=[False, False, True],
            )
            .iloc[0]
            .to_dict()
        )
        seleccionados.append(mejor)

    canonicos = pd.DataFrame(seleccionados)

    canonicos["canonical_security_id"] = np.where(
        canonicos["shareClassFIGI"].str.len() > 0,
        canonicos["shareClassFIGI"],
        np.where(
            canonicos["compositeFIGI"].str.len() > 0,
            canonicos["compositeFIGI"],
            canonicos["figi"],
        ),
    )

    canonicos = canonicos.merge(
        control,
        on="isin",
        how="left",
        validate="one_to_one",
    )

    canonicos["mapeo_aceptable_automatico"] = (
        canonicos["clase_ambiguedad"].isin(
            ["unico", "ambiguedad_benigna"]
        )
        & canonicos["canonical_security_id"].fillna("").ne("")
        & canonicos["name"].fillna("").ne("")
    )

    return canonicos


def cargar_cache(ruta: Path) -> dict[str, Any]:
    if not ruta.exists():
        return {}

    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def guardar_cache(ruta: Path, cache: dict[str, Any]) -> None:
    ruta.write_text(
        json.dumps(
            cache,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def crear_sesion(api_key: str) -> requests.Session:
    sesion = requests.Session()
    sesion.headers.update(
        {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "AFP-Fondo3-Research/1.0",
        }
    )

    if api_key:
        sesion.headers["X-OPENFIGI-APIKEY"] = api_key

    return sesion


def consultar_lote(
    sesion: requests.Session,
    lote: list[str],
) -> list[dict[str, Any]]:
    payload = [
        {
            "idType": "ID_ISIN",
            "idValue": isin,
        }
        for isin in lote
    ]

    ultimo_error = None

    for intento in range(1, MAX_REINTENTOS + 1):
        try:
            respuesta = sesion.post(
                OPENFIGI_URL,
                json=payload,
                timeout=TIMEOUT_SEGUNDOS,
            )

            if respuesta.status_code == 429:
                espera = respuesta.headers.get(
                    "ratelimit-reset",
                    "",
                )
                try:
                    segundos = max(float(espera), 3.0)
                except ValueError:
                    segundos = min(5 * intento, 30)

                time.sleep(segundos)
                continue

            if respuesta.status_code in {500, 502, 503, 504}:
                time.sleep(min(2**intento, 30))
                continue

            respuesta.raise_for_status()
            datos = respuesta.json()

            if not isinstance(datos, list):
                raise RuntimeError(
                    "La respuesta OpenFIGI no es una lista."
                )

            return datos

        except (
            requests.RequestException,
            ValueError,
            RuntimeError,
        ) as error:
            ultimo_error = error

            if intento < MAX_REINTENTOS:
                time.sleep(min(2**intento, 30))

    raise RuntimeError(
        f"No se pudo consultar OpenFIGI: {ultimo_error}"
    )


def generar_correcciones_checksum(
    universo: pd.DataFrame,
    cache_ruta: Path,
) -> pd.DataFrame:
    filas = []

    for _, fila in universo.iterrows():
        original = fila["isin_normalizado"]
        clasificacion = fila[
            "clasificacion_identificador"
        ]

        if original.startswith("PRIV"):
            continue

        candidato = corregir_checksum_posible(original)

        if not candidato or candidato == original:
            continue

        filas.append(
            {
                "identificador_original": original,
                "clasificacion_original": clasificacion,
                "isin_corregido_propuesto": candidato,
                "cambio_realizado": (
                    f"{original[-1]} -> {candidato[-1]}"
                ),
                "peso_max_total_fondo_pct": fila[
                    "peso_max_total_fondo_pct"
                ],
                "meses_presentes": fila["meses_presentes"],
                "gestora_reportada": fila[
                    "gestora_reportada"
                ],
                "lista_afp": fila["lista_afp"],
                "corregido_ya_existe_en_universo": bool(
                    candidato
                    in set(universo["isin_normalizado"])
                ),
            }
        )

    correcciones = pd.DataFrame(filas)

    if correcciones.empty:
        return correcciones

    api_key = limpiar_texto(
        os.environ.get("OPENFIGI_API_KEY", "")
    )
    max_lote = 100 if api_key else 5
    pausa = 0.35 if api_key else 2.6

    cache = cargar_cache(cache_ruta)
    candidatos = sorted(
        set(
            correcciones["isin_corregido_propuesto"]
        )
    )
    pendientes = [
        x
        for x in candidatos
        if x not in cache
    ]

    if pendientes:
        sesion = crear_sesion(api_key)

        print(
            f"\nValidando {len(pendientes)} correcciones "
            "propuestas con OpenFIGI..."
        )

        for inicio in range(0, len(pendientes), max_lote):
            lote = pendientes[inicio : inicio + max_lote]
            respuestas = consultar_lote(sesion, lote)

            for isin, respuesta in zip(lote, respuestas):
                cache[isin] = respuesta

            guardar_cache(cache_ruta, cache)

            if inicio + max_lote < len(pendientes):
                time.sleep(pausa)

    estados = []

    for candidato in correcciones[
        "isin_corregido_propuesto"
    ]:
        respuesta = cache.get(candidato, {})
        datos = respuesta.get("data", [])

        if isinstance(datos, list) and datos:
            primer = datos[0]
            estados.append(
                {
                    "isin_corregido_propuesto": candidato,
                    "correccion_resuelta_openfigi": True,
                    "numero_resultados_corregido": len(datos),
                    "ticker_corregido": limpiar_texto(
                        primer.get("ticker")
                    ),
                    "nombre_corregido": limpiar_texto(
                        primer.get("name")
                    ),
                    "figi_corregido": limpiar_texto(
                        primer.get("figi")
                    ),
                }
            )
        else:
            estados.append(
                {
                    "isin_corregido_propuesto": candidato,
                    "correccion_resuelta_openfigi": False,
                    "numero_resultados_corregido": 0,
                    "ticker_corregido": "",
                    "nombre_corregido": "",
                    "figi_corregido": "",
                }
            )

    estados_df = pd.DataFrame(estados).drop_duplicates(
        subset=["isin_corregido_propuesto"]
    )

    correcciones = correcciones.merge(
        estados_df,
        on="isin_corregido_propuesto",
        how="left",
        validate="many_to_one",
    )

    correcciones["confianza_correccion"] = np.select(
        [
            correcciones[
                "corregido_ya_existe_en_universo"
            ]
            & correcciones[
                "correccion_resuelta_openfigi"
            ],
            correcciones[
                "correccion_resuelta_openfigi"
            ],
            correcciones[
                "corregido_ya_existe_en_universo"
            ],
        ],
        [
            "alta",
            "media_alta",
            "media",
        ],
        default="baja",
    )

    return correcciones.sort_values(
        [
            "confianza_correccion",
            "peso_max_total_fondo_pct",
        ],
        ascending=[True, False],
    )


def construir_revision_manual(
    universo: pd.DataFrame,
    canonicos: pd.DataFrame,
    no_resueltos: pd.DataFrame,
    correcciones: pd.DataFrame,
) -> pd.DataFrame:
    filas = []

    ambiguos = canonicos[
        canonicos["clase_ambiguedad"].eq(
            "ambiguedad_sustantiva"
        )
    ].copy()

    for _, fila in ambiguos.iterrows():
        filas.append(
            {
                "identificador": fila["isin"],
                "motivo_revision": (
                    "ambiguedad_sustantiva_openfigi"
                ),
                "accion_sugerida": (
                    "contrastar nombre, ticker, tipo y gestora"
                ),
                "ticker_provisional": fila["ticker"],
                "nombre_provisional": fila["name"],
                "peso_max_total_fondo_pct": np.nan,
                "meses_presentes": np.nan,
            }
        )

    for _, fila in no_resueltos.iterrows():
        filas.append(
            {
                "identificador": fila[
                    "isin_normalizado"
                ],
                "motivo_revision": fila[
                    "estado_openfigi"
                ],
                "accion_sugerida": (
                    "buscar fuente secundaria o comprobar "
                    "si el instrumento fue liquidado"
                ),
                "ticker_provisional": "",
                "nombre_provisional": "",
                "peso_max_total_fondo_pct": fila[
                    "peso_max_total_fondo_pct"
                ],
                "meses_presentes": fila[
                    "meses_presentes"
                ],
            }
        )

    if not correcciones.empty:
        for _, fila in correcciones.iterrows():
            filas.append(
                {
                    "identificador": fila[
                        "identificador_original"
                    ],
                    "motivo_revision": (
                        "correccion_checksum_propuesta"
                    ),
                    "accion_sugerida": (
                        f"revisar contra {fila['isin_corregido_propuesto']} "
                        f"({fila['confianza_correccion']})"
                    ),
                    "ticker_provisional": fila[
                        "ticker_corregido"
                    ],
                    "nombre_provisional": fila[
                        "nombre_corregido"
                    ],
                    "peso_max_total_fondo_pct": fila[
                        "peso_max_total_fondo_pct"
                    ],
                    "meses_presentes": fila[
                        "meses_presentes"
                    ],
                }
            )

    revision = pd.DataFrame(filas)

    if revision.empty:
        return revision

    pesos = universo[
        [
            "isin_normalizado",
            "peso_max_total_fondo_pct",
            "meses_presentes",
            "gestora_reportada",
            "lista_afp",
        ]
    ].rename(
        columns={
            "isin_normalizado": "identificador",
            "peso_max_total_fondo_pct": (
                "peso_universo_pct"
            ),
            "meses_presentes": "meses_universo",
        }
    )

    revision = revision.merge(
        pesos,
        on="identificador",
        how="left",
        validate="many_to_one",
    )

    revision["peso_prioridad_pct"] = revision[
        "peso_max_total_fondo_pct"
    ].fillna(
        revision["peso_universo_pct"]
    )
    revision["meses_prioridad"] = revision[
        "meses_presentes"
    ].fillna(
        revision["meses_universo"]
    )

    return revision.sort_values(
        [
            "peso_prioridad_pct",
            "meses_prioridad",
        ],
        ascending=[False, False],
    )


def main() -> None:
    raiz = Path(__file__).resolve().parents[1]
    processed = raiz / "data" / "processed"

    universo = preparar_universo(
        leer_csv(
            processed
            / "ca0001_isin_universo_priorizado.csv",
            ["primera_fecha", "ultima_fecha"],
        )
    )
    resultados = preparar_resultados(
        leer_csv(
            processed
            / "ca0001_isin_openfigi_todos_resultados.csv"
        )
    )
    no_resueltos = leer_csv(
        processed
        / "ca0001_isin_openfigi_no_resueltos.csv",
        ["primera_fecha", "ultima_fecha"],
    )

    control_amb = construir_control_ambiguedad(
        resultados
    )
    canonicos = seleccionar_canonicos(
        resultados,
        control_amb,
    )

    canonicos = canonicos.merge(
        universo[
            [
                "isin_normalizado",
                "peso_max_total_fondo_pct",
                "meses_presentes",
                "gestora_reportada",
                "moneda_reportada",
                "lista_afp",
            ]
        ],
        left_on="isin",
        right_on="isin_normalizado",
        how="left",
        validate="one_to_one",
    )

    cache_ruta = (
        processed
        / "ca0001_openfigi_cache_isin.json"
    )

    correcciones = generar_correcciones_checksum(
        universo,
        cache_ruta,
    )

    revision = construir_revision_manual(
        universo,
        canonicos,
        no_resueltos,
        correcciones,
    )

    resumen = (
        canonicos.groupby(
            "clase_ambiguedad",
            as_index=False,
        )
        .agg(
            identificadores=("isin", "nunique"),
            aceptables_automaticamente=(
                "mapeo_aceptable_automatico",
                "sum",
            ),
            peso_maximo_pct=(
                "peso_max_total_fondo_pct",
                "max",
            ),
            meses_mediana=("meses_presentes", "median"),
        )
        .sort_values(
            "identificadores",
            ascending=False,
        )
    )

    rutas = {
        "control_ambiguedad": (
            processed
            / "ca0001_isin_openfigi_ambiguedad_clasificada.csv"
        ),
        "canonicos": (
            processed
            / "ca0001_isin_openfigi_mapeo_canonico.csv"
        ),
        "correcciones": (
            processed
            / "ca0001_isin_correcciones_checksum_propuestas.csv"
        ),
        "revision": (
            processed
            / "ca0001_isin_revision_manual_priorizada.csv"
        ),
        "resumen": (
            processed
            / "ca0001_isin_openfigi_resumen_ambiguedad.csv"
        ),
    }

    control_amb.to_csv(
        rutas["control_ambiguedad"],
        index=False,
        encoding="utf-8-sig",
    )
    canonicos.to_csv(
        rutas["canonicos"],
        index=False,
        encoding="utf-8-sig",
    )
    correcciones.to_csv(
        rutas["correcciones"],
        index=False,
        encoding="utf-8-sig",
    )
    revision.to_csv(
        rutas["revision"],
        index=False,
        encoding="utf-8-sig",
    )
    resumen.to_csv(
        rutas["resumen"],
        index=False,
        encoding="utf-8-sig",
    )

    print("\nAUDITORÍA DE AMBIGÜEDAD Y CHECKSUM TERMINADA")
    print("=" * 118)

    print("\nRESUMEN DE AMBIGÜEDAD")
    print("-" * 118)
    print(resumen.to_string(index=False))

    print("\nMAPEOS CANÓNICOS DE MAYOR PESO")
    print("-" * 118)
    print(
        canonicos.sort_values(
            "peso_max_total_fondo_pct",
            ascending=False,
        )[
            [
                "isin",
                "canonical_security_id",
                "ticker",
                "name",
                "securityType2",
                "clase_ambiguedad",
                "razon_ambiguedad",
                "numero_resultados",
                "mapeo_aceptable_automatico",
                "peso_max_total_fondo_pct",
                "meses_presentes",
            ]
        ]
        .head(40)
        .to_string(index=False)
    )

    print("\nCORRECCIONES DE CHECKSUM PROPUESTAS")
    print("-" * 118)
    if correcciones.empty:
        print("No se generaron propuestas.")
    else:
        print(
            correcciones[
                [
                    "identificador_original",
                    "isin_corregido_propuesto",
                    "cambio_realizado",
                    "correccion_resuelta_openfigi",
                    "ticker_corregido",
                    "nombre_corregido",
                    "confianza_correccion",
                    "peso_max_total_fondo_pct",
                    "meses_presentes",
                ]
            ]
            .head(40)
            .to_string(index=False)
        )

    print("\nREVISIÓN MANUAL PRIORITARIA")
    print("-" * 118)
    if revision.empty:
        print("No hay registros pendientes de revisión.")
    else:
        print(
            revision[
                [
                    "identificador",
                    "motivo_revision",
                    "accion_sugerida",
                    "ticker_provisional",
                    "nombre_provisional",
                    "peso_prioridad_pct",
                    "meses_prioridad",
                    "gestora_reportada",
                    "lista_afp",
                ]
            ]
            .head(50)
            .to_string(index=False)
        )

    print("\nArchivos creados:")
    for ruta in rutas.values():
        print(f" - {ruta.resolve()}")

    print(
        "\nCriterio metodológico:\n"
        "- Varias respuestas de OpenFIGI no implican necesariamente varias "
        "inversiones: con frecuencia son distintas plazas de negociación "
        "del mismo shareClassFIGI.\n"
        "- Una ambigüedad se considera benigna cuando los resultados "
        "comparten shareClassFIGI, compositeFIGI o la misma identidad "
        "económica básica.\n"
        "- El identificador canónico prioriza shareClassFIGI, después "
        "compositeFIGI y finalmente FIGI de plaza.\n"
        "- Las correcciones de checksum son propuestas de auditoría; solo "
        "deben incorporarse a la base cuando OpenFIGI o una fuente primaria "
        "confirme el código corregido.\n"
        "- Los casos sustantivamente ambiguos y los no resueltos se "
        "mantienen fuera del enriquecimiento automático de país, sector e "
        "índice hasta su revisión."
    )


if __name__ == "__main__":
    main()
