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
        "insert into ontology.min_turn (carrier_id, samples, p5, p10, p25, p50) "
        "select carrier_id, 500, 40, 40, 30, 60 from ontology.carrier where code = 'DL' "
        "union all select null, 1000, 45, 45, 20, 70"
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

def review(conn, decision_id, cols):
    return conn.execute(f"select {cols} from app_read.decision_review where decision_id = %s", (decision_id,)).fetchone()


@pytest.mark.parametrize(
    "action, target, label",
    [
        ("cancel_leg", "104", "airline did the same"),
        ("cancel_leg", "102", "airline flew it, +45 min"),
        ("hold_departure", "103", "flown, +60 min vs predicted +50"),
        ("hold_departure", "104", "airline cancelled it"),
        ("other", "105", "flown, +0 min vs predicted +0"),
        ("swap_aircraft", "102", "this tail flew it, +45 min (swap not visible)"),
        ("swap_aircraft", "104", "airline cancelled it"),
    ],
)
def test_match_label_compares_the_target_with_bts(built, action, target, label):
    assert review(built, record(built, "101", action, target), "match_label") == (label,)


def test_target_without_a_prediction_says_so(built):
    d = record(built, "101", "hold_departure", "102")
    built.execute("update app.decision_leg set predicted_dep_delay = null where decision_id = %s and flight_number = '102'", (d,))
    assert review(built, d, "match_label") == ("flown, +45 min, no prediction",)


def test_accept_delay_has_chain_totals_and_no_label(built):
    d = record(built, "101")
    assert review(built, d, "flight_number, match_label, predicted_at_risk, actually_late, cancelled") == ("101", None, 2, 2, 1)


def test_review_keeps_the_prediction_after_the_model_changes(built):
    d = record(built, "101", "hold_departure", "102")
    built.execute("update ontology.min_turn set p10 = 90")
    assert review(built, d, "target_predicted_dep_delay, match_label") == (40, "flown, +45 min vs predicted +40")


def test_legs_sit_beside_their_actuals(built):
    d = record(built, "101", "cancel_leg", "104")
    assert built.execute(
        "select flight_number, is_target, actual_cancelled, actual_dep_delay from app_read.decision_legs "
        "where decision_id = %s order by depth, kind = 'flown'",
        (d,),
    ).fetchall() == [
        ("101", False, False, 60),
        ("102", False, False, 45),
        ("103", False, False, 60),
        ("104", True, True, None),
        ("105", False, False, 0),
    ]


def test_log_survives_a_rebuild_and_rematches(built):
    d = record(built, "101", "cancel_leg", "104")
    pipeline.build(built)
    assert built.execute("select count(*) from app.decision_leg where decision_id = %s", (d,)).fetchone() == (5,)
    assert review(built, d, "flight_found, current_flight_id, match_label") == (True, fid(built, "101"), "airline did the same")


def test_rematch_uses_the_natural_key_not_the_old_id(built):
    d = record(built, "101", "cancel_leg", "104")
    # A rebuild that renumbered every flight: the frozen ids no longer point at the same rows.
    built.execute("update app.decision set flight_id = flight_id + 1000, target_flight_id = target_flight_id + 1000")
    built.execute("update app.decision_leg set flight_id = flight_id + 1000")
    assert review(built, d, "current_flight_id, match_label") == (fid(built, "101"), "airline did the same")


@pytest.mark.parametrize("action, target", [("accept_delay", None), ("cancel_leg", "104")])
def test_flight_gone_after_rebuild_is_labelled_not_dropped(built, action, target):
    d = record(built, "101", action, target)
    built.execute("update app.decision_leg set flight_number = '999' where decision_id = %s and depth = 0", (d,))
    assert review(built, d, "flight_found, match_label") == (False, "flight not found after rebuild")


def test_app_role_reads_the_review(built):
    record(built, "101")
    built.execute("SET ROLE flightops_app")
    try:
        assert built.execute("select count(*) from app_read.decision_review").fetchone() == (1,)
        assert built.execute("select count(*) from app_read.decision_legs").fetchone() == (5,)
    finally:
        built.execute("RESET ROLE")
