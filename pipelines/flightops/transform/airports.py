from timezonefinder import TimezoneFinder

CODES_AND_AIRPORTS = """
WITH codes AS (
    SELECT origin AS code FROM staging.v_bts
    UNION SELECT dest FROM staging.v_bts
    UNION SELECT div1airport FROM staging.v_bts
    UNION SELECT div2airport FROM staging.v_bts
    UNION SELECT div3airport FROM staging.v_bts
    UNION SELECT div4airport FROM staging.v_bts
    UNION SELECT div5airport FROM staging.v_bts
)
SELECT o.ident, c.code, nullif(o.iata_code, ''), nullif(o.icao_code, ''), o.name,
       o.latitude_deg::float, o.longitude_deg::float, o.iso_country
FROM codes c
LEFT JOIN staging.airport_code_alias a ON a.bts_code = c.code
JOIN staging.v_airports o ON o.ident = a.ident OR (a.ident IS NULL AND o.iata_code = c.code)
WHERE nullif(c.code, '') IS NOT NULL
ORDER BY c.code
"""


def build_airports(conn) -> None:
    finder = TimezoneFinder()
    rows = conn.execute(CODES_AND_AIRPORTS).fetchall()
    with conn.transaction():
        conn.execute("TRUNCATE staging.airport")
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO staging.airport (ident, bts_code, iata_current, icao_code, name, latitude, longitude, country, tz) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                [(*r, finder.timezone_at(lat=r[5], lng=r[6])) for r in rows],
            )
