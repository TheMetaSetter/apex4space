# Frism

A local North America fire explorer for researchers and students.
Uses plain HTML/CSS/JavaScript, OpenLayers 10.11.0 with WebGL cells, and FastAPI.

## Start

Run from `/Users/macbookofjimmy/apex4space`:

```sh
uv pip install --python .venv/bin/python -e './time-series-api[test]' pyshp==2.3.1
```

```sh
.venv/bin/python web-app/serve.py
```

Open http://127.0.0.1:8000. Stop with Ctrl+C.
The server binds only to this computer. No CDN, frontend build or tile service is needed.
The launcher makes a temporary cursor key; restarting invalidates existing daily cursors.

## Views

- Explore: search North America or a listed country; choose a UTC day.
- Compare: select two years. Maps share their view and their 1–366 active-day color scale.
- Discover: view three years of daily activity. Click a day to open its map.
  Year arrows page through all imported years, including partial years.
- Close and reopen panels for more map space. Only comparison stats scroll.
  On small screens, comparison maps use tabs and calendar months use two rows.

The calendar uses one daily-count color scale for its visible years.
Cards describe the latest year shown. Hatched days are outside the release;
zero-record days use a distinct solid color. Coverage remains unknown.
10 km cells are not wildfire counts, burned area, or finer pixels when zoomed.
The map uses EPSG:6933; polar cells outside 86°S–86°N remain in totals but are not drawn.
North America membership follows Natural Earth's continent field, including
Central America, Greenland and the Caribbean. Exact queries use cell centers.

## Local chat

Install Ollama from its official website if needed. In Terminal:

```sh
ollama serve
```

In another Terminal:

```sh
ollama pull gemma4:e2b
```

Chat uses only `http://127.0.0.1:11434/api/chat`; it has no cloud fallback.
The model plans a typed request; the backend validates it and runs fixed read-only
functions. No model SQL is executed. Daily, monthly, yearly and two-year queries
share the same data functions as the visual views. Questions use the map area,
selected date, comparison years and the last three question/answer pairs.
Data answers show exact backend stats, release ID and date coverage separately
from model prose. If Ollama is offline, the map still works. If answer generation
fails after retrieval, the retrieved results remain visible. Long answers use
page buttons, not a scrolling chat panel. General explanations are model output,
not measured database results.

## Reuse and API

`time-series-api/config/settings.json` selects the North America release and
`config/north-america` boundary catalog. The original database is unchanged.
Derived yearly results are cached in memory (six area/year results); cold reads
can take several seconds. Queries have a 30-second SQL deadline.

- `POST /v2/hotspots/query`: release_id, area_name, date, page_size, cursor.
- `POST /v2/hotspots/summaries/query`: release_id, area_name, start_date, end_date (excluded; up to 366 days).
- `POST /v2/hotspots/years/query`: release_id, area_name, year, page_size (up to 10000), offset (default 0).
  Repeat with next_offset until null. Returns annual stats, daily/monthly counts,
  full-cell GeoJSON pages, active_days per cell, partial-year and polar flags.
- `POST /v2/chat/query`: question, area_name, years (up to two), date, history (up to six strings).
  Returns answer, exact data, sources and available. The source includes release,
  area, source dates, metric definition and unknown coverage. Clarification uses
  an explicit 422 CLARIFY response.

API examples and types are at http://127.0.0.1:8000/docs.
Custom area drawing, other region releases and future Parquet are deferred.
The data reader can later change behind the shared query functions.

## Check

From `time-series-api/`:

```sh
../.venv/bin/python -m pytest -q
```

The world background is display-only Natural Earth data; exact country queries
use the checked 10m catalog. No geometry repairs were needed for North America.
OpenLayers and Proj4js are bundled in `vendor/` with their licenses.
The supplied cream Frism logo is used locally.

## Current Parquet release — 15 November 2026

Frism now reads the checked Parquet copy in
`time-series-api/data/areas/world/parquet-v1/monthly` with DuckDB. Its hashes
match the original files. Metadata and the full
validation report are in `time-series-api/data/areas/north-america/parquet-v1/`.
313 monthly files hold 150,615,549 country/cell/day rows, from 2000-11-01
through 2026-11-11. Every file passed duplicate, schema, date-partition,
coordinate-index and null checks. File hashes were checked again after integration.
The file sequence has no missing months. Source observation coverage remains unknown.

These source cells use EPSG:3857, a 10,000 metre projected lattice starting
at (0,0). Row and column use floor, including negative values. A cell's ground
area varies by latitude. Corners are transformed for the EPSG:6933 map; cells
are not regridded. At the world edges, display shapes are clipped to Mercator
bounds to keep longitude within ±180°. The source grid ID stays unchanged.

The supplied script assigns a detection to a country using `within` before
building the grid. This differs from the original SQLite cell-center rule.
The producer discarded invalid dates/coordinates, country boundary/unmatched
points, and latitudes outside ±85.0511287798066°. This release cannot recover
those rows. The supplied script documents the grid, but the original country
boundary file and raw input inventory were not provided, so their exact
provenance cannot be verified. No geometry repair or new country assignment
is performed on the Parquet rows.

North America selects the 42 codes in the checked country membership list.
40 have records; BJN and SER have none. Continent totals use distinct
`(acq_date, grid_id)` across countries. Adding country totals can overcount
border cells. For 2024 the checked reference is **91,057 unique cells and
749,373 cell-days**; its peak day is 2024-05-02 with 5,046 cells.
These results must not be mixed with the old equal-area release.

All four existing v2 endpoints select the reader using `storage.data_format`:
`parquet` or `sqlite` (default). `storage.global_release_path` selects the
release metadata folder. Daily and summary responses now also expose source
grid, cell size, membership rule, metric, source dates and equal-area flag.
Year and chat provenance carry the same values. The Parquet snapshot ID hashes
file hashes, grid rules and country membership; it is not a SQLite logical-table hash.
Signed daily cursors bind the selected snapshot and query. Restarting invalidates cursors.

The reader checks source size and modification time on each query, even for
cached year results. Changed or missing files require a new validation run.
Year aggregates have a six-entry memory cache; geometry is built only for the
requested page. Queries open only intersecting months, allow two concurrent
DuckDB scans, use 512 MiB per scan and stop SQL work after 30 seconds.
A real 2024 query returned all 91,057 cell shapes in 2.58 seconds in the local
API check; browser and disk speed may differ.

To validate a new copy of this exact Parquet format, run from the project root:

```sh
.venv/bin/python time-series-api/scripts/prepare_parquet.py --input /path/to/fire_grid_daily --output-dir time-series-api/data/areas/north-america/parquet-v2 --catalog time-series-api/config/north-america --producer-script /path/to/producer.py
```

The output directory must be new. This validator expects one Parquet file
per month and a continuous sequence of monthly partitions. It refuses bad
input rather than silently skipping it. It publishes metadata only.

### Return to the original SQLite release

Stop the server, run this from the project root, then start it again:

```sh
cp time-series-api/config/settings-sqlite.json time-series-api/config/settings.json
```

```sh
.venv/bin/python web-app/serve.py
```

The saved settings select `data_format: sqlite` and
`data/areas/north-america/release-1`. The original database is retained.
Live Gemma generation still needs local Ollama running with `gemma4:e2b`;
the Parquet chat context and exact results are covered by tests with a model stub.

## Global date ranges — current version

Frism now starts at **World** and supports 230 source country codes, seven
geographic groups, and World. Country lookup uses source country codes,
not a new spatial join. Continent groups follow Natural Earth's country-level
classification; transcontinental countries are not split into smaller parts.
Every source code matched a name. Egypt's invalid outline is omitted; Egypt's
country data and search still work. No geometry is repaired.

Explore has From and To dates. **Both dates are included.** The One day button
sets To equal to From. Compare has two independent From/To pairs plus year
shortcuts. Ranges can overlap, be separate, be identical, or have different
lengths. Shared dates remain in both results. Do not add the two comparison
results to produce a union. Average daily active cells divides cell-days by
selected UTC days, not by satellite observation opportunities. Coverage remains
unknown. Longer ranges can have larger totals.

Use the new shared endpoint:

```text
POST /v2/hotspots/ranges/query
```

```json
{
  "release_id": "50589b4e46f939cc682ffb4e6bf940fad69e95e25a1a908a1074ab675adad721",
  "area_name": "World",
  "start_date": "2024-01-01",
  "end_date": "2024-12-31",
  "include_geometry": false
}
```

The result has selected_days, unique_active_cells, total_cell_days,
average_daily_active_cells, peak_date, peak_count, daily counts and month totals.
It also identifies the source grid, dates, release and lookup catalog version.
`include_geometry: true` adds paged cell shapes with active_days. Use offset and
page_size (up to 10000); repeat with next_offset until null. An optional WGS84
bbox `[west,south,east,north]` limits shapes to the viewport. West > east crosses
the date line. Summary totals always cover the full selected area. A null
visible_active_cells means geometry was not requested; it does not mean zero.

The date-range endpoint requires Parquet. Existing single-day and yearly
Parquet routes share its aggregation; old daily/summary API end dates retain
their original meanings. The legacy summary API still has a 366-day limit.
Range requests may span the whole release. Multi-year requests combine disjoint
yearly aggregates, preserving exact daily country unions. The range cache has
three entries. SQL uses 512 MiB per scan, up to 2 GiB of temporary disk in a
cleaned system temp folder, two concurrent scans and a 30-second SQL timer.
Long-range work also checks a 30-second budget between yearly chunks. If a
limit is reached, the request returns a clear error asking for a smaller area
or shorter range; it never silently shortens dates or returns partial totals.
Total process memory includes Python aggregates and the cache, not just SQL.

Maps below zoom 2.5 show an overview and a zoom prompt. At higher zoom, only
visible detailed cells are paged in; movement reloads them. Loading messages
and the loaded count distinguish map progress from whole-area statistics.
Compare uses a shared active-day scale across both selected ranges. Calendar
year requests load statistics rather than every cell shape. All panels retain
the existing open/close controls and only comparison stats scroll.

Chat accepts an additional `ranges` list containing up to two objects with
start_date and end_date. The model can choose range or compare_ranges intents;
the server validates them and uses the same data functions. Exact stats and
selected dates are returned with each source separately.

### Checked global reference

- World, 2024-02-29: 30,798 cells (0.08 seconds locally).
- World, 2024: 656,093 cells; 11,233,633 cell-days (1.94 seconds locally).
- Viet Nam, 2024: 3,634 cells; 71,684 cell-days (0.24 seconds locally).
- World, 2000-11-01 through 2026-11-11: 1,397,448 cells and 150,115,992
  cell-days (27 seconds locally after year chunking; about 1.42 GB process peak).

Independent monthly DISTINCT counts and a separate unique-grid query match
the full-history totals. Times vary with machine load and disk speed.

Current settings use `config/global` and `data/areas/world/parquet-v1`.
The release metadata references the same original Parquet files; no data was
copied or regridded. The snapshot ID is unchanged because source data is unchanged.
To return to North America scope, stop the server, then run:

```sh
cp time-series-api/config/settings-north-america.json time-series-api/config/settings.json
```

```sh
.venv/bin/python web-app/serve.py
```

The page detects the available catalog and starts at North America in that
mode. `settings-sqlite.json` still restores the original SQLite APIs, but the
new date-range web controls require Parquet.

A live local Gemma comparison was also checked: North America 2024-02-27
through 2024-02-29 returned 5,422 cell-days, and the overlapping 2024-02-28
through 2024-02-29 range returned 3,366. The model explained both correctly
with exact backend stats and source dates attached (3.53 seconds locally).
Planning disables thinking and allows 1,000 output tokens to avoid truncated
JSON; selected UI ranges fill an incomplete comparison plan. Explicit valid
model range pairs are still validated before querying.

Current verification: 57 tests pass. Phone layouts fit 390x844 without page
scrolling. Hidden comparison panes request only stats; choosing a pane loads
its visible cells. Viewport filters compare the original grid indices before
building GeoJSON, avoiding conversion of off-screen shapes.

The header Ask button opens chat in every view. The comparison starter sends
`compare_selected: true` so the backend queries the two current ranges directly;
Gemma only explains the results. Free-text questions retain model planning.
Calendar chat uses the latest displayed calendar year. Final suite: 58 tests passed.
