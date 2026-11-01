from pathlib import Path

import psycopg
import pytest

from flightops.sources import raw

SAMPLE = Path(__file__).parent / "fixtures" / "raw_sample.csv"


@pytest.fixture
def table(conn):
    conn.execute(raw.create_table_sql("sample", SAMPLE))
    return "sample"


def count(conn, sql):
    return conn.execute(sql).fetchone()[0]


def test_normalize_header_handles_faa_and_bts_shapes():
    assert raw.normalize_header(["N-NUMBER", " TYPE REGISTRANT ", "Div1Airport", ""]) == [
        "n_number", "type_registrant", "div1airport",
    ]


def test_load_keeps_values_as_delivered_with_provenance(conn, table):
    assert raw.load_file(conn, "test", table, SAMPLE) == raw.LoadResult(2, False)
    rows = conn.execute(
        "select n_number, note, source_file, length(source_sha256) from raw.sample order by 1"
    ).fetchall()
    assert rows == [
        ("123AB", "late, inbound", "raw_sample.csv", 64),
        ("456CD", "", "raw_sample.csv", 64),
    ]
    assert count(conn, "select count(*) from raw.sample where loaded_at is null") == 0


def test_reload_changes_nothing(conn, table):
    raw.load_file(conn, "test", table, SAMPLE)
    assert raw.load_file(conn, "test", table, SAMPLE) == raw.LoadResult(2, True)
    assert count(conn, "select count(*) from raw.sample") == 2
    assert count(conn, "select count(*) from dq.ingestion_run") == 1


def test_changed_file_is_appended_as_a_new_delivery(conn, table, tmp_path):
    raw.load_file(conn, "test", table, SAMPLE)
    changed = tmp_path / "raw_sample.csv"
    changed.write_text(SAMPLE.read_text() + "789EF,2024-07-21,,\n")
    assert raw.load_file(conn, "test", table, changed) == raw.LoadResult(3, False)
    assert count(conn, "select count(*) from raw.sample") == 5
    assert count(conn, "select count(distinct source_sha256) from raw.sample") == 2


def test_header_drift_is_refused(conn, table, tmp_path):
    drifted = tmp_path / "drifted.csv"
    drifted.write_text("N-NUMBER,Other\n123AB,x\n")
    with pytest.raises(ValueError, match="columns"):
        raw.load_file(conn, "test", table, drifted)


@pytest.mark.parametrize("bad_row", ["123AB", "123AB,2024-07-19,x,y"])
def test_malformed_row_rolls_back_the_whole_file(conn, table, tmp_path, bad_row):
    bad = tmp_path / "bad.csv"
    bad.write_text(f"N-NUMBER,Flight Date,Note,\n456CD,2024-07-20,,\n{bad_row}\n")
    with pytest.raises((ValueError, psycopg.Error)):
        raw.load_file(conn, "test", table, bad)
    assert count(conn, "select count(*) from raw.sample") == 0
    assert count(conn, "select count(*) from dq.ingestion_run") == 0
