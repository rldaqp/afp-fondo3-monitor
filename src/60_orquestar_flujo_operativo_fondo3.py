from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd


SCRIPTS = {
    "validar_previos": "58_archivar_y_validar_estimaciones_sbs.py",
    "generar_actuales": "57_generar_seguimiento_operativo_y_grafica_actual.py",
    "archivar_actuales": "58_archivar_y_validar_estimaciones_sbs.py",
    "generar_panel": "59_generar_panel_operativo_fondo3.py",
}

ARCHIVOS_REQUERIDOS = [
    "sbs_fondo3_base_maestra.csv",
    "mercados_factores_modelo.csv",
    "ca0001_modelo51_canasta_depurada.csv",
    "ca0001_modelo56_modelos.csv",
    "ca0001_modelo56_metricas.csv",
]


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


def validar_entorno(
    raiz: Path,
    src: Path,
    processed: Path,
) -> list[str]:
    errores = []

    for nombre in sorted(set(SCRIPTS.values())):
        ruta = src / nombre
        if not ruta.exists():
            errores.append(f"Falta el script: {ruta}")

    for nombre in ARCHIVOS_REQUERIDOS:
        ruta = processed / nombre
        if not ruta.exists():
            errores.append(f"Falta el archivo requerido: {ruta}")

    if not raiz.exists():
        errores.append(f"No existe la raíz del proyecto: {raiz}")

    return errores


def ejecutar_script(
    etiqueta: str,
    ruta_script: Path,
    raiz: Path,
    log_dir: Path,
) -> dict[str, object]:
    inicio = datetime.now()
    comando = [sys.executable, str(ruta_script)]

    proceso = subprocess.run(
        comando,
        cwd=raiz,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )

    fin = datetime.now()
    duracion = (fin - inicio).total_seconds()

    salida = proceso.stdout or ""
    error = proceso.stderr or ""

    ruta_log = log_dir / f"{etiqueta}.log"
    ruta_log.write_text(
        "\n".join(
            [
                f"ETIQUETA: {etiqueta}",
                f"INICIO: {inicio.isoformat()}",
                f"FIN: {fin.isoformat()}",
                f"DURACION_SEGUNDOS: {duracion:.3f}",
                f"CODIGO_RETORNO: {proceso.returncode}",
                "",
                "STDOUT",
                "=" * 100,
                salida,
                "",
                "STDERR",
                "=" * 100,
                error,
            ]
        ),
        encoding="utf-8",
    )

    return {
        "etiqueta": etiqueta,
        "script": ruta_script.name,
        "inicio": inicio.isoformat(),
        "fin": fin.isoformat(),
        "duracion_segundos": duracion,
        "codigo_retorno": proceso.returncode,
        "estado": "CORRECTO" if proceso.returncode == 0 else "ERROR",
        "ruta_log": str(ruta_log.resolve()),
        "stdout": salida,
        "stderr": error,
    }


def leer_resumen_final(processed: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    ruta_panel = processed / "ca0001_modelo59_panel_actual.csv"
    ruta_alertas = processed / "ca0001_modelo59_alertas.csv"

    panel = (
        leer_csv_flexible(ruta_panel)
        if ruta_panel.exists()
        else pd.DataFrame()
    )
    for columna in [
        "estado_cobertura",
        "factores_actualizados",
        "factores_sin_actualizar",
    ]:
        if columna in panel.columns:
            panel[columna] = panel[columna].fillna("").astype(str)
    alertas = (
        leer_csv_flexible(ruta_alertas)
        if ruta_alertas.exists()
        else pd.DataFrame()
    )

    return panel, alertas


def construir_estado(
    ejecuciones: list[dict[str, object]],
    panel: pd.DataFrame,
    alertas: pd.DataFrame,
    fecha_ejecucion: datetime,
) -> dict[str, object]:
    todo_correcto = all(
        ejecucion["estado"] == "CORRECTO"
        for ejecucion in ejecuciones
    )

    panel_resumen = []

    if not panel.empty:
        columnas = [
            columna
            for columna in [
                "afp",
                "fecha_ultima_cuota_oficial",
                "cuota_ultima_oficial",
                "fecha_estimada_hasta",
                "cuota_estimada_actual",
                "retorno_estimado_acumulado_pct",
                "direccion",
                "intensidad",
                "cobertura_factores_pct",
                "estado_cobertura",
                "factores_actualizados",
                "pronosticos_validados",
                "pronosticos_pendientes_archivados",
                "estado_datos",
            ]
            if columna in panel.columns
        ]
        panel_resumen = panel[columnas].to_dict(orient="records")

    alertas_resumen = (
        alertas.to_dict(orient="records")
        if not alertas.empty
        else []
    )

    return {
        "version": "modelo60_orquestador_operativo_cobertura_v2",
        "fecha_ejecucion": fecha_ejecucion.isoformat(),
        "estado_general": "CORRECTO" if todo_correcto else "ERROR",
        "ejecuciones": [
            {
                clave: valor
                for clave, valor in ejecucion.items()
                if clave not in {"stdout", "stderr"}
            }
            for ejecucion in ejecuciones
        ],
        "panel_resumen": panel_resumen,
        "alertas": alertas_resumen,
        "nota": (
            "Este orquestador no descarga datos. Debe ejecutarse después "
            "de actualizar las bases SBS y de mercados. El resumen "
            "incluye cobertura efectiva de factores."
        ),
    }


def imprimir_panel(panel: pd.DataFrame) -> None:
    print("\nPANEL FINAL")
    print("-" * 120)

    if panel.empty:
        print("No se encontró el panel del módulo 59.")
        return

    columnas = [
        columna
        for columna in [
            "afp",
            "fecha_ultima_cuota_oficial",
            "cuota_ultima_oficial",
            "fecha_estimada_hasta",
            "cuota_estimada_actual",
            "retorno_estimado_acumulado_pct",
            "direccion",
            "intensidad",
            "cobertura_factores_pct",
            "estado_cobertura",
            "factores_actualizados",
            "pronosticos_validados",
            "pronosticos_pendientes_archivados",
            "estado_datos",
        ]
        if columna in panel.columns
    ]

    print(panel[columnas].to_string(index=False))


def imprimir_alertas(alertas: pd.DataFrame) -> None:
    print("\nALERTAS FINALES")
    print("-" * 120)

    if alertas.empty:
        print("No se identificaron alertas.")
        return

    print(alertas.to_string(index=False))


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Ejecuta el flujo operativo correcto de validación, "
            "estimación, archivo y panel."
        )
    )
    parser.add_argument(
        "--omitir-validacion-previa",
        action="store_true",
        help=(
            "Omite la primera ejecución del módulo 58. "
            "Solo debe usarse en una instalación nueva sin pronósticos previos."
        ),
    )
    args = parser.parse_args()

    raiz = Path(__file__).resolve().parents[1]
    src = raiz / "src"
    processed = raiz / "data" / "processed"

    fecha_ejecucion = datetime.now()
    sello = fecha_ejecucion.strftime("%Y%m%d_%H%M%S")
    log_dir = processed / "logs_modelo60" / sello
    log_dir.mkdir(parents=True, exist_ok=True)

    errores = validar_entorno(raiz, src, processed)

    if errores:
        print("\nNO SE PUEDE EJECUTAR EL FLUJO")
        print("=" * 120)
        for error in errores:
            print(f"- {error}")
        raise SystemExit(1)

    pasos: list[tuple[str, str]] = []

    ruta_pronosticos = (
        processed
        / "ca0001_modelo57_estimaciones_pendientes.csv"
    )

    if (
        not args.omitir_validacion_previa
        and ruta_pronosticos.exists()
    ):
        pasos.append(
            ("01_validar_pronosticos_previos", SCRIPTS["validar_previos"])
        )

    pasos.extend(
        [
            ("02_generar_estimaciones_actuales", SCRIPTS["generar_actuales"]),
            ("03_archivar_estimaciones_actuales", SCRIPTS["archivar_actuales"]),
            ("04_generar_panel_operativo", SCRIPTS["generar_panel"]),
        ]
    )

    ejecuciones: list[dict[str, object]] = []

    print("\nORQUESTADOR OPERATIVO DEL FONDO 3")
    print("=" * 120)
    print(
        "Este flujo asume que las bases SBS y de mercados ya fueron actualizadas."
    )

    for etiqueta, nombre_script in pasos:
        print(f"\nEjecutando: {etiqueta}")
        resultado = ejecutar_script(
            etiqueta,
            src / nombre_script,
            raiz,
            log_dir,
        )
        ejecuciones.append(resultado)

        print(
            f"Estado: {resultado['estado']} | "
            f"duración: {resultado['duracion_segundos']:.2f} s"
        )

        if resultado["estado"] != "CORRECTO":
            print("\nEL FLUJO SE DETUVO POR ERROR")
            print("-" * 120)
            print(resultado["stderr"] or resultado["stdout"])
            break

    panel, alertas = leer_resumen_final(processed)
    estado = construir_estado(
        ejecuciones,
        panel,
        alertas,
        fecha_ejecucion,
    )

    ruta_estado = (
        processed
        / "ca0001_modelo60_estado_ultima_ejecucion.json"
    )
    ruta_estado.write_text(
        json.dumps(
            estado,
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )

    ruta_resumen = (
        processed
        / "ca0001_modelo60_resumen_ultima_ejecucion.csv"
    )

    if not panel.empty:
        panel.to_csv(
            ruta_resumen,
            index=False,
            encoding="utf-8-sig",
        )
    else:
        pd.DataFrame(
            [
                {
                    "estado_general": estado["estado_general"],
                    "fecha_ejecucion": fecha_ejecucion.isoformat(),
                }
            ]
        ).to_csv(
            ruta_resumen,
            index=False,
            encoding="utf-8-sig",
        )

    print("\nRESULTADO DEL FLUJO")
    print("=" * 120)
    print(f"Estado general: {estado['estado_general']}")
    print(f"Carpeta de logs: {log_dir.resolve()}")
    print(f"Estado JSON: {ruta_estado.resolve()}")
    print(f"Resumen CSV: {ruta_resumen.resolve()}")

    imprimir_panel(panel)
    imprimir_alertas(alertas)

    print(
        "\nORDEN AUTOMATIZADO:\n"
        "1. Valida pronósticos previos con las cuotas SBS nuevas.\n"
        "2. Genera estimaciones actuales desde la última cuota oficial.\n"
        "3. Archiva la nueva versión de los pronósticos.\n"
        "4. Regenera el panel operativo y las alertas.\n"
        "\nEl orquestador no descarga SBS ni precios de mercado."
    )

    if estado["estado_general"] != "CORRECTO":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
