from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Iterable

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


AFPS = ["Habitat", "Integra", "Prima", "Profuturo"]
ULTIMAS_CUOTAS_GRAFICO = 120
UMBRAL_DESACTUALIZADO_DIAS_HABILES = 3


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

    return (
        salida.dropna(subset=["fecha_cuota", "afp", "cuota_sbs"])
        .sort_values(["afp", "fecha_cuota"])
        .drop_duplicates(
            subset=["fecha_cuota", "afp"],
            keep="last",
        )
        .reset_index(drop=True)
    )


def cargar_resumen57(processed: Path) -> pd.DataFrame:
    ruta = processed / "ca0001_modelo57_resumen_actual.csv"

    if not ruta.exists():
        raise FileNotFoundError(
            "No existe ca0001_modelo57_resumen_actual.csv."
        )

    df = leer_csv_flexible(ruta)
    df["afp"] = df["afp"].map(normalizar_afp)

    for columna in [
        "fecha_ultima_cuota_oficial",
        "fecha_estimada_hasta",
    ]:
        df[columna] = pd.to_datetime(
            df[columna],
            errors="coerce",
        )

    numericas = [
        "cuota_ultima_oficial",
        "dias_estimados",
        "retorno_estimado_acumulado",
        "cuota_estimada_actual",
        "ratio_senal_rmse",
        "rmse_diario_referencia",
        "factores_total",
        "factores_con_dato_nuevo",
        "cobertura_factores_pct",
        "cobertura_promedio_periodo_pct",
    ]

    for columna in numericas:
        if columna in df.columns:
            df[columna] = pd.to_numeric(
                df[columna],
                errors="coerce",
            )

    for columna in [
        "estado_cobertura",
        "factores_actualizados",
        "factores_sin_actualizar",
    ]:
        if columna in df.columns:
            df[columna] = df[columna].fillna("").astype(str)

    return df


def cargar_estimaciones57(processed: Path) -> pd.DataFrame:
    ruta = processed / "ca0001_modelo57_estimaciones_pendientes.csv"

    if not ruta.exists():
        raise FileNotFoundError(
            "No existe ca0001_modelo57_estimaciones_pendientes.csv."
        )

    df = leer_csv_flexible(ruta)

    if df.empty:
        return df

    df["fecha_cuota"] = pd.to_datetime(
        df["fecha_cuota"],
        errors="coerce",
    )
    df["fecha_ultima_cuota_oficial"] = pd.to_datetime(
        df["fecha_ultima_cuota_oficial"],
        errors="coerce",
    )
    df["afp"] = df["afp"].map(normalizar_afp)

    for columna in [
        "cuota_ultima_oficial",
        "dias_desde_ultima_oficial",
        "retorno_estimado",
        "cuota_estimada",
        "factores_total",
        "factores_con_dato_nuevo",
        "cobertura_factores_pct",
    ]:
        df[columna] = pd.to_numeric(
            df[columna],
            errors="coerce",
        )

    return (
        df.dropna(subset=["fecha_cuota", "afp"])
        .sort_values(["afp", "fecha_cuota"])
        .reset_index(drop=True)
    )


def cargar_metricas56(processed: Path) -> pd.DataFrame:
    ruta = processed / "ca0001_modelo56_metricas.csv"

    if not ruta.exists():
        raise FileNotFoundError(
            "No existe ca0001_modelo56_metricas.csv."
        )

    df = leer_csv_flexible(ruta)
    df["afp"] = df["afp"].map(normalizar_afp)

    for columna in [
        "mape_cuota_pct",
        "mediana_error_abs_pct",
        "p90_error_abs_pct",
        "sesgo_medio_pct",
        "correlacion_retorno_acumulado",
        "direccion_correcta_pct",
    ]:
        if columna in df.columns:
            df[columna] = pd.to_numeric(
                df[columna],
                errors="coerce",
            )

    return df


def cargar_validacion58(processed: Path) -> pd.DataFrame:
    ruta = processed / "ca0001_modelo58_validacion_completa.csv"

    if not ruta.exists():
        return pd.DataFrame()

    df = leer_csv_flexible(ruta)

    if df.empty:
        return df

    df["afp"] = df["afp"].map(normalizar_afp)
    df["fecha_cuota"] = pd.to_datetime(
        df["fecha_cuota"],
        errors="coerce",
    )

    for columna in [
        "cuota_estimada",
        "cuota_sbs",
        "error_pct",
        "error_abs_pct",
    ]:
        if columna in df.columns:
            df[columna] = pd.to_numeric(
                df[columna],
                errors="coerce",
            )

    return df


def cargar_contribuciones57(processed: Path) -> pd.DataFrame:
    ruta = processed / "ca0001_modelo57_contribuciones.csv"

    if not ruta.exists():
        return pd.DataFrame()

    df = leer_csv_flexible(ruta)

    if df.empty:
        return df

    df["fecha_cuota"] = pd.to_datetime(
        df["fecha_cuota"],
        errors="coerce",
    )
    df["afp"] = df["afp"].map(normalizar_afp)
    df["contribucion_modelo"] = pd.to_numeric(
        df["contribucion_modelo"],
        errors="coerce",
    )

    return df.dropna(
        subset=["fecha_cuota", "afp", "factor", "contribucion_modelo"]
    )


def cargar_controles58(processed: Path) -> pd.DataFrame:
    ruta = processed / "ca0001_modelo58_controles.csv"

    if not ruta.exists():
        return pd.DataFrame()

    return leer_csv_flexible(ruta)


def dias_habiles_transcurridos(
    fecha_inicio: pd.Timestamp,
    fecha_fin: pd.Timestamp,
) -> int:
    inicio = pd.Timestamp(fecha_inicio).normalize()
    fin = pd.Timestamp(fecha_fin).normalize()

    if fin <= inicio:
        return 0

    return int(
        len(
            pd.bdate_range(
                inicio + pd.Timedelta(days=1),
                fin,
            )
        )
    )


def resumir_validacion(
    validacion: pd.DataFrame,
) -> pd.DataFrame:
    filas = []

    for afp in AFPS:
        if validacion.empty:
            bloque = pd.DataFrame()
        else:
            bloque = validacion[
                validacion["afp"].eq(afp)
            ].copy()

        validados = bloque[
            bloque.get(
                "estado_validacion",
                pd.Series(index=bloque.index, dtype=str),
            ).eq("VALIDADO")
        ]
        pendientes = bloque[
            bloque.get(
                "estado_validacion",
                pd.Series(index=bloque.index, dtype=str),
            ).eq("PENDIENTE")
        ]

        if validados.empty:
            filas.append(
                {
                    "afp": afp,
                    "pronosticos_validados": 0,
                    "pronosticos_pendientes_archivados": len(pendientes),
                    "fecha_ultima_validacion": pd.NaT,
                    "ultimo_error_validado_pct": np.nan,
                    "mape_validado_acumulado_pct": np.nan,
                    "estado_validacion": (
                        "SIN_VALIDACIONES_PROSPECTIVAS"
                    ),
                }
            )
        else:
            validados = validados.sort_values("fecha_cuota")
            ultima = validados.iloc[-1]

            filas.append(
                {
                    "afp": afp,
                    "pronosticos_validados": len(validados),
                    "pronosticos_pendientes_archivados": len(pendientes),
                    "fecha_ultima_validacion": ultima["fecha_cuota"],
                    "ultimo_error_validado_pct": float(
                        ultima["error_pct"] * 100.0
                    ),
                    "mape_validado_acumulado_pct": float(
                        validados["error_abs_pct"].mean() * 100.0
                    ),
                    "estado_validacion": "VALIDACION_EN_CURSO",
                }
            )

    return pd.DataFrame(filas)


def resumir_contribuciones(
    contribuciones: pd.DataFrame,
) -> pd.DataFrame:
    if contribuciones.empty:
        return pd.DataFrame()

    resumen = (
        contribuciones.groupby(
            ["afp", "factor"],
            as_index=False,
        )["contribucion_modelo"]
        .sum()
    )
    resumen["contribucion_acumulada_pp"] = (
        resumen["contribucion_modelo"] * 100.0
    )
    resumen["tipo"] = np.where(
        resumen["factor"].eq("intercepto"),
        "componente_base",
        "factor_mercado",
    )

    return resumen.sort_values(
        ["afp", "contribucion_modelo"],
        ascending=[True, False],
    ).reset_index(drop=True)


def construir_panel(
    resumen57: pd.DataFrame,
    metricas56: pd.DataFrame,
    resumen_validacion: pd.DataFrame,
    hoy: pd.Timestamp,
) -> pd.DataFrame:
    panel = (
        resumen57.merge(
            metricas56[
                [
                    "afp",
                    "mape_cuota_pct",
                    "mediana_error_abs_pct",
                    "p90_error_abs_pct",
                    "correlacion_retorno_acumulado",
                    "direccion_correcta_pct",
                ]
            ],
            on="afp",
            how="left",
            validate="one_to_one",
        )
        .merge(
            resumen_validacion,
            on="afp",
            how="left",
            validate="one_to_one",
        )
    )

    panel["retorno_estimado_acumulado_pct"] = (
        panel["retorno_estimado_acumulado"] * 100.0
    )

    p90 = panel["p90_error_abs_pct"] / 100.0
    panel["banda_orientativa_inferior"] = (
        panel["cuota_estimada_actual"] / (1.0 + p90)
    )
    panel["banda_orientativa_superior"] = (
        panel["cuota_estimada_actual"] / (1.0 - p90)
    )

    panel["dias_calendario_desde_ultima_cuota"] = (
        panel["fecha_estimada_hasta"]
        - panel["fecha_ultima_cuota_oficial"]
    ).dt.days

    panel["rezago_mercado_dias_habiles"] = panel[
        "fecha_estimada_hasta"
    ].map(
        lambda fecha: dias_habiles_transcurridos(
            fecha,
            hoy,
        )
        if pd.notna(fecha)
        else np.nan
    )

    def estado_datos(fila: pd.Series) -> str:
        if int(fila.get("dias_estimados", 0) or 0) == 0:
            return "SIN_EXTENSION_PENDIENTE"

        rezago = fila["rezago_mercado_dias_habiles"]

        if pd.isna(rezago):
            return "REVISAR_FECHAS"

        if rezago <= 1:
            return "DATOS_VIGENTES"

        if rezago <= UMBRAL_DESACTUALIZADO_DIAS_HABILES:
            return "ACTUALIZACION_RECOMENDADA"

        return "DATOS_DESACTUALIZADOS"

    panel["estado_datos"] = panel.apply(
        estado_datos,
        axis=1,
    )
    panel["fecha_generacion_panel"] = hoy

    columnas = [
        "afp",
        "fecha_ultima_cuota_oficial",
        "cuota_ultima_oficial",
        "fecha_estimada_hasta",
        "dias_estimados",
        "retorno_estimado_acumulado_pct",
        "cuota_estimada_actual",
        "banda_orientativa_inferior",
        "banda_orientativa_superior",
        "direccion",
        "intensidad",
        "ratio_senal_rmse",
        "factores",
        "factores_total",
        "factores_con_dato_nuevo",
        "cobertura_factores_pct",
        "cobertura_promedio_periodo_pct",
        "estado_cobertura",
        "factores_actualizados",
        "factores_sin_actualizar",
        "mape_cuota_pct",
        "mediana_error_abs_pct",
        "p90_error_abs_pct",
        "correlacion_retorno_acumulado",
        "direccion_correcta_pct",
        "pronosticos_validados",
        "pronosticos_pendientes_archivados",
        "fecha_ultima_validacion",
        "ultimo_error_validado_pct",
        "mape_validado_acumulado_pct",
        "estado_validacion",
        "dias_calendario_desde_ultima_cuota",
        "rezago_mercado_dias_habiles",
        "estado_datos",
        "fecha_generacion_panel",
    ]

    return panel[columnas].sort_values("afp").reset_index(drop=True)


def construir_alertas(
    panel: pd.DataFrame,
    controles58: pd.DataFrame,
) -> pd.DataFrame:
    alertas = []

    for _, fila in panel.iterrows():
        afp = fila["afp"]

        if fila["estado_datos"] == "DATOS_DESACTUALIZADOS":
            alertas.append(
                {
                    "afp": afp,
                    "nivel": "ALTA",
                    "tipo": "DATOS_DESACTUALIZADOS",
                    "detalle": (
                        f"El último mercado disponible tiene "
                        f"{int(fila['rezago_mercado_dias_habiles'])} "
                        f"días hábiles de rezago."
                    ),
                }
            )

        elif fila["estado_datos"] == "ACTUALIZACION_RECOMENDADA":
            alertas.append(
                {
                    "afp": afp,
                    "nivel": "MEDIA",
                    "tipo": "ACTUALIZAR_MERCADOS",
                    "detalle": (
                        f"El último mercado disponible tiene "
                        f"{int(fila['rezago_mercado_dias_habiles'])} "
                        f"días hábiles de rezago."
                    ),
                }
            )

        estado_cobertura = str(
            fila.get("estado_cobertura", "NO_INFORMADA")
        )

        if estado_cobertura == "PARCIAL":
            alertas.append(
                {
                    "afp": afp,
                    "nivel": "MEDIA",
                    "tipo": "COBERTURA_PARCIAL",
                    "detalle": (
                        f"La última fecha tiene cobertura de "
                        f"{float(fila['cobertura_factores_pct']):.1f} %. "
                        f"Factores actualizados: "
                        f"{fila.get('factores_actualizados', '') or 'ninguno'}."
                    ),
                }
            )
        elif estado_cobertura == "SIN_NUEVA_SENAL":
            alertas.append(
                {
                    "afp": afp,
                    "nivel": "INFORMATIVA",
                    "tipo": "SIN_NUEVA_SENAL_FACTORES",
                    "detalle": (
                        "Ningún factor de la canasta tuvo un nuevo cierre "
                        "en la última fecha; el retorno estimado proviene "
                        "principalmente del componente base del modelo."
                    ),
                }
            )

        if fila["estado_validacion"] == "SIN_VALIDACIONES_PROSPECTIVAS":
            alertas.append(
                {
                    "afp": afp,
                    "nivel": "INFORMATIVA",
                    "tipo": "SIN_VALIDACIONES_NUEVAS",
                    "detalle": (
                        "Las estimaciones están archivadas, pero la SBS "
                        "todavía no publicó cuotas coincidentes."
                    ),
                }
            )

        if fila["intensidad"] == "debil":
            alertas.append(
                {
                    "afp": afp,
                    "nivel": "INFORMATIVA",
                    "tipo": "SENAL_DEBIL",
                    "detalle": (
                        "La variación estimada es pequeña frente al "
                        "error histórico del modelo."
                    ),
                }
            )

    if not controles58.empty:
        revisar = controles58[
            ~controles58["estado"].astype(str).str.lower().isin(
                ["correcto", "no_aplica"]
            )
        ]

        for _, fila in revisar.iterrows():
            alertas.append(
                {
                    "afp": "SISTEMA",
                    "nivel": "ALTA",
                    "tipo": str(fila["control"]),
                    "detalle": str(fila.get("detalle", "")),
                }
            )

    if not alertas:
        return pd.DataFrame(
            columns=["afp", "nivel", "tipo", "detalle"]
        )

    return pd.DataFrame(alertas)


def crear_graficos(
    sbs: pd.DataFrame,
    estimaciones: pd.DataFrame,
    panel: pd.DataFrame,
    graficos_dir: Path,
) -> None:
    graficos_dir.mkdir(parents=True, exist_ok=True)

    for afp in AFPS:
        oficial = (
            sbs[sbs["afp"].eq(afp)]
            .sort_values("fecha_cuota")
            .tail(ULTIMAS_CUOTAS_GRAFICO)
        )
        estimada = (
            estimaciones[estimaciones["afp"].eq(afp)]
            .sort_values("fecha_cuota")
            .copy()
        )
        fila_panel = panel[panel["afp"].eq(afp)]

        if oficial.empty or fila_panel.empty:
            continue

        plt.figure(figsize=(12, 6))
        plt.plot(
            oficial["fecha_cuota"],
            oficial["cuota_sbs"],
            label="Cuota oficial SBS",
            linewidth=1.8,
        )

        if not estimada.empty:
            fecha_ancla = oficial["fecha_cuota"].iloc[-1]
            cuota_ancla = oficial["cuota_sbs"].iloc[-1]

            puente = pd.DataFrame(
                {
                    "fecha_cuota": [fecha_ancla],
                    "cuota_estimada": [cuota_ancla],
                }
            )
            curva = pd.concat(
                [
                    puente,
                    estimada[
                        ["fecha_cuota", "cuota_estimada"]
                    ],
                ],
                ignore_index=True,
            )

            p90 = (
                float(fila_panel["p90_error_abs_pct"].iloc[0])
                / 100.0
            )
            curva["banda_inferior"] = (
                curva["cuota_estimada"] / (1.0 + p90)
            )
            curva["banda_superior"] = (
                curva["cuota_estimada"] / (1.0 - p90)
            )

            plt.plot(
                curva["fecha_cuota"],
                curva["cuota_estimada"],
                linestyle="--",
                marker="o",
                label="Cuota estimada no publicada",
                linewidth=1.4,
            )
            plt.fill_between(
                curva["fecha_cuota"],
                curva["banda_inferior"],
                curva["banda_superior"],
                alpha=0.18,
                label="Banda histórica orientativa P90",
            )
            plt.axvline(
                fecha_ancla,
                linestyle=":",
                linewidth=1.0,
                label="Última cuota oficial",
            )

        cobertura = float(
            fila_panel["cobertura_factores_pct"].iloc[0]
        )
        estado_cobertura = str(
            fila_panel["estado_cobertura"].iloc[0]
        )
        plt.title(
            f"{afp} Fondo 3: panel operativo oficial y estimado\n"
            f"Cobertura de factores: {cobertura:.1f} % "
            f"({estado_cobertura})"
        )
        plt.xlabel("Fecha del valor cuota")
        plt.ylabel("Valor cuota")
        plt.legend()
        plt.grid(True, alpha=0.25)
        plt.tight_layout()
        plt.savefig(
            graficos_dir
            / f"modelo59_{afp.lower()}_panel_operativo.png",
            dpi=180,
        )
        plt.close()

    plt.figure(figsize=(10, 5))
    orden = panel.sort_values("retorno_estimado_acumulado_pct")
    plt.bar(
        orden["afp"],
        orden["retorno_estimado_acumulado_pct"],
    )
    plt.axhline(0.0, linewidth=1.0)
    plt.title(
        "Fondo 3: variación acumulada estimada desde la última cuota oficial"
    )
    plt.xlabel("AFP")
    plt.ylabel("Variación estimada (%)")
    plt.tight_layout()
    plt.savefig(
        graficos_dir / "modelo59_comparacion_senal_afp.png",
        dpi=180,
    )
    plt.close()


def crear_reporte(
    panel: pd.DataFrame,
    contribuciones: pd.DataFrame,
    alertas: pd.DataFrame,
    ruta: Path,
) -> None:
    lineas = [
        "# Panel operativo del Fondo 3",
        "",
        (
            "El panel combina la última cuota oficial, las cuotas "
            "estimadas todavía no publicadas, el desempeño histórico "
            "del modelo y el estado de las validaciones prospectivas."
        ),
        "",
        (
            "La banda P90 es orientativa: se deriva del percentil 90 "
            "del error absoluto histórico observado en la simulación "
            "de publicación retrasada. No es un intervalo de confianza."
        ),
        "",
    ]

    for _, fila in panel.iterrows():
        afp = fila["afp"]

        lineas.extend(
            [
                f"## {afp}",
                "",
                (
                    f"- Última cuota oficial: "
                    f"{fila['cuota_ultima_oficial']:.6f} "
                    f"del {pd.Timestamp(fila['fecha_ultima_cuota_oficial']).date()}."
                ),
                (
                    f"- Cuota estimada: "
                    f"{fila['cuota_estimada_actual']:.6f} "
                    f"hasta {pd.Timestamp(fila['fecha_estimada_hasta']).date()}."
                ),
                (
                    f"- Variación acumulada estimada: "
                    f"{fila['retorno_estimado_acumulado_pct']:.3f} %."
                ),
                (
                    f"- Señal: {fila['direccion']} / "
                    f"{fila['intensidad']}."
                ),
                (
                    f"- Cobertura de factores: "
                    f"{fila['cobertura_factores_pct']:.1f} % "
                    f"({fila['estado_cobertura']})."
                ),
                (
                    f"- Factores actualizados: "
                    f"{fila['factores_actualizados'] or 'ninguno'}."
                ),
                (
                    f"- Factores sin nuevo cierre: "
                    f"{fila['factores_sin_actualizar'] or 'ninguno'}."
                ),
                (
                    f"- Banda histórica orientativa P90: "
                    f"{fila['banda_orientativa_inferior']:.6f} a "
                    f"{fila['banda_orientativa_superior']:.6f}."
                ),
                (
                    f"- Error histórico medio de cuota: "
                    f"{fila['mape_cuota_pct']:.3f} %; "
                    f"dirección acumulada correcta: "
                    f"{fila['direccion_correcta_pct']:.1f} %."
                ),
                (
                    f"- Validaciones prospectivas: "
                    f"{int(fila['pronosticos_validados'])} validadas y "
                    f"{int(fila['pronosticos_pendientes_archivados'])} pendientes."
                ),
                (
                    f"- Estado de datos: {fila['estado_datos']}."
                ),
                "",
            ]
        )

        contrib_afp = contribuciones[
            contribuciones["afp"].eq(afp)
        ]

        if not contrib_afp.empty:
            lineas.append("Contribución acumulada aproximada:")

            for _, contrib in contrib_afp.iterrows():
                lineas.append(
                    f"- {contrib['factor']}: "
                    f"{contrib['contribucion_acumulada_pp']:.3f} "
                    f"puntos porcentuales."
                )

            lineas.append("")

    lineas.extend(["## Alertas", ""])

    if alertas.empty:
        lineas.append("- No se identificaron alertas.")
    else:
        for _, alerta in alertas.iterrows():
            lineas.append(
                f"- [{alerta['nivel']}] {alerta['afp']} — "
                f"{alerta['tipo']}: {alerta['detalle']}"
            )

    lineas.extend(
        [
            "",
            "## Lectura correcta",
            "",
            (
                "La estimación muestra una aproximación provisional del "
                "valor cuota todavía no publicado. La señal de dirección "
                "es más confiable que el valor puntual y debe reemplazarse "
                "por la cuota oficial cuando la SBS la publique."
            ),
        ]
    )

    ruta.write_text("\n".join(lineas), encoding="utf-8")


def main() -> None:
    raiz = Path(__file__).resolve().parents[1]
    processed = raiz / "data" / "processed"
    graficos_dir = processed / "graficos_modelo59"
    hoy = pd.Timestamp.now().normalize()

    sbs = cargar_sbs(processed)
    resumen57 = cargar_resumen57(processed)
    estimaciones57 = cargar_estimaciones57(processed)
    metricas56 = cargar_metricas56(processed)
    validacion58 = cargar_validacion58(processed)
    contribuciones57 = cargar_contribuciones57(processed)
    controles58 = cargar_controles58(processed)

    resumen_validacion = resumir_validacion(validacion58)
    contribuciones = resumir_contribuciones(contribuciones57)
    panel = construir_panel(
        resumen57,
        metricas56,
        resumen_validacion,
        hoy,
    )
    alertas = construir_alertas(
        panel,
        controles58,
    )

    crear_graficos(
        sbs,
        estimaciones57,
        panel,
        graficos_dir,
    )

    rutas = {
        "panel": (
            processed
            / "ca0001_modelo59_panel_actual.csv"
        ),
        "contribuciones": (
            processed
            / "ca0001_modelo59_contribuciones_resumen.csv"
        ),
        "validacion": (
            processed
            / "ca0001_modelo59_resumen_validacion.csv"
        ),
        "alertas": (
            processed
            / "ca0001_modelo59_alertas.csv"
        ),
        "reporte": (
            processed
            / "ca0001_modelo59_reporte.md"
        ),
        "json": (
            processed
            / "ca0001_modelo59_resumen.json"
        ),
    }

    panel.to_csv(
        rutas["panel"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    contribuciones.to_csv(
        rutas["contribuciones"],
        index=False,
        encoding="utf-8-sig",
    )
    resumen_validacion.to_csv(
        rutas["validacion"],
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )
    alertas.to_csv(
        rutas["alertas"],
        index=False,
        encoding="utf-8-sig",
    )
    crear_reporte(
        panel,
        contribuciones,
        alertas,
        rutas["reporte"],
    )

    contenido = {
        "version": "modelo59_panel_operativo_cobertura_v2",
        "fecha_generacion": str(hoy.date()),
        "panel": panel.to_dict(orient="records"),
        "alertas": alertas.to_dict(orient="records"),
        "graficos": [
            ruta.name
            for ruta in sorted(graficos_dir.glob("*.png"))
        ],
        "nota": (
            "La banda P90 es una referencia basada en errores históricos. "
            "El panel también informa si la última fecha tiene cobertura "
            "completa, parcial o ninguna nueva señal de los factores."
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

    print("\nPANEL OPERATIVO DEL FONDO 3 TERMINADO")
    print("=" * 120)

    print("\nRESUMEN CONSOLIDADO")
    print("-" * 120)
    columnas_panel = [
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
        "banda_orientativa_inferior",
        "banda_orientativa_superior",
        "mape_cuota_pct",
        "direccion_correcta_pct",
        "pronosticos_validados",
        "pronosticos_pendientes_archivados",
        "estado_datos",
    ]
    print(panel[columnas_panel].to_string(index=False))

    print("\nCONTRIBUCIONES ACUMULADAS, INCLUYENDO COMPONENTE BASE")
    print("-" * 120)
    if contribuciones.empty:
        print("No existen contribuciones.")
    else:
        print(
            contribuciones[
                [
                    "afp",
                    "factor",
                    "tipo",
                    "contribucion_acumulada_pp",
                ]
            ].to_string(index=False)
        )

    print("\nALERTAS")
    print("-" * 120)
    if alertas.empty:
        print("No se identificaron alertas.")
    else:
        print(alertas.to_string(index=False))

    print("\nArchivos creados:")
    for ruta in rutas.values():
        print(f" - {ruta.resolve()}")
    print(f" - Carpeta de gráficos: {graficos_dir.resolve()}")

    print(
        "\nLectura correcta:\n"
        "- La cuota estimada es provisional.\n"
        "- La banda P90 refleja el error histórico del modelo, no una "
        "garantía estadística.\n"
        "- Las validaciones prospectivas comenzarán cuando la SBS publique "
        "las cuotas archivadas por el módulo 58.\n"
        "- La cobertura separa fechas completas, parciales y sin nueva señal.\n"
        "- Las contribuciones se expresan en la escala original del retorno.\n"
        "- Este panel consolida los módulos 56, 57 y 58 en una salida diaria."
    )


if __name__ == "__main__":
    main()
