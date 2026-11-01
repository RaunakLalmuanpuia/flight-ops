TRUNCATE ontology.flight_weather;

WITH atl AS (SELECT airport_id FROM ontology.airport WHERE iata_code = 'ATL'),
events AS (
    SELECT flight_id, 'departure' AS event, 'scheduled' AS basis, sched_dep_utc AS event_at FROM ontology.flight WHERE origin_airport_id = (TABLE atl)
    UNION ALL
    SELECT flight_id, 'departure', 'actual', actual_dep_utc FROM ontology.flight WHERE origin_airport_id = (TABLE atl) AND actual_dep_utc IS NOT NULL
    UNION ALL
    SELECT flight_id, 'arrival', 'scheduled', sched_arr_utc FROM ontology.flight WHERE dest_airport_id = (TABLE atl) AND sched_arr_utc IS NOT NULL
    UNION ALL
    -- landed, not dest: a flight bound elsewhere that stopped short at ATL did arrive here
    SELECT flight_id, 'arrival', 'actual', actual_arr_utc FROM ontology.flight WHERE landed_airport_id = (TABLE atl) AND actual_arr_utc IS NOT NULL
),
matched AS (
    SELECT e.*, m.observed_at
    FROM events e
    LEFT JOIN LATERAL (
        SELECT w.observed_at FROM ontology.weather_observation w
        WHERE w.airport_id = (TABLE atl) AND w.observed_at <= e.event_at
        ORDER BY w.observed_at DESC LIMIT 1
    ) m ON true
),
linked AS (
    INSERT INTO ontology.flight_weather
    SELECT flight_id, event, basis, event_at, (TABLE atl), observed_at,
           (extract(epoch FROM event_at - observed_at) / 60)::int
    FROM matched WHERE observed_at IS NOT NULL
    ORDER BY flight_id, event, basis
)
INSERT INTO dq.unresolved_link
SELECT 'atl_weather', flight_id || '|' || event || '|' || basis, 'no_metar_at_or_before', 1
FROM matched WHERE observed_at IS NULL;
