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
