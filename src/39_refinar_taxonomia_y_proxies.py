from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd


ESCENARIOS = {
    "principal_5pct": "usar_modelo_principal",
    "ampliado_15pct": "usar_analisis_ampliado",
}

FACTORES = [
    "ACWI", "SPY", "QQQ", "EEM", "ILF", "EPU", "VGK", "EWJ",
    "MCHI", "XLK", "XLF", "XLE", "XLB", "XLI", "XLV", "XLY",
    "XLP", "GLD", "CPER", "COPX", "TLT", "LQD", "HYG",
    "PRIVATE_ALTERNATIVES", "RESIDUAL_NO_MAPEADO",
]

TOLERANCIA = 1e-8


def leer_csv(ruta: Path, fechas: list[str] | None = None) -> pd.DataFrame:
    if not ruta.exists():
        raise FileNotFoundError(f"No existe: {ruta}")
    return pd.read_csv(ruta, parse_dates=fechas or [])


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


def ticker_base(ticker: object) -> str:
    bruto = limpiar_texto(ticker).upper()

    # OpenFIGI puede devolver tickers con código de plaza separado,
    # por ejemplo "SPY SS". En esos casos se conserva el primer token.
    tokens = bruto.split()
    if (
        len(tokens) >= 2
        and re.fullmatch(r"[A-Z0-9]{1,8}", tokens[0])
        and re.fullmatch(r"[A-Z]{1,4}", tokens[1])
    ):
        bruto = tokens[0]

    limpio = re.sub(r"[^A-Z0-9]", "", bruto)

    for sufijo in ["USD", "EUR", "GBP", "GBX", "HUF", "JPY", "CHF", "CAD", "AUD"]:
        if limpio.endswith(sufijo) and len(limpio) > len(sufijo) + 1:
            limpio = limpio[:-len(sufijo)]
            break

    return limpio


def preparar_taxonomia(df: pd.DataFrame) -> pd.DataFrame:
    salida = df.copy()

    columnas_texto = [
        "identificador_agregacion", "identificador_canonico", "ticker",
        "name", "securityType", "securityType2", "marketSector",
        "estado_identidad_final", "tipo_identificador", "entidad_administradora",
        "moneda", "vehiculo", "confianza_vehiculo", "tipo_activo",
        "confianza_tipo_activo", "region_exposicion_preliminar",
        "confianza_region", "sector_tema_preliminar", "confianza_sector",
        "indice_referencia_preliminar", "confianza_indice",
        "factor_proxy_mercado", "confianza_factor_proxy", "razon_factor_proxy",
    ]

    for columna in columnas_texto:
        if columna not in salida.columns:
            salida[columna] = ""
        salida[columna] = salida[columna].map(limpiar_texto)

    for columna in [
        "peso_max_total_fondo_pct", "peso_mediano_total_fondo_pct",
        "peso_max_exterior_pct", "meses_presentes",
    ]:
        if columna not in salida.columns:
            salida[columna] = np.nan
        salida[columna] = pd.to_numeric(salida[columna], errors="coerce")

    salida["ticker_base_refinado"] = salida["ticker"].map(ticker_base)
    salida["texto_economico"] = (
        salida[
            ["ticker", "name", "securityType", "securityType2", "marketSector"]
        ]
        .fillna("")
        .astype(str)
        .agg(" | ".join, axis=1)
        .map(normalizar_texto)
    )

    return salida


def preparar_base(df: pd.DataFrame) -> pd.DataFrame:
    salida = df.copy()

    salida["fecha_cartera"] = pd.to_datetime(
        salida["fecha_cartera"], errors="coerce"
    )
    salida["periodo"] = salida["fecha_cartera"].dt.to_period("M").astype(str)

    for columna in [
        "identificador_agregacion", "afp", "estado_cobertura",
    ]:
        if columna not in salida.columns:
            salida[columna] = ""
        salida[columna] = salida[columna].map(limpiar_texto)

    for columna in [
        "peso_exterior_reconciliado", "peso_total_fondo_reconciliado",
    ]:
        salida[columna] = pd.to_numeric(salida[columna], errors="coerce")

    for columna in ["usar_modelo_principal", "usar_analisis_ampliado"]:
        salida[columna] = convertir_booleano(salida[columna])

    return salida


# Reglas exactas. Tienen prioridad sobre cualquier regla textual.
REGLAS_TICKER = {
    "SPY": ("SPY", "Estados Unidos", "Mercado amplio", "S&P 500"),
    "IVV": ("SPY", "Estados Unidos", "Mercado amplio", "S&P 500"),
    "VOO": ("SPY", "Estados Unidos", "Mercado amplio", "S&P 500"),
    "VTI": ("SPY", "Estados Unidos", "Mercado amplio", "CRSP US Total Market"),
    "SPYM": ("SPY", "Estados Unidos", "Mercado amplio", "S&P 500"),
    "SPXS": ("SPY", "Estados Unidos", "Mercado amplio", "S&P 500"),
    "QQQ": ("QQQ", "Estados Unidos", "Tecnología y crecimiento", "Nasdaq-100"),
    "QQQM": ("QQQ", "Estados Unidos", "Tecnología y crecimiento", "Nasdaq-100"),
    "EQQS": ("QQQ", "Estados Unidos", "Tecnología y crecimiento", "Nasdaq-100"),
    "ACWI": ("ACWI", "Global", "Mercado amplio", "MSCI ACWI"),
    "VT": ("ACWI", "Global", "Mercado amplio", "FTSE Global All Cap"),
    "EEM": ("EEM", "Mercados emergentes", "Mercado amplio", "MSCI Emerging Markets"),
    "IEMG": ("EEM", "Mercados emergentes", "Mercado amplio", "MSCI Emerging Markets IMI"),
    "EMIM": ("EEM", "Mercados emergentes", "Mercado amplio", "MSCI Emerging Markets IMI"),
    "AAXJ": ("EEM", "Asia excepto Japón", "Mercado amplio", "MSCI Asia ex Japan"),
    "XSOE": ("EEM", "Mercados emergentes", "Mercado amplio", "Emerging Markets ex State Owned"),
    "EWY": ("EEM", "Corea del Sur", "Mercado amplio", "MSCI South Korea"),
    "ILF": ("ILF", "América Latina", "Mercado amplio", "Latin America 40"),
    "EPU": ("EPU", "Perú", "Mercado amplio", "MSCI Peru"),
    "VGK": ("VGK", "Europa", "Mercado amplio", "FTSE Europe"),
    "EZU": ("VGK", "Eurozona", "Mercado amplio", "MSCI Eurozone"),
    "EWG": ("VGK", "Alemania", "Mercado amplio", "MSCI Germany"),
    "HEDJ": ("VGK", "Europa", "Mercado amplio", "Europe Hedged Equity"),
    "HEZU": ("VGK", "Eurozona", "Mercado amplio", "MSCI Eurozone Hedged"),
    "EWJ": ("EWJ", "Japón", "Mercado amplio", "MSCI Japan"),
    "DXJ": ("EWJ", "Japón", "Mercado amplio", "Japan Hedged Equity"),
    "BBJP": ("EWJ", "Japón", "Mercado amplio", "Japan Equity"),
    "VDJP": ("EWJ", "Japón", "Mercado amplio", "FTSE Japan"),
    "MCHI": ("MCHI", "China", "Mercado amplio", "MSCI China"),
    "KWEB": ("MCHI", "China", "Internet y servicios digitales", "China Internet"),
    "FXI": ("MCHI", "China", "Mercado amplio", "China Large Cap"),
    "ASHR": ("MCHI", "China", "Mercado amplio", "CSI 300"),
    "SOXX": ("XLK", "Estados Unidos", "Semiconductores", "Semiconductor Index"),
    "SMH": ("XLK", "Estados Unidos", "Semiconductores", "Semiconductor Index"),
    "XLK": ("XLK", "Estados Unidos", "Tecnología", "Technology Select Sector"),
    "FDN": ("QQQ", "Estados Unidos", "Internet y servicios digitales", "Internet Index"),
    "WTAI": ("QQQ", "Global", "Inteligencia artificial", "AI and Innovation"),
    "XLF": ("XLF", "Estados Unidos", "Finanzas", "Financial Select Sector"),
    "KBWB": ("XLF", "Estados Unidos", "Bancos", "KBW Bank Index"),
    "KRE": ("XLF", "Estados Unidos", "Bancos regionales", "Regional Banks Index"),
    "SX7E": ("VGK", "Eurozona", "Bancos", "EURO STOXX Banks"),
    "SX7EE": ("VGK", "Eurozona", "Bancos", "EURO STOXX Banks"),
    "XLE": ("XLE", "Estados Unidos", "Energía", "Energy Select Sector"),
    "OIH": ("XLE", "Estados Unidos", "Servicios petroleros", "Oil Services Index"),
    "XOP": ("XLE", "Estados Unidos", "Exploración y producción", "Oil & Gas Exploration"),
    "XLB": ("XLB", "Estados Unidos", "Materiales", "Materials Select Sector"),
    "XME": ("XLB", "Estados Unidos", "Metales y minería", "S&P Metals & Mining"),
    "REMX": ("XLB", "Global", "Tierras raras y metales estratégicos", "Rare Earths"),
    "COPX": ("COPX", "Global", "Cobre", "Copper Miners"),
    "CPER": ("CPER", "Global", "Cobre", "Copper"),
    "GDX": ("GLD", "Global", "Minería de oro", "Gold Miners"),
    "XLI": ("XLI", "Estados Unidos", "Industriales", "Industrial Select Sector"),
    "AIRR": ("XLI", "Estados Unidos", "Industriales", "American Industrial Renaissance"),
    "XLV": ("XLV", "Estados Unidos", "Salud", "Health Care Select Sector"),
    "XLY": ("XLY", "Estados Unidos", "Consumo discrecional", "Consumer Discretionary Select Sector"),
    "XLP": ("XLP", "Estados Unidos", "Consumo básico", "Consumer Staples Select Sector"),
    "XLU": ("SPY", "Estados Unidos", "Servicios públicos", "Utilities Select Sector"),
    "VPU": ("SPY", "Estados Unidos", "Servicios públicos", "US Utilities"),
    "VLUE": ("SPY", "Estados Unidos", "Factor valor", "MSCI USA Enhanced Value"),
    "IWD": ("SPY", "Estados Unidos", "Factor valor", "Russell 1000 Value"),
    "QUAL": ("SPY", "Estados Unidos", "Factor calidad", "MSCI USA Quality"),
    "JQUA": ("SPY", "Estados Unidos", "Factor calidad", "US Quality Factor"),
    "SPSM": ("SPY", "Estados Unidos", "Pequeña capitalización", "S&P SmallCap 600"),
    "ICVT": ("LQD", "Estados Unidos", "Bonos convertibles", "Convertible Bonds"),
    "MDELAAE": ("HYG", "América Latina", "Deuda latinoamericana", "No determinado"),
}


REGLAS_NOMBRE = [
    # Liquidez y mercado monetario: no se fuerza a un índice de renta variable.
    (r"\bLIQUIDITY\b|\bLIQUID\b|\bMONEY MARKET\b|\bLVNAV\b|\bCASH\b",
     "RESIDUAL_NO_MAPEADO", "Global", "Liquidez y equivalentes", "No determinado", "liquidez", "media"),

    # Renta fija.
    (r"HIGH YIELD|\bLATAM HY\b|EMERGING MARKET DEBT|SENIOR LOAN",
     "HYG", "Mercados emergentes", "Renta fija de mayor riesgo", "No determinado", "renta_fija", "media"),
    (r"\bDEBT\b|\bDEUDA\b|\bBOND\b|\bCREDIT\b|FIXED INCOME",
     "LQD", "No determinado", "Renta fija", "No determinado", "renta_fija", "baja"),

    # Estados Unidos / mercado amplio.
    (r"S P 500|S&P 500|US EQUITY|US RES EQ|USA EQUITY|US CORE EQUITY|US SMALL CAP",
     "SPY", "Estados Unidos", "Mercado amplio", "S&P 500 o mercado amplio de EE. UU.", "renta_variable", "media"),
    (r"NASDAQ 100|NASDAQ-100",
     "QQQ", "Estados Unidos", "Tecnología y crecimiento", "Nasdaq-100", "renta_variable", "alta"),
    (r"WORLD TECH|GLOBAL TECHNOLOGY|ARTIFICIAL INTELLIGENCE|AI AND INNOVATION",
     "XLK", "Global", "Tecnología", "No determinado", "renta_variable", "media"),

    # Regiones.
    (r"\bJAPAN\b|\bJPN\b|JAPANESE",
     "EWJ", "Japón", "Mercado amplio", "No determinado", "renta_variable", "media"),
    (r"\bCHINA\b|CHIN EQ|CHINA A",
     "MCHI", "China", "Mercado amplio", "No determinado", "renta_variable", "media"),
    (r"EMERGING MARKET|EM MRK|EM ASIA|EMERG MKT|ASIAN OPPORT",
     "EEM", "Mercados emergentes", "Mercado amplio", "No determinado", "renta_variable", "media"),
    (r"\bEUROPE\b|\bEURO\b|CONT EUR|EUROPEAN",
     "VGK", "Europa", "Mercado amplio", "No determinado", "renta_variable", "media"),
    (r"LATIN AMERICA|LATINOAMERI|\bLATAM\b",
     "ILF", "América Latina", "Mercado amplio", "No determinado", "renta_variable", "media"),

    # Sectores/temas.
    (r"SEMICONDUCTOR",
     "XLK", "Estados Unidos", "Semiconductores", "No determinado", "renta_variable", "alta"),
    (r"METALS MINING|METALS & MINING|MATERIALS",
     "XLB", "No determinado", "Metales y minería", "No determinado", "renta_variable", "media"),
    (r"RARE EARTH",
     "XLB", "Global", "Tierras raras y metales estratégicos", "No determinado", "renta_variable", "media"),
    (r"\bBANKS?\b|FINANCIAL",
     "XLF", "No determinado", "Finanzas", "No determinado", "renta_variable", "media"),
    (r"\bQUALITY\b|QUALITY GROWTH",
     "SPY", "Estados Unidos", "Factor calidad", "No determinado", "renta_variable", "media"),
    (r"\bENERGY\b|OIL SERVICE|OIL GAS|PETROLEUM",
     "XLE", "No determinado", "Energía", "No determinado", "renta_variable", "media"),
    (r"CONSUMER STAPLES",
     "XLP", "Estados Unidos", "Consumo básico", "No determinado", "renta_variable", "alta"),
    (r"CONSUMER DISCRETIONARY",
     "XLY", "Estados Unidos", "Consumo discrecional", "No determinado", "renta_variable", "alta"),
    (r"HEALTH CARE|HEALTHCARE|BIOTECH",
     "XLV", "No determinado", "Salud", "No determinado", "renta_variable", "media"),
    (r"INDUSTRIAL",
     "XLI", "No determinado", "Industriales", "No determinado", "renta_variable", "media"),
]


def aplicar_regla_fila(fila: pd.Series) -> pd.Series:
    salida = fila.copy()

    factor_original = limpiar_texto(salida["factor_proxy_mercado"])
    region_original = limpiar_texto(salida["region_exposicion_preliminar"])
    sector_original = limpiar_texto(salida["sector_tema_preliminar"])
    indice_original = limpiar_texto(salida["indice_referencia_preliminar"])
    confianza_original = limpiar_texto(salida["confianza_factor_proxy"])

    estado = normalizar_texto(salida["estado_identidad_final"])
    ticker = limpiar_texto(salida["ticker_base_refinado"])
    texto = limpiar_texto(salida["texto_economico"])

    salida["factor_proxy_original"] = factor_original
    salida["region_original"] = region_original
    salida["sector_original"] = sector_original
    salida["indice_original"] = indice_original
    salida["confianza_factor_original"] = confianza_original
    salida["regla_refinamiento"] = "sin_cambio"

    # Fondos privados y códigos privados: nunca se asignan a un índice público.
    if (
        "FONDO PRIVADO" in estado
        or "PRIVATE" in estado
        or "IDENTIFICADOR PRIVADO" in estado
        or "CHECKSUM INVALIDO PENDIENTE" in estado
    ):
        salida["vehiculo"] = "fondo_privado"
        salida["tipo_activo"] = "mercados_privados_y_alternativos"
        salida["factor_proxy_mercado"] = "PRIVATE_ALTERNATIVES"
        salida["confianza_factor_proxy"] = "alta"
        salida["razon_factor_proxy"] = "identificador privado o vehículo alternativo"
        salida["regla_refinamiento"] = "privado_alternativo"
        return salida

    # ISIN no resuelto sin nombre/ticker: no inferir SPY por el prefijo del ISIN.
    if "ISIN NO RESUELTO" in estado and not ticker and not texto:
        salida["factor_proxy_mercado"] = "RESIDUAL_NO_MAPEADO"
        salida["confianza_factor_proxy"] = "baja"
        salida["region_exposicion_preliminar"] = "No determinado"
        salida["sector_tema_preliminar"] = "No determinado"
        salida["indice_referencia_preliminar"] = "No determinado"
        salida["razon_factor_proxy"] = "identidad económica no resuelta"
        salida["regla_refinamiento"] = "isin_no_resuelto"
        return salida

    if ticker in REGLAS_TICKER:
        factor, region, sector, indice = REGLAS_TICKER[ticker]
        salida["factor_proxy_mercado"] = factor
        salida["confianza_factor_proxy"] = "alta"
        salida["region_exposicion_preliminar"] = region
        salida["confianza_region"] = "alta"
        salida["sector_tema_preliminar"] = sector
        salida["confianza_sector"] = "alta"
        salida["indice_referencia_preliminar"] = indice
        salida["confianza_indice"] = "alta"
        salida["tipo_activo"] = (
            "renta_fija" if factor in {"TLT", "LQD", "HYG"}
            else "renta_variable"
        )
        salida["razon_factor_proxy"] = f"regla exacta de ticker {ticker}"
        salida["regla_refinamiento"] = f"ticker::{ticker}"
        return salida

    for (
        patron,
        factor,
        region,
        sector,
        indice,
        tipo_activo,
        confianza,
    ) in REGLAS_NOMBRE:
        if re.search(patron, texto, flags=re.IGNORECASE):
            salida["factor_proxy_mercado"] = factor
            salida["confianza_factor_proxy"] = confianza
            salida["region_exposicion_preliminar"] = region
            salida["confianza_region"] = confianza
            salida["sector_tema_preliminar"] = sector
            salida["confianza_sector"] = confianza
            salida["indice_referencia_preliminar"] = indice
            salida["confianza_indice"] = confianza
            salida["tipo_activo"] = tipo_activo
            salida["razon_factor_proxy"] = f"regla textual: {patron}"
            salida["regla_refinamiento"] = f"nombre::{patron}"
            return salida

    # Evitar clasificaciones sectoriales inducidas por el custodio/gestora.
    # La nueva taxonomía usa texto económico sin entidad_administradora.
    if (
        salida["sector_tema_preliminar"] in {"Finanzas", "Bancos"}
        and not re.search(r"\bBANKS?\b|FINANCIAL", texto)
    ):
        salida["sector_tema_preliminar"] = "Mercado amplio o no determinado"
        salida["confianza_sector"] = "baja"
        salida["regla_refinamiento"] = "elimina_sector_por_custodio"

    # No mantener un proxy regional en ISIN sin identidad económica.
    if "ISIN NO RESUELTO" in estado:
        salida["factor_proxy_mercado"] = "RESIDUAL_NO_MAPEADO"
        salida["confianza_factor_proxy"] = "baja"
        salida["region_exposicion_preliminar"] = "No determinado"
        salida["sector_tema_preliminar"] = "No determinado"
        salida["indice_referencia_preliminar"] = "No determinado"
        salida["razon_factor_proxy"] = "ISIN no resuelto"
        salida["regla_refinamiento"] = "isin_no_resuelto"

    return salida


def refinar_taxonomia(taxonomia: pd.DataFrame) -> pd.DataFrame:
    refinada = taxonomia.apply(aplicar_regla_fila, axis=1)

    refinada["cambio_factor"] = (
        refinada["factor_proxy_mercado"]
        != refinada["factor_proxy_original"]
    )
    refinada["cambio_region"] = (
        refinada["region_exposicion_preliminar"]
        != refinada["region_original"]
    )
    refinada["cambio_sector"] = (
        refinada["sector_tema_preliminar"]
        != refinada["sector_original"]
    )

    return refinada


def aplicar_taxonomia(
    base: pd.DataFrame,
    taxonomia: pd.DataFrame,
) -> pd.DataFrame:
    columnas = [
        "identificador_agregacion",
        "vehiculo",
        "tipo_activo",
        "region_exposicion_preliminar",
        "confianza_region",
        "sector_tema_preliminar",
        "confianza_sector",
        "indice_referencia_preliminar",
        "confianza_indice",
        "factor_proxy_mercado",
        "confianza_factor_proxy",
        "razon_factor_proxy",
        "regla_refinamiento",
    ]

    return base.merge(
        taxonomia[columnas],
        on="identificador_agregacion",
        how="left",
        validate="many_to_one",
    )


def construir_escenarios(base: pd.DataFrame) -> pd.DataFrame:
    partes = []

    for escenario, columna in ESCENARIOS.items():
        bloque = base[base[columna]].copy()
        bloque["escenario"] = escenario
        partes.append(bloque)

    return pd.concat(partes, ignore_index=True, sort=False)


def features_proxy_largo(escenarios: pd.DataFrame) -> pd.DataFrame:
    salida = (
        escenarios.groupby(
            [
                "escenario", "periodo", "fecha_cartera", "afp",
                "factor_proxy_mercado",
            ],
            dropna=False,
            as_index=False,
        )
        .agg(
            peso_exterior=("peso_exterior_reconciliado", "sum"),
            peso_total_fondo=("peso_total_fondo_reconciliado", "sum"),
            identificadores=("identificador_agregacion", "nunique"),
        )
    )

    salida["peso_exterior_pct"] = salida["peso_exterior"] * 100.0
    salida["peso_total_fondo_pct"] = salida["peso_total_fondo"] * 100.0
    return salida


def features_proxy_ancho(largo: pd.DataFrame) -> pd.DataFrame:
    ancho = (
        largo.pivot_table(
            index=["escenario", "periodo", "fecha_cartera", "afp"],
            columns="factor_proxy_mercado",
            values="peso_total_fondo",
            aggfunc="sum",
            fill_value=0.0,
        )
        .reset_index()
    )
    ancho.columns.name = None

    for factor in FACTORES:
        if factor not in ancho.columns:
            ancho[factor] = 0.0

    return ancho[
        ["escenario", "periodo", "fecha_cartera", "afp"] + FACTORES
    ]


def resumen_cobertura(
    escenarios: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    bloque = escenarios.copy()

    bloque["grupo_cobertura"] = np.select(
        [
            bloque["factor_proxy_mercado"].eq("RESIDUAL_NO_MAPEADO"),
            bloque["factor_proxy_mercado"].eq("PRIVATE_ALTERNATIVES"),
            bloque["confianza_factor_proxy"].eq("alta"),
            bloque["confianza_factor_proxy"].eq("media"),
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
        bloque.groupby(
            ["escenario", "periodo", "afp", "grupo_cobertura"],
            as_index=False,
        )
        .agg(
            peso_exterior=("peso_exterior_reconciliado", "sum"),
            peso_total_fondo=("peso_total_fondo_reconciliado", "sum"),
        )
    )

    resumen = (
        mensual.groupby(
            ["escenario", "afp", "grupo_cobertura"],
            as_index=False,
        )
        .agg(
            periodos=("periodo", "nunique"),
            peso_exterior_mediano=("peso_exterior", "median"),
            peso_exterior_p90=(
                "peso_exterior",
                lambda s: float(pd.Series(s).dropna().quantile(0.90)),
            ),
            peso_total_fondo_mediano=("peso_total_fondo", "median"),
        )
    )
    resumen["peso_exterior_mediano_pct"] = (
        resumen["peso_exterior_mediano"] * 100.0
    )
    resumen["peso_total_fondo_mediano_pct"] = (
        resumen["peso_total_fondo_mediano"] * 100.0
    )

    return mensual, resumen


def comparar_cobertura(
    cobertura_anterior: pd.DataFrame,
    cobertura_nueva: pd.DataFrame,
) -> pd.DataFrame:
    anterior = cobertura_anterior.copy()

    columnas_clave = ["escenario", "afp", "grupo_cobertura"]

    anterior = anterior.rename(
        columns={
            "peso_exterior_mediano_pct": "anterior_peso_exterior_mediano_pct",
            "peso_total_fondo_mediano_pct": "anterior_peso_total_fondo_mediano_pct",
        }
    )

    nueva = cobertura_nueva.rename(
        columns={
            "peso_exterior_mediano_pct": "nuevo_peso_exterior_mediano_pct",
            "peso_total_fondo_mediano_pct": "nuevo_peso_total_fondo_mediano_pct",
        }
    )

    comparacion = anterior[
        columnas_clave
        + [
            "anterior_peso_exterior_mediano_pct",
            "anterior_peso_total_fondo_mediano_pct",
        ]
    ].merge(
        nueva[
            columnas_clave
            + [
                "nuevo_peso_exterior_mediano_pct",
                "nuevo_peso_total_fondo_mediano_pct",
            ]
        ],
        on=columnas_clave,
        how="outer",
        validate="one_to_one",
    ).fillna(0.0)

    comparacion["cambio_exterior_pp"] = (
        comparacion["nuevo_peso_exterior_mediano_pct"]
        - comparacion["anterior_peso_exterior_mediano_pct"]
    )
    comparacion["cambio_total_fondo_pp"] = (
        comparacion["nuevo_peso_total_fondo_mediano_pct"]
        - comparacion["anterior_peso_total_fondo_mediano_pct"]
    )

    return comparacion


def control_pesos(
    escenarios: pd.DataFrame,
    largo: pd.DataFrame,
) -> pd.DataFrame:
    original = (
        escenarios.groupby(
            ["escenario", "periodo", "afp"],
            as_index=False,
        )
        .agg(
            peso_exterior_original=("peso_exterior_reconciliado", "sum"),
            peso_fondo_original=("peso_total_fondo_reconciliado", "sum"),
        )
    )

    clasificado = (
        largo.groupby(
            ["escenario", "periodo", "afp"],
            as_index=False,
        )
        .agg(
            peso_exterior_clasificado=("peso_exterior", "sum"),
            peso_fondo_clasificado=("peso_total_fondo", "sum"),
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

    control["estado"] = np.where(
        (control["diferencia_exterior"].abs() <= TOLERANCIA)
        & (control["diferencia_fondo"].abs() <= TOLERANCIA),
        "correcto",
        "revisar",
    )

    return control


def main() -> None:
    raiz = Path(__file__).resolve().parents[1]
    processed = raiz / "data" / "processed"

    taxonomia = preparar_taxonomia(
        leer_csv(
            processed / "ca0001_taxonomia_instrumentos_preliminar.csv",
            ["primera_fecha", "ultima_fecha"],
        )
    )
    base = preparar_base(
        leer_csv(
            processed / "ca0001_base_identificadores_canonica_final.csv",
            ["fecha_cartera"],
        )
    )
    cobertura_anterior = leer_csv(
        processed / "ca0001_taxonomia_resumen_cobertura.csv"
    )

    refinada = refinar_taxonomia(taxonomia)
    base_refinada = aplicar_taxonomia(base, refinada)
    escenarios = construir_escenarios(base_refinada)

    proxy_largo = features_proxy_largo(escenarios)
    proxy_ancho = features_proxy_ancho(proxy_largo)
    cobertura_mensual, cobertura_resumen = resumen_cobertura(escenarios)
    comparacion = comparar_cobertura(
        cobertura_anterior,
        cobertura_resumen,
    )
    control = control_pesos(escenarios, proxy_largo)

    cambios = refinada[
        refinada["cambio_factor"]
        | refinada["cambio_region"]
        | refinada["cambio_sector"]
    ].copy()

    pendientes = refinada[
        refinada["factor_proxy_mercado"].eq("RESIDUAL_NO_MAPEADO")
        | refinada["confianza_factor_proxy"].eq("baja")
    ].sort_values(
        ["peso_max_total_fondo_pct", "meses_presentes"],
        ascending=[False, False],
    )

    rutas = {
        "taxonomia": processed / "ca0001_taxonomia_instrumentos_refinada.csv",
        "base": processed / "ca0001_base_identificadores_taxonomia_refinada.csv",
        "cambios": processed / "ca0001_taxonomia_cambios_refinamiento.csv",
        "pendientes": processed / "ca0001_taxonomia_refinada_pendientes.csv",
        "proxy_largo": processed / "ca0001_features_proxy_refinado_mensual_largo.csv",
        "proxy_ancho": processed / "ca0001_features_proxy_refinado_mensual_ancho.csv",
        "cobertura_mensual": processed / "ca0001_taxonomia_refinada_cobertura_mensual.csv",
        "cobertura_resumen": processed / "ca0001_taxonomia_refinada_resumen_cobertura.csv",
        "comparacion": processed / "ca0001_taxonomia_comparacion_cobertura.csv",
        "control": processed / "ca0001_taxonomia_refinada_control_pesos.csv",
    }

    refinada.to_csv(
        rutas["taxonomia"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    base_refinada.to_csv(
        rutas["base"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    cambios.to_csv(
        rutas["cambios"],
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
    comparacion.to_csv(
        rutas["comparacion"],
        index=False,
        encoding="utf-8-sig",
    )
    control.to_csv(
        rutas["control"],
        index=False,
        encoding="utf-8-sig",
    )

    print("\nREFINAMIENTO DE TAXONOMÍA Y PROXIES TERMINADO")
    print("=" * 120)

    print("\nCAMBIOS APLICADOS")
    print("-" * 120)
    print(f"Instrumentos con algún cambio: {len(cambios)}")
    print(
        cambios.groupby(
            "regla_refinamiento",
            as_index=False,
        )
        .agg(
            instrumentos=("identificador_agregacion", "nunique"),
            peso_maximo_pct=("peso_max_total_fondo_pct", "max"),
        )
        .sort_values(
            ["peso_maximo_pct", "instrumentos"],
            ascending=[False, False],
        )
        .head(40)
        .to_string(index=False)
    )

    print("\nCOMPARACIÓN DE COBERTURA")
    print("-" * 120)
    print(
        comparacion.sort_values(
            ["escenario", "afp", "grupo_cobertura"]
        ).to_string(index=False)
    )

    print("\nCONTROL DE PESOS")
    print("-" * 120)
    print(
        control["estado"]
        .value_counts(dropna=False)
        .rename_axis("estado")
        .reset_index(name="observaciones")
        .to_string(index=False)
    )

    print("\nTOP DE CAMBIOS POR PESO")
    print("-" * 120)
    print(
        cambios.sort_values(
            "peso_max_total_fondo_pct",
            ascending=False,
        )[
            [
                "identificador_agregacion",
                "ticker",
                "name",
                "factor_proxy_original",
                "factor_proxy_mercado",
                "region_original",
                "region_exposicion_preliminar",
                "sector_original",
                "sector_tema_preliminar",
                "confianza_factor_proxy",
                "regla_refinamiento",
                "peso_max_total_fondo_pct",
                "meses_presentes",
            ]
        ]
        .head(50)
        .to_string(index=False)
    )

    print("\nPENDIENTES DESPUÉS DEL REFINAMIENTO")
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
        "- Las reglas exactas de ticker tienen prioridad sobre reglas textuales.\n"
        "- La gestora o custodio ya no se usa para inferir sector o región del activo.\n"
        "- Los ISIN sin identidad económica no se asignan a SPY por su prefijo.\n"
        "- Los fondos de liquidez permanecen como residual hasta incorporar un factor monetario apropiado.\n"
        "- El refinamiento no modifica los pesos reconciliados; solo cambia la etiqueta económica y el proxy.\n"
        "- Los proxies siguen siendo aproximaciones y no sustituyen el look-through de cada fondo."
    )


if __name__ == "__main__":
    main()
