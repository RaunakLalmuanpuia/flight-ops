from flightops import pipeline


def test_min_turn_percentiles_per_carrier_and_overall(conn, load_fixture):
    load_fixture("ourairports_airports", "airports.csv")
    load_fixture("bts_ontime", "bts_min_turn.csv")
    pipeline.build(conn)
    rows = conn.execute(
        "select c.code, m.samples, m.p10, m.p25, m.p50 from ontology.min_turn m "
        "left join ontology.carrier c using (carrier_id) order by c.code nulls last"
    ).fetchall()
    # DL samples 40/50/60; zero-cause, blank-cause and non-connecting turns are excluded.
    # All carriers adds WN's 35. p10 is 36.5, and round(numeric) takes it up to 37.
    assert rows == [("DL", 3, 42, 45, 50), ("WN", 1, 35, 35, 35), (None, 4, 37, 39, 45)]


def test_rebuild_replaces_min_turn(conn, load_fixture):
    load_fixture("ourairports_airports", "airports.csv")
    load_fixture("bts_ontime", "bts_min_turn.csv")
    pipeline.build(conn)
    pipeline.build(conn)
    assert conn.execute("select count(*) from ontology.min_turn").fetchone() == (3,)
