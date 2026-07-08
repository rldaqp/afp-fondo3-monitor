from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd


def cargar_modulo79(ruta: Path):
    spec = importlib.util.spec_from_file_location("modelo79", ruta)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"No se pudo cargar {ruta}")

    modulo = importlib.util.module_from_spec(spec)

    # Las dataclasses consultan sys.modules mientras se define la clase.
    # Por eso el mÃ³dulo debe registrarse antes de ejecutarlo.
    sys.modules[spec.name] = modulo

    try:
        spec.loader.exec_module(modulo)
    except Exception:
        sys.modules.pop(spec.name, None)
        raise

    return modulo


def ecuacion_legible(intercepto: float, filas: pd.DataFrame) -> str:
    partes = [f"{intercepto:.12f}"]
    for _, fila in filas.iterrows():
        beta = float(fila["coeficiente_raw"])
        nombre = str(fila["variable_modelo"])
        signo = "+" if beta >= 0 else "-"
        partes.append(f" {signo} {abs(beta):.12f}*{nombre}")
    return "".join(partes)


def main() -> None:
    raiz = Path(__file__).resolve().parents[1]
    processed = raiz / "data" / "processed"

    ruta79 = (
        raiz
        / "src"
        / "79_congelar_modelo_y_estimar_prospectivamente.py"
    )

    if not ruta79.exists():
        raise FileNotFoundError(
            f"No se encontrÃ³ el mÃ³dulo 79 en:\n{ruta79}"
        )

    m79 = cargar_modulo79(ruta79)

    base = m79.leer_csv(
        processed / "ca0001_modelo56_base_alineada.csv"
    )
    canasta = m79.leer_csv(
        processed / "ca0001_modelo78_canasta_final_podada.csv"
    )
    metricas = m79.leer_csv(
        processed / "ca0001_modelo78_metricas_validacion.csv"
    )

    base["fecha_cuota"] = pd.to_datetime(
        base["fecha_cuota"], errors="coerce"
    ).dt.normalize()
    base["cuota_sbs"] = pd.to_numeric(
        base["cuota_sbs"], errors="coerce"
    )
    base["retorno_cuota"] = pd.to_numeric(
        base["retorno_cuota"], errors="coerce"
    )

    canasta["lag"] = pd.to_numeric(
        canasta["lag"], errors="coerce"
    ).astype(int)

    configuraciones = metricas[
        metricas["tipo_modelo"]
        .astype(str)
        .eq("CANASTA_PODADA")
    ].copy()

    registro = m79.construir_registro_factores(canasta)

    fecha_ancla_global = pd.Timestamp(
        base.loc[
            base["cuota_sbs"].notna(),
            "fecha_cuota",
        ].max()
    ).normalize()

    fecha_inicio = (
        fecha_ancla_global
        - pd.Timedelta(days=m79.DIAS_BUFFER_DESCARGA)
    )
    fecha_fin = pd.Timestamp.today().normalize()

    print(
        "\nMÃ“DULO 79C â€” ECUACIONES EXACTAS Y CONTRIBUCIONES"
    )
    print("=" * 170)

    operativo, auditoria = m79.descargar_factores_operativos(
        registro,
        fecha_inicio,
        fecha_fin,
    )

    historico = m79.cargar_factores_historicos(processed)

    factores_requeridos = (
        canasta["factor"]
        .astype(str)
        .drop_duplicates()
        .tolist()
    )

    factores = m79.combinar_historico_y_operativo(
        historico,
        operativo,
        factores_requeridos,
    )

    parametros = []
    ecuaciones = []
    contribuciones = []

    for afp in sorted(canasta["afp"].astype(str).unique()):
        cuota = (
            base[base["afp"].astype(str).eq(afp)]
            [["fecha_cuota", "cuota_sbs", "retorno_cuota"]]
            .dropna(subset=["fecha_cuota", "cuota_sbs"])
            .drop_duplicates("fecha_cuota", keep="last")
            .sort_values("fecha_cuota")
        )

        factores = factores.copy()
        cuota = cuota.copy()
        factores["fecha_cuota"] = pd.to_datetime(factores["fecha_cuota"]).dt.normalize()
        cuota["fecha_cuota"] = pd.to_datetime(cuota["fecha_cuota"]).dt.normalize()

        fecha_ancla = pd.Timestamp(
            cuota["fecha_cuota"].max()
        ).normalize()
        cuota_ancla = float(
            cuota.loc[
                cuota["fecha_cuota"].eq(fecha_ancla),
                "cuota_sbs",
            ].iloc[-1]
        )

        canasta_afp = (
            canasta[canasta["afp"].astype(str).eq(afp)]
            .sort_values("orden")
        )

        specs = canasta_afp[
            ["factor", "lag"]
        ].to_dict(orient="records")

        panel = (
            factores.merge(
                cuota,
                on="fecha_cuota",
                how="left",
            )
            .sort_values("fecha_cuota")
            .reset_index(drop=True)
        )

        pf, columnas, factores_base = m79.materializar(
            panel,
            specs,
        )

        train = pf[
            pf["fecha_cuota"].le(fecha_ancla)
        ].copy()

        cfg = configuraciones[
            configuraciones["afp"].astype(str).eq(afp)
        ]

        if cfg.empty:
            raise RuntimeError(
                f"Falta configuraciÃ³n para {afp}."
            )

        cfg = cfg.iloc[0]

        familia = str(cfg["familia"])
        alpha = float(cfg["alpha"])
        half_life = (
            int(cfg["half_life"])
            if pd.notna(cfg["half_life"])
            else None
        )

        modelo = m79.ajustar_modelo(
            train,
            columnas,
            familia,
            alpha,
            half_life,
        )

        medias = np.asarray(modelo.scaler.mean_, dtype=float)
        escalas = np.asarray(modelo.scaler.scale_, dtype=float)
        escalas = np.where(escalas == 0, 1.0, escalas)
        coef_std = np.asarray(modelo.ridge.coef_, dtype=float)
        intercepto_std = float(modelo.ridge.intercept_)

        coef_raw = coef_std / escalas
        intercepto_raw = float(
            intercepto_std
            - np.sum(coef_std * medias / escalas)
        )

        filas_afp = []

        for orden, (
            spec_factor,
            columna,
            media,
            escala,
            b_std,
            b_raw,
        ) in enumerate(
            zip(
                specs,
                columnas,
                medias,
                escalas,
                coef_std,
                coef_raw,
            ),
            start=1,
        ):
            meta = canasta_afp[
                canasta_afp["factor"]
                .astype(str)
                .eq(str(spec_factor["factor"]))
            ]

            fila = {
                "afp": afp,
                "orden": orden,
                "factor": str(spec_factor["factor"]),
                "ticker": (
                    str(meta["ticker"].iloc[0])
                    if not meta.empty
                    else ""
                ),
                "nombre": (
                    str(meta["nombre"].iloc[0])
                    if not meta.empty
                    else ""
                ),
                "lag": int(spec_factor["lag"]),
                "variable_modelo": columna,
                "media_entrenamiento": float(media),
                "desviacion_entrenamiento": float(escala),
                "coeficiente_estandarizado": float(b_std),
                "coeficiente_raw": float(b_raw),
                "intercepto_estandarizado": intercepto_std,
                "intercepto_raw": intercepto_raw,
                "familia": familia,
                "alpha": alpha,
                "half_life": half_life,
                "fecha_ancla": fecha_ancla,
                "cuota_ancla": cuota_ancla,
            }

            parametros.append(fila)
            filas_afp.append(fila)

        filas_afp_df = pd.DataFrame(filas_afp)

        ecuacion_raw = ecuacion_legible(
            intercepto_raw,
            filas_afp_df,
        )

        ecuacion_std_partes = [
            f"{intercepto_std:.12f}"
        ]

        for _, fila in filas_afp_df.iterrows():
            beta = float(
                fila["coeficiente_estandarizado"]
            )
            signo = "+" if beta >= 0 else "-"
            factor = fila["factor"]
            media = float(
                fila["media_entrenamiento"]
            )
            escala = float(
                fila["desviacion_entrenamiento"]
            )
            lag = int(fila["lag"])

            ecuacion_std_partes.append(
                f" {signo} {abs(beta):.12f}"
                f"*(({factor}[t-{lag}]"
                f" - {media:.12f})/{escala:.12f})"
            )

        ecuacion_std = "".join(ecuacion_std_partes)

        ecuaciones.append(
            {
                "afp": afp,
                "familia": familia,
                "alpha": alpha,
                "half_life": half_life,
                "fecha_ancla": fecha_ancla,
                "cuota_ancla": cuota_ancla,
                "ecuacion_retorno_estandarizada": ecuacion_std,
                "ecuacion_retorno_raw": ecuacion_raw,
                "formula_cuota": (
                    "cuota_estimada_t = cuota_ancla * "
                    "PRODUCTO_u(1 + retorno_estimado_u)"
                ),
            }
        )

        futuro = pf[
            pf["fecha_cuota"].gt(fecha_ancla)
        ].copy()

        if futuro.empty:
            continue

        disponibles = futuro[
            factores_base
        ].notna().sum(axis=1)

        futuro["cobertura_pct"] = (
            disponibles
            / max(len(factores_base), 1)
            * 100.0
        )

        publicable = futuro[
            futuro["cobertura_pct"].ge(
                m79.MIN_COBERTURA_PUBLICABLE_PCT
            )
        ]

        if publicable.empty:
            fila_objetivo = futuro.iloc[-1]
        else:
            fila_objetivo = publicable.iloc[-1]

        X_obj = (
            fila_objetivo[columnas]
            .astype(float)
            .replace([np.inf, -np.inf], np.nan)
            .fillna(0.0)
            .to_numpy()
        )

        z_obj = (X_obj - medias) / escalas
        contribs = coef_std * z_obj
        retorno_estimado = float(
            intercepto_std + contribs.sum()
        )

        for spec_factor, columna, valor_x, valor_z, contrib in zip(
            specs,
            columnas,
            X_obj,
            z_obj,
            contribs,
        ):
            meta = canasta_afp[
                canasta_afp["factor"]
                .astype(str)
                .eq(str(spec_factor["factor"]))
            ]

            contribuciones.append(
                {
                    "afp": afp,
                    "fecha_objetivo": fila_objetivo["fecha_cuota"],
                    "factor": str(spec_factor["factor"]),
                    "ticker": (
                        str(meta["ticker"].iloc[0])
                        if not meta.empty
                        else ""
                    ),
                    "lag": int(spec_factor["lag"]),
                    "variable_modelo": columna,
                    "retorno_factor_decimal": float(valor_x),
                    "z_estandarizado": float(valor_z),
                    "coeficiente_estandarizado": float(
                        coef_std[
                            columnas.index(columna)
                        ]
                    ),
                    "contribucion_al_retorno_estimado": float(
                        contrib
                    ),
                    "intercepto_modelo": intercepto_std,
                    "retorno_diario_estimado": retorno_estimado,
                    "cobertura_pct": float(
                        fila_objetivo["cobertura_pct"]
                    ),
                }
            )

        contribuciones.append(
            {
                "afp": afp,
                "fecha_objetivo": fila_objetivo["fecha_cuota"],
                "factor": "INTERCEPTO",
                "ticker": "",
                "lag": 0,
                "variable_modelo": "INTERCEPTO",
                "retorno_factor_decimal": np.nan,
                "z_estandarizado": np.nan,
                "coeficiente_estandarizado": np.nan,
                "contribucion_al_retorno_estimado": intercepto_std,
                "intercepto_modelo": intercepto_std,
                "retorno_diario_estimado": retorno_estimado,
                "cobertura_pct": float(
                    fila_objetivo["cobertura_pct"]
                ),
            }
        )

    parametros_df = pd.DataFrame(parametros)
    ecuaciones_df = pd.DataFrame(ecuaciones)
    contribuciones_df = pd.DataFrame(contribuciones)

    rutas = {
        "parametros": (
            processed
            / "ca0001_modelo79c_parametros_ecuaciones.csv"
        ),
        "ecuaciones": (
            processed
            / "ca0001_modelo79c_ecuaciones_exactas.csv"
        ),
        "contribuciones": (
            processed
            / "ca0001_modelo79c_contribuciones_ultima_fecha.csv"
        ),
        "auditoria": (
            processed
            / "ca0001_modelo79c_auditoria_descargas.csv"
        ),
        "resumen_json": (
            processed
            / "ca0001_modelo79c_resumen.json"
        ),
    }

    parametros_df.to_csv(
        rutas["parametros"],
        index=False,
        encoding="utf-8-sig",
    )
    ecuaciones_df.to_csv(
        rutas["ecuaciones"],
        index=False,
        encoding="utf-8-sig",
    )
    contribuciones_df.to_csv(
        rutas["contribuciones"],
        index=False,
        encoding="utf-8-sig",
    )
    auditoria.to_csv(
        rutas["auditoria"],
        index=False,
        encoding="utf-8-sig",
    )

    rutas["resumen_json"].write_text(
        json.dumps(
            {
                "ecuaciones": ecuaciones,
                "nota": (
                    "Los coeficientes corresponden a la ejecuciÃ³n actual. "
                    "La canasta y los hiperparÃ¡metros estÃ¡n congelados; "
                    "los coeficientes se reestiman cuando se incorporan "
                    "nuevas cuotas oficiales SBS."
                ),
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )

    print("\nECUACIONES DEL RETORNO DIARIO")
    print("-" * 170)

    for _, fila in ecuaciones_df.iterrows():
        print(f"\n{fila['afp']}:")
        print(fila["ecuacion_retorno_estandarizada"])
        print(
            "\nTransformaciÃ³n a cuota:\n"
            f"Cuota_t = {fila['cuota_ancla']:.12f} "
            "* PRODUCTO(1 + retorno_estimado_diario)"
        )

    print("\nCONTRIBUCIONES EN LA ÃšLTIMA FECHA DISPONIBLE")
    print("-" * 170)

    if contribuciones_df.empty:
        print("No existen fechas posteriores al ancla.")
    else:
        tabla = contribuciones_df[
            [
                "afp",
                "fecha_objetivo",
                "ticker",
                "factor",
                "lag",
                "retorno_factor_decimal",
                "z_estandarizado",
                "contribucion_al_retorno_estimado",
                "retorno_diario_estimado",
            ]
        ]

        print(tabla.to_string(index=False))

    print("\nARCHIVOS CREADOS")
    print("-" * 170)

    for ruta in rutas.values():
        print(f" - {ruta.resolve()}")


if __name__ == "__main__":
    main()
