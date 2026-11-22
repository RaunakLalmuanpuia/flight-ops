import psycopg
import pytest

from flightops import pipeline

COLS = "depth, kind, flight_number, slack_min, predicted_dep_delay, at_risk, stop_reason"


@pytest.fixture
def built(conn, load_fixture):
    load_fixture("ourairports_airports", "airports.csv")
    load_fixture("bts_ontime", "bts_propagate.csv")
    pipeline.build(conn)
    # Fixed turns so the arithmetic is readable; the fixture alone is too small to measure them.
    conn.execute("truncate ontology.min_turn")
    conn.execute(
        "insert into ontology.min_turn (carrier_id, samples, p10, p25, p50) "
        "select carrier_id, 500, 30, 40, 60 from ontology.carrier where code = 'DL' "
        "union all select null, 1000, 20, 45, 70"
    )
    return conn


def fid(conn, number):
    return conn.execute("select flight_id from ontology.flight where flight_number = %s", (number,)).fetchone()[0]


def chain(conn, number, *args):
    return conn.execute(f"select {COLS} from app_read.propagate(%s{', %s' * len(args)})", (fid(conn, number), *args)).fetchall()


def test_delay_carries_across_legs_shows_cancelled_gap_and_stops_when_absorbed(built):
    assert chain(built, "101") == [
        (0, "selected", "101", None, None, None, None),
        (1, "flown", "102", -40, 40, True, None),
        (2, "flown", "103", -50, 50, True, None),
        (3, "cancelled", "104", None, None, None, None),
        (3, "flown", "105", 120, 0, False, "absorbed"),
    ]


def test_actuals_sit_beside_predictions(built):
    row = built.execute(
        "select actual_dep_delay, actual_late_aircraft, min_turn from app_read.propagate(%s) where flight_number = '102'",
        (fid(built, "101"),),
    ).fetchone()
    assert row == (45, 45, 40)


def test_what_if_delay_replaces_the_actual_arrival(built):
    assert chain(built, "101", 0) == [
        (0, "selected", "101", None, None, None, None),
        (1, "flown", "102", 20, 0, False, "absorbed"),
    ]


def test_percentile_selects_the_min_turn_column(built):
    assert chain(built, "101", None, 50)[1] == (1, "flown", "102", -60, 60, True, None)


def test_carrier_with_few_samples_falls_back_to_all_carriers(built):
    built.execute("update ontology.min_turn set samples = 199 where carrier_id is not null")
    assert chain(built, "101")[1] == (1, "flown", "102", -45, 45, True, None)


def test_rotation_break_stops_without_predicting(built):
    assert chain(built, "201")[1:] == [(1, "flown", "202", None, None, None, "break")]


def test_leg_more_than_24h_out_stops_without_predicting(built):
    assert chain(built, "301")[1:] == [(1, "flown", "302", None, None, None, "limit")]


def test_end_of_data_while_still_late(built):
    assert chain(built, "401")[1:] == [(1, "flown", "402", -40, 40, True, "end")]


def test_last_leg_selected_ends_at_once(built):
    assert chain(built, "106") == [(0, "selected", "106", None, None, None, "end")]


def test_cancelled_flight_returns_nothing(built):
    assert chain(built, "104") == []


def test_app_role_can_propagate_but_not_read_ontology(built):
    flight_id = fid(built, "101")
    built.execute("SET ROLE flightops_app")
    try:
        assert built.execute("select count(*) from app_read.propagate(%s)", (flight_id,)).fetchone() == (5,)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            built.execute("select 1 from ontology.min_turn")
    finally:
        built.execute("RESET ROLE")


def test_start_without_an_arrival_returns_nothing(built):
    built.execute("update ontology.flight set actual_arr_utc = null where flight_number = '101'")
    assert chain(built, "101") == []


def test_unknown_percentile_is_rejected(built):
    with pytest.raises(psycopg.errors.InvalidParameterValue):
        chain(built, "101", None, 75)
