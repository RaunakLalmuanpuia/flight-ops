from datetime import date

import psycopg
import pytest

from flightops import pipeline

D19, D20, D21 = date(2024, 7, 19), date(2024, 7, 20), date(2024, 7, 21)


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
        ("19", None, D21, None, None, None, None),
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
    ).fetchall() == [(None, None, "no_faa_record", 5)]


def test_tail_aircraft_spans_the_atl_days_of_its_flights(built):
    assert built.execute(
        "select first_day, last_day from app_read.tail_aircraft where tail_number = 'N1A'"
    ).fetchone() == (D19, D21)


def test_leg_order_covers_cancelled_and_flown_legs(built):
    assert built.execute(
        "select flight_number, leg_order from app_read.tail_legs where tail_number = 'N1A' order by leg_order"
    ).fetchall() == [("10", 1), ("11", 2), ("12", 3), ("13", 4), ("19", 5)]


def test_neighbour_legs_of_an_all_cancelled_day(built):
    assert built.execute(
        "select flight_number from app_read.tail_legs where tail_number = 'N1A' and leg_order between "
        "(select min(leg_order) from app_read.tail_legs where tail_number = 'N1A' and leg_day = %s) - 1 and "
        "(select max(leg_order) from app_read.tail_legs where tail_number = 'N1A' and leg_day = %s) + 1 "
        "order by leg_order",
        (D21, D21),
    ).fetchall() == [("13",), ("19",)]


def test_no_tail_is_not_an_unresolved_aircraft(built):
    assert by_flight(
        built,
        "select flight_number, no_tail, aircraft_unresolved from app_read.hub_day_flights where atl_day = %s",
        (D21,),
    ) == {"20": (True, False), "19": (False, True)}
    assert built.execute(
        "select no_tail, aircraft_unresolved from app_read.hub_day_caveats where atl_day = %s", (D21,)
    ).fetchone() == (1, 1)


def test_diverted_leg_carries_its_landed_timezone(built):
    assert built.execute(
        "select landed, landed_tz from app_read.tail_legs where flight_number = '15'"
    ).fetchone() == ("CLE", "America/New_York")


def test_tail_legs_carry_each_legs_aircraft_link(conn, load_fixture):
    load_fixture("ourairports_airports", "airports.csv")
    load_fixture("bts_ontime", "bts_tail_links.csv")  # bts_tails.csv has no actual times, so build() blocks on it
    load_fixture("faa_master", "faa_master.csv")
    load_fixture("faa_dereg", "faa_dereg.csv")
    load_fixture("faa_acftref", "faa_acftref.csv")
    pipeline.build(conn)
    rows = conn.execute(
        "select tail_number, aircraft_link_confidence, aircraft_id is not null from app_read.tail_legs "
        "where tail_number in ('N100A', 'N500A') order by 1"
    ).fetchall()
    assert rows == [("N100A", "high", True), ("N500A", "medium", True)]


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
    assert built.execute("select first_day, last_day from app_read.day_range").fetchone() == (D19, D21)


def test_app_role_reads_app_read_only(built):
    built.execute("SET ROLE flightops_app")
    try:
        assert built.execute("select count(*) from app_read.hub_day_flights").fetchone() == (9,)
        assert built.execute("select count(*) from app_read.hub_day_weather").fetchone()[0] > 0
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


def test_leg_order_follows_schedule_so_a_cancelled_leg_never_jumps_ahead(conn, load_fixture):
    load_fixture("ourairports_airports", "airports.csv")
    load_fixture("bts_ontime", "bts_leg_order.csv")
    load_fixture("iem_metar", "metar_join.csv")
    pipeline.build(conn)
    assert conn.execute(
        "select flight_number, leg_order from app_read.tail_legs where tail_number = 'N7A' order by leg_order"
    ).fetchall() == [("30", 1), ("31", 2)]


def test_overnight_inbound_links_to_the_tail_day_of_its_departure(conn, load_fixture):
    load_fixture("ourairports_airports", "airports.csv")
    load_fixture("bts_ontime", "bts_leg_order.csv")
    load_fixture("iem_metar", "metar_join.csv")
    pipeline.build(conn)
    assert conn.execute(
        "select atl_day, tail_day from app_read.hub_day_flights where flight_number = '32'"
    ).fetchall() == [(date(2024, 7, 20), date(2024, 7, 19))]
    assert conn.execute(
        "select leg_day from app_read.tail_legs where flight_number = '32'"
    ).fetchall() == [(date(2024, 7, 19),)]
