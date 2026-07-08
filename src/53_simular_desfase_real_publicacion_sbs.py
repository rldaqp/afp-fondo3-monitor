from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Iterable

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error


AFPS = ["Habitat", "Integra", "Prima", "Profuturo"]
LAGS_SIMULADOS = [1, 2, 3, 4, 5]
LAGS_OBJETIVO = [4, 5]


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


def cargar_comparacion(processed: Path) -> pd.DataFrame:
    ruta = processed / "ca0001_modelo52_comparacion_cuota.csv"

    if not ruta.exists():
        raise FileNotFoundError(
            "No existe ca0001_modelo52_comparacion_cuota.csv. "
            "Primero ejecute el módulo 52."
        )

    df = leer_csv_flexible(ruta)

    fecha_col = detectar_columna(df.columns, {"fecha", "date"})
    afp_col = detectar_columna(df.columns, {"afp", "administradora"})
    cuota_col = detectar_columna(
        df.columns,
        {"cuota_sbs", "valor_cuota", "cuota_oficial"},
    )
    pred_col = detectar_columna(
        df.columns,
        {
            "retorno_estimado",
            "retorno_predicho",
            "prediccion",
            "y_pred",
        },
    )

    if None in [fecha_col, afp_col, cuota_col, pred_col]:
        raise ValueError(
            "No se identificaron fecha, AFP, cuota SBS y retorno estimado."
        )

    salida = pd.DataFrame(
        {
            "fecha": pd.to_datetime(df[fecha_col], errors="coerce"),
            "afp": df[afp_col].map(normalizar_afp),
            "cuota_sbs": pd.to_numeric(df[cuota_col], errors="coerce"),
            "retorno_estimado": pd.to_numeric(
                df[pred_col],
                errors="coerce",
            ),
        }
    )

    return (
        salida.dropna(
            subset=["fecha", "afp", "cuota_sbs", "retorno_estimado"]
        )
        .sort_values(["afp", "fecha"])
        .drop_duplicates(subset=["fecha", "afp"], keep="last")
        .reset_index(drop=True)
    )


def construir_simulacion(base: pd.DataFrame) -> pd.DataFrame:
    resultados = []

    for afp, bloque in base.groupby("afp", sort=False):
        bloque = bloque.sort_values("fecha").reset_index(drop=True).copy()
        gross = 1.0 + bloque["retorno_estimado"]

        for lag in LAGS_SIMULADOS:
            temporal = bloque.copy()
            temporal["lag_dias_observacion"] = lag
            temporal["fecha_ultima_cuota_conocida"] = temporal["fecha"].shift(lag)
            temporal["cuota_ultima_conocida"] = temporal["cuota_sbs"].shift(lag)

            producto_estimado = gross.rolling(
                window=lag,
                min_periods=lag,
            ).apply(np.prod, raw=True)

            temporal["retorno_estimado_acumulado"] = (
                producto_estimado - 1.0
            )
            temporal["cuota_estimada_desfase"] = (
                temporal["cuota_ultima_conocida"]
                * producto_estimado
            )
            temporal["retorno_real_acumulado"] = (
                temporal["cuota_sbs"]
                / temporal["cuota_ultima_conocida"]
                - 1.0
            )
            temporal["error_cuota"] = (
                temporal["cuota_estimada_desfase"]
                - temporal["cuota_sbs"]
            )
            temporal["error_pct"] = (
                temporal["error_cuota"]
                / temporal["cuota_sbs"]
            )
            temporal["error_abs_pct"] = temporal["error_pct"].abs()
            temporal["direccion_correcta"] = (
                np.sign(temporal["retorno_estimado_acumulado"])
                == np.sign(temporal["retorno_real_acumulado"])
            )

            resultados.append(temporal)

    return (
        pd.concat(resultados, ignore_index=True)
        .dropna(
            subset=[
                "cuota_ultima_conocida",
                "cuota_estimada_desfase",
                "retorno_real_acumulado",
            ]
        )
        .sort_values(["afp", "lag_dias_observacion", "fecha"])
        .reset_index(drop=True)
    )


def calcular_metricas(simulacion: pd.DataFrame) -> pd.DataFrame:
    filas = []

    for (afp, lag), bloque in simulacion.groupby(
        ["afp", "lag_dias_observacion"],
        sort=True,
    ):
        y_real = bloque["cuota_sbs"].to_numpy()
        y_est = bloque["cuota_estimada_desfase"].to_numpy()
        ret_real = bloque["retorno_real_acumulado"].to_numpy()
        ret_est = bloque["retorno_estimado_acumulado"].to_numpy()

        correlacion = pd.Series(ret_real).corr(pd.Series(ret_est))

        filas.append(
            {
                "afp": afp,
                "lag_dias_observacion": int(lag),
                "fecha_inicio": bloque["fecha"].min(),
                "fecha_fin": bloque["fecha"].max(),
                "observaciones": len(bloque),
                "mae_cuota": float(
                    mean_absolute_error(y_real, y_est)
                ),
                "rmse_cuota": float(
                    mean_squared_error(y_real, y_est) ** 0.5
                ),
                "mape_cuota_pct": float(
                    bloque["error_abs_pct"].mean() * 100.0
                ),
                "p90_error_abs_pct": float(
                    bloque["error_abs_pct"].quantile(0.90) * 100.0
                ),
                "sesgo_medio_pct": float(
                    bloque["error_pct"].mean() * 100.0
                ),
                "correlacion_retorno_acumulado": float(correlacion),
                "direccion_correcta_pct": float(
                    bloque["direccion_correcta"].mean() * 100.0
                ),
            }
        )

    return pd.DataFrame(filas)


def crear_resumen_objetivo(metricas: pd.DataFrame) -> pd.DataFrame:
    objetivo = metricas[
        metricas["lag_dias_observacion"].isin(LAGS_OBJETIVO)
    ].copy()

    if objetivo.empty:
        return objetivo

    objetivo["lectura"] = np.where(
        objetivo["mape_cuota_pct"] <= 1.0,
        "seguimiento_razonable",
        np.where(
            objetivo["mape_cuota_pct"] <= 2.0,
            "seguimiento_con_cautela",
            "error_elevado",
        ),
    )

    objetivo["ranking_mape_entre_4y5"] = (
        objetivo.groupby("afp")["mape_cuota_pct"]
        .rank(method="first", ascending=True)
        .astype(int)
    )

    return objetivo.sort_values(
        ["afp", "lag_dias_observacion"]
    ).reset_index(drop=True)


def graficar(
    simulacion: pd.DataFrame,
    graficos_dir: Path,
) -> None:
    graficos_dir.mkdir(parents=True, exist_ok=True)

    for afp in AFPS:
        for lag in LAGS_OBJETIVO:
            bloque = simulacion[
                simulacion["afp"].eq(afp)
                & simulacion["lag_dias_observacion"].eq(lag)
            ].copy()

            if bloque.empty:
                continue

            plt.figure(figsize=(12, 6))
            plt.plot(
                bloque["fecha"],
                bloque["cuota_sbs"],
                label="Valor cuota oficial SBS",
                linewidth=1.8,
            )
            plt.plot(
                bloque["fecha"],
                bloque["cuota_estimada_desfase"],
                label=f"Estimación con desfase de {lag} días",
                linewidth=1.2,
            )
            plt.title(
                f"{afp} Fondo 3: SBS vs estimación con desfase de {lag} días"
            )
            plt.xlabel("Fecha")
            plt.ylabel("Valor cuota")
            plt.legend()
            plt.grid(True, alpha=0.25)
            plt.tight_layout()
            plt.savefig(
                graficos_dir
                / f"modelo53_{afp.lower()}_desfase_{lag}d.png",
                dpi=180,
            )
            plt.close()

            plt.figure(figsize=(12, 5))
            plt.plot(
                bloque["fecha"],
                bloque["error_pct"] * 100.0,
                linewidth=1.0,
            )
            plt.axhline(0.0, linewidth=1.0)
            plt.title(
                f"{afp} Fondo 3: error con desfase de {lag} días"
            )
            plt.xlabel("Fecha")
            plt.ylabel("Error estimado - oficial (%)")
            plt.grid(True, alpha=0.25)
            plt.tight_layout()
            plt.savefig(
                graficos_dir
                / f"modelo53_{afp.lower()}_error_desfase_{lag}d.png",
                dpi=180,
            )
            plt.close()


def crear_reporte(
    resumen: pd.DataFrame,
    ruta: Path,
) -> None:
    lineas = [
        "# Simulación del desfase real de publicación",
        "",
        (
            "La estimación parte de la última cuota que habría estado "
            "disponible y acumula los retornos predichos de los siguientes "
            "4 o 5 días de observación."
        ),
        "",
        (
            "Los días se cuentan como observaciones consecutivas de la serie "
            "SBS/mercado, no como días calendario. Esto evita tratar fines de "
            "semana y feriados como sesiones con retorno."
        ),
        "",
    ]

    for afp in AFPS:
        lineas.extend([f"## {afp}", ""])
        bloque = resumen[resumen["afp"].eq(afp)]

        for _, fila in bloque.iterrows():
            lineas.append(
                f"- Desfase {int(fila['lag_dias_observacion'])} días: "
                f"MAPE={fila['mape_cuota_pct']:.3f} %, "
                f"error P90={fila['p90_error_abs_pct']:.3f} %, "
                f"dirección={fila['direccion_correcta_pct']:.1f} %, "
                f"correlación acumulada="
                f"{fila['correlacion_retorno_acumulado']:.3f}."
            )

        lineas.append("")

    lineas.extend(
        [
            "## Interpretación",
            "",
            (
                "Esta simulación es más cercana al uso real que una estimación "
                "de un solo día, porque reproduce el periodo durante el cual "
                "la SBS todavía no habría publicado las cuotas recientes."
            ),
            (
                "La estimación debe reanclarse cada vez que aparece una nueva "
                "cuota oficial. No debe acumularse indefinidamente."
            ),
        ]
    )

    ruta.write_text("\n".join(lineas), encoding="utf-8")


def main() -> None:
    raiz = Path(__file__).resolve().parents[1]
    processed = raiz / "data" / "processed"
    graficos_dir = processed / "graficos_modelo53"

    base = cargar_comparacion(processed)
    simulacion = construir_simulacion(base)
    metricas = calcular_metricas(simulacion)
    resumen = crear_resumen_objetivo(metricas)

    rutas = {
        "simulacion": (
            processed
            / "ca0001_modelo53_simulacion_desfase.csv"
        ),
        "metricas": (
            processed
            / "ca0001_modelo53_metricas_por_lag.csv"
        ),
        "resumen": (
            processed
            / "ca0001_modelo53_resumen_lag_4_5.csv"
        ),
        "reporte": (
            processed
            / "ca0001_modelo53_reporte.md"
        ),
        "json": (
            processed
            / "ca0001_modelo53_resumen.json"
        ),
    }

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
    resumen.to_csv(
        rutas["resumen"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    crear_reporte(resumen, rutas["reporte"])
    graficar(simulacion, graficos_dir)

    contenido = {
        "version": "modelo53_simulacion_desfase_real",
        "lags_simulados": LAGS_SIMULADOS,
        "lags_objetivo": LAGS_OBJETIVO,
        "resumen_4_5_dias": resumen.to_dict(orient="records"),
        "graficos": [
            ruta.name
            for ruta in sorted(graficos_dir.glob("*.png"))
        ],
        "nota": (
            "El ancla es la cuota oficial de L observaciones atrás. "
            "Los retornos estimados se acumulan hasta la fecha objetivo."
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

    print("\nSIMULACIÓN DEL DESFASE SBS TERMINADA")
    print("=" * 120)

    print("\nMÉTRICAS PARA 1 A 5 DÍAS DE DESFASE")
    print("-" * 120)
    print(metricas.to_string(index=False))

    print("\nRESULTADO CENTRAL: DESFASE DE 4 Y 5 DÍAS")
    print("-" * 120)
    print(resumen.to_string(index=False))

    print("\nÚLTIMA ESTIMACIÓN HISTÓRICA DE 4 Y 5 DÍAS")
    print("-" * 120)
    ultimas = (
        simulacion[
            simulacion["lag_dias_observacion"].isin(LAGS_OBJETIVO)
        ]
        .sort_values(["afp", "lag_dias_observacion", "fecha"])
        .groupby(["afp", "lag_dias_observacion"], as_index=False)
        .tail(1)
    )
    columnas = [
        "afp",
        "lag_dias_observacion",
        "fecha_ultima_cuota_conocida",
        "fecha",
        "cuota_ultima_conocida",
        "cuota_estimada_desfase",
        "cuota_sbs",
        "error_pct",
        "direccion_correcta",
    ]
    print(ultimas[columnas].to_string(index=False))

    print("\nArchivos creados:")
    for ruta in rutas.values():
        print(f" - {ruta.resolve()}")
    print(f" - Carpeta de gráficos: {graficos_dir.resolve()}")

    print(
        "\nLectura correcta:\n"
        "- El módulo 52 midió una estimación diaria reanclada.\n"
        "- Este módulo 53 simula el problema real: estar 4 o 5 "
        "observaciones por detrás.\n"
        "- La cuota estimada se obtiene acumulando todas las predicciones "
        "desde la última cuota conocida.\n"
        "- Cada nueva publicación SBS debe volver a anclar el cálculo."
    )


if __name__ == "__main__":
    main()
