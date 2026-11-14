"""Prepare and publish a source-only data release."""

import argparse
import csv
import hashlib
import json
import time
import tracemalloc
from collections.abc import Iterator, Sequence
from datetime import date, datetime, timezone
from pathlib import Path
from pydantic import TypeAdapter
from shapely.geometry import Point, shape

from app.cells import (
    AreaRecord, CellPreparationSettings, CellRecord, CellReleaseManifest, GridSettings,
    load_area_catalog, load_cell_settings, summarize_hotspots, assign_cell, cell_from_id,
)
from app.drive import DriveFile, ProcessedSource, list_drive_csvs, scan_drive_csv
from app.models import ReleaseRecord, ReleaseSummary, SourceBatch, SourceFileRecord, ValidationReport, load_settings
from app.sources import _downloaded_record, _read_progress, read_source, select_source_records, _sha256
from app.storage import initialize_cell_database, initialize_database, publish_cell_release, publish_release

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_PLATFORMS = {
    "MODIS": ("Aqua", "Terra"), "VIIRS_SNPP": ("Suomi-NPP",),
    "VIIRS_NOAA20": ("NOAA-20",), "VIIRS_NOAA21": ("NOAA-21",),
}


def parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare and publish a processed hotspot release.")
    parser.add_argument("--settings", type=Path, default=PROJECT_ROOT / "config" / "settings.json")
    parser.add_argument("--release-id", required=True)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--input-csv", type=Path)
    source.add_argument("--drive-folder-id")
    parser.add_argument("--source-id")
    parser.add_argument("--area-id")
    parser.add_argument("--start-date", type=date.fromisoformat)
    parser.add_argument("--end-date", type=date.fromisoformat)
    parser.add_argument("--platforms", nargs="+")
    return parser.parse_args(argv)


def _date_window(settings: CellPreparationSettings, start_date, end_date):
    start = start_date or settings.start_date
    end = end_date or settings.end_date
    if start >= end:
        raise ValueError("start date must precede end date")
    return start, end


def _local_source(path: Path, source_id: str) -> SourceFileRecord:
    if path.is_symlink() or not path.is_file() or not source_id:
        raise ValueError("local CSV path or source ID is invalid")
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        first = next(reader, None)
        if not reader.fieldnames or first is None:
            raise ValueError("local CSV has no data rows")
        version = first.get("version", "")
    nrt = source_id.endswith("_NRT")
    if nrt:
        for suffix in ("NRT", "URT", "RT"):
            if version.endswith(suffix):
                version = version[:-len(suffix)]
                break
    product = "MODIS" if source_id.startswith("MODIS") else "VIIRS"
    record = SourceFileRecord(
        source_file_id=path.name, source_id=source_id, product=product, version=version,
        processing_mode="NRT" if nrt else "standard", start_date=date.min, end_date=date.max,
        downloaded_at=datetime.now(timezone.utc), sha256=_sha256(path), request_parameters={"local_file": path.name},
    )
    return record


def _read_local_processed(path: Path, source_id: str, *, grid: GridSettings,
                          area: AreaRecord, start_date: date, end_date: date,
                          platforms: tuple[str, ...], maximum_memberships: int):
    record = _local_source(path, source_id)
    area_geometry = shape(area.geometry)
    day_cells: dict[date, set[str]] = {}
    shapes: dict[str, CellRecord] = {}
    rows_seen = rows_used = 0
    for batch in read_source(path, record, batch_size=1000):
        for observation in batch.observations:
            rows_seen += 1
            day = observation.observed_at.date()
            if observation.platform not in platforms or not start_date <= day < end_date:
                continue
            cell = assign_cell(observation.longitude, observation.latitude, grid)
            if not area_geometry.covers(Point(cell.center_longitude, cell.center_latitude)):
                continue
            day_cells.setdefault(day, set()).add(cell.cell_id)
            shapes[cell.cell_id] = cell
            rows_used += 1
            if sum(len(values) for values in day_cells.values()) > maximum_memberships:
                raise ValueError("processed memberships exceed the configured limit")
    return record, day_cells, shapes, rows_seen, rows_used, path.stat().st_size


def prepare_cell_release(settings: CellPreparationSettings, release_id: str, *,
                         input_csv: Path | None = None, input_source: str | None = None,
                         drive_folder_id: str | None = None, start_date: date | None = None,
                         end_date: date | None = None, area_id: str | None = None,
                         platforms: tuple[str, ...] | None = None) -> None:
    """Stream selected sources and publish only two processed tables."""
    from app.drive import load_drive_token
    import httpx

    if bool(input_csv) == bool(drive_folder_id):
        raise ValueError("select exactly one local CSV or Drive folder")
    selected_start, selected_end = _date_window(settings, start_date, end_date)
    selected_area_id = area_id or settings.area_id
    selected_platforms = platforms or settings.platforms
    if not set(selected_platforms).issubset(set(settings.platforms)):
        raise ValueError("platform selection is not enabled in processed settings")
    areas = {item.area_id: item for item in load_area_catalog(settings.area_catalog_path)}
    if selected_area_id not in areas:
        raise ValueError("area ID is not in the reviewed catalog")
    area = areas[selected_area_id]
    started = time.perf_counter()
    tracemalloc.start()
    all_days: dict[date, set[str]] = {}
    all_cells: dict[str, CellRecord] = {}
    sources = []
    scanned_bytes = rows_seen = rows_used = 0
    if input_csv is not None:
        if input_source is None:
            raise ValueError("--source-id is required with --input-csv")
        record, days, cells_by_id, seen, used, size = _read_local_processed(
            input_csv, input_source, grid=settings.grid, area=area,
            start_date=selected_start, end_date=selected_end,
            platforms=selected_platforms, maximum_memberships=settings.maximum_memberships)
        sources.append({"source_id": record.source_id, "file_id": record.source_file_id,
                        "version": record.version, "sha256": record.sha256,
                        "bytes_read": size, "rows_seen": seen, "rows_used": used})
        scanned_bytes += size
        rows_seen += seen
        rows_used += used
        all_cells.update(cells_by_id)
        for day, ids in days.items():
            all_days.setdefault(day, set()).update(ids)
    else:
        load_drive_token()
        with httpx.Client(verify=True, follow_redirects=False, timeout=30) as client:
            files = list_drive_csvs(drive_folder_id, client=client, source_ids=settings.drive_source_ids)
            if {file.file_id for file in files} != set(settings.drive_source_ids):
                raise ValueError("one or more explicitly selected Drive CSV files are missing")
            for file in files:
                processed = scan_drive_csv(file, client=client, grid=settings.grid, area=area,
                    start_date=selected_start, end_date=selected_end, platforms=selected_platforms,
                    maximum_bytes=settings.maximum_file_bytes,
                    maximum_memberships=settings.maximum_memberships)
                scanned_bytes += processed.bytes_read
                if scanned_bytes > settings.maximum_run_bytes:
                    raise ValueError("Drive run exceeds the configured byte limit")
                rows_seen += processed.rows_seen
                rows_used += processed.rows_used
                sources.append({"source_id": processed.source_id, "file_id": file.file_id,
                    "version": processed.source_version, "sha256": processed.sha256,
                    "bytes_read": processed.bytes_read, "rows_seen": processed.rows_seen,
                    "rows_used": processed.rows_used})
                for day, ids in processed.daily_cell_sets.items():
                    all_days.setdefault(day, set()).update(ids)
                    for cell_id in ids:
                        all_cells.setdefault(cell_id, cell_from_id(cell_id, settings.grid))
                memberships = sum(len(items) for items in all_days.values())
                if memberships > settings.maximum_memberships:
                    raise ValueError("processed memberships exceed the configured limit")
    day_states = {}
    current = selected_start
    from datetime import timedelta
    while current < selected_end:
        day_states[current] = "coverage_unknown"
        current += timedelta(days=1)
    summaries = summarize_hotspots(
        {day: frozenset(ids) for day, ids in all_days.items()},
        release_id=release_id, area_id=selected_area_id,
        start_date=selected_start, end_date=selected_end, day_states=day_states,
    )
    catalog_hash = hashlib.sha256(settings.area_catalog_path.read_bytes()).hexdigest()
    manifest = CellReleaseManifest(
        release_id=release_id, grid_version=settings.grid.grid_version,
        start_date=selected_start, end_date=selected_end, grid=settings.grid,
        areas={selected_area_id: {"name": area.name, "version": area.version,
                                 "geometry": area.geometry}},
        sources=tuple(sources), code_version="0.1.0", catalog_sha256=catalog_hash,
    )
    initialize_cell_database(settings.storage.database_path)
    publish_cell_release(settings.storage.database_path, iter(all_cells.values()), iter(summaries),
                         manifest, settings.storage)
    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    elapsed = time.perf_counter() - started
    print(json.dumps({"release_id": release_id, "status": "published",
        "source_bytes_scanned": scanned_bytes, "rows_seen": rows_seen,
        "rows_used": rows_used, "cell_day_memberships": sum(len(items) for items in all_days.values()),
        "unique_hotspot_cells": len(all_cells), "peak_memory_bytes": peak_bytes,
        "elapsed_seconds": round(elapsed, 3)}, sort_keys=True))


def _source_inputs(settings):
    root = settings.storage.staging_path
    progress = _read_progress(root)
    records = []
    paths = {}
    for entry in progress.values():
        if entry.get("source") not in settings.downloads.sources or entry.get("bbox") != ",".join(map(str, settings.downloads.bbox)):
            continue
        if not (settings.downloads.start_date.isoformat() <= entry.get("start_date", "")
                and entry.get("end_date", "") <= settings.downloads.end_date.isoformat()):
            continue
        path = root / entry["file"]
        if Path(entry["file"]).name != entry["file"] or path.is_symlink() or not path.is_file():
            raise ValueError("saved source file is unsafe")
        start = date.fromisoformat(entry["start_date"])
        end = date.fromisoformat(entry["end_date"])
        downloaded_at = datetime.fromisoformat(entry["downloaded_at"])
        if downloaded_at.tzinfo is None or downloaded_at.utcoffset() != timezone.utc.utcoffset(downloaded_at):
            raise ValueError("saved download time is invalid")
        record = _downloaded_record(path, entry["source"], start, end, settings, downloaded_at)
        if record.sha256 != entry["sha256"]:
            raise ValueError("saved source hash does not match progress")
        records.append(record)
        paths[record.source_file_id] = path
    if not records:
        raise ValueError("no checked downloads are available")
    return tuple(records), paths


def _source_rows(records, paths, batch_size, maximum_rows):
    observations = []
    band_map = {}
    for source in records:
        for batch in read_source(paths[source.source_file_id], source, batch_size=batch_size):
            if len(observations) + len(batch.observations) > maximum_rows:
                raise ValueError("source rows exceed the configured input limit")
            observations.extend(batch.observations)
            band_map.update({item.observation_id: item for item in batch.bands})
    return tuple(observations), band_map


def _make_report(release_id, records, selected, settings, scope):
    rows = {source.source_file_id: [] for source in records}
    for item in selected:
        rows[item.source_file_id].append(item.source_row_id)
    source_hashes = {source.source_file_id: source.sha256 for source in records}
    manifest_settings = {"schema_version": 1, "tested_scope": scope,
                         "source_policy": dict(settings.science.source_policy)}
    checks = {"provenance": {"source_hashes": source_hashes,
                              "code_version": "0.1.0", "method_id": None,
                              "settings": manifest_settings},
              "source_rows": sum(len(value) for value in rows.values())}
    report = ValidationReport(release_id=release_id, checks=checks,
        supported_metrics=(), tested_scope=scope,
        failures=(), random_seed=None, repeat_count=None, memory_bytes=0, elapsed_seconds=0.0)
    report_data = TypeAdapter(ValidationReport).dump_python(report, mode="json")
    report_bytes = json.dumps(report_data, sort_keys=True,
        separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    return manifest_settings, rows, hashlib.sha256(report_bytes).hexdigest(), report


def _iter_batches(records, selected, bands, batch_size):
    selected_ids = {item.observation_id for item in selected}
    for source in records:
        chosen = tuple(item for item in selected if item.source_file_id == source.source_file_id)
        source_bands = tuple(value for key, value in bands.items() if key in selected_ids and key.startswith(source.source_file_id + ":"))
        yield from _batches(source, chosen, source_bands, batch_size)


def _batches(source, observations, bands, batch_size):
    for offset in range(0, len(observations), batch_size):
        part = observations[offset:offset + batch_size]
        ids = {item.observation_id for item in part}
        yield SourceBatch(
            source_file=source, observations=part,
            bands=tuple(item for item in bands if item.observation_id in ids), opportunities=())


def prepare_release(settings, release_id: str) -> None:
    records, paths = _source_inputs(settings)
    observations, bands = _source_rows(
        records, paths, 1000, settings.api.query_limits["maximum_input_rows"])
    selected = select_source_records(observations, settings.science.source_policy)
    platforms = tuple(sorted({
        platform for source in records
        for platform in SOURCE_PLATFORMS[source.source_id.rsplit("_", 1)[0]]
    }))
    latest_dates = {}
    for item in selected:
        current = latest_dates.get(item.platform)
        if current is None or item.observed_at.date() > current:
            latest_dates[item.platform] = item.observed_at.date()
    scope = {"bbox": list(settings.downloads.bbox),
             "start_date": settings.downloads.start_date.isoformat(),
             "end_date": settings.downloads.end_date.isoformat(),
             "source_only": True}
    manifest_settings, rows, report_hash, report = _make_report(
        release_id, records, selected, settings, scope)
    summary = ReleaseSummary(release_id=release_id,
        study_areas=(settings.downloads.bbox,), start_date=settings.downloads.start_date,
        end_date=settings.downloads.end_date, latest_source_dates=latest_dates,
        available_metrics=(), allowed_platforms=platforms)
    manifest = ReleaseRecord(summary=summary, method_id=None,
        reference_count_definition=None, code_version="0.1.0", settings=manifest_settings,
        source_files=records, source_selection={"rows": rows, "policy": dict(settings.science.source_policy)},
        baseline_rules={}, report_sha256=report_hash, report_urls=())
    batches = _iter_batches(records, selected, bands, 1000)
    initialize_database(settings.storage.database_path)
    publish_release(settings.storage.database_path, batches, iter(()), manifest, report,
                    storage=settings.storage)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_arguments(argv)
    try:
        if args.input_csv or args.drive_folder_id:
            prepare_cell_release(load_cell_settings(args.settings), args.release_id,
                input_csv=args.input_csv, input_source=args.source_id,
                drive_folder_id=args.drive_folder_id, start_date=args.start_date,
                end_date=args.end_date, area_id=args.area_id,
                platforms=tuple(args.platforms) if args.platforms else None)
            return 0
        prepare_release(load_settings(args.settings), args.release_id)
    except Exception as error:
        print(f"Preparation failed: {error}")
        return 1
    print(f"Published source-only release: {args.release_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
