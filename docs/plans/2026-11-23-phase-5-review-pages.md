# Phase 5 Step 3: Decision Review Pages and Close-out Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** review logged decisions on `/decisions` and `/decisions/{id}`, send a new decision to its own page, then record a three-decision walkthrough on N102DN, take screenshots and close phase 5 in the docs.

**Architecture:** `DecisionController` gains `index` and `show`, both reading `app_read.decision_review` and `app_read.decision_legs` (migration 022). `show` left-joins `tail_legs` on `current_flight_id` for each leg's origin timezone. Two new Vue pages reuse `lib/decisions.js`, which gains the hindsight caveat text and an `outcome()` helper. The nav link goes in HubDay's header beside "ATL live →".

**Tech Stack:** Laravel 12, Inertia v3, Vue 3, Tailwind 4, Pest, `node --test`, headless Chrome via `web/scripts/screenshots.sh`.

## Global Constraints

- The app reads `app_read` only, and writes only through `record_decision`.
- Caveat text on both review pages, exactly: `Decisions are logged with the July 2024 outcome already visible on the flight page, so this is an audit trail, not a test of foresight. BTS records only the tail that flew, so a swap can never be confirmed.`
- Pest tests that write use `DatabaseTransactions` and leave no rows. The walkthrough's three decisions in Task 2 are kept on purpose, as portfolio data.
- Known July values for N102DN's DEN→ATL 2341 on 2024-07-19 (`flight_id` 371994 in the current build): actual arrival +316. Its chain is cancelled 1487, 1487, 574, then flown ATL→BWI 2590 (predicted +0, actual dep +49), where it is absorbed. With a 600-min what-if, 2590 is predicted +63 and BWI→ATL 2950 +0 (actual dep +308).
- Port 8000 is taken by another process on this Mac. Serve on 8010 and leave 8000 alone.
- Commands run from `web/`: `./vendor/bin/pest`, `npm test`, `npm run build`.

---

### Task 1: `/decisions` and `/decisions/{id}`

**Files:**
- Modify: `web/app/Http/Controllers/DecisionController.php`
- Modify: `web/routes/web.php`
- Modify: `web/resources/js/lib/decisions.js`, `web/resources/js/lib/decisions.test.js`
- Create: `web/resources/js/pages/Decisions.vue`, `web/resources/js/pages/Decision.vue`
- Modify: `web/resources/js/components/DecisionPanel.vue` (earlier decisions link to their page)
- Modify: `web/resources/js/pages/HubDay.vue` (nav link)
- Modify: `web/tests/Feature/DecisionTest.php`

**Interfaces:**
- Consumes: `decision_review` (one row per decision: `decision_id, recorded_at, author, action, reason, arr_delay_min, what_if, percentile, carrier, flight_number, origin, dest, sched_dep_utc, current_flight_id, flight_found, target_carrier, target_flight_number, target_origin, target_dest, target_sched_dep_utc, target_kind, target_predicted_dep_delay, target_cancelled, target_actual_dep_delay, predicted_at_risk, actually_late, cancelled, match_label`), and `decision_legs` (frozen leg columns plus `is_target, current_flight_id, actual_cancelled, actual_dep_delay, actual_arr_delay`). Test helpers `n102dn()`, `bwi()` and `decision()` from step 2.
- Produces: routes `GET /decisions` (Inertia `Decisions`, prop `decisions`) and `GET /decisions/{decision}` (Inertia `Decision`, props `decision` and `legs`, each leg with `origin_tz`). `POST /flights/{flight}/decisions` now redirects to `/decisions/{id}`. `lib/decisions.js` adds `HINDSIGHT: string` and `outcome(d): string`.

- [ ] **Step 1: Write the failing Pest tests**

In `web/tests/Feature/DecisionTest.php`, change the first two tests' redirect assertions, since a new decision now opens its own page:

```php
it('records a decision with its frozen chain and opens it', function () {
    $response = decision();

    $d = DB::selectOne("select * from decision_review where author = 'pest'");
    $response->assertRedirect("/decisions/{$d->decision_id}");
    expect($d->action)->toBe('cancel_leg')
        ->and($d->target_flight_number)->toBe('2590')
        ->and($d->arr_delay_min)->toBe(316)
        ->and($d->what_if)->toBeFalse()
        ->and($d->match_label)->toBe('airline flew it, +49 min');
    expect(DB::selectOne('select count(*) as n from decision_legs where decision_id = ?', [$d->decision_id])->n)->toBe(5);
});

it('freezes a what-if delay', function () {
    $response = decision(['delay' => 600]);

    $d = DB::selectOne("select decision_id, arr_delay_min, what_if, target_predicted_dep_delay from decision_review where author = 'pest'");
    $response->assertRedirect("/decisions/{$d->decision_id}");
    expect([$d->arr_delay_min, $d->what_if, $d->target_predicted_dep_delay])->toBe([600, true, 63]);
});
```

These replace `it('records a decision with its frozen chain and returns to the flight', ...)` and `it('freezes a what-if delay and returns to the what-if', ...)`. Leave the other tests as they are, and append:

```php
function pestDecisionId(): int
{
    return DB::selectOne("select decision_id from decision_review where author = 'pest' order by decision_id desc limit 1")->decision_id;
}

it('lists decisions newest first with their outcome', function () {
    decision(['action' => 'hold_departure']);
    decision(['action' => 'accept_delay', 'target' => null]);

    $this->get('/decisions')->assertOk()->assertInertia(fn (Assert $page) => $page
        ->component('Decisions')
        ->where('decisions.0.action', 'accept_delay')
        ->where('decisions.0.match_label', null)
        ->where('decisions.0.predicted_at_risk', 0)
        ->where('decisions.0.actually_late', 1)
        ->where('decisions.0.cancelled', 3)
        ->where('decisions.1.action', 'hold_departure')
        ->where('decisions.1.match_label', 'flown, +49 min vs predicted +0'));
});

it('shows a decision with its frozen chain beside the actuals', function () {
    decision();

    $this->get('/decisions/'.pestDecisionId())->assertOk()->assertInertia(fn (Assert $page) => $page
        ->component('Decision')
        ->where('decision.flight_number', '2341')
        ->where('decision.reason', 'protect the BWI bank')
        ->where('decision.current_flight_id', n102dn())
        ->where('legs', fn ($legs) => collect($legs)->map(fn ($l) => [$l['kind'], $l['flight_number']])->all() === [
            ['selected', '2341'], ['cancelled', '1487'], ['cancelled', '1487'], ['cancelled', '574'], ['flown', '2590'],
        ])
        ->where('legs.4.is_target', true)
        ->where('legs.4.predicted_dep_delay', 0)
        ->where('legs.4.actual_dep_delay', 49)
        ->where('legs.4.origin_tz', 'America/New_York'));
});

it('shows a what-if decision with its longer chain', function () {
    decision(['delay' => 600, 'target' => null, 'action' => 'other']);

    $this->get('/decisions/'.pestDecisionId())->assertInertia(fn (Assert $page) => $page
        ->where('decision.what_if', true)
        ->where('decision.arr_delay_min', 600)
        ->where('legs.5.flight_number', '2950')
        ->where('legs.5.predicted_dep_delay', 0)
        ->where('legs.5.actual_dep_delay', 308));
});

it('returns not found for an unknown decision', function () {
    $this->get('/decisions/999999999')->assertNotFound()->assertInertia(fn (Assert $page) => $page->component('NotFound'));
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./vendor/bin/pest tests/Feature/DecisionTest.php`
Expected: the two changed tests FAIL (redirect is `/flights/...`, not `/decisions/...`), the four new ones FAIL (`/decisions` hits the fallback, so the component is `NotFound`), and the rest PASS.

- [ ] **Step 3: Write `index`, `show` and the new redirect**

Replace `web/app/Http/Controllers/DecisionController.php` with:

```php
<?php

namespace App\Http\Controllers;

use App\Support\Days;
use Illuminate\Database\QueryException;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\DB;
use Illuminate\Validation\Rule;
use Illuminate\Validation\ValidationException;
use Inertia\Inertia;

class DecisionController
{
    // Same set as the check constraint on app.decision.action (migration 022)
    public const ACTIONS = ['accept_delay', 'hold_departure', 'swap_aircraft', 'cancel_leg', 'other'];

    public function index()
    {
        // shortcut: every decision on one page; paginate once the log holds a few hundred
        return Inertia::render('Decisions', [
            'decisions' => DB::select('select * from decision_review order by recorded_at desc, decision_id desc'),
        ]);
    }

    public function show(int $decision)
    {
        $d = DB::selectOne('select * from decision_review where decision_id = ?', [$decision]);
        if (! $d) {
            return Days::missing("No decision {$decision}.");
        }

        // The timezone comes from the flight as rebuilt; a leg no longer found has none and shows UTC
        $legs = DB::select(
            "select l.*, t.origin_tz from decision_legs l left join tail_legs t on t.flight_id = l.current_flight_id
             where l.decision_id = ? order by l.depth, l.kind = 'flown', l.sched_dep_utc",
            [$decision]);

        return Inertia::render('Decision', ['decision' => $d, 'legs' => $legs]);
    }

    public function store(Request $request, int $flight)
    {
        $given = $request->validate([
            'action' => ['required', Rule::in(self::ACTIONS)],
            'target' => ['nullable', 'integer', 'prohibited_if:action,accept_delay'],
            'delay' => ['nullable', 'integer', 'between:0,1440'],
            'reason' => ['required', 'string', 'max:2000'],
            'author' => ['required', 'string', 'max:100'],
        ]);

        try {
            // A savepoint when a transaction is already open, so a refusal leaves it usable
            $id = DB::transaction(fn () => DB::selectOne('select record_decision(?, ?, ?, ?, ?, ?) as id', [
                $flight, $given['delay'] ?? null, $given['action'], $given['target'] ?? null, $given['reason'], $given['author'],
            ])->id);
        } catch (QueryException $e) {
            // record_decision refuses with a plain RAISE (P0001); anything else is a real error
            if ($e->getCode() !== 'P0001') {
                throw $e;
            }
            preg_match('/ERROR:\s+([^\n]+)/', $e->getMessage(), $m);
            throw ValidationException::withMessages(['decision' => $m[1] ?? 'The decision was refused.']);
        }

        return redirect("/decisions/{$id}");
    }
}
```

In `web/routes/web.php`, add after the `POST /flights/{flight}/decisions` route:

```php
Route::get('/decisions', [DecisionController::class, 'index']);
Route::get('/decisions/{decision}', [DecisionController::class, 'show'])->where('decision', '\d+');
```

- [ ] **Step 4: Run the Pest tests to verify they pass**

Run: `./vendor/bin/pest tests/Feature/DecisionTest.php`
Expected: the two redirect tests and the not-found test PASS. The three page tests still FAIL, now only with `Inertia page component file [Decisions] does not exist` (or `[Decision]`), because Inertia's `testing.ensure_pages_exist` is on. They pass once Steps 7-8 add the pages, which Step 10 checks.

- [ ] **Step 5: Write the failing JS test**

Append to `web/resources/js/lib/decisions.test.js`, and add `HINDSIGHT, outcome` to its import from `./decisions.js`:

```js
test('outcome is the match label, or the chain totals without a target', () => {
    assert.equal(outcome({ match_label: 'airline did the same' }), 'airline did the same');
    assert.equal(
        outcome({ match_label: null, predicted_at_risk: 0, actually_late: 1, cancelled: 3 }),
        '0 predicted at risk · 1 left 15+ min late · 3 cancelled',
    );
});

test('the hindsight caveat names both limits', () => {
    assert.match(HINDSIGHT, /not a test of foresight/);
    assert.match(HINDSIGHT, /swap can never be confirmed/);
});
```

Run: `npm test`
Expected: FAIL with `SyntaxError: The requested module './decisions.js' does not provide an export named 'HINDSIGHT'`.

- [ ] **Step 6: Add `HINDSIGHT` and `outcome` to `lib/decisions.js`**

Append to `web/resources/js/lib/decisions.js`:

```js
export const HINDSIGHT =
    'Decisions are logged with the July 2024 outcome already visible on the flight page, so this is an audit trail, not a test of foresight. BTS records only the tail that flew, so a swap can never be confirmed.';

// The target's match label, or the chain totals when the decision has no target
export function outcome(d) {
    return d.match_label ?? `${d.predicted_at_risk} predicted at risk · ${d.actually_late} left 15+ min late · ${d.cancelled} cancelled`;
}
```

Run: `npm test`
Expected: all PASS.

- [ ] **Step 7: Write `Decisions.vue`**

Create `web/resources/js/pages/Decisions.vue`:

```vue
<script setup>
import { Head, Link } from '@inertiajs/vue3';
import { ATL_TZ, localDate, localTime, utcTitle } from '../lib/time.js';
import { ACTIONS, HINDSIGHT, outcome } from '../lib/decisions.js';

defineProps({ decisions: Array });
const logged = (v) => `${localDate(v, ATL_TZ)} ${localTime(v, ATL_TZ)}`;
const cell = 'px-2 py-1';
</script>

<template>
    <Head title="Decisions" />
    <main class="mx-auto max-w-7xl space-y-4 px-4 py-6">
        <header class="flex flex-wrap items-center gap-4">
            <h1 class="mr-auto text-xl font-semibold">Decision log</h1>
            <Link href="/day/2024-07-19" class="text-sm text-sky-700 underline">July 2024 history →</Link>
        </header>
        <p class="text-xs text-slate-500">{{ HINDSIGHT }}</p>

        <p v-if="!decisions.length" class="text-slate-500">No decisions yet. Log one from any flight's impact page.</p>
        <div v-else class="overflow-x-auto rounded border border-slate-200 bg-white">
            <table class="w-full text-left text-sm">
                <thead class="bg-slate-100 text-xs uppercase text-slate-600">
                    <tr>
                        <th :class="cell">Logged (Atlanta)</th><th :class="cell">Author</th><th :class="cell">Flight</th>
                        <th :class="cell">Action</th><th :class="cell">Target</th><th :class="cell">Outcome</th>
                    </tr>
                </thead>
                <tbody>
                    <tr v-for="d in decisions" :key="d.decision_id" class="border-t border-slate-100 align-top">
                        <td :class="cell" class="whitespace-nowrap">{{ logged(d.recorded_at) }}</td>
                        <td :class="cell">{{ d.author }}</td>
                        <td :class="cell" class="whitespace-nowrap">
                            <Link :href="`/decisions/${d.decision_id}`" class="text-sky-700 underline">{{ d.carrier }} {{ d.flight_number }} {{ d.origin }} → {{ d.dest }}</Link>
                            <span class="text-slate-500"> {{ utcTitle(d.sched_dep_utc) }}</span>
                            <span v-if="d.what_if" class="text-slate-500"> · what-if {{ d.arr_delay_min }} min</span>
                        </td>
                        <td :class="cell">{{ ACTIONS[d.action] }}</td>
                        <td :class="cell" class="whitespace-nowrap">
                            <template v-if="d.target_flight_number">{{ d.target_carrier }} {{ d.target_flight_number }} {{ d.target_origin }} → {{ d.target_dest }}</template>
                            <span v-else class="text-slate-500">none</span>
                        </td>
                        <td :class="cell">{{ outcome(d) }}</td>
                    </tr>
                </tbody>
            </table>
        </div>
    </main>
</template>
```

- [ ] **Step 8: Write `Decision.vue`**

Create `web/resources/js/pages/Decision.vue`:

```vue
<script setup>
import { computed } from 'vue';
import { Head, Link } from '@inertiajs/vue3';
import { ATL_TZ, localDate, localTime, utcTitle } from '../lib/time.js';
import { ACTIONS, HINDSIGHT, outcome } from '../lib/decisions.js';

const props = defineProps({ decision: Object, legs: Array });
const d = props.decision;
const flightHref = computed(() => `/flights/${d.current_flight_id}${d.what_if ? `?delay=${d.arr_delay_min}` : ''}`);
// A leg no longer found after a rebuild has no timezone, so it shows UTC
const sched = (l) => (l.origin_tz ? `${localDate(l.sched_dep_utc, l.origin_tz)} ${localTime(l.sched_dep_utc, l.origin_tz)}` : utcTitle(l.sched_dep_utc));
const minutes = (n) => (n === null || n === undefined ? '—' : `${n} min`);
const cell = 'px-2 py-1';
</script>

<template>
    <Head :title="`Decision ${d.decision_id}`" />
    <main class="mx-auto max-w-7xl space-y-4 px-4 py-6">
        <header class="space-y-1">
            <Link href="/decisions" class="text-sm text-sky-700 underline">← Decision log</Link>
            <h1 class="text-xl font-semibold">{{ ACTIONS[d.action] }} · {{ d.carrier }} {{ d.flight_number }} {{ d.origin }} → {{ d.dest }}</h1>
            <p class="text-sm text-slate-600">
                {{ d.author }}, {{ localDate(d.recorded_at, ATL_TZ) }} {{ localTime(d.recorded_at, ATL_TZ) }} Atlanta time.
                <template v-if="d.what_if">Logged against a {{ d.arr_delay_min }}-min what-if arrival delay.</template>
                <template v-else-if="d.arr_delay_min !== null">Logged against the actual {{ d.arr_delay_min }}-min arrival delay.</template>
                <template v-else>Logged against the actual landing of a diversion.</template>
                Min turn at p{{ d.percentile }}.
            </p>
            <Link v-if="d.flight_found" :href="flightHref" class="text-sm text-sky-700 underline">Open the flight's impact page →</Link>
        </header>

        <blockquote class="border-l-4 border-slate-300 pl-3 text-sm">{{ d.reason }}</blockquote>

        <section class="rounded border border-slate-200 bg-white p-3 text-sm">
            <h2 class="font-semibold">Outcome</h2>
            <p v-if="d.target_flight_number">Target {{ d.target_carrier }} {{ d.target_flight_number }} {{ d.target_origin }} → {{ d.target_dest }}: {{ outcome(d) }}.</p>
            <p v-else-if="!d.flight_found">{{ outcome(d) }}.</p>
            <p>Chain: {{ d.predicted_at_risk }} predicted at risk · {{ d.actually_late }} left 15+ min late · {{ d.cancelled }} cancelled.</p>
        </section>

        <p class="text-xs text-slate-500">{{ HINDSIGHT }}</p>

        <div class="overflow-x-auto rounded border border-slate-200 bg-white">
            <table class="w-full whitespace-nowrap text-left text-sm">
                <thead class="bg-slate-100 text-xs uppercase text-slate-600">
                    <tr>
                        <th :class="cell">Leg</th><th :class="cell">Flight</th><th :class="cell">Route</th><th :class="cell">Sched dep (local)</th>
                        <th :class="cell">Predicted dep delay (frozen)</th><th :class="cell">Actual dep delay</th>
                    </tr>
                </thead>
                <tbody>
                    <tr v-for="l in legs" :key="`${l.kind}-${l.flight_id}`" class="border-t border-slate-100" :class="[l.is_target && 'bg-sky-50', l.kind === 'cancelled' && 'text-slate-500']">
                        <td :class="cell">{{ l.depth }}</td>
                        <td :class="cell">{{ l.carrier }} {{ l.flight_number }} <span v-if="l.is_target" class="badge bg-sky-100 text-sky-900">target</span></td>
                        <td :class="cell">{{ l.origin }} → {{ l.dest }}</td>
                        <td :class="cell" :title="utcTitle(l.sched_dep_utc)">{{ sched(l) }}</td>
                        <td :class="cell">
                            <template v-if="l.kind === 'selected'">decided on</template>
                            <template v-else-if="l.kind === 'cancelled'">cancelled in the gap, not predicted</template>
                            <span v-else-if="l.at_risk" class="badge bg-amber-100 text-amber-900">{{ l.predicted_dep_delay }} min · at risk</span>
                            <template v-else-if="l.predicted_dep_delay !== null">{{ l.predicted_dep_delay }} min</template>
                            <span v-else class="text-slate-500">not predicted ({{ l.stop_reason }})</span>
                        </td>
                        <td :class="cell">
                            <template v-if="l.current_flight_id === null">flight not found after rebuild</template>
                            <template v-else-if="l.actual_cancelled">cancelled</template>
                            <template v-else>{{ minutes(l.actual_dep_delay) }}</template>
                        </td>
                    </tr>
                </tbody>
            </table>
        </div>
        <p v-if="d.what_if" class="text-xs text-slate-500">Actual delays followed the real arrival, not the what-if.</p>
    </main>
</template>
```

- [ ] **Step 9: Link the earlier decisions and the nav**

In `web/resources/js/components/DecisionPanel.vue`, change the import line `import { useForm } from '@inertiajs/vue3';` to:

```js
import { Link, useForm } from '@inertiajs/vue3';
```

and replace the `<li v-for="d in decisions" ...>` element with:

```vue
                <li v-for="d in decisions" :key="d.decision_id" class="py-1">
                    <Link :href="`/decisions/${d.decision_id}`" class="text-sky-700 underline">{{ recorded(d) }}</Link> · {{ d.author }} · {{ ACTIONS[d.action] }}<template v-if="d.target_flight_number">: {{ d.target_carrier }} {{ d.target_flight_number }} {{ d.target_origin }} → {{ d.target_dest }}</template><template v-if="d.match_label"> · {{ d.match_label }}</template>
                </li>
```

In `web/resources/js/pages/HubDay.vue`, after `<Link href="/live" class="text-sm text-sky-700 underline">ATL live →</Link>`, add:

```vue
            <Link href="/decisions" class="text-sm text-sky-700 underline">Decisions →</Link>
```

- [ ] **Step 10: Run every suite**

Run: `./vendor/bin/pest && npm test && npm run build`
Expected: all PASS, including the three page tests from Step 1, and the build has no Vue compile errors.

- [ ] **Step 11: Commit**

```bash
git add web/app/Http/Controllers/DecisionController.php web/routes/web.php web/resources/js/lib/decisions.js web/resources/js/lib/decisions.test.js web/resources/js/pages/Decisions.vue web/resources/js/pages/Decision.vue web/resources/js/components/DecisionPanel.vue web/resources/js/pages/HubDay.vue web/tests/Feature/DecisionTest.php
git commit -m "feat: decision log and decision review pages"
```

---

### Task 2: Walkthrough, screenshots and close-out

**Files:**
- Modify: `web/scripts/screenshots.sh`
- Create: `docs/screenshots/decisions.png`, `docs/screenshots/decision-N102DN-what-if.png`; regenerate `docs/screenshots/flight-N102DN-2024-07-19.png`
- Modify: `docs/phase-5-plan.md` (Notes), `README.md`, `docs/roadmap.md`, `CLAUDE.md`

**Interfaces:**
- Consumes: the pages from Task 1 and `record_decision`.
- Produces: three kept decisions in the real log, by author `walkthrough`, and the screenshots the README links.

- [ ] **Step 1: Record the walkthrough's three decisions**

These stay in the log as portfolio data. They're recorded as the app's role, through the same function the form calls:

```bash
psql -h localhost -U flightops_app flightops <<'EOF'
\set f 371994
select app_read.record_decision(:f, null, 'accept_delay', null,
  'Inbound 5 h late on the outage day. Next ATL departure is 22:50, so let the turn absorb it.', 'walkthrough') as accept;
select app_read.record_decision(:f, null, 'cancel_leg',
  (select flight_id from app_read.propagate(:f) where flight_number = '2590'),
  'Protect the evening bank instead: cancel ATL-BWI and reposition later.', 'walkthrough') as cancel;
select app_read.record_decision(:f, 600, 'hold_departure',
  (select flight_id from app_read.propagate(:f, 600) where flight_number = '2950'),
  'If the inbound slips to 10 h, hold BWI-ATL for the aircraft rather than swap.', 'walkthrough') as hold;
EOF
```

Expected: three ids printed. Write down the `hold` id for Step 3.

- [ ] **Step 2: Check the review against the known values**

Run:

```bash
psql -h localhost flightops -c "select decision_id, action, what_if, target_flight_number, predicted_at_risk, actually_late, cancelled, match_label from app_read.decision_review where author = 'walkthrough' order by decision_id"
```

Expected:

| action | what_if | target | at risk | late | cancelled | match_label |
|---|---|---|---|---|---|---|
| accept_delay | f | | 0 | 1 | 3 | |
| cancel_leg | f | 2590 | 0 | 1 | 3 | airline flew it, +49 min |
| hold_departure | t | 2950 | 1 | 2 | 3 | flown, +308 min vs predicted +0 |

If a row differs, stop and investigate before taking screenshots.

- [ ] **Step 3: Add the screenshots**

In `web/scripts/screenshots.sh`, append after the `live` shot, replacing `<hold-id>` with the id from Step 1:

```bash
shot decisions /decisions 1440,700
# shortcut: the walkthrough's what-if decision by id; look it up by author 'walkthrough' if the log is recreated
shot decision-N102DN-what-if /decisions/<hold-id> 1440,1000
```

Start the server and take the shots, then put back the screenshots this step isn't meant to change. The live shot would otherwise be replaced by a stale banner:

```bash
cd web && php artisan serve --port=8010   # in the background
scripts/screenshots.sh http://127.0.0.1:8010
cd .. && git checkout -- docs/screenshots/hub-2024-07-19.png docs/screenshots/hub-2024-07-10.png docs/screenshots/tail-N102DN-2024-07-19.png docs/screenshots/tail-N181PQ-2024-07-19.png docs/screenshots/live.png
```

Open `docs/screenshots/decisions.png`, `docs/screenshots/decision-N102DN-what-if.png` and `docs/screenshots/flight-N102DN-2024-07-19.png`, and check that:
- the log shows three rows with their outcomes;
- the what-if page highlights 2950 as the target, predicted 0 min, actual 308 min;
- the flight page ends with the decision panel listing the three decisions.

Stop the server.

- [ ] **Step 4: Write the notes in `docs/phase-5-plan.md`**

Add these rows under the Notes table header, with the measured values from Steps 1-3 and from steps 1-2 of the phase:

```markdown
| Recording a decision is fast enough for a form post | `record_decision` on N102DN's DEN→ATL: 92 ms, including `propagate` and the 5-leg snapshot | No async write or queue |
| The natural key is unique for July | 634,613 flights, 634,613 distinct (carrier, flight number, origin, scheduled departure) | Re-matching after a rebuild needs no tiebreak |
| Inertia v3 sends the CSRF token by default | Its client reads `XSRF-TOKEN` and sends `X-XSRF-TOKEN`. A replayed POST without it got 419, with it 302 | No CSRF setup in the app |
| The review shows what the model misses | Walkthrough on N102DN, July 19: accepting the 316-min delay predicted 0 legs at risk, while 1 left late and 3 were cancelled. A 600-min what-if hold on BWI→ATL 2950 predicted +0; it left 308 min late with no late-aircraft minutes | The cancellation-risk phase the case study recommends would have something to score against |
```

- [ ] **Step 5: Update `README.md`**

Replace the sentence `The app reads through a database role that can only select from a schema of views, so the rules for days, statuses and labels live in tested SQL, and the app cannot write.` with:

```markdown
The app reads through a database role that can only select from a schema of views, so the rules for days, statuses and labels live in tested SQL. Its one write is logging a decision, through a single database function.
```

Insert this section after the "Decision support" section and before "How it works":

```markdown
## Decision log

![A logged what-if decision on N102DN](docs/screenshots/decision-N102DN-what-if.png)

From any flight's impact page, a controller can log a decision (accept the delay, hold a departure, swap aircraft, cancel a leg) with a reason. The predicted chain is frozen with it. The log puts each decision next to what BTS shows happened: whether the airline cancelled the target leg, and how late it actually left against the frozen prediction. The log is append-only and survives a rebuild of the data, re-matching each flight on carrier, flight number, origin and scheduled departure. Decisions are made with the July outcome already visible, so this is an audit trail, not a test of foresight.
```

In the last paragraph, change `live data, operator decisions, a second hub and containers.` to `a second hub and containers.`

- [ ] **Step 6: Update `docs/roadmap.md` and `CLAUDE.md`**

In `docs/roadmap.md`, change the row `| 5. Operator workflow | ... | Write-backs stored in \`app\` |` so the last cell reads `See \`phase-5-plan.md\`. Writes go through one SQL function`, and change `Phases 4-6 are optional, and phase 4 is built.` to `Phases 4-6 are optional, and phases 4 and 5 are built.`

In `CLAUDE.md`'s Status section:
- **Current phase:** `5 complete on branch \`phase-5\`: decisions are logged from FlightImpact through \`app_read.record_decision\` (migration 022) and reviewed on \`/decisions\`.`
- **Next action:** `ask the user whether to merge \`phase-5\` into \`main\`, then whether to brainstorm the cancellation-risk phase or phase 6 (second hub).`
- **Built so far:** add `phase 5` to the list of phases, and `Decisions and Decision` to the list of pages.

In `CLAUDE.md`'s Docs section, change `` `docs/phase-1-plan.md` to `docs/phase-4-plan.md` `` to `` `docs/phase-1-plan.md` to `docs/phase-5-plan.md` ``. In its Stack section, change `It reads from \`ontology\` and \`dq\` and never writes to them.` to `It reads from \`ontology\` and \`dq\` through \`app_read\`, and never writes to them. Its only write is \`app_read.record_decision\`, into \`app\`.`

- [ ] **Step 7: Check the phase's "Done means"**

Run from `pipelines/`: `uv run --env-file ../.env pytest`, then from `web/`: `./vendor/bin/pest && npm test && npm run build`.
Expected: all PASS.

Then check each line of "Done means" in `docs/phase-5-plan.md`:
- the suites pass (just run);
- a decision logged through the app appears on `/decisions` with its match label (the step 2 smoke test and Step 3's screenshot);
- a full `build` leaves the log intact and re-matched. Run `uv run --env-file ../.env python -m flightops build` from `pipelines/`, then repeat Step 2's query and expect the same three rows with `flight_found` true;
- `DECISIONS.md` has the four entries.

- [ ] **Step 8: Commit**

```bash
git add web/scripts/screenshots.sh docs/screenshots/decisions.png docs/screenshots/decision-N102DN-what-if.png docs/screenshots/flight-N102DN-2024-07-19.png docs/phase-5-plan.md README.md docs/roadmap.md CLAUDE.md
git commit -m "docs: phase 5 walkthrough, screenshots and status"
```
