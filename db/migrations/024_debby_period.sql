-- Hurricane Debby at ATL: Aug 2-6 had 25, 74, 141, 129 and 45 ATL cancellations, mostly code B, against an August
-- median of 5 a day (docs/phase-6-plan.md notes). Still a holdout: it is not 'july_%'.
CREATE OR REPLACE FUNCTION ontology.period(p_flight_date date) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE
        WHEN p_flight_date BETWEEN '2024-07-19' AND '2024-07-23' THEN 'july_outage'
        WHEN p_flight_date BETWEEN '2024-07-01' AND '2024-07-31' THEN 'july_normal'
        WHEN p_flight_date BETWEEN '2024-08-02' AND '2024-08-06' THEN 'debby'
        WHEN p_flight_date BETWEEN '2024-08-01' AND '2024-08-31' THEN 'august'
    END
$$;
