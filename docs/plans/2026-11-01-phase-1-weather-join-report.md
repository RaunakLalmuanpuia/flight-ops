# Phase 1, Steps 6-7: Weather Join and Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans and superpowers:test-driven-development. Use superpowers:verification-before-completion before calling a step done. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every ATL departure and arrival carries the latest METAR at or before it, and one command produces a data-quality report that can be defended line by line, including the July 19-23 walkthrough.

**Architecture:** The weather join is one more set-based `.sql` file run after rotations, storing a link to the observation rather than copying it. The report is a small Python module holding a list of headed SQL queries, rendered to `docs/phase-1-report.md` with each query printed under its table, so every number traces to its SQL.

**Tech Stack:** Python 3.12 or newer, `psycopg` 3, `pytest`, local Postgres 18.

## Global Constraints

- Pipelines are the only writers to `raw`, `staging`, `ontology` and `dq`. Schema changes go through `db/migrations/`.
- `ontology` stores times in UTC. METAR joins use `observed_at`, never a later observation.
- Unresolved matches are recorded with a reason. Never guess, and never drop them silently.
- No PostGIS, orchestration, streaming or Docker.
- Run `uv` commands from `pipelines/`, and `git` commands from the repo root.

## Findings from prototyping on real data, 2026-11-01

Task 3 checks the build against these. They come from read-only queries on the built July 2024 `ontology`.

| Finding | Evidence | Design consequence |
|---|---|---|
| Hourly METARs cover every ATL event | 116,716 events, all with a METAR at or before them, at most 59 minutes old | The join has no real unresolved cases, but still records them, and a stale count stays reported |
| Scheduled and actual times answer different questions | 1,750 scheduled departures and 1,822 scheduled arrivals have no actual time, all on cancelled flights | Store both bases, so a cancelled flight still has weather |
| No diversion stopped at or short of ATL this month | 113 flights stopped short nationally, none involving ATL. All 179 diversions bound for ATL reached it | Not a bug. Fixtures cover both cases, because the real month doesn't |
| The cancellation spike isn't weather | July 19-23 touching ATL: 3,208 cancelled. Code A (carrier) 3,098, C (NAS) 80, B (weather) 30 | The report's main finding |
| July 19 weather was benign | 0 of 25 METARs adverse on July 19 with 895 cancellations. 15 of 38 adverse on July 24 with 27 | Shown as a daily table |
| Weather delays line up with observed weather, more at departure | Adverse METAR in the delay window: ATL departures 81.5% with a weather delay and 24.9% without. ATL arrivals 40.5% and 28.5% | Satisfies the phase cross-check. The arrival gap is weaker because BTS doesn't say where the weather was, so it may be at the origin |

## Decisions for review

1. **Both scheduled and actual weather.** Step 6 says "each departure and arrival". This stores one row per event and basis, so 116,716 rows, not about 58,000.
2. **"Adverse" is our definition, not a standard:** thunderstorm, heavy rain, fog, snow or freezing precipitation in the weather group, ceiling under 1,000 ft, visibility under 3 SM, or gust of 30 kt or more. It flags 199 of 953 July METARs (20.9%). It lives only in the report, not in `ontology`.
3. **No thresholds on reported checks yet.** The phase plan says to set them after the first run. One month containing the outage isn't a baseline, so this plan defers them until a second month is loaded, and records why.
4. **Report numbers are generated, and the findings prose is written by hand.** Tables can't drift from the data. The findings can, so Task 3 checks them, and they'd need rewriting for another month.

## Not built here

- Weather at airports other than ATL: only `KATL` was downloaded.
- Thresholds on reported checks, per decision 3.
- The `README.md` shown in the phase plan's folder structure. It isn't in the phase's "done when", and it reads better once phase 2 has something to show.

## File Structure

| Path | Responsibility |
|---|---|
| `db/migrations/009_flight_weather.sql` | `ontology.flight_weather` |
| `pipelines/flightops/resolve/flight_weather.sql` | Latest METAR at or before each ATL event |
| `pipelines/flightops/report.py` | Report sections and markdown rendering |
| `pipelines/tests/fixtures/bts_weather.csv`, `metar_join.csv` | Awkward join cases |
| `pipelines/tests/test_flight_weather.py`, `test_report.py` | Tests |
| `docs/phase-1-report.md` | Generated report |

---

### Task 1: Attach the latest METAR to each ATL event

**Files:**
- Create: `db/migrations/009_flight_weather.sql`, `pipelines/flightops/resolve/flight_weather.sql`, `pipelines/tests/fixtures/bts_weather.csv`, `pipelines/tests/fixtures/metar_join.csv`, `pipelines/tests/test_flight_weather.py`
- Modify: `pipelines/flightops/pipeline.py`, `pipelines/flightops/resolve/ontology.sql`, `pipelines/flightops/dq/checks.py`, `DECISIONS.md`, `CLAUDE.md`

**Interfaces:**
- Consumes: `load_fixture`, `pipeline.build`, `ontology.flight`, `ontology.weather_observation`.
- Produces: `ontology.flight_weather(flight_id, event, basis, event_at, airport_id, observed_at, staleness_min)`, with `event` in `departure|arrival` and `basis` in `scheduled|actual`. Unresolved events go to `dq.unresolved_link` with entity `atl_weather`.

- [ ] **Step 1: Create the fixtures**

`pipelines/tests/fixtures/metar_join.csv` has a `MADISHF` row at 12:55 that must never be chosen:

```csv
station,valid,metar
ATL,2024-07-19 11:52,KATL 191152Z 19007KT 10SM CLR 27/22 A3000
ATL,2024-07-19 12:30,KATL 191230Z 19007KT 5SM TSRA BKN030CB 25/22 A3000
ATL,2024-07-19 12:52,KATL 191252Z 19007KT 10SM FEW040 26/22 A3000
ATL,2024-07-19 12:55,KATL 191255Z AUTO 19007KT 10SM CLR 26/22 A3000 RMK MADISHF
ATL,2024-07-19 14:52,KATL 191452Z 19007KT 10SM FEW040 28/22 A3000
```

`pipelines/tests/fixtures/bts_weather.csv` covers, by flight number: (1) a late ATL departure, (2) a late ATL arrival, (3) a cancelled ATL departure, (4) a flight bound for ATL that stopped short at `IAD`, (5) a flight bound for `LGA` that stopped short at ATL, (6) an ATL departure before the first METAR, (7) a flight that never touches ATL.

```csv
flightdate,reporting_airline,tail_number,flight_number_reporting_airline,origin,dest,crsdeptime,deptime,depdelay,crsarrtime,arrtime,crselapsedtime,actualelapsedtime,cancelled,diverted,divreacheddest,div1airport,div1wheelson
2024-07-19,DL,N1W,1,ATL,ORD,0800,0830,30.00,0855,0925,115.00,115.00,0.00,0.00,,,
2024-07-19,DL,N2W,2,ORD,ATL,0800,0830,30.00,1100,1130,120.00,120.00,0.00,0.00,,,
2024-07-19,DL,N3W,3,ATL,ORD,0900,,,0955,,115.00,,1.00,0.00,,,
2024-07-19,DL,N4W,4,ORD,ATL,1000,1000,0.00,1300,,120.00,,0.00,1.00,0.00,IAD,1230
2024-07-19,DL,N5W,5,ORD,LGA,1000,1000,0.00,1300,,120.00,,0.00,1.00,0.00,ATL,1400
2024-07-19,DL,N6W,6,ATL,ORD,0500,0500,0.00,0555,0555,115.00,115.00,0.00,0.00,,,
2024-07-19,DL,N7W,7,LAX,ORD,0800,0800,0.00,1400,1400,240.00,240.00,0.00,0.00,,,
```

- [ ] **Step 2: Write the failing tests**

`pipelines/tests/test_flight_weather.py`:

```python
from datetime import datetime, timezone

import pytest

from flightops import pipeline


def utc(hour, minute):
    return datetime(2024, 7, 19, hour, minute, tzinfo=timezone.utc)


@pytest.fixture
def conn_built(conn, load_fixture):
    load_fixture("ourairports_airports", "airports.csv")
    load_fixture("bts_ontime", "bts_weather.csv")
    load_fixture("iem_metar", "metar_join.csv")
    pipeline.build(conn)
    return conn


@pytest.fixture
def joined(conn_built):
    rows = conn_built.execute(
        "select f.flight_number, w.event, w.basis, w.observed_at, w.staleness_min "
        "from ontology.flight_weather w join ontology.flight f using (flight_id)"
    ).fetchall()
    return {r[:3]: r[3:] for r in rows}


def test_scheduled_departure_uses_the_latest_earlier_metar(joined):
    assert joined["1", "departure", "scheduled"] == (utc(11, 52), 8)


def test_metar_at_the_exact_minute_counts(joined):
    assert joined["1", "departure", "actual"] == (utc(12, 30), 0)


def test_arrival_is_joined_on_both_bases(joined):
    assert joined["2", "arrival", "scheduled"] == (utc(14, 52), 8)
    assert joined["2", "arrival", "actual"] == (utc(14, 52), 38)


def test_madis_record_is_never_chosen_and_cancelled_flight_has_scheduled_only(joined):
    assert joined["3", "departure", "scheduled"] == (utc(12, 52), 8)
    assert ("3", "departure", "actual") not in joined


def test_flight_that_stopped_short_of_atl_has_no_actual_arrival_here(joined):
    assert joined["4", "arrival", "scheduled"] == (utc(14, 52), 128)
    assert ("4", "arrival", "actual") not in joined


def test_flight_that_stopped_short_at_atl_has_an_actual_arrival_here(joined):
    assert joined["5", "arrival", "actual"] == (utc(14, 52), 188)
    assert ("5", "arrival", "scheduled") not in joined


def test_flight_away_from_atl_has_no_rows(joined):
    assert not [k for k in joined if k[0] == "7"]


def test_event_before_the_first_metar_is_recorded_not_dropped(conn_built, joined):
    assert not [k for k in joined if k[0] == "6"]
    rows = conn_built.execute(
        "select reason, count(*), sum(flights) from dq.unresolved_link where entity = 'atl_weather' group by 1"
    ).fetchall()
    assert rows == [("no_metar_at_or_before", 2, 2)]


def test_stale_observations_are_reported_not_hidden(conn_built):
    value = conn_built.execute(
        "select value from dq.check_result where name = 'atl_weather_stale_over_90' order by id desc limit 1"
    ).fetchone()[0]
    assert value == 2
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run --env-file ../.env pytest tests/test_flight_weather.py -q`
Expected: failures, because `ontology.flight_weather` does not exist.

- [ ] **Step 4: Implement**

`db/migrations/009_flight_weather.sql`:

```sql
CREATE TABLE ontology.flight_weather (
    flight_id     bigint NOT NULL REFERENCES ontology.flight,
    event         text NOT NULL CHECK (event IN ('departure', 'arrival')),
    basis         text NOT NULL CHECK (basis IN ('scheduled', 'actual')),
    event_at      timestamptz NOT NULL,
    airport_id    bigint NOT NULL,
    observed_at   timestamptz NOT NULL,
    staleness_min integer NOT NULL CHECK (staleness_min >= 0),
    PRIMARY KEY (flight_id, event, basis),
    FOREIGN KEY (airport_id, observed_at) REFERENCES ontology.weather_observation (airport_id, observed_at)
);
```

`pipelines/flightops/resolve/flight_weather.sql`:

```sql
TRUNCATE ontology.flight_weather;

WITH atl AS (SELECT airport_id FROM ontology.airport WHERE iata_code = 'ATL'),
events AS (
    SELECT flight_id, 'departure' AS event, 'scheduled' AS basis, sched_dep_utc AS event_at FROM ontology.flight WHERE origin_airport_id = (TABLE atl)
    UNION ALL
    SELECT flight_id, 'departure', 'actual', actual_dep_utc FROM ontology.flight WHERE origin_airport_id = (TABLE atl) AND actual_dep_utc IS NOT NULL
    UNION ALL
    SELECT flight_id, 'arrival', 'scheduled', sched_arr_utc FROM ontology.flight WHERE dest_airport_id = (TABLE atl) AND sched_arr_utc IS NOT NULL
    UNION ALL
    -- landed, not dest: a flight bound elsewhere that stopped short at ATL did arrive here
    SELECT flight_id, 'arrival', 'actual', actual_arr_utc FROM ontology.flight WHERE landed_airport_id = (TABLE atl) AND actual_arr_utc IS NOT NULL
),
matched AS (
    SELECT e.*, m.observed_at
    FROM events e
    LEFT JOIN LATERAL (
        SELECT w.observed_at FROM ontology.weather_observation w
        WHERE w.airport_id = (TABLE atl) AND w.observed_at <= e.event_at
        ORDER BY w.observed_at DESC LIMIT 1
    ) m ON true
),
linked AS (
    INSERT INTO ontology.flight_weather
    SELECT flight_id, event, basis, event_at, (TABLE atl), observed_at,
           (extract(epoch FROM event_at - observed_at) / 60)::int
    FROM matched WHERE observed_at IS NOT NULL
    ORDER BY flight_id, event, basis
)
INSERT INTO dq.unresolved_link
SELECT 'atl_weather', flight_id || '|' || event || '|' || basis, 'no_metar_at_or_before', 1
FROM matched WHERE observed_at IS NULL;
```

In `pipelines/flightops/resolve/ontology.sql`, add `ontology.flight_weather` to the `TRUNCATE` list at the top, because it references `ontology.flight`.

In `pipelines/flightops/pipeline.py`, add `run_sql(conn, "resolve/flight_weather.sql")` after the rotations line in `build`.

In `pipelines/flightops/dq/checks.py`, append to `REPORTED`:

```python
    ("atl_weather_events", "SELECT count(*) FROM ontology.flight_weather"),
    ("atl_weather_unresolved", "SELECT count(*) FROM dq.unresolved_link WHERE entity = 'atl_weather'"),
    ("atl_weather_stale_over_90", "SELECT count(*) FROM ontology.flight_weather WHERE staleness_min > 90"),
    ("atl_weather_max_staleness_min", "SELECT coalesce(max(staleness_min), 0) FROM ontology.flight_weather"),
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run --env-file ../.env pytest -q`
Expected: all passed.

- [ ] **Step 6: Record the tradeoff and commit**

Append to `DECISIONS.md`:

```markdown
## 2026-11-01: Join weather to both scheduled and actual ATL times
- **Chose:** one row per flight, event and basis, each linking to the latest METAR at or before that time, with its age in minutes.
- **Gave up:** a single weather row per flight, so readers must pick a basis.
- **Why:** a cancelled flight has no actual time but still needs its weather, and a delayed flight met different weather from what its schedule implied.
- **Revisit if:** phase 2 only ever reads one basis.
```

Update Status in `CLAUDE.md` so that step 6 is done and the next action is step 7 of this plan.

```bash
git add db pipelines DECISIONS.md CLAUDE.md
git commit -m "feat: attach the latest METAR to each ATL event"
```

---

### Task 2: Generate the report

**Files:**
- Create: `pipelines/flightops/report.py`, `pipelines/tests/test_report.py`, `docs/phase-1-report.md` (generated in Task 3)
- Modify: `pipelines/flightops/__main__.py`

**Interfaces:**
- Consumes: `ontology.*`, `dq.check_result`, `dq.ingestion_run`, `dq.unresolved_link`.
- Produces: `report.render(conn) -> str`, CLI command `report`. `all` also writes the report.

- [ ] **Step 1: Write the failing tests**

`pipelines/tests/test_report.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --env-file ../.env pytest tests/test_report.py -q`
Expected: collection error, `flightops.report` does not exist.

- [ ] **Step 3: Implement**

`pipelines/flightops/report.py`:

```python
HEADER = """# Phase 1 data-quality report: July 2024

Generated by `python -m flightops report`. Don't edit this file. Tables come from the database, and the SQL behind each one sits under it. Times are UTC.
"""

# Written by hand from the tables below. Rewrite them if the data changes.
FINDINGS = """## Findings

- **The July 19-23 cancellations at ATL were not caused by ATL weather.** 3,208 flights touching ATL were cancelled: 3,098 with code A (carrier), 80 with code C (NAS) and 30 with code B (weather). 2,864 were Delta and 207 were Endeavor (`9E`). This is the CrowdStrike outage period, which BTS doesn't name. The data shows the pattern, not the cause.
- **Weather was mild when the spike began.** On July 19, 0 of 25 METARs were adverse, and that day had 895 cancellations. July 24 had 15 adverse METARs of 38 and 27 cancellations.
- **Reported weather delays line up with observed weather.** An adverse METAR fell in the delay window for 81.5% of ATL departures with a weather delay, against 24.9% of other delayed departures. For arrivals it was 40.5% against 28.5%. The gap is smaller there because BTS doesn't say where the weather was, and it may have been at the origin.
- **Rotations hold together.** 98.70% of consecutive legs connect nationally, and 98.84% on tails that touched ATL. The rest carry a label for their likely cause.
- **Tail matching is good but not perfect.** 98.8% of flights with a tail link to an airframe. 7,683 stay unresolved with a reason, 317 of them on ATL flights.

## Limits

- **The registry is today's, not July 2024's.** 34,653 flights link only because the registry names one airframe for the tail, and these are marked medium confidence.
- **Break causes are likely, not known.** BTS doesn't identify non-reporting or international flying.
- **"Adverse" is this project's definition:** thunderstorm, heavy rain, fog, snow or freezing precipitation, ceiling under 1,000 ft, visibility under 3 SM, or gust of 30 kt or more.
- **Weather covers ATL only,** so it can't explain a delay caused elsewhere.
- **One month is not a baseline,** especially one containing this outage, so reported checks have no thresholds yet.
"""

ADVERSE = r"""(array_to_string(w.weather, ' ') ~ '(TS|\+RA|FG|SN|FZ)'
       OR coalesce(w.ceiling_ft, 99999) < 1000 OR w.visibility_sm < 3 OR coalesce(w.gust_kt, 0) >= 30)"""

ATL_FLIGHTS = """SELECT f.* FROM ontology.flight f JOIN ontology.airport a ON a.iata_code = 'ATL'
    WHERE a.airport_id IN (f.origin_airport_id, f.dest_airport_id)"""

CROSS_CHECK = """
SELECT '{label}' AS flights, d.flight_id IS NOT NULL AS weather_delay_reported, count(*) AS delayed_flights,
       count(*) FILTER (WHERE x.adverse) AS adverse_in_window,
       round(100.0 * count(*) FILTER (WHERE x.adverse) / count(*), 1) AS pct
FROM ontology.flight f
JOIN ontology.airport a ON a.iata_code = 'ATL' AND a.airport_id = f.{column}
LEFT JOIN ontology.delay d ON d.flight_id = f.flight_id AND d.cause = 'weather'
CROSS JOIN LATERAL (
    SELECT coalesce(bool_or({adverse}), false) AS adverse
    FROM ontology.weather_observation w
    WHERE w.airport_id = a.airport_id AND w.observed_at BETWEEN f.{start} - interval '1 hour' AND f.{end}
) x
WHERE NOT f.cancelled AND f.arr_delay_min >= 15
GROUP BY 2
"""

SECTIONS = [
    (
        "Raw files",
        "Rows loaded and rows quarantined per delivered file. Raw rows plus quarantined rows equal the file.",
        "SELECT table_name, row_count, quarantined_count, left(source_sha256, 12) AS sha256 FROM dq.ingestion_run ORDER BY table_name",
    ),
    (
        "Blocking checks",
        "Any failure here stops promotion to `ontology`. These are the results of the latest run.",
        "SELECT name, value, passed FROM (SELECT DISTINCT ON (name) id, name, value, passed, blocking "
        "FROM dq.check_result ORDER BY name, id DESC) x WHERE blocking ORDER BY id",
    ),
    (
        "Reported checks",
        "These don't block, and have no thresholds until there is a second month to compare with.",
        "SELECT name, value FROM (SELECT DISTINCT ON (name) id, name, value, blocking "
        "FROM dq.check_result ORDER BY name, id DESC) x WHERE NOT blocking ORDER BY id",
    ),
    (
        "Tail matching",
        "Flights per tail-to-airframe rule. Flights with no tail are all cancelled.",
        """SELECT coalesce(k.method, k.unresolved_reason, 'no tail') AS outcome, k.confidence, count(*) AS flights,
       count(*) FILTER (WHERE f.origin = 'ATL' OR f.dest = 'ATL') AS touching_atl
FROM staging.flight f
LEFT JOIN staging.aircraft_link k ON k.tail_number = f.tail_number AND k.flight_date = f.flight_date
GROUP BY 1, 2 ORDER BY 3 DESC""",
    ),
    (
        "Rotation breaks",
        "Consecutive legs, whether or not the next origin equals the previous landing station.",
        """SELECT coalesce(break_cause, 'connects') AS outcome, count(*) AS national,
       count(*) FILTER (WHERE touched_atl) AS tails_touching_atl
FROM ontology.rotation_leg WHERE connects IS NOT NULL
GROUP BY 1 ORDER BY 2 DESC""",
    ),
    (
        "Weather join",
        "Latest ATL METAR at or before each ATL event. Unresolved events are in `dq.unresolved_link`.",
        """SELECT event, basis, count(*) AS events, percentile_cont(0.5) WITHIN GROUP (ORDER BY staleness_min) AS median_age_min,
       max(staleness_min) AS max_age_min
FROM ontology.flight_weather GROUP BY 1, 2 ORDER BY 1, 2""",
    ),
    (
        "ATL by day, July 15-27",
        "Flights touching ATL by scheduled local departure date, against METARs by Atlanta local date. "
        "Codes: A carrier, B weather, C NAS, D security.",
        f"""SELECT f.flight_date, count(*) AS flights, count(*) FILTER (WHERE f.cancelled) AS cancelled,
       count(*) FILTER (WHERE f.cancellation_code = 'A') AS a, count(*) FILTER (WHERE f.cancellation_code = 'B') AS b,
       count(*) FILTER (WHERE f.cancellation_code = 'C') AS c, count(*) FILTER (WHERE f.cancellation_code = 'D') AS d,
       (SELECT count(*) FROM ontology.weather_observation w
        WHERE (w.observed_at AT TIME ZONE 'America/New_York')::date = f.flight_date) AS metars,
       (SELECT count(*) FROM ontology.weather_observation w
        WHERE (w.observed_at AT TIME ZONE 'America/New_York')::date = f.flight_date AND {ADVERSE}) AS adverse_metars
FROM ({ATL_FLIGHTS}) f
WHERE f.flight_date BETWEEN '2024-07-15' AND '2024-07-27'
GROUP BY 1 ORDER BY 1""",
    ),
    (
        "Carriers, July 19-23",
        "Flights touching ATL, the eight carriers with the most cancellations.",
        f"""SELECT c.code, count(*) AS flights, count(*) FILTER (WHERE f.cancelled) AS cancelled,
       round(100.0 * count(*) FILTER (WHERE f.cancelled) / count(*), 1) AS pct
FROM ({ATL_FLIGHTS}) f JOIN ontology.carrier c USING (carrier_id)
WHERE f.flight_date BETWEEN '2024-07-19' AND '2024-07-23'
GROUP BY 1 ORDER BY 3 DESC, 1 LIMIT 8""",
    ),
    (
        "Weather delays against observed weather",
        "ATL flights with an arrival delay of 15 minutes or more, the only ones where BTS reports causes. "
        "The window runs from an hour before the scheduled time to the actual time.",
        CROSS_CHECK.format(label="departing ATL", column="origin_airport_id", start="sched_dep_utc", end="actual_dep_utc", adverse=ADVERSE)
        + "UNION ALL"
        + CROSS_CHECK.format(label="arriving ATL", column="landed_airport_id", start="sched_arr_utc", end="actual_arr_utc", adverse=ADVERSE)
        + "ORDER BY 1 DESC, 2",
    ),
    (
        "One aircraft, July 18-23",
        "The first Delta `N…DN` tail with a July 19 cancellation. Cancelled legs have no arrival and no rotation position. "
        "Weather shows only for departures from ATL, using the actual time when there is one.",
        """SELECT f.tail_number, f.flight_date, f.flight_number, o.iata_code AS origin, d.iata_code AS dest, l.iata_code AS landed,
       to_char(f.sched_dep_utc AT TIME ZONE 'UTC', 'MM-DD HH24:MI') AS sched_dep,
       to_char(f.actual_dep_utc AT TIME ZONE 'UTC', 'MM-DD HH24:MI') AS actual_dep,
       to_char(f.actual_arr_utc AT TIME ZONE 'UTC', 'MM-DD HH24:MI') AS actual_arr,
       f.cancellation_code AS cxl, r.leg_seq, r.break_cause, ac.model,
       f.aircraft_link_method AS link, array_to_string(w.weather, ' ') AS wx, w.ceiling_ft, w.visibility_sm
FROM ontology.flight f
JOIN ontology.airport o ON o.airport_id = f.origin_airport_id
JOIN ontology.airport d ON d.airport_id = f.dest_airport_id
LEFT JOIN ontology.airport l ON l.airport_id = f.landed_airport_id
LEFT JOIN ontology.rotation_leg r USING (flight_id)
LEFT JOIN ontology.aircraft ac USING (aircraft_id)
LEFT JOIN ontology.flight_weather fw ON fw.flight_id = f.flight_id AND fw.event = 'departure'
    AND fw.basis = CASE WHEN f.actual_dep_utc IS NULL THEN 'scheduled' ELSE 'actual' END
LEFT JOIN ontology.weather_observation w ON w.airport_id = fw.airport_id AND w.observed_at = fw.observed_at
WHERE f.tail_number = (SELECT min(tail_number) FROM ontology.flight
                       WHERE cancelled AND flight_date = '2024-07-19' AND tail_number LIKE 'N%DN')
  AND f.flight_date BETWEEN '2024-07-18' AND '2024-07-23'
ORDER BY f.sched_dep_utc, f.flight_id""",
    ),
]


def _table(cursor) -> str:
    columns = [c.name for c in cursor.description]
    lines = ["| " + " | ".join(columns) + " |", "|" + " --- |" * len(columns)]
    for row in cursor.fetchall():
        lines.append("| " + " | ".join("" if v is None else str(v) for v in row) + " |")
    return "\n".join(lines)


def render(conn) -> str:
    parts = [HEADER, FINDINGS]
    for heading, prose, query in SECTIONS:
        parts.append(
            f"## {heading}\n\n{prose}\n\n{_table(conn.execute(query))}\n\n"
            f"<details><summary>SQL</summary>\n\n```sql\n{query.strip()}\n```\n\n</details>\n"
        )
    return "\n".join(parts)
```

In `pipelines/flightops/__main__.py`, change the import to `from flightops import db, pipeline, report`, add `"report"` to the choices, and add at the end of the `with db.connect() as conn:` block, after the `build` block:

```python
            if command in ("report", "all"):
                path = db.REPO / "docs" / "phase-1-report.md"
                path.write_text(report.render(conn))
                print("wrote", path)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --env-file ../.env pytest -q`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add pipelines
git commit -m "feat: generate the data-quality report from the database"
```

---

### Task 3: Run on real data, prove it reproduces, and close the phase

**Files:**
- Create: `docs/phase-1-report.md` (generated)
- Modify: `docs/data-sources.md`, `docs/phase-1-plan.md`, `docs/roadmap.md` only if scope changed, `DECISIONS.md`, `CLAUDE.md`, and the `FINDINGS` text in `pipelines/flightops/report.py` if any number differs

**Interfaces:**
- Consumes: the CLI.
- Produces: the populated `ontology.flight_weather` and the report.

- [ ] **Step 1: Run the full pipeline**

Run: `uv run --env-file ../.env python -m flightops all`
Expected: blocking checks print `ok`, every value from the previous build is unchanged, and:

| Value | Expected |
|---|---|
| `atl_weather_events` | 116,716 |
| `atl_weather_unresolved` | 0 |
| `atl_weather_stale_over_90` | 0 |
| `atl_weather_max_staleness_min` | 59 |

Use superpowers:systematic-debugging on any failure, and never weaken a check to pass it.

- [ ] **Step 2: Check every number in the findings against the generated tables**

Read `docs/phase-1-report.md`. Each `FINDINGS` number must appear in, or sum directly from, a table:

| Finding | Expected | Table |
|---|---|---|
| Cancelled July 19-23 | 3,208 (A 3,098, B 30, C 80) | ATL by day |
| Delta and `9E` cancellations | 2,864 and 207 | Carriers |
| July 19 | 895 cancelled, 0 of 25 METARs adverse | ATL by day |
| July 24 | 27 cancelled, 15 of 38 METARs adverse | ATL by day |
| Departures | 81.5% and 24.9% | Weather delays |
| Arrivals | 40.5% and 28.5% | Weather delays |
| Rotation continuity | 98.70% and 98.84% | Rotation breaks |
| Tail matching | 98.8%, 7,683, 317 | Tail matching |

If the data disagrees, debug first. Correct the prose only once you know why it differs, and then regenerate.

- [ ] **Step 3: Prove a fresh database reproduces the counts**

This is the phase's "done when". `flightops_fresh` is a throwaway database, separate from `flightops`. `DATABASE_URL` is set inline, and `--env-file` is left out so it can't override it. Set `<url>` to the `DATABASE_URL` from `.env` with its database name changed to `flightops_fresh`.

```bash
HASH="select md5(string_agg(flight_id||'|'||coalesce(aircraft_id::text,'')||'|'||coalesce(actual_arr_utc::text,''), ',' order by flight_id)) from ontology.flight union all select md5(string_agg(flight_id||'|'||tail_number||'|'||leg_seq||'|'||coalesce(break_cause,''), ',' order by flight_id)) from ontology.rotation_leg union all select md5(string_agg(flight_id||'|'||event||'|'||basis||'|'||observed_at::text, ',' order by flight_id, event, basis)) from ontology.flight_weather"
createdb -h localhost flightops_fresh
DATABASE_URL=<url> uv run python -m flightops migrate
DATABASE_URL=<url> uv run python -m flightops load
DATABASE_URL=<url> uv run python -m flightops build
PGTZ=UTC psql -h localhost flightops -Atc "$HASH"
PGTZ=UTC psql -h localhost flightops_fresh -Atc "$HASH"
dropdb -h localhost flightops_fresh
```

Expected: the two `PGTZ=UTC` runs print the same three hashes. Using `migrate`, `load` and `build` rather than `all` keeps this run from overwriting the report.

- [ ] **Step 4: Update the docs and commit**

Add the join results to "Measured July 2024 build" in `docs/data-sources.md`. In `docs/phase-1-plan.md`, replace "set thresholds after the first run" with "thresholds wait for a second month, see `DECISIONS.md`", and add the report path. Add `report` to the commands in `CLAUDE.md`, and update its Status to say phase 1 is built, with the next action being the user's review of the report and a decision on merging `phase-1-foundation`, ahead of the roadmap's OpenSky collection and phase 2. Add `docs/phase-1-report.md` to the Docs list.

Append to `DECISIONS.md`:

```markdown
## 2026-11-01: Hold off on thresholds for reported checks
- **Chose:** reported checks record values with no pass or fail, for now.
- **Gave up:** an automatic warning when, say, the tail match rate drops, so a person has to read the report.
- **Why:** the phase plan meant to set them after the first run, but one month containing a major outage can't show what normal looks like.
- **Revisit if:** a second month is loaded. Set thresholds from the two months together.

## 2026-11-01: Generate the report's tables and write its findings by hand
- **Chose:** `docs/phase-1-report.md` comes from `python -m flightops report`, with the SQL under each table. The findings and limits are fixed prose in `report.py`.
- **Gave up:** a report that fully rewrites itself, so the prose can fall out of step when data changes.
- **Why:** tables that can't drift make the report defensible line by line, and interpreting them is a human job. Generating the sentences as well would be more code and read worse.
- **Revisit if:** the project reports on more than a few months.

## 2026-11-01: Define adverse weather for the cross-check only
- **Chose:** thunderstorm, heavy rain, fog, snow or freezing precipitation, ceiling under 1,000 ft, visibility under 3 SM, or gust of 30 kt or more, defined in the report.
- **Gave up:** a standard category such as FAA IFR, so the definition is open to challenge.
- **Why:** the cross-check needs a yes or no on weather that could delay flights, and that wording is easy to read and to dispute line by line.
- **Revisit if:** phase 2 or 3 needs weather as a feature. Then define it in `ontology`, and test it against delays.
```

```bash
git add docs DECISIONS.md CLAUDE.md pipelines
git commit -m "feat: add the July 2024 data-quality report and close phase 1"
```

---

## Build notes, 2026-11-01

All expected values matched. The plan's findings had no walkthrough, although step 7 asks for one, so the build added a finding for `N102DN`, drawn from the report's last table.
