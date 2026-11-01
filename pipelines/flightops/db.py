import os
from pathlib import Path

import psycopg

REPO = Path(__file__).resolve().parents[2]


def connect(url: str | None = None) -> psycopg.Connection:
    # autocommit so conn.transaction() is a real transaction, never a savepoint
    return psycopg.connect(url or os.environ["DATABASE_URL"], autocommit=True)


def migrate(conn: psycopg.Connection) -> list[str]:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS public.schema_migration ("
        "filename text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
    )
    done = {r[0] for r in conn.execute("SELECT filename FROM public.schema_migration")}
    applied = []
    for path in sorted((REPO / "db" / "migrations").glob("*.sql")):
        if path.name in done:
            continue
        with conn.transaction():
            conn.execute(path.read_text())
            conn.execute("INSERT INTO public.schema_migration (filename) VALUES (%s)", (path.name,))
        applied.append(path.name)
    return applied
