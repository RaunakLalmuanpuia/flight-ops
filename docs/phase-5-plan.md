# Phase 5: operator workflow

**Goal:** answer "What did the controller decide, and did it help?": log a decision against a flight from its FlightImpact page, freeze the prediction it was made on, and review it later against what BTS shows happened.

Reasoning behind these choices is in `DECISIONS.md`. Out of scope: login, editing or deleting decisions, a what-if simulator that applies a decision to the model, filters on `/decisions`, and decisions from the Live page (it has no schedule).

## What "did it help" can mean here

Every flight is July 2024, so the outcome is already in the database and is visible on the FlightImpact page when the decision is made. The review is therefore an audit trail, not a test of foresight. It can show two things: how the frozen prediction compared with what happened, and whether the airline did what the controller chose. Both review pages say so.

`propagate` walks the flown chain, so every downstream leg was flown by this tail, and cancelled legs come back as their own rows. BTS records only the tail that flew, so a swap can never be confirmed.

## Folder structure

```
flight-ops/
├── db/migrations/022_decisions.sql         # app.decision, app.decision_leg, record_decision, review views, grants
├── pipelines/tests/test_decisions.py       # fixture tests for the write path and the review
└── web/
    ├── app/Http/Controllers/               # DecisionController (store, index, show)
    ├── resources/js/pages/                 # Decisions.vue, Decision.vue, FlightImpact.vue panel
    └── tests/Feature/                      # Pest, inside rolled-back transactions
```

## Data layer

| Object | One row per | Contents |
|---|---|---|
| `app.decision` | logged decision | `decision_id`, `flight_id` and target `flight_id` (nullable) as they were when recorded, `arr_delay_min` used, `what_if`, `percentile`, `action`, `reason`, `author`, `recorded_at`. The natural keys live on the frozen legs, which include the flight itself at depth 0 |
| `app.decision_leg` | snapshot row | `decision_id` and `propagate`'s output as it was at decision time: depth, kind, flight and its natural key, schedule, min turn, slack, predicted delay, predicted arrival, at risk, stop reason |
| `app_read.record_decision(flight, delay, action, target, reason, author)` | call | `SECURITY DEFINER`. Runs `propagate`, inserts the decision and its snapshot in one statement, returns `decision_id` |
| `app_read.decision_review` | decision | the decision, its target's frozen prediction and actual outcome, the match label, and chain totals: predicted at risk, actually departing 15+ min late, cancelled |
| `app_read.decision_legs` | snapshot row | each frozen leg beside its actual dep and arr delay, or cancelled |

- **Actions:** `accept_delay`, `hold_departure`, `swap_aircraft`, `cancel_leg`, `other`, as a check constraint.
- **Refusals in `record_decision`:** a target that is not a flown or cancelled leg in the chain, a target on `accept_delay`, a blank reason or author, a what-if delay on a diverted flight, and a flight with no chain (cancelled or no arrival).
- **Append-only:** no `UPDATE` or `DELETE` for anyone but the owner. A correction is a new decision.
- **No foreign key to `ontology`:** `build` truncates and rebuilds `ontology.flight` with new ids, so a foreign key would block the build or cascade into the log. The review views join on the natural key. A decision whose flight no longer matches shows `flight not found after rebuild` and stays in the log.
- **Grants:** `flightops_app` gets `EXECUTE` on `record_decision` and `SELECT` on the two views. Nothing on `app` itself.

**Match labels for the target leg:**

| Action | BTS shows cancelled | BTS shows flown |
|---|---|---|
| `cancel_leg` | airline did the same | airline flew it, +N min |
| `hold_departure`, `other` | airline cancelled it | flown, +N min vs predicted +M |
| `swap_aircraft` | airline cancelled it | this tail flew it, +N min (swap not visible) |
| `accept_delay` | no target: chain totals only | |

## App

- **FlightImpact decision panel:** action, target leg (flown and cancelled legs of the chain, hidden for `accept_delay`), reason and author. The author is remembered in `localStorage`, wrapped in try/catch. The form posts the page's current delay and what-if state, so the snapshot matches the screen. Below the form, earlier decisions on this flight link to their detail pages.
- **`POST /flights/{flight}/decisions`:** Laravel validates for form messages, then calls `record_decision`. A database refusal comes back as a form error, not a 500. Success redirects to the decision's page.
- **`/decisions`:** all decisions, newest first: when, author, flight, action, target, predicted vs actual, match label. Linked from the nav.
- **`/decisions/{id}`:** the decision, its reason, and the frozen chain beside the actuals, in FlightImpact's table style.
- **Caveat on both review pages:** decisions are logged with the July 2024 outcome visible, and BTS can't show a swap. It uses the existing caveats pattern.
- **No login:** the author is typed, and the app must stay on this machine.

## Steps

1. Migration 022 and `test_decisions.py`: snapshot equals `propagate`, each refusal, a what-if snapshot, every match label, append-only, a direct `INSERT` as `flightops_app` failing, and a decision surviving a fixture rebuild and re-matching.
2. FlightImpact panel and the POST route, with Pest: a round trip on a real July 19 flight and a validation error on the form.
3. `/decisions` and `/decisions/{id}`, the nav link, Pest, screenshots, and a walkthrough: three decisions on the outage's worst tail, with what the review showed written into the notes below.

## Done means

- `pytest`, `pest` and `npm test` pass.
- A decision logged in the browser appears on `/decisions` with its match label.
- A full `build` leaves the log intact and re-matched.
- `DECISIONS.md` records the write path through a SQL function, the `app` tables in a pipelines migration, the append-only log with no foreign key, and the typed author with no login.

## Notes

| Finding | Evidence | Design consequence |
|---|---|---|
