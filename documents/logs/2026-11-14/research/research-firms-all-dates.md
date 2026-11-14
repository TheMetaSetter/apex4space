---
date: 2026-11-14
timezone: Asia/Ho_Chi_Minh
status: complete
revision: cbfaf13ab50f91c09164b15c51208d21a819dbed
branch: anhkhoi-dev
---
# Research: reusable FIRMS preprocessing and named areas

## 🔎 Findings

The current implementation is a local pilot, not an importer for all input dates. The working tree already contains the earlier pilot changes; this research does not change them. The primitive prompts were read in order: research, plan, structure, detail. This turn produces planning documents only.

The local folder contains nine CSVs totaling **7,012,980,383 bytes**. Inventory used file metadata, CSV headers, and the first 256 records per file for label inspection. It did not scan all rows, establish actual date bounds, count all detections, establish geographic extent, or check whether polar detections exist. Years in filenames are not verified date ranges.

| Group | Files | Bytes |
| --- | ---: | ---: |
| MODIS archive and NRT | 2 | 1,422,745,547 |
| Suomi-NPP archive and NRT | 2 | 3,011,855,620 |
| NOAA-20 archive and NRT | 2 | 1,823,379,062 |
| NOAA-21 archive and NRT | 2 | 748,922,750 |
| Additional global sample | 1 | 6,077,404 |

All nine have latitude, longitude, acquisition date/time, satellite, and version fields. Archive VIIRS headers use `brightness`/`bright_t31`; NRT VIIRS uses `bright_ti4`/`bright_ti5`. Sampled labels include Terra, SNPP, N20, N21, and N. An importer that derives sensor identity from filenames or demands one brightness convention will not cover these files reliably.

## 📍 Implemented evidence

| Location | Confirmed behavior |
| --- | --- |
| `time-series-api/app/local.py:66`, `discover_local_csvs` | Requires an exact relative-path/source-ID mapping. |
| `time-series-api/app/local.py:117`, `_scan_rows` | Holds daily sets and shapes in memory; filters platforms, dates, and a prepared area; requires one version base. |
| `time-series-api/app/local.py:165`, `scan_local_csv` | Streams and hashes bytes and checks unchanged file identity. These checks are useful to preserve. |
| `time-series-api/config/processed-settings.json` | EPSG:8857, one rectangle/day, two files, 80 MiB/file, 256 MiB/run, 100,000 memberships. |
| `time-series-api/scripts/prepare_data.py:167` | Release metadata includes a literal EPSG:8857 rule; changing only settings is insufficient. |
| `time-series-api/app/processed_storage.py:19`, `CELL_SCHEMA` | Two final tables; area/day summaries store JSON ID lists. |
| `time-series-api/app/processed_storage.py:75`, `_validated_processed_rows` | Materializes tuples and applies 10,000-cell/100,000-membership release limits. |
| `time-series-api/app/processed_storage.py:111`, `_release_metadata` | Materializes the complete processed hash payload in memory. |
| `time-series-api/scripts/check_results.py:66` | Expects exactly two tables and materializes rows for the processed hash. |
| `time-series-api/app/main.py:212`, `query_hotspot_cells` | Accepts a prepared area ID or contained bbox, not country-name resolution; returns one day and rejects oversized maps. |
| `time-series-api/app/cells.py:355`, `summarize_hotspots`; `make_cell_map` | Saved area/day sets, center inclusion, clipped display geometry, coverage states. |

The development spec §10.6 and prior detailed execution log describe the processed-only pilot. Older plan/structure files still say proposed/paused and are historical. The prior execution report records 30 passing cases; tests were not rerun during this planning turn.

## 🌍 Projection and boundary evidence

Installed pyproj's EPSG database reports EPSG:6933's area of use as 86°S–86°N. NSIDC documents separate global, northern, and southern EASE-Grid projections. The official EPSG webpage returned HTTP 403 during research; the installed CRS metadata and NSIDC are the available evidence. [^1]

Leaflet has a map CRS, not a separate CRS for an individual bottom layer. Proj4Leaflet supplies custom projection support; a tiled basemap must have matching projection and tile geometry. A plain local vector world background avoids requiring a new tile service. [^2][^3]

Natural Earth Admin-0 Countries provides country polygons and region fields. Its default boundaries are de facto, and country units differ from sovereign states and map units. A versioned catalog must name this choice and explicitly map continent membership and common aliases. [^4]

## ✅ Decisions for execution

1. Polar input uses three explicit 10 km grids: EPSG:6933 for −86° through +86° inclusive, EPSG:6931 above +86°, and EPSG:6932 below −86°. The user requires every valid hotspot row in the final database; this policy preserves rows beyond EPSG:6933's area of use. `grid_version` namespaces cell IDs. A Leaflet EPSG:6933 view must identify polar features as outside that view's valid domain.
2. Final schema resolved on 2026-11-14: the user approved a compact third processed cell/day membership table. This supersedes the earlier strict two-table restriction for the new release.
3. The user explicitly requested execution of the phase structure and checklist in order. The structure is approved for this execution; implementation still follows the separate detailed checklist.

[^1]: NSIDC, [A Guide to EASE Grids](https://nsidc.org/data/user-resources/help-center/guide-ease-grids).
[^2]: Leaflet, [stable 1.9.4 reference](https://leafletjs.com/reference-1.9.4.html).
[^3]: Proj4Leaflet, [custom CRS documentation](https://www.liedman.net/Proj4Leaflet/).
[^4]: Natural Earth, [Admin 0 – Countries](https://www.naturalearthdata.com/downloads/10m-cultural-vectors/10m-admin-0-countries/).

Input CRS clarification: NASA's FIRMS tutorial constructs point geometry from CSV longitude/latitude with EPSG:4326. Input degrees, projected grid metres, and map display CRS are separate contracts. [NASA FIRMS visualization tutorial](https://firms.modaps.eosdis.nasa.gov/content/academy/data_visualization/firms_visualization.html).
