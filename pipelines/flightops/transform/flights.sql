TRUNCATE staging.flight;

INSERT INTO staging.flight
SELECT
    b.flightdate::date,
    b.reporting_airline,
    nullif(b.iata_code_reporting_airline, ''),
    nullif(b.dot_id_reporting_airline, ''),
    b.flight_number_reporting_airline,
    b.origin,
    b.dest,
    nullif(b.originairportid, ''),
    nullif(b.destairportid, ''),
    b.crsdeptime,
    CASE WHEN b.tail_number ~ '^[0-9]' THEN 'N' || b.tail_number ELSE nullif(b.tail_number, '') END,
    nullif(b.tail_number, ''),
    s.sched_dep,
    staging.local_near(b.crsarrtime, d.tz, s.sched_dep + s.crs_block * interval '1 minute'),
    a.actual_dep,
    l.actual_arr,
    CASE WHEN f.is_cancelled THEN NULL WHEN f.stopped_short THEN f.last_div_airport ELSE b.dest END,
    f.is_cancelled,
    nullif(b.cancellationcode, ''),
    f.is_diverted,
    CASE WHEN f.is_diverted THEN NOT f.stopped_short END,
    s.dep_delay,
    nullif(b.arrdelay, '')::numeric::int,
    nullif(b.carrierdelay, '')::numeric::int,
    nullif(b.weatherdelay, '')::numeric::int,
    nullif(b.nasdelay, '')::numeric::int,
    nullif(b.securitydelay, '')::numeric::int,
    nullif(b.lateaircraftdelay, '')::numeric::int,
    abs(extract(epoch FROM staging.local_near(b.crsarrtime, d.tz, s.sched_dep + s.crs_block * interval '1 minute') - s.sched_dep) / 60 - s.crs_block) > 1
FROM staging.v_bts b
JOIN staging.airport o ON o.bts_code = b.origin
JOIN staging.airport d ON d.bts_code = b.dest
CROSS JOIN LATERAL (
    SELECT
        nullif(b.cancelled, '')::numeric = 1 AS is_cancelled,
        coalesce(nullif(b.diverted, '')::numeric = 1, false) AS is_diverted,
        coalesce(nullif(b.diverted, '')::numeric = 1, false) AND coalesce(nullif(b.divreacheddest, '')::numeric <> 1, true) AS stopped_short,
        coalesce(nullif(b.div5airport, ''), nullif(b.div4airport, ''), nullif(b.div3airport, ''), nullif(b.div2airport, ''), nullif(b.div1airport, '')) AS last_div_airport,
        coalesce(nullif(b.div5wheelson, ''), nullif(b.div4wheelson, ''), nullif(b.div3wheelson, ''), nullif(b.div2wheelson, ''), nullif(b.div1wheelson, '')) AS last_div_wheelson
) f
LEFT JOIN staging.airport x ON x.bts_code = f.last_div_airport
CROSS JOIN LATERAL (
    SELECT
        staging.local_at(b.flightdate::date, b.crsdeptime, o.tz) AS sched_dep,
        nullif(b.crselapsedtime, '')::numeric AS crs_block,
        nullif(b.depdelay, '')::numeric::int AS dep_delay
) s
CROSS JOIN LATERAL (
    SELECT staging.local_near(nullif(b.deptime, ''), o.tz, s.sched_dep + coalesce(s.dep_delay, 0) * interval '1 minute') AS actual_dep
) a
CROSS JOIN LATERAL (
    SELECT CASE
        WHEN f.stopped_short THEN staging.local_near(f.last_div_wheelson, x.tz, a.actual_dep + interval '12 hours')
        ELSE staging.local_near(
            nullif(b.arrtime, ''), d.tz,
            a.actual_dep + coalesce(nullif(b.actualelapsedtime, ''), nullif(b.divactualelapsedtime, ''), '720')::numeric * interval '1 minute'
        )
    END AS actual_arr
) l
ORDER BY 1, 2, 5, 6, 10;
