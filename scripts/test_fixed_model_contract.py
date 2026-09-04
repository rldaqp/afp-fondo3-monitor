import copy
import json
import unittest
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from build_fixed_models_intraday import build_snapshot, quote_record
from fixed_market_quotes import google_html_quote, session_context, visible_google_stamp, yahoo_chart_quote
from fixed_model_contract import FACTORS, history_revision, recalculate, validate_history, validate_snapshot
from reconcile_fixed_history import main as reconcile_files, write_rows

ROOT = Path(__file__).resolve().parents[1]
NY = ZoneInfo("America/New_York")
NOW = datetime(2026, 9, 3, 18, 30, tzinfo=NY)
PRICES = {"SPY": 773.17, "EEM": 67.47, "MCHI": 54.37, "QQQ": 717.67, "SPBLSCUP": 455.91}


def fixture():
    base = json.loads((ROOT / "public/data/fixed_models_2026.json").read_text(encoding="utf-8"))
    base["rows"] = [r for r in base["rows"] if r["fecha"] <= "2026-09-02"]
    official = {r["fecha"]: r["vc_sbs"] for r in base["rows"] if r.get("vc_sbs") is not None and r["fecha"] < "2026-09-01"}
    recalculate(base, official)
    return base, official


def provider(ticker, now, baseline):
    stamp = datetime(2026, 9, 3, 16, 0, tzinfo=NY)
    return quote_record(ticker, PRICES[ticker], stamp, True, baseline, now, "TEST")


class ModelTests(unittest.TestCase):
    def test_new_sbs_reanchors_without_freezing_prediction(self):
        base, official = fixture()
        old = base["rows"][-1]["vc_retornos"]
        levels = base["rows"][-1]["vc_niveles"]
        official["2026-09-01"] = 70.8600385
        recalculate(base, official)
        self.assertNotAlmostEqual(old, base["rows"][-1]["vc_retornos"])
        self.assertAlmostEqual(base["rows"][-1]["vc_retornos"], 71.38604717565835)
        self.assertEqual(base["rows"][-1]["vc_niveles"], levels)
        self.assertEqual(base["latest"]["latest_sbs_date"], "2026-09-01")
        validate_history(base, official)

    def test_later_sbs_reanchors_again(self):
        base, official = fixture()
        official["2026-09-01"] = 70.8600385
        official["2026-09-02"] = 71.2  # Synthetic arrival, not a published VC.
        recalculate(base, official)
        with patch("build_fixed_models_intraday.liquid_snapshot", provider), patch("build_fixed_models_intraday.google_finance_snapshot", provider):
            snap = build_snapshot(base, NOW)
        self.assertEqual(snap["models"]["retornos"]["base_vc"], 71.2)

    def test_stale_anchor_rejected(self):
        base, official = fixture()
        official["2026-09-01"] = 70.8600385
        recalculate(base, official)
        base["rows"][-1]["vc_retornos"] = 72.03148401873725
        with self.assertRaises(AssertionError):
            validate_history(base, official)

    def test_duplicate_date_rejected(self):
        base, official = fixture()
        base["rows"].append(copy.deepcopy(base["rows"][-1]))
        with self.assertRaises(AssertionError):
            validate_history(base, official)

    def test_full_snapshot_and_invariants(self):
        base, official = fixture()
        official["2026-09-01"] = 70.8600385
        recalculate(base, official)
        with patch("build_fixed_models_intraday.liquid_snapshot", provider), patch("build_fixed_models_intraday.google_finance_snapshot", provider):
            snap = build_snapshot(base, NOW)
        self.assertTrue(snap["close_consolidated"])
        self.assertEqual(snap["fresh_factors"], 5)
        self.assertAlmostEqual(snap["models"]["niveles"]["vc_intraday"], 71.97775231698063)
        self.assertAlmostEqual(snap["models"]["retornos"]["vc_intraday"], 71.77351723820415, places=4)
        for change in ("return", "price_previous", "timestamp", "quote_timestamp"):
            bad = copy.deepcopy(snap)
            bad["tickers"][0][change] = {"return": .99, "price_previous": 1, "timestamp": "2026-09-02", "quote_timestamp": "2026-09-03T15:55:00-04:00"}[change]
            with self.assertRaises(AssertionError, msg=change):
                validate_snapshot(base, bad)
        bad = copy.deepcopy(snap)
        bad["base_revision"] = "old"
        with self.assertRaises(AssertionError):
            validate_snapshot(base, bad)
        bad = copy.deepcopy(snap)
        bad["tickers"].append(copy.deepcopy(bad["tickers"][0]))
        with self.assertRaises(AssertionError):
            validate_snapshot(base, bad)

    def test_missing_quote_cannot_become_current_close(self):
        base, _ = fixture()
        with patch("build_fixed_models_intraday.liquid_snapshot", provider), patch("build_fixed_models_intraday.google_finance_snapshot", side_effect=ValueError("missing")):
            snap = build_snapshot(base, NOW)
        self.assertEqual(snap["fresh_factors"], 4)
        self.assertFalse(snap["close_consolidated"])
        self.assertEqual(snap["tickers"][-1]["timestamp"], "2026-09-02")

    def test_same_inputs_reproduce_sheet(self):
        base, official = fixture()
        official["2026-09-01"] = 70.8600385
        recalculate(base, official)
        prices = {**PRICES, "SPY": 773.11, "EEM": 67.48, "QQQ": 717.61}
        lc, rc = (base["models"][k]["coefficients"] for k in ("niveles", "retornos"))
        prev = {"SPY": 765.16, "EEM": 67.15, "MCHI": 54.54, "QQQ": 709.24, "SPBLSCUP": 455.17}
        level = lc["intercept"] + sum(lc[f]*prices[f] for f in FACTORS)
        ret = rc["intercept"] + sum(rc[f]*(prices[f]/prev[f]-1) for f in FACTORS)
        value = base["rows"][-1]["vc_retornos"]*(1+ret)
        self.assertEqual(f"{level:.4f}", "71.9859")
        self.assertEqual(f"{value:.4f}", "71.7802")

    def test_confirmed_close_saved_once_and_repeated_run_is_idempotent(self):
        base, official = fixture()
        official["2026-09-01"] = 70.8600385
        recalculate(base, official)
        with patch("build_fixed_models_intraday.liquid_snapshot", provider), patch("build_fixed_models_intraday.google_finance_snapshot", provider):
            snap = build_snapshot(base, NOW)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for path in ("public/data", "data/rolling90", "data/fixed_models"):
                (root/path).mkdir(parents=True)
            (root/"public/data/fixed_models_2026.json").write_text(json.dumps(base))
            (root/"public/data/fixed_models_intraday.json").write_text(json.dumps(snap))
            write_rows(root/"data/rolling90/sbs_profuturo_f3.csv", [{"fecha": k, "valor_cuota": official[k]} for k in sorted(official)])
            for name, factors in (("yahoo_levels_2026.csv", FACTORS[:-1]), ("spblscup_levels_2026.csv", ["SPBLSCUP"])):
                write_rows(root/"data/fixed_models"/name, [{"fecha": "2026-09-02", **{f: base["rows"][-1][f] for f in factors}, "source": "TEST"}])
            reconcile_files(root=root)
            first = json.loads((root/"public/data/fixed_models_2026.json").read_text())
            reconcile_files(root=root)
            second = json.loads((root/"public/data/fixed_models_2026.json").read_text())
            self.assertEqual(first["data_revision"], second["data_revision"])
            self.assertEqual([r["fecha"] for r in second["rows"]].count("2026-09-03"), 1)
            self.assertAlmostEqual(second["rows"][-1]["vc_retornos"], snap["models"]["retornos"]["vc_intraday"])


class QuoteTests(unittest.TestCase):
    def chart(self, last_hour=16, last_minute=0):
        last = datetime(2026, 9, 3, last_hour, last_minute, tzinfo=NY)
        first = datetime(2026, 9, 3, 15, 55, tzinfo=NY)
        return {"chart": {"result": [{"meta": {"symbol": "SPY", "regularMarketPrice": 773.17, "regularMarketTime": int(last.timestamp())},
                "timestamp": [int(first.timestamp()), int(last.timestamp())], "indicators": {"quote": [{"close": [773.11, 773.17]}]}}]}}

    def test_yahoo_keeps_1600_closing_print(self):
        price, stamp, confirmed = yahoo_chart_quote(self.chart(), "SPY", NOW)
        self.assertEqual(price, 773.17)
        self.assertEqual(stamp.hour, 16)
        self.assertTrue(confirmed)

    def test_1555_bar_is_not_final_close(self):
        _, _, confirmed = yahoo_chart_quote(self.chart(15, 55), "SPY", NOW)
        self.assertFalse(confirmed)

    def test_wrong_yahoo_symbol_rejected(self):
        with self.assertRaises(ValueError):
            yahoo_chart_quote(self.chart(), "EEM", NOW)

    def test_google_visible_price_date_without_attributes(self):
        html = '<main>S&amp;P Peru Select 20% Capped Index (USD) 455.91 +0.16% 1D Sep 3, 4:57:49 PM GMT-4</main>'
        price, stamp, confirmed = google_html_quote(html, "SPBLSCUP", "INDEXSP", NOW)
        self.assertEqual(price, 455.91)
        self.assertEqual(stamp.isoformat(), "2026-09-03T16:57:49-04:00")
        self.assertTrue(confirmed)

    def test_google_scopes_timestamp_to_main_quote(self):
        stamp = int(datetime(2026, 9, 2, 16, 0, tzinfo=NY).timestamp())
        html = f'<main><div data-exchange="INDEXSP" data-last-price="455.91" data-last-normal-market-timestamp="{stamp}"><div class="YMlKec fxKbKc">455.91</div></div></main><aside data-last-normal-market-timestamp="1788469069">other</aside>'
        _, date, confirmed = google_html_quote(html, "SPBLSCUP", "INDEXSP", NOW)
        self.assertEqual(date.date().isoformat(), "2026-09-02")
        self.assertFalse(confirmed)

    def test_google_missing_own_date_rejected(self):
        with self.assertRaises(ValueError):
            google_html_quote('<main><div class="YMlKec fxKbKc">455.91</div></main><aside data-last-normal-market-timestamp="1788469069">other</aside>', "SPBLSCUP", "INDEXSP", NOW)

    def test_google_etf_text_layout_excludes_after_hours(self):
        html = '<title>iShares MSCI China ETF (MCHI) Price &amp; News - Google Finance</title><main>MCHI:NASDAQ iShares MSCI China ETF $54.37 -0.31% 1D $55.99 After hours Closed: Sep 3, 4:00:00 PM GMT-4</main>'
        price, stamp, confirmed = google_html_quote(html, "MCHI", "NASDAQ", NOW)
        self.assertEqual(price, 54.37)
        self.assertEqual(stamp.hour, 16)
        self.assertTrue(confirmed)

    def test_year_rollover(self):
        now = datetime(2027, 1, 2, 9, 0, tzinfo=NY)
        self.assertEqual(visible_google_stamp("Dec 31, 4:00 PM GMT-5", now).year, 2026)

    def test_preopen_weekend_and_holiday_use_previous_session(self):
        for value, expected in [("2026-09-04T08:00", "2026-09-03"), ("2026-09-05T14:00", "2026-09-04"), ("2026-09-07T14:00", "2026-09-04")]:
            ctx = session_context(datetime.fromisoformat(value).replace(tzinfo=NY))
            self.assertEqual(ctx["date"], expected)
            self.assertFalse(ctx["market_open"])

    def test_early_close_and_dst(self):
        ctx = session_context(datetime(2026, 11, 27, 14, 0, tzinfo=NY))
        self.assertEqual(ctx["close"].hour, 13)
        self.assertFalse(ctx["market_open"])
        self.assertEqual(ctx["close"].utcoffset().total_seconds(), -5*3600)


if __name__ == "__main__":
    unittest.main()
