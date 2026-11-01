import argparse

from flightops import db, pipeline, report
from flightops.sources import fetch, raw, registry


def main() -> None:
    parser = argparse.ArgumentParser(prog="flightops")
    parser.add_argument("command", choices=["migrate", "ddl", "fetch", "load", "build", "report", "all"])
    command = parser.parse_args().command

    if command == "ddl":  # prints raw table DDL from real headers, for writing a migration
        for f in registry.RAW_FILES:
            print(raw.create_table_sql(f.table, f.path()))
    elif command == "fetch":
        for d in registry.DOWNLOADS:
            print(("fetched " if fetch.download(d.url, d.dest) else "present ") + d.dest.name)
            if d.unzip:
                fetch.extract_csv(d.dest)
    else:
        with db.connect() as conn:
            if command in ("migrate", "all"):
                print("applied:", db.migrate(conn))
            if command in ("load", "all"):
                for f in registry.RAW_FILES:
                    result = raw.load_file(conn, f.source, f.table, f.path())
                    print(
                        f"{f.table}: {result.rows} rows, {result.quarantined} quarantined"
                        f"{' (already loaded)' if result.skipped else ''}"
                    )
            if command in ("build", "all"):
                last_id = conn.execute("SELECT coalesce(max(id), 0) FROM dq.check_result").fetchone()[0]
                pipeline.build(conn)
                for name, value, passed in conn.execute(
                    "SELECT name, value, passed FROM dq.check_result WHERE id > %s ORDER BY id", (last_id,)
                ):
                    print(f"{name}: {value}{'' if passed is None else ' ok' if passed else ' FAILED'}")
            if command in ("report", "all"):
                path = db.REPO / "docs" / "phase-1-report.md"
                path.write_text(report.render(conn))
                print("wrote", path)


if __name__ == "__main__":
    main()
