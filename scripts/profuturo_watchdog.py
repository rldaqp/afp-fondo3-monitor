"""Supervise publication, not equations; the only writes are workflow dispatches.

A bounded lease hands off through workflow_dispatch, without waiting for cron.
Outside the NYSE session/close window it only waits and hands off.
"""
from __future__ import annotations

import argparse
import base64
import json
import math
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

FACTORS = {"SPY", "EEM", "MCHI", "QQQ", "SPBLSCUP"}
BRANCH = "migracion-github-actions"
UPDATER = "update-fixed-models-intraday.yml"
HEARTBEAT = "intraday-heartbeat.yml"
PUBLISHERS = (UPDATER, "update-fixed-levels-returns.yml")
ACTIVE = {"queued", "in_progress", "pending", "waiting", "requested"}
PUBLIC_URL = "https://rldaqp.github.io/afp-fondo3-monitor/data/fixed_models_intraday.json"
SNAPSHOT_PATH = "public/data/fixed_models_intraday.json"
UTC = timezone.utc
NY = ZoneInfo("America/New_York")
REFRESH_SECONDS = 300
QUOTE_MAX_SECONDS = 900


def clock():
    return datetime.now(UTC)


def log(event, **fields):
    print(json.dumps({"at": clock().isoformat(), "event": event, **fields},
                     ensure_ascii=False), flush=True)


def stamp(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.utcoffset() is not None else None
    except (AttributeError, TypeError, ValueError):
        return None


def positive(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def market_context(now):
    # Lazy import: publication verification needs only the standard library.
    import exchange_calendars as xcals

    cal = xcals.get_calendar("XNYS")
    local = now.astimezone(NY)
    session = cal.date_to_session(local.date().isoformat(), direction="previous")
    if now < cal.session_open(session):
        session = cal.previous_session(session)
    opening = cal.session_open(session).to_pydatetime()
    closing = cal.session_close(session).to_pydatetime()
    following = cal.session_open(cal.next_session(session)).to_pydatetime()
    return {"date": session.date().isoformat(),
            "previous_date": cal.previous_session(session).date().isoformat(),
            "open": opening, "close": closing, "next_open": following,
            "market_open": opening <= now < closing,
            # SPBLSCUP can confirm later than the US ETF closing print.
            "monitor": opening <= now <= closing + timedelta(minutes=90)}


def snapshot_problems(snapshot, ctx, now):
    """A newly generated file is not necessarily a current market quote."""
    if not isinstance(snapshot, dict):
        return ["snapshot ausente"]
    problems = []
    if snapshot.get("signal_date") != ctx["date"]:
        problems.append("fecha de señal de otra sesión")
    if snapshot.get("market_open") is not ctx["market_open"]:
        problems.append("estado de mercado incorrecto")
    expected_mode = "INTRADÍA" if ctx["market_open"] else "CIERRE / ÚLTIMO SNAPSHOT"
    if snapshot.get("mode") != expected_mode:
        problems.append("modo no consolidado")
    generated = stamp(snapshot.get("generated_at_lima"))
    if generated is None or generated > now + timedelta(seconds=60):
        problems.append("hora de generación inválida")
    elif ctx["market_open"]:
        if generated < ctx["open"] or (now - generated).total_seconds() >= REFRESH_SECONDS:
            problems.append("corte pendiente de renovar")
    elif generated < ctx["close"]:
        problems.append("corte anterior al cierre")
    if snapshot.get("fresh_factors") != 5 or snapshot.get("total_factors") != 5:
        problems.append("factores incompletos")
    tickers = snapshot.get("tickers")
    if not isinstance(tickers, list) or len(tickers) != 5 or any(not isinstance(t, dict) for t in tickers):
        return problems + ["lista de factores inválida"]
    if {t.get("ticker") for t in tickers} != FACTORS:
        return problems + ["tickers duplicados o faltantes"]
    for ticker in tickers:
        name = ticker["ticker"]
        if not positive(ticker.get("price_current")) or not positive(ticker.get("price_previous")):
            problems.append(f"{name}: precio inválido")
        else:
            expected = ticker["price_current"] / ticker["price_previous"] - 1
            observed = ticker.get("return")
            if not isinstance(observed, (int, float)) or not math.isfinite(observed) or abs(expected - observed) > 1e-8:
                problems.append(f"{name}: retorno incoherente")
        if ticker.get("previous_close_date") != ctx["previous_date"]:
            problems.append(f"{name}: cierre previo de otra rueda")
        quote = stamp(ticker.get("quote_timestamp"))
        if (ticker.get("fresh") is not True or ticker.get("timestamp") != ctx["date"]
                or quote is None or quote.astimezone(NY).date().isoformat() != ctx["date"]):
            problems.append(f"{name}: cotización de otra sesión o sin hora propia")
        elif quote > now + timedelta(seconds=60) or quote < ctx["open"]:
            problems.append(f"{name}: hora de cotización inválida")
        elif ctx["market_open"] and (now - quote).total_seconds() > QUOTE_MAX_SECONDS:
            problems.append(f"{name}: cotización con más de 15 minutos")
        elif not ctx["market_open"] and (quote < ctx["close"] or ticker.get("close_confirmed") is not True):
            problems.append(f"{name}: cierre no confirmado")
    if not ctx["market_open"] and snapshot.get("close_consolidated") is not True:
        problems.append("cierre no consolidado")
    return problems


def read_json(url, *, token=None, data=None, sleeper=time.sleep):
    """Bounded retries; never log tokens, authenticated URLs or response bodies."""
    headers = {"Accept": "application/vnd.github+json", "Cache-Control": "no-cache",
               "User-Agent": "profuturo-publication-watchdog"}
    if token:
        if not url.startswith("https://api.github.com/"):
            raise ValueError("El token solo puede enviarse a api.github.com")
        headers["Authorization"] = "Bearer " + token
        headers["X-GitHub-Api-Version"] = "2022-11-28"
    encoded = json.dumps(data).encode() if data is not None else None
    if encoded is not None:
        headers["Content-Type"] = "application/json"
    for attempt in range(3):
        try:
            with urlopen(Request(url, data=encoded, headers=headers), timeout=25) as response:
                body = response.read()
                return json.loads(body) if body else None
        except HTTPError as exc:
            if exc.code not in {403, 408, 429, 500, 502, 503, 504} or attempt == 2:
                raise RuntimeError(f"HTTP {exc.code} consultando/publicando estado") from None
        except (URLError, TimeoutError) as exc:
            if attempt == 2:
                raise RuntimeError(f"Red no disponible: {type(exc).__name__}") from None
        sleeper(5 * (attempt + 1))


class GitHub:
    def __init__(self, repository, token):
        if repository != "rldaqp/afp-fondo3-monitor" or not token:
            raise ValueError("Repositorio o permiso de Actions no configurado")
        self.base = f"https://api.github.com/repos/{repository}"
        self.token = token

    def published(self):
        return read_json(PUBLIC_URL + "?watchdog=" + str(time.time_ns()))

    def repository_snapshot(self):
        payload = read_json(self.base + f"/contents/{SNAPSHOT_PATH}?ref={BRANCH}", token=self.token)
        return json.loads(base64.b64decode(payload["content"]))

    def publisher_active(self):
        for workflow in PUBLISHERS:
            payload = read_json(self.base + f"/actions/workflows/{workflow}/runs?per_page=10", token=self.token)
            for run in payload["workflow_runs"]:
                if run.get("head_branch") == BRANCH and run.get("status") in ACTIVE:
                    return True
        return False

    def dispatch(self, workflow):
        if workflow not in {UPDATER, HEARTBEAT}:
            raise ValueError("Workflow fuera del alcance del supervisor")
        read_json(self.base + f"/actions/workflows/{workflow}/dispatches",
                  token=self.token, data={"ref": BRANCH})


class Supervisor:
    def __init__(self, github, context=market_context):
        self.github = github
        self.context = context
        self.last_dispatch = None

    def tick(self, now):
        ctx = self.context(now)
        if not ctx["monitor"]:
            until_open = max(1, (ctx["next_open"] - now).total_seconds())
            return {"state": "fuera_de_sesion", "next_open": ctx["next_open"].isoformat(),
                    "sleep": min(900, until_open)}
        problems = []
        try:
            published = self.github.published()
            problems = snapshot_problems(published, ctx, now)
        except (RuntimeError, ValueError, KeyError, TypeError):
            published = None
            problems.append("publicación no accesible o inválida")
        repository_snapshot = self.github.repository_snapshot()
        if published != repository_snapshot:
            problems.append("publicación distinta al repositorio")
        if not problems:
            return {"state": "publicacion_verificada", "signal_date": ctx["date"],
                    "cut": published["generated_at_lima"], "fresh_factors": 5, "sleep": 60}
        if self.github.publisher_active():
            return {"state": "actualizacion_en_curso", "problems": problems, "sleep": 60}
        if self.last_dispatch and (now - self.last_dispatch).total_seconds() < REFRESH_SECONDS:
            return {"state": "esperando_recuperacion", "problems": problems, "sleep": 60}
        self.github.dispatch(UPDATER)
        self.last_dispatch = now
        return {"state": "recuperacion_solicitada", "problems": problems, "sleep": 60}


def run_lease(github, lease_seconds=10800, *, now=clock, monotonic=time.monotonic,
              sleeper=time.sleep, context=market_context):
    if not 60 <= lease_seconds <= 18000:
        raise ValueError("El relevo debe ocurrir entre 1 minuto y 5 horas")
    deadline = monotonic() + lease_seconds
    supervisor = Supervisor(github, context=context)
    while monotonic() < deadline:
        try:
            result = supervisor.tick(now())
            log("supervision", **{key: value for key, value in result.items() if key != "sleep"})
            delay = result["sleep"]
        except Exception as exc:
            # An API/source outage must not kill the only running timer.
            log("error_transitorio", error=type(exc).__name__, detail=str(exc)[:240])
            delay = 60
        remaining = deadline - monotonic()
        if remaining > 0:
            sleeper(min(delay, remaining))
    # workflow_dispatch resets the workflow_run chaining limit. The successor
    # waits for this lease to release the singleton concurrency lock.
    for attempt in range(3):
        try:
            github.dispatch(HEARTBEAT)
            log("relevo_automatico_solicitado", workflow=HEARTBEAT)
            return
        except Exception:
            if attempt == 2:
                raise
            sleeper(30)


def verify_publication(expected, *, attempts=12, fetch=None, sleeper=time.sleep):
    fetch = fetch or (lambda: read_json(PUBLIC_URL + "?verify=" + str(time.time_ns())))
    for attempt in range(attempts):
        try:
            if fetch() == expected:
                log("despliegue_verificado", signal_date=expected["signal_date"],
                    cut=expected["generated_at_lima"], fresh_factors=expected["fresh_factors"])
                return
        except (RuntimeError, ValueError):
            pass
        if attempt + 1 < attempts:
            sleeper(10)
    raise RuntimeError("El visor público no sirve el corte que acaba de desplegarse")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lease-seconds", type=int, default=10800)
    parser.add_argument("--verify-publication", action="store_true")
    args = parser.parse_args()
    if args.verify_publication:
        verify_publication(json.loads(Path(SNAPSHOT_PATH).read_text(encoding="utf-8")))
    else:
        github = GitHub(os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GH_TOKEN"))
        run_lease(github, args.lease_seconds)


if __name__ == "__main__":
    main()
