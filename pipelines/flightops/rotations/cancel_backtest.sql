TRUNCATE ontology.cancel_backtest;

WITH p AS (
    SELECT *, ontology.delay_bucket(arr_delay_min) AS delay_bucket, ontology.stress_bucket(stress) AS stress_bucket
    FROM ontology.cancel_pair
),
-- Both baselines are sums over the fitted cells, so they come from July too.
carrier_base AS (
    SELECT carrier_id, sum(cancelled)::numeric / sum(samples) AS rate
    FROM ontology.cancel_rate WHERE carrier_id IS NOT NULL GROUP BY 1
),
delay_base AS (
    SELECT rank, delay_bucket, sum(cancelled)::numeric / sum(samples) AS rate
    FROM ontology.cancel_rate WHERE carrier_id IS NULL GROUP BY 1, 2
)
INSERT INTO ontology.cancel_backtest
SELECT p.inbound_flight_id, p.target_flight_id, p.rank, p.period, p.carrier_id, p.arr_delay_min, p.delay_bucket,
       p.stress, p.stress_bucket,
       CASE WHEN c.samples >= 200 THEN c.rate ELSE a.rate END,
       CASE WHEN c.samples >= 200 THEN 'carrier' WHEN a.samples IS NOT NULL THEN 'all carriers' END,
       CASE WHEN c.samples >= 200 THEN c.samples ELSE a.samples END,
       cb.rate, db.rate, p.cancelled
FROM p
LEFT JOIN ontology.cancel_rate c ON c.carrier_id = p.carrier_id AND c.rank = p.rank
     AND c.delay_bucket = p.delay_bucket AND c.stress_bucket = p.stress_bucket
LEFT JOIN ontology.cancel_rate a ON a.carrier_id IS NULL AND a.rank = p.rank
     AND a.delay_bucket = p.delay_bucket AND a.stress_bucket = p.stress_bucket
LEFT JOIN carrier_base cb ON cb.carrier_id = p.carrier_id
LEFT JOIN delay_base db ON db.rank = p.rank AND db.delay_bucket = p.delay_bucket;
