CREATE TABLE staging.metar (
    station_icao   text NOT NULL,
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
    PRIMARY KEY (station_icao, observed_at)
);

CREATE TABLE staging.taf (
    station_icao text NOT NULL,
    product_id   text NOT NULL,
    issued_at    timestamptz NOT NULL,
    valid_from   timestamptz NOT NULL,
    valid_to     timestamptz,
    forecast_type text NOT NULL,
    is_tempo     boolean NOT NULL,
    raw_text     text NOT NULL
);
