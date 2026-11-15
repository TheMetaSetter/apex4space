"""Check a published release and its saved source files."""

import argparse
import hashlib
import json
import sqlite3
import sys
from contextlib import closing
from collections.abc import Sequence
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", type=Path, default=PROJECT_ROOT / "config" / "settings.json")
    parser.add_argument("--release-id")
    parser.add_argument("--processed", action="store_true")
    parser.add_argument("--schema2-release-dir", type=Path)
    args = parser.parse_args(argv)
    if not args.release_id and not args.schema2_release_dir:
        parser.error("--release-id or --schema2-release-dir is required")
    return args


def _firms_logical_hashes(connection):
    tables = {
        "daily_hotspot_summary": ("release_id,date,area_id,active_cell_count,status,input_state", "release_id,date"),
        "hotspot_cell": ("grid_version,cell_id,column_index,row_index,min_x_m,min_y_m,max_x_m,max_y_m,center_longitude,center_latitude,geometry_json", "grid_version,cell_id"),
        "hotspot_cell_day": ("release_id,date,grid_version,cell_id", "release_id,date,grid_version,cell_id"),
    }
    output = []
    for name, (fields, order) in tables.items():
        count = connection.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
        digest = hashlib.sha256(b"apex4space.firms.logical.v1\0" + name.encode() + b"\0" + count.to_bytes(8, "big"))
        for row in connection.execute(f"SELECT {fields} FROM {name} ORDER BY {order}"):
            raw = json.dumps(row, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
            digest.update(len(raw).to_bytes(8, "big")); digest.update(raw)
        output.append({"name": name, "rows": count, "sha256": digest.hexdigest()})
    payload = {"hash_version": "apex4space.firms.logical.v1", "schema_version": 2,
        "grid_policy_version": "firms-ease-10km-v2", "reduction_policy_version": "union-valid-cell-day-v1",
        "tables": sorted(output, key=lambda row: row["name"])}
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    return payload, hashlib.sha256(raw).hexdigest()


def check_firms_release(directory: Path) -> dict[str, object]:
    """Independently verify a schema-2 database without loading rows into lists."""
    directory = directory.resolve(strict=True)
    manifest = json.loads((directory / "manifest.json").read_bytes())
    validation = json.loads((directory / "validation.json").read_bytes())
    if manifest.get("schema_version") != 2 or len(manifest.get("release_id", "")) != 64:
        raise ValueError("schema-2 release metadata is invalid")
    sources = manifest.get("sources", [])
    if not sources or any(len(item.get("sha256", "")) != 64 for item in sources):
        raise ValueError("source hash inventory is missing or invalid")
    source_hashes = sorted({item["sha256"] for item in sources})
    release = {"schema_version": 2, "grid_policy_version": "firms-ease-10km-v2",
        "reduction_policy_version": "union-valid-cell-day-v1", "source_sha256s": source_hashes}
    release_id = hashlib.sha256(json.dumps(release, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()).hexdigest()
    if release_id != manifest["release_id"]:
        raise ValueError("content release ID does not match source hashes")
    db = directory / "database.sqlite3"
    with closing(sqlite3.connect(db.as_uri() + "?mode=ro", uri=True)) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        if connection.execute("PRAGMA user_version").fetchone()[0] != 2:
            raise ValueError("SQLite schema version is not 2")
        names = sorted(row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"))
        if names != ["daily_hotspot_summary", "hotspot_cell", "hotspot_cell_day"]:
            raise ValueError("schema-2 database must contain exactly three processed tables")
        columns = {
            "daily_hotspot_summary": "release_id,date,area_id,active_cell_count,status,input_state",
            "hotspot_cell": "grid_version,cell_id,column_index,row_index,min_x_m,min_y_m,max_x_m,max_y_m,center_longitude,center_latitude,geometry_json",
            "hotspot_cell_day": "release_id,date,grid_version,cell_id",
        }
        if any(",".join(row[1] for row in connection.execute(f"PRAGMA table_info({table})")) != expected
               for table, expected in columns.items()):
            raise ValueError("schema-2 table columns do not match the processed contract")
        indexes = sorted(row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='index' AND sql IS NOT NULL"))
        if indexes != ["hotspot_cell_center", "hotspot_cell_day_cell_date"] or connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("database indexes or SQLite integrity check failed")
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise ValueError("database contains a foreign-key violation")
        mismatches = connection.execute("SELECT count(*) FROM daily_hotspot_summary d WHERE d.release_id!=? OR d.active_cell_count!=(SELECT count(*) FROM hotspot_cell_day m WHERE m.release_id=d.release_id AND m.date=d.date)", (release_id,)).fetchone()[0]
        start, end, days = connection.execute("SELECT min(date),max(date),count(*) FROM daily_hotspot_summary").fetchone()
        if mismatches or start != manifest["date_start"] or end != manifest["date_end"] or days != (date.fromisoformat(end) - date.fromisoformat(start)).days + 1:
            raise ValueError("daily counts or dense date coverage do not match manifest")
        hashes, logical = _firms_logical_hashes(connection)
    if hashes != manifest.get("table_hashes") or logical != manifest.get("logical_sha256") or logical != validation.get("logical_sha256"):
        raise ValueError("logical table hashes do not match release metadata")
    if manifest["rows_read"] != manifest["rows_assigned"] or sum(item["rows_read"] for item in sources) != manifest["rows_read"]:
        raise ValueError("source row accounting does not reconcile")
    return {"release_id": release_id, "rows_read": manifest["rows_read"],
        "cell_count": hashes["tables"][1]["rows"], "membership_count": hashes["tables"][2]["rows"],
        "daily_count": days, "logical_sha256": logical, "status": "passed"}


def check_release(settings, release_id: str) -> dict[str, object]:
    from app.sources import _read_progress, read_source
    from app.storage import load_release
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


def check_processed_release(settings, release_id: str) -> dict[str, object]:
    """Check processed metadata, exact table names, references, and data hash."""
    from app.cells import DailyHotspotSummary
    from app.storage import _cell_json, _read_connection, read_cell_manifest, read_hotspot_cells
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
        if args.schema2_release_dir:
            result = check_firms_release(args.schema2_release_dir)
        elif not args.release_id:
            raise ValueError("--release-id is required for the schema-1 checker")
        else:
            if str(PROJECT_ROOT) not in sys.path:
                sys.path.insert(0, str(PROJECT_ROOT))
            from app.cells import load_cell_settings
            from app.models import load_settings
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
