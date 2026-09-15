from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


AFPS = ["Habitat", "Integra", "Prima", "Profuturo"]
TRAIN_FRAC = 0.60
VALID_FRAC = 0.20
TEST_FRAC = 0.20
MOMENTUM_WINDOWS = (2, 3, 5)
VOL_WINDOWS = (5, 10, 20)
DRAWDOWN_WINDOWS = (5, 10, 20)
MIN_ROWS = 600


def cargar_modulo79(raiz: Path):
    ruta = raiz / "src" / "79_congelar_modelo_y_estimar_prospectivamente.py"
    spec = importlib.util.spec_from_file_location("modelo79_operativo", ruta)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"No se pudo cargar {ruta}")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def leer_csv(ruta: Path, obligatorio: bool = True) -> pd.DataFrame:
    if not ruta.exists():
        if obligatorio:
            raise FileNotFoundError(f"No existe el archivo requerido: {ruta}")
        return pd.DataFrame()
    ultimo_error: Exception | None = None
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return pd.read_csv(ruta, encoding=encoding)
        except Exception as exc:
            ultimo_error = exc
    raise RuntimeError(f"No se pudo leer {ruta}: {ultimo_error}")


def escribir_csv(df: pd.DataFrame, ruta: Path) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(ruta, index=False, encoding="utf-8-sig", date_format="%Y-%m-%d")


def retorno_compuesto(serie: pd.Series, ventana: int) -> pd.Series:
    r = pd.to_numeric(serie, errors="coerce").replace([np.inf, -np.inf], np.nan)
    return (1.0 + r).rolling(ventana, min_periods=ventana).apply(np.prod, raw=True) - 1.0


def dividir_bloques(df: pd.DataFrame) -> pd.DataFrame:
    n = len(df)
    if n < MIN_ROWS:
        raise RuntimeError(f"Muestra insuficiente para 60/20/20: {n} filas")
    corte_train = int(math.floor(n * TRAIN_FRAC))
    corte_valid = int(math.floor(n * (TRAIN_FRAC + VALID_FRAC)))
    if min(corte_train, corte_valid - corte_train, n - corte_valid) < 50:
        raise RuntimeError("Alguno de los bloques temporales quedo demasiado pequeno")

    salida = df.copy()
    salida["bloque_60_20_20"] = "test_reservado"
    salida.loc[salida.index[:corte_train], "bloque_60_20_20"] = "entrenamiento"
    salida.loc[salida.index[corte_train:corte_valid], "bloque_60_20_20"] = "validacion"
    return salida


def preparar_base_sbs(base: pd.DataFrame, afp: str) -> pd.DataFrame:
    requeridas = {"fecha_cuota", "afp", "cuota_sbs", "retorno_cuota"}
    faltantes = requeridas.difference(base.columns)
    if faltantes:
        raise KeyError(f"Faltan columnas en la base SBS: {sorted(faltantes)}")

    g = base[base["afp"].astype(str).eq(afp)].copy()
    g["fecha_cuota"] = pd.to_datetime(g["fecha_cuota"], errors="coerce").dt.normalize()
    g["cuota_sbs"] = pd.to_numeric(g["cuota_sbs"], errors="coerce")
    g["retorno_cuota"] = pd.to_numeric(g["retorno_cuota"], errors="coerce")
    g = g.dropna(subset=["fecha_cuota"]).drop_duplicates("fecha_cuota", keep="last")
    g = g.sort_values("fecha_cuota").reset_index(drop=True)

    # Al decidir al cierre de t, la cuota oficial de t puede no estar publicada.
    # Las variables SBS usan exclusivamente t-1 o fechas anteriores.
    g["cuota_sbs_conocida"] = g["cuota_sbs"].shift(1)
    g["retorno_sbs_lag1"] = g["retorno_cuota"].shift(1)
    g["retorno_sbs_lag2"] = g["retorno_cuota"].shift(2)
    g["retorno_sbs_lag3"] = g["retorno_cuota"].shift(3)
    g["momentum_sbs_3"] = retorno_compuesto(g["retorno_cuota"].shift(1), 3)
    g["momentum_sbs_5"] = retorno_compuesto(g["retorno_cuota"].shift(1), 5)
    g["vol_sbs_5"] = g["retorno_cuota"].shift(1).rolling(5, min_periods=5).std()
    g["vol_sbs_10"] = g["retorno_cuota"].shift(1).rolling(10, min_periods=10).std()
    g["aceleracion_sbs"] = g["retorno_sbs_lag1"] - g["retorno_sbs_lag2"]

    cuota_conocida = g["cuota_sbs"].shift(1)
    for ventana in DRAWDOWN_WINDOWS:
        maximo = cuota_conocida.rolling(ventana, min_periods=ventana).max()
        g[f"retroceso_sbs_max_{ventana}"] = cuota_conocida / maximo - 1.0

    # Los objetivos siempre pertenecen a la siguiente fecha SBS disponible.
    g["fecha_objetivo_t1"] = g["fecha_cuota"].shift(-1)
    g["retorno_real_t1"] = g["retorno_cuota"].shift(-1)
    g["caida_t1"] = np.where(
        g["retorno_real_t1"].notna(),
        (g["retorno_real_t1"] < 0).astype(int),
        np.nan,
    )
    return g


def preparar_nowcast(bitacora: pd.DataFrame, afp: str) -> pd.DataFrame:
    if bitacora.empty:
        return pd.DataFrame(columns=["fecha_cuota"])

    requeridas = {"fecha", "afp", "retorno_estimado"}
    faltantes = requeridas.difference(bitacora.columns)
    if faltantes:
        raise KeyError(f"Faltan columnas en la bitacora: {sorted(faltantes)}")

    g = bitacora[bitacora["afp"].astype(str).eq(afp)].copy()
    g["fecha_cuota"] = pd.to_datetime(g["fecha"], errors="coerce").dt.normalize()
    g["retorno_nowcast"] = pd.to_numeric(g["retorno_estimado"], errors="coerce")
    g = g.dropna(subset=["fecha_cuota"]).drop_duplicates("fecha_cuota", keep="last")
    g = g.sort_values("fecha_cuota").reset_index(drop=True)

    g["nowcast_lag1"] = g["retorno_nowcast"].shift(1)
    g["nowcast_lag2"] = g["retorno_nowcast"].shift(2)
    g["aceleracion_nowcast"] = g["retorno_nowcast"] - g["nowcast_lag1"]
    g["momentum_nowcast_2"] = retorno_compuesto(g["retorno_nowcast"], 2)
    g["momentum_nowcast_3"] = retorno_compuesto(g["retorno_nowcast"], 3)
    g["vol_nowcast_5"] = g["retorno_nowcast"].rolling(5, min_periods=5).std()

    if "error_abs_pct" in g.columns:
        error = pd.to_numeric(g["error_abs_pct"], errors="coerce") / 100.0
        g["error_abs_nowcast_lag1"] = error.shift(1)
        g["error_abs_nowcast_media5"] = error.shift(1).rolling(5, min_periods=3).mean()
    else:
        g["error_abs_nowcast_lag1"] = np.nan
        g["error_abs_nowcast_media5"] = np.nan

    return g[
        [
            "fecha_cuota",
            "retorno_nowcast",
            "nowcast_lag1",
            "nowcast_lag2",
            "aceleracion_nowcast",
            "momentum_nowcast_2",
            "momentum_nowcast_3",
            "vol_nowcast_5",
            "error_abs_nowcast_lag1",
            "error_abs_nowcast_media5",
        ]
    ]


def preparar_factores(
    factores: pd.DataFrame,
    canasta_afp: pd.DataFrame,
) -> tuple[pd.DataFrame, list[str]]:
    panel = factores.copy()
    panel["fecha_cuota"] = pd.to_datetime(panel["fecha_cuota"], errors="coerce").dt.normalize()
    panel = panel.dropna(subset=["fecha_cuota"]).drop_duplicates("fecha_cuota", keep="last")
    panel = panel.sort_values("fecha_cuota").set_index("fecha_cuota")

    specs = canasta_afp[["factor", "lag"]].drop_duplicates().sort_values(["factor", "lag"])
    features = pd.DataFrame(index=panel.index)
    columnas_individuales: list[str] = []

    for _, spec in specs.iterrows():
        factor = str(spec["factor"])
        lag_num = pd.to_numeric(spec["lag"], errors="coerce")
        lag = int(lag_num) if pd.notna(lag_num) else 0
        if factor not in panel.columns:
            continue

        disponible = pd.to_numeric(panel[factor], errors="coerce").shift(lag)
        prefijo = f"{factor}__lag{lag}"
        features[f"{prefijo}__ret1"] = disponible
        columnas_individuales.append(f"{prefijo}__ret1")

        for ventana in MOMENTUM_WINDOWS:
            columna = f"{prefijo}__mom{ventana}"
            features[columna] = retorno_compuesto(disponible, ventana)
            columnas_individuales.append(columna)

        for ventana in VOL_WINDOWS:
            columna = f"{prefijo}__vol{ventana}"
            features[columna] = disponible.rolling(ventana, min_periods=ventana).std()
            columnas_individuales.append(columna)

        features[f"{prefijo}__aceleracion"] = disponible - disponible.shift(1)
        columnas_individuales.append(f"{prefijo}__aceleracion")

    retornos_dia = [c for c in features.columns if c.endswith("__ret1")]
    if retornos_dia:
        bloque = features[retornos_dia]
        features["amplitud_factores_positivos"] = (bloque > 0).mean(axis=1)
        features["amplitud_factores_negativos"] = (bloque < 0).mean(axis=1)
        features["retorno_medio_factores"] = bloque.mean(axis=1)
        features["dispersion_factores"] = bloque.std(axis=1)
        features["min_factor"] = bloque.min(axis=1)
        features["max_factor"] = bloque.max(axis=1)

    features = features.replace([np.inf, -np.inf], np.nan).reset_index()
    return features, columnas_individuales


def construir_afp(
    afp: str,
    base: pd.DataFrame,
    factores: pd.DataFrame,
    canasta: pd.DataFrame,
    bitacora: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any], list[str]]:
    sbs = preparar_base_sbs(base, afp)
    nowcast = preparar_nowcast(bitacora, afp)
    factores_afp, columnas_factores = preparar_factores(
        factores,
        canasta[canasta["afp"].astype(str).eq(afp)].copy(),
    )

    dataset = sbs.merge(factores_afp, on="fecha_cuota", how="left")
    if not nowcast.empty:
        dataset = dataset.merge(nowcast, on="fecha_cuota", how="left")

    dataset["afp"] = afp
    dataset = dataset.sort_values("fecha_cuota").reset_index(drop=True)
    historico = dataset.dropna(subset=["retorno_real_t1", "caida_t1"]).reset_index(drop=True)
    historico = dividir_bloques(historico)

    columnas_prohibidas = {
        "afp",
        "fecha_cuota",
        "fecha_objetivo_t1",
        "cuota_sbs",
        "retorno_cuota",
        "retorno_real_t1",
        "caida_t1",
        "bloque_60_20_20",
    }
    columnas_modelo = [
        c
        for c in historico.columns
        if c not in columnas_prohibidas and pd.api.types.is_numeric_dtype(historico[c])
    ]
    cobertura = historico[columnas_modelo].notna().mean().sort_values(ascending=False)
    nowcast_disponible = (
        historico["retorno_nowcast"].notna().mean() * 100.0
        if "retorno_nowcast" in historico.columns
        else 0.0
    )

    resumen = {
        "afp": afp,
        "n_total": int(len(historico)),
        "n_train_60": int((historico["bloque_60_20_20"] == "entrenamiento").sum()),
        "n_valid_20": int((historico["bloque_60_20_20"] == "validacion").sum()),
        "n_test_20": int((historico["bloque_60_20_20"] == "test_reservado").sum()),
        "fecha_inicio": historico["fecha_cuota"].min(),
        "fecha_fin": historico["fecha_cuota"].max(),
        "n_variables_modelo": int(len(columnas_modelo)),
        "n_factores_individuales": int(len(columnas_factores)),
        "cobertura_mediana_variables": float(cobertura.median()) if not cobertura.empty else np.nan,
        "nowcast_disponible_pct": float(nowcast_disponible),
    }
    return historico, resumen, columnas_modelo


def main() -> None:
    raiz = Path(__file__).resolve().parents[2]
    processed = raiz / "data" / "processed"
    salida = processed / "modelo_salida"
    salida.mkdir(parents=True, exist_ok=True)

    m79 = cargar_modulo79(raiz)
    base = leer_csv(processed / "ca0001_modelo56_base_alineada.csv")
    canasta = leer_csv(processed / "ca0001_modelo78_canasta_final_podada.csv")
    bitacora = leer_csv(processed / "tablero_operativo_bitacora_diaria.csv", obligatorio=False)

    base["fecha_cuota"] = pd.to_datetime(base["fecha_cuota"], errors="coerce").dt.normalize()
    historicos = m79.cargar_factores_historicos(processed)
    factores_requeridos = canasta["factor"].astype(str).drop_duplicates().tolist()

    # Primera etapa reproducible: usa factores historicos ya guardados. La descarga
    # operativa se incorporara en el modulo de senal actual, sin alterar esta base.
    columnas_factores = [c for c in factores_requeridos if c in historicos.columns]
    factores = historicos[["fecha_cuota"] + columnas_factores].copy()

    bases: list[pd.DataFrame] = []
    resumenes: list[dict[str, Any]] = []
    columnas_por_afp: dict[str, list[str]] = {}

    for afp in AFPS:
        dataset, resumen, columnas_modelo = construir_afp(afp, base, factores, canasta, bitacora)
        bases.append(dataset)
        resumenes.append(resumen)
        columnas_por_afp[afp] = columnas_modelo

    base_salida = pd.concat(bases, ignore_index=True)
    resumen_df = pd.DataFrame(resumenes)

    escribir_csv(base_salida, salida / "base_modelo_salida.csv")
    escribir_csv(
        base_salida[
            [
                "afp",
                "fecha_cuota",
                "fecha_objetivo_t1",
                "bloque_60_20_20",
                "retorno_real_t1",
                "caida_t1",
            ]
        ],
        salida / "division_temporal.csv",
    )
    escribir_csv(resumen_df, salida / "resumen_base.csv")

    manifiesto = {
        "version": "modelo_salida_v1_base",
        "objetivo": "Predecir el retorno y el riesgo de caida de la siguiente cuota SBS disponible.",
        "regla_informacion": "Las variables SBS oficiales se desplazan al menos un paso. El objetivo corresponde a t+1.",
        "division": {
            "entrenamiento": TRAIN_FRAC,
            "validacion": VALID_FRAC,
            "test_reservado": TEST_FRAC,
            "orden_cronologico": True,
        },
        "fuentes": {
            "sbs": "ca0001_modelo56_base_alineada.csv",
            "canasta": "ca0001_modelo78_canasta_final_podada.csv",
            "factores": [
                "ca0001_modelo69_factores_ampliados.csv",
                "ca0001_modelo72_factores_bvl.csv",
                "ca0001_modelo74_factores_indices.csv",
                "ca0001_modelo76_factores_futuros_cripto.csv",
            ],
            "nowcast_opcional": "tablero_operativo_bitacora_diaria.csv",
        },
        "columnas_modelo_por_afp": columnas_por_afp,
        "advertencia": "La bitacora historica de nowcast debe auditarse como pronostico congelado antes de interpretar resultados causales.",
    }
    (salida / "manifiesto_base.json").write_text(
        json.dumps(manifiesto, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    print("Base del modelo de salida creada")
    print(resumen_df.to_string(index=False))


if __name__ == "__main__":
    main()
