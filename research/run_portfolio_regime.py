from __future__ import annotations

import pandas as pd

import portfolio_report_parser as parser
import test_portfolio_regime as experiment


def row_text_all_labels(
    frame: pd.DataFrame,
    row: int,
    cols: tuple[int, ...] = (0, 1, 2, 3),
) -> str:
    return " | ".join(
        parser.norm(frame.iloc[row, col])
        for col in cols
        if col < frame.shape[1] and parser.norm(frame.iloc[row, col])
    )


def find_row_all_labels(
    frame: pd.DataFrame,
    needle: str,
    start: int = 0,
    end: int | None = None,
    cols: tuple[int, ...] = (0, 1, 2, 3),
    optional: bool = False,
    exclude: tuple[str, ...] = (),
) -> int | None:
    target = parser.norm(needle)
    excluded = tuple(parser.norm(value) for value in exclude)
    stop = len(frame) if end is None else min(end, len(frame))
    for row in range(max(start, 0), stop):
        text = row_text_all_labels(frame, row, cols)
        if target in text and not any(item in text for item in excluded):
            return row
    if optional:
        return None
    raise RuntimeError(
        f"No se encontró {needle!r} entre filas {start} y {stop}; "
        f"muestra: {[row_text_all_labels(frame, i) for i in range(start, min(stop, start + 8))]}"
    )


parser.row_text = row_text_all_labels
parser.find_row = find_row_all_labels


def build_weights_2025_forward() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for month_end in experiment.month_iter("2025-01-31", "2026-06-30"):
        path = experiment.download_report(month_end)
        rows.append(parser.parse_report_dynamic(path, month_end))
    weights = pd.DataFrame(rows)
    weights["report_month"] = pd.to_datetime(weights["report_month"])
    weights["available_date"] = pd.to_datetime(weights["available_date"])
    return weights.sort_values("available_date").reset_index(drop=True)


experiment.parse_report = parser.parse_report_dynamic
experiment.build_weights = build_weights_2025_forward

if __name__ == "__main__":
    experiment.main()
