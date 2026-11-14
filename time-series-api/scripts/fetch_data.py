"""Fetch configured, bounded FIRMS windows."""

import argparse
from pathlib import Path
from collections.abc import Sequence

from app.models import load_settings
from app.sources import fetch_windows

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", type=Path, default=PROJECT_ROOT / "config" / "settings.json")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_arguments(argv)
    try:
        settings = load_settings(args.settings)
        records = tuple(fetch_windows(settings))
    except Exception as error:
        print(f"Fetch failed: {error}")
        return 1
    for record in records:
        print(f"Saved {record.source_file_id} ({record.sha256})")
    print(f"Completed windows: {len(records)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
