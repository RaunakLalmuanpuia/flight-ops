-- The newest delivery of each source file. A changed file replaces its predecessor, a new month adds to it.
CREATE VIEW staging.current_delivery AS
SELECT DISTINCT ON (table_name, source_file) table_name, source_sha256
FROM dq.ingestion_run
ORDER BY table_name, source_file, id DESC;

CREATE VIEW staging.v_bts AS SELECT r.* FROM raw.bts_ontime r JOIN staging.current_delivery d ON d.table_name = 'bts_ontime' AND d.source_sha256 = r.source_sha256;
CREATE VIEW staging.v_airports AS SELECT r.* FROM raw.ourairports_airports r JOIN staging.current_delivery d ON d.table_name = 'ourairports_airports' AND d.source_sha256 = r.source_sha256;
CREATE VIEW staging.v_faa_master AS SELECT r.* FROM raw.faa_master r JOIN staging.current_delivery d ON d.table_name = 'faa_master' AND d.source_sha256 = r.source_sha256;
CREATE VIEW staging.v_faa_dereg AS SELECT r.* FROM raw.faa_dereg r JOIN staging.current_delivery d ON d.table_name = 'faa_dereg' AND d.source_sha256 = r.source_sha256;
CREATE VIEW staging.v_faa_acftref AS SELECT r.* FROM raw.faa_acftref r JOIN staging.current_delivery d ON d.table_name = 'faa_acftref' AND d.source_sha256 = r.source_sha256;
CREATE VIEW staging.v_metar AS SELECT r.* FROM raw.iem_metar r JOIN staging.current_delivery d ON d.table_name = 'iem_metar' AND d.source_sha256 = r.source_sha256;
CREATE VIEW staging.v_taf AS SELECT r.* FROM raw.iem_taf r JOIN staging.current_delivery d ON d.table_name = 'iem_taf' AND d.source_sha256 = r.source_sha256;

-- BTS codes that OurAirports no longer uses, because OurAirports holds only current codes.
CREATE TABLE staging.airport_code_alias (
    bts_code text PRIMARY KEY,
    ident    text NOT NULL,
    reason   text NOT NULL
);
INSERT INTO staging.airport_code_alias VALUES
    ('PBI', 'KPBI', 'West Palm Beach is PBI in July 2024 BTS, and DJT in current OurAirports');

CREATE TABLE staging.airport (
    ident        text PRIMARY KEY,
    bts_code     text NOT NULL UNIQUE,
    iata_current text,
    icao_code    text,
    name         text NOT NULL,
    latitude     double precision NOT NULL,
    longitude    double precision NOT NULL,
    country      text NOT NULL,
    tz           text
);

-- A local time on a known date. 2400 is midnight at the end of that date.
CREATE FUNCTION staging.local_at(d date, hhmm text, tz text) RETURNS timestamptz
LANGUAGE sql STABLE STRICT AS $$
    SELECT (d + make_interval(hours => hhmm::int / 100, mins => hhmm::int % 100)) AT TIME ZONE tz
$$;

-- A local time whose date is unknown: the occurrence closest to the anchor.
CREATE FUNCTION staging.local_near(hhmm text, tz text, anchor timestamptz) RETURNS timestamptz
LANGUAGE sql STABLE STRICT AS $$
    SELECT staging.local_at(((anchor AT TIME ZONE tz)::date + i)::date, hhmm, tz)
    FROM generate_series(-1, 1) i
    ORDER BY abs(extract(epoch FROM staging.local_at(((anchor AT TIME ZONE tz)::date + i)::date, hhmm, tz) - anchor))
    LIMIT 1
$$;

CREATE TABLE staging.flight (
    flight_date         date NOT NULL,
    carrier             text NOT NULL,
    carrier_iata        text,
    carrier_dot_id      text,
    flight_number       text NOT NULL,
    origin              text NOT NULL,
    dest                text NOT NULL,
    origin_bts_id       text,
    dest_bts_id         text,
    crs_dep_local       text NOT NULL,
    tail_number         text,
    tail_as_delivered   text,
    sched_dep_utc       timestamptz NOT NULL,
    sched_arr_utc       timestamptz,
    actual_dep_utc      timestamptz,
    actual_arr_utc      timestamptz,
    landed_station      text,
    cancelled           boolean NOT NULL,
    cancellation_code   text,
    diverted            boolean NOT NULL,
    reached_dest        boolean,
    dep_delay_min       integer,
    arr_delay_min       integer,
    carrier_delay       integer,
    weather_delay       integer,
    nas_delay           integer,
    security_delay      integer,
    late_aircraft_delay integer,
    block_mismatch      boolean NOT NULL,
    PRIMARY KEY (flight_date, carrier, flight_number, origin, crs_dep_local)
);
