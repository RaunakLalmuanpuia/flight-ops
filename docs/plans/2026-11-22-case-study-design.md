# Outage case study — design

**Goal:** a written case study of the July 19-23, 2024 outage at ATL, told through an operations controller's questions. With phases 1-3 it completes the core portfolio piece (`docs/roadmap.md`).

**Deliverables:**
- `docs/case-study.md`, about 1,200-1,800 words, hand-written Markdown.
- `README.md` updated for phase 3, linking the case study and the phase-3 report.
- `docs/roadmap.md` noting that the core piece is done.

**Reader:** a hiring manager or engineer for a forward deployed role, reading on GitHub next to the code. They should come away knowing what the data showed, how far to trust it, and how the author handled what the data couldn't answer.

## Structure

Each section opens with a controller's question in plain words, and answers it with evidence and one decision the work required.

1. **July 19, 08:00 in Atlanta.** Flights are cancelling under clear skies, and the controller needs to know why and what breaks next. One paragraph, ending with the three questions below.
2. **Can I trust this data?** Four public sources resolved into one model. Rotations connect (98.84% on ATL tails), and 98.8% of flights with a tail link to an airframe, with every unresolved one keeping a reason. OpenSky ADS-B confirms the BTS drop independently: daily counts correlate at 0.996, and Delta+Endeavor arrivals fell 39-48% in OpenSky against 38-52% in BTS on the worst days. Decision to show: resolving tails against the flight date, and the scope trap of rebuilding rotations from the national file.
3. **What happened?** 3,208 cancellations touching ATL from July 19-23, 3,098 of them carrier code A and 30 weather code B. On July 19, 0 of 25 METARs were adverse. Screenshot of the hub on July 19. Then one aircraft, N102DN: its DEN→ATL left 5h16m late, and 11 of its legs were cancelled through July 23, while every leg it flew connected. Tail screenshot. Decision to show: hub rows filed by their ATL event, and tail legs ordered by schedule, with the N102DN bug that this fixed.
4. **What breaks next?** Propagation along the flown chain, using each carrier's minimum turn measured from July. Backtest: p10 was chosen on July outside the outage, and the model beat predict-0 and full carry at every depth for both targets. Depth-1 `late_aircraft` error was 13.0 min (normal days) and 18.4 (outage), against 36.1 and 60.0 for full carry. At-risk precision was 90.1%, against a 74.8% base rate. Flight screenshot: N102DN's DEN→ATL "absorbed" while three legs in its gap were cancelled, and its next leg BWI→ATL left 308 min late with no aircraft cause.
5. **What the model can't see.** 9.8% of late legs in the outage had a cancelled leg in the gap after them, against 1.6% on normal days. During the outage the decision was cancellation, which the model shows but doesn't predict. Also: departure delay undercounted by 17.5 min (normal days) and 33.8 (outage), no crew or passenger data, in-sample percentile choice, and p10 at the edge of the tested range.
6. **What I'd do next.** Load a second month to choose the percentile out of sample and try turns below p10. Model cancellation risk as its own phase, since this is where the outage decisions were. Live data (phase 4) only after that.

## Sourcing rule

Every number links to the table it came from: `docs/phase-1-report.md` or `docs/phase-3-report.md`, by section anchor, or a `DECISIONS.md` entry. Numbers that appear in no report, such as July 19's hub-day totals, come from a query given in a footnote. Before committing, check each figure against its source.

**Known tension to handle:** July 19 cancellations are 895 by BTS flight date in the phase-1 report, and 899 by ATL day on the hub page. The case study uses one figure per context and says which day definition it means.

## Out of scope

Charts or images beyond the three existing screenshots, a published web version, generated prose, and automated number checks.
