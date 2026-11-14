# Processed Hotspot MVP Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans. Execute each unchecked step in order. This document does not start implementation.

Date: 2026-11-14. Status: proposed; implementation paused.
Spec: [§10.6](../../../specs/time-series-api-devspec.md#106-hotspot-cell-schema-draft--2026-11-14).
Input details: [Drive CSV plan](../plan/plan-drive-csv-preprocessing.md).
The primitive research → plan → structure → detail prompts were read in order.
This revision supersedes the earlier three-table/raw-retention plan.

## Goal and scope

Store only `hotspot_cell` and `daily_hotspot_summary`. Read raw CSVs directly
from Drive; ignore ZIPs and notebooks. Use raw rows only in memory. Prepare
source checks and daily unique cell sets before publishing any release.

Flow: Website → API → daily_hotspot_summary → hotspot_cell shapes →
GeoJSON features + daily hotspot count → OpenLayers map and count display.

Use Python 3.13, existing httpx/CSV/SQLite/FastAPI/Pydantic/Shapely/pytest,
and proposed pyproj for the checked grid. No ORM, service layer, queues, new
raw database, full CSV download, or time-series server.

## Limits and compatibility

- Saved budget 500 MiB; temporary budget 2 GiB. Chunk size 64 KiB; batch size 1,000.
- Drive limits: 80 MiB/file, 256 MiB/run including retries. Archives require larger explicit settings.
- Bound processed cell/day memberships at 100,000 per run. Do not cap scanned
  CSV rows at 100,000: a full stream can be much larger with few active cells.
- Map cap 10,000 cells and 5 seconds. Reject oversized requests before headers.
- Write failing checks before behavior changes. Extend existing tests; keep
  at most 30 collected cases, including parameter combinations.
- Existing code still has six tables. The unfinished local-input assertion is
  not a passing baseline. Old user databases/sample files are not deleted here.
- Build a separate two-table pilot. Old point/export/science routes remain
  legacy-only; new processed releases return a clear unavailable-dataset error.
- No new FIRMS requests: the seven approved requests are used.
- Runtime Drive credentials are a preflight gate; chat connector access is
  not a Python OAuth session. Never log credentials or access-bearing URLs.
- Raw FRP, raw detail UI, history validation, and sensor correction are later work.

## Small file-level tree

`+` means proposed new file. Other files exist. No new test module is needed.

```text
time-series-api/
├── pyproject.toml                     # checked projection dependency
├── README.md                          # preparation and responder examples
├── app/
│   ├── __init__.py
│   ├── cells.py                    +  # grid, daily sets, summary and map contracts
│   ├── drive.py                    +  # Drive listing, streaming and source checks
│   ├── sources.py                     # reuse checked field/platform parsing
│   ├── storage.py                     # two-table SQL, publication and reads
│   ├── main.py                        # cell API and existing legacy routes
│   ├── models.py                      # existing shared settings/legacy records
│   └── analysis.py                    # legacy science; outside the new data path
├── config/
│   ├── settings.json                  # explicit Drive/grid/budget settings
│   └── areas.geojson               +  # versioned reviewed area catalog
├── scripts/
│   ├── __init__.py
│   ├── prepare_data.py                # Drive → processed release
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
│   ├── service.sqlite3                # generated pilot: exactly two user tables
│   ├── staging/drive/progress.json     # temporary completed-file metadata
│   ├── staging/drive/<identity>.cells.json  # temporary processed sets only
│   ├── releases/<release_id>/manifest.json
│   ├── releases/<release_id>/validation.json
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

## Proposed records and signatures

New records live in `app/cells.py`; these are not implemented symbols.

- `GridSettings`: grid_version, width_km, projection, origin_x_m, origin_y_m, edge_rule.
- `AreaRecord`: area_id, name, geometry.
- `CellRecord`: grid_version, cell_id, center_longitude, center_latitude, geometry.
- `DailyHotspotSummary`: release_id, area_id, UTC date, nullable active_cell_count,
  nullable sorted unique hotspot_cell_ids, status.
- `ProcessedSource`: source ID/version/hash, grid/area/filter identity, daily
  cell sets, rows_seen/rows_used, bytes_read, and checks. No raw rows/row-ID arrays.
- `CellMapQuery`: release_id, UTC date, exactly one of bbox/area_id.
- `CellMapResponse`: GeoJSON FeatureCollection, release_id, grid_version,
  date, requested selector, active_cell_count, status, warnings. Each feature
  has only cell_id and its Polygon/MultiPolygon geometry.
- `CellReleaseManifest`: schema_version, release_id, code_version, grid settings,
  catalog hash, prepared areas/dates/platforms, compact source evidence,
  processed-data hash, validation hash. No `source_selection.rows` field.

```python
# app/cells.py
load_area_catalog(path: Path) -> tuple[AreaRecord, ...]
assign_cell(longitude: float, latitude: float, grid: GridSettings) -> CellRecord
cell_from_id(cell_id: str, grid: GridSettings) -> CellRecord
summarize_hotspots(day_cells: Mapping[date, frozenset[str]], *,
                   release_id: str, area_id: str, start_date: date,
                   end_date: date, day_states: Mapping[date, str]) -> tuple[DailyHotspotSummary, ...]
make_cell_map(query: CellMapQuery, summary: DailyHotspotSummary,
              cells: Sequence[CellRecord], *, grid_version: str,
              selection: AreaGeometry) -> CellMapResponse
# app/drive.py: exact stream settings in the Drive plan.
scan_drive_csv(file: DriveFile, *, client: httpx.Client, grid: GridSettings,
               area: AreaRecord, start_date: date, end_date: date,
               platforms: tuple[str, ...], maximum_bytes: int,
               maximum_memberships: int) -> ProcessedSource
# app/storage.py
initialize_cell_database(path: Path) -> None
publish_cell_release(path: Path, cells: Iterator[CellRecord],
                     summaries: Iterator[DailyHotspotSummary],
                     manifest: CellReleaseManifest, *, storage: StorageSettings) -> None
read_cell_manifest(releases_path: Path, release_id: str) -> CellReleaseManifest
read_hotspot_summary(path: Path, release_id: str, area_id: str, day: date) -> DailyHotspotSummary
read_hotspot_cells(path: Path, grid_version: str, cell_ids: Sequence[str]) -> tuple[CellRecord, ...]
# Existing scripts/main: proposed updated entry points.
prepare_release(settings: Settings, release_id: str, *,
                drive_folder_id: str | None = None, input_csv: Path | None = None,
                input_source: str | None = None) -> None
check_release(settings: Settings, release_id: str) -> dict[str, object]
query_hotspot_cells(query: CellMapQuery, request: Request) -> CellMapResponse
```

Class field names above use normal Python types: IDs/status are text, count
is int or None, coordinates/width are float, date is datetime.date, geometries
use existing GeoJSON types, and IDs are tuple[str, ...] or None. Status values:
coverage_unknown, partial, missing, available, observed_zero. Require count/list
nulls together; otherwise count equals unique list length. No stored raw record type.

Pilot defaults proposed by the plan: w=10 km, EPSG:8857, metre origin (0,0),
IDs column:row using floor and half-open edges. Check pyproj, seam shapes, and
negative coordinates before publication. Use covers for center inclusion.
The Drive pilot is the honestly named South America rectangle [-60,-15,-59,-14]
on [2026-09-01,2026-09-02). This is not national or coverage verification.

## Phase 1 — Contracts and access

### Stage 1.1 — Establish the baseline

Tools: shell, existing Python/pytest. Files: tests and existing source readers.

- [ ] Record the current worktree changes.
- [ ] Collect tests and record the total without claiming they pass.
- [ ] Run the unfinished local-input test and record its intended failure.
- [ ] Implement its CLI compatibility without retaining raw data in new releases.
- [ ] Rerun that case until it passes.

### Stage 1.2 — Define processed contracts

Tools: Pydantic/dataclasses, Markdown, pytest. Files: new cells.py, existing settings/tests.

- [ ] Extend existing API validation tests with selector and count/list checks.
- [ ] Run them and record the intended failures.
- [ ] Define the processed records and manifest listed above.
- [ ] Define the reviewed pilot grid and area in settings/catalog.
- [ ] Rerun the affected tests until they pass.

### Stage 1.3 — Check Drive access

Tools: existing httpx, Drive API, pytest. Files: new drive.py, prepare_data.py, test_sources.py.

- [ ] Add paginated discovery and ZIP/notebook exclusion assertions to the existing fetch test.
- [ ] Run that case and record the intended failure.
- [ ] Implement the metadata-only discovery described in the Drive plan.
- [ ] Validate runtime OAuth access without downloading content.
- [ ] Rerun the case until it passes.
- [ ] Proofread Phase 1 before Phase 2.

## Phase 2 — Stream into processed cell sets

### Stage 2.1 — Check cell assignment

Tools: pyproj, Shapely, math, pytest. Files: cells.py, pyproject.toml, test_analysis.py.

- [ ] Extend the existing spatial-support case with edges, holes, negative coordinates, and seams.
- [ ] Run it and record the intended failure.
- [ ] Verify and pin the projection dependency.
- [ ] Implement assign_cell and cell_from_id with the frozen settings.
- [ ] Rerun the case until it passes.

### Stage 2.2 — Build the stream reducer

Tools: httpx, streaming CSV, hashing, bounded sets. Files: drive.py, sources.py, existing source tests.

- [ ] Extend the existing batch/provenance case with split chunks and quoted CSV newlines.
- [ ] Add interrupted-body, changed-version, credential, and budget checks to the fetch case.
- [ ] Run the affected cases and record intended failures.
- [ ] Reuse source header/time/platform checks for transient rows without constructing stored observations.
- [ ] Implement scan_drive_csv to hash every byte and add only selected day/cell IDs to sets.
- [ ] Discard each raw row immediately after validation and assignment.
- [ ] Verify EOF, provider checksums/length, and unchanged source version.
- [ ] Save only a processed per-file checkpoint after successful verification.
- [ ] Rerun the affected cases until they pass.

### Stage 2.3 — Finalize daily summaries

Tools: Python sets, pytest. Files: cells.py, prepare_data.py, test_analysis.py.

- [ ] Add A/B plus B/C = 3 and repeated-pass assertions to the existing missing-data case.
- [ ] Add empty, missing, and partial-day assertions to that case.
- [ ] Run the case and record the intended failure.
- [ ] Union the verified selected files' day/cell sets.
- [ ] Build shapes only for active cell IDs.
- [ ] Implement summarize_hotspots for every day in the declared period.
- [ ] Rerun the case until it passes.
- [ ] Proofread Phase 2 and verify no raw staging file is produced.

## Phase 3 — Publish two tables atomically

### Stage 3.1 — Create and publish the dataset

Tools: sqlite3, file hashes, transactions, pytest. Files: storage.py, prepare_data.py, test_storage.py.

- [ ] Extend the existing storage rollback case with processed summary/geometry failures.
- [ ] Add an assertion that the new database contains exactly the two user tables.
- [ ] Run the cases and record intended failures.
- [ ] Implement initialize_cell_database without calling the legacy initializer.
- [ ] Implement publish_cell_release in a separate pilot database.
- [ ] Validate shape references, grid identity, sorted IDs, and count equality.
- [ ] Write compact manifest/validation files with processed-data hashes.
- [ ] Rerun the publication cases until they pass.

### Stage 3.2 — Verify local-only reads

Tools: read-only sqlite3, pytest. Files: storage.py, check_results.py, test_storage.py.

- [ ] Extend round-trip tests with release/grid/day isolation and missing-shape checks.
- [ ] Run the cases and record intended failures.
- [ ] Implement read_cell_manifest and the two table-read functions.
- [ ] Validate processed table hashes and summary counts in check_release.
- [ ] Rerun storage tests until they pass.
- [ ] Proofread Phase 3 before Phase 4.

## Phase 4 — Serve GeoJSON and count

### Stage 4.1 — Build the response

Tools: Pydantic, Shapely, pytest. Files: cells.py, test_api.py.

- [ ] Extend the existing route case with GeoJSON, bbox, status, and size checks.
- [ ] Run that case and record the intended failure.
- [ ] Implement make_cell_map from saved summary IDs and shapes only.
- [ ] Filter bbox centers within a containing prepared area before counting.
- [ ] Clip display shapes without changing full-cell IDs.
- [ ] Reject more than 10,000 matching cells before response headers.
- [ ] Rerun the response checks until they pass.

### Stage 4.2 — Connect the route

Tools: FastAPI TestClient, existing guards. Files: main.py, test_api.py, OpenAPI.

- [ ] Add an assertion that requests never call Drive or a raw-data reader.
- [ ] Run the affected API cases and record intended failures.
- [ ] Register POST /v1/hotspots/cells/query with existing body/rate/origin/host guards.
- [ ] Load verified manifest/catalog metadata before the two-table read.
- [ ] Return explicit unavailable errors for raw/science requests on processed releases.
- [ ] Preserve existing legacy-release behavior in the legacy database path.
- [ ] Rerun API tests until they pass.
- [ ] Regenerate OpenAPI with the existing temporary-fixture approach.
- [ ] Proofread Phase 4 before Phase 5.

## Phase 5 — One pilot and handoff

### Stage 5.1 — Prepare and reopen a small release

Tools: existing CLI scripts, Drive stream, SQLite, memory/time measurement.

- [ ] Create explicit pilot settings for the MODIS/Suomi NRT pair and proposed rectangle/day.
- [ ] Set separate pilot database/release paths.
- [ ] Run prepare_data.py with the root Drive folder ID and a new release ID.
- [ ] Run check_results.py on the published processed release.
- [ ] Record bytes scanned, rows used, memberships, saved bytes, peak memory, and elapsed time.
- [ ] Reopen the API with all Drive/FIRMS calls blocked.
- [ ] Compare GeoJSON cell IDs and daily count with the published summary.
- [ ] Repeat the query and confirm identical output.

### Stage 5.2 — Final checks and cleanup

Tools: pytest, HTML/SVG checks, OpenLayers, Markdown.

- [ ] Collect tests and confirm at most 30 cases.
- [ ] Run the full suite and record its actual result.
- [ ] Update README, spec, signatures, guides, and diagram to match the implementation.
- [ ] Remove only this run's processed temporary checkpoints after release validation.
- [ ] Verify no downloaded CSV, raw-row file, or raw database table remains in the new dataset.
- [ ] Ask the web developer to render GeoJSON with EPSG:4326 input above the basemap.
- [ ] Verify the visible shapes, count, and missing/partial states together.
- [ ] Record approval or pending feedback without inferring acceptance.

## Verification commands

These are existing commands; proposed symbols above are not implemented yet.

```sh
.venv/bin/python -m pytest time-series-api/tests --collect-only -q
.venv/bin/python -m pytest time-series-api/tests/test_sources.py -q
.venv/bin/python -m pytest time-series-api/tests/test_analysis.py -q
.venv/bin/python -m pytest time-series-api/tests/test_storage.py -q
.venv/bin/python -m pytest time-series-api/tests/test_api.py -q
.venv/bin/python -m pytest time-series-api/tests -q
```

Extend existing cases named in the source/storage/API test files. Keep their
old assertions; do not remove coverage merely to meet the cap. Tests use tiny
mock streams, not real Drive requests. A red test must fail for its intended
behavior; do not count an unrelated setup failure as evidence.

## Migration, recovery, and later work

Do not convert or delete the current user database in place. Build and check
a separate two-table database, then switch paths only after the pilot passes.
On failure, restore the previous paths/selected release. Interrupted streams
have no published dataset; reuse only verified processed checkpoints.

No raw-table deletion is needed in a newly created processed-only database.
Old files are outside this migration and need explicit scoped cleanup if later
requested. Published releases stay immutable. Future raw detail/FRP work must
re-read a verified Drive version; source availability is not guaranteed by a hash.
TimescaleDB migration remains later work for the summary time key only.
