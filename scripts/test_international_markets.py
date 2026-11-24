import unittest
from datetime import datetime
from unittest.mock import patch

import update_international_markets as market


def epoch(day, hour):
    return int(datetime.fromisoformat(day + "T" + hour).replace(tzinfo=market.NY).timestamp())


class InternationalMarketTests(unittest.TestCase):
    def setUp(self):
        day, prev = "2026-11-24", "2026-11-23"
        self.start, self.open = epoch(day, "04:00"), epoch(day, "09:30")
        self.prior = [epoch(prev, "09:30"), None, None, epoch(prev, "16:00")]
        self.window = (day, self.start, self.open, self.prior)

    def chart(self, pairs):
        return {"meta": {"regularMarketTime": self.prior[3], "regularMarketPrice": 100},
                "timestamp": [p[0] for p in pairs],
                "indicators": {"quote": [{"close": [p[1] for p in pairs]}]}}

    def test_pre_excludes_last_night_and_opening_auction(self):
        chart = self.chart([(self.prior[3] + 600, 90), (self.start, 101),
                            (self.open - 300, 103), (self.open, 110)])
        with patch.object(market, "yahoo_chart", return_value=chart):
            q = market.pre_quote("SPY", self.window, self.open + 900, None)
        self.assertEqual((q["at"], q["price"]), (self.open - 300, 103))
        self.assertAlmostEqual(q["change"], 3)

    def test_no_pre_quote_does_not_reuse_regular_close(self):
        chart = self.chart([(self.prior[3], 100), (self.prior[3] + 600, 104)])
        with patch.object(market, "nasdaq_pre", return_value=None), patch.object(market, "yahoo_chart", return_value=chart):
            self.assertIsNone(market.pre_quote("EPU", self.window, self.start + 600, None))

    def test_nasdaq_timestamp_must_belong_to_requested_session(self):
        result = {"data": {"marketStatus": "Pre-Market", "primaryData": {
            "lastTradeTimestamp": "Nov 23, 2026 8:12 AM ET", "lastSalePrice": "$47.05"}}}
        with patch.object(market, "request_json", return_value=result):
            self.assertIsNone(market.nasdaq_pre("MCHI", *self.window[:3], self.open))

    def test_index_uses_its_local_trading_date_and_reported_percentage(self):
        stamp = epoch("2026-11-24", "02:00")
        chart = self.chart([(stamp - 86400, 3540), (stamp - 300, 3546), (stamp, 3548)])
        chart["meta"] = {"regularMarketTime": stamp, "regularMarketPrice": 3548,
                         "exchangeTimezoneName": "Asia/Shanghai", "regularMarketChangePercent": 0.27}
        with patch.object(market, "yahoo_chart", return_value=chart):
            q = market.index_quote("000001.SS", stamp)
        self.assertEqual((q["session"], q["change"], len(q["points"])), ("2026-11-24", 0.27, 2))
        self.assertEqual(market.keep_latest(q, {"at": stamp - 600}), q)


if __name__ == "__main__":
    unittest.main()
