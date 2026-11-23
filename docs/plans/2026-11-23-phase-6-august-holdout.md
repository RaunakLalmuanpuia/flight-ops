# Phase 6 step 1: August 2024 and a true phase 3 holdout. Implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** load August 2024 beside July, measure `min_turn` on July only, add p5 to the percentile grid, and score the phase 3 propagation backtest on August as a true holdout.

**Architecture:** one SQL function, `ontology.period(flight_date)`, replaces every hard-coded July window, so the fit set (`july_%`) and the score set (`august`) are named in one place. `min_turn` gains a `p5` column. The new month enters through the existing hash-keyed raw loader as new registry entries. `staging.current_delivery` is keyed by source file, so August adds to July rather than replacing it.

**Tech Stack:** Postgres 18 (Postgres.app), Python with `uv` and psycopg, pytest with fixture CSVs, Laravel + Pest for the app checks.

Spec: `docs/phase-6-plan.md`, step 1.

## Global Constraints

- Pipelines are the only writers to `raw`, `staging`, `ontology` and `dq`. Schema changes go through `db/migrations/` only.
- Reruns are idempotent: loading the same file twice changes nothing.
- Never disguise a client. If BTS or IEM refuses a scripted download, download the file by hand into `data/raw/<source>/`.
- Every non-trivial transform gets a fixture test in `pipelines/tests/fixtures/`.
- Commands run from `pipelines/` as `uv run --env-file ../.env <cmd>`. Pest runs from `web/` as `./vendor/bin/pest`.
- Tradeoffs get a `DECISIONS.md` entry in the same commit, in its format: Chose / Gave up / Why / Revisit if.
- `docs/phase-1-report.md` and `docs/phase-3-report.md` are generated. Change them only through `pipelines/flightops/report.py`.
- The fit set is `ontology.period(flight_date) LIKE 'july_%'`. The holdout is `'august'`. Choices (percentile, later the cancellation table) are made on July and scored on August, never the reverse.

## File map

| File | Change |
|---|---|
| `db/migrations/023_periods_p5.sql` | create: `ontology.period`, `min_turn.p5`, `min_turn_for` accepting 5 |
| `pipelines/flightops/rotations/min_turn.sql` | July-only fit, fills `p5` |
| `pipelines/flightops/rotations/backtest.sql` | `period` from `ontology.period`, percentiles 5/10/25/50 |
| `pipelines/flightops/report.py` | period labels, p5 in the min-turn table, later the findings prose |
| `pipelines/flightops/sources/registry.py` | August BTS and IEM entries |
| `pipelines/tests/fixtures/bts_min_turn.csv`, `bts_backtest.csv` | one August tail each |
| `pipelines/tests/test_min_turn.py`, `test_backtest.py`, `test_report.py`, `test_propagate.py`, `test_decisions.py` | p5 in fixture inserts, new expectations |
| `web/tests/Feature/HubDayTest.php` | `last_day` becomes `2024-08-31` |
| `docs/data-sources.md`, `DECISIONS.md`, `docs/case-study.md`, `docs/phase-6-plan.md`, `CLAUDE.md` | notes, entries, rechecked figures, status |

---

### Task 1: periods and a p5 min turn

**Files:**
- Create: `db/migrations/023_periods_p5.sql`
- Modify: `pipelines/flightops/rotations/min_turn.sql`
- Modify: `pipelines/tests/fixtures/bts_min_turn.csv`
- Modify: `pipelines/tests/test_min_turn.py`, `pipelines/tests/test_propagate.py`, `pipelines/tests/test_decisions.py`, `pipelines/tests/test_backtest.py:17-19`, `pipelines/tests/test_report.py:52-54`

**Interfaces:**
- Produces: `ontology.period(p_flight_date date) RETURNS text`, giving `'july_outage'` (July 19-23), `'july_normal'` (rest of July), `'august'`, or NULL. `ontology.min_turn.p5 integer NOT NULL`. `app_read.min_turn_for(carrier, percentile)` accepting 5, 10, 25 or 50.

- [ ] **Step 1: Write the failing tests**

Append to `pipelines/tests/fixtures/bts_min_turn.csv` an August DL turn. If it were counted, DL would have 4 samples:

```csv
2024-08-05,DL,N4M,11,LGA,ATL,0800,0800,0.00,1000,1000,0.00,120.00,120.00,0.00,,0.00,,,,,,,,
2024-08-05,DL,N4M,12,ATL,CLE,1030,1045,15.00,1200,1220,20.00,90.00,95.00,0.00,,0.00,,,,0.00,0.00,0.00,0.00,20.00
```

Replace the body of `pipelines/tests/test_min_turn.py` with:

```python
from flightops import pipeline


def test_min_turn_percentiles_per_carrier_and_overall(conn, load_fixture):
    load_fixture("ourairports_airports", "airports.csv")
    load_fixture("bts_ontime", "bts_min_turn.csv")
    pipeline.build(conn)
    rows = conn.execute(
        "select c.code, m.samples, m.p5, m.p10, m.p25, m.p50 from ontology.min_turn m "
        "left join ontology.carrier c using (carrier_id) order by c.code nulls last"
    ).fetchall()
    # DL samples 40/50/60; zero-cause, blank-cause and non-connecting turns are excluded.
    # N4M's 45-min turn is in August, outside the July fit, so DL keeps 3 samples.
    # All carriers adds WN's 35. p10 is 36.5 and p5 35.75, and round(numeric) takes them to 37 and 36.
    assert rows == [("DL", 3, 41, 42, 45, 50), ("WN", 1, 35, 35, 35, 35), (None, 4, 36, 37, 39, 45)]


def test_rebuild_replaces_min_turn(conn, load_fixture):
    load_fixture("ourairports_airports", "airports.csv")
    load_fixture("bts_ontime", "bts_min_turn.csv")
    pipeline.build(conn)
    pipeline.build(conn)
    assert conn.execute("select count(*) from ontology.min_turn").fetchone() == (3,)


def test_period_labels_july_outage_and_august(conn):
    days = ["2024-07-18", "2024-07-19", "2024-07-23", "2024-07-24", "2024-08-01", "2024-08-31", "2024-09-01"]
    got = conn.execute("select ontology.period(d::date) from unnest(%s::text[]) d", (days,)).fetchall()
    assert [g[0] for g in got] == [
        "july_normal", "july_outage", "july_outage", "july_normal", "august", "august", None,
    ]
```

In the four fixture inserts, add `p5` with the same value as `p10`, so a later change of `propagate`'s default from 10 to 5 leaves these tests' arithmetic alone.

`pipelines/tests/test_propagate.py:17-20` and `pipelines/tests/test_decisions.py:17-19` become:

```python
        "insert into ontology.min_turn (carrier_id, samples, p5, p10, p25, p50) "
        "select carrier_id, 500, 40, 40, 30, 60 from ontology.carrier where code = 'DL' "
        "union all select null, 1000, 45, 45, 20, 70"
```

(Keep `test_propagate.py`'s comment line about the default percentile, and change it to read: `# p5 and p10 hold 40 for DL and 45 for all carriers, so either default gives the same chain.`)

`pipelines/tests/test_backtest.py:17-19` and `pipelines/tests/test_report.py:52-54` become:

```python
        "insert into ontology.min_turn (carrier_id, samples, p5, p10, p25, p50) "
        "select carrier_id, 500, 30, 30, 40, 60 from ontology.carrier where code = 'DL' "
        "union all select null, 1000, 20, 20, 45, 70"
```

Add to `pipelines/tests/test_propagate.py`, after `test_percentile_selects_the_min_turn_column`:

```python
def test_p5_is_a_percentile(built):
    built.execute("update ontology.min_turn set p5 = 35 where carrier_id is not null")
    assert chain(built, "101", None, 5)[1] == (1, "flown", "102", -35, 35, True, None)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd pipelines && uv run --env-file ../.env pytest tests/test_min_turn.py tests/test_propagate.py -q`
Expected: FAIL. `column "p5" of relation "min_turn" does not exist` and `function ontology.period(date) does not exist`.

- [ ] **Step 3: Write the migration**

Create `db/migrations/023_periods_p5.sql`:

```sql
-- Phase 6 (docs/phase-6-plan.md): fit on July, score on August, so every period comes from one place.
-- shortcut: the months are hard-coded, so replace this with a table if a third month is loaded.
CREATE FUNCTION ontology.period(p_flight_date date) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE
        WHEN p_flight_date BETWEEN '2024-07-19' AND '2024-07-23' THEN 'july_outage'
        WHEN p_flight_date BETWEEN '2024-07-01' AND '2024-07-31' THEN 'july_normal'
        WHEN p_flight_date BETWEEN '2024-08-01' AND '2024-08-31' THEN 'august'
    END
$$;

-- p10 was the edge of phase 3's grid, so p5 is added. Refilled by the next build.
TRUNCATE ontology.min_turn;
ALTER TABLE ontology.min_turn ADD COLUMN p5 integer NOT NULL;

CREATE OR REPLACE FUNCTION app_read.min_turn_for(p_carrier_id bigint, p_percentile integer) RETURNS integer
LANGUAGE plpgsql STABLE SET search_path = pg_catalog, pg_temp AS $$
DECLARE v_turn integer;
BEGIN
    IF p_percentile NOT IN (5, 10, 25, 50) THEN
        RAISE EXCEPTION 'percentile must be 5, 10, 25 or 50, got %', p_percentile USING ERRCODE = 'invalid_parameter_value';
    END IF;
    SELECT CASE p_percentile WHEN 5 THEN m.p5 WHEN 10 THEN m.p10 WHEN 25 THEN m.p25 WHEN 50 THEN m.p50 END INTO v_turn
    FROM ontology.min_turn m
    WHERE m.carrier_id = p_carrier_id AND m.samples >= 200
       OR m.carrier_id IS NULL
    ORDER BY m.carrier_id NULLS LAST
    LIMIT 1;
    IF v_turn IS NULL THEN
        RAISE EXCEPTION 'ontology.min_turn has no all-carrier row (carrier_id NULL)' USING ERRCODE = 'no_data_found';
    END IF;
    RETURN v_turn;
END
$$;
```

`CREATE OR REPLACE` keeps the existing `REVOKE ... FROM PUBLIC` from migration 017.

- [ ] **Step 4: Fit `min_turn` on July and fill p5**

Replace `pipelines/flightops/rotations/min_turn.sql` with:

```sql
TRUNCATE ontology.min_turn;

-- A late_aircraft cause on the next leg means the aircraft was the constraint, so its turn is near the minimum.
WITH turn AS (
    SELECT n.carrier_id, extract(epoch FROM n.actual_dep_utc - p.actual_arr_utc) / 60 AS minutes
    FROM ontology.rotation_leg r
    JOIN ontology.flight n ON n.flight_id = r.flight_id
    JOIN ontology.flight p ON p.flight_id = r.prev_flight_id
    JOIN ontology.delay d ON d.flight_id = n.flight_id AND d.cause = 'late_aircraft'
    WHERE r.connects AND r.touched_atl
      AND n.actual_dep_utc >= p.actual_arr_utc  -- an overlap is a data error, not a turn
      AND ontology.period(n.flight_date) LIKE 'july_%'  -- fit on July only, so August scores out of sample
)
INSERT INTO ontology.min_turn (carrier_id, samples, p5, p10, p25, p50)
SELECT carrier_id, count(*),
       round(percentile_cont(0.05) WITHIN GROUP (ORDER BY minutes)::numeric),
       round(percentile_cont(0.10) WITHIN GROUP (ORDER BY minutes)::numeric),
       round(percentile_cont(0.25) WITHIN GROUP (ORDER BY minutes)::numeric),
       round(percentile_cont(0.50) WITHIN GROUP (ORDER BY minutes)::numeric)
FROM turn
GROUP BY GROUPING SETS ((carrier_id), ())
HAVING count(*) > 0;  -- the empty grand-total row has no percentiles
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd pipelines && uv run --env-file ../.env pytest tests/test_min_turn.py tests/test_propagate.py tests/test_decisions.py -q`
Expected: PASS.

- [ ] **Step 6: Run the full suite**

Run: `cd pipelines && uv run --env-file ../.env pytest -q`
Expected: all PASS. The backtest still runs 10/25/50 and labels `normal`/`outage` until Task 2.

- [ ] **Step 7: Commit**

```bash
git add db/migrations/023_periods_p5.sql pipelines/flightops/rotations/min_turn.sql pipelines/tests
git commit -m "feat: periods function, July-only min turn with p5"
```

---

### Task 2: backtest and report by period, with p5

**Files:**
- Modify: `pipelines/flightops/rotations/backtest.sql:1-12`
- Modify: `pipelines/flightops/report.py` (the `P3_SECTIONS` min-turn, percentile-choice and what-the-model-misses queries, and `P3_HEADER`'s last sentence)
- Modify: `pipelines/tests/fixtures/bts_backtest.csv`, `pipelines/tests/test_backtest.py`, `pipelines/tests/test_report.py`
- Leave `db/migrations/018_propagation_backtest.sql` alone: applied migrations are never edited, so its `period` column comment goes stale.

**Interfaces:**
- Consumes: `ontology.period(date)` and `min_turn.p5` from Task 1.
- Produces: `ontology.propagation_backtest.period` holding `july_normal`, `july_outage` or `august`, and `percentile` holding 5, 10, 25 or 50.

- [ ] **Step 1: Write the failing tests**

Append to `pipelines/tests/fixtures/bts_backtest.csv` an August copy of 101→102:

```csv
2024-08-10,DL,N5B,501,LGA,ATL,0800,0900,60.00,1000,1100,60.00,120.00,120.00,0.00,,0.00,,,,60.00,0.00,0.00,0.00,0.00
2024-08-10,DL,N5B,502,ATL,CLE,1100,1145,45.00,1230,1315,45.00,90.00,90.00,0.00,,0.00,,,,0.00,0.00,0.00,0.00,45.00
```

In `pipelines/tests/test_backtest.py`, change `test_backtest_scores_pairs_from_rotation_legs`'s expected list: `"normal"` becomes `"july_normal"`, `"outage"` becomes `"july_outage"`, and add one row after the `"401"` row:

```python
        ("501", "502", 1, "august", 60, 40, 45, 45, False),  # 11:00 arrival + DL p25 40 against an 11:00 departure
```

Change `test_rebuild_replaces_backtest`'s count from `(24,)` to `(36,)`, with this comment: `# 9 pairs x 4 percentiles`.

In `pipelines/tests/test_report.py`:

```python
def test_phase3_counts_cancelled_legs_in_the_gap_and_swaps(backtested):
    text = phase3(backtested)
    # july_normal: 101, 102, 104, 301 late; july_outage: 201 (cancelled 204 in its gap), 401, 402; august: 501, 502.
    assert "| july_normal | 4 | 0 | 0.0 | 7 | 0 |" in text
    assert "| july_outage | 3 | 1 | 33.3 | 1 | 1 |" in text
    assert "| august | 2 | 0 | 0.0 | 1 | 0 |" in text


def test_phase3_scores_against_both_baselines(backtested):
    text = phase3(backtested)
    # depth 1, late_aircraft reported only on 102 (and 502): model at p10 predicts 30 vs 45, zero 45, carry 60.
    assert "| july_normal | 1 | 1 | 15.0 | 45.0 | 15.0 | 100.0 | 100.0 | 100.0 |" in text
    assert "| august | 1 | 1 | 15.0 | 45.0 | 15.0 | 100.0 | 100.0 | 100.0 |" in text


def test_phase3_min_turn_shows_p5(backtested):
    assert "| carrier | samples | p5 | p10 | p25 | p50 |" in phase3(backtested)
```

(`test_phase3_counts_cancelled_legs_in_the_gap_and_swaps` and `test_phase3_scores_against_both_baselines` replace the existing functions of those names. `test_phase3_min_turn_shows_p5` is new.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd pipelines && uv run --env-file ../.env pytest tests/test_backtest.py tests/test_report.py -q`
Expected: FAIL. The rows still say `normal` and `outage`, the count is 27 (9 pairs × 3), and the min-turn header has no p5.

- [ ] **Step 3: Label the backtest by period and add p5**

In `pipelines/flightops/rotations/backtest.sql`, the `late` CTE's period line and the percentile list become:

```sql
WITH late AS (
    SELECT f.flight_id, r.tail_number, r.leg_seq, f.sched_dep_utc, f.arr_delay_min,
           ontology.period(f.flight_date) AS period  -- NULL outside the loaded months fails the NOT NULL column loudly
    FROM ontology.rotation_leg r
    JOIN ontology.flight f USING (flight_id)
    WHERE r.touched_atl AND f.arr_delay_min >= 15
      -- propagate raises without an all-carrier min turn, and a build with no late_aircraft samples has nothing to score.
      AND EXISTS (SELECT 1 FROM ontology.min_turn WHERE carrier_id IS NULL)
),
pct AS (SELECT unnest(ARRAY[5, 10, 25, 50]) AS percentile),
```

The rest of the file is unchanged.

- [ ] **Step 4: Update the report queries**

In `pipelines/flightops/report.py`:

The min-turn section's description and SQL:

```python
        "Min turn",
        "Measured per carrier from July turns where the next leg reported `late_aircraft` minutes. "
        "August is not used, so it scores the turns out of sample. A blank carrier is the all-carrier row.",
        "SELECT c.code AS carrier, m.samples, m.p5, m.p10, m.p25, m.p50 FROM ontology.min_turn m "
        "LEFT JOIN ontology.carrier c USING (carrier_id) ORDER BY m.samples DESC",
```

The percentile choice: the description becomes `"Depth-1 `late_aircraft` error on July's normal days, where it was reported. The lowest `mae_model` is chosen, and August is not looked at."`, and its `WHERE` line becomes:

```sql
WHERE period = 'july_normal' AND depth = 1 AND actual_late_aircraft IS NOT NULL
```

In "What the model misses", the first line of the `late` CTE becomes:

```sql
    SELECT ontology.period(f.flight_date) AS period,
```

In `P3_HEADER`, replace the title with `# Phase 3 propagation backtest: July and August 2024`, and replace the last sentence (`The outage period is July 19-23 by the late leg's flight date.`) with:

```
Periods come from the late leg's flight date: `july_outage` is July 19-23, `july_normal` is the rest of July, and `august` is the holdout. Min turns and the percentile are chosen on July only.
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd pipelines && uv run --env-file ../.env pytest -q`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add pipelines/flightops/rotations/backtest.sql pipelines/flightops/report.py pipelines/tests
git commit -m "feat: backtest scored by period, with p5 in the grid"
```

---

### Task 3: load August into the real database

**Files:**
- Modify: `pipelines/flightops/sources/registry.py`
- Modify: `web/tests/Feature/HubDayTest.php:17`
- Modify: `docs/data-sources.md` (an August section under BTS and IEM)
- Modify: `DECISIONS.md`

**Interfaces:**
- Consumes: Tasks 1 and 2.
- Produces: a `flightops` database holding July and August 2024, built with migration 023.

- [ ] **Step 1: Add August to the registry**

In `pipelines/flightops/sources/registry.py`, `RAW_FILES` gains these after the July entries of the same table:

```python
    RawFile("bts", "bts_ontime", "*2024_8.csv"),
    RawFile("iem", "iem_metar", "metar_katl_2024_08.csv"),
    RawFile("iem", "iem_taf", "taf_katl_2024_08.csv"),
```

The weather comment becomes:

```python
# FAA is absent on purpose: it answers scripted requests with 403, so it is a hand download.
# Weather files cover June 30 to August 1 and August 2 to September 1 UTC. IEM's end date is exclusive
# (the July file ends 2024-08-01 23:55), so the two never overlap, as staging.metar's primary key requires.
```

`DOWNLOADS` gains:

```python
    Download(
        "https://transtats.bts.gov/PREZIP/"
        "On_Time_Reporting_Carrier_On_Time_Performance_1987_present_2024_8.zip",
        DATA / "bts" / "ontime_2024_8.zip",
        unzip=True,
    ),
    Download(
        f"{_IEM}/asos.py?station=ATL&data=metar&year1=2024&month1=8&day1=2"
        "&year2=2024&month2=9&day2=2&tz=Etc/UTC&format=onlycomma&latlon=no"
        "&missing=empty&trace=empty&report_type=1&report_type=3&report_type=4",
        DATA / "iem" / "metar_katl_2024_08.csv",
    ),
    Download(
        f"{_IEM}/taf.py?station=KATL&sts=2024-08-02T00:00Z&ets=2024-09-02T00:00Z&fmt=csv",
        DATA / "iem" / "taf_katl_2024_08.csv",
    ),
```

The registry is configuration with no logic, so it has no test of its own. Step 3's load is its check.

- [ ] **Step 2: Fetch**

Run: `cd pipelines && uv run --env-file ../.env python -m flightops fetch`
Expected: `fetched ontime_2024_8.zip`, `fetched metar_katl_2024_08.csv` and `fetched taf_katl_2024_08.csv`, with the July files `present`. If BTS answers with an error page or 403, stop: download the August 2024 zip by hand from the BTS PREZIP page into `data/raw/bts/` and unzip it there. Then confirm `ls data/raw/bts/*2024_8.csv` shows exactly one file.

- [ ] **Step 3: Record July's figures before the build, then migrate, load and build, timed**

Before anything changes, run `psql -h localhost flightops -Atc "select count(*) from ontology.rotation_leg where touched_atl"` and record it as July's old ATL-tail leg count (the database holds only July now).

Migration 023 truncates `min_turn`, so the app's FlightImpact page raises until the build finishes. Don't run the app in between.

Run: `cd pipelines && uv run --env-file ../.env python -m flightops migrate && uv run --env-file ../.env python -m flightops load && time uv run --env-file ../.env python -m flightops build`
Expected: `applied: ['023_periods_p5.sql']`. The load reports the three August files, with July `(already loaded)`. The build passes its blocking checks. Write down the build's wall time: the backtest was 111 s for 3 percentiles on July, and it now runs 4 percentiles on two months.

If a blocking check fails, the most likely cause is an airport code that changed (`airports_have_timezones`). Per CLAUDE.md, add a row to `staging.airport_code_alias` in a new migration. Don't guess.

- [ ] **Step 4: Measure what the load changed**

Run each query with `psql -h localhost flightops -c "<query>"` and paste the results into a scratch note for Step 7:

```sql
SELECT ontology.period(flight_date) AS period, count(*) AS flights, count(*) FILTER (WHERE cancelled) AS cancelled
FROM ontology.flight GROUP BY 1 ORDER BY 1;

SELECT count(*) AS flights, count(DISTINCT (carrier_id, flight_number, origin_airport_id, sched_dep_utc)) AS natural_keys
FROM ontology.flight;

SELECT period, count(DISTINCT late_flight_id) AS late_legs FROM ontology.propagation_backtest
WHERE percentile = 10 GROUP BY 1 ORDER BY 1;

SELECT count(*) FILTER (WHERE r.touched_atl) AS july_atl_tail_legs_now
FROM ontology.rotation_leg r JOIN ontology.flight f USING (flight_id)
WHERE ontology.period(f.flight_date) LIKE 'july_%';

SELECT decision_id, match_label FROM app_read.decision_review ORDER BY decision_id;
```

Expected:
- July still has 634,613 flights.
- `flights` equals `natural_keys`. If it doesn't, stop and tell the user, because the decision log re-matches on that key ("Keep the decision log append-only").
- The three walkthrough decisions keep their labels, and none reads `flight not found after rebuild`.
- `july_atl_tail_legs_now` is at least Step 3's old count. It only grows, from tails that touched ATL only in August. Record both.

If `decision_review` has no `match_label` column, run `\d app_read.decision_review` and use the label column it shows.

- [ ] **Step 5: Fix the app's range test and run the app's checks**

`web/tests/Feature/HubDayTest.php:17`:

```php
        ->where('range', ['first_day' => '2024-07-01', 'last_day' => '2024-08-31'])
```

Run: `cd web && ./vendor/bin/pest && npm test`
Expected: PASS. A failing July assertion other than the range means a July number moved. Check it against Step 4's measurements before changing the expected value, and record each change for Step 7.

- [ ] **Step 6: Run the pipeline suite**

Run: `cd pipelines && uv run --env-file ../.env pytest -q`
Expected: PASS. It builds its own `flightops_test` database, so this confirms the registry change didn't break the loaders.

- [ ] **Step 7: Record it**

In `docs/data-sources.md`, add a short "August 2024" note under the BTS section (row count, cancellations, the download method used) and under IEM (span, row count). Use Step 4's numbers.

Add to `DECISIONS.md`:

```markdown
## 2026-11-23: Load August 2024 before modelling cancellations
- **Chose:** August 2024 beside July, with `min_turn` and every later choice fitted on July and scored on August, named by `ontology.period`.
- **Gave up:** a quicker cancellation phase scored on July's outage alone, and stable whole-database figures: the build now takes <measured> s, and reports covering all loaded data moved.
- **Why:** July contains the outage, so any score drawn from July alone is in-sample. August gives a holdout for normal days, and possibly a second disruption.
- **Revisit if:** a third month is loaded. Then `ontology.period`'s hard-coded dates become a table.

## 2026-11-23: Count a tail as touching ATL across all loaded months
- **Chose:** `rotation_leg.touched_atl` stays a property of the tail over all loaded data, so a tail that touched ATL only in August counts in July too.
- **Gave up:** July figures that stay fixed when a month is added. July's ATL-tail legs went from <old> to <new>.
- **Why:** a month boundary shouldn't cut a rotation, and a per-month flag would break the July 31 to August 1 chain the national load exists to keep.
- **Revisit if:** a report needs per-month ATL-tail counts. Then filter by `ontology.period` in that report, not in the flag.
```

Fill each `<measured>`, `<old>` and `<new>` with Step 3's and Step 4's numbers before committing.

- [ ] **Step 8: Commit**

```bash
git add pipelines/flightops/sources/registry.py web/tests/Feature/HubDayTest.php docs/data-sources.md DECISIONS.md
git commit -m "feat: load August 2024 beside July"
```

---

### Task 3b (added after Task 3): touched_atl per month, and the debby period

Task 3 found that the whole-data `touched_atl` made July's ATL-tail legs grow 17% (377,530 to 440,734). At the Task 4 checkpoint the user chose a per-month flag and a `debby` period of August 2-6. Both land in one rebuild. The brief is `.superpowers/sdd/task-3b-brief.md`: per-month `touched_atl` in `rotations.sql` with a fixture test, migration 024 for `debby`, and July's ATL-tail legs back to 377,530. The user also accepted the 1,100 s build for now.

### Task 4: checkpoint. Is there a Debby period? (resolved by Task 3b)

**Files:** none until the user decides. Then, if a window is chosen: create `db/migrations/024_debby_period.sql` and modify `pipelines/tests/test_min_turn.py`.

- [ ] **Step 1: Measure ATL cancellations by August day**

```sql
SELECT f.flight_date, count(*) AS atl_flights, count(*) FILTER (WHERE f.cancelled) AS cancelled,
       count(*) FILTER (WHERE f.cancellation_code = 'B') AS weather_cancelled
FROM ontology.flight f
JOIN ontology.airport a ON a.iata_code = 'ATL' AND a.airport_id IN (f.origin_airport_id, f.dest_airport_id)
WHERE ontology.period(f.flight_date) = 'august'
GROUP BY 1 ORDER BY 1;
```

A candidate window is consecutive days with `cancelled` at 3× August's median daily cancellations or more.

- [ ] **Step 2: Stop and show the user the table and any candidate window.** Ask whether to add a `debby` period. Don't write the migration without their answer.

- [ ] **Step 3: If yes, write the failing test**

Add to `pipelines/tests/test_min_turn.py`, using the window the user approved (shown here as `<first>` to `<last>`):

```python
def test_debby_period_sits_inside_august(conn):
    got = conn.execute(
        "select ontology.period(%s::date), ontology.period(%s::date), ontology.period('2024-08-31')",
        ("<first>", "<last>"),
    ).fetchone()
    assert got == ("debby", "debby", "august")
```

Run: `cd pipelines && uv run --env-file ../.env pytest tests/test_min_turn.py -q`
Expected: FAIL, because the days return `'august'`.

- [ ] **Step 4: Write the migration**

`db/migrations/024_debby_period.sql`:

```sql
-- Window from ATL cancellations by day (docs/phase-6-plan.md, step 1 notes). Still a holdout: not 'july_%'.
CREATE OR REPLACE FUNCTION ontology.period(p_flight_date date) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE
        WHEN p_flight_date BETWEEN '2024-07-19' AND '2024-07-23' THEN 'july_outage'
        WHEN p_flight_date BETWEEN '2024-07-01' AND '2024-07-31' THEN 'july_normal'
        WHEN p_flight_date BETWEEN '<first>' AND '<last>' THEN 'debby'
        WHEN p_flight_date BETWEEN '2024-08-01' AND '2024-08-31' THEN 'august'
    END
$$;
```

Run: `cd pipelines && uv run --env-file ../.env pytest -q`, then `uv run --env-file ../.env python -m flightops migrate && uv run --env-file ../.env python -m flightops build`
Expected: PASS, and the backtest now has a `debby` period.

- [ ] **Step 5: Record and commit**

Either way, add a row to the Notes table in `docs/phase-6-plan.md` with the daily counts that decided it. If there's no window, the row says so, and the cancellation backtest's limits will say August can't test the high-stress cells.

```bash
git add docs/phase-6-plan.md db/migrations pipelines/tests
git commit -m "docs: whether August holds a second disruption"
```

---

### Task 5: choose the percentile on July and score it on August

**Files:**
- Conditional create: `db/migrations/02N_propagate_default_p5.sql` (next free number)
- Conditional modify: `pipelines/flightops/report.py:192` (`PERCENTILE`)
- Modify: `DECISIONS.md`

- [ ] **Step 1: Read the choice**

Run: `cd pipelines && uv run --env-file ../.env python -m flightops report`, then read the "Percentile choice" table in `docs/phase-3-report.md`.

- [ ] **Step 2: If p10 still has the lowest `mae_model`, skip to Step 5.**

- [ ] **Step 3: If p5 is lowest, change the default**

Create the migration by copying `db/migrations/019_propagate_default.sql` in full. Change only:
- the header comment, to `-- The July-fitted backtest (docs/phase-3-report.md) chose p5 on July's normal days. Same function as 019 except the default.`
- `p_percentile integer DEFAULT 10` becomes `p_percentile integer DEFAULT 5`

Set `PERCENTILE = 5` in `pipelines/flightops/report.py`.

`test_report.py::test_report_percentile_is_propagates_default` checks that the two agree. The fixture inserts give p5 the same values as p10, so no other test changes.

- [ ] **Step 4: Verify**

Run: `cd pipelines && uv run --env-file ../.env pytest -q && uv run --env-file ../.env python -m flightops migrate && uv run --env-file ../.env python -m flightops report`, then `cd web && ./vendor/bin/pest`
Expected: PASS. Pest's FlightImpact and decision tests use the default percentile, so a failure there means a July value moved with the turn. Update the expectation only after checking the new chain by hand with `select * from app_read.propagate(<flight_id>)`.

- [ ] **Step 5: Record the result**

Add to `DECISIONS.md`, filling in the measured values:

```markdown
## 2026-11-23: Choose the min-turn percentile on July and score it on August
- **Chose:** p<chosen>, the lowest depth-1 `late_aircraft` error on July's normal days (<mae> min, against <others>), with p5 added to the grid. `min_turn` is measured on July only.
- **Gave up:** <for p5: a more cautious turn, with recall falling from x to y | for p10: nothing changes in the app>.
- **Why:** choosing and scoring on the same month made phase 3's numbers in-sample. On August the model's depth-1 error is <august mae>, against <predict-0> and <carry>.
- **Revisit if:** <p5 wins: percentiles below p5 | p10 wins: never, unless a later month disagrees>.
```

```bash
git add DECISIONS.md db/migrations pipelines/flightops/report.py docs/phase-3-report.md
git commit -m "feat: min-turn percentile chosen on July, scored on August"
```

---

### Task 6: reports, case study and status

**Files:**
- Modify: `pipelines/flightops/report.py` (`HEADER`, `FINDINGS`, the "Reported checks" description, `P3_FINDINGS`, the limits)
- Regenerate: `docs/phase-1-report.md`, `docs/phase-3-report.md`
- Modify: `docs/case-study.md`, `docs/phase-6-plan.md`, `CLAUDE.md`

- [ ] **Step 1: Regenerate and diff**

Run: `cd pipelines && uv run --env-file ../.env python -m flightops report && git diff --stat docs/`
Then read `git diff docs/phase-1-report.md docs/phase-3-report.md` table by table.

- [ ] **Step 2: Rewrite the phase 1 report's fixed prose**

In `pipelines/flightops/report.py`:
- `HEADER`'s title becomes `# Data-quality report: July and August 2024`.
- The "Reported checks" description becomes: `These don't block. Each is a whole-database total, so thresholds wait for per-month checks: see DECISIONS.md, "Hold off on thresholds for reported checks".`
- In `FINDINGS`, update every figure that comes from a whole-database table (rotations connecting, tail match rate, unresolved flights, the weather cross-check percentages) to the regenerated values, and say "across July and August" where a figure now spans both. Findings tied to dated tables (July 19-23, OpenSky July 15-27, N102DN) stay as they are.
- The limit `One month is not a baseline, ...` becomes: `**Two months, one with an outage,** are still a thin baseline, so reported checks have no thresholds yet.`

- [ ] **Step 3: Rewrite the phase 3 findings and limits**

Rewrite `P3_FINDINGS` from the regenerated tables. Every finding names its period, and the headline numbers are `august`'s. Each figure must appear in a table of the regenerated report. Keep the N102DN findings, which are July examples. Replace the `One month` limit with: `**Fit on July, scored on August.** The outage is inside the fit month, so outage-period scores are not out of sample. August is.`

Run: `cd pipelines && uv run --env-file ../.env python -m flightops report && uv run --env-file ../.env pytest tests/test_report.py -q`
Expected: PASS, and no `None` in either report.

- [ ] **Step 4: Recheck the case study**

For each figure in `docs/case-study.md`, follow its link and confirm the number is still there. The ones expected to move are the whole-database ones (98.84% connecting, 98.8% tail match, 7,683 unresolved, 81.5% and 24.9% in the weather cross-check) and every phase 3 score (13.0 / 48.4 / 36.1, 18.4 / 57.9 / 60.0, 90.1%, 74.8%, 89.0%, 30.5%, 117,818, 519 of 333,556, 17.5 and 33.8, the turn percentile). Update each one. Where the case study claims "in sample" or "the outage held out" (the "What the model can't see" limits and "What I'd do next" item 1), rewrite it to say that turns and percentile are fitted on July and scored on August. The July-dated figures (3,208, 899, 895, N102DN, OpenSky 38-52%, 0.996) should not move. If one did, stop and find out why before editing.

- [ ] **Step 5: Update the plan's notes and the status**

Add rows to the Notes table in `docs/phase-6-plan.md` for: August flights and cancellations, the build time, the natural key check, July's ATL-tail legs before and after, and the percentile result on July against August.

In `CLAUDE.md`'s Status:
- Current phase: 6, step 1 done
- Next action: write the step 2 task plan (rate table and backtest) with `superpowers:writing-plans`
- Built so far: the database holds July and August 2024
- Docs: `docs/phase-1-report.md` is now the data-quality report for all loaded data, and `docs/phase-3-report.md` covers both months

- [ ] **Step 6: Final verification**

Run: `cd pipelines && uv run --env-file ../.env pytest -q`, then `cd web && ./vendor/bin/pest && npm test && npm run build`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add pipelines/flightops/report.py docs/ CLAUDE.md
git commit -m "docs: reports and case study on the August holdout"
```
