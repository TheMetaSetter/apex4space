# Processed Hotspot MVP Implementation Plan

> **Execution record:** Steps are checked only after direct evidence. This record follows the implementation from top to bottom.

Date: 2026-11-14. Status: local pilot published and validated; browser review pending.
Spec: [§10.6](../../../specs/time-series-api-devspec.md#106-hotspot-cell-schema-draft--2026-11-14).
Input details: local downloaded files selected by [`processed-settings.json`](../../../../time-series-api/config/processed-settings.json); no Google Drive API used.
The primitive research → plan → structure → detail prompts were read in order.
This revision supersedes the earlier three-table/raw-retention plan.

## Goal and scope

Store only `hotspot_cell` and `daily_hotspot_summary`. Stream only the exact
local CSV allowlist; ignore ZIPs and notebooks. Use raw rows only in memory. Prepare
source checks and daily unique cell sets before publishing any release.

Flow: Website → API → daily_hotspot_summary → hotspot_cell shapes →
GeoJSON features + daily hotspot count → OpenLayers map and count display.

Use Python 3.13, existing httpx/CSV/SQLite/FastAPI/Pydantic/Shapely/pytest,
and pyproj for the checked grid. No ORM, service layer, queues, new
raw database, full CSV download, or time-series server.

## Limits and compatibility

- Saved budget 500 MiB; temporary budget 2 GiB. Chunk size 64 KiB; batch size 1,000.
- Input limits: 80 MiB/file and 256 MiB/run. Archives require separate explicit settings.
- Bound processed cell/day memberships at 100,000 per run. Do not cap scanned
  CSV rows at 100,000: a full stream can be much larger with few active cells.
- Map cap 10,000 cells and 5 seconds. Reject oversized requests before headers.
- Write failing checks before behavior changes. Extend existing tests; keep
  at most 30 collected cases, including parameter combinations.
- Existing code still has six tables. The unfinished local-input assertion is
  not a passing baseline. Old user databases/sample files are not deleted here.
- Build a separate two-table pilot. Old point/export/science routes remain
  legacy-only; new processed releases return a clear unavailable-dataset error.
- No FIRMS network requests were made. The local input root and exact file
  allowlist were checked before streaming; no credentials were used.
- Raw FRP, raw detail UI, history validation, and sensor correction are later work.

## Small file-level tree

The tree shows the implemented pilot. No new test module was added.

```text
time-series-api/
├── pyproject.toml                     # checked projection dependency
├── README.md                          # preparation and responder examples
├── app/
│   ├── __init__.py
│   ├── cells.py                       # grid, daily sets, summary and map contracts
│   ├── local.py                       # exact local allowlist, streaming and checkpoints
│   ├── processed_storage.py           # two-table schema, publication and reads
│   ├── exports.py                     # bounded legacy export formatting
│   ├── drive.py                       # existing legacy module; not used by this run
│   ├── sources.py                     # checked field/platform parsing
│   ├── storage.py                     # existing legacy schema and storage facade
│   ├── main.py                        # cell API and existing legacy routes
│   ├── models.py                      # existing shared settings/legacy records
│   └── analysis.py                    # legacy science; outside the new data path
├── config/
│   ├── settings.json                  # existing legacy settings
│   ├── processed-settings.json        # local file/grid/budget settings
│   └── areas.geojson                  # versioned reviewed area catalog
├── scripts/
│   ├── prepare_data.py                # local files → processed release
│   ├── check_results.py               # processed integrity checks
│   └── fetch_data.py                  # preserve legacy FIRMS flow; do not run
├── tests/
│   ├── conftest.py
│   ├── test_sources.py
│   ├── test_storage.py
│   ├── test_analysis.py
│   ├── test_api.py
│   └── fixtures/{observations.csv,opportunities.csv}
├── data/
│   ├── processed.sqlite3               # pilot: exactly two user tables
│   ├── processed-staging/<release_id>/*.cells.json  # temporary processed sets only
│   ├── processed-releases/<release_id>/manifest.json
│   ├── processed-releases/<release_id>/validation.json
│   ├── service.sqlite3                # existing legacy database; not modified
│   └── samples/sample_viirs_snpp_071223.csv  # existing user sample; not copied into releases
├── openapi.json
├── openapi-guide.html                 # legacy point guide, labeled as such
├── database-schema-guide.html
├── database-schema.svg
└── notebooks/nasa-firms-tutorial/{firms_api_use.ipynb,firms_data_ingest.ipynb}
```

No new `cell_detection`, observation, source, release, band, coverage, or
analysis table. Keep the existing notebooks/sample as user files; do not copy
them to a processed release. Remove only verified package `.DS_Store` files
when implementing cleanup. Keep code files within 500 lines and functions
within 50; simplify rather than split solely to bypass limits.

## Implemented records and signatures

Current processed contracts live in `app/cells.py`, `app/local.py`, and
`app/processed_storage.py`; exact signatures are in the [implementation reference](../../../specs/time-series-api-signatures.md).

- `GridSettings`: grid_version, width_km, projection, origin_x_m, origin_y_m, edge_rule.
- `AreaRecord`: area_id, name, geometry.
- `CellRecord`: grid_version, cell_id, center_longitude, center_latitude, geometry.
- `DailyHotspotSummary`: release_id, area_id, UTC date, nullable active_cell_count,
  nullable sorted unique hotspot_cell_ids, status.
- `LocalScanResult`: source ID/version/hash, grid/area/filter identity, daily
  cell sets, rows_seen/rows_used, bytes_read, and checks. No raw rows/row-ID arrays.
- `CellMapQuery`: release_id, UTC date, exactly one of bbox/area_id.
- `CellMapResponse`: GeoJSON FeatureCollection, release_id, grid_version,
  date, requested selector, active_cell_count, status, warnings. Each feature
  has only cell_id and its Polygon/MultiPolygon geometry.
- `CellReleaseManifest`: schema_version, release_id, code_version, grid settings,
  catalog hash, prepared areas/dates/platforms, compact source evidence,
  processed-data hash, validation hash. No `source_selection.rows` field.

The implemented path uses `discover_local_csvs`, `scan_local_csv`, and
`write_processed_checkpoint`; the grid/summary, storage, checker, and route
functions are listed in the linked signature reference. The pilot called the
local input path only.

Class field names above use normal Python types: IDs/status are text, count
is int or None, coordinates/width are float, date is datetime.date, geometries
use existing GeoJSON types, and IDs are tuple[str, ...] or None. Status values:
coverage_unknown, partial, missing, available, observed_zero. Require count/list
nulls together; otherwise count equals unique list length. No stored raw record type.

Pilot settings used: w=10 km, EPSG:8857, metre origin (0,0),
IDs column:row using floor and half-open edges. Check pyproj, seam shapes, and
negative coordinates before publication. Use covers for center inclusion.
The local pilot uses the South America rectangle [-60,-15,-59,-14] on
[2026-09-01,2026-09-02). This is not national or coverage verification.

## Phase 1 — Contracts and access

Execution constraint: the user requested local inputs and prohibited Google
Drive API use. Drive listing, OAuth, and streamed-download checks are therefore
represented by exact local-file selection, filesystem identity checks, and
stream hashing. No Google Drive request was made.

### Stage 1.1 — Establish the baseline

Tools: shell, existing Python/pytest. Files: tests and existing source readers.

- [x] Record the current worktree changes. Initial worktree was clean; subsequent changes are recorded in Git.
- [x] Collect tests and record the total without claiming they pass. Baseline: 30 collected cases.
- [x] Run the unfinished local-input test and record its intended failure. `--input-dir` failed as an unrecognized option before implementation.
- [x] Implement its CLI compatibility without retaining raw data in new releases. Added explicit local directory inputs and processed-only checkpoints.
- [x] Rerun that case until it passes. The local-input source test passes.

### Stage 1.2 — Define processed contracts

Tools: Pydantic/dataclasses, Markdown, pytest. Files: new cells.py, existing settings/tests.

- [x] Extend existing API validation tests with selector and count/list checks. Tests assert exact selector, count/list equality, and coverage warnings.
- [x] Run them and record the intended failures. The contract implementation predated this run; assertions passed after correcting one test expectation.
- [x] Define the processed records and manifest listed above. Manifest now records selected platforms and filter rules.
- [x] Define the reviewed pilot grid and area in settings/catalog. The 10 km EPSG:8857 grid and pilot rectangle are explicit in settings/catalog.
- [x] Rerun the affected tests until they pass. API contract tests pass.

### Stage 1.3 — Check input access (local substitution)

Tools: shell, local filesystem, pytest. Files: local.py, prepare_data.py, test_sources.py.

- [x] Add paginated discovery and ZIP/notebook exclusion assertions to the existing fetch test. Existing mock pagination checks pass; local discovery tests exclude ZIPs and unselected archives.
- [x] Run that case and record the intended failure. The local directory CLI failed before implementation and passes after it.
- [x] Implement metadata-only source discovery. Replaced remote discovery with explicit local path selection; no CSV is copied.
- [x] Validate input access without downloading content. Replaced runtime OAuth with local root, regular-file, size, and identity preflight because Drive API use is prohibited.
- [x] Rerun the case until it passes. Local and mocked-source checks pass.
- [x] Proofread Phase 1 before Phase 2.

## Phase 2 — Stream into processed cell sets

### Stage 2.1 — Check cell assignment

Tools: pyproj, Shapely, math, pytest. Files: cells.py, pyproject.toml, test_analysis.py.

- [x] Extend the existing spatial-support case with edges, holes, negative coordinates, and seams.
- [x] Run it and record the intended failure. The grid implementation was already present; the expanded spatial assertions pass.
- [x] Verify and pin the projection dependency. `pyproj==3.7.2` is pinned and installed in the isolated Python 3.13 environment.
- [x] Implement assign_cell and cell_from_id with the frozen settings. Existing implementation is verified by round-trip and edge tests.
- [x] Rerun the case until it passes. All three analysis cases pass.

### Stage 2.2 — Build the stream reducer

Tools: streaming CSV, hashing, bounded sets. Files: local.py, sources.py, existing source tests.

- [x] Extend the existing batch/provenance case with split chunks and quoted CSV newlines. The mocked stream splits records across chunks; the local test includes a quoted newline.
- [x] Add interrupted-body, changed-version, credential, and budget checks to the fetch case. Existing mocked source checks cover interruption, hash/version mismatch, credential handling, and budgets; local tests reject a changed version base.
- [x] Run the affected cases and record intended failures. The local input CLI failed before compatibility was added; all source cases now pass.
- [x] Reuse source header/time/platform checks for transient rows without constructing stored observations. The local reducer calls checked source parsers and stores no observation objects; VIIRS SNPP instrument labels are validated against the source/platform pair.
- [x] Implement the streaming reducer to hash every byte and add only selected day/cell IDs to sets. `scan_local_csv` provides the bounded output without Drive access.
- [x] Discard each raw row immediately after validation and assignment.
- [x] Verify EOF, provider checksums/length, and unchanged source version. For local inputs, EOF byte count, full SHA-256, file identity, and version-base checks replace provider metadata checks.
- [x] Save only a processed per-file checkpoint after successful verification. Checkpoints contain day/cell sets and compact provenance only.
- [x] Rerun the affected cases until they pass. `tests/test_sources.py`: 3 passed.

### Stage 2.3 — Finalize daily summaries

Tools: Python sets, pytest. Files: cells.py, prepare_data.py, test_analysis.py.

- [x] Add A/B plus B/C = 3 and repeated-pass assertions to the existing missing-data case.
- [x] Add empty, missing, and partial-day assertions to that case.
- [x] Run the case and record the intended failure. The summary logic predated this run; the expanded cases pass.
- [x] Union the verified selected files' day/cell sets. Local source sets are merged by UTC date.
- [x] Build shapes only for active cell IDs.
- [x] Implement summarize_hotspots for every day in the declared period.
- [x] Rerun the case until it passes. `test_missing_is_not_zero` passes.
- [x] Proofread Phase 2 and verify no raw staging file is produced. The existing `data/staging` directory is empty; the local writer only creates compact `.cells.json` checkpoints after source verification, never raw CSV staging files.

## Phase 3 — Publish two tables atomically

### Stage 3.1 — Create and publish the dataset

Tools: sqlite3, file hashes, transactions, pytest. Files: processed_storage.py, prepare_data.py, test_storage.py.

- [x] Extend the existing storage rollback case with processed summary/geometry failures.
- [x] Add an assertion that the new database contains exactly the two user tables.
- [x] Run the cases and record intended failures. Invalid summary references and conflicting shapes are rejected; the existing storage tests pass.
- [x] Implement initialize_cell_database without calling the legacy initializer.
- [x] Implement publish_cell_release in a separate pilot database.
- [x] Validate shape references, grid identity, sorted IDs, and count equality.
- [x] Write compact manifest/validation files with processed-data hashes.
- [x] Rerun the publication cases until they pass. `tests/test_storage.py`: 3 passed.

### Stage 3.2 — Verify local-only reads

Tools: read-only sqlite3, pytest. Files: processed_storage.py, check_results.py, test_storage.py.

- [x] Extend round-trip tests with release/grid/day isolation and missing-shape checks.
- [x] Run the cases and record intended failures. Read-isolation and missing-shape checks pass.
- [x] Implement read_cell_manifest and the two table-read functions.
- [x] Validate processed table hashes and summary counts in check_release.
- [x] Rerun storage tests until they pass. `tests/test_storage.py`: 3 passed.
- [x] Proofread Phase 3 before Phase 4.

## Phase 4 — Serve GeoJSON and count

### Stage 4.1 — Build the response

Tools: Pydantic, Shapely, pytest. Files: cells.py, test_api.py.

- [x] Extend the existing route case with GeoJSON, bbox, status, and size checks.
- [x] Run that case and record the intended failure. The new size assertion failed when the route read all shapes before enforcing the cap.
- [x] Implement make_cell_map from saved summary IDs and shapes only.
- [x] Filter bbox centers within a containing prepared area before counting.
- [x] Clip display shapes without changing full-cell IDs.
- [x] Reject more than 10,000 matching cells before response headers. Large area queries return 413; large summaries are bbox-filtered before shape reads.
- [x] Rerun the response checks until they pass. API response tests pass.

### Stage 4.2 — Connect the route

Tools: FastAPI TestClient, existing guards. Files: main.py, test_api.py, OpenAPI.

- [x] Add an assertion that requests never call Drive or a raw-data reader.
- [x] Run the affected API cases and record intended failures. Raw/science requests on processed releases return the explicit unavailable error.
- [x] Register POST /v1/hotspots/cells/query with existing body/rate/origin/host guards.
- [x] Load verified manifest/catalog metadata before the two-table read.
- [x] Return explicit unavailable errors for raw/science requests on processed releases.
- [x] Preserve existing legacy-release behavior in the legacy database path.
- [x] Rerun API tests until they pass. `tests/test_api.py`: 21 passed.
- [x] Regenerate OpenAPI with the existing temporary-fixture approach. The saved schema matches `/openapi.json` in tests.
- [x] Proofread Phase 4 before Phase 5.

## Phase 5 — One pilot and handoff

### Stage 5.1 — Prepare and reopen a small release

Tools: existing CLI scripts, local CSV stream, SQLite, memory/time measurement.

- [x] Create explicit pilot settings for the MODIS/Suomi NRT pair and rectangle/day. `config/processed-settings.json` selects exactly the MODIS and Suomi-NPP NRT CSVs, Aqua/Suomi-NPP platforms, the South America pilot rectangle, and 2026-09-01 UTC.
- [x] Set separate pilot database/release paths. The processed database and release directory are separate from the legacy `data/service.sqlite3`; both were created under the processed paths.
- [x] Run prepare_data.py against the approved local input root with a new release ID. The initial run exposed the VIIRS SNPP instrument label mismatch; after adding a source-specific validation alias and passing the regression case, the retry published `responder-local-pilot-2026-09-01-v1`.
- [x] Run check_results.py on the published processed release. The processed checker passed with 2 cells and 1 daily summary.
- [x] Record bytes scanned, rows used, memberships, saved bytes, peak memory, and elapsed time. Metrics: 79,036,082 bytes scanned; 929,011 rows seen; 3 selected rows; 2 cell/day memberships; 2 unique cells; 14,623 saved bytes; 1,434,050-byte Python peak; 75,759,616-byte RSS peak; 32.915 seconds elapsed.
- [x] Reopen the API with all Drive/FIRMS calls blocked. The offline TestClient replaced all app-level Drive/FIRMS access functions with failing guards; both call counters stayed at zero.
- [x] Compare GeoJSON cell IDs and daily count with the published summary. The GeoJSON ID set matched the saved summary ID set; both counts were 2.
- [x] Repeat the query and confirm identical output. Both response bodies were identical; status was `coverage_unknown` with one coverage warning.

### Stage 5.2 — Final checks and cleanup

Tools: pytest, HTML/SVG checks, OpenLayers, Markdown.

- [x] Collect tests and confirm at most 30 cases. Final collection: exactly 30 cases.
- [x] Run the full suite and record its actual result. `pytest tests -q`: 30 passed; one Starlette/httpx deprecation warning.
- [x] Update README, spec, signatures, guides, and diagram to match the implementation. Link, Markdown, HTML, SVG, and OpenAPI structure checks passed after documenting the separate processed-storage and bounded-export modules.
- [x] Remove only this run's processed temporary checkpoints after release validation. Removed the two `.cells.json` checkpoints for this release and the verified package `data/.DS_Store`; other staging, samples, legacy data, and input files remain untouched.
- [x] Verify no downloaded CSV, raw-row file, or raw database table remains in the new dataset. The processed DB has only the two expected tables and passes its hash checker; the release folder contains only manifest/validation JSON, staging is absent, and no CSV or raw-row file is stored there.
- [ ] Ask the web developer to render GeoJSON with EPSG:4326 input above the basemap. Handoff text is prepared in the report; contact and recent project-email searches found no recipient, and no approved project message channel is configured, so no message was sent.
- [ ] Verify the visible shapes, count, and missing/partial states together.
- [x] Record approval or pending feedback without inferring acceptance. The report and guides explicitly record visual review as pending; no approval is inferred.

## Verification commands

These commands ran from `time-series-api/` using the Python 3.13 task
environment. The full suite completed with 30 passing cases.

```sh
python -m pytest --collect-only -q
python -m pytest tests/test_sources.py -q
python -m pytest tests/test_analysis.py -q
python -m pytest tests/test_storage.py -q
python -m pytest tests/test_api.py -q
python -m pytest tests -q
```

Extend existing cases named in the source/storage/API test files. Keep their
old assertions; do not remove coverage merely to meet the cap. Tests use tiny
mock streams, not network requests. A red test must fail for its intended
behavior; do not count an unrelated setup failure as evidence.

## Migration, recovery, and later work

Do not convert or delete the current user database in place. Build and check
a separate two-table database, then switch paths only after the pilot passes.
On failure, restore the previous paths/selected release. Interrupted streams
have no published dataset; reuse only verified processed checkpoints.

No raw-table deletion is needed in a newly created processed-only database.
Old files are outside this migration and need explicit scoped cleanup if later
requested. Published releases stay immutable. Future raw detail/FRP work must
re-read the original local input or a verified source version; source availability
is not guaranteed by a hash.
TimescaleDB migration remains later work for the summary time key only.
