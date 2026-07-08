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
from sklearn.metrics import mean_squared_error, r2_score
from sklearn.preprocessing import StandardScaler


AFPS = ["Habitat", "Integra", "Prima", "Profuturo"]
RETRASO_PUBLICACION_DIAS = 5
ALPHAS = [0.01, 0.1, 1.0, 10.0, 100.0]


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


def cargar_division_temporal(
    processed: Path,
) -> tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp]:
    ruta = processed / "ca0001_modelo50_division_temporal.csv"

    if not ruta.exists():
        raise FileNotFoundError(
            "No existe ca0001_modelo50_division_temporal.csv."
        )

    df = leer_csv_flexible(ruta)
    df["fecha_inicio"] = pd.to_datetime(
        df["fecha_inicio"],
        errors="coerce",
    )
    df["fecha_fin"] = pd.to_datetime(
        df["fecha_fin"],
        errors="coerce",
    )

    train = df[
        df["segmento"].astype(str).eq(
            "entrenamiento_descubrimiento"
        )
    ]
    valid = df[
        df["segmento"].astype(str).eq("validacion")
    ]
    test = df[
        df["segmento"].astype(str).eq("prueba_intocable")
    ]

    if train.empty or valid.empty or test.empty:
        raise ValueError(
            "No se encontraron los tres segmentos temporales."
        )

    return (
        pd.Timestamp(train["fecha_fin"].iloc[0]),
        pd.Timestamp(valid["fecha_fin"].iloc[0]),
        pd.Timestamp(test["fecha_inicio"].iloc[0]),
    )


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

    return (
        df.dropna(subset=["afp", "factor"])
        .drop_duplicates(subset=["afp", "factor"])
        .reset_index(drop=True)
    )


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


def cargar_factores_seleccionados(
    processed: Path,
    factores_necesarios: list[str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
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

    salida = pd.DataFrame(
        {
            "fecha_mercado": pd.to_datetime(
                df[fecha_col],
                errors="coerce",
            )
        }
    )
    auditoria = []

    faltantes = [
        factor
        for factor in factores_necesarios
        if factor not in df.columns
    ]

    if faltantes:
        raise ValueError(
            "Faltan factores seleccionados en mercados_factores_modelo.csv: "
            + ", ".join(faltantes)
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

        salida[factor] = transformada

        auditoria.append(
            {
                "factor": factor,
                "metodo_transformacion": metodo,
                "fecha_minima": salida.loc[
                    salida[factor].notna(),
                    "fecha_mercado",
                ].min(),
                "fecha_maxima": salida.loc[
                    salida[factor].notna(),
                    "fecha_mercado",
                ].max(),
                "observaciones": int(
                    salida[factor].notna().sum()
                ),
            }
        )

    salida = (
        salida.dropna(subset=["fecha_mercado"])
        .sort_values("fecha_mercado")
        .drop_duplicates(
            subset=["fecha_mercado"],
            keep="last",
        )
        .reset_index(drop=True)
    )

    return salida, pd.DataFrame(auditoria)


def alinear_factor_con_cuotas(
    fechas_cuota: pd.DataFrame,
    factores: pd.DataFrame,
    factor: str,
) -> pd.DataFrame:
    mercado_factor = (
        factores[["fecha_mercado", factor]]
        .dropna(subset=[factor])
        .sort_values("fecha_mercado")
        .copy()
    )

    if mercado_factor.empty:
        raise ValueError(f"El factor {factor} no tiene observaciones.")

    if (mercado_factor[factor] <= -1.0).any():
        raise ValueError(
            f"El factor {factor} contiene retornos <= -100 %."
        )

    mercado_factor[f"{factor}__indice"] = (
        1.0 + mercado_factor[factor]
    ).cumprod()

    base = fechas_cuota[["fecha_cuota"]].drop_duplicates().sort_values(
        "fecha_cuota"
    )

    alineado = pd.merge_asof(
        base,
        mercado_factor[
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

    alineado[f"{factor}__fecha_usada"] = alineado["fecha_mercado"]
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
) -> pd.DataFrame:
    factores_necesarios = sorted(set(canasta["factor"]))
    fechas_cuota = (
        sbs[["fecha_cuota"]]
        .drop_duplicates()
        .sort_values("fecha_cuota")
    )

    base_factores = fechas_cuota.copy()

    for factor in factores_necesarios:
        alineado = alinear_factor_con_cuotas(
            fechas_cuota,
            factores,
            factor,
        )
        base_factores = base_factores.merge(
            alineado,
            on="fecha_cuota",
            how="left",
            validate="one_to_one",
        )

    base = sbs.merge(
        base_factores,
        on="fecha_cuota",
        how="left",
        validate="many_to_one",
    )

    for afp in AFPS:
        indices = base["afp"].eq(afp)
        canasta_afp = canasta[canasta["afp"].eq(afp)]

        for _, fila in canasta_afp.iterrows():
            factor = str(fila["factor"])
            lag = int(fila["lag_dias"])
            columna = f"{factor}__retorno_alineado"

            if lag > 0:
                base.loc[indices, columna] = (
                    base.loc[indices, columna].shift(lag)
                )

    return base.sort_values(
        ["afp", "fecha_cuota"]
    ).reset_index(drop=True)


def elegir_alpha(
    train: pd.DataFrame,
    valid: pd.DataFrame,
    columnas: list[str],
) -> tuple[float, float]:
    scaler = StandardScaler()
    x_train = scaler.fit_transform(train[columnas])
    x_valid = scaler.transform(valid[columnas])
    y_train = train["retorno_cuota"].to_numpy()
    y_valid = valid["retorno_cuota"].to_numpy()

    resultados = []

    for alpha in ALPHAS:
        modelo = Ridge(alpha=alpha)
        modelo.fit(x_train, y_train)
        pred = modelo.predict(x_valid)
        rmse = float(
            mean_squared_error(y_valid, pred) ** 0.5
        )
        resultados.append((rmse, alpha))

    return min(resultados, key=lambda par: par[0])


def entrenar_modelos(
    base: pd.DataFrame,
    canasta: pd.DataFrame,
    fin_train: pd.Timestamp,
    fin_valid: pd.Timestamp,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    modelos = []
    predicciones = []

    for afp in AFPS:
        canasta_afp = canasta[
            canasta["afp"].eq(afp)
        ].sort_values("orden" if "orden" in canasta.columns else "factor")

        factores_afp = canasta_afp["factor"].astype(str).tolist()
        columnas = [
            f"{factor}__retorno_alineado"
            for factor in factores_afp
        ]

        bloque = (
            base[base["afp"].eq(afp)]
            [
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

        train = bloque[
            bloque["fecha_cuota"].le(fin_train)
        ]
        valid = bloque[
            bloque["fecha_cuota"].gt(fin_train)
            & bloque["fecha_cuota"].le(fin_valid)
        ]
        test = bloque[
            bloque["fecha_cuota"].gt(fin_valid)
        ]

        if len(train) < 250 or len(valid) < 100 or len(test) < 100:
            raise RuntimeError(
                f"Muestra insuficiente para {afp}: "
                f"train={len(train)}, valid={len(valid)}, test={len(test)}"
            )

        rmse_valid, alpha = elegir_alpha(
            train,
            valid,
            columnas,
        )

        train_valid = pd.concat(
            [train, valid],
            ignore_index=True,
        )

        scaler = StandardScaler()
        x_train_valid = scaler.fit_transform(
            train_valid[columnas]
        )
        x_test = scaler.transform(test[columnas])
        y_train_valid = train_valid["retorno_cuota"].to_numpy()
        y_test = test["retorno_cuota"].to_numpy()

        modelo = Ridge(alpha=alpha)
        modelo.fit(x_train_valid, y_train_valid)
        pred_test = modelo.predict(x_test)

        rmse_test = float(
            mean_squared_error(y_test, pred_test) ** 0.5
        )
        rmse_cero = float(
            mean_squared_error(
                y_test,
                np.zeros_like(y_test),
            ) ** 0.5
        )
        r2_test = float(r2_score(y_test, pred_test))
        direccion = float(
            (
                np.sign(y_test)
                == np.sign(pred_test)
            ).mean()
            * 100.0
        )

        modelos.append(
            {
                "afp": afp,
                "factores": " | ".join(factores_afp),
                "n_factores": len(factores_afp),
                "alpha": alpha,
                "n_train": len(train),
                "n_valid": len(valid),
                "n_test": len(test),
                "rmse_valid": rmse_valid,
                "rmse_test": rmse_test,
                "rmse_baseline_cero": rmse_cero,
                "mejora_rmse_vs_cero_pct": (
                    (rmse_cero - rmse_test)
                    / rmse_cero
                    * 100.0
                ),
                "r2_test": r2_test,
                "direccion_correcta_test_pct": direccion,
                "intercepto": float(modelo.intercept_),
                "coeficientes_estandarizados": json.dumps(
                    {
                        factor: float(coef)
                        for factor, coef in zip(
                            factores_afp,
                            modelo.coef_,
                        )
                    },
                    ensure_ascii=False,
                ),
            }
        )

        predicciones.append(
            pd.DataFrame(
                {
                    "fecha_cuota": test["fecha_cuota"].to_numpy(),
                    "afp": afp,
                    "cuota_sbs": test["cuota_sbs"].to_numpy(),
                    "retorno_real": y_test,
                    "retorno_estimado": pred_test,
                }
            )
        )

    return (
        pd.DataFrame(modelos),
        pd.concat(predicciones, ignore_index=True),
    )


def simular_retraso_publicacion(
    sbs: pd.DataFrame,
    predicciones: pd.DataFrame,
    fin_valid: pd.Timestamp,
) -> pd.DataFrame:
    resultados = []

    for afp in AFPS:
        cuotas_afp = (
            sbs[sbs["afp"].eq(afp)]
            .sort_values("fecha_cuota")
            .reset_index(drop=True)
        )
        pred_afp = (
            predicciones[predicciones["afp"].eq(afp)]
            .sort_values("fecha_cuota")
            .reset_index(drop=True)
        )

        pred_map = pred_afp.set_index(
            "fecha_cuota"
        )["retorno_estimado"].to_dict()

        for _, objetivo in pred_afp.iterrows():
            fecha_objetivo = pd.Timestamp(objetivo["fecha_cuota"])
            fecha_corte_visible = (
                fecha_objetivo
                - pd.Timedelta(days=RETRASO_PUBLICACION_DIAS)
            )

            candidatas = cuotas_afp[
                cuotas_afp["fecha_cuota"].le(fecha_corte_visible)
            ]

            if candidatas.empty:
                continue

            ancla = candidatas.iloc[-1]
            fecha_ancla = pd.Timestamp(ancla["fecha_cuota"])

            # Evita que las primeras ventanas de prueba usen predicciones
            # in-sample del periodo de validación.
            if fecha_ancla <= fin_valid:
                continue

            fechas_ocultas = cuotas_afp[
                cuotas_afp["fecha_cuota"].gt(fecha_ancla)
                & cuotas_afp["fecha_cuota"].le(fecha_objetivo)
            ]["fecha_cuota"].tolist()

            faltantes = [
                fecha
                for fecha in fechas_ocultas
                if fecha not in pred_map
            ]

            if faltantes:
                continue

            retornos_estimados = np.array(
                [pred_map[fecha] for fecha in fechas_ocultas],
                dtype=float,
            )

            cuota_ancla = float(ancla["cuota_sbs"])
            cuota_real = float(objetivo["cuota_sbs"])
            retorno_estimado_acumulado = float(
                np.prod(1.0 + retornos_estimados) - 1.0
            )
            cuota_estimada = cuota_ancla * (
                1.0 + retorno_estimado_acumulado
            )
            retorno_real_acumulado = (
                cuota_real / cuota_ancla - 1.0
            )
            error_pct = cuota_estimada / cuota_real - 1.0

            resultados.append(
                {
                    "afp": afp,
                    "fecha_hoy_simulada": fecha_objetivo,
                    "retraso_publicacion_dias": (
                        RETRASO_PUBLICACION_DIAS
                    ),
                    "fecha_corte_visible": fecha_corte_visible,
                    "fecha_ultima_cuota_visible": fecha_ancla,
                    "cuota_ultima_visible": cuota_ancla,
                    "cuotas_ocultas_estimadas": len(fechas_ocultas),
                    "primera_fecha_oculta": min(fechas_ocultas),
                    "ultima_fecha_oculta": max(fechas_ocultas),
                    "retorno_estimado_acumulado": (
                        retorno_estimado_acumulado
                    ),
                    "retorno_real_acumulado": retorno_real_acumulado,
                    "cuota_estimada_hoy": cuota_estimada,
                    "cuota_real_hoy": cuota_real,
                    "error_pct": error_pct,
                    "error_abs_pct": abs(error_pct),
                    "direccion_correcta": (
                        np.sign(retorno_estimado_acumulado)
                        == np.sign(retorno_real_acumulado)
                    ),
                }
            )

    return pd.DataFrame(resultados)


def calcular_metricas_simulacion(
    simulacion: pd.DataFrame,
) -> pd.DataFrame:
    filas = []

    for afp in AFPS:
        bloque = simulacion[
            simulacion["afp"].eq(afp)
        ].copy()

        if bloque.empty:
            continue

        filas.append(
            {
                "afp": afp,
                "retraso_publicacion_dias": (
                    RETRASO_PUBLICACION_DIAS
                ),
                "fecha_inicio": bloque[
                    "fecha_hoy_simulada"
                ].min(),
                "fecha_fin": bloque[
                    "fecha_hoy_simulada"
                ].max(),
                "observaciones": len(bloque),
                "promedio_cuotas_ocultas": float(
                    bloque["cuotas_ocultas_estimadas"].mean()
                ),
                "min_cuotas_ocultas": int(
                    bloque["cuotas_ocultas_estimadas"].min()
                ),
                "max_cuotas_ocultas": int(
                    bloque["cuotas_ocultas_estimadas"].max()
                ),
                "mape_cuota_pct": float(
                    bloque["error_abs_pct"].mean() * 100.0
                ),
                "mediana_error_abs_pct": float(
                    bloque["error_abs_pct"].median() * 100.0
                ),
                "p90_error_abs_pct": float(
                    bloque["error_abs_pct"].quantile(0.90) * 100.0
                ),
                "sesgo_medio_pct": float(
                    bloque["error_pct"].mean() * 100.0
                ),
                "correlacion_retorno_acumulado": float(
                    bloque["retorno_real_acumulado"].corr(
                        bloque["retorno_estimado_acumulado"]
                    )
                ),
                "direccion_correcta_pct": float(
                    bloque["direccion_correcta"].mean() * 100.0
                ),
            }
        )

    return pd.DataFrame(filas)


def construir_ultima_ventana(
    simulacion: pd.DataFrame,
) -> pd.DataFrame:
    return (
        simulacion.sort_values(
            ["afp", "fecha_hoy_simulada"]
        )
        .groupby("afp", as_index=False)
        .tail(1)
        .reset_index(drop=True)
    )


def crear_graficos(
    simulacion: pd.DataFrame,
    predicciones: pd.DataFrame,
    graficos_dir: Path,
) -> None:
    graficos_dir.mkdir(parents=True, exist_ok=True)

    for afp in AFPS:
        bloque = (
            simulacion[simulacion["afp"].eq(afp)]
            .sort_values("fecha_hoy_simulada")
        )

        if bloque.empty:
            continue

        plt.figure(figsize=(12, 6))
        plt.plot(
            bloque["fecha_hoy_simulada"],
            bloque["cuota_real_hoy"],
            label="Valor cuota real SBS",
            linewidth=1.8,
        )
        plt.plot(
            bloque["fecha_hoy_simulada"],
            bloque["cuota_estimada_hoy"],
            label="Valor cuota estimado con publicación retrasada 5 días",
            linewidth=1.2,
        )
        plt.title(
            f"{afp} Fondo 3: cuota SBS vs estimación con retraso de publicación"
        )
        plt.xlabel("Fecha del valor cuota")
        plt.ylabel("Valor cuota")
        plt.legend()
        plt.grid(True, alpha=0.25)
        plt.tight_layout()
        plt.savefig(
            graficos_dir
            / f"modelo56_{afp.lower()}_sbs_vs_estimacion_5d.png",
            dpi=180,
        )
        plt.close()

        plt.figure(figsize=(12, 5))
        plt.plot(
            bloque["fecha_hoy_simulada"],
            bloque["error_pct"] * 100.0,
            linewidth=1.0,
        )
        plt.axhline(0.0, linewidth=1.0)
        plt.title(
            f"{afp} Fondo 3: error de la estimación con retraso de 5 días"
        )
        plt.xlabel("Fecha del valor cuota")
        plt.ylabel("Error estimado - real (%)")
        plt.grid(True, alpha=0.25)
        plt.tight_layout()
        plt.savefig(
            graficos_dir
            / f"modelo56_{afp.lower()}_error_estimacion_5d.png",
            dpi=180,
        )
        plt.close()

        ultima = bloque.iloc[-1]
        fecha_ancla = pd.Timestamp(
            ultima["fecha_ultima_cuota_visible"]
        )
        fecha_objetivo = pd.Timestamp(
            ultima["fecha_hoy_simulada"]
        )

        pred_afp = (
            predicciones[
                predicciones["afp"].eq(afp)
                & predicciones["fecha_cuota"].gt(fecha_ancla)
                & predicciones["fecha_cuota"].le(fecha_objetivo)
            ]
            .sort_values("fecha_cuota")
            .copy()
        )

        cuota_ancla = float(
            ultima["cuota_ultima_visible"]
        )
        pred_afp["cuota_estimada_trayectoria"] = (
            cuota_ancla
            * (1.0 + pred_afp["retorno_estimado"]).cumprod()
        )

        plt.figure(figsize=(10, 5))
        plt.plot(
            pred_afp["fecha_cuota"],
            pred_afp["cuota_sbs"],
            marker="o",
            label="Cuotas reales luego publicadas por SBS",
        )
        plt.plot(
            pred_afp["fecha_cuota"],
            pred_afp["cuota_estimada_trayectoria"],
            marker="o",
            linestyle="--",
            label="Cuotas estimadas mientras aún estaban ocultas",
        )
        plt.scatter(
            [fecha_ancla],
            [cuota_ancla],
            marker="s",
            label="Última cuota visible en esa fecha",
        )
        plt.title(
            f"{afp}: última ventana histórica simulada de publicación"
        )
        plt.xlabel("Fecha del valor cuota")
        plt.ylabel("Valor cuota")
        plt.legend()
        plt.grid(True, alpha=0.25)
        plt.tight_layout()
        plt.savefig(
            graficos_dir
            / f"modelo56_{afp.lower()}_ultima_ventana_oculta.png",
            dpi=180,
        )
        plt.close()


def crear_controles(
    base: pd.DataFrame,
    modelos: pd.DataFrame,
    simulacion: pd.DataFrame,
) -> pd.DataFrame:
    fechas_mercado_usadas = [
        columna
        for columna in base.columns
        if columna.endswith("__fecha_usada")
    ]

    no_futuro = True

    for columna in fechas_mercado_usadas:
        mascara = base[columna].notna()
        if (
            base.loc[mascara, columna]
            > base.loc[mascara, "fecha_cuota"]
        ).any():
            no_futuro = False
            break

    controles = [
        {
            "control": "canasta_fija_modulo51",
            "estado": "correcto",
            "detalle": (
                "los factores no se vuelven a seleccionar con el test"
            ),
        },
        {
            "control": "mercado_sin_futuro",
            "estado": "correcto" if no_futuro else "revisar",
            "detalle": (
                "cada cuota usa el último cierre de mercado disponible "
                "en esa fecha o antes"
            ),
        },
        {
            "control": "modelos_evaluados",
            "estado": (
                "correcto"
                if len(modelos) == 4
                else "revisar"
            ),
            "detalle": f"modelos={len(modelos)}",
        },
        {
            "control": "retraso_exactamente_5_dias",
            "estado": (
                "correcto"
                if (
                    not simulacion.empty
                    and simulacion[
                        "retraso_publicacion_dias"
                    ].eq(RETRASO_PUBLICACION_DIAS).all()
                )
                else "revisar"
            ),
            "detalle": (
                "fecha de corte visible = fecha objetivo menos 5 días calendario"
            ),
        },
        {
            "control": "sin_cuotas_futuras_en_estimacion",
            "estado": "correcto",
            "detalle": (
                "la cuota real del objetivo se usa solo para evaluar, "
                "no para calcular la estimación"
            ),
        },
        {
            "control": "ventanas_completas",
            "estado": (
                "correcto"
                if not simulacion.empty
                else "revisar"
            ),
            "detalle": (
                f"simulaciones_completas={len(simulacion)}"
            ),
        },
    ]

    return pd.DataFrame(controles)


def crear_reporte(
    metricas: pd.DataFrame,
    modelos: pd.DataFrame,
    ultima: pd.DataFrame,
    ruta: Path,
) -> None:
    lineas = [
        "# Simulación correcta del retraso de publicación de la SBS",
        "",
        (
            "Para cada fecha histórica tratada como “hoy”, el sistema "
            "supone que solo están visibles las cuotas cuya fecha es al "
            "menos cinco días calendario anterior. Las cuotas más recientes "
            "se estiman con los activos seleccionados en el módulo 51."
        ),
        "",
        "## Resultados por AFP",
        "",
    ]

    for afp in AFPS:
        met = metricas[metricas["afp"].eq(afp)]
        mod = modelos[modelos["afp"].eq(afp)]
        ult = ultima[ultima["afp"].eq(afp)]

        if met.empty:
            continue

        fila = met.iloc[0]
        factores = (
            mod["factores"].iloc[0]
            if not mod.empty
            else ""
        )

        lineas.extend(
            [
                f"### {afp}",
                "",
                f"- Activos de seguimiento: {factores}.",
                (
                    f"- Error porcentual absoluto medio: "
                    f"{fila['mape_cuota_pct']:.3f} %."
                ),
                (
                    f"- Dirección acumulada correcta: "
                    f"{fila['direccion_correcta_pct']:.1f} %."
                ),
                (
                    f"- Correlación del movimiento acumulado: "
                    f"{fila['correlacion_retorno_acumulado']:.3f}."
                ),
                (
                    f"- Cuotas ocultas estimadas por ventana: "
                    f"{fila['min_cuotas_ocultas']} a "
                    f"{fila['max_cuotas_ocultas']}."
                ),
            ]
        )

        if not ult.empty:
            u = ult.iloc[0]
            lineas.extend(
                [
                    (
                        f"- Última simulación: el {pd.Timestamp(u['fecha_hoy_simulada']).date()} "
                        f"solo habría estado visible la cuota del "
                        f"{pd.Timestamp(u['fecha_ultima_cuota_visible']).date()}."
                    ),
                    (
                        f"- Cuota estimada: {u['cuota_estimada_hoy']:.6f}; "
                        f"cuota posteriormente observada: "
                        f"{u['cuota_real_hoy']:.6f}."
                    ),
                ]
            )

        lineas.append("")

    lineas.extend(
        [
            "## Interpretación",
            "",
            (
                "La prueba ya no exige que la SBS y los ETF compartan "
                "exactamente el mismo calendario. Cada valor cuota se alinea "
                "con el último cierre disponible de cada factor."
            ),
            (
                "La estimación se reancla en la última cuota que habría estado "
                "publicada. La cuota real del día objetivo se mantiene oculta "
                "durante el cálculo y se usa únicamente para medir el error."
            ),
        ]
    )

    ruta.write_text("\n".join(lineas), encoding="utf-8")


def main() -> None:
    raiz = Path(__file__).resolve().parents[1]
    processed = raiz / "data" / "processed"
    graficos_dir = processed / "graficos_modelo56"

    fin_train, fin_valid, _ = cargar_division_temporal(processed)
    sbs = cargar_sbs(processed)
    canasta = cargar_canasta(processed)
    factores_necesarios = sorted(set(canasta["factor"]))

    factores, auditoria_factores = cargar_factores_seleccionados(
        processed,
        factores_necesarios,
    )
    base_alineada = construir_base_alineada(
        sbs,
        canasta,
        factores,
    )
    modelos, predicciones = entrenar_modelos(
        base_alineada,
        canasta,
        fin_train,
        fin_valid,
    )
    simulacion = simular_retraso_publicacion(
        sbs,
        predicciones,
        fin_valid,
    )
    metricas = calcular_metricas_simulacion(simulacion)
    ultima = construir_ultima_ventana(simulacion)
    controles = crear_controles(
        base_alineada,
        modelos,
        simulacion,
    )

    crear_graficos(
        simulacion,
        predicciones,
        graficos_dir,
    )

    rutas = {
        "auditoria_factores": (
            processed
            / "ca0001_modelo56_auditoria_factores.csv"
        ),
        "base_alineada": (
            processed
            / "ca0001_modelo56_base_alineada.csv"
        ),
        "modelos": (
            processed
            / "ca0001_modelo56_modelos.csv"
        ),
        "predicciones": (
            processed
            / "ca0001_modelo56_predicciones_diarias.csv"
        ),
        "simulacion": (
            processed
            / "ca0001_modelo56_simulacion_publicacion_5d.csv"
        ),
        "metricas": (
            processed
            / "ca0001_modelo56_metricas.csv"
        ),
        "ultima": (
            processed
            / "ca0001_modelo56_ultima_ventana.csv"
        ),
        "controles": (
            processed
            / "ca0001_modelo56_controles.csv"
        ),
        "reporte": (
            processed
            / "ca0001_modelo56_reporte.md"
        ),
        "json": (
            processed
            / "ca0001_modelo56_resumen.json"
        ),
    }

    auditoria_factores.to_csv(
        rutas["auditoria_factores"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    base_alineada.to_csv(
        rutas["base_alineada"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    modelos.to_csv(
        rutas["modelos"],
        index=False,
        encoding="utf-8-sig",
    )
    predicciones.to_csv(
        rutas["predicciones"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    simulacion.to_csv(
        rutas["simulacion"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    metricas.to_csv(
        rutas["metricas"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    ultima.to_csv(
        rutas["ultima"],
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
        metricas,
        modelos,
        ultima,
        rutas["reporte"],
    )

    contenido = {
        "version": "modelo56_publicacion_sbs_retrasada_5_dias",
        "retraso_publicacion_dias": RETRASO_PUBLICACION_DIAS,
        "modelos": modelos.to_dict(orient="records"),
        "metricas": metricas.to_dict(orient="records"),
        "ultima_ventana": ultima.to_dict(orient="records"),
        "controles": controles.to_dict(orient="records"),
        "graficos": [
            ruta.name
            for ruta in sorted(graficos_dir.glob("*.png"))
        ],
        "nota": (
            "La fecha objetivo representa el día cuyo valor cuota se desea "
            "estimar. La última cuota visible es la más reciente cuya fecha "
            "sea menor o igual a fecha objetivo menos cinco días calendario."
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

    print("\nSIMULACIÓN CORRECTA DE PUBLICACIÓN SBS TERMINADA")
    print("=" * 120)

    print("\nMODELOS CON CALENDARIOS ALINEADOS")
    print("-" * 120)
    print(
        modelos[
            [
                "afp",
                "factores",
                "alpha",
                "n_train",
                "n_valid",
                "n_test",
                "r2_test",
                "direccion_correcta_test_pct",
                "mejora_rmse_vs_cero_pct",
            ]
        ].to_string(index=False)
    )

    print("\nRESULTADO DEL RETRASO DE PUBLICACIÓN DE 5 DÍAS")
    print("-" * 120)
    print(metricas.to_string(index=False))

    print("\nÚLTIMA VENTANA HISTÓRICA SIMULADA")
    print("-" * 120)
    columnas_ultima = [
        "afp",
        "fecha_hoy_simulada",
        "fecha_corte_visible",
        "fecha_ultima_cuota_visible",
        "cuota_ultima_visible",
        "cuotas_ocultas_estimadas",
        "primera_fecha_oculta",
        "ultima_fecha_oculta",
        "cuota_estimada_hoy",
        "cuota_real_hoy",
        "error_pct",
        "direccion_correcta",
    ]
    print(ultima[columnas_ultima].to_string(index=False))

    print("\nCONTROLES")
    print("-" * 120)
    print(controles.to_string(index=False))

    print("\nArchivos creados:")
    for ruta in rutas.values():
        print(f" - {ruta.resolve()}")
    print(f" - Carpeta de gráficos: {graficos_dir.resolve()}")

    print(
        "\nLectura correcta:\n"
        "- En cada fecha histórica, el modelo solo conoce cuotas con al "
        "menos cinco días de antigüedad.\n"
        "- Las cuotas recientes se estiman acumulando los retornos del "
        "modelo desde la última cuota visible.\n"
        "- Los calendarios se alinean con el último cierre disponible de "
        "cada ETF o índice.\n"
        "- La cuota real del día objetivo se usa únicamente para evaluar.\n"
        "- Este módulo reemplaza operativamente las simulaciones 53, 54 y "
        "la auditoría 55; esos módulos quedan como diagnósticos."
    )


if __name__ == "__main__":
    main()
