"""Build an immutable, processed-only SQLite release from FIRMS CSV files."""

import argparse
import csv
import hashlib
import io
import json
import math
import os
import re
import shutil
import sqlite3
import stat
import sys
import tempfile
import time
import unicodedata
from datetime import date, timedelta
from pathlib import Path

from pyproj import Transformer, __version__ as pyproj_version, proj_version_str
from shapely import normalize
from shapely.affinity import translate
from shapely.geometry import LineString, MultiPolygon, Polygon, box, mapping
from shapely.ops import split
from shapely.validation import explain_validity
import shapely

try:
    import resource
except ImportError:
    resource = None
FIELD_LIMIT = 64 * 1024
RECORD_LIMIT = 1024 * 1024
BATCH_SIZE = 4000
GRID_SIZE = 10_000.0
GRID_POLICY = "firms-ease-10km-v2"
REDUCTION_POLICY = "union-valid-cell-day-v1"
DOMAINS = {
    "firms-ease-global-10km-v2": (6933, -86.0, 86.0),
    "firms-ease-north-10km-v2": (6931, 86.0, 90.0),
    "firms-ease-south-10km-v2": (6932, -90.0, -86.0),
}
TRANSFORMERS = {}
class HashingReader(io.RawIOBase):
    """Hash the exact bytes consumed by Python's streaming CSV decoder."""

    def __init__(self, stream):
        self.stream = stream; self.digest = hashlib.sha256(); self.bytes_read = 0

    def readable(self): return True

    def readinto(self, target):
        data = self.stream.read(len(target)); self.digest.update(data); self.bytes_read += len(data)
        target[:len(data)] = data; return len(data)

    def close(self):
        if not self.closed: self.stream.close(); super().close()
def _signature(info): return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns
def _hash_path(path):
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size

def _find_csv_paths(inputs):
    paths = set()
    for supplied in inputs:
        root = Path(supplied)
        if root.is_symlink():
            raise ValueError("input path cannot be a symlink")
        if root.is_file():
            if root.suffix.casefold() != ".csv":
                raise ValueError(f"input file is not a CSV: {root.name}")
            paths.add(root.resolve(strict=True))
        elif root.is_dir():
            for folder, directories, filenames in os.walk(root, followlinks=False):
                if any((Path(folder) / name).is_symlink() for name in directories):
                    raise ValueError(f"input directory contains a symlink: {root.name}")
                directories[:] = sorted(directories)
                for name in filenames:
                    path = Path(folder) / name
                    if path.suffix.casefold() != ".csv":
                        continue
                    if path.is_symlink():
                        raise ValueError(f"CSV input cannot be a symlink: {name}")
                    paths.add(path.resolve(strict=True))
        else:
            raise ValueError(f"input path does not exist or is not a file/directory: {root}")
    if not paths:
        raise ValueError("no FIRMS CSV files were found")
    return tuple(sorted(paths, key=lambda path: path.as_posix()))

def discover_inputs(inputs):
    """Find CSVs, hash them in bounded memory, and freeze their file identity."""
    paths = _find_csv_paths(inputs)
    roots = [Path(path).resolve() for path in inputs]
    base = Path(os.path.commonpath([str(path if path.is_dir() else path.parent)
                                   for path in roots]))
    found = []
    for path in paths:
        before = path.stat(follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise ValueError(f"CSV input must be a singly linked regular file: {path.name}")
        digest, byte_count = _hash_path(path)
        after = path.stat(follow_symlinks=False)
        if _signature(before) != _signature(after) or byte_count != before.st_size:
            raise ValueError(f"CSV changed during discovery: {path.name}")
        try:
            label = path.relative_to(base).as_posix()
        except ValueError:
            label = path.name
        found.append(dict(path=path, label=label, size_bytes=byte_count,
            device=before.st_dev, inode=before.st_ino, modified_ns=before.st_mtime_ns,
            sha256=digest))
    return tuple(found)

def _header_indexes(headers, label):
    normalized = [unicodedata.normalize("NFC", value.strip()).casefold() for value in headers]
    if any(not value for value in normalized) or len(set(normalized)) != len(normalized):
        raise ValueError(f"{label}: duplicate or empty normalized CSV header")
    indexes = {name: index for index, name in enumerate(normalized)}
    missing = {"latitude", "longitude", "acq_date"} - indexes.keys()
    if missing:
        raise ValueError(f"{label}: missing required CSV headers: {', '.join(sorted(missing))}")
    return indexes

def _parse_record(values, indexes, label, record_number):
    if sum(len(value.encode("utf-8")) for value in values) > RECORD_LIMIT:
        raise ValueError(f"{label}: record {record_number}: CSV record exceeds 1 MiB")
    try:
        longitude = float(values[indexes["longitude"]].strip())
        latitude = float(values[indexes["latitude"]].strip())
    except ValueError as error:
        raise ValueError(f"{label}: record {record_number}: invalid coordinates") from error
    if not math.isfinite(longitude) or not math.isfinite(latitude):
        raise ValueError(f"{label}: record {record_number}: non-finite coordinates")
    if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
        raise ValueError(f"{label}: record {record_number}: coordinates are out of range")
    date_text = values[indexes["acq_date"]].strip()
    try:
        acquired = date.fromisoformat(date_text)
    except ValueError as error:
        raise ValueError(f"{label}: record {record_number}: invalid acq_date") from error
    if acquired.isoformat() != date_text:
        raise ValueError(f"{label}: record {record_number}: acq_date must be YYYY-MM-DD")
    time_text = values[indexes["acq_time"]].strip() if "acq_time" in indexes else ""
    if time_text and (not re.fullmatch(r"\d{1,4}", time_text)
                      or int(time_text.zfill(4)[:2]) > 23 or int(time_text.zfill(4)[2:]) > 59):
        raise ValueError(f"{label}: record {record_number}: invalid UTC acq_time")
    labels = tuple((field, values[indexes[field]].strip()) for field in
                   ("satellite", "instrument", "version")
                   if field in indexes and values[indexes[field]].strip())
    return record_number, acquired, longitude, latitude, labels

def read_rows(identity):
    """Yield validated compact rows and verify the exact source bytes at EOF."""
    path, label = identity["path"], identity["label"]
    before = path.stat(follow_symlinks=False)
    expected = (identity["device"], identity["inode"], identity["size_bytes"], identity["modified_ns"])
    if _signature(before) != expected:
        raise ValueError(f"CSV changed after discovery: {label}")
    csv.field_size_limit(FIELD_LIMIT)
    hashing = HashingReader(path.open("rb"))
    record_number = 1
    try:
        with io.TextIOWrapper(io.BufferedReader(hashing), encoding="utf-8-sig", newline="") as text:
            reader = csv.reader(text, strict=True)
            try:
                indexes = _header_indexes(next(reader), label)
            except StopIteration as error:
                raise ValueError(f"{label}: CSV is empty") from error
            try:
                for record_number, values in enumerate(reader, start=2):
                    if len(values) != len(indexes):
                        raise ValueError(f"{label}: record {record_number}: CSV row has the wrong field count")
                    yield _parse_record(values, indexes, label, record_number)
            except csv.Error as error:
                raise ValueError(f"{label}: record {record_number + 1}: malformed CSV") from error
        after = path.stat(follow_symlinks=False)
        if (_signature(after) != expected or hashing.bytes_read != identity["size_bytes"]
                or hashing.digest.hexdigest() != identity["sha256"]):
            raise ValueError(f"CSV changed or failed byte verification: {label}")
    finally:
        if not hashing.closed:
            hashing.close()

def _transformers(epsg):
    if epsg not in TRANSFORMERS:
        TRANSFORMERS[epsg] = (Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True), Transformer.from_crs(f"EPSG:{epsg}", "EPSG:4326", always_xy=True))
    return TRANSFORMERS[epsg]

def _grid_index(value):
    nearest = round(value / GRID_SIZE)
    edge = nearest * GRID_SIZE
    return nearest if abs(value - edge) <= 1e-6 else math.floor(value / GRID_SIZE)

def assign_grid_cell(longitude, latitude):
    """Return a grid key only; shape creation waits until unique cells are known."""
    longitude = -180.0 if longitude == 180.0 else longitude
    if latitude > 86:
        grid_version, epsg = "firms-ease-north-10km-v2", 6931
    elif latitude < -86:
        grid_version, epsg = "firms-ease-south-10km-v2", 6932
    else:
        grid_version, epsg = "firms-ease-global-10km-v2", 6933
    try:
        x, y = _transformers(epsg)[0].transform(longitude, latitude, errcheck=True)
    except Exception as error:
        raise ValueError("coordinate cannot be projected into its selected grid") from error
    if not math.isfinite(x) or not math.isfinite(y):
        raise ValueError("coordinate has a non-finite projected location")
    column, row = _grid_index(x), _grid_index(y)
    return grid_version, f"{column}:{row}", column, row

def _sampled_ring(left, bottom, epsg):
    size = GRID_SIZE
    corners = [(left, bottom), (left + size, bottom),
               (left + size, bottom + size), (left, bottom + size)]
    projected = []
    for index, (x0, y0) in enumerate(corners):
        x1, y1 = corners[(index + 1) % 4]
        projected.extend((x0 + (x1 - x0) * step / 10,
                          y0 + (y1 - y0) * step / 10) for step in range(10))
    projected.append(projected[0])
    xs, ys = zip(*projected)
    longitudes, latitudes = _transformers(epsg)[1].transform(xs, ys, errcheck=True)
    ring = []
    for longitude, latitude in zip(longitudes, latitudes, strict=True):
        if not math.isfinite(longitude) or not math.isfinite(latitude):
            raise ValueError("cell edge has a non-finite geographic coordinate")
        if ring:
            longitude += 360 * round((ring[-1][0] - longitude) / 360)
        ring.append((longitude, latitude))
    return ring

def _polygon_parts(geometry):
    if geometry.geom_type == "Polygon":
        return [geometry]
    if hasattr(geometry, "geoms"):
        return [part for child in geometry.geoms for part in _polygon_parts(child)]
    return []

def make_cell_geometry(grid_version, column, row):
    """Build and normalize one geographic shape for one unique grid cell."""
    epsg = next(code for name, (code, _, _) in DOMAINS.items() if name == grid_version)
    left, bottom = column * GRID_SIZE, row * GRID_SIZE
    ring = _sampled_ring(left, bottom, epsg)
    polar = epsg in (6931, 6932) and left <= 0 <= left + GRID_SIZE and bottom <= 0 <= bottom + GRID_SIZE
    if polar:
        pole = 90.0 if epsg == 6931 else -90.0
        ring.extend(((ring[-1][0], pole), (ring[0][0], pole), ring[0]))
    polygon = Polygon(ring)
    if epsg == 6933:
        polygon = polygon.intersection(box(min(x for x, _ in ring) - 1, -86,
                                           max(x for x, _ in ring) + 1, 86))
    if polygon.is_empty or not polygon.is_valid:
        raise ValueError(f"invalid cell geometry: {explain_validity(polygon)}")
    pieces = [polygon]
    min_x, _, max_x, _ = polygon.bounds
    first = math.ceil((min_x - 180) / 360)
    last = math.floor((max_x - 180) / 360)
    for seam_index in range(first, last + 1):
        seam = 180 + 360 * seam_index
        line = LineString(((seam, -90), (seam, 90)))
        pieces = [part for current in pieces for part in split(current, line).geoms]
    normalized = []
    for part in pieces:
        shifted = translate(part, xoff=-360 * math.floor((part.representative_point().x + 180) / 360))
        clipped = shifted.intersection(box(-180, -90, 180, 90))
        normalized.extend(_polygon_parts(clipped))
    geometry = normalize(normalized[0] if len(normalized) == 1 else MultiPolygon(normalized))
    if geometry.is_empty or not geometry.is_valid:
        raise ValueError("cell geometry is invalid after seam normalization")
    return mapping(geometry)

TABLES = {
    "hotspot_cell": ("grid_version,cell_id,column_index,row_index,min_x_m,min_y_m,max_x_m,max_y_m,center_longitude,center_latitude,geometry_json", "grid_version,cell_id"),
    "hotspot_cell_day": ("release_id,date,grid_version,cell_id", "release_id,date,grid_version,cell_id"),
    "daily_hotspot_summary": ("release_id,date,area_id,active_cell_count,status,input_state", "release_id,date"),
}

def _canonical(value): return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)

def _schema(connection):
    connection.executescript("""
    PRAGMA foreign_keys=ON; PRAGMA user_version=2;
    CREATE TABLE hotspot_cell(
      grid_version TEXT NOT NULL, cell_id TEXT NOT NULL,
      column_index INTEGER NOT NULL, row_index INTEGER NOT NULL,
      min_x_m REAL NOT NULL, min_y_m REAL NOT NULL, max_x_m REAL NOT NULL, max_y_m REAL NOT NULL,
      center_longitude REAL NOT NULL CHECK(center_longitude BETWEEN -180 AND 180),
      center_latitude REAL NOT NULL CHECK(center_latitude BETWEEN -90 AND 90), geometry_json TEXT NOT NULL,
      PRIMARY KEY(grid_version,cell_id), UNIQUE(grid_version,column_index,row_index),
      CHECK(cell_id=CAST(column_index AS TEXT)||':'||CAST(row_index AS TEXT)),
      CHECK(min_x_m<max_x_m AND min_y_m<max_y_m)) WITHOUT ROWID;
    CREATE TABLE daily_hotspot_summary(
      release_id TEXT NOT NULL, date TEXT NOT NULL, area_id TEXT NOT NULL CHECK(area_id='world'),
      active_cell_count INTEGER NOT NULL CHECK(active_cell_count>=0),
      status TEXT NOT NULL CHECK(status='coverage_unknown'),
      input_state TEXT NOT NULL CHECK(input_state IN ('records_present','no_records')),
      PRIMARY KEY(release_id,date)) WITHOUT ROWID;
    CREATE TABLE hotspot_cell_day(
      release_id TEXT NOT NULL, date TEXT NOT NULL, grid_version TEXT NOT NULL, cell_id TEXT NOT NULL,
      PRIMARY KEY(release_id,date,grid_version,cell_id),
      FOREIGN KEY(release_id,date) REFERENCES daily_hotspot_summary(release_id,date),
      FOREIGN KEY(grid_version,cell_id) REFERENCES hotspot_cell(grid_version,cell_id)) WITHOUT ROWID;
    CREATE INDEX hotspot_cell_day_cell_date ON hotspot_cell_day(grid_version,cell_id,release_id,date);
    CREATE INDEX hotspot_cell_center ON hotspot_cell(center_longitude,center_latitude,grid_version,cell_id);
    """)

def _logical_hashes(connection):
    entries = []
    for name, (columns, order) in TABLES.items():
        count = connection.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
        digest = hashlib.sha256(b"apex4space.firms.logical.v1\0" + name.encode() + b"\0" + count.to_bytes(8, "big"))
        cursor = connection.execute(f"SELECT {columns} FROM {name} ORDER BY {order}")
        while rows := cursor.fetchmany(2000):
            for row in rows:
                raw = _canonical(row).encode("utf-8")
                digest.update(len(raw).to_bytes(8, "big")); digest.update(raw)
        entries.append({"name": name, "rows": count, "sha256": digest.hexdigest()})
    payload = {"hash_version": "apex4space.firms.logical.v1", "schema_version": 2,
        "grid_policy_version": GRID_POLICY, "reduction_policy_version": REDUCTION_POLICY,
        "tables": sorted(entries, key=lambda item: item["name"])}
    return payload, hashlib.sha256(_canonical(payload).encode()).hexdigest()

def _free_bytes(path): return os.statvfs(path).f_bavail * os.statvfs(path).f_frsize

def _flush(path):
    if path.is_dir() and os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)

def _json_file(path, value):
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(_canonical(value) + "\n"); stream.flush(); os.fsync(stream.fileno())

def _check_inputs(inputs, expected):
    paths = _find_csv_paths(inputs)
    if [str(path) for path in paths] != [str(item["path"]) for item in expected]:
        raise ValueError("selected CSV set changed during build")
    for item in expected:
        current = item["path"].stat(follow_symlinks=False)
        if _signature(current) != (item["device"], item["inode"], item["size_bytes"], item["modified_ns"]):
            raise ValueError(f"CSV identity changed during build: {item['label']}")

def _load_scratch(work, identities, inputs, memory_budget_mib, max_work_bytes):
    connection = sqlite3.connect(work / "scratch.sqlite3")
    connection.execute(f"PRAGMA cache_size=-{memory_budget_mib * 1024}")
    connection.executescript("CREATE TABLE membership(date TEXT,grid_version TEXT,cell_id TEXT,column_index INT,row_index INT,PRIMARY KEY(date,grid_version,cell_id)) WITHOUT ROWID; CREATE TABLE source(path TEXT,size_bytes INT,sha256 TEXT,rows_read INT); CREATE TABLE source_label(path TEXT,field TEXT,value TEXT,PRIMARY KEY(path,field,value)) WITHOUT ROWID;")
    rows = assigned = scratch_peak = 0; batch = []; labels_batch = []
    extent = [180.0, 90.0, -180.0, -90.0]
    for item in identities:
        file_rows = 0
        for _, acquired, longitude, latitude, labels in read_rows(item):
            rows += 1; file_rows += 1; grid, key, column, row = assign_grid_cell(longitude, latitude)
            extent[:] = (min(extent[0], longitude), min(extent[1], latitude), max(extent[2], longitude), max(extent[3], latitude))
            batch.append((acquired.isoformat(), grid, key, column, row)); assigned += 1
            labels_batch.extend((item["label"], field, value) for field, value in labels)
            if len(batch) == BATCH_SIZE:
                connection.executemany("INSERT INTO membership VALUES(?,?,?,?,?) ON CONFLICT DO NOTHING", batch); connection.commit(); batch.clear()
                connection.executemany("INSERT INTO source_label VALUES(?,?,?) ON CONFLICT DO NOTHING", labels_batch); connection.commit(); labels_batch.clear()
                scratch_peak = max(scratch_peak, sum(path.stat().st_size for path in work.iterdir()))
                if max_work_bytes and sum(path.stat().st_size for path in work.iterdir()) > max_work_bytes:
                    raise OSError("scratch database exceeded --max-work-bytes")
        connection.execute("INSERT INTO source VALUES(?,?,?,?)", (item["label"], item["size_bytes"], item["sha256"], file_rows)); connection.commit()
    if labels_batch:
        connection.executemany("INSERT INTO source_label VALUES(?,?,?) ON CONFLICT DO NOTHING", labels_batch); connection.commit()
        scratch_peak = max(scratch_peak, sum(path.stat().st_size for path in work.iterdir()))
    if batch:
        connection.executemany("INSERT INTO membership VALUES(?,?,?,?,?) ON CONFLICT DO NOTHING", batch); connection.commit()
    if not rows:
        raise ValueError("selected CSV files contain no data rows")
    _check_inputs(inputs, identities)
    return connection, rows, assigned, scratch_peak, extent

def _write_cells(scratch, final):
    query = "SELECT DISTINCT grid_version,cell_id,column_index,row_index FROM membership ORDER BY grid_version,cell_id"
    for grid, cell_id, column, row in scratch.execute(query):
        epsg = next(spec[0] for name, spec in DOMAINS.items() if name == grid)
        x, y = column * GRID_SIZE, row * GRID_SIZE
        lon, lat = _transformers(epsg)[1].transform(x + GRID_SIZE / 2, y + GRID_SIZE / 2, errcheck=True)
        geometry = _canonical(make_cell_geometry(grid, column, row))
        final.execute("INSERT INTO hotspot_cell VALUES(?,?,?,?,?,?,?,?,?,?,?)", (
            grid, cell_id, column, row, x, y, x + GRID_SIZE, y + GRID_SIZE,
            0.0 if lon == 0 else lon, 0.0 if lat == 0 else lat, geometry))

def _write_days(scratch, final, release_id, minimum, maximum):
    counts = dict(scratch.execute("SELECT date,count(*) FROM membership GROUP BY date"))
    day = date.fromisoformat(minimum); end = date.fromisoformat(maximum)
    while day <= end:
        text_day = day.isoformat(); count = counts.get(text_day, 0)
        final.execute("INSERT INTO daily_hotspot_summary VALUES(?,?,?,?,?,?)", (
            release_id, text_day, "world", count, "coverage_unknown", "records_present" if count else "no_records"))
        day += timedelta(days=1)
    final.execute("INSERT INTO hotspot_cell_day SELECT ?,date,grid_version,cell_id FROM scratch.membership ORDER BY date,grid_version,cell_id", (release_id,))

def _validate_final(final):
    integrity = final.execute("PRAGMA integrity_check").fetchall()
    foreign = final.execute("PRAGMA foreign_key_check").fetchall()
    names = [row[0] for row in final.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    mismatch = final.execute("SELECT count(*) FROM daily_hotspot_summary d WHERE active_cell_count != (SELECT count(*) FROM hotspot_cell_day m WHERE m.release_id=d.release_id AND m.date=d.date)").fetchone()[0]
    if integrity != [("ok",)] or foreign or mismatch or names != sorted(TABLES):
        raise ValueError("final database integrity, references, daily counts, or table list failed")
    return names, mismatch

def _memory_peak(): return None if resource is None else resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1024 if sys.platform == "darwin" else 1)

def _release_metadata(scratch, hashes, logical_sha, names, mismatch, release_id, rows, assigned,
                     minimum, maximum, extent, scratch_peak):
    sources = []
    for path, size, digest, count in scratch.execute("SELECT path,size_bytes,sha256,rows_read FROM source ORDER BY path"):
        labels = {}
        for field, value in scratch.execute("SELECT field,value FROM source_label WHERE path=? ORDER BY field,value", (path,)):
            labels.setdefault(field, []).append(value)
        sources.append({"path": path, "size_bytes": size, "sha256": digest, "rows_read": count, "identity_labels": labels})
    counts = {entry["name"]: entry["rows"] for entry in hashes["tables"]}
    grids = dict(scratch.execute("SELECT grid_version,count(*) FROM membership GROUP BY grid_version ORDER BY grid_version"))
    manifest = {"schema_version": 2, "release_id": release_id, "sources": sources,
        "rows_read": rows, "rows_assigned": assigned, "distinct_memberships": counts["hotspot_cell_day"],
        "duplicate_memberships": assigned - counts["hotspot_cell_day"], "memberships_by_grid": grids,
        "unique_cells": counts["hotspot_cell"], "date_start": minimum, "date_end": maximum,
        "observed_extent_wgs84": extent, "dense_days": counts["daily_hotspot_summary"],
        "grid_policy_version": GRID_POLICY, "reduction_policy_version": REDUCTION_POLICY, "grids": DOMAINS,
        "python": sys.version, "pyproj": pyproj_version, "proj": proj_version_str, "shapely": shapely.__version__,
        "table_hashes": hashes, "logical_sha256": logical_sha, "peak_rss_bytes": _memory_peak(),
        "scratch_peak_bytes": scratch_peak}
    validation = {"integrity_check": "ok", "foreign_key_violations": 0, "tables": names,
        "rows_read_equals_assigned": rows == assigned, "daily_count_mismatches": mismatch, "logical_sha256": logical_sha}
    return manifest, validation, counts

def build_database(inputs, output_dir, memory_budget_mib=256, max_work_bytes=None, max_output_bytes=None):
    """Stream all selected rows into a new checked, immutable release directory."""
    started = time.monotonic(); output = Path(output_dir).expanduser().absolute()
    if output.exists() or not output.parent.is_dir() or memory_budget_mib < 64:
        raise ValueError("output must be new, its parent must exist, and memory budget must be at least 64 MiB")
    if _free_bytes(output.parent) < 512 * 1024 * 1024:
        raise OSError("less than 512 MiB free before build")
    identities = discover_inputs(inputs); source_hashes = sorted({item["sha256"] for item in identities})
    release_id = hashlib.sha256(_canonical({"schema_version": 2, "grid_policy_version": GRID_POLICY,
        "reduction_policy_version": REDUCTION_POLICY, "source_sha256s": source_hashes}).encode()).hexdigest()
    work = Path(tempfile.mkdtemp(prefix=".firms-work-", dir=output.parent)); stage = None
    scratch = final = None
    try:
        scratch, rows, assigned, scratch_peak, extent = _load_scratch(work, identities, inputs, memory_budget_mib, max_work_bytes)
        minimum, maximum = scratch.execute("SELECT min(date),max(date) FROM membership").fetchone()
        if _free_bytes(output.parent) < 512 * 1024 * 1024: raise OSError("less than 512 MiB free for publication")
        stage = Path(tempfile.mkdtemp(prefix=".firms-stage-", dir=output.parent)); database = stage / "database.sqlite3"
        final = sqlite3.connect(database); final.execute("PRAGMA foreign_keys=ON")
        final.execute("ATTACH DATABASE ? AS scratch", (str(work / "scratch.sqlite3"),))
        final.execute(f"PRAGMA cache_size=-{memory_budget_mib * 1024}"); _schema(final)
        _write_cells(scratch, final); _write_days(scratch, final, release_id, minimum, maximum); final.commit()
        hashes, logical_sha = _logical_hashes(final); names, mismatch = _validate_final(final)
        if max_output_bytes and database.stat().st_size > max_output_bytes: raise OSError("database exceeded --max-output-bytes")
        manifest, validation, counts = _release_metadata(scratch, hashes, logical_sha, names, mismatch,
            release_id, rows, assigned, minimum, maximum, extent, scratch_peak)
        manifest["database_bytes"] = database.stat().st_size
        manifest["elapsed_seconds"] = round(time.monotonic() - started, 2)
        final.close(); final = None; scratch.close(); scratch = None; _check_inputs(inputs, identities)
        _json_file(stage / "manifest.json", manifest); _json_file(stage / "validation.json", validation); _flush(database)
        if _free_bytes(output.parent) < 512 * 1024 * 1024: raise OSError("less than 512 MiB free before publication")
        _check_inputs(inputs, identities)
        if output.exists(): raise ValueError("output directory appeared during build; refusing to replace it")
        _flush(stage); os.rename(stage, output); stage = None; _flush(output.parent)
        return {"release_id": release_id, "rows_read": rows, "rows_assigned": assigned,
            "memberships": counts["hotspot_cell_day"], "cells": counts["hotspot_cell"],
            "start_date": minimum, "end_date": maximum, "database_bytes": (output / "database.sqlite3").stat().st_size,
            "scratch_peak_bytes": manifest["scratch_peak_bytes"],
            "elapsed_seconds": round(time.monotonic() - started, 2)}
    finally:
        if final is not None: final.close()
        if scratch is not None: scratch.close()
        if stage is not None: shutil.rmtree(stage)
        shutil.rmtree(work)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", action="append", required=True, help="CSV file or recursively searched directory (repeatable)")
    parser.add_argument("--output-dir", required=True, help="new output directory on the destination filesystem")
    parser.add_argument("--memory-budget-mib", type=int, default=256)
    parser.add_argument("--max-work-bytes", type=int)
    parser.add_argument("--max-output-bytes", type=int)
    args = parser.parse_args()
    try:
        print(_canonical(build_database(args.input, args.output_dir, args.memory_budget_mib,
                                        args.max_work_bytes, args.max_output_bytes)))
    except (ValueError, OSError, sqlite3.Error) as error:
        parser.exit(2, f"preprocess_firms: {error}\n")

if __name__ == "__main__":
    main()
