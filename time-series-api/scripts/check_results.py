"""Check a published release and its saved source files."""

import argparse
import hashlib
import json
from collections.abc import Sequence
from pathlib import Path

from app.models import load_settings
from app.sources import _read_progress, read_source
from app.storage import load_release

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", type=Path, default=PROJECT_ROOT / "config" / "settings.json")
    parser.add_argument("--release-id", required=True)
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


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_arguments(argv)
    try:
        result = check_release(load_settings(args.settings), args.release_id)
    except Exception as error:
        print(json.dumps({"status": "failed", "message": str(error)}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
