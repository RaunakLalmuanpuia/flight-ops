from datetime import datetime, timezone


class BlockingCheckFailed(Exception):
    pass


# name, SQL returning a single number, and the only passing value
BLOCKING = [
    ("flights_reconcile", "SELECT (SELECT count(*) FROM staging.v_bts) - (SELECT count(*) FROM staging.flight)", 0),
    (
        "atl_flights_reconcile",
        "SELECT (SELECT count(*) FROM staging.v_bts WHERE origin = 'ATL' OR dest = 'ATL') "
        "- (SELECT count(*) FROM staging.flight WHERE origin = 'ATL' OR dest = 'ATL')",
        0,
    ),
    (
        "airports_have_timezones",
        "SELECT count(*) FROM (SELECT origin c FROM staging.v_bts UNION SELECT dest FROM staging.v_bts) x "
        "LEFT JOIN staging.airport a ON a.bts_code = x.c WHERE a.tz IS NULL",
        0,
    ),
    (
        "operated_flights_have_times",
        "SELECT count(*) FROM staging.flight WHERE NOT cancelled AND (actual_dep_utc IS NULL OR actual_arr_utc IS NULL)",
        0,
    ),
    ("arrive_after_departure", "SELECT count(*) FROM staging.flight WHERE actual_arr_utc <= actual_dep_utc", 0),
    (
        "delay_causes_add_up",
        "SELECT count(*) FROM staging.flight WHERE carrier_delay IS NOT NULL AND arr_delay_min IS DISTINCT FROM "
        "carrier_delay + coalesce(weather_delay, 0) + coalesce(nas_delay, 0) + coalesce(security_delay, 0) + coalesce(late_aircraft_delay, 0)",
        0,
    ),
]

# name and SQL returning a single number, recorded without a pass or fail until thresholds are set
REPORTED = [
    ("flights_total", "SELECT count(*) FROM ontology.flight"),
    ("flights_touching_atl", "SELECT count(*) FROM staging.flight WHERE origin = 'ATL' OR dest = 'ATL'"),
    ("cancelled_jul19_23_touching_atl", "SELECT count(*) FROM staging.flight WHERE cancelled AND (origin = 'ATL' OR dest = 'ATL') AND flight_date BETWEEN '2024-07-19' AND '2024-07-23'"),
    ("operated_missing_tail", "SELECT count(*) FROM staging.flight WHERE NOT cancelled AND tail_number IS NULL"),
    ("block_mismatch_flights", "SELECT count(*) FROM staging.flight WHERE block_mismatch"),
    ("sched_arrival_not_after_departure", "SELECT count(*) FROM staging.flight WHERE sched_arr_utc <= sched_dep_utc"),
    ("flights_link_high", "SELECT count(*) FROM ontology.flight WHERE aircraft_link_confidence = 'high'"),
    ("flights_link_medium", "SELECT count(*) FROM ontology.flight WHERE aircraft_link_confidence = 'medium'"),
    ("flights_tail_unresolved", "SELECT coalesce(sum(flights), 0) FROM dq.unresolved_link WHERE entity = 'tail'"),
    ("flights_matched_active", "SELECT count(*) FROM ontology.flight f WHERE aircraft_id IS NOT NULL AND EXISTS (SELECT 1 FROM ontology.aircraft_registration r WHERE r.aircraft_id = f.aircraft_id AND r.tail_number = f.tail_number AND r.source = 'master')"),
    ("flights_matched_deregistered_only", "SELECT count(*) FROM ontology.flight f WHERE aircraft_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM ontology.aircraft_registration r WHERE r.aircraft_id = f.aircraft_id AND r.tail_number = f.tail_number AND r.source = 'master')"),
    ("metar_filtered_madis", "SELECT count(*) FROM staging.v_metar WHERE metar LIKE '%MADISHF%'"),
    ("metar_gaps_over_90_min", "SELECT count(*) FROM (SELECT observed_at - lag(observed_at) OVER (ORDER BY observed_at) AS gap FROM staging.metar) x WHERE gap > interval '90 minutes'"),
]


def run(conn, phase: str) -> list[tuple]:
    now = datetime.now(timezone.utc)
    results = []
    if phase == "blocking":
        for name, query, expected in BLOCKING:
            value = conn.execute(query).fetchone()[0]
            results.append((now, name, True, value == expected, value))
    else:
        for name, query in REPORTED:
            results.append((now, name, False, None, conn.execute(query).fetchone()[0]))
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO dq.check_result (run_at, name, blocking, passed, value) VALUES (%s, %s, %s, %s, %s)", results
        )
    failed = [r[1] for r in results if r[3] is False]
    if failed:
        raise BlockingCheckFailed(", ".join(failed))
    return results
