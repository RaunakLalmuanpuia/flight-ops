# Phase 6 step 3: cancellation risk in `propagate` and the decision log Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `app_read.propagate` returns `cancel_risk` and `cancel_risk_basis` for the selected flight's next three scheduled legs, `record_decision` freezes them in `app.decision_leg`, and `app_read.decision_review` counts the legs flagged at cancellation risk.

**Architecture:** migration 026 adds two small functions, `app_read.cancel_rate_for` (a cell lookup with the 200-sample fallback) and `app_read.cancel_risk_threshold` (0.183). It re-creates `propagate` with two new output columns. It adds two nullable columns to `app.decision_leg`, re-creates the two review views, and replaces `record_decision`. `propagate` doesn't recompute ranks, the 24h cut or stress. It reads them for the selected flight from `ontology.cancel_backtest` (primary key `(inbound_flight_id, rank)`), so the app and the backtest share one definition. Only the rate lookup is repeated, so that a what-if delay can change the delay bucket.

**Tech Stack:** Postgres 18, Python with `uv`, psycopg, pytest. Pest checks that the app still reads the re-created function and views.

## Global Constraints

- Ranks, the 24h cut and stress are as in step 2: ranks 1-3 by scheduled departure after the selected flight, within 24h of its **actual** arrival, with stress from its **actual** departure. A what-if delay changes only the delay bucket, never the target set or stress.
- A row gets a rate only if it is one of the selected flight's ranked targets in `ontology.cancel_backtest`. The selected row and every other row get `cancel_risk` NULL and `cancel_risk_basis` NULL.
- A ranked target with no July cell gets `cancel_risk` NULL, with basis `not scored: no July cell`.
- A diverted start: every row after it gets `cancel_risk` NULL, with basis `not scored: diverted`.
- Basis text is `<carrier code>, <n> samples` for a carrier cell and `all carriers, <n> samples` otherwise, for example `DL, 1309 samples`.
- The flag threshold is 0.183. The report's exact July F1 maximum is 0.18338, and no cell rate lies between the two (checked: one distinct rate in [0.18, 0.18338], the threshold itself), so the flagged set is the same.
- `propagate` gets new output columns, so it is dropped and re-created, and its grants are reapplied in the same migration. `record_decision` is plpgsql and names `propagate` only at run time, so it doesn't block the drop.
- `app_read.decision_legs` is `SELECT l.*`, which Postgres expands when the view is created, so both review views are dropped and re-created after the new columns are added.
- The log is append-only: the three walkthrough decisions already in `app` keep NULL risk.
- Next free migration number is 026. Step 4 (the app) is out of scope: no Vue, controller or screenshot changes.
- Commands run from `pipelines/`: `uv run --env-file ../.env pytest` and `uv run --env-file ../.env python -m flightops ...`. Pest runs from `web/` as `./vendor/bin/pest`, against the local `flightops` database.

## Known limit, measured in Task 3

`propagate` returns the flown chain, plus cancelled legs scheduled between two chain legs. A ranked target that falls outside those rows has a rate in the backtest but no row on which to show it. For example, a cancelled leg scheduled after the chain has already stopped as absorbed. Task 3 counts how many cancelled targets this hides, so step 4 can decide whether FlightImpact needs to list them separately.

---

## File structure

| File | Responsibility |
|---|---|
| `db/migrations/026_propagate_cancel_risk.sql` (create) | the threshold and lookup functions, `propagate` re-created, `app.decision_leg` columns, both review views re-created, `record_decision` replaced |
| `pipelines/tests/fixtures/bts_cancel_risk.csv` (create) | an N102DN-shaped tail and a diverted start |
| `pipelines/tests/test_cancel_risk.py` (create) | `propagate` risk, what-if, diverted start, snapshot, review count, pre-phase rows, app role |
| `pipelines/flightops/report.py` (modify) | the "Flag threshold" section shows the app's threshold beside the fitted one |
| `pipelines/tests/test_report.py` (modify) | the threshold row gains that column |
| `DECISIONS.md`, `docs/phase-6-plan.md`, `CLAUDE.md` (modify) | decisions, measured notes, status |

---

### Task 1: Migration 026 and its tests

**Files:**
- Create: `db/migrations/026_propagate_cancel_risk.sql`, `pipelines/tests/fixtures/bts_cancel_risk.csv`, `pipelines/tests/test_cancel_risk.py`

**Interfaces:**
- Consumes: `ontology.cancel_backtest` (`inbound_flight_id`, `target_flight_id`, `rank`, `carrier_id`, `delay_bucket`, `stress_bucket`), `ontology.cancel_rate`, `ontology.delay_bucket(integer)` from step 2.
- Produces: `app_read.propagate(bigint, integer DEFAULT NULL, integer DEFAULT 10)` with two new columns at the end, `cancel_risk numeric` and `cancel_risk_basis text`. Also `app_read.cancel_rate_for(bigint, integer, text, text) RETURNS TABLE (rate numeric, basis text)`, `app_read.cancel_risk_threshold() RETURNS numeric`, `app.decision_leg.cancel_risk` and `.cancel_risk_basis`, the same two columns at the end of `app_read.decision_legs`'s frozen columns, and `app_read.decision_review.flagged_cancel_risk` (bigint). Step 4 reads all of these.

The fixture times are Eastern local (EDT, UTC−4), on July 10:

| Tail | Case |
|---|---|
| N8C | N102DN-shaped. 801 LGA→ATL arrives 150 min late. Three cancelled legs (802, 803, 804) are scheduled before the next flown leg, 805, so `propagate` returns all three at depth 1, and 805 is rank 4 |
| N6D | 601 LGA→ATL diverted to IAD, then 602 IAD→ATL flown |

801's stress is 0: the only other DL departure in its window is 601, which wasn't cancelled. The test injects fixed rates, because the fixture is far too small to fit any. For 801 (`120-239`, `<2%`), they are:

| rank | DL cell | all-carrier cell | used |
|---|---|---|---|
| 1 | 300 samples, 0.25 | 2,000, 0.20 | DL, 0.25 |
| 2 | none | 1,000, 0.19 | all carriers, 0.19 |
| 3 | 150 samples, 0.20 | 40, 0.10 | all carriers, 0.10 (DL is under 200) |

A what-if of 300 min puts 801 in `240+`, where only rank 1 has a cell (DL, 250 samples, 0.60).

- [ ] **Step 1: Write the fixture** `pipelines/tests/fixtures/bts_cancel_risk.csv`

```csv
flightdate,reporting_airline,tail_number,flight_number_reporting_airline,origin,dest,crsdeptime,deptime,depdelay,crsarrtime,arrtime,arrdelay,crselapsedtime,actualelapsedtime,cancelled,cancellationcode,diverted,divreacheddest,div1airport,div1wheelson,carrierdelay,weatherdelay,nasdelay,securitydelay,lateaircraftdelay
2024-07-10,DL,N8C,801,LGA,ATL,0800,1030,150.00,1000,1230,150.00,120.00,120.00,0.00,,0.00,,,,150.00,0.00,0.00,0.00,0.00
2024-07-10,DL,N8C,802,ATL,CLE,1300,,,1430,,,90.00,,1.00,A,0.00,,,,,,,,
2024-07-10,DL,N8C,803,CLE,ATL,1500,,,1630,,,90.00,,1.00,A,0.00,,,,,,,,
2024-07-10,DL,N8C,804,ATL,IAD,1700,,,1830,,,90.00,,1.00,A,0.00,,,,,,,,
2024-07-10,DL,N8C,805,ATL,LGA,1900,1900,0.00,2100,2100,0.00,120.00,120.00,0.00,,0.00,,,,,,,,
2024-07-10,DL,N6D,601,LGA,ATL,0800,0800,0.00,1000,,,120.00,,0.00,,1.00,0.00,IAD,0950,,,,,
2024-07-10,DL,N6D,602,IAD,ATL,1300,1300,0.00,1430,1430,0.00,90.00,90.00,0.00,,0.00,,,,,,,,
```

- [ ] **Step 2: Write the failing tests** `pipelines/tests/test_cancel_risk.py`

```python
import pytest

from flightops import pipeline

RISK = "depth, kind, flight_number, round(cancel_risk, 3)::float8, cancel_risk_basis"


@pytest.fixture
def built(conn, load_fixture):
    load_fixture("ourairports_airports", "airports.csv")
    load_fixture("bts_ontime", "bts_cancel_risk.csv")
    pipeline.build(conn)
    # Fixed turns and rates: the fixture is far too small to fit either.
    conn.execute("truncate ontology.min_turn")
    conn.execute(
        "insert into ontology.min_turn (carrier_id, samples, p5, p10, p25, p50) "
        "select carrier_id, 500, 40, 40, 30, 60 from ontology.carrier where code = 'DL' "
        "union all select null, 1000, 45, 45, 20, 70"
    )
    conn.execute("truncate ontology.cancel_rate")
    conn.execute(
        "insert into ontology.cancel_rate (carrier_id, rank, delay_bucket, stress_bucket, samples, cancelled, rate) "
        "select carrier_id, 1, '120-239', '<2%', 300, 75, 0.25 from ontology.carrier where code = 'DL' "
        "union all select null, 1, '120-239', '<2%', 2000, 400, 0.20 "
        "union all select null, 2, '120-239', '<2%', 1000, 190, 0.19 "
        "union all select carrier_id, 3, '120-239', '<2%', 150, 30, 0.20 from ontology.carrier where code = 'DL' "
        "union all select null, 3, '120-239', '<2%', 40, 4, 0.10 "
        "union all select carrier_id, 1, '240+', '<2%', 250, 150, 0.60 from ontology.carrier where code = 'DL'"
    )
    pipeline.run_sql(conn, "rotations/cancel_backtest.sql")
    return conn


def fid(conn, number):
    return conn.execute("select flight_id from ontology.flight where flight_number = %s", (number,)).fetchone()[0]


def risk(conn, number, *args):
    return conn.execute(
        f"select {RISK} from app_read.propagate(%s{', %s' * len(args)})", (fid(conn, number), *args)
    ).fetchall()


def record(conn, number, delay=None):
    return conn.execute(
        "select app_read.record_decision(%s, %s, 'accept_delay', null, 'inbound late', 'duty controller')",
        (fid(conn, number), delay),
    ).fetchone()[0]


def test_ranked_legs_are_scored_by_schedule_not_depth(built):
    assert risk(built, "801") == [
        (0, "selected", "801", None, None),
        # All three cancelled legs come back at depth 1, and they are ranks 1-3.
        (1, "cancelled", "802", 0.25, "DL, 300 samples"),
        (1, "cancelled", "803", 0.19, "all carriers, 1000 samples"),  # no DL cell
        (1, "cancelled", "804", 0.1, "all carriers, 40 samples"),  # the DL cell has 150
        (1, "flown", "805", None, None),  # rank 4
    ]


def test_rates_match_the_backtest(built):
    got = built.execute(
        "select round(predicted_rate, 3)::float8 from ontology.cancel_backtest where inbound_flight_id = %s order by rank",
        (fid(built, "801"),),
    ).fetchall()
    assert [g[0] for g in got] == [0.25, 0.19, 0.1]


def test_what_if_changes_only_the_delay_bucket(built):
    assert risk(built, "801", 300) == [
        (0, "selected", "801", None, None),
        (1, "cancelled", "802", 0.6, "DL, 250 samples"),
        (1, "cancelled", "803", None, "not scored: no July cell"),
        (1, "cancelled", "804", None, "not scored: no July cell"),
        (1, "flown", "805", None, None),
    ]


def test_diverted_start_is_not_scored(built):
    assert risk(built, "601") == [
        (0, "selected", "601", None, None),
        (1, "flown", "602", None, "not scored: diverted"),
    ]


def test_threshold_is_the_july_f1_maximum(built):
    assert float(built.execute("select app_read.cancel_risk_threshold()").fetchone()[0]) == 0.183


def test_decision_freezes_the_risk_and_counts_flagged_legs(built):
    d = record(built, "801")
    frozen = built.execute(
        f"select {RISK} from app.decision_leg where decision_id = %s order by depth, kind = 'flown', sched_dep_utc", (d,)
    ).fetchall()
    assert frozen == risk(built, "801")
    # 0.25 and 0.19 are at or above 0.183. 0.10 is not.
    assert built.execute(
        "select flagged_cancel_risk from app_read.decision_review where decision_id = %s", (d,)
    ).fetchone() == (2,)


def test_frozen_risk_survives_a_rate_change(built):
    d = record(built, "801")
    built.execute("update ontology.cancel_rate set rate = 0")
    assert built.execute(
        "select flagged_cancel_risk from app_read.decision_review where decision_id = %s", (d,)
    ).fetchone() == (2,)


def test_decisions_recorded_before_cancel_risk_read_as_null(built):
    d = record(built, "801")
    # Rows logged before migration 026 have these columns NULL.
    built.execute("update app.decision_leg set cancel_risk = null, cancel_risk_basis = null where decision_id = %s", (d,))
    assert built.execute(
        "select count(*) filter (where cancel_risk is not null or cancel_risk_basis is not null) "
        "from app_read.decision_legs where decision_id = %s",
        (d,),
    ).fetchone() == (0,)
    assert built.execute(
        "select flagged_cancel_risk from app_read.decision_review where decision_id = %s", (d,)
    ).fetchone() == (0,)


def test_app_role_reads_cancel_risk(built):
    flight_id = fid(built, "801")
    built.execute("SET ROLE flightops_app")
    try:
        assert built.execute(
            "select count(cancel_risk) from app_read.propagate(%s)", (flight_id,)
        ).fetchone() == (3,)
        built.execute(
            "select app_read.record_decision(%s, null, 'accept_delay', null, 'inbound late', 'duty controller')",
            (flight_id,),
        )
        assert built.execute("select flagged_cancel_risk from app_read.decision_review").fetchone() == (2,)
        assert built.execute("select app_read.cancel_risk_threshold()").fetchone() is not None
    finally:
        built.execute("RESET ROLE")
```

- [ ] **Step 3: Run the tests to see them fail**

Run: `uv run --env-file ../.env pytest tests/test_cancel_risk.py -v`
Expected: FAIL with `column "cancel_risk" does not exist` and `function app_read.cancel_risk_threshold() does not exist`.

- [ ] **Step 4: Write the migration** `db/migrations/026_propagate_cancel_risk.sql`

```sql
-- Phase 6 step 3 (docs/phase-6-plan.md): cancellation risk on propagate's rows, frozen in the decision log.

-- The July F1 maximum in docs/phase-6-report.md is 0.18338. No cell rate lies between it and 0.183, so the flags match.
-- shortcut: hard-coded, so compare it with the report's app_threshold_pct after every rebuild.
-- Left executable by PUBLIC: decision_review calls it, and functions in a view run with the caller's rights.
CREATE FUNCTION app_read.cancel_risk_threshold() RETURNS numeric
LANGUAGE sql IMMUTABLE AS $$ SELECT 0.183 $$;

-- One July cell, with the same 200-sample fallback as cancel_backtest.sql. No row when July has no cell at all.
CREATE FUNCTION app_read.cancel_rate_for(p_carrier_id bigint, p_rank integer, p_delay_bucket text, p_stress_bucket text)
RETURNS TABLE (rate numeric, basis text)
LANGUAGE sql STABLE SET search_path = pg_catalog, pg_temp AS $$
    SELECT r.rate, coalesce(c.code, 'all carriers') || ', ' || r.samples || ' samples'
    FROM ontology.cancel_rate r
    LEFT JOIN ontology.carrier c ON c.carrier_id = r.carrier_id
    WHERE r.rank = p_rank AND r.delay_bucket = p_delay_bucket AND r.stress_bucket = p_stress_bucket
      AND (r.carrier_id = p_carrier_id AND r.samples >= 200 OR r.carrier_id IS NULL)
    ORDER BY r.carrier_id NULLS LAST
    LIMIT 1
$$;
REVOKE EXECUTE ON FUNCTION app_read.cancel_rate_for(bigint, integer, text, text) FROM PUBLIC;

-- New output columns can't be added with CREATE OR REPLACE.
DROP FUNCTION app_read.propagate(bigint, integer, integer);

-- Walks the flown chain (prev_flight_id), never the schedule-ordered leg_order used for display.
-- Cancellation risk is by schedule rank instead, read from cancel_backtest so it matches the scored backtest.
CREATE FUNCTION app_read.propagate(p_flight_id bigint, p_arr_delay_min integer DEFAULT NULL, p_percentile integer DEFAULT 10)
RETURNS TABLE (
    depth integer, kind text, flight_id bigint, carrier text, flight_number text, origin text, dest text,
    sched_dep_utc timestamptz, sched_arr_utc timestamptz, min_turn integer, slack_min integer,
    predicted_dep_delay integer, predicted_arr_utc timestamptz, at_risk boolean,
    actual_dep_delay integer, actual_arr_delay integer, actual_late_aircraft integer, stop_reason text,
    cancel_risk numeric, cancel_risk_basis text
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
      -- No starting arrival means nothing to propagate: return no rows, like a cancelled flight.
      AND (CASE WHEN p_arr_delay_min IS NULL THEN f.actual_arr_utc ELSE f.sched_arr_utc END) IS NOT NULL
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
),
-- Ranks, the 24h cut and stress come from the actual flight. A what-if changes only the delay bucket.
risk AS (
    SELECT b.target_flight_id, r.rate, coalesce(r.basis, 'not scored: no July cell') AS basis
    FROM ontology.cancel_backtest b
    LEFT JOIN LATERAL app_read.cancel_rate_for(
        b.carrier_id, b.rank, coalesce(ontology.delay_bucket(p_arr_delay_min), b.delay_bucket), b.stress_bucket) r ON true
    WHERE b.inbound_flight_id = p_flight_id
)
SELECT w.depth, w.kind, f.flight_id, ca.code, f.flight_number, o.iata_code, de.iata_code,
       f.sched_dep_utc, f.sched_arr_utc, w.min_turn, w.slack_min,
       CASE WHEN w.kind = 'flown' THEN w.delay END,
       CASE WHEN w.kind <> 'cancelled' AND (w.kind = 'selected' OR w.delay IS NOT NULL) THEN w.arr_utc END,
       CASE WHEN w.kind = 'flown' AND w.delay IS NOT NULL THEN w.delay >= 15 END,
       f.dep_delay_min, f.arr_delay_min,
       -- Causes are reported only at arrival delay >= 15, and delay rows hold minutes > 0, so reported-but-absent is 0.
       CASE WHEN f.arr_delay_min >= 15 THEN coalesce(
           (SELECT y.minutes FROM ontology.delay y WHERE y.flight_id = f.flight_id AND y.cause = 'late_aircraft'), 0) END,
       w.stop_reason,
       x.rate,
       -- A diverted start has no arrival delay, so the backtest never scored it.
       CASE WHEN w.depth > 0 AND (SELECT s.diverted FROM ontology.flight s WHERE s.flight_id = p_flight_id)
            THEN 'not scored: diverted' ELSE x.basis END
FROM out_legs w
JOIN ontology.flight f ON f.flight_id = w.flight_id
JOIN ontology.carrier ca ON ca.carrier_id = f.carrier_id
JOIN ontology.airport o ON o.airport_id = f.origin_airport_id
JOIN ontology.airport de ON de.airport_id = f.dest_airport_id
LEFT JOIN risk x ON x.target_flight_id = w.flight_id AND w.kind <> 'selected'
ORDER BY w.depth, w.kind = 'flown', f.sched_dep_utc
$$;

-- Runs as its owner, so the app can call it without reading ontology.
REVOKE EXECUTE ON FUNCTION app_read.propagate(bigint, integer, integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app_read.propagate(bigint, integer, integer) TO flightops_app;

-- The views expand l.* when they are created, so they are re-created around the new columns.
DROP VIEW app_read.decision_review;
DROP VIEW app_read.decision_legs;

-- NULL on legs recorded before this migration: the log is append-only, so they are never backfilled.
ALTER TABLE app.decision_leg ADD COLUMN cancel_risk numeric, ADD COLUMN cancel_risk_basis text;

-- Each frozen leg beside what BTS shows for it now, matched on the natural key because flight ids restart on rebuild.
CREATE VIEW app_read.decision_legs AS
SELECT l.*,
       coalesce(l.flight_id = d.target_flight_id, false) AS is_target,
       f.flight_id      AS current_flight_id,
       f.cancelled      AS actual_cancelled,
       f.dep_delay_min  AS actual_dep_delay,
       f.arr_delay_min  AS actual_arr_delay
FROM app.decision_leg l
JOIN app.decision d ON d.decision_id = l.decision_id
LEFT JOIN (ontology.flight f
           JOIN ontology.carrier c ON c.carrier_id = f.carrier_id
           JOIN ontology.airport o ON o.airport_id = f.origin_airport_id)
       ON c.code = l.carrier AND f.flight_number = l.flight_number
      AND o.iata_code = l.origin AND f.sched_dep_utc = l.sched_dep_utc;

CREATE VIEW app_read.decision_review AS
SELECT d.decision_id, d.recorded_at, d.author, d.action, d.reason, d.arr_delay_min, d.what_if, d.percentile,
       s.carrier, s.flight_number, s.origin, s.dest, s.sched_dep_utc,
       s.current_flight_id, s.current_flight_id IS NOT NULL AS flight_found,
       t.carrier AS target_carrier, t.flight_number AS target_flight_number, t.origin AS target_origin,
       t.dest AS target_dest, t.sched_dep_utc AS target_sched_dep_utc, t.kind AS target_kind,
       t.predicted_dep_delay AS target_predicted_dep_delay, t.actual_cancelled AS target_cancelled,
       t.actual_dep_delay AS target_actual_dep_delay,
       n.predicted_at_risk, n.actually_late, n.cancelled, n.flagged_cancel_risk,
       CASE
           WHEN s.current_flight_id IS NULL OR (t.decision_id IS NOT NULL AND t.current_flight_id IS NULL)
               THEN 'flight not found after rebuild'
           WHEN t.decision_id IS NULL THEN NULL
           WHEN t.actual_cancelled THEN
               CASE d.action WHEN 'cancel_leg' THEN 'airline did the same' ELSE 'airline cancelled it' END
           WHEN d.action = 'cancel_leg' THEN 'airline flew it, ' || m.actual
           -- BTS records only the tail that flew, so a swap can't be confirmed.
           WHEN d.action = 'swap_aircraft' THEN 'this tail flew it, ' || m.actual || ' (swap not visible)'
           ELSE 'flown, ' || m.actual || coalesce(' vs predicted ' || m.predicted, ', no prediction')
       END AS match_label
FROM app.decision d
JOIN app_read.decision_legs s ON s.decision_id = d.decision_id AND s.depth = 0
LEFT JOIN app_read.decision_legs t ON t.decision_id = d.decision_id AND t.is_target
CROSS JOIN LATERAL (SELECT
    CASE WHEN t.actual_dep_delay >= 0 THEN '+' ELSE '' END || t.actual_dep_delay || ' min' AS actual,
    CASE WHEN t.predicted_dep_delay >= 0 THEN '+' ELSE '' END || t.predicted_dep_delay AS predicted) m
CROSS JOIN LATERAL (SELECT
    count(*) FILTER (WHERE x.at_risk) AS predicted_at_risk,
    count(*) FILTER (WHERE x.kind = 'flown' AND x.actual_dep_delay >= 15) AS actually_late,
    count(*) FILTER (WHERE x.depth > 0 AND x.actual_cancelled) AS cancelled,
    -- Frozen risk against today's threshold. Legs recorded before cancellation risk are NULL and never count.
    count(*) FILTER (WHERE x.cancel_risk >= app_read.cancel_risk_threshold()) AS flagged_cancel_risk
    FROM app_read.decision_legs x WHERE x.decision_id = d.decision_id) n;

GRANT SELECT ON app_read.decision_legs, app_read.decision_review TO flightops_app;

-- p_arr_delay_min NULL means the actual arrival, as in propagate. p_percentile defaults to propagate's default.
CREATE OR REPLACE FUNCTION app_read.record_decision(
    p_flight_id bigint, p_arr_delay_min integer, p_action text, p_target_flight_id bigint,
    p_reason text, p_author text, p_percentile integer DEFAULT 10)
RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    v_id bigint;
BEGIN
    IF coalesce(trim(p_reason), '') = '' THEN RAISE EXCEPTION 'A reason is required.'; END IF;
    IF coalesce(trim(p_author), '') = '' THEN RAISE EXCEPTION 'An author is required.'; END IF;
    IF p_action = 'accept_delay' AND p_target_flight_id IS NOT NULL THEN
        RAISE EXCEPTION 'Accepting the delay takes no target leg.';
    END IF;
    -- propagate's override measures from the scheduled destination, the wrong airport after a diversion.
    IF p_arr_delay_min IS NOT NULL AND EXISTS (SELECT FROM ontology.flight WHERE flight_id = p_flight_id AND diverted) THEN
        RAISE EXCEPTION 'A diverted flight has no arrival delay to replace.';
    END IF;

    INSERT INTO app.decision (flight_id, arr_delay_min, what_if, percentile, action, target_flight_id, reason, author)
    VALUES (p_flight_id,
            coalesce(p_arr_delay_min, (SELECT arr_delay_min FROM ontology.flight WHERE flight_id = p_flight_id)),
            p_arr_delay_min IS NOT NULL, p_percentile, p_action, p_target_flight_id, trim(p_reason), trim(p_author))
    RETURNING decision_id INTO v_id;

    -- One propagate call: the target is checked against the frozen copy, so the check and the snapshot can't differ.
    INSERT INTO app.decision_leg (
        decision_id, depth, kind, flight_id, carrier, flight_number, origin, dest, sched_dep_utc, sched_arr_utc,
        min_turn, slack_min, predicted_dep_delay, predicted_arr_utc, at_risk, stop_reason, cancel_risk, cancel_risk_basis)
    SELECT v_id, p.depth, p.kind, p.flight_id, p.carrier, p.flight_number, p.origin, p.dest, p.sched_dep_utc, p.sched_arr_utc,
           p.min_turn, p.slack_min, p.predicted_dep_delay, p.predicted_arr_utc, p.at_risk, p.stop_reason,
           p.cancel_risk, p.cancel_risk_basis
    FROM app_read.propagate(p_flight_id, p_arr_delay_min, p_percentile) p;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Flight % has no arrival to propagate from.', p_flight_id;
    END IF;

    IF p_target_flight_id IS NOT NULL AND NOT EXISTS (
        SELECT FROM app.decision_leg WHERE decision_id = v_id AND flight_id = p_target_flight_id AND kind <> 'selected') THEN
        RAISE EXCEPTION 'The target is not a later leg in this chain.';
    END IF;
    RETURN v_id;
END
$$;
```

The body of `propagate` is migration 019's, unchanged except for three things: the two new return columns, the `risk` CTE, and the two new select expressions with the `LEFT JOIN risk`. `record_decision` is migration 022's with the two columns added to its insert. Diff each against its original before running.

- [ ] **Step 5: Run the new tests, then the full suite**

Run: `uv run --env-file ../.env pytest tests/test_cancel_risk.py -v`
Expected: 9 passed.
Run: `uv run --env-file ../.env pytest`
Expected: all pass. `test_propagate.py` and `test_decisions.py` select named columns, so the new columns don't change them, and the backtest's `propagate` call reads only named columns.

If an expected row differs, recheck the fixture arithmetic in the tables above before changing the SQL.

- [ ] **Step 6: Commit**

```bash
git add db/migrations/026_propagate_cancel_risk.sql pipelines/tests/fixtures/bts_cancel_risk.csv pipelines/tests/test_cancel_risk.py
git commit -m "feat: cancellation risk in propagate, frozen in the decision log"
```

---

### Task 2: The report shows the app's threshold

**Files:**
- Modify: `pipelines/flightops/report.py` (the "Flag threshold" entry in `P6_SECTIONS`)
- Modify: `pipelines/tests/test_report.py` (`test_phase6_threshold_maximizes_july_f1`)

**Interfaces:**
- Consumes: `app_read.cancel_risk_threshold()` from Task 1.

The threshold is hard-coded in the migration, so the report puts it beside the fitted one, and a rebuild that moves the fitted threshold shows up as a mismatch.

- [ ] **Step 1: Update the test** in `pipelines/tests/test_report.py`, so the expected row gains the app's 18.3 (the fixture's fitted threshold is 50.0, so the two differ there by design):

```python
def test_phase6_threshold_maximizes_july_f1(cancel_scored):
    # July predictions: 1.0 x3 (all cancelled), 0.5 x2 (one cancelled), 0.0 x2 (none); 4 cancelled in all.
    # Flagging at 0.5 catches 4 of 5 flagged and all 4 cancelled: F1 8/9, above 6/7 at 1.0 and 8/11 at 0.0.
    # The app's threshold is fixed at 18.3 by migration 026, so it differs from this fixture's.
    assert "| 50.0 | 5 | 4 | 80.0 | 100.0 | 0.889 | 18.3 |" in phase6(cancel_scored)
```

- [ ] **Step 2: Run it to see it fail**

Run: `uv run --env-file ../.env pytest tests/test_report.py -k threshold -v`
Expected: FAIL, because the row has no seventh column.

- [ ] **Step 3: Change the section** in `pipelines/flightops/report.py`. In the "Flag threshold" entry, the prose becomes:

```python
        "Chosen on all of July, ranks 1-3 pooled, as the predicted rate that maximizes F1 when every pair at or above it is flagged. "
        "`app_threshold_pct` is the threshold `propagate`'s callers flag at (`app_read.cancel_risk_threshold`), "
        "hard-coded in a migration, so the two must agree.",
```

and its query gains one column after `f1`:

```sql
       round(2.0 * count(*) FILTER (WHERE b.predicted_rate >= th.r AND b.actual_cancelled)
             / (count(*) FILTER (WHERE b.predicted_rate >= th.r) + count(*) FILTER (WHERE b.actual_cancelled)), 3) AS f1,
       round(100 * app_read.cancel_risk_threshold(), 1) AS app_threshold_pct
```

- [ ] **Step 4: Run the report tests**

Run: `uv run --env-file ../.env pytest tests/test_report.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add pipelines/flightops/report.py pipelines/tests/test_report.py
git commit -m "feat: phase 6 report shows the app's flag threshold"
```

---

### Task 3: Migrate the real database and measure

**Files:**
- Modify: `docs/phase-6-plan.md` (Notes table)

No rebuild is needed: 026 changes only functions, views and an `app` table. If a check below fails, stop and bring the numbers to the user.

- [ ] **Step 1: Migrate**

Run: `uv run --env-file ../.env python -m flightops migrate`
Expected: `applied: ['026_propagate_cancel_risk.sql']`.

- [ ] **Step 2: The walkthrough decisions survive with NULL risk**

```sql
SELECT d.decision_id, d.author, count(l.*) AS legs, count(l.cancel_risk_basis) AS with_basis, r.flagged_cancel_risk
FROM app.decision d JOIN app.decision_leg l USING (decision_id)
JOIN app_read.decision_review r USING (decision_id)
GROUP BY 1, 2, 5 ORDER BY 1;
```

Expected: the three `walkthrough` decisions, each with its legs, `with_basis` 0 and `flagged_cancel_risk` 0.

- [ ] **Step 3: N102DN matches the report**

```sql
SELECT depth, kind, flight_number, origin, dest, round(100 * cancel_risk, 1) AS risk_pct, cancel_risk_basis
FROM app_read.propagate((SELECT f.flight_id FROM ontology.flight f JOIN ontology.airport o ON o.airport_id = f.origin_airport_id
     WHERE f.tail_number = 'N102DN' AND f.flight_date = '2024-07-19' AND o.iata_code = 'DEN'));
```

Expected: ATL→CLE 49.5, CLE→ATL 51.4 and ATL→GEG 46.7, with bases `DL, 1309 samples`, `DL, 1276 samples` and `DL, 1197 samples`, matching the report's worked example. ATL→BWI has no risk.

Run the same query with `, 600` after the flight id subquery (the phase 5 what-if). Expected: the same three legs, scored from the `240+` cells. The flight is already 316 min late, so the bucket and rates are unchanged.

- [ ] **Step 4: Count the cancelled targets `propagate` doesn't show**

```sql
SELECT b.period, count(*) AS cancelled_targets, count(*) FILTER (WHERE p.flight_id IS NULL) AS not_shown,
       round(100.0 * count(*) FILTER (WHERE p.flight_id IS NULL) / count(*), 1) AS not_shown_pct
FROM ontology.cancel_backtest b
LEFT JOIN LATERAL (SELECT x.flight_id FROM app_read.propagate(b.inbound_flight_id) x
                   WHERE x.flight_id = b.target_flight_id) p ON true
WHERE b.actual_cancelled
GROUP BY 1 ORDER BY 1;
```

Run it with `\timing`. It makes one `propagate` call per cancelled target, about 33,700 in all. Record the result either way. It decides whether step 4 needs a separate list of ranked legs that aren't in the chain.

- [ ] **Step 5: Time one call**

```sql
EXPLAIN (ANALYZE) SELECT * FROM app_read.propagate((SELECT f.flight_id FROM ontology.flight f JOIN ontology.airport o ON o.airport_id = f.origin_airport_id
     WHERE f.tail_number = 'N102DN' AND f.flight_date = '2024-07-19' AND o.iata_code = 'DEN'));
```

Expected: a few milliseconds. The `risk` CTE reads `cancel_backtest` by its primary key. **If it takes over 50 ms, stop.**

- [ ] **Step 6: The app still reads the re-created function and views**

Run from `web/`: `./vendor/bin/pest`
Expected: all pass. FlightImpact selects `p.*` from `propagate`, and the decision pages select `*` from the views, so the new columns arrive unused until step 4.

- [ ] **Step 7: Write the measured rows into the Notes table** in `docs/phase-6-plan.md`: the cancelled targets not shown, by period, the time per call, and the walkthrough decisions read as NULL.

- [ ] **Step 8: Commit**

```bash
git add docs/phase-6-plan.md
git commit -m "docs: measured cancel risk in propagate"
```

---

### Task 4: Decisions and status

**Files:**
- Modify: `DECISIONS.md`, `CLAUDE.md`

- [ ] **Step 1: Add `DECISIONS.md` entries** in the existing format, dated the day of the work:
  - **Read cancellation risk in `propagate` from the backtest table:** `propagate` takes the selected flight's ranks, 24h cut, carrier and stress from `ontology.cancel_backtest`, and only looks the rate up again, so that a what-if can change the delay bucket. Gave up: risk for flights the backtest didn't score (a tail that didn't touch ATL that month, or a diversion), and for ranked legs outside `propagate`'s rows (Task 3's count). Why: one definition of the target set and stress, shared with the scored numbers in the report, and a lookup by primary key. Revisit if the app needs risk for a schedule that isn't in BTS, such as a live one.
  - **A what-if changes only the delay bucket:** the target set and stress stay those of the actual flight. Gave up: a what-if that also moves the 24h cut. Why: stress is measured at the actual departure, which a typed delay doesn't move, and keeping the target set fixed means the what-if rows are the same legs the backtest scored. Revisit if what-ifs on flights still in the air become possible, where there is no actual departure yet.
  - **Hard-code the flag threshold at 0.183:** `app_read.cancel_risk_threshold()`, from the July F1 maximum of 0.18338. No cell rate lies between the two. Gave up: a threshold that follows the data on a rebuild. Why: frozen decisions are counted against it, and a value that moved silently would change past reviews. The report shows the app's value beside the fitted one. Revisit when a rebuild makes them disagree.

- [ ] **Step 2: Update `CLAUDE.md` Status:** step 3 done (on its branch until merged), with the next action being the step 4 plan (FlightImpact column, decision pages, screenshots).

- [ ] **Step 3: Verify**

Run: `uv run --env-file ../.env pytest` from `pipelines/`, and `./vendor/bin/pest` from `web/`.
Expected: all pass.
Run: `uv run --env-file ../.env python -m flightops report && git status --short docs/`
Expected: `docs/phase-6-report.md` changes only by the new `app_threshold_pct` column (18.3) and its prose. Phase 1 and phase 3 reports are unchanged.

- [ ] **Step 4: Commit**

```bash
git add DECISIONS.md CLAUDE.md docs/phase-6-report.md
git commit -m "docs: phase 6 step 3 decisions and status"
```
