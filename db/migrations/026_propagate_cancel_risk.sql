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
