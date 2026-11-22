# Outage case study — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** write `docs/case-study.md` to the design in `docs/plans/2026-11-22-case-study-design.md`, and update the README and roadmap for phase 3.

**Architecture:** hand-written Markdown. Every figure links to a section of a generated report or a `DECISIONS.md` entry. Two checks run before commit: every figure must appear in its source, and every link and anchor must resolve.

**Tech Stack:** Markdown on GitHub. Python only for the link check.

## Global Constraints

- 1,200-1,800 words in `docs/case-study.md`, excluding footnotes.
- Six sections, in the order and with the questions given in the design.
- Only the three existing screenshots: `hub-2024-07-19.png`, `tail-N102DN-2024-07-19.png`, `flight-N102DN-2024-07-19.png`.
- State which day definition a July 19 figure uses: BTS flight date (895 cancellations touching ATL) or ATL day (899 of 2,078 on the hub page).
- Plain, specific prose. No claim the data doesn't show. The outage's cause is named as the CrowdStrike outage only as context, as the phase-1 report does ("the data shows the pattern, not the cause").
- Links are relative from `docs/`. Anchors use GitHub's rule: lowercase, punctuation dropped, spaces become `-`.

## Figures and sources

| Figure | Source |
|---|---|
| 98.84% of consecutive legs connect on ATL tails | `phase-1-report.md#findings` |
| 98.8% of flights with a tail link to an airframe; 7,683 unresolved with a reason | `phase-1-report.md#findings` |
| OpenSky/BTS daily correlation 0.996; DL+9E drops 38/52/50/44/26% BTS, 39/48/45/43/22% OpenSky | `phase-1-report.md#opensky-against-bts-july-15-27`, `#opensky-and-bts-agreement-july-2-31` |
| 3,208 cancelled touching ATL July 19-23; 3,098 code A, 30 code B; 2,864 Delta | `phase-1-report.md#findings` |
| July 19: 0 of 25 METARs adverse, 895 cancellations (flight date) | `phase-1-report.md#atl-by-day-july-15-27` |
| July 19 hub page: 2,078 flights, 899 cancelled (ATL day) | footnote query on `app_read.hub_day_hourly` |
| N102DN: DEN→ATL 5h16m late, 11 legs cancelled through July 23, all code A | `phase-1-report.md#one-aircraft-july-18-23` |
| 9,534 flown legs under a different row in actual-time order (the reason for schedule order) | `DECISIONS.md#2026-11-22-order-a-tails-legs-by-scheduled-departure` |
| Min turn DL p10 50, OH 28; p10 chosen at 13.0 vs 14.7 vs 20.4 | `phase-3-report.md#min-turn`, `#percentile-choice` |
| Depth-1 `late_aircraft` MAE 13.0 / 48.4 / 36.1 (normal), 18.4 / 57.9 / 60.0 (outage) | `phase-3-report.md#late-aircraft-minutes-against-baselines` |
| Precision 90.1%, recall 89.0%, base rate 74.8%; depth-3 recall 30.5% | same |
| Departure delay undercount 17.5 (normal), 33.8 (outage) | `phase-3-report.md#findings` |
| Cancelled in gap 9.8% (2,659 of 27,050) vs 1.6% (1,470 of 90,768) | `phase-3-report.md#what-the-model-misses` |
| 519 of 333,556 scored pairs are swaps | `phase-3-report.md#findings` |
| N102DN chain: 50-min turn, 221 slack, absorbed; ATL→BWI 49 late, 0 late aircraft; BWI→ATL 308 late, 0 late aircraft | `phase-3-report.md#worked-example-n102dn-july-19`, `#worked-example-n102dns-scored-pairs` |

---

### Task 1: Write `docs/case-study.md`

**Files:**
- Create: `docs/case-study.md`

- [ ] **Step 1: Write the six sections** from the design, citing each figure from the table above with a link at its first use. Section headings are the questions: "Can I trust this data?", "What happened?", "What breaks next?", "What the model can't see", "What I'd do next", after an untitled opening scene under the title `# The July 2024 outage at ATL: a case study`. Embed the screenshots with `![…](screenshots/<file>.png)`, one each in sections 3 and 4 (hub and tail in 3, flight in 4). End with a footnote holding the hub-day query:

```sql
select sum(scheduled) as flights, sum(cancelled) as cancelled
from app_read.hub_day_hourly where atl_day = '2024-07-19';  -- 2078 | 899
```

- [ ] **Step 2: Check every figure against its source.** For each number in the draft, grep it in the linked file. Run:

```bash
for n in 98.84 98.8 7,683 0.996 3,208 3,098 2,864 895 9,534 13.0 14.7 20.4 36.1 48.4 18.4 57.9 60.0 90.1 89.0 74.8 30.5 17.5 33.8 2,659 27,050 1,470 90,768 519 333,556 221 308; do
  printf '%-8s' "$n"; grep -l -- "$n" docs/phase-1-report.md docs/phase-3-report.md DECISIONS.md | tr '\n' ' '; echo
done
```

Expected: each number lists at least one file, and that file is the one the draft links for it. Report tables print numbers without thousands separators, so check those (`3208`, `27050` and so on) in the tables by hand where only the table has them. 2,078 and 899 come from the footnote query, so rerun it.

- [ ] **Step 3: Check links and anchors.** Save this as a scratchpad script, and run it with `python3 <script> docs/case-study.md README.md`:

```python
import re, sys
from pathlib import Path

def slug(h):
    return re.sub(r"[^\w\- ]", "", h.strip().lower()).replace(" ", "-")

bad = 0
for name in sys.argv[1:]:
    src = Path(name)
    for target in re.findall(r"\]\(([^)\s]+)\)", src.read_text()):
        if target.startswith("http"):
            continue
        path, _, anchor = target.partition("#")
        file = (src.parent / path).resolve() if path else src.resolve()
        if not file.exists():
            print(f"{name}: missing file {target}"); bad += 1; continue
        if anchor and file.suffix == ".md":
            heads = {slug(h) for h in re.findall(r"^#+ (.+)$", file.read_text(), re.M)}
            if anchor not in heads:
                print(f"{name}: missing anchor {target}"); bad += 1
print("bad links:", bad)
```

Expected: `bad links: 0`.

- [ ] **Step 4: Word count.** Run `sed '/^\[\^/,$d' docs/case-study.md | wc -w`. Expected: 1,200-1,800.

- [ ] **Step 5: Commit**

```bash
git add docs/case-study.md
git commit -m "docs: write the outage case study"
```

### Task 2: README, roadmap and status

**Files:**
- Modify: `README.md` (status line, "What the data shows", a phase-3 section)
- Modify: `docs/roadmap.md`, `CLAUDE.md`

- [ ] **Step 1: Update `README.md`.**
  - Change "Phases 1 and 2 are built: …" to cover phase 3, and link the case study first.
  - Under "What the data shows", add one bullet from the [Phase 3 report](docs/phase-3-report.md): the model beats both baselines, with depth-1 error 13.0 against 36.1 for full carry.
  - Add a short "Decision support" section after the ops console, with the flight screenshot and two sentences on what the page shows and the cancellation blind spot.
  - Leave "How it works" as it is, except for adding `min_turn` and the backtest to the ontology bullet.

- [ ] **Step 2: Update `docs/roadmap.md`.** After "Phases 1-3 plus a written outage case study are the core portfolio piece.", add: "That piece is done: see `case-study.md`."

- [ ] **Step 3: Update `CLAUDE.md`.** Status gets "Next action: brainstorm phase 4 (live data), or a cancellation-risk phase, which the case study recommends first. Ask the user which." Add `docs/case-study.md` to the Docs list.

- [ ] **Step 4: Rerun the link check** on `README.md` and `docs/case-study.md`. Expected: `bad links: 0`.

- [ ] **Step 5: Commit**

```bash
git add README.md docs/roadmap.md CLAUDE.md
git commit -m "docs: link the case study, README for phase 3"
```
