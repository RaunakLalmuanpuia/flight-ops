CREATE TABLE raw.opensky_flight (
    "icao24" text,
    "firstseen" text,
    "estdepartureairport" text,
    "lastseen" text,
    "estarrivalairport" text,
    "callsign" text,
    "estdepartureairporthorizdistance" text,
    "estdepartureairportvertdistance" text,
    "estarrivalairporthorizdistance" text,
    "estarrivalairportvertdistance" text,
    "departureairportcandidatescount" text,
    "arrivalairportcandidatescount" text,
    source_file text NOT NULL,
    source_sha256 text NOT NULL,
    loaded_at timestamptz NOT NULL DEFAULT now()
);
