from datetime import datetime, timezone
from decimal import Decimal

from flightops.transform import weather


def test_parse_wind_gust_and_temperature_below_zero():
    p = weather.parse_metar("KATL 042345Z 35017G25KT 1 1/2SM +TSRA BR OVC040CB M02/M05 A2998 RMK AO2")
    assert (p["wind_dir_deg"], p["wind_kt"], p["gust_kt"]) == (350, 17, 25)
    assert p["visibility_sm"] == Decimal("1.5")
    assert p["weather"] == ["+TSRA", "BR"]
    assert p["ceiling_ft"] == 4000
    assert (p["temp_c"], p["dewpoint_c"]) == (-2, -5)
    assert p["altimeter_inhg"] == Decimal("29.98")


def test_parse_variable_wind_and_greater_than_visibility():
    p = weather.parse_metar("KATL 010000Z VRB03KT P6SM FEW040 27/19 A3001")
    assert (p["wind_dir_deg"], p["wind_kt"], p["gust_kt"]) == (None, 3, None)
    assert p["visibility_sm"] == Decimal("6")
    assert p["ceiling_ft"] is None


def test_lowest_broken_or_overcast_layer_is_the_ceiling_and_few_is_not():
    assert weather.parse_metar("KATL 010000Z 00000KT 10SM FEW010 BKN050 OVC090 27/19 A3001")["ceiling_ft"] == 5000


def test_remarks_are_not_parsed_as_weather():
    p = weather.parse_metar("KATL 010000Z 00000KT 10SM CLR 27/19 A3001 RMK AO2 TS VC SW RAB39")
    assert p["weather"] == []


def test_build_filters_madis_records_and_stores_utc(conn, load_fixture):
    load_fixture("iem_metar", "metar.csv")
    load_fixture("iem_taf", "taf.csv")
    weather.build_weather(conn)
    rows = conn.execute("select station_icao, observed_at from staging.metar order by 2").fetchall()
    assert rows == [
        ("KATL", datetime(2024, 7, 4, 23, 6, tzinfo=timezone.utc)),
        ("KATL", datetime(2024, 7, 4, 23, 45, tzinfo=timezone.utc)),
    ]
    assert conn.execute("select count(*) from staging.taf where product_id = 'P1'").fetchone()[0] == 2


def test_build_twice_changes_nothing(conn, load_fixture):
    load_fixture("iem_metar", "metar.csv")
    load_fixture("iem_taf", "taf.csv")
    weather.build_weather(conn)
    weather.build_weather(conn)
    assert conn.execute("select count(*) from staging.metar").fetchone()[0] == 2


def test_less_than_visibility_is_not_read_as_the_denominator():
    assert weather.parse_metar("KATL 010000Z 00000KT M1/4SM FG VV002 20/20 A3001")["visibility_sm"] == Decimal("0.25")
