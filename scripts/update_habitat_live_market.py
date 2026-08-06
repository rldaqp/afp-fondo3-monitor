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
    HABITAT_LIVE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
