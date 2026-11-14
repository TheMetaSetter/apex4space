# time-series-api: proposed interfaces

Status: design only. No application code or security test has run.
Based on [spec v0.4](time-series-api-devspec.md) and the
[directory tree](../logs/2026-11-13/structure/time-series-api-directory-tree.md).
Keep the six modules and three scripts. This document fills in their types
and calls; it does not choose the still-untested scientific method.

## 1. Design steps and choice

- [x] Phase 1 — Read requirements with file tools.
  - [x] Read the spec, tree, repository rules, and Python semantics guide.
  - [x] Check official Python, FastAPI, Pydantic, and Starlette docs.
- [x] Phase 2 — Write the interfaces in Markdown.
  - [x] Define shared data and HTTP contracts.
  - [x] Define calls in file order and their security rules.
  - [x] Define web handoff examples and focused checks.
- [x] Phase 3 — Check the design with Python and a manual review.
  - [x] Parse the Python examples and check local links.
  - [x] Check names, endpoint coverage, limits, and failure paths.

| Choice | Benefit | Cost |
| --- | --- | --- |
| Functions plus typed data | Few calls; easy to test. Chosen. | Callers pass their settings and data. |
| A service class for each module | Holds shared state | Adds object lifetimes and hidden dependencies. |
| Generic repositories and plugins | Supports many backends | Adds work without an MVP need. |

Use classes for data, one error type, and one small request guard. Data
classes have no business methods. Use keyword arguments for limits and
settings. Do not add an interface for a second database or an unchosen model.

## 2. Shared types: app/models.py

HTTP/settings classes use Pydantic `BaseModel`. Internal records use
`@dataclass(frozen=True, kw_only=True)`. Each field table below defines the
class constructor: listed fields are required unless a default is shown.
Tuples and dates become JSON arrays and ISO strings in HTTP responses.
No SQL row, connection, local path, or secret belongs in a public response.

```python
from collections.abc import Iterator, Mapping, Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Literal, Self, TypedDict

from pydantic import JsonValue

BBox = tuple[float, float, float, float]
MetricName = Literal[
    "observed_hotspot_count", "harmonized_hotspot_count",
    "active_cell_count", "frp_pass_sum_mw", "valid_coverage_fraction",
]
PeriodStatus = Literal[
    "available", "observed_zero", "partial", "low_coverage", "missing",
    "insufficient_baseline", "not_validated",
]
Aggregation = Literal["day", "month"]

class PointGeometry(TypedDict):
    type: Literal["Point"]
    coordinates: tuple[float, float]

class PolygonGeometry(TypedDict):
    type: Literal["Polygon"]
    coordinates: tuple[tuple[tuple[float, float], ...], ...]

class MultiPolygonGeometry(TypedDict):
    type: Literal["MultiPolygon"]
    coordinates: tuple[tuple[tuple[tuple[float, float], ...], ...], ...]

AreaGeometry = PolygonGeometry | MultiPolygonGeometry
```

Use `extra="forbid"`, finite numbers, and frozen fields on HTTP models.
Reject numeric strings and booleans where numbers are required. Accept only
ISO `YYYY-MM-DD` strings for HTTP dates; reject timestamps there. Parse UTC
observation timestamps separately. Do not enable blanket strict Python-mode
date checking that would also reject valid JSON date strings.
Collections have length limits. Never use a mutable default list or dict.

### Request classes

| Class | Fields |
| --- | --- |
| `ComparisonRequest` | `mode: Literal["same_elapsed_days"]`; `baseline_start_year: int`; `baseline_end_year: int`. |
| `AnalysisRequest` | `release_id: str`; `bbox: BBox`; `start_date: date`; `end_date: date`; `metric: MetricName`; `aggregation: Aggregation`; `comparison: ComparisonRequest | None = None`; `platforms: tuple[str, ...] | None = None`. |
| `HotspotQuery` | `release_id: str`; `bbox: BBox`; `start_date: date`; `end_date: date`; `platforms: tuple[str, ...]`; `page_size: int = 1000`; `cursor: str | None = None`. |
| `ExportRequest` | `release_id: str`; `bbox: BBox`; `start_date: date`; `end_date: date`; `kind: Literal["observations", "analysis"]`; `format: Literal["csv", "json"]`; `platforms: tuple[str, ...] | None = None`; `metric: MetricName | None = None`; `aggregation: Aggregation | None = None`; `comparison: ComparisonRequest | None = None`. |

Keep export fields flat, like the spec. Observations require `csv` and
platforms, and forbid analysis-only fields. Analysis requires `json`, metric,
and aggregation. `comparison=null` means no historical comparison was asked
for. Original analysis requires platforms. Harmonized analysis rejects any
platform override with `REFERENCE_POLICY_CONFLICT`.

Request validators are Pydantic after-validators with these signatures:

```python
# Methods on the named classes; use @model_validator(mode="after").
# Self means the same class, from typing.Self.
def validate_fields(self) -> Self: ...

# Ordinary functions in models.py.
def load_settings(path: Path) -> Settings: ...
def validate_bbox(bbox: BBox) -> BBox: ...
def selection_geometry(bbox: BBox) -> PolygonGeometry: ...
```

Give `validate_fields` to the four request classes and `Settings` only where
cross-field checks are needed. A field constraint handles simple bounds.
`validate_bbox` requires finite values, −180 ≤ west < east ≤ 180 and
−90 ≤ south < north ≤ 90. Dates require start < end. Reject duplicate/empty
platforms. IDs are 1–64 ASCII letters, digits, `_` or `-`; they are identifiers,
not paths. Cursor length is limited to 2,048 characters before decoding.

`selection_geometry` turns checked bounds into one closed rectangle ring in
longitude/latitude order. Use it for the shared area rules. It adds no public
request field. Existing `AreaGeometry` types describe actual footprints and
used cells; they do not mean the MVP accepts polygon requests.

Historical years must be ordered and earlier than the target year. For a
comparison, keep the target window within one calendar year in the first MVP;
return 422 for a cross-year target rather than choosing a meaning silently.
No-comparison queries may span years. This is a proposed clarification of
v0.4, not an already implemented restriction.

### Response classes

| Class | Fields |
| --- | --- |
| `Notice` | `code: str`; `message: str`. Stable code; human-readable message. |
| `HealthResponse` | `status: Literal["ok"]`. Readiness failure uses the error response and 503. |
| `MetricDefinition` | `name: MetricName`; `unit: str`; `definition: str`; `allowed_aggregations: tuple[Aggregation, ...]`. A pass-only metric has an empty tuple. |
| `ReleaseSummary` | `release_id: str`; `study_areas: tuple[BBox, ...]`; `start_date: date`; `end_date: date`; `latest_source_dates: Mapping[str, date]`; `available_metrics: tuple[MetricName, ...]`; `allowed_platforms: tuple[str, ...]`. |
| `CoverageResult` | `expected_days: int`; `usable_days: int | None`; `numerator: float | None`; `denominator: float | None`; `unit: Literal["km2_visits"]`; `valid_coverage_fraction: float | None`. |
| `HistoricalComparison` | `status: Literal["available", "insufficient_baseline"]`; `median: float | None`; `years_used: tuple[int, ...]`; `excluded_years: Mapping[int, str]`; `absolute_difference: float | None`; `percentage_difference: float | None`; `warnings: tuple[Notice, ...]`. |
| `UncertaintyResult` | `lower: float`; `upper: float`; `method: str`. Only return after the method is checked. |
| `PeriodResult` | `start_date: date`; `end_date: date`; `value: int | float | None`; `partial_value: int | float | None`; `original_count: int`; `original_count_rule: str`; `coverage: CoverageResult`; `baseline: HistoricalComparison | None`; `uncertainty: UncertaintyResult | None`; `status: PeriodStatus`; `partial_calendar_period: bool`; `old_data: bool`; `warnings: tuple[Notice, ...]`. |
| `AnalysisResponse` | `query: AnalysisRequest`; `requested_bbox: BBox`; `used_area: AreaGeometry | None`; `release_id: str`; `method_id: str | None`; `reference_count_definition: str | None`; `unit: str`; `latest_source_date: date | None`; `response_time_ms: float`; `summary: PeriodResult`; `calendar: tuple[PeriodResult, ...]`; `warnings: tuple[Notice, ...]`. |
| `ErrorResponse` | `code: str`; `message: str`; `details: Mapping[str, JsonValue]`; `request_id: str`. No nested `detail` wrapper. |

`used_area` is a checked GeoJSON Polygon/MultiPolygon, including the union
of whole selected cells, or null when no spatial support exists. It is not
an arbitrary JSON payload. Point coordinates use longitude first.
Daily/monthly values use the requested half-open dates. The summary compares
the whole requested window; each calendar entry compares its own window.
Baseline fields stay separate from observation coverage and main status.
Missing estimates use null even when `original_count=0`.

`GET /v1/releases` returns an array of `ReleaseSummary`.
`GET /v1/metrics` returns an array of `MetricDefinition`.
`GET /v1/releases/{release_id}` returns a public projection of `ReleaseRecord`
with settings, source IDs/hashes, and report URLs; omit local paths and keys.

Hotspot responses are GeoJSON FeatureCollections, with these typed members:

| Class | Fields |
| --- | --- |
| `HotspotProperties` | `observed_at: datetime`; `platform: str`; `instrument: str`; `product: str`; `version: str`; `source_file_id: str`; `source_row_id: int`; `pass_id: str | None`; `frp_mw: float | None`; `confidence: str | None`; `hotspot_type: str`; `quality: tuple[str, ...]`; `bands: tuple[BandRecord, ...]`. |
| `HotspotFeature` | `type: Literal["Feature"]`; `id: str`; `geometry: PointGeometry`; `properties: HotspotProperties`. |
| `HotspotPage` | `type: Literal["FeatureCollection"]`; `features: tuple[HotspotFeature, ...]`; `query: HotspotQuery`; `release_id: str`; `next_cursor: str | None`; `has_more: bool`. |

Use `next_cursor=null` exactly when `has_more=false`. Do not claim the page
length is the total. Keep band names, values, units, and limit flags together.
OpenAPI must describe concrete Point/Polygon shapes, not free-form JSON.

### Internal records

These frozen data classes share the same names across all modules.
`JsonValue` below is only for checked metadata, not pickled objects.

| Class | Constructor fields |
| --- | --- |
| `SourceFileRecord` | `source_file_id: str`; `source_id: str`; `product: str`; `version: str`; `processing_mode: str`; `start_date: date`; `end_date: date`; `downloaded_at: datetime`; `sha256: str`; `request_parameters: Mapping[str, JsonValue]`. |
| `ObservationRecord` | `observation_id: str`; `source_file_id: str`; `source_row_id: int`; `pass_id: str | None`; `platform: str`; `instrument: str`; `observed_at: datetime`; `longitude: float`; `latitude: float`; `scan_km: float | None`; `track_km: float | None`; `frp_mw: float | None`; `confidence: str | None`; `hotspot_type: str`; `quality: tuple[str, ...]`; `original_fields: Mapping[str, str]`. |
| `BandRecord` | `observation_id: str`; `band_name: str`; `value: float | None`; `unit: str`; `flags: tuple[str, ...]`. |
| `OpportunityRecord` | `source_file_id: str`; `pass_id: str`; `platform: str`; `observed_at: datetime`; `footprint: AreaGeometry`; `usable_footprint: AreaGeometry | None`; `expected: bool | None`; `quality: str`. Areas use the declared equal-area calculation, not map-screen area. |
| `DailyRecord` | `release_id: str`; `method_id: str | None`; `cell_id: str`; `cell_area: AreaGeometry`; `cell_center: PointGeometry`; `date: date`; `source_count: int`; `reference_count_estimate: float | None`; `coverage: CoverageResult`; `uncertainty: UncertaintyResult | None`; `status: PeriodStatus`. |
| `ReleaseRecord` | `summary: ReleaseSummary`; `method_id: str | None`; `reference_count_definition: str | None`; `code_version: str`; `settings: Mapping[str, JsonValue]`; `source_files: tuple[SourceFileRecord, ...]`; `source_selection: Mapping[str, JsonValue]`; `baseline_rules: Mapping[str, JsonValue]`; `report_sha256: str`; `report_urls: tuple[str, ...]`. |
| `SourceBatch` | `source_file: SourceFileRecord`; `observations: tuple[ObservationRecord, ...]`; `bands: tuple[BandRecord, ...]`; `opportunities: tuple[OpportunityRecord, ...]`. Batches may contain only opportunities. |
| `AnalysisInputs` | `observations: tuple[ObservationRecord, ...]`; `daily: tuple[DailyRecord, ...]`; `opportunities: tuple[OpportunityRecord, ...]`. Requested and baseline data only, within limits. |
| `CursorPosition` | `observed_at: datetime`; `observation_id: str`. Last returned row, not an offset. |
| `ObservationPage` | `observations: tuple[ObservationRecord, ...]`; `bands: tuple[BandRecord, ...]`; `next_position: CursorPosition | None`. Internal storage result. |
| `MatchResult` | `pairs: tuple[tuple[str, str], ...]`; `unmatched_observation_ids: tuple[str, ...]`; `settings: Mapping[str, JsonValue]`. Pairs may be many-to-one. |
| `ValidationReport` | `release_id: str`; `checks: Mapping[str, JsonValue]`; `supported_metrics: tuple[MetricName, ...]`; `tested_scope: Mapping[str, JsonValue]`; `failures: tuple[Notice, ...]`; `random_seed: int | None`; `repeat_count: int | None`; `memory_bytes: int`; `elapsed_seconds: float`. |

IDs are immutable. Observation IDs identify source observations; they are not
fire IDs. Keep file and row IDs even when rows are rejected by a policy.
Freeze source-file membership plus the exact row/selection rules in a release.
Never mutate a stored observation when a standard product replaces NRT.
Frozen classes do not freeze nested dicts: copy mappings on construction and
do not share mutable mappings across requests.
Check UTC awareness, finite coordinates/values, nonnegative counts/FRP,
closed polygon rings, ring/vertex limits, and coverage bounds at data entry.
Unknown values stay null. Do not infer a usable footprint from an empty file.
Malformed records cannot become checked data merely by being put in a class.
The grid supplies each cell's checked center in longitude/latitude order.
Store it with the daily row; do not guess it from the centroid of a projected
cell after conversion to geographic coordinates. `cell_center` is a new
internal field. No real release or database existed when it was added; later
schema changes must preserve old releases.

### Settings classes

`Settings` has exactly `storage`, `downloads`, `science`, and `api`, using
the four classes below. Load JSON from a trusted operator path, with a file
size limit. Resolve relative paths against the project folder, not the
caller's current directory. API input cannot set any of these paths.

| Class | Fields |
| --- | --- |
| `StorageSettings` | `database_path: Path`; `staging_path: Path`; `releases_path: Path`; `saved_bytes_limit: int`; `temporary_bytes_limit: int`. |
| `DownloadSettings` | `sources: tuple[str, ...]`; `bbox: BBox`; `start_date: date`; `end_date: date`; `window_days: int`; `provider_window_seconds: int`; `transaction_limit: int`; `transaction_pause_at: int`; `timeout_seconds: float`; `retry_limit: int`. |
| `ScienceSettings` | `study_areas: tuple[BBox, ...]`; `source_policy: Mapping[str, JsonValue]`; `type_policy: str`; `confidence_policy: Mapping[str, JsonValue]`; `grid: Mapping[str, JsonValue]`; `reference_schedule: Mapping[str, JsonValue]`; `minimum_coverage_fraction: float`; `method_id: str | None`; `method_version: str | None`; `random_seed: int`; `repeat_count: int`; `test_splits: Mapping[str, JsonValue]`; `matching_time_gaps_minutes: tuple[int, ...]`; `acceptance_targets: Mapping[str, JsonValue]`; `rule_notes: Mapping[str, str]`. |
| `ApiSettings` | Tree fields: `selected_release_id: str | None`; `allowed_origins: tuple[str, ...]`; `default_page_size: int`; `maximum_page_size: int`; `query_limits: Mapping[str, int]`; `export_limits: Mapping[str, int]`; `request_bytes_limit: int`; `requests_per_minute: int`; `stale_after_days: int`; `public_report_base_url: str | None`. Add `allowed_hosts: tuple[str, ...]` for trusted HTTP hosts. |

`query_limits` keys: `maximum_days`, `maximum_baseline_years`,
`maximum_input_rows`, `maximum_cells`, `maximum_execution_seconds`.
`export_limits` keys: `maximum_rows`, `maximum_bytes`,
`maximum_execution_seconds`. All must be positive and set before serving.
Download/pilot limits are separate from HTTP limits. Validate the science
mapping keys and values for the selected method; no free-form expressions,
module names, SQL, or executable formulas. Unchosen science settings may be
empty only for a source-only release. Use the tree's stated defaults.

### One error class

```python
class ApiError(Exception):
    def __init__(
        self, status_code: int, code: str, message: str,
        *, details: Mapping[str, JsonValue] | None = None,
    ) -> None: ...
```

Only safe, explicit details cross HTTP. Raw exception text stays out of the
response. A server-created request ID is added by `main.py`.

## 3. HTTP calls: app/main.py

`create_app` loads settings, reads `CURSOR_SECRET` from the environment,
checks the selected release, and registers the routes below. Require at
least 32 random bytes for that secret; keep the same secret across restarts
when existing cursors must remain usable. Do not reuse `FIRMS_MAP_KEY` as this key.
An unset selected release is allowed for offline preparation, but blocks serving.
Use dependency injection through app state for settings and trusted secrets,
not module globals. `app/__init__.py` stays empty.

```python
def create_app(settings_path: Path | None = None) -> FastAPI: ...

def health_live() -> HealthResponse: ...
def health_ready(request: Request) -> HealthResponse: ...
def list_releases(request: Request) -> tuple[ReleaseSummary, ...]: ...
def get_release(release_id: str, request: Request) -> ReleasePublicResponse: ...
def list_metrics() -> tuple[MetricDefinition, ...]: ...
def analyze(query: AnalysisRequest, request: Request) -> AnalysisResponse: ...
def query_hotspots(query: HotspotQuery, request: Request) -> HotspotPage: ...
def export_results(query: ExportRequest, request: Request) -> Response: ...

def handle_api_error(request: Request, error: ApiError) -> JSONResponse: ...
def handle_validation_error(
    request: Request, error: RequestValidationError,
) -> JSONResponse: ...
def handle_server_error(request: Request, error: Exception) -> JSONResponse: ...

def encode_cursor(
    position: CursorPosition, query: HotspotQuery, *, secret: bytes,
) -> str: ...
def decode_cursor(
    token: str, query: HotspotQuery, *, secret: bytes,
) -> CursorPosition: ...
def to_geojson(
    page: ObservationPage, query: HotspotQuery, *, secret: bytes,
) -> HotspotPage: ...
def build_export(
    query: ExportRequest, *, settings: Settings,
) -> tuple[bytes, str, str]: ...
```

Imports: FastAPI/Request, Starlette response classes, and FastAPI's
`RequestValidationError`. `ReleasePublicResponse` is a Pydantic class with
the fields of `ReleaseRecord` above; its settings and selection metadata
contain only science/source data. Storage paths, provider URLs bearing keys,
and private server settings are excluded by an explicit response model.

When `settings_path` is `None`, use
`Path(__file__).resolve().parents[1] / "config/settings.json"`. An explicit
path keeps the same meaning. This changes startup arguments only; it does not
rename an HTTP, settings, database, or checkpoint field.

Routes, in order: `/health/live`, `/health/ready`, `/v1/releases`,
`/v1/releases/{release_id}`, `/v1/metrics`, `/v1/analysis`,
`/v1/hotspots/query`, `/v1/exports`. First five use GET; last three use POST.
Route names above become stable OpenAPI operation IDs. Sync route functions
let FastAPI run blocking SQLite work outside the event loop.

The cursor contains a version, query digest, release ID, and row position.
Sign its canonical JSON bytes with HMAC-SHA256; verify with
`hmac.compare_digest` before using the position. Bind all query fields except
`cursor`, including page size and normalized platforms. Base64 is encoding,
not encryption: the cursor contains no secret or private data. Reject an
invalid signature/query/version with 422 `INVALID_CURSOR`.

`build_export` returns `(body, media_type, filename)`. Build the limited
result before response headers are sent, then send it directly. This keeps
413 possible for row/byte/time limits; never return a truncated CSV as a
successful download. The bounded in-memory body is the chosen small-MVP
trade-off. Check the byte limit as UTF-8 rows are encoded, not after joining
an unlimited list. Include this memory in deployment limits. Use `csv.writer`
and prefix dangerous text cells, including leading whitespace followed by
`=`, `+`, `-`, or `@`; do not rewrite real numeric values. Generate download
filenames on the server. Analysis exports call the same analysis builder.

### Request guard

```python
# ASGIApp, Scope, Receive, Send come from starlette.types.
class RequestGuard:
    def __init__(self, app: ASGIApp, *, settings: ApiSettings) -> None: ...
    async def __call__(
        self, scope: Scope, receive: Receive, send: Send,
    ) -> None: ...
```

Count actual incoming bytes before parsing JSON, including requests without
Content-Length. Reject oversized bodies with 413. Accept JSON on the three
POST routes; use 415 for other media types. Require uncompressed request
bodies in the MVP to avoid compressed-size surprises. Use one fixed-size,
process-wide rate bucket and monotonic time: no growing per-client dict.
Return 429 with Retry-After. This simple limit is for one process and is not
a claim of protection from large network attacks. Count updates occur without
await points. Body counters and request IDs stay local to each request.

Use built-in TrustedHost and CORS middleware; no custom authentication stack.
Allow exact configured origins, GET/POST/OPTIONS, and required headers only.
Expose `Content-Disposition`, `X-Request-ID`, and `Retry-After` to the browser.
Wrap error responses with CORS too. CORS is not access control for a public
read API. Default local serving binds to loopback; public hosting adds HTTPS,
connection/time limits, and trusted proxy settings before it is exposed.
Do not trust arbitrary forwarded headers or log request bodies/full queries.

## 4. Source calls: app/sources.py

```python
def fetch_windows(settings: Settings) -> Iterator[SourceFileRecord]: ...
def read_source(
    path: Path, source_definition: SourceFileRecord, *, batch_size: int,
) -> Iterator[SourceBatch]: ...
def read_opportunities(
    path: Path, source_definition: SourceFileRecord, *, batch_size: int,
) -> Iterator[SourceBatch]: ...
def select_source_records(
    records: Sequence[ObservationRecord], policy: Mapping[str, JsonValue],
) -> tuple[ObservationRecord, ...]: ...
```

`fetch_windows` reads `FIRMS_MAP_KEY` from the environment or the repository
`.env` and never returns it. The environment takes priority. Only configured
NASA endpoints and checked source IDs are allowed. No user-supplied URL,
hostname, output path, or redirect target. Use HTTPS verification, timeouts,
small retry limits, and the provider's actual transaction status. Unknown
budget means stop. Check bytes while reading even if Content-Length is absent;
compressed inputs need a decoded-byte limit too. Save progress after a checked
window. Partial files never become completed downloads.

Paths here come only from trusted offline settings/progress, stay under the
staging root, and reject unexpected symlinks. Do not automatically extract
ZIPs. Native readers use only the selected product format. Bad schemas or
ambiguous product/alias mappings fail closed for harmonized work. CSV empty
rows and provider HTML errors are not evidence of zero activity. Keep UTC,
original confidence/type/version, band flags, file hashes, and row IDs.

An NRT file can contain NRT, RT, and URT rows from the same collection. In
that case, `SourceFileRecord.version` holds the collection text, such as
`2.0`; each observation keeps its full row version in `original_fields`.
A single-version file may keep its full version in the source record. Reject
other collections and processing modes. Do not convert version text to a
number. For a VIIRS export whose second band is called `bright_t31`, preserve
it as an unverified band until its meaning is checked against the product.

Source selection must also check overlap across batches/files; it cannot
deduplicate correctly with an isolated batch alone. Storage enforces stable
observation identities; publication applies the frozen selection rule across
the full candidate release. Neighboring pixels and unmatched detections stay.
The MVP policy accepts optional `types`, `confidences`, and
`preferred_sources` lists. An omitted filter keeps all values. The preferred
list contains source file IDs in priority order. Exact repeated rows in one
file keep their first row. If an exact repeat occurs in different files, both
files must appear in the preferred list; otherwise selection stops. Record the
chosen and rejected row IDs in the release. Do not infer that nearby pixels
are the same observation. For this exact-row check, compare the mapped
platform and source values, and compare original fields except the satellite
alias and version text. Records with other differences stay separate.

## 5. Science calls: app/harmonization.py

```python
def match_passes(
    observations: Sequence[ObservationRecord],
    opportunities: Sequence[OpportunityRecord], *, settings: ScienceSettings,
) -> MatchResult: ...
def compare_frp(
    matches: MatchResult, observations: Sequence[ObservationRecord],
    *, release_id: str, settings: ScienceSettings,
) -> ValidationReport: ...
def evaluate_counts(
    matches: MatchResult, observations: Sequence[ObservationRecord],
    *, release_id: str, settings: ScienceSettings,
) -> ValidationReport: ...
def prepare_daily(
    batches: Iterator[SourceBatch], *, release_id: str,
    settings: ScienceSettings,
) -> Iterator[DailyRecord]: ...
```

Matching runs on a small declared area/time block, including the nearby
visits needed at block edges. Do not lose matches by splitting a pass across
arbitrary CSV batches. The offline caller enforces the block memory limit.
Report settings include the candidate release ID, split IDs, reference rule,
seed, repeats, supported scope, and predeclared targets. Test data never tune
the method. The FRP adapter is a private function here, pinned to reviewed
reference code; its exact input signature waits for the checked product reader.

`prepare_daily` carries incomplete blocks until their needed observations
arrive; it has a bounded working set. Fail if a block exceeds the pilot
budget rather than silently dropping rows. Until a method is chosen, no
model class, fit API, or checkpoint loader is promised. Source-only daily
results may have null estimates. There is no science call in an HTTP route.

## 6. Query calls: app/analysis.py

```python
def validate_query_domain(
    query: AnalysisRequest | HotspotQuery | ExportRequest,
    release: ReleaseRecord, *, settings: ApiSettings,
) -> None: ...
def summarize_periods(
    query: AnalysisRequest, records: AnalysisInputs, release: ReleaseRecord,
) -> tuple[PeriodResult, ...]: ...
def compare_history(
    query: AnalysisRequest, records: AnalysisInputs, release: ReleaseRecord,
) -> HistoricalComparison | None: ...
def build_analysis(
    query: AnalysisRequest, records: AnalysisInputs, release: ReleaseRecord,
) -> AnalysisResponse: ...
```

Reject unsupported metric/aggregation pairs, source overrides, and queries
outside the release, including historical windows. Point boundaries use
source coordinates; estimates use cell centers. Never use a daily cell count
as an exact raw-point rectangle count. `summarize_periods` creates every
requested calendar period. `build_analysis` also builds the whole-window
summary; it does not add historical medians or uncertainty endpoints.

Missing data, low coverage, and zero are distinct. Baselines use five usable
earlier years with identical day windows and no February 29. Unknown usable
coverage stays null; an empty point result alone cannot establish coverage.
An unavailable baseline is a valid response with reasons, not an exception.
These functions do not mutate input data. `main.py` fills response timing
after the calculation; timing is transport metadata, not a scientific value.

## 7. Database calls: app/storage.py

```python
def initialize_database(path: Path) -> None: ...
def list_releases(path: Path) -> tuple[ReleaseSummary, ...]: ...
def load_release(path: Path, release_id: str) -> ReleaseRecord: ...
def read_daily(
    path: Path, query: AnalysisRequest, *, settings: ApiSettings,
) -> AnalysisInputs: ...
def read_observations(
    path: Path, query: HotspotQuery, position: CursorPosition | None,
) -> ObservationPage: ...
def publish_release(
    path: Path, batches: Iterator[SourceBatch], daily: Iterator[DailyRecord],
    manifest: ReleaseRecord, report: ValidationReport,
    *, storage: StorageSettings,
) -> None: ...
```

`read_daily` is the tree's name for loading analysis inputs. It loads the
needed daily estimates, original points, and coverage for target and baseline
windows. Row/cell limits apply before returning tuples. For exports, use
`read_observations` repeatedly with the same checked query; no separate raw
SQL export path. `publish_release` consumes independent iterators over saved
source inputs; do not reuse a consumed generator for daily results.

All SQL and schema creation stay here. Bind values with SQL parameters;
table/column/sort names come from fixed code, never a query field. Reads open
the existing database in read-only mode and close it on success or error.
Never silently create an empty database during an API request. Use a bounded
SQLite execution deadline as well as a lock timeout. No extension loading,
arbitrary SQL endpoint, pickle, or shared cross-thread connection.

Page by `(observed_at, observation_id)`, with one extra row to detect more
results. Match only the requested release's frozen source selection. Enforce
foreign keys and basic value constraints on offline writes. Never overwrite
a published release ID or delete older source rows during replacement.

Publication stops serving. Check that report and manifest refer to the same
source hashes, settings, code, method, release ID, and tested scope. Published
metrics must be a subset of the report's supported metrics. Write the files
in the trusted release folder, then commit data and its release row in one transaction.
Until commit the release is invisible. A crash may leave an unused folder,
but not a published half-release. Check file hashes against the database
record before serving; keep release files read-only for the serving account.
Failed publication rolls back SQL; cleanup targets only its own unused files.
Do not run this writer through HTTP or make public file paths from release IDs.

For this SQLite schema, `source_selection` contains `rows`: a mapping from
each source file ID to its selected source row IDs. The list may be empty.
The manifest settings contain `schema_version` and `tested_scope`. The
validation report's `checks.provenance` contains `source_hashes`,
`code_version`, `method_id`, and `settings`. Publication requires these
values and the report's `tested_scope` to match the manifest. A source-only
report can list a failed science check, but it cannot list a metric that the
report does not support. This representation is for a small MVP release;
measure its size before expanding the data.
Until the scientific checks are complete, publication rejects every non-null
method ID. T11 can replace this gate only with a check backed by the selected
method's independent test report.

## 8. Script entrypoints

Each script defines the following functions in its own file. `argv=None`
means normal command-line arguments. Exit 0 means success; nonzero means the
requested step failed or required inputs are missing. Use a __main__ guard.

```python
def parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace: ...
def main(argv: Sequence[str] | None = None) -> int: ...
```

| File | Arguments and work |
| --- | --- |
| `scripts/fetch_data.py` | `--settings` (default `config/settings.json` relative to the project). Check availability/budget, fetch small windows, save progress. Never accept a raw provider URL or key argument. |
| `scripts/prepare_data.py` | `--settings`; required `--release-id`. Read saved inputs, apply release policy, compute supported results, check, publish. A source-only release cannot advertise harmonized metrics. |
| `scripts/check_results.py` | `--settings`; required `--release-id`. Load a saved release, rerun its declared checks from traceable inputs, report failures. Never change a published report/data file; print a rerun result or write an operator-selected review file outside the release folder. |

Importing a script starts no work. Commands and their defaults are documented
from their parser code when implemented, not inferred from this proposal.

## 9. Errors and focused tests

| HTTP | Stable codes |
| --- | --- |
| 422 | `INVALID_QUERY`, `INVALID_CURSOR`, `OUTSIDE_RELEASE_DOMAIN` |
| 404 | `RELEASE_NOT_FOUND` |
| 409 | `METRIC_NOT_AVAILABLE`, `REFERENCE_POLICY_CONFLICT` |
| 413 | `REQUEST_TOO_LARGE`, `QUERY_TOO_LARGE`, `EXPORT_TOO_LARGE` |
| 415 | `UNSUPPORTED_MEDIA_TYPE` |
| 429 | `RATE_LIMITED` |
| 503 | `SERVICE_UNAVAILABLE` |
| 500 | `INTERNAL_ERROR` for an unexpected programming failure |

Known temporary DB/dependency failures use 503; do not hide every bug as a
retryable service failure. Validation errors include safe field locations and
reasons, without echoing the submitted body. All errors use ErrorResponse.

Keep the existing test files. Proposed tests use plain Pytest functions:

```python
# tests/conftest.py: fixtures
def settings(tmp_path: Path) -> Settings: ...
def database(tmp_path: Path, settings: Settings) -> Path: ...
def client(settings: Settings, database: Path) -> Iterator[TestClient]: ...

# Representative tests; add focused cases within the same files.
def test_source_reader_keeps_text_versions(tmp_path: Path) -> None: ...
def test_matching_keeps_unmatched_records() -> None: ...
def test_missing_is_not_zero() -> None: ...
def test_old_release_is_unchanged_after_publication(database: Path) -> None: ...
def test_cursor_rejects_a_changed_query(client: TestClient) -> None: ...
def test_body_limit_without_content_length(client: TestClient) -> None: ...
def test_export_limit_returns_error_before_download(client: TestClient) -> None: ...
```

Also check query/SQL injection strings, path-like release IDs, finite numeric
bounds, harmful CSV text, unexpected redirects, real byte limits, DB rollback,
safe errors/CORS headers, rate limits, malformed cursors, and browser examples.
Use local fixtures and mocked network calls. No live keys or bulk downloads
in unit tests. Save/load parity is required if a fitted method is later added.

## 10. Web developer handoff

One OpenAPI schema is generated from the actual models. README contains
small copyable JSON/fetch examples and a short error-code table. Add normal,
zero, missing, partial, and unsupported examples to OpenAPI. Clearly label
invented examples. The frontend may generate TypeScript types from that schema;
do not hand-maintain a second conflicting contract.

Use explicit JSON nulls and stable field names. Requests use YYYY-MM-DD;
observations return UTC ISO timestamps with `Z`. Keep status and warning codes
stable so UI code does not parse English messages. `X-Request-ID` helps the
developer report an error without exposing private logs.

Example point query, with an invented release and area:

```json
{
  "release_id": "pilot-example-v1",
  "bbox": [106.0, 10.0, 107.0, 11.0],
  "start_date": "2026-09-01",
  "end_date": "2026-09-03",
  "platforms": ["Aqua"],
  "page_size": 1000,
  "cursor": null
}
```

The next request changes only `cursor`. The frontend keeps the full query
and release until paging ends. For a CSV download, remove page_size/cursor
and add `kind="observations"`, `format="csv"`. Analysis export adds
`kind="analysis"`, `format="json"` to the analysis fields. For comparison,
screen and export scientific fields match; response timing may differ.

OpenLayers sends the drawn rectangle as EPSG:4326 bounds and reads Point
GeoJSON into the actual map projection. Abort/ignore old responses; clear the
old point layer after a query change. A page is not a total and a grouped
map symbol is not a real fire event. CORS exposes the download filename.

## 11. Naming and small clarifications

### Later polygon requests

Keep the MVP's required `bbox`. In a future API revision, accept exactly one
of `bbox` or `geometry` and keep old rectangle requests valid. Convert either
input to a checked selection shape. SQL may first filter its bounds, but
analysis must use the actual shape for points, cell centers, and coverage.
History and exports reuse that selection. A cursor digest includes the full
checked shape; two polygons with the same bounds must not share a cursor.

Add polygon validation, coordinate/ring/vertex limits, and tests before
enabling this input. Do not silently repair invalid shapes or simplify them
to fit a limit. Define and test boundary and hole rules. Keep requested shape
and used cell area separate in the future response, with an explicit schema
change rather than changing `requested_bbox` to mean a polygon.
OpenLayers polygon drawing belongs in web-app; it does not change the count
method or turn hotspots into real fire events. No general geometry framework
or unused polygon handlers are needed now.

### Current names

Existing tree function/class names are kept. No table, scientific metric,
status, or stored checkpoint name changes. Newly named records describe
existing data, not new services. `ApiError` remains the exception;
`ErrorResponse` is its HTTP shape. `ObservationPage` is internal data;
`HotspotPage` is GeoJSON. Their stored content and callers differ, so they are
not aliases. Settings and all public data types belong in models.py.

Small proposed clarifications: `allowed_hosts`, CURSOR_SECRET, 415/500 error
codes, a one-year target for historical comparisons, prebuilt limited
exports, and a timing-only difference between screen/export responses.
These add no modules/services. The exact count method, footprint
reader, final science settings, and any model checkpoint remain open.
Do not call the system secure or scientifically checked from this document.

## 12. Official references

- [Python SQLite](https://docs.python.org/3/library/sqlite3.html): parameter binding and read-only URI connections.
- [Python HMAC](https://docs.python.org/3/library/hmac.html): keyed signatures and constant-time digest comparison.
- [Pydantic configuration](https://docs.pydantic.dev/latest/api/config/): extra fields, finite numbers, and frozen models.
- [FastAPI response models](https://fastapi.tiangolo.com/tutorial/response-model/): explicit output models and OpenAPI.
- [FastAPI CORS](https://fastapi.tiangolo.com/tutorial/cors/): origins and browser access.
- [Starlette middleware](https://starlette.dev/middleware/): trusted hosts, CORS wrapping, and ASGI calls.

Check the installed versions before implementation; these signatures are a
proposal, not a promise that every current library default matches the design.
