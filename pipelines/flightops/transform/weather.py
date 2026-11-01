import re
from decimal import Decimal
from fractions import Fraction

WIND = re.compile(r"\b(\d{3}|VRB)(\d{2,3})(?:G(\d{2,3}))?KT\b")
VISIBILITY = re.compile(r"\b[PM]?(?:(\d+) )?(\d+/\d+|\d+)SM\b")
CEILING = re.compile(r"\b(?:BKN|OVC|VV)(\d{3})")
TEMPERATURE = re.compile(r"\b(M?\d{2})/(M?\d{2})?\b")
ALTIMETER = re.compile(r"\bA(\d{4})\b")
WEATHER = re.compile(
    r"^[-+]?(?:VC)?(?:MI|PR|BC|DR|BL|SH|TS|FZ)?"
    r"(?:DZ|RA|SN|SG|IC|PL|GR|GS|UP|BR|FG|FU|VA|DU|SA|HZ|PY|PO|SQ|FC|SS|DS)*$"
)
DESCRIPTOR_ONLY = {"TS", "VCTS", "VCSH"}


def _temperature(value: str | None) -> int | None:
    if value is None:
        return None
    return -int(value[1:]) if value.startswith("M") else int(value)


def parse_metar(text: str) -> dict:
    body = text.split(" RMK")[0]
    wind = WIND.search(body)
    visibility = VISIBILITY.search(body)
    ceilings = [int(c) * 100 for c in CEILING.findall(body)]
    temperature = TEMPERATURE.search(body)
    altimeter = ALTIMETER.search(body)

    visibility_sm = None
    if visibility:
        whole = int(visibility.group(1) or 0)
        part = Fraction(visibility.group(2))
        visibility_sm = Decimal(float(whole + part)).quantize(Decimal("0.01")).normalize()

    # weather groups sit between visibility and the first sky or temperature group
    weather = []
    if visibility:
        for token in body[visibility.end():].split():
            if token in DESCRIPTOR_ONLY or (WEATHER.match(token) and token.lstrip("+-") and len(token.lstrip("+-")) >= 2):
                weather.append(token)
            else:
                break

    return {
        "wind_dir_deg": None if not wind or wind.group(1) == "VRB" else int(wind.group(1)),
        "wind_kt": int(wind.group(2)) if wind else None,
        "gust_kt": int(wind.group(3)) if wind and wind.group(3) else None,
        "visibility_sm": visibility_sm,
        "ceiling_ft": min(ceilings) if ceilings else None,
        "temp_c": _temperature(temperature.group(1)) if temperature else None,
        "dewpoint_c": _temperature(temperature.group(2)) if temperature else None,
        "altimeter_inhg": Decimal(altimeter.group(1)) / 100 if altimeter else None,
        "weather": weather,
    }


def build_weather(conn) -> None:
    # MADISHF rows are 5-minute automated records, not standard METARs
    rows = conn.execute(
        "SELECT split_part(metar, ' ', 1), valid || '+00', metar FROM staging.v_metar "
        "WHERE metar NOT LIKE '%MADISHF%' ORDER BY 1, 2"
    ).fetchall()
    with conn.transaction():
        conn.execute("TRUNCATE staging.metar")
        conn.execute("TRUNCATE staging.taf")
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO staging.metar (station_icao, observed_at, raw_text, wind_dir_deg, wind_kt, gust_kt, "
                "visibility_sm, ceiling_ft, temp_c, dewpoint_c, altimeter_inhg, weather) "
                "VALUES (%(station)s, %(observed_at)s, %(raw)s, %(wind_dir_deg)s, %(wind_kt)s, %(gust_kt)s, "
                "%(visibility_sm)s, %(ceiling_ft)s, %(temp_c)s, %(dewpoint_c)s, %(altimeter_inhg)s, %(weather)s)",
                [{"station": s, "observed_at": v, "raw": m, **parse_metar(m)} for s, v, m in rows],
            )
        conn.execute(
            """
            INSERT INTO staging.taf
            SELECT station, product_id, (valid || '+00')::timestamptz, (fx_valid || '+00')::timestamptz,
                   (nullif(fx_valid_end, '') || '+00')::timestamptz, ftype, is_tempo = 'True', raw
            FROM staging.v_taf
            ORDER BY product_id, fx_valid
            """
        )
