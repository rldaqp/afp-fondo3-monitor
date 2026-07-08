from __future__ import annotations

import json
import warnings
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler


warnings.filterwarnings("ignore")

MIN_COBERTURA_PUBLICABLE_PCT = 100.0
DIAS_BUFFER_DESCARGA = 35


@dataclass
class ModeloCongelado:
    scaler: StandardScaler
    ridge: Ridge
    familia: str
    alpha: float
    half_life: int | None
    columnas: list[str]

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        z = self.scaler.transform(X[self.columnas])
        return self.ridge.predict(z)


def leer_csv(
    ruta: Path,
    obligatorio: bool = True,
) -> pd.DataFrame:
    if not ruta.exists():
        if obligatorio:
            raise FileNotFoundError(f"Falta el archivo: {ruta}")
        return pd.DataFrame()

    ultimo_error: Exception | None = None

    for encoding in ["utf-8-sig", "latin-1"]:
        try:
            return pd.read_csv(ruta, encoding=encoding)
        except Exception as exc:
            ultimo_error = exc

    raise RuntimeError(f"No se pudo leer {ruta}: {ultimo_error}")


def escribir_csv(
    df: pd.DataFrame,
    ruta: Path,
) -> None:
    df.to_csv(
        ruta,
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )


def extraer_serie_yfinance(
    descarga: pd.DataFrame,
    ticker: str,
) -> pd.Series:
    if descarga.empty:
        return pd.Series(dtype=float)

    campos = ["Adj Close", "Close"]

    if isinstance(descarga.columns, pd.MultiIndex):
        nivel0 = descarga.columns.get_level_values(0)
        nivel1 = descarga.columns.get_level_values(1)

        for campo in campos:
            if campo in nivel0:
                bloque = descarga[campo]

                if isinstance(bloque, pd.Series):
                    serie = bloque
                elif ticker in bloque.columns:
                    serie = bloque[ticker]
                elif bloque.shape[1] == 1:
                    serie = bloque.iloc[:, 0]
                else:
                    continue

                return pd.to_numeric(
                    serie,
                    errors="coerce",
                )

            if ticker in nivel0:
                bloque = descarga[ticker]

                if campo in bloque.columns:
                    return pd.to_numeric(
                        bloque[campo],
                        errors="coerce",
                    )

            if ticker in nivel1:
                bloque = descarga.xs(
                    ticker,
                    axis=1,
                    level=1,
                )

                if campo in bloque.columns:
                    return pd.to_numeric(
                        bloque[campo],
                        errors="coerce",
                    )

        return pd.Series(dtype=float)

    for campo in campos:
        if campo in descarga.columns:
            return pd.to_numeric(
                descarga[campo],
                errors="coerce",
            )

    return pd.Series(dtype=float)


def normalizar_serie(
    serie: pd.Series,
) -> pd.Series:
    x = serie.dropna().copy()
    fechas = pd.to_datetime(
        x.index,
        errors="coerce",
    )

    try:
        fechas = fechas.tz_localize(None)
    except (TypeError, AttributeError):
        pass

    x.index = pd.DatetimeIndex(
        fechas
    ).normalize()

    x = x[~x.index.isna()]
    x = x[~x.index.duplicated(
        keep="last"
    )]

    return x.sort_index()


def descargar_precio(
    ticker: str,
    fecha_inicio: str,
    fecha_fin: str,
) -> pd.Series:
    try:
        import yfinance as yf
    except ImportError as exc:
        raise RuntimeError(
            "Falta yfinance. Ejecuta: pip install yfinance"
        ) from exc

    datos = yf.download(
        ticker,
        start=fecha_inicio,
        end=fecha_fin,
        auto_adjust=False,
        progress=False,
        threads=False,
    )

    return normalizar_serie(
        extraer_serie_yfinance(
            datos,
            ticker,
        )
    )


def clasificar_transformacion(
    factor: str,
) -> str:
    if factor.startswith("ret_BVL_PEN_"):
        return "LOCAL_PEN"

    if factor.startswith("ret_IDX_LOCAL_"):
        return "INDICE_LOCAL"

    if factor.startswith("ret_PEN_"):
        return "USD_CONVERTIDO_PEN"

    if factor.startswith("ret_USD_"):
        return "USD"

    raise ValueError(
        f"No se reconoce la transformaciÃ³n de {factor}"
    )


def construir_registro_factores(
    canasta: pd.DataFrame,
) -> pd.DataFrame:
    requeridos = (
        canasta[
            [
                "factor",
                "ticker",
                "nombre",
                "categoria",
                "moneda_modelo",
                "fuente_catalogo",
            ]
        ]
        .drop_duplicates("factor")
        .copy()
    )

    requeridos["transformacion_operativa"] = (
        requeridos["factor"]
        .astype(str)
        .map(clasificar_transformacion)
    )

    vacios = requeridos[
        requeridos["ticker"]
        .fillna("")
        .astype(str)
        .str.strip()
        .eq("")
    ]

    if not vacios.empty:
        faltantes = ", ".join(
            vacios["factor"].astype(str)
        )
        raise RuntimeError(
            "La canasta final no contiene ticker para: "
            f"{faltantes}"
        )

    return requeridos


def descargar_factores_operativos(
    registro: pd.DataFrame,
    fecha_inicio: pd.Timestamp,
    fecha_fin: pd.Timestamp,
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
]:
    inicio_str = fecha_inicio.strftime("%Y-%m-%d")
    fin_exclusivo = (
        fecha_fin
        + pd.Timedelta(days=1)
    ).strftime("%Y-%m-%d")

    requiere_fx = registro[
        "transformacion_operativa"
    ].eq("USD_CONVERTIDO_PEN").any()

    precios: dict[str, pd.Series] = {}
    auditoria = []

    tickers = sorted(
        set(
            registro["ticker"]
            .astype(str)
            .tolist()
        )
        | ({"PEN=X"} if requiere_fx else set())
    )

    for numero, ticker in enumerate(
        tickers,
        start=1,
    ):
        print(
            f"  [{numero:02d}/{len(tickers):02d}] "
            f"Descargando {ticker}"
        )

        try:
            serie = descargar_precio(
                ticker,
                inicio_str,
                fin_exclusivo,
            )
            estado = (
                "CORRECTO"
                if len(serie) >= 2
                else "SIN_HISTORIA_SUFICIENTE"
            )
        except Exception as exc:
            serie = pd.Series(dtype=float)
            estado = f"ERROR: {exc}"

        precios[ticker] = serie

        auditoria.append(
            {
                "ticker": ticker,
                "estado": estado,
                "n_precios": int(len(serie)),
                "fecha_inicio": (
                    serie.index.min()
                    if not serie.empty
                    else pd.NaT
                ),
                "fecha_fin": (
                    serie.index.max()
                    if not serie.empty
                    else pd.NaT
                ),
            }
        )

    fx = precios.get(
        "PEN=X",
        pd.Series(dtype=float),
    )

    factores: dict[str, pd.Series] = {}

    for _, fila in registro.iterrows():
        factor = str(fila["factor"])
        ticker = str(fila["ticker"])
        modo = str(
            fila["transformacion_operativa"]
        )

        precio = precios.get(
            ticker,
            pd.Series(dtype=float),
        )

        if precio.empty:
            factores[factor] = pd.Series(
                dtype=float,
                name=factor,
            )
            continue

        if modo in {
            "USD",
            "LOCAL_PEN",
            "INDICE_LOCAL",
        }:
            retorno = precio.pct_change(
                fill_method=None
            )

        elif modo == "USD_CONVERTIDO_PEN":
            if fx.empty:
                retorno = pd.Series(
                    dtype=float,
                )
            else:
                fx_alineado = fx.reindex(
                    precio.index,
                    method="ffill",
                    tolerance=pd.Timedelta(
                        days=5
                    ),
                )
                precio_pen = precio * fx_alineado
                retorno = precio_pen.pct_change(
                    fill_method=None
                )

        else:
            raise ValueError(
                f"Modo desconocido: {modo}"
            )

        retorno.name = factor
        factores[factor] = retorno

    if not factores:
        raise RuntimeError(
            "No se construyÃ³ ningÃºn factor operativo."
        )

    panel = pd.concat(
        factores.values(),
        axis=1,
    ).sort_index()

    panel.index.name = "fecha_cuota"

    return (
        panel.reset_index(),
        pd.DataFrame(auditoria),
    )


def cargar_factores_historicos(
    processed: Path,
) -> pd.DataFrame:
    rutas = [
        processed
        / "ca0001_modelo69_factores_ampliados.csv",
        processed
        / "ca0001_modelo72_factores_bvl.csv",
        processed
        / "ca0001_modelo74_factores_indices.csv",
        processed
        / "ca0001_modelo76_factores_futuros_cripto.csv",
    ]

    acumulado: pd.DataFrame | None = None

    for ruta in rutas:
        df = leer_csv(
            ruta,
            obligatorio=False,
        )

        if df.empty:
            continue

        df["fecha_cuota"] = pd.to_datetime(
            df["fecha_cuota"],
            errors="coerce",
        ).dt.normalize()

        df = (
            df.dropna(
                subset=["fecha_cuota"]
            )
            .drop_duplicates(
                "fecha_cuota",
                keep="last",
            )
        )

        for columna in df.columns:
            if columna != "fecha_cuota":
                df[columna] = pd.to_numeric(
                    df[columna],
                    errors="coerce",
                )

        if acumulado is None:
            acumulado = df
        else:
            columnas_nuevas = [
                c
                for c in df.columns
                if c == "fecha_cuota"
                or c not in acumulado.columns
            ]

            acumulado = acumulado.merge(
                df[columnas_nuevas],
                on="fecha_cuota",
                how="outer",
                validate="one_to_one",
            )

    if acumulado is None:
        raise RuntimeError(
            "No se encontraron factores histÃ³ricos."
        )

    return acumulado.sort_values(
        "fecha_cuota"
    )


def combinar_historico_y_operativo(
    historico: pd.DataFrame,
    operativo: pd.DataFrame,
    factores_requeridos: list[str],
) -> pd.DataFrame:
    fechas = pd.concat(
        [
            historico[["fecha_cuota"]],
            operativo[["fecha_cuota"]],
        ],
        ignore_index=True,
    ).drop_duplicates()

    salida = fechas.sort_values(
        "fecha_cuota"
    ).reset_index(drop=True)

    hist = historico.set_index(
        "fecha_cuota"
    )
    op = operativo.set_index(
        "fecha_cuota"
    )

    for factor in factores_requeridos:
        serie_hist = (
            hist[factor]
            if factor in hist.columns
            else pd.Series(dtype=float)
        )
        serie_op = (
            op[factor]
            if factor in op.columns
            else pd.Series(dtype=float)
        )

        # Los valores histÃ³ricos tienen prioridad.
        combinada = serie_hist.combine_first(
            serie_op
        )

        salida[factor] = salida[
            "fecha_cuota"
        ].map(combinada)

    return salida


def pesos_exponenciales(
    n: int,
    half_life: int,
) -> np.ndarray:
    edades = np.arange(
        n - 1,
        -1,
        -1,
        dtype=float,
    )

    return np.power(
        0.5,
        edades / float(half_life),
    )


def nombre_feature(
    factor: str,
    lag: int,
) -> str:
    return f"{factor}__lag{lag}"


def materializar(
    panel: pd.DataFrame,
    specs: list[dict[str, Any]],
) -> tuple[
    pd.DataFrame,
    list[str],
    list[str],
]:
    x = panel.copy()
    columnas = []
    factores_base = []

    for spec in specs:
        factor = str(spec["factor"])
        lag = int(spec["lag"])
        columna = nombre_feature(
            factor,
            lag,
        )

        if factor not in x.columns:
            raise KeyError(
                f"No existe el factor requerido: {factor}"
            )

        x[columna] = pd.to_numeric(
            x[factor],
            errors="coerce",
        ).shift(lag)

        columnas.append(columna)
        factores_base.append(factor)

    return x, columnas, factores_base


def ajustar_modelo(
    train: pd.DataFrame,
    columnas: list[str],
    familia: str,
    alpha: float,
    half_life: int | None,
) -> ModeloCongelado:
    mascara = train[
        "retorno_cuota"
    ].notna()

    X = (
        train.loc[
            mascara,
            columnas,
        ]
        .replace(
            [np.inf, -np.inf],
            np.nan,
        )
        .fillna(0.0)
    )

    y = train.loc[
        mascara,
        "retorno_cuota",
    ].astype(float)

    if len(y) < 500:
        raise RuntimeError(
            f"Muestra insuficiente: {len(y)}"
        )

    scaler = StandardScaler()
    z = scaler.fit_transform(X)

    ridge = Ridge(
        alpha=float(alpha)
    )

    if familia == "EW_RIDGE":
        if half_life is None:
            raise ValueError(
                "EW_RIDGE requiere half_life."
            )

        ridge.fit(
            z,
            y,
            sample_weight=pesos_exponenciales(
                len(y),
                int(half_life),
            ),
        )
    else:
        ridge.fit(z, y)

    return ModeloCongelado(
        scaler=scaler,
        ridge=ridge,
        familia=familia,
        alpha=float(alpha),
        half_life=half_life,
        columnas=columnas,
    )


def etiqueta_cobertura(
    cobertura_pct: float,
) -> str:
    if cobertura_pct >= 90.0:
        return "ALTA"

    if cobertura_pct >= 75.0:
        return "MEDIA"

    return "BAJA"


def estimar_afp(
    afp: str,
    base: pd.DataFrame,
    factores: pd.DataFrame,
    canasta_afp: pd.DataFrame,
    config_afp: pd.Series,
    run_id: str,
) -> tuple[
    pd.DataFrame,
    dict[str, Any],
    pd.DataFrame,
]:
    cuota = (
        base[
            base["afp"]
            .astype(str)
            .eq(afp)
        ]
        [
            [
                "fecha_cuota",
                "cuota_sbs",
                "retorno_cuota",
            ]
        ]
        .dropna(
            subset=[
                "fecha_cuota",
                "cuota_sbs",
            ]
        )
        .drop_duplicates(
            "fecha_cuota",
            keep="last",
        )
        .sort_values(
            "fecha_cuota"
        )
    )

    if cuota.empty:
        raise RuntimeError(
            f"No existen cuotas para {afp}."
        )

    factores = factores.copy()
    cuota = cuota.copy()
    factores["fecha_cuota"] = pd.to_datetime(factores["fecha_cuota"]).dt.normalize()
    cuota["fecha_cuota"] = pd.to_datetime(cuota["fecha_cuota"]).dt.normalize()

    fecha_ancla = pd.Timestamp(
        cuota["fecha_cuota"].max()
    ).normalize()

    cuota_ancla = float(
        cuota.loc[
            cuota["fecha_cuota"].eq(
                fecha_ancla
            ),
            "cuota_sbs",
        ].iloc[-1]
    )

    specs = (
        canasta_afp
        .sort_values("orden")
        [
            [
                "factor",
                "lag",
            ]
        ]
        .to_dict(
            orient="records"
        )
    )

    panel = factores.merge(
        cuota,
        on="fecha_cuota",
        how="left",
    ).sort_values(
        "fecha_cuota"
    ).reset_index(
        drop=True
    )

    pf, columnas, factores_base = materializar(
        panel,
        specs,
    )

    train = pf[
        pf["fecha_cuota"].le(
            fecha_ancla
        )
    ].copy()

    familia = str(
        config_afp["familia"]
    )
    alpha = float(
        config_afp["alpha"]
    )
    half_life = (
        int(
            config_afp["half_life"]
        )
        if pd.notna(
            config_afp["half_life"]
        )
        else None
    )

    modelo = ajustar_modelo(
        train,
        columnas,
        familia,
        alpha,
        half_life,
    )

    futuro = pf[
        pf["fecha_cuota"].gt(
            fecha_ancla
        )
    ].copy()

    if futuro.empty:
        return (
            pd.DataFrame(),
            {
                "afp": afp,
                "estado": "SIN_DIAS_POSTERIORES_AL_ANCLA",
                "fecha_ultima_cuota_oficial": fecha_ancla,
                "cuota_ultima_oficial": cuota_ancla,
            },
            pd.DataFrame(),
        )

    # La validez se calcula sobre las variables efectivamente
    # utilizadas por la ecuaciÃ³n, incluidos sus rezagos.
    disponibles = futuro[
        columnas
    ].notna().sum(axis=1)

    futuro[
        "n_factores_disponibles"
    ] = disponibles

    futuro[
        "n_factores_totales"
    ] = len(columnas)

    futuro[
        "cobertura_factores_pct"
    ] = (
        disponibles
        / max(
            len(columnas),
            1,
        )
        * 100.0
    )

    # No se imputan ceros ni se fabrican estimaciones.
    # Solo se conservan fechas con todas las variables disponibles.
    futuro = futuro[
        futuro[
            "cobertura_factores_pct"
        ].ge(
            MIN_COBERTURA_PUBLICABLE_PCT
        )
    ].copy()

    if futuro.empty:
        return (
            pd.DataFrame(),
            {
                "afp": afp,
                "estado": "SIN_FECHAS_CON_DATOS_COMPLETOS",
                "fecha_ultima_cuota_oficial": fecha_ancla,
                "cuota_ultima_oficial": cuota_ancla,
            },
            pd.DataFrame(),
        )

    X_futuro = futuro[
        columnas
    ].replace(
        [np.inf, -np.inf],
        np.nan,
    )

    futuro[
        "retorno_diario_estimado"
    ] = modelo.predict(
        X_futuro
    )

    futuro[
        "retorno_acumulado_estimado"
    ] = (
        1.0
        + futuro[
            "retorno_diario_estimado"
        ]
    ).cumprod() - 1.0

    futuro[
        "cuota_estimada"
    ] = (
        cuota_ancla
        * (
            1.0
            + futuro[
                "retorno_acumulado_estimado"
            ]
        )
    )

    futuro[
        "direccion_estimada"
    ] = np.where(
        futuro[
            "retorno_acumulado_estimado"
        ].gt(0),
        "SUBE",
        np.where(
            futuro[
                "retorno_acumulado_estimado"
            ].lt(0),
            "BAJA",
            "SIN_CAMBIO",
        ),
    )

    futuro[
        "nivel_cobertura_datos"
    ] = futuro[
        "cobertura_factores_pct"
    ].map(
        etiqueta_cobertura
    )

    futuro["afp"] = afp
    futuro["run_id"] = run_id
    futuro[
        "fecha_ultima_cuota_oficial"
    ] = fecha_ancla
    futuro[
        "cuota_ultima_oficial"
    ] = cuota_ancla
    futuro["familia"] = familia
    futuro["alpha"] = alpha
    futuro["half_life"] = half_life

    columnas_salida = [
        "run_id",
        "afp",
        "fecha_cuota",
        "fecha_ultima_cuota_oficial",
        "cuota_ultima_oficial",
        "retorno_diario_estimado",
        "retorno_acumulado_estimado",
        "cuota_estimada",
        "direccion_estimada",
        "n_factores_disponibles",
        "n_factores_totales",
        "cobertura_factores_pct",
        "nivel_cobertura_datos",
        "familia",
        "alpha",
        "half_life",
    ]

    detalle = futuro[
        columnas_salida
    ].rename(
        columns={
            "fecha_cuota": "fecha_objetivo"
        }
    )

    publicables = detalle[
        detalle[
            "cobertura_factores_pct"
        ].ge(
            MIN_COBERTURA_PUBLICABLE_PCT
        )
    ]

    if publicables.empty:
        ultima = detalle.iloc[-1]
        estado = (
            "COBERTURA_INSUFICIENTE_EN_TODAS_LAS_FECHAS"
        )
    else:
        ultima = publicables.iloc[-1]
        estado = "ESTIMACION_GENERADA"

    resumen = {
        "run_id": run_id,
        "afp": afp,
        "estado": estado,
        "fecha_ultima_cuota_oficial": fecha_ancla,
        "cuota_ultima_oficial": cuota_ancla,
        "fecha_estimada": ultima[
            "fecha_objetivo"
        ],
        "cuota_estimada": float(
            ultima["cuota_estimada"]
        ),
        "retorno_acumulado_estimado_pct": float(
            ultima[
                "retorno_acumulado_estimado"
            ]
            * 100.0
        ),
        "direccion_estimada": str(
            ultima["direccion_estimada"]
        ),
        "cobertura_factores_pct": float(
            ultima[
                "cobertura_factores_pct"
            ]
        ),
        "nivel_cobertura_datos": str(
            ultima[
                "nivel_cobertura_datos"
            ]
        ),
        "n_factores": int(
            ultima["n_factores_totales"]
        ),
        "familia": familia,
        "alpha": alpha,
        "half_life": half_life,
    }

    coeficientes = pd.DataFrame(
        {
            "afp": afp,
            "factor": [
                str(x["factor"])
                for x in specs
            ],
            "lag": [
                int(x["lag"])
                for x in specs
            ],
            "coeficiente_estandarizado": (
                modelo.ridge.coef_
            ),
        }
    )

    coeficientes[
        "abs_coeficiente"
    ] = coeficientes[
        "coeficiente_estandarizado"
    ].abs()

    coeficientes = coeficientes.sort_values(
        "abs_coeficiente",
        ascending=False,
    )

    return (
        detalle,
        resumen,
        coeficientes,
    )


def anexar_bitacora(
    nuevos: pd.DataFrame,
    ruta: Path,
) -> None:
    anterior = leer_csv(
        ruta,
        obligatorio=False,
    )

    if anterior.empty:
        combinado = nuevos.copy()
    else:
        combinado = pd.concat(
            [
                anterior,
                nuevos,
            ],
            ignore_index=True,
        )

    combinado = combinado.drop_duplicates(
        subset=[
            "run_id",
            "afp",
            "fecha_objetivo",
        ],
        keep="last",
    )

    escribir_csv(
        combinado,
        ruta,
    )


def anexar_primer_pronostico(
    nuevos: pd.DataFrame,
    ruta: Path,
) -> None:
    anterior = leer_csv(
        ruta,
        obligatorio=False,
    )

    if anterior.empty:
        combinado = (
            nuevos.sort_values(
                [
                    "afp",
                    "fecha_objetivo",
                    "run_id",
                ]
            )
            .drop_duplicates(
                subset=[
                    "afp",
                    "fecha_objetivo",
                ],
                keep="first",
            )
        )
    else:
        existentes = set(
            zip(
                anterior["afp"].astype(str),
                anterior[
                    "fecha_objetivo"
                ].astype(str),
            )
        )

        nuevos_solos = nuevos[
            [
                (
                    str(afp),
                    str(fecha),
                )
                not in existentes
                for afp, fecha in zip(
                    nuevos["afp"],
                    nuevos[
                        "fecha_objetivo"
                    ],
                )
            ]
        ]

        combinado = pd.concat(
            [
                anterior,
                nuevos_solos,
            ],
            ignore_index=True,
        )

    escribir_csv(
        combinado,
        ruta,
    )


def main() -> None:
    raiz = Path(
        __file__
    ).resolve().parents[1]

    processed = (
        raiz
        / "data"
        / "processed"
    )

    processed.mkdir(
        parents=True,
        exist_ok=True,
    )

    run_datetime = datetime.now(
        timezone.utc
    )

    run_id = run_datetime.strftime(
        "%Y%m%dT%H%M%SZ"
    )

    base = leer_csv(
        processed
        / "ca0001_modelo56_base_alineada.csv"
    )

    canasta = leer_csv(
        processed
        / "ca0001_modelo78_canasta_final_podada.csv"
    )

    metricas78 = leer_csv(
        processed
        / "ca0001_modelo78_metricas_validacion.csv"
    )

    base["fecha_cuota"] = pd.to_datetime(
        base["fecha_cuota"],
        errors="coerce",
    ).dt.normalize()

    base["cuota_sbs"] = pd.to_numeric(
        base["cuota_sbs"],
        errors="coerce",
    )

    base["retorno_cuota"] = pd.to_numeric(
        base["retorno_cuota"],
        errors="coerce",
    )

    canasta["lag"] = pd.to_numeric(
        canasta["lag"],
        errors="coerce",
    ).astype(int)

    configuraciones = metricas78[
        metricas78[
            "tipo_modelo"
        ].astype(str).eq(
            "CANASTA_PODADA"
        )
    ].copy()

    if configuraciones.empty:
        raise RuntimeError(
            "No se encontraron configuraciones de CANASTA_PODADA."
        )

    registro = construir_registro_factores(
        canasta
    )

    ultima_fecha_oficial = pd.Timestamp(
        base[
            base["cuota_sbs"].notna()
        ]["fecha_cuota"].max()
    ).normalize()

    fecha_inicio_descarga = (
        ultima_fecha_oficial
        - pd.Timedelta(
            days=DIAS_BUFFER_DESCARGA
        )
    )

    fecha_fin_descarga = (
        pd.Timestamp.today().normalize()
    )

    print(
        "\nMÃ“DULO 79 â€” MODELO CONGELADO Y ESTIMACIÃ“N PROSPECTIVA"
    )
    print("=" * 170)
    print(
        f"Ãšltima fecha oficial disponible: "
        f"{ultima_fecha_oficial.date()}"
    )
    print(
        f"EjecuciÃ³n prospectiva: {run_id}"
    )

    print(
        "\nActualizando Ãºnicamente los instrumentos "
        "de la canasta final..."
    )

    operativo, auditoria = (
        descargar_factores_operativos(
            registro,
            fecha_inicio_descarga,
            fecha_fin_descarga,
        )
    )

    historico = cargar_factores_historicos(
        processed
    )

    factores_requeridos = (
        canasta["factor"]
        .astype(str)
        .drop_duplicates()
        .tolist()
    )

    factores = combinar_historico_y_operativo(
        historico,
        operativo,
        factores_requeridos,
    )

    detalles = []
    resumenes = []
    coeficientes = []

    for afp in sorted(
        canasta["afp"]
        .astype(str)
        .unique()
    ):
        config = configuraciones[
            configuraciones[
                "afp"
            ].astype(str).eq(afp)
        ]

        if config.empty:
            raise RuntimeError(
                f"Falta configuraciÃ³n congelada para {afp}."
            )

        detalle, resumen, coef = estimar_afp(
            afp,
            base,
            factores,
            canasta[
                canasta[
                    "afp"
                ].astype(str).eq(afp)
            ],
            config.iloc[0],
            run_id,
        )

        if not detalle.empty:
            detalles.append(detalle)

        resumenes.append(resumen)

        if not coef.empty:
            coeficientes.append(coef)

    detalle_df = (
        pd.concat(
            detalles,
            ignore_index=True,
        )
        if detalles
        else pd.DataFrame()
    )

    resumen_df = pd.DataFrame(
        resumenes
    )

    coeficientes_df = (
        pd.concat(
            coeficientes,
            ignore_index=True,
        )
        if coeficientes
        else pd.DataFrame()
    )

    rutas = {
        "snapshot": (
            processed
            / "ca0001_modelo79_snapshot_estimacion_actual.csv"
        ),
        "detalle": (
            processed
            / "ca0001_modelo79_detalle_estimaciones_run.csv"
        ),
        "bitacora": (
            processed
            / "ca0001_modelo79_bitacora_todas_ejecuciones.csv"
        ),
        "primer_pronostico": (
            processed
            / "ca0001_modelo79_primer_pronostico_congelado.csv"
        ),
        "auditoria": (
            processed
            / "ca0001_modelo79_auditoria_descargas.csv"
        ),
        "coeficientes": (
            processed
            / "ca0001_modelo79_coeficientes_congelados.csv"
        ),
        "canasta": (
            processed
            / "ca0001_modelo79_canasta_congelada.csv"
        ),
        "manifiesto": (
            processed
            / "ca0001_modelo79_manifiesto_modelo_congelado.json"
        ),
    }

    escribir_csv(
        resumen_df,
        rutas["snapshot"],
    )

    escribir_csv(
        detalle_df,
        rutas["detalle"],
    )

    escribir_csv(
        auditoria,
        rutas["auditoria"],
    )

    escribir_csv(
        coeficientes_df,
        rutas["coeficientes"],
    )

    canasta_con_config = canasta.merge(
        configuraciones[
            [
                "afp",
                "familia",
                "alpha",
                "half_life",
            ]
        ],
        on="afp",
        how="left",
    )

    escribir_csv(
        canasta_con_config,
        rutas["canasta"],
    )

    if not detalle_df.empty:
        detalle_valido = detalle_df[
            pd.to_datetime(
                detalle_df["fecha_objetivo"],
                errors="coerce",
            ).notna()
            & pd.to_numeric(
                detalle_df["cobertura_factores_pct"],
                errors="coerce",
            ).ge(
                MIN_COBERTURA_PUBLICABLE_PCT
            )
        ].copy()

        if not detalle_valido.empty:
            anexar_bitacora(
                detalle_valido,
                rutas["bitacora"],
            )

            anexar_primer_pronostico(
                detalle_valido,
                rutas["primer_pronostico"],
            )

    manifiesto = {
        "version": "modelo79_congelado_prospectivo",
        "run_id": run_id,
        "fecha_hora_utc": run_datetime.isoformat(),
        "ultima_fecha_oficial_detectada": str(
            ultima_fecha_oficial.date()
        ),
        "cobertura_minima_publicable_pct": (
            MIN_COBERTURA_PUBLICABLE_PCT
        ),
        "regla_congelamiento": (
            "Canasta final podada del mÃ³dulo 78 y "
            "configuraciÃ³n CANASTA_PODADA. No se realiza "
            "nueva selecciÃ³n de variables."
        ),
        "canasta": canasta_con_config.to_dict(
            orient="records"
        ),
        "nota": (
            "El primer pronÃ³stico de cada AFP y fecha objetivo "
            "se conserva de forma acumulativa para evaluaciÃ³n futura. "
            "La cobertura de datos no equivale a confianza estadÃ­stica."
        ),
    }

    rutas["manifiesto"].write_text(
        json.dumps(
            manifiesto,
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )

    print(
        "\nESTIMACIÃ“N ACTUAL"
    )
    print("-" * 170)

    columnas_mostrar = [
        "afp",
        "estado",
        "fecha_ultima_cuota_oficial",
        "cuota_ultima_oficial",
        "fecha_estimada",
        "cuota_estimada",
        "retorno_acumulado_estimado_pct",
        "direccion_estimada",
        "cobertura_factores_pct",
        "nivel_cobertura_datos",
        "n_factores",
    ]

    disponibles = [
        c
        for c in columnas_mostrar
        if c in resumen_df.columns
    ]

    print(
        resumen_df[
            disponibles
        ].to_string(
            index=False
        )
    )

    print(
        "\nAUDITORÃA DE DESCARGAS"
    )
    print("-" * 170)
    print(
        auditoria.to_string(
            index=False
        )
    )

    print(
        "\nARCHIVOS CREADOS"
    )
    print("-" * 170)
    for ruta in rutas.values():
        print(
            f" - {ruta.resolve()}"
        )

    print(
        "\nLECTURA:\n"
        "- La canasta y los hiperparÃ¡metros quedan congelados.\n"
        "- Cada nueva ejecuciÃ³n puede actualizar precios, pero no "
        "cambiar los factores seleccionados.\n"
        "- La bitÃ¡cora conserva todas las ejecuciones.\n"
        "- El archivo de primer pronÃ³stico guarda la primera estimaciÃ³n "
        "realizada para cada fecha y no la reemplaza despuÃ©s.\n"
        "- Cuando la SBS publique esas cuotas, el mÃ³dulo 80 podrÃ¡ "
        "compararlas contra los pronÃ³sticos congelados."
    )


if __name__ == "__main__":
    main()
