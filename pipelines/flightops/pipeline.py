from pathlib import Path

PACKAGE = Path(__file__).resolve().parent


def run_sql(conn, relative_path: str) -> None:
    with conn.transaction():
        conn.execute((PACKAGE / relative_path).read_text())
