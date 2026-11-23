# Phase 5 Step 2: Decision Form on FlightImpact Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** a controller can log a decision from a flight's FlightImpact page and see earlier decisions on that flight, through `POST /flights/{flight}/decisions` calling `app_read.record_decision`.

**Architecture:** `DecisionController::store` validates the form for friendly messages, then calls `record_decision` inside `DB::transaction`. That's a savepoint when a test already holds a transaction, so a refusal doesn't abort it. A `P0001` refusal from the function becomes a `decision` form error. FlightImpact gets a `decisions` prop from `decision_review` and a `DecisionPanel` component. Small pure helpers (action labels, target labels, the remembered author) live in `resources/js/lib/decisions.js` with node tests.

**Tech Stack:** Laravel 12, Inertia v3 with Vue 3 (`useForm`), Tailwind 4, Pest, `node --test`.

## Global Constraints

- The app connects as `flightops_app` with `DB_SEARCH_PATH=app_read`. It writes only by calling `record_decision`. It has no rights on `app`.
- Actions are exactly `accept_delay`, `hold_departure`, `swap_aircraft`, `cancel_leg`, `other`, in that order (the check constraint in `db/migrations/022_decisions.sql`).
- `record_decision(p_flight_id, p_arr_delay_min, p_action, p_target_flight_id, p_reason, p_author)` returns the new `decision_id`. `p_arr_delay_min` is NULL unless the page shows a what-if. Its refusals are SQLSTATE `P0001` with messages such as `The target is not a later leg in this chain.`
- Pest tests run against the loaded July database and must leave no rows behind: `DecisionTest.php` uses `DatabaseTransactions`.
- Known July values: N102DN's DEN→ATL 2341 on 2024-07-19 arrived 316 min late. Its chain is cancelled 1487, 1487, 574, then flown ATL→BWI 2590 (predicted +0, actual dep +49). With a 600-min what-if, 2590 is predicted +63.
- `localStorage` reads and writes are wrapped in try/catch, and the page works without it.
- Commands run from `web/`: `./vendor/bin/pest`, `npm test`, `npm run build`.

---

### Task 1: `POST /flights/{flight}/decisions`

**Files:**
- Create: `web/app/Http/Controllers/DecisionController.php`
- Modify: `web/routes/web.php`
- Modify: `web/tests/Pest.php` (gains `n102dn()`)
- Modify: `web/tests/Feature/FlightImpactTest.php` (loses `n102dn()`)
- Modify: `web/tests/Feature/ReadOnlyTest.php`
- Create: `web/tests/Feature/DecisionTest.php`

**Interfaces:**
- Consumes: `app_read.record_decision`, `app_read.decision_review`, `app_read.decision_legs`, `app_read.propagate` (step 1 and migration 019).
- Produces: route `POST /flights/{flight}/decisions` with fields `action` (required), `target` (nullable flight id, prohibited with `accept_delay`), `delay` (nullable integer 0-1440, sent only for a what-if), `reason` (required, max 2000), `author` (required, max 100). On success it redirects to `/flights/{flight}`, or `/flights/{flight}?delay=N` for a what-if. A database refusal comes back as the session error `decision`. `DecisionController::ACTIONS` is the action list. Test helpers `n102dn(): int` (in `Pest.php`), and `bwi(): int` and `decision(array $fields = []): TestResponse` (in `DecisionTest.php`).

- [ ] **Step 1: Move `n102dn()` into `tests/Pest.php`**

Delete the `n102dn()` function from `web/tests/Feature/FlightImpactTest.php` (keep its `use` lines) and append it to `web/tests/Pest.php`, so `DecisionTest.php` can use it when run alone:

```php

function n102dn(): int
{
    // DEN->ATL on July 19, 316 min late; looked up, since flight_id is a surrogate
    return Illuminate\Support\Facades\DB::selectOne("select flight_id from tail_legs where tail_number = 'N102DN' and leg_day = '2024-07-19' and origin = 'DEN'")->flight_id;
}
```

Run: `./vendor/bin/pest tests/Feature/FlightImpactTest.php`
Expected: PASS, the same 10 tests as before.

- [ ] **Step 2: Write the failing tests**

Create `web/tests/Feature/DecisionTest.php`:

```php
<?php

use Illuminate\Foundation\Testing\DatabaseTransactions;
use Illuminate\Support\Facades\DB;
use Illuminate\Testing\TestResponse;

// Every test rolls back, so the real decision log never holds test rows.
uses(DatabaseTransactions::class);

function bwi(): int
{
    // ATL->BWI 2590, the flown leg after N102DN's 316-min arrival
    return DB::selectOne("select flight_id from propagate(?) where kind = 'flown' and flight_number = '2590'", [n102dn()])->flight_id;
}

function decision(array $fields = []): TestResponse
{
    return test()->post('/flights/'.n102dn().'/decisions', array_merge(
        ['action' => 'cancel_leg', 'target' => bwi(), 'reason' => 'protect the BWI bank', 'author' => 'pest'],
        $fields,
    ));
}

function pestDecisions(): int
{
    return DB::selectOne("select count(*) as n from decision_review where author = 'pest'")->n;
}

it('records a decision with its frozen chain and returns to the flight', function () {
    decision()->assertRedirect('/flights/'.n102dn());

    $d = DB::selectOne("select * from decision_review where author = 'pest'");
    expect($d->action)->toBe('cancel_leg')
        ->and($d->target_flight_number)->toBe('2590')
        ->and($d->arr_delay_min)->toBe(316)
        ->and($d->what_if)->toBeFalse()
        ->and($d->match_label)->toBe('airline flew it, +49 min');
    expect(DB::selectOne('select count(*) as n from decision_legs where decision_id = ?', [$d->decision_id])->n)->toBe(5);
});

it('freezes a what-if delay and returns to the what-if', function () {
    decision(['delay' => 600])->assertRedirect('/flights/'.n102dn().'?delay=600');

    $d = DB::selectOne("select arr_delay_min, what_if, target_predicted_dep_delay from decision_review where author = 'pest'");
    expect([$d->arr_delay_min, $d->what_if, $d->target_predicted_dep_delay])->toBe([600, true, 63]);
});

it('rejects a form that fails validation, recording nothing', function (array $fields, string $field) {
    decision($fields)->assertSessionHasErrors($field);
    expect(pestDecisions())->toBe(0);
})->with([
    'blank reason' => [['reason' => '  '], 'reason'],
    'blank author' => [['author' => ''], 'author'],
    'unknown action' => [['action' => 'ground_stop'], 'action'],
    'target on accept' => [['action' => 'accept_delay'], 'target'],
    'delay out of range' => [['delay' => 1441], 'delay'],
]);

it('shows a database refusal as a form error, recording nothing', function () {
    decision(['target' => n102dn()])->assertSessionHasErrors(['decision' => 'The target is not a later leg in this chain.']);
    expect(pestDecisions())->toBe(0);
});
```

Append to `web/tests/Feature/ReadOnlyTest.php`:

```php

it('cannot write to the decision log directly', function () {
    expect(fn () => DB::statement("insert into app.decision (flight_id, what_if, percentile, action, reason, author) values (1, false, 10, 'other', 'x', 'x')"))
        ->toThrow(QueryException::class);
});
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `./vendor/bin/pest tests/Feature/DecisionTest.php tests/Feature/ReadOnlyTest.php`
Expected: the `ReadOnlyTest` cases PASS (the role already has no rights on `app`). Every `DecisionTest` case FAILS: the POST hits no route, so the redirect and session-error assertions fail on a 405 or 404 response.

- [ ] **Step 4: Write the controller and route**

Create `web/app/Http/Controllers/DecisionController.php`:

```php
<?php

namespace App\Http\Controllers;

use Illuminate\Database\QueryException;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\DB;
use Illuminate\Validation\Rule;
use Illuminate\Validation\ValidationException;

class DecisionController
{
    // Same set as the check constraint on app.decision.action (migration 022)
    public const ACTIONS = ['accept_delay', 'hold_departure', 'swap_aircraft', 'cancel_leg', 'other'];

    public function store(Request $request, int $flight)
    {
        $given = $request->validate([
            'action' => ['required', Rule::in(self::ACTIONS)],
            'target' => ['nullable', 'integer', 'prohibited_if:action,accept_delay'],
            'delay' => ['nullable', 'integer', 'between:0,1440'],
            'reason' => ['required', 'string', 'max:2000'],
            'author' => ['required', 'string', 'max:100'],
        ]);
        $delay = $given['delay'] ?? null;

        try {
            // A savepoint when a transaction is already open, so a refusal leaves it usable
            DB::transaction(fn () => DB::selectOne('select record_decision(?, ?, ?, ?, ?, ?) as id', [
                $flight, $delay, $given['action'], $given['target'] ?? null, $given['reason'], $given['author'],
            ]));
        } catch (QueryException $e) {
            // record_decision refuses with a plain RAISE (P0001); anything else is a real error
            if ($e->getCode() !== 'P0001') {
                throw $e;
            }
            preg_match('/ERROR:\s+([^\n]+)/', $e->getMessage(), $m);
            throw ValidationException::withMessages(['decision' => $m[1] ?? 'The decision was refused.']);
        }

        return redirect("/flights/{$flight}".($delay !== null ? "?delay={$delay}" : ''));
    }
}
```

In `web/routes/web.php`, add the import and the route after the `/flights/{flight}` route:

```php
use App\Http\Controllers\DecisionController;
```

```php
Route::post('/flights/{flight}/decisions', [DecisionController::class, 'store'])->where('flight', '\d+');
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `./vendor/bin/pest tests/Feature/DecisionTest.php tests/Feature/ReadOnlyTest.php`
Expected: all PASS (8 in `DecisionTest`, counting the 5 dataset rows, and 4 in `ReadOnlyTest`).

Run: `psql -h localhost flightops -Atc "select count(*) from app.decision where author = 'pest'"`
Expected: `0`.

- [ ] **Step 6: Commit**

```bash
git add web/app/Http/Controllers/DecisionController.php web/routes/web.php web/tests/Pest.php web/tests/Feature/FlightImpactTest.php web/tests/Feature/ReadOnlyTest.php web/tests/Feature/DecisionTest.php
git commit -m "feat: POST a decision through record_decision"
```

---

### Task 2: Decision panel on FlightImpact

**Files:**
- Create: `web/resources/js/lib/decisions.js`
- Create: `web/resources/js/lib/decisions.test.js`
- Create: `web/resources/js/components/DecisionPanel.vue`
- Modify: `web/resources/js/pages/FlightImpact.vue`
- Modify: `web/app/Http/Controllers/FlightImpactController.php`
- Modify: `web/tests/Feature/DecisionTest.php` (append)
- Modify: `DECISIONS.md` (append)

**Interfaces:**
- Consumes: the route and `decision()` test helper from Task 1, `localDate`, `localTime` and `ATL_TZ` from `resources/js/lib/time.js`, and `decision_review` columns `decision_id, recorded_at, author, action, target_carrier, target_flight_number, target_origin, target_dest, match_label, current_flight_id`.
- Produces: FlightImpact prop `decisions` (array, newest first). `lib/decisions.js` exports `ACTIONS` (object, action → label), `rememberedAuthor(storage = globalThis.localStorage): string`, `rememberAuthor(author, storage = globalThis.localStorage): void` and `targetLabel(leg): string`. Component `DecisionPanel` with props `flightId: Number, legs: Array, whatIfDelay: Number|null, decisions: Array`. Step 3 reuses `ACTIONS`.

- [ ] **Step 1: Write the failing JS tests**

Create `web/resources/js/lib/decisions.test.js`:

```js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ACTIONS, rememberAuthor, rememberedAuthor, targetLabel } from './decisions.js';

test('actions match the database check constraint, in order', () => {
    assert.deepEqual(Object.keys(ACTIONS), ['accept_delay', 'hold_departure', 'swap_aircraft', 'cancel_leg', 'other']);
});

test('the author round-trips through storage', () => {
    const map = new Map();
    const storage = { getItem: (k) => map.get(k) ?? null, setItem: (k, v) => map.set(k, v) };
    assert.equal(rememberedAuthor(storage), '');
    rememberAuthor('duty controller', storage);
    assert.equal(rememberedAuthor(storage), 'duty controller');
});

test('storage that throws or is missing leaves the author empty', () => {
    const blocked = {
        getItem() { throw new Error('blocked'); },
        setItem() { throw new Error('blocked'); },
    };
    assert.equal(rememberedAuthor(blocked), '');
    assert.doesNotThrow(() => rememberAuthor('x', blocked));
    assert.equal(rememberedAuthor(null), '');
    assert.doesNotThrow(() => rememberAuthor('x', null));
});

test('a target is labelled with its depth, route and local departure', () => {
    const leg = { depth: 2, kind: 'flown', carrier: 'DL', flight_number: '2590', origin: 'ATL', dest: 'BWI', sched_dep_utc: '2024-07-20 02:50:00+00', origin_tz: 'America/New_York' };
    assert.equal(targetLabel(leg), '2 · DL 2590 ATL → BWI · Jul 19 22:50');
    assert.equal(targetLabel({ ...leg, kind: 'cancelled' }), '2 · DL 2590 ATL → BWI · Jul 19 22:50 · cancelled');
});
```

Run: `npm test`
Expected: FAIL with `Cannot find module '.../resources/js/lib/decisions.js'`.

- [ ] **Step 2: Write `lib/decisions.js`**

Create `web/resources/js/lib/decisions.js`:

```js
import { localDate, localTime } from './time.js';

// Same set and order as app.decision's check constraint (migration 022)
export const ACTIONS = {
    accept_delay: 'Accept the delay',
    hold_departure: 'Hold a departure',
    swap_aircraft: 'Swap aircraft',
    cancel_leg: 'Cancel a leg',
    other: 'Other',
};

const KEY = 'flightops.author';

// Storage can be missing or throw (private window, blocked site data); the field then starts empty.
export function rememberedAuthor(storage = globalThis.localStorage) {
    try {
        return storage?.getItem(KEY) ?? '';
    } catch {
        return '';
    }
}

export function rememberAuthor(author, storage = globalThis.localStorage) {
    try {
        storage?.setItem(KEY, author);
    } catch {
        // not remembered; the form still works
    }
}

export function targetLabel(leg) {
    const when = `${localDate(leg.sched_dep_utc, leg.origin_tz)} ${localTime(leg.sched_dep_utc, leg.origin_tz)}`;
    return `${leg.depth} · ${leg.carrier} ${leg.flight_number} ${leg.origin} → ${leg.dest} · ${when}${leg.kind === 'cancelled' ? ' · cancelled' : ''}`;
}
```

Run: `npm test`
Expected: all PASS, including the existing `flights`, `legs`, `live`, `time` and `timeline` tests.

- [ ] **Step 3: Write the failing Pest test for the `decisions` prop**

Append to `web/tests/Feature/DecisionTest.php`, adding `use Inertia\Testing\AssertableInertia as Assert;` to its `use` lines:

```php
it('lists earlier decisions on the flight, newest first', function () {
    decision(['action' => 'hold_departure']);
    decision(['action' => 'swap_aircraft', 'reason' => 'second look']);

    $this->get('/flights/'.n102dn())->assertOk()->assertInertia(fn (Assert $page) => $page
        ->component('FlightImpact')
        ->where('decisions.0.action', 'swap_aircraft')
        ->where('decisions.0.author', 'pest')
        ->where('decisions.0.target_flight_number', '2590')
        ->where('decisions.0.match_label', 'this tail flew it, +49 min (swap not visible)')
        ->where('decisions.1.action', 'hold_departure'));
});
```

Run: `./vendor/bin/pest tests/Feature/DecisionTest.php`
Expected: the new test FAILS with `Property [decisions.0.action] does not exist`. The Task 1 tests PASS.

- [ ] **Step 4: Pass `decisions` from the controller**

In `web/app/Http/Controllers/FlightImpactController.php`, add to the array passed to `Inertia::render('FlightImpact', [...])`, after `'stop' => ...`:

```php
            // recorded_at is the transaction start, so decision_id breaks ties between decisions in one transaction
            'decisions' => DB::select(
                'select decision_id, recorded_at, author, action, target_carrier, target_flight_number, target_origin, target_dest, match_label
                 from decision_review where current_flight_id = ? order by recorded_at desc, decision_id desc',
                [$flight]),
```

Run: `./vendor/bin/pest tests/Feature/DecisionTest.php tests/Feature/FlightImpactTest.php`
Expected: all PASS.

- [ ] **Step 5: Write `DecisionPanel.vue`**

Create `web/resources/js/components/DecisionPanel.vue`:

```vue
<script setup>
import { watch } from 'vue';
import { useForm } from '@inertiajs/vue3';
import { ATL_TZ, localDate, localTime } from '../lib/time.js';
import { ACTIONS, rememberAuthor, rememberedAuthor, targetLabel } from '../lib/decisions.js';

const props = defineProps({ flightId: Number, legs: Array, whatIfDelay: Number, decisions: Array });

const form = useForm({ action: 'accept_delay', target: null, reason: '', author: rememberedAuthor() });
watch(() => form.action, (action) => {
    if (action === 'accept_delay') form.target = null;
});

const submit = () => {
    rememberAuthor(form.author);
    form
        // Read at submit time: the page's what-if can change while the form keeps its state
        .transform((data) => ({ ...data, delay: props.whatIfDelay }))
        .post(`/flights/${props.flightId}/decisions`, { preserveScroll: true, onSuccess: () => form.reset('reason', 'target') });
};
const recorded = (d) => `${localDate(d.recorded_at, ATL_TZ)} ${localTime(d.recorded_at, ATL_TZ)}`;
const field = 'rounded border border-slate-300 bg-white px-1 py-0.5';
</script>

<template>
    <section class="space-y-3 rounded border border-slate-200 bg-white p-3 text-sm">
        <h2 class="font-semibold">Log a decision</h2>
        <form class="grid gap-2 sm:grid-cols-2" @submit.prevent="submit">
            <label class="flex flex-col gap-1">Action
                <select v-model="form.action" :class="field">
                    <option v-for="(label, value) in ACTIONS" :key="value" :value="value">{{ label }}</option>
                </select>
            </label>
            <label v-if="form.action !== 'accept_delay'" class="flex flex-col gap-1">Target leg (optional)
                <select v-model="form.target" :class="field">
                    <option :value="null">None</option>
                    <option v-for="l in legs" :key="`${l.kind}-${l.flight_id}`" :value="l.flight_id">{{ targetLabel(l) }}</option>
                </select>
            </label>
            <label class="flex flex-col gap-1 sm:col-span-2">Reason
                <textarea v-model="form.reason" required rows="2" maxlength="2000" :class="field"></textarea>
            </label>
            <label class="flex flex-col gap-1">Your name
                <input v-model="form.author" required maxlength="100" autocomplete="name" :class="field" />
            </label>
            <div class="flex items-end">
                <button type="submit" :disabled="form.processing" class="rounded border border-slate-300 bg-white px-2 py-0.5">Log decision</button>
            </div>
            <p v-for="(message, key) in form.errors" :key="key" class="text-red-700 sm:col-span-2" role="alert">{{ message }}</p>
        </form>
        <p v-if="whatIfDelay !== null" class="text-xs text-slate-500">Logged against the {{ whatIfDelay }}-min what-if, with the chain shown above.</p>

        <div v-if="decisions.length" class="space-y-1">
            <h3 class="font-semibold">Earlier decisions on this flight</h3>
            <ul class="divide-y divide-slate-100">
                <li v-for="d in decisions" :key="d.decision_id" class="py-1">
                    {{ recorded(d) }} · {{ d.author }} · {{ ACTIONS[d.action] }}<template v-if="d.target_flight_number">: {{ d.target_carrier }} {{ d.target_flight_number }} {{ d.target_origin }} → {{ d.target_dest }}</template><template v-if="d.match_label"> · {{ d.match_label }}</template>
                </li>
            </ul>
        </div>
    </section>
</template>
```

- [ ] **Step 6: Put the panel on FlightImpact**

In `web/resources/js/pages/FlightImpact.vue`:

Add the import below the existing imports:

```js
import DecisionPanel from '../components/DecisionPanel.vue';
```

Change the props line to:

```js
const props = defineProps({ flight: Object, legs: Array, delay: Number, whatIf: Boolean, stop: String, decisions: Array });
```

Add the panel as the last child of `<main>`, after the what-if footnote `<p v-if="whatIf" ...>`:

```vue
        <DecisionPanel :flight-id="flight.flight_id" :legs="legs" :what-if-delay="whatIf ? delay : null" :decisions="decisions" />
```

Run: `npm run build`
Expected: the build succeeds with no Vue compile errors.

- [ ] **Step 7: Append the author entry to `DECISIONS.md`**

```markdown

## 2026-11-23: Type the author on each decision, with no login
- **Chose:** a required name field on the decision form, remembered in the browser's `localStorage`. No accounts.
- **Gave up:** knowing who wrote a record. Anyone at the keyboard can type any name, and the app must stay on this machine.
- **Why:** login would be the largest part of the phase, and the review's value is the frozen prediction beside the outcome, not proof of identity.
- **Revisit if:** the app is deployed anywhere or more than one person logs decisions. Then add Laravel's auth, with users in `app`.
```

- [ ] **Step 8: Run every suite**

Run: `./vendor/bin/pest && npm test && npm run build`
Expected: all PASS.

- [ ] **Step 9: Smoke test in a browser**

This is the only place the CSRF token is exercised, since Laravel skips the check under tests.

1. Run `php artisan serve` (in the background).
2. Open `http://127.0.0.1:8000/flights/<id>`, where `<id>` is from `psql -h localhost flightops -Atc "select flight_id from app_read.tail_legs where tail_number = 'N102DN' and leg_day = '2024-07-19' and origin = 'DEN'"`.
3. Log `Cancel a leg`, target `DL 2590 ATL → BWI`, reason `smoke`, name `smoke test`.
   Expected: the page returns to the flight with no 419. The entry `... smoke test · Cancel a leg: DL 2590 ATL → BWI · airline flew it, +49 min` appears, and the name field is still filled after a reload.
4. Remove the smoke row as the database owner (the app role can't):

```bash
psql -h localhost flightops -c "delete from app.decision_leg where decision_id in (select decision_id from app.decision where author = 'smoke test'); delete from app.decision where author = 'smoke test';"
```

Expected: `DELETE 5` then `DELETE 1`.

If step 3 returns 419, stop. Inertia v3 isn't sending the `XSRF-TOKEN` cookie, and that needs its own fix before going on.

- [ ] **Step 10: Commit**

```bash
git add web/resources/js/lib/decisions.js web/resources/js/lib/decisions.test.js web/resources/js/components/DecisionPanel.vue web/resources/js/pages/FlightImpact.vue web/app/Http/Controllers/FlightImpactController.php web/tests/Feature/DecisionTest.php DECISIONS.md
git commit -m "feat: decision panel on the FlightImpact page"
```
