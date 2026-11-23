# Phase 6 step 2: cancellation rate table and backtest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** fill `ontology.cancel_rate` (cancellation rates fitted on July 2024) and `ontology.cancel_backtest` (every inbound × target pair in both months, scored against two baselines), and publish them in a generated `docs/phase-6-report.md`.

**Architecture:** migration 025 adds an index, two bucket functions, a carrier-hour count table, a `cancel_pair` view (inbound, target, features, outcome) and the two result tables. Two SQL files in `pipelines/flightops/rotations/` fill them, run by `pipeline.build` after `backtest.sql`: `cancel_rate.sql` (carrier-hour counts, then July rates) and `cancel_backtest.sql` (every pair, with its rate, basis and baselines). This is the same split as `min_turn.sql` / `backtest.sql`, so tests can inject a fixed rate table and rerun only the backtest. The report is a third entry in `report.REPORTS`.

**Tech Stack:** Postgres 18 (Postgres.app), Python with `uv`, psycopg, pytest.

## Global Constraints

- Fit set: `ontology.period(flight_date) LIKE 'july_%'`, using the inbound's flight date. Score set: every period. The report shows `july_normal`, `july_outage`, `debby` and `august`, with `august` and `debby` as the holdout.
- Inbound: a leg in `ontology.rotation_leg` with `touched_atl` (per calendar month, as it already is) and a non-NULL `arr_delay_min`. That excludes diverted legs.
- Decision moment `t`: the inbound's `actual_dep_utc`.
- Targets: the same tail's next 3 legs in `ontology.flight`, flown or cancelled, ordered by `sched_dep_utc` (then `flight_id`) after the inbound's `sched_dep_utc`, and kept only if `sched_dep_utc <= inbound actual_arr_utc + 24h`. `rank` is 1-3.
- Delay buckets: `<15` (including early), `15-59`, `60-119`, `120-239`, `240+`.
- Stress: cancelled share of the inbound carrier's departures scheduled in the window, excluding the inbound's own tail. No departures counts as 0. Buckets `<2%`, `2-10%`, `10%+`, tentative until Task 3 measures them.
- Fallback: a carrier cell with fewer than 200 samples uses the all-carrier cell. An all-carrier cell is used at any count, and `basis_samples` shows the count.
- Next free migration number is 025. Migrations are applied once and recorded in `public.schema_migration`, so a change after 025 is applied locally goes in 026.
- Out of scope: `propagate` columns, the decision log (step 3) and the app (step 4).
- Commands run from `pipelines/`: `uv run --env-file ../.env pytest` and `uv run --env-file ../.env python -m flightops ...`.

## One change to the spec, for review

The phase plan defines the stress window as `[t − 3h, t)` and the brief says to precompute carrier-hour counts. Those two don't fit exactly: hour counts can only sum whole hours. This plan uses **the three whole UTC clock hours before `t`'s hour**, `[hour(t) − 3h, hour(t))`. It still holds only departures scheduled before `t`, so no cancellation counts before its scheduled departure. The window ends 0-59 min before `t`, so the most recent cancellations are left out. It costs three equality lookups on a primary key per inbound, against a range count over a flight table with 1.25M rows. If you want the exact window, the alternative is a running count per carrier, one row per flight, read with two index lookups per inbound. It is more code, and Task 3's timing would show whether it is needed. Task 4 records the choice in `DECISIONS.md`.

The N102DN worked example also changes. ATL→BWI is rank 4 (after the three cancelled legs), so it gets no rate. The report shows it as `not scored: rank 4`. Step 3's `propagate` treats it the same way.

---

## File structure

| File | Responsibility |
|---|---|
| `db/migrations/025_cancel_rate.sql` (create) | index on `flight (tail_number, sched_dep_utc)`, `ontology.delay_bucket`, `ontology.stress_bucket`, `ontology.carrier_hour`, `ontology.cancel_pair` view, `ontology.cancel_rate`, `ontology.cancel_backtest` |
| `pipelines/flightops/rotations/cancel_rate.sql` (create) | refill `carrier_hour`, then the July rates |
| `pipelines/flightops/rotations/cancel_backtest.sql` (create) | refill the scored pairs |
| `pipelines/flightops/resolve/ontology.sql` (modify, line 1) | add the three new tables to the `TRUNCATE ... RESTART IDENTITY`, because they reference `flight` and `carrier` |
| `pipelines/flightops/pipeline.py` (modify) | run both files after `backtest.sql` |
| `pipelines/tests/fixtures/bts_cancel.csv` (create) | the awkward cases |
| `pipelines/tests/test_cancel.py` (create) | buckets, stress, ranks, 24h cut, July-only fit, fallback, rebuild |
| `pipelines/flightops/report.py` (modify) | `P6_HEADER`, `P6_FINDINGS`, `P6_SECTIONS`, a `REPORTS` entry |
| `pipelines/tests/test_report.py` (modify) | phase 6 report runs and picks the threshold |
| `docs/phase-6-report.md` (generated) | the cancellation report |
| `DECISIONS.md`, `docs/phase-6-plan.md`, `CLAUDE.md` (modify) | decisions, measured notes, status |

---

### Task 1: Schema, rate table and its fixture tests

**Files:**
- Create: `db/migrations/025_cancel_rate.sql`, `pipelines/flightops/rotations/cancel_rate.sql`, `pipelines/flightops/rotations/cancel_backtest.sql`, `pipelines/tests/fixtures/bts_cancel.csv`, `pipelines/tests/test_cancel.py`
- Modify: `pipelines/flightops/resolve/ontology.sql:1`, `pipelines/flightops/pipeline.py`

**Interfaces:**
- Produces: `ontology.delay_bucket(integer) -> text`, `ontology.stress_bucket(numeric) -> text`, the view `ontology.cancel_pair (inbound_flight_id, target_flight_id, rank, period, carrier_id, arr_delay_min, stress, cancelled)`, the tables `ontology.cancel_rate (carrier_id, rank, delay_bucket, stress_bucket, samples, cancelled, rate)` and `ontology.cancel_backtest` (columns in Step 3). Step 3's `propagate` reuses the two bucket functions and `carrier_hour`.

The fixture times are Eastern local (EDT, UTC−4). The cases it covers:

| Tail | Case |
|---|---|
| N1C, July 10 | N102DN-shaped. 101 LGA→ATL is 150 min late, leaving at 10:30 local (14:30 UTC). Then 102 and 103 are cancelled and 104 is flown, so ranks 1-3 follow the schedule. 100 is an own-tail cancellation inside the stress window |
| N9C, July 10 | another DL tail. 901 is flown and 902 cancelled inside 101's window. 903 is cancelled at 10:15 local, after the window closes (it is in `t`'s own hour), so it doesn't count |
| N7C, July 10 | a DL tail that never touches ATL. 701 is a flown departure in the window, which counts for stress but is never an inbound |
| N6C, July 10 | a WN cancellation in the window. Another carrier's, so it doesn't count |
| N2C, July 12-13 | 201 is exactly 15 min late (bucket edge). 202 next day is inside the 24h cut and 203 is outside it |
| N5C, Aug 10 | an August pair whose cell July never saw |

101's stress: DL departures scheduled 11:00-13:59 UTC are 100, 101 (own tail, one cancelled), 901, 902 (cancelled) and 701. Excluding the own tail that is 1 of 3 = 0.333. With the own tail it would be 2 of 5 = 0.4, and with the exact window it would also count 903 (0.5).

- [ ] **Step 1: Write the fixture** `pipelines/tests/fixtures/bts_cancel.csv`

```csv
flightdate,reporting_airline,tail_number,flight_number_reporting_airline,origin,dest,crsdeptime,deptime,depdelay,crsarrtime,arrtime,arrdelay,crselapsedtime,actualelapsedtime,cancelled,cancellationcode,diverted,divreacheddest,div1airport,div1wheelson,carrierdelay,weatherdelay,nasdelay,securitydelay,lateaircraftdelay
2024-07-10,DL,N1C,100,ATL,LGA,0700,,,0900,,,120.00,,1.00,B,0.00,,,,,,,,
2024-07-10,DL,N1C,101,LGA,ATL,0800,1030,150.00,1000,1230,150.00,120.00,120.00,0.00,,0.00,,,,150.00,0.00,0.00,0.00,0.00
2024-07-10,DL,N1C,102,ATL,CLE,1100,,,1230,,,90.00,,1.00,A,0.00,,,,,,,,
2024-07-10,DL,N1C,103,CLE,ATL,1400,,,1530,,,90.00,,1.00,A,0.00,,,,,,,,
2024-07-10,DL,N1C,104,ATL,IAD,1700,1700,0.00,1830,1830,0.00,90.00,90.00,0.00,,0.00,,,,,,,,
2024-07-10,DL,N9C,901,ATL,LGA,0700,0700,0.00,0900,0900,0.00,120.00,120.00,0.00,,0.00,,,,,,,,
2024-07-10,DL,N9C,902,LGA,ATL,0900,,,1100,,,120.00,,1.00,A,0.00,,,,,,,,
2024-07-10,DL,N9C,903,ATL,CLE,1015,,,1145,,,90.00,,1.00,A,0.00,,,,,,,,
2024-07-10,DL,N7C,701,CLE,IAD,0800,0800,0.00,0930,0930,0.00,90.00,90.00,0.00,,0.00,,,,,,,,
2024-07-10,WN,N6C,601,LGA,IAD,0900,,,1030,,,90.00,,1.00,A,0.00,,,,,,,,
2024-07-12,DL,N2C,201,LGA,ATL,0800,0815,15.00,1000,1015,15.00,120.00,120.00,0.00,,0.00,,,,15.00,0.00,0.00,0.00,0.00
2024-07-13,DL,N2C,202,ATL,LGA,0900,0900,0.00,1100,1100,0.00,120.00,120.00,0.00,,0.00,,,,,,,,
2024-07-13,DL,N2C,203,LGA,ATL,1100,1100,0.00,1300,1300,0.00,120.00,120.00,0.00,,0.00,,,,,,,,
2024-08-10,DL,N5C,501,LGA,ATL,0800,0900,60.00,1000,1100,60.00,120.00,120.00,0.00,,0.00,,,,60.00,0.00,0.00,0.00,0.00
2024-08-10,DL,N5C,502,ATL,CLE,1200,,,1330,,,90.00,,1.00,A,0.00,,,,,,,,
```

- [ ] **Step 2: Write the failing tests** `pipelines/tests/test_cancel.py`

```python
import pytest

from flightops import pipeline

COLS = """i.flight_number, t.flight_number, b.rank, b.period, b.delay_bucket, round(b.stress, 3)::float8,
          b.stress_bucket, round(b.predicted_rate, 3)::float8, b.basis, b.basis_samples,
          round(b.carrier_rate, 3)::float8, round(b.delay_rate, 3)::float8, b.actual_cancelled"""


@pytest.fixture
def built(conn, load_fixture):
    load_fixture("ourairports_airports", "airports.csv")
    load_fixture("bts_ontime", "bts_cancel.csv")
    pipeline.build(conn)
    return conn


def rows(conn):
    return conn.execute(
        f"select {COLS} from ontology.cancel_backtest b "
        "join ontology.flight i on i.flight_id = b.inbound_flight_id "
        "join ontology.flight t on t.flight_id = b.target_flight_id order by 1, 3"
    ).fetchall()


def test_buckets_at_their_edges(conn):
    got = conn.execute(
        "select ontology.delay_bucket(d) from unnest(array[-5, 14, 15, 59, 60, 119, 120, 239, 240, null]) d"
    ).fetchall()
    assert [g[0] for g in got] == ["<15", "<15", "15-59", "15-59", "60-119", "60-119", "120-239", "120-239", "240+", None]
    got = conn.execute(
        "select ontology.stress_bucket(s) from unnest(array[0, 0.0199, 0.02, 0.0999, 0.1, 1]::numeric[]) s"
    ).fetchall()
    assert [g[0] for g in got] == ["<2%", "<2%", "2-10%", "2-10%", "10%+", "10%+"]


def test_backtest_pairs_features_and_fallback_to_all_carriers(built):
    # July DL pairs give 7 samples, 4 cancelled, so the DL constant baseline is 0.571.
    # Every carrier cell is under 200 samples, so every rate comes from the all-carrier cell.
    assert rows(built) == [
        # Ranks follow the schedule: two cancelled legs come before the flown 104.
        # Stress 1/3: own-tail 100 and 101 are excluded, 903 (after the window) and WN 601 don't count.
        ("101", "102", 1, "july_normal", "120-239", 0.333, "10%+", 1.0, "all carriers", 1, 0.571, 1.0, True),
        ("101", "103", 2, "july_normal", "120-239", 0.333, "10%+", 1.0, "all carriers", 1, 0.571, 1.0, True),
        ("101", "104", 3, "july_normal", "120-239", 0.333, "10%+", 0.0, "all carriers", 1, 0.571, 0.0, False),
        # 15 min late is in 15-59. No departures in its window counts as stress 0. 203 is past the 24h cut.
        ("201", "202", 1, "july_normal", "15-59", 0.0, "<2%", 0.0, "all carriers", 1, 0.571, 0.0, False),
        ("202", "203", 1, "july_normal", "<15", 0.0, "<2%", 0.5, "all carriers", 2, 0.571, 0.5, False),
        # August is scored but not fitted, and July has no 60-119 cell, so there is no rate.
        ("501", "502", 1, "august", "60-119", 0.0, "<2%", None, None, None, 0.571, None, True),
        ("901", "902", 1, "july_normal", "<15", 0.0, "<2%", 0.5, "all carriers", 2, 0.571, 0.5, True),
        ("901", "903", 2, "july_normal", "<15", 0.0, "<2%", 1.0, "all carriers", 1, 0.571, 1.0, True),
    ]


def test_rate_table_is_fitted_on_july_only(built):
    got = built.execute(
        "select c.code, r.rank, r.delay_bucket, r.stress_bucket, r.samples, r.cancelled, round(r.rate, 3)::float8 "
        "from ontology.cancel_rate r left join ontology.carrier c using (carrier_id) "
        'order by c.code nulls last, r.delay_bucket collate "C", r.stress_bucket collate "C", r.rank'
    ).fetchall()
    cells = [
        (1, "120-239", "10%+", 1, 1, 1.0), (2, "120-239", "10%+", 1, 1, 1.0), (3, "120-239", "10%+", 1, 0, 0.0),
        (1, "15-59", "<2%", 1, 0, 0.0), (1, "<15", "<2%", 2, 1, 0.5), (2, "<15", "<2%", 1, 1, 1.0),
    ]  # no 60-119 cell: N5C's pair is in August
    assert got == [("DL", *c) for c in cells] + [(None, *c) for c in cells]


def test_carrier_cell_used_at_200_samples_and_all_carrier_cell_below(built):
    built.execute("truncate ontology.cancel_rate")
    built.execute(
        "insert into ontology.cancel_rate (carrier_id, rank, delay_bucket, stress_bucket, samples, cancelled, rate) "
        "select carrier_id, 1, '120-239', '10%+', 250, 100, 0.4 from ontology.carrier where code = 'DL' "
        "union all select null, 1, '120-239', '10%+', 1000, 300, 0.3 "
        "union all select carrier_id, 2, '120-239', '10%+', 150, 135, 0.9 from ontology.carrier where code = 'DL' "
        "union all select null, 2, '120-239', '10%+', 50, 10, 0.2"
    )
    pipeline.run_sql(built, "rotations/cancel_backtest.sql")
    got = [r[1:3] + r[7:10] for r in rows(built) if r[0] == "101"]
    assert got == [
        ("102", 1, 0.4, "carrier", 250),
        ("103", 2, 0.2, "all carriers", 50),  # the carrier cell has 150; the all-carrier cell is used under 200 too
        ("104", 3, None, None, None),  # no cell at all
    ]


def test_rebuild_replaces_rates_and_pairs(built):
    pipeline.build(built)
    assert built.execute("select count(*) from ontology.cancel_rate").fetchone() == (12,)
    assert built.execute("select count(*) from ontology.cancel_backtest").fetchone() == (8,)
```

- [ ] **Step 3: Run the tests to see them fail**

Run: `uv run --env-file ../.env pytest tests/test_cancel.py -v`
Expected: FAIL, `function ontology.delay_bucket(integer) does not exist` and `relation "ontology.cancel_backtest" does not exist`.

- [ ] **Step 4: Write the migration** `db/migrations/025_cancel_rate.sql`

```sql
-- Phase 6 step 2 (docs/phase-6-plan.md): cancellation risk on a late inbound's next scheduled legs.

-- A tail's next legs by schedule, for targets and for removing the own tail from stress.
CREATE INDEX ON ontology.flight (tail_number, sched_dep_utc);

CREATE FUNCTION ontology.delay_bucket(p_delay integer) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE
        WHEN p_delay < 15 THEN '<15'  -- early arrivals included
        WHEN p_delay < 60 THEN '15-59'
        WHEN p_delay < 120 THEN '60-119'
        WHEN p_delay < 240 THEN '120-239'
        WHEN p_delay >= 240 THEN '240+'
    END
$$;

-- shortcut: edges come from the July probe (docs/phase-6-plan.md notes), replace them if Task 3's measurement disagrees.
CREATE FUNCTION ontology.stress_bucket(p_stress numeric) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE WHEN p_stress < 0.02 THEN '<2%' WHEN p_stress < 0.10 THEN '2-10%' WHEN p_stress >= 0.10 THEN '10%+' END
$$;

-- National departures and cancellations per carrier per UTC hour of scheduled departure.
CREATE TABLE ontology.carrier_hour (
    carrier_id bigint NOT NULL REFERENCES ontology.carrier,
    hour       timestamptz NOT NULL,
    departures integer NOT NULL,
    cancelled  integer NOT NULL,
    PRIMARY KEY (carrier_id, hour)
);

-- One row per late-or-not inbound and each of its next three scheduled legs, with the features known at its
-- actual departure t. A cancellation counts as known from its scheduled departure: BTS gives no announcement time.
CREATE VIEW ontology.cancel_pair AS
WITH inbound AS (
    SELECT f.flight_id, f.tail_number, f.carrier_id, f.flight_date, f.sched_dep_utc, f.actual_arr_utc, f.arr_delay_min,
           date_trunc('hour', f.actual_dep_utc, 'UTC') AS t_hour
    FROM ontology.rotation_leg r
    JOIN ontology.flight f USING (flight_id)
    WHERE r.touched_atl AND f.arr_delay_min IS NOT NULL  -- diverted legs have no arrival delay
)
SELECT i.flight_id AS inbound_flight_id, t.flight_id AS target_flight_id, t.rank,
       ontology.period(i.flight_date) AS period, i.carrier_id, i.arr_delay_min,
       -- shortcut: the window is the 3 whole UTC hours before t's hour, not [t - 3h, t); see DECISIONS.md.
       coalesce((h.cancelled - o.cancelled)::numeric / nullif(h.departures - o.departures, 0), 0) AS stress,
       t.cancelled
FROM inbound i
CROSS JOIN LATERAL (
    SELECT x.flight_id, x.sched_dep_utc, x.cancelled, row_number() OVER (ORDER BY x.sched_dep_utc, x.flight_id) AS rank
    FROM ontology.flight x
    WHERE x.tail_number = i.tail_number AND x.sched_dep_utc > i.sched_dep_utc
    ORDER BY x.sched_dep_utc, x.flight_id
    LIMIT 3
) t
CROSS JOIN LATERAL (
    SELECT coalesce(sum(c.departures), 0) AS departures, coalesce(sum(c.cancelled), 0) AS cancelled
    FROM ontology.carrier_hour c
    WHERE c.carrier_id = i.carrier_id AND c.hour >= i.t_hour - interval '3 hours' AND c.hour < i.t_hour
) h
CROSS JOIN LATERAL (
    SELECT count(*) AS departures, count(*) FILTER (WHERE x.cancelled) AS cancelled
    FROM ontology.flight x
    WHERE x.tail_number = i.tail_number AND x.carrier_id = i.carrier_id
      AND x.sched_dep_utc >= i.t_hour - interval '3 hours' AND x.sched_dep_utc < i.t_hour
) o
WHERE t.sched_dep_utc <= i.actual_arr_utc + interval '24 hours';

CREATE TABLE ontology.cancel_rate (
    carrier_id    bigint REFERENCES ontology.carrier,  -- NULL: all carriers together
    rank          integer NOT NULL,
    delay_bucket  text NOT NULL,
    stress_bucket text NOT NULL,
    samples       integer NOT NULL,
    cancelled     integer NOT NULL,
    rate          numeric NOT NULL,
    UNIQUE NULLS NOT DISTINCT (carrier_id, rank, delay_bucket, stress_bucket)
);

CREATE TABLE ontology.cancel_backtest (
    inbound_flight_id bigint NOT NULL REFERENCES ontology.flight,
    target_flight_id  bigint NOT NULL REFERENCES ontology.flight,
    rank              integer NOT NULL,
    period            text NOT NULL,
    carrier_id        bigint NOT NULL REFERENCES ontology.carrier,
    arr_delay_min     integer NOT NULL,
    delay_bucket      text NOT NULL,
    stress            numeric NOT NULL,
    stress_bucket     text NOT NULL,
    predicted_rate    numeric,  -- NULL when July has no cell, carrier or all-carrier
    basis             text,     -- 'carrier' or 'all carriers'
    basis_samples     integer,
    carrier_rate      numeric,  -- baseline: the carrier's July rate over all its cells
    delay_rate        numeric,  -- baseline: all carriers, delay bucket x rank
    actual_cancelled  boolean NOT NULL,
    PRIMARY KEY (inbound_flight_id, rank)
);
```

- [ ] **Step 5: Write `pipelines/flightops/rotations/cancel_rate.sql`**

```sql
TRUNCATE ontology.carrier_hour, ontology.cancel_rate;

INSERT INTO ontology.carrier_hour (carrier_id, hour, departures, cancelled)
SELECT carrier_id, date_trunc('hour', sched_dep_utc, 'UTC'), count(*), count(*) FILTER (WHERE cancelled)
FROM ontology.flight
GROUP BY 1, 2;

ANALYZE ontology.carrier_hour;

WITH p AS (
    SELECT carrier_id, rank, ontology.delay_bucket(arr_delay_min) AS delay_bucket,
           ontology.stress_bucket(stress) AS stress_bucket, cancelled
    FROM ontology.cancel_pair
    WHERE period LIKE 'july_%'  -- fit on July only, so August scores out of sample
)
INSERT INTO ontology.cancel_rate (carrier_id, rank, delay_bucket, stress_bucket, samples, cancelled, rate)
SELECT carrier_id, rank, delay_bucket, stress_bucket, count(*), count(*) FILTER (WHERE cancelled), avg(cancelled::int)
FROM p
GROUP BY GROUPING SETS ((carrier_id, rank, delay_bucket, stress_bucket), (rank, delay_bucket, stress_bucket));
```

- [ ] **Step 6: Write `pipelines/flightops/rotations/cancel_backtest.sql`**

```sql
TRUNCATE ontology.cancel_backtest;

WITH p AS (
    SELECT *, ontology.delay_bucket(arr_delay_min) AS delay_bucket, ontology.stress_bucket(stress) AS stress_bucket
    FROM ontology.cancel_pair
),
-- Both baselines are sums over the fitted cells, so they come from July too.
carrier_base AS (
    SELECT carrier_id, sum(cancelled)::numeric / sum(samples) AS rate
    FROM ontology.cancel_rate WHERE carrier_id IS NOT NULL GROUP BY 1
),
delay_base AS (
    SELECT rank, delay_bucket, sum(cancelled)::numeric / sum(samples) AS rate
    FROM ontology.cancel_rate WHERE carrier_id IS NULL GROUP BY 1, 2
)
INSERT INTO ontology.cancel_backtest
SELECT p.inbound_flight_id, p.target_flight_id, p.rank, p.period, p.carrier_id, p.arr_delay_min, p.delay_bucket,
       p.stress, p.stress_bucket,
       CASE WHEN c.samples >= 200 THEN c.rate ELSE a.rate END,
       CASE WHEN c.samples >= 200 THEN 'carrier' WHEN a.samples IS NOT NULL THEN 'all carriers' END,
       CASE WHEN c.samples >= 200 THEN c.samples ELSE a.samples END,
       cb.rate, db.rate, p.cancelled
FROM p
LEFT JOIN ontology.cancel_rate c ON c.carrier_id = p.carrier_id AND c.rank = p.rank
     AND c.delay_bucket = p.delay_bucket AND c.stress_bucket = p.stress_bucket
LEFT JOIN ontology.cancel_rate a ON a.carrier_id IS NULL AND a.rank = p.rank
     AND a.delay_bucket = p.delay_bucket AND a.stress_bucket = p.stress_bucket
LEFT JOIN carrier_base cb ON cb.carrier_id = p.carrier_id
LEFT JOIN delay_base db ON db.rank = p.rank AND db.delay_bucket = p.delay_bucket;
```

`period` is NOT NULL in the table, so an inbound outside the loaded months fails loudly, as in `backtest.sql`.

- [ ] **Step 7: Wire the build**

In `pipelines/flightops/resolve/ontology.sql` line 1, add the three tables at the front of the `TRUNCATE` list, because they reference `flight` and `carrier`:

```sql
TRUNCATE ontology.cancel_backtest, ontology.cancel_rate, ontology.carrier_hour, ontology.propagation_backtest, ontology.min_turn, ontology.flight_weather, ontology.rotation_leg, ontology.delay, ontology.taf_forecast, ontology.weather_observation, ontology.flight,
```

In `pipelines/flightops/pipeline.py`, after `run_sql(conn, "rotations/backtest.sql")`:

```python
    run_sql(conn, "rotations/cancel_rate.sql")
    run_sql(conn, "rotations/cancel_backtest.sql")
```

- [ ] **Step 8: Run the new tests, then the full suite**

Run: `uv run --env-file ../.env pytest tests/test_cancel.py -v`
Expected: 5 passed.
Run: `uv run --env-file ../.env pytest`
Expected: all pass. The `conn` fixture migrates a fresh test database, so 025 is picked up.

If an expected row differs, recheck the fixture arithmetic in the table above before changing the SQL. The assertions encode the spec.

- [ ] **Step 9: Commit**

```bash
git add db/migrations/025_cancel_rate.sql pipelines/flightops/rotations/cancel_rate.sql pipelines/flightops/rotations/cancel_backtest.sql pipelines/flightops/resolve/ontology.sql pipelines/flightops/pipeline.py pipelines/tests/fixtures/bts_cancel.csv pipelines/tests/test_cancel.py
git commit -m "feat: cancellation rate table and backtest, fitted on July"
```

---

### Task 2: Phase 6 report

**Files:**
- Modify: `pipelines/flightops/report.py` (new constants before `def _table`, plus a `REPORTS` entry)
- Modify: `pipelines/tests/test_report.py` (append)

**Interfaces:**
- Consumes: `ontology.cancel_backtest`, `ontology.cancel_rate` from Task 1, the `N102DN` constant already in `report.py`.
- Produces: `report.REPORTS["phase-6-report.md"] = (P6_HEADER, P6_FINDINGS, P6_SECTIONS)`, and a `THRESHOLD` SQL fragment (one row, column `r`) used by two sections.

- [ ] **Step 1: Write the failing tests** (append to `pipelines/tests/test_report.py`)

```python
@pytest.fixture
def cancel_scored(conn, load_fixture):
    load_fixture("ourairports_airports", "airports.csv")
    load_fixture("bts_ontime", "bts_cancel.csv")
    pipeline.build(conn)
    return conn


def phase6(conn):
    return report.render(conn, *report.REPORTS["phase-6-report.md"])


def test_phase6_every_section_runs_and_has_a_heading(cancel_scored):
    text = phase6(cancel_scored)
    for heading, _, _ in report.P6_SECTIONS:
        assert f"## {heading}" in text
    assert "None" not in text


def test_phase6_threshold_maximizes_july_f1(cancel_scored):
    # July predictions: 1.0 x3 (all cancelled), 0.5 x2 (one cancelled), 0.0 x2 (none); 4 cancelled in all.
    # Flagging at 0.5 catches 4 of 5 flagged and all 4 cancelled: F1 8/9, above 6/7 at 1.0 and 8/11 at 0.0.
    assert "| 50.0 | 5 | 4 | 80.0 | 100.0 | 0.889 |" in phase6(cancel_scored)
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run --env-file ../.env pytest tests/test_report.py -k phase6 -v`
Expected: FAIL with `KeyError: 'phase-6-report.md'`.

- [ ] **Step 3: Add the report** to `pipelines/flightops/report.py`, before `def _table`

```python
P6_HEADER = """# Phase 6 cancellation risk: July and August 2024

Generated by `python -m flightops report`. Don't edit this file. Tables come from the database, and the SQL behind each one sits under it. Times are UTC.

An inbound is a flown leg on a tail that touched ATL that month, with an arrival delay (diverted legs have none). Its targets are the tail's next three legs by scheduled departure, flown or cancelled, scheduled within 24h of the inbound's arrival. Each target gets the July cancellation rate of its cell: carrier × rank × delay bucket × carrier stress, or the all-carrier cell when the carrier cell has fewer than 200 samples. Carrier stress is the cancelled share of the carrier's national departures scheduled in the three whole UTC hours before the inbound's actual departure hour, excluding the inbound's own tail. A cancellation counts as known from its scheduled departure. Rates and the flag threshold are fitted on July. `debby` (August 2-6) and `august` are the holdout.
"""

# Written by hand from the tables below in Task 4. Rewrite them if the data changes.
P6_FINDINGS = """## Findings

Written after the first full build.
"""

THRESHOLD = """SELECT r FROM (
    SELECT r, 2.0 * sum(c) OVER w / (sum(n) OVER w + sum(c) OVER ()) AS f1
    FROM (SELECT predicted_rate AS r, count(*) AS n, count(*) FILTER (WHERE actual_cancelled) AS c
          FROM ontology.cancel_backtest WHERE period LIKE 'july_%' AND predicted_rate IS NOT NULL GROUP BY 1) g
    WINDOW w AS (ORDER BY r DESC)
) t ORDER BY f1 DESC, r DESC LIMIT 1"""

P6_SECTIONS = [
    (
        "Rate table",
        "All-carrier cells fitted on July. Carrier cells are used instead where they hold 200 samples or more.",
        """SELECT rank, delay_bucket, stress_bucket, samples, cancelled, round(100 * rate, 2) AS rate_pct
FROM ontology.cancel_rate WHERE carrier_id IS NULL
ORDER BY rank, array_position(ARRAY['<15', '15-59', '60-119', '120-239', '240+'], delay_bucket),
         array_position(ARRAY['<2%', '2-10%', '10%+'], stress_bucket)""",
    ),
    (
        "Does the holdout reach high stress?",
        "Pairs and cancellations in the highest stress bucket, per period. If `debby` and `august` hold few of them, "
        "July's high-stress cells, which come from a single outage, are untested out of sample.",
        """SELECT period, count(*) AS pairs,
       count(*) FILTER (WHERE stress_bucket = '10%+') AS high_stress_pairs,
       count(*) FILTER (WHERE stress_bucket = '10%+' AND actual_cancelled) AS high_stress_cancelled,
       count(*) FILTER (WHERE stress_bucket = '10%+' AND arr_delay_min >= 120) AS high_stress_120_plus,
       round(100 * max(stress), 1) AS max_stress_pct,
       round(100.0 * count(*) FILTER (WHERE actual_cancelled) / count(*), 2) AS cancelled_pct
FROM ontology.cancel_backtest GROUP BY 1 ORDER BY 1""",
    ),
    (
        "Brier score against baselines",
        "Mean squared error of the predicted probability against the outcome (0 or 1), lower is better, on pairs where "
        "the model and both baselines have a rate. The carrier baseline is the carrier's July rate. The delay baseline is "
        "July's all-carrier rate for the delay bucket and rank, without stress. `unscored` pairs had no July cell.",
        """SELECT period, rank, count(*) FILTER (WHERE s) AS pairs, count(*) FILTER (WHERE NOT s) AS unscored,
       round(100.0 * avg(actual_cancelled::int) FILTER (WHERE s), 2) AS cancelled_pct,
       round(avg((predicted_rate - actual_cancelled::int) ^ 2) FILTER (WHERE s), 5) AS brier_model,
       round(avg((carrier_rate - actual_cancelled::int) ^ 2) FILTER (WHERE s), 5) AS brier_carrier,
       round(avg((delay_rate - actual_cancelled::int) ^ 2) FILTER (WHERE s), 5) AS brier_delay
FROM (SELECT *, predicted_rate IS NOT NULL AND carrier_rate IS NOT NULL AND delay_rate IS NOT NULL AS s
      FROM ontology.cancel_backtest) b
GROUP BY 1, 2 ORDER BY 1, 2""",
    ),
    (
        "Calibration",
        "Predicted against actual cancellation rate by decile of predicted rate, ranks pooled. "
        "A calibrated model has the two columns close in every decile.",
        """SELECT period, decile, count(*) AS pairs,
       round(100 * avg(predicted_rate), 2) AS predicted_pct, round(100.0 * avg(actual_cancelled::int), 2) AS actual_pct
FROM (SELECT period, predicted_rate, actual_cancelled,
             ntile(10) OVER (PARTITION BY period ORDER BY predicted_rate) AS decile
      FROM ontology.cancel_backtest WHERE predicted_rate IS NOT NULL) b
GROUP BY 1, 2 ORDER BY 1, 2""",
    ),
    (
        "Flag threshold",
        "Chosen on all of July, ranks 1-3 pooled, as the predicted rate that maximizes F1 when every pair at or above it is flagged.",
        f"""WITH th AS ({THRESHOLD})
SELECT round(100 * th.r, 1) AS threshold_pct,
       count(*) FILTER (WHERE b.predicted_rate >= th.r) AS flagged,
       count(*) FILTER (WHERE b.predicted_rate >= th.r AND b.actual_cancelled) AS flagged_cancelled,
       round(100.0 * count(*) FILTER (WHERE b.predicted_rate >= th.r AND b.actual_cancelled)
             / nullif(count(*) FILTER (WHERE b.predicted_rate >= th.r), 0), 1) AS precision_pct,
       round(100.0 * count(*) FILTER (WHERE b.predicted_rate >= th.r AND b.actual_cancelled)
             / nullif(count(*) FILTER (WHERE b.actual_cancelled), 0), 1) AS recall_pct,
       round(2.0 * count(*) FILTER (WHERE b.predicted_rate >= th.r AND b.actual_cancelled)
             / (count(*) FILTER (WHERE b.predicted_rate >= th.r) + count(*) FILTER (WHERE b.actual_cancelled)), 3) AS f1
FROM ontology.cancel_backtest b CROSS JOIN th
WHERE b.period LIKE 'july_%' AND b.predicted_rate IS NOT NULL
GROUP BY th.r""",
    ),
    (
        "Flag scored by period",
        "The July threshold applied to every period and rank. `debby` and `august` are out of sample.",
        f"""WITH th AS ({THRESHOLD})
SELECT b.period, b.rank, count(*) AS pairs,
       count(*) FILTER (WHERE b.predicted_rate >= th.r) AS flagged,
       round(100.0 * count(*) FILTER (WHERE b.predicted_rate >= th.r AND b.actual_cancelled)
             / nullif(count(*) FILTER (WHERE b.predicted_rate >= th.r), 0), 1) AS precision_pct,
       round(100.0 * count(*) FILTER (WHERE b.predicted_rate >= th.r AND b.actual_cancelled)
             / nullif(count(*) FILTER (WHERE b.actual_cancelled), 0), 1) AS recall_pct
FROM ontology.cancel_backtest b CROSS JOIN th
WHERE b.predicted_rate IS NOT NULL
GROUP BY 1, 2 ORDER BY 1, 2""",
    ),
    (
        "Basis",
        "How often a pair was scored from its carrier's cell, from the all-carrier cell, or not at all.",
        """SELECT period, coalesce(basis, 'no July cell') AS basis, count(*) AS pairs,
       round(100.0 * count(*) / sum(count(*)) OVER (PARTITION BY period), 1) AS share_pct
FROM ontology.cancel_backtest GROUP BY 1, 2 ORDER BY 1, 2""",
    ),
    (
        "Worked example: N102DN, July 19",
        "The tail's next four scheduled legs after its 316-min DEN→ATL. Only ranks 1-3 are scored, so ATL→BWI is not.",
        f"""SELECT n.rank, s.flight_number, o.iata_code AS origin, d.iata_code AS dest,
       to_char(s.sched_dep_utc AT TIME ZONE 'UTC', 'MM-DD HH24:MI') AS sched_dep,
       b.delay_bucket, round(100 * b.stress, 1) AS stress_pct, round(100 * b.predicted_rate, 1) AS predicted_pct,
       coalesce(b.basis || ', ' || b.basis_samples || ' samples', 'not scored: rank ' || n.rank) AS basis,
       s.cancelled
FROM (SELECT x.*, row_number() OVER (ORDER BY x.sched_dep_utc, x.flight_id) AS rank
      FROM ontology.flight x JOIN ontology.flight i ON i.flight_id = {N102DN}
      WHERE x.tail_number = i.tail_number AND x.sched_dep_utc > i.sched_dep_utc
      ORDER BY x.sched_dep_utc, x.flight_id LIMIT 4) n
JOIN ontology.flight s ON s.flight_id = n.flight_id
JOIN ontology.airport o ON o.airport_id = s.origin_airport_id
JOIN ontology.airport d ON d.airport_id = s.dest_airport_id
LEFT JOIN ontology.cancel_backtest b ON b.inbound_flight_id = {N102DN} AND b.target_flight_id = s.flight_id
ORDER BY n.rank""",
    ),
]
```

In the fixture, N102DN doesn't exist, so the worked example returns no rows, and that is fine.

Add the entry to `REPORTS`:

```python
    "phase-6-report.md": (P6_HEADER, P6_FINDINGS, P6_SECTIONS),
```

- [ ] **Step 4: Run the tests**

Run: `uv run --env-file ../.env pytest tests/test_report.py -v`
Expected: all pass, including the two phase 6 tests.

- [ ] **Step 5: Commit**

```bash
git add pipelines/flightops/report.py pipelines/tests/test_report.py
git commit -m "feat: phase 6 cancellation report"
```

---

### Task 3: Full build, timing and stress buckets (measure, then stop if anything is off)

**Files:**
- Modify: `docs/phase-6-plan.md` (Notes table)

No code changes unless a check below fails. If one fails, stop and bring the numbers to the user rather than changing the design.

- [ ] **Step 1: Migrate and time the full build**

Run: `time uv run --env-file ../.env python -m flightops migrate && time uv run --env-file ../.env python -m flightops build`
Expected: `025_cancel_rate.sql` applied, and the build finishes. Note both wall times. The previous rebuild took 685 s.

- [ ] **Step 2: Time the two new files on their own**

```bash
cd /Users/raunak/Developer/Side/flight-ops/pipelines
for f in cancel_rate cancel_backtest; do
  /usr/bin/time -p psql -h localhost -d flightops -v ON_ERROR_STOP=1 -q -f flightops/rotations/$f.sql
done
```

Expected: the two together add well under 300 s. **If they add more than 300 s, stop**, run `EXPLAIN (ANALYZE, BUFFERS)` on `SELECT count(*) FROM ontology.cancel_pair WHERE period LIKE 'july_%'`, and bring the plan to the user. The likely fix is materializing `cancel_pair` once into a temp table shared by both files.

- [ ] **Step 3: Sanity counts**

```sql
SELECT period, count(*) AS pairs, count(*) FILTER (WHERE actual_cancelled) AS cancelled,
       count(DISTINCT inbound_flight_id) AS inbounds
FROM ontology.cancel_backtest GROUP BY 1 ORDER BY 1;
SELECT count(*) FROM ontology.cancel_rate;
```

Expected: about 749,000 inbounds across the four periods (that is the inbound count before targets are joined; inbounds with no legs in 24h drop out), up to 3 pairs each, and `july_outage`'s cancelled share well above the others.

- [ ] **Step 4: Measure July's stress distribution**

```sql
SELECT stress_bucket, count(*) AS pairs, round(100.0 * count(*) / sum(count(*)) OVER (), 1) AS share_pct,
       round(100.0 * avg(actual_cancelled::int), 2) AS cancelled_pct
FROM ontology.cancel_backtest WHERE period LIKE 'july_%' GROUP BY 1 ORDER BY min(stress);
SELECT percentile_cont(ARRAY[0.5, 0.75, 0.9, 0.95, 0.99]) WITHIN GROUP (ORDER BY stress)
FROM ontology.cancel_backtest WHERE period LIKE 'july_%';
```

Keep the buckets if every bucket holds at least 2% of July pairs and the cancelled rate rises from bucket to bucket. Compare with the probe in the Notes (under 60 min late: 0.27%, 2.19%, 9.20%). Rates should read slightly lower, because the own tail is excluded. **If either check fails, stop** and propose edges to the user. A change is a new migration `026` that re-creates `ontology.stress_bucket`, followed by a rebuild.

- [ ] **Step 5: Check the Debby limit**

```sql
SELECT period, count(*) FILTER (WHERE stress_bucket = '10%+') AS high, round(100 * max(stress), 1) AS max_pct
FROM ontology.cancel_backtest GROUP BY 1 ORDER BY 1;
```

Note whether `debby` and `august` reach the `10%+` bucket, and how many pairs they put there compared with `july_outage`. This decides the report's limit wording in Task 4.

- [ ] **Step 6: Write the measured rows into the Notes table** in `docs/phase-6-plan.md`, replacing the "The build takes longer" row's "Measure again when the stress table lands" with the new times, and adding rows for: pairs per period, July stress distribution and the bucket decision, and the high-stress count per period.

- [ ] **Step 7: Commit**

```bash
git add docs/phase-6-plan.md
git commit -m "docs: measured cancel-rate build time and stress buckets"
```

---

### Task 4: Generate the report, write findings and decisions

**Files:**
- Modify: `pipelines/flightops/report.py` (`P6_FINDINGS` only), `DECISIONS.md`, `CLAUDE.md`
- Generate: `docs/phase-6-report.md`

- [ ] **Step 1: Generate the reports**

Run: `uv run --env-file ../.env python -m flightops report`
Expected: `docs/phase-6-report.md` is written. `docs/phase-1-report.md` and `docs/phase-3-report.md` should be unchanged (`git diff --stat docs/` shows only the new file). If phase 1 changed, it is because its whole-database tables now see the new tables. Check that the diff only reflects that.

- [ ] **Step 2: Write `P6_FINDINGS` by hand from the generated tables**, in the phase 3 style: one bold sentence per bullet, then the numbers. It must cover:
  - whether the model beats both baselines on `august` and `debby` (Brier per rank), and by how much
  - calibration on `august`: where predicted and actual diverge
  - the threshold chosen on July, and precision and recall at it on `august` and `debby`
  - the basis split: how often carrier cells are used
  - N102DN: each of the three cancelled legs with its rate and basis, and ATL→BWI not scored at rank 4
  - a `## Limits` section with: the decision moment uses the inbound's arrival delay, which includes en-route change after `t` (shared with `propagate`); BTS records the tail that flew, so a tail swap is invisible and the later schedule is partly hindsight; cancellations count as known from their scheduled departure; the stress window is whole clock hours; and, **if Task 3 Step 5 showed `debby` and `august` with few or no `10%+` pairs**, the sentence: "July's high-stress cells are fitted on a single outage, and August has no comparable disruption, so those cells are untested out of sample." If August does reach those cells, give the counts instead.

Then regenerate: `uv run --env-file ../.env python -m flightops report`.

- [ ] **Step 3: Add `DECISIONS.md` entries** in the existing format (Chose / Gave up / Why / Revisit if), dated 2026-11-23 or the day of the work:
  - **Score cancellations with a rate table, not a regression:** cells of carrier × rank × delay × stress fitted on July, with a 200-sample fallback. Gave up: smooth interactions and features beyond four. Revisit if a regression on the same pairs beats its Brier score on August.
  - **Decide at the inbound's actual departure, and measure stress from the carrier's recent cancellations, excluding the own tail:** gave up counting the inbound tail's own trouble, which would make a target its own feature. Revisit if an announcement time for cancellations becomes available.
  - **Treat a cancellation as known from its scheduled departure:** BTS gives no announcement time. Gave up: early-announced cancellations that a controller would have known about. Revisit with a source that has announcement times.
  - **Count stress over whole clock hours:** the window is the three UTC hours before `t`'s hour, so it ends 0-59 min before `t`. Gave up the most recent hour's cancellations. Why: three primary-key lookups per inbound, with the measured build time from Task 3. Revisit if the exact window changes the August Brier score, using a running count per carrier.
  - **Flag threshold:** the value and its July F1, with August precision and recall. Revisit if operators want a different trade between precision and recall.

- [ ] **Step 4: Update `CLAUDE.md`:** in Docs, add `docs/phase-6-report.md: generated cancellation-risk backtest, fitted on July and scored on August. Change it, and its hand-written findings, through pipelines/flightops/report.py.` In Status, set step 2 done and the next action to the step 3 plan (`propagate` columns and the decision log).

- [ ] **Step 5: Verify**

Run: `uv run --env-file ../.env pytest`
Expected: all pass.
Run: `uv run --env-file ../.env python -m flightops report && git diff --stat docs/`
Expected: no diff after the second generation, so the report is repeatable.

- [ ] **Step 6: Commit**

```bash
git add pipelines/flightops/report.py docs/phase-6-report.md DECISIONS.md CLAUDE.md
git commit -m "docs: phase 6 cancellation report, findings and decisions"
```
