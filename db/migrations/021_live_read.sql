-- Read views for the Live page (phase 4). Same grants as the rest of app_read, from 012's default privileges.

CREATE VIEW app_read.live_aircraft AS
SELECT p.snapshot_at, p.hex, p.callsign, p.tail_number, p.manufacturer, p.model,
       p.resolve_method, p.resolve_confidence, p.unresolved_reason,
       p.operator, p.bts_carrier, p.operator_reason,
       p.on_ground, p.altitude_ft, p.vertical_rate_fpm, p.distance_nm, p.bearing_deg,
       extract(epoch FROM p.snapshot_at - p.position_at)::int AS position_age_s,
       j.day AS july_day
FROM ontology.live_position p
-- Link to TailDay only when the July airframe on this tail carries this hex: a tail can be re-registered.
-- flight_date, not the ATL-local day, so the link always falls inside the loaded range.
LEFT JOIN LATERAL (
    SELECT max(f.flight_date) AS day
    FROM ontology.flight f
    JOIN ontology.aircraft_registration r ON r.aircraft_id = f.aircraft_id AND r.hex = p.hex
    WHERE f.tail_number = p.tail_number
      AND f.tail_number IN (SELECT tail_number FROM ontology.rotation_leg WHERE touched_atl)
) j ON true;

CREATE VIEW app_read.live_weather AS
SELECT w.observed_at, w.metar_type, w.raw_text,
       ontology.is_adverse(ROW(NULL::bigint, w.observed_at, w.raw_text, w.wind_dir_deg, w.wind_kt, w.gust_kt,
           w.visibility_sm, w.ceiling_ft, w.temp_c, w.dewpoint_c, w.altimeter_inhg, w.weather
       )::ontology.weather_observation) AS adverse,
       now() - w.observed_at > interval '90 minutes' AS stale,
       w.wind_dir_deg, w.wind_kt, w.gust_kt, w.visibility_sm, w.ceiling_ft, w.temp_c, w.dewpoint_c, w.weather
FROM ontology.live_weather w;

CREATE VIEW app_read.live_taf AS
SELECT fetched_at, raw_text FROM ontology.live_taf;

-- The last poll that loaded, even when its box was empty, so the page can tell a quiet sky from a stopped loop.
CREATE VIEW app_read.live_status AS
SELECT (SELECT max(loaded_at) FROM dq.ingestion_run WHERE table_name = 'opensky_state') AS states_loaded_at,
       (SELECT max(snapshot_at) FROM ontology.live_position) AS snapshot_at,
       now() AS checked_at;
