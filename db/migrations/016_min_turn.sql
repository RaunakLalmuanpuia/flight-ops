-- Shortest turn each carrier's aircraft managed when the aircraft was the constraint, measured from loaded data.
CREATE TABLE ontology.min_turn (
    carrier_id bigint REFERENCES ontology.carrier,  -- NULL: all carriers together
    samples    integer NOT NULL,
    p10        integer NOT NULL,
    p25        integer NOT NULL,
    p50        integer NOT NULL,
    UNIQUE NULLS NOT DISTINCT (carrier_id)
);
