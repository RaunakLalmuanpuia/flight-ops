import csv
import hashlib
import re
from pathlib import Path
from typing import NamedTuple

from psycopg import sql

PROVENANCE = ("source_file", "source_sha256", "loaded_at")
MAX_QUARANTINED = 10  # more than this means a broken file, not a few bad rows


class LoadResult(NamedTuple):
    rows: int
    skipped: bool
    quarantined: int = 0


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
            "SELECT row_count, quarantined_count FROM dq.ingestion_run WHERE table_name = %s AND source_sha256 = %s",
            (table, digest),
        ).fetchone()
        if prior:
            return LoadResult(prior[0], True, prior[1])

        rows = 0
        quarantined = []
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
                        quarantined.append((reader.line_num, f"expected {len(cols)} fields, got {len(row)}", row))
                        if len(quarantined) > MAX_QUARANTINED:
                            raise ValueError(f"{path}: more than {MAX_QUARANTINED} malformed rows, last at line {reader.line_num}")
                        continue
                    copy.write_row([*row[: len(cols)], path.name, digest])
                    rows += 1
        run_id = conn.execute(
            "INSERT INTO dq.ingestion_run (source, table_name, source_file, source_sha256, row_count, quarantined_count) "
            "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
            (source, table, path.name, digest, rows, len(quarantined)),
        ).fetchone()[0]
        for line, reason, fields in quarantined:
            conn.execute(
                "INSERT INTO dq.quarantined_row (ingestion_run_id, line_number, reason, fields) "
                "VALUES (%s, %s, %s, %s)",
                (run_id, line, reason, fields),
            )
    return LoadResult(rows, False, len(quarantined))


def write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    part = path.with_name(path.name + ".part")  # never leave a partial file under the real name
    try:
        with part.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, columns)  # raises on a field we don't expect
            writer.writeheader()
            writer.writerows(rows)
    except ValueError:
        part.unlink()
        raise
    part.rename(path)
