import csv
import hashlib
import re
from pathlib import Path
from typing import NamedTuple

from psycopg import sql

PROVENANCE = ("source_file", "source_sha256", "loaded_at")


class LoadResult(NamedTuple):
    rows: int
    skipped: bool


def normalize_header(header: list[str]) -> list[str]:
    cols = list(header)
    while cols and not cols[-1].strip():  # BTS and FAA rows end in a trailing comma
        cols.pop()
    return [re.sub(r"[^a-z0-9]+", "_", c.strip().lower()).strip("_") for c in cols]


def _open(path: Path):
    return path.open(newline="", encoding="utf-8-sig")


def create_table_sql(table: str, path: Path) -> str:
    with _open(path) as f:
        cols = normalize_header(next(csv.reader(f)))
    lines = [f'    "{c}" text' for c in cols]
    lines += [
        "    source_file text NOT NULL",
        "    source_sha256 text NOT NULL",
        "    loaded_at timestamptz NOT NULL DEFAULT now()",
    ]
    return f"CREATE TABLE raw.{table} (\n" + ",\n".join(lines) + "\n);\n"


def _table_columns(conn, table: str) -> list[str]:
    rows = conn.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'raw' AND table_name = %s ORDER BY ordinal_position",
        (table,),
    )
    return [r[0] for r in rows if r[0] not in PROVENANCE]


def load_file(conn, source: str, table: str, path: Path) -> LoadResult:
    with path.open("rb") as f:
        digest = hashlib.file_digest(f, "sha256").hexdigest()
    with conn.transaction():
        prior = conn.execute(
            "SELECT row_count FROM dq.ingestion_run WHERE table_name = %s AND source_sha256 = %s",
            (table, digest),
        ).fetchone()
        if prior:
            return LoadResult(prior[0], True)

        rows = 0
        with _open(path) as f:
            reader = csv.reader(f)
            cols = normalize_header(next(reader))
            expected = _table_columns(conn, table)
            if cols != expected:
                raise ValueError(f"{path}: columns {cols} do not match raw.{table} {expected}")
            target = sql.SQL("COPY raw.{} ({}) FROM STDIN").format(
                sql.Identifier(table),
                sql.SQL(", ").join(map(sql.Identifier, [*cols, "source_file", "source_sha256"])),
            )
            with conn.cursor() as cur, cur.copy(target) as copy:
                for row in reader:
                    if not row:
                        continue
                    if len(row) < len(cols) or any(row[len(cols):]):
                        raise ValueError(f"{path}:{reader.line_num}: expected {len(cols)} fields, got {len(row)}")
                    copy.write_row([*row[: len(cols)], path.name, digest])
                    rows += 1
        conn.execute(
            "INSERT INTO dq.ingestion_run (source, table_name, source_file, source_sha256, row_count) "
            "VALUES (%s, %s, %s, %s, %s)",
            (source, table, path.name, digest, rows),
        )
    return LoadResult(rows, False)
