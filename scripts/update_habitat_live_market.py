from __future__ import annotations

import copy
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
PROFUTURO_LIVE = ROOT / "public" / "data" / "live_market.json"
HABITAT_LATEST = ROOT / "public" / "habitat" / "data" / "latest.json"
HABITAT_LIVE = ROOT / "public" / "habitat" / "data" / "live_market.json"
HABITAT_SIGNALS = ROOT / "public" / "habitat" / "data" / "signals.json"
HABITAT_SERIES = ROOT / "public" / "habitat" / "data" / "series.json"
HABITAT_OPERATION_SERIES = (
    ROOT / "public" / "habitat" / "data" / "operation_series.json"
)
HABITAT_INSIGHTS = ROOT / "public" / "habitat" / "data" / "model_insights.json"
LIMA = ZoneInfo("America/Lima")
THRESHOLD = 0.001


def classify(value: float) -> str:
    if value > THRESHOLD:
        return "SUBE"
    if value < -THRESHOLD:
        return "BAJA"
    return "NEUTRO"


def finite_number(value: object, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if np.isfinite(number) else default


def factor_returns(assets: list[dict]) -> dict[str, float]:
    returns: dict[str, float] = {}
    for asset in assets:
        serie = str(asset.get("serie", "")).strip()
        if not serie:
            continue
        key = "ret_USD_PEN" if serie == "USD_PEN" else f"ret_{serie}"
        value = asset.get("retorno_modelo")
        if value is None:
            value = asset.get("retorno")
        returns[key] = finite_number(value)
    return returns


def read_json(path: Path, default: object) -> object:
    if not path.exists() or path.stat().st_size == 0:
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def upsert_by_date(rows: list[dict], row: dict, date_key: str = "fecha") -> list[dict]:
    date = str(row.get(date_key, ""))
    filtered = [item for item in rows if str(item.get(date_key, "")) != date]
    filtered.append(row)
    return sorted(filtered, key=lambda item: str(item.get(date_key, "")))


def sync_fallback_outputs(payload: dict, latest: dict) -> None:
    """Mantiene los JSON base al día cuando el motor live ya tiene cierre nuevo."""
    mode = str(payload.get("mode", ""))
    signal_date = str(payload.get("signal_date") or "")
    latest_date = str(latest.get("latest_estimate_date") or "")
    if not mode.startswith("CIERRE") or not signal_date or signal_date <= latest_date:
        return
    if not np.isfinite(float(payload.get("vc_estimated", np.nan))):
        return

    estimated_vc = float(payload["vc_estimated"])
    estimated_return = finite_number(payload.get("return_estimated"))
    signal = str(payload.get("signal") or classify(estimated_return))

    latest["generated_at_lima"] = payload.get("generated_at_lima") or datetime.now(LIMA).isoformat()
    latest["latest_market_date"] = signal_date
    latest["latest_estimate_date"] = signal_date
    latest["latest_estimated_vc"] = estimated_vc
    latest["latest_return_estimated"] = estimated_return
    latest["signal"] = signal
    latest["latest_fx_source"] = payload.get("fx_source", latest.get("latest_fx_source", "SIN DATO"))
    latest["latest_fx_provisional"] = bool(
        payload.get("fx_provisional", latest.get("latest_fx_provisional", True))
    )
    write_json(HABITAT_LATEST, latest)

    signal_row = {
        "fecha": signal_date,
        "ret_estimado": estimated_return,
        "senal": signal,
        "vc_real": None,
        "vc_estimado": estimated_vc,
        "tipo": "CIERRE DIARIO",
    }
    series_row = {
        "fecha": signal_date,
        "vc": estimated_vc,
        "fuente": "MODELO OLS",
        "es_oficial": False,
        "senal": signal,
        "ret_estimado": estimated_return,
    }

    for path, row in (
        (HABITAT_SIGNALS, signal_row),
        (HABITAT_SERIES, series_row),
        (HABITAT_OPERATION_SERIES, series_row),
    ):
        rows = read_json(path, [])
        if isinstance(rows, list):
            write_json(path, upsert_by_date(rows, row))

    insights = read_json(HABITAT_INSIGHTS, {})
    if isinstance(insights, dict):
        insights["generated_for"] = signal_date
        insights["current_signal"] = signal
        quality = insights.get("quality")
        if isinstance(quality, dict):
            quality["fx_provisional"] = latest.get("latest_fx_provisional", True)
        write_json(HABITAT_INSIGHTS, insights)


def main() -> None:
    if not PROFUTURO_LIVE.exists():
        raise RuntimeError("Falta public/data/live_market.json")
    if not HABITAT_LATEST.exists():
        raise RuntimeError("Falta public/habitat/data/latest.json")

    market = json.loads(PROFUTURO_LIVE.read_text(encoding="utf-8"))
    latest = json.loads(HABITAT_LATEST.read_text(encoding="utf-8"))
    assets = copy.deepcopy(market.get("assets", []))
    is_open = bool(market.get("market_open"))
    mode = str(market.get("mode", ""))
    is_intraday = mode.startswith("INTRAD")
    is_market_snapshot = mode.startswith(("INTRAD", "CIERRE"))
    market_signal_date = str(market.get("signal_date") or "")
    latest_estimate_date = str(latest.get("latest_estimate_date") or "")
    needs_new_projection = bool(market_signal_date) and (
        not latest_estimate_date or market_signal_date > latest_estimate_date
    )

    if is_market_snapshot and needs_new_projection and not market.get("warning"):
        coefficients = latest.get("coefficients", {}) or {}
        estimated_return = finite_number(coefficients.get("intercept"))
        for key, value in factor_returns(assets).items():
            estimated_return += finite_number(coefficients.get(key)) * value

        base_vc = finite_number(
            latest.get("latest_estimated_vc"),
            finite_number(latest.get("latest_sbs_vc")),
        )
        payload = {
            "generated_at_lima": market.get("generated_at_lima")
            or datetime.now(LIMA).isoformat(),
            "mode": market.get("mode") or "INTRADIA PROVISIONAL",
            "market_open": is_open,
            "signal_date": market_signal_date,
            "vc_base": base_vc,
            "vc_estimated": base_vc * (1.0 + estimated_return),
            "return_estimated": estimated_return,
            "signal": classify(estimated_return),
            "assets": assets,
            "action": "ESPERAR" if is_open else ("ULTIMO_CORTE" if is_intraday else "CIERRE"),
            "engine": "LIVE HABITAT INDEPENDIENTE",
            "fx_fresh": market.get("fx_fresh"),
            "fx_source": market.get("fx_source", "SIN DATO"),
            "fx_provisional": bool(market.get("fx_provisional", True)),
            "fx_rule": market.get("fx_rule", ""),
            "checked_at_lima": market.get("checked_at_lima"),
            "note": (
                "Snapshot calculado con los coeficientes propios de Habitat "
                "y los mismos retornos de mercado del motor en vivo."
            ),
        }
    else:
        payload = {
            "generated_at_lima": datetime.now(LIMA).isoformat(),
            "mode": market.get("mode", "CIERRE DIARIO"),
            "market_open": False,
            "signal_date": latest.get("latest_estimate_date"),
            "vc_base": latest.get("latest_sbs_vc"),
            "vc_estimated": latest.get("latest_estimated_vc"),
            "return_estimated": latest.get("latest_return_estimated"),
            "signal": latest.get("signal"),
            "assets": assets,
            "action": "CIERRE",
            "engine": "LIVE HABITAT INDEPENDIENTE",
            "warning": market.get("warning"),
            "fx_source": latest.get("latest_fx_source", market.get("fx_source", "SIN DATO")),
            "fx_provisional": bool(
                latest.get("latest_fx_provisional", market.get("fx_provisional", True))
            ),
            "fx_rule": market.get("fx_rule", ""),
            "note": "Cierre diario de Habitat con actualizacion del motor de mercado.",
        }

    HABITAT_LIVE.parent.mkdir(parents=True, exist_ok=True)
    write_json(HABITAT_LIVE, payload)
    sync_fallback_outputs(payload, latest)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
