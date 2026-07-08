from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats


AFPS = ["Habitat", "Integra", "Prima", "Profuturo"]


def leer_csv(ruta: Path) -> pd.DataFrame:
    return pd.read_csv(ruta, encoding="utf-8-sig")


def diebold_mariano(
    perdida_modelo: np.ndarray,
    perdida_referencia: np.ndarray,
    max_lag: int = 5,
) -> dict[str, float]:
    mascara = np.isfinite(perdida_modelo) & np.isfinite(perdida_referencia)
    d = (
        np.asarray(perdida_modelo, dtype=float)[mascara]
        - np.asarray(perdida_referencia, dtype=float)[mascara]
    )
    n = len(d)

    if n < 30:
        return {
            "n_dm": n,
            "diferencia_media_perdida": np.nan,
            "dm_estadistico": np.nan,
            "dm_pvalor": np.nan,
        }

    media = float(np.mean(d))
    centrado = d - media
    gamma0 = float(np.dot(centrado, centrado) / n)
    var_hac = gamma0

    for lag in range(1, min(max_lag, n - 1) + 1):
        gamma = float(np.dot(centrado[lag:], centrado[:-lag]) / n)
        peso = 1.0 - lag / (max_lag + 1.0)
        var_hac += 2.0 * peso * gamma

    var_media = var_hac / n

    if var_media <= 0:
        return {
            "n_dm": n,
            "diferencia_media_perdida": media,
            "dm_estadistico": np.nan,
            "dm_pvalor": np.nan,
        }

    estadistico = media / math.sqrt(var_media)
    pvalor = float(2.0 * (1.0 - stats.norm.cdf(abs(estadistico))))

    return {
        "n_dm": n,
        "diferencia_media_perdida": media,
        "dm_estadistico": float(estadistico),
        "dm_pvalor": pvalor,
    }


def main() -> None:
    raiz = Path(__file__).resolve().parents[1]
    processed = raiz / "data" / "processed"

    ruta_sim = processed / "ca0001_modelo65_simulacion_publicacion_5d.csv"
    ruta_diag = processed / "ca0001_modelo65_diagnosticos_residuales.csv"
    ruta_rank = processed / "ca0001_modelo65_ranking_prueba.csv"

    if not ruta_sim.exists():
        raise FileNotFoundError(f"No existe {ruta_sim}")

    sim = leer_csv(ruta_sim)
    sim["fecha_hoy_simulada"] = pd.to_datetime(
        sim["fecha_hoy_simulada"], errors="coerce"
    )
    sim["error_abs_pct"] = pd.to_numeric(
        sim["error_abs_pct"], errors="coerce"
    )

    filas = []

    for afp in AFPS:
        ref = sim[
            sim["afp"].eq(afp)
            & sim["modelo"].eq("RIDGE")
            & sim["segmento"].eq("prueba")
        ][["fecha_hoy_simulada", "error_abs_pct"]].rename(
            columns={"error_abs_pct": "perdida_referencia"}
        )

        for modelo in sim[
            sim["afp"].eq(afp)
            & sim["segmento"].eq("prueba")
        ]["modelo"].dropna().unique():
            cand = sim[
                sim["afp"].eq(afp)
                & sim["modelo"].eq(modelo)
                & sim["segmento"].eq("prueba")
            ][["fecha_hoy_simulada", "error_abs_pct"]].rename(
                columns={"error_abs_pct": "perdida_modelo"}
            )

            unido = cand.merge(
                ref,
                on="fecha_hoy_simulada",
                how="inner",
            ).dropna()

            resultado = diebold_mariano(
                unido["perdida_modelo"].to_numpy(),
                unido["perdida_referencia"].to_numpy(),
                max_lag=5,
            )

            filas.append(
                {
                    "afp": afp,
                    "modelo": modelo,
                    "referencia": "RIDGE",
                    **resultado,
                    "modelo_mejor_que_ridge": (
                        resultado["diferencia_media_perdida"] < 0
                        if pd.notna(resultado["diferencia_media_perdida"])
                        else False
                    ),
                    "diferencia_significativa_5pct": (
                        resultado["dm_pvalor"] < 0.05
                        if pd.notna(resultado["dm_pvalor"])
                        else False
                    ),
                }
            )

    dm = pd.DataFrame(filas)
    ruta_salida = (
        processed
        / "ca0001_modelo65_diebold_mariano_CORREGIDO.csv"
    )
    dm.to_csv(ruta_salida, index=False, encoding="utf-8-sig")

    print("\nMÓDULO 65B — DIEBOLD-MARIANO CORREGIDO")
    print("=" * 125)
    print(
        "Corrección: todas las fechas se convierten a datetime antes de "
        "cruzar cada modelo con Ridge."
    )

    print("\nCOMPARACIÓN DEL ERROR DE CUOTA CONTRA RIDGE")
    print("-" * 125)
    print(
        dm[
            [
                "afp",
                "modelo",
                "n_dm",
                "diferencia_media_perdida",
                "dm_estadistico",
                "dm_pvalor",
                "modelo_mejor_que_ridge",
                "diferencia_significativa_5pct",
            ]
        ]
        .sort_values(["afp", "dm_pvalor"], na_position="last")
        .to_string(index=False)
    )

    if ruta_rank.exists():
        ranking = leer_csv(ruta_rank)
        mejores = (
            ranking.sort_values(
                ["afp", "mape_cuota_5d_pct", "p90_error_abs_5d_pct"]
            )
            .groupby("afp", as_index=False)
            .first()
        )
        print("\nMEJOR MODELO POR MAPE EN PRUEBA")
        print("-" * 125)
        print(
            mejores[
                [
                    "afp",
                    "modelo",
                    "mape_cuota_5d_pct",
                    "p90_error_abs_5d_pct",
                    "direccion_acumulada_pct",
                ]
            ].to_string(index=False)
        )

    if ruta_diag.exists():
        diag = leer_csv(ruta_diag)
        print("\nDIAGNÓSTICOS RESIDUALES DE LOS MODELOS DINÁMICOS EN PRUEBA")
        print("-" * 125)
        print(
            diag[diag["segmento"].eq("prueba")]
            [
                [
                    "afp",
                    "modelo",
                    "ljungbox_p_lag10",
                    "arch_lm_p_lag10",
                    "asimetria_residual",
                    "curtosis_exceso_residual",
                ]
            ]
            .sort_values(["afp", "modelo"])
            .to_string(index=False)
        )

    print(f"\nArchivo creado:\n - {ruta_salida.resolve()}")
    print(
        "\nLECTURA:\n"
        "- diferencia_media_perdida < 0: el modelo tiene menor error que Ridge.\n"
        "- dm_pvalor < 0.05: la diferencia es estadísticamente significativa.\n"
        "- Un modelo debe cumplir ambas condiciones para afirmar que supera "
        "a Ridge con evidencia estadística."
    )


if __name__ == "__main__":
    main()
