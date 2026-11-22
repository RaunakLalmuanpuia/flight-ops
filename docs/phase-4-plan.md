# Phase 4: live data

**Goal:** answer "What is happening now?" at ATL: current weather, and the aircraft in the air or on the ground around the airport right now, each resolved to a tail, type and operator.

Reasoning behind these choices is in `DECISIONS.md`. Out of scope: a live schedule (BTS is published months late, so none exists), callsign to flight matching, live delays and propagation, arrival or departure inference, a map, PostGIS and a scheduler. The case study recommended a cancellation-risk phase before this one. The user chose live data first.

## Folder structure

```
flight-ops/
├── db/migrations/020_live.sql              # raw live tables, staging.v_faa_current, staging.callsign_prefix, ontology.live_*
├── db/migrations/021_live_read.sql         # app_read.live_* (step 3)
├── pipelines/flightops/sources/live.py     # fetch states and METAR/TAF, write files
├── pipelines/flightops/live.py             # the loop
├── pipelines/flightops/transform/live.py   # rebuild ontology.live_* from the latest raw rows
├── pipelines/tests/fixtures/live/          # OpenSky states and aviationweather responses
└── web/
    ├── app/Http/Controllers/               # LiveController
    ├── resources/js/pages/                 # Live.vue
    └── tests/Feature/                      # Pest, with and without live rows
```

## Sources, as checked on 2026-11-22

- **OpenSky `/states/all`:** bounding box `lamin`, `lamax`, `lomin`, `lomax`. A box of 25 sq° or less costs 1 credit. Standard users get 4,000 credits a day **per endpoint group**, so states don't share a budget with `collect`'s flights queries. Exhausted credits return 429 with `X-Rate-Limit-Retry-After-Seconds`. Each state is an array: 0 `icao24` (lowercase hex), 1 `callsign` (padded to 8, may be null), 3 `time_position`, 4 `last_contact`, 5 `longitude`, 6 `latitude`, 7 `baro_altitude` (m), 8 `on_ground`, 9 `velocity` (m/s), 10 `true_track`, 11 `vertical_rate` (m/s), 13 `geo_altitude`, 14 `squawk`, 16 `position_source`. Same OAuth2 token as `collect`.
- **aviationweather.gov:** `GET /api/data/metar?ids=KATL&format=json&hours=2` returns objects with `rawOb`, `reportTime` and `metarType` (`METAR` or `SPECI`). `GET /api/data/taf?ids=KATL&format=raw` returns the current TAF text. No credentials.

## Collection

- `python -m flightops live [--every 60]` runs until Ctrl-C. It is started by hand, like `collect`.
- Each tick fetches states for ATL ± 1.5° in latitude and longitude (9 sq°, 1 credit). At 60 s that is 1,440 credits a day if left running.
- Every 5th tick it also fetches the METAR (last 2 hours) and TAF.
- Each response is written as a file under `data/raw/opensky_states/` or `data/raw/awc/`, named by fetch time, then loaded with `raw.load_file`. That keeps hashing and idempotence in one place, and the raw layer is a replayable recording.
- After loading, the tick rebuilds `ontology.live_*` in one transaction.
- **Errors:** a failed fetch or 429 is logged and the loop continues, waiting out `Retry-After` when given. A 401 fetches a new token. The loop never exits on a source error, only on a database error.

## Data layer

| Object | One row per | Contents |
|---|---|---|
| `raw.opensky_state`, `raw.awc_metar`, `raw.awc_taf` | delivered row | all text, plus `source_file`, `source_sha256`, `loaded_at`, and the fetch time |
| `staging.v_faa_current` | current MASTER registration | tail with `N`, hex uppercase, `mfr_mdl_code`, manufacturer and model from ACFTREF |
| `staging.callsign_prefix` | ICAO callsign prefix | prefix (`DAL`, `EDV`, `SKW`, ...), operator name, the BTS carrier code where one exists, and the source of the row |
| `ontology.live_position` | aircraft in the latest snapshot | hex, callsign, position and its age, altitude, vertical rate, on ground, distance (nm) and bearing from ATL, tail, type, operator, `resolve_method`, `resolve_confidence`, `unresolved_reason`, `operator_reason`. No `aircraft_id`: the July rebuild restarts identities, so `app_read` joins it by hex |
| `ontology.live_weather` | METAR at KATL | the columns of `weather_observation`, parsed with the existing `parse_metar` |
| `ontology.live_taf` | latest TAF at KATL | issue time and raw text |
| `app_read.live_aircraft`, `app_read.live_weather` | as above | what the page reads, including `snapshot_at`, the adverse flag via `is_adverse`, and the 90-minute stale flag |

**Resolution**, following the CLAUDE.md rules:

- **Hex:** uppercase, then match against `staging.v_faa_current`. That is today's registry, which is correct for a live flight. `staging.faa_record` can't be used, because it holds only July BTS tails.
- **Unresolved, with a reason:** `hex not in FAA registry` (foreign or military) and `ambiguous hex`. A row with no position is kept with a NULL distance if the snapshot holds more than one registration for a hex. None are dropped.
- **Operator:** the first 3 characters of the trimmed callsign, matched against `staging.callsign_prefix`. A callsign that is a tail number (general aviation) gets an operator of none and the reason `general aviation callsign`, a blank callsign gets `no callsign`, and any other unmatched prefix gets `unknown prefix`.
- **Distance and bearing:** haversine in plain SQL, from ATL's OurAirports coordinates held as a constant in `sources/live.py` (the bounding box needs them before any database read). Phase 6 replaces it.

## App

- **Live page** at `/live`, linked from the nav.
- **Weather strip:** the latest METAR with its adverse and stale flags, and the current TAF text.
- **Aircraft table:** tail, type, operator, callsign, distance and bearing, altitude (ft), climbing, descending, level or on ground, and position age. Sorted by distance. A tail in the July ontology links to its most recent TailDay. Unresolved rows show their reason.
- **Freshness banner:** the snapshot time. If it is more than 5 minutes old, the banner reads "live loop not running, data is N min old". With no rows at all, an empty state shows the command to start the loop.
- **Caveats:** no schedule, so no delays, no flight numbers and no propagation. It uses the existing caveats pattern.
- **Controller:** one query per view, as the existing controllers do. Reads `app_read` only.

## Steps

1. Migration 020, `sources/live.py` (fetch, write, load) and fixture tests, plus one real call to each source to confirm the format.
2. `transform/live.py` and `staging.callsign_prefix`: resolution and tests for lowercase hex, a blank callsign, an unknown hex, a GA callsign, on ground, a null position and an unknown prefix. Then the loop, tested as one tick with fetches stubbed.
3. Live page, nav link, Pest tests with and without rows, and a screenshot from a real run.

## Done means

- `pytest`, `pest` and `npm test` pass.
- A real run of `live` for at least 10 minutes fills the page, and the share of resolved hexes and of known operators is written into the notes below.
- Stopping the loop makes the page say it is stale.
- `DECISIONS.md` records the separate live tables, the hand-made callsign prefix table, and the hand-run loop.

## Notes
