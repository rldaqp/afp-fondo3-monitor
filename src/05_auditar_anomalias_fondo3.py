from __future__ import annotations

from pathlib import Path
import pandas as pd


UMBRAL_PCT = 5.0
VENTANA = 3


def main() -> None:
    raiz = Path(__file__).resolve().parents[1]
    processed = raiz / "data" / "processed"

    ruta_base = processed / "sbs_fondo3_base_maestra.csv"
    if not ruta_base.exists():
        raise FileNotFoundError(
            f"No existe la base maestra: {ruta_base}"
        )

    base = pd.read_csv(ruta_base, parse_dates=["fecha"])
    base = base.sort_values(["afp", "fecha"]).reset_index(drop=True)

    anomalías = base[
        base["variacion_porcentual"].abs() > UMBRAL_PCT
    ].copy()

    if anomalías.empty:
        print("No se encontraron variaciones superiores al umbral.")
        return

    detalles = []

    print(
        f"Se encontraron {len(anomalías)} variaciones "
        f"superiores a {UMBRAL_PCT:.1f} %.\n"
    )

    for _, fila in anomalías.iterrows():
        afp = fila["afp"]
        fecha = fila["fecha"]

        grupo = base[base["afp"] == afp].reset_index(drop=True)
        posiciones = grupo.index[grupo["fecha"] == fecha].tolist()

        if not posiciones:
            continue

        pos = posiciones[0]
        inicio = max(0, pos - VENTANA)
        fin = min(len(grupo), pos + VENTANA + 1)

        ventana = grupo.iloc[inicio:fin].copy()
        ventana["dias_desde_anterior"] = ventana["fecha"].diff().dt.days

        print("=" * 88)
        print(
            f"AFP: {afp} | Fecha anómala: {fecha.date()} | "
            f"Variación: {fila['variacion_porcentual']:.4f} %"
        )
        print("-" * 88)
        print(
            ventana[
                [
                    "fecha",
                    "valor_cuota",
                    "variacion_porcentual",
                    "dias_desde_anterior",
                    "fuente_tipo",
                    "archivo_fuente",
                ]
            ].to_string(index=False)
        )
        print()

        for registro in ventana.itertuples(index=False):
            detalles.append(
                {
                    "afp_objetivo": afp,
                    "fecha_anomala": fecha,
                    "variacion_anomala_pct": fila["variacion_porcentual"],
                    "fecha_contexto": registro.fecha,
                    "valor_cuota_contexto": registro.valor_cuota,
                    "variacion_contexto_pct": registro.variacion_porcentual,
                    "dias_desde_anterior": registro.dias_desde_anterior,
                    "fuente_tipo": registro.fuente_tipo,
                    "archivo_fuente": registro.archivo_fuente,
                }
            )

    salida = processed / "sbs_fondo3_anomalias_contexto.csv"
    pd.DataFrame(detalles).to_csv(
        salida,
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )

    print(f"Archivo de revisión creado:\n{salida.resolve()}")
    print(
        "\nInterpretación:\n"
        "- Si la variación ocurre después de varios días sin registro, puede "
        "ser un rendimiento acumulado y no un error.\n"
        "- Si el valor cuota salta y al día siguiente vuelve casi exactamente "
        "al nivel anterior, puede ser un dato atípico o una corrección.\n"
        "- Si las cuatro AFP muestran un movimiento parecido el mismo día, "
        "es más probable que sea un evento real de mercado."
    )


if __name__ == "__main__":
    main()
