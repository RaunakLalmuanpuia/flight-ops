# Phase 1, Steps 1-2: Foundation and Raw Load Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans and superpowers:test-driven-development. Use superpowers:verification-before-completion before calling a step done. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One command applies migrations, and another loads every July 2024 source file into `raw` as delivered. Loading the same file twice changes nothing.

**Architecture:** Pipelines run from a `uv` virtual environment in `pipelines/.venv` against the local Postgres. A small migration runner applies `db/migrations/*.sql`. One generic loader copies any delimited file into its `raw` table inside a single transaction, and records the file's SHA-256 in `dq.ingestion_run`, which is what makes reloads no-ops.

**Tech Stack:** Python 3.12, `uv`, `psycopg` 3, `pytest`, local Postgres 18 (Postgres.app).

## Global Constraints

- Pipelines are the only writers to `raw`, `staging`, `ontology` and `dq`. Schema changes go through `db/migrations/`.
- `raw` holds source rows as delivered, all text, plus `source_file`, `source_sha256` and `loaded_at`. Never edited.
- Downloaded files go in `data/raw/<source>/` and are gitignored. `.env` is gitignored.
- If a source refuses scripted downloads, download by hand. Never disguise the client.
- No PostGIS, orchestration or streaming.
- No Docker. Containerization is the final roadmap phase.
- Run `uv` commands from `pipelines/`, and `git` commands from the repo root.

## Findings from checks on 2026-11-01

| Source | Result |
|---|---|
| BTS `PREZIP/..._2024_7.zip` | HEAD 200, 34,427,174 bytes |
| FAA `ReleasableAircraft.zip` | **HEAD with curl returns 403.** Treat it as a hand download, per `DECISIONS.md` |
| OurAirports `airports.csv` | 200, 19 columns, including `icao_code` and `iata_code` |
| IEM `asos.py`, station `ATL` | Works. One day gave 312 rows, mostly 5-minute `AUTO ... MADISHF` |
| IEM `taf.py`, station `KATL` | Works. One row per forecast group, with `product_id` |

IEM's ASOS endpoint takes `ATL` while its TAF endpoint takes `KATL`. The weather pull covers June 30 to August 2 UTC, not just July. July 31 flights land on August 1 UTC, and the "latest METAR at or before" join in step 6 needs an observation before the first departure.

## File Structure

| Path | Responsibility |
|---|---|
| `.env.example`, `.gitignore` | Local settings and secret handling |
| `pipelines/pyproject.toml` | Python version and dependencies |
| `pipelines/flightops/db.py` | Connect and apply migrations |
| `pipelines/flightops/sources/raw.py` | Hash files, normalize headers, load a file into `raw` |
| `pipelines/flightops/sources/registry.py` | Which files exist, their URLs and raw tables |
| `pipelines/flightops/sources/fetch.py` | Download and unzip |
| `pipelines/flightops/__main__.py` | CLI: `migrate`, `ddl`, `fetch`, `load` |
| `db/migrations/001_foundation.sql` | Schemas and `dq.ingestion_run` |
| `db/migrations/002_raw_tables.sql` | Raw tables, generated once from real file headers |
| `docs/data-sources.md` | Field notes, written from the real files |

---

### Task 1: Local setup, schemas and migration runner

**Files:**
- Create: `.gitignore`, `.env.example`, `pipelines/pyproject.toml`, `pipelines/flightops/__init__.py`, `pipelines/flightops/db.py`, `pipelines/tests/conftest.py`, `pipelines/tests/test_db.py`, `db/migrations/001_foundation.sql`

**Interfaces:**
- Produces: `db.connect(url: str | None = None) -> psycopg.Connection` (autocommit, defaults to `DATABASE_URL`), `db.migrate(conn) -> list[str]` (names of the files applied), pytest fixture `conn` (a fresh migrated test database).

- [ ] **Step 1: Check Postgres is running**

Run: `pg_isready -h localhost`
Expected: `localhost:5432 - accepting connections`. If not, ask the user to start Postgres.app.

- [ ] **Step 2: Create the project files and database**

`.gitignore`:

```gitignore
.env
data/raw/
.venv/
__pycache__/
.pytest_cache/
```

`.env.example`:

```dotenv
DATABASE_URL=postgresql://localhost:5432/flightops
```

`pipelines/pyproject.toml`:

```toml
[project]
name = "flightops"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = ["psycopg[binary]>=3.2,<4"]

[dependency-groups]
dev = ["pytest>=8"]

[tool.uv]
package = false

[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
```

Then run from the repo root:

```bash
cp .env.example .env
createdb -h localhost flightops
mkdir -p pipelines/flightops && touch pipelines/flightops/__init__.py
(cd pipelines && uv sync)
```

Expected: `pipelines/.venv` and `pipelines/uv.lock` exist. `uv` downloads Python 3.12 or newer if needed.

- [ ] **Step 3: Write the failing test**

`pipelines/tests/conftest.py`:

```python
import os

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from flightops import db


@pytest.fixture
def conn():
    url = os.environ["DATABASE_URL"]
    with psycopg.connect(url, autocommit=True) as admin:
        admin.execute("DROP DATABASE IF EXISTS flightops_test WITH (FORCE)")
        admin.execute("CREATE DATABASE flightops_test")
    with db.connect(make_conninfo(url, dbname="flightops_test")) as c:
        db.migrate(c)
        yield c
```

`pipelines/tests/test_db.py`:

```python
from flightops import db


def test_migrate_creates_schemas_and_run_table(conn):
    schemas = {r[0] for r in conn.execute("select schema_name from information_schema.schemata")}
    assert {"raw", "staging", "ontology", "dq"} <= schemas
    assert conn.execute("select count(*) from dq.ingestion_run").fetchone()[0] == 0


def test_migrate_twice_applies_nothing(conn):
    assert db.migrate(conn) == []
```

- [ ] **Step 4: Run the test to verify it fails**

Run: `uv run --env-file ../.env pytest tests/test_db.py -v`
Expected: collection error, `flightops.db` does not exist.

- [ ] **Step 5: Implement**

`db/migrations/001_foundation.sql`:

```sql
CREATE SCHEMA raw;
CREATE SCHEMA staging;
CREATE SCHEMA ontology;
CREATE SCHEMA dq;

CREATE TABLE dq.ingestion_run (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source        text NOT NULL,
    table_name    text NOT NULL,
    source_file   text NOT NULL,
    source_sha256 text NOT NULL,
    row_count     bigint NOT NULL,
    loaded_at     timestamptz NOT NULL DEFAULT now(),
    UNIQUE (table_name, source_sha256)
);
```

`pipelines/flightops/db.py`:

```python
import os
from pathlib import Path

import psycopg

REPO = Path(__file__).resolve().parents[2]


def connect(url: str | None = None) -> psycopg.Connection:
    # autocommit so conn.transaction() is a real transaction, never a savepoint
    return psycopg.connect(url or os.environ["DATABASE_URL"], autocommit=True)


def migrate(conn: psycopg.Connection) -> list[str]:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS public.schema_migration ("
        "filename text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
    )
    done = {r[0] for r in conn.execute("SELECT filename FROM public.schema_migration")}
    applied = []
    for path in sorted((REPO / "db" / "migrations").glob("*.sql")):
        if path.name in done:
            continue
        with conn.transaction():
            conn.execute(path.read_text())
            conn.execute("INSERT INTO public.schema_migration (filename) VALUES (%s)", (path.name,))
        applied.append(path.name)
    return applied
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `uv run --env-file ../.env pytest tests/test_db.py -v`
Expected: 2 passed.

- [ ] **Step 7: Commit**

```bash
git add .gitignore .env.example pipelines db
git commit -m "feat: add local setup, schemas and migration runner"
```

---

### Task 2: Idempotent raw loader

**Files:**
- Create: `pipelines/flightops/sources/__init__.py`, `pipelines/flightops/sources/raw.py`, `pipelines/tests/test_raw.py`, `pipelines/tests/fixtures/raw_sample.csv`
- Modify: `DECISIONS.md`

**Interfaces:**
- Consumes: `conn` fixture.
- Produces: `raw.normalize_header(header: list[str]) -> list[str]`, `raw.create_table_sql(table: str, path: Path) -> str`, `raw.load_file(conn, source: str, table: str, path: Path) -> raw.LoadResult` where `LoadResult` is a NamedTuple of `rows: int, skipped: bool`.

- [ ] **Step 1: Write the failing tests**

`pipelines/tests/fixtures/raw_sample.csv` has awkward header names, the trailing blank column that BTS and FAA files are expected to have, a quoted comma and an empty value:

```csv
N-NUMBER,Flight Date,Note,
123AB,2024-07-19,"late, inbound",
456CD,2024-07-20,,
```

`pipelines/tests/test_raw.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --env-file ../.env pytest tests/test_raw.py -v`
Expected: collection error, `flightops.sources.raw` does not exist.

- [ ] **Step 3: Implement**

`pipelines/flightops/sources/raw.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --env-file ../.env pytest tests/test_raw.py -v`
Expected: all passed.

- [ ] **Step 5: Record the tradeoff**

Append to `DECISIONS.md`:

```markdown
## 2026-11-01: Key raw reloads on file hash, and append changed files
- **Chose:** a file already recorded in `dq.ingestion_run` by hash is skipped. A changed file with the same name, such as a newer FAA snapshot, is appended as a new delivery. Each file loads in one transaction.
- **Gave up:** raw tables with one current version of each row, so staging must pick a delivery by `source_sha256`. Failed loads roll back and leave no run record, only the error.
- **Revisit if:** repeated snapshots make raw too large, or failed attempts need to be reported in `dq`.
```

- [ ] **Step 6: Commit**

```bash
git add pipelines DECISIONS.md
git commit -m "feat: add idempotent raw file loader"
```

---

### Task 3: Source registry, fetch and CLI

**Files:**
- Create: `pipelines/flightops/sources/registry.py`, `pipelines/flightops/sources/fetch.py`, `pipelines/flightops/__main__.py`, `pipelines/tests/test_fetch.py`

**Interfaces:**
- Consumes: `db.REPO`, `db.connect`, `db.migrate`, `raw.create_table_sql`, `raw.load_file`.
- Produces: `registry.RAW_FILES: list[RawFile]`, `registry.DOWNLOADS: list[Download]`, `registry.DATA: Path`, `RawFile.path() -> Path`, `fetch.download(url: str, dest: Path) -> bool`, `fetch.extract_csv(zip_path: Path) -> None`, CLI `python -m flightops {migrate,ddl,fetch,load}`.

- [ ] **Step 1: Write the failing tests**

`pipelines/tests/test_fetch.py`:

```python
import zipfile

from flightops.sources import fetch


def test_download_writes_file_and_skips_when_present(tmp_path):
    src = tmp_path / "src.csv"
    src.write_text("a\n")
    dest = tmp_path / "out" / "dest.csv"
    assert fetch.download(src.as_uri(), dest) is True
    assert dest.read_text() == "a\n"
    src.write_text("changed\n")
    assert fetch.download(src.as_uri(), dest) is False
    assert dest.read_text() == "a\n"
    assert not dest.with_name("dest.csv.part").exists()


def test_extract_csv_takes_only_csv_members(tmp_path):
    archive = tmp_path / "x.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("data.csv", "a\n")
        z.writestr("readme.html", "<p>")
    fetch.extract_csv(archive)
    assert (tmp_path / "data.csv").read_text() == "a\n"
    assert not (tmp_path / "readme.html").exists()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --env-file ../.env pytest tests/test_fetch.py -v`
Expected: collection error, `flightops.sources.fetch` does not exist.

- [ ] **Step 3: Implement**

`pipelines/flightops/sources/fetch.py`:

```python
import shutil
import urllib.request
import zipfile
from pathlib import Path


def download(url: str, dest: Path) -> bool:
    if dest.exists():
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")  # never leave a partial file under the real name
    with urllib.request.urlopen(url) as response, part.open("wb") as out:
        shutil.copyfileobj(response, out)
    part.rename(dest)
    return True


def extract_csv(zip_path: Path) -> None:
    with zipfile.ZipFile(zip_path) as z:
        for name in z.namelist():
            if name.lower().endswith(".csv"):
                z.extract(name, zip_path.parent)
```

`pipelines/flightops/sources/registry.py`:

```python
from dataclasses import dataclass
from pathlib import Path

from flightops.db import REPO

DATA = REPO / "data" / "raw"


@dataclass(frozen=True)
class RawFile:
    source: str
    table: str
    pattern: str  # glob, because the BTS zip names its CSV for us

    def path(self) -> Path:
        matches = list((DATA / self.source).glob(self.pattern))
        if len(matches) != 1:
            raise FileNotFoundError(
                f"expected one file for {DATA / self.source / self.pattern}, found {len(matches)}"
            )
        return matches[0]


@dataclass(frozen=True)
class Download:
    url: str
    dest: Path
    unzip: bool = False


RAW_FILES = [
    RawFile("bts", "bts_ontime", "*2024_7.csv"),
    RawFile("faa", "faa_master", "MASTER.txt"),
    RawFile("faa", "faa_acftref", "ACFTREF.txt"),
    RawFile("faa", "faa_dereg", "DEREG.txt"),
    RawFile("ourairports", "ourairports_airports", "airports.csv"),
    RawFile("iem", "iem_metar", "metar_katl_2024_07.csv"),
    RawFile("iem", "iem_taf", "taf_katl_2024_07.csv"),
]

# FAA is absent on purpose: it answers scripted requests with 403, so it is a hand download.
# Weather spans June 30 to August 2 UTC so joins at both ends of July have data.
_IEM = "https://mesonet.agron.iastate.edu/cgi-bin/request"
DOWNLOADS = [
    Download(
        "https://transtats.bts.gov/PREZIP/"
        "On_Time_Reporting_Carrier_On_Time_Performance_1987_present_2024_7.zip",
        DATA / "bts" / "ontime_2024_7.zip",
        unzip=True,
    ),
    Download(
        "https://davidmegginson.github.io/ourairports-data/airports.csv",
        DATA / "ourairports" / "airports.csv",
    ),
    Download(
        f"{_IEM}/asos.py?station=ATL&data=metar&year1=2024&month1=6&day1=30"
        "&year2=2024&month2=8&day2=2&tz=Etc/UTC&format=onlycomma&latlon=no"
        "&missing=empty&trace=empty&report_type=1&report_type=3&report_type=4",
        DATA / "iem" / "metar_katl_2024_07.csv",
    ),
    Download(
        f"{_IEM}/taf.py?station=KATL&sts=2024-06-30T00:00Z&ets=2024-08-02T00:00Z&fmt=csv",
        DATA / "iem" / "taf_katl_2024_07.csv",
    ),
]
```

`pipelines/flightops/__main__.py`:

```python
import argparse

from flightops import db
from flightops.sources import fetch, raw, registry


def main() -> None:
    parser = argparse.ArgumentParser(prog="flightops")
    parser.add_argument("command", choices=["migrate", "ddl", "fetch", "load"])
    command = parser.parse_args().command

    if command == "ddl":  # prints raw table DDL from real headers, for writing a migration
        for f in registry.RAW_FILES:
            print(raw.create_table_sql(f.table, f.path()))
    elif command == "fetch":
        for d in registry.DOWNLOADS:
            print(("fetched " if fetch.download(d.url, d.dest) else "present ") + d.dest.name)
            if d.unzip:
                fetch.extract_csv(d.dest)
    else:
        with db.connect() as conn:
            if command == "migrate":
                print("applied:", db.migrate(conn))
            else:
                for f in registry.RAW_FILES:
                    result = raw.load_file(conn, f.source, f.table, f.path())
                    print(f"{f.table}: {result.rows} rows{' (already loaded)' if result.skipped else ''}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --env-file ../.env pytest tests/test_fetch.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add pipelines
git commit -m "feat: add source registry, downloads and pipeline CLI"
```

---

### Task 4: Load the real files and reconcile

**Files:**
- Create: `db/migrations/002_raw_tables.sql`, `docs/data-sources.md`
- Modify: `docs/phase-1-plan.md`, `CLAUDE.md`, and `DECISIONS.md` if the real files force a tradeoff

**Interfaces:**
- Consumes: the CLI from Task 3.
- Produces: populated `raw.*` tables that steps 3-7 build on, with these table names: `bts_ontime`, `faa_master`, `faa_acftref`, `faa_dereg`, `ourairports_airports`, `iem_metar`, `iem_taf`.

- [ ] **Step 1: Download the files**

The user downloads `https://registry.faa.gov/database/ReleasableAircraft.zip` in a browser and unzips `MASTER.txt`, `ACFTREF.txt` and `DEREG.txt` into `data/raw/faa/`. Stop and ask for this if the files are absent. Then run:

Run: `uv run --env-file ../.env python -m flightops fetch`
Expected: four `fetched` lines. The BTS download takes several minutes, and `data/raw/bts/` gains one CSV ending in `2024_7.csv`.

- [ ] **Step 2: Generate the raw table migration from real headers**

Run: `uv run --env-file ../.env python -m flightops ddl > ../db/migrations/002_raw_tables.sql`
Expected: seven `CREATE TABLE raw.*` statements. Read the file and confirm that `raw.bts_ontime` has the 110 columns noted in the phase plan, or 109 if that count included the trailing blank column. If migrate fails on duplicate column names, stop and report them, because the loader compares headers to table columns and would need a rename rule.

- [ ] **Step 3: Migrate and load**

Run:

```bash
uv run --env-file ../.env python -m flightops migrate
uv run --env-file ../.env python -m flightops load
```

Expected: `bts_ontime: 634613 rows`, and a row count for each of the other six tables. If FAA files fail on encoding or a malformed row, use superpowers:systematic-debugging. Do not add `errors="ignore"` or anything else that drops data silently.

- [ ] **Step 4: Check that stray quotes did not swallow FAA rows**

The CSV reader joins lines across an unmatched `"`, which would lose rows with no error.

Run: `wc -l ../data/raw/faa/MASTER.txt ../data/raw/faa/DEREG.txt ../data/raw/faa/ACFTREF.txt`
Expected: each count minus the header equals `row_count` for that table in `dq.ingestion_run`. A difference is a bug to resolve before moving on.

- [ ] **Step 5: Reconcile against the measured counts in `docs/phase-1-plan.md`**

Run in `psql -h localhost flightops`:

```sql
SELECT count(*) AS national FROM raw.bts_ontime;
WITH atl AS (SELECT * FROM raw.bts_ontime WHERE origin = 'ATL' OR dest = 'ATL')
SELECT count(*) AS touching_atl,
       count(*) FILTER (WHERE iata_code_operating_airline = 'DL') AS operated_dl,
       count(DISTINCT nullif(tail_number, '')) AS tails,
       count(*) FILTER (WHERE tail_number = '') AS missing_tail,
       count(*) FILTER (WHERE tail_number = '' AND cancelled::numeric <> 1) AS missing_tail_operated,
       count(*) FILTER (WHERE '2400' IN (crsdeptime, crsarrtime, deptime, arrtime, wheelsoff, wheelson)) AS with_2400,
       count(*) FILTER (WHERE diverted::numeric = 1) AS diverted,
       count(*) FILTER (WHERE cancelled::numeric = 1 AND flightdate::date BETWEEN '2024-07-19' AND '2024-07-23') AS cancelled_outage,
       count(*) FILTER (WHERE cancelled::numeric = 1 AND flightdate::date BETWEEN '2024-07-19' AND '2024-07-23' AND iata_code_operating_airline = 'DL') AS cancelled_outage_dl
FROM atl;
```

Expected: national 634,613, touching_atl 60,144, operated_dl 41,363, tails 3,078, missing_tail 152, missing_tail_operated 0, with_2400 57, diverted 278, cancelled_outage 3,208, cancelled_outage_dl 2,864. If a column name differs from the real header, use the name in `002_raw_tables.sql`. `with_2400` is the least certain, because the original count's column list isn't recorded. Investigate any other mismatch before moving on, and if the columns turn out to explain `with_2400`, record which ones.

- [ ] **Step 6: Prove reloads change nothing**

Run:

```bash
uv run --env-file ../.env python -m flightops load
```

Expected: every line ends `(already loaded)`, and `SELECT count(*) FROM dq.ingestion_run` still returns 7.

- [ ] **Step 7: Write up the sources and close the open items**

Write `docs/data-sources.md` with one section per source, stating only what was observed in the loaded files: URL, how it is obtained (scripted or by hand), snapshot date for FAA, delimiter, encoding, row count, SHA-256, and quirks. Remove the resolved items from "Open before step 1" in `docs/phase-1-plan.md`. Add a `DECISIONS.md` entry if the real files forced a tradeoff. Update Status in `CLAUDE.md` so the next action is planning steps 3-5, and list the commands that now work.

- [ ] **Step 8: Run all tests and commit**

Run: `uv run --env-file ../.env pytest -v`
Expected: all passed.

```bash
git add db docs DECISIONS.md CLAUDE.md
git commit -m "feat: load July 2024 raw sources and reconcile counts"
```
