"""Offline regression tests: no dispatches, credentials, or live quote requests."""
import copy
import io
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta

from profuturo_watchdog import (FACTORS, GitHub, HEARTBEAT, NY, Supervisor, UPDATER,
                               market_context, read_json, run_lease,
                               snapshot_problems, verify_publication)


def dt(value):
    return datetime.fromisoformat(value).replace(tzinfo=NY)


NOW = dt("2026-09-04T09:40:00")


def snapshot(now=NOW):
    ctx = market_context(now)
    quote = now - timedelta(seconds=30) if ctx["market_open"] else ctx["close"]
    return {"signal_date": ctx["date"], "market_open": ctx["market_open"],
            "mode": "INTRADÍA" if ctx["market_open"] else "CIERRE / ÚLTIMO SNAPSHOT",
            "generated_at_lima": now.isoformat(), "fresh_factors": 5, "total_factors": 5,
            "close_consolidated": not ctx["market_open"],
            "tickers": [{"ticker": name, "timestamp": ctx["date"],
                         "quote_timestamp": quote.isoformat(), "fresh": True,
                         "close_confirmed": not ctx["market_open"],
                         "price_current": 101.0, "price_previous": 100.0,
                         "return": 101.0 / 100.0 - 1,
                         "previous_close_date": ctx["previous_date"]} for name in sorted(FACTORS)]}


class FakeGitHub:
    def __init__(self, public=None):
        self.public = snapshot() if public is None else public
        self.repo = copy.deepcopy(self.public)
        self.in_progress = False
        self.dispatched = []
        self.reads = 0
        self.api_error = False

    def published(self):
        self.reads += 1
        return self.public

    def repository_snapshot(self):
        if self.api_error:
            raise RuntimeError("HTTP 503")
        return self.repo

    def publisher_active(self):
        return self.in_progress

    def dispatch(self, workflow):
        self.dispatched.append(workflow)


class CalendarTests(unittest.TestCase):
    def test_current_session_and_previous_close(self):
        ctx = market_context(NOW)
        self.assertEqual(ctx["date"], "2026-09-04")
        self.assertEqual(ctx["previous_date"], "2026-09-03")
        self.assertTrue(ctx["market_open"])

    def test_preopen_wakes_at_open_and_does_not_fetch(self):
        github = FakeGitHub()
        result = Supervisor(github).tick(dt("2026-09-04T09:29:50"))
        self.assertEqual(result["sleep"], 10)
        self.assertEqual(github.reads, 0)

    def test_weekend_and_labor_day_do_not_dispatch(self):
        for day in ("2026-09-05", "2026-09-06", "2026-09-07"):
            github = FakeGitHub()
            result = Supervisor(github).tick(dt(day + "T10:00:00"))
            self.assertEqual(result["state"], "fuera_de_sesion")
            self.assertTrue(result["next_open"].startswith("2026-09-08"))
            self.assertEqual(github.reads, 0)
            self.assertEqual(github.dispatched, [])

    def test_early_close_and_dst(self):
        ctx = market_context(dt("2026-11-27T13:05:00"))
        self.assertFalse(ctx["market_open"])
        self.assertTrue(ctx["monitor"])
        self.assertEqual(ctx["close"].astimezone(NY).hour, 13)
        self.assertEqual(ctx["close"].astimezone(NY).utcoffset(), timedelta(hours=-5))
        self.assertFalse(market_context(dt("2026-11-27T14:31:00"))["monitor"])


class FreshnessTests(unittest.TestCase):
    def problems(self, value):
        return snapshot_problems(value, market_context(NOW), NOW)

    def test_healthy_current_snapshot(self):
        self.assertEqual(self.problems(snapshot()), [])

    def test_yesterdays_five_of_five_is_not_fresh_today(self):
        value = snapshot(dt("2026-09-03T16:30:00"))
        value["generated_at_lima"] = NOW.isoformat()
        self.assertIn("fecha de señal de otra sesión", self.problems(value))

    def test_old_file_retriggers_after_five_minutes(self):
        value = snapshot()
        value["generated_at_lima"] = (NOW - timedelta(minutes=5)).isoformat()
        self.assertIn("corte pendiente de renovar", self.problems(value))

    def test_new_file_with_old_quote_is_rejected(self):
        value = snapshot()
        value["tickers"][0]["quote_timestamp"] = (NOW - timedelta(minutes=16)).isoformat()
        self.assertTrue(any("hora de cotización inválida" in p or "más de 15 minutos" in p for p in self.problems(value)))

    def test_duplicate_missing_invalid_price_and_return(self):
        for mutation in (lambda s: s["tickers"].__setitem__(0, copy.deepcopy(s["tickers"][1])),
                         lambda s: s["tickers"].pop(),
                         lambda s: s["tickers"][0].update(price_current=-1),
                         lambda s: s["tickers"][0].update({"return": 5}),
                         lambda s: s["tickers"][0].update(previous_close_date="2026-09-02")):
            value = snapshot()
            mutation(value)
            self.assertTrue(self.problems(value))

    def test_future_and_naive_timestamps(self):
        for generated in ((NOW + timedelta(minutes=2)).isoformat(), "2026-09-04T09:40:00"):
            value = snapshot()
            value["generated_at_lima"] = generated
            self.assertIn("hora de generación inválida", self.problems(value))

    def test_consolidated_close_is_not_forced_to_refresh_every_five_minutes(self):
        now = dt("2026-09-04T17:00:00")
        value = snapshot(dt("2026-09-04T16:05:00"))
        self.assertEqual(snapshot_problems(value, market_context(now), now), [])
        value["tickers"][0]["close_confirmed"] = False
        self.assertTrue(snapshot_problems(value, market_context(now), now))


class RecoveryTests(unittest.TestCase):
    def test_healthy_does_not_dispatch(self):
        github = FakeGitHub()
        self.assertEqual(Supervisor(github).tick(NOW)["state"], "publicacion_verificada")
        self.assertEqual(github.dispatched, [])

    def test_missing_opening_automatically_dispatches_without_flooding(self):
        github = FakeGitHub(snapshot(dt("2026-09-03T16:30:00")))
        supervisor = Supervisor(github)
        self.assertEqual(supervisor.tick(NOW)["state"], "recuperacion_solicitada")
        self.assertEqual(supervisor.tick(NOW + timedelta(minutes=1))["state"], "esperando_recuperacion")
        self.assertEqual(github.dispatched, [UPDATER])
        supervisor.tick(NOW + timedelta(minutes=5))
        self.assertEqual(github.dispatched, [UPDATER, UPDATER])

    def test_existing_publisher_is_not_duplicated(self):
        github = FakeGitHub(snapshot(dt("2026-09-03T16:30:00")))
        github.in_progress = True
        self.assertEqual(Supervisor(github).tick(NOW)["state"], "actualizacion_en_curso")
        self.assertEqual(github.dispatched, [])

    def test_fresh_but_different_deployment_is_recovered(self):
        github = FakeGitHub()
        github.repo["base_revision"] = "other-generation"
        result = Supervisor(github).tick(NOW)
        self.assertIn("publicación distinta al repositorio", result["problems"])
        self.assertEqual(github.dispatched, [UPDATER])

    def test_lease_hands_off_without_cron_even_through_api_failures(self):
        for failure in (False, True):
            github = FakeGitHub()
            github.api_error = failure
            elapsed = [0]
            def sleep(seconds):
                elapsed[0] += seconds
            with redirect_stdout(io.StringIO()):
                run_lease(github, 180, now=lambda: NOW + timedelta(seconds=elapsed[0]),
                          monotonic=lambda: elapsed[0], sleeper=sleep)
            self.assertEqual(elapsed[0], 180)
            self.assertEqual(github.dispatched, [HEARTBEAT])

    def test_weekend_lease_handoff_does_not_fetch_quotes(self):
        github = FakeGitHub()
        elapsed = [0]
        def sleep(seconds):
            elapsed[0] += seconds
        with redirect_stdout(io.StringIO()):
            run_lease(github, 120, now=lambda: dt("2026-09-07T10:00:00"),
                      monotonic=lambda: elapsed[0], sleeper=sleep)
        self.assertEqual(elapsed[0], 120)
        self.assertEqual(github.dispatched, [HEARTBEAT])
        self.assertEqual(github.reads, 0)

    def test_scoped_permissions_and_token_destination(self):
        with self.assertRaises(ValueError):
            GitHub("other/repo", "fake-test-token")
        with self.assertRaises(ValueError):
            read_json("https://example.com/", token="fake-test-token")
        with self.assertRaises(ValueError):
            GitHub("rldaqp/afp-fondo3-monitor", "fake-test-token").dispatch("unrelated.yml")


class PublicationTests(unittest.TestCase):
    def test_waits_until_the_exact_generation_is_public(self):
        expected = snapshot()
        responses = iter([{}, expected])
        sleep = []
        with redirect_stdout(io.StringIO()):
            verify_publication(expected, fetch=lambda: next(responses), sleeper=sleep.append)
        self.assertEqual(sleep, [10])

    def test_fails_when_pages_never_serves_new_generation(self):
        with self.assertRaises(RuntimeError):
            verify_publication(snapshot(), attempts=2, fetch=lambda: {}, sleeper=lambda _: None)


if __name__ == "__main__":
    unittest.main()
