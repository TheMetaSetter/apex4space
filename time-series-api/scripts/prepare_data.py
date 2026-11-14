"""Prepare and publish a source-only data release."""

import argparse
import hashlib
import json
from collections.abc import Iterator, Sequence
from datetime import date, datetime, timezone
from pathlib import Path
from pydantic import TypeAdapter

from app.models import ReleaseRecord, ReleaseSummary, SourceBatch, ValidationReport, load_settings
from app.sources import _downloaded_record, _read_progress, read_source, select_source_records
from app.storage import initialize_database, publish_release

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_PLATFORMS = {
    "MODIS": ("Aqua", "Terra"), "VIIRS_SNPP": ("Suomi-NPP",),
    "VIIRS_NOAA20": ("NOAA-20",), "VIIRS_NOAA21": ("NOAA-21",),
}


def parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", type=Path, default=PROJECT_ROOT / "config" / "settings.json")
    parser.add_argument("--release-id", required=True)
    return parser.parse_args(argv)


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
        prepare_release(load_settings(args.settings), args.release_id)
    except Exception as error:
        print(f"Preparation failed: {error}")
        return 1
    print(f"Published source-only release: {args.release_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
