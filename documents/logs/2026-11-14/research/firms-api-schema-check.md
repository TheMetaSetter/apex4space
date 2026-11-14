# FIRMS API schema check

Date: 2026-11-14. Five keyed FIRMS API requests were made, which is the
user's limit for this work. The [request ledger](firms-api-request-ledger.json)
contains the request results. It contains no key or access-bearing URL.

The first status response reported 0 of 5,000 transactions used in a
10-minute interval. The last reported 9. The key may be shared, so the change
is not proof of the exact cost of each request. The limit and the planned
pause at 4,000 remain in force. Do not make another API request under this
five-request authorization.

The availability response had the columns `data_id`, `min_date`, and
`max_date`. It reported MODIS NRT from 2026-09-01 through 2026-11-13 and
S-NPP NRT from 2026-08-01 through 2026-11-02. These are the response's dates,
not claims about satellite lifetime.

Two one-day responses were saved under the ignored staging folder:

| Source | UTC date | Rectangle [west, south, east, north] | Bytes | Rows |
| --- | --- | --- | ---: | ---: |
| VIIRS_SNPP_NRT | 2026-09-01 | [106, 10, 107, 11] | 122 | 0 |
| MODIS_SP | 2026-03-01 | [104, 20, 105, 21] | 127 | 0 |

The VIIRS header has `bright_ti4` and `bright_ti5`. The MODIS header has
`brightness`, `bright_t31`, and `type`. Both have latitude, longitude, scan,
track, acquisition date and time, satellite, instrument, confidence, version,
FRP, and day/night. The ledger records the exact column order and file hashes.
Neither response contains a data row. They do not confirm row values, source
versions, coverage, or absence of fire. The saved samples have not yet passed
through the planned offline publication and API flow.

NASA documents the [area API](https://firms.modaps.eosdis.nasa.gov/api/area):
its dated request includes the start date and `DAY_RANGE - 1` later days. It
also documents the [availability API](https://firms.modaps.eosdis.nasa.gov/api/data_availability/).

A separate existing local VIIRS sample was read without an API request. It has
74,605 rows for 2023-07-12. All rows use satellite code `N`; 69,507 rows use
version `2.0NRT` and 5,098 use `2.0URT`. Thus, one NRT source file can contain
more than one row version. The reader must preserve each row's version and
check the collection and the allowed versions. This older sample is not a
new pilot download.

## Data access for later work

For this project, the user permits the implementation work to read
`FIRMS_MAP_KEY` from the repository `.env` when a FIRMS download is needed.
Never print, copy, commit, or place the key in a URL, log, report, or command
example. Check the provider's current transaction count before a request.
The limit is 5,000 transactions per 10 minutes. Keep requests small and stop
at the configured pause point. Five FIRMS API requests have already been
used for this work; this run must make no more.

The user also permits reading CSV files in Google Drive at
`Shared with me / NASA Space Apps Challenge / Data`. Four NRT CSV files were
previewed in bounded 256 KiB ranges. Those previews confirmed the shared
columns and satellite labels `Terra`/`Aqua`, `SNPP`, `N20`, and `N21`. They did
not cover the full files. In the Drive VIIRS export, `bright_t31` remains an
unverified band mapping. Do not treat it as I5 or use it to validate band
harmonization without checking an authoritative source.

The Drive CSV archives are large. Read only the rows or byte ranges needed for
a small check. Do not download or unpack the full archives for the MVP.
Retain file identity, date range, checksum, and the fact that a read was
partial when recording any sample derived from them.
