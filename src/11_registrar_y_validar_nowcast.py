from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd


def cargar_o_vacio(ruta: Path) -> pd.DataFrame:
    if ruta.exists() and ruta.stat().st_size > 0:
        return pd.read_csv(
            ruta,
            parse_dates=[
                "fecha_registro",
                "fecha_ultima_oficial",
                "fecha_estimada",
            ],
        )
    return pd.DataFrame()


def archivar_nowcast(
    nowcast_actual: pd.DataFrame,
    ruta_historico: Path,
) -> pd.DataFrame:
    """
    Guarda de manera acumulativa cada estimación generada.
    Así no se pierden los nowcasts anteriores cuando el archivo operativo se actualiza.
    """
    captura = nowcast_actual.copy()
    captura["fecha_registro"] = pd.Timestamp.now()

    historico = cargar_o_vacio(ruta_historico)

    combinado = pd.concat(
        [historico, captura],
        ignore_index=True,
        sort=False,
    )

    clave = [
        "afp",
        "modelo",
        "fecha_ultima_oficial",
        "fecha_estimada",
        "valor_cuota_estimado",
    ]

    combinado = combinado.drop_duplicates(
        subset=[c for c in clave if c in combinado.columns],
        keep="first",
    )

    combinado = combinado.sort_values(
        ["fecha_registro", "afp", "fecha_estimada"]
    )

    combinado.to_csv(
        ruta_historico,
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d %H:%M:%S",
    )

    return combinado


def validar_estimaciones(
    historico_nowcast: pd.DataFrame,
    base_oficial: pd.DataFrame,
) -> pd.DataFrame:
    """
    Compara estimaciones ya archivadas con valores oficiales SBS
    cuando estos pasan a estar disponibles.
    """
    columnas_oficiales = [
        "fecha",
        "afp",
        "valor_cuota",
        "fuente_tipo",
    ]

    oficial = base_oficial[columnas_oficiales].copy()
    oficial = oficial.rename(
        columns={
            "fecha": "fecha_estimada",
            "valor_cuota": "valor_cuota_oficial",
            "fuente_tipo": "fuente_oficial",
        }
    )

    validacion = historico_nowcast.merge(
        oficial,
        on=["fecha_estimada", "afp"],
        how="left",
        validate="many_to_one",
    )

    validacion["estado_validacion"] = np.where(
        validacion["valor_cuota_oficial"].notna(),
        "validado",
        "pendiente",
    )

    validacion["error_valor"] = (
        validacion["valor_cuota_estimado"]
        - validacion["valor_cuota_oficial"]
    )

    validacion["error_absoluto"] = validacion["error_valor"].abs()

    validacion["error_pct"] = (
        validacion["error_valor"]
        / validacion["valor_cuota_oficial"]
        * 100
    )

    validacion["error_abs_pct"] = validacion["error_pct"].abs()

    validacion["retorno_real_acumulado_pct"] = (
        validacion["valor_cuota_oficial"]
        / validacion["valor_ultima_oficial"]
        - 1.0
    ) * 100

    validacion["direccion_estimada"] = np.sign(
        validacion["retorno_estimado_acumulado_pct"]
    )

    validacion["direccion_real"] = np.sign(
        validacion["retorno_real_acumulado_pct"]
    )

    validacion["acierto_direccion"] = np.where(
        validacion["estado_validacion"] == "validado",
        validacion["direccion_estimada"]
        == validacion["direccion_real"],
        np.nan,
    )

    if {
        "valor_estimado_bajo_80",
        "valor_estimado_alto_80",
    }.issubset(validacion.columns):
        validacion["dentro_intervalo_80"] = np.where(
            validacion["estado_validacion"] == "validado",
            (
                validacion["valor_cuota_oficial"]
                >= validacion["valor_estimado_bajo_80"]
            )
            & (
                validacion["valor_cuota_oficial"]
                <= validacion["valor_estimado_alto_80"]
            ),
            np.nan,
        )

    if {
        "valor_estimado_bajo_95",
        "valor_estimado_alto_95",
    }.issubset(validacion.columns):
        validacion["dentro_intervalo_95"] = np.where(
            validacion["estado_validacion"] == "validado",
            (
                validacion["valor_cuota_oficial"]
                >= validacion["valor_estimado_bajo_95"]
            )
            & (
                validacion["valor_cuota_oficial"]
                <= validacion["valor_estimado_alto_95"]
            ),
            np.nan,
        )

    return validacion


def resumir_validacion(validacion: pd.DataFrame) -> pd.DataFrame:
    validadas = validacion[
        validacion["estado_validacion"] == "validado"
    ].copy()

    if validadas.empty:
        return pd.DataFrame(
            columns=[
                "afp",
                "modelo",
                "observaciones_validadas",
                "mae_valor",
                "mape_pct",
                "sesgo_medio_pct",
                "acierto_direccion_pct",
                "cobertura_intervalo_80_pct",
                "cobertura_intervalo_95_pct",
            ]
        )

    filas = []

    for (afp, modelo), grupo in validadas.groupby(
        ["afp", "modelo"]
    ):
        fila = {
            "afp": afp,
            "modelo": modelo,
            "observaciones_validadas": len(grupo),
            "mae_valor": grupo["error_absoluto"].mean(),
            "mape_pct": grupo["error_abs_pct"].mean(),
            "sesgo_medio_pct": grupo["error_pct"].mean(),
            "acierto_direccion_pct": (
                pd.to_numeric(
                    grupo["acierto_direccion"],
                    errors="coerce",
                ).mean()
                * 100
            ),
        }

        if "dentro_intervalo_80" in grupo.columns:
            fila["cobertura_intervalo_80_pct"] = (
                pd.to_numeric(
                    grupo["dentro_intervalo_80"],
                    errors="coerce",
                ).mean()
                * 100
            )
        else:
            fila["cobertura_intervalo_80_pct"] = np.nan

        if "dentro_intervalo_95" in grupo.columns:
            fila["cobertura_intervalo_95_pct"] = (
                pd.to_numeric(
                    grupo["dentro_intervalo_95"],
                    errors="coerce",
                ).mean()
                * 100
            )
        else:
            fila["cobertura_intervalo_95_pct"] = np.nan

        filas.append(fila)

    return pd.DataFrame(filas).sort_values(["afp", "modelo"])


def main() -> None:
    raiz = Path(__file__).resolve().parents[1]
    processed = raiz / "data" / "processed"

    ruta_nowcast_actual = (
        processed / "nowcast_operativo_fondo3.csv"
    )
    ruta_base_oficial = (
        processed / "sbs_fondo3_base_maestra.csv"
    )
    ruta_historico = (
        processed / "nowcast_historico_estimaciones.csv"
    )
    ruta_validacion = (
        processed / "nowcast_validacion_detalle.csv"
    )
    ruta_resumen = (
        processed / "nowcast_validacion_resumen.csv"
    )

    if not ruta_nowcast_actual.exists():
        raise FileNotFoundError(
            f"No existe el nowcast operativo: {ruta_nowcast_actual}"
        )

    if not ruta_base_oficial.exists():
        raise FileNotFoundError(
            f"No existe la base oficial: {ruta_base_oficial}"
        )

    nowcast_actual = pd.read_csv(
        ruta_nowcast_actual,
        parse_dates=[
            "fecha_ultima_oficial",
            "fecha_estimada",
        ],
    )

    base_oficial = pd.read_csv(
        ruta_base_oficial,
        parse_dates=["fecha"],
    )

    historico = archivar_nowcast(
        nowcast_actual,
        ruta_historico,
    )

    validacion = validar_estimaciones(
        historico,
        base_oficial,
    )

    resumen = resumir_validacion(validacion)

    validacion.to_csv(
        ruta_validacion,
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d %H:%M:%S",
    )

    resumen.to_csv(
        ruta_resumen,
        index=False,
        encoding="utf-8-sig",
    )

    pendientes = (
        validacion["estado_validacion"] == "pendiente"
    ).sum()
    validadas = (
        validacion["estado_validacion"] == "validado"
    ).sum()

    print("\nREGISTRO Y VALIDACIÓN DEL NOWCAST")
    print("=" * 92)
    print(f"Estimaciones archivadas: {len(historico):,}")
    print(f"Estimaciones validadas: {validadas:,}")
    print(f"Estimaciones pendientes: {pendientes:,}")

    if validadas > 0:
        columnas = [
            "fecha_registro",
            "fecha_estimada",
            "afp",
            "modelo",
            "valor_cuota_estimado",
            "valor_cuota_oficial",
            "error_pct",
            "acierto_direccion",
        ]

        print("\nÚltimas estimaciones validadas:")
        print(
            validacion[
                validacion["estado_validacion"] == "validado"
            ]
            .sort_values(
                ["fecha_estimada", "afp"]
            )
            .tail(20)[columnas]
            .to_string(index=False)
        )

        print("\nResumen acumulado:")
        print(resumen.to_string(index=False))
    else:
        print(
            "\nTodavía no existen valores oficiales SBS para las fechas "
            "estimadas. Las predicciones quedaron archivadas y listas "
            "para validarse cuando se actualice la base maestra."
        )

    print("\nArchivos creados o actualizados:")
    print(f" - {ruta_historico.resolve()}")
    print(f" - {ruta_validacion.resolve()}")
    print(f" - {ruta_resumen.resolve()}")

    print(
        "\nSecuencia futura cuando la SBS publique nuevos datos:\n"
        "1. python src\\descargar_sbs_actual.py\n"
        "2. python src\\04_construir_base_maestra_fondo3.py\n"
        "3. python src\\11_registrar_y_validar_nowcast.py\n"
        "\nNo vuelvas a generar el nowcast antes de archivarlo, porque "
        "el archivo operativo puede reemplazarse."
    )


if __name__ == "__main__":
    main()
