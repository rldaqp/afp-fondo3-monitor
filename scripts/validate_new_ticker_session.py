from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
LIVE = ROOT / "public" / "data" / "live_market.json"
ALT_LIVE = ROOT / "data" / "analysis" / "googlefinance_alt_rolling30_live_returns.csv"
WANTED = [".INX", "CPER", "EEM", "NDX", "SPBLSCUP"]


def finite(v) -> bool:
    try:
        return v is not None and np.isfinite(float(v))
    except Exception:
        return False


def main() -> None:
    live = json.loads(LIVE.read_text(encoding="utf-8"))
    signal_date = str(live.get("signal_date", ""))[:10]
    assets = {str(x.get("serie")): x for x in live.get("experimental_assets", [])}
    core = {str(x.get("serie")): x for x in live.get("assets", [])}

    problems: list[str] = []
    for name in WANTED:
        row = assets.get(name)
        if row is None:
            problems.append(f"{name}: ausente")
            continue
        if row.get("validado_modelo") is False:
            problems.append(f"{name}: marcado no validado")
            continue
        ret = row.get("retorno_modelo") if row.get("retorno_modelo") is not None else row.get("retorno")
        if not finite(ret):
            problems.append(f"{name}: retorno no finito")

    # Control cruzado específico para el índice Perú. EPU no reemplaza a
    # SPBLSCUP: solo sirve como alarma de integridad. Una discrepancia >5 puntos
    # porcentuales en una sola sesión obliga a dejar Modelo B pendiente antes que
    # alimentar un número posiblemente extraído de otra tarjeta de Google.
    sp = assets.get("SPBLSCUP")
    epu = core.get("EPU")
    if sp and epu:
        sp_ret = sp.get("retorno_modelo") if sp.get("retorno_modelo") is not None else sp.get("retorno")
        epu_ret = epu.get("retorno_modelo") if epu.get("retorno_modelo") is not None else epu.get("retorno")
        if finite(sp_ret) and finite(epu_ret) and abs(float(sp_ret) - float(epu_ret)) > 0.05:
            sp["validado_modelo"] = False
            sp["usado_modelo"] = False
            sp["retorno_modelo"] = None
            sp["retorno"] = None
            sp["estado"] = (
                f"CIERRE BLOQUEADO · SPBLSCUP difiere {abs(float(sp_ret)-float(epu_ret))*100:.2f} pp de EPU; "
                "requiere fuente exacta corroborada"
            )
            problems.append("SPBLSCUP: divergencia >5 pp frente a EPU")

    # Si hay cualquier problema, borra del incremental la fila de HOY para que
    # el constructor resiliente no reutilice un cierre ya persistido pero luego
    # invalidado. El histórico previo queda intacto.
    if problems and ALT_LIVE.exists() and signal_date:
        df = pd.read_csv(ALT_LIVE)
        if "fecha" in df.columns:
            dates = pd.to_datetime(df["fecha"], errors="coerce").dt.strftime("%Y-%m-%d")
            before = len(df)
            df = df.loc[dates.ne(signal_date)].copy()
            if len(df) != before:
                df.to_csv(ALT_LIVE, index=False)
                print(f"Fila incremental {signal_date} retirada por validación: {problems}")

    live["new_ticker_validation"] = {
        "signal_date": signal_date,
        "status": "OK" if not problems else "PENDIENTE/BLOQUEADO",
        "problems": problems,
        "rule": "No se usa un cierre dudoso para Modelo B; se conserva la última sesión completa.",
    }
    LIVE.write_text(json.dumps(live, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(live["new_ticker_validation"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
