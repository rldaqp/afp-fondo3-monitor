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


def cargar_cuotas_sbs(processed: Path) -> pd.DataFrame:
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
    valor_col = detectar_columna(
        df.columns,
        {"valor_cuota", "valor_de_la_cuota", "cuota", "valor"},
    )

    if fecha_col is None or afp_col is None or valor_col is None:
        raise ValueError(
            "La base SBS debe contener fecha, AFP y valor cuota."
        )

    base = pd.DataFrame(
        {
            "fecha": pd.to_datetime(df[fecha_col], errors="coerce"),
            "afp": df[afp_col].map(normalizar_afp),
            "cuota_sbs": pd.to_numeric(df[valor_col], errors="coerce"),
        }
    )

    base = (
        base.dropna(subset=["fecha", "afp", "cuota_sbs"])
        .sort_values(["afp", "fecha"])
        .drop_duplicates(subset=["fecha", "afp"], keep="last")
        .reset_index(drop=True)
    )

    base["cuota_sbs_anterior"] = (
        base.groupby("afp")["cuota_sbs"].shift(1)
    )
    base["retorno_real_calculado"] = (
        base["cuota_sbs"] / base["cuota_sbs_anterior"] - 1.0
    )
    base["fecha_anterior_sbs"] = (
        base.groupby("afp")["fecha"].shift(1)
    )

    return base


def cargar_predicciones(processed: Path) -> pd.DataFrame:
    ruta = processed / "ca0001_modelo51_predicciones_prueba.csv"

    if not ruta.exists():
        raise FileNotFoundError(
            "No existe el archivo de predicciones del módulo 51."
        )

    df = leer_csv_flexible(ruta)

    fecha_col = detectar_columna(df.columns, {"fecha", "date"})
    afp_col = detectar_columna(df.columns, {"afp", "administradora"})
    pred_col = detectar_columna(
        df.columns,
        {
            "retorno_estimado",
            "retorno_predicho",
            "prediccion",
            "y_pred",
        },
    )
    real_col = detectar_columna(
        df.columns,
        {
            "retorno_real",
            "y_real",
            "retorno_afp",
        },
    )

    if fecha_col is None or afp_col is None or pred_col is None:
        raise ValueError(
            "No se identificaron fecha, AFP y retorno estimado "
            "en las predicciones del módulo 51."
        )

    salida = pd.DataFrame(
        {
            "fecha": pd.to_datetime(df[fecha_col], errors="coerce"),
            "afp": df[afp_col].map(normalizar_afp),
            "retorno_estimado": pd.to_numeric(
                df[pred_col],
                errors="coerce",
            ),
        }
    )

    if real_col is not None:
        salida["retorno_real_archivo"] = pd.to_numeric(
            df[real_col],
            errors="coerce",
        )

    return (
        salida.dropna(subset=["fecha", "afp", "retorno_estimado"])
        .sort_values(["afp", "fecha"])
        .drop_duplicates(subset=["fecha", "afp"], keep="last")
        .reset_index(drop=True)
    )


def construir_comparacion(
    cuotas: pd.DataFrame,
    predicciones: pd.DataFrame,
) -> pd.DataFrame:
    base = predicciones.merge(
        cuotas[
            [
                "fecha",
                "afp",
                "cuota_sbs",
                "cuota_sbs_anterior",
                "retorno_real_calculado",
                "fecha_anterior_sbs",
            ]
        ],
        on=["fecha", "afp"],
        how="left",
        validate="one_to_one",
    )

    base["cuota_estimada_1d"] = (
        base["cuota_sbs_anterior"]
        * (1.0 + base["retorno_estimado"])
    )
    base["error_cuota_1d"] = (
        base["cuota_estimada_1d"] - base["cuota_sbs"]
    )
    base["error_abs_cuota_1d"] = base["error_cuota_1d"].abs()
    base["error_pct_cuota_1d"] = (
        base["error_cuota_1d"] / base["cuota_sbs"]
    )
    base["direccion_real"] = np.sign(
        base["retorno_real_calculado"]
    )
    base["direccion_estimada"] = np.sign(
        base["retorno_estimado"]
    )
    base["direccion_correcta"] = (
        base["direccion_real"] == base["direccion_estimada"]
    )

    acumulados = []

    for afp, bloque in base.groupby("afp", sort=False):
        bloque = bloque.sort_values("fecha").copy()

        validos = bloque.dropna(
            subset=[
                "cuota_sbs",
                "cuota_sbs_anterior",
                "retorno_estimado",
            ]
        )

        if validos.empty:
            acumulados.append(bloque)
            continue

        primera_fila = validos.iloc[0]
        ancla = float(primera_fila["cuota_sbs_anterior"])

        bloque["cuota_estimada_acumulada"] = (
            ancla
            * (1.0 + bloque["retorno_estimado"]).cumprod()
        )

        primera_cuota_real = float(primera_fila["cuota_sbs"])
        bloque["indice_sbs_base100"] = (
            bloque["cuota_sbs"] / primera_cuota_real * 100.0
        )
        primera_cuota_est = float(
            bloque.loc[
                bloque["fecha"].eq(primera_fila["fecha"]),
                "cuota_estimada_acumulada",
            ].iloc[0]
        )
        bloque["indice_estimado_base100"] = (
            bloque["cuota_estimada_acumulada"]
            / primera_cuota_est
            * 100.0
        )

        acumulados.append(bloque)

    return (
        pd.concat(acumulados, ignore_index=True)
        .sort_values(["afp", "fecha"])
        .reset_index(drop=True)
    )


def calcular_metricas(comparacion: pd.DataFrame) -> pd.DataFrame:
    filas = []

    for afp in AFPS:
        bloque = comparacion[
            comparacion["afp"].eq(afp)
        ].dropna(
            subset=[
                "cuota_sbs",
                "cuota_estimada_1d",
                "retorno_real_calculado",
                "retorno_estimado",
            ]
        )

        if bloque.empty:
            continue

        y_cuota = bloque["cuota_sbs"].to_numpy()
        y_cuota_est = bloque["cuota_estimada_1d"].to_numpy()
        y_ret = bloque["retorno_real_calculado"].to_numpy()
        y_ret_est = bloque["retorno_estimado"].to_numpy()

        mae_cuota = float(
            mean_absolute_error(y_cuota, y_cuota_est)
        )
        rmse_cuota = float(
            mean_squared_error(y_cuota, y_cuota_est) ** 0.5
        )
        mape_cuota = float(
            np.mean(
                np.abs(
                    (y_cuota_est - y_cuota) / y_cuota
                )
            )
            * 100.0
        )
        corr_retornos = float(
            pd.Series(y_ret).corr(pd.Series(y_ret_est))
        )
        direccion = float(
            (
                np.sign(y_ret)
                == np.sign(y_ret_est)
            ).mean()
            * 100.0
        )

        acumulado = comparacion[
            comparacion["afp"].eq(afp)
        ].dropna(
            subset=[
                "cuota_sbs",
                "cuota_estimada_acumulada",
            ]
        )

        if acumulado.empty:
            error_final_acumulado_pct = np.nan
        else:
            ultima = acumulado.iloc[-1]
            error_final_acumulado_pct = float(
                (
                    ultima["cuota_estimada_acumulada"]
                    / ultima["cuota_sbs"]
                    - 1.0
                )
                * 100.0
            )

        filas.append(
            {
                "afp": afp,
                "fecha_inicio": bloque["fecha"].min(),
                "fecha_fin": bloque["fecha"].max(),
                "observaciones": len(bloque),
                "mae_cuota_1d": mae_cuota,
                "rmse_cuota_1d": rmse_cuota,
                "mape_cuota_1d_pct": mape_cuota,
                "correlacion_retornos": corr_retornos,
                "direccion_correcta_pct": direccion,
                "error_final_acumulado_sin_reanclaje_pct": (
                    error_final_acumulado_pct
                ),
            }
        )

    return pd.DataFrame(filas)


def graficar_por_afp(
    comparacion: pd.DataFrame,
    graficos_dir: Path,
) -> None:
    graficos_dir.mkdir(parents=True, exist_ok=True)

    for afp in AFPS:
        bloque = comparacion[
            comparacion["afp"].eq(afp)
        ].dropna(
            subset=[
                "fecha",
                "cuota_sbs",
                "cuota_estimada_1d",
            ]
        )

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
            bloque["cuota_estimada_1d"],
            label="Valor cuota estimado (1 día, reanclado)",
            linewidth=1.2,
        )
        plt.title(
            f"{afp} Fondo 3: valor cuota SBS vs estimación diaria"
        )
        plt.xlabel("Fecha")
        plt.ylabel("Valor cuota")
        plt.legend()
        plt.grid(True, alpha=0.25)
        plt.tight_layout()
        plt.savefig(
            graficos_dir
            / f"modelo52_{afp.lower()}_sbs_vs_estimado_1d.png",
            dpi=180,
        )
        plt.close()

        acumulado = comparacion[
            comparacion["afp"].eq(afp)
        ].dropna(
            subset=[
                "fecha",
                "indice_sbs_base100",
                "indice_estimado_base100",
            ]
        )

        if acumulado.empty:
            continue

        plt.figure(figsize=(12, 6))
        plt.plot(
            acumulado["fecha"],
            acumulado["indice_sbs_base100"],
            label="SBS oficial (base 100)",
            linewidth=1.8,
        )
        plt.plot(
            acumulado["fecha"],
            acumulado["indice_estimado_base100"],
            label="Estimación acumulada sin reanclaje (base 100)",
            linewidth=1.2,
        )
        plt.title(
            f"{afp} Fondo 3: trayectoria acumulada oficial vs modelo"
        )
        plt.xlabel("Fecha")
        plt.ylabel("Índice base 100")
        plt.legend()
        plt.grid(True, alpha=0.25)
        plt.tight_layout()
        plt.savefig(
            graficos_dir
            / f"modelo52_{afp.lower()}_trayectoria_acumulada.png",
            dpi=180,
        )
        plt.close()

        errores = comparacion[
            comparacion["afp"].eq(afp)
        ].dropna(
            subset=[
                "fecha",
                "error_pct_cuota_1d",
            ]
        )

        if errores.empty:
            continue

        plt.figure(figsize=(12, 5))
        plt.plot(
            errores["fecha"],
            errores["error_pct_cuota_1d"] * 100.0,
            linewidth=1.0,
        )
        plt.axhline(0.0, linewidth=1.0)
        plt.title(
            f"{afp} Fondo 3: error porcentual de la estimación diaria"
        )
        plt.xlabel("Fecha")
        plt.ylabel("Error estimado - oficial (%)")
        plt.grid(True, alpha=0.25)
        plt.tight_layout()
        plt.savefig(
            graficos_dir
            / f"modelo52_{afp.lower()}_error_diario.png",
            dpi=180,
        )
        plt.close()


def crear_reporte_markdown(
    metricas: pd.DataFrame,
    ruta: Path,
) -> None:
    lineas = [
        "# Comparación del valor cuota SBS y el valor estimado",
        "",
        "## Dos lecturas distintas",
        "",
        (
            "1. **Estimación diaria reanclada:** usa el valor cuota oficial "
            "anterior y aplica el retorno estimado del modelo. Esta es la "
            "comparación más justa para medir la estimación diaria."
        ),
        (
            "2. **Trayectoria acumulada sin reanclaje:** parte de una sola "
            "cuota inicial y acumula todos los retornos estimados. Sirve para "
            "observar deriva y sesgo acumulado, pero no representa el uso "
            "operativo cuando la SBS publica nuevas cuotas."
        ),
        "",
        "## Métricas",
        "",
    ]

    for _, fila in metricas.iterrows():
        lineas.extend(
            [
                f"### {fila['afp']}",
                "",
                (
                    f"- Periodo: {pd.Timestamp(fila['fecha_inicio']).date()} "
                    f"a {pd.Timestamp(fila['fecha_fin']).date()}."
                ),
                f"- Observaciones: {int(fila['observaciones'])}.",
                (
                    f"- Error porcentual absoluto medio de cuota: "
                    f"{fila['mape_cuota_1d_pct']:.3f} %."
                ),
                (
                    f"- Correlación entre retornos reales y estimados: "
                    f"{fila['correlacion_retornos']:.3f}."
                ),
                (
                    f"- Dirección correcta: "
                    f"{fila['direccion_correcta_pct']:.1f} %."
                ),
                (
                    f"- Error acumulado final sin reanclaje: "
                    f"{fila['error_final_acumulado_sin_reanclaje_pct']:.2f} %."
                ),
                "",
            ]
        )

    lineas.extend(
        [
            "## Interpretación",
            "",
            (
                "La línea reanclada muestra qué valor cuota habría estimado "
                "el modelo para cada fecha usando como ancla la cuota oficial "
                "anterior. La línea acumulada revela cuánto se desvía el "
                "modelo cuando no recibe ninguna corrección oficial durante "
                "todo el periodo."
            ),
        ]
    )

    ruta.write_text(
        "\n".join(lineas),
        encoding="utf-8",
    )


def main() -> None:
    raiz = Path(__file__).resolve().parents[1]
    processed = raiz / "data" / "processed"
    graficos_dir = processed / "graficos_modelo52"

    cuotas = cargar_cuotas_sbs(processed)
    predicciones = cargar_predicciones(processed)
    comparacion = construir_comparacion(cuotas, predicciones)
    metricas = calcular_metricas(comparacion)

    rutas = {
        "comparacion": (
            processed
            / "ca0001_modelo52_comparacion_cuota.csv"
        ),
        "metricas": (
            processed
            / "ca0001_modelo52_metricas.csv"
        ),
        "reporte": (
            processed
            / "ca0001_modelo52_reporte.md"
        ),
        "json": (
            processed
            / "ca0001_modelo52_resumen.json"
        ),
    }

    comparacion.to_csv(
        rutas["comparacion"],
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
    crear_reporte_markdown(metricas, rutas["reporte"])

    resumen = {
        "version": "modelo52_sbs_vs_estimacion",
        "metricas": metricas.to_dict(orient="records"),
        "graficos": [
            str(ruta.name)
            for ruta in sorted(graficos_dir.glob("*.png"))
        ],
        "nota": (
            "La estimación diaria reanclada usa la cuota SBS anterior. "
            "La trayectoria acumulada no se reancla y permite observar deriva."
        ),
    }
    rutas["json"].write_text(
        json.dumps(
            resumen,
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )

    graficar_por_afp(comparacion, graficos_dir)

    # Reescribir JSON después de generar los gráficos.
    resumen["graficos"] = [
        str(ruta.name)
        for ruta in sorted(graficos_dir.glob("*.png"))
    ]
    rutas["json"].write_text(
        json.dumps(
            resumen,
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )

    print("\nCOMPARACIÓN SBS VS ESTIMACIÓN TERMINADA")
    print("=" * 120)

    print("\nMÉTRICAS POR AFP")
    print("-" * 120)
    print(metricas.to_string(index=False))

    print("\nÚLTIMAS 5 COMPARACIONES POR AFP")
    print("-" * 120)
    columnas = [
        "fecha",
        "afp",
        "cuota_sbs",
        "cuota_estimada_1d",
        "retorno_real_calculado",
        "retorno_estimado",
        "error_pct_cuota_1d",
        "direccion_correcta",
    ]
    print(
        comparacion.groupby("afp", group_keys=False)
        .tail(5)[columnas]
        .to_string(index=False)
    )

    print("\nArchivos creados:")
    for ruta in rutas.values():
        print(f" - {ruta.resolve()}")

    print(f" - Carpeta de gráficos: {graficos_dir.resolve()}")

    print(
        "\nLectura de las gráficas:\n"
        "- SBS vs estimación diaria: compara la cuota oficial con la "
        "estimada usando la cuota oficial anterior como ancla.\n"
        "- Trayectoria acumulada: muestra la deriva si el modelo no se "
        "reancla durante todo el periodo.\n"
        "- Error diario: muestra cuándo el modelo sobreestima o subestima.\n"
        "- El siguiente paso será simular el desfase real de publicación "
        "de la SBS y acumular solo los días todavía no publicados."
    )


if __name__ == "__main__":
    main()
