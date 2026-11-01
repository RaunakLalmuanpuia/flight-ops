# Phase 1, Steps 3-5: Staging, Ontology and Rotations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans and superpowers:test-driven-development. Use superpowers:verification-before-completion before calling a step done. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One command takes `raw` to `ontology`, stops at failed blocking checks, and rebuilds national rotations with every break labelled.

**Architecture:** Set-based SQL does the flight, aircraft, ontology and rotation work, in `.sql` files run by a small Python runner. Python handles only what SQL can't do well: timezone lookup from coordinates, and METAR parsing. `staging` and `ontology` are fully rebuilt on each run, in key order, so reruns are identical. Blocking checks run between staging and ontology, so a failure leaves the previous `ontology` in place.

**Tech Stack:** Python 3.12 or newer, `psycopg` 3, `timezonefinder`, `pytest`, local Postgres 18.

## Global Constraints

- Pipelines are the only writers to `raw`, `staging`, `ontology` and `dq`. Schema changes go through `db/migrations/`.
- `ontology` stores times in UTC. Never build an ICAO code by prefixing `K`.
- Blank delay causes mean not reported, not zero.
- Unresolved matches are recorded with a reason. Never guess, and never drop them silently. Each resolved link stores its method and confidence.
- Cancelled flights never join a rotation. Diverted flights use their actual landing station.
- No PostGIS, orchestration, streaming or Docker.
- Run `uv` commands from `pipelines/`, and `git` commands from the repo root.

## Findings from prototyping on real data, 2026-11-01

These come from temporary-table prototypes against the loaded July 2024 files. Task 6 checks the build against them.

| Finding | Evidence | Design consequence |
|---|---|---|
| BTS `hhmm` is more reliable than block time | Scheduled block disagrees with `crsarrtime` on 316 of 634,613 flights. Using `hhmm` with block time only choosing the date gives 0 actual arrivals at or before departure. The block-only prototype had 1 | `hhmm` is authoritative. Block time only picks the date. Mismatches are flagged |
| Scheduled data has its own errors | 61 flights have a scheduled arrival at or before scheduled departure | Reported, not blocking. The blocking check covers actual times, as the phase plan says |
| Timezones work | Every BTS airport, including diversion airports, gets a timezone. Actual departure `hhmm` matched `depdelay` on all 616,756 flights compared | The blocking check should pass |
| Not all BTS tails include `N` | 123 Allegiant tails on 12,478 flights look like `320NV` | **Corrects `CLAUDE.md`.** Add the `N` when the tail starts with a digit, and keep the delivered value |
| A strict FAA date window is too strict | Reissued certificates move `cert_issue_date` past the flight, stranding 306 tails. For example, `N935AT` on Delta has a certificate dated 2024-07-31 and no `DEREG` row | See the FAA rules below |
| FAA dates can be blank | 107,087 of 383,685 `DEREG` rows have no `cert_issue_date`, and 12,541 have no `cancel_date` | Blank means an open end, which gets lower confidence |
| Rotations mostly connect | Of 610,617 consecutive pairs, 602,697 connect (98.70%) | Breaks are labelled by the rules in Task 5 |

### FAA rules

A candidate airframe is a distinct `(mfr_mdl_code, serial_number)` among a tail's `MASTER` and `DEREG` records. For each tail and flight date, the first matching rule wins:

| Rule | Condition | Method | Confidence | Prototype flights |
|---|---|---|---|---|
| 1 | Exactly one airframe has a dated window covering the flight | `window_exact` | high | 580,026 |
| 2 | Exactly one airframe covers it once blank dates count as open | `window_open_start` | medium | 1,002 |
| 3 | The tail has only ever had one airframe, whatever the dates | `single_airframe_outside_window` | medium | 34,653 |
| - | No records | unresolved: `no_faa_record` | - | 399 |
| - | Several airframes cover the date | unresolved: `ambiguous_window` | - | up to 7,910 |
| - | No window covers it, and there are several airframes | unresolved: `no_window_multiple_airframes` | - | 6,965 |

Prototype counts come from a simpler ordering, and rule 1 here should move some `ambiguous_window` flights into `window_exact`. At most about 2.4% of flights stay unresolved, which is reported, not blocking.

## Not built here

- `Carrier.icao_code` and `marketing_brand`: BTS has neither, and adding them needs a new source. The Carrier table holds IATA and DOT IDs.
- Weather join (step 6) and the written report (step 7).

## File Structure

| Path | Responsibility |
|---|---|
| `db/migrations/004_staging.sql` | Staging tables, time functions, current-delivery views, airport alias |
| `db/migrations/005_weather_staging.sql`, `006_aircraft_staging.sql` | Remaining staging tables |
| `db/migrations/007_ontology.sql`, `008_rotations.sql` | Ontology tables, `dq.check_result`, `dq.unresolved_link`, rotation legs |
| `pipelines/flightops/transform/airports.py` | Airport timezone lookup |
| `pipelines/flightops/transform/flights.sql` | BTS to `staging.flight` |
| `pipelines/flightops/transform/weather.py` | METAR parsing, and METAR and TAF staging |
| `pipelines/flightops/resolve/aircraft.sql` | FAA records and tail links |
| `pipelines/flightops/resolve/ontology.sql` | Promotion to `ontology` |
| `pipelines/flightops/rotations/rotations.sql` | Rotation legs and break labels |
| `pipelines/flightops/dq/checks.py` | Blocking and reported checks |
| `pipelines/flightops/pipeline.py` | Run order |
| `pipelines/tests/fixtures/*.csv` | Awkward cases |

---

### Task 1: Airports and UTC flight times

**Files:**
- Create: `db/migrations/004_staging.sql`, `pipelines/flightops/transform/__init__.py`, `pipelines/flightops/transform/airports.py`, `pipelines/flightops/transform/flights.sql`, `pipelines/flightops/pipeline.py`, `pipelines/tests/fixtures/airports.csv`, `pipelines/tests/fixtures/bts_awkward.csv`, `pipelines/tests/test_flights.py`
- Modify: `pipelines/pyproject.toml`, `pipelines/tests/conftest.py`, `CLAUDE.md`, `DECISIONS.md`

**Interfaces:**
- Consumes: `conn` fixture, `raw.*`.
- Produces: pytest fixture `load_fixture(table: str, filename: str)`; `airports.build_airports(conn) -> None`; `pipeline.run_sql(conn, relative_path: str) -> None`; `staging.airport(ident, bts_code, iata_current, icao_code, name, latitude, longitude, country, tz)`; `staging.flight` as defined below.

- [ ] **Step 1: Add the dependency**

Run: `uv add timezonefinder`
Expected: `pyproject.toml` and `uv.lock` updated.

- [ ] **Step 2: Create the fixtures**

`pipelines/tests/fixtures/airports.csv`:

```csv
id,ident,type,name,latitude_deg,longitude_deg,iso_country,icao_code,iata_code,gps_code,local_code
1,KATL,large_airport,Hartsfield-Jackson,33.6367,-84.4281,US,KATL,ATL,KATL,ATL
2,KORD,large_airport,O'Hare,41.9786,-87.9048,US,KORD,ORD,KORD,ORD
3,KLAX,large_airport,Los Angeles,33.9425,-118.408,US,KLAX,LAX,KLAX,LAX
4,KLGA,large_airport,LaGuardia,40.7772,-73.8726,US,KLGA,LGA,KLGA,LGA
5,KIAD,large_airport,Dulles,38.9445,-77.4558,US,KIAD,IAD,KIAD,IAD
6,KCLE,large_airport,Cleveland,41.4117,-81.8498,US,KCLE,CLE,KCLE,CLE
7,KPBI,large_airport,West Palm Beach,26.6832,-80.0956,US,KDJT,DJT,KDJT,DJT
8,TJSJ,large_airport,San Juan,18.4394,-66.0018,PR,TJSJ,SJU,TJSJ,SJU
```

`pipelines/tests/fixtures/bts_awkward.csv` covers, in order by flight number: (1) a timezone crossing, (2) `2400`, (3) a red-eye crossing the date, (4) a cancelled flight with no tail, (5) a flight cancelled after departing, (6) a diversion that reached its destination, (7) a diversion that did not, (8) a tail without `N` and reported delay causes, (9) the `PBI` alias, (10) a block time that disagrees with `hhmm`.

```csv
flightdate,reporting_airline,dot_id_reporting_airline,iata_code_reporting_airline,tail_number,flight_number_reporting_airline,originairportid,destairportid,origin,dest,crsdeptime,deptime,depdelay,crsarrtime,arrtime,arrdelay,crselapsedtime,actualelapsedtime,cancelled,cancellationcode,diverted,divreacheddest,divactualelapsedtime,div1airport,div1wheelson,div2airport,div2wheelson,carrierdelay,weatherdelay,nasdelay,securitydelay,lateaircraftdelay
2024-07-19,DL,19790,DL,N100DL,1,10397,13930,ATL,ORD,0800,0810,10.00,0855,0905,10.00,115.00,115.00,0.00,,0.00,,,,,,,,,,,
2024-07-19,DL,19790,DL,N101DL,2,10397,13930,ATL,ORD,2400,2400,0.00,0055,0055,0.00,115.00,115.00,0.00,,0.00,,,,,,,,,,,
2024-07-19,DL,19790,DL,N102DL,3,12892,10397,LAX,ATL,2300,2300,0.00,0630,0630,0.00,270.00,270.00,0.00,,0.00,,,,,,,,,,,
2024-07-19,DL,19790,DL,,4,10397,13930,ATL,ORD,1600,,,1655,,,115.00,,1.00,A,0.00,,,,,,,,,,,
2024-07-19,DL,19790,DL,N100DL,5,10397,13930,ATL,ORD,1700,1705,5.00,1755,,,115.00,,1.00,B,0.00,,,,,,,,,,,
2024-07-19,DL,19790,DL,N103DL,6,10397,12953,ATL,LGA,0900,0900,0.00,1115,1600,,135.00,,0.00,,1.00,1.00,420.00,IAD,1100,,,,,,,
2024-07-19,DL,19790,DL,N104DL,7,10397,12953,ATL,LGA,1300,1300,0.00,1515,,,135.00,,0.00,,1.00,0.00,,IAD,1500,CLE,1700,,,,,
2024-07-19,G4,20368,G4,320NV,8,10397,13930,ATL,ORD,1000,1010,10.00,1055,1120,25.00,115.00,130.00,0.00,,0.00,,,,,,,10.00,0.00,0.00,0.00,15.00
2024-07-19,DL,19790,DL,N105DL,9,13495,10397,PBI,ATL,0800,0800,0.00,1000,1000,0.00,120.00,120.00,0.00,,0.00,,,,,,,,,,,
2024-07-19,DL,19790,DL,N106DL,10,10397,13930,ATL,ORD,1400,1400,0.00,1500,1455,-5.00,115.00,115.00,0.00,,0.00,,,,,,,,,,,
```

- [ ] **Step 3: Add the fixture loader and write the failing tests**

Append to `pipelines/tests/conftest.py`:

```python
import csv
from pathlib import Path

from psycopg import sql

FIXTURES = Path(__file__).parent / "fixtures"


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
```

`pipelines/tests/test_flights.py`:

```python
from datetime import datetime, timezone

import pytest

from flightops import pipeline
from flightops.transform import airports


def utc(month, day, hour, minute=0):
    return datetime(2024, month, day, hour, minute, tzinfo=timezone.utc)


@pytest.fixture
def flights(conn, load_fixture):
    load_fixture("ourairports_airports", "airports.csv")
    load_fixture("bts_ontime", "bts_awkward.csv")
    airports.build_airports(conn)
    pipeline.run_sql(conn, "transform/flights.sql")
    return conn


def get(conn, number, *columns):
    row = conn.execute(
        f"select {', '.join(columns)} from staging.flight where flight_number = %s", (str(number),)
    ).fetchone()
    return row[0] if len(columns) == 1 else row


def test_every_row_arrives(flights):
    assert flights.execute("select count(*) from staging.flight").fetchone()[0] == 10


def test_timezones_come_from_coordinates(flights):
    zones = dict(flights.execute("select bts_code, tz from staging.airport").fetchall())
    assert zones["ATL"] == "America/New_York"
    assert zones["ORD"] == "America/Chicago"


def test_alias_keeps_the_2024_code_and_the_current_one(flights):
    row = flights.execute(
        "select ident, iata_current, icao_code from staging.airport where bts_code = 'PBI'"
    ).fetchone()
    assert row == ("KPBI", "DJT", "KDJT")
    assert get(flights, 9, "sched_dep_utc") == utc(7, 19, 12)


def test_times_convert_across_timezones(flights):
    assert get(flights, 1, "sched_dep_utc", "sched_arr_utc", "actual_dep_utc", "actual_arr_utc") == (
        utc(7, 19, 12), utc(7, 19, 13, 55), utc(7, 19, 12, 10), utc(7, 19, 14, 5),
    )


def test_2400_is_midnight_at_the_end_of_flight_date(flights):
    assert get(flights, 2, "sched_dep_utc", "actual_arr_utc") == (utc(7, 20, 4), utc(7, 20, 5, 55))


def test_arrival_date_comes_from_the_block_not_flight_date(flights):
    assert get(flights, 3, "sched_dep_utc", "sched_arr_utc") == (utc(7, 20, 6), utc(7, 20, 10, 30))


def test_cancelled_flight_with_no_tail(flights):
    assert get(flights, 4, "tail_number", "cancelled", "actual_dep_utc", "landed_station") == (
        None, True, None, None,
    )


def test_cancelled_after_departure_keeps_departure_but_never_lands(flights):
    assert get(flights, 5, "actual_dep_utc", "actual_arr_utc", "landed_station") == (
        utc(7, 19, 21, 5), None, None,
    )


def test_diversion_that_reached_destination_lands_there(flights):
    assert get(flights, 6, "diverted", "reached_dest", "landed_station", "actual_arr_utc") == (
        True, True, "LGA", utc(7, 19, 20),
    )


def test_diversion_that_stopped_short_lands_at_last_diversion_airport(flights):
    assert get(flights, 7, "diverted", "reached_dest", "landed_station", "actual_arr_utc") == (
        True, False, "CLE", utc(7, 19, 21),
    )


def test_tail_without_n_is_normalized_and_kept_as_delivered(flights):
    assert get(flights, 8, "tail_number", "tail_as_delivered") == ("N320NV", "320NV")


def test_blank_delay_causes_stay_null_and_reported_ones_are_kept(flights):
    assert get(flights, 1, "carrier_delay", "late_aircraft_delay") == (None, None)
    assert get(flights, 8, "carrier_delay", "weather_delay", "late_aircraft_delay") == (10, 0, 15)


def test_hhmm_wins_when_block_time_disagrees_and_it_is_flagged(flights):
    assert get(flights, 10, "sched_arr_utc", "block_mismatch") == (utc(7, 19, 20), True)
    assert get(flights, 1, "block_mismatch") is False
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `uv run --env-file ../.env pytest tests/test_flights.py -q`
Expected: collection error, `flightops.pipeline` does not exist.

- [ ] **Step 5: Implement**

`db/migrations/004_staging.sql`:

```sql
-- The newest delivery of each source file. A changed file replaces its predecessor, a new month adds to it.
CREATE VIEW staging.current_delivery AS
SELECT DISTINCT ON (table_name, source_file) table_name, source_sha256
FROM dq.ingestion_run
ORDER BY table_name, source_file, id DESC;

CREATE VIEW staging.v_bts AS SELECT r.* FROM raw.bts_ontime r JOIN staging.current_delivery d ON d.table_name = 'bts_ontime' AND d.source_sha256 = r.source_sha256;
CREATE VIEW staging.v_airports AS SELECT r.* FROM raw.ourairports_airports r JOIN staging.current_delivery d ON d.table_name = 'ourairports_airports' AND d.source_sha256 = r.source_sha256;
CREATE VIEW staging.v_faa_master AS SELECT r.* FROM raw.faa_master r JOIN staging.current_delivery d ON d.table_name = 'faa_master' AND d.source_sha256 = r.source_sha256;
CREATE VIEW staging.v_faa_dereg AS SELECT r.* FROM raw.faa_dereg r JOIN staging.current_delivery d ON d.table_name = 'faa_dereg' AND d.source_sha256 = r.source_sha256;
CREATE VIEW staging.v_faa_acftref AS SELECT r.* FROM raw.faa_acftref r JOIN staging.current_delivery d ON d.table_name = 'faa_acftref' AND d.source_sha256 = r.source_sha256;
CREATE VIEW staging.v_metar AS SELECT r.* FROM raw.iem_metar r JOIN staging.current_delivery d ON d.table_name = 'iem_metar' AND d.source_sha256 = r.source_sha256;
CREATE VIEW staging.v_taf AS SELECT r.* FROM raw.iem_taf r JOIN staging.current_delivery d ON d.table_name = 'iem_taf' AND d.source_sha256 = r.source_sha256;

-- BTS codes that OurAirports no longer uses, because OurAirports holds only current codes.
CREATE TABLE staging.airport_code_alias (
    bts_code text PRIMARY KEY,
    ident    text NOT NULL,
    reason   text NOT NULL
);
INSERT INTO staging.airport_code_alias VALUES
    ('PBI', 'KPBI', 'West Palm Beach is PBI in July 2024 BTS, and DJT in current OurAirports');

CREATE TABLE staging.airport (
    ident        text PRIMARY KEY,
    bts_code     text NOT NULL UNIQUE,
    iata_current text,
    icao_code    text,
    name         text NOT NULL,
    latitude     double precision NOT NULL,
    longitude    double precision NOT NULL,
    country      text NOT NULL,
    tz           text
);

-- A local time on a known date. 2400 is midnight at the end of that date.
CREATE FUNCTION staging.local_at(d date, hhmm text, tz text) RETURNS timestamptz
LANGUAGE sql STABLE STRICT AS $$
    SELECT (d + make_interval(hours => hhmm::int / 100, mins => hhmm::int % 100)) AT TIME ZONE tz
$$;

-- A local time whose date is unknown: the occurrence closest to the anchor.
CREATE FUNCTION staging.local_near(hhmm text, tz text, anchor timestamptz) RETURNS timestamptz
LANGUAGE sql STABLE STRICT AS $$
    SELECT staging.local_at(((anchor AT TIME ZONE tz)::date + i)::date, hhmm, tz)
    FROM generate_series(-1, 1) i
    ORDER BY abs(extract(epoch FROM staging.local_at(((anchor AT TIME ZONE tz)::date + i)::date, hhmm, tz) - anchor))
    LIMIT 1
$$;

CREATE TABLE staging.flight (
    flight_date         date NOT NULL,
    carrier             text NOT NULL,
    carrier_iata        text,
    carrier_dot_id      text,
    flight_number       text NOT NULL,
    origin              text NOT NULL,
    dest                text NOT NULL,
    origin_bts_id       text,
    dest_bts_id         text,
    crs_dep_local       text NOT NULL,
    tail_number         text,
    tail_as_delivered   text,
    sched_dep_utc       timestamptz NOT NULL,
    sched_arr_utc       timestamptz,
    actual_dep_utc      timestamptz,
    actual_arr_utc      timestamptz,
    landed_station      text,
    cancelled           boolean NOT NULL,
    cancellation_code   text,
    diverted            boolean NOT NULL,
    reached_dest        boolean,
    dep_delay_min       integer,
    arr_delay_min       integer,
    carrier_delay       integer,
    weather_delay       integer,
    nas_delay           integer,
    security_delay      integer,
    late_aircraft_delay integer,
    block_mismatch      boolean NOT NULL,
    PRIMARY KEY (flight_date, carrier, flight_number, origin, crs_dep_local)
);
```

`pipelines/flightops/pipeline.py`:

```python
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent


def run_sql(conn, relative_path: str) -> None:
    with conn.transaction():
        conn.execute((PACKAGE / relative_path).read_text())
```

`pipelines/flightops/transform/airports.py`:

```python
from timezonefinder import TimezoneFinder

CODES_AND_AIRPORTS = """
WITH codes AS (
    SELECT origin AS code FROM staging.v_bts
    UNION SELECT dest FROM staging.v_bts
    UNION SELECT div1airport FROM staging.v_bts
    UNION SELECT div2airport FROM staging.v_bts
    UNION SELECT div3airport FROM staging.v_bts
    UNION SELECT div4airport FROM staging.v_bts
    UNION SELECT div5airport FROM staging.v_bts
)
SELECT o.ident, c.code, nullif(o.iata_code, ''), nullif(o.icao_code, ''), o.name,
       o.latitude_deg::float, o.longitude_deg::float, o.iso_country
FROM codes c
LEFT JOIN staging.airport_code_alias a ON a.bts_code = c.code
JOIN staging.v_airports o ON o.ident = a.ident OR (a.ident IS NULL AND o.iata_code = c.code)
WHERE nullif(c.code, '') IS NOT NULL
ORDER BY c.code
"""


def build_airports(conn) -> None:
    finder = TimezoneFinder()
    rows = conn.execute(CODES_AND_AIRPORTS).fetchall()
    with conn.transaction():
        conn.execute("TRUNCATE staging.airport")
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO staging.airport (ident, bts_code, iata_current, icao_code, name, latitude, longitude, country, tz) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                [(*r, finder.timezone_at(lat=r[5], lng=r[6])) for r in rows],
            )
```

`pipelines/flightops/transform/flights.sql`:

```sql
TRUNCATE staging.flight;

INSERT INTO staging.flight
SELECT
    b.flightdate::date,
    b.reporting_airline,
    nullif(b.iata_code_reporting_airline, ''),
    nullif(b.dot_id_reporting_airline, ''),
    b.flight_number_reporting_airline,
    b.origin,
    b.dest,
    nullif(b.originairportid, ''),
    nullif(b.destairportid, ''),
    b.crsdeptime,
    CASE WHEN b.tail_number ~ '^[0-9]' THEN 'N' || b.tail_number ELSE nullif(b.tail_number, '') END,
    nullif(b.tail_number, ''),
    s.sched_dep,
    staging.local_near(b.crsarrtime, d.tz, s.sched_dep + s.crs_block * interval '1 minute'),
    a.actual_dep,
    l.actual_arr,
    CASE WHEN f.is_cancelled THEN NULL WHEN f.stopped_short THEN f.last_div_airport ELSE b.dest END,
    f.is_cancelled,
    nullif(b.cancellationcode, ''),
    f.is_diverted,
    CASE WHEN f.is_diverted THEN NOT f.stopped_short END,
    s.dep_delay,
    nullif(b.arrdelay, '')::numeric::int,
    nullif(b.carrierdelay, '')::numeric::int,
    nullif(b.weatherdelay, '')::numeric::int,
    nullif(b.nasdelay, '')::numeric::int,
    nullif(b.securitydelay, '')::numeric::int,
    nullif(b.lateaircraftdelay, '')::numeric::int,
    abs(extract(epoch FROM staging.local_near(b.crsarrtime, d.tz, s.sched_dep + s.crs_block * interval '1 minute') - s.sched_dep) / 60 - s.crs_block) > 1
FROM staging.v_bts b
JOIN staging.airport o ON o.bts_code = b.origin
JOIN staging.airport d ON d.bts_code = b.dest
CROSS JOIN LATERAL (
    SELECT
        nullif(b.cancelled, '')::numeric = 1 AS is_cancelled,
        coalesce(nullif(b.diverted, '')::numeric = 1, false) AS is_diverted,
        coalesce(nullif(b.diverted, '')::numeric = 1, false) AND coalesce(nullif(b.divreacheddest, '')::numeric <> 1, true) AS stopped_short,
        coalesce(nullif(b.div5airport, ''), nullif(b.div4airport, ''), nullif(b.div3airport, ''), nullif(b.div2airport, ''), nullif(b.div1airport, '')) AS last_div_airport,
        coalesce(nullif(b.div5wheelson, ''), nullif(b.div4wheelson, ''), nullif(b.div3wheelson, ''), nullif(b.div2wheelson, ''), nullif(b.div1wheelson, '')) AS last_div_wheelson
) f
LEFT JOIN staging.airport x ON x.bts_code = f.last_div_airport
CROSS JOIN LATERAL (
    SELECT
        staging.local_at(b.flightdate::date, b.crsdeptime, o.tz) AS sched_dep,
        nullif(b.crselapsedtime, '')::numeric AS crs_block,
        nullif(b.depdelay, '')::numeric::int AS dep_delay
) s
CROSS JOIN LATERAL (
    SELECT staging.local_near(nullif(b.deptime, ''), o.tz, s.sched_dep + coalesce(s.dep_delay, 0) * interval '1 minute') AS actual_dep
) a
CROSS JOIN LATERAL (
    SELECT CASE
        WHEN f.stopped_short THEN staging.local_near(f.last_div_wheelson, x.tz, a.actual_dep + interval '12 hours')
        ELSE staging.local_near(
            nullif(b.arrtime, ''), d.tz,
            a.actual_dep + coalesce(nullif(b.actualelapsedtime, ''), nullif(b.divactualelapsedtime, ''), '720')::numeric * interval '1 minute'
        )
    END AS actual_arr
) l
ORDER BY 1, 2, 5, 6, 10;
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run --env-file ../.env pytest tests/test_flights.py -q`
Expected: all passed.

- [ ] **Step 7: Correct the docs and record the decisions**

In `CLAUDE.md`, change the Tail format bullet to: "**Tail format:** BTS tails usually include the `N`, but 123 Allegiant tails do not (`320NV`), and FAA `N-NUMBER` omits it. Normalize all of them to the full form with the `N`, and keep the delivered value." Also add under BTS traps: "`hhmm` is authoritative. Block time only picks the date, because scheduled block disagrees with `crsarrtime` on 316 flights in July 2024." Under Airports add: "OurAirports holds current codes only, so a BTS code that has since changed needs a row in `staging.airport_code_alias`."

Append to `DECISIONS.md`:

```markdown
## 2026-11-01: Treat BTS hhmm as authoritative, and use block time only for the date
- **Chose:** each UTC time comes from its delivered local `hhmm`, on the date closest to what block time or delay implies. Disagreements set `block_mismatch`.
- **Gave up:** a single simple formula, so a flight's elapsed time can differ from the difference between its times, which it does on 7 flights.
- **Why:** deriving arrivals purely from block time contradicted BTS's own scheduled arrival on 316 flights and produced an arrival before departure.
- **Revisit if:** a mismatch pattern points to a wrong timezone instead of a schedule error.

## 2026-11-01: Handle changed airport codes with an explicit alias table
- **Chose:** `staging.airport_code_alias`, with one row so far: `PBI` to `KPBI`. Airports keep both the BTS code and the current code.
- **Gave up:** a generic history of airport codes, so the next renamed airport fails the timezone check until someone adds a row.
- **Why:** that failure is loud and the fix is one recorded line. OurAirports has no code history to build from.
- **Revisit if:** adding months or hubs needs more than a handful of aliases.
```

- [ ] **Step 8: Commit**

```bash
git add db pipelines CLAUDE.md DECISIONS.md
git commit -m "feat: add airports and UTC flight staging"
```

---

### Task 2: METAR parsing and weather staging

**Files:**
- Create: `db/migrations/005_weather_staging.sql`, `pipelines/flightops/transform/weather.py`, `pipelines/tests/fixtures/metar.csv`, `pipelines/tests/fixtures/taf.csv`, `pipelines/tests/test_weather.py`

**Interfaces:**
- Consumes: `load_fixture`, `staging.v_metar`, `staging.v_taf`.
- Produces: `weather.parse_metar(text: str) -> dict`, `weather.build_weather(conn) -> None`, `staging.metar`, `staging.taf`.

- [ ] **Step 1: Write the fixtures and failing tests**

`pipelines/tests/fixtures/metar.csv`:

```csv
station,valid,metar
ATL,2024-07-04 23:00,KATL 042300Z AUTO 19007KT 10SM CLR 33/22 A2994 RMK T03280222 MADISHF
ATL,2024-07-04 23:06,KATL 042306Z 19007KT 10SM TS BKN050CB BKN080 BKN250 33/22 A2994 RMK AO2 TSB06 $
ATL,2024-07-04 23:45,KATL 042345Z 35017G25KT 1 1/2SM +TSRA BR OVC040CB M02/M05 A2998 RMK AO2 WSHFT 2328
```

`pipelines/tests/fixtures/taf.csv`:

```csv
station,valid,fx_valid,raw,is_tempo,fx_valid_end,ftype,product_id
KATL,2024-07-19 01:43,2024-07-19 01:43,22006KT P6SM VCSH SCT150,False,,Observation,P1
KATL,2024-07-19 01:43,2024-07-19 03:00,FM190300 21004KT P6SM FEW120,False,2024-07-19 06:00,Forecast,P1
```

`pipelines/tests/test_weather.py`:

```python
from datetime import datetime, timezone
from decimal import Decimal

from flightops.transform import weather


def test_parse_wind_gust_and_temperature_below_zero():
    p = weather.parse_metar("KATL 042345Z 35017G25KT 1 1/2SM +TSRA BR OVC040CB M02/M05 A2998 RMK AO2")
    assert (p["wind_dir_deg"], p["wind_kt"], p["gust_kt"]) == (350, 17, 25)
    assert p["visibility_sm"] == Decimal("1.5")
    assert p["weather"] == ["+TSRA", "BR"]
    assert p["ceiling_ft"] == 4000
    assert (p["temp_c"], p["dewpoint_c"]) == (-2, -5)
    assert p["altimeter_inhg"] == Decimal("29.98")


def test_parse_variable_wind_and_greater_than_visibility():
    p = weather.parse_metar("KATL 010000Z VRB03KT P6SM FEW040 27/19 A3001")
    assert (p["wind_dir_deg"], p["wind_kt"], p["gust_kt"]) == (None, 3, None)
    assert p["visibility_sm"] == Decimal("6")
    assert p["ceiling_ft"] is None


def test_lowest_broken_or_overcast_layer_is_the_ceiling_and_few_is_not():
    assert weather.parse_metar("KATL 010000Z 00000KT 10SM FEW010 BKN050 OVC090 27/19 A3001")["ceiling_ft"] == 5000


def test_remarks_are_not_parsed_as_weather():
    p = weather.parse_metar("KATL 010000Z 00000KT 10SM CLR 27/19 A3001 RMK AO2 TS VC SW RAB39")
    assert p["weather"] == []


def test_build_filters_madis_records_and_stores_utc(conn, load_fixture):
    load_fixture("iem_metar", "metar.csv")
    load_fixture("iem_taf", "taf.csv")
    weather.build_weather(conn)
    rows = conn.execute("select station_icao, observed_at from staging.metar order by 2").fetchall()
    assert rows == [
        ("KATL", datetime(2024, 7, 4, 23, 6, tzinfo=timezone.utc)),
        ("KATL", datetime(2024, 7, 4, 23, 45, tzinfo=timezone.utc)),
    ]
    assert conn.execute("select count(*) from staging.taf where product_id = 'P1'").fetchone()[0] == 2


def test_build_twice_changes_nothing(conn, load_fixture):
    load_fixture("iem_metar", "metar.csv")
    load_fixture("iem_taf", "taf.csv")
    weather.build_weather(conn)
    weather.build_weather(conn)
    assert conn.execute("select count(*) from staging.metar").fetchone()[0] == 2
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --env-file ../.env pytest tests/test_weather.py -q`
Expected: collection error, `weather` does not exist.

- [ ] **Step 3: Implement**

`db/migrations/005_weather_staging.sql`:

```sql
CREATE TABLE staging.metar (
    station_icao   text NOT NULL,
    observed_at    timestamptz NOT NULL,
    raw_text       text NOT NULL,
    wind_dir_deg   integer,
    wind_kt        integer,
    gust_kt        integer,
    visibility_sm  numeric,
    ceiling_ft     integer,
    temp_c         integer,
    dewpoint_c     integer,
    altimeter_inhg numeric,
    weather        text[] NOT NULL,
    PRIMARY KEY (station_icao, observed_at)
);

CREATE TABLE staging.taf (
    station_icao text NOT NULL,
    product_id   text NOT NULL,
    issued_at    timestamptz NOT NULL,
    valid_from   timestamptz NOT NULL,
    valid_to     timestamptz,
    forecast_type text NOT NULL,
    is_tempo     boolean NOT NULL,
    raw_text     text NOT NULL
);
```

`pipelines/flightops/transform/weather.py`:

```python
import re
from decimal import Decimal
from fractions import Fraction

WIND = re.compile(r"\b(\d{3}|VRB)(\d{2,3})(?:G(\d{2,3}))?KT\b")
VISIBILITY = re.compile(r"\b(P)?(?:(\d+) )?(\d+/\d+|\d+)SM\b")
CEILING = re.compile(r"\b(?:BKN|OVC|VV)(\d{3})")
TEMPERATURE = re.compile(r"\b(M?\d{2})/(M?\d{2})?\b")
ALTIMETER = re.compile(r"\bA(\d{4})\b")
WEATHER = re.compile(
    r"^[-+]?(?:VC)?(?:MI|PR|BC|DR|BL|SH|TS|FZ)?"
    r"(?:DZ|RA|SN|SG|IC|PL|GR|GS|UP|BR|FG|FU|VA|DU|SA|HZ|PY|PO|SQ|FC|SS|DS)*$"
)
DESCRIPTOR_ONLY = {"TS", "VCTS", "VCSH"}


def _temperature(value: str | None) -> int | None:
    if value is None:
        return None
    return -int(value[1:]) if value.startswith("M") else int(value)


def parse_metar(text: str) -> dict:
    body = text.split(" RMK")[0]
    wind = WIND.search(body)
    visibility = VISIBILITY.search(body)
    ceilings = [int(c) * 100 for c in CEILING.findall(body)]
    temperature = TEMPERATURE.search(body)
    altimeter = ALTIMETER.search(body)

    visibility_sm = None
    if visibility:
        whole = int(visibility.group(2) or 0)
        part = Fraction(visibility.group(3))
        visibility_sm = Decimal(float(whole + part)).quantize(Decimal("0.01")).normalize()

    # weather groups sit between visibility and the first sky or temperature group
    weather = []
    if visibility:
        for token in body[visibility.end():].split():
            if token in DESCRIPTOR_ONLY or (WEATHER.match(token) and token.lstrip("+-") and len(token.lstrip("+-")) >= 2):
                weather.append(token)
            else:
                break

    return {
        "wind_dir_deg": None if not wind or wind.group(1) == "VRB" else int(wind.group(1)),
        "wind_kt": int(wind.group(2)) if wind else None,
        "gust_kt": int(wind.group(3)) if wind and wind.group(3) else None,
        "visibility_sm": visibility_sm,
        "ceiling_ft": min(ceilings) if ceilings else None,
        "temp_c": _temperature(temperature.group(1)) if temperature else None,
        "dewpoint_c": _temperature(temperature.group(2)) if temperature else None,
        "altimeter_inhg": Decimal(altimeter.group(1)) / 100 if altimeter else None,
        "weather": weather,
    }


def build_weather(conn) -> None:
    # MADISHF rows are 5-minute automated records, not standard METARs
    rows = conn.execute(
        "SELECT split_part(metar, ' ', 1), valid || '+00', metar FROM staging.v_metar "
        "WHERE metar NOT LIKE '%MADISHF%' ORDER BY 1, 2"
    ).fetchall()
    with conn.transaction():
        conn.execute("TRUNCATE staging.metar")
        conn.execute("TRUNCATE staging.taf")
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO staging.metar (station_icao, observed_at, raw_text, wind_dir_deg, wind_kt, gust_kt, "
                "visibility_sm, ceiling_ft, temp_c, dewpoint_c, altimeter_inhg, weather) "
                "VALUES (%(station)s, %(observed_at)s, %(raw)s, %(wind_dir_deg)s, %(wind_kt)s, %(gust_kt)s, "
                "%(visibility_sm)s, %(ceiling_ft)s, %(temp_c)s, %(dewpoint_c)s, %(altimeter_inhg)s, %(weather)s)",
                [{"station": s, "observed_at": v, "raw": m, **parse_metar(m)} for s, v, m in rows],
            )
        conn.execute(
            """
            INSERT INTO staging.taf
            SELECT station, product_id, (valid || '+00')::timestamptz, (fx_valid || '+00')::timestamptz,
                   (nullif(fx_valid_end, '') || '+00')::timestamptz, ftype, is_tempo = 'True', raw
            FROM staging.v_taf
            ORDER BY product_id, fx_valid
            """
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --env-file ../.env pytest tests/test_weather.py -q`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add db pipelines
git commit -m "feat: parse METARs and stage weather"
```

---

### Task 3: Resolve tails to airframes

**Files:**
- Create: `db/migrations/006_aircraft_staging.sql`, `pipelines/flightops/resolve/__init__.py`, `pipelines/flightops/resolve/aircraft.sql`, `pipelines/tests/fixtures/faa_master.csv`, `pipelines/tests/fixtures/faa_dereg.csv`, `pipelines/tests/fixtures/faa_acftref.csv`, `pipelines/tests/fixtures/bts_tails.csv`, `pipelines/tests/test_aircraft.py`
- Modify: `DECISIONS.md`

**Interfaces:**
- Consumes: `staging.flight`, `staging.v_faa_*`, `pipeline.run_sql`.
- Produces: `staging.faa_record(tail_number, frame, serial_number, mfr_mdl_code, hex, valid_from, valid_to, source)` and `staging.aircraft_link(tail_number, flight_date, frame, method, confidence, unresolved_reason)`. `frame` is `mfr_mdl_code|serial_number`.

- [ ] **Step 1: Write the fixtures and failing tests**

`pipelines/tests/fixtures/faa_master.csv` (with the padding the real file has):

```csv
n_number,serial_number,mfr_mdl_code,mode_s_code_hex,cert_issue_date
100A ,S1   ,M1 ,a00001    ,20200101
200A ,S2   ,M1 ,A00002    ,20240731
300A ,S3   ,M1 ,A00003    ,20250101
400A ,S4   ,M1 ,A00004    ,20200101
500A ,S5   ,M1 ,A00005    ,20250101
```

`pipelines/tests/fixtures/faa_dereg.csv`:

```csv
n_number,serial_number,mfr_mdl_code,mode_s_code_hex,cert_issue_date,cancel_date
300A ,S9   ,M1 ,A00003    ,20100101,20200101
400A ,S8   ,M2 ,A00004    ,        ,
500A ,S7   ,M1 ,A00005    ,        ,20240801
600A ,S6   ,M2 ,A00006    ,20100101,20240801
```

`pipelines/tests/fixtures/faa_acftref.csv`:

```csv
code,mfr,model
M1      ,BOEING       ,737-900ER
M2      ,AIRBUS       ,A321
```

`pipelines/tests/fixtures/bts_tails.csv` holds one July 19 flight per case, with tails `N100A` (rule 1), `N200A` (rule 3: reissued after the flight, one airframe), `N300A` (two airframes, neither covering), `N400A` (two airframes, both cover because `DEREG` dates are blank, but only one is dated, so rule 1 picks `MASTER`), `N500A` (rule 2: only the open-start `DEREG` covers), `N600A` (rule 1: `DEREG` window), `N700A` (no record):

```csv
flightdate,reporting_airline,tail_number,flight_number_reporting_airline,origin,dest,crsdeptime,crsarrtime,crselapsedtime,cancelled,diverted
2024-07-19,DL,N100A,1,ATL,ORD,0800,0855,115.00,0.00,0.00
2024-07-19,DL,N200A,2,ATL,ORD,0900,0955,115.00,0.00,0.00
2024-07-19,DL,N300A,3,ATL,ORD,1000,1055,115.00,0.00,0.00
2024-07-19,DL,N400A,4,ATL,ORD,1100,1155,115.00,0.00,0.00
2024-07-19,DL,N500A,5,ATL,ORD,1200,1255,115.00,0.00,0.00
2024-07-19,DL,N600A,6,ATL,ORD,1300,1355,115.00,0.00,0.00
2024-07-19,DL,N700A,7,ATL,ORD,1400,1455,115.00,0.00,0.00
2024-07-19,DL,,8,ATL,ORD,1500,1555,115.00,1.00,0.00
```

`pipelines/tests/test_aircraft.py`:

```python
import pytest

from flightops import pipeline
from flightops.transform import airports


@pytest.fixture
def links(conn, load_fixture):
    load_fixture("ourairports_airports", "airports.csv")
    load_fixture("bts_ontime", "bts_tails.csv")
    load_fixture("faa_master", "faa_master.csv")
    load_fixture("faa_dereg", "faa_dereg.csv")
    load_fixture("faa_acftref", "faa_acftref.csv")
    airports.build_airports(conn)
    pipeline.run_sql(conn, "transform/flights.sql")
    pipeline.run_sql(conn, "resolve/aircraft.sql")
    rows = conn.execute(
        "select tail_number, frame, method, confidence, unresolved_reason from staging.aircraft_link"
    ).fetchall()
    return {r[0]: r[1:] for r in rows}


def test_dated_window_is_high_confidence(links):
    assert links["N100A"] == ("M1|S1", "window_exact", "high", None)


def test_deregistered_window_resolves_to_the_older_airframe(links):
    assert links["N600A"] == ("M2|S6", "window_exact", "high", None)


def test_dated_window_beats_an_undated_record(links):
    assert links["N400A"] == ("M1|S4", "window_exact", "high", None)


def test_open_start_is_medium_confidence(links):
    assert links["N500A"] == ("M1|S7", "window_open_start", "medium", None)


def test_reissued_certificate_with_one_airframe_is_medium_confidence(links):
    assert links["N200A"] == ("M1|S2", "single_airframe_outside_window", "medium", None)


def test_two_airframes_and_no_covering_window_stays_unresolved(links):
    assert links["N300A"] == (None, None, None, "no_window_multiple_airframes")


def test_no_record_stays_unresolved(links):
    assert links["N700A"] == (None, None, None, "no_faa_record")


def test_blank_tail_makes_no_link(links):
    assert None not in links


def test_hex_is_uppercase_and_tail_has_n(conn, links):
    assert conn.execute("select hex from staging.faa_record where tail_number = 'N100A'").fetchone()[0] == "A00001"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --env-file ../.env pytest tests/test_aircraft.py -q`
Expected: failures, because `resolve/aircraft.sql` does not exist.

- [ ] **Step 3: Implement**

`db/migrations/006_aircraft_staging.sql`:

```sql
CREATE TABLE staging.faa_record (
    tail_number   text NOT NULL,
    frame         text NOT NULL,
    serial_number text NOT NULL,
    mfr_mdl_code  text NOT NULL,
    hex           text,
    valid_from    date,
    valid_to      date,
    source        text NOT NULL
);
CREATE INDEX ON staging.faa_record (tail_number);

CREATE TABLE staging.aircraft_link (
    tail_number       text NOT NULL,
    flight_date       date NOT NULL,
    frame             text,
    method            text,
    confidence        text,
    unresolved_reason text,
    PRIMARY KEY (tail_number, flight_date),
    CHECK ((frame IS NULL) = (unresolved_reason IS NOT NULL))
);
```

`pipelines/flightops/resolve/aircraft.sql`:

```sql
TRUNCATE staging.faa_record, staging.aircraft_link;

-- Only tails seen in BTS, because the registry holds 700,000 rows we would never read.
INSERT INTO staging.faa_record
SELECT 'N' || trim(n_number), trim(mfr_mdl_code) || '|' || trim(serial_number), trim(serial_number), trim(mfr_mdl_code),
       upper(nullif(trim(mode_s_code_hex), '')), to_date(nullif(trim(cert_issue_date), ''), 'YYYYMMDD'), NULL::date, 'master'
FROM staging.v_faa_master
WHERE 'N' || trim(n_number) IN (SELECT tail_number FROM staging.flight)
UNION ALL
SELECT 'N' || trim(n_number), trim(mfr_mdl_code) || '|' || trim(serial_number), trim(serial_number), trim(mfr_mdl_code),
       upper(nullif(trim(mode_s_code_hex), '')), to_date(nullif(trim(cert_issue_date), ''), 'YYYYMMDD'),
       to_date(nullif(trim(cancel_date), ''), 'YYYYMMDD'), 'dereg'
FROM staging.v_faa_dereg
WHERE 'N' || trim(n_number) IN (SELECT tail_number FROM staging.flight);

INSERT INTO staging.aircraft_link
SELECT t.tail_number, t.flight_date,
    CASE
        WHEN cardinality(dated) = 1 THEN dated[1]
        WHEN cardinality(dated) > 1 THEN NULL
        WHEN cardinality(open) = 1 THEN open[1]
        WHEN cardinality(open) > 1 THEN NULL
        WHEN cardinality(every) = 1 THEN every[1]
    END,
    CASE
        WHEN cardinality(dated) = 1 THEN 'window_exact'
        WHEN cardinality(dated) > 1 THEN NULL
        WHEN cardinality(open) = 1 THEN 'window_open_start'
        WHEN cardinality(open) > 1 THEN NULL
        WHEN cardinality(every) = 1 THEN 'single_airframe_outside_window'
    END,
    CASE
        WHEN cardinality(dated) = 1 THEN 'high'
        WHEN cardinality(dated) > 1 THEN NULL
        WHEN cardinality(open) = 1 OR cardinality(every) = 1 THEN 'medium'
    END,
    CASE
        WHEN cardinality(dated) = 1 THEN NULL
        WHEN cardinality(dated) > 1 THEN 'ambiguous_window'
        WHEN cardinality(open) = 1 THEN NULL
        WHEN cardinality(open) > 1 THEN 'ambiguous_window'
        WHEN cardinality(every) = 1 THEN NULL
        WHEN cardinality(every) = 0 THEN 'no_faa_record'
        ELSE 'no_window_multiple_airframes'
    END
FROM (SELECT DISTINCT tail_number, flight_date FROM staging.flight WHERE tail_number IS NOT NULL) t
CROSS JOIN LATERAL (
    SELECT
        ARRAY(SELECT DISTINCT frame FROM staging.faa_record r WHERE r.tail_number = t.tail_number
              AND r.valid_from <= t.flight_date AND coalesce(r.valid_to, 'infinity') >= t.flight_date) AS dated,
        ARRAY(SELECT DISTINCT frame FROM staging.faa_record r WHERE r.tail_number = t.tail_number
              AND coalesce(r.valid_from, '-infinity') <= t.flight_date AND coalesce(r.valid_to, 'infinity') >= t.flight_date) AS open,
        ARRAY(SELECT DISTINCT frame FROM staging.faa_record r WHERE r.tail_number = t.tail_number) AS every
) c;
```

Check `N500A` against this: `MASTER` starts after the flight, and `DEREG` has no start and ends 2024-08-01, so only `DEREG` covers the flight once blanks count as open, which gives rule 2. `N400A`: `MASTER` is dated and covers it, so rule 1 applies even though the blank `DEREG` row would also cover it. 
- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --env-file ../.env pytest tests/test_aircraft.py -q`
Expected: all passed.

- [ ] **Step 5: Record the tradeoff**

Replace the "Resolve aircraft from a current FAA snapshot plus DEREG" entry's **Revisit if** with its measured outcome once Task 6 has run, and append now:

```markdown
## 2026-11-01: Resolve tails by airframe, in a fixed order of rules
- **Chose:** a dated window first, then a window with blank dates open, then a tail that has only ever had one airframe. Anything else stays unresolved with a reason. Each link stores its method and confidence.
- **Gave up:** a complete match. About 2% of flights stay without an aircraft, and medium-confidence links rest on the registry never naming a second airframe for that tail.
- **Why:** a strict window strands 306 tails whose certificates were reissued after July 2024, even though the registry names only one airframe for them.
- **Revisit if:** archived registry snapshots turn up, or phase 3 needs aircraft type on the unresolved flights.
```

- [ ] **Step 6: Commit**

```bash
git add db pipelines DECISIONS.md
git commit -m "feat: resolve tails to airframes as of the flight date"
```

---

### Task 4: Ontology, blocking checks and one pipeline command

**Files:**
- Create: `db/migrations/007_ontology.sql`, `pipelines/flightops/resolve/ontology.sql`, `pipelines/flightops/dq/__init__.py`, `pipelines/flightops/dq/checks.py`, `pipelines/tests/test_pipeline.py`
- Modify: `pipelines/flightops/pipeline.py`, `pipelines/flightops/__main__.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `pipeline.build_staging(conn)`, `pipeline.build(conn)`, `checks.BlockingCheckFailed`, `checks.run(conn, phase: str) -> list[tuple]`, CLI command `build`, and CLI command `all` (migrate, load, build), `ontology.*`, `dq.check_result`, `dq.unresolved_link`.

- [ ] **Step 1: Write the failing tests**

`pipelines/tests/test_pipeline.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --env-file ../.env pytest tests/test_pipeline.py -q`
Expected: collection error, `flightops.dq` does not exist.

- [ ] **Step 3: Implement**

`db/migrations/007_ontology.sql`:

```sql
CREATE TABLE ontology.airport (
    airport_id     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ident          text NOT NULL UNIQUE,
    iata_code      text NOT NULL UNIQUE,
    iata_current   text,
    icao_code      text,
    bts_airport_id text,
    name           text NOT NULL,
    latitude       double precision NOT NULL,
    longitude      double precision NOT NULL,
    timezone       text NOT NULL
);

CREATE TABLE ontology.carrier (
    carrier_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code       text NOT NULL UNIQUE,
    iata_code  text,
    dot_id     text
);

CREATE TABLE ontology.aircraft (
    aircraft_id   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    frame         text NOT NULL UNIQUE,
    serial_number text NOT NULL,
    mfr_mdl_code  text NOT NULL,
    manufacturer  text,
    model         text
);

CREATE TABLE ontology.aircraft_registration (
    aircraft_id bigint NOT NULL REFERENCES ontology.aircraft,
    tail_number text NOT NULL,
    hex         text,
    valid_from  date,
    valid_to    date,
    source      text NOT NULL
);
CREATE INDEX ON ontology.aircraft_registration (tail_number);

CREATE TABLE ontology.flight (
    flight_id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    flight_date       date NOT NULL,
    carrier_id        bigint NOT NULL REFERENCES ontology.carrier,
    flight_number     text NOT NULL,
    origin_airport_id bigint NOT NULL REFERENCES ontology.airport,
    dest_airport_id   bigint NOT NULL REFERENCES ontology.airport,
    landed_airport_id bigint REFERENCES ontology.airport,
    crs_dep_local     text NOT NULL,
    tail_number       text,
    aircraft_id       bigint REFERENCES ontology.aircraft,
    aircraft_link_method     text,
    aircraft_link_confidence text,
    sched_dep_utc     timestamptz NOT NULL,
    sched_arr_utc     timestamptz,
    actual_dep_utc    timestamptz,
    actual_arr_utc    timestamptz,
    cancelled         boolean NOT NULL,
    cancellation_code text,
    diverted          boolean NOT NULL,
    reached_dest      boolean,
    dep_delay_min     integer,
    arr_delay_min     integer,
    block_mismatch    boolean NOT NULL,
    UNIQUE (flight_date, carrier_id, flight_number, origin_airport_id, crs_dep_local)
);
CREATE INDEX ON ontology.flight (tail_number, actual_dep_utc);
CREATE INDEX ON ontology.flight (origin_airport_id, sched_dep_utc);
CREATE INDEX ON ontology.flight (dest_airport_id, sched_arr_utc);

CREATE TABLE ontology.delay (
    flight_id bigint NOT NULL REFERENCES ontology.flight,
    cause     text NOT NULL,
    minutes   integer NOT NULL,
    PRIMARY KEY (flight_id, cause)
);

CREATE TABLE ontology.weather_observation (
    airport_id     bigint NOT NULL REFERENCES ontology.airport,
    observed_at    timestamptz NOT NULL,
    raw_text       text NOT NULL,
    wind_dir_deg   integer,
    wind_kt        integer,
    gust_kt        integer,
    visibility_sm  numeric,
    ceiling_ft     integer,
    temp_c         integer,
    dewpoint_c     integer,
    altimeter_inhg numeric,
    weather        text[] NOT NULL,
    PRIMARY KEY (airport_id, observed_at)
);

CREATE TABLE ontology.taf_forecast (
    airport_id    bigint NOT NULL REFERENCES ontology.airport,
    product_id    text NOT NULL,
    issued_at     timestamptz NOT NULL,
    valid_from    timestamptz NOT NULL,
    valid_to      timestamptz,
    forecast_type text NOT NULL,
    is_tempo      boolean NOT NULL,
    raw_text      text NOT NULL
);

CREATE TABLE dq.check_result (
    id      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_at  timestamptz NOT NULL,
    name    text NOT NULL,
    blocking boolean NOT NULL,
    passed  boolean,
    value   numeric,
    detail  text
);

CREATE TABLE dq.unresolved_link (
    entity  text NOT NULL,
    key     text NOT NULL,
    reason  text NOT NULL,
    flights bigint NOT NULL,
    PRIMARY KEY (entity, key, reason)
);
```

`pipelines/flightops/resolve/ontology.sql`:

```sql
TRUNCATE ontology.delay, ontology.taf_forecast, ontology.weather_observation, ontology.flight,
         ontology.aircraft_registration, ontology.aircraft, ontology.carrier, ontology.airport,
         dq.unresolved_link
RESTART IDENTITY;

INSERT INTO ontology.airport (ident, iata_code, iata_current, icao_code, bts_airport_id, name, latitude, longitude, timezone)
SELECT a.ident, a.bts_code, a.iata_current, a.icao_code,
       (SELECT min(origin_bts_id) FROM staging.flight WHERE origin = a.bts_code),
       a.name, a.latitude, a.longitude, a.tz
FROM staging.airport a ORDER BY a.bts_code;

INSERT INTO ontology.carrier (code, iata_code, dot_id)
SELECT carrier, min(carrier_iata), min(carrier_dot_id) FROM staging.flight GROUP BY 1 ORDER BY 1;

INSERT INTO ontology.aircraft (frame, serial_number, mfr_mdl_code, manufacturer, model)
SELECT DISTINCT ON (r.frame) r.frame, r.serial_number, r.mfr_mdl_code, trim(t.mfr), trim(t.model)
FROM staging.faa_record r LEFT JOIN staging.v_faa_acftref t ON trim(t.code) = r.mfr_mdl_code
ORDER BY r.frame;

INSERT INTO ontology.aircraft_registration (aircraft_id, tail_number, hex, valid_from, valid_to, source)
SELECT a.aircraft_id, r.tail_number, r.hex, r.valid_from, r.valid_to, r.source
FROM staging.faa_record r JOIN ontology.aircraft a USING (frame);

INSERT INTO ontology.flight (
    flight_date, carrier_id, flight_number, origin_airport_id, dest_airport_id, landed_airport_id, crs_dep_local,
    tail_number, aircraft_id, aircraft_link_method, aircraft_link_confidence,
    sched_dep_utc, sched_arr_utc, actual_dep_utc, actual_arr_utc, cancelled, cancellation_code,
    diverted, reached_dest, dep_delay_min, arr_delay_min, block_mismatch)
SELECT f.flight_date, c.carrier_id, f.flight_number, o.airport_id, d.airport_id, l.airport_id, f.crs_dep_local,
       f.tail_number, a.aircraft_id, k.method, k.confidence,
       f.sched_dep_utc, f.sched_arr_utc, f.actual_dep_utc, f.actual_arr_utc, f.cancelled, f.cancellation_code,
       f.diverted, f.reached_dest, f.dep_delay_min, f.arr_delay_min, f.block_mismatch
FROM staging.flight f
JOIN ontology.carrier c ON c.code = f.carrier
JOIN ontology.airport o ON o.iata_code = f.origin
JOIN ontology.airport d ON d.iata_code = f.dest
LEFT JOIN ontology.airport l ON l.iata_code = f.landed_station
LEFT JOIN staging.aircraft_link k ON k.tail_number = f.tail_number AND k.flight_date = f.flight_date
LEFT JOIN ontology.aircraft a ON a.frame = k.frame
ORDER BY f.flight_date, f.carrier, f.flight_number, f.origin, f.crs_dep_local;

-- Reported causes of zero are left out, and a flight with blank causes has no rows.
INSERT INTO ontology.delay (flight_id, cause, minutes)
SELECT o.flight_id, c.cause, c.minutes
FROM staging.flight f
JOIN ontology.carrier cr ON cr.code = f.carrier
JOIN ontology.airport oa ON oa.iata_code = f.origin
JOIN ontology.flight o ON o.flight_date = f.flight_date AND o.carrier_id = cr.carrier_id
    AND o.flight_number = f.flight_number AND o.origin_airport_id = oa.airport_id AND o.crs_dep_local = f.crs_dep_local
CROSS JOIN LATERAL (VALUES
    ('carrier', f.carrier_delay), ('weather', f.weather_delay), ('nas', f.nas_delay),
    ('security', f.security_delay), ('late_aircraft', f.late_aircraft_delay)
) c(cause, minutes)
WHERE c.minutes > 0;

-- Weather stations join through ICAO, which is what METARs and TAFs carry.
INSERT INTO ontology.weather_observation
SELECT a.airport_id, m.observed_at, m.raw_text, m.wind_dir_deg, m.wind_kt, m.gust_kt, m.visibility_sm,
       m.ceiling_ft, m.temp_c, m.dewpoint_c, m.altimeter_inhg, m.weather
FROM staging.metar m JOIN ontology.airport a ON a.icao_code = m.station_icao;

INSERT INTO ontology.taf_forecast
SELECT a.airport_id, t.product_id, t.issued_at, t.valid_from, t.valid_to, t.forecast_type, t.is_tempo, t.raw_text
FROM staging.taf t JOIN ontology.airport a ON a.icao_code = t.station_icao;

INSERT INTO dq.unresolved_link
SELECT 'tail', k.tail_number, k.unresolved_reason, count(*)
FROM staging.aircraft_link k
JOIN staging.flight f ON f.tail_number = k.tail_number AND f.flight_date = k.flight_date
WHERE k.unresolved_reason IS NOT NULL
GROUP BY 1, 2, 3;
```

`pipelines/flightops/dq/checks.py`:

```python
from datetime import datetime, timezone


class BlockingCheckFailed(Exception):
    pass


# name, SQL returning a single number, and the only passing value
BLOCKING = [
    ("flights_reconcile", "SELECT (SELECT count(*) FROM staging.v_bts) - (SELECT count(*) FROM staging.flight)", 0),
    (
        "atl_flights_reconcile",
        "SELECT (SELECT count(*) FROM staging.v_bts WHERE origin = 'ATL' OR dest = 'ATL') "
        "- (SELECT count(*) FROM staging.flight WHERE origin = 'ATL' OR dest = 'ATL')",
        0,
    ),
    (
        "airports_have_timezones",
        "SELECT count(*) FROM (SELECT origin c FROM staging.v_bts UNION SELECT dest FROM staging.v_bts) x "
        "LEFT JOIN staging.airport a ON a.bts_code = x.c WHERE a.tz IS NULL",
        0,
    ),
    (
        "operated_flights_have_times",
        "SELECT count(*) FROM staging.flight WHERE NOT cancelled AND (actual_dep_utc IS NULL OR actual_arr_utc IS NULL)",
        0,
    ),
    ("arrive_after_departure", "SELECT count(*) FROM staging.flight WHERE actual_arr_utc <= actual_dep_utc", 0),
    (
        "delay_causes_add_up",
        "SELECT count(*) FROM staging.flight WHERE carrier_delay IS NOT NULL AND arr_delay_min IS DISTINCT FROM "
        "carrier_delay + coalesce(weather_delay, 0) + coalesce(nas_delay, 0) + coalesce(security_delay, 0) + coalesce(late_aircraft_delay, 0)",
        0,
    ),
]

# name and SQL returning a single number, recorded without a pass or fail until thresholds are set
REPORTED = [
    ("flights_total", "SELECT count(*) FROM ontology.flight"),
    ("flights_touching_atl", "SELECT count(*) FROM staging.flight WHERE origin = 'ATL' OR dest = 'ATL'"),
    ("cancelled_jul19_23_touching_atl", "SELECT count(*) FROM staging.flight WHERE cancelled AND (origin = 'ATL' OR dest = 'ATL') AND flight_date BETWEEN '2024-07-19' AND '2024-07-23'"),
    ("operated_missing_tail", "SELECT count(*) FROM staging.flight WHERE NOT cancelled AND tail_number IS NULL"),
    ("block_mismatch_flights", "SELECT count(*) FROM staging.flight WHERE block_mismatch"),
    ("sched_arrival_not_after_departure", "SELECT count(*) FROM staging.flight WHERE sched_arr_utc <= sched_dep_utc"),
    ("flights_link_high", "SELECT count(*) FROM ontology.flight WHERE aircraft_link_confidence = 'high'"),
    ("flights_link_medium", "SELECT count(*) FROM ontology.flight WHERE aircraft_link_confidence = 'medium'"),
    ("flights_tail_unresolved", "SELECT coalesce(sum(flights), 0) FROM dq.unresolved_link WHERE entity = 'tail'"),
    ("flights_matched_active", "SELECT count(*) FROM ontology.flight f WHERE aircraft_id IS NOT NULL AND EXISTS (SELECT 1 FROM ontology.aircraft_registration r WHERE r.aircraft_id = f.aircraft_id AND r.tail_number = f.tail_number AND r.source = 'master')"),
    ("flights_matched_deregistered_only", "SELECT count(*) FROM ontology.flight f WHERE aircraft_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM ontology.aircraft_registration r WHERE r.aircraft_id = f.aircraft_id AND r.tail_number = f.tail_number AND r.source = 'master')"),
    ("metar_filtered_madis", "SELECT count(*) FROM staging.v_metar WHERE metar LIKE '%MADISHF%'"),
    ("metar_gaps_over_90_min", "SELECT count(*) FROM (SELECT observed_at - lag(observed_at) OVER (ORDER BY observed_at) AS gap FROM staging.metar) x WHERE gap > interval '90 minutes'"),
]


def run(conn, phase: str) -> list[tuple]:
    now = datetime.now(timezone.utc)
    results = []
    if phase == "blocking":
        for name, query, expected in BLOCKING:
            value = conn.execute(query).fetchone()[0]
            results.append((now, name, True, value == expected, value))
    else:
        for name, query in REPORTED:
            results.append((now, name, False, None, conn.execute(query).fetchone()[0]))
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO dq.check_result (run_at, name, blocking, passed, value) VALUES (%s, %s, %s, %s, %s)", results
        )
    failed = [r[1] for r in results if r[3] is False]
    if failed:
        raise BlockingCheckFailed(", ".join(failed))
    return results
```

Replace `pipelines/flightops/pipeline.py` with:

```python
from pathlib import Path

from flightops.dq import checks
from flightops.transform import airports, weather

PACKAGE = Path(__file__).resolve().parent


def run_sql(conn, relative_path: str) -> None:
    with conn.transaction():
        conn.execute((PACKAGE / relative_path).read_text())


def build_staging(conn) -> None:
    airports.build_airports(conn)
    run_sql(conn, "transform/flights.sql")
    weather.build_weather(conn)
    run_sql(conn, "resolve/aircraft.sql")


def build(conn) -> None:
    build_staging(conn)
    checks.run(conn, "blocking")  # a failure here leaves the previous ontology untouched
    run_sql(conn, "resolve/ontology.sql")
    checks.run(conn, "reported")
```

In `pipelines/flightops/__main__.py`, add `build` and `all` to the choices, import `pipeline`, and replace the `else:` block with:

```python
    else:
        with db.connect() as conn:
            if command in ("migrate", "all"):
                print("applied:", db.migrate(conn))
            if command in ("load", "all"):
                for f in registry.RAW_FILES:
                    result = raw.load_file(conn, f.source, f.table, f.path())
                    print(
                        f"{f.table}: {result.rows} rows, {result.quarantined} quarantined"
                        f"{' (already loaded)' if result.skipped else ''}"
                    )
            if command in ("build", "all"):
                pipeline.build(conn)
                for name, value, passed in conn.execute(
                    "SELECT name, value, passed FROM dq.check_result "
                    "WHERE run_at >= (SELECT max(run_at) - interval '1 hour' FROM dq.check_result) ORDER BY id"
                ):
                    print(f"{name}: {value}{'' if passed is None else ' ok' if passed else ' FAILED'}")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --env-file ../.env pytest -q`
Expected: all passed. `test_failed_blocking_check_keeps_the_previous_ontology` removes the `PBI` alias, so flight 9 drops out of staging and `flights_reconcile` fails.

- [ ] **Step 5: Commit**

```bash
git add db pipelines
git commit -m "feat: promote staging to ontology behind blocking checks"
```

---

### Task 5: Rotations with labelled breaks

**Files:**
- Create: `db/migrations/008_rotations.sql`, `pipelines/flightops/rotations/__init__.py`, `pipelines/flightops/rotations/rotations.sql`, `pipelines/tests/fixtures/bts_rotation.csv`, `pipelines/tests/test_rotations.py`
- Modify: `pipelines/flightops/pipeline.py`, `pipelines/flightops/dq/checks.py`

**Interfaces:**
- Consumes: `ontology.flight`.
- Produces: `ontology.rotation_leg(flight_id, tail_number, leg_seq, prev_flight_id, connects, gap_minutes, break_cause, touched_atl)` and view `ontology.atl_rotation_leg`.

Break labels, checked in this order, when a leg's origin differs from the previous landing station:

| Label | Condition | Prototype count |
|---|---|---|
| `after_diversion` | The previous leg was diverted | 277 |
| `overlap_data_error` | This departure precedes the previous arrival | 8 |
| `short_gap_likely_data_error` | Under 2 hours on the ground | 14 |
| `likely_unreported_flying` | 2 to 24 hours | 5,533 |
| `long_gap_unreported_or_out_of_service` | 24 hours or more | 2,088 |

These are likely causes, and BTS doesn't identify the real one. Flying a non-reporting or international leg is the expected reason for the two larger groups.

- [ ] **Step 1: Write the fixture and failing tests**

`pipelines/tests/fixtures/bts_rotation.csv` has tail `N1R` with connecting legs, a cancelled flight between them that must not count, a break, and tail `N2R` that never touches ATL and tail `N3R` that stops short on a diversion:

```csv
flightdate,reporting_airline,tail_number,flight_number_reporting_airline,origin,dest,crsdeptime,deptime,depdelay,crsarrtime,arrtime,crselapsedtime,actualelapsedtime,cancelled,diverted,divreacheddest,div1airport,div1wheelson
2024-07-19,DL,N1R,1,ATL,ORD,0800,0800,0.00,0855,0855,115.00,115.00,0.00,0.00,,,
2024-07-19,DL,N1R,2,ORD,LGA,1000,,,1300,,120.00,,1.00,0.00,,,
2024-07-19,DL,N1R,3,ORD,ATL,1100,1100,0.00,1400,1400,120.00,120.00,0.00,0.00,,,
2024-07-19,DL,N1R,4,LGA,ATL,1900,1900,0.00,2115,2115,135.00,135.00,0.00,0.00,,,
2024-07-19,DL,N2R,5,ORD,LGA,0800,0800,0.00,1100,1100,120.00,120.00,0.00,0.00,,,
2024-07-19,DL,N2R,6,LGA,ORD,1200,1200,0.00,1320,1320,140.00,140.00,0.00,0.00,,,
2024-07-19,DL,N3R,7,ATL,LGA,0800,0800,0.00,1015,,135.00,,0.00,1.00,0.00,IAD,0950
2024-07-19,DL,N3R,8,IAD,LGA,1200,1200,0.00,1300,1300,60.00,60.00,0.00,0.00,,,
```

`pipelines/tests/test_rotations.py`:

```python
import pytest

from flightops import pipeline


@pytest.fixture
def legs(conn, load_fixture):
    load_fixture("ourairports_airports", "airports.csv")
    load_fixture("bts_ontime", "bts_rotation.csv")
    pipeline.build(conn)
    rows = conn.execute(
        "select f.flight_number, r.leg_seq, r.connects, r.break_cause, r.touched_atl "
        "from ontology.rotation_leg r join ontology.flight f using (flight_id)"
    ).fetchall()
    return {r[0]: r[1:] for r in rows}


def test_cancelled_flight_never_joins_a_rotation(legs):
    assert "2" not in legs


def test_first_leg_has_nothing_to_connect_to(legs):
    assert legs["1"] == (1, None, None, True)


def test_consecutive_legs_connect_across_a_cancelled_flight(legs):
    assert legs["3"] == (2, True, None, True)


def test_station_mismatch_is_a_labelled_gap(legs):
    assert legs["4"] == (3, False, "likely_unreported_flying", True)


def test_tails_that_never_touched_atl_are_flagged_not_dropped(legs):
    assert legs["5"][-1] is False
    assert legs["6"] == (2, True, None, False)


def test_diversion_connects_from_where_it_actually_landed(legs):
    assert legs["8"] == (2, True, None, True)


def test_gap_after_a_short_diversion_uses_the_diversion_label(conn, load_fixture):
    load_fixture("ourairports_airports", "airports.csv")
    load_fixture("bts_ontime", "bts_diversion_break.csv")
    pipeline.build(conn)
    cause = conn.execute(
        "select r.break_cause from ontology.rotation_leg r join ontology.flight f using (flight_id) "
        "where f.flight_number = '2'"
    ).fetchone()[0]
    assert cause == "after_diversion"


def test_atl_view_excludes_other_tails(conn, legs):
    assert conn.execute(
        "select count(*) from ontology.atl_rotation_leg where tail_number = 'N2R'"
    ).fetchone()[0] == 0
```

`pipelines/tests/fixtures/bts_diversion_break.csv`:

```csv
flightdate,reporting_airline,tail_number,flight_number_reporting_airline,origin,dest,crsdeptime,deptime,depdelay,crsarrtime,arrtime,crselapsedtime,actualelapsedtime,cancelled,diverted,divreacheddest,div1airport,div1wheelson
2024-07-19,DL,N4R,1,ATL,LGA,0800,0800,0.00,1015,,135.00,,0.00,1.00,0.00,IAD,0950
2024-07-19,DL,N4R,2,LGA,ATL,1400,1400,0.00,1615,1615,135.00,135.00,0.00,0.00,,,
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --env-file ../.env pytest tests/test_rotations.py -q`
Expected: failures, because `ontology.rotation_leg` does not exist.

- [ ] **Step 3: Implement**

`db/migrations/008_rotations.sql`:

```sql
CREATE TABLE ontology.rotation_leg (
    flight_id      bigint PRIMARY KEY REFERENCES ontology.flight,
    tail_number    text NOT NULL,
    leg_seq        integer NOT NULL,
    prev_flight_id bigint REFERENCES ontology.flight,
    connects       boolean,
    gap_minutes    integer,
    break_cause    text,
    touched_atl    boolean NOT NULL,
    UNIQUE (tail_number, leg_seq)
);

CREATE VIEW ontology.atl_rotation_leg AS
SELECT * FROM ontology.rotation_leg WHERE touched_atl;
```

`pipelines/flightops/rotations/rotations.sql`:

```sql
TRUNCATE ontology.rotation_leg;

WITH atl AS (SELECT airport_id FROM ontology.airport WHERE iata_code = 'ATL'),
atl_tails AS (
    -- Includes cancelled flights: an aircraft assigned to ATL and cancelled still touched the hub's plan.
    SELECT DISTINCT tail_number FROM ontology.flight
    WHERE tail_number IS NOT NULL
      AND (origin_airport_id IN (SELECT airport_id FROM atl) OR dest_airport_id IN (SELECT airport_id FROM atl))
),
legs AS (
    SELECT f.flight_id, f.tail_number, f.origin_airport_id, f.actual_dep_utc,
           row_number() OVER w AS leg_seq,
           lag(f.flight_id) OVER w AS prev_flight_id,
           lag(f.landed_airport_id) OVER w AS prev_landed,
           lag(f.actual_arr_utc) OVER w AS prev_arr,
           lag(f.diverted) OVER w AS prev_diverted
    FROM ontology.flight f
    WHERE NOT f.cancelled AND f.tail_number IS NOT NULL
    WINDOW w AS (PARTITION BY f.tail_number ORDER BY f.actual_dep_utc, f.flight_id)
)
INSERT INTO ontology.rotation_leg
SELECT flight_id, tail_number, leg_seq, prev_flight_id,
       CASE WHEN prev_flight_id IS NOT NULL THEN prev_landed = origin_airport_id END,
       (extract(epoch FROM actual_dep_utc - prev_arr) / 60)::int,
       CASE
           WHEN prev_flight_id IS NULL OR prev_landed = origin_airport_id THEN NULL
           WHEN prev_diverted THEN 'after_diversion'
           WHEN actual_dep_utc < prev_arr THEN 'overlap_data_error'
           WHEN actual_dep_utc - prev_arr < interval '2 hours' THEN 'short_gap_likely_data_error'
           WHEN actual_dep_utc - prev_arr < interval '24 hours' THEN 'likely_unreported_flying'
           ELSE 'long_gap_unreported_or_out_of_service'
       END,
       tail_number IN (SELECT tail_number FROM atl_tails)
FROM legs
ORDER BY tail_number, leg_seq;
```

In `pipeline.py`, add `run_sql(conn, "rotations/rotations.sql")` after the ontology line in `build`.

In `dq/checks.py`, append to `REPORTED`:

```python
    ("rotation_pairs", "SELECT count(*) FROM ontology.rotation_leg WHERE connects IS NOT NULL"),
    ("rotation_pairs_connected", "SELECT count(*) FROM ontology.rotation_leg WHERE connects"),
    ("atl_rotation_pairs", "SELECT count(*) FROM ontology.atl_rotation_leg WHERE connects IS NOT NULL"),
    ("atl_rotation_pairs_connected", "SELECT count(*) FROM ontology.atl_rotation_leg WHERE connects"),
    ("breaks_after_diversion", "SELECT count(*) FROM ontology.rotation_leg WHERE break_cause = 'after_diversion'"),
    ("breaks_overlap", "SELECT count(*) FROM ontology.rotation_leg WHERE break_cause = 'overlap_data_error'"),
    ("breaks_short_gap", "SELECT count(*) FROM ontology.rotation_leg WHERE break_cause = 'short_gap_likely_data_error'"),
    ("breaks_unreported_flying", "SELECT count(*) FROM ontology.rotation_leg WHERE break_cause = 'likely_unreported_flying'"),
    ("breaks_long_gap", "SELECT count(*) FROM ontology.rotation_leg WHERE break_cause = 'long_gap_unreported_or_out_of_service'"),
```

Also add `ontology.rotation_leg` to the `TRUNCATE` list at the top of `resolve/ontology.sql`, because it references `ontology.flight`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --env-file ../.env pytest -q`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add db pipelines
git commit -m "feat: rebuild national rotations and label breaks"
```

---

### Task 6: Run on real data and reconcile

**Files:**
- Modify: `docs/data-sources.md`, `docs/phase-1-plan.md`, `docs/roadmap.md` only if scope changed, `DECISIONS.md`, `CLAUDE.md`

**Interfaces:**
- Consumes: the CLI.
- Produces: populated `ontology` and `dq`.

- [ ] **Step 1: Run the full pipeline**

Run: `uv run --env-file ../.env python -m flightops all`
Expected: raw tables report `(already loaded)`, all blocking checks print `ok`, and the reported values below print. Use superpowers:systematic-debugging on any failure, and never weaken a check to pass it.

| Value | Expected |
|---|---|
| `flights_total` | 634,613 |
| `flights_touching_atl` | 60,144 |
| `cancelled_jul19_23_touching_atl` | 3,208 |
| `operated_missing_tail` | 0 |
| `block_mismatch_flights` | 316 |
| `sched_arrival_not_after_departure` | 61 |
| `metar_filtered_madis` | 9,493 |
| `metar_gaps_over_90_min` | 0 |
| `rotation_pairs` | 610,617 |
| `rotation_pairs_connected` | 602,697 |
| `atl_rotation_pairs` | 374,452 |
| `breaks_after_diversion` | 277 |
| `flights_tail_unresolved` | at most 15,274 |

- [ ] **Step 2: Prove a rebuild is identical**

Run: `psql -h localhost flightops -Atc "select md5(string_agg(flight_id||'|'||coalesce(aircraft_id::text,'')||'|'||coalesce(actual_arr_utc::text,''), ',' order by flight_id)) from ontology.flight"`, then `uv run --env-file ../.env python -m flightops build`, then the same query.
Expected: the same hash both times.

- [ ] **Step 3: Answer the phase's question with SQL**

Pick the first Delta tail with a July 19 cancellation:

```sql
SELECT f.flight_date, f.flight_number, o.iata_code AS origin, d.iata_code AS dest, l.iata_code AS landed,
       f.sched_dep_utc, f.actual_dep_utc, f.actual_arr_utc, f.cancelled, f.cancellation_code, r.break_cause,
       a.model, f.aircraft_link_method
FROM ontology.flight f
JOIN ontology.airport o ON o.airport_id = f.origin_airport_id
JOIN ontology.airport d ON d.airport_id = f.dest_airport_id
LEFT JOIN ontology.airport l ON l.airport_id = f.landed_airport_id
LEFT JOIN ontology.rotation_leg r USING (flight_id)
LEFT JOIN ontology.aircraft a USING (aircraft_id)
WHERE f.tail_number = (SELECT min(tail_number) FROM ontology.flight WHERE cancelled AND flight_date = '2024-07-19' AND tail_number LIKE 'N%DN')
  AND f.flight_date BETWEEN '2024-07-18' AND '2024-07-20'
ORDER BY f.sched_dep_utc;
```

Expected: a readable timeline whose legs are in time order, with cancelled legs having no `actual_arr_utc`.

- [ ] **Step 4: Update the docs and commit**

Record measured results in `docs/data-sources.md`. Close the "Open before step 3" items in `docs/phase-1-plan.md`. Update the FAA snapshot entry in `DECISIONS.md` with the measured match rate. Update Status in `CLAUDE.md` so the next action is planning steps 6-7, and add `build` and `all` to the commands.

```bash
git add docs DECISIONS.md CLAUDE.md
git commit -m "feat: build July 2024 ontology and rotations, and reconcile"
```
