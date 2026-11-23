-- Phase 5: operator decisions. The app writes only through app_read.record_decision,
-- so flightops_app has no rights on schema app and the log stays append-only.
CREATE SCHEMA app;

CREATE TABLE app.decision (
    decision_id      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    -- Ids as they were when recorded. No foreign key: build truncates ontology.flight and restarts its ids,
    -- so the review re-matches through the natural key frozen in app.decision_leg.
    flight_id        bigint NOT NULL,
    arr_delay_min    integer,
    what_if          boolean NOT NULL,
    percentile       integer NOT NULL,
    action           text NOT NULL CHECK (action IN ('accept_delay', 'hold_departure', 'swap_aircraft', 'cancel_leg', 'other')),
    target_flight_id bigint,
    reason           text NOT NULL,
    author           text NOT NULL,
    recorded_at      timestamptz NOT NULL DEFAULT now()
);

-- propagate's output as the controller saw it. Actuals are not frozen: the review reads them from ontology.
CREATE TABLE app.decision_leg (
    decision_id         bigint NOT NULL REFERENCES app.decision,
    depth               integer NOT NULL,
    kind                text NOT NULL,
    flight_id           bigint NOT NULL,
    carrier             text NOT NULL,
    flight_number       text NOT NULL,
    origin              text NOT NULL,
    dest                text NOT NULL,
    sched_dep_utc       timestamptz NOT NULL,
    sched_arr_utc       timestamptz,
    min_turn            integer,
    slack_min           integer,
    predicted_dep_delay integer,
    predicted_arr_utc   timestamptz,
    at_risk             boolean,
    stop_reason         text,
    PRIMARY KEY (decision_id, flight_id)
);

-- p_arr_delay_min NULL means the actual arrival, as in propagate. p_percentile defaults to propagate's default.
CREATE FUNCTION app_read.record_decision(
    p_flight_id bigint, p_arr_delay_min integer, p_action text, p_target_flight_id bigint,
    p_reason text, p_author text, p_percentile integer DEFAULT 10)
RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    v_id bigint;
BEGIN
    IF coalesce(trim(p_reason), '') = '' THEN RAISE EXCEPTION 'A reason is required.'; END IF;
    IF coalesce(trim(p_author), '') = '' THEN RAISE EXCEPTION 'An author is required.'; END IF;
    IF p_action = 'accept_delay' AND p_target_flight_id IS NOT NULL THEN
        RAISE EXCEPTION 'Accepting the delay takes no target leg.';
    END IF;
    -- propagate's override measures from the scheduled destination, the wrong airport after a diversion.
    IF p_arr_delay_min IS NOT NULL AND EXISTS (SELECT FROM ontology.flight WHERE flight_id = p_flight_id AND diverted) THEN
        RAISE EXCEPTION 'A diverted flight has no arrival delay to replace.';
    END IF;

    INSERT INTO app.decision (flight_id, arr_delay_min, what_if, percentile, action, target_flight_id, reason, author)
    VALUES (p_flight_id,
            coalesce(p_arr_delay_min, (SELECT arr_delay_min FROM ontology.flight WHERE flight_id = p_flight_id)),
            p_arr_delay_min IS NOT NULL, p_percentile, p_action, p_target_flight_id, trim(p_reason), trim(p_author))
    RETURNING decision_id INTO v_id;

    -- One propagate call: the target is checked against the frozen copy, so the check and the snapshot can't differ.
    INSERT INTO app.decision_leg (
        decision_id, depth, kind, flight_id, carrier, flight_number, origin, dest, sched_dep_utc, sched_arr_utc,
        min_turn, slack_min, predicted_dep_delay, predicted_arr_utc, at_risk, stop_reason)
    SELECT v_id, p.depth, p.kind, p.flight_id, p.carrier, p.flight_number, p.origin, p.dest, p.sched_dep_utc, p.sched_arr_utc,
           p.min_turn, p.slack_min, p.predicted_dep_delay, p.predicted_arr_utc, p.at_risk, p.stop_reason
    FROM app_read.propagate(p_flight_id, p_arr_delay_min, p_percentile) p;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Flight % has no arrival to propagate from.', p_flight_id;
    END IF;

    IF p_target_flight_id IS NOT NULL AND NOT EXISTS (
        SELECT FROM app.decision_leg WHERE decision_id = v_id AND flight_id = p_target_flight_id AND kind <> 'selected') THEN
        RAISE EXCEPTION 'The target is not a later leg in this chain.';
    END IF;
    RETURN v_id;
END
$$;
REVOKE EXECUTE ON FUNCTION app_read.record_decision(bigint, integer, text, bigint, text, text, integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app_read.record_decision(bigint, integer, text, bigint, text, text, integer) TO flightops_app;

-- Each frozen leg beside what BTS shows for it now, matched on the natural key because flight ids restart on rebuild.
CREATE VIEW app_read.decision_legs AS
SELECT l.*,
       coalesce(l.flight_id = d.target_flight_id, false) AS is_target,
       f.flight_id      AS current_flight_id,
       f.cancelled      AS actual_cancelled,
       f.dep_delay_min  AS actual_dep_delay,
       f.arr_delay_min  AS actual_arr_delay
FROM app.decision_leg l
JOIN app.decision d ON d.decision_id = l.decision_id
LEFT JOIN (ontology.flight f
           JOIN ontology.carrier c ON c.carrier_id = f.carrier_id
           JOIN ontology.airport o ON o.airport_id = f.origin_airport_id)
       ON c.code = l.carrier AND f.flight_number = l.flight_number
      AND o.iata_code = l.origin AND f.sched_dep_utc = l.sched_dep_utc;

CREATE VIEW app_read.decision_review AS
SELECT d.decision_id, d.recorded_at, d.author, d.action, d.reason, d.arr_delay_min, d.what_if, d.percentile,
       s.carrier, s.flight_number, s.origin, s.dest, s.sched_dep_utc,
       s.current_flight_id, s.current_flight_id IS NOT NULL AS flight_found,
       t.carrier AS target_carrier, t.flight_number AS target_flight_number, t.origin AS target_origin,
       t.dest AS target_dest, t.sched_dep_utc AS target_sched_dep_utc, t.kind AS target_kind,
       t.predicted_dep_delay AS target_predicted_dep_delay, t.actual_cancelled AS target_cancelled,
       t.actual_dep_delay AS target_actual_dep_delay,
       n.predicted_at_risk, n.actually_late, n.cancelled,
       CASE
           WHEN s.current_flight_id IS NULL OR (t.decision_id IS NOT NULL AND t.current_flight_id IS NULL)
               THEN 'flight not found after rebuild'
           WHEN t.decision_id IS NULL THEN NULL
           WHEN t.actual_cancelled THEN
               CASE d.action WHEN 'cancel_leg' THEN 'airline did the same' ELSE 'airline cancelled it' END
           WHEN d.action = 'cancel_leg' THEN 'airline flew it, ' || m.actual
           -- BTS records only the tail that flew, so a swap can't be confirmed.
           WHEN d.action = 'swap_aircraft' THEN 'this tail flew it, ' || m.actual || ' (swap not visible)'
           ELSE 'flown, ' || m.actual || coalesce(' vs predicted ' || m.predicted, ', no prediction')
       END AS match_label
FROM app.decision d
JOIN app_read.decision_legs s ON s.decision_id = d.decision_id AND s.depth = 0
LEFT JOIN app_read.decision_legs t ON t.decision_id = d.decision_id AND t.is_target
CROSS JOIN LATERAL (SELECT
    CASE WHEN t.actual_dep_delay >= 0 THEN '+' ELSE '' END || t.actual_dep_delay || ' min' AS actual,
    CASE WHEN t.predicted_dep_delay >= 0 THEN '+' ELSE '' END || t.predicted_dep_delay AS predicted) m
CROSS JOIN LATERAL (SELECT
    count(*) FILTER (WHERE x.at_risk) AS predicted_at_risk,
    count(*) FILTER (WHERE x.kind = 'flown' AND x.actual_dep_delay >= 15) AS actually_late,
    count(*) FILTER (WHERE x.depth > 0 AND x.actual_cancelled) AS cancelled
    FROM app_read.decision_legs x WHERE x.decision_id = d.decision_id) n;
