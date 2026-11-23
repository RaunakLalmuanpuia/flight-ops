TRUNCATE ontology.rotation_leg;

WITH atl AS (SELECT airport_id FROM ontology.airport WHERE iata_code = 'ATL'),
atl_tails AS (
    -- Includes cancelled flights: an aircraft assigned to ATL and cancelled still touched the hub's plan.
    -- Per calendar month, so adding a month never changes an earlier month's ATL-tail set (DECISIONS.md).
    SELECT DISTINCT tail_number, date_trunc('month', flight_date) AS month FROM ontology.flight
    WHERE tail_number IS NOT NULL
      AND (origin_airport_id IN (SELECT airport_id FROM atl) OR dest_airport_id IN (SELECT airport_id FROM atl))
),
legs AS (
    SELECT f.flight_id, f.tail_number, f.flight_date, f.origin_airport_id, f.actual_dep_utc,
           row_number() OVER w AS leg_seq,
           lag(f.flight_id) OVER w AS prev_flight_id,
           lag(f.landed_airport_id) OVER w AS prev_landed,
           lag(f.actual_arr_utc) OVER w AS prev_arr,
           lag(f.diverted) OVER w AS prev_diverted
    FROM ontology.flight f
    WHERE NOT f.cancelled AND f.tail_number IS NOT NULL
    WINDOW w AS (PARTITION BY f.tail_number ORDER BY f.actual_dep_utc, f.flight_id)
)
INSERT INTO ontology.rotation_leg
SELECT flight_id, tail_number, leg_seq, prev_flight_id,
       CASE WHEN prev_flight_id IS NOT NULL THEN prev_landed = origin_airport_id END,
       (extract(epoch FROM actual_dep_utc - prev_arr) / 60)::int,
       CASE
           WHEN prev_flight_id IS NULL OR prev_landed = origin_airport_id THEN NULL
           WHEN prev_diverted THEN 'after_diversion'
           WHEN actual_dep_utc < prev_arr THEN 'overlap_data_error'
           WHEN actual_dep_utc - prev_arr < interval '2 hours' THEN 'short_gap_likely_data_error'
           WHEN actual_dep_utc - prev_arr < interval '24 hours' THEN 'likely_unreported_flying'
           ELSE 'long_gap_unreported_or_out_of_service'
       END,
       (tail_number, date_trunc('month', flight_date)) IN (SELECT tail_number, month FROM atl_tails)
FROM legs
ORDER BY tail_number, leg_seq;
