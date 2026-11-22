import pytest

# Column order of ontology.weather_observation: airport_id, observed_at, raw_text, wind_dir_deg, wind_kt,
# gust_kt, visibility_sm, ceiling_ft, temp_c, dewpoint_c, altimeter_inhg, weather
ADVERSE = (
    "SELECT ontology.is_adverse(ROW(1, now(), '', NULL, NULL, %s::int, %s::numeric, %s::int, "
    "NULL, NULL, NULL, %s::text[])::ontology.weather_observation)"
)


@pytest.mark.parametrize(
    "weather, ceiling, visibility, gust, expected",
    [
        ([], 5000, 10, None, False),
        (["TSRA"], None, 10, None, True),
        (["VCTS"], None, 10, None, True),
        (["+RA"], None, 10, None, True),
        (["-RA"], None, 10, None, False),
        (["FG"], None, 10, None, True),
        (["-SN"], None, 10, None, True),
        (["FZDZ"], None, 10, None, True),
        (["BR"], 900, 10, None, True),
        ([], 1000, 10, None, False),
        ([], None, 2.5, None, True),
        ([], None, 3, None, False),
        ([], None, 10, 30, True),
        ([], None, 10, 29, False),
        ([], None, None, None, False),
    ],
)
def test_adverse_rule(conn, weather, ceiling, visibility, gust, expected):
    assert conn.execute(ADVERSE, (gust, visibility, ceiling, weather)).fetchone()[0] is expected
