# Phase 3, steps 1-2: min turn and propagation — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** a per-carrier minimum turn table measured from July, and `app_read.propagate()`, which walks a late flight's flown chain and predicts the delay each downstream leg inherits.

**Architecture:** `ontology.min_turn` is created by migration 016 and filled by a new SQL step in `pipeline.build`, after rotations. `app_read.propagate` is a `SECURITY DEFINER` SQL function in migration 017, with a recursive CTE over `ontology.rotation_leg.prev_flight_id`. The app role may execute it, but still cannot read `ontology`. Design: `docs/phase-3-plan.md`.

**Tech Stack:** Postgres 18 SQL, Python 3 + psycopg + pytest (run with `uv`).

## Global Constraints

- Propagate along `rotation_leg.prev_flight_id` (flown order). Never use `tail_legs.leg_order`.
- Min turn sample: a connecting flown pair on an ATL-touching tail whose next leg has `late_aircraft` minutes > 0. The value is next actual departure minus previous actual arrival.
- A carrier with fewer than 200 samples uses the all-carrier row (`carrier_id` NULL).
- `ready = previous predicted arrival + min_turn`, `predicted_dep_delay = max(0, ready - sched_dep)`, `predicted_arr = sched_arr + predicted_dep_delay`.
- At risk means a predicted departure delay of 15 min or more.
- Stop reasons: `absorbed`, `break`, `limit` (scheduled departure more than 24h after the starting arrival), `end`.
- Cancelled legs on the same tail, scheduled strictly between two consecutive chain legs, are returned as `kind = 'cancelled'` rows with no prediction.
- The default percentile is 25 until step 3's backtest picks one.
- Run all commands from `pipelines/`. Tests: `uv run --env-file ../.env pytest`.

---

### Task 1: `ontology.min_turn`

**Files:**
- Create: `db/migrations/016_min_turn.sql`
- Create: `pipelines/flightops/rotations/min_turn.sql`
- Modify: `pipelines/flightops/pipeline.py` (`build`, after rotations)
- Modify: `pipelines/flightops/resolve/ontology.sql:1` (add the table to `TRUNCATE`, since it references `ontology.carrier`)
- Create: `pipelines/tests/fixtures/bts_min_turn.csv`
- Create: `pipelines/tests/test_min_turn.py`
- Modify: `DECISIONS.md`, `docs/phase-3-plan.md` (Notes)

**Interfaces:**
- Produces: table `ontology.min_turn(carrier_id bigint NULL, samples int, p10 int, p25 int, p50 int)`, one row per carrier plus one all-carrier row with `carrier_id IS NULL`.

- [ ] **Step 1: Write the fixture**

`pipelines/tests/fixtures/bts_min_turn.csv`. All airports are Eastern, so local time is UTC-4. DL tail N1M has samples of 40, 50 and 60. Its 30-min turn with a cause of zero is excluded, and so is the 30-min turn with blank causes. N3M's late aircraft doesn't connect, so it's excluded. WN tail N2M has one sample of 35.

```csv
flightdate,reporting_airline,tail_number,flight_number_reporting_airline,origin,dest,crsdeptime,deptime,depdelay,crsarrtime,arrtime,arrdelay,crselapsedtime,actualelapsedtime,cancelled,cancellationcode,diverted,divreacheddest,div1airport,div1wheelson,carrierdelay,weatherdelay,nasdelay,securitydelay,lateaircraftdelay
2024-07-19,DL,N1M,1,LGA,ATL,0800,0800,0.00,1000,1000,0.00,120.00,120.00,0.00,,0.00,,,,,,,,
2024-07-19,DL,N1M,2,ATL,CLE,1030,1040,10.00,1200,1220,20.00,90.00,100.00,0.00,,0.00,,,,10.00,0.00,0.00,0.00,10.00
2024-07-19,DL,N1M,3,CLE,ATL,1300,1310,10.00,1430,1450,20.00,90.00,100.00,0.00,,0.00,,,,0.00,0.00,0.00,0.00,20.00
2024-07-19,DL,N1M,4,ATL,LGA,1530,1550,20.00,1730,1750,20.00,120.00,120.00,0.00,,0.00,,,,0.00,0.00,0.00,0.00,20.00
2024-07-19,DL,N1M,5,LGA,ATL,1800,1820,20.00,2000,2020,20.00,120.00,120.00,0.00,,0.00,,,,20.00,0.00,0.00,0.00,0.00
2024-07-19,DL,N1M,6,ATL,IAD,2100,2050,-10.00,2230,2220,-10.00,90.00,90.00,0.00,,0.00,,,,,,,,
2024-07-19,WN,N2M,7,LGA,ATL,0800,0800,0.00,1000,1000,0.00,120.00,120.00,0.00,,0.00,,,,,,,,
2024-07-19,WN,N2M,8,ATL,CLE,1030,1035,5.00,1200,1220,20.00,90.00,105.00,0.00,,0.00,,,,0.00,0.00,0.00,0.00,20.00
2024-07-19,DL,N3M,9,LGA,ATL,0800,0800,0.00,1000,1000,0.00,120.00,120.00,0.00,,0.00,,,,,,,,
2024-07-19,DL,N3M,10,CLE,ATL,1100,1120,20.00,1230,1250,20.00,90.00,90.00,0.00,,0.00,,,,0.00,0.00,0.00,0.00,20.00
```

- [ ] **Step 2: Write the failing test**

`pipelines/tests/test_min_turn.py`:

```python
from flightops import pipeline


def test_min_turn_percentiles_per_carrier_and_overall(conn, load_fixture):
    load_fixture("ourairports_airports", "airports.csv")
    load_fixture("bts_ontime", "bts_min_turn.csv")
    pipeline.build(conn)
    rows = conn.execute(
        "select c.code, m.samples, m.p10, m.p25, m.p50 from ontology.min_turn m "
        "left join ontology.carrier c using (carrier_id) order by c.code nulls last"
    ).fetchall()
    # DL samples 40/50/60; zero-cause, blank-cause and non-connecting turns are excluded.
    # All carriers adds WN's 35. p10 is 36.5, and round(numeric) takes it up to 37.
    assert rows == [("DL", 3, 42, 45, 50), ("WN", 1, 35, 35, 35), (None, 4, 37, 39, 45)]


def test_rebuild_replaces_min_turn(conn, load_fixture):
    load_fixture("ourairports_airports", "airports.csv")
    load_fixture("bts_ontime", "bts_min_turn.csv")
    pipeline.build(conn)
    pipeline.build(conn)
    assert conn.execute("select count(*) from ontology.min_turn").fetchone() == (3,)
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `uv run --env-file ../.env pytest tests/test_min_turn.py -v`
Expected: FAIL with `relation "ontology.min_turn" does not exist`.

- [ ] **Step 4: Write the migration**

`db/migrations/016_min_turn.sql`:

```sql
-- Shortest turn each carrier's aircraft managed when the aircraft was the constraint, measured from loaded data.
CREATE TABLE ontology.min_turn (
    carrier_id bigint REFERENCES ontology.carrier,  -- NULL: all carriers together
    samples    integer NOT NULL,
    p10        integer NOT NULL,
    p25        integer NOT NULL,
    p50        integer NOT NULL,
    UNIQUE NULLS NOT DISTINCT (carrier_id)
);
```

- [ ] **Step 5: Write the build SQL**

`pipelines/flightops/rotations/min_turn.sql`:

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
)
INSERT INTO ontology.min_turn (carrier_id, samples, p10, p25, p50)
SELECT carrier_id, count(*),
       round(percentile_cont(0.10) WITHIN GROUP (ORDER BY minutes)::numeric),
       round(percentile_cont(0.25) WITHIN GROUP (ORDER BY minutes)::numeric),
       round(percentile_cont(0.50) WITHIN GROUP (ORDER BY minutes)::numeric)
FROM turn
GROUP BY GROUPING SETS ((carrier_id), ());
```

`ontology.delay` holds only causes above zero (see `resolve/ontology.sql`), so the join needs no `minutes > 0`. `round(numeric)` rounds half away from zero, which is what the test expects.

- [ ] **Step 6: Wire it into the build and the truncate**

In `pipelines/flightops/pipeline.py`, `build`:

```python
    run_sql(conn, "rotations/rotations.sql")
    run_sql(conn, "rotations/min_turn.sql")
    run_sql(conn, "resolve/flight_weather.sql")
```

In `pipelines/flightops/resolve/ontology.sql` line 1, add `ontology.min_turn` first:

```sql
TRUNCATE ontology.min_turn, ontology.flight_weather, ontology.rotation_leg, ontology.delay, ontology.taf_forecast, ontology.weather_observation, ontology.flight,
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run --env-file ../.env pytest tests/test_min_turn.py -v`
Expected: 2 passed. Then run the full suite: `uv run --env-file ../.env pytest`, expecting all tests to pass.

- [ ] **Step 8: Apply to the July database and measure**

```bash
uv run --env-file ../.env python -m flightops migrate
uv run --env-file ../.env python -c "from flightops import db, pipeline; pipeline.run_sql(db.connect(), 'rotations/min_turn.sql')"
psql -d flightops -c "select coalesce(c.code, 'all') carrier, m.samples, m.p10, m.p25, m.p50 from ontology.min_turn m left join ontology.carrier c using (carrier_id) order by m.samples desc"
```

Expected: about 13 carrier rows, plus `all`. DL should come out near 50/58/69 from 10,690 samples, as in the exploratory query. Small differences come from the overlap filter. Copy the table into `docs/phase-3-plan.md` Notes, replacing the exploratory line, and note which carriers fall below 200 samples.

- [ ] **Step 9: Record the decision**

Append to `DECISIONS.md`:

```markdown
## 2026-11-22: Measure minimum turn per carrier from July
- **Chose:** `ontology.min_turn`, holding p10, p25 and p50 of observed turns where the next leg reported `late_aircraft` minutes, per carrier and for all carriers. A carrier with under 200 samples uses the all-carrier row.
- **Gave up:** turn times by airport or aircraft type, and a figure measured outside the month being backtested. The outage days are among the samples.
- **Why:** turns differ by about 20 min between carriers at p10 (OH 28, DL 50), so one constant would be wrong for most of them. Finer cells get few samples, and 1.2% of flights have no aircraft type.
- **Revisit if:** a second month is loaded. Then measure on one month and backtest on the other.
```

- [ ] **Step 10: Commit**

```bash
git add ../db/migrations/016_min_turn.sql flightops/rotations/min_turn.sql flightops/pipeline.py flightops/resolve/ontology.sql tests/fixtures/bts_min_turn.csv tests/test_min_turn.py ../DECISIONS.md ../docs/phase-3-plan.md
git commit -m "feat: measure minimum turn per carrier"
```

---

### Task 2: `app_read.propagate`

**Files:**
- Create: `db/migrations/017_propagate.sql`
- Create: `pipelines/tests/fixtures/bts_propagate.csv`
- Create: `pipelines/tests/test_propagate.py`
- Modify: `DECISIONS.md`, `docs/phase-3-plan.md` (Notes), `CLAUDE.md` (Status)

**Interfaces:**
- Consumes: `ontology.min_turn` from Task 1.
- Produces: `app_read.propagate(p_flight_id bigint, p_arr_delay_min integer DEFAULT NULL, p_percentile integer DEFAULT 25)`, returning rows ordered by `depth`, then cancelled before flown, then `sched_dep_utc`:

| Column | Type | Meaning |
|---|---|---|
| `depth` | int | 0 for the selected flight, n for the nth flown leg after it. A cancelled row carries the depth of the flown leg after its gap |
| `kind` | text | `selected`, `flown`, `cancelled` |
| `flight_id` | bigint | |
| `carrier`, `flight_number`, `origin`, `dest` | text | IATA codes |
| `sched_dep_utc`, `sched_arr_utc` | timestamptz | |
| `min_turn` | int | min turn used for this leg (flown, predicted rows only) |
| `slack_min` | int | scheduled departure − predicted arrival of the previous leg − min turn. Negative means delay carried |
| `predicted_dep_delay` | int | `max(0, -slack_min)`. NULL on selected, cancelled, `break` and `limit` rows |
| `predicted_arr_utc` | timestamptz | selected row: the starting arrival. Flown: `sched_arr + predicted_dep_delay` |
| `at_risk` | boolean | `predicted_dep_delay >= 15`. NULL when there's no prediction |
| `actual_dep_delay` | int | BTS departure delay |
| `actual_late_aircraft` | int | BTS `late_aircraft` minutes, NULL when not reported |
| `stop_reason` | text | set on the last chain row only: `absorbed`, `break`, `limit`, `end` |

It returns no rows when the flight is cancelled, unknown or has no rotation row.

- [ ] **Step 1: Write the fixture**

`pipelines/tests/fixtures/bts_propagate.csv`. The airports are Eastern (UTC-4). N1P carries a 60-min delay through two legs, has a cancelled leg in a gap, then absorbs. N2P breaks, N3P hits the 24h limit, and N4P ends while still late.

```csv
flightdate,reporting_airline,tail_number,flight_number_reporting_airline,origin,dest,crsdeptime,deptime,depdelay,crsarrtime,arrtime,arrdelay,crselapsedtime,actualelapsedtime,cancelled,cancellationcode,diverted,divreacheddest,div1airport,div1wheelson,carrierdelay,weatherdelay,nasdelay,securitydelay,lateaircraftdelay
2024-07-19,DL,N1P,101,LGA,ATL,0800,0900,60.00,1000,1100,60.00,120.00,120.00,0.00,,0.00,,,,60.00,0.00,0.00,0.00,0.00
2024-07-19,DL,N1P,102,ATL,CLE,1100,1145,45.00,1230,1315,45.00,90.00,90.00,0.00,,0.00,,,,0.00,0.00,0.00,0.00,45.00
2024-07-19,DL,N1P,103,CLE,ATL,1300,1400,60.00,1430,1530,60.00,90.00,90.00,0.00,,0.00,,,,15.00,0.00,0.00,0.00,45.00
2024-07-19,DL,N1P,104,ATL,LGA,1530,,,1730,,,120.00,,1.00,A,0.00,,,,,,,,
2024-07-19,DL,N1P,105,ATL,IAD,1800,1800,0.00,1930,1930,0.00,90.00,90.00,0.00,,0.00,,,,,,,,
2024-07-19,DL,N1P,106,IAD,ATL,2100,2100,0.00,2230,2230,0.00,90.00,90.00,0.00,,0.00,,,,,,,,
2024-07-19,DL,N2P,201,LGA,ATL,0800,0900,60.00,1000,1100,60.00,120.00,120.00,0.00,,0.00,,,,60.00,0.00,0.00,0.00,0.00
2024-07-19,DL,N2P,202,CLE,ATL,1300,1300,0.00,1430,1430,0.00,90.00,90.00,0.00,,0.00,,,,,,,,
2024-07-19,DL,N3P,301,ATL,LGA,0800,0900,60.00,1000,1100,60.00,120.00,120.00,0.00,,0.00,,,,60.00,0.00,0.00,0.00,0.00
2024-07-20,DL,N3P,302,LGA,ATL,1200,1200,0.00,1400,1400,0.00,120.00,120.00,0.00,,0.00,,,,,,,,
2024-07-19,DL,N4P,401,LGA,ATL,0800,0900,60.00,1000,1100,60.00,120.00,120.00,0.00,,0.00,,,,60.00,0.00,0.00,0.00,0.00
2024-07-19,DL,N4P,402,ATL,CLE,1100,1145,45.00,1230,1315,45.00,90.00,90.00,0.00,,0.00,,,,0.00,0.00,0.00,0.00,45.00
```

Worked numbers with DL p25 = 40. Flight 101 lands 11:00, 60 late. For 102, `ready` is 11:40 against a sched dep of 11:00, so slack is −40 and the delay 40. 102 is predicted to arrive 12:30 + 40 = 13:10. For 103, `ready` is 13:50 against 13:00, so slack is −50 and the delay 50, with a predicted arrival of 15:20. Cancelled 104 at 15:30 sits in the gap. For 105, `ready` is 16:00 against 18:00, so slack is 120 and the delay is absorbed.

- [ ] **Step 2: Write the failing tests**

`pipelines/tests/test_propagate.py`:

```python
import psycopg
import pytest

from flightops import pipeline

COLS = "depth, kind, flight_number, slack_min, predicted_dep_delay, at_risk, stop_reason"


@pytest.fixture
def built(conn, load_fixture):
    load_fixture("ourairports_airports", "airports.csv")
    load_fixture("bts_ontime", "bts_propagate.csv")
    pipeline.build(conn)
    # Fixed turns so the arithmetic is readable; the fixture alone is too small to measure them.
    conn.execute("truncate ontology.min_turn")
    conn.execute(
        "insert into ontology.min_turn (carrier_id, samples, p10, p25, p50) "
        "select carrier_id, 500, 30, 40, 60 from ontology.carrier where code = 'DL' "
        "union all select null, 1000, 20, 45, 70"
    )
    return conn


def fid(conn, number):
    return conn.execute("select flight_id from ontology.flight where flight_number = %s", (number,)).fetchone()[0]


def chain(conn, number, *args):
    return conn.execute(f"select {COLS} from app_read.propagate(%s{', %s' * len(args)})", (fid(conn, number), *args)).fetchall()


def test_delay_carries_across_legs_shows_cancelled_gap_and_stops_when_absorbed(built):
    assert chain(built, "101") == [
        (0, "selected", "101", None, None, None, None),
        (1, "flown", "102", -40, 40, True, None),
        (2, "flown", "103", -50, 50, True, None),
        (3, "cancelled", "104", None, None, None, None),
        (3, "flown", "105", 120, 0, False, "absorbed"),
    ]


def test_actuals_sit_beside_predictions(built):
    row = built.execute(
        "select actual_dep_delay, actual_late_aircraft, min_turn from app_read.propagate(%s) where flight_number = '102'",
        (fid(built, "101"),),
    ).fetchone()
    assert row == (45, 45, 40)


def test_what_if_delay_replaces_the_actual_arrival(built):
    assert chain(built, "101", 0) == [
        (0, "selected", "101", None, None, None, None),
        (1, "flown", "102", 20, 0, False, "absorbed"),
    ]


def test_percentile_selects_the_min_turn_column(built):
    assert chain(built, "101", None, 50)[1] == (1, "flown", "102", -60, 60, True, None)


def test_carrier_with_few_samples_falls_back_to_all_carriers(built):
    built.execute("update ontology.min_turn set samples = 199 where carrier_id is not null")
    assert chain(built, "101")[1] == (1, "flown", "102", -45, 45, True, None)


def test_rotation_break_stops_without_predicting(built):
    assert chain(built, "201")[1:] == [(1, "flown", "202", None, None, None, "break")]


def test_leg_more_than_24h_out_stops_without_predicting(built):
    assert chain(built, "301")[1:] == [(1, "flown", "302", None, None, None, "limit")]


def test_end_of_data_while_still_late(built):
    assert chain(built, "401")[1:] == [(1, "flown", "402", -40, 40, True, "end")]


def test_last_leg_selected_ends_at_once(built):
    assert chain(built, "106") == [(0, "selected", "106", None, None, None, "end")]


def test_cancelled_flight_returns_nothing(built):
    assert chain(built, "104") == []


def test_app_role_can_propagate_but_not_read_ontology(built):
    flight_id = fid(built, "101")
    built.execute("SET ROLE flightops_app")
    try:
        assert built.execute("select count(*) from app_read.propagate(%s)", (flight_id,)).fetchone() == (5,)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            built.execute("select 1 from ontology.min_turn")
    finally:
        built.execute("RESET ROLE")
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run --env-file ../.env pytest tests/test_propagate.py -v`
Expected: FAIL with `function app_read.propagate(bigint) does not exist`.

- [ ] **Step 4: Write the migration**

`db/migrations/017_propagate.sql`:

```sql
-- Min turn for a carrier at one percentile, falling back to all carriers under 200 samples.
CREATE FUNCTION app_read.min_turn_for(p_carrier_id bigint, p_percentile integer) RETURNS integer
LANGUAGE sql STABLE AS $$
    SELECT CASE p_percentile WHEN 10 THEN m.p10 WHEN 25 THEN m.p25 WHEN 50 THEN m.p50 END
    FROM ontology.min_turn m
    WHERE m.carrier_id = p_carrier_id AND m.samples >= 200
       OR m.carrier_id IS NULL
    ORDER BY m.carrier_id NULLS LAST
    LIMIT 1
$$;

-- Walks the flown chain (prev_flight_id), never the schedule-ordered leg_order used for display.
CREATE FUNCTION app_read.propagate(p_flight_id bigint, p_arr_delay_min integer DEFAULT NULL, p_percentile integer DEFAULT 25)
RETURNS TABLE (
    depth integer, kind text, flight_id bigint, carrier text, flight_number text, origin text, dest text,
    sched_dep_utc timestamptz, sched_arr_utc timestamptz, min_turn integer, slack_min integer,
    predicted_dep_delay integer, predicted_arr_utc timestamptz, at_risk boolean,
    actual_dep_delay integer, actual_late_aircraft integer, stop_reason text
)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
WITH RECURSIVE chain AS (
    SELECT 0 AS depth, f.flight_id, f.tail_number, f.sched_dep_utc,
           CASE WHEN p_arr_delay_min IS NULL THEN f.actual_arr_utc
                ELSE f.sched_arr_utc + p_arr_delay_min * interval '1 minute' END AS arr_utc,
           CASE WHEN p_arr_delay_min IS NULL THEN f.actual_arr_utc
                ELSE f.sched_arr_utc + p_arr_delay_min * interval '1 minute' END AS start_arr,
           NULL::integer AS min_turn, NULL::integer AS slack_min, NULL::integer AS delay, NULL::text AS stop_reason
    FROM ontology.flight f
    JOIN ontology.rotation_leg r ON r.flight_id = f.flight_id
    WHERE f.flight_id = p_flight_id
  UNION ALL
    SELECT c.depth + 1, n.flight_id, n.tail_number, n.sched_dep_utc,
           n.sched_arr_utc + d.delay * interval '1 minute',
           c.start_arr, t.min_turn, s.slack_min, d.delay,
           coalesce(k.cut, CASE WHEN d.delay = 0 THEN 'absorbed' END)
    FROM chain c
    JOIN ontology.rotation_leg r ON r.prev_flight_id = c.flight_id
    JOIN ontology.flight n ON n.flight_id = r.flight_id
    CROSS JOIN LATERAL (SELECT CASE
        WHEN NOT r.connects THEN 'break'
        WHEN n.sched_dep_utc > c.start_arr + interval '24 hours' THEN 'limit'
    END AS cut) k
    CROSS JOIN LATERAL (SELECT CASE WHEN k.cut IS NULL THEN app_read.min_turn_for(n.carrier_id, p_percentile) END AS min_turn) t
    CROSS JOIN LATERAL (SELECT (extract(epoch FROM n.sched_dep_utc - c.arr_utc) / 60)::integer - t.min_turn AS slack_min) s
    -- greatest() ignores NULL, so a break or limit row must stay NULL explicitly.
    CROSS JOIN LATERAL (SELECT CASE WHEN s.slack_min IS NOT NULL THEN greatest(0, -s.slack_min) END AS delay) d
    WHERE c.stop_reason IS NULL
),
out_legs AS (
    SELECT c.depth, CASE WHEN c.depth = 0 THEN 'selected' ELSE 'flown' END AS kind, c.flight_id,
           c.min_turn, c.slack_min, c.delay, c.arr_utc,
           coalesce(c.stop_reason, CASE WHEN c.depth = max(c.depth) OVER () THEN 'end' END) AS stop_reason
    FROM chain c
  UNION ALL
    -- Cancelled legs of this tail scheduled inside a gap: shown, never predicted.
    SELECT nxt.depth, 'cancelled', x.flight_id, NULL, NULL, NULL, NULL, NULL
    FROM chain prv
    JOIN chain nxt ON nxt.depth = prv.depth + 1
    JOIN ontology.flight x ON x.tail_number = prv.tail_number AND x.cancelled
        AND x.sched_dep_utc > prv.sched_dep_utc AND x.sched_dep_utc < nxt.sched_dep_utc
)
SELECT w.depth, w.kind, f.flight_id, ca.code, f.flight_number, o.iata_code, de.iata_code,
       f.sched_dep_utc, f.sched_arr_utc, w.min_turn, w.slack_min,
       CASE WHEN w.kind = 'flown' THEN w.delay END,
       CASE WHEN w.kind <> 'cancelled' AND (w.kind = 'selected' OR w.delay IS NOT NULL) THEN w.arr_utc END,
       CASE WHEN w.kind = 'flown' AND w.delay IS NOT NULL THEN w.delay >= 15 END,
       f.dep_delay_min,
       (SELECT y.minutes FROM ontology.delay y WHERE y.flight_id = f.flight_id AND y.cause = 'late_aircraft'),
       w.stop_reason
FROM out_legs w
JOIN ontology.flight f ON f.flight_id = w.flight_id
JOIN ontology.carrier ca ON ca.carrier_id = f.carrier_id
JOIN ontology.airport o ON o.airport_id = f.origin_airport_id
JOIN ontology.airport de ON de.airport_id = f.dest_airport_id
ORDER BY w.depth, w.kind = 'flown', f.sched_dep_utc
$$;

-- Runs as its owner, so the app can call it without reading ontology.
CREATE INDEX ON ontology.rotation_leg (prev_flight_id);

REVOKE EXECUTE ON FUNCTION app_read.propagate(bigint, integer, integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app_read.propagate(bigint, integer, integer) TO flightops_app;
```

Notes for the implementer:

- `search_path` is empty of user schemas, so every name is schema-qualified, including the `app_read.min_turn_for` call. `min_turn_for` runs as the definer, because it is called from inside a definer function.
- On `break` and `limit` rows, `min_turn` is NULL, so `slack_min`, `delay` and `predicted_arr_utc` are NULL too. `greatest(0, NULL)` returns 0 in Postgres, which is why the delay line guards with `CASE`.
- The recursive step joins on `rotation_leg.prev_flight_id`, which had no index. The backtest in step 3 calls this function once per late leg, so the index is created up front.
- Sorting `w.kind = 'flown'` puts `false` first, so selected and cancelled rows come before the flown row at the same depth.
- Times in BTS are whole minutes, so `::integer` on the epoch difference loses nothing.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run --env-file ../.env pytest tests/test_propagate.py -v`
Expected: 11 passed. Then run the full suite: `uv run --env-file ../.env pytest`, expecting all tests to pass.

- [ ] **Step 6: Apply to the July database and check N102DN**

```bash
uv run --env-file ../.env python -m flightops migrate
psql -d flightops -c "select depth, kind, flight_number, origin, dest, min_turn, slack_min, predicted_dep_delay, at_risk, actual_dep_delay, actual_late_aircraft, stop_reason from app_read.propagate(371994)"
psql -d flightops -c "explain analyze select * from app_read.propagate(371994)" | tail -3
```

Expected: selected 371994 (DEN→ATL), then three cancelled rows at depth 1 (ATL→CLE, CLE→ATL, ATL→GEG). ATL→IAH at 02:50Z has the same scheduled time as the next flown leg, so the strict `<` excludes it. Then flown ATL→BWI at depth 1, `absorbed`, with a slack of 271 − DL p25 (02:50Z scheduled departure minus the 22:19Z arrival). Its actual departure delay is 49 with no `late_aircraft` minutes. Execution time should be well under 100 ms. If it isn't, stop and report the plan instead of tuning blind.

Record the N102DN output and the timing in `docs/phase-3-plan.md` Notes.

- [ ] **Step 7: Record the decision and update status**

Append to `DECISIONS.md`:

```markdown
## 2026-11-22: Propagate along the flown chain, and show cancelled legs without predicting them
- **Chose:** `app_read.propagate` follows `rotation_leg.prev_flight_id`. Cancelled legs on the same tail scheduled inside a gap are returned as their own rows, with no prediction.
- **Gave up:** a model of what the delay did to the schedule. For N102DN on July 19, the 316-min DEN→ATL is predicted as absorbed by the 02:50Z ATL→BWI, while the three legs scheduled in between were cancelled.
- **Why:** flown legs have actual times to score against, and BTS gives no signal for predicting cancellations outside the outage. Showing the cancelled legs keeps what the model misses in plain view.
- **Revisit if:** the backtest shows cancellations in the gap after most large delays. Then a cancellation model is worth its own phase.
```

In `CLAUDE.md` Status, set **Current phase** to "3, steps 1-2 built: `ontology.min_turn` (migration 016) and `app_read.propagate` (migration 017)". Set **Next action** to "plan step 3: `app_read.propagation_backtest`, the percentile choice, and `docs/phase-3-report.md`".

- [ ] **Step 8: Commit**

```bash
git add ../db/migrations/017_propagate.sql tests/fixtures/bts_propagate.csv tests/test_propagate.py ../DECISIONS.md ../docs/phase-3-plan.md ../CLAUDE.md
git commit -m "feat: propagate a late arrival along its tail's flown chain"
```
