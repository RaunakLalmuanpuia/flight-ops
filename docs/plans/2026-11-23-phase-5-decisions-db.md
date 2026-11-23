# Phase 5 Step 1: Decision Log in the Database Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** migration 022 creates the append-only decision log in `app`, the only write path `app_read.record_decision`, and the review views `app_read.decision_legs` and `app_read.decision_review`, all covered by pytest.

**Architecture:** `record_decision` is a `SECURITY DEFINER` plpgsql function. It inserts one `app.decision` row and a frozen copy of `app_read.propagate`'s chain into `app.decision_leg`, then checks the target against that copy, so a refusal rolls the whole call back. There is no foreign key to `ontology`: `build` truncates `ontology.flight` with `RESTART IDENTITY`, so the review views re-match each frozen leg on its natural key (carrier code, flight number, origin IATA, scheduled departure UTC). All 634,613 July flights are distinct on that key.

**Tech Stack:** Postgres SQL migrations in `db/migrations/`, applied by `flightops.db.migrate`; pytest with psycopg 3 in `pipelines/tests/`.

## Global Constraints

- Schema changes go through SQL migrations in `db/migrations/`. This one is `022_decisions.sql`.
- `flightops_app` gets `EXECUTE` on `record_decision` and `SELECT` on the two views (the default privileges from migration 012 grant `SELECT` on new `app_read` views). It gets nothing on `app`, so it can't `INSERT`, `UPDATE` or `DELETE` there.
- Actions are exactly `accept_delay`, `hold_departure`, `swap_aircraft`, `cancel_leg`, `other`.
- No foreign key from `app` to `ontology`.
- Match labels, exactly: `airline did the same`, `airline flew it, +N min`, `airline cancelled it`, `flown, +N min vs predicted +M` (or `flown, +N min, no prediction`), `this tail flew it, +N min (swap not visible)`, `flight not found after rebuild`. NULL when there is no target and the flight is found.
- Tests use the `bts_propagate.csv` fixture with min turn fixed at p10 = 40 for DL, exactly as `tests/test_propagate.py` does. For flight 101 the chain is 102 (predicted +40, at risk, actual dep +45), 103 (+50, at risk, actual +60), 104 (cancelled), 105 (+0, absorbed, actual +0).
- Connections are autocommit (`flightops.db.connect`), so each function call is its own transaction and a refusal leaves nothing behind.
- Run tests from `pipelines/`: `uv run --env-file ../.env pytest`.

---

### Task 1: Decision tables and `record_decision`

**Files:**
- Create: `db/migrations/022_decisions.sql`
- Create: `pipelines/tests/test_decisions.py`

**Interfaces:**
- Consumes: `app_read.propagate(p_flight_id bigint, p_arr_delay_min integer DEFAULT NULL, p_percentile integer DEFAULT 10)` from migration 019. Its columns `carrier`, `origin` and `dest` are the carrier code and the IATA codes.
- Produces:
  - `app.decision (decision_id, flight_id, arr_delay_min, what_if, percentile, action, target_flight_id, reason, author, recorded_at)`
  - `app.decision_leg (decision_id, depth, kind, flight_id, carrier, flight_number, origin, dest, sched_dep_utc, sched_arr_utc, min_turn, slack_min, predicted_dep_delay, predicted_arr_utc, at_risk, stop_reason)`, primary key `(decision_id, flight_id)`
  - `app_read.record_decision(p_flight_id bigint, p_arr_delay_min integer, p_action text, p_target_flight_id bigint, p_reason text, p_author text, p_percentile integer DEFAULT 10) RETURNS bigint`. `p_arr_delay_min` NULL means the actual arrival, as in `propagate`. Refusals raise SQLSTATE `P0001` with the messages below; an unknown action raises `23514` from the check constraint.

- [ ] **Step 1: Write the failing tests**

Create `pipelines/tests/test_decisions.py`:

```python
import psycopg
import pytest

from flightops import pipeline

SNAP = "depth, kind, flight_number, slack_min, predicted_dep_delay, at_risk, stop_reason"


@pytest.fixture
def built(conn, load_fixture):
    # Same setup as test_propagate, so flight 101's chain is known: 102 +40, 103 +50, 104 cancelled, 105 absorbed.
    load_fixture("ourairports_airports", "airports.csv")
    load_fixture("bts_ontime", "bts_propagate.csv")
    pipeline.build(conn)
    conn.execute("truncate ontology.min_turn")
    conn.execute(
        "insert into ontology.min_turn (carrier_id, samples, p10, p25, p50) "
        "select carrier_id, 500, 40, 30, 60 from ontology.carrier where code = 'DL' "
        "union all select null, 1000, 45, 20, 70"
    )
    return conn


def fid(conn, number):
    return conn.execute("select flight_id from ontology.flight where flight_number = %s", (number,)).fetchone()[0]


def record(conn, number, action="accept_delay", target=None, delay=None, reason="inbound late", author="duty controller"):
    target_id = fid(conn, target) if target else None
    return conn.execute(
        "select app_read.record_decision(%s, %s, %s, %s, %s, %s)",
        (fid(conn, number), delay, action, target_id, reason, author),
    ).fetchone()[0]


def test_snapshot_is_the_propagated_chain(built):
    d = record(built, "101")
    snap = built.execute(
        f"select {SNAP} from app.decision_leg where decision_id = %s order by depth, kind = 'flown', sched_dep_utc", (d,)
    ).fetchall()
    assert snap == built.execute(f"select {SNAP} from app_read.propagate(%s)", (fid(built, "101"),)).fetchall()
    assert [r[2] for r in snap] == ["101", "102", "103", "104", "105"]
    assert built.execute(
        "select arr_delay_min, what_if, percentile, action, target_flight_id from app.decision where decision_id = %s", (d,)
    ).fetchone() == (60, False, 10, "accept_delay", None)


def test_what_if_delay_is_frozen_with_its_chain(built):
    d = record(built, "101", delay=0)
    assert built.execute("select arr_delay_min, what_if from app.decision where decision_id = %s", (d,)).fetchone() == (0, True)
    assert built.execute(
        "select flight_number, stop_reason from app.decision_leg where decision_id = %s order by depth", (d,)
    ).fetchall() == [("101", None), ("102", "absorbed")]


def test_reason_and_author_are_trimmed(built):
    d = record(built, "101", reason="  inbound late ", author=" duty controller ")
    assert built.execute("select reason, author from app.decision where decision_id = %s", (d,)).fetchone() == (
        "inbound late",
        "duty controller",
    )


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"action": "accept_delay", "target": "102"}, "takes no target"),
        ({"action": "cancel_leg", "target": "201"}, "not a later leg"),
        ({"action": "cancel_leg", "target": "101"}, "not a later leg"),
        ({"reason": "  "}, "reason is required"),
        ({"author": ""}, "author is required"),
    ],
)
def test_refusals_record_nothing(built, kwargs, message):
    with pytest.raises(psycopg.errors.RaiseException, match=message):
        record(built, "101", **kwargs)
    assert built.execute("select count(*) from app.decision").fetchone() == (0,)
    assert built.execute("select count(*) from app.decision_leg").fetchone() == (0,)


def test_cancelled_flight_has_no_chain_to_decide_on(built):
    with pytest.raises(psycopg.errors.RaiseException, match="no arrival to propagate"):
        record(built, "104")
    assert built.execute("select count(*) from app.decision").fetchone() == (0,)


def test_what_if_on_a_diverted_flight_is_refused(built):
    built.execute("update ontology.flight set diverted = true where flight_number = '101'")
    with pytest.raises(psycopg.errors.RaiseException, match="diverted"):
        record(built, "101", delay=30)


def test_unknown_action_is_refused(built):
    with pytest.raises(psycopg.errors.CheckViolation):
        record(built, "101", action="ground_stop")


def test_app_role_records_only_through_the_function(built):
    flight_id = fid(built, "101")
    built.execute("SET ROLE flightops_app")
    try:
        built.execute(
            "select app_read.record_decision(%s, null, 'accept_delay', null, 'inbound late', 'duty controller')", (flight_id,)
        )
        for stmt in (
            "insert into app.decision (flight_id, what_if, percentile, action, reason, author) "
            "values (1, false, 10, 'other', 'x', 'x')",
            "update app.decision set reason = 'edited'",
            "delete from app.decision",
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                built.execute(stmt)
    finally:
        built.execute("RESET ROLE")
    assert built.execute("select reason from app.decision").fetchall() == [("inbound late",)]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --env-file ../.env pytest tests/test_decisions.py -v`
Expected: every test FAILS with `psycopg.errors.UndefinedFunction` (`function app_read.record_decision(...) does not exist`), or `UndefinedTable` for `app.decision`.

- [ ] **Step 3: Write the migration's first half**

Create `db/migrations/022_decisions.sql`:

```sql
-- Phase 5: operator decisions. The app writes only through app_read.record_decision,
-- so flightops_app has no rights on schema app and the log stays append-only.
CREATE SCHEMA app;

CREATE TABLE app.decision (
    decision_id      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    -- Ids as they were when recorded. No foreign key: build truncates ontology.flight and restarts its ids,
    -- so the review re-matches through the natural key frozen in app.decision_leg.
    flight_id        bigint NOT NULL,
    arr_delay_min    integer,
    what_if          boolean NOT NULL,
    percentile       integer NOT NULL,
    action           text NOT NULL CHECK (action IN ('accept_delay', 'hold_departure', 'swap_aircraft', 'cancel_leg', 'other')),
    target_flight_id bigint,
    reason           text NOT NULL,
    author           text NOT NULL,
    recorded_at      timestamptz NOT NULL DEFAULT now()
);

-- propagate's output as the controller saw it. Actuals are not frozen: the review reads them from ontology.
CREATE TABLE app.decision_leg (
    decision_id         bigint NOT NULL REFERENCES app.decision,
    depth               integer NOT NULL,
    kind                text NOT NULL,
    flight_id           bigint NOT NULL,
    carrier             text NOT NULL,
    flight_number       text NOT NULL,
    origin              text NOT NULL,
    dest                text NOT NULL,
    sched_dep_utc       timestamptz NOT NULL,
    sched_arr_utc       timestamptz,
    min_turn            integer,
    slack_min           integer,
    predicted_dep_delay integer,
    predicted_arr_utc   timestamptz,
    at_risk             boolean,
    stop_reason         text,
    PRIMARY KEY (decision_id, flight_id)
);

-- p_arr_delay_min NULL means the actual arrival, as in propagate. p_percentile defaults to propagate's default.
CREATE FUNCTION app_read.record_decision(
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
        min_turn, slack_min, predicted_dep_delay, predicted_arr_utc, at_risk, stop_reason)
    SELECT v_id, p.depth, p.kind, p.flight_id, p.carrier, p.flight_number, p.origin, p.dest, p.sched_dep_utc, p.sched_arr_utc,
           p.min_turn, p.slack_min, p.predicted_dep_delay, p.predicted_arr_utc, p.at_risk, p.stop_reason
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
REVOKE EXECUTE ON FUNCTION app_read.record_decision(bigint, integer, text, bigint, text, text, integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app_read.record_decision(bigint, integer, text, bigint, text, text, integer) TO flightops_app;
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --env-file ../.env pytest tests/test_decisions.py -v`
Expected: all 12 tests PASS (the parametrized refusal test counts 5).

- [ ] **Step 5: Run the full suite**

Run: `uv run --env-file ../.env pytest`
Expected: all tests PASS. The `conn` fixture applies every migration to a fresh `flightops_test`, so 022 is applied with the rest.

- [ ] **Step 6: Commit**

```bash
git add db/migrations/022_decisions.sql pipelines/tests/test_decisions.py
git commit -m "feat: decision log with record_decision as the only write path"
```

---

### Task 2: Review views, rebuild safety and DECISIONS entries

**Files:**
- Modify: `db/migrations/022_decisions.sql` (append the views; 022 is not applied to the `flightops` database until Step 6, so editing it is safe)
- Modify: `pipelines/tests/test_decisions.py` (append tests)
- Modify: `DECISIONS.md` (append three entries)

**Interfaces:**
- Consumes: `app.decision`, `app.decision_leg` and `app_read.record_decision` from Task 1; the test helpers `built`, `fid` and `record` in `test_decisions.py`.
- Produces (step 2 reads these from Laravel):
  - `app_read.decision_legs`: every `app.decision_leg` column, plus `is_target boolean`, `current_flight_id bigint` (NULL when no longer found), `actual_cancelled boolean`, `actual_dep_delay integer`, `actual_arr_delay integer`.
  - `app_read.decision_review`, one row per decision: `decision_id, recorded_at, author, action, reason, arr_delay_min, what_if, percentile, carrier, flight_number, origin, dest, sched_dep_utc, current_flight_id, flight_found, target_carrier, target_flight_number, target_origin, target_dest, target_sched_dep_utc, target_kind, target_predicted_dep_delay, target_cancelled, target_actual_dep_delay, predicted_at_risk, actually_late, cancelled, match_label`.

- [ ] **Step 1: Write the failing tests**

Append to `pipelines/tests/test_decisions.py`:

```python
def review(conn, decision_id, cols):
    return conn.execute(f"select {cols} from app_read.decision_review where decision_id = %s", (decision_id,)).fetchone()


@pytest.mark.parametrize(
    "action, target, label",
    [
        ("cancel_leg", "104", "airline did the same"),
        ("cancel_leg", "102", "airline flew it, +45 min"),
        ("hold_departure", "103", "flown, +60 min vs predicted +50"),
        ("hold_departure", "104", "airline cancelled it"),
        ("other", "105", "flown, +0 min vs predicted +0"),
        ("swap_aircraft", "102", "this tail flew it, +45 min (swap not visible)"),
        ("swap_aircraft", "104", "airline cancelled it"),
    ],
)
def test_match_label_compares_the_target_with_bts(built, action, target, label):
    assert review(built, record(built, "101", action, target), "match_label") == (label,)


def test_target_without_a_prediction_says_so(built):
    d = record(built, "101", "hold_departure", "102")
    built.execute("update app.decision_leg set predicted_dep_delay = null where decision_id = %s and flight_number = '102'", (d,))
    assert review(built, d, "match_label") == ("flown, +45 min, no prediction",)


def test_accept_delay_has_chain_totals_and_no_label(built):
    d = record(built, "101")
    assert review(built, d, "flight_number, match_label, predicted_at_risk, actually_late, cancelled") == ("101", None, 2, 2, 1)


def test_review_keeps_the_prediction_after_the_model_changes(built):
    d = record(built, "101", "hold_departure", "102")
    built.execute("update ontology.min_turn set p10 = 90")
    assert review(built, d, "target_predicted_dep_delay, match_label") == (40, "flown, +45 min vs predicted +40")


def test_legs_sit_beside_their_actuals(built):
    d = record(built, "101", "cancel_leg", "104")
    assert built.execute(
        "select flight_number, is_target, actual_cancelled, actual_dep_delay from app_read.decision_legs "
        "where decision_id = %s order by depth, kind = 'flown'",
        (d,),
    ).fetchall() == [
        ("101", False, False, 60),
        ("102", False, False, 45),
        ("103", False, False, 60),
        ("104", True, True, None),
        ("105", False, False, 0),
    ]


def test_log_survives_a_rebuild_and_rematches(built):
    d = record(built, "101", "cancel_leg", "104")
    pipeline.build(built)
    assert built.execute("select count(*) from app.decision_leg where decision_id = %s", (d,)).fetchone() == (5,)
    assert review(built, d, "flight_found, current_flight_id, match_label") == (True, fid(built, "101"), "airline did the same")


def test_rematch_uses_the_natural_key_not_the_old_id(built):
    d = record(built, "101", "cancel_leg", "104")
    # A rebuild that renumbered every flight: the frozen ids no longer point at the same rows.
    built.execute("update app.decision set flight_id = flight_id + 1000, target_flight_id = target_flight_id + 1000")
    built.execute("update app.decision_leg set flight_id = flight_id + 1000")
    assert review(built, d, "current_flight_id, match_label") == (fid(built, "101"), "airline did the same")


@pytest.mark.parametrize("action, target", [("accept_delay", None), ("cancel_leg", "104")])
def test_flight_gone_after_rebuild_is_labelled_not_dropped(built, action, target):
    d = record(built, "101", action, target)
    built.execute("update app.decision_leg set flight_number = '999' where decision_id = %s and depth = 0", (d,))
    assert review(built, d, "flight_found, match_label") == (False, "flight not found after rebuild")


def test_app_role_reads_the_review(built):
    record(built, "101")
    built.execute("SET ROLE flightops_app")
    try:
        assert built.execute("select count(*) from app_read.decision_review").fetchone() == (1,)
        assert built.execute("select count(*) from app_read.decision_legs").fetchone() == (5,)
    finally:
        built.execute("RESET ROLE")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --env-file ../.env pytest tests/test_decisions.py -v`
Expected: the Task 1 tests PASS. The new tests FAIL with `psycopg.errors.UndefinedTable: relation "app_read.decision_review" does not exist` (or `decision_legs`).

- [ ] **Step 3: Append the views to the migration**

Append to `db/migrations/022_decisions.sql`:

```sql
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
       n.predicted_at_risk, n.actually_late, n.cancelled,
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
    count(*) FILTER (WHERE x.depth > 0 AND x.actual_cancelled) AS cancelled
    FROM app_read.decision_legs x WHERE x.decision_id = d.decision_id) n;
```

`SELECT` for `flightops_app` comes from migration 012's `ALTER DEFAULT PRIVILEGES IN SCHEMA app_read`; `test_app_role_reads_the_review` checks it.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --env-file ../.env pytest tests/test_decisions.py -v`
Expected: all tests PASS.

- [ ] **Step 5: Append three entries to `DECISIONS.md`**

```markdown
## 2026-11-23: Write decisions through one SQL function
- **Chose:** `app_read.record_decision`, a `SECURITY DEFINER` function that runs `propagate` and stores the decision with a frozen copy of the chain. `flightops_app` gets `EXECUTE` on it and nothing on `app`.
- **Gave up:** Eloquent models and plain inserts from Laravel, so the write path is plpgsql, tested with pytest rather than Pest.
- **Why:** the app's role still can't write anywhere directly, so read-only stays a database guarantee with one audited door, and the snapshot is exactly what `propagate` returned rather than what PHP copied.
- **Revisit if:** the app needs writes that aren't decisions, such as user accounts. Those belong in Laravel-owned tables.

## 2026-11-23: Create the `app` decision tables in a pipelines migration
- **Chose:** `app.decision` and `app.decision_leg` in `db/migrations/022`, beside the views that read them.
- **Gave up:** the convention that Laravel migrations cover `app`. Laravel still owns any future `app` tables of its own.
- **Why:** `app_read.decision_review` joins the log to `ontology`, and one migration order avoids a view that depends on tables from a second migration system.
- **Revisit if:** Laravel adds tables to `app` that pipelines' views need to read.

## 2026-11-23: Keep the decision log append-only, with no foreign key to `ontology`
- **Chose:** no `UPDATE` or `DELETE` for the app, and a correction is a new decision. Frozen legs keep carrier, flight number, origin and scheduled departure, and the review re-matches on those. A decision whose flight is gone is labelled `flight not found after rebuild`.
- **Gave up:** referential integrity, and fixing a typo in place.
- **Why:** `build` truncates `ontology.flight` with `RESTART IDENTITY`. A foreign key would block that or cascade into the log, and stored ids would point at different flights afterwards. The natural key is unique across all 634,613 July flights.
- **Revisit if:** a second month makes the natural key collide, or operators need to amend decisions, which would call for an amendment table rather than edits.
```

- [ ] **Step 6: Run the full suite and apply the migration to the real database**

Run: `uv run --env-file ../.env pytest`
Expected: all tests PASS.

Run: `uv run --env-file ../.env python -m flightops migrate`
Expected: `022_decisions.sql` is listed as applied.

Run: `psql -h localhost flightops -Atc "select count(*) from app_read.decision_review"`
Expected: `0`.

- [ ] **Step 7: Commit**

```bash
git add db/migrations/022_decisions.sql pipelines/tests/test_decisions.py DECISIONS.md
git commit -m "feat: decision review views matched on the natural key"
```
