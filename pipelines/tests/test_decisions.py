import psycopg
import pytest

from flightops import pipeline

SNAP = "depth, kind, flight_number, slack_min, predicted_dep_delay, at_risk, stop_reason"


@pytest.fixture
def built(conn, load_fixture):
    # Same setup as test_propagate, so flight 101's chain is known: 102 +40, 103 +50, 104 cancelled, 105 absorbed.
    load_fixture("ourairports_airports", "airports.csv")
    load_fixture("bts_ontime", "bts_propagate.csv")
    pipeline.build(conn)
    conn.execute("truncate ontology.min_turn")
    conn.execute(
        "insert into ontology.min_turn (carrier_id, samples, p10, p25, p50) "
        "select carrier_id, 500, 40, 30, 60 from ontology.carrier where code = 'DL' "
        "union all select null, 1000, 45, 20, 70"
    )
    return conn


def fid(conn, number):
    return conn.execute("select flight_id from ontology.flight where flight_number = %s", (number,)).fetchone()[0]


def record(conn, number, action="accept_delay", target=None, delay=None, reason="inbound late", author="duty controller"):
    target_id = fid(conn, target) if target else None
    return conn.execute(
        "select app_read.record_decision(%s, %s, %s, %s, %s, %s)",
        (fid(conn, number), delay, action, target_id, reason, author),
    ).fetchone()[0]


def test_snapshot_is_the_propagated_chain(built):
    d = record(built, "101")
    snap = built.execute(
        f"select {SNAP} from app.decision_leg where decision_id = %s order by depth, kind = 'flown', sched_dep_utc", (d,)
    ).fetchall()
    assert snap == built.execute(f"select {SNAP} from app_read.propagate(%s)", (fid(built, "101"),)).fetchall()
    assert [r[2] for r in snap] == ["101", "102", "103", "104", "105"]
    assert built.execute(
        "select arr_delay_min, what_if, percentile, action, target_flight_id from app.decision where decision_id = %s", (d,)
    ).fetchone() == (60, False, 10, "accept_delay", None)


def test_what_if_delay_is_frozen_with_its_chain(built):
    d = record(built, "101", delay=0)
    assert built.execute("select arr_delay_min, what_if from app.decision where decision_id = %s", (d,)).fetchone() == (0, True)
    assert built.execute(
        "select flight_number, stop_reason from app.decision_leg where decision_id = %s order by depth", (d,)
    ).fetchall() == [("101", None), ("102", "absorbed")]


def test_reason_and_author_are_trimmed(built):
    d = record(built, "101", reason="  inbound late ", author=" duty controller ")
    assert built.execute("select reason, author from app.decision where decision_id = %s", (d,)).fetchone() == (
        "inbound late",
        "duty controller",
    )


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"action": "accept_delay", "target": "102"}, "takes no target"),
        ({"action": "cancel_leg", "target": "201"}, "not a later leg"),
        ({"action": "cancel_leg", "target": "101"}, "not a later leg"),
        ({"reason": "  "}, "reason is required"),
        ({"author": ""}, "author is required"),
    ],
)
def test_refusals_record_nothing(built, kwargs, message):
    with pytest.raises(psycopg.errors.RaiseException, match=message):
        record(built, "101", **kwargs)
    assert built.execute("select count(*) from app.decision").fetchone() == (0,)
    assert built.execute("select count(*) from app.decision_leg").fetchone() == (0,)


def test_cancelled_flight_has_no_chain_to_decide_on(built):
    with pytest.raises(psycopg.errors.RaiseException, match="no arrival to propagate"):
        record(built, "104")
    assert built.execute("select count(*) from app.decision").fetchone() == (0,)


def test_what_if_on_a_diverted_flight_is_refused(built):
    built.execute("update ontology.flight set diverted = true where flight_number = '101'")
    with pytest.raises(psycopg.errors.RaiseException, match="diverted"):
        record(built, "101", delay=30)


def test_unknown_action_is_refused(built):
    with pytest.raises(psycopg.errors.CheckViolation):
        record(built, "101", action="ground_stop")


def test_app_role_records_only_through_the_function(built):
    flight_id = fid(built, "101")
    built.execute("SET ROLE flightops_app")
    try:
        built.execute(
            "select app_read.record_decision(%s, null, 'accept_delay', null, 'inbound late', 'duty controller')", (flight_id,)
        )
        for stmt in (
            "insert into app.decision (flight_id, what_if, percentile, action, reason, author) "
            "values (1, false, 10, 'other', 'x', 'x')",
            "update app.decision set reason = 'edited'",
            "delete from app.decision",
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                built.execute(stmt)
    finally:
        built.execute("RESET ROLE")
    assert built.execute("select reason from app.decision").fetchall() == [("inbound late",)]
