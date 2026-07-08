from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt


AFPS = ["Habitat", "Integra", "Prima", "Profuturo"]


def leer_csv(ruta: Path) -> pd.DataFrame:
    ultimo = None

    for encoding in ["utf-8-sig", "latin-1"]:
        try:
            return pd.read_csv(ruta, encoding=encoding)
        except Exception as exc:
            ultimo = exc

    raise RuntimeError(f"No se pudo leer {ruta}: {ultimo}")


def direccion_pct(real: pd.Series, estimado: pd.Series) -> float:
    mascara = real.notna() & estimado.notna() & estimado.ne(0)

    if not mascara.any():
        return np.nan

    return float(
        (
            np.sign(real[mascara])
            == np.sign(estimado[mascara])
        ).mean()
        * 100.0
    )


def main() -> None:
    raiz = Path(__file__).resolve().parents[1]
    processed = raiz / "data" / "processed"
    graficos = processed / "graficos_modelo79a"

    graficos.mkdir(parents=True, exist_ok=True)

    ruta = (
        processed
        / "ca0001_modelo78_simulacion_publicacion_5d.csv"
    )

    df = leer_csv(ruta)

    df["fecha_hoy_simulada"] = pd.to_datetime(
        df["fecha_hoy_simulada"],
        errors="coerce",
    )

    podada = df[
        df["tipo_modelo"].astype(str).eq("CANASTA_PODADA")
    ].copy()

    filas = []

    for afp in AFPS:
        x = podada[
            podada["afp"].astype(str).eq(afp)
        ].dropna(
            subset=[
                "cuota_real_hoy",
                "cuota_estimada_hoy",
                "retorno_acumulado_real",
                "retorno_acumulado_estimado",
            ]
        ).sort_values("fecha_hoy_simulada")

        if x.empty:
            continue

        pearson_cuota = x[
            "cuota_real_hoy"
        ].corr(
            x["cuota_estimada_hoy"],
            method="pearson",
        )

        spearman_cuota = x[
            "cuota_real_hoy"
        ].corr(
            x["cuota_estimada_hoy"],
            method="spearman",
        )

        pearson_retorno = x[
            "retorno_acumulado_real"
        ].corr(
            x["retorno_acumulado_estimado"],
            method="pearson",
        )

        spearman_retorno = x[
            "retorno_acumulado_real"
        ].corr(
            x["retorno_acumulado_estimado"],
            method="spearman",
        )

        mape = float(
            x["error_abs_pct"].mean() * 100.0
        )

        dir_acum = direccion_pct(
            x["retorno_acumulado_real"],
            x["retorno_acumulado_estimado"],
        )

        filas.append(
            {
                "afp": afp,
                "n_observaciones": int(len(x)),
                "pearson_cuota_real_vs_estimada": float(
                    pearson_cuota
                ),
                "spearman_cuota_real_vs_estimada": float(
                    spearman_cuota
                ),
                "pearson_retorno_acumulado": float(
                    pearson_retorno
                ),
                "spearman_retorno_acumulado": float(
                    spearman_retorno
                ),
                "mape_cuota_pct": mape,
                "direccion_acumulada_pct": dir_acum,
            }
        )

        plt.figure(figsize=(12, 5))
        plt.plot(
            x["fecha_hoy_simulada"],
            x["cuota_real_hoy"],
            label="Cuota real SBS",
        )
        plt.plot(
            x["fecha_hoy_simulada"],
            x["cuota_estimada_hoy"],
            label="Cuota estimada",
        )
        plt.title(
            f"Prueba histórica final: real vs estimada — {afp}"
        )
        plt.xlabel("Fecha")
        plt.ylabel("Valor cuota")
        plt.legend()
        plt.tight_layout()
        plt.savefig(
            graficos
            / f"01_real_vs_estimada_{afp.lower()}.png",
            dpi=170,
            bbox_inches="tight",
        )
        plt.close()

        plt.figure(figsize=(6, 6))
        plt.scatter(
            x["retorno_acumulado_real"] * 100.0,
            x["retorno_acumulado_estimado"] * 100.0,
            alpha=0.6,
        )

        minimo = float(
            min(
                (x["retorno_acumulado_real"] * 100.0).min(),
                (x["retorno_acumulado_estimado"] * 100.0).min(),
            )
        )
        maximo = float(
            max(
                (x["retorno_acumulado_real"] * 100.0).max(),
                (x["retorno_acumulado_estimado"] * 100.0).max(),
            )
        )

        plt.plot(
            [minimo, maximo],
            [minimo, maximo],
            linestyle="--",
            label="Estimación perfecta",
        )
        plt.title(
            f"Retorno real vs estimado — {afp}"
        )
        plt.xlabel("Retorno acumulado real (%)")
        plt.ylabel("Retorno acumulado estimado (%)")
        plt.legend()
        plt.tight_layout()
        plt.savefig(
            graficos
            / f"02_scatter_retorno_{afp.lower()}.png",
            dpi=170,
            bbox_inches="tight",
        )
        plt.close()

    resumen = pd.DataFrame(filas)

    salida = (
        processed
        / "ca0001_modelo79a_correlaciones_finales.csv"
    )

    resumen.to_csv(
        salida,
        index=False,
        encoding="utf-8-sig",
    )

    print(
        "\nMÓDULO 79A — CORRELACIONES Y GRÁFICOS FINALES"
    )
    print("=" * 150)

    print(
        resumen.to_string(index=False)
    )

    print("\nARCHIVOS CREADOS")
    print("-" * 150)
    print(f" - {salida.resolve()}")
    print(f" - {graficos.resolve()}")

    print(
        "\nLECTURA:\n"
        "- Pearson mide qué tan alineados están los movimientos lineales.\n"
        "- Spearman mide si ambos suben y bajan en un orden parecido.\n"
        "- La correlación de cuota puede ser alta por la tendencia del nivel; "
        "la correlación de retornos es la prueba más exigente.\n"
        "- Los gráficos real vs estimada permiten ver dónde el modelo se separa."
    )


if __name__ == "__main__":
    main()
