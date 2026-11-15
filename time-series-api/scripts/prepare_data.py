"""Prepare and publish a source-only data release."""

import argparse
import hashlib
import json
import resource
import sys
import time
import tracemalloc
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from pydantic import TypeAdapter
from app.cells import (
    AreaRecord, CellPreparationSettings, CellRecord, CellReleaseManifest,
    load_area_catalog, load_cell_settings, summarize_hotspots, cell_from_id,
)
from app.drive import list_drive_csvs, scan_drive_csv
from app.local import discover_local_csvs, scan_local_csv, write_processed_checkpoint
from app.models import ReleaseRecord, ReleaseSummary, SourceBatch, ValidationReport, load_settings
from app.sources import _downloaded_record, _read_progress, read_source, select_source_records
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
    source.add_argument("--input-dir", type=Path)
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


@dataclass
class CellRunData:
    sources: list[dict[str, object]] = field(default_factory=list)
    day_cells: dict[date, set[str]] = field(default_factory=dict)
    cells: dict[str, CellRecord] = field(default_factory=dict)
    bytes_scanned: int = 0
    rows_seen: int = 0
    rows_used: int = 0

    def merge(self, source: Mapping[str, object], day_sets, shapes) -> None:
        self.sources.append(dict(source))
        for day, cell_ids in day_sets.items():
            self.day_cells.setdefault(day, set()).update(cell_ids)
        self.cells.update(shapes)


def _selection_sha256(settings, area: AreaRecord, area_id: str,
                      start: date, end: date, platforms: tuple[str, ...]) -> str:
    value = {"grid": settings.grid.model_dump(mode="json"), "area_id": area_id,
        "area_version": area.version, "area_geometry": area.geometry,
        "start_date": start.isoformat(), "end_date": end.isoformat(), "platforms": platforms}
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _scan_local_file(settings, release_id, root, path, source_id, area, area_id,
                     start, end, platforms, selection_hash, run: CellRunData) -> None:
    expected_bytes = path.stat(follow_symlinks=False).st_size
    if expected_bytes > settings.maximum_file_bytes:
        raise ValueError("local source file exceeds the configured per-file limit")
    if run.bytes_scanned + expected_bytes > settings.maximum_run_bytes:
        raise ValueError("local source run exceeds the configured byte limit")
    processed = scan_local_csv(path, root=root, source_id=source_id,
        grid=settings.grid, area=area, start_date=start, end_date=end,
        platforms=platforms, maximum_memberships=settings.maximum_memberships)
    if processed.bytes_read != expected_bytes:
        raise ValueError("local source byte count changed during processing")
    _, checkpoint_hash = write_processed_checkpoint(
        settings.storage.staging_path, release_id, processed, selection_hash)
    run.merge({"source_id": processed.source_id, "file_id": processed.file_id,
        "versions": processed.versions, "sha256": processed.sha256,
        "bytes_read": processed.bytes_read, "rows_seen": processed.rows_seen,
        "rows_used": processed.rows_used, "modified_time_utc": processed.modified_time_utc,
        "checkpoint_sha256": checkpoint_hash,
        "verification": "full_stream_sha256_and_unchanged_local_file_identity"},
        processed.daily_cell_sets, processed.cell_shapes)
    run.bytes_scanned += processed.bytes_read
    run.rows_seen += processed.rows_seen
    run.rows_used += processed.rows_used


def _check_local_staging_limit(settings) -> None:
    total = 0
    if settings.storage.staging_path.exists():
        for item in settings.storage.staging_path.rglob("*"):
            if item.is_symlink():
                raise ValueError("processed staging tree cannot contain symlinks")
            if item.is_file():
                total += item.stat().st_size
    if total > settings.storage.temporary_bytes_limit:
        raise ValueError("processed checkpoints exceed the temporary storage limit")


def _scan_local_inputs(settings, release_id, input_csv, input_source, input_dir,
                       area, area_id, start, end, platforms) -> CellRunData:
    root = input_dir if input_dir is not None else input_csv.parent
    local_files = (discover_local_csvs(root, settings.local_source_files) if input_dir is not None
                   else ((input_csv, input_source),))
    selection_hash = _selection_sha256(settings, area, area_id, start, end, platforms)
    run = CellRunData()
    for path, source_id in local_files:
        _scan_local_file(settings, release_id, root, path, source_id, area, area_id,
                         start, end, platforms, selection_hash, run)
        if sum(map(len, run.day_cells.values())) > settings.maximum_memberships:
            raise ValueError("processed memberships exceed the configured limit")
        _check_local_staging_limit(settings)
    return run


def _scan_drive_inputs(settings, folder_id, area, start, end, platforms) -> CellRunData:
    from app.drive import load_drive_token
    import httpx

    load_drive_token()
    run = CellRunData()
    with httpx.Client(verify=True, follow_redirects=False, timeout=30) as client:
        files = list_drive_csvs(folder_id, client=client, source_ids=settings.drive_source_ids)
        if {file.file_id for file in files} != set(settings.drive_source_ids):
            raise ValueError("one or more explicitly selected Drive CSV files are missing")
        for file in files:
            processed = scan_drive_csv(file, client=client, grid=settings.grid, area=area,
                start_date=start, end_date=end, platforms=platforms,
                maximum_bytes=settings.maximum_file_bytes,
                maximum_memberships=settings.maximum_memberships)
            run.bytes_scanned += processed.bytes_read
            if run.bytes_scanned > settings.maximum_run_bytes:
                raise ValueError("Drive run exceeds the configured byte limit")
            shapes = {cell_id: cell_from_id(cell_id, settings.grid)
                      for ids in processed.daily_cell_sets.values() for cell_id in ids}
            run.merge({"source_id": processed.source_id, "file_id": file.file_id,
                "version": processed.source_version, "sha256": processed.sha256,
                "bytes_read": processed.bytes_read, "rows_seen": processed.rows_seen,
                "rows_used": processed.rows_used}, processed.daily_cell_sets, shapes)
            run.rows_seen += processed.rows_seen
            run.rows_used += processed.rows_used
            if sum(map(len, run.day_cells.values())) > settings.maximum_memberships:
                raise ValueError("processed memberships exceed the configured limit")
    return run


def _make_cell_release_metadata(settings, release_id, area_id, area, start, end,
                                platforms, run: CellRunData):
    day_states = {}
    current = start
    while current < end:
        day_states[current] = "coverage_unknown"
        current += timedelta(days=1)
    summaries = summarize_hotspots({day: frozenset(ids) for day, ids in run.day_cells.items()},
        release_id=release_id, area_id=area_id, start_date=start, end_date=end,
        day_states=day_states)
    catalog_hash = hashlib.sha256(settings.area_catalog_path.read_bytes()).hexdigest()
    manifest = CellReleaseManifest(release_id=release_id,
        grid_version=settings.grid.grid_version, start_date=start, end_date=end,
        grid=settings.grid,
        areas={area_id: {"name": area.name, "version": area.version,
                         "geometry": area.geometry}}, platforms=platforms,
        filter_rules={"date_window": "UTC half-open [start_date, end_date)",
            "platforms": platforms,
            "area_rule": "assign projected 10 km cell; retain when cell center is covered by the area",
            "cell_rule": "EPSG:8857; 10 km; floor with half-open edges",
            "daily_rule": "union unique cell IDs across all selected files for each UTC day",
            "coverage": "unknown; no observation-opportunity inputs were provided"},
        sources=tuple(run.sources), code_version="0.1.0", catalog_sha256=catalog_hash)
    return summaries, manifest


def _publish_cell_run(settings, release_id, run: CellRunData, summaries, manifest, started) -> None:
    initialize_cell_database(settings.storage.database_path)
    publish_cell_release(settings.storage.database_path, iter(run.cells.values()),
                         iter(summaries), manifest, settings.storage)
    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    peak_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform != "darwin":
        peak_rss *= 1024
    saved_bytes = settings.storage.database_path.stat().st_size + sum(
        item.stat().st_size for item in (settings.storage.releases_path / release_id).rglob("*")
        if item.is_file())
    print(json.dumps({"release_id": release_id, "status": "published",
        "source_bytes_scanned": run.bytes_scanned, "rows_seen": run.rows_seen,
        "rows_used": run.rows_used,
        "cell_day_memberships": sum(map(len, run.day_cells.values())),
        "unique_hotspot_cells": len(run.cells), "saved_bytes": saved_bytes,
        "peak_memory_bytes": peak_bytes, "peak_rss_bytes": peak_rss,
        "elapsed_seconds": round(time.perf_counter() - started, 3)}, sort_keys=True))


def prepare_cell_release(settings: CellPreparationSettings, release_id: str, *,
                         input_csv: Path | None = None, input_source: str | None = None,
                         input_dir: Path | None = None,
                         drive_folder_id: str | None = None, start_date: date | None = None,
                         end_date: date | None = None, area_id: str | None = None,
                         platforms: tuple[str, ...] | None = None) -> None:
    """Stream selected sources and publish only two processed tables."""
    if sum((input_csv is not None, input_dir is not None, bool(drive_folder_id))) != 1:
        raise ValueError("select exactly one local CSV, local directory, or Drive folder")
    if input_source is not None and input_csv is None:
        raise ValueError("--source-id is only valid with --input-csv")
    if input_csv is not None and input_source is None:
        raise ValueError("--source-id is required with --input-csv")
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
    if input_csv is None and input_dir is None:
        run = _scan_drive_inputs(settings, drive_folder_id, area, selected_start,
                                 selected_end, selected_platforms)
    else:
        run = _scan_local_inputs(settings, release_id, input_csv, input_source, input_dir,
                                 area, selected_area_id, selected_start, selected_end,
                                 selected_platforms)
    summaries, manifest = _make_cell_release_metadata(settings, release_id, selected_area_id,
        area, selected_start, selected_end, selected_platforms, run)
    _publish_cell_run(settings, release_id, run, summaries, manifest, started)


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
        if args.input_csv or args.input_dir or args.drive_folder_id:
            prepare_cell_release(load_cell_settings(args.settings), args.release_id,
                input_csv=args.input_csv, input_source=args.source_id,
                input_dir=args.input_dir,
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
