-- One scored (late leg, downstream leg) pair per depth and min-turn percentile. Built by the pipeline because
-- it calls app_read.propagate once per late leg and percentile, too slow for a view.
CREATE TABLE ontology.propagation_backtest (
    late_flight_id       bigint NOT NULL REFERENCES ontology.flight,
    scored_flight_id     bigint NOT NULL REFERENCES ontology.flight,
    depth                integer NOT NULL,
    percentile           integer NOT NULL,
    period               text NOT NULL,     -- 'outage' when the late leg's flight_date is July 19-23
    late_arr_delay       integer NOT NULL,  -- the full-carry baseline
    predicted_dep_delay  integer NOT NULL,
    actual_dep_delay     integer,           -- signed, as BTS reports it
    actual_late_aircraft integer,           -- NULL when not reported (arrival delay under 15)
    swapped              boolean NOT NULL,  -- scored leg was scheduled before the late leg
    PRIMARY KEY (late_flight_id, depth, percentile)
);
