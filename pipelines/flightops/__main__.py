import argparse
from datetime import date, datetime, timezone

from flightops import db, live, pipeline, report
from flightops.sources import fetch, opensky, raw, registry


def main() -> None:
    parser = argparse.ArgumentParser(prog="flightops")
    parser.add_argument("command", choices=["migrate", "ddl", "fetch", "load", "build", "report", "all", "collect", "live"])
    parser.add_argument("--from", dest="first", type=date.fromisoformat)
    parser.add_argument("--to", dest="last", type=date.fromisoformat)
    parser.add_argument("--every", type=int, default=60, help="seconds between live polls")
    args = parser.parse_args()
    command = args.command

    if command == "ddl":  # prints raw table DDL from real headers, for writing a migration
        for f in registry.RAW_FILES:
            print(raw.create_table_sql(f.table, f.path()))
    elif command == "fetch":
        for d in registry.DOWNLOADS:
            print(("fetched " if fetch.download(d.url, d.dest) else "present ") + d.dest.name)
            if d.unzip:
                fetch.extract_csv(d.dest)
    elif command == "collect":
        first, last = opensky.settled_days(datetime.now(timezone.utc).date())
        for path in opensky.collect(args.first or first, args.last or last):  # files first: they survive a stopped database
            print("collected", path.name)
        with db.connect() as conn:
            print("opensky files:", len(opensky.load_all(conn)))
    elif command == "live":
        with db.connect() as conn:
            try:
                live.run(conn, args.every)
            except KeyboardInterrupt:
                print("stopped")
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
                print("opensky files:", len(opensky.load_all(conn)))
            if command in ("build", "all"):
                last_id = conn.execute("SELECT coalesce(max(id), 0) FROM dq.check_result").fetchone()[0]
                pipeline.build(conn)
                for name, value, passed in conn.execute(
                    "SELECT name, value, passed FROM dq.check_result WHERE id > %s ORDER BY id", (last_id,)
                ):
                    print(f"{name}: {value}{'' if passed is None else ' ok' if passed else ' FAILED'}")
            if command in ("report", "all"):
                for name, parts in report.REPORTS.items():
                    path = db.REPO / "docs" / name
                    path.write_text(report.render(conn, *parts))
                    print("wrote", path)


if __name__ == "__main__":
    main()
