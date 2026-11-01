# Phase 1: one month of ATL history

**Goal:** one command loads July 2024 from raw files into `ontology`, and produces a data-quality report you can defend line by line.

Reasoning behind these choices is in `DECISIONS.md`. The Laravel app is out of scope for this phase.

## Folder structure

```
flight-ops/
├── CLAUDE.md
├── DECISIONS.md
├── README.md
├── .env.example
├── data/raw/{bts,faa,iem,ourairports}/   # gitignored
├── db/migrations/                        # raw, staging, ontology, dq
├── pipelines/
│   ├── pyproject.toml
│   ├── flightops/
│   │   ├── sources/                      # one module per source: fetch and load raw
│   │   ├── transform/                    # staging: types, UTC
│   │   ├── resolve/                      # entity resolution
│   │   ├── rotations/
│   │   └── dq/
│   └── tests/fixtures/
├── web/                                  # Laravel app, later phase
└── docs/
    ├── data-sources.md
    └── phase-1-plan.md
```

## Steps

1. **Foundation:** set up the local Postgres database and Python environment, the schemas and an ingestion-run table, plus file hashing so reloads change nothing.
2. **Raw load:** load the BTS national file, FAA `MASTER`/`ACFTREF`/`DEREG`, OurAirports, and IEM METAR/TAF for KATL.
3. **Staging:** handle `2400` times, convert local times to UTC using timezones derived from coordinates, and parse METARs. Filter out IEM's 5-minute `AUTO`/`MADISHF` records, which appeared in the sample and aren't standard METARs.
4. **Ontology:** build Airport, Carrier, Aircraft, Flight, WeatherObservation and Delay. Link tails to FAA records as of the flight date, recording the match method and any failures.
5. **Rotations:** rebuild them nationally, then limit to tails that touched ATL. Label each break by likely cause.
6. **Weather join:** attach the latest METAR at or before each ATL departure and arrival.
7. **Report:** write the data-quality results and walk through July 19-23 as the worked example.

## Data-quality checks

**Blocking (these stop promotion to `ontology`):**

- Row counts reconcile from raw to Flight: 634,613 national and 60,144 touching ATL for this file.
- Flight keys are unique, and no reload creates duplicates.
- Every BTS airport resolves to a timezone.
- Actual times convert to UTC and arrive after departure.
- Delay causes add up to the arrival delay when they're reported.

**Reported (these don't block; thresholds wait for a second month, see `DECISIONS.md`):**

- Share of tails matched to FAA, split into active and deregistered.
- Rotation continuity rate, and breaks by cause.
- METAR gaps longer than 90 minutes.
- Missing tails. The file has 152 on ATL flights, all cancelled, so a missing tail on an operated flight is an anomaly.
- Cross-checks: the July 19-23 cancellation spike is present, and weather-attributed delays line up with observed weather.

## Report

`python -m flightops report` writes `docs/phase-1-report.md`, and `all` does too.

## Done when

- A freshly created database plus the pipeline command reproduces the same counts.
- Fixture tests cover the traps listed in `CLAUDE.md`.
- "What happened to tail X on July 19?" can be answered with SQL.

## Measured from the July 2024 BTS file

Use these to check the load:

| ATL flights | Count |
|---|---|
| Touching ATL | 60,144 |
| `reporting_airline` is DL | 41,363 |
| Distinct tails | 3,078 |
| Missing tail (all cancelled) | 152 |
| With a `2400` scheduled or actual departure or arrival time | 57 |
| Also counting wheels-off and wheels-on | 109 |
| Diverted | 278 |
| Cancelled July 19-23 | 3,208 |
| Of those, DL | 2,864 |

The file has 109 columns plus a blank one from a trailing comma, and is 34.4 MB zipped. Allow several minutes for the download.

## Closed before step 3

- **Airport codes change:** resolved by `staging.airport_code_alias`, with one row, `PBI` to `KPBI`, covering 4,112 flights. The blocking timezone check passes.
- **`DEREG` repeats tails:** resolved by choosing an airframe per tail and flight date. The rules are in `docs/plans/2026-11-01-phase-1-staging-ontology-rotations.md`, and results are in `docs/data-sources.md`.
