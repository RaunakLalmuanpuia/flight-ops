from datetime import date

import psycopg
import pytest

from flightops import pipeline

D19, D20 = date(2024, 7, 19), date(2024, 7, 20)


@pytest.fixture
def built(conn, load_fixture):
    load_fixture("ourairports_airports", "airports.csv")
    load_fixture("bts_ontime", "bts_app_read.csv")
    load_fixture("iem_metar", "metar_join.csv")
    pipeline.build(conn)
    return conn


def by_flight(conn, sql, params=()):
    return {r[0]: r[1:] for r in conn.execute(sql, params).fetchall()}


def hub(conn, day):
    return by_flight(
        conn,
        "select flight_number, atl_hour, direction, status from app_read.hub_day_flights where atl_day = %s",
        (day,),
    )


def test_hub_day_holds_atl_flights_by_their_scheduled_atl_event(built):
    assert hub(built, D19) == {
        "17": (7, "dep", "on_time"),
        "10": (8, "dep", "on_time"),
        "11": (12, "arr", "delayed"),
        "12": (14, "dep", "cancelled"),
        "13": (20, "arr", "on_time"),
        "15": (16, "arr", "diverted"),
    }


def test_inbound_flight_belongs_to_the_atl_day_it_lands(built):
    assert hub(built, D20) == {"14": (6, "arr", "on_time")}


def test_hourly_counts_split_by_status(built):
    rows = built.execute(
        "select atl_hour, direction, scheduled, operated, on_time, delayed, diverted, cancelled "
        "from app_read.hub_day_hourly where atl_day = %s order by 1, 2",
        (D19,),
    ).fetchall()
    assert rows == [
        (7, "dep", 1, 1, 1, 0, 0, 0),
        (8, "dep", 1, 1, 1, 0, 0, 0),
        (12, "arr", 1, 1, 0, 1, 0, 0),
        (14, "dep", 1, 0, 0, 0, 0, 1),
        (16, "arr", 1, 1, 0, 0, 1, 0),
        (20, "arr", 1, 1, 1, 0, 0, 0),
    ]


def test_metar_is_from_the_actual_atl_event_else_the_scheduled_one(built):
    assert by_flight(
        built,
        "select flight_number, metar_staleness_min, metar_stale from app_read.hub_day_flights where atl_day = %s",
        (D19,),
    ) == {
        "17": (None, True),  # no METAR before 07:00 local counts as stale
        "10": (8, False),
        "11": (153, True),
        "12": (188, True),
        "13": (563, True),
        "15": (363, True),
    }


def test_metar_from_the_previous_day_is_still_used_and_stale(built):
    assert by_flight(
        built, "select flight_number, metar_staleness_min, metar_stale from app_read.hub_day_flights where atl_day = %s", (D20,)
    ) == {"14": (1178, True)}


def test_delays_are_minutes_by_cause(built):
    delays = by_flight(built, "select flight_number, delays from app_read.hub_day_flights where atl_day = %s", (D19,))
    assert delays["11"] == ({"carrier": 10, "late_aircraft": 20},)
    assert delays["10"] == (None,)


def test_caveats_count_each_flag_for_the_day(built):
    assert built.execute(
        "select metar_stale, block_mismatch, aircraft_unresolved, aircraft_medium_confidence, rotation_break "
        "from app_read.hub_day_caveats where atl_day = %s",
        (D19,),
    ).fetchone() == (5, 0, 6, 0, 1)


def test_weather_strip_marks_adverse_metars_and_skips_madis(built):
    assert built.execute(
        "select atl_hour, adverse from app_read.hub_day_weather where atl_day = %s order by observed_at", (D19,)
    ).fetchall() == [(7, False), (8, True), (8, False), (10, False)]


def test_tail_legs_include_cancelled_flights_and_label_gaps(built):
    rows = built.execute(
        "select flight_number, leg_seq, leg_day, connects, gap_minutes, break_label, prev_station "
        "from app_read.tail_legs where tail_number = 'N1A' order by sched_dep_utc"
    ).fetchall()
    assert rows == [
        ("10", 1, D19, None, None, None, None),
        ("11", 2, D19, True, 95, None, "ORD"),
        ("12", None, D19, None, None, None, None),
        ("13", 3, D19, False, 275, "Likely flew legs BTS does not report", "ATL"),
    ]


def test_tail_legs_cover_legs_away_from_atl(built):
    assert by_flight(
        built,
        "select flight_number, connects, prev_station, metar_staleness_min from app_read.tail_legs "
        "where tail_number = 'N3A'",
    ) == {"15": (None, None, 363), "18": (True, "CLE", None)}


def test_leg_day_is_the_atl_local_date_of_scheduled_departure(built):
    assert built.execute("select leg_day from app_read.tail_legs where flight_number = '14'").fetchone() == (D20,)


def test_tails_that_never_touched_atl_are_absent(built):
    assert built.execute("select count(*) from app_read.tail_legs where tail_number = 'N4A'").fetchone() == (0,)


def test_tail_aircraft_gives_the_unresolved_reason(built):
    assert built.execute(
        "select model, confidence, unresolved_reason, flights from app_read.tail_aircraft where tail_number = 'N1A'"
    ).fetchall() == [(None, None, "no_faa_record", 4)]


@pytest.mark.parametrize(
    "cause",
    [
        "likely_unreported_flying",
        "long_gap_unreported_or_out_of_service",
        "after_diversion",
        "overlap_data_error",
        "short_gap_likely_data_error",
    ],
)
def test_every_break_cause_has_a_readable_label(conn, cause):
    label = conn.execute("select app_read.break_label(%s)", (cause,)).fetchone()[0]
    assert label and label != cause


def test_unknown_break_cause_shows_as_delivered(conn):
    assert conn.execute("select app_read.break_label('new_cause')").fetchone() == ("new_cause",)


def test_day_range_is_the_bts_flight_dates(built):
    assert built.execute("select first_day, last_day from app_read.day_range").fetchone() == (D19, D19)


def test_app_role_reads_app_read_only(built):
    built.execute("SET ROLE flightops_app")
    try:
        assert built.execute("select count(*) from app_read.hub_day_flights").fetchone() == (7,)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            built.execute("select 1 from ontology.flight")
    finally:
        built.execute("RESET ROLE")


@pytest.mark.parametrize(
    "statement",
    ["insert into ontology.carrier (code) values ('XX')", "create table app_read.scratch (i int)"],
)
def test_app_role_cannot_write(built, statement):
    built.execute("SET ROLE flightops_app")
    try:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            built.execute(statement)
    finally:
        built.execute("RESET ROLE")
