CREATE TABLE ontology.flight_weather (
    flight_id     bigint NOT NULL REFERENCES ontology.flight,
    event         text NOT NULL CHECK (event IN ('departure', 'arrival')),
    basis         text NOT NULL CHECK (basis IN ('scheduled', 'actual')),
    event_at      timestamptz NOT NULL,
    airport_id    bigint NOT NULL,
    observed_at   timestamptz NOT NULL,
    staleness_min integer NOT NULL CHECK (staleness_min >= 0),
    PRIMARY KEY (flight_id, event, basis),
    FOREIGN KEY (airport_id, observed_at) REFERENCES ontology.weather_observation (airport_id, observed_at)
);
