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
