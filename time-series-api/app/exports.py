"""Bounded legacy export formatting for prepared releases."""

import csv
import io
import json
import time
from collections.abc import Iterable, Mapping

from app import analysis, storage
from app.models import (
    AnalysisRequest, ApiError, ApiSettings, BandRecord, ExportRequest, HotspotQuery,
    ObservationRecord, ReleaseRecord, Settings,
)

def build_export(query: ExportRequest, *, settings: Settings) -> tuple[bytes, str, str]:
    release = storage.load_release(settings.storage.database_path, query.release_id)
    api_settings = settings.api
    limits = api_settings.export_limits
    started = time.perf_counter()
    if query.kind == "analysis":
        return _build_analysis_export(query, release, settings, api_settings, limits, started)
    return _build_observation_export(query, release, settings, api_settings, limits, started)


def _check_export_time(started: float, maximum_seconds: float) -> None:
    if time.perf_counter() - started > maximum_seconds:
        raise ApiError(413, "EXPORT_TIME_LIMIT", "The export exceeds the time limit.")


def _append_export_bytes(body: bytearray, encoded: bytes, maximum_bytes: int) -> None:
    if len(body) + len(encoded) > maximum_bytes:
        raise ApiError(413, "EXPORT_BYTE_LIMIT", "The export exceeds the byte limit.")
    body.extend(encoded)


def _append_export_row(
    body: bytearray, values: Iterable[object], started: float,
    limits: Mapping[str, int | float],
) -> None:
    _check_export_time(started, limits["maximum_execution_seconds"])
    buffer = io.StringIO(newline="")
    csv.writer(buffer, lineterminator="\r\n").writerow(values)
    _append_export_bytes(body, buffer.getvalue().encode("utf-8"), limits["maximum_bytes"])


def _build_analysis_export(
    query: ExportRequest, release: ReleaseRecord, settings: Settings,
    api_settings: ApiSettings, limits: Mapping[str, int | float], started: float,
) -> tuple[bytes, str, str]:
    body = bytearray()
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
    chunks = json.JSONEncoder(ensure_ascii=False, separators=(",", ":")).iterencode(
        result.model_dump(mode="json")
    )
    for chunk in chunks:
        _check_export_time(started, limits["maximum_execution_seconds"])
        _append_export_bytes(body, chunk.encode("utf-8"), limits["maximum_bytes"])
    return bytes(body), "application/json", "time-series-analysis.json"


def _export_band_map(bands: tuple[BandRecord, ...]) -> dict[str, list[dict[str, object]]]:
    result: dict[str, list[dict[str, object]]] = {}
    for band in bands:
        result.setdefault(band.observation_id, []).append({
            "band_name": band.band_name, "value": band.value,
            "unit": band.unit, "flags": band.flags,
        })
    return result


def _observation_export_values(
    row: ObservationRecord, bands: dict[str, list[dict[str, object]]],
) -> tuple[object, ...]:
    return (
        row.observation_id, row.observed_at.isoformat(), row.longitude, row.latitude,
        row.platform, row.instrument, row.source_file_id, row.source_row_id,
        row.pass_id, row.frp_mw, row.confidence, row.hotspot_type,
        json.dumps(row.quality, separators=(",", ":")),
        json.dumps(bands.get(row.observation_id, []), sort_keys=True, separators=(",", ":")),
        json.dumps(row.original_fields, sort_keys=True, separators=(",", ":")),
    )


def _build_observation_export(
    query: ExportRequest, release: ReleaseRecord, settings: Settings,
    api_settings: ApiSettings, limits: Mapping[str, int | float], started: float,
) -> tuple[bytes, str, str]:
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
    body = bytearray()
    _append_export_row(body, headers, started, limits)
    row_count = 0
    position = None
    while True:
        _check_export_time(started, limits["maximum_execution_seconds"])
        page = storage.read_observations(settings.storage.database_path, point_query, position)
        bands = _export_band_map(page.bands)
        for row in page.observations:
            row_count += 1
            if row_count > limits["maximum_rows"]:
                raise ApiError(413, "EXPORT_ROW_LIMIT", "The export exceeds the row limit.")
            values = _observation_export_values(row, bands)
            _append_export_row(body, (_safe_csv_cell(value) for value in values), started, limits)
        if page.next_position is None:
            break
        position = page.next_position
    _check_export_time(started, limits["maximum_execution_seconds"])
    return bytes(body), "text/csv; charset=utf-8", "time-series-observations.csv"


def _safe_csv_cell(value: object) -> object:
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value
