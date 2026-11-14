"""HTTP app for fixed time-series releases."""

import base64
import csv
from collections import deque
from datetime import datetime
import hashlib
import hmac
import io
import json
import os
import secrets
import time
from pathlib import Path
from shapely.geometry import shape

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

from app import analysis, storage
from app.cells import CellMapQuery, CellMapResponse, make_cell_map
from app.models import (
    AnalysisRequest, AnalysisResponse, ApiError, ApiSettings, ExportRequest,
    CursorPosition, ErrorResponse, HealthResponse,
    HotspotFeature, HotspotPage, HotspotProperties, HotspotQuery, MetricDefinition,
    ObservationPage, PointGeometry, ReleasePublicResponse,
    ReleaseSummary, Settings, load_settings, selection_geometry,
)

_POST_PATHS = {"/v1/analysis", "/v1/hotspots/query", "/v1/hotspots/cells/query", "/v1/exports"}
_METRICS = (
    MetricDefinition(name="observed_hotspot_count", unit="detections",
        definition="Count selected source detections.", allowed_aggregations=("day", "month")),
    MetricDefinition(name="harmonized_hotspot_count", unit="estimated detections",
        definition="Estimate reference detections using the checked release method.", allowed_aggregations=("day", "month")),
    MetricDefinition(name="active_cell_count", unit="cells",
        definition="Count selected cells with detections.", allowed_aggregations=("day", "month")),
    MetricDefinition(name="frp_pass_sum_mw", unit="MW",
        definition="Sum fire radiative power for one satellite pass.", allowed_aggregations=()),
    MetricDefinition(name="valid_coverage_fraction", unit="fraction",
        definition="Usable area-visits divided by expected area-visits.", allowed_aggregations=("day", "month")),
)


def create_app(settings_path: Path | None = None) -> FastAPI:
    """Load trusted settings and prepare one read-only app instance."""
    path = settings_path or Path(__file__).resolve().parents[1] / "config/settings.json"
    settings = load_settings(path)
    if settings.api.selected_release_id is None:
        raise ValueError("selected release is required for serving")
    secret = os.environ.get("CURSOR_SECRET", "").encode("utf-8")
    if len(secret) < 32:
        raise ValueError("CURSOR_SECRET must contain at least 32 bytes")
    app = FastAPI(title="Time-series API", version="1.0.0")
    app.state.settings = settings
    app.state.cursor_secret = secret
    app.add_exception_handler(ApiError, handle_api_error)
    app.add_exception_handler(RequestValidationError, handle_validation_error)
    app.add_exception_handler(Exception, handle_server_error)
    app.add_api_route("/health/live", health_live, methods=["GET"], response_model=HealthResponse, operation_id="health_live")
    app.add_api_route("/health/ready", health_ready, methods=["GET"], response_model=HealthResponse, operation_id="health_ready")
    app.add_api_route("/v1/releases", list_releases, methods=["GET"], response_model=tuple[ReleaseSummary, ...], operation_id="list_releases")
    app.add_api_route("/v1/releases/{release_id}", get_release, methods=["GET"], response_model=ReleasePublicResponse, operation_id="get_release")
    app.add_api_route("/v1/metrics", list_metrics, methods=["GET"], response_model=tuple[MetricDefinition, ...], operation_id="list_metrics")
    app.add_api_route("/v1/analysis", analyze, methods=["POST"], response_model=AnalysisResponse, operation_id="analyze")
    app.add_api_route("/v1/hotspots/query", query_hotspots, methods=["POST"], response_model=HotspotPage, operation_id="query_hotspots")
    app.add_api_route("/v1/hotspots/cells/query", query_hotspot_cells, methods=["POST"],
                      response_model=CellMapResponse, operation_id="query_hotspot_cells")
    app.add_api_route(
        "/v1/exports", export_results, methods=["POST"], response_class=Response,
        response_model=None, operation_id="export_results",
        responses={200: {
            "description": "Analysis JSON or observation CSV.",
            "content": {
                "application/json": {"schema": {"$ref": "#/components/schemas/AnalysisResponse"}},
                "text/csv": {"schema": {"type": "string"}},
            },
        }},
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(settings.api.allowed_hosts))
    app.add_middleware(RequestGuard, settings=settings.api)
    app.add_middleware(
        CORSMiddleware, allow_origins=list(settings.api.allowed_origins),
        allow_methods=["GET", "POST", "OPTIONS"], allow_headers=["Content-Type"],
        expose_headers=["Content-Disposition", "X-Request-ID", "Retry-After"],
    )
    return app


def health_live() -> HealthResponse:
    return HealthResponse(status="ok")


def health_ready(request: Request) -> HealthResponse:
    settings: Settings = request.app.state.settings
    try:
        storage.load_release(settings.storage.database_path, settings.api.selected_release_id)
    except Exception as error:
        raise ApiError(503, "NOT_READY", "The selected release is not ready.") from error
    return HealthResponse(status="ok")


def list_releases(request: Request) -> tuple[ReleaseSummary, ...]:
    settings: Settings = request.app.state.settings
    return storage.list_releases(settings.storage.database_path)


def get_release(release_id: str, request: Request) -> ReleasePublicResponse:
    settings: Settings = request.app.state.settings
    _reject_processed_release(release_id, settings)
    release = storage.load_release(settings.storage.database_path, release_id)
    return ReleasePublicResponse.model_validate(release.__dict__)


def list_metrics() -> tuple[MetricDefinition, ...]:
    return _METRICS


def analyze(query: AnalysisRequest, request: Request) -> AnalysisResponse:
    started = time.perf_counter()
    settings: Settings = request.app.state.settings
    _reject_processed_release(query.release_id, settings)
    release = storage.load_release(settings.storage.database_path, query.release_id)
    analysis.validate_query_domain(query, release, settings=settings.api)
    inputs = storage.read_daily(settings.storage.database_path, query, settings=settings.api)
    result = analysis.build_analysis(query, inputs, release)
    elapsed = (time.perf_counter() - started) * 1000
    return result.model_copy(update={"response_time_ms": round(elapsed, 3)})


def encode_cursor(position: CursorPosition, query: HotspotQuery, *, secret: bytes) -> str:
    payload = {
        "v": 1, "query": _query_digest(query), "release_id": query.release_id,
        "observed_at": position.observed_at.isoformat(), "observation_id": position.observation_id,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    signature = hmac.new(secret, raw, hashlib.sha256).digest()
    return f"{_b64_encode(raw)}.{_b64_encode(signature)}"


def decode_cursor(token: str, query: HotspotQuery, *, secret: bytes) -> CursorPosition:
    try:
        if not token or len(token) > 2048 or token.count(".") != 1:
            raise ValueError
        encoded, signature_text = token.split(".")
        raw = _b64_decode(encoded)
        signature = _b64_decode(signature_text)
        expected = hmac.new(secret, raw, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError
        payload = json.loads(raw)
        if set(payload) != {"v", "query", "release_id", "observed_at", "observation_id"}:
            raise ValueError
        if payload["v"] != 1 or payload["query"] != _query_digest(query) or payload["release_id"] != query.release_id:
            raise ValueError
        if not isinstance(payload["observation_id"], str) or not payload["observation_id"]:
            raise ValueError
        observed_at = datetime.fromisoformat(payload["observed_at"])
        if observed_at.tzinfo is None or observed_at.utcoffset().total_seconds() != 0:
            raise ValueError
        return CursorPosition(observed_at=observed_at, observation_id=payload["observation_id"])
    except (ValueError, TypeError, KeyError, AttributeError, json.JSONDecodeError):
        raise ApiError(422, "INVALID_CURSOR", "The cursor is invalid for this query.") from None


def to_geojson(page: ObservationPage, query: HotspotQuery, *, secret: bytes) -> HotspotPage:
    bands = {}
    for band in page.bands:
        bands.setdefault(band.observation_id, []).append(band)
    features = []
    for row in page.observations:
        point: PointGeometry = {"type": "Point", "coordinates": (row.longitude, row.latitude)}
        properties = HotspotProperties(
            observed_at=row.observed_at, platform=row.platform, instrument=row.instrument,
            product=row.instrument, version=row.original_fields.get("version", "unknown"),
            source_file_id=row.source_file_id, source_row_id=row.source_row_id,
            pass_id=row.pass_id, frp_mw=row.frp_mw, confidence=row.confidence,
            hotspot_type=row.hotspot_type, quality=row.quality,
            bands=tuple(bands.get(row.observation_id, ())),
        )
        features.append(HotspotFeature(type="Feature", id=row.observation_id, geometry=point, properties=properties))
    has_more = page.next_position is not None
    return HotspotPage(
        type="FeatureCollection", features=tuple(features), query=query,
        release_id=query.release_id,
        next_cursor=encode_cursor(page.next_position, query, secret=secret) if has_more else None,
        has_more=has_more,
    )


def query_hotspots(query: HotspotQuery, request: Request) -> HotspotPage:
    settings: Settings = request.app.state.settings
    _reject_processed_release(query.release_id, settings)
    if query.page_size > settings.api.maximum_page_size:
        raise ApiError(422, "PAGE_SIZE_LIMIT", "The requested page is too large.")
    release = storage.load_release(settings.storage.database_path, query.release_id)
    analysis.validate_query_domain(query, release, settings=settings.api)
    position = decode_cursor(query.cursor, query, secret=request.app.state.cursor_secret) if query.cursor else None
    page = storage.read_observations(settings.storage.database_path, query, position)
    return to_geojson(page, query, secret=request.app.state.cursor_secret)


def _reject_processed_release(release_id: str, settings: Settings) -> None:
    root = settings.storage.cell_releases_path
    if root is not None and (root / release_id).exists():
        raise ApiError(409, "UNSUPPORTED_DATASET", "This release contains processed cell summaries only.")


def query_hotspot_cells(query: CellMapQuery, request: Request) -> CellMapResponse:
    """Read one stored summary and its saved cell shapes; never read source CSVs."""
    settings: Settings = request.app.state.settings
    database = settings.storage.cell_database_path
    releases = settings.storage.cell_releases_path
    if database is None or releases is None:
        raise ApiError(503, "CELL_DATA_UNAVAILABLE", "Processed cell data are not configured.")
    manifest = storage.read_cell_manifest(releases, query.release_id)
    if query.area_id is not None:
        area_id = query.area_id
    else:
        requested = shape(selection_geometry(query.bbox))
        areas = [(area_id, record) for area_id, record in manifest.areas.items()
                 if shape(record["geometry"]).covers(requested)]
        if not areas:
            raise ApiError(422, "AREA_NOT_PREPARED", "The bbox is not inside a prepared area.")
        if len(areas) > 1:
            raise ApiError(422, "AREA_AMBIGUOUS", "The bbox matches more than one prepared area.")
        area_id = areas[0][0]
    if area_id not in manifest.areas:
        raise ApiError(422, "AREA_NOT_PREPARED", "The area is not in this release.")
    area_geometry = manifest.areas[area_id]["geometry"]
    summary = storage.read_hotspot_summary(database, query.release_id, area_id, query.date)
    cells = storage.read_hotspot_cells(database, manifest.grid_version,
        summary.hotspot_cell_ids) if summary.hotspot_cell_ids else ()
    try:
        return make_cell_map(query, summary, cells, grid_version=manifest.grid_version,
                             selection=area_geometry)
    except ValueError as error:
        if "10,000" in str(error):
            raise ApiError(413, "CELL_LIMIT", "The map selection has too many cells.") from None
        raise ApiError(503, "CELL_DATA_INVALID", "The processed cell data are invalid.") from None


def export_results(query: ExportRequest, request: Request) -> Response:
    _reject_processed_release(query.release_id, request.app.state.settings)
    body, media_type, filename = build_export(query, settings=request.app.state.settings)
    return Response(body, media_type=media_type, headers={
        "Content-Disposition": f'attachment; filename="{filename}"',
    })


def build_export(query: ExportRequest, *, settings: Settings) -> tuple[bytes, str, str]:
    release = storage.load_release(settings.storage.database_path, query.release_id)
    api_settings = settings.api
    limits = api_settings.export_limits
    started = time.perf_counter()
    maximum_seconds = limits["maximum_execution_seconds"]
    maximum_bytes = limits["maximum_bytes"]
    body = bytearray()

    def check_time() -> None:
        if time.perf_counter() - started > maximum_seconds:
            raise ApiError(413, "EXPORT_TIME_LIMIT", "The export exceeds the time limit.")

    def add_row(writer_values) -> None:
        check_time()
        buffer = io.StringIO(newline="")
        csv.writer(buffer, lineterminator="\r\n").writerow(writer_values)
        encoded = buffer.getvalue().encode("utf-8")
        if len(body) + len(encoded) > maximum_bytes:
            raise ApiError(413, "EXPORT_BYTE_LIMIT", "The export exceeds the byte limit.")
        body.extend(encoded)

    if query.kind == "analysis":
        analysis_query = AnalysisRequest.model_validate({
            key: value for key, value in query.model_dump(mode="json").items()
            if key not in {"kind", "format"}
        })
        analysis.validate_query_domain(analysis_query, release, settings=api_settings)
        inputs = storage.read_daily(settings.storage.database_path, analysis_query, settings=api_settings)
        result = analysis.build_analysis(analysis_query, inputs, release)
        result = result.model_copy(update={
            "response_time_ms": round((time.perf_counter() - started) * 1000, 3),
        })
        for chunk in json.JSONEncoder(ensure_ascii=False, separators=(",", ":")).iterencode(
            result.model_dump(mode="json")
        ):
            check_time()
            encoded = chunk.encode("utf-8")
            if len(body) + len(encoded) > maximum_bytes:
                raise ApiError(413, "EXPORT_BYTE_LIMIT", "The export exceeds the byte limit.")
            body.extend(encoded)
        return bytes(body), "application/json", "time-series-analysis.json"

    analysis.validate_query_domain(query, release, settings=api_settings)
    page_size = min(api_settings.default_page_size, api_settings.maximum_page_size)
    point_query = HotspotQuery(
        release_id=query.release_id, bbox=query.bbox, start_date=query.start_date,
        end_date=query.end_date, platforms=query.platforms, page_size=page_size,
    )
    headers = (
        "observation_id", "observed_at", "longitude", "latitude", "platform",
        "instrument", "source_file_id", "source_row_id", "pass_id", "frp_mw",
        "confidence", "hotspot_type", "quality", "bands", "original_fields",
    )
    add_row(headers)
    row_count = 0
    position = None
    while True:
        check_time()
        page = storage.read_observations(settings.storage.database_path, point_query, position)
        bands: dict[str, list[dict]] = {}
        for band in page.bands:
            bands.setdefault(band.observation_id, []).append({
                "band_name": band.band_name, "value": band.value,
                "unit": band.unit, "flags": band.flags,
            })
        for row in page.observations:
            row_count += 1
            if row_count > limits["maximum_rows"]:
                raise ApiError(413, "EXPORT_ROW_LIMIT", "The export exceeds the row limit.")
            values = (
                row.observation_id, row.observed_at.isoformat(), row.longitude, row.latitude,
                row.platform, row.instrument, row.source_file_id, row.source_row_id,
                row.pass_id, row.frp_mw, row.confidence, row.hotspot_type,
                json.dumps(row.quality, separators=(",", ":")),
                json.dumps(bands.get(row.observation_id, []), sort_keys=True, separators=(",", ":")),
                json.dumps(row.original_fields, sort_keys=True, separators=(",", ":")),
            )
            add_row(_safe_csv_cell(value) for value in values)
        if page.next_position is None:
            break
        position = page.next_position
    check_time()
    return bytes(body), "text/csv; charset=utf-8", "time-series-observations.csv"


def _safe_csv_cell(value):
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def handle_api_error(request: Request, error: ApiError) -> JSONResponse:
    return _error(request, error.status_code, error.code, error.message, error.details)


def handle_validation_error(request: Request, error: RequestValidationError) -> JSONResponse:
    fields = [{"field": ".".join(str(part) for part in item.get("loc", ())), "type": item.get("type", "invalid")}
              for item in error.errors()[:20]]
    return _error(request, 422, "INVALID_REQUEST", "The request fields are invalid.", {"fields": fields})


def handle_server_error(request: Request, error: Exception) -> JSONResponse:
    return _error(request, 500, "INTERNAL_ERROR", "The request could not be completed.", {})


class RequestGuard:
    """Bound request rate and POST body size for one app process."""

    def __init__(self, app: ASGIApp, *, settings: ApiSettings) -> None:
        self.app = app
        self.settings = settings
        self.requests: deque[float] = deque(maxlen=settings.requests_per_minute)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = secrets.token_hex(16)
        scope.setdefault("state", {})["request_id"] = request_id

        async def send_with_id(message):
            if message["type"] == "http.response.start":
                headers = [(key, value) for key, value in message.get("headers", [])
                           if key.lower() != b"x-request-id"]
                headers.append((b"x-request-id", request_id.encode("ascii")))
                message = {**message, "headers": headers}
            await send(message)

        retry_after = self._take_rate_slot()
        if retry_after is not None:
            await _send_guard_error(send_with_id, request_id, 429, "RATE_LIMITED",
                                    "Too many requests.", [(b"retry-after", str(retry_after).encode())])
            return
        if scope.get("method") == "POST" and scope.get("path") in _POST_PATHS:
            problem = _body_problem(scope, self.settings.request_bytes_limit)
            if problem is not None:
                status, code, message = problem
                await _send_guard_error(send_with_id, request_id, status, code, message)
                return
            limited_receive = _limited_receive(receive, self.settings.request_bytes_limit)
            try:
                await self.app(scope, limited_receive, send_with_id)
            except _BodyTooLarge:
                await _send_guard_error(send_with_id, request_id, 413, "BODY_TOO_LARGE", "The request body is too large.")
            return
        await self.app(scope, receive, send_with_id)

    def _take_rate_slot(self) -> int | None:
        now = time.monotonic()
        while self.requests and now - self.requests[0] >= 60:
            self.requests.popleft()
        if len(self.requests) >= self.settings.requests_per_minute:
            return max(1, int(60 - (now - self.requests[0]) + 0.999))
        self.requests.append(now)
        return None


def _limited_receive(receive: Receive, limit: int):
    seen = 0

    async def checked():
        nonlocal seen
        message = await receive()
        if message["type"] == "http.request":
            seen += len(message.get("body", b""))
            if seen > limit:
                raise _BodyTooLarge
        return message

    return checked


def _body_problem(scope: Scope, limit: int):
    headers = {key.lower(): value for key, value in scope.get("headers", [])}
    content_type = headers.get(b"content-type", b"").split(b";", 1)[0].strip().lower()
    if content_type != b"application/json":
        return 415, "UNSUPPORTED_MEDIA_TYPE", "POST requests require JSON."
    encoding = headers.get(b"content-encoding", b"identity").lower()
    if encoding not in (b"", b"identity"):
        return 415, "UNSUPPORTED_CONTENT_ENCODING", "Compressed requests are not supported."
    if b"content-length" in headers:
        try:
            size = int(headers[b"content-length"])
        except ValueError:
            return 400, "INVALID_CONTENT_LENGTH", "Content-Length is invalid."
        if size < 0:
            return 400, "INVALID_CONTENT_LENGTH", "Content-Length is invalid."
        if size > limit:
            return 413, "BODY_TOO_LARGE", "The request body is too large."
    return None


def _error(request: Request, status: int, code: str, message: str, details) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "")
    body = ErrorResponse(code=code, message=message, details=details, request_id=request_id)
    return JSONResponse(status_code=status, content=body.model_dump(mode="json"), headers={"X-Request-ID": request_id})


async def _send_guard_error(send, request_id, status, code, message, extra_headers=()):
    body = ErrorResponse(code=code, message=message, details={}, request_id=request_id)
    content = json.dumps(body.model_dump(mode="json"), separators=(",", ":")).encode("utf-8")
    headers = [(b"content-type", b"application/json"), *extra_headers]
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": content})


def _query_digest(query: HotspotQuery) -> str:
    data = query.model_dump(mode="json", exclude={"cursor"})
    data["platforms"] = sorted(data["platforms"])
    raw = json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _b64_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64_decode(value: str) -> bytes:
    if not value or any(char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" for char in value):
        raise ValueError("bad base64")
    return base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)


class _BodyTooLarge(Exception):
    pass
