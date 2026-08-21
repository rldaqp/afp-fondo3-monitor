from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "analysis" / "profuturo_rolling90_vc_validation.json"
BLIND_OUT = ROOT / "analysis" / "profuturo_blind_chain_validation.csv"

CANDIDATE_WEIGHTS = [0.40, 0.50, 0.60]  # peso del modelo actual; resto = modelo sin NEM/FCX + QQQ
LOOKBACK_COMPLETED = 20
MIN_COMPLETED = 10
FIXED_WEIGHTS = [0.40, 0.50, 0.60]


def choose_weight(history: list[dict], origin_date: pd.Timestamp) -> tuple[float, int, dict]:
    eligible = [x for x in history if x["end_date"] < origin_date]
    eligible = sorted(eligible, key=lambda x: x["end_date"])[-LOOKBACK_COMPLETED:]
    n = len(eligible)
    if n < MIN_COMPLETED:
        return 0.50, n, {"0.4": None, "0.5": None, "0.6": None}

    scores = {}
    for w in CANDIDATE_WEIGHTS:
        errs = [abs(w * x["current"] + (1.0 - w) * x["alt"] - x["actual"]) for x in eligible]
        scores[f"{w:.1f}"] = float(np.mean(errs))
    # Desempate a favor de 50/50 para no introducir movimiento innecesario.
    best = min(CANDIDATE_WEIGHTS, key=lambda w: (scores[f"{w:.1f}"], abs(w - 0.50)))
    return float(best), n, scores


def summarize(origins: pd.DataFrame) -> dict:
    if origins.empty:
        return {"n_origins": 0}
    result = {
        "n_origins": int(len(origins)),
        "first_origin": origins.iloc[0]["origin_date"].strftime("%Y-%m-%d"),
        "last_origin": origins.iloc[-1]["origin_date"].strftime("%Y-%m-%d"),
        "models": {},
    }
    model_cols = {
        "current": "current",
        "alt": "alt",
        "w40_current_w60_alt": "w40",
        "w50_current_w50_alt": "w50",
        "w60_current_w40_alt": "w60",
        "adaptive": "adaptive",
    }
    for label, key in model_cols.items():
        result["models"][label] = {
            "endpoint_mae": float(origins[f"endpoint_abs_{key}"].mean()),
            "endpoint_median_abs": float(origins[f"endpoint_abs_{key}"].median()),
            "endpoint_bias": float(origins[f"endpoint_bias_{key}"].mean()),
            "path_mae": float(origins[f"path_mae_{key}"].mean()),
        }
    cur_ep = result["models"]["current"]["endpoint_mae"]
    cur_path = result["models"]["current"]["path_mae"]
    for label in ["w40_current_w60_alt", "w50_current_w50_alt", "w60_current_w40_alt", "adaptive"]:
        m = result["models"][label]
        m["endpoint_improvement_vs_current_pct"] = float((cur_ep - m["endpoint_mae"]) / cur_ep * 100.0)
        m["path_improvement_vs_current_pct"] = float((cur_path - m["path_mae"]) / cur_path * 100.0)

    counts = origins["adaptive_weight_current"].value_counts().sort_index()
    result["adaptive_weight_frequency"] = {
        f"{float(w):.1f}": {"count": int(c), "pct": float(c / len(origins) * 100.0)}
        for w, c in counts.items()
    }
    mature = origins.loc[origins["adaptive_history_n"] >= MIN_COMPLETED]
    result["adaptive_mature_origins"] = int(len(mature))
    if len(mature):
        result["adaptive_mature_endpoint_mae"] = float(mature["endpoint_abs_adaptive"].mean())
        result["adaptive_mature_path_mae"] = float(mature["path_mae_adaptive"].mean())
    return result


def main() -> None:
    if not BLIND_OUT.exists():
        raise RuntimeError(f"No existe {BLIND_OUT}")
    if not OUT.exists():
        raise RuntimeError(f"No existe {OUT}")

    blind = pd.read_csv(BLIND_OUT)
    blind["origin_date"] = pd.to_datetime(blind["origin_date"], errors="coerce")
    blind["fecha"] = pd.to_datetime(blind["fecha"], errors="coerce")
    required = ["horizon", "origin_date", "step", "fecha", "actual_vc", "current_pred_vc", "alt_pred_vc"]
    missing = [c for c in required if c not in blind.columns]
    if missing:
        raise RuntimeError(f"Faltan columnas: {missing}")
    blind = blind.dropna(subset=required).copy()

    all_origin_rows = []
    new_rows = []
    latest_selections = {}

    for horizon in sorted(int(x) for x in blind["horizon"].unique()):
        hdf = blind.loc[blind["horizon"] == horizon].sort_values(["origin_date", "step"]).copy()
        history: list[dict] = []
        groups = list(hdf.groupby("origin_date", sort=True))

        for origin_date, g in groups:
            g = g.sort_values("step").copy()
            end_date = pd.Timestamp(g.iloc[-1]["fecha"])
            w_adapt, hist_n, scores = choose_weight(history, pd.Timestamp(origin_date))
            g["w40_pred_vc"] = 0.40 * g["current_pred_vc"] + 0.60 * g["alt_pred_vc"]
            g["w50_pred_vc"] = 0.50 * g["current_pred_vc"] + 0.50 * g["alt_pred_vc"]
            g["w60_pred_vc"] = 0.60 * g["current_pred_vc"] + 0.40 * g["alt_pred_vc"]
            g["adaptive_pred_vc"] = w_adapt * g["current_pred_vc"] + (1.0 - w_adapt) * g["alt_pred_vc"]
            g["adaptive_weight_current"] = w_adapt
            g["adaptive_weight_alt"] = 1.0 - w_adapt
            g["adaptive_history_n"] = hist_n
            for key in ["current", "alt", "w40", "w50", "w60", "adaptive"]:
                pred_col = f"{key}_pred_vc"
                if key == "current": pred_col = "current_pred_vc"
                elif key == "alt": pred_col = "alt_pred_vc"
                g[f"{key}_abs_error_adaptive_test"] = (g[pred_col] - g["actual_vc"]).abs()

            endpoint = g.iloc[-1]
            actual_end = float(endpoint["actual_vc"])
            vals = {
                "current": float(endpoint["current_pred_vc"]),
                "alt": float(endpoint["alt_pred_vc"]),
                "w40": float(endpoint["w40_pred_vc"]),
                "w50": float(endpoint["w50_pred_vc"]),
                "w60": float(endpoint["w60_pred_vc"]),
                "adaptive": float(endpoint["adaptive_pred_vc"]),
            }
            row = {
                "horizon": horizon,
                "origin_date": pd.Timestamp(origin_date),
                "end_date": end_date,
                "adaptive_weight_current": w_adapt,
                "adaptive_weight_alt": 1.0 - w_adapt,
                "adaptive_history_n": hist_n,
                "selection_mae_w40": scores["0.4"],
                "selection_mae_w50": scores["0.5"],
                "selection_mae_w60": scores["0.6"],
            }
            for key, val in vals.items():
                row[f"endpoint_abs_{key}"] = abs(val - actual_end)
                row[f"endpoint_bias_{key}"] = val - actual_end
                row[f"path_mae_{key}"] = float(g[f"{key}_abs_error_adaptive_test"].mean())
            all_origin_rows.append(row)
            new_rows.append(g)

            history.append({
                "origin_date": pd.Timestamp(origin_date),
                "end_date": end_date,
                "current": vals["current"],
                "alt": vals["alt"],
                "actual": actual_end,
            })

        # Peso que se habría elegido al terminar el último VC real de este backtest.
        asof = pd.Timestamp(hdf["fecha"].max()) + pd.Timedelta(days=1)
        w_live, n_live, live_scores = choose_weight(history, asof)
        latest_selections[str(horizon)] = {
            "as_of": hdf["fecha"].max().strftime("%Y-%m-%d"),
            "weight_current": w_live,
            "weight_alt": 1.0 - w_live,
            "history_n": n_live,
            "recent20_endpoint_mae_by_weight": live_scores,
        }

    origins = pd.DataFrame(all_origin_rows).sort_values(["horizon", "origin_date"]).reset_index(drop=True)
    detailed = pd.concat(new_rows, ignore_index=True).sort_values(["horizon", "origin_date", "step"]).reset_index(drop=True)

    summary_all = {}
    summary_recent90 = {}
    for horizon in sorted(origins["horizon"].unique()):
        o = origins.loc[origins["horizon"] == horizon].sort_values("origin_date").reset_index(drop=True)
        summary_all[str(int(horizon))] = summarize(o)
        summary_recent90[str(int(horizon))] = summarize(o.tail(min(90, len(o))).reset_index(drop=True))

    payload = json.loads(OUT.read_text(encoding="utf-8"))
    payload["adaptive_weight_test"] = {
        "rule": {
            "candidate_weights_current": CANDIDATE_WEIGHTS,
            "alternative_weight_is_one_minus_current": True,
            "selection_metric": "MAE del endpoint de las ultimas 20 cadenas ciegas ya completadas del mismo horizonte",
            "no_leakage": "Solo se usan cadenas cuyo end_date es anterior al origin_date actual.",
            "minimum_completed_history": MIN_COMPLETED,
            "default_before_minimum": 0.50,
            "weight_held_fixed_inside_each_blind_path": True,
        },
        "summary_all_origins": summary_all,
        "summary_recent_90_origins": summary_recent90,
        "latest_selection_by_horizon": latest_selections,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    for c in ["origin_date", "fecha"]:
        detailed[c] = pd.to_datetime(detailed[c]).dt.strftime("%Y-%m-%d")
    detailed.to_csv(BLIND_OUT, index=False)

    print(json.dumps(payload["adaptive_weight_test"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
