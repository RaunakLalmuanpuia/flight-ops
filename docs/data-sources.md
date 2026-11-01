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
