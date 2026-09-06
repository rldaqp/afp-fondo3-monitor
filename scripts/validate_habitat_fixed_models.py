from __future__ import annotations

import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "public" / "habitat" / "data" / "fixed_models_2026.json"
LIVE = ROOT / "public" / "habitat" / "data" / "fixed_models_intraday.json"
FACTORS = ["SPY", "EEM", "MCHI", "QQQ", "SPBLSCUP"]


def finite(value) -> bool:
    try:
        return value is not None and math.isfinite(float(value))
    except Exception:
        return False


def main() -> None:
    if not BASE.exists():
        raise SystemExit(f"Falta {BASE}")
    base = json.loads(BASE.read_text(encoding="utf-8"))
    assert base.get("fund") == "HÁBITAT Fondo 3"
    assert base.get("factors") == FACTORS
    assert base.get("training", {}).get("start") == "2026-07-07"
    assert base.get("training", {}).get("end") == "2026-08-17"
    assert base.get("validation_start") == "2026-08-18"
    assert int(base["training"]["n_levels"]) > 20
    assert int(base["training"]["n_returns"]) > 20
    assert finite(base["latest"]["latest_sbs_vc"])

    rows = base.get("rows", [])
    dates = [str(r.get("fecha", ""))[:10] for r in rows]
    assert len(rows) == len(set(dates)), "Fechas duplicadas en base Hábitat"
    assert dates == sorted(dates), "Fechas no ordenadas en base Hábitat"
    for key in ("niveles", "retornos"):
        model = base["models"][key]
        coeff = model["coefficients"]
        assert set(coeff) == {"intercept", *FACTORS}
        assert all(finite(v) for v in coeff.values())
        assert finite(model["r2"])
        assert finite(model["adj_r2"])
        assert finite(model["stderr"])

    if LIVE.exists():
        live = json.loads(LIVE.read_text(encoding="utf-8"))
        assert live.get("fund") == "HÁBITAT Fondo 3"
        signal_date = str(live.get("signal_date", ""))[:10]
        assert len(signal_date) == 10
        tickers = live.get("tickers", [])
        assert [r.get("ticker") for r in tickers] == FACTORS
        assert len({r.get("ticker") for r in tickers}) == 5
        for row in tickers:
            assert finite(row.get("price_previous"))
            assert finite(row.get("price_current"))
            assert finite(row.get("return"))
            if row.get("fresh") is True:
                assert str(row.get("timestamp", ""))[:10] == signal_date, (
                    f"{row.get('ticker')} fresh con fecha distinta a signal_date"
                )
        assert finite(live["models"]["niveles"]["vc_intraday"])
        assert finite(live["models"]["retornos"]["vc_intraday"])

    print(
        "Hábitat niveles/retornos validado:",
        base["latest"],
        base["metrics"]["validation"],
    )


if __name__ == "__main__":
    main()
