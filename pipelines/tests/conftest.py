import csv
import os
from pathlib import Path

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo

from flightops import db

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def conn():
    url = os.environ["DATABASE_URL"]
    with psycopg.connect(url, autocommit=True) as admin:
        admin.execute("DROP DATABASE IF EXISTS flightops_test WITH (FORCE)")
        admin.execute("CREATE DATABASE flightops_test")
    with db.connect(make_conninfo(url, dbname="flightops_test")) as c:
        db.migrate(c)
        yield c


@pytest.fixture
def load_fixture(conn):
    """Load a fixture holding only the columns a test cares about, as if it were a delivery."""

    def load(table: str, filename: str) -> None:
        with (FIXTURES / filename).open(newline="") as f:
            reader = csv.reader(f)
            cols = next(reader)
            stmt = sql.SQL("COPY raw.{} ({}) FROM STDIN").format(
                sql.Identifier(table),
                sql.SQL(", ").join(map(sql.Identifier, [*cols, "source_file", "source_sha256"])),
            )
            rows = 0
            with conn.cursor() as cur, cur.copy(stmt) as copy:
                for row in reader:
                    copy.write_row([*row, filename, filename])
                    rows += 1
        conn.execute(
            "INSERT INTO dq.ingestion_run (source, table_name, source_file, source_sha256, row_count) "
            "VALUES ('fixture', %s, %s, %s, %s)",
            (table, filename, filename, rows),
        )

    return load
