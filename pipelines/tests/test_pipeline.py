import pytest

from flightops import pipeline
from flightops.dq import checks


@pytest.fixture
def loaded(conn, load_fixture):
    load_fixture("ourairports_airports", "airports.csv")
    load_fixture("bts_ontime", "bts_awkward.csv")
    load_fixture("faa_master", "faa_master.csv")
    load_fixture("faa_dereg", "faa_dereg.csv")
    load_fixture("faa_acftref", "faa_acftref.csv")
    load_fixture("iem_metar", "metar.csv")
    load_fixture("iem_taf", "taf.csv")
    return conn


def count(conn, table):
    return conn.execute(f"select count(*) from {table}").fetchone()[0]


def test_build_promotes_every_flight(loaded):
    pipeline.build(loaded)
    assert count(loaded, "ontology.flight") == 10
    assert loaded.execute(
        "select a.iata_code from ontology.flight f join ontology.airport a on a.airport_id = f.origin_airport_id "
        "where f.flight_number = '9'"
    ).fetchone()[0] == "PBI"


def test_delay_has_one_row_per_reported_nonzero_cause(loaded):
    pipeline.build(loaded)
    rows = loaded.execute(
        "select d.cause, d.minutes from ontology.delay d join ontology.flight f using (flight_id) order by 1"
    ).fetchall()
    assert rows == [("carrier", 10), ("late_aircraft", 15)]


def test_weather_joins_through_the_airport_table(loaded):
    pipeline.build(loaded)
    assert count(loaded, "ontology.weather_observation") == 2
    assert count(loaded, "ontology.taf_forecast") == 2


def test_unresolved_tails_are_recorded_with_a_reason(loaded):
    pipeline.build(loaded)
    reasons = {r[0] for r in loaded.execute("select reason from dq.unresolved_link where entity = 'tail'")}
    assert reasons == {"no_faa_record"}


def test_rebuild_is_identical(loaded):
    pipeline.build(loaded)
    query = "select flight_id, flight_number, aircraft_id from ontology.flight order by 1"
    first = loaded.execute(query).fetchall()
    pipeline.build(loaded)
    assert loaded.execute(query).fetchall() == first


def test_failed_blocking_check_keeps_the_previous_ontology(loaded):
    pipeline.build(loaded)
    loaded.execute("delete from staging.airport_code_alias")
    with pytest.raises(checks.BlockingCheckFailed, match="flights_reconcile"):
        pipeline.build(loaded)
    assert count(loaded, "ontology.flight") == 10
    failed = {r[0] for r in loaded.execute("select name from dq.check_result where not passed")}
    assert "flights_reconcile" in failed


def test_delay_causes_that_do_not_add_up_block_promotion(loaded):
    loaded.execute("update raw.bts_ontime set carrierdelay = '11.00' where flight_number_reporting_airline = '8'")
    with pytest.raises(checks.BlockingCheckFailed, match="delay_causes_add_up"):
        pipeline.build(loaded)
