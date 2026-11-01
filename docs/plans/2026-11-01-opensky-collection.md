# OpenSky Collection Job Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans and superpowers:test-driven-development. Use superpowers:verification-before-completion before calling a step done. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A daily job on this Mac saves ATL arrivals and departures from OpenSky into `raw`, catches up after missed days, and has backfilled July 2024.

**Architecture:** One small module flattens each API response to a CSV in `data/raw/opensky/`, then the existing `raw.load_file` loads it, so hashing, idempotence and quarantine are reused. Files are written before the database is touched, so a stopped Postgres loses nothing. `launchd` runs it daily.

**Tech Stack:** Python 3.12 or newer standard library `urllib`, `psycopg` 3, `pytest`, `launchd`.

## Global Constraints

- Credentials come only from `OPENSKY_CLIENT_ID` and `OPENSKY_CLIENT_SECRET`. Never print or commit them or the token.
- Pipelines are the only writers to `raw`. Schema changes go through `db/migrations/`.
- Respect the quota: 4,000 credits a day for this endpoint group, and each query costs 30.
- Raw means as delivered. Callsigns keep their trailing spaces, and hex stays lowercase until staging.
- No staging, ontology or callsign resolution here. That is phase 4.
- Run `uv` commands from `pipelines/`, and `git` commands from the repo root.

## Findings from probing the real API, 2026-11-01

| Finding | Evidence | Design consequence |
|---|---|---|
| Each query costs 30 credits, whatever its length or result | 1-hour and 24-hour queries, and a 404, each cost 30. Remaining went from 3,970 to 3,790 over 6 queries | Query whole days. Two a day costs 60 credits, as the roadmap estimated |
| History reaches back at least to July 2024 | Rows returned for 30 days ago, 365 days ago and 2024-07-19 | **Corrects the roadmap**, which feared history might not be recoverable. The daily job is not urgent |
| OpenSky corroborates the outage, in the one hour tested | ATL arrivals 12:00-13:00 UTC on 2024-07-19: BTS 21, with 1 DL or 9E. OpenSky 27, with 2 `DAL` or `EDV`. BTS on July 12 and 26 shows 81 and 85, with 66 and 67 | Backfill July 2024. It is independent evidence for the report, if the rest of the month holds up |
| Coverage looks good for a recent day | 2026-10-31: 997 arrivals and 861 departures | Reasonable, but no BTS file exists yet for that date to compare with |
| A day with no data yet returns 404 | Today's 00:00 UTC hour returned 404 with body `[]` and still cost 30 | 404 means "not ready": write no file, and retry on the next run |
| Some fields can be blank | 2 of 84 arrivals had no `estDepartureAirport` | Stored blank in raw |

The probed quota figure assumes the count started at 4,000. Nothing has been measured about when a finished day's data stops changing.

## Decisions for review

1. **Backfill July 2024 now, once, for 1,860 credits** (31 days, 2 queries, 30 each). It fits inside one day's quota. It is the only part of this plan that bears on phase 1's findings.
2. **Only collect days at least 2 UTC days old.** The API updates in batches, and this avoids saving a partial day, because a saved file is never fetched again. The cost is data arriving a day later.
3. **Catch up over the last 7 settled days on each run.** A Mac that is off for up to a week loses nothing. Longer gaps can be filled with `--from` and `--to`, because history reaches far back.
4. **Keep files only on this Mac.** `data/raw/` is gitignored, as for every other source. Since history can be fetched again, losing them costs credits rather than data.

## Not built here

- Staging, ontology, hex or callsign resolution, and any report change. The July comparison goes in `docs/data-sources.md` only, until it has been reviewed.
- Other airports, position data, retries or alerts. A failed run logs its error, and the next run catches up.

## Open item

I haven't read OpenSky's terms of use. Task 1 reads them first. If they rule out this use, stop and tell the user.

## File Structure

| Path | Responsibility |
|---|---|
| `db/migrations/010_opensky.sql` | `raw.opensky_flight` |
| `pipelines/flightops/sources/opensky.py` | Token, fetch, CSV writing, loading |
| `pipelines/tests/test_opensky.py` | Tests |
| `ops/com.flightops.opensky.plist` | `launchd` schedule |

---

### Task 1: Collect days into files and `raw`

**Files:**
- Create: `db/migrations/010_opensky.sql`, `pipelines/flightops/sources/opensky.py`, `pipelines/tests/test_opensky.py`
- Modify: `pipelines/flightops/__main__.py`, `.env.example`, `docs/roadmap.md`, `DECISIONS.md`, `CLAUDE.md`

**Interfaces:**
- Consumes: `raw.load_file`, `registry.DATA`.
- Produces: `opensky.collect(first: date, last: date) -> list[Path]`, `opensky.load_all(conn) -> list[raw.LoadResult]`, `opensky.settled_days(today: date) -> tuple[date, date]`, and CLI command `collect [--from YYYY-MM-DD] [--to YYYY-MM-DD]`.

- [ ] **Step 1: Read OpenSky's terms of use**

Read the terms on `opensky-network.org`. Continue if they allow this project's use, and record the outcome in `docs/data-sources.md` in Step 7.

- [ ] **Step 2: Write the failing tests**

`pipelines/tests/test_opensky.py`:

```python
import io
import urllib.error
from datetime import date

import pytest

from flightops.sources import opensky

ROW = {
    "icao24": "ab92c4", "firstSeen": 1793449096, "estDepartureAirport": None, "lastSeen": 1793451539,
    "estArrivalAirport": "KATL", "callsign": "DAL1674 ", "estDepartureAirportHorizDistance": 6308,
    "estDepartureAirportVertDistance": 459, "estArrivalAirportHorizDistance": 1047,
    "estArrivalAirportVertDistance": 129, "departureAirportCandidatesCount": 2, "arrivalAirportCandidatesCount": 22,
}
DAY = date(2026, 10, 30)


@pytest.fixture
def api(monkeypatch, tmp_path):
    calls = []

    def fetch(kind, day, token):
        calls.append((kind, day))
        return [ROW]

    monkeypatch.setattr(opensky, "DIR", tmp_path)
    monkeypatch.setattr(opensky, "_token", lambda: "t")
    monkeypatch.setattr(opensky, "_fetch", fetch)
    return calls


def test_one_day_writes_arrivals_and_departures(api, tmp_path):
    written = opensky.collect(DAY, DAY)
    assert [p.name for p in written] == ["KATL_arrival_2026-10-30.csv", "KATL_departure_2026-10-30.csv"]


def test_a_collected_day_is_never_fetched_again(api):
    opensky.collect(DAY, DAY)
    api.clear()
    assert opensky.collect(DAY, DAY) == []
    assert api == []


def test_no_token_is_requested_when_nothing_is_missing(api, monkeypatch):
    opensky.collect(DAY, DAY)
    monkeypatch.setattr(opensky, "_token", lambda: pytest.fail("token requested"))
    opensky.collect(DAY, DAY)


def test_day_with_no_data_yet_writes_no_file_and_is_retried(api, monkeypatch, tmp_path):
    real = opensky._fetch
    monkeypatch.setattr(opensky, "_fetch", lambda kind, day, token: None)
    assert opensky.collect(DAY, DAY) == []
    assert list(tmp_path.iterdir()) == []
    monkeypatch.setattr(opensky, "_fetch", real)
    assert len(opensky.collect(DAY, DAY)) == 2


def test_a_new_api_field_fails_loudly(api, monkeypatch, tmp_path):
    monkeypatch.setattr(opensky, "_fetch", lambda kind, day, token: [{**ROW, "surprise": 1}])
    with pytest.raises(ValueError):
        opensky.collect(DAY, DAY)
    assert list(tmp_path.iterdir()) == []


def test_fetch_treats_404_as_not_ready_and_raises_on_quota(monkeypatch):
    def raises(code):
        def urlopen(request, timeout):
            raise urllib.error.HTTPError("u", code, "x", {}, io.BytesIO(b"[]"))
        return urlopen

    monkeypatch.setattr(opensky.urllib.request, "urlopen", raises(404))
    assert opensky._fetch("arrival", DAY, "t") is None
    monkeypatch.setattr(opensky.urllib.request, "urlopen", raises(429))
    with pytest.raises(urllib.error.HTTPError):
        opensky._fetch("arrival", DAY, "t")


def test_settled_days_end_two_days_back_and_span_seven(api):
    assert opensky.settled_days(date(2026, 11, 1)) == (date(2026, 10, 24), date(2026, 10, 30))


def test_files_load_as_delivered_and_reload_changes_nothing(api, conn):
    opensky.collect(DAY, DAY)
    assert [r.skipped for r in opensky.load_all(conn)] == [False, False]
    assert [r.skipped for r in opensky.load_all(conn)] == [True, True]
    assert conn.execute(
        "select count(*), min(callsign), min(icao24), min(coalesce(estdepartureairport, 'null')) from raw.opensky_flight"
    ).fetchone() == (2, "DAL1674 ", "ab92c4", "")
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run --env-file ../.env pytest tests/test_opensky.py -q`
Expected: collection error, `opensky` does not exist.

- [ ] **Step 4: Implement**

`db/migrations/010_opensky.sql`:

```sql
CREATE TABLE raw.opensky_flight (
    "icao24" text,
    "firstseen" text,
    "estdepartureairport" text,
    "lastseen" text,
    "estarrivalairport" text,
    "callsign" text,
    "estdepartureairporthorizdistance" text,
    "estdepartureairportvertdistance" text,
    "estarrivalairporthorizdistance" text,
    "estarrivalairportvertdistance" text,
    "departureairportcandidatescount" text,
    "arrivalairportcandidatescount" text,
    source_file text NOT NULL,
    source_sha256 text NOT NULL,
    loaded_at timestamptz NOT NULL DEFAULT now()
);
```

`pipelines/flightops/sources/opensky.py`:

```python
import csv
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from flightops.sources import raw
from flightops.sources.registry import DATA

DIR = DATA / "opensky"
AIRPORT = "KATL"
TOKEN_URL = "https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token"
API_URL = "https://opensky-network.org/api/flights"
COLUMNS = [
    "icao24", "firstSeen", "estDepartureAirport", "lastSeen", "estArrivalAirport", "callsign",
    "estDepartureAirportHorizDistance", "estDepartureAirportVertDistance",
    "estArrivalAirportHorizDistance", "estArrivalAirportVertDistance",
    "departureAirportCandidatesCount", "arrivalAirportCandidatesCount",
]


def settled_days(today: date) -> tuple[date, date]:
    # the API updates in batches, and a saved day is never fetched again, so skip days that may be partial
    return today - timedelta(days=8), today - timedelta(days=2)


def _token() -> str:
    body = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": os.environ["OPENSKY_CLIENT_ID"],
        "client_secret": os.environ["OPENSKY_CLIENT_SECRET"],
    }).encode()
    with urllib.request.urlopen(urllib.request.Request(TOKEN_URL, data=body), timeout=30) as response:
        return json.load(response)["access_token"]


def _fetch(kind: str, day: date, token: str) -> list[dict] | None:
    begin = int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp())
    url = f"{API_URL}/{kind}?airport={AIRPORT}&begin={begin}&end={begin + 86399}"
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            return json.load(response)
    except urllib.error.HTTPError as e:
        if e.code == 404:  # not ready yet, so the next run retries it
            return None
        raise


def _write(path: Path, rows: list[dict]) -> None:
    part = path.with_name(path.name + ".part")  # never leave a partial file under the real name
    try:
        with part.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, COLUMNS)  # raises on a field we don't expect
            writer.writeheader()
            writer.writerows(rows)
    except ValueError:
        part.unlink()
        raise
    part.rename(path)


def collect(first: date, last: date) -> list[Path]:
    DIR.mkdir(parents=True, exist_ok=True)
    token = None
    written = []
    for offset in range((last - first).days + 1):
        day = first + timedelta(days=offset)
        for kind in ("arrival", "departure"):
            path = DIR / f"{AIRPORT}_{kind}_{day.isoformat()}.csv"
            if path.exists():
                continue
            token = token or _token()
            rows = _fetch(kind, day, token)
            if rows is None:
                print(f"not ready: {path.name}")
                continue
            _write(path, rows)
            written.append(path)
    return written


def load_all(conn) -> list[raw.LoadResult]:
    return [raw.load_file(conn, "opensky", "opensky_flight", p) for p in sorted(DIR.glob(f"{AIRPORT}_*.csv"))]
```

In `pipelines/flightops/__main__.py`:

1. Change the imports to include `from datetime import date, datetime, timezone` and `from flightops.sources import fetch, opensky, raw, registry`.
2. Add `"collect"` to the choices, and after that argument add:

```python
    parser.add_argument("--from", dest="first", type=date.fromisoformat)
    parser.add_argument("--to", dest="last", type=date.fromisoformat)
```

3. Change `command = parser.parse_args().command` to:

```python
    args = parser.parse_args()
    command = args.command
```

4. Add before the final `else:` branch:

```python
    elif command == "collect":
        first, last = opensky.settled_days(datetime.now(timezone.utc).date())
        for path in opensky.collect(args.first or first, args.last or last):  # files first: they survive a stopped database
            print("collected", path.name)
        with db.connect() as conn:
            print("opensky files:", len(opensky.load_all(conn)))
```

5. In the `load` block, after the `RAW_FILES` loop, add:

```python
                print("opensky files:", len(opensky.load_all(conn)))
```

Note that `load_all` must tolerate a missing directory, which `Path.glob` does by returning nothing.

`.env.example` already lists both variables with placeholder values, so commit it as it stands.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run --env-file ../.env pytest -q`
Expected: all passed.

- [ ] **Step 6: Collect one real day**

Run: `uv run --env-file ../.env python -m flightops collect --from 2026-10-30 --to 2026-10-30`, then the same again.
Expected: the first run collects 2 files and uses 60 credits. The second collects nothing and requests no token. `raw.opensky_flight` has the same row count after both.

- [ ] **Step 7: Correct the docs and commit**

In `docs/roadmap.md`, replace the "OpenSky collection starts right after phase 1" bullet with: "**OpenSky collection starts right after phase 1:** a small daily job for ATL arrivals and departures. Probing showed flight history reaching back to at least July 2024, so this is cheap and worthwhile rather than urgent. Each query costs 30 of 4,000 daily credits, so a daily pull costs 60."

Add an OpenSky section to `docs/data-sources.md` with the findings table above and the terms outcome. In `CLAUDE.md`, add `collect` to the commands, and add to the OpenSky row of Data sources: "The flights endpoints reach back to at least July 2024, and each query costs 30 credits."

Append to `DECISIONS.md`:

```markdown
## 2026-11-01: Collect OpenSky days as files, and only once they have settled
- **Chose:** one CSV per airport, direction and UTC day, written before loading through the existing raw loader. Only days at least 2 days old are collected, and a saved day is never fetched again.
- **Gave up:** data from yesterday, and any corrections OpenSky makes after a day has been saved.
- **Why:** reusing the loader keeps hashing and idempotence in one place, files survive a stopped database, and a saved partial day would otherwise never be repaired.
- **Revisit if:** phase 4 needs fresher data, or a re-fetch shows settled days still change.
```

```bash
git add db pipelines docs DECISIONS.md CLAUDE.md .env.example
git commit -m "feat: collect ATL flights from OpenSky into raw"
```

---

### Task 2: Backfill July 2024 and compare with BTS

**Files:**
- Modify: `docs/data-sources.md`, `CLAUDE.md`

**Interfaces:**
- Consumes: CLI `collect`.
- Produces: `raw.opensky_flight` holding July 2024, and a recorded comparison.

- [ ] **Step 1: Backfill**

Run: `uv run --env-file ../.env python -m flightops collect --from 2024-07-01 --to 2024-07-31`
Expected: 62 files and 1,860 credits, with no query for days already held. On a 429, stop and rerun the next day, which picks up where it stopped.

- [ ] **Step 2: Compare by day**

Run in `psql -h localhost flightops`, with `SET timezone = 'UTC';` first:

```sql
WITH os AS (
    SELECT to_timestamp(lastseen::bigint)::date AS day, count(*) AS opensky,
           count(*) FILTER (WHERE left(callsign, 3) IN ('DAL', 'EDV')) AS opensky_dl_9e
    FROM raw.opensky_flight
    WHERE source_file LIKE 'KATL_arrival_2024-07-%' AND estarrivalairport = 'KATL'
    GROUP BY 1
), bts AS (
    SELECT f.actual_arr_utc::date AS day, count(*) AS bts,
           count(*) FILTER (WHERE c.code IN ('DL', '9E')) AS bts_dl_9e
    FROM ontology.flight f
    JOIN ontology.carrier c USING (carrier_id)
    JOIN ontology.airport a ON a.airport_id = f.landed_airport_id
    WHERE a.iata_code = 'ATL'
    GROUP BY 1
)
SELECT day, bts, opensky, bts_dl_9e, opensky_dl_9e FROM bts LEFT JOIN os USING (day)
WHERE day BETWEEN '2024-07-01' AND '2024-07-31' ORDER BY 1;
```

Expected: the July 19-23 dip in `opensky_dl_9e` follows `bts_dl_9e`. This is a day-level comparison of counts, not a flight-level match. Record whatever it shows, including a poor match, and any days of thin coverage.

Also record blank `estarrivalairport` rows if any, because a query for ATL arrivals may return flights whose estimate names another airport.

- [ ] **Step 3: Record and commit**

Add the table and a plain reading of it to the OpenSky section of `docs/data-sources.md`. Don't change the report. Tell the user what it shows, so they can decide whether it belongs there.

```bash
git add docs CLAUDE.md
git commit -m "docs: compare the OpenSky July 2024 backfill with BTS"
```

---

### Task 3: Schedule it daily

**Files:**
- Create: `ops/com.flightops.opensky.plist`
- Modify: `CLAUDE.md`

**Interfaces:**
- Consumes: CLI `collect`.
- Produces: an installed user `launchd` agent. Removing it: `launchctl bootout gui/$(id -u)/com.flightops.opensky`.

- [ ] **Step 1: Write the schedule**

`launchd` runs a missed calendar job when the Mac next wakes, though not if it was fully shut down at that time. The catch-up window covers that case.

`ops/com.flightops.opensky.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.flightops.opensky</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/zsh</string>
        <string>-lc</string>
        <string>cd /Users/raunak/Developer/Side/flight-ops/pipelines &amp;&amp; uv run --env-file ../.env python -m flightops collect &gt;&gt; ../data/raw/opensky/collect.log 2&gt;&amp;1</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>9</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
</dict>
</plist>
```

- [ ] **Step 2: Install it and prove it runs**

```bash
cp ops/com.flightops.opensky.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.flightops.opensky.plist
launchctl kickstart -k gui/$(id -u)/com.flightops.opensky
```

Expected: `data/raw/opensky/collect.log` shows the settled days being collected or already present, with no traceback, and the log never contains a credential. `launchctl print gui/$(id -u)/com.flightops.opensky` reports exit code 0.

- [ ] **Step 3: Update Status and commit**

In `CLAUDE.md`, record that the job is installed and how to remove it, with the next action being phase 2 brainstorming.

```bash
git add ops CLAUDE.md
git commit -m "feat: schedule the daily OpenSky collection"
```

---

## Build notes, 2026-11-01

- **Terms:** the site refused an automated fetch of the terms page, so the user read them and confirmed this use is allowed.
- **`launchd`:** the planned plist failed with exit 127, because `uv` isn't on the login shell's `PATH` under `launchd`. The plist now uses `/opt/homebrew/bin/uv`.
- **Test fixture:** arrival and departure rows now differ, because the loader correctly skips a repeated file hash.

- **Task 3 reversed:** the user chose to run collection by hand, so the `launchd` agent was uninstalled and `ops/` removed.
