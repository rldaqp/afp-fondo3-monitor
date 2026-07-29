from __future__ import annotations

import json
import math
import warnings
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
import requests
import yfinance as yf
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import HuberRegressor
from sklearn.metrics import r2_score
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "rolling90"
OUT = ROOT / "research_outputs" / "portfolio_regime"
REPORT_DIR = OUT / "fp1356"

WINDOW = 90
THRESHOLD = 0.001
EPSILON = 1.1
ALPHA = 0.0001

BASE_FEATURES = [
    "ret_SPY",
    "ret_NEM",
    "ret_FCX",
    "ret_EPU",
    "ret_MCHI",
    "ret_EEM",
    "ret_USD_PEN",
]

MONTHS = {
    1: ("Enero", "en"),
    2: ("Febrero", "fe"),
    3: ("Marzo", "ma"),
    4: ("Abril", "ab"),
    5: ("Mayo", "my"),
    6: ("Junio", "jn"),
    7: ("Julio", "jl"),
    8: ("Agosto", "ag"),
    9: ("Setiembre", "se"),
    10: ("Octubre", "oc"),
    11: ("Noviembre", "no"),
    12: ("Diciembre", "di"),
}

TARGET_DATES = [
    "2026-03-24",
    "2026-03-27",
    "2026-04-09",
    "2026-06-01",
    "2026-06-16",
    "2026-06-18",
    "2026-06-26",
    "2026-07-02",
    "2026-07-20",
]


def classify(value: float) -> str:
    if value > THRESHOLD:
        return "SUBE"
    if value < -THRESHOLD:
        return "BAJA"
    return "NEUTRO"


def download_close(ticker: str, start: str, end: str) -> pd.Series:
    raw = yf.download(
        ticker,
        start=start,
        end=end,
        auto_adjust=False,
        progress=False,
        threads=False,
    )
    if raw.empty:
        raise RuntimeError(f"Yahoo no devolvió datos para {ticker}")
    close = raw["Close"]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    close = pd.to_numeric(close, errors="coerce")
    close.index = pd.to_datetime(close.index, errors="coerce").tz_localize(None)
    close.name = ticker
    return close.dropna().sort_index()


def month_iter(start: str, end: str) -> Iterable[pd.Timestamp]:
    current = pd.Timestamp(start).to_period("M")
    final = pd.Timestamp(end).to_period("M")
    while current <= final:
        yield current.to_timestamp("M")
        current += 1


def download_report(month_end: pd.Timestamp) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    year = int(month_end.year)
    month = int(month_end.month)
    month_name, code = MONTHS[month]
    path = REPORT_DIR / f"FP-1356-{code}{year}.XLS"
    if path.exists() and path.stat().st_size > 10_000:
        return path

    candidates = [month_name]
    if month == 9:
        candidates.append("Septiembre")
    last_error: Exception | None = None
    for folder in candidates:
        url = (
            "https://intranet2.sbs.gob.pe/estadistica/financiera/"
            f"{year}/{folder}/FP-1356-{code}{year}.XLS"
        )
        try:
            response = requests.get(
                url,
                timeout=60,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            response.raise_for_status()
            if len(response.content) < 10_000:
                raise RuntimeError(f"Archivo demasiado pequeño: {len(response.content)}")
            path.write_bytes(response.content)
            return path
        except Exception as exc:  # pragma: no cover - diagnostic fallback
            last_error = exc
    raise RuntimeError(f"No se pudo descargar {path.name}: {last_error}")


def pct_value(frame: pd.DataFrame, row: int) -> float:
    value = pd.to_numeric(pd.Series([frame.iloc[row, 10]]), errors="coerce").iloc[0]
    if pd.isna(value):
        raise RuntimeError(f"Porcentaje Profuturo vacío en fila {row}")
    return float(value) / 100.0


def label(frame: pd.DataFrame, row: int) -> str:
    return " | ".join(
        str(value).strip()
        for value in frame.iloc[row, :3].tolist()
        if pd.notna(value) and str(value).strip()
    )


def parse_report(path: Path, month_end: pd.Timestamp) -> dict[str, object]:
    frame = pd.read_excel(path, sheet_name="Fondo3xIntru", header=None, engine="xlrd")
    if frame.shape[0] < 72 or frame.shape[1] < 11:
        raise RuntimeError(f"Formato inesperado {path.name}: {frame.shape}")

    checks = {
        7: "INVERSIONES LOCALES",
        23: "Acciones y Valores representativos sobre Acciones",
        34: "Acciones y Valores representativos sobre Acciones",
        49: "INVERSIONES EN EL EXTERIOR",
        64: "Fondos Mutuos Alternativos del Extranjero",
        65: "Fondos Mutuos del Extranjero",
        70: "OPERACIONES EN TRÁNSITO",
        71: "TOTAL",
    }
    for row, expected in checks.items():
        if expected.lower() not in label(frame, row).lower():
            raise RuntimeError(
                f"Estructura cambió en {path.name}, fila {row}: {label(frame, row)!r}"
            )

    # Totales jerárquicos e instrumentos, todos como fracción de la cartera.
    w_local_total = pct_value(frame, 7)
    w_local_government = pct_value(frame, 8)
    w_local_fin_total = pct_value(frame, 13)
    w_local_fin_equity = pct_value(frame, 23)
    w_local_nonfin_total = pct_value(frame, 25)
    w_local_nonfin_equity = pct_value(frame, 34)
    w_local_fund_admin = pct_value(frame, 38)
    w_local_etf = pct_value(frame, 39)
    w_local_alt_limit = pct_value(frame, 40)
    w_local_alt_fund = pct_value(frame, 43)
    w_local_titulization = pct_value(frame, 44)
    w_foreign_total = pct_value(frame, 49)
    w_foreign_government = pct_value(frame, 50)
    w_foreign_fin_total = pct_value(frame, 52)
    w_foreign_nonfin_total = pct_value(frame, 58)
    w_foreign_nonfin_equity = pct_value(frame, 62)
    w_foreign_fund_admin = pct_value(frame, 63)
    w_foreign_alt = pct_value(frame, 64)
    w_foreign_funds = pct_value(frame, 65)
    w_transit = pct_value(frame, 70)

    w_local_equity = w_local_fin_equity + w_local_nonfin_equity
    w_foreign_liquid_funds = w_foreign_funds + w_local_etf
    w_alternatives = w_foreign_alt + w_local_alt_limit + w_local_alt_fund
    w_fixed_income = (
        w_local_government
        + max(w_local_fin_total - w_local_fin_equity, 0.0)
        + max(w_local_nonfin_total - w_local_nonfin_equity, 0.0)
        + w_local_titulization
        + w_foreign_government
        + w_foreign_fin_total
        + max(w_foreign_nonfin_total - w_foreign_nonfin_equity, 0.0)
    )

    # Regla conservadora de disponibilidad: día 15 del mes siguiente.
    available_date = (month_end + pd.offsets.MonthBegin(1)) + pd.Timedelta(days=14)

    return {
        "report_month": month_end.date().isoformat(),
        "available_date": available_date.date().isoformat(),
        "source_file": path.name,
        "w_local_total": w_local_total,
        "w_foreign_total": w_foreign_total,
        "w_local_fin_equity": w_local_fin_equity,
        "w_local_nonfin_equity": w_local_nonfin_equity,
        "w_local_equity": w_local_equity,
        "w_local_etf": w_local_etf,
        "w_foreign_funds": w_foreign_funds,
        "w_foreign_liquid_funds": w_foreign_liquid_funds,
        "w_fixed_income": w_fixed_income,
        "w_alternatives": w_alternatives,
        "w_transit": w_transit,
        "w_observed_liquid": w_local_equity + w_foreign_liquid_funds,
        "w_unobservable": w_alternatives + abs(w_transit),
        "w_local_fund_admin": w_local_fund_admin,
        "w_foreign_fund_admin": w_foreign_fund_admin,
    }


def build_weights() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for month_end in month_iter("2024-11-30", "2026-06-30"):
        path = download_report(month_end)
        rows.append(parse_report(path, month_end))
    weights = pd.DataFrame(rows)
    weights["report_month"] = pd.to_datetime(weights["report_month"])
    weights["available_date"] = pd.to_datetime(weights["available_date"])
    return weights.sort_values("available_date").reset_index(drop=True)


def prepare_data() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    sbs = pd.read_csv(DATA / "sbs_profuturo_f3.csv")
    markets = pd.read_csv(DATA / "markets.csv")

    sbs["fecha"] = pd.to_datetime(sbs["fecha"], errors="coerce")
    sbs["valor_cuota"] = pd.to_numeric(sbs["valor_cuota"], errors="coerce")
    sbs = (
        sbs.dropna(subset=["fecha", "valor_cuota"])
        .sort_values("fecha")
        .drop_duplicates("fecha", keep="last")
    )
    sbs["ret_profuturo"] = sbs["valor_cuota"].pct_change(fill_method=None)

    markets["fecha"] = pd.to_datetime(markets["fecha"], errors="coerce")
    for feature in BASE_FEATURES:
        markets[feature] = pd.to_numeric(markets.get(feature), errors="coerce")

    start = (markets["fecha"].min() - pd.Timedelta(days=15)).date().isoformat()
    end = (markets["fecha"].max() + pd.Timedelta(days=3)).date().isoformat()
    tickers = ["BAP", "IFS", "EMB", "EMLC", "IEF"]
    closes = pd.concat([download_close(ticker, start, end) for ticker in tickers], axis=1)
    extras = closes.reset_index().rename(columns={"Date": "fecha", "index": "fecha"})
    extras["fecha"] = pd.to_datetime(extras["fecha"], errors="coerce")
    for ticker in tickers:
        extras[f"ret_{ticker}"] = extras[ticker].pct_change(fill_method=None)

    market = markets.merge(
        extras[["fecha", *[f"ret_{ticker}" for ticker in tickers]]],
        on="fecha",
        how="left",
    )
    market["ret_PERU_FIN"] = market[["ret_BAP", "ret_IFS"]].mean(axis=1, skipna=False)
    market["ret_FIXED"] = market[["ret_EMB", "ret_EMLC", "ret_IEF"]].mean(
        axis=1, skipna=False
    )
    market["ret_GLOBAL_EQ"] = market[["ret_SPY", "ret_EEM", "ret_MCHI"]].mean(
        axis=1, skipna=False
    )

    weights = build_weights()
    data = sbs[["fecha", "valor_cuota", "ret_profuturo"]].merge(
        market,
        on="fecha",
        how="inner",
    )
    data = pd.merge_asof(
        data.sort_values("fecha"),
        weights.sort_values("available_date"),
        left_on="fecha",
        right_on="available_date",
        direction="backward",
    )

    data["ret_portfolio_proxy"] = (
        data["w_local_nonfin_equity"] * data["ret_EPU"]
        + data["w_local_fin_equity"] * data["ret_PERU_FIN"]
        + data["w_foreign_liquid_funds"] * data["ret_GLOBAL_EQ"]
        + data["w_fixed_income"] * data["ret_FIXED"]
        + data["w_foreign_total"] * data["ret_USD_PEN"]
    )

    # Interacciones de régimen: el mismo retorno pesa distinto según la última cartera publicada.
    data["x_local_nonfin"] = data["w_local_nonfin_equity"] * data["ret_EPU"]
    data["x_local_fin"] = data["w_local_fin_equity"] * data["ret_PERU_FIN"]
    data["x_foreign_spy"] = data["w_foreign_liquid_funds"] * data["ret_SPY"]
    data["x_foreign_eem"] = data["w_foreign_liquid_funds"] * data["ret_EEM"]
    data["x_foreign_mchi"] = data["w_foreign_liquid_funds"] * data["ret_MCHI"]
    data["x_fixed"] = data["w_fixed_income"] * data["ret_FIXED"]
    data["x_fx"] = data["w_foreign_total"] * data["ret_USD_PEN"]

    required = [
        "ret_profuturo",
        *BASE_FEATURES,
        "ret_PERU_FIN",
        "ret_EMB",
        "ret_EMLC",
        "ret_IEF",
        "ret_portfolio_proxy",
        "x_local_nonfin",
        "x_local_fin",
        "x_foreign_spy",
        "x_foreign_eem",
        "x_foreign_mchi",
        "x_fixed",
        "x_fx",
        "w_unobservable",
        "w_alternatives",
        "w_transit",
    ]
    data = data.dropna(subset=required).sort_values("fecha").reset_index(drop=True)
    return data, market, weights


def fit_huber(x: np.ndarray, y: np.ndarray) -> tuple[StandardScaler, HuberRegressor]:
    scaler = StandardScaler()
    x_scaled = scaler.fit_transform(x)
    model = HuberRegressor(
        epsilon=EPSILON,
        alpha=ALPHA,
        fit_intercept=True,
        max_iter=3000,
        tol=1e-8,
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", ConvergenceWarning)
        model.fit(x_scaled, y * 100.0)
    return scaler, model


def rolling_predictions(
    data: pd.DataFrame,
    features: list[str],
    label_name: str,
    residual_proxy: bool = False,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for i in range(WINDOW, len(data)):
        train = data.iloc[i - WINDOW : i]
        row = data.iloc[i]
        y_train = train["ret_profuturo"].to_numpy(float)
        if residual_proxy:
            y_train = y_train - train["ret_portfolio_proxy"].to_numpy(float)
        scaler, model = fit_huber(train[features].to_numpy(float), y_train)
        pred = float(
            model.predict(
                scaler.transform(row[features].to_numpy(float).reshape(1, -1))
            )[0]
            / 100.0
        )
        if residual_proxy:
            pred += float(row["ret_portfolio_proxy"])
        actual = float(row["ret_profuturo"])
        rows.append(
            {
                "row_index": i,
                "fecha": row["fecha"],
                "ret_profuturo": actual,
                f"pred_{label_name}": pred,
                f"class_{label_name}": classify(pred),
                "real_class": classify(actual),
                "report_month": row["report_month"],
                "available_date": row["available_date"],
                "w_alternatives": float(row["w_alternatives"]),
                "w_transit": float(row["w_transit"]),
                "w_unobservable": float(row["w_unobservable"]),
                "ret_portfolio_proxy": float(row["ret_portfolio_proxy"]),
            }
        )
    return pd.DataFrame(rows)


def proxy_predictions(data: pd.DataFrame) -> pd.DataFrame:
    rows = data.iloc[WINDOW:].copy()
    pred = rows["ret_portfolio_proxy"].astype(float)
    return pd.DataFrame(
        {
            "row_index": rows.index,
            "fecha": rows["fecha"],
            "ret_profuturo": rows["ret_profuturo"].astype(float),
            "pred_proxy_only": pred,
            "class_proxy_only": pred.map(classify),
            "real_class": rows["ret_profuturo"].astype(float).map(classify),
        }
    )


def metrics(frame: pd.DataFrame, pred_col: str) -> dict[str, object]:
    work = frame.dropna(subset=["ret_profuturo", pred_col]).copy()
    work["pred_class"] = work[pred_col].map(classify)
    work["real_class"] = work["ret_profuturo"].map(classify)
    work["hit"] = work["pred_class"].eq(work["real_class"])
    error = work[pred_col] - work["ret_profuturo"]
    result: dict[str, object] = {
        "n": int(len(work)),
        "correct": int(work["hit"].sum()),
        "accuracy": float(work["hit"].mean()) if len(work) else None,
        "mae_pp": float(error.abs().mean() * 100.0) if len(work) else None,
        "rmse_pp": float(np.sqrt(np.mean(error * error)) * 100.0) if len(work) else None,
        "r2": float(r2_score(work["ret_profuturo"], work[pred_col]))
        if len(work) > 1
        else None,
        "hard_reversals": int(
            (
                work["pred_class"].isin(["SUBE", "BAJA"])
                & work["real_class"].isin(["SUBE", "BAJA"])
                & work["pred_class"].ne(work["real_class"])
            ).sum()
        ),
    }
    for signal in ["SUBE", "BAJA", "NEUTRO"]:
        subset = work.loc[work["pred_class"].eq(signal)]
        result[f"{signal.lower()}_n"] = int(len(subset))
        result[f"{signal.lower()}_accuracy"] = (
            None if subset.empty else float(subset["hit"].mean())
        )
    return result


def split_name(row_index: int, n: int) -> str:
    train_end = int(math.floor(n * 0.60))
    validation_end = int(math.floor(n * 0.80))
    if row_index < train_end:
        return "train"
    if row_index < validation_end:
        return "validation"
    return "test"


def alert_metrics(frame: pd.DataFrame, pred_col: str, flag: pd.Series) -> dict[str, object]:
    work = frame.copy()
    work["flag"] = flag.reindex(work.index).fillna(False).astype(bool)
    work["abs_error_pp"] = (work[pred_col] - work["ret_profuturo"]).abs() * 100.0
    work["hit"] = work[pred_col].map(classify).eq(work["ret_profuturo"].map(classify))
    result: dict[str, object] = {}
    for name, subset in [("alert", work.loc[work["flag"]]), ("no_alert", work.loc[~work["flag"]])]:
        result[name] = {
            "n": int(len(subset)),
            "error_rate": None if subset.empty else float((~subset["hit"]).mean()),
            "mae_pp": None if subset.empty else float(subset["abs_error_pp"].mean()),
            "hard_reversals": int(
                (
                    subset[pred_col].map(classify).isin(["SUBE", "BAJA"])
                    & subset["ret_profuturo"].map(classify).isin(["SUBE", "BAJA"])
                    & subset[pred_col].map(classify).ne(subset["ret_profuturo"].map(classify))
                ).sum()
            ),
        }
    return result


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    data, market, weights = prepare_data()
    if len(data) <= WINDOW:
        raise RuntimeError(f"Muestra insuficiente: {len(data)}")

    variants: dict[str, tuple[list[str], bool]] = {
        "full7": (BASE_FEATURES, False),
        "plus_peru_fin": ([*BASE_FEATURES, "ret_PERU_FIN"], False),
        "plus_fixed": ([*BASE_FEATURES, "ret_EMB", "ret_EMLC", "ret_IEF"], False),
        "plus_proxy": ([*BASE_FEATURES, "ret_portfolio_proxy"], False),
        "portfolio_regime": (
            [
                *BASE_FEATURES,
                "x_local_nonfin",
                "x_local_fin",
                "x_foreign_spy",
                "x_foreign_eem",
                "x_foreign_mchi",
                "x_fixed",
                "x_fx",
            ],
            False,
        ),
        "residual_proxy": (BASE_FEATURES, True),
        "plus_all": (
            [
                *BASE_FEATURES,
                "ret_PERU_FIN",
                "ret_EMB",
                "ret_EMLC",
                "ret_IEF",
                "ret_portfolio_proxy",
            ],
            False,
        ),
    }

    paired: pd.DataFrame | None = None
    for name, (features, residual) in variants.items():
        pred = rolling_predictions(data, features, name, residual_proxy=residual)
        cols = ["row_index", "fecha", f"pred_{name}", f"class_{name}"]
        if paired is None:
            paired = pred.copy()
        else:
            paired = paired.merge(pred[cols], on=["row_index", "fecha"], how="inner")

    proxy = proxy_predictions(data)
    assert paired is not None
    paired = paired.merge(
        proxy[["row_index", "fecha", "pred_proxy_only", "class_proxy_only"]],
        on=["row_index", "fecha"],
        how="inner",
    )
    all_names = [*variants.keys(), "proxy_only"]
    paired["split"] = paired["row_index"].map(lambda i: split_name(int(i), len(data)))
    for name in all_names:
        paired[f"hit_{name}"] = paired["real_class"].eq(paired[f"class_{name}"])

    split_metrics: dict[str, dict[str, object]] = {}
    for split in ["train", "validation", "test"]:
        subset = paired.loc[paired["split"].eq(split)]
        split_metrics[split] = {
            name: metrics(subset, f"pred_{name}") for name in all_names
        }

    validation = split_metrics["validation"]
    candidates = [name for name in variants if name != "full7"]
    selected = sorted(
        candidates,
        key=lambda name: (
            -float(validation[name]["accuracy"]),
            float(validation[name]["mae_pp"]),
            int(validation[name]["hard_reversals"]),
        ),
    )[0]

    latest90 = paired.tail(WINDOW).copy()
    comparisons: dict[str, object] = {}
    base_hit = latest90["hit_full7"]
    for name in candidates:
        candidate_hit = latest90[f"hit_{name}"]
        corrected = (~base_hit) & candidate_hit
        new_errors = base_hit & (~candidate_hit)
        comparisons[name] = {
            "corrected_errors": int(corrected.sum()),
            "new_errors": int(new_errors.sum()),
            "corrected_dates": latest90.loc[corrected, "fecha"].dt.date.astype(str).tolist(),
            "new_error_dates": latest90.loc[new_errors, "fecha"].dt.date.astype(str).tolist(),
            "signal_changes": int(
                latest90[f"class_{name}"].ne(latest90["class_full7"]).sum()
            ),
        }

    target_rows = paired.loc[
        paired["fecha"].dt.strftime("%Y-%m-%d").isin(TARGET_DATES)
    ].copy()
    target_cols = [
        "fecha",
        "ret_profuturo",
        "real_class",
        "report_month",
        "w_alternatives",
        "w_transit",
        "w_unobservable",
        "ret_portfolio_proxy",
    ]
    for name in all_names:
        target_cols.extend([f"pred_{name}", f"class_{name}", f"hit_{name}"])
    target_rows = target_rows[target_cols]

    # Alertas de calidad: umbrales elegidos solo con validación y evaluados en test.
    validation_rows = paired.loc[paired["split"].eq("validation")]
    test_rows = paired.loc[paired["split"].eq("test")]
    unobservable_threshold = float(validation_rows["w_unobservable"].quantile(0.75))
    alt_threshold = float(validation_rows["w_alternatives"].quantile(0.75))
    transit_threshold = float(validation_rows["w_transit"].abs().quantile(0.75))
    alerts = {
        "thresholds_from_validation": {
            "unobservable_weight": unobservable_threshold,
            "alternatives_weight": alt_threshold,
            "absolute_transit_weight": transit_threshold,
        },
        "test_full7": {
            "unobservable": alert_metrics(
                test_rows,
                "pred_full7",
                test_rows["w_unobservable"].gt(unobservable_threshold),
            ),
            "alternatives": alert_metrics(
                test_rows,
                "pred_full7",
                test_rows["w_alternatives"].gt(alt_threshold),
            ),
            "transit": alert_metrics(
                test_rows,
                "pred_full7",
                test_rows["w_transit"].abs().gt(transit_threshold),
            ),
        },
        "test_selected": {
            "selected": selected,
            "unobservable": alert_metrics(
                test_rows,
                f"pred_{selected}",
                test_rows["w_unobservable"].gt(unobservable_threshold),
            ),
        },
    }

    test_base = split_metrics["test"]["full7"]
    test_selected = split_metrics["test"][selected]
    recent_base = metrics(latest90, "pred_full7")
    recent_selected = metrics(latest90, f"pred_{selected}")
    accepted = bool(
        int(test_selected["correct"]) > int(test_base["correct"])
        and float(test_selected["mae_pp"]) < float(test_base["mae_pp"])
        and (
            test_selected["baja_accuracy"] is not None
            and test_base["baja_accuracy"] is not None
            and float(test_selected["baja_accuracy"]) >= float(test_base["baja_accuracy"])
        )
        and int(recent_selected["correct"]) >= int(recent_base["correct"])
    )

    result = {
        "method": {
            "window": WINDOW,
            "threshold": THRESHOLD,
            "huber_epsilon": EPSILON,
            "huber_alpha": ALPHA,
            "base_features": BASE_FEATURES,
            "new_market_data": "Yahoo Finance Close, auto_adjust=False: BAP, IFS, EMB, EMLC, IEF",
            "portfolio_reports": "SBS FP-1356, Profuturo Fondo 3",
            "report_availability_rule": "Each month-end report becomes usable on day 15 of the following month",
            "selection_rule": "Highest validation 3-class accuracy; ties by lower validation MAE and hard reversals",
            "acceptance_rule": "Independent test must improve correct classifications and MAE, not reduce BAJA accuracy, and not reduce latest90 correct classifications",
            "leakage_control": "Every prediction uses only the preceding 90 observations and the latest portfolio report already available under the conservative publication rule",
        },
        "sample": {
            "n": int(len(data)),
            "start": data.iloc[0]["fecha"].date().isoformat(),
            "end": data.iloc[-1]["fecha"].date().isoformat(),
            "rolling_predictions_n": int(len(paired)),
            "reports_n": int(len(weights)),
            "reports_start": weights.iloc[0]["report_month"].date().isoformat(),
            "reports_end": weights.iloc[-1]["report_month"].date().isoformat(),
        },
        "selected_candidate": selected,
        "accepted_for_operational_use": accepted,
        "chronological_60_20_20": split_metrics,
        "latest90": {
            "metrics": {
                name: metrics(latest90, f"pred_{name}") for name in all_names
            },
            "comparisons_vs_full7": comparisons,
        },
        "alerts": alerts,
        "target_dates": json.loads(
            target_rows.to_json(orient="records", date_format="iso")
        ),
        "latest_portfolio_report": json.loads(
            weights.tail(1).to_json(orient="records", date_format="iso")
        )[0],
    }

    paired.to_csv(OUT / "paired_predictions.csv", index=False)
    weights.to_csv(OUT / "monthly_weights.csv", index=False)
    target_rows.to_csv(OUT / "target_dates.csv", index=False)
    data[
        [
            "fecha",
            "report_month",
            "available_date",
            "ret_portfolio_proxy",
            "w_local_fin_equity",
            "w_local_nonfin_equity",
            "w_foreign_liquid_funds",
            "w_fixed_income",
            "w_alternatives",
            "w_transit",
            "w_unobservable",
        ]
    ].to_csv(OUT / "daily_portfolio_features.csv", index=False)
    (OUT / "results.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
