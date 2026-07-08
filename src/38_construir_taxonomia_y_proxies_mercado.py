from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd


ESCENARIOS = {
    "principal_5pct": "usar_modelo_principal",
    "ampliado_15pct": "usar_analisis_ampliado",
}

FACTORES_VALIDOS = {
    "ACWI",
    "SPY",
    "QQQ",
    "EEM",
    "ILF",
    "EPU",
    "VGK",
    "EWJ",
    "MCHI",
    "XLK",
    "XLF",
    "XLE",
    "XLB",
    "XLI",
    "XLV",
    "XLY",
    "XLP",
    "GLD",
    "CPER",
    "COPX",
    "TLT",
    "LQD",
    "HYG",
    "PRIVATE_ALTERNATIVES",
    "RESIDUAL_NO_MAPEADO",
}

TOLERANCIA_PESOS = 1e-8


def leer_csv(
    ruta: Path,
    fechas: list[str] | None = None,
) -> pd.DataFrame:
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


def normalizar_texto(valor: object) -> str:
    texto = limpiar_texto(valor).upper()
    texto = re.sub(r"[^A-Z0-9]+", " ", texto)
    return re.sub(r"\s+", " ", texto).strip()


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


def moda_no_vacia(serie: pd.Series) -> str:
    valores = [
        limpiar_texto(x)
        for x in serie
        if limpiar_texto(x)
    ]

    if not valores:
        return ""

    return str(pd.Series(valores).value_counts().index[0])


def contiene(texto: str, patrones: list[str]) -> bool:
    return any(
        re.search(patron, texto, flags=re.IGNORECASE)
        for patron in patrones
    )


def ticker_base(ticker: str) -> str:
    """
    Extrae una versión estable del ticker de plaza.

    Ejemplos:
    SPY SS -> SPY
    GDXUSD -> GDX
    EWYGBX -> EWY
    SPXSEUR -> SPXS
    """
    limpio = re.sub(
        r"[^A-Z0-9]",
        "",
        limpiar_texto(ticker).upper(),
    )

    sufijos = [
        "USD",
        "EUR",
        "GBP",
        "GBX",
        "HUF",
        "JPY",
        "CHF",
        "CAD",
        "AUD",
    ]

    for sufijo in sufijos:
        if limpio.endswith(sufijo) and len(limpio) > len(sufijo) + 1:
            limpio = limpio[: -len(sufijo)]
            break

    return limpio


def preparar_base(df: pd.DataFrame) -> pd.DataFrame:
    salida = df.copy()

    salida["fecha_cartera"] = pd.to_datetime(
        salida["fecha_cartera"],
        errors="coerce",
    )
    salida["periodo"] = (
        salida["fecha_cartera"]
        .dt.to_period("M")
        .astype(str)
    )

    for columna in [
        "afp",
        "identificador_agregacion",
        "identificador_canonico",
        "ticker",
        "name",
        "securityType",
        "securityType2",
        "marketSector",
        "exchCode",
        "estado_identidad_final",
        "estado_cobertura",
        "tipo_identificador",
        "entidad_administradora",
        "moneda",
    ]:
        if columna not in salida.columns:
            salida[columna] = ""
        salida[columna] = salida[columna].map(limpiar_texto)

    for columna in [
        "peso_exterior_reconciliado",
        "peso_total_fondo_reconciliado",
        "peso_exterior_reconciliado_pct",
        "peso_total_fondo_reconciliado_pct",
        "valor_reconciliado_miles_soles",
        "error_cobertura_pct",
        "factor_reescala",
    ]:
        if columna not in salida.columns:
            salida[columna] = np.nan

        salida[columna] = pd.to_numeric(
            salida[columna],
            errors="coerce",
        )

    for columna in [
        "usar_modelo_principal",
        "usar_analisis_ampliado",
    ]:
        if columna not in salida.columns:
            salida[columna] = False
        salida[columna] = convertir_booleano(
            salida[columna]
        )

    salida["ticker_base"] = salida["ticker"].map(
        ticker_base
    )
    salida["texto_clasificacion"] = (
        salida[
            [
                "ticker",
                "name",
                "securityType",
                "securityType2",
                "marketSector",
                "entidad_administradora",
            ]
        ]
        .fillna("")
        .astype(str)
        .agg(" | ".join, axis=1)
        .map(normalizar_texto)
    )

    return salida


def construir_universo(base: pd.DataFrame) -> pd.DataFrame:
    return (
        base.groupby(
            "identificador_agregacion",
            dropna=False,
            as_index=False,
        )
        .agg(
            identificador_canonico=(
                "identificador_canonico",
                moda_no_vacia,
            ),
            ticker=("ticker", moda_no_vacia),
            ticker_base=("ticker_base", moda_no_vacia),
            name=("name", moda_no_vacia),
            securityType=("securityType", moda_no_vacia),
            securityType2=("securityType2", moda_no_vacia),
            marketSector=("marketSector", moda_no_vacia),
            exchCode=("exchCode", moda_no_vacia),
            estado_identidad_final=(
                "estado_identidad_final",
                moda_no_vacia,
            ),
            tipo_identificador=(
                "tipo_identificador",
                moda_no_vacia,
            ),
            entidad_administradora=(
                "entidad_administradora",
                moda_no_vacia,
            ),
            moneda=("moneda", moda_no_vacia),
            primera_fecha=("fecha_cartera", "min"),
            ultima_fecha=("fecha_cartera", "max"),
            meses_presentes=("periodo", "nunique"),
            afp_presentes=("afp", "nunique"),
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
        )
    )


def clasificar_vehiculo(
    texto: str,
    estado: str,
    tipo_identificador: str,
) -> tuple[str, str]:
    estado_norm = normalizar_texto(estado)
    tipo_norm = normalizar_texto(tipo_identificador)

    if (
        "FONDO PRIVADO" in estado_norm
        or "PRIVATE" in estado_norm
        or "FONDO SIN ISIN" in tipo_norm
        or "CHECKSUM INVALIDO PENDIENTE" in estado_norm
    ):
        return "fondo_privado", "alta"

    if contiene(
        texto,
        [
            r"\bETF\b",
            r"\bETP\b",
            r"EXCHANGE TRADED",
            r"ISHARES",
            r"VANGUARD .* ETF",
            r"SPDR",
            r"SELECT SECTOR",
        ],
    ):
        return "etf_etp", "alta"

    if contiene(
        texto,
        [
            r"OPEN END FUND",
            r"MUTUAL FUND",
            r"\bSICAV\b",
            r"\bUCITS\b",
            r"\bFUND\b",
        ],
    ):
        return "fondo_mutuo_o_abierto", "media"

    if contiene(
        texto,
        [
            r"CLOSED END FUND",
            r"CLOSED-END",
        ],
    ):
        return "fondo_cerrado", "alta"

    if contiene(
        texto,
        [
            r"COMMON STOCK",
            r"ORDINARY SHARE",
            r"\bEQUITY\b",
        ],
    ):
        return "accion_directa", "media"

    return "otro_o_no_determinado", "baja"


def clasificar_tipo_activo(
    texto: str,
    vehiculo: str,
    estado: str,
) -> tuple[str, str]:
    estado_norm = normalizar_texto(estado)

    if (
        vehiculo == "fondo_privado"
        or "PRIVATE" in estado_norm
    ):
        return "mercados_privados_y_alternativos", "alta"

    if contiene(
        texto,
        [
            r"\bBOND\b",
            r"\bDEBT\b",
            r"\bCREDIT\b",
            r"HIGH YIELD",
            r"FIXED INCOME",
            r"TREASUR",
            r"SOVEREIGN",
            r"DEUDA",
            r"OBLIGACION",
        ],
    ):
        return "renta_fija", "alta"

    if contiene(
        texto,
        [
            r"\bGOLD\b",
            r"\bSILVER\b",
            r"\bCOPPER\b",
            r"COMMODIT",
            r"PRECIOUS METAL",
        ],
    ):
        if contiene(
            texto,
            [
                r"MINER",
                r"MINING",
                r"EQUITY",
                r"ETF",
                r"FUND",
            ],
        ):
            return "renta_variable", "media"
        return "materias_primas", "media"

    if contiene(
        texto,
        [
            r"\bEQUITY\b",
            r"\bSTOCK\b",
            r"\bSHARE\b",
            r"\bETF\b",
            r"\bETP\b",
            r"MSCI",
            r"S P 500",
            r"NASDAQ",
            r"FTSE",
            r"RUSSELL",
        ],
    ):
        return "renta_variable", "alta"

    if vehiculo in {
        "etf_etp",
        "fondo_mutuo_o_abierto",
        "fondo_cerrado",
        "accion_directa",
    }:
        return "renta_variable", "baja"

    return "no_determinado", "baja"


def clasificar_region(
    texto: str,
    ticker: str,
) -> tuple[str, str]:
    t = ticker_base(ticker)

    reglas_exactas = {
        "EPU": ("Perú", "alta"),
        "ILF": ("América Latina", "alta"),
        "MCHI": ("China", "alta"),
        "KWEB": ("China", "alta"),
        "EWJ": ("Japón", "alta"),
        "DXJ": ("Japón", "alta"),
        "BBJP": ("Japón", "alta"),
        "EWY": ("Corea del Sur", "alta"),
        "EWG": ("Alemania", "alta"),
        "EZU": ("Eurozona", "alta"),
        "VGK": ("Europa", "alta"),
        "EEM": ("Mercados emergentes", "alta"),
        "IEMG": ("Mercados emergentes", "alta"),
        "EMIM": ("Mercados emergentes", "alta"),
        "AAXJ": ("Asia excepto Japón", "alta"),
        "ACWI": ("Global", "alta"),
        "VT": ("Global", "alta"),
        "SPY": ("Estados Unidos", "alta"),
        "IVV": ("Estados Unidos", "alta"),
        "VOO": ("Estados Unidos", "alta"),
        "VTI": ("Estados Unidos", "alta"),
        "QQQ": ("Estados Unidos", "alta"),
        "QQQM": ("Estados Unidos", "alta"),
        "SOXX": ("Estados Unidos", "alta"),
        "SMH": ("Estados Unidos", "alta"),
        "XLK": ("Estados Unidos", "alta"),
        "XLE": ("Estados Unidos", "alta"),
        "XLY": ("Estados Unidos", "alta"),
        "XOP": ("Estados Unidos", "alta"),
        "OIH": ("Estados Unidos", "alta"),
        "KBWB": ("Estados Unidos", "alta"),
        "FDN": ("Estados Unidos", "alta"),
        "VLUE": ("Estados Unidos", "alta"),
        "IWD": ("Estados Unidos", "alta"),
        "JQUA": ("Estados Unidos", "alta"),
        "VPU": ("Estados Unidos", "alta"),
    }

    if t in reglas_exactas:
        return reglas_exactas[t]

    reglas_texto = [
        (
            [
                r"\bPERU\b",
                r"PERUVIAN",
            ],
            "Perú",
        ),
        (
            [
                r"LATIN AMERICA",
                r"\bLATAM\b",
                r"LATINOAMERI",
            ],
            "América Latina",
        ),
        (
            [
                r"SOUTH KOREA",
                r"\bKOREA\b",
            ],
            "Corea del Sur",
        ),
        (
            [
                r"\bCHINA\b",
                r"CHINESE",
            ],
            "China",
        ),
        (
            [
                r"\bJAPAN\b",
                r"JAPANESE",
            ],
            "Japón",
        ),
        (
            [
                r"\bGERMANY\b",
                r"GERMAN",
            ],
            "Alemania",
        ),
        (
            [
                r"EUROZONE",
                r"\bEMU\b",
            ],
            "Eurozona",
        ),
        (
            [
                r"\bEUROPE\b",
                r"EUROPEAN",
            ],
            "Europa",
        ),
        (
            [
                r"ASIA EX JAPAN",
                r"ALL COUNTRY ASIA",
            ],
            "Asia excepto Japón",
        ),
        (
            [
                r"EMERGING MARKET",
                r"\bEMERGING\b",
            ],
            "Mercados emergentes",
        ),
        (
            [
                r"\bACWI\b",
                r"TOTAL WORLD",
                r"ALL WORLD",
                r"\bGLOBAL\b",
                r"\bWORLD\b",
            ],
            "Global",
        ),
        (
            [
                r"S P 500",
                r"NASDAQ",
                r"RUSSELL",
                r"US EQUITY",
                r"USA",
                r"UNITED STATES",
                r"TOTAL STOCK MKT",
                r"SELECT SECTOR",
            ],
            "Estados Unidos",
        ),
    ]

    for patrones, region in reglas_texto:
        if contiene(texto, patrones):
            return region, "media"

    return "No determinado", "baja"


def clasificar_sector_tema(
    texto: str,
    ticker: str,
) -> tuple[str, str]:
    t = ticker_base(ticker)

    reglas_exactas = {
        "SOXX": ("Semiconductores", "alta"),
        "SMH": ("Semiconductores", "alta"),
        "XLK": ("Tecnología", "alta"),
        "FDN": ("Internet y servicios digitales", "alta"),
        "KWEB": ("Internet y servicios digitales", "alta"),
        "XLE": ("Energía", "alta"),
        "OIH": ("Servicios petroleros", "alta"),
        "XOP": ("Exploración y producción de petróleo y gas", "alta"),
        "KBWB": ("Bancos", "alta"),
        "VPU": ("Servicios públicos", "alta"),
        "XLY": ("Consumo discrecional", "alta"),
        "GDX": ("Minería de oro", "alta"),
        "VLUE": ("Factor valor", "alta"),
        "IWD": ("Factor valor", "alta"),
        "JQUA": ("Factor calidad", "alta"),
    }

    if t in reglas_exactas:
        return reglas_exactas[t]

    reglas = [
        (
            [r"SEMICONDUCTOR"],
            "Semiconductores",
        ),
        (
            [
                r"TECHNOLOGY",
                r"INFORMATION TECH",
            ],
            "Tecnología",
        ),
        (
            [
                r"INTERNET",
                r"DIGITAL",
            ],
            "Internet y servicios digitales",
        ),
        (
            [
                r"OIL SERVICE",
                r"PETROLEUM SERVICE",
            ],
            "Servicios petroleros",
        ),
        (
            [
                r"\bENERGY\b",
                r"OIL GAS",
            ],
            "Energía",
        ),
        (
            [
                r"\bBANK\b",
                r"FINANCIAL",
            ],
            "Finanzas",
        ),
        (
            [
                r"UTILIT",
            ],
            "Servicios públicos",
        ),
        (
            [
                r"CONSUMER DISCRETIONARY",
            ],
            "Consumo discrecional",
        ),
        (
            [
                r"CONSUMER STAPLE",
            ],
            "Consumo básico",
        ),
        (
            [
                r"HEALTH",
                r"BIOTECH",
            ],
            "Salud",
        ),
        (
            [
                r"INDUSTRIAL",
            ],
            "Industriales",
        ),
        (
            [
                r"GOLD MINER",
                r"GOLD MINING",
            ],
            "Minería de oro",
        ),
        (
            [
                r"COPPER",
            ],
            "Cobre",
        ),
        (
            [
                r"MINING",
                r"MINER",
                r"MATERIAL",
            ],
            "Materiales y minería",
        ),
        (
            [
                r"\bVALUE\b",
            ],
            "Factor valor",
        ),
        (
            [
                r"\bQUALITY\b",
            ],
            "Factor calidad",
        ),
        (
            [
                r"SMALL CAP",
            ],
            "Pequeña capitalización",
        ),
        (
            [
                r"S P 500",
                r"NASDAQ 100",
                r"TOTAL STOCK",
                r"TOTAL WORLD",
                r"\bACWI\b",
                r"MSCI EMERGING",
                r"MSCI JAPAN",
                r"MSCI GERMANY",
                r"FTSE EUROPE",
            ],
            "Mercado amplio",
        ),
    ]

    for patrones, sector in reglas:
        if contiene(texto, patrones):
            return sector, "media"

    return "Mercado amplio o no determinado", "baja"


def clasificar_indice(
    texto: str,
    ticker: str,
) -> tuple[str, str]:
    t = ticker_base(ticker)

    exactos = {
        "SPY": "S&P 500",
        "IVV": "S&P 500",
        "VOO": "S&P 500",
        "QQQ": "Nasdaq-100",
        "QQQM": "Nasdaq-100",
        "ACWI": "MSCI ACWI",
        "EEM": "MSCI Emerging Markets",
        "IEMG": "MSCI Emerging Markets IMI",
        "EMIM": "MSCI Emerging Markets IMI",
        "EWJ": "MSCI Japan",
        "EWG": "MSCI Germany",
        "EWY": "MSCI South Korea",
        "MCHI": "MSCI China",
        "AAXJ": "MSCI Asia ex Japan",
        "EZU": "MSCI Eurozone",
        "VGK": "FTSE Europe",
        "VTI": "CRSP US Total Market",
        "SOXX": "Índice de semiconductores",
        "SMH": "Índice de semiconductores",
        "XLK": "Technology Select Sector",
        "XLE": "Energy Select Sector",
        "XLY": "Consumer Discretionary Select Sector",
        "KBWB": "KBW Nasdaq Bank Index",
        "FDN": "Índice de internet",
        "GDX": "Índice de mineras de oro",
        "KWEB": "Índice de internet de China",
        "VLUE": "MSCI USA Enhanced Value",
        "IWD": "Russell 1000 Value",
        "JQUA": "Índice de factor calidad de EE. UU.",
        "DXJ": "Índice de acciones japonesas cubierto",
    }

    if t in exactos:
        return exactos[t], "alta"

    reglas = [
        ([r"S P 500"], "S&P 500"),
        ([r"NASDAQ 100"], "Nasdaq-100"),
        ([r"MSCI ACWI"], "MSCI ACWI"),
        (
            [r"MSCI EMERGING"],
            "MSCI Emerging Markets",
        ),
        ([r"MSCI JAPAN"], "MSCI Japan"),
        ([r"MSCI GERMANY"], "MSCI Germany"),
        ([r"MSCI CHINA"], "MSCI China"),
        ([r"FTSE EUROPE"], "FTSE Europe"),
        (
            [r"RUSSELL 1000 VALUE"],
            "Russell 1000 Value",
        ),
    ]

    for patrones, indice in reglas:
        if contiene(texto, patrones):
            return indice, "media"

    return "No determinado", "baja"


def seleccionar_factor_proxy(
    texto: str,
    ticker: str,
    tipo_activo: str,
    region: str,
    sector_tema: str,
    estado_identidad: str,
) -> tuple[str, str, str]:
    t = ticker_base(ticker)

    if estado_identidad in {
        "fondo_privado_sin_isin",
        "identificador_privado_o_no_estandar",
        "checksum_invalido_pendiente",
    }:
        return (
            "PRIVATE_ALTERNATIVES",
            "alta",
            "identificador privado o no estándar",
        )

    exactos = {
        "SPY": "SPY",
        "IVV": "SPY",
        "VOO": "SPY",
        "VTI": "SPY",
        "QQQ": "QQQ",
        "QQQM": "QQQ",
        "ACWI": "ACWI",
        "VT": "ACWI",
        "EEM": "EEM",
        "IEMG": "EEM",
        "EMIM": "EEM",
        "AAXJ": "EEM",
        "EWY": "EEM",
        "ILF": "ILF",
        "EPU": "EPU",
        "VGK": "VGK",
        "EZU": "VGK",
        "EWG": "VGK",
        "HEDJ": "VGK",
        "EWJ": "EWJ",
        "DXJ": "EWJ",
        "BBJP": "EWJ",
        "MCHI": "MCHI",
        "KWEB": "MCHI",
        "SOXX": "XLK",
        "SMH": "XLK",
        "XLK": "XLK",
        "FDN": "QQQ",
        "XLF": "XLF",
        "KBWB": "XLF",
        "XLE": "XLE",
        "OIH": "XLE",
        "XOP": "XLE",
        "XLB": "XLB",
        "XLI": "XLI",
        "XLV": "XLV",
        "XLY": "XLY",
        "XLP": "XLP",
        "GDX": "GLD",
        "CPER": "CPER",
        "COPX": "COPX",
        "TLT": "TLT",
        "LQD": "LQD",
        "HYG": "HYG",
        "VLUE": "SPY",
        "IWD": "SPY",
        "JQUA": "SPY",
        "VPU": "SPY",
    }

    if t in exactos:
        return (
            exactos[t],
            "alta",
            f"ticker exacto {t}",
        )

    if tipo_activo == "renta_fija":
        if contiene(
            texto,
            [
                r"HIGH YIELD",
                r"\bHY\b",
                r"EMERGING MARKET DEBT",
                r"LATAM HY",
            ],
        ):
            return "HYG", "media", "renta fija de mayor riesgo"

        if contiene(
            texto,
            [
                r"TREASUR",
                r"SOVEREIGN",
                r"GOVERNMENT",
            ],
        ):
            return "TLT", "media", "deuda soberana"

        return "LQD", "baja", "renta fija genérica"

    sector_map = {
        "Semiconductores": ("XLK", "media"),
        "Tecnología": ("XLK", "media"),
        "Internet y servicios digitales": ("QQQ", "media"),
        "Finanzas": ("XLF", "media"),
        "Bancos": ("XLF", "media"),
        "Energía": ("XLE", "media"),
        "Servicios petroleros": ("XLE", "media"),
        "Exploración y producción de petróleo y gas": (
            "XLE",
            "media",
        ),
        "Materiales y minería": ("XLB", "media"),
        "Cobre": ("COPX", "media"),
        "Minería de oro": ("GLD", "media"),
        "Industriales": ("XLI", "media"),
        "Salud": ("XLV", "media"),
        "Consumo discrecional": ("XLY", "media"),
        "Consumo básico": ("XLP", "media"),
        "Factor valor": ("SPY", "baja"),
        "Factor calidad": ("SPY", "baja"),
        "Servicios públicos": ("SPY", "baja"),
    }

    if sector_tema in sector_map:
        factor, confianza = sector_map[sector_tema]
        return factor, confianza, f"sector o tema {sector_tema}"

    region_map = {
        "Perú": "EPU",
        "América Latina": "ILF",
        "China": "MCHI",
        "Japón": "EWJ",
        "Europa": "VGK",
        "Eurozona": "VGK",
        "Alemania": "VGK",
        "Mercados emergentes": "EEM",
        "Asia excepto Japón": "EEM",
        "Corea del Sur": "EEM",
        "Estados Unidos": "SPY",
        "Global": "ACWI",
    }

    if region in region_map:
        return (
            region_map[region],
            "media",
            f"región {region}",
        )

    return (
        "RESIDUAL_NO_MAPEADO",
        "baja",
        "sin regla suficientemente específica",
    )


def clasificar_instrumento(
    fila: pd.Series,
) -> dict[str, object]:
    texto = normalizar_texto(
        " | ".join(
            [
                limpiar_texto(fila.get("ticker")),
                limpiar_texto(fila.get("name")),
                limpiar_texto(fila.get("securityType")),
                limpiar_texto(fila.get("securityType2")),
                limpiar_texto(fila.get("marketSector")),
                limpiar_texto(
                    fila.get("entidad_administradora")
                ),
            ]
        )
    )
    estado = limpiar_texto(
        fila.get("estado_identidad_final")
    )
    tipo_identificador = limpiar_texto(
        fila.get("tipo_identificador")
    )
    ticker = limpiar_texto(fila.get("ticker"))

    vehiculo, confianza_vehiculo = clasificar_vehiculo(
        texto,
        estado,
        tipo_identificador,
    )
    tipo_activo, confianza_activo = clasificar_tipo_activo(
        texto,
        vehiculo,
        estado,
    )
    region, confianza_region = clasificar_region(
        texto,
        ticker,
    )
    sector_tema, confianza_sector = (
        clasificar_sector_tema(
            texto,
            ticker,
        )
    )
    indice, confianza_indice = clasificar_indice(
        texto,
        ticker,
    )
    factor, confianza_factor, razon_factor = (
        seleccionar_factor_proxy(
            texto,
            ticker,
            tipo_activo,
            region,
            sector_tema,
            estado,
        )
    )

    if factor not in FACTORES_VALIDOS:
        factor = "RESIDUAL_NO_MAPEADO"
        confianza_factor = "baja"
        razon_factor = "factor fuera del catálogo permitido"

    return {
        "vehiculo": vehiculo,
        "confianza_vehiculo": confianza_vehiculo,
        "tipo_activo": tipo_activo,
        "confianza_tipo_activo": confianza_activo,
        "region_exposicion_preliminar": region,
        "confianza_region": confianza_region,
        "sector_tema_preliminar": sector_tema,
        "confianza_sector": confianza_sector,
        "indice_referencia_preliminar": indice,
        "confianza_indice": confianza_indice,
        "factor_proxy_mercado": factor,
        "confianza_factor_proxy": confianza_factor,
        "razon_factor_proxy": razon_factor,
    }


def construir_taxonomia(
    universo: pd.DataFrame,
) -> pd.DataFrame:
    clasificaciones = universo.apply(
        clasificar_instrumento,
        axis=1,
        result_type="expand",
    )

    return pd.concat(
        [
            universo.reset_index(drop=True),
            clasificaciones.reset_index(drop=True),
        ],
        axis=1,
    )


def aplicar_taxonomia(
    base: pd.DataFrame,
    taxonomia: pd.DataFrame,
) -> pd.DataFrame:
    columnas = [
        "identificador_agregacion",
        "vehiculo",
        "confianza_vehiculo",
        "tipo_activo",
        "confianza_tipo_activo",
        "region_exposicion_preliminar",
        "confianza_region",
        "sector_tema_preliminar",
        "confianza_sector",
        "indice_referencia_preliminar",
        "confianza_indice",
        "factor_proxy_mercado",
        "confianza_factor_proxy",
        "razon_factor_proxy",
    ]

    return base.merge(
        taxonomia[columnas],
        on="identificador_agregacion",
        how="left",
        validate="many_to_one",
    )


def construir_escenarios(
    base: pd.DataFrame,
) -> pd.DataFrame:
    partes = []

    for escenario, columna in ESCENARIOS.items():
        bloque = base[base[columna]].copy()
        bloque["escenario"] = escenario
        partes.append(bloque)

    return pd.concat(
        partes,
        ignore_index=True,
        sort=False,
    )


def features_largas(
    escenarios: pd.DataFrame,
    categoria: str,
    nombre_salida: str,
) -> pd.DataFrame:
    salida = (
        escenarios.groupby(
            [
                "escenario",
                "periodo",
                "fecha_cartera",
                "afp",
                categoria,
            ],
            dropna=False,
            as_index=False,
        )
        .agg(
            peso_exterior=(
                "peso_exterior_reconciliado",
                "sum",
            ),
            peso_total_fondo=(
                "peso_total_fondo_reconciliado",
                "sum",
            ),
            identificadores=(
                "identificador_agregacion",
                "nunique",
            ),
        )
    )

    salida = salida.rename(
        columns={categoria: nombre_salida}
    )
    salida["peso_exterior_pct"] = (
        salida["peso_exterior"] * 100.0
    )
    salida["peso_total_fondo_pct"] = (
        salida["peso_total_fondo"] * 100.0
    )

    return salida


def features_proxy_ancho(
    proxy_largo: pd.DataFrame,
) -> pd.DataFrame:
    ancho = (
        proxy_largo.pivot_table(
            index=[
                "escenario",
                "periodo",
                "fecha_cartera",
                "afp",
            ],
            columns="factor_proxy_mercado",
            values="peso_total_fondo",
            aggfunc="sum",
            fill_value=0.0,
        )
        .reset_index()
    )
    ancho.columns.name = None

    for factor in sorted(FACTORES_VALIDOS):
        if factor not in ancho.columns:
            ancho[factor] = 0.0

    columnas_factor = sorted(FACTORES_VALIDOS)

    ancho = ancho[
        [
            "escenario",
            "periodo",
            "fecha_cartera",
            "afp",
        ]
        + columnas_factor
    ]

    return ancho


def construir_control(
    escenarios: pd.DataFrame,
    proxy_largo: pd.DataFrame,
) -> pd.DataFrame:
    original = (
        escenarios.groupby(
            [
                "escenario",
                "periodo",
                "afp",
            ],
            as_index=False,
        )
        .agg(
            peso_exterior_original=(
                "peso_exterior_reconciliado",
                "sum",
            ),
            peso_fondo_original=(
                "peso_total_fondo_reconciliado",
                "sum",
            ),
        )
    )

    clasificado = (
        proxy_largo.groupby(
            [
                "escenario",
                "periodo",
                "afp",
            ],
            as_index=False,
        )
        .agg(
            peso_exterior_clasificado=(
                "peso_exterior",
                "sum",
            ),
            peso_fondo_clasificado=(
                "peso_total_fondo",
                "sum",
            ),
        )
    )

    control = original.merge(
        clasificado,
        on=["escenario", "periodo", "afp"],
        how="outer",
        validate="one_to_one",
    )

    control["diferencia_exterior"] = (
        control["peso_exterior_clasificado"]
        - control["peso_exterior_original"]
    )
    control["diferencia_fondo"] = (
        control["peso_fondo_clasificado"]
        - control["peso_fondo_original"]
    )

    control["estado_control"] = np.where(
        (
            control["diferencia_exterior"].abs()
            <= TOLERANCIA_PESOS
        )
        & (
            control["diferencia_fondo"].abs()
            <= TOLERANCIA_PESOS
        ),
        "correcto",
        "revisar",
    )

    return control


def construir_cobertura(
    escenarios: pd.DataFrame,
) -> pd.DataFrame:
    salida = escenarios.copy()

    salida["grupo_cobertura"] = np.select(
        [
            salida["factor_proxy_mercado"].eq(
                "RESIDUAL_NO_MAPEADO"
            ),
            salida["factor_proxy_mercado"].eq(
                "PRIVATE_ALTERNATIVES"
            ),
            salida["confianza_factor_proxy"].eq("alta"),
            salida["confianza_factor_proxy"].eq("media"),
        ],
        [
            "residual_no_mapeado",
            "privados_alternativos",
            "mapeo_alta_confianza",
            "mapeo_confianza_media",
        ],
        default="mapeo_baja_confianza",
    )

    mensual = (
        salida.groupby(
            [
                "escenario",
                "periodo",
                "afp",
                "grupo_cobertura",
            ],
            as_index=False,
        )
        .agg(
            peso_exterior=(
                "peso_exterior_reconciliado",
                "sum",
            ),
            peso_total_fondo=(
                "peso_total_fondo_reconciliado",
                "sum",
            ),
        )
    )

    resumen = (
        mensual.groupby(
            [
                "escenario",
                "afp",
                "grupo_cobertura",
            ],
            as_index=False,
        )
        .agg(
            periodos=("periodo", "nunique"),
            peso_exterior_mediano=(
                "peso_exterior",
                "median",
            ),
            peso_exterior_p90=(
                "peso_exterior",
                lambda s: float(
                    pd.Series(s).dropna().quantile(0.90)
                ),
            ),
            peso_total_fondo_mediano=(
                "peso_total_fondo",
                "median",
            ),
        )
    )

    resumen["peso_exterior_mediano_pct"] = (
        resumen["peso_exterior_mediano"] * 100.0
    )
    resumen["peso_total_fondo_mediano_pct"] = (
        resumen["peso_total_fondo_mediano"] * 100.0
    )

    return mensual, resumen


def main() -> None:
    raiz = Path(__file__).resolve().parents[1]
    processed = raiz / "data" / "processed"

    base = preparar_base(
        leer_csv(
            processed
            / "ca0001_base_identificadores_canonica_final.csv",
            ["fecha_cartera"],
        )
    )

    universo = construir_universo(base)
    taxonomia = construir_taxonomia(universo)
    base_taxonomia = aplicar_taxonomia(
        base,
        taxonomia,
    )
    escenarios = construir_escenarios(
        base_taxonomia,
    )

    proxy_largo = features_largas(
        escenarios,
        "factor_proxy_mercado",
        "factor_proxy_mercado",
    )
    proxy_ancho = features_proxy_ancho(
        proxy_largo
    )
    region_largo = features_largas(
        escenarios,
        "region_exposicion_preliminar",
        "region_exposicion_preliminar",
    )
    sector_largo = features_largas(
        escenarios,
        "sector_tema_preliminar",
        "sector_tema_preliminar",
    )
    activo_largo = features_largas(
        escenarios,
        "tipo_activo",
        "tipo_activo",
    )

    control = construir_control(
        escenarios,
        proxy_largo,
    )
    cobertura_mensual, cobertura_resumen = (
        construir_cobertura(escenarios)
    )

    pendientes = taxonomia[
        taxonomia["factor_proxy_mercado"].eq(
            "RESIDUAL_NO_MAPEADO"
        )
        | taxonomia["confianza_factor_proxy"].eq("baja")
        | taxonomia[
            "region_exposicion_preliminar"
        ].eq("No determinado")
    ].sort_values(
        [
            "peso_max_total_fondo_pct",
            "meses_presentes",
        ],
        ascending=[False, False],
    )

    rutas = {
        "taxonomia": (
            processed
            / "ca0001_taxonomia_instrumentos_preliminar.csv"
        ),
        "base_taxonomia": (
            processed
            / "ca0001_base_identificadores_con_taxonomia.csv"
        ),
        "pendientes": (
            processed
            / "ca0001_taxonomia_pendientes_priorizados.csv"
        ),
        "proxy_largo": (
            processed
            / "ca0001_features_proxy_mercado_mensual_largo.csv"
        ),
        "proxy_ancho": (
            processed
            / "ca0001_features_proxy_mercado_mensual_ancho.csv"
        ),
        "region_largo": (
            processed
            / "ca0001_features_region_mensual.csv"
        ),
        "sector_largo": (
            processed
            / "ca0001_features_sector_tema_mensual.csv"
        ),
        "activo_largo": (
            processed
            / "ca0001_features_tipo_activo_mensual.csv"
        ),
        "control": (
            processed
            / "ca0001_taxonomia_control_pesos.csv"
        ),
        "cobertura_mensual": (
            processed
            / "ca0001_taxonomia_cobertura_mensual.csv"
        ),
        "cobertura_resumen": (
            processed
            / "ca0001_taxonomia_resumen_cobertura.csv"
        ),
    }

    taxonomia.to_csv(
        rutas["taxonomia"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    base_taxonomia.to_csv(
        rutas["base_taxonomia"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    pendientes.to_csv(
        rutas["pendientes"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    proxy_largo.to_csv(
        rutas["proxy_largo"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    proxy_ancho.to_csv(
        rutas["proxy_ancho"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    region_largo.to_csv(
        rutas["region_largo"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    sector_largo.to_csv(
        rutas["sector_largo"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    activo_largo.to_csv(
        rutas["activo_largo"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    control.to_csv(
        rutas["control"],
        index=False,
        encoding="utf-8-sig",
    )
    cobertura_mensual.to_csv(
        rutas["cobertura_mensual"],
        index=False,
        encoding="utf-8-sig",
    )
    cobertura_resumen.to_csv(
        rutas["cobertura_resumen"],
        index=False,
        encoding="utf-8-sig",
    )

    print("\nTAXONOMÍA PRELIMINAR Y PROXIES DE MERCADO TERMINADOS")
    print("=" * 120)

    print("\nRESUMEN DE FACTORES PROXY")
    print("-" * 120)
    print(
        taxonomia.groupby(
            [
                "factor_proxy_mercado",
                "confianza_factor_proxy",
            ],
            as_index=False,
        )
        .agg(
            identificadores=(
                "identificador_agregacion",
                "nunique",
            ),
            peso_maximo_pct=(
                "peso_max_total_fondo_pct",
                "max",
            ),
            meses_mediana=(
                "meses_presentes",
                "median",
            ),
        )
        .sort_values(
            [
                "factor_proxy_mercado",
                "confianza_factor_proxy",
            ]
        )
        .to_string(index=False)
    )

    print("\nCOBERTURA DE LA TAXONOMÍA POR AFP")
    print("-" * 120)
    print(
        cobertura_resumen.to_string(index=False)
    )

    print("\nCONTROL DE PESOS")
    print("-" * 120)
    print(
        control["estado_control"]
        .value_counts(dropna=False)
        .rename_axis("estado")
        .reset_index(name="observaciones")
        .to_string(index=False)
    )

    print("\nTOP DE INSTRUMENTOS CLASIFICADOS")
    print("-" * 120)
    print(
        taxonomia.sort_values(
            "peso_max_total_fondo_pct",
            ascending=False,
        )[
            [
                "identificador_agregacion",
                "ticker",
                "name",
                "vehiculo",
                "tipo_activo",
                "region_exposicion_preliminar",
                "sector_tema_preliminar",
                "indice_referencia_preliminar",
                "factor_proxy_mercado",
                "confianza_factor_proxy",
                "peso_max_total_fondo_pct",
                "meses_presentes",
            ]
        ]
        .head(50)
        .to_string(index=False)
    )

    print("\nPENDIENTES PRIORITARIOS")
    print("-" * 120)

    if pendientes.empty:
        print("No quedaron instrumentos pendientes.")
    else:
        print(
            pendientes[
                [
                    "identificador_agregacion",
                    "identificador_canonico",
                    "ticker",
                    "name",
                    "estado_identidad_final",
                    "vehiculo",
                    "tipo_activo",
                    "region_exposicion_preliminar",
                    "sector_tema_preliminar",
                    "factor_proxy_mercado",
                    "confianza_factor_proxy",
                    "peso_max_total_fondo_pct",
                    "meses_presentes",
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
        "- La taxonomía es preliminar y se apoya en ticker, nombre, tipo de "
        "instrumento y reglas explícitas; no representa todavía un análisis "
        "look-through de los activos subyacentes.\n"
        "- El factor proxy es una aproximación para modelar sensibilidad de "
        "mercado. No implica que el fondo replique exactamente ese índice.\n"
        "- Los fondos privados se mantienen como PRIVATE_ALTERNATIVES y los "
        "casos sin regla suficiente como RESIDUAL_NO_MAPEADO.\n"
        "- Las exposiciones por región y sector deben validarse con fuentes "
        "del emisor antes de presentarse como composición económica final.\n"
        "- Los controles garantizan que la clasificación no modifica los "
        "pesos reconciliados del Fondo 3."
    )


if __name__ == "__main__":
    main()
