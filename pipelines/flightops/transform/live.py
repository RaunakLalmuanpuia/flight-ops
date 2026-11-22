from flightops.sources.live import ATL
from flightops.transform.weather import parse_metar

# Raw is read directly: every live file is its own delivery, and the loader skips a repeated hash.
POSITIONS = """
INSERT INTO ontology.live_position
WITH s AS (
    SELECT to_timestamp("time"::bigint) AS snapshot_at, upper(icao24) AS hex, nullif(trim(callsign), '') AS callsign,
           nullif(latitude, '')::float8 AS lat, nullif(longitude, '')::float8 AS lon,
           to_timestamp(nullif(time_position, '')::bigint) AS position_at, on_ground = 'True' AS on_ground,
           round(nullif(baro_altitude, '')::numeric * 3.28084)::int AS altitude_ft,
           round(nullif(vertical_rate, '')::numeric * 196.850)::int AS vertical_rate_fpm
    FROM raw.opensky_state
    WHERE source_file = (SELECT source_file FROM dq.ingestion_run WHERE table_name = 'opensky_state' ORDER BY id DESC LIMIT 1)
), f AS (
    SELECT hex, min(tail_number) AS tail_number, min(manufacturer) AS manufacturer, min(model) AS model, count(*) AS n
    FROM staging.v_faa_current WHERE hex IN (SELECT hex FROM s) GROUP BY hex
)
SELECT s.snapshot_at, s.hex, s.callsign,
       CASE WHEN f.n = 1 THEN f.tail_number END,
       CASE WHEN f.n = 1 THEN f.manufacturer END,
       CASE WHEN f.n = 1 THEN f.model END,
       CASE WHEN f.n = 1 THEN 'faa_current_hex' END,
       CASE WHEN f.n = 1 THEN 'high' END,
       CASE WHEN f.n IS NULL THEN 'hex not in FAA registry' WHEN f.n > 1 THEN 'ambiguous hex' END,
       p.operator, p.bts_carrier,
       CASE WHEN p.prefix IS NOT NULL THEN NULL
            WHEN s.callsign IS NULL THEN 'no callsign'
            WHEN s.callsign ~ '^N[0-9][0-9A-Z]{0,4}$' THEN 'general aviation callsign'
            ELSE 'unknown prefix' END,
       s.lat, s.lon, s.position_at, s.on_ground, s.altitude_ft, s.vertical_rate_fpm,
       round((3440.065 * 2 * asin(sqrt(
           power(sin(radians(s.lat - %(lat)s) / 2), 2)
           + cos(radians(%(lat)s)) * cos(radians(s.lat)) * power(sin(radians(s.lon - %(lon)s) / 2), 2)
       )))::numeric, 1),
       mod(round(degrees(atan2(
           sin(radians(s.lon - %(lon)s)) * cos(radians(s.lat)),
           cos(radians(%(lat)s)) * sin(radians(s.lat))
           - sin(radians(%(lat)s)) * cos(radians(s.lat)) * cos(radians(s.lon - %(lon)s))
       )))::int + 360, 360)
FROM s
LEFT JOIN f USING (hex)
LEFT JOIN staging.callsign_prefix p ON s.callsign ~ '^[A-Z]{3}[0-9]' AND p.prefix = left(s.callsign, 3)
"""


def build_live(conn) -> tuple[int, int, int]:
    lat, lon = ATL
    metars = conn.execute(
        "SELECT DISTINCT ON (icaoid, obstime) icaoid, to_timestamp(obstime::bigint), metartype, rawob "
        "FROM raw.awc_metar ORDER BY icaoid, obstime"
    ).fetchall()
    with conn.transaction():
        conn.execute("TRUNCATE ontology.live_position, ontology.live_weather, ontology.live_taf")
        conn.execute(POSITIONS, {"lat": lat, "lon": lon})
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO ontology.live_weather (station_icao, observed_at, metar_type, raw_text, wind_dir_deg, "
                "wind_kt, gust_kt, visibility_sm, ceiling_ft, temp_c, dewpoint_c, altimeter_inhg, weather) "
                "VALUES (%(station)s, %(observed_at)s, %(type)s, %(raw)s, %(wind_dir_deg)s, %(wind_kt)s, %(gust_kt)s, "
                "%(visibility_sm)s, %(ceiling_ft)s, %(temp_c)s, %(dewpoint_c)s, %(altimeter_inhg)s, %(weather)s)",
                [{"station": s, "observed_at": t, "type": k, "raw": m, **parse_metar(m)} for s, t, k, m in metars],
            )
        conn.execute(
            "INSERT INTO ontology.live_taf SELECT to_timestamp(fetched_at::bigint), raw_text "
            "FROM raw.awc_taf ORDER BY fetched_at::bigint DESC LIMIT 1"
        )
    return conn.execute(
        "SELECT count(*), count(tail_number), count(operator) FROM ontology.live_position"
    ).fetchone()
