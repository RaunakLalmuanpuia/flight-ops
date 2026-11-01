# flight-ops

Airline operations control tool for one US hub, starting with ATL. It is a portfolio project for Palantir-style forward deployed engineer roles, so it should show messy data turned into an operational model that someone can make decisions from. Favor defensible data and clear reasoning over feature count.

## Status

- **Current phase:** 1, built. Steps 1-7 are done, and a fresh database reproduces the counts.
- **Next action:** user decides whether to merge `opensky-collection` to `main` and whether the OpenSky comparison belongs in the phase 1 report. Then phase 2, which needs brainstorming first.
- **Built so far:** migration runner, idempotent raw loader with quarantine, downloads, staging, tail resolution, ontology promotion behind blocking checks, rotations, the ATL weather join, the generated report and the CLI. The local `flightops` database holds the July 2024 ontology, and measured results are in `docs/data-sources.md`. OpenSky ATL arrivals and departures are collected daily by a `launchd` agent at 09:00, from `ops/com.flightops.opensky.plist`, logging to `data/raw/opensky/collect.log`. Remove it with `launchctl bootout gui/$(id -u)/com.flightops.opensky`. It runs from the working tree, so the checked-out branch must contain `sources/opensky.py`.
- **Commands (from `pipelines/`):** `uv run --env-file ../.env pytest`, and `uv run --env-file ../.env python -m flightops {migrate,ddl,fetch,load,build,report,all,collect}`.
- **Repo:** phase 1 is merged to `main` locally, not pushed. OpenSky work is on branch `opensky-collection`.

Keep this section current: update it at the end of every work session and whenever a step finishes, so a new session knows where things stand without being told.

## Session workflow

At the start of a session, state the current phase and next action from Status in one or two lines.

When the user says "start phase N" or "continue":

1. Read `DECISIONS.md`, `docs/roadmap.md` and the phase's plan in `docs/`. Phase 1's design is approved, so don't brainstorm it again. Later phases with no plan file need `superpowers:brainstorming` first.
2. If the repo has no commits, rename the branch to `main` and commit the existing docs. Saying "start" authorizes this one commit.
3. Check that `pg_isready -h localhost` reports accepting connections. If it doesn't, stop and tell the user.
4. Use `superpowers:writing-plans` for only the next few steps of the phase, then stop for the user's review before building. Save it under `docs/plans/`.
5. After approval, build with `superpowers:executing-plans` and `superpowers:test-driven-development`, and use `superpowers:verification-before-completion` before calling a step done.

## Stack

- **Pipelines:** Python, managed with `uv`. Pipelines are the only writers to `raw`, `staging`, `ontology` and `dq`.
- **Database:** Postgres. PostGIS comes later, when a feature needs geospatial queries.
- **App:** Laravel + Inertia + Vue + Tailwind. It reads from `ontology` and `dq` and never writes to them. App-owned tables (users, sessions) live in `app`.
- **Runtime:** local for now: Postgres.app, a `uv` virtual environment in `pipelines/.venv`, and the Laravel dev server (`php artisan serve`). Don't add Docker until the final roadmap phase.

## Data sources

| Source | Provides | Constraints |
|---|---|---|
| BTS Reporting Carrier On-Time Performance | Flights, tails, delays, cancellations | Monthly files, published with a lag. Domestic flights by reporting carriers only |
| FAA aircraft registry | Tail number to ICAO hex, type, owner | Current snapshot. `MASTER` holds active registrations, `DEREG` holds deregistered ones |
| Iowa Environmental Mesonet (IEM) | Historical METAR and TAF | Used for backfill, because aviationweather.gov cannot reach back far enough |
| aviationweather.gov | Current METAR and TAF | Documented as previous 30 days only, 100 requests/min, 400 entries per response. Use from the live phase onward |
| OurAirports | Airport reference, IATA/ICAO codes, coordinates | No timezone column. Derive timezone from coordinates |
| OpenSky Network (later) | Callsigns, ICAO hex, positions | OAuth2 client credentials, tokens last 30 minutes. Daily credit quota per endpoint group. REST state vectors reach back 1 hour. The flights endpoints reach back to at least July 2024, and each query costs 30 credits |

Credentials come from environment variables. Never commit them, and keep `.env` gitignored.

## Data layers

Postgres schemas, in order of flow:

1. `raw`: source rows as delivered, all text, plus `source_file`, `source_sha256` and `loaded_at`. Never edited.
2. `staging`: typed and normalized, with times converted to UTC.
3. `ontology`: resolved entities that the app reads.
4. `dq`: check results per ingestion run, plus quarantined rows with a reason.

Downloaded files go in `data/raw/<source>/` and are gitignored. Reruns must be idempotent: loading the same file twice changes nothing.

## Ontology

- **Airport:** keyed internally, with IATA, ICAO and BTS airport IDs as attributes.
- **Carrier:** the operating carrier. The table holds IATA and DOT IDs for now. ICAO code and marketing brand are intended but need a source that BTS doesn't provide.
- **Aircraft:** a physical airframe, with tail number, ICAO hex and type.
- **Flight:** one operated leg, with scheduled and actual times in UTC.
- **WeatherObservation:** one METAR at one airport. TAFs are stored separately because they are forecasts, not observations.
- **Delay:** minutes attributed to a flight, one row per cause.

## Entity resolution

Identifiers are time-bounded and not interchangeable. Follow these rules:

- **Tail to hex:** a tail number can be re-registered and a hex can move, so mappings carry `valid_from` and `valid_to`. Resolve against the flight date, not today's registry.
- **Tail format:** BTS tails usually include the `N`, but 123 Allegiant tails do not (`320NV`), and FAA `N-NUMBER` omits it. Normalize all of them to the full form with the `N`, and keep the delivered value.
- **Hex format:** uppercase in storage. OpenSky returns lowercase.
- **Callsign to flight:** a callsign identifies a flight on a date, not an aircraft. It may not match the marketed number, because regional flights sold as DL fly under the operator's prefix (Endeavor uses `EDV`).
- **Airports:** BTS uses IATA codes, weather and OpenSky use ICAO. Join through the airport table and never build one by prefixing `K`, which fails outside the contiguous US. OurAirports holds current codes only, so a BTS code that has since changed needs a row in `staging.airport_code_alias`.
- **Unresolved matches:** record them with a reason. Never guess, and never drop them silently. Each resolved link stores its method and confidence.

## Aircraft rotations

A rotation is one tail's flights ordered by actual time. Consecutive legs should connect: the next origin equals the previous destination.

- **Scope trap:** ATL-only data contains only legs touching ATL, so a rotation looks broken whenever the aircraft flies elsewhere. Rebuild rotations from the national file, then filter to aircraft that touched ATL.
- **Known gaps:** international legs and non-reporting flying are absent from BTS. A station mismatch is a labelled gap, not an error.
- **Cancelled and diverted flights:** cancelled flights never join a rotation. Diverted flights need their actual landing station.

## BTS traps

- Times are local `hhmm` strings and `2400` occurs. `FlightDate` is the scheduled local departure date.
- Arrivals can cross midnight and timezones, so derive the UTC arrival date from the scheduled block rather than assuming `FlightDate`.
- Delay cause columns are filled only when the arrival delay is 15 minutes or more. Blank means not reported, not zero.
- `hhmm` is authoritative. Block time only picks the date, because scheduled block disagrees with `crsarrtime` on 316 flights in July 2024.
- METAR times are UTC, so all weather joins happen after conversion.

## Conventions

- Every non-trivial transform gets a test using a small fixture in `pipelines/tests/fixtures/`, including the awkward cases above.
- Data-quality checks are code that runs on every load. A failed blocking check stops promotion to `ontology`.
- Schema changes go through SQL migrations in `db/migrations/`. Laravel migrations cover `app` only.
- Respect source rate limits and terms. If a source refuses scripted downloads, download the file by hand into `data/raw/` rather than disguising the client.
- Add PostGIS, orchestration and streaming only when a feature needs them.

## Docs

- `docs/data-sources.md`: field notes on each source.
- `docs/roadmap.md`: all phases, kept loose until each one starts.
- `docs/phase-1-plan.md`: current phase plan.
- `docs/phase-1-report.md`: generated data-quality report for July 2024. Change it through `pipelines/flightops/report.py`.
- `docs/plans/`: task-level implementation plans.
- `DECISIONS.md`: running log of tradeoffs. When work involves a real tradeoff, add an entry in the same change, using the existing format: what was chosen, what it gave up, and what would change the decision.
