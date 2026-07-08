from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Iterable

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler


AFPS = ["Habitat", "Integra", "Prima", "Profuturo"]
ULTIMAS_CUOTAS_EN_GRAFICO = 120


def limpiar_nombre(valor: object) -> str:
    texto = str(valor).strip().upper()
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(
        caracter
        for caracter in texto
        if not unicodedata.combining(caracter)
    )
    return re.sub(r"[^A-Z0-9]+", "", texto)


def leer_csv_flexible(ruta: Path) -> pd.DataFrame:
    intentos = [
        {"sep": None, "engine": "python", "encoding": "utf-8-sig"},
        {"sep": None, "engine": "python", "encoding": "latin-1"},
        {"sep": ",", "encoding": "utf-8-sig"},
        {"sep": ";", "encoding": "utf-8-sig"},
        {"sep": ";", "encoding": "latin-1"},
    ]

    ultimo_error: Exception | None = None

    for argumentos in intentos:
        try:
            return pd.read_csv(ruta, **argumentos)
        except Exception as error:
            ultimo_error = error

    raise RuntimeError(f"No se pudo leer {ruta}: {ultimo_error}")


def detectar_columna(
    columnas: Iterable[object],
    alias: set[str],
) -> str | None:
    alias_limpios = {limpiar_nombre(valor) for valor in alias}

    for columna in columnas:
        if limpiar_nombre(columna) in alias_limpios:
            return str(columna)

    for columna in columnas:
        limpio = limpiar_nombre(columna)
        for candidato in sorted(alias_limpios, key=len, reverse=True):
            if candidato and (
                limpio.startswith(candidato)
                or limpio.endswith(candidato)
            ):
                return str(columna)

    return None


def normalizar_afp(valor: object) -> str | None:
    limpio = limpiar_nombre(valor)

    for afp in AFPS:
        if limpiar_nombre(afp) in limpio:
            return afp

    return None


def cargar_sbs(processed: Path) -> pd.DataFrame:
    ruta = processed / "sbs_fondo3_base_maestra.csv"

    if not ruta.exists():
        raise FileNotFoundError(f"No existe la base SBS: {ruta}")

    df = leer_csv_flexible(ruta)

    fecha_col = detectar_columna(
        df.columns,
        {"fecha", "date", "fecha_cuota", "fecha_valor_cuota"},
    )
    afp_col = detectar_columna(
        df.columns,
        {"afp", "administradora", "nombre_afp"},
    )
    cuota_col = detectar_columna(
        df.columns,
        {"valor_cuota", "valor_de_la_cuota", "cuota", "valor"},
    )

    if fecha_col is None or afp_col is None or cuota_col is None:
        raise ValueError(
            "La base SBS debe contener fecha, AFP y valor cuota."
        )

    salida = pd.DataFrame(
        {
            "fecha_cuota": pd.to_datetime(
                df[fecha_col],
                errors="coerce",
            ),
            "afp": df[afp_col].map(normalizar_afp),
            "cuota_sbs": pd.to_numeric(
                df[cuota_col],
                errors="coerce",
            ),
        }
    )

    salida = (
        salida.dropna(subset=["fecha_cuota", "afp", "cuota_sbs"])
        .sort_values(["afp", "fecha_cuota"])
        .drop_duplicates(
            subset=["fecha_cuota", "afp"],
            keep="last",
        )
        .reset_index(drop=True)
    )

    salida["cuota_sbs_anterior"] = (
        salida.groupby("afp")["cuota_sbs"].shift(1)
    )
    salida["retorno_cuota"] = (
        salida["cuota_sbs"]
        / salida["cuota_sbs_anterior"]
        - 1.0
    )

    return salida


def cargar_canasta(processed: Path) -> pd.DataFrame:
    ruta = processed / "ca0001_modelo51_canasta_depurada.csv"

    if not ruta.exists():
        raise FileNotFoundError(
            "No existe ca0001_modelo51_canasta_depurada.csv."
        )

    df = leer_csv_flexible(ruta)

    if not {"afp", "factor"}.issubset(df.columns):
        raise ValueError(
            "La canasta depurada debe contener afp y factor."
        )

    df["afp"] = df["afp"].map(normalizar_afp)
    df["factor"] = df["factor"].astype(str)

    if "lag_dias" not in df.columns:
        df["lag_dias"] = 0

    df["lag_dias"] = pd.to_numeric(
        df["lag_dias"],
        errors="coerce",
    ).fillna(0).astype(int)

    if "orden" not in df.columns:
        df["orden"] = (
            df.groupby("afp").cumcount() + 1
        )

    return (
        df.dropna(subset=["afp", "factor"])
        .sort_values(["afp", "orden"])
        .drop_duplicates(subset=["afp", "factor"])
        .reset_index(drop=True)
    )


def cargar_parametros_modelo56(processed: Path) -> pd.DataFrame:
    ruta = processed / "ca0001_modelo56_modelos.csv"

    if not ruta.exists():
        raise FileNotFoundError(
            "No existe ca0001_modelo56_modelos.csv. "
            "Primero ejecute el módulo 56."
        )

    df = leer_csv_flexible(ruta)
    df["afp"] = df["afp"].map(normalizar_afp)

    for columna in ["alpha", "rmse_test", "r2_test"]:
        if columna in df.columns:
            df[columna] = pd.to_numeric(
                df[columna],
                errors="coerce",
            )

    return df


def inferir_transformacion_factor(
    serie: pd.Series,
    nombre: str,
) -> str:
    valores = pd.to_numeric(serie, errors="coerce").dropna()

    if len(valores) < 30:
        return "insuficiente"

    limpio = limpiar_nombre(nombre)
    fraccion_negativa = float((valores < 0).mean())
    fraccion_positiva = float((valores > 0).mean())
    p99_abs = float(valores.abs().quantile(0.99))

    if (
        fraccion_negativa > 0.05
        and fraccion_positiva > 0.05
        and p99_abs <= 0.50
    ):
        return "ya_es_variacion"

    if any(
        token in limpio
        for token in [
            "YIELD",
            "RATE",
            "TASA",
            "TREASURY",
            "TNX",
            "IRX",
            "FVX",
            "TYX",
        ]
    ):
        return "diferencia"

    return "retorno_porcentual"


def cargar_factores(
    processed: Path,
    factores_necesarios: list[str],
) -> pd.DataFrame:
    ruta = processed / "mercados_factores_modelo.csv"

    if not ruta.exists():
        raise FileNotFoundError(
            f"No existe el archivo de mercados: {ruta}"
        )

    df = leer_csv_flexible(ruta)
    fecha_col = detectar_columna(
        df.columns,
        {"fecha", "date", "trading_date"},
    )

    if fecha_col is None:
        fecha_col = str(df.columns[0])

    faltantes = [
        factor
        for factor in factores_necesarios
        if factor not in df.columns
    ]

    if faltantes:
        raise ValueError(
            "Faltan factores en mercados_factores_modelo.csv: "
            + ", ".join(faltantes)
        )

    salida = pd.DataFrame(
        {
            "fecha_mercado": pd.to_datetime(
                df[fecha_col],
                errors="coerce",
            )
        }
    )

    for factor in factores_necesarios:
        serie = pd.to_numeric(df[factor], errors="coerce")
        metodo = inferir_transformacion_factor(serie, factor)

        if metodo == "ya_es_variacion":
            transformada = serie
        elif metodo == "diferencia":
            transformada = serie.diff()
        elif metodo == "retorno_porcentual":
            transformada = serie.pct_change(fill_method=None)
        else:
            raise ValueError(
                f"No se pudo transformar el factor {factor}."
            )

        if (transformada.dropna() <= -1.0).any():
            raise ValueError(
                f"El factor {factor} contiene retornos <= -100 %."
            )

        salida[factor] = transformada

    return (
        salida.dropna(subset=["fecha_mercado"])
        .sort_values("fecha_mercado")
        .drop_duplicates(
            subset=["fecha_mercado"],
            keep="last",
        )
        .reset_index(drop=True)
    )


def crear_calendario_objetivo(
    sbs: pd.DataFrame,
    factores: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.Timestamp, pd.Timestamp]:
    fecha_ultima_sbs = pd.Timestamp(
        sbs["fecha_cuota"].max()
    )
    fecha_ultimo_mercado = pd.Timestamp(
        factores["fecha_mercado"].max()
    )

    fechas_historicas = (
        sbs[["fecha_cuota"]]
        .drop_duplicates()
        .sort_values("fecha_cuota")
    )

    if fecha_ultimo_mercado <= fecha_ultima_sbs:
        futuras = pd.DatetimeIndex([])
    else:
        futuras = pd.bdate_range(
            fecha_ultima_sbs + pd.Timedelta(days=1),
            fecha_ultimo_mercado,
        )

    calendario = pd.DataFrame(
        {
            "fecha_cuota": sorted(
                set(fechas_historicas["fecha_cuota"])
                | set(futuras)
            )
        }
    )

    return calendario, fecha_ultima_sbs, fecha_ultimo_mercado


def alinear_factor(
    calendario: pd.DataFrame,
    factores: pd.DataFrame,
    factor: str,
) -> pd.DataFrame:
    mercado = (
        factores[["fecha_mercado", factor]]
        .dropna(subset=[factor])
        .sort_values("fecha_mercado")
        .copy()
    )

    mercado[f"{factor}__indice"] = (
        1.0 + mercado[factor]
    ).cumprod()

    alineado = pd.merge_asof(
        calendario.sort_values("fecha_cuota"),
        mercado[
            [
                "fecha_mercado",
                f"{factor}__indice",
            ]
        ],
        left_on="fecha_cuota",
        right_on="fecha_mercado",
        direction="backward",
        allow_exact_matches=True,
    )

    alineado[f"{factor}__fecha_usada"] = (
        alineado["fecha_mercado"]
    )
    alineado[f"{factor}__retorno_alineado"] = (
        alineado[f"{factor}__indice"]
        / alineado[f"{factor}__indice"].shift(1)
        - 1.0
    )

    return alineado[
        [
            "fecha_cuota",
            f"{factor}__fecha_usada",
            f"{factor}__retorno_alineado",
        ]
    ]


def construir_base_alineada(
    sbs: pd.DataFrame,
    canasta: pd.DataFrame,
    factores: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.Timestamp, pd.Timestamp]:
    calendario, fecha_ultima_sbs, fecha_ultimo_mercado = (
        crear_calendario_objetivo(sbs, factores)
    )

    base_factores = calendario.copy()
    factores_necesarios = sorted(set(canasta["factor"]))

    for factor in factores_necesarios:
        alineado = alinear_factor(
            calendario,
            factores,
            factor,
        )
        base_factores = base_factores.merge(
            alineado,
            on="fecha_cuota",
            how="left",
            validate="one_to_one",
        )

    historico = sbs.merge(
        base_factores,
        on="fecha_cuota",
        how="left",
        validate="many_to_one",
    )

    futuras = base_factores[
        base_factores["fecha_cuota"].gt(fecha_ultima_sbs)
    ].copy()

    bloques_futuros = []

    for afp in AFPS:
        bloque = futuras.copy()
        bloque["afp"] = afp
        bloque["cuota_sbs"] = np.nan
        bloque["cuota_sbs_anterior"] = np.nan
        bloque["retorno_cuota"] = np.nan
        bloques_futuros.append(bloque)

    if bloques_futuros:
        futuro_afp = pd.concat(
            bloques_futuros,
            ignore_index=True,
        )
        base = pd.concat(
            [historico, futuro_afp],
            ignore_index=True,
            sort=False,
        )
    else:
        base = historico.copy()

    base = base.sort_values(
        ["afp", "fecha_cuota"]
    ).reset_index(drop=True)

    for afp in AFPS:
        indices = base["afp"].eq(afp)
        canasta_afp = canasta[canasta["afp"].eq(afp)]

        for _, fila in canasta_afp.iterrows():
            factor = str(fila["factor"])
            lag = int(fila["lag_dias"])
            columna_retorno = f"{factor}__retorno_alineado"
            columna_fecha = f"{factor}__fecha_usada"

            if lag > 0:
                base.loc[indices, columna_retorno] = (
                    base.loc[indices, columna_retorno].shift(lag)
                )
                base.loc[indices, columna_fecha] = (
                    base.loc[indices, columna_fecha].shift(lag)
                )

            fechas_usadas = base.loc[indices, columna_fecha]
            base.loc[indices, f"{factor}__dato_nuevo"] = (
                fechas_usadas.notna()
                & fechas_usadas.ne(fechas_usadas.shift(1))
            )

    return base, fecha_ultima_sbs, fecha_ultimo_mercado


def clasificar_intensidad(
    retorno_acumulado: float,
    rmse_referencia: float,
    dias_estimados: int,
) -> tuple[str, float]:
    if dias_estimados <= 0 or not np.isfinite(rmse_referencia):
        return "sin_clasificar", np.nan

    rmse_acumulado = rmse_referencia * np.sqrt(dias_estimados)

    if rmse_acumulado <= 0:
        return "sin_clasificar", np.nan

    ratio = abs(retorno_acumulado) / rmse_acumulado

    if ratio < 0.50:
        intensidad = "debil"
    elif ratio < 1.00:
        intensidad = "moderada"
    else:
        intensidad = "alta"

    return intensidad, float(ratio)


def entrenar_y_estimar(
    base: pd.DataFrame,
    canasta: pd.DataFrame,
    parametros56: pd.DataFrame,
    fecha_ultima_sbs: pd.Timestamp,
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
]:
    estimaciones = []
    resumenes = []
    contribuciones = []

    for afp in AFPS:
        canasta_afp = (
            canasta[canasta["afp"].eq(afp)]
            .sort_values("orden")
        )
        factores_afp = (
            canasta_afp["factor"].astype(str).tolist()
        )
        columnas = [
            f"{factor}__retorno_alineado"
            for factor in factores_afp
        ]
        columnas_fechas = [
            f"{factor}__fecha_usada"
            for factor in factores_afp
        ]
        columnas_nuevo = [
            f"{factor}__dato_nuevo"
            for factor in factores_afp
        ]

        historico = (
            base[
                base["afp"].eq(afp)
                & base["fecha_cuota"].le(fecha_ultima_sbs)
            ][
                [
                    "fecha_cuota",
                    "cuota_sbs",
                    "retorno_cuota",
                ]
                + columnas
            ]
            .dropna()
            .sort_values("fecha_cuota")
        )

        futuro = (
            base[
                base["afp"].eq(afp)
                & base["fecha_cuota"].gt(fecha_ultima_sbs)
            ][
                ["fecha_cuota"]
                + columnas
                + columnas_fechas
                + columnas_nuevo
            ]
            .dropna(subset=columnas)
            .sort_values("fecha_cuota")
        )

        parametro = parametros56[
            parametros56["afp"].eq(afp)
        ]

        if parametro.empty:
            raise ValueError(
                f"No se encontró el parámetro del módulo 56 para {afp}."
            )

        alpha = float(parametro["alpha"].iloc[0])
        rmse_test = float(parametro["rmse_test"].iloc[0])

        scaler = StandardScaler()
        x_hist = scaler.fit_transform(
            historico[columnas]
        )
        y_hist = historico[
            "retorno_cuota"
        ].to_numpy()

        modelo = Ridge(alpha=alpha)
        modelo.fit(x_hist, y_hist)

        ultima_cuota = float(
            base[
                base["afp"].eq(afp)
                & base["fecha_cuota"].eq(fecha_ultima_sbs)
            ]["cuota_sbs"].iloc[0]
        )

        if futuro.empty:
            resumenes.append(
                {
                    "afp": afp,
                    "fecha_ultima_cuota_oficial": fecha_ultima_sbs,
                    "cuota_ultima_oficial": ultima_cuota,
                    "fecha_estimada_hasta": fecha_ultima_sbs,
                    "dias_estimados": 0,
                    "retorno_estimado_acumulado": 0.0,
                    "cuota_estimada_actual": ultima_cuota,
                    "direccion": "sin_dias_pendientes",
                    "intensidad": "sin_dias_pendientes",
                    "ratio_senal_rmse": np.nan,
                    "rmse_diario_referencia": rmse_test,
                    "factores": " | ".join(factores_afp),
                    "factores_total": len(factores_afp),
                    "factores_con_dato_nuevo": 0,
                    "cobertura_factores_pct": 0.0,
                    "cobertura_promedio_periodo_pct": 0.0,
                    "estado_cobertura": "SIN_EXTENSION_PENDIENTE",
                    "factores_actualizados": "",
                    "factores_sin_actualizar": " | ".join(factores_afp),
                }
            )
            continue

        x_futuro = scaler.transform(
            futuro[columnas]
        )
        pred = modelo.predict(x_futuro)

        coeficientes_originales = (
            modelo.coef_ / scaler.scale_
        )
        intercepto_original = float(
            modelo.intercept_
            - np.dot(coeficientes_originales, scaler.mean_)
        )
        pred_reconstruida = (
            intercepto_original
            + futuro[columnas].to_numpy()
            @ coeficientes_originales
        )

        if not np.allclose(
            pred,
            pred_reconstruida,
            rtol=1e-10,
            atol=1e-12,
        ):
            raise RuntimeError(
                f"No se pudo reconciliar la escala original para {afp}."
            )

        futuro = futuro.copy()
        futuro["afp"] = afp
        futuro["factores_total"] = len(factores_afp)
        futuro["factores_con_dato_nuevo"] = (
            futuro[columnas_nuevo]
            .astype("boolean")
            .fillna(False)
            .astype(bool)
            .sum(axis=1)
            .astype(int)
        )
        futuro["cobertura_factores_pct"] = np.where(
            len(factores_afp) > 0,
            futuro["factores_con_dato_nuevo"]
            / len(factores_afp)
            * 100.0,
            np.nan,
        )

        def listar_factores_actualizados(fila: pd.Series) -> str:
            return " | ".join(
                factor
                for factor in factores_afp
                if bool(fila[f"{factor}__dato_nuevo"])
            )

        def listar_factores_sin_actualizar(fila: pd.Series) -> str:
            return " | ".join(
                factor
                for factor in factores_afp
                if not bool(fila[f"{factor}__dato_nuevo"])
            )

        futuro["factores_actualizados"] = futuro.apply(
            listar_factores_actualizados,
            axis=1,
        )
        futuro["factores_sin_actualizar"] = futuro.apply(
            listar_factores_sin_actualizar,
            axis=1,
        )
        futuro["estado_cobertura"] = np.select(
            [
                futuro["factores_con_dato_nuevo"].eq(
                    futuro["factores_total"]
                ),
                futuro["factores_con_dato_nuevo"].eq(0),
            ],
            [
                "COMPLETA",
                "SIN_NUEVA_SENAL",
            ],
            default="PARCIAL",
        )
        futuro["retorno_estimado"] = pred
        futuro["cuota_estimada"] = (
            ultima_cuota
            * (1.0 + futuro["retorno_estimado"]).cumprod()
        )
        futuro["fecha_ultima_cuota_oficial"] = fecha_ultima_sbs
        futuro["cuota_ultima_oficial"] = ultima_cuota
        futuro["dias_desde_ultima_oficial"] = np.arange(
            1,
            len(futuro) + 1,
        )

        for _, fila_futura in futuro.iterrows():
            for factor_idx, factor in enumerate(factores_afp):
                retorno_factor = float(
                    fila_futura[f"{factor}__retorno_alineado"]
                )
                coeficiente_original = float(
                    coeficientes_originales[factor_idx]
                )
                contribuciones.append(
                    {
                        "fecha_cuota": fila_futura["fecha_cuota"],
                        "afp": afp,
                        "factor": factor,
                        "fecha_factor_usada": fila_futura[
                            f"{factor}__fecha_usada"
                        ],
                        "dato_nuevo": bool(
                            fila_futura[f"{factor}__dato_nuevo"]
                        ),
                        "retorno_factor_alineado": retorno_factor,
                        "coeficiente_escala_original": (
                            coeficiente_original
                        ),
                        "contribucion_modelo": float(
                            coeficiente_original * retorno_factor
                        ),
                        "metodo_contribucion": "escala_original",
                    }
                )

            contribuciones.append(
                {
                    "fecha_cuota": fila_futura["fecha_cuota"],
                    "afp": afp,
                    "factor": "intercepto",
                    "fecha_factor_usada": pd.NaT,
                    "dato_nuevo": False,
                    "retorno_factor_alineado": np.nan,
                    "coeficiente_escala_original": np.nan,
                    "contribucion_modelo": intercepto_original,
                    "metodo_contribucion": "escala_original",
                }
            )

        retorno_acumulado = float(
            futuro["cuota_estimada"].iloc[-1]
            / ultima_cuota
            - 1.0
        )
        intensidad, ratio = clasificar_intensidad(
            retorno_acumulado,
            rmse_test,
            len(futuro),
        )

        if retorno_acumulado > 0:
            direccion = "positiva"
        elif retorno_acumulado < 0:
            direccion = "negativa"
        else:
            direccion = "neutral"

        ultima_fila = futuro.iloc[-1]
        resumenes.append(
            {
                "afp": afp,
                "fecha_ultima_cuota_oficial": fecha_ultima_sbs,
                "cuota_ultima_oficial": ultima_cuota,
                "fecha_estimada_hasta": futuro[
                    "fecha_cuota"
                ].max(),
                "dias_estimados": len(futuro),
                "retorno_estimado_acumulado": retorno_acumulado,
                "cuota_estimada_actual": float(
                    futuro["cuota_estimada"].iloc[-1]
                ),
                "direccion": direccion,
                "intensidad": intensidad,
                "ratio_senal_rmse": ratio,
                "rmse_diario_referencia": rmse_test,
                "factores": " | ".join(factores_afp),
                "factores_total": int(
                    ultima_fila["factores_total"]
                ),
                "factores_con_dato_nuevo": int(
                    ultima_fila["factores_con_dato_nuevo"]
                ),
                "cobertura_factores_pct": float(
                    ultima_fila["cobertura_factores_pct"]
                ),
                "cobertura_promedio_periodo_pct": float(
                    futuro["cobertura_factores_pct"].mean()
                ),
                "estado_cobertura": str(
                    ultima_fila["estado_cobertura"]
                ),
                "factores_actualizados": str(
                    ultima_fila["factores_actualizados"]
                ),
                "factores_sin_actualizar": str(
                    ultima_fila["factores_sin_actualizar"]
                ),
            }
        )

        estimaciones.append(
            futuro[
                [
                    "fecha_cuota",
                    "afp",
                    "fecha_ultima_cuota_oficial",
                    "cuota_ultima_oficial",
                    "dias_desde_ultima_oficial",
                    "retorno_estimado",
                    "cuota_estimada",
                    "factores_total",
                    "factores_con_dato_nuevo",
                    "cobertura_factores_pct",
                    "estado_cobertura",
                    "factores_actualizados",
                    "factores_sin_actualizar",
                ]
            ]
        )

    return (
        (
            pd.concat(estimaciones, ignore_index=True)
            if estimaciones
            else pd.DataFrame()
        ),
        pd.DataFrame(resumenes),
        pd.DataFrame(contribuciones),
    )


def crear_graficos(
    sbs: pd.DataFrame,
    estimaciones: pd.DataFrame,
    graficos_dir: Path,
) -> None:
    graficos_dir.mkdir(parents=True, exist_ok=True)

    for afp in AFPS:
        oficial = (
            sbs[sbs["afp"].eq(afp)]
            .sort_values("fecha_cuota")
            .tail(ULTIMAS_CUOTAS_EN_GRAFICO)
        )
        estimada = (
            estimaciones[
                estimaciones["afp"].eq(afp)
            ]
            .sort_values("fecha_cuota")
        )

        plt.figure(figsize=(12, 6))
        plt.plot(
            oficial["fecha_cuota"],
            oficial["cuota_sbs"],
            label="Valor cuota oficial SBS",
            linewidth=1.8,
        )

        if not estimada.empty:
            puente = pd.DataFrame(
                {
                    "fecha_cuota": [
                        oficial["fecha_cuota"].iloc[-1]
                    ],
                    "cuota_estimada": [
                        oficial["cuota_sbs"].iloc[-1]
                    ],
                }
            )
            serie_estimada = pd.concat(
                [
                    puente,
                    estimada[
                        ["fecha_cuota", "cuota_estimada"]
                    ],
                ],
                ignore_index=True,
            )

            plt.plot(
                serie_estimada["fecha_cuota"],
                serie_estimada["cuota_estimada"],
                linestyle="--",
                marker="o",
                label="Valor cuota estimado aún no publicado",
                linewidth=1.4,
            )
            plt.axvline(
                oficial["fecha_cuota"].iloc[-1],
                linestyle=":",
                linewidth=1.0,
                label="Última cuota oficial disponible",
            )

        plt.title(
            f"{afp} Fondo 3: cuota oficial y extensión estimada"
        )
        plt.xlabel("Fecha del valor cuota")
        plt.ylabel("Valor cuota")
        plt.legend()
        plt.grid(True, alpha=0.25)
        plt.tight_layout()
        plt.savefig(
            graficos_dir
            / f"modelo57_{afp.lower()}_oficial_y_estimado.png",
            dpi=180,
        )
        plt.close()


def crear_controles(
    sbs: pd.DataFrame,
    factores: pd.DataFrame,
    estimaciones: pd.DataFrame,
    resumen: pd.DataFrame,
) -> pd.DataFrame:
    fecha_ultima_sbs = pd.Timestamp(
        sbs["fecha_cuota"].max()
    )
    fecha_ultimo_mercado = pd.Timestamp(
        factores["fecha_mercado"].max()
    )

    controles = [
        {
            "control": "canasta_fija",
            "estado": "correcto",
            "detalle": (
                "se usan los activos seleccionados en el módulo 51"
            ),
        },
        {
            "control": "alpha_fijo_modulo56",
            "estado": "correcto",
            "detalle": (
                "la regularización ya fue elegida antes del uso operativo"
            ),
        },
        {
            "control": "entrenamiento_con_todo_el_historico_oficial",
            "estado": "correcto",
            "detalle": (
                "el modelo se reajusta con todas las cuotas oficialmente "
                "conocidas sin cambiar la canasta"
            ),
        },
        {
            "control": "fecha_ultima_sbs",
            "estado": "correcto",
            "detalle": str(fecha_ultima_sbs.date()),
        },
        {
            "control": "fecha_ultimo_mercado",
            "estado": "correcto",
            "detalle": str(fecha_ultimo_mercado.date()),
        },
        {
            "control": "estimaciones_solo_despues_de_sbs",
            "estado": (
                "correcto"
                if (
                    estimaciones.empty
                    or estimaciones["fecha_cuota"]
                    .gt(fecha_ultima_sbs)
                    .all()
                )
                else "revisar"
            ),
            "detalle": (
                f"filas_estimadas={len(estimaciones)}"
            ),
        },
        {
            "control": "cuatro_afp_resumidas",
            "estado": (
                "correcto"
                if resumen["afp"].nunique() == 4
                else "revisar"
            ),
            "detalle": (
                f"afp={resumen['afp'].nunique()}"
            ),
        },
        {
            "control": "cobertura_factores_informada",
            "estado": (
                "correcto"
                if {
                    "cobertura_factores_pct",
                    "estado_cobertura",
                }.issubset(resumen.columns)
                else "revisar"
            ),
            "detalle": (
                "se distingue cobertura completa, parcial y sin nueva señal"
            ),
        },
        {
            "control": "cobertura_en_rango",
            "estado": (
                "correcto"
                if resumen.get(
                    "cobertura_factores_pct",
                    pd.Series(dtype=float),
                ).dropna().between(0.0, 100.0).all()
                else "revisar"
            ),
            "detalle": "la cobertura debe estar entre 0 y 100 %",
        },
    ]

    return pd.DataFrame(controles)


def crear_reporte(
    resumen: pd.DataFrame,
    contribuciones: pd.DataFrame,
    ruta: Path,
) -> None:
    lineas = [
        "# Seguimiento operativo del Fondo 3",
        "",
        (
            "El modelo parte de la última cuota oficial disponible y "
            "extiende la serie hasta la fecha más reciente con datos de "
            "mercado. La canasta y la regularización permanecen fijas; "
            "solo se actualizan los datos y se reentrena con las cuotas "
            "oficialmente conocidas."
        ),
        "",
    ]

    for afp in AFPS:
        fila = resumen[resumen["afp"].eq(afp)]

        if fila.empty:
            continue

        fila = fila.iloc[0]
        lineas.extend(
            [
                f"## {afp}",
                "",
                f"- Factores: {fila['factores']}.",
                (
                    f"- Última cuota oficial: "
                    f"{fila['cuota_ultima_oficial']:.6f} "
                    f"({pd.Timestamp(fila['fecha_ultima_cuota_oficial']).date()})."
                ),
                (
                    f"- Cuota estimada: "
                    f"{fila['cuota_estimada_actual']:.6f} "
                    f"hasta {pd.Timestamp(fila['fecha_estimada_hasta']).date()}."
                ),
                (
                    f"- Variación acumulada estimada: "
                    f"{fila['retorno_estimado_acumulado'] * 100:.3f} %."
                ),
                (
                    f"- Señal: {fila['direccion']} / "
                    f"{fila['intensidad']}."
                ),
                (
                    f"- Cobertura de factores en la última fecha: "
                    f"{fila['cobertura_factores_pct']:.1f} % "
                    f"({fila['estado_cobertura']})."
                ),
                (
                    f"- Factores actualizados: "
                    f"{fila['factores_actualizados'] or 'ninguno'}."
                ),
                "",
            ]
        )

        contrib_afp = contribuciones[
            contribuciones["afp"].eq(afp)
            & contribuciones["factor"].ne("intercepto")
        ]

        if not contrib_afp.empty:
            totales = (
                contrib_afp.groupby("factor", as_index=False)[
                    "contribucion_modelo"
                ]
                .sum()
                .assign(
                    magnitud=lambda x: x[
                        "contribucion_modelo"
                    ].abs()
                )
                .sort_values("magnitud", ascending=False)
            )
            lineas.append("Contribución acumulada aproximada:")

            for _, contrib in totales.iterrows():
                lineas.append(
                    f"- {contrib['factor']}: "
                    f"{contrib['contribucion_modelo'] * 100:.3f} puntos porcentuales."
                )

            lineas.append("")

    lineas.extend(
        [
            "## Advertencia",
            "",
            (
                "La intensidad compara la variación acumulada con el RMSE "
                "histórico del modelo. No es una garantía ni un intervalo "
                "de confianza. La cuota estimada se reemplaza por el dato "
                "oficial cada vez que la SBS publica una nueva observación."
            ),
        ]
    )

    ruta.write_text("\n".join(lineas), encoding="utf-8")


def main() -> None:
    raiz = Path(__file__).resolve().parents[1]
    processed = raiz / "data" / "processed"
    graficos_dir = processed / "graficos_modelo57"

    sbs = cargar_sbs(processed)
    canasta = cargar_canasta(processed)
    parametros56 = cargar_parametros_modelo56(processed)
    factores_necesarios = sorted(set(canasta["factor"]))
    factores = cargar_factores(
        processed,
        factores_necesarios,
    )
    base, fecha_ultima_sbs, fecha_ultimo_mercado = (
        construir_base_alineada(
            sbs,
            canasta,
            factores,
        )
    )
    estimaciones, resumen, contribuciones = (
        entrenar_y_estimar(
            base,
            canasta,
            parametros56,
            fecha_ultima_sbs,
        )
    )
    controles = crear_controles(
        sbs,
        factores,
        estimaciones,
        resumen,
    )

    crear_graficos(
        sbs,
        estimaciones,
        graficos_dir,
    )

    rutas = {
        "estimaciones": (
            processed
            / "ca0001_modelo57_estimaciones_pendientes.csv"
        ),
        "resumen": (
            processed
            / "ca0001_modelo57_resumen_actual.csv"
        ),
        "contribuciones": (
            processed
            / "ca0001_modelo57_contribuciones.csv"
        ),
        "controles": (
            processed
            / "ca0001_modelo57_controles.csv"
        ),
        "reporte": (
            processed
            / "ca0001_modelo57_reporte.md"
        ),
        "json": (
            processed
            / "ca0001_modelo57_resumen.json"
        ),
    }

    estimaciones.to_csv(
        rutas["estimaciones"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    resumen.to_csv(
        rutas["resumen"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    contribuciones.to_csv(
        rutas["contribuciones"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    controles.to_csv(
        rutas["controles"],
        index=False,
        encoding="utf-8-sig",
    )
    crear_reporte(
        resumen,
        contribuciones,
        rutas["reporte"],
    )

    contenido = {
        "version": "modelo57_seguimiento_operativo_cobertura_v2",
        "fecha_ultima_sbs": str(fecha_ultima_sbs.date()),
        "fecha_ultimo_mercado": str(fecha_ultimo_mercado.date()),
        "resumen": resumen.to_dict(orient="records"),
        "controles": controles.to_dict(orient="records"),
        "graficos": [
            ruta.name
            for ruta in sorted(graficos_dir.glob("*.png"))
        ],
        "nota": (
            "La serie estimada comienza después de la última cuota oficial, "
            "informa la cobertura efectiva de factores y separa las "
            "contribuciones en escala original."
        ),
    }
    rutas["json"].write_text(
        json.dumps(
            contenido,
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )

    print("\nSEGUIMIENTO OPERATIVO DEL FONDO 3 TERMINADO")
    print("=" * 120)

    print("\nRESUMEN ACTUAL POR AFP")
    print("-" * 120)
    print(resumen.to_string(index=False))

    print("\nESTIMACIONES PENDIENTES")
    print("-" * 120)
    if estimaciones.empty:
        print(
            "No existen fechas de mercado posteriores a la última cuota SBS."
        )
    else:
        print(estimaciones.to_string(index=False))

    print("\nCONTRIBUCIONES ACUMULADAS POR FACTOR EN ESCALA ORIGINAL")
    print("-" * 120)
    if contribuciones.empty:
        print("No existen contribuciones pendientes.")
    else:
        tabla = (
            contribuciones[
                contribuciones["factor"].ne("intercepto")
            ]
            .groupby(["afp", "factor"], as_index=False)[
                "contribucion_modelo"
            ]
            .sum()
            .sort_values(
                ["afp", "contribucion_modelo"],
                ascending=[True, False],
            )
        )
        tabla["contribucion_pp"] = (
            tabla["contribucion_modelo"] * 100.0
        )
        print(
            tabla[
                ["afp", "factor", "contribucion_pp"]
            ].to_string(index=False)
        )

    print("\nCONTROLES")
    print("-" * 120)
    print(controles.to_string(index=False))

    print("\nArchivos creados:")
    for ruta in rutas.values():
        print(f" - {ruta.resolve()}")
    print(f" - Carpeta de gráficos: {graficos_dir.resolve()}")

    print(
        "\nLectura correcta:\n"
        "- La línea oficial termina en la última cuota conocida.\n"
        "- La línea estimada continúa hasta la última fecha de mercado.\n"
        "- La señal indica dirección e intensidad, no una certeza.\n"
        "- La cobertura distingue días completos, parciales o sin nueva señal.\n"
        "- Un factor con retorno cero tiene contribución directa cero.\n"
        "- Cuando la SBS publique una nueva cuota, vuelva a ejecutar los "
        "módulos de actualización de datos y luego este módulo 57."
    )


if __name__ == "__main__":
    main()
