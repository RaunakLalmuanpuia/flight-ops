CREATE TABLE staging.faa_record (
    tail_number   text NOT NULL,
    frame         text NOT NULL,
    serial_number text NOT NULL,
    mfr_mdl_code  text NOT NULL,
    hex           text,
    valid_from    date,
    valid_to      date,
    source        text NOT NULL
);
CREATE INDEX ON staging.faa_record (tail_number);

CREATE TABLE staging.aircraft_link (
    tail_number       text NOT NULL,
    flight_date       date NOT NULL,
    frame             text,
    method            text,
    confidence        text,
    unresolved_reason text,
    PRIMARY KEY (tail_number, flight_date),
    CHECK ((frame IS NULL) = (unresolved_reason IS NOT NULL))
);
