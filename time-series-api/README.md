# Time-series API

This API is under development. The cell map works with the saved local sample.
The Drive pilot is pending a fresh Google Drive token.

## Setup

Run these commands from the repository root:

```bash
uv pip install --python .venv/bin/python -e './time-series-api[test]'
.venv/bin/python -m pytest time-series-api/tests -q
```

The settings file is `config/settings.json`. Paths in this file are relative to
`time-series-api/`. The file contains no keys. A FIRMS key is needed only for
a live download. Serving also needs a private `CURSOR_SECRET`.

The current settings use rectangle `[106, 10, 107, 11]` and the single day
`2026-09-01`. They select `VIIRS_SNPP_NRT` and the checked source-only release
`responder-viirs-empty-2026-09-01-v1`. Its saved FIRMS response has a valid
header and zero rows. This is not evidence of a clear-sky day: coverage is
unknown and the release has no available metrics. Do not use it for a fire
severity decision.

## Test data

The CSV files in `tests/fixtures/` contain invented data. `observations.csv`
uses a small FIRMS MODIS-style schema. `opportunities.csv` is a test
interchange format: it stores GeoJSON areas in CSV fields. It is not a native
satellite product and does not prove actual coverage.

The CSV reader uses the field names and satellite codes in the NASA
[MODIS](https://firms.modaps.eosdis.nasa.gov/content/descriptions/FIRMS_MODIS_Firehotspots.html)
and [VIIRS](https://firms.modaps.eosdis.nasa.gov/content/descriptions/FIRMS_VIIRS_Firehotspots.html)
descriptions. It keeps the original fields and full row versions. MODIS
`brightness` and `bright_t31` map to channels 21/22 and 31. VIIRS
`bright_ti4` or `brightness` maps to I4; `bright_ti5` or `brightness_2` maps
to I5. A VIIRS export field named `bright_t31` is kept as unverified. A VIIRS
I4 value of 367 K is marked as a possible sensor limit; the value stays
unchanged.

## Processed cell dataset

The processed path stores only `hotspot_cell` and `daily_hotspot_summary` in
`data/processed.sqlite3`. The separate legacy database is unchanged. Release
hashes and source details stay in small JSON files.

The checked local sample can build a small map release:

```bash
.venv/bin/python time-series-api/scripts/prepare_data.py --settings time-series-api/config/processed-settings.json --release-id local-sample-v1 --input-csv time-series-api/data/samples/sample_viirs_snpp_071223.csv --source-id VIIRS_SNPP_NRT --start-date 2023-07-12 --end-date 2023-07-13 --area-id sample-africa --platforms Suomi-NPP
```

Check its metadata and tables:

```bash
.venv/bin/python time-series-api/scripts/check_results.py --settings time-series-api/config/processed-settings.json --release-id local-sample-v1 --processed
```

The sample produced 1,720 hotspot cells for 2023-07-12. Coverage is unknown;
this is a software pilot, not a fire or sensor-coverage claim. The web route
reads these two tables only:

```bash
curl -X POST http://127.0.0.1:8000/v1/hotspots/cells/query \
  -H 'Content-Type: application/json' \
  -d '{"release_id":"local-sample-v1","date":"2023-07-12","area_id":"sample-africa"}'
```

The response has one GeoJSON feature per hotspot cell and `active_cell_count`.
OpenLayers can read the feature geometries as EPSG:4326.

The Drive command uses an explicit folder ID and reads
`GOOGLE_DRIVE_ACCESS_TOKEN` from the environment or repository `.env`:

```bash
.venv/bin/python time-series-api/scripts/prepare_data.py --settings time-series-api/config/processed-settings.json --release-id drive-pilot-v1 --drive-folder-id 1_RbaB1o7lrmOlzsp8CGq34Oe_rQ_lKMc
```

The current token is expired. Refresh it before using this command. It reads
only the two CSV IDs in `processed-settings.json` and does not read ZIPs or
notebooks.

## Legacy source commands

Run these from the repository root after setting a checked source, area, and
date window in `time-series-api/config/settings.json`:

```bash
.venv/bin/python time-series-api/scripts/fetch_data.py
.venv/bin/python time-series-api/scripts/prepare_data.py --release-id pilot-source-v1
.venv/bin/python time-series-api/scripts/check_results.py --release-id pilot-source-v1
```

The settings file is the default for all three commands. `--settings PATH` is
an explicit override. `--release-id` is required for preparation and checks.
Downloads use a 30-second timeout and up to two retries. They pause at 4,000
reported transactions in the provider's 600-second window. A single download
can use at most 2 GiB of temporary storage; saved source files can use at most
500 MiB. Source CSVs are read in batches of 1,000 rows. The configured maximum
input size is 100,000 rows.
The current settings contain one source ID. Seven FIRMS HTTP requests have
been used for this work: five exploration requests, then two approved resume
checks. The last two checked status and availability, then reused the saved
file. They did not request fire rows. Do not run the fetch command again
unless the team allows more requests. The fetch command reads
`FIRMS_MAP_KEY` from the environment first, then the repository `.env`; never
pass it as an argument.
It checks the provider's transaction count. An availability request reserves
five transactions, based on NASA's usage example.

Preparation publishes source rows only. It advertises no daily metric until
a grid and a checked method are available. The check command verifies the
published release and its saved source files. It does not rewrite a report.

## Saved empty response check

The saved one-day VIIRS response is 122 bytes with zero data rows. Its hash is
`2b11a44667d05367ecf77651b95fd3d34c545c7ec154856094b91245e41ae697`.
The original sample request took 1.363 seconds. The five-request exploration
ended at 9 reported transactions on a shared key. The approved resume command
made two HTTP requests and did not measure the transaction change. It reused
the saved response, took 2.48 seconds, and used at most 49,430,528 bytes of
resident memory. No third request was made to read the shared counter.
Preparation and integrity checks passed for the source-only release. A local
API check returned an empty GeoJSON point page with `has_more=false`; the CSV
export had the same zero rows. There were no source records to compare by ID,
date, or FRP. The release has no analysis metrics, and the map response does
not provide coverage. Treat this result as unknown coverage.

## Early web requests

These requests use invented values. Replace `local-release` with a published
release ID. Send rectangle bounds in EPSG:4326 order: west, south, east, north.

```bash
curl http://127.0.0.1:8000/v1/metrics
```

```bash
curl -X POST http://127.0.0.1:8000/v1/analysis \
  -H 'Content-Type: application/json' \
  -d '{"release_id":"local-release","bbox":[106,10,107,11],"start_date":"2024-03-01","end_date":"2024-03-02","metric":"observed_hotspot_count","aggregation":"day","platforms":["Aqua"]}'
```

```bash
curl -X POST http://127.0.0.1:8000/v1/hotspots/query \
  -H 'Content-Type: application/json' \
  -d '{"release_id":"local-release","bbox":[106,10,107,11],"start_date":"2024-03-01","end_date":"2024-03-02","platforms":["Aqua"],"page_size":1000}'
```

When `has_more` is true, send the returned `next_cursor` with the same point
query to get the next page. A cursor is valid only for that query.

Download the same rectangle as CSV:

```bash
curl -X POST http://127.0.0.1:8000/v1/exports \
  -H 'Content-Type: application/json' \
  -d '{"release_id":"local-release","bbox":[106,10,107,11],"start_date":"2024-03-01","end_date":"2024-03-02","kind":"observations","format":"csv","platforms":["Aqua"]}' \
  -o time-series-observations.csv
```

For analysis JSON, use the analysis fields above and add
`"kind":"analysis","format":"json"`. These download values are invented.

The generated schema is in [`openapi.json`](openapi.json). It is built from a
temporary test release and checked against `/openapi.json`; it has no live data
or keys. The live server needs a selected release before it can start. Record
web developer feedback during the later map handoff.

### Web review status

The web developer approved only the emergency responder map feature. The
rectangle request and point paging are covered by that approval. The developer
has not approved downloads. The map review closes the map-focused review in T6;
download review remains for the full web handoff in T13. Please check that the
examples can:

1. **Approved in T6: emergency responder map.** Send a rectangle query with longitude and latitude in the correct order; read hotspot points and request the next page with the returned cursor.
2. **Pending for T13: downloads.** Download the same selection as CSV or analysis JSON.

Record any confusing field or failed request here after review. The examples use
invented values; a live request also needs a selected release.
