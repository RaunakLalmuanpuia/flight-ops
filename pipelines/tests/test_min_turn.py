from flightops import pipeline


def test_min_turn_percentiles_per_carrier_and_overall(conn, load_fixture):
    load_fixture("ourairports_airports", "airports.csv")
    load_fixture("bts_ontime", "bts_min_turn.csv")
    pipeline.build(conn)
    rows = conn.execute(
        "select c.code, m.samples, m.p5, m.p10, m.p25, m.p50 from ontology.min_turn m "
        "left join ontology.carrier c using (carrier_id) order by c.code nulls last"
    ).fetchall()
    # DL samples 40/50/60; zero-cause, blank-cause and non-connecting turns are excluded.
    # N4M's 45-min turn is in August, outside the July fit, so DL keeps 3 samples.
    # All carriers adds WN's 35. p10 is 36.5 and p5 35.75, so round(numeric) takes them to 37 and 36.
    assert rows == [("DL", 3, 41, 42, 45, 50), ("WN", 1, 35, 35, 35, 35), (None, 4, 36, 37, 39, 45)]


def test_rebuild_replaces_min_turn(conn, load_fixture):
    load_fixture("ourairports_airports", "airports.csv")
    load_fixture("bts_ontime", "bts_min_turn.csv")
    pipeline.build(conn)
    pipeline.build(conn)
    assert conn.execute("select count(*) from ontology.min_turn").fetchone() == (3,)


def test_period_labels_july_outage_and_august(conn):
    days = ["2024-07-18", "2024-07-19", "2024-07-23", "2024-07-24", "2024-08-01", "2024-08-31", "2024-09-01"]
    got = conn.execute("select ontology.period(d::date) from unnest(%s::text[]) d", (days,)).fetchall()
    assert [g[0] for g in got] == [
        "july_normal", "july_outage", "july_outage", "july_normal", "august", "august", None,
    ]


def test_debby_period_sits_inside_august(conn):
    got = conn.execute(
        "select ontology.period('2024-08-01'), ontology.period('2024-08-02'), ontology.period('2024-08-06'), "
        "ontology.period('2024-08-07')"
    ).fetchone()
    assert got == ("august", "debby", "debby", "august")
