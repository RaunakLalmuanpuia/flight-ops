from flightops import db


def test_migrate_creates_schemas_and_run_table(conn):
    schemas = {r[0] for r in conn.execute("select schema_name from information_schema.schemata")}
    assert {"raw", "staging", "ontology", "dq"} <= schemas
    assert conn.execute("select count(*) from dq.ingestion_run").fetchone()[0] == 0


def test_migrate_twice_applies_nothing(conn):
    assert db.migrate(conn) == []
