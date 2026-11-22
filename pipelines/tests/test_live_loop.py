import io
import json
import urllib.error
from pathlib import Path

import pytest

from flightops import live as loop
from flightops.sources import live, opensky
LIVE = Path(__file__).parent / "fixtures" / "live"


@pytest.fixture
def sources(monkeypatch, tmp_path):
    monkeypatch.setattr(live, "STATES_DIR", tmp_path / "s")
    monkeypatch.setattr(live, "AWC_DIR", tmp_path / "a")
    monkeypatch.setattr(opensky, "_token", lambda: "t")
    monkeypatch.setattr(live, "fetch_states", lambda token: json.loads((LIVE / "states.json").read_text()))
    monkeypatch.setattr(live, "fetch_metar", lambda: json.loads((LIVE / "metar.json").read_text()))
    monkeypatch.setattr(live, "fetch_taf", lambda: "TAF KATL x")


def raises(exc):
    def fetch(*args):
        raise exc
    return fetch


def http_error(code, headers=None):
    return raises(urllib.error.HTTPError("u", code, "x", headers or {}, io.BytesIO(b"")))


def count(conn, table):
    return conn.execute(f"SELECT count(*) FROM ontology.{table}").fetchone()[0]


def test_first_tick_fetches_everything(conn, sources):
    assert loop.tick(conn, 0, {}) == 0
    assert (count(conn, "live_position"), count(conn, "live_weather"), count(conn, "live_taf")) == (4, 2, 1)


def test_weather_is_fetched_every_fifth_tick_only(conn, sources, monkeypatch):
    monkeypatch.setattr(live, "fetch_metar", lambda: pytest.fail("weather fetched on tick 1"))
    loop.tick(conn, 1, {})


def test_expired_token_is_dropped_and_the_tick_still_builds(conn, sources, monkeypatch):
    monkeypatch.setattr(live, "fetch_states", http_error(401))
    state = {"token": "old"}
    assert loop.tick(conn, 0, state) == 0
    assert state["token"] is None
    assert count(conn, "live_weather") == 2


def test_quota_exhausted_returns_the_wait(conn, sources, monkeypatch):
    monkeypatch.setattr(live, "fetch_states", http_error(429, {"X-Rate-Limit-Retry-After-Seconds": "900"}))
    assert loop.tick(conn, 1, {}) == 900


def test_network_failure_does_not_stop_the_loop(conn, sources, monkeypatch):
    monkeypatch.setattr(live, "fetch_states", raises(urllib.error.URLError("down")))
    monkeypatch.setattr(live, "fetch_metar", raises(TimeoutError()))
    loop.tick(conn, 0, {})


def test_run_sleeps_the_interval_or_the_longer_wait(conn, sources, monkeypatch):
    waits = iter([0, 900])
    monkeypatch.setattr(loop, "tick", lambda conn, n, state: next(waits))
    slept = []
    loop.run(conn, every=60, ticks=2, sleep=slept.append)
    assert slept == [60, 900]
