from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "rolling90"
SBS_PATH = DATA / "sbs_profuturo_f3.csv"
CORRECTIONS_PATH = DATA / "sbs_reference_corrections.csv"


def main() -> None:
    if not SBS_PATH.exists():
        raise FileNotFoundError(f"No existe {SBS_PATH}")
    if not CORRECTIONS_PATH.exists():
        raise FileNotFoundError(f"No existe {CORRECTIONS_PATH}")

    sbs = pd.read_csv(SBS_PATH)
    corrections = pd.read_csv(CORRECTIONS_PATH)

    sbs["fecha"] = pd.to_datetime(sbs["fecha"], errors="coerce")
    sbs["valor_cuota"] = pd.to_numeric(sbs["valor_cuota"], errors="coerce")
    corrections["fecha"] = pd.to_datetime(corrections["fecha"], errors="coerce")
    corrections["valor_cuota"] = pd.to_numeric(corrections["valor_cuota"], errors="coerce")

    corrections = corrections.dropna(subset=["fecha", "valor_cuota"])
    before = sbs.set_index("fecha")["valor_cuota"]

    for _, row in corrections.iterrows():
        old = before.get(row["fecha"], None)
        print(
            f"SBS corrección {row['fecha']:%Y-%m-%d}: "
            f"antes={old} -> correcto={row['valor_cuota']:.7f}"
        )

    corrected = pd.concat(
        [sbs[["fecha", "valor_cuota"]], corrections[["fecha", "valor_cuota"]]],
        ignore_index=True,
    )
    corrected = (
        corrected.dropna(subset=["fecha", "valor_cuota"])
        .sort_values("fecha")
        .drop_duplicates("fecha", keep="last")
        .reset_index(drop=True)
    )

    # Controles explícitos de las fechas recuperadas y de puntos posteriores.
    expected = {
        pd.Timestamp("2026-07-01"): 70.9226332,
        pd.Timestamp("2026-07-02"): 70.3358541,
        pd.Timestamp("2026-07-03"): 70.3944744,
        pd.Timestamp("2026-07-06"): 71.3369613,
        pd.Timestamp("2026-07-07"): 69.9352638,
        pd.Timestamp("2026-07-08"): 69.8131004,
        pd.Timestamp("2026-07-09"): 70.9792394,
        pd.Timestamp("2026-07-10"): 71.0624925,
        pd.Timestamp("2026-07-15"): 69.9080824,
        pd.Timestamp("2026-07-20"): 68.0638500,
    }
    indexed = corrected.set_index("fecha")["valor_cuota"]
    for fecha, value in expected.items():
        if fecha not in indexed.index:
            raise AssertionError(f"Falta SBS {fecha:%Y-%m-%d}")
        actual = float(indexed.loc[fecha])
        if abs(actual - value) > 1e-9:
            raise AssertionError(
                f"SBS {fecha:%Y-%m-%d}: {actual:.7f} != {value:.7f}"
            )

    out = corrected.copy()
    out["fecha"] = out["fecha"].dt.strftime("%Y-%m-%d")
    out.to_csv(SBS_PATH, index=False, encoding="utf-8")
    print("SBS corregida y validada con controles de continuidad de julio.")


if __name__ == "__main__":
    main()
