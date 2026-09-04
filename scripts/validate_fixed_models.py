"""Production validation: equations, official SBS and cross-file consistency."""
import csv
import json
from pathlib import Path

from fixed_model_contract import FACTORS, close, validate_history, validate_snapshot
from reconcile_fixed_history import read_official
from build_fixed_levels_returns_monitor import LEVEL_COEFF, RETURN_COEFF

ROOT = Path(__file__).resolve().parents[1]


def main():
    data = ROOT / "public/data"
    base = json.loads((data / "fixed_models_2026.json").read_text(encoding="utf-8"))
    snap = json.loads((data / "fixed_models_intraday.json").read_text(encoding="utf-8"))
    official = read_official()
    validate_history(base, official)
    validate_snapshot(base, snap)
    assert base["models"]["niveles"]["coefficients"] == LEVEL_COEFF
    assert base["models"]["retornos"]["coefficients"] == RETURN_COEFF
    assert len(base["rows"]) >= 100
    assert base["training"]["n"] == 30
    close(base["training"]["levels_r2"], 0.9839967207688474, "R2 niveles", 1e-12)
    close(base["training"]["returns_r2"], 0.9518032304214648, "R2 retornos", 1e-12)
    assert base["training"]["sbs_corrections"] == {"2026-08-14": 70.8740985, "2026-08-17": 71.5395979}
    assert base["model_version"] == "v2-sbs-corrected-20260831"
    by = {r["fecha"]: r for r in base["rows"]}
    for d, value in {"2026-08-28": 454.70, "2026-08-31": 450.67, "2026-09-01": 446.70, "2026-09-02": 455.17}.items():
        close(by[d]["SPBLSCUP"], value, (d, "SPBLSCUP auditado"), 0.005)
    for ticker, value in {"SPY": 769.35, "EEM": 67.14, "MCHI": 55.23, "QQQ": 716.43}.items():
        close(by["2026-08-28"][ticker], value, ("2026-08-28", ticker), 0.01)
    # Predictions intentionally are NOT constant: a new SBS changes their base.
    status = json.loads((data / "sbs_sync_status.json").read_text(encoding="utf-8"))
    assert status["latest_remote_date"] <= base["latest"]["latest_sbs_date"]
    close(official[status["latest_remote_date"]], status["latest_remote_vc_profuturo_f3"], "SBS remoto publicado")
    series = json.loads((data / "series.json").read_text(encoding="utf-8"))
    actual = {r["fecha"]: r["vc"] for r in series if r.get("fuente") == "SBS OFICIAL"}
    close(actual[max(official)], official[max(official)], "Gráfico SBS")
    with (data / "fixed_models_2026.csv").open(encoding="utf-8") as f:
        csv_rows = list(csv.DictReader(f))
    assert [r["fecha"] for r in csv_rows] == [r["fecha"] for r in base["rows"]]
    for saved, row in zip(csv_rows, base["rows"]):
        for field in [*FACTORS, "vc_sbs", "vc_niveles", "vc_retornos", "ret_vc_estimado"]:
            if row[field] is not None:
                close(float(saved[field]), row[field], ("CSV/JSON", row["fecha"], field))
            else:
                assert saved[field] == ""
    if snap["close_consolidated"]:
        row = by[snap["signal_date"]]
        for t in snap["tickers"]:
            close(row[t["ticker"]], t["price_current"], ("histórico/snapshot", t["ticker"]))
        for model in ("niveles", "retornos"):
            close(row["vc_"+model], snap["models"][model]["vc_intraday"], ("histórico/snapshot", model))
    health = json.loads((data / "model_health.json").read_text(encoding="utf-8"))
    assert health["policy"]["minimum_change_n"] == 30
    assert set(health["models"]) == {"niveles", "retornos"}
    print("VALIDADO: SBS, ecuaciones, fechas únicas, precios, CSV/JSON y snapshot", base["latest"])


if __name__ == "__main__":
    main()
