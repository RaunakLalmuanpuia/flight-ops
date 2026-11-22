# Phase 3, step 4: FlightImpact page — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** a page at `/flights/{flight_id}?delay=N` showing what a late arrival puts at risk downstream on its tail, with predicted beside actual, linked from TailDay and HubDay.

**Architecture:** `FlightImpactController` looks the flight up in `app_read.tail_legs` (which gives its tail, ATL day, timezones and cancelled/diverted flags), then runs one query: `app_read.propagate` joined to `tail_legs` for timezones. It uses propagate's default percentile (p10, chosen by the backtest). `FlightImpact.vue` renders a header with a what-if delay form, the chain table and the stop reason. No database changes. Design: the App section of `docs/phase-3-plan.md`.

**Tech Stack:** Laravel 12 + Inertia + Vue 3 (plain JS) + Tailwind 4, Pest against the loaded July database.

## Global Constraints

- The app reads through `flightops_app`, which may `SELECT` on `app_read` and execute `app_read.propagate`, and nothing else. No new migrations.
- `delay` is an integer from 0 to 1440, validated with Laravel's usual response (redirect back with errors).
- An unknown flight, a flight on a tail that never touched ATL, or a cancelled flight returns the existing `NotFound` page with status 404, via `Days::missing`.
- Cancelled-in-gap rows read "Scheduled on this tail, cancelled, not predicted".
- When `delay` differs from the actual arrival delay, the actual columns are dimmed and labelled as not comparable.
- Caveat line: aircraft-driven delay only, no crew or passenger connections.
- Look up N102DN's DEN→ATL in tests by tail, day and origin, never by the surrogate `flight_id`.
- Run web commands from `web/`: `./vendor/bin/pest`, `npm test`, `npm run build`.

## Choice for review: a diverted start

A diverted flight has an actual landing but no arrival delay. All 1,414 diverted legs on ATL tails have NULL `arr_delay_min`, and 1,378 have a next leg. So:

- **Chosen:** the page shows the chain propagated from the actual landing (propagate's NULL-delay path), with a line saying BTS gives no arrival delay for a diversion. There is no what-if form, and `?delay=` on a diverted flight fails validation with "A diverted flight has no arrival delay to replace."
- **Gave up:** a what-if for diversions. Propagate's override measures from the scheduled arrival at the *scheduled* destination, which is the wrong airport when the aircraft landed elsewhere.

A flight that arrived early gets a default input of 0, because the form's range starts at 0. Submitting it counts as a what-if, since 0 differs from the actual delay.

## Files

| File | Change |
|---|---|
| `web/app/Http/Controllers/FlightImpactController.php` | new |
| `web/routes/web.php` | add `/flights/{flight}` |
| `web/resources/js/pages/FlightImpact.vue` | new |
| `web/resources/js/components/TailLegs.vue` | link flown legs |
| `web/resources/js/components/FlightTable.vue` | link late arrivals |
| `web/tests/Feature/FlightImpactTest.php` | new |
| `web/scripts/screenshots.sh` | add the N102DN impact page |
| `docs/screenshots/flight-N102DN-2024-07-19.png` | generated |
| `DECISIONS.md`, `docs/phase-3-plan.md`, `CLAUDE.md` | decision, notes, status |

---

### Task 1: Controller, route and Pest tests

**Files:**
- Create: `web/app/Http/Controllers/FlightImpactController.php`
- Modify: `web/routes/web.php`
- Create: `web/tests/Feature/FlightImpactTest.php`
- Create: `web/resources/js/pages/FlightImpact.vue` (a stub in this task, so Inertia can resolve the component; Task 2 fills it)

**Interfaces:**
- Produces: route `GET /flights/{flight}` (`\d+`), rendering Inertia component `FlightImpact` with props:
  - `flight`: the `selected` row of `propagate`, plus `tail_number`, `leg_day`, `origin_tz`, `dest_tz`, `diverted`, `landed`, `landed_tz` from `tail_legs`.
  - `legs`: the rows at depth 1 and beyond, in propagate's order (depth, cancelled before flown, then scheduled departure), with the same added columns.
  - `delay`: `int|null`, the arrival delay propagated (`null` for a diverted start).
  - `whatIf`: `bool`, true when `delay` differs from the actual arrival delay.
  - `stop`: `string|null`, the chain's `stop_reason`.

- [ ] **Step 1: Write the failing tests** in `web/tests/Feature/FlightImpactTest.php`:

```php
<?php

use Illuminate\Support\Collection;
use Illuminate\Support\Facades\DB;
use Inertia\Testing\AssertableInertia as Assert;

function n102dn(): int
{
    // DEN->ATL on July 19, 316 min late; looked up, since flight_id is a surrogate
    return DB::selectOne("select flight_id from tail_legs where tail_number = 'N102DN' and leg_day = '2024-07-19' and origin = 'DEN'")->flight_id;
}

it('shows the chain of a late arrival with cancelled legs in its gap', function () {
    $this->get('/flights/'.n102dn())->assertOk()->assertInertia(fn (Assert $page) => $page
        ->component('FlightImpact')
        ->where('flight.flight_number', '2341')
        ->where('flight.tail_number', 'N102DN')
        ->where('delay', 316)
        ->where('whatIf', false)
        ->where('stop', 'absorbed')
        ->where('legs', fn (Collection $legs) => $legs->map(fn ($l) => [$l['kind'], $l['flight_number']])->all() === [
            ['cancelled', '1487'], ['cancelled', '1487'], ['cancelled', '574'], ['flown', '2590'],
        ])
        ->where('legs.3.predicted_dep_delay', 0)
        ->where('legs.3.actual_dep_delay', 49));
});

it('propagates a what-if delay', function () {
    // 600 min instead of 316 eats ATL->BWI's 221 min of slack and 63 more; BWI->ATL absorbs it
    $this->get('/flights/'.n102dn().'?delay=600')->assertOk()->assertInertia(fn (Assert $page) => $page
        ->where('delay', 600)
        ->where('whatIf', true)
        ->where('legs.3.predicted_dep_delay', 63)
        ->where('legs.3.at_risk', true)
        ->where('legs.4.flight_number', '2950')
        ->where('stop', 'absorbed'));
});

it('treats the actual delay given explicitly as not a what-if', function () {
    $this->get('/flights/'.n102dn().'?delay=316')->assertInertia(fn (Assert $page) => $page->where('whatIf', false));
});

it('rejects a delay that is not a whole number from 0 to 1440', function (string $delay) {
    $this->get('/flights/'.n102dn()."?delay={$delay}")->assertSessionHasErrors('delay');
})->with(['-1', '1441', 'abc', '1.5']);

it('starts a diverted flight from its actual landing, without a what-if', function () {
    $id = DB::selectOne('select t.flight_id from tail_legs t
        where t.diverted and t.actual_arr_utc is not null and exists (select 1 from tail_legs n where n.tail_number = t.tail_number and n.leg_seq = t.leg_seq + 1)
        order by t.flight_id limit 1')->flight_id;

    $this->get("/flights/{$id}")->assertOk()->assertInertia(fn (Assert $page) => $page
        ->where('flight.diverted', true)
        ->where('delay', null)
        ->where('legs', fn (Collection $legs) => $legs->isNotEmpty()));
    $this->get("/flights/{$id}?delay=30")->assertSessionHasErrors(['delay' => 'A diverted flight has no arrival delay to replace.']);
});

it('returns not found for a cancelled flight', function () {
    $id = DB::selectOne('select flight_id from tail_legs where cancelled order by flight_id limit 1')->flight_id;
    $this->get("/flights/{$id}")->assertNotFound()->assertInertia(fn (Assert $page) => $page->component('NotFound'));
});

it('returns not found for an unknown flight', function () {
    $this->get('/flights/999999999')->assertNotFound()->assertInertia(fn (Assert $page) => $page->component('NotFound'));
});
```

Create the stub page, `web/resources/js/pages/FlightImpact.vue`:

```vue
<template><main /></template>
```

- [ ] **Step 2: Run them and see them fail**

Run: `cd web && ./vendor/bin/pest tests/Feature/FlightImpactTest.php`
Expected: every test fails. The router's fallback returns 404 for `/flights/...`, so the `assertOk` tests and the validation tests fail. The two not-found tests may already pass through the fallback, which is fine: they pin behaviour the controller must keep.

- [ ] **Step 3: Write the controller** `web/app/Http/Controllers/FlightImpactController.php`:

```php
<?php

namespace App\Http\Controllers;

use App\Support\Days;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\DB;
use Inertia\Inertia;

class FlightImpactController
{
    public function __invoke(Request $request, int $flight)
    {
        $leg = DB::selectOne('select cancelled, diverted, arr_delay_min from tail_legs where flight_id = ?', [$flight]);
        if (! $leg) {
            return Days::missing("No flight {$flight} on an aircraft that touched ATL.");
        }
        if ($leg->cancelled) {
            return Days::missing("Flight {$flight} was cancelled, so it has no arrival to propagate.");
        }

        // A diversion has no arrival delay, and propagate's override measures from the scheduled destination
        $given = $request->validate(
            ['delay' => $leg->diverted ? ['prohibited'] : ['nullable', 'integer', 'between:0,1440']],
            ['delay.prohibited' => 'A diverted flight has no arrival delay to replace.'],
        )['delay'] ?? null;
        $whatIf = $given !== null && (int) $given !== $leg->arr_delay_min;

        $rows = collect(DB::select(
            'select p.*, t.tail_number, t.leg_day, t.origin_tz, t.dest_tz, t.diverted, t.landed, t.landed_tz
             from propagate(?, ?) p join tail_legs t using (flight_id)
             order by p.depth, p.kind = \'flown\', p.sched_dep_utc',
            [$flight, $whatIf ? (int) $given : null]));
        if ($rows->isEmpty()) {
            return Days::missing("Flight {$flight} has no arrival to propagate from.");
        }

        return Inertia::render('FlightImpact', [
            'flight' => $rows->first(),
            'legs' => $rows->slice(1)->values(),
            'delay' => $whatIf ? (int) $given : $leg->arr_delay_min,
            'whatIf' => $whatIf,
            'stop' => $rows->pluck('stop_reason')->filter()->last(),
        ]);
    }
}
```

Passing NULL when the given delay equals the actual one keeps the page identical to the backtest's numbers, which use the actual arrival time.

In `web/routes/web.php`, add the import and the route after the tail route:

```php
use App\Http\Controllers\FlightImpactController;
```

```php
Route::get('/flights/{flight}', FlightImpactController::class)->where('flight', '\d+');
```

- [ ] **Step 4: Run the tests and see them pass**

Run: `cd web && ./vendor/bin/pest tests/Feature/FlightImpactTest.php`
Expected: 10 passed (the dataset makes the validation test four cases).

- [ ] **Step 5: Run the whole Pest suite**

Run: `cd web && ./vendor/bin/pest`
Expected: 30 passed.

- [ ] **Step 6: Commit**

```bash
git add web/app/Http/Controllers/FlightImpactController.php web/routes/web.php web/tests/Feature/FlightImpactTest.php web/resources/js/pages/FlightImpact.vue
git commit -m "feat: serve a late flight's downstream chain"
```

---

### Task 2: The page and its links

**Files:**
- Modify: `web/resources/js/pages/FlightImpact.vue` (replace the stub)
- Modify: `web/resources/js/components/TailLegs.vue`
- Modify: `web/resources/js/components/FlightTable.vue`

**Interfaces:**
- Consumes: the props from Task 1, and `localDate`, `localTime`, `utcTitle` from `resources/js/lib/time.js`.

- [ ] **Step 1: Write the page** `web/resources/js/pages/FlightImpact.vue`:

```vue
<script setup>
import { computed, ref } from 'vue';
import { Head, Link, router, usePage } from '@inertiajs/vue3';
import { localDate, localTime, utcTitle } from '../lib/time.js';

const props = defineProps({ flight: Object, legs: Array, delay: Number, whatIf: Boolean, stop: String });
const page = usePage();

const STOPS = {
    absorbed: 'Delay absorbed: every later leg is predicted on time.',
    break: "Rotation break: the next leg doesn't start where this one landed, so the chain stops unpredicted.",
    limit: 'The next leg is scheduled more than 24 hours after this arrival, so the chain stops unpredicted.',
    end: "End of this tail's data while the delay was still being carried.",
};

const input = ref(Math.max(0, props.delay ?? 0));
const submit = () => router.get(`/flights/${props.flight.flight_id}`, { delay: input.value });
const dim = computed(() => (props.whatIf ? 'opacity-40' : ''));
const minutes = (n) => (n === null || n === undefined ? '—' : `${n} min`);
const arrival = (n) => (n > 0 ? `${n} min late` : n < 0 ? `${-n} min early` : 'on time');
</script>

<template>
    <Head :title="`${flight.carrier} ${flight.flight_number} impact`" />
    <main class="mx-auto max-w-7xl space-y-4 px-4 py-6">
        <header class="space-y-1">
            <Link :href="`/tail/${flight.tail_number}/${flight.leg_day}`" class="text-sm text-sky-700 underline">← {{ flight.tail_number }} on {{ flight.leg_day }}</Link>
            <h1 class="text-xl font-semibold">
                {{ flight.carrier }} {{ flight.flight_number }} · {{ flight.origin }} → {{ flight.dest }} · {{ localDate(flight.sched_dep_utc, flight.origin_tz) }} · {{ flight.tail_number }}
            </h1>
            <p v-if="flight.diverted" class="text-sm text-violet-800">
                Diverted, landed {{ flight.landed ?? '?' }}. BTS gives no arrival delay for a diversion, so the chain starts from the actual landing time and there is no delay to change.
            </p>
            <p v-else class="text-sm">Arrived {{ arrival(flight.actual_arr_delay) }}.<template v-if="whatIf"> Showing what a {{ delay }}-min arrival delay would do instead.</template></p>
        </header>

        <form v-if="!flight.diverted" class="flex flex-wrap items-end gap-2 text-sm" @submit.prevent="submit">
            <label>Arrival delay to propagate (min)
                <input v-model.number="input" type="number" min="0" max="1440" step="1" required class="ml-1 w-24 rounded border border-slate-300 bg-white px-1 py-0.5" />
            </label>
            <button type="submit" class="rounded border border-slate-300 bg-white px-2 py-0.5">Propagate</button>
            <Link v-if="whatIf" :href="`/flights/${flight.flight_id}`" class="text-sky-700 underline">Back to the actual delay</Link>
            <p v-if="page.props.errors?.delay" class="w-full text-red-700" role="alert">{{ page.props.errors.delay }}</p>
        </form>

        <p class="text-xs text-slate-500">
            Aircraft-driven delay only: no crew or passenger connections. Each leg is predicted from the previous predicted arrival, the carrier's minimum turn measured from July, and the schedule, with no time made up in the air. At risk means a predicted departure delay of 15 min or more.
        </p>

        <p v-if="!legs.length" class="text-slate-500">No later flights on this tail in the loaded data.</p>
        <div v-else class="overflow-x-auto rounded border border-slate-200 bg-white">
            <table class="w-full text-left text-sm">
                <thead class="bg-slate-100 text-xs uppercase text-slate-600">
                    <tr>
                        <th class="px-2 py-1">Leg</th><th class="px-2 py-1">Flight</th><th class="px-2 py-1">Route</th>
                        <th class="px-2 py-1">Sched dep (local)</th><th class="px-2 py-1">Min turn</th><th class="px-2 py-1">Slack</th>
                        <th class="px-2 py-1">Predicted dep delay</th>
                        <th class="px-2 py-1" :class="dim">Actual dep delay</th><th class="px-2 py-1" :class="dim">Actual arr delay</th>
                        <th class="px-2 py-1" :class="dim">Actual late-aircraft</th>
                    </tr>
                </thead>
                <tbody>
                    <tr v-for="l in legs" :key="`${l.kind}-${l.flight_id}`" class="border-t border-slate-100 align-top" :class="l.kind === 'cancelled' && 'bg-slate-50 text-slate-500'">
                        <td class="px-2 py-1">{{ l.depth }}</td>
                        <td class="px-2 py-1 whitespace-nowrap">{{ l.carrier }} {{ l.flight_number }}</td>
                        <td class="px-2 py-1 whitespace-nowrap">{{ l.origin }} → {{ l.dest }}</td>
                        <td class="px-2 py-1 whitespace-nowrap" :title="utcTitle(l.sched_dep_utc)">{{ localDate(l.sched_dep_utc, l.origin_tz) }} {{ localTime(l.sched_dep_utc, l.origin_tz) }}</td>
                        <td v-if="l.kind === 'cancelled'" colspan="6" class="px-2 py-1 italic">Scheduled on this tail, cancelled, not predicted</td>
                        <template v-else>
                            <td class="px-2 py-1">{{ minutes(l.min_turn) }}</td>
                            <td class="px-2 py-1">{{ minutes(l.slack_min) }}</td>
                            <td class="px-2 py-1">
                                <span v-if="l.at_risk" class="badge bg-amber-100 text-amber-900">{{ l.predicted_dep_delay }} min · at risk</span>
                                <template v-else-if="l.predicted_dep_delay !== null">{{ l.predicted_dep_delay }} min</template>
                                <span v-else class="text-slate-500">not predicted ({{ l.stop_reason }})</span>
                            </td>
                            <td class="px-2 py-1" :class="dim">{{ minutes(l.actual_dep_delay) }}</td>
                            <td class="px-2 py-1" :class="dim">{{ minutes(l.actual_arr_delay) }}</td>
                            <td class="px-2 py-1" :class="dim">{{ l.actual_late_aircraft === null ? 'not reported' : `${l.actual_late_aircraft} min` }}</td>
                        </template>
                    </tr>
                </tbody>
            </table>
        </div>

        <p v-if="stop" class="text-sm text-slate-700">{{ STOPS[stop] ?? stop }}</p>
        <p v-if="whatIf" class="text-xs text-slate-500">Actual columns are dimmed and not comparable: they record what followed the real {{ flight.actual_arr_delay }}-min delay, not this one.</p>
    </main>
</template>
```

- [ ] **Step 2: Link flown legs on TailDay.** In `web/resources/js/components/TailLegs.vue`, add `import { Link } from '@inertiajs/vue3';` to the script, and replace

```
                        {{ localDate(r.leg.sched_dep_utc, r.leg.origin_tz) }} · {{ r.leg.carrier }} {{ r.leg.flight_number }} · {{ r.leg.origin }} → {{ r.leg.dest }}
```

with

```
                        {{ localDate(r.leg.sched_dep_utc, r.leg.origin_tz) }} ·
                        <Link v-if="!r.leg.cancelled" :href="`/flights/${r.leg.flight_id}`" class="text-sky-700 underline" title="What a delay here puts at risk downstream">{{ r.leg.carrier }} {{ r.leg.flight_number }}</Link>
                        <template v-else>{{ r.leg.carrier }} {{ r.leg.flight_number }}</template>
                        · {{ r.leg.origin }} → {{ r.leg.dest }}
```

- [ ] **Step 3: Link late arrivals on HubDay.** In `web/resources/js/components/FlightTable.vue`, replace

```
                        <td class="px-2 py-1 whitespace-nowrap">{{ f.carrier }} {{ f.flight_number }}</td>
```

with

```
                        <td class="px-2 py-1 whitespace-nowrap">
                            <Link v-if="f.tail_number && f.arr_delay_min >= 15" :href="`/flights/${f.flight_id}`" class="text-sky-700 underline" title="What this late arrival puts at risk downstream">{{ f.carrier }} {{ f.flight_number }}</Link>
                            <template v-else>{{ f.carrier }} {{ f.flight_number }}</template>
                        </td>
```

`Link` is already imported there.

- [ ] **Step 4: Build and test**

Run: `cd web && npm run build && npm test && ./vendor/bin/pest`
Expected: the build succeeds, 24 node tests pass, and 30 Pest tests pass.

- [ ] **Step 5: Check it in a browser.** Start the app (`cd web && php artisan serve`) and open `/day/2024-07-19`, then a late arrival's flight link. Also open N102DN's July 19 tail page, then its DEN→ATL link. Check:
  - three grey "cancelled, not predicted" rows, then ATL→BWI with 50 min turn, 221 min slack, predicted 0 min, actual 49 min dep
  - the "Delay absorbed" line
  - entering 600 and pressing Propagate gives ATL→BWI "63 min · at risk", the actual columns dimmed, and the not-comparable note
  - "Back to the actual delay" returns to 316
  - a diverted leg's page shows the diversion line and no form
  - at phone width (390 px) the table scrolls inside its box and the page doesn't scroll sideways

- [ ] **Step 6: Commit**

```bash
git add web/resources/js/pages/FlightImpact.vue web/resources/js/components/TailLegs.vue web/resources/js/components/FlightTable.vue
git commit -m "feat: FlightImpact page, linked from tail legs and late hub arrivals"
```

---

### Task 3: Screenshot and records

**Files:**
- Modify: `web/scripts/screenshots.sh`
- Generate: `docs/screenshots/flight-N102DN-2024-07-19.png`
- Modify: `DECISIONS.md`, `docs/phase-3-plan.md`, `CLAUDE.md`

- [ ] **Step 1: Add the screenshot.** Append to `web/scripts/screenshots.sh`:

```bash
# shortcut: N102DN's DEN->ATL by flight_id, which held across July rebuilds so far; look it up if a rebuild renumbers flights
shot flight-N102DN-2024-07-19 /flights/371994 1440,900
```

Run (with the app serving): `cd web && scripts/screenshots.sh`
Expected: five PNG paths printed. Open the new one and check it shows the chain described in Task 2, step 5.

- [ ] **Step 2: Record it.**
  - `DECISIONS.md`: an entry for the diverted start (chose: chain from the actual landing, no what-if; gave up: what-if for diversions; why: propagate's override measures from the scheduled destination, and 1,414 diverted ATL-tail legs have no arrival delay; revisit if: propagate gains an override measured from the actual landing).
  - `docs/phase-3-plan.md`: replace the "Diverted start" bullet with the decision, and add a Notes bullet for step 4 (the page, its links, the Pest count).
  - `CLAUDE.md` Status: phase 3 complete. Next action: start phase 4 per `docs/roadmap.md` (brainstorm first, since it has no plan file).

- [ ] **Step 3: Verify everything**

Run: `cd pipelines && uv run --env-file ../.env pytest -q` and `cd web && ./vendor/bin/pest && npm test && npm run build`
Expected: 152 pytest, 30 Pest and 24 node tests pass, and the build succeeds.

- [ ] **Step 4: Commit**

```bash
git add web/scripts/screenshots.sh docs/screenshots/flight-N102DN-2024-07-19.png DECISIONS.md docs/phase-3-plan.md CLAUDE.md
git commit -m "docs: FlightImpact screenshot, diverted-start decision, phase 3 done"
```
