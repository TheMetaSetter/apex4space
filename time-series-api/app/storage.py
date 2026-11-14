"""SQLite storage for fixed releases.

Offline preparation writes releases. The API opens an existing database
read-only, so a request cannot create or change data.
"""

import hashlib
import json
import math
import re
import sqlite3
import time
from collections.abc import Iterator
from contextlib import closing
from datetime import date, datetime, time as day_time, timezone
from pathlib import Path

from pydantic import TypeAdapter

from app.models import (
    AnalysisInputs, AnalysisRequest, ApiError, ApiSettings, BandRecord, CursorPosition,
    DailyRecord, HotspotQuery, ObservationPage, ObservationRecord, OpportunityRecord,
    ReleaseRecord, ReleaseSummary, SourceBatch, SourceFileRecord, StorageSettings, ValidationReport,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS source_file (
    source_file_id TEXT PRIMARY KEY, payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS observation (
    observation_id TEXT PRIMARY KEY,
    source_file_id TEXT NOT NULL REFERENCES source_file(source_file_id),
    source_row_id INTEGER NOT NULL CHECK (source_row_id >= 1),
    observed_at TEXT NOT NULL, platform TEXT NOT NULL,
    longitude REAL NOT NULL CHECK (longitude BETWEEN -180 AND 180),
    latitude REAL NOT NULL CHECK (latitude BETWEEN -90 AND 90),
    frp_mw REAL CHECK (frp_mw IS NULL OR (frp_mw >= 0 AND frp_mw < 1e308)),
    payload TEXT NOT NULL, UNIQUE (source_file_id, source_row_id)
);
CREATE TABLE IF NOT EXISTS band_measurement (
    observation_id TEXT NOT NULL REFERENCES observation(observation_id),
    band_name TEXT NOT NULL, payload TEXT NOT NULL,
    PRIMARY KEY (observation_id, band_name)
);
CREATE TABLE IF NOT EXISTS opportunity (
    source_file_id TEXT NOT NULL REFERENCES source_file(source_file_id),
    pass_id TEXT NOT NULL, payload TEXT NOT NULL,
    PRIMARY KEY (source_file_id, pass_id)
);
CREATE TABLE IF NOT EXISTS release (
    release_id TEXT PRIMARY KEY, manifest TEXT NOT NULL,
    manifest_sha256 TEXT NOT NULL, report_sha256 TEXT NOT NULL,
    release_dir TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS analysis_daily (
    release_id TEXT NOT NULL REFERENCES release(release_id),
    cell_id TEXT NOT NULL, date TEXT NOT NULL,
    source_count INTEGER NOT NULL CHECK (source_count >= 0),
    reference_count_estimate REAL CHECK (reference_count_estimate IS NULL OR
        (reference_count_estimate >= 0 AND reference_count_estimate < 1e308)),
    payload TEXT NOT NULL, PRIMARY KEY (release_id, cell_id, date)
);
"""


def initialize_database(path: Path) -> None:
    """Create the six tables for an offline data preparation job."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path, timeout=5)) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.executescript(SCHEMA)


def _read_connection(path: Path, seconds: float = 5) -> sqlite3.Connection:
    """Open an existing database and stop a query that takes too long."""
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
    deadline = time.monotonic() + seconds
    connection.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
    return connection


def _decode_manifest(data: str) -> ReleaseRecord:
    return TypeAdapter(ReleaseRecord).validate_json(data)


def list_releases(path: Path) -> tuple[ReleaseSummary, ...]:
    with closing(_read_connection(path)) as connection:
        rows = connection.execute("SELECT manifest FROM release ORDER BY release_id").fetchall()
    return tuple(_decode_manifest(row[0]).summary for row in rows)


def load_release(path: Path, release_id: str) -> ReleaseRecord:
    with closing(_read_connection(path)) as connection:
        row = connection.execute(
            "SELECT manifest, manifest_sha256, report_sha256, release_dir FROM release WHERE release_id = ?",
            (release_id,),
        ).fetchone()
    if row is None:
        raise ApiError(404, "RELEASE_NOT_FOUND", "Release not found")
    stored, manifest_hash, report_hash, directory = row
    manifest_bytes = (Path(directory) / "manifest.json").read_bytes()
    report_bytes = (Path(directory) / "validation.json").read_bytes()
    if (hashlib.sha256(manifest_bytes).hexdigest() != manifest_hash or
            hashlib.sha256(report_bytes).hexdigest() != report_hash or
            manifest_bytes.decode("utf-8") != stored):
        raise ValueError("release files do not match the database")
    manifest = _decode_manifest(stored)
    if manifest.summary.release_id != release_id or manifest.report_sha256 != report_hash:
        raise ValueError("release identity does not match")
    return manifest


def _utc_text(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
        raise ValueError("timestamp must be UTC")
    return value.isoformat(timespec="microseconds")


def read_observations(path: Path, query: HotspotQuery, position: CursorPosition | None) -> ObservationPage:
    load_release(path, query.release_id)
    west, south, east, north = query.bbox
    start = _utc_text(datetime.combine(query.start_date, day_time.min, timezone.utc))
    end = _utc_text(datetime.combine(query.end_date, day_time.min, timezone.utc))
    placeholders = ",".join("?" for _ in query.platforms)
    position_time = _utc_text(position.observed_at) if position else ""
    position_id = position.observation_id if position else ""
    sql = f"""
        SELECT o.payload FROM observation AS o JOIN release AS r ON r.release_id = ?
        WHERE o.observed_at >= ? AND o.observed_at < ?
          AND o.longitude BETWEEN ? AND ? AND o.latitude BETWEEN ? AND ?
          AND o.platform IN ({placeholders})
          AND (o.observed_at, o.observation_id) > (?, ?)
          AND EXISTS (SELECT 1 FROM json_each(r.manifest, '$.source_selection.rows') AS source
                      JOIN json_each(source.value) AS selected
                      WHERE source.key = o.source_file_id AND selected.value = o.source_row_id)
        ORDER BY o.observed_at, o.observation_id LIMIT ?
    """
    parameters = (query.release_id, start, end, west, east, south, north,
                  *query.platforms, position_time, position_id, query.page_size + 1)
    with closing(_read_connection(path)) as connection:
        rows = connection.execute(sql, parameters).fetchall()
        observations = tuple(TypeAdapter(ObservationRecord).validate_json(row[0]) for row in rows[:query.page_size])
        bands = _read_bands(connection, observations)
    last = observations[-1] if len(rows) > query.page_size else None
    next_position = CursorPosition(observed_at=last.observed_at, observation_id=last.observation_id) if last else None
    return ObservationPage(observations=observations, bands=bands, next_position=next_position)


def _read_bands(connection: sqlite3.Connection, observations: tuple[ObservationRecord, ...]) -> tuple[BandRecord, ...]:
    result: list[BandRecord] = []
    for observation in observations:
        rows = connection.execute("SELECT payload FROM band_measurement WHERE observation_id = ? ORDER BY band_name", (observation.observation_id,))
        result.extend(TypeAdapter(BandRecord).validate_json(row[0]) for row in rows)
    return tuple(result)


def _analysis_windows(query: AnalysisRequest) -> list[tuple[date, date]]:
    windows = [(query.start_date, query.end_date)]
    if query.comparison is not None:
        for year in range(query.comparison.baseline_start_year, query.comparison.baseline_end_year + 1):
            end_year = year + (query.end_date.year - query.start_date.year)
            start = _date_in_year(query.start_date, year)
            end = _date_in_year(query.end_date, end_year)
            if start < end:
                windows.append((start, end))
    return windows


def _date_in_year(value: date, year: int) -> date:
    try:
        return value.replace(year=year)
    except ValueError:
        return date(year, 3, 1)


def read_daily(path: Path, query: AnalysisRequest, *, settings: ApiSettings) -> AnalysisInputs:
    release = load_release(path, query.release_id)
    limits = settings.query_limits
    comparison = query.comparison
    baseline_years = 0 if comparison is None else comparison.baseline_end_year - comparison.baseline_start_year + 1
    if baseline_years > limits["maximum_baseline_years"] or (query.end_date - query.start_date).days > limits["maximum_days"]:
        raise ApiError(413, "QUERY_TOO_LARGE", "Query exceeds the configured limit")
    windows = _analysis_windows(query)
    deadline = time.monotonic() + limits["maximum_execution_seconds"]
    observations: list[ObservationRecord] = []
    daily: list[DailyRecord] = []
    opportunities: list[OpportunityRecord] = []
    for start, end in windows:
        point_query = HotspotQuery(release_id=query.release_id, bbox=query.bbox, start_date=start, end_date=end,
                                   platforms=query.platforms or release.summary.allowed_platforms, page_size=1000)
        position = None
        while True:
            if time.monotonic() > deadline:
                raise ApiError(413, "QUERY_TOO_LARGE", "Query took too long")
            page = read_observations(path, point_query, position)
            observations.extend(page.observations)
            if len(observations) > limits["maximum_input_rows"]:
                raise ApiError(413, "QUERY_TOO_LARGE", "Too many input rows")
            position = page.next_position
            if position is None:
                break
        _append_analysis_rows(path, release, start.isoformat(), end.isoformat(), daily, opportunities, limits, deadline)
        if len(observations) + len(daily) + len(opportunities) > limits["maximum_input_rows"]:
            raise ApiError(413, "QUERY_TOO_LARGE", "Too many input rows")
    return AnalysisInputs(observations=tuple(observations), daily=tuple(daily), opportunities=tuple(opportunities))


def _append_analysis_rows(path, release, start, end, daily, opportunities, limits, deadline) -> None:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ApiError(413, "QUERY_TOO_LARGE", "Query took too long")
    with closing(_read_connection(path, remaining)) as connection:
        rows = connection.execute(
            "SELECT payload FROM analysis_daily WHERE release_id = ? AND date >= ? AND date < ? LIMIT ?",
            (release.summary.release_id, start, end, limits["maximum_input_rows"] + 1),
        )
        daily.extend(TypeAdapter(DailyRecord).validate_json(row[0]) for row in rows)
        if len({record.cell_id for record in daily}) > limits["maximum_cells"]:
            raise ApiError(413, "QUERY_TOO_LARGE", "Too many cells")
        for source in release.source_files:
            rows = connection.execute(
                "SELECT payload FROM opportunity WHERE source_file_id = ? AND substr(json_extract(payload, '$.observed_at'), 1, 10) >= ? AND substr(json_extract(payload, '$.observed_at'), 1, 10) < ? LIMIT ?",
                (source.source_file_id, start, end, limits["maximum_input_rows"] + 1),
            )
            opportunities.extend(TypeAdapter(OpportunityRecord).validate_json(row[0]) for row in rows)
            if len(opportunities) > limits["maximum_input_rows"]:
                raise ApiError(413, "QUERY_TOO_LARGE", "Too many input rows")


def _json_bytes(record: object) -> bytes:
    value = TypeAdapter(type(record)).dump_python(record, mode="json")
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _check_manifest(manifest: ReleaseRecord, report: ValidationReport) -> None:
    summary = manifest.summary
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", summary.release_id) or report.release_id != summary.release_id:
        raise ValueError("invalid or mismatched release ID")
    source_hashes = {source.source_file_id: source.sha256 for source in manifest.source_files}
    if len(source_hashes) != len(manifest.source_files) or any(not re.fullmatch(r"[0-9a-f]{64}", digest) for digest in source_hashes.values()):
        raise ValueError("invalid source IDs or hashes")
    expected = {"source_hashes": source_hashes, "code_version": manifest.code_version,
                "method_id": manifest.method_id, "settings": manifest.settings}
    if report.checks.get("provenance") != expected or manifest.settings.get("tested_scope") != report.tested_scope:
        raise ValueError("report provenance does not match manifest")
    if manifest.settings.get("schema_version") != 1 or not set(summary.available_metrics).issubset(report.supported_metrics):
        raise ValueError("invalid schema version or unsupported metric")
    if manifest.method_id is not None:
        raise ValueError("no science method is validated yet")
    if manifest.method_id is None and "harmonized_hotspot_count" in summary.available_metrics:
        raise ValueError("source-only releases cannot publish harmonized counts")
    if hashlib.sha256(_json_bytes(report)).hexdigest() != manifest.report_sha256:
        raise ValueError("report hash does not match manifest")
    rows = manifest.source_selection.get("rows")
    if not isinstance(rows, dict) or set(rows) != set(source_hashes):
        raise ValueError("source selection must name every source file")
    for row_ids in rows.values():
        if not isinstance(row_ids, list) or any(type(row) is not int or row < 1 for row in row_ids) or len(set(row_ids)) != len(row_ids):
            raise ValueError("invalid selected source rows")


def _insert_checked(connection: sqlite3.Connection, statement: str, parameters: tuple,
                    lookup: str, key: tuple, expected: str, frozen: bool = False) -> None:
    if frozen and connection.execute(lookup, key).fetchone() is None:
        raise ValueError("published source data cannot be extended")
    connection.execute(statement, parameters)
    found = connection.execute(lookup, key).fetchone()
    if found is None or found[0] != expected:
        raise ValueError("stored source data conflicts with this release")


def _write_release_files(directory: Path, manifest_data: bytes, report_data: bytes) -> None:
    with (directory / "manifest.json").open("xb") as output:
        output.write(manifest_data)
    with (directory / "validation.json").open("xb") as output:
        output.write(report_data)


def _insert_source(connection: sqlite3.Connection, source: SourceFileRecord) -> None:
    payload = _json_bytes(source).decode("utf-8")
    _insert_checked(connection, "INSERT INTO source_file VALUES (?, ?) ON CONFLICT DO NOTHING",
                    (source.source_file_id, payload), "SELECT payload FROM source_file WHERE source_file_id = ?",
                    (source.source_file_id,), payload)


def _insert_observation(connection: sqlite3.Connection, item: ObservationRecord, frozen: bool) -> None:
    if type(item.source_row_id) is not int or item.source_row_id < 1:
        raise ValueError("invalid source row ID")
    for value in (item.longitude, item.latitude, item.scan_km, item.track_km, item.frp_mw):
        if value is not None and (type(value) not in (int, float) or not math.isfinite(value)):
            raise ValueError("observation values must be finite")
    if any(value is not None and value < 0 for value in (item.scan_km, item.track_km, item.frp_mw)):
        raise ValueError("observation values cannot be negative")
    observed_at = _utc_text(item.observed_at)
    payload = _json_bytes(item).decode("utf-8")
    _insert_checked(connection,
        "INSERT INTO observation VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING",
        (item.observation_id, item.source_file_id, item.source_row_id, observed_at,
         item.platform, item.longitude, item.latitude, item.frp_mw, payload),
        "SELECT payload FROM observation WHERE observation_id = ?", (item.observation_id,), payload, frozen)


def _insert_batch(connection: sqlite3.Connection, batch: SourceBatch, sources: dict[str, SourceFileRecord]) -> None:
    source = sources.get(batch.source_file.source_file_id)
    if source is None or _json_bytes(source) != _json_bytes(batch.source_file):
        raise ValueError("batch source is not in the manifest")
    frozen = connection.execute(
        "SELECT 1 FROM release, json_each(release.manifest, '$.source_files') AS file WHERE json_extract(file.value, '$.source_file_id') = ? LIMIT 1",
        (source.source_file_id,),
    ).fetchone() is not None
    for item in batch.observations:
        if item.source_file_id != source.source_file_id:
            raise ValueError("observation source does not match batch")
        _utc_text(item.observed_at)
        if not source.start_date <= item.observed_at.date() < source.end_date:
            raise ValueError("observation date is outside the source window")
        _insert_observation(connection, item, frozen)
    for item in batch.bands:
        owner = connection.execute("SELECT source_file_id FROM observation WHERE observation_id = ?", (item.observation_id,)).fetchone()
        if owner is None or owner[0] != source.source_file_id:
            raise ValueError("band observation does not belong to batch source")
        if item.value is not None and (type(item.value) not in (int, float) or not math.isfinite(item.value)):
            raise ValueError("band value must be finite")
        payload = _json_bytes(item).decode("utf-8")
        _insert_checked(connection, "INSERT INTO band_measurement VALUES (?, ?, ?) ON CONFLICT DO NOTHING",
                        (item.observation_id, item.band_name, payload),
                        "SELECT payload FROM band_measurement WHERE observation_id = ? AND band_name = ?",
                        (item.observation_id, item.band_name), payload, frozen)
    for item in batch.opportunities:
        if item.source_file_id != source.source_file_id:
            raise ValueError("opportunity source does not match batch")
        _utc_text(item.observed_at)
        if not source.start_date <= item.observed_at.date() < source.end_date:
            raise ValueError("opportunity date is outside the source window")
        payload = _json_bytes(item).decode("utf-8")
        _insert_checked(connection, "INSERT INTO opportunity VALUES (?, ?, ?) ON CONFLICT DO NOTHING",
                        (item.source_file_id, item.pass_id, payload),
                        "SELECT payload FROM opportunity WHERE source_file_id = ? AND pass_id = ?",
                        (item.source_file_id, item.pass_id), payload, frozen)


def _check_selection(connection: sqlite3.Connection, manifest: ReleaseRecord) -> None:
    for source_id, row_ids in manifest.source_selection["rows"].items():
        for row_id in row_ids:
            exists = connection.execute(
                "SELECT 1 FROM observation WHERE source_file_id = ? AND source_row_id = ?",
                (source_id, row_id),
            ).fetchone()
            if exists is None:
                raise ValueError("selected source row is missing")


def _insert_daily(connection: sqlite3.Connection, item: DailyRecord, manifest: ReleaseRecord) -> None:
    if item.release_id != manifest.summary.release_id or item.method_id != manifest.method_id:
        raise ValueError("daily row does not match release")
    if type(item.source_count) is not int or item.source_count < 0:
        raise ValueError("source count must be a nonnegative integer")
    if item.reference_count_estimate is not None and not math.isfinite(item.reference_count_estimate):
        raise ValueError("daily estimate must be finite")
    if manifest.method_id is None and item.reference_count_estimate is not None:
        raise ValueError("source-only releases cannot contain an estimate")
    connection.execute(
        "INSERT INTO analysis_daily VALUES (?, ?, ?, ?, ?, ?)",
        (item.release_id, item.cell_id, item.date.isoformat(), item.source_count,
         item.reference_count_estimate, _json_bytes(item).decode("utf-8")),
    )


def publish_release(path: Path, batches: Iterator[SourceBatch], daily: Iterator[DailyRecord],
                    manifest: ReleaseRecord, report: ValidationReport, *, storage: StorageSettings) -> None:
    """Write files first, then commit all data and the release in one transaction."""
    _check_manifest(manifest, report)
    if path.resolve() != storage.database_path.resolve():
        raise ValueError("database path does not match settings")
    root = storage.releases_path.resolve()
    root.mkdir(parents=True, exist_ok=True)
    directory = root / manifest.summary.release_id
    manifest_data, report_data = _json_bytes(manifest), _json_bytes(report)
    created = False
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=rw", uri=True, timeout=5)
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("BEGIN IMMEDIATE")
        if connection.execute("SELECT 1 FROM release WHERE release_id = ?", (manifest.summary.release_id,)).fetchone():
            raise ValueError("release ID already exists")
        sources = {item.source_file_id: item for item in manifest.source_files}
        for source in sources.values():
            _insert_source(connection, source)
        for batch in batches:
            _insert_batch(connection, batch, sources)
        _check_selection(connection, manifest)
        directory.mkdir()
        created = True
        _write_release_files(directory, manifest_data, report_data)
        connection.execute("INSERT INTO release VALUES (?, ?, ?, ?, ?)",
                           (manifest.summary.release_id, manifest_data.decode("utf-8"),
                            hashlib.sha256(manifest_data).hexdigest(), manifest.report_sha256, str(directory)))
        for item in daily:
            _insert_daily(connection, item, manifest)
        connection.commit()
    except Exception:
        connection.rollback()
        if created:
            for name in ("manifest.json", "validation.json"):
                (directory / name).unlink(missing_ok=True)
            directory.rmdir()
        raise
    finally:
        connection.close()
