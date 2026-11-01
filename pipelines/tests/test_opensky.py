import io
import urllib.error
from datetime import date

import pytest

from flightops.sources import opensky

ROW = {
    "icao24": "ab92c4", "firstSeen": 1793449096, "estDepartureAirport": None, "lastSeen": 1793451539,
    "estArrivalAirport": "KATL", "callsign": "DAL1674 ", "estDepartureAirportHorizDistance": 6308,
    "estDepartureAirportVertDistance": 459, "estArrivalAirportHorizDistance": 1047,
    "estArrivalAirportVertDistance": 129, "departureAirportCandidatesCount": 2, "arrivalAirportCandidatesCount": 22,
}
DAY = date(2026, 10, 30)


@pytest.fixture
def api(monkeypatch, tmp_path):
    calls = []

    def fetch(kind, day, token):
        calls.append((kind, day))
        return [{**ROW, "firstSeen": len(calls)}]  # real files differ, and the loader skips a repeated hash

    monkeypatch.setattr(opensky, "DIR", tmp_path)
    monkeypatch.setattr(opensky, "_token", lambda: "t")
    monkeypatch.setattr(opensky, "_fetch", fetch)
    return calls


def test_one_day_writes_arrivals_and_departures(api, tmp_path):
    written = opensky.collect(DAY, DAY)
    assert [p.name for p in written] == ["KATL_arrival_2026-10-30.csv", "KATL_departure_2026-10-30.csv"]


def test_a_collected_day_is_never_fetched_again(api):
    opensky.collect(DAY, DAY)
    api.clear()
    assert opensky.collect(DAY, DAY) == []
    assert api == []


def test_no_token_is_requested_when_nothing_is_missing(api, monkeypatch):
    opensky.collect(DAY, DAY)
    monkeypatch.setattr(opensky, "_token", lambda: pytest.fail("token requested"))
    opensky.collect(DAY, DAY)


def test_day_with_no_data_yet_writes_no_file_and_is_retried(api, monkeypatch, tmp_path):
    real = opensky._fetch
    monkeypatch.setattr(opensky, "_fetch", lambda kind, day, token: None)
    assert opensky.collect(DAY, DAY) == []
    assert list(tmp_path.iterdir()) == []
    monkeypatch.setattr(opensky, "_fetch", real)
    assert len(opensky.collect(DAY, DAY)) == 2


def test_a_new_api_field_fails_loudly(api, monkeypatch, tmp_path):
    monkeypatch.setattr(opensky, "_fetch", lambda kind, day, token: [{**ROW, "surprise": 1}])
    with pytest.raises(ValueError):
        opensky.collect(DAY, DAY)
    assert list(tmp_path.iterdir()) == []


def test_fetch_treats_404_as_not_ready_and_raises_on_quota(monkeypatch):
    def raises(code):
        def urlopen(request, timeout):
            raise urllib.error.HTTPError("u", code, "x", {}, io.BytesIO(b"[]"))
        return urlopen

    monkeypatch.setattr(opensky.urllib.request, "urlopen", raises(404))
    assert opensky._fetch("arrival", DAY, "t") is None
    monkeypatch.setattr(opensky.urllib.request, "urlopen", raises(429))
    with pytest.raises(urllib.error.HTTPError):
        opensky._fetch("arrival", DAY, "t")


def test_settled_days_end_two_days_back_and_span_seven(api):
    assert opensky.settled_days(date(2026, 11, 1)) == (date(2026, 10, 24), date(2026, 10, 30))


def test_files_load_as_delivered_and_reload_changes_nothing(api, conn):
    opensky.collect(DAY, DAY)
    assert [r.skipped for r in opensky.load_all(conn)] == [False, False]
    assert [r.skipped for r in opensky.load_all(conn)] == [True, True]
    assert conn.execute(
        "select count(*), min(callsign), min(icao24), min(coalesce(estdepartureairport, 'null')) from raw.opensky_flight"
    ).fetchone() == (2, "DAL1674 ", "ab92c4", "")
