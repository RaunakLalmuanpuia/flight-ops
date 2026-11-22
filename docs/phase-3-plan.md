# Phase 3: decision support

**Goal:** answer "If this aircraft runs late, what breaks next?" Select a late flight, see the downstream flights on its tail that the delay puts at risk, and see how well that prediction held up against what actually happened, backtested on the July 19-23 outage.

Reasoning behind these choices is in `DECISIONS.md`. Out of scope: predicting cancellations, crew and passenger connections (BTS has neither), aircraft swaps, and a hub-wide "at risk" dashboard.

## Folder structure

```
flight-ops/
├── db/migrations/016_min_turn.sql      # ontology.min_turn table
├── db/migrations/017_propagate.sql     # app_read.propagate(), app_read.propagation_backtest
├── pipelines/flightops/build.py        # fills ontology.min_turn after rotations
├── pipelines/flightops/report.py       # also writes docs/phase-3-report.md
├── pipelines/tests/                    # fixtures for min_turn, propagate, backtest
└── web/
    ├── app/Http/Controllers/           # FlightImpactController
    ├── resources/js/pages/             # FlightImpact.vue
    └── tests/Feature/                  # Pest, against the July database
```

## Definitions

- **Flown chain:** a tail's legs in `ontology.rotation_leg`, followed by `prev_flight_id` (equivalently `leg_seq + 1`). Never `tail_legs.leg_order`, which is ordered by schedule for display.
- **Min turn:** the shortest time a carrier's aircraft can turn, measured from July. A sample is a flown pair that connects, where the next leg reported `late_aircraft` minutes above zero, on a tail that touched ATL. Its value is the next leg's actual departure minus the previous leg's actual arrival. When the aircraft was the constraint, that turn is close to the minimum. `ontology.min_turn` stores p10, p25 and p50 per carrier, plus a row for all carriers. A carrier with fewer than 200 samples uses the all-carrier row.
- **Propagated delay:** for each downstream leg, `ready = previous predicted arrival + min_turn`, `predicted_dep_delay = max(0, ready - sched_dep)`, and `predicted_arr = predicted_dep + scheduled block` (`sched_arr - sched_dep`). No time is made up in the air.
- **At risk:** a predicted departure delay of 15 min or more, the BTS on-time threshold.
- **Stop reason:** the walk ends when the delay is `absorbed` (predicted 0), at a `break` (the next leg doesn't connect), at the `limit` (scheduled departure more than 24h after the selected flight's arrival, at the delay being propagated), or at the `end` of the tail's data.
- **Cancelled in gap:** a cancelled flight on the same tail, scheduled to depart between two consecutive flown legs. It is shown, never predicted.
- **Outage window:** BTS `flight_date` July 19-23. The rest of July is the normal window.

## Data layer

| Object | One row per | Contents |
|---|---|---|
| `ontology.min_turn` | carrier, plus one all-carrier row (`carrier_id` NULL) | `samples`, `p10`, `p25`, `p50` in minutes |
| `app_read.propagate(flight_id, arr_delay_min, percentile)` | the selected flight, downstream legs, or cancelled-in-gap flights | `depth`, flight, kind (`selected`, `flown`, `cancelled`), scheduled departure, `min_turn`, `slack`, `predicted_dep_delay`, `at_risk`, the actual departure delay, the actual arrival delay (`actual_arr_delay`) and `late_aircraft` minutes, and `stop_reason` on the last row |
| `app_read.propagation_backtest` | scored pair, at depth 1-3 and each percentile | late leg, scored leg, depth, percentile, window, predicted delay, actual departure delay, `late_aircraft` minutes (NULL when not reported), and both baselines |

`propagate` takes the selected flight's arrival delay as its starting point. Leaving it NULL uses the actual value. The percentile stays a parameter, because the backtest needs it. After step 3 the function's default is set to the chosen percentile and the app relies on the default. `propagation_backtest` starts from every flown leg on an ATL-touching tail that arrived 15 min or more late, and uses only that leg's actual arrival and the downstream schedule.

## Backtest

- **Targets, scored separately:** the scored leg's `late_aircraft` minutes, where reported (reported means arrival delay of 15 min or more; blank is excluded, never zero, and a reported cause with no `ontology.delay` row is 0), and its total departure delay. The model should undercount the second, because other causes add delay.
- **Scored pairs:** build them from `rotation_leg` (depth k = `leg_seq + k`, k = 1..3) and LEFT JOIN propagate's output. A leg after an `absorbed` stop scores as predicted 0, and pairs past a `break` or `limit` are excluded. Never score only the rows propagate returns, which would drop false negatives.
- **Build once:** compute the backtest into a table built by the pipeline (or one query in the report), not a plain view that re-runs propagate per read (about 118k late legs x 3 percentiles, at 0.25-0.45 ms per call).
- **Hindsight caveat:** the flown chain uses the actual order, including swaps. Report beside the in-sample note the count of scored pairs whose next leg's `sched_dep` precedes the late leg's `sched_dep`.
- **Metrics:** mean absolute error in minutes, and precision and recall for at risk against an actual 15 min or more.
- **Baselines:** no propagation (predict 0) and full carry (predict the late leg's arrival delay).
- **Percentile choice:** pick p10, p25 or p50 by the best depth-1 `late_aircraft` error on the normal window, then report the outage window as held out. `min_turn` itself is still measured on all of July, including the outage, so this is not fully out of sample.
- **What the model misses:** for each window, the share of late legs whose tail had a cancelled leg in the gap before its next flown leg.
- **Report:** `docs/phase-3-report.md`, generated by `report.py` with its SQL under each table, and findings written by hand. It includes a worked section on N102DN's DEN→ATL on July 19 (flight 371994, 316 min late). Its next flown leg, ATL→BWI, had a 320-min gap, while three scheduled legs in that gap were cancelled.

## App

- **FlightImpact page** at `/flights/{flight_id}?delay=N`, linked from every flown leg on TailDay and from late arrivals on HubDay.
- **Header:** the flight, its actual arrival delay, and a delay input that defaults to that value. Submitting reloads the page with `?delay=`.
- **Chain table:** one row per downstream leg, with predicted and actual side by side. When `delay` differs from the actual value, the actual columns are dimmed and labelled as not comparable. Cancelled-in-gap rows are grey and read "scheduled on this tail, cancelled, not predicted". The last row gives the stop reason.
- **Diverted start:** decide in step 4 how a diverted start is shown, since diverted flights have `actual_arr_utc` but NULL `arr_delay_min`.
- **Caveat line:** aircraft-driven delay only. No crew or passenger connections.
- **Controller:** `delay` must be an integer from 0 to 1440, with Laravel's usual validation response. An unknown or cancelled flight returns 404. One query against `app_read.propagate`, as the existing controllers do.

## Steps

1. `ontology.min_turn`: migration, build step, fixture tests, and the measured values.
2. `app_read.propagate`: migration and fixture tests for absorbed, carried across two legs, break, the 24h limit, cancelled in gap, a what-if override and the all-carrier fallback.
3. `app_read.propagation_backtest`, the percentile choice, and `docs/phase-3-report.md` with the N102DN section.
4. FlightImpact page, links from TailDay and HubDay, Pest tests and a screenshot.

## Done means

- `pytest`, `pest` and `npm test` pass.
- The report shows the model against both baselines in both windows, and says plainly if the model doesn't beat full carry.
- N102DN's 371994 page shows its chain, the three cancelled legs in its gap, and actual next to predicted.
- `DECISIONS.md` records per-carrier min turn by percentile, flown-chain propagation with cancelled legs shown but not predicted, and the in-sample caveat.

## Notes

Measured values go here as steps finish.

- Measured `ontology.min_turn` for July (turns on ATL-touching tails where the next leg had `late_aircraft` minutes), p10/p25/p50 in minutes:

  | Carrier | Samples | p10 | p25 | p50 |
  |---|---|---|---|---|
  | all | 69,476 | 39 | 47 | 57 |
  | WN | 25,094 | 38 | 44 | 52 |
  | AA | 12,343 | 42 | 49 | 59 |
  | DL | 10,689 | 50 | 58 | 69 |
  | UA | 4,708 | 46 | 52 | 61 |
  | F9 | 4,133 | 44 | 51 | 60 |
  | OH | 3,541 | 28 | 33 | 41 |
  | NK | 2,872 | 47 | 53 | 61 |
  | 9E | 1,964 | 34 | 39 | 46 |
  | AS | 1,435 | 51 | 55 | 60 |
  | MQ | 1,341 | 29 | 33 | 39 |
  | B6 | 1,045 | 42 | 50 | 58 |
  | YX | 311 | 28 | 32 | 40 |

  No carrier falls below 200 samples (smallest is YX at 311), so the all-carrier fallback is not used in July.

- Checked `app_read.propagate(371994)` (N102DN, July 19) on the real July database. Selected DEN->ATL (316 min late), three cancelled rows at depth 1 (ATL->CLE, CLE->ATL, ATL->GEG), then flown ATL->BWI at depth 1: min turn 58 (DL p25), slack 213, predicted delay 0, `absorbed`. Its actual departure delay was 49, arrival delay 28, and `late_aircraft` was a reported 0. `explain analyze` execution time: 3.1 ms for that one call. Over 2,000 real late legs it measured 0.25-0.45 ms per call.
