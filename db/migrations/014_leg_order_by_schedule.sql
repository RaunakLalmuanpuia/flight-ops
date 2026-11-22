-- Cancelled legs have only a scheduled time, so all legs compare on schedule.
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
       row_number() OVER (PARTITION BY f.tail_number ORDER BY f.sched_dep_utc, f.flight_id) AS leg_order,
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
