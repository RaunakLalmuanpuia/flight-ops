-- Phase 6 (docs/phase-6-plan.md): fit on July, score on August, so every period comes from one place.
-- shortcut: the months are hard-coded, so replace this with a table if a third month is loaded.
CREATE FUNCTION ontology.period(p_flight_date date) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE
        WHEN p_flight_date BETWEEN '2024-07-19' AND '2024-07-23' THEN 'july_outage'
        WHEN p_flight_date BETWEEN '2024-07-01' AND '2024-07-31' THEN 'july_normal'
        WHEN p_flight_date BETWEEN '2024-08-01' AND '2024-08-31' THEN 'august'
    END
$$;

-- p10 was the edge of phase 3's grid, so p5 is added. Refilled by the next build.
TRUNCATE ontology.min_turn;
ALTER TABLE ontology.min_turn ADD COLUMN p5 integer NOT NULL;

CREATE OR REPLACE FUNCTION app_read.min_turn_for(p_carrier_id bigint, p_percentile integer) RETURNS integer
LANGUAGE plpgsql STABLE SET search_path = pg_catalog, pg_temp AS $$
DECLARE v_turn integer;
BEGIN
    IF p_percentile NOT IN (5, 10, 25, 50) THEN
        RAISE EXCEPTION 'percentile must be 5, 10, 25 or 50, got %', p_percentile USING ERRCODE = 'invalid_parameter_value';
    END IF;
    SELECT CASE p_percentile WHEN 5 THEN m.p5 WHEN 10 THEN m.p10 WHEN 25 THEN m.p25 WHEN 50 THEN m.p50 END INTO v_turn
    FROM ontology.min_turn m
    WHERE m.carrier_id = p_carrier_id AND m.samples >= 200
       OR m.carrier_id IS NULL
    ORDER BY m.carrier_id NULLS LAST
    LIMIT 1;
    IF v_turn IS NULL THEN
        RAISE EXCEPTION 'ontology.min_turn has no all-carrier row (carrier_id NULL)' USING ERRCODE = 'no_data_found';
    END IF;
    RETURN v_turn;
END
$$;
