from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


AFPS = ["Habitat", "Integra", "Prima", "Profuturo"]


def leer_csv(ruta: Path) -> pd.DataFrame:
    if not ruta.exists():
        raise FileNotFoundError(f"No existe el archivo requerido: {ruta}")

    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return pd.read_csv(ruta, encoding=encoding)
        except UnicodeDecodeError:
            continue

    return pd.read_csv(ruta)


def escribir_csv(df: pd.DataFrame, ruta: Path) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(ruta, index=False, encoding="utf-8-sig")


def numero(serie: pd.Series) -> pd.Series:
    return pd.to_numeric(serie, errors="coerce")


def cargar_cartera(processed: Path) -> pd.DataFrame:
    ruta = processed / "ca0001_fondo3_hoja10_base_canonica_reconciliada.csv"
    df = leer_csv(ruta)

    requeridas = {
        "fecha_cartera",
        "afp",
        "fondo",
        "identificador_final",
        "tipo_identificador",
        "moneda",
        "peso_total_fondo_reconciliado",
        "valor_reconciliado_miles_soles",
    }
    faltantes = sorted(requeridas.difference(df.columns))
    if faltantes:
        raise ValueError(f"Faltan columnas de cartera: {faltantes}")

    df["fecha_cartera"] = pd.to_datetime(df["fecha_cartera"], errors="coerce")
    df["fondo"] = numero(df["fondo"])
    df["peso_total_fondo_reconciliado"] = numero(
        df["peso_total_fondo_reconciliado"]
    )
    df["valor_reconciliado_miles_soles"] = numero(
        df["valor_reconciliado_miles_soles"]
    )

    cartera = df[
        df["afp"].isin(AFPS)
        & df["fondo"].eq(3)
        & df["fecha_cartera"].notna()
        & df["identificador_final"].notna()
        & df["peso_total_fondo_reconciliado"].gt(0)
    ].copy()

    if cartera.empty:
        raise ValueError("No se encontro cartera valida para Fondo 3.")

    ultima_fecha = cartera["fecha_cartera"].max()
    return cartera[cartera["fecha_cartera"].eq(ultima_fecha)].copy()


def preparar_cartera_replicante(cartera: pd.DataFrame) -> pd.DataFrame:
    columnas_opcionales = [
        "archivo",
        "grupo",
        "entidad_administradora",
        "isin",
        "estado_identificacion",
        "estado_cobertura",
    ]
    columnas = [
        "fecha_cartera",
        "afp",
        "fondo",
        "identificador_final",
        "tipo_identificador",
        "moneda",
        "peso_total_fondo_reconciliado",
        "peso_total_fondo_reconciliado_pct",
        "valor_reconciliado_miles_soles",
    ] + [c for c in columnas_opcionales if c in cartera.columns]

    base = cartera[columnas].copy()
    base = base.rename(
        columns={
            "identificador_final": "instrumento_id",
            "tipo_identificador": "tipo_id",
            "peso_total_fondo_reconciliado": "peso_fondo",
            "peso_total_fondo_reconciliado_pct": "peso_fondo_pct",
            "valor_reconciliado_miles_soles": "monto_miles_soles",
        }
    )

    base["fuente_precio_sugerida"] = base["tipo_id"].map(
        {
            "isin": "mapear_isin_a_ticker",
            "ticker": "yfinance_o_bvl",
        }
    ).fillna("proxy_pendiente")
    base["ticker_precio"] = ""
    base["proxy_si_no_hay_precio"] = ""
    base["estado_mapeo_precio"] = "pendiente"

    return base.sort_values(["afp", "peso_fondo"], ascending=[True, False])


def preparar_resumen(cartera_replicante: pd.DataFrame) -> pd.DataFrame:
    resumen = (
        cartera_replicante.groupby("afp", as_index=False)
        .agg(
            fecha_cartera=("fecha_cartera", "max"),
            instrumentos=("instrumento_id", "nunique"),
            peso_total_mapeado=("peso_fondo", "sum"),
            monto_total_miles_soles=("monto_miles_soles", "sum"),
            peso_top_10=("peso_fondo", lambda s: s.nlargest(10).sum()),
            peso_top_25=("peso_fondo", lambda s: s.nlargest(25).sum()),
        )
        .sort_values("afp")
    )
    resumen["peso_total_mapeado_pct"] = resumen["peso_total_mapeado"] * 100.0
    resumen["peso_top_10_pct"] = resumen["peso_top_10"] * 100.0
    resumen["peso_top_25_pct"] = resumen["peso_top_25"] * 100.0
    return resumen


def preparar_fuentes() -> pd.DataFrame:
    filas = [
        {
            "bloque": "cartera",
            "fuente": "SBS CA-0001",
            "uso": "instrumentos y pesos por AFP Fondo 3",
            "estado": "disponible_en_repo",
        },
        {
            "bloque": "cuota",
            "fuente": "SBS valor cuota Fondo 3",
            "uso": "validacion diaria y ancla del valor cuota",
            "estado": "disponible_en_repo",
        },
        {
            "bloque": "precios",
            "fuente": "Yahoo Finance / yfinance",
            "uso": "precios intradia de ETF, acciones USA y proxies",
            "estado": "pendiente_mapeo",
        },
        {
            "bloque": "precios",
            "fuente": "BVL",
            "uso": "acciones peruanas y precios locales",
            "estado": "pendiente_mapeo",
        },
        {
            "bloque": "fx",
            "fuente": "USD/PEN",
            "uso": "convertir exposiciones extranjeras a soles",
            "estado": "pendiente_fuente_operativa",
        },
        {
            "bloque": "bonos",
            "fuente": "curvas/proxies de renta fija",
            "uso": "aproximar instrumentos sin precio intradia",
            "estado": "pendiente_proxy",
        },
    ]
    return pd.DataFrame(filas)


def preparar_metricas() -> pd.DataFrame:
    filas = [
        {
            "grupo": "precision_diaria",
            "metrica": "MAE",
            "calculo": "promedio(abs(cuota_estimada - cuota_sbs_real))",
            "respuesta": "cuanto se equivoca en unidades de valor cuota",
        },
        {
            "grupo": "precision_diaria",
            "metrica": "MAPE",
            "calculo": "promedio(abs(cuota_estimada / cuota_sbs_real - 1))",
            "respuesta": "error porcentual promedio",
        },
        {
            "grupo": "precision_diaria",
            "metrica": "RMSE",
            "calculo": "raiz(promedio(error^2))",
            "respuesta": "castiga mas los errores grandes",
        },
        {
            "grupo": "direccion",
            "metrica": "acierto_direccion",
            "calculo": "signo(retorno_estimado) == signo(retorno_real)",
            "respuesta": "si acierta sube o baja",
        },
        {
            "grupo": "relacion",
            "metrica": "correlacion_retornos",
            "calculo": "corr(retorno_estimado, retorno_real)",
            "respuesta": "si se mueve parecido a la SBS",
        },
        {
            "grupo": "riesgo_modelo",
            "metrica": "tracking_error",
            "calculo": "desviacion_estandar(retorno_estimado - retorno_real)",
            "respuesta": "desviacion frente a la cuota oficial",
        },
        {
            "grupo": "intradia",
            "metrica": "error_por_hora",
            "calculo": "error de estimacion 10:00, 12:00, 15:00, cierre",
            "respuesta": "a que hora la estimacion empieza a ser util",
        },
        {
            "grupo": "comparacion",
            "metrica": "mejora_vs_modelo_tonto",
            "calculo": "MAE_modelo < MAE(ultima_cuota_sbs)",
            "respuesta": "si el modelo aporta valor real",
        },
    ]
    return pd.DataFrame(filas)


def main() -> None:
    raiz = Path(__file__).resolve().parents[1]
    processed = raiz / "data" / "processed"

    cartera = cargar_cartera(processed)
    cartera_replicante = preparar_cartera_replicante(cartera)
    resumen = preparar_resumen(cartera_replicante)
    fuentes = preparar_fuentes()
    metricas = preparar_metricas()

    escribir_csv(
        cartera_replicante,
        processed / "cartera_replicante_intradia_base_ultimo_mes.csv",
    )
    escribir_csv(
        resumen,
        processed / "cartera_replicante_intradia_resumen_afp.csv",
    )
    escribir_csv(
        fuentes,
        processed / "cartera_replicante_intradia_fuentes.csv",
    )
    escribir_csv(
        metricas,
        processed / "cartera_replicante_intradia_metricas_plan.csv",
    )

    manifiesto = {
        "proyecto": "valor_cuota_intradia_cartera_replicante",
        "fecha_cartera": str(
            pd.Timestamp(cartera_replicante["fecha_cartera"].max()).date()
        ),
        "afps": AFPS,
        "archivos_generados": [
            "cartera_replicante_intradia_base_ultimo_mes.csv",
            "cartera_replicante_intradia_resumen_afp.csv",
            "cartera_replicante_intradia_fuentes.csv",
            "cartera_replicante_intradia_metricas_plan.csv",
        ],
        "siguiente_paso": (
            "Mapear instrumento_id/ISIN a ticker_precio o proxy para poder "
            "descargar precios intradia."
        ),
    }
    (processed / "cartera_replicante_intradia_manifiesto.json").write_text(
        json.dumps(manifiesto, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print("Proyecto creado: valor cuota intradia por cartera replicante")
    print(resumen.to_string(index=False))


if __name__ == "__main__":
    main()

