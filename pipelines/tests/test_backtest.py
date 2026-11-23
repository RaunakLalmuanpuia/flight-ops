import pytest

from flightops import pipeline

COLS = """l.flight_number, s.flight_number, b.depth, b.period, b.late_arr_delay, b.predicted_dep_delay,
          b.actual_dep_delay, b.actual_late_aircraft, b.swapped"""


@pytest.fixture
def built(conn, load_fixture):
    load_fixture("ourairports_airports", "airports.csv")
    load_fixture("bts_ontime", "bts_backtest.csv")
    pipeline.build(conn)
    # Fixed turns so the arithmetic is readable; the fixture alone is too small to measure them.
    conn.execute("truncate ontology.min_turn")
    conn.execute(
        "insert into ontology.min_turn (carrier_id, samples, p5, p10, p25, p50) "
        "select carrier_id, 500, 30, 30, 40, 60 from ontology.carrier where code = 'DL' "
        "union all select null, 1000, 20, 20, 45, 70"
    )
    pipeline.run_sql(conn, "rotations/backtest.sql")
    return conn


def rows(conn, percentile):
    return conn.execute(
        f"select {COLS} from ontology.propagation_backtest b "
        "join ontology.flight l on l.flight_id = b.late_flight_id "
        "join ontology.flight s on s.flight_id = b.scored_flight_id "
        "where b.percentile = %s order by 1, 3",
        (percentile,),
    ).fetchall()


def test_backtest_scores_pairs_from_rotation_legs(built):
    assert rows(built, 25) == [
        ("101", "102", 1, "july_normal", 60, 40, 45, 45, False),
        ("101", "103", 2, "july_normal", 60, 0, -5, None, False),  # absorbed here
        ("101", "104", 3, "july_normal", 60, 0, 20, 0, False),  # past absorbed, propagate returned no row
        ("102", "103", 1, "july_normal", 45, 0, -5, None, False),
        ("102", "104", 2, "july_normal", 45, 0, 20, 0, False),
        ("102", "105", 3, "july_normal", 45, 0, 0, None, False),
        ("104", "105", 1, "july_normal", 20, 0, 0, None, False),
        ("401", "402", 1, "july_outage", 60, 280, 300, 300, True),
        ("501", "502", 1, "august", 60, 40, 45, 45, False),  # 11:00 arrival + DL p25 40 against an 11:00 departure
        # 201: break at depth 1, so 202 and 203 are excluded. 301: limit. 101->105 is depth 4.
    ]


def test_each_percentile_is_scored(built):
    assert rows(built, 50)[0][5] == 60
    assert rows(built, 10)[0][5] == 30


def test_rebuild_replaces_backtest(built):
    pipeline.run_sql(built, "rotations/backtest.sql")
    assert built.execute("select count(*) from ontology.propagation_backtest").fetchone() == (36,)  # 9 pairs x 4 percentiles


def test_no_min_turn_leaves_backtest_empty_instead_of_raising(built):
    built.execute("truncate ontology.min_turn")
    pipeline.run_sql(built, "rotations/backtest.sql")  # propagate would raise NoDataFound without the guard
    assert built.execute("select count(*) from ontology.propagation_backtest").fetchone() == (0,)
