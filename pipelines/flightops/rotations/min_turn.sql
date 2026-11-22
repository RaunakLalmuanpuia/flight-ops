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
GROUP BY GROUPING SETS ((carrier_id), ())
HAVING count(*) > 0;  -- the empty grand-total row has no percentiles
