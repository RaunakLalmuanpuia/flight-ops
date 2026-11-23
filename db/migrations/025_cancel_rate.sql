-- Phase 6 step 2 (docs/phase-6-plan.md): cancellation risk on a late inbound's next scheduled legs.

-- A tail's next legs by schedule, for targets and for removing the own tail from stress.
CREATE INDEX ON ontology.flight (tail_number, sched_dep_utc);

CREATE FUNCTION ontology.delay_bucket(p_delay integer) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE
        WHEN p_delay < 15 THEN '<15'  -- early arrivals included
        WHEN p_delay < 60 THEN '15-59'
        WHEN p_delay < 120 THEN '60-119'
        WHEN p_delay < 240 THEN '120-239'
        WHEN p_delay >= 240 THEN '240+'
    END
$$;

-- shortcut: edges come from the July probe (docs/phase-6-plan.md notes), replace them if Task 3's measurement disagrees.
CREATE FUNCTION ontology.stress_bucket(p_stress numeric) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE WHEN p_stress < 0.02 THEN '<2%' WHEN p_stress < 0.10 THEN '2-10%' WHEN p_stress >= 0.10 THEN '10%+' END
$$;

-- National departures and cancellations per carrier per UTC hour of scheduled departure.
CREATE TABLE ontology.carrier_hour (
    carrier_id bigint NOT NULL REFERENCES ontology.carrier,
    hour       timestamptz NOT NULL,
    departures integer NOT NULL,
    cancelled  integer NOT NULL,
    PRIMARY KEY (carrier_id, hour)
);

-- One row per late-or-not inbound and each of its next three scheduled legs, with the features known at its
-- actual departure t. A cancellation counts as known from its scheduled departure: BTS gives no announcement time.
CREATE VIEW ontology.cancel_pair AS
WITH inbound AS (
    SELECT f.flight_id, f.tail_number, f.carrier_id, f.flight_date, f.sched_dep_utc, f.actual_arr_utc, f.arr_delay_min,
           date_trunc('hour', f.actual_dep_utc, 'UTC') AS t_hour
    FROM ontology.rotation_leg r
    JOIN ontology.flight f USING (flight_id)
    WHERE r.touched_atl AND f.arr_delay_min IS NOT NULL  -- diverted legs have no arrival delay
)
SELECT i.flight_id AS inbound_flight_id, t.flight_id AS target_flight_id, t.rank,
       ontology.period(i.flight_date) AS period, i.carrier_id, i.arr_delay_min,
       -- shortcut: the window is the 3 whole UTC hours before t's hour, not [t - 3h, t); see DECISIONS.md.
       coalesce((h.cancelled - o.cancelled)::numeric / nullif(h.departures - o.departures, 0), 0) AS stress,
       t.cancelled
FROM inbound i
CROSS JOIN LATERAL (
    SELECT x.flight_id, x.sched_dep_utc, x.cancelled, row_number() OVER (ORDER BY x.sched_dep_utc, x.flight_id) AS rank
    FROM ontology.flight x
    WHERE x.tail_number = i.tail_number AND x.sched_dep_utc > i.sched_dep_utc
    ORDER BY x.sched_dep_utc, x.flight_id
    LIMIT 3
) t
CROSS JOIN LATERAL (
    SELECT coalesce(sum(c.departures), 0) AS departures, coalesce(sum(c.cancelled), 0) AS cancelled
    FROM ontology.carrier_hour c
    WHERE c.carrier_id = i.carrier_id AND c.hour >= i.t_hour - interval '3 hours' AND c.hour < i.t_hour
) h
CROSS JOIN LATERAL (
    SELECT count(*) AS departures, count(*) FILTER (WHERE x.cancelled) AS cancelled
    FROM ontology.flight x
    WHERE x.tail_number = i.tail_number AND x.carrier_id = i.carrier_id
      AND x.sched_dep_utc >= i.t_hour - interval '3 hours' AND x.sched_dep_utc < i.t_hour
) o
WHERE t.sched_dep_utc <= i.actual_arr_utc + interval '24 hours';

CREATE TABLE ontology.cancel_rate (
    carrier_id    bigint REFERENCES ontology.carrier,  -- NULL: all carriers together
    rank          integer NOT NULL,
    delay_bucket  text NOT NULL,
    stress_bucket text NOT NULL,
    samples       integer NOT NULL,
    cancelled     integer NOT NULL,
    rate          numeric NOT NULL,
    UNIQUE NULLS NOT DISTINCT (carrier_id, rank, delay_bucket, stress_bucket)
);

CREATE TABLE ontology.cancel_backtest (
    inbound_flight_id bigint NOT NULL REFERENCES ontology.flight,
    target_flight_id  bigint NOT NULL REFERENCES ontology.flight,
    rank              integer NOT NULL,
    period            text NOT NULL,
    carrier_id        bigint NOT NULL REFERENCES ontology.carrier,
    arr_delay_min     integer NOT NULL,
    delay_bucket      text NOT NULL,
    stress            numeric NOT NULL,
    stress_bucket     text NOT NULL,
    predicted_rate    numeric,  -- NULL when July has no cell, carrier or all-carrier
    basis             text,     -- 'carrier' or 'all carriers'
    basis_samples     integer,
    carrier_rate      numeric,  -- baseline: the carrier's July rate over all its cells
    delay_rate        numeric,  -- baseline: all carriers, delay bucket x rank
    actual_cancelled  boolean NOT NULL,
    PRIMARY KEY (inbound_flight_id, rank)
);
