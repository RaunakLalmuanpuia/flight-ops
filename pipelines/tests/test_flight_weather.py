from datetime import datetime, timezone

import pytest

from flightops import pipeline


def utc(hour, minute):
    return datetime(2024, 7, 19, hour, minute, tzinfo=timezone.utc)


@pytest.fixture
def conn_built(conn, load_fixture):
    load_fixture("ourairports_airports", "airports.csv")
    load_fixture("bts_ontime", "bts_weather.csv")
    load_fixture("iem_metar", "metar_join.csv")
    pipeline.build(conn)
    return conn


@pytest.fixture
def joined(conn_built):
    rows = conn_built.execute(
        "select f.flight_number, w.event, w.basis, w.observed_at, w.staleness_min "
        "from ontology.flight_weather w join ontology.flight f using (flight_id)"
    ).fetchall()
    return {r[:3]: r[3:] for r in rows}


def test_scheduled_departure_uses_the_latest_earlier_metar(joined):
    assert joined["1", "departure", "scheduled"] == (utc(11, 52), 8)


def test_metar_at_the_exact_minute_counts(joined):
    assert joined["1", "departure", "actual"] == (utc(12, 30), 0)


def test_arrival_is_joined_on_both_bases(joined):
    assert joined["2", "arrival", "scheduled"] == (utc(14, 52), 8)
    assert joined["2", "arrival", "actual"] == (utc(14, 52), 38)


def test_madis_record_is_never_chosen_and_cancelled_flight_has_scheduled_only(joined):
    assert joined["3", "departure", "scheduled"] == (utc(12, 52), 8)
    assert ("3", "departure", "actual") not in joined


def test_flight_that_stopped_short_of_atl_has_no_actual_arrival_here(joined):
    assert joined["4", "arrival", "scheduled"] == (utc(14, 52), 128)
    assert ("4", "arrival", "actual") not in joined


def test_flight_that_stopped_short_at_atl_has_an_actual_arrival_here(joined):
    assert joined["5", "arrival", "actual"] == (utc(14, 52), 188)
    assert ("5", "arrival", "scheduled") not in joined


def test_flight_away_from_atl_has_no_rows(joined):
    assert not [k for k in joined if k[0] == "7"]


def test_event_before_the_first_metar_is_recorded_not_dropped(conn_built, joined):
    assert not [k for k in joined if k[0] == "6"]
    rows = conn_built.execute(
        "select reason, count(*), sum(flights) from dq.unresolved_link where entity = 'atl_weather' group by 1"
    ).fetchall()
    assert rows == [("no_metar_at_or_before", 2, 2)]


def test_stale_observations_are_reported_not_hidden(conn_built):
    value = conn_built.execute(
        "select value from dq.check_result where name = 'atl_weather_stale_over_90' order by id desc limit 1"
    ).fetchone()[0]
    assert value == 2
