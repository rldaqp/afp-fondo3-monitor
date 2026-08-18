from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise RuntimeError(f"No se encontró marcador para {label}")
    return text.replace(old, new, 1)


def patch_monitor() -> None:
    path = ROOT / ".github" / "workflows" / "update-monitor.yml"
    text = path.read_text(encoding="utf-8")

    text = replace_once(
        text,
        '      - "scripts/build_model_insights.py"\n',
        '      - "scripts/build_model_insights.py"\n      - "scripts/build_qqq_incremental_challenger.py"\n      - "scripts/postprocess_qqq_incremental_ui.py"\n',
        "paths monitor",
    )
    text = replace_once(
        text,
        '          git restore --source=HEAD -- public/data/live_market.json || true\n          python scripts/build_operation_series.py\n',
        '          git restore --source=HEAD -- public/data/live_market.json || true\n          python scripts/build_qqq_incremental_challenger.py\n          python scripts/build_operation_series.py\n',
        "build challenger monitor",
    )
    text = replace_once(
        text,
        '          python scripts/postprocess_investment_signal_1pct.py\n',
        '          python scripts/postprocess_investment_signal_1pct.py\n          python scripts/postprocess_qqq_incremental_ui.py\n',
        "UI challenger monitor",
    )
    text = replace_once(
        text,
        '          test -s public/data/model_insights.json\n',
        '          test -s public/data/model_insights.json\n          test -s public/data/qqq_incremental_challenger.json\n',
        "test challenger monitor",
    )
    text = replace_once(
        text,
        '          grep -q "Confianza y calidad del modelo" public/index.html\n',
        '          grep -q "Confianza y calidad del modelo" public/index.html\n          grep -q "QQQ INCREMENTAL · CHALLENGER" public/index.html\n          ! grep -q "Challenger Huber · paralelo" public/index.html\n',
        "grep challenger monitor",
    )
    text = replace_once(
        text,
        '          vc_accuracy = json.loads(Path("public/data/vc_accuracy_1pct.json").read_text(encoding="utf-8"))\n',
        '          vc_accuracy = json.loads(Path("public/data/vc_accuracy_1pct.json").read_text(encoding="utf-8"))\n          qqq = json.loads(Path("public/data/qqq_incremental_challenger.json").read_text(encoding="utf-8"))\n',
        "load challenger validation",
    )
    text = replace_once(
        text,
        '          assert 0 <= float(vc_accuracy["accuracy"]) <= 1\n',
        '          assert 0 <= float(vc_accuracy["accuracy"]) <= 1\n          assert qqq["challenger"]["signal"] in {"SUBE", "NEUTRO", "BAJA"}\n          assert float(qqq["challenger"]["vc_estimated"]) > 0\n          assert float(qqq["official"]["vc_estimated"]) > 0\n          assert int(qqq["training"]["n"]) == 90\n',
        "assert challenger validation",
    )
    path.write_text(text, encoding="utf-8")


def patch_live() -> None:
    path = ROOT / ".github" / "workflows" / "update-live-market.yml"
    text = path.read_text(encoding="utf-8")

    text = replace_once(
        text,
        '      - "scripts/update_live_market_hybrid.py"\n',
        '      - "scripts/update_live_market_hybrid.py"\n      - "scripts/build_qqq_incremental_challenger.py"\n',
        "paths live",
    )
    text = replace_once(
        text,
        '          print("Profuturo cierre coherente:", signal_date, live.get("signal"), live.get("return_estimated"), source)\n          PY\n\n          python - <<\'PY\'\n',
        '          print("Profuturo cierre coherente:", signal_date, live.get("signal"), live.get("return_estimated"), source)\n          PY\n\n          python scripts/build_qqq_incremental_challenger.py --live-only\n\n          python - <<\'PY\'\n',
        "build challenger live",
    )
    text = replace_once(
        text,
        '          git add public/data/live_market.json public/habitat/data/live_market.json public/habitat/data/latest.json public/habitat/data/signals.json public/habitat/data/series.json public/habitat/data/operation_series.json public/habitat/data/model_insights.json\n',
        '          git add public/data/live_market.json public/data/qqq_incremental_challenger.json data/rolling90/qqq_incremental_shadow.csv public/habitat/data/live_market.json public/habitat/data/latest.json public/habitat/data/signals.json public/habitat/data/series.json public/habitat/data/operation_series.json public/habitat/data/model_insights.json\n',
        "stage challenger live",
    )
    text = replace_once(
        text,
        '          cp public/data/live_market.json "$tmp/gh-pages/data/live_market.json"\n',
        '          cp public/data/live_market.json "$tmp/gh-pages/data/live_market.json"\n          cp public/data/qqq_incremental_challenger.json "$tmp/gh-pages/data/qqq_incremental_challenger.json"\n',
        "copy challenger gh-pages",
    )
    text = replace_once(
        text,
        '          git add data/live_market.json habitat/data/live_market.json\n',
        '          git add data/live_market.json data/qqq_incremental_challenger.json habitat/data/live_market.json\n',
        "stage challenger gh-pages",
    )
    path.write_text(text, encoding="utf-8")


def main() -> None:
    patch_monitor()
    patch_live()
    print("Workflows integrados con QQQ incremental.")


if __name__ == "__main__":
    main()
