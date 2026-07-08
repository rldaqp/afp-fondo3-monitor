from __future__ import annotations

import json
import re
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from sklearn.feature_selection import mutual_info_regression

warnings.filterwarnings("ignore")

AFPS = ["Habitat", "Integra", "Prima", "Profuturo"]
FECHA_INICIO = "2014-12-01"
MIN_ALIAS = 180
MIN_SCREEN = 700
MAX_GAP_RETORNO_DIAS = 5
LAGS = [0, 1, 2, 3]

UMBRAL_COBERTURA = 55.0
UMBRAL_CERO_VOLUMEN = 35.0
UMBRAL_SIN_CAMBIO = 75.0
UMBRAL_P90_GAP = 5.0

# Catálogo exploratorio. El programa prueba varios alias y conserva el mejor.
CATALOGO: list[dict[str, Any]] = [
    {
        "instrumento": "S&P/BVL Peru General",
        "tipo": "INDICE_BVL",
        "sector": "MERCADO_GENERAL",
        "aliases": [("^SPBLPGPT", "PEN"), ("SPBLPGPT", "PEN"), ("^IGBVL", "PEN")],
    },
    {
        "instrumento": "S&P/BVL Peru Select",
        "tipo": "INDICE_BVL",
        "sector": "MERCADO_SELECTIVO",
        "aliases": [("^SPBLPSPT", "PEN"), ("SPBLPSPT", "PEN"), ("^IBVL", "PEN")],
    },
    {
        "instrumento": "S&P/BVL Lima 25",
        "tipo": "INDICE_BVL",
        "sector": "MERCADO_LIQUIDO",
        "aliases": [("^SPBL25PT", "PEN"), ("SPBL25PT", "PEN"), ("^LIMA25", "PEN")],
    },
    {
        "instrumento": "S&P/BVL Peru General ESG",
        "tipo": "INDICE_BVL",
        "sector": "ESG",
        "aliases": [("^SPBLPESGPT", "PEN"), ("SPBLPESGPT", "PEN")],
    },
    {
        "instrumento": "Alicorp",
        "tipo": "ACCION_BVL",
        "sector": "CONSUMO",
        "aliases": [("ALICORC1.LM", "PEN"), ("ALICORC1", "PEN")],
    },
    {
        "instrumento": "InRetail Peru",
        "tipo": "ACCION_BVL",
        "sector": "RETAIL",
        "aliases": [("INRETC1.LM", "PEN"), ("INRETC1", "PEN"), ("INRE.LM", "PEN")],
    },
    {
        "instrumento": "Backus",
        "tipo": "ACCION_BVL",
        "sector": "BEBIDAS",
        "aliases": [("BACKUSI1.LM", "PEN"), ("BACKUSI1", "PEN"), ("BACKUSBC1.LM", "PEN")],
    },
    {
        "instrumento": "Ferreycorp",
        "tipo": "ACCION_BVL",
        "sector": "INDUSTRIA",
        "aliases": [("FERREYC1.LM", "PEN"), ("FERREYC1", "PEN")],
    },
    {
        "instrumento": "UNACEM",
        "tipo": "ACCION_BVL",
        "sector": "CEMENTO",
        "aliases": [("UNACEMC1.LM", "PEN"), ("UNACEMC1", "PEN")],
    },
    {
        "instrumento": "Cementos Pacasmayo",
        "tipo": "ACCION_BVL_ADR",
        "sector": "CEMENTO",
        "aliases": [("CPACASC1.LM", "PEN"), ("CPACASC1", "PEN"), ("CPAC", "USD")],
    },
    {
        "instrumento": "Siderperu",
        "tipo": "ACCION_BVL",
        "sector": "ACERO",
        "aliases": [("SIDERC1.LM", "PEN"), ("SIDERC1", "PEN")],
    },
    {
        "instrumento": "Aceros Arequipa",
        "tipo": "ACCION_BVL",
        "sector": "ACERO",
        "aliases": [("CORAREC1.LM", "PEN"), ("CORAREC1", "PEN"), ("CORAREI1.LM", "PEN")],
    },
    {
        "instrumento": "Aenza",
        "tipo": "ACCION_BVL_ADR",
        "sector": "INFRAESTRUCTURA",
        "aliases": [("AENZAC1.LM", "PEN"), ("AENZAC1", "PEN"), ("AENZ", "USD")],
    },
    {
        "instrumento": "Buenaventura",
        "tipo": "ACCION_BVL_ADR",
        "sector": "MINERIA",
        "aliases": [("BUENAVC1.LM", "PEN"), ("BUENAVC1", "PEN"), ("BVN", "USD")],
    },
    {
        "instrumento": "Southern Copper",
        "tipo": "ACCION_BVL_ADR",
        "sector": "MINERIA_COBRE",
        "aliases": [("SCCO", "USD"), ("SOUTHERC1.LM", "PEN"), ("SOUTHERC1", "PEN")],
    },
    {
        "instrumento": "Minsur",
        "tipo": "ACCION_BVL",
        "sector": "MINERIA",
        "aliases": [("MINSURI1.LM", "PEN"), ("MINSURI1", "PEN"), ("MINSURC1.LM", "PEN")],
    },
    {
        "instrumento": "Volcan",
        "tipo": "ACCION_BVL",
        "sector": "MINERIA",
        "aliases": [("VOLCABC1.LM", "PEN"), ("VOLCABC1", "PEN"), ("VOLCAAC1.LM", "PEN")],
    },
    {
        "instrumento": "El Brocal",
        "tipo": "ACCION_BVL",
        "sector": "MINERIA",
        "aliases": [("BROCALC1.LM", "PEN"), ("BROCALC1", "PEN")],
    },
    {
        "instrumento": "Nexa Resources Peru",
        "tipo": "ACCION_BVL",
        "sector": "MINERIA",
        "aliases": [("NEXAPEC1.LM", "PEN"), ("NEXAPEC1", "PEN"), ("MILPOC1.LM", "PEN")],
    },
    {
        "instrumento": "Cerro Verde",
        "tipo": "ACCION_BVL",
        "sector": "MINERIA_COBRE",
        "aliases": [("CVERDEC1.LM", "PEN"), ("CVERDEC1", "PEN")],
    },
    {
        "instrumento": "Credicorp",
        "tipo": "ACCION_BVL_ADR",
        "sector": "FINANCIERO",
        "aliases": [("BAP", "USD"), ("BAP.LM", "PEN"), ("CREDITC1.LM", "PEN")],
    },
    {
        "instrumento": "Intercorp Financial Services",
        "tipo": "ACCION_BVL_ADR",
        "sector": "FINANCIERO",
        "aliases": [("IFS", "USD"), ("IFSC1.LM", "PEN"), ("IFSC1", "PEN")],
    },
    {
        "instrumento": "Bolsa de Valores de Lima",
        "tipo": "ACCION_BVL",
        "sector": "INFRAESTRUCTURA_MERCADO",
        "aliases": [("BVLAC1.LM", "PEN"), ("BVLAC1", "PEN")],
    },
    {
        "instrumento": "Engie Energia Peru",
        "tipo": "ACCION_BVL",
        "sector": "ENERGIA",
        "aliases": [("ENGIEC1.LM", "PEN"), ("ENGIEC1", "PEN")],
    },
    {
        "instrumento": "Luz del Sur",
        "tipo": "ACCION_BVL",
        "sector": "ENERGIA_DISTRIBUCION",
        "aliases": [("LUSURC1.LM", "PEN"), ("LUSURC1", "PEN")],
    },
    {
        "instrumento": "Pluz Energia Peru",
        "tipo": "ACCION_BVL",
        "sector": "ENERGIA_DISTRIBUCION",
        "aliases": [("PLUZC1.LM", "PEN"), ("PLUZC1", "PEN"), ("ENDISPC1.LM", "PEN")],
    },
    {
        "instrumento": "Casa Grande",
        "tipo": "ACCION_BVL",
        "sector": "AGROINDUSTRIA",
        "aliases": [("CASAGRC1.LM", "PEN"), ("CASAGRC1", "PEN")],
    },
    {
        "instrumento": "Cartavio",
        "tipo": "ACCION_BVL",
        "sector": "AGROINDUSTRIA",
        "aliases": [("CARTAVC1.LM", "PEN"), ("CARTAVC1", "PEN")],
    },
    {
        "instrumento": "Pomalca",
        "tipo": "ACCION_BVL",
        "sector": "AGROINDUSTRIA",
        "aliases": [("POMALCC1.LM", "PEN"), ("POMALCC1", "PEN")],
    },
    {
        "instrumento": "Austral Group",
        "tipo": "ACCION_BVL",
        "sector": "PESCA",
        "aliases": [("AUSTRAC1.LM", "PEN"), ("AUSTRAC1", "PEN")],
    },
]


def slug(texto: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", texto.upper()).strip("_")


def leer_csv(ruta: Path) -> pd.DataFrame:
    for encoding in ("utf-8-sig", "latin-1"):
        try:
            return pd.read_csv(ruta, encoding=encoding)
        except Exception:
            pass
    raise RuntimeError(f"No se pudo leer {ruta}")


def extraer(descarga: pd.DataFrame, ticker: str, campo: str) -> pd.Series:
    if descarga.empty:
        return pd.Series(dtype=float)

    campos = [campo] + (["Close"] if campo == "Adj Close" else [])

    if isinstance(descarga.columns, pd.MultiIndex):
        nivel0 = descarga.columns.get_level_values(0)
        nivel1 = descarga.columns.get_level_values(1)

        for c in campos:
            if c in nivel0:
                bloque = descarga[c]
                if isinstance(bloque, pd.Series):
                    return pd.to_numeric(bloque, errors="coerce")
                if ticker in bloque.columns:
                    return pd.to_numeric(bloque[ticker], errors="coerce")
                if len(bloque.columns) == 1:
                    return pd.to_numeric(bloque.iloc[:, 0], errors="coerce")

            if ticker in nivel1:
                bloque = descarga.xs(ticker, axis=1, level=1)
                if c in bloque.columns:
                    return pd.to_numeric(bloque[c], errors="coerce")

        return pd.Series(dtype=float)

    for c in campos:
        if c in descarga.columns:
            return pd.to_numeric(descarga[c], errors="coerce")

    return pd.Series(dtype=float)


def normalizar_serie(serie: pd.Series) -> pd.Series:
    x = serie.dropna().copy()
    indice = pd.to_datetime(x.index, errors="coerce")
    try:
        indice = indice.tz_localize(None)
    except (TypeError, AttributeError):
        pass
    x.index = pd.DatetimeIndex(indice).normalize()
    x = x[~x.index.isna()]
    return x[~x.index.duplicated(keep="last")].sort_index()


def descargar(ticker: str, inicio: str, fin: str) -> pd.DataFrame:
    try:
        import yfinance as yf
    except ImportError as exc:
        raise RuntimeError("Instale yfinance: pip install yfinance") from exc

    raw = yf.download(
        ticker,
        start=inicio,
        end=fin,
        auto_adjust=False,
        progress=False,
        threads=False,
    )

    precio = normalizar_serie(extraer(raw, ticker, "Adj Close"))
    cierre = normalizar_serie(extraer(raw, ticker, "Close"))
    volumen = normalizar_serie(extraer(raw, ticker, "Volume"))

    fechas = precio.index.union(cierre.index).union(volumen.index)
    if len(fechas) == 0:
        return pd.DataFrame(columns=["precio_ajustado", "cierre", "volumen"])

    df = pd.DataFrame(index=fechas.sort_values())
    df["precio_ajustado"] = precio.reindex(df.index)
    df["cierre"] = cierre.reindex(df.index)
    df["volumen"] = volumen.reindex(df.index)
    df.index.name = "fecha_mercado"
    return df.dropna(subset=["precio_ajustado", "cierre"], how="all")


def calidad(df: pd.DataFrame) -> dict[str, Any]:
    if df.empty:
        return {
            "n_precios": 0,
            "fecha_inicio": pd.NaT,
            "fecha_fin": pd.NaT,
            "cero_volumen_pct": np.nan,
            "sin_cambio_pct": np.nan,
            "gap_mediana_dias": np.nan,
            "gap_p90_dias": np.nan,
            "gap_max_dias": np.nan,
        }

    precio = df["precio_ajustado"].fillna(df["cierre"])
    gaps = df.index.to_series().diff().dt.days.dropna()
    volumen = df["volumen"]

    return {
        "n_precios": int(precio.notna().sum()),
        "fecha_inicio": df.index.min(),
        "fecha_fin": df.index.max(),
        "cero_volumen_pct": (
            float(volumen.fillna(0).eq(0).mean() * 100.0)
            if volumen.notna().any() else np.nan
        ),
        "sin_cambio_pct": float(precio.pct_change(fill_method=None).eq(0).mean() * 100.0),
        "gap_mediana_dias": float(gaps.median()) if not gaps.empty else np.nan,
        "gap_p90_dias": float(gaps.quantile(0.90)) if not gaps.empty else np.nan,
        "gap_max_dias": float(gaps.max()) if not gaps.empty else np.nan,
    }


def elegir_aliases(inicio: str, fin: str) -> tuple[dict[str, dict[str, Any]], pd.DataFrame]:
    seleccionados: dict[str, dict[str, Any]] = {}
    auditoria: list[dict[str, Any]] = []

    for i, entrada in enumerate(CATALOGO, start=1):
        print(f"  [{i:02d}/{len(CATALOGO):02d}] {entrada['instrumento']}")
        mejor = None

        for ticker, moneda in entrada["aliases"]:
            try:
                datos = descargar(ticker, inicio, fin)
                met = calidad(datos)
                estado = "CORRECTO" if met["n_precios"] >= MIN_ALIAS else "HISTORIA_INSUFICIENTE"
            except Exception as exc:
                datos = pd.DataFrame()
                met = calidad(datos)
                estado = f"ERROR: {exc}"

            auditoria.append({
                "instrumento": entrada["instrumento"],
                "tipo": entrada["tipo"],
                "sector": entrada["sector"],
                "alias_probado": ticker,
                "moneda_alias": moneda,
                "estado": estado,
                **met,
            })

            if met["n_precios"] < MIN_ALIAS:
                continue

            candidato = {
                "instrumento": entrada["instrumento"],
                "tipo": entrada["tipo"],
                "sector": entrada["sector"],
                "ticker": ticker,
                "moneda": moneda,
                "datos": datos,
                "metricas": met,
            }

            if mejor is None or met["n_precios"] > mejor["metricas"]["n_precios"]:
                mejor = candidato

            if met["n_precios"] >= 2500 and pd.Timestamp(met["fecha_inicio"]) <= pd.Timestamp("2015-01-15"):
                break

        if mejor is not None:
            seleccionados[entrada["instrumento"]] = mejor

    return seleccionados, pd.DataFrame(auditoria)


def construir_retorno(df: pd.DataFrame, usar_volumen: bool) -> pd.DataFrame:
    x = df.copy()
    x["precio"] = x["precio_ajustado"].fillna(x["cierre"])
    x = x.dropna(subset=["precio"]).sort_index()
    x["gap_dias"] = x.index.to_series().diff().dt.days
    x["retorno"] = x["precio"].pct_change(fill_method=None)
    x.loc[x["gap_dias"].gt(MAX_GAP_RETORNO_DIAS), "retorno"] = np.nan

    if usar_volumen and x["volumen"].notna().any():
        x.loc[x["volumen"].fillna(0).eq(0), "retorno"] = np.nan

    return x


def cargar_usdpen(inicio: str, fin: str) -> pd.Series:
    df = descargar("PEN=X", inicio, fin)
    if df.empty:
        raise RuntimeError("No se pudo descargar PEN=X")
    return df["precio_ajustado"].fillna(df["cierre"]).dropna().sort_index()


def construir_factores(
    seleccionados: dict[str, dict[str, Any]],
    usdpen: pd.Series,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    factores: dict[str, pd.Series] = {}
    catalogo: list[dict[str, Any]] = []

    for nombre, info in seleccionados.items():
        tipo = info["tipo"]
        moneda = info["moneda"]
        base = construir_retorno(info["datos"], usar_volumen=tipo != "INDICE_BVL")
        nombre_slug = slug(nombre)

        if moneda == "PEN":
            factor = f"ret_BVL_PEN_{nombre_slug}"
            factores[factor] = base["retorno"]
            catalogo.append({
                "factor": factor,
                "instrumento": nombre,
                "ticker_elegido": info["ticker"],
                "tipo": tipo,
                "sector": info["sector"],
                "moneda_modelo": "PEN",
                "transformacion": "retorno_local_en_PEN",
            })
        else:
            factor_usd = f"ret_BVL_USD_{nombre_slug}"
            factores[factor_usd] = base["retorno"]
            catalogo.append({
                "factor": factor_usd,
                "instrumento": nombre,
                "ticker_elegido": info["ticker"],
                "tipo": tipo,
                "sector": info["sector"],
                "moneda_modelo": "USD",
                "transformacion": "retorno_en_USD",
            })

            fx = usdpen.reindex(base.index, method="ffill", tolerance=pd.Timedelta(days=5))
            precio_pen = base["precio"] * fx
            retorno_pen = precio_pen.pct_change(fill_method=None)
            retorno_pen.loc[base["gap_dias"].gt(MAX_GAP_RETORNO_DIAS)] = np.nan
            if tipo != "INDICE_BVL" and base["volumen"].notna().any():
                retorno_pen.loc[base["volumen"].fillna(0).eq(0)] = np.nan

            factor_pen = f"ret_BVL_PEN_{nombre_slug}"
            factores[factor_pen] = retorno_pen
            catalogo.append({
                "factor": factor_pen,
                "instrumento": nombre,
                "ticker_elegido": info["ticker"],
                "tipo": tipo,
                "sector": info["sector"],
                "moneda_modelo": "PEN",
                "transformacion": "retorno_USD_convertido_a_PEN",
            })

    panel = pd.concat(factores.values(), axis=1).sort_index()
    panel.columns = list(factores.keys())
    panel.index.name = "fecha_cuota"
    return panel.reset_index(), pd.DataFrame(catalogo)


def cargar_base_y_train(processed: Path) -> tuple[pd.DataFrame, pd.Timestamp]:
    base = leer_csv(processed / "ca0001_modelo56_base_alineada.csv")
    split = leer_csv(processed / "ca0001_modelo50_division_temporal.csv")

    base["fecha_cuota"] = pd.to_datetime(base["fecha_cuota"], errors="coerce").dt.normalize()
    base["retorno_cuota"] = pd.to_numeric(base["retorno_cuota"], errors="coerce")
    split["fecha_fin"] = pd.to_datetime(split["fecha_fin"], errors="coerce")

    fila = split[split["segmento"].astype(str).eq("entrenamiento_descubrimiento")]
    if fila.empty:
        raise RuntimeError("No se encontró entrenamiento_descubrimiento")

    return base, pd.Timestamp(fila["fecha_fin"].iloc[0]).normalize()


def mutual_info(x: pd.Series, y: pd.Series) -> float:
    par = pd.concat([x, y], axis=1).dropna()
    if len(par) < MIN_SCREEN:
        return np.nan
    try:
        return float(mutual_info_regression(
            par.iloc[:, [0]].to_numpy(),
            par.iloc[:, 1].to_numpy(),
            random_state=42,
        )[0])
    except Exception:
        return np.nan


def screening(base: pd.DataFrame, factores: pd.DataFrame, fin_train: pd.Timestamp) -> pd.DataFrame:
    panel = base.merge(factores, on="fecha_cuota", how="left")
    columnas = [c for c in factores.columns if c != "fecha_cuota"]
    filas: list[dict[str, Any]] = []

    for afp in AFPS:
        datos = panel[
            panel["afp"].astype(str).eq(afp)
            & panel["fecha_cuota"].le(fin_train)
        ].copy()
        y = datos["retorno_cuota"]

        for factor in columnas:
            evaluados = []
            for lag in LAGS:
                x = datos[factor].shift(lag)
                par = pd.concat([y, x], axis=1).dropna()
                if len(par) < MIN_SCREEN:
                    continue
                evaluados.append({
                    "lag": lag,
                    "n": len(par),
                    "spearman": float(par.iloc[:, 0].corr(par.iloc[:, 1], method="spearman")),
                    "pearson": float(par.iloc[:, 0].corr(par.iloc[:, 1], method="pearson")),
                    "mi": mutual_info(par.iloc[:, 1], par.iloc[:, 0]),
                })

            if not evaluados:
                continue

            mejor = max(evaluados, key=lambda z: abs(z["spearman"]))
            filas.append({
                "afp": afp,
                "factor": factor,
                "mejor_lag_train": int(mejor["lag"]),
                "n_train": int(mejor["n"]),
                "cobertura_train_pct": float(datos[factor].notna().mean() * 100.0),
                "spearman_train": mejor["spearman"],
                "pearson_train": mejor["pearson"],
                "mutual_information_train": mejor["mi"],
                "abs_spearman_train": abs(mejor["spearman"]),
            })

    if not filas:
        return pd.DataFrame()

    return pd.DataFrame(filas).sort_values(
        ["afp", "abs_spearman_train"],
        ascending=[True, False],
    ).reset_index(drop=True)


def auditar_factores(
    factores: pd.DataFrame,
    catalogo: pd.DataFrame,
    base: pd.DataFrame,
    fin_train: pd.Timestamp,
    seleccionados: dict[str, dict[str, Any]],
) -> pd.DataFrame:
    fechas_train = base[base["fecha_cuota"].le(fin_train)][["fecha_cuota"]].drop_duplicates()
    calidad_map = {nombre: info["metricas"] for nombre, info in seleccionados.items()}
    filas = []

    for factor in [c for c in factores.columns if c != "fecha_cuota"]:
        meta = catalogo[catalogo["factor"].eq(factor)].iloc[0]
        serie = factores[["fecha_cuota", factor]].dropna()
        train = fechas_train.merge(factores[["fecha_cuota", factor]], on="fecha_cuota", how="left")
        q = calidad_map[meta["instrumento"]]

        cobertura = float(train[factor].notna().mean() * 100.0)
        volumen_ok = pd.isna(q["cero_volumen_pct"]) or q["cero_volumen_pct"] <= UMBRAL_CERO_VOLUMEN
        elegible = (
            cobertura >= UMBRAL_COBERTURA
            and volumen_ok
            and q["sin_cambio_pct"] <= UMBRAL_SIN_CAMBIO
            and q["gap_p90_dias"] <= UMBRAL_P90_GAP
        )

        motivos = []
        if cobertura < UMBRAL_COBERTURA:
            motivos.append("COBERTURA_BAJA")
        if not volumen_ok:
            motivos.append("MUCHO_VOLUMEN_CERO")
        if q["sin_cambio_pct"] > UMBRAL_SIN_CAMBIO:
            motivos.append("PRECIO_MUY_ESTATICO")
        if q["gap_p90_dias"] > UMBRAL_P90_GAP:
            motivos.append("GAPS_FRECUENTES")

        filas.append({
            "factor": factor,
            "instrumento": meta["instrumento"],
            "ticker_elegido": meta["ticker_elegido"],
            "tipo": meta["tipo"],
            "sector": meta["sector"],
            "moneda_modelo": meta["moneda_modelo"],
            "n_retornos": int(len(serie)),
            "fecha_inicio_retorno": serie["fecha_cuota"].min() if not serie.empty else pd.NaT,
            "fecha_fin_retorno": serie["fecha_cuota"].max() if not serie.empty else pd.NaT,
            "cobertura_train_pct": cobertura,
            "cero_volumen_pct": q["cero_volumen_pct"],
            "sin_cambio_pct": q["sin_cambio_pct"],
            "gap_p90_dias": q["gap_p90_dias"],
            "gap_max_dias": q["gap_max_dias"],
            "elegible_operativo": bool(elegible),
            "motivo_elegibilidad": "ELEGIBLE" if not motivos else "|".join(motivos),
        })

    return pd.DataFrame(filas)


def graficar(screen: pd.DataFrame, carpeta: Path) -> None:
    carpeta.mkdir(parents=True, exist_ok=True)
    if screen.empty:
        return

    for afp in AFPS:
        top = screen[screen["afp"].eq(afp)].head(20).sort_values("abs_spearman_train")
        if top.empty:
            continue
        etiquetas = [f"{i} (L{l})" for i, l in zip(top["instrumento"], top["mejor_lag_train"])]
        plt.figure(figsize=(12, 8))
        plt.barh(etiquetas, top["spearman_train"])
        plt.axvline(0, linewidth=1)
        plt.xlabel("Spearman en entrenamiento")
        plt.title(f"Índices y acciones BVL — {afp}")
        plt.tight_layout()
        plt.savefig(carpeta / f"01_bvl_{afp.lower()}.png", dpi=160, bbox_inches="tight")
        plt.close()


def main() -> None:
    raiz = Path(__file__).resolve().parents[1]
    processed = raiz / "data" / "processed"
    graficos = processed / "graficos_modelo72"
    processed.mkdir(parents=True, exist_ok=True)

    base, fin_train = cargar_base_y_train(processed)
    fecha_fin = (
        max(pd.Timestamp.today().normalize(), pd.Timestamp(base["fecha_cuota"].max()) + pd.Timedelta(days=5))
        + pd.Timedelta(days=1)
    ).strftime("%Y-%m-%d")

    print("\nMÓDULO 72 — ÍNDICES Y ACCIONES DE LA BVL")
    print("=" * 150)
    print("Se prueba disponibilidad, calidad de negociación y relación con la cuota usando solo entrenamiento.")
    print(f"Descarga: {FECHA_INICIO} a {fecha_fin}")

    seleccionados, auditoria_alias = elegir_aliases(FECHA_INICIO, fecha_fin)
    if not seleccionados:
        auditoria_alias.to_csv(
            processed / "ca0001_modelo72_auditoria_alias_bvl.csv",
            index=False,
            encoding="utf-8-sig",
        )
        raise RuntimeError("Ningún alias tuvo historia suficiente. Revise la auditoría creada.")

    usdpen = cargar_usdpen(FECHA_INICIO, fecha_fin)
    factores, catalogo = construir_factores(seleccionados, usdpen)
    screen = screening(base, factores, fin_train)
    auditoria_factores = auditar_factores(
        factores, catalogo, base, fin_train, seleccionados
    )

    if not screen.empty:
        screen = (
            screen.merge(catalogo, on="factor", how="left")
            .merge(
                auditoria_factores[["factor", "elegible_operativo", "motivo_elegibilidad"]],
                on="factor",
                how="left",
            )
        )

    graficar(screen, graficos)

    rutas = {
        "auditoria_alias": processed / "ca0001_modelo72_auditoria_alias_bvl.csv",
        "catalogo": processed / "ca0001_modelo72_catalogo_factores_bvl.csv",
        "factores": processed / "ca0001_modelo72_factores_bvl.csv",
        "auditoria_factores": processed / "ca0001_modelo72_auditoria_factores_bvl.csv",
        "screening": processed / "ca0001_modelo72_screening_train_bvl.csv",
        "top": processed / "ca0001_modelo72_top20_bvl_por_afp.csv",
        "resumen": processed / "ca0001_modelo72_resumen.json",
    }

    auditoria_alias.to_csv(rutas["auditoria_alias"], index=False, encoding="utf-8-sig", date_format="%Y-%m-%d")
    catalogo.to_csv(rutas["catalogo"], index=False, encoding="utf-8-sig")
    factores.to_csv(rutas["factores"], index=False, encoding="utf-8-sig", date_format="%Y-%m-%d")
    auditoria_factores.to_csv(rutas["auditoria_factores"], index=False, encoding="utf-8-sig", date_format="%Y-%m-%d")
    screen.to_csv(rutas["screening"], index=False, encoding="utf-8-sig")

    if screen.empty:
        pd.DataFrame().to_csv(rutas["top"], index=False, encoding="utf-8-sig")
    else:
        screen.groupby("afp", group_keys=False).head(20).to_csv(
            rutas["top"], index=False, encoding="utf-8-sig"
        )

    resumen = {
        "version": "modelo72_bvl_indices_acciones",
        "instrumentos_catalogo": len(CATALOGO),
        "instrumentos_con_alias_valido": len(seleccionados),
        "factores_generados": int(len([c for c in factores.columns if c != "fecha_cuota"])),
        "factores_elegibles_operativamente": int(auditoria_factores["elegible_operativo"].sum()),
        "fin_entrenamiento_screening": str(fin_train.date()),
        "nota": "La relación estadística no prueba que la AFP mantenga el instrumento.",
    }
    rutas["resumen"].write_text(json.dumps(resumen, ensure_ascii=False, indent=2), encoding="utf-8")

    elegidos = []
    for nombre, info in seleccionados.items():
        elegidos.append({
            "instrumento": nombre,
            "ticker_elegido": info["ticker"],
            "moneda": info["moneda"],
            "tipo": info["tipo"],
            "sector": info["sector"],
            **info["metricas"],
        })
    elegidos_df = pd.DataFrame(elegidos)

    print("\nALIAS ELEGIDOS")
    print("-" * 150)
    print(elegidos_df[[
        "instrumento", "ticker_elegido", "moneda", "tipo", "n_precios",
        "fecha_inicio", "fecha_fin", "cero_volumen_pct", "sin_cambio_pct", "gap_p90_dias"
    ]].to_string(index=False))

    print("\nELEGIBILIDAD OPERATIVA")
    print("-" * 150)
    print(auditoria_factores[[
        "factor", "instrumento", "ticker_elegido", "tipo", "sector", "moneda_modelo",
        "cobertura_train_pct", "cero_volumen_pct", "sin_cambio_pct", "gap_p90_dias",
        "elegible_operativo", "motivo_elegibilidad"
    ]].to_string(index=False))

    print("\nTOP 20 POR AFP — SOLO ENTRENAMIENTO")
    print("-" * 150)
    if screen.empty:
        print(f"No hubo factores con al menos {MIN_SCREEN} observaciones.")
    else:
        print(screen.groupby("afp", group_keys=False).head(20)[[
            "afp", "instrumento", "ticker_elegido", "factor", "mejor_lag_train",
            "n_train", "cobertura_train_pct", "spearman_train", "pearson_train",
            "mutual_information_train", "elegible_operativo"
        ]].to_string(index=False))

    print("\nARCHIVOS CREADOS")
    print("-" * 150)
    for ruta in rutas.values():
        print(f" - {ruta.resolve()}")
    print(f" - {graficos.resolve()}")

    print(
        "\nLECTURA:\n"
        "- El alias válido solo confirma disponibilidad de datos.\n"
        "- Una acción local con volumen cero no se interpreta como retorno real de 0%.\n"
        "- Elegible operativo exige cobertura y calidad mínima.\n"
        "- El módulo 73 probará aporte incremental frente a los modelos 70 y 71."
    )


if __name__ == "__main__":
    main()
