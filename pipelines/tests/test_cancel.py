import pytest

from flightops import pipeline

COLS = """i.flight_number, t.flight_number, b.rank, b.period, b.delay_bucket, round(b.stress, 3)::float8,
          b.stress_bucket, round(b.predicted_rate, 3)::float8, b.basis, b.basis_samples,
          round(b.carrier_rate, 3)::float8, round(b.delay_rate, 3)::float8, b.actual_cancelled"""


@pytest.fixture
def built(conn, load_fixture):
    load_fixture("ourairports_airports", "airports.csv")
    load_fixture("bts_ontime", "bts_cancel.csv")
    pipeline.build(conn)
    return conn


def rows(conn):
    return conn.execute(
        f"select {COLS} from ontology.cancel_backtest b "
        "join ontology.flight i on i.flight_id = b.inbound_flight_id "
        "join ontology.flight t on t.flight_id = b.target_flight_id order by 1, 3"
    ).fetchall()


def test_buckets_at_their_edges(conn):
    got = conn.execute(
        "select ontology.delay_bucket(d) from unnest(array[-5, 14, 15, 59, 60, 119, 120, 239, 240, null]) d"
    ).fetchall()
    assert [g[0] for g in got] == ["<15", "<15", "15-59", "15-59", "60-119", "60-119", "120-239", "120-239", "240+", None]
    got = conn.execute(
        "select ontology.stress_bucket(s) from unnest(array[0, 0.0199, 0.02, 0.0999, 0.1, 1]::numeric[]) s"
    ).fetchall()
    assert [g[0] for g in got] == ["<2%", "<2%", "2-10%", "2-10%", "10%+", "10%+"]


def test_backtest_pairs_features_and_fallback_to_all_carriers(built):
    # July DL pairs give 7 samples, 4 cancelled, so the DL constant baseline is 0.571.
    # Every carrier cell is under 200 samples, so every rate comes from the all-carrier cell.
    assert rows(built) == [
        # Ranks follow the schedule: two cancelled legs come before the flown 104.
        # Stress 1/3: own-tail 100 and 101 are excluded, 903 (after the window) and WN 601 don't count.
        ("101", "102", 1, "july_normal", "120-239", 0.333, "10%+", 1.0, "all carriers", 1, 0.571, 1.0, True),
        ("101", "103", 2, "july_normal", "120-239", 0.333, "10%+", 1.0, "all carriers", 1, 0.571, 1.0, True),
        ("101", "104", 3, "july_normal", "120-239", 0.333, "10%+", 0.0, "all carriers", 1, 0.571, 0.0, False),
        # 15 min late is in 15-59. No departures in its window counts as stress 0. 203 is past the 24h cut.
        ("201", "202", 1, "july_normal", "15-59", 0.0, "<2%", 0.0, "all carriers", 1, 0.571, 0.0, False),
        ("202", "203", 1, "july_normal", "<15", 0.0, "<2%", 0.5, "all carriers", 2, 0.571, 0.5, False),
        # August is scored but not fitted, and July has no 60-119 cell, so there is no rate.
        ("501", "502", 1, "august", "60-119", 0.0, "<2%", None, None, None, 0.571, None, True),
        ("901", "902", 1, "july_normal", "<15", 0.0, "<2%", 0.5, "all carriers", 2, 0.571, 0.5, True),
        ("901", "903", 2, "july_normal", "<15", 0.0, "<2%", 1.0, "all carriers", 1, 0.571, 1.0, True),
    ]


def test_rate_table_is_fitted_on_july_only(built):
    got = built.execute(
        "select c.code, r.rank, r.delay_bucket, r.stress_bucket, r.samples, r.cancelled, round(r.rate, 3)::float8 "
        "from ontology.cancel_rate r left join ontology.carrier c using (carrier_id) "
        'order by c.code nulls last, r.delay_bucket collate "C", r.stress_bucket collate "C", r.rank'
    ).fetchall()
    cells = [
        (1, "120-239", "10%+", 1, 1, 1.0), (2, "120-239", "10%+", 1, 1, 1.0), (3, "120-239", "10%+", 1, 0, 0.0),
        (1, "15-59", "<2%", 1, 0, 0.0), (1, "<15", "<2%", 2, 1, 0.5), (2, "<15", "<2%", 1, 1, 1.0),
    ]  # no 60-119 cell: N5C's pair is in August
    assert got == [("DL", *c) for c in cells] + [(None, *c) for c in cells]


def test_carrier_cell_used_at_200_samples_and_all_carrier_cell_below(built):
    built.execute("truncate ontology.cancel_rate")
    built.execute(
        "insert into ontology.cancel_rate (carrier_id, rank, delay_bucket, stress_bucket, samples, cancelled, rate) "
        "select carrier_id, 1, '120-239', '10%+', 250, 100, 0.4 from ontology.carrier where code = 'DL' "
        "union all select null, 1, '120-239', '10%+', 1000, 300, 0.3 "
        "union all select carrier_id, 2, '120-239', '10%+', 150, 135, 0.9 from ontology.carrier where code = 'DL' "
        "union all select null, 2, '120-239', '10%+', 50, 10, 0.2"
    )
    pipeline.run_sql(built, "rotations/cancel_backtest.sql")
    got = [r[1:3] + r[7:10] for r in rows(built) if r[0] == "101"]
    assert got == [
        ("102", 1, 0.4, "carrier", 250),
        ("103", 2, 0.2, "all carriers", 50),  # the carrier cell has 150; the all-carrier cell is used under 200 too
        ("104", 3, None, None, None),  # no cell at all
    ]


def test_rebuild_replaces_rates_and_pairs(built):
    pipeline.build(built)
    assert built.execute("select count(*) from ontology.cancel_rate").fetchone() == (12,)
    assert built.execute("select count(*) from ontology.cancel_backtest").fetchone() == (8,)
