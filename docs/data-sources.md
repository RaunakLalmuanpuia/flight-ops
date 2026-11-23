# Data sources

Field notes from the files loaded on 2026-11-01. Everything here was observed in the files, except where a note says otherwise. Row counts come from `dq.ingestion_run`.

Every file is UTF-8 with a header row. Column names in `raw` are the source headers in lowercase, with runs of other characters replaced by `_`.

## BTS Reporting Carrier On-Time Performance

- **File:** `On_Time_Reporting_Carrier_On_Time_Performance_(1987_present)_2024_7.csv`, from `https://transtats.bts.gov/PREZIP/On_Time_Reporting_Carrier_On_Time_Performance_1987_present_2024_7.zip`
- **Obtained:** scripted, about 5 minutes.
- **Table:** `raw.bts_ontime`, 634,613 rows, 109 columns.
- **SHA-256:** `08894d7a211469ff69234ea0ba5c8bad1abe565d0bfe3f1b547798a605078173`
- **Trailing comma:** every row ends in one, which reads as a 110th blank column. The loader drops it.
- **Carrier column:** there is no operating-carrier column. `reporting_airline` is the carrier code, and regional operators report under their own code: at ATL, `9E` has 3,821 flights separately from `DL`'s 41,363.
- **`2400` times:** 57 ATL flights have it in a scheduled or actual departure or arrival time. Counting `wheelsoff` and `wheelson` too makes it 109, so staging must handle all six columns.

### August 2024

- **File:** `..._2024_8.csv` from the matching PREZIP URL. **Obtained:** scripted, about 2 minutes, no refusal.
- **Table:** `raw.bts_ontime` gains 619,025 rows (0 quarantined), 12,714 cancelled. SHA-256 `a154c46b18d8dad0be6bbc30d9d01c840de697650b909e563475fc3a8d622d44`.
- **Role:** the holdout month. `ontology.period` names it `august`.

## FAA aircraft registry

- **Files:** `MASTER.txt`, `ACFTREF.txt` and `DEREG.txt`, from `https://registry.faa.gov/database/ReleasableAircraft.zip`
- **Obtained:** by hand. A curl header request returned 403. The files are dated 2026-10-30 on disk, which is the closest thing to a snapshot date.
- **Format:** comma-separated `.txt` with a byte order mark, fixed-width padding inside each field (`[100  ]`, `[A004B3    ]`) and a trailing comma on each row.

| Table | Rows | Columns | SHA-256 |
|---|---|---|---|
| `raw.faa_master` | 318,181 | 34 | `2dcb13d2b3373ab8b7a89751149db9a687d7d176643e0b0007a1eda53ff2675e` |
| `raw.faa_acftref` | 94,162 | 13 | `beb27403b03fcba4024bcd752d79ab94c899f59cae34beda360d8ebb4658f03d` |
| `raw.faa_dereg` | 383,685 | 38 | `ead53c6fdbc3a291fbad738293837c05258e407b6bb2dbb273e81643f002ce36` |

- **`MASTER` and `DEREG` differ:** they don't share a layout, for example `last_action_date` against `last_act_date`, and `DEREG` has `cancel_date`.
- **Repeated tails in `DEREG`:** 383,685 rows cover only 301,255 distinct `n_number` values, so one tail can have several deregistrations. `MASTER` has one row per tail. Step 4 has to pick by date.
- **One malformed row:** `DEREG.txt` line 200876, `N54096`, has the unquoted city `NASSAU, NP`, which shifts every later field by one. It is in `dq.quarantined_row` and is not repaired.

## OurAirports

- **File:** `https://davidmegginson.github.io/ourairports-data/airports.csv`
- **Obtained:** scripted.
- **Table:** `raw.ourairports_airports`, 86,329 rows, 19 columns, no timezone column.
- **SHA-256:** `1aab80ccfa203a0d02476c16ac282d9e787cf3d08700d7365c5c5502a0db8ba7`
- **Current codes, not 2024 codes:** West Palm Beach is `DJT`/`KDJT` here, while BTS July 2024 calls it `PBI` on 4,112 flights. Its `ident` is still `KPBI`. It is the only one of the 342 BTS airports with no IATA match, and no BTS airport matches two rows.

## Iowa Environmental Mesonet

- **Obtained:** scripted, one request per file. Both cover June 30 to August 1 UTC, so joins at both ends of July have data.

| Table | Request | Rows | SHA-256 |
|---|---|---|---|
| `raw.iem_metar` | `asos.py`, station `ATL` | 10,496 | `a649dab62de73ec7579e980767d717be086eed4acf445ca4ff6f4ad7f86a2494` |
| `raw.iem_taf` | `taf.py`, station `KATL` | 2,767, from 444 products | `544fcccf3830211d0b4c48384285c981ad2a2363615518c278b5802ab686bf75` |

- **METAR noise:** 9,493 rows are 5-minute `MADISHF` records, leaving 1,003 others for staging to keep.
- **Station codes:** the METAR endpoint takes `ATL` and the TAF endpoint takes `KATL`.
- **TAF shape:** one row per forecast group, so `product_id` identifies the whole forecast.

### August 2024

- **Obtained:** scripted. Both files cover August 2 to September 1 UTC (IEM's end date is exclusive), so they never overlap the July files, as `staging.metar`'s primary key requires.
- `raw.iem_metar` gains 9,642 rows (SHA-256 `bd4faf29635837e553d68ff26991cb2d722c65a11d0505b2f6c097ac79a0aa5d`), `raw.iem_taf` 1,712 rows (SHA-256 `1b10acd9f1c31820be9cd73d4f3278abcc7b41cbe46809f2b97c7ee9ca0ad513`).

## Measured July 2024 build (before August was loaded)

From `python -m flightops all`. A second `build` gave identical hashes of `ontology.flight` and `ontology.rotation_leg`. All six blocking checks pass.

| Staging and ontology | Value |
|---|---|
| Flights, national and raw-to-ontology difference | 634,613, difference 0 |
| Touching ATL | 60,144 |
| Cancelled July 19-23 touching ATL | 3,208 |
| Operated flights with no tail | 0 (3,658 cancelled flights have none) |
| Scheduled block disagrees with `hhmm` | 316 |
| Scheduled arrival at or before scheduled departure | 61 |
| Actual departure `hhmm` matches `depdelay` | 616,756 of 616,756 |
| Actual elapsed time differs from the time difference by over 1 minute | 7 |
| METARs kept and `MADISHF` filtered | 1,003 and 9,493 |
| METAR gaps over 90 minutes | 0 |
| Airports, carriers, airframes | 345, 15, 7,280 |
| Delay rows, TAF rows | 309,046, 2,767 |

| Tail to airframe | Flights | Tails |
|---|---|---|
| `window_exact`, high | 587,617 | 5,274 |
| `single_airframe_outside_window`, medium | 34,653 | 292 |
| `window_open_start`, medium | 1,002 | 8 |
| Unresolved: `no_window_multiple_airframes` | 6,965 | 57 |
| Unresolved: `no_faa_record` | 399 | 7 |
| Unresolved: `ambiguous_window` | 319 | 3 |

Tails can appear under more than one method across dates. Matched flights split into 597,959 active and 25,313 deregistered only. On flights touching ATL, 317 of 59,992 with a tail are unresolved.

| Rotations | Value |
|---|---|
| Legs | 616,241 |
| Consecutive pairs, national | 610,617, of which 602,697 connect (98.70%) |
| Consecutive pairs on tails that touched ATL | 374,452, of which 370,112 connect (98.84%) |
| `likely_unreported_flying` | 5,533 |
| `long_gap_unreported_or_out_of_service` | 2,088 |
| `after_diversion` | 277 |
| `short_gap_likely_data_error` | 14 |
| `overlap_data_error` | 8 |

**METAR parsing:** one report has a malformed wind group (`080/05KT`), so its wind stays null.

| ATL weather join | Value |
|---|---|
| Events: scheduled and actual departures | 30,072 and 28,322 |
| Events: scheduled and actual arrivals | 30,072 and 28,250 |
| Total, and with no earlier METAR | 116,716, and 0 |
| Age of the METAR: maximum, and over 90 minutes | 59 minutes, and 0 |

A throwaway database built from the same raw files with `migrate`, `load` and `build` gave identical hashes of `ontology.flight`, `ontology.rotation_leg` and `ontology.flight_weather`. The full report is `docs/phase-1-report.md`.

**Diversions:** 113 flights stopped short nationally, none at or bound for ATL. All 179 diversions bound for ATL reached it.

## OpenSky Network

- **Obtained:** scripted, with `python -m flightops collect`, using OAuth2 client credentials from `.env`.
- **Files and table:** `data/raw/opensky/KATL_{arrival,departure}_YYYY-MM-DD.csv`, one per UTC day, into `raw.opensky_flight`.
- **Terms:** the user read the terms of use on 2026-11-01 and confirmed this use is allowed. The site refuses automated fetches of that page, so the pipeline's author didn't read them directly. The API docs allow "research and non-commerical purposes".
- **Citation:** public work using this data should cite Schäfer, Strohmeier, Lenders, Martinovic and Wilhelm, "Bringing Up OpenSky: A Large-scale ADS-B Sensor Network for Research", IPSN 2014, pages 83-94.

| Finding | Evidence | Design consequence |
|---|---|---|
| Each query costs 30 credits, whatever its length or result | 1-hour and 24-hour queries, and a 404, each cost 30. Remaining went from 3,970 to 3,790 over 6 queries | Query whole days. Two a day costs 60 credits, as the roadmap estimated |
| History reaches back at least to July 2024 | Rows returned for 30 days ago, 365 days ago and 2024-07-19 | **Corrects the roadmap**, which feared history might not be recoverable. The daily job is not urgent |
| OpenSky corroborates the outage, in the one hour tested | ATL arrivals 12:00-13:00 UTC on 2024-07-19: BTS 21, with 1 DL or 9E. OpenSky 27, with 2 `DAL` or `EDV`. BTS on July 12 and 26 shows 81 and 85, with 66 and 67 | Backfill July 2024. It is independent evidence for the report, if the rest of the month holds up |
| Coverage looks good for a recent day | 2026-10-31: 997 arrivals and 861 departures | Reasonable, but no BTS file exists yet for that date to compare with |
| A day with no data yet returns 404 | Today's 00:00 UTC hour returned 404 with body `[]` and still cost 30 | 404 means "not ready": write no file, and retry on the next run |
| Some fields can be blank | 2 of 84 arrivals had no `estDepartureAirport` | Stored blank in raw |

### July 2024 backfill against BTS

62 files, 66,680 rows. Every arrival file row names `KATL` as its arrival and every departure file row names it as its departure. 22 rows have no callsign. These are counts of ATL arrivals by UTC day, not a flight-by-flight match.

| Day | BTS | OpenSky | BTS DL and 9E | OpenSky `DAL` and `EDV` |
|---|---|---|---|---|
| 2024-07-01 | 722 | 1099 | 555 | 780 |
| 2024-07-02 | 891 | 1058 | 658 | 752 |
| 2024-07-03 | 921 | 1088 | 678 | 772 |
| 2024-07-04 | 846 | 991 | 606 | 685 |
| 2024-07-05 | 730 | 891 | 542 | 634 |
| 2024-07-06 | 840 | 1015 | 624 | 727 |
| 2024-07-07 | 943 | 1109 | 698 | 797 |
| 2024-07-08 | 994 | 1186 | 758 | 864 |
| 2024-07-09 | 989 | 1167 | 762 | 872 |
| 2024-07-10 | 1009 | 1167 | 757 | 837 |
| 2024-07-11 | 977 | 1148 | 738 | 826 |
| 2024-07-12 | 1021 | 1194 | 778 | 866 |
| 2024-07-13 | 968 | 1150 | 739 | 846 |
| 2024-07-14 | 930 | 1095 | 695 | 787 |
| 2024-07-15 | 1033 | 1198 | 787 | 875 |
| 2024-07-16 | 1035 | 1195 | 791 | 877 |
| 2024-07-17 | 923 | 1101 | 699 | 789 |
| 2024-07-18 | 933 | 1125 | 708 | 804 |
| 2024-07-19 | 706 | 842 | 482 | 525 |
| 2024-07-20 | 581 | 748 | 355 | 436 |
| 2024-07-21 | 577 | 745 | 348 | 430 |
| 2024-07-22 | 688 | 811 | 443 | 497 |
| 2024-07-23 | 821 | 1004 | 587 | 686 |
| 2024-07-24 | 971 | 1161 | 735 | 825 |
| 2024-07-25 | 1023 | 1201 | 772 | 864 |
| 2024-07-26 | 1033 | 1187 | 782 | 865 |
| 2024-07-27 | 988 | 1176 | 752 | 864 |
| 2024-07-28 | 890 | 1050 | 661 | 755 |
| 2024-07-29 | 1034 | 1190 | 786 | 879 |
| 2024-07-30 | 1057 | 1217 | 812 | 897 |
| 2024-07-31 | 958 | 1123 | 726 | 807 |

**Reading it:**

- **The two sources agree on the shape of the month.** From July 2 to 31, the daily correlation is 0.994 for all arrivals and 0.996 for Delta and Endeavor.
- **The outage shows in both, independently.** Delta and Endeavor arrivals against the same weekday a week earlier:

| Day | BTS drop | OpenSky drop |
|---|---|---|
| July 19 | 38% | 39% |
| July 20 | 52% | 48% |
| July 21 | 50% | 45% |
| July 22 | 44% | 43% |
| July 23 | 26% | 22% |

- **OpenSky counts run higher,** by 15-29% overall and 9-24% for Delta and Endeavor. It includes flying BTS doesn't, such as business jets and cargo, but that doesn't obviously explain the Delta and Endeavor gap. This is unexplained until flights are matched individually in phase 4.
- **July 1 is an edge effect.** BTS has 0 arrivals before 06:00 UTC against OpenSky's 195, because those are June 30 local flights and the BTS file holds July flight dates only.
