import pytest

from flightops import pipeline
from flightops.transform import airports


@pytest.fixture
def links(conn, load_fixture):
    load_fixture("ourairports_airports", "airports.csv")
    load_fixture("bts_ontime", "bts_tails.csv")
    load_fixture("faa_master", "faa_master.csv")
    load_fixture("faa_dereg", "faa_dereg.csv")
    load_fixture("faa_acftref", "faa_acftref.csv")
    airports.build_airports(conn)
    pipeline.run_sql(conn, "transform/flights.sql")
    pipeline.run_sql(conn, "resolve/aircraft.sql")
    rows = conn.execute(
        "select tail_number, frame, method, confidence, unresolved_reason from staging.aircraft_link"
    ).fetchall()
    return {r[0]: r[1:] for r in rows}


def test_dated_window_is_high_confidence(links):
    assert links["N100A"] == ("M1|S1", "window_exact", "high", None)


def test_deregistered_window_resolves_to_the_older_airframe(links):
    assert links["N600A"] == ("M2|S6", "window_exact", "high", None)


def test_dated_window_beats_an_undated_record(links):
    assert links["N400A"] == ("M1|S4", "window_exact", "high", None)


def test_open_start_is_medium_confidence(links):
    assert links["N500A"] == ("M1|S7", "window_open_start", "medium", None)


def test_reissued_certificate_with_one_airframe_is_medium_confidence(links):
    assert links["N200A"] == ("M1|S2", "single_airframe_outside_window", "medium", None)


def test_two_airframes_and_no_covering_window_stays_unresolved(links):
    assert links["N300A"] == (None, None, None, "no_window_multiple_airframes")


def test_no_record_stays_unresolved(links):
    assert links["N700A"] == (None, None, None, "no_faa_record")


def test_blank_tail_makes_no_link(links):
    assert None not in links


def test_hex_is_uppercase_and_tail_has_n(conn, links):
    assert conn.execute("select hex from staging.faa_record where tail_number = 'N100A'").fetchone()[0] == "A00001"
