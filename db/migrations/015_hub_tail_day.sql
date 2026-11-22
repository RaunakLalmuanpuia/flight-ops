-- Hub rows link to the tail page of the day their leg departs ATL-locally; only appends tail_day.
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
       f.tail_number IS NULL AS no_tail,
       (f.sched_dep_utc AT TIME ZONE atl.timezone)::date AS tail_day
FROM app_read.atl_flight f
JOIN ontology.airport atl ON atl.iata_code = 'ATL'
JOIN ontology.carrier c ON c.carrier_id = f.carrier_id
JOIN ontology.airport o ON o.airport_id = CASE f.direction WHEN 'dep' THEN f.dest_airport_id ELSE f.origin_airport_id END
LEFT JOIN ontology.airport l ON l.airport_id = f.landed_airport_id
LEFT JOIN ontology.rotation_leg r ON r.flight_id = f.flight_id;
