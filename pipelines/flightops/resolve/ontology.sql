TRUNCATE ontology.propagation_backtest, ontology.min_turn, ontology.flight_weather, ontology.rotation_leg, ontology.delay, ontology.taf_forecast, ontology.weather_observation, ontology.flight,
         ontology.aircraft_registration, ontology.aircraft, ontology.carrier, ontology.airport,
         dq.unresolved_link
RESTART IDENTITY;

INSERT INTO ontology.airport (ident, iata_code, iata_current, icao_code, bts_airport_id, name, latitude, longitude, timezone)
SELECT a.ident, a.bts_code, a.iata_current, a.icao_code,
       (SELECT min(origin_bts_id) FROM staging.flight WHERE origin = a.bts_code),
       a.name, a.latitude, a.longitude, a.tz
FROM staging.airport a ORDER BY a.bts_code;

INSERT INTO ontology.carrier (code, iata_code, dot_id)
SELECT carrier, min(carrier_iata), min(carrier_dot_id) FROM staging.flight GROUP BY 1 ORDER BY 1;

INSERT INTO ontology.aircraft (frame, serial_number, mfr_mdl_code, manufacturer, model)
SELECT DISTINCT ON (r.frame) r.frame, r.serial_number, r.mfr_mdl_code, trim(t.mfr), trim(t.model)
FROM staging.faa_record r LEFT JOIN staging.v_faa_acftref t ON trim(t.code) = r.mfr_mdl_code
ORDER BY r.frame;

INSERT INTO ontology.aircraft_registration (aircraft_id, tail_number, hex, valid_from, valid_to, source)
SELECT a.aircraft_id, r.tail_number, r.hex, r.valid_from, r.valid_to, r.source
FROM staging.faa_record r JOIN ontology.aircraft a USING (frame);

INSERT INTO ontology.flight (
    flight_date, carrier_id, flight_number, origin_airport_id, dest_airport_id, landed_airport_id, crs_dep_local,
    tail_number, aircraft_id, aircraft_link_method, aircraft_link_confidence,
    sched_dep_utc, sched_arr_utc, actual_dep_utc, actual_arr_utc, cancelled, cancellation_code,
    diverted, reached_dest, dep_delay_min, arr_delay_min, block_mismatch)
SELECT f.flight_date, c.carrier_id, f.flight_number, o.airport_id, d.airport_id, l.airport_id, f.crs_dep_local,
       f.tail_number, a.aircraft_id, k.method, k.confidence,
       f.sched_dep_utc, f.sched_arr_utc, f.actual_dep_utc, f.actual_arr_utc, f.cancelled, f.cancellation_code,
       f.diverted, f.reached_dest, f.dep_delay_min, f.arr_delay_min, f.block_mismatch
FROM staging.flight f
JOIN ontology.carrier c ON c.code = f.carrier
JOIN ontology.airport o ON o.iata_code = f.origin
JOIN ontology.airport d ON d.iata_code = f.dest
LEFT JOIN ontology.airport l ON l.iata_code = f.landed_station
LEFT JOIN staging.aircraft_link k ON k.tail_number = f.tail_number AND k.flight_date = f.flight_date
LEFT JOIN ontology.aircraft a ON a.frame = k.frame
ORDER BY f.flight_date, f.carrier, f.flight_number, f.origin, f.crs_dep_local;

-- Reported causes of zero are left out, and a flight with blank causes has no rows.
INSERT INTO ontology.delay (flight_id, cause, minutes)
SELECT o.flight_id, c.cause, c.minutes
FROM staging.flight f
JOIN ontology.carrier cr ON cr.code = f.carrier
JOIN ontology.airport oa ON oa.iata_code = f.origin
JOIN ontology.flight o ON o.flight_date = f.flight_date AND o.carrier_id = cr.carrier_id
    AND o.flight_number = f.flight_number AND o.origin_airport_id = oa.airport_id AND o.crs_dep_local = f.crs_dep_local
CROSS JOIN LATERAL (VALUES
    ('carrier', f.carrier_delay), ('weather', f.weather_delay), ('nas', f.nas_delay),
    ('security', f.security_delay), ('late_aircraft', f.late_aircraft_delay)
) c(cause, minutes)
WHERE c.minutes > 0;

-- Weather stations join through ICAO, which is what METARs and TAFs carry.
INSERT INTO ontology.weather_observation
SELECT a.airport_id, m.observed_at, m.raw_text, m.wind_dir_deg, m.wind_kt, m.gust_kt, m.visibility_sm,
       m.ceiling_ft, m.temp_c, m.dewpoint_c, m.altimeter_inhg, m.weather
FROM staging.metar m JOIN ontology.airport a ON a.icao_code = m.station_icao;

INSERT INTO ontology.taf_forecast
SELECT a.airport_id, t.product_id, t.issued_at, t.valid_from, t.valid_to, t.forecast_type, t.is_tempo, t.raw_text
FROM staging.taf t JOIN ontology.airport a ON a.icao_code = t.station_icao;

INSERT INTO dq.unresolved_link
SELECT 'tail', k.tail_number, k.unresolved_reason, count(*)
FROM staging.aircraft_link k
JOIN staging.flight f ON f.tail_number = k.tail_number AND f.flight_date = k.flight_date
WHERE k.unresolved_reason IS NOT NULL
GROUP BY 1, 2, 3;
