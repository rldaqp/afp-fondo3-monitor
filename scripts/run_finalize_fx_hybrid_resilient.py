from __future__ import annotations

import json

import pandas as pd

import finalize_fx_hybrid as hybrid


_original_load_bcrp = hybrid.v5.parity.engine.load_bcrp


def _load_bcrp_resilient() -> pd.DataFrame:
    """Usa BCRP cuando responde y, si devuelve contenido inválido, conserva el histórico BCRP ya guardado.

    No inventa un tipo de cambio nuevo: el respaldo sale únicamente de USD_PEN ya persistido
    en data/rolling90/markets.csv. Las fechas pendientes siguen usando PEN=X provisional
    mediante la lógica híbrida existente.
    """
    try:
        return _original_load_bcrp()
    except Exception as exc:
        saved = hybrid.v5.parity.engine.read_saved(hybrid.v5.parity.DATA / "markets.csv")
        if saved.empty or "USD_PEN" not in saved.columns:
            raise
        fallback = saved[["fecha", "USD_PEN"]].copy()
        fallback["fecha"] = pd.to_datetime(fallback["fecha"], errors="coerce")
        fallback["USD_PEN"] = pd.to_numeric(fallback["USD_PEN"], errors="coerce")
        fallback = (
            fallback.dropna(subset=["fecha", "USD_PEN"])
            .sort_values("fecha")
            .drop_duplicates("fecha", keep="last")
            .reset_index(drop=True)
        )
        if fallback.empty:
            raise
        print(
            "BCRP temporalmente inválido; se usa histórico BCRP ya guardado hasta "
            f"{fallback['fecha'].max():%Y-%m-%d} ({type(exc).__name__}: {exc})"
        )
        return fallback


def main() -> None:
    hybrid.v5.parity.engine.load_bcrp = _load_bcrp_resilient
    hybrid._prepare_saved_markets_for_eem()
    hybrid.v5.main()

    latest = json.loads(hybrid.v5.LATEST_PATH.read_text(encoding="utf-8"))
    latest["live_engine"] = "INDEPENDIENTE: update_live_market_hybrid.py"

    markets_check = hybrid.v5.parity.engine.read_saved(hybrid.v5.parity.DATA / "markets.csv")
    markets_check["fecha"] = pd.to_datetime(markets_check["fecha"], errors="coerce")
    core = ["SPY", "NEM", "FCX", "EPU", "MCHI"]
    recent_core = markets_check.dropna(subset=core).sort_values("fecha").tail(5)
    if recent_core.empty:
        raise RuntimeError("No hay sesiones recientes de los cinco activos base para validar EEM")

    missing_eem = recent_core.loc[recent_core["EEM"].isna(), "fecha"]
    if not missing_eem.empty:
        dates = ", ".join(pd.Timestamp(x).strftime("%Y-%m-%d") for x in missing_eem)
        raise RuntimeError(f"EEM sigue faltando en sesiones ya cerradas: {dates}")

    expected_market_date = pd.Timestamp(recent_core.iloc[-1]["fecha"]).normalize()
    published_market_date = pd.Timestamp(latest["latest_market_date"]).normalize()
    if published_market_date != expected_market_date:
        raise RuntimeError(
            "Último mercado inconsistente: "
            f"latest.json={published_market_date:%Y-%m-%d}, "
            f"mercados={expected_market_date:%Y-%m-%d}"
        )

    if expected_market_date > pd.Timestamp(latest["latest_sbs_date"]).normalize():
        pending_check = hybrid.v5.parity.engine.read_saved(hybrid.v5.PENDING_PATH)
        pending_check["fecha"] = pd.to_datetime(pending_check["fecha"], errors="coerce")
        if expected_market_date not in set(pending_check["fecha"].dropna().dt.normalize()):
            raise RuntimeError(
                f"La sesión {expected_market_date:%Y-%m-%d} existe pero no fue estimada por el OLS"
            )

    hybrid.v5.LATEST_PATH.write_text(
        json.dumps(latest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Último mercado validado: {expected_market_date:%Y-%m-%d}")


if __name__ == "__main__":
    main()
