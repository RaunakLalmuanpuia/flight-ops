# Phase 6 step 4: cancellation risk in the app Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** FlightImpact shows a cancel-risk column for the selected flight's next three scheduled legs, with a badge at the threshold. The decision pages show the frozen risk and the flagged count, and decisions logged before cancellation risk say so. Screenshots and an N102DN walkthrough close the phase.

**Architecture:** migration 027 makes `propagate` also return the scored legs it had no row for, as `kind = 'scheduled'` rows with `depth` NULL. With that, one column covers every scored leg, and `record_decision` freezes them with no change of its own. The same migration marks each decision with `cancel_risk_recorded`: false for rows that already exist, true from then on. The Vue pages format risk through one helper in `resources/js/lib/risk.js`. The controllers pass the threshold from `app_read.cancel_risk_threshold()`.

**Tech Stack:** Postgres 18, Laravel + Inertia + Vue + Tailwind, Pest, `node --test`, pytest.

## Global Constraints

- The app reads only through `app_read` and writes only through `record_decision` (CLAUDE.md, Stack).
- Cancel risk shows as a percentage to one decimal, with a badge at or above `app_read.cancel_risk_threshold()` (0.183). Where the risk is NULL, the cell shows the basis text (`not scored: diverted`, `not scored: no July cell`), or `not scored` when there is none.
- A caveat in the existing small-print pattern says: fitted on July, scored on August; a cancellation counts as known only from its scheduled departure; and a what-if changes only the delay band.
- Decisions with `cancel_risk_recorded` false show `recorded before cancellation risk`, never `not scored`.
- The chain totals (`predicted_at_risk`, `actually_late`, `cancelled`) keep counting only the chain, so `depth` NULL rows stay out of them. `flagged_cancel_risk` counts every frozen leg.
- Next free migration number is 027. Pest runs against the local `flightops` database as `flightops_app`, with `search_path` `app_read`. DecisionTest rolls back its writes.
- Commands: from `pipelines/`, `uv run --env-file ../.env pytest`. From `web/`, `./vendor/bin/pest`, `npm test` and `npm run build`.

## One change to the spec, for review

The phase plan says "a Cancel risk column beside predicted delay". Step 3 measured that `propagate`'s rows miss 45.6% of the cancelled rank-2 targets and 72.6% of the rank-3 ones in `august` and `debby`. So a column on those rows alone would hide about half the cancelled legs the rate table scores. N102DN shows it on July 19. Its ATL→BWI (DL 2590, 28 min late) is absorbed at BWI→ATL, which is flagged at 20.8%. Two later cancelled legs are flagged too, IAH→ATL at 23.8% and ATL→DTW at 28.0%, but they get no row.

This plan adds those legs to `propagate` as `scheduled` rows, with no depth and no delay prediction, and puts them after the chain. The alternative was a separate "next three scheduled legs" panel. That needs its own frozen table in the log, and it shows each leg's risk in two places. Task 5 records the choice in `DECISIONS.md`.

---

## File structure

| File | Responsibility |
|---|---|
| `db/migrations/027_scheduled_legs.sql` (create) | `propagate` adds `scheduled` rows. `app.decision_leg.depth` becomes nullable. `app.decision.cancel_risk_recorded` is added. `decision_review` gains that column |
| `pipelines/tests/fixtures/bts_cancel_risk.csv` (modify) | add N4D: an on-time inbound whose chain is absorbed before two cancelled legs |
| `pipelines/tests/test_cancel_risk.py` (modify) | `scheduled` rows, frozen with NULL depth and left out of the chain totals; the `cancel_risk_recorded` default |
| `web/resources/js/lib/risk.js`, `risk.test.js` (create) | `cancelRisk(leg, threshold)` and `CANCEL_RISK_CAVEAT` |
| `web/resources/js/lib/decisions.js`, `decisions.test.js` (modify) | `targetLabel` for a leg with no depth |
| `web/app/Http/Controllers/FlightImpactController.php` (modify) | `t.cancelled` in the leg select, and the `cancelThreshold` prop |
| `web/app/Http/Controllers/DecisionController.php` (modify) | the `cancelThreshold` prop on `show` |
| `web/resources/js/Pages/FlightImpact.vue`, `Decision.vue`, `Decisions.vue` (modify) | the column, the frozen risk, the flagged totals |
| `web/tests/Feature/FlightImpactTest.php`, `DecisionTest.php` (modify) | Pest on real July 19 flights |
| `web/scripts/screenshots.sh` (modify) | the ATL→BWI shot and the new walkthrough decision |
| `DECISIONS.md`, `docs/phase-6-plan.md`, `CLAUDE.md` (modify) | decisions, the walkthrough notes, status |

---

### Task 1: Migration 027 and its pytest cases

**Files:**
- Create: `db/migrations/027_scheduled_legs.sql`
- Modify: `pipelines/tests/fixtures/bts_cancel_risk.csv`, `pipelines/tests/test_cancel_risk.py`

**Interfaces:**
- Consumes: `app_read.propagate` and `app_read.decision_review` as migration 026 left them.
- Produces: `propagate` rows with `kind = 'scheduled'` and `depth` NULL, sorted after the chain. These have `cancel_risk` and `cancel_risk_basis`, and NULL for every prediction column. Also `app.decision.cancel_risk_recorded boolean`, and the same column at the end of `app_read.decision_review`. The output columns are otherwise unchanged, so no `DROP` is needed.

The new fixture tail, N4D, flies on July 11, so it sits outside N8C's July 10 stress window. 401 LGA→ATL arrives on time. 402 ATL→CLE is flown and absorbs everything (slack 120 − 40). Then 403 CLE→ATL and 404 ATL→IAD are cancelled. `propagate` stops at 402, so 403 and 404 come back only as `scheduled` rows. The only injected cell for 401 (`<15`, `<2%`) is all-carrier rank 2, with 500 samples at 0.05.

- [ ] **Step 1: Append N4D to the fixture** `pipelines/tests/fixtures/bts_cancel_risk.csv`

```csv
2024-07-11,DL,N4D,401,LGA,ATL,0800,0800,0.00,1000,1000,0.00,120.00,120.00,0.00,,0.00,,,,,,,,
2024-07-11,DL,N4D,402,ATL,CLE,1200,1200,0.00,1330,1330,0.00,90.00,90.00,0.00,,0.00,,,,,,,,
2024-07-11,DL,N4D,403,CLE,ATL,1500,,,1630,,,90.00,,1.00,A,0.00,,,,,,,,
2024-07-11,DL,N4D,404,ATL,IAD,1700,,,1830,,,90.00,,1.00,A,0.00,,,,,,,,
```

- [ ] **Step 2: Add the injected cell and the tests** to `pipelines/tests/test_cancel_risk.py`

In the `built` fixture's `cancel_rate` insert, add one more `union all` line after the `'240+'` one:

```python
        "union all select null, 2, '<15', '<2%', 500, 25, 0.05"
```

Then append:

```python
def test_scored_legs_outside_the_chain_come_back_as_scheduled(built):
    # 402 absorbs the delay, so the chain stops there and 403 and 404 have no chain row.
    assert risk(built, "401") == [
        (0, "selected", "401", None, None),
        (1, "flown", "402", None, "not scored: no July cell"),
        (None, "scheduled", "403", 0.05, "all carriers, 500 samples"),
        (None, "scheduled", "404", None, "not scored: no July cell"),
    ]


def test_scheduled_rows_carry_no_prediction(built):
    assert built.execute(
        "select min_turn, slack_min, predicted_dep_delay, predicted_arr_utc, at_risk, stop_reason "
        "from app_read.propagate(%s) where kind = 'scheduled'",
        (fid(built, "401"),),
    ).fetchall() == [(None,) * 6, (None,) * 6]


def test_scheduled_legs_are_frozen_but_stay_out_of_the_chain_totals(built):
    d = record(built, "401")
    assert built.execute(
        "select flight_number from app.decision_leg where decision_id = %s and depth is null order by flight_number", (d,)
    ).fetchall() == [("403",), ("404",)]
    # Both scheduled legs were cancelled, but the chain (402) wasn't, and 0.05 is under the threshold.
    assert built.execute(
        "select cancelled, flagged_cancel_risk, cancel_risk_recorded from app_read.decision_review where decision_id = %s", (d,)
    ).fetchone() == (0, 0, True)


def test_a_scheduled_leg_can_be_the_target(built):
    d = built.execute(
        "select app_read.record_decision(%s, null, 'cancel_leg', %s, 'protect the bank', 'duty controller')",
        (fid(built, "401"), fid(built, "403")),
    ).fetchone()[0]
    assert built.execute(
        "select target_kind, match_label from app_read.decision_review where decision_id = %s", (d,)
    ).fetchone() == ("scheduled", "airline did the same")
```

N8C's existing tests keep their rows: its three cancelled legs are all in the chain's gap, so it gets no `scheduled` rows.

- [ ] **Step 3: Run them to see them fail**

Run: `uv run --env-file ../.env pytest tests/test_cancel_risk.py -v`
Expected: the 4 new tests FAIL (no `scheduled` rows, no `cancel_risk_recorded` column). The 9 existing tests pass.

- [ ] **Step 4: Write the migration** `db/migrations/027_scheduled_legs.sql`

```sql
-- Phase 6 step 4 (docs/phase-6-plan.md): show every scored leg, and mark decisions logged before cancellation risk.

-- Legs scored by schedule rank but outside the chain get a row with no depth. Step 3 measured that the chain
-- alone hides 45.6% of cancelled rank-2 targets and 72.6% of rank-3. Output columns are unchanged.
CREATE OR REPLACE FUNCTION app_read.propagate(p_flight_id bigint, p_arr_delay_min integer DEFAULT NULL, p_percentile integer DEFAULT 10)
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
legs AS (
    SELECT * FROM out_legs
  UNION ALL
    -- Scored next legs the chain never reached, such as a cancellation after the delay was absorbed: risk only.
    SELECT NULL, 'scheduled', b.target_flight_id, NULL, NULL, NULL, NULL, NULL
    FROM ontology.cancel_backtest b
    WHERE b.inbound_flight_id = p_flight_id
      AND EXISTS (SELECT 1 FROM out_legs)
      AND b.target_flight_id NOT IN (SELECT o.flight_id FROM out_legs o)
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
FROM legs w
JOIN ontology.flight f ON f.flight_id = w.flight_id
JOIN ontology.carrier ca ON ca.carrier_id = f.carrier_id
JOIN ontology.airport o ON o.airport_id = f.origin_airport_id
JOIN ontology.airport de ON de.airport_id = f.dest_airport_id
LEFT JOIN risk x ON x.target_flight_id = w.flight_id AND w.kind <> 'selected'
ORDER BY w.depth, w.kind = 'flown', f.sched_dep_utc  -- NULL depth sorts last
$$;

-- Scheduled legs are frozen too, and have no depth.
ALTER TABLE app.decision_leg ALTER COLUMN depth DROP NOT NULL;

-- Rows that already exist were logged before cancellation risk. Every later decision records it.
ALTER TABLE app.decision ADD COLUMN cancel_risk_recorded boolean NOT NULL DEFAULT false;
ALTER TABLE app.decision ALTER COLUMN cancel_risk_recorded SET DEFAULT true;

-- Same view as 026, with cancel_risk_recorded appended, which CREATE OR REPLACE allows.
CREATE OR REPLACE VIEW app_read.decision_review AS
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
       END AS match_label,
       d.cancel_risk_recorded
FROM app.decision d
JOIN app_read.decision_legs s ON s.decision_id = d.decision_id AND s.depth = 0
LEFT JOIN app_read.decision_legs t ON t.decision_id = d.decision_id AND t.is_target
CROSS JOIN LATERAL (SELECT
    CASE WHEN t.actual_dep_delay >= 0 THEN '+' ELSE '' END || t.actual_dep_delay || ' min' AS actual,
    CASE WHEN t.predicted_dep_delay >= 0 THEN '+' ELSE '' END || t.predicted_dep_delay AS predicted) m
CROSS JOIN LATERAL (SELECT
    count(*) FILTER (WHERE x.at_risk) AS predicted_at_risk,
    count(*) FILTER (WHERE x.kind = 'flown' AND x.actual_dep_delay >= 15) AS actually_late,
    -- depth > 0 leaves out scheduled legs (NULL depth): the chain totals describe the chain.
    count(*) FILTER (WHERE x.depth > 0 AND x.actual_cancelled) AS cancelled,
    -- Frozen risk against today's threshold. Legs recorded before cancellation risk are NULL and never count.
    count(*) FILTER (WHERE x.cancel_risk >= app_read.cancel_risk_threshold()) AS flagged_cancel_risk
    FROM app_read.decision_legs x WHERE x.decision_id = d.decision_id) n;
```

Diff `propagate` against migration 026's body before running. The only changes should be the `legs` CTE, `FROM legs w`, and the comment on `ORDER BY`. Diff `decision_review` against 026's: the only changes should be `d.cancel_risk_recorded` and the one comment. `record_decision` is not touched: it inserts `p.depth` as given, which is now NULL for scheduled rows, and it checks the target against `kind <> 'selected'`, which lets a scheduled leg be the target.

- [ ] **Step 5: Run the tests**

Run: `uv run --env-file ../.env pytest tests/test_cancel_risk.py -v`
Expected: 13 passed.
Run: `uv run --env-file ../.env pytest`
Expected: all pass. `backtest.sql` reads only `kind = 'flown'` rows, so `scheduled` rows don't reach `propagation_backtest`.

- [ ] **Step 6: Commit**

```bash
git add db/migrations/027_scheduled_legs.sql pipelines/tests/fixtures/bts_cancel_risk.csv pipelines/tests/test_cancel_risk.py
git commit -m "feat: propagate returns scored legs outside the chain; mark decisions before cancel risk"
```

---

### Task 2: Risk formatting helper

**Files:**
- Create: `web/resources/js/lib/risk.js`, `web/resources/js/lib/risk.test.js`
- Modify: `web/resources/js/lib/decisions.js` (`targetLabel`), `web/resources/js/lib/decisions.test.js`

**Interfaces:**
- Produces: `cancelRisk(leg, threshold) -> { text: string, flagged: boolean, basis: string | null }` and `CANCEL_RISK_CAVEAT: string`, both used by Task 3. Postgres `numeric` reaches the browser as a string, so `cancelRisk` converts it.

- [ ] **Step 1: Write the failing tests** `web/resources/js/lib/risk.test.js`

```js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { CANCEL_RISK_CAVEAT, cancelRisk } from './risk.js';

test('a scored leg shows its rate to one decimal, its basis, and a flag at the threshold', () => {
    assert.deepEqual(cancelRisk({ cancel_risk: '0.49503', cancel_risk_basis: 'DL, 1309 samples' }, 0.183), {
        text: '49.5%', flagged: true, basis: 'DL, 1309 samples',
    });
    assert.equal(cancelRisk({ cancel_risk: '0.183', cancel_risk_basis: 'x' }, 0.183).flagged, true);
    assert.equal(cancelRisk({ cancel_risk: '0.1829', cancel_risk_basis: 'x' }, 0.183).flagged, false);
});

test('an unscored leg says why, or just not scored', () => {
    assert.deepEqual(cancelRisk({ cancel_risk: null, cancel_risk_basis: 'not scored: diverted' }, 0.183), {
        text: 'not scored: diverted', flagged: false, basis: null,
    });
    assert.deepEqual(cancelRisk({ cancel_risk: null, cancel_risk_basis: null }, 0.183), { text: 'not scored', flagged: false, basis: null });
});

test('the caveat names the fit, the holdout, the known-at proxy and the what-if limit', () => {
    assert.match(CANCEL_RISK_CAVEAT, /fitted on July 2024 and scored on August/);
    assert.match(CANCEL_RISK_CAVEAT, /scheduled departure/);
    assert.match(CANCEL_RISK_CAVEAT, /what-if changes only the delay band/);
});
```

And in `web/resources/js/lib/decisions.test.js`, after the existing `targetLabel` test:

```js
test('a scheduled leg outside the chain has no depth', () => {
    const leg = { depth: null, kind: 'scheduled', carrier: 'DL', flight_number: '1069', origin: 'IAH', dest: 'ATL', sched_dep_utc: '2024-07-20 11:00:00+00', origin_tz: 'America/Chicago' };
    assert.equal(targetLabel(leg), '— · DL 1069 IAH → ATL · Jul 20 06:00 · outside the chain');
});
```

- [ ] **Step 2: Run them to see them fail**

Run from `web/`: `npm test`
Expected: FAIL, because `./risk.js` can't be found, and the label starts `null ·`.

- [ ] **Step 3: Write `web/resources/js/lib/risk.js`**

```js
// cancel_risk arrives as a numeric string from Postgres; NULL keeps the basis as the reason
export function cancelRisk(leg, threshold) {
    if (leg.cancel_risk === null || leg.cancel_risk === undefined) {
        return { text: leg.cancel_risk_basis ?? 'not scored', flagged: false, basis: null };
    }
    const risk = Number(leg.cancel_risk);
    return { text: `${(100 * risk).toFixed(1)}%`, flagged: risk >= threshold, basis: leg.cancel_risk_basis };
}

export const CANCEL_RISK_CAVEAT =
    "Cancel risk is how often legs like this one were cancelled in July 2024: the tail's next three scheduled legs within 24 h of this arrival, by carrier, place in the schedule, arrival-delay band and carrier stress (the share of the carrier's departures cancelled in the three clock hours before this flight left, other aircraft only). It is fitted on July 2024 and scored on August. A cancellation counts as known only from its scheduled departure, because BTS gives no announcement time. A what-if changes only the delay band. The badge marks the July threshold that best balanced catching cancellations against false alarms, which mostly fires on outage-scale days.";
```

In `web/resources/js/lib/decisions.js`, replace `targetLabel`:

```js
export function targetLabel(leg) {
    const when = `${localDate(leg.sched_dep_utc, leg.origin_tz)} ${localTime(leg.sched_dep_utc, leg.origin_tz)}`;
    const note = { cancelled: ' · cancelled', scheduled: ' · outside the chain' }[leg.kind] ?? '';
    return `${leg.depth ?? '—'} · ${leg.carrier} ${leg.flight_number} ${leg.origin} → ${leg.dest} · ${when}${note}`;
}
```

- [ ] **Step 4: Run the tests**

Run: `npm test`
Expected: all pass. If the IAH local time differs, check the expected string: CDT is UTC−5, so 11:00 UTC is 06:00.

- [ ] **Step 5: Commit**

```bash
git add web/resources/js/lib/risk.js web/resources/js/lib/risk.test.js web/resources/js/lib/decisions.js web/resources/js/lib/decisions.test.js
git commit -m "feat: cancel-risk formatting and caveat"
```

---

### Task 3: FlightImpact column

**Files:**
- Modify: `web/app/Http/Controllers/FlightImpactController.php`, `web/resources/js/Pages/FlightImpact.vue`, `web/tests/Feature/FlightImpactTest.php`

**Interfaces:**
- Consumes: Task 1's `scheduled` rows, and Task 2's `cancelRisk` and `CANCEL_RISK_CAVEAT`.
- Produces: FlightImpact props `cancelThreshold` (float), and `legs.*.cancelled` (from `tail_legs`).

- [ ] **Step 1: Write the failing Pest tests** (append to `web/tests/Feature/FlightImpactTest.php`)

```php
it('scores the three cancelled legs after N102DN\'s 316-min arrival', function () {
    $pct = fn ($r) => round(100 * (float) $r, 1);
    $this->get('/flights/'.n102dn())->assertOk()->assertInertia(fn (Assert $page) => $page
        ->where('cancelThreshold', 0.183)
        ->where('legs.0.cancel_risk', fn ($r) => $pct($r) === 49.5)
        ->where('legs.0.cancel_risk_basis', 'DL, 1309 samples')
        ->where('legs.2.cancel_risk', fn ($r) => $pct($r) === 46.7)
        ->where('legs.3.flight_number', '2590')
        ->where('legs.3.cancel_risk', null));  // ATL->BWI is rank 5
});

it('lists scored legs the chain never reached as scheduled rows', function () {
    // ATL->BWI arrived 28 min late and BWI->ATL absorbed it, so the two cancelled legs after are outside the chain
    $id = DB::selectOne("select flight_id from tail_legs where tail_number = 'N102DN' and leg_day = '2024-07-19' and flight_number = '2590'")->flight_id;
    $this->get("/flights/{$id}")->assertOk()->assertInertia(fn (Assert $page) => $page
        ->where('legs', fn (Collection $legs) => $legs->map(fn ($l) => [$l['kind'], $l['flight_number'], $l['depth']])->all() === [
            ['flown', '2950', 1], ['scheduled', '1069', null], ['scheduled', '1240', null],
        ])
        ->where('legs.1.cancelled', true)
        ->where('legs.1.cancel_risk_basis', 'DL, 1300 samples')
        ->where('legs.1.predicted_dep_delay', null)
        ->where('stop', 'absorbed'));
});
```

- [ ] **Step 2: Run them to see them fail**

Pest reads the local database, so apply 027 there first. From `pipelines/`, run `uv run --env-file ../.env python -m flightops migrate`. Expected: `applied: ['027_scheduled_legs.sql']`.
Run from `web/`: `./vendor/bin/pest tests/Feature/FlightImpactTest.php`
Expected: both new tests FAIL, the first on `cancelThreshold` and the second on `legs.1.cancelled`. The existing tests pass.

- [ ] **Step 3: Change the controller** `web/app/Http/Controllers/FlightImpactController.php`

In the `propagate` select, add `t.cancelled`:

```php
            "select p.*, t.tail_number, t.leg_day, t.origin_tz, t.dest_tz, t.diverted, t.landed, t.landed_tz, t.cancelled
             from propagate(?, ?) p join tail_legs t using (flight_id)
             order by p.depth, p.kind = 'flown', p.sched_dep_utc",
```

The `order by` already puts NULL depth last. In the `Inertia::render` array, after `'stop' => ...`, add:

```php
            'cancelThreshold' => (float) DB::selectOne('select cancel_risk_threshold() as t')->t,
```

- [ ] **Step 4: Replace `web/resources/js/Pages/FlightImpact.vue`** with:

```vue
<script setup>
import { computed, ref } from 'vue';
import { Head, Link, router, usePage } from '@inertiajs/vue3';
import { localDate, localTime, utcTitle } from '../lib/time.js';
import { CANCEL_RISK_CAVEAT, cancelRisk } from '../lib/risk.js';
import DecisionPanel from '../components/DecisionPanel.vue';

const props = defineProps({ flight: Object, legs: Array, delay: Number, whatIf: Boolean, stop: String, decisions: Array, cancelThreshold: Number });
const page = usePage();

const STOPS = {
    absorbed: 'Delay absorbed: every later leg is predicted on time.',
    break: "Rotation break: the next leg doesn't start where this one landed, so the chain stops unpredicted.",
    limit: 'The next leg is scheduled more than 24 hours after this arrival, so the chain stops unpredicted.',
    end: "End of this tail's data while the delay was still being carried.",
};
const OUTSIDE = {
    cancelled: 'Cancelled in the gap, delay not predicted',
    scheduled: 'Later on the schedule, outside the propagated chain',
};

const input = ref(Math.max(0, props.delay ?? 0));
const submit = () => router.get(`/flights/${props.flight.flight_id}`, { delay: input.value });
const dim = computed(() => (props.whatIf ? 'opacity-40' : ''));
const minutes = (n) => (n === null || n === undefined ? '—' : `${n} min`);
const arrival = (n) => (n > 0 ? `${n} min late` : n < 0 ? `${-n} min early` : 'on time');
const risk = (l) => cancelRisk(l, props.cancelThreshold);
</script>

<template>
    <Head :title="`${flight.carrier} ${flight.flight_number} impact`" />
    <main class="mx-auto max-w-7xl space-y-4 px-4 py-6">
        <header class="space-y-1">
            <Link :href="`/tail/${flight.tail_number}/${flight.leg_day}`" class="text-sm text-sky-700 underline">← {{ flight.tail_number }} on {{ flight.leg_day }}</Link>
            <h1 class="text-xl font-semibold">
                {{ flight.carrier }} {{ flight.flight_number }} · {{ flight.origin }} → {{ flight.dest }} · {{ localDate(flight.sched_dep_utc, flight.origin_tz) }} · {{ flight.tail_number }}
            </h1>
            <p v-if="flight.diverted" class="text-sm text-violet-800">
                Diverted, landed {{ flight.landed ?? '?' }}. BTS gives no arrival delay for a diversion, so the chain starts from the actual landing time and there is no delay to change.
            </p>
            <p v-else class="text-sm">Arrived {{ arrival(flight.actual_arr_delay) }}.<template v-if="whatIf"> Showing what a {{ delay }}-min arrival delay would do instead.</template></p>
        </header>

        <form v-if="!flight.diverted" class="flex flex-wrap items-end gap-2 text-sm" @submit.prevent="submit">
            <label>Arrival delay to propagate (min)
                <input v-model.number="input" type="number" min="0" max="1440" step="1" required class="ml-1 w-24 rounded border border-slate-300 bg-white px-1 py-0.5" />
            </label>
            <button type="submit" class="rounded border border-slate-300 bg-white px-2 py-0.5">Propagate</button>
            <Link v-if="whatIf" :href="`/flights/${flight.flight_id}`" class="text-sky-700 underline">Back to the actual delay</Link>
            <p v-if="page.props.errors?.delay" class="w-full text-red-700" role="alert">{{ page.props.errors.delay }}</p>
        </form>

        <p class="text-xs text-slate-500">
            Aircraft-driven delay only: no crew or passenger connections. Each leg is predicted from the previous predicted arrival, the carrier's minimum turn measured from July, and the schedule, with no time made up in the air. At risk means a predicted departure delay of 15 min or more.
        </p>
        <p class="text-xs text-slate-500">{{ CANCEL_RISK_CAVEAT }}</p>

        <p v-if="!legs.length" class="text-slate-500">No later flights on this tail in the loaded data.</p>
        <div v-else class="overflow-x-auto rounded border border-slate-200 bg-white">
            <table class="w-full whitespace-nowrap text-left text-sm">
                <thead class="bg-slate-100 text-xs uppercase text-slate-600">
                    <tr>
                        <th class="px-2 py-1">Leg</th><th class="px-2 py-1">Flight</th><th class="px-2 py-1">Route</th>
                        <th class="px-2 py-1">Sched dep (local)</th><th class="px-2 py-1">Min turn</th><th class="px-2 py-1">Slack</th>
                        <th class="px-2 py-1">Predicted dep delay</th><th class="px-2 py-1">Cancel risk</th>
                        <th class="px-2 py-1" :class="dim">Actual dep delay</th><th class="px-2 py-1" :class="dim">Actual arr delay</th>
                        <th class="px-2 py-1" :class="dim">Actual late-aircraft</th>
                    </tr>
                </thead>
                <tbody>
                    <tr v-for="l in legs" :key="`${l.kind}-${l.flight_id}`" class="border-t border-slate-100 align-top" :class="l.cancelled && 'bg-slate-50 text-slate-500'">
                        <td class="px-2 py-1">{{ l.depth ?? '—' }}</td>
                        <td class="px-2 py-1 whitespace-nowrap">{{ l.carrier }} {{ l.flight_number }}</td>
                        <td class="px-2 py-1 whitespace-nowrap">{{ l.origin }} → {{ l.dest }}</td>
                        <td class="px-2 py-1 whitespace-nowrap" :title="utcTitle(l.sched_dep_utc)">{{ localDate(l.sched_dep_utc, l.origin_tz) }} {{ localTime(l.sched_dep_utc, l.origin_tz) }}</td>
                        <template v-if="l.kind === 'flown'">
                            <td class="px-2 py-1">{{ minutes(l.min_turn) }}</td>
                            <td class="px-2 py-1">{{ minutes(l.slack_min) }}</td>
                            <td class="px-2 py-1">
                                <span v-if="l.at_risk" class="badge bg-amber-100 text-amber-900">{{ l.predicted_dep_delay }} min · at risk</span>
                                <template v-else-if="l.predicted_dep_delay !== null">{{ l.predicted_dep_delay }} min</template>
                                <span v-else class="text-slate-500">not predicted ({{ l.stop_reason }})</span>
                            </td>
                        </template>
                        <td v-else colspan="3" class="px-2 py-1 italic">{{ OUTSIDE[l.kind] }}</td>
                        <td class="px-2 py-1">
                            <span v-if="risk(l).flagged" class="badge bg-red-100 text-red-800">{{ risk(l).text }} · cancel risk</span>
                            <span v-else :class="!risk(l).basis && 'text-slate-500'">{{ risk(l).text }}</span>
                            <div v-if="risk(l).basis" class="text-xs text-slate-500">{{ risk(l).basis }}</div>
                        </td>
                        <td v-if="l.cancelled" colspan="3" class="px-2 py-1" :class="dim">cancelled</td>
                        <template v-else>
                            <td class="px-2 py-1" :class="dim">{{ minutes(l.actual_dep_delay) }}</td>
                            <td class="px-2 py-1" :class="dim">{{ minutes(l.actual_arr_delay) }}</td>
                            <td class="px-2 py-1" :class="dim">{{ l.actual_late_aircraft === null ? 'not reported' : `${l.actual_late_aircraft} min` }}</td>
                        </template>
                    </tr>
                </tbody>
            </table>
        </div>

        <p v-if="stop" class="text-sm text-slate-700">{{ STOPS[stop] ?? stop }}</p>
        <p v-if="whatIf" class="text-xs text-slate-500">Actual columns are dimmed and not comparable: they record what followed the real {{ flight.actual_arr_delay }}-min delay, not this one.</p>
        <DecisionPanel :flight-id="flight.flight_id" :legs="legs" :what-if-delay="whatIf ? delay : null" :decisions="decisions" />
    </main>
</template>
```

Compared with the old file, the changes are: the risk import and the `cancelThreshold` prop, `OUTSIDE`, the second caveat, the `Cancel risk` column, `scheduled` rows sharing the cancelled-row layout for the three prediction cells, actuals shown as `cancelled` from `l.cancelled`, and `—` for no depth.

- [ ] **Step 5: Run the tests and the build**

Run: `./vendor/bin/pest tests/Feature/FlightImpactTest.php && npm run build`
Expected: all pass, and the build succeeds.

- [ ] **Step 6: Commit**

```bash
git add web/app/Http/Controllers/FlightImpactController.php web/resources/js/Pages/FlightImpact.vue web/tests/Feature/FlightImpactTest.php
git commit -m "feat: cancel-risk column on FlightImpact, with scheduled legs outside the chain"
```

---

### Task 4: Decision pages

**Files:**
- Modify: `web/app/Http/Controllers/DecisionController.php` (`show`), `web/resources/js/Pages/Decision.vue`, `web/resources/js/Pages/Decisions.vue`, `web/tests/Feature/DecisionTest.php`

**Interfaces:**
- Consumes: `decision_review.flagged_cancel_risk` and `.cancel_risk_recorded`, `decision_legs.cancel_risk` and `.cancel_risk_basis`, and Task 2's `cancelRisk`.
- Produces: Decision prop `cancelThreshold`.

- [ ] **Step 1: Write the failing Pest tests** (append to `web/tests/Feature/DecisionTest.php`)

```php
it('freezes the cancel risk with the decision and counts the flagged legs', function () {
    decision(['action' => 'accept_delay', 'target' => null]);

    $this->get('/decisions')->assertInertia(fn (Assert $page) => $page
        ->where('decisions.0.cancel_risk_recorded', true)
        ->where('decisions.0.flagged_cancel_risk', 3));  // 49.5%, 51.4% and 46.7%, all at or above 18.3%
    $this->get('/decisions/'.pestDecisionId())->assertInertia(fn (Assert $page) => $page
        ->where('cancelThreshold', 0.183)
        ->where('legs.1.cancel_risk_basis', 'DL, 1309 samples')
        ->where('legs.4.cancel_risk', null));
});

it('marks decisions logged before cancellation risk', function () {
    $old = DB::select("select decision_id, cancel_risk_recorded, flagged_cancel_risk from decision_review where author = 'walkthrough' and decision_id <= 50");
    expect($old)->toHaveCount(3)
        ->and(collect($old)->every(fn ($d) => $d->cancel_risk_recorded === false && $d->flagged_cancel_risk === 0))->toBeTrue();
    $this->get('/decisions/50')->assertInertia(fn (Assert $page) => $page->where('decision.cancel_risk_recorded', false));
});

it('takes a scheduled leg outside the chain as the target', function () {
    $bwi = bwi();
    $iah = DB::selectOne("select flight_id from propagate(?) where kind = 'scheduled' and flight_number = '1069'", [$bwi])->flight_id;
    $this->post("/flights/{$bwi}/decisions", ['action' => 'cancel_leg', 'target' => $iah, 'reason' => 'flagged at cancel risk', 'author' => 'pest']);

    $d = DB::selectOne("select target_kind, match_label, cancelled from decision_review where author = 'pest'");
    expect([$d->target_kind, $d->match_label, $d->cancelled])->toBe(['scheduled', 'airline did the same', 0]);
});
```

- [ ] **Step 2: Run them to see them fail**

Run: `./vendor/bin/pest tests/Feature/DecisionTest.php`
Expected: the first fails on `cancelThreshold`. The second and third may already pass after Task 1's migration, because they test the database. Note which.

- [ ] **Step 3: The controller.** In `DecisionController::show`, replace the render line:

```php
        return Inertia::render('Decision', [
            'decision' => $d,
            'legs' => $legs,
            'cancelThreshold' => (float) DB::selectOne('select cancel_risk_threshold() as t')->t,
        ]);
```

- [ ] **Step 4: `web/resources/js/Pages/Decision.vue`.** In the script:

```js
import { CANCEL_RISK_CAVEAT, cancelRisk } from '../lib/risk.js';

const props = defineProps({ decision: Object, legs: Array, cancelThreshold: Number });
const risk = (l) => cancelRisk(l, props.cancelThreshold);
```

(This replaces the existing `defineProps` line. Keep the other imports.)

In the Outcome section, replace the chain line:

```html
            <p>
                Chain: {{ d.predicted_at_risk }} predicted at risk · {{ d.actually_late }} left 15+ min late · {{ d.cancelled }} cancelled
                · <template v-if="d.cancel_risk_recorded">{{ d.flagged_cancel_risk }} flagged at cancellation risk</template><template v-else>recorded before cancellation risk</template>.
            </p>
```

After `<p class="text-xs text-slate-500">{{ HINDSIGHT }}</p>`, add:

```html
        <p class="text-xs text-slate-500">{{ CANCEL_RISK_CAVEAT }} Risks here are frozen as the decision saw them; the badge uses today's threshold.</p>
```

In the table header, after the `Predicted dep delay (frozen)` header, add `<th :class="cell">Cancel risk (frozen)</th>`. In each row:
- the depth cell becomes `<td :class="cell">{{ l.depth ?? '—' }}</td>`
- in the predicted cell, after the `cancelled` line, add `<template v-else-if="l.kind === 'scheduled'">outside the chain, not predicted</template>`
- after the predicted cell, add:

```html
                        <td :class="cell">
                            <template v-if="l.kind === 'selected'">—</template>
                            <span v-else-if="!d.cancel_risk_recorded" class="text-slate-500">recorded before cancellation risk</span>
                            <template v-else>
                                <span v-if="risk(l).flagged" class="badge bg-red-100 text-red-800">{{ risk(l).text }} · cancel risk</span>
                                <span v-else :class="!risk(l).basis && 'text-slate-500'">{{ risk(l).text }}</span>
                                <div v-if="risk(l).basis" class="text-xs text-slate-500">{{ risk(l).basis }}</div>
                            </template>
                        </td>
```

The row class `l.kind === 'cancelled' && 'text-slate-500'` becomes `l.actual_cancelled && 'text-slate-500'`, so a cancelled scheduled leg is greyed too.

- [ ] **Step 5: `web/resources/js/Pages/Decisions.vue`.** After the `Outcome` header, add `<th :class="cell">Cancel risk</th>`. After the outcome cell, add:

```html
                        <td :class="cell">
                            <template v-if="d.cancel_risk_recorded">{{ d.flagged_cancel_risk }} flagged</template>
                            <span v-else class="text-slate-500">recorded before cancellation risk</span>
                        </td>
```

- [ ] **Step 6: Run everything in `web/`**

Run: `./vendor/bin/pest && npm test && npm run build`
Expected: all pass. The existing DecisionTest assertions are unchanged, because N102DN's DEN→ATL chain has no `scheduled` rows.

- [ ] **Step 7: Commit**

```bash
git add web/app/Http/Controllers/DecisionController.php web/resources/js/Pages/Decision.vue web/resources/js/Pages/Decisions.vue web/tests/Feature/DecisionTest.php
git commit -m "feat: frozen cancel risk and flagged totals on the decision pages"
```

---

### Task 5: Walkthrough, screenshots, decisions, status

**Files:**
- Modify: `web/scripts/screenshots.sh`, `docs/screenshots/*.png` (regenerated), `docs/phase-6-plan.md`, `DECISIONS.md`, `CLAUDE.md`

- [ ] **Step 1: Run the app and walk N102DN through it**

From `web/`: `php artisan serve` (in the background), then open `http://127.0.0.1:8000/flights/371994` (N102DN's DEN→ATL; check the id with `select flight_id from app_read.tail_legs where tail_number = 'N102DN' and leg_day = '2024-07-19' and origin = 'DEN'`). Check that:
- the three cancelled legs show 49.5%, 51.4% and 46.7%, with red badges and `DL, … samples` under them
- ATL→BWI shows `not scored`
- `?delay=600` keeps the same three rates, because the bucket is still `240+`

Then open ATL→BWI (`/flights/372283`) and check:
- BWI→ATL is badged at 20.8%
- the two `—` rows (IAH→ATL, ATL→DTW) are badged at 23.8% and 28.0% and read `cancelled`

- [ ] **Step 2: Log one walkthrough decision** from the DEN→ATL page's form, or, without a browser, through the same function as the app's role: `psql -h localhost -d flightops -c "SET ROLE flightops_app; SELECT app_read.record_decision(<DEN→ATL id>, NULL, 'cancel_leg', <ATL→CLE id>, '<reason>', 'walkthrough')"`. Use action **Cancel a leg**, target ATL→CLE (DL 1487), reason `Walkthrough: cancel risk 49.5% on a 316-min inbound with Delta stress at 50%. Cancel ATL→CLE early to protect the rest of the rotation.`, author `walkthrough`. It is kept, like the three before it. Check that its page shows `airline did the same`, `3 flagged at cancellation risk` and the frozen rates. Note its decision id.

- [ ] **Step 3: Update `web/scripts/screenshots.sh`**, after the existing flight shot:

```bash
# shortcut: N102DN's ATL->BWI by flight_id; look it up if a rebuild renumbers flights
shot flight-N102DN-BWI-2024-07-19 /flights/372283 1440,900
```

and after the existing decision shot:

```bash
# shortcut: the phase 6 walkthrough decision by id (cancel ATL->CLE on cancel risk); look it up by author 'walkthrough'
shot decision-N102DN-cancel-risk /decisions/<id from step 2> 1440,1000
```

Run: `scripts/screenshots.sh`, with the server running. Then `python -m flightops live` is not needed: the live shot keeps its stale banner, as before. Look at `flight-N102DN-2024-07-19.png`, `flight-N102DN-BWI-2024-07-19.png`, `decisions.png`, `decision-N102DN-what-if.png` (which now reads `recorded before cancellation risk`) and the new decision shot. Stop the server.

- [ ] **Step 4: Write the walkthrough into the Notes** of `docs/phase-6-plan.md`, as rows: N102DN's DEN→ATL page (the three rates and the unscored ATL→BWI), ATL→BWI's scheduled rows, and the logged decision with its id and match label.

- [ ] **Step 5: `DECISIONS.md` entries:**
  - **Show scored legs outside the chain as `scheduled` rows in `propagate`:** chose one table with a `—` depth over a separate panel. Gave up: a propagation table that holds only the flown chain and its gaps. Why: the chain alone hides about half the cancelled legs at ranks 2-3, and rows in `propagate` are frozen by `record_decision` with no change to it. Revisit if the rows confuse users of the chain. Then split them into a panel with its own frozen table.
  - **Mark decisions logged before cancellation risk with a column, not a NULL check:** `app.decision.cancel_risk_recorded`, false for the rows that existed at migration 027 and true afterwards. Gave up: nothing visible. Why: a later decision on a flight the backtest never scored also has all-NULL risk, so NULLs alone can't tell "before" from "not scored". Revisit: never.

- [ ] **Step 6: Update `CLAUDE.md` Status.** Phase 6 is done (on its branch until merged). The decision log holds four kept walkthrough decisions. Next action: read `docs/roadmap.md` and ask the user whether to start phase 7 or go to phase 8. Update `docs/screenshots/` mentions if the file list changed.

- [ ] **Step 7: Final verification**

Run: from `pipelines/`, `uv run --env-file ../.env pytest`. From `web/`, `./vendor/bin/pest && npm test && npm run build`. From `pipelines/`, `uv run --env-file ../.env python -m flightops report && git status --short ../docs/*.md`.
Expected: all pass, and no generated report changes (027 changes no table the reports read, and `propagate`'s new rows aren't flown).

- [ ] **Step 8: Commit**

```bash
git add web/scripts/screenshots.sh docs/screenshots docs/phase-6-plan.md DECISIONS.md CLAUDE.md
git commit -m "docs: phase 6 walkthrough, screenshots, decisions and status"
```
