---
date: 2026-11-14 Asia/Ho_Chi_Minh
topic: "Reusable all-date FIRMS database and named-area backend"
status: in-progress
revision: cbfaf13ab50f91c09164b15c51208d21a819dbed
source_structure: ../structure/structure-firms-all-dates.md
related_documents:
  - ../plan/plan-firms-all-dates.md
  - ../research/research-firms-all-dates.md
  - ../../specs/time-series-api-devspec.md
  - ../../specs/time-series-api-signatures.md
---

# Detailed Implementation: reusable all-date FIRMS database

## Summary

Build a portable Python script that reads arbitrary FIRMS CSV files and publishes every valid row and date into a checked SQLite database. Add a local boundary catalog and read-only API queries for country/continent names. The new data uses three processed tables and three explicitly named 10 km grids. The older EPSG:8857 pilot remains separate.

## Source structure

The user authorized the six phases in [structure-firms-all-dates.md](../structure/structure-firms-all-dates.md) by asking to execute the plan from top to bottom. This document turns those phases into an ordered checklist. Check each item only after observing its result, then update the parent plan's corresponding checkbox.

## Current state

- The branch is `anhkhoi-dev`, at baseline commit `cbfaf13ab50f91c09164b15c51208d21a819dbed`, with existing pilot worktree edits that must be preserved.
- The current specification §10.6, `app/processed_storage.py`, and the pilot database use two tables, EPSG:8857, and area/day JSON ID arrays.
- `app/local.py` accepts only an exact configured allowlist and reduces into Python sets. It is not suitable for the all-file global build.
- `scripts/check_results.py` currently checks the pilot's two-table schema and materializes its hash input.
- The local FIRMS folder has nine CSV files totaling 7,012,980,383 bytes. Full date bounds, row count, spatial extent, polar-row count, and required disk space remain to be measured by the importer.
- Pytest collected 30 existing cases with `/private/tmp/apex-firms-venv-313/bin/python -m pytest tests --collect-only -q`. Collection does not prove they pass.

## Desired end state

1. One script, `time-series-api/scripts/preprocess_firms.py`, runs outside the repository and accepts repeated CSV-file or directory inputs, independent of filenames.
2. Every valid row is assigned once to exactly one grid: EPSG:6933 for latitude −86° through +86° inclusive, EPSG:6931 above +86°, or EPSG:6932 below −86°. Same-cell/date duplicates are deduplicated; no valid row is filtered by sensor, date, confidence, or area.
3. A newly created immutable release directory contains `database.sqlite3`, `manifest.json`, and `validation.json`. The database has exactly three user tables: `hotspot_cell`, `hotspot_cell_day`, and `daily_hotspot_summary`.
4. A pinned local catalog resolves country and continent aliases to polygons. API v2 returns paged full cell geometries and area-derived daily totals without reading CSVs, Drive, or FIRMS.
5. The nine supplied CSVs complete the same path after fixture and subset checks pass. The old pilot remains readable and recoverable.

## Scope

### In scope

- All supplied FIRMS CSV rows and acquisition dates, a filename-agnostic portable importer, a deterministic three-grid cell/day database, a local Natural Earth country/continent catalog, version-2 named-area queries, independent integrity checks, and documentation.

### Out of scope

- FIRMS or Drive downloads, retaining raw rows or FRP values, sensor harmonization, fire-event inference, observation-coverage claims, updating the old pilot in place, automatic database switching, and building or visually approving the web UI.

## Frozen decisions

- Input coordinates are longitude/latitude in EPSG:4326. Files do not embed a CRS; the importer validates degrees and transforms with `always_xy=True`.
- Use custom 10,000 m square lattices, origin `(0,0)`, floor indices, and half-open cell edges. Snap projected coordinates within 1e-6 m of a grid line before floor; the exact line belongs to the east/north cell. Canonicalize longitude +180° to −180°. Densify each projected edge at maximum 1,000 m intervals before inverse transform and clip EPSG:6933 geometry to its valid latitude domain. `grid_version` is part of every cell key. This is not a claim of matching NSIDC native pixels.
- Grid ownership at the polar boundary is deterministic: `-86 <= latitude <= 86` uses 6933; `latitude > 86` uses 6931; `latitude < -86` uses 6932.
- Any malformed required field, unreadable selected CSV, source mutation, empty input set, disk/resource exhaustion, or integrity error aborts the build. Never publish partial success or silently skip rows.
- Deduplicate only `(release_id, UTC date, grid_version, cell_id)` memberships. Multiple sensors/passes at one cell/date count once; distinct cells all remain.
- Every calendar day from observed minimum to maximum appears in the global summary. All counts carry `coverage_unknown`; zero imported records are not proof of a clear day.
- Named-area counts use `polygon.covers(cell_center)`. The result is active grid cells, not detections proven inside a political border.
- EPSG:6933 map mode cannot represent the polar bands as a valid projection. Preserve polar records and expose their grid versions; the API/client contract must state that a 6933 view cannot show them as a valid full-pole map.
- Natural Earth Admin-0 Countries 1:10m, version 5.1.1, de-facto boundaries. Store source URL, archive hash, preparation tool versions, attribution, alias map, exact continent membership, and catalog version. Catalog preparation is offline at runtime.
- No Google Drive API, FIRMS network/API requests, web geocoder, or network dependency in the importer/API runtime.

## 📐 Data flow

```mermaid
flowchart LR
    accTitle: FIRMS import and named-area query flow
    accDescr: CSV files are validated and reduced to cell and day keys in scratch SQLite, then published as a checked immutable database. A local polygon catalog drives read-only API queries.
    csv[Local FIRMS CSVs] --> importer[Portable importer]
    importer --> scratch[Temporary SQLite reduction]
    scratch --> output[Three-table release]
    names[Country or continent name] --> catalog[Local polygon catalog]
    catalog --> api[Read-only API v2]
    output --> api
    api --> geojson[Paged GeoJSON and daily summaries]
```

## Phase 1: Freeze contracts and baseline

### Detailed changes

#### 1. Record current state and decisions

- **Files:** `documents/logs/2026-11-14/plan/plan-firms-all-dates.md`, `research/research-firms-all-dates.md`, `structure/structure-firms-all-dates.md`.
- **Change:** Record the existing pilot as preserved, schema 2's approved third table, the approved phase order, and the exact three-grid latitude ownership above. Mark only verified baseline items complete.
- **Reason:** The pilot has a different CRS and schema; global IDs and interfaces must not silently reuse them.
- **Verification:** Worktree/branch/revision recorded; installed EPSG areas and three-grid boundary cases are tested later.

#### 2. Update canonical specifications before implementation

- **Files:** `documents/specs/time-series-api-devspec.md` §10.6 and terminology/revision section; `documents/specs/time-series-api-signatures.md` current-interface section.
- **Change:** Preserve the pilot contract as historical/schema 1; add the schema-2 importer, global grid versions, catalog policy, route contracts, migration boundary, and old-to-new name mapping. Change the new frontend handoff to Leaflet while keeping old pilot behavior labeled as OpenLayers/schema 1.
- **Reason:** The project names `documents/specs/` as the source of truth. Its current §10.6 contradicts the new schema and library choice.
- **Compatibility:** Do not change `/v1/hotspots/cells/query`, the pilot's EPSG:8857 grid, or its database format.
- **Verification:** Internal links, names, and signatures match code after each phase; old tests still exercise v1.

#### 3. Freeze schema, hashing, errors, and area rules

- `hotspot_cell` primary key `(grid_version, cell_id)`; columns in order: `grid_version TEXT`, `cell_id TEXT`, `column_index INTEGER`, `row_index INTEGER`, `min_x_m REAL`, `min_y_m REAL`, `max_x_m REAL`, `max_y_m REAL`, `center_longitude REAL`, `center_latitude REAL`, `geometry_json TEXT`. Set `cell_id=f"{column_index}:{row_index}"` with canonical signed decimal integers (no leading zero; zero is `0`); enforce uniqueness of `(grid_version,column_index,row_index)`, finite/range checks, and ordered projected bounds.
- `daily_hotspot_summary` primary key `(release_id, date)`; columns: `release_id TEXT`, canonical ISO `date TEXT`, `area_id TEXT CHECK(area_id='world')`, `active_cell_count INTEGER CHECK(active_cell_count>=0)`, `status TEXT CHECK(status='coverage_unknown')`, and `input_state TEXT CHECK(input_state IN ('records_present','no_records'))`. No cell-ID JSON arrays.
- `hotspot_cell_day` primary key `(release_id, date, grid_version, cell_id)`; all columns `NOT NULL`; foreign keys `(release_id,date)` to `daily_hotspot_summary` and `(grid_version,cell_id)` to `hotspot_cell`. Enable `PRAGMA foreign_keys=ON` on every writer and checker connection.
- Add exactly two secondary indexes: `hotspot_cell(center_longitude,center_latitude,grid_version,cell_id)` for bbox candidates and `hotspot_cell_day(grid_version,cell_id,release_id,date)` for selected-cell/date joins. Use `WITHOUT ROWID` for the three tables. Set `PRAGMA user_version=2`. The only user tables are the three listed; no R-tree/shadow tables or data triggers. Python validation enforces finite projected bounds/centers and geometry validity before insert; SQLite `CHECK` constraints enforce representable ranges, ordered bounds, nonnegative counts, and allowed status values.
- Logical table hashes: begin with `apex4space.firms.logical.v1\0`, UTF-8 table name plus NUL, and row count as 8-byte unsigned big-endian. Stream each table's primary-key ordered rows; encode its schema-ordered column array as canonical UTF-8 JSON (`separators=(',',':')`, `ensure_ascii=False`, `allow_nan=False`), preceded by its 8-byte unsigned big-endian byte length. Hash incrementally. `logical_sha256` is SHA-256 of canonical JSON with exactly `hash_version`, `schema_version`, `grid_policy_version`, `reduction_policy_version`, and alphabetically sorted `{name,rows,sha256}` table entries. Do not serialize the release into one Python list/string.
- Release ID is lowercase SHA-256 over UTF-8 canonical JSON, sorted keys and compact separators, for the exact object `{"grid_policy_version":"firms-ease-10km-v2","reduction_policy_version":"union-valid-cell-day-v1","schema_version":2,"source_sha256s":[sorted distinct full lowercase source hashes]}`. It excludes paths, file order, mtimes, and catalog version.
- Set `PRAGMA user_version=2`. Record schema version, release ID, source file inventory/hashes/labels, bytes and row counts, distinct/duplicate memberships, cells and per-grid counts, inclusive date bounds, dense summary days, grid definitions, policies, Python/pyproj/PROJ/Shapely versions, table hashes, and logical hash in `manifest.json`. Record row accounting, counts, SQLite integrity/FK results, exact table/index list, and logical hash result in `validation.json`. Never infer download time from local mtimes.
- Normalize input headers with BOM removal, trim, case-fold, and reject duplicate normalized headers. Required columns: `latitude`, `longitude`, `acq_date`. Validate `acq_time` when present. Ignore unused product-specific brightness names.
- Validate rectangular CSV records, finite coordinates, longitude −180..180, latitude −90..90, ISO date, and optional UTC time as 1–4 digits (`3` means `0003`). CSV reader supports UTF-8 BOM, CRLF, quoted newlines, and missing final newline; bound field/record size.
- Enumerate status/error response codes, empty-day semantics, date-out-of-range behavior, ambiguity candidates, and stable pagination cursor fields before coding.
- Catalog: Natural Earth source URL/hash and public-domain attribution; exact country unit IDs based on unique `ADM0_A3`; explicit continent membership built from source `CONTINENT` assignments and committed as IDs; common aliases; Unicode NFC/casefold/whitespace normalization; unknown=404, ambiguous=409. Save a manifest containing source/archive hash, catalog version, build-tool versions, and policy.
- **Complete when:** schema, key encoding, grid ownership, error policy, catalog provenance, and request/response examples need no implementation-time guess.

### Verification

- [x] Baseline `30` cases collected; no pass claim from collection.
- [x] Run the existing suite before Phase 2 — 30 passed, with one Starlette/httpx deprecation warning.
- [x] Check specification link targets and terminology table — no missing relative links; the schema-2 terminology map names distinct owners and migrations while preserving schema 1.

### Frozen-contract review

- [x] Schema, row/coverage rules, all grid boundaries, hashing, and errors are explicit in this document and devspec §10.7.
- [x] Natural Earth source/version/boundary policy, alias normalization, continent membership rule, geometry validation, and catalog version/hash are explicit.
- [x] API request/response fields, date limits, errors, and cursor binding are explicit in this document and the signature reference.

## Phase 2: Build the portable importer

### Proposed new files

- `time-series-api/scripts/preprocess_firms.py`: one-file, standard-library CSV/SQLite CLI plus the already pinned `pyproj==3.7.2` and `shapely==2.2.0`; do not import `app`.
- `time-series-api/tests/test_firms_importer.py`: fixtures and focused end-to-end tests for discovery through publication.

### Ordered implementation steps

#### 1. Discovery and input identity

- `discover_inputs(inputs)` accepts repeated paths. A file must be regular and `.csv` case-insensitively; directories recurse. Resolve paths, reject symlinks/special files, deduplicate canonical paths, sort deterministically, and fail if no CSV exists.
- During discovery, snapshot each file's device/inode/size/mtime-ns and full SHA-256 with bounded-memory reads; check identity before and after this hash. During CSV parsing, hash the exact bytes through the decoding reader and require equality with the discovery hash. Check identity again at EOF and re-enumerate directories before publish. This reads each source twice and catches ordinary mutation without storing rows.
- Store original path/size/hash as provenance, but compute the stable release ID from sorted distinct content hashes plus schema/grid/reduction-policy versions.

#### 2. Strict streaming CSV parse

- `read_rows(path)` uses Python `csv` with `newline=''`, UTF-8-SIG, strict quoting, normalized unique headers, maximum field size 64 KiB, maximum logical record size 1 MiB, and explicit rectangular-row validation.
- Each row receives a one-based logical record number for diagnostics; never log row contents.
- Parse only required values and optional acquisition time/compact labels. Do not require sensor names, product filename patterns, brightness fields, or version-base consistency.
- A row with invalid required fields raises an error naming the file, record, and field. No continue-and-count-skipped mode.

#### 3. Assign one grid cell per valid row

- `assign_grid_cell(longitude, latitude)` selects the grid using the inclusive ±86 rule, projects WGS84 with `always_xy=True`, checks finite projected values and valid domain, snaps within 1e-6 m of an integer cell edge, and computes `column=floor((x-origin_x)/10000)`, `row=floor((y-origin_y)/10000)`.
- Use cell ID `column:row`; grid version is a separate key component. Convert exactly +180° to −180° before projection so seam-equivalent inputs use the same side.
- Count each parsed row as assigned only after all validation/projection succeeds. Insert its `(date, grid_version, cell_id)` into scratch SQLite with conflict-ignore.
- Build each unique shape once after reduction. Densify each projected edge to at most 1,000 m between vertices, inverse-project, use Shapely normalization for stable ring/component order, split antimeridian crossings, clip EPSG:6933 cells to latitudes −86°..+86°, and validate finite coordinates and polygon geometry. Normalize negative zero before serialization. Test exact edges and seam/pole cells independently.

#### 4. Scratch reduction, bounded resources, and publication

- `build_database(...)` creates a unique sibling scratch directory/file under the output filesystem. It stores only keys and compact per-source counters; no raw row or raw attribute enters scratch.
- Insert in fixed-size batches; use primary-key conflict handling for duplicate memberships. Do not hold all keys, all shapes, or all hashes in Python collections.
- Refuse an existing output directory. Check free space before work and before publish, keeping a 512 MiB safety reserve. `--memory-budget-mib` defaults to 256 and sets bounded CSV batch/SQLite cache targets; measure peak RSS where the platform exposes it. Optional `--max-work-bytes` and `--max-output-bytes` limit temporary/final storage. Any limit exhaustion fails the release; no limit filters rows.
- Aggregate distinct shapes, dense dates, and membership counts with SQL. Create the final output in a fresh sibling directory. Insert shapes and daily summaries before memberships so foreign keys are active.
- Stream table hashes in primary-key order. Verify `PRAGMA integrity_check`, `PRAGMA foreign_key_check`, exact three user tables, shape references, daily membership equality, dense dates, source hashes, and `rows_read == rows_assigned`.
- Write `manifest.json` and `validation.json` with fsync, checkpoint/close SQLite, fsync the completed directory, and atomically rename it to the requested new output path. On failure, delete only scratch/temp paths created by this invocation; never touch inputs or prior releases.
- Release ID is the full lowercase SHA-256 of UTF-8 canonical JSON for `{"schema_version":2,"grid_policy_version":"firms-ease-10km-v2","reduction_policy_version":"union-valid-cell-day-v1","source_sha256s":[sorted distinct full lowercase hashes]}` using `sort_keys=True`, compact separators, `ensure_ascii=False`, and `allow_nan=False`. Reordering/renaming inputs with identical content must yield identical logical hashes/release ID; path provenance may differ.

#### 5. CLI and independent checker

- `main()` accepts repeated `--input` plus required new `--output-dir`. No date/area/platform filter or API key is accepted. Print a compact completion report with counts/bytes/timing, never row values.
- Add a schema-2 dispatch to `time-series-api/scripts/check_results.py`. Preserve v1 checker behavior. Schema-2 checks stream keys and rows, compare logical hashes, references, table count, dense dates, and absence of raw fields/tables.
- Common invocation from any working directory: `python /absolute/path/to/preprocess_firms.py --input /path/to/csv-or-directory --output-dir /path/to/new-release`.

### Tests

- **Location:** `tests/test_firms_importer.py`; unit tests for discovery, parser, projection, logical encoding, then an end-to-end tiny multi-file build.
- **Fixtures:** arbitrary Unicode names, nested `.CSV`, BOM/CRLF/quoted newline/no final newline, all three distinct header variants found across the nine observed files, overlapping archive/NRT rows, leap day and disjoint years, negative indices and exact boundaries, ±180 seam, ±86 ownership and both poles, malformed rows, duplicate headers, nonfinite/out-of-range coordinates, source mutation, disk limit, interrupted publish, and existing output refusal.
- **Expected result:** every valid fixture row is assigned, unique cell/day set matches an independently written expected set, database contains exactly three tables, `foreign_key_check` is empty, every date is present, and renamed/reordered/duplicate input paths produce equal logical output.
- **Small complete flow:** run the end-to-end fixture outside the repository working directory before any real subset.

### Complete when

The portable file runs standalone on a small fixture, publishes atomically, and passes its independent checker without importing `app` or opening network connections.

### Execution evidence

- [x] Stage 2.1: arbitrary recursive discovery, content hashes, identity checks, strict CSV parsing, all three observed FIRMS header variants, and fixed SQLite batches are implemented in `time-series-api/scripts/preprocess_firms.py`; mutation, overlap, BOM/CRLF, quoted-newline, and missing-final-newline fixtures pass.
- [x] Stage 2.2: the external-working-directory fixture published exactly three tables and passed `scripts/check_results.py --schema2-release-dir`; leap-day coverage, pole grids, seam geometry, foreign keys, duplicate accounting, and rename/order invariance are verified.
- [x] The all-date importer and existing API suite passed: 35 tests at the Phase 2 checkpoint. The importer is 499 lines and no function exceeds 50 lines.

## Phase 3: Prepare and load named-area polygons

### Proposed new files

- `time-series-api/scripts/prepare_world_areas.py`: offline build-time converter for the pinned Natural Earth archive.
- `time-series-api/app/areas.py`: runtime catalog loader, alias resolution, and spatial candidate selection.
- `time-series-api/config/world-areas.geojson`, `area-aliases.json`, `continent-membership.json`, and `world-areas-manifest.json`: generated, versioned catalog data with a checked manifest.
- `time-series-api/tests/test_areas.py`: local geometry/alias tests.

### Ordered implementation steps

1. [x] Obtain the official 1:10m Admin-0 Countries archive version 5.1.1, record exact URL, checksum, public-domain attribution, and source fields used. Keep the archive/build intermediate outside the runtime dataset; do not bundle downloaded source features into the hotspot SQLite database. Source link: `https://naciscdn.org/naturalearth/10m/cultural/ne_10m_admin_0_countries.zip`; SHA-256 `ce1ac7036499a0edd641fbc093cd209a98f96a49d2eca8480aaacad35138a7f6`. Natural Earth labels the Countries product version 5.1.1 and says it uses de-facto boundaries; the data are public domain. The archive has 258 features and uses `ADM0_A3`, `ADMIN`, `NAME`, `ISO_A2`, `ISO_A3`, and `CONTINENT`. [Natural Earth product](https://www.naturalearthdata.com/downloads/10m-cultural-vectors/) · [Terms](https://www.naturalearthdata.com/about/terms-of-use/)
2. [x] Pin and record pyshp 2.3.1. `scripts/prepare_world_areas.py` validates source fields/CRS/IDs and fails on invalid included geometry without repair. The full source contains invalid Egypt, outside the user-focused Viet Nam/South America scope. All selected features and their South America union validate; no invalid feature was repaired or dropped within scope.
3. [ ] Create stable `country:<ADM0_A3>` identities from the source's country units and validate ID uniqueness. Keep dependent units separately addressable. Preserve USA's represented Alaska/Hawaii pieces and Viet Nam multipolygon. Avoid sovereignty unions; ISO alpha-2/alpha-3 codes are aliases where available.
4. [ ] Generate continent member IDs deterministically from Natural Earth `CONTINENT` assignments. Include Central America and the Caribbean in North America; write the full resolved member list and any transcontinental assignments into the generated catalog. Use stable IDs for Africa, Antarctica, Asia, Europe, North America, Oceania, and South America. Union member polygons, retaining holes and disjoint parts.
5. [ ] Build aliases from source `ADMIN`, `NAME`, ISO alpha-2/alpha-3 codes, plus reviewed common names. USA aliases include `USA`, `US`, `United States`, `United States of America`; Viet Nam aliases include `VN`, `VNM`, `Vietnam`, `Viet Nam`, `Việt Nam`. Normalize Unicode NFC, case-fold, trim, and collapse whitespace. Add `America` to both North and South America; `America` and natural name collisions such as `Congo` return sorted ambiguity candidates, never first-match wins.
6. [ ] Canonically encode each generated JSON asset with sorted keys, compact separators, UTF-8, and no non-finite numbers. Compute catalog SHA-256 from domain `apex4space.world-areas.catalog.v1\0`, the source archive SHA-256 text, and each sorted asset filename, byte length, and exact bytes. Set `catalog_version=ne-admin0-10m-5.1.1-<first-16-catalog-hash>`. `world-areas-manifest.json` records source/file/catalog hashes, version, feature/member counts, and build-tool versions. `load_world_areas` validates all hashes, IDs, aliases, membership, finite WGS84 geometry, polygon validity, and bounds at startup. Cache immutable geometries only.
7. [ ] Candidate cell selection first queries each safe bbox component, handles antimeridian splits and multipolygons, deduplicates IDs, then confirms `polygon.covers(center)`. Return the full cell geometry, not a clipped count geometry.

### Tests and verification

- Check USA components, Viet Nam aliases/accents, every continent member list, North America scope, islands/holes, antimeridian, center exactly on polygon boundary, unknown name=404, ambiguous name=409, invalid catalog disables v2 routes, and catalog generation is deterministic.
- **Complete when:** generated catalog can be loaded offline, every alias resolves deterministically, and independent fixture geometry yields expected selected centers.

## Phase 4: Add version-2 API queries

### Proposed new file

`time-series-api/app/area_queries.py` owns v2 request/response models and read-only schema-2 SQL. `app/areas.py` owns catalog and geometry; `app/main.py:create_app` registers endpoints and reuses existing request guards. Add optional `storage.global_release_path` and `storage.world_areas_path` to `app/models.py:StorageSettings` and `config/settings.json`; `global_release_path` names one immutable directory containing the database and manifest, while `world_areas_path` names the four catalog assets. A request release ID must match that directory's manifest. Missing/bad v2 paths disable v2 with 503 while preserving v1. Do not alter v1 payloads or pilot paths.

### Request and response contracts

- `POST /v2/hotspots/query`: `{release_id, area_name, date, page_size?, cursor?}`. Require a 64-character lowercase hex release ID, nonempty area name up to 200 characters, canonical ISO date, strict integer page size (default `1000`, max `10000`), and cursor up to 2048 characters. Resolve area server-side. Return `release_id`, canonical `area_id`/`area_name`, `catalog_version`, date, sorted grid versions, full matching `active_cell_count`, `status`, `warnings`, a GeoJSON `FeatureCollection` (WGS84 lon/lat), `returned_count`, `has_more`, and `next_cursor`. Feature IDs combine grid version and cell ID; properties include both.
- Count all exact center matches before paging. Sort by `(grid_version, cell_id)`. Cursor payload fields are `v=2`, release ID, logical release hash, canonical area ID, catalog version, date, page size, last grid version, and last cell ID. Sign canonical JSON with HMAC-SHA-256 and the existing server cursor secret; encode as unpadded base64url payload plus signature. Reject reuse after any bound value changes.
- `POST /v2/hotspots/summaries/query`: `{release_id, area_name, start_date, end_date}` with canonical ISO dates, `start_date < end_date`, exclusive end, maximum 366 days, and the entire requested range inside the imported inclusive min/max range. Return one day entry per date, including zero `coverage_unknown` days, with exact cell-derived count and the global `input_state`. Clients request sequential windows for all history.
- Out-of-range date: 422 `DATE_UNAVAILABLE` with available range. Unknown area 404 `AREA_NOT_FOUND`; ambiguous 409 `AREA_AMBIGUOUS` plus sorted candidate IDs; schema mismatch 409 `UNSUPPORTED_SCHEMA`; invalid request 422 `INVALID_QUERY`; database unavailable/timeout 503 `DATABASE_UNAVAILABLE`/`QUERY_TIMEOUT`. Never imply zero means no fires.
- For multi-grid output, include `grid_version` on every feature and in response metadata. GeoJSON remains EPSG:4326. In EPSG:6933 map mode, warn that EPSG:6931/6932 features are outside the valid display domain; do not relabel or reproject them as 6933.

### Query behavior and tests

- Use bound SQL parameters, read-only connections, indexed cell bounds, exact Shapely `covers` center checks, then indexed membership joins. Stream candidate IDs; do not load all global shapes or all dates.
- Reuse the five-second request deadline. Measure country and continent requests on the built database before accepting query shape; timeout explicitly.
- `tests/test_area_queries.py` covers USA/Viet Nam/North America, independently calculated counts, full-count stability across pages, exact all-page ID equality, cursor binding, empty/unavailable dates, 366-day maximum, polar grid metadata, repeated identical results, and network/raw-source guards.
- **Complete when:** paged results equal the independent count and no request opens CSV, Drive, or FIRMS functions.

## Phase 5: Process every supplied CSV and verify

### Ordered execution

1. Run all new tests and the existing suite. Run a tiny multi-file fixture end-to-end, then a representative real subset from each sensor family and archive/NRT type. Record subset metrics and resolve any parser, edge, or resource defect before full ingestion.
2. Preflight the nine local inputs: recursively discover `.csv`, inventory exact paths and bytes, check free disk, then hash each full file. Do not read from Google Drive or call FIRMS.
3. Run the portable script on the entire input root, all dates and all sensors, with no filters. The output directory must be new and on a filesystem with room for scratch plus final release.
4. Save exact selected relative paths, sizes and SHA-256; rows read/assigned; invalid rows (must be zero on success); memberships before/after dedup; shape count; dense date range/day count; grid counts; bytes written; scratch peak; RSS; elapsed time; code/dependency/PROJ versions.
5. Run the schema-2 independent checker. Verify all nine source hashes and unchanged identities, `rows_read == rows_assigned`, duplicates accounted separately, all membership FKs resolve, daily count equals membership rows, all dates exist, no raw columns/tables exist, logical hashes match, and database integrity checks pass.
6. Run independent sampled/reference assignments and country/continent query comparisons. Rename/reorder a small copied fixture and verify identical logical output. Never infer geographic completeness from file names or observed extent.
7. Preserve the EPSG:8857 pilot and old selected config. Configure a distinct schema-2 database/release path only after every check passes. Keep rollback path to the pilot config. Remove only scratch paths proven owned by the completed build.

### Verification commands

Use the installed Python 3.13 environment and run from `time-series-api/`:

```sh
/private/tmp/apex-firms-venv-313/bin/python -m pytest tests --collect-only -q
/private/tmp/apex-firms-venv-313/bin/python -m pytest tests/test_firms_importer.py tests/test_areas.py tests/test_area_queries.py -q
/private/tmp/apex-firms-venv-313/bin/python -m pytest tests -q
```

Run the actual CLI and the version-2 checker commands documented by the implemented parsers, against temporary fixture outputs first and the full output second. Do not claim a command works until it has run successfully.

### Complete when

All nine source files pass a full hash/identity check; every source row is accounted for; all dates and memberships pass the independent checker; query timings and resource measurements are recorded; and the previous pilot remains usable.

## Phase 6: Document Leaflet contract and handoff

- Update `time-series-api/README.md`, canonical devspec/signatures, `database-schema-guide.html`, `database-schema.svg`, `openapi-guide.html`, and generated `openapi.json`.
- Document importer invocation, schema 2, data provenance, day/coverage semantics, country aliases, polygon-center rule, API payloads/paging, all three grid versions, and EPSG:6933's polar display limit.
- Give USA, Viet Nam, and North America request/response examples and distinguish full counts from page counts and `coverage_unknown` zero days.
- Specify Leaflet 1.9.4 with compatible Proj4Leaflet/Proj4js for a custom EPSG:6933 view; set projected bounds/origin/resolutions and place local vector background in the lowest pane. Do not use ordinary Web Mercator tiles in that view. Provide a separate polar display contract or explicitly show the API's polar warning.
- Keep external visual review pending until a reviewer performs it. No developer contact is authorized by this checklist.
- **Complete when:** docs/OpenAPI match the running schema and API; links/JSON/HTML/SVG validate; visual review is accurately recorded as pending.

## Interface and migration map

| Existing name/object | New name/object | Change | Owner and migration |
| --- | --- | --- | --- |
| `pilot-10km-v1`, EPSG:8857 | `firms-ease-global-10km-v2`, plus `firms-ease-north-10km-v2` / `firms-ease-south-10km-v2` | New grids and IDs | Schema-2 importer; rebuild, never reinterpret pilot IDs. |
| `hotspot_cell` | `hotspot_cell` | Same concept, expanded bounds/row/column/grid metadata | Schema-2 importer; separate versioned database. |
| JSON `hotspot_cell_ids` on area/day summary | `hotspot_cell_day` | New normalized relation | Importer writes; SQLite FKs enforce shape/day references. |
| area/day `daily_hotspot_summary` | global/day stored summary plus query-derived area/day response | Split scope | Importer owns world rows; API owns country/continent aggregation. |
| `discover_local_csvs` exact allowlist | `discover_inputs` recursive arbitrary CSVs | Replaced in new path | Standalone script; pilot remains intact. |
| `AreaRecord` rectangle | versioned country/continent polygon catalog | New resolver contract | `app/areas.py`; v1 pilot still uses its rectangle. |
| `/v1/hotspots/cells/query` | `/v2/hotspots/query` and `/v2/hotspots/summaries/query` | New versioned API | v1 remains compatible and unchanged. |
| OpenLayers handoff | Leaflet custom CRS handoff | User-directed library change | Only new global docs/contract; no UI implementation here. |

## Risks and recovery

- **Input mutations or malformed CSV:** could create incomplete counts. Hash/identity checks before and after, fatal error, no publish.
- **Large scratch/final database:** may exhaust disk. Preflight and repeated free-space checks; fail and clean only invocation-owned scratch; never truncate.
- **Polar map limit:** EPSG:6933 excludes the polar bands. Preserve in 6931/6932, label grids, and warn clients; a 6933 view is not a pole-complete display.
- **Natural Earth political boundaries:** de-facto map units can change or differ from legal/sovereign groupings. Pin version, record policy/attribution, expose catalog version, and rebuild rather than mutate old releases.
- **Schema/API compatibility:** pilot readers expect schema 1. Use explicit schema dispatch and separate paths; keep v1 tests and pilot artifacts intact; rollback config to prior pilot path.
- **Atomic publication failure:** output must not appear complete until verified. Build beside destination, fsync, then atomic rename; on error remove only exact owned temp paths.

## Final verification checklist

- [ ] Every checklist item in the parent plan has evidence and an `[x]`.
- [ ] Importer runs outside repository from arbitrary CSV names and completes all nine current files.
- [ ] Release has exactly three user tables, no raw detection fields, passing integrity/FK/logical hashes, complete dates, and reconciled row counts.
- [ ] USA, Viet Nam, and North America queries match independent reference counts and complete pagination.
- [ ] Existing pilot tests and database remain valid; v1 behavior is unchanged.
- [ ] Docs and generated OpenAPI/schema visuals match runtime behavior; visual review remains pending unless actually completed.
