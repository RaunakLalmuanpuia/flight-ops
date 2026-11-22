-- Tail-page gaps from the final review. Only appends columns and changes aircraft_unresolved; hub_day_caveats follows hub_day_flights.
CREATE OR REPLACE VIEW app_read.hub_day_flights AS
SELECT f.atl_day, f.atl_hour, f.direction, f.status, f.flight_id, c.code AS carrier, f.flight_number,
       o.iata_code AS other_station, l.iata_code AS landed_station, f.tail_number,
       f.sched_dep_utc, f.sched_arr_utc, f.actual_dep_utc, f.actual_arr_utc,
       f.dep_delay_min, f.arr_delay_min, f.cancellation_code, f.delays,
       f.metar_observed_at, f.metar_staleness_min, f.metar_raw_text, f.metar_adverse,
       coalesce(f.metar_staleness_min > 90, true) AS metar_stale,  -- no METAR at all counts as stale
       f.block_mismatch,
       f.tail_number IS NOT NULL AND f.aircraft_id IS NULL AS aircraft_unresolved,
       coalesce(f.aircraft_link_confidence = 'medium', false) AS aircraft_medium_confidence,
       coalesce(NOT r.connects, false) AS rotation_break,
       f.tail_number IS NULL AS no_tail
FROM app_read.atl_flight f
JOIN ontology.carrier c ON c.carrier_id = f.carrier_id
JOIN ontology.airport o ON o.airport_id = CASE f.direction WHEN 'dep' THEN f.dest_airport_id ELSE f.origin_airport_id END
LEFT JOIN ontology.airport l ON l.airport_id = f.landed_airport_id
LEFT JOIN ontology.rotation_leg r ON r.flight_id = f.flight_id;

CREATE OR REPLACE VIEW app_read.hub_day_caveats AS
SELECT atl_day,
       count(*) FILTER (WHERE metar_stale) AS metar_stale,
       count(*) FILTER (WHERE block_mismatch) AS block_mismatch,
       count(*) FILTER (WHERE aircraft_unresolved) AS aircraft_unresolved,
       count(*) FILTER (WHERE aircraft_medium_confidence) AS aircraft_medium_confidence,
       count(*) FILTER (WHERE rotation_break) AS rotation_break,
       count(*) FILTER (WHERE no_tail) AS no_tail
FROM app_read.hub_day_flights
GROUP BY 1;

CREATE OR REPLACE VIEW app_read.tail_legs AS
SELECT f.tail_number, r.leg_seq, f.flight_id,
       (f.sched_dep_utc AT TIME ZONE atl.timezone)::date AS leg_day,
       c.code AS carrier, f.flight_number,
       o.iata_code AS origin, o.timezone AS origin_tz, d.iata_code AS dest, d.timezone AS dest_tz,
       l.iata_code AS landed,
       f.sched_dep_utc, f.sched_arr_utc, f.actual_dep_utc, f.actual_arr_utc,
       f.cancelled, f.cancellation_code, f.diverted, f.dep_delay_min, f.arr_delay_min,
       (SELECT jsonb_object_agg(x.cause, x.minutes) FROM ontology.delay x WHERE x.flight_id = f.flight_id) AS delays,
       r.connects, r.gap_minutes, r.break_cause, app_read.break_label(r.break_cause) AS break_label,
       pl.iata_code AS prev_station,
       a.metar_observed_at, a.metar_staleness_min, a.metar_raw_text, a.metar_adverse,
       row_number() OVER (PARTITION BY f.tail_number ORDER BY coalesce(f.actual_dep_utc, f.sched_dep_utc), f.flight_id) AS leg_order,
       f.aircraft_id, ac.manufacturer, ac.model, f.aircraft_link_method, f.aircraft_link_confidence,
       l.timezone AS landed_tz
FROM ontology.flight f
JOIN ontology.airport atl ON atl.iata_code = 'ATL'
JOIN ontology.carrier c ON c.carrier_id = f.carrier_id
JOIN ontology.airport o ON o.airport_id = f.origin_airport_id
JOIN ontology.airport d ON d.airport_id = f.dest_airport_id
LEFT JOIN ontology.airport l ON l.airport_id = f.landed_airport_id
LEFT JOIN ontology.rotation_leg r ON r.flight_id = f.flight_id
LEFT JOIN ontology.flight p ON p.flight_id = r.prev_flight_id
LEFT JOIN ontology.airport pl ON pl.airport_id = p.landed_airport_id
LEFT JOIN ontology.aircraft ac ON ac.aircraft_id = f.aircraft_id
LEFT JOIN app_read.atl_flight a ON a.flight_id = f.flight_id
WHERE f.tail_number IN (SELECT tail_number FROM ontology.rotation_leg WHERE touched_atl)
  AND (r.flight_id IS NOT NULL OR f.cancelled);

CREATE OR REPLACE VIEW app_read.tail_aircraft AS
SELECT f.tail_number, a.aircraft_id, a.manufacturer, a.model,
       f.aircraft_link_method AS method, f.aircraft_link_confidence AS confidence,
       u.reason AS unresolved_reason, count(*) AS flights,
       min((f.sched_dep_utc AT TIME ZONE atl.timezone)::date) AS first_day,
       max((f.sched_dep_utc AT TIME ZONE atl.timezone)::date) AS last_day
FROM ontology.flight f
JOIN ontology.airport atl ON atl.iata_code = 'ATL'
LEFT JOIN ontology.aircraft a ON a.aircraft_id = f.aircraft_id
LEFT JOIN dq.unresolved_link u ON u.entity = 'tail' AND u.key = f.tail_number AND f.aircraft_id IS NULL
WHERE f.tail_number IN (SELECT tail_number FROM ontology.rotation_leg WHERE touched_atl)
GROUP BY 1, 2, 3, 4, 5, 6, 7;
