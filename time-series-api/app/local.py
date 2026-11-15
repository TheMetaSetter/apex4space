"""Read local FIRMS CSVs into transient daily hotspot cell sets."""

import csv
import hashlib
import io
import json
import os
import re
import stat
import tempfile
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from pathlib import Path

from shapely.geometry import Point, shape

from app.cells import AreaRecord, CellRecord, GridSettings, assign_cell
from app.models import SourceFileRecord
from app.sources import (
    REQUIRED_COLUMNS, _band_fields, _csv_reader, _number, _observation_time, _platform,
)

FIELD_LIMIT_BYTES = 64 * 1024
RECORD_LIMIT_BYTES = 1024 * 1024

@dataclass(frozen=True)
class LocalScanResult:
    source_id: str
    file_id: str
    sha256: str
    versions: tuple[str, ...]
    daily_cell_sets: Mapping[date, frozenset[str]]
    cell_shapes: Mapping[str, CellRecord]
    rows_seen: int
    rows_used: int
    bytes_read: int
    modified_time_utc: str


class _HashingReader(io.RawIOBase):
    """Hash source bytes as the CSV parser consumes them."""

    def __init__(self, stream):
        self.stream = stream
        self.digest = hashlib.sha256()
        self.bytes_read = 0

    def readable(self) -> bool:
        return True

    def readinto(self, target) -> int:
        data = self.stream.read(len(target))
        self.digest.update(data)
        self.bytes_read += len(data)
        target[:len(data)] = data
        return len(data)

    def close(self) -> None:
        if not self.closed:
            self.stream.close()
        super().close()


def discover_local_csvs(root: Path, source_files: Mapping[str, str]) -> tuple[tuple[Path, str], ...]:
    """Resolve only the explicitly selected local CSV paths; inspect no contents."""
    if root.is_symlink() or not root.is_dir():
        raise ValueError("local input root must be a real directory")
    if not source_files:
        raise ValueError("local input settings must select at least one CSV")
    resolved_root = root.resolve(strict=True)
    selected = []
    for name, source_id in sorted(source_files.items()):
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts or not name.lower().endswith(".csv"):
            raise ValueError("selected local CSV path is invalid")
        path = resolved_root / relative
        current = resolved_root
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                raise ValueError("selected local CSV path cannot contain symlinks")
        if not path.is_file():
            raise ValueError("an explicitly selected local CSV is missing")
        info = path.stat(follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("local CSV input must be a singly linked regular file")
        selected.append((path, source_id))
    return tuple(selected)


def _source_version(value: str, processing_mode: str) -> str:
    if not value or len(value) > 64 or any(ord(char) < 32 for char in value):
        raise ValueError("source row has an invalid version label")
    if processing_mode != "NRT":
        return value
    for suffix in ("NRT", "URT", "RT"):
        if value.endswith(suffix) and len(value) > len(suffix):
            return value[:-len(suffix)]
    raise ValueError("NRT row has an unknown version suffix")


def _source_record(file_id: str, source_id: str, modified_time: float) -> SourceFileRecord:
    family, separator, mode = source_id.rpartition("_")
    if not separator or mode not in {"NRT", "SP"}:
        raise ValueError("local CSV source mapping is invalid")
    product = "MODIS" if family == "MODIS" else "VIIRS"
    return SourceFileRecord(
        source_file_id=file_id, source_id=source_id, product=product,
        version="local-stream", processing_mode="NRT" if mode == "NRT" else "standard",
        start_date=date.min, end_date=date.max,
        downloaded_at=datetime.fromtimestamp(modified_time, timezone.utc),
        sha256="0" * 64, request_parameters={"local_file": file_id},
    )


def _scan_rows(reader, source: SourceFileRecord, *, grid: GridSettings,
               area_geometry, start_date: date, end_date: date,
               platforms: tuple[str, ...], maximum_memberships: int):
    day_cells: dict[date, set[str]] = defaultdict(set)
    cell_shapes: dict[str, CellRecord] = {}
    versions: set[str] = set()
    version_bases: set[str] = set()
    rows_seen = rows_used = memberships = 0
    for row in reader:
        rows_seen += 1
        if None in row or any(value is None for value in row.values()):
            raise ValueError("CSV row has the wrong number of fields")
        if sum(len(value.encode("utf-8")) for value in row.values()) > RECORD_LIMIT_BYTES:
            raise ValueError("CSV record exceeds the configured byte limit")
        raw_version = row["version"]
        version_base = _source_version(raw_version, source.processing_mode)
        versions.add(raw_version)
        version_bases.add(version_base)
        if len(version_bases) > 1:
            raise ValueError("source processing version changed during local stream")
        row_source = replace(source, version=version_base)
        longitude, latitude = _number(row["longitude"]), _number(row["latitude"])
        if longitude is None or latitude is None or not (
            -180 <= longitude <= 180 and -90 <= latitude <= 90
        ):
            raise ValueError("invalid observation location")
        observed_at = _observation_time(row, row_source)
        platform = _platform(row, row_source)
        day = observed_at.date()
        if platform not in platforms or not start_date <= day < end_date:
            continue
        cell = assign_cell(longitude, latitude, grid)
        if not area_geometry.covers(Point(cell.center_longitude, cell.center_latitude)):
            continue
        selected_ids = day_cells[day]
        is_new_membership = cell.cell_id not in selected_ids
        selected_ids.add(cell.cell_id)
        cell_shapes[cell.cell_id] = cell
        rows_used += 1
        memberships += int(is_new_membership)
        if memberships > maximum_memberships:
            raise ValueError("processed memberships exceed the configured limit")
    if not versions:
        raise ValueError("local CSV contains no data rows")
    return day_cells, cell_shapes, versions, rows_seen, rows_used


def scan_local_csv(path: Path, *, root: Path, source_id: str, grid: GridSettings,
                   area: AreaRecord, start_date: date, end_date: date,
                   platforms: tuple[str, ...], maximum_memberships: int) -> LocalScanResult:
    """Validate a local source stream and retain only selected day/cell sets."""
    if root.is_symlink() or path.is_symlink():
        raise ValueError("local CSV input root and file cannot be symlinks")
    root = root.resolve(strict=True)
    path = path.resolve(strict=True)
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError("local CSV is outside its input root or is not a regular file")
    if path.suffix.lower() != ".csv" or start_date >= end_date:
        raise ValueError("invalid local CSV or date window")
    before = path.stat(follow_symlinks=False)
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise ValueError("local CSV input must be a singly linked regular file")
    file_id = path.relative_to(root).as_posix()
    source = _source_record(file_id, source_id, before.st_mtime)
    scanned = None
    csv.field_size_limit(FIELD_LIMIT_BYTES)
    hasher = _HashingReader(path.open("rb"))
    try:
        with io.TextIOWrapper(io.BufferedReader(hasher), encoding="utf-8-sig", newline="") as text:
            reader = _csv_reader(text, REQUIRED_COLUMNS)
            _band_fields(reader.fieldnames or [], source.product)
            scanned = _scan_rows(reader, source, grid=grid, area_geometry=shape(area.geometry),
                start_date=start_date, end_date=end_date, platforms=platforms,
                maximum_memberships=maximum_memberships)
        after = path.stat(follow_symlinks=False)
        identity_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        identity_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        if identity_before != identity_after or hasher.bytes_read != before.st_size:
            raise ValueError("local CSV changed or ended before source verification")
    finally:
        if not hasher.closed:
            hasher.close()
    day_cells, cell_shapes, versions, rows_seen, rows_used = scanned
    return LocalScanResult(
        source_id=source_id, file_id=file_id, sha256=hasher.digest.hexdigest(),
        versions=tuple(sorted(versions)),
        daily_cell_sets={day: frozenset(ids) for day, ids in day_cells.items()},
        cell_shapes=cell_shapes, rows_seen=rows_seen, rows_used=rows_used,
        bytes_read=hasher.bytes_read,
        modified_time_utc=datetime.fromtimestamp(before.st_mtime, timezone.utc).isoformat(),
    )


def write_processed_checkpoint(staging_path: Path, release_id: str,
                               result: LocalScanResult, selection_sha256: str) -> tuple[Path, str]:
    """Atomically save verified day/cell sets without raw records or row IDs."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", release_id):
        raise ValueError("invalid release ID for processed checkpoint")
    if not re.fullmatch(r"[0-9a-f]{64}", selection_sha256):
        raise ValueError("invalid local selection identity")
    if staging_path.is_symlink():
        raise ValueError("processed staging path cannot be a symlink")
    staging_path.mkdir(parents=True, exist_ok=True)
    directory = staging_path / release_id
    if directory.is_symlink():
        raise ValueError("processed checkpoint directory cannot be a symlink")
    directory.mkdir(exist_ok=True)
    identity = hashlib.sha256(result.file_id.encode("utf-8")).hexdigest()[:16]
    name = f"{identity}-{result.sha256[:16]}-{selection_sha256[:16]}.cells.json"
    target = directory / name
    checkpoint = {
        "schema_version": 1, "release_id": release_id,
        "source_id": result.source_id, "file_id": result.file_id,
        "source_sha256": result.sha256, "versions": result.versions,
        "selection_sha256": selection_sha256,
        "daily_cell_sets": {day.isoformat(): sorted(ids)
                            for day, ids in sorted(result.daily_cell_sets.items())},
        "rows_seen": result.rows_seen, "rows_used": result.rows_used,
        "bytes_read": result.bytes_read,
    }
    encoded = json.dumps(checkpoint, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    if target.exists():
        if target.is_symlink() or not target.is_file() or target.read_bytes() != encoded:
            raise ValueError("existing processed checkpoint does not match this source selection")
        return target, digest
    descriptor, temporary = tempfile.mkstemp(prefix=f".{name}.", suffix=".part", dir=directory)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return target, digest
