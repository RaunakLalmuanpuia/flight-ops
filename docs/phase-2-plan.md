# Phase 2: ATL ops console

**Goal:** a read-only app that answers "What happened at ATL on a given day, and to a given aircraft?" Pick a day, see the hub's timeline against its weather, then drill down to one tail's legs with their gaps labelled.

Reasoning behind these choices is in `DECISIONS.md`. Out of scope: a data-quality page, other hubs, live data, month-wide tail views and delay propagation (phase 3).

## Folder structure

```
flight-ops/
├── db/migrations/011_app_read.sql   # views, is_adverse(), flightops_app role grants
├── pipelines/tests/                 # view tests with fixtures
└── web/                             # Laravel + Inertia + Vue + Tailwind
    ├── app/Http/Controllers/        # HubDayController, TailDayController
    ├── resources/js/pages/          # HubDay.vue, TailDay.vue
    ├── resources/js/components/     # DayTimeline, CaveatPanel, FlightTable, TailLegs
    ├── resources/js/lib/            # pure helpers with node --test checks
    └── tests/Feature/               # Pest
```

## Definitions

- **ATL day:** the ATL local date (`America/New_York`) of a flight's scheduled ATL event. That's the departure for flights leaving ATL and the arrival for flights landing there, so cancelled flights have a day too. On the tail page, a leg belongs to the ATL local date of its scheduled departure, wherever it departs from.
- **Adverse weather:** thunderstorm, heavy rain, fog, snow or freezing precipitation, ceiling under 1,000 ft, visibility under 3 SM, or gust of 30 kt or more. It is defined once, in `app_read.is_adverse`, and used by both the app and `report.py`.
- **Stale METAR:** more than 90 minutes old at the flight's ATL event. METARs come roughly hourly, so one hour old is normal.
- **Time display:** ATL local time on the hub page, each station's local time on the tail page, and UTC on hover in both places. Views return UTC, and Vue formats it with `Intl.DateTimeFormat`.

## Data layer: `app_read`

This schema holds views and one function, and no data. Pipelines own it through SQL migrations. The app connects as `flightops_app`, which has `SELECT` on `app_read` only.

| Object | One row per | Contents |
|---|---|---|
| `is_adverse(weather_observation)` | — | The adverse rule above |
| `atl_flight` | flight touching ATL | `atl_day`, `direction` (`dep` or `arr`), and the flight's columns |
| `hub_day_hourly` | day × local hour × direction | Scheduled, operated, cancelled and delayed-15+ counts, and delay minutes by cause |
| `hub_day_weather` | ATL METAR | `atl_day`, local hour, `adverse`, wind, gust, visibility, ceiling, weather and raw text |
| `hub_day_flights` | flight touching ATL | Times, carrier, other station, tail, status, delays, and the caveat flags `metar_stale`, `block_mismatch`, `aircraft_unresolved` and `aircraft_medium_confidence` |
| `hub_day_caveats` | day | Counts of each caveat flag, plus rotation breaks touching the day |
| `tail_legs` | leg of a tail that touched ATL, plus its cancelled flights | `leg_seq` (null when cancelled), the ATL local day of scheduled departure, gap minutes, a readable label for `break_cause`, delays and the ATL METAR |

Day boundaries, the adverse rule and break labels live only in SQL. PHP filters by `atl_day`, `tail_number` and `leg_seq`, and nothing more.

## App

There is no auth in phase 2. Sessions use the file driver, and the `app` schema stays empty until phase 5.

| Route | Page | Behaviour |
|---|---|---|
| `/` | — | Redirects to `/day/2024-07-19` |
| `/day/{date}` | `HubDay` | 404 naming the loaded range if the date is outside it |
| `/tail/{tail}/{date}` | `TailDay` | Tail normalized to the `N` form. 404 if the tail is unknown |

**HubDay**
- A date input limited to the loaded range, with previous and next day buttons.
- **`DayTimeline`:** an SVG with 24 local-hour columns. Departures stack above the axis and arrivals below, split into on time, delayed 15+ and cancelled. A METAR strip shares the axis, shades adverse hours and shows details on hover. Clicking an hour filters the table.
- **`CaveatPanel`:** lists caveat counts that are non-zero. Clicking one filters the table.
- **`FlightTable`:** filters on the client by direction, carrier, status, hour and caveat, with no paging. Caveats show as labels on each row, and each tail links to its page.

**TailDay**
- A header with the tail, aircraft type and link confidence, or the reason the tail is unresolved.
- **`TailLegs`:** shows the day's legs plus the last leg before and the first leg after. Each one has scheduled and actual bars on a shared axis, delay causes and the ATL METAR where relevant. Cancelled legs are greyed out as unflown and sorted by scheduled time. Gaps appear as labelled rows between legs.
- Previous and next day arrows.

Charts are hand-written SVG. There is no chart or date library.

## Steps

1. **Views:** write `011_app_read.sql` with the role and grants, and pytest fixtures covering an inbound flight that crosses ATL midnight, a cancelled flight, a diversion, a stale METAR and each break cause.
2. **Report reuse:** `report.py` uses `is_adverse`, and the regenerated report must be identical to the current one.
3. **App skeleton:** create `web/` from the Vue starter kit, remove auth, connect as `flightops_app`, add the routes and 404s, and write Pest tests.
4. **HubDay:** build the timeline, caveat panel and flight table.
5. **TailDay:** build the legs view with gaps and neighbouring legs.
6. **Verification and docs:** a browser walkthrough with screenshots, DECISIONS entries and a CLAUDE.md Status update.

## Done means

- pytest, Pest and `node --test` all pass.
- `migrate` on a fresh database produces the same views.
- `/day/2024-07-19` shows cancellations that match a direct SQL count using the ATL day definition. The report's 895 counts by `FlightDate`, so any difference is explained in the plan's notes.
- The browser walkthrough shows the outage spike against a mostly clear METAR strip, and one click reaches a broken rotation with its labelled gap.
- An insert attempted as `flightops_app` fails.
