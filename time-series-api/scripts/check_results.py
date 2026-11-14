"""Check a published release and its saved source files."""

import argparse
import hashlib
import json
import sqlite3
from contextlib import closing
from collections.abc import Sequence
from pathlib import Path

from app.cells import CellRecord, DailyHotspotSummary, CellPreparationSettings, load_cell_settings
from app.models import load_settings
from app.sources import _read_progress, read_source
from app.storage import (
    _cell_json, _read_connection, load_release, read_cell_manifest,
    read_hotspot_cells, read_hotspot_summary,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", type=Path, default=PROJECT_ROOT / "config" / "settings.json")
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--processed", action="store_true")
    return parser.parse_args(argv)


def check_release(settings, release_id: str) -> dict[str, object]:
    manifest = load_release(settings.storage.database_path, release_id)
    progress = _read_progress(settings.storage.staging_path)
    indexed = {item.source_file_id: item for item in manifest.source_files}
    row_counts = {}
    for source_id, source in indexed.items():
        entry = next((value for value in progress.values()
                      if value.get("source") == source.source_id
                      and value.get("start_date") == source.start_date.isoformat()
                      and value.get("end_date") == source.end_date.isoformat()
                      and value.get("bbox") == ",".join(map(str, settings.downloads.bbox))), None)
        if entry is None:
            raise ValueError("release source is missing from download progress")
        if Path(entry["file"]).name != entry["file"]:
            raise ValueError("release source path is unsafe")
        path = settings.storage.staging_path / entry["file"]
        if path.is_symlink() or not path.is_file():
            raise ValueError("release source path is unsafe")
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != source.sha256 or digest != entry.get("sha256"):
            raise ValueError("release source hash does not match")
        row_ids = set()
        for batch in read_source(path, source, batch_size=1000):
            row_ids.update(item.source_row_id for item in batch.observations)
            if len(row_ids) > settings.api.query_limits["maximum_input_rows"]:
                raise ValueError("source rows exceed the configured input limit")
        selected = set(manifest.source_selection["rows"].get(source_id, ()))
        if not selected.issubset(row_ids):
            raise ValueError("release selection names a missing source row")
        row_counts[source_id] = len(row_ids)
    return {"release_id": release_id, "source_files": len(indexed),
            "rows_checked": sum(row_counts.values()), "row_counts": row_counts,
            "status": "passed"}


def check_processed_release(settings: CellPreparationSettings, release_id: str) -> dict[str, object]:
    """Check processed metadata, exact table names, references, and data hash."""
    manifest = read_cell_manifest(settings.storage.releases_path, release_id)
    with closing(_read_connection(settings.storage.database_path)) as connection:
        table_names = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        if table_names != {"hotspot_cell", "daily_hotspot_summary"}:
            raise ValueError("processed database must contain exactly two user tables")
        raw_summaries = connection.execute(
            "SELECT area_id, date, active_cell_count, hotspot_cell_ids_json, status "
            "FROM daily_hotspot_summary WHERE release_id=? ORDER BY area_id, date", (release_id,),
        ).fetchall()
        summaries = tuple(DailyHotspotSummary(
            release_id=release_id, area_id=row[0], date=row[1], active_cell_count=row[2],
            hotspot_cell_ids=None if row[3] is None else tuple(json.loads(row[3])), status=row[4],
        ) for row in raw_summaries)
    expected_days = (manifest.end_date - manifest.start_date).days * len(manifest.areas)
    if len(summaries) != expected_days:
        raise ValueError("release is missing one or more day summaries")
    cell_ids = tuple(sorted({cell_id for row in summaries for cell_id in (row.hotspot_cell_ids or ())}))
    cells = read_hotspot_cells(settings.storage.database_path, manifest.grid_version, cell_ids) if cell_ids else ()
    for row in summaries:
        if row.hotspot_cell_ids is not None:
            resolved = read_hotspot_cells(settings.storage.database_path, manifest.grid_version,
                                          row.hotspot_cell_ids) if row.hotspot_cell_ids else ()
            if len(resolved) != row.active_cell_count:
                raise ValueError("summary count does not match cell shapes")
    cell_data = sorted((json.loads(_cell_json(cell)) for cell in cells), key=lambda item: item["cell_id"])
    summary_data = [json.loads(_cell_json(row)) for row in summaries]
    processed_hash = hashlib.sha256(json.dumps(
        {"cells": cell_data, "summaries": summary_data}, sort_keys=True,
        separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()
    directory = settings.storage.releases_path / release_id
    validation = json.loads((directory / "validation.json").read_bytes())
    if processed_hash != manifest.processed_sha256 or processed_hash != validation.get("processed_sha256"):
        raise ValueError("processed database hash does not match release metadata")
    if len(cells) != validation.get("cell_count") or len(summaries) != validation.get("summary_count"):
        raise ValueError("processed table counts do not match validation metadata")
    return {"release_id": release_id, "cell_count": len(cells),
            "summary_count": len(summaries), "processed_sha256": processed_hash,
            "status": "passed"}


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_arguments(argv)
    try:
        settings = load_cell_settings(args.settings) if args.processed else load_settings(args.settings)
        result = (check_processed_release(settings, args.release_id) if args.processed
                  else check_release(settings, args.release_id))
    except Exception as error:
        print(json.dumps({"status": "failed", "message": str(error)}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
