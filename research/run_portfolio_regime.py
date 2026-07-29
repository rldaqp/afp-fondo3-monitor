from __future__ import annotations

import pandas as pd

import test_portfolio_regime as experiment
from portfolio_report_parser import parse_report_dynamic


def build_weights_2025_forward() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for month_end in experiment.month_iter("2025-01-31", "2026-06-30"):
        path = experiment.download_report(month_end)
        rows.append(parse_report_dynamic(path, month_end))
    weights = pd.DataFrame(rows)
    weights["report_month"] = pd.to_datetime(weights["report_month"])
    weights["available_date"] = pd.to_datetime(weights["available_date"])
    return weights.sort_values("available_date").reset_index(drop=True)


experiment.parse_report = parse_report_dynamic
experiment.build_weights = build_weights_2025_forward

if __name__ == "__main__":
    experiment.main()
