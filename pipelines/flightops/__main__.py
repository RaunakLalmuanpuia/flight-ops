import argparse

from flightops import db
from flightops.sources import fetch, raw, registry


def main() -> None:
    parser = argparse.ArgumentParser(prog="flightops")
    parser.add_argument("command", choices=["migrate", "ddl", "fetch", "load"])
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
            if command == "migrate":
                print("applied:", db.migrate(conn))
            else:
                for f in registry.RAW_FILES:
                    result = raw.load_file(conn, f.source, f.table, f.path())
                    print(f"{f.table}: {result.rows} rows{' (already loaded)' if result.skipped else ''}")


if __name__ == "__main__":
    main()
