TRUNCATE ontology.carrier_hour, ontology.cancel_rate;

INSERT INTO ontology.carrier_hour (carrier_id, hour, departures, cancelled)
SELECT carrier_id, date_trunc('hour', sched_dep_utc, 'UTC'), count(*), count(*) FILTER (WHERE cancelled)
FROM ontology.flight
GROUP BY 1, 2;

ANALYZE ontology.carrier_hour;

WITH p AS (
    SELECT carrier_id, rank, ontology.delay_bucket(arr_delay_min) AS delay_bucket,
           ontology.stress_bucket(stress) AS stress_bucket, cancelled
    FROM ontology.cancel_pair
    WHERE period LIKE 'july_%'  -- fit on July only, so August scores out of sample
)
INSERT INTO ontology.cancel_rate (carrier_id, rank, delay_bucket, stress_bucket, samples, cancelled, rate)
SELECT carrier_id, rank, delay_bucket, stress_bucket, count(*), count(*) FILTER (WHERE cancelled), avg(cancelled::int)
FROM p
GROUP BY GROUPING SETS ((carrier_id, rank, delay_bucket, stress_bucket), (rank, delay_bucket, stress_bucket));
