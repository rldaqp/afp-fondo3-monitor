from __future__ import annotations

from pathlib import Path
import numpy as np
import pandas as pd


UMBRAL_ANOMALIA = 5.0
UMBRAL_MOVIMIENTO_RELEVANTE = 2.0
DESVIO_AISLADO = 3.0


def clasificar_fecha(tabla_fecha: pd.DataFrame) -> str:
    """
    Clasifica la fecha según si el movimiento es generalizado o aislado.
    """
    retornos = tabla_fecha["variacion_porcentual"].dropna()

    if retornos.empty:
        return "sin_datos"

    mediana = retornos.median()
    signos = np.sign(retornos)
    mismo_signo = int((signos == np.sign(mediana)).sum()) if mediana != 0 else 0
    movimientos_relevantes = int(
        (retornos.abs() >= UMBRAL_MOVIMIENTO_RELEVANTE).sum()
    )
    anomalias = int((retornos.abs() >= UMBRAL_ANOMALIA).sum())

    if movimientos_relevantes >= 3 and mismo_signo >= 3:
        return "movimiento_generalizado"

    if anomalias == 1:
        fila_anomala = tabla_fecha.loc[
            tabla_fecha["variacion_porcentual"].abs().idxmax()
        ]
        desvio = abs(fila_anomala["variacion_porcentual"] - mediana)

        if desvio >= DESVIO_AISLADO:
            return "movimiento_aislado_revisar"

    return "movimiento_mixto"


def main() -> None:
    raiz = Path(__file__).resolve().parents[1]
    processed = raiz / "data" / "processed"

    ruta_base = processed / "sbs_fondo3_base_maestra.csv"
    if not ruta_base.exists():
        raise FileNotFoundError(
            f"No existe la base maestra: {ruta_base}"
        )

    base = pd.read_csv(ruta_base, parse_dates=["fecha"])
    base = base.sort_values(["fecha", "afp"]).reset_index(drop=True)

    fechas_anomalas = (
        base.loc[
            base["variacion_porcentual"].abs() >= UMBRAL_ANOMALIA,
            "fecha",
        ]
        .dropna()
        .drop_duplicates()
        .sort_values()
        .tolist()
    )

    if not fechas_anomalas:
        print("No se encontraron fechas anómalas.")
        return

    tablas = []
    resumen = []

    for fecha in fechas_anomalas:
        tabla = base[base["fecha"] == fecha][
            [
                "fecha",
                "afp",
                "valor_cuota",
                "variacion_porcentual",
                "fuente_tipo",
                "archivo_fuente",
            ]
        ].copy()

        clasificacion = clasificar_fecha(tabla)
        mediana = tabla["variacion_porcentual"].median()
        promedio = tabla["variacion_porcentual"].mean()
        dispersion = tabla["variacion_porcentual"].std(ddof=0)

        tabla["mediana_fecha_pct"] = mediana
        tabla["desvio_vs_mediana_pct"] = (
            tabla["variacion_porcentual"] - mediana
        )
        tabla["clasificacion_fecha"] = clasificacion
        tablas.append(tabla)

        resumen.append(
            {
                "fecha": fecha,
                "clasificacion": clasificacion,
                "promedio_pct": promedio,
                "mediana_pct": mediana,
                "dispersion_pct": dispersion,
                "afp_con_movimiento_mayor_5pct": int(
                    (tabla["variacion_porcentual"].abs() >= UMBRAL_ANOMALIA).sum()
                ),
                "afp_con_movimiento_mayor_2pct": int(
                    (
                        tabla["variacion_porcentual"].abs()
                        >= UMBRAL_MOVIMIENTO_RELEVANTE
                    ).sum()
                ),
                "max_abs_pct": tabla["variacion_porcentual"].abs().max(),
            }
        )

        print("=" * 92)
        print(
            f"Fecha: {fecha.date()} | "
            f"Clasificación: {clasificacion}"
        )
        print("-" * 92)
        print(
            tabla[
                [
                    "afp",
                    "valor_cuota",
                    "variacion_porcentual",
                    "desvio_vs_mediana_pct",
                ]
            ].to_string(index=False)
        )
        print()

    detalle = pd.concat(tablas, ignore_index=True)
    resumen_df = pd.DataFrame(resumen).sort_values("fecha")

    salida_detalle = (
        processed / "sbs_fondo3_comparacion_anomalias_por_afp.csv"
    )
    salida_resumen = (
        processed / "sbs_fondo3_clasificacion_anomalias.csv"
    )

    detalle.to_csv(
        salida_detalle,
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    resumen_df.to_csv(
        salida_resumen,
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )

    print("\nResumen de clasificación:")
    print(resumen_df.to_string(index=False))

    print("\nArchivos creados:")
    print(f" - {salida_detalle.resolve()}")
    print(f" - {salida_resumen.resolve()}")

    print(
        "\nCriterio práctico:\n"
        "- movimiento_generalizado: al menos 3 AFP se mueven con fuerza "
        "en la misma dirección; probablemente refleja mercado.\n"
        "- movimiento_aislado_revisar: una AFP se separa claramente de las "
        "demás; puede ser ajuste, cambio metodológico o dato atípico.\n"
        "- movimiento_mixto: no hay evidencia suficiente para clasificar."
    )


if __name__ == "__main__":
    main()
