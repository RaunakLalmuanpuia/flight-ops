# Roadmap

Only the next phase gets detailed planning. Review and update this file before each phase starts.

| Phase | Question it answers | Demo | Main work |
|---|---|---|---|
| 1. History | Can we trust the data? | SQL and a data-quality report for July 19-23 | See `phase-1-plan.md` |
| 2. Ops console | What happened at ATL on a given day, and to a given aircraft? | Pick a day, then drill from the hub to a tail's timeline with its weather | Read-only Laravel app over `ontology` and `dq` |
| 3. Decision support | If this aircraft runs late, what breaks next? | Select a late inbound flight and see the downstream flights at risk | Delay propagation along rotations, backtested on the outage |
| 4. Live data | What is happening now? | Current ATL view with live weather and aircraft | aviationweather.gov, OpenSky, hex and callsign resolution, PostGIS if needed |
| 5. Operator workflow | What did the controller decide, and did it help? | Log a decision against a flight and review it later | Write-backs stored in `app` |
| 6. Second hub | Does this work beyond ATL? | Same app on another hub, with a list of what broke | Mostly finding hidden ATL assumptions |
| 7. Containerization | Can someone else run it from a clean checkout? | `docker compose up` reproduces the same counts and app | Compose for Postgres, pipelines and the app |

Phases 1-3 plus a written outage case study are the core portfolio piece. That piece is done: see [case-study.md](case-study.md). Phases 4-6 are optional. Phase 7 comes last, whichever of those get built.

## Ordering

- **Decision support before live data:** telling a controller what to act on is the stronger signal, and the July 2024 outage gives a real event to test against.
- **OpenSky collection starts right after phase 1:** a small job for ATL arrivals and departures, run by hand when needed. Probing showed flight history reaching back to at least July 2024, so this is cheap and worthwhile rather than urgent. Each query costs 30 of 4,000 daily credits, so each day collected costs 60.

## Known limit

BTS has no crew or passenger connection data, so phase 3 predictions cover aircraft-driven delays only.
