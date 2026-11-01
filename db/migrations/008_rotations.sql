CREATE TABLE ontology.rotation_leg (
    flight_id      bigint PRIMARY KEY REFERENCES ontology.flight,
    tail_number    text NOT NULL,
    leg_seq        integer NOT NULL,
    prev_flight_id bigint REFERENCES ontology.flight,
    connects       boolean,
    gap_minutes    integer,
    break_cause    text,
    touched_atl    boolean NOT NULL,
    UNIQUE (tail_number, leg_seq)
);

CREATE VIEW ontology.atl_rotation_leg AS
SELECT * FROM ontology.rotation_leg WHERE touched_atl;
