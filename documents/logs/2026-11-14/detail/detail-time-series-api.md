# Detailed implementation plan: time-series-api

Date: 2026-11-14. Status: engineering can start; data and science gates remain.
Branch at planning: `anhkhoi-dev`; HEAD `c3bf05efa0f0d0ec7e8be76d853a1e0ea8a62e66`.
No implementation, dependency install, provider download, or runtime test ran
while writing this plan. All execution checkboxes below are intentionally open.

## Read first

Read [spec v0.4](../../../specs/time-series-api-devspec.md),
[signatures](../../../specs/time-series-api-signatures.md),
[file tree](../../2026-11-13/structure/time-series-api-directory-tree.md),
[current-state research](../research/research-time-series-api-implementation.md),
[phase structure](../structure/structure-time-series-api-implementation.md),
and [plan overview](../plan/plan-time-series-api.md).
Follow AGENTS.md, codebase_preferences.md, and python_semantics.md.

The user accepted the design and asked for this plan. The research → plan →
structure → detail prompts were read in that order. No source files are
approved as complete merely because they appear in the design.

## Execution rules

Run P1 → P2 → P3 → P4 → P5 → P6. Within a phase, run tasks in numeric order.
Within a task, check each item only after its stated result is observed.
If a check fails, fix that task before continuing. Do not skip a science gate.

All app, script, test, settings, and package files named below are **proposed
new files**, unless marked existing. Their full paths are relative to
`time-series-api/`. The signatures document owns their exact fields and type
annotations; use those signatures verbatim. This plan adds ordering and tests,
not competing class definitions. Private short helpers are allowed within
their owning file; no new module or public framework is needed.

Execution update: the user requested at most 30 test cases for the project,
counting parameterized cases separately. Combine related checks carefully and
write each test before the behavior it checks. This limit overrides the larger
list of separately named tests below; preserve the checks where practical.
The user authorized reading `FIRMS_MAP_KEY` from the repository `.env` for the
download step. The process environment takes priority. Keep the key private.
NASA's limit remains 5,000 transactions per 600 seconds; pause at 4,000.
The user permits at most five FIRMS API requests in total for this work.
Count budget, availability, and data requests. One request may cost more than
one transaction. Record the request count and transaction counter without
recording the key. The five-request limit has been reached; see the
[schema check](../research/firms-api-schema-check.md). Reuse the saved samples.
T1's serving test precedes T5's full factory. A temporary factory therefore
checks for a selected release and refuses all other startup until T5 adds the
routes and security checks. Its selected-release guard has a test.

For each test change, write the named test first, run it and record a failure
for the intended missing behavior, implement the smallest change, then run
the same test again. Do not count an unrelated import/config error as a valid
behavior failure after setup is complete. Do not add tests for empty package
markers or README wording. Keep code files below 500 lines and functions below
50 lines; review these limits at each task, without artificial wrapper splits.

Use the existing repository Python environment. The command recipes below
are **planned commands**, not existing project commands or checks already run.
They become runnable only after the named files and dependency setup exist.
All recipes run from the repository root unless stated otherwise.

## Fixed scope and initial choices

Keep the spec's limits: 500 MiB saved; 2 GiB temporary; 1–5-day provider
windows; 5,000 transactions per 600 seconds with a proposed pause at 4,000;
page default 1,000 and cap 10,000. Original values stay separate from estimates.
No new service, ORM, queue, live stream, real polygon input, fire-event count,
automatic severity alert, or full archive import belongs in this work.

These **new starting choices** make the engineering tasks concrete. They
are local limits to measure, not claims of speed, safety, or scientific accuracy:

| Setting | Initial value | Reason/check |
| --- | --- | --- |
| Candidate pilot rectangle | `[106.0, 10.0, 107.0, 11.0]` | Small Viet Nam study rectangle; not a country boundary. Confirm availability and size in T8. |
| Candidate shared sample | `[2026-09-01, 2026-09-03)` | Two UTC days for Aqua–Suomi; use only if available. Otherwise follow source-only fallback. |
| CSV batch size | 1,000 records | Fits the first small import; measure memory in T8. |
| Provider timeout/retries | 30 seconds / 2 retries | Bounded failures; respect provider retry advice and budget. |
| Request body | 16,384 bytes | Enough for rectangle JSON; count actual bytes. |
| Global rate | 60 requests/minute, one process | Small local/shared demo; fixed-size state. |
| Query limits | 3,660 days; 10 baseline years; 100,000 input rows; 10,000 cells; 5 seconds | Explicit bounds before queries return large data. |
| Export limits | 10,000 rows; 8,388,608 UTF-8 bytes; 5 seconds | Bound memory and reject before response headers. |
| Old-data flag | More than 3 UTC days since latest source date | Display policy only; freeze/document it and show real source dates. |
| Rectangle point edges | Include all four edges | Simple closed-area selection; dates still exclude end_date. Test corners. |

Write these choices into the canonical spec/settings during T1 before callers
depend on them. Keep numeric science proposals distinct: 80% coverage and
10% count bias remain targets to test in P4. They are not engineering defaults
that make a method valid. Unknown provider source IDs must not be invented.

## File ownership

| File | Tasks and responsibility |
| --- | --- |
| `pyproject.toml`, `app/__init__.py` | T1: package and test setup; no import side effects. |
| `app/models.py` | T1: types/settings/errors/geometry; later add only checked science settings. |
| `app/storage.py` | T2: six tables, all SQL, reads, paging, publication. |
| `app/sources.py` | T3 source parsing; T7 small provider downloads; T9 native readers. |
| `app/analysis.py` | T4: area, calendar, coverage, and baseline rules. |
| `app/main.py` | T5 routes/guard/cursors; T6 exports. |
| Three files in `scripts/` | T7 offline commands; T8 real pilot; T9–T12 checked science flow. |
| `config/settings.json` | T1 limits; T8 real source window; T9–T12 checked science choices. Never keys. |
| Five `tests/test_*.py`, `tests/conftest.py`, two fixture CSVs | Owning task below; no network/user database in tests. |
| `README.md` | T1 setup; T5 early OpenAPI examples; T13 complete web/operator handoff. |
| Existing repository `.gitignore` | T1: narrowly ignore generated data/secrets; preserve current sample/notebooks. |
| Generated `data/` files | Progress, one SQLite database, release manifest/report; retain within budgets. |

## P1 — Contracts and release storage

Tools: repository Python, uv, Pydantic, sqlite3, Pytest. Finish T1 before T2.

### T1. Package, types, and validated settings

**Files:** pyproject.toml, app/__init__.py, app/models.py, config/settings.json,
README.md, tests/test_api.py, tests/conftest.py; existing root .gitignore;
canonical specs for the explicit starting choices above.
**Consumes:** interface document §2. **Produces:** its types, validators,
`load_settings(path: Path) -> Settings`, `validate_bbox(bbox: BBox) -> BBox`,
`selection_geometry(bbox: BBox) -> PolygonGeometry`, and `ApiError`.

- [x] Inspect the current Git diff; list existing user edits that must be preserved. Existing edits: `.gitignore`, root `README.md`, and all untracked documents, requirements, sample data, notebooks, and `.DS_Store` files.
- [x] Create pyproject.toml with FastAPI, Pydantic, Uvicorn, HTTPX and a `test` extra containing Pytest; configure package discovery for `app` and test discovery for `tests`.
- [x] Create the empty app/__init__.py package marker.
- [x] Install this proposed package with the setup recipe below. Network access was required; a writable temporary uv cache was used.
- [x] Record the resolved dependency versions in pyproject.toml after the first passing setup/import check; avoid unrelated root requirements changes. Imports passed on Python 3.13.5.
- [x] Add a parameterized `test_request_fields` in tests/test_api.py: valid ISO dates pass; timestamps, booleans/numeric strings, NaN/Infinity, extra fields, duplicate platforms, path-like IDs, invalid export pairs, reversed dates, and cross-year comparison targets fail.
- [x] Run the request test and record its initial failure. After creating the type-only module, all 12 cases fail because the request classes do not exist yet. The earlier missing-module error was not counted.
- [x] Define BBox/metric/status/aggregation aliases and the three geometry TypedDicts from the interface document.
- [x] Define ComparisonRequest, then AnalysisRequest, HotspotQuery, and ExportRequest; implement one class at a time in that order.
- [x] Define Notice, HealthResponse, MetricDefinition, and ReleaseSummary, one at a time.
- [x] Define CoverageResult, HistoricalComparison, UncertaintyResult, PeriodResult, and AnalysisResponse, one at a time.
- [x] Define SourceFileRecord, ObservationRecord, BandRecord, OpportunityRecord, and DailyRecord, one at a time.
- [x] Define ReleaseRecord, SourceBatch, AnalysisInputs, CursorPosition, and ObservationPage, one at a time.
- [x] Define MatchResult and ValidationReport, one at a time.
- [x] Define HotspotProperties, HotspotFeature, HotspotPage, and ReleasePublicResponse, one at a time.
- [x] Define StorageSettings, DownloadSettings, ScienceSettings, ApiSettings, and Settings, one at a time.
- [x] Define ApiError and ErrorResponse as distinct exception and HTTP types.
- [x] Implement validate_bbox with finite bounds, ordered longitude/latitude, and no 180° crossing.
- [x] Implement selection_geometry as a closed longitude-first rectangle ring; test its five coordinates and no mutation of input. Test failed for the missing function, then passed.
- [x] Implement each required validate_fields method, one class at a time, using the request/setting rules in interface §2. Added checks for numeric dates, strict limits, invalid bounds, wildcard hosts and origins, and unchecked methods. The science method remains disabled until its tests.
- [x] Implement load_settings with a 65,536-byte JSON limit, forbidden extra keys, project-relative paths, and copied nested data.
- [x] Write settings.json with the chosen limits; leave selected release and scientific method unset until their tasks can fill them.
- [x] Add settings tests: unset release permits offline use; serving must reject it; bad limits fail; mutable mappings are not shared between loads.
- [x] Run the request/settings tests; require all cases to pass. Latest result: 17 passed.
- [x] Update README setup/default notes and root .gitignore without changing existing sample tracking.
- [x] Record the starting choices in canonical specs, preserving the same public names and marking future polygon fields as deferred.
- [x] Record the operator-only factory refinement `create_app(settings_path: Path | None = None) -> FastAPI` in canonical interfaces; None resolves to `Path(__file__).resolve().parents[1] / "config/settings.json"`. Explicit paths still work. This is the same factory with an optional argument, not a second entrypoint.

Setup recipe, enabled by the new package definition:

```bash
uv pip install --python .venv/bin/python -e './time-series-api[test]'
.venv/bin/python -m pytest time-series-api/tests/test_api.py -q
```

Dependency installation needs network access when executed. uv is available
today; pip and Pytest are not. Do not claim the recipe already works. Fix
package discovery in pyproject rather than adding ad hoc sys.path edits.
**Complete when:** imports and strict contract/settings tests pass.

### T2. Store and publish fixed releases

**Files:** app/storage.py, tests/test_storage.py, tests/conftest.py.
**Consumes:** model records. **Produces:** all storage functions in interface §7,
including publish_release with independent source/daily iterators.

- [x] Add `test_storage_round_trip`, `test_failed_publish_rolls_back`, and `test_old_release_is_unchanged_after_publication` using a temporary database and two invented releases.
- [x] Run those tests and record their initial failures. With an importable empty storage module, all three fail because `initialize_database` is missing.
- [x] Implement initialize_database(path) with the six tables from spec §10.1, foreign keys, finite/nonnegative value checks, and fixed schema version metadata inside release settings.
- [x] Use source_file_id as source_file key; observation_id as observation key; `(observation_id, band_name)` for bands; `(source_file_id, pass_id)` for opportunities; `(release_id, cell_id, date)` for daily results; release_id for releases. One method per release makes method_id nullable without placing null in a primary key.
- [x] Implement list_releases(path) with typed public summaries.
- [x] Implement load_release(path, release_id) with 404 for an unknown published ID and checked report/manifest hashes.
- [x] Implement read_observations(path, query, position) with bound SQL values, release selection, `(time, ID)` order, and page_size + 1 detection.
- [x] Implement read_daily(path, query, settings=...) to load the bounded target/baseline inputs; preserve original point selection separately from daily cell estimates.
- [x] Implement publish_release with report/manifest identity checks, safe trusted paths, immutable source records, file writes before the final SQL commit, and no overwrite of a published ID. Until T11, non-null method IDs are rejected.
- [x] Apply release source-selection rules across all files/batches; save explicit selected row ranges/decisions in release metadata. Preserve rejected/replaced source provenance. Do not add a seventh table silently if this metadata later becomes too large.
- [x] Add tests for mixed source batches, source-only releases with empty daily input, UTC round trips, missing DB without auto-create, hostile SQL-like values, and cursor rows sharing a timestamp.
- [x] Add a crash test for files written before SQL failure; no new published release may be visible.
- [x] Run tests/test_storage.py; require stable release A results after publishing B with replacement NRT/standard observations. Result: 3 passed; full suite: 20 passed.

Use read-only connections for reads, a connection per call, parameterized SQL,
and a progress-handler deadline separate from the lock timeout. Keep SQL here.
Do not add indexes before query timing shows a need, beyond constraints needed
for keys and identity. **Recovery:** keep release A selected and inspect only
the failed candidate's files. **Complete when:** round-trip, rollback, immutable
selection, and paging tests pass with no leaked connections.

## P2 — Fixture-backed source-only API

Tools: csv, typed models, SQLite, FastAPI/TestClient, Pytest. T3 → T4 → T5 → T6.
This gives the web developer a working contract before science results exist.

### T3. Parse small source batches without changing original meaning

**Files:** app/sources.py, tests/test_sources.py, tests/fixtures/observations.csv,
tests/fixtures/opportunities.csv, tests/conftest.py.
**Consumes:** checked source definition and local file path. **Produces:**
read_source(..., batch_size=...), read_opportunities(..., batch_size=...),
select_source_records(records, policy), with the exact interface §4 types.

- [x] Create the two tiny, clearly invented CSV fixtures; use explicit UTC dates and longitude-first locations. Keep their schemas and origin documented in README.
- [x] Add `test_source_reader_keeps_text_versions`: version `6.03` remains text, HHMM `1` becomes 00:01 UTC, FRP zero remains zero, absent type becomes unknown.
- [x] Add `test_batches_keep_provenance`: batch size two yields no batch above two; original row IDs survive; neighboring pixels are not duplicates.
- [x] Run these tests and record their initial failures. Both fail because `read_source` is not implemented.
- [x] Implement read_source with streaming csv reads, explicit product-field mapping, original_fields retention, checked platform aliases, and bounded batches. The local real sample revealed mixed NRT/URT row versions; correct that case before continuing. It preserves `2.0NRT` and `2.0URT` rows and rejects unsuffixed or other-collection versions. It also rejects a file without the product's primary brightness band. A 74,605-row local VIIRS file parsed in 75 batches of at most 1,000 records; no API request was made.
- [x] Implement read_opportunities for the declared small interchange fixture format; label it as test/interchange data, not a native-product reader.
- [x] Implement select_source_records with release type/confidence rules; keep source provenance even for records the analysis policy excludes.
- [x] Add tests for invalid UTC times, missing columns, HTML error bodies, unknown bands, source changes, exact repeated rows, and an empty valid CSV without coverage evidence.
- [x] Add a cross-file duplicate/replacement test through storage publication, not just a single-batch unit test.
- [x] Run tests/test_sources.py and the relevant storage test; require all to pass after the mixed-version correction. Result: 5 passed. A new missing-primary-band check failed before its parser fix, then passed. Collection remains at 25 tests, under the 30-case limit.

Do not run the tutorial notebooks or treat their saved outputs as current
results. Native product reading remains T9. **Complete when:** small batches
preserve units, row identity, source flags, and uncertainty about coverage.

### T4. Calculate honest calendar and historical results

**Files:** app/analysis.py, tests/test_analysis.py, tests/conftest.py.
**Consumes:** validated query, ReleaseRecord, AnalysisInputs.
**Produces:** validate_query_domain, summarize_periods, compare_history,
build_analysis with interface §6 signatures.

- [x] Add `test_missing_is_not_zero`: absent coverage yields null estimate/coverage, while original_count still reports selected detections.
- [x] Add `test_equal_historical_window`: prior totals `[0,2,4,6,8]` have median 4; target 6 gives difference 2 and 50%; February 29 is excluded.
- [x] Add `test_tiny_selection_has_no_spatial_support`: source points can exist while no selected cell center exists; estimated result is not zero.
- [x] Run these tests and record their initial failures. All three fail for missing analysis functions. The internal daily record needed an explicit grid cell center; the canonical interface now records that addition. No real database needs migration.
- [x] Implement validate_query_domain with full area/date/baseline bounds, fixed source policy, metric/aggregation rules, and size limits. Check: in-area requests pass; outside area/date, unknown platforms, and oversized date ranges fail. A harmonized source override reaches this domain check and returns 409 `REFERENCE_POLICY_CONFLICT`.
- [x] Implement summarize_periods so every requested day/month appears; preserve requested partial-month dates, expected/usable days, nulls, warnings, and old-data flag. Tests cover missing and partial periods, leap day visibility, unknown coverage, per-period point counts, and per-period baselines. Old-data uses the latest stored source date and a three-day UTC threshold.
- [x] Implement compare_history for five valid earlier years, excluded-year reasons, same calendar windows, null percentage at zero median, and no comparison when not requested. Tests cover five usable years, four-year and missing-day baselines, exclusion of February 29, and zero medians.
- [x] Implement build_analysis for one whole-window summary plus calendar periods; calculate each baseline on its own window, not by adding medians. It returns the union of selected whole cells and does not change input records.
- [x] Add Shapely to pyproject.toml for the required whole-cell union and checked footprint operations; this solves the existing used_area contract, not deferred polygon request input.
- [x] Rerun the setup recipe to install that dependency before the geometry tests. Shapely 2.2.0 installed.
- [x] Use union_all without precision snapping; reject invalid/empty geometry where a real used area is required. A self-intersecting cell test returns a safe release error.
- [x] Add closed rectangle edge/corner tests; compare source-point selection with cell-center selection using selection_geometry. Four source corners count; a center on the rectangle edge selects the whole cell.
- [x] Add fewer-than-five-year, zero-median, outside-domain, missing-day, and unavailable-uncertainty cases.
- [x] Run tests/test_analysis.py; require all expected numeric/null/status fields to match. Result: 3 passed.
- [x] Pin the tested Shapely version in pyproject.toml after those checks pass: 2.2.0.

Do not use screen-map area or scale estimates by an untested coverage/area
fraction. Reject day/month aggregation of the pass-only FRP metric. Return
the exact whole-cell union as used_area using the planned Shapely dependency.
Its [official union documentation](https://shapely.readthedocs.io/en/stable/reference/shapely.union_all.html)
was checked while planning; no installed version is claimed. Do not fill
gaps to make the calendar look complete. **Complete when:** all target and
baseline cases pass without changing input records.

### T5. Serve routes, guard inputs, and page points

**Files:** app/main.py, tests/test_api.py, tests/conftest.py, README.md.
**Consumes:** T1–T4. **Produces:** create_app, the first seven endpoint handlers,
three error handlers, RequestGuard, cursor functions, and to_geojson from
interface §3. The export route is completed in T6 before P2 finishes.

- [x] Add fixture releases/client and `test_route_contracts` for health, releases, metrics, analysis, and GeoJSON points. The fixture uses a temporary SQLite database and two invented rows.
- [x] Run route tests and record their initial failures. They stop at the expected missing `create_app` implementation; no real database or provider is used.
- [x] Implement create_app(settings_path: Path | None = None) with T1's project-local default, trusted settings, CURSOR_SECRET checks, read-only serving, exact origins/hosts, and explicit response models. Routes only read published data; CORS and host lists come from trusted settings.
- [x] Test factory calls with explicit temporary settings; separately capture the default load_settings path with a test stub and require it to resolve from the app file rather than the working directory. A unit test must not open a real published database. The test stubs settings and confirms the default path; app creation does not open SQLite.
- [x] Implement health_live, then health_ready; readiness checks the selected release and files without returning private details. Missing release files return a safe 503.
- [x] Implement list_releases, then get_release, then list_metrics with stable OpenAPI operation IDs. Public detail uses an explicit response model.
- [x] Implement analyze with domain checks, bounded storage reads, pure calculation, and transport timing. It reuses T4 validation and calculation.
- [x] Implement encode_cursor with canonical JSON and HMAC-SHA256 binding the full query except cursor. Page size and normalized platforms are included.
- [x] Implement decode_cursor with length/version/signature/query checks before using its row position. Invalid, changed, and oversized cursors return 422.
- [x] Implement to_geojson with typed Point geometry and source/band metadata. OpenAPI declares a concrete Point geometry.
- [x] Implement query_hotspots with stable page order and next_cursor/has_more agreement. Two one-row pages preserve time/ID order; the configured page maximum is enforced.
- [x] Implement handle_api_error, then handle_validation_error, then handle_server_error using safe ErrorResponse fields and server-created request IDs. Validation input and server exception text are not returned.
- [x] Implement RequestGuard.__init__ with one bounded process-wide rate bucket.
- [x] Implement RequestGuard.__call__ with per-request body counters, actual-byte limits, JSON-only uncompressed POST input, and consistent errors.
- [x] Add `test_body_limit_without_content_length` using a raw ASGI chunked receive fixture; require 413 without first parsing the whole body. The test also checks separate request bodies and rate-limit headers.
- [x] Add `test_cursor_rejects_a_changed_query` for edits to bbox/date/platform/release/page size and malformed oversized tokens.
- [x] Add concurrent-request tests for isolated body counters, safe request IDs, 429/Retry-After, and CORS headers on errors. Concurrent body receives are isolated; error CORS is checked.
- [x] Add tests for every documented error status, unknown host, missing DB, sanitized validation details, and public release data without keys/local paths. Checks cover 400, 404, 409, 413, 415, 422, 429, 500, and 503.
- [x] Run tests/test_api.py; check /openapi.json contains all current fields and concrete GeoJSON shapes. Result: 20 passed. Full suite collects 28 cases. One upstream Starlette warning says `httpx` support in TestClient is deprecated.
- [x] Add early copyable README requests for the web developer, marked invented where appropriate. Examples show metric, analysis, point paging, and longitude-first EPSG:4326 bounds.

CORS is not authentication. Bind local Uvicorn to loopback; trust no arbitrary
forwarded headers. No route imports source-download or fitting workflows.
**Complete when:** guarded fixture API, browser-visible errors, and stable
paging pass. No live provider access is needed for these tests.

### T6. Download matching results without partial success

**Files:** app/main.py, tests/test_api.py.
**Consumes:** same query/storage/calculation paths as screen results.
**Produces:** build_export(query, settings=...) -> tuple[bytes,str,str] and
export_results(query, request) -> Response.

- [x] Add `test_export_matches_screen` for analysis scientific fields and selected raw rows across multiple point pages.
- [x] Add `test_export_limit_returns_error_before_download` at each row/byte/time boundary; require 413 and no attachment body on overflow.
- [x] Run export tests and record their initial failures. Both new tests first returned 404 because the export route did not exist.
- [x] Implement build_export with a bounded body, UTF-8 byte counting during encoding, csv.writer, safe text cells, and server-created filenames.
- [x] Implement export_results with the correct media type and Content-Disposition; expose filename/request-ID headers through CORS.
- [x] Add tests for whitespace-prefixed spreadsheet formulas, quoted commas/newlines, preserved numeric negatives, JSON nulls, and timing-only screen/export differences. Checks are part of `test_export_matches_screen`.
- [x] Run the full backend test suite; require all eight endpoints and export limits to pass. Result: 30 passed across four test modules; one upstream Starlette/httpx deprecation warning.
- [x] Get web developer review of the map requests; record its scope in README. The developer approved the emergency responder map feature (rectangle request and point paging). A generated fixture schema is available at `time-series-api/openapi.json`, with a plain guide at `time-series-api/openapi-guide.html`; tests check the schema and all example request types. Download examples were not reviewed; check them in T13. The live server still needs a selected release; T8 will provide the real release.

Do not start sending bytes before the bounded export succeeds. No job IDs,
queues, or export files are needed. **Complete when:** downloads match the
same release/query, limits return clear errors, and the first web handoff works.

## P3 — One real saved API sample

Tools: HTTPX, provider docs/status, three scripts, local API, Pytest. T7 → T8.

### T7. Offline commands and reliable small downloads

**Files:** app/sources.py; scripts/fetch_data.py, prepare_data.py,
check_results.py; tests/test_sources.py, test_storage.py; README.md.
**Consumes:** existing typed/storage calls. **Produces:** fetch_windows(settings)
and parse_arguments/main in each script, exactly as interface §§4, 8.

- [x] Add mocked download tests for availability, unknown budget, retry cost, provider errors, interrupted files, resume, and real byte limits without Content-Length.
- [x] Run the first mocked download test and record its initial failure. The unknown-transaction-status case failed because `app.sources.fetch_windows` did not exist. The remaining mocked cases were then added before implementation was complete.
- [x] Implement fetch_windows with trusted NASA hosts/source IDs, TLS checks, no untrusted redirects, explicit timeouts, sequential windows, and no MAP_KEY in outputs/logs.
- [x] Save completed-window hashes/parameters and safe filenames in download-progress.json; accept a window only after schema/date checks pass.
- [x] Add tests that retries/status requests consume budget, an unknown/shared-key budget pauses work, and a configured batch cannot exceed local disk space silently.
- [x] Implement parse_arguments in fetch_data.py, then its main; read FIRMS_MAP_KEY from the environment or repository .env, never an argument.
- [x] Implement parse_arguments in prepare_data.py, then its main for source-only preparation and publication; read saved inputs through repeatable iterators.
- [x] Implement parse_arguments in check_results.py, then its main for saved-release integrity/scope checks; never overwrite a published validation report.
- [x] Add tests for command exit codes, no import side effects, repeated-window resume, independent consumed generators, and failed preparation without a visible release.
- [x] Run source/storage tests and each CLI's argument tests; inspect parser defaults directly. `.venv/bin/python -m pytest time-series-api/tests -q` passed all 30 tests; compileall and `git diff --check` also passed. The test run reports one upstream Starlette/httpx deprecation warning.
- [x] Document the exact working commands, intentional defaults, and explicit overrides in README.

Source-only reports list import/integrity checks and unresolved science. They
do not mark FRP/count tests passed. Cleanup touches only this job's checked
partial files. **Complete when:** a mocked fetch → prepare → check cycle passes.

### T8. Run the first real combination

**Files:** config/settings.json and generated data only; README pilot record.
**Prerequisites:** working P2/T7; private MAP_KEY supplied to the runtime;
actual provider availability/status. Missing key or network stops this task.

- [x] Read current official provider endpoint/availability/transaction rules; record the source IDs and access date without the key. NASA FIRMS area, availability, and tutorial pages were reviewed; the 2026-11-14 availability response listed `MODIS_NRT` and `VIIRS_SNPP_NRT` for the candidate September dates. The request ledger records five requests and no key.
- [ ] Check whether the candidate rectangle and shared September window are available for Aqua–Suomi. The saved VIIRS request for the candidate rectangle/date returned a valid header with zero rows. The saved availability response shows date overlap, but the MODIS sample used another rectangle/date. The five-request limit is reached, so box-level shared data availability is unresolved.
- [ ] If shared dates are unavailable, choose one currently available source-only platform and at most two UTC days; record the change and missing science inputs. Do not silently switch a harmonized method.
- [ ] Write the concrete rectangle/date/source window into settings and estimate its bytes before downloading.
- [ ] Fetch only this one combination with fetch_data.py; record provider cost, rows, bytes, time, and highest memory use.
- [ ] Check schema, source/platform identity, dates, hashes, and original sample rows before preparation.
- [ ] Prepare a uniquely named source-only release using prepare_data.py.
- [ ] Check its manifest/report with check_results.py.
- [ ] Set selected_release_id to that checked release and start the local API with the serving recipe.
- [ ] Run one rectangle query, read all its point pages, and download the same raw selection.
- [ ] Compare row identities, dates, units, and scientific fields across screen/download; record matching results and unknown coverage honestly.
- [ ] Check disk totals against both budgets; stop serving before any release change.
- [ ] Record whether this one combination passed the whole path; do not expand if it failed.

If there are zero detections, retain the valid empty source response and
unknown coverage. It is not a tested clear-sky zero. A different source/date
pilot is a recorded next attempt, not evidence that the failed one passed.
**Complete when:** exactly one real combination passes or a concrete external
block is recorded. A blocked attempt does not complete P3.

## P4 — Scientific checks before harmonized claims

Tools: verified native-product readers, small geometry/numeric tools where
needed, pinned FRP reference code, independent test data. T9 → T10 → T11.
These stages produce evidence and may reject an approach. Their scientific
choices are not predetermined by an API signature or the planning document.

### T9. Verify native inputs and freeze the test design

**Files:** app/sources.py, app/harmonization.py, tests/test_sources.py,
tests/test_harmonization.py, config/settings.json, canonical spec science notes.
**Consumes:** T8 pilot and spec §7.2. **Produces:** real OpportunityRecord inputs,
reviewed source mappings, fixed splits, and declared method settings.

- [ ] Locate matching Aqua MYD14/MYD35 and Suomi VNP14IMG/VNP03IMG inputs for a small shared region/time; record missing products before writing a reader.
- [ ] Check product versions, pass/granule IDs, units, masks, location fields, and file sizes against official product docs.
- [ ] Resolve the recorded NOAA-21/date and MODIS version conflicts before using those data; do not include unresolved sources in a claim.
- [ ] Choose the minimum reader dependencies for the actual file formats and record their license/version/input need.
- [ ] Freeze study areas, grid width `w` in km, equal-area projection, origin, cell ID and edge rules, pass schedule, quality rules, and train/tuning/final-test groups before fitting. Assign a record by its center; one boundary rule must place it in exactly one cell.
- [ ] Define seasonal agreement as correlation of month-wise totals on the held-out set, with an explicit allowed loss and handling of constant series; write those values before the final test.
- [ ] Freeze subgroup/pass-failure targets, count bias/MAE targets, and the reasons for them in science settings; if evidence does not support a target, report that gate as unresolved rather than running a final test.
- [ ] Add native-reader tests from small checked extracts; expected masks/pass geometry must come from independent source interpretation, not the reader's own output.
- [ ] Extend read_opportunities for the verified native products; keep the interchange fixture path clearly separate.
- [ ] Add low-activity/non-fire/cloud/missing-visit cases and check area/units independently.
- [ ] Record reader checks and frozen split IDs in the candidate validation report.

Do not fabricate native QA from hotspot CSVs. Do not fit if the reference
schedule or usable coverage is unknown. Missing native inputs block T10–T11;
the source-only API can still be used. **Complete when:** source and coverage
inputs are independently checked and final-test rules are fixed.

### T10. Test the FRP operator

**Files:** app/harmonization.py, tests/test_harmonization.py, settings/report;
app/sources.py only if a verified input conversion requires it.
**Produces:** match_passes and compare_frp with interface §5 signatures.

- [ ] Pin a full FRP_OOp repository commit and check its license/dependencies and behavior against the paper; record what was actually reviewed.
- [ ] Define the small private operator-adapter signature from the checked reader output; record it in canonical interfaces before writing that adapter.
- [ ] Add `test_matching_keeps_unmatched_records` and a block-edge test; require many-to-one candidates, retained unmatched IDs, and no arbitrary CSV-boundary losses.
- [ ] Run these tests and record their initial failures.
- [ ] Implement match_passes with declared footprint/time rules and bounded area/time blocks.
- [ ] Add repeatability and zero-FRP tests for the adapter; a retained random draw must not change measured input FRP.
- [ ] Add cell tests for stable center assignment, cell edges, UTC day boundaries, MODIS-only/VIIRS-only/both/no-detection cells, and the difference between a covered zero and unknown coverage.
- [ ] Sum valid raw FRP by cell, platform, and pass. Keep each input value unchanged and keep MODIS and VIIRS separate.
- [ ] Compare uncorrected paired pass sums first. Then test one scale factor fitted on tuning data; keep it only if it improves held-out dates and areas.
- [ ] Calculate each platform's daily cell value as the highest valid pass sum in that UTC day. Do not add different passes or combine platforms before an independent test passes.
- [ ] Implement the reviewed adapter, then compare_frp; keep these as separate short functions in the same file.
- [ ] Run original, matched-coverage-only, and operator comparisons at 15/30/60/120-minute gaps using frozen splits.
- [ ] Report signed error, MAE in MW, repeat variation/error information, and results by power/day-night/pixel-size/time-gap groups.
- [ ] Apply the predeclared pass rules to independent data and record failures without forcing totals to match.

If the operator fails, record why and a concrete next test; do not treat it
as a passed prerequisite. A changed method needs a fresh untouched test set.
**Complete when:** the FRP test has an auditable outcome; only a passing
candidate may contribute to a harmonized method.

### T11. Test counts separately and select one method

**Files:** app/harmonization.py, tests/test_harmonization.py, science settings,
canonical spec/interface notes and candidate report.
**Produces:** evaluate_counts and prepare_daily from interface §5.

- [ ] Freeze the Aqua-like target count and all area/visit/quality/type rules from T9.
- [ ] Implement the matched uncorrected baseline for the same target and inputs.
- [ ] Implement the declared grouping/projection count candidate as ordinary functions.
- [ ] Evaluate the baseline and grouping candidate on tuning data using the same split groups.
- [ ] Consider a simple fitted count model only if the grouping candidate fails or a measured remaining error justifies it; record available deployment-time inputs first.
- [ ] If a fitted model is selected, define its one-file lifecycle/checkpoint API in the canonical design before implementation; resolve repository model-entrypoint rules without silently adding files to this tree.
- [ ] Add and pass save/load parity and one-batch computation tests for any selected fitted model; add forward/backward tests only if it is a trainable neural model.
- [ ] Implement evaluate_counts with count bias, MAE, seasonal agreement, low-activity cases, and source-change checks.
- [ ] Choose the simplest candidate that meets the frozen rules on tuning data; lock it before the independent final test.
- [ ] Run the untouched final test once under the declared protocol and record the full supported scope and failed subgroups.
- [ ] Implement prepare_daily for the passed method with bounded blocks and explicit unavailable estimates outside tested scope.
- [ ] Check daily count/coverage/seed repeatability through storage save/load.

If all candidates fail, retain source-only publication and record that the
harmonized MVP remains unfinished. Do not choose a winner just because it has
the smallest training error. If a learned experiment is used, apply the
repository's W&B/artifact rules; do not persist raw forward-pass tensors.
Synthetic injection/DVC is not part of this fire-data task unless later added.
**Complete when:** one method passes independently, or the failure is reported
and harmonized publication remains blocked.

## P5 — Checked historical release

Tools: same offline scripts, selected method, SQLite, independent historical
checks. Depends on a passed T11 method; do not replace this with fixture tests.

### T12. Expand only as far as evidence and budget allow

**Files:** source/science settings, scripts/prepare_data.py and check_results.py,
tests/test_harmonization.py, test_storage.py, generated data/release files.

- [ ] Estimate historical bytes for the small area and 2020–2026 window using measured sample sizes before requesting more data.
- [ ] Check actual usable years and product/platform availability; record exclusions and source cutoffs.
- [ ] Process one historical area/year/platform combination through fetch, native coverage, method, publication, API, and download checks.
- [ ] Stop expansion until that combination passes.
- [ ] Process additional small batches within budgets; reduce area before reducing baseline years.
- [ ] Test additional years/seasons and each proposed new platform/product separately; retain null/not_validated outside supported scope.
- [ ] Require five usable earlier same-window years for each published comparison; suppress unsupported baselines instead of filling gaps.
- [ ] Build the immutable release manifest/report with source hashes, exact row selection, code/settings/method versions, actual dates, supported metrics, and tested scope.
- [ ] Stop serving and publish the checked release transactionally.
- [ ] Reopen old and new releases; rerun stable paging, numeric results, file-hash checks, and standard/NRT replacement tests.
- [ ] Measure 95th-percentile analysis/first-page latency on declared hardware with representative queries and both cold/warm reads; target under two seconds.
- [ ] Add only measured-needed SQL indexes in storage.py, then rerun identical correctness and timing checks; do not add a cache/service without a recorded need.
- [ ] Check total saved/temporary bytes and safely remove only checked temporary downloads whose provenance is retained.

Keep uncertainty null with UNCERTAINTY_UNAVAILABLE unless its own checked
block-resampling method is implemented. An optional rank/active-cell metric
stays unavailable unless independently supported. **Complete when:** only
tested historical scope/metrics are served and old results remain repeatable.

## P6 — Web handoff and local/public acceptance

Tools: generated OpenAPI, browser/OpenLayers, local API; a host only if selected.
No frontend source files are created by this backend plan.

### T13. Complete the web developer and operator handoff

**Files:** README.md, app/main.py model examples, tests/test_api.py;
existing root README only for a short link to the backend guide.

- [ ] Generate OpenAPI from actual implemented models and verify all eight operation IDs, error shapes, optional fields, nulls, and GeoJSON types.
- [ ] Review the cell-grid map result with the web developer. Agree on cell geometry, platform-specific daily FRP, coverage states, and query limits before adding an OpenAPI operation or changing the current rectangle/point contract.
- [ ] Add copyable rectangle/analysis/point/export examples plus available, zero, missing, partial, and unsupported fixtures; mark invented examples.
- [ ] Document public release source/type policies, supported dates/areas, data age, use limits, source credits, and report links.
- [ ] Document exact CLI defaults/overrides from the implemented parsers, private environment variables, source refresh, stop-serving publication, and rollback.
- [ ] Ask the web developer to transform a drawn OpenLayers rectangle to EPSG:4326 and test known positive/negative coordinates without swapping latitude/longitude.
- [ ] Test draw completion/Apply requests, old-response cancellation, layer replacement, visible point paging, and date handling without browser-local shifts.
- [ ] Test map → selection → calendar → month/day → source points → history → matching download on one real checked release.
- [ ] Verify unknown periods stay visible, unsupported areas are not shown as zero, and requested versus used cell areas remain distinct.
- [ ] Record web acceptance results and unresolved UI issues in README; do not claim the API alone completes the web app.
- [ ] Run the full backend test suite and compile check after handoff fixes.

Future polygon drawing uses the existing area-selection seam but needs a new
checked request contract; it is not implemented here. **Complete when:** the
developer can use the documented contract without Python/database knowledge
and the full real user flow has recorded results.

### T14. Optional public demo, after local checks

**Prerequisite:** explicit deployment scope and a chosen host. This plan does
not choose a paid cloud account or authorize new spending. Local completion
does not depend on this task unless the public challenge submission needs it.

- [ ] Confirm host, persistent disk, public URL, exact frontend origins, and one-process resource limits with the deployment owner.
- [ ] Install the same tested pinned package on that host without exposing MAP_KEY/CURSOR_SECRET or mounting the full data tree publicly.
- [ ] Copy the checked database and matching release files while serving is stopped.
- [ ] Apply HTTPS, host/CORS rules, bounded connections/timeouts, trusted-proxy settings, and least-privilege read access for serving.
- [ ] Start the API and run health, one query, paging, export, error/CORS, and restart/persistence checks through the public frontend.
- [ ] Reopen an old release and compare results with the local copy.
- [ ] Prepare source/tool/AI-use credits and the recorded demo; verify current submission rules before using slide/video limits from supplied screenshots.
- [ ] Keep the local demo and last checked release available if hosting fails.

**Recovery:** stop the new deployment and restore the last checked release;
do not rewrite its artifacts. **Complete when:** public smoke/persistence checks
pass or a concrete deployment block is reported without claiming success.

## Verification recipes and expected results

These commands are introduced by this plan and the proposed files above.
They are not evidence of existing runtime behavior. Use the narrow test file
named in each task until it passes; run the full suite at P2/T13 completion.

```bash
.venv/bin/python -m pytest time-series-api/tests/test_sources.py -q
.venv/bin/python -m pytest time-series-api/tests/test_storage.py -q
.venv/bin/python -m pytest time-series-api/tests/test_analysis.py -q
.venv/bin/python -m pytest time-series-api/tests/test_harmonization.py -q
.venv/bin/python -m pytest time-series-api/tests/test_api.py -q
.venv/bin/python -m pytest time-series-api/tests -q
.venv/bin/python -m compileall -q time-series-api/app time-series-api/scripts
```

Expected: selected tests pass; compileall reports no syntax error. Do not
interpret skipped science checks as passed science. Inspect failed assertions
before changing expected values. No invented minimum test count is required.

Proposed CLI invocations after T7; --settings is an explicit override and
--release-id is required. Other values come from the validated settings file:

```bash
.venv/bin/python time-series-api/scripts/fetch_data.py --settings time-series-api/config/settings.json
.venv/bin/python time-series-api/scripts/prepare_data.py --settings time-series-api/config/settings.json --release-id pilot-source-v1
.venv/bin/python time-series-api/scripts/check_results.py --settings time-series-api/config/settings.json --release-id pilot-source-v1
```

Expected: exit 0 only for the requested completed step; missing key/data or
failed checks produce a safe nonzero result. Set keys privately in the shell;
never place their values in commands, examples, logs, or Git.

Serving recipe after T5/T8, using the installed app package:

```bash
.venv/bin/python -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000 --workers 1
```

T1/T5 make settings_path optional as defined above, so Uvicorn's no-argument
factory call works. A real selected release and private CURSOR_SECRET must
exist before starting this command. Test with explicit temporary settings in
unit tests; test this actual no-argument startup against the T8 local pilot.

## Risks, schema changes, and recovery

| Cause | Impact | Mitigation/check | Recovery |
| --- | --- | --- | --- |
| Generator reused after consumption | Missing imported/calculated rows | Independent source/daily iterators; T2/T7 tests | Discard unpublished candidate and rerun saved inputs. |
| Half-published files/database | Inconsistent release | Files first, SQL commit last; crash tests | Keep prior release selected; inspect unused candidate folder. |
| Unchecked source replacement | Changed old results | Immutable rows plus frozen selection; T2/T12 tests | Restore prior selection, never overwrite old release. |
| Large query/native block/export | High memory or delay | Explicit row/byte/time/block limits and measured pilot | Reduce area/window; no silent truncation. |
| Missing coverage or baseline | False zero/comparison | Nulls and named reasons; T4/T9/T12 checks | Serve original data with clear limits. |
| Failed science test | Invalid harmonized claim | Independent gates and metric whitelist | Source-only release; new method/test protocol before retry. |

There is no existing API database to migrate. First creation uses six tables.
For a later schema change, stop serving, retain the old database, build a new
candidate, compare row counts/units/query results, and switch only after checks.
Do not add a migration framework to this empty MVP. Use unique release IDs;
restore the last checked selected_release_id to roll back a data update.

## Final acceptance checklist

- [ ] All listed engineering tests pass with no live keys or user database.
- [ ] One real source-only combination completed end to end before expansion.
- [ ] Native data and FRP/count test reports exist for every harmonized claim.
- [ ] Unsupported years/platforms/products are unavailable, never guessed.
- [ ] Every published historical comparison has five usable earlier years.
- [ ] Old releases, cursors, and exports remain repeatable after a new release.
- [ ] OpenLayers user workflow and screen/download equality are recorded.
- [ ] Saved/temp bytes, memory, and query latency are measured on named hardware.
- [ ] Secrets, local paths, and raw exception bodies are absent from public data.
- [ ] Public hosting checks pass if hosting is part of the requested delivery.
- [ ] No source-only demo, skipped science, static plan, or passing unit suite is called a complete harmonized MVP.

## Planning review

This is a detailed engineering plan with explicit data/science/deployment
prerequisites, not a claim that those prerequisites are met. The scientific
adapter signature, exact native readers, final count choice, and learned-model
checkpoint contract are intentionally decided by their evidence stages before
implementation. Do not fill them in by guessing. All current public/table/type
names remain unchanged; any later change must update the spec's name mapping.

One callable refinement is explicit: required `create_app(settings_path)`
becomes `create_app(settings_path=None)` with the same owner and behavior for
explicit paths. Only startup argument optionality changes. No HTTP/config/
database/checkpoint field migrates. T1 updates the canonical interface first.
