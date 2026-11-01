from datetime import datetime, timezone

import pytest

from flightops import pipeline
from flightops.transform import airports


def utc(month, day, hour, minute=0):
    return datetime(2024, month, day, hour, minute, tzinfo=timezone.utc)


@pytest.fixture
def flights(conn, load_fixture):
    load_fixture("ourairports_airports", "airports.csv")
    load_fixture("bts_ontime", "bts_awkward.csv")
    airports.build_airports(conn)
    pipeline.run_sql(conn, "transform/flights.sql")
    return conn


def get(conn, number, *columns):
    row = conn.execute(
        f"select {', '.join(columns)} from staging.flight where flight_number = %s", (str(number),)
    ).fetchone()
    return row[0] if len(columns) == 1 else row


def test_every_row_arrives(flights):
    assert flights.execute("select count(*) from staging.flight").fetchone()[0] == 10


def test_timezones_come_from_coordinates(flights):
    zones = dict(flights.execute("select bts_code, tz from staging.airport").fetchall())
    assert zones["ATL"] == "America/New_York"
    assert zones["ORD"] == "America/Chicago"


def test_alias_keeps_the_2024_code_and_the_current_one(flights):
    row = flights.execute(
        "select ident, iata_current, icao_code from staging.airport where bts_code = 'PBI'"
    ).fetchone()
    assert row == ("KPBI", "DJT", "KDJT")
    assert get(flights, 9, "sched_dep_utc") == utc(7, 19, 12)


def test_times_convert_across_timezones(flights):
    assert get(flights, 1, "sched_dep_utc", "sched_arr_utc", "actual_dep_utc", "actual_arr_utc") == (
        utc(7, 19, 12), utc(7, 19, 13, 55), utc(7, 19, 12, 10), utc(7, 19, 14, 5),
    )


def test_2400_is_midnight_at_the_end_of_flight_date(flights):
    assert get(flights, 2, "sched_dep_utc", "actual_arr_utc") == (utc(7, 20, 4), utc(7, 20, 5, 55))


def test_arrival_date_comes_from_the_block_not_flight_date(flights):
    assert get(flights, 3, "sched_dep_utc", "sched_arr_utc") == (utc(7, 20, 6), utc(7, 20, 10, 30))


def test_cancelled_flight_with_no_tail(flights):
    assert get(flights, 4, "tail_number", "cancelled", "actual_dep_utc", "landed_station") == (
        None, True, None, None,
    )


def test_cancelled_after_departure_keeps_departure_but_never_lands(flights):
    assert get(flights, 5, "actual_dep_utc", "actual_arr_utc", "landed_station") == (
        utc(7, 19, 21, 5), None, None,
    )


def test_diversion_that_reached_destination_lands_there(flights):
    assert get(flights, 6, "diverted", "reached_dest", "landed_station", "actual_arr_utc") == (
        True, True, "LGA", utc(7, 19, 20),
    )


def test_diversion_that_stopped_short_lands_at_last_diversion_airport(flights):
    assert get(flights, 7, "diverted", "reached_dest", "landed_station", "actual_arr_utc") == (
        True, False, "CLE", utc(7, 19, 21),
    )


def test_tail_without_n_is_normalized_and_kept_as_delivered(flights):
    assert get(flights, 8, "tail_number", "tail_as_delivered") == ("N320NV", "320NV")


def test_blank_delay_causes_stay_null_and_reported_ones_are_kept(flights):
    assert get(flights, 1, "carrier_delay", "late_aircraft_delay") == (None, None)
    assert get(flights, 8, "carrier_delay", "weather_delay", "late_aircraft_delay") == (10, 0, 15)


def test_hhmm_wins_when_block_time_disagrees_and_it_is_flagged(flights):
    assert get(flights, 10, "sched_arr_utc", "block_mismatch") == (utc(7, 19, 20), True)
    assert get(flights, 1, "block_mismatch") is False
