# Minimal time-series-api directory tree

Status: proposed design; no application code created.
Basis: [development spec v0.4](../../../specs/time-series-api-devspec.md).
The specification remains the source of truth.

Start with a small saved FIRMS API sample, one Python app, and one SQLite
database. Prepare data offline; serve saved results. OpenLayers belongs in
the separate `web-app/` folder.

## Design steps

- [x] Phase 1 — Read requirements using shell file reads.
  - [x] Read repository rules and the full development specification.
  - [x] Inspect existing files and the earlier brainstorming note.
- [x] Phase 2 — Design the layout using Markdown.
  - [x] Compare three layouts.
  - [x] Assign each file one clear responsibility.
  - [x] Map specification requirements to those files.
- [x] Phase 3 — Review the proposal using a Python document check.
  - [x] Check listed existing files against the working tree.
  - [x] Check links, tree entries, and requirement coverage.

## Layout choice

| Option | Benefit | Cost |
| --- | --- | --- |
| Four app modules, as sketched in v0.3 | Fewest modules | Download and scientific logic would live inside scripts or mix with request calculations. |
| Six app modules and three scripts, as in v0.4 | Clear download, science, storage, and request boundaries | Two more modules. Recommended. |
| Separate preparation and API packages | Strong package separation | More directories and interfaces before their need is known. |

Use the second option. `app/` holds importable functions; scripts only run
offline workflows. An app module need not be imported by the HTTP server.
Keep functions under 50 lines and code files under 500 lines. File counts
are a starting design, not permission to exceed those limits.

## File-level tree

Unmarked files are proposed. `[existing]` means keep the current file.
`[generated]` means create at runtime and exclude from Git.
Angle brackets identify variable names, not literal files.

```text
time-series-api/
├── README.md
├── pyproject.toml
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── models.py
│   ├── sources.py
│   ├── harmonization.py
│   ├── analysis.py
│   └── storage.py
├── scripts/
│   ├── fetch_data.py
│   ├── prepare_data.py
│   └── check_results.py
├── config/
│   └── settings.json
├── tests/
│   ├── conftest.py
│   ├── test_sources.py
│   ├── test_harmonization.py
│   ├── test_analysis.py
│   ├── test_storage.py
│   ├── test_api.py
│   └── fixtures/
│       ├── observations.csv
│       └── opportunities.csv
├── notebooks/
│   └── nasa-firms-tutorial/
│       ├── firms_api_use.ipynb                  [existing]
│       └── firms_data_ingest.ipynb              [existing]
└── data/
    ├── samples/
    │   └── sample_viirs_snpp_071223.csv          [existing]
    ├── service.sqlite3                         [generated]
    ├── staging/
    │   ├── download-progress.json              [generated]
    │   └── <source-window>.<native-extension>   [generated]
    └── releases/
        └── <release_id>/
            ├── manifest.json                  [generated]
            └── validation.json                [generated]
```

The tree lists files within each repeated runtime directory once. Download
extensions follow actual products, such as CSV, HDF, or NetCDF. Do not force
native coverage products into hotspot CSVs.

## File responsibilities

### Project files

| File | Contents |
| --- | --- |
| `README.md` | Link to the canonical spec; setup; three offline commands; serving and testing instructions; environment variables; source credits; OpenLayers handoff examples; local and hosted demo steps. Mark invented examples. Link real examples to their release. Explain API date bounds and default versus overridden settings. |
| `pyproject.toml` | Package metadata; FastAPI and serving dependencies; Pytest and HTTP test dependencies; package discovery; test settings. Add scientific/native-file libraries only when the chosen inputs require them. Pin versions after testing. |
| `app/__init__.py` | Package marker only. No startup work or automatic downloads. |

Do not copy the spec into `time-series-api/development-spec.md`. The README
links to `../documents/specs/time-series-api-devspec.md`, avoiding two copies.
Use the repository `.venv`; do not add another environment inside this folder.

### Application modules

| File | Owns | Main proposed functions or types |
| --- | --- | --- |
| `app/main.py` | App creation, all eight specified endpoints, CORS, error responses, request IDs, request size/rate limits, timing logs, GeoJSON, and bounded downloads. Use one process for simple in-memory rate limits. | `create_app(settings_path)`; small endpoint functions; CSV encoding and response helpers. |
| `app/models.py` | Pydantic request/response/settings models; ordinary typed records crossing the storage boundary; metric definitions; status/error names; JSON settings loading. | `Settings`, `AnalysisRequest`, `AnalysisResponse`, `HotspotQuery`, `ExportRequest`, `ReleaseRecord`, `ObservationRecord`, `DailyRecord`, `ApiError`; `load_settings(path)`. |
| `app/sources.py` | Provider availability/status checks; small sequential downloads; retries, resume progress, disk/transaction budgets; CSV batches and SQLite-ready records; UTC conversion; original source fields; checked platform/band aliases; type/confidence policy; quality flags; duplicate/replacement rules; native coverage reading. Keep version fields as text. | `fetch_windows(settings)`; `read_source(path, source_definition)`; `read_opportunities(path, source_definition)`; `select_source_records(records, policy)`. |
| `app/harmonization.py` | Offline pass/area matching, coverage and grid assignment, the FRP operator adapter, count-method comparison, seeded repeats, fitting when needed, daily estimates, and scientific checks. Keep unmatched detections; report them by sensor. Matching does not identify real fire events. | `match_passes(observations, opportunities, settings)`; `compare_frp(matches, settings)`; `evaluate_counts(matches, split, settings)`; `prepare_daily(observations, opportunities, method)`. |
| `app/analysis.py` | Pure query calculations: point versus cell area rules, daily/monthly totals, missing periods, coverage, equal historical windows, baseline median/differences, and quality labels. | `validate_query_domain(query, release)`; `summarize_periods(query, records, release)`; `compare_history(query, records, release)`; `build_analysis(query, records, release)`. |
| `app/storage.py` | All SQLite connections and SQL; the six specified tables; explicit UTC/unit conversion; source records and release-scoped reads; stable paging; atomic release publication. | `initialize_database(path)`; `load_release(path, release_id)`; `read_daily(path, query)`; `read_observations(path, query, cursor)`; `publish_release(path, prepared_data, manifest)`. |

These signatures describe ownership, not a complete implementation API.
The [typed interface design](../../../specs/time-series-api-signatures.md)
defines detailed class fields, function signatures, and security rules.
Source readers yield small batches rather than returning a whole archive.
Storage writes each batch in a transaction. Start with built-in `csv` and
`sqlite3`; add PyArrow only if measured memory use or import time needs it.
Use ordinary functions; add no base classes, plugin registry, ORM, or generic
repository layer. The FRP adapter stays beside its scientific use. If a fitted
model is selected later, keep its public lifecycle in one file and define its
checkpoint contract then; do not invent that model now.

`main.py` calls storage and calculation functions. It never imports download
or fitting workflows. `analysis.py` receives typed values, not database rows
or connections. SQL stays in `storage.py`, including schema creation.

Store releases together in one database. Release-scoped queries must preserve
their source membership and source-selection policy, even when newer standard
data replace NRT data. A new release must not change old query results.
Keep the six-table design; record explicit membership in release metadata
until measured size justifies a schema change.

### Offline scripts

| File | Ordered work |
| --- | --- |
| `scripts/fetch_data.py` | Load settings → check availability and budgets → fetch one small window → check/save progress → continue within limits. Start with one rectangle and one 1–5-day window. Accept supplied native products where automated access is not yet implemented. Missing required inputs stay explicit. |
| `scripts/prepare_data.py` | Load checked source inputs → parse/select records in small batches → build source-only results, or apply a tested method when its inputs exist → check the candidate release → publish only supported metrics. The same entrypoint handles the small pilot and later historical preparation. |
| `scripts/check_results.py` | Run declared FRP/count checks on held-out inputs → check coverage, scope, years, and disk use → write a validation report. Recheck a saved release without modifying it. |

Share scientific checks through `harmonization.py`; do not import one script
from another. Stop serving during publication for the MVP. Publish data and
release metadata in a checked transaction; expose a release only after its
report and manifest exist. A failed count test blocks harmonized metrics,
while an explicitly original-only release can remain useful.

If Aqua and Suomi have no available shared API window, keep an available
source-only sample for web work. Report the missing inputs. Do not silently
switch sensors or produce harmonized estimates from untested inputs.

### Settings and generated files

| File | Fields or contents |
| --- | --- |
| `config/settings.json` | Four groups: `storage`, `downloads`, `science`, and `api`. See fields below. No credentials. |
| `data/service.sqlite3` | The six tables: `source_file`, `observation`, `band_measurement`, `opportunity`, `analysis_daily`, `release`. Preserve source values; store estimates separately. Avoid a second complete CSV copy. |
| `data/staging/download-progress.json` | Source, area/date windows, completion state, local paths, file hashes, and retry state. No credentials or access-bearing URLs. |
| `data/staging/<source-window>.<native-extension>` | Temporary provider bytes. Remove only after derived records and enough provenance to fetch again are saved and checked. |
| `data/releases/<release_id>/manifest.json` | Release ID; source IDs/hashes and membership; actual cutoff; code/dependency/settings versions; frozen settings; method/reference definition; tested spatial/temporal/platform/product scope; metrics; baseline rules; report path/hash. Store fitted parameters here only if small and JSON-compatible. |
| `data/releases/<release_id>/validation.json` | Fixed train/test split IDs; declared targets; results versus baselines; subgroup failures; random seed/repeats; error methods; supported scope; pass/fail decisions. This is evidence, not just a success flag. |

Read `MAP_KEY` from the environment. Keep it out of settings, progress,
manifests, logs, and notebooks. Unsettled scientific settings remain explicit
and block the related published claim. A working settings file is not proof
of validation. Keep editable settings separate from each frozen release.

Use the repository `.gitignore` for generated data and credentials. Preserve
the existing sample; do not silently remove or change its tracking. The two
tiny fixtures below are committed, explicitly invented test inputs. Tutorial
notebooks remain references, with no runtime dependency on their cells.

Proposed settings fields:

| Group | Fields |
| --- | --- |
| `storage` | `database_path`, `staging_path`, `releases_path`, `saved_bytes_limit`, `temporary_bytes_limit`. |
| `downloads` | `sources`, `bbox`, `start_date`, `end_date`, `window_days`, `provider_window_seconds`, `transaction_limit`, `transaction_pause_at`, `timeout_seconds`, `retry_limit`. These select the small first sample; credentials come from the environment. |
| `science` | `study_areas`, `source_policy`, `type_policy`, `confidence_policy`, `grid`, `reference_schedule`, `minimum_coverage_fraction`, `method_id`, `method_version`, `random_seed`, `repeat_count`, `test_splits`, `matching_time_gaps_minutes`, `acceptance_targets`, `rule_notes`. Each rule note links its reason and test report. |
| `api` | `selected_release_id`, `allowed_origins`, `default_page_size`, `maximum_page_size`, `query_limits`, `export_limits`, `request_bytes_limit`, `requests_per_minute`, `stale_after_days`, `public_report_base_url`. |

Use spec v0.4's proposed values: 500 MiB saved, 2 GiB temporary, at most five
days per provider request, transaction pause at 4,000, page size 1,000, and
maximum page size 10,000. Validate these when loading settings. Keep unknown
areas, method rules, and release IDs unset until chosen; do not invent them.
Nested limits must name their units, such as rows, bytes, days, and seconds.
Start with all hotspot types, clearly labeled, as required by v0.4.

### Tests

| File | Focus |
| --- | --- |
| `tests/conftest.py` | Temporary database, invented records/settings, and FastAPI client. No network, real key, or user database. |
| `tests/test_sources.py` | Zero-padded UTC times; original fields; type/unknown handling; textual versions and checked aliases; mixed archive/NRT schemas; band identity/limit flags; zero FRP; duplicate versus neighboring detections; standard/NRT precedence; small batches; download boundaries, resume, and budget/failure handling. |
| `tests/test_harmonization.py` | Matching, unmatched-record retention, coverage, related-observation split isolation, repeatable draws, count/FRP distinction, source changes, fitted-parameter save/load if a fitted method is selected, and failed scientific publication gates. Independent held-out checks remain separate from unit tests. |
| `tests/test_analysis.py` | Missing versus zero, requested-day totals, five usable earlier years, leap-day exclusion, zero median, cell-center versus point boundaries, no spatial support, and unavailable uncertainty. |
| `tests/test_storage.py` | Six-table round trip, timestamps/units, rollback on failed publication, immutable old releases, release source membership, and time/ID paging. |
| `tests/test_api.py` | All eight endpoints, structured errors, release/domain/source-policy checks, limits/CORS, query-bound cursors, GeoJSON order, CSV formula escaping, and exact screen/export agreement. |
| `tests/fixtures/observations.csv` | Small invented multi-year source rows, including time, quality, zero-FRP, and edge cases. Document their invented origin in README. |
| `tests/fixtures/opportunities.csv` | Matching invented scheduled/usable visits, including missing and cloudy visits. Hotspot absence alone cannot establish coverage. |

API examples and manual map/calendar acceptance steps live in README.
FastAPI generates OpenAPI; do not maintain a second handwritten schema.
Report links must resolve through a configured local/deployment report URL;
never expose the whole data directory or filesystem paths to the browser.

The README handoff covers OpenLayers rectangle conversion to `EPSG:4326`,
explicit GeoJSON projections, cancellation of old requests, visible paging,
UTC date handling, and matching screen/download results. The web developer
tests these in `web-app/`; Python tests check the API side. Keep frontend
source files and frontend dependencies out of `time-series-api/`.

For later polygon selections, keep shape checks in `models.py`, database
candidate reads in `storage.py`, and exact point/cell/coverage selection in
`analysis.py`. `selection_geometry(bbox)` converts the MVP rectangle to a
Polygon. No new file is needed. Later polygon requests must use the actual
shape for history, paging, and exports, not just its surrounding rectangle.
OpenLayers drawing stays in `web-app/`. Polygon inputs remain outside the MVP.

Record pilot memory use, import time, rows, and bytes in the validation report.
One measured end-to-end pilot comes before a wider download or experiment.

## Runtime flow

```text
fetch_data.py → sources.py → staging files
prepare_data.py → sources.py → storage.py → source-only release
prepare_data.py → sources.py → harmonization.py → storage.py → checked estimates
check_results.py → storage.py + harmonization.py → validation report

HTTP → main.py → storage.py → analysis.py → JSON / GeoJSON / bounded download
```

Analysis JSON downloads use the same `build_analysis` result as the screen.
Observation downloads use the same release/source selection as point queries.
No request downloads NASA files, fits a method, or draws new random samples.

## Terminology and scope

No scientific, table, metric, or API object names change from spec v0.4.
The module names `sources` and `harmonization` match v0.4 and the earlier tree
proposal. They are not renamed runtime objects. Omit the duplicate `development-spec.md`;
its canonical document remains in `documents/specs/`.

The earlier brainstorming note describes CLI ingestion. Here, the three
scripts provide that entrypoint within v0.4's wider preparation/API scope;
they do not introduce a separate CLI framework or streaming service.

Exact areas, count method, reference visits, acceptance targets, historical
availability, and deployment remain open as stated in the spec. No directory
choice resolves them. Add model artifacts, extra native readers, indexes,
or new modules only when the selected method or measured workload needs them.

Event clustering, fire-spread prediction, economic loss, and automatic
severity alerts remain outside this tree. Local checks come before a hosted
demo. Hosting uses the same fixed release and persistent storage; it does
not need a second database adapter or a live ingestion service.
