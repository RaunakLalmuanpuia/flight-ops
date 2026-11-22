import json
from pathlib import Path

import pytest

from flightops.sources import live, raw
LIVE = Path(__file__).parent / "fixtures" / "live"


@pytest.fixture
def dirs(monkeypatch, tmp_path):
    monkeypatch.setattr(live, "STATES_DIR", tmp_path / "opensky_states")
    monkeypatch.setattr(live, "AWC_DIR", tmp_path / "awc")
    return tmp_path


def states():
    return json.loads((LIVE / "states.json").read_text())


def test_box_stays_in_the_one_credit_tier():
    assert (2 * live.BOX) ** 2 <= 25


def test_fetch_states_asks_for_the_box_around_atl(monkeypatch):
    urls = []
    monkeypatch.setattr(live, "_get", lambda url, token=None: urls.append((url, token)) or '{"time": 1, "states": null}')
    live.fetch_states("t")
    url, token = urls[0]
    assert token == "t"
    assert "lamin=32.1367" in url and "lamax=35.1367" in url and "lomin=-85.9281" in url and "lomax=-82.9281" in url


def test_states_round_trip_as_delivered(conn, dirs):
    path = live.write_states(states())
    assert path.name == "KATL_states_1795368605.csv"
    assert raw.load_file(conn, "opensky", "opensky_state", path).rows == 4
    row = conn.execute("SELECT time, icao24, callsign, on_ground, latitude FROM raw.opensky_state ORDER BY icao24").fetchone()
    assert row == ("1795368605", "a00001", "DAL1674 ", "False", "34.6367")


def test_an_empty_box_writes_a_header_only_file(conn, dirs):
    path = live.write_states({"time": 5, "states": None})
    assert raw.load_file(conn, "opensky", "opensky_state", path).rows == 0


def test_a_changed_state_vector_fails_loudly(dirs):
    payload = states()
    payload["states"][0].append("surprise")
    with pytest.raises(ValueError):
        live.write_states(payload)
    assert not any((dirs / "opensky_states").glob("*.csv"))


def test_metar_and_multiline_taf_round_trip(conn, dirs):
    metar = live.write_metar(json.loads((LIVE / "metar.json").read_text()), 1795368700)
    taf = live.write_taf((LIVE / "taf.txt").read_text().strip(), 1795368700)
    assert raw.load_file(conn, "awc", "awc_metar", metar).rows == 2
    assert raw.load_file(conn, "awc", "awc_taf", taf).rows == 1
    assert conn.execute("SELECT raw_text FROM raw.awc_taf").fetchone()[0] == (LIVE / "taf.txt").read_text().strip()


def test_no_taf_writes_a_header_only_file(conn, dirs):
    assert raw.load_file(conn, "awc", "awc_taf", live.write_taf("", 1)).rows == 0
