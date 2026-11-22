# Phase 2, steps 1-2: `app_read` views and the shared adverse rule

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** add the read-only SQL layer that the phase 2 app will query, and move the adverse-weather rule into the database so the report and the app share one definition.

**Architecture:** two new SQL migrations. `011_is_adverse.sql` adds `ontology.is_adverse(weather_observation)`, which `report.py` then uses. `012_app_read.sql` adds the `app_read` schema: views over `ontology` and `dq`, a `break_label` function, and a `flightops_app` login role that can only `SELECT` from `app_read`. pytest exercises everything against a fixture-built `flightops_test` database.

**Tech Stack:** Postgres 18 (Postgres.app), Python with `uv`, psycopg 3 and pytest. The existing fixtures `conn` and `load_fixture` live in `pipelines/tests/conftest.py`.

## Global Constraints

- Run every command from `pipelines/`. Tests: `uv run --env-file ../.env pytest`. CLI: `uv run --env-file ../.env python -m flightops <command>`.
- Schema changes go only through `db/migrations/NNN_*.sql`. The runner (`flightops/db.py:migrate`) records filenames, so **never edit a migration after it has been applied to the local `flightops` database**. Add a new one instead.
- Pipelines are the only writers to `raw`, `staging`, `ontology` and `dq`. `app_read` holds views and functions only, never data.
- The ATL day, the adverse rule, the stale-METAR rule and break labels live only in SQL.
- Every non-trivial transform gets a test using a small fixture in `pipelines/tests/fixtures/`.
- Pass dates to psycopg as `datetime.date`, not strings.
- `DECISIONS.md` entries are appended, newest last, using its existing format: **Chose / Gave up / Why / Revisit if**.

---

### Task 1: `ontology.is_adverse` and the report using it

**Files:**
- Create: `db/migrations/011_is_adverse.sql`
- Create: `pipelines/tests/test_adverse.py`
- Modify: `pipelines/flightops/report.py` (the `ADVERSE` constant at line 31 and its uses at lines 45, 122, 140 and 142)
- Modify: `DECISIONS.md` (append one entry)

**Interfaces:**
- Produces: `ontology.is_adverse(w ontology.weather_observation) RETURNS boolean`. It never returns NULL. Task 2's views call it.

- [ ] **Step 1: Write the failing test**

`pipelines/tests/test_adverse.py`:

```python
import pytest

# Column order of ontology.weather_observation: airport_id, observed_at, raw_text, wind_dir_deg, wind_kt,
# gust_kt, visibility_sm, ceiling_ft, temp_c, dewpoint_c, altimeter_inhg, weather
ADVERSE = (
    "SELECT ontology.is_adverse(ROW(1, now(), '', NULL, NULL, %s::int, %s::numeric, %s::int, "
    "NULL, NULL, NULL, %s::text[])::ontology.weather_observation)"
)


@pytest.mark.parametrize(
    "weather, ceiling, visibility, gust, expected",
    [
        ([], 5000, 10, None, False),
        (["TSRA"], None, 10, None, True),
        (["VCTS"], None, 10, None, True),
        (["+RA"], None, 10, None, True),
        (["-RA"], None, 10, None, False),
        (["FG"], None, 10, None, True),
        (["-SN"], None, 10, None, True),
        (["FZDZ"], None, 10, None, True),
        (["BR"], 900, 10, None, True),
        ([], 1000, 10, None, False),
        ([], None, 2.5, None, True),
        ([], None, 3, None, False),
        ([], None, 10, 30, True),
        ([], None, 10, 29, False),
        ([], None, None, None, False),
    ],
)
def test_adverse_rule(conn, weather, ceiling, visibility, gust, expected):
    assert conn.execute(ADVERSE, (gust, visibility, ceiling, weather)).fetchone()[0] is expected
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `uv run --env-file ../.env pytest tests/test_adverse.py -v`
Expected: every case FAILS with `psycopg.errors.UndefinedFunction: function ontology.is_adverse(...) does not exist`.

- [ ] **Step 3: Write the migration**

`db/migrations/011_is_adverse.sql`:

```sql
-- Weather that could delay flights, as this project defines it (see DECISIONS.md). Shared by the report and app_read.
CREATE FUNCTION ontology.is_adverse(w ontology.weather_observation) RETURNS boolean
LANGUAGE sql IMMUTABLE AS $$
    SELECT coalesce(
        array_to_string(w.weather, ' ') ~ '(TS|\+RA|FG|SN|FZ)'
        OR coalesce(w.ceiling_ft, 99999) < 1000
        OR w.visibility_sm < 3
        OR coalesce(w.gust_kt, 0) >= 30,
        false)
$$;
```

The outer `coalesce` is new. The report's inline expression could return NULL when visibility was missing. That doesn't change any report count, because `FILTER (WHERE NULL)` and `bool_or` both treat NULL as false here, which Step 7 confirms.

- [ ] **Step 4: Run the test to make sure it passes**

Run: `uv run --env-file ../.env pytest tests/test_adverse.py -v`
Expected: 15 passed.

- [ ] **Step 5: Point `report.py` at the function**

In `pipelines/flightops/report.py`:

1. Delete the `ADVERSE = r"""..."""` constant (lines 31-32).
2. In `CROSS_CHECK`, replace `SELECT coalesce(bool_or({adverse}), false) AS adverse` with:
   ```python
       SELECT coalesce(bool_or(ontology.is_adverse(w)), false) AS adverse
   ```
3. In the "ATL by day, July 15-27" section, replace `AND {ADVERSE}) AS adverse_metars` with:
   ```python
           WHERE (w.observed_at AT TIME ZONE 'America/New_York')::date = f.flight_date AND ontology.is_adverse(w)) AS adverse_metars
   ```
   That is, keep the line as it is with `{ADVERSE}` swapped for `ontology.is_adverse(w)`.
4. In both `CROSS_CHECK.format(...)` calls, delete the `, adverse=ADVERSE` argument.

Then run `grep -n ADVERSE flightops/report.py`. Expected: no output.

- [ ] **Step 6: Run the whole suite**

Run: `uv run --env-file ../.env pytest`
Expected: all pass, including `tests/test_report.py`.

- [ ] **Step 7: Regenerate the real report and check that no table changed**

```bash
uv run --env-file ../.env python -m flightops migrate
uv run --env-file ../.env python -m flightops report
git diff -U0 ../docs/phase-1-report.md | grep '^[-+]|' ; echo "table rows changed: $?"
git diff --stat ../docs/phase-1-report.md
```

Expected: `migrate` prints `applied: ['011_is_adverse.sql']`. The grep prints nothing and `table rows changed: 1`, meaning no table row differs. The only diff lines are the SQL shown under two tables. If any `|` row changed, stop: the function doesn't match the old expression.

- [ ] **Step 8: Append the decision**

Append to `DECISIONS.md`:

```markdown
## 2026-11-22: Define adverse weather once, in `ontology`
- **Chose:** `ontology.is_adverse(weather_observation)`, used by the report and by the app's views. It never returns NULL: missing fields count as not adverse.
- **Gave up:** a definition that sits beside the report's prose. A reader of the report now follows the function name to the migration.
- **Why:** phase 2 shades adverse hours on the timeline. Two copies of the rule would drift, and the earlier entry said to move it into `ontology` once a second reader needed it.
- **Revisit if:** phase 3 tests weather as a delay predictor. Then check the rule against delays instead of keeping it by judgment.
```

- [ ] **Step 9: Commit**

```bash
git add ../db/migrations/011_is_adverse.sql tests/test_adverse.py flightops/report.py ../docs/phase-1-report.md ../DECISIONS.md
git commit -m "feat: define adverse weather once in ontology and use it in the report"
```

---

### Task 2: the `app_read` schema

**Files:**
- Create: `pipelines/tests/fixtures/bts_app_read.csv`
- Create: `db/migrations/012_app_read.sql`
- Create: `pipelines/tests/test_app_read.py`

**Interfaces:**
- Consumes: `ontology.is_adverse(w)` from Task 1.
- Produces, for the Laravel steps (3-5). Every view is filtered by plain columns.
  - `app_read.day_range(first_day date, last_day date)`: one row. It is the range of BTS `flight_date`, and the app's allowed days.
  - `app_read.hub_day_hourly`: keyed by `(atl_day date, atl_hour int, direction text)`, with `scheduled, operated, on_time, delayed, diverted, cancelled` as bigint. `direction` is `'dep'` or `'arr'`.
  - `app_read.hub_day_weather`: `atl_day, atl_hour, observed_at, adverse, wind_dir_deg, wind_kt, gust_kt, visibility_sm, ceiling_ft, weather text[], raw_text`.
  - `app_read.hub_day_flights`: `atl_day, atl_hour, direction, status ('on_time'|'delayed'|'diverted'|'cancelled'), flight_id, carrier, flight_number, other_station, landed_station, tail_number, sched_dep_utc, sched_arr_utc, actual_dep_utc, actual_arr_utc, dep_delay_min, arr_delay_min, cancellation_code, delays jsonb ({cause: minutes} or NULL), metar_observed_at, metar_staleness_min, metar_raw_text, metar_adverse, metar_stale, block_mismatch, aircraft_unresolved, aircraft_medium_confidence, rotation_break`. The last five are non-null booleans.
  - `app_read.hub_day_caveats`: keyed by `atl_day`, with counts `metar_stale, block_mismatch, aircraft_unresolved, aircraft_medium_confidence, rotation_break`.
  - `app_read.tail_legs`: keyed by `(tail_number, flight_id)`, with `leg_seq` (NULL for cancelled), `leg_day, carrier, flight_number, origin, origin_tz, dest, dest_tz, landed, sched_dep_utc, sched_arr_utc, actual_dep_utc, actual_arr_utc, cancelled, cancellation_code, diverted, dep_delay_min, arr_delay_min, delays, connects, gap_minutes, break_cause, break_label, prev_station, metar_observed_at, metar_staleness_min, metar_raw_text, metar_adverse`.
  - `app_read.tail_aircraft`: `tail_number, aircraft_id, manufacturer, model, method, confidence, unresolved_reason, flights`.
  - Role `flightops_app` (LOGIN, no password, which suits the local trust setup) with `SELECT` on `app_read` only.

The fixture's cases. All local times are EDT (UTC-4) except ORD (CDT, UTC-5) and LAX (PDT, UTC-7). METARs come from the existing `metar_join.csv`: 11:52Z clear, 12:30Z thunderstorm, 12:52Z, 12:55Z MADIS (filtered out) and 14:52Z.

| # | Tail | Leg | Case | ATL day / local hour | Status | METAR used |
|---|---|---|---|---|---|---|
| 10 | N1A | ATL→ORD 08:00 | baseline departure | 07-19 / 8 | on_time | actual 12:00Z, 11:52, 8 min |
| 11 | N1A | ORD→ATL, lands 13:25 | 30 min late, carrier 10 + late aircraft 20 | 07-19 / 12 | delayed | actual 17:25Z, 14:52, 153 min, stale |
| 12 | N1A | ATL→LGA 14:00 | cancelled, code A | 07-19 / 14 | cancelled | scheduled 18:00Z, 14:52, 188 min, stale |
| 13 | N1A | LGA→ATL 18:00 | origin ≠ previous landing (ATL), gap 275 min | 07-19 / 20 | on_time | actual 00:15Z, 563 min, stale |
| 14 | N2A | LAX→ATL 23:00 PDT on 07-19 | lands 06:30 on 07-20 | **07-20** / 6 | on_time | — |
| 15 | N3A | ORD→ATL, diverted to CLE | never reached ATL | 07-19 / 16 | diverted | scheduled 20:55Z, 363 min, stale |
| 16 | N4A | ORD→LGA | tail never touched ATL | — | — | — |
| 18 | N3A | CLE→LGA | leg away from ATL, after the diversion | — (leg day 07-19) | — | none |
| 17 | N5A | ATL→ORD 07:00 | departs before the first METAR (11:52Z) | 07-19 / 7 | on_time | none, so stale |

Flight 14's METAR is the previous afternoon's 14:52Z, 1,178 minutes old.

No FAA files are loaded, so every tail is unresolved (`no_faa_record`).

- [ ] **Step 1: Write the fixture**

`pipelines/tests/fixtures/bts_app_read.csv`:

```csv
flightdate,reporting_airline,tail_number,flight_number_reporting_airline,origin,dest,crsdeptime,deptime,depdelay,crsarrtime,arrtime,arrdelay,crselapsedtime,actualelapsedtime,cancelled,cancellationcode,diverted,divreacheddest,div1airport,div1wheelson,carrierdelay,weatherdelay,nasdelay,securitydelay,lateaircraftdelay
2024-07-19,DL,N1A,10,ATL,ORD,0800,0800,0.00,0855,0855,0.00,115.00,115.00,0.00,,0.00,,,,,,,,
2024-07-19,DL,N1A,11,ORD,ATL,1000,1030,30.00,1255,1325,30.00,115.00,115.00,0.00,,0.00,,,,10.00,0.00,0.00,0.00,20.00
2024-07-19,DL,N1A,12,ATL,LGA,1400,,,1615,,,135.00,,1.00,A,0.00,,,,,,,,
2024-07-19,DL,N1A,13,LGA,ATL,1800,1800,0.00,2015,2015,0.00,135.00,135.00,0.00,,0.00,,,,,,,,
2024-07-19,DL,N2A,14,LAX,ATL,2300,2300,0.00,0630,0630,0.00,270.00,270.00,0.00,,0.00,,,,,,,,
2024-07-19,DL,N3A,15,ORD,ATL,1400,1400,0.00,1655,,,115.00,,0.00,,1.00,0.00,CLE,1630,,,,,
2024-07-19,DL,N4A,16,ORD,LGA,0800,0800,0.00,1100,1100,0.00,120.00,120.00,0.00,,0.00,,,,,,,,
2024-07-19,DL,N3A,18,CLE,LGA,1900,1900,0.00,2030,2030,0.00,90.00,90.00,0.00,,0.00,,,,,,,,
2024-07-19,DL,N5A,17,ATL,ORD,0700,0700,0.00,0755,0755,0.00,115.00,115.00,0.00,,0.00,,,,,,,,
```

- [ ] **Step 2: Write the failing tests**

`pipelines/tests/test_app_read.py`:

```python
from datetime import date

import psycopg
import pytest

from flightops import pipeline

D19, D20 = date(2024, 7, 19), date(2024, 7, 20)


@pytest.fixture
def built(conn, load_fixture):
    load_fixture("ourairports_airports", "airports.csv")
    load_fixture("bts_ontime", "bts_app_read.csv")
    load_fixture("iem_metar", "metar_join.csv")
    pipeline.build(conn)
    return conn


def by_flight(conn, sql, params=()):
    return {r[0]: r[1:] for r in conn.execute(sql, params).fetchall()}


def hub(conn, day):
    return by_flight(
        conn,
        "select flight_number, atl_hour, direction, status from app_read.hub_day_flights where atl_day = %s",
        (day,),
    )


def test_hub_day_holds_atl_flights_by_their_scheduled_atl_event(built):
    assert hub(built, D19) == {
        "17": (7, "dep", "on_time"),
        "10": (8, "dep", "on_time"),
        "11": (12, "arr", "delayed"),
        "12": (14, "dep", "cancelled"),
        "13": (20, "arr", "on_time"),
        "15": (16, "arr", "diverted"),
    }


def test_inbound_flight_belongs_to_the_atl_day_it_lands(built):
    assert hub(built, D20) == {"14": (6, "arr", "on_time")}


def test_hourly_counts_split_by_status(built):
    rows = built.execute(
        "select atl_hour, direction, scheduled, operated, on_time, delayed, diverted, cancelled "
        "from app_read.hub_day_hourly where atl_day = %s order by 1, 2",
        (D19,),
    ).fetchall()
    assert rows == [
        (7, "dep", 1, 1, 1, 0, 0, 0),
        (8, "dep", 1, 1, 1, 0, 0, 0),
        (12, "arr", 1, 1, 0, 1, 0, 0),
        (14, "dep", 1, 0, 0, 0, 0, 1),
        (16, "arr", 1, 1, 0, 0, 1, 0),
        (20, "arr", 1, 1, 1, 0, 0, 0),
    ]


def test_metar_is_from_the_actual_atl_event_else_the_scheduled_one(built):
    assert by_flight(
        built,
        "select flight_number, metar_staleness_min, metar_stale from app_read.hub_day_flights where atl_day = %s",
        (D19,),
    ) == {
        "17": (None, True),  # no METAR before 07:00 local counts as stale
        "10": (8, False),
        "11": (153, True),
        "12": (188, True),
        "13": (563, True),
        "15": (363, True),
    }


def test_metar_from_the_previous_day_is_still_used_and_stale(built):
    assert by_flight(
        built, "select flight_number, metar_staleness_min, metar_stale from app_read.hub_day_flights where atl_day = %s", (D20,)
    ) == {"14": (1178, True)}


def test_delays_are_minutes_by_cause(built):
    delays = by_flight(built, "select flight_number, delays from app_read.hub_day_flights where atl_day = %s", (D19,))
    assert delays["11"] == ({"carrier": 10, "late_aircraft": 20},)
    assert delays["10"] == (None,)


def test_caveats_count_each_flag_for_the_day(built):
    assert built.execute(
        "select metar_stale, block_mismatch, aircraft_unresolved, aircraft_medium_confidence, rotation_break "
        "from app_read.hub_day_caveats where atl_day = %s",
        (D19,),
    ).fetchone() == (5, 0, 6, 0, 1)


def test_weather_strip_marks_adverse_metars_and_skips_madis(built):
    assert built.execute(
        "select atl_hour, adverse from app_read.hub_day_weather where atl_day = %s order by observed_at", (D19,)
    ).fetchall() == [(7, False), (8, True), (8, False), (10, False)]


def test_tail_legs_include_cancelled_flights_and_label_gaps(built):
    rows = built.execute(
        "select flight_number, leg_seq, leg_day, connects, gap_minutes, break_label, prev_station "
        "from app_read.tail_legs where tail_number = 'N1A' order by sched_dep_utc"
    ).fetchall()
    assert rows == [
        ("10", 1, D19, None, None, None, None),
        ("11", 2, D19, True, 95, None, "ORD"),
        ("12", None, D19, None, None, None, None),
        ("13", 3, D19, False, 275, "Likely flew legs BTS does not report", "ATL"),
    ]


def test_tail_legs_cover_legs_away_from_atl(built):
    assert by_flight(
        built,
        "select flight_number, connects, prev_station, metar_staleness_min from app_read.tail_legs "
        "where tail_number = 'N3A'",
    ) == {"15": (None, None, 363), "18": (True, "CLE", None)}


def test_leg_day_is_the_atl_local_date_of_scheduled_departure(built):
    assert built.execute("select leg_day from app_read.tail_legs where flight_number = '14'").fetchone() == (D20,)


def test_tails_that_never_touched_atl_are_absent(built):
    assert built.execute("select count(*) from app_read.tail_legs where tail_number = 'N4A'").fetchone() == (0,)


def test_tail_aircraft_gives_the_unresolved_reason(built):
    assert built.execute(
        "select model, confidence, unresolved_reason, flights from app_read.tail_aircraft where tail_number = 'N1A'"
    ).fetchall() == [(None, None, "no_faa_record", 4)]


@pytest.mark.parametrize(
    "cause",
    [
        "likely_unreported_flying",
        "long_gap_unreported_or_out_of_service",
        "after_diversion",
        "overlap_data_error",
        "short_gap_likely_data_error",
    ],
)
def test_every_break_cause_has_a_readable_label(conn, cause):
    label = conn.execute("select app_read.break_label(%s)", (cause,)).fetchone()[0]
    assert label and label != cause


def test_unknown_break_cause_shows_as_delivered(conn):
    assert conn.execute("select app_read.break_label('new_cause')").fetchone() == ("new_cause",)


def test_day_range_is_the_bts_flight_dates(built):
    assert built.execute("select first_day, last_day from app_read.day_range").fetchone() == (D19, D19)


def test_app_role_reads_app_read_only(built):
    built.execute("SET ROLE flightops_app")
    try:
        assert built.execute("select count(*) from app_read.hub_day_flights").fetchone() == (7,)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            built.execute("select 1 from ontology.flight")
    finally:
        built.execute("RESET ROLE")


@pytest.mark.parametrize(
    "statement",
    ["insert into ontology.carrier (code) values ('XX')", "create table app_read.scratch (i int)"],
)
def test_app_role_cannot_write(built, statement):
    built.execute("SET ROLE flightops_app")
    try:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            built.execute(statement)
    finally:
        built.execute("RESET ROLE")
```

- [ ] **Step 3: Run the tests to make sure they fail**

Run: `uv run --env-file ../.env pytest tests/test_app_read.py -v`
Expected: every test FAILS with `UndefinedTable: relation "app_read..." does not exist` or `UndefinedFunction` for `break_label`.

- [ ] **Step 4: Write the migration**

`db/migrations/012_app_read.sql`:

```sql
-- Read-only views for the app. Holds no data; pipelines own it, the app reads it as flightops_app.
CREATE SCHEMA app_read;

CREATE FUNCTION app_read.break_label(cause text) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE cause
        WHEN 'likely_unreported_flying' THEN 'Likely flew legs BTS does not report'
        WHEN 'long_gap_unreported_or_out_of_service' THEN 'Over a day unaccounted for: unreported flying or out of service'
        WHEN 'after_diversion' THEN 'Repositioned after a diversion'
        WHEN 'overlap_data_error' THEN 'Departed before the previous leg landed: likely a data error'
        WHEN 'short_gap_likely_data_error' THEN 'Under 2 hours to reach this station: likely a data error'
        ELSE cause
    END
$$;

-- Days the app offers. BTS flight_date, so an ATL day at either edge can be partial (see DECISIONS.md).
CREATE VIEW app_read.day_range AS
SELECT min(flight_date) AS first_day, max(flight_date) AS last_day FROM ontology.flight;

-- A flight touching ATL belongs to the ATL local day of its scheduled ATL event.
CREATE VIEW app_read.atl_flight AS
SELECT f.*, e.direction, e.atl_event_utc,
       (e.atl_event_utc AT TIME ZONE atl.timezone)::date AS atl_day,
       extract(hour FROM e.atl_event_utc AT TIME ZONE atl.timezone)::int AS atl_hour,
       CASE WHEN f.cancelled THEN 'cancelled'
            WHEN f.diverted THEN 'diverted'
            WHEN CASE e.direction WHEN 'dep' THEN f.dep_delay_min ELSE f.arr_delay_min END >= 15 THEN 'delayed'
            ELSE 'on_time' END AS status,
       (SELECT jsonb_object_agg(d.cause, d.minutes) FROM ontology.delay d WHERE d.flight_id = f.flight_id) AS delays,
       m.observed_at AS metar_observed_at, m.staleness_min AS metar_staleness_min,
       m.raw_text AS metar_raw_text, m.adverse AS metar_adverse
FROM ontology.flight f
JOIN ontology.airport atl ON atl.iata_code = 'ATL' AND atl.airport_id IN (f.origin_airport_id, f.dest_airport_id)
CROSS JOIN LATERAL (
    SELECT CASE WHEN f.origin_airport_id = atl.airport_id THEN 'dep' ELSE 'arr' END AS direction,
           CASE WHEN f.origin_airport_id = atl.airport_id THEN f.sched_dep_utc ELSE f.sched_arr_utc END AS atl_event_utc
) e
LEFT JOIN LATERAL (
    -- the METAR at the actual ATL event when there was one, else at the scheduled one
    SELECT fw.observed_at, fw.staleness_min, w.raw_text, ontology.is_adverse(w) AS adverse
    FROM ontology.flight_weather fw
    JOIN ontology.weather_observation w USING (airport_id, observed_at)
    WHERE fw.flight_id = f.flight_id AND fw.airport_id = atl.airport_id
      AND fw.event = CASE e.direction WHEN 'dep' THEN 'departure' ELSE 'arrival' END
    ORDER BY fw.basis = 'actual' DESC
    LIMIT 1
) m ON true;

CREATE VIEW app_read.hub_day_hourly AS
SELECT atl_day, atl_hour, direction,
       count(*) AS scheduled,
       count(*) FILTER (WHERE status <> 'cancelled') AS operated,
       count(*) FILTER (WHERE status = 'on_time') AS on_time,
       count(*) FILTER (WHERE status = 'delayed') AS delayed,
       count(*) FILTER (WHERE status = 'diverted') AS diverted,
       count(*) FILTER (WHERE status = 'cancelled') AS cancelled
FROM app_read.atl_flight
GROUP BY 1, 2, 3;

CREATE VIEW app_read.hub_day_weather AS
SELECT (w.observed_at AT TIME ZONE a.timezone)::date AS atl_day,
       extract(hour FROM w.observed_at AT TIME ZONE a.timezone)::int AS atl_hour,
       w.observed_at, ontology.is_adverse(w) AS adverse,
       w.wind_dir_deg, w.wind_kt, w.gust_kt, w.visibility_sm, w.ceiling_ft, w.weather, w.raw_text
FROM ontology.weather_observation w
JOIN ontology.airport a USING (airport_id)
WHERE a.iata_code = 'ATL';

CREATE VIEW app_read.hub_day_flights AS
SELECT f.atl_day, f.atl_hour, f.direction, f.status, f.flight_id, c.code AS carrier, f.flight_number,
       o.iata_code AS other_station, l.iata_code AS landed_station, f.tail_number,
       f.sched_dep_utc, f.sched_arr_utc, f.actual_dep_utc, f.actual_arr_utc,
       f.dep_delay_min, f.arr_delay_min, f.cancellation_code, f.delays,
       f.metar_observed_at, f.metar_staleness_min, f.metar_raw_text, f.metar_adverse,
       coalesce(f.metar_staleness_min > 90, true) AS metar_stale,  -- no METAR at all counts as stale
       f.block_mismatch,
       f.aircraft_id IS NULL AS aircraft_unresolved,
       coalesce(f.aircraft_link_confidence = 'medium', false) AS aircraft_medium_confidence,
       coalesce(NOT r.connects, false) AS rotation_break
FROM app_read.atl_flight f
JOIN ontology.carrier c ON c.carrier_id = f.carrier_id
JOIN ontology.airport o ON o.airport_id = CASE f.direction WHEN 'dep' THEN f.dest_airport_id ELSE f.origin_airport_id END
LEFT JOIN ontology.airport l ON l.airport_id = f.landed_airport_id
LEFT JOIN ontology.rotation_leg r ON r.flight_id = f.flight_id;

CREATE VIEW app_read.hub_day_caveats AS
SELECT atl_day,
       count(*) FILTER (WHERE metar_stale) AS metar_stale,
       count(*) FILTER (WHERE block_mismatch) AS block_mismatch,
       count(*) FILTER (WHERE aircraft_unresolved) AS aircraft_unresolved,
       count(*) FILTER (WHERE aircraft_medium_confidence) AS aircraft_medium_confidence,
       count(*) FILTER (WHERE rotation_break) AS rotation_break
FROM app_read.hub_day_flights
GROUP BY 1;

-- Every flown leg of a tail that touched ATL, plus its cancelled flights, which never join a rotation.
CREATE VIEW app_read.tail_legs AS
SELECT f.tail_number, r.leg_seq, f.flight_id,
       (f.sched_dep_utc AT TIME ZONE atl.timezone)::date AS leg_day,
       c.code AS carrier, f.flight_number,
       o.iata_code AS origin, o.timezone AS origin_tz, d.iata_code AS dest, d.timezone AS dest_tz,
       l.iata_code AS landed,
       f.sched_dep_utc, f.sched_arr_utc, f.actual_dep_utc, f.actual_arr_utc,
       f.cancelled, f.cancellation_code, f.diverted, f.dep_delay_min, f.arr_delay_min,
       (SELECT jsonb_object_agg(x.cause, x.minutes) FROM ontology.delay x WHERE x.flight_id = f.flight_id) AS delays,
       r.connects, r.gap_minutes, r.break_cause, app_read.break_label(r.break_cause) AS break_label,
       pl.iata_code AS prev_station,
       a.metar_observed_at, a.metar_staleness_min, a.metar_raw_text, a.metar_adverse
FROM ontology.flight f
JOIN ontology.airport atl ON atl.iata_code = 'ATL'
JOIN ontology.carrier c ON c.carrier_id = f.carrier_id
JOIN ontology.airport o ON o.airport_id = f.origin_airport_id
JOIN ontology.airport d ON d.airport_id = f.dest_airport_id
LEFT JOIN ontology.airport l ON l.airport_id = f.landed_airport_id
LEFT JOIN ontology.rotation_leg r ON r.flight_id = f.flight_id
LEFT JOIN ontology.flight p ON p.flight_id = r.prev_flight_id
LEFT JOIN ontology.airport pl ON pl.airport_id = p.landed_airport_id
LEFT JOIN app_read.atl_flight a ON a.flight_id = f.flight_id
WHERE f.tail_number IN (SELECT tail_number FROM ontology.rotation_leg WHERE touched_atl)
  AND (r.flight_id IS NOT NULL OR f.cancelled);

-- shortcut: a tail unresolved for two reasons on different dates repeats its unresolved flights under each; fix if the tail header ever shows counts.
CREATE VIEW app_read.tail_aircraft AS
SELECT f.tail_number, a.aircraft_id, a.manufacturer, a.model,
       f.aircraft_link_method AS method, f.aircraft_link_confidence AS confidence,
       u.reason AS unresolved_reason, count(*) AS flights
FROM ontology.flight f
LEFT JOIN ontology.aircraft a ON a.aircraft_id = f.aircraft_id
LEFT JOIN dq.unresolved_link u ON u.entity = 'tail' AND u.key = f.tail_number AND f.aircraft_id IS NULL
WHERE f.tail_number IN (SELECT tail_number FROM ontology.rotation_leg WHERE touched_atl)
GROUP BY 1, 2, 3, 4, 5, 6, 7;

-- The app's login. Views run with their owner's rights, so SELECT on app_read is all it needs.
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'flightops_app') THEN
        CREATE ROLE flightops_app LOGIN;
    END IF;
END $$;
GRANT USAGE ON SCHEMA app_read TO flightops_app;
GRANT SELECT ON ALL TABLES IN SCHEMA app_read TO flightops_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA app_read GRANT SELECT ON TABLES TO flightops_app;
```

- [ ] **Step 5: Run the tests to make sure they pass**

Run: `uv run --env-file ../.env pytest tests/test_app_read.py -v`
Expected: 23 passed.

If a test fails on a fixture value rather than view logic, check the hand-worked times in the table above against `ontology.flight` in `flightops_test` before changing the view. For example, check whether BTS stores the diverted flight's `landed_airport_id` as CLE. Fix whichever is wrong and note it in the commit message.

- [ ] **Step 6: Run the whole suite**

Run: `uv run --env-file ../.env pytest`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add ../db/migrations/012_app_read.sql tests/test_app_read.py tests/fixtures/bts_app_read.csv
git commit -m "feat: add app_read views and a read-only app role"
```

---

### Task 3: apply to the July 2024 database, measure, and record the decisions

**Files:**
- Modify: `docs/phase-2-plan.md` (add a `## Notes` section)
- Modify: `DECISIONS.md` (append four entries)
- Modify: `CLAUDE.md` (the Status section)

- [ ] **Step 1: Apply the migration**

Run: `uv run --env-file ../.env python -m flightops migrate`
Expected: `applied: ['012_app_read.sql']`

- [ ] **Step 2: Check the views against direct counts**

```bash
psql -h localhost flightops -c "
select (select sum(cancelled) from app_read.hub_day_hourly where atl_day = '2024-07-19') as cancelled_atl_day,
       (select sum(scheduled) from app_read.hub_day_hourly where atl_day = '2024-07-19') as flights_atl_day,
       (select count(*) from app_read.atl_flight where flight_date = '2024-07-19' and cancelled) as cancelled_flight_date,
       (select count(*) from app_read.hub_day_flights where atl_day = '2024-07-19') as table_rows,
       (select first_day || ' to ' || last_day from app_read.day_range) as range"
```

Expected, from a direct query on 2026-11-22: `cancelled_atl_day` 899, `flights_atl_day` 2078, `cancelled_flight_date` 895 (the report's number), `table_rows` 2078, and `range` 2024-07-01 to 2024-07-31. If any number differs, stop and investigate before continuing.

- [ ] **Step 3: Check the app role from outside the test suite**

```bash
psql -h localhost -U flightops_app flightops -c "select count(*) from app_read.hub_day_flights where atl_day = '2024-07-19'"
psql -h localhost -U flightops_app flightops -c "select count(*) from ontology.flight"
```

Expected: the first prints 2078. The second fails with `permission denied for schema ontology`. If the login itself is refused, report the `pg_hba.conf` error to the user rather than changing auth settings.

- [ ] **Step 4: Measure the queries the app will run**

```bash
for q in \
  "select * from app_read.hub_day_flights where atl_day = '2024-07-19'" \
  "select * from app_read.hub_day_hourly where atl_day = '2024-07-19'" \
  "select * from app_read.hub_day_caveats where atl_day = '2024-07-19'" \
  "select * from app_read.hub_day_weather where atl_day = '2024-07-19'" \
  "select * from app_read.tail_legs where tail_number = 'N102DN'" \
  "select * from app_read.tail_aircraft where tail_number = 'N102DN'"; do
  echo "$q"; psql -h localhost flightops -c "explain (analyze, timing off, summary on) $q" | grep 'Execution Time'
done
```

Record each execution time. If any is over 500 ms, stop and bring the numbers to the user with the `EXPLAIN` plan. Don't add indexes to `ontology` without agreement.

- [ ] **Step 5: Add notes to the phase plan**

Append to `docs/phase-2-plan.md`, filling the times in from Step 4:

```markdown
## Notes

- **July 19 cancellations:** 899 by ATL day against 895 by `FlightDate` in the phase 1 report. The difference is flights whose scheduled ATL event falls on a different local date from their scheduled departure date, mostly late inbound flights from the west.
- **Edge days:** the app offers July 1-31, the BTS `flight_date` range. July 1 lacks inbound flights that departed on June 30, and the 40 flights whose ATL day is August 1 are not offered.
- **Query times on July 19 (ms):** hub flights …, hourly …, caveats …, weather …, N102DN legs …, N102DN aircraft ….
- **Changes from the design during step 1:** the adverse rule lives in `ontology`, not `app_read`. Migrations are `011_is_adverse.sql` and `012_app_read.sql`. Added `day_range`, `tail_aircraft` and `break_label`. The hourly view counts flights by status rather than summing delay minutes by cause, since the bars use status. A flight with no METAR counts as stale.
```

- [ ] **Step 6: Append the decisions**

Append to `DECISIONS.md`:

```markdown
## 2026-11-22: Serve the app from SQL views in `app_read`
- **Chose:** views and small functions in an `app_read` schema, owned by pipelines' migrations and tested with pytest. Laravel runs plain queries against them.
- **Gave up:** Eloquent models and Laravel-only tests, so each app feature spans SQL and PHP, and a view change needs a migration.
- **Why:** the ATL day, adverse weather and break labels are data rules. Keeping them beside the pipelines means one definition, tested against the same fixtures as the data.
- **Revisit if:** a page needs per-request logic that SQL expresses badly, or a view grows slow enough to need materializing.

## 2026-11-22: Assign each ATL flight to the ATL local day of its scheduled ATL event
- **Chose:** departures by scheduled departure and arrivals by scheduled arrival, both in Atlanta local time. Cancelled flights keep their day. The app offers the BTS `flight_date` range, July 1-31.
- **Gave up:** agreement with BTS `FlightDate`. July 19 shows 899 cancellations, not the report's 895, and July 1 is missing inbound flights that departed June 30.
- **Why:** a hub controller's day runs midnight to midnight local time, and an LAX red-eye landing at 06:30 belongs to the morning it lands.
- **Revisit if:** a second month is loaded. Then the edge days fill in and the range can follow ATL days.

## 2026-11-22: Flag a METAR older than 90 minutes as stale
- **Chose:** a flight whose ATL METAR is more than 90 minutes old at its ATL event, or which has none, gets a stale-weather caveat. The METAR is the one at the actual event when there was one, otherwise the scheduled one.
- **Gave up:** a threshold drawn from data, so the number is open to challenge.
- **Why:** METARs come about hourly, so one hour old is normal. Past 90 minutes a routine report has been missed, and the weather shown may not be what the flight met.
- **Revisit if:** the caveat fires on most flights on a normal day, which would mean the observation feed has gaps worth fixing instead.

## 2026-11-22: Enforce the app's read-only access with a database role
- **Chose:** a `flightops_app` login with `SELECT` on `app_read` only. The views read `ontology` and `dq` with their owner's rights.
- **Gave up:** connecting the app as the owner, which is simpler. The app also can't query `ontology` directly, even for a quick look.
- **Why:** "the app never writes" becomes a guarantee the database checks, not a convention, and the app can only see what `app_read` chooses to show.
- **Revisit if:** phase 5 adds write-backs. Grant that role rights on `app` only.
```

- [ ] **Step 7: Update the Status section of `CLAUDE.md`**

Replace the Current phase, Next action and Built so far bullets with:

```markdown
- **Current phase:** 2, in progress. Steps 1-2 are done: the `app_read` views and the shared `ontology.is_adverse`.
- **Next action:** plan steps 3-5 of `docs/phase-2-plan.md` (Laravel skeleton, HubDay, TailDay).
- **Built so far:** phase 1 in full (see `docs/phase-1-plan.md`), plus `app_read` views read by the `flightops_app` role. The local `flightops` database holds the July 2024 ontology, and measured results are in `docs/data-sources.md` and the notes in `docs/phase-2-plan.md`. OpenSky ATL arrivals and departures are collected by hand with `collect`, which fetches the last 7 settled days it doesn't hold. Use `--from` and `--to` for older gaps.
```

- [ ] **Step 8: Run the whole suite one last time and commit**

```bash
uv run --env-file ../.env pytest
git add ../docs/phase-2-plan.md ../DECISIONS.md ../CLAUDE.md
git commit -m "docs: record phase 2 step 1-2 measurements and decisions"
```

Expected: all tests pass before the commit.
