# Decisions

Tradeoffs made while building flight-ops, newest last. Each entry says what was chosen, what it costs, and what would change the decision.

## 2026-11-01: Use July 2024 as the first month
- **Chose:** July 2024, which includes the CrowdStrike outage. BTS shows 3,208 cancellations on flights touching ATL from July 19 to 23, 2,864 of them Delta.
- **Gave up:** a typical month, so baselines drawn from July alone are skewed by the outage.
- **Revisit if:** analysis needs a normal baseline. Load a second month rather than replacing this one.

## 2026-11-01: Load the national BTS file, not an ATL extract
- **Chose:** all 634,613 rows for the month, with the app scoped to tails that touched ATL (60,144 flights touch ATL).
- **Gave up:** about 10x more rows to store and process.
- **Why:** an ATL-only extract breaks a rotation every time an aircraft flies elsewhere.
- **Revisit if:** load times become a real problem. Then keep only flights by tails that touched ATL.

## 2026-11-01: Use IEM for historical weather
- **Chose:** Iowa Environmental Mesonet for historical METAR and TAF. aviationweather.gov stays for the live phase.
- **Gave up:** a single weather source. There are now two sources to normalize, and IEM includes 5-minute `AUTO`/`MADISHF` records that must be filtered out.
- **Why:** aviationweather.gov documents only the previous 30 days and rejected a July 2024 request.
- **Revisit if:** a better archive turns up, or IEM's coverage has gaps in the first full-month pull.

## 2026-11-01: Resolve aircraft from a current FAA snapshot plus DEREG
- **Chose:** build dated tail mappings from today's `MASTER` and `DEREG` files, and report the match rate.
- **Gave up:** true point-in-time registry history, so a tail re-registered since July 2024 could match the wrong aircraft.
- **Revisit if:** the step 4 match results show this affects aircraft-type analysis. Then look for archived registry snapshots.

## 2026-11-01: Derive airport timezones from coordinates
- **Chose:** compute timezones from OurAirports coordinates, because the source has no timezone column.
- **Gave up:** one more derived step that adds a dependency and can be wrong near boundaries.
- **Revisit if:** a blocking timezone check fails, or a maintained airport-timezone source proves simpler.

## 2026-11-01: Download by hand if a source refuses scripts
- **Chose:** never disguise the client. Files a source refuses to serve to scripts get downloaded by hand into `data/raw/`.
- **Gave up:** a fully unattended pipeline for those sources.
- **Revisit if:** the source offers a supported bulk route.

## 2026-11-01: Leave the Laravel app out of phase 1
- **Chose:** phase 1 ends at `ontology`, `dq` and a report answerable with SQL.
- **Gave up:** anything visual to demo until a later phase.
- **Why:** the app is only as credible as the data under it.
- **Revisit if:** a demo is needed before the pipeline is finished.

## 2026-11-01: Keep pipelines and the app apart at the database
- **Chose:** pipelines alone write `raw`, `staging`, `ontology` and `dq`, using SQL migrations. Laravel reads those and owns only `app`.
- **Gave up:** Laravel's migrations and write paths for the data model, so there are two migration mechanisms.
- **Revisit if:** the app needs to record operator input against ontology entities. Store that in `app` first.

## 2026-11-01: Add PostGIS, orchestration and streaming only on demand
- **Chose:** plain Postgres and a single pipeline command.
- **Gave up:** a stack that looks more impressive on first read, and some later migration work.
- **Revisit if:** a specific feature needs geospatial queries, scheduled runs or live ingestion, starting with OpenSky.

## 2026-11-01: Run locally and containerize in the final phase
- **Chose:** local Postgres, a Python virtual environment and the Laravel dev server. Docker becomes the last roadmap phase.
- **Gave up:** a one-command setup on another machine. The Postgres version comes from this Mac (18.1) instead of being pinned in the repo, so setup differences can go unnoticed until phase 7.
- **Why:** no Docker runtime is installed, and nothing before phase 7 needs one.
- **Revisit if:** someone else needs to run the project sooner, or a local dependency becomes hard to install.

## 2026-11-01: Key raw reloads on file hash, and append changed files
- **Chose:** a file already recorded in `dq.ingestion_run` by hash is skipped. A changed file with the same name, such as a newer FAA snapshot, is appended as a new delivery. Each file loads in one transaction.
- **Gave up:** raw tables with one current version of each row, so staging must pick a delivery by `source_sha256`. Failed loads roll back and leave no run record, only the error.
- **Revisit if:** repeated snapshots make raw too large, or failed attempts need to be reported in `dq`.
