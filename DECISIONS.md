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
- **Measured, July 2024:** 623,272 of 630,955 flights with a tail link to an airframe (98.8%). 587,617 are high confidence and 35,655 medium. 597,959 match an active registration, 25,313 a deregistered one only, and 7,683 stay unresolved with a reason. On ATL flights, 317 of 59,992 stay unresolved (0.5%).
- **Revisit if:** aircraft-type analysis leans on the 34,653 flights linked only because the registry names one airframe for the tail, or on the unresolved flights. Then look for archived registry snapshots.

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
- **Gave up:** a one-command setup on another machine. The Postgres version comes from this Mac (18.1) instead of being pinned in the repo, so setup differences can go unnoticed until phase 8.
- **Why:** no Docker runtime is installed, and nothing before phase 8 needs one.
- **Revisit if:** someone else needs to run the project sooner, or a local dependency becomes hard to install.

## 2026-11-01: Key raw reloads on file hash, and append changed files
- **Chose:** a file already recorded in `dq.ingestion_run` by hash is skipped. A changed file with the same name, such as a newer FAA snapshot, is appended as a new delivery. Each file loads in one transaction.
- **Gave up:** raw tables with one current version of each row, so staging must pick a delivery by `source_sha256`. Failed loads roll back and leave no run record, only the error.
- **Revisit if:** repeated snapshots make raw too large, or failed attempts need to be reported in `dq`.

## 2026-11-01: Quarantine a few malformed raw rows instead of failing the file
- **Chose:** a row with the wrong field count goes to `dq.quarantined_row` with its line number and fields, unrepaired. More than 10 in one file fails that file. `DEREG.txt` has one such row.
- **Gave up:** a guarantee that raw holds every delivered row, so reconciling means raw rows plus quarantined rows. The limit of 10 is a judgment call, not a measured value.
- **Why:** repairing would mean guessing at source data, and failing would block the file over one deregistered Bahamas aircraft.
- **Revisit if:** a quarantined row turns out to matter to a flight, or a later file exceeds the limit.

## 2026-11-01: Treat BTS hhmm as authoritative, and use block time only for the date
- **Chose:** each UTC time comes from its delivered local `hhmm`, on the date closest to what block time or delay implies. Disagreements set `block_mismatch`.
- **Gave up:** a single simple formula, so a flight's elapsed time can differ from the difference between its times, which it does on 7 flights.
- **Why:** deriving arrivals purely from block time contradicted BTS's own scheduled arrival on 316 flights and produced an arrival before departure.
- **Revisit if:** a mismatch pattern points to a wrong timezone instead of a schedule error.

## 2026-11-01: Handle changed airport codes with an explicit alias table
- **Chose:** `staging.airport_code_alias`, with one row so far: `PBI` to `KPBI`. Airports keep both the BTS code and the current code.
- **Gave up:** a generic history of airport codes, so the next renamed airport fails the timezone check until someone adds a row.
- **Why:** that failure is loud and the fix is one recorded line. OurAirports has no code history to build from.
- **Revisit if:** adding months or hubs needs more than a handful of aliases.

## 2026-11-01: Resolve tails by airframe, in a fixed order of rules
- **Chose:** a dated window first, then a window with blank dates open, then a tail that has only ever had one airframe. Anything else stays unresolved with a reason. Each link stores its method and confidence.
- **Gave up:** a complete match. 1.2% of flights with a tail stay without an aircraft, and medium-confidence links rest on the registry never naming a second airframe for that tail.
- **Why:** a strict window strands 292 tails, on 34,653 flights, whose windows miss the flight date even though the registry names only one airframe for them, usually because the certificate was reissued after July 2024.
- **Revisit if:** archived registry snapshots turn up, or phase 3 needs aircraft type on the unresolved flights.

## 2026-11-01: Join weather to both scheduled and actual ATL times
- **Chose:** one row per flight, event and basis, each linking to the latest METAR at or before that time, with its age in minutes.
- **Gave up:** a single weather row per flight, so readers must pick a basis.
- **Why:** a cancelled flight has no actual time but still needs its weather, and a delayed flight met different weather from what its schedule implied.
- **Revisit if:** phase 2 only ever reads one basis.

## 2026-11-01: Hold off on thresholds for reported checks
- **Chose:** reported checks record values with no pass or fail, for now.
- **Gave up:** an automatic warning when, say, the tail match rate drops, so a person has to read the report.
- **Why:** the phase plan meant to set them after the first run, but one month containing a major outage can't show what normal looks like.
- **Revisit if:** a second month is loaded. Set thresholds from the two months together.

## 2026-11-01: Generate the report's tables and write its findings by hand
- **Chose:** `docs/phase-1-report.md` comes from `python -m flightops report`, with the SQL under each table. The findings and limits are fixed prose in `report.py`.
- **Gave up:** a report that fully rewrites itself, so the prose can fall out of step when data changes.
- **Why:** tables that can't drift make the report defensible line by line, and interpreting them is a human job. Generating the sentences as well would be more code and read worse.
- **Revisit if:** the project reports on more than a few months.

## 2026-11-01: Define adverse weather for the cross-check only
- **Chose:** thunderstorm, heavy rain, fog, snow or freezing precipitation, ceiling under 1,000 ft, visibility under 3 SM, or gust of 30 kt or more, defined in the report.
- **Gave up:** a standard category such as FAA IFR, so the definition is open to challenge.
- **Why:** the cross-check needs a yes or no on weather that could delay flights, and that wording is easy to read and to dispute line by line.
- **Revisit if:** phase 2 or 3 needs weather as a feature. Then define it in `ontology`, and test it against delays.

## 2026-11-01: Collect OpenSky days as files, and only once they have settled
- **Chose:** one CSV per airport, direction and UTC day, written before loading through the existing raw loader. Only days at least 2 days old are collected, and a saved day is never fetched again.
- **Gave up:** data from yesterday, and any corrections OpenSky makes after a day has been saved.
- **Why:** reusing the loader keeps hashing and idempotence in one place, files survive a stopped database, and a saved partial day would otherwise never be repaired.
- **Revisit if:** phase 4 needs fresher data, or a re-fetch shows settled days still change.

## 2026-11-01: Run OpenSky collection by hand, not on a schedule
- **Chose:** the user runs `python -m flightops collect` when needed. A `launchd` agent was built, tested and then removed.
- **Gave up:** data arriving without anyone acting. A gap over 7 days needs `--from` and `--to`, and costs 60 credits per day collected.
- **Why:** the user doesn't want a background job on this Mac, and flight history reaches back at least to July 2024, so waiting loses nothing today.
- **Revisit if:** OpenSky shortens its history, or a later phase needs fresh data every day.

## 2026-11-22: Define adverse weather once, in `ontology`
- **Chose:** `ontology.is_adverse(weather_observation)`, used by the report and by the app's views. It never returns NULL: missing fields count as not adverse.
- **Gave up:** a definition that sits beside the report's prose. A reader of the report now follows the function name to the migration.
- **Why:** phase 2 shades adverse hours on the timeline. Two copies of the rule would drift, and the earlier entry said to move it into `ontology` once a second reader needed it.
- **Revisit if:** phase 3 tests weather as a delay predictor. Then check the rule against delays instead of keeping it by judgment.

## 2026-11-22: Serve the app from SQL views in `app_read`
- **Chose:** views and small functions in an `app_read` schema, owned by pipelines' migrations and tested with pytest. Laravel runs plain queries against them.
- **Gave up:** Eloquent models and Laravel-only tests, so each app feature spans SQL and PHP, and a view change needs a migration.
- **Why:** the ATL day, adverse weather and break labels are data rules. Keeping them beside the pipelines means one definition, tested against the same fixtures as the data.
- **Revisit if:** a page needs per-request logic that SQL expresses badly, or a view grows slow enough to need materializing.

## 2026-11-22: Assign each ATL flight to the ATL local day of its scheduled ATL event
- **Chose:** departures by scheduled departure and arrivals by scheduled arrival, both in Atlanta local time. Cancelled flights keep their day. The app offers the BTS `flight_date` range, July 1-31.
- **Gave up:** agreement with BTS `FlightDate`. July 19 shows 899 cancellations, not the report's 895, and July 1 is missing inbound flights that departed June 30.
- **Why:** a hub controller's day runs midnight to midnight local time, and an LAX red-eye landing at 06:30 belongs to the morning it lands.
- **Revisit if:** a second month is loaded. Then the edge days fill in and the range can follow ATL days.

## 2026-11-22: Flag a METAR older than 90 minutes as stale
- **Chose:** a flight whose ATL METAR is more than 90 minutes old at its ATL event, or which has none, gets a stale-weather caveat. The METAR is the one at the actual event when there was one, otherwise the scheduled one.
- **Gave up:** a threshold drawn from data, so the number is open to challenge.
- **Why:** METARs come about hourly, so one hour old is normal. Past 90 minutes a routine report has been missed, and the weather shown may not be what the flight met.
- **Revisit if:** the caveat fires on most flights on a normal day, which would mean the observation feed has gaps worth fixing instead.

## 2026-11-22: Enforce the app's read-only access with a database role
- **Chose:** a `flightops_app` login with `SELECT` on `app_read` only. The views read `ontology` and `dq` with their owner's rights.
- **Gave up:** connecting the app as the owner, which is simpler. The app also can't query `ontology` directly, even for a quick look.
- **Why:** "the app never writes" becomes a guarantee the database checks, not a convention, and the app can only see what `app_read` chooses to show.
- **Revisit if:** phase 5 adds write-backs. Grant that role rights on `app` only.

## 2026-11-22: Leave flights diverted into ATL out of the hub day
- **Chose:** the hub views include a flight only when ATL is its scheduled origin or destination. A flight bound elsewhere that diverts and stays at ATL still appears on its tail's page.
- **Gave up:** a complete count of aircraft that ended the day at ATL.
- **Why:** such a flight has no scheduled ATL event to assign it an ATL day, and July 2024 has none: 113 diversions nationally ended away from their destination, none at ATL.
- **Revisit if:** a loaded month has diversions stranded at ATL, or phase 3 needs every aircraft on the ground at the hub.

## 2026-11-22: Build the app on the plain Laravel skeleton, in JavaScript
- **Chose:** `composer create-project laravel/laravel`, adding Inertia, Vue and Pest by hand. Pages are Vue single-file components in plain JavaScript.
- **Gave up:** the official Vue starter kit's components and TypeScript checks.
- **Why:** the kit's value is auth and settings pages, which phase 2 would delete, and the `laravel` installer on this Mac is Herd Lite's old one. Plain JS keeps two pages and a few helpers free of a type build.
- **Revisit if:** phase 5 adds users, which is when the kit's auth earns its place, or the front end grows past a handful of components.

## 2026-11-22: No login in phase 2
- **Chose:** no authentication. The app runs locally and reads through a role that cannot write.
- **Gave up:** any access control, so the app must not be exposed beyond this machine.
- **Why:** there is nothing to protect that the database role doesn't already, and auth would be the largest part of a two-page app.
- **Revisit if:** phase 5 records operator decisions, or the app is deployed anywhere.

## 2026-11-22: Test the app against the loaded July database
- **Chose:** Pest feature tests run as `flightops_app` against the local `flightops` database and assert measured July 2024 values, such as 2,078 flights and 899 cancellations on July 19.
- **Gave up:** hermetic tests. They need the database loaded and migrated, and they break if the data is rebuilt differently.
- **Why:** the role cannot write, so the tests cannot seed fixtures without owner rights. The view logic already has fixture tests in pytest, so these tests check the wiring and the real numbers.
- **Revisit if:** phase 8 containerizes the stack. Then seed a known database for the app tests.

## 2026-11-22: Order a tail's legs by scheduled departure
- **Chose:** `tail_legs.leg_order` sorts every leg, flown or cancelled, by scheduled departure.
- **Gave up:** actual-time order for flown legs, which differs when an aircraft's legs swap or a delay pushes one leg past the next one's schedule. Measured on July 2024, counting the cancelled legs the page shows between rows: 9,534 flown legs sit under a different row than the leg they followed, and 712 of 4,340 gap rows sit beside a different leg than the one they compare against (643 directly under a cancelled leg). Leaving cancelled legs out, the figures are 3,443 of 377,530 and 77 of 4,340. `connects` and the break label still come from the actual-time rotation.
- **Why:** a cancelled leg has no actual time. Mixing its scheduled time with other legs' actual times put N102DN's cancelled ATL→CLE before the late DEN→ATL that should have fed it, so the aircraft appeared to leave Atlanta before arriving.
- **Revisit if:** phase 3's delay propagation needs the flown order. `leg_seq` still holds it.

## 2026-11-22: Link hub rows to the tail page's day for that leg
- **Chose:** each hub row links to the tail page for its leg's ATL date of scheduled departure (`tail_day`), not the hub day.
- **Gave up:** staying on the same date when drilling down. An overnight inbound flight on the July 20 hub opens its tail on July 19.
- **Why:** the hub files flights by their ATL event and the tail page by departure. Linking by hub day opened 438 July pages with the clicked flight outside the day, and 12 that showed no legs at all.
- **Revisit if:** the walkthrough shows the date change confuses more than the mismatch did. Then widen the tail page's day to include arrivals at ATL.

## 2026-11-22: Measure minimum turn per carrier from July
- **Chose:** `ontology.min_turn`, holding p10, p25 and p50 of observed turns where the next leg reported `late_aircraft` minutes, per carrier and for all carriers. A carrier with under 200 samples uses the all-carrier row.
- **Gave up:** turn times by airport or aircraft type, and a figure measured outside the month being backtested. The outage days are among the samples.
- **Why:** turns differ by about 20 min between carriers at p10 (OH 28, DL 50), so one constant would be wrong for most of them. Finer cells get few samples, and 1.2% of flights have no aircraft type.
- **Revisit if:** a second month is loaded. Then measure on one month and backtest on the other.

## 2026-11-22: Propagate along the flown chain, and show cancelled legs without predicting them
- **Chose:** `app_read.propagate` follows `rotation_leg.prev_flight_id`. Cancelled legs on the same tail scheduled inside a gap are returned as their own rows, with no prediction.
- **Gave up:** a model of what the delay did to the schedule. For N102DN on July 19, the 316-min DEN→ATL is predicted as absorbed by the 02:50Z ATL→BWI, while the three legs scheduled in between were cancelled.
- **Why:** flown legs have actual times to score against, and BTS gives no signal for predicting cancellations outside the outage. Showing the cancelled legs keeps what the model misses in plain view.
- **Revisit if:** the backtest shows cancellations in the gap after most large delays. Then a cancellation model is worth its own phase.

## 2026-11-22: Score the backtest from the flown chain, built inside the pipeline
- **Chose:** `ontology.propagation_backtest`, filled by `pipeline.build` after `min_turn`. Pairs come from `rotation_leg` at depths 1-3, so a leg after an absorbed stop scores as predicted 0. Pairs at or past a break or the 24h limit are excluded. It lives in `ontology`, not `app_read` as first planned, because the app doesn't read it and `app_read`'s default grants would expose it.
- **Gave up:** 111 s on every build (353k `propagate` calls), and a backtest that can be rerun without a full build.
- **Why:** scoring only the rows `propagate` returns would drop every leg it called absorbed, which are its false negatives. A view would rerun all those calls on every read, and a separate command could go stale against `min_turn`.
- **Revisit if:** builds get run often enough that 2 minutes matters. Then move it to its own command, and have the report check it is newer than `min_turn`.

## 2026-11-22: Use p10 min turn for propagation
- **Chose:** p10 as `app_read.propagate`'s default percentile (migration 019). Depth-1 `late_aircraft` error on July outside the outage was 13.0 min, against 14.7 at p25 and 20.4 at p50.
- **Gave up:** a more cautious turn. p10 flags fewer legs at risk: depth-1 recall falls from 95.0% at p25 to 89.0%, while precision rises from 88.5% to 90.1%.
- **Why:** the backtest scores the error in minutes, which is what the page shows. p10 is the edge of the grid and still overpredicts depth 1 by 5 min on average, so the best turn may be shorter.
- **Revisit if:** a second month is loaded. Then choose on one month and score on the other, and try percentiles below p10.

## 2026-11-22: Start a diverted flight's chain from its landing, with no what-if
- **Chose:** the FlightImpact page propagates a diverted flight from its actual landing time, says that BTS gives no arrival delay for a diversion, and shows no delay form. A `?delay=` on a diverted flight fails validation.
- **Gave up:** what-if delays for diversions. All 1,414 diverted legs on ATL tails have no arrival delay, and 1,378 have a next leg.
- **Why:** propagate's override measures from the scheduled arrival at the scheduled destination, which is the wrong airport when the aircraft landed elsewhere. A form that silently did that would show a confident, wrong chain.
- **Revisit if:** propagate gains an override measured from the actual landing, or diversions become a case operators ask about.

## 2026-11-22: Keep live data in its own tables
- **Chose:** live METARs, TAFs and positions go into `ontology.live_*`, rebuilt from the latest raw rows on each poll, beside the July tables rather than in them.
- **Gave up:** one weather table for the app and report to read, so a query that wants both live and historical METARs has to union them.
- **Why:** `build_weather` truncates and rebuilds weather from IEM, which would wipe live rows, and live rows would otherwise change the report's counts.
- **Revisit if:** live collection runs long enough to become history worth reporting on, at which point live METARs should flow through staging like IEM.

## 2026-11-22: Map callsigns to operators with a hand-made prefix table
- **Chose:** `staging.callsign_prefix`, a short seed of ICAO prefixes (`DAL`, `EDV`, `SKW` and others seen at ATL), each with its source. Unmatched prefixes are kept and labelled.
- **Gave up:** completeness. Rare operators show as `unknown prefix`.
- **Why:** BTS gives no ICAO codes, and the prefixes that matter at ATL are few and stable.
- **Revisit if:** the unknown share in a real run is large, or a licensed source of ICAO designators becomes available.

## 2026-11-22: Run the live loop by hand, with no live schedule
- **Chose:** `python -m flightops live` polls every 60 s while left running in a terminal. The page shows positions and weather only, with no flight numbers or delays.
- **Gave up:** a page that is live without anyone acting, and any link from a live aircraft to a scheduled flight.
- **Why:** the user doesn't want a background job on this Mac, pipelines stay the only writers, and BTS has no schedule for today. A full day costs 1,440 of the 4,000 daily state-vector credits.
- **Revisit if:** a schedule source is added, or the app is containerized in phase 8 and a scheduler comes for free.

## 2026-11-23: Write decisions through one SQL function
- **Chose:** `app_read.record_decision`, a `SECURITY DEFINER` function that runs `propagate` and stores the decision with a frozen copy of the chain. `flightops_app` gets `EXECUTE` on it and nothing on `app`.
- **Gave up:** Eloquent models and plain inserts from Laravel, so the write path is plpgsql, tested with pytest rather than Pest.
- **Why:** the app's role still can't write anywhere directly, so read-only stays a database guarantee with one audited door, and the snapshot is exactly what `propagate` returned rather than what PHP copied.
- **Revisit if:** the app needs writes that aren't decisions, such as user accounts. Those belong in Laravel-owned tables.

## 2026-11-23: Create the `app` decision tables in a pipelines migration
- **Chose:** `app.decision` and `app.decision_leg` in `db/migrations/022`, beside the views that read them.
- **Gave up:** the convention that Laravel migrations cover `app`. Laravel still owns any future `app` tables of its own.
- **Why:** `app_read.decision_review` joins the log to `ontology`, and one migration order avoids a view that depends on tables from a second migration system.
- **Revisit if:** Laravel adds tables to `app` that pipelines' views need to read.

## 2026-11-23: Keep the decision log append-only, with no foreign key to `ontology`
- **Chose:** no `UPDATE` or `DELETE` for the app, and a correction is a new decision. Frozen legs keep carrier, flight number, origin and scheduled departure, and the review re-matches on those. A decision whose flight is gone is labelled `flight not found after rebuild`.
- **Gave up:** referential integrity, and fixing a typo in place.
- **Why:** `build` truncates `ontology.flight` with `RESTART IDENTITY`. A foreign key would block that or cascade into the log, and stored ids would point at different flights afterwards. The natural key is unique across all 634,613 July flights.
- **Revisit if:** a second month makes the natural key collide, or operators need to amend decisions, which would call for an amendment table rather than edits.

## 2026-11-23: Type the author on each decision, with no login
- **Chose:** a required name field on the decision form, remembered in the browser's `localStorage`. No accounts.
- **Gave up:** knowing who wrote a record. Anyone at the keyboard can type any name, and the app must stay on this machine.
- **Why:** login would be the largest part of the phase, and the review's value is the frozen prediction beside the outcome, not proof of identity.
- **Revisit if:** the app is deployed anywhere or more than one person logs decisions. Then add Laravel's auth, with users in `app`.

## 2026-11-23: Load August 2024 before modelling cancellations
- **Chose:** August 2024 beside July, with `min_turn` and every later choice fitted on July and scored on August, named by `ontology.period`.
- **Gave up:** a quicker cancellation phase scored on July's outage alone, and stable whole-database figures: the build now takes 1,100 s, and reports covering all loaded data moved.
- **Why:** July contains the outage, so any score drawn from July alone is in-sample. August gives a holdout for normal days, and possibly a second disruption.
- **Revisit if:** a third month is loaded. Then `ontology.period`'s hard-coded dates become a table.

## 2026-11-23: Count a tail as touching ATL across all loaded months
- **Chose:** `rotation_leg.touched_atl` stays a property of the tail over all loaded data, so a tail that touched ATL only in August counts in July too.
- **Gave up:** July figures that stay fixed when a month is added. July's ATL-tail legs went from 377,530 to 440,734.
- **Why:** a month boundary shouldn't cut a rotation, and a per-month flag would break the July 31 to August 1 chain the national load exists to keep.
- **Revisit if:** a report needs per-month ATL-tail counts. Then filter by `ontology.period` in that report, not in the flag.
