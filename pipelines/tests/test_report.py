import pytest

from flightops import pipeline, report


@pytest.fixture
def built(conn, load_fixture):
    load_fixture("ourairports_airports", "airports.csv")
    load_fixture("bts_ontime", "bts_weather.csv")
    load_fixture("iem_metar", "metar_join.csv")
    pipeline.build(conn)
    return conn


def test_every_section_runs_and_has_a_heading(built):
    text = report.render(built)
    for heading, _, _ in report.SECTIONS:
        assert f"## {heading}" in text


def test_results_come_from_the_latest_run(built):
    pipeline.build(built)
    assert report.render(built).count("| flights_reconcile | 0 | True |") == 1


def test_each_table_shows_the_query_behind_it(built):
    assert "FROM dq.check_result" in report.render(built)


def test_empty_values_render_blank_not_none(built):
    assert "None" not in report.render(built)


def test_render_is_repeatable(built):
    assert report.render(built) == report.render(built)


def test_opensky_comparison_counts_atl_arrivals_by_utc_day(built, load_fixture):
    load_fixture("opensky_flight", "KATL_arrival_2024-07-19.csv")
    # a session timezone must not move flights between days
    built.execute("set timezone = 'Asia/Kolkata'")
    assert "| 2024-07-19 | 2 | 2 | 2 | 1 |" in report.render(built)


@pytest.fixture
def backtested(conn, load_fixture):
    load_fixture("ourairports_airports", "airports.csv")
    load_fixture("bts_ontime", "bts_backtest.csv")
    pipeline.build(conn)
    conn.execute("truncate ontology.min_turn")
    conn.execute(
        "insert into ontology.min_turn (carrier_id, samples, p5, p10, p25, p50) "
        "select carrier_id, 500, 30, 30, 40, 60 from ontology.carrier where code = 'DL' "
        "union all select null, 1000, 20, 20, 45, 70"
    )
    pipeline.run_sql(conn, "rotations/backtest.sql")
    return conn


def phase3(conn):
    return report.render(conn, *report.REPORTS["phase-3-report.md"])


def test_phase3_every_section_runs_and_has_a_heading(backtested):
    text = phase3(backtested)
    for heading, _, _ in report.P3_SECTIONS:
        assert f"## {heading}" in text
    assert "None" not in text


def test_phase3_counts_cancelled_legs_in_the_gap_and_swaps(backtested):
    text = phase3(backtested)
    # july_normal: 101, 102, 104, 301 late; july_outage: 201 (cancelled 204 in its gap), 401, 402; august: 501, 502.
    assert "| july_normal | 4 | 0 | 0.0 | 7 | 0 |" in text
    assert "| july_outage | 3 | 1 | 33.3 | 1 | 1 |" in text
    assert "| august | 2 | 0 | 0.0 | 1 | 0 |" in text


def test_phase3_scores_against_both_baselines(backtested):
    text = phase3(backtested)
    # depth 1, late_aircraft reported only on 102 (and 502): model at p10 predicts 30 vs 45, zero 45, carry 60.
    assert "| july_normal | 1 | 1 | 15.0 | 45.0 | 15.0 | 100.0 | 100.0 | 100.0 |" in text
    assert "| august | 1 | 1 | 15.0 | 45.0 | 15.0 | 100.0 | 100.0 | 100.0 |" in text


def test_phase3_min_turn_shows_p5(backtested):
    assert "| carrier | samples | p5 | p10 | p25 | p50 |" in phase3(backtested)


def test_report_percentile_is_propagates_default(conn):
    args = conn.execute("select pg_get_function_arguments('app_read.propagate'::regproc)").fetchone()[0]
    assert args.endswith(f"p_percentile integer DEFAULT {report.PERCENTILE}")
