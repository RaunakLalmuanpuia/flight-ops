# fix-final report
1. 015_hub_tail_day.sql (appends tail_day), controller select, FlightTable link; fixture row N8A/32 + pytest test (RED: UndefinedColumn tail_day; GREEN 126 passed). Pest tests added in HubDayTest/TailDayTest.
2. legs.js signed delays + test. npm test 24 pass (RED run skipped: test and fix written together). Build OK.
3. FlightTable "arrival delay causes: " on dep rows. 4. DayNav resets input. 5. DECISIONS reworded + new entry.
Pest (015 not applied): 16 pass; failing, all "no such column tail_day": HubDayTest "shows every ATL flight of the ATL local day" (500), "counts 899 cancellations on July 19..." (not valid Inertia response), "gives every tailed flight a tail_day"; TailDayTest "opens the tail day that holds the flight clicked on the hub" (error, undefined column).
