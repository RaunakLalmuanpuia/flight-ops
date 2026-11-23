# Phase 6: cancellation risk

**Goal:** answer "When an inbound aircraft is late, which of its later flights are likely to be cancelled, not just delayed?" Give each of the tail's next scheduled legs a cancellation probability, fitted on July 2024 and scored on August 2024, and show it on FlightImpact and in the decision log.

Reasoning behind these choices goes in `DECISIONS.md` as each is built. Out of scope: a regression or other fitted model (the rate table is the baseline to beat first), cancellation risk on the Live page (it has no schedule), backfilling scores into decisions logged before this phase, and a second hub.

## Why now

- The propagation model scores only the flying that survived. During the outage, 9.8% of late arrivals (2,659 of 27,050) had a cancelled leg on the same tail before its next flown leg, against 1.6% (1,470 of 90,768) on normal days ([phase 3 report](phase-3-report.md#what-the-model-misses)).
- On N102DN's 316-min DEN→ATL on July 19, `propagate` predicted 0 legs at risk while 3 were cancelled. A 600-min what-if predicted BWI→ATL at +0, and it left 308 min late (phase 5 notes).
- `DECISIONS.md`, "Propagate along the flown chain, and show cancelled legs without predicting them", said to revisit this when cancellations in the gap follow large delays. They do: see Notes.

## Step 1: August 2024 and a true phase 3 holdout

Only July is loaded, and the outage is inside it, so August comes first.

- **Load:** BTS August 2024 and IEM weather from August 2 to September 2 UTC, through the existing loaders, as new entries in `sources/registry.py`. `staging.current_delivery` is keyed by source file, so a second month adds rather than replaces. OpenSky August is left out, because nothing in this phase reads it and it costs 1,860 credits.
- **Periods:** `july_normal`, `july_outage` (flight date July 19-23) and `august`. If ATL cancellations by day show Hurricane Debby in early August, a `debby` period is added with a window taken from those counts. If they don't, there is no `debby` period and the report says so. This is decided after loading, not assumed.
- **Phase 3 re-score:** `min_turn` is measured on July only. The percentile grid gains p5 (p10 sat at the edge) and is chosen on `july_normal` depth-1 `late_aircraft` error. `propagation_backtest` is scored on both months, and the report's headline numbers come from `august`. If p5 wins, a migration changes `propagate`'s default.
- **Places that assume July:** `rotations/backtest.sql`, `rotations/min_turn.sql` and `report.py` (outage window, period labels), all replaced by one `ontology.period(flight_date)` function (migration 023). `dq/checks.py`'s July 19-23 check stays July-scoped. The app's day range comes from `app_read.day_range`, so it extends to August 31 by itself.
- **Whole-database figures move:** `touched_atl` is computed over all loaded flights, so a tail that touched ATL only in August now counts in July too, and the phase 1 report's whole-database tables (checks, tail matching, rotation breaks, weather join) cover both months. The phase 1 report becomes a report on all loaded data, and its date-scoped tables keep their July dates.
- **Rechecks:** Pest's July assertions, the decision log's natural key across both months, and every figure in `docs/case-study.md` and `docs/phase-3-report.md`.
- **Thresholds stay deferred:** reported checks are whole-database totals, so two months give one value each, not two to compare. Setting thresholds needs per-month checks, which nothing in this phase uses.

## Step 2: the rate table and its backtest

### Definitions

- **Inbound:** a flown leg on a tail that touched ATL, with an arrival delay. Diverted legs have none, so they are not scored.
- **Decision moment `t`:** the inbound's actual departure, when a controller learns it is late. The feature uses the inbound's arrival delay, which includes en-route change after `t`. `propagate` uses the same delay, so the limit is shared and stated.
- **Targets:** the tail's next three legs by scheduled departure after the inbound's scheduled departure, flown or cancelled, scheduled no later than the inbound's arrival plus 24h. `rank` is 1-3 in schedule order. This is the leg set behind the phase 3 report's 9.8%. A tail swap is invisible: BTS records the tail that flew or was assigned, so the later schedule is partly hindsight.
- **Outcome:** the target leg's `cancelled`.

### Features

| Feature | Definition | Buckets |
|---|---|---|
| Delay | inbound arrival delay, or the what-if delay on FlightImpact | <15 (including early), 15-59, 60-119, 120-239, 240+ |
| Rank | the target's schedule rank after the inbound | 1, 2, 3 |
| Carrier stress | share of the carrier's national departures scheduled in `[t − 3h, t)` that were cancelled, excluding the inbound's own tail. A cancellation counts as known from its scheduled departure, because BTS gives no announcement time. No departures in the window counts as 0 | <2%, 2-10%, 10%+, tentative until July's distribution is measured |
| Carrier | the inbound's operating carrier | as `ontology.carrier` |

Excluding the own tail matters: after a long delay the target's own cancellation can fall inside the window and become its own feature.

### Objects

| Object | One row per | Contents |
|---|---|---|
| `ontology.cancel_rate` | carrier (NULL for all carriers) × rank × delay bucket × stress bucket | `samples`, `cancelled`, `rate`. Built from July only |
| `ontology.cancel_backtest` | inbound × target, both months | period, rank, buckets, `predicted_rate`, `basis` (carrier or all-carrier cell, with its sample count), the two baselines' rates, `actual_cancelled` |

- **Fallback:** a carrier cell with under 200 samples uses the all-carrier cell, as `min_turn` does. An all-carrier cell under 200 samples is still used, and its `basis` shows the count.
- **Build:** both tables are filled by `pipeline.build` after `min_turn`, set-based, not per-call. Stress comes from precomputed carrier-hour counts, less the own tail's. The unindexed probe took over 10 minutes (see Notes), so the build time is measured and written down.

### Report

A new generated section in `report.py`, tables with their SQL under each as before. For each period and rank:

- **Brier score** of the model against two baselines: the carrier's July cancellation rate in the score set (constant), and delay bucket × rank across all carriers (delay only).
- **Calibration:** predicted against actual cancellation rate by decile of predicted rate.
- **Flag:** precision and recall at the cancellation-risk threshold, chosen on all of July to maximize F1 over ranks 1-3 pooled, and scored on August.
- **N102DN worked example:** the three cancelled gap legs and ATL→BWI, each with its rate and basis.
- **Limits:** July's high-stress cells are fitted on a single outage. If August has no comparable disruption, those cells are untested out of sample, and the report says that instead of claiming otherwise.

## Step 3: `propagate` and the decision log (next free migration)

- **`propagate` gains `cancel_risk` (numeric) and `cancel_risk_basis` (text).** Rows are scored by schedule rank after the selected flight, not by `propagate`'s depth, since N102DN's three cancelled legs all come back at depth 1. Ranks 1-3 within 24h get a rate, the rest are NULL. A what-if delay changes only the delay bucket. Stress always comes from the inbound's actual departure. A diverted start gets NULL, with basis `not scored: diverted`.
- **New output columns mean `DROP FUNCTION` and re-create.** Grants are reapplied in the same migration. `record_decision` is plpgsql, so it doesn't block the drop. Its tests catch the change.
- **`app.decision_leg`** gains nullable `cancel_risk` and `cancel_risk_basis`, filled by `record_decision`'s existing single `propagate` call. Rows logged before this phase stay NULL: the log is append-only.
- **`app_read.decision_legs`** returns them. **`app_read.decision_review`** gains a chain total: legs flagged at cancellation risk.

## Step 4: app

- **FlightImpact:** a "Cancel risk" column beside predicted delay, as a percentage with a cancellation-risk badge at the threshold, and "not scored" where NULL. A caveat in the existing pattern says it is fitted on July, scored on August, and that cancellations count as known only from their scheduled departure.
- **`/decisions/{id}`:** the frozen risk beside "cancelled" or "flown". NULL rows read "recorded before cancellation risk".
- **`/decisions`:** the flagged-legs total beside the existing chain totals.
- **Screenshots** regenerated with `web/scripts/screenshots.sh`, and a walkthrough on N102DN's July 19 DEN→ATL written into the notes below.

## Testing

- **pytest fixtures:** stress excludes the own tail. A cancellation counts only from its scheduled departure. Ranks follow the schedule, not the flown chain. The 24h cut. The fallback under 200 samples. Delay buckets at their edges, including early arrivals.
- **`propagate`:** an N102DN-shaped fixture, with three cancelled gap legs scored at ranks 1-3 and the flown leg after them unscored. What-if changes the bucket. A diverted start returns NULL.
- **`record_decision`:** the snapshot carries the new columns, and decisions logged before that migration survive it with NULLs.
- **Pest:** the cancel-risk column on a real July 19 flight, and the decision page showing frozen risk and the pre-phase label.
- Report numbers are generated, not asserted.

## Done means

- `pytest`, `pest`, `npm test` and `npm run build` pass, and a full `build` loads both months.
- The phase 3 report scores August as the holdout, and the case study's figures are rechecked.
- The cancellation report shows the model's Brier score against both baselines on `august`, with calibration and the flag threshold.
- A decision logged on FlightImpact freezes the risk, and `/decisions/{id}` shows it beside the outcome.
- `DECISIONS.md` records loading August before modelling, the rate table over a regression, the decision moment and stress definition, the cancellation-known-at-scheduled-departure proxy, the threshold choice, and the phase 3 percentile result.

## Notes

| Finding | Evidence | Design consequence |
|---|---|---|
| Next-leg cancellation rises with inbound delay | July, ATL tails, next scheduled leg cancelled. Normal days: 0.53% under 15 min, 1.08%, 1.87%, 3.03%, 6.12% at 240+. Outage: 2.32% to 32.1% across the same buckets | Delay is a feature. Under-15 arrivals are kept, for the base rate and the what-if |
| The outage multiplies every bucket by 4-5x | Same table | A table fitted on normal days alone would underpredict a bad day, so it needs a day-state feature |
| Carrier stress separates more than delay does | July probe, stress over the 3h before actual arrival, own tail not excluded. Under 60 min late: 0.27% at stress <2%, 2.19% at 2-10%, 9.20% at 10%+. At 120+ min: 1.28%, 6.00%, 28.5% | Stress is a feature. The probe's cuts are the starting buckets. The real table excludes the own tail and uses actual departure, so it will read slightly lower |
| High-stress cells are not too sparse | The 10%+, 120+ cell holds 6,082 samples at all-carrier level, 12,319 for under 60 min | The 200-sample fallback should mostly land on carrier cells |
| The stress query needs precomputing | The probe, a correlated subquery over an unindexed carrier-hour temp table, ran over 10 minutes | Build stress from indexed carrier-hour counts, and measure the build time |
| August has one disruption, and it is mild | ATL cancellations Aug 2-6: 25, 74, 141, 129, 45, mostly code B; August median 5 a day; worst day 6.8% of ATL flights against 43% on July 19 | A `debby` period (migration 024). August can't test the outage's high-stress cells out of sample, and the cancellation report must say so |
