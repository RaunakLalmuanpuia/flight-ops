import pytest

from flightops import pipeline


@pytest.fixture
def legs(conn, load_fixture):
    load_fixture("ourairports_airports", "airports.csv")
    load_fixture("bts_ontime", "bts_rotation.csv")
    pipeline.build(conn)
    rows = conn.execute(
        "select f.flight_number, r.leg_seq, r.connects, r.break_cause, r.touched_atl "
        "from ontology.rotation_leg r join ontology.flight f using (flight_id)"
    ).fetchall()
    return {r[0]: r[1:] for r in rows}


def test_cancelled_flight_never_joins_a_rotation(legs):
    assert "2" not in legs


def test_first_leg_has_nothing_to_connect_to(legs):
    assert legs["1"] == (1, None, None, True)


def test_consecutive_legs_connect_across_a_cancelled_flight(legs):
    assert legs["3"] == (2, True, None, True)


def test_station_mismatch_is_a_labelled_gap(legs):
    assert legs["4"] == (3, False, "likely_unreported_flying", True)


def test_tails_that_never_touched_atl_are_flagged_not_dropped(legs):
    assert legs["5"][-1] is False
    assert legs["6"] == (2, True, None, False)


def test_diversion_connects_from_where_it_actually_landed(legs):
    assert legs["8"] == (2, True, None, True)


def test_gap_after_a_short_diversion_uses_the_diversion_label(conn, load_fixture):
    load_fixture("ourairports_airports", "airports.csv")
    load_fixture("bts_ontime", "bts_diversion_break.csv")
    pipeline.build(conn)
    cause = conn.execute(
        "select r.break_cause from ontology.rotation_leg r join ontology.flight f using (flight_id) "
        "where f.flight_number = '2'"
    ).fetchone()[0]
    assert cause == "after_diversion"


def test_atl_view_excludes_other_tails(conn, legs):
    assert conn.execute(
        "select count(*) from ontology.atl_rotation_leg where tail_number = 'N2R'"
    ).fetchone()[0] == 0
