# Phase 4 Live Collection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `python -m flightops live` polls OpenSky state vectors and aviationweather.gov METAR/TAF for ATL, saves each response as a raw file, loads it, and rebuilds `ontology.live_position`, `ontology.live_weather` and `ontology.live_taf` on every tick. This covers phase 4 steps 1 and 2 in `docs/phase-4-plan.md`. The page (step 3) is a later plan.

**Architecture:** `sources/live.py` fetches and writes CSV files, reusing the raw loader. `transform/live.py` rebuilds the live ontology tables from raw in one transaction. `flightops/live.py` runs the loop, the way `pipeline.py` orchestrates the batch build. The live tables have no foreign keys to the July tables, because `resolve/ontology.sql` truncates those with `RESTART IDENTITY`.

**Tech Stack:** Python 3.12, `urllib` (as `sources/opensky.py` uses), psycopg 3, pytest, Postgres.

## Global Constraints

- Run tests from `pipelines/`: `uv run --env-file ../.env pytest`.
- Pipelines are the only writers to `raw`, `staging`, `ontology` and `dq`.
- Raw tables are all text, plus `source_file`, `source_sha256` and `loaded_at`. Never edited.
- Hex is uppercase in storage. OpenSky returns lowercase, and raw keeps it as delivered.
- Unresolved matches are kept with a reason. Never guess, never drop.
- Each resolved link stores its method and confidence.
- OpenSky box: 25 sq° or less costs 1 credit. Credentials come from `OPENSKY_CLIENT_ID` and `OPENSKY_CLIENT_SECRET` in `.env`.
- No new dependencies.

---

### Task 1: Probe both sources once

Confirms the formats this plan relies on. Costs 1 OpenSky state credit.

**Files:** none changed.

- [ ] **Step 1: Fetch one state snapshot and the weather**

Run from `pipelines/`:

```bash
uv run --env-file ../.env python -I -c "
import json, urllib.request
from flightops.sources import opensky
t = opensky._token()
url = 'https://opensky-network.org/api/states/all?lamin=32.1367&lamax=35.1367&lomin=-85.9281&lomax=-82.9281'
r = urllib.request.urlopen(urllib.request.Request(url, headers={'Authorization': 'Bearer ' + t}), timeout=30)
print('remaining', r.headers.get('X-Rate-Limit-Remaining'))
p = json.load(r)
print('time', p['time'], 'states', len(p['states'] or []), 'fields', {len(s) for s in p['states'] or []})
print(p['states'][0] if p['states'] else None)
"
curl -s "https://aviationweather.gov/api/data/metar?ids=KATL&format=json&hours=2" | head -c 400; echo
curl -s "https://aviationweather.gov/api/data/taf?ids=KATL&format=raw"
```

Note: `-I` drops the current directory from `sys.path`, so if `flightops` doesn't import, run without `-I` (this is our own code, not a download).

Expected: `fields {17}`, and the first state starts with a lowercase hex. The METAR JSON has `icaoId`, `obsTime`, `reportTime`, `metarType` and `rawOb`. The TAF is multi-line text starting `TAF KATL`.

- [ ] **Step 2: Reconcile**

If the field count isn't 17, change `STATE_FIELDS` in Task 2 to match the real arrays before writing any code. Write the snapshot size, field count and credits remaining under `## Notes` in `docs/phase-4-plan.md`.

---

### Task 2: Raw tables and the live source

**Files:**
- Create: `db/migrations/020_live.sql`
- Create: `pipelines/flightops/sources/live.py`
- Modify: `pipelines/flightops/sources/raw.py` (add `write_csv`)
- Modify: `pipelines/flightops/sources/opensky.py` (use `raw.write_csv`, delete `_write`)
- Create: `pipelines/tests/fixtures/live/states.json`, `pipelines/tests/fixtures/live/metar.json`, `pipelines/tests/fixtures/live/taf.txt`
- Test: `pipelines/tests/test_live_sources.py`

**Interfaces:**
- Produces: `raw.write_csv(path: Path, columns: list[str], rows: list[dict]) -> None`
- Produces, in `flightops.sources.live`: `ATL: tuple[float, float]`, `BOX: float`, `STATES_DIR`, `AWC_DIR`, `STATE_FIELDS: list[str]`, `fetch_states(token: str) -> dict`, `fetch_metar() -> list[dict]`, `fetch_taf() -> str`, `write_states(payload: dict) -> Path`, `write_metar(rows: list[dict], fetched_at: int) -> Path`, `write_taf(text: str, fetched_at: int) -> Path`
- Produces tables: `raw.opensky_state`, `raw.awc_metar`, `raw.awc_taf`, `staging.v_faa_current`, `staging.callsign_prefix`, `ontology.live_position`, `ontology.live_weather`, `ontology.live_taf`

- [ ] **Step 1: Write the migration**

`db/migrations/020_live.sql`:

```sql
-- Live collection (phase 4). Kept apart from the July tables: see DECISIONS.md, "Keep live data in its own tables".

CREATE TABLE raw.opensky_state (
    "time" text, "icao24" text, "callsign" text, "origin_country" text, "time_position" text, "last_contact" text,
    "longitude" text, "latitude" text, "baro_altitude" text, "on_ground" text, "velocity" text, "true_track" text,
    "vertical_rate" text, "sensors" text, "geo_altitude" text, "squawk" text, "spi" text, "position_source" text,
    source_file text NOT NULL,
    source_sha256 text NOT NULL,
    loaded_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE raw.awc_metar (
    "icaoid" text, "obstime" text, "reporttime" text, "metartype" text, "rawob" text,
    source_file text NOT NULL,
    source_sha256 text NOT NULL,
    loaded_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE raw.awc_taf (
    "fetched_at" text, "raw_text" text,
    source_file text NOT NULL,
    source_sha256 text NOT NULL,
    loaded_at timestamptz NOT NULL DEFAULT now()
);

-- Today's registry, for live aircraft. staging.faa_record holds only tails that flew in BTS July.
CREATE VIEW staging.v_faa_current AS
SELECT 'N' || trim(m.n_number) AS tail_number, upper(trim(m.mode_s_code_hex)) AS hex,
       trim(m.mfr_mdl_code) AS mfr_mdl_code, trim(t.mfr) AS manufacturer, trim(t.model) AS model
FROM staging.v_faa_master m
LEFT JOIN staging.v_faa_acftref t ON trim(t.code) = trim(m.mfr_mdl_code)
WHERE trim(m.mode_s_code_hex) <> '';

-- ICAO callsign prefixes seen at ATL. BTS gives no ICAO codes: see DECISIONS.md.
CREATE TABLE staging.callsign_prefix (
    prefix      text PRIMARY KEY,
    operator    text NOT NULL,
    bts_carrier text,
    source      text NOT NULL
);
INSERT INTO staging.callsign_prefix (prefix, operator, bts_carrier, source)
SELECT p, o, c, 'ICAO Doc 8585 designator, entered by hand 2026-11-22' FROM (VALUES
    ('DAL', 'Delta Air Lines', 'DL'), ('EDV', 'Endeavor Air', '9E'), ('SKW', 'SkyWest Airlines', 'OO'),
    ('RPA', 'Republic Airways', 'YX'), ('ENY', 'Envoy Air', 'MQ'), ('JIA', 'PSA Airlines', 'OH'),
    ('AAL', 'American Airlines', 'AA'), ('UAL', 'United Airlines', 'UA'), ('SWA', 'Southwest Airlines', 'WN'),
    ('JBU', 'JetBlue Airways', 'B6'), ('NKS', 'Spirit Airlines', 'NK'), ('FFT', 'Frontier Airlines', 'F9'),
    ('AAY', 'Allegiant Air', 'G4'), ('ASA', 'Alaska Airlines', 'AS'), ('HAL', 'Hawaiian Airlines', 'HA'),
    ('ASH', 'Mesa Airlines', NULL), ('GJS', 'GoJet Airlines', NULL), ('PDT', 'Piedmont Airlines', NULL),
    ('FDX', 'FedEx', NULL), ('UPS', 'UPS Airlines', NULL),
    ('KLM', 'KLM', NULL), ('AFR', 'Air France', NULL), ('VIR', 'Virgin Atlantic', NULL),
    ('KAL', 'Korean Air', NULL), ('BAW', 'British Airways', NULL), ('DLH', 'Lufthansa', NULL),
    ('AMX', 'Aeromexico', NULL), ('ACA', 'Air Canada', NULL), ('WJA', 'WestJet', NULL)
) v (p, o, c);

-- Rebuilt every tick from the latest snapshot. No foreign keys: the July rebuild restarts ontology identities.
CREATE TABLE ontology.live_position (
    snapshot_at        timestamptz NOT NULL,
    hex                text NOT NULL,
    callsign           text,
    tail_number        text,
    manufacturer       text,
    model              text,
    resolve_method     text,
    resolve_confidence text,
    unresolved_reason  text,
    operator           text,
    bts_carrier        text,
    operator_reason    text,
    latitude           double precision,
    longitude          double precision,
    position_at        timestamptz,
    on_ground          boolean,
    altitude_ft        integer,
    vertical_rate_fpm  integer,
    distance_nm        numeric,
    bearing_deg        integer
);

CREATE TABLE ontology.live_weather (
    station_icao   text NOT NULL,
    observed_at    timestamptz NOT NULL,
    metar_type     text,
    raw_text       text NOT NULL,
    wind_dir_deg   integer,
    wind_kt        integer,
    gust_kt        integer,
    visibility_sm  numeric,
    ceiling_ft     integer,
    temp_c         integer,
    dewpoint_c     integer,
    altimeter_inhg numeric,
    weather        text[] NOT NULL,
    PRIMARY KEY (station_icao, observed_at)
);

CREATE TABLE ontology.live_taf (
    fetched_at timestamptz NOT NULL,
    raw_text   text NOT NULL
);
```

- [ ] **Step 2: Write the fixtures**

`pipelines/tests/fixtures/live/states.json` (field order is OpenSky's: longitude comes before latitude):

```json
{"time": 1795368605, "states": [
  ["a00001", "DAL1674 ", "United States", 1795368600, 1795368601, -84.4281, 34.6367, 3048.0, false, 200.0, 180.0, -5.08, null, 3100.0, "1234", false, 0],
  ["a00002", "N200A   ", "United States", 1795368590, 1795368601, -83.2281, 33.6367, 914.4, false, 60.0, 270.0, 0.0, null, 950.0, null, false, 0],
  ["a00003", "XYZ123  ", "United States", 1795368500, 1795368601, -84.4281, 33.6367, null, true, 0.0, 90.0, null, null, null, null, false, 0],
  ["ffffff", null, "Mexico", null, 1795368601, null, null, null, false, null, null, null, null, null, null, false, 0]
]}
```

`pipelines/tests/fixtures/live/metar.json` (real KATL responses from 2026-11-22, trimmed to the fields we keep):

```json
[
  {"icaoId": "KATL", "obsTime": 1795368660, "reportTime": "2026-11-22T17:31:00.000Z", "metarType": "SPECI", "rawOb": "SPECI KATL 221731Z 05005KT 6SM BR OVC008 15/14 A2997 RMK AO2 DZB12E31 CIG 007V010 P0000 T01500139 $"},
  {"icaoId": "KATL", "obsTime": 1795366320, "reportTime": "2026-11-22T17:00:00.000Z", "metarType": "METAR", "rawOb": "METAR KATL 221652Z 04005KT 2SM BR OVC008 15/13 A2999 RMK AO2 SFC VIS 4 DZE50 SLP155 CIG 006V012 P0000 T01500133 $"}
]
```

`pipelines/tests/fixtures/live/taf.txt`:

```
TAF KATL 221726Z 2218/2324 02006KT 6SM BR BKN008
  FM222000 35004KT P6SM SCT007 BKN012
  FM230100 VRB03KT 6SM BR SCT012 BKN025
```

- [ ] **Step 3: Write the failing tests**

`pipelines/tests/test_live_sources.py`:

```python
import json
from pathlib import Path

import pytest

from flightops.sources import live, raw
LIVE = Path(__file__).parent / "fixtures" / "live"


@pytest.fixture
def dirs(monkeypatch, tmp_path):
    monkeypatch.setattr(live, "STATES_DIR", tmp_path / "opensky_states")
    monkeypatch.setattr(live, "AWC_DIR", tmp_path / "awc")
    return tmp_path


def states():
    return json.loads((LIVE / "states.json").read_text())


def test_box_stays_in_the_one_credit_tier():
    assert (2 * live.BOX) ** 2 <= 25


def test_fetch_states_asks_for_the_box_around_atl(monkeypatch):
    urls = []
    monkeypatch.setattr(live, "_get", lambda url, token=None: urls.append((url, token)) or '{"time": 1, "states": null}')
    live.fetch_states("t")
    url, token = urls[0]
    assert token == "t"
    assert "lamin=32.1367" in url and "lamax=35.1367" in url and "lomin=-85.9281" in url and "lomax=-82.9281" in url


def test_states_round_trip_as_delivered(conn, dirs):
    path = live.write_states(states())
    assert path.name == "KATL_states_1795368605.csv"
    assert raw.load_file(conn, "opensky", "opensky_state", path).rows == 4
    row = conn.execute("SELECT time, icao24, callsign, on_ground, latitude FROM raw.opensky_state ORDER BY icao24").fetchone()
    assert row == ("1795368605", "a00001", "DAL1674 ", "False", "34.6367")


def test_an_empty_box_writes_a_header_only_file(conn, dirs):
    path = live.write_states({"time": 5, "states": None})
    assert raw.load_file(conn, "opensky", "opensky_state", path).rows == 0


def test_a_changed_state_vector_fails_loudly(dirs):
    payload = states()
    payload["states"][0].append("surprise")
    with pytest.raises(ValueError):
        live.write_states(payload)
    assert not any((dirs / "opensky_states").glob("*.csv"))


def test_metar_and_multiline_taf_round_trip(conn, dirs):
    metar = live.write_metar(json.loads((LIVE / "metar.json").read_text()), 1795368700)
    taf = live.write_taf((LIVE / "taf.txt").read_text().strip(), 1795368700)
    assert raw.load_file(conn, "awc", "awc_metar", metar).rows == 2
    assert raw.load_file(conn, "awc", "awc_taf", taf).rows == 1
    assert conn.execute("SELECT raw_text FROM raw.awc_taf").fetchone()[0] == (LIVE / "taf.txt").read_text().strip()


def test_no_taf_writes_a_header_only_file(conn, dirs):
    assert raw.load_file(conn, "awc", "awc_taf", live.write_taf("", 1)).rows == 0
```

- [ ] **Step 4: Run the tests to check they fail**

Run: `uv run --env-file ../.env pytest tests/test_live_sources.py -v`
Expected: FAIL with `ImportError: cannot import name 'live'`.

- [ ] **Step 5: Move the CSV writer into `raw.py`**

Append to `pipelines/flightops/sources/raw.py`:

```python
def write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    part = path.with_name(path.name + ".part")  # never leave a partial file under the real name
    try:
        with part.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, columns)  # raises on a field we don't expect
            writer.writeheader()
            writer.writerows(rows)
    except ValueError:
        part.unlink()
        raise
    part.rename(path)
```

In `pipelines/flightops/sources/opensky.py`, delete `_write` and change its call in `collect` to:

```python
            raw.write_csv(path, COLUMNS, rows)
```

Then remove the now-unused `import csv` from `opensky.py`.

- [ ] **Step 6: Write the source module**

`pipelines/flightops/sources/live.py`:

```python
import json
import urllib.parse
import urllib.request
from pathlib import Path

from flightops.sources import raw
from flightops.sources.registry import DATA

STATES_DIR = DATA / "opensky_states"
AWC_DIR = DATA / "awc"
# shortcut: ATL only, from OurAirports; phase 6 (second hub) should read the airport table instead
ATL = (33.6367, -84.4281)
BOX = 1.5  # degrees each way: 3 x 3 = 9 sq deg, inside OpenSky's 1-credit tier of 25
STATES_URL = "https://opensky-network.org/api/states/all"
AWC_URL = "https://aviationweather.gov/api/data"
STATE_FIELDS = [
    "icao24", "callsign", "origin_country", "time_position", "last_contact", "longitude", "latitude",
    "baro_altitude", "on_ground", "velocity", "true_track", "vertical_rate", "sensors", "geo_altitude",
    "squawk", "spi", "position_source",
]
METAR_FIELDS = ["icaoId", "obsTime", "reportTime", "metarType", "rawOb"]  # rawOb is the delivered observation


def _get(url: str, token: str | None = None) -> str:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as response:
        return response.read().decode()


def fetch_states(token: str) -> dict:
    lat, lon = ATL
    query = urllib.parse.urlencode({
        "lamin": round(lat - BOX, 4), "lamax": round(lat + BOX, 4),
        "lomin": round(lon - BOX, 4), "lomax": round(lon + BOX, 4),
    })
    return json.loads(_get(f"{STATES_URL}?{query}", token))


def fetch_metar() -> list[dict]:
    return json.loads(_get(f"{AWC_URL}/metar?ids=KATL&format=json&hours=2") or "[]")  # empty body when none


def fetch_taf() -> str:
    return _get(f"{AWC_URL}/taf?ids=KATL&format=raw").strip()


def write_states(payload: dict) -> Path:
    rows = []
    for state in payload["states"] or []:  # null when the box is empty
        if len(state) != len(STATE_FIELDS):
            raise ValueError(f"state vector has {len(state)} fields, expected {len(STATE_FIELDS)}")
        rows.append({"time": payload["time"], **dict(zip(STATE_FIELDS, state))})
    STATES_DIR.mkdir(parents=True, exist_ok=True)
    path = STATES_DIR / f"KATL_states_{payload['time']}.csv"
    raw.write_csv(path, ["time", *STATE_FIELDS], rows)
    return path


def write_metar(rows: list[dict], fetched_at: int) -> Path:
    AWC_DIR.mkdir(parents=True, exist_ok=True)
    path = AWC_DIR / f"KATL_metar_{fetched_at}.csv"
    raw.write_csv(path, METAR_FIELDS, [{k: r.get(k) for k in METAR_FIELDS} for r in rows])
    return path


def write_taf(text: str, fetched_at: int) -> Path:
    AWC_DIR.mkdir(parents=True, exist_ok=True)
    path = AWC_DIR / f"KATL_taf_{fetched_at}.csv"
    raw.write_csv(path, ["fetched_at", "raw_text"], [{"fetched_at": fetched_at, "raw_text": text}] if text else [])
    return path
```

- [ ] **Step 7: Run the tests to check they pass**

Run: `uv run --env-file ../.env pytest tests/test_live_sources.py tests/test_opensky.py -v`
Expected: all PASS. `test_opensky.py` checks the `write_csv` move didn't break `collect`.

- [ ] **Step 8: Commit**

```bash
git add db/migrations/020_live.sql pipelines/flightops/sources/live.py pipelines/flightops/sources/raw.py \
  pipelines/flightops/sources/opensky.py pipelines/tests/fixtures/live pipelines/tests/test_live_sources.py
git commit -m "feat: live OpenSky states and aviationweather METAR/TAF into raw"
```

---

### Task 3: Rebuild the live ontology tables

**Files:**
- Create: `pipelines/flightops/transform/live.py`
- Create: `pipelines/tests/fixtures/live/faa_master.csv`
- Test: `pipelines/tests/test_live.py`

**Interfaces:**
- Consumes: everything Task 2 produces, `flightops.transform.weather.parse_metar(text) -> dict`
- Produces: `build_live(conn) -> tuple[int, int, int]`, returning (positions, with a tail, with an operator)

- [ ] **Step 1: Write the registry fixture**

`pipelines/tests/fixtures/live/faa_master.csv` (A00003 is on two registrations, to test the ambiguous case. The lowercase hex and the trailing spaces copy the real file):

```
n_number,mfr_mdl_code,mode_s_code_hex
102DN ,M2 ,A00001
200A ,M1 ,a00002
300A ,M1 ,A00003
301A ,M1 ,A00003
```

- [ ] **Step 2: Write the failing tests**

`pipelines/tests/test_live.py`:

```python
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from flightops.sources import live, raw
from flightops.transform.live import build_live
LIVE = Path(__file__).parent / "fixtures" / "live"
COLS = ("tail_number", "manufacturer", "model", "resolve_method", "resolve_confidence", "unresolved_reason",
        "operator", "bts_carrier", "operator_reason", "on_ground", "altitude_ft", "vertical_rate_fpm",
        "distance_nm", "bearing_deg")


@pytest.fixture
def built(conn, load_fixture, monkeypatch, tmp_path):
    monkeypatch.setattr(live, "STATES_DIR", tmp_path / "s")
    monkeypatch.setattr(live, "AWC_DIR", tmp_path / "a")
    load_fixture("faa_master", "live/faa_master.csv")
    load_fixture("faa_acftref", "faa_acftref.csv")
    raw.load_file(conn, "opensky", "opensky_state", live.write_states(json.loads((LIVE / "states.json").read_text())))
    metar = json.loads((LIVE / "metar.json").read_text())
    raw.load_file(conn, "awc", "awc_metar", live.write_metar(metar, 100))
    raw.load_file(conn, "awc", "awc_metar", live.write_metar(metar[:1], 200))  # the same SPECI fetched again
    raw.load_file(conn, "awc", "awc_taf", live.write_taf("TAF KATL old", 100))
    raw.load_file(conn, "awc", "awc_taf", live.write_taf("TAF KATL new", 200))
    counts = build_live(conn)
    rows = conn.execute(f"SELECT hex, {', '.join(COLS)} FROM ontology.live_position").fetchall()
    return counts, {r[0]: dict(zip(COLS, r[1:])) for r in rows}


def test_counts(built):
    assert built[0] == (4, 2, 1)


def test_lowercase_hex_resolves_to_a_tail_type_and_operator(built):
    row = built[1]["A00001"]
    assert row["tail_number"] == "N102DN" and (row["manufacturer"], row["model"]) == ("AIRBUS", "A321")
    assert (row["resolve_method"], row["resolve_confidence"], row["unresolved_reason"]) == ("faa_current_hex", "high", None)
    assert (row["operator"], row["bts_carrier"], row["operator_reason"]) == ("Delta Air Lines", "DL", None)


def test_units_distance_and_bearing(built):
    row = built[1]["A00001"]  # one degree due north of ATL, at 3,048 m, sinking 5.08 m/s
    assert (row["altitude_ft"], row["vertical_rate_fpm"]) == (10000, -1000)
    assert (row["distance_nm"], row["bearing_deg"]) == (Decimal("60.0"), 0)
    assert built[1]["A00002"]["bearing_deg"] == 90


def test_general_aviation_callsign_has_no_operator(built):
    row = built[1]["A00002"]
    assert row["tail_number"] == "N200A"
    assert (row["operator"], row["operator_reason"]) == (None, "general aviation callsign")


def test_hex_on_two_registrations_stays_unresolved(built):
    row = built[1]["A00003"]
    assert (row["tail_number"], row["resolve_method"], row["unresolved_reason"]) == (None, None, "ambiguous hex")
    assert (row["operator_reason"], row["on_ground"], row["distance_nm"]) == ("unknown prefix", True, Decimal("0.0"))


def test_unknown_hex_with_no_callsign_or_position_is_kept(built):
    row = built[1]["FFFFFF"]
    assert (row["unresolved_reason"], row["operator_reason"], row["distance_nm"]) == ("hex not in FAA registry", "no callsign", None)


def test_only_the_latest_snapshot_is_live(conn, built):
    raw.load_file(conn, "opensky", "opensky_state", live.write_states({"time": 1795368999, "states": None}))
    assert build_live(conn) == (0, 0, 0)


def test_repeated_metars_are_kept_once_and_parsed(conn, built):
    rows = conn.execute(
        "SELECT observed_at, metar_type, wind_dir_deg, visibility_sm, ceiling_ft, weather "
        "FROM ontology.live_weather ORDER BY observed_at"
    ).fetchall()
    assert len(rows) == 2
    assert rows[1] == (datetime(2026, 11, 22, 17, 31, tzinfo=timezone.utc), "SPECI", 50, Decimal("6"), 800, ["BR"])


def test_latest_taf_only(conn, built):
    assert conn.execute("SELECT raw_text FROM ontology.live_taf").fetchall() == [("TAF KATL new",)]
```

- [ ] **Step 3: Run the tests to check they fail**

Run: `uv run --env-file ../.env pytest tests/test_live.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'flightops.transform.live'`.

- [ ] **Step 4: Write the transform**

`pipelines/flightops/transform/live.py`:

```python
from flightops.sources.live import ATL
from flightops.transform.weather import parse_metar

# Raw is read directly: every live file is its own delivery, and the loader skips a repeated hash.
POSITIONS = """
INSERT INTO ontology.live_position
WITH s AS (
    SELECT to_timestamp("time"::bigint) AS snapshot_at, upper(icao24) AS hex, nullif(trim(callsign), '') AS callsign,
           nullif(latitude, '')::float8 AS lat, nullif(longitude, '')::float8 AS lon,
           to_timestamp(nullif(time_position, '')::bigint) AS position_at, on_ground = 'True' AS on_ground,
           round(nullif(baro_altitude, '')::numeric * 3.28084)::int AS altitude_ft,
           round(nullif(vertical_rate, '')::numeric * 196.850)::int AS vertical_rate_fpm
    FROM raw.opensky_state
    WHERE source_file = (SELECT source_file FROM dq.ingestion_run WHERE table_name = 'opensky_state' ORDER BY id DESC LIMIT 1)
), f AS (
    SELECT hex, min(tail_number) AS tail_number, min(manufacturer) AS manufacturer, min(model) AS model, count(*) AS n
    FROM staging.v_faa_current WHERE hex IN (SELECT hex FROM s) GROUP BY hex
)
SELECT s.snapshot_at, s.hex, s.callsign,
       CASE WHEN f.n = 1 THEN f.tail_number END,
       CASE WHEN f.n = 1 THEN f.manufacturer END,
       CASE WHEN f.n = 1 THEN f.model END,
       CASE WHEN f.n = 1 THEN 'faa_current_hex' END,
       CASE WHEN f.n = 1 THEN 'high' END,
       CASE WHEN f.n IS NULL THEN 'hex not in FAA registry' WHEN f.n > 1 THEN 'ambiguous hex' END,
       p.operator, p.bts_carrier,
       CASE WHEN p.prefix IS NOT NULL THEN NULL
            WHEN s.callsign IS NULL THEN 'no callsign'
            WHEN s.callsign ~ '^N[0-9][0-9A-Z]{0,4}$' THEN 'general aviation callsign'
            ELSE 'unknown prefix' END,
       s.lat, s.lon, s.position_at, s.on_ground, s.altitude_ft, s.vertical_rate_fpm,
       round((3440.065 * 2 * asin(sqrt(
           power(sin(radians(s.lat - %(lat)s) / 2), 2)
           + cos(radians(%(lat)s)) * cos(radians(s.lat)) * power(sin(radians(s.lon - %(lon)s) / 2), 2)
       )))::numeric, 1),
       mod(round(degrees(atan2(
           sin(radians(s.lon - %(lon)s)) * cos(radians(s.lat)),
           cos(radians(%(lat)s)) * sin(radians(s.lat))
           - sin(radians(%(lat)s)) * cos(radians(s.lat)) * cos(radians(s.lon - %(lon)s))
       )))::int + 360, 360)
FROM s
LEFT JOIN f USING (hex)
LEFT JOIN staging.callsign_prefix p ON s.callsign ~ '^[A-Z]{3}[0-9]' AND p.prefix = left(s.callsign, 3)
"""


def build_live(conn) -> tuple[int, int, int]:
    lat, lon = ATL
    metars = conn.execute(
        "SELECT DISTINCT ON (icaoid, obstime) icaoid, to_timestamp(obstime::bigint), metartype, rawob "
        "FROM raw.awc_metar ORDER BY icaoid, obstime"
    ).fetchall()
    with conn.transaction():
        conn.execute("TRUNCATE ontology.live_position, ontology.live_weather, ontology.live_taf")
        conn.execute(POSITIONS, {"lat": lat, "lon": lon})
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO ontology.live_weather (station_icao, observed_at, metar_type, raw_text, wind_dir_deg, "
                "wind_kt, gust_kt, visibility_sm, ceiling_ft, temp_c, dewpoint_c, altimeter_inhg, weather) "
                "VALUES (%(station)s, %(observed_at)s, %(type)s, %(raw)s, %(wind_dir_deg)s, %(wind_kt)s, %(gust_kt)s, "
                "%(visibility_sm)s, %(ceiling_ft)s, %(temp_c)s, %(dewpoint_c)s, %(altimeter_inhg)s, %(weather)s)",
                [{"station": s, "observed_at": t, "type": k, "raw": m, **parse_metar(m)} for s, t, k, m in metars],
            )
        conn.execute(
            "INSERT INTO ontology.live_taf SELECT to_timestamp(fetched_at::bigint), raw_text "
            "FROM raw.awc_taf ORDER BY fetched_at::bigint DESC LIMIT 1"
        )
    return conn.execute(
        "SELECT count(*), count(tail_number), count(operator) FROM ontology.live_position"
    ).fetchone()
```

- [ ] **Step 5: Run the tests to check they pass**

Run: `uv run --env-file ../.env pytest tests/test_live.py -v`
Expected: all PASS. If the bearing test for A00002 gives 89, the great-circle starting bearing is just under 90. Leave the SQL as it is and fix the assertion to the value it computes, since 89 and 90 are both correct for "due east".

- [ ] **Step 6: Commit**

```bash
git add pipelines/flightops/transform/live.py pipelines/tests/fixtures/live/faa_master.csv pipelines/tests/test_live.py
git commit -m "feat: resolve live positions to tail, type and operator"
```

---

### Task 4: The loop and the `live` command

**Files:**
- Create: `pipelines/flightops/live.py`
- Modify: `pipelines/flightops/__main__.py`
- Test: `pipelines/tests/test_live_loop.py`

**Interfaces:**
- Consumes: `flightops.sources.live` (Task 2), `build_live` (Task 3), `opensky._token() -> str`, `raw.load_file`
- Produces: `tick(conn, n: int, state: dict) -> int` (seconds the source asked us to wait, 0 if none), `run(conn, every: int = 60, ticks: int | None = None, sleep=time.sleep) -> None`

- [ ] **Step 1: Write the failing tests**

`pipelines/tests/test_live_loop.py`:

```python
import io
import json
import urllib.error
from pathlib import Path

import pytest

from flightops import live as loop
from flightops.sources import live, opensky
LIVE = Path(__file__).parent / "fixtures" / "live"


@pytest.fixture
def sources(monkeypatch, tmp_path):
    monkeypatch.setattr(live, "STATES_DIR", tmp_path / "s")
    monkeypatch.setattr(live, "AWC_DIR", tmp_path / "a")
    monkeypatch.setattr(opensky, "_token", lambda: "t")
    monkeypatch.setattr(live, "fetch_states", lambda token: json.loads((LIVE / "states.json").read_text()))
    monkeypatch.setattr(live, "fetch_metar", lambda: json.loads((LIVE / "metar.json").read_text()))
    monkeypatch.setattr(live, "fetch_taf", lambda: "TAF KATL x")


def raises(exc):
    def fetch(*args):
        raise exc
    return fetch


def http_error(code, headers=None):
    return raises(urllib.error.HTTPError("u", code, "x", headers or {}, io.BytesIO(b"")))


def count(conn, table):
    return conn.execute(f"SELECT count(*) FROM ontology.{table}").fetchone()[0]


def test_first_tick_fetches_everything(conn, sources):
    assert loop.tick(conn, 0, {}) == 0
    assert (count(conn, "live_position"), count(conn, "live_weather"), count(conn, "live_taf")) == (4, 2, 1)


def test_weather_is_fetched_every_fifth_tick_only(conn, sources, monkeypatch):
    monkeypatch.setattr(live, "fetch_metar", lambda: pytest.fail("weather fetched on tick 1"))
    loop.tick(conn, 1, {})


def test_expired_token_is_dropped_and_the_tick_still_builds(conn, sources, monkeypatch):
    monkeypatch.setattr(live, "fetch_states", http_error(401))
    state = {"token": "old"}
    assert loop.tick(conn, 0, state) == 0
    assert state["token"] is None
    assert count(conn, "live_weather") == 2


def test_quota_exhausted_returns_the_wait(conn, sources, monkeypatch):
    monkeypatch.setattr(live, "fetch_states", http_error(429, {"X-Rate-Limit-Retry-After-Seconds": "900"}))
    assert loop.tick(conn, 1, {}) == 900


def test_network_failure_does_not_stop_the_loop(conn, sources, monkeypatch):
    monkeypatch.setattr(live, "fetch_states", raises(urllib.error.URLError("down")))
    monkeypatch.setattr(live, "fetch_metar", raises(TimeoutError()))
    loop.tick(conn, 0, {})


def test_run_sleeps_the_interval_or_the_longer_wait(conn, sources, monkeypatch):
    waits = iter([0, 900])
    monkeypatch.setattr(loop, "tick", lambda conn, n, state: next(waits))
    slept = []
    loop.run(conn, every=60, ticks=2, sleep=slept.append)
    assert slept == [60, 900]
```

- [ ] **Step 2: Run the tests to check they fail**

Run: `uv run --env-file ../.env pytest tests/test_live_loop.py -v`
Expected: FAIL with `ImportError: cannot import name 'live' from 'flightops'`.

- [ ] **Step 3: Write the loop**

`pipelines/flightops/live.py`:

```python
import time
import urllib.error

from flightops.sources import live, opensky, raw
from flightops.transform.live import build_live

WEATHER_EVERY = 5  # ticks: METARs come about hourly, so every 5 minutes is plenty


def tick(conn, n: int, state: dict) -> int:
    """One poll. Source errors are printed and skipped; database errors propagate and stop the loop."""
    files, wait = [], 0
    try:
        state["token"] = state.get("token") or opensky._token()
        files.append(("opensky", "opensky_state", live.write_states(live.fetch_states(state["token"]))))
    except urllib.error.HTTPError as e:
        if e.code == 401:
            state["token"] = None  # tokens last 30 minutes; the next tick gets a new one
        wait = int(e.headers.get("X-Rate-Limit-Retry-After-Seconds") or 0)
        print(f"states: HTTP {e.code}")
    except (urllib.error.URLError, TimeoutError) as e:
        print(f"states: {e}")
    if n % WEATHER_EVERY == 0:
        fetched_at = int(time.time())
        try:
            files.append(("awc", "awc_metar", live.write_metar(live.fetch_metar(), fetched_at)))
            files.append(("awc", "awc_taf", live.write_taf(live.fetch_taf(), fetched_at)))
        except (urllib.error.URLError, TimeoutError) as e:
            print(f"weather: {e}")
    for source, table, path in files:
        raw.load_file(conn, source, table, path)
    positions, tails, operators = build_live(conn)
    print(f"tick {n}: {positions} aircraft, {tails} with a tail, {operators} with an operator")
    return wait


def run(conn, every: int = 60, ticks: int | None = None, sleep=time.sleep) -> None:
    n = 0
    state: dict = {}
    while ticks is None or n < ticks:
        wait = tick(conn, n, state)
        n += 1
        sleep(max(every, wait))
```

- [ ] **Step 4: Wire the command**

In `pipelines/flightops/__main__.py`, change the imports and choices:

```python
from flightops import db, live, pipeline, report
```

```python
    parser.add_argument("command", choices=["migrate", "ddl", "fetch", "load", "build", "report", "all", "collect", "live"])
    parser.add_argument("--from", dest="first", type=date.fromisoformat)
    parser.add_argument("--to", dest="last", type=date.fromisoformat)
    parser.add_argument("--every", type=int, default=60, help="seconds between live polls")
```

and add a branch before the final `else:`:

```python
    elif command == "live":
        with db.connect() as conn:
            try:
                live.run(conn, args.every)
            except KeyboardInterrupt:
                print("stopped")
```

- [ ] **Step 5: Run the whole suite**

Run: `uv run --env-file ../.env pytest`
Expected: all PASS, including the existing tests.

- [ ] **Step 6: Real run**

Run from `pipelines/`:

```bash
uv run --env-file ../.env python -m flightops migrate
uv run --env-file ../.env python -m flightops live
```

Let it run for 3 ticks, then press Ctrl-C. Expected: three `tick N: ...` lines and `stopped`. Then check:

```bash
psql -h localhost flightops -c "select unresolved_reason, operator_reason, count(*) from ontology.live_position group by 1, 2 order by 3 desc" -c "select observed_at, raw_text from ontology.live_weather order by 1 desc limit 2"
```

Write the aircraft count, the share with a tail, the share with an operator, and the most common unknown prefixes under `## Notes` in `docs/phase-4-plan.md`. If one unknown prefix accounts for many rows, add it to `staging.callsign_prefix` in a new migration, not by editing 020.

- [ ] **Step 7: Commit**

```bash
git add pipelines/flightops/live.py pipelines/flightops/__main__.py pipelines/tests/test_live_loop.py docs/phase-4-plan.md
git commit -m "feat: live command polls ATL states and weather"
```

Then update `CLAUDE.md` Status (phase 4 steps 1-2 done, `live` in the command list, next is the Live page plan) and commit it as `docs: status after phase 4 steps 1-2`.
