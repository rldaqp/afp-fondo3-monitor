from __future__ import annotations

import json
import math
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from scipy import stats
from sklearn.feature_selection import mutual_info_regression

from statsmodels.graphics.tsaplots import plot_acf, plot_pacf
from statsmodels.stats.diagnostic import acorr_ljungbox, het_arch
from statsmodels.stats.outliers_influence import variance_inflation_factor
from statsmodels.tsa.stattools import adfuller, kpss


warnings.filterwarnings("ignore")

AFPS = ["Habitat", "Integra", "Prima", "Profuturo"]
LAGS = [0, 1, 2, 3]
VENTANAS = [120, 250]
RANDOM_STATE = 42


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


def cargar_division(processed: Path) -> tuple[pd.Timestamp, pd.Timestamp]:
    ruta = processed / "ca0001_modelo50_division_temporal.csv"
    if not ruta.exists():
        raise FileNotFoundError(
            "No existe ca0001_modelo50_division_temporal.csv."
        )

    df = leer_csv_flexible(ruta)
    df["fecha_inicio"] = pd.to_datetime(df["fecha_inicio"], errors="coerce")
    df["fecha_fin"] = pd.to_datetime(df["fecha_fin"], errors="coerce")

    train = df[df["segmento"].astype(str).eq("entrenamiento_descubrimiento")]
    valid = df[df["segmento"].astype(str).eq("validacion")]

    if train.empty or valid.empty:
        raise ValueError(
            "No se encontraron los segmentos de entrenamiento y validación."
        )

    return pd.Timestamp(train["fecha_fin"].iloc[0]), pd.Timestamp(valid["fecha_fin"].iloc[0])


def cargar_canasta(processed: Path) -> pd.DataFrame:
    ruta = processed / "ca0001_modelo51_canasta_depurada.csv"
    if not ruta.exists():
        raise FileNotFoundError("No existe ca0001_modelo51_canasta_depurada.csv.")

    df = leer_csv_flexible(ruta)

    if not {"afp", "factor"}.issubset(df.columns):
        raise ValueError("La canasta debe contener las columnas afp y factor.")

    if "orden" not in df.columns:
        df["orden"] = df.groupby("afp").cumcount() + 1

    return (
        df.dropna(subset=["afp", "factor"])
        .sort_values(["afp", "orden"])
        .drop_duplicates(["afp", "factor"])
        .reset_index(drop=True)
    )


def cargar_base(processed: Path) -> pd.DataFrame:
    ruta = processed / "ca0001_modelo56_base_alineada.csv"
    if not ruta.exists():
        raise FileNotFoundError(
            "No existe ca0001_modelo56_base_alineada.csv. "
            "Ejecute primero el módulo 56."
        )

    df = leer_csv_flexible(ruta)
    df["fecha_cuota"] = pd.to_datetime(df["fecha_cuota"], errors="coerce")
    df["cuota_sbs"] = pd.to_numeric(df["cuota_sbs"], errors="coerce")
    df["retorno_cuota"] = pd.to_numeric(df["retorno_cuota"], errors="coerce")

    return (
        df.dropna(subset=["fecha_cuota", "afp", "cuota_sbs"])
        .sort_values(["afp", "fecha_cuota"])
        .reset_index(drop=True)
    )


def correlacion_segura(x: pd.Series, y: pd.Series, metodo: str) -> float:
    datos = pd.concat([x, y], axis=1).dropna()
    if len(datos) < 10:
        return np.nan
    if datos.iloc[:, 0].nunique() < 2 or datos.iloc[:, 1].nunique() < 2:
        return np.nan
    return float(datos.iloc[:, 0].corr(datos.iloc[:, 1], method=metodo))


def mutual_info_segura(x: pd.Series, y: pd.Series) -> float:
    datos = pd.concat([x, y], axis=1).dropna()
    if len(datos) < 30:
        return np.nan
    X = datos.iloc[:, [0]].to_numpy()
    target = datos.iloc[:, 1].to_numpy()
    valor = mutual_info_regression(
        X,
        target,
        random_state=RANDOM_STATE,
        discrete_features=False,
    )
    return float(valor[0])


def prueba_adf(serie: pd.Series) -> dict[str, float]:
    s = serie.dropna()
    if len(s) < 30 or s.nunique() < 2:
        return {"adf_estadistico": np.nan, "adf_pvalor": np.nan}
    resultado = adfuller(s, autolag="AIC")
    return {
        "adf_estadistico": float(resultado[0]),
        "adf_pvalor": float(resultado[1]),
    }


def prueba_kpss(serie: pd.Series) -> dict[str, float]:
    s = serie.dropna()
    if len(s) < 30 or s.nunique() < 2:
        return {"kpss_estadistico": np.nan, "kpss_pvalor": np.nan}
    try:
        resultado = kpss(s, regression="c", nlags="auto")
        return {
            "kpss_estadistico": float(resultado[0]),
            "kpss_pvalor": float(resultado[1]),
        }
    except Exception:
        return {"kpss_estadistico": np.nan, "kpss_pvalor": np.nan}


def pruebas_temporales(serie: pd.Series) -> dict[str, float]:
    s = serie.dropna()
    resultado: dict[str, float] = {}

    resultado.update(prueba_adf(s))
    resultado.update(prueba_kpss(s))

    if len(s) >= 40:
        lb = acorr_ljungbox(s, lags=[5, 10, 20], return_df=True)
        for lag in [5, 10, 20]:
            resultado[f"ljungbox_pvalor_lag{lag}"] = float(lb.loc[lag, "lb_pvalue"])
    else:
        for lag in [5, 10, 20]:
            resultado[f"ljungbox_pvalor_lag{lag}"] = np.nan

    if len(s) >= 50:
        try:
            arch = het_arch(s, nlags=10)
            resultado["arch_lm_estadistico"] = float(arch[0])
            resultado["arch_lm_pvalor"] = float(arch[1])
        except Exception:
            resultado["arch_lm_estadistico"] = np.nan
            resultado["arch_lm_pvalor"] = np.nan
    else:
        resultado["arch_lm_estadistico"] = np.nan
        resultado["arch_lm_pvalor"] = np.nan

    resultado["media"] = float(s.mean()) if len(s) else np.nan
    resultado["desviacion"] = float(s.std(ddof=1)) if len(s) > 1 else np.nan
    resultado["asimetria"] = float(stats.skew(s, bias=False)) if len(s) > 2 else np.nan
    resultado["curtosis_exceso"] = float(stats.kurtosis(s, fisher=True, bias=False)) if len(s) > 3 else np.nan

    if len(s) > 5 and s.std(ddof=1) > 0:
        z = (s - s.mean()) / s.std(ddof=1)
        resultado["outliers_abs_z_mayor_3_pct"] = float((z.abs() > 3).mean() * 100.0)
    else:
        resultado["outliers_abs_z_mayor_3_pct"] = np.nan

    return resultado


def calcular_vif(df_factores: pd.DataFrame, afp: str) -> pd.DataFrame:
    datos = df_factores.dropna().copy()

    if datos.empty:
        return pd.DataFrame()

    columnas_validas = [c for c in datos.columns if datos[c].nunique() > 1]
    datos = datos[columnas_validas]

    if len(columnas_validas) == 1:
        return pd.DataFrame(
            {
                "afp": [afp],
                "factor_columna": columnas_validas,
                "vif": [1.0],
            }
        )

    matriz = datos.to_numpy(dtype=float)
    filas = []

    for i, columna in enumerate(columnas_validas):
        try:
            valor = float(variance_inflation_factor(matriz, i))
        except Exception:
            valor = np.nan
        filas.append(
            {
                "afp": afp,
                "factor_columna": columna,
                "vif": valor,
            }
        )

    return pd.DataFrame(filas)


def beta_movil(y: pd.Series, x: pd.Series, ventana: int) -> pd.Series:
    cov = y.rolling(ventana).cov(x)
    var = x.rolling(ventana).var()
    return cov / var.replace(0, np.nan)


def guardar_figura(ruta: Path) -> None:
    plt.tight_layout()
    plt.savefig(ruta, dpi=160, bbox_inches="tight")
    plt.close()


def grafico_heatmap_correlaciones(
    correlaciones: pd.DataFrame,
    graficos: Path,
) -> None:
    pivote = correlaciones.pivot_table(
        index="factor",
        columns="afp",
        values="spearman_train_lag0",
        aggfunc="first",
    ).reindex(columns=AFPS)

    if pivote.empty:
        return

    plt.figure(figsize=(8, max(4, len(pivote) * 0.7)))
    imagen = plt.imshow(pivote.to_numpy(), aspect="auto", vmin=-1, vmax=1)
    plt.colorbar(imagen, label="Spearman")
    plt.xticks(range(len(pivote.columns)), pivote.columns)
    plt.yticks(range(len(pivote.index)), pivote.index)
    plt.title("Correlación de Spearman en el 60 % de entrenamiento")

    for i in range(len(pivote.index)):
        for j in range(len(pivote.columns)):
            valor = pivote.iloc[i, j]
            if pd.notna(valor):
                plt.text(j, i, f"{valor:.2f}", ha="center", va="center")

    guardar_figura(graficos / "01_heatmap_correlaciones_spearman_train.png")


def grafico_base100(
    bloque: pd.DataFrame,
    factores: list[str],
    afp: str,
    fin_train: pd.Timestamp,
    fin_valid: pd.Timestamp,
    graficos: Path,
) -> None:
    datos = bloque.dropna(subset=["fecha_cuota", "cuota_sbs"]).copy()
    if datos.empty:
        return

    plt.figure(figsize=(12, 6))
    base_cuota = datos["cuota_sbs"].iloc[0]
    plt.plot(
        datos["fecha_cuota"],
        100.0 * datos["cuota_sbs"] / base_cuota,
        label=f"{afp} Fondo 3",
    )

    for factor in factores:
        columna = f"{factor}__retorno_alineado"
        if columna not in datos.columns:
            continue
        retorno = pd.to_numeric(datos[columna], errors="coerce").fillna(0.0)
        indice = 100.0 * (1.0 + retorno).cumprod()
        plt.plot(datos["fecha_cuota"], indice, label=factor)

    plt.axvline(fin_train, linestyle="--", label="Fin 60 %")
    plt.axvline(fin_valid, linestyle=":", label="Fin validación")
    plt.title(f"Trayectorias normalizadas base 100 — {afp}")
    plt.xlabel("Fecha")
    plt.ylabel("Índice base 100")
    plt.legend()
    guardar_figura(graficos / f"02_base100_{afp.lower()}.png")


def grafico_lags(
    corr_afp: pd.DataFrame,
    afp: str,
    graficos: Path,
) -> None:
    if corr_afp.empty:
        return

    plt.figure(figsize=(9, 5))
    for factor, grupo in corr_afp.groupby("factor"):
        grupo = grupo.sort_values("lag")
        plt.plot(grupo["lag"], grupo["spearman_train"], marker="o", label=factor)

    plt.axhline(0, linewidth=1)
    plt.xticks(LAGS)
    plt.xlabel("Rezago del factor (días)")
    plt.ylabel("Correlación de Spearman")
    plt.title(f"Correlación por rezago — {afp} — 60 % entrenamiento")
    plt.legend()
    guardar_figura(graficos / f"03_correlacion_rezagos_{afp.lower()}.png")


def grafico_distribucion(
    serie: pd.Series,
    afp: str,
    graficos: Path,
) -> None:
    s = serie.dropna()
    if s.empty:
        return

    plt.figure(figsize=(8, 5))
    plt.hist(s, bins=50)
    plt.axvline(s.mean(), linestyle="--", label="Media")
    plt.axvline(s.median(), linestyle=":", label="Mediana")
    plt.title(f"Distribución de retornos — {afp} — 60 % entrenamiento")
    plt.xlabel("Retorno diario")
    plt.ylabel("Frecuencia")
    plt.legend()
    guardar_figura(graficos / f"04_histograma_retornos_{afp.lower()}.png")

    plt.figure(figsize=(7, 6))
    stats.probplot(s, dist="norm", plot=plt)
    plt.title(f"Gráfico Q-Q de retornos — {afp} — 60 % entrenamiento")
    guardar_figura(graficos / f"05_qq_retornos_{afp.lower()}.png")


def grafico_acf_pacf(
    serie: pd.Series,
    afp: str,
    graficos: Path,
) -> None:
    s = serie.dropna()
    if len(s) < 50:
        return

    plt.figure(figsize=(9, 5))
    plot_acf(s, lags=30, zero=False, ax=plt.gca())
    plt.title(f"ACF de retornos — {afp} — 60 % entrenamiento")
    guardar_figura(graficos / f"06_acf_{afp.lower()}.png")

    plt.figure(figsize=(9, 5))
    plot_pacf(s, lags=30, zero=False, method="ywm", ax=plt.gca())
    plt.title(f"PACF de retornos — {afp} — 60 % entrenamiento")
    guardar_figura(graficos / f"07_pacf_{afp.lower()}.png")


def grafico_scatter(
    x: pd.Series,
    y: pd.Series,
    afp: str,
    factor: str,
    spearman: float,
    pearson: float,
    graficos: Path,
) -> None:
    datos = pd.concat([x, y], axis=1).dropna()
    if len(datos) < 20:
        return

    xx = datos.iloc[:, 0].to_numpy()
    yy = datos.iloc[:, 1].to_numpy()

    plt.figure(figsize=(7, 6))
    plt.scatter(xx, yy, alpha=0.45)

    if np.std(xx) > 0:
        pendiente, intercepto = np.polyfit(xx, yy, 1)
        orden = np.argsort(xx)
        plt.plot(xx[orden], intercepto + pendiente * xx[orden])

    plt.axhline(0, linewidth=1)
    plt.axvline(0, linewidth=1)
    plt.xlabel(f"Retorno {factor}")
    plt.ylabel(f"Retorno {afp} Fondo 3")
    plt.title(
        f"{factor} vs {afp} — 60 % entrenamiento\n"
        f"Spearman={spearman:.3f} | Pearson={pearson:.3f}"
    )
    guardar_figura(
        graficos / f"08_scatter_{afp.lower()}_{factor.replace('ret_', '').lower()}.png"
    )


def grafico_rolling(
    fechas: pd.Series,
    corr120: pd.Series,
    corr250: pd.Series,
    beta120: pd.Series,
    beta250: pd.Series,
    afp: str,
    factor: str,
    fin_train: pd.Timestamp,
    graficos: Path,
) -> None:
    nombre = factor.replace("ret_", "").lower()

    plt.figure(figsize=(11, 5))
    plt.plot(fechas, corr120, label="120 días")
    plt.plot(fechas, corr250, label="250 días")
    plt.axhline(0, linewidth=1)
    plt.axvline(fin_train, linestyle="--", label="Fin 60 %")
    plt.ylim(-1.05, 1.05)
    plt.xlabel("Fecha")
    plt.ylabel("Correlación móvil")
    plt.title(f"Correlación móvil — {factor} vs {afp}")
    plt.legend()
    guardar_figura(graficos / f"09_corr_movil_{afp.lower()}_{nombre}.png")

    plt.figure(figsize=(11, 5))
    plt.plot(fechas, beta120, label="120 días")
    plt.plot(fechas, beta250, label="250 días")
    plt.axhline(0, linewidth=1)
    plt.axvline(fin_train, linestyle="--", label="Fin 60 %")
    plt.xlabel("Fecha")
    plt.ylabel("Beta móvil")
    plt.title(f"Beta móvil — {factor} vs {afp}")
    plt.legend()
    guardar_figura(graficos / f"10_beta_movil_{afp.lower()}_{nombre}.png")


def main() -> None:
    raiz = Path(__file__).resolve().parents[1]
    processed = raiz / "data" / "processed"
    graficos = processed / "graficos_modelo62"
    graficos.mkdir(parents=True, exist_ok=True)

    fin_train, fin_valid = cargar_division(processed)
    canasta = cargar_canasta(processed)
    base = cargar_base(processed)

    correlaciones_lag = []
    correlaciones_resumen = []
    diagnosticos = []
    vif_todos = []
    rolling_todos = []
    recomendaciones = []

    for afp in AFPS:
        factores = (
            canasta[canasta["afp"].eq(afp)]
            .sort_values("orden")["factor"]
            .astype(str)
            .tolist()
        )
        columnas = [f"{factor}__retorno_alineado" for factor in factores]

        faltantes = [c for c in columnas if c not in base.columns]
        if faltantes:
            raise ValueError(f"Faltan columnas para {afp}: {', '.join(faltantes)}")

        bloque = (
            base[base["afp"].eq(afp)]
            [["fecha_cuota", "cuota_sbs", "retorno_cuota"] + columnas]
            .sort_values("fecha_cuota")
            .reset_index(drop=True)
        )

        train = bloque[bloque["fecha_cuota"].le(fin_train)].copy()

        diagnostico_afp = {
            "afp": afp,
            "fecha_inicio_train": train["fecha_cuota"].min(),
            "fecha_fin_train": train["fecha_cuota"].max(),
            "n_train": int(train["retorno_cuota"].notna().sum()),
            **pruebas_temporales(train["retorno_cuota"]),
        }
        diagnosticos.append(diagnostico_afp)

        vif = calcular_vif(train[columnas], afp)
        if not vif.empty:
            vif["factor"] = vif["factor_columna"].str.replace(
                "__retorno_alineado", "", regex=False
            )
            vif_todos.append(vif)

        for factor, columna in zip(factores, columnas):
            for lag in LAGS:
                factor_lag = train[columna].shift(lag)
                spearman = correlacion_segura(factor_lag, train["retorno_cuota"], "spearman")
                pearson = correlacion_segura(factor_lag, train["retorno_cuota"], "pearson")

                correlaciones_lag.append(
                    {
                        "afp": afp,
                        "factor": factor,
                        "lag": lag,
                        "spearman_train": spearman,
                        "pearson_train": pearson,
                        "n_train": int(
                            pd.concat([factor_lag, train["retorno_cuota"]], axis=1)
                            .dropna()
                            .shape[0]
                        ),
                    }
                )

            x0 = train[columna]
            y0 = train["retorno_cuota"]
            spearman0 = correlacion_segura(x0, y0, "spearman")
            pearson0 = correlacion_segura(x0, y0, "pearson")
            mi0 = mutual_info_segura(x0, y0)

            tabla_factor = pd.DataFrame(
                [
                    fila
                    for fila in correlaciones_lag
                    if fila["afp"] == afp and fila["factor"] == factor
                ]
            )
            fila_mejor = tabla_factor.iloc[
                tabla_factor["spearman_train"].abs().argmax()
            ]

            datos_factor = pd.concat([x0, y0], axis=1).dropna()
            vol_factor = float(datos_factor.iloc[:, 0].std(ddof=1))
            vol_afp = float(datos_factor.iloc[:, 1].std(ddof=1))
            ratio_amplitud = vol_afp / vol_factor if vol_factor > 0 else np.nan
            beta = (
                float(datos_factor.iloc[:, 1].cov(datos_factor.iloc[:, 0]))
                / float(datos_factor.iloc[:, 0].var(ddof=1))
                if datos_factor.iloc[:, 0].var(ddof=1) > 0
                else np.nan
            )

            correlaciones_resumen.append(
                {
                    "afp": afp,
                    "factor": factor,
                    "spearman_train_lag0": spearman0,
                    "pearson_train_lag0": pearson0,
                    "informacion_mutua_train_lag0": mi0,
                    "mejor_lag_spearman_train": int(fila_mejor["lag"]),
                    "mejor_spearman_train": float(fila_mejor["spearman_train"]),
                    "pearson_en_mejor_lag": float(fila_mejor["pearson_train"]),
                    "volatilidad_factor": vol_factor,
                    "volatilidad_afp": vol_afp,
                    "ratio_amplitud_afp_factor": ratio_amplitud,
                    "beta_estatica_train": beta,
                    "n_train": len(datos_factor),
                }
            )

            corr120 = bloque["retorno_cuota"].rolling(120).corr(bloque[columna])
            corr250 = bloque["retorno_cuota"].rolling(250).corr(bloque[columna])
            beta120 = beta_movil(bloque["retorno_cuota"], bloque[columna], 120)
            beta250 = beta_movil(bloque["retorno_cuota"], bloque[columna], 250)

            rolling_todos.append(
                pd.DataFrame(
                    {
                        "fecha_cuota": bloque["fecha_cuota"],
                        "afp": afp,
                        "factor": factor,
                        "corr_120": corr120,
                        "corr_250": corr250,
                        "beta_120": beta120,
                        "beta_250": beta250,
                    }
                )
            )

            grafico_scatter(
                x0,
                y0,
                afp,
                factor,
                spearman0,
                pearson0,
                graficos,
            )
            grafico_rolling(
                bloque["fecha_cuota"],
                corr120,
                corr250,
                beta120,
                beta250,
                afp,
                factor,
                fin_train,
                graficos,
            )

        grafico_base100(bloque, factores, afp, fin_train, fin_valid, graficos)
        grafico_distribucion(train["retorno_cuota"], afp, graficos)
        grafico_acf_pacf(train["retorno_cuota"], afp, graficos)

    corr_lag_df = pd.DataFrame(correlaciones_lag)
    corr_resumen_df = pd.DataFrame(correlaciones_resumen)
    diagnosticos_df = pd.DataFrame(diagnosticos)
    vif_df = pd.concat(vif_todos, ignore_index=True) if vif_todos else pd.DataFrame()
    rolling_df = pd.concat(rolling_todos, ignore_index=True) if rolling_todos else pd.DataFrame()

    grafico_heatmap_correlaciones(corr_resumen_df, graficos)

    for afp in AFPS:
        grafico_lags(corr_lag_df[corr_lag_df["afp"].eq(afp)], afp, graficos)

    for afp in AFPS:
        d = diagnosticos_df[diagnosticos_df["afp"].eq(afp)].iloc[0]
        vif_afp = vif_df[vif_df["afp"].eq(afp)] if not vif_df.empty else pd.DataFrame()
        corr_afp = corr_resumen_df[corr_resumen_df["afp"].eq(afp)]

        razones = []
        modelos = ["Ridge", "Huber"]

        max_vif = float(vif_afp["vif"].replace([np.inf, -np.inf], np.nan).max()) if not vif_afp.empty else np.nan
        if pd.notna(max_vif) and max_vif >= 5:
            modelos.extend(["ElasticNet"])
            razones.append(f"multicolinealidad relevante (VIF máximo {max_vif:.2f})")

        lb10 = d.get("ljungbox_pvalor_lag10", np.nan)
        if pd.notna(lb10) and lb10 < 0.05:
            modelos.extend(["ARDL", "ARIMAX"])
            razones.append(f"autocorrelación temporal (Ljung-Box lag 10 p={lb10:.4f})")

        arch_p = d.get("arch_lm_pvalor", np.nan)
        if pd.notna(arch_p) and arch_p < 0.05:
            modelos.extend(["GARCH", "RegresionCuantil"])
            razones.append(f"heterocedasticidad/volatilidad agrupada (ARCH-LM p={arch_p:.4f})")

        outliers = d.get("outliers_abs_z_mayor_3_pct", np.nan)
        curtosis = d.get("curtosis_exceso", np.nan)
        if (
            (pd.notna(outliers) and outliers > 0.5)
            or (pd.notna(curtosis) and curtosis > 3)
        ):
            modelos.extend(["Huber", "LAD", "RegresionCuantil"])
            razones.append(
                f"colas y extremos (outliers {outliers:.2f} %, curtosis exceso {curtosis:.2f})"
            )

        if not corr_afp.empty:
            brecha_no_lineal = (
                corr_afp["informacion_mutua_train_lag0"].rank(pct=True)
                - corr_afp["pearson_train_lag0"].abs().rank(pct=True)
            ).max()
            if pd.notna(brecha_no_lineal) and brecha_no_lineal > 0.25:
                modelos.extend(["GAM", "SVR", "GradientBoosting"])
                razones.append("indicios de relación no lineal")

        rolling_afp = rolling_df[
            rolling_df["afp"].eq(afp)
            & rolling_df["fecha_cuota"].le(fin_train)
        ]
        if not rolling_afp.empty:
            dispersion_corr = float(
                rolling_afp.groupby("factor")["corr_250"].std().mean()
            )
            if pd.notna(dispersion_corr) and dispersion_corr > 0.15:
                modelos.extend(["Kalman", "VentanaMovil"])
                razones.append(
                    f"correlaciones cambiantes en el tiempo (dispersión media {dispersion_corr:.3f})"
                )
        else:
            dispersion_corr = np.nan

        modelos = list(dict.fromkeys(modelos))
        recomendaciones.append(
            {
                "afp": afp,
                "modelos_candidatos_sugeridos": " | ".join(modelos),
                "razones": " | ".join(razones) if razones else "sin señales diagnósticas adicionales fuertes",
                "vif_maximo": max_vif,
                "ljungbox_pvalor_lag10": lb10,
                "arch_lm_pvalor": arch_p,
                "outliers_pct": outliers,
                "curtosis_exceso": curtosis,
                "dispersion_correlacion_movil_250": dispersion_corr,
            }
        )

    recomendaciones_df = pd.DataFrame(recomendaciones)

    rutas = {
        "correlaciones_lag": processed / "ca0001_modelo62_correlaciones_rezagadas_train.csv",
        "correlaciones_resumen": processed / "ca0001_modelo62_resumen_relaciones_train.csv",
        "diagnosticos": processed / "ca0001_modelo62_diagnostico_series_train.csv",
        "vif": processed / "ca0001_modelo62_vif_train.csv",
        "rolling": processed / "ca0001_modelo62_correlacion_beta_moviles.csv",
        "recomendaciones": processed / "ca0001_modelo62_modelos_sugeridos.csv",
        "resumen_json": processed / "ca0001_modelo62_resumen.json",
    }

    corr_lag_df.to_csv(rutas["correlaciones_lag"], index=False, encoding="utf-8-sig")
    corr_resumen_df.to_csv(rutas["correlaciones_resumen"], index=False, encoding="utf-8-sig")
    diagnosticos_df.to_csv(rutas["diagnosticos"], index=False, encoding="utf-8-sig")
    vif_df.to_csv(rutas["vif"], index=False, encoding="utf-8-sig")
    rolling_df.to_csv(rutas["rolling"], index=False, encoding="utf-8-sig", date_format="%Y-%m-%d")
    recomendaciones_df.to_csv(rutas["recomendaciones"], index=False, encoding="utf-8-sig")

    resumen = {
        "version": "modelo62_diagnostico_series_y_ondas",
        "principio_metodologico": (
            "Los diagnósticos para sugerir modelos usan únicamente el 60 % "
            "de entrenamiento. Los gráficos de trayectoria pueden mostrar "
            "todo el histórico con líneas de separación temporal."
        ),
        "fecha_fin_train": str(fin_train.date()),
        "fecha_fin_validacion": str(fin_valid.date()),
        "afp": recomendaciones_df.to_dict(orient="records"),
        "graficos_generados": len(list(graficos.glob("*.png"))),
    }
    rutas["resumen_json"].write_text(
        json.dumps(resumen, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    print("\nMÓDULO 62 — DIAGNÓSTICO DE SERIES DE TIEMPO Y ONDAS")
    print("=" * 120)
    print(f"Entrenamiento analizado hasta: {fin_train.date()}")
    print(f"Carpeta de gráficos: {graficos.resolve()}")

    print("\nCORRELACIONES Y AMPLITUD — 60 % ENTRENAMIENTO")
    print("-" * 120)
    columnas_corr = [
        "afp",
        "factor",
        "spearman_train_lag0",
        "pearson_train_lag0",
        "informacion_mutua_train_lag0",
        "mejor_lag_spearman_train",
        "mejor_spearman_train",
        "ratio_amplitud_afp_factor",
        "beta_estatica_train",
    ]
    print(corr_resumen_df[columnas_corr].to_string(index=False))

    print("\nDIAGNÓSTICO TEMPORAL POR AFP")
    print("-" * 120)
    columnas_diag = [
        "afp",
        "adf_pvalor",
        "kpss_pvalor",
        "ljungbox_pvalor_lag10",
        "arch_lm_pvalor",
        "asimetria",
        "curtosis_exceso",
        "outliers_abs_z_mayor_3_pct",
    ]
    print(diagnosticos_df[columnas_diag].to_string(index=False))

    print("\nMODELOS SUGERIDOS POR LOS DIAGNÓSTICOS")
    print("-" * 120)
    print(
        recomendaciones_df[
            ["afp", "modelos_candidatos_sugeridos", "razones"]
        ].to_string(index=False)
    )

    print("\nARCHIVOS CREADOS")
    print("-" * 120)
    for ruta in rutas.values():
        print(f" - {ruta.resolve()}")
    print(f" - {graficos.resolve()}")

    print(
        "\nLECTURA CORRECTA:\n"
        "- Este módulo no entrena todavía modelos predictivos.\n"
        "- Pearson, Spearman, información mutua, ACF/PACF, VIF, ARCH y "
        "correlaciones móviles sirven para decidir qué familias deben competir.\n"
        "- Las métricas de rendimiento MAE, RMSE, R², MAPE, P90, sesgo y "
        "dirección se aplicarán después del entrenamiento bajo un cuadro común.\n"
        "- Los gráficos quedan guardados para el análisis visual y el informe."
    )


if __name__ == "__main__":
    main()
