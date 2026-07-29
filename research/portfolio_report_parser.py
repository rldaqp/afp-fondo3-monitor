from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import pandas as pd


def norm(value: object) -> str:
    if pd.isna(value):
        return ""
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text).strip().lower()


def row_text(frame: pd.DataFrame, row: int, cols: tuple[int, ...] = (0, 1, 2)) -> str:
    return " | ".join(norm(frame.iloc[row, col]) for col in cols if norm(frame.iloc[row, col]))


def find_row(
    frame: pd.DataFrame,
    needle: str,
    start: int = 0,
    end: int | None = None,
    cols: tuple[int, ...] = (0, 1, 2),
    optional: bool = False,
    exclude: tuple[str, ...] = (),
) -> int | None:
    target = norm(needle)
    excluded = tuple(norm(value) for value in exclude)
    stop = len(frame) if end is None else min(end, len(frame))
    for row in range(max(start, 0), stop):
        text = row_text(frame, row, cols)
        if target in text and not any(item in text for item in excluded):
            return row
    if optional:
        return None
    raise RuntimeError(
        f"No se encontró {needle!r} entre filas {start} y {stop}; "
        f"muestra: {[row_text(frame, i) for i in range(start, min(stop, start + 8))]}"
    )


def parse_report_dynamic(path: Path, month_end: pd.Timestamp) -> dict[str, object]:
    frame = pd.read_excel(path, sheet_name="Fondo3xIntru", header=None, engine="xlrd")
    if frame.shape[1] < 11:
        raise RuntimeError(f"Formato inesperado {path.name}: {frame.shape}")

    prof_header_row = find_row(frame, "Profuturo", cols=tuple(range(frame.shape[1])))
    assert prof_header_row is not None
    prof_monto_col = next(
        col
        for col in range(frame.shape[1])
        if "profuturo" in norm(frame.iloc[prof_header_row, col])
    )
    prof_pct_col = prof_monto_col + 1

    def pct(row: int | None) -> float:
        if row is None:
            return 0.0
        value = pd.to_numeric(pd.Series([frame.iloc[row, prof_pct_col]]), errors="coerce").iloc[0]
        if pd.isna(value):
            raise RuntimeError(
                f"Porcentaje Profuturo vacío en {path.name}, fila {row}, columna {prof_pct_col}: "
                f"{row_text(frame, row)}"
            )
        return float(value) / 100.0

    local = find_row(frame, "INVERSIONES LOCALES")
    foreign = find_row(frame, "INVERSIONES EN EL EXTERIOR", start=int(local) + 1)
    transit = find_row(frame, "OPERACIONES EN TRÁNSITO", start=int(foreign) + 1)
    total = find_row(frame, "TOTAL", start=int(transit) + 1)
    assert local is not None and foreign is not None and transit is not None and total is not None

    local_gov = find_row(frame, "1. Gobierno", start=local + 1, end=foreign)
    local_fin = find_row(frame, "2. Sistema Financiero", start=int(local_gov) + 1, end=foreign)
    local_nonfin = find_row(frame, "3. Empresas no Financieras", start=int(local_fin) + 1, end=foreign)
    local_admin = find_row(frame, "4. Administradoras de Fondos", start=int(local_nonfin) + 1, end=foreign)
    local_tit = find_row(frame, "5. Sociedades Titulizadoras", start=int(local_admin) + 1, end=foreign)

    local_fin_equity = find_row(
        frame,
        "Acciones y Valores representativos sobre Acciones",
        start=int(local_fin) + 1,
        end=int(local_nonfin),
    )
    local_nonfin_equity = find_row(
        frame,
        "Acciones y Valores representativos sobre Acciones",
        start=int(local_nonfin) + 1,
        end=int(local_admin),
    )
    local_etf = find_row(
        frame,
        "ETF del mercado local",
        start=int(local_admin) + 1,
        end=int(local_tit),
        optional=True,
    )
    local_alt_limit = find_row(
        frame,
        "Alternativo Extranjero",
        start=int(local_admin) + 1,
        end=int(local_tit),
        optional=True,
    )
    local_alt_fund = find_row(
        frame,
        "Fondo de Inversión Alternativo",
        start=int(local_admin) + 1,
        end=int(local_tit),
        optional=True,
    )

    foreign_gov = find_row(frame, "1. Gobierno", start=foreign + 1, end=transit)
    foreign_fin = find_row(frame, "2. Sistema Financiero", start=int(foreign_gov) + 1, end=transit)
    foreign_nonfin = find_row(frame, "3. Empresas no Financieras", start=int(foreign_fin) + 1, end=transit)
    foreign_admin = find_row(frame, "4. Administradoras de Fondos", start=int(foreign_nonfin) + 1, end=transit)

    foreign_nonfin_equity = find_row(
        frame,
        "Acciones y Valores representativos sobre Acciones",
        start=int(foreign_nonfin) + 1,
        end=int(foreign_admin),
        optional=True,
    )
    foreign_alt = find_row(
        frame,
        "Fondos Mutuos Alternativos del Extranjero",
        start=int(foreign_admin) + 1,
        end=transit,
        optional=True,
    )
    foreign_funds = find_row(
        frame,
        "Fondos Mutuos del Extranjero",
        start=int(foreign_admin) + 1,
        end=transit,
        optional=False,
        exclude=("alternativos",),
    )

    w_local_total = pct(local)
    w_local_government = pct(local_gov)
    w_local_fin_total = pct(local_fin)
    w_local_fin_equity = pct(local_fin_equity)
    w_local_nonfin_total = pct(local_nonfin)
    w_local_nonfin_equity = pct(local_nonfin_equity)
    w_local_fund_admin = pct(local_admin)
    w_local_etf = pct(local_etf)
    w_local_alt_limit = pct(local_alt_limit)
    w_local_alt_fund = pct(local_alt_fund)
    w_local_titulization = pct(local_tit)
    w_foreign_total = pct(foreign)
    w_foreign_government = pct(foreign_gov)
    w_foreign_fin_total = pct(foreign_fin)
    w_foreign_nonfin_total = pct(foreign_nonfin)
    w_foreign_nonfin_equity = pct(foreign_nonfin_equity)
    w_foreign_fund_admin = pct(foreign_admin)
    w_foreign_alt = pct(foreign_alt)
    w_foreign_funds = pct(foreign_funds)
    w_transit = pct(transit)

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
