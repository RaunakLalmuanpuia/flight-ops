# Phase 2, step 6: walkthrough, screenshots and close-out

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Task 3 is an interactive browser walkthrough that the controller does, not a subagent.

**Goal:** confirm the demo path works in a real browser, fix the two review findings a viewer would hit, save portfolio screenshots, and close phase 2 in the docs.

**Architecture:** no new layers.
- Two template changes to `DayTimeline.vue`.
- A small shell script that takes headless Chrome screenshots of the running app into `docs/screenshots/`.
- A walkthrough driven through Claude in Chrome.
- Updates to `README.md`, `CLAUDE.md` and `docs/phase-2-plan.md`.

**Tech stack:** the existing app (Laravel 13, Inertia 3, Vue 3.5, Tailwind 4) and headless Google Chrome at `/Applications/Google Chrome.app`.

## Global Constraints

- The app reads, never writes. Don't touch the database or the migrations.
- No new packages and no TypeScript.
- Accessibility: every filter is reachable by keyboard. A chart interaction always has a form-control equivalent.
- Run web commands from `web/`: `./vendor/bin/pest`, `npm test`, `npm run build`. Kill any server you start. Headless Chrome won't render below a 500px viewport, so check phone width through a 390px iframe.
- The phase 2 "done means" list is in `docs/phase-2-plan.md`. Task 4 records each item as met or not.

---

### Task 1: a timeline that phones and screen readers can use

**Files:**
- Modify: `web/resources/js/components/DayTimeline.vue`

**Why:**
- At 390px the 960-unit SVG scales to about 0.37, so its labels shrink to about 4px.
- The hourly totals live only in SVG `<title>` hover text, so a screen reader gets none of them.

- [ ] **Step 1: Let the chart scroll instead of shrinking, and add a hidden summary table**

In the `<template>`, wrap the `<svg>` in a scroll container and give it a minimum width. Update its `aria-label`, and add a visually hidden table after the wrapper. The template ends up with two root nodes, which Vue 3 allows:

```vue
<template>
    <div class="overflow-x-auto">
        <svg :viewBox="`0 0 ${WIDTH} ${HEIGHT}`" class="w-full min-w-[640px]" role="img" aria-label="ATL departures and arrivals by local hour, with METARs below. The table that follows gives the same counts.">
            <!-- existing <g>, <line> and <text> content unchanged -->
        </svg>
    </div>
    <table class="sr-only">
        <caption>Flights by ATL local hour</caption>
        <thead>
            <tr><th scope="col">Hour</th><th scope="col">Departures</th><th scope="col">Arrivals</th><th scope="col">Cancelled</th><th scope="col">Adverse METAR</th></tr>
        </thead>
        <tbody>
            <tr v-for="h in hours" :key="`s${h.hour}`">
                <th scope="row">{{ pad(h.hour) }}:00</th>
                <td>{{ total(h.dep) }}</td>
                <td>{{ total(h.arr) }}</td>
                <td>{{ h.dep.cancelled + h.arr.cancelled }}</td>
                <td>{{ metars[h.hour].adverse ? 'yes' : 'no' }}</td>
            </tr>
        </tbody>
    </table>
</template>
```

Keep everything inside the `<svg>` as it is. `hours`, `metars`, `total` and `pad` already exist in the component's script.

- [ ] **Step 2: Build, test and check**

From `web/`:

```bash
npm test && npm run build && ./vendor/bin/pest
php artisan serve --port=8010 > /dev/null 2>&1 &
SERVER=$!
until curl -s -o /dev/null http://127.0.0.1:8010/up; do :; done
C="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
"$C" --headless=new --disable-gpu --virtual-time-budget=10000 --dump-dom http://127.0.0.1:8010/day/2024-07-19 > "$TMPDIR/hub.html"
printf '<iframe src="http://127.0.0.1:8010/day/2024-07-19" width="390" height="900" style="border:0"></iframe>' > "$TMPDIR/phone.html"
"$C" --headless=new --disable-gpu --hide-scrollbars --window-size=400,900 --virtual-time-budget=10000 --screenshot="$TMPDIR/phone.png" "file://$TMPDIR/phone.html"
kill $SERVER
grep -o 'Flights by ATL local hour' "$TMPDIR/hub.html" | wc -l
grep -o '<tr' "$TMPDIR/hub.html" | wc -l
```

Expected:
- All suites pass.
- The first grep prints `1`.
- The second prints `2104`: 2,079 rows in the flight table plus 25 in the summary table.
- Read `$TMPDIR/phone.png`. The timeline keeps readable labels and scrolls inside its box, and the page itself doesn't scroll sideways.

- [ ] **Step 3: Commit**

```bash
git add web/resources/js/components/DayTimeline.vue
git commit -m "fix: scrollable timeline on phones and an accessible hourly summary"
```

---

### Task 2: a repeatable screenshot script

**Files:**
- Create: `web/scripts/screenshots.sh`
- Create: `docs/screenshots/*.png` (produced by the script)

- [ ] **Step 1: Write the script**

`web/scripts/screenshots.sh`:

```bash
#!/usr/bin/env bash
# Portfolio screenshots of the running app into docs/screenshots/.
# Usage: scripts/screenshots.sh [base-url]   (default http://127.0.0.1:8000)
set -euo pipefail
BASE=${1:-http://127.0.0.1:8000}
OUT="$(cd "$(dirname "$0")/../.." && pwd)/docs/screenshots"
# shortcut: macOS Chrome path; on Linux pass CHROME=chromium
CHROME=${CHROME:-"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"}
mkdir -p "$OUT"

shot() {
    "$CHROME" --headless=new --disable-gpu --hide-scrollbars --window-size="$3" \
        --virtual-time-budget=10000 --screenshot="$OUT/$1.png" "$BASE$2" 2>/dev/null
    echo "$OUT/$1.png"
}

shot hub-2024-07-19 /day/2024-07-19 1440,1300
shot hub-2024-07-10 /day/2024-07-10 1440,1300
shot tail-N102DN-2024-07-19 /tail/N102DN/2024-07-19 1440,1100
shot tail-N181PQ-2024-07-19 /tail/N181PQ/2024-07-19 1440,1100
```

Then run `chmod +x web/scripts/screenshots.sh`.

These pages show:
- **July 19:** the outage.
- **July 10:** a normal day with adverse weather, for contrast.
- **N102DN:** the phase 1 report's example aircraft.
- **N181PQ:** a labelled rotation break ("Next origin JFK ≠ previous arrival DTW").

- [ ] **Step 2: Run it against a fresh server and look at every image**

From `web/`:

```bash
npm run build
php artisan serve --port=8010 > /dev/null 2>&1 &
SERVER=$!
until curl -s -o /dev/null http://127.0.0.1:8010/up; do :; done
scripts/screenshots.sh http://127.0.0.1:8010
kill $SERVER
ls -la ../docs/screenshots
```

Expected: the script prints four PNG paths, each file is over 50 KB, and each image shows its page fully rendered when you read it, not a blank or half-loaded frame. If a frame is blank, raise `--virtual-time-budget` to 20000 once.

- [ ] **Step 3: Commit**

```bash
git add web/scripts/screenshots.sh ../docs/screenshots
git commit -m "docs: add a screenshot script and portfolio screenshots"
```

---

### Task 3: browser walkthrough (the controller, through Claude in Chrome)

**Files:** none. Findings go into Task 4's notes.

The app runs at `http://127.0.0.1:8000`. Start it with `php artisan serve` from `web/` if it isn't already running. Use a new tab and record a GIF called `phase2_walkthrough.gif`. Check each item, and write down what you see:

- [ ] **Step 1:** Open `/`. It lands on `/day/2024-07-19`. The timeline shows the red and amber spike, the METAR strip has no adverse hours, and the caveat panel lists rotation breaks, unresolved aircraft, medium-confidence aircraft and no-tail flights.
- [ ] **Step 2:** Click the 08 column. It highlights, the Hour select reads 08:00, and the table shows only hour 08, in time order. Click it again to clear the filter.
- [ ] **Step 3:** Click the "Rotation break" caveat. The table filters to those flights and the button reads as pressed. Pick a row and click its tail. The tail page opens with that flight inside the day and a labelled gap row.
- [ ] **Step 4:** From the hub, filter Direction to Arrivals and Hour to 00:00. Click the tail of a flight whose origin is on the West Coast (an overnight inbound). The tail page opens on the previous ATL date, with the clicked flight shown in-day and not faded.
- [ ] **Step 5:** On a tail page, open a METAR disclosure with the keyboard (Tab to the summary, then Enter). Check that Previous and Next day move through the days.
- [ ] **Step 6:** Use the date input with the keyboard. Type `07/10/2024`, or the browser's local order, and press Enter. July 10 loads. Type a date outside July and press Enter. Nothing loads, and the field resets.
- [ ] **Step 7:** Open `/day/2024-08-01` and `/day/garbage`. Both show the Not found page naming July 1-31.

If a step fails, stop and report it to the user with the GIF before fixing anything. Small cosmetic findings go into the notes.

---

### Task 4: close phase 2 in the docs

**Files:**
- Modify: `README.md`, `CLAUDE.md`, `docs/phase-2-plan.md`

- [ ] **Step 1: README**

In `README.md`:

1. Replace the paragraph `Phase 1 is built: a reproducible data foundation and a data-quality report on July 2024, the month of the CrowdStrike outage.` with:

   ```markdown
   Phases 1 and 2 are built: a reproducible data foundation with a data-quality report on July 2024, the month of the CrowdStrike outage, and a read-only ops console that shows what happened at ATL on any day and to any aircraft.
   ```

2. After the `## What the data shows` section, insert:

   ```markdown
   ## The ops console

   ![ATL on July 19, 2024](docs/screenshots/hub-2024-07-19.png)

   - **Pick a day, see the hub.** Departures and arrivals by local hour, split by status, over a strip of the METARs for the same hours. July 19 is a wall of cancellations under clear skies. July 10 is a normal day with storms.
   - **Data problems show where they matter.** Each day lists its caveats (rotation breaks, unresolved or medium-confidence aircraft, stale weather, missing tails), and every flight row carries its own.
   - **Drill into an aircraft.** One click opens a tail's legs for the day, plus the legs either side: scheduled and actual bars on an Atlanta-time axis, delay causes, unflown cancellations and labelled gaps where the rotation breaks.

   ![N102DN on July 19, 2024](docs/screenshots/tail-N102DN-2024-07-19.png)

   The app reads through a database role that can only select from a schema of views, so the rules for days, statuses and labels live in tested SQL, and the app cannot write.
   ```

3. Replace the `## Stack` paragraph with:

   ```markdown
   Python (uv, pytest), PostgreSQL and SQL for the pipelines. Laravel 13, Inertia and Vue for the app, tested with Pest and `node --test`.
   ```

4. At the end of `## Run it`, after the line about `data/`, append:

   ```markdown
   To run the app once the pipeline has built the database:

   ```sh
   cd web
   composer install && npm install
   cp .env.example .env && php artisan key:generate
   npm run build
   php artisan serve      # http://127.0.0.1:8000
   ./vendor/bin/pest      # tests run against the loaded database
   ```

   The app connects as `flightops_app`, a read-only role the migrations create without a password. That assumes local trust authentication, as Postgres.app sets up by default.
   ```

- [ ] **Step 2: Phase plan notes**

Append to `## Notes` in `docs/phase-2-plan.md`:

```markdown
- **Step 6 and done means:** met.
  - pytest, Pest and `node --test` pass.
  - Every pytest run builds `flightops_test` from the migrations, so a fresh database gets the same views.
  - `/day/2024-07-19` shows 899 cancellations, which matches the direct count.
  - The walkthrough showed the spike against a clear METAR strip, and one click reached N181PQ's labelled gap.
  - An insert as `flightops_app` fails.
  - Screenshots are in `docs/screenshots/` and are regenerated by `web/scripts/screenshots.sh`.
  - Walkthrough findings: … (from Task 3, or "none").
```

Fill in the findings. If a done-means item wasn't met, say so plainly rather than writing "met".

- [ ] **Step 3: CLAUDE.md**

In the Status section, replace the **Current phase** and **Next action** bullets with:

```markdown
- **Current phase:** 2, built. Steps 1-6 are done: the `app_read` views (migrations 011-015), the Laravel app in `web/`, and the walkthrough with screenshots in `docs/screenshots/`.
- **Next action:** phase 3, decision support, which needs brainstorming first.
```

In the `## Docs` list, replace the line about `docs/phase-1-plan.md` with these two lines, and add a line for the screenshots:

```markdown
- `docs/phase-1-plan.md`, `docs/phase-2-plan.md`: phase plans, with measured notes at the end of phase 2's.
- `docs/screenshots/`: portfolio screenshots, regenerated by `web/scripts/screenshots.sh` against a running app.
```

- [ ] **Step 4: Run every suite and commit**

```bash
(cd pipelines && uv run --env-file ../.env pytest -q) && (cd web && ./vendor/bin/pest && npm test)
git add README.md CLAUDE.md docs/phase-2-plan.md
git commit -m "docs: close phase 2 with the console, screenshots and run steps"
```

Expected: pytest 126, Pest 20 and node 24 all pass.
