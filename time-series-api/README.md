# Time-series API

This API is under development. It is not ready to serve data.

## Setup

Run these commands from the repository root:

```bash
uv pip install --python .venv/bin/python -e './time-series-api[test]'
.venv/bin/python -m pytest time-series-api/tests -q
```

The settings file is `config/settings.json`. Paths in this file are relative to
`time-series-api/`. The file contains no keys. Set private keys in the runtime
environment when the data download and server are ready.

The initial settings use rectangle `[106, 10, 107, 11]` and dates
`2026-09-01` to `2026-09-03` (end date is not included). Each request window
is at most two days. No source IDs are selected, so fetch is a no-op. Data
availability has not been checked. The selected release and science method
are empty. A science method needs independent tests before it can be used.

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

## Offline source commands

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
The current settings have no source IDs, so the fetch command downloads
nothing until an operator selects them. The fetch command reads
`FIRMS_MAP_KEY` from the environment first, then the repository `.env`; never
pass it as an argument. The transaction pause is 4,000 within a provider
window of 600 seconds. Availability checks reserve five transactions, based
on the current NASA usage example.

Preparation publishes source rows only. It advertises no daily metric until
a grid and a checked method are available. The check command verifies the
published release and its saved source files. It does not rewrite a report.

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
