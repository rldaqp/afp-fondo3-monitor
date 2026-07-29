from __future__ import annotations

import test_portfolio_regime as experiment
from portfolio_report_parser import parse_report_dynamic

experiment.parse_report = parse_report_dynamic

if __name__ == "__main__":
    experiment.main()
