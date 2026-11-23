import pytest

from flightops import pipeline

RISK = "depth, kind, flight_number, round(cancel_risk, 3)::float8, cancel_risk_basis"


@pytest.fixture
def built(conn, load_fixture):
    load_fixture("ourairports_airports", "airports.csv")
    load_fixture("bts_ontime", "bts_cancel_risk.csv")
    pipeline.build(conn)
    # Fixed turns and rates: the fixture is far too small to fit either.
    conn.execute("truncate ontology.min_turn")
    conn.execute(
        "insert into ontology.min_turn (carrier_id, samples, p5, p10, p25, p50) "
        "select carrier_id, 500, 40, 40, 30, 60 from ontology.carrier where code = 'DL' "
        "union all select null, 1000, 45, 45, 20, 70"
    )
    conn.execute("truncate ontology.cancel_rate")
    conn.execute(
        "insert into ontology.cancel_rate (carrier_id, rank, delay_bucket, stress_bucket, samples, cancelled, rate) "
        "select carrier_id, 1, '120-239', '<2%', 300, 75, 0.25 from ontology.carrier where code = 'DL' "
        "union all select null, 1, '120-239', '<2%', 2000, 400, 0.20 "
        "union all select null, 2, '120-239', '<2%', 1000, 190, 0.19 "
        "union all select carrier_id, 3, '120-239', '<2%', 150, 30, 0.20 from ontology.carrier where code = 'DL' "
        "union all select null, 3, '120-239', '<2%', 40, 4, 0.10 "
        "union all select carrier_id, 1, '240+', '<2%', 250, 150, 0.60 from ontology.carrier where code = 'DL' "
        "union all select null, 2, '<15', '<2%', 500, 25, 0.05"
    )
    pipeline.run_sql(conn, "rotations/cancel_backtest.sql")
    return conn


def fid(conn, number):
    return conn.execute("select flight_id from ontology.flight where flight_number = %s", (number,)).fetchone()[0]


def risk(conn, number, *args):
    return conn.execute(
        f"select {RISK} from app_read.propagate(%s{', %s' * len(args)})", (fid(conn, number), *args)
    ).fetchall()


def record(conn, number, delay=None):
    return conn.execute(
        "select app_read.record_decision(%s, %s, 'accept_delay', null, 'inbound late', 'duty controller')",
        (fid(conn, number), delay),
    ).fetchone()[0]


def test_ranked_legs_are_scored_by_schedule_not_depth(built):
    assert risk(built, "801") == [
        (0, "selected", "801", None, None),
        # All three cancelled legs come back at depth 1, and they are ranks 1-3.
        (1, "cancelled", "802", 0.25, "DL, 300 samples"),
        (1, "cancelled", "803", 0.19, "all carriers, 1000 samples"),  # no DL cell
        (1, "cancelled", "804", 0.1, "all carriers, 40 samples"),  # the DL cell has 150
        (1, "flown", "805", None, None),  # rank 4
    ]


def test_rates_match_the_backtest(built):
    got = built.execute(
        "select round(predicted_rate, 3)::float8 from ontology.cancel_backtest where inbound_flight_id = %s order by rank",
        (fid(built, "801"),),
    ).fetchall()
    assert [g[0] for g in got] == [0.25, 0.19, 0.1]


def test_what_if_changes_only_the_delay_bucket(built):
    assert risk(built, "801", 300) == [
        (0, "selected", "801", None, None),
        (1, "cancelled", "802", 0.6, "DL, 250 samples"),
        (1, "cancelled", "803", None, "not scored: no July cell"),
        (1, "cancelled", "804", None, "not scored: no July cell"),
        (1, "flown", "805", None, None),
    ]


def test_diverted_start_is_not_scored(built):
    assert risk(built, "601") == [
        (0, "selected", "601", None, None),
        (1, "flown", "602", None, "not scored: diverted"),
    ]


def test_threshold_is_the_july_f1_maximum(built):
    assert float(built.execute("select app_read.cancel_risk_threshold()").fetchone()[0]) == 0.183


def test_decision_freezes_the_risk_and_counts_flagged_legs(built):
    d = record(built, "801")
    frozen = built.execute(
        f"select {RISK} from app.decision_leg where decision_id = %s order by depth, kind = 'flown', sched_dep_utc", (d,)
    ).fetchall()
    assert frozen == risk(built, "801")
    # 0.25 and 0.19 are at or above 0.183. 0.10 is not.
    assert built.execute(
        "select flagged_cancel_risk from app_read.decision_review where decision_id = %s", (d,)
    ).fetchone() == (2,)


def test_frozen_risk_survives_a_rate_change(built):
    d = record(built, "801")
    built.execute("update ontology.cancel_rate set rate = 0")
    assert built.execute(
        "select flagged_cancel_risk from app_read.decision_review where decision_id = %s", (d,)
    ).fetchone() == (2,)


def test_decisions_recorded_before_cancel_risk_read_as_null(built):
    d = record(built, "801")
    # Rows logged before migration 026 have these columns NULL.
    built.execute("update app.decision_leg set cancel_risk = null, cancel_risk_basis = null where decision_id = %s", (d,))
    assert built.execute(
        "select count(*) filter (where cancel_risk is not null or cancel_risk_basis is not null) "
        "from app_read.decision_legs where decision_id = %s",
        (d,),
    ).fetchone() == (0,)
    assert built.execute(
        "select flagged_cancel_risk from app_read.decision_review where decision_id = %s", (d,)
    ).fetchone() == (0,)


def test_app_role_reads_cancel_risk(built):
    flight_id = fid(built, "801")
    built.execute("SET ROLE flightops_app")
    try:
        assert built.execute(
            "select count(cancel_risk) from app_read.propagate(%s)", (flight_id,)
        ).fetchone() == (3,)
        built.execute(
            "select app_read.record_decision(%s, null, 'accept_delay', null, 'inbound late', 'duty controller')",
            (flight_id,),
        )
        assert built.execute("select flagged_cancel_risk from app_read.decision_review").fetchone() == (2,)
        assert built.execute("select app_read.cancel_risk_threshold()").fetchone() is not None
    finally:
        built.execute("RESET ROLE")


def test_scored_legs_outside_the_chain_come_back_as_scheduled(built):
    # 402 absorbs the delay, so the chain stops there and 403 and 404 have no chain row.
    assert risk(built, "401") == [
        (0, "selected", "401", None, None),
        (1, "flown", "402", None, "not scored: no July cell"),
        (None, "scheduled", "403", 0.05, "all carriers, 500 samples"),
        (None, "scheduled", "404", None, "not scored: no July cell"),
    ]


def test_scheduled_rows_carry_no_prediction(built):
    assert built.execute(
        "select min_turn, slack_min, predicted_dep_delay, predicted_arr_utc, at_risk, stop_reason "
        "from app_read.propagate(%s) where kind = 'scheduled'",
        (fid(built, "401"),),
    ).fetchall() == [(None,) * 6, (None,) * 6]


def test_scheduled_legs_are_frozen_but_stay_out_of_the_chain_totals(built):
    d = record(built, "401")
    assert built.execute(
        "select flight_number from app.decision_leg where decision_id = %s and depth is null order by flight_number", (d,)
    ).fetchall() == [("403",), ("404",)]
    # Both scheduled legs were cancelled, but the chain (402) wasn't, and 0.05 is under the threshold.
    assert built.execute(
        "select cancelled, flagged_cancel_risk, cancel_risk_recorded from app_read.decision_review where decision_id = %s", (d,)
    ).fetchone() == (0, 0, True)


def test_a_scheduled_leg_can_be_the_target(built):
    d = built.execute(
        "select app_read.record_decision(%s, null, 'cancel_leg', %s, 'protect the bank', 'duty controller')",
        (fid(built, "401"), fid(built, "403")),
    ).fetchone()[0]
    assert built.execute(
        "select target_kind, match_label from app_read.decision_review where decision_id = %s", (d,)
    ).fetchone() == ("scheduled", "airline did the same")
