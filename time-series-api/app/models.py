"""Shared types for the time-series API."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
import re
from typing import Literal, Self, TypedDict

from pydantic import BaseModel, ConfigDict, JsonValue, StrictFloat, StrictInt, model_validator

BBox = tuple[float, float, float, float]
MetricName = Literal[
    "observed_hotspot_count", "harmonized_hotspot_count", "active_cell_count",
    "frp_pass_sum_mw", "valid_coverage_fraction",
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

class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

class ComparisonRequest(ContractModel):
    mode: Literal["same_elapsed_days"]
    baseline_start_year: StrictInt
    baseline_end_year: StrictInt
    @model_validator(mode="after")
    def validate_fields(self) -> Self:
        if not 1 <= self.baseline_start_year <= self.baseline_end_year <= 9999:
            raise ValueError("invalid baseline years")
        return self

class RequestModel(ContractModel):
    release_id: str
    bbox: BBox
    start_date: date
    end_date: date
    @model_validator(mode="before")
    @classmethod
    def validate_input(cls, value: object) -> object:
        return _check_request_input(value)

class AnalysisRequest(RequestModel):
    metric: MetricName
    aggregation: Aggregation
    comparison: ComparisonRequest | None = None
    platforms: tuple[str, ...] | None = None
    @model_validator(mode="after")
    def validate_fields(self) -> Self:
        _check_request(self)
        return self

class HotspotQuery(RequestModel):
    platforms: tuple[str, ...]
    page_size: int = 1000
    cursor: str | None = None
    @model_validator(mode="after")
    def validate_fields(self) -> Self:
        _check_request(self)
        if not 1 <= self.page_size <= 10000 or (self.cursor is not None and len(self.cursor) > 2048):
            raise ValueError("invalid page size or cursor")
        return self

class ExportRequest(RequestModel):
    kind: Literal["observations", "analysis"]
    format: Literal["csv", "json"]
    platforms: tuple[str, ...] | None = None
    metric: MetricName | None = None
    aggregation: Aggregation | None = None
    comparison: ComparisonRequest | None = None
    @model_validator(mode="after")
    def validate_fields(self) -> Self:
        _check_request(self)
        if self.kind == "observations":
            if self.format != "csv" or not self.platforms or any(x is not None for x in (self.metric, self.aggregation, self.comparison)):
                raise ValueError("invalid observation export")
        elif self.format != "json" or self.metric is None or self.aggregation is None:
            raise ValueError("invalid analysis export")
        return self

class Notice(ContractModel):
    code: str
    message: str

class HealthResponse(ContractModel):
    status: Literal["ok"]

class MetricDefinition(ContractModel):
    name: MetricName
    unit: str
    definition: str
    allowed_aggregations: tuple[Aggregation, ...]

class ReleaseSummary(ContractModel):
    release_id: str
    study_areas: tuple[BBox, ...]
    start_date: date
    end_date: date
    latest_source_dates: Mapping[str, date]
    available_metrics: tuple[MetricName, ...]
    allowed_platforms: tuple[str, ...]

class CoverageResult(ContractModel):
    expected_days: int
    usable_days: int | None
    numerator: float | None
    denominator: float | None
    unit: Literal["km2_visits"]
    valid_coverage_fraction: float | None

class HistoricalComparison(ContractModel):
    status: Literal["available", "insufficient_baseline"]
    median: float | None
    years_used: tuple[int, ...]
    excluded_years: Mapping[int, str]
    absolute_difference: float | None
    percentage_difference: float | None
    warnings: tuple[Notice, ...]

class UncertaintyResult(ContractModel):
    lower: float
    upper: float
    method: str

class PeriodResult(ContractModel):
    start_date: date
    end_date: date
    value: int | float | None
    partial_value: int | float | None
    original_count: int
    original_count_rule: str
    coverage: CoverageResult
    baseline: HistoricalComparison | None
    uncertainty: UncertaintyResult | None
    status: PeriodStatus
    partial_calendar_period: bool
    old_data: bool
    warnings: tuple[Notice, ...]

class AnalysisResponse(ContractModel):
    query: AnalysisRequest
    requested_bbox: BBox
    used_area: AreaGeometry | None
    release_id: str
    method_id: str | None
    reference_count_definition: str | None
    unit: str
    latest_source_date: date | None
    response_time_ms: float
    summary: PeriodResult
    calendar: tuple[PeriodResult, ...]
    warnings: tuple[Notice, ...]
class _Record:
    def __post_init__(self) -> None:
        from copy import deepcopy
        for name, value in vars(self).items():
            if isinstance(value, Mapping):
                object.__setattr__(self, name, deepcopy(value))
@dataclass(frozen=True, kw_only=True)
class SourceFileRecord(_Record):
    source_file_id: str
    source_id: str
    product: str
    version: str
    processing_mode: str
    start_date: date
    end_date: date
    downloaded_at: datetime
    sha256: str
    request_parameters: Mapping[str, JsonValue]
@dataclass(frozen=True, kw_only=True)
class ObservationRecord(_Record):
    observation_id: str
    source_file_id: str
    source_row_id: int
    pass_id: str | None
    platform: str
    instrument: str
    observed_at: datetime
    longitude: float
    latitude: float
    scan_km: float | None
    track_km: float | None
    frp_mw: float | None
    confidence: str | None
    hotspot_type: str
    quality: tuple[str, ...]
    original_fields: Mapping[str, str]
@dataclass(frozen=True, kw_only=True)
class BandRecord:
    observation_id: str
    band_name: str
    value: float | None
    unit: str
    flags: tuple[str, ...]
@dataclass(frozen=True, kw_only=True)
class OpportunityRecord(_Record):
    source_file_id: str
    pass_id: str
    platform: str
    observed_at: datetime
    footprint: AreaGeometry
    usable_footprint: AreaGeometry | None
    expected: bool | None
    quality: str
@dataclass(frozen=True, kw_only=True)
class DailyRecord(_Record):
    release_id: str
    method_id: str | None
    cell_id: str
    cell_area: AreaGeometry
    cell_center: PointGeometry
    date: date
    source_count: int
    reference_count_estimate: float | None
    coverage: CoverageResult
    uncertainty: UncertaintyResult | None
    status: PeriodStatus
@dataclass(frozen=True, kw_only=True)
class ReleaseRecord(_Record):
    summary: ReleaseSummary
    method_id: str | None
    reference_count_definition: str | None
    code_version: str
    settings: Mapping[str, JsonValue]
    source_files: tuple[SourceFileRecord, ...]
    source_selection: Mapping[str, JsonValue]
    baseline_rules: Mapping[str, JsonValue]
    report_sha256: str
    report_urls: tuple[str, ...]
@dataclass(frozen=True, kw_only=True)
class SourceBatch:
    source_file: SourceFileRecord
    observations: tuple[ObservationRecord, ...]
    bands: tuple[BandRecord, ...]
    opportunities: tuple[OpportunityRecord, ...]
@dataclass(frozen=True, kw_only=True)
class AnalysisInputs:
    observations: tuple[ObservationRecord, ...]
    daily: tuple[DailyRecord, ...]
    opportunities: tuple[OpportunityRecord, ...]
@dataclass(frozen=True, kw_only=True)
class CursorPosition:
    observed_at: datetime
    observation_id: str
@dataclass(frozen=True, kw_only=True)
class ObservationPage:
    observations: tuple[ObservationRecord, ...]
    bands: tuple[BandRecord, ...]
    next_position: CursorPosition | None
@dataclass(frozen=True, kw_only=True)
class MatchResult(_Record):
    pairs: tuple[tuple[str, str], ...]
    unmatched_observation_ids: tuple[str, ...]
    settings: Mapping[str, JsonValue]
@dataclass(frozen=True, kw_only=True)
class ValidationReport(_Record):
    release_id: str
    checks: Mapping[str, JsonValue]
    supported_metrics: tuple[MetricName, ...]
    tested_scope: Mapping[str, JsonValue]
    failures: tuple[Notice, ...]
    random_seed: int | None
    repeat_count: int | None
    memory_bytes: int
    elapsed_seconds: float

class HotspotProperties(ContractModel):
    observed_at: datetime
    platform: str
    instrument: str
    product: str
    version: str
    source_file_id: str
    source_row_id: int
    pass_id: str | None
    frp_mw: float | None
    confidence: str | None
    hotspot_type: str
    quality: tuple[str, ...]
    bands: tuple[BandRecord, ...]

class HotspotFeature(ContractModel):
    type: Literal["Feature"]
    id: str
    geometry: PointGeometry
    properties: HotspotProperties

class HotspotPage(ContractModel):
    type: Literal["FeatureCollection"]
    features: tuple[HotspotFeature, ...]
    query: HotspotQuery
    release_id: str
    next_cursor: str | None
    has_more: bool

class ReleasePublicResponse(ContractModel):
    summary: ReleaseSummary
    method_id: str | None
    reference_count_definition: str | None
    code_version: str
    settings: Mapping[str, JsonValue]
    source_files: tuple[SourceFileRecord, ...]
    source_selection: Mapping[str, JsonValue]
    baseline_rules: Mapping[str, JsonValue]
    report_sha256: str
    report_urls: tuple[str, ...]

class StorageSettings(ContractModel):
    database_path: Path
    staging_path: Path
    releases_path: Path
    saved_bytes_limit: StrictInt
    temporary_bytes_limit: StrictInt
    cell_database_path: Path | None = None
    cell_releases_path: Path | None = None
    global_release_path: Path | None = None
    world_areas_path: Path | None = None

class DownloadSettings(ContractModel):
    sources: tuple[str, ...]
    bbox: BBox
    start_date: date
    end_date: date
    window_days: StrictInt
    provider_window_seconds: StrictInt
    transaction_limit: StrictInt
    transaction_pause_at: StrictInt
    timeout_seconds: StrictFloat
    retry_limit: StrictInt

class ScienceSettings(ContractModel):
    study_areas: tuple[BBox, ...]
    source_policy: Mapping[str, JsonValue]
    type_policy: str
    confidence_policy: Mapping[str, JsonValue]
    grid: Mapping[str, JsonValue]
    reference_schedule: Mapping[str, JsonValue]
    minimum_coverage_fraction: StrictFloat
    method_id: str | None
    method_version: str | None
    random_seed: StrictInt
    repeat_count: StrictInt
    test_splits: Mapping[str, JsonValue]
    matching_time_gaps_minutes: tuple[int, ...]
    acceptance_targets: Mapping[str, JsonValue]
    rule_notes: Mapping[str, str]

class ApiSettings(ContractModel):
    selected_release_id: str | None
    allowed_origins: tuple[str, ...]
    allowed_hosts: tuple[str, ...]
    default_page_size: StrictInt
    maximum_page_size: StrictInt
    query_limits: Mapping[str, StrictInt]
    export_limits: Mapping[str, StrictInt]
    request_bytes_limit: StrictInt
    requests_per_minute: StrictInt
    stale_after_days: StrictInt
    public_report_base_url: str | None

class Settings(ContractModel):
    storage: StorageSettings
    downloads: DownloadSettings
    science: ScienceSettings
    api: ApiSettings
    @model_validator(mode="before")
    @classmethod
    def validate_raw_bounds(cls, value: object) -> object:
        if isinstance(value, dict):
            download = value.get("downloads", {})
            science = value.get("science", {})
            if isinstance(download, dict):
                _check_request_input(download)
            if isinstance(science, dict) and isinstance(science.get("study_areas", ()), (list, tuple)):
                for area in science.get("study_areas", ()):
                    validate_bbox(area)
        return value
    @model_validator(mode="after")
    def validate_fields(self) -> Self:
        download = self.downloads
        api = self.api
        if api.selected_release_id is not None and not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", api.selected_release_id):
            raise ValueError("invalid selected release ID")
        if "*" in api.allowed_origins or "*" in api.allowed_hosts:
            raise ValueError("wildcard origins or hosts are not allowed")
        if self.science.method_id is not None or self.science.method_version is not None:
            raise ValueError("science methods are not validated yet")
        validate_bbox(download.bbox)
        for area in self.science.study_areas:
            validate_bbox(area)
        if not (download.start_date < download.end_date and 1 <= download.window_days <= 5):
            raise ValueError("invalid download dates or window")
        if not (0 < download.transaction_pause_at < download.transaction_limit <= 5000 and download.provider_window_seconds >= 600):
            raise ValueError("invalid transaction limits")
        if download.timeout_seconds <= 0 or download.retry_limit < 0:
            raise ValueError("invalid download timeout or retry limit")
        if not (0 < self.storage.saved_bytes_limit <= 500 * 1024**2 and 0 < self.storage.temporary_bytes_limit <= 2 * 1024**3):
            raise ValueError("invalid storage limits")
        if not (0 <= self.science.minimum_coverage_fraction <= 1 and self.science.repeat_count > 0):
            raise ValueError("invalid science settings")
        if not (1 <= api.default_page_size <= api.maximum_page_size <= 10000):
            raise ValueError("invalid page limits")
        if min(api.request_bytes_limit, api.requests_per_minute, api.stale_after_days) <= 0:
            raise ValueError("invalid API limits")
        query_keys = {"maximum_days", "maximum_baseline_years", "maximum_input_rows", "maximum_cells", "maximum_execution_seconds"}
        export_keys = {"maximum_rows", "maximum_bytes", "maximum_execution_seconds"}
        if set(api.query_limits) != query_keys or set(api.export_limits) != export_keys:
            raise ValueError("invalid query or export limit keys")
        if any(value <= 0 for value in (*api.query_limits.values(), *api.export_limits.values())):
            raise ValueError("limits must be positive")
        return self

class ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str, *, details: Mapping[str, JsonValue] | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = dict(details or {})

class ErrorResponse(ContractModel):
    code: str
    message: str
    details: Mapping[str, JsonValue]
    request_id: str

def validate_bbox(bbox: BBox) -> BBox:
    """Check a non-wrapping longitude/latitude rectangle."""
    from math import isfinite

    if not isinstance(bbox, (tuple, list)) or len(bbox) != 4 or any(type(value) not in (int, float) or not isfinite(value) for value in bbox):
        raise ValueError("bbox must contain four finite numbers")
    west, south, east, north = bbox
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise ValueError("bbox bounds are invalid")
    return bbox

def selection_geometry(bbox: BBox) -> PolygonGeometry:
    west, south, east, north = validate_bbox(bbox)
    return {"type": "Polygon", "coordinates": (((west, south), (east, south), (east, north), (west, north), (west, south)),)}

def _check_request_input(value: object) -> object:
    if not isinstance(value, dict):
        return value
    if "page_size" in value and type(value["page_size"]) is not int:
        raise ValueError("page size must be an integer")
    bbox = value.get("bbox")
    if not isinstance(bbox, (tuple, list)):
        raise ValueError("bbox must be a list of numbers")
    validate_bbox(tuple(bbox))
    for name in ("start_date", "end_date"):
        item = value.get(name)
        if not (type(item) is date or isinstance(item, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", item)):
            raise ValueError("dates must use YYYY-MM-DD")
    return value

def _check_request(query: AnalysisRequest | HotspotQuery | ExportRequest) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", query.release_id):
        raise ValueError("invalid release ID")
    if query.start_date >= query.end_date:
        raise ValueError("start date must precede end date")
    if query.platforms is not None and (not 1 <= len(query.platforms) <= 16 or any(not 1 <= len(p) <= 64 for p in query.platforms) or len(set(query.platforms)) != len(query.platforms)):
        raise ValueError("platforms must be nonempty and unique")
    metric = getattr(query, "metric", None)
    if metric == "observed_hotspot_count" and not query.platforms:
        raise ValueError("platforms do not match metric")
    comparison = getattr(query, "comparison", None)
    if comparison is not None:
        from datetime import timedelta
        if comparison.baseline_end_year >= query.start_date.year or (query.end_date - timedelta(days=1)).year != query.start_date.year:
            raise ValueError("invalid comparison window")

def load_settings(path: Path) -> Settings:
    """Load a small operator-owned JSON file and resolve project paths."""
    import json

    with path.open("rb") as source:
        content = source.read(65537)
    if len(content) > 65536:
        raise ValueError("settings file is too large")
    data = json.loads(content)
    project = Path(__file__).resolve().parents[1]
    for name in ("database_path", "staging_path", "releases_path", "cell_database_path", "cell_releases_path", "global_release_path", "world_areas_path"):
        if data["storage"].get(name) is None:
            continue
        location = Path(data["storage"][name])
        data["storage"][name] = str((project / location).resolve())
    return Settings.model_validate(data)
