-- Read-only views for the app. Holds no data; pipelines own it, the app reads it as flightops_app.
CREATE SCHEMA app_read;

CREATE FUNCTION app_read.break_label(cause text) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE cause
        WHEN 'likely_unreported_flying' THEN 'Likely flew legs BTS does not report'
        WHEN 'long_gap_unreported_or_out_of_service' THEN 'Over a day unaccounted for: unreported flying or out of service'
        WHEN 'after_diversion' THEN 'Repositioned after a diversion'
        WHEN 'overlap_data_error' THEN 'Departed before the previous leg landed: likely a data error'
        WHEN 'short_gap_likely_data_error' THEN 'Under 2 hours to reach this station: likely a data error'
        ELSE cause
    END
$$;

-- Days the app offers. BTS flight_date, so an ATL day at either edge can be partial (see DECISIONS.md).
CREATE VIEW app_read.day_range AS
SELECT min(flight_date) AS first_day, max(flight_date) AS last_day FROM ontology.flight;

-- A flight touching ATL belongs to the ATL local day of its scheduled ATL event.
CREATE VIEW app_read.atl_flight AS
SELECT f.*, e.direction, e.atl_event_utc,
       (e.atl_event_utc AT TIME ZONE atl.timezone)::date AS atl_day,
       extract(hour FROM e.atl_event_utc AT TIME ZONE atl.timezone)::int AS atl_hour,
       CASE WHEN f.cancelled THEN 'cancelled'
            WHEN f.diverted THEN 'diverted'
            WHEN CASE e.direction WHEN 'dep' THEN f.dep_delay_min ELSE f.arr_delay_min END >= 15 THEN 'delayed'
            ELSE 'on_time' END AS status,
       (SELECT jsonb_object_agg(d.cause, d.minutes) FROM ontology.delay d WHERE d.flight_id = f.flight_id) AS delays,
       m.observed_at AS metar_observed_at, m.staleness_min AS metar_staleness_min,
       m.raw_text AS metar_raw_text, m.adverse AS metar_adverse
FROM ontology.flight f
JOIN ontology.airport atl ON atl.iata_code = 'ATL' AND atl.airport_id IN (f.origin_airport_id, f.dest_airport_id)
CROSS JOIN LATERAL (
    SELECT CASE WHEN f.origin_airport_id = atl.airport_id THEN 'dep' ELSE 'arr' END AS direction,
           CASE WHEN f.origin_airport_id = atl.airport_id THEN f.sched_dep_utc ELSE f.sched_arr_utc END AS atl_event_utc
) e
LEFT JOIN LATERAL (
    -- the METAR at the actual ATL event when there was one, else at the scheduled one
    SELECT fw.observed_at, fw.staleness_min, w.raw_text, ontology.is_adverse(w) AS adverse
    FROM ontology.flight_weather fw
    JOIN ontology.weather_observation w USING (airport_id, observed_at)
    WHERE fw.flight_id = f.flight_id AND fw.airport_id = atl.airport_id
      AND fw.event = CASE e.direction WHEN 'dep' THEN 'departure' ELSE 'arrival' END
    ORDER BY fw.basis = 'actual' DESC
    LIMIT 1
) m ON true;

CREATE VIEW app_read.hub_day_hourly AS
SELECT atl_day, atl_hour, direction,
       count(*) AS scheduled,
       count(*) FILTER (WHERE status <> 'cancelled') AS operated,
       count(*) FILTER (WHERE status = 'on_time') AS on_time,
       count(*) FILTER (WHERE status = 'delayed') AS delayed,
       count(*) FILTER (WHERE status = 'diverted') AS diverted,
       count(*) FILTER (WHERE status = 'cancelled') AS cancelled
FROM app_read.atl_flight
GROUP BY 1, 2, 3;

CREATE VIEW app_read.hub_day_weather AS
SELECT (w.observed_at AT TIME ZONE a.timezone)::date AS atl_day,
       extract(hour FROM w.observed_at AT TIME ZONE a.timezone)::int AS atl_hour,
       w.observed_at, ontology.is_adverse(w) AS adverse,
       w.wind_dir_deg, w.wind_kt, w.gust_kt, w.visibility_sm, w.ceiling_ft, w.weather, w.raw_text
FROM ontology.weather_observation w
JOIN ontology.airport a USING (airport_id)
WHERE a.iata_code = 'ATL';

CREATE VIEW app_read.hub_day_flights AS
SELECT f.atl_day, f.atl_hour, f.direction, f.status, f.flight_id, c.code AS carrier, f.flight_number,
       o.iata_code AS other_station, l.iata_code AS landed_station, f.tail_number,
       f.sched_dep_utc, f.sched_arr_utc, f.actual_dep_utc, f.actual_arr_utc,
       f.dep_delay_min, f.arr_delay_min, f.cancellation_code, f.delays,
       f.metar_observed_at, f.metar_staleness_min, f.metar_raw_text, f.metar_adverse,
       coalesce(f.metar_staleness_min > 90, true) AS metar_stale,  -- no METAR at all counts as stale
       f.block_mismatch,
       f.aircraft_id IS NULL AS aircraft_unresolved,
       coalesce(f.aircraft_link_confidence = 'medium', false) AS aircraft_medium_confidence,
       coalesce(NOT r.connects, false) AS rotation_break
FROM app_read.atl_flight f
JOIN ontology.carrier c ON c.carrier_id = f.carrier_id
JOIN ontology.airport o ON o.airport_id = CASE f.direction WHEN 'dep' THEN f.dest_airport_id ELSE f.origin_airport_id END
LEFT JOIN ontology.airport l ON l.airport_id = f.landed_airport_id
LEFT JOIN ontology.rotation_leg r ON r.flight_id = f.flight_id;

CREATE VIEW app_read.hub_day_caveats AS
SELECT atl_day,
       count(*) FILTER (WHERE metar_stale) AS metar_stale,
       count(*) FILTER (WHERE block_mismatch) AS block_mismatch,
       count(*) FILTER (WHERE aircraft_unresolved) AS aircraft_unresolved,
       count(*) FILTER (WHERE aircraft_medium_confidence) AS aircraft_medium_confidence,
       count(*) FILTER (WHERE rotation_break) AS rotation_break
FROM app_read.hub_day_flights
GROUP BY 1;

-- Every flown leg of a tail that touched ATL, plus its cancelled flights, which never join a rotation.
CREATE VIEW app_read.tail_legs AS
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
       a.metar_observed_at, a.metar_staleness_min, a.metar_raw_text, a.metar_adverse
FROM ontology.flight f
JOIN ontology.airport atl ON atl.iata_code = 'ATL'
JOIN ontology.carrier c ON c.carrier_id = f.carrier_id
JOIN ontology.airport o ON o.airport_id = f.origin_airport_id
JOIN ontology.airport d ON d.airport_id = f.dest_airport_id
LEFT JOIN ontology.airport l ON l.airport_id = f.landed_airport_id
LEFT JOIN ontology.rotation_leg r ON r.flight_id = f.flight_id
LEFT JOIN ontology.flight p ON p.flight_id = r.prev_flight_id
LEFT JOIN ontology.airport pl ON pl.airport_id = p.landed_airport_id
LEFT JOIN app_read.atl_flight a ON a.flight_id = f.flight_id
WHERE f.tail_number IN (SELECT tail_number FROM ontology.rotation_leg WHERE touched_atl)
  AND (r.flight_id IS NOT NULL OR f.cancelled);

-- shortcut: a tail unresolved for two reasons on different dates repeats its unresolved flights under each; fix if the tail header ever shows counts.
CREATE VIEW app_read.tail_aircraft AS
SELECT f.tail_number, a.aircraft_id, a.manufacturer, a.model,
       f.aircraft_link_method AS method, f.aircraft_link_confidence AS confidence,
       u.reason AS unresolved_reason, count(*) AS flights
FROM ontology.flight f
LEFT JOIN ontology.aircraft a ON a.aircraft_id = f.aircraft_id
LEFT JOIN dq.unresolved_link u ON u.entity = 'tail' AND u.key = f.tail_number AND f.aircraft_id IS NULL
WHERE f.tail_number IN (SELECT tail_number FROM ontology.rotation_leg WHERE touched_atl)
GROUP BY 1, 2, 3, 4, 5, 6, 7;

-- The app's login. Views run with their owner's rights, so SELECT on app_read is all it needs.
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'flightops_app') THEN
        CREATE ROLE flightops_app LOGIN;
    END IF;
END $$;
GRANT USAGE ON SCHEMA app_read TO flightops_app;
GRANT SELECT ON ALL TABLES IN SCHEMA app_read TO flightops_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA app_read GRANT SELECT ON TABLES TO flightops_app;
