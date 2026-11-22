import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from flightops.sources import live, raw
from flightops.transform.live import build_live
LIVE = Path(__file__).parent / "fixtures" / "live"
COLS = ("tail_number", "manufacturer", "model", "resolve_method", "resolve_confidence", "unresolved_reason",
        "operator", "bts_carrier", "operator_reason", "on_ground", "altitude_ft", "vertical_rate_fpm",
        "distance_nm", "bearing_deg")


@pytest.fixture
def built(conn, load_fixture, monkeypatch, tmp_path):
    monkeypatch.setattr(live, "STATES_DIR", tmp_path / "s")
    monkeypatch.setattr(live, "AWC_DIR", tmp_path / "a")
    load_fixture("faa_master", "live/faa_master.csv")
    load_fixture("faa_acftref", "faa_acftref.csv")
    raw.load_file(conn, "opensky", "opensky_state", live.write_states(json.loads((LIVE / "states.json").read_text())))
    metar = json.loads((LIVE / "metar.json").read_text())
    raw.load_file(conn, "awc", "awc_metar", live.write_metar(metar, 100))
    raw.load_file(conn, "awc", "awc_metar", live.write_metar(metar[:1], 200))  # the same SPECI fetched again
    raw.load_file(conn, "awc", "awc_taf", live.write_taf("TAF KATL old", 100))
    raw.load_file(conn, "awc", "awc_taf", live.write_taf("TAF KATL new", 200))
    counts = build_live(conn)
    rows = conn.execute(f"SELECT hex, {', '.join(COLS)} FROM ontology.live_position").fetchall()
    return counts, {r[0]: dict(zip(COLS, r[1:])) for r in rows}


def test_counts(built):
    assert built[0] == (4, 2, 1)


def test_lowercase_hex_resolves_to_a_tail_type_and_operator(built):
    row = built[1]["A00001"]
    assert row["tail_number"] == "N102DN" and (row["manufacturer"], row["model"]) == ("AIRBUS", "A321")
    assert (row["resolve_method"], row["resolve_confidence"], row["unresolved_reason"]) == ("faa_current_hex", "high", None)
    assert (row["operator"], row["bts_carrier"], row["operator_reason"]) == ("Delta Air Lines", "DL", None)


def test_units_distance_and_bearing(built):
    row = built[1]["A00001"]  # one degree due north of ATL, at 3,048 m, sinking 5.08 m/s
    assert (row["altitude_ft"], row["vertical_rate_fpm"]) == (10000, -1000)
    assert (row["distance_nm"], row["bearing_deg"]) == (Decimal("60.0"), 0)
    assert built[1]["A00002"]["bearing_deg"] == 90


def test_general_aviation_callsign_has_no_operator(built):
    row = built[1]["A00002"]
    assert row["tail_number"] == "N200A"
    assert (row["operator"], row["operator_reason"]) == (None, "general aviation callsign")


def test_hex_on_two_registrations_stays_unresolved(built):
    row = built[1]["A00003"]
    assert (row["tail_number"], row["resolve_method"], row["unresolved_reason"]) == (None, None, "ambiguous hex")
    assert (row["operator_reason"], row["on_ground"], row["distance_nm"]) == ("unknown prefix", True, Decimal("0.0"))


def test_unknown_hex_with_no_callsign_or_position_is_kept(built):
    row = built[1]["FFFFFF"]
    assert (row["unresolved_reason"], row["operator_reason"], row["distance_nm"]) == ("hex not in FAA registry", "no callsign", None)


def test_only_the_latest_snapshot_is_live(conn, built):
    raw.load_file(conn, "opensky", "opensky_state", live.write_states({"time": 1795368999, "states": None}))
    assert build_live(conn) == (0, 0, 0)


def test_repeated_metars_are_kept_once_and_parsed(conn, built):
    rows = conn.execute(
        "SELECT observed_at, metar_type, wind_dir_deg, visibility_sm, ceiling_ft, weather "
        "FROM ontology.live_weather ORDER BY observed_at"
    ).fetchall()
    assert len(rows) == 2
    assert rows[1] == (datetime(2026, 11, 22, 17, 31, tzinfo=timezone.utc), "SPECI", 50, Decimal("6"), 800, ["BR"])


def test_latest_taf_only(conn, built):
    assert conn.execute("SELECT raw_text FROM ontology.live_taf").fetchall() == [("TAF KATL new",)]
