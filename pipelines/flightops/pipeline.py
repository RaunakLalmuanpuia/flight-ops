from pathlib import Path

from flightops.dq import checks
from flightops.transform import airports, weather

PACKAGE = Path(__file__).resolve().parent


def run_sql(conn, relative_path: str) -> None:
    with conn.transaction():
        conn.execute((PACKAGE / relative_path).read_text())


def build_staging(conn) -> None:
    airports.build_airports(conn)
    run_sql(conn, "transform/flights.sql")
    weather.build_weather(conn)
    run_sql(conn, "resolve/aircraft.sql")


def build(conn) -> None:
    build_staging(conn)
    checks.run(conn, "blocking")  # a failure here leaves the previous ontology untouched
    run_sql(conn, "resolve/ontology.sql")
    run_sql(conn, "rotations/rotations.sql")
    run_sql(conn, "rotations/min_turn.sql")
    run_sql(conn, "rotations/backtest.sql")
    run_sql(conn, "rotations/cancel_rate.sql")
    run_sql(conn, "rotations/cancel_backtest.sql")
    run_sql(conn, "resolve/flight_weather.sql")
    checks.run(conn, "reported")
