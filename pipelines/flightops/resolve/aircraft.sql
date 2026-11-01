TRUNCATE staging.faa_record, staging.aircraft_link;

-- Only tails seen in BTS, because the registry holds 700,000 rows we would never read.
INSERT INTO staging.faa_record
SELECT 'N' || trim(n_number), trim(mfr_mdl_code) || '|' || trim(serial_number), trim(serial_number), trim(mfr_mdl_code),
       upper(nullif(trim(mode_s_code_hex), '')), to_date(nullif(trim(cert_issue_date), ''), 'YYYYMMDD'), NULL::date, 'master'
FROM staging.v_faa_master
WHERE 'N' || trim(n_number) IN (SELECT tail_number FROM staging.flight)
UNION ALL
SELECT 'N' || trim(n_number), trim(mfr_mdl_code) || '|' || trim(serial_number), trim(serial_number), trim(mfr_mdl_code),
       upper(nullif(trim(mode_s_code_hex), '')), to_date(nullif(trim(cert_issue_date), ''), 'YYYYMMDD'),
       to_date(nullif(trim(cancel_date), ''), 'YYYYMMDD'), 'dereg'
FROM staging.v_faa_dereg
WHERE 'N' || trim(n_number) IN (SELECT tail_number FROM staging.flight);

INSERT INTO staging.aircraft_link
SELECT t.tail_number, t.flight_date,
    CASE
        WHEN cardinality(dated) = 1 THEN dated[1]
        WHEN cardinality(dated) > 1 THEN NULL
        WHEN cardinality(open) = 1 THEN open[1]
        WHEN cardinality(open) > 1 THEN NULL
        WHEN cardinality(every) = 1 THEN every[1]
    END,
    CASE
        WHEN cardinality(dated) = 1 THEN 'window_exact'
        WHEN cardinality(dated) > 1 THEN NULL
        WHEN cardinality(open) = 1 THEN 'window_open_start'
        WHEN cardinality(open) > 1 THEN NULL
        WHEN cardinality(every) = 1 THEN 'single_airframe_outside_window'
    END,
    CASE
        WHEN cardinality(dated) = 1 THEN 'high'
        WHEN cardinality(dated) > 1 THEN NULL
        WHEN cardinality(open) = 1 OR cardinality(every) = 1 THEN 'medium'
    END,
    CASE
        WHEN cardinality(dated) = 1 THEN NULL
        WHEN cardinality(dated) > 1 THEN 'ambiguous_window'
        WHEN cardinality(open) = 1 THEN NULL
        WHEN cardinality(open) > 1 THEN 'ambiguous_window'
        WHEN cardinality(every) = 1 THEN NULL
        WHEN cardinality(every) = 0 THEN 'no_faa_record'
        ELSE 'no_window_multiple_airframes'
    END
FROM (SELECT DISTINCT tail_number, flight_date FROM staging.flight WHERE tail_number IS NOT NULL) t
CROSS JOIN LATERAL (
    SELECT
        ARRAY(SELECT DISTINCT frame FROM staging.faa_record r WHERE r.tail_number = t.tail_number
              AND r.valid_from <= t.flight_date AND coalesce(r.valid_to, 'infinity') >= t.flight_date) AS dated,
        ARRAY(SELECT DISTINCT frame FROM staging.faa_record r WHERE r.tail_number = t.tail_number
              AND coalesce(r.valid_from, '-infinity') <= t.flight_date AND coalesce(r.valid_to, 'infinity') >= t.flight_date) AS open,
        ARRAY(SELECT DISTINCT frame FROM staging.faa_record r WHERE r.tail_number = t.tail_number) AS every
) c;
