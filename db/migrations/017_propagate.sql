-- Min turn for a carrier at one percentile, falling back to all carriers under 200 samples.
-- Raises only when a downstream leg exists, since propagate calls it per leg.
CREATE FUNCTION app_read.min_turn_for(p_carrier_id bigint, p_percentile integer) RETURNS integer
LANGUAGE plpgsql STABLE SET search_path = pg_catalog, pg_temp AS $$
DECLARE v_turn integer;
BEGIN
    IF p_percentile NOT IN (10, 25, 50) THEN
        RAISE EXCEPTION 'percentile must be 10, 25 or 50, got %', p_percentile USING ERRCODE = 'invalid_parameter_value';
    END IF;
    SELECT CASE p_percentile WHEN 10 THEN m.p10 WHEN 25 THEN m.p25 WHEN 50 THEN m.p50 END INTO v_turn
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
REVOKE EXECUTE ON FUNCTION app_read.min_turn_for(bigint, integer) FROM PUBLIC;

-- Walks the flown chain (prev_flight_id), never the schedule-ordered leg_order used for display.
CREATE FUNCTION app_read.propagate(p_flight_id bigint, p_arr_delay_min integer DEFAULT NULL, p_percentile integer DEFAULT 25)
RETURNS TABLE (
    depth integer, kind text, flight_id bigint, carrier text, flight_number text, origin text, dest text,
    sched_dep_utc timestamptz, sched_arr_utc timestamptz, min_turn integer, slack_min integer,
    predicted_dep_delay integer, predicted_arr_utc timestamptz, at_risk boolean,
    actual_dep_delay integer, actual_arr_delay integer, actual_late_aircraft integer, stop_reason text
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
