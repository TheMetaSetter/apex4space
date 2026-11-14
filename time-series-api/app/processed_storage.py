"""Storage and integrity checks for processed hotspot cell releases."""

import hashlib
import json
import os
import re
import sqlite3
import time
from collections.abc import Iterator, Sequence
from contextlib import closing
from datetime import date
from pathlib import Path

from pydantic import TypeAdapter

from app.cells import CellRecord, CellReleaseManifest, DailyHotspotSummary
from app.models import ApiError, StorageSettings

CELL_SCHEMA = """
CREATE TABLE IF NOT EXISTS hotspot_cell (
    grid_version TEXT NOT NULL,
    cell_id TEXT NOT NULL,
    center_longitude REAL NOT NULL CHECK (center_longitude BETWEEN -180 AND 180),
    center_latitude REAL NOT NULL CHECK (center_latitude BETWEEN -90 AND 90),
    geometry_json TEXT NOT NULL,
    PRIMARY KEY (grid_version, cell_id)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS daily_hotspot_summary (
    release_id TEXT NOT NULL,
    area_id TEXT NOT NULL,
    date TEXT NOT NULL,
    active_cell_count INTEGER,
    hotspot_cell_ids_json TEXT,
    status TEXT NOT NULL,
    PRIMARY KEY (release_id, area_id, date),
    CHECK ((active_cell_count IS NULL) = (hotspot_cell_ids_json IS NULL)),
    CHECK (active_cell_count IS NULL OR active_cell_count >= 0)
) WITHOUT ROWID;
"""


def initialize_cell_database(path: Path) -> None:
    """Create only the two tables used by processed map releases."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError("processed database path cannot be a symlink")
    with closing(sqlite3.connect(path, timeout=5)) as connection:
        existing = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        allowed = {"hotspot_cell", "daily_hotspot_summary"}
        if existing and existing != allowed:
            raise ValueError("processed database must contain only the two map tables")
        connection.executescript(CELL_SCHEMA)
        created = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        if created != allowed:
            raise ValueError("processed database schema is not exact")


def _cell_json(value: object) -> str:
    data = TypeAdapter(type(value)).dump_python(value, mode="json")
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _write_json(path: Path, value: object) -> bytes:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    with path.open("xb") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    return encoded


def _validated_processed_rows(
    cells: Iterator[CellRecord], summaries: Iterator[DailyHotspotSummary],
    manifest: CellReleaseManifest,
) -> tuple[tuple[CellRecord, ...], tuple[DailyHotspotSummary, ...]]:
    release_id = manifest.release_id
    cell_rows = tuple(cells)
    summary_rows = tuple(summaries)
    if len(cell_rows) > 10000 or sum(row.active_cell_count or 0 for row in summary_rows) > 100000:
        raise ValueError("processed release exceeds cell or membership limit")
    if any(row.grid_version != manifest.grid_version for row in cell_rows):
        raise ValueError("cell grid does not match release")
    if any(row.area_id not in manifest.areas for row in summary_rows):
        raise ValueError("summary area is not in the release catalog")
    if any(row.release_id != release_id or not manifest.start_date <= row.date < manifest.end_date
           for row in summary_rows):
        raise ValueError("summary is outside the release")
    cell_rows = tuple(sorted(cell_rows, key=lambda row: (row.grid_version, row.cell_id)))
    summary_rows = tuple(sorted(summary_rows, key=lambda row: (row.area_id, row.date)))
    if len({(row.grid_version, row.cell_id) for row in cell_rows}) != len(cell_rows):
        raise ValueError("duplicate hotspot cell shape")
    available_ids = {row.cell_id for row in cell_rows}
    if any(row.hotspot_cell_ids is not None and not set(row.hotspot_cell_ids).issubset(available_ids)
           for row in summary_rows):
        raise ValueError("summary references a missing hotspot cell shape")
    if len({(row.release_id, row.area_id, row.date) for row in summary_rows}) != len(summary_rows):
        raise ValueError("duplicate daily hotspot summary")
    expected_summary_keys = {
        (area_id, date.fromordinal(manifest.start_date.toordinal() + offset))
        for area_id in manifest.areas
        for offset in range((manifest.end_date - manifest.start_date).days)
    }
    if not manifest.areas or {(row.area_id, row.date) for row in summary_rows} != expected_summary_keys:
        raise ValueError("release must contain one summary for every area and UTC day")
    return cell_rows, summary_rows


def _release_metadata(
    cell_rows: Sequence[CellRecord], summary_rows: Sequence[DailyHotspotSummary],
    manifest: CellReleaseManifest,
) -> tuple[CellReleaseManifest, dict[str, object]]:
    release_id = manifest.release_id
    processed_data = {
        "cells": [json.loads(_cell_json(row)) for row in cell_rows],
        "summaries": [json.loads(_cell_json(row)) for row in summary_rows],
    }
    processed_hash = hashlib.sha256(json.dumps(processed_data, sort_keys=True,
        separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()).hexdigest()
    validation = {"release_id": release_id, "processed_sha256": processed_hash,
                  "cell_count": len(cell_rows), "summary_count": len(summary_rows), "status": "passed"}
    validation_bytes = json.dumps(validation, sort_keys=True, separators=(",", ":"),
                                  ensure_ascii=False, allow_nan=False).encode("utf-8")
    final_manifest = manifest.model_copy(update={
        "processed_sha256": processed_hash,
        "validation_sha256": hashlib.sha256(validation_bytes).hexdigest(),
    })
    return final_manifest, validation


def _insert_processed_rows(
    connection: sqlite3.Connection, cell_rows: Sequence[CellRecord],
    summary_rows: Sequence[DailyHotspotSummary],
) -> None:
    for cell in cell_rows:
        geometry = json.dumps(cell.geometry, sort_keys=True, separators=(",", ":"))
        connection.execute(
            "INSERT OR IGNORE INTO hotspot_cell VALUES (?, ?, ?, ?, ?)",
            (cell.grid_version, cell.cell_id, cell.center_longitude, cell.center_latitude, geometry),
        )
        stored = connection.execute(
            "SELECT center_longitude, center_latitude, geometry_json FROM hotspot_cell "
            "WHERE grid_version=? AND cell_id=?", (cell.grid_version, cell.cell_id),
        ).fetchone()
        if stored != (cell.center_longitude, cell.center_latitude, geometry):
            raise ValueError("cell shape changed within a grid version")
    for row in summary_rows:
        ids = None if row.hotspot_cell_ids is None else json.dumps(row.hotspot_cell_ids, separators=(",", ":"))
        connection.execute(
            "INSERT INTO daily_hotspot_summary VALUES (?, ?, ?, ?, ?, ?)",
            (row.release_id, row.area_id, row.date.isoformat(), row.active_cell_count, ids, row.status),
        )


def _check_saved_budget(
    connection: sqlite3.Connection, storage: StorageSettings, temp_dir: Path,
) -> None:
    metadata_bytes = sum(item.stat().st_size for item in temp_dir.iterdir() if item.is_file())
    page_count = connection.execute("PRAGMA page_count").fetchone()[0]
    page_size = connection.execute("PRAGMA page_size").fetchone()[0]
    release_bytes = sum(
        item.stat().st_size for item in storage.releases_path.rglob("*")
        if item.is_file() and temp_dir not in item.parents
    )
    if page_count * page_size + release_bytes + metadata_bytes > storage.saved_bytes_limit:
        raise ValueError("saved data exceed the configured storage limit")


def _remove_release_directory(path: Path) -> None:
    if path.exists():
        for item in path.iterdir():
            item.unlink()
        path.rmdir()


def publish_cell_release(path: Path, cells: Iterator[CellRecord],
                         summaries: Iterator[DailyHotspotSummary],
                         manifest: CellReleaseManifest, storage: StorageSettings) -> None:
    """Write one checked processed release into the exact two-table database."""
    import tempfile

    if path != storage.database_path:
        raise ValueError("processed database path does not match settings")
    release_id = manifest.release_id
    target = storage.releases_path / release_id
    if target.exists() or target.is_symlink():
        raise ValueError("processed release already exists")
    storage.releases_path.mkdir(parents=True, exist_ok=True)
    cell_rows, summary_rows = _validated_processed_rows(cells, summaries, manifest)
    final_manifest, validation = _release_metadata(cell_rows, summary_rows, manifest)
    temp_dir = Path(tempfile.mkdtemp(prefix=f".{release_id}-", dir=storage.releases_path))
    try:
        _write_json(temp_dir / "manifest.json", TypeAdapter(CellReleaseManifest).dump_python(final_manifest, mode="json"))
        _write_json(temp_dir / "validation.json", validation)
        with closing(sqlite3.connect(path, timeout=5)) as connection:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("BEGIN IMMEDIATE")
            _insert_processed_rows(connection, cell_rows, summary_rows)
            _check_saved_budget(connection, storage, temp_dir)
            os.replace(temp_dir, target)
            connection.commit()
    except Exception:
        _remove_release_directory(target)
        _remove_release_directory(temp_dir)
        raise


def read_cell_manifest(releases_path: Path, release_id: str) -> CellReleaseManifest:
    """Read release files after checking their identity and hashes."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", release_id):
        raise ValueError("invalid release ID")
    directory = releases_path / release_id
    if directory.is_symlink() or not directory.is_dir():
        raise ApiError(404, "RELEASE_NOT_FOUND", "Release not found")
    manifest_path, validation_path = directory / "manifest.json", directory / "validation.json"
    if any(path.is_symlink() or not path.is_file() or path.stat().st_size > 1_000_000
           for path in (manifest_path, validation_path)):
        raise ValueError("processed release metadata is unsafe")
    manifest = CellReleaseManifest.model_validate_json(manifest_path.read_bytes())
    validation = json.loads(validation_path.read_bytes())
    validation_hash = hashlib.sha256(validation_path.read_bytes()).hexdigest()
    if (manifest.release_id != release_id or manifest.validation_sha256 != validation_hash
            or manifest.processed_sha256 != validation.get("processed_sha256")
            or validation.get("release_id") != release_id or validation.get("status") != "passed"):
        raise ValueError("processed release metadata does not match")
    return manifest


def read_hotspot_summary(path: Path, release_id: str, area_id: str, day: date) -> DailyHotspotSummary:
    """Read one prepared area and UTC day row."""
    with closing(_read_connection(path)) as connection:
        row = connection.execute(
            "SELECT active_cell_count, hotspot_cell_ids_json, status FROM daily_hotspot_summary "
            "WHERE release_id=? AND area_id=? AND date=?", (release_id, area_id, day.isoformat()),
        ).fetchone()
    if row is None:
        raise ApiError(404, "SUMMARY_NOT_FOUND", "No prepared summary exists for this area and day.")
    ids = None if row[1] is None else tuple(json.loads(row[1]))
    return DailyHotspotSummary(release_id=release_id, area_id=area_id, date=day,
        active_cell_count=row[0], hotspot_cell_ids=ids, status=row[2])


def read_hotspot_cells(path: Path, grid_version: str, cell_ids: Sequence[str]) -> tuple[CellRecord, ...]:
    """Read the requested sparse cell shapes from the local database."""
    if not cell_ids or len(cell_ids) > 10000 or len(set(cell_ids)) != len(cell_ids):
        raise ValueError("cell ID selection is empty, too large, or duplicated")
    placeholders = ",".join("?" for _ in cell_ids)
    with closing(_read_connection(path)) as connection:
        rows = connection.execute(
            f"SELECT cell_id, center_longitude, center_latitude, geometry_json FROM hotspot_cell "
            f"WHERE grid_version=? AND cell_id IN ({placeholders})", (grid_version, *cell_ids),
        ).fetchall()
    by_id = {row[0]: CellRecord(grid_version=grid_version, cell_id=row[0],
        center_longitude=row[1], center_latitude=row[2], geometry=json.loads(row[3])) for row in rows}
    if set(by_id) != set(cell_ids):
        raise ValueError("summary references a missing hotspot cell shape")
    return tuple(by_id[cell_id] for cell_id in cell_ids)


def read_hotspot_cell_ids_in_bbox(path: Path, grid_version: str,
                                  cell_ids: Sequence[str], bbox,
                                  *, maximum_cells: int = 10000) -> tuple[str, ...]:
    """Select stored cell centers inside a bbox before loading their shapes."""
    if len(cell_ids) > 100000 or len(set(cell_ids)) != len(cell_ids):
        raise ValueError("summary cell IDs are too large or duplicated")
    west, south, east, north = bbox
    found: set[str] = set()
    matched: set[str] = set()
    with closing(_read_connection(path)) as connection:
        for offset in range(0, len(cell_ids), 500):
            part = cell_ids[offset:offset + 500]
            placeholders = ",".join("?" for _ in part)
            rows = connection.execute(
                "SELECT cell_id, center_longitude, center_latitude FROM hotspot_cell "
                f"WHERE grid_version=? AND cell_id IN ({placeholders})",
                (grid_version, *part),
            ).fetchall()
            for cell_id, longitude, latitude in rows:
                found.add(cell_id)
                if west <= longitude <= east and south <= latitude <= north:
                    matched.add(cell_id)
                    if len(matched) > maximum_cells:
                        raise ValueError("map contains more than 10,000 matching cells")
    if found != set(cell_ids):
        raise ValueError("summary references a missing hotspot cell shape")
    return tuple(cell_id for cell_id in cell_ids if cell_id in matched)


def _read_connection(path: Path, seconds: float = 5) -> sqlite3.Connection:
    """Open an existing database read-only and bound query time."""
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
    deadline = time.monotonic() + seconds
    connection.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
    return connection
