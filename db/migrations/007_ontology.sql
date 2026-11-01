CREATE TABLE ontology.airport (
    airport_id     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ident          text NOT NULL UNIQUE,
    iata_code      text NOT NULL UNIQUE,
    iata_current   text,
    icao_code      text,
    bts_airport_id text,
    name           text NOT NULL,
    latitude       double precision NOT NULL,
    longitude      double precision NOT NULL,
    timezone       text NOT NULL
);

CREATE TABLE ontology.carrier (
    carrier_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code       text NOT NULL UNIQUE,
    iata_code  text,
    dot_id     text
);

CREATE TABLE ontology.aircraft (
    aircraft_id   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    frame         text NOT NULL UNIQUE,
    serial_number text NOT NULL,
    mfr_mdl_code  text NOT NULL,
    manufacturer  text,
    model         text
);

CREATE TABLE ontology.aircraft_registration (
    aircraft_id bigint NOT NULL REFERENCES ontology.aircraft,
    tail_number text NOT NULL,
    hex         text,
    valid_from  date,
    valid_to    date,
    source      text NOT NULL
);
CREATE INDEX ON ontology.aircraft_registration (tail_number);

CREATE TABLE ontology.flight (
    flight_id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    flight_date       date NOT NULL,
    carrier_id        bigint NOT NULL REFERENCES ontology.carrier,
    flight_number     text NOT NULL,
    origin_airport_id bigint NOT NULL REFERENCES ontology.airport,
    dest_airport_id   bigint NOT NULL REFERENCES ontology.airport,
    landed_airport_id bigint REFERENCES ontology.airport,
    crs_dep_local     text NOT NULL,
    tail_number       text,
    aircraft_id       bigint REFERENCES ontology.aircraft,
    aircraft_link_method     text,
    aircraft_link_confidence text,
    sched_dep_utc     timestamptz NOT NULL,
    sched_arr_utc     timestamptz,
    actual_dep_utc    timestamptz,
    actual_arr_utc    timestamptz,
    cancelled         boolean NOT NULL,
    cancellation_code text,
    diverted          boolean NOT NULL,
    reached_dest      boolean,
    dep_delay_min     integer,
    arr_delay_min     integer,
    block_mismatch    boolean NOT NULL,
    UNIQUE (flight_date, carrier_id, flight_number, origin_airport_id, crs_dep_local)
);
CREATE INDEX ON ontology.flight (tail_number, actual_dep_utc);
CREATE INDEX ON ontology.flight (origin_airport_id, sched_dep_utc);
CREATE INDEX ON ontology.flight (dest_airport_id, sched_arr_utc);

CREATE TABLE ontology.delay (
    flight_id bigint NOT NULL REFERENCES ontology.flight,
    cause     text NOT NULL,
    minutes   integer NOT NULL,
    PRIMARY KEY (flight_id, cause)
);

CREATE TABLE ontology.weather_observation (
    airport_id     bigint NOT NULL REFERENCES ontology.airport,
    observed_at    timestamptz NOT NULL,
    raw_text       text NOT NULL,
    wind_dir_deg   integer,
    wind_kt        integer,
    gust_kt        integer,
    visibility_sm  numeric,
    ceiling_ft     integer,
    temp_c         integer,
    dewpoint_c     integer,
    altimeter_inhg numeric,
    weather        text[] NOT NULL,
    PRIMARY KEY (airport_id, observed_at)
);

CREATE TABLE ontology.taf_forecast (
    airport_id    bigint NOT NULL REFERENCES ontology.airport,
    product_id    text NOT NULL,
    issued_at     timestamptz NOT NULL,
    valid_from    timestamptz NOT NULL,
    valid_to      timestamptz,
    forecast_type text NOT NULL,
    is_tempo      boolean NOT NULL,
    raw_text      text NOT NULL
);

CREATE TABLE dq.check_result (
    id      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_at  timestamptz NOT NULL,
    name    text NOT NULL,
    blocking boolean NOT NULL,
    passed  boolean,
    value   numeric,
    detail  text
);

CREATE TABLE dq.unresolved_link (
    entity  text NOT NULL,
    key     text NOT NULL,
    reason  text NOT NULL,
    flights bigint NOT NULL,
    PRIMARY KEY (entity, key, reason)
);
