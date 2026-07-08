from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats


AFPS = ["Habitat", "Integra", "Prima", "Profuturo"]


def leer_csv(ruta: Path) -> pd.DataFrame:
    intentos = [
        {"encoding": "utf-8-sig"},
        {"encoding": "latin-1"},
    ]
    ultimo = None
    for args in intentos:
        try:
            return pd.read_csv(ruta, **args)
        except Exception as exc:
            ultimo = exc
    raise RuntimeError(f"No se pudo leer {ruta}: {ultimo}")


def normalizar(df: pd.DataFrame) -> pd.DataFrame:
    x = df.copy()

    for col in ["afp", "modelo", "segmento"]:
        if col in x.columns:
            x[col] = x[col].astype(str).str.strip()

    if "fecha_hoy_simulada" in x.columns:
        x["fecha_hoy_simulada"] = (
            pd.to_datetime(x["fecha_hoy_simulada"], errors="coerce")
            .dt.normalize()
        )

    if "error_abs_pct" in x.columns:
        x["error_abs_pct"] = pd.to_numeric(
            x["error_abs_pct"], errors="coerce"
        )

    return x


def diebold_mariano(
    perdida_modelo: np.ndarray,
    perdida_referencia: np.ndarray,
    max_lag: int = 5,
) -> dict[str, float]:
    modelo = np.asarray(perdida_modelo, dtype=float)
    ref = np.asarray(perdida_referencia, dtype=float)

    mascara = np.isfinite(modelo) & np.isfinite(ref)
    d = modelo[mascara] - ref[mascara]
    n = len(d)

    if n < 30:
        return {
            "n_dm": int(n),
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
            "n_dm": int(n),
            "diferencia_media_perdida": media,
            "dm_estadistico": np.nan,
            "dm_pvalor": np.nan,
        }

    estadistico = media / math.sqrt(var_media)
    pvalor = float(
        2.0 * (1.0 - stats.norm.cdf(abs(estadistico)))
    )

    return {
        "n_dm": int(n),
        "diferencia_media_perdida": media,
        "dm_estadistico": float(estadistico),
        "dm_pvalor": pvalor,
    }


def main() -> None:
    raiz = Path(__file__).resolve().parents[1]
    processed = raiz / "data" / "processed"

    ruta_dinamicos = (
        processed
        / "ca0001_modelo65_simulacion_publicacion_5d.csv"
    )
    ruta_ridge = (
        processed
        / "ca0001_modelo64_simulacion_publicacion_5d.csv"
    )

    if not ruta_dinamicos.exists():
        raise FileNotFoundError(f"No existe {ruta_dinamicos}")
    if not ruta_ridge.exists():
        raise FileNotFoundError(f"No existe {ruta_ridge}")

    dinamicos = normalizar(leer_csv(ruta_dinamicos))
    ridge64 = normalizar(leer_csv(ruta_ridge))

    dinamicos = dinamicos[
        dinamicos["segmento"].eq("prueba")
        & ~dinamicos["modelo"].eq("RIDGE")
    ].copy()

    ridge64 = ridge64[
        ridge64["segmento"].eq("prueba")
        & ridge64["modelo"].eq("RIDGE")
    ].copy()

    modelos_dinamicos = (
        dinamicos[
            dinamicos["familia"].isin(
                ["ARIMAX", "EW_RIDGE", "ROLLING_RIDGE"]
            )
        ]["modelo"]
        .dropna()
        .unique()
        .tolist()
    )

    filas_control = []
    filas_dm = []

    for afp in AFPS:
        ref = (
            ridge64[ridge64["afp"].eq(afp)]
            [["fecha_hoy_simulada", "error_abs_pct"]]
            .dropna()
            .drop_duplicates("fecha_hoy_simulada", keep="last")
            .rename(
                columns={
                    "error_abs_pct": "perdida_referencia"
                }
            )
            .sort_values("fecha_hoy_simulada")
        )

        modelos_afp = (
            dinamicos[dinamicos["afp"].eq(afp)]["modelo"]
            .dropna()
            .unique()
            .tolist()
        )

        for modelo in modelos_afp:
            cand = (
                dinamicos[
                    dinamicos["afp"].eq(afp)
                    & dinamicos["modelo"].eq(modelo)
                ][["fecha_hoy_simulada", "error_abs_pct"]]
                .dropna()
                .drop_duplicates(
                    "fecha_hoy_simulada",
                    keep="last",
                )
                .rename(
                    columns={
                        "error_abs_pct": "perdida_modelo"
                    }
                )
                .sort_values("fecha_hoy_simulada")
            )

            unido = cand.merge(
                ref,
                on="fecha_hoy_simulada",
                how="inner",
                validate="one_to_one",
            )

            filas_control.append(
                {
                    "afp": afp,
                    "modelo": modelo,
                    "n_modelo": int(len(cand)),
                    "n_ridge": int(len(ref)),
                    "n_cruce": int(len(unido)),
                    "fecha_inicio_modelo": (
                        cand["fecha_hoy_simulada"].min()
                        if not cand.empty
                        else pd.NaT
                    ),
                    "fecha_fin_modelo": (
                        cand["fecha_hoy_simulada"].max()
                        if not cand.empty
                        else pd.NaT
                    ),
                    "fecha_inicio_ridge": (
                        ref["fecha_hoy_simulada"].min()
                        if not ref.empty
                        else pd.NaT
                    ),
                    "fecha_fin_ridge": (
                        ref["fecha_hoy_simulada"].max()
                        if not ref.empty
                        else pd.NaT
                    ),
                }
            )

            resultado = diebold_mariano(
                unido["perdida_modelo"].to_numpy(float),
                unido["perdida_referencia"].to_numpy(float),
                max_lag=5,
            )

            diferencia = resultado[
                "diferencia_media_perdida"
            ]
            pvalor = resultado["dm_pvalor"]

            filas_dm.append(
                {
                    "afp": afp,
                    "modelo": modelo,
                    "referencia": "RIDGE_MODELO64",
                    **resultado,
                    "modelo_mejor_que_ridge": (
                        bool(diferencia < 0)
                        if pd.notna(diferencia)
                        else False
                    ),
                    "diferencia_significativa_5pct": (
                        bool(pvalor < 0.05)
                        if pd.notna(pvalor)
                        else False
                    ),
                    "supera_ridge_con_evidencia": (
                        bool(
                            pd.notna(diferencia)
                            and pd.notna(pvalor)
                            and diferencia < 0
                            and pvalor < 0.05
                        )
                    ),
                }
            )

    control = pd.DataFrame(filas_control)
    dm = pd.DataFrame(filas_dm)

    ruta_control = (
        processed
        / "ca0001_modelo65C_control_cruce_fechas.csv"
    )
    ruta_dm = (
        processed
        / "ca0001_modelo65C_diebold_mariano_final.csv"
    )

    control.to_csv(
        ruta_control,
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    dm.to_csv(
        ruta_dm,
        index=False,
        encoding="utf-8-sig",
    )

    print("\nMÓDULO 65C — DIEBOLD-MARIANO FINAL")
    print("=" * 135)
    print(
        "La referencia Ridge se carga directamente desde el módulo 64. "
        "Los modelos dinámicos se cargan desde el módulo 65."
    )

    print("\nCONTROL DEL CRUCE DE FECHAS")
    print("-" * 135)
    print(
        control[
            [
                "afp",
                "modelo",
                "n_modelo",
                "n_ridge",
                "n_cruce",
                "fecha_inicio_modelo",
                "fecha_fin_modelo",
                "fecha_inicio_ridge",
                "fecha_fin_ridge",
            ]
        ].to_string(index=False)
    )

    print("\nDIEBOLD-MARIANO CONTRA RIDGE")
    print("-" * 135)
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
                "supera_ridge_con_evidencia",
            ]
        ]
        .sort_values(["afp", "dm_pvalor"], na_position="last")
        .to_string(index=False)
    )

    print("\nARCHIVOS CREADOS")
    print("-" * 135)
    print(f" - {ruta_control.resolve()}")
    print(f" - {ruta_dm.resolve()}")

    print(
        "\nLECTURA:\n"
        "- n_cruce debe ser cercano a 593.\n"
        "- diferencia_media_perdida < 0: menor error que Ridge.\n"
        "- dm_pvalor < 0.05: diferencia estadísticamente significativa.\n"
        "- supera_ridge_con_evidencia=True: cumple ambas condiciones."
    )


if __name__ == "__main__":
    main()
