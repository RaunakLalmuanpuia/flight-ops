-- Weather that could delay flights, as this project defines it (see DECISIONS.md). Shared by the report and app_read.
CREATE FUNCTION ontology.is_adverse(w ontology.weather_observation) RETURNS boolean
LANGUAGE sql IMMUTABLE AS $$
    SELECT coalesce(
        array_to_string(w.weather, ' ') ~ '(TS|\+RA|FG|SN|FZ)'
        OR coalesce(w.ceiling_ft, 99999) < 1000
        OR w.visibility_sm < 3
        OR coalesce(w.gust_kt, 0) >= 30,
        false)
$$;
