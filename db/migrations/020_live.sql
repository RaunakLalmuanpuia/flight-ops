-- Live collection (phase 4). Kept apart from the July tables: see DECISIONS.md, "Keep live data in its own tables".

CREATE TABLE raw.opensky_state (
    "time" text, "icao24" text, "callsign" text, "origin_country" text, "time_position" text, "last_contact" text,
    "longitude" text, "latitude" text, "baro_altitude" text, "on_ground" text, "velocity" text, "true_track" text,
    "vertical_rate" text, "sensors" text, "geo_altitude" text, "squawk" text, "spi" text, "position_source" text,
    source_file text NOT NULL,
    source_sha256 text NOT NULL,
    loaded_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE raw.awc_metar (
    "icaoid" text, "obstime" text, "reporttime" text, "metartype" text, "rawob" text,
    source_file text NOT NULL,
    source_sha256 text NOT NULL,
    loaded_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE raw.awc_taf (
    "fetched_at" text, "raw_text" text,
    source_file text NOT NULL,
    source_sha256 text NOT NULL,
    loaded_at timestamptz NOT NULL DEFAULT now()
);

-- Today's registry, for live aircraft. staging.faa_record holds only tails that flew in BTS July.
CREATE VIEW staging.v_faa_current AS
SELECT 'N' || trim(m.n_number) AS tail_number, upper(trim(m.mode_s_code_hex)) AS hex,
       trim(m.mfr_mdl_code) AS mfr_mdl_code, trim(t.mfr) AS manufacturer, trim(t.model) AS model
FROM staging.v_faa_master m
LEFT JOIN staging.v_faa_acftref t ON trim(t.code) = trim(m.mfr_mdl_code)
WHERE trim(m.mode_s_code_hex) <> '';

-- ICAO callsign prefixes seen at ATL. BTS gives no ICAO codes: see DECISIONS.md.
CREATE TABLE staging.callsign_prefix (
    prefix      text PRIMARY KEY,
    operator    text NOT NULL,
    bts_carrier text,
    source      text NOT NULL
);
INSERT INTO staging.callsign_prefix (prefix, operator, bts_carrier, source)
SELECT p, o, c, 'ICAO Doc 8585 designator, entered by hand 2026-11-22' FROM (VALUES
    ('DAL', 'Delta Air Lines', 'DL'), ('EDV', 'Endeavor Air', '9E'), ('SKW', 'SkyWest Airlines', 'OO'),
    ('RPA', 'Republic Airways', 'YX'), ('ENY', 'Envoy Air', 'MQ'), ('JIA', 'PSA Airlines', 'OH'),
    ('AAL', 'American Airlines', 'AA'), ('UAL', 'United Airlines', 'UA'), ('SWA', 'Southwest Airlines', 'WN'),
    ('JBU', 'JetBlue Airways', 'B6'), ('NKS', 'Spirit Airlines', 'NK'), ('FFT', 'Frontier Airlines', 'F9'),
    ('AAY', 'Allegiant Air', 'G4'), ('ASA', 'Alaska Airlines', 'AS'), ('HAL', 'Hawaiian Airlines', 'HA'),
    ('ASH', 'Mesa Airlines', NULL), ('GJS', 'GoJet Airlines', NULL), ('PDT', 'Piedmont Airlines', NULL),
    ('FDX', 'FedEx', NULL), ('UPS', 'UPS Airlines', NULL),
    ('KLM', 'KLM', NULL), ('AFR', 'Air France', NULL), ('VIR', 'Virgin Atlantic', NULL),
    ('KAL', 'Korean Air', NULL), ('BAW', 'British Airways', NULL), ('DLH', 'Lufthansa', NULL),
    ('AMX', 'Aeromexico', NULL), ('ACA', 'Air Canada', NULL), ('WJA', 'WestJet', NULL)
) v (p, o, c);

-- Rebuilt every tick from the latest snapshot. No foreign keys: the July rebuild restarts ontology identities.
CREATE TABLE ontology.live_position (
    snapshot_at        timestamptz NOT NULL,
    hex                text NOT NULL,
    callsign           text,
    tail_number        text,
    manufacturer       text,
    model              text,
    resolve_method     text,
    resolve_confidence text,
    unresolved_reason  text,
    operator           text,
    bts_carrier        text,
    operator_reason    text,
    latitude           double precision,
    longitude          double precision,
    position_at        timestamptz,
    on_ground          boolean,
    altitude_ft        integer,
    vertical_rate_fpm  integer,
    distance_nm        numeric,
    bearing_deg        integer
);

CREATE TABLE ontology.live_weather (
    station_icao   text NOT NULL,
    observed_at    timestamptz NOT NULL,
    metar_type     text,
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

CREATE TABLE ontology.live_taf (
    fetched_at timestamptz NOT NULL,
    raw_text   text NOT NULL
);
