"""Shared invariants, not frozen predicted outputs: new official SBS may re-anchor returns."""
from __future__ import annotations

import hashlib
import json
import math

FACTORS = ["SPY", "EEM", "MCHI", "QQQ", "SPBLSCUP"]


def finite(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def close(a, b, label, tolerance=1e-8):
    assert finite(a) and finite(b) and abs(a-b) <= tolerance, (label, a, b)


def history_revision(base):
    fields = ["fecha", *FACTORS, "vc_sbs", "vc_niveles", "ret_vc_estimado", "vc_retornos"]
    data = {"models": base["models"], "rows": [{k: r.get(k) for k in fields} for r in base["rows"]]}
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def validate_history(base, official=None):
    rows = base["rows"]
    dates = [r["fecha"] for r in rows]
    assert dates == sorted(set(dates)), "Fechas repetidas o desordenadas"
    lc, rc = (base["models"][k]["coefficients"] for k in ("niveles", "retornos"))
    for i, row in enumerate(rows):
        if official is not None:
            expected = official.get(row["fecha"])
            if expected is not None:
                close(row.get("vc_sbs"), expected, (row["fecha"], "SBS"))
            else:
                assert row.get("vc_sbs") is None, (row["fecha"], "SBS sin fuente oficial")
        complete = all(finite(row.get(f)) and row[f] > 0 for f in FACTORS)
        if not complete:
            assert row.get("vc_niveles") is None, (row["fecha"], "Niveles con factores incompletos")
            continue
        expected_level = lc["intercept"] + sum(lc[f]*row[f] for f in FACTORS)
        close(row["vc_niveles"], expected_level, (row["fecha"], "niveles"))
        if i and all(finite(rows[i-1].get(f)) and rows[i-1][f] > 0 for f in FACTORS):
            prev = rows[i-1]
            expected_return = rc["intercept"] + sum(rc[f]*(row[f]/prev[f]-1) for f in FACTORS)
            close(row["ret_vc_estimado"], expected_return, (row["fecha"], "retorno"))
            anchor = prev.get("vc_sbs") if finite(prev.get("vc_sbs")) else prev.get("vc_retornos")
            if finite(anchor):
                close(row["vc_retornos"], anchor*(1+expected_return), (row["fecha"], "base SBS/estimada"))
    complete = [r for r in rows if all(finite(r.get(f)) and r[f] > 0 for f in FACTORS)]
    assert complete, "Histórico sin cierres completos"
    last = complete[-1]
    assert base["latest"]["market_date"] == last["fecha"]
    for field in ("vc_niveles", "vc_retornos", "ret_vc_estimado"):
        close(base["latest"][field], last[field], ("latest", field))
    official = official if official is not None else {r["fecha"]: r["vc_sbs"] for r in rows if finite(r.get("vc_sbs"))}
    latest_date = max(official)
    assert base["latest"]["latest_sbs_date"] == latest_date, "Último SBS desactualizado"
    close(base["latest"]["latest_sbs_vc"], official[latest_date], "Último VC SBS")
    if "data_revision" in base:
        assert base["data_revision"] == history_revision(base), "Revisión de histórico inválida"


def validate_snapshot(base, snap):
    from datetime import datetime
    import exchange_calendars as xcals
    tickers = snap["tickers"]
    assert len(tickers) == 5 and {t["ticker"] for t in tickers} == set(FACTORS), "Factores repetidos o faltantes"
    target = snap["signal_date"]
    prior = [r for r in base["rows"] if r["fecha"] < target][-1]
    calendar = xcals.get_calendar("XNYS")
    assert prior["fecha"] == calendar.previous_session(target).date().isoformat(), "Falta la rueda inmediatamente anterior"
    from fixed_market_quotes import session_context
    ctx = session_context(datetime.fromisoformat(snap["generated_at_ny"]))
    assert target == ctx["date"] and snap["market_open"] == ctx["market_open"], "Sesión/mercado incoherentes"
    assert snap["session_close_ny"] == ctx["close"].isoformat()
    lc, rc = (base["models"][k]["coefficients"] for k in ("niveles", "retornos"))
    level, ret = lc["intercept"], rc["intercept"]
    for t in tickers:
        f = t["ticker"]
        assert finite(t["price_current"]) and t["price_current"] > 0
        close(t["price_previous"], prior[f], (f, "cierre previo"))
        assert t["previous_close_date"] == prior["fecha"] < target
        close(t["return"], t["price_current"]/t["price_previous"]-1, (f, "retorno"))
        close(t["level_contribution"], lc[f]*t["price_current"], (f, "aporte niveles"))
        close(t["return_contribution"], rc[f]*t["return"], (f, "aporte retornos"))
        level += t["level_contribution"]
        ret += t["return_contribution"]
        if t["fresh"]:
            assert t["timestamp"] == target, (f, "fecha no actual")
            assert t.get("quote_timestamp"), (f, "hora propia ausente")
            if not snap["market_open"]:
                assert t.get("close_confirmed"), (f, "barra pre-cierre")
        if t.get("close_confirmed"):
            stamp = datetime.fromisoformat(t["quote_timestamp"])
            assert stamp.date().isoformat() == target
            assert datetime.fromisoformat(snap["session_close_ny"]) <= stamp <= datetime.fromisoformat(snap["generated_at_ny"])
    close(snap["models"]["niveles"]["vc_intraday"], level, "Niveles snapshot")
    close(snap["models"]["retornos"]["return_intraday"], ret, "Retorno snapshot")
    anchor = prior.get("vc_sbs") if finite(prior.get("vc_sbs")) else prior["vc_retornos"]
    close(snap["models"]["retornos"]["base_vc"], anchor, "Base snapshot")
    close(snap["models"]["retornos"]["vc_intraday"], anchor*(1+ret), "VC retornos snapshot")
    assert level > 0 and anchor*(1+ret) > 0
    for model in ("niveles", "retornos"):
        assert snap["models"][model]["equation"] == base["models"][model]["equation"]
    for field, contribution in (("level_weight_abs_pct", "level_contribution"), ("return_weight_abs_pct", "return_contribution")):
        total = sum(abs(t[contribution]) for t in tickers)
        for t in tickers:
            if total:
                close(t[field], abs(t[contribution])/total*100, (t["ticker"], field))
            else:
                assert t[field] is None
    assert snap["fresh_factors"] == sum(t["fresh"] and t["timestamp"] == target for t in tickers)
    assert snap["total_factors"] == 5
    mode = ("INTRADÍA" if snap["fresh_factors"] == 5 else "INTRADÍA PARCIAL") if snap["market_open"] else "CIERRE / ÚLTIMO SNAPSHOT"
    assert snap["mode"] == mode
    consolidated = not snap["market_open"] and snap["fresh_factors"] == 5 and all(t.get("close_confirmed") for t in tickers)
    assert snap["close_consolidated"] == consolidated
    assert snap["base_revision"] == history_revision(base), "Snapshot calculado con otra base SBS/histórica"
    assert snap["latest_sbs_date"] == base["latest"]["latest_sbs_date"]
    close(snap["latest_sbs_vc"], base["latest"]["latest_sbs_vc"], "SBS snapshot")


def recalculate(base, official):
    rows = base["rows"]
    assert [r["fecha"] for r in rows] == sorted({r["fecha"] for r in rows})
    lc, rc = (base["models"][k]["coefficients"] for k in ("niveles", "retornos"))
    for i, row in enumerate(rows):
        row["vc_sbs"] = official.get(row["fecha"])
        row["vc_niveles"] = (lc["intercept"] + sum(lc[f]*row[f] for f in FACTORS)
                             if all(finite(row.get(f)) and row[f] > 0 for f in FACTORS) else None)
        row["ret_vc_estimado"] = row["vc_retornos"] = None
        if i and all(finite(r.get(f)) and r[f] > 0 for r in (row, rows[i-1]) for f in FACTORS):
            prev = rows[i-1]
            row["ret_vc_estimado"] = rc["intercept"] + sum(rc[f]*(row[f]/prev[f]-1) for f in FACTORS)
            anchor = prev.get("vc_sbs") if finite(prev.get("vc_sbs")) else prev.get("vc_retornos")
            if finite(anchor):
                row["vc_retornos"] = anchor*(1+row["ret_vc_estimado"])
        for model in ("niveles", "retornos"):
            value = row.get("vc_"+model)
            row["error_"+model+"_pct"] = (value/row["vc_sbs"]-1)*100 if finite(value) and finite(row["vc_sbs"]) else None
        row["fase"] = ("RETROSPECTIVO" if row["fecha"] < base["training"]["start"] else
                       "ENTRENAMIENTO" if row["fecha"] <= base["training"]["end"] else
                       "VALIDACIÓN" if finite(row["vc_sbs"]) else "PROYECCIÓN")
    last = [r for r in rows if all(finite(r.get(f)) and r[f] > 0 for f in FACTORS)][-1]
    latest_sbs = max(official)
    base["latest"].update({"market_date": last["fecha"], **{k: last[k] for k in ("vc_niveles", "vc_retornos", "ret_vc_estimado")},
                           "latest_sbs_date": latest_sbs, "latest_sbs_vc": official[latest_sbs]})
    for name, select in (("validation_from_2026_08_18", lambda r: r["fecha"] > base["training"]["end"]),
                         ("retrospective_before_2026_07_07", lambda r: r["fecha"] < base["training"]["start"])):
        for model in ("niveles", "retornos"):
            errors = [r["error_"+model+"_pct"] for r in rows if select(r) and finite(r["error_"+model+"_pct"])]
            base["metrics"][name][model] = {"n": len(errors), "mae_pct": sum(map(abs, errors))/len(errors) if errors else None,
                                          "rmse_pct": math.sqrt(sum(e*e for e in errors)/len(errors)) if errors else None}
    base["data_revision"] = history_revision(base)
    validate_history(base, official)
    return base
