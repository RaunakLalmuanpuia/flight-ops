# Phase 3, step 3: backtest, percentile choice and report — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** score `app_read.propagate` against what actually happened in July 2024, pick the min-turn percentile from it, and publish `docs/phase-3-report.md` with the N102DN worked example.

**Architecture:** a new pipeline-built table `ontology.propagation_backtest` (migration 018), filled by `rotations/backtest.sql` as the last step of `pipeline.build`, after `min_turn`. It calls `propagate` once per late leg and percentile, and scores pairs taken from `rotation_leg`, so legs the model never reached still count. `report.py` gains a second report from the same `render`, with metrics computed from the table. Design: `docs/phase-3-plan.md`, Backtest section.

**Tech Stack:** Postgres 18 SQL, Python 3 + psycopg + pytest (run with `uv`).

## Global Constraints

- **Late leg:** a `rotation_leg` row with `touched_atl` whose flight has `arr_delay_min >= 15`. July has 117,818, 27,050 of them in the outage window.
- **Scored pairs** come from `rotation_leg` at `leg_seq + k`, for k = 1..3, with a LEFT JOIN to propagate's `flown` rows. A leg after an `absorbed` stop scores as predicted 0. A `break` or `limit` row, and every pair past one, is excluded. Never score only the rows propagate returns.
- **`late_aircraft` target:** reported only when the scored leg's `arr_delay_min >= 15`, and then a missing `ontology.delay` row means 0. Otherwise it is NULL and excluded, never scored as zero.
- **Departure delay target:** `dep_delay_min` is signed (298,639 early departures in July), and predictions are never negative, so metrics use `greatest(actual_dep_delay, 0)`. The table stores the signed value.
- **Period:** `outage` when the late leg's `flight_date` is July 19-23, otherwise `normal`.
- **Baselines:** predict 0, and full carry (predict the late leg's arrival delay at every depth).
- **Metrics:** MAE in minutes. Precision and recall for at risk (predicted >= 15) against actual >= 15.
- **Percentile choice:** lowest depth-1 `late_aircraft` MAE on the `normal` period. The outage is reported as held out, with the caveat that `min_turn` was measured on all of July.
- **Swap:** a scored pair whose scored leg's `sched_dep_utc` is before the late leg's.
- **Cancelled in gap:** a cancelled flight on the late leg's tail with `sched_dep_utc` strictly between the late leg's and its next flown leg's (`leg_seq + 1`). Same rule as `propagate`.
- Find N102DN's leg by tail, date and origin (`N102DN`, `2024-07-19`, `DEN`), never by the surrogate `flight_id` 371994, which can change on a rebuild.
- Run all commands from `pipelines/`. Tests: `uv run --env-file ../.env pytest`.

## Choices for review

1. **The table lives in `ontology`, not `app_read`** as `phase-3-plan.md` names it. `app_read` holds the app's views, and its default privileges would grant the table to `flightops_app`. Step 4's page doesn't read the backtest. The plan's data-layer row gets renamed in Task 3.
2. **The backtest runs inside `pipeline.build`.** That adds about 2 minutes to every build (353k propagate calls at about 0.3 ms). A separate `backtest` command would avoid that, but then the table could go stale against `min_turn`.
3. **The table stores the late leg's arrival delay, not the baselines.** Predict-0 is a constant and full carry is that column, so the report computes both.

## Files

| File | Change |
|---|---|
| `db/migrations/018_propagation_backtest.sql` | create the table |
| `pipelines/flightops/rotations/backtest.sql` | fill it |
| `pipelines/flightops/pipeline.py` | run it after `min_turn.sql` |
| `pipelines/flightops/resolve/ontology.sql:1` | add the table to `TRUNCATE`, since it references `ontology.flight` |
| `pipelines/tests/fixtures/bts_backtest.csv` | new fixture |
| `pipelines/tests/test_backtest.py` | new tests |
| `pipelines/flightops/report.py` | `REPORTS`, phase-3 sections, `render` takes a report |
| `pipelines/flightops/__main__.py` | write both reports |
| `pipelines/tests/test_report.py` | phase-3 tests |
| `db/migrations/019_propagate_default.sql` | only if the backtest picks p10 or p50 |
| `docs/phase-3-report.md` | generated |
| `DECISIONS.md`, `docs/phase-3-plan.md`, `CLAUDE.md` | decisions, notes, status |

---

### Task 1: `ontology.propagation_backtest`

**Files:**
- Create: `db/migrations/018_propagation_backtest.sql`
- Create: `pipelines/flightops/rotations/backtest.sql`
- Modify: `pipelines/flightops/pipeline.py` (`build`)
- Modify: `pipelines/flightops/resolve/ontology.sql:1`
- Create: `pipelines/tests/fixtures/bts_backtest.csv`
- Create: `pipelines/tests/test_backtest.py`

**Interfaces:**
- Consumes: `app_read.propagate(flight_id, NULL, percentile)` from migration 017, `ontology.min_turn`, `ontology.rotation_leg`.
- Produces: table `ontology.propagation_backtest(late_flight_id bigint, scored_flight_id bigint, depth int, percentile int, period text, late_arr_delay int, predicted_dep_delay int, actual_dep_delay int, actual_late_aircraft int NULL, swapped bool)`, keyed by `(late_flight_id, depth, percentile)`.

- [ ] **Step 1: Write the fixture** `pipelines/tests/fixtures/bts_backtest.csv`. All Eastern airports, all DL. Cases: N1B (July 10) carries one leg, is absorbed, then scores two more legs as 0, and its fifth leg is past depth 3 from 101. N2B (July 20) breaks at once and has a cancelled leg in the gap. N3B hits the 24h limit. N4B (July 21) flies a swapped leg.

```csv
flightdate,reporting_airline,tail_number,flight_number_reporting_airline,origin,dest,crsdeptime,deptime,depdelay,crsarrtime,arrtime,arrdelay,crselapsedtime,actualelapsedtime,cancelled,cancellationcode,diverted,divreacheddest,div1airport,div1wheelson,carrierdelay,weatherdelay,nasdelay,securitydelay,lateaircraftdelay
2024-07-10,DL,N1B,101,LGA,ATL,0800,0900,60.00,1000,1100,60.00,120.00,120.00,0.00,,0.00,,,,60.00,0.00,0.00,0.00,0.00
2024-07-10,DL,N1B,102,ATL,CLE,1100,1145,45.00,1230,1315,45.00,90.00,90.00,0.00,,0.00,,,,0.00,0.00,0.00,0.00,45.00
2024-07-10,DL,N1B,103,CLE,ATL,1500,1455,-5.00,1630,1625,-5.00,90.00,90.00,0.00,,0.00,,,,,,,,
2024-07-10,DL,N1B,104,ATL,IAD,1700,1720,20.00,1830,1850,20.00,90.00,90.00,0.00,,0.00,,,,20.00,0.00,0.00,0.00,0.00
2024-07-10,DL,N1B,105,IAD,ATL,2000,2000,0.00,2130,2130,0.00,90.00,90.00,0.00,,0.00,,,,,,,,
2024-07-20,DL,N2B,201,LGA,ATL,0800,0900,60.00,1000,1100,60.00,120.00,120.00,0.00,,0.00,,,,60.00,0.00,0.00,0.00,0.00
2024-07-20,DL,N2B,204,ATL,LGA,1030,,,1230,,,120.00,,1.00,A,0.00,,,,,,,,
2024-07-20,DL,N2B,202,CLE,ATL,1300,1300,0.00,1430,1430,0.00,90.00,90.00,0.00,,0.00,,,,,,,,
2024-07-20,DL,N2B,203,ATL,LGA,1600,1600,0.00,1800,1800,0.00,120.00,120.00,0.00,,0.00,,,,,,,,
2024-07-10,DL,N3B,301,ATL,LGA,0800,0900,60.00,1000,1100,60.00,120.00,120.00,0.00,,0.00,,,,60.00,0.00,0.00,0.00,0.00
2024-07-11,DL,N3B,302,LGA,ATL,1200,1200,0.00,1400,1400,0.00,120.00,120.00,0.00,,0.00,,,,,,,,
2024-07-21,DL,N4B,401,LGA,ATL,1200,1300,60.00,1400,1500,60.00,120.00,120.00,0.00,,0.00,,,,60.00,0.00,0.00,0.00,0.00
2024-07-21,DL,N4B,402,ATL,CLE,1100,1600,300.00,1230,1730,300.00,90.00,90.00,0.00,,0.00,,,,0.00,0.00,0.00,0.00,300.00
```

- [ ] **Step 2: Write the failing tests** in `pipelines/tests/test_backtest.py`. With DL p25 = 40: 101→102 is predicted 1100 + 40 − 1100 = 40. 102's predicted arrival is 1310, so 103 is absorbed, and 104 is scored as 0 past it. 103 departed 5 early, and its arrival delay was under 15, so `late_aircraft` is NULL. 104 reported 20 min of carrier delay and no `late_aircraft`, so its value is 0. 401→402: 1500 + 40 against a 1100 schedule is 280.

```python
from flightops import pipeline

COLS = """l.flight_number, s.flight_number, b.depth, b.period, b.late_arr_delay, b.predicted_dep_delay,
          b.actual_dep_delay, b.actual_late_aircraft, b.swapped"""


def rows(conn, percentile):
    return conn.execute(
        f"select {COLS} from ontology.propagation_backtest b "
        "join ontology.flight l on l.flight_id = b.late_flight_id "
        "join ontology.flight s on s.flight_id = b.scored_flight_id "
        "where b.percentile = %s order by 1, 3",
        (percentile,),
    ).fetchall()


def test_backtest_scores_pairs_from_rotation_legs(built):
    assert rows(built, 25) == [
        ("101", "102", 1, "normal", 60, 40, 45, 45, False),
        ("101", "103", 2, "normal", 60, 0, -5, None, False),  # absorbed here
        ("101", "104", 3, "normal", 60, 0, 20, 0, False),     # past absorbed, propagate returned no row
        ("102", "103", 1, "normal", 45, 0, -5, None, False),
        ("102", "104", 2, "normal", 45, 0, 20, 0, False),
        ("102", "105", 3, "normal", 45, 0, 0, None, False),
        ("104", "105", 1, "normal", 20, 0, 0, None, False),
        ("401", "402", 1, "outage", 60, 280, 300, 300, True),
        # 201: break at depth 1, so 202 and 203 are excluded. 301: limit. 101→105 is depth 4.
    ]


def test_each_percentile_is_scored(built):
    assert rows(built, 50)[0][5] == 60
    assert rows(built, 10)[0][5] == 30


def test_rebuild_replaces_backtest(built):
    pipeline.run_sql(built, "rotations/backtest.sql")
    assert built.execute("select count(*) from ontology.propagation_backtest").fetchone() == (24,)


def test_no_min_turn_leaves_backtest_empty_instead_of_raising(built):
    built.execute("truncate ontology.min_turn")
    pipeline.run_sql(built, "rotations/backtest.sql")  # propagate would raise NoDataFound without the guard
    assert built.execute("select count(*) from ontology.propagation_backtest").fetchone() == (0,)
```

Add this fixture at the top of the same file. The fixture is too small to measure turns, so it fixes them as `test_propagate.py` does and rebuilds the backtest:

```python
import pytest


@pytest.fixture
def built(conn, load_fixture):
    load_fixture("ourairports_airports", "airports.csv")
    load_fixture("bts_ontime", "bts_backtest.csv")
    pipeline.build(conn)
    conn.execute("truncate ontology.min_turn")
    conn.execute(
        "insert into ontology.min_turn (carrier_id, samples, p10, p25, p50) "
        "select carrier_id, 500, 30, 40, 60 from ontology.carrier where code = 'DL' "
        "union all select null, 1000, 20, 45, 70"
    )
    pipeline.run_sql(conn, "rotations/backtest.sql")
    return conn
```

The count of 24 is 8 pairs at each of 3 percentiles. It holds at p10 and p50 too: no stop changes, since every absorbed leg still has slack at p50 (the smallest is 104→105, 10 min).

- [ ] **Step 3: Run the tests and see them fail**

Run: `uv run --env-file ../.env pytest tests/test_backtest.py -v`
Expected: FAIL, `relation "ontology.propagation_backtest" does not exist`.

- [ ] **Step 4: Write the migration** `db/migrations/018_propagation_backtest.sql`

```sql
-- One scored (late leg, downstream leg) pair per depth and min-turn percentile. Built by the pipeline because
-- it calls app_read.propagate once per late leg and percentile, too slow for a view.
CREATE TABLE ontology.propagation_backtest (
    late_flight_id       bigint NOT NULL REFERENCES ontology.flight,
    scored_flight_id     bigint NOT NULL REFERENCES ontology.flight,
    depth                integer NOT NULL,
    percentile           integer NOT NULL,
    period               text NOT NULL,     -- 'outage' when the late leg's flight_date is July 19-23
    late_arr_delay       integer NOT NULL,  -- the full-carry baseline
    predicted_dep_delay  integer NOT NULL,
    actual_dep_delay     integer,           -- signed, as BTS reports it
    actual_late_aircraft integer,           -- NULL when not reported (arrival delay under 15)
    swapped              boolean NOT NULL,  -- scored leg was scheduled before the late leg
    PRIMARY KEY (late_flight_id, depth, percentile)
);
```

- [ ] **Step 5: Write** `pipelines/flightops/rotations/backtest.sql`

```sql
TRUNCATE ontology.propagation_backtest;

WITH late AS (
    SELECT f.flight_id, r.tail_number, r.leg_seq, f.sched_dep_utc, f.arr_delay_min,
           CASE WHEN f.flight_date BETWEEN '2024-07-19' AND '2024-07-23' THEN 'outage' ELSE 'normal' END AS period
    FROM ontology.rotation_leg r
    JOIN ontology.flight f USING (flight_id)
    WHERE r.touched_atl AND f.arr_delay_min >= 15
      -- propagate raises without an all-carrier min turn, and a build with no late_aircraft samples has nothing to score.
      AND EXISTS (SELECT 1 FROM ontology.min_turn WHERE carrier_id IS NULL)
),
pct AS (SELECT unnest(ARRAY[10, 25, 50]) AS percentile),
run AS MATERIALIZED (  -- one propagate call per late leg and percentile
    SELECT l.flight_id AS late_flight_id, p.percentile, x.depth, x.flight_id, x.predicted_dep_delay, x.stop_reason
    FROM late l
    CROSS JOIN pct p
    CROSS JOIN LATERAL app_read.propagate(l.flight_id, NULL, p.percentile) x
    WHERE x.kind = 'flown'
),
pair AS (
    -- Pairs come from the flown chain, not from propagate's rows, so legs it never reached still score.
    SELECT l.flight_id AS late_flight_id, l.sched_dep_utc AS late_sched_dep, l.arr_delay_min, l.period,
           p.percentile, k.depth, n.flight_id AS scored_flight_id,
           CASE
               WHEN x.flight_id IS NOT NULL THEN x.predicted_dep_delay  -- NULL on a break or limit row
               WHEN s.stop_reason = 'absorbed' THEN 0
           END AS predicted                                             -- NULL past a break or limit
    FROM late l
    CROSS JOIN pct p
    CROSS JOIN generate_series(1, 3) AS k(depth)
    JOIN ontology.rotation_leg n ON n.tail_number = l.tail_number AND n.leg_seq = l.leg_seq + k.depth
    LEFT JOIN run x ON x.late_flight_id = l.flight_id AND x.percentile = p.percentile
                   AND x.depth = k.depth AND x.flight_id = n.flight_id
    LEFT JOIN run s ON s.late_flight_id = l.flight_id AND s.percentile = p.percentile
                   AND s.stop_reason IS NOT NULL AND s.depth < k.depth
)
INSERT INTO ontology.propagation_backtest
SELECT p.late_flight_id, p.scored_flight_id, p.depth, p.percentile, p.period, p.arr_delay_min, p.predicted,
       f.dep_delay_min,
       -- Causes are reported only at arrival delay >= 15, and delay rows hold minutes > 0, so reported-but-absent is 0.
       CASE WHEN f.arr_delay_min >= 15 THEN coalesce(d.minutes, 0) END,
       f.sched_dep_utc < p.late_sched_dep
FROM pair p
JOIN ontology.flight f ON f.flight_id = p.scored_flight_id
LEFT JOIN ontology.delay d ON d.flight_id = f.flight_id AND d.cause = 'late_aircraft'
WHERE p.predicted IS NOT NULL;
```

- [ ] **Step 6: Wire it in.** In `pipelines/flightops/pipeline.py`, after `run_sql(conn, "rotations/min_turn.sql")`, add:

```python
    run_sql(conn, "rotations/backtest.sql")
```

In `pipelines/flightops/resolve/ontology.sql:1`, put `ontology.propagation_backtest, ` first in the `TRUNCATE` list.

- [ ] **Step 7: Run the tests and see them pass**

Run: `uv run --env-file ../.env pytest tests/test_backtest.py -v`
Expected: 4 passed.

- [ ] **Step 8: Run the full suite**

Run: `uv run --env-file ../.env pytest`
Expected: all pass. Every other fixture build now runs the backtest too, and most of them have no `min_turn` row, which the `EXISTS` guard covers.

- [ ] **Step 9: Commit**

```bash
git add db/migrations/018_propagation_backtest.sql pipelines/flightops/rotations/backtest.sql pipelines/flightops/pipeline.py \
        pipelines/flightops/resolve/ontology.sql pipelines/tests/fixtures/bts_backtest.csv pipelines/tests/test_backtest.py
git commit -m "feat: backtest propagation against flown chains"
```

---

### Task 2: Phase-3 report

**Files:**
- Modify: `pipelines/flightops/report.py`
- Modify: `pipelines/flightops/__main__.py` (the `report` branch)
- Modify: `pipelines/tests/test_report.py`

**Interfaces:**
- Consumes: `ontology.propagation_backtest` from Task 1, `app_read.propagate`.
- Produces: `report.PERCENTILE: int` (the chosen percentile, 25 until Task 3), `report.REPORTS: dict[str, tuple[str, str, list]]` mapping a file name under `docs/` to `(header, findings, sections)`, and `report.render(conn, header=HEADER, findings=FINDINGS, sections=SECTIONS) -> str`.

- [ ] **Step 1: Write the failing tests.** Append to `pipelines/tests/test_report.py`:

```python
@pytest.fixture
def backtested(conn, load_fixture):
    load_fixture("ourairports_airports", "airports.csv")
    load_fixture("bts_ontime", "bts_backtest.csv")
    pipeline.build(conn)
    conn.execute("truncate ontology.min_turn")
    conn.execute(
        "insert into ontology.min_turn (carrier_id, samples, p10, p25, p50) "
        "select carrier_id, 500, 30, 40, 60 from ontology.carrier where code = 'DL' "
        "union all select null, 1000, 20, 45, 70"
    )
    pipeline.run_sql(conn, "rotations/backtest.sql")
    return conn


def phase3(conn):
    return report.render(conn, *report.REPORTS["phase-3-report.md"])


def test_phase3_every_section_runs_and_has_a_heading(backtested):
    text = phase3(backtested)
    for heading, _, _ in report.P3_SECTIONS:
        assert f"## {heading}" in text
    assert "None" not in text


def test_phase3_counts_cancelled_legs_in_the_gap_and_swaps(backtested):
    text = phase3(backtested)
    # normal: 101, 102, 104, 301 late; outage: 201 (cancelled 204 in its gap), 401, 402.
    assert "| normal | 4 | 0 | 0.0 | 7 | 0 |" in text
    assert "| outage | 3 | 1 | 33.3 | 1 | 1 |" in text


def test_phase3_scores_against_both_baselines(backtested):
    # normal, depth 1, late_aircraft reported only on 102: model 40 vs 45, zero 45, carry 60.
    assert "| normal | 1 | 1 | 5.0 | 45.0 | 15.0 | 100.0 | 100.0 | 100.0 |" in phase3(backtested)


def test_report_percentile_is_propagates_default(conn):
    args = conn.execute("select pg_get_function_arguments('app_read.propagate'::regproc)").fetchone()[0]
    assert args.endswith(f"p_percentile integer DEFAULT {report.PERCENTILE}")
```

- [ ] **Step 2: Run them and see them fail**

Run: `uv run --env-file ../.env pytest tests/test_report.py -v`
Expected: the four new tests FAIL with `AttributeError: module 'flightops.report' has no attribute 'REPORTS'` (or `PERCENTILE`). The old tests pass.

- [ ] **Step 3: Implement.** In `pipelines/flightops/report.py`, change `render` to take a report, keeping the phase-1 defaults so existing callers and tests don't change:

```python
def render(conn, header=HEADER, findings=FINDINGS, sections=SECTIONS) -> str:
    parts = [header, findings]
    for heading, prose, query in sections:
```

(the loop body and return are unchanged). Then add, after `SECTIONS`:

```python
PERCENTILE = 25  # the min-turn percentile the backtest chose; must equal propagate's default

P3_HEADER = """# Phase 3 propagation backtest: July 2024

Generated by `python -m flightops report`. Don't edit this file. Tables come from the database, and the SQL behind each one sits under it. Times are UTC.

A late leg is a flown leg on a tail that touched ATL, arriving 15 min or more late. Each is propagated along its tail's flown chain using only its actual arrival and the schedule after it, and the next three flown legs are scored. A leg after the delay is absorbed scores as predicted 0. Pairs at or past a rotation break or the 24h limit are left out. The outage period is July 19-23 by the late leg's flight date.
"""

# Written by hand from the tables below. Rewrite them if the data changes.
P3_FINDINGS = """## Findings

Written in Task 3 of docs/plans/2026-11-22-phase-3-backtest.md, from the tables below.
"""

METRICS = """SELECT period, depth, count(*) AS pairs,
       round(avg(abs(predicted_dep_delay - {target})), 1) AS mae_model,
       round(avg(abs({target})), 1) AS mae_zero,
       round(avg(abs(late_arr_delay - {target})), 1) AS mae_carry,
       round(100.0 * count(*) FILTER (WHERE predicted_dep_delay >= 15 AND {target} >= 15)
             / nullif(count(*) FILTER (WHERE predicted_dep_delay >= 15), 0), 1) AS precision_pct,
       round(100.0 * count(*) FILTER (WHERE predicted_dep_delay >= 15 AND {target} >= 15)
             / nullif(count(*) FILTER (WHERE {target} >= 15), 0), 1) AS recall_pct,
       round(100.0 * count(*) FILTER (WHERE {target} >= 15) / count(*), 1) AS carry_precision_pct
FROM ontology.propagation_backtest
WHERE percentile = {percentile} AND {target} IS NOT NULL
GROUP BY 1, 2 ORDER BY 1, 2"""

N102DN = """(SELECT f.flight_id FROM ontology.flight f JOIN ontology.airport o ON o.airport_id = f.origin_airport_id
     WHERE f.tail_number = 'N102DN' AND f.flight_date = '2024-07-19' AND o.iata_code = 'DEN')"""

P3_SECTIONS = [
    (
        "Min turn",
        "Measured per carrier from July turns where the next leg reported `late_aircraft` minutes. "
        "A blank carrier is the all-carrier row.",
        "SELECT c.code AS carrier, m.samples, m.p10, m.p25, m.p50 FROM ontology.min_turn m "
        "LEFT JOIN ontology.carrier c USING (carrier_id) ORDER BY m.samples DESC",
    ),
    (
        "Percentile choice",
        "Depth-1 `late_aircraft` error on the normal period, where it was reported. The lowest `mae_model` is chosen.",
        """SELECT percentile, count(*) AS pairs,
       round(avg(abs(predicted_dep_delay - actual_late_aircraft)), 1) AS mae_model,
       round(avg(actual_late_aircraft), 1) AS mae_zero,
       round(avg(abs(late_arr_delay - actual_late_aircraft)), 1) AS mae_carry
FROM ontology.propagation_backtest
WHERE period = 'normal' AND depth = 1 AND actual_late_aircraft IS NOT NULL
GROUP BY 1 ORDER BY 1""",
    ),
    (
        "Late aircraft minutes against baselines",
        f"At p{PERCENTILE}. The target is the scored leg's reported `late_aircraft` minutes, which BTS reports only "
        "when its arrival delay is 15 min or more. Predict-0 never flags a leg, so its recall is 0. "
        "Full carry flags every leg, so its recall is 100 and its precision is `carry_precision_pct`.",
        METRICS.format(target="actual_late_aircraft", percentile=PERCENTILE),
    ),
    (
        "Departure delay against baselines",
        f"At p{PERCENTILE}. The target is the scored leg's departure delay, with early departures as 0. "
        "Other causes add to it, so the model should undercount.",
        METRICS.format(target="greatest(actual_dep_delay, 0)", percentile=PERCENTILE),
    ),
    (
        "What the model misses",
        "Late legs whose tail had a cancelled leg scheduled between the late leg and its next flown leg, "
        "which the model shows but never predicts. Swapped pairs are scored legs scheduled before the late leg, "
        f"where the flown order is known only in hindsight. Pairs are at p{PERCENTILE}.",
        f"""WITH late AS (
    SELECT CASE WHEN f.flight_date BETWEEN '2024-07-19' AND '2024-07-23' THEN 'outage' ELSE 'normal' END AS period,
           EXISTS (SELECT 1 FROM ontology.flight x
                   WHERE x.tail_number = f.tail_number AND x.cancelled
                     AND x.sched_dep_utc > f.sched_dep_utc AND x.sched_dep_utc < nf.sched_dep_utc) AS cancelled_in_gap
    FROM ontology.rotation_leg r
    JOIN ontology.flight f USING (flight_id)
    LEFT JOIN ontology.rotation_leg n ON n.tail_number = r.tail_number AND n.leg_seq = r.leg_seq + 1
    LEFT JOIN ontology.flight nf ON nf.flight_id = n.flight_id
    WHERE r.touched_atl AND f.arr_delay_min >= 15
), gap AS (
    SELECT period, count(*) AS late_legs, count(*) FILTER (WHERE cancelled_in_gap) AS cancelled_in_gap
    FROM late GROUP BY 1
), pairs AS (
    SELECT period, count(*) AS scored_pairs, count(*) FILTER (WHERE swapped) AS swapped_pairs
    FROM ontology.propagation_backtest WHERE percentile = {PERCENTILE} GROUP BY 1
)
SELECT g.period, g.late_legs, g.cancelled_in_gap, round(100.0 * g.cancelled_in_gap / g.late_legs, 1) AS cancelled_pct,
       coalesce(p.scored_pairs, 0) AS scored_pairs, coalesce(p.swapped_pairs, 0) AS swapped_pairs
FROM gap g LEFT JOIN pairs p USING (period)
ORDER BY 1""",
    ),
    (
        "Worked example: N102DN, July 19",
        f"`app_read.propagate` at p{PERCENTILE} from N102DN's DEN→ATL. Cancelled rows are legs scheduled in the gap.",
        f"""SELECT depth, kind, carrier, flight_number, origin, dest,
       to_char(sched_dep_utc AT TIME ZONE 'UTC', 'MM-DD HH24:MI') AS sched_dep,
       min_turn, slack_min, predicted_dep_delay, actual_dep_delay, actual_arr_delay, actual_late_aircraft, stop_reason
FROM app_read.propagate({N102DN}, NULL, {PERCENTILE})""",
    ),
    (
        "Worked example: N102DN's scored pairs",
        "The same late leg in the backtest. Legs after the absorbed stop score as predicted 0.",
        f"""SELECT b.depth, s.flight_number, o.iata_code AS origin, d.iata_code AS dest, b.predicted_dep_delay,
       b.actual_dep_delay, b.actual_late_aircraft, b.swapped
FROM ontology.propagation_backtest b
JOIN ontology.flight s ON s.flight_id = b.scored_flight_id
JOIN ontology.airport o ON o.airport_id = s.origin_airport_id
JOIN ontology.airport d ON d.airport_id = s.dest_airport_id
WHERE b.late_flight_id = {N102DN} AND b.percentile = {PERCENTILE}
ORDER BY b.depth""",
    ),
]

REPORTS = {
    "phase-1-report.md": (HEADER, FINDINGS, SECTIONS),
    "phase-3-report.md": (P3_HEADER, P3_FINDINGS, P3_SECTIONS),
}
```

Check `test_phase3_scores_against_both_baselines` by hand: at depth 1 in the normal period, `late_aircraft` is reported only on 101→102 (102 and 104's next legs had arrival delays under 15). The model predicts 40 against 45, so MAE 5.0. Zero is 45.0. Carry predicts 60, so 15.0. 40 and 45 are both at least 15, so precision and recall are 100.0, and so is the carry precision.

In `pipelines/flightops/__main__.py`, replace the `report` branch body with:

```python
            if command in ("report", "all"):
                for name, parts in report.REPORTS.items():
                    path = db.REPO / "docs" / name
                    path.write_text(report.render(conn, *parts))
                    print("wrote", path)
```

- [ ] **Step 4: Run the tests and see them pass**

Run: `uv run --env-file ../.env pytest tests/test_report.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add pipelines/flightops/report.py pipelines/flightops/__main__.py pipelines/tests/test_report.py
git commit -m "feat: generate the phase-3 backtest report"
```

---

### Task 3: Run on July, choose the percentile, write the findings

**Files:**
- Create (only if p10 or p50 wins): `db/migrations/019_propagate_default.sql`
- Modify: `pipelines/flightops/report.py` (`PERCENTILE`, `P3_FINDINGS`), `pipelines/tests/test_propagate.py` (only if the default changes)
- Generate: `docs/phase-3-report.md`, `docs/phase-1-report.md` (regenerated, should not change)
- Modify: `DECISIONS.md`, `docs/phase-3-plan.md`, `CLAUDE.md`

- [ ] **Step 1: Migrate and build July, timing the build**

Run: `uv run --env-file ../.env python -m flightops migrate && time uv run --env-file ../.env python -m flightops build`
Expected: `applied: ['018_propagation_backtest.sql']`, blocking checks pass, and the build takes about 2 minutes longer than before. Record the backtest's own time:

```bash
uv run --env-file ../.env python -c "import time; from flightops import db, pipeline
with db.connect() as c:
    t = time.time(); pipeline.run_sql(c, 'rotations/backtest.sql'); print(round(time.time() - t, 1), 's')"
```

- [ ] **Step 2: Sanity-check the table**

```bash
psql "$DATABASE_URL" -c "
select percentile, period, count(distinct late_flight_id) as late_legs, count(*) as pairs, max(depth)
from ontology.propagation_backtest group by 1, 2 order by 1, 2;"
```

Expected: three percentiles, both periods, `max = 3`, and per-percentile late legs no more than 117,818 (late legs whose next leg is a break or limit, or that have no next leg, score no pairs). Pair counts may differ slightly by percentile, because a lower min turn can be absorbed earlier and a higher one can reach the 24h limit.

- [ ] **Step 3: Choose the percentile.** Run `uv run --env-file ../.env python -m flightops report` and read the "Percentile choice" table in `docs/phase-3-report.md`. The lowest `mae_model` wins. On a tie to one decimal, take p25, the current default.

- [ ] **Step 4 (only if p10 or p50 wins): change the default.** Write `db/migrations/019_propagate_default.sql` holding the full `CREATE OR REPLACE FUNCTION app_read.propagate(...)` from `017_propagate.sql`, unchanged except `p_percentile integer DEFAULT <chosen>`. Postgres allows `CREATE OR REPLACE` to change a default value, and grants survive a replace. Set `PERCENTILE = <chosen>` in `report.py`. In `test_propagate.py`'s `built` fixture, swap the column values so the default column still holds 40 (DL) and 45 (all):
  - p10: DL `(p10 40, p25 30, p50 60)`, all `(45, 20, 70)`.
  - p50: DL `(p10 30, p25 60, p50 40)`, all `(20, 70, 45)`, and `test_percentile_selects_the_min_turn_column` passes `None, 25`, still expecting `(1, "flown", "102", -60, 60, True, None)`.

  Then run `uv run --env-file ../.env python -m flightops migrate`. The backtest table doesn't change, because it passes percentiles explicitly.

- [ ] **Step 5: Run the full suite**

Run: `uv run --env-file ../.env pytest`
Expected: all pass, including `test_report_percentile_is_propagates_default`.

- [ ] **Step 6: Write `P3_FINDINGS` by hand** from the regenerated tables. Replace the placeholder text with bullets stating, with the numbers:
  - The chosen percentile and its depth-1 normal-period `late_aircraft` MAE against the other two percentiles.
  - For each period and target, whether the model beats predict-0 and full carry on MAE, at each depth. If it doesn't beat full carry somewhere, say so in those words, and give the margin.
  - The model's precision and recall for at risk against full carry's precision (its base rate).
  - The outage as held out, and that it isn't fully out of sample, because `min_turn` was measured on all of July.
  - That departure delay is undercounted, by how much, and that other causes explain it.
  - The cancelled-in-gap share in each period, against the normal period's, and what it says about the model's blind spot in the outage.
  - The swapped-pair count, as the hindsight caveat: the chain uses the actual flown order.
  - N102DN: predicted absorbed at ATL→BWI (58 min turn, 213 slack) while three legs in the gap were cancelled, and its actual departure delay was 49 with a reported `late_aircraft` of 0. That delay came from something other than this aircraft's late arrival, which the model correctly didn't attribute to it.

  Add a `## Limits` section in the same string covering: one month, in-sample min turn, `late_aircraft` scored only where arrival delay is 15+, no crew or passenger connections.

- [ ] **Step 7: Regenerate and check**

Run: `uv run --env-file ../.env python -m flightops report && git diff --stat docs/`
Expected: `docs/phase-3-report.md` is new, and `docs/phase-1-report.md` is unchanged. Read the phase-3 report end to end, and check every number in the findings against its table.

- [ ] **Step 8: Record it.**
  - `DECISIONS.md`: one entry for scoring the backtest from `rotation_leg` and building it inside `pipeline.build` (gave up about N s per build, the measured time), and one for the chosen percentile (gave up the others' measured errors; revisit when a second month allows an out-of-sample choice). If the table name moved out of `app_read`, say so in the first.
  - `docs/phase-3-plan.md`: rename the data-layer row to `ontology.propagation_backtest`, and add a Notes bullet with the chosen percentile, row counts and the backtest's time.
  - `CLAUDE.md` Status: step 3 built, next action is planning step 4 (FlightImpact page).

- [ ] **Step 9: Commit**

```bash
git add docs/phase-3-report.md docs/phase-1-report.md pipelines/flightops/report.py DECISIONS.md docs/phase-3-plan.md CLAUDE.md
# plus db/migrations/019_propagate_default.sql and pipelines/tests/test_propagate.py if step 4 ran
git commit -m "docs: phase-3 backtest report, percentile choice"
```
