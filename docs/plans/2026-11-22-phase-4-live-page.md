# Phase 4 Live Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** a read-only `/live` page showing ATL's current METAR and TAF and the aircraft around ATL from the latest `live` poll, with a banner when the loop isn't running. This is phase 4 step 3 in `docs/phase-4-plan.md`.

**Architecture:** migration 021 adds `app_read.live_aircraft`, `live_weather`, `live_taf` and `live_status` over the tables the `live` command fills. `LiveController` reads them with one query each, as the other controllers do. `Live.vue` renders them, with the freshness and motion logic in `resources/js/lib/live.js` so `node --test` covers the empty and stale states, which the read-only Pest suite can't create.

**Tech Stack:** Postgres views, Laravel 12 + Inertia + Vue 3 + Tailwind, Pest, `node --test`.

## Global Constraints

- The app reads `app_read` only, as `flightops_app`. It never writes.
- Pest runs against the loaded local database: `cd web && ./vendor/bin/pest`. JS tests: `npm test`. Pipelines: `cd pipelines && uv run --env-file ../.env pytest`.
- Views return `timestamptz`, and the app's connection uses UTC (`config/database.php`), so timestamps arrive as `"2026-11-22 17:46:35+00"`. Parse them with `toDate` from `lib/time.js`.
- Show times in Atlanta local time with `ATL_TZ`, as the other pages do.
- A link to TailDay must be a tail and day TailDay can show: the July airframe for that tail must carry the live hex (identifiers are time-bounded), and the day must be in the loaded range.
- No new dependencies.

---

### Task 1: Migration 021, the read views

**Files:**
- Create: `db/migrations/021_live_read.sql`
- Test: `pipelines/tests/test_live.py` (append)

**Interfaces:**
- Consumes: `ontology.live_position`, `ontology.live_weather`, `ontology.live_taf` (migration 020), `ontology.is_adverse(ontology.weather_observation)`, `dq.ingestion_run`
- Produces:
  - `app_read.live_aircraft`: the `live_position` columns except latitude, longitude and `position_at`, plus `position_age_s` (int) and `july_day` (date, NULL when there's no July link)
  - `app_read.live_weather`: `observed_at`, `metar_type`, `raw_text`, `adverse` (bool), `stale` (bool, more than 90 min old), and the parsed columns
  - `app_read.live_taf`: `fetched_at`, `raw_text`
  - `app_read.live_status`: one row, `states_loaded_at` (last poll loaded, NULL if never), `snapshot_at`, `checked_at` (`now()`)

- [ ] **Step 1: Write the failing tests**

Append to `pipelines/tests/test_live.py`:

```python
def test_live_weather_view_flags_adverse_and_stale(conn, built):
    rows = conn.execute("SELECT metar_type, adverse, stale FROM app_read.live_weather ORDER BY observed_at").fetchall()
    # 2SM and an 800 ft ceiling are both adverse, and the fixture METARs are long past 90 minutes
    assert rows == [("METAR", True, True), ("SPECI", True, True)]


def test_live_aircraft_view_gives_position_age_and_no_july_link_without_july_data(conn, built):
    rows = dict(conn.execute("SELECT hex, position_age_s FROM app_read.live_aircraft").fetchall())
    assert rows["A00001"] == 5 and rows["FFFFFF"] is None
    assert conn.execute("SELECT count(july_day) FROM app_read.live_aircraft").fetchone()[0] == 0


def test_live_status_reports_the_last_poll(conn, built):
    loaded, snapshot = conn.execute("SELECT states_loaded_at, snapshot_at FROM app_read.live_status").fetchone()
    assert loaded is not None
    assert snapshot == datetime(2026, 11, 22, 17, 30, 5, tzinfo=timezone.utc)


def test_live_status_has_one_row_before_any_poll(conn):
    assert conn.execute("SELECT states_loaded_at, snapshot_at FROM app_read.live_status").fetchall() == [(None, None)]
```

(`snapshot_at` is the fixture's `time`, 1795368605, which is 2026-11-22 17:30:05 UTC. A00001's `time_position` is 5 s earlier.)

- [ ] **Step 2: Run them to check they fail**

Run: `cd pipelines && uv run --env-file ../.env pytest tests/test_live.py -v -k "view or status"`
Expected: FAIL with `relation "app_read.live_weather" does not exist`.

- [ ] **Step 3: Write the migration**

`db/migrations/021_live_read.sql`:

```sql
-- Read views for the Live page (phase 4). Same grants as the rest of app_read, from 012's default privileges.

CREATE VIEW app_read.live_aircraft AS
SELECT p.snapshot_at, p.hex, p.callsign, p.tail_number, p.manufacturer, p.model,
       p.resolve_method, p.resolve_confidence, p.unresolved_reason,
       p.operator, p.bts_carrier, p.operator_reason,
       p.on_ground, p.altitude_ft, p.vertical_rate_fpm, p.distance_nm, p.bearing_deg,
       extract(epoch FROM p.snapshot_at - p.position_at)::int AS position_age_s,
       j.day AS july_day
FROM ontology.live_position p
-- Link to TailDay only when the July airframe on this tail carries this hex: a tail can be re-registered.
-- flight_date, not the ATL-local day, so the link always falls inside the loaded range.
LEFT JOIN LATERAL (
    SELECT max(f.flight_date) AS day
    FROM ontology.flight f
    JOIN ontology.aircraft_registration r ON r.aircraft_id = f.aircraft_id AND r.hex = p.hex
    WHERE f.tail_number = p.tail_number
      AND f.tail_number IN (SELECT tail_number FROM ontology.rotation_leg WHERE touched_atl)
) j ON true;

CREATE VIEW app_read.live_weather AS
SELECT w.observed_at, w.metar_type, w.raw_text,
       ontology.is_adverse(ROW(NULL::bigint, w.observed_at, w.raw_text, w.wind_dir_deg, w.wind_kt, w.gust_kt,
           w.visibility_sm, w.ceiling_ft, w.temp_c, w.dewpoint_c, w.altimeter_inhg, w.weather
       )::ontology.weather_observation) AS adverse,
       now() - w.observed_at > interval '90 minutes' AS stale,
       w.wind_dir_deg, w.wind_kt, w.gust_kt, w.visibility_sm, w.ceiling_ft, w.temp_c, w.dewpoint_c, w.weather
FROM ontology.live_weather w;

CREATE VIEW app_read.live_taf AS
SELECT fetched_at, raw_text FROM ontology.live_taf;

-- The last poll that loaded, even when its box was empty, so the page can tell a quiet sky from a stopped loop.
CREATE VIEW app_read.live_status AS
SELECT (SELECT max(loaded_at) FROM dq.ingestion_run WHERE table_name = 'opensky_state') AS states_loaded_at,
       (SELECT max(snapshot_at) FROM ontology.live_position) AS snapshot_at,
       now() AS checked_at;
```

- [ ] **Step 4: Run the tests to check they pass**

Run: `cd pipelines && uv run --env-file ../.env pytest tests/test_live.py tests/test_app_read.py -v`
Expected: all PASS. `test_app_read.py` includes the existing checks that `flightops_app` can read `app_read` and can't write.

- [ ] **Step 5: Apply to the local database and time the aircraft view**

```bash
cd pipelines && uv run --env-file ../.env python -m flightops migrate
psql -h localhost flightops -c '\timing on' -c 'select count(*), count(july_day) from app_read.live_aircraft'
```

Expected: `applied: ['021_live_read.sql']`, and the query under 500 ms. (The same join measured 187 ms on 158 aircraft.) If it's slower, stop and report rather than adding an index unplanned.

- [ ] **Step 6: Commit**

```bash
git add db/migrations/021_live_read.sql pipelines/tests/test_live.py
git commit -m "feat: app_read views for the live page"
```

---

### Task 2: Route and controller

**Files:**
- Create: `web/app/Http/Controllers/LiveController.php`
- Modify: `web/routes/web.php`
- Test: `web/tests/Feature/LiveTest.php`

**Interfaces:**
- Consumes: the four `app_read.live_*` views (Task 1)
- Produces: Inertia page `Live` with props `status` (`{states_loaded_at, snapshot_at, checked_at}`), `aircraft` (array of `live_aircraft` rows, nearest first), `weather` (latest 3 `live_weather` rows, newest first), `taf` (`{fetched_at, raw_text}` or null)

- [ ] **Step 1: Write the failing tests**

`web/tests/Feature/LiveTest.php`:

```php
<?php

use Illuminate\Support\Collection;
use Illuminate\Support\Facades\DB;
use Inertia\Testing\AssertableInertia as Assert;

// Read-only against whatever the last `live` run left. Empty and stale states are covered in resources/js/lib/live.test.js.

it('renders the live page with status, aircraft, weather and taf', function () {
    $this->get('/live')->assertOk()->assertInertia(fn (Assert $page) => $page
        ->component('Live')
        ->has('status.checked_at')
        ->has('aircraft')
        ->has('weather')
        ->has('taf'));
});

it('lists aircraft nearest first', function () {
    $this->get('/live')->assertInertia(fn (Assert $page) => $page
        ->where('aircraft', function (Collection $rows) {
            $d = $rows->pluck('distance_nm')->filter(fn ($v) => $v !== null)->map(fn ($v) => (float) $v)->values();
            return $d->all() === $d->sort()->values()->all();
        }));
});

it('gives every aircraft a tail or a reason', function () {
    $this->get('/live')->assertInertia(fn (Assert $page) => $page
        ->where('aircraft', fn (Collection $rows) => $rows->every(fn ($r) => $r['tail_number'] !== null || $r['unresolved_reason'] !== null)));
});

it('links only to tail days the tail page can show', function () {
    $row = DB::selectOne('select tail_number, july_day from live_aircraft where july_day is not null limit 1');
    if (! $row) {
        $this->markTestSkipped('no live aircraft with a July link; run `python -m flightops live` first');
    }
    $this->get("/tail/{$row->tail_number}/{$row->july_day}")->assertOk();
});

it('shows at most three metars, newest first', function () {
    $this->get('/live')->assertInertia(fn (Assert $page) => $page
        ->where('weather', fn (Collection $rows) => $rows->count() <= 3
            && $rows->pluck('observed_at')->all() === $rows->pluck('observed_at')->sortDesc()->values()->all()));
});
```

- [ ] **Step 2: Run them to check they fail**

Run: `cd web && ./vendor/bin/pest tests/Feature/LiveTest.php`
Expected: FAIL, with `/live` returning 404 (the fallback route).

- [ ] **Step 3: Write the controller and route**

`web/app/Http/Controllers/LiveController.php`:

```php
<?php

namespace App\Http\Controllers;

use Illuminate\Support\Facades\DB;
use Inertia\Inertia;

class LiveController
{
    public function __invoke()
    {
        return Inertia::render('Live', [
            'status' => DB::selectOne('select states_loaded_at, snapshot_at, checked_at from live_status'),
            'aircraft' => DB::select('select * from live_aircraft order by distance_nm nulls last, hex'),
            'weather' => DB::select('select * from live_weather order by observed_at desc limit 3'),
            'taf' => DB::selectOne('select fetched_at, raw_text from live_taf'),
        ]);
    }
}
```

In `web/routes/web.php`, add the import and the route above the fallback:

```php
use App\Http\Controllers\LiveController;
```

```php
Route::get('/live', LiveController::class);
```

- [ ] **Step 4: Create a placeholder page so Inertia can resolve the component**

`web/resources/js/pages/Live.vue` (replaced in Task 3):

```vue
<script setup>
defineProps({ status: Object, aircraft: Array, weather: Array, taf: Object });
</script>

<template>
    <main />
</template>
```

- [ ] **Step 5: Run the tests to check they pass**

Run: `cd web && ./vendor/bin/pest`
Expected: all PASS. With live rows from the last run, the July-link test runs. Without them it's reported as skipped.

- [ ] **Step 6: Commit**

```bash
git add web/app/Http/Controllers/LiveController.php web/routes/web.php web/tests/Feature/LiveTest.php web/resources/js/pages/Live.vue
git commit -m "feat: /live route reads the live views"
```

---

### Task 3: The page

**Files:**
- Create: `web/resources/js/lib/live.js`, `web/resources/js/lib/live.test.js`
- Modify: `web/resources/js/pages/Live.vue` (replace the placeholder)
- Modify: `web/resources/js/pages/HubDay.vue` (link to `/live`)

**Interfaces:**
- Consumes: Task 2's props, `toDate`, `localTime`, `ATL_TZ` from `lib/time.js`
- Produces: `freshness(loadedAt: string|null, now: string) -> {state: 'never'|'stale'|'fresh', minutes: number|null}`, `motion(row) -> string`, `LIVE_REASONS: object`, `STALE_AFTER_MIN = 5`

- [ ] **Step 1: Write the failing JS tests**

`web/resources/js/lib/live.test.js`:

```js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { freshness, motion, LIVE_REASONS } from './live.js';

const now = '2026-11-22 18:00:00+00';

test('no poll ever loaded', () => {
    assert.deepEqual(freshness(null, now), { state: 'never', minutes: null });
});

test('a poll within five minutes is fresh', () => {
    assert.deepEqual(freshness('2026-11-22 17:56:00+00', now), { state: 'fresh', minutes: 4 });
});

test('a poll over five minutes old is stale', () => {
    assert.deepEqual(freshness('2026-11-22 17:42:30+00', now), { state: 'stale', minutes: 17 });
});

test('motion from the vertical rate, with ground first', () => {
    assert.equal(motion({ on_ground: true, vertical_rate_fpm: 1500 }), 'on ground');
    assert.equal(motion({ on_ground: false, vertical_rate_fpm: 1500 }), 'climbing');
    assert.equal(motion({ on_ground: false, vertical_rate_fpm: -800 }), 'descending');
    assert.equal(motion({ on_ground: false, vertical_rate_fpm: 100 }), 'level');
    assert.equal(motion({ on_ground: false, vertical_rate_fpm: null }), '—');
});

test('every reason the pipeline writes has a label', () => {
    for (const r of ['hex not in FAA registry', 'ambiguous hex', 'general aviation callsign', 'unknown prefix', 'no callsign']) {
        assert.ok(LIVE_REASONS[r], r);
    }
});
```

- [ ] **Step 2: Run them to check they fail**

Run: `cd web && npm test`
Expected: FAIL with `Cannot find module '.../live.js'`.

- [ ] **Step 3: Write the helpers**

`web/resources/js/lib/live.js`:

```js
import { toDate } from './time.js';

export const STALE_AFTER_MIN = 5; // the loop polls every 60 s, so 5 minutes means it stopped or keeps failing
const LEVEL_FPM = 300; // under this either way, call it level

export const LIVE_REASONS = {
    'hex not in FAA registry': 'Not in the FAA registry (foreign or military)',
    'ambiguous hex': 'Hex on more than one FAA registration',
    'general aviation callsign': 'Flying under its tail number',
    'unknown prefix': 'Callsign prefix not in our operator list',
    'no callsign': 'No callsign broadcast',
};

export function freshness(loadedAt, now) {
    if (!loadedAt) return { state: 'never', minutes: null };
    const minutes = Math.floor((toDate(now) - toDate(loadedAt)) / 60000);
    return { state: minutes > STALE_AFTER_MIN ? 'stale' : 'fresh', minutes };
}

export function motion({ on_ground, vertical_rate_fpm: v }) {
    if (on_ground) return 'on ground';
    if (v === null || v === undefined) return '—';
    return v >= LEVEL_FPM ? 'climbing' : v <= -LEVEL_FPM ? 'descending' : 'level';
}
```

- [ ] **Step 4: Run the JS tests to check they pass**

Run: `cd web && npm test`
Expected: all PASS.

- [ ] **Step 5: Write the page**

Replace `web/resources/js/pages/Live.vue`:

```vue
<script setup>
import { computed } from 'vue';
import { Head, Link } from '@inertiajs/vue3';
import { ATL_TZ, localTime } from '../lib/time.js';
import { freshness, motion, LIVE_REASONS } from '../lib/live.js';

const props = defineProps({ status: Object, aircraft: Array, weather: Array, taf: Object });
const fresh = computed(() => freshness(props.status.states_loaded_at, props.status.checked_at));
const latest = computed(() => props.weather[0] ?? null);
const reason = (r) => LIVE_REASONS[r] ?? r;
const CAVEATS = [
    'No schedule: BTS is published months late, so there are no flight numbers, delays or propagation here.',
    'Operators come from the callsign prefix. Regional flights sold as Delta fly as Endeavor (EDV) or SkyWest (SKW).',
    'Positions are OpenSky ADS-B and can lag by a few seconds to minutes. Each row shows how old its position is.',
];
</script>

<template>
    <Head title="ATL live" />
    <main class="mx-auto max-w-7xl space-y-4 px-4 py-6">
        <header class="flex flex-wrap items-center gap-4">
            <h1 class="mr-auto text-xl font-semibold">ATL · live <span class="text-sm font-normal text-slate-500">(Atlanta local time)</span></h1>
            <Link href="/day/2024-07-19" class="text-sm text-sky-700 underline">July 2024 history →</Link>
        </header>

        <p v-if="fresh.state === 'never'" role="status" class="rounded border border-slate-300 bg-slate-50 p-3 text-sm">
            No live data yet. Start the loop from <code>pipelines/</code>:
            <code class="ml-1 rounded bg-white px-1">uv run --env-file ../.env python -m flightops live</code>
        </p>
        <p v-else-if="fresh.state === 'stale'" role="status" class="rounded border border-amber-400 bg-amber-50 p-3 text-sm">
            Live loop not running: data is {{ fresh.minutes }} min old (last poll {{ localTime(status.states_loaded_at, ATL_TZ) }}).
        </p>
        <p v-else role="status" class="text-sm text-slate-600">
            Last poll {{ localTime(status.states_loaded_at, ATL_TZ) }} · {{ aircraft.length }} aircraft within about 90 nm
        </p>

        <section aria-label="Weather" class="space-y-1 rounded border border-slate-200 bg-white p-3 text-sm">
            <h2 class="font-semibold text-slate-700">Weather at ATL</h2>
            <p v-if="!latest" class="text-slate-500">No METAR loaded yet.</p>
            <template v-else>
                <p>
                    <span class="mr-2 rounded px-1.5 py-0.5 text-xs" :class="latest.adverse ? 'bg-sky-700 text-white' : 'bg-sky-100'">{{ latest.adverse ? 'Adverse' : 'Not adverse' }}</span>
                    <span v-if="latest.stale" class="mr-2 rounded bg-amber-100 px-1.5 py-0.5 text-xs">Over 90 min old</span>
                    {{ localTime(latest.observed_at, ATL_TZ) }} {{ latest.metar_type }}
                </p>
                <p class="font-mono text-xs">{{ latest.raw_text }}</p>
            </template>
            <p v-if="taf" class="whitespace-pre-line font-mono text-xs text-slate-600">{{ taf.raw_text }}</p>
        </section>

        <section aria-labelledby="live-caveats" class="text-xs text-slate-600">
            <h2 id="live-caveats" class="text-sm font-semibold text-slate-700">What this page can't show</h2>
            <ul class="mt-1 list-disc pl-5">
                <li v-for="c in CAVEATS" :key="c">{{ c }}</li>
            </ul>
        </section>

        <section aria-label="Aircraft" class="overflow-x-auto">
            <p v-if="!aircraft.length" class="text-sm text-slate-500">No aircraft in the last snapshot.</p>
            <table v-else class="w-full text-left text-sm">
                <thead class="text-xs text-slate-500">
                    <tr>
                        <th class="py-1 pr-3">Tail</th><th class="pr-3">Type</th><th class="pr-3">Operator</th><th class="pr-3">Callsign</th>
                        <th class="pr-3 text-right">Distance</th><th class="pr-3 text-right">Bearing</th><th class="pr-3 text-right">Altitude</th>
                        <th class="pr-3">Motion</th><th class="text-right">Position age</th>
                    </tr>
                </thead>
                <tbody>
                    <tr v-for="a in aircraft" :key="a.hex" class="border-t border-slate-100">
                        <td class="py-1 pr-3">
                            <Link v-if="a.july_day" :href="`/tail/${a.tail_number}/${a.july_day}`" class="text-sky-700 underline" :title="`Last July 2024 day: ${a.july_day}`">{{ a.tail_number }}</Link>
                            <span v-else-if="a.tail_number">{{ a.tail_number }}</span>
                            <span v-else class="text-slate-500" :title="a.hex">{{ reason(a.unresolved_reason) }}</span>
                        </td>
                        <td class="pr-3">{{ a.manufacturer }} {{ a.model }}</td>
                        <td class="pr-3">
                            <span v-if="a.operator">{{ a.operator }}</span>
                            <span v-else class="text-slate-500">{{ reason(a.operator_reason) }}</span>
                        </td>
                        <td class="pr-3 font-mono">{{ a.callsign }}</td>
                        <td class="pr-3 text-right">{{ a.distance_nm === null ? '—' : `${a.distance_nm} nm` }}</td>
                        <td class="pr-3 text-right">{{ a.bearing_deg === null ? '—' : `${a.bearing_deg}°` }}</td>
                        <td class="pr-3 text-right">{{ a.on_ground || a.altitude_ft === null ? '—' : `${a.altitude_ft.toLocaleString('en-US')} ft` }}</td>
                        <td class="pr-3">{{ motion(a) }}</td>
                        <td class="text-right">{{ a.position_age_s === null ? '—' : `${a.position_age_s} s` }}</td>
                    </tr>
                </tbody>
            </table>
        </section>
    </main>
</template>
```

- [ ] **Step 6: Link to it from the hub page**

In `web/resources/js/pages/HubDay.vue`, add the `Link` import:

```js
import { Head, Link } from '@inertiajs/vue3';
```

and put the link before `DayNav` in the header:

```vue
            <Link href="/live" class="text-sm text-sky-700 underline">ATL live →</Link>
            <DayNav :day="day" :range="range" base="/day" />
```

- [ ] **Step 7: Build and run every app test**

Run: `cd web && npm run build && npm test && ./vendor/bin/pest`
Expected: the build succeeds, and all tests PASS.

- [ ] **Step 8: Commit**

```bash
git add web/resources/js/lib/live.js web/resources/js/lib/live.test.js web/resources/js/pages/Live.vue web/resources/js/pages/HubDay.vue
git commit -m "feat: live page with weather, aircraft and freshness banner"
```

---

### Task 4: Real run, screenshot and docs

**Files:**
- Modify: `web/scripts/screenshots.sh`
- Create: `docs/screenshots/live-stale.png`, `docs/screenshots/live.png`
- Modify: `docs/phase-4-plan.md` (notes), `docs/roadmap.md`, `CLAUDE.md` (Status, Docs)

- [ ] **Step 1: Add the live shots to the script**

Append to `web/scripts/screenshots.sh`:

```bash
# live data changes every minute: run `python -m flightops live` first, or this captures the stale banner
shot live /live 1440,1300
```

- [ ] **Step 2: Check the stale state**

With the app running (`cd web && php artisan serve`), and the last `live` poll more than 5 minutes old:

```bash
cd web && "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new --disable-gpu --hide-scrollbars \
  --window-size=1440,700 --virtual-time-budget=10000 --screenshot=../docs/screenshots/live-stale.png http://127.0.0.1:8000/live
```

Open the PNG and check that the amber banner reads "Live loop not running".

- [ ] **Step 3: Check the fresh state**

Start `cd pipelines && uv run --env-file ../.env python -m flightops live` in another terminal, wait for `tick 0`, then run `cd web && scripts/screenshots.sh`. Open `docs/screenshots/live.png` and check:
- the status line shows the last poll and the aircraft count
- the weather strip shows the METAR and the TAF
- the table is nearest first
- at least one tail is a link, and clicking it opens a July TailDay page

Stop the loop with Ctrl-C.

- [ ] **Step 4: Write it down**

- Under `## Notes` in `docs/phase-4-plan.md`: the number of aircraft with a July link, and that the tail link uses `flight_date` so it always falls inside the loaded range.
- In `docs/roadmap.md`: mark phase 4 as built, with "See `phase-4-plan.md`" in its Main work cell, as phases 1-3 have.
- In `CLAUDE.md` Status: phase 4 complete, the `/live` page, and the next action (ask the user whether to brainstorm the cancellation-risk phase the case study recommends, or phase 5).

- [ ] **Step 5: Commit**

```bash
git add web/scripts/screenshots.sh docs/screenshots/live.png docs/screenshots/live-stale.png docs/phase-4-plan.md docs/roadmap.md CLAUDE.md
git commit -m "docs: live page screenshots, phase 4 complete"
```
