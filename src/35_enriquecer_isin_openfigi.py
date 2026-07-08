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
MAX_REINTENTOS = 5

PESO_PRIORIDAD_PRINCIPAL = 1_000_000
PESO_PRIORIDAD_AMPLIADO = 100_000


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


def convertir_booleano(serie: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(serie):
        return serie.fillna(False)

    return (
        serie.fillna(False)
        .astype(str)
        .str.strip()
        .str.lower()
        .isin({"true", "1", "si", "sí", "yes"})
    )


def validar_formato_isin(isin: str) -> bool:
    return bool(
        re.fullmatch(
            r"[A-Z]{2}[A-Z0-9]{9}[0-9]",
            isin.upper(),
        )
    )


def expandir_isin_para_luhn(isin: str) -> str:
    salida = []

    for caracter in isin.upper():
        if caracter.isdigit():
            salida.append(caracter)
        elif "A" <= caracter <= "Z":
            salida.append(str(ord(caracter) - 55))
        else:
            return ""

    return "".join(salida)


def validar_checksum_isin(isin: str) -> bool:
    """
    Valida el dígito de control del ISIN mediante Luhn.
    """
    if not validar_formato_isin(isin):
        return False

    expandido = expandir_isin_para_luhn(isin)
    if not expandido:
        return False

    total = 0
    invertir = False

    for caracter in reversed(expandido):
        digito = int(caracter)

        if invertir:
            digito *= 2
            if digito > 9:
                digito -= 9

        total += digito
        invertir = not invertir

    return total % 10 == 0


def preparar_base(base: pd.DataFrame) -> pd.DataFrame:
    salida = base.copy()

    salida["fecha_cartera"] = pd.to_datetime(
        salida["fecha_cartera"],
        errors="coerce",
    )

    for columna in [
        "identificador_final",
        "isin",
        "tipo_identificador",
        "afp",
        "moneda",
        "entidad_administradora",
        "estado_cobertura",
    ]:
        if columna not in salida.columns:
            salida[columna] = ""
        salida[columna] = salida[columna].map(limpiar_texto)

    for columna in [
        "peso_total_fondo_reconciliado_pct",
        "peso_exterior_reconciliado_pct",
        "valor_reconciliado_miles_soles",
    ]:
        salida[columna] = pd.to_numeric(
            salida[columna],
            errors="coerce",
        )

    salida["usar_modelo_principal"] = convertir_booleano(
        salida["usar_modelo_principal"]
    )
    salida["usar_analisis_ampliado"] = convertir_booleano(
        salida["usar_analisis_ampliado"]
    )

    salida["isin_normalizado"] = (
        salida["isin"]
        .str.upper()
        .str.replace(r"\s+", "", regex=True)
    )

    salida = salida[
        salida["tipo_identificador"].eq("isin")
        & salida["isin_normalizado"].ne("")
    ].copy()

    salida["formato_isin_valido"] = salida[
        "isin_normalizado"
    ].map(validar_formato_isin)
    salida["checksum_isin_valido"] = salida[
        "isin_normalizado"
    ].map(validar_checksum_isin)
    salida["prefijo_isin"] = salida[
        "isin_normalizado"
    ].str[:2]

    return salida


def construir_universo(base: pd.DataFrame) -> pd.DataFrame:
    resumen = (
        base.groupby(
            "isin_normalizado",
            as_index=False,
        )
        .agg(
            primera_fecha=("fecha_cartera", "min"),
            ultima_fecha=("fecha_cartera", "max"),
            meses_presentes=("fecha_cartera", "nunique"),
            afp_presentes=("afp", "nunique"),
            lista_afp=(
                "afp",
                lambda s: " | ".join(sorted(set(s))),
            ),
            moneda_reportada=(
                "moneda",
                lambda s: " | ".join(
                    sorted(
                        {
                            limpiar_texto(x).upper()
                            for x in s
                            if limpiar_texto(x)
                        }
                    )
                ),
            ),
            gestora_reportada=(
                "entidad_administradora",
                lambda s: " | ".join(
                    sorted(
                        {
                            limpiar_texto(x)
                            for x in s
                            if limpiar_texto(x)
                        }
                    )
                ),
            ),
            peso_max_total_fondo_pct=(
                "peso_total_fondo_reconciliado_pct",
                "max",
            ),
            peso_mediano_total_fondo_pct=(
                "peso_total_fondo_reconciliado_pct",
                "median",
            ),
            peso_max_exterior_pct=(
                "peso_exterior_reconciliado_pct",
                "max",
            ),
            valor_max_reconciliado_miles_soles=(
                "valor_reconciliado_miles_soles",
                "max",
            ),
            aparece_modelo_principal=(
                "usar_modelo_principal",
                "max",
            ),
            aparece_analisis_ampliado=(
                "usar_analisis_ampliado",
                "max",
            ),
            formato_isin_valido=(
                "formato_isin_valido",
                "max",
            ),
            checksum_isin_valido=(
                "checksum_isin_valido",
                "max",
            ),
            prefijo_isin=("prefijo_isin", "first"),
        )
    )

    resumen["prioridad"] = (
        resumen["aparece_modelo_principal"].astype(int)
        * PESO_PRIORIDAD_PRINCIPAL
        + resumen["aparece_analisis_ampliado"].astype(int)
        * PESO_PRIORIDAD_AMPLIADO
        + resumen["peso_max_total_fondo_pct"].fillna(0.0) * 1_000
        + resumen["meses_presentes"].fillna(0)
    )

    resumen["clasificacion_identificador"] = np.select(
        [
            resumen["formato_isin_valido"]
            & resumen["checksum_isin_valido"],
            resumen["formato_isin_valido"]
            & ~resumen["checksum_isin_valido"],
        ],
        [
            "isin_estandar_valido",
            "formato_isin_checksum_invalido",
        ],
        default="identificador_no_estandar",
    )

    return resumen.sort_values(
        ["prioridad", "peso_max_total_fondo_pct"],
        ascending=[False, False],
    ).reset_index(drop=True)


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


def pedir_lote(
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

                print(
                    f"  Límite temporal alcanzado; "
                    f"esperando {segundos:.1f} segundos..."
                )
                time.sleep(segundos)
                continue

            if respuesta.status_code in {500, 502, 503, 504}:
                segundos = min(2**intento, 30)
                print(
                    f"  Error temporal {respuesta.status_code}; "
                    f"reintento en {segundos} segundos..."
                )
                time.sleep(segundos)
                continue

            respuesta.raise_for_status()
            datos = respuesta.json()

            if not isinstance(datos, list):
                raise RuntimeError(
                    "La respuesta de OpenFIGI no es una lista."
                )

            if len(datos) != len(lote):
                raise RuntimeError(
                    "El número de respuestas no coincide con "
                    "el número de identificadores enviados."
                )

            return datos

        except (
            requests.RequestException,
            ValueError,
            RuntimeError,
        ) as error:
            ultimo_error = error
            segundos = min(2**intento, 30)

            if intento < MAX_REINTENTOS:
                print(
                    f"  Reintento {intento}/{MAX_REINTENTOS}: "
                    f"{error}"
                )
                time.sleep(segundos)

    raise RuntimeError(
        f"No se pudo consultar OpenFIGI: {ultimo_error}"
    )


def puntuar_resultado(
    resultado: dict[str, Any],
    isin: str,
) -> float:
    puntaje = 0.0

    ticker = limpiar_texto(resultado.get("ticker"))
    nombre = limpiar_texto(resultado.get("name"))
    exchange = limpiar_texto(resultado.get("exchCode"))
    security_type = limpiar_texto(
        resultado.get("securityType")
    ).lower()
    security_type2 = limpiar_texto(
        resultado.get("securityType2")
    ).lower()
    market_sector = limpiar_texto(
        resultado.get("marketSector")
    ).lower()

    if resultado.get("compositeFIGI"):
        puntaje += 5.0
    if resultado.get("shareClassFIGI"):
        puntaje += 4.0
    if ticker:
        puntaje += 3.0
    if nombre:
        puntaje += 2.0
    if exchange:
        puntaje += 1.0

    texto_tipo = f"{security_type} {security_type2}"

    if any(
        palabra in texto_tipo
        for palabra in [
            "fund",
            "etf",
            "exchange traded",
            "mutual",
            "unit",
        ]
    ):
        puntaje += 6.0

    if market_sector == "equity":
        puntaje += 2.0

    if isin.startswith("US") and exchange.upper() == "US":
        puntaje += 2.0

    return puntaje


def convertir_resultados(
    isin: str,
    respuesta: dict[str, Any],
) -> list[dict[str, Any]]:
    datos = respuesta.get("data", [])

    if not isinstance(datos, list):
        datos = []

    filas = []

    for indice, resultado in enumerate(datos, start=1):
        filas.append(
            {
                "isin": isin,
                "numero_resultado": indice,
                "puntaje_seleccion": puntuar_resultado(
                    resultado,
                    isin,
                ),
                "figi": resultado.get("figi"),
                "compositeFIGI": resultado.get(
                    "compositeFIGI"
                ),
                "shareClassFIGI": resultado.get(
                    "shareClassFIGI"
                ),
                "ticker": resultado.get("ticker"),
                "name": resultado.get("name"),
                "exchCode": resultado.get("exchCode"),
                "marketSector": resultado.get(
                    "marketSector"
                ),
                "securityType": resultado.get(
                    "securityType"
                ),
                "securityType2": resultado.get(
                    "securityType2"
                ),
                "securityDescription": resultado.get(
                    "securityDescription"
                ),
                "metadata": resultado.get("metadata"),
            }
        )

    return filas


def consultar_openfigi(
    universo: pd.DataFrame,
    cache_ruta: Path,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    api_key = limpiar_texto(
        os.environ.get("OPENFIGI_API_KEY", "")
    )

    max_lote = 100 if api_key else 5
    pausa = 0.35 if api_key else 2.6

    cache = cargar_cache(cache_ruta)

    elegibles = universo[
        universo["clasificacion_identificador"].eq(
            "isin_estandar_valido"
        )
    ]["isin_normalizado"].tolist()

    pendientes = [
        isin
        for isin in elegibles
        if isin not in cache
    ]

    print(
        f"ISIN estándar válidos: {len(elegibles):,}"
    )
    print(
        f"Ya presentes en caché: "
        f"{len(elegibles) - len(pendientes):,}"
    )
    print(
        f"Pendientes de consultar: {len(pendientes):,}"
    )
    print(
        "Modo OpenFIGI:",
        "con API key" if api_key else "sin API key",
    )

    if pendientes:
        sesion = crear_sesion(api_key)

        for inicio in range(0, len(pendientes), max_lote):
            lote = pendientes[inicio : inicio + max_lote]
            numero = inicio // max_lote + 1
            total = int(np.ceil(len(pendientes) / max_lote))

            print(
                f"  Lote {numero:03d}/{total:03d}: "
                f"{len(lote)} ISIN"
            )

            respuestas = pedir_lote(sesion, lote)

            for isin, respuesta in zip(lote, respuestas):
                cache[isin] = respuesta

            guardar_cache(cache_ruta, cache)

            if inicio + max_lote < len(pendientes):
                time.sleep(pausa)

    filas_todos = []
    filas_control = []

    for _, fila in universo.iterrows():
        isin = fila["isin_normalizado"]

        if fila["clasificacion_identificador"] != (
            "isin_estandar_valido"
        ):
            filas_control.append(
                {
                    "isin": isin,
                    "estado_openfigi": (
                        "no_consultado_identificador_no_estandar"
                    ),
                    "mensaje": fila[
                        "clasificacion_identificador"
                    ],
                    "numero_resultados": 0,
                }
            )
            continue

        respuesta = cache.get(isin, {})
        resultados = convertir_resultados(
            isin,
            respuesta,
        )
        filas_todos.extend(resultados)

        warning = limpiar_texto(
            respuesta.get("warning")
        )
        error = limpiar_texto(
            respuesta.get("error")
        )

        if resultados:
            estado = "resuelto"
            mensaje = ""
        elif warning:
            estado = "sin_coincidencia"
            mensaje = warning
        elif error:
            estado = "error_openfigi"
            mensaje = error
        else:
            estado = "respuesta_sin_datos"
            mensaje = ""

        filas_control.append(
            {
                "isin": isin,
                "estado_openfigi": estado,
                "mensaje": mensaje,
                "numero_resultados": len(resultados),
            }
        )

    return (
        pd.DataFrame(filas_todos),
        pd.DataFrame(filas_control),
    )


def seleccionar_mejor_resultado(
    todos: pd.DataFrame,
) -> pd.DataFrame:
    if todos.empty:
        return pd.DataFrame(
            columns=[
                "isin",
                "figi",
                "ticker",
                "name",
            ]
        )

    ordenado = todos.sort_values(
        [
            "isin",
            "puntaje_seleccion",
            "numero_resultado",
        ],
        ascending=[True, False, True],
    )

    seleccionado = (
        ordenado.groupby(
            "isin",
            as_index=False,
        )
        .head(1)
        .copy()
    )

    seleccionado["seleccion_ambigua"] = (
        seleccionado["isin"].map(
            todos.groupby("isin").size()
        )
        > 1
    )

    return seleccionado


def crear_resumen_control(
    maestro: pd.DataFrame,
) -> pd.DataFrame:
    return (
        maestro.groupby(
            [
                "clasificacion_identificador",
                "estado_openfigi",
            ],
            dropna=False,
            as_index=False,
        )
        .agg(
            identificadores=("isin_normalizado", "nunique"),
            peso_max_total_fondo_pct=(
                "peso_max_total_fondo_pct",
                "max",
            ),
            meses_presentes_mediana=(
                "meses_presentes",
                "median",
            ),
        )
        .sort_values(
            [
                "clasificacion_identificador",
                "estado_openfigi",
            ]
        )
    )


def main() -> None:
    raiz = Path(__file__).resolve().parents[1]
    processed = raiz / "data" / "processed"
    processed.mkdir(parents=True, exist_ok=True)

    base = preparar_base(
        leer_csv(
            processed
            / "ca0001_fondo3_hoja10_base_canonica_reconciliada.csv",
            ["fecha_cartera"],
        )
    )

    universo = construir_universo(base)

    cache_ruta = (
        processed
        / "ca0001_openfigi_cache_isin.json"
    )

    todos, control = consultar_openfigi(
        universo,
        cache_ruta,
    )
    seleccionado = seleccionar_mejor_resultado(todos)

    maestro = (
        universo.merge(
            control,
            left_on="isin_normalizado",
            right_on="isin",
            how="left",
            validate="one_to_one",
        )
        .drop(columns=["isin"], errors="ignore")
        .merge(
            seleccionado,
            left_on="isin_normalizado",
            right_on="isin",
            how="left",
            validate="one_to_one",
            suffixes=("", "_openfigi"),
        )
        .drop(columns=["isin"], errors="ignore")
    )

    maestro["mapeo_utilizable"] = (
        maestro["estado_openfigi"].eq("resuelto")
        & maestro["ticker"].fillna("").astype(str).ne("")
    )

    no_resueltos = maestro[
        ~maestro["estado_openfigi"].eq("resuelto")
    ].copy()

    ambiguos = maestro[
        maestro["seleccion_ambigua"].fillna(False)
    ].copy()

    resumen = crear_resumen_control(maestro)

    rutas = {
        "universo": (
            processed
            / "ca0001_isin_universo_priorizado.csv"
        ),
        "todos": (
            processed
            / "ca0001_isin_openfigi_todos_resultados.csv"
        ),
        "maestro": (
            processed
            / "ca0001_isin_openfigi_mapeo_seleccionado.csv"
        ),
        "no_resueltos": (
            processed
            / "ca0001_isin_openfigi_no_resueltos.csv"
        ),
        "ambiguos": (
            processed
            / "ca0001_isin_openfigi_ambiguos.csv"
        ),
        "resumen": (
            processed
            / "ca0001_isin_openfigi_control.csv"
        ),
    }

    universo.to_csv(
        rutas["universo"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    todos.to_csv(
        rutas["todos"],
        index=False,
        encoding="utf-8-sig",
    )
    maestro.to_csv(
        rutas["maestro"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    no_resueltos.to_csv(
        rutas["no_resueltos"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    ambiguos.to_csv(
        rutas["ambiguos"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    resumen.to_csv(
        rutas["resumen"],
        index=False,
        encoding="utf-8-sig",
    )

    print("\nENRIQUECIMIENTO INICIAL DE ISIN CON OPENFIGI TERMINADO")
    print("=" * 118)
    print(f"ISIN/identificadores únicos: {len(universo):,}")
    print(
        "ISIN estándar con checksum válido:",
        int(
            universo["clasificacion_identificador"]
            .eq("isin_estandar_valido")
            .sum()
        ),
    )
    print(
        "Mapeados por OpenFIGI:",
        int(maestro["estado_openfigi"].eq("resuelto").sum()),
    )
    print(
        "Sin coincidencia:",
        int(
            maestro["estado_openfigi"]
            .eq("sin_coincidencia")
            .sum()
        ),
    )
    print(
        "Identificadores no estándar/no consultados:",
        int(
            maestro["estado_openfigi"]
            .eq("no_consultado_identificador_no_estandar")
            .sum()
        ),
    )
    print(
        "Mapeos con más de un resultado:",
        int(maestro["seleccion_ambigua"].fillna(False).sum()),
    )

    print("\nRESUMEN DE CONTROL")
    print("-" * 118)
    print(resumen.to_string(index=False))

    print("\nTOP DE MAPEO OPENFIGI POR PESO")
    print("-" * 118)
    columnas_top = [
        "isin_normalizado",
        "ticker",
        "name",
        "exchCode",
        "marketSector",
        "securityType",
        "securityType2",
        "peso_max_total_fondo_pct",
        "meses_presentes",
        "seleccion_ambigua",
    ]
    print(
        maestro[
            maestro["estado_openfigi"].eq("resuelto")
        ]
        .sort_values(
            "peso_max_total_fondo_pct",
            ascending=False,
        )[columnas_top]
        .head(40)
        .to_string(index=False)
    )

    print("\nPRINCIPALES NO RESUELTOS")
    print("-" * 118)
    columnas_pendientes = [
        "isin_normalizado",
        "clasificacion_identificador",
        "estado_openfigi",
        "mensaje",
        "gestora_reportada",
        "moneda_reportada",
        "peso_max_total_fondo_pct",
        "meses_presentes",
        "lista_afp",
    ]
    print(
        no_resueltos.sort_values(
            "peso_max_total_fondo_pct",
            ascending=False,
        )[columnas_pendientes]
        .head(40)
        .to_string(index=False)
    )

    print("\nArchivos creados:")
    for ruta in rutas.values():
        print(f" - {ruta.resolve()}")

    print(
        "\nCriterio metodológico:\n"
        "- El prefijo del ISIN identifica la jurisdicción de emisión del "
        "código, no necesariamente el país económico de exposición.\n"
        "- OpenFIGI se utiliza para obtener FIGI, ticker, nombre, mercado y "
        "tipo de instrumento; país, sector económico e índice subyacente "
        "requieren una segunda etapa.\n"
        "- Los resultados ambiguos se conservan en un archivo separado y "
        "no deben aceptarse automáticamente sin contrastar nombre, ticker y "
        "tipo de instrumento.\n"
        "- Los identificadores privados o no estándar se mantienen con su "
        "gestora reportada y no se fuerzan contra OpenFIGI.\n"
        "- El caché evita repetir consultas ya realizadas."
    )


if __name__ == "__main__":
    main()
