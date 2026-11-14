#!/usr/bin/env python3
"""Merge normalized archive and near-real-time files per sensor."""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INPUT_ROOT = ROOT / "processed" / "normalized"
OUTPUT_ROOT = ROOT / "processed" / "by_sensor"
REPORT_ROOT = ROOT / "reports"

GROUPS = {
    "MODIS": "01_MODIS_C6",
    "VIIRS_SNPP": "02_VIIRS_SNPP_C2",
    "VIIRS_NOAA20": "03_VIIRS_NOAA20_C2",
    "VIIRS_NOAA21": "04_VIIRS_NOAA21_C2",
}


def merge_group(name: str, folder: str) -> dict:
    files = sorted((INPUT_ROOT / folder).glob("*.csv"))
    archive = [path for path in files if "archive" in path.name]
    nrt = [path for path in files if "near_real_time" in path.name]
    if len(archive) != 1 or len(nrt) != 1:
        raise ValueError(f"Expected one archive and one NRT file for {name}: {files}")

    output = OUTPUT_ROOT / f"{name}_south_america_all_available.csv"
    output.parent.mkdir(parents=True, exist_ok=True)
    rows = 0
    headers = None
    with output.open("w", encoding="utf-8", newline="") as out:
        writer = None
        for index, source in enumerate([archive[0], nrt[0]]):
            with source.open("r", encoding="utf-8", newline="") as source_handle:
                reader = csv.reader(source_handle)
                source_header = next(reader)
                if headers is None:
                    headers = source_header
                    writer = csv.writer(out, lineterminator="\n")
                    writer.writerow(headers)
                elif source_header != headers:
                    raise ValueError(f"Header mismatch in {source}")
                for row in reader:
                    writer.writerow(row)
                    rows += 1

    return {
        "sensor_group": name,
        "archive_file": archive[0].relative_to(ROOT).as_posix(),
        "near_real_time_file": nrt[0].relative_to(ROOT).as_posix(),
        "output_file": output.relative_to(ROOT).as_posix(),
        "rows_written": rows,
        "columns": headers,
        "archive_before_nrt": True,
        "size_bytes": output.stat().st_size,
    }


def main() -> None:
    results = [merge_group(name, folder) for name, folder in GROUPS.items()]
    REPORT_ROOT.mkdir(exist_ok=True)
    report = {
        "generated_at_utc": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "scope": "normalized South America files; archive and NRT merged per sensor group",
        "files": results,
    }
    output = REPORT_ROOT / "sensor_merge_manifest.json"
    output.write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(f"Wrote {output.relative_to(ROOT)} for {len(results)} sensor groups")


if __name__ == "__main__":
    main()
